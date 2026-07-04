"""Phase-2A route byte family decision for log10max GlobalMax routes.

This module deliberately stops before raw route bytes.  It chooses the
candidate route family and derives physical COPY row plans from the Phase-0
``RouteEndpointPatch`` records, but it does not pack inst_t rows, does not
insert rows into final components, and does not change runtime readiness.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from gpdpu_compiler.core.program_legacy_inst import (
    FLOW_UNIT_INST_TYPE,
    LEGACY_OPS,
    OP_COPY_LATENCY,
    OPERANDS_PER_OPERAND_RAM,
    OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE,
)

from .log10max_ring_update_operands import EXPECTED_PHASE_COUNTS
from .log10max_route_endpoint_patch import (
    LOG10MAX_ROUTE_COMPONENT_INTEGRATION_BLOCKER,
    LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER,
    LOG10MAX_ROUTE_ROW_BYTES_BLOCKER,
    RouteEndpointPatch,
    RouteEndpointPatchReport,
    build_log10max_route_endpoint_patch_report,
)
from .log10max_route_layout_plan import (
    Log10MaxRouteLayoutPlanReport,
    build_log10max_route_layout_plan_report,
)


LOG10MAX_ROUTE_BYTE_FAMILY_DECISION_ID = (
    "route_family_decision:log10max:copyt_logical_globalmax_route:v1"
)
LOG10MAX_ROUTE_FAMILY_DECISION_BLOCKER = (
    "log10max_route_byte_family_candidate_only"
)
LOG10MAX_ROUTE_PHYSICAL_ROW_BYTES_BLOCKER = "log10max_route_row_bytes_missing"
LOG10MAX_ROUTE_PHYSICAL_COMPONENT_BLOCKER = (
    "log10max_route_component_integration_missing"
)


@dataclass(frozen=True)
class RouteByteFamilyDecision:
    """Report-only V1 route family choice for one logical route kind."""

    schema_version: str
    decision_id: str
    operator: Literal["log10max"]
    collective_strategy: Literal["ring_spmd_row_then_col"]
    logical_family: Literal["copyt_logical_globalmax_route"]
    physical_family: Literal["copyt_logical_expanded_copy_rows"]
    route_opcode_family: Literal["COPYT"]
    physical_opcode_name: Literal["COPY"]
    physical_opcode: int
    physical_unit_inst_type: int
    physical_latency: int
    logical_value_kind: Literal["replicated_vector"]
    dtype: Literal["fp32"]
    logical_width_bits: int
    lane_count: int
    lane_stride: int
    source_template_family: Literal["COPYT"]
    route_family_status: Literal["selected_candidate"]
    flow_ack_policy_status: Literal["pending_policy"]
    blocker_ids: tuple[str, ...]

    @property
    def row_bytes_claim(self) -> bool:
        return False

    @property
    def final_component_claim(self) -> bool:
        return False

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def uploadable(self) -> bool:
        return False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "decision_id": self.decision_id,
            "operator": self.operator,
            "collective_strategy": self.collective_strategy,
            "logical_family": self.logical_family,
            "physical_family": self.physical_family,
            "route_opcode_family": self.route_opcode_family,
            "physical_opcode_name": self.physical_opcode_name,
            "physical_opcode": self.physical_opcode,
            "physical_unit_inst_type": self.physical_unit_inst_type,
            "physical_latency": self.physical_latency,
            "logical_value_kind": self.logical_value_kind,
            "dtype": self.dtype,
            "logical_width_bits": self.logical_width_bits,
            "lane_count": self.lane_count,
            "lane_stride": self.lane_stride,
            "source_template_family": self.source_template_family,
            "route_family_status": self.route_family_status,
            "flow_ack_policy_status": self.flow_ack_policy_status,
            "blocker_ids": list(self.blocker_ids),
            "row_bytes_claim": self.row_bytes_claim,
            "final_component_claim": self.final_component_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }


@dataclass(frozen=True)
class RouteByteFamilyDecisionReport:
    """Phase-2A route family decision report."""

    profile_id: str
    source_endpoint_report_id: str
    decision: RouteByteFamilyDecision

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def uploadable(self) -> bool:
        return False

    @property
    def row_bytes_claim(self) -> bool:
        return False

    @property
    def final_component_claim(self) -> bool:
        return False

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        return self.decision.blocker_ids

    def summary(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "source_endpoint_report_id": self.source_endpoint_report_id,
            "decision_id": self.decision.decision_id,
            "logical_family": self.decision.logical_family,
            "physical_family": self.decision.physical_family,
            "route_opcode_family": self.decision.route_opcode_family,
            "physical_opcode_name": self.decision.physical_opcode_name,
            "physical_opcode": self.decision.physical_opcode,
            "physical_unit_inst_type": self.decision.physical_unit_inst_type,
            "physical_latency": self.decision.physical_latency,
            "logical_value_kind": self.decision.logical_value_kind,
            "dtype": self.decision.dtype,
            "logical_width_bits": self.decision.logical_width_bits,
            "lane_count": self.decision.lane_count,
            "lane_stride": self.decision.lane_stride,
            "route_family_status": self.decision.route_family_status,
            "flow_ack_policy_status": self.decision.flow_ack_policy_status,
            "blocker_ids": list(self.blocker_ids),
            "row_bytes_claim": self.row_bytes_claim,
            "final_component_claim": self.final_component_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_route_byte_family_decision_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "row_bytes_claim": self.row_bytes_claim,
            "final_component_claim": self.final_component_claim,
            "blocker_ids": list(self.blocker_ids),
            "decision": self.decision.to_plan(),
            "layering_policy": (
                "Phase 2A chooses the route byte family only. It does not "
                "pack COPY rows, bind flow_ack, insert component bytes, or "
                "change runtime_ready."
            ),
        }


@dataclass(frozen=True)
class RoutePhysicalRowPlan:
    """Physical COPY lane-row plan derived from one logical route edge."""

    schema_version: str
    row_plan_id: str
    logical_route_edge_id: str
    route_endpoint_patch_id: str
    route_family_decision_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    app_id: int
    task_id: int
    src_pe: str
    dst_pe: str
    dst_pe_pos: tuple[int, int, int]
    lane_index: int
    lane_count: int
    lane_stride: int
    source_template_family: Literal["COPYT"]
    physical_opcode_name: Literal["COPY"]
    physical_opcode: int
    physical_unit_inst_type: int
    physical_latency: int
    src_operand_allocation_id: str
    dst_operand_allocation_id: str
    src_operand_base_idx: int
    dst_operand_base_idx: int
    src_operand_idx: int
    dst_operand_idx: int
    src_allocation_scope: str
    dst_allocation_scope: str
    expected_src_allocation_scope: str
    expected_dst_allocation_scope: str
    dst_block_idx: int | None
    dst_block_binding_status: Literal["pending_layout", "bound"]
    sender_layout_plan_id: str | None
    receiver_layout_plan_id: str | None
    receiver_exe_block_writer_plan_id: str | None
    physical_local_order: int | None
    physical_local_pc: int | None
    physical_local_pc_status: Literal["candidate_bound", "pending_layout"]
    flow_ack: int | None
    flow_ack_policy_id: str | None
    flow_ack_status: Literal["pending_policy", "bound"]
    lane_policy_id: str
    plan_status: Literal["physical_row_planned", "blocked"]
    blocker_ids: tuple[str, ...]

    @property
    def row_bytes_claim(self) -> bool:
        return False

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
    def physical_row_plan_id(self) -> str:
        return self.row_plan_id

    @property
    def lane_stride_operands(self) -> int:
        return self.lane_stride

    @property
    def src_operand_idx_before_lane_delta(self) -> int:
        return self.src_operand_base_idx

    @property
    def dst_operand_idx_before_lane_delta(self) -> int:
        return self.dst_operand_base_idx

    @property
    def dst_block_status(self) -> str:
        return self.dst_block_binding_status

    @property
    def status(self) -> str:
        return self.plan_status

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "row_plan_id": self.row_plan_id,
            "logical_route_edge_id": self.logical_route_edge_id,
            "route_endpoint_patch_id": self.route_endpoint_patch_id,
            "route_family_decision_id": self.route_family_decision_id,
            "phase": self.phase,
            "app_id": self.app_id,
            "task_id": self.task_id,
            "src_pe": self.src_pe,
            "dst_pe": self.dst_pe,
            "dst_pe_pos": list(self.dst_pe_pos),
            "lane_index": self.lane_index,
            "lane_count": self.lane_count,
            "lane_stride": self.lane_stride,
            "source_template_family": self.source_template_family,
            "physical_opcode_name": self.physical_opcode_name,
            "physical_opcode": self.physical_opcode,
            "physical_unit_inst_type": self.physical_unit_inst_type,
            "physical_latency": self.physical_latency,
            "src_operand_allocation_id": self.src_operand_allocation_id,
            "dst_operand_allocation_id": self.dst_operand_allocation_id,
            "src_operand_base_idx": self.src_operand_base_idx,
            "dst_operand_base_idx": self.dst_operand_base_idx,
            "src_operand_idx": self.src_operand_idx,
            "dst_operand_idx": self.dst_operand_idx,
            "src_allocation_scope": self.src_allocation_scope,
            "dst_allocation_scope": self.dst_allocation_scope,
            "expected_src_allocation_scope": self.expected_src_allocation_scope,
            "expected_dst_allocation_scope": self.expected_dst_allocation_scope,
            "dst_block_idx": self.dst_block_idx,
            "dst_block_binding_status": self.dst_block_binding_status,
            "sender_layout_plan_id": self.sender_layout_plan_id,
            "receiver_layout_plan_id": self.receiver_layout_plan_id,
            "receiver_exe_block_writer_plan_id": (
                self.receiver_exe_block_writer_plan_id
            ),
            "physical_local_order": self.physical_local_order,
            "physical_local_pc": self.physical_local_pc,
            "physical_local_pc_status": self.physical_local_pc_status,
            "flow_ack": self.flow_ack,
            "flow_ack_policy_id": self.flow_ack_policy_id,
            "flow_ack_status": self.flow_ack_status,
            "lane_policy_id": self.lane_policy_id,
            "plan_status": self.plan_status,
            "blocker_ids": list(self.blocker_ids),
            "row_bytes_claim": self.row_bytes_claim,
            "final_component_claim": self.final_component_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }


@dataclass(frozen=True)
class RoutePhysicalRowPlanReport:
    """Phase-2A physical COPY row plan report; no bytes are emitted."""

    profile_id: str
    source_endpoint_report_id: str
    source_decision_report_id: str
    source_layout_report_id: str
    decision_id: str
    physical_rows: tuple[RoutePhysicalRowPlan, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def uploadable(self) -> bool:
        return False

    @property
    def row_bytes_claim(self) -> bool:
        return False

    @property
    def final_component_claim(self) -> bool:
        return False

    @property
    def plans(self) -> tuple[RoutePhysicalRowPlan, ...]:
        return self.physical_rows

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.physical_rows:
            blockers.append("log10max_route_physical_row_plan_missing")
        for row in self.physical_rows:
            blockers.extend(row.blocker_ids)
        return tuple(dict.fromkeys(blockers))

    def summary(self) -> dict[str, object]:
        phase_counts: dict[str, int] = {}
        lane_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        opcode_counts: dict[str, int] = {}
        flow_ack_counts: dict[str, int] = {}
        dst_block_counts: dict[str, int] = {}
        local_pc_counts: dict[str, int] = {}
        edge_ids = {row.logical_route_edge_id for row in self.physical_rows}
        for row in self.physical_rows:
            phase_counts[row.phase] = phase_counts.get(row.phase, 0) + 1
            lane_counts[str(row.lane_index)] = lane_counts.get(str(row.lane_index), 0) + 1
            status_counts[row.plan_status] = status_counts.get(row.plan_status, 0) + 1
            opcode_counts[row.physical_opcode_name] = (
                opcode_counts.get(row.physical_opcode_name, 0) + 1
            )
            flow_ack_counts[row.flow_ack_status] = (
                flow_ack_counts.get(row.flow_ack_status, 0) + 1
            )
            dst_block_counts[row.dst_block_binding_status] = (
                dst_block_counts.get(row.dst_block_binding_status, 0) + 1
            )
            local_pc_counts[row.physical_local_pc_status] = (
                local_pc_counts.get(row.physical_local_pc_status, 0) + 1
            )
        return {
            "profile_id": self.profile_id,
            "source_endpoint_report_id": self.source_endpoint_report_id,
            "source_decision_report_id": self.source_decision_report_id,
            "source_layout_report_id": self.source_layout_report_id,
            "decision_id": self.decision_id,
            "logical_route_edge_count": len(edge_ids),
            "physical_row_count": len(self.physical_rows),
            "physical_row_plan_count": len(self.physical_rows),
            "phase_counts": dict(sorted(phase_counts.items())),
            "expected_phase_counts": {
                phase: count * OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE
                for phase, count in sorted(EXPECTED_PHASE_COUNTS.items())
            },
            "lane_counts": dict(sorted(lane_counts.items())),
            "plan_status_counts": dict(sorted(status_counts.items())),
            "physical_opcode_counts": dict(sorted(opcode_counts.items())),
            "flow_ack_status_counts": dict(sorted(flow_ack_counts.items())),
            "dst_block_binding_status_counts": dict(sorted(dst_block_counts.items())),
            "physical_local_pc_status_counts": dict(sorted(local_pc_counts.items())),
            "lane_count": OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE,
            "lane_stride": OPERANDS_PER_OPERAND_RAM,
            "route_family_status": "selected_candidate",
            "physical_row_family": "copyt_logical_expanded_copy_rows",
            "blocker_ids": list(self.blocker_ids),
            "row_bytes_claim": self.row_bytes_claim,
            "final_component_claim": self.final_component_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_route_physical_row_plan_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "row_bytes_claim": self.row_bytes_claim,
            "final_component_claim": self.final_component_claim,
            "blocker_ids": list(self.blocker_ids),
            "physical_rows": [row.to_plan() for row in self.physical_rows],
            "layering_policy": (
                "Each row is a physical COPY lane candidate derived from a "
                "logical COPYT GlobalMax route edge. No inst_t bytes or final "
                "component rows are emitted in Phase 2A."
            ),
        }


def build_log10max_route_byte_family_decision_report(
    endpoint_report: RouteEndpointPatchReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_route_byte_family_decision_v1",
) -> RouteByteFamilyDecisionReport:
    endpoint = endpoint_report or build_log10max_route_endpoint_patch_report()
    copy_op = LEGACY_OPS["COPY"]
    decision = RouteByteFamilyDecision(
        schema_version="1",
        decision_id=LOG10MAX_ROUTE_BYTE_FAMILY_DECISION_ID,
        operator="log10max",
        collective_strategy="ring_spmd_row_then_col",
        logical_family="copyt_logical_globalmax_route",
        physical_family="copyt_logical_expanded_copy_rows",
        route_opcode_family="COPYT",
        physical_opcode_name="COPY",
        physical_opcode=copy_op.opcode,
        physical_unit_inst_type=FLOW_UNIT_INST_TYPE,
        physical_latency=OP_COPY_LATENCY,
        logical_value_kind="replicated_vector",
        dtype="fp32",
        logical_width_bits=4096,
        lane_count=OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE,
        lane_stride=OPERANDS_PER_OPERAND_RAM,
        source_template_family="COPYT",
        route_family_status="selected_candidate",
        flow_ack_policy_status="pending_policy",
        blocker_ids=(
            LOG10MAX_ROUTE_FAMILY_DECISION_BLOCKER,
            LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER,
            LOG10MAX_ROUTE_ROW_BYTES_BLOCKER,
            LOG10MAX_ROUTE_COMPONENT_INTEGRATION_BLOCKER,
        ),
    )
    return RouteByteFamilyDecisionReport(
        profile_id=profile_id,
        source_endpoint_report_id=endpoint.profile_id,
        decision=decision,
    )


def summarize_log10max_route_byte_family_decision_report(
    report: RouteByteFamilyDecisionReport,
) -> dict[str, object]:
    return report.summary()


def build_log10max_route_physical_row_plan_report(
    endpoint_report: RouteEndpointPatchReport | None = None,
    decision_report: RouteByteFamilyDecisionReport | None = None,
    layout_report: Log10MaxRouteLayoutPlanReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_route_physical_row_plan_v1",
) -> RoutePhysicalRowPlanReport:
    endpoint = endpoint_report or build_log10max_route_endpoint_patch_report()
    decision_report = decision_report or build_log10max_route_byte_family_decision_report(
        endpoint
    )
    layout_report = layout_report or build_log10max_route_layout_plan_report()
    decision = decision_report.decision
    layout_by_row = _layout_by_row_id(layout_report.instruction_layout_plans)
    exe_by_block = {
        plan.plan_id.removeprefix("exe_block_writer:"): plan
        for plan in layout_report.exe_block_writer_plans
    }
    physical_rows: list[RoutePhysicalRowPlan] = []
    for patch in endpoint.patches:
        physical_rows.extend(
            _physical_rows_for_endpoint(
                patch,
                decision,
                layout_by_row=layout_by_row,
                exe_by_block=exe_by_block,
            )
        )
    return RoutePhysicalRowPlanReport(
        profile_id=profile_id,
        source_endpoint_report_id=endpoint.profile_id,
        source_decision_report_id=decision_report.profile_id,
        source_layout_report_id=layout_report.profile_id,
        decision_id=decision.decision_id,
        physical_rows=tuple(physical_rows),
    )


def summarize_log10max_route_physical_row_plan_report(
    report: RoutePhysicalRowPlanReport,
) -> dict[str, object]:
    return report.summary()


def _physical_rows_for_endpoint(
    patch: RouteEndpointPatch,
    decision: RouteByteFamilyDecision,
    *,
    layout_by_row: dict[str, object],
    exe_by_block: dict[str, object],
) -> tuple[RoutePhysicalRowPlan, ...]:
    rows: list[RoutePhysicalRowPlan] = []
    sender_row = _route_row_candidate_id("push", patch.logical_route_edge_id)
    receiver_row = _route_row_candidate_id("recv", patch.logical_route_edge_id)
    sender_layout = layout_by_row.get(sender_row)
    receiver_layout = layout_by_row.get(receiver_row)
    receiver_exe_block = (
        exe_by_block.get(receiver_layout.exe_block_id)
        if receiver_layout is not None
        else None
    )
    dst_block_idx = (
        receiver_exe_block.block_idx if receiver_exe_block is not None else None
    )
    dst_block_status = "bound" if receiver_exe_block is not None else "pending_layout"
    plan_status: Literal["physical_row_planned", "blocked"] = (
        "physical_row_planned"
        if patch.patch_status in {"endpoint_bound", "endpoint_bound_layout_pending"}
        else "blocked"
    )
    for lane in range(decision.lane_count):
        blockers = [
            LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER,
            LOG10MAX_ROUTE_PHYSICAL_ROW_BYTES_BLOCKER,
            LOG10MAX_ROUTE_PHYSICAL_COMPONENT_BLOCKER,
        ]
        physical_local_order = (
            sender_layout.local_order * decision.lane_count + lane
            if sender_layout is not None
            else None
        )
        physical_local_pc = physical_local_order
        physical_local_pc_status = (
            "candidate_bound" if physical_local_pc is not None else "pending_layout"
        )
        if dst_block_status != "bound":
            blockers.insert(0, "log10max_route_dst_block_binding_missing")
        if physical_local_pc_status != "candidate_bound":
            blockers.insert(0, "log10max_route_physical_local_pc_missing")
        src_operand = patch.src_operand_idx + lane * decision.lane_stride
        dst_operand = patch.dst_operand_idx + lane * decision.lane_stride
        row_id = (
            "route_physical_row_plan:"
            f"{patch.logical_route_edge_id}:copy_lane{lane}"
        )
        rows.append(
            RoutePhysicalRowPlan(
                schema_version="1",
                row_plan_id=row_id,
                logical_route_edge_id=patch.logical_route_edge_id,
                route_endpoint_patch_id=patch.patch_id,
                route_family_decision_id=decision.decision_id,
                phase=patch.phase,
                app_id=patch.app_id,
                task_id=patch.task_id,
                src_pe=patch.src_pe,
                dst_pe=patch.dst_pe,
                dst_pe_pos=patch.dst_pe_pos,
                lane_index=lane,
                lane_count=decision.lane_count,
                lane_stride=decision.lane_stride,
                source_template_family=decision.source_template_family,
                physical_opcode_name=decision.physical_opcode_name,
                physical_opcode=decision.physical_opcode,
                physical_unit_inst_type=decision.physical_unit_inst_type,
                physical_latency=decision.physical_latency,
                src_operand_allocation_id=patch.src_operand_allocation_id,
                dst_operand_allocation_id=patch.dst_operand_allocation_id,
                src_operand_base_idx=patch.src_operand_idx,
                dst_operand_base_idx=patch.dst_operand_idx,
                src_operand_idx=src_operand,
                dst_operand_idx=dst_operand,
                src_allocation_scope=patch.src_allocation_scope,
                dst_allocation_scope=patch.dst_allocation_scope,
                expected_src_allocation_scope=patch.expected_src_allocation_scope,
                expected_dst_allocation_scope=patch.expected_dst_allocation_scope,
                dst_block_idx=dst_block_idx,
                dst_block_binding_status=dst_block_status,
                sender_layout_plan_id=(
                    sender_layout.plan_id if sender_layout is not None else None
                ),
                receiver_layout_plan_id=(
                    receiver_layout.plan_id if receiver_layout is not None else None
                ),
                receiver_exe_block_writer_plan_id=(
                    receiver_exe_block.plan_id
                    if receiver_exe_block is not None
                    else None
                ),
                physical_local_order=physical_local_order,
                physical_local_pc=physical_local_pc,
                physical_local_pc_status=physical_local_pc_status,
                flow_ack=None,
                flow_ack_policy_id=None,
                flow_ack_status="pending_policy",
                lane_policy_id=(
                    "lane_policy:copyt_logical_expanded_copy_rows:"
                    f"stride{decision.lane_stride}:lanes{decision.lane_count}"
                ),
                plan_status=plan_status,
                blocker_ids=blockers,
            )
        )
    return tuple(rows)


def _layout_by_row_id(plans: tuple[object, ...]) -> dict[str, object]:
    result: dict[str, object] = {}
    for plan in plans:
        for row_id in plan.row_candidate_ids:
            result[row_id] = plan
    return result


def _route_row_candidate_id(
    direction: Literal["push", "recv"],
    edge_id: str,
) -> str:
    return f"route_row_candidate:{direction}:{edge_id}"


__all__ = [
    "LOG10MAX_ROUTE_BYTE_FAMILY_DECISION_ID",
    "LOG10MAX_ROUTE_FAMILY_DECISION_BLOCKER",
    "LOG10MAX_ROUTE_PHYSICAL_COMPONENT_BLOCKER",
    "LOG10MAX_ROUTE_PHYSICAL_ROW_BYTES_BLOCKER",
    "RouteByteFamilyDecision",
    "RouteByteFamilyDecisionReport",
    "RoutePhysicalRowPlan",
    "RoutePhysicalRowPlanReport",
    "build_log10max_route_byte_family_decision_report",
    "build_log10max_route_physical_row_plan_report",
    "summarize_log10max_route_byte_family_decision_report",
    "summarize_log10max_route_physical_row_plan_report",
]
