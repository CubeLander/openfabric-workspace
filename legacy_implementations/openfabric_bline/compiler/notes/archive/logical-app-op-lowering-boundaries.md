# LogicalApp stream-action lowering boundary notes

Date: 2026-06-18

## Context

While discussing whether `LogicalApp` lowering should become more OOP and move
op-specific behavior into op specs, we inspected `compiler/gpdpu_compiler/core/logical_plan.py`.
The important finding is that `LogicalApp` is not simply copying app-level ops to
every stream.  Its real job is to translate app-level logical ops into a flat set
of stream-local actions plus explicit cross-stream dependency edges.

The reason this layer exists is that app-level ops cannot always lower directly
to independent stream op sequences.  Tensor placements, soft mesh topology,
operand visibility, route behavior, collectives, and materialization boundaries
can require extra actions and ordering edges between streams.

The core IR should remain as flat as possible, with a single source of truth:

```text
LogicalApp
  streams[]
    actions[]
      depends_on[]
```

There should not be a separate authoritative `dependencies[]` table.  If a graph
view is useful for dumps, validation, or tile lowering, it should be derived
temporarily from the per-action `depends_on` fields.

Communication and collectives should not become a deeply nested graph language.
They should appear as normal stream actions, with dependencies stored on the
consumer/downstream action.


## Concrete GEMM AppPlan example

For the current explicit-SRAM GEMM+ReLU frontend program, the chip-level program
contains declaration ops plus the executable sequence.  `AppPlan` drops SRAM
declarations from the app body and leaves a single app with these flat app ops:

```text
app0:
  0. load_sram_tensor
     inputs:  [A_sram]
     outputs: [A_dtensor]
     attrs:   src_region=A

  1. load_sram_tensor
     inputs:  [B_sram]
     outputs: [B_dtensor]
     attrs:   src_region=B

  2. matmul
     inputs:  [A_dtensor, B_dtensor]
     outputs: [C_dtensor]
     attrs:   lowering_hint=dfu_summa_gemm

  3. relu
     inputs:  [C_dtensor]
     outputs: [Y_dtensor]

  4. store_sram_tensor
     inputs:  [Y_dtensor]
     outputs: [Y_sram]
     attrs:   dst_region=C/Y
```

The purpose of `LogicalApp` construction is to consume this flat app op sequence
from left to right and append action suffixes to every soft processor stream.
In process terms:

```text
for chip_op in app_ops:
  lower chip_op into zero or more appended actions per stream
  record any stream-visible values produced by those actions
  attach dependencies directly to downstream actions
```

For a single stream, the resulting visible causal sequence is roughly:

```text
materialize A as stream-visible value
materialize B as stream-visible value
matmul consumes visible A/B and produces local output tile
relu consumes local output tile
store materializes local output tile to SRAM
```

Across streams, `load` / value materialization is where the sequence stops being
a simple copy.  A/B shards are placed differently, so the lowerer for materializing
those values may append read, push, receive, or forward actions to different
streams before local compute consumes the visible values:

```text
stream S0:
  load A shard
  route_push / source_visibility for A

stream S1:
  route_recv / endpoint_visibility for A
  matmul depends_on=[A endpoint visibility, B endpoint visibility]
```

The exact route/fanout shape is target/topology policy.  The flat action model is
only saying where the truth should live: in stream actions and their dependencies.


## Left-to-right stream suffix lowering model

A better way to understand `LogicalApp` construction is as a left-to-right
consumer of app ops.  For every `ChipOp` in `app_ops`, the lowerer appends an
action suffix to each stream:

```text
for chip_op in app_ops:
  op_spec_or_lowerer.lower(chip_op, logical_app)
    -> append zero or more actions to stream0
    -> append zero or more actions to stream1
    -> ...
    -> record the produced stream-visible value for each stream
```

The important point is that a single app op does not need to become exactly one
action per stream.  The action suffix length can differ by stream.

For example, an SRAM/DTensor load with distributed visibility may lower as:

```text
stream S0:
  sram_read_A_shard
  route_push_A_to_S1

stream S1:
  route_recv_A_from_S0

stream S2:
  sram_read_A_shard
  route_push_A_to_S3

stream S3:
  route_recv_A_from_S2
  route_push_A_to_S4
```

All of these are part of lowering the same logical `load` / materialization op.
The result of the lowerer is not just a single action; it is a per-stream visible
value map:

```text
A_visible_on_stream[S0] = value produced by sram_read_A_shard
A_visible_on_stream[S1] = value produced by route_recv_A_from_S0
A_visible_on_stream[S2] = value produced by sram_read_A_shard
A_visible_on_stream[S3] = value produced by route_recv_A_from_S2
```

Then later compute ops consume the stream-visible values directly:

```text
matmul on stream S:
  inputs = [A_visible_on_stream[S], B_visible_on_stream[S]]
```

This means the earlier phrase "make A/B operands visible before matmul" should
not be treated as a separate app op or permanent phase.  It is the effect of
lowering value materialization under placement/topology constraints.

In this model:

- `load` lowering owns SRAM/DTensor -> stream-visible value materialization,
- `matmul` lowering consumes already-visible A/B values and produces C,
- `relu` lowering consumes visible C and produces visible Y,
- `store` lowering consumes visible Y and materializes it to SRAM, possibly with
  gather/route/write actions if needed.

This keeps the high-level app op sequence unchanged while allowing distributed
semantics to insert different action suffixes into each stream.

### Practical implementation note

The op spec / op lowerer is system-maintained code, not user-authored plugin code.
So it does not need an overly heavy abstraction barrier.  It may mutate
`LogicalApp` state directly if that keeps the implementation simple and readable.
If the mutation surface grows too large, `LogicalApp` can expose small helper
methods such as:

```text
append_action(stream, action)
ensure_visible_value(stream, tensor)
attach_depends_on(action, upstream_action)
```

But this should be a convenience interface, not a second IR layer.  The primary
truth should remain the flat stream action lists and each action's `depends_on`.

## Current responsibilities mixed in LogicalApp

`LogicalApp` currently mixes three related but separable responsibilities:

1. projecting chip-level ops into per-soft-processor logical actions and local values,
2. adding stream actions that implement visibility / route / collective behavior,
3. maintaining the app-local value ledger and action dependency annotations.

These should not be moved as one block into op specs.  In particular, `MatmulOpSpec`
should not become a mini compiler that builds route steps and dependency edges itself.

## Desired model: flat stream actions plus edges

Route construction is best understood as lowering a value-visibility behavior into
two-sided stream actions.  It is not a bidirectional dependency.  It is a pair or
chain of stream-local actions, with normal one-way dependencies:

```text
producer stream:
  route_push / source_visibility / route_hop_source

consumer stream:
  route_recv / endpoint_visibility / route_hop_dest

dependencies stored on actions:
  consumer_visibility_action.depends_on = [producer_action]
  consumer_compute_action.depends_on = [consumer_visibility_action]
```

This keeps the IR simple:

- every operation that happens on a stream is represented as an action in that stream,
- every ordering constraint is stored on the downstream action that needs it,
- route / collective / materialization are not special hidden side channels,
- dependency tables are derived views, not independent truth,
- downstream tile lowering can expand, merge, or specialize these stream actions.

This model is especially useful because later passes may fuse or replay route steps,
but the logical layer still has a readable causal story: one stream produces
visibility, another stream depends on it before computing.

## Current coupling points

### Boundary op projection

`_lower_load`, `_lower_store`, `_lower_app_materialize_store`, and
`_lower_app_materialize_load` are mostly simple projections:

- iterate over logical streams / soft processors,
- create or look up a `ProcessorLocalValue`,
- append a `ProcessorLogicalAction`,
- copy relevant SRAM/app-boundary metadata into action attrs.

These are the safest first candidates for extraction into explicit op lowerers.
They do not need to understand route fanout or collectives.

### Generic compute projection

`_lower_compute` currently does the generic per-stream action/value projection,
then triggers two additional behaviors:

- DFU3500 operand visibility route lowering via `dfu3500_operand_visibility_policy_for`,
- symbolic collective reduce lowering for `reduce_max`.

This means `_lower_compute` is not just an op projector; it is the current junction
where compute actions become inputs to visibility/collective action insertion.
A refactor should preserve that separation explicitly.

### Operand visibility route lowering

`_add_operand_visibility_routes` and `_add_operand_visibility_route_group` currently
build `LogicalRouteEdge` and `LogicalRouteStep` records.  Conceptually, these are
stream actions and dependencies needed to make operand shards visible to consumers.
They are target/placement/topology logic, not pure matmul semantics.

The current DFU3500 route policy already lives in
`compiler/gpdpu_compiler/core/dfu3500/operand_visibility.py`, whose module docstring
states the key boundary:

> ops describe data relationships; this module decides how the current DFU3500
> processor lowering makes operands visible.

This boundary should be kept.  `MatmulOpSpec` may describe data roles and the
selected lowering strategy, but it should not construct route actions, choose
route endpoints, or create dependency edges.

### Collective reduce lowering

`_add_logical_reduce` creates `LogicalReduceEdge` records and related dependencies.
Conceptually, this is also stream-action insertion:

```text
local scalar actions
  -> collective combine / visibility actions
  -> replicated result visible to consumers
```

This is distinct from ordinary route movement:

- routes move values,
- reduces combine values and define visibility semantics.

A future reduce op spec may describe reduce semantics, but the collective lowerer
should own participant expansion, stream action insertion, and dependency edges.

### Value/dependency bookkeeping

`_ensure_local_value`, dependency annotation, and ID generation are LogicalApp-level
bookkeeping.  They should not be replicated inside op specs or per-op lowerers.
If extraction continues, lowerers should call a narrow context API rather than
constructing IDs and mutating global dictionaries directly.

The current implementation still has explicit `LogicalDependency` records.  The
desired direction is to make action-local `depends_on` the authoritative form and
derive any dependency table only as a view.

## Recommended boundary

### Op specs / op lowerers may own

- op-level semantic contract,
- input/output role descriptors,
- supported placement/lowering hints,
- per-stream action projection for simple ops,
- whether an op needs visibility or collective action insertion.

### Op specs / op lowerers should not own

- route path/fanout algorithm,
- cross-stream endpoint selection,
- global dependency table mutation,
- app-local value table mutation details,
- DFU3500 byte or vendor ABI details,
- task/subtask/instance binary packing.

## Suggested incremental refactor plan

1. Extract boundary op lowerers first:
   - `load_sram_tensor`,
   - `store_sram_tensor`,
   - `app_materialize_store`,
   - `app_materialize_load`.

2. Extract generic compute action/value projection, but keep visibility/reduce
action insertion in `LogicalApp` or a nearby planner.

3. Move operand visibility lowering into a dedicated logical visibility module,
for example `logical_visibility.py`.  It should consume already-lowered actions,
local values, soft mesh information, and DFU3500 visibility policy, then emit
flat stream actions with action-local dependencies.

4. Move reduce collective lowering into a dedicated collective module, parallel
to the visibility module.

5. Only after these seams are stable, let op specs provide richer descriptors
that feed these lowerers.  Do not let op specs build downstream IR directly.

## Design principle

`LogicalApp` should be understood as the layer that turns app-level ops into a
flat stream-action plan with dependencies owned by actions:

```text
App-level logical ops
  + tensor placement
  + soft mesh topology
  + visibility / collective / materialization behavior
  -> stream-local actions
  -> action-local depends_on links, including cross-stream links
```

Matmul-specific policy can describe what kind of work and operand roles are
required, but route and dependency construction are system-level responsibilities.
Do not let `MatmulOpSpec` become a small compiler hidden inside the operator.

## New-line implementation strategy

We do not have to force this model into the current `logical_plan.py` implementation
immediately.  The old path is already entangled with `LogicalRouteEdge`,
`LogicalReduceEdge`, and tile lowering compatibility.  Refactoring it in place
would risk spending most of the effort preserving old scaffolding rather than
building the cleaner model.

Instead, create a new experimental line under:

```text
compiler/gpdpu_compiler/core/stream_compiler/
```

This new line should model the desired IR directly:

```text
App ops
  -> left-to-right op lowering
  -> flat stream action lists
  -> action-local depends_on links
  -> derived graph/route views only when needed
```

The new implementation does not need to be wired into `env.generate()` at first.
It can produce dumps/tests for the same GEMM app ops and prove the model in
parallel.  At a later point, downstream code can "jump" from the old pipeline to
this new stream plan at a natural seam:

- first as a debug artifact next to `LogicalPlan`,
- then as an alternate input to tile lowering,
- finally as the primary logical stream IR once compatibility is proven.

This is intentionally more aggressive than incremental in-place refactoring.
The goal is to make the right architecture exist in code, not to polish every
old scaffolding seam before moving.

## Follow-up insight: StreamTilePlan preserves topology

The stream-to-tile transition should preserve the stream topology decided by
`StreamPlan`.  It is better understood as slicing each stream's river of actions
into tile fragments, not as replanning route/collective topology.

The genuinely hard problem is not topology but micro-distribution: tile lowering
must choose compatible tile slices for each action's input and output values.
For elementwise ops this can be a simple zip of matching tile coordinates.  GEMM
is different because output tiles reuse input fragments:

```text
C(m,n) = sum_k A(m,k) @ B(k,n)
```

So tile lowering needs operator-provided tile access maps.  `matmul` should not
own inter-stream routes, but it does need to describe its local tile access
pattern:

```text
output C(m,n) consumes A(m,k) and B(k,n) for each k block
```

This sharpens the split:

```text
StreamPlan: topology and whole-value visibility.
StreamTilePlan: topology-preserving slicing plus operator tile access maps.
```

## Follow-up insight: tile fibers

The tile layer can be viewed as a second, processor-local DTensor partitioning
pass.  Macro placement maps tensors to stream-visible shards.  Tile lowering maps
those shards to tile-visible fragments and compute fibers.

For GEMM, a fiber is naturally:

```text
GemmFiber(m_tile, n_tile, k_block)
```

with inputs:

```text
A_fragment(m_tile, k_block)
B_fragment(k_block, n_tile)
```

and contribution to:

```text
C_fragment(m_tile, n_tile)
```

The interesting part is fragment reuse:

```text
A(m,k) feeds many C(m,*,k) fibers
B(k,n) feeds many C(*,n,k) fibers
```

So tile-level input materialization behaves like a local fragment fanout or
collective entrance.  This means the new stream/tile compiler should focus on:

```text
TileFragment
TileFiber
FragmentProducer
FragmentFanout
```

while still keeping the primary IR flat:

```text
streams[].tile_actions[].depends_on[]
```

This gives us a concise principle:

```text
StreamPlan solves stream visibility.
StreamTilePlan solves tile fiber micro-distribution and fragment reuse.
```

## Follow-up insight: deterministic fiber schedule

Once stream-local tile work is modeled as fibers, the tile layer can regain a
micro-SPMD structure.  A group of streams can execute the same deterministic
fiber schedule shape with different coordinates:

```text
for fiber_step in FiberSchedule:
  materialize step fragments
  run stream-local fiber instance
  update local carried/output state
```

For GEMM, this means every stream follows the same ordered K-step pattern.  The
shared fragment entrances become obvious at each step:

```text
step k0 requires A(*,k0), B(k0,*)
step k1 requires A(*,k1), B(k1,*)
```

So fragment reuse and fanout are generated by the schedule instead of discovered
later from a tangled graph.  This gives the tile layer the determinism we want:

```text
FiberSchedule -> fragment materialization -> fiber compute -> loop metadata
```

In short:

```text
StreamPlan handles topology.
FiberSchedule gives tile-level work a deterministic micro-SPMD order.
StreamTilePlan materializes that order into flat tile actions.
```
