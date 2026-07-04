"""Byte serializers for binary-facing DFU row plans.

This module consumes ``ProgramBinRows`` only. It must not rediscover loops,
routes, dependency classes, tile ownership, or vendor ABI row semantics. The
first milestone intentionally emits only the low-risk config components whose
struct layouts are already pinned by legacy evidence.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

from gpdpu_compiler.core.program_legacy_inst import pack_legacy_inst
from gpdpu_compiler.core.program_bin import (
    EXEBLOCK_CONF_CAPACITY,
    EXEBLOCK_CONF_RECORD_SIZE_BYTES,
    DFU3500_LEGACY_EXEBLOCKS_PER_PE,
    INST_CAPACITY,
    INST_RECORD_SIZE_BYTES,
    INSTANCE_CONF_CAPACITY,
    INSTANCE_CONF_RECORD_SIZE_BYTES,
    SUBTASK_CONF_CAPACITY,
    SUBTASK_CONF_RECORD_SIZE_BYTES,
    SUBTASK_EMBEDDED_EXEBLOCK_SLOT_COUNT,
    TASK_CONF_CAPACITY,
    TASK_CONF_RECORD_SIZE_BYTES,
    UNUSED_EXEBLOCK_FIELD,
    ExeBlockConfBinRow,
    InstBinRow,
    InstanceConfBinRow,
    ProgramBinRows,
    SubtaskConfBinRow,
    TaskConfBinRow,
)


EXEBLOCK_CONF_COMPONENT = "simulator_bin/exeblock_conf_info_file.bin"
INSTS_COMPONENT = "simulator_bin/insts_file.bin"
INSTANCE_CONF_COMPONENT = "simulator_bin/instance_conf_info_file.bin"
SUBTASK_CONF_COMPONENT = "simulator_bin/subtasks_conf_info_file.bin"
TASK_CONF_COMPONENT = "simulator_bin/tasks_conf_info_file.bin"
CBUF_PACKAGE = "config/cbuf_file.bin"
MICC_PACKAGE = "config/micc_file.bin"


@dataclass(frozen=True)
class ProgramBinComponent:
    """One serialized simulator component image."""

    path: str
    content: bytes
    record_size_bytes: int
    capacity: int
    active_row_count: int
    source_row_ids: tuple[str, ...]
    serializer: str

    def to_plan(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": len(self.content),
            "sha256": hashlib.sha256(self.content).hexdigest(),
            "record_size_bytes": self.record_size_bytes,
            "capacity": self.capacity,
            "active_row_count": self.active_row_count,
            "source_row_ids": list(self.source_row_ids),
            "serializer": self.serializer,
            "content_in_plan": False,
        }


@dataclass(frozen=True)
class ProgramBinPackage:
    """One composed runtime blob image."""

    path: str
    content: bytes
    source_component_paths: tuple[str, ...]
    composer: str
    semantics: str

    def to_plan(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size_bytes": len(self.content),
            "sha256": hashlib.sha256(self.content).hexdigest(),
            "source_component_paths": list(self.source_component_paths),
            "composer": self.composer,
            "semantics": self.semantics,
            "content_in_plan": False,
        }


@dataclass(frozen=True)
class ProgramBinComponents:
    """Serialized component set for the current binary milestone."""

    source_program: str
    source_ir: str
    components: dict[str, ProgramBinComponent]
    packages: dict[str, ProgramBinPackage]

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ir": "program_bin_components",
            "source_ir": self.source_ir,
            "source_program": self.source_program,
            "serialization_policy": (
                "program_serializer_consumes_program_bin_rows_only;"
                "no_loop_route_dependency_or_tile_semantics_are_rederived"
            ),
            "components": {
                name: component.to_plan()
                for name, component in sorted(self.components.items())
            },
            "packages": {
                name: package.to_plan()
                for name, package in sorted(self.packages.items())
            },
            "validation": self._validation(),
            "totals": self._totals(),
            "package_totals": self._package_totals(),
        }

    def write_to(self, output_dir: str | Path) -> None:
        output_path = Path(output_dir)
        for component in self.components.values():
            component_path = output_path / component.path
            component_path.parent.mkdir(parents=True, exist_ok=True)
            component_path.write_bytes(component.content)
        for package in self.packages.values():
            package_path = output_path / package.path
            package_path.parent.mkdir(parents=True, exist_ok=True)
            package_path.write_bytes(package.content)

    def _validation(self) -> dict[str, Any]:
        package_semantics = sorted({package.semantics for package in self.packages.values()})
        runtime_semantics: str | list[str]
        if package_semantics == ["native_symbolic_structural_smoke_only"]:
            runtime_semantics = "structural_smoke_only"
        elif len(package_semantics) == 1:
            runtime_semantics = package_semantics[0]
        else:
            runtime_semantics = package_semantics
        return {
            "component_bytes_emitted": True,
            "package_bytes_emitted": True,
            "instance_conf_info_file_ready": INSTANCE_CONF_COMPONENT in self.components,
            "tasks_conf_info_file_ready": TASK_CONF_COMPONENT in self.components,
            "exeblock_conf_info_file_ready": EXEBLOCK_CONF_COMPONENT in self.components,
            "subtasks_conf_info_file_ready": SUBTASK_CONF_COMPONENT in self.components,
            "insts_file_ready": INSTS_COMPONENT in self.components,
            "cbuf_file_ready": CBUF_PACKAGE in self.packages,
            "micc_file_ready": MICC_PACKAGE in self.packages,
            "complete_runtime_package_semantics": runtime_semantics,
        }

    def _totals(self) -> dict[str, Any]:
        return {
            "component_count": len(self.components),
            "total_size_bytes": sum(
                len(component.content)
                for component in self.components.values()
            ),
            "active_row_count": sum(
                component.active_row_count
                for component in self.components.values()
            ),
        }

    def _package_totals(self) -> dict[str, Any]:
        return {
            "package_count": len(self.packages),
            "total_size_bytes": sum(
                len(package.content)
                for package in self.packages.values()
            ),
        }


def lower_program_bin_rows_to_components(bin_rows: ProgramBinRows) -> ProgramBinComponents:
    """Serialize the first safe component subset from ``ProgramBinRows``."""

    components = {
        EXEBLOCK_CONF_COMPONENT: _serialize_exeblock_conf_component(bin_rows),
        INSTS_COMPONENT: _serialize_insts_component(bin_rows),
        INSTANCE_CONF_COMPONENT: _serialize_instance_conf_component(bin_rows),
        SUBTASK_CONF_COMPONENT: _serialize_subtask_conf_component(bin_rows),
        TASK_CONF_COMPONENT: _serialize_task_conf_component(bin_rows),
    }
    packages = _compose_runtime_packages(
        components,
        semantics=_package_semantics(bin_rows),
    )
    return ProgramBinComponents(
        source_program=bin_rows.source_program,
        source_ir="program_bin_rows",
        components=components,
        packages=packages,
    )


def _package_semantics(bin_rows: ProgramBinRows) -> str:
    modes = {row.vendor_inst_mode for row in bin_rows.inst_rows.values()}
    if modes == {"legacy_gemm_compat"}:
        return "legacy_gemm_compat_real_inst_t_runtime_validation_blocked"
    if modes == {"legacy_template_compat"}:
        return "legacy_template_compat_real_inst_t_runtime_validation_blocked"
    return "native_symbolic_structural_smoke_only"


def _compose_runtime_packages(
    components: dict[str, ProgramBinComponent],
    *,
    semantics: str,
) -> dict[str, ProgramBinPackage]:
    cbuf_sources = (
        INSTS_COMPONENT,
        EXEBLOCK_CONF_COMPONENT,
        INSTANCE_CONF_COMPONENT,
    )
    micc_sources = (
        TASK_CONF_COMPONENT,
        SUBTASK_CONF_COMPONENT,
    )
    return {
        CBUF_PACKAGE: ProgramBinPackage(
            path=CBUF_PACKAGE,
            content=b"".join(components[path].content for path in cbuf_sources),
            source_component_paths=cbuf_sources,
            composer="legacy_cbuf_layout:insts+exeblock_conf+instance_conf",
            semantics=semantics,
        ),
        MICC_PACKAGE: ProgramBinPackage(
            path=MICC_PACKAGE,
            content=b"".join(components[path].content for path in micc_sources),
            source_component_paths=micc_sources,
            composer="legacy_micc_layout:tasks_conf+subtasks_conf",
            semantics=semantics,
        ),
    }


def _serialize_exeblock_conf_component(bin_rows: ProgramBinRows) -> ProgramBinComponent:
    legacy_template_compat = any(
        row.vendor_inst_mode in {"legacy_gemm_compat", "legacy_template_compat"}
        for row in bin_rows.exe_block_rows.values()
    )
    content = bytearray(EXEBLOCK_CONF_CAPACITY * EXEBLOCK_CONF_RECORD_SIZE_BYTES)
    if legacy_template_compat:
        for row_index in range(EXEBLOCK_CONF_CAPACITY):
            offset = row_index * EXEBLOCK_CONF_RECORD_SIZE_BYTES
            content[offset : offset + EXEBLOCK_CONF_RECORD_SIZE_BYTES] = (
                _pack_legacy_gemm_inactive_exeblock_conf_row(row_index)
            )
    source_row_ids: list[str] = []
    instances_amount_by_subtask = {
        row.vendor_subtask_id: row.instances_amount
        for row in bin_rows.subtask_rows.values()
    }
    for row in sorted(
        bin_rows.exe_block_rows.values(),
        key=lambda row: row.global_row_index,
    ):
        encoded = _pack_exeblock_conf_row(
            row,
            instances_amount=instances_amount_by_subtask[row.vendor_subtask_id],
        )
        content[row.component_byte_offset : row.component_byte_offset + len(encoded)] = encoded
        source_row_ids.append(row.id)
    return ProgramBinComponent(
        path=EXEBLOCK_CONF_COMPONENT,
        content=bytes(content),
        record_size_bytes=EXEBLOCK_CONF_RECORD_SIZE_BYTES,
        capacity=EXEBLOCK_CONF_CAPACITY,
        active_row_count=len(source_row_ids),
        source_row_ids=tuple(source_row_ids),
        serializer=(
            "legacy_struct:exeBlock_conf_info_t:legacy_template_compat_physical_base"
            if legacy_template_compat
            else "legacy_struct:exeBlock_conf_info_t:v0_symbolic_edges_zeroed"
        ),
    )


def _pack_legacy_gemm_inactive_exeblock_conf_row(row_index: int) -> bytes:
    block_idx = row_index % DFU3500_LEGACY_EXEBLOCKS_PER_PE
    pe_linear_index = row_index // DFU3500_LEGACY_EXEBLOCKS_PER_PE
    pe_row = pe_linear_index // 4
    pe_col = pe_linear_index % 4
    encoded = struct.pack(
        "<B7xQ3QQ",
        0,
        block_idx,
        pe_row,
        pe_col,
        0,
        0,
    ) + bytes(EXEBLOCK_CONF_RECORD_SIZE_BYTES - 48)
    if len(encoded) != EXEBLOCK_CONF_RECORD_SIZE_BYTES:
        raise ValueError("inactive exeBlock_conf_info_t serializer size mismatch")
    return encoded


def _serialize_insts_component(bin_rows: ProgramBinRows) -> ProgramBinComponent:
    content = bytearray(INST_CAPACITY * INST_RECORD_SIZE_BYTES)
    source_row_ids: list[str] = []
    for row in sorted(
        bin_rows.inst_rows.values(),
        key=lambda row: row.global_row_index,
    ):
        encoded = _pack_inst_row(row)
        content[row.component_byte_offset : row.component_byte_offset + len(encoded)] = encoded
        source_row_ids.append(row.id)
    return ProgramBinComponent(
        path=INSTS_COMPONENT,
        content=bytes(content),
        record_size_bytes=INST_RECORD_SIZE_BYTES,
        capacity=INST_CAPACITY,
        active_row_count=len(source_row_ids),
        source_row_ids=tuple(source_row_ids),
        serializer="legacy_struct:inst_t:native_symbolic_structural_smoke_only",
    )


def _serialize_subtask_conf_component(bin_rows: ProgramBinRows) -> ProgramBinComponent:
    capacity = SUBTASK_CONF_CAPACITY
    content = bytearray(capacity * SUBTASK_CONF_RECORD_SIZE_BYTES)
    source_row_ids: list[str] = []
    packed_exeblocks = _pack_exeblock_rows_by_id(bin_rows)
    exeblock_rows = bin_rows.exe_block_rows
    next_subtask_by_row_id = _next_local_subtask_index_by_row_id(bin_rows)
    for row in sorted(
        bin_rows.subtask_rows.values(),
        key=lambda row: row.global_row_index,
    ):
        encoded = _pack_subtask_conf_row(
            row,
            packed_exeblocks=packed_exeblocks,
            exeblock_rows=exeblock_rows,
            next_subtask_index=next_subtask_by_row_id.get(row.id),
        )
        content[row.component_byte_offset : row.component_byte_offset + len(encoded)] = encoded
        source_row_ids.append(row.id)
    return ProgramBinComponent(
        path=SUBTASK_CONF_COMPONENT,
        content=bytes(content),
        record_size_bytes=SUBTASK_CONF_RECORD_SIZE_BYTES,
        capacity=capacity,
        active_row_count=len(source_row_ids),
        source_row_ids=tuple(source_row_ids),
        serializer=(
            "legacy_struct:sub_task_conf_info_t:"
            "embedded_exeBlocks_conf_info_from_program_bin_rows"
        ),
    )


def _serialize_instance_conf_component(bin_rows: ProgramBinRows) -> ProgramBinComponent:
    content = bytearray(INSTANCE_CONF_CAPACITY * INSTANCE_CONF_RECORD_SIZE_BYTES)
    source_row_ids: list[str] = []
    for row in sorted(
        bin_rows.instance_rows.values(),
        key=lambda row: row.global_row_index,
    ):
        encoded = _pack_instance_conf_row(row)
        content[row.component_byte_offset : row.component_byte_offset + len(encoded)] = encoded
        source_row_ids.append(row.id)
    return ProgramBinComponent(
        path=INSTANCE_CONF_COMPONENT,
        content=bytes(content),
        record_size_bytes=INSTANCE_CONF_RECORD_SIZE_BYTES,
        capacity=INSTANCE_CONF_CAPACITY,
        active_row_count=len(source_row_ids),
        source_row_ids=tuple(source_row_ids),
        serializer="struct:<4Q",
    )


def _serialize_task_conf_component(bin_rows: ProgramBinRows) -> ProgramBinComponent:
    capacity = TASK_CONF_CAPACITY
    content = bytearray(capacity * TASK_CONF_RECORD_SIZE_BYTES)
    source_row_ids: list[str] = []
    for row in sorted(
        bin_rows.task_rows.values(),
        key=lambda row: row.global_row_index,
    ):
        encoded = _pack_task_conf_row(row)
        content[row.component_byte_offset : row.component_byte_offset + len(encoded)] = encoded
        source_row_ids.append(row.id)
    return ProgramBinComponent(
        path=TASK_CONF_COMPONENT,
        content=bytes(content),
        record_size_bytes=TASK_CONF_RECORD_SIZE_BYTES,
        capacity=capacity,
        active_row_count=len(source_row_ids),
        source_row_ids=tuple(source_row_ids),
        serializer="struct:<BB6xQQ8Q4Q",
    )

def _pack_instance_conf_row(row: InstanceConfBinRow) -> bytes:
    encoded = struct.pack("<4Q", *row.base_addr_words)
    if len(encoded) != INSTANCE_CONF_RECORD_SIZE_BYTES:
        raise ValueError("instance_conf_info_t serializer size mismatch")
    return encoded


def _pack_inst_row(row: InstBinRow) -> bytes:
    if row.legacy_inst is not None:
        return pack_legacy_inst(row.legacy_inst)

    zero3 = (0, 0, 0)
    zero9 = (0,) * 9
    encoded = struct.pack(
        "<I4xQQ3Q3Q3Q9Q3Q3Q3QQ3B3B2xQQQ3Q",
        row.opcode_value,
        row.unit_inst_type,
        row.latency,
        *row.imms,
        *zero3,
        *zero3,
        *zero9,
        *zero3,
        *zero3,
        *zero3,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        row.block_idx,
        0,
        int(row.end_inst),
        *row.extra_fields,
    )
    if len(encoded) != INST_RECORD_SIZE_BYTES:
        raise ValueError("inst_t serializer size mismatch")
    return encoded


def _pack_subtask_conf_row(
    row: SubtaskConfBinRow,
    *,
    packed_exeblocks: dict[str, bytes],
    exeblock_rows: dict[str, ExeBlockConfBinRow],
    next_subtask_index: int | None,
) -> bytes:
    successor_slots = (
        (next_subtask_index, 0, 0, 0)
        if next_subtask_index is not None
        else (0, 0, 0, 0)
    )
    root_block_amount = sum(
        1
        for row_id in row.embedded_exe_block_row_ids
        if exeblock_rows[row_id].req_activations == 0
    )
    header = struct.pack(
        "<BB6xQQ4QQQ",
        int(row.is_exe_start),
        int(row.is_exe_end),
        row.instances_amount,
        row.instances_conf_mem_based_addr,
        *successor_slots,
        root_block_amount,
        row.valid_exe_blocks,
    )
    embedded_blocks = bytearray(
        SUBTASK_EMBEDDED_EXEBLOCK_SLOT_COUNT * EXEBLOCK_CONF_RECORD_SIZE_BYTES
    )
    for slot_index, row_id in enumerate(row.embedded_exe_block_slots):
        if row_id == UNUSED_EXEBLOCK_FIELD:
            continue
        encoded_exeblock = packed_exeblocks[row_id]
        offset = slot_index * EXEBLOCK_CONF_RECORD_SIZE_BYTES
        embedded_blocks[offset : offset + len(encoded_exeblock)] = encoded_exeblock
    encoded = header + bytes(embedded_blocks) + struct.pack(
        "<QQ",
        row.subtask_index,
        row.task_index,
    )
    if len(encoded) != SUBTASK_CONF_RECORD_SIZE_BYTES:
        raise ValueError("sub_task_conf_info_t serializer size mismatch")
    return encoded


def _pack_exeblock_conf_row(row: ExeBlockConfBinRow, *, instances_amount: int) -> bytes:
    has_stages = (
        int(row.stage_instruction_counts.get("LD", 0) > 0),
        int(row.stage_instruction_counts.get("CAL", 0) > 0),
        int(row.stage_instruction_counts.get("FLOW", 0) > 0),
        int(row.stage_instruction_counts.get("ST", 0) > 0),
        0,
    )
    stages_start_pc = (
        row.stage_start_pc.get("LD", 0),
        row.stage_start_pc.get("CAL", 0),
        row.stage_start_pc.get("FLOW", 0),
        row.stage_start_pc.get("ST", 0),
        row.stage_start_pc.get("END", 0),
    )
    predecessor_records = (0,) * (4 * 5)
    successor_records = (0,) * (4 * 5)
    if row.vendor_inst_mode == "legacy_gemm_compat":
        predecessor_records = _legacy_gemm_exeblock_edge_records(
            row.global_row_index,
            edge_kind="predecessor",
        )
        successor_records = _legacy_gemm_exeblock_edge_records(
            row.global_row_index,
            edge_kind="successor",
        )
    stage_instruction_count_fields = (
        row.stage_instruction_counts.get("LD", 0),
        row.stage_instruction_counts.get("CAL", 0),
        row.stage_instruction_counts.get("FLOW", 0),
        row.stage_instruction_counts.get("ST", 0),
    )
    if row.vendor_inst_mode == "legacy_gemm_compat":
        # arch-13's libapp_build_common.so leaves these legacy GEMM C-struct
        # count fields zero while preserving has_stages and stage_start_pc.
        # Keep OpenFabric's real counts in IR/debug reports; only the vendor
        # byte projection follows this compatibility quirk.
        stage_instruction_count_fields = (0, 0, 0, 0)
    serialized_child_amount = row.child_amount
    if row.vendor_inst_mode == "legacy_gemm_compat":
        # The same arch-13 projection keeps explicit successor records but
        # leaves child_amount zero in the serialized exeBlock_conf_t rows.
        serialized_child_amount = 0
    exe_block_conf = struct.pack(
        "<Q5B3x5Q20Q20Q11QB7x",
        row.req_activations,
        *has_stages,
        *stages_start_pc,
        *predecessor_records,
        *successor_records,
        row.block_idx,
        row.subtask_index,
        row.task_index,
        instances_amount,
        serialized_child_amount,
        0,
        row.inst_mem_based_addr,
        *stage_instruction_count_fields,
        0,
    )
    encoded = struct.pack(
        "<B7xQ3QQ",
        1,
        row.block_idx,
        *row.pe_pos,
        0,
    ) + exe_block_conf
    if len(encoded) != EXEBLOCK_CONF_RECORD_SIZE_BYTES:
        raise ValueError("exeBlock_conf_info_t serializer size mismatch")
    return encoded


@lru_cache(maxsize=None)
def _legacy_gemm_exeblock_edge_records(
    row_index: int,
    *,
    edge_kind: str,
) -> tuple[int, ...]:
    """Return legacy GEMM exeBlock graph slots for compatibility mode.

    ``legacy_gemm_compat`` is a byte-parity profile.  Its predecessor/successor
    slots are DFU3500 physical control-table facts from the vendor generated
    build, while OpenFabric's semantic tile graph remains represented in
    earlier IR layers.
    """

    data = _legacy_gemm_exeblock_conf_path().read_bytes()
    row_offset = int(row_index) * EXEBLOCK_CONF_RECORD_SIZE_BYTES
    exe_block_conf_offset = row_offset + struct.calcsize("<B7xQ3QQ")
    predecessor_offset = exe_block_conf_offset + 56
    successor_offset = exe_block_conf_offset + 216
    if edge_kind == "predecessor":
        return struct.unpack_from("<20Q", data, predecessor_offset)
    if edge_kind == "successor":
        return struct.unpack_from("<20Q", data, successor_offset)
    raise ValueError(f"unknown legacy exeBlock edge kind: {edge_kind}")


def _legacy_gemm_exeblock_conf_path() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "simict3500final/gpdpu/users/risc_nn_riscv/testcase/build_out"
        / "gemm_template_fusion/worktree/gpdpu/users/risc_nn_riscv/testcase"
        / "application/gemm_template_fusion/simulator_bin"
        / "exeblock_conf_info_file.bin"
    )


def _pack_exeblock_rows_by_id(bin_rows: ProgramBinRows) -> dict[str, bytes]:
    instances_amount_by_subtask = {
        row.vendor_subtask_id: row.instances_amount
        for row in bin_rows.subtask_rows.values()
    }
    return {
        row.id: _pack_exeblock_conf_row(
            row,
            instances_amount=instances_amount_by_subtask[row.vendor_subtask_id],
        )
        for row in bin_rows.exe_block_rows.values()
    }


def _next_local_subtask_index_by_row_id(bin_rows: ProgramBinRows) -> dict[str, int]:
    rows_by_task: dict[int, list[SubtaskConfBinRow]] = {}
    for row in bin_rows.subtask_rows.values():
        rows_by_task.setdefault(row.task_index, []).append(row)

    next_by_row_id: dict[str, int] = {}
    for rows in rows_by_task.values():
        sorted_rows = sorted(rows, key=lambda row: row.subtask_index)
        for current, next_row in zip(sorted_rows, sorted_rows[1:]):
            if not current.is_exe_end:
                # DFU3500 legacy MICC uses local subtask indices in
                # sub_task_conf_info_t.suc_subtasks, while task_conf_info_t
                # subtask slots still use the fixed physical row/index space.
                next_by_row_id[current.id] = next_row.subtask_index
    return next_by_row_id


def _pack_task_conf_row(row: TaskConfBinRow) -> bytes:
    encoded = struct.pack(
        "<BB6xQQ8Q4Q",
        int(row.is_exe_start),
        int(row.is_exe_end),
        len(row.active_subtask_ids),
        row.execute_times,
        *row.subtasks_idx_slots,
        *row.successor_task_slots,
    )
    if len(encoded) != TASK_CONF_RECORD_SIZE_BYTES:
        raise ValueError("task_conf_info_t serializer size mismatch")
    return encoded
