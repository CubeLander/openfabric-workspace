"""Payload inventory and profile-size conformance checks."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Mapping

from .report import (
    CheckSpec,
    ReadinessLevel,
    ValidationIssue,
    ValidationReport,
    sha256_file,
)
from ...decoder.binary_layout import DfuBinaryProfile, FileLayout

ArtifactRole = Literal[
    "cbuf",
    "micc",
    "component",
    "manifest",
    "runtime_asset",
    "diagnostic_sidecar",
]


@dataclass(frozen=True)
class ArtifactFile:
    logical_name: str
    path: Path
    size: int
    sha256: str
    role: ArtifactRole


@dataclass(frozen=True)
class PayloadInventory:
    artifact_root: Path
    manifest_path: Path | None
    manifest: Mapping[str, str]
    files: Mapping[str, ArtifactFile]


PAYLOAD_CONFORMANCE_SPEC = CheckSpec(
    name="payload_conformance",
    applies_to=(ReadinessLevel.PACKAGE_COMPLETE, ReadinessLevel.RUNTIME_READY),
    authoritative=True,
    required_inputs=("artifact_root", "profile"),
)


def build_payload_inventory(artifact_root: Path) -> PayloadInventory:
    manifest_path = artifact_root / "MANIFEST.txt"
    manifest = _read_key_value_manifest(manifest_path) if manifest_path.exists() else {}
    files: dict[str, ArtifactFile] = {}
    if manifest_path.exists():
        files["MANIFEST.txt"] = ArtifactFile(
            logical_name="MANIFEST.txt",
            path=manifest_path,
            size=manifest_path.stat().st_size,
            sha256=sha256_file(manifest_path),
            role="manifest",
        )
    for path in sorted(p for p in artifact_root.rglob("*") if p.is_file()):
        if path == manifest_path:
            continue
        rel = path.relative_to(artifact_root).as_posix()
        role = _role_for_path(rel)
        files[rel] = ArtifactFile(
            logical_name=rel,
            path=path,
            size=path.stat().st_size,
            sha256=sha256_file(path),
            role=role,
        )
    return PayloadInventory(
        artifact_root=artifact_root,
        manifest_path=manifest_path if manifest_path.exists() else None,
        manifest=manifest,
        files=files,
    )


def run_payload_conformance(
    artifact_root: Path,
    profile: DfuBinaryProfile,
    *,
    requested_gate: ReadinessLevel,
) -> ValidationReport:
    inventory = build_payload_inventory(artifact_root)
    issues: list[ValidationIssue] = []
    input_paths: list[str] = []
    input_sha256: dict[str, str] = {}

    if inventory.manifest_path is None:
        issues.append(
            ValidationIssue(
                severity="error",
                code="manifest_missing",
                message="Payload is missing MANIFEST.txt.",
                path=str(artifact_root / "MANIFEST.txt"),
                remediation="Regenerate the payload manifest before claiming package readiness.",
            )
        )
    else:
        manifest_rel = inventory.manifest_path.relative_to(artifact_root).as_posix()
        input_paths.append(manifest_rel)
        input_sha256[manifest_rel] = sha256_file(inventory.manifest_path)

    for file_kind, file_layout in _required_final_files(profile).items():
        rel_path = f"result/{_canonical_payload_name(file_layout)}"
        artifact = inventory.files.get(rel_path)
        expected_size = file_layout.size(profile)
        if artifact is None:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="required_payload_file_missing",
                    message=f"Missing required {file_kind} payload file {rel_path}.",
                    path=rel_path,
                )
            )
            continue
        input_paths.append(rel_path)
        input_sha256[rel_path] = artifact.sha256
        if artifact.size != expected_size:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="payload_file_size_mismatch",
                    message=(
                        f"{rel_path} has size {artifact.size}, expected {expected_size} "
                        f"for profile {profile.profile_id}."
                    ),
                    path=rel_path,
                    details={
                        "actual_size": artifact.size,
                        "expected_size": expected_size,
                        "file_kind": file_kind,
                    },
                )
            )
        _check_manifest_claims(
            inventory,
            artifact,
            rel_path=rel_path,
            require_claims=True,
            issues=issues,
        )

    if requested_gate == ReadinessLevel.RUNTIME_READY:
        for rel_path in _runtime_ready_manifest_required_paths(inventory):
            if rel_path in input_sha256:
                continue
            artifact = inventory.files.get(rel_path)
            if artifact is None:
                continue
            input_paths.append(rel_path)
            input_sha256[rel_path] = artifact.sha256
            _check_manifest_claims(
                inventory,
                artifact,
                rel_path=rel_path,
                require_claims=True,
                issues=issues,
            )

    status = "fail" if issues else "pass"
    return ValidationReport(
        schema_version="dfu_validation_check_report_v1",
        check_name=PAYLOAD_CONFORMANCE_SPEC.name,
        status=status,
        authoritative=PAYLOAD_CONFORMANCE_SPEC.applies_to_gate(requested_gate),
        requested_gate=requested_gate,
        profile_id=profile.profile_id,
        profile_sha256=profile.profile_sha256(),
        input_paths=tuple(input_paths),
        input_sha256=input_sha256,
        policy={"mode": "strict", "source": "gate_default"},
        issues=tuple(issues),
    )


def _read_key_value_manifest(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line or line.lstrip().startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _required_final_files(profile: DfuBinaryProfile) -> dict[str, FileLayout]:
    return {
        name: layout
        for name, layout in profile.files.items()
        if name in {"cbuf", "micc"}
    }


def _canonical_payload_name(file_layout: FileLayout) -> str:
    if file_layout.aliases:
        return file_layout.aliases[0]
    return f"{file_layout.kind}_file.bin"


def _manifest_key(rel_path: str, suffix: str) -> str:
    return f"{rel_path.replace('/', '_')}_{suffix}"


def _check_manifest_claims(
    inventory: PayloadInventory,
    artifact: ArtifactFile,
    *,
    rel_path: str,
    require_claims: bool,
    issues: list[ValidationIssue],
) -> None:
    size_key = _manifest_key(rel_path, "size")
    sha_key = _manifest_key(rel_path, "sha256")
    if require_claims and size_key not in inventory.manifest:
        issues.append(
            ValidationIssue(
                severity="error",
                code="manifest_size_claim_missing",
                message=f"Manifest is missing size claim {size_key} for {rel_path}.",
                path="MANIFEST.txt",
                details={"key": size_key, "artifact": rel_path},
            )
        )
    if require_claims and sha_key not in inventory.manifest:
        issues.append(
            ValidationIssue(
                severity="error",
                code="manifest_sha256_claim_missing",
                message=f"Manifest is missing sha256 claim {sha_key} for {rel_path}.",
                path="MANIFEST.txt",
                details={"key": sha_key, "artifact": rel_path},
            )
        )
    if size_key in inventory.manifest:
        try:
            claimed_size = int(inventory.manifest[size_key])
        except ValueError:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="manifest_size_not_integer",
                    message=f"Manifest key {size_key} is not an integer.",
                    path="MANIFEST.txt",
                    details={"key": size_key, "value": inventory.manifest[size_key]},
                )
            )
        else:
            if claimed_size != artifact.size:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="manifest_size_mismatch",
                        message=(
                            f"Manifest claims {rel_path} size {claimed_size}, "
                            f"actual size is {artifact.size}."
                        ),
                        path="MANIFEST.txt",
                        details={"key": size_key},
                    )
                )
    if sha_key in inventory.manifest and inventory.manifest[sha_key] != artifact.sha256:
        issues.append(
            ValidationIssue(
                severity="error",
                code="manifest_sha256_mismatch",
                message=f"Manifest sha256 for {rel_path} does not match actual file.",
                path="MANIFEST.txt",
                details={
                    "key": sha_key,
                    "manifest_sha256": inventory.manifest[sha_key],
                    "actual_sha256": artifact.sha256,
                },
            )
        )


def _runtime_ready_manifest_required_paths(inventory: PayloadInventory) -> tuple[str, ...]:
    required = {
        rel_path
        for rel_path, artifact in inventory.files.items()
        if artifact.role in {"component", "runtime_asset"}
    }
    required.update(
        rel_path
        for rel_path in inventory.files
        if rel_path.startswith("config/")
        or rel_path.startswith("simulator_bin/")
        or rel_path.startswith("reference/")
    )
    return tuple(sorted(required))


def _role_for_path(rel_path: str) -> ArtifactRole:
    name = Path(rel_path).name
    if name == "cbuf_file.bin":
        return "cbuf"
    if name == "micc_file.bin":
        return "micc"
    if rel_path.startswith("runtime/"):
        return "runtime_asset"
    if rel_path.endswith(".json") or rel_path.endswith(".txt"):
        return "diagnostic_sidecar"
    return "component"
