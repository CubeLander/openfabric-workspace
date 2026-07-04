# RFC: DFU3500 Legacy Instance Config Table Layout

Date: 2026-06-15

## Status

Accepted for implementation.

```text
priority: P0 / P1
nature: DFU3500 CBUF physical table layout fix
risk: medium-low
benefit: high
```

This RFC updates the current binary serializer plan after cross-checking
`docs_refactored/runtime/data/cbuf.md` against the vendor GEMM implementation.

The central correction is:

```text
ProgramBinRows must distinguish semantic active instance rows from the physical
DFU3500 instance_conf_info_file.bin fixed-slot table.
```

Current OpenFabric code correctly emits the fixed-size file, but it only fills
compact active instance rows. Legacy DFU3500 fills the full physical table:

```text
4 tasks * 8 subtask slots * 2048 instance slots = 65536 rows
```

Hard guardrail:

```text
Do not derive sub_task_conf_info_t.instances_conf_mem_based_addr from the
physical instance_conf_info_file.bin row index.

Legacy MICC keeps compact instance_conf offsets in subtask rows, while the
physical CBUF instance table is emitted as a fixed DFU3500
task/subtask/instance window.
```

## Current State

### Already Aligned

Recent work aligned the MICC task/subtask row indexing policy:

```text
task_conf_info_t.subtasks_idx:
  uses global subtask row index

sub_task_conf_info_t physical row:
  task_index * 8 + local_subtask_index

sub_task_conf_info_t.subtask_idx trailer:
  remains local subtask index

suc_subtasks:
  uses global subtask row index
```

Current row diff shows:

```text
tasks:
  active rows match legacy

subtasks:
  active rows match legacy
```

### Still Mismatched

`instance_conf_info_file.bin` still differs:

```text
legacy:
  65536 physical rows contain role-specific values or 0xffffffff filler

OpenFabric:
  only compact active rows are written
  unwritten physical rows remain zero
```

This matters because `instance_conf_info_t.base_addr[4]` participates in
runtime address calculation:

```text
effective_addr = base_addr[base_addr_idx] + imm
```

So this is not just cosmetic byte parity.

## Evidence

### Legacy CBUF Layout

The local runtime data notes record:

```text
instance_conf_info_file.bin = 2,097,152 B
                            = 4 task * 8 subtask * 2048 instance * 32 B
```

### Legacy Generator

The vendor GEMM generator:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/build_out/gemm_template_fusion/worktree/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/csv_generate/test_app_conf_generate.c
```

loops:

```text
for each task file j in 0..3
  for each subtask slot n in MAX_SUBTASK_NUM
    write 2048 instance_conf_info_t rows
```

Then `csv_generate/run.sh` concatenates:

```text
instance_conf_info_file0.bin
instance_conf_info_file1.bin
instance_conf_info_file2.bin
instance_conf_info_file3.bin
```

into final:

```text
simulator_bin/instance_conf_info_file.bin
```

### Observed Legacy Rows

Actual legacy GEMM rows:

```text
row 0:
  (0x20000, 0xffffffff, 0xffffffff, 0xffffffff)

row 2048:
  (0x0, 0x10000, 0xffffffff, 0xffffffff)

row 2049:
  (0x20, 0x14000, 0xffffffff, 0xffffffff)

row 4096:
  (0x20000, 0xffffffff, 0xffffffff, 0xffffffff)

row 6144:
  (0xffffffff, 0xffffffff, 0xffffffff, 0xffffffff)

row 16384:
  (0x20000, 0xffffffff, 0xffffffff, 0xffffffff)
```

These rows prove task/subtask-window physical placement:

```text
row = task_index * 8 * 2048
    + local_subtask_index * 2048
    + instance_index
```

### Runtime CBUF Transfer

`DPU_CbufTransfer()` transfers the CBUF blob that contains:

```text
insts_file.bin
exeblock_conf_info_file.bin
instance_conf_info_file.bin
```

The instance table is part of runtime-facing CBUF state.

### Runtime Instance Base

`DPU_Kernel_Start()` writes:

```text
MICC_INSTANCE_BASE
MICC_INSTANCE_BASE_NONEED
```

This suggests runtime instance addressing has additional dynamic base semantics.
Do not reduce the model to `instances_conf_mem_based_addr` alone.

## Problem

The current implementation conflates:

```text
semantic active subtask instances
```

with:

```text
physical CBUF instance_conf table rows
```

Current `_build_instance_conf_rows()` allocates:

```text
row 0..23 for active semantic instances
```

but legacy expects physical positions like:

```text
task0 subtask0 instance0 -> row 0
task0 subtask1 instance0 -> row 2048
task0 subtask2 instance0 -> row 4096
task1 subtask0 instance0 -> row 16384
...
```

Additionally, current serializer leaves unwritten rows as zero. Legacy fills:

```text
active windows:
  role-specific base addresses

inactive windows:
  0xffffffff sentinel values
```

There are now five distinct index spaces:

```text
1. task row index
   0..3

2. local subtask index
   0, 1, 2 inside each task

3. global subtask row index
   task_index * 8 + local_subtask_index

4. compact semantic instance order
   used by instances_conf_mem_based_addr and already matching legacy

5. physical instance_conf row index
   task_index * 8 * 2048
 + local_subtask_index * 2048
 + instance_index
```

Previous task/subtask work separated 1, 2, and 3. This RFC separates 4 and 5.

## Goals

1. Emit `instance_conf_info_file.bin` with the legacy physical row layout.
2. Preserve semantic reports that explain active instance count separately.
3. Keep task/subtask MICC row parity intact.
4. Avoid moving DFU3500-specific constants into generic frontend IR.
5. Improve row-level diff so the remaining instance mismatch is meaningful.

## Non-Goals

1. Do not change `task_conf_info_t` or `sub_task_conf_info_t` indexing policy.
2. Do not change `instances_conf_mem_based_addr` until simulator evidence
   proves it is necessary.
3. Do not redesign `VendorLoopVariantBinding`.
4. Do not attempt full byte-for-byte parity for `inst_t` fields in this RFC.
5. Do not generalize this policy to future non-DFU backends.

## Proposed Design

### Constants

Add explicit DFU3500 legacy constants:

```python
DFU3500_LEGACY_TASK_COUNT = 4
DFU3500_LEGACY_SUBTASK_SLOTS_PER_TASK = 8
DFU3500_LEGACY_INSTANCES_PER_SUBTASK_SLOT = 2048
```

Use existing global capacities where appropriate, but keep the naming explicit.

### Row Index Helper

Add:

```python
def dfu3500_legacy_instance_conf_row_index(
    task_index: int,
    local_subtask_index: int,
    instance_index: int,
) -> int:
    return (
        task_index * DFU3500_LEGACY_SUBTASK_SLOTS_PER_TASK
        * DFU3500_LEGACY_INSTANCES_PER_SUBTASK_SLOT
        + local_subtask_index * DFU3500_LEGACY_INSTANCES_PER_SUBTASK_SLOT
        + instance_index
    )
```

This helper must not be named generically. It is a vendor ABI fact.

### Physical Row Plan

Build instance rows for all physical slots:

```text
for task_index in 0..3:
  for local_subtask_index in 0..7:
    for instance_index in 0..2047:
      emit one InstanceConfBinRow
```

This changes:

```text
len(instance_rows): 24 -> 65536
```

but report both:

```text
semantic_active_instance_row_count = 24
physical_instance_row_count = 65536
role_filled_window_row_count = 4 tasks * 3 active subtask windows * 2048
                             = 24576
inactive_filler_row_count = 4 tasks * 5 inactive subtask windows * 2048
                          = 40960
```

Do not call all nonzero/sentinel rows “active”. Many rows are role-filled
physical rows, not semantically executed instances.

### Role-Specific Base Address Fill

For current GEMM legacy compatibility:

```text
local subtask 0:
  base_addr[0] = SPM_GEMM_INPUT3_ADDR
  base_addr[1..3] = 0xffffffff

local subtask 1:
  base_addr[0] = SPM_GEMM_INPUT1_ADDR + instance_idx * A_stride
  base_addr[1] = SPM_GEMM_INPUT2_ADDR + instance_idx * B_stride
  base_addr[2..3] = 0xffffffff

local subtask 2:
  base_addr[0] = SPM_GEMM_INPUT3_ADDR
  base_addr[1..3] = 0xffffffff

local subtask 3..7:
  base_addr[0..3] = 0xffffffff
```

For the current GEMM configuration:

```text
SPM_GEMM_INPUT1_ADDR = 0x0
SPM_GEMM_INPUT2_ADDR = 0x10000
SPM_GEMM_INPUT3_ADDR = 0x20000

A_stride = 64 * sizeof(short) / sizeof(float)
         = 0x20

B_stride = 64 * GEMM_INPUT2_WIDTH_app * sizeof(short) / sizeof(float)
         = 0x4000
```

These constants should come from the DFU3500 GEMM legacy profile / chip config,
not from arbitrary serializer literals if avoidable.

The helper should accept `task_index`, even if the first implementation is
task-independent:

```python
def dfu3500_legacy_gemm_instance_base_addr_words(
    task_index: int,
    local_subtask_index: int,
    instance_index: int,
    profile: Dfu3500LegacyGemmProfile,
) -> tuple[int, int, int, int]:
    ...
```

This keeps the interface ready for task/app ping-pong base selection without
changing call sites later.

### Active Semantic Mapping

`SubtaskConfBinRow.instance_conf_row_ids` should continue to refer to the rows
for active semantic instances. After physical placement, for task0:

```text
subtask0 active row ids:
  row 0

subtask1 active row ids:
  rows 2048, 2049, 2050, 2051

subtask2 active row ids:
  row 4096
```

This is useful for debug/reverse-map, even though the physical component
contains all rows.

Important: role-filled windows must be filled as whole windows, not only the
semantic rows. For example:

```text
local subtask 0:
  row 0 is semantically executed for prepare
  row 1..2047 may not execute
  legacy still fills row 1..2047 with the same subtask0 base pattern

local subtask 1:
  row 2048..4095 are all filled with A/B stride pattern
  not just rows 2048..2051
```

### `instances_conf_mem_based_addr`

Keep current legacy-matching MICC field behavior for now:

```text
subtask0 task0: 0
subtask1 task0: 32
subtask2 task0: 160
subtask0 task1: 192
...
```

This looks compact, but it matches legacy `subtasks_conf_info_file.bin`.

Do not “fix” it to physical row byte offsets in this RFC. That would break the
task/subtask parity just achieved and is not justified by available evidence.

The implementation should include a hard comment equivalent to:

```python
# Do not derive instances_conf_mem_based_addr from the physical
# instance_conf_info_file.bin row index.
#
# Legacy MICC keeps compact instance_conf offsets in subtask rows,
# while the physical CBUF instance table is emitted as a fixed
# DFU3500 task/subtask/instance window.
```

### Serializer Fill Policy

After this RFC, `_serialize_instance_conf_component()` should no longer depend
on zero-initialized holes for unused rows.

Instead:

```text
all 65536 rows should be present in ProgramBinRows.instance_rows
```

and serializer simply writes them.

If later we choose sparse internal storage for memory reasons, the serializer
must still apply an explicit DFU3500 filler policy:

```text
inactive row = (0xffffffff, 0xffffffff, 0xffffffff, 0xffffffff)
```

Do not silently leave rows as zero.

## Implementation Plan

### Step 1: Add Physical Index Helper

Add `dfu3500_legacy_instance_conf_row_index()` near the existing
`dfu3500_legacy_subtask_row_index()`.

Add unit assertions for:

```text
(0, 0, 0) -> 0
(0, 1, 0) -> 2048
(0, 2, 0) -> 4096
(0, 3, 0) -> 6144
(1, 0, 0) -> 16384
(2, 0, 0) -> 32768
(3, 7, 2047) -> 65535
```

### Step 2: Add Legacy GEMM Instance Fill Function

Add a focused helper:

```python
dfu3500_legacy_gemm_instance_base_addr_words(
    task_index: int,
    local_subtask_index: int,
    instance_index: int,
    profile: Dfu3500LegacyGemmProfile,
) -> tuple[int, int, int, int]
```

First implementation can target current GEMM compatibility only.

### Step 3: Build Physical Rows

Change `_build_instance_conf_rows()` so it emits the physical table for the
current DFU3500 legacy profile. The loop must be physical-slot driven:

```python
for task_index in range(4):
    for local_subtask_index in range(8):
        for instance_index in range(2048):
            row_index = dfu3500_legacy_instance_conf_row_index(
                task_index,
                local_subtask_index,
                instance_index,
            )
```

Do not drive physical row emission only from active semantic instances.

Preserve provenance:

```text
source active vendor subtask id
source active instance key
physical task/subtask/instance slot
role
is_semantic_active
```

If the existing `InstanceConfBinRow` does not have enough fields, add metadata
fields conservatively.

### Step 4: Keep MICC Field Stable

Ensure `_build_subtask_conf_rows()` still sets:

```text
instances_conf_mem_based_addr
```

to the legacy compact values that already match row diff.

Do not derive that field from the new physical `global_row_index`.

### Step 5: Update Serializer Report

Update instance report to show:

```text
semantic_active_instance_row_count
physical_instance_row_count
role_filled_window_row_count
inactive_filler_row_count
legacy_fixed_window_layout = true
```

Avoid reporting `row_count = 65536` as if all rows are executed.

### Step 6: Update Row Diff Expectations

Expected after implementation:

```text
instance_conf_info_file.bin:
  candidate nonzero/sentinel rows = 65536
  legacy nonzero/sentinel rows    = 65536
```

Where “active” in current diff means “nonzero or sentinel bytes present”, not
semantic activity. Rename or supplement it to avoid confusion:

```text
nonzero_row_count
semantic_active_row_count
role_filled_window_row_count
inactive_filler_row_count
```

### Step 7: Run Tests

Run:

```text
pytest -q tests/test_chip_program_frontend.py -x
pytest -q
```

Regenerate:

```text
docs/compiler/binary_packaging/research_notes/archive/legacy_drafts/legacy_gemm_compat_row_diff_report.json
```

## Expected Effects

### Binary Shape

Before:

```text
OpenFabric instance rows written:
  24 compact rows

unwritten rows:
  zero
```

After:

```text
OpenFabric instance rows written:
  65536 fixed physical rows

inactive windows:
  0xffffffff sentinel rows

active GEMM windows:
  legacy-compatible base_addr pattern
```

### Row Diff

Expected improvement:

```text
instances active/nonzero row count:
  legacy == candidate == 65536
```

Likely remaining mismatches after this RFC:

```text
if base_addr constants / strides are exact:
  instance rows should largely or fully match legacy

if task/app ping-pong base selection differs:
  mismatches will reveal precise address-policy gaps
```

### Runtime Risk Reduction

This removes a dangerous ambiguity:

```text
current package may read zero base_addr rows if MICC uses fixed-window
physical addressing.
```

After this RFC, any valid fixed-window row contains either a meaningful base
address or explicit `0xffffffff` sentinel, matching vendor behavior.

## Validation Gates

### Gate A: Physical Row Formula

Hard assertions for known row indices:

```text
task0/subtask1/instance0 -> row 2048
task1/subtask0/instance0 -> row 16384
task3/subtask7/instance2047 -> row 65535
```

### Gate B: Legacy Sample Rows

For the current GEMM profile:

```text
row 0    == (0x20000, 0xffffffff, 0xffffffff, 0xffffffff)
row 2048 == (0x0, 0x10000, 0xffffffff, 0xffffffff)
row 2049 == (0x20, 0x14000, 0xffffffff, 0xffffffff)
row 4096 == (0x20000, 0xffffffff, 0xffffffff, 0xffffffff)
row 6144 == (0xffffffff, 0xffffffff, 0xffffffff, 0xffffffff)
```

### Gate C: MICC Stability

Task/subtask rows must remain matched:

```text
tasks mismatched shared rows = 0
subtasks mismatched shared rows = 0
```

### Gate D: Semantic Counts

Reports must distinguish:

```text
semantic_active_instance_row_count = 24
physical_instance_row_count = 65536
```

### Gate E: No Generic Leakage

The helper names and constants must clearly say DFU3500 / legacy. Do not expose
fixed-window instance layout as a generic OpenFabric assumption.

## Risks

### Risk 1: `instances_conf_mem_based_addr` Formula Is Still Not Fully Proven

We have original code evidence for:

```text
compact MICC offsets
fixed physical CBUF instance table
runtime MICC_INSTANCE_BASE
```

but not the closed MICC simulator formula.

Mitigation:

```text
Do not change MICC offsets in this RFC.
Only align physical CBUF table.
```

### Risk 2: Current GEMM Constants Are Profile-Specific

The first implementation may hardcode current GEMM dimensions/regions.

Mitigation:

```text
Place constants in DFU3500 legacy GEMM profile/chip config.
Document that it is not generic.
```

### Risk 3: Row Diff Terminology Is Misleading

Current row diff calls sentinel-filled rows “active” because bytes are nonzero.

Mitigation:

```text
Rename or supplement with semantic/nonzero counts.
```

## Recommended Next Step

Implement this RFC before continuing lower-level instruction-field parity.

Rationale:

```text
instruction/exeBlock/task/subtask shapes are now close enough that the
remaining large CBUF mismatch is dominated by instance_conf physical table
layout.
```

Once this lands, the serializer will have a much cleaner foundation:

```text
ProgramVendorABI
  -> ProgramBinRows with legacy physical instance table
  -> serializer writes bytes without reinterpreting instance semantics
```
