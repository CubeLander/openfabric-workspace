# RFC: DFU Task/Subtask Row Indexing Policy

Date: 2026-06-15
Status: Proposed / needs implementation after review
Scope: `ProgramBinRows`, `program_serializer.py`, SimICT `tasks_conf_info_file.bin`, `subtasks_conf_info_file.bin`

## Why This RFC Exists

After the legacy GEMM compatibility work, OpenFabric now matches the vendor legacy GEMM bundle on the large structural counts:

```text
active exeBlock rows: 256 == 256
active inst rows:     53376 == 53376
opcode counts:        equal
stage counts:         equal
```

The next mismatch class is no longer opcode/template size. It is MICC control-table layout:

```text
tasks_conf_info_file.bin
subtasks_conf_info_file.bin
```

This cannot be patched casually. Task/subtask rows are the control skeleton that tells SimICT which subtask rows belong to each task, where instance configuration rows begin, and which subtask executes next. A wrong row-index policy can produce a binary package that looks structurally valid but runs the wrong workflow.

## Current Evidence From Legacy GEMM

Source legacy bundle:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/build_out/
  gemm_template_fusion/worktree/gpdpu/users/risc_nn_riscv/testcase/
  application/gemm_template_fusion/simulator_bin
```

The current row-level diff report is:

```text
docs/compiler/binary_packaging/research_notes/archive/legacy_drafts/legacy_gemm_compat_row_diff_report.json
```

### Legacy `task_conf_info_t` Rows

Observed decoded task rows:

```text
task row 0:
  subtasks_idx = [0, 1, 2, 0, 0, 0, 0, 0]
  suc_tasks    = [0, 0, 0, 0]

task row 1:
  subtasks_idx = [8, 9, 10, 0, 0, 0, 0, 0]
  suc_tasks    = [0, 0, 0, 0]

task row 2:
  subtasks_idx = [16, 17, 18, 0, 0, 0, 0, 0]
  suc_tasks    = [0, 0, 0, 0]

task row 3:
  subtasks_idx = [24, 25, 26, 0, 0, 0, 0, 0]
  suc_tasks    = [0, 0, 0, 0]
```

This strongly suggests:

```text
subtask_global_row_index = task_index * 8 + local_subtask_index
```

where each task has a fixed slot window of eight subtask rows.

Only local subtask rows `0, 1, 2` are active in each task window for the current GEMM case. Slots `3..7` are unused.

### Legacy `sub_task_conf_info_t` Rows

Observed active legacy rows:

```text
task0: rows  0,  1,  2
task1: rows  8,  9, 10
task2: rows 16, 17, 18
task3: rows 24, 25, 26
```

The row payloads follow this pattern:

```text
prepare subtask:
  global rows: 0, 8, 16, 24
  local subtask trailer idx: 0
  is_exe_start = 1
  is_exe_end   = 0
  instances    = 1
  suc_subtasks = [next global row, 0, 0, 0]
  root_blocks  = 16
  block_amount = 16

k_stream subtask:
  global rows: 1, 9, 17, 25
  local subtask trailer idx: 1
  is_exe_start = 0
  is_exe_end   = 0
  instances    = 4
  suc_subtasks = [next global row, 0, 0, 0]
  root_blocks  = 4
  block_amount = 32

finalize/store subtask:
  global rows: 2, 10, 18, 26
  local subtask trailer idx: 2
  is_exe_start = 0
  is_exe_end   = 1
  instances    = 1
  suc_subtasks = [0, 0, 0, 0]
  root_blocks  = 16
  block_amount = 16
```

Important: the trailer `subtask_idx` is local within the task (`0, 1, 2`), while the row location and successor subtask references use global row indices (`0/1/2`, `8/9/10`, etc.).

### Legacy Instance Config Address Pattern

Legacy `instances_conf_mem_based_addr` follows active subtask order and is measured in bytes:

```text
task0 prepare: 0
task0 k_stream: 32
task0 final: 160

task1 prepare: 192
task1 k_stream: 224
task1 final: 352

task2 prepare: 384
task2 k_stream: 416
task2 final: 544

task3 prepare: 576
task3 k_stream: 608
task3 final: 736
```

This is consistent with semantic instance counts:

```text
prepare:  1 row  * 32 bytes
k_stream: 4 rows * 32 bytes
final:    1 row  * 32 bytes
per task: 6 rows * 32 bytes = 192 bytes
```

So subtask sparse row layout does **not** imply sparse instance_conf rows. Instance rows are compact by execution order.

This observation is a hard guardrail for implementation:

```text
DFU3500 legacy MICC uses sparse fixed subtask windows per task,
but instance_conf rows remain compact in active subtask execution order.
```

Fixing subtask row placement must not make instance_conf rows sparse.

## Current OpenFabric Behavior

Current code locations:

```text
compiler/gpdpu_compiler/core/program_bin.py
  _build_task_conf_rows
  _build_subtask_conf_rows

compiler/gpdpu_compiler/core/program_serializer.py
  _pack_task_conf_row
  _pack_subtask_conf_row
  _next_subtask_index_by_row_id
```

Current OpenFabric emits:

```text
subtask rows: 0,1,2,3,4,5,6,7,8,9,10,11
```

instead of legacy sparse windows:

```text
subtask rows: 0,1,2,8,9,10,16,17,18,24,25,26
```

Current task rows emit every task with:

```text
subtasks_idx = [0, 1, 2, 0xffffffff, ...]
suc_tasks    = [0xffffffff, ...]
```

instead of legacy:

```text
task0 subtasks_idx = [0, 1, 2, 0, ...]
task1 subtasks_idx = [8, 9, 10, 0, ...]
task2 subtasks_idx = [16, 17, 18, 0, ...]
task3 subtasks_idx = [24, 25, 26, 0, ...]
suc_tasks = [0, 0, 0, 0]
```

Current OpenFabric also sets `is_exe_start = true` on k_stream subtask, while legacy sets `is_exe_start = true` on prepare subtask.

## Interpretation

The evidence points to three distinct index spaces:

```text
Task row index:
  0..3
  one row per vendor task

Global subtask row index:
  task_index * 8 + local_subtask_index
  used by tasks_conf.subtasks_idx and subtask successor references

Local subtask index:
  0,1,2 within each task
  stored in sub_task_conf trailer field `subtask_idx`
```

The current OpenFabric model conflates local subtask index and global subtask row index. That is why task rows and subtask rows diverge from legacy even after counts match.

## Proposed Policy

### 1. Fixed Subtask Window Per Task

For the current DFU3500 / SimICT legacy compatibility profile:

```text
SUBTASK_SLOT_COUNT_PER_TASK = 8
subtask_global_row_index = task_index * 8 + local_subtask_index
```

This should live with DFU3500 vendor ABI facts, not generic compiler semantics.
Use a deliberately vendor-shaped helper name such as:

```python
def dfu3500_legacy_subtask_row_index(
    task_index: int,
    local_subtask_index: int,
) -> int:
    return task_index * DFU3500_SUBTASK_SLOT_COUNT_PER_TASK + local_subtask_index
```

The long name is intentional: this is a DFU3500 / SimICT legacy ABI fact, not
an OpenFabric-wide indexing abstraction.

### 1A. Physical Subtask Table Emission Uses Sparse Global Rows

`subtasks_conf_info_file.bin` is a fixed 32-row physical table. Active subtask
rows must be placed at their global row index, leaving inactive/filler rows
inside each task's 8-row window:

```text
active planning order:
  task0.s0, task0.s1, task0.s2, task1.s0, ...

physical subtask table rows:
  0,1,2, empty, empty, empty, empty, empty,
  8,9,10, empty, ...
```

The serializer already writes a fixed-capacity table. The row planner must set
`SubtaskConfBinRow.global_row_index` to the sparse physical row index so active
rows land in legacy-compatible positions.

### 1B. Instance Rows Remain Compact

This RFC changes only task/subtask control row indexing. It must not change
`instance_conf_info_t` row allocation.

Even though subtask rows are sparse, instance rows remain compact in active
subtask execution order:

```text
instance row 0: task0 prepare
instance row 1..4: task0 k_stream k0..k3
instance row 5: task0 final
instance row 6: task1 prepare
...
```

`instances_conf_mem_based_addr` should continue to advance by active instance
rows in execution order. Do not derive instance row addresses from sparse
subtask row indices.

### 2. Task Rows Reference Global Subtask Rows

`TaskConfBinRow.active_subtask_indices` and `subtasks_idx_slots` should carry global subtask row indices:

```text
task0: [0, 1, 2, 0, 0, 0, 0, 0]
task1: [8, 9, 10, 0, 0, 0, 0, 0]
task2: [16, 17, 18, 0, 0, 0, 0, 0]
task3: [24, 25, 26, 0, 0, 0, 0, 0]
```

Open question: unused task slots should probably use zero for legacy compatibility, not `0xffffffff`. In this legacy case, zero is ambiguous because subtask row 0 is valid. However vendor code appears to rely on `subtasks_amount` to determine how many slots are active, so unused slots are ignored.

Keep two concepts separate in row planning:

```text
active_subtask_indices = (8, 9, 10)
subtasks_idx_slots     = (8, 9, 10, 0, 0, 0, 0, 0)
```

The former is semantic. The latter is legacy byte emission.

### 3. Subtask Rows Use Sparse Global Row Index

`SubtaskConfBinRow.global_row_index` should be:

```text
task_index * 8 + local_subtask_index
```

`SubtaskConfBinRow.subtask_index` should remain local (`0, 1, 2`) because this is what legacy writes into the trailer.

### 4. Subtask Successors Reference Global Row Indices

For local chain prepare -> k_stream -> final:

```text
prepare.suc_subtasks = [global_k_stream_row, 0, 0, 0]
k_stream.suc_subtasks = [global_finalize_row, 0, 0, 0]
final.suc_subtasks = [0, 0, 0, 0]
```

The helper currently named `_next_subtask_index_by_row_id` should be renamed or clarified, because the serializer needs the next **global subtask row index**, not the next local subtask index.

### 5. Subtask Start/End Flags Follow Legacy Chain

For the current profile:

```text
prepare:  is_exe_start = true,  is_exe_end = false
k_stream: is_exe_start = false, is_exe_end = false
final:    is_exe_start = false, is_exe_end = true
```

This differs from the current OpenFabric row planner, which marks k_stream as start.

### 6. Task Successor Slots Use Zero Fill For Legacy Compatibility

For `task_successor_policy = independent_start_end`, legacy uses:

```text
suc_tasks = [0, 0, 0, 0]
```

not sentinel values. This should be treated as a serializer/profile detail:

```text
active count field controls valid successor slots;
unused slots are zero-filled in legacy-compatible byte mode.
```

This zero-fill is a byte-emission compatibility policy, not graph semantics.
It must not be interpreted as a real task0 successor edge.

## Non-Goals

This RFC does not solve:

1. instruction row field parity (`imms`, `src_operands_idx`, forwarding/bypass bits);
2. exeBlock row ordering beyond the task/subtask row index implications;
3. instance_conf full-table sentinel/base_addr fill policy;
4. multi-app inter-task dependency semantics beyond the current GEMM four-task legacy shape.

Those should be follow-up RFCs or implementation tasks after the MICC row indexing policy is fixed.

## Implementation Plan

### Step 1: Add Explicit Subtask Row Index Policy

Add a small DFU3500 policy helper, likely in `program_bin.py` first and later moved into `core/dfu3500` if it grows:

```python
def _global_subtask_row_index(task_index: int, local_subtask_index: int) -> int:
    return task_index * TASK_SUBTASK_SLOT_COUNT + local_subtask_index
```

Use this in:

```text
_build_task_conf_rows
_build_subtask_conf_rows
```

### Step 2: Separate Local And Global Subtask Indices

Ensure each row plan exposes both:

```text
local_subtask_index: 0/1/2
global_row_index: task_index * 8 + local_subtask_index
```

`SubtaskConfBinRow.subtask_index` should remain the local trailer value.

### Step 3: Change Task Slot Padding Policy For Legacy Bytes

For legacy-compatible MICC rows:

```text
unused task subtask slots -> 0
unused task successor slots -> 0
```

Do not globally replace all padding helpers; exeBlock edge slots and other sentinel-bearing structures may still intentionally use `0xffffffff` or string placeholders in planning.

### Step 4: Fix Subtask Start/End Flags

Change `_build_subtask_conf_rows` from role-based `k_stream` start to:

```text
prepare/first local subtask is start
final/last local subtask is end
```

For current GEMM roles this means:

```text
accumulator_prepare -> start
k_stream            -> middle
finalize_store      -> end
```

### Step 5: Fix Subtask Successor Reference Emission

Change serializer helper from local next index to global next row:

```text
current global row 0 -> successor 1
current global row 1 -> successor 2
current global row 2 -> no successor
current global row 8 -> successor 9
...
```

### Step 6: Add Tests

Update / add assertions around:

```text
task0 subtasks_idx == [0,1,2,0,0,0,0,0]
task1 subtasks_idx == [8,9,10,0,0,0,0,0]
task2 subtasks_idx == [16,17,18,0,0,0,0,0]
task3 subtasks_idx == [24,25,26,0,0,0,0,0]

active subtask rows == [0,1,2,8,9,10,16,17,18,24,25,26]

subtask row 0 start/end == (1,0)
subtask row 1 start/end == (0,0)
subtask row 2 start/end == (0,1)

subtask row 8 successor == 9
subtask row 9 successor == 10
```

Then re-run:

```text
pytest -q tests/test_chip_program_frontend.py -x
pytest -q
```

Finally regenerate:

```text
docs/compiler/binary_packaging/research_notes/archive/legacy_drafts/legacy_gemm_compat_row_diff_report.json
```

## Expected Effect

This should substantially reduce or eliminate row-index MICC diffs:

```text
tasks row field diffs:
  subtasks_idx
  suc_tasks

subtasks row presence diffs:
  only_legacy rows 8/9/10/16/17/18/24/25/26
  only_candidate rows 3/4/5/6/7/11

subtasks field diffs:
  is_exe_start
  suc_subtasks
  subtask_idx/task_idx row placement confusion
```

It will likely also improve downstream exeBlock diff readability, because `task_idx/subtask_idx` and embedded subtask windows will align better with legacy.

## Open Questions

### Q1: Are unused task slots always zero-filled?

Legacy GEMM uses zero fill. We should use this for legacy-compatible MICC emission, but keep the question open for other vendor cases until more evidence appears.

### Q2: Are task successor slots semantic or ignored by `is_exe_end` / task count?

Legacy independent tasks use `[0,0,0,0]`. This looks like zero-fill rather than a real task0 successor edge, because all tasks also have `is_exe_start = is_exe_end = true`.

### Q3: Should this policy live in DFU3500 config?

Probably yes. For MVP, implement in `program_bin.py` as a named helper with a comment tying it to DFU3500 legacy MICC ABI. Later move to `core/dfu3500` if more chip-specific row policies accumulate.

## Recommendation

Implement this RFC before touching instruction-level field parity. The task/subtask row-index policy is a control-table ABI fact, and fixing it first will make all later row-by-row diffs easier to interpret.
