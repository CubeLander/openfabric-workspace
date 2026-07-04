#!/usr/bin/env python3
"""Check Phase-4A log10max route final flow_ack field ownership."""

from __future__ import annotations

from collections import defaultdict

from gpdpu_compiler.core.stream_compiler.log10max_ring_update_operands import (
    EXPECTED_PHASE_COUNTS,
)
from gpdpu_compiler.core.stream_compiler.log10max_route_flow_ack import (
    BASE_ADDR_SLOT_COUNT,
    LOG10MAX_ROUTE_COMPONENT_BYTE_OFFSET_MISSING,
    build_log10max_route_flow_ack_final_policy_report,
    summarize_log10max_route_flow_ack_final_policy_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_route_endpoint_patch import (
    LOG10MAX_ROUTE_COMPONENT_INTEGRATION_BLOCKER,
)


EXPECTED_PHYSICAL_PHASE_COUNTS = {
    phase: count * 4 for phase, count in sorted(EXPECTED_PHASE_COUNTS.items())
}
EXPECTED_FLOW_ACK_COUNTS = {"0": 90, "1": 30}


def main() -> None:
    report = build_log10max_route_flow_ack_final_policy_report()
    summary = summarize_log10max_route_flow_ack_final_policy_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["logical_route_edge_count"] != 30:
        failures.append(f"expected 30 logical route edges: {summary}")
    if summary["binding_count"] != 120:
        failures.append(f"expected 120 final flow_ack bindings: {summary}")
    if summary["phase_counts"] != EXPECTED_PHYSICAL_PHASE_COUNTS:
        failures.append(f"unexpected phase distribution: {summary}")
    if summary["flow_ack_value_counts"] != EXPECTED_FLOW_ACK_COUNTS:
        failures.append(f"unexpected flow_ack values: {summary}")
    if summary["flow_ack_one_phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected flow_ack=1 phase distribution: {summary}")
    if summary["final_policy_status_counts"] != {"final_bound": 120}:
        failures.append(f"all flow_ack values must be final-bound: {summary}")
    if summary["base_slot_status_counts"] != {"asset_bound": 120}:
        failures.append(f"base slot evidence must be final-bound: {summary}")
    if summary["policy_scope_counts"] != {"simulator_inst_t_only": 120}:
        failures.append(f"policy scope must remain simulator-only: {summary}")
    if summary["rtl_projection_status_counts"] != {"not_claimed": 120}:
        failures.append(f"RTL projection must remain unclaimed: {summary}")
    if summary["final_component_claim_count"] != 0:
        failures.append(f"must not claim final component: {summary}")
    if summary["runtime_ready_claim_count"] != 0:
        failures.append(f"must not claim runtime_ready: {summary}")
    if summary["uploadable_claim_count"] != 0:
        failures.append(f"must not claim uploadable: {summary}")
    if LOG10MAX_ROUTE_COMPONENT_BYTE_OFFSET_MISSING not in summary["blocker_ids"]:
        failures.append(f"component offset blocker must remain: {summary}")
    if LOG10MAX_ROUTE_COMPONENT_INTEGRATION_BLOCKER not in summary["blocker_ids"]:
        failures.append(f"component integration blocker must remain: {summary}")
    if "log10max_route_flow_ack_final_policy_missing" in summary["blocker_ids"]:
        failures.append(f"final flow_ack blocker should be cleared: {summary}")
    if summary["runtime_ready"] is not False or summary["uploadable"] is not False:
        failures.append(f"readiness claims forbidden: {summary}")

    rows_by_edge: dict[str, list[dict[str, object]]] = defaultdict(list)
    seen_ids: set[str] = set()
    for binding in plan["bindings"]:
        binding_id = str(binding["binding_id"])
        if binding_id in seen_ids:
            failures.append(f"duplicate binding id: {binding}")
        seen_ids.add(binding_id)
        rows_by_edge[str(binding["logical_route_edge_id"])].append(binding)

        lane_idx = int(binding["physical_lane_index"])
        lane_count = int(binding["physical_lane_count"])
        flow_ack = int(binding["flow_ack"])
        expected_flow_ack = 1 if lane_idx == lane_count - 1 else 0
        if flow_ack != expected_flow_ack:
            failures.append(f"last-lane policy mismatch: {binding}")
        if not (0 <= flow_ack < BASE_ADDR_SLOT_COUNT):
            failures.append(f"flow_ack outside base slot range: {binding}")
        if binding["policy_scope"] != "simulator_inst_t_only":
            failures.append(f"unexpected final policy scope: {binding}")
        if binding["rtl_projection_status"] != "not_claimed":
            failures.append(f"must not claim RTL projection: {binding}")
        if binding["final_policy_status"] != "final_bound":
            failures.append(f"flow_ack not final-bound: {binding}")
        if binding["base_slot_status"] != "asset_bound":
            failures.append(f"base slot not asset-bound: {binding}")
        if not binding["base_slot_binding_id"]:
            failures.append(f"base slot binding id missing: {binding}")
        if not binding["base_slot_evidence_id"]:
            failures.append(f"base slot evidence missing: {binding}")
        if not binding["memory_template_check_report_id"]:
            failures.append(f"memory-template evidence missing: {binding}")
        if binding["simulator_path_exempt_evidence_id"] is not None:
            failures.append(f"simulator exemption should not be used by default: {binding}")
        if binding["final_component_claim"] is not False:
            failures.append(f"final component claim forbidden: {binding}")
        if binding["runtime_ready"] is not False or binding["uploadable"] is not False:
            failures.append(f"readiness claims forbidden: {binding}")
        if binding["blocker_ids"] != []:
            failures.append(f"per-row blocker should be empty: {binding}")

    if len(rows_by_edge) != 30:
        failures.append(f"expected 30 edge groups, got {len(rows_by_edge)}")
    for edge_id, rows in rows_by_edge.items():
        lanes = sorted(int(row["physical_lane_index"]) for row in rows)
        if lanes != [0, 1, 2, 3]:
            failures.append(f"{edge_id} must have lanes 0..3 exactly once: {lanes}")
        phases = {str(row["phase"]) for row in rows}
        if len(phases) != 1:
            failures.append(f"{edge_id} rows must share one phase: {phases}")

    if failures:
        print("stream compiler log10max route flow_ack final policy check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max route flow_ack final policy check OK")
    print(f"binding_count={summary['binding_count']}")
    print(f"phase_counts={summary['phase_counts']}")
    print(f"flow_ack_value_counts={summary['flow_ack_value_counts']}")
    print(f"base_slot_status_counts={summary['base_slot_status_counts']}")
    print(f"blocker_ids={summary['blocker_ids']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


if __name__ == "__main__":
    main()
