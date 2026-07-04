#!/usr/bin/env python3
"""Check Phase-1 log10max endpoint operand placeholders."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.log10max_ring_update_operands import (
    LOG10MAX_ENDPOINT_ALLOCATION_BLOCKER,
    build_log10max_endpoint_operand_placeholder_report,
    summarize_log10max_endpoint_operand_placeholder_report,
)


def main() -> None:
    report = build_log10max_endpoint_operand_placeholder_report()
    summary = summarize_log10max_endpoint_operand_placeholder_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    participating = plan["participating_pes"]
    consumers = plan["consumer_pes"]
    expected_count = len(participating) + len(consumers)

    if summary["participating_pe_count"] != len(participating):
        failures.append(f"participating PE count mismatch: {summary}")
    if summary["consumer_pe_count"] != len(consumers):
        failures.append(f"consumer PE count mismatch: {summary}")
    if summary["placeholder_count"] != expected_count:
        failures.append(f"endpoint count must derive from PE sets: {summary}")
    if summary["local_reduce_endpoint_placeholder_count"] != len(participating):
        failures.append(f"missing local_reduce endpoints: {summary}")
    if summary["max_with_floor_endpoint_placeholder_count"] != len(consumers):
        failures.append(f"missing max_with_floor endpoints: {summary}")
    if summary["blocker_ids"] != [LOG10MAX_ENDPOINT_ALLOCATION_BLOCKER]:
        failures.append(f"endpoint placeholders should stop at allocation: {summary}")
    if summary["runtime_ready"] is not False:
        failures.append("endpoint placeholders must not claim runtime_ready")
    if summary["component_integration_claim"] is not False:
        failures.append("endpoint placeholders must not claim component integration")

    placeholders = plan["placeholders"]
    ids: set[str] = set()
    local_by_pe: dict[str, dict[str, object]] = {}
    max_by_pe: dict[str, dict[str, object]] = {}
    for placeholder in placeholders:
        placeholder_id = str(placeholder["placeholder_id"])
        if placeholder_id in ids:
            failures.append(f"duplicate endpoint placeholder id: {placeholder_id}")
        ids.add(placeholder_id)
        if not placeholder_id.startswith("opnd:log10max:t"):
            failures.append(f"endpoint placeholder id must be deterministic: {placeholder}")
        if placeholder["value_kind"] != "replicated_vector":
            failures.append(f"endpoint value must be replicated vector: {placeholder}")
        if placeholder["dtype"] != "fp32":
            failures.append(f"endpoint dtype must be fp32: {placeholder}")
        if placeholder["alias_policy"] != "forbidden":
            failures.append(f"endpoint instruction aliasing must be forbidden: {placeholder}")
        if placeholder["allocation_required"] is not True:
            failures.append(f"endpoint placeholder must require allocation: {placeholder}")
        if placeholder["hardcoded_operand_idx_allowed"] is not False:
            failures.append(f"hardcoded endpoint operands are forbidden: {placeholder}")
        if placeholder["final_row_bytes_claim"] if "final_row_bytes_claim" in placeholder else False:
            failures.append(f"endpoint placeholder must not claim final bytes: {placeholder}")

        role = placeholder["role"]
        pe = str(placeholder["pe"])
        if role == "local_reduce_max_out":
            local_by_pe[pe] = placeholder
            if placeholder["producer_placeholder_ids"]:
                failures.append(f"local_reduce endpoint should allocate fresh: {placeholder}")
            if not placeholder["consumer_stream_action_ids"]:
                failures.append(f"local_reduce endpoint needs route/FMAX consumers: {placeholder}")
        elif role == "max_with_floor_globalmax_src":
            max_by_pe[pe] = placeholder
            if len(placeholder["producer_placeholder_ids"]) != 1:
                failures.append(f"max_with_floor endpoint needs final acc_out producer: {placeholder}")
            if not placeholder["consumer_stream_action_ids"]:
                failures.append(f"max_with_floor endpoint needs consumer action: {placeholder}")
        else:
            failures.append(f"unexpected endpoint role: {placeholder}")

    if set(local_by_pe) != set(participating):
        failures.append("local_reduce endpoint PE set must match participating PE set")
    if set(max_by_pe) != set(consumers):
        failures.append("max_with_floor endpoint PE set must match consumer PE set")

    if failures:
        print("stream compiler log10max endpoint operand placeholder check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max endpoint operand placeholder check OK")
    print(f"placeholder_count={summary['placeholder_count']}")
    print(f"blocker_ids={summary['blocker_ids']}")


if __name__ == "__main__":
    main()
