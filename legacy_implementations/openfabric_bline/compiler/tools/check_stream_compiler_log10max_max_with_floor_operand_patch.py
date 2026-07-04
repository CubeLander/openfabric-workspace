#!/usr/bin/env python3
"""Check report-only max_with_floor GlobalMax source operand patches."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.log10max_ring_update_operands import (
    LOG10MAX_COMPONENT_INTEGRATION_BLOCKER,
    LOG10MAX_MAX_WITH_FLOOR_CONSTANTS_DEFERRED_BLOCKER,
    LOG10MAX_MAX_WITH_FLOOR_LOG_SPEC_DEFERRED_BLOCKER,
    LOG10MAX_MAX_WITH_FLOOR_OUTPUT_DEFERRED_BLOCKER,
    LOG10MAX_MAX_WITH_FLOOR_ROW_BYTES_BLOCKER,
    build_log10max_max_with_floor_operand_patch_report,
    build_log10max_unified_operand_allocation_report,
    build_log10max_ring_update_operand_allocation_report,
    build_log10max_ring_update_operand_placeholder_report,
    summarize_log10max_max_with_floor_operand_patch_report,
)


EXPECTED_DEFERRED_BLOCKERS = {
    LOG10MAX_MAX_WITH_FLOOR_LOG_SPEC_DEFERRED_BLOCKER,
    LOG10MAX_MAX_WITH_FLOOR_CONSTANTS_DEFERRED_BLOCKER,
    LOG10MAX_MAX_WITH_FLOOR_OUTPUT_DEFERRED_BLOCKER,
    LOG10MAX_MAX_WITH_FLOOR_ROW_BYTES_BLOCKER,
    LOG10MAX_COMPONENT_INTEGRATION_BLOCKER,
}


def main() -> None:
    placeholder_report = build_log10max_ring_update_operand_placeholder_report()
    _ring_only_allocation_report = build_log10max_ring_update_operand_allocation_report(
        placeholder_report
    )
    allocation_report = build_log10max_unified_operand_allocation_report()
    patch_report = build_log10max_max_with_floor_operand_patch_report()
    summary = summarize_log10max_max_with_floor_operand_patch_report(patch_report)
    placeholder_plan = placeholder_report.to_plan()
    allocation_plan = allocation_report.to_plan()
    plan = patch_report.to_plan()
    failures: list[str] = []

    final_acc_out_placeholders = {
        placeholder["placeholder_id"]: placeholder
        for placeholder in placeholder_plan["placeholders"]
        if placeholder["role"] == "globalmax_acc_out"
        and any(
            str(consumer).startswith("max_with_floor_tile:")
            for consumer in placeholder["consumer_stream_action_ids"]
        )
    }
    allocations = {
        allocation["placeholder_id"]: allocation
        for allocation in allocation_plan["allocations"]
    }

    if summary["patch_count"] != len(final_acc_out_placeholders):
        failures.append(
            "max_with_floor patch count should match final acc_out consumer set: "
            f"{summary}, expected={len(final_acc_out_placeholders)}"
        )
    if summary["patch_count"] != 16:
        failures.append(f"expected current 4x4 ring to produce 16 patches: {summary}")
    if summary["consumer_pe_count"] != 16:
        failures.append(f"expected 16 consumer PEs: {summary}")
    if summary["globalmax_source_patch_status_counts"] != {"patched": 16}:
        failures.append(f"all GlobalMax source patches must be patched: {summary}")
    if summary["value_identity_reuse_count"] != 16:
        failures.append(f"all patches must use value identity reuse: {summary}")
    if summary["globalmax_source_allocation_claim"] is not True:
        failures.append(f"GlobalMax source allocation should be proven: {summary}")
    if "log10max_max_with_floor_globalmax_operand_allocation_missing" in summary[
        "blocker_ids"
    ]:
        failures.append(f"GlobalMax source allocation blocker should be cleared: {summary}")
    if not EXPECTED_DEFERRED_BLOCKERS.issubset(set(summary["blocker_ids"])):
        failures.append(f"expected deferred row/component blockers: {summary}")
    if summary["postprocess_completion_claim"] is not False:
        failures.append("must not claim full max_with_floor postprocess completion")
    if summary["final_row_bytes_claim"] is not False:
        failures.append("must not claim final max_with_floor row bytes")
    if summary["component_integration_claim"] is not False:
        failures.append("must not claim component integration")
    if summary["runtime_ready"] is not False:
        failures.append("must not claim runtime_ready")

    seen_consumers: set[str] = set()
    for patch in plan["patches"]:
        producer_id = patch["producer_placeholder_id"]
        consumer_id = patch["consumer_placeholder_id"]
        if producer_id not in final_acc_out_placeholders:
            failures.append(f"patch producer is not final acc_out: {patch}")
            continue
        if producer_id not in allocations:
            failures.append(f"missing producer allocation: {patch}")
            continue
        if consumer_id not in allocations:
            failures.append(f"missing consumer endpoint allocation: {patch}")
            continue
        producer_allocation = allocations[producer_id]
        consumer_allocation = allocations[consumer_id]
        if patch["allocation_id"] != consumer_allocation["allocation_id"]:
            failures.append(f"consumer allocation id mismatch: {patch}")
        if patch["producer_allocation_id"] != producer_allocation["allocation_id"]:
            failures.append(f"producer allocation id mismatch: {patch}")
        if consumer_allocation["allocation_kind"] != "value_identity_reuse":
            failures.append(f"consumer endpoint must value-reuse producer: {patch}")
        if consumer_allocation["producer_allocation_ids"] != [
            producer_allocation["allocation_id"]
        ]:
            failures.append(f"consumer endpoint producer allocation mismatch: {patch}")
        if patch["operand_idx"] != consumer_allocation["operand_idx"]:
            failures.append(f"operand_idx mismatch: {patch}")
        if patch["operand_idx"] != producer_allocation["operand_idx"]:
            failures.append(f"producer/consumer operand_idx continuity mismatch: {patch}")
        if patch["operand_ram"] != consumer_allocation["operand_ram"]:
            failures.append(f"operand_ram mismatch: {patch}")
        if patch["operand_line"] != consumer_allocation["operand_line"]:
            failures.append(f"operand_line mismatch: {patch}")
        if patch["allocation_scope"] != consumer_allocation["allocation_scope"]:
            failures.append(f"allocation scope mismatch: {patch}")
        if consumer_allocation["allocation_scope"] != producer_allocation["allocation_scope"]:
            failures.append(f"producer/consumer allocation scope mismatch: {patch}")
        if patch["value_identity_reuse"] is not True:
            failures.append(f"must mark value identity reuse: {patch}")
        if patch["globalmax_source_patch_status"] != "patched":
            failures.append(f"GlobalMax source should be patched: {patch}")
        if patch["consumer_fiber_op"] != "max_with_floor_tile":
            failures.append(f"unexpected consumer fiber op: {patch}")
        if patch["consumer_operand_role"] != "globalmax_src":
            failures.append(f"unexpected consumer operand role: {patch}")
        if not consumer_id.endswith(":max_with_floor_globalmax_src"):
            failures.append(f"unexpected consumer placeholder id: {patch}")
        if patch["log_spec_source_status"] != "deferred_named":
            failures.append(f"log_spec source must remain deferred/named: {patch}")
        if patch["constants_status"] != "deferred_named":
            failures.append(f"constants must remain deferred/named: {patch}")
        if patch["output_operand_status"] != "deferred_named":
            failures.append(f"output must remain deferred/named: {patch}")
        if set(patch["blocker_ids"]) != EXPECTED_DEFERRED_BLOCKERS:
            failures.append(f"unexpected patch blockers: {patch}")
        if patch["final_row_bytes_claim"] is not False:
            failures.append(f"patch must not claim final row bytes: {patch}")
        if patch["component_integration_claim"] is not False:
            failures.append(f"patch must not claim component integration: {patch}")
        if patch["runtime_ready"] is not False:
            failures.append(f"patch must not claim runtime_ready: {patch}")
        seen_consumers.add(consumer_id)

    if len(seen_consumers) != len(plan["patches"]):
        failures.append("max_with_floor consumer placeholder ids must be unique")

    if failures:
        print("stream compiler log10max max_with_floor operand patch check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max max_with_floor operand patch check OK")
    print(f"patch_count={summary['patch_count']}")
    print(f"blocker_ids={summary['blocker_ids']}")


if __name__ == "__main__":
    main()
