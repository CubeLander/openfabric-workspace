# Stage Report: Folded TileLoop Vendor Repeat

Date: 2026-06-14

## Executive Summary

The refactored DFU path has reached a meaningful backend milestone:

```text
ProcessorTileProgram
  -> ProgramNodeProgram
  -> DFUPackingProgram
  -> ProgramAsm
  -> folded ProgramVendorABI
```

The important change is that `TileLoopRegion` is no longer only debug metadata.
The vendor ABI layer now consumes loop structure and emits a folded repeated
subtask schedule:

```text
TileLoopRegion(repeat_count=K)
  -> one k_stream subtask body template
  -> VendorSubtaskRow.instances_amount = K
```

Expanded `k0..kN` bodies are still preserved in Packing / ASM as inspectable
debug views, but `ProgramVendorABI` no longer emits all K-expanded k-stream
exeBlocks.

## Current Layer Responsibilities

### ProcessorTileProgram

`ProcessorTileProgram` is the semantic truth layer for tile execution:

- Tile route / compute / store actions are explicit.
- Tile dependencies are explicit.
- `TileLoopRegion` describes repeated GEMM K bodies.
- `TileMicroBlock` partitions tile actions into executable units.

Key invariant:

```text
TileLoopRegion decides what repeats.
TileMicroBlock decides the executable block boundary inside the repeated body.
```

This prevents later backend layers from re-guessing route ownership or
accumulator recurrence.

### ProgramNodeProgram

`ProgramNodeProgram` mirrors tile actions as backend graph nodes while
preserving:

- loop membership,
- source tile action identity,
- micro-block identity,
- debug origin path.

It remains expanded for analysis. It is not yet a vendor binary ABI.

### DFUPackingProgram

`DFUPackingProgram` maps nodes into task / processor / subtask / instance
containers.

It now records two views:

```text
expanded_debug_instances:
  k0, k1, k2, k3 are all visible for inspection

repeated_loop_templates:
  k0 is used as the canonical repeated body template
```

The repeated template is still metadata at this layer. This is intentional:
Packing remains easy to debug and can still explain every expanded K instance.

### ProgramAsm

`ProgramAsm` keeps the expanded debug assembly:

- one `ProgramAsmBlock` per `TileMicroBlock`,
- one symbolic instruction per `ProgramNode`,
- K-expanded instructions remain visible.

This makes it possible to diff, inspect, and validate loop isomorphism before
vendor ABI folding.

### ProgramVendorABI

`ProgramVendorABI` is now the first folded vendor-facing layer.

For `k_stream` subtasks:

```text
emit only template instance k0 exeBlocks
set instances_amount = TileLoopRegion.repeat_count
mark repeat_semantics = vendor_instance_repeat_whole_subtask_body
```

For `finalize_store` subtasks:

```text
emit normal single-pass store exeBlocks
```

Cross-subtask store ordering is currently absorbed by vendor subtask order. The
expanded `compute_k_last -> store` dependency remains visible in ASM as debug
evidence, but it is not emitted as a folded VendorABI graph edge.

## Confirmed Vendor Repeat Semantics

Vendor repeat has been confirmed to execute the whole subtask body per
instance:

```text
for k in 0..K-1:
  execute whole subtask body template for k
```

This is the condition that makes folded `VendorSubtaskRow.instances_amount`
safe. If repeat were per-exeBlock rather than whole-subtask-body, this lowering
would be invalid.

Evidence and checks:

| Evidence item | Observed field / location | Conclusion |
| --- | --- | --- |
| Repeat count is stored on subtask row | `VendorSubtaskRow.instances_amount` / legacy `subtasks_conf.instances_amount` | Repeat is a subtask-level property, not a per-PE local counter. |
| Active body is described by subtask valid exeBlocks | `VendorSubtaskRow.valid_exeblock_ids`, `valid_exe_blocks` | A subtask owns a body made of multiple exeBlocks. |
| PE-specific work lives in exeBlock rows | legacy `dfu_vendor_aligned_packing.py` notes: `PE-specific differences live in exeBlock rows` | Multiple PE-local exeBlocks participate in one subtask body. |
| Instance rows are shared by subtask | legacy notes: `vendor_instance_rows_are_global_subtask_instance_rows_shared_by_all_pes` | Instances select repeated subtask iterations, not isolated exeBlock repeats. |
| Serializer writes subtask `instances_amount` separately from embedded exeBlocks | legacy `dfu_vendor_subtask_conf_serializer.py` offsets include `instances_amount` and `exeBlocks_conf_info` | Repeat count and body exeBlocks are encoded as separate subtask-level facts. |
| Current folded ABI keeps `k0` exeBlocks and sets `instances_amount = 4` | `ProgramVendorABI.vendor_subtasks[...].repeat_semantics` | The emitted schedule matches whole-subtask-body repeat. |

The remaining binary RFC must still pin down how each instance selects its
variant address / base-row / immediate fields.

## Current GEMM Counts

For the current GEMM+ReLU example:

```text
ProcessorTileProgram:
  tile_route_action_count       = 512
  tile_compute_action_count     = 256
  tile_store_action_count       = 64
  tile_micro_block_count        = 832
  tile_loop_region_count        = 64

ProgramAsm:
  block_count                   = 832
  symbolic_instruction_count    = 832
  dependency_count              = 1152
  k_stream blocks               = 768
  finalize_store blocks         = 64

ProgramVendorABI:
  vendor_exeblock_count         = 256
  instruction_range_count       = 256
  vendor_graph_edge_count       = 224
  vendor_instance_template_rows = 8
  k_stream exeBlocks            = 192
  finalize_store exeBlocks      = 64
  predecessor_overflow_count    = 0
  successor_overflow_count      = 0
```

The key compression is:

```text
expanded ASM k_stream blocks:
  768

folded VendorABI k_stream exeBlocks:
  192
```

That is exactly the intended boundary:

```text
debug layers stay expanded
vendor ABI emits folded repeated subtask rows
```

`vendor_instance_template_rows = 8` counts symbolic `VendorInstanceRow`
records, not expanded logical K iterations. Effective repeated execution is
represented by each k-stream `VendorSubtaskRow.instances_amount`.

`ProgramAsm.symbolic_instruction_count = 832` is also a symbolic row count: one
record per `ProgramNode`. It is not the final expanded `inst_t` count.

## FoldedVendorReport

`ProgramVendorABI` now emits an explicit `folded_vendor_report` so binary
lowering does not have to infer which expanded edges were absorbed:

```text
expanded_asm_block_count                         = 832
expanded_k_stream_block_count                    = 768
folded_vendor_exeblock_count                     = 256
folded_k_stream_exeblock_count                   = 192

expanded_asm_dependency_count                    = 1152
expanded_vendor_graph_eligible_dependency_count  = 960
emitted_vendor_graph_dependency_count_before_dedup = 224
folded_vendor_graph_edge_count                   = 224

template_internal_edge_count                     = 512
emitted_template_internal_edge_count             = 128
loop_carried_edge_count                          = 192
absorbed_loop_carried_edges                      = 192
loop_exit_edge_count                             = 64
absorbed_cross_subtask_store_edges               = 64
debug_expanded_edge_count                        = 672
```

Interpretation:

```text
loop_carried edges:
  absorbed into repeated subtask carried accumulator state

cross-subtask store edges:
  absorbed by task-local subtask ordering in folded VendorABI

debug expanded edges:
  remain in ASM debug view but are not emitted as folded vendor graph edges
```

The report also marks loop variant binding as not binary-bound yet:

```text
variant_binding_status = symbolic_only_not_binary_bound

required before binary:
  spm_addr_offset
  base_addr_row_selection
  route_bundle_id
  visibility_ref_id
  symbolic_immediate_fields
```

## Important Invariants

### Route Ownership

DFU route actions are sender-push:

```text
TileRouteAction.execution_processor owns the executable route block.
TileRouteAction.endpoint_processor owns the produced visibility endpoint.
```

Compute blocks consume local visibility endpoints. They must not own full route
paths.

### MicroBlock Boundary

Compute micro-blocks do not contain route or store actions:

```text
compute_update:
  only HMMAL / local compute instruction

route_source_materialize / route_forward:
  only route materialization / forwarding instruction

tile_store:
  only store instruction
```

This fixed the predecessor / successor overflow that appeared when route and
compute were mixed into one executable block.

### Loop-Carried State

K recurrence is not emitted as vendor graph edges:

```text
compute_k0 -> compute_k1 -> compute_k2 -> compute_k3
```

is represented as loop-carried accumulator state inside a repeated subtask, not
as explicit vendor graph fan-in / fan-out.

### Store Ordering

Store follows the folded k-stream subtask by subtask ordering. The expanded
store dependency remains in ASM debug form, but folded VendorABI does not emit
the old expanded `k_last -> store` graph edge.

## Current Validation

The active frontend test checks:

- all tile actions have micro-blocks,
- route blocks are owned by execution processor,
- compute blocks are owned by compute processor,
- Packing / ASM preserve micro-block identity,
- repeated loop templates are isomorphic,
- VendorABI uses folded repeat rows,
- K-expanded k1 compute ASM blocks are not emitted as vendor exeBlocks,
- `folded_vendor_report` accounts for absorbed loop-carried / store / debug edges,
- variant binding is explicitly marked `symbolic_only_not_binary_bound`,
- predecessor / successor overflow remains zero.

Current test result:

```text
pytest -q
79 passed
```

## What Is Still Not Done

### Binary Serializer

`ProgramVendorABI` is still symbolic. It does not yet serialize:

- `inst_t`,
- exeBlock conf,
- instance conf,
- task conf,
- subtask conf,
- simulator bundle files.

The next major stage is to decide the symbolic-to-byte ABI field mapping.

### LoopExitToken Cleanup

The current folded VendorABI absorbs store ordering by subtask order. A more
formal `LoopRegionExitToken` may still be useful as metadata, especially once
binary graph rows are emitted.

### Variant Binding

The folded ABI emits a k0 body template plus `instances_amount = K`. Binary
serialization must ensure each K instance selects the correct variant fields:

- A/B tile SPM offsets,
- base address row selection,
- route bundle / visibility identifiers,
- symbolic immediate fields tied to the loop index.

Without this, the simulator could incorrectly repeat k0 addresses for every
instance. The serializer must not start until this mapping is explicit.

### Multi-Accumulator Folding

Only single-accumulator K-body folding is active. Multi-accumulator folding
remains an optimization pass and should not block functional binary lowering.

## Recommended Next Step

Proceed to a binary serializer RFC / implementation plan, but with three gates:

```text
Gate 1:
  repeat evidence stays recorded in this report

Gate 2:
  loop variant bindings map to concrete symbolic vendor fields

Gate 3:
  folded_vendor_report is consumed as a no-reexpand contract
```

Then lower:

```text
ProgramVendorABI
  -> symbolic vendor binary rows
  -> concrete vendor blob fields
  -> byte serializers
  -> simulator bundle files
```

Do not re-expand K recurrence in the binary layer. The binary serializer should
be boring: it should serialize the already-folded VendorABI rows, not rediscover
loop semantics or route dependencies.
