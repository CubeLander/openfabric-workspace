"""Symbolic DFU assembly program derived from packing rows.

This layer assigns packed program nodes to assembly blocks and symbolic
instructions. It intentionally does not encode ``inst_t`` bytes yet; the output
is the last inspectable IR before vendor ABI rows and serializers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gpdpu_compiler.core.dfu3500.legacy_templates import (
    Dfu3500TemplateBoundProgram,
    TemplateBoundInstruction,
    TemplateBoundSegment,
)
from gpdpu_compiler.core.program_nodes import ProgramNode, ProgramNodeProgram
from gpdpu_compiler.core.program_packing import (
    DFUPackingProgram,
    EdgePackingBinding,
    NodePackingBinding,
    PackingInstance,
)


@dataclass
class ProgramAsmBlock:
    """One symbolic assembly block, currently one block per packing instance."""

    id: str
    source_instance_id: str
    source_container_id: str
    source_tile_micro_block_id: str | None
    source_tile_micro_block_kind: str | None
    task_id: str
    processor: str
    subtask_id: str
    subtask_role: str
    instance_key: str
    source_tile_micro_block_ids: list[str] = field(default_factory=list)
    source_tile_micro_block_kinds: list[str] = field(default_factory=list)
    instruction_ids: list[str] = field(default_factory=list)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_instance_id": self.source_instance_id,
            "source_container_id": self.source_container_id,
            "source_tile_micro_block_id": self.source_tile_micro_block_id,
            "source_tile_micro_block_kind": self.source_tile_micro_block_kind,
            "task_id": self.task_id,
            "processor": self.processor,
            "subtask_id": self.subtask_id,
            "subtask_role": self.subtask_role,
            "instance_key": self.instance_key,
            "source_tile_micro_block_ids": list(self.source_tile_micro_block_ids),
            "source_tile_micro_block_kinds": list(self.source_tile_micro_block_kinds),
            "source_tile_micro_block_count": len(self.source_tile_micro_block_ids),
            "instruction_ids": list(self.instruction_ids),
            "instruction_count": len(self.instruction_ids),
        }


@dataclass(frozen=True)
class ProgramAsmInstruction:
    """One symbolic instruction row."""

    id: str
    opcode: str
    stage: str
    asm_block_id: str
    source_node_id: str
    source_action_id: str
    node_kind: str
    task_id: str
    processor: str
    subtask_id: str
    subtask_role: str
    instance_id: str
    instance_key: str
    source_tile_micro_block_id: str | None
    source_tile_micro_block_kind: str | None
    global_index: int
    block_local_index: int
    stage_source: str = "symbolic_opcode_fallback"
    template_bound_segment_ids: tuple[str, ...] = ()
    template_bound_instruction_ids: tuple[str, ...] = ()
    template_bound_instruction_count: int = 0
    symbolic_operands: dict[str, Any] = field(default_factory=dict)
    payload: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "opcode": self.opcode,
            "stage": self.stage,
            "asm_block_id": self.asm_block_id,
            "source_node_id": self.source_node_id,
            "source_action_id": self.source_action_id,
            "node_kind": self.node_kind,
            "task_id": self.task_id,
            "processor": self.processor,
            "subtask_id": self.subtask_id,
            "subtask_role": self.subtask_role,
            "instance_id": self.instance_id,
            "instance_key": self.instance_key,
            "source_tile_micro_block_id": self.source_tile_micro_block_id,
            "source_tile_micro_block_kind": self.source_tile_micro_block_kind,
            "stage_source": self.stage_source,
            "template_bound_segment_ids": list(self.template_bound_segment_ids),
            "template_bound_instruction_ids": list(self.template_bound_instruction_ids),
            "template_bound_instruction_count": self.template_bound_instruction_count,
            "global_index": self.global_index,
            "block_local_index": self.block_local_index,
            "symbolic_operands": self.symbolic_operands,
            "payload": self.payload,
        }


@dataclass(frozen=True)
class ProgramAsmDependency:
    """Dependency between symbolic instructions."""

    id: str
    source_edge_id: str
    edge_kind: str
    src_instruction: str
    dst_instruction: str
    src_block: str
    dst_block: str
    scope: str
    reason: str
    legalized_edge_class: str = "normal_graph_edge"
    vendor_graph_eligible: bool = True
    absorbed_by: str | None = None

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_edge_id": self.source_edge_id,
            "edge_kind": self.edge_kind,
            "src_instruction": self.src_instruction,
            "dst_instruction": self.dst_instruction,
            "src_block": self.src_block,
            "dst_block": self.dst_block,
            "scope": self.scope,
            "reason": self.reason,
            "legalized_edge_class": self.legalized_edge_class,
            "vendor_graph_eligible": self.vendor_graph_eligible,
            "absorbed_by": self.absorbed_by,
        }


@dataclass
class ProgramAsm:
    """Whole-chip symbolic assembly program."""

    chip: str
    source_program: str
    source_ir: str
    processor_shape: tuple[int, ...]
    blocks: dict[str, ProgramAsmBlock]
    instructions: dict[str, ProgramAsmInstruction]
    dependencies: dict[str, ProgramAsmDependency]
    node_to_instruction: dict[str, str]
    edge_to_dependency: dict[str, str]
    repeated_loop_templates: dict[str, dict[str, Any]]
    per_processor_blocks: dict[str, list[str]]
    per_processor_instructions: dict[str, list[str]]
    template_bound_instruction_to_asm_instruction: dict[str, str] = field(default_factory=dict)
    template_bound_segments: dict[str, TemplateBoundSegment] = field(default_factory=dict)
    template_bound_instructions: dict[str, TemplateBoundInstruction] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ir": "program_asm",
            "backend": "dfu3500_symbolic_asm",
            "chip": self.chip,
            "source_program": self.source_program,
            "source_ir": self.source_ir,
            "processor_shape": list(self.processor_shape),
            "layering_policy": (
                "program_asm_consumes_dfu_packing_and_program_nodes;"
                "one_program_node_maps_to_one_symbolic_instruction;"
                "one_packing_instance_maps_to_one_asm_block;"
                "inst_t_binary_encoding_not_started"
            ),
            "asm_policy": {
                "block_unit": "PackingInstance",
                "instruction_unit": "ProgramNode",
                "pc_assignment": "stable_symbolic_global_index",
                "binary_encoding": "out_of_scope",
            },
            "blocks": {
                block_id: block.to_plan()
                for block_id, block in sorted(self.blocks.items())
            },
            "instructions": {
                instruction_id: instruction.to_plan()
                for instruction_id, instruction in sorted(self.instructions.items())
            },
            "dependencies": {
                dependency_id: dependency.to_plan()
                for dependency_id, dependency in sorted(self.dependencies.items())
            },
            "node_to_instruction": dict(sorted(self.node_to_instruction.items())),
            "edge_to_dependency": dict(sorted(self.edge_to_dependency.items())),
            "repeated_loop_templates": dict(sorted(self.repeated_loop_templates.items())),
            "per_processor_blocks": {
                processor: sorted(block_ids)
                for processor, block_ids in sorted(self.per_processor_blocks.items())
            },
            "per_processor_instructions": {
                processor: sorted(instruction_ids)
                for processor, instruction_ids in sorted(self.per_processor_instructions.items())
            },
            "template_bound_instruction_to_asm_instruction": dict(
                sorted(self.template_bound_instruction_to_asm_instruction.items())
            ),
            "template_bound_segment_count": len(self.template_bound_segments),
            "template_bound_instruction_table_count": len(self.template_bound_instructions),
            "validation": self._validation(),
            "totals": self._totals(),
        }

    def _validation(self) -> dict[str, Any]:
        return {
            "all_bound_nodes_have_instructions": len(self.node_to_instruction)
            == len(self.instructions),
            "all_bound_edges_have_dependencies": len(self.edge_to_dependency)
            == len(self.dependencies),
            "all_blocks_nonempty": all(block.instruction_ids for block in self.blocks.values()),
            "template_bound_metadata_attached": bool(
                self.template_bound_instruction_to_asm_instruction
            ),
        }

    def _totals(self) -> dict[str, Any]:
        stage_counts: dict[str, int] = {}
        opcode_counts: dict[str, int] = {}
        block_role_counts: dict[str, int] = {}
        dependency_scope_counts: dict[str, int] = {}
        dependency_class_counts: dict[str, int] = {}
        template_bound_instruction_count = 0

        for instruction in self.instructions.values():
            stage_counts[instruction.stage] = stage_counts.get(instruction.stage, 0) + 1
            opcode_counts[instruction.opcode] = opcode_counts.get(instruction.opcode, 0) + 1
            template_bound_instruction_count += instruction.template_bound_instruction_count
        for block in self.blocks.values():
            role = block.subtask_role
            block_role_counts[role] = block_role_counts.get(role, 0) + 1
        for dependency in self.dependencies.values():
            scope = dependency.scope
            dependency_scope_counts[scope] = dependency_scope_counts.get(scope, 0) + 1
            dependency_class_counts[dependency.legalized_edge_class] = (
                dependency_class_counts.get(dependency.legalized_edge_class, 0) + 1
            )

        return {
            "block_count": len(self.blocks),
            "instruction_count": len(self.instructions),
            "dependency_count": len(self.dependencies),
            "node_to_instruction_count": len(self.node_to_instruction),
            "edge_to_dependency_count": len(self.edge_to_dependency),
            "template_bound_instruction_count": template_bound_instruction_count,
            "template_bound_instruction_to_asm_instruction_count": len(
                self.template_bound_instruction_to_asm_instruction
            ),
            "stage_counts": dict(sorted(stage_counts.items())),
            "opcode_counts": dict(sorted(opcode_counts.items())),
            "block_role_counts": dict(sorted(block_role_counts.items())),
            "dependency_scope_counts": dict(sorted(dependency_scope_counts.items())),
            "dependency_class_counts": dict(sorted(dependency_class_counts.items())),
            "vendor_graph_eligible_dependency_count": sum(
                1
                for dependency in self.dependencies.values()
                if dependency.vendor_graph_eligible
            ),
            "loop_carried_dependency_count": dependency_class_counts.get(
                "loop_carried_edge",
                0,
            ),
        }


def lower_dfu_packing_to_program_asm(
    packing_program: DFUPackingProgram,
    node_program: ProgramNodeProgram,
    template_bound_program: Dfu3500TemplateBoundProgram | None = None,
) -> ProgramAsm:
    """Lower packed program nodes to symbolic assembly blocks."""

    builder = _ProgramAsmBuilder(
        packing_program=packing_program,
        node_program=node_program,
        template_bound_program=template_bound_program,
    )
    return builder.build()


class _ProgramAsmBuilder:
    def __init__(
        self,
        *,
        packing_program: DFUPackingProgram,
        node_program: ProgramNodeProgram,
        template_bound_program: Dfu3500TemplateBoundProgram | None = None,
    ) -> None:
        self.packing_program = packing_program
        self.node_program = node_program
        self.template_bound_program = template_bound_program
        self.blocks: dict[str, ProgramAsmBlock] = {}
        self.instructions: dict[str, ProgramAsmInstruction] = {}
        self.dependencies: dict[str, ProgramAsmDependency] = {}
        self.node_to_instruction: dict[str, str] = {}
        self.edge_to_dependency: dict[str, str] = {}
        self.template_bound_instruction_to_asm_instruction: dict[str, str] = {}
        self.per_processor_blocks: dict[str, list[str]] = {
            processor: [] for processor in node_program.per_processor_nodes
        }
        self.per_processor_instructions: dict[str, list[str]] = {
            processor: [] for processor in node_program.per_processor_nodes
        }

    def build(self) -> ProgramAsm:
        self._emit_blocks_and_instructions()
        self._emit_dependencies()
        return ProgramAsm(
            chip=self.packing_program.chip,
            source_program=self.packing_program.source_program,
            source_ir="dfu_packing_program",
            processor_shape=self.packing_program.processor_shape,
            blocks=self.blocks,
            instructions=self.instructions,
            dependencies=self.dependencies,
            node_to_instruction=self.node_to_instruction,
            edge_to_dependency=self.edge_to_dependency,
            repeated_loop_templates={
                template_id: template.to_plan()
                for template_id, template in self.packing_program.repeated_loop_templates.items()
            },
            per_processor_blocks=self.per_processor_blocks,
            per_processor_instructions=self.per_processor_instructions,
            template_bound_instruction_to_asm_instruction=(
                self.template_bound_instruction_to_asm_instruction
            ),
            template_bound_segments=(
                dict(self.template_bound_program.segments)
                if self.template_bound_program is not None
                else {}
            ),
            template_bound_instructions=(
                dict(self.template_bound_program.instructions)
                if self.template_bound_program is not None
                else {}
            ),
        )

    def _emit_blocks_and_instructions(self) -> None:
        global_index = 0
        for instance_id, instance in sorted(
            self.packing_program.instances.items(),
            key=lambda item: _instance_sort_key(item[1]),
        ):
            ordered_node_ids = self._ordered_instance_nodes(instance)
            for block_local_nodes in _nodes_by_micro_block(
                ordered_node_ids,
                self.packing_program.node_bindings,
            ):
                first_node_id = block_local_nodes[0]
                binding = self.packing_program.node_bindings[first_node_id]
                block = _asm_block(instance, binding)
                self.blocks[block.id] = block
                self.per_processor_blocks.setdefault(block.processor, []).append(block.id)

                block.source_tile_micro_block_ids = _instance_micro_block_ids(
                    block_local_nodes,
                    self.packing_program.node_bindings,
                )
                block.source_tile_micro_block_kinds = _instance_micro_block_kinds(
                    block_local_nodes,
                    self.packing_program.node_bindings,
                )
                for block_local_index, node_id in enumerate(block_local_nodes):
                    node = self.node_program.nodes[node_id]
                    binding = self.packing_program.node_bindings[node_id]
                    instruction = _asm_instruction(
                        node=node,
                        binding=binding,
                        block=block,
                        global_index=global_index,
                        block_local_index=block_local_index,
                        template_bound_program=self.template_bound_program,
                    )
                    self.instructions[instruction.id] = instruction
                    for template_instruction_id in instruction.template_bound_instruction_ids:
                        self.template_bound_instruction_to_asm_instruction[
                            template_instruction_id
                        ] = instruction.id
                    self.node_to_instruction[node_id] = instruction.id
                    self.per_processor_instructions.setdefault(
                        instruction.processor,
                        [],
                    ).append(instruction.id)
                    block.instruction_ids.append(instruction.id)
                    global_index += 1

    def _emit_dependencies(self) -> None:
        for edge_id, edge_binding in sorted(self.packing_program.edge_bindings.items()):
            src_instruction = self.node_to_instruction.get(edge_binding.src_node)
            dst_instruction = self.node_to_instruction.get(edge_binding.dst_node)
            if src_instruction is None or dst_instruction is None:
                continue
            dependency = ProgramAsmDependency(
                id=f"asm_dep:{edge_id}",
                source_edge_id=edge_id,
                edge_kind=edge_binding.edge_kind,
                src_instruction=src_instruction,
                dst_instruction=dst_instruction,
                src_block=self.instructions[src_instruction].asm_block_id,
                dst_block=self.instructions[dst_instruction].asm_block_id,
                scope=_dependency_scope(
                    edge_binding,
                    src_block=self.instructions[src_instruction].asm_block_id,
                    dst_block=self.instructions[dst_instruction].asm_block_id,
                ),
                reason=edge_binding.reason,
                legalized_edge_class=edge_binding.legalized_edge_class,
                vendor_graph_eligible=edge_binding.vendor_graph_eligible,
                absorbed_by=edge_binding.absorbed_by,
            )
            self.dependencies[dependency.id] = dependency
            self.edge_to_dependency[edge_id] = dependency.id

    def _first_binding_for_instance(self, instance_id: str) -> NodePackingBinding | None:
        for binding in self.packing_program.node_bindings.values():
            if binding.instance_id == instance_id:
                return binding
        return None

    def _ordered_instance_nodes(self, instance: PackingInstance) -> list[str]:
        return sorted(
            instance.node_ids,
            key=lambda node_id: _node_instruction_sort_key(self.node_program.nodes[node_id]),
        )


def _asm_block(instance: PackingInstance, binding: NodePackingBinding) -> ProgramAsmBlock:
    return ProgramAsmBlock(
        id=f"asm_block:{instance.id}:{_asm_micro_block_suffix(binding)}",
        source_instance_id=instance.id,
        source_container_id=instance.container_id,
        source_tile_micro_block_id=binding.tile_micro_block_id,
        source_tile_micro_block_kind=binding.tile_micro_block_kind,
        task_id=instance.task_id,
        processor=instance.processor,
        subtask_id=instance.subtask_id,
        subtask_role=binding.subtask_role,
        instance_key=instance.instance_key,
    )


def _nodes_by_micro_block(
    node_ids: list[str],
    node_bindings: dict[str, NodePackingBinding],
) -> list[list[str]]:
    groups: dict[str, list[str]] = {}
    order: list[str] = []
    for node_id in node_ids:
        binding = node_bindings[node_id]
        key = binding.tile_micro_block_id or f"node:{node_id}"
        if key not in groups:
            groups[key] = []
            order.append(key)
        groups[key].append(node_id)
    return [groups[key] for key in order]


def _asm_micro_block_suffix(binding: NodePackingBinding) -> str:
    if binding.tile_micro_block_id is None:
        return _sanitize_id_part(binding.source_action_id)
    return _sanitize_id_part(binding.tile_micro_block_id)


def _instance_micro_block_ids(
    node_ids: list[str],
    node_bindings: dict[str, NodePackingBinding],
) -> list[str]:
    result: list[str] = []
    for node_id in node_ids:
        micro_block_id = node_bindings[node_id].tile_micro_block_id
        if micro_block_id is not None and micro_block_id not in result:
            result.append(micro_block_id)
    return result


def _instance_micro_block_kinds(
    node_ids: list[str],
    node_bindings: dict[str, NodePackingBinding],
) -> list[str]:
    result: list[str] = []
    for node_id in node_ids:
        micro_block_kind = node_bindings[node_id].tile_micro_block_kind
        if micro_block_kind is not None and micro_block_kind not in result:
            result.append(micro_block_kind)
    return result


def _asm_instruction(
    *,
    node: ProgramNode,
    binding: NodePackingBinding,
    block: ProgramAsmBlock,
    global_index: int,
    block_local_index: int,
    template_bound_program: Dfu3500TemplateBoundProgram | None = None,
) -> ProgramAsmInstruction:
    template_segment_ids, template_instruction_ids = _template_bound_refs(
        binding,
        template_bound_program,
    )
    opcode, symbolic_stage = _opcode_and_stage(node)
    template_stage = _template_stage(template_segment_ids, template_bound_program)
    stage = template_stage or symbolic_stage
    if template_stage is not None:
        stage_source = "template_bound_segment"
    elif template_segment_ids:
        stage_source = "mixed_template_bound_segments_symbolic_fallback"
    else:
        stage_source = "symbolic_opcode_fallback"
    return ProgramAsmInstruction(
        id=f"asm_inst:{global_index:06d}",
        opcode=opcode,
        stage=stage,
        asm_block_id=block.id,
        source_node_id=node.id,
        source_action_id=node.source_action_id,
        node_kind=node.node_kind,
        task_id=binding.task_id,
        processor=binding.processor,
        subtask_id=binding.subtask_id,
        subtask_role=binding.subtask_role,
        instance_id=binding.instance_id,
        instance_key=binding.instance_key,
        source_tile_micro_block_id=binding.tile_micro_block_id,
        source_tile_micro_block_kind=binding.tile_micro_block_kind,
        global_index=global_index,
        block_local_index=block_local_index,
        stage_source=stage_source,
        template_bound_segment_ids=template_segment_ids,
        template_bound_instruction_ids=template_instruction_ids,
        template_bound_instruction_count=len(template_instruction_ids),
        symbolic_operands=_symbolic_operands(node),
        payload={
            "source_node_payload": node.payload,
            "source_phase_id": node.source_phase_id,
            "tile_refs": list(node.tile_refs),
            "binary_status": "symbolic_instruction_not_encoded",
            "symbolic_stage_fallback": symbolic_stage,
            "template_bound_status": (
                "template_bound_instruction_refs_attached"
                if template_instruction_ids
                else "template_bound_instruction_refs_unavailable"
            ),
        },
    )


def _template_bound_refs(
    binding: NodePackingBinding,
    template_bound_program: Dfu3500TemplateBoundProgram | None,
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    if template_bound_program is None or binding.tile_micro_block_id is None:
        return (), ()
    micro_op_id = f"micro_op:{binding.tile_micro_block_id}"
    return (
        template_bound_program.micro_op_to_segments.get(micro_op_id, ()),
        template_bound_program.micro_op_to_instructions.get(micro_op_id, ()),
    )


def _template_stage(
    template_segment_ids: tuple[str, ...],
    template_bound_program: Dfu3500TemplateBoundProgram | None,
) -> str | None:
    if template_bound_program is None or not template_segment_ids:
        return None
    stages = {
        template_bound_program.segments[segment_id].stage
        for segment_id in template_segment_ids
        if segment_id in template_bound_program.segments
    }
    if len(stages) == 1:
        return next(iter(stages))
    return None


def _opcode_and_stage(node: ProgramNode) -> tuple[str, str]:
    if node.node_kind == "route_materialize":
        step_kind = str(node.payload.get("step_kind", ""))
        if step_kind == "source_endpoint_visibility":
            return "DFU_COPY_LOCAL_TILE", "LD"
        return "DFU_COPYT_ROUTE_TILE", "LD"
    if node.node_kind == "tile_compute":
        compute_kind = str(node.payload.get("compute_kind", "compute"))
        if compute_kind == "gemm_k_update":
            return "DFU_HMMAL_TILE", "CAL"
        return f"DFU_LOCAL_{compute_kind.upper()}", "CAL"
    if node.node_kind == "tile_store":
        return "DFU_STORE_TILE_TO_SRAM", "ST"
    return "DFU_UNKNOWN", "FLOW"


def _symbolic_operands(node: ProgramNode) -> dict[str, Any]:
    if node.node_kind == "route_materialize":
        return {
            "operand_role": node.payload.get("operand_role"),
            "k_index": node.payload.get("k_index"),
            "execution_processor": node.payload.get("execution_processor"),
            "endpoint_processor": node.payload.get("endpoint_processor"),
            "src_processor": node.payload.get("src_processor"),
            "dst_processor": node.payload.get("dst_processor"),
            "source_tile_ref": node.payload.get("source_tile_ref"),
            "produces_endpoint_ref": node.payload.get("produces_endpoint_ref"),
            "route_edge": node.payload.get("attrs", {}).get("edge", "-")
            if isinstance(node.payload.get("attrs"), dict)
            else "-",
        }
    if node.node_kind == "tile_compute":
        attrs = node.payload.get("attrs", {})
        if not isinstance(attrs, dict):
            attrs = {}
        return {
            "compute_kind": node.payload.get("compute_kind"),
            "k_index": attrs.get("k_index"),
            "a_tile_ref": _tile_ref(attrs.get("a_tile")),
            "b_tile_ref": _tile_ref(attrs.get("b_tile")),
            "accumulator_view_ref": attrs.get("accumulator_view_ref"),
            "member_value_ref": attrs.get("member_value_ref"),
            "output_refs": node.payload.get("output_refs", []),
        }
    if node.node_kind == "tile_store":
        return {
            "dst_sram_tensor_id": node.payload.get("dst_sram_tensor_id"),
            "dst_region": node.payload.get("dst_region"),
            "source_final_tile_ref": _tile_ref(node.payload.get("source_final_tile")),
            "output_refs": node.payload.get("output_refs", []),
        }
    return {}


def _tile_ref(value: Any) -> str | None:
    if isinstance(value, dict):
        ref = value.get("tile_ref")
        if ref is not None:
            return str(ref)
    return None


def _node_instruction_sort_key(node: ProgramNode) -> tuple[int, int, int, str]:
    stage_order = {"route_materialize": 0, "tile_compute": 1, "tile_store": 2}
    payload = node.payload
    k_index = _int_or_default(payload.get("k_index"), 0)
    attrs = payload.get("attrs", {})
    if isinstance(attrs, dict):
        k_index = _int_or_default(attrs.get("k_index"), k_index)
        tile_coord = attrs.get("tile_coord", {})
        if isinstance(tile_coord, dict):
            k_index = _int_or_default(tile_coord.get("k_block"), k_index)
    position = _int_or_default(payload.get("position"), 0)
    return stage_order.get(node.node_kind, 99), k_index, position, node.id


def _instance_sort_key(instance: PackingInstance) -> tuple[int, str, int, int, str]:
    return (
        _task_index(instance.task_id),
        instance.processor,
        _subtask_index(instance.subtask_id),
        _instance_key_index(instance.instance_key),
        instance.id,
    )


def _task_index(task_id: str) -> int:
    digits = "".join(ch for ch in task_id if ch.isdigit())
    return int(digits or 0)


def _subtask_index(subtask_id: str) -> int:
    digits = "".join(ch for ch in subtask_id if ch.isdigit())
    return int(digits or 0)


def _instance_key_index(instance_key: str) -> int:
    if instance_key == "final":
        return 999
    digits = "".join(ch for ch in instance_key if ch.isdigit())
    return int(digits or 0)


def _sanitize_id_part(value: str) -> str:
    result = []
    for char in str(value):
        if char.isalnum():
            result.append(char)
        else:
            result.append("_")
    return "".join(result).strip("_")


def _int_or_default(value: Any, default: int) -> int:
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return default


def _dependency_scope(
    edge_binding: EdgePackingBinding,
    *,
    src_block: str,
    dst_block: str,
) -> str:
    if src_block == dst_block:
        return "same_asm_block"
    if edge_binding.src_instance == edge_binding.dst_instance:
        return "same_instance_cross_block"
    if edge_binding.src_container == edge_binding.dst_container:
        return "same_container_cross_block"
    if edge_binding.scope == "cross_subtask":
        return "cross_subtask_block"
    if edge_binding.scope == "cross_processor_same_task":
        return "cross_processor_block"
    return edge_binding.scope


__all__ = [
    "ProgramAsm",
    "ProgramAsmBlock",
    "ProgramAsmDependency",
    "ProgramAsmInstruction",
    "lower_dfu_packing_to_program_asm",
]
