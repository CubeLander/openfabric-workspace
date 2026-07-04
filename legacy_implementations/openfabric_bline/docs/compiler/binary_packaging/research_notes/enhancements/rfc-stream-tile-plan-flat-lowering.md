# RFC: StreamTilePlan as Flat Tile-Action Lowering

Date: 2026-06-18
Status: Draft for review
Scope: New `core/stream_compiler` line, not production DFU lowering yet

## Summary

The existing `ProcessorTileProgram` is important, but it grew around several
simultaneous goals:

1. split logical processor actions into tile-sized units,
2. represent GEMM K-loop repeat semantics,
3. expose route / compute / store executable block boundaries,
4. provide enough metadata for node packing, DFU micro-op roles, vendor ABI, and
   binary diffing,
5. preserve expanded debug views while preparing folded vendor instance loops.

That old design was useful for reaching vendor binary parity, but it does not fit
our current direction: a flat, stream-action lowering model where the primary IR
truth is:

```text
StreamPlan
  streams[]
    actions[]
      depends_on[]
```

This RFC proposes a new `StreamTilePlan` line under
`compiler/gpdpu_compiler/core/stream_compiler/`.  It should lower flat stream
actions to flat tile actions, preserving action-local dependencies as the source
of truth.  It should avoid importing the old `TilePhase` / `TileCollectiveBundle`
/ `LogicalRouteEdge` worldview into the new line unless a specific downstream
compatibility adapter needs a derived view.

The goal is not to delete the old path immediately.  The goal is to build a clean
parallel model that can later reconnect to existing micro-op / packing / vendor
layers at a natural seam.

## Background

We recently introduced an experimental `StreamPlan` model:

```text
App ops
  -> left-to-right stream suffix lowering
  -> flat stream action lists
  -> action-local depends_on links
  -> derived graph/route views only when needed
```

A GEMM app op sequence such as:

```text
load A
load B
matmul
relu
store Y
```

can lower to stream actions like:

```text
stream t0_pe01:
  route_recv_A
  route_push_A
  sram_read_B
  route_push_B
  matmul(depends_on=[route_recv_A, sram_read_B])
  relu(depends_on=[matmul])
  sram_store_Y(depends_on=[relu])
```

This is intentionally flat.  Route actions are not hidden in a separate route
edge table.  Dependencies are stored on downstream actions.  Any edge table is a
view.

The next natural question is whether we need an equally complex tile layer.  The
answer is nuanced:

- yes, we need a tile-level view, because stream-visible tensors must be sliced
  into tile-visible fragments before GEMM, route, store, and eventual vendor
  templates;
- no, we should not copy the old `ProcessorTileProgram` shape wholesale.

## Investigation: why the old tile layer is complex

The old `program_tile.py` states its original purpose clearly: it lowers
processor-local logical actions into tile-sized tasks and names tile values,
phases, and logical collective bundles before backend materialization.

Over time it accumulated several legitimate responsibilities.

### 1. Tile value decomposition

`_lower_generic` and `_lower_store` maintain `value_final_tile_actions`, mapping a
logical value to the tile action(s) that most recently produced tile fragments.
This is needed because a later store cannot write a whole logical DTensor at once;
it must know which tile action produced each tile-sized piece.

This responsibility is still needed in the new model, but it should be expressed
as a first-class `tile_visible` table:

```text
tile_visible[(stream_id, logical_value_id, tile_coord)] = TileValueRef
```

### 2. GEMM K-loop structure

Old `_lower_matmul` expands each local matmul into:

```text
accumulator_prepare
for k_block in k_blocks:
  route A tile prefix
  route B tile prefix
  compute_update
store/finalize
```

It also builds `TileLoopRegion` and `TileLoopBodyInstance` so later passes can
fold K into vendor subtask instance repeat instead of emitting a giant expanded
DAG.

This was not accidental complexity.  It was necessary to avoid representing:

```text
k0 -> k1 -> k2 -> k3
```

as vendor graph edges.  K recurrence is loop-carried state and should be lowered
into repeat/instance semantics or local PC order.

The new model still needs loop information, but it does not need to wrap it in
`TilePhase` or make a separate phase payload the primary truth.  A tile action
may carry:

```text
loop_region_id
loop_instance_id
loop_axis="k"
fold_policy="vendor_instance_repeat_candidate"
```

and a separate loop metadata view can be derived from those annotations.

### 3. Route and visibility expansion

Old tile lowering consumes `LogicalRouteEdge.route_steps` and expands each route
step into `TileRouteAction`.  This was required because the old logical layer kept
route path structure outside normal stream actions.

In the new stream model, route push/recv/forward actions are already normal stream
actions.  Tile lowering should therefore lower those stream actions directly:

```text
route_push_A(stream action)
  -> route_push_A_tile for each relevant tile fragment

route_recv_A(stream action)
  -> route_recv_A_tile / visibility token for each relevant tile fragment
```

No separate `LogicalRouteEdge` should be required as authoritative input.  If a
legacy compatibility view needs route groups, derive it from tile actions.

### 4. Micro-block authority

The old path introduced `TileMicroBlock` because downstream `ProgramAsm` and
`ProgramVendorABI` must not rediscover route/compute/store executable boundaries
from generic nodes.  This lesson is still valid.

The new path should not skip executable block partitioning.  It should make the
partition simpler:

```text
StreamTileAction
  -> TileBlock view / MicroBlock view
  -> micro-op roles
```

A block view may be derived from action kinds and loop annotations, but once
created it should be the authority for micro-op / vendor-template lowering.

### 5. Vendor compatibility and debug views

The old tile program contains `TilePhase`, `TileProgramItemRef`,
`TileCollectiveBundle`, `TileLoopRegion`, `TileMicroBlock`, `TileDependency`, and
several index tables.  Some of these are real semantic layers; others are review
or compatibility views.

For the new line, we should distinguish:

```text
Authoritative:
  flat tile actions
  action-local dependencies
  tile_visible table
  loop annotations on actions

Derived views:
  dependency edge table
  route group table
  collective bundle table
  phase/program_sequence view
  micro-block index
  vendor packing projection
```

This distinction is the center of the RFC.

## Problem with copying old ProcessorTileProgram

If we implement `StreamTilePlan` by cloning old `ProcessorTileProgram`, the new
line will inherit the old shape:

```text
TilePhase
TileCollectiveBundle
TileRouteAction / TileComputeAction / TileStoreAction split tables
TileDependency table
TileLoopRegion
TileMicroBlock
ProcessorTileActionStream
```

That recreates the same issue we are trying to escape: multiple parallel sources
of truth.  The old code was engineered under pressure to support vendor parity;
it was not designed around the left-to-right flat stream lowering principle.

The new model should therefore start smaller and only add views when a consumer
proves it needs them.

## Proposed model

### Core IR

Add an experimental `StreamTilePlan` under `core/stream_compiler`:

```text
StreamTilePlan
  app_id
  streams: dict[stream_id, list[StreamTileAction]]
  tile_visible: dict[(stream_id, logical_value_id, tile_coord), StreamTileValue]
```

### StreamTileAction

A tile action is a normal stream action at tile granularity:

```text
StreamTileAction
  id
  stream_id
  op
  source_stream_action_id
  source_chip_op
  tile_coord
  inputs
  outputs
  depends_on
  attrs
```

Dependencies live on the downstream action:

```text
compute_tile.depends_on = [a_tile_visible_action, b_tile_visible_action]
store_tile.depends_on = [relu_tile]
route_recv_tile.depends_on = [route_push_tile]
```

There is no authoritative `tile_dependencies` table.  A table can be derived.

### StreamTileValue

A tile-visible value describes one fragment visible on one stream:

```text
StreamTileValue
  id
  stream_id
  logical_value_id
  tile_coord
  kind
  producer_action_id
  shape
  global_offset
  attrs
```

The table:

```text
tile_visible[(stream_id, logical_value_id, tile_coord)]
```

is the tile-level analogue of `StreamPlan.visible_values`.

### Loop metadata

Loop/repeat metadata should be action annotation first:

```text
loop_region_id
loop_axis
loop_instance_id
repeat_count
fold_policy
carried_refs
variant_refs
```

A `TileLoopRegion`-like report can be derived from actions sharing the same
`loop_region_id`.  The derived report may still be necessary for packing and
review, but it should not be the only way to understand the action stream.

### Block / micro-op metadata

Executable block partition remains important.  The new model should support a
block projection:

```text
StreamTileAction(s)
  -> TileBlock / MicroBlock view
  -> TileMicroOp roles
```

But block projection should be a later pass over flat tile actions, not something
that forces `StreamTilePlan` itself to be phase/block-shaped.

## Lowering algorithm

The new tile lowering should mirror the stream lowering algorithm:

```text
for stream_action in stream.actions:
  lower stream_action into zero or more tile actions
  record produced tile-visible values
  attach dependencies to downstream tile actions
```

### Example: sram_read_A

For each tile of the local shard:

```text
sram_read_A
  -> sram_read_A_tile(tile_coord=(m_tile,k_block))
  -> tile_visible[(stream,A,m_tile,k_block)]
```

### Example: route_push_A / route_recv_A

If `route_push_A` depends on an upstream visible A value, tile lowering expands
it per tile fragment:

```text
route_push_A_tile(tile_coord)
  depends_on=[producer tile action for A tile_coord]

route_recv_A_tile(tile_coord)
  depends_on=[route_push_A_tile(tile_coord)]
  produces tile_visible[(receiver,A,tile_coord)]
```

This makes route wiring local and explicit without a separate route edge IR.

### Example: matmul

For each output tile and K block:

```text
accumulator_prepare_tile(m_tile,n_tile)

compute_update_tile(m_tile,n_tile,k)
  depends_on=[
    tile_visible[(stream,A,m_tile,k)],
    tile_visible[(stream,B,k,n_tile)],
    accumulator_prepare if k == 0 else compute_update(k-1),
  ]
```

The resulting C tile is recorded in `tile_visible` only after the final K update
or a finalize/relu action, depending on lowering policy.

### Example: relu/store

```text
relu_tile(m_tile,n_tile)
  depends_on=[final C tile producer]

store_tile(m_tile,n_tile)
  depends_on=[relu_tile]
```

This matches the existing TODO direction: generic fusion should become explicit
tile op chains instead of hidden payload fields.

## What to keep from old design

The old design contains hard-won lessons.  We should preserve these principles:

1. Tile-level actions are not assembly or vendor instruction rows.
2. Route, compute, and store executable block boundaries must be decided before
   `ProgramAsm` / `ProgramVendorABI`.
3. K-loop recurrence should be represented as loop-carried state, not as vendor
   graph predecessor/successor edges.
4. Fine-grained tile route visibility must be traceable to producer and consumer.
5. Store depends on final tile value; app storage materialization must be explicit.
6. Downstream packing must not rediscover block roles from anonymous nodes.

## What to change

### Stop making phase the primary truth

Old `TilePhase` bundles local ops, route prefixes, collective refs, payloads, and
fused post-ops.  In the new line, phase-like views should be derived from flat
actions.

### Stop using route-edge expansion as the primary route model

Old route expansion starts from `LogicalRouteEdge.route_steps`.  New route tile
actions should originate from stream route actions.  Route group reports can be
derived later.

### Stop keeping an authoritative dependency table

Dependencies should live on actions.  A dependency table is a query view.

### Stop hiding fusion in GEMM payloads

GEMM+ReLU can remain fused in production for parity, but the new stream tile line
should represent `relu_tile` explicitly.

## Proposed implementation phases

### Phase 0: documentation and tests for current demo

- Keep `stream_compiler/gemm_demo.py` as an executable toy model.
- Add focused tests locking:
  - `route_push` consumes the current stream-visible value,
  - `matmul` depends on visible A/B producer actions,
  - `dependency_edges()` is derived from action `depends_on`.

### Phase 1: define tile IR skeleton

Add:

```text
core/stream_compiler/tile_ir.py
```

with:

```text
StreamTileAction
StreamTileValue
StreamTilePlan
```

No production wiring.

### Phase 2: lower route-free simple chain

Prototype:

```text
sram_read -> relu -> store
```

or a fake single-stream matmul with no route.  Goal: validate `tile_visible` and
action-local dependencies without route complexity.

### Phase 3: lower GEMM demo materialization routes

Lower the existing demo route actions into per-tile `route_push_A_tile` /
`route_recv_A_tile` and B equivalents.  Ensure each recv tile depends on the
matching push tile and each push tile depends on the current stream-visible tile.

### Phase 4: lower GEMM compute and explicit ReLU/store

Create tile actions for:

```text
accumulator_prepare
compute_update(k)
relu_tile
store_tile
```

Add loop annotations to compute/update actions.  Produce a derived loop report,
but keep flat tile actions authoritative.

### Phase 5: compatibility adapter to old views

Only when needed, derive old-style views:

```text
TileRouteAction view
TileComputeAction view
TileStoreAction view
TileLoopRegion view
TileMicroBlock view
```

This adapter can be the natural jump-back point into the current micro-op /
packing / vendor flow.

### Phase 6: evaluate replacing production tile lowering

Once the adapter can reproduce enough old plan shape for GEMM, compare:

- action counts,
- route/compute/store role counts,
- loop repeat metadata,
- microblock roles,
- eventually vendor ABI and binary artifacts.

## Open questions

### 1. Should `StreamTilePlan` use one unified action class or typed subclasses?

Recommendation: start with one unified `StreamTileAction` plus `op` / `attrs`.
Use typed helper constructors if readability suffers.  Do not recreate separate
route/compute/store action tables as primary IR.

### 2. Should route recv be an executable action?

At logical stream level yes: it is a receiver-side visibility event.  At DFU tile
execution level the actual instruction may be sender-side COPY/COPYT.  The tile
action can carry:

```text
execution_stream
endpoint_stream
```

This preserves the simple stream-action model while allowing DFU sender-push
semantics downstream.

### 3. How do we represent vendor instance repeat?

As loop annotations on tile actions first.  Derived `TileLoopRegion` reports can
be generated for packing.  Avoid making loop region the only source of body
membership truth.

### 4. How do we avoid huge expanded plans?

For MVP, expanded tile actions are acceptable for review.  Later, the same flat
action model can support symbolic loop bodies:

```text
StreamTileLoopTemplate
  body_actions
  repeat_axis=k
```

But do not start with an opaque loop template.  We need expanded debug visibility
while validating wiring.

### 5. Can we skip `StreamTilePlan` entirely?

Probably not.  Stream-level values are too coarse for GEMM, route, and store.
The minimal useful layer is not a full old `ProcessorTileProgram`, but it must at
least map:

```text
stream-visible logical value
  -> tile-visible fragments
  -> per-tile dependencies
```

That is exactly `StreamTilePlan`.

## Recommendation

Accept this RFC direction:

```text
Build StreamTilePlan as a new-line flat tile-action IR.
Do not clone old ProcessorTileProgram.
Keep tile actions and action-local dependencies authoritative.
Represent tile-visible values explicitly.
Make loop/block/route/phase tables derived views until a downstream consumer
proves they need to become stable interfaces.
```

This gives us a clean, readable middle layer while preserving the lessons learned
from the old vendor-parity path.

## Addendum: topology-preserving slicing and micro-distribution

A better mental model for stream-to-tile lowering is a river model:

```text
StreamPlan = topology / river direction
StreamTilePlan = longitudinal slicing of the same rivers
LoopRegion = cross-section view over repeated slices
```

Tile lowering should not rediscover inter-stream topology.  The stream program
has already decided which stream sends to which stream and which downstream
actions depend on which upstream actions.  Tile lowering preserves that shape and
refines whole-stream values into tile fragments.

For a route action:

```text
route_push_A: S0 -> S1
```

tile lowering should produce a family of corresponding tile actions with the
same producer/consumer shape:

```text
route_push_A_tile(k0): S0 -> S1
route_push_A_tile(k1): S0 -> S1
route_push_A_tile(k2): S0 -> S1
route_push_A_tile(k3): S0 -> S1
```

The hard part is not route topology.  The hard part is choosing an isomorphic
vertical slicing scheme for each action's input/output values so dependencies can
be refined from whole-value edges to tile-fragment edges.

### Why naive slicing fails for GEMM

For elementwise chains, the slicing is almost zip-like:

```text
X_tile(i) -> relu_tile(i) -> Y_tile(i)
```

The output tile and input tile usually share the same tile coordinate.

GEMM is different.  One output tile does not consume one A tile and one B tile.
It consumes a family of K-slices:

```text
C(m,n) = sum_k A(m,k) @ B(k,n)
```

This means different output tiles reuse input fragments:

```text
C(m,n0) and C(m,n1) both reuse A(m,k)
C(m0,n) and C(m1,n) both reuse B(k,n)
```

Therefore stream-to-tile lowering still needs a matrix micro-distribution rule.
It is not enough to slice each stream-visible input/output tensor naively by the
same tile coordinate.  The tile layer must know the local operator's tile access
map:

```text
matmul output tile (m_tile, n_tile)
  requires A tiles (m_tile, k_block)
  requires B tiles (k_block, n_tile)
  produces C tile (m_tile, n_tile)
```

This is the real difficulty hidden inside `StreamTilePlan`:

```text
stream topology is already solved;
tile micro-distribution is still operator-specific.
```

### Implication for the new design

`StreamTilePlan` should be a slicer, but not a blind slicer.  It needs
operator-provided tile access maps:

```text
ElementwiseTileAccess:
  output_tile(i) <- input_tile(i)

MatmulTileAccess:
  output_tile(m,n) <- A_tile(m,k), B_tile(k,n) for k in K-blocks

StoreTileAccess:
  storage_tile(i) <- visible_value_tile(i)
```

This gives a sharper boundary than the old design:

- stream compiler owns inter-stream topology and value visibility,
- tile compiler owns intra-stream micro-distribution and tile access maps,
- op specs may provide tile access maps,
- tile compiler materializes those maps into flat tile actions and dependencies.

In short:

```text
StreamPlan answers: which stream can see which whole value?
StreamTilePlan answers: which tile fragments of that value are needed by each
stream action?
```

This is why `StreamTilePlan` remains necessary, but it can be much simpler than
old `ProcessorTileProgram`: it preserves stream topology and focuses on value
fragment slicing plus operator tile access maps.

## Addendum: tile fibers and micro-DTensor partitioning

Another useful interpretation is that `StreamTilePlan` performs a second,
processor-local DTensor-style partitioning pass.

The macro placement already did:

```text
tensor -> stream-visible shard
```

The tile plan now does:

```text
stream-visible shard -> tile-visible fragments -> compute fibers
```

A **fiber** is a minimal tile-level compute lane.  For GEMM, a natural fiber is:

```text
GemmFiber(m_tile, n_tile, k_block)
```

It consumes:

```text
A_fragment(m_tile, k_block)
B_fragment(k_block, n_tile)
```

and contributes to:

```text
C_fragment(m_tile, n_tile)
```

This gives a more precise picture of why tile-level GEMM is not a naive zip of
input/output tile coordinates.  Many fibers share the same fragment entrance:

```text
A(m,k) feeds C(m,n0,k), C(m,n1,k), ...
B(k,n) feeds C(m0,n,k), C(m1,n,k), ...
```

So from the fiber viewpoint, reading or receiving an input tile fragment behaves
like a local collective / fanout source.  It materializes one fragment that many
fibers may consume.  Across streams, the same idea composes with stream-level
routing:

```text
stream-level route materializes A(m,k) on peer streams
  -> tile-level fragment fanout feeds many local GEMM fibers
```

This suggests a clean conceptual split:

```text
StreamPlan:
  coarse visibility of logical values across streams

StreamTilePlan:
  local micro-DTensor partitioning into fragments and fibers

TileFiber / TileAction:
  minimal compute lanes and fragment materialization/fanout actions
```

### Fiber vocabulary

A future `StreamTilePlan` can use these terms without adding a heavy graph layer:

```text
TileFragment:
  one tile-visible piece of a stream-visible logical value

TileFiber:
  one minimal tile compute lane, e.g. GEMM(m,n,k)

FragmentProducer:
  action that materializes a fragment: sram_read, route_recv, compute, etc.

FragmentFanout:
  one produced fragment feeding many fibers or forwarding actions
```

The IR can remain flat:

```text
streams[]
  tile_actions[]
    depends_on[]
```

but the action attrs / derived debug views can expose the fiber interpretation:

```text
compute_update_tile:
  fiber = GemmFiber(m_tile=0, n_tile=1, k_block=2)
  inputs = [A_fragment(0,2), B_fragment(2,1)]
```

### Design implication

The next hard problem is not just slicing values.  It is preserving fragment
reuse and fanout.  A correct tile lowering must avoid treating every output fiber
as owning private input reads when the algorithm actually shares input fragments.

Therefore op specs should be allowed to provide tile fiber access maps:

```text
MatmulFiberAccess:
  fiber(m,n,k)
    consumes A(m,k)
    consumes B(k,n)
    contributes C(m,n)
```

The stream/tile compiler then decides how those fragments are produced, reused,
forwarded, and connected with action-local dependencies.

This is a compact way to express the real issue:

```text
Stream topology is solved.
Tile fiber micro-distribution and fragment reuse are the remaining core problem.
```

## Addendum: deterministic fiber schedule as micro-SPMD

The fiber model gives the tile layer a new simplifying structure: after stream
lowering, tile work can become SPMD again at a finer granularity.

Instead of treating each stream as an unrelated local tile program, define a
deterministic fiber schedule shared by a group of streams:

```text
for fiber_step in FiberSchedule:
  materialize required fragments for this step
  run each stream's local fiber instance for this step
  update local outputs / carried state
```

Each stream executes the same schedule shape, but with stream-local coordinates.
For GEMM:

```text
stream S00:
  fiber(m0,n0,k0)
  fiber(m0,n0,k1)
  fiber(m0,n0,k2)

stream S01:
  fiber(m0,n1,k0)
  fiber(m0,n1,k1)
  fiber(m0,n1,k2)

stream S10:
  fiber(m1,n0,k0)
  fiber(m1,n0,k1)
  fiber(m1,n0,k2)
```

The important point is that the shape is deterministic and shared.  The schedule
is not discovered after the fact from a tangled action graph; it is the generator
of tile actions.

### Fragment reuse emerges from schedule steps

If all streams advance through the same `k_block` step, then shared input
fragment requirements become explicit and naturally reusable:

```text
step k0:
  materialize A(*, k0)
  materialize B(k0, *)
  run all fibers that consume k0 fragments

step k1:
  materialize A(*, k1)
  materialize B(k1, *)
  run all fibers that consume k1 fragments
```

This reframes route/materialize planning.  We no longer need to rediscover that
many fibers share `A(m,k)` or `B(k,n)`.  The deterministic fiber schedule exposes
that reuse as part of the step definition.

### Proposed vocabulary

```text
FiberSchedule:
  deterministic ordered plan shared by a stream group

FiberStep:
  one schedule step, such as k_block=0 for GEMM

FiberInstance:
  the stream-local work item for a step, such as GEMM(m,n,k)

StepFragmentSet:
  required fragments for the whole step, such as A(*,k), B(k,*)

FragmentMaterializationPlan:
  route/read/fanout actions that make the step fragments visible
```

### Why this helps

This model turns tile lowering from graph archaeology into deterministic
construction:

```text
FiberSchedule
  -> fragment materialization actions
  -> per-stream fiber compute actions
  -> carried-state / output actions
```

It also provides a cleaner source for loop metadata:

```text
repeat_axis = k
repeat_count = len(FiberSchedule.k_steps)
loop_body = actions generated by one FiberStep
```

So vendor instance repeat metadata can be derived from the schedule generator,
not recovered from a large expanded dependency graph.

### Design principle

```text
StreamPlan restores deterministic visibility across streams.
FiberSchedule restores deterministic SPMD structure inside the tile layer.
```

This is the target shape for `StreamTilePlan`: a flat tile-action IR generated
from deterministic fiber schedules, with action-local dependencies and derived
views for route groups, loop regions, and micro-blocks.

## Reviewer integration: contracts to freeze before implementation

The review accepts the architecture direction, but it correctly points out that
several contracts must be frozen before Phase 2/3.  This section upgrades those
contracts from intuition to implementation constraints.

### 1. Authority lifecycle

For MVP, use this authority model:

```text
FiberSchedule:
  generator / provenance object
  produces deterministic tile actions
  not the post-lowering execution IR authority

StreamTilePlan:
  materialized semantic IR authority
  flat tile actions + values + action-local dependencies are truth

Derived views:
  dependency edge table
  route group report
  loop report
  block/micro-op projection
  vendor packing projection
```

If a later pass rewrites `StreamTilePlan`, any derived view must be invalidated.
If a future symbolic loop/template representation becomes authoritative, it must
be introduced explicitly as a separate `StreamTileLoopTemplate` authority mode.

### 2. Value/version model

`tile_visible[(stream_id, semantic_value_id, tile_coord)]` is a **current binding
map**, not immutable provenance.  Actions must refer to immutable value versions.

MVP schema should distinguish:

```text
semantic_value_id:
  logical tensor/value identity, e.g. A_dtensor, C_dtensor, Y_dtensor

version_id:
  producer-specific value version, e.g. C_after_k1, Y_after_relu

TileValueRef:
  immutable reference used by action.inputs / action.outputs

StreamTileValue:
  produced version visible on one stream and tile coordinate
```

Example:

```text
acc0 = accumulator_prepare_tile(m,n)
acc1 = compute_update_tile(k0, inputs=[A(m,k0), B(k0,n), acc0])
acc2 = compute_update_tile(k1, inputs=[A(m,k1), B(k1,n), acc1])
y1   = relu_tile(inputs=[acc_final])

stream_tile_visible[(S, Y, m,n)] = y1
store_tile.inputs = [y1]
```

Consumers must not recover inputs by looking up a mutable current map after the
fact.  The current map is for lowering-time binding; immutable action inputs are
for provenance.

### 3. Dependency model

Keep `depends_on` action-local, but do not mix action refs and value refs in the
same field.

Proposed MVP split:

```text
StreamTileAction
  inputs: tuple[TileValueRef, ...]
  outputs: tuple[TileValueRef, ...]
  depends_on: tuple[TileActionDependency, ...]
```

where:

```text
TileActionDependency
  action_id
  kind: data | order | visibility | loop_carried | resource | barrier
  via_value_id: optional TileValueRef
```

Derived dependency views can be built from:

```text
1. action.inputs[*].producer_action_id -> consumer action  # data edges
2. action.depends_on[*]                                  # explicit edges
```

This preserves the “no authoritative dependency table” principle while making
field meaning unambiguous.

### 4. Structured carried state

Accumulator recurrence must become structured carried state, not magic attrs.

GEMM example:

```text
acc0 = accumulator_prepare_tile(m,n)

acc1 = compute_update_tile(
  fiber=(m,n,k0),
  inputs=[A(m,k0), B(k0,n), acc0],
  outputs=[acc1],
  carried=[acc0 -> acc1],
)

acc2 = compute_update_tile(
  fiber=(m,n,k1),
  inputs=[A(m,k1), B(k1,n), acc1],
  outputs=[acc2],
  carried=[acc1 -> acc2],
)

c_final = accumulator_finalize_tile(inputs=[accK], outputs=[C(m,n)])
```

A structured carried field allows:

- expanded debug DAGs to stay readable,
- loop-carried recurrence to avoid becoming vendor graph edges,
- vendor repeat metadata to derive from schedule/carried state.

### 5. Tile access map schema

Tile access maps should be formal, not explanatory prose.

Minimal protocol:

```text
TileAccessMap
  op_kind
  output_fragment_space
  input_fragment_spaces
  fibers()
  inputs_for_fiber(fiber_id)
  outputs_for_fiber(fiber_id)
  carried_state_for_fiber(fiber_id)
  step_key(fiber_id)
```

Examples:

```text
ElementwiseTileAccessMap:
  fiber_id = output_tile_coord
  inputs   = [input_fragment(output_tile_coord)]
  outputs  = [output_fragment(output_tile_coord)]

MatmulTileAccessMap:
  fiber_id = (m_tile, n_tile, k_block)
  inputs   = [A_fragment(m_tile,k_block), B_fragment(k_block,n_tile), acc_prev]
  outputs  = [acc_next]
  final    = C_fragment(m_tile,n_tile)

StoreTileAccessMap:
  inputs  = [visible_fragment(tile_coord)]
  outputs = [storage_fragment(tile_coord)]
```

### 6. Named tile coordinates and fragment spaces

Do not rely on bare positional tuples for semantic tile coordinates.  A coordinate
must carry its fragment space and named axes.

```text
TileCoord
  fragment_space_id
  axes: dict[str, int]
```

Examples:

```text
A_fragment: axes={m: 0, k: 2}
B_fragment: axes={k: 2, n: 1}
C_fragment: axes={m: 0, n: 1}
```

The tuple `(0, 2)` means different things in A/B/C fragment spaces.  Named axes
prevent accidental coordinate aliasing.

### 7. Default fragment fanout semantics

MVP fanout model:

```text
one StreamTileValue may be consumed by many actions
```

Explicit fanout actions should be introduced only when hardware/resource lowering
requires distinct local copies, banked views, multicast tokens, or lifetime
splitting.

Validator rule:

```text
duplicate materialization of the same fragment is rejected unless the action is
marked allow_duplicate_materialization or the strategy explicitly requires it.
```

### 8. Route logical ownership vs physical execution

Route recv remains a logical receiver-side visibility event, while DFU execution
may be sender-side COPY/COPYT.  Preserve both meanings:

```text
StreamTileAction
  stream_id             # logical owner / where visibility belongs
  execution_stream_id   # physical stream/engine that emits instruction, optional
  endpoint_stream_id    # destination visibility stream, optional
```

For route receive:

```text
stream_id = receiver
execution_stream_id = sender or route engine
endpoint_stream_id = receiver
outputs = [receiver-visible fragment]
```

This avoids collapsing logical producer identity and physical execution location.

### 9. FiberScheduleGroup schema

A deterministic schedule is shared by a group of streams, but each stream has its
own coordinate projection.

```text
FiberScheduleGroup
  id
  streams
  schedule_axes
  per_stream_coord_map
  active_mask / empty_fiber_policy
  step_order
```

```text
FiberInstance
  schedule_id
  step_id
  stream_id
  local_coords
  active: bool
```

This is required for partial tiles, non-square meshes, ragged shards, and inactive
stream/step combinations.

### 10. Action list order

Action list order is stable generation/presentation order.  Execution legality is
controlled by explicit inputs, carried state, and `depends_on` entries.

If `FiberSchedule` step order is semantic, it must generate explicit order or
loop-carried dependencies in `StreamTilePlan`.  Do not let list order become a
hidden second dependency system.

### 11. Block projection lifecycle

Before block partition:

```text
StreamTilePlan is authoritative.
```

After block partition:

```text
TileBlockPlan is authoritative for executable grouping,
block roles,
micro-op lowering,
vendor template selection.
```

`TileBlockPlan` must carry:

```text
source_plan_id
source_plan_fingerprint
action_to_block
blocks
block_roles
loop_region_refs
route_group_refs
```

Any mutation to `StreamTilePlan` invalidates `TileBlockPlan`.

## Validator gates

Before real GEMM route/compute lowering, implement validators for these gates.

### Gate 1: value provenance

```text
for every action input:
  referenced value exists
  referenced value has producer_action_id
  producer action exists
  input value version is immutable
```

### Gate 2: visibility map coherence

```text
for every tile_visible[(stream, semantic_value, coord)] = value:
  value.stream_id == stream
  value.semantic_value_id == semantic_value
  value.tile_coord == coord
```

### Gate 3: dependency derivation

```text
derived data edge exists from each input producer to consumer
explicit depends_on edge kind is valid
no dangling action refs
no illegal cycles outside loop-carried regions
```

### Gate 4: tile access map coverage

For GEMM:

```text
every C(m,n) has exactly K compute_update fibers
each fiber consumes A(m,k) and B(k,n)
all required A/B fragments are materialized before use
final C visible only after last carried update/finalize
```

### Gate 5: fragment reuse

```text
same A(m,k) value_id may feed multiple n fibers
same B(k,n) value_id may feed multiple m fibers
duplicate materialization is rejected unless explicitly allowed
```

### Gate 6: schedule consistency

```text
every compute fiber references a schedule_id and step_id
step order matches loop_axis order
loop annotations derive from schedule
carried_refs connect consecutive steps for same output accumulator
```

### Gate 7: route tile matching

```text
route_recv_tile matches exactly one route_push/forward source unless fanin policy says otherwise
tile_coord / fragment_space match
logical source value matches
receiver-visible output is produced by recv visibility action
```

### Gate 8: block projection invalidation

```text
TileBlockPlan.source_plan_fingerprint == StreamTilePlan.fingerprint
each tile action belongs to zero or one executable block depending on op kind
block roles are schema-checked
```

## Revised implementation order

### Phase 1A: IR skeleton

```text
TileCoord / FragmentCoord
TileValueRef
StreamTileValue
StreamTileAction
StreamTilePlan
DependencyKind
TileActionDependency
```

### Phase 1B: validator + derived views

```text
validate_stream_tile_plan()
dependency_edges()
producer_consumers()
visible_fragments()
```

### Phase 1C: elementwise chain

```text
sram_read X
relu X -> Y
store Y
```

This validates value versioning, `tile_visible`, immutable inputs/outputs, and
store dependencies without GEMM route complexity.

### Phase 2: access maps

Implement:

```text
ElementwiseTileAccessMap
StoreTileAccessMap
FakeMatmulTileAccessMap
```

### Phase 3: route materialization

Implement:

```text
route_push_tile
route_recv_tile
execution_stream_id / endpoint_stream_id
route matching validator
```

### Phase 4: GEMM fiber schedule

Implement:

```text
MatmulTileAccessMap
GemmFiber
FiberScheduleGroup
accumulator carried state
compute_update actions
loop report derived from schedule
```

### Phase 5: block projection

Build debug `TileBlockPlan` only after action/value/fiber semantics are stable.
Do not connect to vendor ABI until block projection is validated.

## Addendum: coarse fiber vs micro-fiber dataflow

The current GEMM task-axis configuration makes each soft stream own exactly one
local output tile after `TaskShard(gemm_output_tiles)` filtering:

```text
stream-visible C envelope: 2 x 2 local output tiles
actual task-assigned work: 1 output tile per soft stream
K steps: 4
coarse GEMM fibers: 1 output tile x 4 K blocks
```

This means the first runnable fiber-planning MVP does not need an additional
inter-output-tile fiber mesh inside one stream.  A simple `1x1` output-fiber
mesh is enough for the current vendor-aligned task placement.

However, this must not be mistaken for "fiber planning is unnecessary".  There
is a more interesting second interpretation:

```text
coarse fiber:
  owns one C(m,n) output tile

micro-fiber/dataflow inside that coarse fiber:
  organize how A(m,k) and B(k,n) fragments are split, replicated, combined,
  and accumulated inside the stream-local tile computation
```

For example, one possible micro dataflow model for a single output tile is:

```text
A side: 1 x 4 tile fragments
B side: 4 x 1 tile fragments

for k in 0..3:
  consume A(m,k) and B(k,n)
  update local accumulator for C(m,n)
```

A future finer-grained implementation could choose one of several equivalent
micro strategies:

```text
1. replicate A-side fragments and shard/sequence B-side fragments,
2. replicate B-side fragments and shard/sequence A-side fragments,
3. split both sides and perform a stream-local reduction/allreduce-like combine,
4. keep the current sequential K-loop and treat it as the degenerate micro mesh.
```

The important distinction is:

```text
Task/stream placement decides which output tile a soft stream owns.
Fiber planning decides the stream-local dataflow used to realize that owned tile.
```

For the current phase, keep micro-fiber topology as a TODO and model it as the
degenerate sequential K schedule.  Do not delete the concept: it is the natural
place to describe future intra-stream tile splitting, local allreduce, fragment
reuse, and HMMAL/CAL scheduling variants.

## Addendum: explicit flat fiber op sequence

The current implementation should model stream-local fiber work explicitly, but
without introducing a separate micro-plan authority.  A fiber is a flat op
sequence.  Each op carries:

```text
fiber_id
stream_id
order_index        # stable generation/presentation order
op
inputs / outputs   # fragment refs
depends_on         # explicit op dependencies
attrs              # placement, subtask role, k_block, carried-state metadata
```

For a single assigned GEMM output tile, this flat sequence still answers the
four scheduling questions:

```text
Which fragments are prepared before the loop?
Which fragments are materialized inside each loop iteration?
Which fragments are finalized after the loop?
Which carried state connects loop iterations?
```

Current conservative sequence:

```text
#00 accumulator_prepare
  placement = pre_loop
  subtask   = accumulator_prepare
  output    = C_acc(m,n,k=-1)

#01 materialize A(m,k0)
#02 materialize B(k0,n)
#03 gemm_update C_acc(k=-1), A(k0), B(k0) -> C_acc(k0)

#04 materialize A(m,k1)
#05 materialize B(k1,n)
#06 gemm_update C_acc(k0), A(k1), B(k1) -> C_acc(k1)

...

#13 finalize_accumulator C_acc(k_last) -> C(m,n)
  placement = post_loop
  subtask   = finalize_store

#14 epilogue_relu C(m,n) -> Y(m,n)
#15 store_fragment Y(m,n)
```

This is the degenerate micro-topology, but it already gives the lowering stack a
clean contract:

```text
accumulator prepare is outside the loop,
A/B route or load obligations are loop-body obligations,
loop-carried accumulator state is explicit through op inputs/outputs/deps,
finalize / epilogue / store happen after the final K update.
```

Alternative future strategies should still produce the same kind of flat fiber
op sequence.  They may change where materialization ops appear, but should not
introduce a second source of truth:

```text
prefetch_a_side:
  emit A materialization ops before the K loop, B materialization ops inside it

prefetch_b_side:
  emit B materialization ops before the K loop, A materialization ops inside it

split_both_sides_with_stream_local_reduce:
  emit micro-split materialization/update ops plus explicit local combine deps
```

Thus, fiber planning is the formal bridge between tile access maps and the later
loop/block/instruction scheduler, but its IR remains flat.  It says where data
becomes visible, where it is consumed, and how recurrence is carried, before any
DFU-specific packing decisions are made.

## Addendum: semantic dependency edges in flat fibers

Fiber dependencies should keep semantic edge kinds even if later lowering can
prove those edges are structurally satisfied.  Do not erase dependencies just
because a vendor subtask, loop instance, or same-block order is expected to cover
them.

MVP dependency schema:

```text
FiberDependency
  source_op_id
  kind:
    fragment_visibility
    carried_state
    phase_order
    epilogue_order
  expected_satisfaction:
    route_or_local_materialization
    loop_instance_order
    subtask_order
    same_block_order
    unresolved
  via_fragment?
  reason
```

Examples:

```text
accumulator_prepare -> gemm_update(k0)
  kind = phase_order
  expected_satisfaction = subtask_order

materialize A(m,k) -> gemm_update(k)
  kind = fragment_visibility
  expected_satisfaction = route_or_local_materialization

gemm_update(k) -> gemm_update(k+1)
  kind = carried_state
  expected_satisfaction = loop_instance_order

gemm_update(k_last) -> finalize_accumulator
  kind = phase_order
  expected_satisfaction = subtask_order

finalize -> epilogue -> store
  kind = epilogue_order
  expected_satisfaction = same_block_order
```

Later passes should attach proof/report data such as:

```text
edge_id -> satisfied_by = subtask_order | loop_instance_order | route_pair | block_order
```

The fiber layer's job is to preserve the semantic obligation.  The lower layer's
job is to prove which obligations disappear into structural execution ordering
and which must remain as explicit scheduling edges.
