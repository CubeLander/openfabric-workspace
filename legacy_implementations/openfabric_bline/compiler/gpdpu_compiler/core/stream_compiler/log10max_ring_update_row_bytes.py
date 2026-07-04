"""Candidate inst_t row bytes for log10max ring FMAX updates.

This module implements the accepted Phase-1 scope of the inst-row field
provenance RFC.  It consumes allocation-backed ``InstOperandPatch`` records and
packs only the FMAX row-body fields whose owners are already known.  The output
is intentionally candidate-only: no route rows, component offsets, CBUF/MICC
insertion, or runtime_ready transition are claimed here.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, Mapping

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
    RING_UPDATE_FMAX_OPERAND_FIELD_USAGE,
    RING_UPDATE_FMAX_OPCODE,
    RING_UPDATE_FMAX_UNIT_INST_TYPE,
    RING_UPDATE_FORWARDING_BITS,
)


EXPECTED_PHASE_COUNTS = {
    "col_broadcast": 3,
    "col_reduce": 3,
    "row_broadcast": 12,
    "row_reduce": 12,
}
ROW_BODY_FIELD_BLOCKERS = (
    "log10max_ring_update_inst_field_binding_pending",
    "log10max_ring_update_instruction_layout_pending",
    "log10max_ring_update_instruction_boundary_pending",
    "log10max_ring_update_component_placement_pending",
    "log10max_ring_update_component_integration_missing",
)
OWNED_DECODED_FIELD_NAMES = (
    "opcode",
    "unit_inst_type",
    "latency",
    "imms",
    "src_operands_idx",
    "dst_operands_idx",
    "forwarding_bits",
    "bypass_bits",
    "iter_exe_cond",
    "operand_field_usage",
)
PENDING_DECODED_FIELD_NAMES = (
    "dst_pes_pos",
    "dst_blocks_idx",
    "src_operands_fetched",
    "dst_operands_fetched",
    "block_idx",
    "flow_ack",
    "end_inst",
    "extra_fields",
)


@dataclass(frozen=True)
class InstRowByteCandidateRecord:
    """Allocation-backed row-body bytes for one FMAX update candidate."""

    schema_version: str
    row_byte_candidate_id: str
    row_candidate_id: str
    source_patch_id: str
    source_ring_edge_id: str
    source_stream_action_id: str
    source_fiber_op_id: str
    template_expansion_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    opcode: Literal["FMAX"]
    field_binding_record_id: str | None
    field_binding_status: Literal["pending_inst_field_binding_record"]
    decoded_fields: Mapping[str, object]
    pending_decoded_fields: Mapping[str, object]
    raw_inst_t_row_bytes_sha256: str
    raw_inst_t_byte_count: int
    decode_roundtrip_status: Literal["candidate_row_body_decode_roundtrip", "not_run"]
    placement_status: Literal["unplaced_candidate"]
    component_byte_offset: int | None
    component_integration_status: Literal["not_integrated"]
    blocker_ids: tuple[str, ...]

    @property
    def runtime_ready_claim(self) -> bool:
        return False

    @property
    def uploadable_claim(self) -> bool:
        return False

    @property
    def final_row_bytes_claim(self) -> bool:
        return False

    @property
    def component_integration_claim(self) -> bool:
        return False

    @property
    def row_body_candidate_bytes_claim(self) -> bool:
        return self.decode_roundtrip_status == "candidate_row_body_decode_roundtrip"

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "row_byte_candidate_id": self.row_byte_candidate_id,
            "row_candidate_id": self.row_candidate_id,
            "source_patch_id": self.source_patch_id,
            "source_ring_edge_id": self.source_ring_edge_id,
            "source_stream_action_id": self.source_stream_action_id,
            "source_fiber_op_id": self.source_fiber_op_id,
            "template_expansion_id": self.template_expansion_id,
            "phase": self.phase,
            "opcode": self.opcode,
            "field_binding_record_id": self.field_binding_record_id,
            "field_binding_status": self.field_binding_status,
            "decoded_fields": _jsonish(self.decoded_fields),
            "pending_decoded_fields": _jsonish(self.pending_decoded_fields),
            "owned_decoded_field_names": list(OWNED_DECODED_FIELD_NAMES),
            "pending_decoded_field_names": list(PENDING_DECODED_FIELD_NAMES),
            "raw_inst_t_row_bytes_sha256": self.raw_inst_t_row_bytes_sha256,
            "raw_inst_t_byte_count": self.raw_inst_t_byte_count,
            "decode_roundtrip_status": self.decode_roundtrip_status,
            "placement_status": self.placement_status,
            "component_byte_offset": self.component_byte_offset,
            "component_integration_status": self.component_integration_status,
            "blocker_ids": list(self.blocker_ids),
            "row_body_candidate_bytes_claim": self.row_body_candidate_bytes_claim,
            "final_row_bytes_claim": self.final_row_bytes_claim,
            "component_integration_claim": self.component_integration_claim,
            "runtime_ready_claim": self.runtime_ready_claim,
            "uploadable_claim": self.uploadable_claim,
        }


@dataclass(frozen=True)
class InstRowByteCandidateReport:
    """Phase-1 report for allocation-backed FMAX row-body candidates."""

    profile_id: str
    source_patch_report_id: str
    candidates: tuple[InstRowByteCandidateRecord, ...]

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.candidates:
            blockers.append("log10max_ring_update_inst_row_bytes_missing")
        for candidate in self.candidates:
            blockers.extend(candidate.blocker_ids)
        return tuple(dict.fromkeys(blockers))

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def uploadable(self) -> bool:
        return False

    def summary(self) -> dict[str, object]:
        phase_counts: dict[str, int] = {}
        opcode_counts: dict[str, int] = {}
        decode_counts: dict[str, int] = {}
        placement_counts: dict[str, int] = {}
        integration_counts: dict[str, int] = {}
        byte_count = 0
        for candidate in self.candidates:
            phase_counts[candidate.phase] = phase_counts.get(candidate.phase, 0) + 1
            opcode_counts[candidate.opcode] = opcode_counts.get(candidate.opcode, 0) + 1
            decode_counts[candidate.decode_roundtrip_status] = (
                decode_counts.get(candidate.decode_roundtrip_status, 0) + 1
            )
            placement_counts[candidate.placement_status] = (
                placement_counts.get(candidate.placement_status, 0) + 1
            )
            integration_counts[candidate.component_integration_status] = (
                integration_counts.get(candidate.component_integration_status, 0) + 1
            )
            byte_count += candidate.raw_inst_t_byte_count
        return {
            "profile_id": self.profile_id,
            "source_patch_report_id": self.source_patch_report_id,
            "candidate_count": len(self.candidates),
            "phase_counts": dict(sorted(phase_counts.items())),
            "opcode_counts": dict(sorted(opcode_counts.items())),
            "decode_roundtrip_status_counts": dict(sorted(decode_counts.items())),
            "placement_status_counts": dict(sorted(placement_counts.items())),
            "component_integration_status_counts": dict(
                sorted(integration_counts.items())
            ),
            "raw_inst_t_byte_count": byte_count,
            "blocker_ids": list(self.blocker_ids),
            "row_body_candidate_bytes_claim": bool(self.candidates),
            "final_row_bytes_claim": False,
            "component_integration_claim": False,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_ring_update_inst_row_byte_candidate_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "blocker_ids": list(self.blocker_ids),
            "candidates": [candidate.to_plan() for candidate in self.candidates],
            "layering_policy": (
                "candidate rows consume allocation-backed InstOperandPatch records "
                "and prove only FMAX row-body pack/decode fields; route rows, "
                "component placement, CBUF/MICC insertion, runtime_ready, and "
                "uploadable remain out of scope"
            ),
        }


def build_log10max_ring_update_inst_row_byte_candidate_report(
    patch_report: RingUpdateInstOperandPatchReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_ring_update_inst_row_bytes_v1",
) -> InstRowByteCandidateReport:
    """Build candidate row-body bytes for 30 allocation-backed FMAX updates."""

    patches = patch_report or build_log10max_ring_update_inst_operand_patch_report()
    candidates = tuple(_candidate_for_patch(patch) for patch in patches.patches)
    return InstRowByteCandidateReport(
        profile_id=profile_id,
        source_patch_report_id=patches.profile_id,
        candidates=candidates,
    )


def summarize_log10max_ring_update_inst_row_byte_candidate_report(
    report: InstRowByteCandidateReport,
) -> dict[str, object]:
    return report.summary()


def _candidate_for_patch(patch: InstOperandPatch) -> InstRowByteCandidateRecord:
    if patch.opcode != "FMAX":
        raise ValueError(f"Phase-1 row bytes only support FMAX: {patch.opcode}")
    if patch.patch_status != "patched":
        raise ValueError(f"cannot pack unpatched row candidate: {patch.patch_id}")
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
        block_idx=0,
        end_inst=0,
    )
    raw_bytes = pack_legacy_inst(inst)
    decoded = decode_legacy_inst_skeleton(raw_bytes)
    _check_owned_fields(patch, decoded)
    return InstRowByteCandidateRecord(
        schema_version="1",
        row_byte_candidate_id=f"inst_row_byte_candidate:{patch.row_candidate_id}",
        row_candidate_id=patch.row_candidate_id,
        source_patch_id=patch.patch_id,
        source_ring_edge_id=patch.source_ring_edge_id,
        source_stream_action_id=patch.source_stream_action_id,
        source_fiber_op_id=patch.source_fiber_op_id,
        template_expansion_id=patch.template_expansion_id,
        phase=_phase_from_edge_id(patch.source_ring_edge_id),
        opcode="FMAX",
        field_binding_record_id=None,
        field_binding_status="pending_inst_field_binding_record",
        decoded_fields=_owned_decoded_fields(decoded, patch),
        pending_decoded_fields=_pending_decoded_fields(decoded),
        raw_inst_t_row_bytes_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        raw_inst_t_byte_count=len(raw_bytes),
        decode_roundtrip_status="candidate_row_body_decode_roundtrip",
        placement_status="unplaced_candidate",
        component_byte_offset=None,
        component_integration_status="not_integrated",
        blocker_ids=ROW_BODY_FIELD_BLOCKERS,
    )


def _check_owned_fields(
    patch: InstOperandPatch,
    decoded: Mapping[str, object],
) -> None:
    expected = {
        "opcode": RING_UPDATE_FMAX_OPCODE,
        "unit_inst_type": RING_UPDATE_FMAX_UNIT_INST_TYPE,
        "latency": RING_UPDATE_FMAX_LATENCY,
        "imms": (0, 0, 0),
        "src_operands_idx": patch.src_operands_idx,
        "dst_operands_idx": patch.dst_operands_idx,
        "forwarding_bits": RING_UPDATE_FORWARDING_BITS,
        "bypass_bits": RING_UPDATE_BYPASS_BITS,
        "iter_exe_cond": RING_UPDATE_FMAX_ITER_EXE_COND,
    }
    for field_name, value in expected.items():
        if decoded[field_name] != value:
            raise ValueError(
                "log10max ring update row-body decode mismatch: "
                f"patch={patch.patch_id}, field={field_name}, "
                f"expected={value!r}, got={decoded[field_name]!r}"
            )
    if patch.src_operands_idx[2] != 0:
        raise ValueError(f"src2 must be unused zero-fill: {patch.patch_id}")
    if patch.dst_operands_idx[1:] != (0, 0):
        raise ValueError(f"dst1/dst2 must be unused zero-fill: {patch.patch_id}")


def _owned_decoded_fields(
    decoded: Mapping[str, object],
    patch: InstOperandPatch,
) -> dict[str, object]:
    return {
        "opcode": decoded["opcode"],
        "unit_inst_type": decoded["unit_inst_type"],
        "latency": decoded["latency"],
        "imms": decoded["imms"],
        "src_operands_idx": decoded["src_operands_idx"],
        "dst_operands_idx": decoded["dst_operands_idx"],
        "forwarding_bits": decoded["forwarding_bits"],
        "bypass_bits": decoded["bypass_bits"],
        "iter_exe_cond": decoded["iter_exe_cond"],
        "operand_field_usage": dict(RING_UPDATE_FMAX_OPERAND_FIELD_USAGE),
        "allocation_ids": patch.allocation_ids,
        "src_placeholders": patch.src_placeholders,
        "dst_placeholders": patch.dst_placeholders,
    }


def _pending_decoded_fields(decoded: Mapping[str, object]) -> dict[str, object]:
    return {
        field_name: decoded[field_name]
        for field_name in PENDING_DECODED_FIELD_NAMES
    }


def _phase_from_edge_id(edge_id: str) -> Literal[
    "row_reduce", "col_reduce", "col_broadcast", "row_broadcast"
]:
    parts = edge_id.split(":")
    if len(parts) < 3:
        raise ValueError(f"unexpected ring edge id: {edge_id}")
    phase = parts[2]
    if phase not in EXPECTED_PHASE_COUNTS:
        raise ValueError(f"unexpected ring edge phase: {edge_id}")
    return phase  # type: ignore[return-value]


def _jsonish(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonish(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonish(item) for item in value]
    if isinstance(value, list):
        return [_jsonish(item) for item in value]
    return value
