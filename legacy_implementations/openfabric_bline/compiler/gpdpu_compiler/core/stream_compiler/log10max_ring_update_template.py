"""Template contract for log10max ring receiver-side max updates.

This module deliberately stops before row bytes.  It proves that every
``max_update_global_max`` edge has a source-backed FMAX/HMAX instruction shape,
then binds those candidates to explicit edge/FiberOp/operand records while
keeping row bytes fail-closed.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from gpdpu_compiler.core.program_legacy_inst import (
    INST_RECORD_SIZE_BYTES,
    LegacyInst,
    decode_legacy_inst_skeleton,
    pack_legacy_inst,
)
from gpdpu_compiler.core.program_bin import MAX_INST_AMOUNT_PER_PE

from .log10max_ring_plan import (
    Log10MaxRingPlanReport,
    RingEdgeRecord,
    build_log10max_task_local_ring_plan,
)
from .log10max_ring_fiber_projection import (
    Log10MaxRingFiberProjectionReport,
    RingFiberProjectionRecord,
    build_log10max_ring_fiber_projection_report,
)


UpdateTemplateStatus = Literal[
    "candidate_available_row_bytes_missing",
    "blocked_missing_opcode_capability",
]

RING_UPDATE_FMAX_OPCODE = 0x27
RING_UPDATE_FMAX_UNIT_INST_TYPE = 0x2
RING_UPDATE_FMAX_LATENCY = 72
RING_UPDATE_FMAX_ITER_EXE_COND = 1
RING_UPDATE_SRC_CURRENT_OPERAND_IDX = 0
RING_UPDATE_SRC_RECEIVED_OPERAND_IDX = 128
RING_UPDATE_DST_UPDATED_OPERAND_IDX = 256
RING_UPDATE_FORWARDING_BITS = (0, 1, 0)
RING_UPDATE_BYPASS_BITS = (0, 0, 0)
RING_UPDATE_MESH_X = 4
RING_UPDATE_FMAX_OPERAND_FIELD_USAGE = (
    ("src0", "used"),
    ("src1", "used"),
    ("src2", "unused_zero_fill"),
    ("dst0", "used"),
    ("dst1", "unused_zero_fill"),
    ("dst2", "unused_zero_fill"),
)


@dataclass(frozen=True)
class RingUpdateTemplateRecord:
    """One receiver-side FMAX/HMAX update template candidate."""

    edge_id: str
    update_action_id: str
    update_op: Literal["FMAX", "HMAX"]
    dtype: str
    source_a: str
    source_b: str
    destination: str
    opcode_evidence_refs: tuple[str, ...]
    status: UpdateTemplateStatus
    blocker_id: str

    @property
    def opcode_capability_available(self) -> bool:
        return self.status == "candidate_available_row_bytes_missing"

    def to_plan(self) -> dict[str, object]:
        return {
            "edge_id": self.edge_id,
            "update_action_id": self.update_action_id,
            "update_op": self.update_op,
            "dtype": self.dtype,
            "source_a": self.source_a,
            "source_b": self.source_b,
            "destination": self.destination,
            "opcode_evidence_refs": list(self.opcode_evidence_refs),
            "status": self.status,
            "opcode_capability_available": self.opcode_capability_available,
            "blocker_id": self.blocker_id,
            "row_bytes_claim": False,
            "template_proven_for_runtime_ready": False,
        }


@dataclass(frozen=True)
class RingUpdateTemplateReport:
    """Fail-closed ring update template report."""

    profile_id: str
    records: tuple[RingUpdateTemplateRecord, ...]

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.records:
            blockers.append("log10max_ring_update_template_missing")
        for record in self.records:
            blockers.append(record.blocker_id)
        return tuple(dict.fromkeys(blockers))

    @property
    def template_ready_for_runtime_ready(self) -> bool:
        return not self.blocker_ids

    def summary(self) -> dict[str, object]:
        status_counts: dict[str, int] = {}
        opcode_counts: dict[str, int] = {}
        for record in self.records:
            status_counts[record.status] = status_counts.get(record.status, 0) + 1
            opcode_counts[record.update_op] = opcode_counts.get(record.update_op, 0) + 1
        return {
            "profile_id": self.profile_id,
            "record_count": len(self.records),
            "status_counts": dict(sorted(status_counts.items())),
            "opcode_counts": dict(sorted(opcode_counts.items())),
            "blocker_ids": list(self.blocker_ids),
            "template_ready_for_runtime_ready": self.template_ready_for_runtime_ready,
            "row_bytes_claim": False,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_ring_update_template_report",
            "summary": self.summary(),
            "records": [record.to_plan() for record in self.records],
            "layering_policy": (
                "ring update template report consumes ring FiberOp metadata and "
                "DFU3500 opcode evidence; it does not emit vendor rows or binary bytes"
            ),
        }


def build_log10max_ring_update_template_report(
    ring_report: Log10MaxRingPlanReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_ring_update_template_v1",
) -> RingUpdateTemplateReport:
    """Build source-backed update template candidates for all ring edges."""

    report = ring_report or build_log10max_task_local_ring_plan()
    return RingUpdateTemplateReport(
        profile_id=profile_id,
        records=tuple(_record_for_edge(edge) for edge in report.edges),
    )


def summarize_log10max_ring_update_template_report(
    report: RingUpdateTemplateReport,
) -> dict[str, object]:
    return report.summary()


def _record_for_edge(edge: RingEdgeRecord) -> RingUpdateTemplateRecord:
    return RingUpdateTemplateRecord(
        edge_id=edge.edge_id,
        update_action_id=edge.update_action_id,
        update_op=edge.update_op,
        dtype=edge.dtype,
        source_a="receiver_current_global_max_or_local_max_scalar",
        source_b="route_recv_global_max_scalar",
        destination="receiver_owned_global_max_scalar_operand",
        opcode_evidence_refs=_opcode_evidence_refs(edge.update_op),
        status="candidate_available_row_bytes_missing",
        blocker_id="log10max_ring_update_row_bytes_missing",
    )


@dataclass(frozen=True)
class RingUpdateTemplateBinding:
    """Phase-1 binding from one ring update edge to a template candidate."""

    schema_version: str
    binding_id: str
    edge_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    ordering_group: str
    task_id: int
    src_pe: str
    dst_pe: str
    source_fiber_op_id: str
    source_stream_action_id: str
    recv_stream_action_id: str
    update_stream_action_id: str
    paired_push_stream_action_id: str
    route_recv_dependency_id: str
    update_op: Literal["FMAX", "HMAX"]
    dtype: Literal["fp32", "fp16", "bf16"]
    globalmax_representation: Literal["replicated_vector", "scalar_lane"]
    lane_convention: str
    src_current_operand: str
    src_received_operand: str
    dst_updated_operand: str
    inplace_update_policy: Literal["allowed", "forbidden", "unknown"]
    subtask_slot: str | None
    exe_block_slot: str | None
    row_placement_status: Literal["unplaced", "placed"]
    template_family: Literal["dfu3500_log10max_ring_globalmax_update"]
    template_status: Literal[
        "candidate_available",
        "row_bytes_emitted",
        "blocked",
    ]
    blocker_ids: tuple[str, ...]

    @property
    def row_bytes_claim(self) -> bool:
        return self.template_status == "row_bytes_emitted"

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "binding_id": self.binding_id,
            "edge_id": self.edge_id,
            "phase": self.phase,
            "ordering_group": self.ordering_group,
            "task_id": self.task_id,
            "src_pe": self.src_pe,
            "dst_pe": self.dst_pe,
            "source_fiber_op_id": self.source_fiber_op_id,
            "source_stream_action_id": self.source_stream_action_id,
            "recv_stream_action_id": self.recv_stream_action_id,
            "update_stream_action_id": self.update_stream_action_id,
            "paired_push_stream_action_id": self.paired_push_stream_action_id,
            "route_recv_dependency_id": self.route_recv_dependency_id,
            "update_op": self.update_op,
            "dtype": self.dtype,
            "globalmax_representation": self.globalmax_representation,
            "lane_convention": self.lane_convention,
            "src_current_operand": self.src_current_operand,
            "src_received_operand": self.src_received_operand,
            "dst_updated_operand": self.dst_updated_operand,
            "inplace_update_policy": self.inplace_update_policy,
            "subtask_slot": self.subtask_slot,
            "exe_block_slot": self.exe_block_slot,
            "row_placement_status": self.row_placement_status,
            "template_family": self.template_family,
            "template_status": self.template_status,
            "blocker_ids": list(self.blocker_ids),
            "row_bytes_claim": self.row_bytes_claim,
        }


@dataclass(frozen=True)
class RingUpdateTemplateBindingReport:
    """Phase-1 binding report; row bytes stay fail-closed."""

    profile_id: str
    bindings: tuple[RingUpdateTemplateBinding, ...]

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.bindings:
            blockers.append("log10max_ring_update_template_missing")
        for binding in self.bindings:
            blockers.extend(binding.blocker_ids)
        return tuple(dict.fromkeys(blockers))

    @property
    def runtime_ready(self) -> bool:
        return bool(self.bindings) and not self.blocker_ids

    def summary(self) -> dict[str, object]:
        phase_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        opcode_counts: dict[str, int] = {}
        for binding in self.bindings:
            phase_counts[binding.phase] = phase_counts.get(binding.phase, 0) + 1
            status_counts[binding.template_status] = (
                status_counts.get(binding.template_status, 0) + 1
            )
            opcode_counts[binding.update_op] = opcode_counts.get(binding.update_op, 0) + 1
        return {
            "profile_id": self.profile_id,
            "binding_count": len(self.bindings),
            "phase_counts": dict(sorted(phase_counts.items())),
            "template_status_counts": dict(sorted(status_counts.items())),
            "opcode_counts": dict(sorted(opcode_counts.items())),
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "row_bytes_claim": any(binding.row_bytes_claim for binding in self.bindings),
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_ring_update_template_binding_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "blocker_ids": list(self.blocker_ids),
            "bindings": [binding.to_plan() for binding in self.bindings],
            "layering_policy": (
                "binding report consumes ring edge/projection metadata and FMAX "
                "opcode evidence; it does not emit vendor rows or binary bytes"
            ),
        }


def build_log10max_ring_update_template_binding_report(
    ring_report: Log10MaxRingPlanReport | None = None,
    projection_report: Log10MaxRingFiberProjectionReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_ring_update_template_binding_v1",
) -> RingUpdateTemplateBindingReport:
    """Bind ring update edges to the V1 FMAX template candidate."""

    ring = ring_report or build_log10max_task_local_ring_plan()
    projection = projection_report or build_log10max_ring_fiber_projection_report(ring)
    projection_by_edge = {record.edge_id: record for record in projection.records}
    bindings = tuple(
        _binding_for_edge(edge, projection_by_edge.get(edge.edge_id))
        for edge in ring.edges
    )
    return RingUpdateTemplateBindingReport(
        profile_id=profile_id,
        bindings=bindings,
    )


def summarize_log10max_ring_update_template_binding_report(
    report: RingUpdateTemplateBindingReport,
) -> dict[str, object]:
    return report.summary()


@dataclass(frozen=True)
class RingUpdateTemplateOpCandidate:
    """Phase-2 TemplateOp candidate for one ring update binding."""

    schema_version: str
    template_op_id: str
    template_expansion_id: str
    source_binding_id: str
    source_ring_edge_id: str
    source_fiber_op_id: str
    source_stream_action_id: str
    recv_stream_action_id: str
    paired_push_stream_action_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    ordering_group: str
    task_id: int
    src_pe: str
    dst_pe: str
    role: Literal["collective:global_max"]
    source_fiber_op_kind: Literal["global_max_tile"]
    semantic_op: Literal["max_update_global_max"]
    route_role: Literal["GlobalMax"]
    fiber_op_atomicity: Literal["fiber_atomic_tile_job"]
    template_family: Literal["dfu3500_log10max_ring_globalmax_update"]
    template_status: Literal["layout_candidate"]
    instruction_intent_opcode: Literal["FMAX", "HMAX"]
    operand_policy: Literal["globalmax_acc_in_recv_acc_out_non_inplace"]
    globalmax_representation: Literal["replicated_vector", "scalar_lane"]
    row_byte_status: Literal["row_bytes_missing"]
    blocker_ids: tuple[str, ...]

    @property
    def row_bytes_claim(self) -> bool:
        return False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "template_op_id": self.template_op_id,
            "template_expansion_id": self.template_expansion_id,
            "source_binding_id": self.source_binding_id,
            "source_ring_edge_id": self.source_ring_edge_id,
            "source_fiber_op_id": self.source_fiber_op_id,
            "source_stream_action_id": self.source_stream_action_id,
            "recv_stream_action_id": self.recv_stream_action_id,
            "paired_push_stream_action_id": self.paired_push_stream_action_id,
            "phase": self.phase,
            "ordering_group": self.ordering_group,
            "task_id": self.task_id,
            "src_pe": self.src_pe,
            "dst_pe": self.dst_pe,
            "role": self.role,
            "source_fiber_op_kind": self.source_fiber_op_kind,
            "semantic_op": self.semantic_op,
            "route_role": self.route_role,
            "fiber_op_atomicity": self.fiber_op_atomicity,
            "template_family": self.template_family,
            "template_status": self.template_status,
            "instruction_intent_opcode": self.instruction_intent_opcode,
            "operand_policy": self.operand_policy,
            "globalmax_representation": self.globalmax_representation,
            "row_byte_status": self.row_byte_status,
            "blocker_ids": list(self.blocker_ids),
            "row_bytes_claim": self.row_bytes_claim,
        }


@dataclass(frozen=True)
class RingUpdateBinaryLayoutRowCandidate:
    """Phase-3 BinaryLayout row candidate; still no inst_t bytes."""

    schema_version: str
    row_candidate_id: str
    row_index: int
    pc: int
    template_op_id: str
    template_expansion_id: str
    source_binding_id: str
    source_ring_edge_id: str
    source_fiber_op_id: str
    source_stream_action_id: str
    recv_stream_action_id: str
    paired_push_stream_action_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    ordering_group: str
    task_id: int
    src_pe: str
    dst_pe: str
    role: Literal["collective:global_max"]
    source_fiber_op_kind: Literal["global_max_tile"]
    semantic_op: Literal["max_update_global_max"]
    route_role: Literal["GlobalMax"]
    fiber_op_atomicity: Literal["fiber_atomic_tile_job"]
    opcode: Literal["FMAX", "HMAX"]
    subtask_slot: Literal["log10max_ring_globalmax_update"]
    src_current_operand: str
    src_received_operand: str
    dst_updated_operand: str
    template_family: Literal["dfu3500_log10max_ring_globalmax_update"]
    layout_status: Literal["layout_candidate"]
    row_byte_status: Literal["row_bytes_missing"]
    blocker_ids: tuple[str, ...]

    @property
    def row_bytes_claim(self) -> bool:
        return False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "row_candidate_id": self.row_candidate_id,
            "row_index": self.row_index,
            "pc": self.pc,
            "template_op_id": self.template_op_id,
            "template_expansion_id": self.template_expansion_id,
            "source_binding_id": self.source_binding_id,
            "source_ring_edge_id": self.source_ring_edge_id,
            "source_fiber_op_id": self.source_fiber_op_id,
            "source_stream_action_id": self.source_stream_action_id,
            "recv_stream_action_id": self.recv_stream_action_id,
            "paired_push_stream_action_id": self.paired_push_stream_action_id,
            "phase": self.phase,
            "ordering_group": self.ordering_group,
            "task_id": self.task_id,
            "src_pe": self.src_pe,
            "dst_pe": self.dst_pe,
            "role": self.role,
            "source_fiber_op_kind": self.source_fiber_op_kind,
            "semantic_op": self.semantic_op,
            "route_role": self.route_role,
            "fiber_op_atomicity": self.fiber_op_atomicity,
            "opcode": self.opcode,
            "subtask_slot": self.subtask_slot,
            "src_current_operand": self.src_current_operand,
            "src_received_operand": self.src_received_operand,
            "dst_updated_operand": self.dst_updated_operand,
            "template_family": self.template_family,
            "layout_status": self.layout_status,
            "row_byte_status": self.row_byte_status,
            "blocker_ids": list(self.blocker_ids),
            "row_bytes_claim": self.row_bytes_claim,
            "inst_t_row_count": 0,
            "vendor_row_count": 0,
            "raw_inst_t_byte_count": 0,
            "inst_t_bytes_emitted": False,
            "decode_roundtrip_claim": False,
            "created_directly_from_ring_edge": False,
        }


@dataclass(frozen=True)
class RingUpdateBinaryLayoutCandidateReport:
    """Phase-3 report linking ring update TemplateOps to row candidates."""

    profile_id: str
    source_binding_report_id: str
    template_ops: tuple[RingUpdateTemplateOpCandidate, ...]
    row_candidates: tuple[RingUpdateBinaryLayoutRowCandidate, ...]

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.template_ops or not self.row_candidates:
            blockers.append("log10max_ring_update_row_bytes_missing")
        for op in self.template_ops:
            blockers.extend(op.blocker_ids)
        for row in self.row_candidates:
            blockers.extend(row.blocker_ids)
        return tuple(dict.fromkeys(blockers))

    @property
    def runtime_ready(self) -> bool:
        return False

    def summary(self) -> dict[str, object]:
        phase_counts: dict[str, int] = {}
        opcode_counts: dict[str, int] = {}
        subtask_counts: dict[str, int] = {}
        template_status_counts: dict[str, int] = {}
        layout_status_counts: dict[str, int] = {}
        row_byte_status_counts: dict[str, int] = {}
        for op in self.template_ops:
            template_status_counts[op.template_status] = (
                template_status_counts.get(op.template_status, 0) + 1
            )
            row_byte_status_counts[op.row_byte_status] = (
                row_byte_status_counts.get(op.row_byte_status, 0) + 1
            )
        for row in self.row_candidates:
            phase_counts[row.phase] = phase_counts.get(row.phase, 0) + 1
            opcode_counts[row.opcode] = opcode_counts.get(row.opcode, 0) + 1
            subtask_counts[row.subtask_slot] = subtask_counts.get(row.subtask_slot, 0) + 1
            layout_status_counts[row.layout_status] = (
                layout_status_counts.get(row.layout_status, 0) + 1
            )
            row_byte_status_counts[row.row_byte_status] = (
                row_byte_status_counts.get(row.row_byte_status, 0) + 1
            )
        return {
            "profile_id": self.profile_id,
            "source_binding_report_id": self.source_binding_report_id,
            "template_op_count": len(self.template_ops),
            "row_candidate_count": len(self.row_candidates),
            "phase_counts": dict(sorted(phase_counts.items())),
            "opcode_counts": dict(sorted(opcode_counts.items())),
            "subtask_counts": dict(sorted(subtask_counts.items())),
            "template_status_counts": dict(sorted(template_status_counts.items())),
            "layout_status_counts": dict(sorted(layout_status_counts.items())),
            "row_byte_status_counts": dict(sorted(row_byte_status_counts.items())),
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "row_bytes_claim": any(row.row_bytes_claim for row in self.row_candidates),
            "concrete_template_claim": False,
            "inst_t_row_count": 0,
            "vendor_row_count": 0,
            "raw_inst_t_byte_count": 0,
            "inst_t_bytes_emitted": False,
            "decode_roundtrip_claim": False,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_ring_update_binary_layout_candidate_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "blocker_ids": list(self.blocker_ids),
            "template_ops": [op.to_plan() for op in self.template_ops],
            "binary_layout_row_candidates": [
                row.to_plan() for row in self.row_candidates
            ],
            "source_artifact_kind": "log10max_ring_update_template_binding_report",
            "layering_policy": (
                "row candidates are derived from RingUpdateTemplateBindingReport "
                "and TemplateOp candidates; no inst_t rows, bytes, pack, or decode "
                "are emitted in this phase"
            ),
        }


@dataclass(frozen=True)
class RingUpdateFmaxInstCandidate:
    """Phase-4 candidate inst_t row bytes for one ring update FMAX row.

    These bytes prove the local FMAX row shape can pack/decode.  They are not
    yet inserted into the final CBUF insts component or exeBlock CAL stage.
    """

    schema_version: str
    inst_candidate_id: str
    row_candidate_id: str
    row_index: int
    pc: int
    template_op_id: str
    template_expansion_id: str
    source_binding_id: str
    source_ring_edge_id: str
    source_fiber_op_id: str
    source_stream_action_id: str
    recv_stream_action_id: str
    paired_push_stream_action_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    ordering_group: str
    task_id: int
    src_pe: str
    dst_pe: str
    opcode: Literal["FMAX"]
    opcode_value: int
    unit_inst_type: int
    latency: int
    operand_field_usage: tuple[tuple[str, str], ...]
    src_operands_idx: tuple[int, int, int]
    dst_operands_idx: tuple[int, int, int]
    forwarding_bits: tuple[int, int, int]
    bypass_bits: tuple[int, int, int]
    iter_exe_cond: int
    block_idx: int
    end_inst: int
    raw_inst_t_byte_count: int
    raw_inst_t_sha256: str
    operand_allocation_status: Literal["skeleton_operands_unallocated"]
    decode_roundtrip_status: Literal["candidate_pack_decode_roundtrip"]
    component_integration_status: Literal["not_integrated"]
    blocker_ids: tuple[str, ...]

    @property
    def row_bytes_claim(self) -> bool:
        return True

    @property
    def final_row_bytes_claim(self) -> bool:
        return False

    @property
    def runtime_ready(self) -> bool:
        return False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "inst_candidate_id": self.inst_candidate_id,
            "row_candidate_id": self.row_candidate_id,
            "row_index": self.row_index,
            "pc": self.pc,
            "template_op_id": self.template_op_id,
            "template_expansion_id": self.template_expansion_id,
            "source_binding_id": self.source_binding_id,
            "source_ring_edge_id": self.source_ring_edge_id,
            "source_fiber_op_id": self.source_fiber_op_id,
            "source_stream_action_id": self.source_stream_action_id,
            "recv_stream_action_id": self.recv_stream_action_id,
            "paired_push_stream_action_id": self.paired_push_stream_action_id,
            "phase": self.phase,
            "ordering_group": self.ordering_group,
            "task_id": self.task_id,
            "src_pe": self.src_pe,
            "dst_pe": self.dst_pe,
            "opcode": self.opcode,
            "opcode_value": self.opcode_value,
            "unit_inst_type": self.unit_inst_type,
            "latency": self.latency,
            "operand_field_usage": dict(self.operand_field_usage),
            "src_operands_idx": list(self.src_operands_idx),
            "dst_operands_idx": list(self.dst_operands_idx),
            "forwarding_bits": list(self.forwarding_bits),
            "bypass_bits": list(self.bypass_bits),
            "iter_exe_cond": self.iter_exe_cond,
            "block_idx": self.block_idx,
            "end_inst": self.end_inst,
            "raw_inst_t_byte_count": self.raw_inst_t_byte_count,
            "raw_inst_t_sha256": self.raw_inst_t_sha256,
            "operand_allocation_status": self.operand_allocation_status,
            "decode_roundtrip_status": self.decode_roundtrip_status,
            "component_integration_status": self.component_integration_status,
            "blocker_ids": list(self.blocker_ids),
            "row_bytes_claim": self.row_bytes_claim,
            "final_row_bytes_claim": self.final_row_bytes_claim,
            "runtime_ready": self.runtime_ready,
        }


@dataclass(frozen=True)
class RingUpdateFmaxInstCandidateReport:
    """Phase-4 pack/decode candidate report; component integration is blocked."""

    profile_id: str
    source_layout_report_id: str
    inst_candidates: tuple[RingUpdateFmaxInstCandidate, ...]

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.inst_candidates:
            blockers.append("log10max_ring_update_row_bytes_missing")
        for candidate in self.inst_candidates:
            blockers.extend(candidate.blocker_ids)
        return tuple(dict.fromkeys(blockers))

    @property
    def runtime_ready(self) -> bool:
        return False

    def summary(self) -> dict[str, object]:
        phase_counts: dict[str, int] = {}
        opcode_counts: dict[str, int] = {}
        allocation_status_counts: dict[str, int] = {}
        decode_status_counts: dict[str, int] = {}
        integration_status_counts: dict[str, int] = {}
        byte_count = 0
        for candidate in self.inst_candidates:
            phase_counts[candidate.phase] = phase_counts.get(candidate.phase, 0) + 1
            opcode_counts[candidate.opcode] = opcode_counts.get(candidate.opcode, 0) + 1
            allocation_status_counts[candidate.operand_allocation_status] = (
                allocation_status_counts.get(candidate.operand_allocation_status, 0)
                + 1
            )
            decode_status_counts[candidate.decode_roundtrip_status] = (
                decode_status_counts.get(candidate.decode_roundtrip_status, 0) + 1
            )
            integration_status_counts[candidate.component_integration_status] = (
                integration_status_counts.get(candidate.component_integration_status, 0) + 1
            )
            byte_count += candidate.raw_inst_t_byte_count
        return {
            "profile_id": self.profile_id,
            "source_layout_report_id": self.source_layout_report_id,
            "inst_candidate_count": len(self.inst_candidates),
            "phase_counts": dict(sorted(phase_counts.items())),
            "opcode_counts": dict(sorted(opcode_counts.items())),
            "operand_allocation_status_counts": dict(
                sorted(allocation_status_counts.items())
            ),
            "decode_status_counts": dict(sorted(decode_status_counts.items())),
            "component_integration_status_counts": dict(
                sorted(integration_status_counts.items())
            ),
            "blocker_ids": list(self.blocker_ids),
            "raw_inst_t_byte_count": byte_count,
            "row_bytes_claim": bool(self.inst_candidates),
            "final_row_bytes_claim": False,
            "decode_roundtrip_claim": bool(self.inst_candidates),
            "component_integration_claim": False,
            "runtime_ready": self.runtime_ready,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_ring_update_fmax_inst_candidate_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "blocker_ids": list(self.blocker_ids),
            "inst_candidates": [
                candidate.to_plan() for candidate in self.inst_candidates
            ],
            "source_artifact_kind": "log10max_ring_update_binary_layout_candidate_report",
            "layering_policy": (
                "inst candidates are pack/decode proofs for the FMAX row shape; "
                "their operand indices are skeleton placeholders until an "
                "InstOperandPatch exists; they are not final CBUF component rows "
                "and do not clear runtime_ready"
            ),
        }


@dataclass(frozen=True)
class RingUpdateComponentPlacementCandidate:
    """Phase-5 candidate placement in the insts component address space."""

    schema_version: str
    placement_candidate_id: str
    inst_candidate_id: str
    row_candidate_id: str
    source_ring_edge_id: str
    source_fiber_op_id: str
    template_expansion_id: str
    task_id: int
    dst_pe: str
    pe_index: int
    local_pc: int
    global_row_index: int
    component_name: Literal["insts_file.bin"]
    component_byte_offset: int
    record_size_bytes: int
    subtask_slot: Literal["log10max_ring_globalmax_update"]
    stage: Literal["CAL"]
    opcode: Literal["FMAX"]
    component_placement_status: Literal["candidate_offset_bound"]
    exe_block_integration_status: Literal["not_integrated"]
    cbuf_section_integration_status: Literal["not_integrated"]
    operand_allocation_status: Literal["skeleton_operands_unallocated"]
    blocker_ids: tuple[str, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "placement_candidate_id": self.placement_candidate_id,
            "inst_candidate_id": self.inst_candidate_id,
            "row_candidate_id": self.row_candidate_id,
            "source_ring_edge_id": self.source_ring_edge_id,
            "source_fiber_op_id": self.source_fiber_op_id,
            "template_expansion_id": self.template_expansion_id,
            "task_id": self.task_id,
            "dst_pe": self.dst_pe,
            "pe_index": self.pe_index,
            "local_pc": self.local_pc,
            "global_row_index": self.global_row_index,
            "component_name": self.component_name,
            "component_byte_offset": self.component_byte_offset,
            "record_size_bytes": self.record_size_bytes,
            "subtask_slot": self.subtask_slot,
            "stage": self.stage,
            "opcode": self.opcode,
            "component_placement_status": self.component_placement_status,
            "exe_block_integration_status": self.exe_block_integration_status,
            "cbuf_section_integration_status": self.cbuf_section_integration_status,
            "operand_allocation_status": self.operand_allocation_status,
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
        }


@dataclass(frozen=True)
class RingUpdateComponentPlacementCandidateReport:
    """Candidate component placement; no exeBlock/CBUF mutation yet."""

    profile_id: str
    source_inst_candidate_report_id: str
    placements: tuple[RingUpdateComponentPlacementCandidate, ...]

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.placements:
            blockers.append("log10max_ring_update_component_integration_missing")
        for placement in self.placements:
            blockers.extend(placement.blocker_ids)
        return tuple(dict.fromkeys(blockers))

    @property
    def runtime_ready(self) -> bool:
        return False

    def summary(self) -> dict[str, object]:
        phase_counts: dict[str, int] = {}
        pe_counts: dict[str, int] = {}
        placement_status_counts: dict[str, int] = {}
        exe_block_status_counts: dict[str, int] = {}
        cbuf_status_counts: dict[str, int] = {}
        allocation_status_counts: dict[str, int] = {}
        offsets: set[int] = set()
        duplicate_offset_count = 0
        for placement in self.placements:
            pe_counts[placement.dst_pe] = pe_counts.get(placement.dst_pe, 0) + 1
            placement_status_counts[placement.component_placement_status] = (
                placement_status_counts.get(placement.component_placement_status, 0) + 1
            )
            exe_block_status_counts[placement.exe_block_integration_status] = (
                exe_block_status_counts.get(placement.exe_block_integration_status, 0) + 1
            )
            cbuf_status_counts[placement.cbuf_section_integration_status] = (
                cbuf_status_counts.get(placement.cbuf_section_integration_status, 0) + 1
            )
            allocation_status_counts[placement.operand_allocation_status] = (
                allocation_status_counts.get(placement.operand_allocation_status, 0)
                + 1
            )
            if placement.component_byte_offset in offsets:
                duplicate_offset_count += 1
            offsets.add(placement.component_byte_offset)
            phase = placement.source_ring_edge_id.split(":", 3)[2]
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
        return {
            "profile_id": self.profile_id,
            "source_inst_candidate_report_id": self.source_inst_candidate_report_id,
            "placement_count": len(self.placements),
            "phase_counts": dict(sorted(phase_counts.items())),
            "pe_counts": dict(sorted(pe_counts.items())),
            "component_placement_status_counts": dict(
                sorted(placement_status_counts.items())
            ),
            "exe_block_integration_status_counts": dict(
                sorted(exe_block_status_counts.items())
            ),
            "cbuf_section_integration_status_counts": dict(
                sorted(cbuf_status_counts.items())
            ),
            "operand_allocation_status_counts": dict(
                sorted(allocation_status_counts.items())
            ),
            "duplicate_component_byte_offset_count": duplicate_offset_count,
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_ring_update_component_placement_candidate_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "blocker_ids": list(self.blocker_ids),
            "placements": [placement.to_plan() for placement in self.placements],
            "source_artifact_kind": "log10max_ring_update_fmax_inst_candidate_report",
            "layering_policy": (
                "component placement candidates bind PE-major insts_file offsets "
                "for FMAX update rows; operand allocation, exeBlock/CAL, and CBUF "
                "package mutation remain blocked"
            ),
        }


def build_log10max_ring_update_binary_layout_candidate_report(
    binding_report: RingUpdateTemplateBindingReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_ring_update_binary_layout_candidate_v1",
) -> RingUpdateBinaryLayoutCandidateReport:
    """Create TemplateOp and BinaryLayout row candidates for ring FMAX updates."""

    bindings = binding_report or build_log10max_ring_update_template_binding_report()
    template_ops = tuple(_template_op_candidate_for_binding(binding) for binding in bindings.bindings)
    rows = tuple(
        _row_candidate_for_template_op(binding, template_op, row_index)
        for row_index, (binding, template_op) in enumerate(zip(bindings.bindings, template_ops))
    )
    return RingUpdateBinaryLayoutCandidateReport(
        profile_id=profile_id,
        source_binding_report_id=bindings.profile_id,
        template_ops=template_ops,
        row_candidates=rows,
    )


def summarize_log10max_ring_update_binary_layout_candidate_report(
    report: RingUpdateBinaryLayoutCandidateReport,
) -> dict[str, object]:
    return report.summary()


def build_log10max_ring_update_fmax_inst_candidate_report(
    layout_report: RingUpdateBinaryLayoutCandidateReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_ring_update_fmax_inst_candidate_v1",
) -> RingUpdateFmaxInstCandidateReport:
    """Pack/decode candidate FMAX inst_t rows without component integration."""

    layout = layout_report or build_log10max_ring_update_binary_layout_candidate_report()
    candidates = tuple(
        _fmax_inst_candidate_for_row(row)
        for row in layout.row_candidates
    )
    return RingUpdateFmaxInstCandidateReport(
        profile_id=profile_id,
        source_layout_report_id=layout.profile_id,
        inst_candidates=candidates,
    )


def summarize_log10max_ring_update_fmax_inst_candidate_report(
    report: RingUpdateFmaxInstCandidateReport,
) -> dict[str, object]:
    return report.summary()


def build_log10max_ring_update_component_placement_candidate_report(
    inst_report: RingUpdateFmaxInstCandidateReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_ring_update_component_placement_candidate_v1",
) -> RingUpdateComponentPlacementCandidateReport:
    """Bind candidate FMAX rows to PE-major insts_file offsets."""

    report = inst_report or build_log10max_ring_update_fmax_inst_candidate_report()
    local_pc_by_pe: dict[str, int] = {}
    placements: list[RingUpdateComponentPlacementCandidate] = []
    for candidate in report.inst_candidates:
        local_pc = local_pc_by_pe.get(candidate.dst_pe, 0)
        local_pc_by_pe[candidate.dst_pe] = local_pc + 1
        pe_index = _pe_index_from_label(candidate.dst_pe)
        global_row_index = pe_index * MAX_INST_AMOUNT_PER_PE + local_pc
        placements.append(
            RingUpdateComponentPlacementCandidate(
                schema_version="1",
                placement_candidate_id=(
                    f"component_placement_candidate:{candidate.inst_candidate_id}"
                ),
                inst_candidate_id=candidate.inst_candidate_id,
                row_candidate_id=candidate.row_candidate_id,
                source_ring_edge_id=candidate.source_ring_edge_id,
                source_fiber_op_id=candidate.source_fiber_op_id,
                template_expansion_id=candidate.template_expansion_id,
                task_id=candidate.task_id,
                dst_pe=candidate.dst_pe,
                pe_index=pe_index,
                local_pc=local_pc,
                global_row_index=global_row_index,
                component_name="insts_file.bin",
                component_byte_offset=global_row_index * INST_RECORD_SIZE_BYTES,
                record_size_bytes=INST_RECORD_SIZE_BYTES,
                subtask_slot="log10max_ring_globalmax_update",
                stage="CAL",
                opcode="FMAX",
                component_placement_status="candidate_offset_bound",
                exe_block_integration_status="not_integrated",
                cbuf_section_integration_status="not_integrated",
                operand_allocation_status="skeleton_operands_unallocated",
                blocker_ids=(
                    "log10max_ring_update_operand_allocation_missing",
                    "log10max_ring_update_exeblock_cal_stage_missing",
                ),
            )
        )
    return RingUpdateComponentPlacementCandidateReport(
        profile_id=profile_id,
        source_inst_candidate_report_id=report.profile_id,
        placements=tuple(placements),
    )


def summarize_log10max_ring_update_component_placement_candidate_report(
    report: RingUpdateComponentPlacementCandidateReport,
) -> dict[str, object]:
    return report.summary()


def _binding_for_edge(
    edge: RingEdgeRecord,
    projection: RingFiberProjectionRecord | None,
) -> RingUpdateTemplateBinding:
    if projection is None:
        source_fiber_op_id = ""
        route_recv_dependency_id = ""
        blockers = ("log10max_ring_update_template_missing",)
    else:
        source_fiber_op_id = projection.update_fiber_op_id
        route_recv_dependency_id = (
            f"{projection.update_fiber_op_id}:route_recv_global_max_dependency"
        )
        blockers = ("log10max_ring_update_row_bytes_missing",)
    return RingUpdateTemplateBinding(
        schema_version="1",
        binding_id=f"ring_update_template_binding:{edge.edge_id}",
        edge_id=edge.edge_id,
        phase=edge.phase,
        ordering_group=edge.ordering_group,
        task_id=edge.task_id,
        src_pe=edge.src_pe,
        dst_pe=edge.dst_pe,
        source_fiber_op_id=source_fiber_op_id,
        source_stream_action_id=edge.source_stream_action_id,
        recv_stream_action_id=edge.recv_stream_action_id,
        update_stream_action_id=edge.update_action_id,
        paired_push_stream_action_id=edge.source_stream_action_id,
        route_recv_dependency_id=route_recv_dependency_id,
        update_op=edge.update_op,
        dtype=_binding_dtype(edge.dtype),
        globalmax_representation="replicated_vector",
        lane_convention="replicated_fp32_vector_all_lanes_equal",
        src_current_operand="globalmax_acc_in",
        src_received_operand="globalmax_recv",
        dst_updated_operand="globalmax_acc_out",
        inplace_update_policy="forbidden",
        subtask_slot="log10max_ring_globalmax_update",
        exe_block_slot=None,
        row_placement_status="unplaced",
        template_family="dfu3500_log10max_ring_globalmax_update",
        template_status="candidate_available",
        blocker_ids=blockers,
    )


def _binding_dtype(dtype: str) -> Literal["fp32", "fp16", "bf16"]:
    if dtype in {"fp16", "bf16"}:
        return dtype
    return "fp32"


def _template_op_candidate_for_binding(
    binding: RingUpdateTemplateBinding,
) -> RingUpdateTemplateOpCandidate:
    template_op_id = f"template_op:log10max_ring_globalmax_update:{binding.edge_id}"
    template_expansion_id = (
        f"template_expansion:dfu3500_log10max_ring_globalmax_update:{binding.edge_id}"
    )
    return RingUpdateTemplateOpCandidate(
        schema_version="1",
        template_op_id=template_op_id,
        template_expansion_id=template_expansion_id,
        source_binding_id=binding.binding_id,
        source_ring_edge_id=binding.edge_id,
        source_fiber_op_id=binding.source_fiber_op_id,
        source_stream_action_id=binding.update_stream_action_id,
        recv_stream_action_id=binding.recv_stream_action_id,
        paired_push_stream_action_id=binding.paired_push_stream_action_id,
        phase=binding.phase,
        ordering_group=binding.ordering_group,
        task_id=binding.task_id,
        src_pe=binding.src_pe,
        dst_pe=binding.dst_pe,
        role="collective:global_max",
        source_fiber_op_kind="global_max_tile",
        semantic_op="max_update_global_max",
        route_role="GlobalMax",
        fiber_op_atomicity="fiber_atomic_tile_job",
        template_family=binding.template_family,
        template_status="layout_candidate",
        instruction_intent_opcode=binding.update_op,
        operand_policy="globalmax_acc_in_recv_acc_out_non_inplace",
        globalmax_representation=binding.globalmax_representation,
        row_byte_status="row_bytes_missing",
        blocker_ids=("log10max_ring_update_row_bytes_missing",),
    )


def _row_candidate_for_template_op(
    binding: RingUpdateTemplateBinding,
    template_op: RingUpdateTemplateOpCandidate,
    row_index: int,
) -> RingUpdateBinaryLayoutRowCandidate:
    return RingUpdateBinaryLayoutRowCandidate(
        schema_version="1",
        row_candidate_id=f"binary_layout_row_candidate:{template_op.template_op_id}",
        row_index=row_index,
        pc=row_index,
        template_op_id=template_op.template_op_id,
        template_expansion_id=template_op.template_expansion_id,
        source_binding_id=binding.binding_id,
        source_ring_edge_id=template_op.source_ring_edge_id,
        source_fiber_op_id=template_op.source_fiber_op_id,
        source_stream_action_id=template_op.source_stream_action_id,
        recv_stream_action_id=template_op.recv_stream_action_id,
        paired_push_stream_action_id=template_op.paired_push_stream_action_id,
        phase=template_op.phase,
        ordering_group=template_op.ordering_group,
        task_id=template_op.task_id,
        src_pe=template_op.src_pe,
        dst_pe=template_op.dst_pe,
        role=template_op.role,
        source_fiber_op_kind=template_op.source_fiber_op_kind,
        semantic_op=template_op.semantic_op,
        route_role=template_op.route_role,
        fiber_op_atomicity=template_op.fiber_op_atomicity,
        opcode=template_op.instruction_intent_opcode,
        subtask_slot="log10max_ring_globalmax_update",
        src_current_operand=binding.src_current_operand,
        src_received_operand=binding.src_received_operand,
        dst_updated_operand=binding.dst_updated_operand,
        template_family=template_op.template_family,
        layout_status="layout_candidate",
        row_byte_status="row_bytes_missing",
        blocker_ids=("log10max_ring_update_row_bytes_missing",),
    )


def _fmax_inst_candidate_for_row(
    row: RingUpdateBinaryLayoutRowCandidate,
) -> RingUpdateFmaxInstCandidate:
    if row.opcode != "FMAX":
        raise ValueError(f"Phase-4 V1 only supports FMAX rows: {row.opcode}")
    src_operands = (
        RING_UPDATE_SRC_CURRENT_OPERAND_IDX,
        RING_UPDATE_SRC_RECEIVED_OPERAND_IDX,
        0,
    )
    dst_operands = (RING_UPDATE_DST_UPDATED_OPERAND_IDX, 0, 0)
    inst = LegacyInst(
        op_name="FMAX",
        opcode=RING_UPDATE_FMAX_OPCODE,
        unit_inst_type=RING_UPDATE_FMAX_UNIT_INST_TYPE,
        latency=RING_UPDATE_FMAX_LATENCY,
        imms=(0, 0, 0),
        src_operands_idx=src_operands,
        dst_operands_idx=dst_operands,
        forwarding_bits=RING_UPDATE_FORWARDING_BITS,
        bypass_bits=RING_UPDATE_BYPASS_BITS,
        iter_exe_cond=RING_UPDATE_FMAX_ITER_EXE_COND,
        block_idx=row.row_index,
        end_inst=0,
    )
    raw_bytes = pack_legacy_inst(inst)
    decoded = decode_legacy_inst_skeleton(raw_bytes)
    _assert_fmax_decode_roundtrip(row=row, decoded=decoded)
    return RingUpdateFmaxInstCandidate(
        schema_version="1",
        inst_candidate_id=f"inst_candidate:{row.row_candidate_id}",
        row_candidate_id=row.row_candidate_id,
        row_index=row.row_index,
        pc=row.pc,
        template_op_id=row.template_op_id,
        template_expansion_id=row.template_expansion_id,
        source_binding_id=row.source_binding_id,
        source_ring_edge_id=row.source_ring_edge_id,
        source_fiber_op_id=row.source_fiber_op_id,
        source_stream_action_id=row.source_stream_action_id,
        recv_stream_action_id=row.recv_stream_action_id,
        paired_push_stream_action_id=row.paired_push_stream_action_id,
        phase=row.phase,
        ordering_group=row.ordering_group,
        task_id=row.task_id,
        src_pe=row.src_pe,
        dst_pe=row.dst_pe,
        opcode="FMAX",
        opcode_value=RING_UPDATE_FMAX_OPCODE,
        unit_inst_type=RING_UPDATE_FMAX_UNIT_INST_TYPE,
        latency=RING_UPDATE_FMAX_LATENCY,
        operand_field_usage=RING_UPDATE_FMAX_OPERAND_FIELD_USAGE,
        src_operands_idx=src_operands,
        dst_operands_idx=dst_operands,
        forwarding_bits=RING_UPDATE_FORWARDING_BITS,
        bypass_bits=RING_UPDATE_BYPASS_BITS,
        iter_exe_cond=RING_UPDATE_FMAX_ITER_EXE_COND,
        block_idx=row.row_index,
        end_inst=0,
        raw_inst_t_byte_count=len(raw_bytes),
        raw_inst_t_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        operand_allocation_status="skeleton_operands_unallocated",
        decode_roundtrip_status="candidate_pack_decode_roundtrip",
        component_integration_status="not_integrated",
        blocker_ids=(
            "log10max_ring_update_operand_allocation_missing",
            "log10max_ring_update_component_integration_missing",
        ),
    )


def _assert_fmax_decode_roundtrip(
    *,
    row: RingUpdateBinaryLayoutRowCandidate,
    decoded: dict[str, object],
) -> None:
    expected = {
        "opcode": RING_UPDATE_FMAX_OPCODE,
        "unit_inst_type": RING_UPDATE_FMAX_UNIT_INST_TYPE,
        "latency": RING_UPDATE_FMAX_LATENCY,
        "imms": (0, 0, 0),
        "src_operands_idx": (
            RING_UPDATE_SRC_CURRENT_OPERAND_IDX,
            RING_UPDATE_SRC_RECEIVED_OPERAND_IDX,
            0,
        ),
        "dst_operands_idx": (RING_UPDATE_DST_UPDATED_OPERAND_IDX, 0, 0),
        "forwarding_bits": RING_UPDATE_FORWARDING_BITS,
        "bypass_bits": RING_UPDATE_BYPASS_BITS,
        "iter_exe_cond": RING_UPDATE_FMAX_ITER_EXE_COND,
        "block_idx": row.row_index,
        "end_inst": 0,
    }
    for key, value in expected.items():
        if decoded[key] != value:
            raise ValueError(
                "ring update FMAX candidate decode mismatch: "
                f"row={row.row_candidate_id}, key={key}, "
                f"expected={value!r}, got={decoded[key]!r}"
            )


def _pe_index_from_label(pe: str) -> int:
    if not pe.startswith("PE(") or not pe.endswith(")"):
        raise ValueError(f"unsupported PE label: {pe!r}")
    row_text, col_text = pe[3:-1].split(",", 1)
    return int(row_text) * RING_UPDATE_MESH_X + int(col_text)


def _opcode_evidence_refs(opcode: str) -> tuple[str, ...]:
    if opcode == "HMAX":
        return (
            "docs/architecture/instruction-set/dfu3500-simd/instruction_cards.md:HMAX",
            "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:HMAX",
            "compiler/gpdpu_compiler/core/program_legacy_inst.py:LEGACY_OPS.HMAX",
        )
    return (
        "docs/architecture/instruction-set/dfu3500-simd/instruction_cards.md:FMAX",
        "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:FMAX",
        "compiler/gpdpu_compiler/core/program_legacy_inst.py:LEGACY_OPS.FMAX",
    )


__all__ = [
    "RingUpdateTemplateRecord",
    "RingUpdateTemplateReport",
    "RingUpdateTemplateBinding",
    "RingUpdateTemplateBindingReport",
    "RingUpdateTemplateOpCandidate",
    "RingUpdateBinaryLayoutRowCandidate",
    "RingUpdateBinaryLayoutCandidateReport",
    "RingUpdateFmaxInstCandidate",
    "RingUpdateFmaxInstCandidateReport",
    "RingUpdateComponentPlacementCandidate",
    "RingUpdateComponentPlacementCandidateReport",
    "RING_UPDATE_FMAX_OPERAND_FIELD_USAGE",
    "build_log10max_ring_update_template_report",
    "build_log10max_ring_update_template_binding_report",
    "build_log10max_ring_update_binary_layout_candidate_report",
    "build_log10max_ring_update_fmax_inst_candidate_report",
    "build_log10max_ring_update_component_placement_candidate_report",
    "summarize_log10max_ring_update_template_report",
    "summarize_log10max_ring_update_template_binding_report",
    "summarize_log10max_ring_update_binary_layout_candidate_report",
    "summarize_log10max_ring_update_fmax_inst_candidate_report",
    "summarize_log10max_ring_update_component_placement_candidate_report",
]
