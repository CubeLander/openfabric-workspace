"""Tile-level program IR.

This layer lowers processor-local logical actions into tile-sized tasks.  It
still does not emit DFU assembly or vendor instruction records; it names tile
values, tile phases, and logical collective bundles that later backend passes
can materialize.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any, Literal

from gpdpu_compiler.core.op_specs import MATMUL_SPEC
from gpdpu_compiler.core.logical_plan import (
    LogicalReduceEdge,
    LogicalRouteEdge,
    LogicalRouteStep,
    ProcessorLocalValue,
    ProcessorLogicalAction,
    LogicalPlan,
    LogicalStream,
)
from gpdpu_compiler.core.program_app import AppPlan


TileValueKind = Literal[
    "PE_LOCAL_TILE",
    "PE_LOCAL_SCALAR",
    "REPLICATED_APP_SCALAR",
    "MATERIALIZED_SCALAR",
    "MATERIALIZED_TILE",
    "MATERIALIZED_TENSOR",
]

TileDependencyValueKind = Literal[
    "tile_value",
    "local_scalar",
    "collective_result",
    "materialized_storage",
    "control_barrier",
]


@dataclass(frozen=True)
class TileSubtaskPlan:
    """One vendor-facing subtask role inside a tile task."""

    subtask_id: int
    subtask_name: str
    role: str
    instance_count: int
    repeat_semantics: str | None = None

    def to_plan(self) -> dict[str, Any]:
        return {
            "subtask_id": self.subtask_id,
            "subtask_name": self.subtask_name,
            "role": self.role,
            "instance_count": self.instance_count,
            "repeat_semantics": self.repeat_semantics,
        }


@dataclass(frozen=True)
class VendorTaskProjection:
    """Tile-local projection from soft task axis to legacy vendor task row."""

    assignment_id: str
    source_action: str
    source_chip_op: str
    processor: str
    wave_id: int
    work_index: int
    work_coord: dict[str, int]
    work_axis_order: tuple[str, ...]
    launch_group_id: int
    task_id: int
    task_name: str
    m_tile: int
    n_tile: int
    k_blocks: int
    policy_name: str
    max_vendor_tasks: int
    assignment_source: str
    task_axis_rank: int
    task_axis_partition_count: int
    task_axis_size: int
    task_axis_work_domain: str
    task_axis_placement: dict[str, Any] | None
    subtask_role_map: dict[str, str]
    subtask_plan: tuple[TileSubtaskPlan, ...]

    @property
    def assignment_key(self) -> tuple[str, int, int, int, int, int]:
        return (
            self.policy_name,
            self.wave_id,
            self.launch_group_id,
            self.task_id,
            self.m_tile,
            self.n_tile,
        )

    def to_payload(self) -> dict[str, Any]:
        return {
            "assignment_id": self.assignment_id,
            "assignment_key": list(self.assignment_key),
            "source_action": self.source_action,
            "source_chip_op": self.source_chip_op,
            "processor": self.processor,
            "virtual_work_id": self.work_index,
            "wave_id": self.wave_id,
            "legacy_wave_id": self.wave_id,
            "work_index": self.work_index,
            "work_coord": dict(self.work_coord),
            "work_axis_order": list(self.work_axis_order),
            "launch_group_id": self.launch_group_id,
            "task_id": self.task_id,
            "task_name": self.task_name,
            "m_tile": self.m_tile,
            "n_tile": self.n_tile,
            "k_blocks": self.k_blocks,
            "policy_name": self.policy_name,
            "max_vendor_tasks": self.max_vendor_tasks,
            "assignment_source": self.assignment_source,
            "task_axis_rank": self.task_axis_rank,
            "task_axis_partition_count": self.task_axis_partition_count,
            "task_axis_size": self.task_axis_size,
            "task_axis_work_domain": self.task_axis_work_domain,
            "task_axis_placement": self.task_axis_placement,
            "subtask_role_map": dict(self.subtask_role_map),
            "subtask_plan": [subtask.to_plan() for subtask in self.subtask_plan],
        }

    def to_plan(self) -> dict[str, Any]:
        return self.to_payload()


@dataclass
class TilePhase:
    """One tile-level task for one processor."""

    phase_id: str
    phase_kind: str
    processor: str
    source_action: str
    source_chip_op: str
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    local_ops: tuple[str, ...] = ()
    collective_refs: tuple[str, ...] = ()
    route_prefix_refs: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "phase_id": self.phase_id,
            "phase_kind": self.phase_kind,
            "processor": self.processor,
            "source_action": self.source_action,
            "source_chip_op": self.source_chip_op,
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "local_ops": list(self.local_ops),
            "collective_refs": list(self.collective_refs),
            "route_prefix_refs": list(self.route_prefix_refs),
            "payload": self.payload,
        }


@dataclass
class TileProgramItemRef:
    """One ordered item in a processor tile program.

    This is the sequencing view: regular phases and tile-loop microprograms live
    in the same outer stream, while loop bodies remain inspectable through
    action/dependency tables.
    """

    item_id: str
    item_kind: str
    ref_id: str
    source_action: str
    order_key: tuple[int, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "item_id": self.item_id,
            "item_kind": self.item_kind,
            "ref_id": self.ref_id,
            "source_action": self.source_action,
            "order_key": list(self.order_key),
            "attrs": self.attrs,
        }


@dataclass
class ProcessorTileStream:
    """Tile phases for one processor."""

    processor: str
    coordinate: tuple[int, ...]
    vendor_processor_id: str | None = None
    phases: list[TilePhase] = field(default_factory=list)
    program_sequence: list[TileProgramItemRef] = field(default_factory=list)

    def to_plan(self) -> dict[str, Any]:
        return {
            "processor": self.processor,
            "coordinate": list(self.coordinate),
            "vendor_processor_id": self.vendor_processor_id,
            "phases": [phase.to_plan() for phase in self.phases],
            "program_sequence": [item.to_plan() for item in self.program_sequence],
        }


@dataclass
class TileCollectiveBundle:
    """A logical tile visibility obligation."""

    bundle_id: str
    collective_kind: str
    participants: tuple[str, ...]
    input_refs: tuple[str, ...]
    output_refs: tuple[str, ...]
    logical_source: str
    consumers: list[str] = field(default_factory=list)
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "bundle_id": self.bundle_id,
            "collective_kind": self.collective_kind,
            "participants": list(self.participants),
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "logical_source": self.logical_source,
            "source_tile_identity": self.logical_source,
            "consumers": list(self.consumers),
            "attrs": self.attrs,
        }


@dataclass(frozen=True)
class TileRouteAction:
    """One tile-level communication action expanded from a logical route step.

    DFU COPY/COPYT is source-side push: the executable instruction lives on the
    sender/source processor, while the produced visibility endpoint belongs to
    the destination/receiver processor.
    """

    id: str
    tile_route_group_id: str
    logical_route_edge_id: str
    logical_route_step_id: str
    bundle_id: str
    execution_processor: str
    endpoint_processor: str
    step_kind: str
    source_tile_ref: str
    produces_endpoint_ref: str
    position: int
    operand_role: str
    k_index: int
    src_processor: str | None = None
    dst_processor: str | None = None
    depends_on: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "tile_route_group_id": self.tile_route_group_id,
            "logical_route_edge_id": self.logical_route_edge_id,
            "logical_route_step_id": self.logical_route_step_id,
            "bundle_id": self.bundle_id,
            "execution_processor": self.execution_processor,
            "endpoint_processor": self.endpoint_processor,
            "step_kind": self.step_kind,
            "source_tile_ref": self.source_tile_ref,
            "produces_endpoint_ref": self.produces_endpoint_ref,
            "position": self.position,
            "operand_role": self.operand_role,
            "k_index": self.k_index,
            "src_processor": self.src_processor,
            "dst_processor": self.dst_processor,
            "depends_on": list(self.depends_on),
            "attrs": self.attrs,
        }


@dataclass(frozen=True)
class TileComputeAction:
    """One tile-level compute action owned by a processor."""

    id: str
    processor: str
    phase_id: str
    source_action: str
    source_chip_op: str
    compute_kind: str
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "processor": self.processor,
            "phase_id": self.phase_id,
            "source_action": self.source_action,
            "source_chip_op": self.source_chip_op,
            "compute_kind": self.compute_kind,
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "depends_on": list(self.depends_on),
            "attrs": self.attrs,
        }


@dataclass(frozen=True)
class TileStoreAction:
    """One tile-level store/finalization action owned by a processor."""

    id: str
    processor: str
    phase_id: str
    source_action: str
    source_chip_op: str
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "processor": self.processor,
            "phase_id": self.phase_id,
            "source_action": self.source_action,
            "source_chip_op": self.source_chip_op,
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "depends_on": list(self.depends_on),
            "attrs": self.attrs,
        }


@dataclass(frozen=True)
class TileAppStorageAction:
    """One symbolic tile-level app storage boundary action.

    These actions are still IR-only for generic staged ops. They make app
    storage materialization visible to tile analysis without pretending that a
    runnable DFU3500 scalar workspace implementation exists yet.
    """

    id: str
    processor: str
    action_kind: str
    app_storage_edge_id: str
    storage_id: str
    value_id: str
    source_app_id: int | None = None
    consumer_app_id: int | None = None
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "processor": self.processor,
            "action_kind": self.action_kind,
            "app_storage_edge_id": self.app_storage_edge_id,
            "storage_id": self.storage_id,
            "value_id": self.value_id,
            "source_app_id": self.source_app_id,
            "consumer_app_id": self.consumer_app_id,
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "depends_on": list(self.depends_on),
            "attrs": self.attrs,
        }


@dataclass(frozen=True)
class AppStorageAddressRecord:
    """Report-only candidate address record for a logical app storage region.

    This does not allocate SRAM/SPM space or make app storage runtime-ready. It
    gives later report/lowering passes a typed source record to consume while
    keeping missing concrete allocator facts explicit.
    """

    source_id: str
    source_id_kind: str
    logical_value_id: str
    address_space: str | None
    region_id: str | None
    offset_bytes: int | None
    size_bytes: int
    instance_base_addr_source: str | None
    status: str
    evidence: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, Any]:
        return {
            "record_kind": "app_storage_address_record",
            "source_id": self.source_id,
            "source_id_kind": self.source_id_kind,
            "logical_value_id": self.logical_value_id,
            "address_space": self.address_space,
            "region_id": self.region_id,
            "offset_bytes": self.offset_bytes,
            "size_bytes": self.size_bytes,
            "instance_base_addr_source": self.instance_base_addr_source,
            "status": self.status,
            "evidence": list(self.evidence),
        }


@dataclass(frozen=True)
class TileVisibilityRef:
    """A receiver-side tile visibility token produced by a route action.

    DFU COPY/COPYT is sender-push, so the receiver visibility endpoint is data
    availability, not necessarily a receiver-side executable action.
    """

    ref_id: str
    tensor_ref: str
    producer_action_id: str
    endpoint_processor: str
    source_processor: str | None = None
    loop_region_id: str | None = None
    loop_instance_id: int | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "ref_id": self.ref_id,
            "tensor_ref": self.tensor_ref,
            "producer_action_id": self.producer_action_id,
            "endpoint_processor": self.endpoint_processor,
            "source_processor": self.source_processor,
            "loop_region_id": self.loop_region_id,
            "loop_instance_id": self.loop_instance_id,
            "attrs": self.attrs,
        }


@dataclass(frozen=True)
class TileMicroBlock:
    """A tile-level executable block boundary.

    This is still tile IR, not vendor assembly.  Later layers should consume
    this partition instead of rediscovering route/compute/store block roles.
    """

    block_id: str
    processor: str
    block_kind: str
    source_phase_id: str | None
    loop_region_id: str | None = None
    loop_instance_id: int | None = None
    loop_axis: str | None = None
    fold_policy: str | None = None
    action_ids: tuple[str, ...] = ()
    route_action_ids: tuple[str, ...] = ()
    compute_action_ids: tuple[str, ...] = ()
    store_action_ids: tuple[str, ...] = ()
    input_visibility_refs: tuple[str, ...] = ()
    output_visibility_refs: tuple[str, ...] = ()
    input_value_refs: tuple[str, ...] = ()
    output_value_refs: tuple[str, ...] = ()
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "block_id": self.block_id,
            "processor": self.processor,
            "block_kind": self.block_kind,
            "source_phase_id": self.source_phase_id,
            "loop_region_id": self.loop_region_id,
            "loop_instance_id": self.loop_instance_id,
            "loop_axis": self.loop_axis,
            "fold_policy": self.fold_policy,
            "action_ids": list(self.action_ids),
            "route_action_ids": list(self.route_action_ids),
            "compute_action_ids": list(self.compute_action_ids),
            "store_action_ids": list(self.store_action_ids),
            "input_visibility_refs": list(self.input_visibility_refs),
            "output_visibility_refs": list(self.output_visibility_refs),
            "input_value_refs": list(self.input_value_refs),
            "output_value_refs": list(self.output_value_refs),
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "attrs": self.attrs,
        }


@dataclass(frozen=True)
class TileBlockDependency:
    """A dependency projected from action edges onto tile micro-blocks."""

    dep_id: str
    src_block_id: str
    dst_block_id: str
    dep_kind: str
    source_tile_dependency_ids: tuple[str, ...]
    loop_region_id: str | None = None
    loop_instance_id: int | None = None
    vendor_graph_eligible: bool = True
    absorbed_by: str | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "dep_id": self.dep_id,
            "src_block_id": self.src_block_id,
            "dst_block_id": self.dst_block_id,
            "dep_kind": self.dep_kind,
            "source_tile_dependency_ids": list(self.source_tile_dependency_ids),
            "loop_region_id": self.loop_region_id,
            "loop_instance_id": self.loop_instance_id,
            "vendor_graph_eligible": self.vendor_graph_eligible,
            "absorbed_by": self.absorbed_by,
            "attrs": self.attrs,
        }


@dataclass(frozen=True)
class TileLoopBodyInstance:
    """A symbolic tile-loop body instance.

    Existing tile actions may still be fully expanded for analysis/debugging.
    This record groups the per-instance route/compute/store actions that form a
    closed tile microprogram body.
    """

    instance_id: int
    iv_bindings: dict[str, Any]
    action_ids: tuple[str, ...]
    micro_block_ids: tuple[str, ...] = ()
    micro_block_ids_by_processor: dict[str, tuple[str, ...]] = field(default_factory=dict)
    route_action_ids: tuple[str, ...] = ()
    compute_action_ids: tuple[str, ...] = ()
    store_action_ids: tuple[str, ...] = ()
    depends_on_previous_instance: bool = False
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "iv_bindings": self.iv_bindings,
            "action_ids": list(self.action_ids),
            "micro_block_ids": list(self.micro_block_ids),
            "micro_block_ids_by_processor": {
                processor: list(block_ids)
                for processor, block_ids in sorted(self.micro_block_ids_by_processor.items())
            },
            "route_action_ids": list(self.route_action_ids),
            "compute_action_ids": list(self.compute_action_ids),
            "store_action_ids": list(self.store_action_ids),
            "depends_on_previous_instance": self.depends_on_previous_instance,
            "attrs": self.attrs,
        }


@dataclass(frozen=True)
class TileLoopRegion:
    """Tile-level loop microprogram region.

    A loop region is a first-class tile program item.  Its body is not opaque:
    body actions are still present in the flat tile action/dependency tables so
    later passes can validate resources and lower to vendor subtasks.
    """

    loop_id: str
    processor: str
    source_phase_id: str
    source_action: str
    source_chip_op: str
    loop_axis: str
    repeat_count: int
    closure_shape: str
    fold_policy: str
    body_instances: tuple[TileLoopBodyInstance, ...]
    carried_refs: tuple[str, ...] = ()
    captured_refs: tuple[str, ...] = ()
    loop_variant_refs: tuple[str, ...] = ()
    loop_invariant_refs: tuple[str, ...] = ()
    grouping: dict[str, Any] | None = None
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "loop_id": self.loop_id,
            "processor": self.processor,
            "source_phase_id": self.source_phase_id,
            "source_action": self.source_action,
            "source_chip_op": self.source_chip_op,
            "loop_axis": self.loop_axis,
            "repeat_count": self.repeat_count,
            "closure_shape": self.closure_shape,
            "fold_policy": self.fold_policy,
            "body_instances": [instance.to_plan() for instance in self.body_instances],
            "carried_refs": list(self.carried_refs),
            "captured_refs": list(self.captured_refs),
            "loop_variant_refs": list(self.loop_variant_refs),
            "loop_invariant_refs": list(self.loop_invariant_refs),
            "grouping": self.grouping,
            "attrs": self.attrs,
        }


@dataclass(frozen=True)
class ProcessorTileActionRef:
    """A per-processor reference to a tile action table entry."""

    action_id: str
    action_kind: str
    phase_id: str | None = None
    order_key: tuple[int, ...] = ()

    def to_plan(self) -> dict[str, Any]:
        return {
            "action_id": self.action_id,
            "action_kind": self.action_kind,
            "phase_id": self.phase_id,
            "order_key": list(self.order_key),
        }


@dataclass
class ProcessorTileActionStream:
    """Unified per-processor tile action list.

    Route actions are placed on their sender/execution processor. Compute and
    store actions are placed on their owning phase processor.
    """

    processor: str
    actions: list[ProcessorTileActionRef] = field(default_factory=list)

    def to_plan(self) -> dict[str, Any]:
        return {
            "processor": self.processor,
            "actions": [action.to_plan() for action in self.actions],
        }


@dataclass(frozen=True)
class TileDependency:
    """A tile-level dependency edge."""

    id: str
    dependency_kind: str
    src: str
    dst: str
    logical_route_edge_id: str | None = None
    tile_route_group_id: str | None = None
    value_id: str | None = None
    dependency_value_kind: TileDependencyValueKind | None = None
    producer_value_kind: TileValueKind | None = None
    consumer_value_kind: TileValueKind | None = None
    crosses_app_boundary: bool = False
    scope: str = "processor_tile"
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "dependency_kind": self.dependency_kind,
            "src": self.src,
            "dst": self.dst,
            "logical_route_edge_id": self.logical_route_edge_id,
            "tile_route_group_id": self.tile_route_group_id,
            "value_id": self.value_id,
            "dependency_value_kind": self.dependency_value_kind,
            "producer_value_kind": self.producer_value_kind,
            "consumer_value_kind": self.consumer_value_kind,
            "crosses_app_boundary": self.crosses_app_boundary,
            "scope": self.scope,
            "attrs": self.attrs,
        }


@dataclass
class ProcessorTileProgram:
    """Whole-chip tile-level program."""

    chip: str
    source_program: str
    source_ir: str
    processor_shape: tuple[int, ...]
    tile_sizes: dict[str, int]
    vendor_task_projection: dict[str, Any]
    programs: dict[str, ProcessorTileStream]
    collective_bundles: dict[str, TileCollectiveBundle]
    app_storage_regions: dict[str, dict[str, Any]]
    app_storage_address_records: dict[str, AppStorageAddressRecord]
    app_storage_edges: dict[str, dict[str, Any]]
    tile_route_actions: dict[str, TileRouteAction]
    tile_compute_actions: dict[str, TileComputeAction]
    tile_store_actions: dict[str, TileStoreAction]
    tile_app_storage_actions: dict[str, TileAppStorageAction]
    tile_visibility_refs: dict[str, TileVisibilityRef]
    tile_micro_blocks: dict[str, TileMicroBlock]
    tile_block_dependencies: dict[str, TileBlockDependency]
    action_to_micro_block: dict[str, str]
    tile_loop_regions: dict[str, TileLoopRegion]
    tile_dependencies: dict[str, TileDependency]
    processor_action_streams: dict[str, ProcessorTileActionStream]
    output_bindings: dict[str, str] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ir": "processor_tile_program",
            "chip": self.chip,
            "source_program": self.source_program,
            "source_ir": self.source_ir,
            "processor_shape": list(self.processor_shape),
            "tile_sizes": dict(self.tile_sizes),
            "vendor_task_projection": self.vendor_task_projection,
            "layering_policy": (
                "tile_program_lowers_processor_logical_actions;"
                "tile_phases_are_not_architecture_instructions;"
                "vendor_task_rows_are_projection_metadata;"
                "dfu_assembly_lowering_not_started"
            ),
            "programs": {
                processor: program.to_plan()
                for processor, program in sorted(self.programs.items())
            },
            "collective_bundles": {
                bundle_id: bundle.to_plan()
                for bundle_id, bundle in sorted(self.collective_bundles.items())
            },
            "app_storage_regions": {
                storage_id: dict(region)
                for storage_id, region in sorted(self.app_storage_regions.items())
            },
            **(
                {
                    "app_storage_address_records": {
                        source_id: record.to_plan()
                        for source_id, record in sorted(
                            self.app_storage_address_records.items()
                        )
                    },
                }
                if self.app_storage_address_records
                else {}
            ),
            "app_storage_edges": {
                edge_id: dict(edge)
                for edge_id, edge in sorted(self.app_storage_edges.items())
            },
            "tile_route_actions": {
                action_id: action.to_plan()
                for action_id, action in sorted(self.tile_route_actions.items())
            },
            "tile_compute_actions": {
                action_id: action.to_plan()
                for action_id, action in sorted(self.tile_compute_actions.items())
            },
            "tile_store_actions": {
                action_id: action.to_plan()
                for action_id, action in sorted(self.tile_store_actions.items())
            },
            "tile_app_storage_actions": {
                action_id: action.to_plan()
                for action_id, action in sorted(self.tile_app_storage_actions.items())
            },
            "tile_visibility_refs": {
                ref_id: ref.to_plan()
                for ref_id, ref in sorted(self.tile_visibility_refs.items())
            },
            "tile_micro_blocks": {
                block_id: block.to_plan()
                for block_id, block in sorted(self.tile_micro_blocks.items())
            },
            "tile_block_dependencies": {
                dependency_id: dependency.to_plan()
                for dependency_id, dependency in sorted(self.tile_block_dependencies.items())
            },
            "action_to_micro_block": dict(sorted(self.action_to_micro_block.items())),
            "tile_loop_regions": {
                loop_id: loop.to_plan()
                for loop_id, loop in sorted(self.tile_loop_regions.items())
            },
            "tile_dependencies": {
                dependency_id: dependency.to_plan()
                for dependency_id, dependency in sorted(self.tile_dependencies.items())
            },
            "processor_action_streams": {
                processor: stream.to_plan()
                for processor, stream in sorted(self.processor_action_streams.items())
            },
            "output_bindings": dict(sorted(self.output_bindings.items())),
            "validation": {
                "all_actions_have_micro_blocks": self._all_actions_have_micro_blocks(),
                "all_route_blocks_owned_by_execution_processor": (
                    self._all_route_blocks_owned_by_execution_processor()
                ),
                "all_compute_blocks_owned_by_compute_processor": (
                    self._all_compute_blocks_owned_by_compute_processor()
                ),
                "all_store_blocks_owned_by_store_processor": (
                    self._all_store_blocks_owned_by_store_processor()
                ),
                "cross_app_dependencies_are_materialized_storage": (
                    self._cross_app_dependencies_are_materialized_storage()
                ),
            },
            "totals": {
                "processor_count": len(self.programs),
                "phase_count": sum(len(program.phases) for program in self.programs.values()),
                "collective_bundle_count": len(self.collective_bundles),
                "tile_route_action_count": len(self.tile_route_actions),
                "tile_compute_action_count": len(self.tile_compute_actions),
                "tile_store_action_count": len(self.tile_store_actions),
                "tile_app_storage_action_count": len(self.tile_app_storage_actions),
                "app_storage_region_count": len(self.app_storage_regions),
                **(
                    {
                        "app_storage_address_record_count": len(
                            self.app_storage_address_records
                        ),
                    }
                    if self.app_storage_address_records
                    else {}
                ),
                "app_storage_edge_count": len(self.app_storage_edges),
                "tile_visibility_ref_count": len(self.tile_visibility_refs),
                "tile_micro_block_count": len(self.tile_micro_blocks),
                "tile_block_dependency_count": len(self.tile_block_dependencies),
                "action_to_micro_block_count": len(self.action_to_micro_block),
                "tile_loop_region_count": len(self.tile_loop_regions),
                "processor_tile_action_count": sum(
                    len(stream.actions) for stream in self.processor_action_streams.values()
                ),
                "tile_dependency_count": len(self.tile_dependencies),
                "output_count": len(self.output_bindings),
            },
        }

    def _all_actions_have_micro_blocks(self) -> bool:
        action_count = (
            len(self.tile_route_actions)
            + len(self.tile_compute_actions)
            + len(self.tile_store_actions)
            + len(self.tile_app_storage_actions)
        )
        return len(self.action_to_micro_block) == action_count

    def _all_route_blocks_owned_by_execution_processor(self) -> bool:
        for action_id, action in self.tile_route_actions.items():
            block = self.tile_micro_blocks.get(self.action_to_micro_block.get(action_id, ""))
            if block is None or block.processor != action.execution_processor:
                return False
        return True

    def _all_compute_blocks_owned_by_compute_processor(self) -> bool:
        for action_id, action in self.tile_compute_actions.items():
            block = self.tile_micro_blocks.get(self.action_to_micro_block.get(action_id, ""))
            if block is None or block.processor != action.processor:
                return False
        return True

    def _all_store_blocks_owned_by_store_processor(self) -> bool:
        for action_id, action in self.tile_store_actions.items():
            block = self.tile_micro_blocks.get(self.action_to_micro_block.get(action_id, ""))
            if block is None or block.processor != action.processor:
                return False
        return True

    def _cross_app_dependencies_are_materialized_storage(self) -> bool:
        return all(
            not dependency.crosses_app_boundary
            or dependency.dependency_value_kind == "materialized_storage"
            for dependency in self.tile_dependencies.values()
        )


def lower_processor_logical_to_tile_program(
    processor_program: LogicalPlan,
    chip_config: dict[str, Any],
    app_plan: AppPlan | None = None,
) -> ProcessorTileProgram:
    builder = _TileLoweringBuilder(
        processor_program=processor_program,
        chip_config=chip_config,
        app_plan=app_plan,
    )
    return builder.build()


class _TileLoweringBuilder:
    def __init__(
        self,
        *,
        processor_program: LogicalPlan,
        chip_config: dict[str, Any],
        app_plan: AppPlan | None = None,
    ) -> None:
        self.processor_program = processor_program
        self.chip_config = chip_config
        self.app_plan = app_plan
        self.task_partition_plan = processor_program.task_partition_plan
        self.tile_sizes = _tile_sizes_from_config(chip_config)
        self.max_tasks = int(chip_config.get("vendor_limits", {}).get("max_tasks", 4))
        self.vendor_task_projections: dict[str, VendorTaskProjection] = {}
        self.programs: dict[str, ProcessorTileStream] = {}
        self.collective_bundles: dict[str, TileCollectiveBundle] = {}
        self.app_storage_regions: dict[str, dict[str, Any]] = {}
        self.app_storage_address_records: dict[str, AppStorageAddressRecord] = {}
        self.app_storage_edges: dict[str, dict[str, Any]] = {}
        if app_plan is not None:
            self._collect_app_materialization_ops(app_plan)
        self.tile_route_actions: dict[str, TileRouteAction] = {}
        self.tile_compute_actions: dict[str, TileComputeAction] = {}
        self.tile_store_actions: dict[str, TileStoreAction] = {}
        self.tile_app_storage_actions: dict[str, TileAppStorageAction] = {}
        self.tile_visibility_refs: dict[str, TileVisibilityRef] = {}
        self.tile_micro_blocks: dict[str, TileMicroBlock] = {}
        self.tile_block_dependencies: dict[str, TileBlockDependency] = {}
        self.action_to_micro_block: dict[str, str] = {}
        self.tile_loop_regions: dict[str, TileLoopRegion] = {}
        self.tile_dependencies: dict[str, TileDependency] = {}
        self.processor_action_streams: dict[str, ProcessorTileActionStream] = {}
        self.value_final_tile_actions: dict[str, list[dict[str, Any]]] = {}

    def build(self) -> ProcessorTileProgram:
        for processor, logical_stream in sorted(self.processor_program.streams.items()):
            tile_stream = ProcessorTileStream(
                processor=processor,
                coordinate=logical_stream.coordinate,
                vendor_processor_id=logical_stream.vendor_processor_id,
            )
            self._lower_stream(logical_stream, tile_stream)
            self.programs[processor] = tile_stream

        self._build_app_storage_actions()
        self._build_app_storage_address_records()
        self._build_processor_action_streams()
        self._build_tile_micro_blocks()

        return ProcessorTileProgram(
            chip=self.processor_program.chip,
            source_program=self.processor_program.source_program,
            source_ir="logical_plan",
            processor_shape=self.processor_program.task_axis_mesh.physical_mesh_shape,
            tile_sizes=self.tile_sizes,
            vendor_task_projection=self._vendor_task_projection(),
            programs=self.programs,
            collective_bundles=self.collective_bundles,
            app_storage_regions=self.app_storage_regions,
            app_storage_address_records=self.app_storage_address_records,
            app_storage_edges=self.app_storage_edges,
            tile_route_actions=self.tile_route_actions,
            tile_compute_actions=self.tile_compute_actions,
            tile_store_actions=self.tile_store_actions,
            tile_app_storage_actions=self.tile_app_storage_actions,
            tile_visibility_refs=self.tile_visibility_refs,
            tile_micro_blocks=self.tile_micro_blocks,
            tile_block_dependencies=self.tile_block_dependencies,
            action_to_micro_block=self.action_to_micro_block,
            tile_loop_regions=self.tile_loop_regions,
            tile_dependencies=self.tile_dependencies,
            processor_action_streams=self.processor_action_streams,
            output_bindings=dict(self.processor_program.output_bindings),
        )

    def _lower_stream(
        self,
        logical_stream: LogicalStream,
        tile_stream: ProcessorTileStream,
    ) -> None:
        action_index = 0
        while action_index < len(logical_stream.actions):
            action = logical_stream.actions[action_index]
            if action.op == "load_sram_tensor":
                action_index += 1
                continue
            if action.op in {"app_materialize_store", "app_materialize_load"}:
                action_index += 1
                continue
            if action.op == "matmul":
                post_ops, consumed = self._collect_attached_post_ops(
                    logical_stream.actions,
                    action_index + 1,
                    action.outputs[0],
                )
                phases = self._lower_matmul(logical_stream, action, post_ops)
                tile_stream.phases.extend(phases)
                for phase in phases:
                    loop_id = _tile_loop_id(phase.processor, phase.phase_id)
                    task_assignment = phase.payload.get("task_assignment")
                    virtual_work_id = (
                        int(task_assignment.get("virtual_work_id", 0))
                        if isinstance(task_assignment, dict)
                        else 0
                    )
                    if loop_id in self.tile_loop_regions:
                        tile_stream.program_sequence.append(
                            TileProgramItemRef(
                                item_id=f"item:{phase.phase_id}",
                                item_kind="tile_loop",
                                ref_id=loop_id,
                                source_action=phase.source_action,
                                order_key=(
                                    virtual_work_id,
                                ),
                                attrs={
                                    "source_phase_id": phase.phase_id,
                                    "lowering_hint": "gemm_phase_represented_as_tile_loop_region",
                                },
                            )
                        )
                    else:
                        tile_stream.program_sequence.append(
                            _phase_program_item(phase, order_index=action_index)
                        )
                action_index += consumed + 1
            elif action.op == "store_sram_tensor":
                phase = self._lower_store(logical_stream, action)
                tile_stream.phases.append(phase)
                tile_stream.program_sequence.append(_phase_program_item(phase, order_index=action_index))
                action_index += 1
            else:
                phase = self._lower_generic(logical_stream, action)
                tile_stream.phases.append(phase)
                tile_stream.program_sequence.append(_phase_program_item(phase, order_index=action_index))
                action_index += 1

    def _collect_attached_post_ops(
        self,
        actions: list[ProcessorLogicalAction],
        start_index: int,
        current_value: str,
    ) -> tuple[list[dict[str, Any]], int]:
        post_ops: list[dict[str, Any]] = []
        consumed = 0
        index = start_index
        while index < len(actions):
            action = actions[index]
            if action.op != "relu" or action.inputs != (current_value,) or len(action.outputs) != 1:
                break
            output = self._local_value(action.outputs[0])
            post_ops.append(
                {
                    "op": "relu",
                    "source_action": action.id,
                    "source_chip_op": action.source_chip_op,
                    "input": current_value,
                    "output": action.outputs[0],
                    "output_tensor": output.logical_tensor_id,
                    "output_tensor_name": output.logical_tensor_name,
                }
            )
            current_value = action.outputs[0]
            consumed += 1
            index += 1
        return post_ops, consumed


    def _collect_app_materialization_ops(self, app_plan: AppPlan) -> None:
        stores: dict[str, tuple[int, Any]] = {}
        loads_by_storage: dict[str, list[tuple[int, Any]]] = {}
        for app_id, app_ops in enumerate(app_plan.apps):
            for op in app_ops:
                storage_id = op.attrs.get("storage_id")
                if not storage_id:
                    continue
                if op.op == "app_materialize_store":
                    stores[storage_id] = (app_id, op)
                    self.app_storage_regions[storage_id] = {
                        "storage_id": storage_id,
                        "value_id": op.attrs.get("value_id"),
                        "dtype": op.attrs.get("dtype"),
                        "shape": list(op.attrs.get("shape", ())),
                        "layout": op.attrs.get("layout"),
                        "materialization_kind": op.attrs.get("materialization_kind"),
                        "allocation_kind": "compiler_created",
                        "lifetime": "inter_app",
                    }
                elif op.op == "app_materialize_load":
                    loads_by_storage.setdefault(storage_id, []).append((app_id, op))

        for storage_id, (producer_app_id, store_op) in stores.items():
            loads = loads_by_storage.get(storage_id, [])
            if not loads:
                continue
            edge_id = f"app_storage_edge:{store_op.attrs.get('value_id')}"
            self.app_storage_edges[edge_id] = {
                "edge_id": edge_id,
                "value_id": store_op.attrs.get("value_id"),
                "producer_app_id": producer_app_id,
                "consumer_app_ids": tuple(app_id for app_id, _ in loads),
                "storage_id": storage_id,
                "materialization_kind": store_op.attrs.get("materialization_kind"),
                "producer_op": store_op.attrs.get("producer_op", "reduce_store"),
                "consumer_op": loads[0][1].attrs.get("consumer_op", "broadcast_load"),
                "shape": tuple(store_op.attrs.get("shape", ())),
                "layout": store_op.attrs.get("layout"),
            }

    def _build_app_storage_actions(self) -> None:
        for edge in self.app_storage_edges.values():
            edge_id = edge["edge_id"]
            value_id = edge["value_id"]
            storage_id = edge["storage_id"]
            reduce_edge = self._logical_reduce_for_value(value_id)
            participants = (
                reduce_edge.participants
                if reduce_edge is not None
                else tuple(sorted(self.processor_program.streams))
            )
            if not participants:
                continue
            owner_processor = participants[0]
            materialize_input_ref = (
                reduce_edge.output_value_ids[0]
                if reduce_edge is not None and reduce_edge.output_value_ids
                else value_id
            )
            materialize_depends_on = tuple(
                _tile_action_ids(
                    self.value_final_tile_actions.get(materialize_input_ref),
                    materialize_input_ref,
                )
            )
            materialize_action_id = _tile_app_storage_action_id(
                "materialize",
                edge_id,
                owner_processor,
            )
            self.tile_app_storage_actions[materialize_action_id] = TileAppStorageAction(
                id=materialize_action_id,
                processor=owner_processor,
                action_kind=edge["producer_op"],
                app_storage_edge_id=edge_id,
                storage_id=storage_id,
                value_id=value_id,
                source_app_id=edge["producer_app_id"],
                input_refs=(materialize_input_ref,),
                output_refs=(storage_id,),
                depends_on=materialize_depends_on,
                attrs={
                    "materialization_kind": edge["materialization_kind"],
                    "layout": edge["layout"],
                    "shape": list(edge["shape"]),
                    "logical_reduce_edge_id": reduce_edge.id if reduce_edge else None,
                    "implementation_status": "symbolic_app_storage_materialize",
                    "storage_boundary": "app_materialize_store_op",
                },
            )
            for parent in materialize_depends_on:
                self._ensure_tile_dependency(
                    dependency_kind="collective_result_before_materialize_storage",
                    src=parent,
                    dst=materialize_action_id,
                    value_id=value_id,
                    dependency_value_kind="collective_result",
                    producer_value_kind="REPLICATED_APP_SCALAR",
                    consumer_value_kind="MATERIALIZED_SCALAR",
                    attrs={
                        "app_storage_edge_id": edge_id,
                        "storage_id": storage_id,
                        "owner_processor": owner_processor,
                    },
                )

            for consumer_app_id in edge["consumer_app_ids"]:
                for processor in participants:
                    load_action_id = _tile_app_storage_action_id(
                        "load",
                        edge_id,
                        processor,
                        consumer_app_id=consumer_app_id,
                    )
                    loaded_ref = _tile_app_storage_loaded_ref(storage_id, processor)
                    self.tile_app_storage_actions[load_action_id] = TileAppStorageAction(
                        id=load_action_id,
                        processor=processor,
                        action_kind=edge["consumer_op"],
                        app_storage_edge_id=edge_id,
                        storage_id=storage_id,
                        value_id=value_id,
                        consumer_app_id=consumer_app_id,
                        input_refs=(storage_id,),
                        output_refs=(loaded_ref,),
                        depends_on=(materialize_action_id,),
                        attrs={
                            "materialization_kind": edge["materialization_kind"],
                            "layout": edge["layout"],
                            "shape": list(edge["shape"]),
                            "logical_reduce_edge_id": reduce_edge.id if reduce_edge else None,
                            "implementation_status": "symbolic_app_storage_load",
                            "storage_boundary": "app_materialize_load_op",
                        },
                    )
                    self._ensure_tile_dependency(
                        dependency_kind="materialized_storage_before_app_load",
                        src=materialize_action_id,
                        dst=load_action_id,
                        value_id=value_id,
                        dependency_value_kind="materialized_storage",
                        producer_value_kind="MATERIALIZED_SCALAR",
                        consumer_value_kind="REPLICATED_APP_SCALAR",
                        crosses_app_boundary=True,
                        attrs={
                            "app_storage_edge_id": edge_id,
                            "storage_id": storage_id,
                            "producer_app_id": edge["producer_app_id"],
                            "consumer_app_id": consumer_app_id,
                        },
                    )

    def _build_app_storage_address_records(self) -> None:
        for storage_id, region in sorted(self.app_storage_regions.items()):
            record = AppStorageAddressRecord(
                source_id=storage_id,
                source_id_kind="app_storage_region",
                logical_value_id=str(region.get("value_id")),
                address_space=_optional_str(region.get("address_space")),
                region_id=_optional_str(region.get("region_id") or storage_id),
                offset_bytes=_optional_int(region.get("offset_bytes")),
                size_bytes=_app_storage_region_nbytes(region),
                instance_base_addr_source=_optional_str(
                    region.get("instance_base_addr_source")
                    or region.get("base_addr_source")
                    or region.get("legacy_base_addr_source")
                ),
                status="candidate_address_record_present_but_unverified",
                evidence=(
                    f"derived_from=processor_tile_program.app_storage_regions[{storage_id!r}]",
                    "report_only_no_allocator_has_run",
                    "offset_bytes_missing_explicitly_when_none",
                    "instance_base_addr_source_missing_explicitly_when_none",
                ),
            )
            self.app_storage_address_records[storage_id] = record

    def _lower_matmul(
        self,
        stream: LogicalStream,
        action: ProcessorLogicalAction,
        post_ops: list[dict[str, Any]],
    ) -> list[TilePhase]:
        tile_profile = MATMUL_SPEC.tile_lowering_profile()
        if len(stream.coordinate) != 2 or len(self.processor_program.task_axis_mesh.physical_mesh_shape) != 2:
            raise NotImplementedError("current SUMMA tile lowering expects a 2-D processor grid")
        if len(action.inputs) != 2 or len(action.outputs) != 1:
            raise ValueError(f"{action.id} matmul expects two inputs and one output")

        a_value = self._local_value(action.inputs[0])
        b_value = self._local_value(action.inputs[1])
        c_value = self._local_value(action.outputs[0])
        if len(a_value.local_shape) != 2 or len(b_value.local_shape) != 2:
            raise NotImplementedError("current SUMMA tile lowering supports rank-2 matmul only")
        if len(c_value.local_shape) != 2:
            raise NotImplementedError("current SUMMA tile lowering supports rank-2 output only")

        local_m, local_k = a_value.local_shape
        b_k, local_n = b_value.local_shape
        c_m, c_n = c_value.local_shape
        if local_k != b_k or (local_m, local_n) != (c_m, c_n):
            raise ValueError(
                f"local matmul shape mismatch on {stream.processor}: "
                f"A={a_value.local_shape}, B={b_value.local_shape}, C={c_value.local_shape}"
            )

        tile_m = self.tile_sizes["m"]
        tile_n = self.tile_sizes["n"]
        tile_k = self.tile_sizes["k"]
        m_tiles = _ceildiv(local_m, tile_m)
        n_tiles = _ceildiv(local_n, tile_n)
        k_blocks = _ceildiv(local_k, tile_k)
        self._verify_gemm_task_axis_matches_output_work(
            logical_tensor_id=c_value.logical_tensor_id,
            work_unit_count=m_tiles * n_tiles,
        )
        row_index, col_index = stream.coordinate
        row_participants = [
            _processor_at(
                (row_index, col),
                self.processor_program.streams,
                task_id=stream.task_id,
            )
            for col in range(self.processor_program.task_axis_mesh.physical_mesh_shape[1])
        ]
        col_participants = [
            _processor_at(
                (row, col_index),
                self.processor_program.streams,
                task_id=stream.task_id,
            )
            for row in range(self.processor_program.task_axis_mesh.physical_mesh_shape[0])
        ]
        final_output_ref = str(post_ops[-1]["output"]) if post_ops else c_value.id
        final_value = (
            self._local_value(final_output_ref)
            if final_output_ref in self.processor_program.local_values
            else c_value
        )

        phases: list[TilePhase] = []
        work_axis_order = self._task_work_axis_order(
            c_value.logical_tensor_id,
            default=("m_tile", "n_tile"),
        )
        for work_coord in self._gemm_task_work_coords(
            logical_tensor_id=c_value.logical_tensor_id,
            stream=stream,
            m_tiles=m_tiles,
            n_tiles=n_tiles,
            work_axis_order=work_axis_order,
        ):
            m_tile = int(work_coord["m_tile"])
            n_tile = int(work_coord["n_tile"])
            work_shape = {"m_tile": m_tiles, "n_tile": n_tiles}
            work_index = _linear_work_index(
                work_coord,
                work_shape,
                work_axis_order,
            )
            # Compatibility alias only: legacy downstream ids still contain
            # "wave" while task semantics come from work_index/work_coord.
            wave_id = work_index
            task_assignment = self._ensure_gemm_tile_task_assignment(
                source_action=action.id,
                source_chip_op=action.source_chip_op,
                output_logical_tensor_id=c_value.logical_tensor_id,
                processor=stream.processor,
                stream_task_id=stream.task_id,
                wave_id=wave_id,
                work_index=work_index,
                work_coord=work_coord,
                work_axis_order=work_axis_order,
                m_tile=m_tile,
                n_tile=n_tile,
                k_blocks=k_blocks,
            )
            task_assignment_payload = task_assignment.to_payload()
            launch_group_id = task_assignment.launch_group_id
            task_id = task_assignment.task_id

            c_tile = _make_c_tile_descriptor(
                c_value,
                final_value,
                stream.processor,
                m_tile,
                n_tile,
                tile_m,
                tile_n,
            )
            row_bundle_refs: list[str] = []
            col_bundle_refs: list[str] = []
            phase_route_prefix_refs: list[str] = []
            k_block_updates: list[dict[str, Any]] = []
            previous_compute_action_id: str | None = None
            phase_id = f"{action.id}:wave{wave_id}"
            prepare_action_id = _accumulator_prepare_action_id(
                stream.processor,
                action.id,
                wave_id,
            )
            self._ensure_tile_compute_action(
                action_id=prepare_action_id,
                processor=stream.processor,
                phase_id=phase_id,
                source_action=action.id,
                source_chip_op=action.source_chip_op,
                input_refs=(str(c_tile["accumulator_tile_ref"]),),
                output_refs=(str(c_tile["accumulator_view_ref"]),),
                depends_on=(),
                attrs={
                    "compute_kind": tile_profile.accumulator_prepare_kind,
                    "task_assignment": task_assignment_payload,
                    "accumulator_tile_ref": c_tile["accumulator_tile_ref"],
                    "accumulator_view_ref": c_tile["accumulator_view_ref"],
                    "template_policy": (
                        "legacy_gemm_compat_accumulator_cal_envelope;"
                        "emitted_once_before_k_stream_repeat"
                    ),
                },
            )
            for k_block in range(k_blocks):
                a_tile = _make_a_tile_descriptor(
                    a_value,
                    stream.processor,
                    m_tile,
                    k_block,
                    tile_m,
                    tile_k,
                )
                b_tile = _make_b_tile_descriptor(
                    b_value,
                    stream.processor,
                    n_tile,
                    k_block,
                    tile_n,
                    tile_k,
                )
                row_bundle = self._ensure_collective_bundle(
                    bundle_id=_row_bundle_id(
                        action.source_chip_op,
                        launch_group_id,
                        task_id,
                        k_block,
                        row_index,
                        m_tile,
                        a_tile["global_m"]["start"],
                    ),
                    collective_kind="row_broadcast",
                    participants=tuple(row_participants),
                    logical_source=str(a_tile["tile_ref"]),
                    input_refs=(str(a_tile["tile_ref"]),),
                    output_refs=(str(a_tile["tile_ref"]),),
                    attrs={
                        "source_action": action.id,
                        "source_chip_op": action.source_chip_op,
                        "task_assignment": task_assignment_payload,
                        "instance_id": k_block,
                        "processor_axis": "row",
                        "row": row_index,
                    },
                )
                col_bundle = self._ensure_collective_bundle(
                    bundle_id=_col_bundle_id(
                        action.source_chip_op,
                        launch_group_id,
                        task_id,
                        k_block,
                        col_index,
                        n_tile,
                        b_tile["global_n"]["start"],
                    ),
                    collective_kind="column_broadcast",
                    participants=tuple(col_participants),
                    logical_source=str(b_tile["tile_ref"]),
                    input_refs=(str(b_tile["tile_ref"]),),
                    output_refs=(str(b_tile["tile_ref"]),),
                    attrs={
                        "source_action": action.id,
                        "source_chip_op": action.source_chip_op,
                        "task_assignment": task_assignment_payload,
                        "instance_id": k_block,
                        "processor_axis": "col",
                        "col": col_index,
                    },
                )
                consumer = f"{stream.processor}:{action.id}:wave{wave_id}:k{k_block}"
                _append_unique(row_bundle.consumers, consumer)
                _append_unique(col_bundle.consumers, consumer)
                row_bundle_refs.append(row_bundle.bundle_id)
                col_bundle_refs.append(col_bundle.bundle_id)
                member_value_ref = _tile_member_ref(str(c_tile["owner_tile_ref"]), k_block)
                compute_action_id = _tile_compute_action_id(
                    stream.processor,
                    action.id,
                    wave_id,
                    k_block,
                )
                row_route_prefix = self._ensure_tile_route_prefix(
                        logical_route=self._logical_route_for(
                            action=action,
                            operand_role="A",
                            group_key=self._route_group_key(
                                task_id=stream.task_id,
                                fabric_scope="row",
                                group_index=row_index,
                            ),
                        ),
                    bundle=row_bundle,
                    source_tile_ref=str(a_tile["tile_ref"]),
                    consumer_processor=stream.processor,
                    compute_action_id=compute_action_id,
                    k_index=k_block,
                    tile_coord={
                        "m_tile": m_tile,
                        "n_tile": n_tile,
                        "k_block": k_block,
                    },
                )
                col_route_prefix = self._ensure_tile_route_prefix(
                        logical_route=self._logical_route_for(
                            action=action,
                            operand_role="B",
                            group_key=self._route_group_key(
                                task_id=stream.task_id,
                                fabric_scope="column",
                                group_index=col_index,
                            ),
                        ),
                    bundle=col_bundle,
                    source_tile_ref=str(b_tile["tile_ref"]),
                    consumer_processor=stream.processor,
                    compute_action_id=compute_action_id,
                    k_index=k_block,
                    tile_coord={
                        "m_tile": m_tile,
                        "n_tile": n_tile,
                        "k_block": k_block,
                    },
                )
                _append_unique(phase_route_prefix_refs, row_route_prefix["endpoint_action_id"])
                _append_unique(phase_route_prefix_refs, col_route_prefix["endpoint_action_id"])
                self._ensure_tile_compute_action(
                    action_id=compute_action_id,
                    processor=stream.processor,
                    phase_id=f"{action.id}:wave{wave_id}",
                    source_action=action.id,
                    source_chip_op=action.source_chip_op,
                    input_refs=(
                        row_route_prefix["endpoint_action_id"],
                        col_route_prefix["endpoint_action_id"],
                    ),
                    output_refs=(member_value_ref,),
                    depends_on=tuple(
                        ref
                        for ref in (
                            row_route_prefix["endpoint_action_id"],
                            col_route_prefix["endpoint_action_id"],
                            prepare_action_id if k_block == 0 else None,
                            previous_compute_action_id,
                        )
                        if ref is not None
                    ),
                    attrs={
                        "compute_kind": tile_profile.k_update_kind,
                        "task_assignment": task_assignment_payload,
                        "k_index": k_block,
                        "a_tile": a_tile,
                        "b_tile": b_tile,
                        "member_value_ref": member_value_ref,
                        "accumulator_view_ref": c_tile["accumulator_view_ref"],
                        "route_prefix_action_ids": [
                            row_route_prefix["endpoint_action_id"],
                            col_route_prefix["endpoint_action_id"],
                        ],
                    },
                )
                if previous_compute_action_id is not None:
                    self._ensure_tile_dependency(
                        dependency_kind="tile_compute_accumulator_chain",
                        src=previous_compute_action_id,
                        dst=compute_action_id,
                        attrs={
                            "processor": stream.processor,
                            "phase_id": f"{action.id}:wave{wave_id}",
                            "previous_k": k_block - 1,
                            "current_k": k_block,
                            "accumulator_view_ref": c_tile["accumulator_view_ref"],
                        },
                    )
                elif k_block == 0:
                    self._ensure_tile_dependency(
                        dependency_kind="tile_accumulator_prepare_before_compute",
                        src=prepare_action_id,
                        dst=compute_action_id,
                        attrs={
                            "processor": stream.processor,
                            "phase_id": phase_id,
                            "accumulator_view_ref": c_tile["accumulator_view_ref"],
                            "runtime_shape": "prepare_subtask_before_k_stream_repeat",
                        },
                    )
                previous_compute_action_id = compute_action_id
                k_block_updates.append(
                    {
                        "instance_id": k_block,
                        "tile_compute_action_id": compute_action_id,
                        "a_tile": a_tile,
                        "b_tile": b_tile,
                        "owner_tile_ref": c_tile["owner_tile_ref"],
                        "member_value_ref": member_value_ref,
                        "member_kind": tile_profile.k_update_kind,
                        "accumulator_view_ref": c_tile["accumulator_view_ref"],
                        "c_accumulator_tile_ref": c_tile["accumulator_tile_ref"],
                        "row_broadcast_bundle_id": row_bundle.bundle_id,
                        "column_broadcast_bundle_id": col_bundle.bundle_id,
                        "route_prefix_actions": [
                            row_route_prefix,
                            col_route_prefix,
                        ],
                        "produces": {
                            "value_kind": "tile_fragment",
                            "member_value_ref": member_value_ref,
                            "owner_tile_ref": c_tile["owner_tile_ref"],
                            "view_ref": c_tile["accumulator_view_ref"],
                            "storage_hint": "tile_scope_member_value",
                        },
                        "dummy_mask": {
                            "a_uses_padding": bool(a_tile["uses_padding"]),
                            "b_uses_padding": bool(b_tile["uses_padding"]),
                            "padding_policy": "pre_zeroed_tile_region",
                        },
                    }
                )

            if previous_compute_action_id is not None:
                _append_unique(
                    self.value_final_tile_actions.setdefault(final_output_ref, []),
                    {
                        "tile_action_id": previous_compute_action_id,
                        "tile_ref": c_tile["output_tile_ref"],
                        "tile_scope_ref": c_tile["tile_scope_ref"],
                        "processor": stream.processor,
                        "phase_id": f"{action.id}:wave{wave_id}",
                        "task_assignment": task_assignment_payload,
                        "m_tile": m_tile,
                        "n_tile": n_tile,
                        "local_m": c_tile["local_m"],
                        "local_n": c_tile["local_n"],
                        "global_m": c_tile["global_m"],
                        "global_n": c_tile["global_n"],
                        "uses_padding": c_tile["uses_padding"],
                        "padding_policy": c_tile["padding_policy"],
                    },
                )

            loop_id = _tile_loop_id(stream.processor, phase_id)
            self.tile_loop_regions[loop_id] = self._make_gemm_tile_loop_region(
                loop_id=loop_id,
                processor=stream.processor,
                phase_id=phase_id,
                action=action,
                c_tile=c_tile,
                final_output_ref=final_output_ref,
                k_block_updates=k_block_updates,
                post_ops=post_ops,
                task_assignment=task_assignment,
            )

            phases.append(
                TilePhase(
                    phase_id=phase_id,
                    phase_kind=tile_profile.phase_kind,
                    processor=stream.processor,
                    source_action=action.id,
                    source_chip_op=action.source_chip_op,
                    input_refs=action.inputs,
                    output_refs=(final_output_ref,),
                    local_ops=(
                        tile_profile.local_prepare_op,
                        tile_profile.local_k_stream_op,
                        *tuple(str(op["op"]) for op in post_ops),
                        tile_profile.local_store_op,
                    ),
                    collective_refs=tuple([*row_bundle_refs, *col_bundle_refs]),
                    route_prefix_refs=tuple(phase_route_prefix_refs),
                    payload={
                        "template_kind": tile_profile.template_kind,
                        "producer_action": action.id,
                        "producer_chip_op": action.source_chip_op,
                        "work_index": work_index,
                        "work_coord": work_coord,
                        "work_axis_order": list(work_axis_order),
                        "task_assignment": task_assignment_payload,
                        "accumulator_prepare_action_id": prepare_action_id,
                        "tile_loop_region_id": loop_id,
                        "fused_actions": [str(op["source_action"]) for op in post_ops],
                        "fused_chip_ops": [str(op["source_chip_op"]) for op in post_ops],
                        "c_tile_wave": c_tile,
                        "tile_scope": {
                            "owner_tile_ref": c_tile["owner_tile_ref"],
                            "accumulator_view_ref": c_tile["accumulator_view_ref"],
                            "output_view_ref": c_tile["output_view_ref"],
                            "member_refs": [
                                str(update["member_value_ref"])
                                for update in k_block_updates
                            ],
                            "view_policy": "gemm_k_members_reassembled_as_accumulator_tile_view",
                        },
                        "k_block_updates": k_block_updates,
                        "row_broadcast_bundle_refs": row_bundle_refs,
                        "column_broadcast_bundle_refs": col_bundle_refs,
                        "post_ops": post_ops,
                        "tile_sizes": dict(self.tile_sizes),
                        "subtasks": _gemm_subtasks(k_blocks, final_value.logical_tensor_id),
                    },
                )
            )
        return phases

    def _make_gemm_tile_loop_region(
        self,
        *,
        loop_id: str,
        processor: str,
        phase_id: str,
        action: ProcessorLogicalAction,
        c_tile: dict[str, Any],
        final_output_ref: str,
        k_block_updates: list[dict[str, Any]],
        post_ops: list[dict[str, Any]],
        task_assignment: VendorTaskProjection,
    ) -> TileLoopRegion:
        tile_profile = MATMUL_SPEC.tile_lowering_profile()
        body_instances: list[TileLoopBodyInstance] = []
        loop_variant_refs: list[str] = []
        carried_refs: list[str] = [
            str(c_tile["accumulator_view_ref"]),
            str(c_tile["accumulator_tile_ref"]),
        ]
        for update in k_block_updates:
            route_action_ids = tuple(
                action_id
                for prefix in update["route_prefix_actions"]
                for action_id in prefix["route_action_ids"]
            )
            compute_action_id = str(update["tile_compute_action_id"])
            action_ids = tuple([*route_action_ids, compute_action_id])
            a_tile_ref = str(update["a_tile"]["tile_ref"])
            b_tile_ref = str(update["b_tile"]["tile_ref"])
            _append_unique(loop_variant_refs, a_tile_ref)
            _append_unique(loop_variant_refs, b_tile_ref)
            body_instances.append(
                TileLoopBodyInstance(
                    instance_id=int(update["instance_id"]),
                    iv_bindings={
                        "k": int(update["instance_id"]),
                        "a_tile_ref": a_tile_ref,
                        "b_tile_ref": b_tile_ref,
                        "member_value_ref": str(update["member_value_ref"]),
                    },
                    action_ids=action_ids,
                    route_action_ids=route_action_ids,
                    compute_action_ids=(compute_action_id,),
                    depends_on_previous_instance=int(update["instance_id"]) > 0,
                    attrs={
                        "a_tile": update["a_tile"],
                        "b_tile": update["b_tile"],
                        "row_broadcast_bundle_id": update["row_broadcast_bundle_id"],
                        "column_broadcast_bundle_id": update["column_broadcast_bundle_id"],
                        "accumulator_update_kind": "self_recurrence_along_k",
                    },
                )
            )
        return TileLoopRegion(
            loop_id=loop_id,
            processor=processor,
            source_phase_id=phase_id,
            source_action=action.id,
            source_chip_op=action.source_chip_op,
            loop_axis=tile_profile.loop_axis,
            repeat_count=len(k_block_updates),
            closure_shape=tile_profile.loop_closure_shape,
            fold_policy=tile_profile.loop_fold_policy,
            body_instances=tuple(body_instances),
            carried_refs=tuple(carried_refs),
            captured_refs=(),
            loop_variant_refs=tuple(loop_variant_refs),
            loop_invariant_refs=(),
            grouping={
                "kind": "single_accumulator",
                "group_size": 1,
                "shared_side": None,
                "future_pass": "multi_accumulator_body_grouping",
            },
            attrs={
                "template_kind": tile_profile.template_kind,
                "source_compute_kind": tile_profile.source_compute_kind,
                "final_output_ref": final_output_ref,
                "output_tile_ref": c_tile["output_tile_ref"],
                "post_ops": post_ops,
                "task_assignment": task_assignment.to_payload(),
                "task_planning_policy": task_assignment.policy_name,
                "lowering_status": (
                    "analysis_view_expanded_actions_with_loop_region;"
                    "packing_may_fold_to_repeated_subtask"
                ),
                "loop_body_closure_rule": (
                    "all_loop_variant_visibility_and_compute_actions_are_inside_region"
                ),
            },
        )

    def _lower_generic(
        self,
        stream: LogicalStream,
        action: ProcessorLogicalAction,
    ) -> TilePhase:
        logical_reduce = self._logical_reduce_for_action(action)
        is_reduce = logical_reduce is not None
        phase_kind = "local_reduce_max" if is_reduce else "local_elementwise"
        phase_id = f"{action.id}:local"
        compute_action_id = _generic_tile_compute_action_id(stream.processor, action.id)
        final_tile_dependencies: list[str] = []
        dependency_value_by_parent: dict[str, str] = {}
        for value_id in action.inputs:
            parent_ids = _tile_action_ids(self.value_final_tile_actions.get(value_id), value_id)
            final_tile_dependencies.extend(parent_ids)
            for parent_id in parent_ids:
                dependency_value_by_parent[parent_id] = value_id
        self._ensure_tile_compute_action(
            action_id=compute_action_id,
            processor=stream.processor,
            phase_id=phase_id,
            source_action=action.id,
            source_chip_op=action.source_chip_op,
            input_refs=action.inputs,
            output_refs=action.outputs,
            depends_on=tuple(final_tile_dependencies),
            attrs={
                "compute_kind": "local_reduce_max" if is_reduce else action.op,
                "logical_reduce_edge_id": logical_reduce.id if logical_reduce else None,
                "tile_value_kind": "PE_LOCAL_SCALAR" if is_reduce else "PE_LOCAL_TILE",
                "collective_result_kind": (
                    "REPLICATED_APP_SCALAR" if is_reduce else None
                ),
                "logical_input_refs": list(action.inputs),
                "logical_output_refs": list(action.outputs),
                "attrs": dict(action.attrs),
            },
        )
        for parent in final_tile_dependencies:
            self._ensure_tile_dependency(
                dependency_kind="tile_value_before_compute",
                src=parent,
                dst=compute_action_id,
                value_id=dependency_value_by_parent.get(parent),
                dependency_value_kind="tile_value",
                producer_value_kind="PE_LOCAL_TILE",
                consumer_value_kind="PE_LOCAL_SCALAR" if is_reduce else "PE_LOCAL_TILE",
                attrs={
                    "processor": stream.processor,
                    "phase_id": phase_id,
                    "source_action": action.id,
                    "logical_reduce_edge_id": logical_reduce.id if logical_reduce else None,
                },
            )
        collective_refs: tuple[str, ...] = ()
        if logical_reduce is not None:
            collective_bundle = self._ensure_collective_bundle(
                bundle_id=_tile_collective_reduce_bundle_id(logical_reduce.id),
                collective_kind="all_reduce_max_symbolic",
                participants=logical_reduce.participants,
                logical_source=logical_reduce.id,
                input_refs=logical_reduce.input_value_ids,
                output_refs=logical_reduce.output_value_ids,
                attrs={
                    "logical_reduce_edge_id": logical_reduce.id,
                    "reduce_op": logical_reduce.reduce_op,
                    "identity_value": logical_reduce.identity_value,
                    "source_policy": logical_reduce.source_policy,
                    "visibility_kind": logical_reduce.visibility_kind,
                    "implementation_status": "symbolic_collective_not_physical_route",
                },
            )
            _append_unique(collective_bundle.consumers, compute_action_id)
            collective_refs = (collective_bundle.bundle_id,)
        for output_ref in action.outputs:
            output_value = self._local_value(output_ref)
            output_descriptor = _generic_value_descriptor(output_value, "OUT")
            self.value_final_tile_actions[output_ref] = [
                {
                    "tile_action_id": compute_action_id,
                    "tile_ref": output_descriptor["tile_ref"],
                    "tile_scope_ref": output_descriptor["tile_ref"],
                    "processor": stream.processor,
                    "phase_id": phase_id,
                    "m_tile": 0,
                    "n_tile": 0,
                    "global_offset": list(output_value.global_offset),
                    "local_shape": list(output_value.local_shape),
                    "uses_padding": False,
                    "padding_policy": "single_local_shard_symbolic_store",
                }
            ]
        return TilePhase(
            phase_id=phase_id,
            phase_kind=phase_kind,
            processor=stream.processor,
            source_action=action.id,
            source_chip_op=action.source_chip_op,
            input_refs=action.inputs,
            output_refs=action.outputs,
            local_ops=(action.op,),
            collective_refs=collective_refs,
            payload={
                "producer_action": action.id,
                "producer_chip_op": action.source_chip_op,
                "tile_compute_action_id": compute_action_id,
                "logical_reduce_edge_id": logical_reduce.id if logical_reduce else None,
                "attrs": dict(action.attrs),
                "input_values": [
                    _generic_value_descriptor(self._local_value(value_id), f"IN{index}")
                    for index, value_id in enumerate(action.inputs)
                ],
                "output_values": [
                    _generic_value_descriptor(self._local_value(value_id), f"OUT{index}")
                    for index, value_id in enumerate(action.outputs)
                ],
                "lowering_status": "generic_tile_payload_symbolic",
            },
        )

    def _lower_store(
        self,
        stream: LogicalStream,
        action: ProcessorLogicalAction,
    ) -> TilePhase:
        input_values = [
            _generic_value_descriptor(self._local_value(value_id), f"IN{index}")
            for index, value_id in enumerate(action.inputs)
        ]
        phase_id = f"{action.id}:store"
        final_tile_records: list[dict[str, Any]] = []
        for value_id in action.inputs:
            final_tile_records.extend(
                self.value_final_tile_actions.get(
                    value_id,
                    [
                        {
                            "tile_action_id": value_id,
                            "tile_ref": value_id,
                            "tile_scope_ref": value_id,
                            "processor": stream.processor,
                            "phase_id": phase_id,
                            "m_tile": 0,
                            "n_tile": 0,
                            "uses_padding": False,
                            "padding_policy": "fallback_logical_value_store",
                        }
                    ],
                )
            )
        store_action_ids: list[str] = []
        store_action_records: list[dict[str, Any]] = []
        for store_index, final_tile in enumerate(final_tile_records):
            store_action_id = _tile_store_action_id(stream.processor, action.id, store_index)
            source_tile_action_id = str(final_tile["tile_action_id"])
            self._ensure_tile_store_action(
                action_id=store_action_id,
                processor=stream.processor,
                phase_id=phase_id,
                source_action=action.id,
                source_chip_op=action.source_chip_op,
                input_refs=(source_tile_action_id,),
                output_refs=tuple(
                    str(action.attrs.get("dst_sram_tensor_id"))
                    for _ in action.inputs
                    if action.attrs.get("dst_sram_tensor_id") is not None
                ),
                depends_on=(source_tile_action_id,),
                attrs={
                    "dst_sram_tensor_id": action.attrs.get("dst_sram_tensor_id"),
                    "dst_region": action.attrs.get("dst_region"),
                    "logical_input_refs": list(action.inputs),
                    "source_final_tile": dict(final_tile),
                    "task_assignment": final_tile.get("task_assignment"),
                    "store_index": store_index,
                    "store_kind": "store_sram_tensor",
                    "store_granularity": "one_output_tile",
                },
            )
            store_action_ids.append(store_action_id)
            store_action_records.append(
                {
                    "tile_store_action_id": store_action_id,
                    "source_tile_action_id": source_tile_action_id,
                    "source_tile_ref": final_tile.get("tile_ref", "-"),
                    "store_index": store_index,
                    "tile_coord": {
                        "m_tile": final_tile.get("m_tile", 0),
                        "n_tile": final_tile.get("n_tile", 0),
                    },
                }
            )
        return TilePhase(
            phase_id=phase_id,
            phase_kind="store_sram_tensor",
            processor=stream.processor,
            source_action=action.id,
            source_chip_op=action.source_chip_op,
            input_refs=action.inputs,
            local_ops=("store_sram_tensor",),
            payload={
                "producer_action": action.id,
                "producer_chip_op": action.source_chip_op,
                "tile_store_action_id": store_action_ids[0] if store_action_ids else None,
                "tile_store_action_ids": store_action_ids,
                "tile_store_actions": store_action_records,
                "input_values": input_values,
                "dst_sram_tensor_id": action.attrs.get("dst_sram_tensor_id"),
                "dst_region": action.attrs.get("dst_region"),
                "lowering_status": "store_tile_actions_expanded_per_output_tile",
            },
        )

    def _task_work_axis_order(
        self,
        logical_tensor_id: str,
        *,
        default: tuple[str, ...],
    ) -> tuple[str, ...]:
        if self.task_partition_plan is None:
            return default
        return self.task_partition_plan.work_axis_order_for_tensor(
            logical_tensor_id,
            default,
        )

    def _gemm_task_work_coords(
        self,
        *,
        logical_tensor_id: str,
        stream: LogicalStream,
        m_tiles: int,
        n_tiles: int,
        work_axis_order: tuple[str, ...],
    ) -> list[dict[str, int]]:
        all_coords = [
            {"m_tile": m_tile, "n_tile": n_tile}
            for m_tile in range(m_tiles)
            for n_tile in range(n_tiles)
        ]
        if self.task_partition_plan is None:
            return all_coords
        placement = self.task_partition_plan.placement_for_tensor(logical_tensor_id)
        if placement is None or placement.get("kind") != "task_shard":
            return all_coords

        work_shape = {"m_tile": m_tiles, "n_tile": n_tiles}
        return [
            coord
            for coord in all_coords
            if _linear_work_index(coord, work_shape, work_axis_order) == stream.task_id
        ]

    def _route_group_key(
        self,
        *,
        task_id: int,
        fabric_scope: str,
        group_index: int,
    ) -> str:
        if int(self.processor_program.task_axis_mesh.task_axis_size) <= 1:
            return f"{fabric_scope}:{group_index}"
        return f"task{int(task_id)}:{fabric_scope}:{group_index}"

    def _verify_gemm_task_axis_matches_output_work(
        self,
        *,
        logical_tensor_id: str,
        work_unit_count: int,
    ) -> None:
        if self.task_partition_plan is None:
            return
        placement = self.task_partition_plan.placement_for_tensor(logical_tensor_id)
        if placement is None or placement.get("kind") != "task_shard":
            return
        partition_count = int(
            placement.get("partition_count")
            or self.task_partition_plan.task_axis_size
        )
        if partition_count != int(work_unit_count):
            raise ValueError(
                "current GEMM soft task-axis lowering requires one output-tile "
                "work unit per task-axis rank for each physical processor: "
                f"partition_count={partition_count}, work_unit_count={work_unit_count}. "
                "Use a matching task_axis_size/partition_count, or add an explicit "
                "multi-work-per-task packing strategy before lowering."
            )

    def _ensure_gemm_tile_task_assignment(
        self,
        *,
        source_action: str,
        source_chip_op: str,
        output_logical_tensor_id: str,
        processor: str,
        stream_task_id: int,
        wave_id: int,
        work_index: int,
        work_coord: dict[str, int],
        work_axis_order: tuple[str, ...],
        m_tile: int,
        n_tile: int,
        k_blocks: int,
    ) -> VendorTaskProjection:
        placement = (
            self.task_partition_plan.placement_for_tensor(output_logical_tensor_id)
            if self.task_partition_plan is not None
            else None
        )
        if placement is not None and placement.get("kind") == "task_shard":
            partition_count = int(
                placement.get("partition_count")
                or self.task_partition_plan.task_axis_size
            )
            task_id = int(stream_task_id)
            if task_id < 0 or task_id >= partition_count:
                raise ValueError(
                    "soft processor task_id is outside TaskShard partition_count: "
                    f"task_id={task_id}, partition_count={partition_count}"
                )
            task_axis_assignment = {
                "source": "task_axis_shard",
                "task_axis_rank": task_id,
                "launch_group_id": 0,
                "partition_count": partition_count,
                "task_axis_size": self.task_partition_plan.task_axis_size,
                "placement": dict(placement),
                "work_domain": str(placement.get("work_domain", "task_axis_work")),
                "work_index": int(work_index),
                "work_coord": dict(work_coord),
                "work_axis_order": list(work_axis_order),
            }
        else:
            task_axis_assignment = {
                "source": "legacy_fallback_no_task_axis_shard",
                "task_axis_rank": int(work_index) % self.max_tasks,
                "launch_group_id": int(work_index) // self.max_tasks,
                "partition_count": self.max_tasks,
                "task_axis_size": self.max_tasks,
                "placement": None,
                "work_domain": "legacy_output_wave",
                "work_index": int(work_index),
                "work_coord": dict(work_coord),
                "work_axis_order": list(work_axis_order),
            }
        launch_group_id = int(task_axis_assignment["launch_group_id"])
        task_id = int(task_axis_assignment["task_axis_rank"])
        assignment_id = _tile_task_assignment_id(processor, source_action, wave_id)
        existing = self.vendor_task_projections.get(assignment_id)
        if existing is not None:
            return existing
        assignment = VendorTaskProjection(
            assignment_id=assignment_id,
            source_action=source_action,
            source_chip_op=source_chip_op,
            processor=processor,
            wave_id=wave_id,
            work_index=work_index,
            work_coord=dict(work_coord),
            work_axis_order=tuple(work_axis_order),
            launch_group_id=launch_group_id,
            task_id=task_id,
            task_name=f"task{task_id}",
            m_tile=m_tile,
            n_tile=n_tile,
            k_blocks=k_blocks,
            policy_name="soft_task_axis_legacy_gemm_output_work_projection",
            max_vendor_tasks=self.max_tasks,
            assignment_source=str(task_axis_assignment["source"]),
            task_axis_rank=int(task_axis_assignment["task_axis_rank"]),
            task_axis_partition_count=int(task_axis_assignment["partition_count"]),
            task_axis_size=int(task_axis_assignment["task_axis_size"]),
            task_axis_work_domain=str(task_axis_assignment["work_domain"]),
            task_axis_placement=task_axis_assignment["placement"],
            subtask_role_map={
                "accumulator_prepare": "subtask0",
                "k_stream": "subtask1",
                "finalize_store": "subtask2",
            },
            subtask_plan=_gemm_subtask_plan(k_blocks),
        )
        self.vendor_task_projections[assignment_id] = assignment
        return assignment

    def _vendor_task_projection(self) -> dict[str, Any]:
        launch_group_accumulator: dict[int, dict[str, Any]] = {}
        task_plan: dict[str, dict[str, Any]] = {}
        for projection in sorted(
            self.vendor_task_projections.values(),
            key=lambda item: (item.launch_group_id, item.task_id),
        ):
            group = launch_group_accumulator.setdefault(
                projection.launch_group_id,
                {
                    "launch_group_id": projection.launch_group_id,
                    "work_index_start": (
                        projection.launch_group_id
                        * projection.task_axis_partition_count
                    ),
                    "work_index_end_exclusive": (
                        (projection.launch_group_id + 1)
                        * projection.task_axis_partition_count
                    ),
                    "legacy_wave_alias": "work_index",
                    "task_axis_partition_count": projection.task_axis_partition_count,
                    "task_ids": set(),
                },
            )
            group["task_ids"].add(projection.task_id)
            task_plan.setdefault(
                f"launch_group_{projection.launch_group_id}:task_{projection.task_id}",
                {
                    "launch_group_id": projection.launch_group_id,
                    "task_id": projection.task_id,
                    "subtasks": _gemm_subtasks(
                        projection.k_blocks,
                        output_tensor="-",
                    ),
                    "tile_sizes": dict(self.tile_sizes),
                },
            )
        launch_group_report = {
            str(group_id): {
                **group,
                "task_ids": sorted(group["task_ids"]),
            }
            for group_id, group in sorted(launch_group_accumulator.items())
        }
        launch_groups = {
            f"launch_group_{group_id}": dict(group)
            for group_id, group in sorted(
                launch_group_report.items(),
                key=lambda item: int(item[0]),
            )
        }
        report = {
            "schema_version": 2,
            "ir": "vendor_task_projection_report",
            "chip": self.processor_program.chip,
            "source_program": self.processor_program.source_program,
            "source_of_truth": "restricted_soft_task_axis",
            "compatibility_note": (
                "keeps legacy processor_task_plan output key during migration"
            ),
            "policy": {
                "policy_name": "soft_task_axis_legacy_gemm_output_work_projection",
                "max_vendor_tasks": self.max_tasks,
                "task_axis": "soft_task_axis",
                "work_index_source": "TaskShard.work_axis_order",
                "legacy_wave_alias": "work_index",
                "overflow_policy": "explicit_task_shard_requires_one_work_unit_per_task",
                "supports_multi_launch": False,
            },
            "launch_groups": launch_group_report,
            "assignments": {
                assignment_id: assignment.to_plan()
                for assignment_id, assignment in sorted(
                    self.vendor_task_projections.items()
                )
            },
            "validation": {
                "all_task_ids_within_vendor_limit": all(
                    assignment.task_id < self.max_tasks
                    for assignment in self.vendor_task_projections.values()
                ),
                "single_launch_group_supported": len(launch_group_report) <= 1,
            },
            "totals": {
                "assignment_count": len(self.vendor_task_projections),
                "launch_group_count": len(launch_group_report),
            },
        }
        return {
            "schema_version": 1,
            "ir": "vendor_task_projection",
            "boundary": "dfu3500_vendor_task_rows_not_tile_ir_semantics",
            "processor_task_plan": report,
            "launch_groups": launch_groups,
            "task_plan": task_plan,
            "totals": {
                "assignment_count": len(report["assignments"]),
                "launch_group_count": len(launch_groups),
                "task_plan_count": len(task_plan),
            },
        }

    def _ensure_collective_bundle(
        self,
        *,
        bundle_id: str,
        collective_kind: str,
        participants: tuple[str, ...],
        logical_source: str,
        input_refs: tuple[str, ...],
        output_refs: tuple[str, ...],
        attrs: dict[str, Any],
    ) -> TileCollectiveBundle:
        if bundle_id not in self.collective_bundles:
            self.collective_bundles[bundle_id] = TileCollectiveBundle(
                bundle_id=bundle_id,
                collective_kind=collective_kind,
                participants=participants,
                input_refs=input_refs,
                output_refs=output_refs,
                logical_source=logical_source,
                attrs=attrs,
            )
        return self.collective_bundles[bundle_id]

    def _logical_route_for(
        self,
        *,
        action: ProcessorLogicalAction,
        operand_role: str,
        group_key: str,
    ) -> LogicalRouteEdge:
        matches = [
            route
            for route in self.processor_program.logical_routes.values()
            if route.consumer_chip_op == action.source_chip_op
            and route.operand_role == operand_role
            and route.group_key == group_key
            and action.id in route.consumer_action_ids
        ]
        if len(matches) != 1:
            raise ValueError(
                f"expected one logical route for {action.id} {operand_role} {group_key}, "
                f"found {len(matches)}"
            )
        return matches[0]

    def _logical_reduce_for_action(
        self,
        action: ProcessorLogicalAction,
    ) -> LogicalReduceEdge | None:
        matches = [
            reduce_edge
            for reduce_edge in self.processor_program.logical_reduces.values()
            if reduce_edge.source_chip_op == action.source_chip_op
            and action.id in reduce_edge.producer_action_ids
        ]
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError(
                f"expected at most one logical reduce for {action.id}, "
                f"found {len(matches)}"
            )
        return matches[0]

    def _logical_reduce_for_value(self, value_id: str) -> LogicalReduceEdge | None:
        matches = [
            reduce_edge
            for reduce_edge in self.processor_program.logical_reduces.values()
            if reduce_edge.output_logical_tensor_id == value_id
        ]
        if not matches:
            return None
        if len(matches) != 1:
            raise ValueError(
                f"expected at most one logical reduce for value {value_id}, "
                f"found {len(matches)}"
            )
        return matches[0]

    def _ensure_tile_route_prefix(
        self,
        *,
        logical_route: LogicalRouteEdge,
        bundle: TileCollectiveBundle,
        source_tile_ref: str,
        consumer_processor: str,
        compute_action_id: str,
        k_index: int,
        tile_coord: dict[str, int],
    ) -> dict[str, Any]:
        tile_route_group_id = _tile_route_group_id(bundle.bundle_id)
        step_action_ids: list[str] = []

        for step in logical_route.route_steps:
            action_id = _tile_route_action_id(tile_route_group_id, step)
            depends_on = tuple(
                source_tile_ref
                if parent == logical_route.source_shard["ref"]
                else _tile_route_action_id(
                    tile_route_group_id,
                    _logical_route_step(logical_route, parent),
                )
                for parent in step.depends_on
            )
            if action_id not in self.tile_route_actions:
                self.tile_route_actions[action_id] = TileRouteAction(
                    id=action_id,
                    tile_route_group_id=tile_route_group_id,
                    logical_route_edge_id=logical_route.id,
                    logical_route_step_id=step.id,
                    bundle_id=bundle.bundle_id,
                    execution_processor=step.src_processor or step.processor,
                    endpoint_processor=step.processor,
                    step_kind=step.step_kind,
                    source_tile_ref=source_tile_ref,
                    produces_endpoint_ref=_tile_visibility_endpoint_ref(
                        tile_route_group_id,
                        step.processor,
                    ),
                    position=step.position,
                    operand_role=logical_route.operand_role,
                    k_index=k_index,
                    src_processor=step.src_processor,
                    dst_processor=step.dst_processor,
                    depends_on=depends_on,
                    attrs={
                        "logical_route_group_key": logical_route.group_key,
                        "logical_visibility_kind": logical_route.visibility_kind,
                        "route_kind": logical_route.route_kind,
                        "task_assignment": bundle.attrs.get("task_assignment"),
                        "edge": step.attrs.get("edge"),
                        "execution_model": "sender_push_copyt",
                        "execution_processor": step.src_processor or step.processor,
                        "endpoint_processor": step.processor,
                        "tile_coord": dict(tile_coord),
                    },
                )
            for parent in depends_on:
                self._ensure_tile_dependency(
                    dependency_kind="tile_route_step_dependency",
                    src=parent,
                    dst=action_id,
                    logical_route_edge_id=logical_route.id,
                    tile_route_group_id=tile_route_group_id,
                    attrs={
                        "bundle_id": bundle.bundle_id,
                        "logical_route_step_id": step.id,
                        "operand_role": logical_route.operand_role,
                        "execution_processor": step.src_processor or step.processor,
                        "endpoint_processor": step.processor,
                        "tile_coord": dict(tile_coord),
                    },
                )
            step_action_ids.append(action_id)

        endpoint_logical_step_id = logical_route.endpoint_by_processor[consumer_processor]
        endpoint_action_id = _tile_route_action_id(
            tile_route_group_id,
            _logical_route_step(logical_route, endpoint_logical_step_id),
        )
        compute_dependency_id = self._ensure_tile_dependency(
            dependency_kind="tile_visibility_endpoint_before_compute",
            src=endpoint_action_id,
            dst=compute_action_id,
            logical_route_edge_id=logical_route.id,
            tile_route_group_id=tile_route_group_id,
            attrs={
                "bundle_id": bundle.bundle_id,
                "consumer_processor": consumer_processor,
                "operand_role": logical_route.operand_role,
                "tile_coord": dict(tile_coord),
            },
        )
        return {
            "operand_role": logical_route.operand_role,
            "logical_route_edge_id": logical_route.id,
            "tile_route_group_id": tile_route_group_id,
            "bundle_id": bundle.bundle_id,
            "source_tile_ref": source_tile_ref,
            "consumer_processor": consumer_processor,
            "endpoint_action_id": endpoint_action_id,
            "compute_dependency_id": compute_dependency_id,
            "route_action_ids": step_action_ids,
            "dependency_policy": "expanded_from_logical_route_steps_path_propagation",
        }

    def _ensure_tile_compute_action(
        self,
        *,
        action_id: str,
        processor: str,
        phase_id: str,
        source_action: str,
        source_chip_op: str,
        input_refs: tuple[str, ...],
        output_refs: tuple[str, ...],
        depends_on: tuple[str, ...],
        attrs: dict[str, Any],
    ) -> str:
        if action_id not in self.tile_compute_actions:
            self.tile_compute_actions[action_id] = TileComputeAction(
                id=action_id,
                processor=processor,
                phase_id=phase_id,
                source_action=source_action,
                source_chip_op=source_chip_op,
                compute_kind=str(attrs.get("compute_kind", "tile_compute")),
                input_refs=input_refs,
                output_refs=output_refs,
                depends_on=depends_on,
                attrs=attrs,
            )
        return action_id

    def _ensure_tile_store_action(
        self,
        *,
        action_id: str,
        processor: str,
        phase_id: str,
        source_action: str,
        source_chip_op: str,
        input_refs: tuple[str, ...],
        output_refs: tuple[str, ...],
        depends_on: tuple[str, ...],
        attrs: dict[str, Any],
    ) -> str:
        if action_id not in self.tile_store_actions:
            self.tile_store_actions[action_id] = TileStoreAction(
                id=action_id,
                processor=processor,
                phase_id=phase_id,
                source_action=source_action,
                source_chip_op=source_chip_op,
                input_refs=input_refs,
                output_refs=output_refs,
                depends_on=depends_on,
                attrs=attrs,
            )
        for parent in depends_on:
            self._ensure_tile_dependency(
                dependency_kind="tile_value_before_store",
                src=parent,
                dst=action_id,
                attrs={
                    "processor": processor,
                    "phase_id": phase_id,
                    "source_action": source_action,
                },
            )
        return action_id

    def _ensure_tile_dependency(
        self,
        *,
        dependency_kind: str,
        src: str,
        dst: str,
        logical_route_edge_id: str | None = None,
        tile_route_group_id: str | None = None,
        value_id: str | None = None,
        dependency_value_kind: TileDependencyValueKind | None = None,
        producer_value_kind: TileValueKind | None = None,
        consumer_value_kind: TileValueKind | None = None,
        crosses_app_boundary: bool = False,
        attrs: dict[str, Any] | None = None,
    ) -> str:
        dependency_id = _tile_dependency_id(dependency_kind, src, dst)
        if dependency_id not in self.tile_dependencies:
            self.tile_dependencies[dependency_id] = TileDependency(
                id=dependency_id,
                dependency_kind=dependency_kind,
                src=src,
                dst=dst,
                logical_route_edge_id=logical_route_edge_id,
                tile_route_group_id=tile_route_group_id,
                value_id=value_id,
                dependency_value_kind=dependency_value_kind,
                producer_value_kind=producer_value_kind,
                consumer_value_kind=consumer_value_kind,
                crosses_app_boundary=crosses_app_boundary,
                attrs=attrs or {},
            )
        return dependency_id

    def _build_tile_micro_blocks(self) -> None:
        action_memberships = self._action_loop_memberships()

        for action in sorted(self.tile_route_actions.values(), key=lambda row: row.id):
            memberships = action_memberships.get(action.id, [])
            primary = memberships[0] if len(memberships) == 1 else None
            bundle_attrs = self.collective_bundles[action.bundle_id].attrs
            visibility_ref_id = action.produces_endpoint_ref
            self.tile_visibility_refs.setdefault(
                visibility_ref_id,
                TileVisibilityRef(
                    ref_id=visibility_ref_id,
                    tensor_ref=action.source_tile_ref,
                    producer_action_id=action.id,
                    endpoint_processor=action.endpoint_processor,
                    source_processor=action.execution_processor,
                    loop_region_id=primary["loop_region_id"] if primary else None,
                    loop_instance_id=primary["loop_instance_id"] if primary else None,
                    attrs={
                        "operand_role": action.operand_role,
                        "tile_route_group_id": action.tile_route_group_id,
                        "memberships": memberships,
                        "visibility_model": "sender_push_route_output_token",
                    },
                ),
            )
            self._add_tile_micro_block(
                TileMicroBlock(
                    block_id=_tile_micro_block_id("route", action.id),
                    processor=action.execution_processor,
                    block_kind=_route_micro_block_kind(action),
                    source_phase_id=None,
                    loop_region_id=primary["loop_region_id"] if primary else None,
                    loop_instance_id=primary["loop_instance_id"] if primary else None,
                    loop_axis=primary["loop_axis"] if primary else None,
                    fold_policy=primary["fold_policy"] if primary else None,
                    action_ids=(action.id,),
                    route_action_ids=(action.id,),
                    output_visibility_refs=(visibility_ref_id,),
                    input_refs=action.depends_on,
                    output_refs=(visibility_ref_id,),
                    attrs={
                        "memberships": memberships,
                        "operand_role": action.operand_role,
                        "task_assignment": bundle_attrs.get("task_assignment"),
                        "k_index": action.k_index,
                        "position": action.position,
                        "execution_processor": action.execution_processor,
                        "endpoint_processor": action.endpoint_processor,
                        "tile_coord": dict(action.attrs.get("tile_coord", {})),
                    },
                ),
            )

        for action in sorted(self.tile_compute_actions.values(), key=lambda row: row.id):
            memberships = action_memberships.get(action.id, [])
            primary = memberships[0] if memberships else None
            input_visibility_refs = tuple(
                self.tile_route_actions[ref].produces_endpoint_ref
                if ref in self.tile_route_actions
                else ref
                for ref in action.input_refs
            )
            self._add_tile_micro_block(
                TileMicroBlock(
                    block_id=_tile_micro_block_id("compute", action.id),
                    processor=action.processor,
                    block_kind=_compute_micro_block_kind(action.compute_kind),
                    source_phase_id=action.phase_id,
                    loop_region_id=primary["loop_region_id"] if primary else None,
                    loop_instance_id=primary["loop_instance_id"] if primary else None,
                    loop_axis=primary["loop_axis"] if primary else None,
                    fold_policy=primary["fold_policy"] if primary else None,
                    action_ids=(action.id,),
                    compute_action_ids=(action.id,),
                    input_visibility_refs=input_visibility_refs,
                    input_value_refs=tuple(action.depends_on),
                    output_value_refs=action.output_refs,
                    input_refs=action.input_refs,
                    output_refs=action.output_refs,
                    attrs={
                        "memberships": memberships,
                        "compute_kind": action.compute_kind,
                        "compute_attrs": dict(action.attrs.get("attrs", {})),
                        "task_assignment": action.attrs.get("task_assignment"),
                        "k_index": action.attrs.get("k_index"),
                        "micro_block_policy": "one_compute_action_per_block_mvp",
                    },
                ),
            )

        for action in sorted(self.tile_store_actions.values(), key=lambda row: row.id):
            memberships = action_memberships.get(action.id, [])
            primary = memberships[0] if memberships else None
            self._add_tile_micro_block(
                TileMicroBlock(
                    block_id=_tile_micro_block_id("store", action.id),
                    processor=action.processor,
                    block_kind="tile_store",
                    source_phase_id=action.phase_id,
                    loop_region_id=primary["loop_region_id"] if primary else None,
                    loop_instance_id=primary["loop_instance_id"] if primary else None,
                    loop_axis=primary["loop_axis"] if primary else None,
                    fold_policy=primary["fold_policy"] if primary else None,
                    action_ids=(action.id,),
                    store_action_ids=(action.id,),
                    input_value_refs=action.input_refs,
                    output_value_refs=action.output_refs,
                    input_refs=action.input_refs,
                    output_refs=action.output_refs,
                    attrs={
                        "memberships": memberships,
                        "task_assignment": action.attrs.get("task_assignment"),
                        "store_granularity": action.attrs.get("store_granularity"),
                    },
                ),
            )

        for action in sorted(self.tile_app_storage_actions.values(), key=lambda row: row.id):
            self._add_tile_micro_block(
                TileMicroBlock(
                    block_id=_tile_micro_block_id("app_storage", action.id),
                    processor=action.processor,
                    block_kind=action.action_kind,
                    source_phase_id=None,
                    action_ids=(action.id,),
                    input_value_refs=action.input_refs,
                    output_value_refs=action.output_refs,
                    input_refs=action.input_refs,
                    output_refs=action.output_refs,
                    attrs={
                        "app_storage_edge_id": action.app_storage_edge_id,
                        "storage_id": action.storage_id,
                        "value_id": action.value_id,
                        "source_app_id": action.source_app_id,
                        "consumer_app_id": action.consumer_app_id,
                        "implementation_status": action.attrs.get("implementation_status"),
                        "materialization_kind": action.attrs.get("materialization_kind"),
                    },
                ),
            )

        self._attach_micro_blocks_to_loop_regions()
        self._build_tile_block_dependencies()

    def _add_tile_micro_block(self, block: TileMicroBlock) -> None:
        self.tile_micro_blocks[block.block_id] = block
        for action_id in block.action_ids:
            self.action_to_micro_block[action_id] = block.block_id

    def _attach_micro_blocks_to_loop_regions(self) -> None:
        updated_regions: dict[str, TileLoopRegion] = {}
        for loop_id, loop in self.tile_loop_regions.items():
            updated_instances: list[TileLoopBodyInstance] = []
            for instance in loop.body_instances:
                micro_block_ids: list[str] = []
                by_processor: dict[str, list[str]] = {}
                for action_id in instance.action_ids:
                    block_id = self.action_to_micro_block.get(action_id)
                    if block_id is None:
                        continue
                    _append_unique(micro_block_ids, block_id)
                    block = self.tile_micro_blocks[block_id]
                    by_processor.setdefault(block.processor, [])
                    _append_unique(by_processor[block.processor], block_id)
                updated_instances.append(
                    replace(
                        instance,
                        micro_block_ids=tuple(micro_block_ids),
                        micro_block_ids_by_processor={
                            processor: tuple(block_ids)
                            for processor, block_ids in sorted(by_processor.items())
                        },
                    )
                )
            updated_regions[loop_id] = replace(
                loop,
                body_instances=tuple(updated_instances),
            )
        self.tile_loop_regions = updated_regions

    def _build_tile_block_dependencies(self) -> None:
        grouped: dict[tuple[str, str, str], list[str]] = {}
        for dependency in self.tile_dependencies.values():
            src_block_id = self.action_to_micro_block.get(dependency.src)
            dst_block_id = self.action_to_micro_block.get(dependency.dst)
            if src_block_id is None or dst_block_id is None:
                continue
            dep_kind, vendor_graph_eligible, absorbed_by = self._tile_block_dep_kind(
                dependency,
                src_block_id=src_block_id,
                dst_block_id=dst_block_id,
            )
            grouped.setdefault((src_block_id, dst_block_id, dep_kind), []).append(dependency.id)
            dep_id = _tile_block_dependency_id(src_block_id, dst_block_id, dep_kind)
            self.tile_block_dependencies[dep_id] = TileBlockDependency(
                dep_id=dep_id,
                src_block_id=src_block_id,
                dst_block_id=dst_block_id,
                dep_kind=dep_kind,
                source_tile_dependency_ids=tuple(sorted(grouped[(src_block_id, dst_block_id, dep_kind)])),
                loop_region_id=self._shared_loop_region_id(src_block_id, dst_block_id),
                loop_instance_id=self._shared_loop_instance_id(src_block_id, dst_block_id),
                vendor_graph_eligible=vendor_graph_eligible,
                absorbed_by=absorbed_by,
                attrs={
                    "source_dependency_kinds": sorted(
                        {
                            self.tile_dependencies[source_id].dependency_kind
                            for source_id in grouped[(src_block_id, dst_block_id, dep_kind)]
                        }
                    ),
                    "projection_policy": "tile_action_dependency_to_tile_micro_block_dependency",
                },
            )

    def _tile_block_dep_kind(
        self,
        dependency: TileDependency,
        *,
        src_block_id: str,
        dst_block_id: str,
    ) -> tuple[str, bool, str | None]:
        if src_block_id == dst_block_id:
            return "same_micro_block_internal", False, "same_micro_block"
        if dependency.dependency_kind == "tile_compute_accumulator_chain":
            return "cross_instance_loop_carried", False, "loop_carried_state"
        if dependency.dependency_kind == "tile_value_before_store":
            return "loop_exit_to_store", True, None
        src_block = self.tile_micro_blocks[src_block_id]
        dst_block = self.tile_micro_blocks[dst_block_id]
        if (
            src_block.loop_region_id is not None
            and src_block.loop_region_id == dst_block.loop_region_id
            and src_block.loop_instance_id == dst_block.loop_instance_id
        ):
            return "cross_micro_block_same_instance", True, None
        if src_block.processor != dst_block.processor:
            return "cross_processor", True, None
        return "normal_cross_block", True, None

    def _shared_loop_region_id(self, src_block_id: str, dst_block_id: str) -> str | None:
        src = self.tile_micro_blocks[src_block_id]
        dst = self.tile_micro_blocks[dst_block_id]
        if src.loop_region_id is not None and src.loop_region_id == dst.loop_region_id:
            return src.loop_region_id
        return None

    def _shared_loop_instance_id(self, src_block_id: str, dst_block_id: str) -> int | None:
        src = self.tile_micro_blocks[src_block_id]
        dst = self.tile_micro_blocks[dst_block_id]
        if src.loop_instance_id is not None and src.loop_instance_id == dst.loop_instance_id:
            return src.loop_instance_id
        return None

    def _action_loop_memberships(self) -> dict[str, list[dict[str, Any]]]:
        memberships: dict[str, list[dict[str, Any]]] = {}
        for loop in self.tile_loop_regions.values():
            for instance in loop.body_instances:
                for action_id in instance.action_ids:
                    memberships.setdefault(action_id, []).append(
                        {
                            "loop_region_id": loop.loop_id,
                            "loop_instance_id": instance.instance_id,
                            "loop_axis": loop.loop_axis,
                            "fold_policy": loop.fold_policy,
                            "processor": loop.processor,
                        }
                    )
        return {
            action_id: sorted(
                rows,
                key=lambda row: (
                    str(row["loop_region_id"]),
                    int(row["loop_instance_id"]),
                    str(row["processor"]),
                ),
            )
            for action_id, rows in memberships.items()
        }

    def _build_processor_action_streams(self) -> None:
        streams = {
            processor: ProcessorTileActionStream(processor=processor)
            for processor in self.processor_program.streams
        }
        for action in self.tile_route_actions.values():
            streams.setdefault(
                action.execution_processor,
                ProcessorTileActionStream(processor=action.execution_processor),
            ).actions.append(
                ProcessorTileActionRef(
                    action_id=action.id,
                    action_kind="route",
                    phase_id=None,
                    order_key=(0, action.k_index, action.position),
                )
            )
        for action in self.tile_compute_actions.values():
            streams.setdefault(
                action.processor,
                ProcessorTileActionStream(processor=action.processor),
            ).actions.append(
                ProcessorTileActionRef(
                    action_id=action.id,
                    action_kind="compute",
                    phase_id=action.phase_id,
                    order_key=(1, _k_index_from_attrs(action.attrs), 0),
                )
            )
        for action in self.tile_store_actions.values():
            streams.setdefault(
                action.processor,
                ProcessorTileActionStream(processor=action.processor),
            ).actions.append(
                ProcessorTileActionRef(
                    action_id=action.id,
                    action_kind="store",
                    phase_id=action.phase_id,
                    order_key=(2, _store_index_from_attrs(action.attrs), 0),
                )
            )
        for stream in streams.values():
            stream.actions.sort(key=lambda action: (action.order_key, action.action_id))
        self.processor_action_streams = streams

    def _local_value(self, value_id: str) -> ProcessorLocalValue:
        try:
            return self.processor_program.local_values[value_id]
        except KeyError as exc:
            raise ValueError(f"unknown processor local value id: {value_id}") from exc


def _tile_sizes_from_config(chip_config: dict[str, Any]) -> dict[str, int]:
    default_tile = chip_config.get("default_tile", {})
    return {
        "m": int(default_tile.get("matmul_m", 64)),
        "n": int(default_tile.get("matmul_n", 64)),
        "k": int(default_tile.get("matmul_k", 64)),
    }


def _compute_micro_block_kind(compute_kind: str) -> str:
    for entry in MATMUL_SPEC.tile_lowering_profile().compute_micro_blocks:
        if entry.compute_kind == compute_kind:
            return entry.micro_block_kind
    return "local_compute"


def _make_a_tile_descriptor(
    value: ProcessorLocalValue,
    processor: str,
    m_tile: int,
    k_block: int,
    tile_m: int,
    tile_k: int,
) -> dict[str, Any]:
    local_m = _tile_range(m_tile, tile_m, value.local_shape[0])
    local_k = _tile_range(k_block, tile_k, value.local_shape[1])
    global_m = _offset_range(local_m, value.global_offset[0])
    global_k = _offset_range(local_k, value.global_offset[1])
    tile_ref = _shared_tile_ref(value.logical_tensor_id, "A", global_m["start"], global_k["start"])
    return {
        "tile_ref": tile_ref,
        "logical_tensor_id": value.logical_tensor_id,
        "logical_tensor_name": value.logical_tensor_name,
        "consumer_processor": processor,
        "role": "A",
        "local_m": local_m,
        "local_k": local_k,
        "global_m": global_m,
        "global_k": global_k,
        "uses_padding": local_m["uses_padding"] or local_k["uses_padding"],
        "padding_policy": "pre_zeroed_tile_region",
    }


def _make_b_tile_descriptor(
    value: ProcessorLocalValue,
    processor: str,
    n_tile: int,
    k_block: int,
    tile_n: int,
    tile_k: int,
) -> dict[str, Any]:
    local_k = _tile_range(k_block, tile_k, value.local_shape[0])
    local_n = _tile_range(n_tile, tile_n, value.local_shape[1])
    global_k = _offset_range(local_k, value.global_offset[0])
    global_n = _offset_range(local_n, value.global_offset[1])
    tile_ref = _shared_tile_ref(value.logical_tensor_id, "B", global_k["start"], global_n["start"])
    return {
        "tile_ref": tile_ref,
        "logical_tensor_id": value.logical_tensor_id,
        "logical_tensor_name": value.logical_tensor_name,
        "consumer_processor": processor,
        "role": "B",
        "local_k": local_k,
        "local_n": local_n,
        "global_k": global_k,
        "global_n": global_n,
        "uses_padding": local_k["uses_padding"] or local_n["uses_padding"],
        "padding_policy": "pre_zeroed_tile_region",
    }


def _make_c_tile_descriptor(
    value: ProcessorLocalValue,
    final_value: ProcessorLocalValue,
    processor: str,
    m_tile: int,
    n_tile: int,
    tile_m: int,
    tile_n: int,
) -> dict[str, Any]:
    local_m = _tile_range(m_tile, tile_m, value.local_shape[0])
    local_n = _tile_range(n_tile, tile_n, value.local_shape[1])
    global_m = _offset_range(local_m, value.global_offset[0])
    global_n = _offset_range(local_n, value.global_offset[1])
    owner_tile_ref = _tile_scope_ref(value.logical_tensor_id, processor, global_m["start"], global_n["start"])
    accumulator_tile_ref = _tile_ref(value.logical_tensor_id, processor, "Cacc", global_m["start"], global_n["start"])
    output_tile_ref = _tile_ref(final_value.logical_tensor_id, processor, "Y", global_m["start"], global_n["start"])
    return {
        "owner_tile_ref": owner_tile_ref,
        "tile_scope_ref": owner_tile_ref,
        "accumulator_view_ref": accumulator_tile_ref,
        "output_view_ref": output_tile_ref,
        "accumulator_tile_ref": accumulator_tile_ref,
        "output_tile_ref": output_tile_ref,
        "accumulator_tensor": value.logical_tensor_id,
        "output_tensor": final_value.logical_tensor_id,
        "processor": processor,
        "local_m": local_m,
        "local_n": local_n,
        "global_m": global_m,
        "global_n": global_n,
        "uses_padding": local_m["uses_padding"] or local_n["uses_padding"],
        "padding_policy": "store_mask_for_out_of_bounds_lanes",
    }


def _generic_value_descriptor(value: ProcessorLocalValue, role: str) -> dict[str, Any]:
    first = value.global_offset[0] if len(value.global_offset) >= 1 else 0
    second = value.global_offset[1] if len(value.global_offset) >= 2 else 0
    if len(value.global_shape) == 0:
        first = 0
        second = 0
    return {
        "value_ref": value.id,
        "logical_tensor_id": value.logical_tensor_id,
        "logical_tensor_name": value.logical_tensor_name,
        "processor": value.processor,
        "role": role,
        "tile_ref": _tile_ref(value.logical_tensor_id, value.processor, "V", int(first), int(second)),
        "global_shape": list(value.global_shape),
        "local_shape": list(value.local_shape),
        "global_offset": list(value.global_offset),
        "placements": [repr(placement) for placement in value.placements],
    }


def _gemm_subtasks(k_blocks: int, output_tensor: str) -> list[dict[str, Any]]:
    return [
        {
            "subtask_id": 0,
            "name": "init_c_accumulator",
            "instance_times": 1,
            "c_output_base_required": False,
        },
        {
            "subtask_id": 1,
            "name": "stream_k_blocks",
            "instance_times": k_blocks,
            "instance_table_role": "A/B base addresses vary per K block",
        },
        {
            "subtask_id": 2,
            "name": "apply_post_ops_and_store_c",
            "instance_times": 1,
            "output_tensor": output_tensor,
        },
    ]


def _gemm_subtask_plan(k_blocks: int) -> tuple[TileSubtaskPlan, ...]:
    return (
        TileSubtaskPlan(
            subtask_id=0,
            subtask_name="subtask0",
            role="accumulator_prepare",
            instance_count=1,
        ),
        TileSubtaskPlan(
            subtask_id=1,
            subtask_name="subtask1",
            role="k_stream",
            instance_count=k_blocks,
            repeat_semantics="vendor_instance_repeat_whole_subtask_body",
        ),
        TileSubtaskPlan(
            subtask_id=2,
            subtask_name="subtask2",
            role="finalize_store",
            instance_count=1,
        ),
    )


def _processor_at(
    coordinate: tuple[int, ...],
    programs: dict[str, LogicalStream],
    *,
    task_id: int | None = None,
) -> str:
    for processor, program in programs.items():
        if program.coordinate == coordinate and (
            task_id is None or program.task_id == task_id
        ):
            return processor
    if task_id is None:
        raise ValueError(f"no processor at coordinate {coordinate}")
    raise ValueError(f"no processor at coordinate {coordinate} for task {task_id}")


def _tile_range(tile_idx: int, tile_size: int, limit: int) -> dict[str, Any]:
    start = tile_idx * tile_size
    padded_end = start + tile_size
    end = min(padded_end, limit)
    return {
        "start": start,
        "end": end,
        "padded_end": padded_end,
        "size": max(0, end - start),
        "tile_size": tile_size,
        "uses_padding": padded_end > limit,
    }


def _offset_range(range_desc: dict[str, Any], offset: int) -> dict[str, int]:
    return {
        "start": int(range_desc["start"]) + offset,
        "end": int(range_desc["end"]) + offset,
        "padded_end": int(range_desc["padded_end"]) + offset,
    }


def _tile_ref(tensor_id: str, processor: str, role: str, first: int, second: int) -> str:
    return f"tile:{_sanitize_id_part(tensor_id)}:{_sanitize_id_part(processor)}:{role}:{first}:{second}"


def _tile_scope_ref(tensor_id: str, processor: str, first: int, second: int) -> str:
    return f"tile_scope:{_sanitize_id_part(tensor_id)}:{_sanitize_id_part(processor)}:{first}:{second}"


def _tile_member_ref(owner_tile_ref: str, member_idx: int) -> str:
    return f"{owner_tile_ref}:member:k{member_idx}"


def _tile_compute_action_id(processor: str, action_id: str, wave_id: int, k_block: int) -> str:
    return (
        f"tile_compute:{_sanitize_id_part(processor)}:"
        f"{_sanitize_id_part(action_id)}:wave{wave_id}:k{k_block}"
    )


def _accumulator_prepare_action_id(processor: str, action_id: str, wave_id: int) -> str:
    return (
        f"tile_compute:{_sanitize_id_part(processor)}:"
        f"{_sanitize_id_part(action_id)}:wave{wave_id}:acc_prepare"
    )


def _generic_tile_compute_action_id(processor: str, action_id: str) -> str:
    return f"tile_compute:{_sanitize_id_part(processor)}:{_sanitize_id_part(action_id)}:local"


def _tile_store_action_id(processor: str, action_id: str, store_index: int) -> str:
    return (
        f"tile_store:{_sanitize_id_part(processor)}:"
        f"{_sanitize_id_part(action_id)}:tile{store_index}"
    )


def _tile_app_storage_action_id(
    action_kind: str,
    edge_id: str,
    processor: str,
    *,
    consumer_app_id: int | None = None,
) -> str:
    suffix = "" if consumer_app_id is None else f":app{consumer_app_id}"
    return (
        f"tile_app_storage:{_sanitize_id_part(action_kind)}:"
        f"{_sanitize_id_part(edge_id)}:"
        f"{_sanitize_id_part(processor)}{suffix}"
    )


def _tile_app_storage_loaded_ref(storage_id: str, processor: str) -> str:
    return (
        f"app_storage_loaded:{_sanitize_id_part(storage_id)}:"
        f"{_sanitize_id_part(processor)}"
    )


def _app_storage_region_nbytes(region: dict[str, Any]) -> int:
    shape = region.get("shape", ())
    dims = list(shape) if isinstance(shape, (list, tuple)) else []
    element_count = 1
    for dim in dims:
        element_count *= int(dim)
    return element_count * _dtype_nbytes(str(region.get("dtype")))


def _dtype_nbytes(dtype: str) -> int:
    dtype_sizes = {
        "fp32": 4,
        "float32": 4,
        "f32": 4,
        "fp16": 2,
        "float16": 2,
        "f16": 2,
        "bf16": 2,
        "int32": 4,
        "i32": 4,
        "uint32": 4,
        "u32": 4,
        "int16": 2,
        "i16": 2,
        "uint16": 2,
        "u16": 2,
        "int8": 1,
        "i8": 1,
        "uint8": 1,
        "u8": 1,
    }
    if dtype not in dtype_sizes:
        raise ValueError(f"unsupported app storage dtype for size report: {dtype}")
    return dtype_sizes[dtype]


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    return str(value)


def _optional_int(value: object) -> int | None:
    if value is None:
        return None
    return int(value)


def _tile_route_group_id(bundle_id: str) -> str:
    return f"tile_route:{_sanitize_id_part(bundle_id)}"


def _tile_collective_reduce_bundle_id(logical_reduce_id: str) -> str:
    return f"tile_collective_reduce:{_sanitize_id_part(logical_reduce_id)}"


def _tile_route_action_id(tile_route_group_id: str, step: LogicalRouteStep) -> str:
    return (
        f"{tile_route_group_id}:"
        f"{_sanitize_id_part(step.step_kind)}:"
        f"{step.position}:"
        f"{_sanitize_id_part(step.processor)}"
    )


def _tile_micro_block_id(kind: str, action_id: str) -> str:
    return f"tile_micro_block:{kind}:{_sanitize_id_part(action_id)}"


def _tile_block_dependency_id(src_block_id: str, dst_block_id: str, dep_kind: str) -> str:
    return (
        f"tile_block_dependency:{_sanitize_id_part(dep_kind)}:"
        f"{_sanitize_id_part(src_block_id)}:"
        f"{_sanitize_id_part(dst_block_id)}"
    )


def _route_micro_block_kind(action: TileRouteAction) -> str:
    if action.position == 0:
        return "route_source_materialize"
    return "route_forward"


def _tile_loop_id(processor: str, phase_id: str) -> str:
    return f"tile_loop:{_sanitize_id_part(processor)}:{_sanitize_id_part(phase_id)}"


def _phase_program_item(phase: TilePhase, *, order_index: int) -> TileProgramItemRef:
    return TileProgramItemRef(
        item_id=f"item:{phase.phase_id}",
        item_kind="tile_phase",
        ref_id=phase.phase_id,
        source_action=phase.source_action,
        order_key=(
            int(phase.payload.get("virtual_work_id", order_index)),
            order_index,
        ),
        attrs={
            "phase_kind": phase.phase_kind,
            "source_chip_op": phase.source_chip_op,
        },
    )


def _tile_visibility_endpoint_ref(tile_route_group_id: str, processor: str) -> str:
    return f"{tile_route_group_id}:endpoint:{_sanitize_id_part(processor)}"


def _tile_dependency_id(dependency_kind: str, src: str, dst: str) -> str:
    return (
        f"tile_dep:{_sanitize_id_part(dependency_kind)}:"
        f"{_sanitize_id_part(src)}:"
        f"{_sanitize_id_part(dst)}"
    )


def _logical_route_step(logical_route: LogicalRouteEdge, step_id: str) -> LogicalRouteStep:
    for step in logical_route.route_steps:
        if step.id == step_id:
            return step
    raise ValueError(f"unknown logical route step {step_id} in {logical_route.id}")


def _k_index_from_attrs(attrs: dict[str, Any]) -> int:
    try:
        return int(attrs.get("k_index", 0))
    except (TypeError, ValueError):
        return 0


def _store_index_from_attrs(attrs: dict[str, Any]) -> int:
    try:
        return int(attrs.get("store_index", 0))
    except (TypeError, ValueError):
        return 0


def _tile_action_ids(records: list[dict[str, Any]] | None, fallback: str) -> list[str]:
    if not records:
        return [fallback]
    return [str(record.get("tile_action_id", fallback)) for record in records]


def _shared_tile_ref(tensor_id: str, role: str, first: int, second: int) -> str:
    return f"tile:{_sanitize_id_part(tensor_id)}:{role}:{first}:{second}"


def _row_bundle_id(
    source_chip_op: str,
    launch_group_id: int,
    task_id: int,
    k_block: int,
    row: int,
    m_tile: int,
    global_m_start: object,
) -> str:
    return (
        f"bundle:{_sanitize_id_part(source_chip_op)}:"
        f"lg{launch_group_id}:task{task_id}:k{k_block}:row{row}:"
        f"A:m{m_tile}:gm{global_m_start}"
    )


def _col_bundle_id(
    source_chip_op: str,
    launch_group_id: int,
    task_id: int,
    k_block: int,
    col: int,
    n_tile: int,
    global_n_start: object,
) -> str:
    return (
        f"bundle:{_sanitize_id_part(source_chip_op)}:"
        f"lg{launch_group_id}:task{task_id}:k{k_block}:col{col}:"
        f"B:n{n_tile}:gn{global_n_start}"
    )


def _append_unique(items: list[str], item: str) -> None:
    if item not in items:
        items.append(item)


def _ceildiv(value: int, divisor: int) -> int:
    return (value + divisor - 1) // divisor


def _linear_work_index(
    coord: dict[str, int],
    shape: dict[str, int],
    axis_order: tuple[str, ...],
) -> int:
    missing = [axis for axis in axis_order if axis not in coord or axis not in shape]
    if missing:
        raise ValueError(f"work_axis_order references unknown axis: {missing}")
    index = 0
    for axis in axis_order:
        extent = int(shape[axis])
        axis_index = int(coord[axis])
        if axis_index < 0 or axis_index >= extent:
            raise ValueError(
                f"work coord out of range for axis {axis}: {axis_index} / {extent}"
            )
        index = index * extent + axis_index
    return index


def _tile_task_assignment_id(processor: str, source_action: str, wave_id: int) -> str:
    return (
        "task_assignment:"
        f"{_sanitize_id_part(processor)}:"
        f"{_sanitize_id_part(source_action)}:"
        f"wave{wave_id}"
    )


def _sanitize_id_part(value: str) -> str:
    result = []
    for char in str(value):
        if char.isalnum():
            result.append(char)
        else:
            result.append("_")
    return "".join(result).strip("_")


__all__ = [
    "ProcessorTileProgram",
    "ProcessorTileActionRef",
    "ProcessorTileActionStream",
    "ProcessorTileStream",
    "TileBlockDependency",
    "TileCollectiveBundle",
    "TileComputeAction",
    "TileDependency",
    "TileDependencyValueKind",
    "TileLoopBodyInstance",
    "TileLoopRegion",
    "TileMicroBlock",
    "TilePhase",
    "TileProgramItemRef",
    "TileRouteAction",
    "TileStoreAction",
    "TileSubtaskPlan",
    "VendorTaskProjection",
    "TileValueKind",
    "TileVisibilityRef",
    "lower_processor_logical_to_tile_program",
]
