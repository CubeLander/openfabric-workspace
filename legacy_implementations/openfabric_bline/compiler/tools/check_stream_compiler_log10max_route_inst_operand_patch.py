#!/usr/bin/env python3
"""Check Phase-2B log10max route physical row operand patches."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.log10max_route_inst_fields import (
    EXPECTED_PHYSICAL_PHASE_COUNTS,
    LANE_STRIDE_OPERANDS,
    PHYSICAL_ROWS_PER_LOGICAL_EDGE,
    build_log10max_route_inst_operand_patch_report,
    build_log10max_route_physical_row_plan_report,
    summarize_log10max_route_inst_operand_patch_report,
)


def main() -> None:
    physical_report = build_log10max_route_physical_row_plan_report()
    patch_report = build_log10max_route_inst_operand_patch_report(physical_report)
    summary = summarize_log10max_route_inst_operand_patch_report(patch_report)
    plan_by_id = {
        plan.physical_row_plan_id: plan for plan in physical_report.plans
    }
    failures: list[str] = []

    if summary["logical_route_edge_count"] != 30:
        failures.append(f"expected 30 logical route edges: {summary}")
    if summary["patch_count"] != 30 * PHYSICAL_ROWS_PER_LOGICAL_EDGE:
        failures.append(f"expected 120 physical route patches: {summary}")
    if summary["phase_counts"] != EXPECTED_PHYSICAL_PHASE_COUNTS:
        failures.append(f"unexpected phase distribution: {summary}")
    if summary["patch_status_counts"] != {"patched": 120}:
        failures.append(f"all physical route operand patches should bind: {summary}")
    if summary["serializer_allocation_claim_count"] != 0:
        failures.append(f"serializer must not allocate operands: {summary}")
    if summary["final_component_claim_count"] != 0:
        failures.append(f"patches must not claim final component rows: {summary}")
    if summary["runtime_ready"] is not False or summary["uploadable"] is not False:
        failures.append(f"route operand patch report must stay non-ready: {summary}")

    for patch in patch_report.patches:
        plan = plan_by_id.get(patch.physical_row_plan_id)
        if plan is None:
            failures.append(f"patch references missing physical row plan: {patch}")
            continue
        expected_src = (
            plan.src_operand_idx_before_lane_delta
            + patch.lane_index * LANE_STRIDE_OPERANDS
        )
        expected_dst = (
            plan.dst_operand_idx_before_lane_delta
            + patch.lane_index * LANE_STRIDE_OPERANDS
        )
        usage = dict(patch.operand_field_usage)
        if patch.src_operands_idx[0] != expected_src:
            failures.append(f"src lane continuity mismatch: {patch}")
        if patch.dst_operands_idx[0] != expected_dst:
            failures.append(f"dst lane continuity mismatch: {patch}")
        if patch.src_operands_idx[1:] != (0, 0):
            failures.append(f"unused src fields should be zero-filled: {patch}")
        if patch.dst_operands_idx[1:] != (0, 0):
            failures.append(f"unused dst fields should be zero-filled: {patch}")
        for field in ("src1", "src2", "dst1", "dst2"):
            if not str(usage.get(field, "")).startswith("unused_zero_fill"):
                failures.append(f"{field} needs explicit usage-mask evidence: {patch}")
        if patch.serializer_allocation_claim:
            failures.append(f"serializer allocation claim forbidden: {patch}")
        if patch.final_component_claim:
            failures.append(f"final component claim forbidden: {patch}")
        if patch.runtime_ready or patch.uploadable:
            failures.append(f"route patch must not claim readiness: {patch}")

    if failures:
        print("stream compiler log10max route inst operand patch check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max route inst operand patch check OK")
    print(f"patch_count={summary['patch_count']}")
    print(f"phase_counts={summary['phase_counts']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


if __name__ == "__main__":
    main()
