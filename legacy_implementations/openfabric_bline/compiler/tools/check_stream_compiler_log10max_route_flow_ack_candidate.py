#!/usr/bin/env python3
"""Check Phase-3A log10max route flow_ack candidate policy."""

from __future__ import annotations

from collections import defaultdict

from gpdpu_compiler.core.stream_compiler.log10max_ring_update_operands import (
    EXPECTED_PHASE_COUNTS,
)
from gpdpu_compiler.core.stream_compiler.log10max_route_flow_ack import (
    BASE_ADDR_SLOT_COUNT,
    LOG10MAX_ROUTE_FLOW_ACK_FINAL_POLICY_MISSING,
    build_log10max_route_flow_ack_candidate_report,
    summarize_log10max_route_flow_ack_candidate_report,
)


EXPECTED_PHYSICAL_PHASE_COUNTS = {
    phase: count * 4 for phase, count in sorted(EXPECTED_PHASE_COUNTS.items())
}
EXPECTED_FLOW_ACK_COUNTS = {"0": 90, "1": 30}
EXPECTED_REASON_COUNTS = {
    "lane_idx_0_not_last_physical_copy_lane": 30,
    "lane_idx_1_not_last_physical_copy_lane": 30,
    "lane_idx_2_not_last_physical_copy_lane": 30,
    "lane_idx_3_last_physical_copy_lane": 30,
}


def main() -> None:
    report = build_log10max_route_flow_ack_candidate_report()
    summary = summarize_log10max_route_flow_ack_candidate_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["logical_route_edge_count"] != 30:
        failures.append(f"expected 30 logical route edges: {summary}")
    if summary["candidate_count"] != 120:
        failures.append(f"expected 120 physical flow_ack candidates: {summary}")
    if summary["phase_counts"] != EXPECTED_PHYSICAL_PHASE_COUNTS:
        failures.append(f"unexpected physical phase distribution: {summary}")
    if summary["flow_ack_value_counts"] != EXPECTED_FLOW_ACK_COUNTS:
        failures.append(f"unexpected flow_ack distribution: {summary}")
    if summary["flow_ack_one_phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected flow_ack=1 phase distribution: {summary}")
    if summary["flow_ack_status_counts"] != {"candidate_bound": 120}:
        failures.append(f"all flow_ack values must be candidate-bound: {summary}")
    if summary["final_policy_status_counts"] != {"pending_final_policy": 120}:
        failures.append(f"final flow_ack policy must remain pending: {summary}")
    if summary["base_slot_status_counts"] != {"range_checked": 120}:
        failures.append(f"base slot status must be range-checked only: {summary}")
    if summary["candidate_policy_counts"] != {
        "last_physical_copy_lane_sets_one": 120
    }:
        failures.append(f"unexpected flow_ack candidate policy: {summary}")
    if summary["flow_ack_reason_counts"] != EXPECTED_REASON_COUNTS:
        failures.append(f"unexpected flow_ack reason counts: {summary}")
    if summary["final_component_claim_count"] != 0:
        failures.append(f"candidate report must not claim final component: {summary}")
    if summary["runtime_ready_claim_count"] != 0:
        failures.append(f"candidate report must not claim runtime_ready: {summary}")
    if summary["uploadable_claim_count"] != 0:
        failures.append(f"candidate report must not claim uploadable: {summary}")
    if LOG10MAX_ROUTE_FLOW_ACK_FINAL_POLICY_MISSING not in summary["blocker_ids"]:
        failures.append(f"final policy blocker must remain: {summary}")
    if summary["final_component_claim"] is not False:
        failures.append("report must not claim final component")
    if summary["runtime_ready"] is not False:
        failures.append("report must not claim runtime_ready")
    if summary["uploadable"] is not False:
        failures.append("report must not claim uploadable")

    candidates_by_edge: dict[str, list[dict[str, object]]] = defaultdict(list)
    seen_candidate_ids: set[str] = set()
    for candidate in plan["candidates"]:
        candidate_id = str(candidate["candidate_id"])
        if candidate_id in seen_candidate_ids:
            failures.append(f"duplicate candidate id: {candidate}")
        seen_candidate_ids.add(candidate_id)
        edge_id = str(candidate["logical_route_edge_id"])
        candidates_by_edge[edge_id].append(candidate)

        lane_idx = int(candidate["physical_lane_index"])
        lane_count = int(candidate["physical_lane_count"])
        flow_ack = int(candidate["flow_ack"])
        expected_flow_ack = 1 if lane_idx == lane_count - 1 else 0
        expected_reason = (
            "lane_idx_3_last_physical_copy_lane"
            if expected_flow_ack == 1
            else f"lane_idx_{lane_idx}_not_last_physical_copy_lane"
        )
        if lane_count != 4:
            failures.append(f"expected COPYT logical expansion into 4 lanes: {candidate}")
        if lane_idx not in {0, 1, 2, 3}:
            failures.append(f"unexpected lane index: {candidate}")
        if flow_ack != expected_flow_ack:
            failures.append(f"last-lane policy mismatch: {candidate}")
        if candidate["flow_ack_reason"] != expected_reason:
            failures.append(f"missing or wrong per-row flow_ack reason: {candidate}")
        if not (0 <= flow_ack < BASE_ADDR_SLOT_COUNT):
            failures.append(f"flow_ack outside base slot range: {candidate}")
        if candidate["base_slot_status"] != "range_checked":
            failures.append(f"candidate phase should only range-check base slot: {candidate}")
        if candidate["base_slot_binding_id"] is not None:
            failures.append(f"candidate phase must not bind runtime base slot: {candidate}")
        if candidate["candidate_policy"] != "last_physical_copy_lane_sets_one":
            failures.append(f"unexpected candidate policy: {candidate}")
        if candidate["flow_ack_status"] != "candidate_bound":
            failures.append(f"flow_ack must be candidate-bound: {candidate}")
        if candidate["final_policy_status"] != "pending_final_policy":
            failures.append(f"final policy must remain pending: {candidate}")
        if LOG10MAX_ROUTE_FLOW_ACK_FINAL_POLICY_MISSING not in candidate["blocker_ids"]:
            failures.append(f"final policy blocker missing: {candidate}")
        if candidate["final_component_claim"] is not False:
            failures.append(f"candidate must not claim final component: {candidate}")
        if candidate["runtime_ready"] is not False:
            failures.append(f"candidate must not claim runtime_ready: {candidate}")
        if candidate["uploadable"] is not False:
            failures.append(f"candidate must not claim uploadable: {candidate}")

    if len(candidates_by_edge) != 30:
        failures.append(f"expected 30 edge groups, got {len(candidates_by_edge)}")
    for edge_id, rows in candidates_by_edge.items():
        lanes = sorted(int(row["physical_lane_index"]) for row in rows)
        if lanes != [0, 1, 2, 3]:
            failures.append(f"{edge_id} must have lanes 0..3 exactly once: {lanes}")
        phases = {str(row["phase"]) for row in rows}
        if len(phases) != 1:
            failures.append(f"{edge_id} rows must share one phase: {phases}")
        endpoint_ids = {str(row["route_endpoint_patch_id"]) for row in rows}
        if len(endpoint_ids) != 1:
            failures.append(f"{edge_id} rows must share route endpoint: {endpoint_ids}")

    if failures:
        print("stream compiler log10max route flow_ack candidate check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max route flow_ack candidate check OK")
    print(f"candidate_count={summary['candidate_count']}")
    print(f"phase_counts={summary['phase_counts']}")
    print(f"flow_ack_value_counts={summary['flow_ack_value_counts']}")
    print(f"flow_ack_one_phase_counts={summary['flow_ack_one_phase_counts']}")
    print(f"base_slot_status_counts={summary['base_slot_status_counts']}")
    print(f"blocker_ids={summary['blocker_ids']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


if __name__ == "__main__":
    main()
