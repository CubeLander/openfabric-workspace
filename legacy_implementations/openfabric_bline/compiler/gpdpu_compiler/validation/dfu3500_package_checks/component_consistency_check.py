"""DFU3500 component-vs-combined-image consistency checks."""

from __future__ import annotations

from pathlib import Path

from ..dfu_binary_checks.report import (
    CheckSpec,
    ReadinessLevel,
    ValidationIssue,
    ValidationReport,
    sha256_file,
)
from ...decoder.binary_layout import DfuBinaryProfile, FileLayout, SectionLayout


COMPONENT_CONSISTENCY_SPEC = CheckSpec(
    name="dfu3500_component_consistency",
    applies_to=(ReadinessLevel.RUNTIME_READY,),
    authoritative=True,
    required_inputs=("artifact_root", "profile", "result_files", "component_files"),
)


def run_dfu3500_component_consistency_check(
    artifact_root: Path,
    profile: DfuBinaryProfile,
    *,
    requested_gate: ReadinessLevel,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    input_paths: list[str] = []
    input_sha256: dict[str, str] = {}

    if profile.target != "dfu3500":
        issues.append(
            _issue(
                "dfu3500_component_profile_mismatch",
                "DFU3500 component consistency check requires a dfu3500 profile.",
                None,
            )
        )
    else:
        for file_kind in ("cbuf", "micc"):
            file_layout = profile.files[file_kind]
            combined_rel = f"result/{_payload_file_name(file_layout)}"
            combined_path = artifact_root / combined_rel
            if not combined_path.is_file():
                issues.append(
                    _issue(
                        "dfu3500_combined_file_missing",
                        f"Missing combined {file_kind} image {combined_rel}.",
                        combined_rel,
                    )
                )
                continue
            input_paths.append(combined_rel)
            input_sha256[combined_rel] = sha256_file(combined_path)
            combined_bytes = combined_path.read_bytes()
            _check_config_copy(
                artifact_root,
                combined_rel=combined_rel,
                combined_bytes=combined_bytes,
                input_paths=input_paths,
                input_sha256=input_sha256,
                issues=issues,
            )
            for section in file_layout.sections:
                _check_section_components(
                    artifact_root,
                    profile=profile,
                    file_kind=file_kind,
                    section=section,
                    combined_bytes=combined_bytes,
                    input_paths=input_paths,
                    input_sha256=input_sha256,
                    issues=issues,
                )

    status = "fail" if issues else "pass"
    return ValidationReport(
        schema_version="dfu_validation_check_report_v1",
        check_name=COMPONENT_CONSISTENCY_SPEC.name,
        status=status,
        authoritative=COMPONENT_CONSISTENCY_SPEC.applies_to_gate(requested_gate),
        requested_gate=requested_gate,
        profile_id=profile.profile_id,
        profile_sha256=profile.profile_sha256(),
        input_paths=tuple(input_paths),
        input_sha256=input_sha256,
        policy={"mode": "strict", "source": "dfu3500_component_layout_profile"},
        issues=tuple(issues),
    )


def _check_config_copy(
    artifact_root: Path,
    *,
    combined_rel: str,
    combined_bytes: bytes,
    input_paths: list[str],
    input_sha256: dict[str, str],
    issues: list[ValidationIssue],
) -> None:
    config_rel = combined_rel.replace("result/", "config/", 1)
    config_path = artifact_root / config_rel
    if not config_path.is_file():
        issues.append(
            _issue(
                "dfu3500_config_file_missing",
                f"Missing config copy {config_rel} for {combined_rel}.",
                config_rel,
            )
        )
        return
    input_paths.append(config_rel)
    input_sha256[config_rel] = sha256_file(config_path)
    config_bytes = config_path.read_bytes()
    if config_bytes != combined_bytes:
        issues.append(
            _byte_mismatch_issue(
                code="dfu3500_config_result_mismatch",
                message=f"{config_rel} does not match {combined_rel}.",
                path=config_rel,
                left=config_bytes,
                right=combined_bytes,
                details={
                    "config_path": config_rel,
                    "result_path": combined_rel,
                },
            )
        )


def _check_section_components(
    artifact_root: Path,
    *,
    profile: DfuBinaryProfile,
    file_kind: str,
    section: SectionLayout,
    combined_bytes: bytes,
    input_paths: list[str],
    input_sha256: dict[str, str],
    issues: list[ValidationIssue],
) -> None:
    expected_bytes = combined_bytes[section.offset : section.end_offset(profile)]
    expected_size = section.size(profile)
    for component_name in section.component_file_names:
        component_rel = f"simulator_bin/{component_name}"
        component_path = artifact_root / component_rel
        if not component_path.is_file():
            issues.append(
                _issue(
                    "dfu3500_component_file_missing",
                    f"Missing component file {component_rel}.",
                    component_rel,
                    {
                        "file_kind": file_kind,
                        "section": section.name,
                        "expected_size": expected_size,
                    },
                )
            )
            continue
        input_paths.append(component_rel)
        input_sha256[component_rel] = sha256_file(component_path)
        component_bytes = component_path.read_bytes()
        if len(component_bytes) != expected_size:
            issues.append(
                _issue(
                    "dfu3500_component_size_mismatch",
                    (
                        f"{component_rel} has size {len(component_bytes)}, "
                        f"expected {expected_size} for {file_kind}.{section.name}."
                    ),
                    component_rel,
                    {
                        "file_kind": file_kind,
                        "section": section.name,
                        "actual_size": len(component_bytes),
                        "expected_size": expected_size,
                    },
                )
            )
            continue
        if component_bytes != expected_bytes:
            issues.append(
                _byte_mismatch_issue(
                    code="dfu3500_component_bytes_mismatch",
                    message=(
                        f"{component_rel} does not match the {file_kind}."
                        f"{section.name} section in the combined image."
                    ),
                    path=component_rel,
                    left=component_bytes,
                    right=expected_bytes,
                    details={
                        "file_kind": file_kind,
                        "section": section.name,
                        "combined_offset": section.offset,
                        "combined_end_offset": section.end_offset(profile),
                    },
                )
            )


def _payload_file_name(file_layout: FileLayout) -> str:
    if file_layout.aliases:
        return file_layout.aliases[0]
    return f"{file_layout.kind}_file.bin"


def _byte_mismatch_issue(
    *,
    code: str,
    message: str,
    path: str,
    left: bytes,
    right: bytes,
    details: dict[str, object],
) -> ValidationIssue:
    first_mismatch = _first_mismatch(left, right)
    enriched = dict(details)
    enriched.update(
        {
            "first_mismatch_offset": first_mismatch,
            "left_size": len(left),
            "right_size": len(right),
        }
    )
    if first_mismatch is not None:
        enriched["left_byte"] = left[first_mismatch] if first_mismatch < len(left) else None
        enriched["right_byte"] = (
            right[first_mismatch] if first_mismatch < len(right) else None
        )
    return _issue(code, message, path, enriched)


def _first_mismatch(left: bytes, right: bytes) -> int | None:
    for index, (left_byte, right_byte) in enumerate(zip(left, right)):
        if left_byte != right_byte:
            return index
    if len(left) != len(right):
        return min(len(left), len(right))
    return None


def _issue(
    code: str,
    message: str,
    path: str | None,
    details: dict[str, object] | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        severity="error",
        code=code,
        message=message,
        path=path,
        details=details or {},
    )
