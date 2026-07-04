# RFC: Logical Routes, Tile Routes, and Post-Tile Lowering Views

## Status

Draft for discussion.

This note records the current refactor model for communication / route
dependencies and names the IR layer that should become the graph truth.

The key correction is:

```text
logical route is semantic data movement
tile route is the expanded execution dependency
```

In other words, route should not appear only as a backend patch after tile
planning. Route exists already in the processor logical program as shard-level
dataflow. Tile lowering then expands that large shard-level dependency into
many tile-level route dependencies.

## Core Claim

Processor logical plan owns logical data movement and shard-level dependencies.

Processor tile plan lowers each shard dependency into per-tile communication
dependencies.

The shape is:

```text
LogicalPlan:
  Shard A on ProcessorGroup X
    -> Shard A visible on ProcessorGroup Y

TilePlan:
  A_tile_0 route -> consumer_tile_0
  A_tile_1 route -> consumer_tile_1
  A_tile_2 route -> consumer_tile_2
  ...
```

So a single logical arrow becomes many parallel tile arrows:

```text
one shard-level communication dependency
  ↓ tile lowering
many tile-level communication dependencies
```

This releases parallelism. If the compiler kept the dependency as one big
arrow, execution would degenerate into:

```text
move whole shard
  ↓
compute whole shard
```

That is exactly what we do not want. It creates huge live ranges, breaks the
streaming K-loop shape, and does not match SRAM/SPM capacity constraints.

The desired execution shape is:

```text
tile0 visible -> tile0 compute
tile1 visible -> tile1 compute
tile2 visible -> tile2 compute
```

## Route Is First-Class, But Not Standalone

Route is not an independent execution stage after tile planning.

Route is:

```text
tile value visibility implementation
```

and therefore belongs inside tile execution:

```text
TilePhase k0:
  route_prefix:
    make A[k0] visible
    make B[k0] visible
  compute:
    C += A[k0] @ B[k0]

TilePhase k1:
  route_prefix:
    make A[k1] visible
    make B[k1] visible
  compute:
    C += A[k1] @ B[k1]
```

The useful rule:

```text
logical route is semantic;
tile route is route-prefix execution dependency.
```

## Corrected Pipeline

The new compiler should model:

```text
ChipProgram
  ↓
ProcessorLogicalProgram
  - logical ops
  - logical routes
  - shard-level dependency graph

  ↓ tile lowering

ProcessorTileProgram
  - tile ops
  - tile route actions
  - tile-level dependency graph
  - route prefixes fused into tile phases

  ↓ backend lowering

DFUAssembly / DFUGraph / DFUPacking / Runtime
```

More explicitly:

```text
ChipProgram
  -> ProcessorLogicalPlan
       LogicalTensor
       LogicalCompute
       LogicalRoute
       LogicalDependency

  -> ProcessorTilePlan
       TileTensor
       TileCompute
       TileRoute
       TileDependency

  -> DFUGraphProgram
       GraphNode
       GraphEdge

  -> DFUPackingProgram
       Task
       Subtask
       Instance

  -> DFURuntimeProgram
  -> VendorPackage
       Binary
       Runtime files
```

This replaces the misleading model:

```text
ProcessorTileProgram
  -> ProcessorRouteProgram
  -> DFUAssemblyProgram
```

That old phrasing makes route sound like a standalone program between tile and
assembly. It is better to say:

```text
ProcessorLogicalProgram
  -> ProcessorTileProgram(with expanded tile route dependencies)
  -> RoutedProcessorTileProgram(optional explicit routed view)
  -> DFUExecutionProgram / DFUAssemblyProgram
```

`RoutedProcessorTileProgram` may still be a useful dataclass, but its meaning is
not "run this route program first". Its meaning is:

```text
tile phases annotated with route_prefix_actions
```

## Logical Dependency Model

At processor logical level, represent communication as shard-level logical
route edges.

Possible shape:

```text
LogicalRouteEdge:
  id
  src_shard
  dst_shard_or_group
  producer_action
  consumer_action
  visibility_kind
  fabric_scope
  dependency_kind
  route_steps[]
  endpoint_by_processor
```

Examples:

```text
A shard on row source processor
  -> A shard visible to row consumer group

B shard on column source processor
  -> B shard visible to column consumer group
```

This level answers:

```text
Which shard-level value must be visible before which logical consumer?
```

It should also preserve the route-program shape:

```text
source_shard
  -> logical_route_step_0(source local visibility)
  -> logical_route_step_1(first hop)
  -> logical_route_step_2(second hop)
  -> ...
  -> consumer logical compute
```

So shard-level dependency is not just a root-to-consumer summary. It is already
a route program. Tile lowering then maps each logical route step into many
tile-level route actions.

It does not answer:

```text
Which concrete tile packet moves at k=3?
Which route edge is COPYT edge 7?
```

## Tile Dependency Model

Tile lowering expands each `LogicalRouteEdge` into many tile route edges.

Possible shape:

```text
TileRouteEdge:
  id
  logical_route_edge_id
  src_tile
  dst_tile_or_group
  consumer_tile_action
  route_prefix_action
  dependency_id
  tile_coord
  k_index
```

Then each tile phase can carry route prefixes:

```text
TilePhase:
  id
  route_prefix_actions[]
  compute_action
  route_suffix_actions[]
  store_action?
  deps[]
```

For GEMM/SUMMA:

```text
GemmKUpdate:
  k_index
  route_prefix_actions:
    - A tile visibility
    - B tile visibility
  compute_action:
    C += A_k @ B_k
```

This level answers:

```text
Which exact tile visibility must happen before this tile compute action?
```

This is where one large dependency becomes many small, parallel dependencies.

## Graph Truth

The graph truth should live at `ProcessorTileProgram`.

Reason:

- `ProcessorLogicalProgram` is still too abstract: it knows shard-level
  dependencies, but not the per-tile parallel execution surface.
- `DFUAssemblyProgram` is implementation payload: it knows template calls,
  route edge records, and symbolic opcodes, but should not decide semantic
  scheduling truth.
- `DFUPackingProgram` is runtime containerization: it maps graph work into
  task/subtask/instance structures after the dependency truth already exists.
- Vendor binary files are serialization artifacts and must never become the
  source of compiler truth.

`ProcessorTileProgram` is the first layer where all of these are explicit at
the same time:

```text
explicit parallelism
explicit communication
explicit dependencies
explicit storage / live-window pressure
```

Therefore later DFU graph construction should be understood as a backend view
over tile truth:

```text
ProcessorTileProgram
  -> DFUGraphProgram
```

not:

```text
Assembly records
  -> graph truth
```

Assembly record IDs may be attached to graph nodes as payload references, but
the scheduling and dependency truth should come from tile actions and tile
dependencies.

## Action Vocabulary

At tile level, route should be one action kind among several:

```text
TileAction:
  - TileRouteAction
  - TileComputeAction
  - TileStoreAction
```

This keeps route visible as a first-class compiler object, without turning it
into a separate whole-program stage.

Suggested fields:

```text
TileRouteAction:
  id
  logical_route_edge_id
  src_tile_ref
  dst_tile_ref_or_group
  participants
  execution_processor
  endpoint_processor
  route_kind
  symbolic_edges
  visibility_kind
  folding_signature
```

For DFU, `TileRouteAction` should be modeled as sender push:

```text
execution_processor = source / sender PE where COPY/COPYT is emitted
endpoint_processor  = destination / receiver PE where visibility is produced
```

Legacy evidence: GEMM template generation emits `COPYT` into the source PE's
CSV when the current PE is `copyA`'s `p.first`, and the common block mapper later
fills destination PE position / destination operand fields from the child node.
So the route instruction block belongs to the sender side, while the dependency
endpoint belongs to the receiver side.

## How This Relates to Legacy

Legacy `to_plan()` in `compiler/gpdpu_compiler/core_legacy/env.py` builds
several objects after `tile_backend`:

```text
tile_backend
  ├── route_lowering
  ├── architecture_backend
  ├── assembly_backend
  └── global_tile_dependency_network
        ↓
      dfu_graph
        ↓
      dfu_packing
```

Source landmarks:

- `compiler/gpdpu_compiler/core_legacy/env.py:241` builds `route_lowering`.
- `compiler/gpdpu_compiler/core_legacy/env.py:242` builds `architecture_backend`.
- `compiler/gpdpu_compiler/core_legacy/env.py:243` builds `assembly_backend`.
- `compiler/gpdpu_compiler/core_legacy/env.py:244` builds `global_tile_dependency_network`.
- `compiler/gpdpu_compiler/core_legacy/env.py:249` builds `dfu_graph`.
- `compiler/gpdpu_compiler/core_legacy/env.py:250` builds `dfu_packing`.

Those objects should be read as derived views, not independent execution
stages.

Legacy route lowering is a view over tile-level collective obligations:

```text
tile_backend.collective_bundles
  -> symbolic mesh routes
```

It does not mean all routes run before all compute. The compute assembly records
depend on route refs per k instance, which is evidence that route is logically
attached to each tile update.

## Legacy Route Lowering

Source: `compiler/gpdpu_compiler/core_legacy/route_lowering.py:8`.

Input:

```text
tile_backend.collective_bundles
```

Output:

```text
route_lowering
```

For GEMM/SUMMA, each k update needs A/B visibility:

- A tile visibility along one mesh direction;
- B tile visibility along the other mesh direction;
- source processor selection;
- participants;
- symbolic mesh edges;
- folding signature.

Legacy explicitly stops before final transfer instruction lowering:

```text
physical_instruction_lowered = False
architecture_independent = True
```

The refactor should preserve this useful symbolic route information, but attach
it back to tile phases:

```text
LogicalRouteEdge
  -> TileRouteEdge[]
  -> TileRouteAction / RoutePrefixAction
  -> TilePhase.route_prefix_actions
```

## Legacy Architecture Backend

Source: `compiler/gpdpu_compiler/arch/legacy_dfu.py:25`.

Input:

```text
tile_backend.tile_programs[*].phases
```

Output:

```text
architecture_backend
```

For `local_gemm_summa`, legacy expands:

```text
one tile phase
  -> one GEMM instruction template
  -> one instruction instance per k_block_update
```

This answers:

```text
which DFU compute template implements this tile action?
```

It should remain separate from route planning. Compute lowering consumes the
route-prefix refs; it should not invent route topology.

## Legacy Assembly Backend

Source: `compiler/gpdpu_compiler/arch/legacy_dfu.py:71`.

Input:

```text
tile_backend
route_lowering
architecture_backend
```

Output:

```text
assembly_backend
```

This is where the derived views meet. It emits:

```text
compute_records
route_edge_records
store_records
```

### Compute Records

Source: `compiler/gpdpu_compiler/arch/legacy_dfu.py:376`.

For GEMM, each k-block instruction instance becomes:

```text
asm:compute:{pe}:{phase_id}:k{k}
```

The record references the row/column route refs for the same k update. This is
exactly the dependency shape we want:

```text
route prefix for A/B
  -> compute k update
```

### Route Edge Records

Source: `compiler/gpdpu_compiler/arch/legacy_dfu.py:496`.

Each symbolic route edge becomes:

```text
asm:route_edge:{route_key}:edge{edge_idx}
```

with opcode-like symbolic labels such as:

```text
COPYT_SYMBOLIC
```

In the new model, these records should be emitted from `TileRouteAction`
objects attached to tile phases.

### Store Records

Source: `compiler/gpdpu_compiler/arch/legacy_dfu.py:546`.

Legacy derives store records from GEMM phases:

```text
local_gemm_summa phase
  -> implicit STORE_TILE_SYMBOLIC
```

The refactored compiler should not copy that hidden assumption. We already made
SRAM boundaries explicit:

```text
ChipProgram.store_sram_tensor
  -> ProcessorLogicalAction.store_sram_tensor
  -> ProcessorTilePhase.store_sram_tensor
  -> explicit DFU store assembly record
```

## Dependency Graph Interpretation

The graph should reflect route as per-tile dependency, not as one global barrier.

For one GEMM k update:

```text
route_A_tile(k)
route_B_tile(k)
  ↓
compute_C_update(k)
  ↓
next k update or final store
```

Not:

```text
all A/B routes for every k
  ↓
all compute
```

This matters because:

- it avoids impossible live ranges;
- it supports route/compute pipelining;
- it keeps the scheduling unit close to real streaming execution;
- it makes future deadlock / stall debugging much clearer.

## Required Refactor Changes

This RFC changes earlier implementation expectations. The main correction is:

```text
do not add a top-level ProcessorRouteProgram as the next major IR
```

Instead, start modeling route and dependency earlier, then expand them during
tile lowering.

### 1. Modify `program_processor.py`

The processor logical layer should explicitly model logical dependencies and
logical routes.

Add or prepare dataclasses like:

```text
LogicalRouteEdge
LogicalDependency
LogicalDependencyGraph
```

The processor logical program should include fields such as:

```text
logical_routes[]
logical_dependencies[]
dependency_graph
```

This means `ProcessorLogicalProgram` should not only contain per-processor
actions. It should also describe why those actions are ordered:

```text
LogicalCompute consumes value that requires LogicalRoute visibility
LogicalRoute depends on producer shard availability
LogicalStore depends on final logical compute result
```

For current GEMM/SUMMA, logical lowering should create shard-level route edges
for A/B visibility instead of leaving route to be inferred only after tiling.

### 2. Modify `program_tile.py`

Tile lowering should consume logical routes and expand them:

```text
LogicalRouteEdge
  -> TileRouteEdge[]
  -> TileRouteAction[]
  -> TilePhase.route_prefix_actions[]
```

The tile program should include:

```text
tile_route_actions[]
tile_dependencies[]
route_prefix_actions on tile phases / k updates
```

For GEMM/SUMMA, each k update should have:

```text
A tile route prefix
B tile route prefix
compute action
```

This gives the desired dependency shape:

```text
TileRouteAction(A, k)
TileRouteAction(B, k)
  -> TileComputeAction(k)
```

For a multi-hop route, dependencies should follow the propagation path:

```text
source_shard_or_source_tile_available
  -> source_local_visibility
  -> route_hop_0(src -> mid0)
  -> route_hop_1(mid0 -> mid1)
  -> route_hop_2(mid1 -> dst)
  -> consumer_compute
```

Do not also add a separate dependency from the route tail back to the route
root. The source-local step already depends on the source shard/tile, the first
hop depends on that source-local step, and later hops depend on previous hops.
Adding tail-to-root dependencies would over-constrain the graph and make the
route look more like a root fanout barrier than a streaming propagation chain.

### 3. Demote `program_route.py` / `ProcessorRouteProgram`

If a route-specific helper file is still useful, it should be an internal tile
lowering helper or an annotated tile view, not a standalone top-level IR stage.

Preferred names:

```text
program_routed_tile.py
RoutedProcessorTileProgram
attach_route_prefixes(...)
```

Avoid names that imply a separate execution program:

```text
ProcessorRouteProgram
```

### 4. Update DFU Graph Lowering

DFU graph construction should consume tile actions and tile dependencies:

```text
TileRouteAction
TileComputeAction
TileStoreAction
TileDependency
```

It may attach symbolic assembly records later, but graph topology should be
derived from tile-level truth.

### 5. Update Legacy Comparison

Legacy `route_lowering` should be used as a comparison view:

```text
legacy route_lowering totals
new tile route action / route prefix totals
```

It should not be treated as proof that route must be a standalone post-tile
program.

## Proposed Near-Term Implementation

Do not implement a standalone `ProcessorRouteProgram` first.

Instead, update the IR in two places:

### 1. Processor Logical Layer

Add shard-level logical route / dependency objects:

```text
LogicalRouteEdge
LogicalDependencyGraph
```

These can live in:

```text
compiler/gpdpu_compiler/core/program_processor.py
```

or in a small helper file:

```text
compiler/gpdpu_compiler/core/program_dependency.py
```

### 2. Processor Tile Layer

Expand logical route edges into tile route actions:

```text
LogicalRouteEdge
  -> TileRouteEdge[]
  -> TileRouteAction[]
  -> TilePhase.route_prefix_actions[]
```

This can live in:

```text
compiler/gpdpu_compiler/core/program_tile.py
```

or, if it gets bulky:

```text
compiler/gpdpu_compiler/core/program_routed_tile.py
```

The first version should:

- preserve current `TileCollectiveBundle` information;
- introduce explicit route-prefix actions;
- attach A/B route prefixes to each GEMM k-block update;
- choose stable source processor inside the visibility group;
- emit symbolic line-fanout route edges;
- preserve route folding signatures;
- dump enough JSON to compare with legacy `route_lowering`.

The comparison target should be:

```text
legacy route_lowering totals
new tile route action / route prefix totals
```

not:

```text
legacy execution order == new execution order
```

because legacy route_lowering is a derived route view, not an execution trace.

## Open Questions

1. Should `LogicalRouteEdge` be created during processor logical lowering, or
   inferred during tile lowering?

   Current recommendation: create it during processor logical lowering. The
   logical plan should own shard-level data movement and dependencies.

2. Should route prefix actions be attached to `TilePhase` or to each
   `k_block_update`?

   Current recommendation: attach to each `k_block_update` for GEMM/SUMMA,
   because A/B visibility is k-specific.

3. Should non-GEMM phases also support route prefixes?

   Current recommendation: yes, but allow an empty list. Elementwise local ops
   may not need route prefixes in the first SPMD model.

4. Should graph construction consume tile route actions or assembly records?

   Current recommendation: graph construction should consume tile route actions
   as scheduling facts, and may attach assembly record IDs as payload refs.
   Assembly records should not become the scheduling truth.

## Short Version

The corrected model is:

```text
ProcessorLogicalProgram
  owns logical routes and shard-level dependency graph

ProcessorTileProgram
  lowers each logical route into many tile route actions
  attaches tile route actions as route prefixes on tile phases
  is the graph truth

DFU backend
  lowers route prefixes, compute actions, and store actions into
  assembly / graph / packing / runtime objects
```

Route is first-class, but not standalone.

It starts as a shard-level logical dependency:

```text
producer shard visible to consumer group
```

and lowers into many per-tile execution dependencies:

```text
route this A/B tile for this k
then compute this k
then release / reuse live window
```

This is closer to DFU streaming execution than treating route lowering as a
separate post-tile program.
