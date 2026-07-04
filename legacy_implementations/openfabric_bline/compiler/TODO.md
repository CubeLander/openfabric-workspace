# Compiler TODO

## Tile-Level Fusion Op Chain

Current status: `ProcessorTileProgram` has explicit tile route / compute / store
actions and dependencies. GEMM+ReLU may temporarily keep ReLU as a fused local
op inside the GEMM tile phase so we can prioritize the DFU architecture and
vendor simulator binary path.

Future direction: generic fusion should become an explicit tile op chain, not a
hidden payload field on a phase.

```text
TileRouteAction(A/B visible)
  -> TileComputeAction(gemm_k_update)
  -> TileComputeAction(finalize_accumulator)
  -> TileComputeAction(bias_add / relu / silu / gelu / ...)
  -> TileStoreAction
```

Near-term rule:

```text
[ ] Do not block current DFU/SimICT work on generic fusion.
[ ] When adding nontrivial fusion, model each tile-local stage as a first-class
    TileComputeAction with explicit input/output refs and dependencies.
[ ] Keep current fused GEMM post-op path documented as a transition state.
```

## Layout Mismatch Handling

Illegal tensor shapes should fail fast. For example, `(M, K1) @ (K2, N)` with
`K1 != K2` is not a distributed-layout problem.

The important open problem is legal tensor shapes with unsupported or
incompatible placements. Example cases:

```text
Supported v1:
  A[M, K]: placements = [Shard(0), Replicate()]
  B[K, N]: placements = [Replicate(), Shard(1)]
  C[M, N]: placements = [Shard(0), Shard(1)]

Legal shape but unsupported layout:
  A[M, K]: placements = [Replicate(), Shard(1)]
  B[K, N]: placements = [Shard(0), Replicate()]
  C[M, N]: requires local partial results and a reduction/collective.

Legal shape but needs pre-layout transform:
  A[M, K]: placements = [Shard(0), Shard(1)]
  B[K, N]: placements = [Replicate(), Shard(1)]
  The local matmul contract is not satisfied until one side is redistributed,
  gathered, broadcast, or converted into a partial-reduction strategy.
```

PyTorch DTensor handles this class of problem through sharding propagation.
This is PyTorch runtime behavior, not the policy for this compiler:

```text
OpSchema
  -> sharding rule / strategy selection
  -> OutputSharding
  -> optional redistribute_schema in PyTorch DTensor
  -> local op on each rank
```

For GPDPU, the compiler should model the same semantic decision but lower it to
DFU actions only when the source program contains an explicit `redistribute`
node. This compiler is for writing deployable operators, not exploratory
PyTorch scripts, so layout movement must be visible in source and in `plan.json`.

```text
DTensor placements
  -> required layout contract for the chosen op template
  -> redistribute / collective intent
  -> per-PE tile movement
  -> CollectiveTileBundle
  -> BSP/subtask schedule
```

First implementation policy:

```text
1. Shape/dtype/rank errors: fail fast with ValueError or NotImplementedError.
2. Legal shape but unsupported placement: fail fast with a message pointing to
   explicit `redistribute(...)`.
3. Do not silently invent an output placement for unsupported matmul layouts.
4. Never automatically insert redistribute or collective layout transforms.
5. Do not add an `auto_redistribute` option.
6. Later, add a sharding-rule registry that can either:
   - accept the current placements,
   - accept an explicit `redistribute(...)` node,
   - choose among explicitly requested/supported matmul strategies,
   - or report an unsupported layout.
```

Near-term engineering tasks:

```text
[ ] Add a `redistribute()` frontend op that only records layout-transform intent.
[ ] Add explicit layout-transform intent into `plan.json`.
[ ] Add matmul sharding rules for:
    - output-sharded GEMM: [Shard(0), Replicate()] x [Replicate(), Shard(1)]
    - K-sharded partial GEMM: [Replicate(), Shard(1)] x [Shard(0), Replicate()]
[ ] Represent `Partial("sum")` outputs and require a reduce/all-reduce before
    nonlinear pointwise ops.
[ ] Lower simple redistribute intents to `CollectiveTileBundle`.
[ ] Ensure every layout movement in the final plan has a source-level
    `redistribute(...)` or another explicit collective op as its origin.
```

## Debug IR Storage And Query Surface

The debug artifacts are becoming too large for humans to read as flat text.
Treat the current `*.lines.txt` files as query views, not as the long-term
storage model.

Target direction:

```text
debug_ir.db / debug_ir.sqlite
  tables:
    tile_values
    tile_instances
    tensor_core_program_ops
    logical_collectives
    tile_collective_actions
    local_deps
    collective_deps
    block_dep_hints
    route_records
    assembly_records

*.lines.txt
  saved SQL/query views for human review and regression snapshots
```

Near-term rule:

```text
[ ] Do not add more huge default flat dumps.
[ ] Keep exhaustive edge tables in verbose/debug-only views.
[ ] Default review should be registry + per-TensorCore program.
[ ] Add stable ids for tile_collective_action records.
[ ] Make every downstream compute input traceable to:
      TileInstanceAlias
        -> source_action = tile_collective_action_id
        -> logical_collective_id / route_ref
        -> source tile value
```

The critical invariant is:

```text
compute must depend on the fine-grained tile collective action that produced
the visible tile instance, not only on the coarse logical collective.
```
