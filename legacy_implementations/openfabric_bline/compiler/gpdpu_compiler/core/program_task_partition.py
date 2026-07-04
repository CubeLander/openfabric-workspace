"""High-level task-axis partition metadata.

This layer is intentionally above DFU vendor task rows.  It records developer
chosen task-axis shape and task-axis placement requirements before processor
logical lowering starts.  It does not assign subtasks, exeBlocks, instruction
rows, or binary package layout.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gpdpu_compiler.core.program_app import AppPlan


@dataclass(frozen=True)
class TaskAxisMesh:
    """Restricted soft task axis attached to the chip physical/logical mesh."""

    task_axis_size: int
    physical_mesh_shape: tuple[int, ...]
    physical_mesh_dim_names: tuple[str, ...]
    axis_name: str = "task"

    def __post_init__(self) -> None:
        if self.task_axis_size <= 0:
            raise ValueError("task_axis_size must be positive")
        if not self.physical_mesh_shape:
            raise ValueError("physical_mesh_shape must be non-empty")
        if len(self.physical_mesh_shape) != len(self.physical_mesh_dim_names):
            raise ValueError("physical mesh dim_names rank must match shape rank")

    @property
    def soft_mesh_shape(self) -> tuple[int, ...]:
        return (self.task_axis_size, *self.physical_mesh_shape)

    @property
    def soft_mesh_dim_names(self) -> tuple[str, ...]:
        return (self.axis_name, *self.physical_mesh_dim_names)

    def to_plan(self) -> dict[str, Any]:
        return {
            "axis_name": self.axis_name,
            "task_axis_size": self.task_axis_size,
            "physical_mesh_shape": list(self.physical_mesh_shape),
            "physical_mesh_dim_names": list(self.physical_mesh_dim_names),
            "soft_mesh_shape": list(self.soft_mesh_shape),
            "soft_mesh_dim_names": list(self.soft_mesh_dim_names),
            "semantics": (
                "restricted_soft_task_axis_no_implicit_cross_task_visibility"
            ),
        }


class TaskAxisPlacement:
    """Base class for restricted task-axis placement descriptors."""

    kind: str

    def to_plan(self) -> dict[str, Any]:
        raise NotImplementedError


@dataclass(frozen=True)
class TaskShard(TaskAxisPlacement):
    """Shard independent operator work over the task axis."""

    work_domain: str
    partition_count: int | None = None
    work_axis_order: tuple[str, ...] = ()
    kind: str = "task_shard"

    def to_plan(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "work_domain": self.work_domain,
            "partition_count": self.partition_count,
            "work_axis_order": list(self.work_axis_order),
            "semantics": "task_axis_shards_independent_work_ownership",
        }

    def __repr__(self) -> str:
        if self.partition_count is None and not self.work_axis_order:
            return f"TaskShard({self.work_domain!r})"
        return (
            "TaskShard("
            f"{self.work_domain!r}, "
            f"partition_count={self.partition_count!r}, "
            f"work_axis_order={self.work_axis_order!r})"
        )


@dataclass(frozen=True)
class TaskReplicate(TaskAxisPlacement):
    """Each task independently requires equivalent input visibility."""

    input_requirement: str | None = None
    cost_accounting: str = "per_task"
    kind: str = "task_replicate"

    def to_plan(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "input_requirement": self.input_requirement,
            "cost_accounting": self.cost_accounting,
            "semantics": (
                "require_equivalent_input_visibility_not_zero_cost_sharing"
            ),
        }

    def __repr__(self) -> str:
        if self.input_requirement is None:
            return "TaskReplicate()"
        return f"TaskReplicate({self.input_requirement!r})"


@dataclass(frozen=True)
class TaskPartial(TaskAxisPlacement):
    """Unresolved cross-task partial result; not runnable until resolved."""

    reduce_op: str
    required_merge_scope: str
    kind: str = "task_partial"

    def to_plan(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "reduce_op": self.reduce_op,
            "required_merge_scope": self.required_merge_scope,
            "runnable": False,
            "semantics": "unresolved_task_partial_is_not_runnable",
        }

    def __repr__(self) -> str:
        return f"TaskPartial({self.reduce_op!r})"


@dataclass(frozen=True)
class TaskPartitionValidation:
    """Verifier-friendly task partition metadata validation report."""

    task_axis_mesh_declared: bool
    physical_mesh_matches_chip: bool
    no_unresolved_task_partial: bool
    errors: tuple[str, ...] = ()

    @property
    def ok(self) -> bool:
        return (
            self.physical_mesh_matches_chip
            and self.no_unresolved_task_partial
            and not self.errors
        )

    def to_plan(self) -> dict[str, Any]:
        return {
            "task_axis_mesh_declared": self.task_axis_mesh_declared,
            "physical_mesh_matches_chip": self.physical_mesh_matches_chip,
            "no_unresolved_task_partial": self.no_unresolved_task_partial,
            "ok": self.ok,
            "errors": list(self.errors),
        }


class TaskPartitionPlan:
    """High-level task-axis plan consumed before processor logical lowering."""

    def __init__(self, app_plan: AppPlan, chip_config: dict[str, Any]) -> None:
        self.app_plan = app_plan
        self.chip_program = app_plan.source_chip_program
        self.chip = str(chip_config.get("name", "unknown_chip"))
        fabric_config = chip_config.get("logical_fabric", {})
        if not isinstance(fabric_config, dict):
            raise ValueError("chip config logical_fabric must be a dict")
        self.chip_physical_mesh_shape = tuple(
            int(dim) for dim in fabric_config.get("shape", ())
        )
        self.chip_physical_mesh_dim_names = tuple(
            str(name) for name in fabric_config.get("dim_names", ())
        )
        mesh_payload = self.chip_program.task_axis_mesh
        self.task_axis_mesh = (
            _task_axis_mesh_from_payload(mesh_payload)
            if mesh_payload is not None
            else TaskAxisMesh(
                task_axis_size=1,
                physical_mesh_shape=self.chip_physical_mesh_shape,
                physical_mesh_dim_names=self.chip_physical_mesh_dim_names,
            )
        )
        self.task_axis_placements = dict(self.chip_program.task_axis_placements)
        self.validation = self._validate()

    @property
    def task_axis_size(self) -> int:
        return self.task_axis_mesh.task_axis_size

    def placement_for_tensor(self, logical_tensor_id: str) -> dict[str, Any] | None:
        return self.task_axis_placements.get(logical_tensor_id)

    def work_axis_order_for_tensor(
        self,
        logical_tensor_id: str,
        default: tuple[str, ...],
    ) -> tuple[str, ...]:
        placement = self.placement_for_tensor(logical_tensor_id)
        if placement is None or placement.get("kind") != "task_shard":
            return default
        raw_order = placement.get("work_axis_order") or default
        return tuple(str(axis) for axis in raw_order)

    def _validate(self) -> TaskPartitionValidation:
        errors: list[str] = []
        task_axis_mesh_declared = self.chip_program.task_axis_mesh is not None
        physical_mesh_matches_chip = (
            self.task_axis_mesh.physical_mesh_shape == self.chip_physical_mesh_shape
            and self.task_axis_mesh.physical_mesh_dim_names
            == self.chip_physical_mesh_dim_names
        )
        if not physical_mesh_matches_chip:
            errors.append(
                "task-axis physical mesh must match chip logical_fabric shape/dim_names"
            )
        no_unresolved_task_partial = all(
            placement.get("kind") != "task_partial"
            for placement in self.task_axis_placements.values()
        )
        if not no_unresolved_task_partial:
            errors.append("unresolved TaskPartial is not runnable")
        return TaskPartitionValidation(
            task_axis_mesh_declared=task_axis_mesh_declared,
            physical_mesh_matches_chip=physical_mesh_matches_chip,
            no_unresolved_task_partial=no_unresolved_task_partial,
            errors=tuple(errors),
        )

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ir": "task_partition_plan",
            "chip": self.chip,
            "source_program": self.chip_program.name,
            "implementation_stage": "metadata_only_manual_task_axis",
            "layering_policy": (
                "task_partition_plan_records_high_level_task_axis_contract;"
                "processor_logical_lowering_consumes_without_vendor_row_assignment"
            ),
            "task_axis_mesh": self.task_axis_mesh.to_plan(),
            "task_axis_placements": dict(sorted(self.task_axis_placements.items())),
            "apps": {
                f"app{app_index}": {
                    "app_id": app_index,
                    "task_axis_size": self.task_axis_mesh.task_axis_size,
                    "soft_processor_count": (
                        self.task_axis_mesh.task_axis_size
                        * _product(self.task_axis_mesh.physical_mesh_shape)
                    ),
                    "value_scope": (
                        "PELocal(app_id, task_id, physical_pe_id)"
                    ),
                }
                for app_index in range(self.app_plan.app_count)
            },
            "validation": self.validation.to_plan(),
            "totals": {
                "app_count": self.app_plan.app_count,
                "task_axis_size": self.task_axis_mesh.task_axis_size,
                "task_axis_placement_count": len(self.task_axis_placements),
            },
        }


def _task_axis_mesh_from_payload(payload: dict[str, Any]) -> TaskAxisMesh:
    return TaskAxisMesh(
        task_axis_size=int(payload["task_axis_size"]),
        physical_mesh_shape=tuple(int(dim) for dim in payload["physical_mesh_shape"]),
        physical_mesh_dim_names=tuple(
            str(name) for name in payload["physical_mesh_dim_names"]
        ),
        axis_name=str(payload.get("axis_name", "task")),
    )


def _product(values: tuple[int, ...]) -> int:
    result = 1
    for value in values:
        result *= value
    return result


__all__ = [
    "TaskAxisMesh",
    "TaskAxisPlacement",
    "TaskPartial",
    "TaskPartitionPlan",
    "TaskPartitionValidation",
    "TaskReplicate",
    "TaskShard",
]
