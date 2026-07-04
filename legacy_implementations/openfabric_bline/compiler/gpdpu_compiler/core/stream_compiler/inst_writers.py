"""Fail-closed ``inst_t`` raw-template overlay reports.

This module is not a semantic lowering pass.  It checks whether the current
B-line concrete instruction rows have enough template provenance to be handed
to a raw-template writer, and for exact legacy row selectors it can materialize
raw ``inst_t`` row bytes through the narrow vendor-compatible packer.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Collection, Mapping
from dataclasses import dataclass
from typing import Literal

from gpdpu_compiler.core.dfu3500 import DFU3500_STRUCT_SIZES
from gpdpu_compiler.core.dfu3500.legacy_templates import (
    _legacy_template_index_for_micro_block,
    _stage_for_legacy_inst,
    legacy_gemm_template_for_micro_block_kind,
)
from gpdpu_compiler.core.program_legacy_inst import (
    _legacy_gemm_template_root,
    pack_legacy_inst,
)

from .binary_plan import BinaryInstructionPlan, BinaryLayoutPlan

WriterStatus = Literal["ready", "blocked", "failed"]
SpanCandidateStatus = Literal[
    "catalog_candidate_available",
    "catalog_missing",
    "catalog_unavailable",
]
SpanAuthorityStatus = Literal[
    "blocked_needs_span_policy",
    "partial_route_authority_span_policy_needed",
    "span_policy_candidate_closed",
    "route_span_policy_candidate_closed",
]
ExactSpanHashStatus = Literal[
    "span_hash_candidate_available",
    "blocked_missing_closed_span_policy",
]
RawTemplateRowHashReadinessStatus = Literal[
    "blocked_span_hash_is_not_raw_template_row",
    "ready_raw_template_row_hash",
]
SpanMaterializationStatus = Literal[
    "span_materialization_candidate_available",
    "blocked_missing_span_hash_candidate",
]
ByteMaterializerStatus = Literal[
    "blocked_missing_span_hash_candidate",
    "blocked_missing_exact_span_row_selector",
    "blocked_missing_raw_inst_t_row_bytes",
    "raw_inst_t_row_bytes_available",
]
ExactSpanRowSelectorStatus = Literal[
    "selector_policy_candidate_available",
    "blocked_missing_selector_policy",
    "blocked_missing_candidate_rows",
]

INST_T_STRUCT_NAME = "inst_t"
INST_T_RECORD_SIZE_BYTES = int(DFU3500_STRUCT_SIZES[INST_T_STRUCT_NAME])

FORBIDDEN_FIELD_NAMES = frozenset(
    {
        "source_tile_micro_block_id",
        "source_tile_micro_block_kind",
        "source_tile_micro_block_index",
        "tile_micro_block_kind",
    }
)
FORBIDDEN_FIELD_PREFIXES = ("source_tile_micro_block",)

# S2 intentionally starts with no byte-patch authority for inst_t fields.  The
# field-offset preflight currently reports every inst_t candidate field as
# unresolved, so touching any semantic inst_t field must fail closed.
KNOWN_PATCHABLE_INST_T_FIELDS: frozenset[str] = frozenset()
KNOWN_ZERO_FILL_INST_T_FIELDS: frozenset[str] = frozenset()

RAW_TEMPLATE_BACKED_INST_T_FIELDS = (
    "inst_t.raw_template_row_bytes",
)

ROLE_EVIDENCE_POLICIES: dict[str, dict[str, object]] = {
    "accumulator_prepare": {
        "legacy_block_kind": "accumulator_prepare",
        "legacy_ops": ("LDN", "HMUL", "IMM"),
        "legacy_stages": ("LD", "CAL"),
        "binding_status": "candidate_template_segment_not_single_row",
        "missing_raw_template_bytes_reason": (
            "B-line ACC_PREPARE row summarizes an accumulator_prepare template "
            "segment; no exact legacy row local_order is carried"
        ),
    },
    "operand_materialize:A": {
        "legacy_block_kind": "route_source_materialize",
        "legacy_ops": ("LDN",),
        "legacy_stages": ("LD",),
        "binding_status": "candidate_template_segment_not_single_row",
        "missing_raw_template_bytes_reason": (
            "B-line operand materialize row has no exact legacy LDN local_order"
        ),
    },
    "operand_materialize:B": {
        "legacy_block_kind": "route_source_materialize",
        "legacy_ops": ("LDN",),
        "legacy_stages": ("LD",),
        "binding_status": "candidate_template_segment_not_single_row",
        "missing_raw_template_bytes_reason": (
            "B-line operand materialize row has no exact legacy LDN local_order"
        ),
    },
    "operand_route_recv:A": {
        "legacy_block_kind": "route_forward",
        "legacy_ops": ("COPY",),
        "legacy_stages": ("FLOW",),
        "binding_status": "candidate_endpoint_visibility_route",
        "missing_raw_template_bytes_reason": (
            "B-line endpoint visibility row does not identify sender-side COPY "
            "template row/local_order"
        ),
    },
    "operand_route_recv:B": {
        "legacy_block_kind": "route_source_materialize",
        "legacy_ops": ("LDN",),
        "legacy_stages": ("LD",),
        "binding_status": "candidate_endpoint_visibility_materialize",
        "missing_raw_template_bytes_reason": (
            "DFU3500 legacy B visibility is represented by consumer-side LDN "
            "materialization, but B-line row lacks exact local_order"
        ),
    },
    "compute_core:gemm_tile": {
        "legacy_block_kind": "gemm_tile_template_span",
        "legacy_ops": ("HMMAL",),
        "legacy_stages": ("CAL",),
        "binding_status": "candidate_gemm_tile_template_span",
        "missing_raw_template_bytes_reason": (
            "B-line atomic GEMM tile row binds to a deterministic template "
            "span, but exact expanded row hashes are not materialized yet"
        ),
    },
    "compute_core:gemm_update": {
        "legacy_block_kind": "compute_update",
        "legacy_ops": ("HMMAL",),
        "legacy_stages": ("CAL",),
        "binding_status": "candidate_compute_update_rows",
        "missing_raw_template_bytes_reason": (
            "B-line GEMM update row summarizes an HMMAL update; no exact "
            "legacy HMMAL local_order is carried"
        ),
    },
    "tile_store": {
        "legacy_block_kind": "tile_store",
        "legacy_ops": ("STD",),
        "legacy_stages": ("ST",),
        "binding_status": "candidate_store_rows",
        "missing_raw_template_bytes_reason": (
            "B-line store row lacks exact legacy STD local_order/output tag binding"
        ),
    },
    "tile_op:relu": {
        "legacy_block_kind": "relu_tile_template_span",
        "legacy_ops": ("IMM", "HMAX", "FMAX"),
        "legacy_stages": ("CAL",),
        "binding_status": "candidate_relu_tile_template_span",
        "missing_raw_template_bytes_reason": (
            "B-line ReLU tile row has a concrete HMAX/FMAX opcode decision, "
            "but lacks exact IMM zero row, operand index, local_order, and raw row bytes"
        ),
    },
}

ROLE_COMPRESSED_SPAN_AUTHORITY_POLICIES: dict[str, dict[str, object]] = {
    "accumulator_prepare": {
        "required_policy": "ACC_PREPARE_COMPRESSED_SPAN_POLICY",
        "next_decision": (
            "define accumulator_prepare compressed-row span policy for ACC_PREPARE"
        ),
        "requires_task_resource_replay_authority": False,
    },
    "operand_materialize:A": {
        "required_policy": "LDN_MATERIALIZE_COMPRESSED_SPAN_POLICY",
        "next_decision": (
            "define source materialize compressed-row span policy for operand A LDN"
        ),
        "requires_task_resource_replay_authority": False,
    },
    "operand_materialize:B": {
        "required_policy": "LDN_MATERIALIZE_COMPRESSED_SPAN_POLICY",
        "next_decision": (
            "define source materialize compressed-row span policy for operand B LDN"
        ),
        "requires_task_resource_replay_authority": False,
    },
    "operand_route_recv:A": {
        "required_policy": "SENDER_COPY_COMPRESSED_SPAN_POLICY",
        "next_decision": (
            "define sender COPY compressed-row span policy and consume "
            "TaskResourceReplay row authority for operand A route receive"
        ),
        "requires_task_resource_replay_authority": True,
    },
    "operand_route_recv:B": {
        "required_policy": "LDN_ROUTE_RECV_MATERIALIZE_COMPRESSED_SPAN_POLICY",
        "next_decision": (
            "define consumer LDN materialize compressed-row span policy for "
            "operand B route receive visibility"
        ),
        "requires_task_resource_replay_authority": False,
    },
    "compute_core:gemm_update": {
        "required_policy": "HMMAL_COMPRESSED_SPAN_POLICY",
        "next_decision": "define HMMAL compressed-row span policy for compute update",
        "requires_task_resource_replay_authority": False,
    },
    "compute_core:gemm_tile": {
        "required_policy": "GEMM_TILE_TEMPLATE_SPAN_COMPRESSED_SPAN_POLICY",
        "next_decision": "materialize atomic GEMM tile template row spans",
        "requires_task_resource_replay_authority": False,
    },
    "tile_store": {
        "required_policy": "STD_COMPRESSED_SPAN_POLICY",
        "next_decision": "define STD compressed-row span policy for tile_store",
        "requires_task_resource_replay_authority": False,
    },
    "tile_op:relu": {
        "required_policy": "RELU_TILE_TEMPLATE_SPAN_POLICY",
        "next_decision": "bind explicit relu_tile IMM-zero plus HMAX/FMAX template rows",
        "requires_task_resource_replay_authority": False,
    },
}

ALINE_CATALOG_SPAN_CANDIDATE_POLICIES: dict[str, dict[str, object]] = {
    "accumulator_prepare": {
        "policy_id": "ALINE_CATALOG_SPAN_CANDIDATE_ACC_PREPARE_V1",
        "source": "aline_catalog_span_candidate",
        "close_reason": (
            "A-line catalog has accumulator_prepare span candidates; policy is "
            "report-only and still requires exact template row hashes"
        ),
    },
    "operand_materialize:A": {
        "policy_id": "ALINE_CATALOG_SPAN_CANDIDATE_LDN_MATERIALIZE_A_V1",
        "source": "aline_catalog_span_candidate",
        "close_reason": (
            "A-line catalog has operand A LDN materialize span candidates; "
            "policy is report-only and still requires exact template row hashes"
        ),
    },
    "operand_materialize:B": {
        "policy_id": "ALINE_CATALOG_SPAN_CANDIDATE_LDN_MATERIALIZE_B_V1",
        "source": "aline_catalog_span_candidate",
        "close_reason": (
            "A-line catalog has operand B LDN materialize span candidates; "
            "policy is report-only and still requires exact template row hashes"
        ),
    },
    "compute_core:gemm_update": {
        "policy_id": "ALINE_CATALOG_SPAN_CANDIDATE_HMMAL_UPDATE_V1",
        "source": "aline_catalog_span_candidate",
        "close_reason": (
            "A-line catalog has HMMAL update span candidates; policy is "
            "report-only and still requires exact template row hashes"
        ),
    },
    "compute_core:gemm_tile": {
        "policy_id": "ALINE_CATALOG_SPAN_CANDIDATE_GEMM_TILE_TEMPLATE_SPAN_V1",
        "source": "aline_catalog_span_candidate",
        "close_reason": (
            "A-line catalog has GEMM tile template span candidates; policy is "
            "report-only and still requires exact expanded template row hashes"
        ),
    },
    "tile_store": {
        "policy_id": "ALINE_CATALOG_SPAN_CANDIDATE_STD_STORE_V1",
        "source": "aline_catalog_span_candidate",
        "close_reason": (
            "A-line catalog has STD store span candidates; policy is "
            "report-only and still requires exact template row hashes"
        ),
    },
    "tile_op:relu": {
        "policy_id": "DFU3500_RELU_TILE_SPAN_CANDIDATE_HMAX_ZERO_V1",
        "source": "dfu3500_instruction_cards+relu_binding_report",
        "close_reason": (
            "DFU3500 HMAX/FMAX capability and explicit ReLU fiber chain are closed; "
            "policy is report-only until exact IMM-zero and max rows are selected"
        ),
    },
}

ROUTE_VISIBILITY_SPAN_CANDIDATE_POLICIES: dict[str, dict[str, object]] = {
    "operand_route_recv:A": {
        "policy_id": "ROUTE_VISIBILITY_SPAN_CANDIDATE_SENDER_COPY_A_V1",
        "source": "task_resource_replay_route_authority+aline_catalog_span_candidate",
        "close_reason": (
            "TaskResourceReplay closed operand A route receive authority and "
            "A-line catalog has sender COPY span candidates; policy is "
            "report-only and still requires sender COPY exact span plus exact "
            "template row hashes"
        ),
    },
    "operand_route_recv:B": {
        "policy_id": "ROUTE_VISIBILITY_SPAN_CANDIDATE_CONSUMER_LDN_B_V1",
        "source": "aline_catalog_span_candidate",
        "close_reason": (
            "DFU3500 operand B route visibility is consumer-side LDN "
            "materialize visibility; A-line catalog has LDN span candidates, "
            "policy is report-only and still requires exact template row hashes"
        ),
    },
}


@dataclass(frozen=True)
class RawTemplateOverlayRowReport:
    """One concrete instruction row checked against the overlay contract."""

    row_id: str
    row_index: int
    pc: int
    template_op_id: str
    opcode: str
    template_row_sha256: str | None
    patched_fields: tuple[str, ...]
    zero_fill_fields: tuple[str, ...]
    template_backed_fields: tuple[str, ...]
    forbidden_fields_touched: tuple[str, ...]
    unknown_fields_touched: tuple[str, ...]
    writer_status: WriterStatus
    blockers: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "row_id": self.row_id,
            "row_index": self.row_index,
            "pc": self.pc,
            "template_op_id": self.template_op_id,
            "opcode": self.opcode,
            "template_row_sha256": self.template_row_sha256,
            "patched_fields": list(self.patched_fields),
            "zero_fill_fields": list(self.zero_fill_fields),
            "template_backed_fields": list(self.template_backed_fields),
            "forbidden_fields_touched": list(self.forbidden_fields_touched),
            "unknown_fields_touched": list(self.unknown_fields_touched),
            "writer_status": self.writer_status,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class RawTemplateOverlayReport:
    """Fail-closed report for candidate ``inst_t`` raw-template overlays."""

    profile_id: str
    writer_status: WriterStatus
    struct_name: str
    record_size_bytes: int
    instruction_row_count: int
    zero_instruction_boundary_count: int
    symbolic_unresolved_count: int
    template_row_sha256_missing_count: int
    patched_fields: tuple[str, ...]
    zero_fill_fields: tuple[str, ...]
    template_backed_fields: tuple[str, ...]
    forbidden_fields_touched: tuple[str, ...]
    unknown_fields_touched: tuple[str, ...]
    rows: tuple[RawTemplateOverlayRowReport, ...]
    blockers: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    bytes_emitted: bool = False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_inst_t_raw_template_overlay_report",
            "profile_id": self.profile_id,
            "writer_status": self.writer_status,
            "struct_name": self.struct_name,
            "record_size_bytes": self.record_size_bytes,
            "instruction_row_count": self.instruction_row_count,
            "zero_instruction_boundary_count": self.zero_instruction_boundary_count,
            "symbolic_unresolved_count": self.symbolic_unresolved_count,
            "template_row_sha256_missing_count": self.template_row_sha256_missing_count,
            "patched_fields": list(self.patched_fields),
            "zero_fill_fields": list(self.zero_fill_fields),
            "template_backed_fields": list(self.template_backed_fields),
            "forbidden_fields_touched": list(self.forbidden_fields_touched),
            "unknown_fields_touched": list(self.unknown_fields_touched),
            "rows": [row.to_plan() for row in self.rows],
            "blockers": list(self.blockers),
            "diagnostics": list(self.diagnostics),
            "bytes_emitted": self.bytes_emitted,
            "layering_policy": (
                "inst_writer_consumes_binary_layout_plan;"
                "raw_template_overlay_requires_template_row_sha256;"
                "does_not_infer_semantics_or_fabric_state"
            ),
        }


@dataclass(frozen=True)
class CandidateRawTemplateRow:
    """One possible legacy raw-template row before exact row authority exists."""

    legacy_csv_path: str | None
    template_index: int | None
    local_order: int
    op_name: str
    stage: str
    row_sha256: str

    def to_plan(self) -> dict[str, object]:
        return {
            "legacy_csv_path": self.legacy_csv_path,
            "template_index": self.template_index,
            "local_order": self.local_order,
            "op_name": self.op_name,
            "stage": self.stage,
            "row_sha256": self.row_sha256,
        }


@dataclass(frozen=True)
class TemplateEvidenceBindingRecord:
    """Candidate evidence for one B-line row, not a raw row-byte binding."""

    row_id: str
    row_index: int
    template_op_id: str
    role: str
    opcode: str
    phase: str
    binding_status: str
    legacy_block_kind: str | None
    legacy_ops: tuple[str, ...]
    legacy_stages: tuple[str, ...]
    candidate_raw_row_count: int
    candidate_raw_row_sha256s: tuple[str, ...]
    candidate_legacy_csv_paths: tuple[str, ...]
    candidate_template_indexes: tuple[int, ...]
    template_index_selection_status: str
    candidate_evidence_sha256: str | None
    missing_raw_template_bytes_reason: str | None
    blockers: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "row_id": self.row_id,
            "row_index": self.row_index,
            "template_op_id": self.template_op_id,
            "role": self.role,
            "opcode": self.opcode,
            "phase": self.phase,
            "binding_status": self.binding_status,
            "legacy_block_kind": self.legacy_block_kind,
            "legacy_ops": list(self.legacy_ops),
            "legacy_stages": list(self.legacy_stages),
            "candidate_raw_row_count": self.candidate_raw_row_count,
            "candidate_raw_row_sha256s": list(self.candidate_raw_row_sha256s),
            "candidate_legacy_csv_paths": list(self.candidate_legacy_csv_paths),
            "candidate_template_indexes": list(self.candidate_template_indexes),
            "template_index_selection_status": self.template_index_selection_status,
            "candidate_evidence_sha256": self.candidate_evidence_sha256,
            "missing_raw_template_bytes_reason": self.missing_raw_template_bytes_reason,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class TemplateEvidenceBindingReport:
    """Role/opcode/phase evidence binding before exact raw row selection."""

    profile_id: str
    binding_status: str
    instruction_row_count: int
    matched_template_evidence_count: int
    candidate_evidence_sha256_count: int
    missing_raw_template_bytes_count: int
    unmatched_template_evidence_count: int
    records: tuple[TemplateEvidenceBindingRecord, ...]
    candidate_evidence_sha256_by_template_op_id: tuple[tuple[str, str], ...]
    blockers: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_template_evidence_binding_report",
            "profile_id": self.profile_id,
            "binding_status": self.binding_status,
            "instruction_row_count": self.instruction_row_count,
            "matched_template_evidence_count": self.matched_template_evidence_count,
            "candidate_evidence_sha256_count": self.candidate_evidence_sha256_count,
            "missing_raw_template_bytes_count": self.missing_raw_template_bytes_count,
            "unmatched_template_evidence_count": self.unmatched_template_evidence_count,
            "candidate_evidence_sha256_by_template_op_id": dict(
                self.candidate_evidence_sha256_by_template_op_id
            ),
            "records": [record.to_plan() for record in self.records],
            "blockers": list(self.blockers),
            "diagnostics": list(self.diagnostics),
            "layering_policy": (
                "template_evidence_binding_report_consumes_binary_layout_plan;"
                "matches_role_opcode_phase_to_legacy_template_evidence;"
                "candidate_evidence_sha256_is_not_template_row_sha256"
            ),
        }


@dataclass(frozen=True)
class TemplateRowSpanBinding:
    """Exact seed required before a candidate row can become template bytes."""

    source_plan_id: str
    logical_row_id: str
    template_op_id: str
    role: str
    opcode: str
    phase: str
    legacy_csv_path: str | None
    template_index: int | None
    local_order: int | None
    row_span: tuple[int, int] | None
    candidate_raw_row_count: int
    candidate_legacy_csv_paths: tuple[str, ...]
    candidate_template_indexes: tuple[int, ...]
    candidate_local_order: int | None
    candidate_template_row_sha256: str | None
    exact_seed_candidate_status: str
    candidate_evidence_sha256: str | None
    required_raw_template_bytes_status: str
    s1_representation_selection_status: str
    subtask_instance_semantics_status: str
    missing_seed_fields: tuple[str, ...]
    shortest_owner_path: tuple[str, ...]
    blockers: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "source_plan_id": self.source_plan_id,
            "logical_row_id": self.logical_row_id,
            "template_op_id": self.template_op_id,
            "role": self.role,
            "opcode": self.opcode,
            "phase": self.phase,
            "legacy_csv_path": self.legacy_csv_path,
            "template_index": self.template_index,
            "local_order": self.local_order,
            "row_span": None if self.row_span is None else list(self.row_span),
            "candidate_raw_row_count": self.candidate_raw_row_count,
            "candidate_legacy_csv_paths": list(self.candidate_legacy_csv_paths),
            "candidate_template_indexes": list(self.candidate_template_indexes),
            "candidate_local_order": self.candidate_local_order,
            "candidate_template_row_sha256": self.candidate_template_row_sha256,
            "exact_seed_candidate_status": self.exact_seed_candidate_status,
            "candidate_evidence_sha256": self.candidate_evidence_sha256,
            "required_raw_template_bytes_status": self.required_raw_template_bytes_status,
            "s1_representation_selection_status": (
                self.s1_representation_selection_status
            ),
            "subtask_instance_semantics_status": self.subtask_instance_semantics_status,
            "missing_seed_fields": list(self.missing_seed_fields),
            "shortest_owner_path": list(self.shortest_owner_path),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class ExactTemplateBindingSeedReport:
    """Fail-closed exact binding seed contract for future raw row hashes."""

    profile_id: str
    source_plan_id: str
    seed_status: str
    instruction_row_count: int
    exact_bound_row_count: int
    partial_candidate_row_count: int
    single_candidate_row_count: int
    blocked_row_count: int
    missing_seed_field_counts: tuple[tuple[str, int], ...]
    bindings: tuple[TemplateRowSpanBinding, ...]
    blockers: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    task_resource_replay_authority_status_counts: tuple[tuple[str, int], ...] = ()

    def to_plan(self) -> dict[str, object]:
        plan: dict[str, object] = {
            "schema_version": 1,
            "artifact": "b_line_exact_template_binding_seed_report",
            "profile_id": self.profile_id,
            "source_plan_id": self.source_plan_id,
            "seed_status": self.seed_status,
            "instruction_row_count": self.instruction_row_count,
            "exact_bound_row_count": self.exact_bound_row_count,
            "partial_candidate_row_count": self.partial_candidate_row_count,
            "single_candidate_row_count": self.single_candidate_row_count,
            "blocked_row_count": self.blocked_row_count,
            "missing_seed_field_counts": dict(self.missing_seed_field_counts),
            "bindings": [binding.to_plan() for binding in self.bindings],
            "blockers": list(self.blockers),
            "diagnostics": list(self.diagnostics),
            "layering_policy": (
                "exact_template_binding_seed_report_consumes_candidate_evidence;"
                "declares_required_fields_for_template_row_sha256;"
                "does_not_select_or_patch_raw_bytes"
            ),
        }
        if self.task_resource_replay_authority_status_counts:
            plan["task_resource_replay_authority_status_counts"] = dict(
                self.task_resource_replay_authority_status_counts
            )
        return plan


@dataclass(frozen=True)
class AlineTemplateSpanCandidateRecord:
    """A-line catalog candidates for one B-line instruction row.

    This is deliberately span-level evidence.  It does not select a local row
    and must not be promoted to ``template_row_sha256``.
    """

    logical_row_id: str
    template_op_id: str
    role: str
    opcode: str
    candidate_catalog_row_count: int
    candidate_catalog_sha256_count: int
    candidate_catalog_span_sha256: str | None
    candidate_csv_paths: tuple[str, ...]
    candidate_template_indexes: tuple[int, ...]
    span_binding_status: SpanCandidateStatus

    def to_plan(self) -> dict[str, object]:
        return {
            "logical_row_id": self.logical_row_id,
            "template_op_id": self.template_op_id,
            "role": self.role,
            "opcode": self.opcode,
            "candidate_catalog_row_count": self.candidate_catalog_row_count,
            "candidate_catalog_sha256_count": self.candidate_catalog_sha256_count,
            "candidate_catalog_span_sha256": self.candidate_catalog_span_sha256,
            "candidate_csv_paths": list(self.candidate_csv_paths),
            "candidate_template_indexes": list(self.candidate_template_indexes),
            "span_binding_status": self.span_binding_status,
        }


@dataclass(frozen=True)
class AlineTemplateSpanCandidateReport:
    """Report-only A-line row-catalog span candidates for S2."""

    profile_id: str
    binding_status: str
    instruction_row_count: int
    catalog_available_row_count: int
    catalog_missing_row_count: int
    catalog_unavailable_row_count: int
    exact_single_row_count: int
    row_span_required_count: int
    records: tuple[AlineTemplateSpanCandidateRecord, ...]
    blockers: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    bytes_emitted: bool = False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_aline_template_span_candidate_report",
            "profile_id": self.profile_id,
            "binding_status": self.binding_status,
            "instruction_row_count": self.instruction_row_count,
            "catalog_available_row_count": self.catalog_available_row_count,
            "catalog_missing_row_count": self.catalog_missing_row_count,
            "catalog_unavailable_row_count": self.catalog_unavailable_row_count,
            "exact_single_row_count": self.exact_single_row_count,
            "row_span_required_count": self.row_span_required_count,
            "records": [record.to_plan() for record in self.records],
            "blockers": list(self.blockers),
            "diagnostics": list(self.diagnostics),
            "bytes_emitted": self.bytes_emitted,
            "layering_policy": (
                "aline_template_span_candidate_report_consumes_selected_aline_row_catalog;"
                "matches_candidate_csv_template_op_stage_only;"
                "does_not_select_local_order_or_emit_template_row_sha256"
            ),
        }


@dataclass(frozen=True)
class CompressedTemplateSpanAuthorityRecord:
    """Compressed-row span authority status for one B-line instruction row."""

    logical_row_id: str
    template_op_id: str
    role: str
    opcode: str
    candidate_catalog_row_count: int
    candidate_catalog_sha256_count: int
    candidate_catalog_span_sha256: str | None
    span_candidate_status: SpanCandidateStatus
    task_resource_replay_authority_status: str
    span_authority_status: SpanAuthorityStatus
    required_policy: str
    next_decision: str
    policy_id: str | None
    policy_source: str | None
    does_not_emit_bytes: bool
    requires_template_row_hash: bool
    requires_sender_copy_exact_span: bool
    policy_candidate_close_reason: str | None
    policy_candidate_blockers: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "logical_row_id": self.logical_row_id,
            "template_op_id": self.template_op_id,
            "role": self.role,
            "opcode": self.opcode,
            "candidate_catalog_row_count": self.candidate_catalog_row_count,
            "candidate_catalog_sha256_count": self.candidate_catalog_sha256_count,
            "candidate_catalog_span_sha256": self.candidate_catalog_span_sha256,
            "span_candidate_status": self.span_candidate_status,
            "task_resource_replay_authority_status": (
                self.task_resource_replay_authority_status
            ),
            "span_authority_status": self.span_authority_status,
            "required_policy": self.required_policy,
            "next_decision": self.next_decision,
            "policy_id": self.policy_id,
            "policy_source": self.policy_source,
            "does_not_emit_bytes": self.does_not_emit_bytes,
            "requires_template_row_hash": self.requires_template_row_hash,
            "requires_sender_copy_exact_span": (
                self.requires_sender_copy_exact_span
            ),
            "policy_candidate_close_reason": self.policy_candidate_close_reason,
            "policy_candidate_blockers": list(self.policy_candidate_blockers),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class CompressedTemplateSpanRoleDecision:
    """Role-level next decision before compressed spans can become exact."""

    role: str
    opcode: str
    row_count: int
    status_counts: tuple[tuple[str, int], ...]
    required_policy: str
    next_decision: str
    requires_task_resource_replay_authority: bool
    task_resource_partial_count: int
    policy_candidate_status: str
    policy_id: str | None
    policy_source: str | None
    does_not_emit_bytes: bool
    requires_template_row_hash: bool
    requires_sender_copy_exact_span: bool
    policy_candidate_blockers: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "role": self.role,
            "opcode": self.opcode,
            "row_count": self.row_count,
            "status_counts": dict(self.status_counts),
            "required_policy": self.required_policy,
            "next_decision": self.next_decision,
            "requires_task_resource_replay_authority": (
                self.requires_task_resource_replay_authority
            ),
            "task_resource_partial_count": self.task_resource_partial_count,
            "policy_candidate_status": self.policy_candidate_status,
            "policy_id": self.policy_id,
            "policy_source": self.policy_source,
            "does_not_emit_bytes": self.does_not_emit_bytes,
            "requires_template_row_hash": self.requires_template_row_hash,
            "requires_sender_copy_exact_span": (
                self.requires_sender_copy_exact_span
            ),
            "policy_candidate_blockers": list(self.policy_candidate_blockers),
        }


@dataclass(frozen=True)
class CompressedTemplateSpanAuthorityReport:
    """Report-only compressed-row/span authority contract for S2."""

    profile_id: str
    authority_status: str
    instruction_row_count: int
    exact_span_count: int
    span_policy_needed_count: int
    closed_policy_row_count: int
    blocked_policy_row_count: int
    route_policy_closed_count: int
    route_policy_blocked_count: int
    task_resource_partial_count: int
    role_decisions: tuple[CompressedTemplateSpanRoleDecision, ...]
    records: tuple[CompressedTemplateSpanAuthorityRecord, ...]
    blockers: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    bytes_emitted: bool = False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_compressed_template_span_authority_report",
            "profile_id": self.profile_id,
            "authority_status": self.authority_status,
            "instruction_row_count": self.instruction_row_count,
            "exact_span_count": self.exact_span_count,
            "span_policy_needed_count": self.span_policy_needed_count,
            "closed_policy_row_count": self.closed_policy_row_count,
            "blocked_policy_row_count": self.blocked_policy_row_count,
            "route_policy_closed_count": self.route_policy_closed_count,
            "route_policy_blocked_count": self.route_policy_blocked_count,
            "task_resource_partial_count": self.task_resource_partial_count,
            "role_decisions": [
                role_decision.to_plan() for role_decision in self.role_decisions
            ],
            "records": [record.to_plan() for record in self.records],
            "blockers": list(self.blockers),
            "diagnostics": list(self.diagnostics),
            "bytes_emitted": self.bytes_emitted,
            "layering_policy": (
                "compressed_template_span_authority_report_consumes_aline_span_candidates;"
                "names_role_span_policy_decisions;"
                "does_not_select_local_order_template_row_sha256_or_emit_bytes"
            ),
        }


@dataclass(frozen=True)
class ExactTemplateSpanHashCandidateRecord:
    """Hash candidate for a policy-closed compressed span.

    This is not a raw ``inst_t`` row hash.  It records the digest of the
    selected A-line catalog candidate span so reviewers can audit the next
    byte-writer input without promoting the row to overlay-ready status.
    """

    logical_row_id: str
    template_op_id: str
    source_schedule_step_id: str
    primary_fiber_op_id: str
    role: str
    opcode: str
    phase: str
    subtask_slot: str
    span_provenance_status: str
    status: ExactSpanHashStatus
    span_hash_sha256: str | None
    candidate_catalog_row_count: int
    candidate_catalog_sha256_count: int
    candidate_catalog_span_sha256: str | None
    policy_id: str | None
    raw_overlay_consumable: bool
    blockers: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "logical_row_id": self.logical_row_id,
            "template_op_id": self.template_op_id,
            "source_schedule_step_id": self.source_schedule_step_id,
            "primary_fiber_op_id": self.primary_fiber_op_id,
            "role": self.role,
            "opcode": self.opcode,
            "phase": self.phase,
            "subtask_slot": self.subtask_slot,
            "span_provenance_status": self.span_provenance_status,
            "status": self.status,
            "span_hash_sha256": self.span_hash_sha256,
            "candidate_catalog_row_count": self.candidate_catalog_row_count,
            "candidate_catalog_sha256_count": self.candidate_catalog_sha256_count,
            "candidate_catalog_span_sha256": self.candidate_catalog_span_sha256,
            "policy_id": self.policy_id,
            "raw_overlay_consumable": self.raw_overlay_consumable,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class ExactTemplateSpanHashCandidateReport:
    """Report-only exact span hash candidates after span policy closure."""

    profile_id: str
    candidate_status: str
    instruction_row_count: int
    span_hash_candidate_count: int
    blocked_row_count: int
    raw_overlay_consumable_count: int
    records: tuple[ExactTemplateSpanHashCandidateRecord, ...]
    blockers: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    bytes_emitted: bool = False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_exact_template_span_hash_candidate_report",
            "profile_id": self.profile_id,
            "candidate_status": self.candidate_status,
            "instruction_row_count": self.instruction_row_count,
            "span_hash_candidate_count": self.span_hash_candidate_count,
            "blocked_row_count": self.blocked_row_count,
            "raw_overlay_consumable_count": self.raw_overlay_consumable_count,
            "records": [record.to_plan() for record in self.records],
            "blockers": list(self.blockers),
            "diagnostics": list(self.diagnostics),
            "bytes_emitted": self.bytes_emitted,
            "layering_policy": (
                "exact_template_span_hash_candidate_report_consumes_closed_span_policy;"
                "hashes_audit_candidate_spans_only;"
                "does_not_provide_raw_inst_t_template_row_sha256"
            ),
        }


@dataclass(frozen=True)
class ExactSpanRowSelectorPolicyRecord:
    """Exact CSV/span selector before raw ``inst_t`` bytes exist."""

    logical_row_id: str
    template_op_id: str
    source_schedule_step_id: str
    primary_fiber_op_id: str
    role: str
    opcode: str
    phase: str
    subtask_slot: str
    selector_status: ExactSpanRowSelectorStatus
    selector_policy_id: str | None
    legacy_csv_path: str | None
    template_index: int | None
    selected_row_span: tuple[int, int] | None
    selected_local_orders: tuple[int, ...]
    selected_row_count: int
    selected_row_hash_sequence_sha256: str | None
    store_output_binding: str | None
    selector_does_not_emit_bytes: bool
    missing_selector_fields: tuple[str, ...]
    blockers: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "logical_row_id": self.logical_row_id,
            "template_op_id": self.template_op_id,
            "source_schedule_step_id": self.source_schedule_step_id,
            "primary_fiber_op_id": self.primary_fiber_op_id,
            "role": self.role,
            "opcode": self.opcode,
            "phase": self.phase,
            "subtask_slot": self.subtask_slot,
            "selector_status": self.selector_status,
            "selector_policy_id": self.selector_policy_id,
            "legacy_csv_path": self.legacy_csv_path,
            "template_index": self.template_index,
            "selected_row_span": (
                None if self.selected_row_span is None else list(self.selected_row_span)
            ),
            "selected_local_orders": list(self.selected_local_orders),
            "selected_row_count": self.selected_row_count,
            "selected_row_hash_sequence_sha256": (
                self.selected_row_hash_sequence_sha256
            ),
            "store_output_binding": self.store_output_binding,
            "selector_does_not_emit_bytes": self.selector_does_not_emit_bytes,
            "missing_selector_fields": list(self.missing_selector_fields),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class ExactSpanRowSelectorPolicyReport:
    """Machine-checkable span selector policy before byte materialization."""

    profile_id: str
    selector_status: str
    instruction_row_count: int
    selector_candidate_count: int
    blocked_row_count: int
    selected_row_total_count: int
    records: tuple[ExactSpanRowSelectorPolicyRecord, ...]
    blockers: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    bytes_emitted: bool = False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_exact_span_row_selector_policy_report",
            "profile_id": self.profile_id,
            "selector_status": self.selector_status,
            "instruction_row_count": self.instruction_row_count,
            "selector_candidate_count": self.selector_candidate_count,
            "blocked_row_count": self.blocked_row_count,
            "selected_row_total_count": self.selected_row_total_count,
            "records": [record.to_plan() for record in self.records],
            "blockers": list(self.blockers),
            "diagnostics": list(self.diagnostics),
            "bytes_emitted": self.bytes_emitted,
            "layering_policy": (
                "exact_span_row_selector_policy_report_consumes_binary_layout_and_legacy_evidence;"
                "selects_csv_template_and_local_orders_only;"
                "does_not_emit_inst_t_bytes_or_template_row_sha256"
            ),
        }


@dataclass(frozen=True)
class RawTemplateRowHashReadinessRecord:
    """Readiness of one B-line row for raw ``inst_t`` overlay hashing."""

    logical_row_id: str
    template_op_id: str
    source_schedule_step_id: str
    primary_fiber_op_id: str
    role: str
    opcode: str
    phase: str
    subtask_slot: str
    readiness_status: RawTemplateRowHashReadinessStatus
    span_hash_sha256: str | None
    template_row_sha256: str | None
    candidate_catalog_row_count: int
    candidate_catalog_span_sha256: str | None
    raw_overlay_consumable: bool
    blockers: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "logical_row_id": self.logical_row_id,
            "template_op_id": self.template_op_id,
            "source_schedule_step_id": self.source_schedule_step_id,
            "primary_fiber_op_id": self.primary_fiber_op_id,
            "role": self.role,
            "opcode": self.opcode,
            "phase": self.phase,
            "subtask_slot": self.subtask_slot,
            "readiness_status": self.readiness_status,
            "span_hash_sha256": self.span_hash_sha256,
            "template_row_sha256": self.template_row_sha256,
            "candidate_catalog_row_count": self.candidate_catalog_row_count,
            "candidate_catalog_span_sha256": self.candidate_catalog_span_sha256,
            "raw_overlay_consumable": self.raw_overlay_consumable,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class RawTemplateRowHashReadinessReport:
    """Fail-closed boundary between span hashes and raw row hashes."""

    profile_id: str
    readiness_status: str
    instruction_row_count: int
    raw_template_row_hash_ready_count: int
    blocked_row_count: int
    span_hash_candidate_count: int
    records: tuple[RawTemplateRowHashReadinessRecord, ...]
    blockers: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    bytes_emitted: bool = False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_raw_template_row_hash_readiness_report",
            "profile_id": self.profile_id,
            "readiness_status": self.readiness_status,
            "instruction_row_count": self.instruction_row_count,
            "raw_template_row_hash_ready_count": (
                self.raw_template_row_hash_ready_count
            ),
            "blocked_row_count": self.blocked_row_count,
            "span_hash_candidate_count": self.span_hash_candidate_count,
            "records": [record.to_plan() for record in self.records],
            "blockers": list(self.blockers),
            "diagnostics": list(self.diagnostics),
            "bytes_emitted": self.bytes_emitted,
            "layering_policy": (
                "raw_template_row_hash_readiness_report_consumes_span_hash_candidates;"
                "rejects_span_hashes_as_raw_inst_t_template_row_sha256;"
                "does_not_emit_inst_t_bytes"
            ),
        }


@dataclass(frozen=True)
class TemplateSpanMaterializationCandidateRecord:
    """Report-only materialized span shape for a B-line instruction row."""

    logical_row_id: str
    template_op_id: str
    source_schedule_step_id: str
    primary_fiber_op_id: str
    role: str
    opcode: str
    phase: str
    subtask_slot: str
    status: SpanMaterializationStatus
    template_binding_status: str
    materialization_kind: str
    provenance_policy: str
    materialized_span_row_count: int
    materialized_span_byte_count: int
    span_row_hash_sequence_sha256: str | None
    selector_policy_status: str | None
    selector_policy_id: str | None
    selected_legacy_csv_path: str | None
    selected_template_index: int | None
    selected_row_span: tuple[int, int] | None
    selected_local_orders: tuple[int, ...]
    selected_row_hash_sequence_sha256: str | None
    store_output_binding: str | None
    raw_inst_t_row_count: int
    raw_inst_t_byte_count: int
    raw_inst_t_row_bytes_sha256: str | None
    raw_template_row_sha256: str | None
    raw_overlay_consumable: bool
    raw_overlay_blocker_code: str | None
    byte_materializer_status: ByteMaterializerStatus
    required_byte_materializer_inputs: tuple[str, ...]
    missing_byte_materializer_inputs: tuple[str, ...]
    blockers: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "logical_row_id": self.logical_row_id,
            "template_op_id": self.template_op_id,
            "source_schedule_step_id": self.source_schedule_step_id,
            "primary_fiber_op_id": self.primary_fiber_op_id,
            "role": self.role,
            "opcode": self.opcode,
            "phase": self.phase,
            "subtask_slot": self.subtask_slot,
            "status": self.status,
            "template_binding_status": self.template_binding_status,
            "materialization_kind": self.materialization_kind,
            "provenance_policy": self.provenance_policy,
            "materialized_span_row_count": self.materialized_span_row_count,
            "materialized_span_byte_count": self.materialized_span_byte_count,
            "span_row_hash_sequence_sha256": self.span_row_hash_sequence_sha256,
            "selector_policy_status": self.selector_policy_status,
            "selector_policy_id": self.selector_policy_id,
            "selected_legacy_csv_path": self.selected_legacy_csv_path,
            "selected_template_index": self.selected_template_index,
            "selected_row_span": (
                None if self.selected_row_span is None else list(self.selected_row_span)
            ),
            "selected_local_orders": list(self.selected_local_orders),
            "selected_row_hash_sequence_sha256": (
                self.selected_row_hash_sequence_sha256
            ),
            "store_output_binding": self.store_output_binding,
            "raw_inst_t_row_count": self.raw_inst_t_row_count,
            "raw_inst_t_byte_count": self.raw_inst_t_byte_count,
            "raw_inst_t_row_bytes_sha256": self.raw_inst_t_row_bytes_sha256,
            "raw_template_row_sha256": self.raw_template_row_sha256,
            "raw_overlay_consumable": self.raw_overlay_consumable,
            "raw_overlay_blocker_code": self.raw_overlay_blocker_code,
            "byte_materializer_status": self.byte_materializer_status,
            "required_byte_materializer_inputs": list(
                self.required_byte_materializer_inputs
            ),
            "missing_byte_materializer_inputs": list(
                self.missing_byte_materializer_inputs
            ),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class TemplateSpanMaterializationCandidateReport:
    """Report-only span materialization candidates before byte overlay."""

    profile_id: str
    materialization_status: str
    instruction_row_count: int
    materialized_span_candidate_count: int
    blocked_row_count: int
    materialized_span_total_byte_count: int
    raw_overlay_consumable_count: int
    records: tuple[TemplateSpanMaterializationCandidateRecord, ...]
    blockers: tuple[str, ...] = ()
    diagnostics: tuple[str, ...] = ()
    bytes_emitted: bool = False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_template_span_materialization_candidate_report",
            "profile_id": self.profile_id,
            "materialization_status": self.materialization_status,
            "instruction_row_count": self.instruction_row_count,
            "materialized_span_candidate_count": (
                self.materialized_span_candidate_count
            ),
            "blocked_row_count": self.blocked_row_count,
            "materialized_span_total_byte_count": (
                self.materialized_span_total_byte_count
            ),
            "raw_overlay_consumable_count": self.raw_overlay_consumable_count,
            "records": [record.to_plan() for record in self.records],
            "blockers": list(self.blockers),
            "diagnostics": list(self.diagnostics),
            "bytes_emitted": self.bytes_emitted,
            "layering_policy": (
                "template_span_materialization_candidate_report_consumes_span_hash_candidates;"
                "reports_multi_row_inst_t_span_shape;"
                "does_not_emit_bytes_or_single_row_template_sha"
            ),
        }


@dataclass(frozen=True)
class RawInstTSpanMaterialization:
    """Packed raw ``inst_t`` bytes for one atomic FiberOp template span."""

    row_count: int
    byte_count: int
    sha256: str


def build_raw_template_overlay_report(
    layout: BinaryLayoutPlan,
    *,
    template_row_sha256_by_template_op_id: Mapping[str, str] | None = None,
    patched_fields_by_template_op_id: Mapping[str, tuple[str, ...]] | None = None,
    zero_fill_fields_by_template_op_id: Mapping[str, tuple[str, ...]] | None = None,
) -> RawTemplateOverlayReport:
    """Check whether concrete layout rows are ready for raw-template overlay.

    The optional patch/zero-fill maps model future caller intent.  Because no
    ``inst_t`` field offsets are currently trusted, any non-empty value in
    either map is treated as an unknown touch unless that field has been added
    to one of the explicit allowlists above.
    """

    template_hashes = template_row_sha256_by_template_op_id or {}
    patch_map = patched_fields_by_template_op_id or {}
    zero_fill_map = zero_fill_fields_by_template_op_id or {}

    row_reports = tuple(
        _row_report(
            row,
            template_row_sha256=template_hashes.get(row.template_op_id)
            or _row_attr_str(row, "template_row_sha256"),
            patched_fields=patch_map.get(row.template_op_id, ()),
            zero_fill_fields=zero_fill_map.get(row.template_op_id, ()),
        )
        for row in layout.instruction_rows
    )
    symbolic_unresolved_count = sum(
        item.unresolved_template_op_count for item in layout.task_rows
    )
    forbidden_fields_touched = _sorted_unique(
        field
        for row in row_reports
        for field in row.forbidden_fields_touched
    )
    unknown_fields_touched = _sorted_unique(
        field for row in row_reports for field in row.unknown_fields_touched
    )
    patched_fields = _sorted_unique(
        field for row in row_reports for field in row.patched_fields
    )
    zero_fill_fields = _sorted_unique(
        field for row in row_reports for field in row.zero_fill_fields
    )
    template_backed_fields = _sorted_unique(
        field for row in row_reports for field in row.template_backed_fields
    )
    template_row_sha256_missing_count = sum(
        1 for row in row_reports if row.template_row_sha256 is None
    )

    blockers: list[str] = []
    diagnostics = [
        f"{diagnostic.severity}:{diagnostic.code}:{diagnostic.subject_id}"
        for diagnostic in layout.diagnostics
    ]
    if symbolic_unresolved_count > 0:
        blockers.append(
            "symbolic_unresolved_count>0 fail: "
            f"{symbolic_unresolved_count} unresolved TemplateOps remain"
        )
    if forbidden_fields_touched:
        blockers.append(
            "forbidden_fields_touched fail: "
            + ", ".join(forbidden_fields_touched)
        )
    if unknown_fields_touched:
        blockers.append(
            "unknown_fields_touched fail: "
            + ", ".join(unknown_fields_touched)
        )
    if template_row_sha256_missing_count > 0:
        blockers.append(
            "template_row_sha256 missing blocked: "
            f"{template_row_sha256_missing_count} concrete instruction rows lack raw template hashes"
        )
    if layout.validation_status != "valid":
        blockers.append(
            "layout validation_status fail: "
            f"expected valid, got {layout.validation_status}"
        )

    return RawTemplateOverlayReport(
        profile_id=layout.profile_id,
        writer_status=_overall_status(
            symbolic_unresolved_count=symbolic_unresolved_count,
            forbidden_fields_touched=forbidden_fields_touched,
            unknown_fields_touched=unknown_fields_touched,
            template_row_sha256_missing_count=template_row_sha256_missing_count,
            layout_valid=layout.validation_status == "valid",
        ),
        struct_name=INST_T_STRUCT_NAME,
        record_size_bytes=INST_T_RECORD_SIZE_BYTES,
        instruction_row_count=len(layout.instruction_rows),
        zero_instruction_boundary_count=len(layout.zero_instruction_boundaries),
        symbolic_unresolved_count=symbolic_unresolved_count,
        template_row_sha256_missing_count=template_row_sha256_missing_count,
        patched_fields=patched_fields,
        zero_fill_fields=zero_fill_fields,
        template_backed_fields=template_backed_fields,
        forbidden_fields_touched=forbidden_fields_touched,
        unknown_fields_touched=unknown_fields_touched,
        rows=row_reports,
        blockers=tuple(blockers),
        diagnostics=tuple(diagnostics),
        bytes_emitted=False,
    )


def build_aline_template_span_candidate_report(
    layout: BinaryLayoutPlan,
    aline_report: object,
    evidence_report: TemplateEvidenceBindingReport | None = None,
) -> AlineTemplateSpanCandidateReport:
    """Check B-line candidate spans against the selected A-line row catalog.

    The report proves catalog availability for candidate CSV/template/op/stage
    spans only.  It intentionally does not bind exact local orders or raw row
    bytes, so every current row remains a row-span candidate.
    """

    evidence = evidence_report or build_template_evidence_binding_report(layout)
    evidence_by_template_op_id = {
        record.template_op_id: record for record in evidence.records
    }
    catalog = getattr(aline_report, "row_catalog", None)
    catalog_available = bool(getattr(catalog, "row_catalog_available", False))
    catalog_rows = tuple(getattr(catalog, "rows", ()) or ())

    records = tuple(
        _aline_span_candidate_record(
            row,
            evidence=evidence_by_template_op_id.get(row.template_op_id),
            catalog_rows=catalog_rows,
            catalog_available=catalog_available,
        )
        for row in layout.instruction_rows
    )
    catalog_available_row_count = sum(
        1
        for record in records
        if record.span_binding_status == "catalog_candidate_available"
    )
    catalog_missing_row_count = sum(
        1 for record in records if record.span_binding_status == "catalog_missing"
    )
    catalog_unavailable_row_count = sum(
        1
        for record in records
        if record.span_binding_status == "catalog_unavailable"
    )
    exact_single_row_count = 0
    row_span_required_count = len(records) - exact_single_row_count

    blockers: list[str] = []
    if catalog_unavailable_row_count:
        blockers.append(
            "selected A-line row catalog unavailable: "
            f"{catalog_unavailable_row_count} instruction rows cannot be checked"
        )
    if catalog_missing_row_count:
        blockers.append(
            "A-line row catalog candidates missing: "
            f"{catalog_missing_row_count} instruction rows lack catalog spans"
        )
    diagnostics = [
        f"{diagnostic.severity}:{diagnostic.code}:{diagnostic.subject_id}"
        for diagnostic in layout.diagnostics
    ]
    diagnostics += evidence.diagnostics
    return AlineTemplateSpanCandidateReport(
        profile_id=layout.profile_id,
        binding_status=(
            "span_candidate_report_only" if not blockers else "blocked"
        ),
        instruction_row_count=len(layout.instruction_rows),
        catalog_available_row_count=catalog_available_row_count,
        catalog_missing_row_count=catalog_missing_row_count,
        catalog_unavailable_row_count=catalog_unavailable_row_count,
        exact_single_row_count=exact_single_row_count,
        row_span_required_count=row_span_required_count,
        records=records,
        blockers=tuple(blockers),
        diagnostics=tuple(diagnostics),
        bytes_emitted=False,
    )


def build_compressed_template_span_authority_report(
    layout: BinaryLayoutPlan,
    aline_span_candidate_report: AlineTemplateSpanCandidateReport,
    task_resource_replay_authority_report: object | None = None,
    *,
    enabled_role_span_policies: Collection[str] | None = None,
) -> CompressedTemplateSpanAuthorityReport:
    """Declare compressed-row span authority still needed before exact rows.

    This is intentionally report-only.  It may acknowledge partial
    TaskResourceReplay authority for sender COPY route rows, but it must not
    promote any instruction row to exact or ready raw-template bytes.
    """

    candidate_by_template_op_id = {
        record.template_op_id: record
        for record in aline_span_candidate_report.records
    }
    task_resource_authority_by_key = (
        _task_resource_replay_authority_status_by_role_opcode(
            task_resource_replay_authority_report
        )
    )
    enabled_policy_roles = _enabled_role_span_policy_set(
        enabled_role_span_policies
    )
    records = tuple(
        _compressed_span_authority_record(
            row,
            candidate=candidate_by_template_op_id.get(row.template_op_id),
            task_resource_replay_authority_status=(
                _task_resource_replay_authority_status_for_row(
                    row,
                    task_resource_authority_by_key,
                    enabled=task_resource_replay_authority_report is not None,
                )
            ),
            enabled_role_span_policies=enabled_policy_roles,
        )
        for row in layout.instruction_rows
    )
    exact_span_count = sum(
        1
        for record in records
        if record.span_authority_status in {"exact", "ready"}
    )
    task_resource_partial_count = sum(
        1
        for record in records
        if record.span_authority_status
        == "partial_route_authority_span_policy_needed"
    )
    closed_statuses = {
        "span_policy_candidate_closed",
        "route_span_policy_candidate_closed",
    }
    closed_policy_row_count = sum(
        1
        for record in records
        if record.span_authority_status in closed_statuses
    )
    blocked_policy_row_count = len(records) - closed_policy_row_count
    route_policy_closed_count = sum(
        1
        for record in records
        if record.role.startswith("operand_route_recv:")
        and record.span_authority_status in closed_statuses
    )
    route_policy_blocked_count = sum(
        1
        for record in records
        if record.role.startswith("operand_route_recv:")
        and record.span_authority_status not in closed_statuses
    )
    span_policy_needed_count = sum(
        1
        for record in records
        if record.span_authority_status
        in {
            "blocked_needs_span_policy",
            "partial_route_authority_span_policy_needed",
        }
    )
    role_decisions = _compressed_span_role_decisions(records)
    blockers = (
        "compressed template span authority blocked: "
        f"{blocked_policy_row_count} rows require explicit role span policies; "
        f"{closed_policy_row_count} rows are report-only policy candidates",
    )
    diagnostics = [
        f"{diagnostic.severity}:{diagnostic.code}:{diagnostic.subject_id}"
        for diagnostic in layout.diagnostics
    ]
    diagnostics += aline_span_candidate_report.diagnostics
    return CompressedTemplateSpanAuthorityReport(
        profile_id=layout.profile_id,
        authority_status="blocked",
        instruction_row_count=len(layout.instruction_rows),
        exact_span_count=exact_span_count,
        span_policy_needed_count=span_policy_needed_count,
        closed_policy_row_count=closed_policy_row_count,
        blocked_policy_row_count=blocked_policy_row_count,
        route_policy_closed_count=route_policy_closed_count,
        route_policy_blocked_count=route_policy_blocked_count,
        task_resource_partial_count=task_resource_partial_count,
        role_decisions=role_decisions,
        records=records,
        blockers=blockers,
        diagnostics=tuple(diagnostics),
        bytes_emitted=False,
    )


def build_exact_template_span_hash_candidate_report(
    layout: BinaryLayoutPlan,
    compressed_span_authority_report: CompressedTemplateSpanAuthorityReport,
) -> ExactTemplateSpanHashCandidateReport:
    """Hash closed span candidates without making them raw overlay inputs."""

    authority_by_template_op_id = {
        record.template_op_id: record
        for record in compressed_span_authority_report.records
    }
    records = tuple(
        _exact_span_hash_candidate_record(
            row,
            authority=authority_by_template_op_id.get(row.template_op_id),
        )
        for row in layout.instruction_rows
    )
    span_hash_candidate_count = sum(
        1
        for record in records
        if record.status == "span_hash_candidate_available"
    )
    blocked_row_count = len(records) - span_hash_candidate_count
    raw_overlay_consumable_count = sum(
        1 for record in records if record.raw_overlay_consumable
    )
    blockers: list[str] = []
    if blocked_row_count:
        blockers.append(
            "exact template span hash candidates blocked: "
            f"{blocked_row_count} rows lack closed span policy"
        )
    blockers.append(
        "span hash candidates are not raw inst_t template_row_sha256 values"
    )
    diagnostics = tuple(compressed_span_authority_report.diagnostics)
    return ExactTemplateSpanHashCandidateReport(
        profile_id=layout.profile_id,
        candidate_status=(
            "candidate_report_only" if span_hash_candidate_count else "blocked"
        ),
        instruction_row_count=len(layout.instruction_rows),
        span_hash_candidate_count=span_hash_candidate_count,
        blocked_row_count=blocked_row_count,
        raw_overlay_consumable_count=raw_overlay_consumable_count,
        records=records,
        blockers=tuple(blockers),
        diagnostics=diagnostics,
        bytes_emitted=False,
    )


def build_exact_span_row_selector_policy_report(
    layout: BinaryLayoutPlan,
    evidence_report: TemplateEvidenceBindingReport | None = None,
) -> ExactSpanRowSelectorPolicyReport:
    """Select exact legacy CSV/template/local-order spans without emitting bytes."""

    evidence = evidence_report or build_template_evidence_binding_report(layout)
    evidence_by_template_op_id = {
        record.template_op_id: record for record in evidence.records
    }
    records = tuple(
        _exact_span_row_selector_policy_record(
            row,
            evidence=evidence_by_template_op_id.get(row.template_op_id),
        )
        for row in layout.instruction_rows
    )
    selector_candidate_count = sum(
        1
        for record in records
        if record.selector_status == "selector_policy_candidate_available"
    )
    blocked_row_count = len(records) - selector_candidate_count
    selected_row_total_count = sum(record.selected_row_count for record in records)
    blockers: list[str] = []
    if blocked_row_count:
        blockers.append(
            "exact span row selector blocked: "
            f"{blocked_row_count} rows lack selector candidates"
        )
    blockers.append(
        "selected spans are not raw inst_t bytes and cannot provide template_row_sha256"
    )
    diagnostics = [
        f"{diagnostic.severity}:{diagnostic.code}:{diagnostic.subject_id}"
        for diagnostic in layout.diagnostics
    ]
    diagnostics += evidence.diagnostics
    return ExactSpanRowSelectorPolicyReport(
        profile_id=layout.profile_id,
        selector_status=(
            "selector_candidate_report_only"
            if selector_candidate_count
            else "blocked"
        ),
        instruction_row_count=len(layout.instruction_rows),
        selector_candidate_count=selector_candidate_count,
        blocked_row_count=blocked_row_count,
        selected_row_total_count=selected_row_total_count,
        records=records,
        blockers=tuple(blockers),
        diagnostics=tuple(diagnostics),
        bytes_emitted=False,
    )


def build_raw_template_row_hash_readiness_report(
    layout: BinaryLayoutPlan,
    span_hash_candidate_report: ExactTemplateSpanHashCandidateReport,
) -> RawTemplateRowHashReadinessReport:
    """Reject span hashes as raw template row hashes until materialized."""

    span_by_template_op_id = {
        record.template_op_id: record
        for record in span_hash_candidate_report.records
    }
    records = tuple(
        _raw_template_row_hash_readiness_record(
            row,
            span_candidate=span_by_template_op_id.get(row.template_op_id),
        )
        for row in layout.instruction_rows
    )
    raw_ready_count = sum(
        1
        for record in records
        if record.readiness_status == "ready_raw_template_row_hash"
    )
    span_hash_candidate_count = sum(
        1 for record in records if record.span_hash_sha256 is not None
    )
    blocked_row_count = len(records) - raw_ready_count
    blockers: list[str] = []
    if blocked_row_count:
        blockers.append(
            "raw template row hash readiness blocked: "
            f"{blocked_row_count} rows only have compressed span hash candidates"
        )
    diagnostics = tuple(span_hash_candidate_report.diagnostics)
    return RawTemplateRowHashReadinessReport(
        profile_id=layout.profile_id,
        readiness_status="blocked" if blocked_row_count else "ready",
        instruction_row_count=len(layout.instruction_rows),
        raw_template_row_hash_ready_count=raw_ready_count,
        blocked_row_count=blocked_row_count,
        span_hash_candidate_count=span_hash_candidate_count,
        records=records,
        blockers=tuple(blockers),
        diagnostics=diagnostics,
        bytes_emitted=False,
    )


def build_template_span_materialization_candidate_report(
    layout: BinaryLayoutPlan,
    span_hash_candidate_report: ExactTemplateSpanHashCandidateReport,
    selector_policy_report: ExactSpanRowSelectorPolicyReport | None = None,
) -> TemplateSpanMaterializationCandidateReport:
    """Build report-only multi-row inst_t span materialization candidates."""

    span_by_template_op_id = {
        record.template_op_id: record
        for record in span_hash_candidate_report.records
    }
    selector_report = selector_policy_report or build_exact_span_row_selector_policy_report(
        layout
    )
    selector_by_template_op_id = {
        record.template_op_id: record
        for record in selector_report.records
    }
    records = tuple(
        _template_span_materialization_candidate_record(
            row,
            span_candidate=span_by_template_op_id.get(row.template_op_id),
            selector=selector_by_template_op_id.get(row.template_op_id),
        )
        for row in layout.instruction_rows
    )
    candidate_count = sum(
        1
        for record in records
        if record.status == "span_materialization_candidate_available"
    )
    blocked_row_count = len(records) - candidate_count
    total_byte_count = sum(
        record.materialized_span_byte_count for record in records
    )
    raw_materialized_count = sum(
        1
        for record in records
        if record.byte_materializer_status == "raw_inst_t_row_bytes_available"
    )
    raw_overlay_consumable_count = sum(
        1 for record in records if record.raw_overlay_consumable
    )
    blockers: list[str] = []
    if blocked_row_count:
        blockers.append(
            "template span materialization candidates blocked: "
            f"{blocked_row_count} rows lack span hash candidates"
        )
    diagnostics = list(span_hash_candidate_report.diagnostics)
    diagnostics += selector_report.diagnostics
    if raw_materialized_count:
        diagnostics.append(
            "raw inst_t bytes materialized in-memory from exact selected legacy rows"
        )
    if raw_materialized_count != len(records):
        blockers.append(
            "raw inst_t byte materialization incomplete: "
            f"{len(records) - raw_materialized_count} rows still missing packed bytes"
        )
    return TemplateSpanMaterializationCandidateReport(
        profile_id=layout.profile_id,
        materialization_status=(
            "raw_inst_t_bytes_materialized"
            if raw_materialized_count == len(records) and records
            else ("candidate_report_only" if candidate_count else "blocked")
        ),
        instruction_row_count=len(layout.instruction_rows),
        materialized_span_candidate_count=candidate_count,
        blocked_row_count=blocked_row_count,
        materialized_span_total_byte_count=total_byte_count,
        raw_overlay_consumable_count=raw_overlay_consumable_count,
        records=records,
        blockers=tuple(blockers),
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        bytes_emitted=raw_materialized_count == len(records) and bool(records),
    )


def build_template_evidence_binding_report(
    layout: BinaryLayoutPlan,
) -> TemplateEvidenceBindingReport:
    """Match B-line rows to legacy template evidence without selecting bytes."""

    records = tuple(_evidence_record(row) for row in layout.instruction_rows)
    matched_count = sum(
        1 for record in records if record.binding_status != "unmatched"
    )
    missing_raw_template_bytes_count = sum(
        1 for record in records if record.missing_raw_template_bytes_reason is not None
    )
    unmatched_count = len(records) - matched_count
    candidate_hashes = tuple(
        sorted(
            (
                record.template_op_id,
                record.candidate_evidence_sha256,
            )
            for record in records
            if record.candidate_evidence_sha256 is not None
        )
    )
    blockers: list[str] = []
    if unmatched_count:
        blockers.append(
            "unmatched template evidence: "
            f"{unmatched_count} instruction rows lack role/opcode/phase policy"
        )
    if missing_raw_template_bytes_count:
        blockers.append(
            "missing exact raw template row bytes: "
            f"{missing_raw_template_bytes_count} rows need CSV path/local_order authority"
        )
    diagnostics = [
        f"{diagnostic.severity}:{diagnostic.code}:{diagnostic.subject_id}"
        for diagnostic in layout.diagnostics
    ]
    return TemplateEvidenceBindingReport(
        profile_id=layout.profile_id,
        binding_status="candidate_report_only" if not unmatched_count else "blocked",
        instruction_row_count=len(layout.instruction_rows),
        matched_template_evidence_count=matched_count,
        candidate_evidence_sha256_count=len(candidate_hashes),
        missing_raw_template_bytes_count=missing_raw_template_bytes_count,
        unmatched_template_evidence_count=unmatched_count,
        records=records,
        candidate_evidence_sha256_by_template_op_id=candidate_hashes,
        blockers=tuple(blockers),
        diagnostics=tuple(diagnostics),
    )


def build_exact_template_binding_seed_report(
    layout: BinaryLayoutPlan,
    evidence_report: TemplateEvidenceBindingReport | None = None,
    *,
    s1_representation_selection_complete: bool | object = False,
    task_resource_replay_authority_report: object | None = None,
) -> ExactTemplateBindingSeedReport:
    """Build the exact seed contract required for ``template_row_sha256``.

    Current B-line rows do not carry exact legacy CSV row identity.  The report
    therefore stays blocked and names the fields that an upstream owner must
    provide before S2 can hash real template row bytes.  S1 representation
    selection is fail-closed unless an explicit completed status is passed.
    """

    evidence = evidence_report or build_template_evidence_binding_report(layout)
    evidence_by_template_op_id = {
        record.template_op_id: record for record in evidence.records
    }
    source_plan_id = f"BinaryLayoutPlan:{layout.profile_id}"
    s1_status = (
        "closed"
        if _s1_representation_selection_complete(
            s1_representation_selection_complete
        )
        else "blocked_pending_s1_selection"
    )
    task_resource_authority_by_key = (
        _task_resource_replay_authority_status_by_role_opcode(
            task_resource_replay_authority_report
        )
    )
    task_resource_authority_status_counts: dict[str, int] = {}
    binding_items: list[TemplateRowSpanBinding] = []
    for row in layout.instruction_rows:
        authority_status = _task_resource_replay_authority_status_for_row(
            row,
            task_resource_authority_by_key,
            enabled=task_resource_replay_authority_report is not None,
        )
        _record_task_resource_replay_authority_status(
            task_resource_authority_status_counts,
            authority_status,
        )
        binding_items.append(
            _exact_seed_binding(
                row,
                source_plan_id=source_plan_id,
                evidence=evidence_by_template_op_id.get(row.template_op_id),
                s1_representation_selection_status=s1_status,
                task_resource_replay_row_authority_closed=(
                    authority_status == "closed"
                ),
            )
        )
    bindings = tuple(binding_items)
    missing_counts: dict[str, int] = {}
    for binding in bindings:
        for field in binding.missing_seed_fields:
            missing_counts[field] = missing_counts.get(field, 0) + 1
    blocked_row_count = sum(
        1
        for binding in bindings
        if binding.required_raw_template_bytes_status != "ready"
    )
    blockers = []
    if blocked_row_count:
        blockers.append(
            "exact template binding seed blocked: "
            f"{blocked_row_count} rows lack exact CSV row/span authority"
        )
    partial_candidate_row_count = sum(
        1
        for binding in bindings
        if binding.exact_seed_candidate_status.startswith("partial_")
    )
    single_candidate_row_count = sum(
        1 for binding in bindings if binding.candidate_raw_row_count == 1
    )
    if any(
        binding.s1_representation_selection_status != "closed"
        for binding in bindings
    ):
        blockers.append(
            "S1 representation selection blocked: representation selection is "
            "required before raw overlay row authority can be trusted"
        )
    diagnostics = [
        f"{diagnostic.severity}:{diagnostic.code}:{diagnostic.subject_id}"
        for diagnostic in layout.diagnostics
    ]
    diagnostics += evidence.diagnostics
    return ExactTemplateBindingSeedReport(
        profile_id=layout.profile_id,
        source_plan_id=source_plan_id,
        seed_status="ready" if blocked_row_count == 0 else "blocked",
        instruction_row_count=len(layout.instruction_rows),
        exact_bound_row_count=len(layout.instruction_rows) - blocked_row_count,
        partial_candidate_row_count=partial_candidate_row_count,
        single_candidate_row_count=single_candidate_row_count,
        blocked_row_count=blocked_row_count,
        missing_seed_field_counts=tuple(sorted(missing_counts.items())),
        bindings=bindings,
        blockers=tuple(blockers),
        diagnostics=tuple(diagnostics),
        task_resource_replay_authority_status_counts=tuple(
            sorted(task_resource_authority_status_counts.items())
        ),
    )


def summarize_exact_template_binding_seed_report(
    report: ExactTemplateBindingSeedReport,
) -> dict[str, object]:
    """Return stable counts for the exact seed gate."""

    status_counts: dict[str, int] = {}
    candidate_status_counts: dict[str, int] = {}
    s1_selection_status_counts: dict[str, int] = {}
    subtask_instance_status_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    closure_by_role: dict[str, dict[str, int | str]] = {}
    for binding in report.bindings:
        status_counts[binding.required_raw_template_bytes_status] = (
            status_counts.get(binding.required_raw_template_bytes_status, 0) + 1
        )
        candidate_status_counts[binding.exact_seed_candidate_status] = (
            candidate_status_counts.get(binding.exact_seed_candidate_status, 0) + 1
        )
        s1_selection_status_counts[binding.s1_representation_selection_status] = (
            s1_selection_status_counts.get(
                binding.s1_representation_selection_status, 0
            )
            + 1
        )
        subtask_instance_status_counts[binding.subtask_instance_semantics_status] = (
            subtask_instance_status_counts.get(
                binding.subtask_instance_semantics_status, 0
            )
            + 1
        )
        role_counts[binding.role] = role_counts.get(binding.role, 0) + 1
        role_record = closure_by_role.setdefault(
            binding.role,
            {
                "role": binding.role,
                "row_count": 0,
                "partial_candidate_row_count": 0,
                "single_candidate_raw_row_count": 0,
                "closed_row_count": 0,
                "closure_status": "requires_task_resource_replay_or_local_order",
            },
        )
        role_record["row_count"] = int(role_record["row_count"]) + 1
        if binding.exact_seed_candidate_status.startswith("partial_"):
            role_record["partial_candidate_row_count"] = (
                int(role_record["partial_candidate_row_count"]) + 1
            )
        if binding.candidate_raw_row_count == 1:
            role_record["single_candidate_raw_row_count"] = (
                int(role_record["single_candidate_raw_row_count"]) + 1
            )
        if binding.required_raw_template_bytes_status == "ready":
            role_record["closed_row_count"] = int(role_record["closed_row_count"]) + 1
    for role_record in closure_by_role.values():
        row_count = int(role_record["row_count"])
        single_count = int(role_record["single_candidate_raw_row_count"])
        closed_count = int(role_record["closed_row_count"])
        if closed_count == row_count:
            role_record["closure_status"] = "closed"
        elif single_count == row_count:
            role_record["closure_status"] = "single_candidate_pending_s1_selection"
    return {
        "profile_id": report.profile_id,
        "source_plan_id": report.source_plan_id,
        "seed_status": report.seed_status,
        "instruction_row_count": report.instruction_row_count,
        "exact_bound_row_count": report.exact_bound_row_count,
        "partial_candidate_row_count": report.partial_candidate_row_count,
        "single_candidate_row_count": report.single_candidate_row_count,
        "blocked_row_count": report.blocked_row_count,
        "missing_seed_field_counts": dict(report.missing_seed_field_counts),
        "task_resource_replay_authority_status_counts": dict(
            report.task_resource_replay_authority_status_counts
        ),
        "required_raw_template_bytes_status_counts": dict(sorted(status_counts.items())),
        "exact_seed_candidate_status_counts": dict(
            sorted(candidate_status_counts.items())
        ),
        "s1_representation_selection_status_counts": dict(
            sorted(s1_selection_status_counts.items())
        ),
        "subtask_instance_semantics_status_counts": dict(
            sorted(subtask_instance_status_counts.items())
        ),
        "exact_seed_closure_by_role": {
            role: dict(record)
            for role, record in sorted(closure_by_role.items())
        },
        "role_counts": dict(sorted(role_counts.items())),
        "blocker_count": len(report.blockers),
        "diagnostic_count": len(report.diagnostics),
    }


def summarize_template_evidence_binding_report(
    report: TemplateEvidenceBindingReport,
) -> dict[str, object]:
    """Return stable counts for the second S2 gate."""

    role_counts: dict[str, int] = {}
    binding_status_counts: dict[str, int] = {}
    legacy_block_kind_counts: dict[str, int] = {}
    candidate_raw_row_count_histogram: dict[int, int] = {}
    role_opcode_candidate_stats: dict[str, dict[str, int | str]] = {}
    for record in report.records:
        role_counts[record.role] = role_counts.get(record.role, 0) + 1
        binding_status_counts[record.binding_status] = (
            binding_status_counts.get(record.binding_status, 0) + 1
        )
        key = "none" if record.legacy_block_kind is None else record.legacy_block_kind
        legacy_block_kind_counts[key] = legacy_block_kind_counts.get(key, 0) + 1
        candidate_raw_row_count_histogram[record.candidate_raw_row_count] = (
            candidate_raw_row_count_histogram.get(record.candidate_raw_row_count, 0)
            + 1
        )
        role_opcode_key = f"{record.role}|{record.opcode}"
        stats = role_opcode_candidate_stats.setdefault(
            role_opcode_key,
            {
                "role": record.role,
                "opcode": record.opcode,
                "row_count": 0,
                "min_candidate_raw_row_count": record.candidate_raw_row_count,
                "max_candidate_raw_row_count": record.candidate_raw_row_count,
                "single_candidate_row_count": 0,
            },
        )
        stats["row_count"] = int(stats["row_count"]) + 1
        stats["min_candidate_raw_row_count"] = min(
            int(stats["min_candidate_raw_row_count"]),
            record.candidate_raw_row_count,
        )
        stats["max_candidate_raw_row_count"] = max(
            int(stats["max_candidate_raw_row_count"]),
            record.candidate_raw_row_count,
        )
        if record.candidate_raw_row_count == 1:
            stats["single_candidate_row_count"] = (
                int(stats["single_candidate_row_count"]) + 1
            )
    return {
        "profile_id": report.profile_id,
        "binding_status": report.binding_status,
        "instruction_row_count": report.instruction_row_count,
        "matched_template_evidence_count": report.matched_template_evidence_count,
        "candidate_evidence_sha256_count": report.candidate_evidence_sha256_count,
        "missing_raw_template_bytes_count": report.missing_raw_template_bytes_count,
        "unmatched_template_evidence_count": report.unmatched_template_evidence_count,
        "role_counts": dict(sorted(role_counts.items())),
        "binding_status_counts": dict(sorted(binding_status_counts.items())),
        "legacy_block_kind_counts": dict(sorted(legacy_block_kind_counts.items())),
        "candidate_raw_row_count_histogram": {
            str(count): rows
            for count, rows in sorted(candidate_raw_row_count_histogram.items())
        },
        "single_candidate_raw_row_count": candidate_raw_row_count_histogram.get(1, 0),
        "role_opcode_candidate_raw_row_counts": {
            key: dict(value)
            for key, value in sorted(role_opcode_candidate_stats.items())
        },
        "blocker_count": len(report.blockers),
        "diagnostic_count": len(report.diagnostics),
    }


def summarize_aline_template_span_candidate_report(
    report: AlineTemplateSpanCandidateReport,
) -> dict[str, object]:
    """Return stable counts for A-line catalog span candidates."""

    role_counts: dict[str, int] = {}
    status_counts: dict[str, int] = {}
    for record in report.records:
        role_counts[record.role] = role_counts.get(record.role, 0) + 1
        status_counts[record.span_binding_status] = (
            status_counts.get(record.span_binding_status, 0) + 1
        )
    return {
        "profile_id": report.profile_id,
        "binding_status": report.binding_status,
        "instruction_row_count": report.instruction_row_count,
        "catalog_available_row_count": report.catalog_available_row_count,
        "catalog_missing_row_count": report.catalog_missing_row_count,
        "catalog_unavailable_row_count": report.catalog_unavailable_row_count,
        "exact_single_row_count": report.exact_single_row_count,
        "row_span_required_count": report.row_span_required_count,
        "role_counts": dict(sorted(role_counts.items())),
        "span_binding_status_counts": dict(sorted(status_counts.items())),
        "blocker_count": len(report.blockers),
        "diagnostic_count": len(report.diagnostics),
        "bytes_emitted": report.bytes_emitted,
    }


def summarize_compressed_template_span_authority_report(
    report: CompressedTemplateSpanAuthorityReport,
) -> dict[str, object]:
    """Return stable counts for compressed-row span authority decisions."""

    status_counts: dict[str, int] = {}
    role_status_counts: dict[str, dict[str, int]] = {}
    task_resource_status_counts: dict[str, int] = {}
    for record in report.records:
        status_counts[record.span_authority_status] = (
            status_counts.get(record.span_authority_status, 0) + 1
        )
        role_counts = role_status_counts.setdefault(record.role, {})
        role_counts[record.span_authority_status] = (
            role_counts.get(record.span_authority_status, 0) + 1
        )
        task_resource_status_counts[record.task_resource_replay_authority_status] = (
            task_resource_status_counts.get(
                record.task_resource_replay_authority_status, 0
            )
            + 1
        )
    return {
        "profile_id": report.profile_id,
        "authority_status": report.authority_status,
        "instruction_row_count": report.instruction_row_count,
        "exact_span_count": report.exact_span_count,
        "span_policy_needed_count": report.span_policy_needed_count,
        "closed_policy_row_count": report.closed_policy_row_count,
        "blocked_policy_row_count": report.blocked_policy_row_count,
        "route_policy_closed_count": report.route_policy_closed_count,
        "route_policy_blocked_count": report.route_policy_blocked_count,
        "task_resource_partial_count": report.task_resource_partial_count,
        "span_authority_status_counts": dict(sorted(status_counts.items())),
        "task_resource_replay_authority_status_counts": dict(
            sorted(task_resource_status_counts.items())
        ),
        "role_status_counts": {
            role: dict(sorted(counts.items()))
            for role, counts in sorted(role_status_counts.items())
        },
        "role_next_decisions": {
            decision.role: decision.to_plan()
            for decision in report.role_decisions
        },
        "blocker_count": len(report.blockers),
        "diagnostic_count": len(report.diagnostics),
        "bytes_emitted": report.bytes_emitted,
    }


def summarize_exact_template_span_hash_candidate_report(
    report: ExactTemplateSpanHashCandidateReport,
) -> dict[str, object]:
    """Return stable counts for exact span hash candidates."""

    status_counts: dict[str, int] = {}
    role_status_counts: dict[str, dict[str, int]] = {}
    for record in report.records:
        status_counts[record.status] = status_counts.get(record.status, 0) + 1
        role_counts = role_status_counts.setdefault(record.role, {})
        role_counts[record.status] = role_counts.get(record.status, 0) + 1
    return {
        "profile_id": report.profile_id,
        "candidate_status": report.candidate_status,
        "instruction_row_count": report.instruction_row_count,
        "span_hash_candidate_count": report.span_hash_candidate_count,
        "blocked_row_count": report.blocked_row_count,
        "raw_overlay_consumable_count": report.raw_overlay_consumable_count,
        "status_counts": dict(sorted(status_counts.items())),
        "role_status_counts": {
            role: dict(sorted(counts.items()))
            for role, counts in sorted(role_status_counts.items())
        },
        "blocker_count": len(report.blockers),
        "diagnostic_count": len(report.diagnostics),
        "bytes_emitted": report.bytes_emitted,
    }


def summarize_exact_span_row_selector_policy_report(
    report: ExactSpanRowSelectorPolicyReport,
) -> dict[str, object]:
    """Return stable counts for exact CSV/template/local-order selectors."""

    status_counts: dict[str, int] = {}
    role_status_counts: dict[str, dict[str, int]] = {}
    role_selected_row_counts: dict[str, int] = {}
    missing_selector_field_counts: dict[str, int] = {}
    for record in report.records:
        status_counts[record.selector_status] = (
            status_counts.get(record.selector_status, 0) + 1
        )
        role_counts = role_status_counts.setdefault(record.role, {})
        role_counts[record.selector_status] = (
            role_counts.get(record.selector_status, 0) + 1
        )
        role_selected_row_counts[record.role] = (
            role_selected_row_counts.get(record.role, 0)
            + record.selected_row_count
        )
        for field in record.missing_selector_fields:
            missing_selector_field_counts[field] = (
                missing_selector_field_counts.get(field, 0) + 1
            )
    return {
        "profile_id": report.profile_id,
        "selector_status": report.selector_status,
        "instruction_row_count": report.instruction_row_count,
        "selector_candidate_count": report.selector_candidate_count,
        "blocked_row_count": report.blocked_row_count,
        "selected_row_total_count": report.selected_row_total_count,
        "selector_status_counts": dict(sorted(status_counts.items())),
        "role_status_counts": {
            role: dict(sorted(counts.items()))
            for role, counts in sorted(role_status_counts.items())
        },
        "role_selected_row_counts": dict(sorted(role_selected_row_counts.items())),
        "missing_selector_field_counts": dict(
            sorted(missing_selector_field_counts.items())
        ),
        "blocker_count": len(report.blockers),
        "diagnostic_count": len(report.diagnostics),
        "bytes_emitted": report.bytes_emitted,
    }


def summarize_raw_template_row_hash_readiness_report(
    report: RawTemplateRowHashReadinessReport,
) -> dict[str, object]:
    """Return stable counts for raw row hash readiness."""

    status_counts: dict[str, int] = {}
    role_status_counts: dict[str, dict[str, int]] = {}
    for record in report.records:
        status_counts[record.readiness_status] = (
            status_counts.get(record.readiness_status, 0) + 1
        )
        role_counts = role_status_counts.setdefault(record.role, {})
        role_counts[record.readiness_status] = (
            role_counts.get(record.readiness_status, 0) + 1
        )
    return {
        "profile_id": report.profile_id,
        "readiness_status": report.readiness_status,
        "instruction_row_count": report.instruction_row_count,
        "raw_template_row_hash_ready_count": (
            report.raw_template_row_hash_ready_count
        ),
        "blocked_row_count": report.blocked_row_count,
        "span_hash_candidate_count": report.span_hash_candidate_count,
        "readiness_status_counts": dict(sorted(status_counts.items())),
        "role_status_counts": {
            role: dict(sorted(counts.items()))
            for role, counts in sorted(role_status_counts.items())
        },
        "blocker_count": len(report.blockers),
        "diagnostic_count": len(report.diagnostics),
        "bytes_emitted": report.bytes_emitted,
    }


def summarize_template_span_materialization_candidate_report(
    report: TemplateSpanMaterializationCandidateReport,
) -> dict[str, object]:
    """Return stable counts for report-only span materialization candidates."""

    status_counts: dict[str, int] = {}
    role_status_counts: dict[str, dict[str, int]] = {}
    role_byte_counts: dict[str, int] = {}
    role_raw_byte_counts: dict[str, int] = {}
    materialization_kind_counts: dict[str, int] = {}
    template_binding_status_counts: dict[str, int] = {}
    byte_materializer_status_counts: dict[str, int] = {}
    missing_byte_materializer_input_counts: dict[str, int] = {}
    raw_inst_t_row_count = 0
    raw_inst_t_byte_count = 0
    for record in report.records:
        status_counts[record.status] = status_counts.get(record.status, 0) + 1
        materialization_kind_counts[record.materialization_kind] = (
            materialization_kind_counts.get(record.materialization_kind, 0) + 1
        )
        template_binding_status_counts[record.template_binding_status] = (
            template_binding_status_counts.get(record.template_binding_status, 0) + 1
        )
        byte_materializer_status_counts[record.byte_materializer_status] = (
            byte_materializer_status_counts.get(record.byte_materializer_status, 0)
            + 1
        )
        for missing_input in record.missing_byte_materializer_inputs:
            missing_byte_materializer_input_counts[missing_input] = (
                missing_byte_materializer_input_counts.get(missing_input, 0) + 1
            )
        role_counts = role_status_counts.setdefault(record.role, {})
        role_counts[record.status] = role_counts.get(record.status, 0) + 1
        role_byte_counts[record.role] = (
            role_byte_counts.get(record.role, 0)
            + record.materialized_span_byte_count
        )
        role_raw_byte_counts[record.role] = (
            role_raw_byte_counts.get(record.role, 0)
            + record.raw_inst_t_byte_count
        )
        raw_inst_t_row_count += record.raw_inst_t_row_count
        raw_inst_t_byte_count += record.raw_inst_t_byte_count
    return {
        "profile_id": report.profile_id,
        "materialization_status": report.materialization_status,
        "instruction_row_count": report.instruction_row_count,
        "materialized_span_candidate_count": (
            report.materialized_span_candidate_count
        ),
        "blocked_row_count": report.blocked_row_count,
        "materialized_span_total_byte_count": (
            report.materialized_span_total_byte_count
        ),
        "raw_overlay_consumable_count": report.raw_overlay_consumable_count,
        "status_counts": dict(sorted(status_counts.items())),
        "materialization_kind_counts": dict(
            sorted(materialization_kind_counts.items())
        ),
        "template_binding_status_counts": dict(
            sorted(template_binding_status_counts.items())
        ),
        "byte_materializer_status_counts": dict(
            sorted(byte_materializer_status_counts.items())
        ),
        "missing_byte_materializer_input_counts": dict(
            sorted(missing_byte_materializer_input_counts.items())
        ),
        "role_status_counts": {
            role: dict(sorted(counts.items()))
            for role, counts in sorted(role_status_counts.items())
        },
        "role_byte_counts": dict(sorted(role_byte_counts.items())),
        "role_raw_byte_counts": dict(sorted(role_raw_byte_counts.items())),
        "raw_inst_t_row_count": raw_inst_t_row_count,
        "raw_inst_t_byte_count": raw_inst_t_byte_count,
        "blocker_count": len(report.blockers),
        "diagnostic_count": len(report.diagnostics),
        "bytes_emitted": report.bytes_emitted,
    }


def summarize_raw_template_overlay_report(
    report: RawTemplateOverlayReport,
) -> dict[str, object]:
    """Return stable counts for focused S2 checks."""

    row_status_counts: dict[str, int] = {}
    opcode_counts: dict[str, int] = {}
    for row in report.rows:
        row_status_counts[row.writer_status] = (
            row_status_counts.get(row.writer_status, 0) + 1
        )
        opcode_counts[row.opcode] = opcode_counts.get(row.opcode, 0) + 1
    return {
        "profile_id": report.profile_id,
        "writer_status": report.writer_status,
        "struct_name": report.struct_name,
        "record_size_bytes": report.record_size_bytes,
        "instruction_row_count": report.instruction_row_count,
        "zero_instruction_boundary_count": report.zero_instruction_boundary_count,
        "symbolic_unresolved_count": report.symbolic_unresolved_count,
        "template_row_sha256_missing_count": (
            report.template_row_sha256_missing_count
        ),
        "patched_field_count": len(report.patched_fields),
        "zero_fill_field_count": len(report.zero_fill_fields),
        "template_backed_field_count": len(report.template_backed_fields),
        "forbidden_fields_touched_count": len(report.forbidden_fields_touched),
        "unknown_fields_touched_count": len(report.unknown_fields_touched),
        "row_status_counts": dict(sorted(row_status_counts.items())),
        "opcode_counts": dict(sorted(opcode_counts.items())),
        "blocker_count": len(report.blockers),
        "diagnostic_count": len(report.diagnostics),
        "bytes_emitted": report.bytes_emitted,
    }


def _row_report(
    row: BinaryInstructionPlan,
    *,
    template_row_sha256: str | None,
    patched_fields: tuple[str, ...],
    zero_fill_fields: tuple[str, ...],
) -> RawTemplateOverlayRowReport:
    touched_fields = tuple(patched_fields) + tuple(zero_fill_fields)
    forbidden_fields_touched = _sorted_unique(
        field for field in touched_fields if _is_forbidden_field(field)
    )
    unknown_fields_touched = _sorted_unique(
        field for field in patched_fields if field not in KNOWN_PATCHABLE_INST_T_FIELDS
    ) + _sorted_unique(
        field
        for field in zero_fill_fields
        if field not in KNOWN_ZERO_FILL_INST_T_FIELDS
    )
    blockers: list[str] = []
    if template_row_sha256 is None:
        blockers.append("template_row_sha256 missing")
    if forbidden_fields_touched:
        blockers.append("forbidden fields touched")
    if unknown_fields_touched:
        blockers.append("unknown fields touched")
    writer_status: WriterStatus
    if forbidden_fields_touched or unknown_fields_touched:
        writer_status = "failed"
    elif blockers:
        writer_status = "blocked"
    else:
        writer_status = "ready"
    return RawTemplateOverlayRowReport(
        row_id=row.id,
        row_index=row.row_index,
        pc=row.pc,
        template_op_id=row.template_op_id,
        opcode=row.opcode,
        template_row_sha256=template_row_sha256,
        patched_fields=tuple(patched_fields),
        zero_fill_fields=tuple(zero_fill_fields),
        template_backed_fields=(
            RAW_TEMPLATE_BACKED_INST_T_FIELDS
            if template_row_sha256 is not None
            else ()
        ),
        forbidden_fields_touched=forbidden_fields_touched,
        unknown_fields_touched=unknown_fields_touched,
        writer_status=writer_status,
        blockers=tuple(blockers),
    )


def _exact_seed_binding(
    row: BinaryInstructionPlan,
    *,
    source_plan_id: str,
    evidence: TemplateEvidenceBindingRecord | None,
    s1_representation_selection_status: str,
    task_resource_replay_row_authority_closed: bool = False,
) -> TemplateRowSpanBinding:
    candidate_evidence_sha256 = (
        None if evidence is None else evidence.candidate_evidence_sha256
    )
    candidate_raw_row_count = 0 if evidence is None else evidence.candidate_raw_row_count
    candidate_paths = () if evidence is None else evidence.candidate_legacy_csv_paths
    candidate_template_indexes = (
        () if evidence is None else evidence.candidate_template_indexes
    )
    single_candidate = candidate_raw_row_count == 1 and evidence is not None
    candidate_local_order: int | None = None
    candidate_template_row_sha256: str | None = None
    if single_candidate:
        candidate_local_order = _single_candidate_local_order(evidence)
        candidate_template_row_sha256 = (
            evidence.candidate_raw_row_sha256s[0]
            if evidence.candidate_raw_row_sha256s
            else None
        )
    exact_seed_candidate_status = _exact_seed_candidate_status(
        evidence,
        candidate_raw_row_count=candidate_raw_row_count,
    )
    required_status = _required_raw_template_bytes_status(
        exact_seed_candidate_status
    )
    missing_fields = _missing_seed_fields(
        evidence,
        candidate_local_order=candidate_local_order,
        candidate_template_row_sha256=candidate_template_row_sha256,
        s1_representation_selection_status=s1_representation_selection_status,
        task_resource_replay_row_authority_closed=(
            task_resource_replay_row_authority_closed
        ),
    )
    return TemplateRowSpanBinding(
        source_plan_id=source_plan_id,
        logical_row_id=row.id,
        template_op_id=row.template_op_id,
        role=row.role,
        opcode=row.opcode,
        phase=row.phase,
        legacy_csv_path=None,
        template_index=None,
        local_order=None,
        row_span=None,
        candidate_raw_row_count=candidate_raw_row_count,
        candidate_legacy_csv_paths=candidate_paths,
        candidate_template_indexes=candidate_template_indexes,
        candidate_local_order=candidate_local_order,
        candidate_template_row_sha256=candidate_template_row_sha256,
        exact_seed_candidate_status=exact_seed_candidate_status,
        candidate_evidence_sha256=candidate_evidence_sha256,
        required_raw_template_bytes_status=required_status,
        s1_representation_selection_status=s1_representation_selection_status,
        subtask_instance_semantics_status=s1_representation_selection_status,
        missing_seed_fields=missing_fields,
        shortest_owner_path=(
            "TemplateOpPlan attaches legacy template family and candidate evidence",
            "InstructionLayoutPlan narrows candidate legacy_csv_path/template_index",
            "TaskResourceReplay may close operand/COPY/block row authority",
            "end_inst remains instruction-boundary policy",
            "S1 selects concrete representation/base-slot ownership",
            "S2 hashes exact raw template row bytes into template_row_sha256",
        ),
        blockers=_exact_seed_blockers(
            exact_seed_candidate_status,
            s1_representation_selection_status=s1_representation_selection_status,
        ),
    )


def _aline_span_candidate_record(
    row: BinaryInstructionPlan,
    *,
    evidence: TemplateEvidenceBindingRecord | None,
    catalog_rows: tuple[object, ...],
    catalog_available: bool,
) -> AlineTemplateSpanCandidateRecord:
    if not catalog_available:
        return AlineTemplateSpanCandidateRecord(
            logical_row_id=row.id,
            template_op_id=row.template_op_id,
            role=row.role,
            opcode=row.opcode,
            candidate_catalog_row_count=0,
            candidate_catalog_sha256_count=0,
            candidate_catalog_span_sha256=None,
            candidate_csv_paths=(),
            candidate_template_indexes=(),
            span_binding_status="catalog_unavailable",
        )
    if evidence is None:
        return AlineTemplateSpanCandidateRecord(
            logical_row_id=row.id,
            template_op_id=row.template_op_id,
            role=row.role,
            opcode=row.opcode,
            candidate_catalog_row_count=0,
            candidate_catalog_sha256_count=0,
            candidate_catalog_span_sha256=None,
            candidate_csv_paths=(),
            candidate_template_indexes=(),
            span_binding_status="catalog_missing",
        )

    template_keys = _candidate_template_keys(
        row,
        evidence=evidence,
    )
    candidate_rows = tuple(
        catalog_row
        for catalog_row in catalog_rows
        if _catalog_row_matches_evidence(
            catalog_row,
            template_keys=template_keys,
            evidence=evidence,
        )
    )
    candidate_paths = _sorted_unique(
        _catalog_row_str(candidate, "csv_path")
        for candidate in candidate_rows
    )
    candidate_template_indexes = tuple(
        sorted(
            {
                index
                for index in (
                    _catalog_row_int(candidate, "template_index")
                    for candidate in candidate_rows
                )
                if index is not None
            }
        )
    )
    candidate_sha256s = _sorted_unique(
        _catalog_row_str(candidate, "row_sha256")
        for candidate in candidate_rows
    )
    span_sha256 = (
        None
        if not candidate_rows
        else _stable_sha256(
            {
                "artifact": "aline_catalog_candidate_span",
                "logical_row_id": row.id,
                "template_op_id": row.template_op_id,
                "role": row.role,
                "opcode": row.opcode,
                "candidate_rows": [
                    {
                        "csv_path": _catalog_row_str(candidate, "csv_path"),
                        "local_order": _catalog_row_int(candidate, "local_order"),
                        "row_sha256": _catalog_row_str(candidate, "row_sha256"),
                    }
                    for candidate in candidate_rows
                ],
            }
        )
    )
    return AlineTemplateSpanCandidateRecord(
        logical_row_id=row.id,
        template_op_id=row.template_op_id,
        role=row.role,
        opcode=row.opcode,
        candidate_catalog_row_count=len(candidate_rows),
        candidate_catalog_sha256_count=len(candidate_sha256s),
        candidate_catalog_span_sha256=span_sha256,
        candidate_csv_paths=candidate_paths,
        candidate_template_indexes=candidate_template_indexes,
        span_binding_status=(
            "catalog_candidate_available"
            if candidate_rows
            else "catalog_missing"
        ),
    )


def _compressed_span_authority_record(
    row: BinaryInstructionPlan,
    *,
    candidate: AlineTemplateSpanCandidateRecord | None,
    task_resource_replay_authority_status: str,
    enabled_role_span_policies: frozenset[str],
) -> CompressedTemplateSpanAuthorityRecord:
    policy = _compressed_span_policy_for_role(row.role)
    span_candidate_status: SpanCandidateStatus = (
        "catalog_missing" if candidate is None else candidate.span_binding_status
    )
    candidate_policy = ALINE_CATALOG_SPAN_CANDIDATE_POLICIES.get(row.role)
    route_candidate_policy = ROUTE_VISIBILITY_SPAN_CANDIDATE_POLICIES.get(row.role)
    candidate_policy_blockers = _span_policy_candidate_blockers(
        row,
        candidate=candidate,
        task_resource_replay_authority_status=(
            task_resource_replay_authority_status
        ),
        enabled_role_span_policies=enabled_role_span_policies,
    )
    policy_candidate_closed = not candidate_policy_blockers
    is_route_visibility_role = route_candidate_policy is not None
    is_partial_route_authority = (
        row.role == "operand_route_recv:A"
        and task_resource_replay_authority_status == "closed"
    )
    span_authority_status: SpanAuthorityStatus = (
        "route_span_policy_candidate_closed"
        if policy_candidate_closed and is_route_visibility_role
        else "span_policy_candidate_closed"
        if policy_candidate_closed
        else (
            "partial_route_authority_span_policy_needed"
            if is_partial_route_authority
            else "blocked_needs_span_policy"
        )
    )
    if policy_candidate_closed and is_route_visibility_role:
        blockers = (
            "route span policy candidate closed; exact route row bytes remain unavailable",
            "sender COPY exact span remains required"
            if row.role == "operand_route_recv:A"
            else "consumer LDN exact template row remains required",
            "raw overlay remains blocked until exact template row hash is bound",
        )
    elif policy_candidate_closed:
        blockers = (
            "span policy candidate closed; template_row_sha256 remains unavailable",
            "raw overlay remains blocked until exact template row hash is bound",
        )
    elif is_partial_route_authority:
        blockers = (
            "sender COPY route authority is partial; compressed span policy still needed",
            "template_row_sha256 remains unavailable",
        )
    else:
        blockers = (
            f"missing {policy['required_policy']}",
            "template_row_sha256 remains unavailable",
        )
    policy_id = None
    policy_source = None
    policy_candidate_close_reason = None
    if route_candidate_policy is not None:
        candidate_policy = route_candidate_policy
    if candidate_policy is not None:
        policy_id = str(candidate_policy["policy_id"])
        policy_source = str(candidate_policy["source"])
        if policy_candidate_closed:
            policy_candidate_close_reason = str(candidate_policy["close_reason"])
    return CompressedTemplateSpanAuthorityRecord(
        logical_row_id=row.id,
        template_op_id=row.template_op_id,
        role=row.role,
        opcode=row.opcode,
        candidate_catalog_row_count=(
            0 if candidate is None else candidate.candidate_catalog_row_count
        ),
        candidate_catalog_sha256_count=(
            0 if candidate is None else candidate.candidate_catalog_sha256_count
        ),
        candidate_catalog_span_sha256=(
            None if candidate is None else candidate.candidate_catalog_span_sha256
        ),
        span_candidate_status=span_candidate_status,
        task_resource_replay_authority_status=(
            task_resource_replay_authority_status
        ),
        span_authority_status=span_authority_status,
        required_policy=str(policy["required_policy"]),
        next_decision=str(policy["next_decision"]),
        policy_id=policy_id if policy_candidate_closed else None,
        policy_source=policy_source if policy_candidate_closed else None,
        does_not_emit_bytes=True,
        requires_template_row_hash=True,
        requires_sender_copy_exact_span=row.role == "operand_route_recv:A",
        policy_candidate_close_reason=policy_candidate_close_reason,
        policy_candidate_blockers=candidate_policy_blockers,
        blockers=blockers,
    )


def _enabled_role_span_policy_set(
    enabled_role_span_policies: Collection[str] | None,
) -> frozenset[str]:
    if enabled_role_span_policies is None:
        return frozenset()
    if isinstance(enabled_role_span_policies, str):
        return frozenset((enabled_role_span_policies,))
    return frozenset(str(role) for role in enabled_role_span_policies)


def _span_policy_candidate_blockers(
    row: BinaryInstructionPlan,
    *,
    candidate: AlineTemplateSpanCandidateRecord | None,
    task_resource_replay_authority_status: str,
    enabled_role_span_policies: frozenset[str],
) -> tuple[str, ...]:
    blockers: list[str] = []
    route_candidate_policy = ROUTE_VISIBILITY_SPAN_CANDIDATE_POLICIES.get(
        row.role
    )
    if row.role not in enabled_role_span_policies:
        blockers.append("role_span_policy_candidate_not_enabled")
    if (
        row.role not in ALINE_CATALOG_SPAN_CANDIDATE_POLICIES
        and route_candidate_policy is None
    ):
        blockers.append("no_aline_catalog_span_candidate_policy_for_role")
    if candidate is None:
        blockers.append("aline_catalog_span_candidate_missing_for_row")
    elif candidate.span_binding_status != "catalog_candidate_available":
        blockers.append(
            f"aline_catalog_span_candidate_status={candidate.span_binding_status}"
        )
    policy = _compressed_span_policy_for_role(row.role)
    if bool(policy["requires_task_resource_replay_authority"]):
        if task_resource_replay_authority_status != "closed":
            blockers.append("task_resource_replay_authority_not_closed")
    return tuple(blockers)


def _compressed_span_policy_for_role(role: str) -> dict[str, object]:
    return ROLE_COMPRESSED_SPAN_AUTHORITY_POLICIES.get(
        role,
        {
            "required_policy": "UNREGISTERED_COMPRESSED_SPAN_POLICY",
            "next_decision": f"register compressed-row span policy for {role}",
            "requires_task_resource_replay_authority": False,
        },
    )


def _compressed_span_role_decisions(
    records: tuple[CompressedTemplateSpanAuthorityRecord, ...],
) -> tuple[CompressedTemplateSpanRoleDecision, ...]:
    grouped: dict[str, list[CompressedTemplateSpanAuthorityRecord]] = {}
    for record in records:
        grouped.setdefault(record.role, []).append(record)

    decisions: list[CompressedTemplateSpanRoleDecision] = []
    for role, role_records in sorted(grouped.items()):
        first = role_records[0]
        policy = _compressed_span_policy_for_role(role)
        status_counts: dict[str, int] = {}
        for record in role_records:
            status_counts[record.span_authority_status] = (
                status_counts.get(record.span_authority_status, 0) + 1
            )
        task_resource_partial_count = sum(
            1
            for record in role_records
            if record.span_authority_status
            == "partial_route_authority_span_policy_needed"
        )
        closed_policy_count = status_counts.get(
            "span_policy_candidate_closed", 0
        ) + status_counts.get("route_span_policy_candidate_closed", 0)
        if closed_policy_count == len(role_records):
            policy_candidate_status = "span_policy_candidate_closed"
        elif closed_policy_count:
            policy_candidate_status = "mixed_span_policy_candidate_status"
        else:
            policy_candidate_status = "span_policy_candidate_blocked"
        policy_ids = _sorted_unique(
            record.policy_id
            for record in role_records
            if record.policy_id is not None
        )
        policy_sources = _sorted_unique(
            record.policy_source
            for record in role_records
            if record.policy_source is not None
        )
        policy_candidate_blockers = _sorted_unique(
            blocker
            for record in role_records
            for blocker in record.policy_candidate_blockers
        )
        requires_sender_copy_exact_span = any(
            record.requires_sender_copy_exact_span for record in role_records
        )
        decisions.append(
            CompressedTemplateSpanRoleDecision(
                role=role,
                opcode=first.opcode,
                row_count=len(role_records),
                status_counts=tuple(sorted(status_counts.items())),
                required_policy=str(policy["required_policy"]),
                next_decision=str(policy["next_decision"]),
                requires_task_resource_replay_authority=bool(
                    policy["requires_task_resource_replay_authority"]
                ),
                task_resource_partial_count=task_resource_partial_count,
                policy_candidate_status=policy_candidate_status,
                policy_id=policy_ids[0] if len(policy_ids) == 1 else None,
                policy_source=(
                    policy_sources[0] if len(policy_sources) == 1 else None
                ),
                does_not_emit_bytes=True,
                requires_template_row_hash=True,
                requires_sender_copy_exact_span=requires_sender_copy_exact_span,
                policy_candidate_blockers=policy_candidate_blockers,
            )
        )
    return tuple(decisions)


def _exact_span_hash_candidate_record(
    row: BinaryInstructionPlan,
    *,
    authority: CompressedTemplateSpanAuthorityRecord | None,
) -> ExactTemplateSpanHashCandidateRecord:
    closed_statuses = {
        "span_policy_candidate_closed",
        "route_span_policy_candidate_closed",
    }
    if authority is None or authority.span_authority_status not in closed_statuses:
        return ExactTemplateSpanHashCandidateRecord(
            logical_row_id=row.id,
            template_op_id=row.template_op_id,
            source_schedule_step_id=row.source_schedule_step_id,
            primary_fiber_op_id=row.primary_fiber_op_id,
            role=row.role,
            opcode=row.opcode,
            phase=row.phase,
            subtask_slot=row.subtask_slot,
            span_provenance_status=_span_provenance_status_for_row(row),
            status="blocked_missing_closed_span_policy",
            span_hash_sha256=None,
            candidate_catalog_row_count=(
                0 if authority is None else authority.candidate_catalog_row_count
            ),
            candidate_catalog_sha256_count=(
                0 if authority is None else authority.candidate_catalog_sha256_count
            ),
            candidate_catalog_span_sha256=(
                None if authority is None else authority.candidate_catalog_span_sha256
            ),
            policy_id=None if authority is None else authority.policy_id,
            raw_overlay_consumable=False,
            blockers=("closed compressed span policy is required",),
        )

    span_hash = _stable_sha256(
        {
            "artifact": "exact_template_span_hash_candidate",
            "logical_row_id": row.id,
            "template_op_id": row.template_op_id,
            "source_schedule_step_id": row.source_schedule_step_id,
            "primary_fiber_op_id": row.primary_fiber_op_id,
            "role": row.role,
            "opcode": row.opcode,
            "phase": row.phase,
            "subtask_slot": row.subtask_slot,
            "span_provenance_status": _span_provenance_status_for_row(row),
            "policy_id": authority.policy_id,
            "policy_source": authority.policy_source,
            "candidate_catalog_row_count": authority.candidate_catalog_row_count,
            "candidate_catalog_sha256_count": authority.candidate_catalog_sha256_count,
            "candidate_catalog_span_sha256": authority.candidate_catalog_span_sha256,
            "span_authority_status": authority.span_authority_status,
            "raw_overlay_consumable": False,
        }
    )
    return ExactTemplateSpanHashCandidateRecord(
        logical_row_id=row.id,
        template_op_id=row.template_op_id,
        source_schedule_step_id=row.source_schedule_step_id,
        primary_fiber_op_id=row.primary_fiber_op_id,
        role=row.role,
        opcode=row.opcode,
        phase=row.phase,
        subtask_slot=row.subtask_slot,
        span_provenance_status=_span_provenance_status_for_row(row),
        status="span_hash_candidate_available",
        span_hash_sha256=span_hash,
        candidate_catalog_row_count=authority.candidate_catalog_row_count,
        candidate_catalog_sha256_count=authority.candidate_catalog_sha256_count,
        candidate_catalog_span_sha256=authority.candidate_catalog_span_sha256,
        policy_id=authority.policy_id,
        raw_overlay_consumable=False,
        blockers=("span hash is not raw inst_t template_row_sha256",),
    )


def _raw_template_row_hash_readiness_record(
    row: BinaryInstructionPlan,
    *,
    span_candidate: ExactTemplateSpanHashCandidateRecord | None,
) -> RawTemplateRowHashReadinessRecord:
    if span_candidate is not None and span_candidate.raw_overlay_consumable:
        return RawTemplateRowHashReadinessRecord(
            logical_row_id=row.id,
            template_op_id=row.template_op_id,
            source_schedule_step_id=row.source_schedule_step_id,
            primary_fiber_op_id=row.primary_fiber_op_id,
            role=row.role,
            opcode=row.opcode,
            phase=row.phase,
            subtask_slot=row.subtask_slot,
            readiness_status="ready_raw_template_row_hash",
            span_hash_sha256=span_candidate.span_hash_sha256,
            template_row_sha256=span_candidate.span_hash_sha256,
            candidate_catalog_row_count=span_candidate.candidate_catalog_row_count,
            candidate_catalog_span_sha256=span_candidate.candidate_catalog_span_sha256,
            raw_overlay_consumable=True,
            blockers=(),
        )
    return RawTemplateRowHashReadinessRecord(
        logical_row_id=row.id,
        template_op_id=row.template_op_id,
        source_schedule_step_id=row.source_schedule_step_id,
        primary_fiber_op_id=row.primary_fiber_op_id,
        role=row.role,
        opcode=row.opcode,
        phase=row.phase,
        subtask_slot=row.subtask_slot,
        readiness_status="blocked_span_hash_is_not_raw_template_row",
        span_hash_sha256=(
            None if span_candidate is None else span_candidate.span_hash_sha256
        ),
        template_row_sha256=None,
        candidate_catalog_row_count=(
            0 if span_candidate is None else span_candidate.candidate_catalog_row_count
        ),
        candidate_catalog_span_sha256=(
            None if span_candidate is None else span_candidate.candidate_catalog_span_sha256
        ),
        raw_overlay_consumable=False,
        blockers=(
            "span hash candidate is audit-only and cannot be used as raw inst_t row hash",
            "multi-row span materialization must produce raw template_row_sha256",
        ),
    )


def _exact_span_row_selector_policy_record(
    row: BinaryInstructionPlan,
    *,
    evidence: TemplateEvidenceBindingRecord | None,
) -> ExactSpanRowSelectorPolicyRecord:
    role_policy = _selector_policy_id_for_row(row)
    if role_policy is None:
        return _blocked_selector_policy_record(
            row,
            selector_status="blocked_missing_selector_policy",
            blockers=("missing exact span row selector policy for role",),
            missing_selector_fields=("role_span_selector_policy",),
        )
    if evidence is None or evidence.legacy_block_kind is None:
        return _blocked_selector_policy_record(
            row,
            selector_status="blocked_missing_candidate_rows",
            selector_policy_id=role_policy,
            blockers=("missing legacy candidate evidence",),
            missing_selector_fields=("legacy_candidate_evidence",),
        )
    candidate_rows, _ = _candidate_raw_rows(
        row,
        legacy_block_kind=evidence.legacy_block_kind,
        legacy_ops=evidence.legacy_ops,
        legacy_stages=evidence.legacy_stages,
    )
    if not candidate_rows:
        return _blocked_selector_policy_record(
            row,
            selector_status="blocked_missing_candidate_rows",
            selector_policy_id=role_policy,
            blockers=("legacy candidate evidence produced no rows",),
            missing_selector_fields=("legacy_csv_path", "row_span_or_local_orders"),
        )
    paths = _sorted_unique(
        candidate.legacy_csv_path
        for candidate in candidate_rows
        if candidate.legacy_csv_path is not None
    )
    template_indexes = tuple(
        sorted(
            {
                int(candidate.template_index)
                for candidate in candidate_rows
                if candidate.template_index is not None
            }
        )
    )
    if len(paths) != 1 or len(template_indexes) != 1:
        return _blocked_selector_policy_record(
            row,
            selector_status="blocked_missing_candidate_rows",
            selector_policy_id=role_policy,
            blockers=(
                "exact span selector requires one legacy CSV and one template index",
            ),
            missing_selector_fields=("legacy_csv_path", "template_index"),
        )
    local_orders = tuple(candidate.local_order for candidate in candidate_rows)
    row_hashes = tuple(candidate.row_sha256 for candidate in candidate_rows)
    return ExactSpanRowSelectorPolicyRecord(
        logical_row_id=row.id,
        template_op_id=row.template_op_id,
        source_schedule_step_id=row.source_schedule_step_id,
        primary_fiber_op_id=row.primary_fiber_op_id,
        role=row.role,
        opcode=row.opcode,
        phase=row.phase,
        subtask_slot=row.subtask_slot,
        selector_status="selector_policy_candidate_available",
        selector_policy_id=role_policy,
        legacy_csv_path=paths[0],
        template_index=template_indexes[0],
        selected_row_span=_contiguous_span(local_orders),
        selected_local_orders=local_orders,
        selected_row_count=len(local_orders),
        selected_row_hash_sequence_sha256=_stable_sha256(
            {
                "artifact": "exact_span_row_selector_policy",
                "logical_row_id": row.id,
                "primary_fiber_op_id": row.primary_fiber_op_id,
                "role": row.role,
                "opcode": row.opcode,
                "selector_policy_id": role_policy,
                "legacy_csv_path": paths[0],
                "template_index": template_indexes[0],
                "local_orders": local_orders,
                "row_sha256s": row_hashes,
                "does_not_emit_bytes": True,
            }
        ),
        store_output_binding=(
            _store_output_binding_for_row(row) if row.role == "tile_store" else None
        ),
        selector_does_not_emit_bytes=True,
        missing_selector_fields=(),
        blockers=(
            "selector is exact for CSV/template/local_order span but not raw bytes",
        ),
    )


def _blocked_selector_policy_record(
    row: BinaryInstructionPlan,
    *,
    selector_status: ExactSpanRowSelectorStatus,
    selector_policy_id: str | None = None,
    blockers: tuple[str, ...],
    missing_selector_fields: tuple[str, ...],
) -> ExactSpanRowSelectorPolicyRecord:
    return ExactSpanRowSelectorPolicyRecord(
        logical_row_id=row.id,
        template_op_id=row.template_op_id,
        source_schedule_step_id=row.source_schedule_step_id,
        primary_fiber_op_id=row.primary_fiber_op_id,
        role=row.role,
        opcode=row.opcode,
        phase=row.phase,
        subtask_slot=row.subtask_slot,
        selector_status=selector_status,
        selector_policy_id=selector_policy_id,
        legacy_csv_path=None,
        template_index=None,
        selected_row_span=None,
        selected_local_orders=(),
        selected_row_count=0,
        selected_row_hash_sequence_sha256=None,
        store_output_binding=None,
        selector_does_not_emit_bytes=True,
        missing_selector_fields=missing_selector_fields,
        blockers=blockers,
    )


def _template_span_materialization_candidate_record(
    row: BinaryInstructionPlan,
    *,
    span_candidate: ExactTemplateSpanHashCandidateRecord | None,
    selector: ExactSpanRowSelectorPolicyRecord | None,
) -> TemplateSpanMaterializationCandidateRecord:
    required_inputs = _required_byte_materializer_inputs_for_row(row)
    if span_candidate is None or span_candidate.span_hash_sha256 is None:
        return TemplateSpanMaterializationCandidateRecord(
            logical_row_id=row.id,
            template_op_id=row.template_op_id,
            source_schedule_step_id=row.source_schedule_step_id,
            primary_fiber_op_id=row.primary_fiber_op_id,
            role=row.role,
            opcode=row.opcode,
            phase=row.phase,
            subtask_slot=row.subtask_slot,
            status="blocked_missing_span_hash_candidate",
            template_binding_status=_template_binding_status_for_row(row),
            materialization_kind=_materialization_kind_for_row(row),
            provenance_policy=_template_span_provenance_policy(row),
            materialized_span_row_count=0,
            materialized_span_byte_count=0,
            span_row_hash_sequence_sha256=None,
            selector_policy_status=(
                None if selector is None else selector.selector_status
            ),
            selector_policy_id=None if selector is None else selector.selector_policy_id,
            selected_legacy_csv_path=(
                None if selector is None else selector.legacy_csv_path
            ),
            selected_template_index=(
                None if selector is None else selector.template_index
            ),
            selected_row_span=None if selector is None else selector.selected_row_span,
            selected_local_orders=(
                () if selector is None else selector.selected_local_orders
            ),
            selected_row_hash_sequence_sha256=(
                None if selector is None else selector.selected_row_hash_sequence_sha256
            ),
            store_output_binding=(
                None if selector is None else selector.store_output_binding
            ),
            raw_inst_t_row_count=0,
            raw_inst_t_byte_count=0,
            raw_inst_t_row_bytes_sha256=None,
            raw_template_row_sha256=None,
            raw_overlay_consumable=False,
            raw_overlay_blocker_code="missing_span_hash_candidate",
            byte_materializer_status="blocked_missing_span_hash_candidate",
            required_byte_materializer_inputs=required_inputs,
            missing_byte_materializer_inputs=required_inputs,
            blockers=("span hash candidate is required before materialization",),
        )
    row_count = span_candidate.candidate_catalog_row_count
    missing_inputs = _missing_byte_materializer_inputs_for_row(
        row,
        span_candidate=span_candidate,
        selector=selector,
    )
    selector_available = (
        selector is not None
        and selector.selector_status == "selector_policy_candidate_available"
    )
    if selector_available:
        row_count = selector.selected_row_count
    raw_materialization = (
        _raw_inst_t_materialization_for_selector(row, selector)
        if selector_available and selector is not None
        else None
    )
    raw_template_row_sha256 = (
        None if raw_materialization is None else raw_materialization.sha256
    )
    missing_inputs = tuple(
        item
        for item in missing_inputs
        if not (
            raw_materialization is not None
            and item in {"raw_inst_t_row_bytes", "raw_template_row_sha256"}
        )
    )
    byte_materializer_status: ByteMaterializerStatus = (
        "raw_inst_t_row_bytes_available"
        if raw_materialization is not None
        else (
            "blocked_missing_raw_inst_t_row_bytes"
            if selector_available
            else "blocked_missing_exact_span_row_selector"
        )
    )
    blocker_messages: tuple[str, ...] = ()
    if raw_materialization is None:
        blocker_messages = (
            (
                "exact span selector is bound but row bytes/hash materialization is missing"
                if selector_available
                else "span candidate is audit-only until an exact span row selector is bound"
            ),
            "byte materializer must emit real row bytes and row hashes before template_row_sha256",
        )
    return TemplateSpanMaterializationCandidateRecord(
        logical_row_id=row.id,
        template_op_id=row.template_op_id,
        source_schedule_step_id=row.source_schedule_step_id,
        primary_fiber_op_id=row.primary_fiber_op_id,
        role=row.role,
        opcode=row.opcode,
        phase=row.phase,
        subtask_slot=row.subtask_slot,
        status="span_materialization_candidate_available",
        template_binding_status=_template_binding_status_for_row(row),
        materialization_kind=_materialization_kind_for_row(row),
        provenance_policy=_template_span_provenance_policy(row),
        materialized_span_row_count=row_count,
        materialized_span_byte_count=row_count * INST_T_RECORD_SIZE_BYTES,
        span_row_hash_sequence_sha256=(
            selector.selected_row_hash_sequence_sha256
            if selector_available
            else span_candidate.candidate_catalog_span_sha256
            or span_candidate.span_hash_sha256
        ),
        selector_policy_status=(
            None if selector is None else selector.selector_status
        ),
        selector_policy_id=None if selector is None else selector.selector_policy_id,
        selected_legacy_csv_path=(
            None if selector is None else selector.legacy_csv_path
        ),
        selected_template_index=None if selector is None else selector.template_index,
        selected_row_span=None if selector is None else selector.selected_row_span,
        selected_local_orders=(
            () if selector is None else selector.selected_local_orders
        ),
        selected_row_hash_sequence_sha256=(
            None if selector is None else selector.selected_row_hash_sequence_sha256
        ),
        store_output_binding=None if selector is None else selector.store_output_binding,
        raw_inst_t_row_count=(
            0 if raw_materialization is None else raw_materialization.row_count
        ),
        raw_inst_t_byte_count=(
            0 if raw_materialization is None else raw_materialization.byte_count
        ),
        raw_inst_t_row_bytes_sha256=(
            None if raw_materialization is None else raw_materialization.sha256
        ),
        raw_template_row_sha256=raw_template_row_sha256,
        raw_overlay_consumable=False,
        raw_overlay_blocker_code=(
            "materialized_span_is_not_single_raw_row"
            if raw_materialization is not None
            else (
                "missing_raw_inst_t_row_bytes"
                if selector_available
                else "missing_exact_span_row_selector"
            )
        ),
        byte_materializer_status=byte_materializer_status,
        required_byte_materializer_inputs=required_inputs,
        missing_byte_materializer_inputs=missing_inputs,
        blockers=blocker_messages,
    )


def _required_byte_materializer_inputs_for_row(
    row: BinaryInstructionPlan,
) -> tuple[str, ...]:
    common = (
        "legacy_csv_path",
        "template_index",
        "row_span_or_local_orders",
        "raw_inst_t_row_bytes",
        "raw_template_row_sha256",
    )
    if row.role == "compute_core:gemm_tile":
        return (
            "span_row_selector_policy",
            "primary_fiber_op_id",
            "source_schedule_step_id",
            *common,
            "span_row_hash_sequence_sha256",
        )
    if row.role == "tile_store":
        return (
            "store_output_binding",
            "primary_fiber_op_id",
            "source_schedule_step_id",
            *common,
        )
    if row.role == "tile_op:relu":
        return (
            "relu_zero_constant_row_selector",
            "relu_max_row_selector",
            "relu_input_operand_binding",
            "relu_zero_operand_index",
            "relu_output_operand_binding",
            "primary_fiber_op_id",
            "source_schedule_step_id",
            *common,
        )
    return (
        "role_span_selector_policy",
        "primary_fiber_op_id",
        "source_schedule_step_id",
        *common,
    )


def _raw_inst_t_materialization_for_selector(
    row: BinaryInstructionPlan,
    selector: ExactSpanRowSelectorPolicyRecord,
) -> RawInstTSpanMaterialization | None:
    if selector.template_index is None or not selector.selected_local_orders:
        return None
    block_kind = _materializer_legacy_block_kind_for_row(row)
    if block_kind is None:
        return None
    task_id = 0 if row.task_id is None else int(row.task_id)
    template = legacy_gemm_template_for_micro_block_kind(
        block_kind,
        task_index=task_id,
        template_index=selector.template_index,
    )
    packed_rows: list[bytes] = []
    for local_order in selector.selected_local_orders:
        if local_order < 0 or local_order >= len(template):
            return None
        packed_rows.append(pack_legacy_inst(template[local_order]))
    payload = b"".join(packed_rows)
    if not payload or len(payload) != len(packed_rows) * INST_T_RECORD_SIZE_BYTES:
        return None
    return RawInstTSpanMaterialization(
        row_count=len(packed_rows),
        byte_count=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _materializer_legacy_block_kind_for_row(
    row: BinaryInstructionPlan,
) -> str | None:
    if row.role == "compute_core:gemm_tile":
        return "compute_update"
    if row.role == "tile_store" and row.opcode == "STD":
        return "tile_store"
    return None


def _missing_byte_materializer_inputs_for_row(
    row: BinaryInstructionPlan,
    *,
    span_candidate: ExactTemplateSpanHashCandidateRecord,
    selector: ExactSpanRowSelectorPolicyRecord | None,
) -> tuple[str, ...]:
    selector_available = (
        selector is not None
        and selector.selector_status == "selector_policy_candidate_available"
    )
    missing = [
        "legacy_csv_path",
        "template_index",
        "row_span_or_local_orders",
        "raw_inst_t_row_bytes",
        "raw_template_row_sha256",
    ]
    if selector_available:
        missing = [
            item
            for item in missing
            if item
            not in {
                "legacy_csv_path",
                "template_index",
                "row_span_or_local_orders",
            }
        ]
    elif row.role == "compute_core:gemm_tile":
        missing.insert(0, "span_row_selector_policy")
    elif row.role == "tile_store":
        missing.insert(0, "store_output_binding")
    elif row.role == "tile_op:relu":
        missing = [
            "relu_zero_constant_row_selector",
            "relu_max_row_selector",
            "relu_input_operand_binding",
            "relu_zero_operand_index",
            "relu_output_operand_binding",
            *missing,
        ]
    else:
        missing.insert(0, "role_span_selector_policy")
    if (
        span_candidate.candidate_catalog_span_sha256 is None
        and not selector_available
    ):
        missing.append("span_row_hash_sequence_sha256")
    return tuple(missing)


def _materialization_kind_for_row(row: BinaryInstructionPlan) -> str:
    if row.role == "compute_core:gemm_tile":
        return "atomic_fiber_op_template_span"
    if row.role == "tile_store":
        return "store_tile_template_span"
    if row.role == "tile_op:relu":
        return "relu_tile_template_span"
    return "role_template_span"


def _template_binding_status_for_row(row: BinaryInstructionPlan) -> str:
    if row.role == "compute_core:gemm_tile":
        return "exact_gemm_template_span_candidate"
    if row.role == "tile_store" and row.opcode == "STD":
        return "std_store_binding_candidate"
    if row.role == "tile_op:relu":
        return "hmax_zero_relu_binding_candidate"
    return "role_template_span_candidate"


def _span_provenance_status_for_row(row: BinaryInstructionPlan) -> str:
    if row.role == "compute_core:gemm_tile":
        return "exact_gemm_template_span_preserves_gemm_tile_fiber_op"
    if row.role == "tile_store" and row.opcode == "STD":
        return "std_store_binding_preserves_store_tile_fiber_op"
    if row.role == "tile_op:relu":
        return "hmax_zero_binding_preserves_relu_tile_fiber_op"
    return "role_template_span_preserves_primary_fiber_op"


def _template_span_provenance_policy(row: BinaryInstructionPlan) -> str:
    if row.role == "compute_core:gemm_tile":
        return (
            "template_span_may_expand_internal_dfu3500_rows_but_primary_"
            "fiber_op_remains_gemm_tile"
        )
    if row.role == "tile_store":
        return "template_span_preserves_primary_store_tile_fiber_op"
    if row.role == "tile_op:relu":
        return (
            "template_span_may_expand_IMM_zero_plus_HMAX_or_FMAX_rows_but_"
            "primary_fiber_op_remains_relu_tile"
        )
    return "template_span_preserves_primary_fiber_op"


def _selector_policy_id_for_row(row: BinaryInstructionPlan) -> str | None:
    if row.role == "compute_core:gemm_tile":
        return "GEMM_TILE_HMMAL_LOCAL_ORDER_SPAN_SELECTOR_V1"
    if row.role == "tile_store" and row.opcode == "STD":
        return "STORE_TILE_STD_OUTPUT_LOCAL_ORDER_SELECTOR_V1"
    return None


def _contiguous_span(local_orders: tuple[int, ...]) -> tuple[int, int] | None:
    if not local_orders:
        return None
    sorted_orders = tuple(sorted(local_orders))
    start = sorted_orders[0]
    end = sorted_orders[-1]
    if sorted_orders == tuple(range(start, end + 1)):
        return (start, end)
    return None


def _store_output_binding_for_row(row: BinaryInstructionPlan) -> str | None:
    attrs = dict(row.attrs)
    operand_policy = attrs.get("operand_policy")
    if operand_policy != "output_tile_fragment":
        return None
    return f"{operand_policy}:{row.primary_fiber_op_id}:{row.subtask_slot}"


def _task_resource_replay_authority_status_by_role_opcode(
    report: object | None,
) -> dict[tuple[str, str], str]:
    """Read TaskResourceReplay authority coverage without importing DFU3500."""

    if report is None:
        return {}
    statuses = getattr(report, "role_statuses", None)
    if statuses is not None:
        return _task_resource_replay_authority_statuses_from_items(statuses)
    to_plan = getattr(report, "to_plan", None)
    if callable(to_plan):
        plan = to_plan()
        role_statuses = plan.get("role_statuses", {})
        if isinstance(role_statuses, Mapping):
            return _task_resource_replay_authority_statuses_from_items(
                role_statuses.values()
            )
    return {}


def _task_resource_replay_authority_statuses_from_items(
    items: object,
) -> dict[tuple[str, str], str]:
    statuses: dict[tuple[str, str], str] = {}
    for item in items:
        role = _authority_item_value(item, "role")
        opcode = _authority_item_value(item, "opcode")
        if role is None or opcode is None:
            continue
        blocked_count = _authority_item_int(
            item,
            "blocked_on_task_resource_row_count",
        )
        if blocked_count <= 0:
            continue
        status = str(_authority_item_value(item, "authority_status") or "")
        closed_fields = _authority_item_tuple(item, "closed_fields")
        non_replay_closed_fields = _authority_item_tuple(
            item,
            "non_replay_closed_fields",
        )
        if (
            status in {"closed", "partial"}
            and (closed_fields or non_replay_closed_fields)
        ):
            statuses[(str(role), str(opcode))] = "closed"
        else:
            statuses[(str(role), str(opcode))] = "open"
    return statuses


def _authority_item_value(item: object, field: str) -> object | None:
    if isinstance(item, Mapping):
        return item.get(field)
    return getattr(item, field, None)


def _authority_item_int(item: object, field: str) -> int:
    value = _authority_item_value(item, field)
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _authority_item_tuple(item: object, field: str) -> tuple[object, ...]:
    value = _authority_item_value(item, field)
    if value is None:
        return ()
    if isinstance(value, tuple):
        return value
    if isinstance(value, list):
        return tuple(value)
    return (value,)


def _task_resource_replay_authority_status_for_row(
    row: BinaryInstructionPlan,
    statuses_by_role_opcode: Mapping[tuple[str, str], str],
    *,
    enabled: bool,
) -> str:
    if not enabled:
        return "unreported"
    return statuses_by_role_opcode.get((row.role, row.opcode), "open")


def _record_task_resource_replay_authority_status(
    counts: dict[str, int],
    status: str,
) -> None:
    if status == "unreported":
        return
    counts[status] = counts.get(status, 0) + 1


def _s1_representation_selection_complete(status: bool | object) -> bool:
    if isinstance(status, bool):
        return status
    return bool(getattr(status, "selection_complete", False))


def _single_candidate_local_order(
    evidence: TemplateEvidenceBindingRecord,
) -> int | None:
    if evidence.candidate_raw_row_count != 1:
        return None
    candidate_rows = _candidate_rows_from_evidence(evidence)
    if len(candidate_rows) != 1:
        return None
    return candidate_rows[0].local_order


def _candidate_rows_from_evidence(
    evidence: TemplateEvidenceBindingRecord,
) -> tuple[CandidateRawTemplateRow, ...]:
    task_id = _task_id_from_row_id(evidence.row_id)
    template_indexes = evidence.candidate_template_indexes
    if task_id is None or not template_indexes or evidence.legacy_block_kind is None:
        return ()
    rows: list[CandidateRawTemplateRow] = []
    for template_index in template_indexes:
        template = legacy_gemm_template_for_micro_block_kind(
            evidence.legacy_block_kind,
            task_index=task_id,
            template_index=template_index,
        )
        path = _legacy_csv_path(
            task_id=task_id,
            legacy_block_kind=evidence.legacy_block_kind,
            template_index=template_index,
        )
        for local_order, inst in enumerate(template):
            stage = _stage_for_legacy_inst(inst)
            if inst.op_name not in evidence.legacy_ops or stage not in evidence.legacy_stages:
                continue
            rows.append(
                CandidateRawTemplateRow(
                    legacy_csv_path=path,
                    template_index=template_index,
                    local_order=local_order,
                    op_name=inst.op_name,
                    stage=stage,
                    row_sha256=hashlib.sha256(pack_legacy_inst(inst)).hexdigest(),
                )
            )
    return tuple(rows)


def _task_id_from_row_id(row_id: str) -> int | None:
    marker = ":t"
    if marker not in row_id:
        return None
    tail = row_id.split(marker, 1)[1]
    task_text = tail.split("_", 1)[0]
    try:
        return int(task_text)
    except ValueError:
        return None


def _exact_seed_candidate_status(
    evidence: TemplateEvidenceBindingRecord | None,
    *,
    candidate_raw_row_count: int,
) -> str:
    if evidence is None:
        return "blocked_missing_candidate_evidence"
    if candidate_raw_row_count == 0:
        return "blocked_no_candidate_raw_rows"
    if evidence.template_index_selection_status.startswith("blocked_pending_task"):
        return "partial_candidate_pending_task_resource_replay_row_authority"
    if candidate_raw_row_count == 1:
        return "partial_single_candidate_pending_s1_selection"
    return "partial_multi_candidate_pending_local_order"


def _required_raw_template_bytes_status(
    exact_seed_candidate_status: str,
) -> str:
    if exact_seed_candidate_status == "ready":
        return "ready"
    return exact_seed_candidate_status


def _missing_seed_fields(
    evidence: TemplateEvidenceBindingRecord | None,
    *,
    candidate_local_order: int | None,
    candidate_template_row_sha256: str | None,
    s1_representation_selection_status: str,
    task_resource_replay_row_authority_closed: bool = False,
) -> tuple[str, ...]:
    fields: list[str] = []
    if evidence is None or not evidence.candidate_legacy_csv_paths:
        fields.append("legacy_csv_path")
    if evidence is None or not evidence.candidate_template_indexes:
        fields.append("template_index")
    if candidate_local_order is None:
        fields.append("local_order_or_row_span")
    if candidate_template_row_sha256 is None:
        fields.append("template_row_sha256")
    if not task_resource_replay_row_authority_closed:
        fields.append("task_resource_replay_row_authority")
    if s1_representation_selection_status != "closed":
        fields.append("s1_representation_selection")
    return tuple(fields)


def _exact_seed_blockers(
    exact_seed_candidate_status: str,
    *,
    s1_representation_selection_status: str,
) -> tuple[str, ...]:
    blockers = ["missing TaskResourceReplay row authority"]
    if s1_representation_selection_status != "closed":
        blockers.append("S1 representation selection not closed")
    if exact_seed_candidate_status == "blocked_missing_candidate_evidence":
        blockers.insert(0, "missing candidate evidence")
    elif exact_seed_candidate_status == "blocked_no_candidate_raw_rows":
        blockers.insert(0, "legacy template source produced no candidate raw rows")
    elif exact_seed_candidate_status == "partial_multi_candidate_pending_local_order":
        blockers.insert(0, "multiple candidate legacy rows require local_order or row_span")
    elif (
        exact_seed_candidate_status
        == "partial_candidate_pending_task_resource_replay_row_authority"
    ):
        blockers.insert(0, "candidate row set requires TaskResourceReplay authority")
    elif exact_seed_candidate_status == "partial_single_candidate_pending_s1_selection":
        blockers.insert(0, "single candidate row is not final until S1 selection closes")
    return tuple(blockers)


def _evidence_record(row: BinaryInstructionPlan) -> TemplateEvidenceBindingRecord:
    policy = ROLE_EVIDENCE_POLICIES.get(row.role)
    if policy is None:
        return TemplateEvidenceBindingRecord(
            row_id=row.id,
            row_index=row.row_index,
            template_op_id=row.template_op_id,
            role=row.role,
            opcode=row.opcode,
            phase=row.phase,
            binding_status="unmatched",
            legacy_block_kind=None,
            legacy_ops=(),
            legacy_stages=(),
            candidate_raw_row_count=0,
            candidate_raw_row_sha256s=(),
            candidate_legacy_csv_paths=(),
            candidate_template_indexes=(),
            template_index_selection_status="blocked_missing_role_policy",
            candidate_evidence_sha256=None,
            missing_raw_template_bytes_reason="no role/opcode/phase evidence policy",
            blockers=("missing evidence policy",),
        )

    legacy_block_kind = str(policy["legacy_block_kind"])
    legacy_ops = tuple(str(item) for item in policy["legacy_ops"])
    legacy_stages = tuple(str(item) for item in policy["legacy_stages"])
    candidate_rows, template_index_status = _candidate_raw_rows(
        row,
        legacy_block_kind=legacy_block_kind,
        legacy_ops=legacy_ops,
        legacy_stages=legacy_stages,
    )
    candidate_hashes = tuple(candidate.row_sha256 for candidate in candidate_rows)
    candidate_paths = _sorted_unique(
        candidate.legacy_csv_path
        for candidate in candidate_rows
        if candidate.legacy_csv_path is not None
    )
    candidate_template_indexes = tuple(
        sorted(
            {
                int(candidate.template_index)
                for candidate in candidate_rows
                if candidate.template_index is not None
            }
        )
    )
    blockers = ()
    if not candidate_hashes:
        if row.role == "tile_op:relu":
            blockers = (
                "explicit ReLU writer entry exists but exact IMM/HMAX/FMAX raw rows are missing",
            )
        else:
            blockers = ("legacy template source produced no candidate raw rows",)
    candidate_evidence_sha256 = (
        _stable_sha256(
            {
                "artifact": "candidate_template_evidence",
                "role": row.role,
                "opcode": row.opcode,
                "phase": row.phase,
                "legacy_block_kind": legacy_block_kind,
                "legacy_ops": legacy_ops,
                "legacy_stages": legacy_stages,
                "candidate_raw_row_sha256s": candidate_hashes,
                "candidate_legacy_csv_paths": candidate_paths,
                "candidate_template_indexes": candidate_template_indexes,
                "template_index_selection_status": template_index_status,
                "candidate_is_not_exact_template_row": True,
                "candidate_raw_rows_missing": not candidate_hashes,
            }
        )
    )
    return TemplateEvidenceBindingRecord(
        row_id=row.id,
        row_index=row.row_index,
        template_op_id=row.template_op_id,
        role=row.role,
        opcode=row.opcode,
        phase=row.phase,
        binding_status=(
            str(policy["binding_status"])
            if candidate_hashes or row.role == "tile_op:relu"
            else "unmatched"
        ),
        legacy_block_kind=legacy_block_kind,
        legacy_ops=legacy_ops,
        legacy_stages=legacy_stages,
        candidate_raw_row_count=len(candidate_hashes),
        candidate_raw_row_sha256s=candidate_hashes,
        candidate_legacy_csv_paths=candidate_paths,
        candidate_template_indexes=candidate_template_indexes,
        template_index_selection_status=template_index_status,
        candidate_evidence_sha256=candidate_evidence_sha256,
        missing_raw_template_bytes_reason=str(
            policy["missing_raw_template_bytes_reason"]
        ),
        blockers=blockers,
    )


def _candidate_raw_rows(
    row: BinaryInstructionPlan,
    *,
    legacy_block_kind: str,
    legacy_ops: tuple[str, ...],
    legacy_stages: tuple[str, ...],
) -> tuple[tuple[CandidateRawTemplateRow, ...], str]:
    source_block_kind = _legacy_template_source_block_kind(legacy_block_kind)
    template_indexes, template_index_status = _candidate_template_indexes(
        row,
        legacy_block_kind=source_block_kind,
    )
    task_id = 0 if row.task_id is None else int(row.task_id)
    rows: list[CandidateRawTemplateRow] = []
    for template_index in template_indexes:
        template = legacy_gemm_template_for_micro_block_kind(
            source_block_kind,
            task_index=task_id,
            template_index=template_index,
        )
        legacy_csv_path = _legacy_csv_path(
            task_id=task_id,
            legacy_block_kind=source_block_kind,
            template_index=template_index,
        )
        for local_order, inst in enumerate(template):
            if inst.op_name not in legacy_ops:
                continue
            stage = _stage_for_legacy_inst(inst)
            if stage not in legacy_stages:
                continue
            rows.append(
                CandidateRawTemplateRow(
                    legacy_csv_path=legacy_csv_path,
                    template_index=template_index,
                    local_order=local_order,
                    op_name=inst.op_name,
                    stage=stage,
                    row_sha256=hashlib.sha256(pack_legacy_inst(inst)).hexdigest(),
                )
            )
    return (
        tuple(
            sorted(
                rows,
                key=lambda candidate: (
                    "" if candidate.legacy_csv_path is None else candidate.legacy_csv_path,
                    -1 if candidate.template_index is None else candidate.template_index,
                    candidate.local_order,
                    candidate.row_sha256,
                ),
            )
        ),
        template_index_status,
    )


def _candidate_template_indexes(
    row: BinaryInstructionPlan,
    *,
    legacy_block_kind: str,
) -> tuple[tuple[int, ...], str]:
    processor = _processor_from_stream_id(row.stream_id)
    if legacy_block_kind == "route_forward":
        # The B-line row is consumer visibility.  Sender-side COPY template
        # selection needs TaskResourceReplay, so keep every legal COPY source
        # template as a candidate instead of picking the consumer PE.
        return tuple(range(4, 16)), "blocked_pending_task_resource_replay_row_authority"
    if processor is None:
        return _fallback_template_indexes(
            legacy_block_kind
        ), "blocked_missing_stream_processor_selection"
    return (
        (
            _legacy_template_index_for_micro_block(
                legacy_block_kind,
                processor=processor,
            ),
        ),
        "candidate_from_stream_processor",
    )


def _fallback_template_indexes(legacy_block_kind: str) -> tuple[int, ...]:
    if legacy_block_kind == "compute_update":
        return tuple(range(16, 32))
    if legacy_block_kind == "route_source_materialize":
        return tuple(range(4))
    if legacy_block_kind == "route_forward":
        return tuple(range(4, 16))
    if legacy_block_kind in {"accumulator_prepare", "tile_store"}:
        return tuple(range(16))
    return (0,)


def _legacy_csv_path(
    *,
    task_id: int,
    legacy_block_kind: str,
    template_index: int,
) -> str:
    source_block_kind = _legacy_template_source_block_kind(legacy_block_kind)
    subtask = _legacy_subtask_for_block_kind(source_block_kind)
    return str(
        _legacy_gemm_template_root()
        / f"task{task_id}"
        / f"subtask{subtask}"
        / "template"
        / f"{template_index}.csv"
    )


def _legacy_subtask_for_block_kind(legacy_block_kind: str) -> int:
    legacy_block_kind = _legacy_template_source_block_kind(legacy_block_kind)
    if legacy_block_kind == "accumulator_prepare":
        return 1
    if legacy_block_kind in {
        "compute_update",
        "route_forward",
        "route_source_materialize",
    }:
        return 2
    if legacy_block_kind == "tile_store":
        return 3
    raise ValueError(f"unsupported legacy block kind: {legacy_block_kind}")


def _legacy_template_source_block_kind(legacy_block_kind: str) -> str:
    if legacy_block_kind == "gemm_tile_template_span":
        return "compute_update"
    if legacy_block_kind == "relu_tile_template_span":
        return "compute_update"
    return legacy_block_kind


def _processor_from_stream_id(stream_id: str | None) -> str | None:
    if stream_id is None or "_pe" not in stream_id:
        return None
    pe_text = stream_id.split("_pe", 1)[1]
    if len(pe_text) < 2 or not pe_text[0].isdigit() or not pe_text[1].isdigit():
        return None
    return f"processor_{int(pe_text[0])}_{int(pe_text[1])}"


def _candidate_raw_row_hashes(
    *,
    legacy_block_kind: str,
    legacy_ops: tuple[str, ...],
    legacy_stages: tuple[str, ...],
    task_id: int | None,
) -> tuple[str, ...]:
    source_block_kind = _legacy_template_source_block_kind(legacy_block_kind)
    template = legacy_gemm_template_for_micro_block_kind(
        source_block_kind,
        task_index=0 if task_id is None else task_id,
    )
    hashes = []
    for inst in template:
        if inst.op_name not in legacy_ops:
            continue
        if _stage_for_legacy_inst(inst) not in legacy_stages:
            continue
        hashes.append(hashlib.sha256(pack_legacy_inst(inst)).hexdigest())
    return tuple(sorted(dict.fromkeys(hashes)))


_TEMPLATE_PATH_RE = re.compile(
    r"/task(?P<task>\d+)/subtask(?P<subtask>\d+)/template/"
    r"(?P<template>\d+)\.csv$"
)


def _candidate_template_keys(
    row: BinaryInstructionPlan,
    *,
    evidence: TemplateEvidenceBindingRecord,
) -> tuple[tuple[int, int, int], ...]:
    keys = {
        key
        for key in (
            _template_key_from_path(path)
            for path in evidence.candidate_legacy_csv_paths
        )
        if key is not None
    }
    if keys:
        return tuple(sorted(keys))
    if evidence.legacy_block_kind is None:
        return ()
    task_id = 0 if row.task_id is None else int(row.task_id)
    subtask = _legacy_subtask_for_block_kind(evidence.legacy_block_kind)
    return tuple(
        sorted(
            (task_id, subtask, template_index)
            for template_index in evidence.candidate_template_indexes
        )
    )


def _template_key_from_path(path: str) -> tuple[int, int, int] | None:
    match = _TEMPLATE_PATH_RE.search(path)
    if match is None:
        return None
    return (
        int(match.group("task")),
        int(match.group("subtask")),
        int(match.group("template")),
    )


def _catalog_row_matches_evidence(
    catalog_row: object,
    *,
    template_keys: tuple[tuple[int, int, int], ...],
    evidence: TemplateEvidenceBindingRecord,
) -> bool:
    task_index = _catalog_row_int(catalog_row, "task_index")
    subtask_index = _catalog_row_int(catalog_row, "subtask_index")
    template_index = _catalog_row_int(catalog_row, "template_index")
    if (
        task_index is None
        or subtask_index is None
        or template_index is None
        or (task_index, subtask_index, template_index) not in template_keys
    ):
        return False
    stage = _catalog_row_str(catalog_row, "stage")
    if stage not in evidence.legacy_stages:
        return False
    inst_name = _catalog_row_str(catalog_row, "inst_name")
    op_name = _catalog_row_str(catalog_row, "op_name")
    return inst_name in evidence.legacy_ops or op_name in evidence.legacy_ops


def _catalog_row_str(row: object, field: str) -> str:
    value = getattr(row, field, "")
    return "" if value is None else str(value)


def _catalog_row_int(row: object, field: str) -> int | None:
    value = getattr(row, field, None)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _stable_sha256(payload: dict[str, object]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _overall_status(
    *,
    symbolic_unresolved_count: int,
    forbidden_fields_touched: tuple[str, ...],
    unknown_fields_touched: tuple[str, ...],
    template_row_sha256_missing_count: int,
    layout_valid: bool,
) -> WriterStatus:
    if (
        symbolic_unresolved_count > 0
        or forbidden_fields_touched
        or unknown_fields_touched
        or not layout_valid
    ):
        return "failed"
    if template_row_sha256_missing_count > 0:
        return "blocked"
    return "ready"


def _row_attr_str(row: BinaryInstructionPlan, key: str) -> str | None:
    for attr_key, value in row.attrs:
        if attr_key == key:
            return None if value is None else str(value)
    return None


def _is_forbidden_field(field: str) -> bool:
    return field in FORBIDDEN_FIELD_NAMES or any(
        field.startswith(prefix) for prefix in FORBIDDEN_FIELD_PREFIXES
    )


def _sorted_unique(values: object) -> tuple[str, ...]:
    return tuple(sorted({str(value) for value in values}))


__all__ = [
    "AlineTemplateSpanCandidateRecord",
    "AlineTemplateSpanCandidateReport",
    "CandidateRawTemplateRow",
    "CompressedTemplateSpanAuthorityRecord",
    "CompressedTemplateSpanAuthorityReport",
    "CompressedTemplateSpanRoleDecision",
    "ExactSpanRowSelectorPolicyRecord",
    "ExactSpanRowSelectorPolicyReport",
    "ExactTemplateBindingSeedReport",
    "ExactTemplateSpanHashCandidateRecord",
    "ExactTemplateSpanHashCandidateReport",
    "RawTemplateOverlayReport",
    "RawTemplateOverlayRowReport",
    "RawTemplateRowHashReadinessRecord",
    "RawTemplateRowHashReadinessReport",
    "TemplateSpanMaterializationCandidateRecord",
    "TemplateSpanMaterializationCandidateReport",
    "TemplateRowSpanBinding",
    "TemplateEvidenceBindingRecord",
    "TemplateEvidenceBindingReport",
    "build_aline_template_span_candidate_report",
    "build_compressed_template_span_authority_report",
    "build_exact_span_row_selector_policy_report",
    "build_exact_template_binding_seed_report",
    "build_exact_template_span_hash_candidate_report",
    "build_raw_template_row_hash_readiness_report",
    "build_raw_template_overlay_report",
    "build_template_span_materialization_candidate_report",
    "build_template_evidence_binding_report",
    "summarize_aline_template_span_candidate_report",
    "summarize_compressed_template_span_authority_report",
    "summarize_exact_span_row_selector_policy_report",
    "summarize_exact_template_binding_seed_report",
    "summarize_exact_template_span_hash_candidate_report",
    "summarize_raw_template_row_hash_readiness_report",
    "summarize_raw_template_overlay_report",
    "summarize_template_span_materialization_candidate_report",
    "summarize_template_evidence_binding_report",
]
