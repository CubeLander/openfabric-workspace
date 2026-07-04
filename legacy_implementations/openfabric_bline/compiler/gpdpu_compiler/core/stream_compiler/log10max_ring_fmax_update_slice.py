"""Allocation-backed log10max ring FMAX update slice.

This is the progress-first bridge from the existing ring-update operand patch
records to an operator instruction slice.  It emits candidate row bytes for the
30 receiver-side FMAX updates using already allocated operand indices, then
places those rows into the same layout epoch as the route COPY slice.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from gpdpu_compiler.core.program_bin import MAX_INST_AMOUNT_PER_PE
from gpdpu_compiler.core.program_legacy_inst import (
    INST_RECORD_SIZE_BYTES,
    LegacyInst,
    decode_legacy_inst_skeleton,
    pack_legacy_inst,
)

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
    RING_UPDATE_FMAX_OPERAND_FIELD_USAGE,
    RING_UPDATE_FMAX_UNIT_INST_TYPE,
    RING_UPDATE_FORWARDING_BITS,
    RingUpdateBinaryLayoutCandidateReport,
    RingUpdateBinaryLayoutRowCandidate,
    build_log10max_ring_update_binary_layout_candidate_report,
)
from .log10max_route_component_placement import (
    Log10MaxRouteComponentPlacementReport,
    RouteLaneGroupCompletion,
    build_log10max_route_component_placement_report,
)


EXPECTED_RING_FMAX_PHASE_COUNTS = {
    "col_broadcast": 3,
    "col_reduce": 3,
    "row_broadcast": 12,
    "row_reduce": 12,
}
LOG10MAX_RING_FMAX_UPDATE_COMPONENT_INTEGRATION_BLOCKED = (
    "log10max_ring_fmax_update_component_integration_blocked"
)


@dataclass(frozen=True)
class RingFmaxUpdateSliceRow:
    """One allocation-backed FMAX update row for the operator slice ledger."""

    schema_version: str
    row_id: str
    source_patch_id: str
    row_candidate_id: str
    logical_route_edge_id: str
    route_lane_group_completion_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    task_id: int
    pe: str
    pe_index: int
    local_pc: int
    component_byte_offset: int
    layout_epoch: str
    layout_plan_sha256: str
    source_fiber_op_id: str
    source_stream_action_id: str
    template_expansion_id: str
    allocation_ids: tuple[str, ...]
    opcode: Literal["FMAX"]
    src_operands_idx: tuple[int, int, int]
    dst_operands_idx: tuple[int, int, int]
    operand_field_usage: tuple[tuple[str, str], ...]
    raw_inst_t_row_bytes_hex: str
    raw_inst_t_row_bytes_sha256: str
    decode_roundtrip_status: Literal["pass"]
    provenance_status: Literal["pass"]
    ordering_status: Literal["route_lane_group_completion_bound"]
    byte_status: Literal["allocation_backed_candidate"]
    component_integration_status: Literal["slice_row_candidate"]
    blocker_ids: tuple[str, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def uploadable(self) -> bool:
        return False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "row_id": self.row_id,
            "source_patch_id": self.source_patch_id,
            "row_candidate_id": self.row_candidate_id,
            "logical_route_edge_id": self.logical_route_edge_id,
            "route_lane_group_completion_id": self.route_lane_group_completion_id,
            "phase": self.phase,
            "task_id": self.task_id,
            "pe": self.pe,
            "pe_index": self.pe_index,
            "local_pc": self.local_pc,
            "component_byte_offset": self.component_byte_offset,
            "layout_epoch": self.layout_epoch,
            "layout_plan_sha256": self.layout_plan_sha256,
            "source_fiber_op_id": self.source_fiber_op_id,
            "source_stream_action_id": self.source_stream_action_id,
            "template_expansion_id": self.template_expansion_id,
            "allocation_ids": list(self.allocation_ids),
            "opcode": self.opcode,
            "src_operands_idx": list(self.src_operands_idx),
            "dst_operands_idx": list(self.dst_operands_idx),
            "operand_field_usage": dict(self.operand_field_usage),
            "raw_inst_t_row_bytes_hex": self.raw_inst_t_row_bytes_hex,
            "raw_inst_t_row_bytes_sha256": self.raw_inst_t_row_bytes_sha256,
            "decode_roundtrip_status": self.decode_roundtrip_status,
            "provenance_status": self.provenance_status,
            "ordering_status": self.ordering_status,
            "byte_status": self.byte_status,
            "component_integration_status": self.component_integration_status,
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }


@dataclass(frozen=True)
class RingFmaxUpdateSliceReport:
    """Allocation-backed FMAX update slice candidate for log10max."""

    profile_id: str
    source_patch_report_id: str
    source_layout_report_id: str
    source_route_placement_report_id: str
    layout_epoch: str
    layout_plan_sha256: str
    rows: tuple[RingFmaxUpdateSliceRow, ...]

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.rows:
            blockers.append("log10max_ring_fmax_update_slice_missing")
        for row in self.rows:
            blockers.extend(row.blocker_ids)
        return tuple(dict.fromkeys(blockers))

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def uploadable(self) -> bool:
        return False

    @property
    def slice_sha256(self) -> str | None:
        if not self.rows:
            return None
        payload = "".join(row.raw_inst_t_row_bytes_sha256 for row in self.rows)
        return hashlib.sha256(payload.encode()).hexdigest()

    def summary(self) -> dict[str, object]:
        phase_counts: dict[str, int] = {}
        pe_counts: dict[str, int] = {}
        offset_set: set[int] = set()
        duplicate_offset_count = 0
        for row in self.rows:
            phase_counts[row.phase] = phase_counts.get(row.phase, 0) + 1
            pe_counts[row.pe] = pe_counts.get(row.pe, 0) + 1
            if row.component_byte_offset in offset_set:
                duplicate_offset_count += 1
            offset_set.add(row.component_byte_offset)
        return {
            "profile_id": self.profile_id,
            "source_patch_report_id": self.source_patch_report_id,
            "source_layout_report_id": self.source_layout_report_id,
            "source_route_placement_report_id": self.source_route_placement_report_id,
            "layout_epoch": self.layout_epoch,
            "layout_plan_sha256": self.layout_plan_sha256,
            "row_count": len(self.rows),
            "phase_counts": dict(sorted(phase_counts.items())),
            "pe_counts": dict(sorted(pe_counts.items())),
            "duplicate_component_byte_offset_count": duplicate_offset_count,
            "slice_sha256": self.slice_sha256,
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_ring_fmax_update_slice_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "blocker_ids": list(self.blocker_ids),
            "rows": [row.to_plan() for row in self.rows],
            "layering_policy": (
                "ring_fmax_update is an operator instruction slice candidate. "
                "It uses allocation-backed row bytes and route lane-group "
                "completion, but it does not assemble final CBUF/MICC payloads "
                "or aggregate runtime_ready."
            ),
        }


def build_log10max_ring_fmax_update_slice_report(
    layout_report: RingUpdateBinaryLayoutCandidateReport | None = None,
    patch_report: RingUpdateInstOperandPatchReport | None = None,
    route_placement_report: Log10MaxRouteComponentPlacementReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_ring_fmax_update_slice_v1",
) -> RingFmaxUpdateSliceReport:
    layout = layout_report or build_log10max_ring_update_binary_layout_candidate_report()
    patches = patch_report or build_log10max_ring_update_inst_operand_patch_report(
        layout_report=layout
    )
    route = route_placement_report or build_log10max_route_component_placement_report()
    layout_by_row = {row.row_candidate_id: row for row in layout.row_candidates}
    completion_by_edge = {
        completion.logical_route_edge_id: completion
        for completion in route.lane_group_completions
    }
    next_local_pc_by_pe = _next_local_pc_by_pe(route)
    rows: list[RingFmaxUpdateSliceRow] = []
    for patch in patches.patches:
        layout_row = layout_by_row[patch.row_candidate_id]
        completion = completion_by_edge[patch.source_ring_edge_id]
        local_pc = next_local_pc_by_pe.get(layout_row.dst_pe, 0)
        next_local_pc_by_pe[layout_row.dst_pe] = local_pc + 1
        rows.append(
            _row_from_patch(
                patch=patch,
                layout_row=layout_row,
                completion=completion,
                route=route,
                local_pc=local_pc,
            )
        )
    return RingFmaxUpdateSliceReport(
        profile_id=profile_id,
        source_patch_report_id=patches.profile_id,
        source_layout_report_id=layout.profile_id,
        source_route_placement_report_id=route.profile_id,
        layout_epoch=route.layout_epoch,
        layout_plan_sha256=route.layout_plan_sha256,
        rows=tuple(rows),
    )


def summarize_log10max_ring_fmax_update_slice_report(
    report: RingFmaxUpdateSliceReport,
) -> dict[str, object]:
    return report.summary()


def _row_from_patch(
    *,
    patch: InstOperandPatch,
    layout_row: RingUpdateBinaryLayoutRowCandidate,
    completion: RouteLaneGroupCompletion,
    route: Log10MaxRouteComponentPlacementReport,
    local_pc: int,
) -> RingFmaxUpdateSliceRow:
    raw_bytes = _pack_fmax_patch_row(patch, block_idx=local_pc)
    raw_sha = hashlib.sha256(raw_bytes).hexdigest()
    pe_index = _pe_index_from_label(layout_row.dst_pe)
    return RingFmaxUpdateSliceRow(
        schema_version="1",
        row_id=f"operator_slice_row:ring_fmax_update:{layout_row.source_ring_edge_id}",
        source_patch_id=patch.patch_id,
        row_candidate_id=patch.row_candidate_id,
        logical_route_edge_id=layout_row.source_ring_edge_id,
        route_lane_group_completion_id=completion.completion_id,
        phase=layout_row.phase,
        task_id=layout_row.task_id,
        pe=layout_row.dst_pe,
        pe_index=pe_index,
        local_pc=local_pc,
        component_byte_offset=(
            (pe_index * MAX_INST_AMOUNT_PER_PE + local_pc) * INST_RECORD_SIZE_BYTES
        ),
        layout_epoch=route.layout_epoch,
        layout_plan_sha256=route.layout_plan_sha256,
        source_fiber_op_id=patch.source_fiber_op_id,
        source_stream_action_id=patch.source_stream_action_id,
        template_expansion_id=patch.template_expansion_id,
        allocation_ids=patch.allocation_ids,
        opcode="FMAX",
        src_operands_idx=patch.src_operands_idx,
        dst_operands_idx=patch.dst_operands_idx,
        operand_field_usage=patch.operand_field_usage,
        raw_inst_t_row_bytes_hex=raw_bytes.hex(),
        raw_inst_t_row_bytes_sha256=raw_sha,
        decode_roundtrip_status="pass",
        provenance_status="pass",
        ordering_status="route_lane_group_completion_bound",
        byte_status="allocation_backed_candidate",
        component_integration_status="slice_row_candidate",
        blocker_ids=(LOG10MAX_RING_FMAX_UPDATE_COMPONENT_INTEGRATION_BLOCKED,),
    )


def _pack_fmax_patch_row(patch: InstOperandPatch, *, block_idx: int) -> bytes:
    inst = LegacyInst(
        op_name="FMAX",
        opcode=RING_UPDATE_FMAX_OPCODE,
        unit_inst_type=RING_UPDATE_FMAX_UNIT_INST_TYPE,
        latency=RING_UPDATE_FMAX_LATENCY,
        imms=(0, 0, 0),
        src_operands_idx=patch.src_operands_idx,
        dst_operands_idx=patch.dst_operands_idx,
        forwarding_bits=RING_UPDATE_FORWARDING_BITS,
        bypass_bits=RING_UPDATE_BYPASS_BITS,
        iter_exe_cond=RING_UPDATE_FMAX_ITER_EXE_COND,
        block_idx=block_idx,
        end_inst=0,
    )
    raw_bytes = pack_legacy_inst(inst)
    decoded = decode_legacy_inst_skeleton(raw_bytes)
    expected = {
        "opcode": RING_UPDATE_FMAX_OPCODE,
        "unit_inst_type": RING_UPDATE_FMAX_UNIT_INST_TYPE,
        "latency": RING_UPDATE_FMAX_LATENCY,
        "src_operands_idx": patch.src_operands_idx,
        "dst_operands_idx": patch.dst_operands_idx,
        "forwarding_bits": RING_UPDATE_FORWARDING_BITS,
        "bypass_bits": RING_UPDATE_BYPASS_BITS,
        "iter_exe_cond": RING_UPDATE_FMAX_ITER_EXE_COND,
        "block_idx": block_idx,
        "end_inst": 0,
    }
    for key, value in expected.items():
        if decoded[key] != value:
            raise ValueError(
                "allocation-backed FMAX row decode mismatch: "
                f"patch={patch.patch_id}, key={key}, "
                f"expected={value!r}, got={decoded[key]!r}"
            )
    return raw_bytes


def _next_local_pc_by_pe(
    route: Log10MaxRouteComponentPlacementReport,
) -> dict[str, int]:
    next_pc: dict[str, int] = {}
    for placement in route.placements:
        value = placement.pe_local_pc + 1
        next_pc[placement.source_pe] = max(next_pc.get(placement.source_pe, 0), value)
    return next_pc


def _pe_index_from_label(pe: str) -> int:
    if not pe.startswith("PE(") or not pe.endswith(")"):
        raise ValueError(f"unsupported PE label: {pe!r}")
    row_text, col_text = pe[3:-1].split(",", 1)
    return int(row_text) * 4 + int(col_text)


__all__ = [
    "EXPECTED_RING_FMAX_PHASE_COUNTS",
    "LOG10MAX_RING_FMAX_UPDATE_COMPONENT_INTEGRATION_BLOCKED",
    "RingFmaxUpdateSliceReport",
    "RingFmaxUpdateSliceRow",
    "build_log10max_ring_fmax_update_slice_report",
    "summarize_log10max_ring_fmax_update_slice_report",
]
