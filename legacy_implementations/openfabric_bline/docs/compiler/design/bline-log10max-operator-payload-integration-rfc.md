# RFC: B-line Log10max Operator Payload Integration and Runtime Gate

## Status

Draft for review.

This RFC is the next boundary after route-scope component integration.  The
current B-line log10max route path can now build a report-local route component
candidate by copying 120 route COPY candidate rows into PE-major component
offsets.  That is still not a full log10max operator payload, and it must not
be treated as `runtime_ready` or uploadable.

## Summary

Current checkpoint:

```text
log10max ring route:
  30 logical GlobalMax route edges
  -> 120 physical COPY lane rows
  -> allocation-backed src0/dst0 patches
  -> final simulator-inst_t flow_ack binding
  -> route component placement offsets
  -> route-scope component integration candidate
  -> route_slice_sha256 present

current gate:
  runtime_ready = false
  uploadable = false
  log10max = blocked
```

The route slice has crossed the route-row boundary, but the operator boundary
remains open:

```text
route rows alone are not a log10max operator
route candidate manifest is not the operator payload manifest
route-scope MICC coherence is not full operator MICC coherence
route component integration does not imply runtime_ready
```

This RFC proposes the smallest path from integrated route slice to an honest
operator-level payload candidate:

```text
Phase 5A:
  collect all log10max row-family slices into a single OperatorInstructionSliceSet.

Phase 5B:
  assemble a full insts component candidate only if every slice has copied bytes,
  component offsets, no-overwrite proof, and decode/provenance roundtrip.

Phase 5C:
  bind CBUF/MICC/package manifests from component candidates and runtime assets.

Phase 5D:
  let check_bline_runtime_ready_preintegration be the only runtime_ready
  aggregator.
```

Recommended decision:

```text
Accept Phase 5A/5B as report-local component assembly.
Accept Phase 5C only as operator payload candidate, not uploadable by itself.
Allow runtime_ready transition only through the existing preintegration gate.
```

## Current State

Known route artifacts:

```text
RouteFlowAckFinalPolicyReport:
  120 final-bound simulator-inst_t flow_ack fields
  scope = simulator_inst_t_only
  base_slot_status = asset_bound
  RTL projection not claimed

RouteComponentPlacementReport:
  120 route COPY placements
  component_byte_offset bound
  layout_epoch present
  lane group completion present
  route rows not component-mutated

RouteComponentIntegrationReport:
  120 route COPY rows copied from candidate bytes
  route_slice_sha256 present
  integration_scope = route_rows_only
  operator_payload_manifest_entries = []
  runtime_ready = false
  uploadable = false
```

Known local gate result:

```text
B-line runtime_ready pre-integration check OK
final_state = blocked
runtime_ready = false
uploadable = false
operator_states:
  gemm_no_relu = ready
  gemm_relu = blocked
  log10max = blocked
```

Known remaining boundary:

```text
log10max_operator_manifest_missing
log10max_operator_runtime_ready_gate_not_aggregated
```

Additional full-operator blockers may still exist outside the route slice:

```text
logspec elementwise row bytes / placement / component insertion
local_reduce row bytes / placement / component insertion
ring FMAX update allocation-backed final row bytes / placement / insertion
max_with_floor / postprocess row bytes / constants / placement / insertion
postprocess scale and store row bytes / placement / component insertion
MICC task / subtask / exeBlock coherence
runtime assets and manifest hash binding
```

## Problem

The current route slice is structurally meaningful but not sufficient for
operator delivery.  If package assembly consumes it directly as a final payload,
three failures become likely:

```text
1. partial component lie:
   route rows exist but compute/postprocess rows are missing or overwritten.

2. manifest lie:
   route_candidate_manifest_bound is mistaken for operator_manifest_bound.

3. readiness lie:
   a route-scope coherent slice is interpreted as full runtime_ready.
```

The immediate problem is not how to encode COPY rows anymore.  The immediate
problem is how to combine multiple row-family slices into one operator component
without losing ownership, provenance, and gate semantics.

## Goals

1. Define the artifact that collects all log10max instruction slices.
2. Define when a full `insts` component candidate may be assembled.
3. Define how CBUF/MICC/package manifests bind to that full candidate.
4. Preserve provenance from every final byte back to FiberOp / TemplateExpansion
   / OperandAllocation / field owner records.
5. Keep `runtime_ready` centralized in the preintegration gate.

## Non-goals

This RFC does not:

```text
change ring_spmd_row_then_col topology
add direct_route_reduce_broadcast
invent new communication IR
claim numerical correctness
claim SimICT execution
let serializer allocate operands or infer fields
allow route-only payloads to become uploadable
rewrite GEMM/GEMM+ReLU payload handling
```

## Proposed Design

### 1. OperatorInstructionSliceSet

Add a log10max-level slice collection artifact:

```python
@dataclass(frozen=True)
class OperatorInstructionSlice:
    schema_version: str
    slice_id: str
    operator: Literal["log10max"]
    slice_kind: Literal[
        "logspec_elementwise",
        "local_reduce",
        "route_copy",
        "ring_fmax_update",
        "max_with_floor",
        "postprocess_scale",
        "store",
    ]
    slice_status: Literal[
        "present",
        "blocked",
        "folded",
        "not_applicable",
    ]
    source_report_id: str
    covered_semantic_ops: tuple[str, ...]
    folded_into_slice_id: str | None
    folded_evidence_id: str | None
    integration_scope: Literal[
        "route_rows_only",
        "row_family_only",
        "full_operator_slice",
    ]
    row_count: int
    component_name: Literal["insts_file.bin"]
    row_ids: tuple[str, ...]
    component_byte_offsets: tuple[int, ...]
    row_sha256s: tuple[str, ...]
    slice_sha256: str
    placement_status: Literal["placed", "blocked"]
    byte_status: Literal["copied_from_candidate", "blocked"]
    no_overwrite_status: Literal["pass", "blocked"]
    decode_roundtrip_status: Literal["pass", "blocked"]
    provenance_status: Literal["pass", "blocked"]
    blocker_ids: tuple[str, ...]
```

The existing route component integration report becomes one slice:

```text
slice_kind = route_copy
slice_status = present
integration_scope = route_rows_only
row_count = 120
byte_status = copied_from_candidate
covered_semantic_ops = (route_globalmax_copy,)
```

Expected semantic coverage for log10max V1 is explicit:

```text
logspec_elementwise:
  clamp_min
  log2
  mul_log10_2

local_reduce:
  local_reduce_max

route_copy:
  route_globalmax_copy

ring_fmax_update:
  max_update_global_max

max_with_floor:
  global_max_minus_8
  max_with_floor

postprocess_scale:
  add_scalar_4
  mul_scalar_0_25

store:
  store_output
```

All required semantic ops must be covered exactly once or explicitly folded with
evidence.  Other slices must not be faked.  If logspec, local reduce, FMAX
update, max-with-floor, postprocess scale, or store rows are not integrated with
copied bytes and offsets, their slices are present as blocked records.

Add a set-level artifact:

```python
@dataclass(frozen=True)
class OperatorInstructionSliceSet:
    schema_version: str
    slice_set_id: str
    operator: Literal["log10max"]
    expected_row_families: tuple[str, ...]
    present_row_families: tuple[str, ...]
    folded_row_families: tuple[str, ...]
    missing_row_families: tuple[str, ...]
    blocked_row_families: tuple[str, ...]
    covered_semantic_ops: tuple[str, ...]
    missing_semantic_ops: tuple[str, ...]
    duplicate_semantic_ops: tuple[str, ...]
    slice_set_status: Literal["complete", "partial", "blocked"]
    layout_epoch: str | None
    layout_plan_sha256: str | None
    blocker_ids: tuple[str, ...]
```

`slice_status = folded` requires:

```text
folded_into_slice_id present
folded_evidence_id present
covered_semantic_ops non-empty
```

This lets intentionally folded work differ from missing work.

### 2. Full Insts Component Candidate

Add a full operator component candidate:

```python
@dataclass(frozen=True)
class OperatorInstsComponentCandidate:
    schema_version: str
    candidate_id: str
    operator: Literal["log10max"]
    source_slice_set_id: str
    component_name: Literal["insts_file.bin"]
    layout_epoch: str
    layout_plan_sha256: str
    component_size_bytes: int
    integrated_row_count: int
    expected_row_families: tuple[str, ...]
    present_row_families: tuple[str, ...]
    missing_row_families: tuple[str, ...]
    component_sha256: str | None
    diagnostic_partial_component_sha256: str | None
    active_row_count: int
    reserved_row_count: int
    zero_padding_row_count: int
    unowned_nonzero_row_count: int
    no_overwrite_status: Literal["pass", "blocked"]
    decode_roundtrip_status: Literal["pass", "blocked"]
    micc_coherence_status: Literal["not_checked", "pass", "blocked"]
    component_status: Literal[
        "full_operator_candidate",
        "partial_operator_candidate",
        "blocked",
    ]
    blocker_ids: tuple[str, ...]
```

Assembly rule:

```text
If any expected row family is missing:
  component_status = partial_operator_candidate
  component_sha256 = None
  diagnostic_partial_component_sha256 may be present
  runtime_ready = false

If all expected row families are present:
  assemble one full PE-major insts component candidate
  copy row bytes from slice records, never repack
  verify no offsets overlap
  decode every active row
  compare row field provenance
```

Expected row families for log10max V1:

```text
logspec_elementwise
local_reduce
route_copy
ring_fmax_update
max_with_floor
postprocess_scale
store
```

If V1 intentionally folds a family into another template, the slice set must
still name that decision explicitly:

```text
slice_kind = max_with_floor
slice_status = folded
folded_into_slice_id = ...
folded_evidence_id = ...
```

Silent omission is forbidden.

All pass slices must share the same:

```text
layout_epoch
layout_plan_sha256
```

unless a slice declares a reserved-slot compatibility proof.  The component
assembler must copy bytes from slice records:

```text
assembled_bytes[offset:offset+304] == source_slice.row_bytes
sha256(assembled_bytes[offset:offset+304]) == source_row_sha256
```

It must not call instruction packers or infer row fields.

Active and inactive rows are accounted separately:

```text
active_row_count
reserved_row_count
zero_padding_row_count
unowned_nonzero_row_count
```

`unowned_nonzero_row_count` must be zero.

### 3. MICC / CBUF Coherence Binding

Full instruction bytes are not enough.  Add a coherence report:

```python
@dataclass(frozen=True)
class OperatorControlCoherenceReport:
    schema_version: str
    report_id: str
    operator: Literal["log10max"]
    coherence_scope: Literal["full_operator"]
    source_component_candidate_id: str
    source_micc_candidate_id: str | None
    source_exeblock_component_id: str | None
    source_instance_component_id: str | None
    task_conf_status: Literal["pass", "blocked", "not_applicable"]
    subtask_conf_status: Literal["pass", "blocked", "not_applicable"]
    exe_block_row_count_status: Literal["pass", "blocked", "not_applicable"]
    stage_start_pc_status: Literal["pass", "blocked", "not_applicable"]
    stage_instruction_count_status: Literal["pass", "blocked", "not_applicable"]
    stage_pc_within_pe_local_inst_rows_status: Literal[
        "pass",
        "blocked",
        "not_applicable",
    ]
    active_exeblock_points_to_owned_rows_status: Literal[
        "pass",
        "blocked",
        "not_applicable",
    ]
    end_inst_boundary_status: Literal["pass", "blocked", "not_applicable"]
    successor_predecessor_status: Literal["pass", "blocked", "not_applicable"]
    root_reachability_status: Literal["pass", "blocked", "not_applicable"]
    instance_base_addr_status: Literal["pass", "blocked", "not_applicable"]
    blocker_ids: tuple[str, ...]
```

Coherence is full-operator scoped.  Route-scope coherence reports may feed this
check, but they cannot substitute for it.

### 4. Operator Payload Manifest Candidate

Add a manifest candidate separate from route candidate manifests:

```python
@dataclass(frozen=True)
class OperatorPayloadManifestCandidate:
    schema_version: str
    manifest_id: str
    operator: Literal["log10max"]
    source_component_candidate_id: str
    source_control_coherence_report_id: str
    files: Mapping[str, FileRecord]
    runtime_assets: Mapping[str, FileRecord]
    file_roles: Mapping[
        str,
        Literal[
            "insts_component",
            "exeblock_component",
            "instance_component",
            "cbuf_file",
            "tasks_component",
            "subtasks_component",
            "micc_file",
            "runtime_asset",
            "reference_asset",
        ],
    ]
    component_hashes: Mapping[str, str]
    readiness_claim: Literal[
        "blocked",
        "instruction_component_candidate",
        "dfu_component_candidate",
        "operator_payload_candidate",
        "runtime_ready_candidate",
    ]
    numerical_status: Literal["not_checked", "checked"]
    simict_status: Literal["not_run", "loads", "executes"]
    uploadable: bool
    blocker_ids: tuple[str, ...]
```

Rules:

```text
operator_payload_candidate:
  all required files and component hashes exist
  runtime assets exist
  local structural checks pass
  runtime_ready is still not implied

runtime_ready_candidate:
  candidate may be submitted to check_bline_runtime_ready_preintegration
  only that gate may aggregate final runtime_ready=true

uploadable:
  not set by this RFC directly
```

### 5. RuntimeReady Aggregation

No implementation module may set:

```text
runtime_ready = true
uploadable = true
```

Only:

```text
compiler/tools/check_bline_runtime_ready_preintegration.py
```

may aggregate these states after consuming:

```text
OperatorInstructionSliceSet
OperatorInstsComponentCandidate
OperatorControlCoherenceReport
OperatorPayloadManifestCandidate
existing package validation reports
```

## Invariants

1. Route slice integration is not operator integration.
2. Candidate row bytes must be copied into component candidates, not repacked.
3. Every active component row must map to exactly one source row record.
4. Every source row record must preserve FiberOp / TemplateExpansion /
   OperandAllocation / field-owner provenance when applicable.
5. Component offsets must be globally unique within the operator component.
6. Missing row families must be explicit blockers.
7. MICC coherence is full-operator scoped before manifest binding.
8. Operator manifest binding is distinct from route candidate manifest binding.
9. `runtime_ready` and `uploadable` are gate outputs, not writer outputs.
10. All pass slices in a full component candidate share one layout epoch and
    layout hash, unless an explicit reserved-slot compatibility proof is
    attached.
11. Partial component hashes must use `diagnostic_partial_component_sha256`;
    `component_sha256` is reserved for full operator candidates.

## Alternatives Considered

### A. Let route slice become the operator payload

Rejected.  It would hide missing compute/postprocess row families and produce a
route-only payload that looks structurally complete.

### B. Assemble component bytes by repacking row fields

Rejected.  This reopens serializer-side ownership.  The component assembler must
copy bytes already proven by row-family reports.

### C. Let each row-family report update the payload manifest

Rejected.  Manifest ownership must be operator-level.  Otherwise route,
FMAX-update, local-reduce, and postprocess slices can race each other and create
stale or partial manifests.

### D. Set runtime_ready from the payload assembler

Rejected.  Runtime readiness is a gate decision, not a package assembler side
effect.

## Migration / Implementation Plan

### Phase 5A: Slice Set

```text
[ ] Add OperatorInstructionSlice and OperatorInstructionSliceSet.
[ ] Project existing RouteComponentIntegrationReport into route_copy slice.
[ ] Add blocked slices for logspec_elementwise, local_reduce,
    ring_fmax_update, max_with_floor, postprocess_scale, and store when their
    bytes are missing.
[ ] Check covered_semantic_ops for exact coverage and no duplicates.
[ ] Add checker for expected row-family coverage.
```

Pass condition:

```text
route_copy slice present and pass
all missing row families explicitly named
all missing semantic ops explicitly named
slice_set_status = partial while non-route slices are blocked
runtime_ready = false
uploadable = false
```

### Phase 5B: Full Insts Component Candidate

```text
[ ] Assemble full insts component candidate only from pass slices.
[ ] Copy bytes from slice records.
[ ] Verify unique offsets and no overwrite.
[ ] Decode active rows from assembled component candidate.
[ ] Compare decoded fields/provenance to slice records.
```

Pass condition:

```text
component_status = full_operator_candidate only if all row families pass
otherwise partial_operator_candidate with blockers
partial_operator_candidate must not set component_sha256
```

### Phase 5C: Control Coherence

```text
[ ] Check task/subtask/exeBlock row counts.
[ ] Check stage_start_pc and instruction counts.
[ ] Check end_inst boundary ownership.
[ ] Check successor/predecessor and root reachability.
[ ] Check instance/base_addr requirements for active memory/COPY rows.
[ ] Check stage PCs are inside PE-local instruction capacity.
[ ] Check active exeBlocks point only to owned rows.
```

### Phase 5D: Payload Manifest Candidate

```text
[ ] Bind component hashes and runtime assets.
[ ] Keep route candidate manifest separate from operator manifest.
[ ] Distinguish insts/exeblock/instance components from final cbuf_file.
[ ] Distinguish task/subtask components from final micc_file.
[ ] Produce operator_payload_candidate only when all required files exist.
```

### Phase 5E: Runtime Gate Aggregation

```text
[ ] Teach check_bline_runtime_ready_preintegration.py to consume the new reports.
[ ] Emit blockers_by_layer for log10max.
[ ] Clear log10max blockers only through the gate.
[ ] Keep numerical_status separate.
```

## Validation Plan

Add focused tools:

```text
check_stream_compiler_log10max_operator_instruction_slice_set.py
check_stream_compiler_log10max_operator_insts_component_candidate.py
check_stream_compiler_log10max_operator_control_coherence.py
check_stream_compiler_log10max_operator_payload_manifest_candidate.py
```

Required assertions:

```text
route_copy slice row_count = 120
expected row families are exactly named
missing families are explicit blockers
covered semantic ops are exact, no duplicate coverage
all pass slices share layout_epoch/layout_plan_sha256
component offsets unique
assembled bytes are copied from slice bytes
unowned_nonzero_row_count = 0
decode roundtrip passes from assembled component candidate
operator manifest includes only full-operator candidates
preintegration gate remains the only runtime_ready aggregator
```

Regression checks:

```text
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_route_component_integration.py
PYTHONPATH=compiler python compiler/tools/check_bline_runtime_ready_preintegration.py
PYTHONPATH=compiler:compiler/tools pytest -q tests/test_stream_compiler_log10max_route_component_placement.py
```

## Risks and Mitigations

### Risk: partial operator component looks complete

Mitigation:

```text
component_status must be partial_operator_candidate while any row family is
missing.  operator_payload_manifest must reject partial candidates.
```

### Risk: route placement offsets collide with future compute rows

Mitigation:

```text
full layout_epoch and no-overwrite checks are required before full component
candidate status.
```

### Risk: manifest becomes stale

Mitigation:

```text
manifest candidate stores component hashes and source report ids.  Stale hash
mismatch is a blocker.
```

### Risk: runtime_ready is inflated

Mitigation:

```text
no report in this RFC can set runtime_ready=true.  Only the preintegration gate
can aggregate readiness.
```

## Expected Effect

After Phase 5A:

```text
route slice is a valid operator slice
missing non-route row families are explicit
runtime_ready remains false
```

After Phase 5B:

```text
full insts component candidate exists only if all row-family slices pass
otherwise partial candidate remains blocked
```

After Phase 5C/5D:

```text
operator-level CBUF/MICC/package candidate can be checked structurally
```

After Phase 5E:

```text
runtime_ready may become true only if the existing gate proves all local
structural/package requirements are closed
```

## Open Questions

1. Are local_reduce and max_with_floor V1 rows already available as source
   template fixed spans, or must they follow the same native row-byte pipeline?
2. Should ring FMAX update rows reuse the current FMAX placement candidate, or
   wait for allocation-backed final row bytes before entering the slice set?
3. Does store exist as a separate slice, or is it folded with postprocess_scale
   under explicit evidence?
4. Which runtime assets must be present before `operator_payload_candidate` is
   allowed for log10max?

## Recommended Decision

```text
Accept Phase 5A immediately.
Accept Phase 5B as report-local full component candidate assembly.
Accept Phase 5C/5D only as operator payload candidate construction.
Do not allow any module except check_bline_runtime_ready_preintegration.py
to set runtime_ready/uploadable.
```

Short version:

```text
Route slice is now real enough to become one operator slice.
It is not real enough to be the operator.
```

The next implementation should first build the slice set and expose exactly
which non-route row families still block log10max delivery.  That is the honest
bridge from route progress to full operator packaging.
