# Fiber-first StreamTilePlan design anchor

Date: 2026-06-18
Status: active design anchor
Scope: `core/stream_compiler` new line; not wired into production DFU lowering yet

## Why this note exists

This note records the current agreed reading of the fiber RFC direction.  It is
meant to prevent future refactor work from reading the stream/tile plan as a
bare "split stream actions into tile actions" task.

The core design point is:

```text
StreamPlan decides inter-stream topology and whole-value visibility.
StreamTilePlan performs a second, tile-level DTensor partitioning inside each
stream-visible shard.
```

Flat tile actions and action-local dependencies are still useful, but they are
the materialized output form.  They are not the conceptual center of the tile
lowering algorithm.

## Correct mental model

The compiler has two partitioning levels:

```text
Chip-level DTensor
  -> placement / stream visibility / route policy
  -> stream-visible shard

stream-visible shard
  -> tile-level DTensor partitioning
  -> tile-visible fragments
  -> tile fibers
  -> deterministic fiber schedule
  -> materialized tile actions / values / dependencies
```

So the stream-to-tile transition should be understood as:

```text
for each stream-local shard:
  define fragment spaces
  define named tile coordinates
  define op-specific fiber access maps
  define fragment reuse / fanout
  define carried state
  define deterministic schedule groups
  materialize those decisions into StreamTilePlan actions
```

It should not be understood as:

```text
for each stream action:
  blindly emit one or more tile actions
```

That blind action-splitting model works for simple elementwise chains, but it is
not enough for GEMM or other ops whose input/output tile relation is not a zip.

## StreamPlan boundary

`StreamPlan` owns these decisions:

```text
inter-stream topology
whole-value visibility
route / collective / materialization at stream granularity
action-local cross-stream dependencies
```

For example, a stream plan decides that a whole A shard becomes visible along a
row route, and a whole B shard becomes visible along a column route.  Tile
lowering must preserve that topology.  It must not rediscover or replan the
inter-stream route shape.

## Fiber-first tile boundary

`StreamTilePlan` owns the tile-level micro-distribution inside the
stream-visible shards:

```text
FragmentSpace
TileCoord with named axes
TileFragment / TileValueRef
TileFiber
TileAccessMap
FiberScheduleGroup
FiberInstance
carried state
fragment materialization and reuse
```

The flat tile action list is a materialized semantic IR generated from those
objects.  It is a reviewable and lowerable result, not the source of the
distribution logic.

## GEMM example

For GEMM, after macro placement and stream visibility:

```text
A shard -> A_fragment(m, k)
B shard -> B_fragment(k, n)
C shard -> C_fragment(m, n)
```

The fundamental compute lane is a fiber:

```text
GemmFiber(m_tile, n_tile, k_block):
  consumes A_fragment(m_tile, k_block)
  consumes B_fragment(k_block, n_tile)
  consumes acc_fragment(m_tile, n_tile, k_block - 1)
  produces acc_fragment(m_tile, n_tile, k_block)
```

This is the important part: input fragments are shared entrances, not private
reads owned by each output tile.

```text
A(m, k) feeds C(m, n0, k), C(m, n1, k), ...
B(k, n) feeds C(m0, n, k), C(m1, n, k), ...
```

Therefore a correct tile layer must model fragment reuse / fanout before it
materializes compute actions.  If lowering starts from per-output-tile action
expansion, it will naturally duplicate input materialization and obscure the
reuse pattern.

## FiberSchedule as micro-SPMD structure

`FiberSchedule` restores a deterministic micro-SPMD structure at tile granularity.
For GEMM, streams in a schedule group share the same ordered K-step shape while
using stream-local coordinates:

```text
for k_block in K:
  materialize A(*, k_block), B(k_block, *)
  run active GemmFiber(m, n, k_block) instances
  carry accumulator state to the next step
```

The schedule is the source of loop metadata:

```text
loop_axis
repeat_count
step_id
fiber_instance membership
carried_refs
```

Those properties should not be recovered later by archaeology over a large
expanded action graph.

## Materialized StreamTilePlan

After fiber/access-map/schedule decisions are made, the compiler may materialize:

```text
StreamTileAction
StreamTileValue
TileValueRef
TileActionDependency
tile_visible current binding table
derived dependency edges
```

The materialized plan should still follow these invariants:

```text
action.inputs / action.outputs are immutable value refs
tile_visible is only a current binding table
depends_on contains action dependencies, not value refs
data edges are derived from input value producers
explicit dependencies carry kinds such as order, visibility, loop_carried, resource
action list order is stable presentation order, not hidden execution semantics
```

This preserves the flat-action benefits without making the flat action table the
primary design vocabulary.

## Route recv ownership

Route tile materialization must preserve both logical and physical meanings:

```text
route_recv_tile:
  logical owner = receiver stream
  physical executor = sender stream / route engine, if DFU sender-push requires it
  output = receiver-visible fragment
```

In other words, a receiver-visible fragment is logically produced by the recv
visibility action even if the executable DFU instruction is emitted on the
sender side.

## Block projection lifecycle

Block and micro-op projection should happen after fiber-first materialization:

```text
Fiber/access-map/schedule model
  -> materialized StreamTilePlan
  -> TileBlockPlan / microblock projection
  -> micro-op / vendor template lowering
```

Before block partition, `StreamTilePlan` is the semantic authority.  After block
partition, `TileBlockPlan` becomes the authority for executable grouping, block
roles, micro-op lowering, and vendor template selection.  Any mutation to the
source `StreamTilePlan` invalidates the block projection.

## Implementation guidance

When implementing the new `core/stream_compiler` tile line, start with the
fiber-first schema, not a naked action table:

```text
FragmentSpace
TileCoord
TileFragmentRef / TileValueRef
TileFiber
TileAccessMap
FiberScheduleGroup
FiberInstance
CarriedStateRef
FragmentMaterializationPlan
```

Then add materialized `StreamTileAction` / `StreamTileValue` as the output of
the fiber schedule lowerer.

Minimal validation should include:

```text
every fiber is covered by its access map
every required fragment is materialized before use
shared fragments may feed multiple fibers without duplicate materialization
carried state connects consecutive schedule steps
materialized action inputs point to immutable value versions
derived dependency edges match input producers and explicit dependencies
```

## Summary

The short version:

```text
Do not build StreamTilePlan as "old ProcessorTileProgram, but flatter."

Build it as tile-level DTensor partitioning of stream-local shards:
  fragment spaces
  fiber access relations
  fragment reuse
  deterministic schedule
  carried state
  then materialized actions.
```

