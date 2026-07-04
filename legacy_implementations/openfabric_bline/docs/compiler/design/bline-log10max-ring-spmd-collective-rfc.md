# RFC: B-line log10max Ring SPMD Collective Strategy

Status: Draft for immediate implementation discussion

Date: 2026-06-23

Owner: B-line delivery

## Summary

For the first log10max delivery, defer `direct_route_reduce_broadcast`.

The proposed execution strategy is a ring-style SPMD reduce-max path over the PE
mesh, expressed only with existing B-line communication and scheduling
primitives:

```text
local reduce max
  -> horizontal ring/reduce across each mesh row
  -> vertical ring/reduce across row representatives
  -> distribute global max back to consumers
  -> log10max postprocess and store
```

This keeps the B-line fiber principle intact: every fiber action remains a flat
atomic tile operation, and communication is represented through the current
`StreamAction(route_push/route_recv)` visibility model, the derived
`FiberOp(fragment_route_push/fragment_route_recv)` projection, and existing
dependency proofs. This RFC must not introduce a new communication IR or a new
backend-only path hidden inside GEMM, log10max, or a bundle.

The main complication is that the current mesh `tasks` axis is independent. A
ring that crosses task groups cannot be assumed to have ordering or visibility
inside one app unless the log10max compile profile constrains `task_axis = 1`.
If that is impossible for the customer shape, the fallback should be a
multi-app phased execution where app boundaries provide ordering.

Hard rule after runtime-model review:

```text
PEs inside one task may cooperate through graph/exeBlock route dependencies.
PEs across different tasks must not cooperate inside one app.
Cross-task reduce/distribute requires an app boundary as the barrier.
```

## Current State

B-line currently has enough structure to express the log10max operator as a
sequence of tile/fiber actions, including local elementwise work and local
reduce-max. The remaining hard part is making the global max visible to all PE
consumers in a way that can become a real binary.

The existing communication and scheduling primitives are already sufficient to
describe the intended topology:

```text
StreamAction(route_push_*)      sender-side visibility action
StreamAction(route_recv_*)      receiver-side visibility action
StreamAction.depends_on         authoritative scheduling edge
StreamPlan.visible_values       stream-local visible value table
FiberOp(fragment_route_push)    fiber/block projection of route send
FiberOp(fragment_route_recv)    fiber/block projection of route receive
FiberDependency(... route_or_local_materialization)
DependencyProof(... proven_by = route_path)
TaskAxisMesh                    no implicit cross-task visibility contract
AppPlan / app boundary          coarse ordering boundary when required
```

The GEMM demo path already uses this pattern for A/B operand movement: a source
stream emits `route_push_A/B`, a destination stream emits `route_recv_A/B`, the
receive depends on the push, and the received value becomes visible on the
destination stream. The ring SPMD reduce should reuse that same model for scalar
max fragments.

The partner app/task/subtask model supports this only inside a task-local graph:

```text
app
  -> task chain / task mask
  -> subtask chain through suc_subtasks
  -> exeBlock graph inside each subtask
  -> PE-local predecessor/successor and COPY/COPYT route endpoints
```

`task0..task3` may be launched together through a task mask, but they are not a
safe internal collaboration domain. The compiler must not generate a one-app
ring whose route edges cross task ids.

The previous PE00 materialized-scalar strategy reduced pressure on direct route
allreduce, but it still depends on several hard proofs:

```text
PE00 combine row bytes
PE00 physical store row bytes
consumer physical readback row bytes
runtime subtask ordering
receiver global scalar binding
```

Those proofs are blocking because they require reliable producer-before-consumer
ordering inside the generated runtime path. If the runtime cannot prove that all
local maxima are materialized before consumers read the global scalar, the
strategy is structurally unsafe.

`direct_route_reduce_broadcast` is the correct long-term route when route,
reduce, synchronization, and broadcast semantics are fully mapped. It is not the
right first-delivery path.

## Problem

log10max requires:

```text
log_spec = log10(clamp(mel_spec, min=1e-10))
global_max = reduce_max(log_spec)
out = maximum(log_spec, global_max - 8.0)
out = (out + 4.0) / 4.0
```

The `global_max` value must be derived from all participating PE shards and then
made visible to each PE that performs the final postprocess.

The key engineering problem is not whether B-line can express this semantically.
It can. The problem is whether the physical lowering can provide:

```text
cross-PE value movement
max update at each hop
ordering between producer and consumer phases
final global scalar visibility
```

without pretending that independent task groups are synchronized.

## Goals

1. Ship a first log10max binary path without depending on
   `direct_route_reduce_broadcast`.
2. Preserve B-line architecture: high-level ops lower into a flat fiber op
   chain, and each fiber op lowers through templates/physical rows.
3. Represent collective behavior as explicit uses of existing route visibility
   and dependency primitives.
4. Make task-axis constraints explicit in the compile profile and metadata.
5. Prefer a single-app `task_axis = 1` route for first delivery.
6. Define a multi-app fallback when task-axis independence prevents one-app
   ordering.

## Non-goals

1. Do not implement or claim direct physical allreduce in this RFC.
2. Do not hide communication inside a synthetic log10max bundle.
3. Do not introduce a new route, collective, or scheduling IR.
4. Do not add backend-only communication paths that bypass `StreamPlan`,
   `FiberOp`, or dependency provenance.
5. Do not reintroduce fused or expanded fiber semantics.
6. Do not solve arbitrary mesh collectives. This RFC targets reduce-max for the
   current log10max delivery.
7. Do not claim numerical correctness until the emitted binary is checked
   against a host reference.

## Proposed Design

### Strategy Enum

Add a new B-line collective strategy:

```text
collective_strategy = ring_spmd_row_then_col
customer_collective_label = spmd_ring_materialized_reduce
```

Keep the existing long-term enum reserved:

```text
direct_route_reduce_broadcast
```

but mark it as deferred for this delivery.

### First Delivery Constraint

The first delivery profile should force log10max to compile with:

```text
task_axis = 1
```

This means the participating PE mesh is treated as one task group for the
collective portion. The ring is then a within-task SPMD communication pattern,
not a cross-task synchronization claim.

If `task_axis = 1` is not acceptable for the required customer shape, the
compiler must not silently emit a one-app ring across independent tasks. It must
switch to the multi-app plan described below. There is no cross-task one-app
proof escape hatch in the first-delivery path.

### Ring Reduce Shape

For a 2D mesh, the reduce has three conceptual stages:

```text
Stage A: local_reduce_max
Stage B: horizontal row reduce/ring
Stage C: vertical column reduce/ring over row representatives
Stage D: distribute global max to all consumer PEs
```

The simplest first implementation should use deterministic row representatives,
for example column 0:

```text
local_max[pe_y, pe_x]
  -> row_max[pe_y] at pe_x = 0
  -> global_max at pe_y = 0, pe_x = 0
  -> broadcast global_max down column 0
  -> broadcast global_max across each row
```

This is still ring/SPMD style at the fiber level because every transfer is an
explicit point-to-point route visibility action plus a local max update. It
avoids requiring a hidden backend collective.

Each edge in the ring must be encoded with the same shape as existing B-line
operand route movement:

```text
sender stream:
  StreamAction(
    op="route_push_global_max",
    inputs=(current_max_value,),
    depends_on=(producer_action,),
    attrs={"src": sender_stream, "dst": receiver_stream, "phase": ...}
  )

receiver stream:
  StreamAction(
    op="route_recv_global_max",
    inputs=(current_max_value,),
    outputs=(received_max_value,),
    depends_on=(push_action,),
    attrs={"src": sender_stream, "dst": receiver_stream, "phase": ...}
  )

receiver stream:
  StreamAction(
    op="max_update_global_max",
    inputs=(local_current_max, received_max_value),
    outputs=(updated_max_value,),
    depends_on=(recv_action,)
  )
```

The exact op strings can be normalized during implementation, but the authority
must remain the existing stream action and dependency model.

A full ring where every PE learns the row max during the row phase is also
possible, but it emits more communication rows. The first delivery should prefer
the representative form unless template evidence makes the full ring cheaper.

### Fiber Op Chain

The log10max fiber chain should become explicit:

```text
TileComputeAction(clamp_min_tile)
TileComputeAction(log2_tile)
TileComputeAction(mul_log10_2_tile)
TileComputeAction(local_reduce_max_tile)

TileRouteAction / FiberOp(fragment_route_push)
TileRouteAction / FiberOp(fragment_route_recv)
TileComputeAction(ring_update_max_tile)
...

TileComputeAction(max_with_global_floor_tile)
TileComputeAction(add_scalar_tile)
TileComputeAction(mul_scalar_tile)
TileStoreAction(store_tile)
```

Communication actions are first-class uses of existing route fiber ops. Template
lowering may expand them into existing route rows, route endpoint visibility
rows, scratch-backed materialization rows, or multiple vendor component rows,
but the expansion must preserve provenance back to the original stream/fiber
route op. A new communication primitive is not allowed by this RFC.

In implementation terms, the preferred projection is:

```text
StreamAction(route_push_global_max)
  -> FiberOp(fragment_route_push, operand="GlobalMax")
  -> existing operand_route_push-style role/template binding

StreamAction(route_recv_global_max)
  -> FiberOp(fragment_route_recv, operand="GlobalMax")
  -> existing operand_route_recv-style role/template binding
  -> FiberDependency(expected_satisfaction="route_or_local_materialization")
  -> DependencyProof(proven_by=("route_path",))
```

### Template Lowering

Each ring edge needs a concrete lowering record:

```text
source PE
destination PE
source scalar/register/scratch slot
destination scalar/register/scratch slot
ordering group
update op = FMAX or HMAX according to dtype
row provenance = FiberOp id
```

The max update should use the original instruction set evidence:

```text
FMAX for fp32-style max when applicable
HMAX for fp16-style max when applicable
IMM for constants where required
```

The communication primitive must come from existing route/copy/scratch template
evidence. If a direct neighbor route template is not yet trustworthy, the first
fallback is a materialized scratch/mailbox edge with an app or phase boundary,
not `direct_route_reduce_broadcast`.

The template layer may need to generalize existing operand route roles beyond
`A` and `B` so that `GlobalMax` can reuse the same mechanism:

```text
operand_route_push:A          existing
operand_route_recv:A          existing
operand_route_push:B          existing
operand_route_recv:B          existing
operand_route_push:GlobalMax  allowed role generalization
operand_route_recv:GlobalMax  allowed role generalization
```

This is a role generalization of the existing route primitive, not a new
communication path.

### Runtime Decomposition

#### Primary Route: Single App, `task_axis = 1`

Use one app when the whole participating mesh can be represented inside one
task group:

```text
App log10max:
  local elementwise/reduce
  row reduce
  column reduce
  global max distribution
  postprocess
  store
```

This route needs local ordering between ring phases. The compiler should emit
explicit phase/order metadata even if the runtime ultimately serializes the rows
through existing task/subtask order.

#### Fallback Route: Multi-app Phases

If task-axis independence prevents one-app ordering, split execution:

```text
App 0:
  local elementwise
  local reduce max
  materialize per-task/per-PE local maxima

App 1:
  reduce materialized maxima using task_axis = 1 or a scalar-only profile
  materialize global max

App 2:
  read global max
  postprocess
  store
```

The app boundary is the ordering mechanism. This is heavier but honest: it does
not require unproven cross-task synchronization inside one app.

This fallback is mandatory for cross-task cooperation. A later implementation
may optimize the number of apps, but the first correct shape is:

```text
App N finishes
  -> DPU_Kernel_Wait_Finish observes completion
  -> App N+1 starts
```

That wait/start boundary is the only accepted cross-task barrier in this RFC.

## Invariants

1. `direct_route_reduce_broadcast` is deferred and must not appear in the first
   delivery manifest as the selected strategy.
2. A one-app ring may only cross PEs inside the same task-local visibility and
   ordering domain.
3. If `task_axis > 1`, one-app cross-task ring is forbidden. The compiler must
   either constrain the log10max collective to per-task local rings or split the
   cross-task reduce/distribute into multiple apps.
4. Ring communication must be represented by existing route visibility
   primitives: `StreamAction(route_push/route_recv)` and projected
   `FiberOp(fragment_route_push/fragment_route_recv)`.
5. `StreamAction.depends_on` remains the scheduling source of truth; separate
   route graphs are derived views only.
6. Every physical row emitted for a ring edge must preserve provenance to the
   source stream action and projected fiber op.
7. The strategy label must not claim physical allreduce.
8. GEMM/ReLU fiber rules remain unchanged: no fused epilogue, no hidden
   expansion inside fiber semantics.
9. The RFC allows role generalization for `GlobalMax`; it does not allow new
   communication or scheduling authority.
10. App boundary is the only first-delivery cross-task barrier.

## Alternatives

### PE00 Materialized Scalar

PE00 aggregation is simple to describe but depends on producer/consumer ordering
and scalar readback proofs. It remains a possible fallback if those proofs become
available, but it should not block the ring plan.

### Redundant SPMD Recompute

Every PE independently scans the full reduce domain. This is only valid if every
PE can read the full input domain and the runtime cost is acceptable. It should
remain an internal bring-up strategy, not the default customer path.

### Direct Route Reduce Broadcast

This is the long-term clean physical collective, but it requires route, reduce,
broadcast, and synchronization semantics to be fully understood. Defer it until
after first delivery.

## Implementation Plan

1. Add `ring_spmd_row_then_col` to the log10max collective strategy enum and
   reports.
2. Add a log10max compile profile option that forces `task_axis = 1` for first
   delivery.
3. Lower log10max global max movement into existing stream route actions:
   `route_push_global_max`, `route_recv_global_max`, and dependent
   `max_update_global_max` actions.
4. Project those actions into existing fiber/block route forms:
   `fragment_route_push`, `fragment_route_recv`, and normal tile compute update
   ops.
5. Add ring edge metadata:
   source PE, destination PE, phase, dtype, update op, scratch/register binding,
   and FiberOp provenance.
6. Bind max update templates through FMAX/HMAX instruction evidence.
7. Generalize existing operand route roles to include `GlobalMax` if needed.
8. Bind communication templates using the safest existing neighbor route or
   scratch/mailbox evidence.
9. Change runtime-ready blockers from PE00-specific blockers to ring-specific
   blockers:

```text
task_axis_scope_unproven
cross_task_one_app_ring_forbidden
ring_edge_template_missing
ring_phase_order_missing
global_max_distribution_missing
consumer_global_max_binding_missing
route_path_proof_missing
```

10. If `task_axis = 1` cannot satisfy the customer shape, implement the multi-app
   decomposition and mark app boundaries as the ordering proof.

## Validation Plan

Local validation should stay small and delivery-focused:

1. Compile report shows:

```text
collective_strategy = ring_spmd_row_then_col
task_axis = 1
direct_route_reduce_broadcast = deferred
```

2. Fiber dump contains explicit communication ops and no hidden bundle
   semantics.
3. Ring graph check verifies:

```text
all source/destination PEs are in the same runtime ordering domain
no one-app route edge crosses task ids
every row has a horizontal reduce path
the column representative path reaches the global representative
global max is distributed to all consumer PEs
```

4. Template report verifies:

```text
FMAX/HMAX update rows are concrete
communication edge rows are concrete or fail closed
route push/recv roles reuse existing route template family
no symbolic global max reaches uploadable state
```

5. Dependency projection verifies:

```text
fragment_route_recv dependencies are proven by route_path
no route edge depends on a private/derived route graph as authority
task_axis scope is explicit
cross-task phases are separated by app wait/start when task_axis > 1
```

6. Runtime-ready aggregation must fail if any ring edge, phase order, or
   consumer binding remains symbolic.

7. Numerical validation remains a separate state:

```text
runtime_ready != numerically_checked
```

## Risks

1. `task_axis = 1` may reduce parallelism or fail to match the customer runtime
   shape.
2. Neighbor communication templates may still be incomplete.
3. Multi-app decomposition increases launch overhead and package complexity.
4. A full ring emits more rows than a representative reduce/broadcast plan.
5. If scratch/mailbox communication is used, address allocation must be explicit
   and must not conflict with existing tensor regions.

## Expected Effect

This strategy turns log10max from a PE00 ordering problem into an explicit SPMD
communication problem. It avoids claiming a direct hardware collective before
the route semantics are ready, and it gives the compiler a concrete first path:

```text
force task_axis = 1
emit row/column ring as existing route push/recv plus update ops
bind local max updates through FMAX/HMAX
bind communication through existing route or materialized edge templates
fail closed if global max is not visible to consumers
```

## Open Questions

1. Should first delivery use representative row/column reduce, or full row and
   column rings where every PE learns the max at each phase?
2. Which existing route/copy/scratch template evidence should be selected for
   `GlobalMax` route push/recv role binding?
3. Can the required customer log10max shape accept `task_axis = 1` for first
   delivery?
4. If not, should the multi-app fallback use two apps or three apps? Cross-task
   cooperation cannot happen inside one app either way.
5. Should PE00 materialized scalar remain available as a debug-only fallback?

## Recommended Decision

Accept the RFC direction:

```text
Use ring_spmd_row_then_col for first log10max delivery.
Force task_axis = 1 when possible.
Use multi-app phased execution when cross-task cooperation is required.
Defer direct_route_reduce_broadcast.
Do not claim physical allreduce.
Do not introduce new communication or scheduling primitives.
Represent ring edges with existing StreamPlan route actions, FiberOp route
projection, and route_path dependency proofs.
Forbid one-app cross-task ring.
```

This is the most honest progress-first path: it keeps B-line semantics clean,
gives log10max a concrete global-max movement plan, and avoids spending the
delivery window proving the long-term direct-route collective.
