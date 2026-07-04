from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "compiler"))

from gpdpu_compiler.core.program_legacy_inst import (  # noqa: E402
    OPERANDS_PER_OPERAND_RAM,
)
from gpdpu_compiler.core.stream_compiler.log10max_route_byte_family import (  # noqa: E402
    build_log10max_route_byte_family_decision_report,
    build_log10max_route_physical_row_plan_report,
)


def test_route_byte_family_decision_is_copyt_logical_expanded_copy() -> None:
    report = build_log10max_route_byte_family_decision_report()
    summary = report.summary()

    assert summary["logical_family"] == "copyt_logical_globalmax_route"
    assert summary["physical_family"] == "copyt_logical_expanded_copy_rows"
    assert summary["route_opcode_family"] == "COPYT"
    assert summary["physical_opcode_name"] == "COPY"
    assert summary["logical_value_kind"] == "replicated_vector"
    assert summary["logical_width_bits"] == 4096
    assert summary["lane_count"] == 4
    assert summary["lane_stride"] == OPERANDS_PER_OPERAND_RAM
    assert summary["flow_ack_policy_status"] == "pending_policy"
    assert report.row_bytes_claim is False
    assert report.final_component_claim is False
    assert report.runtime_ready is False
    assert report.uploadable is False


def test_physical_row_plan_expands_30_edges_to_120_copy_lanes() -> None:
    report = build_log10max_route_physical_row_plan_report()
    summary = report.summary()

    assert summary["logical_route_edge_count"] == 30
    assert summary["physical_row_count"] == 120
    assert summary["phase_counts"] == {
        "col_broadcast": 12,
        "col_reduce": 12,
        "row_broadcast": 48,
        "row_reduce": 48,
    }
    assert summary["lane_counts"] == {"0": 30, "1": 30, "2": 30, "3": 30}
    assert summary["physical_opcode_counts"] == {"COPY": 120}
    assert summary["flow_ack_status_counts"] == {"pending_policy": 120}
    assert summary["dst_block_binding_status_counts"] == {"bound": 120}
    assert summary["physical_local_pc_status_counts"] == {"candidate_bound": 120}
    assert report.row_bytes_claim is False
    assert report.final_component_claim is False
    assert report.runtime_ready is False
    assert report.uploadable is False


def test_physical_lane_operand_offsets_are_deterministic() -> None:
    report = build_log10max_route_physical_row_plan_report()
    by_edge: dict[str, list[dict[str, object]]] = {}
    for row in report.to_plan()["physical_rows"]:
        by_edge.setdefault(str(row["logical_route_edge_id"]), []).append(row)

    assert len(by_edge) == 30
    for rows in by_edge.values():
        ordered = sorted(rows, key=lambda row: int(row["lane_index"]))
        base_src = int(ordered[0]["src_operand_base_idx"])
        base_dst = int(ordered[0]["dst_operand_base_idx"])
        assert [row["lane_index"] for row in ordered] == [0, 1, 2, 3]
        assert [
            row["src_operand_idx"] for row in ordered
        ] == [base_src + lane * OPERANDS_PER_OPERAND_RAM for lane in range(4)]
        assert [
            row["dst_operand_idx"] for row in ordered
        ] == [base_dst + lane * OPERANDS_PER_OPERAND_RAM for lane in range(4)]
        assert all(row["dst_block_idx"] is not None for row in ordered)
        assert all(row["dst_block_binding_status"] == "bound" for row in ordered)
        assert [row["physical_local_pc"] for row in ordered] == [
            row["physical_local_order"] for row in ordered
        ]
        assert all(
            row["physical_local_pc_status"] == "candidate_bound" for row in ordered
        )


def test_route_byte_family_check_clis_pass() -> None:
    env = {
        "PYTHONPATH": f"{ROOT / 'compiler'}:{ROOT / 'compiler' / 'tools'}",
    }
    for script in (
        "compiler/tools/check_stream_compiler_log10max_route_byte_family_decision.py",
        "compiler/tools/check_stream_compiler_log10max_route_physical_row_plan.py",
    ):
        result = subprocess.run(
            [sys.executable, str(ROOT / script)],
            check=False,
            cwd=ROOT,
            env=env,
            text=True,
            capture_output=True,
        )
        assert result.returncode == 0, result.stdout + result.stderr
