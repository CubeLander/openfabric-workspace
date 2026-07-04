from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "compiler"))

from gpdpu_compiler.core.program_legacy_inst import (  # noqa: E402
    INST_RECORD_SIZE_BYTES,
    LEGACY_OPS,
    OPERANDS_PER_OPERAND_RAM,
)
from gpdpu_compiler.core.stream_compiler.log10max_route_inst_fields import (  # noqa: E402
    EXPECTED_PHYSICAL_PHASE_COUNTS,
)
from gpdpu_compiler.core.stream_compiler.log10max_route_row_bytes import (  # noqa: E402
    LOG10MAX_ROUTE_COMPONENT_BYTE_OFFSET_MISSING,
    LOG10MAX_ROUTE_COMPONENT_INTEGRATION_MISSING,
    LOG10MAX_ROUTE_FLOW_ACK_FINAL_POLICY_MISSING,
    build_log10max_route_inst_row_byte_candidate_report,
)


def test_route_copy_candidate_bytes_are_report_only_and_decode() -> None:
    report = build_log10max_route_inst_row_byte_candidate_report()
    summary = report.summary()

    assert summary["logical_route_edge_count"] == 30
    assert summary["candidate_count"] == 120
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
        "candidate_route_decode_roundtrip": 120
    }
    assert summary["placement_status_counts"] == {"unplaced_candidate": 120}
    assert summary["component_integration_status_counts"] == {"not_integrated": 120}
    assert summary["raw_inst_t_byte_count"] == 120 * INST_RECORD_SIZE_BYTES
    assert summary["final_component_claim_count"] == 0
    assert summary["runtime_ready_claim_count"] == 0
    assert summary["uploadable_claim_count"] == 0
    assert summary["payload_manifest_claim_count"] == 0
    assert summary["shadow_component_claim_count"] == 0
    assert LOG10MAX_ROUTE_FLOW_ACK_FINAL_POLICY_MISSING in summary["blocker_ids"]
    assert LOG10MAX_ROUTE_COMPONENT_BYTE_OFFSET_MISSING in summary["blocker_ids"]
    assert LOG10MAX_ROUTE_COMPONENT_INTEGRATION_MISSING in summary["blocker_ids"]
    assert summary["runtime_ready"] is False
    assert summary["uploadable"] is False


def test_route_copy_candidate_lane_grouping_and_owner_status() -> None:
    report = build_log10max_route_inst_row_byte_candidate_report()
    by_edge: dict[str, list[dict[str, object]]] = {}
    for candidate in report.to_plan()["candidates"]:
        by_edge.setdefault(str(candidate["logical_route_edge_id"]), []).append(
            candidate
        )
        decoded = candidate["decoded_fields"]
        placement = candidate["placement"]
        layout = candidate["layout_provenance"]
        owners = candidate["decoded_field_owner_ids"]
        statuses = candidate["decoded_field_owner_status"]
        lane = int(candidate["physical_lane_index"])
        flow_ack = 1 if lane == 3 else 0

        assert len(candidate["raw_inst_t_row_bytes_hex"]) == (
            INST_RECORD_SIZE_BYTES * 2
        )
        assert decoded["opCode"] == LEGACY_OPS["COPY"].opcode
        assert decoded["src_operands_idx"][1:] == [0, 0]
        assert decoded["dst_operands_idx"][1:] == [0, 0]
        assert decoded["flow_ack"] == flow_ack
        assert candidate["flow_ack_policy_candidate_id"].startswith(
            "flow_ack_candidate:"
        )
        assert statuses["flow_ack"] == "candidate_bound"
        assert statuses["end_inst"] == "bound"
        assert owners["flow_ack"] != owners["end_inst"]
        assert statuses["src_operands_idx[1]"] == "zero_with_evidence"
        assert statuses["dst_operands_idx[1]"] == "zero_with_evidence"
        assert "component_byte_offset" not in decoded
        assert "local_pc" not in decoded
        assert placement["component_byte_offset"] is None
        assert placement["placement_status"] == "unplaced_candidate"
        assert layout["local_pc_candidate"] is not None
        assert candidate["component_byte_offset"] is None
        assert candidate["final_component_claim"] is False
        assert candidate["runtime_ready"] is False
        assert candidate["uploadable"] is False
        assert candidate["payload_manifest_claim"] is False
        assert candidate["shadow_component_claim"] is False

    assert len(by_edge) == 30
    for rows in by_edge.values():
        ordered = sorted(rows, key=lambda row: int(row["physical_lane_index"]))
        assert [row["physical_lane_index"] for row in ordered] == [0, 1, 2, 3]
        base_src = int(ordered[0]["decoded_fields"]["src_operands_idx"][0])
        base_dst = int(ordered[0]["decoded_fields"]["dst_operands_idx"][0])
        assert [
            row["decoded_fields"]["src_operands_idx"][0] for row in ordered
        ] == [base_src + lane * OPERANDS_PER_OPERAND_RAM for lane in range(4)]
        assert [
            row["decoded_fields"]["dst_operands_idx"][0] for row in ordered
        ] == [base_dst + lane * OPERANDS_PER_OPERAND_RAM for lane in range(4)]
        assert [row["decoded_fields"]["flow_ack"] for row in ordered] == [0, 0, 0, 1]


def test_route_copy_candidate_checker_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "compiler/tools/check_stream_compiler_log10max_route_row_byte_candidate.py"
            ),
        ],
        check=False,
        cwd=ROOT,
        env={"PYTHONPATH": f"{ROOT / 'compiler'}:{ROOT / 'compiler' / 'tools'}"},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
