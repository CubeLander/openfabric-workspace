"""DFU3500 active stage -> CBUF instruction span checks."""

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


DFU3500_INSTRUCTION_SPAN_SPEC = CheckSpec(
    name="dfu3500_instruction_span",
    applies_to=(ReadinessLevel.RUNTIME_READY,),
    authoritative=True,
    required_inputs=("result/cbuf_file.bin", "result/micc_file.bin"),
)

_STAGE_AMOUNT_FIELD_NAMES = (
    "ld_stage_inst_amount",
    "cal_stage_inst_amount",
    "flow_stage_inst_amount",
    "st_stage_inst_amount",
)


def run_dfu3500_instruction_span_check(
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
                "dfu3500_instruction_span_profile_mismatch",
                "DFU3500 instruction span check requires a dfu3500 profile.",
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
        _check_active_instruction_spans(cbuf, micc, profile, issues)

    status = "fail" if issues else "pass"
    return ValidationReport(
        schema_version="dfu_validation_check_report_v1",
        check_name=DFU3500_INSTRUCTION_SPAN_SPEC.name,
        status=status,
        authoritative=DFU3500_INSTRUCTION_SPAN_SPEC.applies_to_gate(requested_gate),
        requested_gate=requested_gate,
        profile_id=profile.profile_id,
        profile_sha256=profile.profile_sha256(),
        input_paths=tuple(input_paths),
        input_sha256=input_sha256,
        policy={"mode": "strict", "source": "dfu3500_micc_stage_to_cbuf_span"},
        issues=tuple(issues),
    )


def _check_active_instruction_spans(
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
    active_subtasks = [
        subtask for subtask in summary["subtasks"] if subtask["active_ish"]
    ]
    for subtask in active_subtasks:
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
            _check_block_instruction_spans(
                cbuf,
                micc,
                profile,
                task_id,
                subtask_id,
                block_row,
                block_base,
                inst_section.offset,
                inst_size,
                pe_count,
                inst_limit,
                issues,
            )


def _check_block_instruction_spans(
    cbuf: bytes,
    micc: bytes,
    profile: DfuBinaryProfile,
    task_id: int,
    subtask_id: int,
    block_row: int,
    block_base: int,
    inst_section_offset: int,
    inst_size: int,
    pe_count: int,
    inst_limit: int,
    issues: list[ValidationIssue],
) -> None:
    conf_base = block_base + 48
    pe_x = _u64(micc, block_base + 16)
    pe_y = _u64(micc, block_base + 24)
    pe_index = pe_x * 4 + pe_y
    path_base = (
        f"micc.subtasks[task={task_id}][subtask={subtask_id}]"
        f".exeBlocks_conf_info[{block_row}]"
    )
    if pe_x >= 4 or pe_y >= 4 or pe_index >= pe_count:
        issues.append(
            _issue(
                "dfu3500_exeblock_pe_dst_out_of_range",
                f"ExeBlock row {block_row} targets invalid PE ({pe_x}, {pe_y}).",
                f"{path_base}.pe_dst",
                details={"pe_x": pe_x, "pe_y": pe_y, "pe_index": pe_index},
            )
        )
        return
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
            row_offset = inst_section_offset + (pe_index * inst_limit + inst_idx) * inst_size
            row = cbuf[row_offset : row_offset + inst_size]
            _check_inst_row(
                row,
                task_id,
                subtask_id,
                block_row,
                int(pe_index),
                stage_index,
                int(inst_idx),
                issues,
            )


def _check_inst_row(
    row: bytes,
    task_id: int,
    subtask_id: int,
    block_row: int,
    pe_index: int,
    stage_index: int,
    inst_idx: int,
    issues: list[ValidationIssue],
) -> None:
    path = f"cbuf.insts[pe_index={pe_index}][inst_idx={inst_idx}]"
    if not any(row):
        issues.append(
            _issue(
                "dfu3500_stage_inst_row_zero",
                (
                    f"Active stage {stage_index} of ({task_id}, {subtask_id}) "
                    f"block row {block_row} points to all-zero CBUF inst row {path}."
                ),
                path,
                details={
                    "task_id": task_id,
                    "subtask_id": subtask_id,
                    "block_row": block_row,
                    "stage_index": stage_index,
                    "pe_index": pe_index,
                    "inst_idx": inst_idx,
                },
            )
        )
        return
    opcode = struct.unpack_from("<I", row, 0)[0]
    annotation = annotate_opcode(opcode)
    if annotation.get("mnemonic") is None:
        issues.append(
            _issue(
                "dfu3500_stage_inst_opcode_unknown",
                (
                    f"Active stage {stage_index} of ({task_id}, {subtask_id}) "
                    f"block row {block_row} points to unknown opCode {opcode} at {path}."
                ),
                f"{path}.opCode",
                details={
                    "task_id": task_id,
                    "subtask_id": subtask_id,
                    "block_row": block_row,
                    "stage_index": stage_index,
                    "pe_index": pe_index,
                    "inst_idx": inst_idx,
                    "opcode": opcode,
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
