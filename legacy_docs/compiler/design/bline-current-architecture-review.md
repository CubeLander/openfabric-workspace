# B-line Current Architecture Review

Status: review note
Date: 2026-06-23
Scope: `compiler/gpdpu_compiler/core`, with TT-Metal used only as a mature
architecture reference

## Summary

B-line is no longer just a flat experimental stream compiler. The current
production-facing path already has a recognizable lowering spine:

```text
ChipEnv / ChipProgram
  -> AppPlan / TaskPartitionPlan / runtime package assignment
  -> ProcessorLogicalProgram
  -> ProcessorTileProgram
  -> TileMicroOpProgram
  -> Dfu3500TemplateBoundProgram
  -> ProgramNodeProgram
  -> DFUPackingProgram
  -> ProgramAsm
  -> ProgramVendorABI
  -> ProgramBinRows
  -> ProgramBinComponents
```

This is directionally correct. It matches the TT-Metal lesson: each major
compiler product should be inspectable, serializable, cacheable, and validated
before the next layer consumes it.

The main risk is not lack of layers. The main risk is unclear authority between
layers:

- template binding is partly explicit, but binary planning still has legacy
  template and `LegacyInst` knowledge;
- hardware facts are partly in `dfu3500`, but binary constants also live in
  generic `program_bin.py`;
- `stream_compiler` is no longer the main `ChipEnv.generate()` path, but it
  still contains a large parallel universe of fiber/template/component tooling;
- simulator/resource validation is not yet a first-class stage in the compile
  pipeline.

Recommended decision:

```text
Keep the current `program_*` spine as the B-line trunk.
Freeze `stream_compiler` as a lab/compat/evidence package.
Move authority upward into explicit TemplateExpansion / PhysicalProgram records.
Add simulator/resource/replay stages beside, not inside, vendor serialization.
```

The intended authority ladder is:

```text
ChipProgram              owns frontend tensor semantics
ProcessorTileProgram     owns tile-level semantic authority
Fiber / TileMicroOp      organizes executable work
TemplateExpansion        chooses implementation templates
DfuPhysicalProgram       owns concrete physical resources and patch points
ProgramVendorABI         projects physical facts into vendor delivery rows
ProgramBinRows           plans binary row placement
ProgramBinComponents     serializes bytes
```

Fiber is therefore not the spine of B-line. It is an execution-organization
view derived from tile semantics. Template layers organize implementation,
physical-program layers organize target resources, and vendor ABI layers
organize delivery. This distinction matters because once `TemplateExpansion`
and `DfuPhysicalProgram` exist, downstream layers should project already-made
decisions rather than infer them again.

## Current State

### Frontend Is Mostly Clean

`ChipEnv` records chip-level tensor semantics:

- SRAM tensor declarations with explicit regions and offsets.
- `load` from SRAM into `LogicalDTensor`.
- `store` from `LogicalDTensor` back into SRAM.
- compute ops as `ChipOp` records.
- logical fabric loaded from the current DFU3500 chip config.

This is a good boundary. It follows the project rule that op calls should not
mutate PE programs, Tensor Core programs, subtasks, instances, or vendor rows.

The weak point is that `ChipEnv.generate()` now acts as a full pipeline
orchestrator. That is acceptable for early integration, but it should not remain
the long-term owner of every pass import and target mode.

### Op Specs Are Moving In The Right Direction

`core/op_specs` is descriptor-only: it defines semantic contracts, access
profiles, visibility profiles, executable roles, and template intent without
constructing downstream IR.

This is the right TTNN-like split. OpenFabric should extend it toward an
operation lifecycle:

```text
validate inputs
compute output TensorSpec / SRAM region requirements
compute placement/topology requirements
select lowering profile
compute structural program identity
```

Do not let op specs import builders, serializers, vendor row classes, or
compatibility evidence.

### Tile Program Is The Strongest Current IR

`ProcessorTileProgram` explicitly models:

- `TileRouteAction`
- `TileComputeAction`
- `TileStoreAction`
- tile dependencies
- tile micro-blocks
- loop regions
- visibility refs

This is the right semantic center for B-line. It is also the right place to
preserve first-class tile op chains:

```text
route/materialize operands
  -> compute tile op
  -> post tile ops
  -> store
```

The risk is naming drift. Records like `accumulator_prepare`, `compute_update`,
and `future_split` are useful as target-lowering hints, but they must not be
reinterpreted as fiber-level semantic expansion. GEMM remains one tile compute
action at the tile/fiber semantic layer; K-loop and accumulator staging are
template/physical lowering details.

Put more directly:

```text
ProcessorTileProgram is the semantic source of truth.
Fiber / TileMicroOp is a derived executable organization view.
Any mutation to tile semantics invalidates Fiber / TileMicroOp / TemplateExpansion.
```

### Template Binding Is Explicit But Not Yet Authoritative

`TileMicroOpProgram -> Dfu3500TemplateBoundProgram` is an important step. It
creates template-bound segments and instructions with provenance back to tile
micro-ops.

However, the boundary is not fully enforced yet:

- `ProgramAsm` consumes template-bound metadata, but still maps one
  `ProgramNode` to one symbolic instruction.
- `program_bin.py` imports `TemplateBoundInstruction` and `LegacyInst`.
- `program_serializer.py` still packs legacy inst rows directly for compatible
  modes.

This is a transitional state, not a stable architecture. The stable shape should
be:

```text
TileMicroOp / FiberOp
  -> TemplateExpansion
  -> DfuPhysicalProgramDescriptor
  -> ProgramVendorABI
  -> ProgramBinRows
  -> ProgramBinComponents
```

After that, binary planning must not rediscover template choice, stage
attribution, row span, local order, K-loop shape, or legacy CSV identity.

### Binary Planning Is Too Hardware-Specific For A Generic File

`program_bin.py` contains DFU3500 facts such as record sizes, capacities,
legacy base addresses, task/subtask slot counts, PE counts, and legacy GEMM
address profiles.

These facts should move under `core/dfu3500`, or behind a `Dfu3500BinaryProfile`
loaded from the chip model. This is not about future multi-backend abstraction;
it is about keeping chip facts in one place so the compiler, simulator, and
validation gates consume the same source.

### Validation Exists, But Simulator Is Missing From The Pipeline

The validation package is useful and honest: `runtime_ready` is a local
structural/package readiness claim, not a SimICT numerical proof.

What is missing is a local simulator/resource stage between IR and serializer:

```text
ProcessorTileProgram
  -> resource checker
  -> TemplateExpansion / PhysicalProgram
  -> physical descriptor checker
  -> serializer
  -> replay bundle / partner validation
```

This mirrors TT-Metal's split between mock device, functional simulator,
no-dispatch graph capture, replay, and performance estimator.

## What To Keep

Keep these as B-line trunk decisions:

- `ChipEnv` only records chip-level program facts.
- explicit SRAM `load` / `store` boundary.
- descriptor-only `op_specs`.
- `ProcessorTileProgram` with route / compute / store actions.
- flat fact-table style IRs with `to_plan()`.
- provenance fields on every downstream row.
- fail-closed status strings such as `runtime_validation_blocked`.
- local delivery contracts that distinguish package readiness from runtime
  execution proof.

## What To Change

### 1. Move Pipeline Orchestration Out Of `ChipEnv`

Add a small pipeline module:

```text
core/pipeline.py
  CompileOptions
  CompileResult
  compile_chip_program(...)
  dump_compile_result(...)
```

`ChipEnv.generate()` can remain as a compatibility wrapper:

```text
def generate(...):
    return compile_chip_program(self.program, self.chip, options).to_plan()
```

This makes it possible to run:

- `dump_only`
- `validate_only`
- `stop_after="processor_tile_program"`
- `target="dfu3500_symbolic" | "legacy_gemm_compat"`
- `simulator="resource" | "functional" | "none"`

without bloating frontend ownership.

### 2. Freeze `stream_compiler` As Evidence/Lab Until Migrated

Current `ChipEnv.generate()` does not depend on `stream_compiler`. That is good.
Keep it that way.

Suggested status:

```text
core/stream_compiler = legacy lab / evidence tooling / migration source
core/program_*       = B-line trunk
```

Useful ideas from `stream_compiler` should migrate into trunk as explicit
records or passes. Avoid growing both lines with equivalent concepts.

### 3. Introduce `DfuPhysicalProgramDescriptor`

The missing TT-Metal-like product is a structured physical program descriptor
between template binding and vendor rows:

```text
DfuPhysicalProgramDescriptor
  template_expansions
  instruction_spans
  operand_buffers
  route_resources
  runtime_patch_points
  memory_windows
  dependency_edges
  provenance_map
```

This should become the last semantic/physical authority before vendor ABI.
`ProgramVendorABI` and `ProgramBinRows` then become projections from it.

### 4. Centralize DFU3500 Hardware Facts

Move binary constants and legacy profiles out of generic binary modules:

```text
core/dfu3500/
  chip_model.py
  memory_model.py
  binary_profile.py
  legacy_profiles.py
```

The current project is DFU-first, so this is not premature multi-backend work.
It is simply enforcing one source of chip truth.

### 5. Add Simulator Stages Before Serializer

Start small:

```text
core/sim/
  target.py
  resource_checker.py
  tile_interpreter.py
  physical_descriptor_checker.py
  replay_bundle.py
```

Phase order:

1. Resource checker: shape/placement/SRAM/SPM/route/capacity.
2. Functional tile interpreter: route/compute/store semantics for selected ops.
3. Physical descriptor checker: template expansion, row provenance, patch
   values, dependency ordering.
4. Replay bundle: archive all IR dumps, binary artifacts, memory snapshots,
   simulator verdict, and SimICT verdict.

### 6. Make Provenance A Shared Schema

Every layer already carries provenance, but the fields are not yet uniform.
Add a small shared provenance schema:

```text
source_chip_op
source_tile_action
source_tile_micro_block
source_micro_op
source_template_expansion
source_vendor_row
source_binary_row
```

This will make debugging and replay artifacts dramatically easier to consume.

### 7. Normalize Layer Names Before `Program*` Becomes Noise

The current code already has many `Program`-suffixed products:

```text
ProcessorLogicalProgram
ProcessorTileProgram
TileMicroOpProgram
Dfu3500TemplateBoundProgram
ProgramNodeProgram
DFUPackingProgram
ProgramAsm
ProgramVendorABI
ProgramBinRows
ProgramBinComponents
```

This is survivable now, but it will become a collaboration cost as soon as
`DfuPhysicalProgramDescriptor` and simulator artifacts are added. The next
boundary-hardening pass should introduce a naming map with layer categories:

```text
Semantic layer:      ChipProgram, ProcessorLogicalProgram, ProcessorTileProgram
Execution layer:     TileMicroOpProgram / Fiber view
Implementation layer: TemplateExpansion / TemplateBoundProgram
Physical layer:      DfuPhysicalProgramDescriptor
Delivery layer:      ProgramVendorABI, ProgramBinRows, ProgramBinComponents
Validation layer:    ResourceCheckReport, PhysicalCheckReport, ReplayBundle
```

This does not require renaming everything immediately. It does require every
new artifact to declare which category it belongs to, so `Program` does not
become a synonym for every intermediate object.

## What Not To Do

- Do not make TT-Metal a dependency or backend substrate.
- Do not re-expand GEMM K-loop inside fiber/tile semantic IR.
- Do not make Fiber the semantic center of the compiler; it is an execution
  organization view below `ProcessorTileProgram`.
- Do not use `include_relu`-style flags for post ops.
- Do not let binary rows select templates by inspecting legacy CSV evidence.
- Do not call `runtime_ready` a numerical or SimICT proof.
- Do not introduce CUDA/CANN/multi-backend abstractions while DFU3500 is the
  current target.

## Recommended Next Phase

The best next implementation phase is not a large rewrite. It is a boundary
hardening pass:

1. Add `core/pipeline.py` and move `ChipEnv.generate()` orchestration there.
2. Add `core/dfu3500/binary_profile.py` and move record sizes/capacities/legacy
   address profile constants out of `program_bin.py`.
3. Add report-only `DfuPhysicalProgramDescriptor` populated from existing
   template-bound/asm/vendor records.
4. Add `sim/resource_checker.py` over `ProcessorTileProgram` and
   `DfuPhysicalProgramDescriptor`.
5. Add a layer naming map to the compiler docs and require new artifacts to
   declare semantic/execution/implementation/physical/delivery/validation
   category.
6. Mark `stream_compiler` as lab/evidence in a README and forbid production
   imports from it.

This sequence preserves the working delivery path while turning the current
implicit architecture into explicit contracts.
