#!/usr/bin/env python3
"""Check split route/update template evidence for log10max ring edges."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.log10max_ring_plan import (
    build_log10max_task_local_ring_plan,
)
from gpdpu_compiler.core.stream_compiler.operator_payload_assembly import (
    build_runtime_ready_preintegration_report,
)


def main() -> None:
    failures: list[str] = []
    report = build_log10max_task_local_ring_plan(
        route_role_proof_status="proven",
        route_template_status="proven",
        route_path_proof_status="proven",
        update_template_status="unresolved",
    )
    plan = report.to_plan()
    edges = plan["ring_edges"]
    if not edges:
        failures.append("ring plan must expose edge metadata")
    for edge in edges:
        if edge["route_template_status"] != "proven":
            failures.append(f"route template should be proven: {edge}")
        if edge["route_path_proof_status"] != "proven":
            failures.append(f"route path should be proven: {edge}")
        if edge["update_template_status"] != "unresolved":
            failures.append(f"update template should stay unresolved: {edge}")
        if edge["template_status"] == "proven":
            failures.append(f"aggregate template status must wait for update: {edge}")

    gate = build_runtime_ready_preintegration_report(
        gemm_materialization_summary={
            "bytes_emitted": True,
            "raw_overlay_consumable_count": 0,
            "missing_byte_materializer_input_counts": {},
            "raw_inst_t_byte_count": 128,
        },
        gemm_selector_summary={"bytes_emitted": False},
        gemm_payload_component_summary={
            "raw_inst_t_payload_present": True,
            "payload_files_claimed": True,
            "raw_inst_t_file_size": 128,
        },
        relu_binding_summary={
            "binding_status": "ready",
            "p0_blocker_ids": (),
        },
        relu_writer_summary={
            "binding_status": "ready",
            "role_opcode_candidate_raw_row_counts": {
                "tile_op:relu|HMAX": {"single_candidate_row_count": 64}
            },
            "missing_raw_template_bytes_count": 0,
        },
        log10max_collective_summary={
            "selected_delivery_strategy": "ring_spmd_row_then_col",
            "selected_delivery_customer_label": "spmd_ring_materialized_reduce",
        },
        log10max_collective_plan={"ring_first_delivery_plan": plan},
        payload_files_claimed=True,
    )
    log10_status = _operator_status(gate.to_plan(), "log10max")
    blockers = set(log10_status["missing_blockers"])
    if "ring_edge_route_template_missing" in blockers:
        failures.append(f"route template blocker should be cleared: {blockers}")
    if "route_path_proof_missing" in blockers:
        failures.append(f"route path blocker should be cleared: {blockers}")
    if "route_role_globalmax_unproven" in blockers:
        failures.append(f"route role blocker should be cleared: {blockers}")
    if "ring_edge_update_template_missing" not in blockers:
        failures.append(f"update template blocker must remain precise: {blockers}")
    if "ring_edge_template_missing" in blockers:
        failures.append(f"aggregate template blocker should be split away: {blockers}")
    if "consumer_global_max_binding_missing" not in blockers:
        failures.append(f"consumer binding must wait for update template: {blockers}")
    if "symbolic_global_max_reaches_postprocess" not in blockers:
        failures.append(f"postprocess must stay fail-closed: {blockers}")

    if failures:
        print("stream compiler log10max ring template evidence check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max ring template evidence check OK")


def _operator_status(plan: dict[str, object], operator: str) -> dict[str, object]:
    statuses = plan["operator_statuses"]
    assert isinstance(statuses, list)
    for status in statuses:
        assert isinstance(status, dict)
        if status["operator"] == operator:
            return status
    raise AssertionError(f"missing operator status: {operator}")


if __name__ == "__main__":
    main()
