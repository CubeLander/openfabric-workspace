# RFC: Op Lowering Specs As A Strangler Layer For MatMul Lowering

Status: Proposed for review

Date: 2026-06-17

Scope: `gpdpu_compiler.core.ops`, op-specific lowering policy, `AppPlan`,
`ProcessorLogicalProgram`, `ProcessorTaskPlan`, `ProcessorTileProgram`, and
future generic operator lowering.  This RFC intentionally excludes
`legacy_gemm_compat` byte-level replay and vendor CSV parity code from the first
implementation phase.

## Summary

The current DFU-first compiler has made the lowering pipeline explicit:

```text
ChipProgram / DTensor program
  -> AppPlan
  -> RuntimePackageAssignment
  -> ProcessorLogicalProgram
  -> ProcessorTaskPlan
  -> ProcessorTileProgram
  -> TileMicroOpProgram
  -> Dfu3500TemplateBoundProgram
  -> ProgramNodeProgram
  -> DFUPackingProgram
  -> ProgramAsm
  -> ProgramVendorABI
  -> ProgramBinRows
```

However, operator-specific knowledge is still scattered across many passes.  For
`matmul`, the same semantic decision is repeatedly rediscovered through string
checks such as:

```python
if op.op == "matmul":
    ...
if compute_kind == "gemm_k_update":
    ...
if primary_schedule_kind == "gemm_output_tile_wave":
    ...
```

This is starting to hurt architecture clarity.  `matmul` affects frontend
validation, app/fusion planning, route planning, task partitioning, tile SUMMA
lowering, micro-block roles, symbolic ASM, and template binding.  Today those
facts are spread over `ops.py`, `program_app.py`, `program_processor.py`,
`program_task.py`, `program_tile.py`, `program_packing.py`,
`program_asm.py`, `dfu3500/legacy_templates.py`, and `program_bin.py`.

This RFC proposes a strangler-pattern refactor:

```text
Introduce op-specific lowering specs.
Move matmul policy facts into MatmulOpSpec incrementally.
Keep each lowering pass responsible for emitting its own IR.
Do not move legacy GEMM binary compatibility code in the first phase.
```

The intent is to centralize operator policy without creating a cross-layer
"god object" that mutates all downstream IRs.

## Problem Statement

### Current MatMul Touch Points

`matmul` currently appears in the pipeline roughly as follows:

1. Frontend construction:

   ```text
   compiler/gpdpu_compiler/core/ops.py
   ```

   Responsibilities:

   - rank / shape / dtype validation
   - placement constraint:

     ```text
     lhs = Shard(0), Replicate()
     rhs = Replicate(), Shard(1)
     output = Shard(0), Shard(1)
     ```

   - chip op creation:

     ```text
     op = "matmul"
     lowering_hint = "dfu_summa_gemm"
     ```

2. App/fusion planning:

   ```text
   compiler/gpdpu_compiler/core/program_app.py
   ```

   Responsibilities:

   - identify `matmul` as the primary op for a GEMM fusion region
   - set:

     ```text
     primary_schedule_kind = gemm_output_tile_wave
     ```

   - attach tile-local post ops such as ReLU
   - create task partition policy:

     ```text
     required_subtask_roles =
       accumulator_prepare
       k_stream
       finalize_store
     ```

   - record GEMM accumulator state as app-local explicit state

3. Processor logical lowering:

   ```text
   compiler/gpdpu_compiler/core/program_processor.py
   ```

   Responsibilities:

   - for A operand:

     ```text
     route_kind = row_broadcast
     visibility_kind = row_visibility
     fabric_scope = row
     ```

   - for B operand:

     ```text
     route_kind = column_broadcast
     visibility_kind = column_visibility
     fabric_scope = column
     ```

4. Task planning:

   ```text
   compiler/gpdpu_compiler/core/program_task.py
   ```

   Responsibilities:

   - map GEMM output tile waves to vendor task rows
   - define launch group / task id / task name policy
   - define GEMM subtask plan:

     ```text
     subtask0 = accumulator_prepare
     subtask1 = k_stream, instances_amount = k_blocks
     subtask2 = finalize_store
     ```

5. Tile lowering:

   ```text
   compiler/gpdpu_compiler/core/program_tile.py
   ```

   Responsibilities:

   - implement current SUMMA lowering
   - choose tile sizes from DFU3500 config:

     ```text
     matmul_m = 64
     matmul_n = 64
     matmul_k = 64
     ```

   - create tile loop regions over K
   - create route actions for A/B visibility
   - create compute actions:

     ```text
     accumulator_prepare
     gemm_k_update
     ```

   - create tile micro-blocks and dependencies

6. Packing / ASM / template / binary:

   ```text
   program_packing.py
   program_asm.py
   dfu3500/legacy_templates.py
   program_bin.py
   program_serializer.py
   ```

   Responsibilities:

   - map GEMM micro-blocks to task/subtask/instance rows
   - map `gemm_k_update` to symbolic HMMAL / CAL
   - bind legacy GEMM templates in `legacy_gemm_compat`
   - emit physical instance table and vendor-compatible binary rows

### Why This Is A Problem

The repeated `matmul` / `gemm` checks are not just cosmetic.  They make it hard
to answer:

```text
What is the full lowering contract of matmul?
Which pieces are frontend semantics?
Which pieces are DFU3500 backend policy?
Which pieces are legacy GEMM compatibility hacks?
```

They also make new operators harder to add.  If `log10max`, convolution,
batched matmul, or reduce-tree operators need similar behavior, future agents
will likely copy scattered `if op.op == ...` branches into every pass.

That path recreates the old problem: behavior exists, but no single place states
the operator's lowering contract.

## Design Goal

Introduce an operator-spec layer:

```text
OpLoweringSpec
  describes operator-specific lowering policy

Lowering passes
  consume the spec and emit their own layer's IR
```

For `matmul`, this means:

```text
MatmulOpSpec owns:
  shape / dtype / placement contract
  app region policy
  logical route policy
  task partition policy
  tile lowering policy
  micro-op role policy
  symbolic op/stage policy

Passes still own:
  AppPlan object construction
  LogicalRouteEdge construction
  TileRouteAction / TileComputeAction construction
  ProgramNode / Packing / ASM / ABI / binary row construction
```

In one sentence:

> Move "what matmul requires" into `MatmulOpSpec`; keep "how this layer builds
> its IR" inside the pass for that layer.

## Non-Goals

1. This RFC does **not** move `legacy_gemm_compat` CSV/template/byte-parity logic
   in the first phase.

2. This RFC does **not** change generated GEMM binary output.

3. This RFC does **not** make op specs emit `ProcessorTileProgram`,
   `ProgramAsm`, `ProgramVendorABI`, or `ProgramBinRows` directly.

4. This RFC does **not** introduce a generic multi-backend op registry.  The
   current target remains DFU3500 / SimICT / GPDPU first.

5. This RFC does **not** redesign frontend public APIs.  Existing calls such as:

   ```python
   y = a @ b
   y = matmul(a, b)
   ```

   should continue to work.

## Proposed File Layout

Because the repository currently has:

```text
compiler/gpdpu_compiler/ops.py
```

we should not immediately create:

```text
compiler/gpdpu_compiler/ops/matmul.py
```

without first migrating the top-level `ops.py` module into a package.  That is a
larger public import change.

For the first phase, use an internal spec package:

```text
compiler/gpdpu_compiler/core/op_specs/
  __init__.py
  base.py
  matmul.py
```

Later, if desired, the public user-facing namespace can be migrated to:

```text
compiler/gpdpu_compiler/ops/
  __init__.py
  matmul.py
  elementwise.py
  reduce.py
```

but that should be a separate compatibility migration.

## Proposed Protocol

Sketch:

```python
from dataclasses import dataclass
from typing import Protocol


class OpLoweringSpec(Protocol):
    op_name: str

    def frontend_contract(self) -> FrontendOpContract: ...

    def app_region_policy(self, op: ChipOp) -> AppRegionPolicy: ...

    def logical_route_policy(self, op: ChipOp) -> LogicalRoutePolicy: ...

    def task_partition_policy(self, op: ChipOp) -> TaskPartitionPolicy: ...

    def tile_lowering_policy(self, op: ProcessorLogicalAction) -> TileLoweringPolicy: ...

    def micro_op_policy(self, role: str) -> MicroOpPolicy: ...

    def asm_policy(self, compute_kind: str) -> AsmOpPolicy: ...
```

The exact dataclass names can evolve, but the important boundary is:

```text
Spec returns policies / descriptors.
Pass constructs IR objects.
```

### Example Matmul Spec Shape

```python
@dataclass(frozen=True)
class MatmulOpSpec:
    op_name: str = "matmul"

    def frontend_contract(self) -> FrontendOpContract:
        return FrontendOpContract(
            rank=2,
            lhs_placements=(Shard(0), Replicate()),
            rhs_placements=(Replicate(), Shard(1)),
            output_placements=(Shard(0), Shard(1)),
            dtype_policy="lhs_rhs_same_dtype",
        )

    def app_region_policy(self, op: ChipOp) -> AppRegionPolicy:
        return AppRegionPolicy(
            primary_schedule_kind="gemm_output_tile_wave",
            task_partition_kind="gemm_output_tile_wave",
            required_subtask_roles=(
                "accumulator_prepare",
                "k_stream",
                "finalize_store",
            ),
            app_local_state_requirements=(...),
        )

    def logical_route_policy(self, op: ChipOp) -> LogicalRoutePolicy:
        return LogicalRoutePolicy(
            operand_routes=(
                OperandRoutePolicy(
                    operand_index=0,
                    operand_role="A",
                    route_kind="row_broadcast",
                    visibility_kind="row_visibility",
                    fabric_scope="row",
                    group_dim=0,
                    axis_name="row",
                ),
                OperandRoutePolicy(
                    operand_index=1,
                    operand_role="B",
                    route_kind="column_broadcast",
                    visibility_kind="column_visibility",
                    fabric_scope="column",
                    group_dim=1,
                    axis_name="col",
                ),
            )
        )

    def tile_lowering_policy(self, action: ProcessorLogicalAction) -> TileLoweringPolicy:
        return TileLoweringPolicy(
            lowering_kind="summa_gemm",
            template_kind="summa_gemm_64x64x64_fp16",
            loop_axis="K",
            compute_k_update_kind="gemm_k_update",
            accumulator_prepare_kind="accumulator_prepare",
        )
```

## Layering Rules

### Rule 1: Op Specs Are Declarative

Allowed:

```python
policy = MATMUL_SPEC.logical_route_policy(op)
```

Forbidden:

```python
MATMUL_SPEC.add_logical_routes(builder, op)
```

Reason:

```text
program_processor.py owns LogicalRouteEdge construction.
MatmulOpSpec only owns route policy facts.
```

### Rule 2: Passes Own Their IR

Examples:

```text
program_app.py:
  uses MatmulOpSpec.app_region_policy()
  constructs FusionRegion / TaskPartitionPolicy

program_processor.py:
  uses MatmulOpSpec.logical_route_policy()
  constructs LogicalRouteEdge / LogicalRouteStep

program_tile.py:
  uses MatmulOpSpec.tile_lowering_policy()
  constructs TilePhase / TileLoopRegion / TileMicroBlock
```

### Rule 3: Legacy Compatibility Remains Backend-Specific

Do not move these yet:

```text
legacy_gemm_micro_block_template
legacy_gemm_template_for_micro_op
Dfu3500LegacyGemmProfile
legacy GEMM inst/exeblock byte replay
vendor-compatible CBUF/MICC quirks
```

These are DFU3500 legacy backend concerns, not frontend op semantics.

Eventually `MatmulOpSpec` may expose:

```text
template_profile_hint = legacy_gemm_compat
```

but it should not know vendor CSV paths or byte packing details.

## Migration Plan

### Phase 0: Add Spec Skeleton

Add:

```text
compiler/gpdpu_compiler/core/op_specs/base.py
compiler/gpdpu_compiler/core/op_specs/matmul.py
compiler/gpdpu_compiler/core/op_specs/__init__.py
```

Define small descriptor dataclasses:

```text
FrontendOpContract
AppRegionPolicy
OperandRoutePolicy
LogicalRoutePolicy
TileLoweringPolicy
AsmOpPolicy
```

Add `MatmulOpSpec`, but do not wire it into all passes yet.

Expected result:

```text
tests pass
no binary output change
```

### Phase 1: Frontend MatMul Uses Spec

Change `core/ops.py::matmul` to ask `MatmulOpSpec.frontend_contract()`.

Move from hardcoded:

```python
supported_lhs = (Shard(0), Replicate())
supported_rhs = (Replicate(), Shard(1))
```

to:

```python
contract = MATMUL_SPEC.frontend_contract()
```

Expected result:

```text
ChipProgram output unchanged
existing frontend tests unchanged
```

### Phase 2: AppPlan Uses Spec

Change `program_app.py` so the GEMM fusion region policy is derived from:

```python
MATMUL_SPEC.app_region_policy(op)
```

Expected result:

```text
AppPlan output unchanged
tests that assert gemm_output_tile_wave still pass
```

### Phase 3: Processor Logical Routes Use Spec

Change `program_processor.py::_add_matmul_logical_routes` to use:

```python
MATMUL_SPEC.logical_route_policy(chip_op)
```

The builder still constructs `LogicalRouteEdge`.

Expected result:

```text
LogicalRouteEdge dumps unchanged
route participants / source shard refs unchanged
```

### Phase 4: Task And Tile Policies Use Spec

Change `program_task.py` / `program_tile.py` to use:

```python
MATMUL_SPEC.task_partition_policy(op)
MATMUL_SPEC.tile_lowering_policy(action)
```

This should mostly replace constants and strings, not algorithms.

Expected result:

```text
ProcessorTaskPlan unchanged
ProcessorTileProgram unchanged
binary rows unchanged
```

### Phase 5: ASM Symbolic Policy Uses Spec

Change:

```python
if compute_kind == "gemm_k_update":
    return "DFU_HMMAL_TILE", "CAL"
```

to a spec-driven table:

```python
MATMUL_SPEC.asm_policy("gemm_k_update")
```

Expected result:

```text
ProgramAsm symbolic output unchanged
legacy_gemm_compat unchanged
```

### Phase 6: Optional Public Namespace Migration

Only after internal spec refactor stabilizes:

```text
gpdpu_compiler/ops.py
  -> gpdpu_compiler/ops/__init__.py
  -> gpdpu_compiler/ops/matmul.py
```

This should be done with import compatibility tests.

## Suggested Initial Descriptor Types

```python
@dataclass(frozen=True)
class FrontendOpContract:
    rank: int
    lhs_placements: tuple[Placement, ...]
    rhs_placements: tuple[Placement, ...]
    output_placements: tuple[Placement, ...]
    dtype_policy: str
    lowering_hint: str
    execution_model: str


@dataclass(frozen=True)
class AppRegionPolicy:
    primary_schedule_kind: str
    task_partition_kind: str
    required_subtask_roles: tuple[str, ...]
    app_local_state_proof: str
    fused_post_ops_are_tile_local: bool


@dataclass(frozen=True)
class OperandRoutePolicy:
    operand_index: int
    operand_role: str
    route_kind: str
    visibility_kind: str
    fabric_scope: str
    group_dim: int
    axis_name: str


@dataclass(frozen=True)
class LogicalRoutePolicy:
    operand_routes: tuple[OperandRoutePolicy, ...]


@dataclass(frozen=True)
class TileLoweringPolicy:
    lowering_kind: str
    template_kind: str
    loop_axis: str
    accumulator_prepare_kind: str
    compute_update_kind: str
    k_loop_fold_policy: str


@dataclass(frozen=True)
class AsmOpPolicy:
    symbolic_opcode: str
    stage: str
```

Keep these dataclasses intentionally boring.  They are contracts, not clever
runtime objects.

## Expected Benefits

### 1. MatMul Contract Becomes Reviewable

Instead of hunting through many files, reviewers can open:

```text
core/op_specs/matmul.py
```

and see:

```text
frontend shape/placement constraints
app/fusion policy
route policy
task partition policy
tile policy
asm policy
```

### 2. New Ops Become Easier To Add

For `log10max`, `reduce_max`, `conv`, or `batched_matmul`, future work can add
new specs without immediately modifying every lowering pass by hand.

### 3. Passes Stay Layer-Clean

The pass-specific builders continue to own their IR:

```text
AppPlan builder owns FusionRegion.
Processor builder owns LogicalRouteEdge.
Tile builder owns TileAction / TileLoopRegion.
ASM builder owns ProgramAsmInstruction.
```

### 4. Legacy Quirks Stay Contained

`legacy_gemm_compat` remains in DFU3500 backend modules until there is a strong
reason to lift a specific piece into a generic matmul policy.

## Risks

### Risk 1: Op Spec Becomes A God Object

Mitigation:

```text
Spec returns descriptors only.
Spec must not mutate builders or emit downstream IR.
```

### Risk 2: Over-Abstraction Before More Ops Exist

Mitigation:

```text
Start with MatmulOpSpec only.
Keep descriptor dataclasses small.
Do not build a dynamic plugin registry yet.
```

### Risk 3: Breaking Existing GEMM Binary Parity

Mitigation:

```text
Each migration phase must assert current GEMM plans remain unchanged.
legacy_gemm_compat tests must continue to pass.
```

### Risk 4: Confusing Public `ops.py` With Internal Op Specs

Mitigation:

```text
Phase 0 uses internal core/op_specs package.
Public namespace migration is deferred.
```

## Tests

Add / preserve tests for:

```text
test_matmul_frontend_contract_matches_existing_behavior
test_matmul_app_region_policy_matches_existing_app_plan
test_matmul_logical_route_policy_matches_existing_routes
test_matmul_task_partition_policy_matches_existing_task_plan
test_matmul_tile_lowering_policy_matches_existing_tile_program
test_matmul_asm_policy_matches_existing_symbolic_asm
test_legacy_gemm_compat_bundle_unchanged
```

For each phase, the golden expectation should be:

```text
observable compiler plans unchanged
only source of policy facts changed
```

## Recommended First Patch

Implement Phase 0 and Phase 1 only:

```text
1. Add core/op_specs/base.py
2. Add core/op_specs/matmul.py
3. Add MATMUL_SPEC singleton
4. Change core/ops.py::matmul to use frontend contract from MATMUL_SPEC
5. Add tests proving frontend ChipProgram output remains unchanged
```

Do **not** touch:

```text
program_tile.py::_lower_matmul
dfu3500/legacy_templates.py
program_bin.py
program_serializer.py
```

This gives us the strangler root without disturbing the fragile vendor-binary
parity work.

## Open Questions

1. Should `MatmulOpSpec` live under `core/op_specs` permanently, or should it
   eventually move to public `gpdpu_compiler/ops/matmul.py` once the top-level
   `ops.py` module is migrated?

2. Should op specs be discovered through a registry:

   ```python
   OP_SPECS["matmul"]
   ```

   or imported explicitly by each pass during the first phase?

   Recommendation: explicit imports first, registry later.

3. How much DFU3500-specific policy belongs in `MatmulOpSpec`?

   Recommendation: current DFU-first placement / route / task policies can live
   in the spec, but vendor byte layout, CSV paths, and replay tables stay in
   DFU3500 backend modules.

4. Should elementwise ops get specs immediately?

   Recommendation: no.  Extract matmul first, then apply the pattern to
   `reduce_max` / log10max-related ops once the boundary is proven.

## Final Recommendation

Accept this RFC as an incremental architecture cleanup.

Use a strangler pattern:

```text
Phase 0/1:
  Add MatmulOpSpec and move frontend contract.

Phase 2/3:
  Move AppPlan and processor route policies.

Phase 4/5:
  Move task/tile/ASM policy descriptors.

Later:
  Decide whether to migrate public ops namespace.
```

The key architectural invariant is:

```text
Op specs centralize operator policy.
Lowering passes still own IR construction.
Legacy vendor compatibility remains backend-local until explicitly migrated.
```

