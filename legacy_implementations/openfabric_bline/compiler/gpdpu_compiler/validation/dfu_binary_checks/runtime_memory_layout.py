"""Runtime-control memory-layout checks.

This check is stricter than runtime asset readiness.  It validates that the
payload-local RuntimeControlPlan describes sane SPM tensor regions and DMA
transfers before a payload is considered locally runtime-ready.
"""

from __future__ import annotations

import json
from itertools import combinations
from math import prod
from pathlib import Path
from typing import Any, Mapping

from .report import CheckSpec, ReadinessLevel, ValidationIssue, ValidationReport, sha256_file
from ...decoder.binary_layout import DfuBinaryProfile

RUNTIME_MEMORY_LAYOUT_SPEC = CheckSpec(
    name="runtime_memory_layout",
    applies_to=(ReadinessLevel.RUNTIME_READY,),
    authoritative=True,
    required_inputs=("artifact_root", "runtime_control"),
)

_DTYPE_SIZE_BYTES: Mapping[str, int] = {
    "bool": 1,
    "int8": 1,
    "uint8": 1,
    "fp16": 2,
    "float16": 2,
    "int16": 2,
    "uint16": 2,
    "bf16": 2,
    "fp32": 4,
    "float32": 4,
    "int32": 4,
    "uint32": 4,
    "fp64": 8,
    "float64": 8,
    "int64": 8,
    "uint64": 8,
}

_SPM_TENSOR_DIRECTIONS = {"input", "output"}


def run_runtime_memory_layout_check(
    artifact_root: Path,
    profile: DfuBinaryProfile,
    *,
    requested_gate: ReadinessLevel,
) -> ValidationReport:
    runtime_control_path = artifact_root / "runtime/riscv_src/riscv_control.json"
    input_paths: list[str] = []
    input_sha256: dict[str, str] = {}
    issues: list[ValidationIssue] = []

    if not runtime_control_path.exists():
        issues.append(
            ValidationIssue(
                severity="error",
                code="runtime_control_missing",
                message="Missing runtime/riscv_src/riscv_control.json.",
                path="runtime/riscv_src/riscv_control.json",
            )
        )
        return _report(profile, requested_gate, "blocked", input_paths, input_sha256, issues)

    input_paths.append("runtime/riscv_src/riscv_control.json")
    input_sha256["runtime/riscv_src/riscv_control.json"] = sha256_file(runtime_control_path)
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
        return _report(profile, requested_gate, "fail", input_paths, input_sha256, issues)

    if not isinstance(runtime_control, dict):
        issues.append(_issue("runtime_control_invalid", "runtime_control.json must contain an object."))
        return _report(profile, requested_gate, "fail", input_paths, input_sha256, issues)

    spm_size = runtime_control.get("spm_image_size_bytes")
    tensors = runtime_control.get("tensors")
    transfers = runtime_control.get("transfers")
    if not isinstance(spm_size, int) or spm_size <= 0:
        issues.append(_issue("runtime_spm_size_invalid", "spm_image_size_bytes must be a positive integer."))
        spm_size = 0
    if not isinstance(tensors, list):
        issues.append(_issue("runtime_control_tensors_missing", "tensors must be a list."))
        tensors = []
    if not isinstance(transfers, list):
        issues.append(_issue("runtime_control_transfers_missing", "transfers must be a list."))
        transfers = []

    tensor_by_name = _validate_tensors(tensors, int(spm_size), artifact_root, input_paths, input_sha256, issues)
    _validate_tensor_overlaps(tensor_by_name, issues)
    _validate_transfers(transfers, tensor_by_name, int(spm_size), artifact_root, input_paths, input_sha256, issues)

    status = "fail" if issues else "pass"
    return _report(profile, requested_gate, status, input_paths, input_sha256, issues)


def _validate_tensors(
    tensors: list[Any],
    spm_size: int,
    artifact_root: Path,
    input_paths: list[str],
    input_sha256: dict[str, str],
    issues: list[ValidationIssue],
) -> dict[str, Mapping[str, Any]]:
    tensor_by_name: dict[str, Mapping[str, Any]] = {}
    for index, tensor in enumerate(tensors):
        if not isinstance(tensor, dict):
            issues.append(_issue("runtime_tensor_invalid", f"tensor[{index}] must be an object."))
            continue
        name = tensor.get("name")
        if not isinstance(name, str) or not name:
            issues.append(_issue("runtime_tensor_name_invalid", f"tensor[{index}] must have a non-empty name."))
            continue
        if name in tensor_by_name:
            issues.append(_issue("runtime_tensor_name_duplicate", f"duplicate tensor name {name!r}."))
            continue
        tensor_by_name[name] = tensor
        direction = tensor.get("direction")
        _validate_tensor_region(name, tensor, spm_size, issues)
        _validate_tensor_shape_size(name, tensor, issues)
        if direction == "output":
            _validate_output_reference(name, tensor, artifact_root, input_paths, input_sha256, issues)

    return tensor_by_name


def _validate_tensor_region(
    name: str,
    tensor: Mapping[str, Any],
    spm_size: int,
    issues: list[ValidationIssue],
) -> None:
    byte_offset = tensor.get("byte_offset")
    byte_size = tensor.get("byte_size")
    dtype = tensor.get("dtype")
    if not isinstance(byte_offset, int) or byte_offset < 0:
        issues.append(_issue("runtime_tensor_offset_invalid", f"tensor {name} has invalid byte_offset."))
        return
    if not isinstance(byte_size, int) or byte_size <= 0:
        issues.append(_issue("runtime_tensor_size_invalid", f"tensor {name} has invalid byte_size."))
        return
    if spm_size > 0 and byte_offset + byte_size > spm_size:
        issues.append(
            _issue(
                "runtime_tensor_region_out_of_bounds",
                f"tensor {name} region [{byte_offset}, {byte_offset + byte_size}) exceeds SPM image size {spm_size}.",
                details={
                    "tensor": name,
                    "byte_offset": byte_offset,
                    "byte_size": byte_size,
                    "spm_image_size_bytes": spm_size,
                },
            )
        )
    if not isinstance(dtype, str) or dtype not in _DTYPE_SIZE_BYTES:
        issues.append(_issue("runtime_tensor_dtype_unknown", f"tensor {name} has unknown dtype {dtype!r}."))
        return
    alignment = _DTYPE_SIZE_BYTES[dtype]
    if byte_offset % alignment != 0:
        issues.append(
            _issue(
                "runtime_tensor_offset_alignment_invalid",
                f"tensor {name} byte_offset {byte_offset} is not aligned to dtype {dtype} size {alignment}.",
            )
        )
    if byte_size % alignment != 0:
        issues.append(
            _issue(
                "runtime_tensor_size_alignment_invalid",
                f"tensor {name} byte_size {byte_size} is not a multiple of dtype {dtype} size {alignment}.",
            )
        )


def _validate_tensor_shape_size(
    name: str,
    tensor: Mapping[str, Any],
    issues: list[ValidationIssue],
) -> None:
    dtype = tensor.get("dtype")
    shape = tensor.get("shape")
    byte_size = tensor.get("byte_size")
    if not isinstance(dtype, str) or dtype not in _DTYPE_SIZE_BYTES:
        return
    if not isinstance(shape, list) or not all(isinstance(dim, int) and dim > 0 for dim in shape):
        issues.append(_issue("runtime_tensor_shape_invalid", f"tensor {name} shape must be a list of positive integers."))
        return
    if not isinstance(byte_size, int) or byte_size <= 0:
        return
    expected_size = prod(shape) * _DTYPE_SIZE_BYTES[dtype]
    if expected_size != byte_size:
        issues.append(
            _issue(
                "runtime_tensor_shape_size_mismatch",
                f"tensor {name} shape/dtype imply {expected_size} bytes, but byte_size is {byte_size}.",
                details={"tensor": name, "expected_size": expected_size, "byte_size": byte_size},
            )
        )


def _validate_output_reference(
    name: str,
    tensor: Mapping[str, Any],
    artifact_root: Path,
    input_paths: list[str],
    input_sha256: dict[str, str],
    issues: list[ValidationIssue],
) -> None:
    reference_path = tensor.get("reference_path")
    byte_size = tensor.get("byte_size")
    if not isinstance(reference_path, str) or not reference_path:
        return
    path = artifact_root / reference_path
    if not path.exists():
        return
    _record_input_file(reference_path, path, input_paths, input_sha256)
    if isinstance(byte_size, int) and path.stat().st_size != byte_size:
        issues.append(
            _issue(
                "runtime_reference_size_mismatch",
                f"reference file for output tensor {name} has size {path.stat().st_size}, expected {byte_size}.",
                path=reference_path,
                details={"tensor": name, "actual_size": path.stat().st_size, "expected_size": byte_size},
            )
        )


def _validate_tensor_overlaps(
    tensor_by_name: Mapping[str, Mapping[str, Any]],
    issues: list[ValidationIssue],
) -> None:
    spm_tensors = [
        tensor
        for tensor in tensor_by_name.values()
        if tensor.get("direction") in _SPM_TENSOR_DIRECTIONS
        and isinstance(tensor.get("byte_offset"), int)
        and isinstance(tensor.get("byte_size"), int)
        and int(tensor.get("byte_size")) > 0
    ]
    for left, right in combinations(spm_tensors, 2):
        left_start = int(left["byte_offset"])
        left_end = left_start + int(left["byte_size"])
        right_start = int(right["byte_offset"])
        right_end = right_start + int(right["byte_size"])
        if max(left_start, right_start) < min(left_end, right_end):
            issues.append(
                _issue(
                    "runtime_tensor_region_overlap",
                    f"tensor {left.get('name')} overlaps tensor {right.get('name')}.",
                    details={
                        "left_tensor": left.get("name"),
                        "right_tensor": right.get("name"),
                        "left_range": [left_start, left_end],
                        "right_range": [right_start, right_end],
                    },
                )
            )


def _validate_transfers(
    transfers: list[Any],
    tensor_by_name: Mapping[str, Mapping[str, Any]],
    spm_size: int,
    artifact_root: Path,
    input_paths: list[str],
    input_sha256: dict[str, str],
    issues: list[ValidationIssue],
) -> None:
    seen_transfer_ids: set[str] = set()
    for index, transfer in enumerate(transfers):
        if not isinstance(transfer, dict):
            issues.append(_issue("runtime_transfer_invalid", f"transfer[{index}] must be an object."))
            continue
        transfer_id = transfer.get("transfer_id")
        if not isinstance(transfer_id, str) or not transfer_id:
            issues.append(_issue("runtime_transfer_id_invalid", f"transfer[{index}] must have a non-empty transfer_id."))
        elif transfer_id in seen_transfer_ids:
            issues.append(_issue("runtime_transfer_id_duplicate", f"duplicate transfer_id {transfer_id!r}."))
        else:
            seen_transfer_ids.add(transfer_id)

        tensor_name = transfer.get("tensor_name")
        if not isinstance(tensor_name, str) or tensor_name not in tensor_by_name:
            continue
        tensor = tensor_by_name[tensor_name]
        _validate_transfer_against_tensor(transfer, tensor, spm_size, artifact_root, input_paths, input_sha256, issues)


def _validate_transfer_against_tensor(
    transfer: Mapping[str, Any],
    tensor: Mapping[str, Any],
    spm_size: int,
    artifact_root: Path,
    input_paths: list[str],
    input_sha256: dict[str, str],
    issues: list[ValidationIssue],
) -> None:
    transfer_id = transfer.get("transfer_id")
    tensor_name = tensor.get("name")
    byte_size = transfer.get("byte_size")
    spm_offset = transfer.get("spm_offset")
    if not isinstance(byte_size, int) or byte_size <= 0:
        issues.append(_issue("runtime_transfer_size_invalid", f"transfer {transfer_id} has invalid byte_size."))
        return
    if not isinstance(spm_offset, int) or spm_offset < 0:
        issues.append(_issue("runtime_transfer_spm_offset_invalid", f"transfer {transfer_id} has invalid spm_offset."))
        return
    tensor_size = tensor.get("byte_size")
    tensor_offset = tensor.get("byte_offset")
    if isinstance(tensor_size, int) and byte_size != tensor_size:
        issues.append(
            _issue(
                "runtime_transfer_size_mismatch",
                f"transfer {transfer_id} byte_size {byte_size} does not match tensor {tensor_name} byte_size {tensor_size}.",
                details={"transfer_id": transfer_id, "tensor": tensor_name},
            )
        )
    if isinstance(tensor_offset, int) and spm_offset != tensor_offset:
        issues.append(
            _issue(
                "runtime_transfer_spm_offset_mismatch",
                f"transfer {transfer_id} spm_offset {spm_offset} does not match tensor {tensor_name} byte_offset {tensor_offset}.",
                details={"transfer_id": transfer_id, "tensor": tensor_name},
            )
        )
    if spm_size > 0 and spm_offset + byte_size > spm_size:
        issues.append(
            _issue(
                "runtime_transfer_region_out_of_bounds",
                f"transfer {transfer_id} region [{spm_offset}, {spm_offset + byte_size}) exceeds SPM image size {spm_size}.",
            )
        )
    direction = transfer.get("direction")
    phase = transfer.get("phase")
    tensor_direction = tensor.get("direction")
    if tensor_direction == "input" and direction != "ddr_to_spm":
        issues.append(_issue("runtime_input_transfer_direction_invalid", f"input tensor {tensor_name} must use ddr_to_spm transfer."))
    if tensor_direction == "output" and direction != "spm_to_ddr":
        issues.append(_issue("runtime_output_transfer_direction_invalid", f"output tensor {tensor_name} must use spm_to_ddr transfer."))
    if direction == "ddr_to_spm" and phase != "before_launch":
        issues.append(_issue("runtime_input_transfer_phase_invalid", f"ddr_to_spm transfer {transfer_id} must run before_launch."))
    if direction == "spm_to_ddr" and phase != "after_launch":
        issues.append(_issue("runtime_output_transfer_phase_invalid", f"spm_to_ddr transfer {transfer_id} must run after_launch."))
    if direction == "ddr_to_spm":
        _validate_input_image_transfer_range(transfer, artifact_root, input_paths, input_sha256, issues)


def _validate_input_image_transfer_range(
    transfer: Mapping[str, Any],
    artifact_root: Path,
    input_paths: list[str],
    input_sha256: dict[str, str],
    issues: list[ValidationIssue],
) -> None:
    path = artifact_root / "runtime/input_data.bin"
    if not path.exists():
        return
    rel_path = "runtime/input_data.bin"
    _record_input_file(rel_path, path, input_paths, input_sha256)
    ddr_offset = transfer.get("ddr_offset")
    byte_size = transfer.get("byte_size")
    if not isinstance(ddr_offset, int) or ddr_offset < 0:
        issues.append(_issue("runtime_transfer_ddr_offset_invalid", f"transfer {transfer.get('transfer_id')} has invalid ddr_offset."))
        return
    if not isinstance(byte_size, int) or byte_size <= 0:
        return
    required_size = ddr_offset + byte_size
    actual_size = path.stat().st_size
    if required_size > actual_size:
        issues.append(
            _issue(
                "runtime_input_data_transfer_out_of_bounds",
                f"transfer {transfer.get('transfer_id')} reads input_data range [0, {required_size}), but file size is {actual_size}.",
                path=rel_path,
                details={
                    "transfer_id": transfer.get("transfer_id"),
                    "ddr_offset": ddr_offset,
                    "byte_size": byte_size,
                    "actual_size": actual_size,
                },
            )
        )


def _record_input_file(
    rel_path: str,
    path: Path,
    input_paths: list[str],
    input_sha256: dict[str, str],
) -> None:
    if rel_path not in input_sha256:
        input_paths.append(rel_path)
        input_sha256[rel_path] = sha256_file(path)


def _report(
    profile: DfuBinaryProfile,
    requested_gate: ReadinessLevel,
    status: str,
    input_paths: list[str],
    input_sha256: dict[str, str],
    issues: list[ValidationIssue],
) -> ValidationReport:
    return ValidationReport(
        schema_version="dfu_validation_check_report_v1",
        check_name=RUNTIME_MEMORY_LAYOUT_SPEC.name,
        status=status,  # type: ignore[arg-type]
        authoritative=RUNTIME_MEMORY_LAYOUT_SPEC.applies_to_gate(requested_gate),
        requested_gate=requested_gate,
        profile_id=profile.profile_id,
        profile_sha256=profile.profile_sha256(),
        input_paths=tuple(input_paths),
        input_sha256=input_sha256,
        policy={"mode": "strict", "source": "runtime_control_memory_layout"},
        issues=tuple(issues),
    )


def _issue(
    code: str,
    message: str,
    *,
    path: str = "runtime/riscv_src/riscv_control.json",
    details: Mapping[str, Any] | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        severity="error",
        code=code,
        message=message,
        path=path,
        details=details or {},
    )
