"""Vendor-like row grouping for B-line debug artifacts.

This module is still report-only.  It groups already-emitted debug rows by
vendor-shaped coordinates such as task, subtask slot, and loop instance.  It
does not write bytes and does not recover semantics from legacy block kinds.
"""

from __future__ import annotations

from dataclasses import dataclass

from .debug_emit import DebugRowArtifact
from .template_ops import Diagnostic


@dataclass(frozen=True)
class VendorLikeRowGroup:
    """A stable report-only row bucket."""

    id: str
    group_kind: str
    task_id: int | None
    subtask_slot: str
    loop_instance: str | None
    instruction_rows: tuple[dict[str, object], ...]
    zero_boundaries: tuple[dict[str, object], ...]

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "group_kind": self.group_kind,
            "task_id": self.task_id,
            "subtask_slot": self.subtask_slot,
            "loop_instance": self.loop_instance,
            "instruction_rows": list(self.instruction_rows),
            "zero_boundaries": list(self.zero_boundaries),
            "instruction_row_count": len(self.instruction_rows),
            "zero_boundary_count": len(self.zero_boundaries),
        }


@dataclass(frozen=True)
class VendorLikeRowGroupPlan:
    """Report-only vendor-shaped grouping over debug rows."""

    profile_id: str
    runnability_state: str
    groups: tuple[VendorLikeRowGroup, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_vendor_like_row_group_plan",
            "profile_id": self.profile_id,
            "runnability_state": self.runnability_state,
            "groups": [group.to_plan() for group in self.groups],
            "diagnostics": [
                diagnostic.to_plan() for diagnostic in self.diagnostics
            ],
            "layering_policy": (
                "vendor_like_row_group_plan_consumes_debug_row_artifact;"
                "groups_rows_without_emitting_vendor_binary_bytes"
            ),
        }


@dataclass(frozen=True)
class VendorLikeLocalRemapGroup:
    """A vendor-like group with local row/PC numbering."""

    group_id: str
    task_id: int | None
    subtask_slot: str
    loop_instance: str | None
    instruction_rows: tuple[dict[str, object], ...]
    zero_boundaries: tuple[dict[str, object], ...]

    def to_plan(self) -> dict[str, object]:
        return {
            "group_id": self.group_id,
            "task_id": self.task_id,
            "subtask_slot": self.subtask_slot,
            "loop_instance": self.loop_instance,
            "instruction_rows": list(self.instruction_rows),
            "zero_boundaries": list(self.zero_boundaries),
            "instruction_row_count": len(self.instruction_rows),
            "zero_boundary_count": len(self.zero_boundaries),
        }


@dataclass(frozen=True)
class VendorLikeLocalRemapPlan:
    """Report-only local row numbering view over vendor-like groups."""

    profile_id: str
    runnability_state: str
    groups: tuple[VendorLikeLocalRemapGroup, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_vendor_like_local_remap_plan",
            "profile_id": self.profile_id,
            "runnability_state": self.runnability_state,
            "groups": [group.to_plan() for group in self.groups],
            "diagnostics": [
                diagnostic.to_plan() for diagnostic in self.diagnostics
            ],
            "layering_policy": (
                "vendor_like_local_remap_plan_consumes_vendor_like_row_group_plan;"
                "adds_group_local_numbering_without_emitting_vendor_binary_bytes"
            ),
        }


def group_debug_rows_vendor_like(
    artifact: DebugRowArtifact,
) -> VendorLikeRowGroupPlan:
    """Group debug rows by task/subtask/loop instance."""

    diagnostics = list(artifact.diagnostics)
    buckets: dict[tuple[int | None, str, str | None], dict[str, list[dict[str, object]]]] = {}
    for row in artifact.instruction_rows:
        key = _row_key(row)
        buckets.setdefault(key, {"instruction": [], "zero": []})["instruction"].append(row)
    for row in artifact.zero_boundaries:
        key = _row_key(row)
        buckets.setdefault(key, {"instruction": [], "zero": []})["zero"].append(row)

    groups = []
    for index, (key, rows) in enumerate(sorted(buckets.items(), key=_bucket_sort_key)):
        task_id, subtask_slot, loop_instance = key
        groups.append(
            VendorLikeRowGroup(
                id=f"vendor_group:{index:04d}:{_key_label(key)}",
                group_kind="task_subtask_loop_bucket",
                task_id=task_id,
                subtask_slot=subtask_slot,
                loop_instance=loop_instance,
                instruction_rows=tuple(
                    sorted(rows["instruction"], key=_row_sort_key)
                ),
                zero_boundaries=tuple(
                    sorted(rows["zero"], key=_zero_sort_key)
                ),
            )
        )

    return VendorLikeRowGroupPlan(
        profile_id=artifact.profile_id,
        runnability_state=artifact.runnability_state,
        groups=tuple(groups),
        diagnostics=tuple(diagnostics),
    )


def remap_vendor_like_groups_locally(
    plan: VendorLikeRowGroupPlan,
) -> VendorLikeLocalRemapPlan:
    """Add local row/PC numbering inside each vendor-like group."""

    remapped_groups = []
    for group in plan.groups:
        remapped_rows = []
        for local_index, row in enumerate(group.instruction_rows):
            remapped = dict(row)
            remapped["global_row_index"] = row.get("row_index")
            remapped["global_pc"] = row.get("pc")
            remapped["local_row_index"] = local_index
            remapped["local_pc"] = local_index
            remapped_rows.append(remapped)
        remapped_boundaries = []
        for local_index, row in enumerate(group.zero_boundaries):
            remapped = dict(row)
            remapped["local_boundary_index"] = local_index
            remapped["local_pc"] = None
            remapped["occupies_local_instruction_row"] = False
            remapped_boundaries.append(remapped)
        remapped_groups.append(
            VendorLikeLocalRemapGroup(
                group_id=group.id,
                task_id=group.task_id,
                subtask_slot=group.subtask_slot,
                loop_instance=group.loop_instance,
                instruction_rows=tuple(remapped_rows),
                zero_boundaries=tuple(remapped_boundaries),
            )
        )
    return VendorLikeLocalRemapPlan(
        profile_id=plan.profile_id,
        runnability_state=plan.runnability_state,
        groups=tuple(remapped_groups),
        diagnostics=plan.diagnostics,
    )


def summarize_vendor_like_row_group_plan(
    plan: VendorLikeRowGroupPlan,
) -> dict[str, object]:
    """Return stable counts for checks and review reports."""

    group_kind_counts: dict[str, int] = {}
    task_group_counts: dict[str, int] = {}
    subtask_group_counts: dict[str, int] = {}
    loop_group_counts: dict[str, int] = {}
    instruction_rows = 0
    zero_boundaries = 0
    diagnostic_severity_counts: dict[str, int] = {}
    forbidden_tile_micro_block_fields = 0
    missing_provenance_count = 0

    for diagnostic in plan.diagnostics:
        diagnostic_severity_counts[diagnostic.severity] = (
            diagnostic_severity_counts.get(diagnostic.severity, 0) + 1
        )
    for group in plan.groups:
        group_kind_counts[group.group_kind] = group_kind_counts.get(group.group_kind, 0) + 1
        task_key = "none" if group.task_id is None else str(group.task_id)
        task_group_counts[task_key] = task_group_counts.get(task_key, 0) + 1
        subtask_group_counts[group.subtask_slot] = subtask_group_counts.get(group.subtask_slot, 0) + 1
        loop_key = "none" if group.loop_instance is None else group.loop_instance
        loop_group_counts[loop_key] = loop_group_counts.get(loop_key, 0) + 1
        instruction_rows += len(group.instruction_rows)
        zero_boundaries += len(group.zero_boundaries)
        for row in (*group.instruction_rows, *group.zero_boundaries):
            forbidden_tile_micro_block_fields += _forbidden_field_count(row)
            if not row.get("template_op_id") or not row.get("primary_fiber_op_id"):
                missing_provenance_count += 1

    return {
        "profile_id": plan.profile_id,
        "runnability_state": plan.runnability_state,
        "group_count": len(plan.groups),
        "instruction_row_count": instruction_rows,
        "zero_boundary_count": zero_boundaries,
        "group_kind_counts": dict(sorted(group_kind_counts.items())),
        "task_group_counts": dict(sorted(task_group_counts.items())),
        "subtask_group_counts": dict(sorted(subtask_group_counts.items())),
        "loop_group_counts": dict(sorted(loop_group_counts.items())),
        "diagnostic_severity_counts": dict(sorted(diagnostic_severity_counts.items())),
        "diagnostic_count": len(plan.diagnostics),
        "missing_provenance_count": missing_provenance_count,
        "forbidden_tile_micro_block_field_count": forbidden_tile_micro_block_fields,
    }


def summarize_vendor_like_local_remap_plan(
    plan: VendorLikeLocalRemapPlan,
) -> dict[str, object]:
    """Return stable counts for local-remap checks."""

    instruction_rows = 0
    zero_boundaries = 0
    diagnostic_severity_counts: dict[str, int] = {}
    non_dense_local_pc_groups: list[str] = []
    zero_boundaries_with_pc = 0
    missing_global_index_count = 0
    forbidden_tile_micro_block_fields = 0

    for diagnostic in plan.diagnostics:
        diagnostic_severity_counts[diagnostic.severity] = (
            diagnostic_severity_counts.get(diagnostic.severity, 0) + 1
        )
    for group in plan.groups:
        instruction_rows += len(group.instruction_rows)
        zero_boundaries += len(group.zero_boundaries)
        local_pcs = [row.get("local_pc") for row in group.instruction_rows]
        if local_pcs != list(range(len(group.instruction_rows))):
            non_dense_local_pc_groups.append(group.group_id)
        for row in group.instruction_rows:
            if row.get("global_row_index") is None or row.get("global_pc") is None:
                missing_global_index_count += 1
            forbidden_tile_micro_block_fields += _forbidden_field_count(row)
        for row in group.zero_boundaries:
            if row.get("local_pc") is not None or row.get("pc") is not None:
                zero_boundaries_with_pc += 1
            forbidden_tile_micro_block_fields += _forbidden_field_count(row)

    return {
        "profile_id": plan.profile_id,
        "runnability_state": plan.runnability_state,
        "group_count": len(plan.groups),
        "instruction_row_count": instruction_rows,
        "zero_boundary_count": zero_boundaries,
        "diagnostic_severity_counts": dict(sorted(diagnostic_severity_counts.items())),
        "diagnostic_count": len(plan.diagnostics),
        "non_dense_local_pc_group_count": len(non_dense_local_pc_groups),
        "non_dense_local_pc_groups": sorted(non_dense_local_pc_groups),
        "zero_boundaries_with_pc_count": zero_boundaries_with_pc,
        "missing_global_index_count": missing_global_index_count,
        "forbidden_tile_micro_block_field_count": forbidden_tile_micro_block_fields,
    }


def _row_key(row: dict[str, object]) -> tuple[int | None, str, str | None]:
    task_value = row.get("task_id")
    task_id = task_value if isinstance(task_value, int) else None
    subtask_slot = str(row.get("subtask_slot"))
    loop_value = row.get("loop_instance")
    loop_instance = None if loop_value is None else str(loop_value)
    return task_id, subtask_slot, loop_instance


def _bucket_sort_key(
    item: tuple[
        tuple[int | None, str, str | None],
        dict[str, list[dict[str, object]]],
    ],
) -> tuple[int, str, str]:
    task_id, subtask_slot, loop_instance = item[0]
    task_sort = -1 if task_id is None else task_id
    loop_sort = "" if loop_instance is None else loop_instance
    return task_sort, subtask_slot, loop_sort


def _row_sort_key(row: dict[str, object]) -> tuple[int, str]:
    row_index = row.get("row_index")
    return (row_index if isinstance(row_index, int) else -1, str(row.get("role")))


def _zero_sort_key(row: dict[str, object]) -> tuple[str, str]:
    return (str(row.get("role")), str(row.get("template_op_id")))


def _key_label(key: tuple[int | None, str, str | None]) -> str:
    task_id, subtask_slot, loop_instance = key
    task_text = "task_none" if task_id is None else f"task{task_id}"
    loop_text = "loop_none" if loop_instance is None else loop_instance
    return f"{task_text}:{subtask_slot}:{loop_text}"


def _forbidden_field_count(row: dict[str, object]) -> int:
    return sum(
        1
        for key in row
        if key.startswith("source_tile_micro_block") or key == "tile_micro_block_kind"
    )


__all__ = [
    "VendorLikeLocalRemapGroup",
    "VendorLikeLocalRemapPlan",
    "VendorLikeRowGroup",
    "VendorLikeRowGroupPlan",
    "group_debug_rows_vendor_like",
    "remap_vendor_like_groups_locally",
    "summarize_vendor_like_local_remap_plan",
    "summarize_vendor_like_row_group_plan",
]
