"""Fiber projection report for log10max task-local ring StreamActions.

This module is intentionally narrow: it consumes the delivery-scoped
``log10max_ring_plan`` StreamActions and projects them into existing FiberOp
forms.  It does not create a communication IR, a route graph authority, runtime
package assets, or binary rows.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Mapping

from .blocks import (
    FiberBlockProjection,
    project_fiber_to_blocks,
    summarize_fiber_block_projections,
    validate_fiber_block_projection,
)
from .fiber import Fiber, FiberDependency, FiberOp, FragmentRef
from .log10max_ring_plan import (
    LOG10MAX_RING_ROUTE_ROLE,
    Log10MaxRingPlanReport,
    RingEdgeRecord,
    build_log10max_task_local_ring_plan,
)


ProjectionProofStatus = Literal["satisfied", "pending", "unsatisfied", "missing"]


@dataclass(frozen=True)
class RingFiberProjectionRecord:
    """One derived record linking a ring StreamAction edge to FiberOps."""

    edge_id: str
    phase: str
    task_id: int
    src_pe: str
    dst_pe: str
    source_stream_action_id: str
    recv_stream_action_id: str
    update_stream_action_id: str
    source_fiber_op_id: str
    recv_fiber_op_id: str
    update_fiber_op_id: str
    route_fragment: FragmentRef
    recv_dependency_expected_satisfaction: str
    route_path_proof_status: ProjectionProofStatus
    route_path_stream_action_ids: tuple[str, ...]
    blockers: tuple[str, ...] = ()

    @property
    def projected(self) -> bool:
        return (
            not self.blockers
            and self.route_path_proof_status == "satisfied"
            and bool(self.route_path_stream_action_ids)
        )

    def to_plan(self) -> dict[str, object]:
        return {
            "edge_id": self.edge_id,
            "phase": self.phase,
            "task_id": self.task_id,
            "src_pe": self.src_pe,
            "dst_pe": self.dst_pe,
            "source_stream_action_id": self.source_stream_action_id,
            "recv_stream_action_id": self.recv_stream_action_id,
            "update_stream_action_id": self.update_stream_action_id,
            "source_fiber_op_id": self.source_fiber_op_id,
            "recv_fiber_op_id": self.recv_fiber_op_id,
            "update_fiber_op_id": self.update_fiber_op_id,
            "route_fragment": self.route_fragment.to_plan(),
            "recv_dependency_expected_satisfaction": (
                self.recv_dependency_expected_satisfaction
            ),
            "route_path_proof_status": self.route_path_proof_status,
            "route_path_stream_action_ids": list(self.route_path_stream_action_ids),
            "projected": self.projected,
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class Log10MaxRingFiberProjectionReport:
    """Focused StreamAction -> FiberOp projection report for ring edges."""

    profile_id: str
    strategy: str
    task_axis: int
    runtime_ordering_domain: str
    fibers: tuple[Fiber, ...]
    projections: tuple[FiberBlockProjection, ...]
    records: tuple[RingFiberProjectionRecord, ...]
    diagnostics: tuple[str, ...] = ()
    attrs: Mapping[str, object] = field(default_factory=dict)

    @property
    def runtime_ready(self) -> bool:
        return not self.diagnostics and all(record.projected for record in self.records)

    def summary(self) -> dict[str, object]:
        fiber_op_counts: dict[str, int] = {}
        proof_status_counts: dict[str, int] = {}
        phase_counts: dict[str, int] = {}
        blocker_counts: dict[str, int] = {}
        route_path_trace_lengths: dict[int, int] = {}
        for fiber in self.fibers:
            for op in fiber.ops:
                fiber_op_counts[op.op] = fiber_op_counts.get(op.op, 0) + 1
        for record in self.records:
            proof_status_counts[record.route_path_proof_status] = (
                proof_status_counts.get(record.route_path_proof_status, 0) + 1
            )
            phase_counts[record.phase] = phase_counts.get(record.phase, 0) + 1
            route_path_trace_lengths[len(record.route_path_stream_action_ids)] = (
                route_path_trace_lengths.get(len(record.route_path_stream_action_ids), 0)
                + 1
            )
            for blocker in record.blockers:
                blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
        return {
            "profile_id": self.profile_id,
            "strategy": self.strategy,
            "task_axis": self.task_axis,
            "runtime_ordering_domain": self.runtime_ordering_domain,
            "fiber_count": len(self.fibers),
            "projection_count": len(self.projections),
            "record_count": len(self.records),
            "fiber_op_counts": dict(sorted(fiber_op_counts.items())),
            "phase_counts": dict(sorted(phase_counts.items())),
            "route_path_proof_status_counts": dict(sorted(proof_status_counts.items())),
            "route_path_trace_lengths": dict(sorted(route_path_trace_lengths.items())),
            "blocker_counts": dict(sorted(blocker_counts.items())),
            "diagnostic_count": len(self.diagnostics),
            "runtime_ready": self.runtime_ready,
            "communication_ir_created": False,
            "one_app_cross_task_route_edge_allowed": False,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_ring_fiber_projection_report",
            "summary": self.summary(),
            "profile_id": self.profile_id,
            "strategy": self.strategy,
            "task_axis": self.task_axis,
            "runtime_ordering_domain": self.runtime_ordering_domain,
            "semantic_authority": "StreamAction.depends_on",
            "fiber_authority": (
                "existing FiberOp(fragment_route_push/fragment_route_recv/"
                "global_max_tile) forms"
            ),
            "projections_are": "derived_report_not_new_communication_ir",
            "fibers": [fiber.to_plan() for fiber in self.fibers],
            "projection_summary": summarize_fiber_block_projections(self.projections),
            "projections": [projection.to_plan() for projection in self.projections],
            "records": [record.to_plan() for record in self.records],
            "diagnostics": list(self.diagnostics),
            "attrs": dict(self.attrs),
        }


def build_log10max_ring_fiber_projection_report(
    ring_report: Log10MaxRingPlanReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_ring_stream_to_fiber_projection_v1",
) -> Log10MaxRingFiberProjectionReport:
    """Project task-local ring StreamActions into existing FiberOps."""

    report = ring_report or build_log10max_task_local_ring_plan()
    diagnostics: list[str] = []
    if report.task_axis != 1:
        diagnostics.append("task_axis_scope_unproven")
    if report.runtime_ordering_domain not in {
        "single_task_graph",
        "single_task_group",
    }:
        diagnostics.append("runtime_ordering_domain_not_task_local")
    task_ids = {edge.task_id for edge in report.edges}
    if len(task_ids) > 1:
        diagnostics.append("one_app_cross_task_route_edge_forbidden")

    fibers, draft_records = _project_ring_edges_to_fibers(report.edges)
    projections = tuple(
        project_fiber_to_blocks(fiber, stream_plan=report.stream_plan)
        for fiber in fibers
    )
    for fiber, projection in zip(fibers, projections):
        validation = validate_fiber_block_projection(fiber, projection)
        if not validation.ok:
            diagnostics.extend(validation.diagnostics)

    records = _attach_projection_proofs(
        draft_records=draft_records,
        projections=projections,
    )
    return Log10MaxRingFiberProjectionReport(
        profile_id=profile_id,
        strategy=report.strategy,
        task_axis=report.task_axis,
        runtime_ordering_domain=report.runtime_ordering_domain,
        fibers=fibers,
        projections=projections,
        records=records,
        diagnostics=tuple(dict.fromkeys(diagnostics)),
        attrs={
            "route_role": LOG10MAX_RING_ROUTE_ROLE,
            "source_artifact_kind": "log10max_task_local_ring_plan",
            "binary_writer_touched": False,
            "runtime_package_touched": False,
        },
    )


def summarize_log10max_ring_fiber_projection_report(
    report: Log10MaxRingFiberProjectionReport,
) -> dict[str, object]:
    return report.summary()


def _project_ring_edges_to_fibers(
    edges: tuple[RingEdgeRecord, ...],
) -> tuple[tuple[Fiber, ...], tuple[RingFiberProjectionRecord, ...]]:
    ops_by_stream: dict[str, list[FiberOp]] = {}
    records: list[RingFiberProjectionRecord] = []

    def pe_to_stream(pe: str, task_id: int) -> str:
        x_text, y_text = pe.removeprefix("PE(").removesuffix(")").split(",")
        return f"t{task_id}_pe{x_text}{y_text}"

    def append_op(
        stream_id: str,
        *,
        op: str,
        edge_index: int,
        suffix: str,
        inputs: tuple[FragmentRef, ...] = (),
        outputs: tuple[FragmentRef, ...] = (),
        depends_on: tuple[FiberDependency, ...] = (),
        attrs: dict[str, object],
    ) -> FiberOp:
        stream_ops = ops_by_stream.setdefault(stream_id, [])
        fiber_id = f"fiber:log10max_ring:{stream_id}"
        fiber_op = FiberOp(
            id=f"{fiber_id}:edge{edge_index:04d}:{suffix}",
            stream_id=stream_id,
            fiber_id=fiber_id,
            order_index=len(stream_ops),
            op=op,  # type: ignore[arg-type]
            inputs=inputs,
            outputs=outputs,
            depends_on=depends_on,
            attrs=attrs,
        )
        stream_ops.append(fiber_op)
        return fiber_op

    for edge_index, edge in enumerate(edges):
        src_stream = pe_to_stream(edge.src_pe, edge.task_id)
        dst_stream = pe_to_stream(edge.dst_pe, edge.task_id)
        fragment = FragmentRef.make("GlobalMax", task=edge.task_id, edge=edge_index)
        push = append_op(
            src_stream,
            op="fragment_route_push",
            edge_index=edge_index,
            suffix="fragment_route_push_global_max",
            inputs=(fragment,),
            attrs={
                "placement": "tile_body",
                "semantic_op": "route_push_global_max",
                "operand": LOG10MAX_RING_ROUTE_ROLE,
                "route_role": LOG10MAX_RING_ROUTE_ROLE,
                "visibility_kind": "route_push",
                "stream_visibility_action_id": edge.source_stream_action_id,
                "source_stream_action_id": edge.source_stream_action_id,
                "paired_recv_stream_action_id": edge.recv_stream_action_id,
                "route_template_family": "route_forward",
                "template_evidence_id": edge.route_template_evidence_id,
                "template_status": edge.route_template_status,
                "source_value_kind": "scalar",
                "destination_value_kind": "scalar",
                "task_id": edge.task_id,
                "src_pe": edge.src_pe,
                "dst_pe": edge.dst_pe,
                "phase": edge.phase,
            },
        )
        update_id = f"fiber:log10max_ring:{dst_stream}:edge{edge_index:04d}:max_update_global_max"
        recv = append_op(
            dst_stream,
            op="fragment_route_recv",
            edge_index=edge_index,
            suffix="fragment_route_recv_global_max",
            outputs=(fragment,),
            attrs={
                "placement": "tile_body",
                "semantic_op": "route_recv_global_max",
                "operand": LOG10MAX_RING_ROUTE_ROLE,
                "route_role": LOG10MAX_RING_ROUTE_ROLE,
                "visibility_kind": "route_recv",
                "stream_visibility_action_id": edge.recv_stream_action_id,
                "source_stream_action_id": edge.recv_stream_action_id,
                "paired_push_stream_action_id": edge.source_stream_action_id,
                "paired_update_stream_action_id": edge.update_action_id,
                "route_template_family": "route_forward",
                "template_evidence_id": edge.route_template_evidence_id,
                "template_status": edge.route_template_status,
                "source_value_kind": "scalar",
                "destination_value_kind": "scalar",
                "receiver_destination_operand": fragment.label(),
                "receiver_destination_block": update_id,
                "task_id": edge.task_id,
                "src_pe": edge.src_pe,
                "dst_pe": edge.dst_pe,
                "phase": edge.phase,
            },
        )
        update = append_op(
            dst_stream,
            op="global_max_tile",
            edge_index=edge_index,
            suffix="max_update_global_max",
            inputs=(fragment,),
            outputs=(fragment,),
            depends_on=(
                FiberDependency(
                    source_op_id=recv.id,
                    kind="fragment_visibility",
                    expected_satisfaction="route_or_local_materialization",
                    via_fragment=fragment,
                    reason=(
                        "ring receiver-side max update consumes the GlobalMax "
                        "fragment made visible by route_recv_global_max"
                    ),
                ),
            ),
            attrs={
                "placement": "tile_body",
                "semantic_op": "max_update_global_max",
                "operand": LOG10MAX_RING_ROUTE_ROLE,
                "route_role": LOG10MAX_RING_ROUTE_ROLE,
                "stream_action_id": edge.update_action_id,
                "source_stream_action_id": edge.update_action_id,
                "recv_stream_action_id": edge.recv_stream_action_id,
                "paired_push_stream_action_id": edge.source_stream_action_id,
                "update_op": edge.update_op,
                "dtype": edge.dtype,
                "template_evidence_id": edge.update_template_evidence_id,
                "template_status": edge.update_template_status,
                "template_blocker": edge.update_template_blocker,
                "task_id": edge.task_id,
                "src_pe": edge.src_pe,
                "dst_pe": edge.dst_pe,
                "phase": edge.phase,
                "atom_boundary": "fiber_atomic_tile_job",
            },
        )
        records.append(
            RingFiberProjectionRecord(
                edge_id=edge.edge_id,
                phase=edge.phase,
                task_id=edge.task_id,
                src_pe=edge.src_pe,
                dst_pe=edge.dst_pe,
                source_stream_action_id=edge.source_stream_action_id,
                recv_stream_action_id=edge.recv_stream_action_id,
                update_stream_action_id=edge.update_action_id,
                source_fiber_op_id=push.id,
                recv_fiber_op_id=recv.id,
                update_fiber_op_id=update.id,
                route_fragment=fragment,
                recv_dependency_expected_satisfaction=(
                    "route_or_local_materialization"
                ),
                route_path_proof_status="missing",
                route_path_stream_action_ids=(),
            )
        )

    fibers = tuple(
        Fiber(
            id=f"fiber:log10max_ring:{stream_id}",
            stream_id=stream_id,
            m_tile=0,
            n_tile=0,
            ops=tuple(ops),
            attrs={
                "strategy_id": "log10max_ring_stream_to_fiber_projection",
                "route_role": LOG10MAX_RING_ROUTE_ROLE,
                "task_local_only": True,
                "communication_ir_created": False,
            },
        )
        for stream_id, ops in sorted(ops_by_stream.items())
    )
    return fibers, tuple(records)


def _attach_projection_proofs(
    *,
    draft_records: tuple[RingFiberProjectionRecord, ...],
    projections: tuple[FiberBlockProjection, ...],
) -> tuple[RingFiberProjectionRecord, ...]:
    proof_by_update_op: dict[str, tuple[ProjectionProofStatus, tuple[str, ...]]] = {}
    for projection in projections:
        for dependency in projection.dependencies:
            proof = dependency.proof
            if proof is None:
                continue
            dst_op_id = dependency.dst_block_id.removeprefix("block:")
            if proof.expected_satisfaction != "route_or_local_materialization":
                continue
            status: ProjectionProofStatus = proof.status
            proof_by_update_op[dst_op_id] = (status, tuple(proof.stream_plan_edge_ids))

    records: list[RingFiberProjectionRecord] = []
    for record in draft_records:
        proof_status, route_trace = proof_by_update_op.get(
            record.update_fiber_op_id,
            ("missing", ()),
        )
        blockers: list[str] = []
        if proof_status != "satisfied":
            blockers.append("route_path_proof_missing")
        if not route_trace:
            blockers.append("route_trace_missing")
        elif route_trace[-1] != record.recv_stream_action_id:
            blockers.append("route_trace_does_not_end_at_recv_action")
        elif record.source_stream_action_id not in route_trace:
            blockers.append("route_trace_does_not_include_push_action")
        records.append(
            RingFiberProjectionRecord(
                edge_id=record.edge_id,
                phase=record.phase,
                task_id=record.task_id,
                src_pe=record.src_pe,
                dst_pe=record.dst_pe,
                source_stream_action_id=record.source_stream_action_id,
                recv_stream_action_id=record.recv_stream_action_id,
                update_stream_action_id=record.update_stream_action_id,
                source_fiber_op_id=record.source_fiber_op_id,
                recv_fiber_op_id=record.recv_fiber_op_id,
                update_fiber_op_id=record.update_fiber_op_id,
                route_fragment=record.route_fragment,
                recv_dependency_expected_satisfaction=(
                    record.recv_dependency_expected_satisfaction
                ),
                route_path_proof_status=proof_status,
                route_path_stream_action_ids=route_trace,
                blockers=tuple(dict.fromkeys(blockers)),
            )
        )
    return tuple(records)


__all__ = [
    "Log10MaxRingFiberProjectionReport",
    "RingFiberProjectionRecord",
    "build_log10max_ring_fiber_projection_report",
    "summarize_log10max_ring_fiber_projection_report",
]
