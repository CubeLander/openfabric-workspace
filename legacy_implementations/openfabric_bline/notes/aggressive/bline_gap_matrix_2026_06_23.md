# B-line Gap Matrix

Date: 2026-06-23

Current baseline:

```text
3329561 Advance B-line runtime proof blockers
```

Previous implementation checkpoint:

```text
e63ff0b Materialize B-line legacy inst_t rows
```

## Current Gate State

```text
final_state=blocked
runtime_ready=False
uploadable=False
operator_states={'gemm_no_relu': 'ready', 'gemm_relu': 'blocked', 'log10max': 'blocked'}
operator_missing_counts={'gemm_no_relu': 0, 'gemm_relu': 5, 'log10max': 43}
payload_files_claimed=True
```

## Gap Matrix

| Operator | Closed | Remaining gap | Failure mode today | Next owner |
|---|---|---|---|---|
| GEMM no-ReLU | Fiber, template mapping, exact selector, raw `inst_t` bytes/hash, zero-instance control, CBUF exeBlock decode, endpoint source roundtrip, MICC order/wait/leaf policy | final exeBlock source-field provenance, runtime trace, runtime assets, delivery gate | CBUF/MICC are structurally decoded but still debug/runtime-trace blocked | Agent M/N |
| GEMM+ReLU | explicit `gemm_tile -> relu_tile -> store_tile`; ReLU semantic proof; candidate `IMM+HMAX` bytes/hash; B-line subtask4/op-chain activation and local decode | active ReLU runtime template family selector trace | B-line activation closed, but active runtime selector trace missing | Agent O |
| log10max | source -> Fiber chain, local op mapping, PE00 strategy, PE00 FMAX/STD/ILDMT synthetic raw rows, synthetic decode roundtrip, receiver synthetic link matrix | active A-line/vendor selector and active operand/readback roundtrip | synthetic path self-consistent, but active runtime row family still missing | Agent P |

## Work Blocks

| Block | Target | Primary write scope | Completion signal |
|---|---|---|---|
| A | GEMM component assembly/runtime_ready | `operator_payload_assembly.py`, runtime/package gate tools, payload manifest code | `gemm_no_relu` reaches local `runtime_ready` or has a narrower fail-closed package blocker |
| B | ReLU exact row materializer | `template_evidence.py`, `relu_binding.py`, `relu_fiber_chain.py`, ReLU focused checks | ReLU blocker shrinks from HMAX selector/evidence to raw row proof, or raw HMAX bytes/hash become available |
| C | log10max PE00 row/runtime proof | `log10max_template_pack.py`, `program_runtime.py`, `micc_component_writers.py`, `binding.py`, log10max focused checks | PE00 FMAX/store/readback selected rows and runtime/receiver proof blockers are narrower or closed |

## Active Agents

| Agent | Agent id | Block | Status |
|---|---|---|---|
| Ramanujan | `019ef26d-6b18-7750-9051-50ae340080d2` | A: GEMM component assembly/runtime_ready | Completed: raw-row payload candidate and manifest/hash records; runtime_ready still false |
| Anscombe | `019ef26d-6d12-7eb1-a60c-283dab11f965` | B: ReLU HMAX selector/evidence | Completed: ReLU row-byte proof plan added; HMAX selector still blocked |
| Feynman | `019ef26d-6f05-7290-8a01-567bd00e2526` | C: log10max PE00 row/runtime proof | Completed: PE00 materialization requests added; row bytes/runtime proof still blocked |
| Banach | `019ef297-f297-7470-a745-c5dd9c3fe36b` | A2: GEMM final CBUF/MICC assembly | Superseded by A3/E4/F4 narrowed blockers |
| Dalton | `019ef297-f4d9-7a71-8c40-5af1df89c92e` | B2: ReLU HMAX selector/evidence | Superseded by C3/G4 narrowed blocker |
| Ptolemy | `019ef297-f69f-7411-8fce-1566456b7c63` | C2: log10max PE00 row materializer | Superseded by D3/H4 narrowed blocker |
| Linnaeus | `019ef2a9-8524-7b92-83ce-0f5f59f83919` | A3: GEMM final CBUF instance/final assembly | Completed: final insts section candidate exists; exeblock/instance CBUF blockers narrowed |
| Aristotle | `019ef2a9-8770-72d1-b18f-fba570f52ac5` | B3: GEMM final MICC assembly | Completed: MICC struct bytes available; decoded proof/runtime order still blocked |
| Pascal | `019ef2a9-89cb-7f70-91aa-f4490a3273ba` | C3: ReLU active HMAX selector | Completed: explicit `IMM+HMAX` materializer candidate exists; active selector remains fail-closed |
| Ampere | `019ef2a9-8c5e-74c3-9297-a62fea331c8f` | D3: log10max PE00 raw rows/runtime proof | Completed: PE00 row-level materializer contract exists; raw row bytes/runtime proof still blocked |
| Herschel | `019ef2c9-eed4-7210-846b-0f0ef39fa825` | E4: GEMM CBUF instance/exeblock收口 | Completed: zero-instance control closed instance blocker; exeblock blocker narrowed to decode/final encoder |
| McClintock | `019ef2ca-1af1-7711-b2ef-7de1355bcfe2` | F4: GEMM MICC decode/runtime order proof | Completed: MICC struct decode roundtrips closed; runtime trace/order policy still blocked |
| Sartre | `019ef2ca-5f11-7b33-8c01-f5e23d21e7f5` | G4: ReLU active HMAX selector/materializer | Completed: ReLU candidate raw bytes/hash closed; active runtime selector still blocked |
| Russell | `019ef2ca-96de-7930-80a7-7371374d5adb` | H4: log10max PE00 raw row/scalar visibility | Completed: PE00 FMAX/STD/ILDMT raw-row candidate requests and receiver proof matrix added |
| Heisenberg | `019ef2dc-b1c3-77d3-bf5e-d27871bdc3ee` | I5: GEMM CBUF exeBlock final encoder/decode | Completed: exeBlock decode and CBUF section offset proofs closed; final encoder/endpoint source still blocked |
| Descartes | `019ef2dc-e051-71a2-bc38-6df23a4b2cf7` | J5: GEMM MICC runtime trace/order policy | Completed: MICC decoded order policy closed; runtime trace/wait/leaf still blocked |
| Lagrange | `019ef2dd-16ae-7803-a189-1b7168fba1ec` | K5: ReLU active template-family selector proof | Completed: vendor subtask4 ReLU generator evidence found; active generated CSV/task activation still blocked |
| Carver | `019ef2dd-4a4d-7e83-9d63-5f4a790ebbdd` | L5: log10max PE00 exact row selector/raw-byte materializer | Completed: PE00 synthetic raw inst_t candidates added; exact active selector/decode roundtrip still blocked |
| Planck | `019ef2e8-2389-74f1-94bd-dd1eddf943bc` | M6: GEMM CBUF final encoder/endpoint source | Completed: endpoint source roundtrip closed; final encoder narrowed to source-field provenance |
| Carson | `019ef2e8-52c9-7133-a53a-a9ee28a4e3e3` | N6: GEMM MICC runtime trace/wait/leaf policy | Completed: wait/leaf policy closed; runtime trace remains |
| Fermat | `019ef2e8-8cc3-7f93-b466-867c519d92fa` | O6: ReLU explicit subtask4 activation/template CSV | Completed: B-line subtask4 activation/local decode closed; active runtime selector trace remains |
| Copernicus | `019ef2e8-bd21-7863-bf84-b5b59b3c461d` | P6: log10max PE00 active selector/decode roundtrip | Completed: synthetic operand/decode/link roundtrip closed; active A-line/vendor selector remains |

## Architecture Guardrails

```text
Do not restore sequential-K Fiber as main path.
Do not place ReLU inside GEMM fiber.
Do not model GEMM+ReLU as epilogue/fused post-op.
Do not call PE00 materialized scalar direct physical allreduce.
Do not use bundle as Fiber/Template semantics.
Do not claim runtime_ready/uploadable until the local gate passes.
```

## Agent A Result

GEMM no-ReLU now has a local component payload candidate below final
CBUF/MICC assembly:

```text
raw_inst_t_rows.bin:
  size = 11206656
  rows = 36864
  source = exact_selector_pack_legacy_inst

operator_payload_manifest.json:
  hashable manifest record exists in the report

runtime_ready=False
uploadable=False
remaining_blockers:
  final_cbuf_file_not_assembled
  final_micc_file_not_assembled
  runtime_assets_not_emitted
  delivery_candidate_gate_not_run
```

## Agent B Result

ReLU is still fail-closed, but the blocker is now machine-checkable:

```text
row_byte_proof_plan_status_counts={
  'blocked_missing_active_hmax_selector_and_operand_binding': 64
}

exact_row_selector_status_counts={
  'doc_hmax_shape_available_active_selector_missing': 64
}

remaining_blockers:
  active_relu_hmax_selector
  active_zero_imm_selector
  relu_input_operand_index
  relu_zero_operand_index
  relu_output_operand_index
  relu_local_order
  raw_inst_t_row_bytes
  raw_template_row_sha256
```

The HMAX opcode metadata and one standalone doc/OCR row shape are source-backed:

```text
HMAX,HMAX15,A1,A2,B4,,,0
```

This is now parseable by the legacy `inst_t` packer, but it is still only a
doc-backed selector shape, not an active SimICT GEMM+ReLU template row. The fp32
`IMM+FMAX` probe remains insufficient for the current fp16/HMAX GEMM+ReLU path.

## Agent C Result

PE00 proof plans now expose materialization requests that can feed a later row
materializer:

```text
pe00_fmax_combine expected rows = 15
pe00_scalar_store expected rows = 1
consumer_readback expected rows = 16

runtime_ready=False
row_bytes_claim=False
physical_route_allreduce=False
```

Remaining blockers:

```text
PE00 FMAX combine raw rows/hash
PE00 scalar store raw rows/hash
consumer readback raw rows/hash
decoded MICC order proof
runtime trace artifact
receiver operand roundtrip
```

## Agent A3 Result

GEMM no-ReLU final CBUF status has been narrowed below the previous generic
package blocker:

```text
insts:
  status = candidate_available
  final_section_candidate = available

exeblock_conf_info:
  status = section_candidate_available
  blocker = blocked_debug_only_candidate
  remaining:
    exeBlock_conf_info_t_final_field_encoder
    endpoint_slots_binary_encoding
    inst_mem_based_addr_unit_and_offset_proof
    final_cbuf_section_offset_layout

instance_conf_info:
  status = blocked_missing_instance_table_semantics
  remaining:
    resolve_subtask_instances_amount_zero_or_emit_instance_rows
    resolve_instances_conf_mem_based_addr
    connect_instance_conf_info_t_rows_to_cbuf_section
```

The key semantic mismatch is now explicit: the current component plan has no
instance rows, while selected subtasks still carry `instances_amount=1` and an
unresolved `instances_conf_mem_based_addr`.

## Agent B3 Result

GEMM MICC writers now produce struct-shaped bytes, but the local gate still
correctly refuses to promote them to final runtime bytes:

```text
task_conf_info_t:
  struct_bytes_available
  blocker = decoded_task_conf_info_roundtrip_missing

sub_task_conf_info_t:
  struct_bytes_available
  blocker = decoded_sub_task_conf_info_roundtrip_missing

exeBlock_conf_info_t:
  struct_bytes_available
  blocker = decoded_exeBlock_conf_info_roundtrip_missing

runtime_order:
  blocker = runtime_order_decoded_roundtrip_missing
  blocker = runtime_start_wait_trace_missing
```

## Agent C3 Result

ReLU remains a separate FiberOp after GEMM and before store. The new candidate
does not reintroduce fused/epilogue semantics.

```text
candidate = IMM + HMAX
row_count = 2
raw_inst_t_byte_count = 608
operands:
  input = 0
  zero = 128
  output = 256
raw_template_row_sha256 = c51450ee504359a6e76c6cd70fa357f4d12497fdc1ebe92104a754713af13087
active_selector_claim = False

remaining:
  active_relu_hmax_selector
  active_relu_template_family_proof
  active_relu_raw_inst_t_row_bytes_claim
  active_relu_raw_template_row_sha256_claim
```

## Agent D3 Result

log10max PE00 materialized scalar planning now exposes a row-level contract
that a later materializer can consume:

```text
stable row_id
subtask_slot
local_order_proposal
operand_role_map
expected_decode_skeleton
materializer_input_contract
MICC stage_row_id_contract
receiver readback row id -> max_with_floor_tile roundtrip lock
```

Remaining fail-closed blockers:

```text
pe00_fmax_combine_order_row_bytes_missing
producer_pe00_physical_store_row_bytes_missing
consumer_physical_readback_row_bytes_missing
runtime_subtask_order_proof_missing
receiver_global_scalar_binding_proof_missing
```

## Agent E4 Result

GEMM no-ReLU CBUF assembly now treats instance rows consistently with the
selected subtask writer artifact:

```text
selected_subtasks = 8
instance_control = zero_instance_control
instances_amount = 0
instances_conf_mem_based_addr = 0

instance_conf_info:
  status = candidate_available
  final_empty_section_candidate = available
```

The old mismatch, where `component_plan.instance_rows` was empty but subtasks
looked like they referenced instance rows, is closed. The remaining CBUF blocker
is now focused on exeBlock finalization:

```text
exeBlock_conf_info:
  payload_rows = 128
  row_size_bytes = 520
  inst_mem_based_addr_unit = bytes
  distinct_inst_offsets = 0, 304, 912, 1520, 2128
  remaining:
    exeBlock_conf_info_t_final_field_encoder
    endpoint_slots_debug_encoding_decode_roundtrip
    inst_mem_based_addr_decode_roundtrip_proof
    final_cbuf_section_offset_decode_roundtrip
```

## Agent F4 Result

MICC struct decode roundtrips are no longer the primary blocker:

```text
decoded_task_conf_info_roundtrip = closed
decoded_sub_task_conf_info_roundtrip = closed
decoded_exeBlock_conf_info_roundtrip = closed
runtime_order_decoded_roundtrip = decoded_structs_available
final_status = decoded_roundtrip_available_runtime_trace_missing
```

Remaining fail-closed blockers:

```text
runtime_start_wait_trace_missing
task_active_subtask_order_proof_missing
task_start_end_runtime_policy_unproven
subtask_successor_order_proof_missing
embedded_exeblock_roundtrip_missing
instance_table_address_roundtrip_missing
exeBlock_instruction_range_roundtrip_missing
exeBlock_wait_or_dependency_flags_unproven
exeBlock_is_leaf_policy_unproven
```

## Agent G4 Result

ReLU is still an independent `relu_tile` FiberOp. The candidate materializer now
has stable raw bytes/hash, but it is still not promoted to the active runtime
template family:

```text
candidate = IMM + HMAX
candidate_row_bytes_claim = True
candidate_raw_template_row_sha256_claim = True
row_count = 2
raw_inst_t_byte_count = 608
active_selector_claim = False
row_bytes_claim = False
raw_template_row_sha256_claim = False

remaining:
  active_relu_template_family_selector_proof
```

## Agent H4 Result

log10max PE00 materialized scalar path now emits explicit raw-row candidate
requests without claiming final bytes:

```text
pe00_fmax_combine:
  rows = 15
  row_ids = global_max_tile.pe00_fmax_combine.00..14
  opcode = FMAX / 0x027

pe00_scalar_store:
  rows = 1
  row_id = global_max_tile.pe00_scalar_store.00
  opcode = STD / 0x080

consumer_readback:
  rows = 16
  row_ids = global_max_tile.consumer_readback.00..15
  opcode = ILDMT / 0x107
```

Scalar visibility now has a 16-row proof matrix linking each readback row to
the receiver-owned operand consumed by `max_with_floor_tile`. Remaining:

```text
exact_legacy_row_selector_missing
operand_index_address_encoding_missing
raw_inst_t_row_bytes_missing
raw_template_row_hash_missing
decoded_readback_to_max_with_floor_operand_roundtrip_missing
```

## Agent I5 Result

GEMM no-ReLU exeBlock CBUF can now be locally decoded from the candidate bytes:

```text
exeBlock_conf_info:
  rows = 128
  bytes = 66560
  decode_roundtrip = available
  inst_mem_based_addr_values = 0, 304, 912, 1520, 2128

cbuf_section_offsets:
  insts -> exeblock_conf_info -> empty instance_conf_info
  decode_roundtrip = available
```

Closed:

```text
inst_mem_based_addr_decode_roundtrip_proof
final_cbuf_section_offset_decode_roundtrip
```

Remaining:

```text
exeBlock_conf_info_t_final_field_encoder_missing
endpoint_slots_source_roundtrip_missing
```

## Agent J5 Result

MICC runtime/order policy advanced from decoded structs to decoded order policy:

```text
final_status = decoded_order_policy_available_runtime_trace_missing

closed:
  task_active_subtask_order
  task/subtask_start_end_policy
  subtask_successor_order
  embedded_exeBlock_roundtrip
  instance_table_address_roundtrip
  exeBlock_instruction_range_roundtrip
```

Remaining:

```text
runtime_start_wait_trace_missing
exeBlock_wait_or_dependency_flags_unproven
exeBlock_is_leaf_policy_unproven
```

## Agent K5 Result

ReLU active selector is now blocked on task activation evidence, not on the
instruction form itself:

```text
vendor_source = subtask4 ReLU generator
row_pattern = IMM ZERO_relu -> HMAX ZERO_relu,input,output
fiber_chain = gemm_tile -> relu_tile -> store_tile
fused_or_epilogue_claim = False
active_runtime_claim = False
```

Remaining:

```text
generated_subtask4_relu_template_csv_for_customer_shape
app_conf_subtask_num_4_or_equivalent_explicit_relu_task
secondary_fusion_array_or_bline_op_chain_activation_record
decoded_subtask4_imm_hmax_roundtrip
```

## Agent L5 Result

log10max PE00 candidate requests now carry synthetic raw `inst_t` rows for
planning and hashing, without claiming final selector/runtime status:

```text
pe00_fmax_combine:
  rows = 15
  row_size = 304
  opcode = FMAX / 0x027

pe00_scalar_store:
  rows = 1
  row_size = 304
  opcode = STD / 0x080

consumer_readback:
  rows = 16
  row_size = 304
  opcode = ILDMT / 0x107

claims:
  exact_legacy_row_selector = False
  active_runtime_family = False
  row_bytes = False
  physical_route_allreduce = False
```

Remaining:

```text
exact_legacy_row_selector_missing
active_template_family_source_missing
operand_index_address_decode_roundtrip_missing
decoded_readback_to_max_with_floor_operand_link_roundtrip_missing
```

## Agent M6 Result

GEMM no-ReLU CBUF exeBlock proof advanced again:

```text
endpoint_slots_status = decoded_endpoint_slots_match_source_records
endpoint_slots_source_roundtrip_claim = True
endpoint_slots_missing_source_fields = []
```

Remaining CBUF blocker:

```text
exeBlock_conf_info_t_source_field_provenance_missing
missing_source_fields:
  valid
  priority
  instances_amount
  block_class
```

This still does not claim final CBUF/runtime readiness.

## Agent N6 Result

MICC local runtime policy proof now closes wait/leaf structural policy:

```text
final_status = decoded_wait_leaf_policy_available_runtime_trace_missing
exeBlock_wait_or_dependency_flags = available_debug_structural_dependency_policy
exeBlock_is_leaf_policy = available_debug_conservative_zero_policy
```

Remaining MICC blocker:

```text
runtime_start_wait_trace_missing
```

## Agent O6 Result

GEMM+ReLU explicit B-line activation is now locally closed without fused or
epilogue semantics:

```text
activation_record = ReluSubtask4ActivationRecord
generated_csv_candidate_status = closed
explicit_task_activation_status = closed
op_chain_activation_status = closed
local_decode_roundtrip_status = closed
decoded_ops = IMM, HMAX
decoded_opcodes = 0x22, 0x53
fiber_chain = gemm_tile -> relu_tile -> store_tile
```

Remaining ReLU blocker:

```text
active_relu_template_family_selector_proof
active_subtask4_runtime_selector_trace
```

## Agent P6 Result

log10max PE00 materialized scalar synthetic path is now internally decoded and
linked:

```text
synthetic_decode_roundtrip = available
synthetic_operand_role_roundtrip = available
synthetic_receiver_operand_link_matrix = available
active_runtime_family_claim = False
row_bytes_claim = False
physical_route_allreduce = False
```

Remaining log10max blocker:

```text
exact_legacy_row_selector_missing
active_template_family_source_missing
active_operand_index_address_decode_roundtrip_missing
active_decoded_readback_to_max_with_floor_operand_link_roundtrip_missing
```

## Baseline Checks

```bash
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_bline_runtime_ready_preintegration.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_no_relu_safe_subset.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_relu_fiber_chain.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_relu_binding.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_collective.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_templates.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_fiber_chain.py
```
