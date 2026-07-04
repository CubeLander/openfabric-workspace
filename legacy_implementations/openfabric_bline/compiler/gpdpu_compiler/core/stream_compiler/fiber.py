"""Experimental flat fiber-op model.

This is an internal compiler model, not a user-facing API.

`StreamPlan` answers the whole-value visibility question:

    Which stream obtains a value, and through which stream-level route/load
    path does that value become visible?

A `Fiber` answers the stream-local tile-job sequencing question with a flat op
list:

    1. Which atomic tile jobs run on this stream?
    2. In what dependency order do those jobs consume stream-visible values?
    3. Which downstream store or tile op-chain action consumes each output?

There is intentionally no separate "micro dataflow plan" authority.  A fiber is
just a flat sequence of `FiberOp` records.  `order_index` is stable presentation
/ generation order; correctness comes from explicit `depends_on` plus value
inputs/outputs, not from list order alone.

The stream layer owns inter-stream visibility.  The fiber layer owns the flat
stream-local atomic tile jobs that consume that visibility.  It must not expand
GEMM internals such as K-loop updates, accumulator prepare/finalize, or
target-specific instruction staging as semantic fiber operations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .fiber_patterns import (
    FiberPatternPlan,
    FiberPatternStep,
    build_matmul_sequential_reduction_pattern,
)


DependencyKind = Literal[
    "fragment_visibility",
    "carried_state",
    "phase_order",
    "store_order",
]
DependencySatisfaction = Literal[
    "route_or_local_materialization",
    "loop_instance_order",
    "subtask_order",
    "same_block_order",
    "unresolved",
]
FiberOpKind = Literal[
    "gemm_tile",
    "relu_tile",
    "clamp_min_tile",
    "log10_tile",
    "local_reduce_max_tile",
    "global_max_tile",
    "max_with_floor_tile",
    "affine_scale_tile",
    "store_tile",
    # Legacy expanded bridge kinds. These are not B-line fiber semantics.
    "accumulator_prepare",
    "fragment_sram_read",
    "fragment_route_push",
    "fragment_route_recv",
    "gemm_update",
    "finalize_accumulator",
    "store_fragment",
]
FragmentRole = Literal[
    "A",
    "B",
    "C_acc",
    "C",
    "X",
    "X_clamped",
    "LocalLog10",
    "LocalMax",
    "GlobalMax",
    "Clipped",
    "Y",
]
FragmentVisibilityKind = Literal["sram_read", "route_recv", "route_push"]

@dataclass(frozen=True)
class FragmentRef:
    """Named tile fragment used by one stream-local fiber."""

    role: FragmentRole
    axes: tuple[tuple[str, int], ...]

    @classmethod
    def make(cls, role: FragmentRole, **axes: int) -> "FragmentRef":
        return cls(role=role, axes=tuple(sorted((key, int(value)) for key, value in axes.items())))

    def label(self) -> str:
        axis_text = ",".join(f"{axis}{value}" for axis, value in self.axes)
        return f"{self.role}({axis_text})"

    def to_plan(self) -> dict[str, object]:
        return {
            "role": self.role,
            "axes": {axis: value for axis, value in self.axes},
            "label": self.label(),
        }


@dataclass(frozen=True)
class FiberDependency:
    """Semantic dependency edge between flat fiber ops.

    The edge is intentionally retained at fiber level even if a later lowering
    can prove it is automatically satisfied by subtask order, loop instance
    order, same-block order, or route/local materialization.
    """

    source_op_id: str
    kind: DependencyKind
    expected_satisfaction: DependencySatisfaction
    via_fragment: FragmentRef | None = None
    reason: str = ""

    def label(self) -> str:
        fragment = f" via {self.via_fragment.label()}" if self.via_fragment is not None else ""
        return (
            f"{self.source_op_id}"
            f"[{self.kind}->{self.expected_satisfaction}{fragment}]"
        )

    def to_plan(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "source_op_id": self.source_op_id,
            "kind": self.kind,
            "expected_satisfaction": self.expected_satisfaction,
            "reason": self.reason,
        }
        if self.via_fragment is not None:
            payload["via_fragment"] = self.via_fragment.to_plan()
        return payload


@dataclass(frozen=True)
class FiberOp:
    """One flat op inside a stream-local fiber."""

    id: str
    stream_id: str
    fiber_id: str
    order_index: int
    op: FiberOpKind
    inputs: tuple[FragmentRef, ...] = ()
    outputs: tuple[FragmentRef, ...] = ()
    depends_on: tuple[FiberDependency, ...] = ()
    attrs: dict[str, object] = field(default_factory=dict)

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "stream_id": self.stream_id,
            "fiber_id": self.fiber_id,
            "order_index": self.order_index,
            "op": self.op,
            "inputs": [fragment.to_plan() for fragment in self.inputs],
            "outputs": [fragment.to_plan() for fragment in self.outputs],
            "depends_on": [dependency.to_plan() for dependency in self.depends_on],
            "attrs": dict(self.attrs),
        }


@dataclass(frozen=True)
class Fiber:
    """Flat stream-local op sequence for one assigned output tile."""

    id: str
    stream_id: str
    m_tile: int
    n_tile: int
    ops: tuple[FiberOp, ...]
    attrs: dict[str, object] = field(default_factory=dict)

    def dependency_edges(self) -> tuple[tuple[str, str], ...]:
        edges: list[tuple[str, str]] = []
        for op in self.ops:
            for dependency in op.depends_on:
                edges.append((dependency.source_op_id, op.id))
        return tuple(edges)

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "stream_id": self.stream_id,
            "m_tile": self.m_tile,
            "n_tile": self.n_tile,
            "ops": [op.to_plan() for op in self.ops],
            "dependency_edges_view": [list(edge) for edge in self.dependency_edges()],
            "attrs": dict(self.attrs),
        }


def build_atomic_gemm_fiber(
    *,
    stream_id: str,
    m_tile: int,
    n_tile: int,
    a_visibility_kind: FragmentVisibilityKind = "sram_read",
    b_visibility_kind: FragmentVisibilityKind = "sram_read",
    a_visibility_action_id: str | None = None,
    b_visibility_action_id: str | None = None,
) -> Fiber:
    """Build the B-line semantic fiber for one GEMM output tile.

    GEMM is atomic at fiber level.  K-loop updates, accumulator management, and
    vendor instruction row expansion belong to later physical lowering passes
    or explicit bridge code, not to the semantic FiberOp sequence.
    """

    fiber_id = f"fiber:{stream_id}:m{m_tile}:n{n_tile}"
    a_fragment = FragmentRef.make("A", m_tile=m_tile)
    b_fragment = FragmentRef.make("B", n_tile=n_tile)
    c_fragment = FragmentRef.make("C", m_tile=m_tile, n_tile=n_tile)
    gemm = FiberOp(
        id=f"{fiber_id}:0000:gemm_tile",
        stream_id=stream_id,
        fiber_id=fiber_id,
        order_index=0,
        op="gemm_tile",
        inputs=(a_fragment, b_fragment),
        outputs=(c_fragment,),
        attrs={
            "placement": "tile_body",
            "semantic_op": "gemm",
            "atom_boundary": "fiber_atomic_tile_job",
            "a_visibility_kind": a_visibility_kind,
            "b_visibility_kind": b_visibility_kind,
            "a_visibility_action_id": a_visibility_action_id,
            "b_visibility_action_id": b_visibility_action_id,
            "lowering_required": "expand_gemm_tile_in_physical_lowering",
        },
    )
    store = FiberOp(
        id=f"{fiber_id}:0001:store_tile",
        stream_id=stream_id,
        fiber_id=fiber_id,
        order_index=1,
        op="store_tile",
        inputs=(c_fragment,),
        depends_on=(
            FiberDependency(
                source_op_id=gemm.id,
                kind="store_order",
                expected_satisfaction="same_block_order",
                via_fragment=c_fragment,
                reason="store consumes the atomic GEMM tile output",
            ),
        ),
        attrs={
            "placement": "tile_store",
            "semantic_op": "store",
            "atom_boundary": "fiber_atomic_tile_job",
        },
    )
    return Fiber(
        id=fiber_id,
        stream_id=stream_id,
        m_tile=m_tile,
        n_tile=n_tile,
        ops=(gemm, store),
        attrs={
            "strategy_id": "gemm_atomic_tile_sequence",
            "atom_boundary": "fiber_ops_are_atomic_tile_jobs",
            "forbidden_expansions": (
                "k_loop_inside_fiber",
                "accumulator_prepare_inside_fiber",
                "accumulator_finalize_inside_fiber",
                "relu_inside_gemm_fiber",
            ),
        },
    )


def build_expanded_gemm_bridge_fiber(
    *,
    stream_id: str,
    m_tile: int,
    n_tile: int,
    k_steps: int,
    a_visibility_kind: FragmentVisibilityKind = "sram_read",
    b_visibility_kind: FragmentVisibilityKind = "sram_read",
    a_visibility_action_id: str | None = None,
    b_visibility_action_id: str | None = None,
    fiber_pattern_plan: FiberPatternPlan | None = None,
) -> Fiber:
    """Build the legacy expanded GEMM bridge sequence.

    This is not B-line fiber semantics.  It exists only as an explicit bridge
    for old debug/binary projection work that still needs sequential-K rows.
    New B-line lowering should use `build_atomic_gemm_fiber` and perform
    target-specific GEMM expansion after the fiber layer.

    The bridge sequence encodes the same placement facts directly in ops:
    - accumulator prepare is outside the K-loop body;
    - A/B fragment visibility actions live in each K-loop body step;
    - each update depends on materialized A/B and previous accumulator state;
    - finalize / store happen after the final carried accumulator.

    This function does not decide the route path for A(m,k) or B(k,n).
    The caller passes the terminal stream-level visibility kind from the
    already-built `StreamPlan`; route path expansion remains a later pass.
    """

    pattern_plan = _validate_sequential_reduction_pattern(
        fiber_pattern_plan or build_matmul_sequential_reduction_pattern()
    )
    fiber_id = f"fiber:{stream_id}:m{m_tile}:n{n_tile}"
    ops: list[FiberOp] = []
    order_index = 0

    def visibility_op_kind(kind: FragmentVisibilityKind) -> FiberOpKind:
        if kind == "sram_read":
            return "fragment_sram_read"
        if kind == "route_recv":
            return "fragment_route_recv"
        return "fragment_route_push"

    def next_op(
        op: FiberOpKind,
        *,
        inputs: tuple[FragmentRef, ...] = (),
        outputs: tuple[FragmentRef, ...] = (),
        depends_on: tuple[FiberDependency, ...] = (),
        attrs: dict[str, object] | None = None,
    ) -> FiberOp:
        nonlocal order_index
        fiber_op = FiberOp(
            id=f"{fiber_id}:{order_index:04d}:{op}",
            stream_id=stream_id,
            fiber_id=fiber_id,
            order_index=order_index,
            op=op,
            inputs=inputs,
            outputs=outputs,
            depends_on=depends_on,
            attrs=attrs or {},
        )
        order_index += 1
        ops.append(fiber_op)
        return fiber_op

    acc_initial = FragmentRef.make(
        "C_acc",
        m_tile=m_tile,
        n_tile=n_tile,
        reduction_fragment=-1,
    )
    prepare_profile = pattern_plan.step("accumulator_prepare")
    prepare = next_op(
        "accumulator_prepare",
        outputs=(acc_initial,),
        attrs=_attrs_from_step_profile(
            prepare_profile,
            placement="pre_loop",
            subtask_role="accumulator_prepare",
            reason="initialize accumulator once for the assigned output tile",
        ),
    )

    previous_acc = acc_initial
    previous_acc_op = prepare
    for reduction_fragment_index in range(k_steps):
        a_fragment = FragmentRef.make(
            "A",
            m_tile=m_tile,
            reduction_fragment=reduction_fragment_index,
        )
        b_fragment = FragmentRef.make(
            "B",
            reduction_fragment=reduction_fragment_index,
            n_tile=n_tile,
        )
        acc_next = FragmentRef.make(
            "C_acc",
            m_tile=m_tile,
            n_tile=n_tile,
            reduction_fragment=reduction_fragment_index,
        )
        materialize_a: FiberOp | None = None
        materialize_b: FiberOp | None = None
        for step_profile in pattern_plan.repeated_steps:
            if step_profile.step_id == "materialize_A":
                materialize_a = next_op(
                    visibility_op_kind(a_visibility_kind),
                    outputs=(a_fragment,),
                    attrs=_attrs_from_step_profile(
                        step_profile,
                        placement="loop_body",
                        subtask_role="k_stream",
                        operand="A",
                        visibility_kind=a_visibility_kind,
                        stream_visibility_action_id=a_visibility_action_id,
                        loop_axis="reduction_fragment",
                        reduction_fragment_index=reduction_fragment_index,
                        reason="make A fragment visible for this reduction update",
                    ),
                )
            elif step_profile.step_id == "materialize_B":
                materialize_b = next_op(
                    visibility_op_kind(b_visibility_kind),
                    outputs=(b_fragment,),
                    attrs=_attrs_from_step_profile(
                        step_profile,
                        placement="loop_body",
                        subtask_role="k_stream",
                        operand="B",
                        visibility_kind=b_visibility_kind,
                        stream_visibility_action_id=b_visibility_action_id,
                        loop_axis="reduction_fragment",
                        reduction_fragment_index=reduction_fragment_index,
                        reason="make B fragment visible for this reduction update",
                    ),
                )
            elif step_profile.step_id == "gemm_update":
                if materialize_a is None or materialize_b is None:
                    raise ValueError(
                        "sequential-K profile must materialize A and B before gemm_update"
                    )
                previous_acc_op = next_op(
                    "gemm_update",
                    inputs=(previous_acc, a_fragment, b_fragment),
                    outputs=(acc_next,),
                    depends_on=(
                        FiberDependency(
                            source_op_id=previous_acc_op.id,
                            kind=(
                                "phase_order"
                                if reduction_fragment_index == 0
                                else "carried_state"
                            ),
                            expected_satisfaction=(
                                "subtask_order"
                                if reduction_fragment_index == 0
                                else "loop_instance_order"
                            ),
                            via_fragment=previous_acc,
                            reason=(
                                "first update waits for accumulator prepare"
                                if reduction_fragment_index == 0
                                else (
                                    "GEMM accumulator is carried across "
                                    "reduction fragments"
                                )
                            ),
                        ),
                        FiberDependency(
                            source_op_id=materialize_a.id,
                            kind="fragment_visibility",
                            expected_satisfaction="route_or_local_materialization",
                            via_fragment=a_fragment,
                            reason=(
                                "A fragment must be locally visible before "
                                "this reduction update"
                            ),
                        ),
                        FiberDependency(
                            source_op_id=materialize_b.id,
                            kind="fragment_visibility",
                            expected_satisfaction="route_or_local_materialization",
                            via_fragment=b_fragment,
                            reason=(
                                "B fragment must be locally visible before "
                                "this reduction update"
                            ),
                        ),
                    ),
                    attrs=_attrs_from_step_profile(
                        step_profile,
                        placement="loop_body",
                        subtask_role="k_stream",
                        loop_axis="reduction_fragment",
                        reduction_fragment_index=reduction_fragment_index,
                        carried_state={
                            "input": previous_acc.label(),
                            "output": acc_next.label(),
                        },
                    ),
                )
            else:
                raise ValueError(f"unsupported sequential-K loop step: {step_profile.step_id}")
        previous_acc = acc_next

    c_fragment = FragmentRef.make("C", m_tile=m_tile, n_tile=n_tile)
    finalize_profile = pattern_plan.step("finalize_accumulator")
    finalize = next_op(
        "finalize_accumulator",
        inputs=(previous_acc,),
        outputs=(c_fragment,),
        depends_on=(
            FiberDependency(
                source_op_id=previous_acc_op.id,
                kind="phase_order",
                expected_satisfaction="subtask_order",
                via_fragment=previous_acc,
                reason="finalize waits for the last K-stream accumulator update",
            ),
        ),
        attrs=_attrs_from_step_profile(
            finalize_profile,
            placement="post_loop",
            subtask_role="finalize_store",
            reason="finalize accumulator after all k steps",
        ),
    )
    store_input = c_fragment
    store_dependency_source = finalize.id
    store_dependency_reason = "store consumes finalized C output"
    store_reason = "store-visible output after accumulator finalize"
    store_profile = pattern_plan.step("store_fragment")
    next_op(
        "store_fragment",
        inputs=(store_input,),
        depends_on=(
            FiberDependency(
                source_op_id=store_dependency_source,
                kind="store_order",
                expected_satisfaction="same_block_order",
                via_fragment=store_input,
                reason=store_dependency_reason,
            ),
        ),
        attrs=_attrs_from_step_profile(
            store_profile,
            placement="post_loop",
            subtask_role="finalize_store",
            reason=store_reason,
        ),
    )

    return Fiber(
        id=fiber_id,
        stream_id=stream_id,
        m_tile=m_tile,
        n_tile=n_tile,
        ops=tuple(ops),
        attrs={
            "strategy_id": "legacy_expanded_gemm_bridge",
            "bad_for_bline_semantics": True,
            "replacement": "build_atomic_gemm_fiber",
            "fiber_pattern_plan": pattern_plan.pattern_id.name,
            "fiber_pattern_step_order": pattern_plan.step_order,
            "micro_topology": "degenerate_sequential_k",
            "loop_axis": "reduction_fragment",
            "loop_count": k_steps,
            "downstream_tile_op_chain": (),
            "disabled_bad_code_paths": ("gemm_relu_inside_gemm_fiber",),
            "future_strategies": (
                "prefetch_a_side",
                "prefetch_b_side",
                "split_both_sides_with_stream_local_reduce",
            ),
        },
    )


_EXPECTED_SEQUENTIAL_K_STEPS = {
    "accumulator_prepare",
    "materialize_A",
    "materialize_B",
    "gemm_update",
    "finalize_accumulator",
    "store_fragment",
}


@dataclass(frozen=True)
class _SequentialReductionPatternPlan:
    pattern_id: object
    steps: dict[str, FiberPatternStep]
    pre_region_steps: tuple[FiberPatternStep, ...]
    repeated_steps: tuple[FiberPatternStep, ...]
    post_region_steps: tuple[FiberPatternStep, ...]

    @property
    def step_order(self) -> tuple[str, ...]:
        return tuple(
            step.step_id
            for step in (
                *self.pre_region_steps,
                *self.repeated_steps,
                *self.post_region_steps,
            )
        )

    def step(self, step_id: str) -> FiberPatternStep | None:
        return self.steps.get(step_id)


def _validate_sequential_reduction_pattern(
    pattern: FiberPatternPlan,
) -> _SequentialReductionPatternPlan:
    repeated_regions = pattern.repeated_regions
    if len(repeated_regions) != 1:
        raise ValueError("sequential reduction pattern must have one repeated region")
    steps = {
        step.step_id: step
        for step in (
            *pattern.pre_region,
            *repeated_regions[0].steps,
            *pattern.post_region,
        )
    }
    missing_steps = _EXPECTED_SEQUENTIAL_K_STEPS - set(steps)
    if missing_steps:
        raise ValueError(
            f"sequential reduction pattern missing steps: {sorted(missing_steps)}"
        )
    pre_region_steps = pattern.pre_region
    repeated_steps = repeated_regions[0].steps
    post_region_steps = pattern.post_region
    _require_step_order(
        "pre_region",
        pre_region_steps,
        ("accumulator_prepare",),
    )
    _require_step_order(
        "repeated_region",
        repeated_steps,
        ("materialize_A", "materialize_B", "gemm_update"),
    )
    _require_step_order(
        "post_region",
        post_region_steps,
        ("finalize_accumulator", "store_fragment"),
    )
    return _SequentialReductionPatternPlan(
        pattern_id=pattern.pattern_id,
        steps=steps,
        pre_region_steps=pre_region_steps,
        repeated_steps=repeated_steps,
        post_region_steps=post_region_steps,
    )


def _require_step_order(
    label: str,
    steps: tuple[FiberPatternStep, ...],
    expected: tuple[str, ...],
) -> None:
    actual = tuple(step.step_id for step in steps)
    if actual != expected:
        raise ValueError(
            f"sequential-K {label} step order must be {expected!r}, got {actual!r}"
        )


def _attrs_from_step_profile(
    step: FiberPatternStep | None,
    **overrides: object,
) -> dict[str, object]:
    attrs: dict[str, object] = {}
    if step is not None:
        attrs.update(
            {
                "placement": _placement_for_pattern_region(step.region),
                "profile_step_id": step.step_id,
                "profile_role": step.role,
            }
        )
        attrs.update({key: value for key, value in step.attrs})
    attrs.update(overrides)
    return attrs


def _placement_for_pattern_region(region: str) -> str:
    if region == "pre_region":
        return "pre_loop"
    if region == "repeated_region":
        return "loop_body"
    if region == "post_region":
        return "post_loop"
    return "unknown"


__all__ = [
    "Fiber",
    "FiberDependency",
    "FiberOp",
    "FragmentVisibilityKind",
    "FragmentRef",
    "build_atomic_gemm_fiber",
    "build_expanded_gemm_bridge_fiber",
]
