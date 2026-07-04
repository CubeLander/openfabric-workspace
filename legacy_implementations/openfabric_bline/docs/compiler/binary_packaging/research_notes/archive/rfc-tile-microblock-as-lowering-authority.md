# RFC: Tile MicroBlock as the Lowering Authority

## Status

Draft for immediate implementation.

This RFC corrects the current boundary between `ProcessorTileProgram`,
`ProgramNodeProgram`, `DFUPackingProgram`, `ProgramAsm`, and vendor ABI lowering.

The short version:

```text
Executable block partition must be decided at tile level.

program_asm.py and program_vendor_abi.py should not rediscover route / compute
block roles from flat nodes.

TileLoopRegion decides what repeats.
TileMicroBlock decides which actions inside the repeated body form an executable
unit.
```

## Background

The current refactor has already established the main compiler pipeline:

```text
ChipProgram
  -> ProcessorLogicalProgram
  -> ProcessorTileProgram
  -> ProgramNodeProgram
  -> DFUPackingProgram
  -> ProgramAsm
  -> ProgramVendorABI
  -> binary / bundle
```

`ProcessorTileProgram` is supposed to be the first layer where tile execution is
explicit:

```text
tile route actions
tile compute actions
tile store actions
tile dependencies
tile loop regions
```

The recent loop-folding work also introduced `TileLoopRegion`, so GEMM K loops
can be represented structurally instead of only as expanded `k0/k1/k2/k3`
actions.

That direction is right, but the current implementation still has one important
granularity bug.

## Current State

### What is already correct

At the dependency level, the current tile graph is mostly right:

```text
A local visibility endpoint -> compute(A, B)
B local visibility endpoint -> compute(A, B)
compute_k_i -> compute_k_i+1    # loop-carried accumulator recurrence
compute_final -> store
route_step_i -> route_step_i+1
```

After edge legalization:

```text
compute_k_i -> compute_k_i+1
```

is classified as:

```text
loop_carried_edge
absorbed_by = loop_carried_state
vendor_graph_eligible = false
```

This is the right semantic direction. K recurrence should be folded into vendor
repeat semantics, not emitted as explicit vendor predecessor/successor graph
edges.

Store order also does not need to be expressed as many fine-grained graph edges
inside the repeated body. It can be represented by a post-loop / subtask boundary
or a future `LoopRegionExitToken`.

### What is wrong

`TileLoopBodyInstance` currently records only flat action groups:

```text
action_ids
route_action_ids
compute_action_ids
store_action_ids
```

For GEMM, `_make_gemm_tile_loop_region()` currently builds:

```text
route_action_ids = all A route steps + all B route steps
action_ids = route_action_ids + compute_action_id
```

This means the loop body for a consumer processor contains the whole A/B route
path, not just the route work locally executed by that processor and not just the
local visibility endpoints consumed by its compute.

Example:

```text
consumer processor = processor_1_2

A row route path:
  processor_1_0 -> processor_1_0
  processor_1_0 -> processor_1_1
  processor_1_1 -> processor_1_2
  processor_1_2 -> processor_1_3

consumer compute on processor_1_2 really needs:
  A endpoint at processor_1_2
  B endpoint at processor_1_2
```

But the current loop body action list may include every route step in the path.
That causes downstream nodes / packing / asm to see one coarse k-stream body that
mixes:

```text
local materialize
forward to downstream processors
local compute
```

### Symptom

The compute action itself only depends on two local tile visibility endpoints:

```text
A endpoint -> compute
B endpoint -> compute
```

plus the loop-carried accumulator state.

However, the current `ProgramAsm` block is:

```text
one PackingInstance -> one ProgramAsmBlock
```

Because each packing instance contains mixed route and compute nodes, the block
inherits the union of all route/compute edges. This makes a vendor exeBlock look
like it has too many predecessors/successors.

This is not a compute-dependency problem. It is a tile execution unit
partitioning problem.

## Root Cause

The compiler is missing a tile-level execution partition between:

```text
TileAction
```

and:

```text
ProgramNode / PackingInstance / ProgramAsmBlock
```

Currently the downstream passes must infer executable block boundaries from flat
nodes and packing instances. That is backwards.

The correct source of truth should be:

```text
ProcessorTileProgram
  owns tile actions
  owns tile dependencies
  owns tile loop regions
  owns tile micro-blocks
```

Then later passes simply lower these micro-blocks:

```text
TileMicroBlock
  -> ProgramNode group / DFU graph block
  -> Packing block
  -> Asm block
  -> Vendor exeBlock
```

## Design Goal

Add first-class tile-level micro-blocks.

```text
TileMicroBlock:
  a small executable tile-region unit
  owned by one processor
  inside or outside a TileLoopRegion
  containing route / compute / store action refs
  carrying a semantic role
```

`TileMicroBlock` is not vendor binary. It is still tile IR.

It answers:

```text
which tile actions form one local executable block?
what role does this block play in the tile program?
which loop instance does it belong to?
which dependencies cross block boundaries?
which dependencies are internal to the block?
```

## Proposed IR

The intended nesting is:

```text
ProcessorTileProgram
  TileLoopRegion              # what repeats
    TileLoopBodyInstance      # one symbolic loop instance
      TileMicroBlock          # executable units inside the instance
        TileAction            # primitive route / compute / store actions
```

This RFC extends, rather than replaces, the earlier TileLoop-aware RFC:

```text
TileLoopRegion:
  repeated boundary and carried state

TileMicroBlock:
  executable block boundary inside repeated body

TileAction:
  primitive tile operation
```

### New dataclass: `TileVisibilityRef`

DFU route is sender-push. A receiver-side visibility endpoint should therefore
not automatically become an executable block. Unless vendor evidence proves a
receiver-side receive instruction exists, visibility should be modeled as a
token/value:

```python
@dataclass(frozen=True)
class TileVisibilityRef:
    ref_id: str
    tensor_ref: str
    producer_action_id: str
    endpoint_processor: str
    source_processor: str | None = None
    loop_region_id: str | None = None
    loop_instance_id: int | None = None
    attrs: dict[str, Any] = field(default_factory=dict)
```

This keeps executable micro-blocks restricted to real work:

```text
route_source_materialize
route_forward
compute_update
tile_store
local_compute
```

If later evidence shows a receiver-side receive instruction exists,
`route_receive_visibility` can be reintroduced as an executable micro-block.

### New dataclass: `TileMicroBlock`

```python
@dataclass(frozen=True)
class TileMicroBlock:
    block_id: str
    processor: str
    block_kind: str
    source_phase_id: str | None

    loop_region_id: str | None = None
    loop_instance_id: int | None = None
    loop_axis: str | None = None
    fold_policy: str | None = None

    action_ids: tuple[str, ...] = ()
    route_action_ids: tuple[str, ...] = ()
    compute_action_ids: tuple[str, ...] = ()
    store_action_ids: tuple[str, ...] = ()

    input_visibility_refs: tuple[str, ...] = ()
    output_visibility_refs: tuple[str, ...] = ()

    input_value_refs: tuple[str, ...] = ()
    output_value_refs: tuple[str, ...] = ()

    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)
```

### New dataclass: `TileBlockDependency`

The tile layer should also expose block-level dependencies projected from
action-level dependencies:

```python
@dataclass(frozen=True)
class TileBlockDependency:
    dep_id: str
    src_block_id: str
    dst_block_id: str
    dep_kind: str
    source_tile_dependency_ids: tuple[str, ...]
    loop_region_id: str | None = None
    loop_instance_id: int | None = None
    vendor_graph_eligible: bool = True
    absorbed_by: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)
```

This gives downstream passes a block graph directly:

```text
TileActionDependency
  -> TileBlockDependency
  -> PackingDependency
  -> VendorGraphDependency
```

If an action dependency stays inside one micro-block, it becomes:

```text
same_micro_block_internal
```

and should not become a vendor block-level edge.

### Recommended `block_kind` values

For GEMM K-stream:

```text
route_source_materialize
route_forward
compute_update
loop_exit
```

For stores:

```text
tile_store
```

For non-GEMM local ops:

```text
local_compute
```

The naming can be adjusted, but the key is that these roles are tile-level
semantic roles, not ASM/vendor inventions.

## Correct GEMM Shape

For one processor and one K instance, the tile body should look like:

```text
TileLoopBodyInstance(k)
  micro_blocks:

    route_* blocks:
      local route actions executed by this processor

    compute_update:
      depends on exactly:
        A local visibility endpoint
        B local visibility endpoint
        loop-carried accumulator state

      contains:
        tile_compute_action_id
```

The compute block should not include unrelated downstream route forwarding.

If the same processor both computes locally and forwards a tile to the next
processor, these are two tile micro-blocks:

```text
route_forward
compute_update
```

They may share the same loop instance, but they are different executable units.

## Route Semantics

DFU route action is sender-push:

```text
execution_processor = sender
endpoint_processor  = receiver / visible endpoint owner
```

Therefore, a route action belongs to the tile micro-block of its
`execution_processor`.

It may produce a visibility endpoint for another processor.

This distinction must remain explicit:

```text
route action placement:
  by execution_processor

compute dependency:
  by endpoint visibility consumed by compute processor
```

This prevents a consumer loop body from accidentally owning the entire route
path.

## Dependency Rules

### Route step dependency

Route propagation remains a real dependency:

```text
route_step_i -> route_step_i+1
```

But it is a dependency between route micro-blocks, not a reason to put every
route step into the consumer compute block.

At block level:

```text
route_forward@processor_i -> route_forward@processor_j
```

not:

```text
full_route_path -> compute_update
```

### Visibility before compute

Compute depends only on local visibility endpoints:

```text
A_endpoint_on_processor_p -> compute_on_processor_p
B_endpoint_on_processor_p -> compute_on_processor_p
```

This is the important invariant:

```text
GEMM compute_update has two tile visibility dependencies.
```

The accumulator recurrence is loop-carried state, not a normal vendor edge.

### Accumulator recurrence

Inside `TileLoopRegion`:

```text
compute_k_i -> compute_k_i+1
```

can remain in the debug / analysis graph, but should be classified as:

```text
loop_carried_edge
```

and folded into:

```text
TileLoopRegion.carried_refs
```

### Store

Store should depend on loop final output:

```text
LoopRegionExitToken -> tile_store
```

The initial implementation may continue to use:

```text
compute_k_last -> tile_store
```

as a debug-expanded equivalent, but vendor ABI should eventually consume the
folded loop-exit form.

## Tile Block Dependency Classification

After `TileMicroBlock` exists, edge legalization should be two-stage:

```text
TileActionDependency
  -> TileBlockDependency
  -> vendor graph edge classification
```

Suggested block dependency classes:

```text
same_micro_block_internal
cross_micro_block_same_instance
cross_instance_loop_carried
loop_exit_to_store
cross_processor
normal_cross_block
```

Vendor graph emission should not consume:

```text
same_micro_block_internal
cross_instance_loop_carried
internal_template_edge
```

It may consume:

```text
cross_micro_block_same_instance
loop_exit_to_store
cross_processor
normal_cross_block
```

subject to vendor fan-in/fan-out limits.

## Layering Policy

### `program_tile.py`

Owns:

```text
TileRouteAction
TileComputeAction
TileStoreAction
TileDependency
TileLoopRegion
TileMicroBlock
```

This layer decides micro-block roles.

### `program_nodes.py`

Consumes tile micro-blocks.

It should not need to reconstruct local route/compute/store roles from flat
actions. It may still create one node per tile action for analysis, but it must
also preserve:

```text
action_id -> tile_micro_block_id
tile_micro_block_id -> node_ids
```

### `program_packing.py`

Consumes tile micro-block IDs and loop metadata.

It assigns:

```text
task
subtask
instance
```

but should not decide whether a route action is source materialize, forward, or
compute-adjacent. That decision is already made by `program_tile.py`.

### `program_asm.py`

Maps each tile micro-block / packed micro-block to symbolic asm block.

It should not use:

```text
one PackingInstance -> one ProgramAsmBlock
```

as a semantic rule.

That policy is too coarse. A single repeated K instance can contain multiple
tile micro-blocks.

### `program_vendor_abi.py`

Serializes asm blocks to vendor exeBlocks.

It should not infer tile roles. It should only project already-decided block
roles into vendor rows.

## Execution Plan

### Phase 1: Add tile micro-block IR

Modify `program_tile.py`:

```text
add TileVisibilityRef dataclass
add TileMicroBlock dataclass
add TileBlockDependency dataclass
add tile_micro_blocks: dict[str, TileMicroBlock]
add tile_visibility_refs: dict[str, TileVisibilityRef]
add tile_block_dependencies: dict[str, TileBlockDependency]
add action_id -> tile_micro_block_id index
add micro_block_ids to TileLoopBodyInstance
add optional micro_block_refs to TilePhase payload
```

Expected result:

```text
ProcessorTileProgram dump shows micro-blocks per loop instance.
```

No downstream behavior needs to change in this phase.

### Phase 2: Build GEMM micro-blocks

During GEMM tile lowering:

```text
for each route action:
  assign to a micro-block on action.execution_processor

for each compute action:
  assign to compute_update block on action.processor

for each store action:
  assign to tile_store block
```

Implementation should start conservative:

```text
Patch 1A:
  Add dataclasses and tables.

Patch 1B:
  Emit one micro-block per action as a trivial ownership-correct baseline.

Patch 1C:
  Group compatible route actions into route micro-blocks.

Patch 1D:
  Add validator and dump checks.
```

The one-block-per-action baseline is useful because it proves ownership before
we optimize grouping:

```text
route action owner == execution_processor
compute action owner == compute.processor
store action owner == store.processor
```

Important correction:

```text
TileLoopBodyInstance for processor P should not blindly include every route
action on the A/B route path.
```

Instead it should reference micro-blocks relevant to processor P:

```text
local route blocks executed by P
local compute block executed by P
```

A route action can still be part of multiple consumers' visibility story through
dependencies, but its executable ownership is unique:

```text
owner = execution_processor
```

### Phase 3: Add micro-block validation

Add checks:

```text
each tile action belongs to exactly one executable micro-block
each micro-block belongs to one processor
route action block.processor == route.execution_processor
compute action block.processor == compute.processor
store action block.processor == store.processor
compute_update block has exactly one compute action for MVP
compute_update visibility predecessors are exactly A/B endpoints
loop-carried recurrence is not counted as normal visibility predecessor
compute_update must not contain route actions
compute_update must not contain store actions
route_forward must not contain compute actions
route_forward must not contain store actions
```

For GEMM:

```text
compute_update predecessor tile roles:
  A visibility endpoint
  B visibility endpoint
  optional loop carried state
```

### Phase 4: Propagate micro-block IDs to ProgramNode

Modify `program_nodes.py`:

```text
ProgramNode.payload.tile_micro_block_id
ProgramNode.payload.tile_micro_block_kind
ProgramNodeProgram.micro_blocks
```

Keep one node per tile action for now.

Expected result:

```text
node -> micro-block mapping is explicit.
micro-block -> node list is explicit.
```

### Phase 5: Pack by micro-block, not by instance-only grouping

Modify `program_packing.py`:

```text
PackingInstance can still represent k instance rows.
PackingBlock or equivalent should represent tile micro-block execution units.
```

At minimum, node bindings need:

```text
tile_micro_block_id
tile_micro_block_kind
```

Then edge legalization can reason at micro-block granularity:

```text
same_micro_block
cross_micro_block_same_instance
cross_instance_loop_carried
cross_subtask
cross_processor
```

MVP mapping:

```text
one TileMicroBlock -> one ProgramAsmBlock
```

Future capacity fallback:

```text
one TileMicroBlock -> multiple ProgramAsmBlocks
```

is allowed if instruction/resource limits require it, but every split asm block
must retain the same `source_tile_micro_block_id`.

### Phase 6: Lower micro-blocks to ASM blocks

Modify `program_asm.py`:

```text
one tile micro-block -> one ProgramAsmBlock
```

not:

```text
one PackingInstance -> one ProgramAsmBlock
```

This removes the artificial block fanout caused by mixing route forwarding and
compute in the same block.

### Phase 7: Vendor ABI consumes asm block roles

Modify `program_vendor_abi.py` only after ASM blocks carry micro-block identity.

Vendor exeBlocks should expose roles inherited from tile micro-blocks:

```text
route_source_materialize
route_forward
compute_update
tile_store
```

This layer should remain boring.

## Target Effects

### Dependency clarity

For one GEMM compute block:

```text
normal incoming tile deps:
  A local visibility
  B local visibility

absorbed:
  loop-carried accumulator recurrence
```

It should not inherit unrelated downstream route-forward successors simply
because those actions shared the same K instance.

### No hidden scheduler in ASM

ASM lowering becomes:

```text
TileMicroBlock -> ProgramAsmBlock
```

not:

```text
PackingInstance -> guess mixed instruction block
```

### Better vendor graph pressure

Expected overflow reduction:

```text
successor/predecessor pressure no longer comes from mixed route+compute blocks.
```

Remaining overflow, if any, should point to real hardware graph constraints, not
IR block granularity artifacts.

Capacity reports should track both sides:

```text
block_count_before_microblock
block_count_after_microblock
max_predecessor_before / after
max_successor_before / after
exeBlock_count_before / after
```

Micro-blocks reduce edge pollution, but they may increase block count. If block
count becomes the limiting resource, the compiler should add safe coalescing
rules later. It must not blindly coalesce `route_forward + compute_update`
unless verification proves compute does not inherit unrelated downstream route
successors.

### Cleaner loop folding

`TileLoopRegion` remains authoritative:

```text
repeat_count
carried_refs
body instances
micro-blocks per instance
```

The folded vendor body can be built from micro-block templates instead of from
flat node lists.

## Tests to Add / Update

### Tile program tests

Assert:

```text
tile_micro_block_count > 0
tile_visibility_ref_count > 0 for routed GEMM
tile_block_dependency_count > 0
all route actions have exactly one micro-block
all compute actions have exactly one micro-block
compute_update micro-block contains only compute_update action(s)
route_forward micro-block contains only route actions
```

For a representative processor:

```text
compute_update block incoming visibility endpoints == {A_endpoint, B_endpoint}
```

Also assert:

```text
consumer compute block does not own full route path
route block processor == route.execution_processor
compute input visibility endpoint processor == compute block processor
loop_carried block dependency is not vendor_graph_eligible
```

### Node tests

Assert:

```text
ProgramNode.payload.tile_micro_block_id is not None
ProgramNodeProgram.micro_blocks maps block -> node ids
```

### Packing tests

Assert:

```text
k_stream repeated body template uses micro-block ids
loop-carried edges are absorbed
same-instance route/compute edges are classified at micro-block granularity
```

### ASM tests

Assert:

```text
ProgramAsmBlock.source_tile_micro_block_id exists
compute asm block does not contain route-forward instructions
route-forward asm block does not contain HMMAL instruction
```

### Vendor ABI tests

Assert:

```text
VendorExeBlockRow.role comes from tile_micro_block_kind
successor/predecessor overflow is reduced or explained by real cross-block deps
```

## Non-Goals

This RFC does not require:

```text
multi-accumulator K folding
generic fusion graph
binary serializer
full operand residency allocator
dynamic shape
CUDA/CANN abstraction
```

Those remain later work.

## Important Invariants

```text
Tile route ownership follows execution_processor.
Tile visibility consumption follows endpoint_processor.
Compute depends on local visibility endpoints, not whole route paths.
Route propagation remains explicit route_step dependency.
K recurrence is loop-carried state, not vendor graph fan-in.
Store follows loop exit / post-loop boundary.
ASM and vendor ABI must not infer tile roles.
```

## Recommended First Patch

The first implementation patch should be intentionally small:

```text
1. Add TileVisibilityRef / TileMicroBlock / TileBlockDependency dataclasses.
2. Add tile_visibility_refs / tile_micro_blocks / tile_block_dependencies tables.
3. Add action_id -> tile_micro_block_id index.
4. Emit one ownership-correct micro-block per existing tile action.
5. Project action dependencies into TileBlockDependency.
6. Add dump output and validation.
7. Do not change ProgramAsm / VendorABI behavior yet.
```

This gives us a visible tile-level truth table before touching lower layers.

Once the dump looks right, downstream lowering can be migrated one layer at a
time.
