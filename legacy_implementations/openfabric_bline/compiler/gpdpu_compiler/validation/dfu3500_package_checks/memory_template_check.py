"""DFU3500 active memory/template base-slot checks."""

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


DFU3500_MEMORY_TEMPLATE_SPEC = CheckSpec(
    name="dfu3500_memory_template",
    applies_to=(ReadinessLevel.RUNTIME_READY,),
    authoritative=True,
    required_inputs=("result/cbuf_file.bin", "result/micc_file.bin"),
)

BASE_ADDR_SLOT_COUNT = 4
DISABLED_BASE_ADDR_SENTINELS = {0xFFFFFFFF, 0xFFFFFFFFFFFFFFFF}
PE_ARRAY_Y_LEN = 4


def run_dfu3500_memory_template_check(
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
                "dfu3500_memory_template_profile_mismatch",
                "DFU3500 memory/template check requires a dfu3500 profile.",
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
        _check_active_memory_template_fields(cbuf, micc, profile, issues)

    return ValidationReport(
        schema_version="dfu_validation_check_report_v1",
        check_name=DFU3500_MEMORY_TEMPLATE_SPEC.name,
        status="fail" if issues else "pass",
        authoritative=DFU3500_MEMORY_TEMPLATE_SPEC.applies_to_gate(requested_gate),
        requested_gate=requested_gate,
        profile_id=profile.profile_id,
        profile_sha256=profile.profile_sha256(),
        input_paths=tuple(input_paths),
        input_sha256=input_sha256,
        policy={
            "mode": "strict",
            "source": "dfu3500_active_memory_rows_vs_instance_base_addr_slots",
            "base_addr_slot_count": BASE_ADDR_SLOT_COUNT,
            "disabled_sentinels": tuple(sorted(DISABLED_BASE_ADDR_SENTINELS)),
        },
        issues=tuple(issues),
    )


def _check_active_memory_template_fields(
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
    instance_section = profile.files["cbuf"].sections[2]
    instance_size = profile.structs["instance_conf_info_t"].size
    instance_task_slots = instance_section.dimensions[0].size
    instance_subtask_slots = instance_section.dimensions[1].size
    instances_per_subtask = instance_section.dimensions[2].size
    instance_limit = instance_task_slots * instance_subtask_slots * instances_per_subtask
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
        instances_amount = _u64(micc, subtask_offset + 8)
        instances_base_addr = _u64(micc, subtask_offset + 16)
        compact_instances_base_index = _compact_instance_base_index_from_addr(
            instances_base_addr,
            instance_size,
            instance_limit,
            task_id,
            subtask_id,
            issues,
        )
        if compact_instances_base_index is None:
            continue
        physical_instances_base_row = (
            task_id * instance_subtask_slots * instances_per_subtask
            + subtask_id * instances_per_subtask
        )
        exeblocks_offset = subtask_offset + 72
        for block_row in range(min(block_amount, 512)):
            block_base = exeblocks_offset + block_row * exeblock_size
            if not _u8(micc, block_base):
                continue
            conf_base = block_base + 48
            pe_x = _u64(micc, block_base + 16)
            pe_y = _u64(micc, block_base + 24)
            pe_index = pe_x * PE_ARRAY_Y_LEN + pe_y
            if pe_index >= pe_count:
                continue
            block_instances_amount = _u64(micc, conf_base + 400)
            active_instance_count = block_instances_amount or instances_amount
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
                    _check_inst_memory_template(
                        cbuf,
                        row,
                        profile,
                        task_id,
                        subtask_id,
                        block_row,
                        int(pe_index),
                        stage_index,
                        int(inst_idx),
                        int(physical_instances_base_row),
                        int(active_instance_count),
                        instance_section.offset,
                        instance_size,
                        instance_limit,
                        issues,
                    )


def _check_inst_memory_template(
    cbuf: bytes,
    row: bytes,
    profile: DfuBinaryProfile,
    task_id: int,
    subtask_id: int,
    block_row: int,
    pe_index: int,
    stage_index: int,
    inst_idx: int,
    instances_base_row: int,
    active_instance_count: int,
    instance_section_offset: int,
    instance_size: int,
    instance_limit: int,
    issues: list[ValidationIssue],
) -> None:
    if not any(row):
        return
    path = f"cbuf.insts[pe_index={pe_index}][inst_idx={inst_idx}]"
    opcode = struct.unpack_from("<I", row, 0)[0]
    annotation = annotate_opcode(opcode)
    if annotation.get("mnemonic") is None:
        return
    category = str(annotation.get("category"))
    mnemonic = str(annotation.get("mnemonic"))
    iter_exe_cond = _u64(row, 240)
    flow_ack = _u64(row, 264)
    if iter_exe_cond >= BASE_ADDR_SLOT_COUNT:
        issues.append(
            _issue(
                "dfu3500_iter_exe_cond_base_slot_out_of_range",
                (
                    f"Active row {path} has iter_exe_cond/base slot {iter_exe_cond}, "
                    f"outside base_addr[0..{BASE_ADDR_SLOT_COUNT - 1}]."
                ),
                f"{path}.iter_exe_cond",
                details=_details(task_id, subtask_id, block_row, pe_index, stage_index, inst_idx, opcode, mnemonic)
                | {"value": iter_exe_cond, "limit": BASE_ADDR_SLOT_COUNT},
            )
        )
    if flow_ack >= BASE_ADDR_SLOT_COUNT:
        issues.append(
            _issue(
                "dfu3500_flow_ack_base_slot_out_of_range",
                (
                    f"Active row {path} has flow_ack/base slot {flow_ack}, "
                    f"outside base_addr[0..{BASE_ADDR_SLOT_COUNT - 1}]."
                ),
                f"{path}.flow_ack",
                details=_details(task_id, subtask_id, block_row, pe_index, stage_index, inst_idx, opcode, mnemonic)
                | {"value": flow_ack, "limit": BASE_ADDR_SLOT_COUNT},
            )
        )
    base_slot: int | None = None
    if category in {"load", "store"}:
        base_slot = int(iter_exe_cond)
    elif category == "flow" and mnemonic == "COPY":
        base_slot = int(flow_ack)
    if base_slot is None or base_slot >= BASE_ADDR_SLOT_COUNT:
        return
    _check_instance_base_slot(
        cbuf,
        task_id,
        subtask_id,
        block_row,
        pe_index,
        stage_index,
        inst_idx,
        opcode,
        mnemonic,
        base_slot,
        instances_base_row,
        active_instance_count,
        instance_section_offset,
        instance_size,
        instance_limit,
        issues,
    )


def _check_instance_base_slot(
    cbuf: bytes,
    task_id: int,
    subtask_id: int,
    block_row: int,
    pe_index: int,
    stage_index: int,
    inst_idx: int,
    opcode: int,
    mnemonic: str,
    base_slot: int,
    instances_base_row: int,
    active_instance_count: int,
    instance_section_offset: int,
    instance_size: int,
    instance_limit: int,
    issues: list[ValidationIssue],
) -> None:
    if active_instance_count <= 0:
        issues.append(
            _issue(
                "dfu3500_memory_row_without_active_instance",
                f"Active memory row uses base_addr{base_slot} but its block/subtask has no active instances.",
                f"cbuf.insts[pe_index={pe_index}][inst_idx={inst_idx}]",
                details=_details(task_id, subtask_id, block_row, pe_index, stage_index, inst_idx, opcode, mnemonic)
                | {"base_slot": base_slot},
            )
        )
        return
    for instance_offset in range(active_instance_count):
        instance_row = instances_base_row + instance_offset
        if instance_row < 0 or instance_row >= instance_limit:
            issues.append(
                _issue(
                    "dfu3500_instance_row_out_of_range",
                    (
                        f"Active memory row references instance row {instance_row}, "
                        f"outside CBUF instance capacity {instance_limit}."
                    ),
                    f"cbuf.instances[instance_idx={instance_row}]",
                    details=_details(task_id, subtask_id, block_row, pe_index, stage_index, inst_idx, opcode, mnemonic)
                    | {
                        "base_slot": base_slot,
                        "instance_row": instance_row,
                        "instance_limit": instance_limit,
                    },
                )
            )
            continue
        base_addr_offset = instance_section_offset + instance_row * instance_size + base_slot * 8
        base_addr = _u64(cbuf, base_addr_offset)
        if base_addr in DISABLED_BASE_ADDR_SENTINELS:
            issues.append(
                _issue(
                    "dfu3500_memory_base_slot_disabled",
                    (
                        f"Active memory row uses base_addr{base_slot}, but instance "
                        f"row {instance_row} contains disabled sentinel 0x{base_addr:x}."
                    ),
                    f"cbuf.instances[instance_idx={instance_row}].base_addr[{base_slot}]",
                    details=_details(task_id, subtask_id, block_row, pe_index, stage_index, inst_idx, opcode, mnemonic)
                    | {
                        "base_slot": base_slot,
                        "instance_row": instance_row,
                        "base_addr": base_addr,
                    },
                )
            )


def _compact_instance_base_index_from_addr(
    instances_base_addr: int,
    instance_size: int,
    instance_limit: int,
    task_id: int,
    subtask_id: int,
    issues: list[ValidationIssue],
) -> int | None:
    """Validate compact MICC instance-table byte offset and return its index."""

    if instances_base_addr % instance_size:
        issues.append(
            _issue(
                "dfu3500_instance_base_addr_misaligned",
                (
                    "sub_task_conf_info_t.instances_conf_mem_based_addr "
                    f"{instances_base_addr} is not aligned to "
                    f"instance_conf_info_t size {instance_size}."
                ),
                (
                    "micc.subtasks"
                    f"[task_id={task_id}][subtask_id={subtask_id}]"
                    ".instances_conf_mem_based_addr"
                ),
                details={
                    "task_id": task_id,
                    "subtask_id": subtask_id,
                    "instances_conf_mem_based_addr": instances_base_addr,
                    "instance_row_size": instance_size,
                },
            )
        )
        return None
    base_row = instances_base_addr // instance_size
    if base_row >= instance_limit:
        issues.append(
            _issue(
                "dfu3500_instance_base_addr_out_of_range",
                (
                    "sub_task_conf_info_t.instances_conf_mem_based_addr "
                    f"{instances_base_addr} points at instance row {base_row}, "
                    f"outside CBUF instance capacity {instance_limit}."
                ),
                (
                    "micc.subtasks"
                    f"[task_id={task_id}][subtask_id={subtask_id}]"
                    ".instances_conf_mem_based_addr"
                ),
                details={
                    "task_id": task_id,
                    "subtask_id": subtask_id,
                    "instances_conf_mem_based_addr": instances_base_addr,
                    "instance_row": base_row,
                    "instance_limit": instance_limit,
                },
            )
        )
        return None
    return int(base_row)


def _details(
    task_id: int,
    subtask_id: int,
    block_row: int,
    pe_index: int,
    stage_index: int,
    inst_idx: int,
    opcode: int,
    mnemonic: str,
) -> dict[str, object]:
    return {
        "task_id": task_id,
        "subtask_id": subtask_id,
        "block_row": block_row,
        "stage_index": stage_index,
        "pe_index": pe_index,
        "inst_idx": inst_idx,
        "opcode": opcode,
        "mnemonic": mnemonic,
    }


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
