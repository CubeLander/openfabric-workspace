"""DFU3500 MICC/CBUF control-plane checks for payload-local validation."""

from __future__ import annotations

import json
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping

from ..dfu_binary_checks.payload_conformance import build_payload_inventory
from ..dfu_binary_checks.report import CheckSpec, ReadinessLevel, ValidationIssue, ValidationReport, sha256_file
from ...decoder.dfu3500_diagnostics import summarize_dfu3500_micc_control
from ...decoder.binary_layout import DfuBinaryProfile

DFU3500_CONTROL_GRAPH_SPEC = CheckSpec(
    name="dfu3500_control_graph",
    applies_to=(ReadinessLevel.RUNTIME_READY,),
    authoritative=True,
    required_inputs=("result/micc_file.bin", "runtime/riscv_src/riscv_control.json"),
)


@dataclass(frozen=True)
class _ExeBlockNode:
    row: int
    block_idx: int
    req_activations: int
    child_amount: int
    predecessors: tuple[int, ...]
    successors: tuple[int, ...]
    is_leaf: int


def run_dfu3500_control_graph_check(
    artifact_root: Path,
    profile: DfuBinaryProfile,
    *,
    requested_gate: ReadinessLevel,
) -> ValidationReport:
    issues: list[ValidationIssue] = []
    input_paths: list[str] = []
    input_sha256: dict[str, str] = {}

    micc_path = artifact_root / "result/micc_file.bin"
    if not micc_path.is_file():
        issues.append(_issue("dfu3500_micc_missing", "Missing result/micc_file.bin.", "result/micc_file.bin"))
        micc = b""
    else:
        micc = micc_path.read_bytes()
        input_paths.append("result/micc_file.bin")
        input_sha256["result/micc_file.bin"] = sha256_file(micc_path)

    runtime_control_path = artifact_root / "runtime/riscv_src/riscv_control.json"
    runtime_control: Mapping[str, Any] | None = None
    if runtime_control_path.is_file():
        input_paths.append("runtime/riscv_src/riscv_control.json")
        input_sha256["runtime/riscv_src/riscv_control.json"] = sha256_file(runtime_control_path)
        try:
            runtime_control = json.loads(runtime_control_path.read_text())
        except json.JSONDecodeError as exc:
            issues.append(
                _issue(
                    "dfu3500_runtime_control_json_invalid",
                    f"runtime control JSON is invalid: {exc}",
                    "runtime/riscv_src/riscv_control.json",
                )
            )
    else:
        issues.append(
            _issue(
                "dfu3500_runtime_control_missing",
                "Missing runtime/riscv_src/riscv_control.json.",
                "runtime/riscv_src/riscv_control.json",
            )
        )

    expected_task_count = _expected_task_count(artifact_root, runtime_control)
    if expected_task_count is None:
        issues.append(
            _issue(
                "dfu3500_expected_task_count_missing",
                "Cannot determine expected task count from runtime control or MANIFEST.",
                "runtime/riscv_src/riscv_control.json",
            )
        )

    if micc and len(micc) == profile.files["micc"].size(profile):
        _check_micc_control_bytes(micc, profile, expected_task_count, issues)
    elif micc:
        issues.append(
            _issue(
                "dfu3500_micc_size_mismatch",
                f"MICC size is {len(micc)}, expected {profile.files['micc'].size(profile)}.",
                "result/micc_file.bin",
            )
        )

    status = "fail" if issues else "pass"
    return ValidationReport(
        schema_version="dfu_validation_check_report_v1",
        check_name=DFU3500_CONTROL_GRAPH_SPEC.name,
        status=status,
        authoritative=DFU3500_CONTROL_GRAPH_SPEC.applies_to_gate(requested_gate),
        requested_gate=requested_gate,
        profile_id=profile.profile_id,
        profile_sha256=profile.profile_sha256(),
        input_paths=tuple(input_paths),
        input_sha256=input_sha256,
        policy={"mode": "strict", "source": "dfu3500_payload_control_metadata"},
        issues=tuple(issues),
    )


def _expected_task_count(
    artifact_root: Path,
    runtime_control: Mapping[str, Any] | None,
) -> int | None:
    if runtime_control is not None:
        launches = runtime_control.get("launches")
        if isinstance(launches, list) and len(launches) == 1 and isinstance(launches[0], dict):
            task_count = launches[0].get("task_count")
            if isinstance(task_count, int) and task_count > 0:
                return task_count
    inventory = build_payload_inventory(artifact_root)
    task_num = inventory.manifest.get("task_num")
    if task_num is None:
        return None
    try:
        value = int(task_num)
    except ValueError:
        return None
    return value if value > 0 else None


def _check_micc_control_bytes(
    micc: bytes,
    profile: DfuBinaryProfile,
    expected_task_count: int | None,
    issues: list[ValidationIssue],
) -> None:
    summary = summarize_dfu3500_micc_control(micc, profile=profile)
    if not summary.get("available"):
        issues.append(_issue("dfu3500_micc_summary_unavailable", str(summary.get("reason")), "result/micc_file.bin"))
        return
    if expected_task_count is not None and summary["active_task_count"] != expected_task_count:
        issues.append(
            _issue(
                "dfu3500_active_task_count_mismatch",
                f"MICC has {summary['active_task_count']} active-ish task rows, expected {expected_task_count}.",
                "result/micc_file.bin",
                details={
                    "active_task_ids": summary["active_task_ids"],
                    "expected_task_count": expected_task_count,
                },
            )
        )
    active_task_ids = set(summary["active_task_ids"])
    for task in summary["tasks"]:
        if not task["active_ish"]:
            continue
        task_id = int(task["task_id"])
        if expected_task_count is not None and task_id >= expected_task_count:
            issues.append(
                _issue(
                    "dfu3500_active_task_outside_expected_range",
                    f"Task row {task_id} is active but expected task count is {expected_task_count}.",
                    f"micc.tasks[task={task_id}]",
                )
            )
        subtasks_amount = int(task.get("subtasks_amount") or 0)
        if not 1 <= subtasks_amount <= 8:
            issues.append(
                _issue(
                    "dfu3500_task_subtasks_amount_invalid",
                    f"Task {task_id} declares invalid subtasks_amount={subtasks_amount}.",
                    f"micc.tasks[task={task_id}].subtasks_amount",
                )
            )
        referenced_subtasks = _referenced_indices(task.get("subtasks_idx", []), subtasks_amount, 8)
        if len(referenced_subtasks) != len(set(referenced_subtasks)):
            issues.append(
                _issue(
                    "dfu3500_task_subtasks_duplicate",
                    f"Task {task_id} references duplicate subtasks: {referenced_subtasks}.",
                    f"micc.tasks[task={task_id}].subtasks_idx",
                )
            )
        for subtask_id in referenced_subtasks:
            subtask = _subtask_summary(summary, task_id, subtask_id)
            if subtask is None or not subtask["active_ish"]:
                issues.append(
                    _issue(
                        "dfu3500_task_references_inactive_subtask",
                        f"Task {task_id} references inactive subtask {subtask_id}.",
                        f"micc.subtasks[task={task_id}][subtask={subtask_id}]",
                    )
                )
        referenced_active_subtasks = [
            subtask
            for subtask_id in referenced_subtasks
            if (subtask := _subtask_summary(summary, task_id, subtask_id)) is not None
            and subtask["active_ish"]
        ]
        start_count = sum(1 for subtask in referenced_active_subtasks if subtask.get("is_exe_start"))
        end_count = sum(1 for subtask in referenced_active_subtasks if subtask.get("is_exe_end"))
        if referenced_active_subtasks and start_count != 1:
            issues.append(
                _issue(
                    "dfu3500_task_start_subtask_count_invalid",
                    f"Task {task_id} has {start_count} start subtasks; expected exactly one.",
                    f"micc.tasks[task={task_id}]",
                )
            )
        if referenced_active_subtasks and end_count != 1:
            issues.append(
                _issue(
                    "dfu3500_task_end_subtask_count_invalid",
                    f"Task {task_id} has {end_count} end subtasks; expected exactly one.",
                    f"micc.tasks[task={task_id}]",
                )
            )
        _check_referenced_subtask_successor_graph(
            micc,
            profile,
            task_id,
            {int(subtask["subtask"]) for subtask in referenced_active_subtasks},
            {
                int(subtask["subtask"])
                for subtask in referenced_active_subtasks
                if subtask.get("is_exe_start")
            },
            issues,
        )
    _check_task_successors(summary, expected_task_count, active_task_ids, issues)
    for subtask in summary["subtasks"]:
        if not subtask["active_ish"]:
            continue
        task_id = int(subtask["task"])
        subtask_id = int(subtask["subtask"])
        if task_id not in active_task_ids:
            issues.append(
                _issue(
                    "dfu3500_active_subtask_has_inactive_task",
                    f"Subtask ({task_id}, {subtask_id}) is active while task {task_id} is inactive.",
                    f"micc.subtasks[task={task_id}][subtask={subtask_id}]",
                )
            )
        if int(subtask.get("task_idx") or 0) != task_id:
            issues.append(
                _issue(
                    "dfu3500_subtask_task_idx_mismatch",
                    f"Subtask ({task_id}, {subtask_id}) task_idx={subtask.get('task_idx')} does not match row task.",
                    f"micc.subtasks[task={task_id}][subtask={subtask_id}].task_idx",
                )
            )
        if int(subtask.get("subtask_idx") or 0) != subtask_id:
            issues.append(
                _issue(
                    "dfu3500_subtask_idx_mismatch",
                    f"Subtask ({task_id}, {subtask_id}) subtask_idx={subtask.get('subtask_idx')} does not match row subtask.",
                    f"micc.subtasks[task={task_id}][subtask={subtask_id}].subtask_idx",
                )
            )
        _check_active_exeblocks(
            micc,
            profile,
            task_id,
            subtask_id,
            int(subtask.get("root_block_amount") or 0),
            int(subtask.get("block_amount") or 0),
            issues,
        )


def _referenced_indices(values: Any, amount: int, max_count: int) -> list[int]:
    if not isinstance(values, list):
        return []
    indices: list[int] = []
    for value in values[:amount]:
        if isinstance(value, int) and 0 <= value < max_count:
            indices.append(value)
    return indices


def _subtask_summary(summary: Mapping[str, Any], task_id: int, subtask_id: int) -> Mapping[str, Any] | None:
    for subtask in summary["subtasks"]:
        if subtask["task"] == task_id and subtask["subtask"] == subtask_id:
            return subtask
    return None


def _check_task_successors(
    summary: Mapping[str, Any],
    expected_task_count: int | None,
    active_task_ids: set[int],
    issues: list[ValidationIssue],
) -> None:
    successor_graph: dict[int, set[int]] = {}
    for task in summary["tasks"]:
        if not task["active_ish"]:
            continue
        task_id = int(task["task_id"])
        raw_successors = task.get("suc_tasks", [])
        successors = [
            int(successor)
            for successor in raw_successors
            if isinstance(successor, int) and successor != 0
        ]
        successor_graph[task_id] = set(successors)
        if len(successors) != len(set(successors)):
            issues.append(
                _issue(
                    "dfu3500_task_successor_duplicate",
                    f"Task {task_id} declares duplicate successors: {successors}.",
                    f"micc.tasks[task={task_id}].suc_tasks",
                )
            )
        for successor in successors:
            if expected_task_count is not None and successor >= expected_task_count:
                issues.append(
                    _issue(
                        "dfu3500_task_successor_outside_expected_range",
                        (
                            f"Task {task_id} successor {successor} is outside "
                            f"expected task count {expected_task_count}."
                        ),
                        f"micc.tasks[task={task_id}].suc_tasks",
                    )
                )
            if successor not in active_task_ids:
                issues.append(
                    _issue(
                        "dfu3500_task_successor_inactive",
                        (
                            f"Task {task_id} successor {successor} is not an "
                            "active task row."
                        ),
                        f"micc.tasks[task={task_id}].suc_tasks",
                    )
                )
    for cycle in _successor_cycles(successor_graph):
        issues.append(
            _issue(
                "dfu3500_task_successor_cycle",
                (
                    "Task successor graph contains a cycle; this can deadlock "
                    f"task completion: {cycle}."
                ),
                "micc.tasks.suc_tasks",
                details={"cycle": cycle},
            )
        )


def _check_referenced_subtask_successor_graph(
    micc: bytes,
    profile: DfuBinaryProfile,
    task_id: int,
    referenced_subtasks: set[int],
    start_subtasks: set[int],
    issues: list[ValidationIssue],
) -> None:
    successor_graph: dict[int, set[int]] = {}
    for subtask_id in sorted(referenced_subtasks):
        subtask_offset = profile.files["micc"].sections[1].offset + (
            task_id * 8 + subtask_id
        ) * profile.structs["sub_task_conf_info_t"].size
        successors = [
            successor
            for successor in _u64_array(micc, subtask_offset + 24, 4)
            if successor != 0
        ]
        successor_graph[subtask_id] = set(successors)
        if len(successors) != len(set(successors)):
            issues.append(
                _issue(
                    "dfu3500_subtask_successor_duplicate",
                    (
                        f"Subtask ({task_id}, {subtask_id}) declares duplicate "
                        f"successors: {successors}."
                    ),
                    f"micc.subtasks[task={task_id}][subtask={subtask_id}].suc_subtasks",
                )
            )
        for successor in successors:
            if successor not in referenced_subtasks:
                issues.append(
                    _issue(
                        "dfu3500_subtask_successor_inactive",
                        f"Subtask ({task_id}, {subtask_id}) successor {successor} is not an active subtask for task {task_id}.",
                        f"micc.subtasks[task={task_id}][subtask={subtask_id}].suc_subtasks",
                    )
                )
    for cycle in _successor_cycles(successor_graph):
        issues.append(
            _issue(
                "dfu3500_subtask_successor_cycle",
                (
                    "Subtask successor graph contains a cycle; this can "
                    f"deadlock subtask completion: {cycle}."
                ),
                f"micc.subtasks[task={task_id}].suc_subtasks",
                details={"task_id": task_id, "cycle": cycle},
            )
        )
    if any(successor_graph.values()) and start_subtasks:
        reachable = _reachable_indices(start_subtasks, successor_graph)
        for subtask_id in sorted(referenced_subtasks - reachable):
            issues.append(
                _issue(
                    "dfu3500_subtask_unreachable_from_start",
                    (
                        f"Subtask ({task_id}, {subtask_id}) is not reachable "
                        "from any start subtask through declared successors."
                    ),
                    f"micc.subtasks[task={task_id}][subtask={subtask_id}]",
                    details={
                        "task_id": task_id,
                        "subtask_id": subtask_id,
                        "start_subtasks": sorted(start_subtasks),
                    },
                )
            )


def _check_active_exeblocks(
    micc: bytes,
    profile: DfuBinaryProfile,
    task_id: int,
    subtask_id: int,
    root_block_amount: int,
    block_amount: int,
    issues: list[ValidationIssue],
) -> None:
    if block_amount < 0 or block_amount > 512:
        issues.append(
            _issue(
                "dfu3500_subtask_block_amount_invalid",
                f"Subtask ({task_id}, {subtask_id}) declares invalid block_amount={block_amount}.",
                f"micc.subtasks[task={task_id}][subtask={subtask_id}].block_amount",
            )
        )
        return
    if root_block_amount < 0 or root_block_amount > block_amount:
        issues.append(
            _issue(
                "dfu3500_subtask_root_block_amount_invalid",
                f"Subtask ({task_id}, {subtask_id}) declares root_block_amount={root_block_amount}, block_amount={block_amount}.",
                f"micc.subtasks[task={task_id}][subtask={subtask_id}].root_block_amount",
            )
        )
    if block_amount > 0 and root_block_amount == 0:
        issues.append(
            _issue(
                "dfu3500_subtask_root_block_missing",
                f"Subtask ({task_id}, {subtask_id}) has block_amount={block_amount} but no root blocks.",
                f"micc.subtasks[task={task_id}][subtask={subtask_id}].root_block_amount",
            )
        )
    subtask_offset = profile.files["micc"].sections[1].offset + (
        task_id * 8 + subtask_id
    ) * profile.structs["sub_task_conf_info_t"].size
    exeblocks_offset = subtask_offset + 72
    exeblock_size = profile.structs["exeBlock_conf_info_t"].size
    inst_limit = profile.files["cbuf"].sections[0].dimensions[1].size
    valid_count = 0
    for block_row in range(512):
        base = exeblocks_offset + block_row * exeblock_size
        if _u8(micc, base):
            valid_count += 1
    if valid_count != block_amount:
        issues.append(
            _issue(
                "dfu3500_subtask_valid_exeblock_count_mismatch",
                f"Subtask ({task_id}, {subtask_id}) has {valid_count} valid exeBlock rows, block_amount={block_amount}.",
                f"micc.subtasks[task={task_id}][subtask={subtask_id}].exeBlocks_conf_info",
            )
    )
    graph_nodes: list[_ExeBlockNode] = []
    for block_row in range(block_amount):
        base = exeblocks_offset + block_row * exeblock_size
        valid = _u8(micc, base)
        if not valid:
            issues.append(
                _issue(
                    "dfu3500_subtask_expected_exeblock_invalid",
                    f"Subtask ({task_id}, {subtask_id}) block row {block_row} is inside block_amount but valid=0.",
                    f"micc.subtasks[task={task_id}][subtask={subtask_id}].exeBlocks_conf_info[{block_row}].valid",
                )
            )
            continue
        conf_base = base + 48
        block_idx = _u64(micc, conf_base + 376)
        req_activations = _u64(micc, conf_base)
        child_amount = _u64(micc, conf_base + 408)
        predecessors = _u64_array(micc, conf_base + 56, 20)
        successors = _u64_array(micc, conf_base + 216, 20)
        is_leaf = _u8(micc, conf_base + 464)
        graph_nodes.append(
            _ExeBlockNode(
                row=block_row,
                block_idx=block_idx,
                req_activations=req_activations,
                child_amount=child_amount,
                predecessors=predecessors,
                successors=successors,
                is_leaf=is_leaf,
            )
        )
        if req_activations > 20:
            issues.append(
                _issue(
                    "dfu3500_exeblock_req_activations_too_large",
                    (
                        f"ExeBlock row {block_row} req_activations={req_activations}, "
                        "but predecessor capacity is 20."
                    ),
                    f"micc.subtasks[task={task_id}][subtask={subtask_id}].exeBlocks_conf_info[{block_row}].exeBlock_conf.req_activations",
                )
            )
        if child_amount > 20:
            issues.append(
                _issue(
                    "dfu3500_exeblock_child_amount_too_large",
                    (
                        f"ExeBlock row {block_row} child_amount={child_amount}, "
                        "but successor capacity is 20."
                    ),
                    f"micc.subtasks[task={task_id}][subtask={subtask_id}].exeBlocks_conf_info[{block_row}].exeBlock_conf.child_amount",
                )
            )
        if block_amount > 0 and req_activations > block_amount - 1:
            issues.append(
                _issue(
                    "dfu3500_exeblock_req_activations_impossible",
                    (
                        f"ExeBlock row {block_row} requires {req_activations} "
                        f"activations with only {block_amount} active blocks."
                    ),
                    f"micc.subtasks[task={task_id}][subtask={subtask_id}].exeBlocks_conf_info[{block_row}].exeBlock_conf.req_activations",
                )
            )
        if block_amount > 0 and child_amount > block_amount - 1:
            issues.append(
                _issue(
                    "dfu3500_exeblock_child_amount_impossible",
                    (
                        f"ExeBlock row {block_row} declares {child_amount} children "
                        f"with only {block_amount} active blocks."
                    ),
                    f"micc.subtasks[task={task_id}][subtask={subtask_id}].exeBlocks_conf_info[{block_row}].exeBlock_conf.child_amount",
                )
            )
        if is_leaf and child_amount:
            issues.append(
                _issue(
                    "dfu3500_exeblock_leaf_has_children",
                    (
                        f"ExeBlock row {block_row} is marked leaf but declares "
                        f"child_amount={child_amount}."
                    ),
                    f"micc.subtasks[task={task_id}][subtask={subtask_id}].exeBlocks_conf_info[{block_row}].exeBlock_conf",
                )
            )
        conf_subtask_idx = _u64(micc, conf_base + 384)
        conf_task_idx = _u64(micc, conf_base + 392)
        if conf_task_idx != task_id or conf_subtask_idx != subtask_id:
            issues.append(
                _issue(
                    "dfu3500_exeblock_task_subtask_idx_mismatch",
                    (
                        f"ExeBlock row {block_row} stamps task/subtask "
                        f"({conf_task_idx}, {conf_subtask_idx}), expected ({task_id}, {subtask_id})."
                    ),
                    f"micc.subtasks[task={task_id}][subtask={subtask_id}].exeBlocks_conf_info[{block_row}].exeBlock_conf",
                )
            )
        stage_amounts = _u64_array(micc, conf_base + 432, 4)
        for stage_index, pc in enumerate(_u64_array(micc, conf_base + 16, 5)):
            if pc >= inst_limit:
                issues.append(
                    _issue(
                        "dfu3500_exeblock_stage_pc_out_of_range",
                        f"ExeBlock row {block_row} stage {stage_index} PC {pc} exceeds PE-local inst limit {inst_limit}.",
                        f"micc.subtasks[task={task_id}][subtask={subtask_id}].exeBlocks_conf_info[{block_row}].exeBlock_conf.stages_start_pc[{stage_index}]",
                    )
                )
            if stage_index < len(stage_amounts):
                amount = stage_amounts[stage_index]
                if amount and pc + amount > inst_limit:
                    issues.append(
                        _issue(
                            "dfu3500_exeblock_stage_span_out_of_range",
                            f"ExeBlock row {block_row} stage {stage_index} spans PC {pc} + amount {amount}, beyond PE-local inst limit {inst_limit}.",
                            f"micc.subtasks[task={task_id}][subtask={subtask_id}].exeBlocks_conf_info[{block_row}].exeBlock_conf",
                        )
                    )
    _check_exeblock_dependency_graph(
        task_id,
        subtask_id,
        root_block_amount,
        graph_nodes,
        issues,
    )


def _check_exeblock_dependency_graph(
    task_id: int,
    subtask_id: int,
    root_block_amount: int,
    nodes: list[_ExeBlockNode],
    issues: list[ValidationIssue],
) -> None:
    if not nodes:
        return
    by_block_idx = {node.block_idx: node for node in nodes}
    root_nodes = [node for node in nodes if node.req_activations == 0]
    if len(root_nodes) != root_block_amount:
        issues.append(
            _issue(
                "dfu3500_exeblock_root_count_mismatch",
                (
                    f"Subtask ({task_id}, {subtask_id}) declares root_block_amount="
                    f"{root_block_amount}, but {len(root_nodes)} exeBlocks have "
                    "req_activations=0."
                ),
                f"micc.subtasks[task={task_id}][subtask={subtask_id}].root_block_amount",
                details={
                    "declared_root_block_amount": root_block_amount,
                    "computed_root_block_count": len(root_nodes),
                    "computed_root_block_indices": [
                        node.block_idx for node in root_nodes
                    ],
                },
            )
        )
    declared_successors: dict[int, set[int]] = {}
    declared_predecessors: dict[int, set[int]] = {}
    for node in nodes:
        successors = tuple(node.successors[: min(node.child_amount, 20)])
        predecessors = tuple(node.predecessors[: min(node.req_activations, 20)])
        declared_successors[node.block_idx] = set(successors)
        declared_predecessors[node.block_idx] = set(predecessors)
        for successor in successors:
            if successor not in by_block_idx:
                issues.append(
                    _issue(
                        "dfu3500_exeblock_successor_missing",
                        (
                            f"ExeBlock block_idx={node.block_idx} declares "
                            f"successor {successor}, but that block is not active."
                        ),
                        f"micc.subtasks[task={task_id}][subtask={subtask_id}].exeBlocks_conf_info[{node.row}].exeBlock_conf.successors",
                    )
                )
        for predecessor in predecessors:
            if predecessor not in by_block_idx:
                issues.append(
                    _issue(
                        "dfu3500_exeblock_predecessor_missing",
                        (
                            f"ExeBlock block_idx={node.block_idx} declares "
                            f"predecessor {predecessor}, but that block is not active."
                        ),
                        f"micc.subtasks[task={task_id}][subtask={subtask_id}].exeBlocks_conf_info[{node.row}].exeBlock_conf.predecessors",
                    )
                )
    for node in nodes:
        for successor in declared_successors[node.block_idx]:
            if successor not in by_block_idx:
                continue
            if node.block_idx not in declared_predecessors.get(successor, set()):
                successor_row = by_block_idx[successor].row
                issues.append(
                    _issue(
                        "dfu3500_exeblock_successor_predecessor_mismatch",
                        (
                            f"ExeBlock block_idx={node.block_idx} names successor "
                            f"{successor}, but successor does not name it as a "
                            "predecessor."
                        ),
                        f"micc.subtasks[task={task_id}][subtask={subtask_id}].exeBlocks_conf_info[{successor_row}].exeBlock_conf.predecessors",
                        details={
                            "source_block_idx": node.block_idx,
                            "successor_block_idx": successor,
                        },
                    )
                )
        for predecessor in declared_predecessors[node.block_idx]:
            if predecessor not in by_block_idx:
                continue
            if node.block_idx not in declared_successors.get(predecessor, set()):
                predecessor_row = by_block_idx[predecessor].row
                issues.append(
                    _issue(
                        "dfu3500_exeblock_predecessor_successor_mismatch",
                        (
                            f"ExeBlock block_idx={node.block_idx} names predecessor "
                            f"{predecessor}, but predecessor does not name it as a "
                            "successor."
                        ),
                        f"micc.subtasks[task={task_id}][subtask={subtask_id}].exeBlocks_conf_info[{predecessor_row}].exeBlock_conf.successors",
                        details={
                            "block_idx": node.block_idx,
                            "predecessor_block_idx": predecessor,
                        },
                    )
                )
    if any(declared_successors.values()):
        reachable = _reachable_block_indices(root_nodes, declared_successors)
        for node in nodes:
            if node.block_idx not in reachable:
                issues.append(
                    _issue(
                        "dfu3500_exeblock_unreachable_from_roots",
                        (
                            f"ExeBlock block_idx={node.block_idx} is not reachable "
                            "from any root block through declared successors."
                        ),
                        f"micc.subtasks[task={task_id}][subtask={subtask_id}].exeBlocks_conf_info[{node.row}]",
                    )
                )
    cycles = _successor_cycles(declared_successors)
    for cycle in cycles:
        issues.append(
            _issue(
                "dfu3500_exeblock_successor_cycle",
                (
                    "ExeBlock successor graph contains a cycle; this can "
                    f"deadlock block completion: {cycle}."
                ),
                f"micc.subtasks[task={task_id}][subtask={subtask_id}].exeBlocks_conf_info",
                details={"cycle": cycle},
            )
        )


def _reachable_block_indices(
    roots: list[_ExeBlockNode],
    successors: Mapping[int, set[int]],
) -> set[int]:
    return _reachable_indices((node.block_idx for node in roots), successors)


def _reachable_indices(
    roots: Any,
    successors: Mapping[int, set[int]],
) -> set[int]:
    visited: set[int] = set()
    stack = list(roots)
    while stack:
        index = stack.pop()
        if index in visited:
            continue
        visited.add(index)
        stack.extend(sorted(successors.get(index, set()) - visited, reverse=True))
    return visited


def _successor_cycles(successors: Mapping[int, set[int]]) -> list[list[int]]:
    visited: set[int] = set()
    visiting: list[int] = []
    cycles: list[list[int]] = []
    seen_cycles: set[tuple[int, ...]] = set()

    def visit(block_idx: int) -> None:
        if block_idx in visiting:
            cycle = visiting[visiting.index(block_idx) :] + [block_idx]
            canonical = _canonical_cycle(cycle)
            if canonical not in seen_cycles:
                seen_cycles.add(canonical)
                cycles.append(cycle)
            return
        if block_idx in visited:
            return
        visiting.append(block_idx)
        for successor in sorted(successors.get(block_idx, ())):
            if successor in successors:
                visit(successor)
        visiting.pop()
        visited.add(block_idx)

    for block_idx in sorted(successors):
        visit(block_idx)
    return cycles


def _canonical_cycle(cycle: list[int]) -> tuple[int, ...]:
    if len(cycle) <= 1:
        return tuple(cycle)
    body = cycle[:-1]
    rotations = [tuple(body[index:] + body[:index]) for index in range(len(body))]
    canonical_body = min(rotations)
    return canonical_body + (canonical_body[0],)


def _u8(data: bytes, offset: int) -> int:
    return struct.unpack_from("<B", data, offset)[0]


def _u64(data: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", data, offset)[0]


def _u64_array(data: bytes, offset: int, count: int) -> tuple[int, ...]:
    return struct.unpack_from("<" + "Q" * count, data, offset)


def _issue(
    code: str,
    message: str,
    path: str,
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
