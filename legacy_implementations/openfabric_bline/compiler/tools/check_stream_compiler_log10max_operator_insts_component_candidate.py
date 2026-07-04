#!/usr/bin/env python3
"""Check Phase-5B log10max operator insts component candidate."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.log10max_operator_payload import (
    EXPECTED_LOG10MAX_ROW_FAMILIES,
    LOG10MAX_OPERATOR_INSTS_COMPONENT_PARTIAL,
    build_log10max_operator_insts_component_candidate,
    summarize_log10max_operator_insts_component_candidate,
)


EXPECTED_PRESENT = ("route_copy", "ring_fmax_update")
EXPECTED_MISSING = tuple(
    family
    for family in EXPECTED_LOG10MAX_ROW_FAMILIES
    if family not in EXPECTED_PRESENT
)


def main() -> None:
    report = build_log10max_operator_insts_component_candidate()
    summary = summarize_log10max_operator_insts_component_candidate(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["component_status"] != "partial_operator_candidate":
        failures.append(f"component must remain partial: {summary}")
    if summary["integrated_row_count"] != 150:
        failures.append(f"route+FMAX rows should be integrated: {summary}")
    if summary["active_row_count"] != 150:
        failures.append(f"active row count mismatch: {summary}")
    if summary["reserved_row_count"] != 0:
        failures.append(f"reserved rows should not be invented: {summary}")
    if summary["zero_padding_row_count"] != 0:
        failures.append(f"zero padding should not be invented: {summary}")
    if summary["unowned_nonzero_row_count"] != 0:
        failures.append(f"unowned nonzero rows forbidden: {summary}")
    if tuple(summary["expected_row_families"]) != EXPECTED_LOG10MAX_ROW_FAMILIES:
        failures.append(f"expected row families mismatch: {summary}")
    if tuple(summary["present_row_families"]) != EXPECTED_PRESENT:
        failures.append(f"route_copy should be only present family: {summary}")
    if tuple(summary["folded_row_families"]) != ():
        failures.append(f"folded families should be empty: {summary}")
    if tuple(summary["missing_row_families"]) != EXPECTED_MISSING:
        failures.append(f"missing row families mismatch: {summary}")
    if summary["component_sha256"] is not None:
        failures.append(f"partial candidate must not set component_sha256: {summary}")
    if not summary["diagnostic_partial_component_sha256"]:
        failures.append(f"partial candidate needs diagnostic hash: {summary}")
    if summary["no_overwrite_status"] != "pass":
        failures.append(f"route-only no-overwrite status should pass: {summary}")
    if summary["decode_roundtrip_status"] != "pass":
        failures.append(f"present route rows should decode: {summary}")
    if summary["provenance_status"] != "pass":
        failures.append(f"present route rows should preserve provenance: {summary}")
    if summary["micc_coherence_status"] != "not_checked":
        failures.append(f"full-operator MICC coherence should not be claimed: {summary}")
    if summary["runtime_ready"] is not False or summary["uploadable"] is not False:
        failures.append(f"readiness claims forbidden: {summary}")
    if LOG10MAX_OPERATOR_INSTS_COMPONENT_PARTIAL not in summary["blocker_ids"]:
        failures.append(f"partial component blocker missing: {summary}")
    for family in EXPECTED_MISSING:
        blocker = f"log10max_operator_slice_{family}_missing"
        if blocker not in summary["blocker_ids"]:
            failures.append(f"missing slice blocker {blocker}: {summary}")
    if plan["operator_payload_manifest_entries"] != []:
        failures.append("partial component must not update operator payload manifest")

    if failures:
        print("stream compiler log10max operator insts component candidate check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max operator insts component candidate check OK")
    print(f"component_status={summary['component_status']}")
    print(f"present_row_families={summary['present_row_families']}")
    print(f"missing_row_families={summary['missing_row_families']}")
    print(f"component_sha256={summary['component_sha256']}")
    print(
        "diagnostic_partial_component_sha256="
        f"{summary['diagnostic_partial_component_sha256']}"
    )
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


if __name__ == "__main__":
    main()
