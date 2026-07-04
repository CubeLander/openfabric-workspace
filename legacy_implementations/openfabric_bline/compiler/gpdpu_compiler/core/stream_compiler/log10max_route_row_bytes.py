"""Candidate COPY inst_t row bytes for log10max GlobalMax routes.

This module implements the accepted Phase-3B scope of the route candidate
bytes RFC.  It consumes already-owned route fields and candidate-only
``flow_ack`` records, packs simulator ``inst_t`` COPY rows, decodes them back,
and stops before final component placement.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal, Mapping

from gpdpu_compiler.core.program_legacy_inst import (
    INST_EXE_IN_ALL,
    INST_RECORD_SIZE_BYTES,
    LegacyInst,
    decode_legacy_inst_skeleton,
    pack_legacy_inst,
)

from .log10max_route_flow_ack import (
    FlowAckPolicyCandidate,
    Log10MaxRouteFlowAckCandidateReport,
    build_log10max_route_flow_ack_candidate_report,
)
from .log10max_route_inst_fields import (
    EXPECTED_PHYSICAL_PHASE_COUNTS,
    ROUTE_COMPONENT_BLOCKER,
    ROUTE_OPERAND_USAGE_POLICY_ID,
    RoutePhysicalRowPlan,
    RouteInstFieldBindingReport,
    RouteInstOperandPatch,
    RouteInstOperandPatchReport,
    build_log10max_route_inst_field_binding_report,
    build_log10max_route_inst_operand_patch_report,
    build_log10max_route_physical_row_plan_report,
)


ROUTE_CANDIDATE_ROW_BYTES_BLOCKERS = (
    "log10max_route_flow_ack_final_policy_missing",
    "log10max_route_component_byte_offset_missing",
    "log10max_route_component_integration_missing",
    "log10max_route_candidate_rows_not_in_payload_manifest",
)
LOG10MAX_ROUTE_FLOW_ACK_FINAL_POLICY_MISSING = (
    "log10max_route_flow_ack_final_policy_missing"
)
LOG10MAX_ROUTE_COMPONENT_BYTE_OFFSET_MISSING = (
    "log10max_route_component_byte_offset_missing"
)
LOG10MAX_ROUTE_COMPONENT_INTEGRATION_MISSING = (
    "log10max_route_component_integration_missing"
)
LOG10MAX_ROUTE_PAYLOAD_MANIFEST_FORBIDDEN = (
    "log10max_route_candidate_rows_not_in_payload_manifest"
)
ROUTE_CANDIDATE_DECODE_STATUS = "candidate_route_decode_roundtrip"
ROUTE_CANDIDATE_PLACEMENT_STATUS = "unplaced_candidate"
ROUTE_CANDIDATE_COMPONENT_STATUS = "not_integrated"


@dataclass(frozen=True)
class RouteInstRowByteCandidateRecord:
    """Candidate-only COPY row bytes for one physical route lane."""

    schema_version: str
    candidate_id: str
    logical_route_edge_id: str
    physical_row_plan_id: str
    physical_lane_index: int
    physical_lane_count: int
    lane_stride: int
    lane_operand_delta: int
    field_binding_record_id: str
    operand_patch_id: str
    flow_ack_policy_candidate_id: str
    raw_inst_t_row_bytes_hex: str
    raw_inst_t_row_bytes_sha256: str
    raw_inst_t_byte_count: int
    decoded_fields: Mapping[str, object]
    layout_provenance: Mapping[str, object]
    placement: Mapping[str, object]
    decoded_field_owner_status: Mapping[str, str]
    decoded_field_owner_ids: Mapping[str, str]
    provenance_refs: tuple[str, ...]
    decode_roundtrip_status: Literal["candidate_route_decode_roundtrip"]
    component_integration_status: Literal["not_integrated"]
    blocker_ids: tuple[str, ...]

    @property
    def placement_status(self) -> Literal["unplaced_candidate"]:
        return "unplaced_candidate"

    @property
    def component_byte_offset(self) -> None:
        return None

    @property
    def final_component_claim(self) -> bool:
        return False

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def uploadable(self) -> bool:
        return False

    @property
    def payload_manifest_claim(self) -> bool:
        return False

    @property
    def shadow_component_claim(self) -> bool:
        return False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "logical_route_edge_id": self.logical_route_edge_id,
            "physical_row_plan_id": self.physical_row_plan_id,
            "physical_lane_index": self.physical_lane_index,
            "physical_lane_count": self.physical_lane_count,
            "lane_stride": self.lane_stride,
            "lane_operand_delta": self.lane_operand_delta,
            "field_binding_record_id": self.field_binding_record_id,
            "operand_patch_id": self.operand_patch_id,
            "flow_ack_policy_candidate_id": self.flow_ack_policy_candidate_id,
            "raw_inst_t_row_bytes_hex": self.raw_inst_t_row_bytes_hex,
            "raw_inst_t_row_bytes_sha256": self.raw_inst_t_row_bytes_sha256,
            "raw_inst_t_byte_count": self.raw_inst_t_byte_count,
            "decoded_fields": _jsonish(self.decoded_fields),
            "layout_provenance": _jsonish(self.layout_provenance),
            "placement": _jsonish(self.placement),
            "decoded_field_owner_status": dict(self.decoded_field_owner_status),
            "decoded_field_owner_ids": dict(self.decoded_field_owner_ids),
            "provenance_refs": list(self.provenance_refs),
            "decode_roundtrip_status": self.decode_roundtrip_status,
            "placement_status": self.placement_status,
            "component_byte_offset": self.component_byte_offset,
            "component_integration_status": self.component_integration_status,
            "final_component_claim": self.final_component_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "payload_manifest_claim": self.payload_manifest_claim,
            "shadow_component_claim": self.shadow_component_claim,
            "blocker_ids": list(self.blocker_ids),
        }


@dataclass(frozen=True)
class RouteInstRowByteCandidateReport:
    """Phase-3B route COPY candidate byte report."""

    profile_id: str
    source_field_binding_report_id: str
    source_operand_patch_report_id: str
    source_flow_ack_candidate_report_id: str
    candidates: tuple[RouteInstRowByteCandidateRecord, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def uploadable(self) -> bool:
        return False

    @property
    def final_component_claim(self) -> bool:
        return False

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.candidates:
            blockers.append("log10max_route_candidate_row_bytes_missing")
        for candidate in self.candidates:
            blockers.extend(candidate.blocker_ids)
        return tuple(dict.fromkeys(blockers))

    def summary(self) -> dict[str, object]:
        phase_counts: dict[str, int] = {}
        logical_edges: set[str] = set()
        lane_counts: dict[str, int] = {}
        flow_ack_counts: dict[str, int] = {}
        flow_ack_one_phase_counts: dict[str, int] = {}
        decode_counts: dict[str, int] = {}
        placement_counts: dict[str, int] = {}
        component_counts: dict[str, int] = {}
        final_claim_count = 0
        runtime_ready_count = 0
        uploadable_count = 0
        payload_manifest_count = 0
        shadow_component_count = 0
        byte_count = 0
        for candidate in self.candidates:
            logical_edges.add(candidate.logical_route_edge_id)
            phase = str(candidate.layout_provenance["phase"])
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
            lane_key = str(candidate.physical_lane_index)
            lane_counts[lane_key] = lane_counts.get(lane_key, 0) + 1
            flow_ack = str(candidate.decoded_fields["flow_ack"])
            flow_ack_counts[flow_ack] = flow_ack_counts.get(flow_ack, 0) + 1
            if flow_ack == "1":
                flow_ack_one_phase_counts[phase] = (
                    flow_ack_one_phase_counts.get(phase, 0) + 1
                )
            decode_counts[candidate.decode_roundtrip_status] = (
                decode_counts.get(candidate.decode_roundtrip_status, 0) + 1
            )
            placement_counts[candidate.placement_status] = (
                placement_counts.get(candidate.placement_status, 0) + 1
            )
            component_counts[candidate.component_integration_status] = (
                component_counts.get(candidate.component_integration_status, 0) + 1
            )
            if candidate.final_component_claim:
                final_claim_count += 1
            if candidate.runtime_ready:
                runtime_ready_count += 1
            if candidate.uploadable:
                uploadable_count += 1
            if candidate.payload_manifest_claim:
                payload_manifest_count += 1
            if candidate.shadow_component_claim:
                shadow_component_count += 1
            byte_count += candidate.raw_inst_t_byte_count
        return {
            "profile_id": self.profile_id,
            "source_field_binding_report_id": self.source_field_binding_report_id,
            "source_operand_patch_report_id": self.source_operand_patch_report_id,
            "source_flow_ack_candidate_report_id": (
                self.source_flow_ack_candidate_report_id
            ),
            "candidate_count": len(self.candidates),
            "logical_route_edge_count": len(logical_edges),
            "phase_counts": dict(sorted(phase_counts.items())),
            "expected_phase_counts": dict(sorted(EXPECTED_PHYSICAL_PHASE_COUNTS.items())),
            "lane_counts": dict(sorted(lane_counts.items())),
            "flow_ack_counts": dict(sorted(flow_ack_counts.items())),
            "flow_ack_one_phase_counts": dict(sorted(flow_ack_one_phase_counts.items())),
            "expected_flow_ack_counts": {"0": 90, "1": 30},
            "expected_flow_ack_one_phase_counts": {
                "col_broadcast": 3,
                "col_reduce": 3,
                "row_broadcast": 12,
                "row_reduce": 12,
            },
            "decode_roundtrip_status_counts": dict(sorted(decode_counts.items())),
            "placement_status_counts": dict(sorted(placement_counts.items())),
            "component_integration_status_counts": dict(sorted(component_counts.items())),
            "raw_inst_t_byte_count": byte_count,
            "raw_inst_t_record_size": INST_RECORD_SIZE_BYTES,
            "final_component_claim_count": final_claim_count,
            "runtime_ready_claim_count": runtime_ready_count,
            "uploadable_claim_count": uploadable_count,
            "payload_manifest_claim_count": payload_manifest_count,
            "shadow_component_claim_count": shadow_component_count,
            "blocker_ids": list(self.blocker_ids),
            "final_component_claim": self.final_component_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_route_inst_row_byte_candidate_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "final_component_claim": self.final_component_claim,
            "blocker_ids": list(self.blocker_ids),
            "candidates": [candidate.to_plan() for candidate in self.candidates],
            "payload_manifest_entries": [],
            "shadow_component_entries": [],
            "layering_policy": (
                "RouteInstRowByteCandidate records are report-only candidate "
                "bytes. They do not enter insts_file.bin, payload manifests, "
                "shadow components, CBUF/MICC, runtime_ready, or uploadable."
            ),
        }


def build_log10max_route_inst_row_byte_candidate_report(
    field_binding_report: RouteInstFieldBindingReport | None = None,
    operand_patch_report: RouteInstOperandPatchReport | None = None,
    flow_ack_candidate_report: Log10MaxRouteFlowAckCandidateReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_route_inst_row_bytes_v1",
) -> RouteInstRowByteCandidateReport:
    """Build candidate COPY row bytes for all physical route lanes."""

    physical_report = build_log10max_route_physical_row_plan_report()
    operand_patch_report = (
        operand_patch_report
        or build_log10max_route_inst_operand_patch_report(physical_report)
    )
    field_binding_report = (
        field_binding_report
        or build_log10max_route_inst_field_binding_report(
            operand_patch_report, physical_report
        )
    )
    flow_ack_candidate_report = (
        flow_ack_candidate_report
        or build_log10max_route_flow_ack_candidate_report(physical_report)
    )
    patch_by_row = {
        patch.physical_row_plan_id: patch for patch in operand_patch_report.patches
    }
    binding_by_row = {
        record.physical_row_plan_id: record for record in field_binding_report.records
    }
    flow_ack_by_row = {
        candidate.physical_row_plan_id: candidate
        for candidate in flow_ack_candidate_report.candidates
    }
    candidates = tuple(
        _candidate_for_row(
            row=row,
            patch=patch_by_row[row.row_plan_id],
            binding=binding_by_row[row.row_plan_id],
            flow_ack=flow_ack_by_row[row.row_plan_id],
        )
        for row in physical_report.physical_rows
    )
    return RouteInstRowByteCandidateReport(
        profile_id=profile_id,
        source_field_binding_report_id=field_binding_report.profile_id,
        source_operand_patch_report_id=operand_patch_report.profile_id,
        source_flow_ack_candidate_report_id=flow_ack_candidate_report.profile_id,
        candidates=candidates,
    )


def summarize_log10max_route_inst_row_byte_candidate_report(
    report: RouteInstRowByteCandidateReport,
) -> dict[str, object]:
    return report.summary()


def _candidate_for_row(
    *,
    row: RoutePhysicalRowPlan,
    patch: RouteInstOperandPatch,
    binding: object,
    flow_ack: FlowAckPolicyCandidate,
) -> RouteInstRowByteCandidateRecord:
    owners = dict(binding.field_owner_ids)
    statuses = dict(binding.field_owner_status)
    _assert_field_owner_closed(patch, binding, flow_ack, owners, statuses)
    dst_pe0 = _single_dst_pe(owners, row)
    dst_block_idx = _decode_dst_block_owner(row)
    block_idx = _decode_block_idx_owner()
    end_inst = _decode_end_inst_owner()
    inst = LegacyInst(
        op_name="COPY",
        opcode=_field_int(binding, row, "opCode", expected_owner_required=True),
        unit_inst_type=_field_int(
            binding, row, "unit_inst_type", expected_owner_required=True
        ),
        latency=_field_int(binding, row, "latency", expected_owner_required=True),
        src_operands_idx=patch.src_operands_idx,
        dst_operands_idx=patch.dst_operands_idx,
        dst_pes_pos=(dst_pe0, (0, 0, 0), (0, 0, 0)),
        dst_blocks_idx=(dst_block_idx, 0, 0),
        iter_exe_cond=INST_EXE_IN_ALL,
        block_idx=block_idx,
        flow_ack=flow_ack.flow_ack,
        end_inst=end_inst,
    )
    raw_bytes = pack_legacy_inst(inst)
    decoded = decode_legacy_inst_skeleton(raw_bytes)
    _assert_decoded_fields(patch, binding, row, flow_ack, decoded)
    decoded_fields = {
        "opCode": decoded["opcode"],
        "unit_inst_type": decoded["unit_inst_type"],
        "latency": decoded["latency"],
        "src_operands_idx": decoded["src_operands_idx"],
        "dst_operands_idx": decoded["dst_operands_idx"],
        "dst_pes_pos": decoded["dst_pes_pos"],
        "dst_blocks_idx": decoded["dst_blocks_idx"],
        "flow_ack": decoded["flow_ack"],
        "end_inst": decoded["end_inst"],
        "iter_exe_cond": decoded["iter_exe_cond"],
        "imms": decoded["imms"],
        "forwarding_bits": decoded["forwarding_bits"],
        "bypass_bits": decoded["bypass_bits"],
        "src_operands_fetched": decoded["src_operands_fetched"],
        "dst_operands_fetched": decoded["dst_operands_fetched"],
        "extra_fields": decoded["extra_fields"],
    }
    layout_provenance = {
        "physical_row_plan_id": patch.physical_row_plan_id,
        "local_pc_candidate": _field_int(
            binding, row, "local_pc", expected_owner_required=True
        ),
        "phase": _phase_from_edge_id(patch.logical_route_edge_id),
        "lane_idx": patch.lane_index,
        "field_owner_ids": owners,
    }
    placement = {
        "placement_status": ROUTE_CANDIDATE_PLACEMENT_STATUS,
        "component_byte_offset": None,
    }
    return RouteInstRowByteCandidateRecord(
        schema_version="1",
        candidate_id=f"route_inst_row_byte_candidate:{patch.physical_row_plan_id}",
        logical_route_edge_id=patch.logical_route_edge_id,
        physical_row_plan_id=patch.physical_row_plan_id,
        physical_lane_index=patch.lane_index,
        physical_lane_count=patch.lane_count,
        lane_stride=patch.lane_stride_operands,
        lane_operand_delta=patch.lane_index * patch.lane_stride_operands,
        field_binding_record_id=binding.binding_id,
        operand_patch_id=patch.patch_id,
        flow_ack_policy_candidate_id=flow_ack.candidate_id,
        raw_inst_t_row_bytes_hex=raw_bytes.hex(),
        raw_inst_t_row_bytes_sha256=hashlib.sha256(raw_bytes).hexdigest(),
        raw_inst_t_byte_count=len(raw_bytes),
        decoded_fields=decoded_fields,
        layout_provenance=layout_provenance,
        placement=placement,
        decoded_field_owner_status=_candidate_field_status(statuses),
        decoded_field_owner_ids=_candidate_field_owners(owners, flow_ack),
        provenance_refs=(
            binding.binding_id,
            patch.patch_id,
            flow_ack.candidate_id,
        ),
        decode_roundtrip_status=ROUTE_CANDIDATE_DECODE_STATUS,
        component_integration_status=ROUTE_CANDIDATE_COMPONENT_STATUS,
        blocker_ids=ROUTE_CANDIDATE_ROW_BYTES_BLOCKERS,
    )


def _assert_field_owner_closed(
    patch: RouteInstOperandPatch,
    binding: object,
    flow_ack: FlowAckPolicyCandidate,
    owners: Mapping[str, str],
    statuses: Mapping[str, str],
) -> None:
    required_bound = (
        "opCode",
        "unit_inst_type",
        "latency",
        "src_operands_idx[0]",
        "dst_operands_idx[0]",
        "dst_pes_pos[0]",
        "dst_blocks_idx[0]",
        "block_idx",
        "end_inst",
        "local_pc",
    )
    for field_name in required_bound:
        if statuses.get(field_name) != "bound":
            raise ValueError(f"route candidate field not bound: {field_name}")
        if not owners.get(field_name):
            raise ValueError(f"route candidate field owner missing: {field_name}")
    for field_name in (
        "src_operands_idx[1]",
        "src_operands_idx[2]",
        "dst_operands_idx[1]",
        "dst_operands_idx[2]",
    ):
        if statuses.get(field_name) != "zero_with_evidence":
            raise ValueError(f"route candidate zero field lacks evidence: {field_name}")
        if owners.get(field_name) != ROUTE_OPERAND_USAGE_POLICY_ID:
            raise ValueError(f"route candidate zero field owner mismatch: {field_name}")
    if owners.get("flow_ack"):
        raise ValueError("Phase-2 field binding must not final-bind flow_ack")
    if flow_ack.flow_ack_status != "candidate_bound":
        raise ValueError(f"flow_ack candidate not bound: {flow_ack.candidate_id}")
    if flow_ack.final_policy_status != "pending_final_policy":
        raise ValueError(f"flow_ack final policy must remain pending: {flow_ack}")
    if flow_ack.final_component_claim or flow_ack.runtime_ready or flow_ack.uploadable:
        raise ValueError(f"flow_ack candidate must not claim final state: {flow_ack}")
    if flow_ack.physical_row_plan_id != patch.physical_row_plan_id:
        raise ValueError("flow_ack candidate row does not match operand patch")
    if owners.get("end_inst") == flow_ack.candidate_id:
        raise ValueError("flow_ack must not own end_inst")
    if binding.final_component_claim or binding.runtime_ready or binding.uploadable:
        raise ValueError(f"field binding must not claim final state: {binding}")


def _assert_decoded_fields(
    patch: RouteInstOperandPatch,
    binding: object,
    row: RoutePhysicalRowPlan,
    flow_ack: FlowAckPolicyCandidate,
    decoded: Mapping[str, object],
) -> None:
    expected = {
        "opcode": _field_int(binding, row, "opCode", expected_owner_required=True),
        "unit_inst_type": _field_int(
            binding, row, "unit_inst_type", expected_owner_required=True
        ),
        "latency": _field_int(binding, row, "latency", expected_owner_required=True),
        "src_operands_idx": patch.src_operands_idx,
        "dst_operands_idx": patch.dst_operands_idx,
        "dst_blocks_idx": (_decode_dst_block_owner(row), 0, 0),
        "block_idx": _decode_block_idx_owner(),
        "flow_ack": flow_ack.flow_ack,
        "end_inst": _decode_end_inst_owner(),
    }
    for field_name, expected_value in expected.items():
        if decoded[field_name] != expected_value:
            raise ValueError(
                "log10max route candidate decode mismatch: "
                f"row={patch.physical_row_plan_id}, field={field_name}, "
                f"expected={expected_value!r}, got={decoded[field_name]!r}"
            )
    if decoded["dst_pes_pos"][0] != _single_dst_pe(dict(binding.field_owner_ids), row):
        raise ValueError(f"dst PE decode mismatch: {patch.physical_row_plan_id}")
    if patch.src_operands_idx[1:] != (0, 0) or patch.dst_operands_idx[1:] != (0, 0):
        raise ValueError(f"COPY candidate only supports src0/dst0: {patch.patch_id}")


def _field_int(
    binding: object,
    row: RoutePhysicalRowPlan,
    field_name: str,
    *,
    expected_owner_required: bool,
) -> int:
    # Values are already source-bound in Phase 2 reports; parse them from known
    # field-owner status by using the physical-row id conventions and record
    # fields.  The explicit checks above keep this from becoming writer-owned
    # default fill.
    if expected_owner_required and not dict(binding.field_owner_ids).get(field_name):
        raise ValueError(f"missing owner for {field_name}")
    if field_name == "opCode":
        return row.physical_opcode
    if field_name == "unit_inst_type":
        return row.physical_unit_inst_type
    if field_name == "latency":
        return row.physical_latency
    if field_name == "local_pc":
        if row.physical_local_pc is None:
            raise ValueError(f"missing local_pc candidate: {row.row_plan_id}")
        return row.physical_local_pc
    raise ValueError(f"unsupported integer field request: {field_name}")


def _single_dst_pe(
    owners: Mapping[str, str],
    row: RoutePhysicalRowPlan,
) -> tuple[int, int, int]:
    if not owners.get("dst_pes_pos[0]"):
        raise ValueError("missing dst PE owner")
    return row.dst_pe_pos


def _decode_dst_block_owner(row: RoutePhysicalRowPlan) -> int:
    if row.dst_block_idx is None:
        raise ValueError(f"missing dst block for {row.row_plan_id}")
    return row.dst_block_idx


def _decode_block_idx_owner() -> int:
    # Sender block index is carried by the ExeBlockWriterPlan owner.  The
    # current route field-binding report only exposes the owner id; for
    # candidate bytes we keep the simulator field at zero and prove ownership
    # through field_owner_ids instead of deriving final placement.
    return 0


def _decode_end_inst_owner() -> int:
    # The boundary owner exists, but this candidate report must not infer final
    # stage boundaries from flow_ack.  Keep the simulator field from the
    # boundary-owned placeholder value and require a distinct owner id.
    return 0


def _candidate_field_status(statuses: Mapping[str, str]) -> dict[str, str]:
    result = {
        key: statuses[key]
        for key in (
            "opCode",
            "unit_inst_type",
            "latency",
            "src_operands_idx[0]",
            "src_operands_idx[1]",
            "src_operands_idx[2]",
            "dst_operands_idx[0]",
            "dst_operands_idx[1]",
            "dst_operands_idx[2]",
            "dst_pes_pos[0]",
            "dst_blocks_idx[0]",
            "block_idx",
            "end_inst",
            "local_pc",
        )
    }
    result["flow_ack"] = "candidate_bound"
    result["component_byte_offset"] = "pending"
    return result


def _candidate_field_owners(
    owners: Mapping[str, str],
    flow_ack: FlowAckPolicyCandidate,
) -> dict[str, str]:
    result = {
        key: owners[key]
        for key in (
            "opCode",
            "unit_inst_type",
            "latency",
            "src_operands_idx[0]",
            "src_operands_idx[1]",
            "src_operands_idx[2]",
            "dst_operands_idx[0]",
            "dst_operands_idx[1]",
            "dst_operands_idx[2]",
            "dst_pes_pos[0]",
            "dst_blocks_idx[0]",
            "block_idx",
            "end_inst",
            "local_pc",
        )
    }
    result["flow_ack"] = flow_ack.candidate_id
    result["component_byte_offset"] = ""
    return result


def _phase_from_edge_id(edge_id: str) -> str:
    parts = edge_id.split(":")
    return parts[2] if len(parts) >= 3 else "unknown"


def _jsonish(value: object) -> object:
    if isinstance(value, Mapping):
        return {str(key): _jsonish(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [_jsonish(item) for item in value]
    if isinstance(value, list):
        return [_jsonish(item) for item in value]
    return value


__all__ = [
    "ROUTE_CANDIDATE_COMPONENT_STATUS",
    "ROUTE_CANDIDATE_DECODE_STATUS",
    "ROUTE_CANDIDATE_PLACEMENT_STATUS",
    "ROUTE_CANDIDATE_ROW_BYTES_BLOCKERS",
    "LOG10MAX_ROUTE_COMPONENT_BYTE_OFFSET_MISSING",
    "LOG10MAX_ROUTE_COMPONENT_INTEGRATION_MISSING",
    "LOG10MAX_ROUTE_FLOW_ACK_FINAL_POLICY_MISSING",
    "LOG10MAX_ROUTE_PAYLOAD_MANIFEST_FORBIDDEN",
    "RouteInstRowByteCandidateRecord",
    "RouteInstRowByteCandidateReport",
    "build_log10max_route_inst_row_byte_candidate_report",
    "summarize_log10max_route_inst_row_byte_candidate_report",
]
