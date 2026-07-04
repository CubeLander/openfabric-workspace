"""Source fingerprint checks for decoder profile provenance."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from .report import CheckSpec, ReadinessLevel, ValidationIssue, ValidationReport, sha256_file
from ...decoder.binary_layout import DfuBinaryProfile

FingerprintMode = Literal["warn", "strict", "missing-ok"]

SOURCE_FINGERPRINT_SPEC = CheckSpec(
    name="source_fingerprint_check",
    applies_to=(
        ReadinessLevel.INSPECTABLE,
        ReadinessLevel.PACKAGE_COMPLETE,
        ReadinessLevel.RUNTIME_READY,
    ),
    authoritative=True,
    required_inputs=("profile",),
)


def default_fingerprint_mode(gate: ReadinessLevel) -> FingerprintMode:
    return "warn"


def run_source_fingerprint_check(
    profile: DfuBinaryProfile,
    *,
    requested_gate: ReadinessLevel,
    source_root: Path | None = None,
    mode: FingerprintMode | None = None,
) -> ValidationReport:
    selected_mode = mode or default_fingerprint_mode(requested_gate)
    issues: list[ValidationIssue] = []
    input_paths: list[str] = []
    input_sha256: dict[str, str] = {}

    if not profile.source_fingerprints:
        issues.append(
            ValidationIssue(
                severity="warning" if selected_mode != "strict" else "error",
                code="profile_source_fingerprints_missing",
                message="Profile does not declare source fingerprints.",
            )
        )
    elif source_root is None:
        if selected_mode != "missing-ok":
            issues.append(
                ValidationIssue(
                    severity="warning" if selected_mode == "warn" else "error",
                    code="source_root_missing",
                    message="No source root provided for fingerprint verification.",
                    remediation="Pass source_root or use missing-ok only for low readiness gates.",
                )
            )
    else:
        for rel_path, expected_hash in sorted(profile.source_fingerprints.items()):
            path = source_root / rel_path
            if not path.exists():
                issues.append(
                    ValidationIssue(
                        severity="warning" if selected_mode == "warn" else "error",
                        code="source_file_missing",
                        message=f"Source file {rel_path} is missing.",
                        path=str(path),
                    )
                )
                continue
            actual_hash = sha256_file(path)
            input_paths.append(str(path))
            input_sha256[str(path)] = actual_hash
            if actual_hash != expected_hash:
                issues.append(
                    ValidationIssue(
                        severity="warning" if selected_mode == "warn" else "error",
                        code="source_fingerprint_mismatch",
                        message=f"Source fingerprint mismatch for {rel_path}.",
                        path=str(path),
                        details={
                            "expected_sha256": expected_hash,
                            "actual_sha256": actual_hash,
                        },
                    )
                )

    if any(
        issue.code == "source_root_missing" and issue.severity == "error"
        for issue in issues
    ):
        status = "blocked"
    elif any(issue.severity == "error" for issue in issues):
        status = "fail"
    elif issues:
        status = "diagnostic_only"
    else:
        status = "pass"

    return ValidationReport(
        schema_version="dfu_validation_check_report_v1",
        check_name=SOURCE_FINGERPRINT_SPEC.name,
        status=status,
        authoritative=SOURCE_FINGERPRINT_SPEC.applies_to_gate(requested_gate)
        and selected_mode == "strict",
        requested_gate=requested_gate,
        profile_id=profile.profile_id,
        profile_sha256=profile.profile_sha256(),
        input_paths=tuple(input_paths),
        input_sha256=input_sha256,
        policy={
            "mode": selected_mode,
            "source": "argument" if mode else "gate_default",
            "requested_gate": requested_gate.value,
        },
        issues=tuple(issues),
    )
