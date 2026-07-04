"""Fail-closed flow_ack policy report for log10max route rows.

This module is Phase 2 evidence plumbing for the route-byte-family RFC.  It
does not emit route bytes and does not choose final ``flow_ack`` values.  The
default policy is blocked because A-line has multiple relevant facts:

* ``inst_map_common::setACKInst`` writes ``flow_ack = child_idx``.
* ``inst_blk_map::set_flag2_last_copy`` and the legacy stage-end mirror mark
  selected last COPY/FLOW rows with ``flow_ack = 1``.
* ``task_print.cpp`` projects COPY ``flow_ack`` into ``base_addr_idx``.
* ``memory_template_check`` bounds ``flow_ack`` by ``BASE_ADDR_SLOT_COUNT``.

Until a source-backed policy is selected, COPY-like row candidates must remain
candidate/report-only and must not be serialized into final components.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from .log10max_ring_update_operands import EXPECTED_PHASE_COUNTS
from .log10max_route_byte_family import (
    RoutePhysicalRowPlan,
    RoutePhysicalRowPlanReport,
    build_log10max_route_physical_row_plan_report,
)
from .log10max_route_endpoint_patch import (
    LOG10MAX_ROUTE_COMPONENT_INTEGRATION_BLOCKER,
    LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER,
    RouteEndpointPatch,
    RouteEndpointPatchReport,
    build_log10max_route_endpoint_patch_report,
)


BASE_ADDR_SLOT_COUNT = 4
LOG10MAX_ROUTE_FLOW_ACK_FINAL_POLICY_MISSING = (
    "log10max_route_flow_ack_final_policy_missing"
)
LOG10MAX_ROUTE_COMPONENT_BYTE_OFFSET_MISSING = (
    "log10max_route_component_byte_offset_missing"
)
FlowAckPolicyName = Literal[
    "blocked",
    "source_template_fixed",
    "last_physical_copy_lane_sets_one",
    "child_edge_slot",
]
FlowAckStatus = Literal["bound", "blocked"]
FlowAckCandidateStatus = Literal[
    "blocked_conflicting_evidence",
    "blocked_missing_exact_source_span",
]
BaseSlotStatus = Literal["range_checked", "asset_bound", "blocked", "not_applicable"]
FinalFlowAckStatus = Literal["final_bound", "blocked"]
FlowAckPolicyScope = Literal["simulator_inst_t_only"]

FLOW_ACK_EVIDENCE_REFS: tuple[str, ...] = (
    "simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/"
    "inst_map_common.cpp::setACKInst sets flow_ack = child_idx",
    "simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/"
    "inst_blk_map.cpp::set_flag2_last_copy sets selected COPY flow_ack = 1",
    "compiler/gpdpu_compiler/core/program_legacy_inst.py::_set_stage_end_inst_flags "
    "sets final FLOW rows flow_ack = 1",
    "simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/"
    "task_print.cpp maps COPY flow_ack to base_addr_idx",
    "compiler/gpdpu_compiler/validation/dfu3500_package_checks/"
    "memory_template_check.py bounds flow_ack by BASE_ADDR_SLOT_COUNT",
)
LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING = LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER


@dataclass(frozen=True)
class FlowAckCandidateEvidence:
    """One fail-closed candidate in the flow_ack evidence matrix."""

    schema_version: str
    candidate_id: str
    logical_route_edge_id: str
    source_endpoint_patch_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    candidate_policy: Literal[
        "child_edge_slot",
        "last_physical_copy_lane_sets_one",
        "source_template_fixed",
    ]
    candidate_status: FlowAckCandidateStatus
    candidate_flow_ack_by_physical_lane: Mapping[int, int]
    evidence_refs: tuple[str, ...]
    conflict_refs: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    serialization_allowed: bool
    final_component_claim: bool
    blocker_ids: tuple[str, ...]

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "logical_route_edge_id": self.logical_route_edge_id,
            "source_endpoint_patch_id": self.source_endpoint_patch_id,
            "phase": self.phase,
            "candidate_policy": self.candidate_policy,
            "candidate_status": self.candidate_status,
            "candidate_flow_ack_by_physical_lane": dict(
                self.candidate_flow_ack_by_physical_lane
            ),
            "evidence_refs": list(self.evidence_refs),
            "conflict_refs": list(self.conflict_refs),
            "missing_evidence": list(self.missing_evidence),
            "serialization_allowed": self.serialization_allowed,
            "final_component_claim": self.final_component_claim,
            "blocker_ids": list(self.blocker_ids),
        }


@dataclass(frozen=True)
class FlowAckPolicy:
    """Field-owner policy for one logical route edge.

    ``copy_like_row_candidate_serialization_claim`` is deliberately false for
    the default report.  If a future worker sets it true while ``status`` is not
    ``bound``, the checker must fail with
    ``log10max_route_flow_ack_policy_missing``.
    """

    schema_version: str
    policy_id: str
    operator: Literal["log10max"]
    route_role: Literal["GlobalMax"]
    selected_strategy: Literal["ring_spmd_row_then_col"]
    logical_route_edge_id: str
    source_endpoint_patch_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    route_family_intent: Literal[
        "copy_like_candidate",
        "source_template_fixed",
        "blocked",
    ]
    policy: FlowAckPolicyName
    status: FlowAckStatus
    applies_to: Literal["simulator_inst_t"]
    rtl_projection_status: Literal["not_claimed"]
    base_addr_slot_count: int
    bound_flow_ack_by_physical_lane: Mapping[int, int]
    source_template_evidence_id: str | None
    source_template_sha256: str | None
    candidate_policy_evidence_refs: tuple[str, ...]
    copy_like_row_candidate_serialization_claim: bool
    final_component_claim: bool
    blocker_ids: tuple[str, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def uploadable(self) -> bool:
        return False

    @property
    def flow_ack_status(self) -> FlowAckStatus:
        return self.status

    @property
    def blocks_copy_like_serialization(self) -> bool:
        return (
            self.route_family_intent == "copy_like_candidate"
            and self.status != "bound"
        )

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "policy_id": self.policy_id,
            "operator": self.operator,
            "route_role": self.route_role,
            "selected_strategy": self.selected_strategy,
            "logical_route_edge_id": self.logical_route_edge_id,
            "source_endpoint_patch_id": self.source_endpoint_patch_id,
            "phase": self.phase,
            "route_family_intent": self.route_family_intent,
            "policy": self.policy,
            "status": self.status,
            "flow_ack_status": self.flow_ack_status,
            "applies_to": self.applies_to,
            "rtl_projection_status": self.rtl_projection_status,
            "base_addr_slot_count": self.base_addr_slot_count,
            "bound_flow_ack_by_physical_lane": dict(
                self.bound_flow_ack_by_physical_lane
            ),
            "source_template_evidence_id": self.source_template_evidence_id,
            "source_template_sha256": self.source_template_sha256,
            "candidate_policy_evidence_refs": list(
                self.candidate_policy_evidence_refs
            ),
            "copy_like_row_candidate_serialization_claim": (
                self.copy_like_row_candidate_serialization_claim
            ),
            "final_component_claim": self.final_component_claim,
            "blocks_copy_like_serialization": self.blocks_copy_like_serialization,
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }


@dataclass(frozen=True)
class Log10MaxRouteFlowAckPolicyReport:
    """Report-only flow_ack evidence gate.

    The report may document candidate policies, but route byte serialization is
    blocked unless every COPY-like policy is ``bound``.
    """

    profile_id: str
    source_endpoint_patch_report_id: str
    policies: tuple[FlowAckPolicy, ...]
    candidate_evidence_matrix: tuple[FlowAckCandidateEvidence, ...]

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
        if not self.policies:
            blockers.append(LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING)
        for policy in self.policies:
            blockers.extend(policy.blocker_ids)
        return tuple(dict.fromkeys(blockers))

    def summary(self) -> dict[str, object]:
        phase_counts: dict[str, int] = {}
        policy_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        intent_counts: dict[str, int] = {}
        candidate_policy_counts: dict[str, int] = {}
        candidate_status_counts: dict[str, int] = {}
        blocked_copy_like = 0
        serialization_claims = 0
        candidate_serialization_claims = 0
        candidate_final_component_claims = 0
        for policy in self.policies:
            phase_counts[policy.phase] = phase_counts.get(policy.phase, 0) + 1
            policy_counts[policy.policy] = policy_counts.get(policy.policy, 0) + 1
            status_counts[policy.status] = status_counts.get(policy.status, 0) + 1
            intent_counts[policy.route_family_intent] = (
                intent_counts.get(policy.route_family_intent, 0) + 1
            )
            if policy.blocks_copy_like_serialization:
                blocked_copy_like += 1
            if policy.copy_like_row_candidate_serialization_claim:
                serialization_claims += 1
        for candidate in self.candidate_evidence_matrix:
            candidate_policy_counts[candidate.candidate_policy] = (
                candidate_policy_counts.get(candidate.candidate_policy, 0) + 1
            )
            candidate_status_counts[candidate.candidate_status] = (
                candidate_status_counts.get(candidate.candidate_status, 0) + 1
            )
            if candidate.serialization_allowed:
                candidate_serialization_claims += 1
            if candidate.final_component_claim:
                candidate_final_component_claims += 1
        return {
            "profile_id": self.profile_id,
            "source_endpoint_patch_report_id": self.source_endpoint_patch_report_id,
            "policy_count": len(self.policies),
            "phase_counts": dict(sorted(phase_counts.items())),
            "expected_phase_counts": dict(sorted(EXPECTED_PHASE_COUNTS.items())),
            "policy_counts": dict(sorted(policy_counts.items())),
            "flow_ack_status_counts": dict(sorted(status_counts.items())),
            "route_family_intent_counts": dict(sorted(intent_counts.items())),
            "copy_like_serialization_blocked_count": blocked_copy_like,
            "copy_like_row_candidate_serialization_claim_count": (
                serialization_claims
            ),
            "candidate_evidence_count": len(self.candidate_evidence_matrix),
            "candidate_policy_counts": dict(sorted(candidate_policy_counts.items())),
            "candidate_status_counts": dict(sorted(candidate_status_counts.items())),
            "candidate_serialization_claim_count": (
                candidate_serialization_claims
            ),
            "candidate_final_component_claim_count": (
                candidate_final_component_claims
            ),
            "base_addr_slot_count": BASE_ADDR_SLOT_COUNT,
            "evidence_refs": list(FLOW_ACK_EVIDENCE_REFS),
            "blocker_ids": list(self.blocker_ids),
            "final_component_claim": self.final_component_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_route_flow_ack_policy_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "final_component_claim": self.final_component_claim,
            "blocker_ids": list(self.blocker_ids),
            "policies": [policy.to_plan() for policy in self.policies],
            "candidate_evidence_matrix": [
                candidate.to_plan() for candidate in self.candidate_evidence_matrix
            ],
            "layering_policy": (
                "FlowAckPolicy is a field-owner report. It may block COPY-like "
                "route row candidates, but it does not emit route bytes, does "
                "not claim RTL projection semantics, and does not change "
                "runtime_ready."
            ),
        }


@dataclass(frozen=True)
class FlowAckPolicyCandidate:
    """Candidate-only flow_ack value for one physical COPY lane row.

    This is Phase 3A evidence.  It may feed candidate-byte pack/decode work, but
    it is not final component evidence and does not clear runtime readiness.
    """

    schema_version: str
    candidate_id: str
    physical_row_plan_id: str
    logical_route_edge_id: str
    route_endpoint_patch_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    physical_lane_index: int
    physical_lane_count: int
    lane_stride: int
    candidate_policy: Literal[
        "last_physical_copy_lane_sets_one",
        "source_template_fixed",
    ]
    flow_ack: int
    flow_ack_reason: str
    flow_ack_status: Literal["candidate_bound"]
    final_policy_status: Literal["pending_final_policy"]
    base_addr_slot_count: int
    base_slot_status: BaseSlotStatus
    base_slot_binding_id: str | None
    source_template_evidence_id: str | None
    source_template_sha256: str | None
    final_component_claim: bool
    runtime_ready: bool
    uploadable: bool
    blocker_ids: tuple[str, ...]

    @property
    def in_base_slot_range(self) -> bool:
        return 0 <= self.flow_ack < self.base_addr_slot_count

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "physical_row_plan_id": self.physical_row_plan_id,
            "logical_route_edge_id": self.logical_route_edge_id,
            "route_endpoint_patch_id": self.route_endpoint_patch_id,
            "phase": self.phase,
            "physical_lane_index": self.physical_lane_index,
            "physical_lane_count": self.physical_lane_count,
            "lane_stride": self.lane_stride,
            "candidate_policy": self.candidate_policy,
            "flow_ack": self.flow_ack,
            "flow_ack_reason": self.flow_ack_reason,
            "flow_ack_status": self.flow_ack_status,
            "final_policy_status": self.final_policy_status,
            "base_addr_slot_count": self.base_addr_slot_count,
            "base_slot_status": self.base_slot_status,
            "base_slot_binding_id": self.base_slot_binding_id,
            "source_template_evidence_id": self.source_template_evidence_id,
            "source_template_sha256": self.source_template_sha256,
            "in_base_slot_range": self.in_base_slot_range,
            "final_component_claim": self.final_component_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "blocker_ids": list(self.blocker_ids),
        }


@dataclass(frozen=True)
class Log10MaxRouteFlowAckCandidateReport:
    """Phase 3A candidate-only flow_ack report for physical COPY rows."""

    profile_id: str
    source_physical_row_plan_report_id: str
    candidates: tuple[FlowAckPolicyCandidate, ...]

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
            blockers.append("log10max_route_flow_ack_candidate_missing")
        for candidate in self.candidates:
            blockers.extend(candidate.blocker_ids)
        blockers.extend(
            (
                LOG10MAX_ROUTE_COMPONENT_BYTE_OFFSET_MISSING,
                LOG10MAX_ROUTE_COMPONENT_INTEGRATION_BLOCKER,
            )
        )
        return tuple(dict.fromkeys(blockers))

    def summary(self) -> dict[str, object]:
        phase_counts: dict[str, int] = {}
        flow_ack_counts: dict[str, int] = {}
        flow_ack_one_phase_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        final_status_counts: dict[str, int] = {}
        base_slot_counts: dict[str, int] = {}
        policy_counts: dict[str, int] = {}
        reason_counts: dict[str, int] = {}
        final_component_claim_count = 0
        runtime_ready_claim_count = 0
        uploadable_claim_count = 0
        edge_ids = {candidate.logical_route_edge_id for candidate in self.candidates}
        for candidate in self.candidates:
            phase_counts[candidate.phase] = phase_counts.get(candidate.phase, 0) + 1
            flow_ack_key = str(candidate.flow_ack)
            flow_ack_counts[flow_ack_key] = flow_ack_counts.get(flow_ack_key, 0) + 1
            if candidate.flow_ack == 1:
                flow_ack_one_phase_counts[candidate.phase] = (
                    flow_ack_one_phase_counts.get(candidate.phase, 0) + 1
                )
            status_counts[candidate.flow_ack_status] = (
                status_counts.get(candidate.flow_ack_status, 0) + 1
            )
            final_status_counts[candidate.final_policy_status] = (
                final_status_counts.get(candidate.final_policy_status, 0) + 1
            )
            base_slot_counts[candidate.base_slot_status] = (
                base_slot_counts.get(candidate.base_slot_status, 0) + 1
            )
            policy_counts[candidate.candidate_policy] = (
                policy_counts.get(candidate.candidate_policy, 0) + 1
            )
            reason_counts[candidate.flow_ack_reason] = (
                reason_counts.get(candidate.flow_ack_reason, 0) + 1
            )
            if candidate.final_component_claim:
                final_component_claim_count += 1
            if candidate.runtime_ready:
                runtime_ready_claim_count += 1
            if candidate.uploadable:
                uploadable_claim_count += 1
        expected_physical_phase_counts = {
            phase: count * 4 for phase, count in sorted(EXPECTED_PHASE_COUNTS.items())
        }
        return {
            "profile_id": self.profile_id,
            "source_physical_row_plan_report_id": (
                self.source_physical_row_plan_report_id
            ),
            "logical_route_edge_count": len(edge_ids),
            "candidate_count": len(self.candidates),
            "phase_counts": dict(sorted(phase_counts.items())),
            "expected_phase_counts": expected_physical_phase_counts,
            "flow_ack_value_counts": dict(sorted(flow_ack_counts.items())),
            "flow_ack_one_phase_counts": dict(
                sorted(flow_ack_one_phase_counts.items())
            ),
            "expected_flow_ack_one_phase_counts": dict(
                sorted(EXPECTED_PHASE_COUNTS.items())
            ),
            "flow_ack_status_counts": dict(sorted(status_counts.items())),
            "final_policy_status_counts": dict(sorted(final_status_counts.items())),
            "base_slot_status_counts": dict(sorted(base_slot_counts.items())),
            "candidate_policy_counts": dict(sorted(policy_counts.items())),
            "flow_ack_reason_counts": dict(sorted(reason_counts.items())),
            "base_addr_slot_count": BASE_ADDR_SLOT_COUNT,
            "final_component_claim_count": final_component_claim_count,
            "runtime_ready_claim_count": runtime_ready_claim_count,
            "uploadable_claim_count": uploadable_claim_count,
            "blocker_ids": list(self.blocker_ids),
            "final_component_claim": self.final_component_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_route_flow_ack_candidate_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "final_component_claim": self.final_component_claim,
            "blocker_ids": list(self.blocker_ids),
            "candidates": [candidate.to_plan() for candidate in self.candidates],
            "layering_policy": (
                "Phase 3A binds candidate-only simulator inst_t flow_ack "
                "values for physical COPY lane rows. It does not claim final "
                "flow_ack correctness, component placement, runtime_ready, or "
                "uploadability."
            ),
        }


@dataclass(frozen=True)
class RouteFlowAckFinalPolicyBinding:
    """Final simulator-inst_t flow_ack binding for one physical COPY lane.

    This is still not a runtime or RTL claim.  The binding only promotes the
    candidate last-lane policy into a simulator ``inst_t`` field owner after the
    local base-slot/memory-template evidence has been named.
    """

    schema_version: str
    binding_id: str
    source_candidate_id: str
    physical_row_plan_id: str
    logical_route_edge_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    physical_lane_index: int
    physical_lane_count: int
    flow_ack: int
    flow_ack_reason: str
    policy: Literal["last_physical_copy_lane_sets_one", "source_template_fixed"]
    policy_scope: FlowAckPolicyScope
    final_policy_status: FinalFlowAckStatus
    base_slot_status: BaseSlotStatus
    base_slot_binding_id: str | None
    base_slot_evidence_id: str | None
    memory_template_check_report_id: str | None
    simulator_path_exempt_evidence_id: str | None
    source_template_evidence_id: str | None
    source_template_sha256: str | None
    rtl_projection_status: Literal["not_claimed"]
    final_component_claim: bool
    runtime_ready: bool
    uploadable: bool
    blocker_ids: tuple[str, ...]

    @property
    def in_base_slot_range(self) -> bool:
        return 0 <= self.flow_ack < BASE_ADDR_SLOT_COUNT

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "binding_id": self.binding_id,
            "source_candidate_id": self.source_candidate_id,
            "physical_row_plan_id": self.physical_row_plan_id,
            "logical_route_edge_id": self.logical_route_edge_id,
            "phase": self.phase,
            "physical_lane_index": self.physical_lane_index,
            "physical_lane_count": self.physical_lane_count,
            "flow_ack": self.flow_ack,
            "flow_ack_reason": self.flow_ack_reason,
            "policy": self.policy,
            "policy_scope": self.policy_scope,
            "final_policy_status": self.final_policy_status,
            "base_slot_status": self.base_slot_status,
            "base_slot_binding_id": self.base_slot_binding_id,
            "base_slot_evidence_id": self.base_slot_evidence_id,
            "memory_template_check_report_id": self.memory_template_check_report_id,
            "simulator_path_exempt_evidence_id": (
                self.simulator_path_exempt_evidence_id
            ),
            "source_template_evidence_id": self.source_template_evidence_id,
            "source_template_sha256": self.source_template_sha256,
            "rtl_projection_status": self.rtl_projection_status,
            "in_base_slot_range": self.in_base_slot_range,
            "final_component_claim": self.final_component_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "blocker_ids": list(self.blocker_ids),
        }


@dataclass(frozen=True)
class Log10MaxRouteFlowAckFinalPolicyReport:
    """Phase-4A final simulator-inst_t flow_ack report.

    The report clears the flow_ack final-policy blocker for route rows only.
    Component offsets/integration and operator-level readiness remain blocked.
    """

    profile_id: str
    source_candidate_report_id: str
    bindings: tuple[RouteFlowAckFinalPolicyBinding, ...]

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
        if not self.bindings:
            blockers.append(LOG10MAX_ROUTE_FLOW_ACK_FINAL_POLICY_MISSING)
        for binding in self.bindings:
            blockers.extend(binding.blocker_ids)
        blockers.extend(
            (
                LOG10MAX_ROUTE_COMPONENT_BYTE_OFFSET_MISSING,
                LOG10MAX_ROUTE_COMPONENT_INTEGRATION_BLOCKER,
            )
        )
        return tuple(dict.fromkeys(blockers))

    def summary(self) -> dict[str, object]:
        phase_counts: dict[str, int] = {}
        flow_ack_counts: dict[str, int] = {}
        flow_ack_one_phase_counts: dict[str, int] = {}
        final_status_counts: dict[str, int] = {}
        base_slot_counts: dict[str, int] = {}
        policy_scope_counts: dict[str, int] = {}
        rtl_status_counts: dict[str, int] = {}
        final_component_claim_count = 0
        runtime_ready_claim_count = 0
        uploadable_claim_count = 0
        edge_ids = {binding.logical_route_edge_id for binding in self.bindings}
        for binding in self.bindings:
            phase_counts[binding.phase] = phase_counts.get(binding.phase, 0) + 1
            flow_ack_key = str(binding.flow_ack)
            flow_ack_counts[flow_ack_key] = flow_ack_counts.get(flow_ack_key, 0) + 1
            if binding.flow_ack == 1:
                flow_ack_one_phase_counts[binding.phase] = (
                    flow_ack_one_phase_counts.get(binding.phase, 0) + 1
                )
            final_status_counts[binding.final_policy_status] = (
                final_status_counts.get(binding.final_policy_status, 0) + 1
            )
            base_slot_counts[binding.base_slot_status] = (
                base_slot_counts.get(binding.base_slot_status, 0) + 1
            )
            policy_scope_counts[binding.policy_scope] = (
                policy_scope_counts.get(binding.policy_scope, 0) + 1
            )
            rtl_status_counts[binding.rtl_projection_status] = (
                rtl_status_counts.get(binding.rtl_projection_status, 0) + 1
            )
            if binding.final_component_claim:
                final_component_claim_count += 1
            if binding.runtime_ready:
                runtime_ready_claim_count += 1
            if binding.uploadable:
                uploadable_claim_count += 1
        expected_physical_phase_counts = {
            phase: count * 4 for phase, count in sorted(EXPECTED_PHASE_COUNTS.items())
        }
        return {
            "profile_id": self.profile_id,
            "source_candidate_report_id": self.source_candidate_report_id,
            "logical_route_edge_count": len(edge_ids),
            "binding_count": len(self.bindings),
            "phase_counts": dict(sorted(phase_counts.items())),
            "expected_phase_counts": expected_physical_phase_counts,
            "flow_ack_value_counts": dict(sorted(flow_ack_counts.items())),
            "flow_ack_one_phase_counts": dict(
                sorted(flow_ack_one_phase_counts.items())
            ),
            "expected_flow_ack_one_phase_counts": dict(
                sorted(EXPECTED_PHASE_COUNTS.items())
            ),
            "final_policy_status_counts": dict(sorted(final_status_counts.items())),
            "base_slot_status_counts": dict(sorted(base_slot_counts.items())),
            "policy_scope_counts": dict(sorted(policy_scope_counts.items())),
            "rtl_projection_status_counts": dict(sorted(rtl_status_counts.items())),
            "base_addr_slot_count": BASE_ADDR_SLOT_COUNT,
            "final_component_claim_count": final_component_claim_count,
            "runtime_ready_claim_count": runtime_ready_claim_count,
            "uploadable_claim_count": uploadable_claim_count,
            "blocker_ids": list(self.blocker_ids),
            "final_component_claim": self.final_component_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_route_flow_ack_final_policy_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "final_component_claim": self.final_component_claim,
            "blocker_ids": list(self.blocker_ids),
            "bindings": [binding.to_plan() for binding in self.bindings],
            "layering_policy": (
                "Phase 4A final-binds simulator inst_t flow_ack fields only. "
                "It does not claim RTL projection semantics, component "
                "integration, runtime_ready, or uploadability."
            ),
        }


def build_log10max_route_flow_ack_policy_report(
    endpoint_report: RouteEndpointPatchReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_route_flow_ack_policy_v1",
) -> Log10MaxRouteFlowAckPolicyReport:
    """Build a fail-closed policy per logical GlobalMax route edge."""

    source_report = endpoint_report or build_log10max_route_endpoint_patch_report()
    policies = tuple(_blocked_policy_for_endpoint(patch) for patch in source_report.patches)
    candidate_evidence_matrix = tuple(
        candidate
        for patch in source_report.patches
        for candidate in _candidate_evidence_for_endpoint(patch)
    )
    return Log10MaxRouteFlowAckPolicyReport(
        profile_id=profile_id,
        source_endpoint_patch_report_id=source_report.profile_id,
        policies=policies,
        candidate_evidence_matrix=candidate_evidence_matrix,
    )


def summarize_log10max_route_flow_ack_policy_report(
    report: Log10MaxRouteFlowAckPolicyReport,
) -> dict[str, object]:
    return report.summary()


def build_log10max_route_flow_ack_candidate_report(
    physical_row_report: RoutePhysicalRowPlanReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_route_flow_ack_candidate_v1",
) -> Log10MaxRouteFlowAckCandidateReport:
    """Bind Phase 3A last-lane flow_ack candidates for physical COPY rows."""

    source_report = physical_row_report or build_log10max_route_physical_row_plan_report()
    candidates = tuple(
        _candidate_for_physical_row(row) for row in source_report.physical_rows
    )
    return Log10MaxRouteFlowAckCandidateReport(
        profile_id=profile_id,
        source_physical_row_plan_report_id=source_report.profile_id,
        candidates=candidates,
    )


def summarize_log10max_route_flow_ack_candidate_report(
    report: Log10MaxRouteFlowAckCandidateReport,
) -> dict[str, object]:
    return report.summary()


def build_log10max_route_flow_ack_final_policy_report(
    candidate_report: Log10MaxRouteFlowAckCandidateReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_route_flow_ack_final_policy_v1",
) -> Log10MaxRouteFlowAckFinalPolicyReport:
    """Promote candidate flow_ack values to final simulator-inst_t owners."""

    source_report = candidate_report or build_log10max_route_flow_ack_candidate_report()
    bindings = tuple(_final_binding_for_candidate(candidate) for candidate in source_report.candidates)
    return Log10MaxRouteFlowAckFinalPolicyReport(
        profile_id=profile_id,
        source_candidate_report_id=source_report.profile_id,
        bindings=bindings,
    )


def summarize_log10max_route_flow_ack_final_policy_report(
    report: Log10MaxRouteFlowAckFinalPolicyReport,
) -> dict[str, object]:
    return report.summary()


def _blocked_policy_for_endpoint(patch: RouteEndpointPatch) -> FlowAckPolicy:
    return FlowAckPolicy(
        schema_version="1",
        policy_id=f"policy:route_flow_ack:{patch.logical_route_edge_id}",
        operator="log10max",
        route_role="GlobalMax",
        selected_strategy="ring_spmd_row_then_col",
        logical_route_edge_id=patch.logical_route_edge_id,
        source_endpoint_patch_id=patch.patch_id,
        phase=patch.phase,
        route_family_intent="copy_like_candidate",
        policy="blocked",
        status="blocked",
        applies_to="simulator_inst_t",
        rtl_projection_status="not_claimed",
        base_addr_slot_count=BASE_ADDR_SLOT_COUNT,
        bound_flow_ack_by_physical_lane={},
        source_template_evidence_id=None,
        source_template_sha256=None,
        candidate_policy_evidence_refs=FLOW_ACK_EVIDENCE_REFS,
        copy_like_row_candidate_serialization_claim=False,
        final_component_claim=False,
        blocker_ids=(LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING,),
    )


def _candidate_for_physical_row(row: RoutePhysicalRowPlan) -> FlowAckPolicyCandidate:
    is_last_lane = row.lane_index == row.lane_count - 1
    flow_ack = 1 if is_last_lane else 0
    reason = (
        "lane_idx_3_last_physical_copy_lane"
        if is_last_lane
        else f"lane_idx_{row.lane_index}_not_last_physical_copy_lane"
    )
    base_slot_status: BaseSlotStatus = (
        "range_checked" if 0 <= flow_ack < BASE_ADDR_SLOT_COUNT else "blocked"
    )
    blockers: list[str] = [LOG10MAX_ROUTE_FLOW_ACK_FINAL_POLICY_MISSING]
    if base_slot_status == "blocked":
        blockers.insert(0, "log10max_route_flow_ack_base_slot_range_invalid")
    return FlowAckPolicyCandidate(
        schema_version="1",
        candidate_id=f"flow_ack_candidate:{row.row_plan_id}",
        physical_row_plan_id=row.row_plan_id,
        logical_route_edge_id=row.logical_route_edge_id,
        route_endpoint_patch_id=row.route_endpoint_patch_id,
        phase=row.phase,
        physical_lane_index=row.lane_index,
        physical_lane_count=row.lane_count,
        lane_stride=row.lane_stride,
        candidate_policy="last_physical_copy_lane_sets_one",
        flow_ack=flow_ack,
        flow_ack_reason=reason,
        flow_ack_status="candidate_bound",
        final_policy_status="pending_final_policy",
        base_addr_slot_count=BASE_ADDR_SLOT_COUNT,
        base_slot_status=base_slot_status,
        base_slot_binding_id=None,
        source_template_evidence_id=None,
        source_template_sha256=None,
        final_component_claim=False,
        runtime_ready=False,
        uploadable=False,
        blocker_ids=tuple(blockers),
    )


def _final_binding_for_candidate(
    candidate: FlowAckPolicyCandidate,
) -> RouteFlowAckFinalPolicyBinding:
    blockers: list[str] = []
    base_slot_status: BaseSlotStatus = "asset_bound"
    base_slot_binding_id = (
        "base_slot_binding:log10max_route_flow_ack:"
        f"slot{candidate.flow_ack}:simulator_inst_t:v1"
    )
    base_slot_evidence_id = (
        "base_slot_evidence:memory_template_check:"
        f"BASE_ADDR_SLOT_COUNT={BASE_ADDR_SLOT_COUNT}:v1"
    )
    memory_template_check_report_id = (
        "memory_template_check:flow_ack_range_and_instance_base_slot:v1"
    )
    if not candidate.in_base_slot_range:
        base_slot_status = "blocked"
        blockers.append("log10max_route_flow_ack_base_slot_range_invalid")
    if candidate.final_component_claim or candidate.runtime_ready or candidate.uploadable:
        blockers.append("log10max_route_flow_ack_candidate_claims_final_state")
    final_status: FinalFlowAckStatus = "blocked" if blockers else "final_bound"
    if final_status == "blocked":
        blockers.append(LOG10MAX_ROUTE_FLOW_ACK_FINAL_POLICY_MISSING)
    return RouteFlowAckFinalPolicyBinding(
        schema_version="1",
        binding_id=f"flow_ack_final_policy:{candidate.physical_row_plan_id}",
        source_candidate_id=candidate.candidate_id,
        physical_row_plan_id=candidate.physical_row_plan_id,
        logical_route_edge_id=candidate.logical_route_edge_id,
        phase=candidate.phase,
        physical_lane_index=candidate.physical_lane_index,
        physical_lane_count=candidate.physical_lane_count,
        flow_ack=candidate.flow_ack,
        flow_ack_reason=candidate.flow_ack_reason,
        policy=candidate.candidate_policy,
        policy_scope="simulator_inst_t_only",
        final_policy_status=final_status,
        base_slot_status=base_slot_status,
        base_slot_binding_id=base_slot_binding_id if final_status == "final_bound" else None,
        base_slot_evidence_id=base_slot_evidence_id if final_status == "final_bound" else None,
        memory_template_check_report_id=(
            memory_template_check_report_id if final_status == "final_bound" else None
        ),
        simulator_path_exempt_evidence_id=None,
        source_template_evidence_id=candidate.source_template_evidence_id,
        source_template_sha256=candidate.source_template_sha256,
        rtl_projection_status="not_claimed",
        final_component_claim=False,
        runtime_ready=False,
        uploadable=False,
        blocker_ids=tuple(dict.fromkeys(blockers)),
    )


def _candidate_evidence_for_endpoint(
    patch: RouteEndpointPatch,
) -> tuple[FlowAckCandidateEvidence, ...]:
    child_edge_slot = FlowAckCandidateEvidence(
        schema_version="1",
        candidate_id=(
            f"candidate:route_flow_ack:{patch.logical_route_edge_id}:"
            "child_edge_slot"
        ),
        logical_route_edge_id=patch.logical_route_edge_id,
        source_endpoint_patch_id=patch.patch_id,
        phase=patch.phase,
        candidate_policy="child_edge_slot",
        candidate_status="blocked_conflicting_evidence",
        candidate_flow_ack_by_physical_lane={lane: 0 for lane in range(4)},
        evidence_refs=(
            "inst_map_common.cpp::setACKInst sets flow_ack = child_idx",
        ),
        conflict_refs=(
            "inst_blk_map.cpp::set_flag2_last_copy marks selected last COPY "
            "rows with flow_ack = 1",
            "program_legacy_inst.py::_set_stage_end_inst_flags marks final "
            "FLOW rows with flow_ack = 1",
        ),
        missing_evidence=(
            "exact child-edge slot mapping for log10max ring physical COPY rows",
            "base_addr slot ownership for simulator inst_t route candidates",
        ),
        serialization_allowed=False,
        final_component_claim=False,
        blocker_ids=(LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING,),
    )
    last_lane = FlowAckCandidateEvidence(
        schema_version="1",
        candidate_id=(
            f"candidate:route_flow_ack:{patch.logical_route_edge_id}:"
            "last_physical_copy_lane_sets_one"
        ),
        logical_route_edge_id=patch.logical_route_edge_id,
        source_endpoint_patch_id=patch.patch_id,
        phase=patch.phase,
        candidate_policy="last_physical_copy_lane_sets_one",
        candidate_status="blocked_conflicting_evidence",
        candidate_flow_ack_by_physical_lane={0: 0, 1: 0, 2: 0, 3: 1},
        evidence_refs=(
            "inst_blk_map.cpp::set_flag2_last_copy marks selected last COPY "
            "rows with flow_ack = 1",
            "program_legacy_inst.py::_set_stage_end_inst_flags marks final "
            "FLOW rows with flow_ack = 1",
        ),
        conflict_refs=(
            "inst_map_common.cpp::setACKInst may encode child_idx instead",
            "task_print.cpp projects COPY flow_ack into a base_addr_idx-like "
            "field, so slot 1 must be explicitly provisioned or proven safe",
        ),
        missing_evidence=(
            "source-backed proof that each logical route edge owns exactly one "
            "last physical COPY lane in the selected block",
            "decode/package proof that flow_ack slot 1 is legal for these rows",
        ),
        serialization_allowed=False,
        final_component_claim=False,
        blocker_ids=(LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING,),
    )
    source_template = FlowAckCandidateEvidence(
        schema_version="1",
        candidate_id=(
            f"candidate:route_flow_ack:{patch.logical_route_edge_id}:"
            "source_template_fixed"
        ),
        logical_route_edge_id=patch.logical_route_edge_id,
        source_endpoint_patch_id=patch.patch_id,
        phase=patch.phase,
        candidate_policy="source_template_fixed",
        candidate_status="blocked_missing_exact_source_span",
        candidate_flow_ack_by_physical_lane={},
        evidence_refs=(
            "source_template_fixed is the preferred override only with an exact "
            "COPY/COPYT span and decode proof",
        ),
        conflict_refs=(),
        missing_evidence=(
            "exact source COPY/COPYT span for this logical GlobalMax route edge",
            "template row sha256 and field provenance for flow_ack",
            "decode proof that source span values match the endpoint patch",
        ),
        serialization_allowed=False,
        final_component_claim=False,
        blocker_ids=(LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING,),
    )
    return (child_edge_slot, last_lane, source_template)


__all__ = [
    "FLOW_ACK_EVIDENCE_REFS",
    "FlowAckCandidateEvidence",
    "FlowAckCandidateStatus",
    "FlowAckPolicyCandidate",
    "FlowAckPolicy",
    "FlowAckPolicyName",
    "Log10MaxRouteFlowAckCandidateReport",
    "Log10MaxRouteFlowAckFinalPolicyReport",
    "Log10MaxRouteFlowAckPolicyReport",
    "RouteFlowAckFinalPolicyBinding",
    "LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING",
    "LOG10MAX_ROUTE_FLOW_ACK_FINAL_POLICY_MISSING",
    "build_log10max_route_flow_ack_candidate_report",
    "build_log10max_route_flow_ack_final_policy_report",
    "build_log10max_route_flow_ack_policy_report",
    "summarize_log10max_route_flow_ack_candidate_report",
    "summarize_log10max_route_flow_ack_final_policy_report",
    "summarize_log10max_route_flow_ack_policy_report",
]
