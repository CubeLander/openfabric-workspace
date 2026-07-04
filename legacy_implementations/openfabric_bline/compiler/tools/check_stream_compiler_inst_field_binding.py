#!/usr/bin/env python3
"""Check Phase-0 InstFieldBindingRecord records for log10max FMAX updates."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.inst_field_binding import (
    LOG10MAX_FMAX_FIELD_BINDING_PENDING_BLOCKERS,
    build_log10max_ring_update_inst_field_binding_report,
    summarize_inst_field_binding_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_ring_update_operands import (
    build_log10max_ring_update_inst_operand_patch_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_ring_update_template import (
    RING_UPDATE_BYPASS_BITS,
    RING_UPDATE_FMAX_ITER_EXE_COND,
    RING_UPDATE_FMAX_LATENCY,
    RING_UPDATE_FMAX_OPCODE,
    RING_UPDATE_FMAX_UNIT_INST_TYPE,
    RING_UPDATE_FORWARDING_BITS,
)


EXPECTED_PHASE_COUNTS = {
    "col_broadcast": 3,
    "col_reduce": 3,
    "row_broadcast": 12,
    "row_reduce": 12,
}
EXPECTED_MISSING_FIELDS = {
    "block_idx",
    "end_inst",
    "instruction_layout_plan_id",
    "exe_block_writer_plan_id",
    "component_placement_plan_id",
    "component_byte_offset",
}
EXPECTED_FIELD_PATHS = {
    "opCode",
    "unit_inst_type",
    "latency",
    "imms[0]",
    "imms[1]",
    "imms[2]",
    "forwarding_bits",
    "bypass_bits",
    "iter_exe_cond",
    "src_operands_idx[0]",
    "src_operands_idx[1]",
    "src_operands_idx[2]",
    "dst_operands_idx[0]",
    "dst_operands_idx[1]",
    "dst_operands_idx[2]",
    "block_idx",
    "stages_start_pc",
    "end_inst",
    "component_byte_offset",
}
EXPECTED_ZERO_FIELDS = {
    "imms[0]",
    "imms[1]",
    "imms[2]",
    "src_operands_idx[2]",
    "dst_operands_idx[1]",
    "dst_operands_idx[2]",
}
EXPECTED_PENDING_FIELDS = {
    "block_idx",
    "stages_start_pc",
    "end_inst",
    "component_byte_offset",
}


def main() -> None:
    patch_report = build_log10max_ring_update_inst_operand_patch_report()
    field_report = build_log10max_ring_update_inst_field_binding_report(
        patch_report=patch_report
    )
    patch_plan = patch_report.to_plan()
    field_plan = field_report.to_plan()
    summary = summarize_inst_field_binding_report(field_report)
    failures: list[str] = []

    if summary["record_count"] != 30:
        failures.append(f"expected 30 field-binding records: {summary}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected phase distribution: {summary}")
    if summary["field_binding_status_counts"] != {
        "candidate_field_bindings_pending_layout": 30
    }:
        failures.append(f"unexpected field-binding statuses: {summary}")
    if summary["blocker_ids"] != list(LOG10MAX_FMAX_FIELD_BINDING_PENDING_BLOCKERS):
        failures.append(f"unexpected blocker ids: {summary}")
    if summary["zero_with_evidence_count"] != 30 * len(EXPECTED_ZERO_FIELDS):
        failures.append(f"unexpected zero_with_evidence count: {summary}")
    if summary["pending_field_count"] != 30 * len(EXPECTED_PENDING_FIELDS):
        failures.append(f"unexpected pending field count: {summary}")
    if summary["raw_inst_t_byte_count"] != 0:
        failures.append(f"field binding report must not emit bytes: {summary}")
    if summary["row_body_bytes_claim"] is not False:
        failures.append("field binding report must not claim row-body bytes")
    if summary["final_row_bytes_claim"] is not False:
        failures.append("field binding report must not claim final row bytes")
    if summary["component_integration_claim"] is not False:
        failures.append("field binding report must not claim component integration")
    if summary["runtime_ready"] is not False or summary["uploadable"] is not False:
        failures.append("field binding report must keep runtime_ready/uploadable false")

    patches = {patch["row_candidate_id"]: patch for patch in patch_plan["patches"]}
    for record in field_plan["records"]:
        if record["base_materialization"] != "native_template_row":
            failures.append(f"unexpected base materialization: {record}")
        if record["route_endpoint_patch_id"] is not None:
            failures.append(f"FMAX update field binding must not bind route row: {record}")
        if record["instruction_layout_plan_id"] is not None:
            failures.append(f"instruction layout must remain pending: {record}")
        if record["exe_block_writer_plan_id"] is not None:
            failures.append(f"exeBlock writer plan must remain pending: {record}")
        if record["component_placement_plan_id"] is not None:
            failures.append(f"component placement must remain pending: {record}")
        if record["boundary_policy_id"] is not None:
            failures.append(f"boundary policy must remain pending: {record}")
        if record["placement_status"] != "unplaced_candidate":
            failures.append(f"unexpected placement status: {record}")
        if record["component_byte_offset"] is not None:
            failures.append(f"component byte offset must not be assigned: {record}")
        if record["raw_inst_t_byte_count"] != 0:
            failures.append(f"field binding must not contain bytes: {record}")
        if record["final_row_bytes_claim"] is not False:
            failures.append(f"record must not claim final bytes: {record}")
        if record["runtime_ready"] is not False or record["uploadable"] is not False:
            failures.append(f"record must keep runtime/uploadable false: {record}")
        if set(record["missing_fields"]) != EXPECTED_MISSING_FIELDS:
            failures.append(f"unexpected missing fields: {record}")
        if record["blocker_ids"] != list(LOG10MAX_FMAX_FIELD_BINDING_PENDING_BLOCKERS):
            failures.append(f"unexpected record blockers: {record}")

        bindings = {binding["field_path"]: binding for binding in record["field_bindings"]}
        if set(bindings) != EXPECTED_FIELD_PATHS:
            failures.append(f"unexpected field paths: {record}")
            continue

        _expect_value(failures, bindings, "opCode", RING_UPDATE_FMAX_OPCODE)
        _expect_value(
            failures, bindings, "unit_inst_type", RING_UPDATE_FMAX_UNIT_INST_TYPE
        )
        _expect_value(failures, bindings, "latency", RING_UPDATE_FMAX_LATENCY)
        _expect_value(failures, bindings, "forwarding_bits", RING_UPDATE_FORWARDING_BITS)
        _expect_value(failures, bindings, "bypass_bits", RING_UPDATE_BYPASS_BITS)
        _expect_value(failures, bindings, "iter_exe_cond", RING_UPDATE_FMAX_ITER_EXE_COND)

        for field_path in EXPECTED_ZERO_FIELDS:
            binding = bindings[field_path]
            if binding["owner_kind"] != "zero_with_evidence":
                failures.append(f"{field_path} must be zero_with_evidence: {record}")
            if binding["binding_status"] != "zero_with_evidence":
                failures.append(f"{field_path} must have zero evidence status: {record}")
            if binding["decoded_value"] != 0:
                failures.append(f"{field_path} must decode as zero: {record}")

        for field_path in EXPECTED_PENDING_FIELDS:
            binding = bindings[field_path]
            if binding["binding_status"] != "pending":
                failures.append(f"{field_path} must remain pending: {record}")
            if not binding["blockers"]:
                failures.append(f"{field_path} needs a pending blocker: {record}")

        patch = patches.get(record["row_candidate_id"])
        if patch is None:
            failures.append(f"missing patch for record: {record}")
            continue
        if record["operand_patch_id"] != patch["patch_id"]:
            failures.append(f"operand patch id mismatch: {record}")
        _expect_value(failures, bindings, "src_operands_idx[0]", patch["src_operands_idx"][0])
        _expect_value(failures, bindings, "src_operands_idx[1]", patch["src_operands_idx"][1])
        _expect_value(failures, bindings, "dst_operands_idx[0]", patch["dst_operands_idx"][0])
        for field_path in (
            "src_operands_idx[0]",
            "src_operands_idx[1]",
            "dst_operands_idx[0]",
        ):
            binding = bindings[field_path]
            if binding["owner_kind"] != "operand_patch":
                failures.append(f"{field_path} must be owned by operand patch: {record}")
            if binding["owner_id"] != patch["patch_id"]:
                failures.append(f"{field_path} owner id mismatch: {record}")

    if failures:
        print("stream compiler inst field binding check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler inst field binding check OK")
    print(f"record_count={summary['record_count']}")
    print(f"zero_with_evidence_count={summary['zero_with_evidence_count']}")
    print(f"pending_field_count={summary['pending_field_count']}")
    print(f"blocker_ids={summary['blocker_ids']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


def _expect_value(
    failures: list[str],
    bindings: dict[str, dict[str, object]],
    field_path: str,
    expected: object,
) -> None:
    actual = bindings[field_path]["decoded_value"]
    if actual != expected:
        failures.append(
            f"{field_path} mismatch: expected {expected!r}, got {actual!r}"
        )


if __name__ == "__main__":
    main()
