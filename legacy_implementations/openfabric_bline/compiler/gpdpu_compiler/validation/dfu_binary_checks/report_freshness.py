"""Archived validation report freshness checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .report import (
    CheckSpec,
    ReadinessLevel,
    ValidationIssue,
    ValidationReport,
    sha256_file,
)
from ...decoder.binary_layout import DfuBinaryProfile


ARCHIVED_REPORT_FRESHNESS_SPEC = CheckSpec(
    name="archived_report_freshness",
    applies_to=(ReadinessLevel.RUNTIME_READY,),
    authoritative=True,
    required_inputs=("artifact_root", "validation/runtime_ready.json"),
)


def run_archived_report_freshness_check(
    artifact_root: Path,
    profile: DfuBinaryProfile,
    *,
    requested_gate: ReadinessLevel,
    report_rel_path: str = "validation/runtime_ready.json",
) -> ValidationReport:
    report_path = artifact_root / report_rel_path
    issues: list[ValidationIssue] = []
    input_paths: list[str] = []
    input_sha256: dict[str, str] = {}

    if not report_path.is_file():
        issues.append(
            _issue(
                "archived_validation_report_missing",
                f"Missing archived validation report {report_rel_path}.",
                report_rel_path,
            )
        )
    else:
        input_paths.append(report_rel_path)
        input_sha256[report_rel_path] = sha256_file(report_path)
        try:
            report_json = json.loads(report_path.read_text())
        except json.JSONDecodeError as exc:
            issues.append(
                _issue(
                    "archived_validation_report_json_invalid",
                    f"Archived validation report is invalid JSON: {exc}",
                    report_rel_path,
                )
            )
        else:
            _check_suite_report(
                artifact_root,
                report_json,
                input_paths=input_paths,
                input_sha256=input_sha256,
                issues=issues,
            )

    status = "fail" if issues else "pass"
    return ValidationReport(
        schema_version="dfu_validation_check_report_v1",
        check_name=ARCHIVED_REPORT_FRESHNESS_SPEC.name,
        status=status,
        authoritative=ARCHIVED_REPORT_FRESHNESS_SPEC.applies_to_gate(requested_gate),
        requested_gate=requested_gate,
        profile_id=profile.profile_id,
        profile_sha256=profile.profile_sha256(),
        input_paths=tuple(input_paths),
        input_sha256=input_sha256,
        policy={"mode": "strict", "source": "archived_validation_report"},
        issues=tuple(issues),
    )


def _check_suite_report(
    artifact_root: Path,
    report_json: Mapping[str, Any],
    *,
    input_paths: list[str],
    input_sha256: dict[str, str],
    issues: list[ValidationIssue],
) -> None:
    if report_json.get("schema_version") != "dfu_validation_suite_report_v1":
        issues.append(
            _issue(
                "archived_validation_report_schema_invalid",
                "Archived validation report has an unexpected schema_version.",
                "validation/runtime_ready.json",
                {"schema_version": report_json.get("schema_version")},
            )
        )
    if report_json.get("requested_gate") != ReadinessLevel.RUNTIME_READY.value:
        issues.append(
            _issue(
                "archived_validation_report_gate_invalid",
                "Archived validation report is not for runtime_ready.",
                "validation/runtime_ready.json",
                {"requested_gate": report_json.get("requested_gate")},
            )
        )
    if report_json.get("final_status") != "pass":
        issues.append(
            _issue(
                "archived_validation_report_not_pass",
                "Archived validation report did not pass.",
                "validation/runtime_ready.json",
                {"final_status": report_json.get("final_status")},
            )
        )
    reports = report_json.get("reports")
    if not isinstance(reports, list):
        issues.append(
            _issue(
                "archived_validation_report_checks_missing",
                "Archived validation report lacks a reports list.",
                "validation/runtime_ready.json",
            )
        )
        return
    for check_report in reports:
        if not isinstance(check_report, dict):
            issues.append(
                _issue(
                    "archived_validation_report_check_invalid",
                    "Archived validation report contains a non-object check report.",
                    "validation/runtime_ready.json",
                )
            )
            continue
        _check_report_inputs(
            artifact_root,
            check_report,
            input_paths=input_paths,
            input_sha256=input_sha256,
            issues=issues,
        )


def _check_report_inputs(
    artifact_root: Path,
    check_report: Mapping[str, Any],
    *,
    input_paths: list[str],
    input_sha256: dict[str, str],
    issues: list[ValidationIssue],
) -> None:
    check_name = str(check_report.get("check_name", "<unknown>"))
    reported_hashes = check_report.get("input_sha256")
    if not isinstance(reported_hashes, dict):
        issues.append(
            _issue(
                "archived_validation_report_input_hashes_missing",
                f"Check {check_name} lacks input_sha256 mapping.",
                "validation/runtime_ready.json",
                {"check_name": check_name},
            )
        )
        return
    for rel_path, expected_hash in sorted(reported_hashes.items()):
        if not isinstance(rel_path, str) or not isinstance(expected_hash, str):
            issues.append(
                _issue(
                    "archived_validation_report_input_hash_invalid",
                    f"Check {check_name} contains an invalid input hash entry.",
                    "validation/runtime_ready.json",
                    {"check_name": check_name, "rel_path": rel_path},
                )
            )
            continue
        path = artifact_root / rel_path
        if not path.is_file():
            issues.append(
                _issue(
                    "archived_validation_report_input_missing",
                    (
                        f"Check {check_name} references {rel_path}, but the "
                        "current payload no longer has that file."
                    ),
                    rel_path,
                    {"check_name": check_name},
                )
            )
            continue
        actual_hash = sha256_file(path)
        if rel_path not in input_sha256:
            input_paths.append(rel_path)
            input_sha256[rel_path] = actual_hash
        if actual_hash != expected_hash:
            issues.append(
                _issue(
                    "archived_validation_report_input_sha256_mismatch",
                    (
                        f"Check {check_name} recorded stale sha256 for "
                        f"{rel_path}."
                    ),
                    rel_path,
                    {
                        "check_name": check_name,
                        "reported_sha256": expected_hash,
                        "actual_sha256": actual_hash,
                    },
                )
            )


def _issue(
    code: str,
    message: str,
    path: str,
    details: Mapping[str, Any] | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        severity="error",
        code=code,
        message=message,
        path=path,
        details=details or {},
    )
