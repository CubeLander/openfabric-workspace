"""Report-only DFU3500 role semantics for the experimental B-line.

This module is the next checkpoint after symbolic template records.  It asks a
narrow target question: what DFU3500 semantic evidence do we currently have for
each executable role?  It still does not emit templates, instructions, ASM, ABI
rows, or binary blobs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .template_records import SymbolicTemplateRecord, SymbolicTemplateRecordProgram

ProofStatus = Literal["proven", "unproven", "unsupported", "unknown"]
SemanticKind = Literal[
    "operand_materialization",
    "operand_route_visibility",
    "accumulator_prepare",
    "atomic_gemm_tile",
    "gemm_k_update",
    "accumulator_boundary",
    "local_elementwise_tile_op",
    "local_reduce_tile_op",
    "collective_scalar_tile_op",
    "tile_store",
    "unknown",
]


@dataclass(frozen=True)
class Dfu3500RoleSemanticRecord:
    """DFU3500 semantic evidence record for one symbolic template record."""

    id: str
    source_template_record_id: str
    source_executable_op_id: str
    source_fiber_op_id: str
    role: str
    profile_id: str
    semantic_kind: SemanticKind
    proof_status: ProofStatus
    candidate_mechanism: str
    required_evidence: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()
    attrs: dict[str, object] = field(default_factory=dict)

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "source_template_record_id": self.source_template_record_id,
            "source_executable_op_id": self.source_executable_op_id,
            "source_fiber_op_id": self.source_fiber_op_id,
            "role": self.role,
            "profile_id": self.profile_id,
            "semantic_kind": self.semantic_kind,
            "proof_status": self.proof_status,
            "candidate_mechanism": self.candidate_mechanism,
            "required_evidence": list(self.required_evidence),
            "notes": list(self.notes),
            "attrs": dict(self.attrs),
        }


@dataclass(frozen=True)
class Dfu3500RoleSemanticReport:
    """Report-only DFU3500 semantic support view for B-line roles."""

    profile_id: str
    records: tuple[Dfu3500RoleSemanticRecord, ...]
    diagnostics: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "ir": "experimental_dfu3500_role_semantic_report",
            "profile_id": self.profile_id,
            "records": [record.to_plan() for record in self.records],
            "diagnostics": list(self.diagnostics),
            "layering_policy": (
                "dfu3500_role_semantic_report_consumes_symbolic_template_records;"
                "reports_target_semantic_evidence_without_emitting_templates_or_binary"
            ),
        }


def lower_template_records_to_dfu3500_semantics(
    program: SymbolicTemplateRecordProgram,
) -> Dfu3500RoleSemanticReport:
    """Build a report-only DFU3500 semantic support view."""

    records = tuple(_semantic_record_for_template_record(record) for record in program.records)
    return Dfu3500RoleSemanticReport(
        profile_id=program.profile_id,
        records=records,
        diagnostics=program.diagnostics,
    )


def summarize_dfu3500_semantic_report(report: Dfu3500RoleSemanticReport) -> dict[str, object]:
    """Return stable counts for checks and demo output."""

    proof_status_counts: dict[str, int] = {}
    semantic_kind_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    unproven_role_counts: dict[str, int] = {}
    mechanism_counts: dict[str, int] = {}
    forbidden_tile_micro_block_fields = 0

    for record in report.records:
        proof_status_counts[record.proof_status] = proof_status_counts.get(record.proof_status, 0) + 1
        semantic_kind_counts[record.semantic_kind] = semantic_kind_counts.get(record.semantic_kind, 0) + 1
        role_counts[record.role] = role_counts.get(record.role, 0) + 1
        mechanism_counts[record.candidate_mechanism] = mechanism_counts.get(record.candidate_mechanism, 0) + 1
        if record.proof_status != "proven":
            unproven_role_counts[record.role] = unproven_role_counts.get(record.role, 0) + 1
        for key in record.attrs:
            if key.startswith("source_tile_micro_block") or key == "tile_micro_block_kind":
                forbidden_tile_micro_block_fields += 1

    return {
        "record_count": len(report.records),
        "proof_status_counts": dict(sorted(proof_status_counts.items())),
        "semantic_kind_counts": dict(sorted(semantic_kind_counts.items())),
        "role_counts": dict(sorted(role_counts.items())),
        "unproven_role_counts": dict(sorted(unproven_role_counts.items())),
        "candidate_mechanism_counts": dict(sorted(mechanism_counts.items())),
        "diagnostic_count": len(report.diagnostics),
        "forbidden_tile_micro_block_field_count": forbidden_tile_micro_block_fields,
    }


def _semantic_record_for_template_record(record: SymbolicTemplateRecord) -> Dfu3500RoleSemanticRecord:
    semantic_kind, proof_status, mechanism, evidence, notes = _role_semantic_policy(record)
    return Dfu3500RoleSemanticRecord(
        id=f"dfu3500_semantics:{record.source_executable_op_id}",
        source_template_record_id=record.id,
        source_executable_op_id=record.source_executable_op_id,
        source_fiber_op_id=record.source_fiber_op_id,
        role=record.role,
        profile_id=record.profile_id,
        semantic_kind=semantic_kind,
        proof_status=proof_status,
        candidate_mechanism=mechanism,
        required_evidence=evidence,
        notes=notes,
        attrs={
            "source_ir": "SymbolicTemplateRecordProgram",
            "source_template_record_status": record.status,
            "source_template_role": record.template_role,
        },
    )


def _role_semantic_policy(
    record: SymbolicTemplateRecord,
) -> tuple[SemanticKind, ProofStatus, str, tuple[str, ...], tuple[str, ...]]:
    role = record.role
    if role == "compute_core:gemm_tile":
        return (
            "atomic_gemm_tile",
            "proven",
            "legacy_expanded_gemm_tile_template_span_candidate",
            (),
            (
                "fiber-level GEMM remains atomic; template lowering owns the "
                "internal DFU3500 GEMM tile template expansion rows",
            ),
        )
    if role in {"operand_materialize:A", "operand_materialize:B"}:
        return (
            "operand_materialization",
            "proven",
            "legacy_route_source_materialize_template_candidate",
            (),
            ("legacy GEMM profile has a source materialization template candidate",),
        )
    if role in {"operand_route_recv:A", "operand_route_recv:B", "operand_route_push:A", "operand_route_push:B"}:
        return (
            "operand_route_visibility",
            "proven",
            "legacy_route_forward_or_endpoint_visibility_candidate",
            (),
            ("route visibility has a legacy route/materialize envelope candidate",),
        )
    if role == "accumulator_prepare":
        return (
            "accumulator_prepare",
            "proven",
            "legacy_accumulator_prepare_template_candidate",
            (),
            ("legacy GEMM profile has an accumulator prepare template candidate",),
        )
    if role == "compute_core:gemm_update":
        return (
            "gemm_k_update",
            "proven",
            "legacy_compute_update_template_candidate",
            (),
            ("legacy GEMM profile has a K-update compute template candidate",),
        )
    if role == "tile_store":
        return (
            "tile_store",
            "proven",
            "legacy_tile_store_template_candidate",
            (),
            ("legacy GEMM profile has a tile store template candidate",),
        )
    if role == "accumulator_finalize":
        return (
            "accumulator_boundary",
            "proven",
            "zero_instruction_accumulator_value_boundary",
            (),
            (
                "DFU3500 tensor instruction semantics integrate accumulator update/final value behavior",
                "B-line keeps the boundary explicit even though no standalone instruction is emitted",
            ),
        )
    if role == "tile_op:relu":
        return (
            "local_elementwise_tile_op",
            "proven",
            "dfu3500_explicit_relu_tile_op_candidate",
            (),
            (
                "DFU3500 instruction set supports max-based ReLU through HMAX/FMAX with zero operand",
                "relu_tile remains first-class; exact IMM/HMAX/FMAX row bytes are writer-level blockers",
            ),
        )
    if role == "tile_op:clamp_min":
        return (
            "local_elementwise_tile_op",
            "proven",
            "dfu3500_log10max_fmax_immediate_clamp_candidate",
            (),
            ("clamp_min_tile remains an independent PE-local FiberOp",),
        )
    if role == "tile_op:log10":
        return (
            "local_elementwise_tile_op",
            "proven",
            "dfu3500_log10max_flog2_fmul_log10_2_candidate",
            (),
            ("log10_tile remains an independent PE-local FiberOp",),
        )
    if role == "tile_reduce:local_reduce_max":
        return (
            "local_reduce_tile_op",
            "proven",
            "dfu3500_log10max_shfl_fmax_local_reduce_candidate",
            (),
            ("local_reduce_max_tile remains an independent PE-local FiberOp",),
        )
    if role == "tile_op:affine_scale":
        return (
            "local_elementwise_tile_op",
            "proven",
            "dfu3500_log10max_fadd_fmul_affine_candidate",
            (),
            ("affine_scale_tile remains an independent PE-local FiberOp",),
        )
    if role == "collective:global_max":
        return (
            "collective_scalar_tile_op",
            "unproven",
            "pe00_aggregate_materialize_waiting_for_row_bytes",
            (
                "lower PE00 FMAX combine/store/load contracts into vendor rows",
                "prove runtime execution and scalar receiver visibility",
            ),
            ("global_max_tile remains blocked outside the local FiberOp promotion",),
        )
    if role == "tile_op:max_with_floor":
        return (
            "local_elementwise_tile_op",
            "unproven",
            "dfu3500_log10max_fmax_vector_scalar_waiting_on_global_scalar",
            (
                "bind scalar source produced by global_max_tile",
                "prove PE00 scalar visibility before marking concrete",
            ),
            ("local template shape is known, but scalar input remains blocked",),
        )
    return (
        "unknown",
        "unknown",
        "no_dfu3500_semantic_policy",
        ("add a role semantic policy",),
        ("unknown executable role",),
    )


__all__ = [
    "Dfu3500RoleSemanticRecord",
    "Dfu3500RoleSemanticReport",
    "lower_template_records_to_dfu3500_semantics",
    "summarize_dfu3500_semantic_report",
]
