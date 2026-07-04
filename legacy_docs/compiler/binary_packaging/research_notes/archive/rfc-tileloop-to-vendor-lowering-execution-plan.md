# RFC: TileLoop-Aware Lowering Execution Plan

Date: 2026-06-14

## Status

`ProcessorTileProgram` now has two complementary views:

```text
analysis view:
  tile_route_actions
  tile_compute_actions
  tile_store_actions
  tile_dependencies
  processor_action_streams

structured sequencing view:
  programs[processor].program_sequence
  tile_loop_regions
```

The current end-to-end pipeline already reaches:

```text
program_vendor_abi_ready_binary_not_started
```

but the lower layers still mostly consume the flat action graph:

```text
ProcessorTileProgram
  -> ProgramNodeProgram
  -> DFUPackingProgram
  -> ProgramAsm
  -> ProgramVendorABI
```

That is useful for analysis and regression safety, but it is not yet the final
TileLoop-aware vendor lowering. The next task is to make `TileLoopRegion` the
authoritative structure for repeated GEMM K bodies.

Important migration boundary:

```text
current lower stack:
  expanded debug / analysis semantics

target lower stack:
  TileLoopRegion is authoritative
  expanded K instances are optional debug views
```

Until the target stack lands, downstream totals such as instance count,
dependency count, and predecessor/successor overflow count should be read as
diagnostic scaffolding rather than final vendor ABI truth.

## Current Program Structure

### `ProcessorTileProgram`

`compiler/gpdpu_compiler/core/program_tile.py` owns the first IR where tile
communication, compute, store, and dependencies are all explicit.

Current GEMM shape:

```text
processor stream:
  TileLoopRegion(wave0, K repeat=4)
  TileLoopRegion(wave1, K repeat=4)
  TileLoopRegion(wave2, K repeat=4)
  TileLoopRegion(wave3, K repeat=4)
  TilePhase(store_sram_tensor)
```

Each `TileLoopRegion` is a closed repeated tile microprogram:

```text
TileLoopRegion:
  loop_axis = "K"
  repeat_count = k_tiles
  fold_policy = "vendor_instance_repeat_candidate"
  carried_refs = [C accumulator view / tile]
  loop_variant_refs = [A[k], B[k], ...]
  body_instances:
    k0:
      route A/B visibility actions
      compute C += A[k0] @ B[k0]
    k1:
      route A/B visibility actions
      compute C += A[k1] @ B[k1]
    ...
```

The body is intentionally not opaque. Every body action still exists in the flat
action tables so validators and debug dumps can inspect route paths, compute
operands, and store dependencies.

### `ProgramNodeProgram`

`program_nodes.py` currently maps every tile action to one backend-facing node:

```text
TileRouteAction   -> ProgramNode(route_materialize)
TileComputeAction -> ProgramNode(tile_compute)
TileStoreAction   -> ProgramNode(tile_store)
TileDependency    -> ProgramEdge(...)
```

This is still correct as an analysis view. It should be extended, not deleted:
nodes should learn which loop region / loop body instance they belong to.

### `DFUPackingProgram`

`program_packing.py` currently packs flat nodes into task/subtask/instance
containers by reading node payloads. It also detects loop-folding candidates.

This is the next place to change. Candidate detection should become structural:

```text
TileLoopRegion -> repeated k_stream subtask
store phase    -> finalize_store subtask
```

The packing pass should not rediscover the loop from node names if
`TileLoopRegion` already states it.

### `ProgramAsm`

`program_asm.py` currently maps packing instances to symbolic assembly blocks
and nodes to symbolic instructions.

This remains the right boundary. The change is that a repeated subtask body
should be represented as a loop body / instance template, not as an accidental
chain of independent K blocks.

### `ProgramVendorABI`

`program_vendor_abi.py` currently projects symbolic assembly into vendor-shaped
task / subtask / instance / exeBlock rows and PC ranges.

This layer should become the place where:

```text
TileLoopRegion.repeat_count
  -> VendorSubtaskRow.instances_amount / instance repeat semantics
```

The ABI projection should not encode K recurrence as ordinary graph edges
between expanded K bodies.

## Key Invariants

### 1. TileLoop Is a Region, Not an Opaque Node

The loop region is a first-class sequencing item, but its body actions remain
visible:

```text
Program sequence sees:
  loop region

Analysis passes see:
  route action
  route action
  compute action
  dependencies
```

This gives us both:

- a clean lowering unit for vendor repeated subtasks;
- inspectable route/compute/store records for validation.

### 2. Loop-Variant Visibility Must Be Inside the Loop

For the current GEMM K loop, A and B tiles vary with `k`, so their visibility
actions belong inside the repeated body:

```text
loop k:
  route/load A[k]
  route/load B[k]
  compute C += A[k] @ B[k]
```

Do not lower this invalid shape:

```text
prologue:
  route/load B once

loop k:
  compute with B[k]
```

unless the producer is proven loop-invariant.

### 3. K Recurrence Is Carried State, Not Vendor Graph Fan-In

Inside a GEMM K loop, this logical relation exists:

```text
C[k+1] = update(C[k], A[k], B[k])
```

But after folding, K instance ordering should be represented by vendor instance
repeat semantics:

```text
one repeated subtask body
instance_times = K
carried accumulator lives across instances
```

It should not become a chain of vendor graph edges:

```text
compute_k0 -> compute_k1 -> compute_k2 -> compute_k3
```

Those edges are useful before folding for debug and closure verification, but
they should be converted into loop-carried state before vendor graph ABI
serialization.

### 4. Route Step Dependencies Stay Real

Route hops are executable communication steps. They should remain ordinary
program dependencies:

```text
route_hop_0 -> route_hop_1 -> route_hop_2 -> compute
```

Do not add extra root/tail dependencies such as:

```text
route_hop_3 also depends on route_hop_0
```

The route chain itself is enough.

### 5. Store Is Post-Loop

Current GEMM tile stores happen after the final K update:

```text
TileLoopRegion(K body)
  -> TileStoreAction(output tile)
```

The store should lower to a post-loop / finalize subtask. The cross-subtask
dependency should mean:

```text
final loop output visible before store
```

not:

```text
store waits for every expanded K instance as separate vendor predecessors
```

## Lowering Plan

### Phase 0: Preserve the Current Flat Analysis Path

Keep the existing action tables and flat node graph alive.

Reason:

- it keeps current tests and dumps stable;
- it gives us a readable audit trail;
- it lets us compare pre-fold and post-fold dependency counts.

Deliverables:

```text
ProcessorTileProgram.to_plan():
  tile_loop_regions present
  program_sequence present
  flat action/dependency tables unchanged
```

Current tests already cover this first checkpoint.

### Phase 1: Add Loop Membership to `ProgramNodeProgram`

Extend node payload/indexing so every node can answer:

```text
am I inside a TileLoopRegion?
which loop region?
which loop body instance?
which role inside the body?
```

Suggested fields:

```text
ProgramNode.payload.loop_region_id
ProgramNode.payload.loop_instance_id
ProgramNode.payload.loop_axis
ProgramNode.payload.loop_role = route | compute | store | relay
ProgramNode.payload.loop_fold_policy
ProgramNode.payload.source_region_path
ProgramNode.payload.debug_origin
```

Also add a loop index:

```text
ProgramNodeProgram.loop_regions:
  loop_id -> {
    source_tile_loop_region
    node_ids_by_instance
    carried_refs
    loop_variant_refs
  }
```

Important: this phase should not change scheduling yet. It only attaches
structure to the existing graph.

Validation:

```text
all TileLoopRegion body action_ids map to ProgramNode ids
each body instance has at least one compute node
loop-variant A/B visibility nodes are inside the same loop instance
route endpoint dependencies still target the compute node
```

### Phase 2: Make Packing Consume TileLoop Structurally

Change `DFUPackingProgram` from heuristic loop detection to structural loop
packing:

```text
for each TileLoopRegion:
  create / reuse task for output tile wave
  create k_stream subtask
  bind body actions to repeated-body container
  record repeat_count
  record carried_refs

for store phase:
  create finalize_store subtask
```

The packing row should make the distinction explicit:

```text
PackingContainer:
  subtask_role = "k_stream"
  repeat_semantics = "vendor_instance_repeat"
  repeat_count = TileLoopRegion.repeat_count
  loop_region_id = ...
  carried_refs = ...
```

The current `PackingInstance` shape can remain as an analysis view:

```text
k0, k1, k2, k3
```

but the packing program should also expose a folded view:

```text
repeated_body_template:
  body_shape is isomorphic across instances
  instance_bindings vary by k
```

Validation:

```text
loop body closure check passes
body instances are isomorphic enough for vendor repeat
all route/compute nodes in a loop are bound to the loop container
K accumulator edges are classified as loop-carried, not normal vendor edges
store edges leave the loop as final-output edges
```

### Phase 3: Legalize Edges for Folded Vendor Semantics

Introduce edge classification before assembly:

```text
normal_graph_edge:
  route step order
  visibility before compute
  store waits for final output

loop_carried_edge:
  compute_k_i -> compute_k_i+1 accumulator recurrence

internal_template_edge:
  route / compute dependencies within one repeated body instance
```

Lowering behavior:

- `normal_graph_edge` becomes ordinary dependency metadata.
- `internal_template_edge` stays inside the repeated subtask body.
- `loop_carried_edge` becomes carried-state metadata and should not become a
  vendor graph predecessor/successor edge.

This phase is the safety valve for the dependency explosion problem.

The pass should emit a visible report:

```text
EdgeLegalizationReport:
  total_edges_before
  normal_graph_edges
  internal_template_edges
  loop_carried_edges
  vendor_edges_after
```

This makes "K recurrence no longer contributes to vendor graph pressure" a
measurable compiler property rather than a hope.

### Phase 4: Lower Packing to Loop-Aware `ProgramAsm`

`ProgramAsm` should continue to be symbolic and inspectable.

For a repeated subtask:

```text
ProgramAsmBlock:
  block_kind = "repeated_body_template"
  loop_region_id = ...
  repeat_count = ...
  instruction_ids = body template instructions
```

There are two possible debug views:

```text
template view:
  one body template with symbolic k binding

expanded debug view:
  k0/k1/k2/k3 views generated from the same template
```

The implementation should prefer template view for semantics, and may keep the
expanded debug view only as derived dump output.

Validation:

```text
instructions in repeated body are instance-isomorphic
only allowed operands vary with loop iv
stage ordering remains LD/CAL/ST-compatible
instruction count fits DFU3500 limits
```

The allowed per-instance variation should be schema-level data:

```text
allowed_variant_fields:
  spm_addr_offset
  base_addr_row
  tile_index
  operand_tag_suffix
  immediate
```

### Phase 5: Project Loop Semantics Into `ProgramVendorABI`

`ProgramVendorABI` should represent repeated subtask semantics directly:

```text
VendorSubtaskRow:
  instances_amount = repeat_count
  role = "k_stream"

VendorInstanceRow:
  either one template plus repeat metadata
  or explicit rows with a shared repeated-body identity
```

`VendorExeBlockRow` should not receive K recurrence as graph fan-in/fan-out.

Graph edge policy:

```text
route and visibility edges inside one body:
  internal or same-exeblock/same-subtask dependencies

store after loop:
  cross_subtask dependency from loop final output to store

K recurrence:
  carried accumulator metadata, not graph edge
```

Validation:

```text
predecessor_overflow_count should drop or become explainable
successor_overflow_count should drop or become explainable
vendor edge counts should not scale with K recurrence chains
task/subtask/instance rows match legacy repeat semantics
```

### Phase 6: Binary Serializers After ABI Is Stable

Only after the symbolic ABI rows are stable should we resume byte serializers:

```text
ProgramVendorABI
  -> task_conf
  -> instance_conf
  -> exeblock rows
  -> graph dependencies
  -> inst_t images
  -> bundle layout
```

Do not start `program_bin.py` by guessing around missing loop semantics. The
binary layer should be boring: it serializes already-decided ABI rows.

Hard gate before `program_bin.py`:

```text
ProgramNode loop membership is stable
PackingContainer repeated_body_template is stable
loop_carried_edge is not emitted as vendor graph edge
VendorSubtaskRow.instances_amount == TileLoopRegion.repeat_count
store depends on LoopRegionExitToken / loop final output, not every K instance
predecessor/successor pressure no longer scales with K recurrence chains
```

## Concrete Implementation Order

### Step 1: Loop Membership Annotation

Files:

```text
compiler/gpdpu_compiler/core/program_nodes.py
tests/test_chip_program_frontend.py
```

Add loop membership fields to node payloads and dumps.

Also add `source_region_path` / `debug_origin` for reverse tracing:

```text
vendor row
  -> asm block
  -> packing container
  -> program node
  -> tile action
  -> tile loop region
```

Expected result:

```text
flat totals unchanged
ProgramNode can trace back to TileLoopRegion
```

### Step 2: Structural Packing

Files:

```text
compiler/gpdpu_compiler/core/program_packing.py
tests/test_chip_program_frontend.py
```

Replace / downgrade heuristic `loop_folding_candidates` with TileLoop-driven
records.

Expected result:

```text
loop_folding_candidate_count == tile_loop_region_count
packing rows name loop_region_id
```

### Step 3: Edge Legalization

Files:

```text
compiler/gpdpu_compiler/core/program_packing.py
compiler/gpdpu_compiler/core/program_asm.py
docs/compiler/binary_packaging/research_notes/archive/vendor_abi_dependency_granularity.md
```

Classify accumulator recurrence edges as loop-carried.

Expected result:

```text
K recurrence no longer contributes to vendor predecessor/successor pressure
route/store dependencies remain visible
EdgeLegalizationReport is dumpable
```

### Step 4: Loop-Aware Symbolic ASM

Files:

```text
compiler/gpdpu_compiler/core/program_asm.py
tests/test_chip_program_frontend.py
```

Add repeated-body metadata to asm blocks and symbolic instructions.

Expected result:

```text
k_stream block is explicitly a repeated-body template
allowed per-instance operands are listed
```

### Step 5: Loop-Aware Vendor ABI

Files:

```text
compiler/gpdpu_compiler/core/program_vendor_abi.py
tests/test_chip_program_frontend.py
```

Project repeated-body metadata into subtask / instance / exeBlock rows.

Expected result:

```text
VendorSubtaskRow.instances_amount follows TileLoopRegion.repeat_count
vendor graph edges do not encode K recurrence chains
```

### Step 6: Serializer RFC / Implementation

Files:

```text
compiler/gpdpu_compiler/core/program_bin.py
docs/compiler/binary_packaging/research_notes/archive/rfc-program-bin-serializer.md
```

Start this only after the previous symbolic ABI tests are stable.

## Testing Strategy

Use the current frontend test as the main spine:

```text
pytest -q tests/test_chip_program_frontend.py
```

Then run the full suite:

```text
pytest -q
```

Add checks gradually:

```text
TileLoopRegion exists and is closed
ProgramNode has loop membership
PackingContainer has loop repeat metadata
loop-carried edges are not vendor graph edges
VendorSubtaskRow repeat count matches TileLoopRegion.repeat_count
store dependency crosses from loop final output to finalize store
```

## Open Questions

### Does Vendor Repeat Repeat the Whole Subtask Body?

Legacy evidence suggests yes: A visibility, A COPYT, B load, and compute all
live in the repeated K subtask. Before byte serialization, re-check the exact
vendor row fields so we do not accidentally repeat each exeBlock independently
instead of the whole body.

Before byte serialization, run a small `RepeatSemanticsProbe` against legacy
rows and confirm:

```text
for k in K:
  execute whole subtask body:
    route A/B
    copy A
    load B
    compute
```

The dangerous alternative is:

```text
execute route block K times
then execute compute block K times
```

### Should `ProgramAsm` Keep Expanded Debug Blocks?

Template semantics are cleaner. Expanded debug blocks are useful for comparing
against the current flat dumps. If both are kept, mark one as authoritative.

Recommended:

```text
authoritative = template view
debug_only = expanded instance view
```

### When To Add Multi-Accumulator Grouping?

Not now. First make single-accumulator `TileLoopRegion` lower correctly to
vendor repeat. Then add multi-accumulator grouping as an optional optimization:

```text
group_size 4 -> 2 -> 1 fallback
```

The fallback must preserve semantics.

Multi-accumulator grouping requires:

```text
loop-aware ProgramVendorABI stable
single-accumulator folded ABI equivalent to legacy
capacity checker can reject unsafe grouping
```

## Recommended Next Action

Start with `program_nodes.py`.

Add loop membership without changing node/edge counts. This is the lowest-risk
bridge from the new `program_tile.py` structure into the existing lower stack.
Once every route/compute node knows its `loop_region_id` and `loop_instance_id`,
`program_packing.py` can stop rediscovering GEMM K loops from naming patterns
and can consume the TileLoop structure directly.
