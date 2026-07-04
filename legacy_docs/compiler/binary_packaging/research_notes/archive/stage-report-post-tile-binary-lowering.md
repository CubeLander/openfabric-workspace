# Stage Report: Post-Tile Binary Lowering After Core Refactor

Date: 2026-06-13

## Executive Summary

The new `core` frontend has pushed several formerly post-tile concerns earlier
into explicit IR:

- `ChipProgram` now owns SRAM tensor declarations, offsets, load/store
  boundaries, and DTensor-level compute intent.
- `ProcessorLogicalProgram` now owns processor-local values, shard-level
  logical routes, route steps, and shard-level dependencies.
- `ProcessorTileProgram` now owns first-class tile route / compute / store
  actions and tile dependencies.

This means the old legacy split:

```text
tile_backend -> route_lowering -> assembly_backend -> global_tile_dependency_network
```

should not be copied literally into the refactored path. The communication
planning part of `route_lowering` has largely moved forward into:

```text
ProcessorLogicalProgram.logical_routes
ProcessorTileProgram.tile_route_actions
ProcessorTileProgram.tile_dependencies
```

The remaining work after tile level is now mostly DFU/backend projection:

```text
ProcessorTileProgram
  -> DFUGraph
  -> DFUPacking / residency / storage / runtime frame
  -> vendor ABI projections
  -> serializers / simulator bundle files
```

## Legacy Post-Tile Binary Path

The legacy `OperatorEnv.to_plan()` pipeline is defined in
`compiler/gpdpu_compiler/core_legacy/env.py`.

The relevant order is:

```text
build_tile_backend_plan
build_route_lowering_plan
build_architecture_backend_plan
build_assembly_backend_plan
build_global_tile_dependency_network
build_dfu_graph_skeleton
build_dfu_packing_plan
build_dfu_residency_plan
build_dfu_storage_binding_plan
build_dfu_runtime_frame_plan
build_dfu_assembly_attachment_plan
build_dfu_base_table_plan
build_dfu_vendor_package_layout_plan
build_dfu_vendor_blob_schema_plan
build_dfu_vendor_aligned_packing_plan
build_dfu_vendor_exeblock_plan
build_dfu_vendor_instance_plan
build_dfu_vendor_base_addr_plan
build_dfu_vendor_instruction_offset_plan
build_dfu_vendor_offset_field_audit_plan
build_dfu_vendor_instruction_folding_plan
build_dfu_vendor_instruction_range_plan
build_dfu_vendor_noncompute_range_plan
build_dfu_vendor_concrete_base_addr_plan
build_dfu_vendor_instance_conf_serializer_plan
build_dfu_vendor_task_conf_serializer_plan
build_dfu_vendor_graph_abi_plan
build_dfu_vendor_exeblock_conf_serializer_plan
build_dfu_vendor_subtask_conf_serializer_plan
build_dfu_vendor_inst_serializer_plan
build_dfu_vendor_simulator_bundle_plan
emit_dfu_vendor_component_files
emit_dfu_vendor_final_blobs
```

For the current legacy GEMM+ReLU plan, the observed major counts are:

```text
tile_backend:
  tile_programs = 16
  collective_bundles = 128

route_lowering:
  routes = 128
  physical_instruction_route_count = 0

architecture_backend:
  template_count = 1
  instance_count = 256
  expanded_instruction_count = 147456

assembly_backend:
  compute_records = 256
  route_edge_records = 384
  store_records = 64
  assembly_records = 704

global_tile_dependency_network:
  tile_ops = 576
  tile_values = 640
  local_deps = 1344
  collective_deps = 640

dfu_graph:
  nodes = 960
  edges = 896
  node_counts = tile_collective_action:512, tile_op:384, store_tile:64

dfu_packing:
  tasks = 4
  containers = 128
  instances = 320

vendor projection:
  vendor_exeblocks = 256
  vendor_instance_rows = 24
  vendor_graph_rows = 256
  vendor_graph_edges = 192
  instance_visibility_obligations = 384

serializers:
  inst_t rows = 37312 active / 69632 padded
  exeBlock_conf rows = 256 active / 512 padded
  instance_conf rows = 24 active / 65536 padded
  task_conf rows = 4 active / 4 padded
  subtask_conf rows = 12 active / 32 padded
```

The final writer currently emits simulator long-struct blobs:

```text
simulator_bin/insts_file.bin
simulator_bin/exeblock_conf_info_file.bin
simulator_bin/instance_conf_info_file.bin
simulator_bin/tasks_conf_info_file.bin
simulator_bin/subtasks_conf_info_file.bin
config/cbuf_file.bin
config/micc_file.bin
```

It still treats RISC-V host program and input data as external/future runtime
package files.

## What Legacy Did After Tile Level

### 1. Route Lowering

Legacy `tile_backend` emits logical `CollectiveBundle` rows. Then
`route_lowering` chooses stable mesh-line fanout paths. It deliberately stops
before physical COPY/COPYT instruction generation:

```text
collective_bundles -> routes
```

In GEMM+ReLU:

- 128 tile collective bundles become 128 routes.
- Each route has 3 physical mesh edges, producing 384 route edge records later.
- The route pass is architecture-independent and uses stable broadcast anchors.

### 2. Architecture Template Expansion

`architecture_backend` expands semantic tile phases into target-owned symbolic
instruction templates.

For GEMM:

- One template: `legacy_dfu:summa_gemm_64x64x64_fp16:64x64x64`.
- 256 GEMM k-update instances.
- Naive expansion: 147456 instruction records.

This layer is route-independent. It describes the compute template; it does
not encode final simulator component files.

### 3. Assembly Records

`assembly_backend` combines:

- compute template instances,
- route edge records,
- store tile records.

It creates structured symbolic assembly payloads, not final vendor binaries.
The later vendor passes consume these payloads for PC ranges, base-address
offsets, and instruction serialization.

### 4. Global Tile Dependency Network

Legacy then rebuilds a tile-level dependency truth surface by combining:

- tile_backend phases,
- route_lowering routes,
- assembly_backend records.

This is a key reason we refactored: the old pipeline discovered important tile
dependencies only after route and assembly views existed. In the new pipeline,
route and tile dependencies should already be explicit in `ProcessorTileProgram`.

### 5. DFU Graph / Packing / Runtime Model

Legacy turns tile dependencies into DFU graph nodes and then groups them into
runtime containers:

```text
tile dependency network
  -> dfu_graph nodes/edges
  -> dfu_packing tasks/subtasks/instances/containers
  -> residency/storage/runtime frame/base table
```

This layer answers:

- which graph nodes exist per PE,
- which graph edges are executable dependencies,
- how nodes are grouped into tasks/subtasks/instances,
- where tile values symbolically reside,
- what base address symbols are needed.

### 6. Vendor ABI Projection And Serializers

Legacy projects OpenFabric/DFU containers into the vendor ABI:

```text
dfu_packing + base table
  -> vendor aligned packing
  -> vendor exeBlock rows
  -> vendor instance rows
  -> vendor graph ABI rows/edges
  -> concrete base_addr values
  -> inst/task/subtask/exeBlock/instance serializers
  -> component files
  -> cbuf/micc blobs
```

This is where most simulator-binary-specific work lives.

## What The Refactor Already Moved Earlier

### SRAM Boundary

Legacy `OperatorEnv.input/output` modeled abstract tensors and output bindings.
The new `ChipEnv` explicitly declares SRAM tensors with region/offset and
forces data movement through chip-level load/store:

```text
declare_sram_tensor
load_sram_tensor
compute
store_sram_tensor
```

This moves an important base-address/runtime-package concern from late vendor
passes into the source-visible chip program.

### Shard-Level Logical Route Program

Legacy `route_lowering` derives route paths from tile collective bundles after
tile lowering.

The new `ProcessorLogicalProgram` already records logical route edges and route
steps at shard level:

```text
LogicalRouteEdge
  route_steps[]
  endpoint_by_processor
  logical_dependencies[]
```

For the current GEMM shape, this is:

```text
8 logical routes
32 logical route steps
64 logical dependencies
```

This is coarser than legacy's 128 tile routes, but it has the correct semantic
shape: a shard-level route program that tile lowering expands.

### Tile-Level Route Actions

Legacy route edges are created after `route_lowering` and become assembly
records later.

The new `ProcessorTileProgram` already expands logical route steps into tile
route actions:

```text
TileRouteAction
  execution_processor  # sender/source side
  endpoint_processor   # receiver/visibility endpoint
  depends_on
```

The sender-push DFU behavior is now documented directly in the tile route
action model. For GEMM+ReLU, current new tile IR has:

```text
tile_route_action_count = 512
tile_compute_action_count = 256
tile_store_action_count = 64
processor_tile_action_count = 832
tile_dependency_count = 1280
```

The count difference from legacy is intentional:

- legacy route assembly records count mesh hop edges only: 128 routes * 3 hops
  = 384 route edge records;
- new tile route actions include the source-local visibility step too:
  128 routes * 4 route steps = 512 tile route actions.

### Tile Compute / Store Actions

Legacy `tile_backend` mostly stores phase payloads. Later graph/network passes
recover tile ops and store dependencies.

The new `ProcessorTileProgram` has first-class:

```text
TileComputeAction
TileStoreAction
ProcessorTileActionStream
TileDependency
```

GEMM k-updates now explicitly depend on A/B visibility endpoints and on the
previous accumulator update. Store actions are now also expanded per output
tile: each `TileStoreAction` depends on one final tile compute action and
carries the output tile ref / coordinate that DFU graph and vendor store
lowering should consume. A store phase may still group multiple store actions
for readability, but the graph-facing unit is the per-tile `TileStoreAction`.

## What Should Not Be Repeated In The New Backend

Do not reintroduce an independent `route_lowering` pass that rediscovers route
paths from tile collectives after the fact.

In the refactored model:

```text
ProcessorLogicalProgram.logical_routes
  -> ProcessorTileProgram.tile_route_actions
```

is already the route lowering surface.

A later DFU backend may still create a view named something like:

```text
DFURouteInstructionPlan
```

but that pass should consume `TileRouteAction` rows and attach DFU COPY/COPYT
templates. It should not choose the semantic route path again unless the target
requires a physical remapping step.

## Remaining Tasks After Refactored Tile Level

### Task 1: Build New DFU Graph From ProcessorTileProgram

Input:

```text
ProcessorTileProgram.tile_route_actions
ProcessorTileProgram.tile_compute_actions
ProcessorTileProgram.tile_store_actions
ProcessorTileProgram.tile_dependencies
ProcessorTileProgram.processor_action_streams
```

Output:

```text
ProgramNodeProgram
  nodes
  edges
  per_processor_nodes
  per_processor_edges
```

This should replace the legacy combination:

```text
tile_backend + route_lowering + assembly_backend
  -> global_tile_dependency_network
  -> dfu_graph
```

The new graph builder can be much cleaner because tile action/dependency facts
already exist.

### Task 2: Rebuild DFU Packing Against New Graph

Legacy packing is still useful conceptually:

```text
dfu_graph -> tasks/subtasks/instances/containers
```

But it currently depends on legacy node kinds and IDs. We need a new adapter or
new implementation that consumes the refactored graph node model.

Expected GEMM target shape can initially match legacy:

```text
task_count = 4
container_count ~= 128
instance_count ~= 320
```

Exact equality is not required until we intentionally target legacy-compatible
binary layout. But the initial milestone should reproduce the same DFU
structural roles:

```text
k_stream
finalize_store
materialize_route / visibility
```

### Task 3: Attach DFU Assembly Templates

Legacy has one good compute template:

```text
legacy_dfu:summa_gemm_64x64x64_fp16
```

The new backend should consume `TileComputeAction(compute_kind=gemm_k_update)`
and emit equivalent symbolic instruction records.

Route/store still need real attention:

- route actions should lower to COPY/COPYT-like source-side push records;
- store actions should lower to store/writeback records;
- current legacy noncompute records are placeholders for route/store in the
  inst serializer path.

### Task 4: Port Or Adapt Runtime Frame / Base Table Passes

The old passes are still valuable:

```text
dfu_residency
dfu_storage_binding
dfu_runtime_frame
dfu_base_table
```

They should be adapted after the new graph/packing shape stabilizes. Because
the new frontend already has explicit SRAM offsets, this layer should consume
chip-level SRAM tensor regions rather than infer all roots from abstract input
names.

### Task 5: Reuse Vendor ABI Projection Where Possible

These passes are backend/vendor ABI concerns and should remain after graph and
packing:

```text
dfu_vendor_aligned_packing
dfu_vendor_exeblock
dfu_vendor_instance
dfu_vendor_graph_abi
dfu_vendor_instruction_range
dfu_vendor_noncompute_range
```

They probably need adapters for new IDs and node kinds, but their concepts are
still valid.

### Task 6: Reuse Serializers After Inputs Are Adapted

The byte serializers are late-stage and relatively narrow:

```text
dfu_vendor_inst_serializer
dfu_vendor_instance_conf_serializer
dfu_vendor_task_conf_serializer
dfu_vendor_exeblock_conf_serializer
dfu_vendor_subtask_conf_serializer
dfu_vendor_component_file_writer
dfu_vendor_final_blob_writer
```

They should be reused as much as possible once the new vendor ABI plans match
their expected row surfaces.

### Task 7: Keep Bundle Runtime Gaps Explicit

Even when simulator binary files are emitted, the runtime package is not fully
standalone unless we also handle:

```text
RISC-V host program
input data / answer data
test launch scripts
CASE/source layout expectations
```

For current customer testing, the practical bundle path may still build host
code on the customer machine and use local SimICT runtime files. This is
separate from core binary lowering.

## Suggested Next Implementation Order

1. Add a new `core/dfu_graph.py` that consumes `ProcessorTileProgram`.
2. Create a compatibility dump comparing new graph counts with legacy graph
   counts for GEMM/GEMM+ReLU.
3. Add a small adapter from new `ProgramNodeProgram` into legacy `dfu_packing`
   shape, only if this is faster than rewriting packing.
4. Once packing is stable, feed legacy residency/storage/runtime/base-table
   passes through an adapter.
5. Reuse vendor ABI and serializer passes with minimal row-shape adapters.
6. Only after simulator blobs match structurally, tighten binary equivalence
   against legacy GEMM artifacts.

## Current Status

Tile-level modeling is basically complete enough for the next backend step:

```text
ChipProgram
  -> ProcessorLogicalProgram
  -> ProcessorTileProgram
```

The current refactor milestone has moved forward to:

```text
ProcessorTileProgram
  -> ProgramNodeProgram
  -> DFUPackingProgram
  -> ProgramAsm
  -> ProgramVendorABI
```

`ProgramNodeProgram` is implemented in
`compiler/gpdpu_compiler/core/program_nodes.py`, and initial DFU task/subtask/
instance packing is implemented in `compiler/gpdpu_compiler/core/program_packing.py`.
Symbolic assembly is implemented in `compiler/gpdpu_compiler/core/program_asm.py`.
Symbolic vendor ABI projection is implemented in
`compiler/gpdpu_compiler/core/program_vendor_abi.py`.
The new graph and packing builders no longer rediscover route paths or infer
compute/store dependencies from phase payloads. They consume explicit tile
actions and explicit dependencies directly.

For current GEMM+ReLU, the new packing shape is:

```text
task_count = 4
container_count = 128
instance_count = 320
node_binding_count = 832
edge_binding_count = 1152
loop_folding_candidate_count = 64
```

The current GEMM+ReLU symbolic assembly shape is:

```text
block_count = 320
instruction_count = 832
dependency_count = 1152
LD = 512
CAL = 256
ST = 64
```

The current GEMM+ReLU symbolic vendor ABI shape is:

```text
vendor_task_count = 4
vendor_subtask_count = 8
vendor_instance_count = 20
vendor_exeblock_count = 320
instruction_range_count = 560
vendor_graph_edge_count = 896
assigned_instruction_count = 832
predecessor_overflow_count = 48
successor_overflow_count = 64
```

The non-zero predecessor/successor overflow counts are intentional visibility
into the remaining serializer hazard: the current symbolic graph can exceed the
vendor edge slot budget if emitted mechanically. The binary layer must either
fold/split rows or encode those dependencies through the correct vendor-side
mechanism before bytes are emitted.

The next real compiler milestone is now:

```text
ProgramVendorABI
  -> binary serializers
```
