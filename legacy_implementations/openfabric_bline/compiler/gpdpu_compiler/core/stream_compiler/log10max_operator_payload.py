"""Operator-level log10max payload slice accounting.

Phase 5A lifts the existing route-scope component integration into an
operator-level instruction slice set.  It deliberately does not assemble a full
operator component, does not bind an operator payload manifest, and does not
aggregate runtime readiness.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Literal

from .log10max_route_component_placement import (
    Log10MaxRouteComponentIntegrationReport,
    build_log10max_route_component_integration_report,
)
from .log10max_ring_fmax_update_slice import (
    RingFmaxUpdateSliceReport,
    build_log10max_ring_fmax_update_slice_report,
)


SliceKind = Literal[
    "logspec_elementwise",
    "local_reduce",
    "route_copy",
    "ring_fmax_update",
    "max_with_floor",
    "postprocess_scale",
    "store",
]
SliceStatus = Literal["present", "blocked", "folded", "not_applicable"]

EXPECTED_LOG10MAX_ROW_FAMILIES: tuple[str, ...] = (
    "logspec_elementwise",
    "local_reduce",
    "route_copy",
    "ring_fmax_update",
    "max_with_floor",
    "postprocess_scale",
    "store",
)

EXPECTED_LOG10MAX_SEMANTIC_OPS: tuple[str, ...] = (
    "clamp_min",
    "log2",
    "mul_log10_2",
    "local_reduce_max",
    "route_globalmax_copy",
    "max_update_global_max",
    "global_max_minus_8",
    "max_with_floor",
    "add_scalar_4",
    "mul_scalar_0_25",
    "store_output",
)

SEMANTIC_OPS_BY_SLICE: dict[str, tuple[str, ...]] = {
    "logspec_elementwise": ("clamp_min", "log2", "mul_log10_2"),
    "local_reduce": ("local_reduce_max",),
    "route_copy": ("route_globalmax_copy",),
    "ring_fmax_update": ("max_update_global_max",),
    "max_with_floor": ("global_max_minus_8", "max_with_floor"),
    "postprocess_scale": ("add_scalar_4", "mul_scalar_0_25"),
    "store": ("store_output",),
}

LOG10MAX_OPERATOR_SLICE_SET_PARTIAL = "log10max_operator_instruction_slice_set_partial"
LOG10MAX_OPERATOR_INSTS_COMPONENT_PARTIAL = (
    "log10max_operator_insts_component_partial"
)
LOG10MAX_OPERATOR_CONTROL_COHERENCE_BLOCKED = (
    "log10max_operator_control_coherence_blocked"
)
LOG10MAX_OPERATOR_PAYLOAD_MANIFEST_BLOCKED = (
    "log10max_operator_payload_manifest_blocked"
)

REQUIRED_LOG10MAX_PAYLOAD_FILE_ROLES: tuple[str, ...] = (
    "insts_component",
    "exeblock_component",
    "instance_component",
    "cbuf_file",
    "tasks_component",
    "subtasks_component",
    "micc_file",
    "runtime_asset",
    "reference_asset",
    "operator_metadata",
    "numerical_contract",
)


@dataclass(frozen=True)
class OperatorInstructionSlice:
    """One operator-level row-family slice."""

    schema_version: str
    slice_id: str
    operator: Literal["log10max"]
    slice_kind: SliceKind
    slice_status: SliceStatus
    source_report_id: str
    covered_semantic_ops: tuple[str, ...]
    folded_into_slice_id: str | None
    folded_evidence_id: str | None
    integration_scope: Literal[
        "route_rows_only",
        "row_family_only",
        "full_operator_slice",
    ]
    row_count: int
    component_name: Literal["insts_file.bin"]
    row_ids: tuple[str, ...]
    component_byte_offsets: tuple[int, ...]
    row_sha256s: tuple[str, ...]
    slice_sha256: str | None
    layout_epoch: str | None
    layout_plan_sha256: str | None
    placement_status: Literal["placed", "blocked"]
    byte_status: Literal["copied_from_candidate", "blocked"]
    no_overwrite_status: Literal["pass", "blocked"]
    decode_roundtrip_status: Literal["pass", "blocked"]
    provenance_status: Literal["pass", "blocked"]
    blocker_ids: tuple[str, ...]

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "slice_id": self.slice_id,
            "operator": self.operator,
            "slice_kind": self.slice_kind,
            "slice_status": self.slice_status,
            "source_report_id": self.source_report_id,
            "covered_semantic_ops": list(self.covered_semantic_ops),
            "folded_into_slice_id": self.folded_into_slice_id,
            "folded_evidence_id": self.folded_evidence_id,
            "integration_scope": self.integration_scope,
            "row_count": self.row_count,
            "component_name": self.component_name,
            "row_ids": list(self.row_ids),
            "component_byte_offsets": list(self.component_byte_offsets),
            "row_sha256s": list(self.row_sha256s),
            "slice_sha256": self.slice_sha256,
            "layout_epoch": self.layout_epoch,
            "layout_plan_sha256": self.layout_plan_sha256,
            "placement_status": self.placement_status,
            "byte_status": self.byte_status,
            "no_overwrite_status": self.no_overwrite_status,
            "decode_roundtrip_status": self.decode_roundtrip_status,
            "provenance_status": self.provenance_status,
            "blocker_ids": list(self.blocker_ids),
        }


@dataclass(frozen=True)
class OperatorInstructionSliceSet:
    """Phase-5A instruction slice set for log10max."""

    schema_version: str
    slice_set_id: str
    operator: Literal["log10max"]
    source_route_component_integration_report_id: str
    expected_row_families: tuple[str, ...]
    present_row_families: tuple[str, ...]
    folded_row_families: tuple[str, ...]
    missing_row_families: tuple[str, ...]
    blocked_row_families: tuple[str, ...]
    covered_semantic_ops: tuple[str, ...]
    missing_semantic_ops: tuple[str, ...]
    duplicate_semantic_ops: tuple[str, ...]
    slice_set_status: Literal["complete", "partial", "blocked"]
    layout_epoch: str | None
    layout_plan_sha256: str | None
    slices: tuple[OperatorInstructionSlice, ...]
    blocker_ids: tuple[str, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def uploadable(self) -> bool:
        return False

    def summary(self) -> dict[str, object]:
        status_counts: dict[str, int] = {}
        byte_counts: dict[str, int] = {}
        placement_counts: dict[str, int] = {}
        row_counts_by_family: dict[str, int] = {}
        for item in self.slices:
            status_counts[item.slice_status] = status_counts.get(item.slice_status, 0) + 1
            byte_counts[item.byte_status] = byte_counts.get(item.byte_status, 0) + 1
            placement_counts[item.placement_status] = (
                placement_counts.get(item.placement_status, 0) + 1
            )
            row_counts_by_family[item.slice_kind] = item.row_count
        return {
            "slice_set_id": self.slice_set_id,
            "operator": self.operator,
            "source_route_component_integration_report_id": (
                self.source_route_component_integration_report_id
            ),
            "expected_row_families": list(self.expected_row_families),
            "present_row_families": list(self.present_row_families),
            "folded_row_families": list(self.folded_row_families),
            "missing_row_families": list(self.missing_row_families),
            "blocked_row_families": list(self.blocked_row_families),
            "covered_semantic_ops": list(self.covered_semantic_ops),
            "missing_semantic_ops": list(self.missing_semantic_ops),
            "duplicate_semantic_ops": list(self.duplicate_semantic_ops),
            "slice_set_status": self.slice_set_status,
            "layout_epoch": self.layout_epoch,
            "layout_plan_sha256": self.layout_plan_sha256,
            "slice_count": len(self.slices),
            "slice_status_counts": dict(sorted(status_counts.items())),
            "byte_status_counts": dict(sorted(byte_counts.items())),
            "placement_status_counts": dict(sorted(placement_counts.items())),
            "row_counts_by_family": dict(sorted(row_counts_by_family.items())),
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_kind": "log10max_operator_instruction_slice_set",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "blocker_ids": list(self.blocker_ids),
            "slices": [item.to_plan() for item in self.slices],
            "layering_policy": (
                "Phase 5A promotes route_copy to one operator slice and keeps "
                "all non-route row families explicit blockers. It does not "
                "assemble a full operator component or bind an operator "
                "payload manifest."
            ),
        }


@dataclass(frozen=True)
class OperatorInstsComponentCandidate:
    """Report-local operator insts component candidate.

    With the current slice set this remains partial: route rows are represented,
    while non-route row families are explicit blockers.
    """

    schema_version: str
    candidate_id: str
    operator: Literal["log10max"]
    source_slice_set_id: str
    component_name: Literal["insts_file.bin"]
    layout_epoch: str | None
    layout_plan_sha256: str | None
    component_size_bytes: int | None
    integrated_row_count: int
    expected_row_families: tuple[str, ...]
    present_row_families: tuple[str, ...]
    folded_row_families: tuple[str, ...]
    missing_row_families: tuple[str, ...]
    component_sha256: str | None
    diagnostic_partial_component_sha256: str | None
    active_row_count: int
    reserved_row_count: int
    zero_padding_row_count: int
    unowned_nonzero_row_count: int
    no_overwrite_status: Literal["pass", "blocked"]
    decode_roundtrip_status: Literal["pass", "blocked"]
    provenance_status: Literal["pass", "blocked"]
    micc_coherence_status: Literal["not_checked", "pass", "blocked"]
    component_status: Literal[
        "full_operator_candidate",
        "partial_operator_candidate",
        "blocked",
    ]
    runtime_ready: bool
    uploadable: bool
    blocker_ids: tuple[str, ...]

    def summary(self) -> dict[str, object]:
        return {
            "candidate_id": self.candidate_id,
            "operator": self.operator,
            "source_slice_set_id": self.source_slice_set_id,
            "component_name": self.component_name,
            "layout_epoch": self.layout_epoch,
            "layout_plan_sha256": self.layout_plan_sha256,
            "component_size_bytes": self.component_size_bytes,
            "integrated_row_count": self.integrated_row_count,
            "expected_row_families": list(self.expected_row_families),
            "present_row_families": list(self.present_row_families),
            "folded_row_families": list(self.folded_row_families),
            "missing_row_families": list(self.missing_row_families),
            "component_sha256": self.component_sha256,
            "diagnostic_partial_component_sha256": (
                self.diagnostic_partial_component_sha256
            ),
            "active_row_count": self.active_row_count,
            "reserved_row_count": self.reserved_row_count,
            "zero_padding_row_count": self.zero_padding_row_count,
            "unowned_nonzero_row_count": self.unowned_nonzero_row_count,
            "no_overwrite_status": self.no_overwrite_status,
            "decode_roundtrip_status": self.decode_roundtrip_status,
            "provenance_status": self.provenance_status,
            "micc_coherence_status": self.micc_coherence_status,
            "component_status": self.component_status,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "blocker_ids": list(self.blocker_ids),
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_kind": "log10max_operator_insts_component_candidate",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "blocker_ids": list(self.blocker_ids),
            "operator_payload_manifest_entries": [],
            "layering_policy": (
                "Phase 5B reports a partial operator insts component candidate "
                "while any expected row family is missing. Partial candidates "
                "may have a diagnostic hash, but component_sha256 is reserved "
                "for full operator candidates."
            ),
        }


@dataclass(frozen=True)
class OperatorControlCoherenceReport:
    """Phase-5C full-operator control coherence report.

    This is intentionally full-operator scoped.  Route-scope coherence can feed
    the report, but it cannot substitute for full CBUF/MICC control closure.
    """

    schema_version: str
    report_id: str
    operator: Literal["log10max"]
    coherence_scope: Literal["full_operator"]
    source_insts_component_candidate_id: str
    source_micc_candidate_id: str | None
    source_exeblock_component_id: str | None
    source_instance_component_id: str | None
    insts_component_status: Literal["pass", "blocked"]
    micc_candidate_status: Literal["pass", "blocked", "not_applicable"]
    exeblock_component_status: Literal["pass", "blocked", "not_applicable"]
    instance_component_status: Literal["pass", "blocked", "not_applicable"]
    stage_start_pc_status: Literal["pass", "blocked", "not_applicable"]
    stage_instruction_count_status: Literal["pass", "blocked", "not_applicable"]
    stage_pc_within_pe_local_inst_rows_status: Literal[
        "pass",
        "blocked",
        "not_applicable",
    ]
    active_exeblock_points_to_owned_rows_status: Literal[
        "pass",
        "blocked",
        "not_applicable",
    ]
    end_inst_boundary_status: Literal["pass", "blocked", "not_applicable"]
    successor_predecessor_status: Literal["pass", "blocked", "not_applicable"]
    root_reachability_status: Literal["pass", "blocked", "not_applicable"]
    task_subtask_stamp_status: Literal["pass", "blocked", "not_applicable"]
    instance_base_addr_status: Literal["pass", "blocked", "not_applicable"]
    coherence_status: Literal["pass", "blocked"]
    blocker_ids: tuple[str, ...]
    runtime_ready: bool
    uploadable: bool

    def summary(self) -> dict[str, object]:
        statuses = {
            "insts_component_status": self.insts_component_status,
            "micc_candidate_status": self.micc_candidate_status,
            "exeblock_component_status": self.exeblock_component_status,
            "instance_component_status": self.instance_component_status,
            "stage_start_pc_status": self.stage_start_pc_status,
            "stage_instruction_count_status": self.stage_instruction_count_status,
            "stage_pc_within_pe_local_inst_rows_status": (
                self.stage_pc_within_pe_local_inst_rows_status
            ),
            "active_exeblock_points_to_owned_rows_status": (
                self.active_exeblock_points_to_owned_rows_status
            ),
            "end_inst_boundary_status": self.end_inst_boundary_status,
            "successor_predecessor_status": self.successor_predecessor_status,
            "root_reachability_status": self.root_reachability_status,
            "task_subtask_stamp_status": self.task_subtask_stamp_status,
            "instance_base_addr_status": self.instance_base_addr_status,
        }
        return {
            "report_id": self.report_id,
            "operator": self.operator,
            "coherence_scope": self.coherence_scope,
            "source_insts_component_candidate_id": (
                self.source_insts_component_candidate_id
            ),
            "source_micc_candidate_id": self.source_micc_candidate_id,
            "source_exeblock_component_id": self.source_exeblock_component_id,
            "source_instance_component_id": self.source_instance_component_id,
            "coherence_status": self.coherence_status,
            "status_by_check": statuses,
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_kind": "log10max_operator_control_coherence_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "blocker_ids": list(self.blocker_ids),
            "layering_policy": (
                "Phase 5C is full-operator scoped and remains blocked while "
                "the insts component is partial or CBUF/MICC control components "
                "are missing. It does not replace the preintegration gate."
            ),
        }


@dataclass(frozen=True)
class OperatorPayloadManifestCandidate:
    """Phase-5D blocked operator payload manifest candidate."""

    schema_version: str
    manifest_id: str
    operator: Literal["log10max"]
    source_insts_component_candidate_id: str
    source_control_coherence_report_id: str
    required_file_roles: tuple[str, ...]
    present_file_roles: tuple[str, ...]
    missing_file_roles: tuple[str, ...]
    component_manifest_status: Literal[
        "blocked",
        "instruction_component_candidate",
        "dfu_component_candidate",
    ]
    operator_payload_manifest_status: Literal[
        "blocked",
        "operator_payload_candidate",
    ]
    readiness_claim: Literal[
        "blocked",
        "instruction_component_candidate",
        "dfu_component_candidate",
        "operator_payload_candidate",
        "runtime_ready_candidate",
    ]
    component_hashes: tuple[tuple[str, str], ...]
    diagnostic_hashes: tuple[tuple[str, str], ...]
    runtime_asset_status: Literal["present", "blocked"]
    simict_status: Literal["not_run", "loads", "executes"]
    numerical_status: Literal["not_checked", "checked"]
    blockers_by_layer: tuple[tuple[str, tuple[str, ...]], ...]
    blocker_ids: tuple[str, ...]
    runtime_ready: bool
    uploadable: bool

    def summary(self) -> dict[str, object]:
        return {
            "manifest_id": self.manifest_id,
            "operator": self.operator,
            "source_insts_component_candidate_id": (
                self.source_insts_component_candidate_id
            ),
            "source_control_coherence_report_id": (
                self.source_control_coherence_report_id
            ),
            "required_file_roles": list(self.required_file_roles),
            "present_file_roles": list(self.present_file_roles),
            "missing_file_roles": list(self.missing_file_roles),
            "component_manifest_status": self.component_manifest_status,
            "operator_payload_manifest_status": (
                self.operator_payload_manifest_status
            ),
            "readiness_claim": self.readiness_claim,
            "component_hashes": dict(self.component_hashes),
            "diagnostic_hashes": dict(self.diagnostic_hashes),
            "runtime_asset_status": self.runtime_asset_status,
            "simict_status": self.simict_status,
            "numerical_status": self.numerical_status,
            "blockers_by_layer": {
                layer: list(blockers)
                for layer, blockers in self.blockers_by_layer
            },
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "artifact_kind": "log10max_operator_payload_manifest_candidate",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "blocker_ids": list(self.blocker_ids),
            "layering_policy": (
                "Phase 5D may list operator payload blockers, but it cannot "
                "turn a partial insts component or diagnostic hash into an "
                "operator payload manifest. Only the preintegration gate may "
                "aggregate runtime_ready or uploadable."
            ),
        }


def build_log10max_operator_instruction_slice_set(
    route_report: Log10MaxRouteComponentIntegrationReport | None = None,
    fmax_update_report: RingFmaxUpdateSliceReport | None = None,
    *,
    slice_set_id: str = "operator_instruction_slice_set:log10max:v1",
) -> OperatorInstructionSliceSet:
    """Build the Phase-5A log10max instruction slice set."""

    route = route_report or build_log10max_route_component_integration_report()
    fmax = fmax_update_report or build_log10max_ring_fmax_update_slice_report()
    slices = [_route_copy_slice(route)]
    slices.append(_ring_fmax_update_slice(fmax))
    slices.extend(
        _blocked_slice(kind)
        for kind in EXPECTED_LOG10MAX_ROW_FAMILIES
        if kind not in {"route_copy", "ring_fmax_update"}
    )

    present = tuple(item.slice_kind for item in slices if item.slice_status == "present")
    folded = tuple(item.slice_kind for item in slices if item.slice_status == "folded")
    blocked = tuple(item.slice_kind for item in slices if item.slice_status == "blocked")
    missing = tuple(
        family
        for family in EXPECTED_LOG10MAX_ROW_FAMILIES
        if family not in present and family not in folded
    )
    covered = tuple(
        op
        for item in slices
        if item.slice_status in {"present", "folded"}
        for op in item.covered_semantic_ops
    )
    duplicates = _duplicates(covered)
    missing_semantic = tuple(
        op for op in EXPECTED_LOG10MAX_SEMANTIC_OPS if op not in set(covered)
    )
    blocker_ids = [LOG10MAX_OPERATOR_SLICE_SET_PARTIAL]
    blocker_ids.extend(f"log10max_operator_slice_{family}_missing" for family in missing)
    blocker_ids.extend(f"log10max_semantic_op_{op}_missing" for op in missing_semantic)
    status: Literal["complete", "partial", "blocked"] = "complete"
    if missing or missing_semantic:
        status = "partial"
    if duplicates:
        status = "blocked"
        blocker_ids.extend(f"log10max_semantic_op_{op}_duplicate" for op in duplicates)
    return OperatorInstructionSliceSet(
        schema_version="1",
        slice_set_id=slice_set_id,
        operator="log10max",
        source_route_component_integration_report_id=route.profile_id,
        expected_row_families=EXPECTED_LOG10MAX_ROW_FAMILIES,
        present_row_families=present,
        folded_row_families=folded,
        missing_row_families=missing,
        blocked_row_families=blocked,
        covered_semantic_ops=covered,
        missing_semantic_ops=missing_semantic,
        duplicate_semantic_ops=duplicates,
        slice_set_status=status,
        layout_epoch=route.layout_epoch,
        layout_plan_sha256=route.layout_plan_sha256,
        slices=tuple(slices),
        blocker_ids=tuple(dict.fromkeys(blocker_ids)),
    )


def summarize_log10max_operator_instruction_slice_set(
    report: OperatorInstructionSliceSet,
) -> dict[str, object]:
    return report.summary()


def build_log10max_operator_insts_component_candidate(
    slice_set: OperatorInstructionSliceSet | None = None,
    *,
    candidate_id: str = "operator_insts_component_candidate:log10max:v1",
) -> OperatorInstsComponentCandidate:
    """Build the Phase-5B report-local insts component candidate."""

    slices = slice_set or build_log10max_operator_instruction_slice_set()
    active_row_count = sum(
        item.row_count for item in slices.slices if item.slice_status == "present"
    )
    full = slices.slice_set_status == "complete"
    partial_sha = _diagnostic_partial_component_sha256(slices)
    blocker_ids: list[str] = []
    if not full:
        blocker_ids.append(LOG10MAX_OPERATOR_INSTS_COMPONENT_PARTIAL)
        blocker_ids.extend(slices.blocker_ids)
    return OperatorInstsComponentCandidate(
        schema_version="1",
        candidate_id=candidate_id,
        operator="log10max",
        source_slice_set_id=slices.slice_set_id,
        component_name="insts_file.bin",
        layout_epoch=slices.layout_epoch,
        layout_plan_sha256=slices.layout_plan_sha256,
        component_size_bytes=None,
        integrated_row_count=active_row_count,
        expected_row_families=slices.expected_row_families,
        present_row_families=slices.present_row_families,
        folded_row_families=slices.folded_row_families,
        missing_row_families=slices.missing_row_families,
        component_sha256=None if not full else partial_sha,
        diagnostic_partial_component_sha256=None if full else partial_sha,
        active_row_count=active_row_count,
        reserved_row_count=0,
        zero_padding_row_count=0,
        unowned_nonzero_row_count=0,
        no_overwrite_status="pass" if not slices.duplicate_semantic_ops else "blocked",
        decode_roundtrip_status="pass" if active_row_count else "blocked",
        provenance_status="pass" if active_row_count else "blocked",
        micc_coherence_status="not_checked",
        component_status=(
            "full_operator_candidate" if full else "partial_operator_candidate"
        ),
        runtime_ready=False,
        uploadable=False,
        blocker_ids=tuple(dict.fromkeys(blocker_ids)),
    )


def summarize_log10max_operator_insts_component_candidate(
    report: OperatorInstsComponentCandidate,
) -> dict[str, object]:
    return report.summary()


def build_log10max_operator_control_coherence_report(
    insts_candidate: OperatorInstsComponentCandidate | None = None,
    *,
    report_id: str = "operator_control_coherence:log10max:v1",
) -> OperatorControlCoherenceReport:
    """Build the Phase-5C full-operator control coherence report."""

    insts = insts_candidate or build_log10max_operator_insts_component_candidate()
    insts_pass = insts.component_status == "full_operator_candidate"
    blocker_ids: list[str] = []
    if not insts_pass:
        blocker_ids.append(LOG10MAX_OPERATOR_CONTROL_COHERENCE_BLOCKED)
        blocker_ids.append("log10max_control_coherence_component_partial")
        blocker_ids.extend(insts.blocker_ids)
    blocker_ids.extend(
        (
            "log10max_control_coherence_micc_candidate_missing",
            "log10max_control_coherence_exeblock_component_missing",
            "log10max_control_coherence_instance_component_missing",
        )
    )
    return OperatorControlCoherenceReport(
        schema_version="1",
        report_id=report_id,
        operator="log10max",
        coherence_scope="full_operator",
        source_insts_component_candidate_id=insts.candidate_id,
        source_micc_candidate_id=None,
        source_exeblock_component_id=None,
        source_instance_component_id=None,
        insts_component_status="pass" if insts_pass else "blocked",
        micc_candidate_status="blocked",
        exeblock_component_status="blocked",
        instance_component_status="blocked",
        stage_start_pc_status="blocked",
        stage_instruction_count_status="blocked",
        stage_pc_within_pe_local_inst_rows_status="blocked",
        active_exeblock_points_to_owned_rows_status="blocked",
        end_inst_boundary_status="blocked",
        successor_predecessor_status="blocked",
        root_reachability_status="blocked",
        task_subtask_stamp_status="blocked",
        instance_base_addr_status="blocked",
        coherence_status="blocked",
        blocker_ids=tuple(dict.fromkeys(blocker_ids)),
        runtime_ready=False,
        uploadable=False,
    )


def summarize_log10max_operator_control_coherence_report(
    report: OperatorControlCoherenceReport,
) -> dict[str, object]:
    return report.summary()


def build_log10max_operator_payload_manifest_candidate(
    insts_candidate: OperatorInstsComponentCandidate | None = None,
    control_report: OperatorControlCoherenceReport | None = None,
    *,
    manifest_id: str = "operator_payload_manifest_candidate:log10max:v1",
) -> OperatorPayloadManifestCandidate:
    """Build the Phase-5D blocked operator payload manifest candidate."""

    insts = insts_candidate or build_log10max_operator_insts_component_candidate()
    control = control_report or build_log10max_operator_control_coherence_report(
        insts
    )
    missing_roles = REQUIRED_LOG10MAX_PAYLOAD_FILE_ROLES
    blocker_ids: list[str] = [
        LOG10MAX_OPERATOR_PAYLOAD_MANIFEST_BLOCKED,
        "log10max_payload_manifest_component_partial",
        "log10max_payload_manifest_control_coherence_blocked",
        "log10max_payload_manifest_runtime_assets_missing",
        "log10max_payload_manifest_final_cbuf_missing",
        "log10max_payload_manifest_final_micc_missing",
    ]
    blocker_ids.extend(insts.blocker_ids)
    blocker_ids.extend(control.blocker_ids)
    blocker_ids.extend(
        f"log10max_payload_file_role_{role}_missing" for role in missing_roles
    )
    blockers_by_layer = (
        ("slice_set", tuple(insts.blocker_ids)),
        (
            "insts_component",
            (
                "log10max_payload_manifest_component_partial",
                *insts.blocker_ids,
            ),
        ),
        ("control_coherence", tuple(control.blocker_ids)),
        (
            "payload_manifest",
            (
                "log10max_payload_manifest_runtime_assets_missing",
                "log10max_payload_manifest_final_cbuf_missing",
                "log10max_payload_manifest_final_micc_missing",
            ),
        ),
        ("runtime_assets", ("log10max_payload_manifest_runtime_assets_missing",)),
        ("numerical", ("not_checked",)),
    )
    diagnostic_hashes = ()
    if insts.diagnostic_partial_component_sha256:
        diagnostic_hashes = (
            (
                "diagnostic_partial_insts_component",
                insts.diagnostic_partial_component_sha256,
            ),
        )
    return OperatorPayloadManifestCandidate(
        schema_version="1",
        manifest_id=manifest_id,
        operator="log10max",
        source_insts_component_candidate_id=insts.candidate_id,
        source_control_coherence_report_id=control.report_id,
        required_file_roles=REQUIRED_LOG10MAX_PAYLOAD_FILE_ROLES,
        present_file_roles=(),
        missing_file_roles=missing_roles,
        component_manifest_status="blocked",
        operator_payload_manifest_status="blocked",
        readiness_claim="blocked",
        component_hashes=(),
        diagnostic_hashes=diagnostic_hashes,
        runtime_asset_status="blocked",
        simict_status="not_run",
        numerical_status="not_checked",
        blockers_by_layer=blockers_by_layer,
        blocker_ids=tuple(dict.fromkeys(blocker_ids)),
        runtime_ready=False,
        uploadable=False,
    )


def summarize_log10max_operator_payload_manifest_candidate(
    report: OperatorPayloadManifestCandidate,
) -> dict[str, object]:
    return report.summary()


def _route_copy_slice(
    route: Log10MaxRouteComponentIntegrationReport,
) -> OperatorInstructionSlice:
    row_ids = tuple(record.physical_row_plan_id for record in route.integration_records)
    offsets = tuple(record.component_byte_offset for record in route.integration_records)
    sha256s = tuple(record.raw_inst_t_row_bytes_sha256 for record in route.integration_records)
    return OperatorInstructionSlice(
        schema_version="1",
        slice_id="operator_instruction_slice:log10max:route_copy",
        operator="log10max",
        slice_kind="route_copy",
        slice_status="present",
        source_report_id=route.profile_id,
        covered_semantic_ops=SEMANTIC_OPS_BY_SLICE["route_copy"],
        folded_into_slice_id=None,
        folded_evidence_id=None,
        integration_scope="route_rows_only",
        row_count=len(route.integration_records),
        component_name="insts_file.bin",
        row_ids=row_ids,
        component_byte_offsets=offsets,
        row_sha256s=sha256s,
        slice_sha256=route.route_slice_sha256,
        layout_epoch=route.layout_epoch,
        layout_plan_sha256=route.layout_plan_sha256,
        placement_status="placed",
        byte_status="copied_from_candidate",
        no_overwrite_status="pass",
        decode_roundtrip_status="pass",
        provenance_status="pass",
        blocker_ids=(),
    )


def _ring_fmax_update_slice(
    report: RingFmaxUpdateSliceReport,
) -> OperatorInstructionSlice:
    row_ids = tuple(record.row_id for record in report.rows)
    offsets = tuple(record.component_byte_offset for record in report.rows)
    sha256s = tuple(record.raw_inst_t_row_bytes_sha256 for record in report.rows)
    return OperatorInstructionSlice(
        schema_version="1",
        slice_id="operator_instruction_slice:log10max:ring_fmax_update",
        operator="log10max",
        slice_kind="ring_fmax_update",
        slice_status="present",
        source_report_id=report.profile_id,
        covered_semantic_ops=SEMANTIC_OPS_BY_SLICE["ring_fmax_update"],
        folded_into_slice_id=None,
        folded_evidence_id=None,
        integration_scope="row_family_only",
        row_count=len(report.rows),
        component_name="insts_file.bin",
        row_ids=row_ids,
        component_byte_offsets=offsets,
        row_sha256s=sha256s,
        slice_sha256=report.slice_sha256,
        layout_epoch=report.layout_epoch,
        layout_plan_sha256=report.layout_plan_sha256,
        placement_status="placed",
        byte_status="copied_from_candidate",
        no_overwrite_status=(
            "pass"
            if report.summary()["duplicate_component_byte_offset_count"] == 0
            else "blocked"
        ),
        decode_roundtrip_status="pass",
        provenance_status="pass",
        blocker_ids=(),
    )


def _blocked_slice(kind: str) -> OperatorInstructionSlice:
    return OperatorInstructionSlice(
        schema_version="1",
        slice_id=f"operator_instruction_slice:log10max:{kind}",
        operator="log10max",
        slice_kind=kind,  # type: ignore[arg-type]
        slice_status="blocked",
        source_report_id="",
        covered_semantic_ops=(),
        folded_into_slice_id=None,
        folded_evidence_id=None,
        integration_scope="row_family_only",
        row_count=0,
        component_name="insts_file.bin",
        row_ids=(),
        component_byte_offsets=(),
        row_sha256s=(),
        slice_sha256=None,
        layout_epoch=None,
        layout_plan_sha256=None,
        placement_status="blocked",
        byte_status="blocked",
        no_overwrite_status="blocked",
        decode_roundtrip_status="blocked",
        provenance_status="blocked",
        blocker_ids=(f"log10max_operator_slice_{kind}_missing",),
    )


def _duplicates(values: tuple[str, ...]) -> tuple[str, ...]:
    seen: set[str] = set()
    duplicates: list[str] = []
    for value in values:
        if value in seen and value not in duplicates:
            duplicates.append(value)
        seen.add(value)
    return tuple(duplicates)


def _diagnostic_partial_component_sha256(
    slices: OperatorInstructionSliceSet,
) -> str:
    payload = [
        {
            "slice_kind": item.slice_kind,
            "slice_status": item.slice_status,
            "row_count": item.row_count,
            "slice_sha256": item.slice_sha256,
        }
        for item in slices.slices
    ]
    data = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(data).hexdigest()


__all__ = [
    "EXPECTED_LOG10MAX_ROW_FAMILIES",
    "EXPECTED_LOG10MAX_SEMANTIC_OPS",
    "LOG10MAX_OPERATOR_CONTROL_COHERENCE_BLOCKED",
    "LOG10MAX_OPERATOR_INSTS_COMPONENT_PARTIAL",
    "LOG10MAX_OPERATOR_PAYLOAD_MANIFEST_BLOCKED",
    "LOG10MAX_OPERATOR_SLICE_SET_PARTIAL",
    "OperatorInstsComponentCandidate",
    "OperatorControlCoherenceReport",
    "OperatorInstructionSlice",
    "OperatorInstructionSliceSet",
    "OperatorPayloadManifestCandidate",
    "REQUIRED_LOG10MAX_PAYLOAD_FILE_ROLES",
    "SEMANTIC_OPS_BY_SLICE",
    "build_log10max_operator_control_coherence_report",
    "build_log10max_operator_insts_component_candidate",
    "build_log10max_operator_instruction_slice_set",
    "build_log10max_operator_payload_manifest_candidate",
    "summarize_log10max_operator_control_coherence_report",
    "summarize_log10max_operator_insts_component_candidate",
    "summarize_log10max_operator_instruction_slice_set",
    "summarize_log10max_operator_payload_manifest_candidate",
]
