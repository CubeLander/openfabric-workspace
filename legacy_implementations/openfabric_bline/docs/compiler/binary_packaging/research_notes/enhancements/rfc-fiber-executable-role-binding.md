# RFC: FiberOp to Executable Role Binding

## Status

Proposed for review.

## Summary

The experimental stream/fiber compiler branch now has a flat `FiberOp` layer
that can describe the full GEMM tile forest:

```text
StreamPlan
  -> Fiber
  -> FiberOp[]
```

Each `FiberOp` is already intended to be block-grain semantic work:

```text
fragment_sram_read
fragment_route_recv
accumulator_prepare
gemm_update
finalize_accumulator
epilogue_relu
store_fragment
```

This RFC proposes the next B-line layer:

```text
FiberOp
  -> ExecutableFiberOp
  -> future target/profile template binding
```

The goal is to bind flat fiber operations to executable roles directly, without
going through `TileMicroBlock` as a permanent trunk abstraction.

The A-line compatibility probe may continue comparing against the old
`TileMicroBlock` shape, but B-line executable lowering must not depend on
`TileMicroBlock` or old micro-block kinds as the semantic source of truth.

## Current State

### Current production executable path

The current production path is:

```text
ProcessorTileProgram
  -> TileMicroBlock
  -> TileMicroOpProgram
  -> Dfu3500TemplateBoundProgram
  -> ProgramNodes / Packing / ASM / ABI / BinRows
```

`TileMicroOp` looks generic, but its source contract is old-block-shaped:

```text
TileMicroOp
  source_tile_micro_block_id
  source_tile_micro_block_kind
  role
  loop_region_id
  loop_instance_key
  input_refs / output_refs
  input_visibility_refs / output_visibility_refs
```

The current DFU3500 legacy template binder resolves templates from
`source_tile_micro_block_kind`, not from an operation-level executable role.

Currently supported legacy GEMM micro-block kinds are:

```text
accumulator_prepare
route_source_materialize
route_forward
compute_update
tile_store
```

### Current stream/fiber branch

The experimental branch under:

```text
compiler/gpdpu_compiler/core/stream_compiler
```

already has:

```text
stream.py
  StreamPlan
  StreamAction
  StreamValue

fiber.py
  Fiber
  FiberOp
  FiberDependency
  FragmentRef

blocks.py
  FiberBlockProjection
  validate_fiber_block_projection()
  summarize_fiber_block_projections()
  probe_tile_micro_block_compat()
```

The validation branch currently proves:

```text
64 fibers
1024 block-shaped FiberOps
960 dependencies
all dependency proofs satisfied
```

The compatibility probe maps most fiber operations to old micro-block-like
roles:

```text
fragment_sram_read     -> route_source_materialize
fragment_route_recv    -> route_forward-ish validation view
accumulator_prepare    -> accumulator_prepare
gemm_update            -> compute_update
store_fragment         -> tile_store
```

But it reports:

```text
finalize_accumulator   -> no old explicit micro-block kind
epilogue_relu          -> no old explicit micro-block kind
```

This is expected.  It indicates that the old path hid finalize / epilogue inside
fused templates or downstream store/compute behavior.  The new fiber model is
more explicit.

## Problem

If B-line executable lowering reuses the old path directly:

```text
FiberOp
  -> FiberBlockProjection
  -> TileMicroBlock-compatible row
  -> TileMicroOp
```

then the refactor inherits the old technical debt:

```text
1. finalize_accumulator has no explicit old slot;
2. epilogue_relu has no explicit old slot;
3. route_forward mixes sender-executed physical behavior with endpoint
   visibility semantics;
4. template selection remains keyed by old micro-block kind;
5. new flat FiberOp semantics get compressed back into legacy categories.
```

That would make the new pipeline look cleaner while still preserving the old
semantic bottleneck.  The B-line needs a direct executable role layer.

## Design Goals

### Goal 1: FiberOp remains the semantic source

`FiberOp` is the unit that says what must happen:

```text
read / receive an operand fragment
prepare accumulator
perform one GEMM K update
finalize accumulator
run local epilogue
store output fragment
```

The executable layer must reference:

```text
source_fiber_id
source_fiber_op_id
source_fiber_op_kind
```

It must not reference:

```text
source_tile_micro_block_id
source_tile_micro_block_kind
```

### Goal 2: Executable roles are target-neutral enough to review

The role layer should name executable intent without encoding `inst_t` bytes or
vendor CSV paths.

Example:

```text
compute_core:gemm_update
epilogue:relu
operand_route_recv:A
```

These are closer to executable work than high-level tensor ops, but still above
DFU3500 instruction layout.

### Goal 3: finalize / epilogue stay explicit

Do not fold:

```text
finalize_accumulator
epilogue_relu
```

into:

```text
compute_update
tile_store
```

just to match the old path.

If DFU3500 legacy templates do not yet support these roles directly, mark them
as symbolic / unsupported in template binding.  Do not hide them.

### Goal 4: Template binding is role-based

Future target binding should consume:

```text
ExecutableFiberOp.role
```

not:

```text
TileMicroBlock.block_kind
```

The legacy DFU3500 binder may temporarily use old templates as implementation
source material, but that should be a target-profile decision below the role
layer.

## Proposed Data Model

### `ExecutableFiberOp`

```python
@dataclass(frozen=True)
class ExecutableFiberOp:
    id: str
    stream_id: str
    source_fiber_id: str
    source_fiber_op_id: str
    source_fiber_op_kind: str
    role: str
    placement: str
    loop_axis: str | None = None
    loop_instance_key: str | None = None
    input_fragments: tuple[FragmentRef, ...] = ()
    output_fragments: tuple[FragmentRef, ...] = ()
    visibility_refs: tuple[str, ...] = ()
    dependency_source_ids: tuple[str, ...] = ()
    proof_summary: dict[str, object] = field(default_factory=dict)
    attrs: dict[str, object] = field(default_factory=dict)
```

Notes:

```text
source_fiber_op_id
  provides provenance back to the semantic flat fiber op.

role
  is the executable role consumed by future template binding.

placement / loop_axis / loop_instance_key
  preserve loop/subtask placement information without requiring TileMicroBlock.

visibility_refs
  preserves the selected StreamPlan visibility suffix where relevant.

dependency_source_ids / proof_summary
  optionally reference validation proof; they do not become a second dependency
  graph authority.
```

### `FiberExecutableProgram`

```python
@dataclass
class FiberExecutableProgram:
    source_ir: str
    executable_ops: dict[str, ExecutableFiberOp]
    fiber_op_to_executable_op: dict[str, str]
    per_stream_executable_ops: dict[str, tuple[str, ...]]
```

Validation:

```text
every FiberOp maps to exactly one ExecutableFiberOp
every ExecutableFiberOp references a valid FiberOp
all required dependency proofs are satisfied before executable role emission
role counts match expected GEMM forest shape
```

## Role Mapping

Initial direct mapping:

```text
FiberOp kind              Executable role
------------------------------------------------------
fragment_sram_read        operand_materialize:<role>
fragment_route_recv       operand_route_recv:<role>
fragment_route_push       operand_route_push:<role>
accumulator_prepare       accumulator_prepare
gemm_update               compute_core:gemm_update
finalize_accumulator      accumulator_finalize
epilogue_relu             epilogue:relu
store_fragment            tile_store
```

`<role>` is derived from the fragment operand role, currently `A` or `B`.

For example:

```text
fragment_sram_read output=A(m0,k0)
  -> operand_materialize:A

fragment_route_recv output=B(k0,n1)
  -> operand_route_recv:B
```

## Lowering Algorithm

Input:

```text
Fiber[]
optional FiberBlockProjection[] only for validation proof summary
```

Algorithm:

```text
for each fiber:
  for each fiber_op in fiber.ops:
    ensure dependencies are proven if projection report is provided
    role = executable_role_for_fiber_op(fiber_op)
    emit ExecutableFiberOp(
      source_fiber_op_id=fiber_op.id,
      source_fiber_op_kind=fiber_op.op,
      role=role,
      placement=fiber_op.attrs["placement"],
      loop_axis=fiber_op.attrs.get("loop_axis"),
      loop_instance_key=f"k{fiber_op.attrs['k_block']}" if present,
      input_fragments=fiber_op.inputs,
      output_fragments=fiber_op.outputs,
      visibility_refs=fiber_op.attrs.get("stream_visibility_action_id"),
    )
```

The executable role layer should not call the A-line compatibility probe.

Allowed dependency on A-line:

```text
projection validation proof summary
```

Forbidden dependency on A-line:

```text
compat old block kind mapping
TileMicroBlock-like rows
```

## Expected First Output

For current GEMM demo:

```text
fibers = 64
executable_ops = 1024
```

Expected role counts:

```text
accumulator_prepare       64
operand_materialize:A     64
operand_materialize:B     64
operand_route_recv:A      192
operand_route_recv:B      192
compute_core:gemm_update  256
accumulator_finalize      64
epilogue:relu             64
tile_store                64
```

Aggregated by broader role family:

```text
operand_materialize       128
operand_route_recv        384
compute_core              256
accumulator_prepare       64
accumulator_finalize      64
epilogue                  64
tile_store                64
```

## Template Binding Implications

### Short term

Do not bind to DFU3500 templates yet.

First implementation should only produce:

```text
FiberExecutableProgram
summary report
focused check
```

### Medium term

Add:

```text
Dfu3500FiberTemplateBoundProgram
```

It should consume `ExecutableFiberOp.role`.

Possible early binding status:

```text
role                         status
----------------------------------------------------------
operand_materialize:A/B       may bind through legacy CSV source
operand_route_recv:A/B        symbolic or legacy-route-backed, TBD
compute_core:gemm_update      may bind through compute_update filtered CSV
tile_store                    may bind through legacy tile_store CSV
accumulator_prepare           may bind through legacy accumulator_prepare CSV
accumulator_finalize          symbolic / unsupported until proven
epilogue:relu                 symbolic / unsupported until proven
```

Unsupported roles must be reported explicitly.  They must not be silently folded
into other roles.

### Long term

The DFU3500 backend can choose whether an executable role maps to:

```text
1. one legacy CSV template segment;
2. a filtered subset of a legacy CSV;
3. a native generated instruction sequence;
4. a fused target-specific template;
5. an unsupported diagnostic.
```

That choice belongs below the executable role layer.

## Relationship To Existing Layers

### `TileMicroBlock`

Validation-only for B-line.  It can remain useful for A-line reports.

### `TileMicroOp`

The existing `TileMicroOp` should not be reused directly for B-line because its
source fields assume `TileMicroBlock`.

If we reuse ideas from it, reuse the concept:

```text
executable role record
```

not the exact schema.

### `Dfu3500TemplateBoundProgram`

The existing template-bound program is structurally useful:

```text
segments
instructions
role / stage attribution
unsupported records
```

But a B-line variant should source from:

```text
ExecutableFiberOp
```

not:

```text
TileMicroOp(source_tile_micro_block_kind=...)
```

## Validation Plan

### Phase 1: Symbolic executable role report

Add:

```text
compiler/gpdpu_compiler/core/stream_compiler/executable.py
```

with:

```text
ExecutableFiberOp
FiberExecutableProgram
lower_fibers_to_executable_ops()
summarize_executable_program()
```

Focused check:

```text
all FiberOps map 1:1 to ExecutableFiberOps
all expected role counts match current GEMM forest
finalize_accumulator and epilogue_relu remain explicit roles
no TileMicroBlock compat data is consumed
```

### Phase 2: Symbolic template binding report

Add role-to-template status without producing instructions:

```text
bound
symbolic
unsupported
```

Expected:

```text
accumulator_finalize symbolic/unsupported
epilogue:relu symbolic/unsupported
```

### Phase 3: DFU3500 profile binding experiment

Only after Phase 1/2 reports are stable, explore mapping executable roles to
legacy CSV source material or generated instructions.

## Risks

### Risk: creating a second `TileMicroOp`

Mitigation:

```text
Do not include source_tile_micro_block_id or source_tile_micro_block_kind.
Name provenance through source_fiber_op_id.
```

### Risk: executable roles become too target-specific

Mitigation:

```text
Keep role names executable but symbolic:
  compute_core:gemm_update
  epilogue:relu
  operand_route_recv:A

Do not encode DFU CSV names or opcodes here.
```

### Risk: finalize / epilogue block old compatibility

Mitigation:

```text
Treat this as useful exposure of old technical debt.
Do not fold roles early.
Template binding may report symbolic/unsupported roles.
```

### Risk: dependency proof becomes a second graph

Mitigation:

```text
ExecutableFiberOp may carry proof summaries, but FiberDependency remains
semantic source and StreamPlan.depends_on remains route source.
```

## Non-goals

This RFC does not propose:

```text
1. replacing production lowering immediately;
2. generating DFU binary rows from ExecutableFiberOp;
3. changing vendor serializers;
4. removing old TileMicroBlock path;
5. hiding finalize_accumulator / epilogue_relu for parity;
6. exposing executable roles to user API.
```

## Recommended Decision

Accept Phase 1:

```text
Implement symbolic FiberExecutableProgram.
Validate role counts and one-to-one FiberOp mapping.
Keep it experimental and report-only.
```

Defer:

```text
Dfu3500FiberTemplateBoundProgram
ASM/packing integration
binary row generation
finalize/epilogue concrete instruction binding
```
