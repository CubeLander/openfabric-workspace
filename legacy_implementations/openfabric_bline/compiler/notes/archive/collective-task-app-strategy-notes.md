# Collective / Task / App Strategy Notes

## Status

Exploration note.  This records an unresolved design direction, not a finalized
compiler policy.

## Observation

The current conservative compiler policy treats collective operators such as
`reduce_max` as strong app-boundary candidates:

```text
app0: produce local values -> collective -> materialize result
app1: reload inputs/result -> continue
```

This is safe because DFU task rows are independent work slots and should not be
misused as global synchronization phases.  However, this is not the only possible
execution strategy.

## Important Distinction

A vendor task is app-local, lock-free parallel work.  The hardware does not say
that all tasks must run the same logical program, nor does it say a collective
must necessarily force an OpenFabric app boundary.

An OpenFabric app boundary is about PE-local state lifetime and explicit storage
handoff.  A collective is about communication / visibility.  These concepts are
related, but not identical.

## Alternative Strategy: SPMD Collective Inside One App

For an allreduce-like operator, it may be possible to keep computation inside one
semantic app if the backend provides or synthesizes an app-local communication
program:

```text
same app:
  every PE computes local contribution
  PEs communicate/reduce
  every PE obtains or reconstructs the replicated result
  every PE continues with post-reduce computation
```

This could be implemented as:

```text
all-PE -> PE00 -> broadcast
pairwise tree -> broadcast
replicated redundant computation where every PE computes the needed scalar
other SPMD collective schemes
```

In this model, `collective` is not automatically an app cut.  It becomes a
processor/tile-level distributed execution strategy inside one app.

## Alternative Strategy: Task-Diverse Programs

Since vendor tasks are independent work slots, a future backend could also
experiment with assigning different subprograms to different tasks, provided the
program proves that required ordering/visibility/storage semantics are explicit.
This must not be confused with treating tasks as semantic app phases.

## Current Policy

For now, OpenFabric keeps the conservative policy:

```text
collective op -> app boundary candidate
cross-app values -> explicit materialize/load ops
tile-local intermediates -> recompute unless a policy materializes them
```

This policy is simple, easy to verify, and prevents accidental PE-local state
leakage while the DFU binary/runtime path is still being stabilized.

## Future Policy Surface

The app splitter should eventually be configurable by an execution strategy, for
example:

```text
collective_strategy:
  materialize_between_apps
  same_app_allreduce_broadcast
  same_app_redundant_spmd
  task_diverse_collective_prototype
```

The same high-level operator may then be compiled with multiple legal strategies
and selected by performance/resource experiments.

## Design Constraint

Even if a collective stays inside one app, the compiler must still make its
communication semantics explicit in intermediate IR:

```text
LogicalReduceEdge / collective IR
  -> tile communication program
  -> dependencies proving result visibility before consumers
```

Do not hide collective semantics in task naming, app numbering, or vendor
`appN.conf` file names.
