"""Payload-local runtime-control/readiness checks.

This check validates that a payload carries coherent local runtime assets.  It is
not a SimICT execution proof and does not validate operator math.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .payload_conformance import build_payload_inventory
from .report import CheckSpec, ReadinessLevel, ValidationIssue, ValidationReport, sha256_file
from ...decoder.binary_layout import DfuBinaryProfile

RUNTIME_READINESS_SPEC = CheckSpec(
    name="runtime_readiness",
    applies_to=(ReadinessLevel.RUNTIME_READY,),
    authoritative=True,
    required_inputs=("artifact_root", "runtime_control"),
)

REQUIRED_RUNTIME_ASSETS = (
    "runtime/input_data.bin",
    "runtime/riscv_src/riscv_control.json",
    "runtime/riscv_src/riscv/testarm.c",
    "runtime/riscv_src/csv_generate/conf.h",
)


def run_runtime_readiness(
    artifact_root: Path,
    profile: DfuBinaryProfile,
    *,
    requested_gate: ReadinessLevel,
) -> ValidationReport:
    inventory = build_payload_inventory(artifact_root)
    issues: list[ValidationIssue] = []
    input_paths: list[str] = []
    input_sha256: dict[str, str] = {}

    for rel_path in REQUIRED_RUNTIME_ASSETS:
        artifact = inventory.files.get(rel_path)
        if artifact is None:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="runtime_asset_missing",
                    message=f"Missing required runtime asset {rel_path}.",
                    path=rel_path,
                )
            )
            continue
        input_paths.append(rel_path)
        input_sha256[rel_path] = artifact.sha256
        _check_manifest_claims(inventory.manifest, rel_path, artifact.size, artifact.sha256, issues)

    runtime_control_path = artifact_root / "runtime/riscv_src/riscv_control.json"
    runtime_control: Mapping[str, Any] | None = None
    if runtime_control_path.exists():
        try:
            runtime_control = json.loads(runtime_control_path.read_text())
        except json.JSONDecodeError as exc:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="runtime_control_json_invalid",
                    message=f"runtime_control.json is invalid JSON: {exc}",
                    path="runtime/riscv_src/riscv_control.json",
                )
            )
    if runtime_control is not None:
        _validate_runtime_control_shape(runtime_control, artifact_root, issues)

    status = "fail" if issues else "pass"
    return ValidationReport(
        schema_version="dfu_validation_check_report_v1",
        check_name=RUNTIME_READINESS_SPEC.name,
        status=status,
        authoritative=RUNTIME_READINESS_SPEC.applies_to_gate(requested_gate),
        requested_gate=requested_gate,
        profile_id=profile.profile_id,
        profile_sha256=profile.profile_sha256(),
        input_paths=tuple(input_paths),
        input_sha256=input_sha256,
        policy={"mode": "strict", "source": "payload_local_runtime_metadata"},
        issues=tuple(issues),
    )


def _manifest_key(rel_path: str, suffix: str) -> str:
    return f"{rel_path.replace('/', '_')}_{suffix}"


def _check_manifest_claims(
    manifest: Mapping[str, str],
    rel_path: str,
    size: int,
    file_sha256: str,
    issues: list[ValidationIssue],
) -> None:
    size_key = _manifest_key(rel_path, "size")
    sha_key = _manifest_key(rel_path, "sha256")
    if size_key in manifest:
        try:
            claimed_size = int(manifest[size_key])
        except ValueError:
            issues.append(
                ValidationIssue(
                    severity="error",
                    code="manifest_size_not_integer",
                    message=f"Manifest key {size_key} is not an integer.",
                    path="MANIFEST.txt",
                )
            )
        else:
            if claimed_size != size:
                issues.append(
                    ValidationIssue(
                        severity="error",
                        code="manifest_size_mismatch",
                        message=(
                            f"Manifest claims {rel_path} size {claimed_size}, "
                            f"actual size is {size}."
                        ),
                        path="MANIFEST.txt",
                        details={"key": size_key},
                    )
                )
    if sha_key in manifest and manifest[sha_key] != file_sha256:
        issues.append(
            ValidationIssue(
                severity="error",
                code="manifest_sha256_mismatch",
                message=f"Manifest sha256 for {rel_path} does not match actual file.",
                path="MANIFEST.txt",
                details={"key": sha_key},
            )
        )


def _validate_runtime_control_shape(
    runtime_control: Mapping[str, Any],
    artifact_root: Path,
    issues: list[ValidationIssue],
) -> None:
    tensors = runtime_control.get("tensors")
    transfers = runtime_control.get("transfers")
    launches = runtime_control.get("launches")
    if not isinstance(tensors, list):
        issues.append(_runtime_issue("runtime_control_tensors_missing", "tensors must be a list"))
        tensors = []
    if not isinstance(transfers, list):
        issues.append(_runtime_issue("runtime_control_transfers_missing", "transfers must be a list"))
        transfers = []
    if not isinstance(launches, list) or len(launches) != 1:
        issues.append(
            _runtime_issue(
                "runtime_control_launch_count_invalid",
                "runtime_control must declare exactly one launch for current generated RISC-V control.",
            )
        )
        launches = [] if not isinstance(launches, list) else launches

    tensor_by_name = {
        str(tensor.get("name")): tensor
        for tensor in tensors
        if isinstance(tensor, dict) and tensor.get("name") is not None
    }
    if len(tensor_by_name) != len(tensors):
        issues.append(_runtime_issue("runtime_control_tensor_names_invalid", "tensor names must be unique and present"))

    transfer_tensor_names = {
        str(transfer.get("tensor_name"))
        for transfer in transfers
        if isinstance(transfer, dict) and transfer.get("tensor_name") is not None
    }
    for transfer in transfers:
        if not isinstance(transfer, dict):
            issues.append(_runtime_issue("runtime_control_transfer_invalid", "transfer entry must be an object"))
            continue
        tensor_name = str(transfer.get("tensor_name"))
        if tensor_name not in tensor_by_name:
            issues.append(
                _runtime_issue(
                    "runtime_control_transfer_unknown_tensor",
                    f"transfer references unknown tensor {tensor_name!r}",
                )
            )

    output_names: set[str] = set()
    for tensor in tensors:
        if not isinstance(tensor, dict):
            continue
        name = str(tensor.get("name"))
        direction = tensor.get("direction")
        byte_size = tensor.get("byte_size")
        if not isinstance(byte_size, int) or byte_size <= 0:
            issues.append(_runtime_issue("runtime_control_tensor_size_invalid", f"tensor {name} has invalid byte_size"))
        if direction == "output":
            output_names.add(name)
            reference_path = tensor.get("reference_path")
            if not isinstance(reference_path, str) or not reference_path:
                issues.append(_runtime_issue("runtime_output_reference_missing", f"output tensor {name} lacks reference_path"))
            elif not (artifact_root / reference_path).is_file():
                issues.append(
                    _runtime_issue(
                        "runtime_output_reference_file_missing",
                        f"reference file for output tensor {name} is missing",
                        path=reference_path,
                    )
                )
        elif direction == "input" and name not in transfer_tensor_names:
            issues.append(_runtime_issue("runtime_input_transfer_missing", f"input tensor {name} has no DMA transfer"))

    output_transfer_names = {
        str(transfer.get("tensor_name"))
        for transfer in transfers
        if isinstance(transfer, dict)
        and transfer.get("direction") == "spm_to_ddr"
        and transfer.get("phase") == "after_launch"
    }
    for output_name in sorted(output_names):
        if output_name not in output_transfer_names:
            issues.append(
                _runtime_issue(
                    "runtime_output_transfer_missing",
                    f"output tensor {output_name} has no after_launch spm_to_ddr transfer",
                )
            )

    for launch in launches:
        if not isinstance(launch, dict):
            issues.append(_runtime_issue("runtime_control_launch_invalid", "launch entry must be an object"))
            continue
        task_count = launch.get("task_count")
        if not isinstance(task_count, int) or task_count <= 0:
            issues.append(_runtime_issue("runtime_control_task_count_invalid", "launch task_count must be positive"))


def _runtime_issue(code: str, message: str, *, path: str = "runtime/riscv_src/riscv_control.json") -> ValidationIssue:
    return ValidationIssue(
        severity="error",
        code=code,
        message=message,
        path=path,
    )
