#!/usr/bin/env python3
"""Check Phase-1 log10max route/update layout reports."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.log10max_route_layout_plan import (
    COMPONENT_PLACEMENT_BLOCKER,
    FMAX_COMPONENT_BLOCKER,
    FMAX_LAYOUT_BLOCKER,
    PHASE_ORDER,
    ROUTE_COMPONENT_BLOCKER,
    ROUTE_EXE_BLOCK_BLOCKER,
    ROUTE_FLOW_ACK_BLOCKER,
    ROUTE_LAYOUT_BLOCKER,
    ROUTE_ROW_BYTES_BLOCKER,
    build_log10max_route_layout_plan_report,
    summarize_log10max_route_layout_plan_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_ring_update_operands import (
    EXPECTED_PHASE_COUNTS,
)


def main() -> None:
    report = build_log10max_route_layout_plan_report()
    summary = summarize_log10max_route_layout_plan_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["instruction_layout_plan_count"] != 90:
        failures.append(f"expected 90 layout plans: {summary}")
    if summary["route_candidate_count"] != 60:
        failures.append(f"expected 60 route candidates: {summary}")
    if summary["fmax_update_candidate_count"] != 30:
        failures.append(f"expected 30 FMAX update candidates: {summary}")
    if summary["stage_counts"] != {"CAL": 30, "FLOW": 60}:
        failures.append(f"unexpected stage counts: {summary}")
    if summary["phase_counts"] != {phase: count * 3 for phase, count in EXPECTED_PHASE_COUNTS.items()}:
        failures.append(f"unexpected phase distribution: {summary}")
    if summary["placement_status_counts"] != {"unplaced_candidate": 90}:
        failures.append(f"Phase 1 must leave all rows unplaced: {summary}")
    if summary["ordering_status_counts"].get("blocked", 0) != 0:
        failures.append(f"ordering_status must fail closed if blocked: {summary}")
    if summary["runtime_ready"] is not False:
        failures.append("Phase 1 layout report must keep runtime_ready false")
    if summary["uploadable"] is not False:
        failures.append("Phase 1 layout report must keep uploadable false")
    if summary["raw_row_bytes_claim"] is not False:
        failures.append("Phase 1 layout report must not claim raw row bytes")
    if summary["component_integration_claim"] is not False:
        failures.append("Phase 1 layout report must not claim component integration")
    for blocker in (
        ROUTE_LAYOUT_BLOCKER,
        ROUTE_FLOW_ACK_BLOCKER,
        ROUTE_ROW_BYTES_BLOCKER,
        FMAX_LAYOUT_BLOCKER,
        FMAX_COMPONENT_BLOCKER,
        ROUTE_EXE_BLOCK_BLOCKER,
        COMPONENT_PLACEMENT_BLOCKER,
        ROUTE_COMPONENT_BLOCKER,
    ):
        if blocker not in summary["blocker_ids"]:
            failures.append(f"expected blocker {blocker}: {summary}")

    layout_by_row: dict[str, dict[str, object]] = {}
    for layout in plan["instruction_layout_plans"]:
        if layout["runtime_ready"] is not False:
            failures.append(f"layout must not claim runtime_ready: {layout}")
        if layout["raw_row_bytes_claim"] is not False:
            failures.append(f"layout must not claim raw row bytes: {layout}")
        if layout["component_integration_claim"] is not False:
            failures.append(f"layout must not claim component integration: {layout}")
        if layout["local_pc"] is not None:
            failures.append(f"local_pc must remain pending in Phase 1: {layout}")
        if layout["layout_status"] != "planned":
            failures.append(f"layout_status must remain planned: {layout}")
        if layout["ordering_status"] == "blocked":
            failures.append(f"ordering must not be blocked: {layout}")
        for row_id in layout["row_candidate_ids"]:
            if row_id in layout_by_row:
                failures.append(f"duplicate layout row id: {row_id}")
            layout_by_row[str(row_id)] = layout
        row_id = str(layout["row_candidate_ids"][0])
        if row_id.startswith("route_row_candidate:"):
            if layout["stage"] != "FLOW":
                failures.append(f"route rows must default to FLOW: {layout}")
            if ROUTE_ROW_BYTES_BLOCKER not in layout["blocker_ids"]:
                failures.append(f"route row bytes blocker must remain: {layout}")
        elif row_id.startswith("binary_layout_row_candidate:"):
            if layout["stage"] != "CAL":
                failures.append(f"FMAX update rows should be CAL with proof: {layout}")
            if layout["ordering_predecessor_row_ids"] == []:
                failures.append(f"FMAX update must depend on route_recv: {layout}")
            if FMAX_COMPONENT_BLOCKER not in layout["blocker_ids"]:
                failures.append(f"FMAX component blocker must remain: {layout}")
        else:
            failures.append(f"unexpected row candidate id: {layout}")

    for layout in plan["instruction_layout_plans"]:
        row_id = str(layout["row_candidate_ids"][0])
        if not row_id.startswith("binary_layout_row_candidate:"):
            continue
        edge_id = _edge_id_from_update_row(row_id)
        recv_row = f"route_row_candidate:recv:{edge_id}"
        if recv_row not in layout["ordering_predecessor_row_ids"]:
            failures.append(
                "FMAX update must explicitly depend on matching route_recv: "
                f"{layout}"
            )
        if recv_row not in layout_by_row:
            failures.append(f"missing recv layout for {row_id}")

    for layout in plan["instruction_layout_plans"]:
        row_id = str(layout["row_candidate_ids"][0])
        if not row_id.startswith("route_row_candidate:push:"):
            continue
        predecessor_ids = layout["ordering_predecessor_row_ids"]
        if predecessor_ids:
            predecessor = str(predecessor_ids[0])
            if not predecessor.startswith("binary_layout_row_candidate:"):
                failures.append(f"next push predecessor must be FMAX update: {layout}")
            if predecessor not in layout_by_row:
                failures.append(f"next push predecessor row missing: {layout}")

    for exe_block in plan["exe_block_writer_plans"]:
        if exe_block["runtime_ready"] is not False:
            failures.append(f"exeBlock plan must not claim runtime_ready: {exe_block}")
        if exe_block["component_integration_claim"] is not False:
            failures.append(f"exeBlock plan must not claim integration: {exe_block}")
        if exe_block["writer_status"] != "planned":
            failures.append(f"writer_status must remain planned: {exe_block}")
        counts = exe_block["stage_instruction_counts"]
        starts = exe_block["stage_start_pc"]
        if set(counts) != {"LD", "CAL", "FLOW", "ST"}:
            failures.append(f"stage counts must cover LD/CAL/FLOW/ST: {exe_block}")
        if set(starts) != {"LD", "CAL", "FLOW", "ST"}:
            failures.append(f"stage start PC must cover LD/CAL/FLOW/ST: {exe_block}")
        if ROUTE_EXE_BLOCK_BLOCKER not in exe_block["blocker_ids"]:
            failures.append(f"exeBlock MICC blocker must remain: {exe_block}")

    for boundary in plan["instruction_boundary_plans"]:
        if boundary["runtime_ready"] is not False:
            failures.append(f"boundary plan must not claim runtime_ready: {boundary}")
        if boundary["component_integration_claim"] is not False:
            failures.append(f"boundary plan must not claim integration: {boundary}")
        if boundary["boundary_status"] != "bound":
            failures.append(f"boundary plan should be candidate-bound: {boundary}")
        end_map = boundary["end_inst_by_row_candidate_id"]
        if len([row_id for row_id, is_end in end_map.items() if is_end]) != 1:
            failures.append(f"exactly one end_inst row per boundary plan: {boundary}")

    for placement in plan["component_placement_plans"]:
        if placement["runtime_ready"] is not False:
            failures.append(f"placement must not claim runtime_ready: {placement}")
        if placement["component_integration_claim"] is not False:
            failures.append(f"placement must not claim integration: {placement}")
        if placement["placement_status"] != "unplaced_candidate":
            failures.append(f"Phase 1 placement must remain unplaced: {placement}")
        if placement["component_byte_offset"] is not None:
            failures.append(f"unplaced placement must not have byte offset: {placement}")
        if placement["pe_local_pc"] != -1 or placement["global_row_index"] != -1:
            failures.append(f"unplaced placement must keep pc/index sentinels: {placement}")
        if COMPONENT_PLACEMENT_BLOCKER not in placement["blocker_ids"]:
            failures.append(f"component placement blocker must remain: {placement}")

    if failures:
        print("stream compiler log10max route layout plan check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max route layout plan check OK")
    print(f"instruction_layout_plan_count={summary['instruction_layout_plan_count']}")
    print(f"exe_block_writer_plan_count={summary['exe_block_writer_plan_count']}")
    print(f"component_placement_plan_count={summary['component_placement_plan_count']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


def _edge_id_from_update_row(row_id: str) -> str:
    marker = "ring_edge:"
    return row_id[row_id.index(marker):]


if __name__ == "__main__":
    main()
