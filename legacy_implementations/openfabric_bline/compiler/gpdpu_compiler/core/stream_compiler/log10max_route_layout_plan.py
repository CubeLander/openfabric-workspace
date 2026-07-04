"""Report-only layout plans for log10max ring route/update rows.

This module implements Phase 1 of the route-row layout RFC.  It assigns
logical layout, exeBlock, boundary, and placement ownership records for the
log10max representative ring.  It deliberately does not choose COPY/COPYT/LDN
row bytes, does not emit raw route rows, and does not insert anything into the
final CBUF/MICC components.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, Mapping

from .log10max_ring_update_operands import (
    EXPECTED_PHASE_COUNTS,
    RingRouteOperandPatchReport,
    build_log10max_ring_route_operand_patch_report,
)
from .log10max_ring_update_template import (
    RingUpdateBinaryLayoutCandidateReport,
    build_log10max_ring_update_binary_layout_candidate_report,
)


Stage = Literal["LD", "CAL", "FLOW", "ST"]
OrderingStatus = Literal[
    "stage_order_proven",
    "block_order_proven",
    "subtask_order_proven",
    "app_boundary_proven",
    "blocked",
]
PlacementStatus = Literal[
    "unplaced_candidate",
    "placed_candidate",
    "component_integrated",
    "blocked",
]

PHASE_ORDER = ("row_reduce", "col_reduce", "col_broadcast", "row_broadcast")
ROUTE_LAYOUT_BLOCKER = "log10max_route_instruction_layout_local_pc_pending"
ROUTE_EXE_BLOCK_BLOCKER = "log10max_route_exe_block_micc_candidate_missing"
ROUTE_FLOW_ACK_BLOCKER = "log10max_route_flow_ack_policy_missing"
ROUTE_ROW_BYTES_BLOCKER = "log10max_route_row_bytes_missing"
ROUTE_COMPONENT_BLOCKER = "log10max_route_component_integration_missing"
FMAX_LAYOUT_BLOCKER = "log10max_ring_update_instruction_layout_local_pc_pending"
FMAX_COMPONENT_BLOCKER = "log10max_ring_update_component_integration_missing"
COMPONENT_PLACEMENT_BLOCKER = "log10max_route_component_placement_pending"


@dataclass(frozen=True)
class InstructionLayoutPlan:
    """PE-local row layout ownership record for a route or FMAX candidate."""

    plan_id: str
    app_id: int
    task_id: int
    pe: str
    exe_block_id: str
    stage: Stage
    local_order: int
    local_pc: int | None
    row_candidate_ids: tuple[str, ...]
    ordering_predecessor_row_ids: tuple[str, ...]
    ordering_status: OrderingStatus
    layout_status: Literal["planned", "pc_assigned", "blocked"]
    blocker_ids: tuple[str, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    def to_plan(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "app_id": self.app_id,
            "task_id": self.task_id,
            "pe": self.pe,
            "exe_block_id": self.exe_block_id,
            "stage": self.stage,
            "local_order": self.local_order,
            "local_pc": self.local_pc,
            "row_candidate_ids": list(self.row_candidate_ids),
            "ordering_predecessor_row_ids": list(self.ordering_predecessor_row_ids),
            "ordering_status": self.ordering_status,
            "layout_status": self.layout_status,
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "raw_row_bytes_claim": False,
            "component_integration_claim": False,
        }


@dataclass(frozen=True)
class ExeBlockWriterPlan:
    """Candidate MICC/exeBlock ownership record.

    V1 uses one collective phase block per PE.  The block index and stage counts
    are deterministic candidates, while MICC serialization remains blocked.
    """

    plan_id: str
    app_id: int
    task_id: int
    subtask_id: int
    pe: str
    block_idx: int
    predecessor_block_refs: tuple[str, ...]
    successor_block_refs: tuple[str, ...]
    stage_start_pc: Mapping[str, int]
    stage_instruction_counts: Mapping[str, int]
    root_or_child_status: Literal["root", "child", "mixed", "unknown"]
    writer_status: Literal["planned", "micc_candidate", "blocked"]
    blocker_ids: tuple[str, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    def to_plan(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "app_id": self.app_id,
            "task_id": self.task_id,
            "subtask_id": self.subtask_id,
            "pe": self.pe,
            "block_idx": self.block_idx,
            "predecessor_block_refs": list(self.predecessor_block_refs),
            "successor_block_refs": list(self.successor_block_refs),
            "stage_start_pc": dict(self.stage_start_pc),
            "stage_instruction_counts": dict(self.stage_instruction_counts),
            "root_or_child_status": self.root_or_child_status,
            "writer_status": self.writer_status,
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "component_integration_claim": False,
        }


@dataclass(frozen=True)
class InstructionBoundaryPlan:
    """Candidate end_inst ownership record for stage-local rows."""

    plan_id: str
    app_id: int
    task_id: int
    pe: str
    stage: str
    row_candidate_ids: tuple[str, ...]
    end_inst_by_row_candidate_id: Mapping[str, bool]
    policy: Literal["last_valid_in_stage", "source_template_fixed"]
    boundary_status: Literal["bound", "blocked"]
    blocker_ids: tuple[str, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    def to_plan(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "app_id": self.app_id,
            "task_id": self.task_id,
            "pe": self.pe,
            "stage": self.stage,
            "row_candidate_ids": list(self.row_candidate_ids),
            "end_inst_by_row_candidate_id": dict(self.end_inst_by_row_candidate_id),
            "policy": self.policy,
            "boundary_status": self.boundary_status,
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "component_integration_claim": False,
        }


@dataclass(frozen=True)
class ComponentPlacementPlan:
    """Candidate insts component placement record.

    Phase 1 keeps rows unplaced; ``component_byte_offset`` must stay ``None``.
    """

    plan_id: str
    component_name: Literal["insts"]
    app_id: int
    task_id: int
    pe: str
    row_candidate_id: str
    pe_local_pc: int
    global_row_index: int
    component_byte_offset: int | None
    placement_status: PlacementStatus
    blocker_ids: tuple[str, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def component_integration_claim(self) -> bool:
        return self.placement_status == "component_integrated"

    def to_plan(self) -> dict[str, object]:
        return {
            "plan_id": self.plan_id,
            "component_name": self.component_name,
            "app_id": self.app_id,
            "task_id": self.task_id,
            "pe": self.pe,
            "row_candidate_id": self.row_candidate_id,
            "pe_local_pc": self.pe_local_pc,
            "global_row_index": self.global_row_index,
            "component_byte_offset": self.component_byte_offset,
            "placement_status": self.placement_status,
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "component_integration_claim": self.component_integration_claim,
        }


@dataclass(frozen=True)
class Log10MaxRouteLayoutPlanReport:
    """Phase-1 report for route/update layout ownership."""

    profile_id: str
    source_route_patch_report_id: str
    source_update_layout_report_id: str
    instruction_layout_plans: tuple[InstructionLayoutPlan, ...]
    exe_block_writer_plans: tuple[ExeBlockWriterPlan, ...]
    instruction_boundary_plans: tuple[InstructionBoundaryPlan, ...]
    component_placement_plans: tuple[ComponentPlacementPlan, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def uploadable(self) -> bool:
        return False

    @property
    def raw_row_bytes_claim(self) -> bool:
        return False

    @property
    def component_integration_claim(self) -> bool:
        return False

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        for plan in self.instruction_layout_plans:
            blockers.extend(plan.blocker_ids)
        for plan in self.exe_block_writer_plans:
            blockers.extend(plan.blocker_ids)
        for plan in self.instruction_boundary_plans:
            blockers.extend(plan.blocker_ids)
        for plan in self.component_placement_plans:
            blockers.extend(plan.blocker_ids)
        if not blockers:
            blockers.append(ROUTE_ROW_BYTES_BLOCKER)
        return tuple(dict.fromkeys(blockers))

    def summary(self) -> dict[str, object]:
        stage_counts: dict[str, int] = {}
        layout_status_counts: dict[str, int] = {}
        ordering_status_counts: dict[str, int] = {}
        placement_status_counts: dict[str, int] = {}
        pe_counts: dict[str, int] = {}
        phase_counts: dict[str, int] = {}
        for plan in self.instruction_layout_plans:
            stage_counts[plan.stage] = stage_counts.get(plan.stage, 0) + 1
            layout_status_counts[plan.layout_status] = (
                layout_status_counts.get(plan.layout_status, 0) + 1
            )
            ordering_status_counts[plan.ordering_status] = (
                ordering_status_counts.get(plan.ordering_status, 0) + 1
            )
            pe_counts[plan.pe] = pe_counts.get(plan.pe, 0) + 1
            for row_id in plan.row_candidate_ids:
                phase = _phase_from_row_candidate_id(row_id)
                if phase:
                    phase_counts[phase] = phase_counts.get(phase, 0) + 1
        for plan in self.component_placement_plans:
            placement_status_counts[plan.placement_status] = (
                placement_status_counts.get(plan.placement_status, 0) + 1
            )
        return {
            "profile_id": self.profile_id,
            "source_route_patch_report_id": self.source_route_patch_report_id,
            "source_update_layout_report_id": self.source_update_layout_report_id,
            "instruction_layout_plan_count": len(self.instruction_layout_plans),
            "exe_block_writer_plan_count": len(self.exe_block_writer_plans),
            "instruction_boundary_plan_count": len(self.instruction_boundary_plans),
            "component_placement_plan_count": len(self.component_placement_plans),
            "route_candidate_count": _count_rows_with_prefix(
                self.instruction_layout_plans,
                "route_row_candidate:",
            ),
            "fmax_update_candidate_count": _count_rows_with_prefix(
                self.instruction_layout_plans,
                "binary_layout_row_candidate:",
            ),
            "stage_counts": dict(sorted(stage_counts.items())),
            "layout_status_counts": dict(sorted(layout_status_counts.items())),
            "ordering_status_counts": dict(sorted(ordering_status_counts.items())),
            "placement_status_counts": dict(sorted(placement_status_counts.items())),
            "pe_counts": dict(sorted(pe_counts.items())),
            "phase_counts": dict(sorted(phase_counts.items())),
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "raw_row_bytes_claim": self.raw_row_bytes_claim,
            "component_integration_claim": self.component_integration_claim,
            "route_family_decision": "pending_phase2_decision",
            "phase_block_policy": "one_collective_phase_per_pe_exe_block",
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_route_layout_plan_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "raw_row_bytes_claim": self.raw_row_bytes_claim,
            "component_integration_claim": self.component_integration_claim,
            "blocker_ids": list(self.blocker_ids),
            "instruction_layout_plans": [
                plan.to_plan() for plan in self.instruction_layout_plans
            ],
            "exe_block_writer_plans": [
                plan.to_plan() for plan in self.exe_block_writer_plans
            ],
            "instruction_boundary_plans": [
                plan.to_plan() for plan in self.instruction_boundary_plans
            ],
            "component_placement_plans": [
                plan.to_plan() for plan in self.component_placement_plans
            ],
            "layering_policy": (
                "Phase 1 binds route/FMAX layout ownership only. It does not "
                "select COPY/COPYT/LDN bytes, emit raw route rows, or integrate "
                "CBUF/MICC components."
            ),
        }


def build_log10max_route_layout_plan_report(
    route_patch_report: RingRouteOperandPatchReport | None = None,
    update_layout_report: RingUpdateBinaryLayoutCandidateReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_route_layout_plan_v1",
) -> Log10MaxRouteLayoutPlanReport:
    """Build report-only route/FMAX layout plans for log10max."""

    route_patches = route_patch_report or build_log10max_ring_route_operand_patch_report()
    update_layout = (
        update_layout_report
        or build_log10max_ring_update_binary_layout_candidate_report()
    )
    rows = tuple(update_layout.row_candidates)
    update_row_by_edge_token = {
        _edge_token_from_edge_id(row.source_ring_edge_id): row for row in rows
    }
    route_patch_by_key = {
        (patch.source_ring_edge_id, patch.direction): patch
        for patch in route_patches.patches
    }
    local_order_by_exe_block: dict[str, int] = {}
    layout_plans: list[InstructionLayoutPlan] = []
    placement_plans: list[ComponentPlacementPlan] = []

    for row in rows:
        push_patch = route_patch_by_key[(row.source_ring_edge_id, "push")]
        recv_patch = route_patch_by_key[(row.source_ring_edge_id, "recv")]
        push_row_id = _route_row_candidate_id("push", row.source_ring_edge_id)
        recv_row_id = _route_row_candidate_id("recv", row.source_ring_edge_id)
        fmax_row_id = row.row_candidate_id
        route_exe_block = _exe_block_id(row.task_id, row.dst_pe, row.phase)
        push_exe_block = _exe_block_id(row.task_id, row.src_pe, row.phase)
        fmax_exe_block = route_exe_block
        push_predecessors = _push_ordering_predecessors(
            push_patch.src_placeholders,
            update_row_by_edge_token,
        )
        layout_plans.append(
            _layout_plan(
                row_candidate_id=push_row_id,
                app_id=0,
                task_id=row.task_id,
                pe=row.src_pe,
                exe_block_id=push_exe_block,
                stage="FLOW",
                local_order_by_exe_block=local_order_by_exe_block,
                ordering_predecessor_row_ids=push_predecessors,
                ordering_status=(
                    "block_order_proven" if push_predecessors else "stage_order_proven"
                ),
                blockers=(ROUTE_LAYOUT_BLOCKER, ROUTE_ROW_BYTES_BLOCKER),
            )
        )
        layout_plans.append(
            _layout_plan(
                row_candidate_id=recv_row_id,
                app_id=0,
                task_id=row.task_id,
                pe=row.dst_pe,
                exe_block_id=route_exe_block,
                stage="FLOW",
                local_order_by_exe_block=local_order_by_exe_block,
                ordering_predecessor_row_ids=(push_row_id,),
                ordering_status="block_order_proven",
                blockers=(
                    ROUTE_LAYOUT_BLOCKER,
                    ROUTE_FLOW_ACK_BLOCKER,
                    ROUTE_ROW_BYTES_BLOCKER,
                ),
            )
        )
        layout_plans.append(
            _layout_plan(
                row_candidate_id=fmax_row_id,
                app_id=0,
                task_id=row.task_id,
                pe=row.dst_pe,
                exe_block_id=fmax_exe_block,
                stage="CAL",
                local_order_by_exe_block=local_order_by_exe_block,
                ordering_predecessor_row_ids=(recv_row_id,),
                ordering_status="block_order_proven",
                blockers=(FMAX_LAYOUT_BLOCKER, FMAX_COMPONENT_BLOCKER),
            )
        )

    exe_blocks = _build_exe_block_plans(layout_plans)
    boundaries = _build_boundary_plans(layout_plans)
    for plan in layout_plans:
        row_id = plan.row_candidate_ids[0]
        placement_plans.append(
            ComponentPlacementPlan(
                plan_id=f"component_placement:{row_id}",
                component_name="insts",
                app_id=plan.app_id,
                task_id=plan.task_id,
                pe=plan.pe,
                row_candidate_id=row_id,
                pe_local_pc=-1,
                global_row_index=-1,
                component_byte_offset=None,
                placement_status="unplaced_candidate",
                blocker_ids=(COMPONENT_PLACEMENT_BLOCKER, ROUTE_COMPONENT_BLOCKER),
            )
        )
    return Log10MaxRouteLayoutPlanReport(
        profile_id=profile_id,
        source_route_patch_report_id=route_patches.profile_id,
        source_update_layout_report_id=update_layout.profile_id,
        instruction_layout_plans=tuple(layout_plans),
        exe_block_writer_plans=exe_blocks,
        instruction_boundary_plans=boundaries,
        component_placement_plans=tuple(placement_plans),
    )


def summarize_log10max_route_layout_plan_report(
    report: Log10MaxRouteLayoutPlanReport,
) -> dict[str, object]:
    return report.summary()


def _layout_plan(
    *,
    row_candidate_id: str,
    app_id: int,
    task_id: int,
    pe: str,
    exe_block_id: str,
    stage: Stage,
    local_order_by_exe_block: dict[str, int],
    ordering_predecessor_row_ids: tuple[str, ...],
    ordering_status: OrderingStatus,
    blockers: tuple[str, ...],
) -> InstructionLayoutPlan:
    local_order = local_order_by_exe_block.get(exe_block_id, 0)
    local_order_by_exe_block[exe_block_id] = local_order + 1
    return InstructionLayoutPlan(
        plan_id=f"instruction_layout:{row_candidate_id}",
        app_id=app_id,
        task_id=task_id,
        pe=pe,
        exe_block_id=exe_block_id,
        stage=stage,
        local_order=local_order,
        local_pc=None,
        row_candidate_ids=(row_candidate_id,),
        ordering_predecessor_row_ids=ordering_predecessor_row_ids,
        ordering_status=ordering_status,
        layout_status="planned",
        blocker_ids=blockers,
    )


def _build_exe_block_plans(
    layout_plans: tuple[InstructionLayoutPlan, ...] | list[InstructionLayoutPlan],
) -> tuple[ExeBlockWriterPlan, ...]:
    plans_by_block: dict[str, list[InstructionLayoutPlan]] = {}
    for plan in layout_plans:
        plans_by_block.setdefault(plan.exe_block_id, []).append(plan)
    result: list[ExeBlockWriterPlan] = []
    for block_index, (block_id, plans) in enumerate(sorted(plans_by_block.items())):
        first = plans[0]
        counts = {stage: 0 for stage in ("LD", "CAL", "FLOW", "ST")}
        for plan in plans:
            counts[plan.stage] += len(plan.row_candidate_ids)
        stage_start_pc: dict[str, int] = {}
        next_pc = 0
        for stage in ("LD", "CAL", "FLOW", "ST"):
            stage_start_pc[stage] = next_pc
            next_pc += counts[stage]
        result.append(
            ExeBlockWriterPlan(
                plan_id=f"exe_block_writer:{block_id}",
                app_id=first.app_id,
                task_id=first.task_id,
                subtask_id=_phase_index_from_block_id(block_id),
                pe=first.pe,
                block_idx=block_index,
                predecessor_block_refs=tuple(
                    dict.fromkeys(
                        predecessor
                        for plan in plans
                        for predecessor in plan.ordering_predecessor_row_ids
                    )
                ),
                successor_block_refs=(),
                stage_start_pc=stage_start_pc,
                stage_instruction_counts=counts,
                root_or_child_status="mixed" if counts["FLOW"] and counts["CAL"] else "child",
                writer_status="planned",
                blocker_ids=(ROUTE_EXE_BLOCK_BLOCKER, ROUTE_COMPONENT_BLOCKER),
            )
        )
    return tuple(result)


def _build_boundary_plans(
    layout_plans: tuple[InstructionLayoutPlan, ...] | list[InstructionLayoutPlan],
) -> tuple[InstructionBoundaryPlan, ...]:
    by_key: dict[tuple[int, str, str, str], list[InstructionLayoutPlan]] = {}
    for plan in layout_plans:
        key = (plan.task_id, plan.pe, plan.exe_block_id, plan.stage)
        by_key.setdefault(key, []).append(plan)
    result: list[InstructionBoundaryPlan] = []
    for (task_id, pe, exe_block_id, stage), plans in sorted(by_key.items()):
        ordered = sorted(plans, key=lambda plan: plan.local_order)
        row_ids = tuple(row_id for plan in ordered for row_id in plan.row_candidate_ids)
        result.append(
            InstructionBoundaryPlan(
                plan_id=f"instruction_boundary:{exe_block_id}:{stage}",
                app_id=ordered[0].app_id,
                task_id=task_id,
                pe=pe,
                stage=stage,
                row_candidate_ids=row_ids,
                end_inst_by_row_candidate_id={
                    row_id: index == len(row_ids) - 1
                    for index, row_id in enumerate(row_ids)
                },
                policy="last_valid_in_stage",
                boundary_status="bound",
                blocker_ids=(ROUTE_COMPONENT_BLOCKER,),
            )
        )
    return tuple(result)


def _route_row_candidate_id(direction: Literal["push", "recv"], edge_id: str) -> str:
    return f"route_row_candidate:{direction}:{edge_id}"


def _exe_block_id(task_id: int, pe: str, phase: str) -> str:
    return f"exe_block:log10max_ring:task{task_id}:{_pe_token(pe)}:{phase}"


def _push_ordering_predecessors(
    src_placeholders: tuple[str, ...],
    update_row_by_edge_token: dict[str, object],
) -> tuple[str, ...]:
    predecessors: list[str] = []
    for placeholder in src_placeholders:
        edge_token = _edge_token_from_placeholder(placeholder)
        if edge_token is None:
            continue
        row = update_row_by_edge_token.get(edge_token)
        if row is not None:
            predecessors.append(getattr(row, "row_candidate_id"))
    return tuple(dict.fromkeys(predecessors))


def _edge_token_from_placeholder(placeholder_id: str) -> str | None:
    for part in placeholder_id.split(":"):
        if part.startswith("ring_edge_"):
            return part.removeprefix("ring_edge_")
    return None


def _edge_token_from_edge_id(edge_id: str) -> str:
    parts = edge_id.split(":")
    return parts[1] if len(parts) > 1 else ""


def _phase_index_from_block_id(block_id: str) -> int:
    phase = block_id.rsplit(":", 1)[-1]
    return PHASE_ORDER.index(phase) if phase in PHASE_ORDER else -1


def _pe_token(pe: str) -> str:
    return (
        pe.replace("PE(", "pe")
        .replace(")", "")
        .replace(",", "_")
        .replace(" ", "")
    )


def _phase_from_row_candidate_id(row_candidate_id: str) -> str:
    for phase in PHASE_ORDER:
        if f":{phase}:" in row_candidate_id:
            return phase
    return ""


def _count_rows_with_prefix(
    plans: tuple[InstructionLayoutPlan, ...],
    prefix: str,
) -> int:
    return sum(
        1
        for plan in plans
        for row_id in plan.row_candidate_ids
        if row_id.startswith(prefix)
    )


__all__ = [
    "COMPONENT_PLACEMENT_BLOCKER",
    "FMAX_COMPONENT_BLOCKER",
    "FMAX_LAYOUT_BLOCKER",
    "PHASE_ORDER",
    "ROUTE_COMPONENT_BLOCKER",
    "ROUTE_EXE_BLOCK_BLOCKER",
    "ROUTE_FLOW_ACK_BLOCKER",
    "ROUTE_LAYOUT_BLOCKER",
    "ROUTE_ROW_BYTES_BLOCKER",
    "ComponentPlacementPlan",
    "ExeBlockWriterPlan",
    "InstructionBoundaryPlan",
    "InstructionLayoutPlan",
    "Log10MaxRouteLayoutPlanReport",
    "build_log10max_route_layout_plan_report",
    "summarize_log10max_route_layout_plan_report",
]
