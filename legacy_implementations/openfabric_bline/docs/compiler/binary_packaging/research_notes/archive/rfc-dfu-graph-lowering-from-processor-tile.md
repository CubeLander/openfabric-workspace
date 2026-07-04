# RFC: Lower `ProcessorTileProgram` Into `ProgramNodeProgram`

Date: 2026-06-14

## Status

Initial implementation landed in `compiler/gpdpu_compiler/core/program_nodes.py`.
Initial packing implementation landed in
`compiler/gpdpu_compiler/core/program_packing.py`.

Current generated status is:

```text
program_vendor_abi_ready_binary_not_started
```

The next discussion should focus on
`ProgramVendorABI -> binary serializers / inst_t encoding`.

## Goal

The next lowering boundary should be:

```text
ProcessorTileProgram
  -> ProgramNodeProgram
```

`ProgramNodeProgram` is not a generic compiler graph. Its purpose is to become the
first DFU/backend view whose form is intentionally close to the vendor binary
packing model:

```text
ProgramNodeProgram
  -> DFUPackingProgram
  -> ProgramAsm
  -> ProgramVendorABI
  -> vendor task / subtask / instance / exeBlock rows
  -> simulator binary component serializers
```

So this step is binary-oriented, but still layered. We should not jump directly
from tile IR to `insts_file.bin`; graph, packing, ABI projection, and serializers
must remain explicit and separately dumpable.

## Current Tile Input Surface

The new `ProcessorTileProgram` already owns the facts that legacy had to
rediscover from several later views:

```text
tile_route_actions
tile_compute_actions
tile_store_actions
tile_dependencies
processor_action_streams
```

For the current GEMM+ReLU shape, the expected tile totals are:

```text
tile_route_action_count = 512
tile_compute_action_count = 256
tile_store_action_count = 64
processor_tile_action_count = 832
tile_dependency_count = 1280
```

Important interpretation:

- `TileRouteAction` is source-side push. `execution_processor` is the sender
  where COPY/COPYT-like code should execute; `endpoint_processor` is where the
  visibility endpoint is produced.
- `TileComputeAction` is one tile-local compute step. GEMM currently emits one
  action per `(processor, output_tile, k_block)`.
- `TileStoreAction` is now one output tile store action, not one whole-processor
  store. A store phase may group several store actions for readability, but the
  graph-facing store unit is per output tile.
- `TileDependency` already records route-step, visibility-before-compute,
  accumulator-chain, generic compute, and store dependencies.

## Why Legacy Had More Intermediate Views

Legacy used this approximate path:

```text
tile_backend
  -> route_lowering
  -> architecture_backend
  -> assembly_backend
  -> global_tile_dependency_network
  -> dfu_graph
```

That made sense when tile phases did not directly own route actions and tile
dependencies. The refactored path should be shorter:

```text
ProcessorTileProgram
  -> ProgramNodeProgram
```

Route planning must not be rederived here. The graph builder consumes
`TileRouteAction` rows as truth.

## Proposed ProgramNodeProgram Shape

```text
ProgramNodeProgram:
  schema_version
  backend = "dfu_node_program"
  source_ir = "processor_tile_program"
nodes: dict[str, ProgramNode]
edges: dict[str, ProgramEdge]
  per_processor_nodes: dict[str, list[str]]
  per_processor_edges: dict[str, list[str]]
  action_to_node: dict[str, str]
  source_tile_dependency_to_edge: dict[str, str]
  totals
```

### Node

```text
ProgramNode:
  id
  node_kind
  processor
  source_action_id
  source_action_kind
  source_phase_id
  tile_refs
  payload
```

Suggested node kinds:

```text
route_materialize
tile_compute
tile_store
```

Legacy names were:

```text
tile_collective_action
tile_op
store_tile
```

The new names can be cleaner, but the mapping should be documented because
vendor packing still cares about the same roles.

### Edge

```text
ProgramEdge:
  id
  edge_kind
  src_node
  dst_node
  src_processor
  dst_processor
  source_tile_dependency_id
  payload
```

Suggested edge kinds:

```text
route_step_order
visibility_dependency
value_dependency
accumulator_dependency
store_dependency
```

The first implementation may use fewer edge kinds if it keeps the original
`TileDependency.dependency_kind` in payload, but it should preserve enough
semantic information for packing and graph ABI review.

## Mapping Rules

### Route Actions

Each `TileRouteAction` becomes one `route_materialize` node.

```text
TileRouteAction.id
  -> ProgramNode(node_kind="route_materialize")
```

Node processor:

```text
processor = TileRouteAction.execution_processor
```

Important: the graph node executes on the sender/source processor. The produced
visibility endpoint belongs to `endpoint_processor` and should remain in the
node payload:

```text
payload.endpoint_processor
payload.produces_endpoint_ref
payload.src_processor
payload.dst_processor
```

This keeps the sender-push DFU behavior visible for later COPY/COPYT lowering.

### Compute Actions

Each `TileComputeAction` becomes one `tile_compute` node.

```text
TileComputeAction.id
  -> ProgramNode(node_kind="tile_compute")
```

Node processor:

```text
processor = TileComputeAction.processor
```

For GEMM, payload should keep:

```text
compute_kind = "gemm_k_update"
wave_id
k_index
task_id
launch_group_id
a_tile
b_tile
member_value_ref
accumulator_view_ref
```

The later assembly/template pass should consume this node to pick the
`summa_gemm_64x64x64_fp16` instruction template.

### Store Actions

Each `TileStoreAction` becomes one `tile_store` node.

```text
TileStoreAction.id
  -> ProgramNode(node_kind="tile_store")
```

Node processor:

```text
processor = TileStoreAction.processor
```

The payload must carry:

```text
dst_sram_tensor_id
dst_region
source_final_tile.tile_ref
source_final_tile.global_m / global_n
source_final_tile.uses_padding
store_index
```

This is the critical fix before program-node lowering: store is already per output
tile, so the graph and later vendor store records do not need to guess how to
split a processor-level store.

## Dependency Mapping

Every `TileDependency` should map to a graph edge when both endpoints have graph
nodes.

Examples:

```text
tile_route_step_dependency:
  route_materialize -> route_materialize

tile_visibility_endpoint_before_compute:
  route_materialize -> tile_compute

tile_compute_accumulator_chain:
  tile_compute(k_i) -> tile_compute(k_i+1)

tile_value_before_compute:
  tile_compute -> tile_compute

tile_value_before_store:
  tile_compute -> tile_store
```

Some tile dependencies may use tile refs rather than action ids, especially for
source-local availability. The graph builder should classify these as either:

```text
external_input_value
```

or preserve them as node payload preconditions rather than graph edges. Do not
invent fake graph nodes unless packing needs them.

## Expected GEMM+ReLU First Milestone

The first implementation does not need to match every legacy count. It should
prove these invariants:

```text
route node count == tile_route_action_count
compute node count == tile_compute_action_count
store node count == tile_store_action_count
all tile action ids map to graph nodes
all graphable tile dependencies map to graph edges
per_processor_nodes are non-empty for all 16 processors
graph is acyclic
store nodes depend on final per-output-tile compute nodes
compute nodes depend on local visibility endpoints for A/B
```

Current expected node count from new tile IR:

```text
route_materialize = 512
tile_compute = 256
tile_store = 64
total = 832
```

This differs from legacy `dfu_graph`:

```text
legacy route/collective graph nodes = 512
legacy tile_op graph nodes = 384
legacy store graph nodes = 64
legacy total = 960
```

The difference is mostly because legacy represents additional finalize/assemble
tile ops separately. The new graph can initially keep GEMM post-op/finalize
inside compute payload, matching the current tile-layer transition state. If we
later introduce first-class tile op chains for generic fusion, those finalize
and post-op nodes should appear naturally.

## What Comes After ProgramNodeProgram

Once graph lowering is stable, the following legacy concepts can be reused or
adapted:

```text
ProgramNodeProgram
  -> DFUPackingProgram
  -> DFUResidencyProgram
  -> DFUStorageBindingProgram
  -> DFURuntimeFrameProgram
  -> DFUAssemblyAttachmentProgram
  -> DFUBaseTableProgram
  -> VendorAlignedPacking
  -> VendorExeBlock / Instance / GraphABI
  -> VendorSerializers
```

The ordering of `assembly` deserves one more discussion:

- Legacy creates symbolic assembly before global tile dependency network.
- Refactor can build program-node graph first, then attach assembly templates to graph
  nodes.

Preferred new direction:

```text
ProcessorTileProgram
  -> ProgramNodeProgram
  -> DFUPackingProgram
  -> ProgramAsm
  -> ProgramVendorABI
  -> Vendor ABI + binary serializers
```

This keeps the graph topology independent from instruction template expansion,
while still moving toward binary quickly.

## Implementation Plan

1. Create `compiler/gpdpu_compiler/core/program_nodes.py`. Done.
2. Define dataclasses. Done:
   - `ProgramNode`
   - `ProgramEdge`
   - `ProgramNodeProgram`
3. Implement. Done:
   - `lower_processor_tile_to_program_nodes(tile_program)`
4. Add `ChipEnv.generate()` output key. Done:
   - `program_nodes`
5. Add tests on GEMM+ReLU. Done:
   - node totals,
   - store dependency shape,
   - route sender/endpoint metadata,
   - acyclicity,
   - per-processor indexes.
6. Create `compiler/gpdpu_compiler/core/program_packing.py`. Done:
   - `DFUPackingProgram`
   - `PackingTask`
   - `PackingContainer`
   - `PackingInstance`
   - node and edge binding tables
7. Add `ChipEnv.generate()` output key. Done:
   - `dfu_packing_program`
8. Keep legacy count comparison as guidance, but do not require exact node
   count parity. Packing container/instance shape now aligns with legacy
   GEMM+ReLU: 4 tasks, 128 containers, 320 instances.
9. Create `compiler/gpdpu_compiler/core/program_asm.py`. Done:
   - one `PackingInstance` maps to one symbolic asm block
   - one `ProgramNode` maps to one symbolic instruction
   - node dependencies map to symbolic instruction dependencies
   - `inst_t` byte encoding is explicitly not started

## Non-Goals For This Step

- Do not serialize binary component files directly from `ProcessorTileProgram`.
- Do not rederive route paths from collective bundles.
- Do not solve generic fusion op-chain yet.
- Do not require exact legacy node count parity before packing.
- Do not encode RTL 8-byte instructions.
