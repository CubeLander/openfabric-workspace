#!/usr/bin/env python3
"""Check Phase-2 log10max route flow_ack policy stays fail-closed."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.log10max_ring_update_operands import (
    EXPECTED_PHASE_COUNTS,
)
from gpdpu_compiler.core.stream_compiler.log10max_route_flow_ack import (
    FLOW_ACK_EVIDENCE_REFS,
    LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING,
    build_log10max_route_flow_ack_policy_report,
    summarize_log10max_route_flow_ack_policy_report,
)


def main() -> None:
    report = build_log10max_route_flow_ack_policy_report()
    summary = summarize_log10max_route_flow_ack_policy_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["policy_count"] != 30:
        failures.append(f"expected 30 flow_ack policies: {summary}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected phase distribution: {summary}")
    if summary["policy_counts"] != {"blocked": 30}:
        failures.append(f"default flow_ack policy must be fail-closed: {summary}")
    if summary["flow_ack_status_counts"] != {"blocked": 30}:
        failures.append(f"default flow_ack status must be blocked: {summary}")
    if summary["route_family_intent_counts"] != {"copy_like_candidate": 30}:
        failures.append(f"expected COPY-like route intent for all edges: {summary}")
    if summary["copy_like_serialization_blocked_count"] != 30:
        failures.append(f"all COPY-like policies must block serialization: {summary}")
    if summary["copy_like_row_candidate_serialization_claim_count"] != 0:
        failures.append(f"unbound flow_ack must not serialize rows: {summary}")
    if summary["candidate_evidence_count"] != 90:
        failures.append(f"expected 90 flow_ack evidence candidates: {summary}")
    if summary["candidate_policy_counts"] != {
        "child_edge_slot": 30,
        "last_physical_copy_lane_sets_one": 30,
        "source_template_fixed": 30,
    }:
        failures.append(f"unexpected candidate policy matrix: {summary}")
    if summary["candidate_status_counts"] != {
        "blocked_conflicting_evidence": 60,
        "blocked_missing_exact_source_span": 30,
    }:
        failures.append(f"candidate ambiguity must remain explicit: {summary}")
    if summary["candidate_serialization_claim_count"] != 0:
        failures.append(f"candidate matrix must not allow serialization: {summary}")
    if summary["candidate_final_component_claim_count"] != 0:
        failures.append(f"candidate matrix must not claim final component: {summary}")
    if LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING not in summary["blocker_ids"]:
        failures.append(f"flow_ack blocker must remain: {summary}")
    if len(summary["evidence_refs"]) != len(FLOW_ACK_EVIDENCE_REFS):
        failures.append(f"evidence refs must be preserved: {summary}")
    if summary["final_component_claim"] is not False:
        failures.append("flow_ack report must not claim final component")
    if summary["runtime_ready"] is not False:
        failures.append("flow_ack report must not claim runtime_ready")
    if summary["uploadable"] is not False:
        failures.append("flow_ack report must not claim uploadable")

    seen_policy_ids: set[str] = set()
    seen_edges: set[str] = set()
    for policy in plan["policies"]:
        policy_id = str(policy["policy_id"])
        edge_id = str(policy["logical_route_edge_id"])
        if policy_id in seen_policy_ids:
            failures.append(f"duplicate policy id: {policy}")
        seen_policy_ids.add(policy_id)
        if edge_id in seen_edges:
            failures.append(f"duplicate route edge policy: {policy}")
        seen_edges.add(edge_id)
        if policy["policy"] != "blocked":
            failures.append(f"default policy must remain blocked: {policy}")
        if policy["flow_ack_status"] != "blocked":
            failures.append(f"default flow_ack status must remain blocked: {policy}")
        if policy["applies_to"] != "simulator_inst_t":
            failures.append(f"Phase 2 must only bind simulator inst_t: {policy}")
        if policy["rtl_projection_status"] != "not_claimed":
            failures.append(f"RTL projection must not be claimed: {policy}")
        if policy["route_family_intent"] != "copy_like_candidate":
            failures.append(f"expected COPY-like candidate intent: {policy}")
        if policy["copy_like_row_candidate_serialization_claim"] is not False:
            failures.append(f"unbound flow_ack must not serialize: {policy}")
        if policy["final_component_claim"] is not False:
            failures.append(f"flow_ack policy must not claim final component: {policy}")
        if policy["blocks_copy_like_serialization"] is not True:
            failures.append(f"COPY-like policy must block serialization: {policy}")
        if policy["bound_flow_ack_by_physical_lane"] != {}:
            failures.append(f"blocked policy must not bind lane values: {policy}")
        if LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING not in policy["blocker_ids"]:
            failures.append(f"flow_ack blocker missing from policy: {policy}")
        if len(policy["candidate_policy_evidence_refs"]) != len(FLOW_ACK_EVIDENCE_REFS):
            failures.append(f"candidate evidence refs missing: {policy}")
        if policy["runtime_ready"] is not False:
            failures.append(f"policy must not claim runtime_ready: {policy}")
        if policy["uploadable"] is not False:
            failures.append(f"policy must not claim uploadable: {policy}")

    if len(seen_edges) != 30:
        failures.append(f"expected 30 unique edge policies, got {len(seen_edges)}")

    candidates_by_edge: dict[str, set[str]] = {}
    for candidate in plan["candidate_evidence_matrix"]:
        edge_id = str(candidate["logical_route_edge_id"])
        candidate_policy = str(candidate["candidate_policy"])
        candidates_by_edge.setdefault(edge_id, set()).add(candidate_policy)
        if candidate["serialization_allowed"] is not False:
            failures.append(f"candidate must not allow serialization: {candidate}")
        if candidate["final_component_claim"] is not False:
            failures.append(f"candidate must not claim final component: {candidate}")
        if LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING not in candidate["blocker_ids"]:
            failures.append(f"candidate must retain blocker: {candidate}")
        if candidate_policy == "child_edge_slot":
            if candidate["candidate_status"] != "blocked_conflicting_evidence":
                failures.append(f"child_edge_slot must be ambiguous: {candidate}")
            if candidate["candidate_flow_ack_by_physical_lane"] != {
                0: 0,
                1: 0,
                2: 0,
                3: 0,
            }:
                failures.append(f"child_edge_slot candidate values changed: {candidate}")
            if not candidate["conflict_refs"]:
                failures.append(f"child_edge_slot conflict refs required: {candidate}")
        elif candidate_policy == "last_physical_copy_lane_sets_one":
            if candidate["candidate_status"] != "blocked_conflicting_evidence":
                failures.append(f"last-lane policy must be ambiguous: {candidate}")
            if candidate["candidate_flow_ack_by_physical_lane"] != {
                0: 0,
                1: 0,
                2: 0,
                3: 1,
            }:
                failures.append(f"last-lane candidate values changed: {candidate}")
            if not candidate["conflict_refs"]:
                failures.append(f"last-lane conflict refs required: {candidate}")
        elif candidate_policy == "source_template_fixed":
            if candidate["candidate_status"] != "blocked_missing_exact_source_span":
                failures.append(f"source-template policy must need exact span: {candidate}")
            if candidate["candidate_flow_ack_by_physical_lane"] != {}:
                failures.append(f"source-template must not invent values: {candidate}")
            if not candidate["missing_evidence"]:
                failures.append(f"source-template missing evidence required: {candidate}")
        else:
            failures.append(f"unexpected flow_ack candidate policy: {candidate}")

    expected_matrix = {
        "child_edge_slot",
        "last_physical_copy_lane_sets_one",
        "source_template_fixed",
    }
    for edge_id, policy_set in candidates_by_edge.items():
        if policy_set != expected_matrix:
            failures.append(f"incomplete candidate matrix for {edge_id}: {policy_set}")
    if set(candidates_by_edge) != seen_edges:
        failures.append("candidate matrix edge set must match policy edge set")

    if failures:
        print("stream compiler log10max route flow_ack policy check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max route flow_ack policy check OK")
    print(f"policy_count={summary['policy_count']}")
    print(f"phase_counts={summary['phase_counts']}")
    print(f"flow_ack_status_counts={summary['flow_ack_status_counts']}")
    print(f"blocker_ids={summary['blocker_ids']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


if __name__ == "__main__":
    main()
