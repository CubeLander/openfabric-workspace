#!/usr/bin/env python3
"""Check Phase-1 log10max ring update InstRowByteCandidateRecord rows."""

from __future__ import annotations

from gpdpu_compiler.core.program_legacy_inst import INST_RECORD_SIZE_BYTES
from gpdpu_compiler.core.stream_compiler.log10max_ring_update_operands import (
    build_log10max_ring_update_inst_operand_patch_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_ring_update_row_bytes import (
    EXPECTED_PHASE_COUNTS,
    OWNED_DECODED_FIELD_NAMES,
    PENDING_DECODED_FIELD_NAMES,
    ROW_BODY_FIELD_BLOCKERS,
    build_log10max_ring_update_inst_row_byte_candidate_report,
    summarize_log10max_ring_update_inst_row_byte_candidate_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_ring_update_template import (
    RING_UPDATE_BYPASS_BITS,
    RING_UPDATE_FMAX_ITER_EXE_COND,
    RING_UPDATE_FMAX_LATENCY,
    RING_UPDATE_FMAX_OPCODE,
    RING_UPDATE_FMAX_OPERAND_FIELD_USAGE,
    RING_UPDATE_FMAX_UNIT_INST_TYPE,
    RING_UPDATE_FORWARDING_BITS,
)


EXPECTED_OPERAND_FIELD_USAGE = dict(RING_UPDATE_FMAX_OPERAND_FIELD_USAGE)


def main() -> None:
    patch_report = build_log10max_ring_update_inst_operand_patch_report()
    report = build_log10max_ring_update_inst_row_byte_candidate_report(patch_report)
    summary = summarize_log10max_ring_update_inst_row_byte_candidate_report(report)
    plan = report.to_plan()
    patch_plan = patch_report.to_plan()
    patches = {
        patch["patch_id"]: patch
        for patch in patch_plan["patches"]
    }
    failures: list[str] = []

    if summary["candidate_count"] != 30:
        failures.append(f"expected 30 row-byte candidates: {summary}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected phase distribution: {summary}")
    if summary["opcode_counts"] != {"FMAX": 30}:
        failures.append(f"expected only FMAX candidates: {summary}")
    if summary["decode_roundtrip_status_counts"] != {
        "candidate_row_body_decode_roundtrip": 30
    }:
        failures.append(f"expected candidate row-body decode roundtrip: {summary}")
    if summary["placement_status_counts"] != {"unplaced_candidate": 30}:
        failures.append(f"Phase 1 must leave candidates unplaced: {summary}")
    if summary["component_integration_status_counts"] != {"not_integrated": 30}:
        failures.append(f"Phase 1 must not integrate components: {summary}")
    if summary["raw_inst_t_byte_count"] != 30 * INST_RECORD_SIZE_BYTES:
        failures.append(f"unexpected candidate byte count: {summary}")
    if summary["blocker_ids"] != list(ROW_BODY_FIELD_BLOCKERS):
        failures.append(f"unexpected blockers: {summary}")
    if summary["row_body_candidate_bytes_claim"] is not True:
        failures.append("Phase 1 should claim only row-body candidate bytes")
    if summary["final_row_bytes_claim"] is not False:
        failures.append("Phase 1 must not claim final row bytes")
    if summary["component_integration_claim"] is not False:
        failures.append("Phase 1 must not claim component integration")
    if summary["runtime_ready"] is not False:
        failures.append("Phase 1 must keep runtime_ready false")
    if summary["uploadable"] is not False:
        failures.append("Phase 1 must keep uploadable false")

    seen_candidates: set[str] = set()
    seen_edges: set[str] = set()
    for candidate in plan["candidates"]:
        candidate_id = str(candidate["row_byte_candidate_id"])
        edge_id = str(candidate["source_ring_edge_id"])
        patch_id = str(candidate["source_patch_id"])
        if candidate_id in seen_candidates:
            failures.append(f"duplicate candidate id: {candidate_id}")
        seen_candidates.add(candidate_id)
        if edge_id in seen_edges:
            failures.append(f"duplicate ring edge: {edge_id}")
        seen_edges.add(edge_id)
        if patch_id not in patches:
            failures.append(f"candidate missing source patch: {candidate}")
            continue
        patch = patches[patch_id]
        decoded = candidate["decoded_fields"]
        pending = candidate["pending_decoded_fields"]
        if candidate["field_binding_record_id"] is not None:
            failures.append(f"Phase 1 should not invent field binding ids: {candidate}")
        if candidate["field_binding_status"] != "pending_inst_field_binding_record":
            failures.append(f"field binding must remain pending: {candidate}")
        if candidate["component_byte_offset"] is not None:
            failures.append(f"component_byte_offset must be None: {candidate}")
        if candidate["placement_status"] != "unplaced_candidate":
            failures.append(f"candidate must remain unplaced: {candidate}")
        if candidate["runtime_ready_claim"] is not False:
            failures.append(f"candidate must not claim runtime_ready: {candidate}")
        if candidate["uploadable_claim"] is not False:
            failures.append(f"candidate must not claim uploadable: {candidate}")
        if candidate["final_row_bytes_claim"] is not False:
            failures.append(f"candidate must not claim final row bytes: {candidate}")
        if candidate["component_integration_claim"] is not False:
            failures.append(f"candidate must not claim component integration: {candidate}")
        if candidate["raw_inst_t_byte_count"] != INST_RECORD_SIZE_BYTES:
            failures.append(f"unexpected row byte size: {candidate}")
        if not candidate["raw_inst_t_row_bytes_sha256"]:
            failures.append(f"missing row byte sha256: {candidate}")
        if candidate["decode_roundtrip_status"] != "candidate_row_body_decode_roundtrip":
            failures.append(f"unexpected decode status: {candidate}")
        if candidate["blocker_ids"] != list(ROW_BODY_FIELD_BLOCKERS):
            failures.append(f"unexpected candidate blockers: {candidate}")

        for field_name in OWNED_DECODED_FIELD_NAMES:
            if field_name not in decoded:
                failures.append(f"missing owned decoded field {field_name}: {candidate}")
        for field_name in PENDING_DECODED_FIELD_NAMES:
            if field_name not in pending:
                failures.append(f"missing pending decoded field {field_name}: {candidate}")

        if decoded.get("opcode") != RING_UPDATE_FMAX_OPCODE:
            failures.append(f"unexpected opcode: {candidate}")
        if decoded.get("unit_inst_type") != RING_UPDATE_FMAX_UNIT_INST_TYPE:
            failures.append(f"unexpected unit_inst_type: {candidate}")
        if decoded.get("latency") != RING_UPDATE_FMAX_LATENCY:
            failures.append(f"unexpected latency: {candidate}")
        if decoded.get("imms") != [0, 0, 0]:
            failures.append(f"FMAX candidate must not bind immediates: {candidate}")
        if decoded.get("src_operands_idx") != patch["src_operands_idx"]:
            failures.append(f"src operands must come from InstOperandPatch: {candidate}")
        if decoded.get("dst_operands_idx") != patch["dst_operands_idx"]:
            failures.append(f"dst operands must come from InstOperandPatch: {candidate}")
        if decoded.get("src_operands_idx", [None, None, None])[2] != 0:
            failures.append(f"src2 must be unused zero-fill: {candidate}")
        if decoded.get("dst_operands_idx", [None, None, None])[1:] != [0, 0]:
            failures.append(f"dst1/dst2 must be unused zero-fill: {candidate}")
        if decoded.get("forwarding_bits") != list(RING_UPDATE_FORWARDING_BITS):
            failures.append(f"unexpected forwarding bits: {candidate}")
        if decoded.get("bypass_bits") != list(RING_UPDATE_BYPASS_BITS):
            failures.append(f"unexpected bypass bits: {candidate}")
        if decoded.get("iter_exe_cond") != RING_UPDATE_FMAX_ITER_EXE_COND:
            failures.append(f"unexpected iter_exe_cond: {candidate}")
        if decoded.get("operand_field_usage") != EXPECTED_OPERAND_FIELD_USAGE:
            failures.append(f"unexpected operand field usage: {candidate}")
        if decoded.get("allocation_ids") != patch["allocation_ids"]:
            failures.append(f"candidate must preserve allocation ids: {candidate}")
        if pending.get("block_idx") != 0:
            failures.append(f"pending block_idx should stay placeholder-zero: {candidate}")
        if pending.get("end_inst") != 0:
            failures.append(f"pending end_inst should stay placeholder-zero: {candidate}")

    if failures:
        print("stream compiler log10max ring update InstRowByteCandidate check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max ring update InstRowByteCandidate check OK")
    print(f"candidate_count={summary['candidate_count']}")
    print(f"blocker_ids={summary['blocker_ids']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


if __name__ == "__main__":
    main()
