"""DFU3500 active instruction operand / route resource boundary checks."""

from __future__ import annotations

import struct
from pathlib import Path
from typing import Any, Mapping

from ..dfu_binary_checks.report import (
    CheckSpec,
    ReadinessLevel,
    ValidationIssue,
    ValidationReport,
    sha256_file,
)
from ...decoder.binary_layout import DfuBinaryProfile
from ...decoder.dfu3500_diagnostics import summarize_dfu3500_micc_control
from ...decoder.dfu3500_isa import annotate_opcode


DFU3500_OPERAND_RESOURCE_SPEC = CheckSpec(
    name="dfu3500_operand_resource",
    applies_to=(ReadinessLevel.RUNTIME_READY,),
    authoritative=True,
    required_inputs=("result/cbuf_file.bin", "result/micc_file.bin"),
)

MAX_OPERAND_RAM_AMOUNT_PER_PE = 1536
MAX_INST_BLOCK_AMOUNT_PER_PE = 32
PE_ARRAY_X_LEN = 4
PE_ARRAY_Y_LEN = 4


def run_dfu3500_operand_resource_check(
    artifact_root: Path,
    profile: DfuBinaryProfile,
    *,
    requested_gate: ReadinessLevel,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    input_paths: list[str] = []
    input_sha256: dict[str, str] = {}
    cbuf = _read_required_file(
        artifact_root,
        "result/cbuf_file.bin",
        input_paths,
        input_sha256,
        issues,
        "dfu3500_cbuf_missing",
    )
    micc = _read_required_file(
        artifact_root,
        "result/micc_file.bin",
        input_paths,
        input_sha256,
        issues,
        "dfu3500_micc_missing",
    )
    if profile.target != "dfu3500":
        issues.append(
            _issue(
                "dfu3500_operand_resource_profile_mismatch",
                "DFU3500 operand/resource check requires a dfu3500 profile.",
                None,
            )
        )
    if cbuf is not None and len(cbuf) != profile.files["cbuf"].size(profile):
        issues.append(
            _issue(
                "dfu3500_cbuf_size_mismatch",
                f"CBUF size is {len(cbuf)}, expected {profile.files['cbuf'].size(profile)}.",
                "result/cbuf_file.bin",
            )
        )
    if micc is not None and len(micc) != profile.files["micc"].size(profile):
        issues.append(
            _issue(
                "dfu3500_micc_size_mismatch",
                f"MICC size is {len(micc)}, expected {profile.files['micc'].size(profile)}.",
                "result/micc_file.bin",
            )
        )
    if cbuf is not None and micc is not None and not issues:
        _check_active_operand_resources(cbuf, micc, profile, issues)

    return ValidationReport(
        schema_version="dfu_validation_check_report_v1",
        check_name=DFU3500_OPERAND_RESOURCE_SPEC.name,
        status="fail" if issues else "pass",
        authoritative=DFU3500_OPERAND_RESOURCE_SPEC.applies_to_gate(requested_gate),
        requested_gate=requested_gate,
        profile_id=profile.profile_id,
        profile_sha256=profile.profile_sha256(),
        input_paths=tuple(input_paths),
        input_sha256=input_sha256,
        policy={
            "mode": "strict",
            "source": "dfu3500_active_cbuf_operand_and_route_resource_bounds",
            "max_operand_ram_amount_per_pe": MAX_OPERAND_RAM_AMOUNT_PER_PE,
            "max_inst_block_amount_per_pe": MAX_INST_BLOCK_AMOUNT_PER_PE,
        },
        issues=tuple(issues),
    )


def _check_active_operand_resources(
    cbuf: bytes,
    micc: bytes,
    profile: DfuBinaryProfile,
    issues: list[ValidationIssue],
) -> None:
    summary = summarize_dfu3500_micc_control(micc, profile=profile)
    if not summary.get("available"):
        issues.append(_issue("dfu3500_micc_summary_unavailable", str(summary.get("reason")), "result/micc_file.bin"))
        return
    inst_section = profile.files["cbuf"].sections[0]
    inst_size = profile.structs[inst_section.row_struct].size
    pe_count = inst_section.dimensions[0].size
    inst_limit = inst_section.dimensions[1].size
    subtask_section = profile.files["micc"].sections[1]
    subtask_size = profile.structs["sub_task_conf_info_t"].size
    exeblock_size = profile.structs["exeBlock_conf_info_t"].size
    for subtask in summary["subtasks"]:
        if not subtask["active_ish"]:
            continue
        task_id = int(subtask["task"])
        subtask_id = int(subtask["subtask"])
        block_amount = int(subtask.get("block_amount") or 0)
        subtask_offset = subtask_section.offset + (
            task_id * 8 + subtask_id
        ) * subtask_size
        exeblocks_offset = subtask_offset + 72
        for block_row in range(min(block_amount, 512)):
            block_base = exeblocks_offset + block_row * exeblock_size
            if not _u8(micc, block_base):
                continue
            conf_base = block_base + 48
            pe_x = _u64(micc, block_base + 16)
            pe_y = _u64(micc, block_base + 24)
            pe_index = pe_x * PE_ARRAY_Y_LEN + pe_y
            if pe_x >= PE_ARRAY_X_LEN or pe_y >= PE_ARRAY_Y_LEN or pe_index >= pe_count:
                continue
            stage_start_pcs = _u64_array(micc, conf_base + 16, 5)
            stage_amounts = _u64_array(micc, conf_base + 432, 4)
            for stage_index, amount in enumerate(stage_amounts):
                if amount == 0:
                    continue
                pc = stage_start_pcs[stage_index]
                if pc + amount > inst_limit:
                    continue
                for relative_index in range(amount):
                    inst_idx = pc + relative_index
                    row_offset = inst_section.offset + (pe_index * inst_limit + inst_idx) * inst_size
                    row = cbuf[row_offset : row_offset + inst_size]
                    _check_inst_resources(
                        row,
                        task_id,
                        subtask_id,
                        block_row,
                        int(pe_index),
                        stage_index,
                        int(inst_idx),
                        issues,
                    )


def _check_inst_resources(
    row: bytes,
    task_id: int,
    subtask_id: int,
    block_row: int,
    pe_index: int,
    stage_index: int,
    inst_idx: int,
    issues: list[ValidationIssue],
) -> None:
    if not any(row):
        return
    path = f"cbuf.insts[pe_index={pe_index}][inst_idx={inst_idx}]"
    opcode = struct.unpack_from("<I", row, 0)[0]
    annotation = annotate_opcode(opcode)
    if annotation.get("mnemonic") is None:
        return
    base_details = {
        "task_id": task_id,
        "subtask_id": subtask_id,
        "block_row": block_row,
        "stage_index": stage_index,
        "pe_index": pe_index,
        "inst_idx": inst_idx,
        "opcode": opcode,
        "mnemonic": annotation.get("mnemonic"),
    }
    for field_name, offset in (("src_operands_idx", 48), ("dst_operands_idx", 72)):
        values = _u64_array(row, offset, 3)
        for index, value in enumerate(values):
            if value >= MAX_OPERAND_RAM_AMOUNT_PER_PE:
                issues.append(
                    _issue(
                        "dfu3500_operand_index_out_of_range",
                        (
                            f"Active row {path} has {field_name}[{index}]={value}, "
                            f"outside PE operand RAM capacity {MAX_OPERAND_RAM_AMOUNT_PER_PE}."
                        ),
                        f"{path}.{field_name}[{index}]",
                        details={
                            **base_details,
                            "field": field_name,
                            "index": index,
                            "value": value,
                            "limit": MAX_OPERAND_RAM_AMOUNT_PER_PE,
                        },
                    )
                )
    dst_blocks = _u64_array(row, 168, 3)
    for index, value in enumerate(dst_blocks):
        if value >= MAX_INST_BLOCK_AMOUNT_PER_PE:
            issues.append(
                _issue(
                    "dfu3500_dst_block_index_out_of_range",
                    (
                        f"Active row {path} has dst_blocks_idx[{index}]={value}, "
                        f"outside PE block capacity {MAX_INST_BLOCK_AMOUNT_PER_PE}."
                    ),
                    f"{path}.dst_blocks_idx[{index}]",
                    details={
                        **base_details,
                        "index": index,
                        "value": value,
                        "limit": MAX_INST_BLOCK_AMOUNT_PER_PE,
                    },
                )
            )
    for index in range(3):
        pos_base = 96 + index * 24
        x, y, z = _u64_array(row, pos_base, 3)
        if x >= PE_ARRAY_X_LEN or y >= PE_ARRAY_Y_LEN or z != 0:
            issues.append(
                _issue(
                    "dfu3500_dst_pe_position_out_of_range",
                    (
                        f"Active row {path} has dst_pes_pos[{index}]=({x}, {y}, {z}), "
                        "outside DFU3500 4x4x1 PE mesh."
                    ),
                    f"{path}.dst_pes_pos[{index}]",
                    details={
                        **base_details,
                        "index": index,
                        "x": x,
                        "y": y,
                        "z": z,
                    },
                )
            )
    for field_name, offset in (
        ("forwarding_bits", 192),
        ("bypass_bits", 216),
    ):
        for index, value in enumerate(_u64_array(row, offset, 3)):
            if value not in {0, 1}:
                issues.append(
                    _issue(
                        "dfu3500_operand_flag_not_bool",
                        f"Active row {path} has {field_name}[{index}]={value}, expected 0 or 1.",
                        f"{path}.{field_name}[{index}]",
                        details={
                            **base_details,
                            "field": field_name,
                            "index": index,
                            "value": value,
                        },
                    )
                )
    for field_name, offset in (
        ("src_operands_fetched", 248),
        ("dst_operands_fetched", 251),
    ):
        for index, value in enumerate(row[offset : offset + 3]):
            if value not in {0, 1}:
                issues.append(
                    _issue(
                        "dfu3500_operand_fetch_flag_not_bool",
                        f"Active row {path} has {field_name}[{index}]={value}, expected 0 or 1.",
                        f"{path}.{field_name}[{index}]",
                        details={
                            **base_details,
                            "field": field_name,
                            "index": index,
                            "value": value,
                        },
                    )
                )


def _read_required_file(
    artifact_root: Path,
    rel_path: str,
    input_paths: list[str],
    input_sha256: dict[str, str],
    issues: list[ValidationIssue],
    missing_code: str,
) -> bytes | None:
    path = artifact_root / rel_path
    if not path.is_file():
        issues.append(_issue(missing_code, f"Missing {rel_path}.", rel_path))
        return None
    input_paths.append(rel_path)
    input_sha256[rel_path] = sha256_file(path)
    return path.read_bytes()


def _u8(data: bytes, offset: int) -> int:
    return struct.unpack_from("<B", data, offset)[0]


def _u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def _u64_array(data: bytes, offset: int, count: int) -> tuple[int, ...]:
    return struct.unpack_from("<" + "Q" * count, data, offset)


def _issue(
    code: str,
    message: str,
    path: str | None,
    *,
    details: Mapping[str, Any] | None = None,
) -> ValidationIssue:
    return ValidationIssue(
        severity="error",
        code=code,
        message=message,
        path=path,
        details=details or {},
    )
