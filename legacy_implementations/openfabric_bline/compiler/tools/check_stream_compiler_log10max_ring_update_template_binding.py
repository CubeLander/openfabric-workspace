#!/usr/bin/env python3
"""Check Phase-1 log10max ring update template bindings."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gpdpu_compiler.core.stream_compiler.log10max_ring_update_template import (
    build_log10max_ring_update_template_binding_report,
    summarize_log10max_ring_update_template_binding_report,
)


EXPECTED_PHASE_COUNTS = {
    "col_broadcast": 3,
    "col_reduce": 3,
    "row_broadcast": 12,
    "row_reduce": 12,
}


def main() -> None:
    report = build_log10max_ring_update_template_binding_report()
    summary = summarize_log10max_ring_update_template_binding_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["binding_count"] != 30:
        failures.append(f"expected 30 update bindings: {summary}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected phase distribution: {summary}")
    if summary["opcode_counts"] != {"FMAX": 30}:
        failures.append(f"fp32 V1 must bind FMAX updates: {summary}")
    if summary["template_status_counts"] != {"candidate_available": 30}:
        failures.append(f"unexpected template status counts: {summary}")
    if summary["blocker_ids"] != ["log10max_ring_update_row_bytes_missing"]:
        failures.append(f"Phase 1 must move to row-byte blocker: {summary}")
    if summary["runtime_ready"] is not False:
        failures.append("Phase 1 binding must keep runtime_ready false")
    if summary["row_bytes_claim"] is not False:
        failures.append("Phase 1 binding must not claim row bytes")

    seen_edges: set[str] = set()
    for binding in plan["bindings"]:
        edge_id = str(binding["edge_id"])
        if edge_id in seen_edges:
            failures.append(f"duplicate edge binding: {edge_id}")
        seen_edges.add(edge_id)
        if not binding["source_fiber_op_id"]:
            failures.append(f"binding missing FiberOp provenance: {binding}")
        if not binding["source_stream_action_id"]:
            failures.append(f"binding missing stream action provenance: {binding}")
        if not binding["recv_stream_action_id"]:
            failures.append(f"binding missing recv action id: {binding}")
        if not binding["update_stream_action_id"]:
            failures.append(f"binding missing update action id: {binding}")
        if not binding["route_recv_dependency_id"]:
            failures.append(f"binding missing route recv dependency id: {binding}")
        if binding["globalmax_representation"] != "replicated_vector":
            failures.append(f"V1 must use replicated vector GlobalMax: {binding}")
        if binding["lane_convention"] != "replicated_fp32_vector_all_lanes_equal":
            failures.append(f"unexpected lane convention: {binding}")
        if binding["inplace_update_policy"] != "forbidden":
            failures.append(f"V1 must be non-in-place: {binding}")
        if binding["subtask_slot"] != "log10max_ring_globalmax_update":
            failures.append(f"unexpected subtask slot: {binding}")
        if binding["src_current_operand"] != "globalmax_acc_in":
            failures.append(f"unexpected src_current operand: {binding}")
        if binding["src_received_operand"] != "globalmax_recv":
            failures.append(f"unexpected src_received operand: {binding}")
        if binding["dst_updated_operand"] != "globalmax_acc_out":
            failures.append(f"unexpected dst operand: {binding}")
        if binding["row_bytes_claim"] is not False:
            failures.append(f"binding must not claim row bytes: {binding}")

    if failures:
        print("stream compiler log10max ring update template binding check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max ring update template binding check OK")
    print(f"binding_count={summary['binding_count']}")
    print(f"blocker_ids={summary['blocker_ids']}")


if __name__ == "__main__":
    main()
