from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "compiler"))

from gpdpu_compiler.core.stream_compiler.operator_payload_assembly import (  # noqa: E402
    LOG10MAX_RING_FIRST_BLOCKERS,
    build_runtime_ready_preintegration_report,
)


def test_log10max_ring_first_gate_reports_delivery_blocker_names() -> None:
    report = build_runtime_ready_preintegration_report(
        gemm_materialization_summary={},
        gemm_selector_summary={},
        relu_binding_summary={},
        relu_writer_summary={},
        log10max_collective_summary={},
        log10max_collective_plan={},
        payload_files_claimed=True,
    )

    log10_status = _operator_status(report, "log10max")

    assert log10_status["gate_id"] == "ring_first_row_col_reduce_broadcast"
    expected_blockers = set(LOG10MAX_RING_FIRST_BLOCKERS)
    expected_blockers.remove("log10max_ring_update_row_bytes_missing")
    expected_blockers.remove("log10max_ring_update_inst_operand_patch_missing")
    expected_blockers.remove("log10max_ring_update_operand_allocation_missing")
    expected_blockers.remove("log10max_ring_update_operand_placeholders_missing")
    assert expected_blockers.issubset(set(log10_status["missing_blockers"]))
    assert report.runtime_ready is False


def test_log10max_ring_first_gate_accepts_concrete_ring_metadata() -> None:
    report = build_runtime_ready_preintegration_report(
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
        log10max_collective_plan={
            "ring_first_delivery_plan": {
                "collective_strategy": "ring_spmd_row_then_col",
                "customer_collective_label": "spmd_ring_materialized_reduce",
                "task_axis": 1,
                "runtime_ordering_domain": "single_task_group",
                "cross_task_visibility_claim": False,
                "representative_selection": {"status": "proven"},
                "route_role_bindings": (
                    {
                        "role": "GlobalMax",
                        "proof_status": "proven",
                        "template_evidence_id": "operand_route_push_recv",
                    },
                ),
                "ring_edges": (
                    {
                        "edge_id": "row_reduce:r0:c1_to_c0",
                        "template_evidence_id": "operand_route_push_recv",
                        "template_status": "proven",
                        "route_path_proof_status": "proven",
                    },
                ),
                "phase_order": {"status": "proven"},
                "global_max_distribution": {"status": "proven"},
                "consumer_global_max_binding": {"status": "proven"},
                "consumer_global_max_ready_dependencies": {"status": "proven"},
                "capacity": {"status": "fits"},
                "dtype_update_op": {"status": "consistent"},
                "symbolic_global_max_reaches_postprocess": False,
            }
        },
        payload_files_claimed=True,
    )

    log10_status = _operator_status(report, "log10max")

    assert log10_status["state"] == "ready"
    assert log10_status["missing_blockers"] == []
    assert log10_status["summary"]["selected_delivery_strategy"] == (
        "ring_spmd_row_then_col"
    )
    assert report.runtime_ready is True


def test_log10max_ring_first_gate_keeps_layout_candidate_blocked_on_placeholders() -> None:
    report = build_runtime_ready_preintegration_report(
        gemm_materialization_summary={},
        gemm_selector_summary={},
        relu_binding_summary={},
        relu_writer_summary={},
        log10max_collective_summary={
            "selected_delivery_strategy": "ring_spmd_row_then_col",
            "selected_delivery_customer_label": "spmd_ring_materialized_reduce",
        },
        log10max_collective_plan={
            "ring_first_delivery_plan": {
                "collective_strategy": "ring_spmd_row_then_col",
                "customer_collective_label": "spmd_ring_materialized_reduce",
                "task_axis": 1,
                "runtime_ordering_domain": "single_task_group",
                "cross_task_visibility_claim": False,
                "representative_selection": {"status": "proven"},
                "route_role_bindings": (
                    {
                        "role": "GlobalMax",
                        "proof_status": "proven",
                        "template_evidence_id": "operand_route_push_recv",
                    },
                ),
                "ring_edges": (
                    {
                        "edge_id": "row_reduce:r0:c1_to_c0",
                        "template_evidence_id": "operand_route_push_recv",
                        "route_template_evidence_id": "operand_route_push_recv",
                        "route_template_status": "proven",
                        "update_template_status": "layout_candidate",
                        "route_path_proof_status": "proven",
                    },
                ),
                "phase_order": {"status": "proven"},
                "global_max_distribution": {"status": "proven"},
                "consumer_global_max_binding": {"status": "proven"},
                "consumer_global_max_ready_dependencies": {"status": "proven"},
                "capacity": {"status": "fits"},
                "dtype_update_op": {"status": "consistent"},
                "symbolic_global_max_reaches_postprocess": False,
            }
        },
        payload_files_claimed=True,
    )

    log10_status = _operator_status(report, "log10max")

    assert log10_status["state"] == "blocked"
    assert log10_status["missing_blockers"] == [
        "log10max_ring_update_operand_placeholders_missing"
    ]
    assert report.runtime_ready is False


def _operator_status(report, operator: str) -> dict[str, object]:
    for status in report.to_plan()["operator_statuses"]:
        if status["operator"] == operator:
            return status
    raise AssertionError(f"missing operator status: {operator}")
