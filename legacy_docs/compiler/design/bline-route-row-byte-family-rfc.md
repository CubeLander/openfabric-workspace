# RFC: B-line Route Row Byte Family Decision

## Status

Draft for review.

This RFC covers Phase 2 after the accepted route endpoint and layout closure
work. It decides how B-line may materialize log10max `GlobalMax` route rows as
candidate `inst_t` bytes without letting route serialization become a hidden
backend.

## Summary

Phase 0/1 proved the route endpoints, receiver-owned operands, phase layout,
and placement candidates for the log10max task-local ring. Phase 2 must now
decide the route instruction family. A-line does not treat route bytes as
`opcode + operands`. Route rows are the result of:

```text
CSV / pseudo instruction skeleton
  + pseudo expansion such as COPYT -> COPY lanes
  + receiver/child Task_Resource operand patch
  + destination PE/block patch
  + flow_ack / base-slot policy
  + stage, block, end_inst, and component placement
```

The Phase 0/1 route-layout RFC intentionally did not choose `COPY`, `COPYT`,
`LDN`, or `source_template_fixed`. This Phase 2 RFC is the decision point. After
reviewing the A-line/vendor baseline, the recommended V1 route family for
`GlobalMax` native B-line candidates is:

```text
COPYT logical route action
  -> 4 physical COPY row candidates
```

This matches the current `GlobalMax` representation as a replicated fp32 vector
over a 4096-bit logical operand, while keeping the actual bytes behind
field-owner and decode gates.

This RFC permits Phase 2A and Phase 2B:

```text
Phase 2A:
  RouteByteFamilyDecisionReport and RoutePhysicalRowPlan.

Phase 2B:
  allocation-backed COPY row candidate bytes, only after flow_ack and
  field ownership are bound.
```

It does not permit final route row component insertion, `runtime_ready=true`, or
uploadable package claims.

## Current State

Already implemented / accepted:

```text
Ring plan:
  ring_spmd_row_then_col, representative row/column reduce+broadcast

Operand chain:
  local_reduce_max_out
    -> route_push.src
    -> route_recv.dst
    -> FMAX.src_received
    -> FMAX.dst
    -> next route_push.src or max_with_floor.globalmax_src

Route endpoint closure:
  30 logical ring route edges
  phase distribution = 12 / 3 / 3 / 12
  sender and receiver PE are known
  sender src allocation and receiver dst allocation are known
  route family remains pending

Layout closure:
  route rows are planned as FLOW-stage candidates
  FMAX update rows are CAL-stage candidates
  one collective phase per exeBlock in V1
  component placement remains unintegrated
```

Current gate state must remain:

```text
runtime_ready = false
uploadable = false
```

## A-line / Vendor Baseline Facts

The A-line and vendor `common_oper` path determines route row fields through
several independent mechanisms.

1. `COPY` and `COPYT` are FLOW instructions.

`csv_oper.cpp` registers `COPYT` as a pseudo instruction and `COPY` as the
physical instruction family. B-line's legacy mirror also records `COPY=0xC0`,
`COPYT=0x101`, and maps pseudo `COPYT` to physical `COPY`.

2. `COPYT` expands into multiple physical `COPY` rows.

The legacy Python mirror expands `COPYT` into physical `COPY` rows and adjusts
lane operands by `lane * OPERANDS_PER_OPERAND_RAM`. The vendor
`inst_blk_map.cpp` path also patches following COPYT rows by adding
`OPERANDS_PER_OPERAND_RAM`-sized lane deltas. Current DFU constants use four
operand RAM lanes for a 4096-bit logical operand.

3. Route destination operands are receiver-owned.

Vendor `fill_copy_inst` patches the COPY destination through the child /
receiver PE's `Task_Resource`, not the sender's resource. The fields patched
include:

```text
dst_operands_idx[0]
dst_pes_pos[0]
dst_blocks_idx[0]
```

B-line must preserve this rule: route push source operands belong to the sender
scope; route receive destination operands belong to the receiver scope.

4. `flow_ack` is not a spare zero field.

There are at least two A-line behaviors:

```text
inst_map_common::setACKInst:
  flow_ack = child_idx

inst_blk_map / legacy stage end handling:
  flow_ack = 1 for selected last COPY / FLOW rows
```

The RTL projection in `task_print.cpp` maps COPY `flow_ack` into a
`base_addr_idx`-like field. The local validation check also treats `flow_ack` as
a base-address slot for FLOW/COPY rows. Therefore B-line must not silently set
`flow_ack=0`.

5. Route row bytes are not a route graph artifact.

The old path consumes graph edges, PE placement, task resource allocation,
pseudo expansion, stage split, and task printing. A B-line serializer must not
reconstruct any of those decisions from `RingEdgeRecord` alone.

## Problem

Phase 0/1 can tell us:

```text
send GlobalMax from PE A to PE B
read sender operand X
write receiver operand Y
place route candidate before its consumer FMAX
```

That is still not enough to write final route bytes. The missing decisions are:

```text
COPY vs COPYT vs LDN vs source_template_fixed
number of physical rows per logical edge
lane operand offsets
src1 / unused operand field policy
flow_ack policy
destination block binding
stage-local row ordering and end_inst
component placement
```

If the byte writer chooses any of these fields, it becomes a hidden backend.
That would violate the B-line contract.

## Goals

1. Choose the V1 route byte family for log10max `GlobalMax` routes.
2. Define the data artifacts required before any route row candidate bytes can
   be emitted.
3. Preserve A-line facts: COPYT expansion, receiver-owned dst patching, and
   non-default `flow_ack`.
4. Keep route byte candidates separate from final component integration.
5. Keep `runtime_ready=false` until component placement, decode, provenance,
   and package gates pass.

## Non-goals

This RFC does not:

```text
implement generic route grouping
implement direct_route_reduce_broadcast
allow cross-task one-app collective cooperation
choose route semantics from RingGraph alone
insert route rows into final CBUF/MICC components
make log10max runtime_ready or uploadable
prove numerical correctness
```

## Proposed Design

### 1. V1 Route Family Decision

For `GlobalMax` V1:

```text
logical family:
  copyt_logical_globalmax_route

physical family:
  copyt_logical_expanded_copy_rows

logical value:
  replicated fp32 vector

logical width:
  4096 bits

physical rows per logical edge:
  4 COPY rows

lane stride:
  OPERANDS_PER_OPERAND_RAM

row opcode:
  COPY

stage:
  FLOW
```

Plain `COPY` as a single row is rejected for native V1 candidates because it
does not prove that the entire replicated 4096-bit `GlobalMax` operand moved.
`LDN` is rejected because this path is route communication, not memory
materialization.

`source_template_fixed` remains an exact-evidence override: if an A-line span
matches the route endpoint, operand continuity, layout, and decode requirements,
it may be used as the byte source for that row family. It is still not the
B-line semantic authority; it is a provenance-backed materialization source.

### 2. RouteByteFamilyDecision

```python
@dataclass(frozen=True)
class RouteByteFamilyDecision:
    schema_version: str
    decision_id: str
    operator: Literal["log10max"]
    route_role: Literal["GlobalMax"]
    selected_strategy: Literal["ring_spmd_row_then_col"]

    logical_route_family: Literal["copyt_logical_globalmax_route"]
    physical_row_family: Literal["copyt_logical_expanded_copy_rows"]
    logical_value_kind: Literal["replicated_vector"]
    dtype: Literal["fp32"]
    logical_width_bits: int
    physical_rows_per_logical_edge: int
    lane_stride_operands: int

    physical_opcode: Literal["COPY"]
    physical_unit: Literal["FLOW"]
    route_family_status: Literal[
        "selected_candidate",
        "blocked",
    ]
    evidence_refs: tuple[str, ...]
    blockers: tuple[str, ...]
```

Expected V1 constants:

```text
logical_width_bits = 4096
physical_rows_per_logical_edge = 4
lane_stride_operands = OPERANDS_PER_OPERAND_RAM
physical_opcode = COPY
```

### 3. Logical Edge vs Physical Row Plan

One logical ring edge must be separated from the physical rows it expands into.

```python
@dataclass(frozen=True)
class RoutePhysicalRowPlan:
    schema_version: str
    physical_row_plan_id: str
    logical_route_edge_id: str
    route_endpoint_patch_id: str
    route_byte_family_decision_id: str

    phase: Literal[
        "row_reduce",
        "col_reduce",
        "col_broadcast",
        "row_broadcast",
    ]
    lane_index: int
    lane_count: int
    lane_stride_operands: int

    src_operand_allocation_id: str
    dst_operand_allocation_id: str
    src_operand_idx: int
    dst_operand_idx: int
    src_operand_idx_before_lane_delta: int
    dst_operand_idx_before_lane_delta: int

    dst_pe_pos: tuple[int, int, int]
    dst_block_idx: int | None
    dst_block_status: Literal["bound", "pending", "blocked"]

    field_binding_record_id: str | None
    row_byte_candidate_id: str | None
    status: Literal[
        "planned",
        "field_bound",
        "candidate_bytes_emitted",
        "blocked",
    ]
    blockers: tuple[str, ...]
```

For the current 30 logical edges:

```text
logical route edges:
  30

physical COPY row plans:
  120

physical phase distribution:
  row_reduce      48
  col_reduce      12
  col_broadcast   12
  row_broadcast   48
```

### 4. Route Operand Patch

Route physical rows must use allocation-backed patches. The serializer cannot
compute lane operands.

```python
@dataclass(frozen=True)
class RouteInstOperandPatch:
    schema_version: str
    patch_id: str
    physical_row_plan_id: str
    logical_route_edge_id: str
    lane_index: int

    src_allocation_id: str
    dst_allocation_id: str
    src_operands_idx: tuple[int, int, int]
    dst_operands_idx: tuple[int, int, int]
    operand_field_usage: Mapping[str, Literal[
        "used",
        "unused_zero_fill",
        "source_template_fixed",
        "blocked",
    ]]
    patch_status: Literal["patched", "blocked"]
    blockers: tuple[str, ...]
```

For V1 physical COPY rows:

```text
src0 = src_base + lane_index * OPERANDS_PER_OPERAND_RAM
dst0 = dst_base + lane_index * OPERANDS_PER_OPERAND_RAM
src1/src2/dst1/dst2 must be zero_with_evidence or source_template_fixed
```

`src1` deserves explicit ownership. The legacy COPYT mirror uses `src1` on the
first expanded row in at least one path. B-line must not assume it is unused
unless the selected `COPY` row family proves that policy.

### 5. FlowAckPolicy

`flow_ack` is a separately owned field.

```python
@dataclass(frozen=True)
class FlowAckPolicy:
    schema_version: str
    policy_id: str
    applies_to: Literal["simulator_inst_t"]
    route_family_decision_id: str
    policy: Literal[
        "last_physical_copy_lane_sets_one",
        "child_edge_slot",
        "source_template_fixed",
        "blocked",
    ]
    slot_value_by_physical_row_id: Mapping[str, int]
    evidence_refs: tuple[str, ...]
    policy_status: Literal["bound", "blocked"]
    blockers: tuple[str, ...]
```

V1 candidate policy:

```text
Use last_physical_copy_lane_sets_one for route byte candidates only if:
  every logical route edge has exactly one outgoing edge in its phase/block, and
  validation confirms the selected slot is legal, and
  source evidence does not contradict it.
```

If that evidence is not closed, candidate bytes are blocked by:

```text
log10max_route_flow_ack_policy_missing
```

The Phase-2 flow_ack evidence worker must therefore produce a fail-closed
`FlowAckPolicy` report before any route bytes are considered. The default report
may record all known A-line facts, but it must keep every COPY-like route
candidate blocked until one of these policies is source/decode backed:

```text
blocked
source_template_fixed
last_physical_copy_lane_sets_one
child_edge_slot
```

The report must also carry a candidate/evidence matrix for every logical route
edge:

```text
child_edge_slot:
  candidate lane values may be all child_idx-derived, but this conflicts with
  last-COPY/FLOW evidence and still needs route child-slot/base-slot proof.

last_physical_copy_lane_sets_one:
  candidate lane values may be 0,0,0,1 for COPYT-expanded rows, but this
  conflicts with child_idx evidence and still needs slot provisioning proof.

source_template_fixed:
  preferred only when an exact source COPY/COPYT span, template hash, field
  provenance, endpoint match, and decode proof exist for the edge.
```

Until one candidate is selected with exact evidence, the matrix status remains
blocked and must retain:

```text
log10max_route_flow_ack_policy_missing
```

This RFC explicitly rejects silent `flow_ack=0`.

### 6. RouteInstFieldBindingRecord

Route bytes require all high-risk fields to have owners.

```python
@dataclass(frozen=True)
class RouteInstFieldBindingRecord:
    schema_version: str
    binding_id: str
    physical_row_plan_id: str

    route_byte_family_decision_id: str
    operand_patch_id: str
    route_endpoint_patch_id: str
    flow_ack_policy_id: str
    instruction_layout_plan_id: str
    exe_block_writer_plan_id: str
    instruction_boundary_plan_id: str
    component_placement_plan_id: str | None

    field_owner_ids: Mapping[str, str]
    field_owner_status: Mapping[str, Literal[
        "bound",
        "zero_with_evidence",
        "source_template_fixed",
        "pending",
        "blocked",
    ]]
    missing_fields: tuple[str, ...]
    binding_status: Literal[
        "candidate_field_bound",
        "component_field_bound",
        "blocked",
    ]
```

At minimum, these fields must be bound or intentionally blocked:

```text
opCode
unit_inst_type
latency
src_operands_idx
dst_operands_idx
dst_pes_pos
dst_blocks_idx
flow_ack
block_idx
end_inst
stage/local_pc
component_byte_offset
```

### 7. RouteInstRowByteCandidateRecord

Candidate bytes may be emitted only after the field binding record is closed
for row-body fields. Candidate bytes are not component rows.

```python
@dataclass(frozen=True)
class RouteInstRowByteCandidateRecord:
    schema_version: str
    candidate_id: str
    physical_row_plan_id: str
    field_binding_record_id: str

    raw_inst_t_row_bytes_sha256: str
    decoded_fields: Mapping[str, object]
    pending_decoded_fields: tuple[str, ...]
    field_owner_ids: Mapping[str, str]
    field_owner_status: Mapping[str, str]

    placement_status: Literal[
        "unplaced_candidate",
        "placed_candidate",
        "component_integrated",
        "blocked",
    ]
    component_byte_offset: int | None
    final_component_claim: bool
```

V1 candidate records must set:

```text
final_component_claim = false
placement_status != component_integrated
runtime_ready = false
```

## Invariants

1. Route row bytes must not be emitted from `RingEdgeRecord` alone.
2. Route push `src` allocation is in sender `(app_id, task_id, pe)` scope.
3. Route recv `dst` allocation is in receiver `(app_id, task_id, pe)` scope.
4. COPYT logical rows expand into physical COPY row candidates before bytes.
5. Every lane operand delta must be produced by a route operand patch, not by
   the serializer.
6. `flow_ack` must be field-owned. Silent zero-fill is forbidden.
7. `dst_pes_pos` and `dst_blocks_idx` must come from endpoint/layout plans.
8. `end_inst`, `block_idx`, and stage ordering must come from layout/boundary
   plans.
9. Candidate bytes may decode successfully and still be non-uploadable.
10. Final component integration is blocked until field binding, placement,
    decode, provenance, and package gates pass.

## Alternatives Considered

### Exact Source-template-fixed Route Spans

Accepted only as an evidence-backed materialization source. Exact A-line spans
may be used if they provide template hashes, row provenance, receiver patch
evidence, flow_ack evidence, and decode proof. They must not become the B-line
route semantic authority.

### Single COPY Per Edge

Rejected for V1. It may be sufficient for a 1024-bit physical lane, but it does
not prove full movement of the current 4096-bit replicated fp32 `GlobalMax`
value.

### LDN / Memory Materialization

Rejected for this path. The route ring is explicit communication. Using LDN
would turn it back into materialization/readback and reintroduce the PE00-style
ordering risk.

### Direct Route Reduce/Broadcast

Deferred. It is the long-term physical collective target, not the delivery-week
route byte family for log10max.

### Scalar-lane GlobalMax

Deferred. A scalar lane would reduce route bytes, but it requires scalar lane
storage and FMAX binding proof. V1 keeps replicated fp32 vector semantics.

## Migration / Implementation Plan

### Phase 2A: Decision and Physical Row Plans

Add:

```text
RouteByteFamilyDecisionReport
RoutePhysicalRowPlanReport
```

Pass criteria:

```text
30 logical route edges
120 physical COPY row plans
physical phase distribution = 48 / 12 / 12 / 48
all physical rows reference one logical route edge
all physical rows reference a RouteEndpointPatch
all rows use sender src allocation and receiver dst allocation
no row bytes claim
runtime_ready remains false
```

### Phase 2B: Operand and Field Binding

Add:

```text
RouteInstOperandPatchReport
FlowAckPolicyReport
RouteInstFieldBindingReport
```

Pass criteria:

```text
all 120 rows have allocation-backed src0/dst0
all lane deltas equal lane_index * OPERANDS_PER_OPERAND_RAM
src1/src2/dst1/dst2 have field usage masks
flow_ack is bound or candidate bytes are blocked
dst PE/block fields have owners
stage/local ordering proof exists
```

### Phase 2C: Candidate Bytes

Only if Phase 2B passes:

```text
emit RouteInstRowByteCandidateRecord
pack -> decode COPY opcode/unit/src/dst/dst_pe/dst_block/flow_ack
compare decoded fields to field owners
keep final_component_claim=false
```

### Phase 3: Component Integration

Out of scope for this RFC. Requires a follow-up implementation review.

## Validation Plan

Add narrow checkers:

```text
check_stream_compiler_log10max_route_byte_family_decision.py
check_stream_compiler_log10max_route_physical_row_plan.py
check_stream_compiler_log10max_route_inst_operand_patch.py
check_stream_compiler_log10max_route_inst_field_binding.py
check_stream_compiler_log10max_route_row_byte_candidate.py
```

Gate rules:

```text
route family not selected -> log10max_route_byte_family_missing
physical row count != 120 -> log10max_route_physical_row_count_mismatch
phase distribution mismatch -> log10max_route_physical_phase_distribution_mismatch
flow_ack unbound -> log10max_route_flow_ack_policy_missing
lane operand patch missing -> log10max_route_lane_operand_patch_missing
field owner missing -> log10max_route_inst_field_binding_missing
candidate bytes emitted with final_component_claim=true -> fail
component integration attempted from candidate-only rows -> fail
```

Existing package/runtime gates must continue to report:

```text
runtime_ready = false
uploadable = false
```

## Risks and Mitigations

### Risk: `flow_ack` policy is wrong.

Mitigation: keep it as a first-class `FlowAckPolicy`, validate slot bounds, and
stop before candidate bytes if source evidence or local package checks reject
the policy.

### Risk: COPYT lane expansion mismatches GlobalMax representation.

Mitigation: V1 binds `GlobalMax` to replicated fp32 vector and requires all four
lanes to be copied. Scalar-lane optimization is deferred.

### Risk: Route candidate bytes are mistaken for final component rows.

Mitigation: every candidate record carries `final_component_claim=false`,
`component_byte_offset=None` unless placed, and `runtime_ready=false`.

### Risk: The serializer reintroduces allocation or route decisions.

Mitigation: serializers may only pack `RouteInstFieldBindingRecord` outputs.
They cannot compute operands, destination PE/block, lane count, or flow_ack.

### Risk: A-line source-template evidence conflicts with B-line native family.

Mitigation: exact source-template spans remain a fallback. Conflicts block V1
candidate bytes rather than being silently resolved by the writer.

## Expected Effect

After Phase 2A/2B, B-line should be able to say:

```text
The log10max route byte family is selected.
Every logical route edge expands into deterministic physical COPY row plans.
Every physical route row has allocation-backed src/dst lane operands.
Every high-risk route field has an owner or a named blocker.
```

It must still say:

```text
Route rows are not final component rows.
log10max is not runtime_ready.
The customer package is not uploadable based on this RFC alone.
```

## Open Questions

1. Did Phase 2 prematurely assume COPYT?

   Recommendation: no. Phase 0/1 stayed undecided. Phase 2 chooses COPYT
   logical expansion for native V1 candidates because the current `GlobalMax`
   value is a 4096-bit replicated fp32 vector and the A-line mirror expands
   COPYT into lane COPY rows. Exact `source_template_fixed` evidence may still
   override the native candidate for a row if it passes all endpoint/layout/
   field-owner checks.

2. Should `flow_ack` use `last_physical_copy_lane_sets_one`,
   `child_edge_slot`, or exact source-template values for the first candidate?

   Recommendation: implement `FlowAckPolicy` with fail-closed evidence. Use
   `blocked` as the default report state. Use
   `last_physical_copy_lane_sets_one`, `child_edge_slot`, or
   `source_template_fixed` only when local checks and source evidence accept
   the selected policy. Until then, `log10max_route_flow_ack_policy_missing`
   must block COPY-like serialization.

3. Does `COPY` require `src1` for expanded COPYT rows in simulator `inst_t`?

   Recommendation: treat `src1` as a field-owned value. Do not zero-fill it
   without evidence.

4. Can a future scalar-lane GlobalMax use one physical COPY row?

   Recommendation: yes, but only in a later RFC after scalar-lane storage,
   FMAX, and postprocess bindings are proven.

5. Can route physical rows be fused into fewer exeBlocks?

   Recommendation: no for V1. One collective phase per exeBlock remains the
   default until ordering proof supports fusion.

## Recommended Decision

Accept Phase 2A and Phase 2B with strict gates.

```text
Do:
  select COPYT logical -> 4 COPY physical rows for GlobalMax V1
  model logical route edge and physical route rows separately
  bind lane operands through allocation-backed route patches
  make flow_ack a hard field-owned policy
  emit candidate bytes only after field ownership is closed

Do not:
  emit route bytes from RingEdgeRecord alone
  silently zero-fill flow_ack or src1
  use one COPY row for 4096-bit GlobalMax without proof
  insert route bytes into final components in this RFC
  claim runtime_ready or uploadable
```

In one sentence: Phase 2 may turn route endpoint/layout closure into
allocation-backed COPY row candidates, but it may not turn those candidates into
final component truth.
