# RFC: Restricted Soft Task Axis for DFU Task Partitioning

## Status

Proposed for review.

## Summary

Task partitioning is placement over a **restricted soft task axis**: the axis
partitions independent work and context ownership, but does **not** imply
implicit data visibility, coherence, synchronization, or collectives.

This RFC proposes making that axis explicit in a DTensor-inspired soft mesh:

```text
SoftDeviceMesh = [task | pe_row, pe_col]
```

The vertical bar is intentional: `task` is not the same kind of axis as physical
PE topology.  It is a restricted context / work-ownership axis.  A soft processor
is:

```text
soft_processor = (task_id, physical_pe_id)
```

The physical PE mesh may be reused by multiple task contexts, but PE-local state
is scoped by task.  Therefore:

```text
PE-local value scope = (app_id, task_id, physical_pe_id)
```

A PE-local value produced in `(app0, task0, PE00)` may be consumed in
`(app0, task0, PE00)`.  It may not be consumed in `(app0, task1, PE00)` unless it
is materialized or moved through an explicit legal mechanism.  Same physical PE
is not same local state.

The goal is to make task partitioning a first-class layout decision rather than
a late vendor-row assignment accident.

## Background

OpenFabric currently has a DTensor-like frontend:

```text
LogicalDTensor
  shape
  dtype
  placements = [Shard(...), Replicate(), Partial(...)]
  logical fabric = 2D PE mesh
```

This has been useful for processor-level lowering:

```text
A[M,K]: placements = [Shard(0), Replicate()]
B[K,N]: placements = [Replicate(), Shard(1)]
C[M,N]: placements = [Shard(0), Shard(1)]
```

However, DFU3500 also has vendor task rows.  A task is not a synchronization
phase and not a semantic app boundary.  A task is an app-local lock-free work
slot.  Current GEMM task planning has historically been driven by output tile
waves and then lowered into vendor task rows, but the conceptual source of truth
has been blurry.

The key observation is:

```text
Task partitioning is also a shard/work partitioning problem.
```

A task partitions independent units of work.  For GEMM, those independent units
are naturally output tile groups.  Therefore task planning should be expressed as
layout over a restricted task axis, not as an incidental mapping from `wave_id` to
vendor task row.

## Inspiration from PyTorch DTensor

PyTorch DTensor describes distributed tensors using:

```text
DeviceMesh + Placement
```

A DeviceMesh can be N-dimensional.  Placement describes how a tensor maps to each
mesh dimension:

```text
Shard(dim)     # split tensor dimension over mesh dimension
Replicate()    # each rank gets the same value
Partial(op)    # pending reduction across mesh dimension
```

This RFC borrows the language, not the implementation.

For DFU, we can view the target as a soft mesh:

```text
SoftDeviceMesh axes:
  task   : independent task contexts / work ownership groups
  pe_row : physical PE row axis
  pe_col : physical PE column axis
```

Then task partitioning becomes placement over the `task` axis, with stricter
semantics than ordinary physical communication axes.

## Proposed Model

### Task axis is a restricted mesh axis

The task axis participates in layout and ownership decisions, but it is not a
normal communication mesh axis.

A task-axis rank names an independent app-local work context.  It does not imply:

```text
1. implicit visibility of PE-local values across task_id,
2. implicit coherence between task contexts on the same physical PE,
3. implicit synchronization or collective availability across task_id,
4. free reuse of routed or loaded input values.
```

By default, route and collective scopes are task-local:

```text
route_scope = (app_id, task_id, selected_physical_pe_group)
```

Any cross-task visibility, merge, or reduction must be represented by an explicit
strategy and verified before lowering to runnable vendor images.

### Soft processors

```text
soft_processor = (task_id, pe_row, pe_col)
```

Within one task:

```text
(task0, PE00) <-> (task0, PE01)
```

may cooperate via explicit routes/collectives.

Across tasks:

```text
(task0, PE00) -/-> (task1, PE00)
```

must not share PE-local values.  Cross-task data movement must use explicit
storage/materialization or a future proven runtime mechanism.

### Task-axis placement descriptors

Near term, task-axis placement should use separate descriptors instead of plain
DTensor `Shard/Replicate/Partial`, because task semantics are restricted:

```text
TaskShard(work_domain_partition):
  preferred for independent output work

TaskReplicate(input_requirement):
  every task independently requires equivalent input visibility
  this is not zero-cost sharing

TaskPartial(reduce_op):
  task results require cross-task merge/reduction
  unresolved TaskPartial is not a runnable placement
```

`TaskReplicate` is a requirement, not a free implementation.  A shared SRAM
address does not mean a task can see the value for free.  Each task must establish
its own input visibility and pay its own load / route / buffer cost, unless a
backend strategy proves a shared reuse mechanism.

`TaskPartial` is a danger state.  It must become one of:

```text
ResolvedTaskPartial(strategy = SameAppCollective)
ResolvedTaskPartial(strategy = MaterializeThroughSRAM)
ResolvedTaskPartial(strategy = RepartitionWork)
Reject
```

before runnable DFU lowering.

Future work may unify task-axis and PE-axis placement under a generalized model:

```text
Placement(axis, policy, axis_capabilities)
```

but Phase 1 should keep `TaskShard`, `TaskReplicate`, and `TaskPartial` separate
so the isolation semantics stay visible.

## Work Domain, Not Tensor Dimension

Task partitioning should shard an operator work domain, not necessarily a raw
tensor dimension.

For GEMM:

```text
C[M,N] = A[M,K] @ B[K,N]
```

The logical tensor remains:

```text
C[M,N]
```

The GEMM work domain is:

```text
CTileDomain[Mt, Nt]
output_tile_group = partition(CTileDomain)
```

A task policy may then choose:

```text
Task axis:
  TaskShard(output_tile_group)

Physical PE axes inside each task:
  pe_row shards M work inside the group
  pe_col shards N work inside the group
```

This avoids treating `output_tile_group` as a fake tensor dimension.  The task
axis shards work ownership; PE axes shard processor cooperation within that
owned work.

## GEMM Example

A natural soft-mesh view is:

```text
SoftDeviceMesh = [task | pe_row, pe_col]
```

A policy may choose:

```text
C work placement:
  [TaskShard(output_tile_group), Shard(M), Shard(N)]

A input requirement:
  [TaskReplicate(required_A_regions_per_group), Shard(M), Replicate()]

B input requirement:
  [TaskReplicate(required_B_regions_per_group), Replicate(), Shard(N)]
```

The important point is not the exact first policy.  The important point is that
output shard groups determine legal task independence:

```text
task0 computes C tile group 0
task1 computes C tile group 1
...
```

Each task can read overlapping A/B SRAM regions, but it must establish its own
route/visibility program inside the task.  Unique source address does not imply
unique cost.

## Relationship to Apps

This RFC does not redefine OpenFabric apps.

```text
AppPlan app:
  PE-local state lifetime boundary
  semantic storage handoff boundary

DFU task:
  app-local independent work context
  no hidden data dependency with other tasks
```

The soft mesh lives inside one compile-time app unless an operator strategy
chooses to cut apps for materialization or sequencing.

For example, a collective op does not automatically have to cut an app.  If the
backend can provide a same-app allreduce/broadcast strategy, the collective may
remain within one app.  If not, the conservative fallback is:

```text
app0: compute/reduce/materialize
app1: reload/recompute/continue
```

## Compiler Pipeline Impact

The future shape should be:

```text
ChipProgram
  -> AppPlan
  -> OpStrategyPlan              # operator-level parallelism and work-domain hints
  -> TaskPartitionPlan           # chooses task-axis shard groups
  -> ProcessorLogicalProgram
       apps[]
       app-local soft processor programs over (task, processor)
  -> ProcessorTileProgram
  -> RuntimeImagePlan            # packs task contexts into CBUF/MICC images
  -> ProgramVendorABI
  -> ProgramBinRows
```

`TaskPartitionPlan` should be a verifier-readable contract object between
`AppPlan` and `ProcessorLogicalProgram`.  `ProcessorLogicalProgram` should
consume task decisions; it should not secretly invent task partitions from
`wave_id`, vendor row ids, or physical processor coordinates.

Current `ProcessorLogicalAppProgram` instantiates ops over physical processors.
This RFC suggests evolving it toward soft processors:

```text
for task_group in TaskPartitionPlan:
  for processor in physical_mesh:
    lower op into (task_group, processor) stream
```

Route and collective scopes then become task-local by default:

```text
route_scope = same task_id + selected processor group
```

## TaskPartitionPlan Skeleton

A minimal contract shape is:

```text
TaskPartitionPlan {
  app_id
  task_axis_size
  physical_mesh = [pe_row, pe_col]

  tasks[] {
    task_id

    owns_outputs[] {
      tensor
      region
      write_mode = Disjoint | ExplicitMerge(strategy)
    }

    requires_inputs[] {
      tensor
      region
      visibility = SRAMLoad | TaskLocalRoute | SameAppCollective | Materialized
      cost_accounting = PerTask | ProvenShared(strategy)
    }

    allowed_processor_group {
      pe_rows
      pe_cols
    }

    unresolved_partials[] {
      tensor
      op
      required_merge_scope
    }

    proofs {
      no_cross_task_pe_local_def_use
      output_regions_disjoint_or_merged
      input_regions_stable
    }
  }
}
```

This is not a binary layout.  It is the high-level task ownership contract that
later layers project onto vendor task rows and image packing.

## Legality Rules

A task partition is legal only if it proves:

```text
1. No task consumes another task's PE-local value.
2. Task output regions are disjoint, or merges are explicit and legal.
3. Every task can obtain its required inputs from SRAM or task-local routes.
4. Any replicated input communication/load cost is explicit.
5. Any TaskPartial placement is resolved by explicit strategy.
6. Shared SRAM input regions are stable for the lifetime of all consuming tasks,
   or mutations are represented as explicit storage dependencies.
7. PE-local values, route buffers, accumulators, and task-local temporaries are
   scoped by soft_processor_id.
8. TaskPartitionPlan is legal under any vendor-permitted task scheduling order,
   unless an explicit sequencing mechanism is represented.
```

The last rule is important:

```text
Legal task partitioning should survive arbitrary legal interleaving.
```

A task plan should not rely on task0 finishing before task1 unless the vendor
runtime profile provides and the IR represents that sequencing.

## Value Scope Verifier Rule

A verifier can model value visibility as:

```text
ValueScope(v) =
  PELocal(app_id, task_id, physical_pe_id)
  | TaskLocal(app_id, task_id, pe_group)
  | SRAMMaterialized(app_id, region)
  | AppBoundaryMaterialized(app_id, region)
```

A consumer may read `v` only if one of the following holds:

```text
1. Same PE-local scope.
2. Same task-local route/collective scope.
3. v is materialized in SRAM and consumer has an explicit input visibility action.
4. v crosses an app boundary through an explicit storage handoff.
```

The core invariant is:

```text
The task axis partitions ownership of work, not ownership of physical PEs.

A physical PE may appear in multiple soft processors, but PE-local state is scoped
by task_id.  Therefore, task partitioning must be legal without relying on hidden
reuse of local values across task contexts on the same physical PE.
```

## Cost Model Notes

Task-replicated inputs should be costed per task or per soft processor, not per
unique SRAM address:

```text
cost(task_plan) =
  Σ_task [
    SRAM_read_bytes(task)
    SRAM_read_transactions(task)
    task_local_route_bytes(task)
    task_local_collective_cost(task)
    CBUF_pressure(task)
    MICC/image_pressure(task)
  ]
  + explicit_merge_cost
  + materialization_cost
```

A backend may grant reuse credit only with explicit proof:

```text
reuse_credit requires explicit backend proof
```

Examples include future task-shared preload, image-level input reuse, or a proven
same-app broadcast mechanism.  None should be assumed by default.

## Operator Classification

Naturally legal task-axis sharding candidates:

```text
elementwise over disjoint output tiles
copy / cast / activation
layout transform with disjoint output regions
convolution over output tile groups
batched GEMM over batch/output tiles
gather with read-only source and disjoint outputs
```

Careful but possibly legal candidates:

```text
scatter, if writes are proven disjoint
reduction, if full reduction domain is contained within each task
softmax, if each complete row/head reduction is inside one task
layernorm, if each normalized unit is task-local
```

Usually unresolved `TaskPartial` candidates:

```text
K-split GEMM across task axis
global reduce_sum / reduce_max split across task axis
softmax split across the reduction dimension
layernorm split across the normalized dimension
histogram or scatter with possible collisions
prefix scan split across task axis
attention variants where normalization/reduction crosses task groups
```

Principle:

```text
TaskShard is legal when task outputs can be finalized without consuming another
task's PE-local result.
```

## Legacy GEMM Compatibility

Current GEMM should be re-expressed with an explicit policy such as:

```text
LegacyGemmTaskPlacementPolicy
```

It should mirror existing behavior:

```text
wave_id -> output_tile_group
task_id = legacy_wave_to_task_row(wave_id)
physical_pe_group = existing mesh policy
```

The required acceptance test is byte equivalence:

```text
old compiler cbuf/micc == new compiler cbuf/micc
```

This proves the refactor is changing the semantic source of truth, not the vendor
binary result.

## Incremental Plan

```text
Phase 0:
  Documentation and terminology.

Phase 1:
  Add TaskPartitionPlan skeleton.
  Add no-cross-task-local-value verifier in report-only mode.

Phase 2:
  Annotate ProcessorLogical actions with task_id / soft_processor_id.
  Add LegacyGemmTaskPlacementPolicy mirror.
  Require byte-equivalence against current GEMM binaries.

Phase 3:
  Introduce TaskShard / TaskReplicate / TaskPartial descriptors.
  Make unresolved TaskPartial a hard verifier error for runnable legacy DFU3500.

Phase 4:
  Add strategy experiments:
    output tiling variants
    materialize fallback
    same-app collectives only when backend proof exists
    non-GEMM task shard experiments

Phase 5:
  Cost-model integration:
    per-task input visibility cost
    duplicated SRAM load accounting
    task image packing pressure
    merge/materialization cost
```

## Open Questions

### Should task-axis placement extend existing Placement?

Near term: no.  Use separate descriptors:

```text
TaskShard
TaskReplicate
TaskPartial
```

Future work can unify them under generalized placement once axis capabilities are
explicit.

### Where should TaskPartitionPlan sit?

Between `AppPlan` and `ProcessorLogicalProgram`:

```text
AppPlan
  -> OpStrategyPlan
  -> TaskPartitionPlan
  -> ProcessorLogicalProgram
```

The task plan is a contract object.  Later lowering consumes it.

### Does collective force an app split?

No.  Collective requires an explicit strategy.  One legal strategy may be same-app
collective.  Another may be app split plus materialization.  If no strategy
exists, reject runnable lowering.

### Can legacy GEMM be byte-exact under this model?

It should be.  That is the required safety test before making the task-axis model
feed the runnable DFU3500 path.

## Why This Matters

This model clarifies a long-standing tension:

```text
DTensor placement wants to partition tensors over processors.
Task planning wants to partition independent work over vendor task rows.
```

The unifying idea is not merely “add a task dimension.”  The important idea is:

```text
make task independence, local-state isolation, and input visibility explicit in
the layout model
```

Vendor row arithmetic should be the final packing result, not the semantic source
of compiler task partitioning.
