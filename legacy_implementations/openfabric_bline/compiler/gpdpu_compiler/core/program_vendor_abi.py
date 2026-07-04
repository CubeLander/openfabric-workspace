"""Symbolic vendor ABI projection derived from ``ProgramAsm``.

This layer is the boundary before byte serialization. It projects symbolic asm
blocks into vendor-shaped task/subtask/instance/exeBlock rows and assigns
symbolic per-processor instruction ranges, but it still does not encode
``inst_t`` records or binary config structs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gpdpu_compiler.core.dfu3500.legacy_templates import TemplateBoundInstruction
from gpdpu_compiler.core.program_asm import (
    ProgramAsm,
    ProgramAsmBlock,
)


STAGES = ("LD", "CAL", "FLOW", "ST", "END")
EDGE_SLOT_COUNT = 4
INVALID_PE_POS = [0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF]
FOLDED_REPEAT_MODE = "emit_vendor_rows"


@dataclass(frozen=True)
class VendorTaskRow:
    """Global vendor task row."""

    id: str
    task_index: int
    active_subtask_ids: tuple[str, ...]
    valid_exeblock_count: int
    instance_count: int

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_index": self.task_index,
            "active_subtask_ids": list(self.active_subtask_ids),
            "active_subtask_count": len(self.active_subtask_ids),
            "valid_exeblock_count": self.valid_exeblock_count,
            "instance_count": self.instance_count,
            "binary_encoded": False,
        }


@dataclass(frozen=True)
class VendorSubtaskRow:
    """Global vendor subtask row scoped by task and logical subtask."""

    id: str
    task_id: str
    task_index: int
    subtask_id: str
    subtask_index: int
    role: str
    instance_keys: tuple[str, ...]
    valid_exeblock_ids: tuple[str, ...]
    repeat_mode: str = "expanded_debug_rows"
    repeat_semantics: str | None = None
    template_instance_key: str | None = None
    folded_from_instance_keys: tuple[str, ...] = ()
    instances_amount_override: int | None = None

    def to_plan(self) -> dict[str, Any]:
        instances_amount = (
            self.instances_amount_override
            if self.instances_amount_override is not None
            else len(self.instance_keys)
        )
        return {
            "id": self.id,
            "task_id": self.task_id,
            "task_index": self.task_index,
            "subtask_id": self.subtask_id,
            "subtask_index": self.subtask_index,
            "role": self.role,
            "instance_keys": list(self.instance_keys),
            "instances_amount": instances_amount,
            "valid_exeblock_ids": list(self.valid_exeblock_ids),
            "valid_exe_blocks": len(self.valid_exeblock_ids),
            "repeat_mode": self.repeat_mode,
            "repeat_semantics": self.repeat_semantics,
            "template_instance_key": self.template_instance_key,
            "folded_from_instance_keys": list(self.folded_from_instance_keys),
            "binary_encoded": False,
        }


@dataclass(frozen=True)
class VendorInstanceRow:
    """Global shared vendor instance row."""

    id: str
    task_id: str
    task_index: int
    vendor_subtask_id: str
    subtask_index: int
    instance_key: str
    subtask_instance_index: int
    source_asm_block_ids: tuple[str, ...]
    source_instruction_ids: tuple[str, ...]

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "task_id": self.task_id,
            "task_index": self.task_index,
            "vendor_subtask_id": self.vendor_subtask_id,
            "subtask_index": self.subtask_index,
            "instance_key": self.instance_key,
            "subtask_instance_index": self.subtask_instance_index,
            "source_asm_block_ids": list(self.source_asm_block_ids),
            "source_instruction_ids": list(self.source_instruction_ids),
            "source_asm_block_count": len(self.source_asm_block_ids),
            "source_instruction_count": len(self.source_instruction_ids),
            "binary_encoded": False,
        }


@dataclass(frozen=True)
class VendorInstructionRange:
    """Symbolic PC range for one stage of one exeBlock row."""

    id: str
    vendor_exeblock_id: str
    task_id: str
    processor: str
    pe: str
    stage: str
    start_pc: int
    end_pc: int
    instruction_ids: tuple[str, ...]
    template_bound_instruction_ids: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "vendor_exeblock_id": self.vendor_exeblock_id,
            "task_id": self.task_id,
            "processor": self.processor,
            "pe": self.pe,
            "stage": self.stage,
            "start_pc": self.start_pc,
            "end_pc": self.end_pc,
            "instruction_count": len(self.instruction_ids),
            "instruction_ids": list(self.instruction_ids),
            "template_bound_instruction_ids": list(self.template_bound_instruction_ids),
            "template_bound_instruction_count": len(self.template_bound_instruction_ids),
            "pc_unit": "symbolic_inst_t_record_index",
            "range_semantics": "inclusive_start_exclusive_end",
            "binary_encoded": False,
        }


@dataclass(frozen=True)
class VendorExeBlockRow:
    """PE-local vendor exeBlock row."""

    id: str
    source_asm_block_id: str
    task_id: str
    task_index: int
    vendor_subtask_id: str
    subtask_index: int
    role: str
    processor: str
    pe: str
    pe_pos: tuple[int, int, int]
    pe_local_block_idx: int
    instance_key: str
    source_tile_micro_block_ids: tuple[str, ...]
    source_tile_micro_block_kinds: tuple[str, ...]
    instruction_ids: tuple[str, ...]
    instruction_range_ids: tuple[str, ...]
    predecessor_ids: tuple[str, ...]
    successor_ids: tuple[str, ...]
    predecessor_overflow_count: int
    successor_overflow_count: int
    stage_start_pc: dict[str, int]
    stage_instruction_counts: dict[str, int]

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_asm_block_id": self.source_asm_block_id,
            "task_id": self.task_id,
            "task_index": self.task_index,
            "vendor_subtask_id": self.vendor_subtask_id,
            "subtask_index": self.subtask_index,
            "role": self.role,
            "processor": self.processor,
            "pe": self.pe,
            "pe_pos": list(self.pe_pos),
            "block_idx": self.pe_local_block_idx,
            "instance_key": self.instance_key,
            "source_tile_micro_block_ids": list(self.source_tile_micro_block_ids),
            "source_tile_micro_block_kinds": list(self.source_tile_micro_block_kinds),
            "source_tile_micro_block_count": len(self.source_tile_micro_block_ids),
            "instruction_ids": list(self.instruction_ids),
            "instruction_range_ids": list(self.instruction_range_ids),
            "instruction_count": len(self.instruction_ids),
            "predecessors": list(self.predecessor_ids),
            "successors": list(self.successor_ids),
            "predecessor_overflow_count": self.predecessor_overflow_count,
            "successor_overflow_count": self.successor_overflow_count,
            "req_activations": len(self.predecessor_ids) + self.predecessor_overflow_count,
            "child_amount": len(self.successor_ids) + self.successor_overflow_count,
            "stage_start_pc": dict(self.stage_start_pc),
            "stage_instruction_counts": dict(self.stage_instruction_counts),
            "ld_stage_inst_amount": self.stage_instruction_counts.get("LD", 0),
            "cal_stage_inst_amount": self.stage_instruction_counts.get("CAL", 0),
            "flow_stage_inst_amount": self.stage_instruction_counts.get("FLOW", 0),
            "st_stage_inst_amount": self.stage_instruction_counts.get("ST", 0),
            "binary_encoded": False,
        }


@dataclass(frozen=True)
class VendorGraphEdge:
    """Cross-exeBlock dependency edge for vendor graph ABI."""

    id: str
    source_asm_dependency_id: str
    edge_kind: str
    src_exeblock_id: str
    dst_exeblock_id: str
    src_pe: str
    dst_pe: str
    scope: str
    reason: str

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_asm_dependency_id": self.source_asm_dependency_id,
            "edge_kind": self.edge_kind,
            "src_exeblock_id": self.src_exeblock_id,
            "dst_exeblock_id": self.dst_exeblock_id,
            "src_pe": self.src_pe,
            "dst_pe": self.dst_pe,
            "scope": self.scope,
            "reason": self.reason,
            "binary_encoded": False,
        }


@dataclass
class ProgramVendorABI:
    """Whole-program symbolic vendor ABI projection."""

    chip: str
    source_program: str
    source_ir: str
    processor_shape: tuple[int, ...]
    vendor_tasks: dict[str, VendorTaskRow]
    vendor_subtasks: dict[str, VendorSubtaskRow]
    vendor_instances: dict[str, VendorInstanceRow]
    vendor_exeblocks: dict[str, VendorExeBlockRow]
    instruction_ranges: dict[str, VendorInstructionRange]
    vendor_graph_edges: dict[str, VendorGraphEdge]
    asm_block_to_exeblock: dict[str, str]
    asm_instruction_to_range: dict[str, str]
    repeated_loop_templates: dict[str, dict[str, Any]]
    folded_vendor_report: dict[str, Any]
    pe_instruction_images: dict[str, dict[str, Any]]
    template_bound_instructions: dict[str, TemplateBoundInstruction] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ir": "program_vendor_abi",
            "backend": "dfu3500_symbolic_vendor_abi",
            "chip": self.chip,
            "source_program": self.source_program,
            "source_ir": self.source_ir,
            "processor_shape": list(self.processor_shape),
            "layering_policy": (
                "program_vendor_abi_consumes_program_asm;"
                "task_subtask_instance_exeblock_rows_are_symbolic;"
                "pc_ranges_are_symbolic_inst_t_indices;"
                "binary_serialization_not_started"
            ),
            "vendor_policy": {
                "task_rows": "global_task_rows",
                "subtask_rows": "global_task_subtask_rows",
                "instance_rows": "global_shared_subtask_instance_rows",
                "exeblock_rows": "pe_local_execution_block_rows",
                "folded_repeat_mode": FOLDED_REPEAT_MODE,
                "folded_repeat_unit": "whole_subtask_body",
                "edge_slot_count": EDGE_SLOT_COUNT,
                "binary_encoding": "out_of_scope",
            },
            "vendor_tasks": {
                row_id: row.to_plan()
                for row_id, row in sorted(self.vendor_tasks.items())
            },
            "vendor_subtasks": {
                row_id: row.to_plan()
                for row_id, row in sorted(self.vendor_subtasks.items())
            },
            "vendor_instances": {
                row_id: row.to_plan()
                for row_id, row in sorted(self.vendor_instances.items())
            },
            "vendor_exeblocks": {
                row_id: row.to_plan()
                for row_id, row in sorted(self.vendor_exeblocks.items())
            },
            "instruction_ranges": {
                row_id: row.to_plan()
                for row_id, row in sorted(self.instruction_ranges.items())
            },
            "vendor_graph_edges": {
                row_id: row.to_plan()
                for row_id, row in sorted(self.vendor_graph_edges.items())
            },
            "asm_block_to_exeblock": dict(sorted(self.asm_block_to_exeblock.items())),
            "asm_instruction_to_range": dict(sorted(self.asm_instruction_to_range.items())),
            "repeated_loop_templates": dict(sorted(self.repeated_loop_templates.items())),
            "folded_vendor_report": self.folded_vendor_report,
            "pe_instruction_images": dict(sorted(self.pe_instruction_images.items())),
            "template_bound_instruction_table_count": len(self.template_bound_instructions),
            "validation": self._validation(),
            "totals": self._totals(),
        }

    def _validation(self) -> dict[str, Any]:
        assigned_instruction_count = sum(
            row.end_pc - row.start_pc for row in self.instruction_ranges.values()
        )
        source_instruction_count = len(self.asm_instruction_to_range)
        return {
            "all_vendor_emitted_asm_blocks_have_exeblocks": len(self.asm_block_to_exeblock)
            == len(self.vendor_exeblocks),
            "all_vendor_emitted_asm_instructions_have_ranges": assigned_instruction_count
            == source_instruction_count,
            "all_graph_edges_have_known_exeblocks": all(
                edge.src_exeblock_id in self.vendor_exeblocks
                and edge.dst_exeblock_id in self.vendor_exeblocks
                for edge in self.vendor_graph_edges.values()
            ),
            "all_repeated_loop_templates_are_emit_vendor_rows": all(
                template.get("attrs", {}).get("folded_repeat_mode") == FOLDED_REPEAT_MODE
                for template in self.repeated_loop_templates.values()
            ),
            "k_stream_subtasks_use_folded_repeat": all(
                subtask.repeat_mode == FOLDED_REPEAT_MODE
                and subtask.repeat_semantics == "vendor_instance_repeat_whole_subtask_body"
                and subtask.instances_amount_override == len(subtask.instance_keys)
                for subtask in self.vendor_subtasks.values()
                if subtask.role == "k_stream"
            ),
            "binary_emitted": False,
        }

    def _totals(self) -> dict[str, Any]:
        stage_counts: dict[str, int] = {}
        role_counts: dict[str, int] = {}
        edge_scope_counts: dict[str, int] = {}
        predecessor_overflow = 0
        successor_overflow = 0

        for row in self.instruction_ranges.values():
            stage_counts[row.stage] = stage_counts.get(row.stage, 0) + len(row.instruction_ids)
        for row in self.vendor_exeblocks.values():
            role_counts[row.role] = role_counts.get(row.role, 0) + 1
            predecessor_overflow += row.predecessor_overflow_count
            successor_overflow += row.successor_overflow_count
        for edge in self.vendor_graph_edges.values():
            edge_scope_counts[edge.scope] = edge_scope_counts.get(edge.scope, 0) + 1

        assigned_instruction_count = sum(stage_counts.values())
        return {
            "vendor_task_count": len(self.vendor_tasks),
            "vendor_subtask_count": len(self.vendor_subtasks),
            "vendor_instance_count": len(self.vendor_instances),
            "vendor_exeblock_count": len(self.vendor_exeblocks),
            "instruction_range_count": len(self.instruction_ranges),
            "vendor_graph_edge_count": len(self.vendor_graph_edges),
            "repeated_loop_template_count": len(self.repeated_loop_templates),
            "assigned_instruction_count": assigned_instruction_count,
            "pe_instruction_image_count": len(self.pe_instruction_images),
            "stage_counts": dict(sorted(stage_counts.items())),
            "exeblock_role_counts": dict(sorted(role_counts.items())),
            "edge_scope_counts": dict(sorted(edge_scope_counts.items())),
            "predecessor_overflow_count": predecessor_overflow,
            "successor_overflow_count": successor_overflow,
        }


def lower_program_asm_to_vendor_abi(asm_program: ProgramAsm) -> ProgramVendorABI:
    """Project symbolic asm rows into vendor ABI-shaped rows."""

    builder = _ProgramVendorABIBuilder(asm_program)
    return builder.build()


class _ProgramVendorABIBuilder:
    def __init__(self, asm_program: ProgramAsm) -> None:
        self.asm_program = asm_program
        self.vendor_tasks: dict[str, VendorTaskRow] = {}
        self.vendor_subtasks: dict[str, VendorSubtaskRow] = {}
        self.vendor_instances: dict[str, VendorInstanceRow] = {}
        self.vendor_exeblocks: dict[str, VendorExeBlockRow] = {}
        self.instruction_ranges: dict[str, VendorInstructionRange] = {}
        self.vendor_graph_edges: dict[str, VendorGraphEdge] = {}
        self.asm_block_to_exeblock: dict[str, str] = {}
        self.asm_instruction_to_range: dict[str, str] = {}
        self.pe_instruction_images: dict[str, dict[str, Any]] = {}
        self.template_instance_key_by_subtask = self._template_instance_keys_by_subtask()

    def build(self) -> ProgramVendorABI:
        block_ranges = self._emit_instruction_ranges()
        self._emit_exeblocks(block_ranges)
        self._emit_graph_edges()
        self._emit_subtasks_and_instances()
        self._emit_tasks()
        self._emit_pe_instruction_images()
        return ProgramVendorABI(
            chip=self.asm_program.chip,
            source_program=self.asm_program.source_program,
            source_ir="program_asm",
            processor_shape=self.asm_program.processor_shape,
            vendor_tasks=self.vendor_tasks,
            vendor_subtasks=self.vendor_subtasks,
            vendor_instances=self.vendor_instances,
            vendor_exeblocks=self.vendor_exeblocks,
            instruction_ranges=self.instruction_ranges,
            vendor_graph_edges=self.vendor_graph_edges,
            asm_block_to_exeblock=self.asm_block_to_exeblock,
            asm_instruction_to_range=self.asm_instruction_to_range,
            repeated_loop_templates=self._vendor_repeated_loop_templates(),
            folded_vendor_report=self._build_folded_vendor_report(),
            pe_instruction_images=self.pe_instruction_images,
            template_bound_instructions=dict(self.asm_program.template_bound_instructions),
        )

    def _emit_instruction_ranges(self) -> dict[str, list[str]]:
        pc_by_processor: dict[str, int] = {}
        block_ranges: dict[str, list[str]] = {}
        for block_id, block in sorted(
            self.asm_program.blocks.items(),
            key=lambda item: _block_sort_key(item[1]),
        ):
            if not self._is_vendor_emitted_block(block):
                continue
            instructions = [
                self.asm_program.instructions[instruction_id]
                for instruction_id in block.instruction_ids
            ]
            ranges_for_block: list[str] = []
            for stage in STAGES:
                if stage == "END":
                    continue
                stage_instructions = [
                    instruction
                    for instruction in instructions
                    if instruction.stage == stage
                ]
                if not stage_instructions:
                    continue
                processor = block.processor
                start_pc = pc_by_processor.get(processor, 0)
                end_pc = start_pc + len(stage_instructions)
                pc_by_processor[processor] = end_pc
                range_id = f"vir:{len(self.instruction_ranges):06d}"
                vendor_exeblock_id = _vendor_exeblock_id(block)
                row = VendorInstructionRange(
                    id=range_id,
                    vendor_exeblock_id=vendor_exeblock_id,
                    task_id=block.task_id,
                    processor=processor,
                    pe=_processor_to_pe(processor),
                    stage=stage,
                    start_pc=start_pc,
                    end_pc=end_pc,
                    instruction_ids=tuple(instruction.id for instruction in stage_instructions),
                    template_bound_instruction_ids=tuple(
                        template_instruction_id
                        for instruction in stage_instructions
                        for template_instruction_id in instruction.template_bound_instruction_ids
                    ),
                )
                self.instruction_ranges[range_id] = row
                ranges_for_block.append(range_id)
                for instruction in stage_instructions:
                    self.asm_instruction_to_range[instruction.id] = range_id
            block_ranges[block_id] = ranges_for_block
        return block_ranges

    def _emit_exeblocks(self, block_ranges: dict[str, list[str]]) -> None:
        pe_local_index: dict[str, int] = {}
        predecessor_map, successor_map = self._block_dependency_maps()
        for block_id, block in sorted(
            self.asm_program.blocks.items(),
            key=lambda item: _block_sort_key(item[1]),
        ):
            if not self._is_vendor_emitted_block(block):
                continue
            pe = _processor_to_pe(block.processor)
            pe_index = pe_local_index.get(pe, 0)
            pe_local_index[pe] = pe_index + 1
            exeblock_id = _vendor_exeblock_id(block)
            self.asm_block_to_exeblock[block_id] = exeblock_id

            predecessor_ids, predecessor_overflow = _edge_slots(predecessor_map.get(block_id, []))
            successor_ids, successor_overflow = _edge_slots(successor_map.get(block_id, []))
            stage_start_pc, stage_instruction_counts = self._stage_layout(block_ranges.get(block_id, []))
            row = VendorExeBlockRow(
                id=exeblock_id,
                source_asm_block_id=block_id,
                task_id=block.task_id,
                task_index=_task_index(block.task_id),
                vendor_subtask_id=_vendor_subtask_id(block),
                subtask_index=_subtask_index(block.subtask_id),
                role=block.subtask_role,
                processor=block.processor,
                pe=pe,
                pe_pos=_processor_to_pe_pos(block.processor),
                pe_local_block_idx=pe_index,
                instance_key=block.instance_key,
                source_tile_micro_block_ids=tuple(block.source_tile_micro_block_ids),
                source_tile_micro_block_kinds=tuple(block.source_tile_micro_block_kinds),
                instruction_ids=tuple(block.instruction_ids),
                instruction_range_ids=tuple(block_ranges.get(block_id, [])),
                predecessor_ids=tuple(predecessor_ids),
                successor_ids=tuple(successor_ids),
                predecessor_overflow_count=predecessor_overflow,
                successor_overflow_count=successor_overflow,
                stage_start_pc=stage_start_pc,
                stage_instruction_counts=stage_instruction_counts,
            )
            self.vendor_exeblocks[exeblock_id] = row

    def _emit_graph_edges(self) -> None:
        emitted: set[tuple[str, str, str]] = set()
        for dependency_id, dependency in sorted(self.asm_program.dependencies.items()):
            if not dependency.vendor_graph_eligible:
                continue
            if dependency.scope == "cross_subtask_block":
                continue
            src_exeblock = self.asm_block_to_exeblock.get(dependency.src_block)
            dst_exeblock = self.asm_block_to_exeblock.get(dependency.dst_block)
            if src_exeblock is None or dst_exeblock is None or src_exeblock == dst_exeblock:
                continue
            key = (src_exeblock, dst_exeblock, dependency.edge_kind)
            if key in emitted:
                continue
            emitted.add(key)
            edge_id = f"vge:{len(self.vendor_graph_edges):06d}"
            src = self.vendor_exeblocks[src_exeblock]
            dst = self.vendor_exeblocks[dst_exeblock]
            self.vendor_graph_edges[edge_id] = VendorGraphEdge(
                id=edge_id,
                source_asm_dependency_id=dependency_id,
                edge_kind=dependency.edge_kind,
                src_exeblock_id=src_exeblock,
                dst_exeblock_id=dst_exeblock,
                src_pe=src.pe,
                dst_pe=dst.pe,
                scope=dependency.scope,
                reason=dependency.reason,
            )

    def _emit_subtasks_and_instances(self) -> None:
        grouped_blocks: dict[tuple[str, str], list[ProgramAsmBlock]] = {}
        all_grouped_blocks: dict[tuple[str, str], list[ProgramAsmBlock]] = {}
        for block in self.asm_program.blocks.values():
            key = (block.task_id, block.subtask_id)
            all_grouped_blocks.setdefault(key, []).append(block)
            if self._is_vendor_emitted_block(block):
                grouped_blocks.setdefault(key, []).append(block)

        for (task_id, subtask_id), blocks in sorted(grouped_blocks.items()):
            blocks = sorted(blocks, key=_block_sort_key)
            sample = blocks[0]
            all_blocks = all_grouped_blocks[(task_id, subtask_id)]
            expanded_instance_keys = tuple(
                sorted(
                    {block.instance_key for block in all_blocks},
                    key=_instance_key_index,
                )
            )
            emitted_instance_keys = tuple(
                sorted(
                    {block.instance_key for block in blocks},
                    key=_instance_key_index,
                )
            )
            exeblock_ids = tuple(self.asm_block_to_exeblock[block.id] for block in blocks)
            subtask_row_id = _vendor_subtask_id(sample)
            is_folded_k_stream = sample.subtask_role == "k_stream"
            template_instance_key = (
                self.template_instance_key_by_subtask.get((task_id, subtask_id))
                if is_folded_k_stream
                else None
            )
            self.vendor_subtasks[subtask_row_id] = VendorSubtaskRow(
                id=subtask_row_id,
                task_id=task_id,
                task_index=_task_index(task_id),
                subtask_id=subtask_id,
                subtask_index=_subtask_index(subtask_id),
                role=sample.subtask_role,
                instance_keys=expanded_instance_keys,
                valid_exeblock_ids=exeblock_ids,
                repeat_mode=FOLDED_REPEAT_MODE if is_folded_k_stream else "single_pass",
                repeat_semantics=(
                    "vendor_instance_repeat_whole_subtask_body"
                    if is_folded_k_stream
                    else None
                ),
                template_instance_key=template_instance_key,
                folded_from_instance_keys=(
                    expanded_instance_keys if is_folded_k_stream else ()
                ),
                instances_amount_override=(
                    len(expanded_instance_keys) if is_folded_k_stream else None
                ),
            )
            for instance_index, instance_key in enumerate(emitted_instance_keys):
                instance_blocks = [block for block in blocks if block.instance_key == instance_key]
                instruction_ids = tuple(
                    instruction_id
                    for block in instance_blocks
                    for instruction_id in block.instruction_ids
                )
                row_id = f"vinst:{task_id}:s{_subtask_index(subtask_id)}:i{instance_index}"
                self.vendor_instances[row_id] = VendorInstanceRow(
                    id=row_id,
                    task_id=task_id,
                    task_index=_task_index(task_id),
                    vendor_subtask_id=subtask_row_id,
                    subtask_index=_subtask_index(subtask_id),
                    instance_key=instance_key,
                    subtask_instance_index=instance_index,
                    source_asm_block_ids=tuple(block.id for block in instance_blocks),
                    source_instruction_ids=instruction_ids,
                )

    def _emit_tasks(self) -> None:
        subtask_by_task: dict[str, list[VendorSubtaskRow]] = {}
        instance_by_task: dict[str, list[VendorInstanceRow]] = {}
        for subtask in self.vendor_subtasks.values():
            subtask_by_task.setdefault(subtask.task_id, []).append(subtask)
        for instance in self.vendor_instances.values():
            instance_by_task.setdefault(instance.task_id, []).append(instance)

        for task_id, subtasks in sorted(subtask_by_task.items()):
            subtasks = sorted(subtasks, key=lambda row: row.subtask_index)
            self.vendor_tasks[task_id] = VendorTaskRow(
                id=task_id,
                task_index=_task_index(task_id),
                active_subtask_ids=tuple(row.id for row in subtasks),
                valid_exeblock_count=sum(len(row.valid_exeblock_ids) for row in subtasks),
                instance_count=len(instance_by_task.get(task_id, [])),
            )

    def _emit_pe_instruction_images(self) -> None:
        ranges_by_processor: dict[str, list[VendorInstructionRange]] = {}
        for row in self.instruction_ranges.values():
            ranges_by_processor.setdefault(row.processor, []).append(row)

        for processor, ranges in sorted(ranges_by_processor.items()):
            ranges = sorted(ranges, key=lambda row: row.start_pc)
            assigned = sum(row.end_pc - row.start_pc for row in ranges)
            self.pe_instruction_images[processor] = {
                "processor": processor,
                "pe": _processor_to_pe(processor),
                "range_count": len(ranges),
                "assigned_instruction_count": assigned,
                "range_ids": [row.id for row in ranges],
                "pc_unit": "symbolic_inst_t_record_index",
                "binary_encoded": False,
            }

    def _stage_layout(self, range_ids: list[str]) -> tuple[dict[str, int], dict[str, int]]:
        ranges_by_stage = {
            self.instruction_ranges[range_id].stage: self.instruction_ranges[range_id]
            for range_id in range_ids
        }
        starts: dict[str, int] = {}
        counts: dict[str, int] = {}
        current = min((row.start_pc for row in ranges_by_stage.values()), default=0)
        end_pc = max((row.end_pc for row in ranges_by_stage.values()), default=current)
        for stage in STAGES:
            if stage == "END":
                starts[stage] = end_pc
                counts[stage] = 0
                continue
            row = ranges_by_stage.get(stage)
            if row is None:
                starts[stage] = current
                counts[stage] = 0
            else:
                starts[stage] = row.start_pc
                counts[stage] = row.end_pc - row.start_pc
                current = row.end_pc
        return starts, counts

    def _block_dependency_maps(
        self,
    ) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        predecessors: dict[str, list[str]] = {}
        successors: dict[str, list[str]] = {}
        for dependency in self.asm_program.dependencies.values():
            if not dependency.vendor_graph_eligible:
                continue
            if dependency.scope == "cross_subtask_block":
                continue
            if dependency.src_block == dependency.dst_block:
                continue
            if (
                not self._is_vendor_emitted_block(self.asm_program.blocks[dependency.src_block])
                or not self._is_vendor_emitted_block(
                    self.asm_program.blocks[dependency.dst_block]
                )
            ):
                continue
            predecessors.setdefault(dependency.dst_block, []).append(dependency.id)
            successors.setdefault(dependency.src_block, []).append(dependency.id)
        for values in predecessors.values():
            values.sort()
        for values in successors.values():
            values.sort()
        return predecessors, successors

    def _is_vendor_emitted_block(self, block: ProgramAsmBlock) -> bool:
        if _is_b_route_visibility_block(block):
            return False
        if block.subtask_role != "k_stream":
            return True
        template_key = self.template_instance_key_by_subtask.get(
            (block.task_id, block.subtask_id),
        )
        return template_key is not None and block.instance_key == template_key

    def _template_instance_keys_by_subtask(self) -> dict[tuple[str, str], str]:
        instance_keys: dict[tuple[str, str], set[str]] = {}
        for block in self.asm_program.blocks.values():
            if block.subtask_role != "k_stream":
                continue
            instance_keys.setdefault((block.task_id, block.subtask_id), set()).add(
                block.instance_key
            )
        return {
            key: sorted(values, key=_instance_key_index)[0]
            for key, values in instance_keys.items()
            if values
        }

    def _vendor_repeated_loop_templates(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for template_id, template in self.asm_program.repeated_loop_templates.items():
            row = dict(template)
            attrs = dict(row.get("attrs", {}))
            attrs["source_folded_repeat_mode"] = attrs.get("folded_repeat_mode")
            attrs["folded_repeat_mode"] = FOLDED_REPEAT_MODE
            attrs["folded_repeat_unit"] = "whole_subtask_body"
            attrs["vendor_row_facing"] = True
            attrs["binary_facing"] = False
            row["attrs"] = attrs
            result[template_id] = row
        return result

    def _build_folded_vendor_report(self) -> dict[str, Any]:
        emitted_blocks = set(self.asm_block_to_exeblock)
        asm_block_role_counts = _count_by(
            self.asm_program.blocks.values(),
            lambda block: block.subtask_role,
        )
        vendor_exeblock_role_counts = _count_by(
            self.vendor_exeblocks.values(),
            lambda row: row.role,
        )
        asm_dependency_class_counts = _count_by(
            self.asm_program.dependencies.values(),
            lambda dependency: dependency.legalized_edge_class,
        )
        asm_dependency_scope_counts = _count_by(
            self.asm_program.dependencies.values(),
            lambda dependency: dependency.scope,
        )
        vendor_graph_edge_scope_counts = _count_by(
            self.vendor_graph_edges.values(),
            lambda edge: edge.scope,
        )
        vendor_graph_eligible_dependencies = [
            dependency
            for dependency in self.asm_program.dependencies.values()
            if dependency.vendor_graph_eligible
        ]
        emitted_vendor_graph_dependencies = [
            dependency
            for dependency in vendor_graph_eligible_dependencies
            if dependency.scope != "cross_subtask_block"
            and dependency.src_block in emitted_blocks
            and dependency.dst_block in emitted_blocks
        ]
        absorbed_cross_subtask_store_edges = [
            dependency
            for dependency in vendor_graph_eligible_dependencies
            if dependency.scope == "cross_subtask_block"
        ]
        debug_expanded_edges = [
            dependency
            for dependency in vendor_graph_eligible_dependencies
            if dependency.scope != "cross_subtask_block"
            and (
                dependency.src_block not in emitted_blocks
                or dependency.dst_block not in emitted_blocks
            )
        ]
        emitted_template_internal_edges = [
            dependency
            for dependency in emitted_vendor_graph_dependencies
            if dependency.legalized_edge_class == "internal_template_edge"
        ]
        emitted_normal_graph_edges = [
            dependency
            for dependency in emitted_vendor_graph_dependencies
            if dependency.legalized_edge_class == "normal_graph_edge"
        ]
        effective_k_stream_repeated_executions = sum(
            int(subtask.instances_amount_override or len(subtask.instance_keys))
            for subtask in self.vendor_subtasks.values()
            if subtask.role == "k_stream"
        )

        return {
            "folded_repeat_mode": FOLDED_REPEAT_MODE,
            "folded_repeat_unit": "whole_subtask_body",
            "expanded_asm_block_count": len(self.asm_program.blocks),
            "expanded_k_stream_block_count": asm_block_role_counts.get("k_stream", 0),
            "expanded_finalize_store_block_count": asm_block_role_counts.get(
                "finalize_store",
                0,
            ),
            "folded_vendor_exeblock_count": len(self.vendor_exeblocks),
            "folded_k_stream_exeblock_count": vendor_exeblock_role_counts.get(
                "k_stream",
                0,
            ),
            "folded_finalize_store_exeblock_count": vendor_exeblock_role_counts.get(
                "finalize_store",
                0,
            ),
            "expanded_symbolic_instruction_count": len(self.asm_program.instructions),
            "folded_symbolic_instruction_count": sum(
                row.end_pc - row.start_pc for row in self.instruction_ranges.values()
            ),
            "symbolic_instruction_semantics": (
                "ProgramAsm instruction_count is symbolic ProgramNode-level rows;"
                "not final expanded inst_t count"
            ),
            "expanded_asm_dependency_count": len(self.asm_program.dependencies),
            "expanded_vendor_graph_eligible_dependency_count": len(
                vendor_graph_eligible_dependencies
            ),
            "emitted_vendor_graph_dependency_count_before_dedup": len(
                emitted_vendor_graph_dependencies
            ),
            "folded_vendor_graph_edge_count": len(self.vendor_graph_edges),
            "deduplicated_vendor_graph_edge_count": max(
                0,
                len(emitted_vendor_graph_dependencies) - len(self.vendor_graph_edges),
            ),
            "template_internal_edge_count": asm_dependency_class_counts.get(
                "internal_template_edge",
                0,
            ),
            "emitted_template_internal_edge_count": len(emitted_template_internal_edges),
            "normal_vendor_graph_edge_count": len(emitted_normal_graph_edges),
            "loop_carried_edge_count": asm_dependency_class_counts.get(
                "loop_carried_edge",
                0,
            ),
            "absorbed_loop_carried_edges": asm_dependency_class_counts.get(
                "loop_carried_edge",
                0,
            ),
            "loop_exit_edge_count": len(absorbed_cross_subtask_store_edges),
            "absorbed_cross_subtask_store_edges": len(absorbed_cross_subtask_store_edges),
            "debug_expanded_edge_count": len(debug_expanded_edges),
            "asm_dependency_class_counts": dict(sorted(asm_dependency_class_counts.items())),
            "asm_dependency_scope_counts": dict(sorted(asm_dependency_scope_counts.items())),
            "vendor_graph_edge_scope_counts": dict(sorted(vendor_graph_edge_scope_counts.items())),
            "symbolic_vendor_instance_row_count": len(self.vendor_instances),
            "vendor_instance_count_semantics": (
                "counts symbolic VendorInstanceRow records;"
                "effective repeated executions are represented by VendorSubtaskRow.instances_amount"
            ),
            "effective_k_stream_repeated_execution_count": (
                effective_k_stream_repeated_executions
            ),
            "variant_binding_status": "symbolic_only_not_binary_bound",
            "variant_binding_required_before_binary": [
                "spm_addr_offset",
                "base_addr_row_selection",
                "route_bundle_id",
                "visibility_ref_id",
                "symbolic_immediate_fields",
            ],
        }


def _vendor_exeblock_id(block: ProgramAsmBlock) -> str:
    return (
        f"veb:{block.task_id}:{_processor_to_pe(block.processor)}:"
        f"{block.subtask_id}:{block.instance_key}:{_sanitize_id_part(block.id)}"
    )


def _is_b_route_visibility_block(block: ProgramAsmBlock) -> bool:
    if block.subtask_role != "k_stream":
        return False
    if not set(block.source_tile_micro_block_kinds).issubset(
        {"route_source_materialize", "route_forward"}
    ):
        return False
    haystack = " ".join(block.source_tile_micro_block_ids)
    return "_B_" in haystack or ":B_" in haystack or ":B:" in haystack


def _vendor_subtask_id(block: ProgramAsmBlock) -> str:
    return f"{block.task_id}:vendor_subtask{_subtask_index(block.subtask_id)}"


def _block_sort_key(block: ProgramAsmBlock) -> tuple[int, str, int, int, int, str]:
    return (
        _task_index(block.task_id),
        block.processor,
        _subtask_index(block.subtask_id),
        _instance_key_index(block.instance_key),
        _legacy_micro_block_order(block),
        block.id,
    )


def _legacy_micro_block_order(block: ProgramAsmBlock) -> int:
    """Return DFU3500 legacy exeBlock order inside one folded K body.

    The semantic tile graph does not require route materialization to be emitted
    before compute, because dependencies carry the truth.  The legacy simulator
    ABI, however, lays out each PE-local k_stream body as materialize/load,
    route/flow, then compute.  Keep this as a vendor row ordering policy so tile
    IR and binary serialization do not learn legacy row-number folklore.
    """

    kinds = set(block.source_tile_micro_block_kinds)
    if "accumulator_prepare" in kinds:
        return 0
    if "route_source_materialize" in kinds:
        return 10
    if "route_forward" in kinds:
        return 20
    if "compute_update" in kinds:
        return 30
    if "tile_store" in kinds:
        return 40
    return 99


def _sanitize_id_part(value: str) -> str:
    result = []
    for char in str(value):
        if char.isalnum():
            result.append(char)
        else:
            result.append("_")
    return "".join(result).strip("_")


def _count_by(values: Any, key_fn: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        key = str(key_fn(value))
        counts[key] = counts.get(key, 0) + 1
    return counts


def _task_index(task_id: str) -> int:
    digits = "".join(ch for ch in str(task_id) if ch.isdigit())
    return int(digits or 0)


def _subtask_index(subtask_id: str) -> int:
    digits = "".join(ch for ch in str(subtask_id) if ch.isdigit())
    return int(digits or 0)


def _instance_key_index(instance_key: str) -> int:
    if instance_key == "final":
        return 999
    digits = "".join(ch for ch in str(instance_key) if ch.isdigit())
    return int(digits or 0)


def _processor_to_pe(processor: str) -> str:
    parts = str(processor).split("_")
    if len(parts) == 3 and parts[0] == "processor":
        return f"PE{parts[1]}{parts[2]}"
    return str(processor)


def _processor_to_pe_pos(processor: str) -> tuple[int, int, int]:
    parts = str(processor).split("_")
    if len(parts) == 3 and parts[0] == "processor":
        return (int(parts[1]), int(parts[2]), 0)
    return (0xFFFFFFFF, 0xFFFFFFFF, 0xFFFFFFFF)


def _edge_slots(edge_ids: list[str]) -> tuple[list[str], int]:
    return edge_ids[:EDGE_SLOT_COUNT], max(0, len(edge_ids) - EDGE_SLOT_COUNT)


__all__ = [
    "ProgramVendorABI",
    "VendorExeBlockRow",
    "VendorGraphEdge",
    "VendorInstructionRange",
    "VendorInstanceRow",
    "VendorSubtaskRow",
    "VendorTaskRow",
    "lower_program_asm_to_vendor_abi",
]
