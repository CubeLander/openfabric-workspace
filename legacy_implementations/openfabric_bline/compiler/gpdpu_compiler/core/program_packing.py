"""DFU task/subtask/instance packing derived from program nodes.

This layer is still above vendor assembly and binary serialization. It consumes
``ProgramNodeProgram`` as truth: route paths, tile compute actions, store actions,
and dependencies must already be explicit before this pass runs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from gpdpu_compiler.core.program_nodes import ProgramEdge, ProgramNode, ProgramNodeProgram


@dataclass
class PackingTask:
    """One DFU task region, currently one task per output tile wave."""

    id: str
    wave_id: int
    packing_kind: str
    container_ids: list[str] = field(default_factory=list)
    processor_set: list[str] = field(default_factory=list)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "wave_id": self.wave_id,
            "packing_kind": self.packing_kind,
            "container_ids": list(self.container_ids),
            "processor_set": list(self.processor_set),
        }


@dataclass
class PackingContainer:
    """A DFU runtime container, corresponding to one subtask on one processor."""

    id: str
    task_id: str
    processor: str
    subtask_id: str
    subtask_role: str
    node_ids: list[str] = field(default_factory=list)
    instance_ids: list[str] = field(default_factory=list)
    incoming_edge_ids: list[str] = field(default_factory=list)
    outgoing_edge_ids: list[str] = field(default_factory=list)
    is_final_runtime_container: bool = False
    authoritative_view: str = "expanded_debug_instances"
    loop_region_id: str | None = None
    repeat_semantics: str | None = None
    repeat_count: int | None = None
    carried_refs: list[str] = field(default_factory=list)
    body_template: dict[str, Any] = field(default_factory=dict)
    expanded_debug_instances: dict[str, list[str]] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "processor": self.processor,
            "subtask_id": self.subtask_id,
            "subtask_role": self.subtask_role,
            "node_ids": list(self.node_ids),
            "instance_ids": list(self.instance_ids),
            "incoming_edge_ids": list(self.incoming_edge_ids),
            "outgoing_edge_ids": list(self.outgoing_edge_ids),
            "is_final_runtime_container": self.is_final_runtime_container,
            "authoritative_view": self.authoritative_view,
            "loop_region_id": self.loop_region_id,
            "repeat_semantics": self.repeat_semantics,
            "repeat_count": self.repeat_count,
            "carried_refs": list(self.carried_refs),
            "body_template": self.body_template,
            "expanded_debug_instances": {
                key: list(value)
                for key, value in sorted(self.expanded_debug_instances.items())
            },
        }


@dataclass
class PackingInstance:
    """One instance row inside a container."""

    id: str
    container_id: str
    task_id: str
    processor: str
    subtask_id: str
    instance_key: str
    node_ids: list[str] = field(default_factory=list)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "container_id": self.container_id,
            "task_id": self.task_id,
            "processor": self.processor,
            "subtask_id": self.subtask_id,
            "instance_key": self.instance_key,
            "node_ids": list(self.node_ids),
        }


@dataclass(frozen=True)
class NodePackingBinding:
    """Binding from a backend program node to a DFU runtime row."""

    node_id: str
    task_id: str
    processor: str
    subtask_id: str
    subtask_role: str
    container_id: str
    instance_id: str
    instance_key: str
    node_kind: str
    source_action_id: str
    tile_micro_block_id: str | None = None
    tile_micro_block_kind: str | None = None
    binding_kind: str = "program_node_to_dfu_runtime_container_binding"

    def to_plan(self) -> dict[str, Any]:
        return {
            "node_id": self.node_id,
            "task_id": self.task_id,
            "processor": self.processor,
            "subtask_id": self.subtask_id,
            "subtask_role": self.subtask_role,
            "container_id": self.container_id,
            "instance_id": self.instance_id,
            "instance_key": self.instance_key,
            "node_kind": self.node_kind,
            "source_action_id": self.source_action_id,
            "tile_micro_block_id": self.tile_micro_block_id,
            "tile_micro_block_kind": self.tile_micro_block_kind,
            "binding_kind": self.binding_kind,
        }


@dataclass(frozen=True)
class EdgePackingBinding:
    """Binding view for a node-level dependency edge."""

    edge_id: str
    edge_kind: str
    src_node: str
    dst_node: str
    src_container: str
    dst_container: str
    src_instance: str
    dst_instance: str
    scope: str
    source_tile_dependency_id: str
    reason: str
    legalized_edge_class: str = "normal_graph_edge"
    vendor_graph_eligible: bool = True
    absorbed_by: str | None = None
    src_micro_block: str | None = None
    dst_micro_block: str | None = None
    src_micro_block_kind: str | None = None
    dst_micro_block_kind: str | None = None

    def to_plan(self) -> dict[str, Any]:
        return {
            "edge_id": self.edge_id,
            "edge_kind": self.edge_kind,
            "src_node": self.src_node,
            "dst_node": self.dst_node,
            "src_container": self.src_container,
            "dst_container": self.dst_container,
            "src_instance": self.src_instance,
            "dst_instance": self.dst_instance,
            "scope": self.scope,
            "source_tile_dependency_id": self.source_tile_dependency_id,
            "reason": self.reason,
            "legalized_edge_class": self.legalized_edge_class,
            "vendor_graph_eligible": self.vendor_graph_eligible,
            "absorbed_by": self.absorbed_by,
            "src_micro_block": self.src_micro_block,
            "dst_micro_block": self.dst_micro_block,
            "src_micro_block_kind": self.src_micro_block_kind,
            "dst_micro_block_kind": self.dst_micro_block_kind,
        }


@dataclass(frozen=True)
class RepeatedTileLoopBodyTemplate:
    """Metadata-only folded TileLoop body template.

    This does not change vendor row emission yet.  It shadows the expanded
    debug schedule so later passes can validate repeat semantics before taking
    over binary-facing ABI rows.
    """

    template_id: str
    loop_region_id: str
    task_id: str
    processor: str
    loop_axis: str
    repeat_count: int
    fold_policy: str
    body_micro_block_ids: tuple[str, ...]
    body_micro_block_kinds: tuple[str, ...]
    carried_refs: tuple[str, ...]
    loop_variant_refs: tuple[str, ...]
    expanded_debug_instance_keys: tuple[str, ...]
    instance_isomorphism: dict[str, Any]
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "template_id": self.template_id,
            "loop_region_id": self.loop_region_id,
            "task_id": self.task_id,
            "processor": self.processor,
            "loop_axis": self.loop_axis,
            "repeat_count": self.repeat_count,
            "fold_policy": self.fold_policy,
            "body_micro_block_ids": list(self.body_micro_block_ids),
            "body_micro_block_kinds": list(self.body_micro_block_kinds),
            "carried_refs": list(self.carried_refs),
            "loop_variant_refs": list(self.loop_variant_refs),
            "expanded_debug_instance_keys": list(self.expanded_debug_instance_keys),
            "instance_isomorphism": self.instance_isomorphism,
            "attrs": self.attrs,
        }


@dataclass
class DFUPackingProgram:
    """Whole-chip DFU packing program."""

    chip: str
    source_program: str
    source_ir: str
    processor_shape: tuple[int, ...]
    tasks: dict[str, PackingTask]
    containers: dict[str, PackingContainer]
    instances: dict[str, PackingInstance]
    node_bindings: dict[str, NodePackingBinding]
    edge_bindings: dict[str, EdgePackingBinding]
    loop_folding_candidates: dict[str, dict[str, Any]]
    repeated_loop_templates: dict[str, RepeatedTileLoopBodyTemplate]
    edge_legalization_report: dict[str, Any]

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ir": "dfu_packing_program",
            "backend": "dfu3500_runtime_packing",
            "chip": self.chip,
            "source_program": self.source_program,
            "source_ir": self.source_ir,
            "processor_shape": list(self.processor_shape),
            "layering_policy": (
                "dfu_packing_consumes_program_nodes;"
                "route_planning_is_not_rederived;"
                "route_materialize_nodes_run_on_sender_execution_processor;"
                "assembly_and_binary_serialization_not_started"
            ),
            "packing_policy": {
                "scheduling_unit": "ProgramNode",
                "task_policy": "task_per_output_tile_work_unit",
                "container_policy": "task_processor_subtask_role",
                "instance_policy": (
                    "TileLoopRegion_repeated_body_template_with_expanded_debug_instances"
                ),
                "is_final_vendor_schedule": False,
            },
            "tasks": {
                task_id: task.to_plan()
                for task_id, task in sorted(self.tasks.items())
            },
            "containers": {
                container_id: container.to_plan()
                for container_id, container in sorted(self.containers.items())
            },
            "instances": {
                instance_id: instance.to_plan()
                for instance_id, instance in sorted(self.instances.items())
            },
            "node_bindings": {
                node_id: binding.to_plan()
                for node_id, binding in sorted(self.node_bindings.items())
            },
            "edge_bindings": {
                edge_id: binding.to_plan()
                for edge_id, binding in sorted(self.edge_bindings.items())
            },
            "loop_folding_candidates": dict(sorted(self.loop_folding_candidates.items())),
            "repeated_loop_templates": {
                template_id: template.to_plan()
                for template_id, template in sorted(self.repeated_loop_templates.items())
            },
            "edge_legalization_report": self.edge_legalization_report,
            "validation": self._validation(),
            "totals": self._totals(),
        }

    def _validation(self) -> dict[str, Any]:
        return {
            "all_nodes_bound": len(self.node_bindings) == sum(
                len(container.node_ids) for container in self.containers.values()
            ),
            "no_unbound_edges": all(
                binding.scope != "unbound" for binding in self.edge_bindings.values()
            ),
            "all_loop_containers_have_repeat_metadata": all(
                container.repeat_semantics == "vendor_instance_repeat"
                and container.repeat_count is not None
                and container.loop_region_id
                for container in self.containers.values()
                if container.subtask_role == "k_stream"
            ),
            "loop_carried_edges_are_absorbed": all(
                not binding.vendor_graph_eligible
                and binding.absorbed_by == "loop_carried_state"
                for binding in self.edge_bindings.values()
                if binding.legalized_edge_class == "loop_carried_edge"
            ),
            "all_node_bindings_keep_micro_block_identity": all(
                binding.tile_micro_block_id is not None
                and binding.tile_micro_block_kind is not None
                for binding in self.node_bindings.values()
            ),
            "all_repeated_loop_templates_are_metadata_only": all(
                template.attrs.get("folded_repeat_mode") == "metadata_only"
                for template in self.repeated_loop_templates.values()
            ),
        }

    def _totals(self) -> dict[str, Any]:
        container_role_counts: dict[str, int] = {}
        for container in self.containers.values():
            role = container.subtask_role
            container_role_counts[role] = container_role_counts.get(role, 0) + 1

        edge_scope_counts: dict[str, int] = {}
        edge_class_counts: dict[str, int] = {}
        for binding in self.edge_bindings.values():
            edge_scope_counts[binding.scope] = edge_scope_counts.get(binding.scope, 0) + 1
            edge_class_counts[binding.legalized_edge_class] = (
                edge_class_counts.get(binding.legalized_edge_class, 0) + 1
            )

        instance_role_counts: dict[str, int] = {}
        for instance in self.instances.values():
            container = self.containers[instance.container_id]
            role = container.subtask_role
            instance_role_counts[role] = instance_role_counts.get(role, 0) + 1

        return {
            "task_count": len(self.tasks),
            "container_count": len(self.containers),
            "instance_count": len(self.instances),
            "node_binding_count": len(self.node_bindings),
            "micro_block_binding_count": len(
                {
                    binding.tile_micro_block_id
                    for binding in self.node_bindings.values()
                    if binding.tile_micro_block_id is not None
                }
            ),
            "edge_binding_count": len(self.edge_bindings),
            "loop_folding_candidate_count": len(self.loop_folding_candidates),
            "repeated_loop_template_count": len(self.repeated_loop_templates),
            "repeated_body_template_count": sum(
                1
                for container in self.containers.values()
                if container.authoritative_view == "folded_template"
            ),
            "vendor_graph_eligible_edge_count": sum(
                1 for binding in self.edge_bindings.values() if binding.vendor_graph_eligible
            ),
            "loop_carried_edge_count": edge_class_counts.get("loop_carried_edge", 0),
            "container_role_counts": dict(sorted(container_role_counts.items())),
            "instance_role_counts": dict(sorted(instance_role_counts.items())),
            "edge_scope_counts": dict(sorted(edge_scope_counts.items())),
            "edge_class_counts": dict(sorted(edge_class_counts.items())),
        }


def lower_program_nodes_to_dfu_packing(
    node_program: ProgramNodeProgram,
) -> DFUPackingProgram:
    """Pack backend program nodes into DFU task/subtask/instance containers."""

    builder = _DFUPackingBuilder(node_program)
    return builder.build()


class _DFUPackingBuilder:
    def __init__(self, node_program: ProgramNodeProgram) -> None:
        self.node_program = node_program
        self.tasks: dict[str, PackingTask] = {}
        self.containers: dict[str, PackingContainer] = {}
        self.instances: dict[str, PackingInstance] = {}
        self.node_bindings: dict[str, NodePackingBinding] = {}
        self.edge_bindings: dict[str, EdgePackingBinding] = {}
        self.loop_folding_candidates: dict[str, dict[str, Any]] = {}
        self.repeated_loop_templates: dict[str, RepeatedTileLoopBodyTemplate] = {}
        self.edge_legalization_report: dict[str, Any] = {}

    def build(self) -> DFUPackingProgram:
        self._bind_nodes()
        self._attach_loop_container_metadata()
        self._bind_edges()
        self._build_edge_legalization_report()
        self._build_loop_folding_candidates()
        self._build_repeated_loop_templates()
        return DFUPackingProgram(
            chip=self.node_program.chip,
            source_program=self.node_program.source_program,
            source_ir="program_nodes",
            processor_shape=self.node_program.processor_shape,
            tasks=self.tasks,
            containers=self.containers,
            instances=self.instances,
            node_bindings=self.node_bindings,
            edge_bindings=self.edge_bindings,
            loop_folding_candidates=self.loop_folding_candidates,
            repeated_loop_templates=self.repeated_loop_templates,
            edge_legalization_report=self.edge_legalization_report,
        )

    def _bind_nodes(self) -> None:
        for node_id, node in sorted(self.node_program.nodes.items()):
            assignment = _node_assignment(node)
            task_id = assignment.task_name
            task = self._ensure_task(task_id, assignment.wave_id)
            container_id = f"{task_id}:{node.processor}:{assignment.subtask_id}"
            container = self._ensure_container(
                container_id,
                task_id=task_id,
                processor=node.processor,
                subtask_id=assignment.subtask_id,
                subtask_role=assignment.subtask_role,
            )
            instance_id = f"{container_id}:{assignment.instance_id}"
            instance = self._ensure_instance(
                instance_id,
                container_id=container_id,
                task_id=task_id,
                processor=node.processor,
                subtask_id=assignment.subtask_id,
                instance_key=assignment.instance_key,
            )

            binding = NodePackingBinding(
                node_id=node_id,
                task_id=task_id,
                processor=node.processor,
                subtask_id=assignment.subtask_id,
                subtask_role=assignment.subtask_role,
                container_id=container_id,
                instance_id=instance_id,
                instance_key=assignment.instance_key,
                node_kind=node.node_kind,
                source_action_id=node.source_action_id,
                tile_micro_block_id=node.payload.get("tile_micro_block_id"),
                tile_micro_block_kind=node.payload.get("tile_micro_block_kind"),
            )
            self.node_bindings[node_id] = binding
            _append_unique(task.container_ids, container_id)
            _append_unique(task.processor_set, node.processor)
            _append_unique(container.node_ids, node_id)
            _append_unique(container.instance_ids, instance_id)
            _append_unique(instance.node_ids, node_id)
            if node.payload.get("loop_region_id"):
                _append_unique(
                    container.expanded_debug_instances.setdefault(
                        str(node.payload.get("loop_instance_id", "unknown")),
                        [],
                    ),
                    node_id,
                )

    def _bind_edges(self) -> None:
        for edge_id, edge in sorted(self.node_program.edges.items()):
            src = self.node_bindings.get(edge.src_node)
            dst = self.node_bindings.get(edge.dst_node)
            scope = _edge_scope(src, dst)
            edge_class, vendor_graph_eligible, absorbed_by = _legalize_edge(
                edge,
                src_node=self.node_program.nodes.get(edge.src_node),
                dst_node=self.node_program.nodes.get(edge.dst_node),
            )
            binding = EdgePackingBinding(
                edge_id=edge_id,
                edge_kind=edge.edge_kind,
                src_node=edge.src_node,
                dst_node=edge.dst_node,
                src_container=src.container_id if src else "-",
                dst_container=dst.container_id if dst else "-",
                src_instance=src.instance_id if src else "-",
                dst_instance=dst.instance_id if dst else "-",
                scope=scope,
                source_tile_dependency_id=edge.source_tile_dependency_id,
                reason=_edge_reason(edge),
                legalized_edge_class=edge_class,
                vendor_graph_eligible=vendor_graph_eligible,
                absorbed_by=absorbed_by,
                src_micro_block=(
                    self.node_program.nodes[edge.src_node].payload.get("tile_micro_block_id")
                    if edge.src_node in self.node_program.nodes
                    else None
                ),
                dst_micro_block=(
                    self.node_program.nodes[edge.dst_node].payload.get("tile_micro_block_id")
                    if edge.dst_node in self.node_program.nodes
                    else None
                ),
                src_micro_block_kind=(
                    self.node_program.nodes[edge.src_node].payload.get("tile_micro_block_kind")
                    if edge.src_node in self.node_program.nodes
                    else None
                ),
                dst_micro_block_kind=(
                    self.node_program.nodes[edge.dst_node].payload.get("tile_micro_block_kind")
                    if edge.dst_node in self.node_program.nodes
                    else None
                ),
            )
            self.edge_bindings[edge_id] = binding
            if src is not None:
                _append_unique(self.containers[src.container_id].outgoing_edge_ids, edge_id)
            if dst is not None:
                _append_unique(self.containers[dst.container_id].incoming_edge_ids, edge_id)

    def _build_edge_legalization_report(self) -> None:
        class_counts: dict[str, int] = {}
        absorbed_counts: dict[str, int] = {}
        for binding in self.edge_bindings.values():
            class_counts[binding.legalized_edge_class] = (
                class_counts.get(binding.legalized_edge_class, 0) + 1
            )
            if binding.absorbed_by:
                absorbed_counts[binding.absorbed_by] = absorbed_counts.get(binding.absorbed_by, 0) + 1
        vendor_graph_eligible = sum(
            1 for binding in self.edge_bindings.values() if binding.vendor_graph_eligible
        )
        self.edge_legalization_report = {
            "total_edges_before": len(self.edge_bindings),
            "normal_graph_edges": class_counts.get("normal_graph_edge", 0),
            "internal_template_edges": class_counts.get("internal_template_edge", 0),
            "loop_carried_edges": class_counts.get("loop_carried_edge", 0),
            "vendor_graph_eligible_edges": vendor_graph_eligible,
            "vendor_edges_after": vendor_graph_eligible,
            "absorbed_counts": dict(sorted(absorbed_counts.items())),
            "policy": (
                "preserve_original_edge_bindings;"
                "absorb_loop_carried_edges_into_repeated_body_carried_state"
            ),
        }

    def _attach_loop_container_metadata(self) -> None:
        for loop_id, loop in sorted(self.node_program.loop_regions.items()):
            task_id = _task_id_from_loop_region(loop)
            container_id = f"{task_id}:{loop['processor']}:subtask1"
            container = self.containers.get(container_id)
            if container is None:
                continue
            container.authoritative_view = "folded_template"
            container.loop_region_id = loop_id
            container.repeat_semantics = "vendor_instance_repeat"
            container.repeat_count = int(loop["repeat_count"])
            container.carried_refs = list(loop["carried_refs"])
            container.body_template = {
                "loop_region_id": loop_id,
                "loop_axis": loop["loop_axis"],
                "repeat_count": loop["repeat_count"],
                "fold_policy": loop["fold_policy"],
                "closure_shape": loop["closure_shape"],
                "source_region_path": loop["source_region_path"],
                "action_ids_by_instance": loop["action_ids_by_instance"],
                "node_ids_by_instance": loop["node_ids_by_instance"],
                "micro_block_ids_by_instance": loop.get("micro_block_ids_by_instance", {}),
                "body_shape": "expanded_debug_instances_are_template_instances",
                "instance_bindings": list(loop["node_ids_by_instance"].keys()),
                "carried_refs": list(loop["carried_refs"]),
                "loop_variant_refs": list(loop["loop_variant_refs"]),
            }
            for instance_key, node_ids in loop["node_ids_by_instance"].items():
                container.expanded_debug_instances[instance_key] = list(node_ids)

    def _build_loop_folding_candidates(self) -> None:
        for loop_id, loop in sorted(self.node_program.loop_regions.items()):
            task_id = _task_id_from_loop_region(loop)
            container_id = f"{task_id}:{loop['processor']}:subtask1"
            container = self.containers.get(container_id)
            if container is None:
                continue
            instance_keys = list(loop["node_ids_by_instance"].keys())
            instance_ids = [
                f"{container_id}:inst{key.removeprefix('k')}"
                for key in instance_keys
            ]
            candidate_id = f"loop_fold:{container_id}"
            self.loop_folding_candidates[candidate_id] = {
                "id": candidate_id,
                "container_id": container_id,
                "task_id": task_id,
                "processor": loop["processor"],
                "subtask_id": container.subtask_id,
                "subtask_role": container.subtask_role,
                "loop_region_id": loop_id,
                "authoritative_view": "folded_template",
                "repeat_semantics": "vendor_instance_repeat",
                "repeat_count": loop["repeat_count"],
                "instance_count": loop["repeat_count"],
                "instance_keys": instance_keys,
                "instance_ids": instance_ids,
                "carried_refs": list(loop["carried_refs"]),
                "loop_variant_refs": list(loop["loop_variant_refs"]),
                "body_template": container.body_template,
                "expanded_debug_instances": {
                    key: list(value)
                    for key, value in sorted(container.expanded_debug_instances.items())
                },
                "status": "structural_tile_loop_region_candidate_not_binary_folded",
                "reason": (
                    "TileLoopRegion_is_authoritative;"
                    "expanded_instances_are_debug_view;"
                    "actual_vendor_loop_folding_is_later"
                ),
            }

    def _build_repeated_loop_templates(self) -> None:
        for loop_id, loop in sorted(self.node_program.loop_regions.items()):
            task_id = _task_id_from_loop_region(loop)
            instance_keys = list(loop["node_ids_by_instance"].keys())
            micro_block_ids_by_instance = loop.get("micro_block_ids_by_instance", {})
            if not instance_keys:
                continue
            template_instance_key = instance_keys[0]
            template_micro_block_ids = tuple(
                micro_block_ids_by_instance.get(template_instance_key, [])
            )
            template_micro_block_kinds = tuple(
                self._micro_block_kind(block_id)
                for block_id in template_micro_block_ids
            )
            isomorphism = self._loop_instance_isomorphism(
                instance_keys=instance_keys,
                micro_block_ids_by_instance=micro_block_ids_by_instance,
                template_kinds=template_micro_block_kinds,
            )
            template_id = f"repeated_loop_template:{loop_id}"
            self.repeated_loop_templates[template_id] = RepeatedTileLoopBodyTemplate(
                template_id=template_id,
                loop_region_id=loop_id,
                task_id=task_id,
                processor=str(loop["processor"]),
                loop_axis=str(loop["loop_axis"]),
                repeat_count=int(loop["repeat_count"]),
                fold_policy=str(loop["fold_policy"]),
                body_micro_block_ids=template_micro_block_ids,
                body_micro_block_kinds=template_micro_block_kinds,
                carried_refs=tuple(loop["carried_refs"]),
                loop_variant_refs=tuple(loop["loop_variant_refs"]),
                expanded_debug_instance_keys=tuple(instance_keys),
                instance_isomorphism=isomorphism,
                attrs={
                    "folded_repeat_mode": "metadata_only",
                    "expanded_debug_instance_count": len(instance_keys),
                    "folded_vendor_row_estimate": len(template_micro_block_ids),
                    "expanded_vendor_row_count": sum(
                        len(micro_block_ids_by_instance.get(key, []))
                        for key in instance_keys
                    ),
                    "template_scope": "per_loop_region_per_processor",
                    "binary_facing": False,
                },
            )

    def _micro_block_kind(self, block_id: str) -> str:
        row = self.node_program.micro_blocks.get(block_id, {})
        return str(row.get("block_kind", "unknown"))

    def _loop_instance_isomorphism(
        self,
        *,
        instance_keys: list[str],
        micro_block_ids_by_instance: dict[str, list[str]],
        template_kinds: tuple[str, ...],
    ) -> dict[str, Any]:
        signatures: dict[str, list[str]] = {}
        violations: list[dict[str, Any]] = []
        for key in instance_keys:
            signature = [
                self._micro_block_kind(block_id)
                for block_id in micro_block_ids_by_instance.get(key, [])
            ]
            signatures[key] = signature
            if tuple(signature) != template_kinds:
                violations.append(
                    {
                        "instance_key": key,
                        "expected": list(template_kinds),
                        "actual": signature,
                    }
                )
        return {
            "instance_isomorphic": not violations,
            "canonical_micro_block_kind_sequence": list(template_kinds),
            "allowed_variant_fields": [
                "k_index",
                "tile_refs",
                "visibility_ref_ids",
                "route_bundle_ids",
                "symbolic_immediates_tied_to_k",
            ],
            "checked_signature": "micro_block_kind_sequence",
            "violations": violations,
            "signatures_by_instance": signatures,
        }

    def _ensure_task(self, task_id: str, wave_id: int) -> PackingTask:
        return self.tasks.setdefault(
            task_id,
            PackingTask(
                id=task_id,
                wave_id=wave_id,
                packing_kind="output_tile_work_unit_region",
            ),
        )

    def _ensure_container(
        self,
        container_id: str,
        *,
        task_id: str,
        processor: str,
        subtask_id: str,
        subtask_role: str,
    ) -> PackingContainer:
        return self.containers.setdefault(
            container_id,
            PackingContainer(
                id=container_id,
                task_id=task_id,
                processor=processor,
                subtask_id=subtask_id,
                subtask_role=subtask_role,
                is_final_runtime_container=subtask_role == "finalize_store",
            ),
        )

    def _ensure_instance(
        self,
        instance_id: str,
        *,
        container_id: str,
        task_id: str,
        processor: str,
        subtask_id: str,
        instance_key: str,
    ) -> PackingInstance:
        return self.instances.setdefault(
            instance_id,
            PackingInstance(
                id=instance_id,
                container_id=container_id,
                task_id=task_id,
                processor=processor,
                subtask_id=subtask_id,
                instance_key=instance_key,
            ),
        )


@dataclass(frozen=True)
class _NodeAssignment:
    wave_id: int
    launch_group_id: int
    task_id: int
    task_name: str
    subtask_id: str
    subtask_role: str
    instance_id: str
    instance_key: str


def _node_assignment(node: ProgramNode) -> _NodeAssignment:
    task = _node_task_assignment(node)
    if node.node_kind == "route_materialize":
        k_index = _node_k_index(node)
        return _NodeAssignment(
            wave_id=_node_wave_id(node),
            launch_group_id=task["launch_group_id"],
            task_id=task["task_id"],
            task_name=task["task_name"],
            subtask_id="subtask1",
            subtask_role="k_stream",
            instance_id=f"inst{k_index}",
            instance_key=f"k{k_index}",
        )
    if node.node_kind == "tile_compute":
        compute_kind = str(node.payload.get("compute_kind", "compute"))
        if compute_kind == "accumulator_prepare":
            return _NodeAssignment(
                wave_id=_node_wave_id(node),
                launch_group_id=task["launch_group_id"],
                task_id=task["task_id"],
                task_name=task["task_name"],
                subtask_id="subtask0",
                subtask_role="accumulator_prepare",
                instance_id="inst_prepare",
                instance_key="prepare",
            )
        if compute_kind == "gemm_k_update":
            k_index = _node_k_index(node)
            return _NodeAssignment(
                wave_id=_node_wave_id(node),
                launch_group_id=task["launch_group_id"],
                task_id=task["task_id"],
                task_name=task["task_name"],
                subtask_id="subtask1",
                subtask_role="k_stream",
                instance_id=f"inst{k_index}",
                instance_key=f"k{k_index}",
            )
        return _NodeAssignment(
            wave_id=_node_wave_id(node),
            launch_group_id=task["launch_group_id"],
            task_id=task["task_id"],
            task_name=task["task_name"],
            subtask_id="subtask0",
            subtask_role="local_compute",
            instance_id=f"inst_{compute_kind}",
            instance_key=compute_kind,
        )
    if node.node_kind == "tile_store":
        source_final_tile = node.payload.get("source_final_tile", {})
        has_gemm_task_assignment = isinstance(source_final_tile, dict) and isinstance(
            source_final_tile.get("task_assignment"),
            dict,
        )
        return _NodeAssignment(
            wave_id=_node_wave_id(node),
            launch_group_id=task["launch_group_id"],
            task_id=task["task_id"],
            task_name=task["task_name"],
            subtask_id="subtask2" if has_gemm_task_assignment else "subtask1",
            subtask_role="finalize_store",
            instance_id="inst_final",
            instance_key="final",
        )
    return _NodeAssignment(
        wave_id=_node_wave_id(node),
        launch_group_id=task["launch_group_id"],
        task_id=task["task_id"],
        task_name=task["task_name"],
        subtask_id="subtask_unknown",
        subtask_role="unknown",
        instance_id="inst0",
        instance_key="unknown",
    )


def _node_task_assignment(node: ProgramNode) -> dict[str, Any]:
    payload = node.payload
    candidates: list[Any] = [
        payload.get("task_assignment"),
    ]
    attrs = payload.get("attrs", {})
    if isinstance(attrs, dict):
        candidates.append(attrs.get("task_assignment"))
    block_attrs = payload.get("tile_micro_block_attrs", {})
    if isinstance(block_attrs, dict):
        candidates.append(block_attrs.get("task_assignment"))
    source_final_tile = payload.get("source_final_tile", {})
    if isinstance(source_final_tile, dict):
        candidates.append(source_final_tile.get("task_assignment"))

    assignment = next((row for row in candidates if isinstance(row, dict)), None)
    if assignment is None:
        if _node_requires_task_assignment(node):
            raise ValueError(
                "GEMM ProgramNode missing TileTaskAssignment; "
                "DFUPackingProgram must not reconstruct task_id from virtual work id. "
                f"node_id={node.id}"
            )
        wave_id = _node_wave_id(node)
        return {
            "launch_group_id": 0,
            "task_id": 0,
            "task_name": "task0",
            "wave_id": wave_id,
            "max_vendor_tasks": 1,
        }

    task_id = _required_int(assignment, "task_id", node.id)
    max_vendor_tasks = _required_int(assignment, "max_vendor_tasks", node.id)
    if task_id < 0 or task_id >= max_vendor_tasks:
        raise ValueError(
            f"vendor task id out of range for {node.id}: "
            f"task_id={task_id}, max_vendor_tasks={max_vendor_tasks}"
        )
    launch_group_id = _required_int(assignment, "launch_group_id", node.id)
    if launch_group_id > 0:
        raise ValueError(
            "DFU3500 legacy GEMM binary emission does not support multi-launch "
            f"task groups yet: node_id={node.id}, launch_group_id={launch_group_id}"
        )
    task_name = str(assignment.get("task_name") or f"task{task_id}")
    virtual_work_id = _optional_int(assignment, "virtual_work_id")
    return {
        "launch_group_id": launch_group_id,
        "task_id": task_id,
        "task_name": task_name,
        "wave_id": (
            virtual_work_id
            if virtual_work_id is not None
            else _required_int(assignment, "wave_id", node.id)
        ),
        "max_vendor_tasks": max_vendor_tasks,
    }


def _node_requires_task_assignment(node: ProgramNode) -> bool:
    if node.node_kind == "route_materialize":
        return True
    if node.node_kind == "tile_store":
        source_final_tile = node.payload.get("source_final_tile", {})
        return isinstance(source_final_tile, dict) and (
            "task_assignment" in source_final_tile
        )
    if node.node_kind == "tile_compute":
        compute_kind = str(node.payload.get("compute_kind", "compute"))
        return compute_kind in {"accumulator_prepare", "gemm_k_update"}
    return False


def _required_int(mapping: dict[str, Any], key: str, node_id: str) -> int:
    value = mapping.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    raise ValueError(f"task assignment field {key!r} missing or invalid for {node_id}")


def _optional_int(mapping: dict[str, Any], key: str) -> int | None:
    value = mapping.get(key)
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def _node_wave_id(node: ProgramNode) -> int:
    payload = node.payload
    attrs = payload.get("attrs", {})
    if not isinstance(attrs, dict):
        attrs = {}

    for value in (
        attrs.get("virtual_work_id"),
        attrs.get("wave_id"),
        payload.get("virtual_work_id"),
        payload.get("wave_id"),
    ):
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)

    source_final_tile = payload.get("source_final_tile", {})
    if isinstance(source_final_tile, dict):
        task_assignment = source_final_tile.get("task_assignment")
        if isinstance(task_assignment, dict):
            for value in (
                task_assignment.get("virtual_work_id"),
                task_assignment.get("wave_id"),
            ):
                if isinstance(value, int):
                    return value
                if isinstance(value, str) and value.isdigit():
                    return int(value)
        for value in (
            source_final_tile.get("virtual_work_id"),
            source_final_tile.get("wave_id"),
        ):
            if isinstance(value, int):
                return value
            if isinstance(value, str) and value.isdigit():
                return int(value)

    for text in (
        str(payload.get("bundle_id", "")),
        node.source_action_id,
        node.id,
        node.source_phase_id or "",
    ):
        match = re.search(r"(?:task|wave)(\d+)", text)
        if match:
            return int(match.group(1))

    return 0


def _node_k_index(node: ProgramNode) -> int:
    payload = node.payload
    attrs = payload.get("attrs", {})
    if not isinstance(attrs, dict):
        attrs = {}

    for value in (
        payload.get("k_index"),
        attrs.get("k_index"),
    ):
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)

    tile_coord = attrs.get("tile_coord", {})
    if isinstance(tile_coord, dict):
        value = tile_coord.get("k_block")
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)

    for text in (node.source_action_id, node.id, str(payload.get("bundle_id", ""))):
        match = re.search(r"[:_]k(\d+)(?:[:_]|$)", text)
        if match:
            return int(match.group(1))

    return 0


def _task_id_from_loop_region(loop: dict[str, Any]) -> str:
    source_phase_id = str(loop.get("source_phase_id", ""))
    match = re.search(r"(?:task|wave)(\d+)", source_phase_id)
    if match:
        return f"task{int(match.group(1))}"

    source_region_path = str(loop.get("source_region_path", ""))
    match = re.search(r"(?:task|wave)(\d+)", source_region_path)
    if match:
        return f"task{int(match.group(1))}"

    return "task0"


def _edge_scope(
    src: NodePackingBinding | None,
    dst: NodePackingBinding | None,
) -> str:
    if src is None or dst is None:
        return "unbound"
    if src.instance_id == dst.instance_id:
        return "internal_instance"
    if src.container_id == dst.container_id:
        return "internal_subtask"
    if src.task_id == dst.task_id and src.processor == dst.processor:
        return "cross_subtask"
    if src.task_id == dst.task_id:
        return "cross_processor_same_task"
    return "cross_task"


def _legalize_edge(
    edge: ProgramEdge,
    *,
    src_node: ProgramNode | None,
    dst_node: ProgramNode | None,
) -> tuple[str, bool, str | None]:
    if _is_loop_carried_accumulator_edge(edge, src_node=src_node, dst_node=dst_node):
        return "loop_carried_edge", False, "loop_carried_state"
    if _is_internal_template_edge(src_node=src_node, dst_node=dst_node):
        return "internal_template_edge", True, None
    return "normal_graph_edge", True, None


def _is_loop_carried_accumulator_edge(
    edge: ProgramEdge,
    *,
    src_node: ProgramNode | None,
    dst_node: ProgramNode | None,
) -> bool:
    if edge.edge_kind != "accumulator_dependency":
        return False
    if src_node is None or dst_node is None:
        return False
    src_payload = src_node.payload
    dst_payload = dst_node.payload
    return (
        src_payload.get("loop_region_id") is not None
        and src_payload.get("loop_region_id") == dst_payload.get("loop_region_id")
        and src_payload.get("loop_instance_id") != dst_payload.get("loop_instance_id")
        and src_payload.get("loop_role") == "compute"
        and dst_payload.get("loop_role") == "compute"
    )


def _is_internal_template_edge(
    *,
    src_node: ProgramNode | None,
    dst_node: ProgramNode | None,
) -> bool:
    if src_node is None or dst_node is None:
        return False
    src_payload = src_node.payload
    dst_payload = dst_node.payload
    return (
        src_payload.get("loop_region_id") is not None
        and src_payload.get("loop_region_id") == dst_payload.get("loop_region_id")
        and src_payload.get("loop_instance_id") == dst_payload.get("loop_instance_id")
    )


def _edge_reason(edge: ProgramEdge) -> str:
    if edge.edge_kind == "route_step_order":
        return "sender_push_route_hop_order"
    if edge.edge_kind == "visibility_dependency":
        return "tile_compute_waits_for_route_endpoint_visibility"
    if edge.edge_kind == "accumulator_dependency":
        return "serial_k_accumulator_update_order"
    if edge.edge_kind == "store_dependency":
        return "tile_store_waits_for_final_output_tile"
    return "program_node_dependency"


def _append_unique(values: list[str], value: str) -> None:
    if value not in values:
        values.append(value)


__all__ = [
    "DFUPackingProgram",
    "EdgePackingBinding",
    "NodePackingBinding",
    "PackingContainer",
    "PackingInstance",
    "PackingTask",
    "RepeatedTileLoopBodyTemplate",
    "lower_program_nodes_to_dfu_packing",
]
