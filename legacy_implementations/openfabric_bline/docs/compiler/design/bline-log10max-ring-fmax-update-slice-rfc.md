# RFC: B-line Log10max Ring FMAX Update Slice Integration

## Status

Draft for review.

This RFC is the next implementation boundary after log10max operator payload
slice accounting.  The current B-line log10max operator ledger has one present
slice:

```text
route_copy:
  30 logical GlobalMax route edges
  -> 120 physical COPY lane rows
  -> route slice structurally integrated
```

The operator remains blocked because the compute row families are still absent.
The narrowest next slice is:

```text
ring_fmax_update:
  max_update_global_max
```

This RFC proposes how to promote the existing ring-update FMAX evidence from
candidate reports into an operator instruction slice without crossing into
runtime readiness, full payload assembly, or local_reduce / postprocess work.

## Summary

Current route work proves GlobalMax movement can be represented as owned route
rows.  Current ring-update work proves the receiver-side update has FMAX-shaped
candidate rows and placement candidates.  The missing boundary is that
`ring_fmax_update` is not yet a present operator slice:

```text
RingUpdateTemplateBinding
  -> RingUpdateBinaryLayoutRowCandidate
  -> OperandPlaceholder / OperandAllocation / InstOperandPatch
  -> RingUpdateFmaxInstCandidate
  -> RingUpdateComponentPlacementCandidate
  -> OperatorInstructionSlice(slice_kind="ring_fmax_update")
```

Recommended decision:

```text
Accept Phase 6A/6B/6C as the next progress slice.

Phase 6A:
  close allocation-backed FMAX row bytes for the 30 update rows.

Phase 6B:
  bind FMAX update placement into the same layout_epoch as route_copy.

Phase 6C:
  add ring_fmax_update as a present OperatorInstructionSlice by copying
  decoded candidate bytes, not repacking.

Do not:
  claim local_reduce, max_with_floor, postprocess, store, payload manifest,
  runtime_ready, uploadable, SimICT execution, or numerical correctness.
```

## Current State

Already accepted and partially implemented:

```text
ring_spmd_row_then_col:
  task_axis = 1
  representative row/column reduce+broadcast
  30 logical GlobalMax route edges

route_copy slice:
  120 COPY lane rows
  allocation-backed route operand patches
  final simulator-inst_t flow_ack
  component offsets
  route_slice_sha256 present
  OperatorInstructionSlice(slice_kind="route_copy") present
```

Current operator payload ledger:

```text
OperatorInstructionSliceSet:
  present_row_families = (route_copy,)
  missing_row_families = (
    logspec_elementwise,
    local_reduce,
    ring_fmax_update,
    max_with_floor,
    postprocess_scale,
    store,
  )
  slice_set_status = partial
  runtime_ready = false
  uploadable = false
```

Existing ring-update reports prove useful but incomplete facts:

```text
30 RingUpdateTemplateBinding records
30 RingUpdateTemplateOpCandidate records
30 RingUpdateBinaryLayoutRowCandidate records
30 RingUpdateFmaxInstCandidate records
30 RingUpdateComponentPlacementCandidate records

phase distribution:
  row_reduce:      12
  col_reduce:       3
  col_broadcast:    3
  row_broadcast:   12

candidate opcode:
  FMAX

current candidate limitation:
  earlier skeleton operands [0, 128, 256] were diagnostic only
  final row operands must come from InstOperandPatch
```

Recent operand-allocation work established the hard chain:

```text
OperandPlaceholder
  -> OperandAllocation
  -> InstOperandPatch
  -> pack/decode proof
  -> final component row candidate
```

The next step is to apply that chain to the 30 FMAX update rows and then expose
the result as the `ring_fmax_update` slice.

## Problem

The route slice can move `GlobalMax`, but the operator still cannot consume
that movement unless every receiver PE performs:

```text
globalmax_acc_out = FMAX(globalmax_acc_in, globalmax_recv)
```

The current project has enough evidence to describe this row family, but not
enough to let the operator ledger mark it present.  The dangerous shortcut is:

```text
FMAX candidate row exists
  -> mark ring_fmax_update slice present
```

That is not acceptable.  A present operator slice must prove:

```text
logical value continuity
operand allocation
inst operand patch
field ownership
row bytes decode
layout epoch compatibility
component offset no-overwrite
row provenance back to FiberOp / TemplateExpansion / ring edge
```

Otherwise B-line regrows the hidden backend we have been removing: a writer or
assembler that silently chooses operands, PCs, or row fields.

## Goals

1. Promote `ring_fmax_update` from blocked row family to present operator slice.
2. Keep `FiberOp(global_max_tile)` atomic.
3. Require allocation-backed FMAX rows; diagnostic skeleton operands are not
   allowed in slice bytes.
4. Require route lane-group completion to dominate each FMAX update.
5. Require FMAX placement to share the same `layout_epoch` and
   `layout_plan_sha256` as route_copy.
6. Copy row bytes from candidate records into slice records; do not repack in
   the slice assembler.
7. Keep log10max operator state blocked until every required row family,
   control component, manifest, and runtime asset is present.

## Non-goals

This RFC does not:

```text
implement local_reduce
implement logspec elementwise rows
implement max_with_floor or postprocess scale
implement store rows
change ring topology
change route COPY/COPYT encoding
add direct_route_reduce_broadcast
add generic register allocation
claim final CBUF/MICC payload
claim runtime_ready or uploadable
claim SimICT execution
claim numerical correctness
```

## Proposed Design

### Phase 6A: Allocation-Backed FMAX Row Bytes

Add a report that turns each ring-update row candidate into an
allocation-backed byte candidate:

```python
@dataclass(frozen=True)
class RingFmaxUpdateRowByteRecord:
    schema_version: str
    row_id: str
    logical_route_edge_id: str
    phase: Literal[
        "row_reduce",
        "col_reduce",
        "col_broadcast",
        "row_broadcast",
    ]
    task_id: int
    dst_pe: str

    source_fiber_op_id: str
    template_expansion_id: str
    ring_update_template_binding_id: str
    inst_operand_patch_id: str
    allocation_ids: tuple[str, ...]

    opcode: Literal["FMAX"]
    dtype: Literal["fp32"]
    globalmax_representation: Literal["replicated_fp32_vector"]
    alias_policy: Literal["forbidden"]

    src_operands_idx: tuple[int, int, int]
    dst_operands_idx: tuple[int, int, int]
    operand_field_usage: Mapping[str, Literal["used", "unused_zero_fill"]]

    raw_inst_t_row_bytes_sha256: str
    decoded_opcode: str
    decoded_src_operands_idx: tuple[int, int, int]
    decoded_dst_operands_idx: tuple[int, int, int]
    decode_roundtrip_status: Literal["pass", "blocked"]
    provenance_status: Literal["pass", "blocked"]
    byte_status: Literal["allocation_backed_candidate", "blocked"]
    blocker_ids: tuple[str, ...]
```

Hard requirements:

```text
row_count = 30
phase distribution = 12 / 3 / 3 / 12
all opcode = FMAX
all dtype = fp32
globalmax_representation = replicated_fp32_vector
alias_policy = forbidden
src0 = allocation(globalmax_acc_in)
src1 = allocation(globalmax_recv)
dst0 = allocation(globalmax_acc_out)
src2 / dst1 / dst2 are zero only through operand_field_usage
no hardcoded skeleton operand index may enter this report
```

Value continuity requirements:

```text
globalmax_acc_in:
  reuses local_reduce_max_out for the first update on that PE,
  or reuses previous globalmax_acc_out for later updates.

globalmax_recv:
  equals matching route_recv(GlobalMax).dst allocation.

globalmax_acc_out:
  feeds next route_push(GlobalMax).src,
  or next FMAX globalmax_acc_in,
  or final max_with_floor.globalmax_src.
```

This phase may produce candidate bytes, but only with allocation-backed
operands and decode/provenance proof.

### Phase 6B: FMAX Placement and Route Dependency Closure

Add a placement report for the 30 FMAX rows:

```python
@dataclass(frozen=True)
class RingFmaxUpdatePlacementRecord:
    schema_version: str
    placement_id: str
    row_id: str
    logical_route_edge_id: str
    phase: str
    task_id: int
    pe: str

    layout_epoch: str
    layout_plan_sha256: str
    exe_block_id: str
    stage: Literal["CAL"]
    local_pc: int
    component_byte_offset: int

    route_lane_group_completion_id: str
    ordering_predecessor_row_ids: tuple[str, ...]
    ordering_status: Literal[
        "block_order_proven",
        "subtask_order_proven",
        "app_boundary_proven",
        "blocked",
    ]

    no_overwrite_status: Literal["pass", "blocked"]
    placement_status: Literal["placed_candidate", "blocked"]
    blocker_ids: tuple[str, ...]
```

Ordering rule:

```text
FMAX update must depend on completion of the full COPY lane group for the same
logical_route_edge_id, not on an arbitrary COPY lane row.
```

Stage rule:

```text
FMAX may live in CAL only if route_recv/COPY lane group completion is ordered
before this CAL row through block/subtask/app ordering proof.
```

Layout rule:

```text
ring_fmax_update.layout_epoch == route_copy.layout_epoch
ring_fmax_update.layout_plan_sha256 == route_copy.layout_plan_sha256
```

If the route and FMAX reports use different layout epochs, the slice is
blocked.  The assembler must not "fix" PCs by repacking or shifting rows.

### Phase 6C: OperatorInstructionSlice Promotion

When Phase 6A and 6B pass, add:

```text
OperatorInstructionSlice(
  slice_kind = "ring_fmax_update",
  slice_status = "present",
  covered_semantic_ops = ("max_update_global_max",),
  row_count = 30,
  byte_status = "copied_from_candidate",
  placement_status = "placed",
  integration_scope = "row_family_only",
)
```

The slice may clear:

```text
log10max_operator_slice_ring_fmax_update_missing
log10max_semantic_op_max_update_global_max_missing
```

It must not clear:

```text
log10max_operator_instruction_slice_set_partial
log10max_operator_insts_component_partial
log10max_payload_manifest_component_partial
log10max_payload_manifest_runtime_assets_missing
log10max_payload_manifest_final_cbuf_missing
log10max_payload_manifest_final_micc_missing
```

After this phase, expected operator state is still:

```text
runtime_ready = false
uploadable = false
log10max = blocked
```

## Invariants

1. `FiberOp(global_max_tile)` remains atomic.  FMAX rows are template/lowering
   implementation, not new fiber semantics.
2. The row byte writer may only pack already-bound fields.
3. The operator slice assembler may only copy candidate row bytes; it must not
   call the packer or infer fields.
4. `src_operands_idx` and `dst_operands_idx` must come from
   `InstOperandPatch`.
5. `src2=0`, `dst1=0`, and `dst2=0` are valid only through explicit usage-mask
   zero-fill evidence.
6. Route lane-group completion dominates FMAX execution.
7. All present slices share one `layout_epoch` and `layout_plan_sha256`.
8. Diagnostic skeleton bytes cannot enter `OperatorInstructionSlice`.
9. `ring_fmax_update` can become an operator slice; it cannot become the
   operator.
10. Only the preintegration gate may aggregate `runtime_ready` or `uploadable`.

## Alternatives Considered

### Mark FMAX Candidate Rows as Present Immediately

Rejected.  Candidate FMAX rows without allocation-backed operands, placement,
ordering, and decode/provenance proof would recreate the exact skeleton-row
bug the operand allocation RFC stopped.

### Implement Local Reduce First

Deferred.  `local_reduce` is necessary, but route_copy already produces the
`globalmax_recv` values that FMAX consumes.  Closing the adjacent
`route_copy -> ring_fmax_update` dependency gives the fastest structural
progress and exposes the next endpoint requirements more clearly.

### Fold FMAX Update into Route Recv

Rejected.  Route receive and receiver-side max update are different FiberOps /
template expansions.  Hiding FMAX inside route rows would create a hidden
communication/backend authority.

### Build Full Component Immediately

Rejected.  Other row families are still missing.  A route+FMAX component is a
stronger partial candidate, not a full log10max operator.

## Migration / Implementation Plan

Phase 6A:

```text
[ ] Build RingFmaxUpdateRowByteRecord for 30 rows.
[ ] Consume existing RingUpdateTemplateBinding / BinaryLayout candidates.
[ ] Consume OperandAllocation / InstOperandPatch records.
[ ] Pack/decode allocation-backed FMAX candidate bytes.
[ ] Fail if any skeleton operand index enters the row.
```

Phase 6B:

```text
[ ] Build RingFmaxUpdatePlacementRecord for 30 rows.
[ ] Bind each row to a route lane-group completion token.
[ ] Prove ordering through block/subtask/app boundary.
[ ] Verify layout_epoch/layout_plan_sha256 matches route_copy.
[ ] Verify no-overwrite and PE-local PC capacity.
```

Phase 6C:

```text
[ ] Add ring_fmax_update to OperatorInstructionSliceSet when 6A/6B pass.
[ ] Copy row bytes from FMAX candidates into slice records.
[ ] Update operator slice checker expected counts:
    route_copy = 120
    ring_fmax_update = 30
[ ] Keep non-route/non-FMAX families blocked.
```

Phase 6D:

```text
[ ] Run preintegration gate.
[ ] Expect log10max still blocked.
[ ] Confirm missing blockers now point at logspec_elementwise, local_reduce,
    max_with_floor, postprocess_scale, store, control coherence, payload files,
    and runtime assets.
```

## Validation Plan

Add focused checkers:

```text
check_stream_compiler_log10max_ring_fmax_update_row_bytes.py
check_stream_compiler_log10max_ring_fmax_update_placement.py
check_stream_compiler_log10max_ring_fmax_update_slice.py
```

Required checks:

```text
30 FMAX rows
phase distribution = 12 / 3 / 3 / 12
all rows decode as FMAX
all operand fields match InstOperandPatch
all allocation ids present
no skeleton operands
all rows preserve ring_edge / StreamAction / FiberOp / TemplateExpansion provenance
all rows use route lane-group completion predecessor
all rows share route_copy layout_epoch/layout_plan_sha256
no component offset overlap
slice covers exactly max_update_global_max
runtime_ready remains false
uploadable remains false
```

Preintegration expected delta:

```text
Before:
  missing includes log10max_operator_slice_ring_fmax_update_missing
  missing includes log10max_semantic_op_max_update_global_max_missing

After:
  those two blockers may clear
  log10max remains blocked
```

## Risks and Mitigations

### Risk: Skeleton Operands Leak Into Slice Bytes

Mitigation:

```text
Every FMAX row must reference InstOperandPatch and allocation_ids.
Rows with diagnostic src/dst indices but no patch remain report-only.
```

### Risk: Route COPY Completion Does Not Dominate FMAX

Mitigation:

```text
Require RouteLaneGroupCompletion per logical edge.
FMAX depends on group completion, not one lane.
```

### Risk: CAL/FLOW Stage Ordering Is Misread

Mitigation:

```text
Require ordering_status = block_order_proven | subtask_order_proven |
app_boundary_proven.  Stage names alone are not enough.
```

### Risk: Layout Epoch Drift

Mitigation:

```text
FMAX slice must share route_copy layout_epoch and layout_plan_sha256.
The assembler cannot shift local_pc values to make rows fit.
```

### Risk: Route+FMAX Is Mistaken for Full Operator

Mitigation:

```text
OperatorInstructionSliceSet remains partial until all expected row families are
present or explicitly folded with evidence.
```

## Expected Effect

After implementation, B-line should honestly report:

```text
present_row_families:
  route_copy
  ring_fmax_update

missing_row_families:
  logspec_elementwise
  local_reduce
  max_with_floor
  postprocess_scale
  store

covered_semantic_ops:
  route_globalmax_copy
  max_update_global_max

runtime_ready:
  false

uploadable:
  false
```

This is real progress because the central ring communication/update spine is
structurally present.  It is not a delivery claim.

## Open Questions

1. Do current `RingUpdateFmaxInstCandidate` rows already have complete
   allocation-backed operand patches, or do we still need a final adapter from
   the operand allocation report?
2. Is FMAX placement already in the same frozen layout epoch as route_copy, or
   do we need to regenerate route+FMAX layout together?
3. Which block/subtask ordering proof is simplest for
   `route lane group completion -> FMAX update`?
4. Should `globalmax_acc_in` for first update reuse `local_reduce_max_out`
   immediately, or remain blocked until the local_reduce slice exists?
5. Does postprocess `max_with_floor.globalmax_src` already consume the final
   FMAX `globalmax_acc_out`, or does that endpoint stay blocked until the
   max_with_floor slice RFC?

## Recommended Decision

Accept this RFC as the next progress slice.

Execute:

```text
Phase 6A:
  allocation-backed FMAX row bytes

Phase 6B:
  layout-compatible FMAX placement and route lane-group dependency proof

Phase 6C:
  promote ring_fmax_update to present operator slice
```

Do not execute under this RFC:

```text
local_reduce rows
max_with_floor rows
postprocess rows
store rows
final CBUF/MICC assembly
operator payload upload
runtime_ready transition
```

One-line decision:

```text
Make ring_fmax_update the next present log10max slice, but keep log10max
blocked until the rest of the operator is on the same slice ledger.
```
