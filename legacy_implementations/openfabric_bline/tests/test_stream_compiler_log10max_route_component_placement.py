from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "compiler"))

from gpdpu_compiler.core.program_bin import MAX_INST_AMOUNT_PER_PE  # noqa: E402
from gpdpu_compiler.core.program_legacy_inst import INST_RECORD_SIZE_BYTES  # noqa: E402
from gpdpu_compiler.core.stream_compiler.log10max_route_component_placement import (  # noqa: E402
    LOG10MAX_OPERATOR_MANIFEST_MISSING,
    LOG10MAX_OPERATOR_RUNTIME_READY_GATE_NOT_AGGREGATED,
    LOG10MAX_ROUTE_COMPONENT_OVERWRITE_CHECK_SCOPED,
    LOG10MAX_ROUTE_FULL_LAYOUT_EPOCH_NOT_FROZEN,
    ROUTE_COMPONENT_CANDIDATE_INTEGRATION_STATUS,
    ROUTE_COMPONENT_INTEGRATION_STATUS,
    ROUTE_COMPONENT_NAME,
    ROUTE_COMPONENT_PLACEMENT_STATUS,
    ROUTE_LAYOUT_EPOCH,
    ROUTE_RESERVED_ROW_POLICY_ID,
    build_log10max_route_component_integration_report,
    build_log10max_route_component_placement_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_route_row_bytes import (  # noqa: E402
    LOG10MAX_ROUTE_COMPONENT_INTEGRATION_MISSING,
)


EXPECTED_PHASE_COUNTS = {
    "col_broadcast": 12,
    "col_reduce": 12,
    "row_broadcast": 48,
    "row_reduce": 48,
}


def test_route_component_placement_report_is_route_scoped_only() -> None:
    report = build_log10max_route_component_placement_report()
    summary = report.summary()

    assert summary["placement_count"] == 120
    assert summary["lane_group_completion_count"] == 30
    assert summary["phase_counts"] == EXPECTED_PHASE_COUNTS
    assert summary["placement_status_counts"] == {ROUTE_COMPONENT_PLACEMENT_STATUS: 120}
    assert summary["component_integration_status_counts"] == {
        ROUTE_COMPONENT_INTEGRATION_STATUS: 120
    }
    assert summary["micc_coherence_status_counts"] == {"not_integrated": 120}
    assert summary["payload_manifest_status_counts"] == {
        "route_candidate_manifest_bound": 120
    }
    assert summary["lane_group_completion_status_counts"] == {"bound": 30}
    assert summary["duplicate_component_byte_offset_count"] == 0
    assert summary["overwritten_row_count"] == 0
    assert summary["runtime_ready_claim_count"] == 0
    assert summary["uploadable_claim_count"] == 0
    assert summary["layout_epoch"] == ROUTE_LAYOUT_EPOCH
    assert summary["layout_plan_sha256"]
    assert summary["inst_per_pe"] == MAX_INST_AMOUNT_PER_PE
    assert LOG10MAX_ROUTE_COMPONENT_INTEGRATION_MISSING in summary["blocker_ids"]
    assert LOG10MAX_ROUTE_FULL_LAYOUT_EPOCH_NOT_FROZEN in summary["blocker_ids"]
    assert LOG10MAX_ROUTE_COMPONENT_OVERWRITE_CHECK_SCOPED in summary["blocker_ids"]
    assert report.runtime_ready is False
    assert report.uploadable is False
    assert report.route_component_integrated_claim is False
    assert report.to_plan()["payload_manifest_entries"] == []


def test_route_component_placement_offsets_follow_pe_major_layout() -> None:
    report = build_log10max_route_component_placement_report()
    seen_offsets: set[int] = set()
    local_pcs_by_pe: dict[str, set[int]] = {}

    for placement in report.placements:
        assert placement.component_name == ROUTE_COMPONENT_NAME
        assert placement.record_size_bytes == INST_RECORD_SIZE_BYTES
        assert placement.layout_epoch == ROUTE_LAYOUT_EPOCH
        assert placement.reserved_row_policy_id == ROUTE_RESERVED_ROW_POLICY_ID
        assert placement.overwrite_policy == "reserved_slot_only"
        assert placement.overwritten_row_ids == ()
        assert placement.placement_status == "placed_candidate"
        assert placement.component_integration_scope == "route_rows_only"
        assert placement.component_integration_status == "not_integrated"
        assert placement.micc_coherence_scope == "route_rows_only"
        assert placement.micc_coherence_status == "not_integrated"
        assert placement.payload_manifest_status == "route_candidate_manifest_bound"
        assert placement.runtime_ready is False
        assert placement.uploadable is False
        assert placement.blocker_ids == (
            LOG10MAX_ROUTE_FULL_LAYOUT_EPOCH_NOT_FROZEN,
            LOG10MAX_ROUTE_COMPONENT_OVERWRITE_CHECK_SCOPED,
            LOG10MAX_ROUTE_COMPONENT_INTEGRATION_MISSING,
        )

        assert 0 <= placement.pe_local_pc < MAX_INST_AMOUNT_PER_PE
        expected_row_index = (
            placement.pe_index * MAX_INST_AMOUNT_PER_PE + placement.pe_local_pc
        )
        assert placement.component_row_index == expected_row_index
        assert placement.component_byte_offset == (
            expected_row_index * INST_RECORD_SIZE_BYTES
        )
        assert placement.component_byte_offset not in seen_offsets
        seen_offsets.add(placement.component_byte_offset)
        local_pcs_by_pe.setdefault(placement.source_pe, set()).add(
            placement.pe_local_pc
        )

    assert len(seen_offsets) == 120
    for pe, local_pcs in local_pcs_by_pe.items():
        assert len(local_pcs) > 0, pe


def test_route_lane_group_completion_uses_last_lane_ready_token() -> None:
    report = build_log10max_route_component_placement_report()
    completions = {item.logical_route_edge_id: item for item in report.lane_group_completions}

    assert len(completions) == 30
    for edge_id, completion in completions.items():
        assert completion.logical_route_edge_id == edge_id
        assert completion.lane_count == 4
        assert completion.completion_lane_index == 3
        assert completion.completion_flow_ack_value == 1
        assert completion.completion_status == "bound"
        assert completion.blocker_ids == ()
        assert completion.receiver_ready_value_id == f"globalmax_route_ready:{edge_id}"
        assert len(completion.physical_row_ids) == 4
        assert len(completion.physical_candidate_ids) == 4


def test_route_component_integration_is_route_slice_only() -> None:
    report = build_log10max_route_component_integration_report()
    summary = report.summary()

    assert summary["integration_count"] == 120
    assert summary["route_slice_row_count"] == 120
    assert summary["phase_counts"] == EXPECTED_PHASE_COUNTS
    assert summary["integration_status_counts"] == {
        ROUTE_COMPONENT_CANDIDATE_INTEGRATION_STATUS: 120
    }
    assert summary["micc_coherence_status_counts"] == {
        "route_slice_candidate_coherent": 120
    }
    assert summary["payload_manifest_status_counts"] == {
        "route_candidate_manifest_bound": 120
    }
    assert summary["duplicate_component_byte_offset_count"] == 0
    assert summary["overwritten_row_count"] == 0
    assert summary["operator_manifest_bound_count"] == 0
    assert summary["runtime_ready_claim_count"] == 0
    assert summary["uploadable_claim_count"] == 0
    assert summary["raw_inst_t_byte_count"] == 120 * INST_RECORD_SIZE_BYTES
    assert summary["component_integration_scope"] == "route_rows_only"
    assert summary["route_component_integrated_claim"] is True
    assert summary["runtime_ready"] is False
    assert summary["uploadable"] is False
    assert summary["route_slice_sha256"]
    assert LOG10MAX_OPERATOR_MANIFEST_MISSING in summary["blocker_ids"]
    assert (
        LOG10MAX_OPERATOR_RUNTIME_READY_GATE_NOT_AGGREGATED
        in summary["blocker_ids"]
    )
    assert LOG10MAX_ROUTE_COMPONENT_INTEGRATION_MISSING not in summary["blocker_ids"]
    assert report.to_plan()["operator_payload_manifest_entries"] == []


def test_route_component_integration_copies_candidate_bytes() -> None:
    report = build_log10max_route_component_integration_report()
    offsets: set[int] = set()

    for record in report.integration_records:
        assert record.component_name == ROUTE_COMPONENT_NAME
        assert record.integration_scope == "route_rows_only"
        assert record.integration_status == ROUTE_COMPONENT_CANDIDATE_INTEGRATION_STATUS
        assert record.byte_count == INST_RECORD_SIZE_BYTES
        assert len(record.raw_inst_t_row_bytes_hex) == INST_RECORD_SIZE_BYTES * 2
        assert record.raw_inst_t_row_bytes_sha256 == record.copied_from_candidate_sha256
        assert record.overwrite_policy == "reserved_slot_only"
        assert record.overwritten_row_ids == ()
        assert record.decode_roundtrip_status == "candidate_route_decode_roundtrip"
        assert record.micc_coherence_scope == "route_rows_only"
        assert record.micc_coherence_status == "route_slice_candidate_coherent"
        assert record.payload_manifest_status == "route_candidate_manifest_bound"
        assert record.operator_manifest_bound is False
        assert record.runtime_ready is False
        assert record.uploadable is False
        assert record.blocker_ids == ()
        assert record.component_byte_offset not in offsets
        offsets.add(record.component_byte_offset)

    assert len(offsets) == 120
