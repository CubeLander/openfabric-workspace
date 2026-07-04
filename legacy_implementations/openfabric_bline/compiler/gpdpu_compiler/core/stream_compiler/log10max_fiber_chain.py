"""Report-only log10max semantic lowering to a flat FiberOp chain.

This module answers one B-line question only:

    Can the current log10max source expression be represented as a flat
    sequence of PE-local atomic FiberOps?

It deliberately does not expand any FiberOp into instruction rows, PE
micro-steps, or vendor subtasks.  Each row here is an atomic tile job that a
later template-binding pass must bind or block.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .fiber import Fiber, FiberDependency, FiberOp, FragmentRef
from .log10max_collective_strategy import (
    LOG10MAX_RING_FIRST_CUSTOMER_LABEL,
    LOG10MAX_RING_FIRST_STRATEGY,
    RING_FIRST_DELIVERY_BLOCKERS,
)
from .log10max_template_pack import (
    LOG10MAX_CLAMP_MIN,
    LOG10MAX_DTYPE,
    LOG10MAX_GLOBAL_THRESHOLD_OFFSET,
    LOG10MAX_LOG10_2,
    LOG10MAX_OUTPUT_BIAS,
    LOG10MAX_OUTPUT_SCALE,
    S5_UNRESOLVED_GLOBAL_SCALAR_INPUT,
    build_log10max_status_report,
)

JsonValue = object
Log10MaxFiberOpKind = Literal[
    "clamp_min_tile",
    "log10_tile",
    "local_reduce_max_tile",
    "global_max_tile",
    "max_with_floor_tile",
    "affine_scale_tile",
    "store_tile",
]
FiberTemplateStatus = Literal[
    "template_ready",
    "blocked_on_collective_template",
    "blocked_on_global_scalar",
]

LOG10MAX_FIBER_CHAIN_PROFILE_ID = "dfu3500_log10max_fiber_chain_v1"


@dataclass(frozen=True)
class Log10MaxFiberChainOp:
    """One atomic log10max FiberOp row.

    `template_status` is intentionally about the atomic op's next binding step.
    Dataflow readiness is summarized by the parent report, so a later op such
    as `store_tile` may be template-ready while the whole chain is still blocked
    by the collective/global scalar op.
    """

    id: str
    order_index: int
    op: Log10MaxFiberOpKind
    source_chip_ops: tuple[str, ...]
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    depends_on: tuple[str, ...]
    template_key: str
    template_status: FiberTemplateStatus
    blocker_ids: tuple[str, ...] = ()
    attrs: dict[str, JsonValue] = field(default_factory=dict)

    @property
    def template_ready(self) -> bool:
        return self.template_status == "template_ready"

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "order_index": self.order_index,
            "op": self.op,
            "atom_boundary": "pe_local_fiber_op",
            "source_chip_ops": list(self.source_chip_ops),
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "depends_on": list(self.depends_on),
            "template_key": self.template_key,
            "template_status": self.template_status,
            "template_ready": self.template_ready,
            "blocker_ids": list(self.blocker_ids),
            "attrs": dict(self.attrs),
        }


@dataclass(frozen=True)
class Log10MaxFiberChainReport:
    """Stable report for the log10max FiberOp-chain projection."""

    profile_id: str
    operator: str
    fiber_id: str
    stream_id: str
    ops: tuple[Log10MaxFiberChainOp, ...]
    selected_collective_strategy: str
    upstream_template_summary: dict[str, object]
    notes: tuple[str, ...] = ()

    def dependency_edges(self) -> tuple[tuple[str, str], ...]:
        edges: list[tuple[str, str]] = []
        for op in self.ops:
            for dependency in op.depends_on:
                edges.append((dependency, op.id))
        return tuple(edges)

    def summary(self) -> dict[str, object]:
        status_counts: dict[str, int] = {}
        for op in self.ops:
            status_counts[op.template_status] = (
                status_counts.get(op.template_status, 0) + 1
            )
        blocked = tuple(op for op in self.ops if not op.template_ready)
        return {
            "profile_id": self.profile_id,
            "operator": self.operator,
            "fiber_id": self.fiber_id,
            "stream_id": self.stream_id,
            "fiber_op_count": len(self.ops),
            "op_sequence": [op.op for op in self.ops],
            "template_status_counts": dict(sorted(status_counts.items())),
            "template_ready_count": len(self.ops) - len(blocked),
            "blocked_count": len(blocked),
            "blocked_ops": [op.op for op in blocked],
            "selected_collective_strategy": self.selected_collective_strategy,
            "chain_template_complete": not blocked,
            "runtime_ready_claim": False,
            "row_bytes_claim": False,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_fiber_chain_report",
            "summary": self.summary(),
            "source_expression": {
                "expression": (
                    "out=(maximum(log10(clamp_min(mel_spec,1e-10)), "
                    "reduce_max(log10(clamp_min(mel_spec,1e-10)))-8)+4)*0.25"
                ),
                "dtype": LOG10MAX_DTYPE,
                "constants": {
                    "clamp_min": LOG10MAX_CLAMP_MIN,
                    "log10_2": LOG10MAX_LOG10_2,
                    "threshold_offset": LOG10MAX_GLOBAL_THRESHOLD_OFFSET,
                    "output_bias": LOG10MAX_OUTPUT_BIAS,
                    "output_scale": LOG10MAX_OUTPUT_SCALE,
                },
            },
            "layering_policy": (
                "This is a source-to-FiberOp-chain report. It must not expand "
                "GEMM/log/reduce/collective internals into fiber rows; each "
                "FiberOp is an atomic PE-local tile job for later template "
                "binding."
            ),
            "fiber": {
                "id": self.fiber_id,
                "stream_id": self.stream_id,
                "ops": [op.to_plan() for op in self.ops],
                "dependency_edges_view": [
                    list(edge) for edge in self.dependency_edges()
                ],
            },
            "upstream_template_summary": dict(self.upstream_template_summary),
            "notes": list(self.notes),
        }


def build_log10max_fiber_chain_report(
    *,
    stream_id: str = "stream:log10max:0",
    fiber_id: str = "fiber:log10max:tile0",
    global_scalar_input: str = S5_UNRESOLVED_GLOBAL_SCALAR_INPUT,
) -> Log10MaxFiberChainReport:
    """Build the minimal log10max semantic FiberOp-chain report."""

    template_status = build_log10max_status_report(
        global_scalar_input=global_scalar_input,
    )
    template_summary = template_status["summary"]
    selected_strategy = LOG10MAX_RING_FIRST_STRATEGY.value
    ops = (
        Log10MaxFiberChainOp(
            id=f"{fiber_id}:0000:clamp_min_tile",
            order_index=0,
            op="clamp_min_tile",
            source_chip_ops=("clamp_min",),
            inputs=("mel_spec_tile",),
            outputs=("clamped_tile",),
            depends_on=(),
            template_key="local_elementwise:FMAX:clamp_min",
            template_status="template_ready",
            attrs={
                "dtype": LOG10MAX_DTYPE,
                "constant": LOG10MAX_CLAMP_MIN,
                "source_template_step": "s6a.step0.clamp_min",
            },
        ),
        Log10MaxFiberChainOp(
            id=f"{fiber_id}:0001:log10_tile",
            order_index=1,
            op="log10_tile",
            source_chip_ops=("log10",),
            inputs=("clamped_tile",),
            outputs=("local_log10_tile",),
            depends_on=(f"{fiber_id}:0000:clamp_min_tile",),
            template_key="local_elementwise:FLOG2_FMUL:log10",
            template_status="template_ready",
            attrs={
                "dtype": LOG10MAX_DTYPE,
                "lowering": "FLOG2*log10(2)",
                "constant_log10_2": LOG10MAX_LOG10_2,
                "source_template_step": "s6a.step1.flog2_times_log10_2",
            },
        ),
        Log10MaxFiberChainOp(
            id=f"{fiber_id}:0002:local_reduce_max_tile",
            order_index=2,
            op="local_reduce_max_tile",
            source_chip_ops=("reduce_max",),
            inputs=("local_log10_tile",),
            outputs=("local_max_scalar",),
            depends_on=(f"{fiber_id}:0001:log10_tile",),
            template_key="local_reduce:SHFL_FMAX:reduce_max",
            template_status="template_ready",
            attrs={
                "dtype": LOG10MAX_DTYPE,
                "visibility_kind": "local_scalar",
                "source_template_step": "s6a.step2.local_reduce_max",
            },
        ),
        Log10MaxFiberChainOp(
            id=f"{fiber_id}:0003:global_max_tile",
            order_index=3,
            op="global_max_tile",
            source_chip_ops=("reduce_max",),
            inputs=("local_max_scalar",),
            outputs=("global_max_scalar",),
            depends_on=(f"{fiber_id}:0002:local_reduce_max_tile",),
            template_key=f"collective:{selected_strategy}:global_max",
            template_status="blocked_on_collective_template",
            blocker_ids=RING_FIRST_DELIVERY_BLOCKERS,
            attrs={
                "collective_kind": "all_reduce_max_scalar",
                "selected_strategy": selected_strategy,
                "customer_label": LOG10MAX_RING_FIRST_CUSTOMER_LABEL.value,
                "physical_allreduce_claim": False,
                "delivery_strategy": selected_strategy,
                "preferred_v1_strategy": selected_strategy,
                "direct_route_reduce_broadcast": "deferred",
                "runtime_ordering_domain": "single_task_group",
                "cross_task_one_app_ring": "forbidden",
                "first_delivery_plan": "representative_row_column_reduce_broadcast",
            },
        ),
        Log10MaxFiberChainOp(
            id=f"{fiber_id}:0004:max_with_floor_tile",
            order_index=4,
            op="max_with_floor_tile",
            source_chip_ops=("maximum", "add_scalar"),
            inputs=("local_log10_tile", "global_max_scalar"),
            outputs=("clipped_tile",),
            depends_on=(
                f"{fiber_id}:0001:log10_tile",
                f"{fiber_id}:0003:global_max_tile",
            ),
            template_key="local_elementwise:FMAX:global_max_minus_8",
            template_status="blocked_on_global_scalar",
            blocker_ids=("global_max_tile_template_blocked",),
            attrs={
                "dtype": LOG10MAX_DTYPE,
                "threshold_expr": "global_max_scalar + (-8.0)",
                "threshold_offset": LOG10MAX_GLOBAL_THRESHOLD_OFFSET,
                "source_template_step": (
                    "s6a.step3.maximum_with_symbolic_global_scalar"
                ),
                "local_template_shape_ready": True,
            },
        ),
        Log10MaxFiberChainOp(
            id=f"{fiber_id}:0005:affine_scale_tile",
            order_index=5,
            op="affine_scale_tile",
            source_chip_ops=("add_scalar", "mul_scalar"),
            inputs=("clipped_tile",),
            outputs=("normalized_tile",),
            depends_on=(f"{fiber_id}:0004:max_with_floor_tile",),
            template_key="local_elementwise_span:FADD_FMUL:affine_scale",
            template_status="template_ready",
            attrs={
                "dtype": LOG10MAX_DTYPE,
                "bias": LOG10MAX_OUTPUT_BIAS,
                "scale": LOG10MAX_OUTPUT_SCALE,
                "source_template_steps": (
                    "s6a.step4.add_scalar",
                    "s6a.step5.mul_scalar",
                ),
            },
        ),
        Log10MaxFiberChainOp(
            id=f"{fiber_id}:0006:store_tile",
            order_index=6,
            op="store_tile",
            source_chip_ops=("store",),
            inputs=("normalized_tile",),
            outputs=("Y_sram_tile",),
            depends_on=(f"{fiber_id}:0005:affine_scale_tile",),
            template_key="tile_store:STD",
            template_status="template_ready",
            attrs={
                "dtype": LOG10MAX_DTYPE,
                "source_template_step": "s6a.step6.store",
            },
        ),
    )
    return Log10MaxFiberChainReport(
        profile_id=LOG10MAX_FIBER_CHAIN_PROFILE_ID,
        operator="log10max",
        fiber_id=fiber_id,
        stream_id=stream_id,
        ops=ops,
        selected_collective_strategy=selected_strategy,
        upstream_template_summary=dict(template_summary),
        notes=(
            "The source-to-fiber lowering gap is closed as a report-only "
            "atomic op-chain.",
            "Binary progress is blocked by the collective/global scalar "
            "template binding, not by source-to-fiber expressiveness.",
        ),
    )


def build_log10max_production_fiber(
    *,
    stream_id: str = "stream:log10max:0",
    fiber_id: str = "fiber:log10max:tile0",
) -> Fiber:
    """Build the shared Fiber/FiberOp form for one log10max tile chain."""

    x = FragmentRef.make("X", tile=0)
    x_clamped = FragmentRef.make("X_clamped", tile=0)
    local_log10 = FragmentRef.make("LocalLog10", tile=0)
    local_max = FragmentRef.make("LocalMax", tile=0)
    global_max = FragmentRef.make("GlobalMax", tile=0)
    clipped = FragmentRef.make("Clipped", tile=0)
    y = FragmentRef.make("Y", tile=0)

    def dep(source: FiberOp, fragment: FragmentRef, reason: str) -> FiberDependency:
        return FiberDependency(
            source_op_id=source.id,
            kind="phase_order",
            expected_satisfaction="same_block_order",
            via_fragment=fragment,
            reason=reason,
        )

    clamp = FiberOp(
        id=f"{fiber_id}:0000:clamp_min_tile",
        stream_id=stream_id,
        fiber_id=fiber_id,
        order_index=0,
        op="clamp_min_tile",
        inputs=(x,),
        outputs=(x_clamped,),
        attrs={
            "placement": "tile_body",
            "semantic_op": "clamp_min",
            "atom_boundary": "fiber_atomic_tile_job",
            "constant": LOG10MAX_CLAMP_MIN,
            "required_template_binding": "dfu3500_log10max_clamp_min_tile",
        },
    )
    log10 = FiberOp(
        id=f"{fiber_id}:0001:log10_tile",
        stream_id=stream_id,
        fiber_id=fiber_id,
        order_index=1,
        op="log10_tile",
        inputs=(x_clamped,),
        outputs=(local_log10,),
        depends_on=(dep(clamp, x_clamped, "log10 consumes clamped tile"),),
        attrs={
            "placement": "tile_body",
            "semantic_op": "log10",
            "atom_boundary": "fiber_atomic_tile_job",
            "lowering": "FLOG2*log10(2)",
            "constant_log10_2": LOG10MAX_LOG10_2,
            "required_template_binding": "dfu3500_log10max_log10_tile",
        },
    )
    local_reduce = FiberOp(
        id=f"{fiber_id}:0002:local_reduce_max_tile",
        stream_id=stream_id,
        fiber_id=fiber_id,
        order_index=2,
        op="local_reduce_max_tile",
        inputs=(local_log10,),
        outputs=(local_max,),
        depends_on=(dep(log10, local_log10, "local reduce consumes log10 tile"),),
        attrs={
            "placement": "tile_body",
            "semantic_op": "local_reduce_max",
            "atom_boundary": "fiber_atomic_tile_job",
            "visibility_kind": "local_scalar",
            "required_template_binding": "dfu3500_log10max_local_reduce_max_tile",
        },
    )
    global_reduce = FiberOp(
        id=f"{fiber_id}:0003:global_max_tile",
        stream_id=stream_id,
        fiber_id=fiber_id,
        order_index=3,
        op="global_max_tile",
        inputs=(local_max,),
        outputs=(global_max,),
        depends_on=(dep(local_reduce, local_max, "global max consumes local max scalar"),),
        attrs={
            "placement": "tile_body",
            "semantic_op": "global_max",
            "atom_boundary": "fiber_atomic_tile_job",
            "selected_strategy": LOG10MAX_RING_FIRST_STRATEGY.value,
            "customer_collective_label": LOG10MAX_RING_FIRST_CUSTOMER_LABEL.value,
            "direct_route_reduce_broadcast": "deferred",
            "runtime_ordering_domain": "single_task_group",
            "template_binding_status": "blocked_on_collective_template",
            "physical_allreduce_claim": False,
        },
    )
    maximum = FiberOp(
        id=f"{fiber_id}:0004:max_with_floor_tile",
        stream_id=stream_id,
        fiber_id=fiber_id,
        order_index=4,
        op="max_with_floor_tile",
        inputs=(local_log10, global_max),
        outputs=(clipped,),
        depends_on=(
            dep(log10, local_log10, "maximum consumes local log10 tile"),
            dep(global_reduce, global_max, "maximum waits for global threshold scalar"),
        ),
        attrs={
            "placement": "tile_body",
            "semantic_op": "max_with_floor",
            "atom_boundary": "fiber_atomic_tile_job",
            "threshold_offset": LOG10MAX_GLOBAL_THRESHOLD_OFFSET,
            "template_binding_status": "blocked_on_global_scalar",
            "local_template_shape_ready": True,
        },
    )
    affine = FiberOp(
        id=f"{fiber_id}:0005:affine_scale_tile",
        stream_id=stream_id,
        fiber_id=fiber_id,
        order_index=5,
        op="affine_scale_tile",
        inputs=(clipped,),
        outputs=(y,),
        depends_on=(dep(maximum, clipped, "affine scale consumes clipped tile"),),
        attrs={
            "placement": "tile_body",
            "semantic_op": "affine_scale",
            "atom_boundary": "fiber_atomic_tile_job",
            "bias": LOG10MAX_OUTPUT_BIAS,
            "scale": LOG10MAX_OUTPUT_SCALE,
            "required_template_binding": "dfu3500_log10max_affine_scale_tile",
        },
    )
    store = FiberOp(
        id=f"{fiber_id}:0006:store_tile",
        stream_id=stream_id,
        fiber_id=fiber_id,
        order_index=6,
        op="store_tile",
        inputs=(y,),
        depends_on=(dep(affine, y, "store consumes normalized output tile"),),
        attrs={
            "placement": "tile_store",
            "semantic_op": "store",
            "atom_boundary": "fiber_atomic_tile_job",
        },
    )

    return Fiber(
        id=fiber_id,
        stream_id=stream_id,
        m_tile=0,
        n_tile=0,
        ops=(clamp, log10, local_reduce, global_reduce, maximum, affine, store),
        attrs={
            "strategy_id": "log10max_flat_local_tile_chain",
            "atom_boundary": "fiber_ops_are_atomic_tile_jobs",
            "blocked_ops": ("global_max_tile", "max_with_floor_tile"),
            "forbidden_expansions": (
                "pe00_scalar_rows_inside_local_fiber_ops",
                "fused_log10max_template_inside_fiber",
            ),
        },
    )


def summarize_log10max_fiber_chain_report(
    report: Log10MaxFiberChainReport,
) -> dict[str, object]:
    """Return a focused summary for tools and merge reports."""

    return report.summary()
