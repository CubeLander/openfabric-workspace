# RFC: B-line log10max Task-local Ring Execution Model

## Status

Accepted direction with progress-gated amendments.

Implementation scope: ring-first delivery path for log10max V1, not a generic
collective framework.

Date: 2026-06-23

Supersedes the broader delivery framing in
`docs/compiler/design/bline-log10max-ring-spmd-collective-rfc.md` for the
first log10max implementation.

## Summary

Use a progress-first, task-local ring strategy for log10max V1.

The first deliverable should not implement a generic allreduce framework and
should not use `direct_route_reduce_broadcast`. It should lower log10max global
max movement into the existing app/task/subtask/exeBlock model:

```text
within one task:
  local reduce on each PE
  representative row reduce to column 0
  representative column reduce to PE(0,0)
  column broadcast from PE(0,0)
  row broadcast to every consumer PE
  postprocess consumes concrete global_max_ready[pe]

across tasks:
  no internal cooperation inside one app
  split with app wait/start boundaries
```

The key rule is:

```text
PEs inside one task may cooperate through route/exeBlock dependencies.
PEs across different tasks must not cooperate inside one app.
Cross-task reduce/distribute requires an app boundary as the barrier.
```

The ring plan is therefore a task-local execution topology, not a new collective
subsystem.

Progress clamp:

```text
Use:
  ring_spmd_row_then_col as first log10max delivery strategy

Require:
  representative row/column reduce+broadcast first
  task_axis=1 profile decision explicit
  no new communication IR
  no full-ring generalization before first package
  fail closed on symbolic route/update/global-max binding

Keep:
  PE00 materialized scalar as debug/delivery escape hatch
  redundant SPMD internal-only unless customer waiver exists
  direct_route_reduce_broadcast deferred
```

## Current State

### Partner Runtime Model

The partner control hierarchy is:

```text
app launch
  -> task_conf_info_t
  -> sub_task_conf_info_t
  -> exeBlock_conf_info_t
  -> instance_conf_info_t
  -> inst_t rows
```

The runtime-control path is:

```text
DPU_CbufTransfer
DPU_MiccTransfer
DPU_Kernel_Start(inst_reload, task_num, instance_base, ..., buf_num, ...)
DPU_Kernel_Wait_Finish(buf_num)
DPU_App_Finish
```

`DPU_Kernel_Start()` writes a task mask:

```text
task_num = 1 -> task_enable = 1
task_num = 2 -> task_enable = 3
task_num = 3 -> task_enable = 7
task_num = 4 -> task_enable = 15
```

This launches selected tasks in one app buffer. It does not create a safe
cross-task collaboration domain.

### Task/Subtask/ExeBlock Semantics

The generation chain shows:

```text
app*.conf
  -> task/subtask declarations
  -> generateGraph()
  -> GRAPH_NODE parent/child relationships
  -> INST_BLK_MAP::map_subtask
  -> exe_block_gen
  -> task_print
  -> CBUF/MICC binary tables
```

Task and subtask tables encode sequencing:

```text
task_conf_info_t.suc_tasks[]
sub_task_conf_info_t.suc_subtasks[]
```

Inside a subtask, `exeBlock_conf_info_t` carries graph execution information:

```text
predecessors[]
successors[]
req_activations
root_block_amount
stage_start_pc
PE destination
```

This is the right place to express PE-local graph dependencies for a task-local
ring.

### Route/COPY Evidence

The vendor route model already supports cross-PE movement inside the graph:

```text
Graph_Extend::set_relationship_node(parent, child, type)
  -> records parent/child relationship
  -> attaches COPY/COPYT instructions for that edge

INST_BLK_MAP route repair
  -> patches COPY destination block from the child node
  -> patches COPY destination PE from the child node
  -> patches destination operand from the receiver's resource plan
```

Compiler implication:

```text
Route destination ownership belongs to the receiver endpoint.
The sender must not invent the receiver operand or block binding.
```

The B-line equivalent already exists conceptually:

```text
StreamAction(route_push_*)
StreamAction(route_recv_*)
StreamAction.depends_on
FiberOp(fragment_route_push)
FiberOp(fragment_route_recv)
FiberDependency(expected_satisfaction="route_or_local_materialization")
DependencyProof(proven_by=("route_path",))
```

### B-line Status

B-line can describe log10max as flat tile/fiber actions:

```text
clamp_min_tile
log10_tile
local_reduce_max_tile
global_max_tile
max_with_floor_tile
affine_scale_tile
store_tile
```

The unresolved part is turning `global_max_tile` into concrete communication and
consumer visibility without relying on PE00 scalar materialization or direct
physical allreduce.

## Problem

log10max needs:

```text
global_max = reduce_max(log10(clamp(input, 1e-10)))
out = (maximum(log_spec, global_max - 8.0) + 4.0) / 4.0
```

The hard part is not local math. The hard part is making one `global_max`
available to every postprocess consumer.

Previous PE00 materialized-scalar planning is blocked by:

```text
PE00 combine/store row bytes
consumer physical readback row bytes
runtime subtask ordering proof
receiver global scalar binding proof
```

The direct route collective path is deferred because route/reduce/broadcast
synchronization is not fully proven.

A representative row/column ring is promising, but only if it is interpreted
correctly:

```text
Allowed:
  representative graph nodes inside one task-local PE graph

Forbidden:
  one row or one column secretly coordinating across independent tasks
```

If tasks are independent work shards, a one-app cross-task ring would be
structurally unsafe even if the package contains route-looking rows.

## Goals / Non-goals

### Goals

1. Produce a first concrete log10max global-max movement plan.
2. Use only existing B-line communication and scheduling primitives.
3. Align the plan with the partner app/task/subtask/exeBlock execution model.
4. Make task-local cooperation and cross-task barriers explicit.
5. Prefer a narrow representative row/column reduce+broadcast plan.
6. Fail closed if route, update, phase order, or consumer binding is symbolic.

### Non-goals

1. Do not implement generic allreduce.
2. Do not use `direct_route_reduce_broadcast` for first delivery.
3. Do not introduce a new communication IR.
4. Do not let a derived ring graph become scheduling authority.
5. Do not allow one-app cross-task cooperation.
6. Do not optimize into full row/column ring before first package.
7. Do not claim numerical correctness from `runtime_ready`.

## Proposed Design

### Execution Model

The first delivery uses two modes.

#### Mode A: Single-task Ring

Use this when log10max can be compiled with:

```text
task_axis = 1
runtime_ordering_domain = single_task_graph
```

All participating PEs are inside one task-local 4x4 graph. First delivery always
uses the representative row/column reduce+broadcast plan with column 0 as the
row representative:

```text
for each PE(x, y):
  local_max[x, y] = reduce_max(local log_spec shard)

row reduce:
  PE(x, 3) -> PE(x, 2) -> PE(x, 1) -> PE(x, 0)
  PE(x, 0) owns row_max[x]

column reduce:
  PE(3, 0) -> PE(2, 0) -> PE(1, 0) -> PE(0, 0)
  PE(0, 0) owns global_max

column broadcast:
  PE(0, 0) -> PE(1, 0) -> PE(2, 0) -> PE(3, 0)

row broadcast:
  PE(x, 0) -> PE(x, 1) -> PE(x, 2) -> PE(x, 3)

for each PE(x, y):
  postprocess depends on global_max_ready[x, y]
```

For a 4x4 mesh, the route-edge count is:

```text
row reduce:       4 * 3 = 12
column reduce:    3
column broadcast: 3
row broadcast:    4 * 3 = 12
total:            30 route edges
```

This shape fits the vendor ABI better than a full ring because
`MAX_PREDECESSOR_AMOUNT = 4` and `MAX_SUCCESSOR_AMOUNT = 4`; a representative
chain keeps fan-in/fan-out small.

Decision:

```text
First package uses representative row/column reduce+broadcast.
Full row/column ring is deferred until after first package unless existing
template evidence proves it is cheaper and no wider than the representative
path.
```

#### Mode B: Cross-task Multi-app Phases

Use this when the customer shape requires multiple independent tasks.

Cross-task cooperation must be split by app boundaries:

```text
App 0:
  each task performs local elementwise and task-local reduce
  each task materializes one task_max to a declared scratch/output region
  wait finish

App 1:
  task_axis = 1 or scalar-only profile
  reduce task_max values into global_max
  materialize global_max to scratch
  wait finish

App 2:
  tasks read materialized global_max
  postprocess and store outputs
  wait finish
```

The app boundary is the barrier:

```text
DPU_Kernel_Start(App N)
DPU_Kernel_Wait_Finish(App N)
DPU_Kernel_Start(App N + 1)
```

This is heavier than Mode A but matches the runtime model. It does not assume
internal cross-task synchronization.

Mode B is not this week's default path. It is enabled only if the existing
package/runtime path can support phased apps cleanly. The implementation must
not grow a new app orchestration framework just to make this fallback work.

### Semantic Authority

The authority chain remains:

```text
StreamAction.depends_on
  -> FiberOp projection
  -> dependency proof
  -> template binding
  -> vendor/component rows
```

A `RingCollectivePlan` may exist only as derived validation metadata:

```text
StreamAction / FiberOp is authority.
RingCollectivePlan is report-only.
```

Template lowering must not consume `RingCollectivePlan` as a new source of
truth.

### Existing Route Primitive Reuse

Each route edge is encoded as existing route visibility:

```text
sender:
  StreamAction(route_push_global_max)

receiver:
  StreamAction(route_recv_global_max)
  StreamAction(max_update_global_max)
```

Projection:

```text
route_push_global_max
  -> FiberOp(fragment_route_push, operand="GlobalMax")
  -> operand_route_push:GlobalMax

route_recv_global_max
  -> FiberOp(fragment_route_recv, operand="GlobalMax")
  -> operand_route_recv:GlobalMax
  -> DependencyProof(proven_by=("route_path",))
```

`GlobalMax` is a route role generalization of existing A/B operand route
movement. It is not a new communication path.

### Route Role Binding

The compiler should emit a small binding record:

```python
@dataclass(frozen=True)
class RouteRoleBinding:
    role: Literal["A", "B", "GlobalMax"]
    route_template_family: str
    source_value_kind: Literal["tile_fragment", "scalar", "scratch_scalar"]
    destination_value_kind: Literal["tile_fragment", "scalar", "scratch_scalar"]
    template_evidence_id: str
    proof_status: Literal["proven", "assumed", "unresolved"]
```

`runtime_ready` requires:

```text
role = GlobalMax
proof_status = proven
template_evidence_id present
source/destination value kinds concrete
receiver-owned destination operand binding concrete
```

### Ring Edge Metadata

For validation and debugging, emit derived records:

```python
@dataclass(frozen=True)
class RingEdgeRecord:
    edge_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    task_id: str
    src_pe: str
    dst_pe: str
    source_stream_action_id: str
    recv_stream_action_id: str
    source_fiber_op_id: str
    recv_fiber_op_id: str
    update_action_id: str | None
    dtype: str
    update_op: Literal["FMAX", "HMAX"]
    route_role: Literal["GlobalMax"]
    ordering_group: str
    proof_status: Literal["proven", "assumed", "unresolved"]
```

The record must include `task_id`. A single-app edge whose source and
destination task ids differ is invalid.

### Consumer Readiness Token

Each consumer PE must receive a concrete readiness token:

```text
global_max_ready[task, pe_x, pe_y]
```

The final postprocess op must depend on it:

```text
max_with_global_floor_tile[task, pe].depends_on += global_max_ready[task, pe]
```

This avoids repeating the PE00 scalar bug in a new shape: it is not enough that
global max was broadcast somewhere; every consumer must depend on its concrete
visibility.

### Package Metadata

The log10max payload metadata should say:

```json
{
  "operator": "log10max",
  "collective_strategy": "ring_spmd_row_then_col",
  "customer_collective_label": "spmd_ring_materialized_reduce",
  "task_axis": 1,
  "runtime_ordering_domain": "single_task_graph",
  "cross_task_internal_cooperation": false,
  "direct_route_reduce_broadcast": "deferred",
  "physical_allreduce_claim": false,
  "runtime_ready": "structural_package_readiness_only",
  "simict_status": "not_run",
  "numerical_status": "not_checked"
}
```

For multi-app mode:

```json
{
  "operator": "log10max",
  "collective_strategy": "multi_app_task_local_ring",
  "cross_task_barrier": "app_wait_start",
  "app_phases": ["local_task_reduce", "global_scalar_reduce", "postprocess_store"],
  "cross_task_internal_cooperation": false
}
```

## Invariants

1. A one-app route edge must not cross task ids.
2. Inside one task, ring edges are ordinary graph/exeBlock route dependencies.
3. Across tasks, app wait/start is the only accepted first-delivery barrier.
4. `StreamAction.depends_on` is the scheduling authority.
5. Ring metadata is derived report data only.
6. `GlobalMax` route is a role generalization of existing route primitives.
7. Destination operand/block binding is receiver-owned.
8. Every postprocess consumer depends on `global_max_ready`.
9. Full-ring generalization is deferred.
10. `direct_route_reduce_broadcast` is deferred.
11. `runtime_ready` does not imply SimICT execution or numerical correctness.
12. Redundant SPMD full-domain scan is not customer-facing unless a customer
    waiver is attached.

## Alternatives Considered

### PE00 Materialized Scalar

Keep as debug or delivery escape hatch only.

It may become useful if PE00 combine/store/readback proofs close faster than
route binding. But it remains risky because producer-before-consumer ordering
and scalar readback are currently hard blockers.

### Full Ring

Defer.

A full row/column ring lets every PE learn intermediate maxima earlier, but it
emits more route rows and does not help first delivery. The representative plan
has fewer edges and lower ABI pressure.

### Redundant SPMD Recompute

Internal-only unless customer explicitly accepts it.

This requires every PE to read the full reduce domain and may be too slow or
shape-constrained.

### Direct Route Reduce Broadcast

Defer.

This is the long-term clean target, but first delivery should not depend on a
generic physical allreduce proof.

## Migration / Implementation Plan

### A. Strategy And Profile Declaration

```text
[ ] add collective_strategy = ring_spmd_row_then_col
[ ] add customer_collective_label = spmd_ring_materialized_reduce
[ ] emit task_axis and runtime_ordering_domain in reports
[ ] manifest prints task_axis and ordering domain
[ ] fail if one-app route edge crosses task ids
[ ] mark direct_route_reduce_broadcast as deferred
```

### B. Representative Ring Action Emission

```text
[ ] emit local_reduce_max per participating PE
[ ] emit row_reduce edges to column 0
[ ] emit col_reduce edges to PE(0,0)
[ ] emit col_broadcast edges down column 0
[ ] emit row_broadcast edges to every consumer PE
[ ] every edge is route_push / route_recv / max_update
[ ] emit global_max_ready[task, pe] tokens
[ ] make postprocess depend on global_max_ready
[ ] no hidden communication bundle
```

### C. Template Binding

```text
[ ] bind GlobalMax route_push/route_recv through existing route family
[ ] bind FMAX/HMAX update rows
[ ] scratch/register binding concrete
[ ] bind receiver-owned destination operand/block
[ ] prove route_path dependencies
[ ] no symbolic global max reaches postprocess
[ ] fail closed on assumed/unresolved GlobalMax route binding
```

### D. Gate And Fallback

Only after A-C are understood:

```text
[ ] ring graph validation passes
[ ] phase ordering validation passes
[ ] consumer binding validation passes
[ ] if task_axis=1 invalid, switch to multi-app or explicit fallback
[ ] if GlobalMax route binding is unproven, stop ring work and evaluate PE00 or multi-app fallback
[ ] App 0 local/task reduce materialization
[ ] App 1 scalar global reduce
[ ] App 2 postprocess/store
[ ] generated RISC-V control supports multiple launches or explicit package mode
[ ] metadata marks app_wait_start as cross-task barrier
```

Do not start Phase 4 by creating a new app orchestration framework. Use it only
if the existing runtime package path can support phased apps cleanly.

## Validation Plan

### Structural Gate

```text
strategy is ring_spmd_row_then_col or multi_app_task_local_ring
direct_route_reduce_broadcast is not selected
no one-app edge crosses task ids
task_axis/runtime_ordering_domain is explicit
```

### Ring Graph Gate

```text
edge count matches representative plan
each edge has source/destination PE and task id
row_reduce reaches column 0 per row
col_reduce reaches PE(0,0)
col_broadcast reaches every row representative
row_broadcast reaches every consumer
```

### Dependency Gate

```text
route_recv dependencies proven by route_path
postprocess depends on global_max_ready
no symbolic global max reaches max_with_floor_tile
phase order is explicit
```

### Template Gate

```text
GlobalMax route role proof_status = proven
receiver-owned destination operand concrete
FMAX/HMAX dtype matches log10max dtype
no unresolved route/update rows are emitted
```

### Package Gate

```text
metadata declares strategy, task_axis, ordering domain
runtime_ready remains structural/package readiness only
numerical_status remains separate
known limitation says this is not direct physical allreduce
```

### Runtime-ready Blockers

`runtime_ready` must fail closed on:

```text
task_axis_scope_unproven
cross_task_one_app_ring_forbidden
representative_selection_missing
ring_edge_template_missing
route_role_globalmax_unproven
route_path_proof_missing
ring_phase_order_missing
global_max_distribution_missing
consumer_global_max_binding_missing
consumer_depends_on_global_ready_missing
ring_capacity_overflow
dtype_update_op_mismatch
symbolic_global_max_reaches_postprocess
```

## Risks And Mitigations

### Risk: Representative Plan Does Not Match Customer Parallel Shape

Mitigation: only use representative plan inside one task. If customer shape
requires multiple tasks, use multi-app phases.

### Risk: GlobalMax Route Binding Is Not Actually Equivalent To A/B Movement

Mitigation: require `RouteRoleBinding` with concrete source/destination kind,
receiver endpoint binding, and evidence id. Do not pass `runtime_ready` on
assumption.

### Risk: Consumer Reads Before Global Max Arrives

Mitigation: require `global_max_ready[pe]` token and explicit postprocess
dependency.

### Risk: Multi-app Fallback Becomes A New Framework

Mitigation: keep it as a fallback using existing RISC-V launch/wait semantics.
Do not build a generic app scheduler during first delivery.

### Risk: Route Edge Count Exceeds Local Capacity

Mitigation: representative plan emits 30 route edges on 4x4, far below full-ring
expansion. Validate predecessor/successor and instruction/block capacities.

## Expected Effect

This RFC converts log10max from symbolic global max into a concrete delivery
path:

```text
local math remains fiber atomic
global max movement is task-local route topology
cross-task coordination uses app barriers
route binding reuses existing primitives
consumer readiness is explicit
runtime_ready fails closed on symbolic communication
```

It should unblock implementation work without compromising the B-line layering
principle or the partner runtime model.

## Open Questions

1. Can the customer first log10max shape accept `task_axis = 1`?
2. Which existing route template family should bind `GlobalMax` first?
3. Is the first update op `FMAX` or `HMAX` for the customer dtype?
4. Which scratch/register slots should hold per-hop `GlobalMax` values?
5. Should the first package include multi-app fallback metadata, or keep it as
   RFC-only until single-task ring stalls?

Resolved from review:

```text
first delivery plan = representative row/column reduce+broadcast
full ring = deferred
one-app cross-task ring = rejected
```

## Recommended Decision

Accept this execution model for log10max V1:

```text
Primary:
  task-local representative row/column reduce+broadcast
  task_axis = 1 when possible
  existing route_push/route_recv + route_path proof
  GlobalMax as route role generalization
  fail closed on symbolic edge/update/consumer binding

Fallback:
  multi-app phased execution only when existing package/runtime path supports it
  PE00 materialized scalar only as debug/delivery escape hatch
  redundant SPMD internal-only unless customer waiver exists

Reject for first delivery:
  one-app cross-task ring
  full-ring generalization
  new communication IR
  direct_route_reduce_broadcast
  physical allreduce claim
```

This is the narrowest design that respects the partner execution model while
still giving B-line a concrete path to log10max binary lowering.
