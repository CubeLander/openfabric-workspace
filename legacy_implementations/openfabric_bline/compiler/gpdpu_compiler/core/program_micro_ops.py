"""Executable tile micro-op IR.

This layer sits between ``ProcessorTileProgram`` and backend template binding.
It names executable roles inside tile micro-blocks without knowing DFU3500 CSV
paths, legacy op names, or binary encoding details.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from gpdpu_compiler.core.program_tile import ProcessorTileProgram, TileMicroBlock


@dataclass(frozen=True)
class TileMicroOp:
    """One executable role derived from a tile micro-block."""

    id: str
    processor: str
    source_tile_micro_block_id: str
    source_tile_micro_block_kind: str
    role: str
    loop_region_id: str | None = None
    loop_instance_key: str | None = None
    input_refs: tuple[str, ...] = ()
    output_refs: tuple[str, ...] = ()
    input_visibility_refs: tuple[str, ...] = ()
    output_visibility_refs: tuple[str, ...] = ()
    source_action_ids: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "processor": self.processor,
            "source_tile_micro_block_id": self.source_tile_micro_block_id,
            "source_tile_micro_block_kind": self.source_tile_micro_block_kind,
            "role": self.role,
            "loop_region_id": self.loop_region_id,
            "loop_instance_key": self.loop_instance_key,
            "input_refs": list(self.input_refs),
            "output_refs": list(self.output_refs),
            "input_visibility_refs": list(self.input_visibility_refs),
            "output_visibility_refs": list(self.output_visibility_refs),
            "source_action_ids": list(self.source_action_ids),
            "attrs": self.attrs,
        }


@dataclass
class TileMicroOpProgram:
    """Whole-chip executable micro-op role program."""

    chip: str
    source_program: str
    source_ir: str
    processor_shape: tuple[int, ...]
    micro_ops: dict[str, TileMicroOp]
    micro_block_to_micro_ops: dict[str, tuple[str, ...]]
    per_processor_micro_ops: dict[str, tuple[str, ...]]

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ir": "tile_micro_op_program",
            "chip": self.chip,
            "source_program": self.source_program,
            "source_ir": self.source_ir,
            "processor_shape": list(self.processor_shape),
            "layering_policy": (
                "tile_micro_op_program_consumes_processor_tile_micro_blocks;"
                "does_not_know_vendor_csv_paths_or_binary_inst_t_encoding"
            ),
            "micro_ops": {
                op_id: op.to_plan()
                for op_id, op in sorted(self.micro_ops.items())
            },
            "micro_block_to_micro_ops": {
                block_id: list(op_ids)
                for block_id, op_ids in sorted(self.micro_block_to_micro_ops.items())
            },
            "per_processor_micro_ops": {
                processor: list(op_ids)
                for processor, op_ids in sorted(self.per_processor_micro_ops.items())
            },
            "validation": self._validation(),
            "totals": self._totals(),
        }

    def _validation(self) -> dict[str, Any]:
        mapped_ids = {
            op_id
            for op_ids in self.micro_block_to_micro_ops.values()
            for op_id in op_ids
        }
        return {
            "all_micro_ops_mapped_from_micro_blocks": mapped_ids == set(self.micro_ops),
            "all_micro_blocks_have_micro_ops": all(
                bool(op_ids) for op_ids in self.micro_block_to_micro_ops.values()
            ),
        }

    def _totals(self) -> dict[str, Any]:
        role_counts: dict[str, int] = {}
        kind_counts: dict[str, int] = {}
        for op in self.micro_ops.values():
            role_counts[op.role] = role_counts.get(op.role, 0) + 1
            kind_counts[op.source_tile_micro_block_kind] = (
                kind_counts.get(op.source_tile_micro_block_kind, 0) + 1
            )
        return {
            "micro_op_count": len(self.micro_ops),
            "source_micro_block_count": len(self.micro_block_to_micro_ops),
            "processor_count": len(self.per_processor_micro_ops),
            "role_counts": dict(sorted(role_counts.items())),
            "source_micro_block_kind_counts": dict(sorted(kind_counts.items())),
        }


def lower_processor_tile_to_micro_ops(
    tile_program: ProcessorTileProgram,
) -> TileMicroOpProgram:
    """Lower tile micro-blocks to executable micro-op roles.

    MVP emits one micro-op per existing ``TileMicroBlock``.  Later phases can
    split ``compute_update`` into operand prepare / core / finalize roles while
    preserving the same source micro-block provenance.
    """

    micro_ops: dict[str, TileMicroOp] = {}
    micro_block_to_micro_ops: dict[str, tuple[str, ...]] = {}
    per_processor: dict[str, list[str]] = {}

    for block_id, block in sorted(tile_program.tile_micro_blocks.items()):
        micro_op = _micro_op_for_block(block)
        micro_ops[micro_op.id] = micro_op
        micro_block_to_micro_ops[block_id] = (micro_op.id,)
        per_processor.setdefault(micro_op.processor, []).append(micro_op.id)

    return TileMicroOpProgram(
        chip=tile_program.chip,
        source_program=tile_program.source_program,
        source_ir="processor_tile_program",
        processor_shape=tile_program.processor_shape,
        micro_ops=micro_ops,
        micro_block_to_micro_ops=micro_block_to_micro_ops,
        per_processor_micro_ops={
            processor: tuple(op_ids)
            for processor, op_ids in sorted(per_processor.items())
        },
    )


def _micro_op_for_block(block: TileMicroBlock) -> TileMicroOp:
    role = _role_for_block(block)
    task_assignment = block.attrs.get("task_assignment")
    if not isinstance(task_assignment, dict):
        task_assignment = {}
    return TileMicroOp(
        id=f"micro_op:{block.block_id}",
        processor=block.processor,
        source_tile_micro_block_id=block.block_id,
        source_tile_micro_block_kind=block.block_kind,
        role=role,
        loop_region_id=block.loop_region_id,
        loop_instance_key=(
            f"k{block.loop_instance_id}"
            if block.loop_instance_id is not None
            else None
        ),
        input_refs=block.input_refs,
        output_refs=block.output_refs,
        input_visibility_refs=block.input_visibility_refs,
        output_visibility_refs=block.output_visibility_refs,
        source_action_ids=block.action_ids,
        attrs={
            "phase2_status": "one_micro_op_per_tile_micro_block",
            "future_split": _future_split_for_block(block),
            "operand_role": block.attrs.get("operand_role"),
            "compute_kind": block.attrs.get("compute_kind"),
            "compute_attrs": block.attrs.get("compute_attrs"),
            "task_assignment": task_assignment or None,
            "task_id": task_assignment.get("task_id"),
            "launch_group_id": task_assignment.get("launch_group_id"),
            "virtual_work_id": task_assignment.get("virtual_work_id"),
            "legacy_wave_id": task_assignment.get("legacy_wave_id"),
            "k_index": block.attrs.get("k_index"),
            "tile_coord": block.attrs.get("tile_coord"),
        },
    )


def _role_for_block(block: TileMicroBlock) -> str:
    if block.block_kind == "route_source_materialize":
        operand_role = str(block.attrs.get("operand_role", "operand"))
        return f"operand_materialize:{operand_role}"
    if block.block_kind == "route_forward":
        return "route_forward"
    if block.block_kind == "accumulator_prepare":
        return "accumulator_prepare"
    if block.block_kind == "compute_update":
        return "compute_core"
    if block.block_kind == "tile_store":
        return "tile_store"
    return block.block_kind


def _future_split_for_block(block: TileMicroBlock) -> tuple[str, ...]:
    if block.block_kind == "compute_update":
        return (
            "compute_operand_prepare",
            "compute_core",
            "compute_accumulator_finalize",
        )
    if block.block_kind == "tile_store":
        return ("tile_store",)
    if block.block_kind == "accumulator_prepare":
        return ("accumulator_prepare",)
    if block.block_kind in {"route_source_materialize", "route_forward"}:
        return (block.block_kind,)
    return ()


__all__ = [
    "TileMicroOp",
    "TileMicroOpProgram",
    "lower_processor_tile_to_micro_ops",
]
