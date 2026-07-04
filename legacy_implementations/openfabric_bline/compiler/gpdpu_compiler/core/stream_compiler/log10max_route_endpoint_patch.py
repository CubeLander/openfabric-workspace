"""Report-only route endpoint closure for log10max ring GlobalMax edges.

This module is Phase 0 of the route-row RFC.  It joins each logical ring edge
with already allocation-backed route push/recv operands and receiver PE
coordinates, while deliberately leaving COPY/COPYT/LDN family selection,
``flow_ack``, block layout, row bytes, and component integration blocked.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .log10max_ring_update_operands import (
    EXPECTED_PHASE_COUNTS,
    InstOperandPatch,
    RingRouteOperandPatchReport,
    RouteOperandPatch,
    build_log10max_ring_route_operand_patch_report,
    build_log10max_ring_update_inst_operand_patch_report,
)


LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER = (
    "log10max_route_flow_ack_policy_missing"
)
LOG10MAX_ROUTE_FAMILY_PHASE2_BLOCKER = (
    "log10max_route_family_phase2_decision_missing"
)
LOG10MAX_ROUTE_DST_BLOCK_LAYOUT_BLOCKER = (
    "log10max_route_dst_block_layout_pending"
)
LOG10MAX_ROUTE_ROW_BYTES_BLOCKER = "log10max_route_row_bytes_missing"
LOG10MAX_ROUTE_COMPONENT_INTEGRATION_BLOCKER = (
    "log10max_route_component_integration_missing"
)


@dataclass(frozen=True)
class RouteEndpointPatch:
    """Logical route-edge endpoint patch; no physical route rows are claimed."""

    schema_version: str
    patch_id: str
    operator: Literal["log10max"]
    collective_strategy: Literal["ring_spmd_row_then_col"]
    logical_route_edge_id: str
    source_ring_edge_id: str
    physical_route_row_candidate_ids: tuple[str, ...]
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    app_id: int
    task_id: int
    src_pe: str
    dst_pe: str
    sender_stream_action_id: str
    receiver_stream_action_id: str
    sender_fiber_op_id: str
    receiver_fiber_op_id: str
    route_opcode_family: Literal[
        "COPY",
        "COPYT",
        "LDN",
        "source_template_fixed",
        "undecided",
    ]
    route_family_status: Literal[
        "pending_phase2_decision",
        "selected",
        "blocked",
    ]
    route_family_decision_id: str | None
    base_materialization: Literal["native_template_row", "source_template_fixed"]
    src_operand_allocation_id: str
    dst_operand_allocation_id: str
    src_route_operand_patch_id: str | None
    dst_route_operand_patch_id: str | None
    src_operand_idx: int
    dst_operand_idx: int
    src_allocation_scope: str
    dst_allocation_scope: str
    expected_src_allocation_scope: str
    expected_dst_allocation_scope: str
    sender_scope_status: Literal["sender_task_pe", "blocked"]
    receiver_scope_status: Literal["receiver_task_pe", "blocked"]
    src_placeholder_id: str
    dst_placeholder_id: str
    fmax_src_received_placeholder_id: str
    fmax_src_received_allocation_id: str
    fmax_src_received_operand_idx: int
    push_source_continuity: Literal[
        "local_reduce_max_out",
        "previous_globalmax_acc_out",
        "blocked",
    ]
    recv_to_fmax_continuity_status: Literal["matched", "blocked"]
    dst_pe_pos: tuple[int, int, int]
    dst_pe_coord_status: Literal["source_backed", "profile_backed", "blocked"]
    dst_block_idx: int | None
    dst_block_binding_status: Literal["bound", "pending_layout"]
    flow_ack: int | None
    flow_ack_policy_id: str | None
    flow_ack_status: Literal["bound", "pending_policy"]
    lane_policy_id: str | None
    lane_count: int
    lane_stride: int | None
    patch_status: Literal[
        "endpoint_bound_layout_pending",
        "endpoint_bound",
        "blocked",
    ]
    blocker_ids: tuple[str, ...]

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
    def physical_route_row_claim(self) -> bool:
        return bool(self.physical_route_row_candidate_ids)

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "patch_id": self.patch_id,
            "operator": self.operator,
            "collective_strategy": self.collective_strategy,
            "logical_route_edge_id": self.logical_route_edge_id,
            "source_ring_edge_id": self.source_ring_edge_id,
            "physical_route_row_candidate_ids": list(
                self.physical_route_row_candidate_ids
            ),
            "phase": self.phase,
            "app_id": self.app_id,
            "task_id": self.task_id,
            "src_pe": self.src_pe,
            "dst_pe": self.dst_pe,
            "sender_stream_action_id": self.sender_stream_action_id,
            "receiver_stream_action_id": self.receiver_stream_action_id,
            "sender_fiber_op_id": self.sender_fiber_op_id,
            "receiver_fiber_op_id": self.receiver_fiber_op_id,
            "route_opcode_family": self.route_opcode_family,
            "route_family_status": self.route_family_status,
            "route_family_decision_id": self.route_family_decision_id,
            "base_materialization": self.base_materialization,
            "src_operand_allocation_id": self.src_operand_allocation_id,
            "dst_operand_allocation_id": self.dst_operand_allocation_id,
            "src_route_operand_patch_id": self.src_route_operand_patch_id,
            "dst_route_operand_patch_id": self.dst_route_operand_patch_id,
            "src_operand_idx": self.src_operand_idx,
            "dst_operand_idx": self.dst_operand_idx,
            "src_allocation_scope": self.src_allocation_scope,
            "dst_allocation_scope": self.dst_allocation_scope,
            "expected_src_allocation_scope": self.expected_src_allocation_scope,
            "expected_dst_allocation_scope": self.expected_dst_allocation_scope,
            "sender_scope_status": self.sender_scope_status,
            "receiver_scope_status": self.receiver_scope_status,
            "src_placeholder_id": self.src_placeholder_id,
            "dst_placeholder_id": self.dst_placeholder_id,
            "fmax_src_received_placeholder_id": self.fmax_src_received_placeholder_id,
            "fmax_src_received_allocation_id": self.fmax_src_received_allocation_id,
            "fmax_src_received_operand_idx": self.fmax_src_received_operand_idx,
            "push_source_continuity": self.push_source_continuity,
            "recv_to_fmax_continuity_status": self.recv_to_fmax_continuity_status,
            "dst_pe_pos": list(self.dst_pe_pos),
            "dst_pe_coord_status": self.dst_pe_coord_status,
            "dst_block_idx": self.dst_block_idx,
            "dst_block_binding_status": self.dst_block_binding_status,
            "flow_ack": self.flow_ack,
            "flow_ack_policy_id": self.flow_ack_policy_id,
            "flow_ack_status": self.flow_ack_status,
            "lane_policy_id": self.lane_policy_id,
            "lane_count": self.lane_count,
            "lane_stride": self.lane_stride,
            "patch_status": self.patch_status,
            "blocker_ids": list(self.blocker_ids),
            "row_bytes_claim": self.row_bytes_claim,
            "physical_route_row_claim": self.physical_route_row_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }


@dataclass(frozen=True)
class RouteEndpointPatchReport:
    """Phase-0 endpoint report; route bytes and runtime readiness stay blocked."""

    profile_id: str
    source_route_operand_patch_report_id: str
    source_inst_operand_patch_report_id: str
    patches: tuple[RouteEndpointPatch, ...]

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
    def physical_route_row_claim(self) -> bool:
        return any(patch.physical_route_row_claim for patch in self.patches)

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.patches:
            blockers.append("log10max_route_endpoint_patch_missing")
        for patch in self.patches:
            blockers.extend(patch.blocker_ids)
        return tuple(dict.fromkeys(blockers))

    def summary(self) -> dict[str, object]:
        phase_counts: dict[str, int] = {}
        family_counts: dict[str, int] = {}
        family_status_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        continuity_counts: dict[str, int] = {}
        coord_counts: dict[str, int] = {}
        flow_ack_counts: dict[str, int] = {}
        unique_pairs = {
            (patch.sender_stream_action_id, patch.receiver_stream_action_id)
            for patch in self.patches
        }
        for patch in self.patches:
            phase_counts[patch.phase] = phase_counts.get(patch.phase, 0) + 1
            family_counts[patch.route_opcode_family] = (
                family_counts.get(patch.route_opcode_family, 0) + 1
            )
            family_status_counts[patch.route_family_status] = (
                family_status_counts.get(patch.route_family_status, 0) + 1
            )
            status_counts[patch.patch_status] = (
                status_counts.get(patch.patch_status, 0) + 1
            )
            continuity_counts[patch.recv_to_fmax_continuity_status] = (
                continuity_counts.get(patch.recv_to_fmax_continuity_status, 0) + 1
            )
            coord_counts[patch.dst_pe_coord_status] = (
                coord_counts.get(patch.dst_pe_coord_status, 0) + 1
            )
            flow_ack_counts[patch.flow_ack_status] = (
                flow_ack_counts.get(patch.flow_ack_status, 0) + 1
            )
        return {
            "profile_id": self.profile_id,
            "source_route_operand_patch_report_id": (
                self.source_route_operand_patch_report_id
            ),
            "source_inst_operand_patch_report_id": (
                self.source_inst_operand_patch_report_id
            ),
            "endpoint_count": len(self.patches),
            "phase_counts": dict(sorted(phase_counts.items())),
            "expected_phase_counts": dict(sorted(EXPECTED_PHASE_COUNTS.items())),
            "unique_push_recv_pair_count": len(unique_pairs),
            "route_opcode_family_counts": dict(sorted(family_counts.items())),
            "route_family_status_counts": dict(sorted(family_status_counts.items())),
            "patch_status_counts": dict(sorted(status_counts.items())),
            "recv_to_fmax_continuity_status_counts": dict(
                sorted(continuity_counts.items())
            ),
            "dst_pe_coord_status_counts": dict(sorted(coord_counts.items())),
            "flow_ack_status_counts": dict(sorted(flow_ack_counts.items())),
            "blocker_ids": list(self.blocker_ids),
            "row_bytes_claim": self.row_bytes_claim,
            "physical_route_row_claim": self.physical_route_row_claim,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_route_endpoint_patch_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "row_bytes_claim": self.row_bytes_claim,
            "physical_route_row_claim": self.physical_route_row_claim,
            "blocker_ids": list(self.blocker_ids),
            "patches": [patch.to_plan() for patch in self.patches],
            "layering_policy": (
                "RouteEndpointPatch consumes existing ring route operand patch "
                "and FMAX InstOperandPatch reports. It does not choose "
                "COPY/COPYT/LDN, emit route bytes, assign component offsets, "
                "or change runtime_ready."
            ),
        }


def build_log10max_route_endpoint_patch_report(
    route_operand_report: RingRouteOperandPatchReport | None = None,
    inst_operand_report: object | None = None,
    *,
    profile_id: str = "dfu3500_log10max_route_endpoint_patch_v1",
) -> RouteEndpointPatchReport:
    """Build one logical endpoint patch per log10max ring edge."""

    route_report = route_operand_report or build_log10max_ring_route_operand_patch_report()
    inst_report = inst_operand_report or build_log10max_ring_update_inst_operand_patch_report()
    route_by_edge_direction: dict[tuple[str, str], RouteOperandPatch] = {
        (patch.source_ring_edge_id, patch.direction): patch
        for patch in route_report.patches
    }
    inst_by_edge: dict[str, InstOperandPatch] = {
        patch.source_ring_edge_id: patch for patch in inst_report.patches
    }
    edge_ids = tuple(
        sorted(
            {patch.source_ring_edge_id for patch in route_report.patches},
            key=_edge_sort_key,
        )
    )
    patches = tuple(
        _endpoint_patch_for_edge(
            edge_id=edge_id,
            push=route_by_edge_direction.get((edge_id, "push")),
            recv=route_by_edge_direction.get((edge_id, "recv")),
            fmax=inst_by_edge.get(edge_id),
        )
        for edge_id in edge_ids
    )
    return RouteEndpointPatchReport(
        profile_id=profile_id,
        source_route_operand_patch_report_id=route_report.profile_id,
        source_inst_operand_patch_report_id=inst_report.profile_id,
        patches=patches,
    )


def summarize_log10max_route_endpoint_patch_report(
    report: RouteEndpointPatchReport,
) -> dict[str, object]:
    return report.summary()


def _endpoint_patch_for_edge(
    *,
    edge_id: str,
    push: RouteOperandPatch | None,
    recv: RouteOperandPatch | None,
    fmax: InstOperandPatch | None,
) -> RouteEndpointPatch:
    blockers = [
        LOG10MAX_ROUTE_FAMILY_PHASE2_BLOCKER,
        LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER,
        LOG10MAX_ROUTE_DST_BLOCK_LAYOUT_BLOCKER,
        LOG10MAX_ROUTE_ROW_BYTES_BLOCKER,
        LOG10MAX_ROUTE_COMPONENT_INTEGRATION_BLOCKER,
    ]
    if push is None:
        blockers.insert(0, "log10max_route_endpoint_push_patch_missing")
    if recv is None:
        blockers.insert(0, "log10max_route_endpoint_recv_patch_missing")
    if fmax is None:
        blockers.insert(0, "log10max_route_endpoint_fmax_patch_missing")

    source = push or recv
    if source is None:
        phase = _phase_from_edge_id(edge_id)
        task_id = 0
        src_pe = ""
        dst_pe = ""
        sender_stream_action_id = ""
        receiver_stream_action_id = ""
        sender_fiber_op_id = ""
        receiver_fiber_op_id = ""
    else:
        phase = _phase_from_edge_id(source.source_ring_edge_id)
        task_id = source.task_id
        src_pe = source.src_pe
        dst_pe = source.dst_pe
        sender_stream_action_id = (
            push.source_stream_action_id if push is not None else ""
        )
        receiver_stream_action_id = (
            recv.source_stream_action_id if recv is not None else ""
        )
        sender_fiber_op_id = push.source_fiber_op_id if push is not None else ""
        receiver_fiber_op_id = recv.source_fiber_op_id if recv is not None else ""

    src_placeholder_id = _single_or_empty(push.src_placeholders if push else ())
    dst_placeholder_id = _single_or_empty(recv.dst_placeholders if recv else ())
    fmax_recv_placeholder = _fmax_recv_placeholder(fmax)
    src_allocation_id = _single_or_empty(push.allocation_ids if push else ())
    dst_allocation_id = _single_or_empty(recv.allocation_ids if recv else ())
    fmax_recv_allocation = _fmax_recv_allocation_id(fmax)
    src_operand_idx = _first_used_operand(push.src_operands_idx if push else ())
    dst_operand_idx = _first_used_operand(recv.dst_operands_idx if recv else ())
    fmax_recv_operand_idx = _fmax_recv_operand_idx(fmax)
    expected_src_scope = push.expected_allocation_scope if push is not None else ""
    expected_dst_scope = recv.expected_allocation_scope if recv is not None else ""
    src_scope = push.allocation_scope if push is not None else ""
    dst_scope = recv.allocation_scope if recv is not None else ""
    sender_scope_status: Literal["sender_task_pe", "blocked"] = (
        "sender_task_pe"
        if push is not None
        and push.scope_status == "sender_task_pe"
        and src_scope == expected_src_scope
        else "blocked"
    )
    receiver_scope_status: Literal["receiver_task_pe", "blocked"] = (
        "receiver_task_pe"
        if recv is not None
        and recv.scope_status == "receiver_task_pe"
        and dst_scope == expected_dst_scope
        else "blocked"
    )
    if sender_scope_status == "blocked":
        blockers.insert(0, "log10max_route_endpoint_sender_scope_mismatch")
    if receiver_scope_status == "blocked":
        blockers.insert(0, "log10max_route_endpoint_receiver_scope_mismatch")

    recv_matches_fmax = (
        recv is not None
        and fmax is not None
        and dst_placeholder_id == fmax_recv_placeholder
        and dst_allocation_id == fmax_recv_allocation
        and dst_operand_idx == fmax_recv_operand_idx
    )
    if not recv_matches_fmax:
        blockers.insert(0, "log10max_route_endpoint_recv_to_fmax_mismatch")

    push_source_continuity: Literal[
        "local_reduce_max_out",
        "previous_globalmax_acc_out",
        "blocked",
    ]
    if src_placeholder_id.endswith(":local_reduce_max_out"):
        push_source_continuity = "local_reduce_max_out"
    elif src_placeholder_id.endswith(":globalmax_acc_out"):
        push_source_continuity = "previous_globalmax_acc_out"
    else:
        push_source_continuity = "blocked"
        blockers.insert(0, "log10max_route_endpoint_push_source_mismatch")

    dst_pe_pos, coord_status = _pe_pos(dst_pe)
    if coord_status == "blocked":
        blockers.insert(0, "log10max_route_endpoint_dst_pe_pos_missing")

    status: Literal[
        "endpoint_bound_layout_pending",
        "endpoint_bound",
        "blocked",
    ]
    hard_fail_blockers = tuple(
        blocker
        for blocker in blockers
        if blocker
        in {
            "log10max_route_endpoint_push_patch_missing",
            "log10max_route_endpoint_recv_patch_missing",
            "log10max_route_endpoint_fmax_patch_missing",
            "log10max_route_endpoint_sender_scope_mismatch",
            "log10max_route_endpoint_receiver_scope_mismatch",
            "log10max_route_endpoint_recv_to_fmax_mismatch",
            "log10max_route_endpoint_push_source_mismatch",
            "log10max_route_endpoint_dst_pe_pos_missing",
        }
    )
    status = "blocked" if hard_fail_blockers else "endpoint_bound_layout_pending"

    return RouteEndpointPatch(
        schema_version="1",
        patch_id=f"patch:route_endpoint:{edge_id}",
        operator="log10max",
        collective_strategy="ring_spmd_row_then_col",
        logical_route_edge_id=edge_id,
        source_ring_edge_id=edge_id,
        physical_route_row_candidate_ids=(),
        phase=phase,  # type: ignore[arg-type]
        app_id=0,
        task_id=task_id,
        src_pe=src_pe,
        dst_pe=dst_pe,
        sender_stream_action_id=sender_stream_action_id,
        receiver_stream_action_id=receiver_stream_action_id,
        sender_fiber_op_id=sender_fiber_op_id,
        receiver_fiber_op_id=receiver_fiber_op_id,
        route_opcode_family="undecided",
        route_family_status="pending_phase2_decision",
        route_family_decision_id=None,
        base_materialization="native_template_row",
        src_operand_allocation_id=src_allocation_id,
        dst_operand_allocation_id=dst_allocation_id,
        src_route_operand_patch_id=None,
        dst_route_operand_patch_id=None,
        src_operand_idx=src_operand_idx,
        dst_operand_idx=dst_operand_idx,
        src_allocation_scope=src_scope,
        dst_allocation_scope=dst_scope,
        expected_src_allocation_scope=expected_src_scope,
        expected_dst_allocation_scope=expected_dst_scope,
        sender_scope_status=sender_scope_status,
        receiver_scope_status=receiver_scope_status,
        src_placeholder_id=src_placeholder_id,
        dst_placeholder_id=dst_placeholder_id,
        fmax_src_received_placeholder_id=fmax_recv_placeholder,
        fmax_src_received_allocation_id=fmax_recv_allocation,
        fmax_src_received_operand_idx=fmax_recv_operand_idx,
        push_source_continuity=push_source_continuity,
        recv_to_fmax_continuity_status="matched" if recv_matches_fmax else "blocked",
        dst_pe_pos=dst_pe_pos,
        dst_pe_coord_status=coord_status,
        dst_block_idx=None,
        dst_block_binding_status="pending_layout",
        flow_ack=None,
        flow_ack_policy_id=None,
        flow_ack_status="pending_policy",
        lane_policy_id=None,
        lane_count=0,
        lane_stride=None,
        patch_status=status,
        blocker_ids=tuple(dict.fromkeys(blockers)),
    )


def _single_or_empty(values: tuple[str, ...]) -> str:
    return values[0] if len(values) == 1 else ""


def _first_used_operand(values: tuple[int, ...]) -> int:
    return int(values[0]) if values else -1


def _fmax_recv_placeholder(patch: InstOperandPatch | None) -> str:
    if patch is None or len(patch.src_placeholders) < 2:
        return ""
    return patch.src_placeholders[1]


def _fmax_recv_allocation_id(patch: InstOperandPatch | None) -> str:
    if patch is None or len(patch.allocation_ids) < 2:
        return ""
    return patch.allocation_ids[1]


def _fmax_recv_operand_idx(patch: InstOperandPatch | None) -> int:
    if patch is None or len(patch.src_operands_idx) < 2:
        return -1
    return patch.src_operands_idx[1]


def _pe_pos(pe: str) -> tuple[tuple[int, int, int], Literal["profile_backed", "blocked"]]:
    body = pe.removeprefix("PE(").removesuffix(")")
    parts = body.split(",")
    if len(parts) != 2:
        return (0, 0, 0), "blocked"
    try:
        return (int(parts[0]), int(parts[1]), 0), "profile_backed"
    except ValueError:
        return (0, 0, 0), "blocked"


def _phase_from_edge_id(edge_id: str) -> str:
    parts = edge_id.split(":")
    return parts[2] if len(parts) >= 3 else "unknown"


def _edge_sort_key(edge_id: str) -> tuple[int, str]:
    parts = edge_id.split(":")
    if len(parts) < 2:
        return (10**9, edge_id)
    try:
        return (int(parts[1]), edge_id)
    except ValueError:
        return (10**9, edge_id)


__all__ = [
    "LOG10MAX_ROUTE_COMPONENT_INTEGRATION_BLOCKER",
    "LOG10MAX_ROUTE_DST_BLOCK_LAYOUT_BLOCKER",
    "LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER",
    "LOG10MAX_ROUTE_FAMILY_PHASE2_BLOCKER",
    "LOG10MAX_ROUTE_ROW_BYTES_BLOCKER",
    "RouteEndpointPatch",
    "RouteEndpointPatchReport",
    "build_log10max_route_endpoint_patch_report",
    "summarize_log10max_route_endpoint_patch_report",
]
