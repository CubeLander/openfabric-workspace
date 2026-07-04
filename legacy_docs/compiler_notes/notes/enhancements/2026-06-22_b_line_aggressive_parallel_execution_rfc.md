# RFC: B-line Aggressive Parallel Execution Plan

Date: 2026-06-22
Status: Accepted with execution amendments for delivery week 2026-06-22..2026-06-28
Scope: B-line GEMM, GEMM+ReLU, log10max, DFU3500 binary lowering, runtime-ready gate

## Summary

The decision under review is how to execute the mandatory B-line operator
delivery plan with maximum parallelism.  The previous delivery RFC defines what
must be delivered:

```text
2026-06-23: GEMM uploadable binary package
2026-06-24: GEMM+ReLU uploadable binary package
2026-06-25: log10max uploadable binary package with declared DFU3500 collective strategy
2026-06-26: customer-facing three-operator bundle
```

This RFC defines how to staff and sequence the work so the team does not
serialize independent tasks behind the GEMM writer.  The recommended decision:

```text
Run seven workstreams in parallel immediately.
Use narrow interface contracts at merge points.
Treat runtime_ready as the common uploadable gate.
Do not wait for full GEMM package completion before starting ReLU or log10max.
Do not let log10max collective remain symbolic.
```

Accepted execution amendments:

```text
1. Every stream must have DRI, deputy, merge reviewer, daily artifact, and
   blocking signal before execution is considered staffed.
2. S0 is the merge control plane, not a package helper.
3. All streams merge through schema artifacts, not prose status.
4. runtime_ready means local structural/package readiness only; it does not
   claim SimICT execution or numerical correctness.
5. Blockers use a common severity ladder and explicit escalation deadlines.
```

## Current State

Known facts:

```text
GEMM no-ReLU:
  TemplateOps = 960
  instruction rows = 896
  zero boundaries = 64
  runnability_state = emittable_debug

GEMM+ReLU:
  TemplateOps = 1024
  ReLU TemplateOps = 64 symbolic_unresolved
  current state = layout_candidate / fail-closed

Packable candidates:
  instance_conf_info_t
  task_conf_info_t
  exeBlock_conf_info_t

Blocked:
  inst_t_fields
  sub_task_conf_info_t.instances_conf_mem_based_addr

Validation:
  archive_runtime_ready_gate(payload_dir) exists
  partner entrypoint guard can detect stale payloads
```

Current implementation pressure:

```text
MICC/control:
  task writer
  exeBlock writer
  subtask writer
  instance-table address semantics

CBUF/instruction:
  inst_t minimal writer
  template overlay / field contract
  CBUF assembly

Operators:
  ReLU concrete binding
  log10max elementwise/reduce templates
  log10max minimum DFU3500 collective strategy

Package:
  result/config/simulator_bin layout
  manifest/runtime/reference assets
  runtime_ready gate
  bundle metadata
```

## Problem

The delivery plan will fail if work is executed as a single chain:

```text
instance writer
  -> task writer
  -> exeBlock writer
  -> subtask writer
  -> inst_t writer
  -> CBUF/MICC assembly
  -> ReLU
  -> log10max
  -> package gate
```

This chain is too slow because `inst_t`, ReLU binding, log10max capacity proof,
minimum collective lowering, and package gate can all start before the MICC
writers are complete.  The correct execution model is a parallel fan-out with
small, explicit merge contracts.

## Goals / Non-goals

Goals:

```text
1. Maximize parallel engineering throughput this week.
2. Make dependencies explicit enough to assign owners independently.
3. Start all long-pole work immediately.
4. Keep B-line semantic/source plan as authority.
5. Ensure every uploadable artifact passes runtime_ready.
6. Ensure log10max allreduce work is a P0 stream, not a late fallback.
```

Non-goals:

```text
1. Do not build generic allreduce framework before V1.
2. Do not finish general elementwise fusion before GEMM+ReLU.
3. Do not migrate folded rows as default unless expanded path blocks delivery.
4. Do not build a new validation framework.
5. Do not let tactical bridge code inspect frontend ops as semantic authority.
```

## Proposed Design

### Parallel Workstreams

Start these seven workstreams immediately:

```text
S0: Delivery gate and bundle contract
S1: MICC/control component writers
S2: CBUF/inst_t writer and CBUF assembly
S3: GEMM package assembly
S4: GEMM+ReLU concrete binding
S5: log10max capacity proof and minimum collective strategy
S6: log10max elementwise/reduce template binding
```

The streams run in parallel but merge through typed artifacts:

```text
VendorComponentPlan
  -> ComponentWriterArtifacts
  -> OperatorPayloadManifest
  -> runtime_ready report
  -> customer bundle metadata
```

### Stream Ownership Matrix

The following fields must be filled with concrete names before the stream is
allowed to claim staffed execution.  Role names below are placeholders for
assignment, not substitutes for people.

```text
S0: Delivery gate and bundle contract
  DRI: TBD
  deputy: TBD
  merge reviewer: delivery lead
  daily merge artifact: operator_delivery_status.schema.json
  blocking signal: schema/gate cannot classify stream artifacts

S1: MICC/control component writers
  DRI: TBD
  deputy: TBD
  merge reviewer: ABI/layout reviewer
  daily merge artifact: micc_writer_status.<operator>.json
  blocking signal: cannot emit MICC rows without unknown address/field semantics

S2: CBUF/inst_t writer and CBUF assembly
  DRI: TBD
  deputy: TBD
  merge reviewer: instruction/template reviewer
  daily merge artifact: inst_writer_report.<operator>.json
  blocking signal: cannot emit concrete rows without forbidden/unknown fields

S3: GEMM package assembly
  DRI: TBD
  deputy: TBD
  merge reviewer: S0 DRI
  daily merge artifact: gemm_no_relu/operator_payload_manifest.json
  blocking signal: package shell cannot reach runtime_ready with meaningful blockers

S4: GEMM+ReLU concrete binding
  DRI: TBD
  deputy: TBD
  merge reviewer: operator/template reviewer
  daily merge artifact: gemm_relu/relu_binding_decision.json
  blocking signal: ReLU cannot become concrete without dropping or misordering store

S5: log10max capacity proof and minimum collective strategy
  DRI: TBD
  deputy: TBD
  merge reviewer: collective/memory reviewer
  daily merge artifact: log10max/selected_collective_strategy.json
  blocking signal: no strategy proves scalar visibility for customer shape

S6: log10max elementwise/reduce template binding
  DRI: TBD
  deputy: TBD
  merge reviewer: instruction/template reviewer
  daily merge artifact: log10max/local_template_pack.status.json
  blocking signal: local template pack cannot become concrete
```

Deputy is required for S1, S2, S4, and S5 because those are long-pole streams.
The deputy must be able to continue the stream if the DRI is unavailable.

### S0: Delivery Gate And Bundle Contract

Owner profile:

```text
validation/runtime/package engineer
```

Execution role:

```text
S0 is the merge control plane.
Other streams do not report "done" directly to the customer bundle.
Other streams submit schema artifacts to S0.
S0 owns readiness transitions and final bundle labels.
```

Can start now:

```text
1. Keep archive_runtime_ready_gate as the single uploadable gate.
2. Add operator-level delivery metadata schema.
3. Add check_dfu_delivery_candidate.py thin CLI if needed.
4. Define bundle JSON labels for all three operators.
5. Ensure payload builder never leaves stale manifest claims.
6. Publish schema_version and allowed enum values.
7. Reject private metadata fields.
8. Archive failed runtime_ready reports.
```

Inputs:

```text
payload_dir
operator name
selected strategy
shape metadata
runtime/numerical status
```

Outputs:

```text
validation/runtime_ready.json
operator_delivery_status.json
customer_bundle_manifest.json
```

Hard dependencies:

```text
None for schema/tooling.
Needs S3/S4/S5/S6 payloads to validate real operators.
```

Must not block on:

```text
inst_t complete
ReLU template complete
log10max allreduce complete
```

Readiness semantics:

```text
binary_emitted:
  component bytes exist

runtime_ready:
  local structural/package gate passes
  payload files exist
  manifest claims match files
  runtime/reference assets exist
  selected representation/strategy is declared
  no symbolic_unresolved row is emitted
  stale payload claims are rejected

uploadable:
  runtime_ready pass
  payload can be handed to partner upload path

simict_loads:
  partner runtime accepts package and launch/control files

simict_executes:
  operator completes execution

numerically_checked:
  output matches host reference under declared tolerance
```

`runtime_ready` does not mean:

```text
SimICT executed successfully
numerical correctness was checked
log10max performance is acceptable
direct physical allreduce exists
```

S0 owns state transitions:

```text
S1/S2/S4/S5/S6 artifacts
  -> S0 schema validation
  -> S0 readiness aggregation
  -> S3/package assembly consumes only S0-accepted artifacts
```

### S1: MICC/Control Component Writers

Owner profile:

```text
binary struct / ABI engineer
```

Can start now:

```text
1. Implement task_conf_info_t writer.
2. Implement exeBlock_conf_info_t writer.
3. Define InstanceTableAddress.
4. Implement sub_task_conf_info_t writer.
5. Enforce instances_amount/address zero invariant.
6. Emit MICC component files with padding policy.
```

Inputs:

```text
VendorComponentPlan
SerializerReadinessPlan
FieldOffsetPreflightPlan
InstanceTableAddress contract
```

Outputs:

```text
tasks_conf_info_file.bin
exeblock_conf_info_file.bin
subtasks_conf_info_file.bin
instance_conf_info_file.bin
MICC component manifest
```

First merge artifact for 2026-06-22:

```json
{
  "schema_version": "instance_table_address_v1",
  "addr_space": "instance_component_offset",
  "unit": "bytes",
  "row_index_base": 0,
  "byte_offset_formula": "row_index * sizeof(instance_conf_info_t)",
  "sizeof_instance_conf_info_t": 32,
  "zero_instances_policy": {
    "instances_amount_eq_0": "address_must_be_zero_and_ignored",
    "instances_amount_gt_0": "address_zero_means_row0"
  },
  "evidence": "serializer_readiness + field_offset_preflight"
}
```

Hard rule:

```text
address = 0 cannot mean both disabled and row0.
If instances_amount == 0, address 0 is ignored.
If instances_amount > 0, address 0 means row0.
```

Hard dependencies:

```text
sub_task_conf_info_t writer depends on InstanceTableAddress.
final MICC assembly depends on task/exeBlock/subtask/instance writers.
```

Soft dependencies:

```text
Can use no-ReLU GEMM component rows first.
ReLU and log10max can add rows later through same interface.
```

### S2: CBUF/inst_t Writer And CBUF Assembly

Owner profile:

```text
instruction template / CBUF engineer
```

Can start now:

```text
1. Implement minimal inst_t writer for existing GEMM template rows.
2. Define raw_template_overlay mode.
3. Classify every inst_t field as source-backed, template-backed, zero-fill, or forbidden.
4. Reject symbolic_unresolved rows.
5. Assemble simulator_bin/insts_file.bin and result/config cbuf_file.bin.
6. Add opcode/unit/latency sanity to writer output if not already covered by validation.
```

Inputs:

```text
BinaryLayoutPlan.instruction_rows
TemplateOpPlan concrete instruction intents
legacy template evidence
inst_t field contract
```

Outputs:

```text
insts_file.bin
cbuf_file.bin
inst_writer_report.json
```

Hard dependencies:

```text
Needs concrete template rows for the operator being emitted.
GEMM can start immediately.
GEMM+ReLU needs S4 ReLU binding.
log10max needs S6 elementwise/reduce/allreduce binding.
```

Must not wait for:

```text
sub_task_conf_info_t writer
final MICC assembly
```

### S3: GEMM Package Assembly

Owner profile:

```text
operator package integrator
```

Can start now:

```text
1. Define GEMM package directory shape.
2. Wire S1 MICC outputs and S2 CBUF outputs.
3. Emit result/config/simulator_bin files.
4. Emit manifest with size/sha claims.
5. Add GEMM delivery metadata.
6. Run archive_runtime_ready_gate.
```

Inputs:

```text
S1 MICC files
S2 CBUF files
runtime/reference assets
GEMM selected representation metadata
```

Outputs:

```text
gemm_no_relu uploadable package
```

Hard dependencies:

```text
binary_emitted needs S1 + S2 first usable files.
uploadable needs S0 gate.
```

Parallel unblock value:

```text
Can test package shell with placeholder failing files first.
Can switch to real files as S1/S2 land.
```

Placeholder package rule:

```json
{
  "package_state": "shell_placeholder",
  "uploadable": false,
  "placeholder_files_present": true,
  "must_not_archive_as_customer_candidate": true
}
```

S0 must fail closed if placeholder files are present:

```text
placeholder files present -> runtime_ready final_status = fail or blocked
```

### S4: GEMM+ReLU Concrete Binding

Owner profile:

```text
operator template / epilogue engineer
```

Can start now:

```text
1. Choose explicit ReLU subtask as default.
2. Bind epilogue:relu to FMAX/HMAX or equivalent.
3. Materialize zero constant with declared dtype.
4. Make ReLU TemplateOps concrete_template.
5. Ensure store consumes ReLU output.
6. Emit ReLU-specific metadata and gate checks.
```

Inputs:

```text
GEMM TemplateOpPlan
ReLU symbolic TemplateOps
DFU3500 opcode evidence
zero constant policy
```

Outputs:

```text
GEMM+ReLU concrete TemplateOpPlan
ReLU writer/gate report
```

Decision deadline:

```text
By 2026-06-23 12:00 Asia/Shanghai:
  if fused finalize/store lifetime is not fully evidenced,
  choose explicit ReLU subtask.
```

Minimum ReLU artifact:

```json
{
  "operator": "gemm_relu",
  "relu_layout": "explicit_subtask",
  "relu_op": "FMAX_OR_HMAX",
  "dtype": "...",
  "zero_constant_policy": "...",
  "expected_relu_template_count": 64,
  "store_input": "relu_output",
  "pre_relu_store_forbidden": true
}
```

Hard dependencies:

```text
GEMM+ReLU package needs S1/S2/S3 path.
ReLU binding itself does not need GEMM package to be uploadable first.
```

Must not wait for:

```text
final GEMM package
log10max work
folded row migration
```

### S5: log10max Capacity Proof And Minimum Collective Strategy

Owner profile:

```text
collective / memory visibility engineer
```

Can start now:

```text
1. Record customer shape, dtype, tile shape, and PE sharding.
2. Prove input visibility for local reduce inputs.
3. Allocate local-max scratch region.
4. Allocate global scalar scratch region.
5. Select minimum collective strategy.
6. Prefer pe00_aggregate_materialize if direct route/reduce/broadcast evidence is incomplete.
7. Define fallback trigger and customer-waiver conditions.
```

Inputs:

```text
LogicalReduceEdge
TileCollectiveBundle
DFU3500 SRAM/SPM layout
runtime shape requirements
route/template evidence
```

Outputs:

```text
log10max_capacity_proof.json
collective_strategy =
  direct_route_reduce_broadcast
  or pe00_aggregate_materialize
  or redundant_spmd_recompute
customer_collective_label =
  physical_route_allreduce
  or pe00_materialized_scalar
  or internal_redundant_recompute
scratch_region_plan.json
```

Strategy meanings:

```text
direct_route_reduce_broadcast:
  direct route/reduce/broadcast path across participating PEs
  customer_collective_label = physical_route_allreduce

pe00_aggregate_materialize:
  staged materialized collective through local-max scratch, PE00 aggregate,
  global scalar scratch, and PE readback
  customer_collective_label = pe00_materialized_scalar

redundant_spmd_recompute:
  every PE recomputes the global max independently
  customer_collective_label = internal_redundant_recompute
  internal-only unless customer waiver exists
```

Fallback triggers:

```text
direct_route_reduce_broadcast blocked if any:
  route template evidence missing
  cross-PE scalar reduction row shape missing
  replicated scalar visibility not proven
  synchronization ordering not represented
  scalar broadcast/readback path missing

pe00_aggregate_materialize blocked if any:
  local maxima scratch region cannot be allocated
  PE00 cannot read all local maxima
  all PEs cannot read global scalar scratch
  subtask ordering cannot enforce max-before-postprocess

redundant_spmd_recompute internal-only unless:
  customer required shape fits full-domain scan per PE
  runtime budget accepted
  customer waiver explicitly attached
```

Hard dependencies:

```text
log10max uploadable package requires selected collective strategy.
S6 needs the strategy shape for final template binding.
```

Must not wait for:

```text
GEMM writers
GEMM+ReLU binding
runtime_ready package gate
```

### S6: log10max Elementwise/Reduce Template Binding

Owner profile:

```text
elementwise / instruction template engineer
```

Can start now:

```text
1. Bind clamp_min.
2. Bind log10 as FLOG2 * log10(2).
3. Bind local reduce_max.
4. Bind maximum(log_spec, global_max - 8.0).
5. Bind add_scalar and mul_scalar.
6. Bind store.
7. Add numerical contract metadata.
```

Inputs:

```text
log10max semantic expression
DFU3500 opcode evidence
S5 selected collective strategy for scalar visibility
constants and dtype policy
```

Outputs:

```text
log10max concrete TemplateOpPlan or tactical TemplateBoundPlan
log10max numerical_contract.json
```

Split delivery:

```text
S6a: local template pack
  clamp_min
  FLOG2 * log10(2)
  local reduce_max
  maximum placeholder using symbolic global scalar input
  add_scalar
  mul_scalar
  store

S6b: scalar visibility binding
  selected strategy from S5
  scalar scratch/load route
  postprocess consumes concrete global_max source
```

S6a artifact:

```json
{
  "operator": "log10max",
  "template_pack": "local_elementwise_reduce_v1",
  "global_scalar_input": "external_symbolic_until_S5",
  "symbolic_unresolved_count_for_uploadable": 1,
  "uploadable": false
}
```

S6b artifact:

```json
{
  "global_scalar_input": "scratch_region.global_max",
  "selected_collective_strategy": "pe00_aggregate_materialize",
  "symbolic_unresolved_count_for_uploadable": 0
}
```

Hard dependencies:

```text
Final scalar visibility templates depend on S5 selected collective strategy.
Local elementwise/reduce templates do not.
```

Must not wait for:

```text
GEMM package completion
ReLU binding
final allreduce route proof for local elementwise work
```

## Dependency Graph

Hard dependencies:

```text
S1.InstanceTableAddress
  -> S1.sub_task_conf_info_t writer
  -> S1.MICC files

S2.inst_t writer
  -> S2.CBUF files

S1.MICC files + S2.CBUF files + S0.gate
  -> S3.GEMM uploadable

S4.ReLU concrete binding + S1/S2/S3 package path
  -> GEMM+ReLU uploadable

S5.capacity/collective strategy
  -> S6.final scalar visibility binding

S6.log10max concrete template plan + S1/S2/S3 package path + S0.gate
  -> log10max uploadable
```

Soft dependencies:

```text
GEMM package success informs but does not block ReLU binding.
GEMM package success informs but does not block log10max capacity proof.
S5 collective strategy informs final S6 binding but does not block local
elementwise template work.
S0 gate can run against placeholder/stale payloads to expose packaging gaps
before real writers land.
```

Forbidden dependencies:

```text
Do not wait for generic allreduce before starting log10max.
Do not wait for GEMM uploadable before starting ReLU concrete binding.
Do not wait for MICC complete before starting inst_t writer.
Do not wait for inst_t complete before implementing package/gate shell.
Do not wait for numerical checker before producing uploadable smoke package.
```

## Critical Path

The critical path for GEMM:

```text
InstanceTableAddress
  -> MICC writers
  -> inst_t writer
  -> package assembly
  -> runtime_ready
```

The critical path for GEMM+ReLU:

```text
ReLU concrete binding
  -> inst_t support for ReLU rows
  -> same package assembly/gate path as GEMM
```

The critical path for log10max:

```text
capacity/memory visibility proof
  -> minimum collective strategy
  -> elementwise/reduce/allreduce templates
  -> same package assembly/gate path
```

The longest poles are expected to be:

```text
1. inst_t minimal writer
2. sub_task_conf_info_t address/embed semantics
3. log10max minimum collective strategy
4. ReLU concrete binding if operand lifetime is unclear
```

Therefore these four must start immediately and in parallel.

## Blocker Escalation Protocol

Every stream reports one status per day:

```text
P0-blocker:
  prevents target operator from reaching runtime_ready by its target date

P0-risk:
  could become a P0-blocker within 24 hours

P1-cleanup:
  does not affect delivery state

Blocked:
  no known implementation path without new evidence

Fallback-triggered:
  primary path abandoned and fallback strategy selected
```

Daily stream status shape:

```json
{
  "stream": "S5",
  "status": "P0-risk",
  "named_blocker": "PE00 scalar scratch readback evidence missing",
  "fallback_trigger": "not_yet",
  "next_decision_deadline": "2026-06-25T12:00:00+08:00"
}
```

Escalation rules:

```text
P0-blocker:
  must name one owner and one next action before end of day

Blocked:
  delivery lead decides within the same checkpoint whether to switch strategy

Fallback-triggered:
  S0 records the old path, selected fallback, trigger condition, and timestamp

P1-cleanup:
  cannot consume S1/S2/S4/S5 long-pole owners until all target operators are
  uploadable
```

## Daily Merge Plan

### 2026-06-22 Monday

Must start:

```text
S0 gate/bundle contract
S1 MICC writers
S2 inst_t writer
S4 ReLU binding
S5 log10max capacity/collective proof
S6 log10max local elementwise templates
```

Merge target:

```text
GEMM package shell can run runtime_ready and fail with meaningful blockers.
ReLU binding decision recorded.
log10max collective strategy shortlist recorded.
```

Required artifacts:

```text
schemas/operator_delivery_status.schema.json
schemas/operator_payload_manifest.schema.json
compiler/tools/check_dfu_delivery_candidate.py smoke result, if implemented
instance_table_address.v1.json
micc_writer_status.gemm_no_relu.json
inst_field_contract.v1.json
inst_writer_report.gemm_no_relu.json
gemm_relu/relu_binding_decision.json
log10max/log10max_capacity_probe_inputs.json
log10max/log10max_strategy_shortlist.json
log10max/local_template_pack.status.json
```

### 2026-06-23 Tuesday

Merge target:

```text
GEMM reaches uploadable or has one named blocker.
GEMM+ReLU has concrete ReLU rows even if package is not uploadable yet.
log10max capacity proof complete.
log10max collective strategy selected.
```

Required artifacts:

```text
gemm_no_relu/operator_payload_manifest.json
gemm_no_relu/validation/runtime_ready.json
gemm_no_relu/operator_delivery_status.json
gemm_relu/relu_writer_report.json
log10max/log10max_capacity_proof.json
log10max/selected_collective_strategy.json
```

Escalation rule:

```text
If inst_t blocks GEMM after midday, stop non-essential work and add people to
S2.  Do not steal S5 owner unless log10max collective proof is already closed.
If fused ReLU lifetime is not fully evidenced by 12:00 Asia/Shanghai, S4
selects explicit ReLU subtask and S2 targets that row shape.
```

### 2026-06-24 Wednesday

Merge target:

```text
GEMM+ReLU reaches uploadable.
log10max local elementwise/reduce templates are concrete.
minimum collective strategy has component-row shape.
```

Required artifacts:

```text
gemm_relu/operator_payload_manifest.json
gemm_relu/validation/runtime_ready.json
gemm_relu/operator_delivery_status.json
log10max/local_template_pack.status.json
log10max/scalar_visibility_binding.status.json
```

Escalation rule:

```text
If GEMM+ReLU is not uploadable because S4 stayed on fused ReLU without full
lifetime evidence, switch to explicit ReLU subtask immediately.  No further
debate.
```

### 2026-06-25 Thursday

Merge target:

```text
log10max reaches uploadable with declared DFU3500 collective strategy.
Customer bundle metadata exists for all three operators.
```

Required artifacts:

```text
log10max/operator_payload_manifest.json
log10max/validation/runtime_ready.json
log10max/operator_delivery_status.json
customer_bundle_manifest.draft.json
```

Escalation rule:

```text
If direct_route_reduce_broadcast is incomplete by 12:00 Asia/Shanghai,
ship pe00_aggregate_materialize as the V1 staged materialized collective.
redundant_spmd_recompute is internal-only unless customer waiver exists.
```

### 2026-06-26 Friday

Merge target:

```text
customer-facing three-operator bundle
runtime_ready reports archived
known limitations explicit
reduced-shape artifacts labeled internal-only
```

## Interface Contracts

### Schema Artifacts

S0 owns schema names, enum values, and readiness transitions.  These schemas are
not a new validation framework; they are the minimum merge contract that keeps
parallel streams from inventing private status fields.

```python
@dataclass(frozen=True)
class FileRecord:
    path: str
    sha256: str
    size: int
```

```python
@dataclass(frozen=True)
class ComponentWriterArtifact:
    schema_version: str
    operator: str
    component_name: Literal[
        "insts",
        "exeblocks",
        "instances",
        "tasks",
        "subtasks",
        "cbuf",
        "micc",
    ]
    path: str
    sha256: str
    size: int
    profile_id: str
    selected_representation: str
    row_count: int
    row_size: int
    writer_status: Literal["pass", "fail", "blocked"]
    unresolved_fields: tuple[str, ...]
    forbidden_fields_touched: tuple[str, ...]
    assumptions: tuple[str, ...]
```

```python
@dataclass(frozen=True)
class OperatorBindingArtifact:
    schema_version: str
    operator: Literal["gemm_no_relu", "gemm_relu", "log10max"]
    source_plan_id: str
    template_plan_id: str
    selected_strategy: str
    concrete_template_count: int
    symbolic_unresolved_count: int
    unresolved_fields: tuple[str, ...]
    numerical_contract_path: str | None
    assumptions: tuple[str, ...]
```

```python
@dataclass(frozen=True)
class OperatorPayloadManifest:
    schema_version: str
    operator: str
    readiness_claim: Literal[
        "binary_emitted",
        "runtime_ready",
        "uploadable",
        "simict_loads",
        "simict_executes",
        "numerically_checked",
    ]
    profile_id: str
    selected_representation: str
    selected_strategy: str | None
    files: Mapping[str, FileRecord]
    runtime_assets: Mapping[str, FileRecord]
    known_limitations: tuple[str, ...]
```

Schema gate:

```text
private metadata fields -> rejected by S0
unresolved_fields non-empty for uploadable -> rejected by S0
selected_strategy missing for log10max -> rejected by S0
```

### Component Writer Contract

```text
Input:
  VendorComponentPlan
  SerializerReadinessPlan
  FieldOffsetPreflightPlan

Output:
  component bytes
  row provenance
  field classification
  writer status

Fail closed if:
  symbolic_unresolved row would be emitted
  unknown semantic field would be encoded
  address unit is unknown
```

Every emitted row must carry:

```text
source_plan_id
component_index
logical_row_id
physical_row_index
component_name
selected_representation
```

Forbidden row identity patterns:

```text
writer-local row numbering as merge key
implicit array order as semantic identity
row index reused across expanded/folded views without representation tag
```

`raw_template_overlay` is allowed only when:

```text
template_row_sha256 is recorded
source template evidence is recorded
patched_fields are listed
unpatched_fields_policy is explicit
forbidden fields are not touched
unknown semantic fields are not changed
```

Minimal overlay report:

```json
{
  "binding_mode": "raw_template_overlay",
  "template_row_sha256": "...",
  "patched_fields": ["opCode", "src_operands", "dst_operands", "imms"],
  "zero_fill_fields": [],
  "template_backed_fields": ["latency", "unit_inst_type"],
  "forbidden_fields_touched": [],
  "unknown_fields_touched": []
}
```

S2 gate:

```text
symbolic_unresolved_count > 0      -> fail
forbidden_fields_touched non-empty -> fail
unknown_fields_touched non-empty   -> fail
template_row_sha256 missing        -> blocked
```

### Operator Binding Contract

```text
Input:
  B-line semantic/source plan
  operator profile
  template evidence

Output:
  concrete TemplateOpPlan or tactical TemplateBoundPlan
  selected strategy
  assumptions
  unresolved fields

Fail closed if:
  unresolved_fields is non-empty for uploadable
  operator semantics are inferred in byte writer
```

### Package Gate Contract

```text
Input:
  payload_dir
  manifest
  runtime/reference assets
  delivery metadata

Output:
  validation/runtime_ready.json
  operator_delivery_status.json

Fail closed if:
  runtime_ready final_status != pass
  manifest claims are stale
  selected representation/strategy is missing
```

## Invariants

1. B-line semantic/source plan remains the authority.
2. Workstreams may run independently only through explicit artifacts.
3. Byte writers do not discover semantics.
4. `runtime_ready` is required before `uploadable`.
5. ReLU cannot be dropped to make GEMM+ReLU run.
6. log10max cannot ship with symbolic-only collective.
7. redundant_spmd_recompute is internal-only unless customer waiver exists.
8. Generic allreduce and generic fusion remain frozen until the three packages exist.

## Alternatives Considered

### A. Keep Phase-Serial Execution

Rejected.

It is easier to coordinate, but it delays ReLU and log10max until GEMM package
work finishes.  That is incompatible with the current delivery week.

### B. Build GEMM First, Then Fork The Code

Rejected.

Forking binary writers by operator will appear fast for one day and then create
three incompatible package paths.  All operators must use the same component
writer and runtime-ready gate path.

### C. Start log10max After GEMM+ReLU

Rejected.

log10max has the largest unknown in minimum collective lowering.  It must start
immediately, even while GEMM binary writers are incomplete.

### D. Move Everyone To inst_t

Rejected unless S2 becomes the named blocker.

`inst_t` is likely the long pole, but overloading it too early starves
log10max allreduce and ReLU binding.  Use the escalation rule instead.

## Validation Plan

Always run:

```text
PYTHONPATH=compiler pytest -q tests/test_dfu_binary_validation.py
PYTHONPATH=compiler:compiler/tools python3 compiler/tools/check_partner_validation_entrypoint.py
for script in compiler/tools/check_stream_compiler_*.py; do
  PYTHONPATH=compiler:compiler/tools python3 "$script"
done
```

Operator-specific gates:

```text
GEMM:
  no symbolic_unresolved emitted
  selected representation present
  runtime_ready pass

GEMM+ReLU:
  ReLU concrete count matches expected tile count
  store consumes ReLU output
  runtime_ready pass

log10max:
  reduce_max visible in semantic/source plan
  selected collective strategy present
  capacity proof present
  scratch regions explicit
  numerical_contract.json present
  global scalar visibility no longer symbolic
  runtime_ready pass
```

Minimum runtime_ready aggregation:

```text
payload_conformance pass
profile_conformance pass
component/package consistency pass
instruction span/opcode checks pass when applicable
no stale manifest claims
component writer status pass
operator binding status pass
selected representation present
selected strategy present when operator requires strategy
no symbolic_unresolved emitted
placeholder package state absent
```

## Risks and Mitigations

### Risk: Parallel streams diverge on schemas

Mitigation:

```text
S0 owns schema names.
Other streams emit only through S0 contracts.
No private bundle metadata fields.
```

### Risk: S1 and S2 disagree on row numbering

Mitigation:

```text
Use BinaryLayoutPlan row ids and VendorComponentPlan component_index as the
join keys.  Do not invent local numbering in writers.
```

### Risk: ReLU waits for package assembly

Mitigation:

```text
ReLU work produces concrete TemplateOps first.  Packaging can catch up later.
```

### Risk: log10max allreduce expands into generic framework work

Mitigation:

```text
Use minimum DFU3500 strategy only.
Prefer PE00 aggregate materialization if direct_route_reduce_broadcast evidence is
not closed by the deadline.
```

### Risk: runtime_ready gate blocks late

Mitigation:

```text
S0 runs gate on package shell from day one.
Every missing manifest/runtime/reference claim becomes visible before final
binary bytes exist.
```

## Expected Effect

After adopting this RFC:

```text
GEMM binary writers, inst_t, ReLU, log10max collective, and package gate all move
at the same time.
```

By 2026-06-23:

```text
GEMM is uploadable or has one explicit blocker.
ReLU and log10max are no longer waiting for GEMM.
```

By 2026-06-25:

```text
log10max has an explicit DFU3500 collective strategy and an uploadable package.
```

## Open Questions

1. How many engineers are available for S1/S2/S5 simultaneously?
2. Which legacy template evidence should S2 use first for `raw_template_overlay`?
3. Does the fastest log10max collective implementation use direct_route_reduce_broadcast or pe00_aggregate_materialize?
4. Which shape is the customer-required log10max shape for uploadable status?
5. Who owns final customer bundle metadata approval?

Recommended answers:

```text
S1/S2/S5 staffing:
  minimum four DRIs are required: S0, S1, S2, S5.
  S5 DRI must not be pulled into S2 unless collective proof is closed.

S2 template evidence:
  start with GEMM no-ReLU matching rows.
  require template_row_sha256, patched_fields, and unpatched_fields_policy.

log10max strategy:
  default to pe00_aggregate_materialize if direct_route_reduce_broadcast is not
  evidence-complete by 2026-06-25 12:00 Asia/Shanghai.

customer shape:
  S5 must publish shape inventory on 2026-06-22.
  no customer-facing status without customer shape or explicit waiver.

bundle approval:
  S0 DRI owns schema and aggregation.
  final approval requires delivery lead + operator owner sign-off.
```

## Recommended Decision

Accept this aggressive parallel execution plan and execute immediately.

Start S0 through S6 immediately.  Treat S2 `inst_t`, S1 subtask address
semantics, S4 ReLU binding, and S5 log10max collective as simultaneous long
poles.  Merge through S0-accepted schema artifacts and runtime-ready packages,
not through informal reports.
