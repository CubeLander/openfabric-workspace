#!/usr/bin/env python3
"""Check Phase-2 log10max endpoint + ring unified operand allocation."""

from __future__ import annotations

from gpdpu_compiler.core.program_legacy_inst import (
    OPERANDS_PER_OPERAND_RAM,
    OPERANDS_RAM_NUM,
)
from gpdpu_compiler.core.stream_compiler.log10max_ring_update_operands import (
    DFU3500_BLINE_LINEAR_ALLOCATOR_ID,
    DFU3500_OPERAND_LAYOUT_PROFILE_ID,
    LOG10MAX_ENDPOINT_PATCH_BLOCKER,
    build_log10max_endpoint_operand_placeholder_report,
    build_log10max_unified_operand_allocation_report,
    summarize_log10max_endpoint_operand_placeholder_report,
    summarize_log10max_unified_operand_allocation_report,
)


def main() -> None:
    placeholder_report = build_log10max_endpoint_operand_placeholder_report()
    allocation_report = build_log10max_unified_operand_allocation_report()
    placeholder_summary = summarize_log10max_endpoint_operand_placeholder_report(
        placeholder_report
    )
    allocation_summary = summarize_log10max_unified_operand_allocation_report(
        allocation_report
    )
    placeholder_plan = placeholder_report.to_plan()
    allocation_plan = allocation_report.to_plan()
    failures: list[str] = []

    _check_summary(placeholder_summary, allocation_summary, failures)
    _check_allocations(placeholder_plan, allocation_plan, failures)

    if failures:
        print("stream compiler log10max endpoint operand allocation check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max endpoint operand allocation check OK")
    print(f"allocation_count={allocation_summary['allocation_record_count']}")
    print(f"blocker_ids={allocation_summary['blocker_ids']}")


def _check_summary(
    placeholder_summary: dict[str, object],
    allocation_summary: dict[str, object],
    failures: list[str],
) -> None:
    endpoint_count = int(placeholder_summary["placeholder_count"])
    if allocation_summary["allocator"] != DFU3500_BLINE_LINEAR_ALLOCATOR_ID:
        failures.append(f"unexpected allocator: {allocation_summary}")
    if allocation_summary["layout_profile_id"] != DFU3500_OPERAND_LAYOUT_PROFILE_ID:
        failures.append(f"unexpected layout profile: {allocation_summary}")
    if allocation_summary["endpoint_placeholder_count"] != endpoint_count:
        failures.append(f"endpoint count mismatch: {allocation_summary}")
    if allocation_summary["ring_update_placeholder_count"] != 90:
        failures.append(f"ring update placeholder count should remain 90: {allocation_summary}")
    if allocation_summary["placeholder_count"] != 90 + endpoint_count:
        failures.append(f"unified placeholder count mismatch: {allocation_summary}")
    if allocation_summary["allocation_record_count"] != allocation_summary["placeholder_count"]:
        failures.append(f"every placeholder needs an allocation record: {allocation_summary}")
    if allocation_summary["allocation_status_counts"] != {
        "allocated": allocation_summary["allocation_record_count"]
    }:
        failures.append(f"all unified allocations should allocate: {allocation_summary}")
    if allocation_summary["blocked_count"] != 0:
        failures.append(f"unified allocation should have no blocked records: {allocation_summary}")
    if allocation_summary["duplicate_new_operand_count"] != 0:
        failures.append(f"new monotonic allocations must not collide: {allocation_summary}")
    if allocation_summary["value_identity_reuse_count"] <= 0:
        failures.append(f"expected value identity reuse records: {allocation_summary}")
    if allocation_summary["blocker_ids"] != [LOG10MAX_ENDPOINT_PATCH_BLOCKER]:
        failures.append(f"allocation should stop at endpoint patch blocker: {allocation_summary}")
    if allocation_summary["allocation_ready_for_endpoint_patch"] is not True:
        failures.append("allocation report should be ready for endpoint patch reports")
    if allocation_summary["runtime_ready"] is not False:
        failures.append("unified allocation must not claim runtime_ready")
    if allocation_summary["final_row_bytes_claim"] is not False:
        failures.append("unified allocation must not claim final row bytes")
    if allocation_summary["component_integration_claim"] is not False:
        failures.append("unified allocation must not claim component integration")


def _check_allocations(
    placeholder_plan: dict[str, object],
    allocation_plan: dict[str, object],
    failures: list[str],
) -> None:
    endpoint_placeholders = {
        str(placeholder["placeholder_id"]): placeholder
        for placeholder in placeholder_plan["placeholders"]
    }
    allocations = {
        str(allocation["placeholder_id"]): allocation
        for allocation in allocation_plan["allocations"]
    }
    local_endpoints = {
        placeholder_id: placeholder
        for placeholder_id, placeholder in endpoint_placeholders.items()
        if placeholder["role"] == "local_reduce_max_out"
    }
    max_endpoints = {
        placeholder_id: placeholder
        for placeholder_id, placeholder in endpoint_placeholders.items()
        if placeholder["role"] == "max_with_floor_globalmax_src"
    }

    for placeholder_id, placeholder in endpoint_placeholders.items():
        allocation = allocations.get(placeholder_id)
        if allocation is None:
            failures.append(f"endpoint placeholder missing allocation: {placeholder}")
            continue
        _check_canonical_layout(allocation, failures)
        if allocation["allocation_scope"] != placeholder["allocation_scope"]:
            failures.append(f"endpoint allocation scope mismatch: {allocation}")
        if allocation["allocator"] != DFU3500_BLINE_LINEAR_ALLOCATOR_ID:
            failures.append(f"endpoint allocation uses wrong allocator: {allocation}")

    for placeholder_id, placeholder in local_endpoints.items():
        allocation = allocations.get(placeholder_id)
        if allocation is None:
            continue
        if allocation["allocation_kind"] != "new_monotonic_no_reuse":
            failures.append(f"local_reduce endpoint should allocate a new value: {allocation}")
        consumers = set(placeholder["consumer_stream_action_ids"]) | set(
            placeholder["consumer_placeholder_ids"]
        )
        if not consumers:
            failures.append(f"local_reduce endpoint must feed route/FMAX consumers: {placeholder}")

    for placeholder_id, placeholder in max_endpoints.items():
        allocation = allocations.get(placeholder_id)
        if allocation is None:
            continue
        producers = placeholder["producer_placeholder_ids"]
        if len(producers) != 1:
            failures.append(f"max_with_floor endpoint needs one producer: {placeholder}")
            continue
        producer_allocation = allocations.get(str(producers[0]))
        if producer_allocation is None:
            failures.append(f"max_with_floor producer allocation missing: {placeholder}")
            continue
        if allocation["allocation_kind"] != "value_identity_reuse":
            failures.append(f"max_with_floor endpoint must reuse final acc_out: {allocation}")
        if allocation["operand_idx"] != producer_allocation["operand_idx"]:
            failures.append(f"max_with_floor operand must equal final acc_out: {allocation}")
        if allocation["allocation_scope"] != producer_allocation["allocation_scope"]:
            failures.append(f"max_with_floor reuse must stay inside task_pe scope: {allocation}")


def _check_canonical_layout(
    allocation: dict[str, object],
    failures: list[str],
) -> None:
    if allocation["layout_profile_id"] != DFU3500_OPERAND_LAYOUT_PROFILE_ID:
        failures.append(f"allocation missing canonical layout profile: {allocation}")
    operand_idx = int(allocation["operand_idx"])
    logical_reg_idx = int(allocation["logical_reg_idx"])
    expected_idx = (
        (logical_reg_idx % OPERANDS_RAM_NUM) * OPERANDS_PER_OPERAND_RAM
        + logical_reg_idx // OPERANDS_RAM_NUM
    )
    if operand_idx != expected_idx:
        failures.append(f"operand_idx does not match canonical formula: {allocation}")
    if allocation["operand_ram"] != operand_idx // OPERANDS_PER_OPERAND_RAM:
        failures.append(f"operand_ram does not match canonical layout: {allocation}")
    if allocation["operand_line"] != operand_idx % OPERANDS_PER_OPERAND_RAM:
        failures.append(f"operand_line does not match canonical layout: {allocation}")


if __name__ == "__main__":
    main()
