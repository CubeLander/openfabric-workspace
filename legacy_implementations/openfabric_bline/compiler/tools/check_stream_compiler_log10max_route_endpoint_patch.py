#!/usr/bin/env python3
"""Check Phase-0 log10max route endpoint patch closure."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.log10max_route_endpoint_patch import (
    LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER,
    LOG10MAX_ROUTE_FAMILY_PHASE2_BLOCKER,
    LOG10MAX_ROUTE_ROW_BYTES_BLOCKER,
    build_log10max_route_endpoint_patch_report,
    summarize_log10max_route_endpoint_patch_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_ring_update_operands import (
    EXPECTED_PHASE_COUNTS,
)


def main() -> None:
    report = build_log10max_route_endpoint_patch_report()
    summary = summarize_log10max_route_endpoint_patch_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["endpoint_count"] != 30:
        failures.append(f"expected 30 route endpoint patches: {summary}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected phase distribution: {summary}")
    if summary["unique_push_recv_pair_count"] != 30:
        failures.append(f"push/recv pairs must be unique: {summary}")
    if summary["route_opcode_family_counts"] != {"undecided": 30}:
        failures.append(f"Phase 0 must not choose COPY/COPYT/LDN: {summary}")
    if summary["route_family_status_counts"] != {"pending_phase2_decision": 30}:
        failures.append(f"route family must stay pending Phase 2: {summary}")
    if summary["patch_status_counts"] != {"endpoint_bound_layout_pending": 30}:
        failures.append(f"endpoints should be bound but layout-pending: {summary}")
    if summary["recv_to_fmax_continuity_status_counts"] != {"matched": 30}:
        failures.append(f"route_recv.dst must match FMAX.src_received: {summary}")
    if summary["dst_pe_coord_status_counts"] != {"profile_backed": 30}:
        failures.append(f"dst PE coordinates must be profile-backed: {summary}")
    if summary["flow_ack_status_counts"] != {"pending_policy": 30}:
        failures.append(f"flow_ack must stay explicitly pending: {summary}")
    if LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER not in summary["blocker_ids"]:
        failures.append(f"flow_ack blocker must remain: {summary}")
    if LOG10MAX_ROUTE_FAMILY_PHASE2_BLOCKER not in summary["blocker_ids"]:
        failures.append(f"route family Phase-2 blocker must remain: {summary}")
    if LOG10MAX_ROUTE_ROW_BYTES_BLOCKER not in summary["blocker_ids"]:
        failures.append(f"route row bytes blocker must remain: {summary}")
    if summary["row_bytes_claim"] is not False:
        failures.append("endpoint report must not claim row bytes")
    if summary["physical_route_row_claim"] is not False:
        failures.append("endpoint report must not claim physical route rows")
    if summary["runtime_ready"] is not False:
        failures.append("endpoint report must not claim runtime_ready")
    if summary["uploadable"] is not False:
        failures.append("endpoint report must not claim uploadable")

    local_reduce_sources = 0
    previous_acc_sources = 0
    seen_pairs: set[tuple[str, str]] = set()
    seen_edges: set[str] = set()
    phase_counts: dict[str, int] = {}
    for patch in plan["patches"]:
        edge_id = str(patch["logical_route_edge_id"])
        phase = str(patch["phase"])
        seen_edges.add(edge_id)
        phase_counts[phase] = phase_counts.get(phase, 0) + 1
        pair = (
            str(patch["sender_stream_action_id"]),
            str(patch["receiver_stream_action_id"]),
        )
        if pair in seen_pairs:
            failures.append(f"duplicate push/recv pair: {patch}")
        seen_pairs.add(pair)

        if patch["physical_route_row_candidate_ids"]:
            failures.append(f"Phase 0 must not claim physical rows: {patch}")
        if patch["route_opcode_family"] != "undecided":
            failures.append(f"Phase 0 route family must remain undecided: {patch}")
        if patch["route_family_status"] != "pending_phase2_decision":
            failures.append(f"route family status must be pending: {patch}")
        if patch["route_family_decision_id"] is not None:
            failures.append(f"Phase 0 must not attach family decision id: {patch}")
        if patch["src_route_operand_patch_id"] is not None:
            failures.append(f"route row src operand patch must remain absent: {patch}")
        if patch["dst_route_operand_patch_id"] is not None:
            failures.append(f"route row dst operand patch must remain absent: {patch}")
        if not patch["src_operand_allocation_id"]:
            failures.append(f"sender source allocation id missing: {patch}")
        if not patch["dst_operand_allocation_id"]:
            failures.append(f"receiver destination allocation id missing: {patch}")
        if patch["sender_scope_status"] != "sender_task_pe":
            failures.append(f"push source must use sender task_pe scope: {patch}")
        if patch["receiver_scope_status"] != "receiver_task_pe":
            failures.append(f"recv destination must use receiver task_pe scope: {patch}")
        if patch["src_allocation_scope"] != patch["expected_src_allocation_scope"]:
            failures.append(f"sender allocation scope mismatch: {patch}")
        if patch["dst_allocation_scope"] != patch["expected_dst_allocation_scope"]:
            failures.append(f"receiver allocation scope mismatch: {patch}")
        if patch["dst_placeholder_id"] != patch["fmax_src_received_placeholder_id"]:
            failures.append(f"recv placeholder must feed FMAX src_received: {patch}")
        if patch["dst_operand_allocation_id"] != patch["fmax_src_received_allocation_id"]:
            failures.append(f"recv allocation must feed FMAX src_received: {patch}")
        if patch["dst_operand_idx"] != patch["fmax_src_received_operand_idx"]:
            failures.append(f"recv operand idx must feed FMAX src_received: {patch}")
        continuity = patch["push_source_continuity"]
        if continuity == "local_reduce_max_out":
            local_reduce_sources += 1
        elif continuity == "previous_globalmax_acc_out":
            previous_acc_sources += 1
        else:
            failures.append(
                "route_push.src must be local_reduce_max_out or previous acc_out: "
                f"{patch}"
            )
        if patch["dst_pe_coord_status"] not in {"source_backed", "profile_backed"}:
            failures.append(f"dst PE coordinate must be concrete: {patch}")
        if len(patch["dst_pe_pos"]) != 3:
            failures.append(f"dst PE position must be x/y/z tuple: {patch}")
        if patch["dst_block_idx"] is not None:
            failures.append(f"dst block must remain layout-pending in Phase 0: {patch}")
        if patch["dst_block_binding_status"] != "pending_layout":
            failures.append(f"dst block binding must stay pending_layout: {patch}")
        if patch["flow_ack"] is not None:
            failures.append(f"flow_ack must not be silently filled: {patch}")
        if patch["flow_ack_policy_id"] is not None:
            failures.append(f"flow_ack policy must stay pending: {patch}")
        if patch["flow_ack_status"] != "pending_policy":
            failures.append(f"flow_ack status must be pending_policy: {patch}")
        if LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER not in patch["blocker_ids"]:
            failures.append(f"flow_ack blocker missing from patch: {patch}")
        if patch["row_bytes_claim"] is not False:
            failures.append(f"route endpoint patch must not claim row bytes: {patch}")
        if patch["physical_route_row_claim"] is not False:
            failures.append(f"route endpoint patch must not claim physical rows: {patch}")
        if patch["runtime_ready"] is not False:
            failures.append(f"route endpoint patch must not claim runtime_ready: {patch}")
        if patch["uploadable"] is not False:
            failures.append(f"route endpoint patch must not claim uploadable: {patch}")

    if len(seen_edges) != 30:
        failures.append(f"expected 30 unique logical route edges, got {len(seen_edges)}")
    if phase_counts != EXPECTED_PHASE_COUNTS:
        failures.append(f"record phase distribution mismatch: {phase_counts}")
    if local_reduce_sources <= 0:
        failures.append("expected at least one route_push sourced from local_reduce")
    if local_reduce_sources + previous_acc_sources != 30:
        failures.append(
            "all route_push sources must be local_reduce or previous acc_out: "
            f"local_reduce={local_reduce_sources}, previous_acc={previous_acc_sources}"
        )

    if failures:
        print("stream compiler log10max route endpoint patch check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max route endpoint patch check OK")
    print(f"endpoint_count={summary['endpoint_count']}")
    print(f"phase_counts={summary['phase_counts']}")
    print(f"blocker_ids={summary['blocker_ids']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


if __name__ == "__main__":
    main()
