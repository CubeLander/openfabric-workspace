"""GEMM -> ReLU -> store fiber op-chain builder.

This module is deliberately narrow.  It proves that a high-level GEMM+ReLU
stream plan can lower to a flat PE-local fiber chain:

    gemm_tile -> relu_tile -> store_tile

`relu_tile` is a first-class FiberOp kind and can flow through production
role/template status mapping.  The target template row placement is concrete,
but the byte writer still needs exact IMM/HMAX/FMAX row evidence.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, cast

from .fiber import (
    Fiber,
    FiberDependency,
    FiberOp,
    FiberOpKind,
    FragmentRef,
    FragmentRole,
    FragmentVisibilityKind,
    build_atomic_gemm_fiber,
)
from .stream import StreamAction, StreamPlan, StreamValue


@dataclass(frozen=True)
class ReluTemplateBindingGap:
    """One missing production binding needed after fiber lowering."""

    gap_id: str
    layer: str
    required_work: str
    blocking_status: str = "missing"

    def to_plan(self) -> dict[str, object]:
        return {
            "gap_id": self.gap_id,
            "layer": self.layer,
            "required_work": self.required_work,
            "blocking_status": self.blocking_status,
        }


@dataclass(frozen=True)
class ReluFiberChainReport:
    """Report for explicit GEMM+ReLU tile op-chain construction."""

    profile_id: str
    fibers: tuple[Fiber, ...]
    template_binding_gaps: tuple[ReluTemplateBindingGap, ...]
    diagnostics: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "ir": "relu_fiber_chain_report",
            "profile_id": self.profile_id,
            "chain_contract": "gemm_tile->relu_tile->store_tile",
            "fiber_count": len(self.fibers),
            "fibers": [fiber.to_plan() for fiber in self.fibers],
            "template_binding_gaps": [
                gap.to_plan() for gap in self.template_binding_gaps
            ],
            "diagnostics": list(self.diagnostics),
            "runtime_claim": "fiber_chain_only_not_runtime_ready",
        }


def build_gemm_relu_fiber_chain_report(plan: StreamPlan) -> ReluFiberChainReport:
    """Build explicit ReLU op-chain fibers from a GEMM+ReLU stream plan.

    The returned fibers intentionally contain a `relu_tile` op as a separate
    tile job.  Until the downstream writer gap in `template_binding_gaps` is
    closed, the result is fiber/template complete but not byte-emittable.
    """

    first_stream = sorted(plan.streams)[0]
    c_value = plan.visible_value(stream_id=first_stream, logical_tensor_id="C_dtensor")
    c_tile_counts = tuple(int(dim) for dim in c_value.attrs["tile_counts"])
    fibers: list[Fiber] = []
    diagnostics: list[str] = []

    for stream_id in sorted(plan.streams):
        stream_actions = tuple(plan.streams[stream_id])
        relu_action = _single_action(stream_actions, "relu")
        store_action = _single_action(stream_actions, "sram_store_Y")
        if relu_action is None:
            diagnostics.append(f"{stream_id}: missing high-level relu action")
            continue
        if store_action is None:
            diagnostics.append(f"{stream_id}: missing high-level store action")
            continue

        task_id = _parse_task_id(stream_id)
        a_stream_value = plan.visible_value(stream_id=stream_id, logical_tensor_id="A_dtensor")
        b_stream_value = plan.visible_value(stream_id=stream_id, logical_tensor_id="B_dtensor")
        for coord in _assigned_output_tile_coords(
            task_id=task_id,
            output_tile_counts=c_tile_counts,
        ):
            base = build_atomic_gemm_fiber(
                stream_id=stream_id,
                m_tile=int(coord["m_tile"]),
                n_tile=int(coord["n_tile"]),
                a_visibility_kind=_visibility_kind(a_stream_value),
                b_visibility_kind=_visibility_kind(b_stream_value),
                a_visibility_action_id=a_stream_value.producer_action_id,
                b_visibility_action_id=b_stream_value.producer_action_id,
            )
            fibers.append(
                _insert_relu_tile(
                    base,
                    relu_action=relu_action,
                    store_action=store_action,
                )
            )

    return ReluFiberChainReport(
        profile_id="gemm_relu_explicit_fiber_chain_report",
        fibers=tuple(fibers),
        template_binding_gaps=_relu_template_binding_gaps(),
        diagnostics=tuple(diagnostics),
    )


def summarize_relu_fiber_chain_report(
    report: ReluFiberChainReport,
) -> dict[str, object]:
    op_sequence_counts: dict[str, int] = {}
    op_counts: dict[str, int] = {}
    relu_status_counts: dict[str, int] = {}
    for fiber in report.fibers:
        sequence = "->".join(str(op.op) for op in fiber.ops)
        op_sequence_counts[sequence] = op_sequence_counts.get(sequence, 0) + 1
        for op in fiber.ops:
            op_counts[str(op.op)] = op_counts.get(str(op.op), 0) + 1
            if op.op == "relu_tile":
                status = str(op.attrs.get("template_binding_status", "unknown"))
                relu_status_counts[status] = relu_status_counts.get(status, 0) + 1
    return {
        "profile_id": report.profile_id,
        "fiber_count": len(report.fibers),
        "op_sequence_counts": dict(sorted(op_sequence_counts.items())),
        "op_counts": dict(sorted(op_counts.items())),
        "relu_template_binding_status_counts": dict(
            sorted(relu_status_counts.items())
        ),
        "template_binding_gap_count": len(report.template_binding_gaps),
        "template_binding_gaps": [
            gap.gap_id for gap in report.template_binding_gaps
        ],
        "diagnostic_count": len(report.diagnostics),
        "runtime_claim": "fiber_chain_only_not_runtime_ready",
    }


def _insert_relu_tile(
    fiber: Fiber,
    *,
    relu_action: StreamAction,
    store_action: StreamAction,
) -> Fiber:
    if len(fiber.ops) != 2 or fiber.ops[0].op != "gemm_tile" or fiber.ops[1].op != "store_tile":
        raise ValueError("expected base atomic GEMM fiber gemm_tile->store_tile")

    gemm = fiber.ops[0]
    c_fragment = gemm.outputs[0]
    y_fragment = FragmentRef(
        role=cast(FragmentRole, "Y"),
        axes=c_fragment.axes,
    )
    relu = FiberOp(
        id=f"{fiber.id}:0001:relu_tile",
        stream_id=fiber.stream_id,
        fiber_id=fiber.id,
        order_index=1,
        op=cast(FiberOpKind, "relu_tile"),
        inputs=(c_fragment,),
        outputs=(y_fragment,),
        depends_on=(
            FiberDependency(
                source_op_id=gemm.id,
                kind="phase_order",
                expected_satisfaction="same_block_order",
                via_fragment=c_fragment,
                reason="ReLU consumes the atomic GEMM tile output as a separate tile job",
            ),
        ),
        attrs={
            "placement": "tile_body",
            "semantic_op": "relu",
            "atom_boundary": "fiber_atomic_tile_job",
            "source_stream_action_id": relu_action.id,
            "template_binding_status": "production_mapping_concrete_writer_blocked",
            "required_template_binding": "dfu3500_relu_tile_template",
            "candidate_instruction_family": "HMAX_OR_FMAX_WITH_ZERO",
        },
    )
    store = FiberOp(
        id=f"{fiber.id}:0002:store_tile",
        stream_id=fiber.stream_id,
        fiber_id=fiber.id,
        order_index=2,
        op="store_tile",
        inputs=(y_fragment,),
        depends_on=(
            FiberDependency(
                source_op_id=relu.id,
                kind="store_order",
                expected_satisfaction="same_block_order",
                via_fragment=y_fragment,
                reason="store consumes the explicit ReLU tile output",
            ),
        ),
        attrs={
            "placement": "tile_store",
            "semantic_op": "store",
            "atom_boundary": "fiber_atomic_tile_job",
            "source_stream_action_id": store_action.id,
            "store_tensor": "Y",
        },
    )
    return Fiber(
        id=fiber.id,
        stream_id=fiber.stream_id,
        m_tile=fiber.m_tile,
        n_tile=fiber.n_tile,
        ops=(gemm, relu, store),
        attrs={
            **dict(fiber.attrs),
            "strategy_id": "gemm_relu_explicit_atomic_tile_chain",
            "runtime_claim": "fiber_chain_only_not_runtime_ready",
            "template_binding_gap": "relu_tile",
            "flat_chain": ("gemm_tile", "relu_tile", "store_tile"),
        },
    )


def _relu_template_binding_gaps() -> tuple[ReluTemplateBindingGap, ...]:
    return (
        ReluTemplateBindingGap(
            gap_id="binary_writer_relu_tile",
            layer="binary lowering",
            required_work=(
                "bind exact IMM-zero and HMAX/FMAX template rows, operand indexes, "
                "local_order, raw inst_t bytes, and raw_template_row_sha256"
            ),
        ),
    )


def _single_action(
    actions: tuple[StreamAction, ...],
    op: str,
) -> StreamAction | None:
    matches = tuple(action for action in actions if action.op == op)
    if not matches:
        return None
    if len(matches) != 1:
        raise ValueError(f"expected one {op} action, got {len(matches)}")
    return matches[0]


def _visibility_kind(value: StreamValue) -> FragmentVisibilityKind:
    if value.kind == "sram_read":
        return "sram_read"
    if value.kind == "route_recv":
        return "route_recv"
    raise ValueError(f"unsupported stream visibility kind for fiber lowering: {value.kind}")


def _parse_task_id(stream_id: str) -> int:
    task_text, _ = stream_id.split("_pe", 1)
    return int(task_text.removeprefix("t"))


def _assigned_output_tile_coords(
    *,
    task_id: int,
    output_tile_counts: tuple[int, int],
) -> tuple[dict[str, int], ...]:
    work_shape = {
        "m_tile": int(output_tile_counts[0]),
        "n_tile": int(output_tile_counts[1]),
    }
    return tuple(
        coord
        for coord in (
            {"m_tile": m_tile, "n_tile": n_tile}
            for m_tile in range(work_shape["m_tile"])
            for n_tile in range(work_shape["n_tile"])
        )
        if _linear_work_index(coord, work_shape, ("m_tile", "n_tile")) == task_id
    )


def _linear_work_index(
    coord: dict[str, int],
    shape: dict[str, int],
    axis_order: tuple[str, ...],
) -> int:
    index = 0
    stride = 1
    for axis in reversed(axis_order):
        index += int(coord[axis]) * stride
        stride *= int(shape[axis])
    return index


__all__ = [
    "ReluFiberChainReport",
    "ReluTemplateBindingGap",
    "build_gemm_relu_fiber_chain_report",
    "summarize_relu_fiber_chain_report",
]
