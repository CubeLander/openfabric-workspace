# Task × Processor as Soft Processor Model

## Status

Exploration note.  This is a candidate mental model for future ProcessorLogical /
TaskPlan refactoring.

## Core Idea

A vendor task can be viewed as a time-sliced execution context over the physical
processor mesh.  The pair `(task, processor)` behaves like a soft processor:

```text
soft_processor = (task_id, physical_processor_id)
```

Within one task, physical processors may cooperate through app-local routes,
collectives, and explicit visibility programs.  Across different tasks, those
soft processors are independent and should not depend on one another's PE-local
state.

```text
same task:
  (task0, PE00) <-> (task0, PE01) may cooperate
  via route / collective / visibility IR

different tasks:
  (task0, PE00) -/-> (task1, PE00) cannot share PE-local value
  task1 must obtain inputs from storage or its own routes
```

This is similar to viewing hardware processors as running multiple independent
logical contexts, like a small time-sharing system.  Task partitioning creates
soft processor groups, and each group has its own local execution world.

## Why This Helps

Both processor placement and task partitioning impose matrix/shard partitions:

```text
processor placement:
  partitions tensors across physical processors inside one cooperative task

task partitioning:
  partitions independent work across task contexts that cannot cooperate
```

So matrix partitioning should eventually be reasoned over a combined axis:

```text
(task_id, processor_coordinate)
```

rather than only over `processor_coordinate`.

For GEMM, an output tile group could be assigned to a task, and then the PE mesh
inside that task cooperates to compute that group:

```text
task0:
  PE mesh computes output shard group C0

task1:
  same physical PE mesh, separate soft context, computes output shard group C1
```

The tasks may read overlapping SRAM inputs, but each task pays for its own load /
visibility setup.

## Compiler Implications

A future model might split lowering into:

```text
AppPlan
  -> TaskPartitionPlan       # chooses independent shard groups
  -> SoftProcessorProgram    # indexed by (task, processor)
  -> Tile/DFU lowering
```

In that model, `ProcessorLogicalAppProgram` would no longer only instantiate ops
across physical processors.  It would instantiate them across soft processors:

```text
for task in task_partition:
  for processor in physical_mesh:
    lower app-local op into (task, processor) stream
```

Then route/collective legality is scoped to a task:

```text
route scope = all soft processors with same task_id and selected processor group
```

## Current Compiler Gap

Today `ProcessorLogicalAppProgram` mostly partitions from input DTensor placement
and then adds routes for operand visibility.  Task partitioning is still mostly a
later GEMM/task-plan concern.  This creates tension because output shard/task
partitioning is also a matrix partitioning force.

The soft processor model suggests task planning should move earlier or become an
explicit axis in processor logical lowering.

## Constraints

1. A soft processor cannot consume another task's PE-local value.
2. Inter-task communication must go through explicit storage/materialization.
3. Intra-task communication may use routes/collectives if represented in IR.
4. Input SRAM sharing across tasks is allowed, but duplicated load/route cost is
   real and must be visible to the planner.
5. Runtime image packing may place multiple task contexts into one image, but it
   must not erase the independence proof.

## Open Questions

- Should `TaskPartitionPlan` sit before `ProcessorLogicalAppProgram`?
- Should DTensor placement include a task axis, or should task partitioning wrap
  processor placement externally?
- How should `(task, processor)` IDs map to vendor task rows and PE instruction
  memories?
- Can current GEMM `wave/task` planning be reformulated as a soft-processor
  partition over output tile groups?
