"""Symbolic template records for B-line executable role bindings.

This module is a staging layer after `binding.py`.  It turns role-binding
results into target/profile template records that are easy to inspect, while
still refusing to emit DFU3500 instructions, ASM, ABI rows, or binary blobs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .binding import SymbolicRoleBinding, SymbolicRoleBindingProgram

TemplateRecordStatus = Literal[
    "template_candidate",
    "symbolic_only",
    "unknown_role",
]


@dataclass(frozen=True)
class SymbolicTemplateRecord:
    """One symbolic target-template record derived from one role binding."""

    id: str
    source_binding_id: str
    source_executable_op_id: str
    source_fiber_op_id: str
    source_fiber_op_kind: str
    role: str
    profile_id: str
    status: TemplateRecordStatus
    stage: str
    template_family: str | None = None
    template_role: str | None = None
    emission_status: str = "symbolic_report_only"
    notes: tuple[str, ...] = ()
    parameter_bindings: dict[str, object] = field(default_factory=dict)
    attrs: dict[str, object] = field(default_factory=dict)

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "source_binding_id": self.source_binding_id,
            "source_executable_op_id": self.source_executable_op_id,
            "source_fiber_op_id": self.source_fiber_op_id,
            "source_fiber_op_kind": self.source_fiber_op_kind,
            "role": self.role,
            "profile_id": self.profile_id,
            "status": self.status,
            "stage": self.stage,
            "template_family": self.template_family,
            "template_role": self.template_role,
            "emission_status": self.emission_status,
            "notes": list(self.notes),
            "parameter_bindings": dict(self.parameter_bindings),
            "attrs": dict(self.attrs),
        }


@dataclass(frozen=True)
class SymbolicTemplateRecordProgram:
    """Symbolic template-record program for B-line inspection."""

    profile_id: str
    records: tuple[SymbolicTemplateRecord, ...]
    diagnostics: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "ir": "experimental_symbolic_template_record_program",
            "profile_id": self.profile_id,
            "records": [record.to_plan() for record in self.records],
            "diagnostics": list(self.diagnostics),
            "layering_policy": (
                "symbolic_template_record_program_consumes_symbolic_role_bindings;"
                "does_not_emit_dfu3500_instructions_or_vendor_binary_rows"
            ),
        }


def lower_symbolic_bindings_to_template_records(
    binding_program: SymbolicRoleBindingProgram,
) -> SymbolicTemplateRecordProgram:
    """Project symbolic role bindings into symbolic template records."""

    records: list[SymbolicTemplateRecord] = []
    for binding in binding_program.bindings:
        records.append(_record_for_binding(binding))
    return SymbolicTemplateRecordProgram(
        profile_id=binding_program.profile_id,
        records=tuple(records),
        diagnostics=binding_program.diagnostics,
    )


def summarize_template_record_program(program: SymbolicTemplateRecordProgram) -> dict[str, object]:
    """Return a stable summary for focused checks and demo output."""

    status_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    template_role_counts: dict[str, int] = {}
    stage_counts: dict[str, int] = {}
    emission_status_counts: dict[str, int] = {}
    symbolic_role_counts: dict[str, int] = {}
    forbidden_tile_micro_block_fields = 0

    for record in program.records:
        status_counts[record.status] = status_counts.get(record.status, 0) + 1
        role_counts[record.role] = role_counts.get(record.role, 0) + 1
        stage_counts[record.stage] = stage_counts.get(record.stage, 0) + 1
        emission_status_counts[record.emission_status] = emission_status_counts.get(record.emission_status, 0) + 1
        if record.template_role is not None:
            template_role_counts[record.template_role] = template_role_counts.get(record.template_role, 0) + 1
        if record.status != "template_candidate":
            symbolic_role_counts[record.role] = symbolic_role_counts.get(record.role, 0) + 1
        for key in (*record.attrs, *record.parameter_bindings):
            if key.startswith("source_tile_micro_block") or key == "tile_micro_block_kind":
                forbidden_tile_micro_block_fields += 1

    return {
        "record_count": len(program.records),
        "status_counts": dict(sorted(status_counts.items())),
        "role_counts": dict(sorted(role_counts.items())),
        "template_role_counts": dict(sorted(template_role_counts.items())),
        "stage_counts": dict(sorted(stage_counts.items())),
        "emission_status_counts": dict(sorted(emission_status_counts.items())),
        "symbolic_role_counts": dict(sorted(symbolic_role_counts.items())),
        "diagnostic_count": len(program.diagnostics),
        "forbidden_tile_micro_block_field_count": forbidden_tile_micro_block_fields,
    }


def _record_for_binding(binding: SymbolicRoleBinding) -> SymbolicTemplateRecord:
    return SymbolicTemplateRecord(
        id=f"template_record:{binding.executable_op_id}",
        source_binding_id=binding.id,
        source_executable_op_id=binding.executable_op_id,
        source_fiber_op_id=binding.source_fiber_op_id,
        source_fiber_op_kind=binding.source_fiber_op_kind,
        role=binding.role,
        profile_id=binding.profile_id,
        status=_record_status(binding),
        stage=_stage_for_role(binding.role),
        template_family=binding.binding_source,
        template_role=binding.template_role,
        notes=binding.notes,
        parameter_bindings={
            "binding_key": "ExecutableFiberOp.role",
            "executable_role": binding.role,
            "candidate_template_role": binding.template_role,
        },
        attrs={
            "source_ir": "SymbolicRoleBindingProgram",
            "source_binding_status": binding.status,
        },
    )


def _record_status(binding: SymbolicRoleBinding) -> TemplateRecordStatus:
    if binding.status == "legacy_template_candidate":
        return "template_candidate"
    if binding.status == "symbolic_unsupported":
        return "symbolic_only"
    return "unknown_role"


def _stage_for_role(role: str) -> str:
    if role in {
        "compute_core:gemm_tile",
        "tile_op:relu",
        "tile_op:clamp_min",
        "tile_op:log10",
        "tile_reduce:local_reduce_max",
        "collective:global_max",
        "tile_op:max_with_floor",
        "tile_op:affine_scale",
    }:
        return "tile_body"
    if role == "accumulator_prepare":
        return "pre_loop"
    if role.startswith("operand_") or role == "compute_core:gemm_update":
        return "loop_body"
    if role in {"accumulator_finalize", "tile_store"}:
        return "post_loop"
    return "unknown"


__all__ = [
    "SymbolicTemplateRecord",
    "SymbolicTemplateRecordProgram",
    "lower_symbolic_bindings_to_template_records",
    "summarize_template_record_program",
]
