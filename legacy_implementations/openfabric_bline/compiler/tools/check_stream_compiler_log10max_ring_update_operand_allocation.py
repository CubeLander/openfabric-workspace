#!/usr/bin/env python3
"""Check Phase-2 log10max ring update operand allocation report."""

from __future__ import annotations

from gpdpu_compiler.core.program_legacy_inst import (
    OPERANDS_PER_OPERAND_RAM,
    OPERANDS_RAM_NUM,
)
from gpdpu_compiler.core.stream_compiler.log10max_ring_update_operands import (
    DFU3500_BLINE_LINEAR_ALLOCATOR_ID,
    DFU3500_OPERAND_LAYOUT_PROFILE_ID,
    build_log10max_ring_update_operand_allocation_report,
    build_log10max_ring_update_operand_placeholder_report,
    summarize_log10max_ring_update_operand_allocation_report,
    summarize_log10max_ring_update_operand_placeholder_report,
)


EXPECTED_PHASE_COUNTS = {
    "col_broadcast": 9,
    "col_reduce": 9,
    "row_broadcast": 36,
    "row_reduce": 36,
}
EXPECTED_ROLE_COUNTS = {
    "globalmax_acc_in": 30,
    "globalmax_acc_out": 30,
    "globalmax_recv": 30,
}
EXPECTED_LAYOUT_FORMULA = (
    "(reg_idx % operands_ram_num) * operands_per_operand_ram "
    "+ reg_idx // operands_ram_num"
)


def main() -> None:
    placeholder_report = build_log10max_ring_update_operand_placeholder_report()
    allocation_report = build_log10max_ring_update_operand_allocation_report(
        placeholder_report
    )
    placeholder_summary = summarize_log10max_ring_update_operand_placeholder_report(
        placeholder_report
    )
    allocation_summary = summarize_log10max_ring_update_operand_allocation_report(
        allocation_report
    )
    placeholder_plan = placeholder_report.to_plan()
    allocation_plan = allocation_report.to_plan()
    failures: list[str] = []

    _check_placeholder_summary(placeholder_summary, failures)
    _check_allocation_summary(allocation_summary, failures)
    _check_layout(allocation_plan["layout"], failures)
    _check_placeholders(placeholder_plan["placeholders"], failures)
    _check_allocations(
        placeholders=placeholder_plan["placeholders"],
        allocations=allocation_plan["allocations"],
        failures=failures,
    )

    if failures:
        print("stream compiler log10max ring update operand allocation check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max ring update operand allocation check OK")
    print(f"placeholder_count={placeholder_summary['placeholder_count']}")
    print(f"allocation_count={allocation_summary['allocation_count']}")
    print(f"blocker_ids={allocation_summary['blocker_ids']}")


def _check_placeholder_summary(summary: dict[str, object], failures: list[str]) -> None:
    if summary["placeholder_count"] != 90:
        failures.append(f"expected 90 placeholders: {summary}")
    if summary["role_counts"] != EXPECTED_ROLE_COUNTS:
        failures.append(f"unexpected placeholder roles: {summary}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected placeholder phase counts: {summary}")
    if summary["allocation_scope_count"] != 16:
        failures.append(f"expected 16 task_pe allocation scopes: {summary}")
    if summary["blocker_ids"] != ["log10max_ring_update_operand_allocation_missing"]:
        failures.append(f"placeholder report should block on allocation: {summary}")
    if summary["runtime_ready"] is not False:
        failures.append("placeholder report must not claim runtime_ready")
    if summary["component_integration_claim"] is not False:
        failures.append("placeholder report must not claim component integration")


def _check_allocation_summary(summary: dict[str, object], failures: list[str]) -> None:
    if summary["allocation_count"] != 90:
        failures.append(f"expected 90 allocation records: {summary}")
    if summary["allocator"] != DFU3500_BLINE_LINEAR_ALLOCATOR_ID:
        failures.append(f"unexpected allocator id: {summary}")
    if summary["layout_profile_id"] != DFU3500_OPERAND_LAYOUT_PROFILE_ID:
        failures.append(f"unexpected layout profile: {summary}")
    if summary["allocation_status_counts"] != {"allocated": 90}:
        failures.append(f"all V1 placeholders should allocate: {summary}")
    if summary["allocation_scope_count"] != 16:
        failures.append(f"expected 16 task_pe allocation scopes: {summary}")
    if summary["duplicate_new_operand_count"] != 0:
        failures.append(f"monotonic no-reuse allocator collided: {summary}")
    if summary["blocker_ids"] != ["log10max_ring_update_inst_operand_patch_missing"]:
        failures.append(f"allocation should stop at patch blocker: {summary}")
    if summary["allocation_ready_for_patch"] is not True:
        failures.append("allocation report should be ready only for patch phase")
    if summary["runtime_ready"] is not False:
        failures.append("allocation report must not claim runtime_ready")
    if summary["component_integration_claim"] is not False:
        failures.append("allocation report must not claim component integration")


def _check_layout(layout: object, failures: list[str]) -> None:
    if not isinstance(layout, dict):
        failures.append(f"layout must be a dict: {layout!r}")
        return
    if layout["layout_profile_id"] != DFU3500_OPERAND_LAYOUT_PROFILE_ID:
        failures.append(f"unexpected layout profile: {layout}")
    if layout["operands_ram_num"] != OPERANDS_RAM_NUM:
        failures.append(f"unexpected operand RAM count: {layout}")
    if layout["operands_per_operand_ram"] != OPERANDS_PER_OPERAND_RAM:
        failures.append(f"unexpected operand RAM depth: {layout}")
    if layout["capacity"] != OPERANDS_RAM_NUM * OPERANDS_PER_OPERAND_RAM:
        failures.append(f"unexpected capacity: {layout}")
    if layout["layout_formula"] != EXPECTED_LAYOUT_FORMULA:
        failures.append(f"unexpected layout formula: {layout}")


def _check_placeholders(
    placeholders: object,
    failures: list[str],
) -> None:
    if not isinstance(placeholders, list):
        failures.append("placeholder plan must contain a placeholder list")
        return
    ids: set[str] = set()
    acc_out_with_consumer = 0
    for placeholder in placeholders:
        if not isinstance(placeholder, dict):
            failures.append(f"placeholder must be dict: {placeholder!r}")
            continue
        placeholder_id = str(placeholder["placeholder_id"])
        if placeholder_id in ids:
            failures.append(f"duplicate placeholder id: {placeholder_id}")
        ids.add(placeholder_id)
        if not placeholder_id.startswith("opnd:log10max:"):
            failures.append(f"placeholder id must be deterministic: {placeholder_id}")
        if placeholder["allocation_required"] is not True:
            failures.append(f"placeholder must require allocation: {placeholder}")
        if placeholder["source_template_fixed_allowed"] is not False:
            failures.append(f"ring update placeholder must not be template-fixed: {placeholder}")
        if placeholder["hardcoded_operand_idx_allowed"] is not False:
            failures.append(f"hardcoded operand ids are forbidden: {placeholder}")
        if placeholder["alias_policy"] != "forbidden":
            failures.append(f"instruction aliasing must be forbidden: {placeholder}")
        if placeholder["value_kind"] != "replicated_vector":
            failures.append(f"GlobalMax V1 must use replicated_vector: {placeholder}")
        if placeholder["dtype"] != "fp32":
            failures.append(f"GlobalMax V1 must use fp32: {placeholder}")
        if not placeholder["source_ring_edge_id"]:
            failures.append(f"placeholder missing ring edge provenance: {placeholder}")
        if not placeholder["source_stream_action_id"]:
            failures.append(f"placeholder missing stream action provenance: {placeholder}")
        if not placeholder["template_expansion_id"]:
            failures.append(f"placeholder missing template expansion provenance: {placeholder}")
        producers = placeholder["producer_placeholder_ids"]
        if not isinstance(producers, list):
            failures.append(f"producer ids must be list in plan: {placeholder}")
        elif len(producers) > 1:
            failures.append(f"multiple producers require explicit merge/reduce: {placeholder}")
        if placeholder["role"] == "globalmax_recv":
            if not any(str(ref).startswith("route_recv:") for ref in placeholder["consumer_refs"]):
                failures.append(f"recv placeholder missing route_recv continuity: {placeholder}")
        if placeholder["role"] == "globalmax_acc_out":
            if not placeholder["consumer_refs"]:
                failures.append(f"acc_out placeholder must have consumer link: {placeholder}")
            acc_out_with_consumer += 1
    if len(ids) != 90:
        failures.append(f"expected 90 unique placeholder ids, got {len(ids)}")
    if acc_out_with_consumer != 30:
        failures.append(f"expected 30 acc_out consumer links, got {acc_out_with_consumer}")


def _check_allocations(
    *,
    placeholders: object,
    allocations: object,
    failures: list[str],
) -> None:
    if not isinstance(placeholders, list) or not isinstance(allocations, list):
        failures.append("placeholder/allocation plans must contain lists")
        return
    placeholder_by_id = {
        str(placeholder["placeholder_id"]): placeholder
        for placeholder in placeholders
        if isinstance(placeholder, dict)
    }
    allocation_by_placeholder: dict[str, dict[str, object]] = {}
    new_operand_by_scope: set[tuple[str, int]] = set()
    for allocation in allocations:
        if not isinstance(allocation, dict):
            failures.append(f"allocation must be dict: {allocation!r}")
            continue
        placeholder_id = str(allocation["placeholder_id"])
        if placeholder_id not in placeholder_by_id:
            failures.append(f"allocation references unknown placeholder: {allocation}")
        if placeholder_id in allocation_by_placeholder:
            failures.append(f"duplicate allocation for placeholder: {placeholder_id}")
        allocation_by_placeholder[placeholder_id] = allocation
        if allocation["allocator"] != DFU3500_BLINE_LINEAR_ALLOCATOR_ID:
            failures.append(f"allocation must use B-line allocator: {allocation}")
        if allocation["layout_profile_id"] != DFU3500_OPERAND_LAYOUT_PROFILE_ID:
            failures.append(f"allocation missing layout profile: {allocation}")
        if allocation["allocation_status"] != "allocated":
            failures.append(f"unexpected blocked allocation: {allocation}")
            continue
        operand_idx = int(allocation["operand_idx"])
        expected_ram = operand_idx // OPERANDS_PER_OPERAND_RAM
        expected_line = operand_idx % OPERANDS_PER_OPERAND_RAM
        if allocation["operand_ram"] != expected_ram:
            failures.append(f"operand_ram does not match canonical layout: {allocation}")
        if allocation["operand_line"] != expected_line:
            failures.append(f"operand_line does not match canonical layout: {allocation}")
        logical_reg_idx = int(allocation["logical_reg_idx"])
        expected_operand_idx = (
            (logical_reg_idx % OPERANDS_RAM_NUM) * OPERANDS_PER_OPERAND_RAM
            + logical_reg_idx // OPERANDS_RAM_NUM
        )
        if operand_idx != expected_operand_idx:
            failures.append(f"operand_idx does not match canonical formula: {allocation}")
        if allocation["allocation_kind"] == "new_monotonic_no_reuse":
            key = (str(allocation["allocation_scope"]), operand_idx)
            if key in new_operand_by_scope:
                failures.append(f"duplicate new operand allocation in scope: {allocation}")
            new_operand_by_scope.add(key)
            if allocation["producer_allocation_ids"]:
                failures.append(f"new allocation must not carry producer allocations: {allocation}")
        elif allocation["allocation_kind"] == "value_identity_reuse":
            if len(allocation["producer_allocation_ids"]) != 1:
                failures.append(f"value reuse must name exactly one producer allocation: {allocation}")
            producer_placeholder_ids = placeholder_by_id[placeholder_id][
                "producer_placeholder_ids"
            ]
            if len(producer_placeholder_ids) != 1:
                failures.append(f"value reuse must come from one producer placeholder: {allocation}")
            else:
                producer_placeholder_id = str(producer_placeholder_ids[0])
                producer_allocation = allocation_by_placeholder.get(producer_placeholder_id)
                if producer_allocation is None:
                    failures.append(f"producer allocation must precede reuse: {allocation}")
                else:
                    for field in ("operand_idx", "operand_ram", "operand_line"):
                        if allocation[field] != producer_allocation[field]:
                            failures.append(
                                "value identity reuse must preserve operand field "
                                f"{field}: {allocation}"
                            )
        else:
            failures.append(f"unexpected allocation kind: {allocation}")
    if len(allocation_by_placeholder) != 90:
        failures.append(
            f"expected 90 unique placeholder allocations, got {len(allocation_by_placeholder)}"
        )


if __name__ == "__main__":
    main()
