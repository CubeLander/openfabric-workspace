#!/usr/bin/env python3
"""Fail-closed B-line runtime_ready pre-integration gate.

This is not the full validation framework.  It is the minimum local gate that
will sit between raw row-byte materializers and eventual package assembly for
the three first-version operators.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPILER_ROOT = REPO_ROOT / "compiler"
TOOLS_ROOT = COMPILER_ROOT / "tools"
for path in (COMPILER_ROOT, TOOLS_ROOT):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from gpdpu_compiler.core.op_specs import LOG10MAX_SPEC, MATMUL_SPEC  # noqa: E402
from gpdpu_compiler.core.stream_compiler.aline_gemm_evidence import (  # noqa: E402
    build_aline_gemm_evidence_report,
)
from gpdpu_compiler.core.stream_compiler.binary_plan import (  # noqa: E402
    lower_template_ops_to_binary_layout,
)
from gpdpu_compiler.core.stream_compiler.binding import (  # noqa: E402
    bind_executable_roles_symbolically,
)
from gpdpu_compiler.core.stream_compiler.component_writers import (  # noqa: E402
    emit_debug_instance_conf_info_component,
)
from gpdpu_compiler.core.stream_compiler.debug_emit import (  # noqa: E402
    emit_debug_row_artifact,
)
from gpdpu_compiler.core.stream_compiler.dfu3500_semantics import (  # noqa: E402
    lower_template_records_to_dfu3500_semantics,
)
from gpdpu_compiler.core.stream_compiler.executable import (  # noqa: E402
    lower_fibers_to_executable_ops,
)
from gpdpu_compiler.core.stream_compiler.field_offsets import (  # noqa: E402
    build_field_offset_preflight_plan,
)
from gpdpu_compiler.core.stream_compiler.folding import (  # noqa: E402
    analyze_stream_loop_folding,
)
from gpdpu_compiler.core.stream_compiler.gemm_demo import (  # noqa: E402
    build_demo_gemm_stream_plan,
)
from gpdpu_compiler.core.stream_compiler.inst_writers import (  # noqa: E402
    build_aline_template_span_candidate_report,
    build_compressed_template_span_authority_report,
    build_exact_span_row_selector_policy_report,
    build_exact_template_span_hash_candidate_report,
    build_template_evidence_binding_report,
    build_template_span_materialization_candidate_report,
    summarize_exact_span_row_selector_policy_report,
    summarize_template_evidence_binding_report,
    summarize_template_span_materialization_candidate_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_collective_strategy import (  # noqa: E402
    build_current_log10max_plan,
    build_log10max_capacity_proof_report,
    summarize_log10max_capacity_proof_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_globalmax_consumer_binding import (  # noqa: E402
    build_log10max_globalmax_consumer_binding_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_operator_payload import (  # noqa: E402
    LOG10MAX_OPERATOR_PAYLOAD_MANIFEST_BLOCKED,
    build_log10max_operator_payload_manifest_candidate,
    summarize_log10max_operator_payload_manifest_candidate,
)
from gpdpu_compiler.core.stream_compiler.log10max_ring_plan import (  # noqa: E402
    build_log10max_task_local_ring_plan,
)
from gpdpu_compiler.core.stream_compiler.log10max_ring_fiber_projection import (  # noqa: E402
    build_log10max_ring_fiber_projection_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_ring_update_template import (  # noqa: E402
    build_log10max_ring_update_binary_layout_candidate_report,
    build_log10max_ring_update_template_binding_report,
)
from gpdpu_compiler.core.stream_compiler.micc_component_writers import (  # noqa: E402
    build_gemm_no_relu_micc_final_candidate_report,
    emit_micc_exeBlock_conf_info_component,
    emit_micc_sub_task_conf_info_component,
    emit_micc_task_conf_info_component,
)
from gpdpu_compiler.core.stream_compiler.operator_payload_assembly import (  # noqa: E402
    RuntimeReadyGateInputStatus,
    RuntimeReadyPreIntegrationReport,
    build_gemm_no_relu_component_payload_candidate_report,
    build_runtime_ready_preintegration_report,
    summarize_gemm_no_relu_component_payload_candidate_report,
    summarize_runtime_ready_preintegration_report,
)
from gpdpu_compiler.core.stream_compiler.relu_binding import (  # noqa: E402
    bind_explicit_relu_subtasks,
    summarize_explicit_relu_subtask_binding_report,
)
from gpdpu_compiler.core.stream_compiler.relu_fiber_chain import (  # noqa: E402
    build_gemm_relu_fiber_chain_report,
)
from gpdpu_compiler.core.stream_compiler.route_role_binding import (  # noqa: E402
    build_route_role_binding_report,
)
from gpdpu_compiler.core.stream_compiler.schedule import (  # noqa: E402
    build_fiber_execution_schedule,
)
from gpdpu_compiler.core.stream_compiler.serializer_readiness import (  # noqa: E402
    build_serializer_readiness_plan,
)
from gpdpu_compiler.core.stream_compiler.template_ops import (  # noqa: E402
    lower_schedule_to_template_ops,
)
from gpdpu_compiler.core.stream_compiler.template_records import (  # noqa: E402
    lower_symbolic_bindings_to_template_records,
)
from gpdpu_compiler.core.stream_compiler.vendor_components import (  # noqa: E402
    build_vendor_component_plan,
)
from gpdpu_compiler.core.stream_compiler.vendor_groups import (  # noqa: E402
    group_debug_rows_vendor_like,
    remap_vendor_like_groups_locally,
)
from stream_compiler_demo_pipeline import build_demo_pipeline  # noqa: E402


NO_RELU_SPAN_POLICY_ROLES = {
    "compute_core:gemm_tile",
    "tile_store",
}

LOG10MAX_INST_FIELD_OWNERSHIP_MISSING = "log10max_inst_field_ownership_missing"
LOG10MAX_INST_FIELD_BINDING_MISSING = "log10max_inst_field_binding_missing"
LOG10MAX_RING_UPDATE_ROW_BODY_CANDIDATE_BYTES_MISSING = (
    "log10max_ring_update_row_body_candidate_bytes_missing"
)
LOG10MAX_RING_UPDATE_COMPONENT_INTEGRATED_BYTES_MISSING = (
    "log10max_ring_update_component_integrated_bytes_missing"
)
LOG10MAX_ROUTE_ENDPOINT_STATUS_MISSING = (
    "log10max_route_endpoint_status_missing"
)
LOG10MAX_ROUTE_FAMILY_PHASE2_DECISION_MISSING = (
    "log10max_route_family_phase2_decision_missing"
)
LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING = (
    "log10max_route_flow_ack_policy_missing"
)
LOG10MAX_INSTRUCTION_LAYOUT_PLAN_MISSING = (
    "log10max_instruction_layout_plan_missing"
)
LOG10MAX_EXE_BLOCK_WRITER_PLAN_MISSING = (
    "log10max_exe_block_writer_plan_missing"
)
LOG10MAX_INSTRUCTION_BOUNDARY_PLAN_MISSING = (
    "log10max_instruction_boundary_plan_missing"
)
LOG10MAX_COMPONENT_PLACEMENT_INTEGRATION_MISSING = (
    "log10max_component_placement_integration_missing"
)


def main() -> None:
    args = _parse_args()
    report = build_current_preintegration_report()
    summary = summarize_runtime_ready_preintegration_report(report)
    failures = _validate_report(summary, report.to_plan())

    if args.json:
        print(json.dumps(report.to_plan(), indent=2, sort_keys=True))

    if failures:
        print("B-line runtime_ready pre-integration check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("B-line runtime_ready pre-integration check OK")
    print(f"final_state={summary['final_state']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")
    print(f"operator_states={summary['operator_states']}")
    print(f"operator_missing_counts={summary['operator_missing_counts']}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check the fail-closed B-line runtime_ready pre-integration gate.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the full pre-integration gate report.",
    )
    return parser.parse_args()


def build_current_preintegration_report():
    (
        gemm_materialization_summary,
        gemm_selector_summary,
        gemm_payload_component_summary,
    ) = _gemm_raw_byte_inputs()
    relu_binding_summary, relu_writer_summary = _relu_writer_inputs()
    log10_summary, log10_plan = _log10max_inputs()
    report = build_runtime_ready_preintegration_report(
        gemm_materialization_summary=gemm_materialization_summary,
        gemm_selector_summary=gemm_selector_summary,
        gemm_payload_component_summary=gemm_payload_component_summary,
        relu_binding_summary=relu_binding_summary,
        relu_writer_summary=relu_writer_summary,
        log10max_collective_summary=log10_summary,
        log10max_collective_plan=log10_plan,
        payload_files_claimed=bool(
            gemm_payload_component_summary.get("payload_files_claimed")
        ),
        placeholder_files_present=False,
    )
    return _augment_log10max_inst_field_provenance_gate(report, log10_plan)


def _augment_log10max_inst_field_provenance_gate(
    report: RuntimeReadyPreIntegrationReport,
    log10max_collective_plan: dict[str, object],
) -> RuntimeReadyPreIntegrationReport:
    """Add the accepted Phase 0/1 inst-field gate without changing readiness.

    The shared payload assembly gate currently models log10max through the ring
    strategy and ring-update row-byte blockers.  The accepted field-provenance
    RFC inserts one narrower fail-closed layer before row bytes may be consumed:
    row-body candidate bytes are only diagnostic/candidate proof, and component
    integration is a later RFC boundary.
    """

    ring_plan = _ring_first_plan(log10max_collective_plan)
    updated_statuses: list[RuntimeReadyGateInputStatus] = []
    for status in report.operator_statuses:
        if status.operator != "log10max":
            updated_statuses.append(status)
            continue
        updated_statuses.append(
            _with_log10max_inst_field_provenance_status(status, ring_plan)
        )
    return RuntimeReadyPreIntegrationReport(
        operator_statuses=tuple(updated_statuses),
        payload_files_claimed=report.payload_files_claimed,
        placeholder_files_present=report.placeholder_files_present,
        runtime_ready_scope=report.runtime_ready_scope,
        schema_version=report.schema_version,
    )


def _ring_first_plan(collective_plan: dict[str, object]) -> dict[str, object]:
    for key in (
        "ring_first_delivery_plan",
        "ring_spmd_row_then_col_plan",
        "representative_ring_plan",
    ):
        candidate = collective_plan.get(key, {})
        if isinstance(candidate, dict):
            return candidate
    return {}


def _with_log10max_inst_field_provenance_status(
    status: RuntimeReadyGateInputStatus,
    ring_plan: dict[str, object],
) -> RuntimeReadyGateInputStatus:
    inst_field_summary = _log10max_inst_field_provenance_summary(ring_plan)
    route_layout_summary = _log10max_route_layout_summary(ring_plan)
    operator_payload_summary = _log10max_operator_payload_summary()
    missing = list(status.missing_blockers)
    missing.extend(inst_field_summary["missing_blockers"])
    missing.extend(route_layout_summary["missing_blockers"])
    missing.extend(operator_payload_summary["missing_blockers"])
    return RuntimeReadyGateInputStatus(
        operator=status.operator,
        gate_id=status.gate_id,
        state="blocked" if missing else status.state,
        runtime_ready=False,
        uploadable=False,
        missing_blockers=tuple(_dedupe(missing)),
        summary={
            **dict(status.summary),
            "inst_field_provenance_gate": inst_field_summary,
            "route_layout_gate": route_layout_summary,
            "operator_payload_gate": operator_payload_summary,
        },
        evidence_refs=tuple(
            _dedupe(
                (
                    *status.evidence_refs,
                    "docs/compiler/design/"
                    "bline-inst-row-byte-field-provenance-rfc.md",
                    "docs/compiler/design/bline-route-row-bytes-layout-rfc.md",
                    "docs/compiler/design/"
                    "bline-log10max-operator-payload-integration-rfc.md",
                )
            )
        ),
    )


def _log10max_inst_field_provenance_summary(
    ring_plan: dict[str, object],
) -> dict[str, object]:
    gate = ring_plan.get("inst_field_provenance_gate", {})
    if not isinstance(gate, dict):
        gate = {}

    field_ownership_status = str(
        gate.get("field_ownership_status", "missing")
    )
    field_binding_status = str(gate.get("field_binding_status", "missing"))
    row_body_candidate_status = str(
        gate.get("row_body_candidate_status", "missing")
    )
    component_integration_status = str(
        gate.get("component_integration_status", "not_integrated")
    )
    placement_status = str(gate.get("placement_status", "unplaced_candidate"))

    missing: list[str] = []
    if field_ownership_status not in {"bound", "complete"}:
        missing.append(LOG10MAX_INST_FIELD_OWNERSHIP_MISSING)
    if field_binding_status not in {"bound", "complete"}:
        missing.append(LOG10MAX_INST_FIELD_BINDING_MISSING)
    if row_body_candidate_status not in {
        "candidate_decode_roundtrip",
        "row_body_bytes_emitted",
    }:
        missing.append(LOG10MAX_RING_UPDATE_ROW_BODY_CANDIDATE_BYTES_MISSING)
    if (
        component_integration_status != "component_integrated"
        or placement_status != "component_integrated"
    ):
        missing.append(LOG10MAX_RING_UPDATE_COMPONENT_INTEGRATED_BYTES_MISSING)

    candidate_decode_roundtrip = (
        row_body_candidate_status == "candidate_decode_roundtrip"
    )
    return {
        "accepted_rfc_phase": "phase_0_1_report_only",
        "field_ownership_status": field_ownership_status,
        "field_binding_status": field_binding_status,
        "row_body_candidate_status": row_body_candidate_status,
        "component_integration_status": component_integration_status,
        "placement_status": placement_status,
        "candidate_decode_roundtrip": candidate_decode_roundtrip,
        "candidate_decode_roundtrip_is_uploadable": False,
        "runtime_ready_claim": False,
        "uploadable_claim": False,
        "missing_blockers": missing,
        "forbidden_scope": (
            "route_COPY_COPYT_LDN_raw_bytes",
            "final_CBUF_MICC_component_insertion",
            "component_byte_offsets",
            "runtime_ready_transition",
        ),
    }


def _log10max_route_layout_summary(
    ring_plan: dict[str, object],
) -> dict[str, object]:
    gate = ring_plan.get("route_layout_gate", {})
    if not isinstance(gate, dict):
        gate = {}

    route_endpoint_status = str(
        gate.get("route_endpoint_status", "missing")
    )
    route_family_status = str(
        gate.get("route_family_status", "pending_phase2_decision")
    )
    flow_ack_status = str(gate.get("flow_ack_status", "pending_policy"))
    instruction_layout_status = str(
        gate.get("instruction_layout_status", "missing")
    )
    exe_block_writer_status = str(
        gate.get("exe_block_writer_status", "missing")
    )
    boundary_status = str(gate.get("boundary_status", "missing"))
    component_placement_status = str(
        gate.get("component_placement_status", "unplaced_candidate")
    )
    route_candidate_decode_status = str(
        gate.get("route_candidate_decode_status", "not_emitted")
    )

    missing: list[str] = []
    if route_endpoint_status not in {
        "endpoint_bound_layout_pending",
        "endpoint_bound",
        "bound",
    }:
        missing.append(LOG10MAX_ROUTE_ENDPOINT_STATUS_MISSING)
    if route_family_status != "selected":
        missing.append(LOG10MAX_ROUTE_FAMILY_PHASE2_DECISION_MISSING)
    if flow_ack_status != "bound":
        missing.append(LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING)
    if instruction_layout_status not in {"planned", "pc_assigned"}:
        missing.append(LOG10MAX_INSTRUCTION_LAYOUT_PLAN_MISSING)
    if exe_block_writer_status not in {"planned", "micc_candidate"}:
        missing.append(LOG10MAX_EXE_BLOCK_WRITER_PLAN_MISSING)
    if boundary_status != "bound":
        missing.append(LOG10MAX_INSTRUCTION_BOUNDARY_PLAN_MISSING)
    if component_placement_status != "component_integrated":
        missing.append(LOG10MAX_COMPONENT_PLACEMENT_INTEGRATION_MISSING)

    candidate_decode_roundtrip = (
        route_candidate_decode_status == "candidate_route_decode_roundtrip"
    )
    return {
        "accepted_rfc_phase": "phase_0_1_report_only",
        "route_endpoint_status": route_endpoint_status,
        "route_family_status": route_family_status,
        "flow_ack_status": flow_ack_status,
        "instruction_layout_status": instruction_layout_status,
        "exe_block_writer_status": exe_block_writer_status,
        "boundary_status": boundary_status,
        "component_placement_status": component_placement_status,
        "route_candidate_decode_status": route_candidate_decode_status,
        "route_family_pending_is_selected": False,
        "candidate_decode_roundtrip": candidate_decode_roundtrip,
        "candidate_decode_roundtrip_is_uploadable": False,
        "component_integrated_required_for_runtime_ready": True,
        "runtime_ready_claim": False,
        "uploadable_claim": False,
        "missing_blockers": missing,
        "forbidden_scope": (
            "route_COPY_COPYT_LDN_raw_bytes",
            "final_CBUF_MICC_component_insertion",
            "component_byte_offsets",
            "runtime_ready_transition",
        ),
    }


def _log10max_operator_payload_summary() -> dict[str, object]:
    manifest = build_log10max_operator_payload_manifest_candidate()
    summary = summarize_log10max_operator_payload_manifest_candidate(manifest)
    return {
        "accepted_rfc_phase": "phase_5_report_only",
        "readiness_claim": summary["readiness_claim"],
        "component_manifest_status": summary["component_manifest_status"],
        "operator_payload_manifest_status": (
            summary["operator_payload_manifest_status"]
        ),
        "required_file_roles": summary["required_file_roles"],
        "present_file_roles": summary["present_file_roles"],
        "missing_file_roles": summary["missing_file_roles"],
        "blockers_by_layer": summary["blockers_by_layer"],
        "diagnostic_hashes": summary["diagnostic_hashes"],
        "component_hashes": summary["component_hashes"],
        "runtime_ready_claim": False,
        "uploadable_claim": False,
        "runtime_ready": False,
        "uploadable": False,
        "missing_blockers": summary["blocker_ids"],
    }


def _dedupe(items) -> list[object]:
    seen: set[object] = set()
    deduped: list[object] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        deduped.append(item)
    return deduped


def _gemm_raw_byte_inputs() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    pipeline = build_demo_pipeline("gemm_no_relu")
    component_sections = _gemm_component_section_payloads(pipeline)
    aline_report = build_aline_gemm_evidence_report()
    aline_span_report = build_aline_template_span_candidate_report(
        pipeline.binary_layout,
        aline_report,
    )
    compressed_span_report = build_compressed_template_span_authority_report(
        pipeline.binary_layout,
        aline_span_report,
        enabled_role_span_policies=NO_RELU_SPAN_POLICY_ROLES,
    )
    exact_span_hash_report = build_exact_template_span_hash_candidate_report(
        pipeline.binary_layout,
        compressed_span_report,
    )
    selector_report = build_exact_span_row_selector_policy_report(
        pipeline.binary_layout,
    )
    materialization_report = build_template_span_materialization_candidate_report(
        pipeline.binary_layout,
        exact_span_hash_report,
        selector_policy_report=selector_report,
    )
    payload_component_report = build_gemm_no_relu_component_payload_candidate_report(
        materialization_report,
        cbuf_exeblock_payload=component_sections["exeblock"],
        cbuf_instance_payload=component_sections["instance"],
        cbuf_exeblock_artifact_plan=component_sections["exeblock_plan"],
        cbuf_instance_artifact_plan=component_sections["instance_plan"],
        micc_subtask_artifact_plan=component_sections["subtask_plan"],
        micc_task_payload=component_sections["task"],
        micc_subtask_payload=component_sections["subtask"],
        micc_final_candidate_summary=component_sections["micc_final_summary"],
    )
    return (
        summarize_template_span_materialization_candidate_report(
            materialization_report
        ),
        summarize_exact_span_row_selector_policy_report(selector_report),
        summarize_gemm_no_relu_component_payload_candidate_report(
            payload_component_report
        ),
    )


def _gemm_component_section_payloads(pipeline) -> dict[str, bytes]:
    artifact = emit_debug_row_artifact(pipeline.binary_layout)
    groups = group_debug_rows_vendor_like(artifact)
    remap = remap_vendor_like_groups_locally(groups)
    component_plan = build_vendor_component_plan(
        remap,
        loop_fold_report=analyze_stream_loop_folding(pipeline.schedule),
    )
    offset_plan = build_field_offset_preflight_plan(component_plan)
    readiness_plan = build_serializer_readiness_plan(component_plan, offset_plan)
    instance = emit_debug_instance_conf_info_component(component_plan, readiness_plan)
    task = emit_micc_task_conf_info_component(component_plan, readiness_plan)
    exeblock = emit_micc_exeBlock_conf_info_component(component_plan, readiness_plan)
    subtask = emit_micc_sub_task_conf_info_component(component_plan, readiness_plan)
    micc_final_summary = build_gemm_no_relu_micc_final_candidate_report(
        task_artifact=task,
        subtask_artifact=subtask,
        exeblock_artifact=exeblock,
    )
    return {
        "instance": instance.payload,
        "instance_plan": _artifact_plan_without_payload_hex(instance),
        "task": task.payload,
        "exeblock": exeblock.payload,
        "exeblock_plan": _artifact_plan_without_payload_hex(exeblock),
        "subtask": subtask.payload,
        "subtask_plan": _artifact_plan_without_payload_hex(subtask),
        "micc_final_summary": micc_final_summary,
    }


def _artifact_plan_without_payload_hex(artifact) -> dict[str, object]:
    plan = artifact.to_plan()
    plan.pop("payload_hex", None)
    return plan


def _relu_writer_inputs() -> tuple[dict[str, object], dict[str, object]]:
    plan = build_demo_gemm_stream_plan(include_relu=True)
    chain_report = build_gemm_relu_fiber_chain_report(plan)
    executable = lower_fibers_to_executable_ops(
        chain_report.fibers,
        executable_role_profile=MATMUL_SPEC.executable_role_profile(),
    )
    bindings = bind_executable_roles_symbolically(
        executable,
        template_intents=MATMUL_SPEC.template_intent_profile(),
    )
    template_records = lower_symbolic_bindings_to_template_records(bindings)
    semantic_report = lower_template_records_to_dfu3500_semantics(template_records)
    schedule = build_fiber_execution_schedule(executable, semantic_report)
    template_plan = lower_schedule_to_template_ops(
        schedule,
        semantic_report=semantic_report,
        template_records=template_records,
    )
    layout = lower_template_ops_to_binary_layout(
        template_plan,
        requested_runnability_state="emittable_debug",
    )
    writer_report = build_template_evidence_binding_report(layout)
    relu_binding_report = bind_explicit_relu_subtasks(template_plan)
    return (
        summarize_explicit_relu_subtask_binding_report(relu_binding_report),
        summarize_template_evidence_binding_report(writer_report),
    )


def _log10max_inputs() -> tuple[dict[str, object], dict[str, object]]:
    collective_report = build_log10max_capacity_proof_report(
        build_current_log10max_plan()
    )
    summary = summarize_log10max_capacity_proof_report(collective_report)
    ring_report = build_log10max_task_local_ring_plan()
    projection_report = build_log10max_ring_fiber_projection_report(ring_report)
    route_executable = lower_fibers_to_executable_ops(
        projection_report.fibers,
        projections=projection_report.projections,
        executable_role_profile=LOG10MAX_SPEC.executable_role_profile(),
    )
    route_role_report = build_route_role_binding_report(route_executable)
    consumer_binding_report = build_log10max_globalmax_consumer_binding_report(
        ring_report,
        projection_report,
    )
    update_template_binding_report = build_log10max_ring_update_template_binding_report(
        ring_report,
        projection_report,
    )
    update_layout_candidate_report = (
        build_log10max_ring_update_binary_layout_candidate_report(
            update_template_binding_report,
        )
    )
    summary["selected_delivery_strategy"] = ring_report.strategy
    summary["selected_delivery_customer_label"] = ring_report.customer_label
    plan = collective_report.to_plan()
    plan["ring_first_delivery_plan"] = _ring_plan_with_lowering_proofs(
        ring_report.to_plan(),
        projection_runtime_ready=projection_report.runtime_ready,
        route_role_runtime_ready=route_role_report.runtime_ready,
        route_role_plan=route_role_report.to_plan(),
        consumer_binding_runtime_ready=consumer_binding_report.runtime_ready,
        consumer_binding_plan=consumer_binding_report.to_plan(),
        update_template_binding_plan=update_template_binding_report.to_plan(),
        update_layout_candidate_plan=update_layout_candidate_report.to_plan(),
    )
    return (summary, plan)


def _ring_plan_with_lowering_proofs(
    ring_plan: dict[str, object],
    *,
    projection_runtime_ready: bool,
    route_role_runtime_ready: bool,
    route_role_plan: dict[str, object],
    consumer_binding_runtime_ready: bool,
    consumer_binding_plan: dict[str, object],
    update_template_binding_plan: dict[str, object],
    update_layout_candidate_plan: dict[str, object],
) -> dict[str, object]:
    proven_route_movement = projection_runtime_ready and route_role_runtime_ready
    update_binding_summary = update_template_binding_plan.get("summary", {})
    update_binding_blockers = update_binding_summary.get("blocker_ids", ())
    update_binding_available = (
        isinstance(update_binding_blockers, list)
        and "log10max_ring_update_row_bytes_missing" in update_binding_blockers
    )
    update_layout_summary = update_layout_candidate_plan.get("summary", {})
    update_layout_blockers = update_layout_summary.get("blocker_ids", ())
    update_layout_available = (
        isinstance(update_layout_blockers, list)
        and update_layout_summary.get("row_candidate_count") == 30
        and update_layout_summary.get("row_bytes_claim") is False
        and "log10max_ring_update_row_bytes_missing" in update_layout_blockers
    )
    if proven_route_movement:
        binding = dict(ring_plan.get("route_role_binding", {}))
        binding.update(
            {
                "proof_status": "proven",
                "runtime_ready": True,
                "route_role_binding_report": route_role_plan,
            }
        )
        ring_plan["route_role_binding"] = binding
        ring_plan["route_role_bindings"] = (binding,)
        ring_plan["global_max_distribution"] = {
            "status": "proven",
            "source": "log10max_ring_fiber_projection_route_path",
        }
        ring_plan["consumer_global_max_ready_dependencies"] = {
            "status": "proven",
            "source": "FiberDependency(route_or_local_materialization)",
        }
        ring_plan["ring_edges"] = [
            {
                **edge,
                "route_template_status": "proven",
                "route_template_evidence_id": edge.get(
                    "route_template_evidence_id",
                    "dfu3500_route_forward_globalmax_role_generalization_v1",
                ),
                "update_template_status": (
                    "layout_candidate"
                    if update_layout_available
                    else "candidate_available"
                    if update_binding_available
                    else edge.get("update_template_status")
                ),
                "update_template_blocker": (
                    "log10max_ring_update_operand_placeholders_missing"
                    if update_binding_available or update_layout_available
                    else edge.get("update_template_blocker")
                ),
                "route_path_proof_status": "proven",
                "route_role_binding_status": "proven",
            }
            for edge in ring_plan.get("ring_edges", ())
            if isinstance(edge, dict)
        ]
    if proven_route_movement and consumer_binding_runtime_ready:
        ring_plan["consumer_global_max_binding"] = {
            "status": "proven",
            "source": "log10max_globalmax_consumer_binding_report",
        }
        ring_plan["symbolic_global_max_reaches_postprocess"] = False
    ring_plan["lowering_proofs"] = {
        "stream_to_fiber_projection_runtime_ready": projection_runtime_ready,
        "globalmax_route_role_runtime_ready": route_role_runtime_ready,
        "globalmax_consumer_binding_runtime_ready": (
            consumer_binding_runtime_ready
        ),
        "globalmax_consumer_binding_report": consumer_binding_plan,
        "ring_update_template_binding_report": update_template_binding_plan,
        "ring_update_binary_layout_candidate_report": update_layout_candidate_plan,
    }
    return ring_plan


def _validate_report(summary: dict[str, object], plan: dict[str, object]) -> list[str]:
    failures: list[str] = []
    if summary["final_state"] != "blocked":
        failures.append(f"pre-integration gate must be blocked, got {summary}")
    if summary["runtime_ready"] is not False:
        failures.append("runtime_ready must stay false before raw bytes close")
    if summary["uploadable"] is not False:
        failures.append("uploadable must stay false before payload files are claimed")
    if summary["payload_files_claimed"] is not True:
        failures.append("GEMM no-ReLU raw payload files should be claimed now")
    expected_operator_states = {
        "gemm_no_relu": "ready",
        "gemm_relu": "blocked",
        "log10max": "blocked",
    }
    if summary["operator_states"] != expected_operator_states:
        failures.append(
            "unexpected operator states: "
            f"expected {expected_operator_states}, got {summary['operator_states']}"
        )

    missing = set(summary["missing_blockers"])
    required_blockers = {
        "gemm_relu:relu_row_writer:relu_p0_blocker=relu_p0:template_row_evidence",
        "gemm_relu:relu_row_writer:relu_exact_hmax_rows_missing",
        (
            "log10max:ring_first_row_col_reduce_broadcast:"
            "log10max_ring_update_operand_placeholders_missing"
        ),
        (
            "log10max:ring_first_row_col_reduce_broadcast:"
            "log10max_inst_field_ownership_missing"
        ),
        (
            "log10max:ring_first_row_col_reduce_broadcast:"
            "log10max_inst_field_binding_missing"
        ),
        (
            "log10max:ring_first_row_col_reduce_broadcast:"
            "log10max_ring_update_row_body_candidate_bytes_missing"
        ),
        (
            "log10max:ring_first_row_col_reduce_broadcast:"
            "log10max_ring_update_component_integrated_bytes_missing"
        ),
        (
            "log10max:ring_first_row_col_reduce_broadcast:"
            "log10max_route_endpoint_status_missing"
        ),
        (
            "log10max:ring_first_row_col_reduce_broadcast:"
            "log10max_route_family_phase2_decision_missing"
        ),
        (
            "log10max:ring_first_row_col_reduce_broadcast:"
            "log10max_route_flow_ack_policy_missing"
        ),
        (
            "log10max:ring_first_row_col_reduce_broadcast:"
            "log10max_instruction_layout_plan_missing"
        ),
        (
            "log10max:ring_first_row_col_reduce_broadcast:"
            "log10max_exe_block_writer_plan_missing"
        ),
        (
            "log10max:ring_first_row_col_reduce_broadcast:"
            "log10max_instruction_boundary_plan_missing"
        ),
        (
            "log10max:ring_first_row_col_reduce_broadcast:"
            "log10max_component_placement_integration_missing"
        ),
        (
            "log10max:ring_first_row_col_reduce_broadcast:"
            "log10max_operator_payload_manifest_blocked"
        ),
    }
    missing_required = sorted(required_blockers - missing)
    if missing_required:
        failures.append(f"gate missing required blockers: {missing_required}")

    if plan["runtime_ready"] is not False or plan["uploadable"] is not False:
        failures.append(f"plan must remain fail-closed: {plan}")
    if "package_shells_are_never_runtime_ready" not in plan["layering_policy"]:
        failures.append("layering policy must explicitly reject package shell readiness")
    log10_statuses = [
        status
        for status in plan["operator_statuses"]
        if status["operator"] == "log10max"
    ]
    if not log10_statuses:
        failures.append("missing log10max gate status")
    else:
        log10_summary = log10_statuses[0]["summary"]
        inst_field_gate = log10_summary.get("inst_field_provenance_gate", {})
        if not isinstance(inst_field_gate, dict):
            failures.append("log10max inst field provenance gate summary missing")
        else:
            if inst_field_gate.get("accepted_rfc_phase") != (
                "phase_0_1_report_only"
            ):
                failures.append(
                    "log10max inst field gate must stay in Phase 0/1: "
                    f"{inst_field_gate}"
                )
            if inst_field_gate.get("runtime_ready_claim") is not False:
                failures.append(
                    "log10max inst field gate must not claim runtime_ready: "
                    f"{inst_field_gate}"
                )
            if inst_field_gate.get("uploadable_claim") is not False:
                failures.append(
                    "log10max inst field gate must not claim uploadable: "
                    f"{inst_field_gate}"
                )
            if (
                inst_field_gate.get("candidate_decode_roundtrip_is_uploadable")
                is not False
            ):
                failures.append(
                    "candidate row-body decode must not imply uploadable: "
                    f"{inst_field_gate}"
                )
            for blocker in (
                LOG10MAX_INST_FIELD_OWNERSHIP_MISSING,
                LOG10MAX_INST_FIELD_BINDING_MISSING,
                LOG10MAX_RING_UPDATE_ROW_BODY_CANDIDATE_BYTES_MISSING,
                LOG10MAX_RING_UPDATE_COMPONENT_INTEGRATED_BYTES_MISSING,
            ):
                if blocker not in inst_field_gate.get("missing_blockers", ()):
                    failures.append(
                        "current log10max inst field gate should expose "
                        f"blocker {blocker}: {inst_field_gate}"
                    )
        route_layout_gate = log10_summary.get("route_layout_gate", {})
        if not isinstance(route_layout_gate, dict):
            failures.append("log10max route layout gate summary missing")
        else:
            if route_layout_gate.get("accepted_rfc_phase") != (
                "phase_0_1_report_only"
            ):
                failures.append(
                    "log10max route layout gate must stay in Phase 0/1: "
                    f"{route_layout_gate}"
                )
            if route_layout_gate.get("runtime_ready_claim") is not False:
                failures.append(
                    "log10max route layout gate must not claim runtime_ready: "
                    f"{route_layout_gate}"
                )
            if route_layout_gate.get("uploadable_claim") is not False:
                failures.append(
                    "log10max route layout gate must not claim uploadable: "
                    f"{route_layout_gate}"
                )
            if (
                route_layout_gate.get("candidate_decode_roundtrip_is_uploadable")
                is not False
            ):
                failures.append(
                    "candidate route decode must not imply uploadable: "
                    f"{route_layout_gate}"
                )
            if route_layout_gate.get("route_family_pending_is_selected") is not False:
                failures.append(
                    "pending route family must not count as selected: "
                    f"{route_layout_gate}"
                )
            if (
                route_layout_gate.get(
                    "component_integrated_required_for_runtime_ready"
                )
                is not True
            ):
                failures.append(
                    "component placement must require component_integrated: "
                    f"{route_layout_gate}"
                )
            for blocker in (
                LOG10MAX_ROUTE_ENDPOINT_STATUS_MISSING,
                LOG10MAX_ROUTE_FAMILY_PHASE2_DECISION_MISSING,
                LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING,
                LOG10MAX_INSTRUCTION_LAYOUT_PLAN_MISSING,
                LOG10MAX_EXE_BLOCK_WRITER_PLAN_MISSING,
                LOG10MAX_INSTRUCTION_BOUNDARY_PLAN_MISSING,
                LOG10MAX_COMPONENT_PLACEMENT_INTEGRATION_MISSING,
            ):
                if blocker not in route_layout_gate.get("missing_blockers", ()):
                    failures.append(
                        "current log10max route layout gate should expose "
                        f"blocker {blocker}: {route_layout_gate}"
                    )
        operator_payload_gate = log10_summary.get("operator_payload_gate", {})
        if not isinstance(operator_payload_gate, dict):
            failures.append("log10max operator payload gate summary missing")
        else:
            if operator_payload_gate.get("accepted_rfc_phase") != (
                "phase_5_report_only"
            ):
                failures.append(
                    "log10max operator payload gate must stay report-only: "
                    f"{operator_payload_gate}"
                )
            if operator_payload_gate.get("readiness_claim") != "blocked":
                failures.append(
                    "log10max operator payload gate must remain blocked: "
                    f"{operator_payload_gate}"
                )
            if operator_payload_gate.get("runtime_ready_claim") is not False:
                failures.append(
                    "log10max operator payload gate must not claim runtime_ready: "
                    f"{operator_payload_gate}"
                )
            if operator_payload_gate.get("uploadable_claim") is not False:
                failures.append(
                    "log10max operator payload gate must not claim uploadable: "
                    f"{operator_payload_gate}"
                )
            if operator_payload_gate.get("component_hashes") != {}:
                failures.append(
                    "partial diagnostic hashes must not become component hashes: "
                    f"{operator_payload_gate}"
                )
            if LOG10MAX_OPERATOR_PAYLOAD_MANIFEST_BLOCKED not in (
                operator_payload_gate.get("missing_blockers", ())
            ):
                failures.append(
                    "operator payload gate should expose manifest blocker: "
                    f"{operator_payload_gate}"
                )
    gemm_statuses = [
        status
        for status in plan["operator_statuses"]
        if status["operator"] == "gemm_no_relu"
    ]
    if not gemm_statuses:
        failures.append("missing GEMM gate status")
    else:
        gemm_summary = gemm_statuses[0]["summary"]
        if gemm_summary.get("bytes_emitted") is not True:
            failures.append(f"GEMM raw bytes should be present now: {gemm_summary}")
        if gemm_summary.get("byte_materializer_status_counts") != {
            "raw_inst_t_row_bytes_available": 128
        }:
            failures.append(
                "unexpected GEMM byte materializer status: "
                f"{gemm_summary.get('byte_materializer_status_counts')}"
            )
        payload_component = gemm_summary.get("payload_component", {})
        if not isinstance(payload_component, dict):
            failures.append("GEMM payload component summary missing")
        else:
            if payload_component.get("state") != "raw_inst_t_payload_candidate":
                failures.append(
                    "GEMM payload component should expose raw inst_t candidate: "
                    f"{payload_component}"
                )
            if payload_component.get("raw_inst_t_file_size") != 11206656:
                failures.append(
                    "unexpected GEMM raw inst_t payload size: "
                    f"{payload_component.get('raw_inst_t_file_size')}"
                )
            if not payload_component.get("raw_inst_t_file_sha256"):
                failures.append("GEMM raw inst_t payload sha256 must be present")
            component_blockers = set(payload_component.get("blockers", ()))
            for blocker in (
                (
                    "final_cbuf_file_not_assembled:"
                    "debug_only_sections=exeblock_conf_info"
                ),
                (
                    "final_micc_file_not_assembled:"
                    "debug_only_sections=tasks_conf_info,subtasks_conf_info"
                ),
                "runtime_assets_not_emitted",
                "delivery_candidate_gate_not_run",
            ):
                if blocker not in component_blockers:
                    failures.append(
                        f"GEMM payload component must keep blocker {blocker}"
                    )
            if payload_component.get("cbuf_inst_section_candidate_present") is not True:
                failures.append(
                    "GEMM CBUF insts section candidate should be present: "
                    f"{payload_component}"
                )
            if payload_component.get("final_cbuf_candidate_present") is not False:
                failures.append("GEMM final CBUF candidate must remain false")
            if payload_component.get("final_micc_candidate_present") is not False:
                failures.append("GEMM final MICC candidate must remain false")
            if payload_component.get("cbuf_inst_section_file_size") != 11206656:
                failures.append(
                    "unexpected CBUF insts section candidate size: "
                    f"{payload_component.get('cbuf_inst_section_file_size')}"
                )
            if (
                payload_component.get("cbuf_inst_section_file_sha256")
                != payload_component.get("raw_inst_t_file_sha256")
            ):
                failures.append(
                    "CBUF insts section candidate hash must match raw inst rows"
                )
            if payload_component.get("cbuf_section_statuses") != {
                "insts": "candidate_available",
                "exeblock_conf_info": "section_candidate_available",
                "instance_conf_info": "candidate_available",
            }:
                failures.append(
                    "unexpected CBUF section statuses: "
                    f"{payload_component.get('cbuf_section_statuses')}"
                )
            if payload_component.get("cbuf_section_finalization_statuses") != {
                "insts": "final_section_candidate_available",
                "exeblock_conf_info": "blocked_debug_only_candidate",
                "instance_conf_info": "final_empty_section_candidate_available",
            }:
                failures.append(
                    "unexpected CBUF finalization statuses: "
                    f"{payload_component.get('cbuf_section_finalization_statuses')}"
                )
            cbuf_proofs = payload_component.get("cbuf_section_proof_summaries", {})
            instance_proof = cbuf_proofs.get("instance_conf_info", {})
            if instance_proof.get("status") != (
                "empty_instance_section_consistent_with_zero_instance_control"
            ):
                failures.append(
                    "GEMM instance_conf_info must prove empty section via "
                    f"zero_instance_control: {instance_proof}"
                )
            if instance_proof.get("zero_instance_subtask_row_count") != 8:
                failures.append(
                    "GEMM instance_conf_info zero-instance proof should cover "
                    f"eight selected subtask rows: {instance_proof}"
                )
            exeblock_proof = cbuf_proofs.get("exeblock_conf_info", {})
            if exeblock_proof.get("inst_mem_based_addr_status") != (
                "candidate_byte_offsets_aligned_to_inst_t"
            ):
                failures.append(
                    "GEMM exeBlock_conf_info must narrow inst_mem_based_addr "
                    f"to aligned byte offsets: {exeblock_proof}"
                )
            if exeblock_proof.get("payload_row_count") != 128:
                failures.append(
                    "GEMM exeBlock_conf_info proof should cover 128 rows: "
                    f"{exeblock_proof}"
                )
            if exeblock_proof.get("decode_roundtrip_status") != (
                "decoded_roundtrip_available"
            ):
                failures.append(
                    "GEMM exeBlock_conf_info bytes should decode back to "
                    f"writer records: {exeblock_proof}"
                )
            if exeblock_proof.get("decoded_row_count") != 128:
                failures.append(
                    "GEMM exeBlock_conf_info decode proof should cover 128 "
                    f"rows: {exeblock_proof}"
                )
            if exeblock_proof.get("inst_mem_based_addr_decode_roundtrip_status") != (
                "decoded_field_matches_writer_records"
            ):
                failures.append(
                    "GEMM exeBlock_conf_info inst_mem_based_addr should "
                    f"roundtrip through bytes: {exeblock_proof}"
                )
            if (
                exeblock_proof.get("inst_mem_based_addr_decoded_distinct_values")
                != exeblock_proof.get("inst_mem_based_addr_distinct_values")
            ):
                failures.append(
                    "GEMM exeBlock_conf_info decoded inst_mem_based_addr values "
                    f"must match writer records: {exeblock_proof}"
                )
            if exeblock_proof.get("section_offset_decode_roundtrip_status") != (
                "candidate_section_offsets_decode_roundtrip_available"
            ):
                failures.append(
                    "GEMM CBUF section offsets should have candidate decode "
                    f"roundtrip proof: {exeblock_proof}"
                )
            if exeblock_proof.get("final_field_encoder_status") != (
                "blocked_source_field_provenance_missing"
            ):
                failures.append(
                    "GEMM exeBlock_conf_info final encoder should be narrowed "
                    "to source-field provenance, not runtime-ready: "
                    f"{exeblock_proof}"
                )
            expected_missing_fields = [
                "valid",
                "priority",
                "instances_amount",
                "block_class",
            ]
            if exeblock_proof.get("final_field_encoder_missing_source_fields") != (
                expected_missing_fields
            ):
                failures.append(
                    "GEMM exeBlock_conf_info final encoder must name missing "
                    "source-provenance fields: "
                    f"{exeblock_proof}"
                )
            if exeblock_proof.get("endpoint_slots_status") != (
                "decoded_endpoint_slots_match_source_records"
            ):
                failures.append(
                    "GEMM exeBlock_conf_info endpoint slots should roundtrip "
                    f"against source records: {exeblock_proof}"
                )
            if exeblock_proof.get("endpoint_slots_source_roundtrip_claim") is not True:
                failures.append(
                    "GEMM exeBlock_conf_info endpoint proof should claim only "
                    f"source-record roundtrip, not final runtime: {exeblock_proof}"
                )
            if exeblock_proof.get("endpoint_slots_missing_source_fields") != []:
                failures.append(
                    "GEMM exeBlock_conf_info endpoint proof should have no "
                    f"missing source endpoint records: {exeblock_proof}"
                )
            cbuf_requirements = payload_component.get(
                "cbuf_section_finalization_requirements",
                {},
            )
            instance_requirements = set(cbuf_requirements.get("instance_conf_info", ()))
            if instance_requirements:
                failures.append(
                    "GEMM instance_conf_info should be closed by zero-instance "
                    f"control, got requirements {sorted(instance_requirements)}"
                )
            exeblock_requirements = set(cbuf_requirements.get("exeblock_conf_info", ()))
            for requirement in (
                "exeBlock_conf_info_t_source_field_provenance",
            ):
                if requirement not in exeblock_requirements:
                    failures.append(
                        "GEMM exeBlock_conf_info must expose finalization "
                        f"requirement {requirement}"
                    )
            for closed_requirement in (
                "inst_mem_based_addr_decode_roundtrip_proof",
                "final_cbuf_section_offset_decode_roundtrip",
            ):
                if closed_requirement in exeblock_requirements:
                    failures.append(
                        "GEMM exeBlock_conf_info decode proof should be closed: "
                        f"{closed_requirement}"
                    )
            if payload_component.get("micc_section_statuses") != {
                "tasks_conf_info": "section_candidate_available",
                "subtasks_conf_info": "section_candidate_available",
            }:
                failures.append(
                    "unexpected MICC section statuses: "
                    f"{payload_component.get('micc_section_statuses')}"
                )
            if (
                payload_component.get("micc_final_candidate_status")
                != "decoded_wait_leaf_policy_available_runtime_trace_missing"
            ):
                failures.append(
                    "GEMM MICC final candidate status must expose proof gap: "
                    f"{payload_component.get('micc_final_candidate_status')}"
                )
            if payload_component.get("micc_final_section_statuses") != {
                "tasks_conf_info": (
                    "decoded_roundtrip_available_runtime_trace_missing"
                ),
                "subtasks_conf_info": (
                    "decoded_roundtrip_available_runtime_trace_missing"
                ),
                "exeblock_conf_info": (
                    "decoded_roundtrip_available_runtime_trace_missing"
                ),
            }:
                failures.append(
                    "unexpected GEMM MICC final section statuses: "
                    f"{payload_component.get('micc_final_section_statuses')}"
                )
            if (
                payload_component.get("micc_final_runtime_order_status")
                != "decoded_wait_leaf_policy_available_runtime_trace_missing"
            ):
                failures.append(
                    "GEMM MICC runtime order must remain trace-blocked: "
                    f"{payload_component.get('micc_final_runtime_order_status')}"
                )
            micc_final_blockers = set(
                payload_component.get("micc_final_blockers", ())
            )
            for closed_blocker in (
                "decoded_task_conf_info_roundtrip_missing",
                "decoded_sub_task_conf_info_roundtrip_missing",
                "decoded_exeBlock_conf_info_roundtrip_missing",
                "runtime_order_decoded_roundtrip_missing",
                "task_active_subtask_order_proof_missing",
                "task_start_end_runtime_policy_unproven",
                "subtask_successor_order_proof_missing",
                "embedded_exeblock_roundtrip_missing",
                "instance_table_address_roundtrip_missing",
                "exeBlock_instruction_range_roundtrip_missing",
                "exeBlock_wait_or_dependency_flags_unproven",
                "exeBlock_is_leaf_policy_unproven",
            ):
                if closed_blocker in micc_final_blockers:
                    failures.append(
                        f"GEMM MICC decoded blocker should be closed: {closed_blocker}"
                    )
            if "runtime_start_wait_trace_missing" not in micc_final_blockers:
                failures.append(
                    "GEMM MICC final blocker missing runtime trace: "
                    f"{payload_component.get('micc_final_blockers')}"
                )
            if micc_final_blockers != {"runtime_start_wait_trace_missing"}:
                failures.append(
                    "GEMM MICC final blockers should be narrowed to runtime trace "
                    f"gaps: {payload_component.get('micc_final_blockers')}"
                )
            if payload_component.get("payload_file_count") != 6:
                failures.append(
                    "GEMM payload component should expose six candidate files: "
                    f"{payload_component.get('payload_file_count')}"
                )

    placeholder_report = build_runtime_ready_preintegration_report(
        gemm_materialization_summary={},
        gemm_selector_summary={},
        relu_binding_summary={},
        relu_writer_summary={},
        log10max_collective_summary={},
        log10max_collective_plan={},
        payload_files_claimed=True,
        placeholder_files_present=True,
    )
    if placeholder_report.runtime_ready or placeholder_report.uploadable:
        failures.append("placeholder pre-integration report must fail closed")
    if "placeholder_files_present" not in placeholder_report.missing_blockers:
        failures.append("placeholder blocker must be explicit")

    return failures


if __name__ == "__main__":
    main()
