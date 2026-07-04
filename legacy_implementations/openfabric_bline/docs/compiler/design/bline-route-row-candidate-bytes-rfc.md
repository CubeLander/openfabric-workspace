# RFC: B-line Route COPY Candidate Bytes and FlowAck Closure

## Status

Draft for review.

This RFC is the next high-risk boundary after the route byte-family work. It
asks whether B-line may move from report-only route rows to allocation-backed
COPY row candidate bytes for log10max `GlobalMax` routes.

## Summary

The current route path has reached a useful checkpoint:

```text
30 logical GlobalMax route edges
  -> COPYT logical route family selected
  -> 120 physical COPY lane row plans
  -> allocation-backed src0/dst0 patches
  -> dst_blocks_idx[0] bound from receiver exeBlock
  -> physical local_pc candidate-bound from sender layout
```

The only remaining route field-binding blockers are:

```text
flow_ack
component_byte_offset
```

The next phase must not jump straight to final CBUF/MICC component rows. It may
only:

```text
1. choose a candidate flow_ack policy with explicit evidence status;
2. pack/decode candidate COPY inst_t rows;
3. prove decoded fields match field-owner records;
4. keep final_component_claim=false, runtime_ready=false, uploadable=false.
```

This is a candidate-bytes bring-up RFC, not a final route-bytes RFC. After this
RFC, the strongest allowed claim is:

```text
120 COPY lane candidate rows pack/decode against field owners.
```

The forbidden claim remains:

```text
these route rows may enter insts_file.bin / CBUF / MICC / uploadable payloads.
```

This RFC proposes:

```text
Phase 3A:
  FlowAckPolicyCandidate chooses a candidate-only simulator inst_t policy.

Phase 3B:
  RouteInstRowByteCandidateRecord packs/decodes 120 COPY candidate rows.

Phase 3C:
  Candidate rows remain outside final components until a later component
  integration RFC.
```

## Current State

Known completed artifacts:

```text
RouteEndpointPatchReport:
  30 logical route endpoints
  sender/receiver PE and operand allocations known
  no row bytes

RouteLayoutPlanReport:
  route push/recv and FMAX update rows have layout candidates
  one collective phase per exeBlock
  component placement still unintegrated

RouteByteFamilyDecisionReport:
  logical_family = copyt_logical_globalmax_route
  physical_family = copyt_logical_expanded_copy_rows
  physical opcode = COPY
  lane_count = 4
  lane_stride = OPERANDS_PER_OPERAND_RAM

RoutePhysicalRowPlanReport:
  120 physical COPY lane row plans
  dst_block_binding_status = bound
  physical_local_pc_status = candidate_bound

RouteInstOperandPatchReport:
  120 allocation-backed src0/dst0 patches
  no serializer-side allocation

RouteInstFieldBindingReport:
  missing fields = flow_ack, component_byte_offset

FlowAckPolicyReport:
  default status = blocked
  candidate matrix compares child_edge_slot, last_physical_copy_lane_sets_one,
  and source_template_fixed
```

Current gate state remains:

```text
runtime_ready = false
uploadable = false
log10max = blocked
```

## A-line / Vendor Baseline Facts

`flow_ack` is the central unresolved field.

Known A-line facts:

```text
inst_map_common::setACKInst:
  flow_ack = child_idx

inst_blk_map::set_flag2_last_copy:
  selected last COPY rows get flow_ack = 1

program_legacy_inst.py::_set_stage_end_inst_flags:
  final FLOW rows get flow_ack = 1

task_print.cpp:
  COPY flow_ack projects to base_addr_idx

memory_template_check.py:
  flow_ack must be < BASE_ADDR_SLOT_COUNT
```

These facts conflict if interpreted as one universal rule. Therefore Phase 3
must distinguish:

```text
candidate-only simulator inst_t policy
exact source-template-fixed policy
final component policy
RTL/debug projection
```

The first can be tested with pack/decode and local structural checks. The last
three require stronger evidence and must not be implied by candidate bytes.

## Problem

B-line cannot pack candidate COPY rows while `flow_ack` is unbound, because
zero-filling it would hide an important route/base-slot choice in the byte
writer. But B-line also cannot make progress toward real route bytes if it keeps
`flow_ack` as an undifferentiated blocker forever.

The precise problem is:

```text
We need a candidate-only flow_ack policy that is explicit enough to pack and
decode simulator inst_t rows, but honest enough not to claim final component
correctness.
```

## Goals

1. Select a candidate-only `flow_ack` policy for simulator `inst_t` COPY rows.
2. Preserve exact A-line source-template spans as an override when available.
3. Emit candidate bytes only from fully bound field-owner records.
4. Decode candidate bytes and compare opcode/unit/operands/dst PE/dst block/
   flow_ack/end_inst/local_pc provenance.
5. Keep route rows out of final CBUF/MICC components.
6. Keep `runtime_ready=false` and `uploadable=false`.

## Non-goals

This RFC does not:

```text
choose final runtime route bytes
insert route rows into final insts_file.bin
modify MICC/exeBlock component rows
change runtime_ready or uploadable state
claim RTL projection correctness
resolve direct_route_reduce_broadcast
permit cross-task one-app communication
```

## Proposed Design

### 1. FlowAckPolicyCandidate

Add a candidate-only policy artifact:

```python
@dataclass(frozen=True)
class FlowAckPolicyCandidate:
    schema_version: str
    policy_id: str
    source_flow_ack_report_id: str
    applies_to: Literal["simulator_inst_t"]
    policy: Literal[
        "source_template_fixed",
        "last_physical_copy_lane_sets_one",
        "blocked",
    ]
    policy_status: Literal[
        "candidate_bound",
        "source_template_bound",
        "blocked",
    ]
    flow_ack_by_physical_row_id: Mapping[str, int]
    flow_ack_reason_by_physical_row_id: Mapping[str, str]
    base_slot_status: Literal[
        "range_checked",
        "asset_bound",
        "blocked",
        "not_applicable",
    ]
    base_slot_binding_id: str | None
    evidence_refs: tuple[str, ...]
    unresolved_conflicts: tuple[str, ...]
    final_component_claim: bool
    runtime_ready: bool
    uploadable: bool
```

Recommended V1 decision:

```text
If exact source-template spans exist:
  use source_template_fixed for those rows.

Else:
  use last_physical_copy_lane_sets_one as candidate-only simulator policy:
    lane 0..2 -> flow_ack = 0
    lane 3    -> flow_ack = 1

For the current 30 logical-edge, 4-lane COPYT expansion:
  physical COPY rows = 120
  flow_ack = 0 rows = 90
  flow_ack = 1 rows = 30

Expected flow_ack=1 phase distribution:
  row_reduce      = 12
  col_reduce      = 3
  col_broadcast   = 3
  row_broadcast   = 12

But:
  policy_status = candidate_bound
  base_slot_status = range_checked
  final_component_claim = false
  runtime_ready = false
  uploadable = false
```

Why this candidate is acceptable:

```text
It is backed by A-line last-COPY/FLOW evidence.
It keeps flow_ack explicit rather than zero-filled by writer.
It produces legal base slot values: 0 or 1, both < 4.
It can be rejected by candidate pack/decode or local package checks without
changing final component state.
```

`base_slot_status=range_checked` only means the candidate value is within
`BASE_ADDR_SLOT_COUNT`. Final component integration must later prove
`base_slot_status=asset_bound`, or prove that this simulator `inst_t` route path
does not require a runtime base-slot asset.

Why it is not final:

```text
inst_map_common::setACKInst also supports child_idx.
task_print maps flow_ack into a base-slot-like field.
No exact log10max route source span has proven which rule the customer runtime
requires for this operator.
```

Even when `policy_status=source_template_bound`, this RFC still requires:

```text
final_component_claim = false
runtime_ready = false
uploadable = false
```

Source-template evidence can strengthen a candidate field value. It does not
prove component placement, MICC/exeBlock coherence, payload freshness, or
runtime legality.

### 2. RouteInstRowByteCandidateRecord

Candidate bytes are a diagnostic / bring-up artifact.

```python
@dataclass(frozen=True)
class RouteInstRowByteCandidateRecord:
    schema_version: str
    candidate_id: str
    logical_route_edge_id: str
    physical_row_plan_id: str
    physical_lane_index: int
    physical_lane_count: int
    lane_stride: int
    lane_operand_delta: int
    field_binding_record_id: str
    operand_patch_id: str
    flow_ack_policy_candidate_id: str

    raw_inst_t_row_bytes_sha256: str
    decoded_fields: Mapping[str, object]
    decoded_field_owner_status: Mapping[str, str]
    decoded_field_owner_ids: Mapping[str, str]
    provenance_refs: tuple[str, ...]

    placement_status: Literal[
        "unplaced_candidate",
        "placed_candidate",
        "component_integrated",
    ]
    component_byte_offset: int | None
    final_component_claim: bool
    runtime_ready: bool
    uploadable: bool
```

Required candidate values:

```text
opcode/unit/latency:
  from RouteByteFamilyDecision

src_operands_idx/dst_operands_idx:
  from RouteInstOperandPatch

dst_pes_pos:
  from RouteEndpointPatch

dst_blocks_idx[0]:
  from receiver ExeBlockWriterPlan

flow_ack:
  from FlowAckPolicyCandidate

block_idx/local_pc/end_inst:
  from InstructionLayoutPlan / ExeBlockWriterPlan / InstructionBoundaryPlan

placement:
  placement_status = unplaced_candidate
  component_byte_offset = None
```

`component_byte_offset` is placement metadata, not an `inst_t` decoded field.
`physical_local_pc_status=candidate_bound` is layout provenance, not byte-field
decode proof.

Candidate reports must therefore keep these buckets separate:

```json
{
  "decoded_fields": {
    "opCode": "...",
    "unit_inst_type": "...",
    "src_operands_idx": "...",
    "dst_operands_idx": "...",
    "dst_pes_pos": "...",
    "dst_blocks_idx": "...",
    "flow_ack": "...",
    "end_inst": "..."
  },
  "layout_provenance": {
    "physical_row_plan_id": "...",
    "local_pc_candidate": "...",
    "phase": "...",
    "lane_idx": "..."
  },
  "placement": {
    "placement_status": "unplaced_candidate",
    "component_byte_offset": null
  }
}
```

### 3. Candidate Packer Boundary

Introduce a narrow packer helper:

```text
pack_route_copy_candidate_row(field_binding, operand_patch, flow_ack_candidate)
```

The helper may only consume field-owner artifacts. It must not:

```text
allocate operands
choose flow_ack
choose route family
choose dst PE/block
choose component offset
mutate final component files
```

Every serialized non-padding field must have an owner id or a
`zero_with_evidence` policy. The packer must not use default-fill logic such as:

```python
field_value = owner_values.get(field_name) or 0
```

That pattern is forbidden because it reintroduces serializer-side ownership.

### 4. Decode Roundtrip

Every candidate row must pass:

```text
decoded opcode == COPY
decoded unit == FLOW
decoded src0/dst0 match RouteInstOperandPatch
decoded unused operand fields match usage mask
decoded dst_pe/dst_block match endpoint/layout owners
decoded flow_ack match FlowAckPolicyCandidate
decoded final_component_claim == false
```

The checker must also verify lane structure:

```text
120 rows = 30 logical route edges * 4 physical lanes
each logical edge has lane_idx = 0, 1, 2, 3 exactly once
phase distribution = 48 / 12 / 12 / 48
same logical edge provenance across all four lanes
same sender/receiver PE across all four lanes
same dst block across all four lanes
src/dst operand offsets follow lane_stride policy
under last-lane candidate policy, flow_ack=1 iff lane_idx=3
flow_ack distribution = 90 zeros / 30 ones
flow_ack values are < BASE_ADDR_SLOT_COUNT
```

Byte-field roundtrip and layout/provenance roundtrip are distinct:

```text
byte fields:
  opcode, unit, operands, dst PE, dst block, flow_ack, end_inst,
  unused field masks

layout/provenance:
  physical_row_plan_id, local_pc candidate, source logical edge,
  phase, lane_idx, field owner ids
```

`flow_ack` and `end_inst` must have different owners. The candidate flow_ack
policy must not mutate or imply the `InstructionBoundaryPlan`.

The route byte candidate checker must fail if any candidate carries:

```text
component_integrated
component_byte_offset != None
runtime_ready = true
uploadable = true
```

It must also fail if any candidate row appears in a payload manifest or shadow
component artifact.

## Invariants

1. Candidate bytes are not final component rows.
2. `flow_ack` must come from `FlowAckPolicyCandidate`; the writer cannot fill it.
3. Candidate policy may be rejected without changing package state.
4. `component_byte_offset` remains `None`.
5. No route row may enter final CBUF/MICC in this RFC.
6. Candidate decode success does not imply SimICT execution.
7. Candidate decode success does not imply numerical correctness.
8. Candidate decode success does not clear `runtime_ready`.
9. Candidate-bound `flow_ack` does not clear final `flow_ack` policy blockers.
10. `flow_ack` is not an alias for `end_inst`.

## Alternatives Considered

### Keep flow_ack fully blocked

Rejected for this phase. It is safe but stops all route byte progress. We now
have enough evidence to emit candidate-only rows while keeping final gates
closed.

### Use child_edge_slot as V1 candidate

Deferred. It is real A-line evidence, but for the current representative ring
most route blocks have one logical outgoing edge, making `child_idx=0` hard to
distinguish from silent zero. It also conflicts with last-COPY/FLOW evidence.

### Use exact source_template_fixed only

Accepted as an override, rejected as the only path. Waiting for exact spans may
block progress. Candidate-only native rows are useful for pack/decode and field
ownership bring-up.

### Insert candidate rows into component files

Rejected. That is final integration and needs a separate RFC.

## Migration / Implementation Plan

### Phase 3A: Candidate flow_ack policy

Add:

```text
FlowAckPolicyCandidateReport
```

Pass criteria:

```text
120 candidate flow_ack values exist
flow_ack distribution = 90 zeros / 30 ones unless source_template_fixed overrides
flow_ack=1 phase distribution = 12 / 3 / 3 / 12
values are in [0, BASE_ADDR_SLOT_COUNT)
base_slot_status = range_checked
flow_ack reason exists for every physical row
candidate policy source is explicit
unresolved conflicts remain listed
final_component_claim=false
runtime_ready=false
```

### Phase 3B: COPY row candidate bytes

Add:

```text
RouteInstRowByteCandidateReport
check_stream_compiler_log10max_route_row_byte_candidate.py
```

Pass criteria:

```text
120 candidate rows emitted
120 rows are grouped as 30 logical route edges * 4 lanes
phase distribution = 48 / 12 / 12 / 48
120 candidate rows decode as COPY
src/dst/dst_pe/dst_block/flow_ack match field owners
flow_ack owner id is present
flow_ack owner is distinct from end_inst owner
component_byte_offset is None
final_component_claim=false
runtime_ready=false
uploadable=false
no candidate row appears in any payload manifest
```

### Phase 3C: Stop before component integration

Do not update:

```text
insts_file.bin
component payload manifests
MICC/exeBlock rows
runtime_ready gate to pass
uploadable state
```

## Validation Plan

New checks:

```text
check_stream_compiler_log10max_route_flow_ack_candidate.py
check_stream_compiler_log10max_route_row_byte_candidate.py
```

Existing checks must keep passing:

```text
check_stream_compiler_log10max_route_endpoint_patch.py
check_stream_compiler_log10max_route_layout_plan.py
check_stream_compiler_log10max_route_byte_family_decision.py
check_stream_compiler_log10max_route_physical_row_plan.py
check_stream_compiler_log10max_route_flow_ack_policy.py
check_stream_compiler_log10max_route_inst_operand_patch.py
check_stream_compiler_log10max_route_inst_field_binding.py
check_bline_runtime_ready_preintegration.py
```

Expected route field-binding state after Phase 3B:

```text
candidate_row_missing_fields:
  component_byte_offset only

final_component_blockers:
  log10max_route_flow_ack_final_policy_missing
  log10max_route_component_byte_offset_missing
  log10max_route_component_integration_missing
```

Expected runtime state:

```text
runtime_ready = false
uploadable = false
```

Expected blocker transition:

```text
Before Phase 3A:
  log10max_route_flow_ack_candidate_missing
  log10max_route_component_byte_offset_missing

After Phase 3A:
  flow_ack_candidate_bound
  log10max_route_flow_ack_final_policy_missing
  log10max_route_component_byte_offset_missing

After Phase 3B:
  route_candidate_bytes_emitted
  log10max_route_flow_ack_final_policy_missing
  log10max_route_component_byte_offset_missing
  log10max_route_component_integration_missing
```

## Risks and Mitigations

### Risk: Candidate flow_ack is wrong for runtime.

Mitigation: label it candidate-only and keep final integration blocked. Exact
source-template evidence can override it later.

### Risk: Candidate bytes are mistaken for final route bytes.

Mitigation: candidate records carry `final_component_claim=false`,
`component_byte_offset=None`, `runtime_ready=false`, and `uploadable=false`.
They also must not appear in a shadow component or payload manifest.

### Risk: The writer becomes a hidden backend.

Mitigation: the packer only consumes `RouteInstFieldBindingRecord`,
`RouteInstOperandPatch`, and `FlowAckPolicyCandidate`. It cannot choose route
family, operands, PE/block, or placement.

### Risk: FlowAckPolicyCandidate hides evidence conflict.

Mitigation: unresolved conflict refs stay in the report and package gate must
not treat candidate-bound as final-bound.

### Risk: `flow_ack=1` is confused with `end_inst=1`.

Mitigation: `flow_ack` is owned by `FlowAckPolicyCandidate`; `end_inst` remains
owned by `InstructionBoundaryPlan`. Candidate flow_ack policy must not alter
instruction boundary records.

### Risk: Candidate base-slot range check is mistaken for runtime asset binding.

Mitigation: Phase 3A/3B only require `base_slot_status=range_checked`. Final
component integration requires `asset_bound` or an explicit proof that this
simulator route path does not need a runtime base-slot asset.

## Expected Effect

After this RFC is implemented, B-line can say:

```text
log10max route COPY row candidates can be packed and decoded.
Every decoded route field is backed by an owner artifact.
flow_ack is explicit rather than writer-filled.
```

B-line still must say:

```text
route rows are not final component rows.
log10max is not runtime_ready.
the package is not uploadable because of these candidates.
```

## Open Questions

1. Does the customer runtime require `child_edge_slot` rather than last-COPY for
   this specific route shape?

   Recommendation: use exact source-template evidence or partner runtime
   feedback before final component integration.

2. Does `flow_ack=1` require a concrete base_addr slot in runtime assets for
   route-only COPY rows?

   Recommendation: candidate checks should run local package memory-template
   validation where possible. Phase 3A/3B only require range checking. Final
   integration must not proceed until a `BaseSlotBinding` or equivalent
   simulator-path exemption exists.

3. Should candidate rows be placed in a shadow component with offsets?

   Recommendation: not in this RFC. Shadow placement is too easy to confuse
   with final component placement. Candidate bytes stay report-only with
   `component_byte_offset=None`.

## Recommended Decision

Accept Phase 3A and Phase 3B only.

```text
Do:
  bind a candidate-only flow_ack policy
  emit route COPY candidate bytes
  decode and compare against field owners
  keep component integration blocked
  keep final flow_ack policy blocked

Do not:
  insert candidate rows into final CBUF/MICC
  mark runtime_ready/uploadable true
  claim final flow_ack correctness
  place candidate rows in a shadow component or payload manifest
  let writer choose fields
```

In one sentence: this RFC lets B-line turn owned route fields into candidate
COPY bytes, but not into deliverable component bytes.
