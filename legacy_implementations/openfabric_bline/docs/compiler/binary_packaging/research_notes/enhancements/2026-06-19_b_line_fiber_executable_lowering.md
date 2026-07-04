# B-line: FiberOp to Executable Lowering

Date: 2026-06-19
Status: active B-line design note
Scope: experimental `core/stream_compiler` branch

## Purpose

This note tracks the B-line refactor direction after the stream/fiber validation
work.

The A-line can keep probing old `TileMicroBlock` compatibility.  The B-line
should not inherit that shape as its main architecture.  It should answer:

```text
Given a flat FiberOp sequence, what is the next executable IR?
```

The guiding principle is:

```text
FiberOp is already the block-grain semantic unit.
The next layer should bind FiberOp roles to executable/template roles directly.
```

Do not route the new trunk through:

```text
FiberOp -> FiberBlock -> TileMicroBlock -> TileMicroOp
```

That path is useful as a validation bridge only.

## Current Findings

The existing executable path is:

```text
ProcessorTileProgram
  -> TileMicroBlock
  -> TileMicroOpProgram
  -> Dfu3500TemplateBoundProgram
  -> ProgramNodes / Packing / ASM / ABI / BinRows
```

The current `TileMicroOp` layer is intentionally generic in wording, but its
source contract is still old-block-shaped:

```text
TileMicroOp
  source_tile_micro_block_id
  source_tile_micro_block_kind
  role
  input_refs / output_refs
  input_visibility_refs / output_visibility_refs
```

The DFU3500 legacy GEMM template binder ultimately uses old micro-block kinds:

```text
accumulator_prepare
route_source_materialize
route_forward
compute_update
tile_store
```

That explains the compatibility probe result:

```text
FiberOp accumulator_prepare   -> old accumulator_prepare
FiberOp fragment_sram_read    -> old route_source_materialize
FiberOp fragment_route_recv   -> old route_forward-ish validation view
FiberOp gemm_update           -> old compute_update
FiberOp store_fragment        -> old tile_store

FiberOp finalize_accumulator  -> no old explicit slot
FiberOp epilogue_relu         -> no old explicit slot
```

This is not a missing semantic capability in the new model.  It is evidence that
the old path hid finalize/epilogue inside fused templates or later store/compute
behavior.

## B-line Direction

Introduce an executable role layer that consumes flat fibers directly:

```text
Fiber
  -> FiberExecutableProgram
  -> Dfu3500FiberTemplateBoundProgram
  -> later packing / ASM bridge
```

Names are provisional.  The important design is the dependency direction:

```text
Executable role records reference source_fiber_op_id.
They do not reference TileMicroBlock.
```

Minimum executable role shape:

```text
ExecutableFiberOp
  id
  stream_id
  source_fiber_id
  source_fiber_op_id
  source_fiber_op_kind
  role
  placement
  loop_axis?
  loop_instance_key?
  input_fragments
  output_fragments
  visibility_refs
  dependency_proof_refs
  attrs
```

This can be implemented as a separate experimental module, not wired to
production.

## Role Mapping

Initial role mapping should be direct and explicit:

```text
fragment_sram_read
  -> operand_materialize:<A|B>

fragment_route_recv
  -> operand_route_recv:<A|B>

fragment_route_push
  -> operand_route_push:<A|B>

accumulator_prepare
  -> accumulator_prepare

gemm_update
  -> compute_core:gemm_update

finalize_accumulator
  -> accumulator_finalize

epilogue_relu
  -> epilogue:relu

store_fragment
  -> tile_store
```

The key difference from old `TileMicroOp` is that finalize and epilogue are not
forced into `compute_update` or `tile_store`.

## Template Binding Policy

The next template-binding layer should bind by executable role, not old block
kind:

```text
ExecutableFiberOp.role
  -> target/profile template binding
```

For DFU3500 legacy GEMM compatibility, some roles may temporarily map to old
CSV-derived templates:

```text
operand_materialize:A/B
  may use legacy route_source_materialize template source

operand_route_recv / operand_route_push
  may use legacy route_forward or source materialization templates depending on
  operand and physical execution model

compute_core:gemm_update
  may use legacy compute_update filtered template

tile_store
  may use legacy tile_store template
```

But the binding should report unsupported or symbolic status for roles that do
not yet have a proven DFU3500 template:

```text
accumulator_finalize
epilogue:relu
```

Do not hide these roles by folding them into old block kinds during B-line
lowering.

## Relationship To A-line Compatibility Probe

A-line:

```text
FiberBlockProjection / compat probe
  asks "how close are we to the old TileMicroBlock shape?"
```

B-line:

```text
FiberExecutableProgram
  asks "what executable roles does the new flat FiberOp model require?"
```

Both can exist, but only B-line should become the new trunk.

## Suggested Next Implementation Slice

Start tiny:

```text
compiler/gpdpu_compiler/core/stream_compiler/executable.py
```

Add:

```text
ExecutableFiberOp
FiberExecutableProgram
lower_fibers_to_executable_ops(fibers, projections?)
summarize_executable_program(program)
```

The lowering may consume projection validation reports only to ensure all
dependencies are proven.  It should not consume compat probe rows.

First check:

```text
64 fibers
1024 executable ops
role counts:
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

This mirrors the current forest while preserving finalize/epilogue as explicit
roles.

## Implementation Checkpoint

Current experimental implementation:

```text
compiler/gpdpu_compiler/core/stream_compiler/executable.py
  ExecutableFiberOp
  FiberExecutableProgram
  lower_fibers_to_executable_ops(fibers, projections?)
  summarize_executable_program(program)

compiler/tools/check_stream_compiler_executable.py
  validates B-line role counts and 1:1 source FiberOp mapping
```

The implementation consumes optional `FiberBlockProjection` only for proof
summaries:

```text
FiberDependency / StreamPlan proof summaries may be attached.
TileMicroBlock-compatible rows and compat probe mappings are not consumed.
```

Current check command:

```bash
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_executable.py
```

Current validation target:

```text
executable_ops = 1024
unique_source_fiber_op_count = 1024
forbidden_tile_micro_block_field_count = 0
proof_status_counts = {satisfied: 960}
```

Most importantly, these explicit roles must remain visible:

```text
accumulator_finalize = 64
epilogue:relu = 64
```

## Open Questions

1. Should `fragment_route_recv` and `fragment_route_push` both become executable
   roles immediately, or should B-line initially model only endpoint visibility
   and leave physical sender execution for a later DFU pass?

2. Should template binding reject `accumulator_finalize` / `epilogue:relu`, or
   mark them as symbolic executable roles until a concrete DFU instruction
   template is identified?

3. Should `ExecutableFiberOp` dependency data reference:

```text
source FiberDependency ids
or DependencyProof ids from projection validation?
```

Current preference:

```text
reference FiberDependency ids as semantic source;
optionally attach proof summary for validation.
```

4. Where should DFU3500 legacy template binding consume the new roles?

Possible staging:

```text
ExecutableFiberOp
  -> symbolic role report only
  -> later Dfu3500FiberTemplateBoundProgram
  -> later adapter into existing ProgramAsm/packing, if still useful
```

## Non-goals

Do not:

```text
1. construct TileMicroBlock from B-line;
2. fold finalize_accumulator or epilogue_relu into store just for legacy parity;
3. modify vendor serializers;
4. replace production lowering before the experimental executable role report is stable.
```

## Symbolic Role Binding Checkpoint

Added a narrow B-line binding report layer:

```text
compiler/gpdpu_compiler/core/stream_compiler/binding.py
  SymbolicRoleBinding
  SymbolicRoleBindingProgram
  bind_executable_roles_symbolically(program)
  summarize_role_binding_program(program)

compiler/tools/check_stream_compiler_role_binding.py
  validates role-based symbolic binding counts
```

This layer consumes only:

```text
FiberExecutableProgram
ExecutableFiberOp.role
ExecutableFiberOp.source_fiber_op_id
ExecutableFiberOp.source_fiber_op_kind
```

It must not consume:

```text
TileMicroBlock-compatible rows
old block-kind mappings
ASM / packing / ABI rows
vendor serializers
```

Current symbolic DFU3500 legacy profile report for the GEMM demo:

```text
bindings = 1024
legacy_template_candidate = 896
symbolic_unsupported = 128

legacy candidates:
  accumulator_prepare       64
  route_source_materialize  128
  route_forward             384
  compute_update            256
  tile_store                 64

explicit unsupported roles retained:
  accumulator_finalize       64
  epilogue:relu              64
```

The important architectural signal is that `accumulator_finalize` and
`epilogue:relu` remain first-class executable roles.  They are reported as
symbolic/unsupported instead of being folded into `compute_update` or
`tile_store` to satisfy the old backend shape.

Current check command:

```bash
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_role_binding.py
```

## Symbolic Template Record Checkpoint

Added the next tiny B-line layer:

```text
compiler/gpdpu_compiler/core/stream_compiler/template_records.py
  SymbolicTemplateRecord
  SymbolicTemplateRecordProgram
  lower_symbolic_bindings_to_template_records(bindings)
  summarize_template_record_program(program)

compiler/tools/check_stream_compiler_template_records.py
  validates role-derived symbolic template records
```

This layer consumes only symbolic role bindings.  It still does not emit:

```text
DFU3500 instructions
ASM
ProgramNodes
packing rows
vendor ABI rows
binary blobs
```

Current GEMM demo symbolic template-record summary:

```text
records = 1024
symbolic_report_only = 1024

template_candidate = 896
symbolic_only       = 128

stage_counts:
  pre_loop   = 64
  loop_body  = 768
  post_loop  = 192

candidate template roles:
  accumulator_prepare       64
  route_source_materialize  128
  route_forward             384
  compute_update            256
  tile_store                 64

symbolic-only executable roles:
  accumulator_finalize       64
  epilogue:relu              64
```

This is intentionally a support matrix, not a backend promise.  The useful
signal is that the future template layer can now see exactly which executable
roles already have legacy template candidates and which roles still need real
DFU3500 semantics before binary emission.

Current check command:

```bash
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_template_records.py
```

## DFU3500 Role Semantic Report Checkpoint

Implemented the Phase-2 report-only target semantics layer.  The original RFC
has been archived after the ReLU evidence split was resolved:

```text
docs/compiler/binary_packaging/research_notes/enhancements/2026-06-19_rfc-b-line-finalize-epilogue-template-semantics.archived.md
docs/compiler/binary_packaging/research_notes/enhancements/2026-06-19_relu_epilogue_vendor_evidence.md
```

New files:

```text
compiler/gpdpu_compiler/core/stream_compiler/dfu3500_semantics.py
  Dfu3500RoleSemanticRecord
  Dfu3500RoleSemanticReport
  lower_template_records_to_dfu3500_semantics(records)
  summarize_dfu3500_semantic_report(report)

compiler/tools/check_stream_compiler_dfu3500_semantics.py
  validates DFU3500 semantic evidence counts
```

Current GEMM demo semantic report:

```text
records = 1024
proven  = 960
unproven = 64

proven semantic kinds:
  accumulator_boundary       64  # accumulator_finalize, zero-instruction
  accumulator_prepare       64
  operand_materialization   128
  operand_route_visibility  384
  gemm_k_update             256
  tile_store                 64

unproven semantic kinds:
  local_elementwise_epilogue 64  # epilogue:relu
```

This layer still does not emit templates, instructions, ASM, ABI rows, or
binary blobs.  It only records target semantic evidence.  The useful signal is
now precise:

```text
accumulator_finalize is a proven zero-instruction accumulator/value boundary.
epilogue:relu is instruction-set supported but unproven for the current
3-subtask runnable package.
```

Current check command:

```bash
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_dfu3500_semantics.py
```

## Legacy Template Evidence Checkpoint

Added a read-only inspector:

```text
compiler/tools/inspect_legacy_gemm_templates.py
```

Current evidence command:

```bash
PYTHONPATH=compiler python compiler/tools/inspect_legacy_gemm_templates.py --subtask 3
```

Observed legacy GEMM `subtask3` shape:

```text
all task0..task3 subtask3 templates:
  stages = {ST:1024} per task
  ops    = {STD:1024} per task

per template:
  stages = {ST:64}
  ops    = {STD:64}
```

Implication for B-line:

```text
accumulator_finalize is not expected to have a standalone subtask3 instruction.
epilogue:relu has no explicit subtask3 template evidence and remains unproven
for the current 3-subtask package.
```

ReLU investigation was consolidated into:

```text
docs/compiler/binary_packaging/research_notes/enhancements/2026-06-19_relu_epilogue_vendor_evidence.md
```

The short version: DFU3500 can implement ReLU via max-style SIMD instructions,
and vendor `subtask4` source emits `IMM ZERO_relu` + `HMAX`; however the current
observed package has `subtask_num:3`, no active `subtask4` CSV rows, and
`subtask3` is pure `STD` store.  Do not flip `epilogue:relu` to proven from the
current store template.

## Fiber Execution Schedule Checkpoint

Added the next B-line row view:

```text
compiler/gpdpu_compiler/core/stream_compiler/schedule.py
  FiberScheduleStep
  FiberExecutionSchedule
  build_fiber_execution_schedule(executable, semantic_report)
  summarize_fiber_execution_schedule(schedule)
```

This is a flat schedule view, not a second dependency graph:

```text
one ExecutableFiberOp -> one FiberScheduleStep
```

The schedule records:

```text
source_fiber_op_id
source_order_index
stream_id
role
phase              # pre_loop / loop_body / post_loop
loop_instance_key  # k0..k3 for loop body ops
dependency_source_ids
proof_status
semantic_kind
candidate_mechanism
```

`dependency_source_ids` continue to point at source `FiberOp` ids.  The schedule
validates that they resolve, but it does not invent a new authoritative edge
table.  If a derived dependency view is needed later, collect it from schedule
rows temporarily.

Current GEMM demo schedule report:

```text
steps  = 1024
fibers = 64
steps_per_fiber = [16]
dependency_refs = 960

phase_counts:
  pre_loop  = 64
  loop_body = 768
  post_loop = 192

loop_instance_counts:
  k0 = 192
  k1 = 192
  k2 = 192
  k3 = 192

proof_status_counts:
  proven   = 960
  unproven = 64

unproven_role_counts:
  epilogue:relu = 64
```

The focused validation is:

```bash
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_schedule.py
```

This checkpoint is the handoff point for the next B-line phase: symbolic opcode
or template selection can consume schedule rows while keeping `FiberOp` as the
semantic source of truth.

## TemplateOp / BinaryLayout Checkpoint

Added report-only target-template and binary-placement views:

```text
compiler/gpdpu_compiler/core/stream_compiler/template_ops.py
  TemplateOpPlan
  TemplateOp
  TemplateOpProvenance
  InstructionIntent
  lower_schedule_to_template_ops(schedule)

compiler/gpdpu_compiler/core/stream_compiler/binary_plan.py
  BinaryLayoutPlan
  BinaryInstructionPlan
  BinaryZeroInstructionBoundary
  lower_template_ops_to_binary_layout(template_plan)
```

These layers intentionally do not emit bytes.  They make the next B-line
boundary observable:

```text
FiberExecutionSchedule
  -> TemplateOpPlan       # template content / unresolved status
  -> BinaryLayoutPlan     # symbolic placement / PC rows / zero boundaries
```

Current default GEMM+ReLU profile remains fail-closed:

```text
TemplateOps:
  total               = 1024
  concrete_template   = 896
  zero_instruction    = 64   # accumulator_finalize
  symbolic_unresolved = 64   # epilogue:relu

BinaryLayout:
  runnability_state              = layout_candidate
  instruction_rows               = 896
  zero_instruction_boundaries    = 64
  epilogue:relu instruction rows = 0
```

Added an explicit no-ReLU safe subset rather than dropping unresolved ReLU from
the default profile:

```text
build_demo_gemm_stream_plan(include_relu=False)
build_demo_fibers(plan, include_relu=False)
```

Current no-ReLU safe subset:

```text
TemplateOps:
  total             = 960
  concrete_template = 896
  zero_instruction  = 64
  unresolved        = 0

BinaryLayout:
  runnability_state           = emittable_debug
  instruction_rows            = 896
  zero_instruction_boundaries = 64
```

Focused validations:

```bash
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_template_ops.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_binary_plan.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_no_relu_safe_subset.py
```

This is still not a runnable vendor binary.  It is the first B-line
debug-emittable layout candidate, with `FiberOp` provenance preserved and
`TileMicroBlock` compatibility fields kept out of the authority path.

## Snapshot Feedback Loop Checkpoint

Added a deterministic snapshot exporter:

```text
compiler/tools/export_stream_compiler_snapshot.py
```

Example:

```bash
PYTHONPATH=compiler python compiler/tools/export_stream_compiler_snapshot.py \
  --profile gemm_no_relu \
  --out /tmp/gemm_no_relu_b_line_snapshot.json
```

Profiles:

```text
gemm_relu:
  include_relu = true
  requested_runnability_state = layout_candidate
  unresolved epilogue:relu remains visible

gemm_no_relu:
  include_relu = false
  requested_runnability_state = emittable_debug
  unresolved = 0
```

The default snapshot contains summaries only.  Passing `--include-rows` includes
full schedule, TemplateOp, and BinaryLayout rows for heavier diffing.

Focused validation:

```bash
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_snapshot_export.py
```

The exporter normalizes through JSON so dict keys and nested values round-trip
deterministically.  This is the Phase 0 feedback-loop artifact: ugly is allowed,
opaque is not.

## Debug Row Artifact Checkpoint

Added the first debug-emitter adapter:

```text
compiler/gpdpu_compiler/core/stream_compiler/debug_emit.py
  DebugRowArtifact
  emit_debug_row_artifact(layout)
  summarize_debug_row_artifact(artifact)

compiler/tools/export_stream_compiler_debug_rows.py
compiler/tools/check_stream_compiler_debug_emit.py
```

This is not a vendor binary writer.  It consumes only `BinaryLayoutPlan` and
serializes stable quasi-binary row artifacts:

```text
instruction_rows.json
zero_boundaries.json
summary.json
```

Current behavior:

```text
gemm_no_relu:
  input layout state = emittable_debug
  instruction_rows  = 896
  zero_boundaries   = 64
  diagnostics       = 0

gemm_relu:
  input layout state = layout_candidate
  debug emit refuses rows
  diagnostics = {error: 1, warning: 128}
```

Example:

```bash
PYTHONPATH=compiler python compiler/tools/export_stream_compiler_debug_rows.py \
  --profile gemm_no_relu \
  --out-dir /tmp/b_line_debug_rows
```

The debug emitter preserves TemplateOp/FiberOp provenance and explicitly keeps
`accumulator_finalize` in `zero_boundaries.json`, not in instruction rows.
`epilogue:relu` remains absent from the no-ReLU source profile and fail-closed
in the default GEMM+ReLU profile.

## Vendor-like Row Group Checkpoint

Added a report-only grouping layer:

```text
compiler/gpdpu_compiler/core/stream_compiler/vendor_groups.py
  VendorLikeRowGroupPlan
  VendorLikeRowGroup
  group_debug_rows_vendor_like(artifact)
  summarize_vendor_like_row_group_plan(plan)

compiler/tools/check_stream_compiler_vendor_groups.py
```

The grouping consumes `DebugRowArtifact`, not `TemplateOpPlan`,
`BinaryLayoutPlan`, or old `TileMicroBlock` compatibility rows.  It groups rows
by:

```text
task_id
subtask_slot
loop_instance
```

Current `gemm_no_relu` report:

```text
groups           = 24
instruction_rows = 896
zero_boundaries  = 64

task_group_counts:
  task0 = 6
  task1 = 6
  task2 = 6
  task3 = 6

subtask_group_counts:
  subtask0_accumulator_prepare = 4
  subtask1_k_stream            = 16
  subtask3_finalize_store      = 4

loop_group_counts:
  k0   = 4
  k1   = 4
  k2   = 4
  k3   = 4
  none = 8
```

The debug row exporter now writes:

```text
instruction_rows.json
zero_boundaries.json
vendor_groups.json
summary.json
```

Example:

```bash
PYTHONPATH=compiler python compiler/tools/export_stream_compiler_debug_rows.py \
  --profile gemm_no_relu \
  --out-dir /tmp/b_line_debug_rows
```

This grouping is still not a vendor serializer.  It deliberately exposes the
current global PC ordering inside vendor-shaped buckets so later passes can
decide whether to preserve, remap, or localize row numbering.

## Vendor-like Local Remap Checkpoint

Added group-local row numbering:

```text
compiler/gpdpu_compiler/core/stream_compiler/vendor_groups.py
  VendorLikeLocalRemapPlan
  VendorLikeLocalRemapGroup
  remap_vendor_like_groups_locally(plan)
  summarize_vendor_like_local_remap_plan(plan)

compiler/tools/check_stream_compiler_local_remap.py
```

The remap layer preserves global row/PC fields and adds group-local numbering:

```text
instruction row:
  global_row_index
  global_pc
  local_row_index
  local_pc

zero boundary:
  local_boundary_index
  local_pc = None
  occupies_local_instruction_row = false
```

Current `gemm_no_relu` report:

```text
groups           = 24
instruction_rows = 896
zero_boundaries  = 64

non_dense_local_pc_group_count = 0
zero_boundaries_with_pc_count  = 0
missing_global_index_count     = 0
```

The debug row exporter now also writes:

```text
vendor_local_remap.json
```

This layer is still a report.  It does not decide final vendor PC semantics; it
only makes the difference between global schedule order and group-local row
order explicit and diffable.

## Vendor Component Plan Checkpoint

Added the next report-only bridge from locally remapped vendor-like row groups
into component-shaped sections:

```text
compiler/gpdpu_compiler/core/stream_compiler/vendor_components.py
  VendorComponentPlan
  build_vendor_component_plan(remap)
  summarize_vendor_component_plan(plan)

compiler/tools/check_stream_compiler_vendor_components.py
```

The component plan currently exports JSON-shaped sections only:

```text
inst_rows
zero_boundaries
task_rows
subtask_rows
instance_rows
```

Current `gemm_no_relu` report:

```text
inst_rows       = 896
task_rows       = 4
subtask_rows    = 12
instance_rows   = 16
zero_boundaries = 64

opcode_counts:
  ACC_PREPARE              = 64
  HMMAL_OR_GEMM_UPDATE     = 256
  LOAD_OR_COPY             = 128
  ROUTE_RECV_VISIBILITY    = 384
  STD                      = 64

subtask_inst_counts:
  subtask0_accumulator_prepare = 64
  subtask1_k_stream            = 768
  subtask3_finalize_store      = 64
```

The debug row exporter now also writes:

```text
vendor_components.json
```

This is not yet `ProgramVendorABI` and not yet a serializer.  It intentionally
keeps global/local row provenance, source `TemplateOp` lineage, and zero
instruction boundaries visible so the next pass can compare component-shaped
reports against legacy vendor expectations without pretending that bytes are
ready.

### Component Capacity Instrumentation

`VendorComponentPlan` now carries a capacity report sourced from the current
DFU3500 legacy runtime limits / struct sizes:

```text
inst_rows:
  active   = 896
  capacity = 69632
  record   = 304 bytes

task_rows:
  active   = 4
  capacity = 4
  record   = 120 bytes

subtask_rows:
  active   = 12
  capacity = 32
  record   = 266328 bytes

instance_rows:
  active   = 16
  capacity = 65536
  record   = 32 bytes

zero_boundaries:
  active = 64
  occupies_binary_rows = false

exeblock_rows:
  modeled = false
  status  = not_projected_yet
```

The summary deliberately reports:

```text
modeled_component_capacity_ok = true
missing_required_component_kinds = ["exeblock_rows"]
```

This keeps the B-line honest: component-shaped reports exist, modeled sections
fit current DFU3500 capacities, and the missing exeBlock projection is visible
instead of being hidden behind an incomplete serializer-shaped artifact.

The `exeblock_rows` gap above is superseded by the following checkpoint.

### Report-only exeBlock Projection

`VendorComponentPlan` now also projects report-only `exeblock_rows` by splitting
each vendor-like task/subtask/loop bucket by `stream_id`:

```text
exeBlock key = (task_id, stream_id, subtask_slot, loop_instance)
```

For the current `gemm_no_relu` demo this yields:

```text
exeblock_rows = 384

per task:
  task0 = 96
  task1 = 96
  task2 = 96
  task3 = 96

per subtask:
  subtask0_accumulator_prepare = 64
  subtask1_k_stream            = 256
  subtask3_finalize_store      = 64

per physical PE:
  each PE has 24 local exeBlocks
  max allowed per PE = 32
```

The component capacity summary now reports:

```text
exeblock_rows:
  active   = 384
  capacity = 512
  record   = 520 bytes
  modeled  = true
  status   = report_only_stream_local_blocks

missing_required_component_kinds = []
```

This is still not an `exeBlock_conf_info_t` serializer.  The row records preserve
source instruction / zero-boundary indices, physical PE id, and PE-local block
index, but dependency edges remain explicitly marked as:

```text
dependency_policy = not_projected_yet_zeroed_report_only
binary_encoded = false
```

The next real semantic gap is exeBlock dependency projection: deciding which
stream-local block dependencies are satisfied by subtask order, loop instance
order, route visibility, or explicit predecessor/successor slots.

The dependency gap above is superseded by the following checkpoint.

### exeBlock Structural Dependency Projection

`VendorComponentPlan` now attaches report-only predecessor / successor structure
for the current sequential-K GEMM shape.  This is still not vendor
`exeBlock_conf_info_t` slot encoding; it is a proof report over the component
rows.

Current `gemm_no_relu` dependency shape:

```text
per stream:
  accumulator_prepare -> k0
  k0 -> k1
  k1 -> k2
  k2 -> k3
  k3 -> finalize_store

streams = 64
edges per stream = 5
total edges = 320
```

Proof counts:

```text
subtask_order       = 128
loop_instance_order = 192

predecessor_overflow_count = 0
successor_overflow_count   = 0
```

Each report-only exeBlock row now carries:

```text
predecessor_component_indices
successor_component_indices
dependency_proofs[]
predecessor_overflow_count
successor_overflow_count
```

The proof records intentionally keep:

```text
status = structurally_projected
binary_encoded = false
```

This means the B-line can now explain the linear stream-local execution chain,
but it still has not committed to DFU3500 predecessor / successor slot bytes.
The remaining gap is to refine this report into a vendor slot policy and to add
route/visibility dependencies once the B-line route materialization model is
ready to claim them.

### Report-only exeBlock Edge Slots

The structural dependency report now also exposes fixed-width edge slots on each
report-only exeBlock row:

```text
predecessor_slots[4]
successor_slots[4]
```

Current `gemm_no_relu` summary:

```text
exeblock_slot_shape_error_count = 0
exeblock_padded_slot_row_count  = 384
```

The slots are intentionally padded with `null` / `None` and explicitly marked as
component-index slots, not vendor row-index slots:

```text
slot_policy = report_only_padded_component_indices
slot_values_are_component_indices = true
slot_values_are_vendor_row_indices = false
```

This checkpoint makes the DFU3500 4-edge-slot constraint visible in B-line
without crossing into byte serialization.  The remaining step before real
`exeBlock_conf_info_t` rows is a slot semantic policy: decide when component
indices can be rewritten to physical vendor exeBlock row indices, how inactive
slots should be encoded, and whether route/visibility dependencies need extra
edges beyond the current stream-local chain.

### Candidate vendor row-index slots

The component-index slots are now mirrored into candidate vendor-row slots:

```text
candidate_vendor_row_index
predecessor_vendor_row_slots[4]
successor_vendor_row_slots[4]
```

Current `gemm_no_relu` summary:

```text
exeblock_candidate_vendor_row_identity_count = 384
exeblock_vendor_row_slot_shape_error_count   = 0
```

The current policy is intentionally conservative:

```text
candidate_vendor_row_index_policy = dense_component_index_identity
vendor_row_slot_policy            = candidate_dense_component_index_identity
vendor_row_slots_are_binary_encoded = false
```

This means B-line can now show a dense candidate physical row order for
report-only exeBlock dependencies, but it still has not committed to real
vendor bytes.  A future serializer must still confirm vendor row-index semantics
and choose the inactive-slot sentinel before these candidate slots become
`exeBlock_conf_info_t` fields.

### Candidate predecessor / successor endpoints

The DFU3500 `exeBlock_conf_t` predecessor / successor fields are not bare row
indices.  The vendor header defines each edge slot as:

```text
successor_t / predecessor_t:
  pe_pos:   position_t {x, y, z}
  block_idx
  valid
```

`VendorComponentPlan` therefore now mirrors the dependency slots into
endpoint-shaped candidate records:

```text
predecessor_endpoint_slots[4]
successor_endpoint_slots[4]
endpoint_slot_policy = candidate_position_block_valid_tuple
endpoint_slots_are_binary_encoded = false
```

Current `gemm_no_relu` summary:

```text
exeblock_candidate_endpoint_slot_shape_error_count = 0
exeblock_candidate_endpoint_valid_count            = 640
```

The valid endpoint count is doubled relative to the 320 structural edges because
each edge appears once as a successor endpoint on the source exeBlock and once
as a predecessor endpoint on the target exeBlock.  Inactive endpoint slots are
represented as structured invalid records in the report:

```text
{pe_pos: null, block_idx: null, valid: false}
```

This is still not byte encoding.  It only proves that the B-line report can now
express the shape required by vendor predecessor/successor fields while keeping
the final inactive-slot bytes and layout packing as a future serializer decision.

### Candidate exeBlock struct field view

`VendorComponentPlan` now attaches a report-only `exeBlock_conf_info_candidate`
object to each candidate exeBlock row.  This view follows the vendor
`exeBlock_conf_info_t` / `exeBlock_conf_t` field shape without writing bytes.

Current `gemm_no_relu` summary:

```text
exeblock_candidate_struct_view_count          = 384
exeblock_candidate_struct_binary_encoded_count = 0
exeblock_candidate_struct_candidate_pc_count  = 384
exeblock_candidate_struct_unresolved_pc_count = 0
candidate_pe_local_pc_row_count               = 896
candidate_pe_local_pc_binary_encoded_count    = 0
exeblock_candidate_struct_inst_base_count     = 384
```

The candidate view currently fills fields whose semantics are already explicit
in B-line:

```text
valid
block_idx
pe_dst
priority
req_activations
predecessors[4]
successors[4]
task_idx
subtask_idx
instances_amount
child_amount
stages_start_pc
stage_inst_amounts
is_leaf
```

The stage PC fields are now backed by a candidate dense PE-local instruction
order:

```text
candidate_pe_local_pc_policy = dense_per_physical_pe_instruction_order
stage_start_pc_policy        = candidate_dense_per_physical_pe_instruction_order
```

For the current report, a PE-local stream has the expected local sequence:

```text
accumulator_prepare: LD=0  CAL=0  FLOW=1  ST=1  END=1,  inst_base=0
k_stream k0:         LD=1  CAL=3  FLOW=4  ST=4  END=4,  inst_base=304
finalize_store:      LD=13 CAL=13 FLOW=13 ST=13 END=14, inst_base=3952
```

This follows the vendor `organize_block_conf()` convention: even an absent stage
gets the cumulative PC boundary reached by previous stages, and the END /
`MAX_COMPONENT` entry is the block end PC.  The candidate
`inst_mem_based_addr` is the PE-local start PC multiplied by `sizeof(inst_t)`.

The view still deliberately keeps block class unresolved:

```text
inst_mem_based_addr_policy = candidate_pe_local_start_pc_byte_offset
block_class                = null
block_class_policy         = unresolved_pending_vendor_class_mapping
```

This means B-line can now reason about candidate PE-local stage starts without
claiming final byte layout, inactive-slot sentinels, or block classes.

### Candidate task / subtask struct field view

`VendorComponentPlan` now also attaches report-only MICC-side struct views:

```text
task_conf_info_candidate
sub_task_conf_info_candidate
```

Current `gemm_no_relu` summary:

```text
task_candidate_struct_view_count              = 4
task_candidate_struct_binary_encoded_count    = 0
task_candidate_active_subtask_total           = 12

subtask_candidate_struct_view_count           = 12
subtask_candidate_struct_binary_encoded_count = 0
subtask_candidate_successor_edge_count        = 8
subtask_candidate_root_block_total            = 192
subtask_candidate_block_total                 = 384
subtask_candidate_observed_loop_instance_total = 16
```

For each task, the candidate subtask chain is:

```text
subtask0_accumulator_prepare -> subtask1_k_stream -> subtask3_finalize_store
```

The candidate task row therefore carries:

```text
subtasks_amount = 3
subtasks_idx    = [0, 1, 3, null, null, null, null, null]
suc_tasks       = [null, null, null, null]
execute_times   = 1
```

Each subtask candidate carries the fields that are already explicit in B-line:

```text
is_exe_start / is_exe_end
instances_amount
suc_subtasks[4]
root_block_amount
block_amount
subtask_idx
task_idx
embedded_exeblock_component_indices
```

Important boundary: current B-line still represents the K loop as expanded
loop-instance exeBlocks.  Therefore `subtask1_k_stream` reports:

```text
instances_amount = 1
instances_amount_policy = expanded_loop_instances_as_exeblocks_report_only
observed_loop_instance_count = 4
block_amount = 64
root_block_amount = 16
```

This intentionally does not claim the folded vendor representation where one
subtask graph body is repeated by `instances_amount = 4`.  That folding decision
belongs to a later loop-folding / instance-table layout pass.
