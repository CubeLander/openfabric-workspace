"""Node-level backend program derived from processor tile actions.

This layer is the first DFU-oriented graph view after ``ProcessorTileProgram``.
It is close enough to the vendor binary packing shape to expose executable
nodes and edges, but it still does not assign task/subtask/instance rows or
serialize vendor structs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gpdpu_compiler.core.program_tile import (
    ProcessorTileProgram,
    TileComputeAction,
    TileDependency,
    TileLoopRegion,
    TileRouteAction,
    TileStoreAction,
)


@dataclass(frozen=True)
class ProgramNode:
    """One backend-facing executable node."""

    id: str
    node_kind: str
    processor: str
    source_action_id: str
    source_action_kind: str
    source_phase_id: str | None = None
    tile_refs: tuple[str, ...] = ()
    payload: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "node_kind": self.node_kind,
            "processor": self.processor,
            "source_action_id": self.source_action_id,
            "source_action_kind": self.source_action_kind,
            "source_phase_id": self.source_phase_id,
            "tile_refs": list(self.tile_refs),
            "payload": self.payload,
        }


@dataclass(frozen=True)
class ProgramEdge:
    """One graph dependency edge between backend-facing nodes."""

    id: str
    edge_kind: str
    src_node: str
    dst_node: str
    src_processor: str
    dst_processor: str
    source_tile_dependency_id: str
    payload: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "edge_kind": self.edge_kind,
            "src_node": self.src_node,
            "dst_node": self.dst_node,
            "src_processor": self.src_processor,
            "dst_processor": self.dst_processor,
            "source_tile_dependency_id": self.source_tile_dependency_id,
            "payload": self.payload,
        }


@dataclass
class ProgramNodeProgram:
    """Whole-chip node-level program."""

    chip: str
    source_program: str
    source_ir: str
    processor_shape: tuple[int, ...]
    nodes: dict[str, ProgramNode]
    edges: dict[str, ProgramEdge]
    action_to_node: dict[str, str]
    source_tile_dependency_to_edge: dict[str, str]
    external_preconditions: dict[str, dict[str, Any]]
    per_processor_nodes: dict[str, list[str]]
    per_processor_edges: dict[str, list[str]]
    loop_regions: dict[str, dict[str, Any]]
    micro_blocks: dict[str, dict[str, Any]]

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ir": "program_nodes",
            "backend": "dfu_node_program",
            "chip": self.chip,
            "source_program": self.source_program,
            "source_ir": self.source_ir,
            "processor_shape": list(self.processor_shape),
            "layering_policy": (
                "program_nodes_consume_processor_tile_actions;"
                "route_planning_is_not_rederived;"
                "packing_and_binary_serialization_not_started"
            ),
            "nodes": {
                node_id: node.to_plan()
                for node_id, node in sorted(self.nodes.items())
            },
            "edges": {
                edge_id: edge.to_plan()
                for edge_id, edge in sorted(self.edges.items())
            },
            "action_to_node": dict(sorted(self.action_to_node.items())),
            "source_tile_dependency_to_edge": dict(
                sorted(self.source_tile_dependency_to_edge.items())
            ),
            "external_preconditions": dict(sorted(self.external_preconditions.items())),
            "loop_regions": dict(sorted(self.loop_regions.items())),
            "micro_blocks": dict(sorted(self.micro_blocks.items())),
            "per_processor_nodes": {
                processor: sorted(node_ids)
                for processor, node_ids in sorted(self.per_processor_nodes.items())
            },
            "per_processor_edges": {
                processor: sorted(edge_ids)
                for processor, edge_ids in sorted(self.per_processor_edges.items())
            },
            "validation": {
                "is_acyclic": _is_acyclic(self.nodes, self.edges),
                "all_actions_have_nodes": self._all_actions_have_nodes(),
                "all_loop_body_actions_have_nodes": self._all_loop_body_actions_have_nodes(),
                "all_micro_block_actions_have_nodes": self._all_micro_block_actions_have_nodes(),
            },
            "totals": self._totals(),
        }

    def _all_actions_have_nodes(self) -> bool:
        return len(self.action_to_node) == len(self.nodes)

    def _all_loop_body_actions_have_nodes(self) -> bool:
        return all(
            action_id in self.action_to_node
            for loop in self.loop_regions.values()
            for action_ids in loop["action_ids_by_instance"].values()
            for action_id in action_ids
        )

    def _all_micro_block_actions_have_nodes(self) -> bool:
        return all(
            action_id in self.action_to_node
            for micro_block in self.micro_blocks.values()
            for action_id in micro_block["action_ids"]
        )

    def _totals(self) -> dict[str, Any]:
        node_counts: dict[str, int] = {}
        edge_counts: dict[str, int] = {}
        for node in self.nodes.values():
            node_counts[node.node_kind] = node_counts.get(node.node_kind, 0) + 1
        for edge in self.edges.values():
            edge_counts[edge.edge_kind] = edge_counts.get(edge.edge_kind, 0) + 1
        return {
            "processor_count": len(self.per_processor_nodes),
            "node_count": len(self.nodes),
            "edge_count": len(self.edges),
            "external_precondition_count": len(self.external_preconditions),
            "action_to_node_count": len(self.action_to_node),
            "graphable_tile_dependency_count": len(self.source_tile_dependency_to_edge),
            "loop_region_count": len(self.loop_regions),
            "micro_block_count": len(self.micro_blocks),
            "micro_block_membership_count": sum(
                len(row["node_ids"]) for row in self.micro_blocks.values()
            ),
            "loop_membership_count": sum(
                len(node.payload.get("loop_memberships", []))
                for node in self.nodes.values()
            ),
            "node_counts": dict(sorted(node_counts.items())),
            "edge_counts": dict(sorted(edge_counts.items())),
        }


def lower_processor_tile_to_program_nodes(
    tile_program: ProcessorTileProgram,
) -> ProgramNodeProgram:
    """Lower tile actions and dependencies to backend-facing program nodes."""

    builder = _ProgramNodeBuilder(tile_program)
    return builder.build()


class _ProgramNodeBuilder:
    def __init__(self, tile_program: ProcessorTileProgram) -> None:
        self.tile_program = tile_program
        self.nodes: dict[str, ProgramNode] = {}
        self.edges: dict[str, ProgramEdge] = {}
        self.action_to_node: dict[str, str] = {}
        self.source_tile_dependency_to_edge: dict[str, str] = {}
        self.external_preconditions: dict[str, dict[str, Any]] = {}
        self.action_loop_memberships = _build_action_loop_memberships(tile_program)
        self.loop_regions: dict[str, dict[str, Any]] = {}
        self.micro_blocks: dict[str, dict[str, Any]] = {}
        self.per_processor_nodes: dict[str, list[str]] = {
            processor: [] for processor in tile_program.programs
        }
        self.per_processor_edges: dict[str, list[str]] = {
            processor: [] for processor in tile_program.programs
        }

    def build(self) -> ProgramNodeProgram:
        self._add_route_nodes()
        self._add_compute_nodes()
        self._add_store_nodes()
        self._add_edges()
        self._add_micro_block_index()
        self._add_loop_region_index()
        return ProgramNodeProgram(
            chip=self.tile_program.chip,
            source_program=self.tile_program.source_program,
            source_ir="processor_tile_program",
            processor_shape=self.tile_program.processor_shape,
            nodes=self.nodes,
            edges=self.edges,
            action_to_node=self.action_to_node,
            source_tile_dependency_to_edge=self.source_tile_dependency_to_edge,
            external_preconditions=self.external_preconditions,
            per_processor_nodes=self.per_processor_nodes,
            per_processor_edges=self.per_processor_edges,
            loop_regions=self.loop_regions,
            micro_blocks=self.micro_blocks,
        )

    def _add_route_nodes(self) -> None:
        for action in sorted(self.tile_program.tile_route_actions.values(), key=lambda row: row.id):
            node = _route_node(
                action,
                self.action_loop_memberships.get(action.id, ()),
                _micro_block_payload(self.tile_program, action.id),
            )
            self._add_node(node, action.id)

    def _add_compute_nodes(self) -> None:
        for action in sorted(self.tile_program.tile_compute_actions.values(), key=lambda row: row.id):
            node = _compute_node(
                action,
                self.action_loop_memberships.get(action.id, ()),
                _micro_block_payload(self.tile_program, action.id),
            )
            self._add_node(node, action.id)

    def _add_store_nodes(self) -> None:
        for action in sorted(self.tile_program.tile_store_actions.values(), key=lambda row: row.id):
            node = _store_node(
                action,
                self.action_loop_memberships.get(action.id, ()),
                _micro_block_payload(self.tile_program, action.id),
            )
            self._add_node(node, action.id)

    def _add_edges(self) -> None:
        for dependency in sorted(
            self.tile_program.tile_dependencies.values(),
            key=lambda row: row.id,
        ):
            src_node = self.action_to_node.get(dependency.src)
            dst_node = self.action_to_node.get(dependency.dst)
            if src_node is None or dst_node is None:
                self._add_external_precondition(dependency, src_node=src_node, dst_node=dst_node)
                continue
            edge = _edge_from_dependency(
                dependency,
                src_node=self.nodes[src_node],
                dst_node=self.nodes[dst_node],
            )
            if edge.id in self.edges:
                continue
            self.edges[edge.id] = edge
            self.source_tile_dependency_to_edge[dependency.id] = edge.id
            self.per_processor_edges.setdefault(edge.src_processor, []).append(edge.id)
            if edge.dst_processor != edge.src_processor:
                self.per_processor_edges.setdefault(edge.dst_processor, []).append(edge.id)

    def _add_node(self, node: ProgramNode, action_id: str) -> None:
        if node.id in self.nodes:
            raise ValueError(f"duplicate program node id: {node.id}")
        if action_id in self.action_to_node:
            raise ValueError(f"duplicate action-to-node mapping: {action_id}")
        self.nodes[node.id] = node
        self.action_to_node[action_id] = node.id
        self.per_processor_nodes.setdefault(node.processor, []).append(node.id)

    def _add_external_precondition(
        self,
        dependency: TileDependency,
        *,
        src_node: str | None,
        dst_node: str | None,
    ) -> None:
        precondition_id = f"external_precondition:{dependency.id}"
        self.external_preconditions[precondition_id] = {
            "id": precondition_id,
            "source_tile_dependency_id": dependency.id,
            "dependency_kind": dependency.dependency_kind,
            "src": dependency.src,
            "dst": dependency.dst,
            "src_node": src_node,
            "dst_node": dst_node,
            "reason": _external_precondition_reason(src_node=src_node, dst_node=dst_node),
            "attrs": dependency.attrs,
        }

    def _add_micro_block_index(self) -> None:
        for block_id, block in sorted(self.tile_program.tile_micro_blocks.items()):
            node_ids: list[str] = []
            missing_action_ids: list[str] = []
            for action_id in block.action_ids:
                node_id = self.action_to_node.get(action_id)
                if node_id is None:
                    missing_action_ids.append(action_id)
                    continue
                node_ids.append(node_id)
            self.micro_blocks[block_id] = {
                "block_id": block.block_id,
                "processor": block.processor,
                "block_kind": block.block_kind,
                "source_phase_id": block.source_phase_id,
                "loop_region_id": block.loop_region_id,
                "loop_instance_id": (
                    f"k{block.loop_instance_id}"
                    if block.loop_instance_id is not None
                    else None
                ),
                "loop_instance_index": block.loop_instance_id,
                "loop_axis": block.loop_axis,
                "fold_policy": block.fold_policy,
                "action_ids": list(block.action_ids),
                "node_ids": node_ids,
                "missing_action_ids": missing_action_ids,
                "route_action_ids": list(block.route_action_ids),
                "compute_action_ids": list(block.compute_action_ids),
                "store_action_ids": list(block.store_action_ids),
                "input_visibility_refs": list(block.input_visibility_refs),
                "output_visibility_refs": list(block.output_visibility_refs),
                "input_value_refs": list(block.input_value_refs),
                "output_value_refs": list(block.output_value_refs),
            }

    def _add_loop_region_index(self) -> None:
        for loop_id, loop in sorted(self.tile_program.tile_loop_regions.items()):
            action_ids_by_instance: dict[str, list[str]] = {}
            node_ids_by_instance: dict[str, list[str]] = {}
            micro_block_ids_by_instance: dict[str, list[str]] = {}
            missing_action_ids: list[str] = []
            for instance in loop.body_instances:
                instance_key = f"k{instance.instance_id}"
                action_ids = list(instance.action_ids)
                action_ids_by_instance[instance_key] = action_ids
                micro_block_ids_by_instance[instance_key] = list(instance.micro_block_ids)
                node_ids: list[str] = []
                for action_id in action_ids:
                    node_id = self.action_to_node.get(action_id)
                    if node_id is None:
                        missing_action_ids.append(action_id)
                        continue
                    node_ids.append(node_id)
                node_ids_by_instance[instance_key] = node_ids

            self.loop_regions[loop_id] = {
                "loop_id": loop.loop_id,
                "processor": loop.processor,
                "source_phase_id": loop.source_phase_id,
                "source_action": loop.source_action,
                "source_chip_op": loop.source_chip_op,
                "loop_axis": loop.loop_axis,
                "repeat_count": loop.repeat_count,
                "closure_shape": loop.closure_shape,
                "fold_policy": loop.fold_policy,
                "carried_refs": list(loop.carried_refs),
                "captured_refs": list(loop.captured_refs),
                "loop_variant_refs": list(loop.loop_variant_refs),
                "loop_invariant_refs": list(loop.loop_invariant_refs),
                "grouping": loop.grouping,
                "action_ids_by_instance": action_ids_by_instance,
                "node_ids_by_instance": node_ids_by_instance,
                "micro_block_ids_by_instance": micro_block_ids_by_instance,
                "missing_action_ids": missing_action_ids,
                "source_region_path": _loop_region_path(loop),
            }


def _route_node(
    action: TileRouteAction,
    memberships: tuple[dict[str, Any], ...],
    micro_block_payload: dict[str, Any],
) -> ProgramNode:
    payload = {
        "tile_route_group_id": action.tile_route_group_id,
        "logical_route_edge_id": action.logical_route_edge_id,
        "logical_route_step_id": action.logical_route_step_id,
        "bundle_id": action.bundle_id,
        "execution_processor": action.execution_processor,
        "endpoint_processor": action.endpoint_processor,
        "src_processor": action.src_processor,
        "dst_processor": action.dst_processor,
        "step_kind": action.step_kind,
        "position": action.position,
        "operand_role": action.operand_role,
        "k_index": action.k_index,
        "source_tile_ref": action.source_tile_ref,
        "produces_endpoint_ref": action.produces_endpoint_ref,
        "attrs": action.attrs,
    }
    payload.update(_loop_payload(action.id, memberships))
    payload.update(micro_block_payload)
    return ProgramNode(
        id=_node_id("route", action.id),
        node_kind="route_materialize",
        processor=action.execution_processor,
        source_action_id=action.id,
        source_action_kind="tile_route_action",
        source_phase_id=None,
        tile_refs=(action.source_tile_ref, action.produces_endpoint_ref),
        payload=payload,
    )


def _compute_node(
    action: TileComputeAction,
    memberships: tuple[dict[str, Any], ...],
    micro_block_payload: dict[str, Any],
) -> ProgramNode:
    tile_refs = tuple(
        str(ref)
        for ref in (
            *action.input_refs,
            *action.output_refs,
            action.attrs.get("accumulator_view_ref"),
            action.attrs.get("member_value_ref"),
        )
        if ref is not None
    )
    payload = {
        "compute_kind": action.compute_kind,
        "input_refs": list(action.input_refs),
        "output_refs": list(action.output_refs),
        "depends_on": list(action.depends_on),
        "attrs": action.attrs,
    }
    payload.update(_loop_payload(action.id, memberships))
    payload.update(micro_block_payload)
    return ProgramNode(
        id=_node_id("compute", action.id),
        node_kind="tile_compute",
        processor=action.processor,
        source_action_id=action.id,
        source_action_kind="tile_compute_action",
        source_phase_id=action.phase_id,
        tile_refs=tile_refs,
        payload=payload,
    )


def _store_node(
    action: TileStoreAction,
    memberships: tuple[dict[str, Any], ...],
    micro_block_payload: dict[str, Any],
) -> ProgramNode:
    source_final_tile = action.attrs.get("source_final_tile", {})
    if not isinstance(source_final_tile, dict):
        source_final_tile = {}
    tile_refs = tuple(
        str(ref)
        for ref in (
            *action.input_refs,
            *action.output_refs,
            source_final_tile.get("tile_ref"),
            source_final_tile.get("tile_scope_ref"),
        )
        if ref is not None
    )
    payload = {
        "input_refs": list(action.input_refs),
        "output_refs": list(action.output_refs),
        "depends_on": list(action.depends_on),
        "dst_sram_tensor_id": action.attrs.get("dst_sram_tensor_id"),
        "dst_region": action.attrs.get("dst_region"),
        "source_final_tile": source_final_tile,
        "store_index": action.attrs.get("store_index"),
        "store_granularity": action.attrs.get("store_granularity"),
        "attrs": action.attrs,
    }
    payload.update(_loop_payload(action.id, memberships))
    payload.update(micro_block_payload)
    return ProgramNode(
        id=_node_id("store", action.id),
        node_kind="tile_store",
        processor=action.processor,
        source_action_id=action.id,
        source_action_kind="tile_store_action",
        source_phase_id=action.phase_id,
        tile_refs=tile_refs,
        payload=payload,
    )


def _edge_from_dependency(
    dependency: TileDependency,
    *,
    src_node: ProgramNode,
    dst_node: ProgramNode,
) -> ProgramEdge:
    return ProgramEdge(
        id=_edge_id(dependency.id),
        edge_kind=_edge_kind(dependency),
        src_node=src_node.id,
        dst_node=dst_node.id,
        src_processor=src_node.processor,
        dst_processor=dst_node.processor,
        source_tile_dependency_id=dependency.id,
        payload={
            "dependency_kind": dependency.dependency_kind,
            "logical_route_edge_id": dependency.logical_route_edge_id,
            "tile_route_group_id": dependency.tile_route_group_id,
            "src_action_id": dependency.src,
            "dst_action_id": dependency.dst,
            "attrs": dependency.attrs,
        },
    )


def _build_action_loop_memberships(
    tile_program: ProcessorTileProgram,
) -> dict[str, tuple[dict[str, Any], ...]]:
    sequence_index_by_loop: dict[str, int] = {}
    for stream in tile_program.programs.values():
        for index, item in enumerate(stream.program_sequence):
            if item.item_kind == "tile_loop":
                sequence_index_by_loop[item.ref_id] = index

    memberships: dict[str, list[dict[str, Any]]] = {}
    for loop in tile_program.tile_loop_regions.values():
        for instance in loop.body_instances:
            roles_by_action: dict[str, str] = {}
            for action_id in instance.route_action_ids:
                roles_by_action[action_id] = "route"
            for action_id in instance.compute_action_ids:
                roles_by_action[action_id] = "compute"
            for action_id in instance.store_action_ids:
                roles_by_action[action_id] = "store"
            for action_id in instance.action_ids:
                role = roles_by_action.get(action_id, "body_action")
                source_region_path = _loop_action_path(
                    loop=loop,
                    instance_id=instance.instance_id,
                    role=role,
                    action_id=action_id,
                )
                membership = {
                    "loop_region_id": loop.loop_id,
                    "loop_instance_id": f"k{instance.instance_id}",
                    "loop_instance_index": instance.instance_id,
                    "loop_axis": loop.loop_axis,
                    "loop_role": role,
                    "loop_fold_policy": loop.fold_policy,
                    "source_region_path": source_region_path,
                    "debug_origin": {
                        "processor": loop.processor,
                        "program_sequence_index": sequence_index_by_loop.get(loop.loop_id),
                        "loop_region_id": loop.loop_id,
                        "source_phase_id": loop.source_phase_id,
                        "loop_axis": loop.loop_axis,
                        "loop_instance_id": f"k{instance.instance_id}",
                        "loop_instance_index": instance.instance_id,
                        "loop_role": role,
                        "tile_action_id": action_id,
                        "fold_policy": loop.fold_policy,
                        "source_region_path": source_region_path,
                    },
                }
                memberships.setdefault(action_id, []).append(membership)

    return {
        action_id: tuple(sorted(action_memberships, key=_loop_membership_sort_key))
        for action_id, action_memberships in memberships.items()
    }


def _loop_payload(
    action_id: str,
    memberships: tuple[dict[str, Any], ...],
) -> dict[str, Any]:
    membership_rows = [dict(membership) for membership in memberships]
    primary = membership_rows[0] if membership_rows else None
    return {
        "loop_region_id": primary["loop_region_id"] if primary else None,
        "loop_region_ids": [
            str(membership["loop_region_id"])
            for membership in membership_rows
        ],
        "loop_instance_id": primary["loop_instance_id"] if primary else None,
        "loop_instance_ids": [
            str(membership["loop_instance_id"])
            for membership in membership_rows
        ],
        "loop_axis": primary["loop_axis"] if primary else None,
        "loop_role": primary["loop_role"] if primary else None,
        "loop_fold_policy": primary["loop_fold_policy"] if primary else None,
        "loop_membership_count": len(membership_rows),
        "loop_memberships": membership_rows,
        "source_region_path": primary["source_region_path"] if primary else None,
        "source_region_paths": [
            str(membership["source_region_path"])
            for membership in membership_rows
        ],
        "debug_origin": primary["debug_origin"] if primary else None,
        "debug_origins": [
            dict(membership["debug_origin"])
            for membership in membership_rows
        ],
        "tile_action_id": action_id,
    }


def _micro_block_payload(
    tile_program: ProcessorTileProgram,
    action_id: str,
) -> dict[str, Any]:
    block_id = tile_program.action_to_micro_block.get(action_id)
    if block_id is None:
        return {
            "tile_micro_block_id": None,
            "tile_micro_block_kind": None,
            "tile_micro_block_processor": None,
            "tile_micro_block_action_count": 0,
        }
    block = tile_program.tile_micro_blocks[block_id]
    task_assignment = block.attrs.get("task_assignment")
    task_assignment_id = (
        task_assignment.get("assignment_id")
        if isinstance(task_assignment, dict)
        else None
    )
    return {
        "tile_micro_block_id": block.block_id,
        "tile_micro_block_kind": block.block_kind,
        "tile_micro_block_processor": block.processor,
        "tile_micro_block_action_count": len(block.action_ids),
        "tile_micro_block_attrs": dict(block.attrs),
        "task_assignment_id": task_assignment_id,
        "task_assignment": task_assignment,
        "tile_micro_block_loop_region_id": block.loop_region_id,
        "tile_micro_block_loop_instance_id": (
            f"k{block.loop_instance_id}" if block.loop_instance_id is not None else None
        ),
        "tile_micro_block_loop_instance_index": block.loop_instance_id,
        "tile_micro_block_input_visibility_refs": list(block.input_visibility_refs),
        "tile_micro_block_output_visibility_refs": list(block.output_visibility_refs),
        "tile_micro_block_input_value_refs": list(block.input_value_refs),
        "tile_micro_block_output_value_refs": list(block.output_value_refs),
    }


def _loop_region_path(loop: TileLoopRegion) -> str:
    return f"processor={loop.processor}/loop={loop.loop_id}"


def _loop_action_path(
    *,
    loop: TileLoopRegion,
    instance_id: int,
    role: str,
    action_id: str,
) -> str:
    return (
        f"{_loop_region_path(loop)}"
        f"/instance=k{instance_id}/role={role}/action={action_id}"
    )


def _loop_membership_sort_key(membership: dict[str, Any]) -> tuple[str, int, str, str]:
    return (
        str(membership["loop_region_id"]),
        int(membership["loop_instance_index"]),
        str(membership["loop_role"]),
        str(membership["source_region_path"]),
    )


def _edge_kind(dependency: TileDependency) -> str:
    if dependency.dependency_kind == "tile_route_step_dependency":
        return "route_step_order"
    if dependency.dependency_kind == "tile_visibility_endpoint_before_compute":
        return "visibility_dependency"
    if dependency.dependency_kind == "tile_compute_accumulator_chain":
        return "accumulator_dependency"
    if dependency.dependency_kind == "tile_value_before_store":
        return "store_dependency"
    if dependency.dependency_kind == "tile_value_before_compute":
        return "value_dependency"
    return dependency.dependency_kind


def _node_id(prefix: str, action_id: str) -> str:
    return f"program_node:{prefix}:{action_id}"


def _edge_id(dependency_id: str) -> str:
    return f"program_edge:{dependency_id}"


def _external_precondition_reason(*, src_node: str | None, dst_node: str | None) -> str:
    if src_node is None and dst_node is None:
        return "dependency_endpoints_are_not_graph_actions"
    if src_node is None:
        return "source_is_external_tile_or_logical_value"
    return "destination_is_external_tile_or_logical_value"


def _is_acyclic(nodes: dict[str, ProgramNode], edges: dict[str, ProgramEdge]) -> bool:
    outgoing: dict[str, list[str]] = {node_id: [] for node_id in nodes}
    indegree: dict[str, int] = {node_id: 0 for node_id in nodes}
    for edge in edges.values():
        if edge.src_node not in outgoing or edge.dst_node not in indegree:
            continue
        outgoing[edge.src_node].append(edge.dst_node)
        indegree[edge.dst_node] += 1

    ready = [node_id for node_id, degree in indegree.items() if degree == 0]
    visited = 0
    while ready:
        node_id = ready.pop()
        visited += 1
        for next_node in outgoing[node_id]:
            indegree[next_node] -= 1
            if indegree[next_node] == 0:
                ready.append(next_node)
    return visited == len(nodes)


__all__ = [
    "ProgramEdge",
    "ProgramNode",
    "ProgramNodeProgram",
    "lower_processor_tile_to_program_nodes",
]
