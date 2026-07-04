"""DFU3500 legacy execution template binding helpers.

This module is the transitional home for DFU3500 ``legacy_gemm_compat``
template selection.  Binary row planning may call this during Phase 1 only to
preserve behavior while template ownership moves upward into
``TileMicroOpProgram -> Dfu3500TemplateBoundProgram``.

Keep vendor CSV/template knowledge here, not in ``program_bin.py``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from gpdpu_compiler.core.program_legacy_inst import (
    FLOW_UNIT_INST_TYPE,
    LD_UNIT_INST_TYPE,
    ST_UNIT_INST_TYPE,
    LegacyInst,
    legacy_gemm_micro_block_template,
    legacy_maximum_scalar_template,
    legacy_single_value_store_template,
)
from gpdpu_compiler.core.program_micro_ops import TileMicroOp, TileMicroOpProgram


@dataclass(frozen=True)
class TemplateBoundSegment:
    """A backend template segment bound to one tile micro-op."""

    id: str
    source_micro_op_id: str
    source_tile_micro_block_id: str
    role: str
    stage: str
    legacy_ops: tuple[str, ...]
    instruction_ids: tuple[str, ...]
    source_csv_path: str | None = None
    repeat_policy: str = "expanded_debug_or_vendor_repeat_body"
    parameter_bindings: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_micro_op_id": self.source_micro_op_id,
            "source_tile_micro_block_id": self.source_tile_micro_block_id,
            "role": self.role,
            "stage": self.stage,
            "legacy_ops": list(self.legacy_ops),
            "instruction_ids": list(self.instruction_ids),
            "instruction_count": len(self.instruction_ids),
            "source_csv_path": self.source_csv_path,
            "repeat_policy": self.repeat_policy,
            "parameter_bindings": self.parameter_bindings,
        }


@dataclass(frozen=True)
class TemplateBoundInstruction:
    """One legacy instruction row after DFU3500 template binding."""

    id: str
    source_segment_id: str
    source_micro_op_id: str
    source_tile_micro_block_id: str
    source_tile_micro_block_kind: str
    role: str
    stage: str
    legacy_inst: LegacyInst
    local_order: int

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "source_segment_id": self.source_segment_id,
            "source_micro_op_id": self.source_micro_op_id,
            "source_tile_micro_block_id": self.source_tile_micro_block_id,
            "source_tile_micro_block_kind": self.source_tile_micro_block_kind,
            "role": self.role,
            "stage": self.stage,
            "legacy_op": self.legacy_inst.op_name,
            "opcode": self.legacy_inst.opcode,
            "unit_inst_type": self.legacy_inst.unit_inst_type,
            "latency": self.legacy_inst.latency,
            "local_order": self.local_order,
        }


@dataclass
class Dfu3500TemplateBoundProgram:
    """DFU3500 legacy template-bound instruction program.

    This is a Phase-2 shadow IR.  It makes template ownership explicit before
    binary packing, but existing ASM / ABI / binary rows still use the previous
    path until ProgramAsm consumes these records directly.
    """

    chip: str
    source_program: str
    source_ir: str
    template_profile: str
    segments: dict[str, TemplateBoundSegment]
    instructions: dict[str, TemplateBoundInstruction]
    micro_op_to_segments: dict[str, tuple[str, ...]]
    micro_op_to_instructions: dict[str, tuple[str, ...]]
    unsupported_micro_ops: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ir": "dfu3500_template_bound_program",
            "chip": self.chip,
            "source_program": self.source_program,
            "source_ir": self.source_ir,
            "template_profile": self.template_profile,
            "layering_policy": (
                "dfu3500_template_bound_program_consumes_tile_micro_ops;"
                "owns_legacy_csv_template_selection_and_stage_attribution;"
                "program_bin_rows_must_not_rediscover_template_selection"
            ),
            "segments": {
                segment_id: segment.to_plan()
                for segment_id, segment in sorted(self.segments.items())
            },
            "instructions": {
                instruction_id: instruction.to_plan()
                for instruction_id, instruction in sorted(self.instructions.items())
            },
            "micro_op_to_segments": {
                op_id: list(segment_ids)
                for op_id, segment_ids in sorted(self.micro_op_to_segments.items())
            },
            "micro_op_to_instructions": {
                op_id: list(instruction_ids)
                for op_id, instruction_ids in sorted(self.micro_op_to_instructions.items())
            },
            "unsupported_micro_ops": {
                op_id: record
                for op_id, record in sorted(self.unsupported_micro_ops.items())
            },
            "validation": self._validation(),
            "totals": self._totals(),
        }

    def _validation(self) -> dict[str, Any]:
        segment_instruction_ids = {
            instruction_id
            for segment in self.segments.values()
            for instruction_id in segment.instruction_ids
        }
        mapped_instruction_ids = {
            instruction_id
            for instruction_ids in self.micro_op_to_instructions.values()
            for instruction_id in instruction_ids
        }
        return {
            "all_instructions_owned_by_segments": segment_instruction_ids == set(self.instructions),
            "all_instructions_mapped_to_micro_ops": mapped_instruction_ids == set(self.instructions),
            "all_micro_ops_have_template_bindings": all(
                bool(segment_ids) for segment_ids in self.micro_op_to_segments.values()
            ),
            "unsupported_micro_op_count": len(self.unsupported_micro_ops),
        }

    def _totals(self) -> dict[str, Any]:
        stage_counts: dict[str, int] = {}
        op_counts: dict[str, int] = {}
        role_counts: dict[str, int] = {}
        for instruction in self.instructions.values():
            stage_counts[instruction.stage] = stage_counts.get(instruction.stage, 0) + 1
            op_counts[instruction.legacy_inst.op_name] = (
                op_counts.get(instruction.legacy_inst.op_name, 0) + 1
            )
            role_counts[instruction.role] = role_counts.get(instruction.role, 0) + 1
        return {
            "segment_count": len(self.segments),
            "template_bound_instruction_count": len(self.instructions),
            "micro_op_count": len(self.micro_op_to_segments),
            "unsupported_micro_op_count": len(self.unsupported_micro_ops),
            "stage_counts": dict(sorted(stage_counts.items())),
            "legacy_op_counts": dict(sorted(op_counts.items())),
            "role_instruction_counts": dict(sorted(role_counts.items())),
        }


@lru_cache(maxsize=None)
def legacy_gemm_template_for_micro_block_kind(
    block_kind: str,
    *,
    task_index: int = 0,
    template_index: int | None = None,
    input0_preallocated: bool = True,
) -> tuple[LegacyInst, ...]:
    """Return the canonical DFU3500 legacy GEMM template for a micro-block kind."""

    return legacy_gemm_micro_block_template(
        block_kind,
        task_index=task_index,
        template_index=template_index,
        input0_preallocated=input0_preallocated,
    )


def legacy_gemm_template_for_micro_block_kinds(
    kinds: tuple[str, ...],
    *,
    source_id: str,
) -> tuple[LegacyInst, ...]:
    """Resolve a source micro-block kind tuple to a legacy GEMM template.

    Current folded vendor rows are one-template-per-micro-block.  If a row has
    multiple provenance kinds, the first kind remains the existing transitional
    behavior and should disappear once template-bound instructions become the
    authority.
    """

    if not kinds:
        raise ValueError(f"missing source tile micro-block kind for {source_id}")
    return legacy_gemm_template_for_micro_block_refs(kinds, source_id=source_id)


def legacy_gemm_template_for_micro_block_refs(
    kinds: tuple[str, ...],
    *,
    block_ids: tuple[str, ...] = (),
    processor: str | None = None,
    task_index: int = 0,
    source_id: str = "",
) -> tuple[LegacyInst, ...]:
    """Resolve a vendor-facing micro-block to a DFU3500 legacy GEMM template.

    DFU3500 legacy GEMM compatibility is operand-aware: A route forwarding is
    encoded with COPY, while B route forwarding is represented by LDN
    materialization at the consumer side. The tile route graph remains the
    semantic truth; this function only selects the concrete legacy instruction
    envelope for the backend profile.
    """

    if not kinds:
        raise ValueError(f"missing source tile micro-block kind for {source_id}")
    kind = str(kinds[0])
    operand_role = _operand_role_from_block_refs(block_ids, source_id)
    if kind == "route_forward" and operand_role == "B":
        kind = "route_source_materialize"
    return legacy_gemm_template_for_micro_block_kind(
        kind,
        task_index=task_index,
        template_index=_legacy_template_index_for_micro_block(
            kind,
            processor=processor,
        ),
        input0_preallocated=_legacy_input0_preallocated_for_micro_block(
            kind,
            processor=processor,
        ),
    )


def legacy_gemm_template_for_micro_op(
    micro_op: TileMicroOp,
) -> tuple[LegacyInst, ...]:
    """Resolve one tile micro-op to a DFU3500 legacy GEMM template."""

    if (
        micro_op.source_tile_micro_block_kind == "local_compute"
        and micro_op.attrs.get("compute_kind") == "maximum_scalar"
    ):
        return _maximum_scalar_template_for_micro_op(micro_op)
    if (
        micro_op.source_tile_micro_block_kind == "tile_store"
        and micro_op.attrs.get("task_assignment") is None
    ):
        return _single_value_store_template_for_micro_op(micro_op)
    return legacy_gemm_template_for_micro_block_refs(
        (micro_op.source_tile_micro_block_kind,),
        block_ids=(micro_op.source_tile_micro_block_id,),
        processor=micro_op.processor,
        task_index=_micro_op_task_index(micro_op),
        source_id=micro_op.id,
    )


def _maximum_scalar_template_for_micro_op(micro_op: TileMicroOp) -> tuple[LegacyInst, ...]:
    compute_attrs = micro_op.attrs.get("compute_attrs")
    if not isinstance(compute_attrs, dict):
        compute_attrs = {}
    if "scalar" not in compute_attrs:
        raise ValueError("maximum_scalar local compute is missing scalar attr")
    if len(micro_op.input_refs) != 1 or len(micro_op.output_refs) != 1:
        raise ValueError(
            "maximum_scalar local compute expects exactly one input and one output"
        )
    return legacy_maximum_scalar_template(
        input_tag=micro_op.input_refs[0],
        output_tag=micro_op.output_refs[0],
        scalar=float(compute_attrs["scalar"]),
    )


def _single_value_store_template_for_micro_op(
    micro_op: TileMicroOp,
) -> tuple[LegacyInst, ...]:
    if len(micro_op.input_refs) != 1:
        raise ValueError("single-value tile store expects exactly one input")
    return legacy_single_value_store_template(input_tag=micro_op.input_refs[0])


def lower_tile_micro_ops_to_dfu3500_template_bound(
    micro_op_program: TileMicroOpProgram,
    *,
    template_profile: str = "legacy_gemm_compat",
) -> Dfu3500TemplateBoundProgram:
    """Bind tile micro-op roles to current DFU3500 legacy GEMM templates."""

    segments: dict[str, TemplateBoundSegment] = {}
    instructions: dict[str, TemplateBoundInstruction] = {}
    micro_op_to_segments: dict[str, tuple[str, ...]] = {}
    micro_op_to_instructions: dict[str, tuple[str, ...]] = {}
    unsupported_micro_ops: dict[str, dict[str, Any]] = {}

    for micro_op in sorted(micro_op_program.micro_ops.values(), key=lambda op: op.id):
        try:
            template = legacy_gemm_template_for_micro_op(micro_op)
        except ValueError as exc:
            micro_op_to_segments[micro_op.id] = ()
            micro_op_to_instructions[micro_op.id] = ()
            unsupported_micro_ops[micro_op.id] = {
                "reason": str(exc),
                "source_tile_micro_block_id": micro_op.source_tile_micro_block_id,
                "source_tile_micro_block_kind": micro_op.source_tile_micro_block_kind,
                "role": micro_op.role,
                "policy": "reported_not_blocking_non_gemm_shadow_ir",
            }
            continue
        op_segment_ids: list[str] = []
        op_instruction_ids: list[str] = []
        grouped = _group_template_by_stage(template)
        local_order = 0
        for segment_index, (stage, legacy_insts) in enumerate(grouped):
            segment_id = f"template_segment:{micro_op.id}:{segment_index:02d}"
            segment_instruction_ids: list[str] = []
            legacy_ops = tuple(dict.fromkeys(inst.op_name for inst in legacy_insts))
            for inst in legacy_insts:
                instruction_id = f"template_inst:{micro_op.id}:{local_order:04d}"
                instructions[instruction_id] = TemplateBoundInstruction(
                    id=instruction_id,
                    source_segment_id=segment_id,
                    source_micro_op_id=micro_op.id,
                    source_tile_micro_block_id=micro_op.source_tile_micro_block_id,
                    source_tile_micro_block_kind=micro_op.source_tile_micro_block_kind,
                    role=micro_op.role,
                    stage=stage,
                    legacy_inst=inst,
                    local_order=local_order,
                )
                segment_instruction_ids.append(instruction_id)
                op_instruction_ids.append(instruction_id)
                local_order += 1
            segments[segment_id] = TemplateBoundSegment(
                id=segment_id,
                source_micro_op_id=micro_op.id,
                source_tile_micro_block_id=micro_op.source_tile_micro_block_id,
                role=micro_op.role,
                stage=stage,
                legacy_ops=legacy_ops,
                instruction_ids=tuple(segment_instruction_ids),
                parameter_bindings={
                    "source_tile_micro_block_kind": micro_op.source_tile_micro_block_kind,
                    "operand_role": micro_op.attrs.get("operand_role"),
                    "task_index": _micro_op_task_index(micro_op),
                    "legacy_template_index": _legacy_template_index_for_micro_block(
                        micro_op.source_tile_micro_block_kind,
                        processor=micro_op.processor,
                    ),
                    "loop_region_id": micro_op.loop_region_id,
                    "loop_instance_key": micro_op.loop_instance_key,
                },
            )
            op_segment_ids.append(segment_id)
        micro_op_to_segments[micro_op.id] = tuple(op_segment_ids)
        micro_op_to_instructions[micro_op.id] = tuple(op_instruction_ids)

    return Dfu3500TemplateBoundProgram(
        chip=micro_op_program.chip,
        source_program=micro_op_program.source_program,
        source_ir="tile_micro_op_program",
        template_profile=template_profile,
        segments=segments,
        instructions=instructions,
        micro_op_to_segments=micro_op_to_segments,
        micro_op_to_instructions=micro_op_to_instructions,
        unsupported_micro_ops=unsupported_micro_ops,
    )


def _group_template_by_stage(
    template: tuple[LegacyInst, ...],
) -> list[tuple[str, tuple[LegacyInst, ...]]]:
    groups: list[tuple[str, list[LegacyInst]]] = []
    for inst in template:
        stage = _stage_for_legacy_inst(inst)
        if not groups or groups[-1][0] != stage:
            groups.append((stage, []))
        groups[-1][1].append(inst)
    return [(stage, tuple(insts)) for stage, insts in groups]


def _stage_for_legacy_inst(inst: LegacyInst) -> str:
    if inst.unit_inst_type & ST_UNIT_INST_TYPE:
        return "ST"
    if inst.unit_inst_type & FLOW_UNIT_INST_TYPE:
        return "FLOW"
    if inst.unit_inst_type & LD_UNIT_INST_TYPE:
        return "LD"
    return "CAL"


def _operand_role_from_block_refs(
    block_ids: tuple[str, ...],
    source_id: str,
) -> str | None:
    haystack = " ".join((*block_ids, source_id))
    if "_A_" in haystack or ":A_" in haystack or ":A:" in haystack:
        return "A"
    if "_B_" in haystack or ":B_" in haystack or ":B:" in haystack:
        return "B"
    return None


def _micro_op_task_index(micro_op: TileMicroOp) -> int:
    value = micro_op.attrs.get("task_id")
    if value is None:
        return 0
    return int(value)


def _legacy_template_index_for_micro_block(
    block_kind: str,
    *,
    processor: str | None,
) -> int:
    pe_index = _pe_index_for_processor(processor)
    if block_kind in {"accumulator_prepare", "compute_update", "tile_store"}:
        if block_kind == "compute_update":
            return 16 + pe_index
        return pe_index
    if block_kind == "route_source_materialize":
        return pe_index // 4
    if block_kind == "route_forward":
        copy_source_pes = (0, 1, 2, 4, 5, 6, 8, 9, 10, 12, 13, 14)
        if pe_index not in copy_source_pes:
            return 4
        return 4 + copy_source_pes.index(pe_index)
    return 0


def _legacy_input0_preallocated_for_micro_block(
    block_kind: str,
    *,
    processor: str | None,
) -> bool:
    # Vendor GEMM treats row-wise A visibility as already materialized before
    # compute on every consumer, including the last mesh column.  The COPY
    # route edge carries A into the endpoint operand window; compute templates
    # must therefore seed input0 before parsing input1/HMMA rows instead of
    # reallocating A after B.
    return True


def _pe_index_for_processor(processor: str | None) -> int:
    parts = str(processor or "").split("_")
    if len(parts) == 3 and parts[0] == "processor":
        return int(parts[1]) * 4 + int(parts[2])
    return 0


def _processor_col(processor: str | None) -> int:
    parts = str(processor or "").split("_")
    if len(parts) == 3 and parts[0] == "processor":
        return int(parts[2])
    return 0


__all__ = [
    "Dfu3500TemplateBoundProgram",
    "TemplateBoundInstruction",
    "TemplateBoundSegment",
    "legacy_gemm_template_for_micro_block_kind",
    "legacy_gemm_template_for_micro_block_kinds",
    "legacy_gemm_template_for_micro_block_refs",
    "legacy_gemm_template_for_micro_op",
    "lower_tile_micro_ops_to_dfu3500_template_bound",
]
