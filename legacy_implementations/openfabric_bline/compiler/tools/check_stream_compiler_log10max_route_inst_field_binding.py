#!/usr/bin/env python3
"""Check Phase-2B log10max route physical row field bindings."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.log10max_route_inst_fields import (
    EXPECTED_PHYSICAL_PHASE_COUNTS,
    ROUTE_FLOW_ACK_BLOCKER,
    build_log10max_route_inst_field_binding_report,
    summarize_log10max_route_inst_field_binding_report,
)


REQUIRED_FIELDS = {
    "opCode",
    "unit_inst_type",
    "latency",
    "src_operands_idx[0]",
    "src_operands_idx[1]",
    "src_operands_idx[2]",
    "dst_operands_idx[0]",
    "dst_operands_idx[1]",
    "dst_operands_idx[2]",
    "dst_pes_pos[0]",
    "dst_blocks_idx[0]",
    "flow_ack",
    "block_idx",
    "end_inst",
    "stage",
    "local_pc",
    "component_byte_offset",
}


def main() -> None:
    report = build_log10max_route_inst_field_binding_report()
    summary = summarize_log10max_route_inst_field_binding_report(report)
    failures: list[str] = []

    if summary["record_count"] != 120:
        failures.append(f"expected 120 field binding records: {summary}")
    if summary["phase_counts"] != EXPECTED_PHYSICAL_PHASE_COUNTS:
        failures.append(f"unexpected phase distribution: {summary}")
    if summary["binding_status_counts"] != {"blocked": 120}:
        failures.append(f"flow_ack should keep all route rows blocked: {summary}")
    if summary["missing_field_counts"].get("flow_ack") != 120:
        failures.append(f"flow_ack must be explicit missing field: {summary}")
    if summary["missing_field_counts"].get("component_byte_offset") != 120:
        failures.append(f"component placement must remain explicit missing: {summary}")
    if summary["final_component_claim_count"] != 0:
        failures.append(f"field binding must not claim final component: {summary}")
    if ROUTE_FLOW_ACK_BLOCKER not in summary["blocker_ids"]:
        failures.append(f"flow_ack blocker must remain: {summary}")
    if summary["runtime_ready"] is not False or summary["uploadable"] is not False:
        failures.append(f"field binding report must stay non-ready: {summary}")

    for record in report.records:
        owners = dict(record.field_owner_ids)
        statuses = dict(record.field_owner_status)
        missing = set(record.missing_fields)
        absent = REQUIRED_FIELDS - set(owners)
        if absent:
            failures.append(f"field owner ids missing {sorted(absent)}: {record}")
        absent_status = REQUIRED_FIELDS - set(statuses)
        if absent_status:
            failures.append(f"field owner statuses missing {sorted(absent_status)}: {record}")
        if statuses.get("flow_ack") != "blocked":
            failures.append(f"flow_ack must be blocked, not guessed: {record}")
        if owners.get("flow_ack"):
            failures.append(f"flow_ack policy id must not be guessed: {record}")
        if "flow_ack" not in missing:
            failures.append(f"flow_ack must be listed in missing_fields: {record}")
        if statuses.get("src_operands_idx[1]") != "zero_with_evidence":
            failures.append(f"src1 needs explicit zero evidence: {record}")
        if statuses.get("src_operands_idx[2]") != "zero_with_evidence":
            failures.append(f"src2 needs explicit zero evidence: {record}")
        if statuses.get("dst_operands_idx[1]") != "zero_with_evidence":
            failures.append(f"dst1 needs explicit zero evidence: {record}")
        if statuses.get("dst_operands_idx[2]") != "zero_with_evidence":
            failures.append(f"dst2 needs explicit zero evidence: {record}")
        if record.final_component_claim:
            failures.append(f"final component claim forbidden: {record}")
        if record.runtime_ready or record.uploadable:
            failures.append(f"field binding must not claim readiness: {record}")

    if failures:
        print("stream compiler log10max route inst field binding check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max route inst field binding check OK")
    print(f"record_count={summary['record_count']}")
    print(f"missing_field_counts={summary['missing_field_counts']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


if __name__ == "__main__":
    main()
