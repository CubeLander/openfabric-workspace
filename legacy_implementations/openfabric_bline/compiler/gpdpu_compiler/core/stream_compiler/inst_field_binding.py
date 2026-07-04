"""Field-owner binding reports for candidate ``inst_t`` rows.

This module is the Phase-0 stop-bleed layer before raw bytes.  It joins
template intent, operand patches, and field-default evidence into an explicit
field-owner map.  It deliberately does not emit final row bytes, component
offsets, route row bytes, or runtime-ready claims.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .log10max_ring_update_operands import (
    InstOperandPatch,
    RingUpdateInstOperandPatchReport,
    build_log10max_ring_update_inst_operand_patch_report,
)
from .log10max_ring_update_template import (
    RING_UPDATE_BYPASS_BITS,
    RING_UPDATE_FMAX_ITER_EXE_COND,
    RING_UPDATE_FMAX_LATENCY,
    RING_UPDATE_FMAX_OPCODE,
    RING_UPDATE_FMAX_UNIT_INST_TYPE,
    RING_UPDATE_FORWARDING_BITS,
    RingUpdateBinaryLayoutCandidateReport,
    RingUpdateBinaryLayoutRowCandidate,
    build_log10max_ring_update_binary_layout_candidate_report,
)


FieldOwnerKind = Literal[
    "opcode_binding",
    "operand_patch",
    "route_endpoint_patch",
    "immediate_binding",
    "instruction_layout",
    "exe_block_writer_plan",
    "component_placement",
    "boundary_policy",
    "fetch_policy",
    "forwarding_bypass_plan",
    "extra_field_binding",
    "zero_with_evidence",
    "source_template_fixed",
    "pending_blocker",
]
FieldBindingStatus = Literal["bound", "blocked", "zero_with_evidence", "pending"]

LOG10MAX_FMAX_FIELD_BINDING_LAYOUT_BLOCKER = (
    "log10max_ring_update_instruction_layout_pending"
)
LOG10MAX_FMAX_FIELD_BINDING_EXEBLOCK_BLOCKER = (
    "log10max_ring_update_exe_block_writer_plan_pending"
)
LOG10MAX_FMAX_FIELD_BINDING_BOUNDARY_BLOCKER = (
    "log10max_ring_update_boundary_policy_pending"
)
LOG10MAX_FMAX_FIELD_BINDING_COMPONENT_BLOCKER = (
    "log10max_ring_update_component_placement_pending"
)

LOG10MAX_FMAX_FIELD_BINDING_PENDING_BLOCKERS = (
    LOG10MAX_FMAX_FIELD_BINDING_LAYOUT_BLOCKER,
    LOG10MAX_FMAX_FIELD_BINDING_EXEBLOCK_BLOCKER,
    LOG10MAX_FMAX_FIELD_BINDING_BOUNDARY_BLOCKER,
    LOG10MAX_FMAX_FIELD_BINDING_COMPONENT_BLOCKER,
)


@dataclass(frozen=True)
class InstFieldOwnerBinding:
    """Owner proof for one field path inside a candidate ``inst_t`` row."""

    field_path: str
    owner_kind: FieldOwnerKind
    owner_id: str
    binding_status: FieldBindingStatus
    decoded_value: object | None
    blockers: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "field_path": self.field_path,
            "owner_kind": self.owner_kind,
            "owner_id": self.owner_id,
            "binding_status": self.binding_status,
            "decoded_value": self.decoded_value,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class InstFieldBindingRecord:
    """Field-owner join record for one future ``inst_t`` row candidate."""

    schema_version: str
    field_binding_id: str
    row_candidate_id: str
    row_index: int
    pc: int
    template_op_id: str
    template_expansion_id: str
    source_ring_edge_id: str
    source_fiber_op_id: str
    source_stream_action_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    opcode: Literal["FMAX"]
    base_materialization: Literal["native_template_row", "source_template_fixed"]
    field_patch_kinds: tuple[
        Literal[
            "opcode_binding",
            "operand_patch",
            "immediate_binding",
            "layout_binding",
            "boundary_policy",
            "default_field_policy",
        ],
        ...,
    ]
    opcode_binding_id: str
    operand_patch_id: str | None
    route_endpoint_patch_id: str | None
    immediate_binding_id: str | None
    instruction_layout_plan_id: str | None
    exe_block_writer_plan_id: str | None
    component_placement_plan_id: str | None
    boundary_policy_id: str | None
    field_bindings: tuple[InstFieldOwnerBinding, ...]
    missing_fields: tuple[str, ...]
    blocker_ids: tuple[str, ...]
    field_binding_status: Literal[
        "candidate_field_bindings_pending_layout",
        "blocked_missing_operand_patch",
    ]
    placement_status: Literal["unplaced_candidate"]
    component_byte_offset: int | None
    raw_inst_t_byte_count: int
    final_row_bytes_claim: bool
    component_integration_claim: bool
    runtime_ready: bool
    uploadable: bool

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "field_binding_id": self.field_binding_id,
            "row_candidate_id": self.row_candidate_id,
            "row_index": self.row_index,
            "pc": self.pc,
            "template_op_id": self.template_op_id,
            "template_expansion_id": self.template_expansion_id,
            "source_ring_edge_id": self.source_ring_edge_id,
            "source_fiber_op_id": self.source_fiber_op_id,
            "source_stream_action_id": self.source_stream_action_id,
            "phase": self.phase,
            "opcode": self.opcode,
            "base_materialization": self.base_materialization,
            "field_patch_kinds": list(self.field_patch_kinds),
            "opcode_binding_id": self.opcode_binding_id,
            "operand_patch_id": self.operand_patch_id,
            "route_endpoint_patch_id": self.route_endpoint_patch_id,
            "immediate_binding_id": self.immediate_binding_id,
            "instruction_layout_plan_id": self.instruction_layout_plan_id,
            "exe_block_writer_plan_id": self.exe_block_writer_plan_id,
            "component_placement_plan_id": self.component_placement_plan_id,
            "boundary_policy_id": self.boundary_policy_id,
            "field_bindings": [binding.to_plan() for binding in self.field_bindings],
            "missing_fields": list(self.missing_fields),
            "blocker_ids": list(self.blocker_ids),
            "field_binding_status": self.field_binding_status,
            "placement_status": self.placement_status,
            "component_byte_offset": self.component_byte_offset,
            "raw_inst_t_byte_count": self.raw_inst_t_byte_count,
            "row_body_bytes_claim": False,
            "final_row_bytes_claim": self.final_row_bytes_claim,
            "component_integration_claim": self.component_integration_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }


@dataclass(frozen=True)
class InstFieldBindingReport:
    """Phase-0 report for field-owner closure on candidate rows."""

    profile_id: str
    source_layout_report_id: str
    source_patch_report_id: str
    records: tuple[InstFieldBindingRecord, ...]

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.records:
            blockers.append("log10max_ring_update_inst_field_binding_missing")
        for record in self.records:
            blockers.extend(record.blocker_ids)
        return tuple(dict.fromkeys(blockers))

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def uploadable(self) -> bool:
        return False

    def summary(self) -> dict[str, object]:
        status_counts: dict[str, int] = {}
        phase_counts: dict[str, int] = {}
        owner_counts: dict[str, int] = {}
        field_status_counts: dict[str, int] = {}
        zero_with_evidence_count = 0
        pending_field_count = 0
        for record in self.records:
            status_counts[record.field_binding_status] = (
                status_counts.get(record.field_binding_status, 0) + 1
            )
            phase_counts[record.phase] = phase_counts.get(record.phase, 0) + 1
            for binding in record.field_bindings:
                owner_counts[binding.owner_kind] = (
                    owner_counts.get(binding.owner_kind, 0) + 1
                )
                field_status_counts[binding.binding_status] = (
                    field_status_counts.get(binding.binding_status, 0) + 1
                )
                if binding.binding_status == "zero_with_evidence":
                    zero_with_evidence_count += 1
                if binding.binding_status == "pending":
                    pending_field_count += 1
        return {
            "profile_id": self.profile_id,
            "source_layout_report_id": self.source_layout_report_id,
            "source_patch_report_id": self.source_patch_report_id,
            "record_count": len(self.records),
            "phase_counts": dict(sorted(phase_counts.items())),
            "field_binding_status_counts": dict(sorted(status_counts.items())),
            "owner_kind_counts": dict(sorted(owner_counts.items())),
            "field_status_counts": dict(sorted(field_status_counts.items())),
            "zero_with_evidence_count": zero_with_evidence_count,
            "pending_field_count": pending_field_count,
            "blocker_ids": list(self.blocker_ids),
            "raw_inst_t_byte_count": 0,
            "row_body_bytes_claim": False,
            "final_row_bytes_claim": False,
            "component_integration_claim": False,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "inst_field_binding_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "blocker_ids": list(self.blocker_ids),
            "records": [record.to_plan() for record in self.records],
            "layering_policy": (
                "field bindings join template intent and operand patches into "
                "field-owner evidence only; no final inst_t bytes, route row "
                "bytes, component offsets, or runtime_ready transition are emitted"
            ),
        }


def build_log10max_ring_update_inst_field_binding_report(
    layout_report: RingUpdateBinaryLayoutCandidateReport | None = None,
    patch_report: RingUpdateInstOperandPatchReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_ring_update_inst_field_binding_v1",
) -> InstFieldBindingReport:
    """Build Phase-0 field-owner records for the 30 ring FMAX update rows."""

    layout = layout_report or build_log10max_ring_update_binary_layout_candidate_report()
    patches = patch_report or build_log10max_ring_update_inst_operand_patch_report(
        layout_report=layout
    )
    patch_by_row = {patch.row_candidate_id: patch for patch in patches.patches}
    return InstFieldBindingReport(
        profile_id=profile_id,
        source_layout_report_id=layout.profile_id,
        source_patch_report_id=patches.profile_id,
        records=tuple(
            _record_for_row(row, patch_by_row.get(row.row_candidate_id))
            for row in layout.row_candidates
        ),
    )


def summarize_inst_field_binding_report(
    report: InstFieldBindingReport,
) -> dict[str, object]:
    return report.summary()


def _record_for_row(
    row: RingUpdateBinaryLayoutRowCandidate,
    patch: InstOperandPatch | None,
) -> InstFieldBindingRecord:
    missing_fields = (
        "block_idx",
        "end_inst",
        "instruction_layout_plan_id",
        "exe_block_writer_plan_id",
        "component_placement_plan_id",
        "component_byte_offset",
    )
    blockers = list(LOG10MAX_FMAX_FIELD_BINDING_PENDING_BLOCKERS)
    field_bindings = list(_template_field_bindings())
    if patch is None or patch.patch_status != "patched":
        blockers.insert(0, "log10max_ring_update_inst_operand_patch_missing")
        operand_patch_id = None
        field_bindings.extend(_blocked_operand_field_bindings())
        status: Literal[
            "candidate_field_bindings_pending_layout",
            "blocked_missing_operand_patch",
        ] = "blocked_missing_operand_patch"
    else:
        operand_patch_id = patch.patch_id
        field_bindings.extend(_operand_patch_field_bindings(patch))
        status = "candidate_field_bindings_pending_layout"
    field_bindings.extend(_pending_layout_field_bindings())
    return InstFieldBindingRecord(
        schema_version="1",
        field_binding_id=f"field_binding:{row.row_candidate_id}",
        row_candidate_id=row.row_candidate_id,
        row_index=row.row_index,
        pc=row.pc,
        template_op_id=row.template_op_id,
        template_expansion_id=row.template_expansion_id,
        source_ring_edge_id=row.source_ring_edge_id,
        source_fiber_op_id=row.source_fiber_op_id,
        source_stream_action_id=row.source_stream_action_id,
        phase=row.phase,
        opcode="FMAX",
        base_materialization="native_template_row",
        field_patch_kinds=(
            "opcode_binding",
            "operand_patch",
            "immediate_binding",
            "default_field_policy",
        ),
        opcode_binding_id="opcode:dfu3500_log10max_ring_globalmax_update:FMAX",
        operand_patch_id=operand_patch_id,
        route_endpoint_patch_id=None,
        immediate_binding_id="immediate:fmax_no_immediate_v1",
        instruction_layout_plan_id=None,
        exe_block_writer_plan_id=None,
        component_placement_plan_id=None,
        boundary_policy_id=None,
        field_bindings=tuple(field_bindings),
        missing_fields=missing_fields,
        blocker_ids=tuple(dict.fromkeys(blockers)),
        field_binding_status=status,
        placement_status="unplaced_candidate",
        component_byte_offset=None,
        raw_inst_t_byte_count=0,
        final_row_bytes_claim=False,
        component_integration_claim=False,
        runtime_ready=False,
        uploadable=False,
    )


def _template_field_bindings() -> tuple[InstFieldOwnerBinding, ...]:
    opcode_owner = "opcode:dfu3500_log10max_ring_globalmax_update:FMAX"
    immediate_owner = "immediate:fmax_no_immediate_v1"
    return (
        InstFieldOwnerBinding(
            field_path="opCode",
            owner_kind="opcode_binding",
            owner_id=opcode_owner,
            binding_status="bound",
            decoded_value=RING_UPDATE_FMAX_OPCODE,
        ),
        InstFieldOwnerBinding(
            field_path="unit_inst_type",
            owner_kind="opcode_binding",
            owner_id=opcode_owner,
            binding_status="bound",
            decoded_value=RING_UPDATE_FMAX_UNIT_INST_TYPE,
        ),
        InstFieldOwnerBinding(
            field_path="latency",
            owner_kind="opcode_binding",
            owner_id=opcode_owner,
            binding_status="bound",
            decoded_value=RING_UPDATE_FMAX_LATENCY,
        ),
        InstFieldOwnerBinding(
            field_path="imms[0]",
            owner_kind="zero_with_evidence",
            owner_id=immediate_owner,
            binding_status="zero_with_evidence",
            decoded_value=0,
        ),
        InstFieldOwnerBinding(
            field_path="imms[1]",
            owner_kind="zero_with_evidence",
            owner_id=immediate_owner,
            binding_status="zero_with_evidence",
            decoded_value=0,
        ),
        InstFieldOwnerBinding(
            field_path="imms[2]",
            owner_kind="zero_with_evidence",
            owner_id=immediate_owner,
            binding_status="zero_with_evidence",
            decoded_value=0,
        ),
        InstFieldOwnerBinding(
            field_path="forwarding_bits",
            owner_kind="forwarding_bypass_plan",
            owner_id="forwarding_bypass:fmax_update_v1",
            binding_status="bound",
            decoded_value=RING_UPDATE_FORWARDING_BITS,
        ),
        InstFieldOwnerBinding(
            field_path="bypass_bits",
            owner_kind="forwarding_bypass_plan",
            owner_id="forwarding_bypass:fmax_update_v1",
            binding_status="bound",
            decoded_value=RING_UPDATE_BYPASS_BITS,
        ),
        InstFieldOwnerBinding(
            field_path="iter_exe_cond",
            owner_kind="fetch_policy",
            owner_id="fetch_policy:fmax_update_iter_exe_cond_v1",
            binding_status="bound",
            decoded_value=RING_UPDATE_FMAX_ITER_EXE_COND,
        ),
    )


def _operand_patch_field_bindings(
    patch: InstOperandPatch,
) -> tuple[InstFieldOwnerBinding, ...]:
    zero_owner = "operand_field_usage:fmax_update_v1"
    return (
        InstFieldOwnerBinding(
            field_path="src_operands_idx[0]",
            owner_kind="operand_patch",
            owner_id=patch.patch_id,
            binding_status="bound",
            decoded_value=patch.src_operands_idx[0],
        ),
        InstFieldOwnerBinding(
            field_path="src_operands_idx[1]",
            owner_kind="operand_patch",
            owner_id=patch.patch_id,
            binding_status="bound",
            decoded_value=patch.src_operands_idx[1],
        ),
        InstFieldOwnerBinding(
            field_path="src_operands_idx[2]",
            owner_kind="zero_with_evidence",
            owner_id=zero_owner,
            binding_status="zero_with_evidence",
            decoded_value=0,
        ),
        InstFieldOwnerBinding(
            field_path="dst_operands_idx[0]",
            owner_kind="operand_patch",
            owner_id=patch.patch_id,
            binding_status="bound",
            decoded_value=patch.dst_operands_idx[0],
        ),
        InstFieldOwnerBinding(
            field_path="dst_operands_idx[1]",
            owner_kind="zero_with_evidence",
            owner_id=zero_owner,
            binding_status="zero_with_evidence",
            decoded_value=0,
        ),
        InstFieldOwnerBinding(
            field_path="dst_operands_idx[2]",
            owner_kind="zero_with_evidence",
            owner_id=zero_owner,
            binding_status="zero_with_evidence",
            decoded_value=0,
        ),
    )


def _blocked_operand_field_bindings() -> tuple[InstFieldOwnerBinding, ...]:
    blocker = "log10max_ring_update_inst_operand_patch_missing"
    return tuple(
        InstFieldOwnerBinding(
            field_path=field_path,
            owner_kind="operand_patch",
            owner_id="missing:inst_operand_patch",
            binding_status="blocked",
            decoded_value=None,
            blockers=(blocker,),
        )
        for field_path in (
            "src_operands_idx[0]",
            "src_operands_idx[1]",
            "src_operands_idx[2]",
            "dst_operands_idx[0]",
            "dst_operands_idx[1]",
            "dst_operands_idx[2]",
        )
    )


def _pending_layout_field_bindings() -> tuple[InstFieldOwnerBinding, ...]:
    return (
        InstFieldOwnerBinding(
            field_path="block_idx",
            owner_kind="instruction_layout",
            owner_id="pending:instruction_layout_plan",
            binding_status="pending",
            decoded_value=None,
            blockers=(LOG10MAX_FMAX_FIELD_BINDING_LAYOUT_BLOCKER,),
        ),
        InstFieldOwnerBinding(
            field_path="stages_start_pc",
            owner_kind="exe_block_writer_plan",
            owner_id="pending:exe_block_writer_plan",
            binding_status="pending",
            decoded_value=None,
            blockers=(LOG10MAX_FMAX_FIELD_BINDING_EXEBLOCK_BLOCKER,),
        ),
        InstFieldOwnerBinding(
            field_path="end_inst",
            owner_kind="boundary_policy",
            owner_id="pending:instruction_boundary_plan",
            binding_status="pending",
            decoded_value=None,
            blockers=(LOG10MAX_FMAX_FIELD_BINDING_BOUNDARY_BLOCKER,),
        ),
        InstFieldOwnerBinding(
            field_path="component_byte_offset",
            owner_kind="component_placement",
            owner_id="pending:component_placement_plan",
            binding_status="pending",
            decoded_value=None,
            blockers=(LOG10MAX_FMAX_FIELD_BINDING_COMPONENT_BLOCKER,),
        ),
    )


__all__ = [
    "InstFieldBindingRecord",
    "InstFieldBindingReport",
    "InstFieldOwnerBinding",
    "LOG10MAX_FMAX_FIELD_BINDING_BOUNDARY_BLOCKER",
    "LOG10MAX_FMAX_FIELD_BINDING_COMPONENT_BLOCKER",
    "LOG10MAX_FMAX_FIELD_BINDING_EXEBLOCK_BLOCKER",
    "LOG10MAX_FMAX_FIELD_BINDING_LAYOUT_BLOCKER",
    "LOG10MAX_FMAX_FIELD_BINDING_PENDING_BLOCKERS",
    "build_log10max_ring_update_inst_field_binding_report",
    "summarize_inst_field_binding_report",
]
