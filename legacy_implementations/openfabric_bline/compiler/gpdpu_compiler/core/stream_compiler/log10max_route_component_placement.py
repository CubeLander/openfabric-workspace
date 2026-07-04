"""Phase-4B route COPY row placement for log10max.

This module assigns PE-major ``insts`` component offsets for candidate route
COPY rows.  It consumes already decoded candidate bytes plus final simulator
``flow_ack`` ownership, but it does not mutate CBUF/MICC files, does not write
payload manifests, and does not aggregate ``runtime_ready``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal, Mapping

from gpdpu_compiler.core.program_bin import MAX_INST_AMOUNT_PER_PE
from gpdpu_compiler.core.program_legacy_inst import INST_RECORD_SIZE_BYTES

from .log10max_route_byte_family import (
    RoutePhysicalRowPlan,
    RoutePhysicalRowPlanReport,
    build_log10max_route_physical_row_plan_report,
)
from .log10max_route_flow_ack import (
    Log10MaxRouteFlowAckFinalPolicyReport,
    RouteFlowAckFinalPolicyBinding,
    build_log10max_route_flow_ack_final_policy_report,
)
from .log10max_route_row_bytes import (
    LOG10MAX_ROUTE_COMPONENT_INTEGRATION_MISSING,
    RouteInstRowByteCandidateRecord,
    RouteInstRowByteCandidateReport,
    build_log10max_route_inst_row_byte_candidate_report,
)


LOG10MAX_ROUTE_FULL_LAYOUT_EPOCH_NOT_FROZEN = (
    "log10max_route_full_layout_epoch_not_frozen"
)
LOG10MAX_ROUTE_COMPONENT_OVERWRITE_CHECK_SCOPED = (
    "log10max_route_component_overwrite_check_reserved_slot_scoped"
)
ROUTE_COMPONENT_PLACEMENT_STATUS = "placed_candidate"
ROUTE_COMPONENT_INTEGRATION_STATUS = "not_integrated"
ROUTE_COMPONENT_CANDIDATE_INTEGRATION_STATUS = "route_slice_integrated_candidate"
ROUTE_COMPONENT_NAME = "insts_file.bin"
ROUTE_LAYOUT_EPOCH = "layout_epoch:log10max_route_copy_rows:phase4b:v1"
ROUTE_RESERVED_ROW_POLICY_ID = (
    "reserved_row_policy:log10max_route_copy_rows:"
    "non_route_rows_pending_same_layout_epoch:v1"
)
PE_MESH_X = 4
PE_MESH_Y = 4
LOG10MAX_OPERATOR_MANIFEST_MISSING = "log10max_operator_manifest_missing"
LOG10MAX_OPERATOR_RUNTIME_READY_GATE_NOT_AGGREGATED = (
    "log10max_operator_runtime_ready_gate_not_aggregated"
)


@dataclass(frozen=True)
class RouteLaneGroupCompletion:
    """Derived completion token for a logical COPYT-expanded route edge."""

    schema_version: str
    completion_id: str
    logical_route_edge_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    physical_row_ids: tuple[str, ...]
    physical_candidate_ids: tuple[str, ...]
    lane_count: int
    completion_lane_index: int
    completion_flow_ack_value: int
    receiver_ready_value_id: str
    completion_status: Literal["bound", "blocked"]
    blocker_ids: tuple[str, ...]

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "completion_id": self.completion_id,
            "logical_route_edge_id": self.logical_route_edge_id,
            "phase": self.phase,
            "physical_row_ids": list(self.physical_row_ids),
            "physical_candidate_ids": list(self.physical_candidate_ids),
            "lane_count": self.lane_count,
            "completion_lane_index": self.completion_lane_index,
            "completion_flow_ack_value": self.completion_flow_ack_value,
            "receiver_ready_value_id": self.receiver_ready_value_id,
            "completion_status": self.completion_status,
            "blocker_ids": list(self.blocker_ids),
        }


@dataclass(frozen=True)
class RouteComponentPlacementRecord:
    """PE-major placement for one candidate route COPY row."""

    schema_version: str
    placement_id: str
    candidate_id: str
    physical_row_plan_id: str
    logical_route_edge_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    source_pe: str
    destination_pe: str
    pe_index: int
    source_physical_local_pc: int
    pe_local_pc: int
    inst_per_pe: int
    component_row_index: int
    component_byte_offset: int
    component_name: Literal["insts_file.bin"]
    record_size_bytes: int
    layout_epoch: str
    layout_plan_sha256: str
    reserved_row_policy_id: str
    overwrite_policy: Literal["reserved_slot_only"]
    overwritten_row_ids: tuple[str, ...]
    placement_status: Literal["placed_candidate", "blocked"]
    component_integration_scope: Literal["route_rows_only"]
    component_integration_status: Literal["not_integrated"]
    micc_coherence_scope: Literal["route_rows_only"]
    micc_coherence_status: Literal["not_integrated"]
    payload_manifest_status: Literal["route_candidate_manifest_bound"]
    runtime_ready: bool
    uploadable: bool
    blocker_ids: tuple[str, ...]

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "placement_id": self.placement_id,
            "candidate_id": self.candidate_id,
            "physical_row_plan_id": self.physical_row_plan_id,
            "logical_route_edge_id": self.logical_route_edge_id,
            "phase": self.phase,
            "source_pe": self.source_pe,
            "destination_pe": self.destination_pe,
            "pe_index": self.pe_index,
            "source_physical_local_pc": self.source_physical_local_pc,
            "pe_local_pc": self.pe_local_pc,
            "inst_per_pe": self.inst_per_pe,
            "component_row_index": self.component_row_index,
            "component_byte_offset": self.component_byte_offset,
            "component_name": self.component_name,
            "record_size_bytes": self.record_size_bytes,
            "layout_epoch": self.layout_epoch,
            "layout_plan_sha256": self.layout_plan_sha256,
            "reserved_row_policy_id": self.reserved_row_policy_id,
            "overwrite_policy": self.overwrite_policy,
            "overwritten_row_ids": list(self.overwritten_row_ids),
            "placement_status": self.placement_status,
            "component_integration_scope": self.component_integration_scope,
            "component_integration_status": self.component_integration_status,
            "micc_coherence_scope": self.micc_coherence_scope,
            "micc_coherence_status": self.micc_coherence_status,
            "payload_manifest_status": self.payload_manifest_status,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "blocker_ids": list(self.blocker_ids),
        }


@dataclass(frozen=True)
class Log10MaxRouteComponentPlacementReport:
    """Phase-4B route placement report; no component mutation."""

    profile_id: str
    source_row_byte_report_id: str
    source_physical_row_plan_report_id: str
    source_flow_ack_final_policy_report_id: str
    layout_epoch: str
    layout_plan_sha256: str
    inst_per_pe: int
    insts_component_size_bytes: int
    placements: tuple[RouteComponentPlacementRecord, ...]
    lane_group_completions: tuple[RouteLaneGroupCompletion, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def uploadable(self) -> bool:
        return False

    @property
    def route_component_integrated_claim(self) -> bool:
        return False

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.placements:
            blockers.append("log10max_route_component_byte_offset_missing")
        for placement in self.placements:
            blockers.extend(placement.blocker_ids)
        for completion in self.lane_group_completions:
            blockers.extend(completion.blocker_ids)
        blockers.append(LOG10MAX_ROUTE_COMPONENT_INTEGRATION_MISSING)
        return tuple(dict.fromkeys(blockers))

    def summary(self) -> dict[str, object]:
        phase_counts: dict[str, int] = {}
        pe_counts: dict[str, int] = {}
        placement_counts: dict[str, int] = {}
        component_counts: dict[str, int] = {}
        micc_counts: dict[str, int] = {}
        manifest_counts: dict[str, int] = {}
        offsets: set[int] = set()
        duplicate_offset_count = 0
        overwritten_row_count = 0
        runtime_ready_claim_count = 0
        uploadable_claim_count = 0
        for placement in self.placements:
            phase_counts[placement.phase] = phase_counts.get(placement.phase, 0) + 1
            pe_counts[placement.source_pe] = pe_counts.get(placement.source_pe, 0) + 1
            placement_counts[placement.placement_status] = (
                placement_counts.get(placement.placement_status, 0) + 1
            )
            component_counts[placement.component_integration_status] = (
                component_counts.get(placement.component_integration_status, 0) + 1
            )
            micc_counts[placement.micc_coherence_status] = (
                micc_counts.get(placement.micc_coherence_status, 0) + 1
            )
            manifest_counts[placement.payload_manifest_status] = (
                manifest_counts.get(placement.payload_manifest_status, 0) + 1
            )
            if placement.component_byte_offset in offsets:
                duplicate_offset_count += 1
            offsets.add(placement.component_byte_offset)
            overwritten_row_count += len(placement.overwritten_row_ids)
            if placement.runtime_ready:
                runtime_ready_claim_count += 1
            if placement.uploadable:
                uploadable_claim_count += 1
        completion_counts: dict[str, int] = {}
        for completion in self.lane_group_completions:
            completion_counts[completion.completion_status] = (
                completion_counts.get(completion.completion_status, 0) + 1
            )
        return {
            "profile_id": self.profile_id,
            "source_row_byte_report_id": self.source_row_byte_report_id,
            "source_physical_row_plan_report_id": (
                self.source_physical_row_plan_report_id
            ),
            "source_flow_ack_final_policy_report_id": (
                self.source_flow_ack_final_policy_report_id
            ),
            "layout_epoch": self.layout_epoch,
            "layout_plan_sha256": self.layout_plan_sha256,
            "inst_per_pe": self.inst_per_pe,
            "insts_component_size_bytes": self.insts_component_size_bytes,
            "placement_count": len(self.placements),
            "lane_group_completion_count": len(self.lane_group_completions),
            "phase_counts": dict(sorted(phase_counts.items())),
            "pe_counts": dict(sorted(pe_counts.items())),
            "placement_status_counts": dict(sorted(placement_counts.items())),
            "component_integration_status_counts": dict(sorted(component_counts.items())),
            "micc_coherence_status_counts": dict(sorted(micc_counts.items())),
            "payload_manifest_status_counts": dict(sorted(manifest_counts.items())),
            "lane_group_completion_status_counts": dict(sorted(completion_counts.items())),
            "duplicate_component_byte_offset_count": duplicate_offset_count,
            "overwritten_row_count": overwritten_row_count,
            "runtime_ready_claim_count": runtime_ready_claim_count,
            "uploadable_claim_count": uploadable_claim_count,
            "route_component_integrated_claim": self.route_component_integrated_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "blocker_ids": list(self.blocker_ids),
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_route_component_placement_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "route_component_integrated_claim": self.route_component_integrated_claim,
            "blocker_ids": list(self.blocker_ids),
            "placements": [placement.to_plan() for placement in self.placements],
            "lane_group_completions": [
                completion.to_plan() for completion in self.lane_group_completions
            ],
            "payload_manifest_entries": [],
            "layering_policy": (
                "Phase 4B binds route row component offsets against a layout "
                "epoch and reserved-slot policy. It does not mutate CBUF/MICC "
                "components, does not enter operator payload manifests, and "
                "does not aggregate runtime_ready."
            ),
        }


@dataclass(frozen=True)
class RouteComponentIntegrationRecord:
    """Route-scope component candidate entry copied from candidate bytes."""

    schema_version: str
    integration_id: str
    placement_id: str
    candidate_id: str
    physical_row_plan_id: str
    logical_route_edge_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    component_name: Literal["insts_file.bin"]
    component_byte_offset: int
    component_row_index: int
    raw_inst_t_row_bytes_hex: str
    raw_inst_t_row_bytes_sha256: str
    copied_from_candidate_sha256: str
    byte_count: int
    overwrite_policy: Literal["reserved_slot_only"]
    overwritten_row_ids: tuple[str, ...]
    integration_scope: Literal["route_rows_only"]
    integration_status: Literal["route_slice_integrated_candidate", "blocked"]
    decode_roundtrip_status: Literal["candidate_route_decode_roundtrip"]
    micc_coherence_scope: Literal["route_rows_only"]
    micc_coherence_status: Literal["route_slice_candidate_coherent"]
    payload_manifest_status: Literal["route_candidate_manifest_bound"]
    operator_manifest_bound: bool
    runtime_ready: bool
    uploadable: bool
    blocker_ids: tuple[str, ...]

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "integration_id": self.integration_id,
            "placement_id": self.placement_id,
            "candidate_id": self.candidate_id,
            "physical_row_plan_id": self.physical_row_plan_id,
            "logical_route_edge_id": self.logical_route_edge_id,
            "phase": self.phase,
            "component_name": self.component_name,
            "component_byte_offset": self.component_byte_offset,
            "component_row_index": self.component_row_index,
            "raw_inst_t_row_bytes_hex": self.raw_inst_t_row_bytes_hex,
            "raw_inst_t_row_bytes_sha256": self.raw_inst_t_row_bytes_sha256,
            "copied_from_candidate_sha256": self.copied_from_candidate_sha256,
            "byte_count": self.byte_count,
            "overwrite_policy": self.overwrite_policy,
            "overwritten_row_ids": list(self.overwritten_row_ids),
            "integration_scope": self.integration_scope,
            "integration_status": self.integration_status,
            "decode_roundtrip_status": self.decode_roundtrip_status,
            "micc_coherence_scope": self.micc_coherence_scope,
            "micc_coherence_status": self.micc_coherence_status,
            "payload_manifest_status": self.payload_manifest_status,
            "operator_manifest_bound": self.operator_manifest_bound,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "blocker_ids": list(self.blocker_ids),
        }


@dataclass(frozen=True)
class Log10MaxRouteComponentIntegrationReport:
    """Phase-4C route-scope component candidate report.

    This report copies already-packed candidate row bytes into a route-scope
    component candidate map.  It deliberately does not write CBUF/MICC files
    and does not update the operator payload manifest.
    """

    profile_id: str
    source_placement_report_id: str
    source_row_byte_report_id: str
    layout_epoch: str
    layout_plan_sha256: str
    route_slice_sha256: str
    route_slice_row_count: int
    component_name: Literal["insts_file.bin"]
    integration_records: tuple[RouteComponentIntegrationRecord, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def uploadable(self) -> bool:
        return False

    @property
    def route_component_integrated_claim(self) -> bool:
        return True

    @property
    def component_integration_scope(self) -> Literal["route_rows_only"]:
        return "route_rows_only"

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.integration_records:
            blockers.append(LOG10MAX_ROUTE_COMPONENT_INTEGRATION_MISSING)
        for record in self.integration_records:
            blockers.extend(record.blocker_ids)
        blockers.extend(
            (
                LOG10MAX_OPERATOR_MANIFEST_MISSING,
                LOG10MAX_OPERATOR_RUNTIME_READY_GATE_NOT_AGGREGATED,
            )
        )
        return tuple(dict.fromkeys(blockers))

    def summary(self) -> dict[str, object]:
        phase_counts: dict[str, int] = {}
        integration_counts: dict[str, int] = {}
        micc_counts: dict[str, int] = {}
        manifest_counts: dict[str, int] = {}
        offsets: set[int] = set()
        duplicate_offset_count = 0
        overwritten_row_count = 0
        operator_manifest_bound_count = 0
        runtime_ready_claim_count = 0
        uploadable_claim_count = 0
        byte_count = 0
        for record in self.integration_records:
            phase_counts[record.phase] = phase_counts.get(record.phase, 0) + 1
            integration_counts[record.integration_status] = (
                integration_counts.get(record.integration_status, 0) + 1
            )
            micc_counts[record.micc_coherence_status] = (
                micc_counts.get(record.micc_coherence_status, 0) + 1
            )
            manifest_counts[record.payload_manifest_status] = (
                manifest_counts.get(record.payload_manifest_status, 0) + 1
            )
            if record.component_byte_offset in offsets:
                duplicate_offset_count += 1
            offsets.add(record.component_byte_offset)
            overwritten_row_count += len(record.overwritten_row_ids)
            if record.operator_manifest_bound:
                operator_manifest_bound_count += 1
            if record.runtime_ready:
                runtime_ready_claim_count += 1
            if record.uploadable:
                uploadable_claim_count += 1
            byte_count += record.byte_count
        return {
            "profile_id": self.profile_id,
            "source_placement_report_id": self.source_placement_report_id,
            "source_row_byte_report_id": self.source_row_byte_report_id,
            "layout_epoch": self.layout_epoch,
            "layout_plan_sha256": self.layout_plan_sha256,
            "route_slice_sha256": self.route_slice_sha256,
            "route_slice_row_count": self.route_slice_row_count,
            "component_name": self.component_name,
            "integration_count": len(self.integration_records),
            "phase_counts": dict(sorted(phase_counts.items())),
            "integration_status_counts": dict(sorted(integration_counts.items())),
            "micc_coherence_status_counts": dict(sorted(micc_counts.items())),
            "payload_manifest_status_counts": dict(sorted(manifest_counts.items())),
            "duplicate_component_byte_offset_count": duplicate_offset_count,
            "overwritten_row_count": overwritten_row_count,
            "operator_manifest_bound_count": operator_manifest_bound_count,
            "runtime_ready_claim_count": runtime_ready_claim_count,
            "uploadable_claim_count": uploadable_claim_count,
            "raw_inst_t_byte_count": byte_count,
            "record_size_bytes": INST_RECORD_SIZE_BYTES,
            "component_integration_scope": self.component_integration_scope,
            "route_component_integrated_claim": self.route_component_integrated_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "blocker_ids": list(self.blocker_ids),
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_route_component_integration_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "component_integration_scope": self.component_integration_scope,
            "route_component_integrated_claim": self.route_component_integrated_claim,
            "blocker_ids": list(self.blocker_ids),
            "integration_records": [
                record.to_plan() for record in self.integration_records
            ],
            "operator_payload_manifest_entries": [],
            "layering_policy": (
                "Phase 4C integrates route COPY rows only into a report-local "
                "component candidate map by copying candidate bytes. It does "
                "not write CBUF/MICC files, does not bind the operator payload "
                "manifest, and does not aggregate runtime_ready."
            ),
        }


def build_log10max_route_component_placement_report(
    row_byte_report: RouteInstRowByteCandidateReport | None = None,
    physical_row_report: RoutePhysicalRowPlanReport | None = None,
    flow_ack_final_report: Log10MaxRouteFlowAckFinalPolicyReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_route_component_placement_v1",
) -> Log10MaxRouteComponentPlacementReport:
    """Bind route COPY candidates to PE-major insts component offsets."""

    physical_report = physical_row_report or build_log10max_route_physical_row_plan_report()
    row_report = row_byte_report or build_log10max_route_inst_row_byte_candidate_report()
    final_flow_ack = flow_ack_final_report or build_log10max_route_flow_ack_final_policy_report()
    physical_by_row = {row.row_plan_id: row for row in physical_report.physical_rows}
    final_by_row = {
        binding.physical_row_plan_id: binding for binding in final_flow_ack.bindings
    }
    layout_plan_sha256 = _layout_plan_sha256(physical_report.physical_rows)
    local_pc_by_pe: dict[str, int] = {}
    placements: list[RouteComponentPlacementRecord] = []
    for candidate in row_report.candidates:
        physical_row = physical_by_row[candidate.physical_row_plan_id]
        component_local_pc = local_pc_by_pe.get(physical_row.src_pe, 0)
        local_pc_by_pe[physical_row.src_pe] = component_local_pc + 1
        placements.append(
            _placement_for_candidate(
                candidate=candidate,
                physical_row=physical_row,
                flow_ack_binding=final_by_row[candidate.physical_row_plan_id],
                layout_plan_sha256=layout_plan_sha256,
                component_local_pc=component_local_pc,
            )
        )
    lane_group_completions = _lane_group_completions(
        row_report.candidates,
        final_by_row,
    )
    return Log10MaxRouteComponentPlacementReport(
        profile_id=profile_id,
        source_row_byte_report_id=row_report.profile_id,
        source_physical_row_plan_report_id=physical_report.profile_id,
        source_flow_ack_final_policy_report_id=final_flow_ack.profile_id,
        layout_epoch=ROUTE_LAYOUT_EPOCH,
        layout_plan_sha256=layout_plan_sha256,
        inst_per_pe=MAX_INST_AMOUNT_PER_PE,
        insts_component_size_bytes=(
            PE_MESH_X * PE_MESH_Y * MAX_INST_AMOUNT_PER_PE * INST_RECORD_SIZE_BYTES
        ),
        placements=tuple(placements),
        lane_group_completions=lane_group_completions,
    )


def summarize_log10max_route_component_placement_report(
    report: Log10MaxRouteComponentPlacementReport,
) -> dict[str, object]:
    return report.summary()


def build_log10max_route_component_integration_report(
    placement_report: Log10MaxRouteComponentPlacementReport | None = None,
    row_byte_report: RouteInstRowByteCandidateReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_route_component_integration_v1",
) -> Log10MaxRouteComponentIntegrationReport:
    """Copy candidate route rows into a route-scope component candidate map."""

    row_report = row_byte_report or build_log10max_route_inst_row_byte_candidate_report()
    placement = placement_report or build_log10max_route_component_placement_report(
        row_byte_report=row_report
    )
    candidates_by_id = {candidate.candidate_id: candidate for candidate in row_report.candidates}
    records = tuple(
        _integration_record_for_placement(
            placement_record=placement_record,
            candidate=candidates_by_id[placement_record.candidate_id],
        )
        for placement_record in placement.placements
    )
    route_slice_sha256 = _route_slice_sha256(records)
    return Log10MaxRouteComponentIntegrationReport(
        profile_id=profile_id,
        source_placement_report_id=placement.profile_id,
        source_row_byte_report_id=row_report.profile_id,
        layout_epoch=placement.layout_epoch,
        layout_plan_sha256=placement.layout_plan_sha256,
        route_slice_sha256=route_slice_sha256,
        route_slice_row_count=len(records),
        component_name=ROUTE_COMPONENT_NAME,
        integration_records=records,
    )


def summarize_log10max_route_component_integration_report(
    report: Log10MaxRouteComponentIntegrationReport,
) -> dict[str, object]:
    return report.summary()


def _placement_for_candidate(
    *,
    candidate: RouteInstRowByteCandidateRecord,
    physical_row: RoutePhysicalRowPlan,
    flow_ack_binding: RouteFlowAckFinalPolicyBinding,
    layout_plan_sha256: str,
    component_local_pc: int,
) -> RouteComponentPlacementRecord:
    if candidate.physical_row_plan_id != physical_row.row_plan_id:
        raise ValueError("route candidate and physical row mismatch")
    if flow_ack_binding.physical_row_plan_id != physical_row.row_plan_id:
        raise ValueError("flow_ack binding and physical row mismatch")
    if flow_ack_binding.final_policy_status != "final_bound":
        raise ValueError(f"flow_ack final policy is not bound: {flow_ack_binding}")
    if physical_row.physical_local_pc is None:
        raise ValueError(f"physical local PC missing: {physical_row.row_plan_id}")
    source_pe = physical_row.src_pe
    pe_index = _pe_index_from_label(source_pe)
    pe_local_pc = component_local_pc
    component_row_index = pe_index * MAX_INST_AMOUNT_PER_PE + pe_local_pc
    component_byte_offset = component_row_index * INST_RECORD_SIZE_BYTES
    if component_byte_offset < 0:
        raise ValueError(f"negative route component offset: {physical_row.row_plan_id}")
    blocker_ids = (
        LOG10MAX_ROUTE_FULL_LAYOUT_EPOCH_NOT_FROZEN,
        LOG10MAX_ROUTE_COMPONENT_OVERWRITE_CHECK_SCOPED,
        LOG10MAX_ROUTE_COMPONENT_INTEGRATION_MISSING,
    )
    return RouteComponentPlacementRecord(
        schema_version="1",
        placement_id=f"route_component_placement:{physical_row.row_plan_id}",
        candidate_id=candidate.candidate_id,
        physical_row_plan_id=physical_row.row_plan_id,
        logical_route_edge_id=physical_row.logical_route_edge_id,
        phase=physical_row.phase,
        source_pe=source_pe,
        destination_pe=physical_row.dst_pe,
        pe_index=pe_index,
        source_physical_local_pc=physical_row.physical_local_pc,
        pe_local_pc=pe_local_pc,
        inst_per_pe=MAX_INST_AMOUNT_PER_PE,
        component_row_index=component_row_index,
        component_byte_offset=component_byte_offset,
        component_name=ROUTE_COMPONENT_NAME,
        record_size_bytes=INST_RECORD_SIZE_BYTES,
        layout_epoch=ROUTE_LAYOUT_EPOCH,
        layout_plan_sha256=layout_plan_sha256,
        reserved_row_policy_id=ROUTE_RESERVED_ROW_POLICY_ID,
        overwrite_policy="reserved_slot_only",
        overwritten_row_ids=(),
        placement_status="placed_candidate",
        component_integration_scope="route_rows_only",
        component_integration_status="not_integrated",
        micc_coherence_scope="route_rows_only",
        micc_coherence_status="not_integrated",
        payload_manifest_status="route_candidate_manifest_bound",
        runtime_ready=False,
        uploadable=False,
        blocker_ids=blocker_ids,
    )


def _integration_record_for_placement(
    *,
    placement_record: RouteComponentPlacementRecord,
    candidate: RouteInstRowByteCandidateRecord,
) -> RouteComponentIntegrationRecord:
    row_bytes = bytes.fromhex(candidate.raw_inst_t_row_bytes_hex)
    copied_sha = hashlib.sha256(row_bytes).hexdigest()
    if copied_sha != candidate.raw_inst_t_row_bytes_sha256:
        raise ValueError(f"candidate byte sha mismatch: {candidate.candidate_id}")
    if placement_record.candidate_id != candidate.candidate_id:
        raise ValueError("placement and candidate mismatch")
    if placement_record.overwritten_row_ids:
        raise ValueError(f"route integration would overwrite rows: {placement_record}")
    return RouteComponentIntegrationRecord(
        schema_version="1",
        integration_id=f"route_component_integration:{placement_record.physical_row_plan_id}",
        placement_id=placement_record.placement_id,
        candidate_id=candidate.candidate_id,
        physical_row_plan_id=placement_record.physical_row_plan_id,
        logical_route_edge_id=placement_record.logical_route_edge_id,
        phase=placement_record.phase,
        component_name=placement_record.component_name,
        component_byte_offset=placement_record.component_byte_offset,
        component_row_index=placement_record.component_row_index,
        raw_inst_t_row_bytes_hex=candidate.raw_inst_t_row_bytes_hex,
        raw_inst_t_row_bytes_sha256=candidate.raw_inst_t_row_bytes_sha256,
        copied_from_candidate_sha256=copied_sha,
        byte_count=len(row_bytes),
        overwrite_policy=placement_record.overwrite_policy,
        overwritten_row_ids=placement_record.overwritten_row_ids,
        integration_scope="route_rows_only",
        integration_status="route_slice_integrated_candidate",
        decode_roundtrip_status=candidate.decode_roundtrip_status,
        micc_coherence_scope="route_rows_only",
        micc_coherence_status="route_slice_candidate_coherent",
        payload_manifest_status="route_candidate_manifest_bound",
        operator_manifest_bound=False,
        runtime_ready=False,
        uploadable=False,
        blocker_ids=(),
    )


def _lane_group_completions(
    candidates: tuple[RouteInstRowByteCandidateRecord, ...],
    final_by_row: Mapping[str, RouteFlowAckFinalPolicyBinding],
) -> tuple[RouteLaneGroupCompletion, ...]:
    rows_by_edge: dict[str, list[RouteInstRowByteCandidateRecord]] = {}
    for candidate in candidates:
        rows_by_edge.setdefault(candidate.logical_route_edge_id, []).append(candidate)
    completions: list[RouteLaneGroupCompletion] = []
    for edge_id, rows in sorted(rows_by_edge.items()):
        rows_sorted = tuple(sorted(rows, key=lambda row: row.physical_lane_index))
        blockers: list[str] = []
        lane_indexes = tuple(row.physical_lane_index for row in rows_sorted)
        if lane_indexes != (0, 1, 2, 3):
            blockers.append("log10max_route_lane_group_incomplete")
        completion_row = rows_sorted[-1]
        completion_binding = final_by_row[completion_row.physical_row_plan_id]
        if completion_binding.flow_ack != 1:
            blockers.append("log10max_route_lane_group_completion_flow_ack_missing")
        status: Literal["bound", "blocked"] = "blocked" if blockers else "bound"
        completions.append(
            RouteLaneGroupCompletion(
                schema_version="1",
                completion_id=f"route_lane_group_completion:{edge_id}",
                logical_route_edge_id=edge_id,
                phase=str(completion_row.layout_provenance["phase"]),  # type: ignore[arg-type]
                physical_row_ids=tuple(row.physical_row_plan_id for row in rows_sorted),
                physical_candidate_ids=tuple(row.candidate_id for row in rows_sorted),
                lane_count=len(rows_sorted),
                completion_lane_index=completion_row.physical_lane_index,
                completion_flow_ack_value=completion_binding.flow_ack,
                receiver_ready_value_id=f"globalmax_route_ready:{edge_id}",
                completion_status=status,
                blocker_ids=tuple(blockers),
            )
        )
    return tuple(completions)


def _layout_plan_sha256(rows: tuple[RoutePhysicalRowPlan, ...]) -> str:
    payload = [
        {
            "row_plan_id": row.row_plan_id,
            "logical_route_edge_id": row.logical_route_edge_id,
            "src_pe": row.src_pe,
            "dst_pe": row.dst_pe,
            "phase": row.phase,
            "lane_index": row.lane_index,
            "physical_local_pc": row.physical_local_pc,
            "dst_block_idx": row.dst_block_idx,
        }
        for row in rows
    ]
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def _route_slice_sha256(records: tuple[RouteComponentIntegrationRecord, ...]) -> str:
    payload = [
        {
            "component_byte_offset": record.component_byte_offset,
            "sha256": record.raw_inst_t_row_bytes_sha256,
            "byte_count": record.byte_count,
        }
        for record in sorted(records, key=lambda item: item.component_byte_offset)
    ]
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


def _pe_index_from_label(pe: str) -> int:
    if not pe.startswith("PE(") or not pe.endswith(")"):
        raise ValueError(f"unsupported PE label: {pe!r}")
    row_text, col_text = pe[3:-1].split(",", 1)
    row = int(row_text)
    col = int(col_text)
    if not (0 <= row < PE_MESH_Y and 0 <= col < PE_MESH_X):
        raise ValueError(f"PE label out of range: {pe!r}")
    return row * PE_MESH_X + col


__all__ = [
    "LOG10MAX_ROUTE_COMPONENT_OVERWRITE_CHECK_SCOPED",
    "LOG10MAX_ROUTE_FULL_LAYOUT_EPOCH_NOT_FROZEN",
    "ROUTE_COMPONENT_INTEGRATION_STATUS",
    "ROUTE_COMPONENT_CANDIDATE_INTEGRATION_STATUS",
    "ROUTE_COMPONENT_NAME",
    "ROUTE_COMPONENT_PLACEMENT_STATUS",
    "ROUTE_LAYOUT_EPOCH",
    "ROUTE_RESERVED_ROW_POLICY_ID",
    "Log10MaxRouteComponentIntegrationReport",
    "Log10MaxRouteComponentPlacementReport",
    "RouteComponentIntegrationRecord",
    "RouteComponentPlacementRecord",
    "RouteLaneGroupCompletion",
    "build_log10max_route_component_integration_report",
    "build_log10max_route_component_placement_report",
    "summarize_log10max_route_component_integration_report",
    "summarize_log10max_route_component_placement_report",
]
