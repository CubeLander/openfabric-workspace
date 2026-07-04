# A-line Binary / Memory Mud Map For B-line

Date: 2026-06-20

Status: knowledge transfer / B-line guardrail

Related notes:

```text
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_functional_probe_manual_abi_assumptions.md
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_a_line_pain_retrospective.md
docs/compiler/binary_packaging/research_notes/enhancements/2026-06-20_b_line_vs_a_line_pain_review.md
docs/vendor_reference/common_oper/binary-artifact-generation-pipeline.md
docs/vendor_reference/common_oper/dfu3500-hardware-constraints-from-vendor-algorithms.md
```

## Purpose

A-line produced a runnable `functional_maximum_single_app` package, but it did
so by walking through a swamp of binary, MICC, CBUF, memory-layout, and runtime
packaging facts.  Those facts are valuable.  They should not remain scattered
across code patches, remote logs, and pain notes.

This document turns that mud into B-line design requirements.

The guiding rule is:

```text
Do not copy A-line scaffolding into B-line.
Extract the ABI facts A-line discovered, then encode them as typed plans,
validators, and profile contracts before B-line writes bytes.
```

A-line is the scar tissue.  B-line should become the skeleton.

## What A-line Actually Proved

The successful A-line probe proved this narrow claim:

```text
OpenFabric current core can generate a runnable DFU3500/SimICT non-GEMM package
for a tiny lane-wise operator:

  Y = maximum(X, 3.5)
```

It did **not** prove a general non-GEMM backend.  The runnable path used a small
compatibility bridge:

```text
vendor_inst_mode = legacy_template_compat
```

That mode means:

```text
real vendor-style legacy inst_t rows for a tiny non-GEMM local compute probe,
without GEMM-specific TaskResource replay assumptions.
```

B-line should preserve the lesson, not the shape:

```text
A-line lesson:
  small supported op templates must bind to real instruction rows.

B-line design:
  FiberOp -> ExecutableFiberOp -> TemplateOp -> VerifiedTemplateFamily
```

## The Mud Categories

A-line mud falls into seven categories:

```text
1. fixed package layout
2. task/subtask control rows
3. exeBlock control rows
4. instruction memory layout
5. data memory base-slot layout
6. legacy template / pseudo-op expansion
7. runtime package / payload selection truth
```

Each category needs a B-line owner.  If a category has no owner, it will leak
back into serializer patches.

## 1. Fixed Package Layout Is A Profile Fact

A-line initially made it tempting to emit compact active-row files.  That is not
what the runtime path wants.

Observed fixed sizes for the first functional probe:

```text
tasks_conf_info_file.bin    = 480
subtasks_conf_info_file.bin = 8522496
micc_file.bin               = 8522976
```

The short active-only files looked locally plausible but were wrong for runtime:

```text
tasks_conf_info_file.bin    = 120
subtasks_conf_info_file.bin = 2130624
micc_file.bin               = 2130744
```

Relevant DFU3500 limits:

```text
max task rows per package      = 4
max subtask rows per task      = 8
max subtask rows per package   = 32
max instances per subtask      = 2048
base_addr slots per instance   = 4
inst rows per PE               = 4352
exeBlock rows per PE           = 32
physical PE count              = 16
```

B-line requirement:

```text
VendorRuntimeProfile / DFU3500 profile constants must own all fixed capacities.
BinaryPackageEmitter must write fixed-capacity component blobs, not active-only
component blobs, unless a profile explicitly says compact layout is legal.
```

B-line guard:

```text
Before runnable emission:
  [ ] MICC size equals profile padded size.
  [ ] CBUF size equals profile padded size.
  [ ] active row count and padded capacity are reported separately.
  [ ] no serializer derives package size from active rows alone.
```

## 2. Task / Subtask Rows Are Control Semantics, Not Names

A-line pain:

```text
functional probe:
  task0
    subtask0 = load + local_compute
    subtask1 = store/final

GEMM:
  prepare / k-stream / store
  store historically lived at a different vendor subtask slot.
```

The bug class was simple:

```text
wrong subtask slot or terminal flag
  -> MicC waits for the wrong thing
  -> runtime hangs or `rest(1)` style symptoms
```

A-line guard now checks:

```text
functional probe active subtasks = [0, 1]
subtask0 is not terminal
subtask1 is terminal
runtime task count matches emitted package task count
```

B-line requirement:

```text
Replace stringly subtask slots with a typed SubtaskRolePlan.
```

Minimum B-line shape:

```text
SubtaskRolePlan:
  task_id
  vendor_subtask_index
  role
  phase
  is_exe_start
  is_exe_end
  successor_subtask_indices
  instance_policy
  block_policy
```

Important rule:

```text
Do not derive final vendor subtask index from strings like
`subtask3_finalize_store` inside a byte writer.
```

Readable names are fine for reports.  Binary emission needs typed indices and
successor/end semantics.

## 3. Task Count Must Be Runtime-Consistent

A-line hit a low-level but expensive failure:

```text
payload was semantically 1 task,
but runtime/control path was still starting or expecting 4 tasks.
```

That made debugging point at MICC/execution even though the first bug was launch
configuration consistency.

B-line requirement:

```text
RuntimeControlPlan / package manifest / task_conf rows / generated run assets
must agree on active task count.
```

Guard before upload:

```text
[ ] emitted task row active count == manifest task count
[ ] runtime launch task count == emitted active task count
[ ] generated conf.h/testarm.c/control JSON come from the same plan
[ ] selected upload payload is exactly the freshly generated payload
```

## 4. ExeBlock Rows Are Control Graph Rows

Vendor pipeline evidence says:

```text
exeblock_conf_info_file.bin is PE-major and fixed-width.
physical row = pe_index * max_exe_blocks_per_pe + pe_local_block_index
```

A-line/B-line pain area:

```text
wrong child/successor slots, root block counts, or stage PCs can make runtime
expect more work or wait on wrong dependencies.
```

B-line is already doing good report-only work here:

```text
candidate endpoint slots
candidate PE-local PCs
candidate stage_start_pc
candidate inst_mem_based_addr
candidate exeBlock_conf_info views
```

But these are not binary facts yet.

B-line requirement:

```text
VendorComponentPlan(report-only)
  -> VerifiedVendorABIPlan(binary-ready)
  -> BinaryPackageEmitter(bytes)
```

The byte emitter must not consume `candidate_*` rows directly.

Guard before ABI verification:

```text
[ ] every exeBlock row has fixed-width predecessor/successor slots
[ ] endpoint slots resolve to physical PE coordinates
[ ] dependency proofs survive projection
[ ] stage_start_pc is verified against PE-local instruction order
[ ] inst_mem_based_addr is verified as instruction-memory base, not data base
[ ] row index maps through an explicit ABI-row verifier
```

## 5. Instruction Memory Layout Is Separate From Data Memory Layout

This distinction is crucial.

Evidence attribution:

```text
Original vendor docs already state:
  DFU memory address = imm + instance_baseaddr(iteration field).

common_oper/task_print.cpp makes it concrete:
  ldst_inst.base_addr_idx = tmp_inst.iter_exe_cond.

A-line runtime bring-up proved the consequence for our generated HSTT/STD store:
  iter_exe_cond = 2 requires output SRAM in base_addr2.
```

So this was not purely newly discovered hardware behavior.  The general rule was
present in the vendor materials; the project had not yet promoted it into a
compiler-facing invariant or guard.

Instruction side:

```text
insts_file.bin is PE-major.
Each PE owns a fixed instruction row window.
exeBlock_conf_info.inst_mem_based_addr points into PE-local instruction memory.
stage_start_pc describes LD/CAL/FLOW/ST stage PCs inside that block.
```

Data side:

```text
instance_conf_info.base_addr[4] feeds LDM/STD address calculation.
Which base slot is consumed depends on instruction/template fields such as
iter_exe_cond.
```

A-line worst memory bug was data-side, not instruction-side:

```text
STD used iter_exe_cond = 2
therefore STD consumed base_addr2
but the instance row initially populated the wrong base slot
```

B-line must never treat these as the same thing:

```text
inst_mem_based_addr != base_addr slot
stage_start_pc      != data offset
PE-local PC         != SRAM/SPM address
```

B-line requirement:

```text
InstructionLayoutPlan and MemoryAccessPlan must be separate objects.
```

Minimum data-memory plan:

```text
MemoryAccessPlan:
  op_id
  role                    # input load / output store / scratch / route materialize
  direction               # load / store
  storage_region
  byte_offset
  address_unit            # bytes / uint32 words, explicitly stated
  base_slot               # 0..3
  iter_exe_cond_or_selector
  instance_row_owner
  subtask_role
  loop_instance
```

Minimum base-slot guard:

```text
For every emitted LDM/STD-family row:
  [ ] selected base slot is known
  [ ] selected instance row exists
  [ ] base_addr[selected_slot] is not sentinel unless intentionally disabled
  [ ] address unit conversion is explicit
```

## 6. Instance Rows Have Two Addressing Stories

A-line code contains an important split:

```text
physical CBUF instance_conf_info_file.bin layout:
  task window * 8 subtask slots * 2048 instance slots

MICC subtask row's instances_conf_mem_based_addr:
  compact active-instance byte offset semantics
```

This is easy to mix up.

B-line requirement:

```text
InstanceBaseRowPlan must track both:
  physical_component_row_index
  semantic_or_compact_instance_offset
```

Do not derive `instances_conf_mem_based_addr` by blindly multiplying physical
row index unless the profile explicitly says that is correct.

Guard:

```text
[ ] physical instance row index uses task/subtask/instance fixed window
[ ] subtask instances_conf_mem_based_addr uses the expected compact offset policy
[ ] both policies are named in reports
```

## 7. Sentinel Values Are Semantics

A-line filled disabled base slots with:

```text
0xffffffff
```

For the functional probe:

```text
subtask0 load row:
  base_addr0 = input base
  base_addr1 = 0xffffffff
  base_addr2 = 0xffffffff
  base_addr3 = 0xffffffff

subtask1 store row:
  base_addr0 = 0xffffffff
  base_addr1 = 0xffffffff
  base_addr2 = output base
  base_addr3 = 0xffffffff
```

B-line requirement:

```text
Sentinel values must be profile constants with meaning, not literal filler.
```

Minimum profile fact:

```text
DFU3500 disabled base address sentinel = 0xffffffff
address unit for legacy base_addr values = uint32 words
```

Guard:

```text
[ ] disabled slots use the profile sentinel
[ ] enabled slots cannot accidentally equal sentinel
[ ] reports distinguish disabled slot from zero base address
```

## 8. Legacy Pseudo-Ops Expand To Real Rows

A-line had to treat vendor CSV pseudo ops as templates, not literal one-row
instructions.

Observed pseudo expansion:

```text
ILDT / ILDMT -> LDM-family physical rows
ISTT / HSTT  -> STD-family physical rows
COPYT        -> COPY-family physical rows
```

For the first local maximum probe:

```text
local compute:
  ILDMT input
  IMM scalar
  FMAX

store:
  HSTT-style pseudo template expanded to STD rows
```

Important observed details:

```text
FMAX wait/latency field was hand-set for this probe.
local FMAX iter_exe_cond was set to 1.
store STD used iter_exe_cond = 2.
stage-end flags were disabled for the tiny local template.
```

B-line requirement:

```text
Template families must expose pseudo expansion as part of the template contract.
```

Minimum template-family shape:

```text
TemplateFamily:
  name
  semantic_role
  pseudo_ops
  physical_ops
  operand_roles
  base_slot_requirements
  iter_exe_cond requirements
  latency/wait policy
  stage policy
  evidence_status
```

Guard:

```text
[ ] every pseudo op expands before binary row counting
[ ] physical row count is known before task/subtask/exeblock layout
[ ] base-slot requirements are exported to MemoryAccessPlan
[ ] stage ownership is exported to InstructionLayoutPlan
```

## 9. Operand Slots Are Not Generic Registers

A-line local max used a fixed tiny operand convention:

```text
regular slot 0 = input value
regular slot 1 = scalar immediate
regular slot 2 = output/store value
```

GEMM route/resource replay revealed a deeper vendor rule:

```text
PE-local operand RAM is a real address space.
TaskResource assigns operands by task/PE first-use order.
Tensor pseudo lanes use lane-strided layout.
COPYT destination operand belongs to receiver/child PE resource ownership.
```

B-line requirement:

```text
Do not pretend a general register allocator exists.
Start with small typed template operand contracts, then grow allocator only when
there is enough evidence.
```

Guard:

```text
[ ] template operand policy states whether slots are fixed or allocated
[ ] allocated operands are scoped by task/soft-processor/physical PE
[ ] route destination operands are receiver-owned, not sender-owned
[ ] tensor lane expansion uses explicit lane/bank policy
```

## 10. CBUF / MICC Component Ownership

Vendor generation chain:

```text
result/cbuf_file.bin
  = simulator_bin/insts_file.bin
  + simulator_bin/exeblock_conf_info_file.bin
  + simulator_bin/instance_conf_info_file.bin

result/micc_file.bin
  = simulator_bin/tasks_conf_info_file.bin
  + simulator_bin/subtasks_conf_info_file.bin
```

Component responsibilities:

```text
insts_file.bin:
  PE-major fixed instruction memory rows

exeblock_conf_info_file.bin:
  PE-major fixed executable block rows, stage PCs, dependency slots

instance_conf_info_file.bin:
  fixed task/subtask/instance base_addr rows

tasks_conf_info_file.bin:
  task row topology, active subtasks, task successors

subtasks_conf_info_file.bin:
  subtask topology, root/block counts, instance pointer, embedded block table
```

B-line requirement:

```text
The final byte emitter should write components from typed component plans, not
from scattered serializer helper functions.
```

Suggested B-line component owners:

```text
InstructionLayoutPlan      -> insts_file.bin
ExeBlockControlPlan        -> exeblock_conf_info_file.bin
InstanceBaseRowPlan        -> instance_conf_info_file.bin
TaskControlPlan            -> tasks_conf_info_file.bin
SubtaskControlPlan         -> subtasks_conf_info_file.bin
RuntimePackageManifestPlan -> result package + upload bundle
```

## 11. A-line Guards To Preserve Or Port

Current useful A-line guard:

```text
compiler/tools/check_core_functional_probe_report.py
```

It checks things B-line should eventually reproduce at its own level:

```text
component sizes are fixed profile sizes
manifest says functional_maximum_single_app and legacy_template_compat
instruction op counts match expected LDM/IMM/FMAX/STD shape
active instance base rows bind input/output bases to correct slots
active subtask indices are [0, 1]
subtask0 is not terminal
subtask1 is terminal
runtime control case id matches payload case id
```

Current useful upload guard:

```text
compiler/tools/check_partner_validation_entrypoint.py
```

It protects against stale package selection.

B-line requirement:

```text
Before any B-line remote package exists, define equivalent guards at B-line plan
level and at final upload-bundle level.
```

Do not wait for the first remote hang to add them.

## 12. What B-line Should Not Inherit

Do not inherit these A-line patterns:

```text
1. byte writer derives semantic task/subtask meaning from string ids
2. serializer owns base-slot decisions
3. compact component file looks valid because local row counts fit
4. program status and manifest status disagree
5. runtime shell case name doubles as semantic operator name
6. candidate vendor rows are directly serialized
7. template support is inferred from op name plus attrs dict
8. remote run is the first complete validator
```

Every one of these patterns already cost time.

## 13. B-line Translation Table

| A-line mud fact | B-line object that should own it |
| --- | --- |
| fixed MICC/CBUF sizes | `VendorRuntimeProfile` / package profile |
| active task count | `TaskControlPlan` + `RuntimeControlPlan` |
| subtask start/end/successors | `SubtaskRolePlan` / `SubtaskControlPlan` |
| exeblock stage PCs | `InstructionLayoutPlan` + `ExeBlockControlPlan` |
| exeblock dependency slots | `ExeBlockControlPlan` with dependency proofs |
| physical instance row index | `InstanceBaseRowPlan` physical row policy |
| compact instance pointer in subtask row | `SubtaskControlPlan` instance offset policy |
| `base_addr[4]` slot values | `BaseSlotBinding` |
| `iter_exe_cond` choosing base slot | `TemplateFamily` + `MemoryAccessPlan` |
| `0xffffffff` disabled base | DFU3500 profile sentinel |
| ILDMT/HSTT/COPYT expansion | `TemplateFamily` pseudo expansion contract |
| fixed local max operand slots | `TemplateOperandPolicy` |
| route receiver-owned operand | future route/template operand ownership plan |
| stale upload tree | package manifest + entrypoint guard |

## 14. Immediate B-line Work Items From This Mud

The next B-line byte-readiness work should be ordered like this:

```text
1. Add typed SubtaskRolePlan / TaskControlPlan.
2. Add typed MemoryAccessPlan / BaseSlotBinding / InstanceBaseRowPlan.
3. Add TemplateFamily contracts for the currently symbolic instruction intents.
4. Convert VendorComponentPlan(candidate) into VerifiedVendorABIPlan(binary-ready).
5. Add a plan-level guard equivalent to check_core_functional_probe_report.py.
6. Only then implement a byte emitter.
```

The first runnable B-line target should remain conservative:

```text
GEMM no-ReLU or another already-covered local subset,
not log10max/reduce/app-storage.
```

## Final Warning

A-line's lesson is not:

```text
we know how to patch these bytes now
```

The real lesson is:

```text
binary correctness comes from making control, memory, and template facts typed
before they reach the serializer
```

If B-line skips that, it will recreate A-line's swamp with better class names.
If B-line follows it, the mud becomes a road.
