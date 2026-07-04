# Task Partitioning as Independent Shard Groups

## Status

Exploration note.  This records a likely core principle for future task planner
work, but it is not yet wired into the compiler policy.

## Core Idea

Vendor tasks are independent app-local work slots.  Therefore task partitioning
should be based on groups of processor shards that do not require data
dependencies between tasks.

```text
Allowed across tasks:
  shared reads from SRAM/input storage
  duplicate communication/loading cost per task
  independent writes to disjoint output regions

Not allowed across tasks:
  task A produces PE-local/tile-local value consumed by task B
  task A must finish before task B can compute inside the same app
  hidden synchronization or lock-step cooperation between task rows
```

This reframes task planning as a partitioning problem over processor-local shard
work, not as a sequencing mechanism.

## Matrix Multiplication Intuition

For GEMM, task boundaries naturally follow output tile boundaries:

```text
C tile / output shard group
  determines which A shards are needed
  determines which B shards are needed
  determines which processors participate
  can run independently from other output tile groups
```

In that sense, output matrix partitioning is the real source of both:

```text
DTensor layout pressure
task partitioning pressure
```

The task planner should answer:

```text
Which output shard groups are independent enough to assign to different tasks?
What input shards must each task read or communicate for itself?
Which output storage regions are disjoint?
```

## Shared SRAM Inputs

Tasks may read the same SRAM input tensors, but each task must establish its own
visibility/communication for the shards it needs.  This can duplicate route/load
work, but it preserves the no-cross-task-dependency invariant.

## Relationship to DTensor Layout

This idea may conflict with the current DTensor-first design, where placement is
chosen before task partitioning.  A future planner may need to make output layout
and task partitioning co-design decisions:

```text
choose output layout / tile partition
  -> derive independent output shard groups
  -> derive task plan
  -> derive required input shard visibility per task
```

For now, keep the existing DTensor model stable.  Treat this as a future design
axis for a more principled task planner.

## Compiler Constraint

Task IDs should not be assigned from incidental values such as `wave_id` unless a
planner has already proven that the corresponding shard groups are independent.

A valid task partition should prove:

```text
1. task output regions are disjoint or safely reducible by explicit storage ops
2. each task can obtain all required inputs from storage or app-local routes
3. no task consumes another task's PE-local value
4. any duplicated input communication is explicit and accounted for
```

## Open Questions

- Should output layout be selected before task planning, or should task planning
  participate in layout selection?
- Can task planning be expressed as partitioning a tile dependency DAG into
  independent connected components?
- How should the planner estimate duplicated route/load cost when tasks share
  SRAM inputs?
- Which operators besides GEMM have a clean output-shard task partition?
