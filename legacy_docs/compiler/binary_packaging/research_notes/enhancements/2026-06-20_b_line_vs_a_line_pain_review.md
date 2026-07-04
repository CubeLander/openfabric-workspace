# B-line vs A-line Pain Review

Date: 2026-06-20

Status: legacy pain/failure evidence. Current architecture is
`../../../../../../next_stage_refactor_direction.md`.

Related notes:

```text
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_a_line_pain_retrospective.md
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_functional_probe_manual_abi_assumptions.md
docs/compiler/binary_packaging/research_notes/enhancements/2026-06-20_a_line_binary_memory_mud_for_b_line.md
docs/compiler/binary_packaging/research_notes/enhancements/rfc-fiber-executable-role-binding.md
docs/compiler/binary_packaging/research_notes/enhancements/rfc-b-line-template-op-binary-plan.md
```

The removed StreamTilePlan RFCs are superseded by the Scoped Tensor Projection
model. Keep this note for A-line/B-line failure lessons, not as an architecture
entrypoint.

## Executive Summary

B-line is aiming at the right disease.

The A-line pain was not just that a few constants were wrong.  The deeper
problem was that task layout, template semantics, memory layout, executable
roles, runtime package status, and vendor component shape were all too implicit
and too close to byte artifacts.

B-line's design directly addresses that by introducing a layered, report-first
pipeline:

```text
StreamPlan
  -> Fiber
  -> FiberBlockProjection
  -> ExecutableFiberOp
  -> SymbolicRoleBinding
  -> SymbolicTemplateRecord
  -> Dfu3500RoleSemanticReport
  -> FiberExecutionSchedule
  -> TemplateOpPlan
  -> BinaryLayoutPlan
  -> DebugRowArtifact
  -> VendorLikeRowGroupPlan
  -> VendorLikeLocalRemapPlan
  -> VendorComponentPlan
```

This is much healthier than A-line's “patch the field closest to the runtime
failure” style.

However, B-line has not yet solved the full problem.  It has mostly solved the
**semantic observability** problem and partially solved the **layout planning**
problem.  It has not yet solved the **runnable vendor ABI emission** problem.

The current B-line state is:

```text
GEMM+ReLU:
  layout_candidate
  ReLU intentionally unresolved / unproven

GEMM without ReLU:
  emittable_debug
  report-only debug rows and vendor component skeletons
  no binary bytes emitted
```

That is a good place to be.  It is honest.  It should remain honest.

## Evidence From Current B-line Checks

The focused B-line checks currently pass:

```text
check_stream_compiler_projection.py
check_stream_compiler_executable.py
check_stream_compiler_role_binding.py
check_stream_compiler_template_records.py
check_stream_compiler_dfu3500_semantics.py
check_stream_compiler_schedule.py
check_stream_compiler_template_ops.py
check_stream_compiler_binary_plan.py
check_stream_compiler_debug_emit.py
check_stream_compiler_vendor_groups.py
check_stream_compiler_local_remap.py
check_stream_compiler_vendor_components.py
check_stream_compiler_no_relu_safe_subset.py
check_stream_compiler_snapshot_export.py
```

Observed summary:

```text
gemm_relu:
  stream_count = 64
  fiber_count = 64
  executable_ops = 1024
  concrete_template = 896
  zero_instruction = 64
  symbolic_unresolved = 64
  unresolved role = epilogue:relu
  runnability_state = layout_candidate

gemm_no_relu:
  stream_count = 64
  fiber_count = 64
  executable_ops = 960
  instruction_rows = 896
  zero_instruction_boundaries = 64
  unresolved_template_op_count = 0
  runnability_state = emittable_debug
```

Debug component projection currently reports:

```text
inst_rows = 896
task_rows = 4
subtask_rows = 12
instance_rows = 16
exeblock_rows = 384
modeled_component_capacity_ok = true
```

Crucially, it also reports:

```text
candidate_pe_local_pc_binary_encoded_count = 0
exeblock_candidate_struct_binary_encoded_count = 0
```

This is good: B-line is not pretending that report-only rows are real vendor
binary bytes.

## Second-Pass Source Audit Additions

After reading the current `stream_compiler` source, B-line is doing more than a
surface-level rename of A-line ideas.  The important thing is that it already
has a report-only path for the two most painful A-line areas:

```text
1. task/subtask/exeblock control shape
2. template/executable-role binding shape
```

The best evidence is not only the architecture notes.  It is the local guard in
`check_stream_compiler_vendor_components.py`, which locks down many exact
component facts that A-line discovered only after remote hangs:

```text
inst_rows = 896
task_rows = 4
subtask_rows = 12
instance_rows = 16
exeblock_rows = 384

subtask successor chain:
  subtask0_accumulator_prepare -> subtask1_k_stream
  subtask1_k_stream            -> subtask3_finalize_store
  subtask3_finalize_store      -> end

per-PE exeblock count = 24
exeblock dependency edges = 320
dependency proofs:
  loop_instance_order = 192
  subtask_order       = 128

candidate endpoint slots are fixed-width 4-slot records.
candidate PE-local PCs exist for every instruction row.
candidate exeBlock struct views exist for every exeBlock row.
all candidate binary_encoded flags are false.
```

This matters because A-line's hardest bugs were not mysterious math failures.
They were control-plane shape mistakes: wrong task count, wrong subtask terminal
semantics, wrong exeblock expectations, wrong fixed package shape, wrong base
slot.  B-line is explicitly turning those into local deterministic facts before
any byte writer is allowed to exist.

The strongest current B-line file for this is:

```text
compiler/gpdpu_compiler/core/stream_compiler/vendor_components.py
```

It does not emit bytes, but it already projects:

```text
task_conf_info_candidate
sub_task_conf_info_candidate
exeBlock_conf_info_candidate
capacity_report
candidate_pe_local_pc
candidate endpoint slots
candidate stage_start_pc
candidate inst_mem_based_addr
```

That is exactly the right direction.  It also keeps every one of these as a
candidate/report-only field.  That honesty must not be weakened.

### Important Distinction: Instruction Memory vs Data Memory

B-line now models candidate instruction-side layout:

```text
candidate_pe_local_pc
stage_start_pc_candidates
inst_mem_based_addr_policy = candidate_pe_local_start_pc_byte_offset
```

This addresses one half of the A-line exeblock pain: the runtime needs coherent
per-PE instruction ordering and block stage metadata.

It does **not** yet address the worst A-line memory bug:

```text
STD used iter_exe_cond=2, therefore it consumed instance base_addr2.
The instance row had to populate base_addr2 with output SRAM.
```

That is data-memory base-slot binding, not instruction-memory PC binding.

So the review must keep these separate:

```text
Instruction-side layout:
  PE-local PC
  stage_start_pc
  inst_mem_based_addr
  exeblock stage counts

Data-side layout:
  LDM/STD operand storage region
  base_addr slot
  iter_exe_cond
  instance_conf_info row
  byte offset unit
```

B-line is already doing real work on the first category.  It still needs an
equally explicit plan for the second before it can safely emit runnable bytes.

## Pain Coverage Matrix

### Pain 1: Task/Subtask Semantics Were Too Fragile

A-line pain:

```text
functional probe store needed subtask1
GEMM store used subtask2
wrong slot caused runtime hangs / MicC rest confusion
```

B-line design response:

```text
BinaryLayoutPlan has explicit task_rows, subtask_rows, instance_rows.
TemplateOps are assigned subtask slots by phase/role.
VendorComponentPlan reports task/subtask/exeblock counts before byte emission.
```

Implemented evidence:

```text
compiler/gpdpu_compiler/core/stream_compiler/binary_plan.py
  BinaryTaskPlan
  BinarySubtaskPlan
  BinaryInstancePlan

compiler/gpdpu_compiler/core/stream_compiler/vendor_components.py
  VendorComponentPlan
  capacity_report

check_stream_compiler_binary_plan.py
  expected subtask_instruction_counts

check_stream_compiler_vendor_components.py
  task/subtask/instance/exeblock count assertions
```

Current coverage:

```text
Substantially addressed for report-only control shape.
Not yet addressed for typed runnable ABI slots.
```

What is improved:

```text
Task/subtask placement is visible and count-checked before binary emission.
Subtask successor chains are locally asserted.
Task/subtask/exeblock/instance capacities are locally asserted.
Candidate exeblock endpoint slots have fixed four-slot shape.
```

What remains weak:

```text
Subtask identity is still string-policy based:
  subtask0_accumulator_prepare
  subtask1_k_stream
  subtask3_finalize_store
  subtask4_relu_candidate

This is better than hidden slot selection, but it is not yet a typed vendor
subtask plan with terminal/successor semantics.

Task id extraction is still derived from stream ids such as t0_pe00.  That is
acceptable for current report-only GEMM demo shape, but final ABI emission
should consume a typed soft-processor/task-axis plan instead of parsing names.
```

Needed next step:

```text
Promote subtask slots from strings to typed rows with:
  vendor_subtask_index
  role
  terminal/successor policy
  allowed loop/instance ownership

Replace task-id-from-stream-id parsing with typed task-axis coordinates before
runnable byte emission.
```

### Pain 2: Template Binding Was Not A Real Op Lowering Contract

A-line pain:

```text
maximum_scalar needed manual compute_attrs plumbing through several layers.
template support was case-shaped and fragile.
```

B-line design response:

```text
FiberOp -> ExecutableFiberOp -> SymbolicRoleBinding -> TemplateOp
```

Implemented evidence:

```text
compiler/gpdpu_compiler/core/stream_compiler/fiber.py
  FiberOp with inputs/outputs/dependencies/attrs

compiler/gpdpu_compiler/core/stream_compiler/executable.py
  ExecutableFiberOp
  role mapping

compiler/gpdpu_compiler/core/stream_compiler/template_ops.py
  TemplateOp
  InstructionIntent
  TemplateResourceRequirement

check_stream_compiler_executable.py
check_stream_compiler_template_ops.py
```

Current coverage:

```text
Strongly addressed in design.
Partially addressed in implementation.
```

What is improved:

```text
Executable roles are explicit and counted.
TemplateOps preserve provenance back to FiberOps.
Unsupported roles remain visible instead of being silently dropped.
```

What remains weak:

```text
TemplateOps still use broad symbolic opcodes:
  HMMAL_OR_GEMM_UPDATE
  LOAD_OR_COPY
  ROUTE_RECV_VISIBILITY

This is acceptable for report-only B-line, but not enough for runnable ABI.
```

Needed next step:

```text
Introduce typed concrete template families with operand/base-slot contracts,
not just symbolic opcode intent strings.
```

### Pain 3: Memory Layout / Base Slot Semantics Were Implicit

A-line pain:

```text
STD used base_addr2 but instance table populated the wrong slot.
```

B-line design response:

```text
TemplateResourceRequirement exists.
TemplateOp/InstructionIntent can describe operand and immediate policies.
VendorComponentPlan has component-shaped instance rows.
```

Implemented evidence:

```text
compiler/gpdpu_compiler/core/stream_compiler/template_ops.py
  TemplateResourceRequirement
  InstructionIntent.operand_policy
  InstructionIntent.immediate_policy

compiler/gpdpu_compiler/core/stream_compiler/vendor_components.py
  instance_rows
  capacity_report
```

Current coverage:

```text
Instruction-memory layout is now actively modeled as candidate data.
Data-memory base-slot layout is still only lightly addressed.
```

What is improved:

```text
Memory/resource requirements now have a place to live.
Candidate PE-local instruction PCs and exeblock instruction-base fields are
computed and guarded.
```

What remains weak:

```text
There is no typed memory layout contract yet:
  storage region
  base slot
  iter_exe_cond
  byte offset
  instance base row owner

VendorComponentPlan counts instance rows, but it does not yet prove that a
specific load/store instruction consumes a specific base slot.

The current candidate `inst_mem_based_addr` is instruction memory metadata.
It must not be mistaken for the data-side `base_addr0..3` contract that feeds
LDM/STD address calculation.
```

Needed next step:

```text
Add a MemoryAccessPlan / BaseSlotBinding layer before any runnable byte emitter.
This must explicitly bind each memory TemplateOp intent to:
  base_addr slot
  instance row
  storage region
  offset unit
```

### Pain 4: Runtime Package Size Was Not A Profile Contract

A-line pain:

```text
short MICC looked plausible but runtime needed fixed package capacity.
```

B-line design response:

```text
VendorComponentPlan uses DFU3500_VENDOR_LIMITS and DFU3500_STRUCT_SIZES.
capacity_report checks modeled component capacity.
```

Implemented evidence:

```text
compiler/gpdpu_compiler/core/stream_compiler/vendor_components.py
  imports DFU3500_VENDOR_LIMITS
  imports DFU3500_STRUCT_SIZES
  capacity_report

check_stream_compiler_vendor_components.py
  inst capacity = 69632
  task capacity = 4
  subtask capacity = 32
  instance capacity = 65536
  exeblock capacity = 512
```

Current coverage:

```text
Well addressed for report-only capacity modeling.
Not yet addressed for real byte package serialization.
```

What remains:

```text
No B-line serializer writes fixed-size CBUF/MICC blobs yet.
```

Needed next step:

```text
Before runnable emission, B-line needs a BinaryPackageEmitter that consumes
VendorComponentPlan and writes fixed-capacity blobs under a single profile
contract.
```

### Pain 5: Validation Truth Was Split Across Too Many Statuses

A-line pain:

```text
program_status, row validation, component validation, manifest gates disagreed.
```

B-line design response:

```text
Every B-line layer has an explicit runnability_state / validation summary.
The current code distinguishes:
  layout_candidate
  emittable_debug
  report_only
  runnable_candidate
```

Implemented evidence:

```text
TemplateOpPlan.runnability_state
BinaryLayoutPlan.runnability_state
VendorComponentPlan.runnability_state
summarize_* functions for every layer
snapshot export tool
```

Current coverage:

```text
Strongly addressed for debug/report flows.
```

What is improved:

```text
B-line is honest about not being runnable.  ReLU remains unresolved; no-ReLU is
only emittable_debug.
```

What remains:

```text
There is not yet a final RuntimeRunnable gate equivalent to A-line's manifest
gate because B-line intentionally does not emit runtime packages.
```

Needed next step:

```text
When B-line reaches binary emission, define one authoritative package-level gate
instead of reintroducing multiple status dialects.
```

### Pain 6: Stale Payload Selection

A-line pain:

```text
validated one tree, uploaded another.
```

B-line design response:

```text
B-line currently avoids upload/runtime packaging entirely.
Snapshot export and debug rows are deterministic report artifacts.
```

Implemented evidence:

```text
compiler/tools/export_stream_compiler_snapshot.py
compiler/tools/export_stream_compiler_debug_rows.py
check_stream_compiler_snapshot_export.py
```

Current coverage:

```text
Avoided, not solved.
```

Needed next step:

```text
If/when B-line emits runnable packages, reuse or generalize the A-line
entrypoint guard.  Do not invent another unguarded run-selection directory.
```

### Pain 7: Vendor Reference Cases Were Useful But Dangerous

A-line pain:

```text
vendor-like hand case helped compare bytes but could copy wrong metadata.
```

B-line design response:

```text
B-line explicitly names report-only vendor-like groups and local remaps.
It does not claim binary encoding.
```

Implemented evidence:

```text
compiler/gpdpu_compiler/core/stream_compiler/vendor_groups.py
  VendorLikeRowGroupPlan
  VendorLikeLocalRemapPlan

compiler/gpdpu_compiler/core/stream_compiler/vendor_components.py
  candidate_* fields
  binary_encoded = false

check_stream_compiler_vendor_components.py
  asserts candidate fields do not claim binary encoding
```

Current coverage:

```text
Strongly addressed as a design discipline.
```

What remains:

```text
The transition from candidate/report-only to real binary encoding is still
future work.  That transition will be dangerous and should have a separate
approval gate.
```

### Pain 8: Semantic Names And Runtime Shell Names Were Mixed

A-line pain:

```text
app_name=CASE/softmax_1 was a runtime shell hook, not semantic truth.
```

B-line design response:

```text
B-line currently models stream/fiber/compiler semantics without remote runtime
case names.
```

Implemented evidence:

```text
StreamPlan.app_id
stream ids like t0_pe00
profile ids like dfu3500_legacy_gemm_symbolic
no CASE/softmax_1 dependency in stream compiler
```

Current coverage:

```text
Well addressed inside B-line.
Not yet tested at runtime integration boundary.
```

Needed next step:

```text
When runtime packaging returns, keep semantic case id and vendor shell staging
id as separate fields.
```

### Pain 9: A-Line Encouraged Cross-Layer Patching

A-line pain:

```text
field failures were patched near serializer/runtime symptom sites.
```

B-line design response:

```text
Authority boundaries are explicit:
  StreamPlan owns whole-value visibility.
  Fiber owns flat fragment ops.
  ExecutableFiberOp owns executable roles.
  TemplateOpPlan owns target-template content.
  BinaryLayoutPlan owns symbolic placement.
  VendorComponentPlan owns component-shaped debug rows.
```

Implemented evidence:

```text
Layering policy strings in to_plan()
forbidden_tile_micro_block_field_count checks
one-way demo pipeline in stream_compiler_demo_pipeline.py
```

Current coverage:

```text
Strongly addressed in design and report-only implementation.
```

What remains:

```text
The real test is whether future byte emission follows these boundaries instead
of reaching back into FiberOps/TemplateOps from a serializer.
```

### Pain 10: Remote Debugging Magnified Implicit Assumptions

A-line pain:

```text
runtime hangs hid whether the issue was task count, MICC size, base slots,
terminal flags, instruction rows, or control program.
```

B-line design response:

```text
Build local, deterministic snapshots and debug rows before runtime.
```

Implemented evidence:

```text
export_stream_compiler_snapshot.py
export_stream_compiler_debug_rows.py
many focused check_stream_compiler_* scripts
```

Current coverage:

```text
Strongly addressed for pre-runtime visibility.
Not yet proven for remote runtime because B-line is not runnable.
```

Needed next step:

```text
Before any remote B-line run, require a snapshot + debug row + component summary
bundle as the upload manifest's evidence.
```

## What B-line Has Really Solved

B-line has genuinely improved:

```text
1. Semantic visibility:
   FiberOps and ExecutableFiberOps make roles visible.

2. Provenance:
   TemplateOps and BinaryLayout rows trace back to source FiberOps.

3. Fail-closed behavior:
   ReLU remains unresolved instead of being silently emitted.

4. Reportability:
   Snapshots and summaries show counts at every layer.

5. Candidate-vs-binary honesty:
   VendorComponentPlan uses candidate fields and explicitly does not claim
   binary encoding.

6. Capacity awareness:
   DFU3500 vendor limits are consulted before any component-shaped report.

7. Legacy TileMicroBlock decoupling:
   Checks assert forbidden TileMicroBlock fields do not leak into B-line rows.
```

This is not cosmetic.  It directly attacks A-line's worst failure mode:

```text
semantic fact hidden until runtime hang
```

## What B-line Has Not Solved Yet

B-line still lacks:

```text
1. Runnable binary serialization.
2. Real CBUF/MICC byte emission.
3. Typed memory/base-slot binding.
4. Typed vendor subtask terminal/successor semantics.
5. A runtime control/package integration path.
6. Numeric result checking.
7. Non-GEMM op family support.
8. Actual log10max/reduce/app-storage lowering.
9. A path from real ChipEnv/AppPlan into StreamPlan.
10. A policy for partial mesh / alternative task partition strategies.
```

This is fine, as long as nobody confuses `emittable_debug` with `runnable`.

## Design Risks In B-line

### Risk 1: Stringly Typed Task/Subtask Slots

Current examples:

```text
subtask0_accumulator_prepare
subtask1_k_stream
subtask3_finalize_store
subtask4_relu_candidate
```

This is readable, but it can become A-line's next hidden convention if not typed
before emission.

Recommendation:

```text
Add `VendorSubtaskSlot` / `SubtaskRolePlan` before runnable byte output.
```

### Risk 2: Memory Binding Is Still Too Abstract

Current `InstructionIntent` has:

```text
operand_policy
immediate_policy
```

But A-line's nastiest bug was:

```text
STD base slot 2
```

Recommendation:

```text
Introduce explicit MemoryAccessPlan before any real STD/LDM emission.
```

### Risk 3: Candidate Component Fields Could Become Cargo Cult

Current vendor component fields are carefully marked:

```text
candidate_*
binary_encoded = false
```

This is good.  But these fields are close enough to ABI shapes that a future
patch may be tempted to flip them into real serializer inputs too early.

Recommendation:

```text
Add a hard adapter phase:
  VendorComponentPlan(report-only)
    -> VerifiedVendorABIPlan
    -> BinaryPackageEmitter
```

Do not let the byte emitter consume report-only candidate rows directly.

### Risk 4: Demo GEMM Is Not Yet Real Frontend Integration

B-line currently builds a demo stream plan:

```text
build_demo_gemm_stream_plan()
```

This is useful for proving the model, but it does not yet consume real
`ChipEnv.generate()` output.

Recommendation:

```text
Next integration milestone should lower one real AppPlan/LogicalPlan GEMM into
StreamPlan, while preserving the same snapshot counts.
```

## Recommended Next Milestones

### Milestone 1: Freeze B-line Report Contracts

Keep current checks and add one meta-check:

```text
All B-line report rows must preserve provenance:
  source FiberOp id
  schedule step id
  TemplateOp id
  task/subtask/loop identity where applicable
```

### Milestone 2: Type Task/Subtask Plan

Before byte emission, replace string-only slots with typed records:

```text
task_id
subtask_index
subtask_role
phase
terminal_policy
successor_policy
loop_instance_policy
```

### Milestone 3: Type Memory/Base Slot Binding

Add:

```text
MemoryAccessPlan
BaseSlotBinding
InstanceBaseRowPlan
```

This directly targets the `STD base_addr2` class of bug.

### Milestone 4: Bridge Real Current-Core GEMM Into StreamPlan

Do not start with runtime bytes.  Start with:

```text
real ChipEnv GEMM
  -> StreamPlan
  -> existing B-line snapshot summaries
```

The count targets should match the demo profile or explain why they differ.

### Milestone 5: Add VerifiedVendorABIPlan

Only after task/subtask and memory binding are typed:

```text
VendorComponentPlan(report-only)
  -> VerifiedVendorABIPlan(binary-ready)
```

This is where candidate fields become real ABI fields, with checks.

### Milestone 6: Only Then Emit Bytes

The first runnable B-line binary should probably be GEMM no-ReLU, not log10max.

Reason:

```text
GEMM no-ReLU has current B-line emittable_debug coverage and known A-line/vendor
baselines.  It is the safest bridge from report-only to runtime.
```

## Supervision Checklist Before B-line Byte Emission

This is the practical guardrail list for future agents.  If any item below is
not true, B-line should stay in report/debug mode.

```text
Task/control shape:
  [ ] task id comes from typed task-axis coordinates, not stream-name parsing
  [ ] subtask index comes from typed SubtaskRolePlan, not string slot names
  [ ] subtask successor/end semantics are explicit and locally checked
  [ ] task amount and active task rows match the package profile

ExeBlock/control graph:
  [ ] exeblock predecessor/successor slots are fixed-width and overflow-checked
  [ ] endpoint slots are proven against physical PE coordinates
  [ ] dependency proofs are carried into verified ABI rows
  [ ] candidate row indices have been converted through an explicit verifier

Instruction layout:
  [ ] PE-local PCs are dense per physical PE
  [ ] stage_start_pc and inst_mem_based_addr are verified as instruction-memory fields
  [ ] no instruction-memory field is used as a data-memory base-slot substitute

Data memory:
  [ ] every LDM/STD has storage region, offset, and base-slot binding
  [ ] every base_addr slot is populated in the correct instance row
  [ ] iter_exe_cond/base-slot consumption is tested for each load/store family

Template binding:
  [ ] symbolic opcode names have been replaced by concrete template families
  [ ] operand/immediate policies are typed enough for byte emission
  [ ] unsupported roles fail closed before package generation

Packaging:
  [ ] fixed-size CBUF/MICC capacities come from DFU3500 profile constants
  [ ] report-only candidate rows are not directly consumed by byte writer
  [ ] runtime manifest points at the exact tree being uploaded
```

This checklist is intentionally stern.  A-line proved that if any of these are
left implicit, the runtime will not give a clean compiler error; it will give a
half-useful hang, a misleading `rest(1)`, or a remote log that has to be decoded
like an archaeological tablet.

## Updated Verdict After Source Audit

B-line is addressing the two biggest A-line pains more directly than the first
review credited:

```text
1. Template/executable-role opacity:
   now split into FiberOp, ExecutableFiberOp, TemplateOp, InstructionIntent,
   and explicit unsupported-role diagnostics.

2. Task/subtask/exeblock control opacity:
   now projected into report-only task/subtask/instance/exeblock component
   views with local guard tests for counts, successor chains, endpoint slots,
   stage PCs, and candidate struct shapes.
```

So the engineering direction is correct.  The important warning is narrower:

```text
B-line solves the observability and candidate-shape problem.
It does not yet solve the final ABI binding problem.
```

That is exactly where A-line got painful.  The next B-line work should not be
"make the candidate rows binary" by editing serializers.  It should be:

```text
typed task/subtask plan
typed memory/base-slot plan
verified ABI plan
then byte emitter
```

If B-line keeps that discipline, it can retire the A-line compatibility bridge
instead of recreating it under nicer class names.

## Final Judgment

B-line is not just “new code.”  It is a serious attempt to remove the pain A-line
exposed:

```text
A-line:
  runnable but implicit, fragile, byte-artifact-shaped

B-line:
  not runnable yet, but explicit, inspectable, provenance-preserving
```

The design addresses most A-line pain points.  The implementation has already
landed meaningful parts of that design:

```text
Stream/Fiber flat IR
semantic dependencies
executable roles
template records
DFU3500 semantic reports
schedule
TemplateOpPlan
BinaryLayoutPlan
vendor-like debug/component reports
focused check scripts
```

The remaining danger is the next step: turning report-only candidate structures
into real vendor ABI bytes.  That is where A-line pain can re-enter if we skip
typed task/subtask and memory/base-slot plans.

So the B-line supervision verdict is:

```text
Proceed, but do not rush to binary emission.

First type the two places A-line hurt the most:
  task/subtask semantics
  memory/base-slot binding
```

B-line has earned the right to continue.  It has not yet earned the right to
write runnable CBUF/MICC bytes.
