"""DFU3500-specific diagnostic views built on top of the generic decoder."""

from __future__ import annotations

from typing import Any

from .binary_decoder import decode_row
from .binary_layout import DfuBinaryProfile


def summarize_dfu3500_micc_control(
    data: bytes,
    *,
    profile: DfuBinaryProfile,
) -> dict[str, Any]:
    """Return a compact task/subtask control-plane summary.

    This is intentionally profile-specific.  It turns the raw MICC rows into the
    first diagnostic questions the earlier manual payload work repeatedly needed:

    - which task rows are active-ish?
    - how many subtasks does each task claim?
    - which subtask rows are active-ish?
    """

    if profile.target != "dfu3500" or "micc" not in profile.files:
        return {
            "available": False,
            "reason": "dfu3500 MICC control summary requires a dfu3500 micc profile",
        }

    task_section = profile.files["micc"].sections[0]
    subtask_section = profile.files["micc"].sections[1]
    tasks = []
    active_task_ids = []
    for task_id in range(task_section.row_count()):
        row = decode_row(
            data,
            file_kind="micc",
            section_name="tasks",
            row_index=task_id,
            profile=profile,
        )
        if row["status"] != "ok":
            return {
                "available": False,
                "reason": "failed to decode task rows",
                "diagnostics": row.get("diagnostics", []),
            }
        fields = _field_values(row["row"])
        activeish = bool(
            fields.get("is_exe_start")
            or fields.get("is_exe_end")
            or fields.get("subtasks_amount")
            or fields.get("execute_times")
            or any(fields.get("subtasks_idx", []))
        )
        if activeish:
            active_task_ids.append(task_id)
        tasks.append(
            {
                "task_id": task_id,
                "active_ish": activeish,
                "is_exe_start": fields.get("is_exe_start"),
                "is_exe_end": fields.get("is_exe_end"),
                "subtasks_amount": fields.get("subtasks_amount"),
                "execute_times": fields.get("execute_times"),
                "subtasks_idx": fields.get("subtasks_idx", []),
                "suc_tasks": fields.get("suc_tasks", []),
            }
        )

    subtasks = []
    active_subtask_ids = []
    for row_index in range(subtask_section.row_count()):
        row = decode_row(
            data,
            file_kind="micc",
            section_name="subtasks",
            row_index=row_index,
            profile=profile,
            max_array_elements=4,
        )
        if row["status"] != "ok":
            return {
                "available": False,
                "reason": "failed to decode subtask rows",
                "diagnostics": row.get("diagnostics", []),
            }
        fields = _field_values(row["row"])
        indices = row["row"]["row_indices"]
        activeish = bool(
            fields.get("is_exe_start")
            or fields.get("is_exe_end")
            or fields.get("instances_amount")
            or fields.get("root_block_amount")
            or fields.get("block_amount")
            or fields.get("subtask_idx")
            or fields.get("task_idx")
            or fields.get("exeBlocks_conf_info_nonzero_element_count")
        )
        if activeish:
            active_subtask_ids.append(
                {
                    "task": indices["task"],
                    "subtask": indices["subtask"],
                }
            )
        subtasks.append(
            {
                "task": indices["task"],
                "subtask": indices["subtask"],
                "active_ish": activeish,
                "is_exe_start": fields.get("is_exe_start"),
                "is_exe_end": fields.get("is_exe_end"),
                "instances_amount": fields.get("instances_amount"),
                "root_block_amount": fields.get("root_block_amount"),
                "block_amount": fields.get("block_amount"),
                "subtask_idx": fields.get("subtask_idx"),
                "task_idx": fields.get("task_idx"),
                "embedded_exeblock_nonzero_count": fields.get(
                    "exeBlocks_conf_info_nonzero_element_count"
                ),
            }
        )

    return {
        "available": True,
        "active_task_count": len(active_task_ids),
        "active_task_ids": active_task_ids,
        "active_subtask_count": len(active_subtask_ids),
        "active_subtask_ids": active_subtask_ids,
        "tasks": tasks,
        "subtasks": subtasks,
    }


def diff_dfu3500_micc_control(
    left: dict[str, Any],
    right: dict[str, Any],
) -> dict[str, Any]:
    if not left.get("available") or not right.get("available"):
        return {
            "available": False,
            "reason": "one side has no DFU3500 MICC control summary",
        }

    task_diffs = []
    left_tasks = {task["task_id"]: task for task in left["tasks"]}
    right_tasks = {task["task_id"]: task for task in right["tasks"]}
    for task_id in sorted(set(left_tasks) | set(right_tasks)):
        left_task = left_tasks.get(task_id)
        right_task = right_tasks.get(task_id)
        changed = _changed_fields(
            left_task or {},
            right_task or {},
            (
                "active_ish",
                "is_exe_start",
                "is_exe_end",
                "subtasks_amount",
                "execute_times",
                "subtasks_idx",
                "suc_tasks",
            ),
        )
        if changed:
            task_diffs.append(
                {
                    "task_id": task_id,
                    "changed_fields": changed,
                }
            )

    subtask_diffs = []
    left_subtasks = {
        (subtask["task"], subtask["subtask"]): subtask
        for subtask in left["subtasks"]
    }
    right_subtasks = {
        (subtask["task"], subtask["subtask"]): subtask
        for subtask in right["subtasks"]
    }
    for key in sorted(set(left_subtasks) | set(right_subtasks)):
        left_subtask = left_subtasks.get(key)
        right_subtask = right_subtasks.get(key)
        changed = _changed_fields(
            left_subtask or {},
            right_subtask or {},
            (
                "active_ish",
                "is_exe_start",
                "is_exe_end",
                "instances_amount",
                "root_block_amount",
                "block_amount",
                "subtask_idx",
                "task_idx",
                "embedded_exeblock_nonzero_count",
            ),
        )
        if changed:
            subtask_diffs.append(
                {
                    "task": key[0],
                    "subtask": key[1],
                    "changed_fields": changed,
                }
            )

    return {
        "available": True,
        "active_task_count": {
            "left": left["active_task_count"],
            "right": right["active_task_count"],
        },
        "active_subtask_count": {
            "left": left["active_subtask_count"],
            "right": right["active_subtask_count"],
        },
        "task_diff_count": len(task_diffs),
        "subtask_diff_count": len(subtask_diffs),
        "task_diffs": task_diffs,
        "subtask_diffs": subtask_diffs,
    }


def _field_values(row: dict[str, Any]) -> dict[str, Any]:
    values: dict[str, Any] = {}
    for field in row["fields"]:
        name = field["field"]
        if field["decode_status"] == "array_summary":
            values[f"{name}_nonzero_element_count"] = field["nonzero_element_count"]
        elif "values" in field:
            raw_values = [item["value"] for item in field["values"]]
            values[name] = raw_values if field["count"] != 1 else raw_values[0]
    return values


def _changed_fields(
    left: dict[str, Any],
    right: dict[str, Any],
    field_names: tuple[str, ...],
) -> dict[str, dict[str, Any]]:
    changed = {}
    for field_name in field_names:
        left_value = left.get(field_name)
        right_value = right.get(field_name)
        if left_value != right_value:
            changed[field_name] = {
                "left": left_value,
                "right": right_value,
            }
    return changed
