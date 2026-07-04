"""Report-only route COPY lane operand and field binding records.

This module implements Phase 2B of the route-row byte-family RFC.  It expands
each log10max GlobalMax logical route edge into COPYT-style physical COPY lane
plans, then binds route operands and high-risk inst_t fields to explicit owner
records.  It deliberately does not pack route bytes, integrate final
components, or change runtime_ready/uploadable state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from gpdpu_compiler.core.program_legacy_inst import OPERANDS_PER_OPERAND_RAM

from .log10max_ring_update_operands import EXPECTED_PHASE_COUNTS
from .log10max_route_endpoint_patch import (
    LOG10MAX_ROUTE_COMPONENT_INTEGRATION_BLOCKER,
    LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER,
    LOG10MAX_ROUTE_ROW_BYTES_BLOCKER,
)
from .log10max_route_byte_family import (
    LOG10MAX_ROUTE_BYTE_FAMILY_DECISION_ID,
    RoutePhysicalRowPlan,
    RoutePhysicalRowPlanReport,
    build_log10max_route_physical_row_plan_report,
)
from .log10max_route_layout_plan import (
    ExeBlockWriterPlan,
    InstructionBoundaryPlan,
    InstructionLayoutPlan,
    Log10MaxRouteLayoutPlanReport,
    build_log10max_route_layout_plan_report,
)


ROUTE_BYTE_FAMILY_DECISION_ID = LOG10MAX_ROUTE_BYTE_FAMILY_DECISION_ID
ROUTE_LANE_POLICY_ID = "route_lane_policy:copyt_logical_4lane_v1"
ROUTE_OPERAND_USAGE_POLICY_ID = "route_operand_usage:copy_src0_dst0_only_v1"
ROUTE_FLOW_ACK_BLOCKER = LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER
ROUTE_COMPONENT_BLOCKER = LOG10MAX_ROUTE_COMPONENT_INTEGRATION_BLOCKER
ROUTE_PHYSICAL_COMPONENT_PLACEMENT_BLOCKER = (
    "log10max_route_physical_component_placement_pending"
)
ROUTE_LOCAL_PC_BLOCKER = "log10max_route_instruction_layout_local_pc_pending"

PHYSICAL_ROWS_PER_LOGICAL_EDGE = 4
LANE_STRIDE_OPERANDS = OPERANDS_PER_OPERAND_RAM
EXPECTED_PHYSICAL_PHASE_COUNTS = {
    phase: count * 4
    for phase, count in EXPECTED_PHASE_COUNTS.items()
}


@dataclass(frozen=True)
class RouteInstOperandPatch:
    """Allocation-backed operand patch for one physical COPY lane row."""

    schema_version: str
    patch_id: str
    physical_row_plan_id: str
    logical_route_edge_id: str
    lane_index: int
    lane_count: int
    lane_stride_operands: int
    src_allocation_id: str
    dst_allocation_id: str
    src_placeholder_id: str
    dst_placeholder_id: str
    src_operands_idx: tuple[int, int, int]
    dst_operands_idx: tuple[int, int, int]
    operand_field_usage: tuple[tuple[str, str], ...]
    serializer_allocation_claim: bool
    final_component_claim: bool
    patch_status: Literal["patched", "blocked"]
    blockers: tuple[str, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def uploadable(self) -> bool:
        return False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "patch_id": self.patch_id,
            "physical_row_plan_id": self.physical_row_plan_id,
            "logical_route_edge_id": self.logical_route_edge_id,
            "lane_index": self.lane_index,
            "lane_count": self.lane_count,
            "lane_stride_operands": self.lane_stride_operands,
            "src_allocation_id": self.src_allocation_id,
            "dst_allocation_id": self.dst_allocation_id,
            "src_placeholder_id": self.src_placeholder_id,
            "dst_placeholder_id": self.dst_placeholder_id,
            "src_operands_idx": list(self.src_operands_idx),
            "dst_operands_idx": list(self.dst_operands_idx),
            "operand_field_usage": dict(self.operand_field_usage),
            "serializer_allocation_claim": self.serializer_allocation_claim,
            "final_component_claim": self.final_component_claim,
            "patch_status": self.patch_status,
            "blockers": list(self.blockers),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }


@dataclass(frozen=True)
class RouteInstOperandPatchReport:
    """Phase-2B operand patch report for physical route rows."""

    profile_id: str
    source_physical_row_plan_report_id: str
    patches: tuple[RouteInstOperandPatch, ...]

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
        if not self.patches:
            blockers.append("log10max_route_inst_operand_patch_missing")
        for patch in self.patches:
            blockers.extend(patch.blockers)
        return tuple(dict.fromkeys(blockers))

    def summary(self) -> dict[str, object]:
        phase_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        serializer_allocation_count = 0
        final_component_count = 0
        logical_edges = {patch.logical_route_edge_id for patch in self.patches}
        for patch in self.patches:
            phase = _phase_from_edge_id(patch.logical_route_edge_id)
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
            status_counts[patch.patch_status] = (
                status_counts.get(patch.patch_status, 0) + 1
            )
            if patch.serializer_allocation_claim:
                serializer_allocation_count += 1
            if patch.final_component_claim:
                final_component_count += 1
        return {
            "profile_id": self.profile_id,
            "source_physical_row_plan_report_id": (
                self.source_physical_row_plan_report_id
            ),
            "logical_route_edge_count": len(logical_edges),
            "patch_count": len(self.patches),
            "phase_counts": dict(sorted(phase_counts.items())),
            "expected_phase_counts": dict(sorted(EXPECTED_PHYSICAL_PHASE_COUNTS.items())),
            "patch_status_counts": dict(sorted(status_counts.items())),
            "serializer_allocation_claim_count": serializer_allocation_count,
            "final_component_claim_count": final_component_count,
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_route_inst_operand_patch_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "final_component_claim": self.final_component_claim,
            "blocker_ids": list(self.blocker_ids),
            "patches": [patch.to_plan() for patch in self.patches],
            "layering_policy": (
                "RouteInstOperandPatch records consume existing allocation ids "
                "and lane policies. They do not allocate in the serializer or "
                "claim final component rows."
            ),
        }


@dataclass(frozen=True)
class RouteInstFieldBindingRecord:
    """Field-owner join record for one physical route row candidate."""

    schema_version: str
    binding_id: str
    physical_row_plan_id: str
    logical_route_edge_id: str
    route_byte_family_decision_id: str
    operand_patch_id: str
    route_endpoint_patch_id: str
    flow_ack_policy_id: str | None
    instruction_layout_plan_id: str | None
    exe_block_writer_plan_id: str | None
    instruction_boundary_plan_id: str | None
    component_placement_plan_id: str | None
    field_owner_ids: tuple[tuple[str, str], ...]
    field_owner_status: tuple[tuple[str, str], ...]
    missing_fields: tuple[str, ...]
    binding_status: Literal[
        "candidate_field_bound",
        "component_field_bound",
        "blocked",
    ]
    final_component_claim: bool
    runtime_ready: bool
    uploadable: bool
    blocker_ids: tuple[str, ...]

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "binding_id": self.binding_id,
            "physical_row_plan_id": self.physical_row_plan_id,
            "logical_route_edge_id": self.logical_route_edge_id,
            "route_byte_family_decision_id": self.route_byte_family_decision_id,
            "operand_patch_id": self.operand_patch_id,
            "route_endpoint_patch_id": self.route_endpoint_patch_id,
            "flow_ack_policy_id": self.flow_ack_policy_id,
            "instruction_layout_plan_id": self.instruction_layout_plan_id,
            "exe_block_writer_plan_id": self.exe_block_writer_plan_id,
            "instruction_boundary_plan_id": self.instruction_boundary_plan_id,
            "component_placement_plan_id": self.component_placement_plan_id,
            "field_owner_ids": dict(self.field_owner_ids),
            "field_owner_status": dict(self.field_owner_status),
            "missing_fields": list(self.missing_fields),
            "binding_status": self.binding_status,
            "final_component_claim": self.final_component_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "blocker_ids": list(self.blocker_ids),
        }


@dataclass(frozen=True)
class RouteInstFieldBindingReport:
    """Phase-2B field binding report for physical route rows."""

    profile_id: str
    source_operand_patch_report_id: str
    source_layout_report_id: str
    records: tuple[RouteInstFieldBindingRecord, ...]

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
        if not self.records:
            blockers.append("log10max_route_inst_field_binding_missing")
        for record in self.records:
            blockers.extend(record.blocker_ids)
        return tuple(dict.fromkeys(blockers))

    def summary(self) -> dict[str, object]:
        status_counts: dict[str, int] = {}
        phase_counts: dict[str, int] = {}
        missing_counts: dict[str, int] = {}
        field_status_counts: dict[str, int] = {}
        final_component_count = 0
        for record in self.records:
            status_counts[record.binding_status] = (
                status_counts.get(record.binding_status, 0) + 1
            )
            phase = _phase_from_edge_id(record.logical_route_edge_id)
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
            for field in record.missing_fields:
                missing_counts[field] = missing_counts.get(field, 0) + 1
            for _, status in record.field_owner_status:
                field_status_counts[status] = field_status_counts.get(status, 0) + 1
            if record.final_component_claim:
                final_component_count += 1
        return {
            "profile_id": self.profile_id,
            "source_operand_patch_report_id": self.source_operand_patch_report_id,
            "source_layout_report_id": self.source_layout_report_id,
            "record_count": len(self.records),
            "phase_counts": dict(sorted(phase_counts.items())),
            "expected_phase_counts": dict(sorted(EXPECTED_PHYSICAL_PHASE_COUNTS.items())),
            "binding_status_counts": dict(sorted(status_counts.items())),
            "missing_field_counts": dict(sorted(missing_counts.items())),
            "field_owner_status_counts": dict(sorted(field_status_counts.items())),
            "final_component_claim_count": final_component_count,
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "final_component_claim": self.final_component_claim,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_route_inst_field_binding_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "final_component_claim": self.final_component_claim,
            "blocker_ids": list(self.blocker_ids),
            "records": [record.to_plan() for record in self.records],
            "layering_policy": (
                "RouteInstFieldBinding records join already-owned fields. "
                "flow_ack and physical component placement remain blockers, "
                "so no route bytes or runtime-ready transition are claimed."
            ),
        }

def build_log10max_route_inst_operand_patch_report(
    physical_row_report: RoutePhysicalRowPlanReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_route_inst_operand_patch_v1",
) -> RouteInstOperandPatchReport:
    physical_rows = physical_row_report or build_log10max_route_physical_row_plan_report()
    patches = tuple(
        _operand_patch_for_plan(plan) for plan in physical_rows.physical_rows
    )
    return RouteInstOperandPatchReport(
        profile_id=profile_id,
        source_physical_row_plan_report_id=physical_rows.profile_id,
        patches=patches,
    )


def build_log10max_route_inst_field_binding_report(
    operand_patch_report: RouteInstOperandPatchReport | None = None,
    physical_row_report: RoutePhysicalRowPlanReport | None = None,
    layout_report: Log10MaxRouteLayoutPlanReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_route_inst_field_binding_v1",
) -> RouteInstFieldBindingReport:
    physical_rows = physical_row_report or build_log10max_route_physical_row_plan_report()
    patches = operand_patch_report or build_log10max_route_inst_operand_patch_report(
        physical_rows
    )
    layout = layout_report or build_log10max_route_layout_plan_report()
    patch_by_row = {patch.physical_row_plan_id: patch for patch in patches.patches}
    layout_by_row = _layout_by_row_id(layout.instruction_layout_plans)
    exe_by_block = {
        plan.plan_id.removeprefix("exe_block_writer:"): plan
        for plan in layout.exe_block_writer_plans
    }
    boundary_by_row = _boundary_by_row_id(layout.instruction_boundary_plans)
    placement_by_row = {
        plan.row_candidate_id: plan for plan in layout.component_placement_plans
    }
    records: list[RouteInstFieldBindingRecord] = []
    for plan in physical_rows.physical_rows:
        patch = patch_by_row.get(plan.row_plan_id)
        sender_row = _route_row_candidate_id("push", plan.logical_route_edge_id)
        layout_plan = layout_by_row.get(sender_row)
        exe_block = (
            exe_by_block.get(layout_plan.exe_block_id)
            if layout_plan is not None
            else None
        )
        boundary = boundary_by_row.get(sender_row)
        placement = placement_by_row.get(sender_row)
        records.append(
            _field_binding_for_plan(
                plan=plan,
                patch=patch,
                layout_plan=layout_plan,
                exe_block=exe_block,
                boundary=boundary,
                placement_plan_id=placement.plan_id if placement is not None else None,
            )
        )
    return RouteInstFieldBindingReport(
        profile_id=profile_id,
        source_operand_patch_report_id=patches.profile_id,
        source_layout_report_id=layout.profile_id,
        records=tuple(records),
    )


def summarize_log10max_route_physical_row_plan_report(
    report: RoutePhysicalRowPlanReport,
) -> dict[str, object]:
    return report.summary()


def summarize_log10max_route_inst_operand_patch_report(
    report: RouteInstOperandPatchReport,
) -> dict[str, object]:
    return report.summary()


def summarize_log10max_route_inst_field_binding_report(
    report: RouteInstFieldBindingReport,
) -> dict[str, object]:
    return report.summary()


def _operand_patch_for_plan(plan: RoutePhysicalRowPlan) -> RouteInstOperandPatch:
    blockers = [LOG10MAX_ROUTE_ROW_BYTES_BLOCKER, ROUTE_COMPONENT_BLOCKER]
    patch_status: Literal["patched", "blocked"] = "patched"
    if plan.plan_status == "blocked":
        blockers.insert(0, "log10max_route_physical_row_plan_blocked")
        patch_status = "blocked"
    return RouteInstOperandPatch(
        schema_version="1",
        patch_id=f"route_operand_patch:{plan.row_plan_id}",
        physical_row_plan_id=plan.row_plan_id,
        logical_route_edge_id=plan.logical_route_edge_id,
        lane_index=plan.lane_index,
        lane_count=plan.lane_count,
        lane_stride_operands=plan.lane_stride,
        src_allocation_id=plan.src_operand_allocation_id,
        dst_allocation_id=plan.dst_operand_allocation_id,
        src_placeholder_id=plan.src_operand_allocation_id,
        dst_placeholder_id=plan.dst_operand_allocation_id,
        src_operands_idx=(plan.src_operand_idx, 0, 0),
        dst_operands_idx=(plan.dst_operand_idx, 0, 0),
        operand_field_usage=(
            ("src0", "used_allocation_lane"),
            ("src1", "unused_zero_fill_with_copy_src_count_evidence"),
            ("src2", "unused_zero_fill_with_copy_src_count_evidence"),
            ("dst0", "used_allocation_lane"),
            ("dst1", "unused_zero_fill_with_copy_dst_count_evidence"),
            ("dst2", "unused_zero_fill_with_copy_dst_count_evidence"),
        ),
        serializer_allocation_claim=False,
        final_component_claim=False,
        patch_status=patch_status,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def _field_binding_for_plan(
    *,
    plan: RoutePhysicalRowPlan,
    patch: RouteInstOperandPatch | None,
    layout_plan: InstructionLayoutPlan | None,
    exe_block: ExeBlockWriterPlan | None,
    boundary: InstructionBoundaryPlan | None,
    placement_plan_id: str | None,
) -> RouteInstFieldBindingRecord:
    operand_patch_id = patch.patch_id if patch is not None else ""
    layout_plan_id = layout_plan.plan_id if layout_plan is not None else None
    exe_block_id = exe_block.plan_id if exe_block is not None else None
    boundary_id = boundary.plan_id if boundary is not None else None
    field_owner_ids = {
        "opCode": ROUTE_BYTE_FAMILY_DECISION_ID,
        "unit_inst_type": ROUTE_BYTE_FAMILY_DECISION_ID,
        "latency": ROUTE_BYTE_FAMILY_DECISION_ID,
        "src_operands_idx[0]": operand_patch_id,
        "src_operands_idx[1]": ROUTE_OPERAND_USAGE_POLICY_ID,
        "src_operands_idx[2]": ROUTE_OPERAND_USAGE_POLICY_ID,
        "dst_operands_idx[0]": operand_patch_id,
        "dst_operands_idx[1]": ROUTE_OPERAND_USAGE_POLICY_ID,
        "dst_operands_idx[2]": ROUTE_OPERAND_USAGE_POLICY_ID,
        "dst_pes_pos[0]": plan.route_endpoint_patch_id,
        "dst_blocks_idx[0]": exe_block_id or "",
        "flow_ack": "",
        "block_idx": exe_block_id or "",
        "end_inst": boundary_id or "",
        "stage": layout_plan_id or "",
        "local_pc": plan.row_plan_id,
        "component_byte_offset": placement_plan_id or "",
    }
    field_owner_status = {
        "opCode": "bound",
        "unit_inst_type": "bound",
        "latency": "bound",
        "src_operands_idx[0]": "bound" if patch is not None else "blocked",
        "src_operands_idx[1]": "zero_with_evidence",
        "src_operands_idx[2]": "zero_with_evidence",
        "dst_operands_idx[0]": "bound" if patch is not None else "blocked",
        "dst_operands_idx[1]": "zero_with_evidence",
        "dst_operands_idx[2]": "zero_with_evidence",
        "dst_pes_pos[0]": "bound",
        "dst_blocks_idx[0]": (
            "bound" if plan.dst_block_binding_status == "bound" else "pending"
        ),
        "flow_ack": "blocked",
        "block_idx": "bound" if exe_block is not None else "pending",
        "end_inst": "bound" if boundary is not None else "pending",
        "stage": "bound" if layout_plan is not None else "pending",
        "local_pc": (
            "bound" if plan.physical_local_pc_status == "candidate_bound" else "pending"
        ),
        "component_byte_offset": "pending",
    }
    missing_fields = [
        field
        for field, status in field_owner_status.items()
        if status in {"blocked", "pending"}
    ]
    blockers = [
        ROUTE_FLOW_ACK_BLOCKER,
        ROUTE_PHYSICAL_COMPONENT_PLACEMENT_BLOCKER,
        ROUTE_COMPONENT_BLOCKER,
    ]
    if plan.physical_local_pc_status != "candidate_bound":
        blockers.insert(1, ROUTE_LOCAL_PC_BLOCKER)
    if patch is None:
        blockers.insert(0, "log10max_route_inst_operand_patch_missing")
    if plan.dst_block_binding_status != "bound":
        blockers.insert(0, "log10max_route_dst_block_binding_missing")
    return RouteInstFieldBindingRecord(
        schema_version="1",
        binding_id=f"route_field_binding:{plan.row_plan_id}",
        physical_row_plan_id=plan.row_plan_id,
        logical_route_edge_id=plan.logical_route_edge_id,
        route_byte_family_decision_id=ROUTE_BYTE_FAMILY_DECISION_ID,
        operand_patch_id=operand_patch_id,
        route_endpoint_patch_id=plan.route_endpoint_patch_id,
        flow_ack_policy_id=None,
        instruction_layout_plan_id=layout_plan_id,
        exe_block_writer_plan_id=exe_block_id,
        instruction_boundary_plan_id=boundary_id,
        component_placement_plan_id=placement_plan_id,
        field_owner_ids=tuple(sorted(field_owner_ids.items())),
        field_owner_status=tuple(sorted(field_owner_status.items())),
        missing_fields=tuple(missing_fields),
        binding_status="blocked",
        final_component_claim=False,
        runtime_ready=False,
        uploadable=False,
        blocker_ids=tuple(dict.fromkeys(blockers)),
    )


def _layout_by_row_id(
    plans: tuple[InstructionLayoutPlan, ...],
) -> dict[str, InstructionLayoutPlan]:
    result: dict[str, InstructionLayoutPlan] = {}
    for plan in plans:
        for row_id in plan.row_candidate_ids:
            result[row_id] = plan
    return result


def _boundary_by_row_id(
    plans: tuple[InstructionBoundaryPlan, ...],
) -> dict[str, InstructionBoundaryPlan]:
    result: dict[str, InstructionBoundaryPlan] = {}
    for plan in plans:
        for row_id in plan.row_candidate_ids:
            result[row_id] = plan
    return result


def _route_row_candidate_id(
    direction: Literal["push", "recv"],
    edge_id: str,
) -> str:
    return f"route_row_candidate:{direction}:{edge_id}"


def _phase_from_edge_id(edge_id: str) -> str:
    parts = edge_id.split(":")
    return parts[2] if len(parts) >= 3 else "unknown"


__all__ = [
    "EXPECTED_PHYSICAL_PHASE_COUNTS",
    "LANE_STRIDE_OPERANDS",
    "PHYSICAL_ROWS_PER_LOGICAL_EDGE",
    "ROUTE_BYTE_FAMILY_DECISION_ID",
    "ROUTE_FLOW_ACK_BLOCKER",
    "RouteInstFieldBindingRecord",
    "RouteInstFieldBindingReport",
    "RouteInstOperandPatch",
    "RouteInstOperandPatchReport",
    "RoutePhysicalRowPlan",
    "RoutePhysicalRowPlanReport",
    "build_log10max_route_inst_field_binding_report",
    "build_log10max_route_inst_operand_patch_report",
    "build_log10max_route_physical_row_plan_report",
    "summarize_log10max_route_inst_field_binding_report",
    "summarize_log10max_route_inst_operand_patch_report",
    "summarize_log10max_route_physical_row_plan_report",
]
