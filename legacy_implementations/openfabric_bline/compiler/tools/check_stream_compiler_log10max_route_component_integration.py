#!/usr/bin/env python3
"""Check Phase-4C log10max route-scope component integration candidate."""

from __future__ import annotations

from gpdpu_compiler.core.program_legacy_inst import INST_RECORD_SIZE_BYTES
from gpdpu_compiler.core.stream_compiler.log10max_route_component_placement import (
    LOG10MAX_OPERATOR_MANIFEST_MISSING,
    LOG10MAX_OPERATOR_RUNTIME_READY_GATE_NOT_AGGREGATED,
    ROUTE_COMPONENT_CANDIDATE_INTEGRATION_STATUS,
    ROUTE_COMPONENT_NAME,
    build_log10max_route_component_integration_report,
    summarize_log10max_route_component_integration_report,
)


EXPECTED_PHASE_COUNTS = {
    "col_broadcast": 12,
    "col_reduce": 12,
    "row_broadcast": 48,
    "row_reduce": 48,
}


def main() -> None:
    report = build_log10max_route_component_integration_report()
    summary = summarize_log10max_route_component_integration_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["integration_count"] != 120:
        failures.append(f"expected 120 route integration records: {summary}")
    if summary["route_slice_row_count"] != 120:
        failures.append(f"route slice should contain 120 rows: {summary}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected phase counts: {summary}")
    if summary["integration_status_counts"] != {
        ROUTE_COMPONENT_CANDIDATE_INTEGRATION_STATUS: 120
    }:
        failures.append(f"unexpected integration status: {summary}")
    if summary["micc_coherence_status_counts"] != {
        "route_slice_candidate_coherent": 120
    }:
        failures.append(f"unexpected scoped MICC status: {summary}")
    if summary["payload_manifest_status_counts"] != {
        "route_candidate_manifest_bound": 120
    }:
        failures.append(f"unexpected manifest status: {summary}")
    if summary["duplicate_component_byte_offset_count"] != 0:
        failures.append(f"component offsets must be unique: {summary}")
    if summary["overwritten_row_count"] != 0:
        failures.append(f"route candidate must not overwrite rows: {summary}")
    if summary["operator_manifest_bound_count"] != 0:
        failures.append(f"operator manifest must remain unbound: {summary}")
    if summary["runtime_ready_claim_count"] != 0:
        failures.append(f"runtime_ready must not be claimed: {summary}")
    if summary["uploadable_claim_count"] != 0:
        failures.append(f"uploadable must not be claimed: {summary}")
    if summary["raw_inst_t_byte_count"] != 120 * INST_RECORD_SIZE_BYTES:
        failures.append(f"unexpected byte count: {summary}")
    if summary["component_integration_scope"] != "route_rows_only":
        failures.append(f"integration scope must remain route-only: {summary}")
    if summary["route_component_integrated_claim"] is not True:
        failures.append(f"route slice integration claim expected: {summary}")
    if summary["runtime_ready"] is not False or summary["uploadable"] is not False:
        failures.append(f"readiness claims forbidden: {summary}")
    if not summary["route_slice_sha256"]:
        failures.append(f"route slice sha missing: {summary}")
    if LOG10MAX_OPERATOR_MANIFEST_MISSING not in summary["blocker_ids"]:
        failures.append(f"operator manifest blocker must remain: {summary}")
    if LOG10MAX_OPERATOR_RUNTIME_READY_GATE_NOT_AGGREGATED not in summary["blocker_ids"]:
        failures.append(f"runtime gate blocker must remain: {summary}")
    if "log10max_route_component_integration_missing" in summary["blocker_ids"]:
        failures.append(f"route integration blocker should be cleared: {summary}")
    if plan["operator_payload_manifest_entries"] != []:
        failures.append("route integration must not update operator payload manifest")

    offsets: set[int] = set()
    for record in plan["integration_records"]:
        if record["component_name"] != ROUTE_COMPONENT_NAME:
            failures.append(f"unexpected component name: {record}")
        if record["integration_scope"] != "route_rows_only":
            failures.append(f"unexpected integration scope: {record}")
        if record["integration_status"] != ROUTE_COMPONENT_CANDIDATE_INTEGRATION_STATUS:
            failures.append(f"unexpected integration status: {record}")
        if record["byte_count"] != INST_RECORD_SIZE_BYTES:
            failures.append(f"bad row byte size: {record}")
        if len(str(record["raw_inst_t_row_bytes_hex"])) != INST_RECORD_SIZE_BYTES * 2:
            failures.append(f"bad row bytes hex length: {record}")
        if record["raw_inst_t_row_bytes_sha256"] != record["copied_from_candidate_sha256"]:
            failures.append(f"row bytes must be copied, not repacked: {record}")
        if record["overwrite_policy"] != "reserved_slot_only":
            failures.append(f"bad overwrite policy: {record}")
        if record["overwritten_row_ids"] != []:
            failures.append(f"must not overwrite rows: {record}")
        if record["decode_roundtrip_status"] != "candidate_route_decode_roundtrip":
            failures.append(f"decode status must come from candidate row: {record}")
        if record["micc_coherence_scope"] != "route_rows_only":
            failures.append(f"bad MICC coherence scope: {record}")
        if record["micc_coherence_status"] != "route_slice_candidate_coherent":
            failures.append(f"bad MICC coherence status: {record}")
        if record["payload_manifest_status"] != "route_candidate_manifest_bound":
            failures.append(f"bad manifest status: {record}")
        if record["operator_manifest_bound"] is not False:
            failures.append(f"operator manifest must remain unbound: {record}")
        if record["runtime_ready"] is not False or record["uploadable"] is not False:
            failures.append(f"readiness claims forbidden: {record}")
        if record["blocker_ids"] != []:
            failures.append(f"per-row blockers should be empty: {record}")
        offset = int(record["component_byte_offset"])
        if offset in offsets:
            failures.append(f"duplicate component offset: {record}")
        offsets.add(offset)

    if failures:
        print("stream compiler log10max route component integration check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max route component integration check OK")
    print(f"integration_count={summary['integration_count']}")
    print(f"phase_counts={summary['phase_counts']}")
    print(f"route_slice_sha256={summary['route_slice_sha256']}")
    print(f"blocker_ids={summary['blocker_ids']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


if __name__ == "__main__":
    main()
