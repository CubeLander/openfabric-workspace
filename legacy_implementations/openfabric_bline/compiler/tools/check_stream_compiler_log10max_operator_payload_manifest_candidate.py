#!/usr/bin/env python3
"""Check Phase-5D log10max operator payload manifest candidate."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.log10max_operator_payload import (
    LOG10MAX_OPERATOR_PAYLOAD_MANIFEST_BLOCKED,
    REQUIRED_LOG10MAX_PAYLOAD_FILE_ROLES,
    build_log10max_operator_payload_manifest_candidate,
    summarize_log10max_operator_payload_manifest_candidate,
)


def main() -> None:
    report = build_log10max_operator_payload_manifest_candidate()
    summary = summarize_log10max_operator_payload_manifest_candidate(report)
    failures: list[str] = []

    if tuple(summary["required_file_roles"]) != REQUIRED_LOG10MAX_PAYLOAD_FILE_ROLES:
        failures.append(f"required payload file roles mismatch: {summary}")
    if tuple(summary["present_file_roles"]) != ():
        failures.append(f"no final payload files should be present: {summary}")
    if tuple(summary["missing_file_roles"]) != REQUIRED_LOG10MAX_PAYLOAD_FILE_ROLES:
        failures.append(f"all payload file roles should be missing: {summary}")
    if summary["component_manifest_status"] != "blocked":
        failures.append(f"component manifest must remain blocked: {summary}")
    if summary["operator_payload_manifest_status"] != "blocked":
        failures.append(f"operator payload manifest must remain blocked: {summary}")
    if summary["readiness_claim"] != "blocked":
        failures.append(f"readiness claim must remain blocked: {summary}")
    if summary["component_hashes"] != {}:
        failures.append(f"partial diagnostic hashes must not be components: {summary}")
    if "diagnostic_partial_insts_component" not in summary["diagnostic_hashes"]:
        failures.append(f"diagnostic partial hash should be recorded separately: {summary}")
    if summary["runtime_asset_status"] != "blocked":
        failures.append(f"runtime assets must remain blocked: {summary}")
    if summary["simict_status"] != "not_run":
        failures.append(f"SimICT status must remain not_run: {summary}")
    if summary["numerical_status"] != "not_checked":
        failures.append(f"numerical status must remain not_checked: {summary}")
    if summary["runtime_ready"] is not False or summary["uploadable"] is not False:
        failures.append(f"readiness claims forbidden: {summary}")
    if LOG10MAX_OPERATOR_PAYLOAD_MANIFEST_BLOCKED not in summary["blocker_ids"]:
        failures.append(f"payload manifest blocker missing: {summary}")
    blockers_by_layer = summary["blockers_by_layer"]
    for layer in (
        "slice_set",
        "insts_component",
        "control_coherence",
        "payload_manifest",
        "runtime_assets",
        "numerical",
    ):
        if layer not in blockers_by_layer:
            failures.append(f"missing blockers_by_layer entry {layer}: {summary}")
    for role in REQUIRED_LOG10MAX_PAYLOAD_FILE_ROLES:
        blocker = f"log10max_payload_file_role_{role}_missing"
        if blocker not in summary["blocker_ids"]:
            failures.append(f"missing payload file-role blocker {blocker}: {summary}")

    if failures:
        print("stream compiler log10max operator payload manifest check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max operator payload manifest check OK")
    print(f"readiness_claim={summary['readiness_claim']}")
    print(f"missing_file_roles={summary['missing_file_roles']}")
    print(f"blockers_by_layer={summary['blockers_by_layer']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


if __name__ == "__main__":
    main()
