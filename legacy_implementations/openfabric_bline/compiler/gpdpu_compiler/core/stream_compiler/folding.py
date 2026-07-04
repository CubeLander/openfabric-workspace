"""Stream-scoped loop folding analysis for B-line schedules.

This module is intentionally report-only.  It does not fold component rows,
mutate subtasks, delete expanded K bodies, or emit bytes.

The analysis answers the next architectural question:

    Does each stream's flat fiber schedule contain a repeated subtask loop body
    that can later be projected to a vendor ``instances_amount`` representation?

The source of truth is still the fiber execution model, but the folding scale is
the stream / PE-local subtask program.  A vendor subtask loop is one runtime
container whose embedded exeBlock graph may contain different PE-local programs
for different streams.  Vendor fields such as ``instances_amount`` are
downstream projections of this proof, not the proof itself.
"""

from __future__ import annotations

from dataclasses import dataclass

from .schedule import (
    FiberExecutionSchedule,
    FiberScheduleStep,
    ValidatedFiberExecutionSchedule,
    verify_fiber_execution_schedule,
)


@dataclass(frozen=True)
class FoldDependencyEdge:
    """Canonical dependency edge inside one repeated body instance."""

    source_step_index: int
    target_step_index: int
    dependency_kind: str

    def to_plan(self) -> dict[str, object]:
        return {
            "source_step_index": self.source_step_index,
            "target_step_index": self.target_step_index,
            "dependency_kind": self.dependency_kind,
        }


@dataclass(frozen=True)
class FoldBodySignature:
    """Normalized repeated-body proof signature.

    This intentionally excludes operator-specific role strings and source ids.
    Roles remain in `loop_body_shape` as diagnostics/reporting, but fold
    uniformity is decided from typed schedule semantics and canonical topology.
    """

    step_semantics: tuple[tuple[str, str], ...]
    dependency_topology: tuple[FoldDependencyEdge, ...]
    order_model: str = "source_order"

    def to_plan(self) -> dict[str, object]:
        return {
            "step_semantics": [
                {
                    "semantic_kind": semantic_kind,
                    "candidate_mechanism": candidate_mechanism,
                }
                for semantic_kind, candidate_mechanism in self.step_semantics
            ],
            "dependency_topology": [
                edge.to_plan() for edge in self.dependency_topology
            ],
            "order_model": self.order_model,
        }


@dataclass(frozen=True)
class StreamLoopFoldCandidate:
    """Report-only candidate for folding one stream's subtask loop body."""

    id: str
    fold_scope: str
    source_fiber_ids: tuple[str, ...]
    stream_id: str
    loop_axis: str
    loop_instance_keys: tuple[str, ...]
    derived_region_axis: str
    derived_instance_keys: tuple[str, ...]
    source_to_derived_instance_keys: tuple[tuple[str, str], ...]
    pre_loop_roles: tuple[str, ...]
    fold_body_signature: FoldBodySignature
    loop_body_shape: tuple[tuple[str, str, str], ...]
    post_loop_roles: tuple[str, ...]
    repeated_action_count: int
    materialization_action_count: int
    carried_dependency_count: int
    loop_body_proof_statuses: tuple[str, ...]
    requires_instance_base_rows: bool
    instance_base_mapping_status: str
    foldable: bool
    rejection_reasons: tuple[str, ...]
    policy: str

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "fold_scope": self.fold_scope,
            "source_fiber_ids": list(self.source_fiber_ids),
            "stream_id": self.stream_id,
            "loop_axis": self.loop_axis,
            "loop_instance_keys": list(self.loop_instance_keys),
            "derived_region_axis": self.derived_region_axis,
            "derived_instance_keys": list(self.derived_instance_keys),
            "source_to_derived_instance_keys": [
                {"source": source, "derived": derived}
                for source, derived in self.source_to_derived_instance_keys
            ],
            "pre_loop_roles": list(self.pre_loop_roles),
            "fold_body_signature": self.fold_body_signature.to_plan(),
            "loop_body_shape": [
                {
                    "role": role,
                    "semantic_kind": semantic_kind,
                    "candidate_mechanism": candidate_mechanism,
                }
                for role, semantic_kind, candidate_mechanism in self.loop_body_shape
            ],
            "post_loop_roles": list(self.post_loop_roles),
            "repeated_action_count": self.repeated_action_count,
            "materialization_action_count": self.materialization_action_count,
            "carried_dependency_count": self.carried_dependency_count,
            "loop_body_proof_statuses": list(self.loop_body_proof_statuses),
            "requires_instance_base_rows": self.requires_instance_base_rows,
            "instance_base_mapping_status": self.instance_base_mapping_status,
            "foldable": self.foldable,
            "rejection_reasons": list(self.rejection_reasons),
            "policy": self.policy,
        }


@dataclass(frozen=True)
class StreamLoopFoldReport:
    """Report-only collection of fiber loop fold candidates."""

    candidates: tuple[StreamLoopFoldCandidate, ...]
    diagnostics: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "ir": "experimental_stream_loop_fold_report",
            "candidates": [candidate.to_plan() for candidate in self.candidates],
            "diagnostics": list(self.diagnostics),
            "layering_policy": (
                "stream_loop_fold_report_consumes_fiber_execution_schedule;"
                "does_not_mutate_vendor_component_rows_or_emit_binary_bytes"
            ),
        }


@dataclass(frozen=True)
class _DerivedRepeatedRegion:
    pre_steps: tuple[FiberScheduleStep, ...]
    loop_steps_by_instance: tuple[tuple[FiberScheduleStep, ...], ...]
    post_steps: tuple[FiberScheduleStep, ...]
    body_signature: FoldBodySignature


def analyze_stream_loop_folding(
    schedule: FiberExecutionSchedule,
) -> StreamLoopFoldReport:
    """Build a report-only fold analysis from a flat execution schedule."""

    validated: ValidatedFiberExecutionSchedule = verify_fiber_execution_schedule(schedule)
    diagnostics = list(validated.diagnostics)
    diagnostics.extend(validated.verifier_diagnostics)
    if "resource_verified" not in validated.validation_statuses:
        diagnostics.append("folding_requires_resource_verified_schedule")
        return StreamLoopFoldReport(candidates=(), diagnostics=tuple(diagnostics))

    steps_by_stream: dict[str, list[FiberScheduleStep]] = {}
    for step in validated.steps:
        steps_by_stream.setdefault(step.stream_id, []).append(step)

    candidates = [
        _candidate_for_stream(stream_id, steps)
        for stream_id, steps in sorted(steps_by_stream.items())
    ]
    return StreamLoopFoldReport(
        candidates=tuple(candidates),
        diagnostics=tuple(diagnostics),
    )


def summarize_stream_loop_fold_report(
    report: StreamLoopFoldReport,
) -> dict[str, object]:
    """Return stable fold-analysis counts for focused checks."""

    fold_candidate_count = 0
    fold_candidate_loop_instance_total = 0
    fold_candidate_repeated_action_total = 0
    fold_candidate_materialization_action_total = 0
    fold_candidate_carried_dependency_total = 0
    fold_candidate_instance_base_mapping_unresolved_count = 0
    fold_candidate_rejected_count = 0
    rejection_reasons: dict[str, int] = {}
    loop_body_shapes: dict[str, int] = {}

    for candidate in report.candidates:
        shape_key = "|".join(
            f"{role}:{semantic}:{mechanism}"
            for role, semantic, mechanism in candidate.loop_body_shape
        )
        loop_body_shapes[shape_key] = loop_body_shapes.get(shape_key, 0) + 1
        if candidate.foldable:
            fold_candidate_count += 1
            fold_candidate_loop_instance_total += len(candidate.loop_instance_keys)
            fold_candidate_repeated_action_total += candidate.repeated_action_count
            fold_candidate_materialization_action_total += (
                candidate.materialization_action_count
            )
            fold_candidate_carried_dependency_total += (
                candidate.carried_dependency_count
            )
            if candidate.instance_base_mapping_status == "unresolved_pending_phase4":
                fold_candidate_instance_base_mapping_unresolved_count += 1
        else:
            fold_candidate_rejected_count += 1
        for reason in candidate.rejection_reasons:
            rejection_reasons[reason] = rejection_reasons.get(reason, 0) + 1

    return {
        "candidate_record_count": len(report.candidates),
        "fold_candidate_count": fold_candidate_count,
        "fold_candidate_loop_instance_total": fold_candidate_loop_instance_total,
        "fold_candidate_repeated_action_total": fold_candidate_repeated_action_total,
        "fold_candidate_materialization_action_total": (
            fold_candidate_materialization_action_total
        ),
        "fold_candidate_carried_dependency_total": (
            fold_candidate_carried_dependency_total
        ),
        "fold_candidate_instance_base_mapping_unresolved_count": (
            fold_candidate_instance_base_mapping_unresolved_count
        ),
        "fold_candidate_rejected_count": fold_candidate_rejected_count,
        "fold_candidate_rejection_reasons": dict(sorted(rejection_reasons.items())),
        "loop_body_shape_counts": dict(sorted(loop_body_shapes.items())),
        "diagnostic_count": len(report.diagnostics),
    }


def _candidate_for_stream(
    stream_id: str,
    steps: list[FiberScheduleStep],
) -> StreamLoopFoldCandidate:
    ordered = sorted(
        steps,
        key=lambda step: (step.source_fiber_id, step.source_order_index, step.id),
    )
    source_fiber_ids = tuple(sorted({step.source_fiber_id for step in ordered}))
    derived_region = _derive_repeated_region_from_ordered_steps(ordered)
    pre_loop_steps = list(derived_region.pre_steps) if derived_region is not None else []
    post_loop_steps = list(derived_region.post_steps) if derived_region is not None else []
    loop_steps = [
        step
        for instance_steps in (
            derived_region.loop_steps_by_instance if derived_region is not None else ()
        )
        for step in instance_steps
    ]
    loop_axes = sorted({step.loop_axis for step in loop_steps if step.loop_axis})
    loop_axis = loop_axes[0] if loop_axes else "unknown"
    derived_instance_keys = tuple(
        f"region{index}"
        for index, _instance_steps in enumerate(
            derived_region.loop_steps_by_instance if derived_region is not None else ()
        )
    )
    loop_steps_by_instance = {
        derived_key: list(instance_steps)
        for derived_key, instance_steps in zip(
            derived_instance_keys,
            derived_region.loop_steps_by_instance if derived_region is not None else (),
            strict=True,
        )
    }
    loop_instance_keys = tuple(
        _source_instance_key_for_group(index, instance_steps)
        for index, instance_steps in enumerate(
            derived_region.loop_steps_by_instance if derived_region is not None else ()
        )
    )
    derived_instance_keys = tuple(
        f"region{index}" for index, _key in enumerate(loop_instance_keys)
    )
    source_to_derived_instance_keys = tuple(
        zip(loop_instance_keys, derived_instance_keys, strict=True)
    )
    instance_signatures = [
        _fold_body_signature(loop_steps_by_instance[key])
        for key in derived_instance_keys
    ]
    canonical_signature = (
        instance_signatures[0] if instance_signatures else _empty_fold_body_signature()
    )
    diagnostic_shapes = [
        _loop_instance_shape(loop_steps_by_instance[key])
        for key in derived_instance_keys
    ]
    canonical_shape = diagnostic_shapes[0] if diagnostic_shapes else ()
    rejection_reasons: list[str] = []
    if derived_region is None or not loop_steps:
        rejection_reasons.append("no_loop_body")
    if len(loop_instance_keys) <= 1:
        rejection_reasons.append("single_loop_instance")
    if any(signature != canonical_signature for signature in instance_signatures):
        rejection_reasons.append("non_uniform_loop_body_shape")
    if any(step.phase == "loop_body" for step in (*pre_loop_steps, *post_loop_steps)):
        rejection_reasons.append("non_uniform_loop_body_shape")
    if any(step.proof_status != "proven" for step in loop_steps):
        rejection_reasons.append("unproven_loop_body_role")
    carried_dependency_count, carry_rejection_reasons = _prove_carry_chains(
        pre_loop_steps=pre_loop_steps,
        loop_steps_by_instance=loop_steps_by_instance,
        loop_instance_keys=derived_instance_keys,
        post_loop_steps=post_loop_steps,
    )
    rejection_reasons.extend(carry_rejection_reasons)
    foldable = not rejection_reasons
    materialization_action_count = sum(
        1
        for step in loop_steps
        if _is_materialization_step(step)
    )
    loop_body_proof_statuses = tuple(
        sorted({step.proof_status for step in loop_steps})
    )
    requires_instance_base_rows = materialization_action_count > 0
    return StreamLoopFoldCandidate(
        id=f"stream_fold_candidate:{stream_id}:{loop_axis}",
        fold_scope="stream_subtask_loop",
        source_fiber_ids=source_fiber_ids,
        stream_id=stream_id,
        loop_axis=loop_axis,
        loop_instance_keys=loop_instance_keys,
        derived_region_axis="derived_region",
        derived_instance_keys=derived_instance_keys,
        source_to_derived_instance_keys=source_to_derived_instance_keys,
        pre_loop_roles=tuple(step.role for step in pre_loop_steps),
        fold_body_signature=canonical_signature,
        loop_body_shape=canonical_shape,
        post_loop_roles=tuple(step.role for step in post_loop_steps),
        repeated_action_count=len(loop_steps),
        materialization_action_count=materialization_action_count,
        carried_dependency_count=carried_dependency_count,
        loop_body_proof_statuses=loop_body_proof_statuses,
        requires_instance_base_rows=requires_instance_base_rows,
        instance_base_mapping_status=(
            "unresolved_pending_phase4"
            if requires_instance_base_rows
            else "not_required"
        ),
        foldable=foldable,
        rejection_reasons=tuple(rejection_reasons),
        policy=(
            "report_only_stream_subtask_loop_analysis;"
            "expanded_component_rows_remain_authoritative"
        ),
    )


def _derive_repeated_region_from_ordered_steps(
    ordered: list[FiberScheduleStep],
) -> _DerivedRepeatedRegion | None:
    """Derive repeated region instances from ordered typed schedule facts.

    This is deliberately independent of operator names, graph kinds, axis names,
    and source loop-instance labels.  The source labels remain useful for
    downstream projection, but the fold proof first finds repeated typed shape
    in the stream-local schedule itself.
    """

    if len(ordered) < 2:
        return None

    best: tuple[int, int, int, int] | None = None
    best_groups: tuple[tuple[FiberScheduleStep, ...], ...] = ()
    for start in range(len(ordered)):
        max_body_len = (len(ordered) - start) // 2
        for body_len in range(1, max_body_len + 1):
            body_signature = _fold_body_signature(ordered[start:start + body_len])
            if not body_signature.step_semantics:
                continue
            repetitions = 1
            while True:
                next_start = start + repetitions * body_len
                next_end = next_start + body_len
                if next_end > len(ordered):
                    break
                if _fold_body_signature(ordered[next_start:next_end]) != body_signature:
                    break
                repetitions += 1
            if repetitions < 2:
                continue
            repeated_action_count = repetitions * body_len
            score = (
                repeated_action_count,
                repetitions,
                -start,
                -body_len,
            )
            if best is not None and score <= best:
                continue
            best = score
            best_groups = tuple(
                tuple(ordered[start + index * body_len:start + (index + 1) * body_len])
                for index in range(repetitions)
            )
    if best is None:
        return None

    _repeated_action_count, _repetitions, negative_start, negative_body_len = best
    start = -negative_start
    body_len = -negative_body_len
    repeated_end = start + len(best_groups) * body_len
    return _DerivedRepeatedRegion(
        pre_steps=tuple(ordered[:start]),
        loop_steps_by_instance=best_groups,
        post_steps=tuple(ordered[repeated_end:]),
        body_signature=_fold_body_signature(best_groups[0]),
    )


def _fold_body_signature(
    steps: list[FiberScheduleStep] | tuple[FiberScheduleStep, ...],
) -> FoldBodySignature:
    ordered = tuple(sorted(steps, key=lambda step: step.source_order_index))
    local_index_by_source_id = {
        step.source_fiber_op_id: index
        for index, step in enumerate(ordered)
    }
    dependency_edges: list[FoldDependencyEdge] = []
    for target_index, step in enumerate(ordered):
        for dependency_id in step.dependency_source_ids:
            source_index = local_index_by_source_id.get(dependency_id)
            if source_index is None:
                continue
            dependency_edges.append(
                FoldDependencyEdge(
                    source_step_index=source_index,
                    target_step_index=target_index,
                    dependency_kind="instance_local",
                )
            )
    return FoldBodySignature(
        step_semantics=tuple(
            (step.semantic_kind, step.candidate_mechanism)
            for step in ordered
        ),
        dependency_topology=tuple(
            sorted(
                dependency_edges,
                key=lambda edge: (
                    edge.source_step_index,
                    edge.target_step_index,
                    edge.dependency_kind,
                ),
            )
        ),
    )


def _empty_fold_body_signature() -> FoldBodySignature:
    return FoldBodySignature(step_semantics=(), dependency_topology=())


def _source_instance_key_for_group(
    index: int,
    instance_steps: tuple[FiberScheduleStep, ...],
) -> str:
    labels = {
        step.loop_instance_key
        for step in instance_steps
        if step.loop_instance_key is not None
    }
    if len(labels) == 1:
        return next(iter(labels))
    return f"source_region{index}"


def _loop_instance_shape(
    steps: list[FiberScheduleStep],
) -> tuple[tuple[str, str, str], ...]:
    return tuple(
        (
            step.role,
            step.semantic_kind,
            step.candidate_mechanism,
        )
        for step in sorted(steps, key=lambda step: step.source_order_index)
    )


def _is_materialization_step(step: FiberScheduleStep) -> bool:
    return step.semantic_kind in {
        "operand_materialization",
        "operand_route_visibility",
    }


def _prove_carry_chains(
    *,
    pre_loop_steps: list[FiberScheduleStep],
    loop_steps_by_instance: dict[str, list[FiberScheduleStep]],
    loop_instance_keys: tuple[str, ...],
    post_loop_steps: list[FiberScheduleStep],
) -> tuple[int, tuple[str, ...]]:
    """Prove adjacent loop-instance carry topology from dependency edges.

    This is intentionally topology-based.  It does not look for MatMul role
    names or axis names.  A carry chain exists when a loop-body step in one
    region instance depends on a loop-body step in the immediately previous
    region instance.
    """

    if len(loop_instance_keys) <= 1:
        return (0, ())

    loop_steps = [
        step
        for key in loop_instance_keys
        for step in loop_steps_by_instance.get(key, ())
    ]
    loop_source_to_instance = {
        step.source_fiber_op_id: key
        for key in loop_instance_keys
        for step in loop_steps_by_instance.get(key, ())
    }
    has_cross_instance_dependency = any(
        dependency_id in loop_source_to_instance
        and loop_source_to_instance[dependency_id]
        != loop_source_to_instance[step.source_fiber_op_id]
        for step in loop_steps
        for dependency_id in step.dependency_source_ids
    )
    if not has_cross_instance_dependency:
        return (0, ())

    rejection_reasons: list[str] = []
    pre_loop_source_ids = {step.source_fiber_op_id for step in pre_loop_steps}
    first_instance_steps = loop_steps_by_instance.get(loop_instance_keys[0], ())
    first_has_init_edge = any(
        dependency_id in pre_loop_source_ids
        for step in first_instance_steps
        for dependency_id in step.dependency_source_ids
    )
    if not first_has_init_edge:
        rejection_reasons.append("missing_carry_identity_edge")

    carried_dependency_count = 0
    previous_key_by_key = {
        key: loop_instance_keys[index - 1]
        for index, key in enumerate(loop_instance_keys)
        if index > 0
    }
    loop_key_order = {key: index for index, key in enumerate(loop_instance_keys)}
    for current_key in loop_instance_keys[1:]:
        previous_key = previous_key_by_key[current_key]
        adjacent_edges_for_instance = 0
        for step in loop_steps_by_instance.get(current_key, ()):
            previous_loop_dependencies_for_step = 0
            for dependency_id in step.dependency_source_ids:
                dependency_instance = loop_source_to_instance.get(dependency_id)
                if dependency_instance is None:
                    continue
                if dependency_instance == current_key:
                    continue
                if dependency_instance == previous_key:
                    adjacent_edges_for_instance += 1
                    previous_loop_dependencies_for_step += 1
                    continue
                if loop_key_order[dependency_instance] < loop_key_order[current_key]:
                    rejection_reasons.append("skipped_carry_edge")
                else:
                    rejection_reasons.append("forward_carry_edge")
            if previous_loop_dependencies_for_step > 1:
                rejection_reasons.append("duplicate_carry_producer")
        if adjacent_edges_for_instance == 0:
            rejection_reasons.append("missing_adjacent_carry_edge")
        carried_dependency_count += adjacent_edges_for_instance

    last_instance_source_ids = {
        step.source_fiber_op_id
        for step in loop_steps_by_instance.get(loop_instance_keys[-1], ())
    }
    final_has_exit_edge = any(
        dependency_id in last_instance_source_ids
        for step in post_loop_steps
        for dependency_id in step.dependency_source_ids
    )
    if not final_has_exit_edge:
        rejection_reasons.append("missing_carry_final_output_edge")

    return (carried_dependency_count, tuple(sorted(set(rejection_reasons))))


__all__ = [
    "FoldBodySignature",
    "FoldDependencyEdge",
    "StreamLoopFoldCandidate",
    "StreamLoopFoldReport",
    "analyze_stream_loop_folding",
    "summarize_stream_loop_fold_report",
]
