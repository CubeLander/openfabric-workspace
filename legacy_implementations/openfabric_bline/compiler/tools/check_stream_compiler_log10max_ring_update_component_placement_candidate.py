#!/usr/bin/env python3
"""Check Phase-5 log10max ring update component placement candidates."""

from __future__ import annotations

from gpdpu_compiler.core.program_bin import MAX_INST_AMOUNT_PER_PE
from gpdpu_compiler.core.program_legacy_inst import INST_RECORD_SIZE_BYTES
from gpdpu_compiler.core.stream_compiler.log10max_ring_update_template import (
    build_log10max_ring_update_component_placement_candidate_report,
    summarize_log10max_ring_update_component_placement_candidate_report,
)


EXPECTED_PHASE_COUNTS = {
    "col_broadcast": 3,
    "col_reduce": 3,
    "row_broadcast": 12,
    "row_reduce": 12,
}


def main() -> None:
    report = build_log10max_ring_update_component_placement_candidate_report()
    summary = summarize_log10max_ring_update_component_placement_candidate_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["placement_count"] != 30:
        failures.append(f"expected 30 placement candidates: {summary}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected phase counts: {summary}")
    if summary["component_placement_status_counts"] != {"candidate_offset_bound": 30}:
        failures.append(f"unexpected component placement status: {summary}")
    if summary["exe_block_integration_status_counts"] != {"not_integrated": 30}:
        failures.append(f"Phase 5 candidate must not claim exeBlock integration: {summary}")
    if summary["cbuf_section_integration_status_counts"] != {"not_integrated": 30}:
        failures.append(f"Phase 5 candidate must not claim CBUF integration: {summary}")
    if summary["operand_allocation_status_counts"] != {
        "skeleton_operands_unallocated": 30
    }:
        failures.append(f"unexpected operand allocation status: {summary}")
    if summary["duplicate_component_byte_offset_count"] != 0:
        failures.append(f"component byte offsets must be unique: {summary}")
    if summary["blocker_ids"] != [
        "log10max_ring_update_operand_allocation_missing",
        "log10max_ring_update_exeblock_cal_stage_missing",
    ]:
        failures.append(f"unexpected placement blocker: {summary}")
    if summary["runtime_ready"] is not False:
        failures.append("placement candidate must not claim runtime_ready")

    local_pcs_by_pe: dict[str, list[int]] = {}
    for placement in plan["placements"]:
        if placement["component_name"] != "insts_file.bin":
            failures.append(f"unexpected component name: {placement}")
        if placement["stage"] != "CAL":
            failures.append(f"ring update rows must be CAL-stage candidates: {placement}")
        if placement["opcode"] != "FMAX":
            failures.append(f"unexpected opcode: {placement}")
        if placement["record_size_bytes"] != INST_RECORD_SIZE_BYTES:
            failures.append(f"unexpected record size: {placement}")
        expected_global_row = (
            int(placement["pe_index"]) * MAX_INST_AMOUNT_PER_PE
            + int(placement["local_pc"])
        )
        if placement["global_row_index"] != expected_global_row:
            failures.append(f"unexpected global row index: {placement}")
        expected_offset = expected_global_row * INST_RECORD_SIZE_BYTES
        if placement["component_byte_offset"] != expected_offset:
            failures.append(f"unexpected component byte offset: {placement}")
        if not placement["source_fiber_op_id"]:
            failures.append(f"missing FiberOp provenance: {placement}")
        if not placement["template_expansion_id"]:
            failures.append(f"missing template expansion provenance: {placement}")
        if placement["exe_block_integration_status"] != "not_integrated":
            failures.append(f"must not claim exeBlock integration: {placement}")
        if placement["cbuf_section_integration_status"] != "not_integrated":
            failures.append(f"must not claim CBUF integration: {placement}")
        if placement["operand_allocation_status"] != "skeleton_operands_unallocated":
            failures.append(f"unexpected operand allocation status: {placement}")
        if placement["runtime_ready"] is not False:
            failures.append(f"placement must not claim runtime_ready: {placement}")
        local_pcs_by_pe.setdefault(str(placement["dst_pe"]), []).append(
            int(placement["local_pc"])
        )

    for pe, local_pcs in local_pcs_by_pe.items():
        expected = list(range(len(local_pcs)))
        if local_pcs != expected:
            failures.append(f"local PCs for {pe} must be contiguous: {local_pcs}")

    if failures:
        print("stream compiler log10max ring update component placement check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max ring update component placement check OK")
    print(f"placement_count={summary['placement_count']}")
    print(f"blocker_ids={summary['blocker_ids']}")


if __name__ == "__main__":
    main()
