"""Suite-level runner for DFU binary artifact validation."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from .payload_conformance import run_payload_conformance
from .profile_conformance import run_profile_conformance
from .runtime_memory_layout import run_runtime_memory_layout_check
from .runtime_readiness import run_runtime_readiness
from ..dfu3500_package_checks import (
    run_dfu3500_component_consistency_check,
    run_dfu3500_control_graph_check,
    run_dfu3500_instruction_span_check,
    run_dfu3500_memory_template_check,
    run_dfu3500_opcode_conformance_check,
    run_dfu3500_operand_resource_check,
)
from .report import ReadinessLevel, ValidationReport, ValidationSuiteReport, aggregate_reports
from .source_fingerprint_check import FingerprintMode, run_source_fingerprint_check
from ...decoder.binary_decoder import get_profile
from ...decoder.binary_layout import DfuBinaryProfile


def validate_payload(
    artifact_root: Path,
    *,
    requested_gate: ReadinessLevel,
    profile: DfuBinaryProfile | None = None,
    profile_id: str | None = None,
    source_root: Path | None = None,
    fingerprint_mode: FingerprintMode | None = None,
) -> ValidationSuiteReport:
    selected_profile = profile or get_profile(profile_id)
    reports: list[ValidationReport] = [
        run_profile_conformance(selected_profile, requested_gate=requested_gate),
        run_source_fingerprint_check(
            selected_profile,
            requested_gate=requested_gate,
            source_root=source_root,
            mode=fingerprint_mode,
        ),
    ]
    if requested_gate in {ReadinessLevel.PACKAGE_COMPLETE, ReadinessLevel.RUNTIME_READY}:
        reports.append(
            run_payload_conformance(
                artifact_root,
                selected_profile,
                requested_gate=requested_gate,
            )
        )
    if requested_gate == ReadinessLevel.RUNTIME_READY:
        reports.append(
            run_runtime_readiness(
                artifact_root,
                selected_profile,
                requested_gate=requested_gate,
            )
        )
        reports.append(
            run_runtime_memory_layout_check(
                artifact_root,
                selected_profile,
                requested_gate=requested_gate,
            )
        )
        if selected_profile.target == "dfu3500":
            reports.append(
                run_dfu3500_component_consistency_check(
                    artifact_root,
                    selected_profile,
                    requested_gate=requested_gate,
                )
            )
            reports.append(
                run_dfu3500_control_graph_check(
                    artifact_root,
                    selected_profile,
                    requested_gate=requested_gate,
                )
            )
            reports.append(
                run_dfu3500_instruction_span_check(
                    artifact_root,
                    selected_profile,
                    requested_gate=requested_gate,
                )
            )
            reports.append(
                run_dfu3500_opcode_conformance_check(
                    artifact_root,
                    selected_profile,
                    requested_gate=requested_gate,
                )
            )
            reports.append(
                run_dfu3500_operand_resource_check(
                    artifact_root,
                    selected_profile,
                    requested_gate=requested_gate,
                )
            )
            reports.append(
                run_dfu3500_memory_template_check(
                    artifact_root,
                    selected_profile,
                    requested_gate=requested_gate,
                )
            )
    manifest_path = artifact_root / "MANIFEST.txt"
    return ValidationSuiteReport(
        schema_version="dfu_validation_suite_report_v1",
        requested_gate=requested_gate,
        final_status=aggregate_reports(reports, requested_gate=requested_gate),
        artifact_root=str(artifact_root),
        manifest_path=str(manifest_path) if manifest_path.exists() else None,
        created_at_utc=datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        reports=tuple(reports),
    )
