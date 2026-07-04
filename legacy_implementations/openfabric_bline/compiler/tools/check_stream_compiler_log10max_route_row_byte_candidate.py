#!/usr/bin/env python3
"""Check Phase-3B log10max route COPY candidate row bytes."""

from __future__ import annotations

from collections import defaultdict

from gpdpu_compiler.core.program_legacy_inst import INST_RECORD_SIZE_BYTES
from gpdpu_compiler.core.stream_compiler.log10max_route_row_bytes import (
    ROUTE_CANDIDATE_COMPONENT_STATUS,
    ROUTE_CANDIDATE_DECODE_STATUS,
    ROUTE_CANDIDATE_PLACEMENT_STATUS,
    build_log10max_route_inst_row_byte_candidate_report,
    summarize_log10max_route_inst_row_byte_candidate_report,
)


EXPECTED_PHASE_COUNTS = {
    "col_broadcast": 12,
    "col_reduce": 12,
    "row_broadcast": 48,
    "row_reduce": 48,
}
EXPECTED_FLOW_ACK_COUNTS = {"0": 90, "1": 30}
EXPECTED_FLOW_ACK_ONE_PHASE_COUNTS = {
    "col_broadcast": 3,
    "col_reduce": 3,
    "row_broadcast": 12,
    "row_reduce": 12,
}


def main() -> None:
    report = build_log10max_route_inst_row_byte_candidate_report()
    summary = summarize_log10max_route_inst_row_byte_candidate_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["candidate_count"] != 120:
        failures.append(f"expected 120 route byte candidates: {summary}")
    if summary["logical_route_edge_count"] != 30:
        failures.append(f"expected 30 logical route edges: {summary}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected phase distribution: {summary}")
    if summary["lane_counts"] != {"0": 30, "1": 30, "2": 30, "3": 30}:
        failures.append(f"unexpected lane distribution: {summary}")
    if summary["flow_ack_counts"] != EXPECTED_FLOW_ACK_COUNTS:
        failures.append(f"unexpected flow_ack distribution: {summary}")
    if summary["flow_ack_one_phase_counts"] != EXPECTED_FLOW_ACK_ONE_PHASE_COUNTS:
        failures.append(f"unexpected flow_ack=1 phase distribution: {summary}")
    if summary["decode_roundtrip_status_counts"] != {ROUTE_CANDIDATE_DECODE_STATUS: 120}:
        failures.append(f"all rows must decode as route candidates: {summary}")
    if summary["placement_status_counts"] != {ROUTE_CANDIDATE_PLACEMENT_STATUS: 120}:
        failures.append(f"all rows must stay unplaced: {summary}")
    if summary["component_integration_status_counts"] != {
        ROUTE_CANDIDATE_COMPONENT_STATUS: 120
    }:
        failures.append(f"all rows must stay outside components: {summary}")
    if summary["raw_inst_t_byte_count"] != 120 * INST_RECORD_SIZE_BYTES:
        failures.append(f"unexpected raw byte count: {summary}")
    for key in (
        "final_component_claim_count",
        "runtime_ready_claim_count",
        "uploadable_claim_count",
        "payload_manifest_claim_count",
        "shadow_component_claim_count",
    ):
        if summary[key] != 0:
            failures.append(f"{key} must stay zero: {summary}")
    if summary["runtime_ready"] is not False or summary["uploadable"] is not False:
        failures.append(f"route candidate report must not be ready/uploadable: {summary}")
    if plan["payload_manifest_entries"] != []:
        failures.append("candidate rows must not enter payload manifest")
    if plan["shadow_component_entries"] != []:
        failures.append("candidate rows must not enter shadow component")

    rows_by_edge: dict[str, list[dict[str, object]]] = defaultdict(list)
    seen_ids: set[str] = set()
    for candidate in plan["candidates"]:
        candidate_id = str(candidate["candidate_id"])
        if candidate_id in seen_ids:
            failures.append(f"duplicate candidate id: {candidate}")
        seen_ids.add(candidate_id)
        edge_id = str(candidate["logical_route_edge_id"])
        rows_by_edge[edge_id].append(candidate)

        lane_idx = int(candidate["physical_lane_index"])
        lane_count = int(candidate["physical_lane_count"])
        decoded = candidate["decoded_fields"]
        owners = candidate["decoded_field_owner_ids"]
        statuses = candidate["decoded_field_owner_status"]
        placement = candidate["placement"]
        layout = candidate["layout_provenance"]

        if candidate["decode_roundtrip_status"] != ROUTE_CANDIDATE_DECODE_STATUS:
            failures.append(f"unexpected decode status: {candidate}")
        if candidate["raw_inst_t_byte_count"] != INST_RECORD_SIZE_BYTES:
            failures.append(f"bad row byte size: {candidate}")
        if len(str(candidate["raw_inst_t_row_bytes_hex"])) != (
            INST_RECORD_SIZE_BYTES * 2
        ):
            failures.append(f"candidate row bytes hex has bad length: {candidate}")
        if not candidate["raw_inst_t_row_bytes_sha256"]:
            failures.append(f"missing row sha256: {candidate}")
        if lane_count != 4 or lane_idx not in {0, 1, 2, 3}:
            failures.append(f"unexpected lane metadata: {candidate}")
        if int(candidate["lane_operand_delta"]) != lane_idx * int(candidate["lane_stride"]):
            failures.append(f"lane delta must follow lane stride: {candidate}")
        expected_flow_ack = 1 if lane_idx == 3 else 0
        if decoded["flow_ack"] != expected_flow_ack:
            failures.append(f"flow_ack must follow last-lane policy: {candidate}")
        if statuses.get("flow_ack") != "candidate_bound":
            failures.append(f"flow_ack must be candidate-bound: {candidate}")
        if not owners.get("flow_ack"):
            failures.append(f"flow_ack owner missing: {candidate}")
        if owners.get("flow_ack") == owners.get("end_inst"):
            failures.append(f"flow_ack must not share owner with end_inst: {candidate}")
        if placement.get("placement_status") != ROUTE_CANDIDATE_PLACEMENT_STATUS:
            failures.append(f"candidate must stay unplaced: {candidate}")
        if placement.get("component_byte_offset") is not None:
            failures.append(f"component_byte_offset must stay None: {candidate}")
        if candidate["component_byte_offset"] is not None:
            failures.append(f"top-level component_byte_offset must stay None: {candidate}")
        if candidate["payload_manifest_claim"] is not False:
            failures.append(f"payload manifest claim forbidden: {candidate}")
        if candidate["shadow_component_claim"] is not False:
            failures.append(f"shadow component claim forbidden: {candidate}")
        if candidate["final_component_claim"] is not False:
            failures.append(f"final component claim forbidden: {candidate}")
        if candidate["runtime_ready"] is not False or candidate["uploadable"] is not False:
            failures.append(f"readiness claims forbidden: {candidate}")
        if layout.get("lane_idx") != lane_idx:
            failures.append(f"layout provenance lane mismatch: {candidate}")
        if layout.get("phase") not in EXPECTED_PHASE_COUNTS:
            failures.append(f"unexpected layout phase: {candidate}")

        src = decoded["src_operands_idx"]
        dst = decoded["dst_operands_idx"]
        if src[1:] != [0, 0] or dst[1:] != [0, 0]:
            failures.append(f"COPY candidate must use only src0/dst0: {candidate}")
        for field_name in (
            "opCode",
            "unit_inst_type",
            "latency",
            "src_operands_idx[0]",
            "dst_operands_idx[0]",
            "dst_pes_pos[0]",
            "dst_blocks_idx[0]",
            "flow_ack",
            "end_inst",
            "local_pc",
        ):
            if not owners.get(field_name):
                failures.append(f"missing field owner {field_name}: {candidate}")

    if len(rows_by_edge) != 30:
        failures.append(f"expected 30 edge groups, got {len(rows_by_edge)}")
    for edge_id, rows in rows_by_edge.items():
        lanes = sorted(int(row["physical_lane_index"]) for row in rows)
        if lanes != [0, 1, 2, 3]:
            failures.append(f"{edge_id} must have lanes 0..3 exactly once: {lanes}")
        phases = {str(row["layout_provenance"]["phase"]) for row in rows}
        if len(phases) != 1:
            failures.append(f"{edge_id} rows must share phase: {phases}")
        src_pes = {tuple(row["decoded_fields"]["dst_pes_pos"][0]) for row in rows}
        if len(src_pes) != 1:
            failures.append(f"{edge_id} rows must share receiver PE: {src_pes}")
        dst_blocks = {
            row["decoded_fields"]["dst_blocks_idx"][0]
            for row in rows
        }
        if len(dst_blocks) != 1:
            failures.append(f"{edge_id} rows must share dst block: {dst_blocks}")

    if failures:
        print("stream compiler log10max route row byte candidate check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max route row byte candidate check OK")
    print(f"candidate_count={summary['candidate_count']}")
    print(f"phase_counts={summary['phase_counts']}")
    print(f"flow_ack_counts={summary['flow_ack_counts']}")
    print(f"blocker_ids={summary['blocker_ids']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


if __name__ == "__main__":
    main()
