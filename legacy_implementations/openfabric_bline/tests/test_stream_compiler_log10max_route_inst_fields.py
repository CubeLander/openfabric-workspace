from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "compiler"))

from gpdpu_compiler.core.stream_compiler.log10max_route_inst_fields import (  # noqa: E402
    EXPECTED_PHYSICAL_PHASE_COUNTS,
    LANE_STRIDE_OPERANDS,
    PHYSICAL_ROWS_PER_LOGICAL_EDGE,
    ROUTE_FLOW_ACK_BLOCKER,
    build_log10max_route_inst_field_binding_report,
    build_log10max_route_inst_operand_patch_report,
    build_log10max_route_physical_row_plan_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_route_row_bytes import (  # noqa: E402
    ROUTE_CANDIDATE_COMPONENT_STATUS,
    ROUTE_CANDIDATE_DECODE_STATUS,
    ROUTE_CANDIDATE_PLACEMENT_STATUS,
    build_log10max_route_inst_row_byte_candidate_report,
)


def test_route_physical_row_plan_expands_copyt_lanes_without_final_claim() -> None:
    report = build_log10max_route_physical_row_plan_report()
    summary = report.summary()

    assert summary["logical_route_edge_count"] == 30
    assert summary["physical_row_plan_count"] == 30 * PHYSICAL_ROWS_PER_LOGICAL_EDGE
    assert summary["phase_counts"] == EXPECTED_PHYSICAL_PHASE_COUNTS
    assert summary["route_family_status"] == "selected_candidate"
    assert summary["final_component_claim"] is False
    assert summary["runtime_ready"] is False
    assert summary["uploadable"] is False


def test_route_inst_operand_patch_lane_continuity_and_no_serializer_alloc() -> None:
    physical_report = build_log10max_route_physical_row_plan_report()
    patch_report = build_log10max_route_inst_operand_patch_report(physical_report)
    plans = {plan.physical_row_plan_id: plan for plan in physical_report.plans}

    assert patch_report.summary()["patch_count"] == 120
    assert patch_report.summary()["serializer_allocation_claim_count"] == 0
    assert patch_report.summary()["final_component_claim_count"] == 0

    for patch in patch_report.patches:
        plan = plans[patch.physical_row_plan_id]
        assert patch.src_operands_idx[0] == (
            plan.src_operand_idx_before_lane_delta
            + patch.lane_index * LANE_STRIDE_OPERANDS
        )
        assert patch.dst_operands_idx[0] == (
            plan.dst_operand_idx_before_lane_delta
            + patch.lane_index * LANE_STRIDE_OPERANDS
        )
        assert patch.src_operands_idx[1:] == (0, 0)
        assert patch.dst_operands_idx[1:] == (0, 0)
        assert patch.serializer_allocation_claim is False
        assert patch.final_component_claim is False
        assert patch.runtime_ready is False


def test_route_inst_field_binding_names_flow_ack_and_placement_blockers() -> None:
    report = build_log10max_route_inst_field_binding_report()
    summary = report.summary()

    assert summary["record_count"] == 120
    assert summary["phase_counts"] == EXPECTED_PHYSICAL_PHASE_COUNTS
    assert summary["binding_status_counts"] == {"blocked": 120}
    assert summary["missing_field_counts"]["flow_ack"] == 120
    assert summary["missing_field_counts"]["component_byte_offset"] == 120
    assert "dst_blocks_idx[0]" not in summary["missing_field_counts"]
    assert "local_pc" not in summary["missing_field_counts"]
    assert ROUTE_FLOW_ACK_BLOCKER in summary["blocker_ids"]
    assert summary["final_component_claim_count"] == 0
    assert summary["runtime_ready"] is False
    assert summary["uploadable"] is False

    for record in report.records:
        statuses = dict(record.field_owner_status)
        assert statuses["flow_ack"] == "blocked"
        assert statuses["dst_blocks_idx[0]"] == "bound"
        assert statuses["local_pc"] == "bound"
        assert statuses["src_operands_idx[1]"] == "zero_with_evidence"
        assert statuses["src_operands_idx[2]"] == "zero_with_evidence"
        assert statuses["dst_operands_idx[1]"] == "zero_with_evidence"
        assert statuses["dst_operands_idx[2]"] == "zero_with_evidence"
        assert record.final_component_claim is False
        assert record.runtime_ready is False


def test_route_candidate_bytes_decode_but_stay_out_of_components() -> None:
    report = build_log10max_route_inst_row_byte_candidate_report()
    summary = report.summary()

    assert summary["candidate_count"] == 120
    assert summary["logical_route_edge_count"] == 30
    assert summary["phase_counts"] == EXPECTED_PHYSICAL_PHASE_COUNTS
    assert summary["lane_counts"] == {"0": 30, "1": 30, "2": 30, "3": 30}
    assert summary["flow_ack_counts"] == {"0": 90, "1": 30}
    assert summary["flow_ack_one_phase_counts"] == {
        "col_broadcast": 3,
        "col_reduce": 3,
        "row_broadcast": 12,
        "row_reduce": 12,
    }
    assert summary["decode_roundtrip_status_counts"] == {
        ROUTE_CANDIDATE_DECODE_STATUS: 120
    }
    assert summary["placement_status_counts"] == {
        ROUTE_CANDIDATE_PLACEMENT_STATUS: 120
    }
    assert summary["component_integration_status_counts"] == {
        ROUTE_CANDIDATE_COMPONENT_STATUS: 120
    }
    assert summary["final_component_claim_count"] == 0
    assert summary["runtime_ready_claim_count"] == 0
    assert summary["uploadable_claim_count"] == 0
    assert summary["payload_manifest_claim_count"] == 0
    assert summary["shadow_component_claim_count"] == 0
    assert report.runtime_ready is False
    assert report.uploadable is False

    rows_by_edge: dict[str, list[int]] = {}
    for candidate in report.candidates:
        rows_by_edge.setdefault(candidate.logical_route_edge_id, []).append(
            candidate.physical_lane_index
        )
        decoded = candidate.decoded_fields
        owners = candidate.decoded_field_owner_ids
        statuses = candidate.decoded_field_owner_status
        expected_flow_ack = 1 if candidate.physical_lane_index == 3 else 0

        assert decoded["flow_ack"] == expected_flow_ack
        assert statuses["flow_ack"] == "candidate_bound"
        assert owners["flow_ack"] != owners["end_inst"]
        assert candidate.placement["placement_status"] == "unplaced_candidate"
        assert candidate.placement["component_byte_offset"] is None
        assert candidate.component_byte_offset is None
        assert candidate.final_component_claim is False
        assert candidate.runtime_ready is False
        assert candidate.uploadable is False
        assert candidate.payload_manifest_claim is False
        assert candidate.shadow_component_claim is False

    assert len(rows_by_edge) == 30
    assert all(sorted(lanes) == [0, 1, 2, 3] for lanes in rows_by_edge.values())
