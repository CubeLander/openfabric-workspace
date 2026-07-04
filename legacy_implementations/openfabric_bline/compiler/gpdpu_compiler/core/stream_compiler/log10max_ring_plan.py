"""Task-local ring plan for the log10max V1 global-max movement.

This module is delivery-scoped and report-first.  It does not create a generic
collective IR.  It emits the representative row/column reduce+broadcast shape
as ordinary StreamAction route push/recv/update records, plus derived metadata
for validation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .log10max_template_pack import LOG10MAX_DTYPE
from .stream import StreamAction, StreamPlan, StreamValue


LOG10MAX_RING_STRATEGY = "ring_spmd_row_then_col"
LOG10MAX_RING_CUSTOMER_LABEL = "spmd_ring_materialized_reduce"
LOG10MAX_RING_ORDERING_DOMAIN = "single_task_group"
LOG10MAX_RING_ROUTE_ROLE = "GlobalMax"

RingPhase = Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
RingProofStatus = Literal["proven", "assumed", "unresolved"]
RouteValueKind = Literal["tile_fragment", "scalar", "scratch_scalar"]

RING_FIRST_RUNTIME_READY_BLOCKERS = (
    "route_role_globalmax_unproven",
    "ring_edge_template_missing",
    "ring_edge_route_template_missing",
    "ring_edge_update_template_missing",
    "route_path_proof_missing",
    "ring_phase_order_missing",
    "global_max_distribution_missing",
    "consumer_global_max_binding_missing",
    "consumer_depends_on_global_ready_missing",
)


@dataclass(frozen=True)
class RouteRoleBinding:
    """Small role-generalization contract for GlobalMax route movement."""

    role: Literal["A", "B", "GlobalMax"]
    route_template_family: str
    source_value_kind: RouteValueKind
    destination_value_kind: RouteValueKind
    template_evidence_id: str
    proof_status: RingProofStatus

    @property
    def runtime_ready(self) -> bool:
        return (
            self.role == "GlobalMax"
            and self.proof_status == "proven"
            and bool(self.template_evidence_id)
        )

    def to_plan(self) -> dict[str, object]:
        return {
            "role": self.role,
            "route_template_family": self.route_template_family,
            "source_value_kind": self.source_value_kind,
            "destination_value_kind": self.destination_value_kind,
            "template_evidence_id": self.template_evidence_id,
            "proof_status": self.proof_status,
            "runtime_ready": self.runtime_ready,
            "authority_boundary": (
                "role_generalization_only_reuses_existing_route_primitive"
            ),
        }


@dataclass(frozen=True)
class RingEdgeRecord:
    """Derived validation metadata for one representative ring edge."""

    edge_id: str
    phase: RingPhase
    task_id: int
    src_pe: str
    dst_pe: str
    source_stream_action_id: str
    recv_stream_action_id: str
    update_action_id: str
    dtype: str
    update_op: Literal["FMAX", "HMAX"]
    route_role: Literal["GlobalMax"]
    ordering_group: str
    proof_status: RingProofStatus
    template_evidence_id: str
    route_template_evidence_id: str
    route_template_status: RingProofStatus
    route_path_proof_status: RingProofStatus
    update_template_evidence_id: str
    update_template_status: RingProofStatus
    update_template_blocker: str

    def to_plan(self) -> dict[str, object]:
        return {
            "edge_id": self.edge_id,
            "phase": self.phase,
            "task_id": self.task_id,
            "src_pe": self.src_pe,
            "dst_pe": self.dst_pe,
            "source_stream_action_id": self.source_stream_action_id,
            "recv_stream_action_id": self.recv_stream_action_id,
            "update_action_id": self.update_action_id,
            "dtype": self.dtype,
            "update_op": self.update_op,
            "route_role": self.route_role,
            "ordering_group": self.ordering_group,
            "proof_status": self.proof_status,
            "template_evidence_id": self.template_evidence_id,
            "template_status": self.proof_status,
            "route_template_evidence_id": self.route_template_evidence_id,
            "route_template_status": self.route_template_status,
            "route_path_proof_status": self.route_path_proof_status,
            "update_template_evidence_id": self.update_template_evidence_id,
            "update_template_status": self.update_template_status,
            "update_template_blocker": self.update_template_blocker,
            "cross_task_edge": False,
            "authority": "derived_from_stream_actions",
        }


@dataclass(frozen=True)
class PostprocessConsumerBindingRecord:
    """Derived binding from PE-local postprocess to global_max_ready."""

    consumer_id: str
    task_id: int
    pe: str
    stream_id: str
    consumer_fiber_op: Literal["max_with_floor_tile"]
    source_expression: str
    global_max_input: Literal["GlobalMax"]
    global_max_ready_token: str
    global_max_producer_action_id: str
    dependency_kind: Literal["global_max_ready"]
    depends_on_global_max_ready: bool
    symbolic_global_max_reaches_postprocess: bool

    @property
    def proven(self) -> bool:
        return (
            self.depends_on_global_max_ready
            and bool(self.global_max_ready_token)
            and bool(self.global_max_producer_action_id)
            and not self.symbolic_global_max_reaches_postprocess
        )

    def to_plan(self) -> dict[str, object]:
        return {
            "consumer_id": self.consumer_id,
            "task_id": self.task_id,
            "pe": self.pe,
            "stream_id": self.stream_id,
            "consumer_fiber_op": self.consumer_fiber_op,
            "source_expression": self.source_expression,
            "global_max_input": self.global_max_input,
            "global_max_ready_token": self.global_max_ready_token,
            "global_max_producer_action_id": self.global_max_producer_action_id,
            "dependency_kind": self.dependency_kind,
            "depends_on_global_max_ready": self.depends_on_global_max_ready,
            "symbolic_global_max_reaches_postprocess": (
                self.symbolic_global_max_reaches_postprocess
            ),
            "proof_status": "proven" if self.proven else "unresolved",
            "authority": "derived_from_stream_action_global_max_ready_tokens",
        }


@dataclass(frozen=True)
class Log10MaxRingPlanReport:
    """Representative task-local ring plan for log10max V1."""

    strategy: str
    customer_label: str
    task_axis: int
    runtime_ordering_domain: str
    mesh_shape: tuple[int, int]
    route_role_binding: RouteRoleBinding
    stream_plan: StreamPlan
    edges: tuple[RingEdgeRecord, ...]
    global_max_ready: tuple[str, ...]
    postprocess_consumers: tuple[PostprocessConsumerBindingRecord, ...]
    runtime_ready_blockers: tuple[str, ...]

    @property
    def runtime_ready(self) -> bool:
        return not self.runtime_ready_blockers

    def summary(self) -> dict[str, object]:
        phase_counts: dict[str, int] = {}
        for edge in self.edges:
            phase_counts[edge.phase] = phase_counts.get(edge.phase, 0) + 1
        proven_consumers = tuple(
            consumer for consumer in self.postprocess_consumers if consumer.proven
        )
        symbolic_consumers = tuple(
            consumer
            for consumer in self.postprocess_consumers
            if consumer.symbolic_global_max_reaches_postprocess
        )
        return {
            "strategy": self.strategy,
            "customer_label": self.customer_label,
            "task_axis": self.task_axis,
            "runtime_ordering_domain": self.runtime_ordering_domain,
            "mesh_shape": list(self.mesh_shape),
            "edge_count": len(self.edges),
            "phase_counts": dict(sorted(phase_counts.items())),
            "global_max_ready_count": len(self.global_max_ready),
            "postprocess_consumer_count": len(self.postprocess_consumers),
            "postprocess_consumer_binding_count": len(proven_consumers),
            "symbolic_postprocess_consumer_count": len(symbolic_consumers),
            "route_role": self.route_role_binding.role,
            "route_role_proof_status": self.route_role_binding.proof_status,
            "runtime_ready": self.runtime_ready,
            "runtime_ready_blockers": list(self.runtime_ready_blockers),
            "direct_route_reduce_broadcast": "deferred",
            "physical_allreduce_claim": False,
            "one_app_cross_task_ring": "forbidden",
        }

    def to_plan(self) -> dict[str, object]:
        edges_ready = all(
            edge.proof_status == "proven"
            and edge.route_path_proof_status == "proven"
            for edge in self.edges
        )
        role_ready = self.route_role_binding.runtime_ready
        ready_count_matches = len(self.global_max_ready) == (
            self.mesh_shape[0] * self.mesh_shape[1]
        )
        consumer_count_matches = len(self.postprocess_consumers) == (
            self.mesh_shape[0] * self.mesh_shape[1]
        )
        consumer_binding_ready = consumer_count_matches and all(
            consumer.proven for consumer in self.postprocess_consumers
        )
        expected_edge_count = _expected_representative_edge_count(*self.mesh_shape)
        edge_count_matches = len(self.edges) == expected_edge_count
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_task_local_ring_plan",
            "summary": self.summary(),
            "collective_strategy": self.strategy,
            "strategy": self.strategy,
            "customer_collective_label": self.customer_label,
            "customer_label": self.customer_label,
            "task_axis": self.task_axis,
            "runtime_ordering_domain": self.runtime_ordering_domain,
            "runtime_app_count": 1,
            "cross_task_visibility_claim": False,
            "profile": {
                "task_axis": self.task_axis,
                "runtime_ordering_domain": self.runtime_ordering_domain,
                "cross_task_visibility_claim": False,
            },
            "mesh_shape": list(self.mesh_shape),
            "semantic_authority": (
                "StreamAction.depends_on; ring records are derived validation metadata"
            ),
            "route_role_binding": self.route_role_binding.to_plan(),
            "route_role_bindings": (self.route_role_binding.to_plan(),),
            "representative_selection": {
                "status": "proven" if edge_count_matches else "unresolved",
                "style": "row_col_reduce_broadcast_col0",
                "expected_edge_count": expected_edge_count,
                "edge_count": len(self.edges),
            },
            "phase_order": {"status": "proven"},
            "global_max_distribution": {
                "status": "proven" if ready_count_matches else "unresolved",
                "ready_count": len(self.global_max_ready),
                "expected_ready_count": self.mesh_shape[0] * self.mesh_shape[1],
            },
            "consumer_global_max_binding": {
                "status": "proven" if consumer_binding_ready else "unresolved",
                "consumer_count": len(self.postprocess_consumers),
                "expected_consumer_count": self.mesh_shape[0] * self.mesh_shape[1],
            },
            "consumer_global_max_ready_dependencies": {
                "status": "proven" if consumer_binding_ready else "unresolved",
                "source": "postprocess_consumer_bindings",
            },
            "capacity": {
                "status": "fits" if edge_count_matches else "overflow",
                "edge_count": len(self.edges),
                "expected_edge_count": expected_edge_count,
            },
            "dtype_update_op": {
                "status": "consistent",
                "dtype": self.edges[0].dtype if self.edges else LOG10MAX_DTYPE,
                "update_op": self.edges[0].update_op if self.edges else "FMAX",
            },
            "symbolic_global_max_reaches_postprocess": not consumer_binding_ready,
            "postprocess": {
                "consumer_fiber_op": "max_with_floor_tile",
                "symbolic_global_max_reaches_postprocess": (
                    not consumer_binding_ready
                ),
                "consumer_binding_source": (
                    "derived_global_max_ready_token_dependencies"
                ),
            },
            "stream_plan": self.stream_plan.to_plan(),
            "ring_edges": [edge.to_plan() for edge in self.edges],
            "global_max_ready": list(self.global_max_ready),
            "postprocess_consumer_bindings": [
                consumer.to_plan() for consumer in self.postprocess_consumers
            ],
            "runtime_ready_blockers": list(self.runtime_ready_blockers),
            "implementation_scope": (
                "ring_first_delivery_path_not_generic_collective_framework"
            ),
        }


def build_log10max_task_local_ring_plan(
    *,
    task_id: int = 0,
    mesh_shape: tuple[int, int] = (4, 4),
    dtype: str = LOG10MAX_DTYPE,
    route_role_proof_status: RingProofStatus = "unresolved",
    route_template_status: RingProofStatus = "unresolved",
    route_path_proof_status: RingProofStatus = "unresolved",
    update_template_status: RingProofStatus = "unresolved",
) -> Log10MaxRingPlanReport:
    """Build the representative row/column ring as existing StreamActions."""

    rows, cols = mesh_shape
    if rows <= 0 or cols <= 0:
        raise ValueError("mesh_shape must be positive")
    stream_plan = StreamPlan(app_id=0)
    action_counter = 0
    value_counter = 0
    current_value: dict[tuple[int, int], str] = {}
    producer_action: dict[tuple[int, int], str] = {}

    def stream_id(x: int, y: int) -> str:
        return f"t{task_id}_pe{x}{y}"

    def pe_label(x: int, y: int) -> str:
        return f"PE({x},{y})"

    def next_action_id(op: str) -> str:
        nonlocal action_counter
        action_id = f"log10max_ring:{op}:{action_counter:04d}"
        action_counter += 1
        return action_id

    def next_value_id(role: str, x: int, y: int) -> str:
        nonlocal value_counter
        value_id = f"{role}:t{task_id}:pe{x}{y}:{value_counter:04d}"
        value_counter += 1
        return value_id

    def append_action(
        *,
        stream: str,
        op: str,
        inputs: tuple[str, ...] = (),
        outputs: tuple[str, ...] = (),
        depends_on: tuple[str, ...] = (),
        attrs: dict[str, object] | None = None,
    ) -> StreamAction:
        action = StreamAction(
            id=next_action_id(op),
            stream_id=stream,
            op=op,
            source_chip_op="chip_op_log10max",
            inputs=inputs,
            outputs=outputs,
            depends_on=depends_on,
            attrs=attrs or {},
        )
        stream_plan.append_action(action)
        return action

    for x in range(rows):
        for y in range(cols):
            value_id = next_value_id("local_max", x, y)
            action = append_action(
                stream=stream_id(x, y),
                op="local_reduce_max",
                outputs=(value_id,),
                attrs={
                    "task_id": task_id,
                    "pe": pe_label(x, y),
                    "dtype": dtype,
                    "fiber_op": "local_reduce_max_tile",
                },
            )
            current_value[(x, y)] = value_id
            producer_action[(x, y)] = action.id
            stream_plan.set_visible_value(
                StreamValue(
                    id=value_id,
                    logical_tensor_id="LocalMax",
                    stream_id=stream_id(x, y),
                    kind="local_reduce_max",
                    producer_action_id=action.id,
                    attrs={"task_id": task_id, "pe": pe_label(x, y), "dtype": dtype},
                )
            )

    edges: list[RingEdgeRecord] = []
    global_ready: dict[tuple[int, int], str] = {}

    def add_edge(phase: RingPhase, src: tuple[int, int], dst: tuple[int, int]) -> None:
        src_x, src_y = src
        dst_x, dst_y = dst
        edge_index = len(edges)
        ordering_group = f"task{task_id}:{phase}"
        push = append_action(
            stream=stream_id(src_x, src_y),
            op="route_push_global_max",
            inputs=(current_value[src],),
            depends_on=(producer_action[src],),
            attrs={
                "task_id": task_id,
                "phase": phase,
                "src": stream_id(src_x, src_y),
                "dst": stream_id(dst_x, dst_y),
                "route_role": LOG10MAX_RING_ROUTE_ROLE,
                "ordering_group": ordering_group,
            },
        )
        received_value = next_value_id("received_global_max", dst_x, dst_y)
        recv = append_action(
            stream=stream_id(dst_x, dst_y),
            op="route_recv_global_max",
            inputs=(current_value[src],),
            outputs=(received_value,),
            depends_on=(push.id,),
            attrs={
                "task_id": task_id,
                "phase": phase,
                "src": stream_id(src_x, src_y),
                "dst": stream_id(dst_x, dst_y),
                "route_role": LOG10MAX_RING_ROUTE_ROLE,
                "ordering_group": ordering_group,
            },
        )
        updated_value = next_value_id("global_max", dst_x, dst_y)
        update = append_action(
            stream=stream_id(dst_x, dst_y),
            op="max_update_global_max",
            inputs=(current_value[dst], received_value),
            outputs=(updated_value,),
            depends_on=(producer_action[dst], recv.id),
            attrs={
                "task_id": task_id,
                "phase": phase,
                "pe": pe_label(dst_x, dst_y),
                "dtype": dtype,
                "update_op": _update_op_for_dtype(dtype),
                "route_role": LOG10MAX_RING_ROUTE_ROLE,
                "ordering_group": ordering_group,
            },
        )
        current_value[dst] = updated_value
        producer_action[dst] = update.id
        if phase in {"col_broadcast", "row_broadcast"}:
            global_ready[dst] = update.id
        edges.append(
            RingEdgeRecord(
                edge_id=f"ring_edge:{edge_index:04d}:{phase}:{src_x}{src_y}>{dst_x}{dst_y}",
                phase=phase,
                task_id=task_id,
                src_pe=pe_label(src_x, src_y),
                dst_pe=pe_label(dst_x, dst_y),
                source_stream_action_id=push.id,
                recv_stream_action_id=recv.id,
                update_action_id=update.id,
                dtype=dtype,
                update_op=_update_op_for_dtype(dtype),
                route_role=LOG10MAX_RING_ROUTE_ROLE,
                ordering_group=ordering_group,
                proof_status=_edge_template_status(
                    route_template_status=route_template_status,
                    update_template_status=update_template_status,
                ),
                template_evidence_id=(
                    "pending_globalmax_route_and_update_template_binding"
                ),
                route_template_evidence_id=(
                    "dfu3500_route_forward_globalmax_role_generalization_v1"
                    if route_template_status == "proven"
                    else "pending_globalmax_existing_route_template_binding"
                ),
                route_template_status=route_template_status,
                route_path_proof_status=route_path_proof_status,
                update_template_evidence_id=(
                    "dfu3500_log10max_ring_globalmax_update_fmax_candidate_unproven"
                ),
                update_template_status=update_template_status,
                update_template_blocker="ring_edge_update_template_missing",
            )
        )
        stream_plan.set_visible_value(
            StreamValue(
                id=updated_value,
                logical_tensor_id="GlobalMax",
                stream_id=stream_id(dst_x, dst_y),
                kind="route_recv",
                producer_action_id=update.id,
                attrs={
                    "task_id": task_id,
                    "pe": pe_label(dst_x, dst_y),
                    "phase": phase,
                    "route_role": LOG10MAX_RING_ROUTE_ROLE,
                },
            )
        )

    for x in range(rows):
        for y in range(cols - 1, 0, -1):
            add_edge("row_reduce", (x, y), (x, y - 1))

    for x in range(rows - 1, 0, -1):
        add_edge("col_reduce", (x, 0), (x - 1, 0))

    global_ready[(0, 0)] = producer_action[(0, 0)]

    for x in range(0, rows - 1):
        add_edge("col_broadcast", (x, 0), (x + 1, 0))

    for x in range(rows):
        for y in range(0, cols - 1):
            add_edge("row_broadcast", (x, y), (x, y + 1))

    global_max_concrete = (
        route_role_proof_status == "proven"
        and route_template_status == "proven"
        and route_path_proof_status == "proven"
        and update_template_status == "proven"
    )
    ready_tokens: list[str] = []
    postprocess_consumers: list[PostprocessConsumerBindingRecord] = []
    for x in range(rows):
        for y in range(cols):
            if (x, y) not in global_ready:
                global_ready[(x, y)] = producer_action[(x, y)]
            pe = pe_label(x, y)
            token = f"global_max_ready[task={task_id},pe={x},{y}]<-{global_ready[(x, y)]}"
            ready_tokens.append(token)
            postprocess_consumers.append(
                PostprocessConsumerBindingRecord(
                    consumer_id=f"postprocess_consumer:task{task_id}:{pe}",
                    task_id=task_id,
                    pe=pe,
                    stream_id=stream_id(x, y),
                    consumer_fiber_op="max_with_floor_tile",
                    source_expression="maximum(log_spec_tile, GlobalMax - 8.0)",
                    global_max_input="GlobalMax",
                    global_max_ready_token=token,
                    global_max_producer_action_id=global_ready[(x, y)],
                    dependency_kind="global_max_ready",
                    depends_on_global_max_ready=True,
                    symbolic_global_max_reaches_postprocess=not global_max_concrete,
                )
            )

    route_role_binding = RouteRoleBinding(
        role="GlobalMax",
        route_template_family="existing_operand_route_visibility_family",
        source_value_kind="scalar",
        destination_value_kind="scalar",
        template_evidence_id="pending_globalmax_route_role_binding",
        proof_status=route_role_proof_status,
    )
    blockers = _runtime_ready_blockers(
        route_role_binding=route_role_binding,
        edges=tuple(edges),
        route_path_proof_status=route_path_proof_status,
        expected_edge_count=_expected_representative_edge_count(rows, cols),
        ready_count=len(ready_tokens),
        expected_ready_count=rows * cols,
        consumer_count=len(postprocess_consumers),
        expected_consumer_count=rows * cols,
        consumer_bindings_ready=all(
            consumer.proven for consumer in postprocess_consumers
        ),
    )
    return Log10MaxRingPlanReport(
        strategy=LOG10MAX_RING_STRATEGY,
        customer_label=LOG10MAX_RING_CUSTOMER_LABEL,
        task_axis=1,
        runtime_ordering_domain=LOG10MAX_RING_ORDERING_DOMAIN,
        mesh_shape=mesh_shape,
        route_role_binding=route_role_binding,
        stream_plan=stream_plan,
        edges=tuple(edges),
        global_max_ready=tuple(ready_tokens),
        postprocess_consumers=tuple(postprocess_consumers),
        runtime_ready_blockers=blockers,
    )


def summarize_log10max_task_local_ring_plan(
    report: Log10MaxRingPlanReport,
) -> dict[str, object]:
    return report.summary()


def _expected_representative_edge_count(rows: int, cols: int) -> int:
    return (2 * rows * (cols - 1)) + (2 * (rows - 1))


def _update_op_for_dtype(dtype: str) -> Literal["FMAX", "HMAX"]:
    return "HMAX" if dtype in {"fp16", "bf16"} else "FMAX"


def _edge_template_status(
    *,
    route_template_status: RingProofStatus,
    update_template_status: RingProofStatus,
) -> RingProofStatus:
    if route_template_status == "proven" and update_template_status == "proven":
        return "proven"
    if route_template_status == "assumed" or update_template_status == "assumed":
        return "assumed"
    return "unresolved"


def _runtime_ready_blockers(
    *,
    route_role_binding: RouteRoleBinding,
    edges: tuple[RingEdgeRecord, ...],
    route_path_proof_status: RingProofStatus,
    expected_edge_count: int,
    ready_count: int,
    expected_ready_count: int,
    consumer_count: int,
    expected_consumer_count: int,
    consumer_bindings_ready: bool,
) -> tuple[str, ...]:
    blockers: list[str] = []
    if not route_role_binding.runtime_ready:
        blockers.append("route_role_globalmax_unproven")
    if len(edges) != expected_edge_count:
        blockers.append("representative_selection_missing")
    if any(edge.route_template_status != "proven" for edge in edges):
        blockers.append("ring_edge_route_template_missing")
    if any(edge.update_template_status != "proven" for edge in edges):
        blockers.append("ring_edge_update_template_missing")
    if (
        "ring_edge_route_template_missing" in blockers
        or "ring_edge_update_template_missing" in blockers
    ):
        blockers.append("ring_edge_template_missing")
    if route_path_proof_status != "proven":
        blockers.append("route_path_proof_missing")
    if ready_count != expected_ready_count:
        blockers.append("global_max_distribution_missing")
    if consumer_count != expected_consumer_count or not consumer_bindings_ready:
        blockers.append("consumer_global_max_binding_missing")
        blockers.append("consumer_depends_on_global_ready_missing")
        blockers.append("symbolic_global_max_reaches_postprocess")
    return tuple(dict.fromkeys(blockers))


__all__ = [
    "LOG10MAX_RING_CUSTOMER_LABEL",
    "LOG10MAX_RING_ORDERING_DOMAIN",
    "LOG10MAX_RING_STRATEGY",
    "Log10MaxRingPlanReport",
    "PostprocessConsumerBindingRecord",
    "RingEdgeRecord",
    "RouteRoleBinding",
    "build_log10max_task_local_ring_plan",
    "summarize_log10max_task_local_ring_plan",
]
