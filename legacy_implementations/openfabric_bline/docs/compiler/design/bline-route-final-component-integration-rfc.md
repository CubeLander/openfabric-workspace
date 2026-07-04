# RFC: B-line Route Final FlowAck and Component Integration

## Status

Draft for review.

This RFC is the next boundary after log10max route COPY candidate bytes.  The
current B-line route path can already produce 120 candidate-only COPY lane rows
and decode them back against field owners.  It still must not enter final CBUF /
MICC components until final `flow_ack`, component byte offsets, and component
coherence are explicitly owned and checked.

## Summary

Current checkpoint:

```text
30 logical GlobalMax route edges
  -> COPYT logical route family selected
  -> 120 physical COPY lane row plans
  -> allocation-backed src0/dst0 operand patches
  -> candidate flow_ack policy bound
  -> 120 COPY candidate rows pack/decode
  -> component_byte_offset = None
  -> runtime_ready = false
  -> uploadable = false
```

Remaining route blockers:

```text
log10max_route_flow_ack_final_policy_missing
log10max_route_component_byte_offset_missing
log10max_route_component_integration_missing
```

This RFC proposes the smallest final-integration path:

```text
Phase 4A:
  promote candidate flow_ack to a final simulator-inst_t policy only with
  BaseSlotBinding or exact source-template proof.

Phase 4B:
  assign component placement and component_byte_offset in a placement plan.

Phase 4C:
  insert route COPY rows into final insts component candidate and decode from
  the integrated component bytes.

Phase 4D:
  run package/preintegration gates.  Only then may route blockers be cleared.
```

This RFC may allow route rows to enter a final component candidate, but it does
not by itself make log10max numerically checked or SimICT-executed.

Acceptance split:

```text
Accept Phase 4A immediately.
Accept Phase 4B immediately.
Accept Phase 4C only with layout-epoch, lane-group completion,
no-overwrite, scoped-coherence, and manifest-scope checks.
```

## Current State

Known route artifacts:

```text
RouteEndpointPatchReport:
  30 logical route endpoints
  sender/receiver PE and operand allocations known

RouteLayoutPlanReport:
  90 route/update layout rows
  one collective phase per exeBlock
  component placement still unintegrated

RouteByteFamilyDecisionReport:
  logical_family = copyt_logical_globalmax_route
  physical_family = copyt_logical_expanded_copy_rows
  physical opcode = COPY
  lane_count = 4

RoutePhysicalRowPlanReport:
  120 physical COPY lane rows
  dst block bound
  physical local_pc candidate-bound

RouteInstOperandPatchReport:
  120 allocation-backed src0/dst0 patches

RouteInstRowByteCandidateReport:
  120 COPY candidate rows
  flow_ack distribution = 90 zero / 30 one
  candidate_decode_roundtrip pass
  component_byte_offset = None
```

Current gate state:

```text
runtime_ready = false
uploadable = false
log10max = blocked
```

## Problem

Candidate bytes prove that B-line can pack and decode COPY rows from owned
fields.  They do not prove final runtime legality.

The missing facts are:

```text
1. final flow_ack policy:
   candidate last-lane flow_ack=1 is not yet a final runtime/base-slot claim.

2. component byte offsets:
   candidate rows have no final insts_file.bin offsets.

3. component coherence:
   inserting 120 COPY rows must update or match exeBlock/stage/MICC metadata,
   row counts, stage PCs, end_inst boundaries, and package manifests.
```

If the serializer or package assembler fills any of these fields implicitly,
B-line regrows the hidden backend this work has been removing.

## Goals

1. Define when `flow_ack` may become final-bound for simulator `inst_t`.
2. Define a component placement artifact that owns `component_byte_offset`.
3. Define final route component insertion without changing route semantics.
4. Decode final component bytes and compare every route row to its candidate
   owner records.
5. Keep runtime readiness honest: integrated component bytes are necessary but
   not sufficient for numerical correctness or SimICT execution.

## Non-goals

This RFC does not:

```text
create a generic collective framework
change ring_spmd_row_then_col topology
claim direct_route_reduce_broadcast
allow cross-task one-app communication
change operand allocation
let serializer choose flow_ack or component offsets
prove numerical correctness
claim RTL/debug projection correctness
```

## Proposed Design

### 1. Final FlowAck Policy Binding

Add a final field-owner artifact:

```python
@dataclass(frozen=True)
class RouteFlowAckFinalPolicyBinding:
    schema_version: str
    binding_id: str
    source_candidate_report_id: str
    policy_scope: Literal["simulator_inst_t_only"]
    policy: Literal[
        "source_template_fixed",
        "last_physical_copy_lane_sets_one",
    ]
    applies_to: Literal["simulator_inst_t"]
    final_policy_status: Literal["final_bound", "blocked"]
    base_slot_status: Literal[
        "asset_bound",
        "simulator_path_exempt",
        "blocked",
    ]
    base_slot_evidence_id: str | None
    base_slot_binding_id: str | None
    memory_template_check_report_id: str | None
    simulator_path_exempt_reason: str | None
    simulator_path_exempt_evidence_id: str | None
    source_template_evidence_id: str | None
    source_template_sha256: str | None
    source_template_exactness_status: Literal[
        "exact_shape_match",
        "source_template_comparable",
        "not_applicable",
        "blocked",
    ]
    flow_ack_by_physical_row_id: Mapping[str, int]
    final_component_claim: bool
    runtime_ready: bool
    uploadable: bool
    blocker_ids: tuple[str, ...]
```

V1 promotion rule:

```text
If exact source-template COPY/COPYT spans exist:
  use source_template_fixed values and decode proof.

Else:
  promote last_physical_copy_lane_sets_one only if:
    all values are range-checked;
    BaseSlotBinding proves slots 0 and 1 are available for simulator inst_t;
    memory-template local validation accepts flow_ack values;
    final policy remains scoped to simulator inst_t, not RTL projection.
```

`simulator_path_exempt` is not a default.  It is allowed only with:

```text
simulator_path_exempt_reason
simulator_path_exempt_evidence_id
```

Without that proof, B-line assumes a concrete `BaseSlotBinding` is required.

`source_template_fixed` exactness requires:

```text
same opcode family
same lane_count
same lane_stride
same value representation
same src/dst PE relation kind
same task_axis / ordering domain
same simulator inst_t field layout
decoded flow_ack matches expected rows
source_template_sha256 present
```

Partial similarity is `source_template_comparable`, not `final_bound`.

This clears:

```text
log10max_route_flow_ack_final_policy_missing
```

only when `final_policy_status=final_bound`.

### 2. Route Component Placement Plan

Add a placement artifact:

```python
@dataclass(frozen=True)
class RouteComponentPlacementRecord:
    schema_version: str
    placement_id: str
    physical_row_plan_id: str
    row_byte_candidate_id: str
    logical_route_edge_id: str
    phase: Literal[
        "row_reduce",
        "col_reduce",
        "col_broadcast",
        "row_broadcast",
    ]
    app_id: int
    task_id: int
    src_pe: str
    pe_index: int
    pe_local_pc: int
    inst_per_pe: int
    physical_local_pc: int
    instruction_layout_plan_id: str
    layout_epoch: str
    layout_plan_sha256: str
    reserved_row_policy_id: str | None
    component_name: Literal["insts"]
    component_row_index: int
    component_byte_offset: int
    row_size_bytes: int
    exe_block_writer_plan_id: str
    instruction_boundary_plan_id: str
    placement_status: Literal["placed", "blocked"]
    blocker_ids: tuple[str, ...]
```

Placement rules:

```text
component_row_index = pe_index * inst_per_pe + pe_local_pc
component_byte_offset = component_row_index * sizeof(inst_t)
sizeof(inst_t) = 304
row ordering must match InstructionLayoutPlan physical_local_pc
one collective phase remains one exeBlock unless a separate fusion proof exists
all component_row_index values are unique within the insts component
candidate rows must not be re-packed differently during placement
0 <= pe_local_pc < inst_per_pe
component_byte_offset + 304 <= insts_component_size
```

Route placement is valid only against a frozen `InstructionLayoutPlan` or a
placement plan with explicit reserved holes for not-yet-integrated rows:

```text
layout_epoch must be stable
layout_plan_sha256 must match route placement and exeBlockWriterPlan
reserved_row_policy_id is required if local_reduce/FMAX/postprocess rows are
not yet integrated
```

PE coordinate to PE index mapping must be source-backed or profile-backed.  If
the mapping is unknown, placement is blocked rather than guessed.

This clears:

```text
log10max_route_component_byte_offset_missing
```

only when all 120 placement records are `placed`.

### 3. Final Route Component Insertion

Before insertion, add lane-group completion metadata:

```python
@dataclass(frozen=True)
class RouteLaneGroupCompletion:
    schema_version: str
    logical_route_edge_id: str
    physical_row_ids: tuple[str, ...]
    lane_count: int
    completion_lane_index: int
    completion_flow_ack_value: int
    receiver_ready_value_id: str
    completion_status: Literal["bound", "blocked"]
    blocker_ids: tuple[str, ...]
```

Checks:

```text
each logical edge has exactly four physical rows
lane indexes are 0, 1, 2, 3 exactly once
only lane 3 has flow_ack=1 under last-lane policy
paired route_recv / FMAX update depends on lane-group completion
```

Add an integrated component artifact:

```python
@dataclass(frozen=True)
class RouteComponentIntegrationReport:
    schema_version: str
    report_id: str
    source_row_candidate_report_id: str
    source_flow_ack_final_policy_id: str
    source_placement_report_id: str
    component_name: Literal["insts"]
    integrated_row_count: int
    integrated_byte_count: int
    component_sha256: str
    decoded_row_count: int
    decode_roundtrip_status: Literal["component_decode_roundtrip", "blocked"]
    micc_coherence_scope: Literal[
        "route_rows_only",
        "full_collective_phase",
        "full_log10max_operator",
    ]
    exe_block_row_count_status: Literal["coherent", "blocked"]
    stage_start_pc_status: Literal["coherent", "blocked"]
    stage_instruction_count_status: Literal["coherent", "blocked"]
    end_inst_boundary_status: Literal["coherent", "blocked"]
    successor_predecessor_status: Literal["coherent", "blocked"]
    root_reachability_status: Literal["coherent", "blocked"]
    task_subtask_stamp_status: Literal["coherent", "blocked"]
    payload_manifest_status: Literal[
        "route_candidate_manifest_bound",
        "operator_manifest_bound",
        "blocked",
    ]
    component_integration_scope: Literal[
        "route_rows_only",
        "full_operator_inst_component",
    ]
    route_component_integrated_claim: bool
    runtime_ready_candidate: bool
    uploadable: bool
    blocker_ids: tuple[str, ...]
```

Insertion rules:

```text
Integrated bytes must equal candidate row bytes at each placement offset.
Decoded final bytes must match candidate decoded fields.
flow_ack must come from RouteFlowAckFinalPolicyBinding.
component_byte_offset must come from RouteComponentPlacementRecord.
MICC/exeBlock row counts and stage_start_pc must reference the same rows.
Payload manifest may reference the integrated route slice only after hashes
match.  `operator_manifest_bound` is out of scope unless the full operator gate
is closed.
Integrated route rows must not overwrite existing non-route rows unless the
overwritten row is an explicitly reserved placeholder from the same
`layout_epoch`.
```

This clears:

```text
log10max_route_component_integration_missing
```

only when:

```text
decode_roundtrip_status = component_decode_roundtrip
component_integration_scope = route_rows_only
all route-scope MICC/exeBlock coherence substatuses = coherent
payload_manifest_status = route_candidate_manifest_bound
overwrite policy passes
```

### 4. Runtime Gate Semantics

After Phase 4C, B-line may claim:

```text
route component integrated structurally
local component decode/provenance gate passed
```

B-line still must not automatically claim:

```text
SimICT execution
numerical correctness
performance acceptability
RTL projection correctness
```

`runtime_ready` may become true only if the existing preintegration gate sees
all operator-level blockers closed, including non-route log10max blockers.

No report in this RFC may set `runtime_ready=true` directly.  Only
`check_bline_runtime_ready_preintegration.py` may aggregate runtime readiness.

## Invariants

1. Serializer never chooses `flow_ack`.
2. Serializer never chooses `component_byte_offset`.
3. Candidate bytes may be inserted only if their SHA/decoded fields match.
4. `flow_ack` final binding and `end_inst` boundary binding remain separate.
5. Component placement must be unique and aligned to `sizeof(inst_t)=304`.
6. MICC/exeBlock metadata must be coherent with route row placement.
7. Cross-task one-app route cooperation remains forbidden.
8. `runtime_ready` and `uploadable` are gate outputs, not writer claims.
9. Route placement must use a frozen layout epoch or explicit reserved slots.
10. FMAX update consumes a completed route lane group, not an arbitrary lane.
11. Route integration is scoped; it does not imply full operator component finality.
12. Component insertion must not overwrite non-route rows except owned reserved slots.

## Alternatives Considered

### Ship candidate bytes directly

Rejected. Candidate bytes intentionally have no component offsets or final
`flow_ack` policy. Treating them as final rows would bypass the owner chain.

### Require exact source-template route spans only

Deferred as a final-policy preference, rejected as the only path. It is safe
when available but may block progress if exact spans are missing. V1 can promote
last-lane flow_ack if base-slot assets and local package checks close.

### Shadow component before final placement

Rejected. A shadow component is too easy to confuse with real payload state.
Use report-only placement until component integration is explicitly performed.

### Merge all ring phases into fewer exeBlocks

Deferred. V1 keeps one collective phase per exeBlock. Fusion requires a separate
ordering proof and is not needed to close this route blocker.

## Migration / Implementation Plan

### Phase 4A: Final flow_ack binding

Add:

```text
RouteFlowAckFinalPolicyBindingReport
check_stream_compiler_log10max_route_flow_ack_final_policy.py
```

Pass criteria:

```text
120 final flow_ack values exist
values match candidate or source-template proof
base_slot_status = asset_bound or simulator_path_exempt
flow_ack owner is distinct from end_inst owner
final_component_claim = false
runtime_ready = false
uploadable = false
```

### Phase 4B: Component placement plan

Add:

```text
RouteComponentPlacementPlanReport
check_stream_compiler_log10max_route_component_placement.py
```

Pass criteria:

```text
120 placement records exist
component_row_index = pe_index * inst_per_pe + pe_local_pc
component_byte_offset = component_row_index * 304
row indexes unique
phase distribution = 48 / 12 / 12 / 48
placement follows physical_local_pc ordering
layout_epoch / layout_plan_sha256 present
reserved slots declared if non-route rows are not integrated
PE-local capacity and component section bounds pass
no component file is mutated yet
runtime_ready = false
uploadable = false
```

### Phase 4C: Component integration candidate

Add:

```text
RouteComponentIntegrationReport
check_stream_compiler_log10max_route_component_integration.py
```

Pass criteria:

```text
120 rows inserted into insts component candidate
30 RouteLaneGroupCompletion records are bound
integrated row bytes equal candidate row bytes
decoded integrated rows match field owners
component sha256 present
no non-route row is overwritten except owned reserved slots
route-scope MICC/exeBlock coherence check passes
route candidate manifest hash check passes
runtime_ready is decided only by preintegration gate
```

### Phase 4D: Gate aggregation

Update preintegration only after Phase 4C checks pass:

```text
flow_ack_status = bound
component_placement_status = component_integrated
route_candidate_decode_status = component_decode_roundtrip
candidate_decode_roundtrip_is_uploadable = false
component_integrated_required_for_runtime_ready = true
```

The route gate may stop blocking. The whole log10max operator may still be
blocked by local_reduce, max_with_floor, postprocess, or package-level gaps.

## Validation Plan

Required checks:

```text
check_stream_compiler_log10max_route_flow_ack_final_policy.py
check_stream_compiler_log10max_route_component_placement.py
check_stream_compiler_log10max_route_component_integration.py
check_stream_compiler_log10max_route_row_byte_candidate.py
check_bline_runtime_ready_preintegration.py
```

Required assertions:

```text
no serializer-side flow_ack fill
no serializer-side component offset fill
120 integrated rows decode as COPY
flow_ack distribution remains explainable
component offsets are unique and aligned
route candidate manifest hash matches component bytes
lane-group completion is bound for 30 logical edges
no-overwrite policy passes
coherence status is scoped to route rows unless full phase/operator is proven
runtime_ready/uploadable are not manually set
```

## Risks and Mitigations

### Risk: final flow_ack policy is wrong for partner runtime.

Mitigation: prefer exact source-template evidence. If using last-lane policy,
require base-slot binding and memory-template validation, and label the policy
as simulator-inst_t scoped.

### Risk: component placement corrupts exeBlock ordering.

Mitigation: keep one phase per exeBlock and validate `physical_local_pc`,
`stages_start_pc`, `end_inst`, row counts, and successor/predecessor coherence.
Require a frozen `layout_epoch` or explicit reserved slots before assigning
component offsets.

### Risk: integrated bytes differ from candidate bytes.

Mitigation: compare SHA/decoded fields before and after placement. Component
writer may concatenate bytes; it may not repack fields.

### Risk: lane group appears complete too early.

Mitigation: require `RouteLaneGroupCompletion` for every logical route edge.
Receiver update/FMAX may depend only on group completion, not a single lane row.

### Risk: route rows overwrite compute rows.

Mitigation: component integration uses `reserved_slot_only` overwrite policy.
Any overwrite of a non-route row blocks unless the target is an owned reserved
slot from the same `layout_epoch`.

### Risk: package manifest makes route rows look uploadable too early.

Mitigation: Phase 4C may produce only a route candidate manifest. Operator
manifest binding is decided by package/preintegration after all operator
blockers close. `runtime_ready` remains a gate result.

## Expected Effect

After this RFC is implemented, B-line may say:

```text
log10max route COPY rows are final-flow_ack-bound.
route COPY rows have component byte offsets.
route COPY rows are integrated into a local component candidate and decode back.
```

B-line must still say, unless later gates prove otherwise:

```text
SimICT execution is not implied.
Numerical correctness is not implied.
Non-route log10max blockers may still block runtime_ready.
```

Expected blocker transition:

```text
After Phase 4A:
  clear log10max_route_flow_ack_final_policy_missing
  keep log10max_route_component_byte_offset_missing
  keep log10max_route_component_integration_missing
  optional warning: log10max_route_flow_ack_policy_simulator_inst_t_scoped

After Phase 4B:
  clear log10max_route_component_byte_offset_missing
  keep log10max_route_component_integration_missing
  keep log10max_route_full_layout_epoch_not_frozen if layout is not frozen

After Phase 4C:
  clear log10max_route_component_integration_missing for route scope only
  preserve non-route blockers such as local_reduce/max_with_floor/postprocess
```

## Open Questions

1. Is exact source-template evidence available for the final log10max route
   shape?

   Recommendation: use it if present. Otherwise use last-lane only with
   base-slot binding and local memory-template validation.

2. Does simulator `inst_t` route `flow_ack` require a concrete runtime
   `BaseSlotBinding` asset?

   Recommendation: assume yes unless local package validation or partner docs
   prove exemption.

3. Should route rows integrate into the same insts component as existing
   candidate rows or into a route-specific component region first?

   Recommendation: one final insts component is the target, but Phase 4B may
   first produce placement records without mutating files.

## Recommended Decision

Accept Phase 4A and Phase 4B immediately.  Accept Phase 4C only after final
flow_ack and placement checks pass, and only with the additional layout-epoch,
lane-group, no-overwrite, scoped-coherence, and manifest-scope checks.

```text
Do:
  bind final simulator flow_ack explicitly
  assign component_byte_offset from a placement plan
  integrate route rows only after byte/placement owners close
  require lane-group completion before receiver update consumption
  scope component integration to route rows unless full operator is proven
  decode integrated component bytes
  let preintegration decide runtime_ready

Do not:
  let serializer choose flow_ack or offsets
  merge ring phases without ordering proof
  overwrite non-route rows except owned reserved slots
  bind operator upload manifest from route-slice integration alone
  claim numerical correctness
  claim SimICT execution
  set runtime_ready/uploadable manually
```

In one sentence: this RFC is the controlled bridge from report-only route
candidate bytes to final component bytes, with `flow_ack`, offsets, and manifest
coherence owned before any package claim.
