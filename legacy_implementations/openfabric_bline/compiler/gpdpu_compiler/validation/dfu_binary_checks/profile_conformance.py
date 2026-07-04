"""Profile self-conformance checks for DFU binary layouts."""

from __future__ import annotations

from .report import CheckSpec, ReadinessLevel, ValidationIssue, ValidationReport
from ...decoder.binary_layout import DfuBinaryProfile

PROFILE_CONFORMANCE_SPEC = CheckSpec(
    name="profile_conformance",
    applies_to=(ReadinessLevel.PACKAGE_COMPLETE, ReadinessLevel.RUNTIME_READY),
    authoritative=True,
    required_inputs=("profile",),
)


def run_profile_conformance(
    profile: DfuBinaryProfile,
    *,
    requested_gate: ReadinessLevel,
) -> ValidationReport:
    errors = profile.validate()
    issues = tuple(
        ValidationIssue(
            severity="error",
            code="profile_layout_invalid",
            message=message,
            remediation="Fix the decoder profile metadata before validating artifacts.",
        )
        for message in errors
    )
    status = "fail" if issues else "pass"
    return ValidationReport(
        schema_version="dfu_validation_check_report_v1",
        check_name=PROFILE_CONFORMANCE_SPEC.name,
        status=status,
        authoritative=PROFILE_CONFORMANCE_SPEC.applies_to_gate(requested_gate),
        requested_gate=requested_gate,
        profile_id=profile.profile_id,
        profile_sha256=profile.profile_sha256(),
        input_paths=(),
        input_sha256={},
        policy={"mode": "strict", "source": "gate_default"},
        issues=issues,
    )
