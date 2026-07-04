#!/usr/bin/env python3
"""Check Phase-1 log10max ring update operand placeholders."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.log10max_ring_update_operands import (
    EXPECTED_PHASE_PLACEHOLDER_COUNTS,
    build_log10max_ring_update_operand_placeholder_report,
    summarize_log10max_ring_update_operand_placeholder_report,
)


def main() -> None:
    report = build_log10max_ring_update_operand_placeholder_report()
    summary = summarize_log10max_ring_update_operand_placeholder_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["placeholder_count"] != 90:
        failures.append(f"expected 90 placeholders: {summary}")
    if summary["role_counts"] != {
        "globalmax_acc_in": 30,
        "globalmax_acc_out": 30,
        "globalmax_recv": 30,
    }:
        failures.append(f"unexpected role counts: {summary}")
    if summary["phase_placeholder_counts"] != EXPECTED_PHASE_PLACEHOLDER_COUNTS:
        failures.append(f"unexpected phase distribution: {summary}")
    if summary["owner_scope_counts"] != {"task_pe": 90}:
        failures.append(f"unexpected owner scope: {summary}")
    if summary["producer_linked_placeholder_count"] < 30:
        failures.append(f"expected producer links for recv/out placeholders: {summary}")
    if summary["consumer_linked_placeholder_count"] != 90:
        failures.append(f"every placeholder should have a consumer link: {summary}")
    if summary["blocker_ids"] != ["log10max_ring_update_operand_allocation_missing"]:
        failures.append(f"unexpected blockers: {summary}")
    if summary["runtime_ready"] is not False:
        failures.append("placeholder report must not claim runtime_ready")

    seen: set[str] = set()
    by_row: dict[str, list[dict[str, object]]] = {}
    for placeholder in plan["placeholders"]:
        placeholder_id = str(placeholder["placeholder_id"])
        if placeholder_id in seen:
            failures.append(f"duplicate placeholder id: {placeholder_id}")
        seen.add(placeholder_id)
        if not placeholder_id.startswith("opnd:log10max:"):
            failures.append(f"placeholder id must be deterministic: {placeholder_id}")
        if placeholder["alias_policy"] != "forbidden":
            failures.append(f"unexpected alias policy: {placeholder}")
        if placeholder["allocation_status"] != "unallocated":
            failures.append(f"placeholder must remain unallocated: {placeholder}")
        if placeholder["blockers"] != ["log10max_ring_update_operand_allocation_missing"]:
            failures.append(f"unexpected placeholder blockers: {placeholder}")
        if not placeholder["source_ring_edge_id"]:
            failures.append(f"missing ring edge provenance: {placeholder}")
        if not placeholder["source_stream_action_id"]:
            failures.append(f"missing stream action provenance: {placeholder}")
        by_row.setdefault(str(placeholder["source_binary_row_candidate_id"]), []).append(
            placeholder
        )

    for row_id, placeholders in by_row.items():
        roles = sorted(str(placeholder["role"]) for placeholder in placeholders)
        if roles != ["globalmax_acc_in", "globalmax_acc_out", "globalmax_recv"]:
            failures.append(f"row {row_id} must have exactly three roles: {roles}")

    if failures:
        print("stream compiler log10max ring update placeholders check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max ring update placeholders check OK")
    print(f"placeholder_count={summary['placeholder_count']}")
    print(f"blocker_ids={summary['blocker_ids']}")


if __name__ == "__main__":
    main()
