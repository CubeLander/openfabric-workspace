"""Processor-level logical program IR.

This layer consumes :class:`AppPlan`, instantiates each app-local op list over
the current chip processors, and materializes logical DTensors as app-scoped
processor-local views.

See ``docs/compiler/binary_packaging/research_notes/archive/app-plan-vs-runtime-image.md`` for
why compile apps remain independent here and runtime image packing is deferred
downstream.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product
from typing import Any, Sequence

from gpdpu_compiler.core.dfu3500.operand_visibility import (
    Dfu3500OperandVisibilityPolicy,
    dfu3500_operand_visibility_policy_for,
)
from gpdpu_compiler.core.placement_types import Partial, Placement, Shard
from gpdpu_compiler.core.program import ChipOp, LogicalDTensor, Shape
from gpdpu_compiler.core.program_app import AppPlan
from gpdpu_compiler.core.program_task_partition import TaskPartitionPlan


@dataclass
class ProcessorLocalValue:
    """A logical DTensor view held by one processor."""

    id: str
    logical_tensor_id: str
    logical_tensor_name: str
    processor: str
    coordinate: tuple[int, ...]
    kind: str
    global_shape: Shape
    local_shape: Shape
    global_offset: Shape
    placements: tuple[Placement, ...]
    source_sram_tensor_id: str | None = None
    producer_chip_op: str | None = None
    producer_processor_action: str | None = None

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "logical_tensor_id": self.logical_tensor_id,
            "logical_tensor_name": self.logical_tensor_name,
            "processor": self.processor,
            "coordinate": list(self.coordinate),
            "kind": self.kind,
            "global_shape": list(self.global_shape),
            "local_shape": list(self.local_shape),
            "global_offset": list(self.global_offset),
            "placements": [repr(placement) for placement in self.placements],
            "source_sram_tensor_id": self.source_sram_tensor_id,
            "producer_chip_op": self.producer_chip_op,
            "producer_processor_action": self.producer_processor_action,
        }


@dataclass(frozen=True)
class ProcessorLogicalAction:
    """One chip op projected onto one processor."""

    id: str
    processor: str
    op: str
    source_chip_op: str
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "processor": self.processor,
            "op": self.op,
            "source_chip_op": self.source_chip_op,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "attrs": self.attrs,
        }


@dataclass(frozen=True)
class LogicalRouteStep:
    """One shard-level route-program step before tile expansion."""

    id: str
    route_edge_id: str
    step_kind: str
    processor: str
    produces_endpoint: str
    position: int
    src_processor: str | None = None
    dst_processor: str | None = None
    depends_on: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "route_edge_id": self.route_edge_id,
            "step_kind": self.step_kind,
            "processor": self.processor,
            "produces_endpoint": self.produces_endpoint,
            "position": self.position,
            "src_processor": self.src_processor,
            "dst_processor": self.dst_processor,
            "depends_on": list(self.depends_on),
            "attrs": self.attrs,
        }


@dataclass(frozen=True)
class LogicalRouteEdge:
    """A shard-level logical visibility route program.

    This is the "large arrow" before tile lowering expands it into many tile
    route-prefix dependencies. It is already structured as route steps so tile
    lowering can directly map each logical step into tile route actions.
    """

    id: str
    source_chip_op: str
    consumer_chip_op: str
    operand_index: int
    operand_role: str
    logical_tensor_id: str
    logical_tensor_name: str
    route_kind: str
    visibility_kind: str
    fabric_scope: str
    group_key: str
    participants: tuple[str, ...]
    source_policy: str
    dependency_policy: str
    source_shard: dict[str, Any]
    route_steps: tuple[LogicalRouteStep, ...] = ()
    endpoint_by_processor: dict[str, str] = field(default_factory=dict)
    producer_action_ids: tuple[str, ...] = ()
    consumer_action_ids: tuple[str, ...] = ()
    consumer_value_ids: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_chip_op": self.source_chip_op,
            "consumer_chip_op": self.consumer_chip_op,
            "operand_index": self.operand_index,
            "operand_role": self.operand_role,
            "logical_tensor_id": self.logical_tensor_id,
            "logical_tensor_name": self.logical_tensor_name,
            "route_kind": self.route_kind,
            "visibility_kind": self.visibility_kind,
            "fabric_scope": self.fabric_scope,
            "group_key": self.group_key,
            "participants": list(self.participants),
            "source_policy": self.source_policy,
            "dependency_policy": self.dependency_policy,
            "source_shard": self.source_shard,
            "route_steps": [step.to_plan() for step in self.route_steps],
            "endpoint_by_processor": dict(sorted(self.endpoint_by_processor.items())),
            "producer_action_ids": list(self.producer_action_ids),
            "consumer_action_ids": list(self.consumer_action_ids),
            "consumer_value_ids": list(self.consumer_value_ids),
            "attrs": self.attrs,
        }


@dataclass(frozen=True)
class LogicalReduceEdge:
    """A shard-level logical collective reduction.

    This is intentionally separate from LogicalRouteEdge.  Route moves values;
    reduce combines many processor-local values into a value with explicit
    visibility semantics.
    """

    id: str
    source_chip_op: str
    reduce_op: str
    identity_value: str
    input_logical_tensor_id: str
    output_logical_tensor_id: str
    input_logical_tensor_name: str
    output_logical_tensor_name: str
    participants: tuple[str, ...]
    input_value_ids: tuple[str, ...]
    output_value_ids: tuple[str, ...]
    producer_action_ids: tuple[str, ...]
    source_policy: str
    visibility_kind: str
    dependency_policy: str
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_chip_op": self.source_chip_op,
            "reduce_op": self.reduce_op,
            "identity_value": self.identity_value,
            "input_logical_tensor_id": self.input_logical_tensor_id,
            "output_logical_tensor_id": self.output_logical_tensor_id,
            "input_logical_tensor_name": self.input_logical_tensor_name,
            "output_logical_tensor_name": self.output_logical_tensor_name,
            "participants": list(self.participants),
            "input_value_ids": list(self.input_value_ids),
            "output_value_ids": list(self.output_value_ids),
            "producer_action_ids": list(self.producer_action_ids),
            "source_policy": self.source_policy,
            "visibility_kind": self.visibility_kind,
            "dependency_policy": self.dependency_policy,
            "attrs": self.attrs,
        }


@dataclass(frozen=True)
class LogicalDependency:
    """A shard-level dependency edge in the processor logical plan."""

    id: str
    dependency_kind: str
    src: str
    dst: str
    route_edge_id: str | None = None
    scope: str = "processor_logical"
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "dependency_kind": self.dependency_kind,
            "src": self.src,
            "dst": self.dst,
            "route_edge_id": self.route_edge_id,
            "scope": self.scope,
            "attrs": self.attrs,
        }


@dataclass
class LogicalStream:
    """The logical action stream for one soft processor."""

    processor: str
    coord: tuple[int, ...]
    axis_names: tuple[str, ...]
    physical_processor: str | None = None
    vendor_processor_id: str | None = None
    actions: list[ProcessorLogicalAction] = field(default_factory=list)

    @property
    def task_id(self) -> int:
        return int(self.coord[0])

    @property
    def coordinate(self) -> tuple[int, ...]:
        return tuple(int(value) for value in self.coord[1:])

    def to_plan(self) -> dict[str, Any]:
        return {
            "processor": self.processor,
            "coord": list(self.coord),
            "axis_names": list(self.axis_names),
            "coordinate": list(self.coordinate),
            "task_id": self.task_id,
            "physical_processor": self.physical_processor or self.processor,
            "vendor_processor_id": self.vendor_processor_id,
            "actions": [action.to_plan() for action in self.actions],
        }


class LogicalApp:
    def __init__(
        self,
        *,
        app_id: int,
        app_ops: tuple[ChipOp, ...],
        app_plan: AppPlan,
        id_counters: dict[str, int],
        chip: str,
        source_program: str,
        fabric: str,
        processor_shape: tuple[int, ...],
        task_axis_size: int,
        soft_mesh: dict[str, dict[str, Any]],
    ) -> None:
        self.app_id = app_id
        self.app_name = f"app{app_id}"
        self.task_axis_size = int(task_axis_size)
        self.app_plan = app_plan
        self.chip_program = app_plan.source_chip_program
        self._id_counters = id_counters
        self.chip = chip
        self.source_program = source_program
        self.fabric = fabric
        self.processor_shape = processor_shape
        self.soft_mesh = soft_mesh
        self.streams: dict[str, LogicalStream] = {
            stream_id: LogicalStream(
                processor=stream_id,
                coord=tuple(int(value) for value in row["coord"]),
                axis_names=tuple(str(value) for value in row["axis_names"]),
                physical_processor=str(row["physical_processor"]),
                vendor_processor_id=(
                    str(row["vendor_processor_id"])
                    if row.get("vendor_processor_id") is not None
                    else None
                ),
            )
            for stream_id, row in sorted(self.soft_mesh.items())
        }
        self.local_values: dict[str, ProcessorLocalValue] = {}
        self.logical_routes: dict[str, LogicalRouteEdge] = {}
        self.logical_reduces: dict[str, LogicalReduceEdge] = {}
        self.logical_dependencies: dict[str, LogicalDependency] = {}
        self.output_bindings = dict(self.chip_program.outputs)

        if self.chip_program.execution_model != "spmd":
            raise NotImplementedError("processor lowering currently supports SPMD only")

        for chip_op in app_ops:
            if chip_op.op == "declare_sram_tensor":
                continue
            if chip_op.op == "load_sram_tensor":
                self._lower_load(chip_op)
            elif chip_op.op == "store_sram_tensor":
                self._lower_store(chip_op)
            elif chip_op.op == "app_materialize_store":
                self._lower_app_materialize_store(chip_op)
            elif chip_op.op == "app_materialize_load":
                self._lower_app_materialize_load(chip_op)
            else:
                self._lower_compute(chip_op)

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ir": "logical_app",
            "app_id": self.app_id,
            "app_name": self.app_name,
            "chip": self.chip,
            "source_program": self.source_program,
            "fabric": self.fabric,
            "processor_shape": list(self.processor_shape),
            "soft_processor_mesh": {
                "axis_order": list(next(iter(self.soft_mesh.values()))["axis_names"])
                if self.soft_mesh
                else ["task"],
                "task_axis_size": self.task_axis_size,
                "physical_processor_shape": list(self.processor_shape),
                "value_scope": "PELocal(app_id, task_id, physical_pe_id)",
                "implementation_stage": "soft_processor_streams",
            },
            "soft_processors": self._soft_processors_to_plan(),
            "layering_policy": (
                "logical_app_is_lowered_from_app_plan_ops;"
                "local_values_reference_logical_dtensors;"
                "local_values_are_app_scoped;"
                "tile_lowering_follows_logical_streams;"
                "app_local_state_is_not_shared_with_other_apps;"
                "dfu_lowering_not_started"
            ),
            "streams": {
                processor: stream.to_plan()
                for processor, stream in sorted(self.streams.items())
            },
            "local_values": {
                value_id: value.to_plan()
                for value_id, value in sorted(self.local_values.items())
            },
            "logical_routes": {
                route_id: route.to_plan()
                for route_id, route in sorted(self.logical_routes.items())
            },
            "logical_reduces": {
                reduce_id: reduce_edge.to_plan()
                for reduce_id, reduce_edge in sorted(self.logical_reduces.items())
            },
            "logical_dependencies": {
                dependency_id: dependency.to_plan()
                for dependency_id, dependency in sorted(self.logical_dependencies.items())
            },
            "output_bindings": dict(sorted(self.output_bindings.items())),
            "totals": {
                "processor_count": len(self.streams),
                "local_value_count": len(self.local_values),
                "action_count": sum(len(stream.actions) for stream in self.streams.values()),
                "logical_route_count": len(self.logical_routes),
                "logical_route_step_count": sum(
                    len(route.route_steps) for route in self.logical_routes.values()
                ),
                "logical_reduce_count": len(self.logical_reduces),
                "logical_dependency_count": len(self.logical_dependencies),
                "output_count": len(self.output_bindings),
            },
        }

    def _soft_processors_to_plan(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for soft_processor_id, stream in sorted(self.streams.items()):
            result[soft_processor_id] = {
                "soft_processor_id": soft_processor_id,
                "app_id": self.app_id,
                "coord": list(stream.coord),
                "axis_names": list(stream.axis_names),
                "task_id": stream.task_id,
                "physical_processor": stream.physical_processor or stream.processor,
                "physical_coordinate": list(stream.coordinate),
                "vendor_processor_id": stream.vendor_processor_id,
                "value_scope": "PELocal(app_id, task_id, physical_pe_id)",
                "stream_status": "logical_stream",
            }
        return result


    def _lower_load(self, chip_op: ChipOp) -> None:
        if len(chip_op.inputs) != 1 or len(chip_op.outputs) != 1:
            raise ValueError(f"{chip_op.id} load_sram_tensor expects one input and one output")
        tensor = self._dtensor(chip_op.outputs[0])
        sram_tensor_id = chip_op.inputs[0]
        for program in self._programs():
            action_id = self._new_action_id()
            output = self._ensure_local_value(
                tensor,
                program,
                kind="loaded_local",
                producer_chip_op=chip_op.id,
                producer_processor_action=action_id,
                source_sram_tensor_id=sram_tensor_id,
            )
            program.actions.append(
                ProcessorLogicalAction(
                    id=action_id,
                    processor=program.processor,
                    op="load_sram_tensor",
                    source_chip_op=chip_op.id,
                    outputs=(output.id,),
                    attrs={
                        "source_sram_tensor_id": sram_tensor_id,
                        "src_region": chip_op.attrs.get("src_region"),
                        "app_id": self.app_id,
                    },
                )
            )

    def _lower_store(self, chip_op: ChipOp) -> None:
        if len(chip_op.inputs) != 1 or len(chip_op.outputs) != 1:
            raise ValueError(f"{chip_op.id} store_sram_tensor expects one input and one output")
        tensor = self._dtensor(chip_op.inputs[0])
        dst_sram_tensor_id = chip_op.outputs[0]
        for program in self._programs():
            input_value = self._ensure_local_value(tensor, program)
            action_id = self._new_action_id()
            program.actions.append(
                ProcessorLogicalAction(
                    id=action_id,
                    processor=program.processor,
                    op="store_sram_tensor",
                    source_chip_op=chip_op.id,
                    inputs=(input_value.id,),
                    attrs={
                        "dst_sram_tensor_id": dst_sram_tensor_id,
                        "dst_region": chip_op.attrs.get("dst_region"),
                        "app_id": self.app_id,
                    },
                )
            )

    def _lower_app_materialize_store(self, chip_op: ChipOp) -> None:
        if len(chip_op.inputs) != 1:
            raise ValueError(f"{chip_op.id} app_materialize_store expects one input")
        tensor = self._dtensor(chip_op.inputs[0])
        storage_id = str(chip_op.attrs.get("storage_id", chip_op.outputs[0] if chip_op.outputs else ""))
        for program in self._programs():
            input_value = self._ensure_local_value(tensor, program)
            action_id = self._new_action_id()
            program.actions.append(
                ProcessorLogicalAction(
                    id=action_id,
                    processor=program.processor,
                    op="app_materialize_store",
                    source_chip_op=chip_op.id,
                    inputs=(input_value.id,),
                    outputs=(storage_id,),
                    attrs={
                        **dict(chip_op.attrs),
                        "storage_id": storage_id,
                        "app_id": self.app_id,
                        "semantic_kind": "app_boundary_materialize_store",
                    },
                )
            )

    def _lower_app_materialize_load(self, chip_op: ChipOp) -> None:
        if len(chip_op.outputs) != 1:
            raise ValueError(f"{chip_op.id} app_materialize_load expects one output")
        tensor = self._dtensor(chip_op.outputs[0])
        storage_id = str(chip_op.attrs.get("storage_id", chip_op.inputs[0] if chip_op.inputs else ""))
        for program in self._programs():
            action_id = self._new_action_id()
            output = self._ensure_local_value(
                tensor,
                program,
                kind="materialized_app_value",
                producer_chip_op=chip_op.id,
                producer_processor_action=action_id,
                source_sram_tensor_id=storage_id,
            )
            program.actions.append(
                ProcessorLogicalAction(
                    id=action_id,
                    processor=program.processor,
                    op="app_materialize_load",
                    source_chip_op=chip_op.id,
                    inputs=(storage_id,),
                    outputs=(output.id,),
                    attrs={
                        **dict(chip_op.attrs),
                        "storage_id": storage_id,
                        "app_id": self.app_id,
                        "semantic_kind": "app_boundary_materialize_load",
                    },
                )
            )

    def _lower_compute(self, chip_op: ChipOp) -> None:
        input_tensors = [self._dtensor(tensor_id) for tensor_id in chip_op.inputs]
        output_tensors = [self._dtensor(tensor_id) for tensor_id in chip_op.outputs]
        lowered_actions: list[tuple[LogicalStream, ProcessorLogicalAction, tuple[ProcessorLocalValue, ...]]] = []
        for program in self._programs():
            action_id = self._new_action_id()
            input_values = [
                self._ensure_local_value(tensor, program)
                for tensor in input_tensors
            ]
            output_values = [
                self._ensure_local_value(
                    tensor,
                    program,
                    kind="computed_local",
                    producer_chip_op=chip_op.id,
                    producer_processor_action=action_id,
                )
                for tensor in output_tensors
            ]
            action = ProcessorLogicalAction(
                id=action_id,
                processor=program.processor,
                op=chip_op.op,
                source_chip_op=chip_op.id,
                inputs=tuple(value.id for value in input_values),
                outputs=tuple(value.id for value in output_values),
                attrs={**dict(chip_op.attrs), "app_id": self.app_id},
            )
            program.actions.append(action)
            lowered_actions.append((program, action, tuple(input_values)))
        route_policy = dfu3500_operand_visibility_policy_for(
            lowering_hint=str(chip_op.attrs.get("lowering_hint", "")),
            operand_count=len(chip_op.inputs),
        )
        if route_policy is not None:
            self._add_operand_visibility_routes(chip_op, lowered_actions, route_policy)
        if chip_op.op == "reduce_max":
            self._add_logical_reduce(chip_op, lowered_actions)

    def _add_logical_reduce(
        self,
        chip_op: ChipOp,
        lowered_actions: Sequence[
            tuple[LogicalStream, ProcessorLogicalAction, tuple[ProcessorLocalValue, ...]]
        ],
    ) -> None:
        if len(chip_op.inputs) != 1 or len(chip_op.outputs) != 1:
            return
        input_tensor = self._dtensor(chip_op.inputs[0])
        output_tensor = self._dtensor(chip_op.outputs[0])
        records = list(lowered_actions)
        participants = tuple(record[0].processor for record in records)
        input_values = tuple(record[2][0] for record in records)
        output_value_ids = tuple(record[1].outputs[0] for record in records)
        action_ids = tuple(record[1].id for record in records)
        reduce_id = self._new_reduce_id()
        reduce_edge = LogicalReduceEdge(
            id=reduce_id,
            source_chip_op=chip_op.id,
            reduce_op="max",
            identity_value="-inf",
            input_logical_tensor_id=input_tensor.id,
            output_logical_tensor_id=output_tensor.id,
            input_logical_tensor_name=input_tensor.name,
            output_logical_tensor_name=output_tensor.name,
            participants=participants,
            input_value_ids=tuple(value.id for value in input_values),
            output_value_ids=output_value_ids,
            producer_action_ids=action_ids,
            source_policy="all_processors_contribute",
            visibility_kind="replicated_scalar",
            dependency_policy=(
                "local_reduce_before_collective;"
                "collective_before_same_app_consumers;"
                "cross_app_consumers_must_use_app_storage"
            ),
            attrs={
                "axes": chip_op.attrs.get("axes"),
                "semantic_kind": "logical_all_reduce_max",
                "implementation_status": "symbolic_collective_not_physical_route",
            },
        )
        self.logical_reduces[reduce_edge.id] = reduce_edge
        for input_value, action_id, output_value_id in zip(
            input_values,
            action_ids,
            output_value_ids,
            strict=True,
        ):
            self._add_dependency(
                dependency_kind="local_value_before_logical_reduce",
                src=input_value.id,
                dst=action_id,
                attrs={
                    "logical_reduce_edge_id": reduce_edge.id,
                    "processor": input_value.processor,
                    "value_id": input_value.id,
                },
            )
            self._add_dependency(
                dependency_kind="logical_reduce_result_visible",
                src=action_id,
                dst=output_value_id,
                attrs={
                    "logical_reduce_edge_id": reduce_edge.id,
                    "processor": input_value.processor,
                    "visibility_kind": reduce_edge.visibility_kind,
                },
            )

    def _add_operand_visibility_routes(
        self,
        chip_op: ChipOp,
        lowered_actions: Sequence[
            tuple[LogicalStream, ProcessorLogicalAction, tuple[ProcessorLocalValue, ...]]
        ],
        route_policy: Dfu3500OperandVisibilityPolicy,
    ) -> None:
        if not route_policy.operand_routes:
            return
        if len(self.processor_shape) != 2:
            raise NotImplementedError(
                "DFU3500 operand visibility route lowering expects a 2-D processor grid"
            )

        route_specs = route_policy.operand_routes
        records = list(lowered_actions)
        for spec in route_specs:
            operand_index = spec.operand_index
            if operand_index >= len(chip_op.inputs):
                raise ValueError(
                    f"operand visibility route references operand {operand_index}, "
                    f"but {chip_op.id} has only {len(chip_op.inputs)} inputs"
                )
            tensor = self._dtensor(chip_op.inputs[operand_index])
            group_dim = spec.group_dim
            task_ids = sorted({record[0].task_id for record in records})
            for task_id in task_ids:
                for group_index in range(self.processor_shape[group_dim]):
                    group_records = [
                        record
                        for record in records
                        if record[0].coordinate[group_dim] == group_index
                        and record[0].task_id == task_id
                    ]
                    if not group_records:
                        continue
                    self._add_operand_visibility_route_group(
                        chip_op=chip_op,
                        tensor=tensor,
                        spec=spec,
                        task_id=task_id,
                        group_index=group_index,
                        group_records=group_records,
                    )

    def _add_operand_visibility_route_group(
        self,
        *,
        chip_op: ChipOp,
        tensor: LogicalDTensor,
        spec: Any,
        task_id: int,
        group_index: int,
        group_records: list[
            tuple[LogicalStream, ProcessorLogicalAction, tuple[ProcessorLocalValue, ...]]
        ],
    ) -> None:
        if not group_records:
            return
        operand_index = spec.operand_index
        participants = tuple(record[0].processor for record in group_records)
        input_values = tuple(record[2][operand_index] for record in group_records)
        consumer_action_by_processor = {
            record[0].processor: record[1].id
            for record in group_records
        }
        consumer_actions = tuple(
            consumer_action_by_processor[processor]
            for processor in participants
        )
        route_id = self._new_route_id()
        group_key = _task_scoped_group_key(
            task_axis_size=self.task_axis_size,
            task_id=task_id,
            fabric_scope=spec.fabric_scope,
            group_index=group_index,
        )
        source_shard_ref = (
            f"logical_shard:{_sanitize_id_part(tensor.id)}:"
            f"{group_key}"
        )
        source_shard = {
            "ref": source_shard_ref,
            "logical_tensor_id": tensor.id,
            "logical_tensor_name": tensor.name,
            "placements": [repr(placement) for placement in tensor.placements],
            "fabric_scope": spec.fabric_scope,
            "task_id": task_id,
            "group_index": group_index,
            "participant_value_ids": [value.id for value in input_values],
            "global_offsets": [list(value.global_offset) for value in input_values],
            "local_shapes": [list(value.local_shape) for value in input_values],
        }
        source_processor = participants[0]
        route_steps_list: list[LogicalRouteStep] = []
        endpoint_by_processor: dict[str, str] = {}
        source_step_id = _logical_route_step_id(
            route_id, "local", source_processor, 0
        )
        source_endpoint = _logical_visibility_endpoint_id(
            route_id, source_processor
        )
        route_steps_list.append(
            LogicalRouteStep(
                id=source_step_id,
                route_edge_id=route_id,
                step_kind="source_local_visibility",
                processor=source_processor,
                produces_endpoint=source_endpoint,
                position=0,
                src_processor=source_processor,
                dst_processor=source_processor,
                depends_on=(source_shard_ref,),
                attrs={
                    "route_kind": spec.route_kind,
                    "visibility_kind": spec.visibility_kind,
                    "edge": f"{source_processor}->{source_processor}",
                    "task_id": task_id,
                },
            )
        )
        endpoint_by_processor[source_processor] = source_step_id

        source_index = participants.index(source_processor)
        fanout_edges: list[dict[str, str]] = []
        previous_processor = source_processor
        for participant_index in range(source_index - 1, -1, -1):
            current_processor = participants[participant_index]
            fanout_edges.append({"from": previous_processor, "to": current_processor})
            previous_processor = current_processor
        previous_processor = source_processor
        for participant_index in range(source_index + 1, len(participants)):
            current_processor = participants[participant_index]
            fanout_edges.append({"from": previous_processor, "to": current_processor})
            previous_processor = current_processor

        previous_step = source_step_id
        for edge_index, edge in enumerate(fanout_edges, start=1):
            src = str(edge["from"])
            dst = str(edge["to"])
            step_id = _logical_route_step_id(route_id, "hop", dst, edge_index)
            endpoint = _logical_visibility_endpoint_id(route_id, dst)
            route_steps_list.append(
                LogicalRouteStep(
                    id=step_id,
                    route_edge_id=route_id,
                    step_kind="route_hop_visibility",
                    processor=dst,
                    produces_endpoint=endpoint,
                    position=edge_index,
                    src_processor=src,
                    dst_processor=dst,
                    depends_on=(previous_step,),
                    attrs={
                        "route_kind": spec.route_kind,
                        "visibility_kind": spec.visibility_kind,
                        "edge": f"{src}->{dst}",
                        "task_id": task_id,
                    },
                )
            )
            endpoint_by_processor[dst] = step_id
            previous_step = step_id

        route_steps = tuple(route_steps_list)
        route_policy_name = (
            "logical_route_is_task_local_path_propagation_program"
            if self.task_axis_size > 1
            else "logical_route_is_already_a_path_propagation_program"
        )
        route = LogicalRouteEdge(
            id=route_id,
            source_chip_op=input_values[0].producer_chip_op or "-",
            consumer_chip_op=chip_op.id,
            operand_index=operand_index,
            operand_role=spec.operand_role,
            logical_tensor_id=tensor.id,
            logical_tensor_name=tensor.name,
            route_kind=spec.route_kind,
            visibility_kind=spec.visibility_kind,
            fabric_scope=spec.fabric_scope,
            group_key=group_key,
            participants=participants,
            source_policy="stable_anchor_first_participant",
            dependency_policy=(
                f"{route_policy_name};"
                "tile_lowering_expands_each_logical_route_step_to_tile_route_actions;"
                "source_endpoint_depends_on_source_shard;"
                "first_route_hop_depends_on_source_endpoint;"
                "each_later_hop_depends_on_previous_hop;"
                "compute_depends_on_local_visibility_endpoint;"
                "no_extra_tail_to_root_dependency"
            ),
            source_shard=source_shard,
            route_steps=route_steps,
            endpoint_by_processor=endpoint_by_processor,
            producer_action_ids=tuple(
                value.producer_processor_action or "-"
                for value in input_values
            ),
            consumer_action_ids=consumer_actions,
            consumer_value_ids=tuple(value.id for value in input_values),
            attrs={
                "source_chip_op": input_values[0].producer_chip_op,
                "consumer_chip_op": chip_op.id,
                "lowering_hint": chip_op.attrs.get("lowering_hint"),
                "axis_name": spec.axis_name,
                "task_id": task_id,
                "source_processor": source_processor,
                "tile_dependency_shape": {
                    "route_action_dependencies": "expand_logical_route_steps",
                    "source_dependency": "source_tile_available_before_source_endpoint",
                    "hop_dependency": "dst_hop_depends_on_previous_route_hop",
                    "compute_dependency": "compute_depends_on_local_visibility_endpoint",
                    "forbidden_dependency": "route_tail_must_not_also_depend_on_route_root",
                },
            },
        )
        self.logical_routes[route.id] = route
        for step in route_steps:
            for parent in step.depends_on:
                self._add_dependency(
                    dependency_kind="logical_route_step_dependency",
                    src=parent,
                    dst=step.id,
                    route_edge_id=route.id,
                    attrs={
                        "logical_tensor_id": tensor.id,
                        "operand_role": spec.operand_role,
                        "group_key": group_key,
                        "step_kind": step.step_kind,
                        "processor": step.processor,
                        "produces_endpoint": step.produces_endpoint,
                        "task_id": task_id,
                    },
                )
        for processor in participants:
            endpoint = endpoint_by_processor[processor]
            consumer_action = consumer_action_by_processor[processor]
            self._add_dependency(
                dependency_kind="logical_visibility_endpoint_before_compute",
                src=endpoint,
                dst=consumer_action,
                route_edge_id=route.id,
                attrs={
                    "logical_tensor_id": tensor.id,
                    "operand_role": spec.operand_role,
                    "group_key": group_key,
                    "processor": processor,
                    "task_id": task_id,
                },
            )

    def _ensure_local_value(
        self,
        tensor: LogicalDTensor,
        program: LogicalStream,
        *,
        kind: str | None = None,
        producer_chip_op: str | None = None,
        producer_processor_action: str | None = None,
        source_sram_tensor_id: str | None = None,
    ) -> ProcessorLocalValue:
        value_id = (
            f"plv_app{self.app_id}_{_sanitize_id_part(tensor.id)}_"
            f"{_sanitize_id_part(program.processor)}"
        )
        if value_id in self.local_values:
            value = self.local_values[value_id]
            if producer_chip_op is not None and value.producer_chip_op is None:
                value.producer_chip_op = producer_chip_op
            if producer_processor_action is not None and value.producer_processor_action is None:
                value.producer_processor_action = producer_processor_action
            if source_sram_tensor_id is not None and value.source_sram_tensor_id is None:
                value.source_sram_tensor_id = source_sram_tensor_id
            return value

        local_shape, global_offset = compute_local_shape_and_offset(
            tensor.shape,
            self.processor_shape,
            program.coordinate,
            tensor.placements,
        )
        value = ProcessorLocalValue(
            id=value_id,
            logical_tensor_id=tensor.id,
            logical_tensor_name=tensor.name,
            processor=program.processor,
            coordinate=program.coordinate,
            kind=kind
            or ("loaded_local" if tensor.source_sram is not None else "computed_local"),
            global_shape=tensor.shape,
            local_shape=local_shape,
            global_offset=global_offset,
            placements=tensor.placements,
            source_sram_tensor_id=source_sram_tensor_id or tensor.source_sram,
            producer_chip_op=producer_chip_op or tensor.producer_op,
            producer_processor_action=producer_processor_action,
        )
        self.local_values[value.id] = value
        return value

    def _dtensor(self, tensor_id: str) -> LogicalDTensor:
        try:
            return self.chip_program.dtensors[tensor_id]
        except KeyError as exc:
            raise ValueError(f"unknown logical DTensor id in chip op: {tensor_id}") from exc

    def _programs(self) -> list[LogicalStream]:
        return [self.streams[key] for key in sorted(self.streams)]

    def _new_action_id(self) -> str:
        action_id = f"processor_action_{self._id_counters['action']:04d}"
        self._id_counters["action"] += 1
        return action_id

    def _new_route_id(self) -> str:
        route_id = f"logical_route_{self._id_counters['route']:04d}"
        self._id_counters["route"] += 1
        return route_id

    def _new_reduce_id(self) -> str:
        reduce_id = f"logical_reduce_{self._id_counters['reduce']:04d}"
        self._id_counters["reduce"] += 1
        return reduce_id

    def _new_dependency_id(self) -> str:
        dependency_id = f"logical_dep_{self._id_counters['dependency']:04d}"
        self._id_counters["dependency"] += 1
        return dependency_id

    def _add_dependency(
        self,
        *,
        dependency_kind: str,
        src: str,
        dst: str,
        route_edge_id: str | None = None,
        attrs: dict[str, Any] | None = None,
    ) -> None:
        dependency = LogicalDependency(
            id=self._new_dependency_id(),
            dependency_kind=dependency_kind,
            src=src,
            dst=dst,
            route_edge_id=route_edge_id,
            attrs=attrs or {},
        )
        self.logical_dependencies[dependency.id] = dependency


class LogicalPlan:
    """Whole-program processor logical IR grouped by compile-time app."""

    def __init__(
        self,
        app_plan: AppPlan,
        chip_config: dict[str, Any],
        *,
        task_partition_plan: TaskPartitionPlan | None = None,
    ) -> None:
        self.app_plan = app_plan
        self.chip_program = app_plan.source_chip_program
        self.chip_config = chip_config
        self.chip = str(chip_config.get("name", "unknown_chip"))
        self.source_program = self.chip_program.name
        self.task_partition_plan = (
            task_partition_plan
            if task_partition_plan is not None
            else TaskPartitionPlan(app_plan, chip_config)
        )
        self.task_axis_mesh = self.task_partition_plan.task_axis_mesh
        self.output_bindings = dict(self.chip_program.outputs)
        self.soft_mesh: dict[str, dict[str, Any]] = {}
        axis_names = _soft_axis_names(self.task_axis_mesh.physical_mesh_shape)
        coordinates = [
            tuple(coord)
            for coord in product(
                *(range(int(dim)) for dim in self.task_axis_mesh.physical_mesh_shape)
            )
        ]
        for coordinate in coordinates:
            physical_processor = _processor_id_from_coord(coordinate)
            vendor_processor_id = _vendor_pe_id_from_coord(coordinate)
            for task_id in range(self.task_axis_mesh.task_axis_size):
                soft_processor = (
                    _soft_processor_id(task_id, physical_processor)
                    if self.task_axis_mesh.task_axis_size > 1
                    else physical_processor
                )
                self.soft_mesh[soft_processor] = {
                    "soft_processor_id": soft_processor,
                    "coord": (int(task_id), *tuple(int(value) for value in coordinate)),
                    "axis_names": axis_names,
                    "task_id": int(task_id),
                    "physical_processor": physical_processor,
                    "physical_coordinate": tuple(int(value) for value in coordinate),
                    "vendor_processor_id": vendor_processor_id,
                }

        id_counters = {
            "action": 0,
            "route": 0,
            "reduce": 0,
            "dependency": 0,
        }
        self.apps = tuple(
            LogicalApp(
                app_id=app_id,
                app_ops=app_ops,
                app_plan=app_plan,
                id_counters=id_counters,
                chip=self.chip,
                source_program=self.source_program,
                fabric="soft_mesh",
                processor_shape=self.task_axis_mesh.physical_mesh_shape,
                task_axis_size=self.task_axis_mesh.task_axis_size,
                soft_mesh=self.soft_mesh,
            )
            for app_id, app_ops in enumerate(app_plan.apps)
        )

    @property
    def streams(self) -> dict[str, LogicalStream]:
        streams: dict[str, LogicalStream] = {}
        for app_program in self.apps:
            for processor, app_stream in sorted(app_program.streams.items()):
                if processor not in streams:
                    streams[processor] = LogicalStream(
                        processor=app_stream.processor,
                        coord=app_stream.coord,
                        axis_names=app_stream.axis_names,
                        physical_processor=app_stream.physical_processor,
                        vendor_processor_id=app_stream.vendor_processor_id,
                    )
                streams[processor].actions.extend(app_stream.actions)
        return streams

    @property
    def programs(self) -> dict[str, LogicalStream]:
        return self.streams

    @property
    def local_values(self) -> dict[str, ProcessorLocalValue]:
        values: dict[str, ProcessorLocalValue] = {}
        for app_program in self.apps:
            values.update(app_program.local_values)
        return values

    @property
    def logical_routes(self) -> dict[str, LogicalRouteEdge]:
        routes: dict[str, LogicalRouteEdge] = {}
        for app_program in self.apps:
            routes.update(app_program.logical_routes)
        return routes

    @property
    def logical_reduces(self) -> dict[str, LogicalReduceEdge]:
        reduces: dict[str, LogicalReduceEdge] = {}
        for app_program in self.apps:
            reduces.update(app_program.logical_reduces)
        return reduces

    @property
    def logical_dependencies(self) -> dict[str, LogicalDependency]:
        dependencies: dict[str, LogicalDependency] = {}
        for app_program in self.apps:
            dependencies.update(app_program.logical_dependencies)
        return dependencies

    def to_plan(self) -> dict[str, Any]:
        streams = self.streams
        local_values = self.local_values
        logical_routes = self.logical_routes
        logical_reduces = self.logical_reduces
        logical_dependencies = self.logical_dependencies
        soft_mesh_plan = {
            stream_id: {
                "soft_processor_id": stream_id,
                "coord": list(row["coord"]),
                "axis_names": list(row["axis_names"]),
                "task_id": row["task_id"],
                "physical_processor": row["physical_processor"],
                "physical_coordinate": list(row["physical_coordinate"]),
                "vendor_processor_id": row["vendor_processor_id"],
                "value_scope": "PELocal(app_id, task_id, physical_pe_id)",
            }
            for stream_id, row in sorted(self.soft_mesh.items())
        }
        return {
            "schema_version": 2,
            "ir": "logical_plan",
            "chip": self.chip,
            "source_program": self.source_program,
            "fabric": "soft_mesh",
            "processor_shape": list(self.task_axis_mesh.physical_mesh_shape),
            "soft_processor_mesh": {
                "axis_order": list(_soft_axis_names(self.task_axis_mesh.physical_mesh_shape)),
                "task_axis_size": self.task_axis_mesh.task_axis_size,
                "physical_processor_shape": list(
                    self.task_axis_mesh.physical_mesh_shape
                ),
                "value_scope": "PELocal(app_id, task_id, physical_pe_id)",
                "implementation_stage": "logical_plan_owned_soft_mesh",
            },
            "soft_mesh": soft_mesh_plan,
            "layering_policy": (
                "logical_plan_owns_soft_mesh;"
                "logical_apps_consume_soft_mesh;"
                "source_of_truth_is_apps;"
                "aggregate_programs_key_is_compatibility_view;"
                "runtime_image_packing_is_downstream;"
                "dfu_lowering_not_started"
            ),
            "apps": {
                app_program.app_name: app_program.to_plan()
                for app_program in self.apps
            },
            "task_partition_plan": (
                self.task_partition_plan.to_plan()
                if self.task_partition_plan is not None
                else None
            ),
            "streams": {
                processor: stream.to_plan()
                for processor, stream in sorted(streams.items())
            },
            "programs": {
                processor: stream.to_plan()
                for processor, stream in sorted(streams.items())
            },
            "local_values": {
                value_id: value.to_plan()
                for value_id, value in sorted(local_values.items())
            },
            "logical_routes": {
                route_id: route.to_plan()
                for route_id, route in sorted(logical_routes.items())
            },
            "logical_reduces": {
                reduce_id: reduce_edge.to_plan()
                for reduce_id, reduce_edge in sorted(logical_reduces.items())
            },
            "logical_dependencies": {
                dependency_id: dependency.to_plan()
                for dependency_id, dependency in sorted(logical_dependencies.items())
            },
            "output_bindings": dict(sorted(self.output_bindings.items())),
            "totals": {
                "app_count": len(self.apps),
                "processor_count": len(streams),
                "local_value_count": len(local_values),
                "action_count": sum(len(stream.actions) for stream in streams.values()),
                "logical_route_count": len(logical_routes),
                "logical_route_step_count": sum(
                    len(route.route_steps) for route in logical_routes.values()
                ),
                "logical_reduce_count": len(logical_reduces),
                "logical_dependency_count": len(logical_dependencies),
                "output_count": len(self.output_bindings),
            },
        }


def compute_local_shape_and_offset(
    global_shape: Sequence[int],
    processor_shape: Sequence[int],
    coordinate: Sequence[int],
    placements: Sequence[Placement],
) -> tuple[Shape, Shape]:
    local_shape = [int(dim) for dim in global_shape]
    global_offset = [0 for _ in local_shape]

    for processor_dim, placement in enumerate(placements):
        if isinstance(placement, Shard):
            shard_dim = placement.dim
            shard_size, shard_offset = _split_dim(
                local_shape[shard_dim],
                int(processor_shape[processor_dim]),
                int(coordinate[processor_dim]),
            )
            local_shape[shard_dim] = shard_size
            global_offset[shard_dim] += shard_offset
        elif isinstance(placement, Partial):
            continue

    return tuple(local_shape), tuple(global_offset)


def _logical_route_step_id(route_id: str, step_kind: str, processor: str, position: int) -> str:
    return f"{route_id}:step:{step_kind}:{position}:{_sanitize_id_part(processor)}"


def _logical_visibility_endpoint_id(route_id: str, processor: str) -> str:
    return f"{route_id}:endpoint:{_sanitize_id_part(processor)}"


def _sanitize_id_part(value: str) -> str:
    result = []
    for char in value:
        if char.isalnum():
            result.append(char)
        else:
            result.append("_")
    return "".join(result).strip("_")


def _soft_processor_id(task_id: int, physical_processor: str) -> str:
    return f"task{int(task_id)}:{_sanitize_id_part(physical_processor)}"


def _soft_axis_names(physical_mesh_shape: Sequence[int]) -> tuple[str, ...]:
    if len(physical_mesh_shape) == 2:
        return ("task", "x", "y")
    return ("task", *tuple(f"pe_dim{axis}" for axis in range(len(physical_mesh_shape))))


def _processor_id_from_coord(coordinate: Sequence[int]) -> str:
    return "processor_" + "_".join(str(int(coord)) for coord in coordinate)


def _vendor_pe_id_from_coord(coordinate: Sequence[int]) -> str | None:
    if len(coordinate) != 2:
        return None
    row, col = (int(coordinate[0]), int(coordinate[1]))
    return f"PE{row}{col}"


def _task_scoped_group_key(
    *,
    task_axis_size: int,
    task_id: int,
    fabric_scope: str,
    group_index: int,
) -> str:
    if int(task_axis_size) <= 1:
        return f"{fabric_scope}:{group_index}"
    return f"task{int(task_id)}:{fabric_scope}:{group_index}"


def _split_dim(dim_size: int, num_chunks: int, chunk_idx: int) -> tuple[int, int]:
    base = dim_size // num_chunks
    remainder = dim_size % num_chunks
    if chunk_idx < remainder:
        shard_size = base + 1
        shard_offset = chunk_idx * shard_size
    else:
        shard_size = base
        shard_offset = remainder * (base + 1) + (chunk_idx - remainder) * base
    return shard_size, shard_offset


__all__ = [
    "LogicalDependency",
    "LogicalReduceEdge",
    "LogicalRouteEdge",
    "LogicalRouteStep",
    "ProcessorLocalValue",
    "LogicalApp",
    "ProcessorLogicalAction",
    "LogicalPlan",
    "LogicalStream",
    "compute_local_shape_and_offset",
]
