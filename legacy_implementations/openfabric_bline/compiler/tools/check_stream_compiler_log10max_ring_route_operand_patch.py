#!/usr/bin/env python3
"""Check report-only GlobalMax route operand patch continuity."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.log10max_ring_update_operands import (
    LOG10MAX_RING_ROUTE_LOCAL_REDUCE_BLOCKER,
    LOG10MAX_RING_UPDATE_COMPONENT_BLOCKER,
    LOG10MAX_ROUTE_ROW_BYTES_BLOCKER,
    build_log10max_ring_route_operand_patch_report,
    summarize_log10max_ring_route_operand_patch_report,
)


def main() -> None:
    report = build_log10max_ring_route_operand_patch_report()
    summary = summarize_log10max_ring_route_operand_patch_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["patch_count"] != 60:
        failures.append(f"expected 60 route patches: {summary}")
    if summary["direction_counts"] != {"push": 30, "recv": 30}:
        failures.append(f"unexpected route direction counts: {summary}")
    if summary["patch_status_counts"] != {"patched": 60}:
        failures.append(f"all route operand patches should be allocation-backed: {summary}")
    if LOG10MAX_RING_ROUTE_LOCAL_REDUCE_BLOCKER in summary["blocker_ids"]:
        failures.append(f"local-reduce route source blocker should be cleared: {summary}")
    if LOG10MAX_ROUTE_ROW_BYTES_BLOCKER not in summary["blocker_ids"]:
        failures.append(f"route row bytes blocker must remain: {summary}")
    if LOG10MAX_RING_UPDATE_COMPONENT_BLOCKER not in summary["blocker_ids"]:
        failures.append(f"component integration blocker must remain: {summary}")
    if summary["runtime_ready"] is not False:
        failures.append("route operand patch report must not claim runtime_ready")
    if summary["final_row_bytes_claim"] is not False:
        failures.append("route operand patch report must not claim final row bytes")
    if summary["component_integration_claim"] is not False:
        failures.append("route operand patch report must not claim component integration")

    recv_patched = 0
    push_sourced_from_local_reduce = 0
    push_with_allocated_source = 0
    for patch in plan["patches"]:
        if patch["final_row_bytes_claim"] is not False:
            failures.append(f"route patch must not claim final bytes: {patch}")
        if patch["runtime_ready"] is not False:
            failures.append(f"route patch must not claim runtime_ready: {patch}")
        if patch["direction"] == "recv":
            if len(patch["dst_placeholders"]) != 1:
                failures.append(f"recv must bind one dst placeholder: {patch}")
            if not str(patch["dst_placeholders"][0]).endswith(":globalmax_recv"):
                failures.append(f"recv must target globalmax_recv: {patch}")
            if len(patch["allocation_ids"]) != 1:
                failures.append(f"recv must reference one allocation: {patch}")
            if patch["patch_status"] != "patched":
                failures.append(f"recv patch should be allocation-backed: {patch}")
            if patch["scope_status"] != "receiver_task_pe":
                failures.append(f"recv patch must use receiver task_pe scope: {patch}")
            if patch["allocation_scope"] != patch["expected_allocation_scope"]:
                failures.append(f"recv allocation scope mismatch: {patch}")
            if patch["dst_operands_idx"][0] == 0:
                failures.append(
                    "recv dst0 uses operand index 0; this is legal only if "
                    f"explicitly allocated, inspect patch: {patch}"
                )
            recv_patched += 1
        elif patch["direction"] == "push":
            if LOG10MAX_RING_ROUTE_LOCAL_REDUCE_BLOCKER in patch["blockers"]:
                failures.append(f"local-reduce push source must now be allocated: {patch}")
            else:
                push_with_allocated_source += 1
                if len(patch["src_placeholders"]) != 1:
                    failures.append(f"push must bind one src placeholder: {patch}")
                src_placeholder = str(patch["src_placeholders"][0])
                if src_placeholder.endswith(":local_reduce_max_out"):
                    push_sourced_from_local_reduce += 1
                elif not src_placeholder.endswith(":globalmax_acc_out"):
                    failures.append(
                        "push must source local_reduce_max_out or previous acc_out: "
                        f"{patch}"
                    )
                if len(patch["allocation_ids"]) != 1:
                    failures.append(f"push must reference one allocation: {patch}")
                if patch["patch_status"] != "patched":
                    failures.append(f"push patch should be allocation-backed: {patch}")
                if patch["scope_status"] != "sender_task_pe":
                    failures.append(f"push patch must use sender task_pe scope: {patch}")
                if patch["allocation_scope"] != patch["expected_allocation_scope"]:
                    failures.append(f"push allocation scope mismatch: {patch}")
        else:
            failures.append(f"unexpected route direction: {patch}")

    if recv_patched != 30:
        failures.append(f"expected 30 recv patches, got {recv_patched}")
    if push_sourced_from_local_reduce <= 0:
        failures.append("expected at least one initial push sourced from local_reduce")
    if push_with_allocated_source != 30:
        failures.append(f"expected 30 allocation-backed push patches, got {push_with_allocated_source}")

    if failures:
        print("stream compiler log10max ring route operand patch check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max ring route operand patch check OK")
    print(f"patch_count={summary['patch_count']}")
    print(f"blocker_ids={summary['blocker_ids']}")


if __name__ == "__main__":
    main()
