#!/usr/bin/env python3
"""Check Phase-5C log10max operator control coherence candidate."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.log10max_operator_payload import (
    LOG10MAX_OPERATOR_CONTROL_COHERENCE_BLOCKED,
    build_log10max_operator_control_coherence_report,
    summarize_log10max_operator_control_coherence_report,
)


def main() -> None:
    report = build_log10max_operator_control_coherence_report()
    summary = summarize_log10max_operator_control_coherence_report(report)
    failures: list[str] = []

    if summary["coherence_scope"] != "full_operator":
        failures.append(f"coherence scope must be full_operator: {summary}")
    if summary["coherence_status"] != "blocked":
        failures.append(f"full-operator coherence must remain blocked: {summary}")
    if summary["runtime_ready"] is not False or summary["uploadable"] is not False:
        failures.append(f"readiness claims forbidden: {summary}")
    if summary["source_micc_candidate_id"] is not None:
        failures.append(f"MICC candidate should be absent: {summary}")
    if summary["source_exeblock_component_id"] is not None:
        failures.append(f"exeBlock component should be absent: {summary}")
    if summary["source_instance_component_id"] is not None:
        failures.append(f"instance component should be absent: {summary}")
    statuses = summary["status_by_check"]
    expected_blocked = {
        "insts_component_status",
        "micc_candidate_status",
        "exeblock_component_status",
        "instance_component_status",
        "stage_start_pc_status",
        "stage_instruction_count_status",
        "stage_pc_within_pe_local_inst_rows_status",
        "active_exeblock_points_to_owned_rows_status",
        "end_inst_boundary_status",
        "successor_predecessor_status",
        "root_reachability_status",
        "task_subtask_stamp_status",
        "instance_base_addr_status",
    }
    for key in expected_blocked:
        if statuses.get(key) != "blocked":
            failures.append(f"{key} must be blocked: {summary}")
    expected_blockers = {
        LOG10MAX_OPERATOR_CONTROL_COHERENCE_BLOCKED,
        "log10max_control_coherence_component_partial",
        "log10max_control_coherence_micc_candidate_missing",
        "log10max_control_coherence_exeblock_component_missing",
        "log10max_control_coherence_instance_component_missing",
    }
    if not expected_blockers.issubset(set(summary["blocker_ids"])):
        failures.append(f"control coherence blockers missing: {summary}")

    if failures:
        print("stream compiler log10max operator control coherence check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max operator control coherence check OK")
    print(f"coherence_scope={summary['coherence_scope']}")
    print(f"coherence_status={summary['coherence_status']}")
    print(f"blocker_ids={summary['blocker_ids']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


if __name__ == "__main__":
    main()
