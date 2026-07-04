"""Gate-oriented validation report contract for DFU binary artifacts.

Decoder modules explain bytes.  This package judges whether a payload has enough
local evidence for a requested readiness gate.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence


class ReadinessLevel(str, Enum):
    """Payload-local artifact readiness gate."""

    INSPECTABLE = "inspectable"
    PACKAGE_COMPLETE = "package_complete"
    RUNTIME_READY = "runtime_ready"


READINESS_ORDER: tuple[ReadinessLevel, ...] = (
    ReadinessLevel.INSPECTABLE,
    ReadinessLevel.PACKAGE_COMPLETE,
    ReadinessLevel.RUNTIME_READY,
)

ReportStatus = Literal["pass", "fail", "blocked", "diagnostic_only"]
SuiteStatus = Literal["pass", "fail", "blocked"]
IssueSeverity = Literal["info", "warning", "error"]


@dataclass(frozen=True)
class ValidationIssue:
    severity: IssueSeverity
    code: str
    message: str
    path: str | None = None
    details: Mapping[str, Any] = field(default_factory=dict)
    remediation: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "path": self.path,
            "details": dict(self.details),
            "remediation": self.remediation,
        }


@dataclass(frozen=True)
class CheckSpec:
    name: str
    applies_to: tuple[ReadinessLevel, ...]
    authoritative: bool
    default_policy: Mapping[str, Any] = field(default_factory=dict)
    required_inputs: tuple[str, ...] = ()

    def applies_to_gate(self, gate: ReadinessLevel) -> bool:
        return gate in self.applies_to


@dataclass(frozen=True)
class ValidationReport:
    schema_version: str
    check_name: str
    status: ReportStatus
    authoritative: bool
    requested_gate: ReadinessLevel | None
    profile_id: str | None
    profile_sha256: str | None
    input_paths: tuple[str, ...]
    input_sha256: Mapping[str, str]
    policy: Mapping[str, Any]
    issues: tuple[ValidationIssue, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "check_name": self.check_name,
            "status": self.status,
            "authoritative": self.authoritative,
            "requested_gate": self.requested_gate.value if self.requested_gate else None,
            "profile_id": self.profile_id,
            "profile_sha256": self.profile_sha256,
            "input_paths": list(self.input_paths),
            "input_sha256": dict(sorted(self.input_sha256.items())),
            "policy": dict(self.policy),
            "issues": [issue.to_json() for issue in self.issues],
        }


@dataclass(frozen=True)
class ValidationSuiteReport:
    schema_version: str
    requested_gate: ReadinessLevel
    final_status: SuiteStatus
    artifact_root: str
    manifest_path: str | None
    created_at_utc: str
    reports: tuple[ValidationReport, ...]

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "requested_gate": self.requested_gate.value,
            "final_status": self.final_status,
            "artifact_root": self.artifact_root,
            "manifest_path": self.manifest_path,
            "created_at_utc": self.created_at_utc,
            "reports": [report.to_json() for report in self.reports],
        }


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def stable_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def aggregate_reports(
    reports: Sequence[ValidationReport],
    *,
    requested_gate: ReadinessLevel,
) -> SuiteStatus:
    relevant_authoritative = [
        report
        for report in reports
        if report.authoritative and report.requested_gate == requested_gate
    ]
    if not relevant_authoritative:
        return "blocked"
    if any(report.status == "fail" for report in relevant_authoritative):
        return "fail"
    if any(report.status == "blocked" for report in relevant_authoritative):
        return "blocked"
    if all(report.status == "pass" for report in relevant_authoritative):
        return "pass"
    return "blocked"
