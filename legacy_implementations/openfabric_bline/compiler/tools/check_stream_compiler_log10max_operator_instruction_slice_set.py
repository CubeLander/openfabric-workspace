#!/usr/bin/env python3
"""Check Phase-5A log10max operator instruction slice set."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.log10max_operator_payload import (
    EXPECTED_LOG10MAX_ROW_FAMILIES,
    EXPECTED_LOG10MAX_SEMANTIC_OPS,
    LOG10MAX_OPERATOR_SLICE_SET_PARTIAL,
    SEMANTIC_OPS_BY_SLICE,
    build_log10max_operator_instruction_slice_set,
    summarize_log10max_operator_instruction_slice_set,
)


EXPECTED_PRESENT = ("route_copy", "ring_fmax_update")
EXPECTED_BLOCKED = tuple(
    family
    for family in EXPECTED_LOG10MAX_ROW_FAMILIES
    if family not in EXPECTED_PRESENT
)
EXPECTED_MISSING_SEMANTIC_OPS = tuple(
    op
    for op in EXPECTED_LOG10MAX_SEMANTIC_OPS
    if op
    not in (
        *SEMANTIC_OPS_BY_SLICE["route_copy"],
        *SEMANTIC_OPS_BY_SLICE["ring_fmax_update"],
    )
)


def main() -> None:
    report = build_log10max_operator_instruction_slice_set()
    summary = summarize_log10max_operator_instruction_slice_set(report)
    plan = report.to_plan()
    failures: list[str] = []

    if tuple(summary["expected_row_families"]) != EXPECTED_LOG10MAX_ROW_FAMILIES:
        failures.append(f"expected row families mismatch: {summary}")
    if tuple(summary["present_row_families"]) != EXPECTED_PRESENT:
        failures.append(f"route_copy should be the only present slice: {summary}")
    if tuple(summary["folded_row_families"]) != ():
        failures.append(f"no folded slices should be claimed yet: {summary}")
    if tuple(summary["missing_row_families"]) != EXPECTED_BLOCKED:
        failures.append(f"non-route slices must be missing: {summary}")
    if tuple(summary["blocked_row_families"]) != EXPECTED_BLOCKED:
        failures.append(f"non-route slices must be blocked: {summary}")
    expected_covered = (
        *SEMANTIC_OPS_BY_SLICE["route_copy"],
        *SEMANTIC_OPS_BY_SLICE["ring_fmax_update"],
    )
    if tuple(summary["covered_semantic_ops"]) != expected_covered:
        failures.append(f"unexpected covered semantic ops: {summary}")
    if tuple(summary["missing_semantic_ops"]) != EXPECTED_MISSING_SEMANTIC_OPS:
        failures.append(f"missing semantic ops mismatch: {summary}")
    if summary["duplicate_semantic_ops"] != []:
        failures.append(f"duplicate semantic ops forbidden: {summary}")
    if summary["slice_set_status"] != "partial":
        failures.append(f"slice set must remain partial: {summary}")
    if summary["slice_count"] != len(EXPECTED_LOG10MAX_ROW_FAMILIES):
        failures.append(f"slice count mismatch: {summary}")
    if summary["slice_status_counts"] != {"blocked": 5, "present": 2}:
        failures.append(f"unexpected slice status counts: {summary}")
    if summary["byte_status_counts"] != {"blocked": 5, "copied_from_candidate": 2}:
        failures.append(f"unexpected byte status counts: {summary}")
    if summary["placement_status_counts"] != {"blocked": 5, "placed": 2}:
        failures.append(f"unexpected placement status counts: {summary}")
    if summary["row_counts_by_family"].get("route_copy") != 120:
        failures.append(f"route_copy row count must be 120: {summary}")
    if summary["row_counts_by_family"].get("ring_fmax_update") != 30:
        failures.append(f"ring_fmax_update row count must be 30: {summary}")
    for family in EXPECTED_BLOCKED:
        if summary["row_counts_by_family"].get(family) != 0:
            failures.append(f"{family} must have zero rows: {summary}")
        blocker = f"log10max_operator_slice_{family}_missing"
        if blocker not in summary["blocker_ids"]:
            failures.append(f"missing blocker {blocker}: {summary}")
    for op in EXPECTED_MISSING_SEMANTIC_OPS:
        blocker = f"log10max_semantic_op_{op}_missing"
        if blocker not in summary["blocker_ids"]:
            failures.append(f"missing semantic blocker {blocker}: {summary}")
    if LOG10MAX_OPERATOR_SLICE_SET_PARTIAL not in summary["blocker_ids"]:
        failures.append(f"partial slice-set blocker missing: {summary}")
    if summary["runtime_ready"] is not False or summary["uploadable"] is not False:
        failures.append(f"slice set must not claim readiness: {summary}")

    slices = {str(item["slice_kind"]): item for item in plan["slices"]}
    if set(slices) != set(EXPECTED_LOG10MAX_ROW_FAMILIES):
        failures.append(f"slice records must cover all families: {slices}")
    route = slices.get("route_copy")
    if route is None:
        failures.append("route_copy slice missing")
    else:
        if route["slice_status"] != "present":
            failures.append(f"route_copy must be present: {route}")
        if route["covered_semantic_ops"] != ["route_globalmax_copy"]:
            failures.append(f"route_copy covered ops mismatch: {route}")
        if route["row_count"] != 120:
            failures.append(f"route_copy row count mismatch: {route}")
        if route["byte_status"] != "copied_from_candidate":
            failures.append(f"route_copy bytes must be copied: {route}")
        if route["placement_status"] != "placed":
            failures.append(f"route_copy must be placed: {route}")
        if route["slice_sha256"] is None:
            failures.append(f"route_copy slice sha missing: {route}")
        if not route["layout_epoch"] or not route["layout_plan_sha256"]:
            failures.append(f"route_copy layout identity missing: {route}")
        if route["blocker_ids"] != []:
            failures.append(f"route_copy should have no per-slice blockers: {route}")
    fmax = slices.get("ring_fmax_update")
    if fmax is None:
        failures.append("ring_fmax_update slice missing")
    else:
        if fmax["slice_status"] != "present":
            failures.append(f"ring_fmax_update must be present: {fmax}")
        if fmax["covered_semantic_ops"] != ["max_update_global_max"]:
            failures.append(f"ring_fmax_update covered ops mismatch: {fmax}")
        if fmax["row_count"] != 30:
            failures.append(f"ring_fmax_update row count mismatch: {fmax}")
        if fmax["byte_status"] != "copied_from_candidate":
            failures.append(f"ring_fmax_update bytes must be copied: {fmax}")
        if fmax["placement_status"] != "placed":
            failures.append(f"ring_fmax_update must be placed: {fmax}")
        if fmax["slice_sha256"] is None:
            failures.append(f"ring_fmax_update slice sha missing: {fmax}")
        if not fmax["layout_epoch"] or not fmax["layout_plan_sha256"]:
            failures.append(f"ring_fmax_update layout identity missing: {fmax}")
        if route is not None and (
            fmax["layout_epoch"] != route["layout_epoch"]
            or fmax["layout_plan_sha256"] != route["layout_plan_sha256"]
        ):
            failures.append(f"ring_fmax_update layout must match route: {fmax}")
        if fmax["blocker_ids"] != []:
            failures.append(f"ring_fmax_update should have no slice blockers: {fmax}")
    for family in EXPECTED_BLOCKED:
        item = slices[family]
        if item["slice_status"] != "blocked":
            failures.append(f"{family} must be blocked: {item}")
        if item["covered_semantic_ops"] != []:
            failures.append(f"{family} must not cover semantic ops while blocked: {item}")
        if item["row_count"] != 0:
            failures.append(f"{family} must have zero rows while blocked: {item}")
        if item["slice_sha256"] is not None:
            failures.append(f"{family} must not have slice sha: {item}")
        if item["blocker_ids"] != [f"log10max_operator_slice_{family}_missing"]:
            failures.append(f"{family} blocker mismatch: {item}")

    if failures:
        print("stream compiler log10max operator instruction slice set check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max operator instruction slice set check OK")
    print(f"slice_set_status={summary['slice_set_status']}")
    print(f"present_row_families={summary['present_row_families']}")
    print(f"missing_row_families={summary['missing_row_families']}")
    print(f"missing_semantic_ops={summary['missing_semantic_ops']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


if __name__ == "__main__":
    main()
