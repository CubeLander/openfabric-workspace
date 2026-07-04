"""Binary bundle decoder and comparison reports for DFU simulator artifacts.

This module is a microscope, not a compiler pass.  It decodes already-emitted
vendor component files and produces stable summary/diff reports so refactored
OpenFabric bundles can be compared with legacy vendor build outputs.
"""

from __future__ import annotations

import hashlib
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from gpdpu_compiler.core.program_bin import (
    EXEBLOCK_CONF_CAPACITY,
    EXEBLOCK_CONF_RECORD_SIZE_BYTES,
    INST_CAPACITY,
    INST_RECORD_SIZE_BYTES,
    INSTANCE_CONF_CAPACITY,
    INSTANCE_CONF_RECORD_SIZE_BYTES,
    MAX_INST_AMOUNT_PER_PE,
    PE_AMOUNT,
    SUBTASK_CONF_CAPACITY,
    SUBTASK_CONF_RECORD_SIZE_BYTES,
    SUBTASK_EMBEDDED_EXEBLOCK_SLOT_COUNT,
    TASK_CONF_CAPACITY,
    TASK_CONF_RECORD_SIZE_BYTES,
)


INST_STRUCT = struct.Struct("<I4xQQ3Q3Q3Q9Q3Q3Q3QQ3B3B2xQQQ3Q")
INSTANCE_CONF_STRUCT = struct.Struct("<4Q")
TASK_CONF_STRUCT = struct.Struct("<BB6xQQ8Q4Q")
EXEBLOCK_CONF_STRUCT = struct.Struct("<B7xQ3QQQ5B3x5Q20Q20Q11QB7x")
SUBTASK_HEADER_STRUCT = struct.Struct("<BB6xQQ4QQQ")
SUBTASK_TRAILER_STRUCT = struct.Struct("<QQ")

SIMULATOR_COMPONENTS = {
    "insts": "insts_file.bin",
    "exeblocks": "exeblock_conf_info_file.bin",
    "instances": "instance_conf_info_file.bin",
    "tasks": "tasks_conf_info_file.bin",
    "subtasks": "subtasks_conf_info_file.bin",
}


@dataclass(frozen=True)
class DecodedBundle:
    """Decoded summary of one simulator binary bundle."""

    root: str
    components: dict[str, dict[str, Any]]
    inst_summary: dict[str, Any]
    exeblock_summary: dict[str, Any]
    instance_summary: dict[str, Any]
    task_summary: dict[str, Any]
    subtask_summary: dict[str, Any]

    def to_report(self) -> dict[str, Any]:
        return {
            "root": self.root,
            "components": self.components,
            "inst_summary": self.inst_summary,
            "exeblock_summary": self.exeblock_summary,
            "instance_summary": self.instance_summary,
            "task_summary": self.task_summary,
            "subtask_summary": self.subtask_summary,
        }


def decode_simulator_bundle(root: str | Path) -> DecodedBundle:
    """Decode component summaries from a simulator bundle directory."""

    root_path = Path(root)
    sim_dir = root_path / "simulator_bin"
    if not sim_dir.is_dir():
        sim_dir = root_path

    component_paths = {
        key: sim_dir / filename
        for key, filename in SIMULATOR_COMPONENTS.items()
    }
    components = {
        key: _component_summary(path)
        for key, path in component_paths.items()
    }
    return DecodedBundle(
        root=str(root_path),
        components=components,
        inst_summary=_decode_inst_summary(component_paths["insts"]),
        exeblock_summary=_decode_exeblock_summary(component_paths["exeblocks"]),
        instance_summary=_decode_instance_summary(component_paths["instances"]),
        task_summary=_decode_task_summary(component_paths["tasks"]),
        subtask_summary=_decode_subtask_summary(component_paths["subtasks"]),
    )


def compare_simulator_bundles(
    *,
    legacy_root: str | Path,
    candidate_root: str | Path,
    top_n: int = 16,
) -> dict[str, Any]:
    """Compare two simulator bundle directories at stable ABI-summary level."""

    legacy = decode_simulator_bundle(legacy_root)
    candidate = decode_simulator_bundle(candidate_root)
    return {
        "schema_version": 1,
        "report": "dfu_simulator_bundle_diff",
        "comparison_policy": (
            "summary_level_not_byte_equal_required;"
            "scheduler_differences_are_expected_between_legacy_and_refactor"
        ),
        "legacy": legacy.to_report(),
        "candidate": candidate.to_report(),
        "diff": {
            "component_sizes": _diff_maps(
                _component_sizes(legacy.components),
                _component_sizes(candidate.components),
            ),
            "component_hash_equal": {
                key: legacy.components[key]["sha256"] == candidate.components[key]["sha256"]
                for key in sorted(SIMULATOR_COMPONENTS)
            },
            "inst": _diff_inst_summaries(
                legacy.inst_summary,
                candidate.inst_summary,
                top_n=top_n,
            ),
            "exeblocks": _diff_exeblock_summaries(
                legacy.exeblock_summary,
                candidate.exeblock_summary,
            ),
            "instances": _diff_instance_summaries(
                legacy.instance_summary,
                candidate.instance_summary,
                top_n=top_n,
            ),
            "tasks": _diff_maps(
                legacy.task_summary["active_task_rows"],
                candidate.task_summary["active_task_rows"],
            ),
            "subtasks": _diff_maps(
                legacy.subtask_summary["active_subtask_rows"],
                candidate.subtask_summary["active_subtask_rows"],
            ),
            "row_diff": compare_simulator_bundle_rows(
                legacy_root=legacy_root,
                candidate_root=candidate_root,
                top_n=top_n,
            )["components"],
        },
    }


def compare_simulator_bundle_rows(
    *,
    legacy_root: str | Path,
    candidate_root: str | Path,
    top_n: int = 16,
) -> dict[str, Any]:
    """Compare simulator bundles row-by-row and field-by-field.

    This is intentionally a diagnostic microscope.  It does not apply semantic
    normalization or scheduler matching; row ``N`` is compared with row ``N``.
    Once summary counts match, this report points at the remaining byte-level
    ABI mismatches that still need to be explained or eliminated.
    """

    legacy_root_path = Path(legacy_root)
    candidate_root_path = Path(candidate_root)
    legacy_sim_dir = _simulator_component_dir(legacy_root_path)
    candidate_sim_dir = _simulator_component_dir(candidate_root_path)
    components: dict[str, Any] = {}
    for component, filename in SIMULATOR_COMPONENTS.items():
        components[component] = _compare_component_rows(
            component=component,
            legacy_path=legacy_sim_dir / filename,
            candidate_path=candidate_sim_dir / filename,
            top_n=top_n,
        )
    return {
        "schema_version": 1,
        "report": "dfu_simulator_bundle_row_diff",
        "comparison_policy": (
            "row_index_field_diff;"
            "no_scheduler_semantic_matching;"
            "use_after_summary_counts_are_aligned"
        ),
        "legacy_root": str(legacy_root_path),
        "candidate_root": str(candidate_root_path),
        "components": components,
    }


def _decode_inst_summary(path: Path) -> dict[str, Any]:
    data = _read_exact_component(path, INST_CAPACITY * INST_RECORD_SIZE_BYTES)
    opcode_counts: dict[str, int] = {}
    pe_instruction_counts: dict[str, int] = {}
    end_inst_count = 0
    active_rows: list[dict[str, Any]] = []
    for index in range(INST_CAPACITY):
        offset = index * INST_RECORD_SIZE_BYTES
        fields = INST_STRUCT.unpack_from(data, offset)
        opcode = int(fields[0])
        if opcode == 0:
            continue
        pe_index = index // MAX_INST_AMOUNT_PER_PE
        local_pc = index % MAX_INST_AMOUNT_PER_PE
        pe = _pe_name(pe_index)
        opcode_name = _opcode_name(opcode)
        opcode_counts[opcode_name] = opcode_counts.get(opcode_name, 0) + 1
        pe_instruction_counts[pe] = pe_instruction_counts.get(pe, 0) + 1
        end_inst = int(fields[39])
        end_inst_count += int(bool(end_inst))
        if len(active_rows) < 32:
            active_rows.append(
                {
                    "global_row_index": index,
                    "pe": pe,
                    "local_pc": local_pc,
                    "opcode": opcode_name,
                    "unit_inst_type": int(fields[1]),
                    "latency": int(fields[2]),
                    "imms": list(fields[3:6]),
                    "src_operands_idx": list(fields[6:9]),
                    "dst_operands_idx": list(fields[9:12]),
                    "dst_pe0": list(fields[12:15]),
                    "iter_exe_cond": int(fields[30]),
                    "block_idx": int(fields[37]),
                    "end_inst": end_inst,
                    "extra_fields": list(fields[40:43]),
                }
            )
    return {
        "active_inst_count": sum(opcode_counts.values()),
        "opcode_counts": dict(sorted(opcode_counts.items())),
        "pe_instruction_counts": dict(sorted(pe_instruction_counts.items())),
        "max_pe_instruction_count": max(pe_instruction_counts.values(), default=0),
        "end_inst_count": end_inst_count,
        "sample_active_rows": active_rows,
    }


def _decode_exeblock_summary(path: Path) -> dict[str, Any]:
    data = _read_exact_component(path, EXEBLOCK_CONF_CAPACITY * EXEBLOCK_CONF_RECORD_SIZE_BYTES)
    active_rows: dict[str, dict[str, Any]] = {}
    stage_counts = {"LD": 0, "CAL": 0, "FLOW": 0, "ST": 0}
    instances_amount_counts: dict[str, int] = {}
    req_activation_counts: dict[str, int] = {}
    child_amount_counts: dict[str, int] = {}
    for index in range(EXEBLOCK_CONF_CAPACITY):
        offset = index * EXEBLOCK_CONF_RECORD_SIZE_BYTES
        fields = EXEBLOCK_CONF_STRUCT.unpack_from(data, offset)
        valid = int(fields[0])
        if valid == 0:
            continue
        pe_pos = tuple(int(value) for value in fields[2:5])
        stages_start_pc = {
            "LD": int(fields[12]),
            "CAL": int(fields[13]),
            "FLOW": int(fields[14]),
            "ST": int(fields[15]),
            "END": int(fields[16]),
        }
        row = {
            "global_row_index": index,
            "block_idx": int(fields[1]),
            "pe_pos": list(pe_pos),
            "req_activations": int(fields[6]),
            "has_stages": {
                "LD": bool(fields[7]),
                "CAL": bool(fields[8]),
                "FLOW": bool(fields[9]),
                "ST": bool(fields[10]),
            },
            "stages_start_pc": stages_start_pc,
            "task_idx": int(fields[59]),
            "subtask_idx": int(fields[58]),
            "instances_amount": int(fields[60]),
            "child_amount": int(fields[61]),
            "inst_mem_based_addr": int(fields[63]),
            "stage_instruction_counts": {
                "LD": int(fields[64]),
                "CAL": int(fields[65]),
                "FLOW": int(fields[66]),
                "ST": int(fields[67]),
            },
            "is_leaf": bool(fields[68]),
        }
        active_rows[f"row{index:03d}"] = row
        for stage, count in row["stage_instruction_counts"].items():
            stage_counts[stage] += int(count)
        instances_amount_counts[str(row["instances_amount"])] = (
            instances_amount_counts.get(str(row["instances_amount"]), 0) + 1
        )
        req_activation_counts[str(row["req_activations"])] = (
            req_activation_counts.get(str(row["req_activations"]), 0) + 1
        )
        child_amount_counts[str(row["child_amount"])] = (
            child_amount_counts.get(str(row["child_amount"]), 0) + 1
        )
    return {
        "active_exeblock_count": len(active_rows),
        "stage_instruction_counts": dict(sorted(stage_counts.items())),
        "instances_amount_counts": dict(sorted(instances_amount_counts.items())),
        "req_activation_counts": dict(sorted(req_activation_counts.items())),
        "child_amount_counts": dict(sorted(child_amount_counts.items())),
        "sample_active_rows": dict(list(active_rows.items())[:32]),
    }


def _decode_instance_summary(path: Path) -> dict[str, Any]:
    data = _read_exact_component(path, INSTANCE_CONF_CAPACITY * INSTANCE_CONF_RECORD_SIZE_BYTES)
    active_rows: dict[str, list[str]] = {}
    filled_slot_counts: dict[str, int] = {}
    for index in range(INSTANCE_CONF_CAPACITY):
        values = INSTANCE_CONF_STRUCT.unpack_from(data, index * INSTANCE_CONF_RECORD_SIZE_BYTES)
        if all(value == 0 for value in values):
            continue
        active_rows[f"row{index:05d}"] = [f"0x{value:08x}" for value in values]
        for slot, value in enumerate(values):
            if value not in {0, 0xFFFFFFFF}:
                key = str(slot)
                filled_slot_counts[key] = filled_slot_counts.get(key, 0) + 1
    return {
        "active_instance_row_count": len(active_rows),
        "filled_slot_counts_excluding_zero_and_sentinel": dict(
            sorted(filled_slot_counts.items())
        ),
        "sample_active_rows": dict(list(active_rows.items())[:32]),
    }


def _decode_task_summary(path: Path) -> dict[str, Any]:
    data = _read_exact_component(path, TASK_CONF_CAPACITY * TASK_CONF_RECORD_SIZE_BYTES)
    active_rows: dict[str, dict[str, Any]] = {}
    for index in range(TASK_CONF_CAPACITY):
        fields = TASK_CONF_STRUCT.unpack_from(data, index * TASK_CONF_RECORD_SIZE_BYTES)
        if int(fields[2]) == 0 and int(fields[3]) == 0:
            continue
        active_rows[f"row{index}"] = {
            "is_exe_start": bool(fields[0]),
            "is_exe_end": bool(fields[1]),
            "subtasks_amount": int(fields[2]),
            "execute_times": int(fields[3]),
            "subtasks_idx": list(fields[4:12]),
            "suc_tasks": list(fields[12:16]),
        }
    return {
        "active_task_count": len(active_rows),
        "active_task_rows": active_rows,
    }


def _decode_subtask_summary(path: Path) -> dict[str, Any]:
    data = _read_exact_component(path, SUBTASK_CONF_CAPACITY * SUBTASK_CONF_RECORD_SIZE_BYTES)
    active_rows: dict[str, dict[str, Any]] = {}
    for index in range(SUBTASK_CONF_CAPACITY):
        offset = index * SUBTASK_CONF_RECORD_SIZE_BYTES
        fields = SUBTASK_HEADER_STRUCT.unpack_from(data, offset)
        if int(fields[6]) == 0 and int(fields[7]) == 0:
            continue
        trailer_offset = offset + SUBTASK_CONF_RECORD_SIZE_BYTES - SUBTASK_TRAILER_STRUCT.size
        trailer = SUBTASK_TRAILER_STRUCT.unpack_from(data, trailer_offset)
        active_rows[f"row{index:02d}"] = {
            "is_exe_start": bool(fields[0]),
            "is_exe_end": bool(fields[1]),
            "instances_amount": int(fields[2]),
            "instances_conf_mem_based_addr": int(fields[3]),
            "suc_subtasks": list(fields[4:8]),
            "root_block_amount": int(fields[8]),
            "block_amount": int(fields[9]),
            "subtask_idx": int(trailer[0]),
            "task_idx": int(trailer[1]),
        }
    return {
        "active_subtask_count": len(active_rows),
        "active_subtask_rows": active_rows,
    }


def _component_summary(path: Path) -> dict[str, Any]:
    data = path.read_bytes()
    return {
        "path": str(path),
        "size_bytes": len(data),
        "sha256": hashlib.sha256(data).hexdigest(),
    }


def _component_sizes(components: dict[str, dict[str, Any]]) -> dict[str, int]:
    return {
        key: int(value["size_bytes"])
        for key, value in components.items()
    }


def _diff_inst_summaries(
    legacy: dict[str, Any],
    candidate: dict[str, Any],
    *,
    top_n: int,
) -> dict[str, Any]:
    return {
        "active_inst_count": {
            "legacy": legacy["active_inst_count"],
            "candidate": candidate["active_inst_count"],
            "delta": candidate["active_inst_count"] - legacy["active_inst_count"],
        },
        "max_pe_instruction_count": {
            "legacy": legacy["max_pe_instruction_count"],
            "candidate": candidate["max_pe_instruction_count"],
            "delta": candidate["max_pe_instruction_count"] - legacy["max_pe_instruction_count"],
        },
        "opcode_counts": _diff_maps(
            legacy["opcode_counts"],
            candidate["opcode_counts"],
        ),
        "pe_instruction_counts": _diff_maps(
            legacy["pe_instruction_counts"],
            candidate["pe_instruction_counts"],
        ),
        "legacy_sample": legacy["sample_active_rows"][:top_n],
        "candidate_sample": candidate["sample_active_rows"][:top_n],
    }


def _diff_exeblock_summaries(
    legacy: dict[str, Any],
    candidate: dict[str, Any],
) -> dict[str, Any]:
    return {
        "active_exeblock_count": {
            "legacy": legacy["active_exeblock_count"],
            "candidate": candidate["active_exeblock_count"],
            "delta": candidate["active_exeblock_count"] - legacy["active_exeblock_count"],
        },
        "stage_instruction_counts": _diff_maps(
            legacy["stage_instruction_counts"],
            candidate["stage_instruction_counts"],
        ),
        "instances_amount_counts": _diff_maps(
            legacy["instances_amount_counts"],
            candidate["instances_amount_counts"],
        ),
        "req_activation_counts": _diff_maps(
            legacy["req_activation_counts"],
            candidate["req_activation_counts"],
        ),
        "child_amount_counts": _diff_maps(
            legacy["child_amount_counts"],
            candidate["child_amount_counts"],
        ),
    }


def _diff_instance_summaries(
    legacy: dict[str, Any],
    candidate: dict[str, Any],
    *,
    top_n: int,
) -> dict[str, Any]:
    return {
        "active_instance_row_count": {
            "legacy": legacy["active_instance_row_count"],
            "candidate": candidate["active_instance_row_count"],
            "delta": (
                candidate["active_instance_row_count"]
                - legacy["active_instance_row_count"]
            ),
        },
        "filled_slot_counts_excluding_zero_and_sentinel": _diff_maps(
            legacy["filled_slot_counts_excluding_zero_and_sentinel"],
            candidate["filled_slot_counts_excluding_zero_and_sentinel"],
        ),
        "legacy_sample": dict(list(legacy["sample_active_rows"].items())[:top_n]),
        "candidate_sample": dict(list(candidate["sample_active_rows"].items())[:top_n]),
    }


def _compare_component_rows(
    *,
    component: str,
    legacy_path: Path,
    candidate_path: Path,
    top_n: int,
) -> dict[str, Any]:
    decoder, active_predicate, record_size, capacity = _row_decoder(component)
    legacy_data = _read_exact_component(legacy_path, record_size * capacity)
    candidate_data = _read_exact_component(candidate_path, record_size * capacity)
    legacy_rows = _decode_component_rows(
        legacy_data,
        decoder,
        active_predicate,
        record_size,
        capacity,
    )
    candidate_rows = _decode_component_rows(
        candidate_data,
        decoder,
        active_predicate,
        record_size,
        capacity,
    )
    shared_row_ids = sorted(set(legacy_rows) & set(candidate_rows), key=_row_sort_key)
    mismatched_rows: list[dict[str, Any]] = []
    matching_row_count = 0
    field_diff_counts: dict[str, int] = {}
    for row_id in shared_row_ids:
        legacy_row = legacy_rows[row_id]
        candidate_row = candidate_rows[row_id]
        field_diff = _diff_row_fields(legacy_row, candidate_row)
        if not field_diff:
            matching_row_count += 1
            continue
        for field_name in field_diff:
            field_diff_counts[field_name] = field_diff_counts.get(field_name, 0) + 1
        if len(mismatched_rows) < top_n:
            row_index = int(row_id[3:])
            mismatched_rows.append(
                {
                    "row_id": row_id,
                    "row_index": row_index,
                    "first_diff_byte_in_record": _first_diff(
                        legacy_data[
                            row_index * record_size : (row_index + 1) * record_size
                        ],
                        candidate_data[
                            row_index * record_size : (row_index + 1) * record_size
                        ],
                    ),
                    "differing_fields": field_diff,
                    "legacy_row": legacy_row,
                    "candidate_row": candidate_row,
                }
            )
    only_legacy = sorted(set(legacy_rows) - set(candidate_rows), key=_row_sort_key)
    only_candidate = sorted(set(candidate_rows) - set(legacy_rows), key=_row_sort_key)
    return {
        "record_size_bytes": record_size,
        "capacity": capacity,
        "active_row_count": {
            "legacy": len(legacy_rows),
            "candidate": len(candidate_rows),
            "delta": len(candidate_rows) - len(legacy_rows),
        },
        "shared_active_row_count": len(shared_row_ids),
        "matching_shared_row_count": matching_row_count,
        "mismatched_shared_row_count": len(shared_row_ids) - matching_row_count,
        "only_legacy_row_count": len(only_legacy),
        "only_candidate_row_count": len(only_candidate),
        "only_legacy_rows_sample": only_legacy[:top_n],
        "only_candidate_rows_sample": only_candidate[:top_n],
        "field_diff_counts": dict(sorted(field_diff_counts.items())),
        "sample_mismatched_rows": mismatched_rows,
    }


def _decode_component_rows(
    data: bytes,
    decoder: Any,
    active_predicate: Any,
    record_size: int,
    capacity: int,
) -> dict[str, dict[str, Any]]:
    rows: dict[str, dict[str, Any]] = {}
    for index in range(capacity):
        offset = index * record_size
        record = data[offset : offset + record_size]
        if not active_predicate(record):
            continue
        rows[f"row{index:05d}"] = decoder(record, index)
    return rows


def _diff_row_fields(
    legacy_row: dict[str, Any],
    candidate_row: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    diff: dict[str, dict[str, Any]] = {}
    for field_name in sorted(set(legacy_row) | set(candidate_row)):
        legacy_value = legacy_row.get(field_name)
        candidate_value = candidate_row.get(field_name)
        if legacy_value == candidate_value:
            continue
        item = {
            "legacy": legacy_value,
            "candidate": candidate_value,
            "equal": False,
        }
        if isinstance(legacy_value, int) and isinstance(candidate_value, int):
            item["delta"] = candidate_value - legacy_value
        diff[field_name] = item
    return diff


def _row_decoder(component: str) -> tuple[Any, Any, int, int]:
    if component == "insts":
        return _decode_inst_row, _inst_row_is_active, INST_RECORD_SIZE_BYTES, INST_CAPACITY
    if component == "exeblocks":
        return (
            _decode_exeblock_row,
            _exeblock_row_is_active,
            EXEBLOCK_CONF_RECORD_SIZE_BYTES,
            EXEBLOCK_CONF_CAPACITY,
        )
    if component == "instances":
        return (
            _decode_instance_row,
            _any_byte_row_is_active,
            INSTANCE_CONF_RECORD_SIZE_BYTES,
            INSTANCE_CONF_CAPACITY,
        )
    if component == "tasks":
        return _decode_task_row, _any_byte_row_is_active, TASK_CONF_RECORD_SIZE_BYTES, TASK_CONF_CAPACITY
    if component == "subtasks":
        return (
            _decode_subtask_row,
            _any_byte_row_is_active,
            SUBTASK_CONF_RECORD_SIZE_BYTES,
            SUBTASK_CONF_CAPACITY,
        )
    raise ValueError(f"unknown simulator component: {component}")


def _any_byte_row_is_active(record: bytes) -> bool:
    return any(record)


def _inst_row_is_active(record: bytes) -> bool:
    return struct.unpack_from("<I", record, 0)[0] != 0


def _exeblock_row_is_active(record: bytes) -> bool:
    return struct.unpack_from("<B", record, 0)[0] != 0


def _decode_inst_row(record: bytes, index: int) -> dict[str, Any]:
    fields = INST_STRUCT.unpack_from(record, 0)
    pe_index = index // MAX_INST_AMOUNT_PER_PE
    local_pc = index % MAX_INST_AMOUNT_PER_PE
    return {
        "global_row_index": index,
        "pe": _pe_name(pe_index),
        "local_pc": local_pc,
        "opcode": _opcode_name(int(fields[0])),
        "opcode_value": int(fields[0]),
        "unit_inst_type": int(fields[1]),
        "latency": int(fields[2]),
        "imms": list(fields[3:6]),
        "src_operands_idx": list(fields[6:9]),
        "dst_operands_idx": list(fields[9:12]),
        "dst_pes_pos": [
            list(fields[12:15]),
            list(fields[15:18]),
            list(fields[18:21]),
        ],
        "dst_blocks_idx": list(fields[21:24]),
        "forwarding_bits": list(fields[24:27]),
        "bypass_bits": list(fields[27:30]),
        "iter_exe_cond": int(fields[30]),
        "src_operands_fetched": list(fields[31:34]),
        "dst_operands_fetched": list(fields[34:37]),
        "block_idx": int(fields[37]),
        "flow_ack": int(fields[38]),
        "end_inst": int(fields[39]),
        "extra_fields": list(fields[40:43]),
    }


def _decode_exeblock_row(record: bytes, index: int) -> dict[str, Any]:
    fields = EXEBLOCK_CONF_STRUCT.unpack_from(record, 0)
    return {
        "global_row_index": index,
        "valid": int(fields[0]),
        "block_idx": int(fields[1]),
        "pe_pos": list(fields[2:5]),
        "req_activations": int(fields[6]),
        "has_ld": int(fields[7]),
        "has_cal": int(fields[8]),
        "has_flow": int(fields[9]),
        "has_st": int(fields[10]),
        "ld_start_pc": int(fields[12]),
        "cal_start_pc": int(fields[13]),
        "flow_start_pc": int(fields[14]),
        "st_start_pc": int(fields[15]),
        "end_pc": int(fields[16]),
        "predecessor_slots": list(fields[17:37]),
        "successor_slots": list(fields[37:57]),
        "subtask_idx": int(fields[58]),
        "task_idx": int(fields[59]),
        "instances_amount": int(fields[60]),
        "child_amount": int(fields[61]),
        "inst_mem_based_addr": int(fields[63]),
        "ld_stage_inst_amount": int(fields[64]),
        "cal_stage_inst_amount": int(fields[65]),
        "flow_stage_inst_amount": int(fields[66]),
        "st_stage_inst_amount": int(fields[67]),
        "is_leaf": int(fields[68]),
    }


def _decode_instance_row(record: bytes, index: int) -> dict[str, Any]:
    values = INSTANCE_CONF_STRUCT.unpack_from(record, 0)
    return {
        "global_row_index": index,
        "base_addr_words": list(values),
        "base_addr_words_hex": [f"0x{value:08x}" for value in values],
    }


def _decode_task_row(record: bytes, index: int) -> dict[str, Any]:
    fields = TASK_CONF_STRUCT.unpack_from(record, 0)
    return {
        "global_row_index": index,
        "is_exe_start": int(fields[0]),
        "is_exe_end": int(fields[1]),
        "subtasks_amount": int(fields[2]),
        "execute_times": int(fields[3]),
        "subtasks_idx": list(fields[4:12]),
        "suc_tasks": list(fields[12:16]),
    }


def _decode_subtask_row(record: bytes, index: int) -> dict[str, Any]:
    fields = SUBTASK_HEADER_STRUCT.unpack_from(record, 0)
    trailer_offset = SUBTASK_CONF_RECORD_SIZE_BYTES - SUBTASK_TRAILER_STRUCT.size
    trailer = SUBTASK_TRAILER_STRUCT.unpack_from(record, trailer_offset)
    embedded_exeblock_valid_count = 0
    embedded_exeblock_stage_counts = {"LD": 0, "CAL": 0, "FLOW": 0, "ST": 0}
    embedded_offset = SUBTASK_HEADER_STRUCT.size
    for slot in range(SUBTASK_EMBEDDED_EXEBLOCK_SLOT_COUNT):
        row_offset = embedded_offset + slot * EXEBLOCK_CONF_RECORD_SIZE_BYTES
        exeblock_fields = EXEBLOCK_CONF_STRUCT.unpack_from(record, row_offset)
        if int(exeblock_fields[0]) == 0:
            continue
        embedded_exeblock_valid_count += 1
        embedded_exeblock_stage_counts["LD"] += int(exeblock_fields[64])
        embedded_exeblock_stage_counts["CAL"] += int(exeblock_fields[65])
        embedded_exeblock_stage_counts["FLOW"] += int(exeblock_fields[66])
        embedded_exeblock_stage_counts["ST"] += int(exeblock_fields[67])
    return {
        "global_row_index": index,
        "is_exe_start": int(fields[0]),
        "is_exe_end": int(fields[1]),
        "instances_amount": int(fields[2]),
        "instances_conf_mem_based_addr": int(fields[3]),
        "suc_subtasks": list(fields[4:8]),
        "root_block_amount": int(fields[8]),
        "block_amount": int(fields[9]),
        "embedded_exeblock_valid_count": embedded_exeblock_valid_count,
        "embedded_exeblock_stage_counts": embedded_exeblock_stage_counts,
        "subtask_idx": int(trailer[0]),
        "task_idx": int(trailer[1]),
    }


def _simulator_component_dir(root: Path) -> Path:
    sim_dir = root / "simulator_bin"
    if sim_dir.is_dir():
        return sim_dir
    return root


def _row_sort_key(row_id: str) -> int:
    return int(row_id[3:])


def _diff_maps(left: dict[str, Any], right: dict[str, Any]) -> dict[str, dict[str, Any]]:
    out: dict[str, dict[str, Any]] = {}
    for key in sorted(set(left) | set(right), key=str):
        left_value = left.get(key)
        right_value = right.get(key)
        item = {
            "legacy": left_value,
            "candidate": right_value,
            "equal": left_value == right_value,
        }
        if isinstance(left_value, int) and isinstance(right_value, int):
            item["delta"] = right_value - left_value
        out[str(key)] = item
    return out


def _read_exact_component(path: Path, expected_size: int) -> bytes:
    data = path.read_bytes()
    if len(data) != expected_size:
        raise ValueError(
            f"unexpected component size for {path}: {len(data)} != {expected_size}"
        )
    return data


def _first_diff(left: bytes, right: bytes) -> int | None:
    for index, (left_byte, right_byte) in enumerate(zip(left, right)):
        if left_byte != right_byte:
            return index
    if len(left) != len(right):
        return min(len(left), len(right))
    return None


def _pe_name(pe_index: int) -> str:
    row = pe_index // 4
    col = pe_index % 4
    return f"PE{row}{col}"


def _opcode_name(opcode: int) -> str:
    return {
        0x22: "IMM",
        0x40: "LDN",
        0x52: "HMUL",
        0x80: "STD",
        0xC0: "COPY",
        0xC1: "GINST",
        0xCE: "RXINT",
        0xCF: "TRCTT",
        0xE1: "HMMAL",
    }.get(opcode, f"OP_0x{opcode:02x}")
