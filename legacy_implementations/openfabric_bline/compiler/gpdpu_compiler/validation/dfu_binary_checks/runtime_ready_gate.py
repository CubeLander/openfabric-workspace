"""Reusable runtime-ready gate for operator binary payloads."""

from __future__ import annotations

import json
from pathlib import Path

from ...decoder.binary_layout import DfuBinaryProfile
from .report import ReadinessLevel, ValidationSuiteReport
from .runner import validate_payload
from .source_fingerprint_check import FingerprintMode


class RuntimeReadyGateError(RuntimeError):
    """Raised when an operator payload cannot pass the runtime-ready gate."""

    def __init__(self, payload_dir: Path, report: ValidationSuiteReport, report_path: Path):
        self.payload_dir = payload_dir
        self.report = report
        self.report_path = report_path
        super().__init__(_format_gate_error(payload_dir, report, report_path))


def archive_runtime_ready_gate(
    payload_dir: Path,
    *,
    profile: DfuBinaryProfile | None = None,
    profile_id: str | None = None,
    source_root: Path | None = None,
    fingerprint_mode: FingerprintMode | None = None,
    report_path: Path | None = None,
    require_pass: bool = True,
) -> ValidationSuiteReport:
    """Validate ``payload_dir`` at RUNTIME_READY and archive the suite report.

    This is the common final gate for first-version operator payloads.  B-line
    binary writers and partner payload builders should call this after writing
    manifest, result/config/simulator_bin, runtime, and reference artifacts.
    """

    report = validate_payload(
        payload_dir,
        requested_gate=ReadinessLevel.RUNTIME_READY,
        profile=profile,
        profile_id=profile_id,
        source_root=source_root,
        fingerprint_mode=fingerprint_mode,
    )
    selected_report_path = report_path or (
        payload_dir / "validation" / "runtime_ready.json"
    )
    selected_report_path.parent.mkdir(parents=True, exist_ok=True)
    selected_report_path.write_text(
        json.dumps(report.to_json(), ensure_ascii=False, indent=2, sort_keys=True)
        + "\n"
    )
    if require_pass and report.final_status != "pass":
        raise RuntimeReadyGateError(payload_dir, report, selected_report_path)
    return report


def runtime_ready_blockers(report: ValidationSuiteReport) -> tuple[str, ...]:
    """Return stable ``check:issue`` blockers for concise operator errors."""

    blockers: list[str] = []
    for check_report in report.reports:
        if check_report.status not in {"fail", "blocked"}:
            continue
        blockers.extend(
            "%s:%s" % (check_report.check_name, issue.code)
            for issue in check_report.issues
            if issue.severity == "error"
        )
    return tuple(blockers)


def _format_gate_error(
    payload_dir: Path,
    report: ValidationSuiteReport,
    report_path: Path,
) -> str:
    blockers = runtime_ready_blockers(report)
    return (
        "payload validation failed for %s at gate %s: %s; report=%s"
        % (
            payload_dir,
            report.requested_gate.value,
            ", ".join(blockers) or report.final_status,
            report_path,
        )
    )

