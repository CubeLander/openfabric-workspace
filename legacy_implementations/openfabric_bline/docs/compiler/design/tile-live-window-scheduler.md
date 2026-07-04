# Tile Live-Window Scheduler

This note records a general scheduling principle for the GPDPU compiler backend.
It is broader than GEMM and should guide how we turn PE-local tile DAGs into
task/subtask stages.

## One Sentence

Represent every PE's work as a tile dependency timeline, then choose an order
that minimizes the cross-PE live window of shared data tiles under SPM, operand,
communication, and barrier constraints.

## Motivation

A hard-coded GEMM schedule can be simple:

```text
for each PE:
  traverse local C tiles by row
  then by column
  stream K blocks in a fixed order
```

But this throws away a useful optimization space. Many operators have data
blocks reused across multiple PEs or multiple local computations:

```text
GEMM:
  A tiles reused along a mesh row
  B tiles reused along a mesh column

softmax/layernorm:
  partial max/sum tiles reused by reduce and normalize stages

attention:
  K/V blocks reused by multiple Q blocks
```

The scheduler should therefore reason about tile reuse directly instead of
starting from a fixed loop nest.

## Model

After distributed tensor lowering, each PE has a tile-level DAG:

```text
PE p:
  action a0 depends on tile X, tile Y
  action a1 depends on tile X, tile Z
  action a2 produces tile R
  ...
```

The same physical/logical tile may appear in multiple PE timelines:

```text
tile A_i_k used by PE(i,0), PE(i,1), PE(i,2), PE(i,3)
tile B_k_j used by PE(0,j), PE(1,j), PE(2,j), PE(3,j)
```

For each tile `t`, once a candidate schedule assigns an execution time to every
action that consumes `t`, the tile has a live window:

```text
first_use(t) = earliest scheduled consumer of t
last_use(t)  = latest scheduled consumer of t
window(t)    = last_use(t) - first_use(t)
```

A small live window means the tile can be loaded, copied, used by all dependent
PEs, and evicted quickly. A large live window means the tile occupies scarce
storage for longer or must be reloaded later.

## Objective

The first scheduler objective should approximate:

```text
minimize sum_t cost(t) * window(t)
```

where `cost(t)` should include:

```text
tile bytes
load cost from SPM/CBUF/DRAM
COPY/COPYT distance over the mesh
number of PE consumers
reload penalty if the tile is evicted before last use
```

This is similar in spirit to register allocation live ranges, cache-aware loop
scheduling, and communication-aware DAG scheduling. The difference is that our
"register file" spans PE operand RAM, SPM/CBUF staging, and mesh communication
windows.

## Constraints

The scheduler cannot minimize live windows in isolation. It must also satisfy:

```text
data dependencies:
  a tile cannot be consumed before it is produced or loaded.

PE local order:
  dependent actions on the same PE must preserve producer-before-consumer order.

collective alignment:
  cross-PE COPY/reduce/broadcast bundles must be scheduled atomically across
  all participating PEs.

resource limits:
  operand slots, instruction slots, accumulator slots, SPM/CBUF capacity, and
  instance table limits.

DFU execution model:
  task/subtask boundaries are natural BSP-style barriers.
```

If a candidate bundle does not fit on every required PE, the scheduler should
not partially schedule it. It should close the current stage and try again in
the next stage.

## Scheduling Sketch

A practical first implementation can use a greedy list scheduler.

Build tile DAGs:

```text
logical DTensor op trace
-> PE-local logical actions
-> tile actions
-> explicit tile dependencies
```

Maintain a frontier:

```text
ready bundles:
  tile actions whose dependencies are satisfied

live tiles:
  tiles already loaded/produced and not yet consumed by all scheduled users

stage resources:
  current operand/SPM/instruction usage estimate
```

At each step, score candidate bundles:

```text
score(bundle) =
  + closes existing live windows
  + reuses already-live tiles
  + serves many PE consumers together
  - opens large new live windows
  - requires expensive communication
  - consumes scarce accumulator/operand resources
```

Schedule the best fitting bundle. If no useful bundle fits, finish the current
stage and start a new task/subtask stage.

## Greedy Tile-First Variant

Another useful heuristic is tile-first rather than op-first scheduling.

Instead of first choosing a fixed loop nest or a concrete compute action, the
scheduler can start from the most reused unscheduled tile:

```text
1. find the tile with the highest remaining consumer count.
2. make that tile available.
3. activate all ready computations that depend on it.
4. schedule the activated computations if PE/resource constraints allow.
5. repeat with the next best tile or the next shallowest PE timeline.
```

For GEMM this naturally tends to discover SUMMA-like behavior:

```text
A_i_k is useful to all PEs in mesh row i.
B_k_j is useful to all PEs in mesh column j.
```

If the scheduler keeps choosing high-fanout tiles, it will prefer bringing in a
shared A or B fragment and immediately serving the PE consumers that need it.
This is close to minimizing the tile's live window:

```text
load/copy shared tile
run all ready consumers
evict shared tile
```

The scheduler also needs a fairness rule across PE timelines. Two possible
rules:

```text
shallowest-PE-first:
  if some PEs have much shorter timelines than others, prefer bundles that give
  work to the shallow PEs.

layered scheduling:
  in each scheduling round, give each PE at most one compute layer, then move to
  the next round.
```

The layered version may make the resulting schedule easier to align with
BSP-style task/subtask stages, but it can lose some local reuse opportunities.

## Hardware Loop Caveat

An unconstrained greedy schedule may produce an irregular sequence:

```text
copy tile A
compute C0
compute C7
copy tile B
compute C2
...
```

That kind of sequence may be valid as a tile DAG schedule, but it may not map
well to DFU hardware loops:

```text
task -> subtask -> instance base table
```

The vendor examples get compact hardware-loop behavior because the inner
subtask program repeats with different instance base addresses. A highly
irregular greedy schedule could reduce or destroy that regularity.

For that reason, the compiler should separate two layers:

```text
exploration scheduler:
  searches for good tile reuse and live-window behavior.

regularization/pass lowering:
  groups the schedule back into repeated templates, instance tables, and
  task/subtask stages when possible.
```

The first production GEMM backend can still use a pragmatic regular schedule
such as SUMMA-style K-block streaming. The tile-first greedy scheduler should be
kept as a design direction and future optimization path, not as a blocker for
the first implementation.

## GEMM Behavior

For output-sharded GEMM:

```text
A: [Shard(0), Replicate()]
B: [Replicate(), Shard(1)]
C: [Shard(0), Shard(1)]
```

the scheduler should discover the SUMMA-like reuse pattern:

```text
A_i_k has consumers across mesh row i
B_k_j has consumers across mesh column j
```

Therefore, a good stage usually looks like:

```text
row-broadcast A_i_k
column-broadcast B_k_j
run all local C updates that consume those tiles
evict A_i_k and B_k_j quickly
```

If accumulator capacity is limited, the scheduler may choose a smaller C-tile
bundle. If A/B movement dominates, it may choose a K-stage-first order so the
same A/B tiles update several local C tiles before eviction.

This means the fixed row/column traversal becomes only one possible result of
the scheduler, not a hard-coded policy.

## Why This Helps Beyond GEMM

This formulation can also describe non-GEMM operators.

For reduce-style operators:

```text
partial tiles create cross-PE reduce dependencies.
The scheduler can keep partials live only across the reduce window.
```

For fusion:

```text
producer tile -> fused consumer tile edges stay PE-local when possible.
The scheduler can avoid materializing intermediate tiles to SPM if the live
window and resource model allow direct operand reuse.
```

For attention:

```text
Q block timelines depend on streaming K/V blocks.
The scheduler can choose K/V block windows that serve multiple Q blocks while
respecting online softmax state.
```

## Open Problems

This scheduling problem is likely hard if solved globally. The compiler should
start with greedy heuristics and make every decision inspectable.

Important unknowns:

```text
accurate COPY/COPYT cost model
operand and accumulator pressure model for HMMAL/HADD/etc.
whether subtask boundaries are the best live-window cut points
how much communication/computation overlap the hardware actually supports
```

The first useful implementation does not need a perfect optimizer. It only needs
to emit a tile schedule with explicit dependencies, live-window estimates, and
resource estimates so we can compare fixed schedules against scheduler-chosen
schedules.
