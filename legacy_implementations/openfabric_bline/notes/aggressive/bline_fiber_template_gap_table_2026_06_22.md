# B-line Fiber -> Template Gap Table

Date: 2026-06-22

This is the current aggressive-progress map for the first-version operators:
GEMM, GEMM+ReLU, and log10max.

Architecture rule: Fiber is a flat sequence of PE-local atomic tile jobs. A
FiberOp must not hide an epilogue, fused post-op, internal K-loop, or vendor
subtask staging. Template lowering may expand one FiberOp into a template span
or row expansion after the FiberOp boundary, with provenance preserved.

Terminology rule: do not use `bundle` for Fiber or Template semantics. Use
`template span`, `template expansion`, or `template lowering plan`. `bundle` is
reserved for final SimICT/package/customer packaging only.

## Current Status

| Operator | Upper -> Fiber status | Fiber -> template status | Binary pressure | Priority |
|---|---|---|---|---|
| GEMM | Main path closed as `gemm_tile -> store_tile` | `gemm_tile` and `store_tile` are production-mapped; light layout reaches `emittable_debug`; exact CSV/template/local-order selector is machine-checkable | Row bytes and raw row hashes still missing; selector/output-binding blockers are closed | P0 |
| GEMM+ReLU | Chain closed as `gemm_tile -> relu_tile -> store_tile` | `relu_tile` is production-mapped as `tile_op:relu`; DFU3500 HMAX-with-zero row placement is concrete | Need exact ReLU/HMAX selector, IMM-zero row selector, operand indexes, local_order, raw row bytes, and raw row hashes; legacy GEMM CSV has IMM rows but no HMAX/FMAX ReLU row, while functional `IMM+FMAX` probe is fp32-only evidence | P0 |
| log10max | Chain closed as `clamp_min_tile -> log10_tile -> local_reduce_max_tile -> global_max_tile -> max_with_floor_tile -> affine_scale_tile -> store_tile` | 5 local ops are production-mapped to roles/template statuses; PE00/global scalar contract selected as `pe00_aggregate_materialize`; vendor-row/MICC/receiver lowering intents now exist | Need concrete vendor row bytes and runtime execution proof for PE00 scalar path; blocker reports now name exact missing row/proof fields | P0 |

## Current Gap Count

| Count type | Count | Meaning |
|---|---:|---|
| Parallel engineering blocks | 3 | GEMM/store row bytes, ReLU writer/evidence, PE00/vendor row lowering |
| Closed production FiberOps | 8 | `gemm_tile`, `store_tile`, `relu_tile`, `clamp_min_tile`, `log10_tile`, `local_reduce_max_tile`, `max_with_floor_tile`, `affine_scale_tile` |
| Report-only log10max FiberOps | 1 | `global_max_tile` remains contract/template-bound but not row-byte/runtime-ready |
| Current hard blockers | 3 | GEMM/store raw bytes/hash materializer, ReLU exact writer row bytes, PE00 vendor row bytes/runtime execution proof |

## Gap Table

| Workstream | FiberOp / action | Used by | Upper -> Fiber | Template evidence | Binary/layout status | Gap to close |
|---|---|---|---|---|---|---|
| A | `gemm_tile` | GEMM, GEMM+ReLU | Production main path closed | `legacy_expanded_gemm_tile_template_span` candidate | `GEMM_TILE_TEMPLATE_SPAN`, `subtask1_gemm_tile_template_span`; selector policy `GEMM_TILE_HMMAL_LOCAL_ORDER_SPAN_SELECTOR_V1` selects legacy CSV/template/local_orders while preserving `primary_fiber_op_id` | Emit raw `inst_t` bytes and raw row hashes for the selected HMMAL span without reintroducing internal FiberOps |
| A | `store_tile` | all three | Production for GEMM/ReLU; report reuse for log10max | STD candidate | `STD`, `subtask3_store_tile`; selector policy `STORE_TILE_STD_OUTPUT_LOCAL_ORDER_SELECTOR_V1` selects output binding + legacy STD CSV/template/local_orders while preserving store Fiber provenance | Emit raw `inst_t` bytes and raw row hashes for selected STD rows; reuse selector shape for non-GEMM stores |
| B | `relu_tile` | GEMM+ReLU | Production chain closed | HMAX/FMAX-with-zero local template evidence closed at semantics/template-placement level; exact row evidence now distinguishes legacy GEMM CSV, functional maximum probe, and required B-line ReLU selector | 64 `HMAX` rows in `subtask4_relu_candidate`; writer evidence status `candidate_relu_tile_template_span`; ReLU binding remains fail-closed with `blocked_missing_hmax_or_relu_specific_selector` on all 64 ReLU tiles | Bind exact ReLU/HMAX selector, IMM-zero row selector, operand indexes, local_order, raw row bytes, and raw row hashes; do not treat fp32 `IMM+FMAX` probe as fp16 HMAX proof |
| C | `clamp_min_tile` | log10max | Production chain closed | FMAX immediate clamp candidate | Production-mapped as `tile_op:clamp_min`; concrete TemplateOp intent | Row-byte materializer still later, but local role/template status is closed |
| C | `log10_tile` | log10max | Production chain closed | FLOG2 + FMUL log10(2) candidate | Production-mapped as `tile_op:log10`; concrete TemplateOp intents | Row-byte materializer still later; numerical constants remain in contract |
| C | `local_reduce_max_tile` | log10max | Production chain closed | SHFL + FMAX skeleton | Production-mapped as `tile_reduce:local_reduce_max`; concrete TemplateOp intents | Row-byte materializer still needs lane/reduce row bytes |
| D | `global_max_tile` | log10max | Report chain closed | Strategy selected: `pe00_aggregate_materialize`; PE00 template/order/receiver contracts available | Vendor-row intent exists for PE00 FMAX combine, scalar store, and consumer readback; each entry now carries `row_byte_proof_plan`; MICC order carries `runtime_order_proof_plan`; no row-bytes/runtime-ready claim | Materialize exact `inst_t` rows, MICC successor/wait rows, raw bytes, and row hashes |
| D | `max_with_floor_tile` | log10max | Production chain closed | FMAX vector-scalar local shape ready; scalar visibility source contract complete | Receiver operand binding intent exists for global scalar consumption and now carries `receiver_binding_proof_plan`; still symbolic until PE00 scalar row-byte path is real | Bind readback destination operand to concrete max-with-floor row bytes |
| C | `affine_scale_tile` | log10max | Production chain closed | FADD + FMUL local sequence candidate | Production-mapped as one explicit `tile_op:affine_scale` FiberOp template span, not a semantic bundle | Row-byte materializer still needs FADD/FMUL expansion under one FiberOp provenance span |

## Dispatch Plan

| Block | Owner | Files / modules | Completion signal |
|---|---|---|---|
| A | Fork worker | `template_ops.py`, `binary_plan.py`, `dfu3500_semantics.py`, `inst_writers.py` | GEMM stays `gemm_tile -> store_tile`; exact template span provenance is present |
| B | Main thread first stage complete; fork only if needed | `fiber.py`, `executable.py`, `op_specs`, `template_ops.py`, `dfu3500_semantics.py`, `binary_plan.py`, `inst_writers.py` | ReLU remains independent `tile_op:relu`; writer/evidence close without GEMM epilogue |
| C | Recovered and closed | `fiber.py`, `executable.py`, `template_ops.py`, `template_records.py`, `dfu3500_semantics.py`, `log10max_fiber_chain.py`, `log10max_template_pack.py` | log10max local FiberOps have production roles/template statuses; row-byte materialization intentionally remains out of scope |
| D | Current thread advanced | `log10max_collective_strategy.py`, `log10max_template_pack.py`, `program_runtime.py`, `binding.py`, `micc_component_writers.py` | PE00 materialize/readback/order/receiver/FMAX contracts are closed and now expose structured row-byte/runtime/receiver proof blockers; next step is exact row bytes and decoded MICC/runtime proof |

## Agent Recovery Status

| Agent | Agent id | Status | Accepted result |
|---|---|---|---|
| Gibbs | `019eefa9-4166-7c60-9223-7a7919249a70` | Recovered and closed | GEMM/store template-span provenance materialization candidates; raw bytes remain fail-closed |
| Cicero | `019eefa9-0655-7960-9d4d-4cc423ebbb05` | Recovered and closed | PE00 global scalar contract closed without direct-physical-allreduce or runtime-ready claim |
| Noether | `019eefa9-01a6-7c93-a100-87224b5a5a45` | Recovered and closed | `relu_tile` production mapping established as independent FiberOp |
| Kant | `019eefb4-1d98-70e0-88fb-96ecb5989458` | Recovered in main workspace | GEMM/store row-byte lowering did not emit bytes; byte-materializer blocker report now names `span_row_selector_policy`, `store_output_binding`, csv/template/local_orders, raw bytes, and raw hash gaps |
| Hegel | `019eefb4-207b-7c83-a9fa-e35cde2f9be1` | Recovered and closed | log10max local ops production-mapped; `global_max_tile` and PE00 row-byte/runtime remain fail-closed |
| Tesla | `019eefb4-239d-7160-9190-5c3dd057e45f` | Recovered in main workspace | PE00 contract-to-vendor/MICC lowering intent added; `runtime_ready=False`, no direct-physical-allreduce claim, row bytes still blocked |
| Ampere | `019eefb9-9ee5-7d52-b6df-2607b7f8edd2` | Recovered in main workspace | `dfu3500_semantics_relu_tile` closed; `binary_writer_relu_tile` remains exact row-byte blocker |
| Pauli | `019eefb9-a334-7643-84fe-6701bcd41692` | Recovered in main workspace | Third-round GEMM/store exact span row selector closed: selector/output-binding blockers removed; raw bytes/hash remain fail-closed |
| Zeno | `019eefb9-a7d6-7fe2-b1dc-5b881462ce54` | Recovered in main workspace | Third-round PE00 proof narrowing: `row_byte_proof_plan`, `runtime_order_proof_plan`, and `receiver_binding_proof_plan` added; `runtime_ready=False`, no direct-physical-allreduce claim |
| Socrates | `019eefca-99f9-7d93-9884-524a231f348c` | Running after commit `1b460e8` | Common raw `inst_t` byte materializer for selected legacy rows |
| Goodall | `019eefca-9ccb-7332-b480-b7c594d7a6af` | Running after commit `1b460e8` | ReLU exact HMAX/IMM-zero evidence and operand/local-order blocker narrowing |
| Mencius | `019eefca-9fde-7eb0-a24c-68e78fec2b17` | Running after commit `1b460e8` | PE00 FMAX/store/readback/runtime/receiver proof narrowing |
| Volta | `019eefca-a37f-7851-b273-b16939effc06` | Running after commit `1b460e8` | Minimal runtime_ready/package gate pre-integration, fail-closed until raw bytes/proofs exist |

## Light Check Snapshot

```text
check_stream_compiler_no_relu_safe_subset.py      OK
check_stream_compiler_relu_fiber_chain.py         OK
check_stream_compiler_relu_binding.py             OK
check_stream_compiler_log10max_fiber_chain.py     OK
check_stream_compiler_log10max_collective.py      OK
check_stream_compiler_log10max_templates.py       OK
```

Latest PE00 proof-blocker snapshot:

```text
vendor_row_plan.row_byte_proof_summary.status=blocked_structured_row_bytes_missing
row_byte_proof_summary.blocker_ids=[
  pe00_fmax_combine_order_row_bytes_missing,
  producer_pe00_physical_store_row_bytes_missing,
  consumer_physical_readback_row_bytes_missing,
]
runtime_order_proof_plan.status=blocked_structured_runtime_proof_missing
receiver_binding_proof_plan.status=blocked_structured_receiver_binding_proof_missing
runtime_ready=False
row_bytes_claim=False
physical_route_allreduce=False
```

Latest GEMM/store selector/materializer snapshot:

```text
selector_status_counts={'selector_policy_candidate_available': 128}
selector_row_counts={'compute_core:gemm_tile': 32768, 'tile_store': 4096}
byte_materializer_status_counts={'blocked_missing_raw_inst_t_row_bytes': 128}
missing_byte_materializer_input_counts={
  'raw_inst_t_row_bytes': 128,
  'raw_template_row_sha256': 128,
}
```

Latest ReLU exact-row evidence snapshot:

```text
chain=gemm_tile->relu_tile->store_tile
relu_exact_row_selector_status_counts={
  'blocked_missing_hmax_or_relu_specific_selector': 64,
}
legacy_gemm_profile_hmax_rows=0
legacy_gemm_profile_fmax_rows=0
legacy_gemm_profile_imm_rows=128
functional_maximum_probe_fmax_rows=16
functional_maximum_probe_imm_rows=16
missing_writer_inputs=[
  relu_zero_constant_row_selector,
  relu_max_row_selector,
  relu_input_operand_binding,
  relu_zero_operand_index,
  relu_output_operand_binding,
  relu_local_order,
  raw_inst_t_row_bytes,
  raw_template_row_sha256,
]
binary_ready=False
runtime_ready=False
```

## Naming Debt

Existing upper tile collective code still contains `collective_bundles` /
`TileCollectiveBundle` as data-field names. Do not spread that term into
FiberOp or template semantics. When touching that area for the PE00 closure,
migrate user-facing names toward `collective_action`, `collective_edge`, or
`collective_lowering_plan` while keeping compatibility shims if needed.
