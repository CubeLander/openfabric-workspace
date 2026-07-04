# RFC: Folded TileLoop Lowering to Vendor Repeat

Date: 2026-06-14

## Status

Draft for review before implementation.

This RFC follows two already-landed refactor steps:

```text
TileLoopRegion:
  decides what repeats.

TileMicroBlock:
  decides which tile actions form executable blocks inside the repeated body.
```

The next step is to stop treating expanded `k0/k1/k2/k3` debug instances as the
authoritative vendor schedule.

Target:

```text
TileLoopRegion(repeat_count=K)
  -> one vendor repeated subtask body
  -> instance repeat count = K
```

not:

```text
k0 blocks + k1 blocks + k2 blocks + k3 blocks
  -> many independent vendor exeBlock rows
```

## Why This Needs an RFC

This step should not be a casual implementation patch.

It touches the exact boundary where compiler IR becomes vendor runtime ABI:

```text
ProgramAsm
  -> ProgramVendorABI
  -> future binary serializers
```

The dangerous question is:

```text
What does vendor instance repeat actually repeat?
```

We need to confirm that vendor repeat means:

```text
for k in 0..K-1:
  execute the whole repeated subtask body for k
```

and not:

```text
repeat block0 K times
then repeat block1 K times
then repeat block2 K times
```

If this semantic assumption is wrong, folding K-loop into vendor repeat will
produce a structurally beautiful but behaviorally wrong binary.

Therefore this RFC defines the intended lowering and the implementation gates.

## Current State

### Tile Layer

`ProcessorTileProgram` now contains:

```text
TileLoopRegion
TileLoopBodyInstance
TileVisibilityRef
TileMicroBlock
TileBlockDependency
TileRouteAction
TileComputeAction
TileStoreAction
```

For GEMM:

```text
TileLoopRegion:
  loop_axis = K
  repeat_count = 4
  carried_refs = C accumulator state
  body_instances = k0, k1, k2, k3
```

Each body instance contains micro-blocks such as:

```text
route_source_materialize
route_forward
compute_update
```

The current implementation keeps expanded instances for debug and validation.

### Node / Packing / ASM / VendorABI

The lowering stack now carries micro-block identity through:

```text
ProgramNode.payload.tile_micro_block_id
NodePackingBinding.tile_micro_block_id
ProgramAsmInstruction.source_tile_micro_block_id
ProgramAsmBlock.source_tile_micro_block_ids
VendorExeBlockRow.source_tile_micro_block_ids
```

`ProgramAsmBlock` is now split by micro-block:

```text
one TileMicroBlock -> one ProgramAsmBlock
```

This fixed the previous mixed-block problem:

```text
compute_update exeBlock no longer contains route LD instructions.
```

Current diagnostic result:

```text
predecessor_overflow_count = 0
successor_overflow_count   = 0
```

This is good, but still not final folded vendor repeat.

### What Is Still Expanded

Today, K instances still exist as expanded runtime rows:

```text
k0 micro-blocks
k1 micro-blocks
k2 micro-blocks
k3 micro-blocks
```

Vendor ABI still emits rows for every expanded instance.

That means the current form is:

```text
loop-aware debug-expanded schedule
```

not:

```text
folded vendor repeated schedule
```

## Target Model

### Structural View

The authoritative repeated unit should be:

```text
RepeatedTileLoopBodyTemplate:
  loop_region_id
  loop_axis
  repeat_count
  carried_refs
  body_micro_block_templates
  variant_bindings
```

Example:

```text
TileLoopRegion wave0:
  repeat_count = 4

  body template:
    route A[k] visibility
    route B[k] visibility
    compute C = update(C, A[k], B[k])

  carried:
    C accumulator

  variant bindings:
    k -> A tile offset
    k -> B tile offset
    k -> route bundle / visibility ref
```

### Vendor View

The vendor-facing representation should be:

```text
VendorSubtaskRow:
  instances_amount = TileLoopRegion.repeat_count
  repeated_body_exeBlocks = template micro-block rows
```

Expanded K instances may still be dumped as debug:

```text
expanded_debug_instances:
  k0
  k1
  k2
  k3
```

but binary-facing ABI must consume:

```text
template + repeat_count
```

## Core Invariants

### 1. TileLoopRegion Is the Repeat Authority

Do not rediscover K loops from names like:

```text
inst0
inst1
k2
```

Use:

```text
TileLoopRegion.repeat_count
TileLoopRegion.body_instances
TileLoopRegion.carried_refs
```

### 2. TileMicroBlock Is the Executable Body Authority

Repeated body blocks are micro-block templates:

```text
TileMicroBlock(route_source_materialize)
TileMicroBlock(route_forward)
TileMicroBlock(compute_update)
```

ASM and VendorABI should not infer route/compute roles from opcodes.

### 3. K Recurrence Is Carried State

This analysis edge may exist:

```text
compute_k0 -> compute_k1
```

But folded vendor ABI must not emit it as a normal graph edge.

Instead:

```text
TileLoopRegion.carried_refs
  -> Vendor repeated subtask carried state metadata
```

### 4. Loop-Variant Visibility Stays Inside the Repeated Body

A/B route and visibility actions depend on `k`, so they belong inside the body:

```text
for k:
  materialize / forward A[k]
  materialize / forward B[k]
  compute C += A[k] @ B[k]
```

Do not hoist loop-variant visibility to a prologue.

### 5. Store Depends on Loop Exit

Store should depend on:

```text
LoopRegionExitToken
```

not on:

```text
compute_k_last
```

The debug-expanded view may show `compute_k_last -> store`, but folded view
should expose:

```text
loop_final(C) -> store_tile
```

### 6. Expanded Instances Are Debug-Only

Expanded instances are allowed for:

```text
validation
diff against old lowering
debug dumps
template isomorphism checks
```

They must not drive final vendor row counts once folded repeat lowering is
enabled.

## Proposed IR Additions

### `folded_repeat_mode`

Add an explicit mode to avoid accidental binary-facing behavior changes:

```python
folded_repeat_mode = "off" | "metadata_only" | "emit_vendor_rows"
```

Semantics:

```text
off:
  fully expanded ABI only

metadata_only:
  generate repeated_loop_templates and folded estimates
  keep vendor rows expanded

emit_vendor_rows:
  make VendorABI consume folded templates
  k_stream rows no longer scale with K
```

The first implementation should use:

```text
metadata_only
```

### Template Scope

There are two related scopes:

```text
RepeatedTileLoopBodyTemplate:
  per loop_region + processor template

RepeatedSubtaskTemplate:
  optional group-level template collecting processor templates and
  cross-processor template edges
```

First implementation only needs `RepeatedTileLoopBodyTemplate`, but dumps should
make the scope obvious:

```text
loop_region_id
processor
body_micro_block_ids
```

This avoids confusing a PE-local body template with a whole-subtask template.

### `RepeatedTileLoopBodyTemplate`

This can live initially inside `program_packing.py` or `program_asm.py`, but the
source of truth is `TileLoopRegion + TileMicroBlock`.

Suggested shape:

```python
@dataclass(frozen=True)
class RepeatedTileLoopBodyTemplate:
    template_id: str
    loop_region_id: str
    processor: str
    loop_axis: str
    repeat_count: int
    fold_policy: str

    body_micro_block_ids: tuple[str, ...]
    body_micro_block_kinds: tuple[str, ...]

    carried_refs: tuple[str, ...]
    loop_variant_refs: tuple[str, ...]

    expanded_debug_instance_keys: tuple[str, ...]
    instance_isomorphism: dict[str, Any]
    attrs: dict[str, Any]
```

### `LoopRegionExitToken`

Add a symbolic final-output token:

```python
@dataclass(frozen=True)
class LoopRegionExitToken:
    token_id: str
    loop_region_id: str
    processor: str
    final_value_refs: tuple[str, ...]
    source_carried_refs: tuple[str, ...]
```

First implementation can expose it in packing/asm metadata without deleting the
debug `compute_k_last -> store` edge.

Later vendor-facing edge emission should use:

```text
LoopRegionExitToken -> tile_store
```

## Implementation Plan

### Phase 0: Repeat Semantics Probe

Before changing binary-facing behavior, inspect legacy/vendor evidence:

```text
Does instance repeat apply to the whole subtask body?
Do all exeBlocks in a subtask share one instance loop?
Are PC ranges / base address rows selected per instance?
Are graph dependencies interpreted per repeated body instance or per block?
```

Expected evidence source:

```text
legacy generated task/subtask/instance rows
vendor instance_conf / subtask_conf structure
known working GEMM legacy bundle
```

Output:

```text
notes/refactor/stage-report-vendor-repeat-semantics.md
```

### Phase 1: Build Folded Templates as Metadata

Do not change vendor row counts yet.

Add:

```text
DFUPackingProgram.repeated_loop_templates
ProgramAsm.repeated_loop_templates
ProgramVendorABI.repeated_loop_templates
```

Each template references:

```text
loop_region_id
repeat_count
micro-block template ids
expanded debug instances
carried refs
```

Validation:

```text
template_count == TileLoopRegion count
repeat_count == TileLoopRegion.repeat_count
all body instances are isomorphic
all loop-variant visibility producers are inside template body
```

Add diagnostic fields:

```text
folded_repeat_mode = metadata_only
expanded_vendor_row_count
folded_vendor_row_estimate
expanded_debug_instance_count
body_template_micro_block_count
```

### Phase 2: Classify Folded Edges

Classify dependencies into:

```text
template_internal_edge
loop_carried_edge
loop_exit_edge
normal_vendor_edge
debug_expanded_edge
```

Rules:

```text
route step inside one repeated body:
  template_internal_edge

visibility before compute inside one repeated body:
  template_internal_edge

compute_k_i -> compute_k_i+1:
  loop_carried_edge

loop final output -> store:
  loop_exit_edge
```

For this phase, keep old graph emission but report:

```text
folded_vendor_edge_count_estimate
expanded_debug_edge_count
absorbed_loop_carried_edge_count
template_internal_edge_count
```

Unified report:

```text
FoldedEdgeReport:
  action_edges_total
  block_edges_total
  template_internal_edge_count
  loop_carried_edge_count
  loop_exit_edge_count
  normal_vendor_edge_count
  debug_expanded_edge_count
  folded_vendor_edge_count_estimate
```

### Phase 3: Emit Folded Vendor Subtask Rows

Once semantics are verified, make `ProgramVendorABI` consume folded templates.

For each `TileLoopRegion`:

```text
VendorSubtaskRow.instances_amount = repeat_count
VendorSubtaskRow.valid_exeblock_ids = template body exeBlocks
```

The vendor exeblock count should no longer scale with `K` for folded K-stream
subtasks.

Expected diagnostic change:

```text
expanded k_stream exeBlocks:
  O(K * body_blocks)

folded k_stream exeBlocks:
  O(body_blocks)
```

### Phase 4: Store Uses Loop Exit

Introduce folded store dependency:

```text
LoopRegionExitToken -> tile_store
```

The old expanded edge:

```text
compute_k_last -> store
```

can stay in debug metadata but should not be emitted as the final vendor graph
truth.

### Phase 5: Binary Serializer Gate

Do not implement binary bytes for folded repeat until:

```text
repeat semantics probe passes
folded template metadata is stable
instance isomorphism verifier passes
vendor subtask repeat count matches TileLoopRegion.repeat_count
store consumes loop exit token
no K-expanded recurrence edge reaches vendor graph
```

## Instance Isomorphism Checks

For vendor repeat, every K instance must have the same body shape.

Allowed per-instance differences:

```text
k index
tile refs
SPM/base address offsets
visibility ref ids
route bundle ids
symbolic immediates tied to k
```

Forbidden differences:

```text
different opcode sequence
different micro-block kind sequence
different dependency topology
different carried refs
different processor ownership
different stage layout
```

Verifier output:

```text
instance_isomorphic = true / false
allowed_variant_fields = [...]
violations = [...]
```

Also check:

```text
same template-internal edge kind sequence
```

The canonical signature should include:

```text
micro-block kind sequence
opcode/stage sequence
template-internal edge kind sequence
processor ownership
carried refs
```

## Expected Effects

### Correctness

K-loop execution semantics move from:

```text
expanded graph ordering
```

to:

```text
vendor repeated subtask semantics
```

### ABI Size

Vendor K-stream rows stop scaling with `K`.

For current GEMM with `repeat_count=4`, folded row counts should drop relative
to the debug-expanded ABI.

### Dependency Pressure

Loop-carried edges remain absorbed.

Template-internal dependencies do not become global vendor graph pressure.

### Debuggability

Expanded K instances remain available as debug view:

```text
template row
  expanded_debug_instances[k0..kN]
```

Every folded vendor row should still reverse-map to:

```text
loop_region_id
tile_micro_block_id
source tile action ids
expanded debug instance examples
```

## Tests to Add

### Packing Tests

```text
repeated_loop_template_count == tile_loop_region_count
template.repeat_count == loop.repeat_count
template.body_micro_block_kinds are isomorphic across instances
template.carried_refs == loop.carried_refs
```

### ASM Tests

```text
ProgramAsm exposes repeated loop templates
template body contains micro-block asm blocks
expanded instances are debug-only
```

### Vendor ABI Tests

Before enabling folded row emission:

```text
folded_vendor_row_estimate exists
expanded_vendor_row_count still unchanged
folded_repeat_mode == metadata_only
```

After enabling folded row emission:

```text
VendorSubtaskRow.instances_amount == TileLoopRegion.repeat_count
k_stream vendor exeBlock count no longer scales with repeat_count
loop_carried edges are not vendor graph edges
store edge references loop exit token
```

### Regression Tests

```text
pytest -q tests/test_chip_program_frontend.py
pytest -q
```

## Non-Goals

This RFC does not implement:

```text
multi-accumulator K-body grouping
route micro-block coalescing
binary byte serializer
operand residency allocator
new GEMM schedule
CUDA/CANN backend abstractions
```

## Open Questions

### Q1: Does vendor repeat apply to whole subtask body?

This is the most important question.

If yes:

```text
folded TileLoopRegion -> VendorSubtask repeat
```

is valid.

If no:

```text
we need another folding representation or must keep expanded rows.
```

### Q2: Where should loop exit token first appear?

Options:

```text
program_tile.py:
  strongest semantic location, but may require changing tile store deps.

program_packing.py:
  lower-risk first landing, can coexist with expanded debug edge.
```

Recommendation:

```text
Start in packing metadata, then move earlier if needed.
```

### Q3: Should template-internal route edges appear in vendor graph?

If vendor repeat body needs explicit internal graph edges, emit them as template
edges, not expanded per-K edges.

If subtask body order is sufficient, internal route/compute dependencies may be
encoded as local body order metadata.

This must be answered by the repeat semantics probe.

## Current Implementation Status

Vendor repeat has been confirmed to execute the whole subtask body per
instance:

```text
for k in 0..K-1:
  execute subtask body template for k
```

The compiler now uses this in `program_vendor_abi.py`:

```text
ProgramAsm expanded debug rows
  -> ProgramVendorABI folded k_stream rows

k_stream:
  emit only template instance k0 exeBlocks
  VendorSubtaskRow.instances_amount = TileLoopRegion.repeat_count
  VendorSubtaskRow.repeat_mode = emit_vendor_rows
  repeat_semantics = vendor_instance_repeat_whole_subtask_body

finalize_store:
  emit normal single-pass store rows
```

The folded ABI deliberately keeps Packing / ASM expanded as debug views. Vendor
ABI is the first layer that stops emitting `k1..kN` k-stream exeBlocks.

Current GEMM symbolic ABI effect:

```text
expanded ASM blocks:
  832

folded VendorABI exeBlocks:
  256

folded VendorABI graph edges:
  224

k_stream subtask:
  valid_exe_blocks = template body only
  instances_amount = 4
```

Cross-subtask store ordering is absorbed by the vendor subtask sequence; the
old expanded `compute_k_last -> store` edge remains visible in ASM as debug
evidence but is not emitted as a folded VendorABI graph edge.

## Recommendation

Do not immediately delete expanded K rows.

The remaining order is:

```text
1. Keep Packing / ASM expanded debug rows until binary serialization is stable.
2. Add a focused folded edge / row report if debugging needs it.
3. Continue toward symbolic vendor binary rows and serializer.
4. Do not re-expand K recurrence into vendor graph edges.
```

Completed implementation phases:

```text
repeat semantics accepted
repeated_loop_templates metadata added
metadata propagated through ASM
VendorABI row emission switched to folded templates
```

This keeps the compiler debuggable while moving toward binary serialization.

## Suggested Commit Sequence

```text
Commit A: DONE / externally confirmed
  notes/refactor/stage-report-vendor-repeat-semantics.md
  vendor repeat unit = whole subtask body

Commit B: DONE
  Add RepeatedTileLoopBodyTemplate dataclass
  Add repeated_loop_templates to DFUPackingProgram

Commit C: DONE
  Propagate templates to ProgramAsm / ProgramVendorABI metadata
  folded_repeat_mode = metadata_only

Commit D: DONE
  Add instance isomorphism signatures
  report violations in metadata_only mode / assert in tests

Commit E: PARTIAL
  Add LoopRegionExitToken in packing metadata
  cross-subtask store order absorbed in folded VendorABI
  keep compute_k_last -> store as ASM debug edge

Commit F: OPTIONAL NEXT
  Add FoldedEdgeReport
  report expanded vs folded row/edge estimates

Commit G: DONE
  folded_repeat_mode = emit_vendor_rows
  switch VendorSubtaskRow.instances_amount to repeat_count
  stop emitting K-expanded k_stream exeBlocks

Commit H: NEXT
  binary serializer RFC
```
