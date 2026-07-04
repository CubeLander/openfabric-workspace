# RFC: GEMM Task Planning Policy

Date: 2026-06-16
Status: Revised / needs review
Scope: `ProcessorTaskPlan`, `ProcessorTileProgram`, `DFUPackingProgram`,
`ProgramVendorABI`, DFU3500 legacy GEMM compatibility

## Why This RFC Exists

OpenFabric currently emits a DFU3500-compatible GEMM package with four vendor
task rows for `gemm_template_fusion`. This matches the vendor case shape:

```text
app0.conf -> task0
app1.conf -> task1
app2.conf -> task2
app3.conf -> task3
```

Each task owns three active subtasks:

```text
subtask0: accumulator prepare,  Instance Times = 1
subtask1: K streaming GEMM,     Instance Times = 4
subtask2: finalize/store,       Instance Times = 1
```

However, the current OpenFabric implementation did not come from a deliberately
designed top-level task planner. It grew out of the early SUMMA tile lowering
implementation:

```python
launch_group_id = wave_id // max_tasks
task_id = wave_id % max_tasks
```

That rule is useful for the current `128x128` local output with `64x64` tiles,
because each processor has exactly four output-tile waves:

```text
wave0 -> C local tile (m0, n0) -> task0
wave1 -> C local tile (m0, n1) -> task1
wave2 -> C local tile (m1, n0) -> task2
wave3 -> C local tile (m1, n1) -> task3
```

But this is currently implicit. Worse, downstream packing currently reconstructs
the task id from `wave_id` again:

```python
task_id = f"task{assignment.wave_id}"
```

For the current case `wave_id in {0,1,2,3}`, both rules agree. For larger tile
counts they diverge:

```text
tile lowering says:
  wave4 -> launch_group1/task0

packing currently says:
  wave4 -> task4
```

DFU3500 has only four vendor task rows. So this is not a harmless detail. It is
a hidden ABI boundary bug waiting for a slightly larger GEMM.

## Current Evidence

### Current OpenFabric Code

`ProcessorTileProgram` already records `launch_group_id` and `task_id` on each
GEMM tile phase:

```text
compiler/gpdpu_compiler/core/program_tile.py
  wave_id = 0
  for m_tile in range(m_tiles):
      for n_tile in range(n_tiles):
          launch_group_id = wave_id // self.max_tasks
          task_id = wave_id % self.max_tasks
```

It also builds a `task_plan` with three subtasks per task:

```text
subtask0: init_c_accumulator
subtask1: stream_k_blocks
subtask2: apply_post_ops_and_store_c
```

`DFUPackingProgram` currently ignores the explicit `task_id` carried by tile
phase payloads and rebuilds task id from the node's `wave_id`.

### Git History

The wave-to-task mapping first appeared in the legacy tracing path:

```text
commit e4ec0a7 继续完善compiler
  compiler/gpdpu_compiler/core/pe_trace.py
```

It was later copied into the new `ProcessorTileProgram` during:

```text
commit ddd5bc6 Refactor chip frontend lowering pipeline
```

The current `program_packing.py` reconstruction:

```python
task_id = f"task{assignment.wave_id}"
```

was introduced later during:

```text
commit c812be9 compiler重构阶段性提交
```

That means the current behavior is not a cleanly designed task planner. It is a
historical compatibility rule that became part of the lowering stack.

### Vendor Shape

The vendor GEMM case uses four task/app conf files:

```text
gemm_template_fusion/app0.conf
gemm_template_fusion/app1.conf
gemm_template_fusion/app2.conf
gemm_template_fusion/app3.conf
```

Each file has one task and three subtasks. The middle subtask repeats four K
instances. This supports the interpretation:

```text
vendor task = one output-tile wave profile
vendor instance = one K block within that wave
```

For the current legacy GEMM profile, four vendor tasks correspond naturally to
the four local output tiles per processor.

## DFU3500 Execution Model Background

This RFC depends on several DFU3500 / SimICT execution facts that are easy to
confuse:

### Vendor task rows

DFU3500 exposes up to four task rows in the MICC task table:

```text
task0
task1
task2
task3
```

For the legacy GEMM case, these task rows are used as four independent output
tile-wave slots. They are not frontend mathematical GEMM tasks.

### Subtask rows

Each task owns a fixed window of eight subtask slots:

```text
global_subtask_row = task_id * 8 + local_subtask_id
```

For current GEMM only three local subtasks are active:

```text
subtask0: accumulator prepare
subtask1: K-stream repeated body
subtask2: finalize/store
```

Slots `3..7` are inactive/filler rows in the legacy-compatible binary layout.

### Hardware instance loop

The repeated K body is represented by vendor subtask instance repeat:

```text
subtask1 Instance Times = k_blocks
```

The hardware model is:

```text
deploy one subtask body template
repeat it for each instance
each instance selects a base-address row
each PE instruction contributes its own static offset
final address = base_addr[slot] + instruction_offset
```

The instance base-address table has fixed physical CBUF capacity:

```text
4 tasks * 8 subtasks/task * 2048 instances/subtask
```

These dimensions are separate:

```text
task:
  output-tile-wave slot

subtask:
  phase role inside that wave

instance:
  repeated K block inside k_stream
```

The current bug risk comes from collapsing these dimensions into one integer
called `wave_id`.

### OpenFabric lowering consequence

Task planning must happen after logical processor placement is known but before
tile route/compute/store actions are finalized. At that point the compiler knows:

```text
processor shape
local GEMM tile grid
tile sizes
K block count
DFU3500 max task slots
legacy subtask/instance profile
```

Before this point, the frontend lacks enough backend information. After this
point, packing and binary layers should only consume the chosen plan.

## Desired Invariant

Task assignment must become a first-class planning decision:

```text
ProcessorLogicalProgram
  -> ProcessorTaskPlan
  -> ProcessorTileProgram
  -> DFUPackingProgram
  -> ProgramVendorABI
  -> ProgramBinRows
```

`ProcessorTaskPlan` is the first layer where vendor-compatible task/subtask
assignment becomes explicit. Downstream layers must consume the chosen task
assignment. They must not rediscover task ids from `wave_id`, `phase_id`,
string parsing, or block order.

Hard invariant:

```text
task_id is assigned exactly once by the task planner.
```

After that:

```text
ProcessorTaskPlan
  owns task planning metadata and assignment

ProcessorTileProgram
  consumes task plan while generating tile actions

DFUPackingProgram
  consumes task-aware tile actions and micro-blocks

ProgramVendorABI / ProgramBinRows
  project and serialize vendor rows
```

No later layer may reinterpret `wave_id` as a vendor task id.

A vendor task id is a physical task-table slot, not a globally unique GEMM wave
id. For uniqueness across larger GEMMs, use:

```text
(launch_group_id, task_id)
```

not `task_id` alone.

## Where The Policy Is Introduced

There are two different things that should not be collapsed:

```text
frontend scheduling intent / backend hint
  says which policy family is acceptable

tile-level task assignment
  computes concrete launch_group_id/task_id/subtask/instance mapping
```

The frontend GEMM op may carry an optional backend scheduling hint:

```python
matmul(..., attrs={
    "dfu_task_policy": "legacy_output_wave_tasks",
})
```

or the same hint may be selected by chip/profile config:

```text
dfu3500 legacy GEMM profile -> legacy_output_wave_tasks
```

But the frontend must not compute vendor task ids. At op-call time the compiler
does not yet have all backend facts needed for the concrete assignment:

```text
local output tile count
tile sizes
K block count
vendor max task slots
launch-group support
legacy subtask/instance profile
```

Therefore the recommended layering is:

```text
ChipProgram / GEMM op
  may carry backend scheduling hint only

ProcessorLogicalProgram
  describes per-processor logical compute/dataflow intent

ProcessorTaskPlan
  computes concrete TileTaskAssignment

ProcessorTileProgram
  expands task-aware waves into tile route/compute/store actions

DFUPackingProgram
  consumes task-aware tile actions and micro-blocks

ProgramVendorABI
  projects assignment into task/subtask rows

ProgramBinRows
  serializes rows
```

For the first implementation, `ProcessorTaskPlan` can be implemented as an
internal sub-pass inside `program_tile.py`, because that file already has access
to `m_tiles`, `n_tiles`, `k_blocks`, and chip vendor limits.

Architecturally, however, it should be treated as a distinct intermediate
product:

```text
ProcessorLogicalProgram
  -> ProcessorTaskPlan
  -> ProcessorTileProgram
```

If it grows more complex, split it into a dedicated module:

```text
ProcessorLogicalProgram
  -> program_task.py / ProcessorTaskPlan
  -> ProcessorTileProgram
```

The important rule is not the file name. The important rule is:

```text
frontend selects or hints policy;
logical-to-task planning computes assignment;
tile lowering consumes assignment;
packing never rediscovers assignment.
```

## Proposed Model

### New Concept: `ProcessorTaskPlan`

Add a task-plan layer between processor logical lowering and tile action
lowering:

```python
@dataclass(frozen=True)
class ProcessorTaskPlan:
    chip: str
    source_program: str
    policy: GemmTaskPlanningPolicy
    assignments: tuple[TileTaskAssignment, ...]
    launch_groups: tuple[TaskLaunchGroup, ...]
```

This layer should be dumpable and reviewable on its own. It answers:

```text
which output wave goes to which vendor task slot
which subtasks exist inside that task
which subtask owns the repeated K loop
which launch group owns this set of task slots
```

It does not yet create detailed route/compute/store actions. Those remain
`ProcessorTileProgram` responsibility.

### New Concept: `GemmTaskPlanningPolicy`

Introduce an explicit policy object or dataclass owned by DFU3500 GEMM lowering:

```python
@dataclass(frozen=True)
class GemmTaskPlanningPolicy:
    policy_name: str
    max_vendor_tasks: int
    task_axis: str
    wave_order: str
    overflow_policy: str
    supports_multi_launch: bool
```

MVP policy:

```text
policy_name      = "dfu3500_legacy_gemm_output_wave_tasks"
max_vendor_tasks = 4
task_axis        = "output_tile_wave"
wave_order       = "row_major_m_then_n"
overflow_policy  = "launch_group_round_robin"
supports_multi_launch = False
```

### Explicit Task Assignment

For each output tile wave:

```python
wave_id = m_tile * n_tiles + n_tile
launch_group_id = wave_id // max_vendor_tasks
task_id = wave_id % max_vendor_tasks
```

The planner emits:

```python
@dataclass(frozen=True)
class TileTaskAssignment:
    wave_id: int
    launch_group_id: int
    task_id: int
    task_name: str
    m_tile: int
    n_tile: int
    k_blocks: int
    policy_name: str
    max_vendor_tasks: int
    subtask_role_map: dict[str, str]
    subtask_plan: tuple[TileSubtaskPlan, ...]
```

Type contract:

```text
task_id:
  physical vendor task-table slot index, int, range [0, max_vendor_tasks)

task_name:
  stable ABI/debug name derived by the planner, e.g. "task0"
```

Logical checks should use `task_id` as an integer. Serialization and debug names
should use `task_name`. Avoid comparing against string task names in compiler
logic.

Each `TilePhase`, `TileLoopRegion`, `TileMicroBlock`, and downstream
`ProgramNode` should carry the same assignment identity copied from
`ProcessorTaskPlan`:

```text
task_id
task_name
launch_group_id
wave_id
m_tile
n_tile
task_planning_policy
```

Verifier identity should use:

```python
assignment_key = (
    policy_name,
    wave_id,
    launch_group_id,
    task_id,
    m_tile,
    n_tile,
)
```

Checking only `task_id` is not sufficient because different launch groups may
legally reuse the same physical task slot.

### Subtask Plan

For the current GEMM:

```text
subtask0:
  role = accumulator_prepare
  instance_count = 1

subtask1:
  role = k_stream
  instance_count = k_blocks
  repeat_semantics = vendor_instance_repeat_whole_subtask_body

subtask2:
  role = finalize_store
  instance_count = 1
```

This should remain the source of truth for:

```text
VendorSubtaskRow.instances_amount
instance_conf role
MICC subtask start/end flags
CBUF base_addr table windows
```

## What `wave_id` Should Mean

`wave_id` is still useful, but only as logical/debug origin:

```text
wave_id = row-major output-tile-wave index within a processor's local C tile
```

It must not be treated as a vendor task id directly.

For current `gemm_template_fusion`:

```text
wave_id == task_id
```

only because:

```text
m_tiles * n_tiles == max_vendor_tasks == 4
```

That equality is a profile-specific coincidence, not a general compiler law.

## How This Fits Current DFU3500 Hardware Loop Semantics

The vendor hardware loop model says:

```text
4 tasks * 8 subtasks * 2048 instance base-address rows
```

The task planner determines which semantic output-tile wave occupies which
vendor task slot.

The subtask planner determines which role occupies which subtask slot:

```text
slot0 = prepare
slot1 = K-loop repeated body
slot2 = finalize/store
slot3..7 = inactive/filler
```

The instance planner determines which base-address rows belong to each K
instance:

```text
subtask1 instance0 -> K block 0
subtask1 instance1 -> K block 1
subtask1 instance2 -> K block 2
subtask1 instance3 -> K block 3
```

These are three different dimensions. They must not be collapsed into one
`wave_id` integer.

## Implementation Plan

### Phase 1: Add `ProcessorTaskPlan` Metadata

No behavior change.

1. Add `ProcessorTaskPlan`, `GemmTaskPlanningPolicy`, `TileTaskAssignment`, and
   `TileSubtaskPlan` dataclasses.
2. Populate `ProcessorTaskPlan` during logical-to-tile lowering, before tile
   actions are expanded.
3. Attach assignment metadata to:
   - `TilePhase.payload`
   - `TileLoopRegion.attrs`
   - tile compute/store/route action attrs
   - `TileMicroBlock.attrs`
4. Add dump output:

```text
task planning:
  policy = dfu3500_legacy_gemm_output_wave_tasks
  wave0 -> launch_group0/task0 C(m0,n0)
  wave1 -> launch_group0/task1 C(m0,n1)
  wave2 -> launch_group0/task2 C(m1,n0)
  wave3 -> launch_group0/task3 C(m1,n1)
```

Expected result:

```text
current tests and binary output unchanged
```

### Phase 2: Make Tile Lowering Consume `ProcessorTaskPlan`

Modify GEMM tile lowering so it does not compute task assignment inline from
scratch. It should ask the task plan:

```text
task_assignment = task_plan.assignment_for_wave(wave_id)
```

Then tile lowering uses that assignment to generate:

```text
TileLoopRegion
TileMicroBlock
TileRouteAction
TileComputeAction
TileStoreAction
```

Expected result:

```text
current GEMM unchanged
task assignment has one source of truth
```

### Phase 3: Stop Reconstructing Task IDs Downstream

Modify `program_packing.py`:

```text
before:
  task_id = f"task{assignment.wave_id}"

after:
  task_id = assignment.task_id / task_name from tile task assignment
```

If task assignment metadata is missing:

```text
raise explicit lowering error
```

Do not silently fall back to `wave_id`.

Expected result:

```text
current GEMM unchanged
future wave_id >= 4 no longer creates invalid task4/task5 rows
```

### Phase 4: Add Verifiers

Add verifier checks:

```text
1. every GEMM tile loop has task assignment metadata
2. every ProgramNode derived from a tile loop carries the same assignment
3. no vendor task index >= max_vendor_tasks
4. all k_stream instances in a TileLoopRegion share the same task/subtask
5. subtask roles match policy:
   prepare -> subtask0
   k_stream -> subtask1
   finalize_store -> subtask2
```

Add a regression test that current `gemm_template_fusion` emits:

```text
task0/task1/task2/task3
each task has subtask0/subtask1/subtask2
subtask1 instances_amount = 4
```

Add a synthetic stress test with more than four output tile waves:

```text
wave0..wave3 -> launch_group0/task0..task3
wave4..wave7 -> launch_group1/task0..task3
```

This test does not need to produce a runnable vendor binary yet. It only needs
to prove that `task_id` never becomes `task4`.

### Phase 5: Decide Multi-Launch Semantics

The current profile only validates one launch group:

```text
launch_group0 with task0..task3
```

If future GEMMs have more than four output waves, we must decide how to execute
multiple launch groups:

```text
Option A:
  emit multiple apps / launches

Option B:
  serialize launch groups through runtime/RISC-V controller

Option C:
  require one GEMM call to fit <= 4 output waves for legacy profile

Option D:
  introduce a higher-level tiling loop outside the vendor task table
```

Until this is decided, the compiler should reject unsupported multi-launch
profiles before binary emission:

```text
if launch_group_count > 1 and profile does not support multi-launch:
    raise UnsupportedTaskPlanningError
```

This guard should land with the metadata/packing cleanup, not as a distant
future binary feature. Otherwise `wave4 -> launch_group1/task0` becomes
well-formed metadata but still not a runnable legacy binary.

## Alternatives Considered

### Alternative A: Keep Current `wave_id -> task_id` Reconstruction

Rejected.

It works only for the current GEMM because there are exactly four output waves.
It hides a real ABI limit and allows invalid task ids for larger cases.

### Alternative B: Expose `task_count=4` as User-Facing GEMM Parameter

Rejected for the frontend.

The user-level GEMM should not be forced to speak vendor task ABI. The task
planner may accept a backend hint:

```python
gemm(..., dfu_task_policy="legacy_output_wave_tasks")
```

but this must remain a backend/placement hint, not mathematical GEMM semantics.

### Alternative C: Always Hard-Code Four Tasks in `program_bin.py`

Rejected as source of truth.

`program_bin.py` must serialize already-decided vendor rows. It may enforce
fixed physical table capacity:

```text
4 task rows
8 subtask slots per task
2048 instance rows per subtask
```

but it must not decide which GEMM wave maps to which task.

## Recommended Policy for Current Work

For DFU3500 legacy GEMM compatibility:

```text
Use output-tile wave task planning.

wave_id = row-major index over local C output tiles
task_id = wave_id % 4
launch_group_id = wave_id // 4
subtask0 = accumulator_prepare
subtask1 = repeated K-stream body
subtask2 = finalize/store
```

For now, require:

```text
launch_group_count == 1
```

when emitting runnable legacy-compatible vendor binaries.

This keeps the current successful `gemm_template_fusion` profile stable while
preventing accidental invalid binaries for larger output tilings.

## Expected Benefits

1. The current implicit behavior becomes reviewable and testable.
2. Future agents will not confuse `wave_id` with vendor `task_id`.
3. The packing layer will stop rediscovering task assignment.
4. Multi-output-wave GEMMs will fail loudly instead of silently generating
   `task4` or invalid MICC rows.
5. The task planning boundary will match the compiler layering principle:

```text
logical-to-task planning chooses semantic/vendor task placement
tile lowering consumes placement while creating actions
packing consumes task-aware tile actions
vendor ABI projects rows
binary serializes rows
```

## Open Questions for Review

1. Is `output_tile_wave -> task` the true vendor intent, or merely a convenient
   reconstruction for `gemm_template_fusion`?
2. If local output has more than four tile waves, should the compiler:
   - emit multiple launches,
   - retile to fit four waves,
   - or reject the profile?
3. Do `app0.conf..app3.conf` represent duplicated application tasks, four
   parallel task slots within one app, or both depending on runtime entrypoint?
4. Should task planning remain an internal sub-pass of `program_tile.py`, or
   become a separate `program_task.py` pass between processor logical and tile
   lowering?
5. Should GEMM expose a backend-only hint such as:

```python
matmul(..., task_policy="dfu3500_legacy_output_wave_tasks")
```

or should the policy be selected entirely from chip/profile config?

## Proposed Next Patch After Review

Make no binary-format changes first.

Patch only the task planning metadata and packing consumption:

```text
1. add ProcessorTaskPlan / TileTaskAssignment metadata
2. make tile lowering consume ProcessorTaskPlan
3. attach assignment through tile -> node -> packing
4. replace packing's `task_id = f"task{wave_id}"`
5. add tests proving current GEMM output is unchanged
6. add guard against `task_id >= 4` and unsupported multi-launch
```

This is a cleanup and safety patch. It should not change current
`gemm_template_fusion` CBUF/MICC bytes.
