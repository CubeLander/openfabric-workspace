# RFC: App / Task / Fusion Region Semantics

Date: 2026-06-16
Status: Accepted for metadata + verifier implementation; runnable multi-app
binary support deferred
Scope: chip-level program partitioning, app boundaries, task planning,
tile fusion, DFU3500 / SimICT execution model

## Why This RFC Exists

OpenFabric has now made DFU3500 GEMM task planning explicit:

```text
ProcessorLogicalProgram
  -> ProcessorTaskPlan
  -> ProcessorTileProgram
```

This fixes the local issue where `wave_id` was being reinterpreted as a vendor
`task_id`. But it raises a larger semantic question:

```text
Where should app-level partitioning, task-level partitioning, and fusion live?
```

This matters for operators that are not single-stage GEMM. A typical example is
`log10max`-like computation:

```text
parallel local work
  -> reduce / max
  -> use reduced result in later parallel computation
```

DFU apps cannot generally assume PE-local state survives across independent app
executions. If a reduced value must become globally visible before later
parallel computation, that boundary should likely be represented as an app
boundary:

```text
app0:
  reduce / materialize result

app1:
  load materialized result / parallel compute
```

If we do not model this explicitly, the compiler will be tempted to misuse
vendor tasks as cross-stage semantic containers. That would blur two different
concepts:

```text
app:
  lifecycle / PE-state boundary

task:
  app-local parallel task slot
```

This RFC proposes a clean separation.

## DFU3500 / SimICT Execution Model Background

### App

An app is the coarse execution unit driven by the runtime/RISC-V control
workflow. In vendor cases, app-level configuration appears as:

```text
app0.conf
app1.conf
app2.conf
app3.conf
```

or as a generated combined runtime package. The exact packer path can vary by
case, but architecturally an app is the safest boundary for PE-local state
lifetime.

Important assumption for compiler design:

```text
PE-local operand/register/tensor_tmp state must not be assumed to survive
across app boundaries.
```

Any value needed by a later app must be materialized through an explicit storage
boundary:

```text
store to SRAM/SPM/result buffer
load from SRAM/SPM/result buffer
```

### Task

DFU3500 exposes up to four vendor task rows inside an app-level runtime
configuration:

```text
task0
task1
task2
task3
```

Tasks are app-local. They should be used to express app-internal parallelism or
divide-and-conquer waves, not cross-app semantic phases.

For GEMM, the current legacy-compatible interpretation is:

```text
task = one output-tile wave slot inside one app
```

### Subtask

Each task owns up to eight local subtask slots:

```text
global_subtask_row = task_id * 8 + local_subtask_id
```

For GEMM:

```text
subtask0 = accumulator_prepare
subtask1 = K-stream repeated body
subtask2 = finalize/store
subtask3..7 = inactive/filler
```

Subtasks are task-local phase containers.

### Instance

Instances are hardware loop iterations inside a subtask:

```text
subtask body template
  repeated N times
  each repeat selects a different instance base-address row
```

For GEMM:

```text
subtask1 instance0 -> K block 0
subtask1 instance1 -> K block 1
...
```

### Storage and State Boundary

The most important modeling rule:

```text
app boundaries break PE-local state.
task/subtask/instance boundaries may preserve state only where the hardware
and vendor ABI explicitly support it.
```

For example:

```text
K accumulator state within GEMM subtask repeat:
  explicit loop-carried state inside one task/subtask profile

reduce result used by a later independent parallel phase:
  should be materialized if it crosses app boundary
```

### State Taxonomy

The verifier should not reason about "PE-local state" as a vague phrase.
State crossing rules are defined by explicit state kinds:

```text
StateKind

PE_LOCAL_VOLATILE
  register / operand slot / tensor_tmp / accumulator
  cannot cross app boundary

APP_LOCAL_EXPLICIT
  subtask / instance-supported loop-carried state with vendor ABI proof
  may live only inside one app

MATERIALIZED_STORAGE
  SRAM / SPM / result buffer / scalar tensor region
  may cross app boundary through explicit store/load edge

RUNTIME_CONFIG_STATE
  app config / task table / address rows
  not a data dependency unless explicitly modeled
```

The current GEMM K accumulator is `APP_LOCAL_EXPLICIT`:

```text
same app
same task/subtask profile
vendor instance repeat carries accumulator semantics
```

A reduce result consumed by a later independent app is
`MATERIALIZED_STORAGE`, even if it is logically a scalar.

## Proposed Compiler Layers

Introduce app partitioning above task planning:

```text
ChipProgram
  -> FusionRegionPlan
  -> AppPlan
  -> ProcessorLogicalProgram
  -> ProcessorTaskPlan
  -> ProcessorTileProgram
  -> DFUPackingProgram
  -> ProgramVendorABI
  -> ProgramBinRows
```

This is the conceptual target. Implementation can be incremental.

### `FusionRegionPlan`

A fusion region groups operations around one primary schedule. A single
primary operator is the common case, but staged operators such as softmax may
later use a compound primary schedule.

```python
@dataclass(frozen=True)
class FusionRegion:
    region_id: str
    primary_schedule_kind: str
    primary_op_ids: tuple[str, ...]
    attached_pre_op_ids: tuple[str, ...]
    attached_post_op_ids: tuple[str, ...]
    app_boundary_policy: str
    task_partition_policy: TaskPartitionPolicy | None
```

The primary operator is the anchor that determines the main task partition
policy inside the app.

Examples:

```text
GEMM region:
  primary_op = matmul
  post_ops   = bias/relu/activation/store-compatible epilogue
  task policy = output-tile-wave tasks

Reduce region:
  primary_op = reduce_max
  post_ops   = local transform that can consume reduce result in same app only
  task policy = reduce-tree / reduction-wave tasks
```

The task policy should be a structured object, not a string hint:

```python
@dataclass(frozen=True)
class TaskPartitionPolicy:
    kind: Literal[
        "gemm_output_tile_wave",
        "elementwise_tile_wave",
        "reduce_tree",
        "softmax_stage",
        "custom_vendor",
    ]
    max_task_rows: int
    required_subtask_roles: tuple[str, ...]
    state_requirements: tuple[StateRequirement, ...]
```

This lets `AppPlan` check whether all regions inside an app share one legal
task partition policy.

### `AppPlan`

An app plan partitions fusion regions into app-level execution units:

```python
@dataclass(frozen=True)
class AppRegion:
    app_id: int
    region_ids: tuple[str, ...]
    input_storage_refs: tuple[str, ...]
    output_storage_refs: tuple[str, ...]
    state_boundary: str
```

Cross-app data movement is represented by explicit storage edges:

```python
@dataclass(frozen=True)
class AppStorageEdge:
    edge_id: str
    value_id: str
    producer_app_id: int
    consumer_app_ids: tuple[int, ...]
    storage_ref: str
    materialization_kind: Literal[
        "scalar",
        "tile",
        "tensor",
        "partial_reduce",
        "scratch",
    ]
    producer_op: Literal["store", "reduce_store", "dma_write"]
    consumer_op: Literal["load", "broadcast_load", "dma_read"]
```

The key decision is:

```text
Can region B consume region A output through valid app-local state?
```

If yes, they may stay in one app.

If no, insert:

```text
store A output
app boundary
load A output in next app
```

### App Boundary Decision Table

The verifier should eventually encode this table:

```text
Producer value kind   Consumer requirement      Same app?       Required edge
-------------------   --------------------      ---------       -------------
PE_LOCAL_VOLATILE     same task/subtask          yes if proven   none
PE_LOCAL_VOLATILE     next app                   no              materialize
APP_LOCAL_EXPLICIT    same app ABI loop          yes if proven   none
APP_LOCAL_EXPLICIT    next app                   no              materialize
MATERIALIZED_STORAGE  next app                   yes             storage edge
REDUCE_GLOBAL         later parallel compute     not by default  store/load or broadcast
TILE_LOCAL_OUTPUT     epilogue elementwise       yes             none
RUNTIME_CONFIG_STATE  data dependency            no              explicit model first
```

This table prevents vendor task rows from becoming pseudo app phases.

### `ProcessorTaskPlan`

Within each app, task planning maps app-local work to vendor task slots:

```text
app-local output waves
  -> task0..task3
  -> subtask roles
  -> instance loops
```

This is where GEMM's current output-wave task policy belongs.

## Core Design Principles

### 1. App is the PE-state lifecycle boundary

No compiler pass may assume PE-local state survives across app boundaries unless
a vendor/runtime mechanism explicitly proves it.

Values crossing app boundaries must be modeled as storage:

```text
SRAM/SPM/output buffer/scalar tensor region
```

### 2. Task is app-local divide-and-conquer

Tasks are not global operator phases. They are app-local task-table slots.

Use tasks for:

```text
output tile waves
parallel chunks
reduce-tree branches inside one app
pipeline phases whose state relation is hardware-supported inside one app
```

Do not use tasks for:

```text
semantic stages that require app restart
cross-app global synchronization
state that must be materialized before reuse
```

### 3. Primary operator owns task partition policy

Inside one app, a fusion region has a primary operator:

```text
matmul
reduce
softmax stage
conv lowered to GEMM
```

The primary operator chooses the app-local task partition strategy. Fusion ops
attach before or after this primary schedule if their data dependencies and
state lifetime allow it.

### 4. Fusion is append-only unless proven otherwise

Post-ops such as ReLU, bias add, or simple elementwise transforms may be fused
into primary operator epilogue if:

```text
they consume tile-local primary output
they do not require cross-PE global information
they do not require app boundary materialization
```

If a post-op needs a global reduced result or cross-app materialized value, it
should form a new fusion region/app.

### 5. Storage boundary must be explicit

If the compiler cuts an app boundary, it must generate explicit:

```text
store
load
```

It must not rely on hidden PE state, tensor_tmp state, operand slots, or
implicit runtime side effects.

## Example: GEMM + ReLU

Source intent:

```text
Y = relu(A @ B)
```

Fusion region:

```text
primary_op = GEMM
post_ops = [ReLU]
```

App plan:

```text
app0:
  GEMM + ReLU + store
```

Task plan inside app0:

```text
wave0 -> task0 -> C local tile (m0,n0)
wave1 -> task1 -> C local tile (m0,n1)
wave2 -> task2 -> C local tile (m1,n0)
wave3 -> task3 -> C local tile (m1,n1)
```

Subtask plan:

```text
subtask0 = accumulator_prepare
subtask1 = K-stream repeated body
subtask2 = relu/finalize/store
```

ReLU is allowed to append because it consumes tile-local GEMM output and does
not require new global state.

## Example: `log10max`-like Reduce Then Parallel Compute

Possible source intent:

```text
m = reduce_max(X)
Y = log10(X / m)
```

The critical question:

```text
Can `m` be held in PE-local/app-local state and consumed by the next parallel
phase without app boundary?
```

If no, the compiler should split:

```text
app0:
  reduce_max(X) -> scalar/tensor m
  store m to SRAM/SPM/result region

app1:
  load X
  load m
  compute log10(X / m) in parallel
  store Y
```

Task plan inside app0 may be reduce-tree shaped:

```text
task0..task3 = local reduce chunks / reduction branches
subtasks = local reduce / cross-task reduction materialization / store
```

Task plan inside app1 may be elementwise tile-wave shaped:

```text
task0..task3 = parallel output chunks
subtasks = load scalar m / compute / store
```

Important: `app1` should not pretend to reuse app0 PE-local register state.

## Example: Softmax

Softmax often has staged structure:

```text
max = reduce_max(X)
E = exp(X - max)
sum = reduce_sum(E)
Y = E / sum
```

Depending on hardware/runtime support, this may become:

```text
app0: reduce max
app1: exp/subtract + reduce sum
app2: normalize
```

or fewer apps if intermediate state can be safely retained within one app.

The compiler should represent this through app partitioning, not by forcing all
semantic stages into vendor task rows.

## App Boundary Decision Rules

Cut an app boundary when any condition holds:

```text
1. A value must be globally visible before the next stage.
2. A value is consumed by a different primary operator schedule and cannot be
   proven PE-local live.
3. Cross-PE reduction result must be re-broadcast or loaded by many PEs.
4. The next stage has a different task partition policy incompatible with the
   current app.
5. Runtime/vendor ABI does not support the needed cross-task state dependency.
6. Resource pressure requires materialization to free instruction/operand/tmp
   capacity.
```

Keep regions in one app only when all conditions hold:

```text
1. Producer and consumer share a compatible primary task schedule.
2. Intermediate value lifetime is within one app.
3. PE-local state use is explicitly supported by the tile/subtask/instance
   model.
4. Fusion does not require a global synchronization outside the app.
```

## Relationship To Current `ProcessorTaskPlan`

Current work has only implemented GEMM task planning:

```text
ProcessorLogicalProgram
  -> ProcessorTaskPlan
  -> ProcessorTileProgram
```

This RFC extends the conceptual model upward:

```text
ChipProgram
  -> FusionRegionPlan
  -> AppPlan
  -> ProcessorLogicalProgram
```

But implementation should remain incremental. The next safe steps are:

```text
1. Keep GEMM task planning stable.
2. Add app/fusion metadata to chip-level planning without changing binaries.
3. Add explicit app boundary verifier:
     no PE-local value crosses app boundary.
4. Model one non-GEMM staged case, e.g. log10max, as app0/app1.
```

## Proposed Implementation Plan

### Phase 1: Document and annotate current GEMM

No binary behavior change.

Add metadata:

```text
FusionRegion(primary_op=matmul, post_ops=[relu])
AppRegion(app0, regions=[gemm_relu])
ProcessorTaskPlan(policy=legacy_output_wave_tasks)
```

Expected result:

```text
current GEMM tests unchanged
current CBUF/MICC unchanged
```

### Phase 2: Introduce app boundary IR

Add a small app planning layer:

```python
@dataclass(frozen=True)
class AppPlan:
    apps: tuple[AppRegion, ...]
    storage_edges: tuple[AppStorageEdge, ...]
```

This layer should be dumpable, but it does not need to change binary emission
for GEMM.

### Phase 3: Add verifier

Verifier rules:

```text
1. Every FusionRegion belongs to exactly one AppRegion unless explicitly
   cloned/recomputed.

2. Every AppRegion has exactly one primary task partition policy unless a
   compatibility proof exists.

3. Every storage edge has:
     producer app < consumer app
     explicit storage_ref
     explicit shape/layout
     explicit materialization kind

4. Any value consumed by multiple apps must be materialized or recomputed
   explicitly.

5. Any post-op fused into a primary region must prove:
     tile-local dependency only
     no cross-PE synchronization
     no incompatible task policy
     no app-boundary materialization requirement

6. Any reduce result consumed by non-reduce parallel work must prove either:
     same-app rebroadcast support
     or explicit materialization plus reload

7. No `PE_LOCAL_VOLATILE` value crosses app boundary without an
   `AppStorageEdge`.
```

Negative tests to add:

```text
test_reject_pe_local_cross_app
test_reject_multi_policy_app_without_compatibility_proof
test_allow_gemm_relu_tile_local_epilogue
test_require_reduce_materialization_for_later_parallel_app
test_allow_reduce_materialization_storage_edge
test_reject_task_as_global_phase_without_app_boundary
```

### Phase 4: Model `log10max`

Implement a staged app plan for one reduce-then-parallel case:

```text
app0 reduce/max -> materialized scalar/tensor
app1 load reduced value -> parallel compute
```

This can start as IR/dump only before runnable binary support.

## Open Questions

1. What exact SimICT/runtime mechanism defines an app boundary in the final
   multi-app package?
2. Can some reductions stay within one app using task/subtask sequencing, or
   must all global reductions materialize across apps?
3. Does vendor RISC-V control support sequential app launches within one bundle
   with deterministic storage handoff?
4. Should `FusionRegionPlan` live before or after processor placement?
5. Should `primary_op` be explicit user/compiler metadata, or inferred from the
   fusion graph?
6. What is the smallest non-GEMM staged operator that can validate this model:
   `log10max`, softmax, layernorm, or reduce+elementwise?

## Recommended Near-Term Decision

Adopt this hierarchy:

```text
App:
  PE-state lifecycle and storage boundary

FusionRegion:
  group of ops around one primary schedule

Primary schedule:
  chooses app-local task partition strategy

Task:
  app-local divide-and-conquer slot

Subtask:
  task-local phase container

Instance:
  hardware loop iteration
```

Then keep GEMM as the first proven instance:

```text
one app
one primary GEMM region
four output-wave tasks
three subtasks per task
K loop as subtask instance repeat
ReLU as epilogue fusion
```

This gives the compiler room to express reduce-then-parallel operators without
abusing vendor task rows as global semantic phases.

Near-term implementation order:

```text
1. Add metadata-only `AppPlan` for current GEMM.
2. Dump one `FusionRegion` with primary schedule `gemm_output_tile_wave`.
3. Represent ReLU as tile-local attached post-op.
4. Add basic verifier plus PE-local cross-app negative test.
5. Keep binary output unchanged.
6. Later model `log10max` as IR-only app0/app1 before attempting runnable
   multi-app binary.
```
