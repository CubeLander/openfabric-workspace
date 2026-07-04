#!/usr/bin/env python3
"""Check Phase-4 log10max ring update FMAX inst_t candidate bytes."""

from __future__ import annotations

from gpdpu_compiler.core.program_legacy_inst import INST_RECORD_SIZE_BYTES
from gpdpu_compiler.core.stream_compiler.log10max_ring_update_template import (
    RING_UPDATE_BYPASS_BITS,
    RING_UPDATE_DST_UPDATED_OPERAND_IDX,
    RING_UPDATE_FMAX_ITER_EXE_COND,
    RING_UPDATE_FMAX_LATENCY,
    RING_UPDATE_FMAX_OPCODE,
    RING_UPDATE_FMAX_OPERAND_FIELD_USAGE,
    RING_UPDATE_FMAX_UNIT_INST_TYPE,
    RING_UPDATE_FORWARDING_BITS,
    RING_UPDATE_SRC_CURRENT_OPERAND_IDX,
    RING_UPDATE_SRC_RECEIVED_OPERAND_IDX,
    build_log10max_ring_update_fmax_inst_candidate_report,
    summarize_log10max_ring_update_fmax_inst_candidate_report,
)


EXPECTED_PHASE_COUNTS = {
    "col_broadcast": 3,
    "col_reduce": 3,
    "row_broadcast": 12,
    "row_reduce": 12,
}
EXPECTED_OPERAND_FIELD_USAGE = dict(RING_UPDATE_FMAX_OPERAND_FIELD_USAGE)


def main() -> None:
    report = build_log10max_ring_update_fmax_inst_candidate_report()
    summary = summarize_log10max_ring_update_fmax_inst_candidate_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["inst_candidate_count"] != 30:
        failures.append(f"expected 30 FMAX inst candidates: {summary}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected phase distribution: {summary}")
    if summary["opcode_counts"] != {"FMAX": 30}:
        failures.append(f"fp32 V1 must pack FMAX rows: {summary}")
    if summary["decode_status_counts"] != {"candidate_pack_decode_roundtrip": 30}:
        failures.append(f"decode roundtrip must be local-candidate complete: {summary}")
    if summary["component_integration_status_counts"] != {"not_integrated": 30}:
        failures.append(f"Phase 4 must not claim component integration: {summary}")
    if summary["operand_allocation_status_counts"] != {
        "skeleton_operands_unallocated": 30
    }:
        failures.append(f"unexpected operand allocation status: {summary}")
    if summary["blocker_ids"] != [
        "log10max_ring_update_operand_allocation_missing",
        "log10max_ring_update_component_integration_missing",
    ]:
        failures.append(f"unexpected Phase-4 blocker: {summary}")
    if summary["raw_inst_t_byte_count"] != 30 * INST_RECORD_SIZE_BYTES:
        failures.append(f"unexpected raw byte count: {summary}")
    if summary["row_bytes_claim"] is not True:
        failures.append("Phase 4 must claim candidate row bytes")
    if summary["final_row_bytes_claim"] is not False:
        failures.append("Phase 4 skeleton operands must not claim final row bytes")
    if summary["decode_roundtrip_claim"] is not True:
        failures.append("Phase 4 must claim candidate decode roundtrip")
    if summary["component_integration_claim"] is not False:
        failures.append("Phase 4 must not claim component integration")
    if summary["runtime_ready"] is not False:
        failures.append("Phase 4 candidate bytes must not claim runtime_ready")

    seen_candidates: set[str] = set()
    seen_edges: set[str] = set()
    for candidate in plan["inst_candidates"]:
        candidate_id = str(candidate["inst_candidate_id"])
        edge_id = str(candidate["source_ring_edge_id"])
        if candidate_id in seen_candidates:
            failures.append(f"duplicate candidate id: {candidate_id}")
        seen_candidates.add(candidate_id)
        if edge_id in seen_edges:
            failures.append(f"duplicate ring edge candidate: {edge_id}")
        seen_edges.add(edge_id)
        if not candidate["template_expansion_id"]:
            failures.append(f"missing template expansion provenance: {candidate}")
        if not candidate["source_fiber_op_id"]:
            failures.append(f"missing FiberOp provenance: {candidate}")
        if not candidate["source_stream_action_id"]:
            failures.append(f"missing stream action provenance: {candidate}")
        if candidate["opcode"] != "FMAX":
            failures.append(f"unexpected opcode: {candidate}")
        if candidate["opcode_value"] != RING_UPDATE_FMAX_OPCODE:
            failures.append(f"unexpected opcode value: {candidate}")
        if candidate["unit_inst_type"] != RING_UPDATE_FMAX_UNIT_INST_TYPE:
            failures.append(f"unexpected unit type: {candidate}")
        if candidate["latency"] != RING_UPDATE_FMAX_LATENCY:
            failures.append(f"unexpected latency: {candidate}")
        if candidate["operand_field_usage"] != EXPECTED_OPERAND_FIELD_USAGE:
            failures.append(f"unexpected operand field usage: {candidate}")
        if candidate["src_operands_idx"] != [
            RING_UPDATE_SRC_CURRENT_OPERAND_IDX,
            RING_UPDATE_SRC_RECEIVED_OPERAND_IDX,
            0,
        ]:
            failures.append(f"unexpected source operands: {candidate}")
        if candidate["dst_operands_idx"] != [RING_UPDATE_DST_UPDATED_OPERAND_IDX, 0, 0]:
            failures.append(f"unexpected destination operands: {candidate}")
        if candidate["operand_allocation_status"] != "skeleton_operands_unallocated":
            failures.append(f"unexpected operand allocation status: {candidate}")
        if candidate["final_row_bytes_claim"] is not False:
            failures.append(f"candidate must not claim final row bytes: {candidate}")
        if candidate["forwarding_bits"] != list(RING_UPDATE_FORWARDING_BITS):
            failures.append(f"unexpected forwarding bits: {candidate}")
        if candidate["bypass_bits"] != list(RING_UPDATE_BYPASS_BITS):
            failures.append(f"unexpected bypass bits: {candidate}")
        if candidate["iter_exe_cond"] != RING_UPDATE_FMAX_ITER_EXE_COND:
            failures.append(f"unexpected iter_exe_cond: {candidate}")
        if candidate["raw_inst_t_byte_count"] != INST_RECORD_SIZE_BYTES:
            failures.append(f"unexpected row byte size: {candidate}")
        if candidate["decode_roundtrip_status"] != "candidate_pack_decode_roundtrip":
            failures.append(f"unexpected decode status: {candidate}")
        if candidate["component_integration_status"] != "not_integrated":
            failures.append(f"unexpected integration status: {candidate}")
        if candidate["runtime_ready"] is not False:
            failures.append(f"candidate must not claim runtime_ready: {candidate}")

    if failures:
        print("stream compiler log10max ring update FMAX inst candidate check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max ring update FMAX inst candidate check OK")
    print(f"inst_candidate_count={summary['inst_candidate_count']}")
    print(f"blocker_ids={summary['blocker_ids']}")


if __name__ == "__main__":
    main()
