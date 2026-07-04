# RFC: Log10Max Audio Preprocess Lowering From AppPlan To DFU Tile Pipeline

Date: 2026-06-16
Status: Accepted for Phase A0/A1 implementation; functional binary deferred
Scope: `log10max` / audio preprocessing fusion, staged app lowering,
generic elementwise tile ops, reduce/all-reduce collective, DFU3500 backend

## Summary

The current refactored core can now express the audio preprocessing fragment at
chip/app level:

```text
log_spec = log10(clamp(mel_spec, min=1e-10))
global_max = reduce_max(log_spec)
out = maximum(log_spec, global_max - 8.0)
out = (out + 4.0) / 4.0
```

The frontend and `AppPlan` already produce a legal staged semantic plan:

```text
app0:
  clamp_min -> log10 -> reduce_max
  materialize global_max scalar

app1:
  reload mel_spec
  load/broadcast global_max scalar
  recompute clamp_min -> log10 locally
  maximum -> add_scalar -> mul_scalar -> store
```

This is intentionally conservative.  It does **not** carry PE-local `log_spec`
tiles across app boundaries.  It stores only the reduced scalar/tensor summary
and recomputes local elementwise work in the next app.

This RFC describes how to lower that `AppPlan` through the compiler pipeline
without abusing vendor task rows as cross-app semantic stages.

## Accepted Reviewer Decisions

This RFC adopts these decisions as implementation constraints:

```text
1. `reduce_max` lowers through a dedicated `LogicalReduceEdge`.
   It must not be represented as `LogicalRouteEdge(route_kind=all_reduce_max)`.

2. The cross-app `global_max` workspace is compiler-created app storage.
   Frontend-declared workspace can be added later as an override.

3. app1 recomputation uses cloned logical ops with origin/recompute metadata.
   It must not be a soft metadata note that tile lowering reinterprets later.

4. Phase A uses a symbolic app-level reduce collective.
   It does not force `reduce_tree` into four vendor task rows yet.

5. The first simulator-valid reduce prototype should prefer:
     all local maxima -> PE00 aggregate -> materialize/broadcast
   Pairwise tree reduction is deferred until the semantic path is proven.
```

The goal is to prove that OpenFabric can describe staged non-GEMM operators
without asking DFU3500 task rows to cosplay as global app phases.

## Execution Model Background

### App

An app is a PE-state lifecycle boundary.  The compiler must assume:

```text
PE_LOCAL_VOLATILE state cannot cross app boundary:
  registers
  operand slots
  tensor_tmp
  accumulator fragments
  route-local visibility tokens
```

Values needed by a later app must become:

```text
MATERIALIZED_STORAGE:
  SRAM/SPM tensor region
  scalar workspace
  result buffer
```

### Task

A task is app-local:

```text
task0..task3 are vendor task slots inside one app.
```

Tasks are not global operator stages.  They can partition work inside one app
such as:

```text
GEMM output tile waves
elementwise tile chunks
reduce tree branches
```

But a task must not be used as:

```text
task0 = reduce app
task1 = unrelated post-reduce global app
```

unless a same-app state/collective proof exists.

### Subtask / Instance

Subtasks are task-local phase containers.  Instances are hardware-loop repeats
inside one subtask body:

```text
subtask body template
  repeated by instances_amount
  base address selected by instance_conf row
```

For GEMM, we already use:

```text
subtask0 = accumulator_prepare
subtask1 = K-stream repeated body
subtask2 = finalize/store
```

For `log10max`, a first runnable backend does **not** need to use instance
repeat aggressively.  It can first lower elementwise/reduce as ordinary
single-pass subtasks, then fold later if capacity requires.

## Current State

Implemented:

```text
ChipEnv ops:
  clamp_min
  log10
  reduce_max
  maximum
  add_scalar
  mul_scalar

AppPlan:
  recognizes log10max audio preprocess
  emits app0/app1
  emits compiler-created AppStorageRegion and AppStorageEdge for global_max

Tests:
  `tests/test_chip_program_frontend.py`
  validates app0/app1 and the storage edge.

Example:
  `compiler/examples/log10_maximum.py`
  writes chip_program.json and app_plan.json.
```

Not implemented:

```text
ProcessorLogicalProgram:
  reduce_max is still a generic compute op; no first-class all-reduce route.

ProcessorTaskPlan:
  only GEMM output-wave task policy is explicit.
  no elementwise or reduce-tree task policy is consumed by tile lowering.

ProcessorTileProgram:
  generic local elementwise/reduce phases exist as a sketch, but are not yet
  a complete authority for store, collective reduce, and app storage edges.

TileMicroOpProgram:
  one micro-op per micro-block only.
  no dedicated elementwise_chain / local_reduce / collective_reduce roles.

DFU3500 template binding:
  GEMM legacy template path is strong.
  generic elementwise/reduce templates need explicit symbolic templates.

Packing / ABI / Binary:
  packing currently understands GEMM task roles best.
  runnable log10max binary is out of scope until generic op templates and
  reduce collective semantics are proven.
```

## Desired Layering

```text
ChipProgram
  owns logical tensor expression and explicit SRAM/SPM load/store.

AppPlan
  owns app boundaries, storage edges, materialize-vs-recompute strategy.

ProcessorLogicalProgram
  owns per-processor logical local actions and logical collectives.

ProcessorTaskPlan
  owns app-local vendor task partition policy.

ProcessorTileProgram
  owns tile actions, tile values, tile dependencies, and tile collectives.

TileMicroOpProgram
  owns executable micro-op roles independent of DFU3500 CSV details.

Dfu3500TemplateBoundProgram
  owns DFU3500 symbolic template selection and stage attribution.

ProgramNodes / DFUPackingProgram / ProgramAsm / ProgramVendorABI
  project already-decided tile/micro-op semantics into vendor containers.

ProgramBinRows / Serializer
  serialize already-decided ABI rows only.
```

## Layer-By-Layer Work Plan

### 1. ChipProgram Layer

Already done for the first slice.

Keep:

```text
clamp_min
log10
reduce_max
maximum
add_scalar
mul_scalar
```

Required constraints:

```text
elementwise ops reject Partial placements unless a reduce is explicit.
reduce_max defaults to reducing all tensor axes.
reduce_max result placement is Replicate over the logical fabric.
```

Future extension:

```text
sub_scalar can either be added or represented as add_scalar(-x).
affine can stay decomposed as add_scalar + mul_scalar first.
```

### 2. AppPlan Layer

Already done for semantic MVP.

Current policy:

```text
app0:
  compute global_max
  materialize scalar

app1:
  reload input and scalar
  recompute local log tile
  post-process
```

Why this belongs here:

```text
materialize-vs-recompute is an app-boundary decision.
It depends on PE-state lifetime and storage semantics, not tile route details.
```

Verifier requirements:

```text
No PE_LOCAL_VOLATILE value crosses app boundary.
Every cross-app value has AppStorageRegion + AppStorageEdge.
AppStorageEdge has shape/layout/materialization kind.
Each app has one task partition policy unless compatibility is proven.
```

App storage should be explicit.  The current `global_max` scalar is not a
frontend user output; it is a compiler-created inter-app workspace:

```python
AppStorageRegion(
    storage_id="app_storage.global_max",
    value_id="global_max",
    dtype="fp32",
    shape=(),
    layout="scalar",
    materialization_kind="scalar",
    allocation_kind="compiler_created",
    lifetime="inter_app",
)

AppStorageEdge(
    edge_id="app_storage_edge.global_max",
    storage_id="app_storage.global_max",
    producer_app_id=0,
    consumer_app_ids=(1,),
    producer_value_id="app0.global_max",
    consumer_value_ids=("app1.global_max_loaded",),
    store_action_kind="scalar_materialize_store",
    load_action_kind="scalar_broadcast_load",
)
```

Frontend-declared workspace can later override allocation, but it should not be
required for backend-created temporaries.

### 3. ProcessorLogicalProgram Layer

Add first-class logical collective modeling for `reduce_max`.

Current generic compute lowering can create per-processor local actions, but
`reduce_max` needs two related logical concepts:

```text
local_reduce_max:
  each processor computes a scalar summary from its local tile.

logical_all_reduce_max:
  all local summaries participate in a mesh/global max collective.
  output is a replicated scalar visible to all processors in the same app.
```

Proposed records:

```python
LogicalReduceEdge(
    edge_id,
    source_chip_op_id,
    reduce_op="max",
    identity_value="-inf",
    input_logical_tensor_id,
    output_logical_tensor_id,
    participants=("processor_0_0", ..., "processor_3_3"),
    source_policy="all_processors_contribute",
    visibility_kind="replicated_scalar",
    dependency_policy="local_reduce_before_collective;collective_before_consumers",
)
```

This lives beside `LogicalRouteEdge`, not inside it.  Route is value movement;
reduce is many-to-one algebra plus visibility semantics.  A reduce edge carries
fields that would make route semantics muddy:

```text
reduce_op
identity_value
participants
source_policy
visibility_kind
determinism_policy
```

app1 recomputation should be explicit cloned logical work:

```python
LogicalOp(
    op_id="app1.recompute.clamp_min",
    kind="clamp_min",
    inputs=("mel_spec",),
    attrs={"min": 1e-10},
    origin_op_id="chip.clamp_min.0",
    recompute_of="chip.clamp_min.0",
)

LogicalOp(
    op_id="app1.recompute.log10",
    kind="log10",
    inputs=("app1.recompute.clamp_min.out",),
    origin_op_id="chip.log10.0",
    recompute_of="chip.log10.0",
)
```

The cloned ops make dependency graph semantics explicit while preserving debug
traceability back to the original chip-level expression.

Important invariant:

```text
all_reduce method is not semantics.
replicated scalar visibility is semantics.
```

The physical reduce tree / line fanout / runtime implementation is later.

### 4. ProcessorTaskPlan Layer

Add app-local policies:

```text
reduce_tree
elementwise_tile_wave
```

For first non-runnable IR:

```text
app0 reduce_tree:
  partition_mode = symbolic_collective
  binary_status = unencoded
  exact physical reduce tree is not chosen yet.

app1 elementwise_tile_wave:
  task0..task3 partition output tile chunks.
```

Do not let task planning decide app split.  It only consumes an app-local
region and assigns vendor task slots.

MVP task policy shape:

```python
TaskPartitionPolicy(
    kind="reduce_tree",
    partition_mode="symbolic_collective",
    max_vendor_tasks=None,
    binary_status="unencoded",
)

TaskPartitionPolicy(kind="elementwise_tile_wave", ...)
```

Do not bind Phase A reduce to four DFU3500 task rows.  That would prematurely
turn a logical collective into a vendor task-table policy.  A later runnable
prototype can choose a concrete shape such as:

```text
local maxima -> PE00 aggregate -> materialize / broadcast
```

Packing guard:

```text
If a region has task policy unsupported by current runnable binary profile,
emit IR/dump only or raise UnsupportedLoweringError before binary emission.
```

### 5. ProcessorTileProgram Layer

This is the main next implementation target.

Add first-class tile value kinds:

```python
class TileValueKind(Enum):
    PE_LOCAL_TILE = "pe_local_tile"
    PE_LOCAL_SCALAR = "pe_local_scalar"
    REPLICATED_APP_SCALAR = "replicated_app_scalar"
    MATERIALIZED_SCALAR = "materialized_scalar"
    MATERIALIZED_TILE = "materialized_tile"
    MATERIALIZED_TENSOR = "materialized_tensor"
```

Add explicit tile dependency edges:

```python
TileDependencyEdge(
    producer_action_id,
    consumer_action_id,
    value_id,
    dependency_kind,
    crosses_app_boundary,
)
```

Allowed `dependency_kind` values:

```text
tile_value
local_scalar
collective_result
materialized_storage
control_barrier
```

Hard rule:

```python
if edge.crosses_app_boundary:
    assert edge.dependency_kind == "materialized_storage"
```

Add first-class tile action families:

```text
TileComputeAction(compute_kind="elementwise_chain")
  attrs.ops = [
    clamp_min(min=1e-10),
    log10,
  ]

TileComputeAction(compute_kind="local_reduce_max")
  input_refs = [log_tile]
  output_refs = [local_max_scalar]

TileCollectiveAction / TileCollectiveBundle(kind="all_reduce_max")
  input_refs = [local_max_scalar per processor]
  output_refs = [global_max_replicated_scalar per processor]

TileComputeAction(compute_kind="post_reduce_elementwise_chain")
  attrs.ops = [
    clamp_min,
    log10,
    add_scalar(-8.0) on global max,
    maximum,
    add_scalar(4.0),
    mul_scalar(0.25),
  ]

TileStoreAction
  stores output tiles to declared SRAM/SPM output tensor.
```

Why this belongs here:

```text
TileProgram is the first layer where explicit parallelism, communication,
dependencies, and tile storage windows all appear together.
```

Required dependency shape:

```text
app0:
  a0 = local_elementwise_chain(
         ops=[clamp_min(1e-10), log10],
         input=mel_spec_tile
       )
       output=log_spec_tile : PE_LOCAL_TILE

  a1 = local_reduce_max(
         input=log_spec_tile
       )
       output=local_max : PE_LOCAL_SCALAR

  a2 = all_reduce_max_symbolic(
         inputs=local_max from participants
       )
       output=global_max_app : REPLICATED_APP_SCALAR

  a3 = scalar_materialize_store(
         input=global_max_app,
         storage=app_storage.global_max
       )
       output=global_max_storage : MATERIALIZED_SCALAR

app1:
  b0 = scalar_broadcast_load(
         storage=app_storage.global_max
       )
       output=global_max_loaded : REPLICATED_APP_SCALAR

  b1 = post_reduce_elementwise_chain(
         ops=[
           clamp_min(1e-10),
           log10,
           threshold = global_max_loaded + (-8.0),
           maximum(log_spec, threshold),
           add_scalar(4.0),
           mul_scalar(0.25),
         ],
         inputs=[mel_spec_tile, global_max_loaded]
       )
       output=out_tile : PE_LOCAL_TILE

  b2 = tile_store(
         input=out_tile,
         storage=out_tensor
       )
```

Important: app1 should not depend on app0 `log_tile`.

It should depend on:

```text
original input SRAM tile
materialized global_max scalar
```

This is the exact place to prevent PE-local state leakage.

The threshold expression must stay ordered:

```text
threshold = global_max + (-8.0)
clipped = maximum(log_spec, threshold)
shifted = clipped + 4.0
out = shifted * 0.25
```

It is not equivalent to `maximum(log_spec, global_max)` followed by
`add_scalar(-8.0)`.

### 6. TileMicroOpProgram Layer

Split generic tile actions into executable roles:

```text
elementwise_chain
local_reduce_max
collective_reduce_participate
scalar_materialize_store
scalar_broadcast_load
tile_store
```

MVP may keep one micro-op per tile action, but role names must be explicit so
DFU3500 template binding does not infer semantics from strings like
`local_elementwise_reduce`.

Suggested roles:

```text
elementwise_clamp_log
local_reduce_max
all_reduce_max_symbolic
load_materialized_scalar
elementwise_threshold_max_affine
store_tile
```

### 7. Dfu3500TemplateBoundProgram Layer

Add symbolic DFU3500 templates for generic ops:

```text
clamp_min:
  FMAX with scalar epsilon

log10:
  FLOG2
  FMUL by log10(2)

local_reduce_max:
  symbolic FMAX reduction across tile lanes

maximum:
  FMAX

add_scalar:
  FADD scalar

mul_scalar:
  FMUL scalar
```

For the first slice:

```text
template_profile = dfu3500_symbolic_generic
binary_status = unencoded
```

This keeps the template boundary honest:

```text
ProgramBinRows must not invent FLOG2/FMAX/FADD/FMUL sequences.
```

### 8. ProgramNodes / DFUPackingProgram Layer

Add generic node roles:

```text
local_elementwise
local_reduce
collective_reduce
scalar_materialize
scalar_load
tile_store
```

Do not pack `collective_reduce` as if it were GEMM route forwarding.

Packing needs two modes:

```text
analysis/debug mode:
  emit nodes and dependencies, no runnable binary claim.

runnable mode:
  require DFU3500 implementation for reduce collective and scalar storage.
```

### 9. ProgramAsm / VendorABI / BinRows

Until DFU3500 reduce collective and scalar workspace are proven:

```text
ProgramAsm may carry symbolic records.
ProgramVendorABI may mark rows as unsupported_for_binary.
ProgramBinRows must refuse full package emission for log10max.
```

Required gate:

```text
if program contains compute_kind in {
  local_reduce_max,
  all_reduce_max,
  scalar_materialize_store,
  scalar_broadcast_load,
  elementwise_log10,
}
and vendor profile lacks concrete support:
  raise UnsupportedFunctionalBinaryError
```

This avoids producing a pretty but false binary bundle.

Distinguish two failure classes:

```text
UnsupportedLoweringError:
  the IR layer cannot express the operation yet.

UnsupportedFunctionalBinaryError:
  the IR can express it, but the active vendor profile cannot emit a proven
  runnable binary for it.
```

Phase A/B should aim for the second class: the compiler understands the
program, but refuses to lie about DFU3500 binary support.

## Proposed Implementation Phases

### Phase A0: Schema And Verifier Guardrails

Goal:

```text
Define the semantic rails before lowering log10max through them.
```

Add:

```text
LogicalReduceEdge
AppStorageRegion
AppStorageEdge(storage_id-based)
TileValueKind
TileDependencyEdge
UnsupportedLoweringError
UnsupportedFunctionalBinaryError
```

Verifier rules:

```text
1. Every cross-app TileDependencyEdge uses dependency_kind=materialized_storage.
2. No PE_LOCAL_TILE / PE_LOCAL_SCALAR value has a consumer in another app.
3. REPLICATED_APP_SCALAR is app-local unless materialized.
4. scalar_broadcast_load references AppStorageRegion, not producer tile action.
5. all_reduce_max_symbolic declares reduce_op, participants, identity, visibility.
6. app1 recompute chain reads original input storage, not app0 log_spec tile.
7. ProgramBinRows rejects unencoded symbolic collective / scalar workspace roles.
8. Existing GEMM binary path remains byte-stable.
```

### Phase A1: IR-Only Generic Tile Program

Goal:

```text
ChipProgram -> AppPlan -> ProcessorLogicalProgram -> ProcessorTileProgram
```

Expected dumps:

```text
app0:
  local_elementwise_chain
  local_reduce_max
  all_reduce_max_symbolic
  scalar_materialize_store

app1:
  scalar_broadcast_load
  post_reduce_elementwise_chain
  tile_store
```

Tests:

```text
test_log10max_app_plan_two_apps
test_log10max_tile_program_has_no_cross_app_pe_local_dependency
test_log10max_tile_program_has_app_storage_edge_dependency
test_log10max_reduce_edge_has_participants_identity_visibility
test_log10max_app1_does_not_consume_app0_log_tile
```

No binary output.

### Phase B: MicroOp + Symbolic Template Binding

Goal:

```text
ProcessorTileProgram -> TileMicroOpProgram -> Dfu3500TemplateBoundProgram
```

Expected:

```text
FLOG2/FMUL symbolic log10 template present
FMAX symbolic reduce/max templates present
all unsupported rows explicitly marked binary_status=unencoded
```

Tests:

```text
template roles exist
ProgramBinRows refuses full package
GEMM binary path unchanged
log10 lowers to FLOG2 + FMUL(log10(2)) symbolic template
maximum/clamp_min lower to FMAX symbolic template
```

### Phase C: Reduce Collective Prototype

Goal:

```text
logical_all_reduce_max -> tile collective actions -> graph nodes
```

Still may be non-runnable.

Open design choices:

```text
tree reduce vs line reduce
single scalar storage location vs replicated scalar storage
whether scalar broadcast uses COPY/COPYT, SRAM reload, or runtime config
```

### Phase D: Functional DFU3500 Binary

Only after Phase C proves:

```text
concrete scalar base address layout
concrete reduce collective implementation
instruction templates for FLOG2/FMAX/FADD/FMUL
task/subtask resource capacity
```

Then `ProgramBinRows` can emit runnable binary.

## Non-Goals

This RFC does not:

```text
1. Change current GEMM binary behavior.
2. Claim log10max can produce runnable DFU3500 binary now.
3. Use vendor task rows as cross-app semantic phases.
4. Reuse app0 PE-local log tile in app1.
5. Design optimized materialize-vs-recompute cost model.
6. Bind reduce_tree to four DFU3500 task rows during Phase A.
7. Claim scalar workspace physical allocation is final.
```

## Negative Tests

```text
test_reject_app1_consumes_app0_pe_local_tile:
  force app1 input to app0.log_spec_tile
  expect verifier failure

test_reject_reduce_without_participants:
  all_reduce_max_symbolic missing participant set
  expect verifier failure

test_reject_reduce_without_visibility:
  reduce result has no replicated/single-owner visibility
  expect verifier failure

test_reject_binary_for_symbolic_collective:
  try full binary emission for log10max
  expect UnsupportedFunctionalBinaryError

test_reject_task_phase_abuse:
  encode reduce as task0 and unrelated post-process as task1 in same app
  without collective/state proof
  expect verifier failure
```

## Resolved Review Questions

```text
1. Dedicated LogicalReduceEdge.
2. Compiler-created AppStorageRegion by default.
3. Cloned app1 logical ops with origin_op_id / recompute_of.
4. Symbolic app-level reduce collective first.
5. First runnable prototype should prefer all-PE -> PE00 -> materialize/broadcast.
```

## Recommended Decision

Accept the staged plan:

```text
1. Keep current AppPlan split.
2. Next implement Phase A0/A1 only:
   semantic guardrails + generic tile actions + symbolic all_reduce_max.
3. Add gates so log10max cannot accidentally enter functional binary emission.
4. Preserve GEMM path and binary byte stability.
```

This lets OpenFabric prove the architecture serves a non-GEMM staged fusion
operator while keeping DFU3500 binary generation honest.
