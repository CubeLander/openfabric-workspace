#!/usr/bin/env python3
"""Check Phase-3 log10max ring update InstOperandPatch records."""

from __future__ import annotations

from gpdpu_compiler.core.program_legacy_inst import INST_RECORD_SIZE_BYTES
from gpdpu_compiler.core.stream_compiler.log10max_ring_update_operands import (
    EXPECTED_PHASE_COUNTS,
    LOG10MAX_RING_UPDATE_COMPONENT_BLOCKER,
    LOG10MAX_RING_UPDATE_PATCH_BLOCKER,
    PLACEHOLDER_ROLES,
    build_log10max_ring_update_inst_operand_patch_report,
    build_log10max_ring_update_operand_allocation_report,
    build_log10max_ring_update_operand_placeholder_report,
    summarize_log10max_ring_update_inst_operand_patch_report,
    summarize_log10max_ring_update_operand_allocation_report,
    summarize_log10max_ring_update_operand_placeholder_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_ring_update_template import (
    RING_UPDATE_FMAX_OPERAND_FIELD_USAGE,
)


EXPECTED_PLACEHOLDER_ROLE_COUNTS = {
    "globalmax_acc_in": 30,
    "globalmax_acc_out": 30,
    "globalmax_recv": 30,
}
EXPECTED_PHASE_PLACEHOLDER_COUNTS = {
    phase: count * len(PLACEHOLDER_ROLES)
    for phase, count in EXPECTED_PHASE_COUNTS.items()
}
EXPECTED_OPERAND_FIELD_USAGE = dict(RING_UPDATE_FMAX_OPERAND_FIELD_USAGE)


def main() -> None:
    placeholder_report = build_log10max_ring_update_operand_placeholder_report()
    allocation_report = build_log10max_ring_update_operand_allocation_report(
        placeholder_report
    )
    patch_report = build_log10max_ring_update_inst_operand_patch_report(
        allocation_report=allocation_report
    )
    placeholder_summary = summarize_log10max_ring_update_operand_placeholder_report(
        placeholder_report
    )
    allocation_summary = summarize_log10max_ring_update_operand_allocation_report(
        allocation_report
    )
    patch_summary = summarize_log10max_ring_update_inst_operand_patch_report(
        patch_report
    )
    plan = patch_report.to_plan()
    allocation_plan = allocation_report.to_plan()
    placeholder_plan = placeholder_report.to_plan()
    failures: list[str] = []

    if placeholder_summary["placeholder_count"] != 90:
        failures.append(f"expected 90 placeholders: {placeholder_summary}")
    if placeholder_summary["row_candidate_count"] != 30:
        failures.append(f"expected 30 placeholder row candidates: {placeholder_summary}")
    if placeholder_summary["role_counts"] != EXPECTED_PLACEHOLDER_ROLE_COUNTS:
        failures.append(f"unexpected placeholder roles: {placeholder_summary}")
    if (
        placeholder_summary["phase_placeholder_counts"]
        != EXPECTED_PHASE_PLACEHOLDER_COUNTS
    ):
        failures.append(f"unexpected placeholder phase distribution: {placeholder_summary}")
    if placeholder_summary["blocker_ids"] != [
        "log10max_ring_update_operand_allocation_missing"
    ]:
        failures.append(f"unexpected placeholder blocker: {placeholder_summary}")

    if allocation_summary["allocation_count"] != 90:
        failures.append(f"expected 90 allocation records: {allocation_summary}")
    if allocation_summary["allocation_status_counts"] != {"allocated": 90}:
        failures.append(f"all placeholders must be allocated: {allocation_summary}")
    if allocation_summary["blocker_ids"] != [
        "log10max_ring_update_inst_operand_patch_missing"
    ]:
        failures.append(f"unexpected allocation blocker: {allocation_summary}")

    if patch_summary["patch_count"] != 30:
        failures.append(f"expected 30 patches: {patch_summary}")
    if patch_summary["patch_status_counts"] != {"patched": 30}:
        failures.append(f"all FMAX patches must be allocation-backed: {patch_summary}")
    if patch_summary["decode_roundtrip_status_counts"] != {
        "candidate_decode_roundtrip": 30
    }:
        failures.append(f"all patches must candidate-decode: {patch_summary}")
    if patch_summary["route_continuity_status_counts"] != {
        "blocked_missing_route_row_patch": 30
    }:
        failures.append(f"route continuity must remain explicitly blocked: {patch_summary}")
    expected_blockers = [
        LOG10MAX_RING_UPDATE_PATCH_BLOCKER,
        LOG10MAX_RING_UPDATE_COMPONENT_BLOCKER,
    ]
    if patch_summary["blocker_ids"] != expected_blockers:
        failures.append(f"unexpected patch blockers: {patch_summary}")
    if patch_summary["raw_inst_t_byte_count"] != 30 * INST_RECORD_SIZE_BYTES:
        failures.append(f"unexpected patch byte count: {patch_summary}")
    if patch_summary["final_row_bytes_claim"] is not False:
        failures.append("InstOperandPatch candidates must not claim final row bytes")
    if patch_summary["component_integration_claim"] is not False:
        failures.append("InstOperandPatch candidates must not claim component integration")
    if patch_summary["runtime_ready"] is not False:
        failures.append("InstOperandPatch report must not claim runtime_ready")

    placeholders = {
        record["placeholder_id"]: record
        for record in placeholder_plan["placeholders"]
    }
    allocations = {
        record["placeholder_id"]: record
        for record in allocation_plan["allocations"]
    }
    for patch in plan["patches"]:
        if patch["opcode"] != "FMAX":
            failures.append(f"unexpected opcode: {patch}")
        if patch["operand_field_usage"] != EXPECTED_OPERAND_FIELD_USAGE:
            failures.append(f"unexpected field usage: {patch}")
        if len(patch["allocation_ids"]) != 3:
            failures.append(f"patch must reference three allocations: {patch}")
        if len(patch["src_placeholders"]) != 2 or len(patch["dst_placeholders"]) != 1:
            failures.append(f"unexpected placeholder arity: {patch}")
        src0_placeholder, src1_placeholder = patch["src_placeholders"]
        dst0_placeholder = patch["dst_placeholders"][0]
        for placeholder_id in (src0_placeholder, src1_placeholder, dst0_placeholder):
            if placeholder_id not in placeholders:
                failures.append(f"missing placeholder record: {placeholder_id}")
            if placeholder_id not in allocations:
                failures.append(f"missing allocation record: {placeholder_id}")
        if src0_placeholder in allocations:
            if patch["src_operands_idx"][0] != allocations[src0_placeholder]["operand_idx"]:
                failures.append(f"src0 mismatch: {patch}")
        if src1_placeholder in allocations:
            if patch["src_operands_idx"][1] != allocations[src1_placeholder]["operand_idx"]:
                failures.append(f"src1 mismatch: {patch}")
        if dst0_placeholder in allocations:
            if patch["dst_operands_idx"][0] != allocations[dst0_placeholder]["operand_idx"]:
                failures.append(f"dst0 mismatch: {patch}")
        if patch["src_operands_idx"][2] != 0:
            failures.append(f"src2 must be unused zero-fill: {patch}")
        if patch["dst_operands_idx"][1:] != [0, 0]:
            failures.append(f"dst1/dst2 must be unused zero-fill: {patch}")
        if patch["patch_status"] != "patched":
            failures.append(f"unexpected patch status: {patch}")
        if patch["decode_roundtrip_status"] != "candidate_decode_roundtrip":
            failures.append(f"unexpected decode status: {patch}")
        if patch["provenance_roundtrip_status"] != "candidate_report_roundtrip":
            failures.append(f"unexpected provenance status: {patch}")
        if patch["route_continuity_status"] != "blocked_missing_route_row_patch":
            failures.append(f"route continuity must be blocked: {patch}")
        if patch["route_continuity_blockers"] != [
            "log10max_ring_update_route_recv_operand_patch_missing",
            "log10max_ring_update_route_push_operand_patch_missing",
        ]:
            failures.append(f"unexpected route blockers: {patch}")
        if patch["final_row_bytes_claim"] is not False:
            failures.append(f"patch must not claim final row bytes: {patch}")
        if patch["runtime_ready"] is not False:
            failures.append(f"patch must not claim runtime_ready: {patch}")
        if patch["raw_inst_t_byte_count"] != INST_RECORD_SIZE_BYTES:
            failures.append(f"unexpected raw row size: {patch}")

    if failures:
        print("stream compiler log10max ring update InstOperandPatch check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max ring update InstOperandPatch check OK")
    print(f"placeholder_count={placeholder_summary['placeholder_count']}")
    print(f"allocation_count={allocation_summary['allocation_count']}")
    print(f"patch_count={patch_summary['patch_count']}")
    print(f"blocker_ids={patch_summary['blocker_ids']}")


if __name__ == "__main__":
    main()
