# B-line Parallel Kickoff Status

Date: 2026-06-22
Status: Fifth parallel merge in progress
Source RFC: `2026-06-22_b_line_aggressive_parallel_execution_rfc.md`

## Command Rule

All streams are active in parallel.  Streams merge through S0-accepted artifacts
and `runtime_ready` reports, not informal status.

S3 package assembly is now delegated to the package shell worker after S0
completed its first merge and freed an agent slot.

## Stream Agents

```text
S0 Delivery gate / merge control plane
  agent: Popper
  id: 019eeeef-0427-7973-9eb2-4acbcbc148d9
  write scope:
    compiler/gpdpu_compiler/validation/delivery_contracts.py
    compiler/tools/check_dfu_delivery_candidate.py
    tests/test_dfu_delivery_contracts.py

S1 MICC/control component writers
  agent: Archimedes
  id: 019eeeef-2eb0-73a2-a38e-952abe3afa91
  write scope:
    compiler/gpdpu_compiler/core/stream_compiler/micc_component_writers.py
    compiler/tools/check_stream_compiler_micc_writers.py

S2 CBUF/inst_t writer
  agent: Schrodinger
  id: 019eeeef-60e9-7850-aa18-006bfb697e3e
  write scope:
    compiler/gpdpu_compiler/core/stream_compiler/inst_writers.py
    compiler/tools/check_stream_compiler_inst_writer.py

S4 GEMM+ReLU concrete binding
  agent: Goodall
  id: 019eeeef-892c-7321-9424-f7d05679428a
  write scope:
    compiler/gpdpu_compiler/core/stream_compiler/relu_binding.py
    compiler/tools/check_stream_compiler_relu_binding.py

S5 log10max capacity / collective strategy
  agent: Hegel
  id: 019eeeef-b68b-7cc2-bb53-edd3510f2836
  write scope:
    compiler/gpdpu_compiler/core/stream_compiler/log10max_collective_strategy.py
    compiler/tools/check_stream_compiler_log10max_collective.py

S6 log10max local template pack
  agent: Bacon
  id: 019eeeef-ea73-7313-b32c-c77b222c8d37
  write scope:
    compiler/gpdpu_compiler/core/stream_compiler/log10max_template_pack.py
    compiler/tools/check_stream_compiler_log10max_templates.py
```

## Main Coordinator Holds

```text
S3 GEMM package assembly
  current owner: Tesla
  id: 019eeefc-3784-75f1-9a3b-f260defa8a09
  reason: second parallel round package-shell integration
  required artifact:
    gemm_no_relu/operator_payload_manifest.json
    gemm_no_relu/validation/runtime_ready.json
    gemm_no_relu/operator_delivery_status.json
```

## First Merge Expectations

```text
S0:
  delivery contract schema and check_dfu_delivery_candidate entrypoint

S1:
  InstanceTableAddress contract and MICC writer status

S2:
  inst_t field contract or raw_template_overlay blocker report

S4:
  ReLU explicit-subtask binding decision and fail-closed check

S5:
  log10max strategy enum, capacity proof shape, blocked conditions

S6:
  log10max local template pack and numerical contract shape
```

## First Merge Results

```text
S0 Delivery gate / merge control plane
  status: accepted
  artifact:
    compiler/gpdpu_compiler/validation/delivery_contracts.py
    compiler/tools/check_dfu_delivery_candidate.py
    tests/test_dfu_delivery_contracts.py
  focused gate:
    PYTHONPATH=compiler pytest -q tests/test_dfu_delivery_contracts.py
    result: 4 passed
  notes:
    runtime_ready is local structural/package readiness only.
    It is not SimICT execution or numerical correctness.

S1 MICC/control component writers
  status: accepted with P0 blocker
  artifact:
    compiler/gpdpu_compiler/core/stream_compiler/micc_component_writers.py
    compiler/tools/check_stream_compiler_micc_writers.py
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_micc_writers.py
    result: PASS
  produced:
    task_conf_info_t debug-only rows=4 payload_size_bytes=480
    exeBlock_conf_info_t debug-only rows=384 payload_size_bytes=199680
    InstanceTableAddress addr_space=instance_component_offset unit=bytes
  blocker:
    sub_task_conf_info_t is blocked because candidate instances_amount=1
    conflicts with derived active instance rows:
      non k-stream subtasks -> 0
      k-stream subtasks -> 4

S2 CBUF/inst_t writer
  status: accepted with P0 blocker
  artifact:
    compiler/gpdpu_compiler/core/stream_compiler/inst_writers.py
    compiler/tools/check_stream_compiler_inst_writer.py
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_inst_writer.py
    result: OK
  produced:
    instruction_rows=896
    matched_template_evidence=896
  blocker:
    template_row_sha256_missing=896
    missing_raw_template_bytes=896
    exact TemplateOp -> legacy CSV row/span binding seed is required.

S4 GEMM+ReLU concrete binding
  status: accepted with P0 blocker
  artifact:
    compiler/gpdpu_compiler/core/stream_compiler/relu_binding.py
    compiler/tools/check_stream_compiler_relu_binding.py
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_relu_binding.py
    result: OK
  produced:
    relu_layout=explicit_subtask
    explicit_relu_bindings=64
    store_dependencies=64
  blocker:
    missing dtype selection
    missing zero constant materialization
    missing 64 concrete ReLU template row evidence
    missing store operand lifetime evidence

S5 log10max capacity / collective strategy
  status: accepted with P0 blocker
  artifact:
    compiler/gpdpu_compiler/core/stream_compiler/log10max_collective_strategy.py
    compiler/tools/check_stream_compiler_log10max_collective.py
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_collective.py
    result: OK
  produced:
    recommended_delivery_strategy=pe00_aggregate_materialize
    selected_delivery_strategy=None
    delivery_status=blocked_on_pe00_evidence
    internal_waiver_strategy=redundant_spmd_recompute
  blocker:
    PE00 scratch address and instance base_addr binding missing
    PE00 scratch write/readback evidence missing
    broadcast load receiver binding missing
    PE00 FMAX combine order missing
    runtime launch/subtask order evidence missing

S6 log10max local template pack
  status: accepted with P0 blocker
  artifact:
    compiler/gpdpu_compiler/core/stream_compiler/log10max_template_pack.py
    compiler/tools/check_stream_compiler_log10max_templates.py
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_templates.py
    result: OK
  produced:
    local_template_steps=7
    op_sequence=clamp_min,FLOG2*log10(2),local_reduce_max,maximum,add_scalar,mul_scalar,store
  blocker:
    uploadable=False while global scalar visibility remains external to S5
    local reduce/store still lack runnable template row and memory base-slot proof
```

## Next Parallel Round

```text
N1 Exact template binding seed
  owner: S2 with S1/S4 inputs
  goal:
    define exact TemplateOp -> legacy CSV path/template_index/row span binding
    produce real template_row_sha256 source for GEMM no-ReLU first
  blocks:
    GEMM cbuf inst_t writer
    GEMM+ReLU concrete ReLU rows

N2 Instance amount / subtask semantics closure
  owner: S1 with S3 integration
  goal:
    resolve candidate instances_amount=1 versus derived 0/4 active instance rows
    keep address=0 semantics unambiguous
  blocks:
    sub_task_conf_info_t writer
    MICC uploadable state

N3 Explicit ReLU concrete binding
  owner: S4 with S2 evidence seed
  goal:
    decide fp32 FMAX versus fp16 HMAX
    bind zero constant materialization
    prove store consumes ReLU output
  blocks:
    GEMM+ReLU runtime_ready

N4 PE00 materialized scalar allreduce
  owner: S5 with S6 local template pack
  goal:
    prove scratch address/base_addr/readback/order/receiver binding
    turn recommended_delivery_strategy into selected_delivery_strategy
  blocks:
    log10max runtime_ready

N5 GEMM package shell integration
  owner: S3 / Tesla
  goal:
    assemble manifest/runtime_ready shell from accepted S0 artifacts
    do not mark uploadable while S1/S2 blockers remain
```

## Second Round Dispatch

```text
S1 / N2:
  build subtask-instance semantics report
  make instances_amount mismatch directly consumable by S3

S2 / N1:
  build exact template binding seed artifact
  separate candidate evidence sha from real template_row_sha256

S3 / N5:
  build report-only operator payload assembly shell
  summarize gemm_no_relu, gemm_relu, log10max readiness without fake binaries

S4 / N3:
  refine ReLU dtype, zero constant, row evidence seed, store lifetime blockers

S5 / N4:
  expand PE00 materialized scalar plan and scalar visibility interface

S6 / N4:
  make local template pack consume a future S5 scalar visibility source
```

## Runtime Ready Gate Fix

```text
issue:
  partner entrypoint guard failed after runtime_ready gate integration with
  dfu3500_memory_template instance row/base-slot errors.

root cause:
  memory_template_check treated sub_task_conf_info_t.instances_conf_mem_based_addr
  as a physical CBUF instance row.

corrected semantics:
  MICC instances_conf_mem_based_addr is a compact active-instance byte offset.
  CBUF instance_conf_info_file.bin is a fixed physical task/subtask/instance
  window.

fix:
  validate compact byte offset alignment/range, then read CBUF instance rows
  through physical row:
    task * 8 * 2048 + subtask * 2048 + instance_offset

verification:
  PYTHONPATH=compiler:compiler/tools python3 compiler/tools/check_partner_validation_entrypoint.py
    PASS
  PYTHONPATH=compiler pytest -q tests/test_dfu_binary_validation.py
    48 passed
  PYTHONPATH=compiler pytest -q tests/test_dfu_delivery_contracts.py
    4 passed
```

## Second Merge Results

```text
S1 / N2 Instance amount / subtask semantics
  status: accepted with P0 blocker refined
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_micc_writers.py
    result: PASS
  produced:
    SubtaskInstanceSemanticsReport
    runtime_ready_candidate=False
    blocked_subtasks=12
  blocker:
    8 non-k-stream subtasks require instances_amount=0 but candidate has 1.
    4 k-stream subtasks require explicit folded selection; derived active
    instance count is 4, current expanded candidate has 1.

S2 / N1 Exact template binding seed
  status: accepted with P0 blocker refined
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_inst_writer.py
    result: OK
  produced:
    TemplateRowSpanBinding
    ExactTemplateBindingSeedReport
    exact_binding_seed_status=blocked
    exact_bound_rows=0
  blocker:
    missing legacy_csv_path
    missing template_index
    missing local_order_or_row_span
    missing task_resource_replay_row_authority
    missing subtask_instance_semantics_status
    missing template_row_sha256

S3 / N5 Package shell integration
  status: accepted
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_operator_payload_assembly.py
    result: OK
  produced:
    gemm_no_relu final_state=blocked runtime_ready=False uploadable=False
    gemm_relu final_state=blocked runtime_ready=False uploadable=False
    log10max final_state=blocked runtime_ready=False uploadable=False
  invariant:
    placeholder_files_present => runtime_ready_false/uploadable_false

S4 / N3 Explicit ReLU concrete binding
  status: accepted with two blockers closed
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_relu_binding.py
    result: OK
  closed:
    dtype_selection -> recommended HMAX
    store_operand_lifetime -> store must consume relu_output
  blocker:
    zero_constant_materialization needs exact IMM/FIMM/zero operand row.
    template_row_evidence needs exact S2 seed/raw bytes/hash.

S5 / N4 PE00 materialized scalar allreduce
  status: accepted with P0 blocker refined
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_collective.py
    result: OK
  produced:
    Pe00MaterializedScalarPlan
    scalar visibility interface for S6
    selected_delivery_strategy=None
  available:
    scratch_region_shape
    producer_pe00_store_action
    consumer_broadcast_load_actions
    materialize_before_readback_dependency
  blocker:
    scratch_address_binding
    producer_pe00_physical_store
    consumer_physical_readback
    runtime_subtask_order
    receiver_binding
    pe00_fmax_combine_order

S6 / N4 log10max template pack scalar binding
  status: accepted
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_templates.py
    result: OK
  produced:
    ScalarVisibilitySource contract
    bind_scalar_visibility(pack, scalar_source)
    synthetic complete PE00 interface closes symbolic scalar to 0 without
    claiming row bytes or runtime runnable.
  blocker:
    real S5 PE00 scalar source remains missing.
```

## Current Critical Path

```text
1. GEMM no-ReLU binary:
   S1 must choose/close subtask instance representation.
   S2 must receive exact legacy row/span seed and produce template_row_sha256.
   S3 can only package after S1/S2 artifacts become runtime_ready candidates.

2. GEMM+ReLU:
   S4 has selected HMAX and store lifetime.
   It now depends on S2 exact row evidence plus zero constant materialization.

3. log10max:
   S5/S6 agree on PE00 scalar visibility interface.
   The hard blocker is turning PE00 materialized scalar from symbolic plan into
   concrete scratch address/base_addr/readback/order/receiver/FMAX evidence.
```

## Third Round Dispatch

```text
coordination note:
  detailed blocker/RFC note:
    2026-06-22_b_line_third_round_a_line_baseline_rfc.md
  conclusion:
    A-line success baseline should be used as binary evidence for
    instance/base_addr and exact row/span authority, not as B-line semantic
    authority.

S1 / N6:
  owner: Bernoulli
  goal:
    convert subtask instance semantics from blocked report into explicit
    representation selection.
  target:
    non-k-stream -> zero_instance_control when derived count is 0
    k-stream -> folded_k_stream_explicit when folded overlay count matches 4
  guard:
    no implicit expanded/folded mixing and no fake runtime-ready claim

S2 / N7:
  owner: Sagan
  goal:
    inspect candidate raw row distribution and close any exact seed rows only
    where the evidence is uniquely authoritative.
  current finding:
    no role has candidate_raw_row_count == 1.
    counts are:
      accumulator_prepare -> 82
      compute_core:gemm_update -> 512
      operand_materialize:A -> 64
      operand_materialize:B -> 64
      operand_route_recv:A -> 64
      operand_route_recv:B -> 64
      tile_store -> 64
  implication:
    exact template row seed requires local_order/row_span or TaskResourceReplay
    row authority; it cannot be inferred from candidate evidence alone.

S5 / N8:
  owner: Ampere
  goal:
    define PE00 scratch allocation/source contract at B-line level and map
    remaining PE00 requirements to specific next owner passes.
  guard:
    selected_delivery_strategy remains None until every PE00 requirement closes.
```

## Third Round Partial Results

```text
S1 / N6:
  status: accepted, selection complete
  result:
    8 non-k-stream subtasks selected as zero_instance_control
    4 k-stream subtasks selected as folded_k_stream
    sub_task_conf_info_t remains debug_only with payload_size_bytes=0
  remaining:
    runnable subtask byte packing for selected representations

S5 / N8:
  status: accepted, PE00 source contract refined
  result:
    Pe00ScratchAllocationContract added
    pe00_delivery_source_id=app_storage:global_max:dtensor_0003
    selected_delivery_strategy=None
  remaining:
    scratch_address_materialization
    producer_pe00_physical_store
    consumer_physical_readback
    runtime_subtask_order
    receiver_binding
    pe00_fmax_combine_order

S2 / N7:
  status: accepted after S1/S2 merge
  result:
    candidate distribution proves no single-candidate row exists.
    partial_candidate_rows=896
    single_candidate_rows=0
    s1_representation_selection={'closed': 896}
    missing_seed_fields now only:
      local_order_or_row_span
      task_resource_replay_row_authority
      template_row_sha256
  remaining:
    A-line row/span evidence and TaskResourceReplay row authority.
```

## Third Round Verification

```text
focused:
  PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_micc_writers.py
    PASS, selection_complete=True
  PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_inst_writer.py
    OK, s1_representation_selection={'closed': 896}
  PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_collective.py
    OK, pe00_delivery_source_id=app_storage:global_max:dtensor_0003

all stream gates:
  for script in compiler/tools/check_stream_compiler_*.py; do
    PYTHONPATH=compiler:compiler/tools python "$script"
  done
  result: all pass

validation:
  PYTHONPATH=compiler pytest -q tests/test_dfu_binary_validation.py
    48 passed
  PYTHONPATH=compiler pytest -q tests/test_dfu_delivery_contracts.py
    4 passed
  PYTHONPATH=compiler:compiler/tools python3 compiler/tools/check_partner_validation_entrypoint.py
    PASS
```

## Current Remaining Work

```text
GEMM no-ReLU:
  1. produce A-line-backed local_order_or_row_span for 896 rows
  2. implement TaskResourceReplay row authority for COPY/operand/block/end fields
  3. compute template_row_sha256 from exact raw row bytes
  4. turn selected subtask rows into runnable sub_task_conf_info_t bytes

GEMM+ReLU:
  1. reuse S2 row/span mechanism
  2. materialize ZERO_relu operand
  3. bind 64 IMM/HMAX rows

log10max:
  1. materialize scratch address for app_storage:global_max:dtensor_0003
  2. lower PE00 physical store/readback
  3. close runtime subtask order, receiver binding, and PE00 FMAX chain
```

## Verification Snapshot

```text
focused stream gates:
  check_stream_compiler_micc_writers.py
  check_stream_compiler_inst_writer.py
  check_stream_compiler_operator_payload_assembly.py
  check_stream_compiler_relu_binding.py
  check_stream_compiler_log10max_collective.py
  check_stream_compiler_log10max_templates.py
  result: all pass

all stream compiler gates:
  for script in compiler/tools/check_stream_compiler_*.py; do
    PYTHONPATH=compiler:compiler/tools python "$script"
  done
  result: all pass

runtime-ready / validation:
  PYTHONPATH=compiler:compiler/tools python3 compiler/tools/check_partner_validation_entrypoint.py
    PASS
  PYTHONPATH=compiler pytest -q tests/test_dfu_binary_validation.py
    48 passed
  PYTHONPATH=compiler pytest -q tests/test_dfu_delivery_contracts.py
    4 passed
```

## Fourth And Fifth Round Results

```text
A-line GEMM evidence / S2 input:
  status: accepted
  artifacts:
    compiler/gpdpu_compiler/core/stream_compiler/aline_gemm_evidence.py
    compiler/tools/check_stream_compiler_aline_gemm_evidence.py
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_aline_gemm_evidence.py
    result: PASS
  produced:
    selected case:
      simict3500final/.../gemm_template_fusion_bash_semantics_probe
    full_size_result_available=True
    result/cbuf_file.bin size=23531520
      sha256=2e83d38ba24ba3a55c7920e971b1493706a330bb66bf3ca7bb74a69ace3c29cb
    result/micc_file.bin size=8522976
      sha256=17e78755ceb408f19b222640dcdcdfdd27f53338b81cbe07e57516b6dc695978
    csv_template_count=256
    task_count=4
    row_catalog_available=True
    row_count=53376
  implication:
    A-line success baseline is now row-addressable evidence.
    It still does not prove one B-line row maps to one raw inst_t row.
    Next step is span/compressed-row authority.

TaskResourceReplay authority / S2 input:
  status: accepted, partial authority
  artifacts:
    compiler/gpdpu_compiler/core/dfu3500/task_resource_replay.py
    compiler/tools/check_stream_compiler_task_resource_replay.py
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_task_resource_replay.py
    result: OK
  produced:
    covered_role_counts={"operand_route_recv:A|ROUTE_RECV_VISIBILITY": 192}
    authority_status=partial
  S2 consumption:
    compiler/gpdpu_compiler/core/stream_compiler/inst_writers.py
    compiler/tools/check_stream_compiler_inst_writer.py
    task_resource_replay_authority closed=192 open=704
    task_resource_replay_row_authority missing count reduced from 896 to 704
  remaining:
    exact sender raw row/local_order
    template_row_sha256
    end_inst boundary policy

MICC selected subtask bytes:
  status: accepted, debug-only bytes emitted
  artifacts:
    compiler/gpdpu_compiler/core/stream_compiler/micc_component_writers.py
    compiler/tools/check_stream_compiler_micc_writers.py
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_micc_writers.py
    result: PASS
  produced:
    sub_task_conf_info_t selected_rows=12
    payload_size_bytes=3195936
    selection_complete=True
    selected_representations=8 zero_instance_control; 4 folded_k_stream
  remaining:
    artifact is runtime-shaped but still debug-only.
    It must not be labeled runtime_ready/uploadable yet.

Current fifth round dispatch:
  S2 / N9:
    owner: Fermat
    goal:
      consume A-line row catalog and produce report-only span candidate.
      This should prove every B-line row has selected A-line catalog candidates
      while keeping exact_bound_rows=0 until row-span authority is real.
  S3 / N10:
    owner: Darwin
    goal:
      consume MICC selected subtask bytes in package shell readiness labels.
      Keep runtime_ready=False/uploadable=False.
```

## Fifth Round Verification

```text
S2 / N9 A-line span candidate:
  status: accepted
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_inst_writer.py
    result: OK
  produced:
    aline_row_catalog_rows=53376
    aline_span_catalog_available_rows=896
    aline_span_row_span_required=896
    exact_bound_rows=0
    template_row_sha256_missing=896
  implication:
    every B-line GEMM no-ReLU instruction row has selected A-line catalog
    candidates.  None may be treated as exact yet because B-line rows are
    compressed/span-level rows, not single legacy inst_t rows.

S3 / N10 package shell MICC status:
  status: accepted
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_operator_payload_assembly.py
    result: OK
  produced:
    gemm_no_relu final_state=blocked runtime_ready=False uploadable=False
    labels include:
      micc_selected_subtask_bytes_present
      subtask_bytes_debug_only
  implication:
    S3 now sees the MICC selected subtask-byte progress but still blocks
    upload/runtime_ready correctly.

all stream gates:
  for script in compiler/tools/check_stream_compiler_*.py; do
    PYTHONPATH=compiler:compiler/tools python "$script"
  done
  result: all pass

runtime-ready / validation:
  PYTHONPATH=compiler pytest -q tests/test_dfu_binary_validation.py
    48 passed
  PYTHONPATH=compiler pytest -q tests/test_dfu_delivery_contracts.py
    4 passed
  PYTHONPATH=compiler:compiler/tools python compiler/tools/check_partner_validation_entrypoint.py
    PASS
```

## Sixth Round Dispatch

```text
S2 / N11:
  owner: Kierkegaard
  goal:
    turn A-line span candidates into a machine-readable compressed-row/span
    authority contract.
  guard:
    no row may become exact/ready until a role-specific span policy is
    explicitly closed.

S5 / N12:
  owner: Sartre
  goal:
    refine PE00 materialized scalar with a concrete scratch address candidate
    record for app_storage:global_max:dtensor_0003.
  guard:
    selected_delivery_strategy remains None while address/source/readback/order
    requirements are not all closed.
```

## Seventh Round Verification

```text
S2 compressed span policies:
  status: accepted, report-only
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_inst_writer.py
    result: OK
  default path:
    compressed_span_policy_needed=896
    compressed_span_closed_policy_rows=0
    compressed_span_route_policy_blocked=384
  opt-in policy path:
    opt_in_compressed_span_policy_needed=0
    opt_in_compressed_span_closed_policy_rows=896
    opt_in_compressed_span_route_policy_closed=384
    exact_span_hash_candidates=896
    exact_span_hash_raw_overlay_consumable=0
  implication:
    all 896 GEMM no-ReLU B-line rows now have report-only span policy
    candidates and stable span-hash candidates.  They are still not raw
    inst_t template_row_sha256 values, so the raw overlay writer remains
    blocked by design.

S5 PE00 scratch address source:
  status: accepted, report-only
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_collective.py
    result: OK
  produced:
    program_tile emits app_storage_address_record candidates
    pe00_scratch_address_candidate=candidate_address_record_present_but_unverified
    selected_delivery_strategy=None
    runtime_ready=False
  remaining:
    concrete allocator / offset
    instance_base_addr_source
    producer_pe00_physical_store
    consumer_physical_readback
    runtime_subtask_order
    receiver_binding
    pe00_fmax_combine_order

all stream gates:
  for script in compiler/tools/check_stream_compiler_*.py; do
    PYTHONPATH=compiler:compiler/tools python "$script"
  done
  result: all pass
```

## Eighth Round Verification

```text
S2 span-hash to raw-hash boundary:
  status: accepted, fail-closed
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_inst_writer.py
    result: OK
  produced:
    exact_span_hash_candidates=896
    exact_span_hash_raw_overlay_consumable=0
    raw_template_row_hash_ready=0
    raw_template_row_hash_blocked=896
  implication:
    GEMM no-ReLU now has full report-only span hash coverage, but no row is
    allowed to feed the raw_template_overlay writer yet.  The next engineering
    step is span materialization: turn closed compressed span policies into
    actual raw inst_t row bytes / template_row_sha256 values.

verification:
  all stream compiler gates:
    result: all pass
  PYTHONPATH=compiler pytest -q tests/test_dfu_binary_validation.py
    48 passed
  PYTHONPATH=compiler:compiler/tools python compiler/tools/check_partner_validation_entrypoint.py
    PASS
```

## Ninth Round Verification

```text
S2 A-line span digest hardening:
  status: accepted, report-only
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_inst_writer.py
    result: OK
  refinement:
    A-line span candidates now carry candidate_catalog_span_sha256 derived from
    the selected A-line catalog row hash sequence:
      csv_path
      local_order
      row_sha256
    exact span hash candidates consume that source span digest rather than only
    count/policy metadata.
  produced:
    exact_span_hash_candidates=896
    exact_span_hash_raw_overlay_consumable=0
    raw_template_row_hash_ready=0
    raw_template_row_hash_blocked=896
  implication:
    GEMM no-ReLU has auditable span digests for every B-line row.  The remaining
    S2 job is now specifically span materialization into raw inst_t bytes /
    template_row_sha256, not evidence discovery.

verification:
  all stream compiler gates:
    result: all pass
  PYTHONPATH=compiler pytest -q tests/test_dfu_delivery_contracts.py
    4 passed
```

## Tenth Round Verification

```text
S2 span materialization candidate boundary:
  status: accepted, report-only
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_inst_writer.py
    result: OK
  produced:
    span_materialization_candidates=896
    span_materialization_total_bytes=93739008
    span_materialization_raw_overlay_consumable=0
    raw_template_row_hash_ready=0
    raw_template_row_hash_blocked=896
  implication:
    GEMM no-ReLU now has a machine-readable materialization candidate for every
    B-line instruction row.  Each candidate names the multi-row A-line span
    shape and byte volume that a byte materializer must turn into real inst_t
    bytes.  The report deliberately does not invent template_row_sha256 and
    does not unblock raw_template_overlay.

remaining S2 blocker:
  build the real span byte materializer:
    consume span_row_hash_sequence_sha256 / candidate catalog rows
    assemble raw inst_t bytes for the selected span policy
    derive real per-output-row template_row_sha256 or a new span-aware writer
    contract
    keep raw_template_overlay blocked unless a single raw inst_t row hash exists

verification:
  all stream compiler gates:
    result: all pass
  PYTHONPATH=compiler pytest -q tests/test_dfu_binary_validation.py
    48 passed
  PYTHONPATH=compiler pytest -q tests/test_dfu_delivery_contracts.py
    4 passed
```

## Eleventh Round Verification

```text
S5 PE00 scratch address allocation candidate:
  status: accepted, report-only
  focused gate:
    PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_collective.py
    result: OK
  produced:
    pe00_scratch_address_candidate=compiler_allocated_address_candidate_available
    scratch_address_materialization closed
    candidate address_space=sram
    candidate offset_bytes=0xA0000
    candidate end_offset_bytes=0xA0004
    candidate instance_base_addr_source=dfu3500_sram_byte_offset_to_legacy_base_word32
  implication:
    log10max PE00 materialized scalar no longer blocks on source scratch
    allocation.  The allocation remains report-only and does not claim physical
    store/readback or runtime readiness.

remaining S5 PE00 blockers:
  producer_pe00_physical_store
  consumer_physical_readback
  runtime_subtask_order
  receiver_binding
  pe00_fmax_combine_order

verification:
  all stream compiler gates:
    result: all pass
  PYTHONPATH=compiler pytest -q tests/test_chip_program_frontend.py -k 'template_bound_shadow_ir or app_storage or materialize or store'
    3 passed, 25 deselected
  PYTHONPATH=compiler:compiler/tools python compiler/tools/check_partner_validation_entrypoint.py
    PASS
```

## Twelfth Round Progress-First Binary Seed

```text
policy shift:
  progress-first binary delivery
  reliability expansion deferred

S2/S3 tactical GEMM payloads:
  status: emitted
  tool:
    python compiler/tools/emit_bline_progress_payload.py --operator gemm_no_relu --force
    python compiler/tools/emit_bline_progress_payload.py --operator gemm_relu --force
  output:
    report/b_line_progress_payloads/gemm_no_relu
    report/b_line_progress_payloads/gemm_relu
  payload_status:
    progress_first_tactical_binary_seed
  source:
    A-line gemm_template_fusion_bash_semantics_probe
  emitted files:
    result/cbuf_file.bin
    result/micc_file.bin
    config/cbuf_file.bin
    config/micc_file.bin
    simulator_bin/insts_file.bin
    simulator_bin/exeblock_conf_info_file.bin
    simulator_bin/instance_conf_info_file.bin
    simulator_bin/tasks_conf_info_file.bin
    simulator_bin/subtasks_conf_info_file.bin
    runtime/input_data.bin
    runtime/input_data_m.bin
    reference/output_data_m.bin
    runtime/riscv_src/riscv/testarm.c
    runtime/riscv_src/riscv/dpuctrl.c
    runtime/riscv_src/csv_generate/conf.h
    source/operator_conf.h
    MANIFEST.txt
    PROGRESS_METADATA.json
  key hashes:
    result_cbuf_sha256=2e83d38ba24ba3a55c7920e971b1493706a330bb66bf3ca7bb74a69ace3c29cb
    result_micc_sha256=17e78755ceb408f19b222640dcdcdfdd27f53338b81cbe07e57516b6dc695978
  sizes:
    result/cbuf_file.bin=23531520
    result/micc_file.bin=8522976
    simulator_bin/insts_file.bin=21168128
  limitation:
    these are tactical A-line binary seeds for upload/SimICT path bring-up.
    gemm_relu is the more honest label for the fused source case.
    gemm_no_relu remains a transport/progress seed until a native no-ReLU
    byte path or better no-ReLU baseline is available.

next progress-first step:
  create a log10max progress seed by pushing PE00 physical store/readback or by
  finding a usable legacy softmax/log10max compatible binary baseline.
```

## Thirteenth Round Log10max Progress Seed

```text
S5/S6 tactical log10max payload:
  status: emitted
  tool:
    python compiler/tools/emit_bline_progress_payload.py --operator log10max --force
  output:
    report/b_line_progress_payloads/log10max
  payload_status:
    progress_first_structural_binary_seed
  source:
    compiler/gpdpu_compiler/validation/dfu3500_partner_validation/payloads/log10max_single_task
  emitted files:
    result/cbuf_file.bin
    result/micc_file.bin
    config/cbuf_file.bin
    config/micc_file.bin
    simulator_bin/insts_file.bin
    simulator_bin/exeblock_conf_info_file.bin
    simulator_bin/instance_conf_info_file.bin
    simulator_bin/tasks_conf_info_file.bin
    simulator_bin/subtasks_conf_info_file.bin
    runtime/input_data.bin
    runtime/riscv_src/riscv_control.json
    runtime/riscv_src/riscv/testarm.c
    runtime/riscv_src/csv_generate/conf.h
    reference/mel_spec.fp32.bin
    reference/Y.fp32.bin
    reference/reference.json
    chip_program.json
    SOURCE_MANIFEST.txt
    MANIFEST.txt
    PROGRESS_METADATA.json
  key hashes:
    result_cbuf_sha256=28c44e44bf986527e40044b1e00f56b13fba4ad799bfd31d6e22d31c09ce4eb2
    result_micc_sha256=f455dc68b061bda23b1f6c3a2703568019838eecc8e566b60c5e58aec20ee492
  sizes:
    result/cbuf_file.bin=23531520
    result/micc_file.bin=8522976
    simulator_bin/insts_file.bin=21168128
  limitation:
    this is a structural binary seed.  Source manifest remains
    runtime_runnable=0 with unsupported broadcast_load/local_compute/reduce_store
    rows.  It is useful for package/upload/control-path bring-up while PE00
    physical store/readback and functional instruction rows are completed.

three required operator progress payloads now exist:
  report/b_line_progress_payloads/gemm_no_relu
  report/b_line_progress_payloads/gemm_relu
  report/b_line_progress_payloads/log10max

verification:
  python -m py_compile compiler/tools/emit_bline_progress_payload.py
    pass
  regenerate gemm_no_relu/gemm_relu/log10max progress payloads
    pass
```
