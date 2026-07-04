"""Flat execution schedule rows for B-line fiber executable ops.

This layer is still symbolic.  It does not emit DFU3500 instructions, ASM,
template rows, ABI rows, or binary blobs.

The schedule is deliberately a row view over `ExecutableFiberOp`:

    one ExecutableFiberOp -> one FiberScheduleStep

Dependencies remain references to source FiberOp ids.  The builder records raw
facts and diagnostics; schedule validity is owned by the verifier below, not by
builder self-certification.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .dfu3500_semantics import Dfu3500RoleSemanticReport
from .executable import ExecutableFiberOp, FiberExecutableProgram

SchedulePhase = Literal[
    "tile_body",
    "tile_store",
    "pre_loop",
    "loop_body",
    "post_loop",
    "unknown",
]
ScheduleValidationStatus = Literal[
    "constructed",
    "binding_verified",
    "resource_verified",
]


@dataclass(frozen=True)
class FiberScheduleStep:
    """Stable schedule row derived from one ExecutableFiberOp."""

    id: str
    executable_op_id: str
    source_fiber_id: str
    source_fiber_op_id: str
    source_order_index: int
    stream_id: str
    role: str
    phase: SchedulePhase
    loop_axis: str | None = None
    loop_instance_key: str | None = None
    dependency_source_ids: tuple[str, ...] = ()
    proof_status: str = "unknown"
    semantic_kind: str = "unknown"
    candidate_mechanism: str = "unknown"
    attrs: dict[str, object] = field(default_factory=dict)

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "executable_op_id": self.executable_op_id,
            "source_fiber_id": self.source_fiber_id,
            "source_fiber_op_id": self.source_fiber_op_id,
            "source_order_index": self.source_order_index,
            "stream_id": self.stream_id,
            "role": self.role,
            "phase": self.phase,
            "loop_axis": self.loop_axis,
            "loop_instance_key": self.loop_instance_key,
            "dependency_source_ids": list(self.dependency_source_ids),
            "proof_status": self.proof_status,
            "semantic_kind": self.semantic_kind,
            "candidate_mechanism": self.candidate_mechanism,
            "attrs": dict(self.attrs),
        }


@dataclass(frozen=True)
class FiberExecutionSchedule:
    """Flat symbolic execution schedule for a FiberExecutableProgram."""

    steps: tuple[FiberScheduleStep, ...]
    diagnostics: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "ir": "experimental_fiber_execution_schedule",
            "steps": [step.to_plan() for step in self.steps],
            "diagnostics": list(self.diagnostics),
            "layering_policy": (
                "fiber_execution_schedule_consumes_executable_ops_and_semantic_report;"
                "does_not_emit_dfu3500_instructions_or_binary_rows"
            ),
        }


@dataclass(frozen=True)
class RawFiberExecutionSchedule(FiberExecutionSchedule):
    """Unverified schedule facts emitted by the schedule builder."""


@dataclass(frozen=True)
class ValidatedFiberExecutionSchedule(FiberExecutionSchedule):
    """Schedule facts accepted by the schedule verifier."""

    validation_statuses: tuple[ScheduleValidationStatus, ...] = ()
    verifier_diagnostics: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        plan = super().to_plan()
        plan["ir"] = "validated_experimental_fiber_execution_schedule"
        plan["validation_statuses"] = list(self.validation_statuses)
        plan["verifier_diagnostics"] = list(self.verifier_diagnostics)
        plan["layering_policy"] = (
            "validated_fiber_execution_schedule_consumes_raw_schedule_facts;"
            "validation_statuses_are_verifier_owned;"
            "folding_consumes_validated_schedule_facts"
        )
        return plan


def build_fiber_execution_schedule(
    program: FiberExecutableProgram,
    semantic_report: Dfu3500RoleSemanticReport | None = None,
) -> RawFiberExecutionSchedule:
    """Build a flat schedule row view from executable ops.

    The optional semantic report annotates target proof status.  Missing
    semantic rows are diagnostics, not implicit proof failures.
    """

    semantics_by_executable_id = {}
    diagnostics = list(program.diagnostics)
    if semantic_report is not None:
        for record in semantic_report.records:
            previous = semantics_by_executable_id.setdefault(record.source_executable_op_id, record)
            if previous is not record:
                diagnostics.append(
                    "duplicate semantic record for executable op: "
                    f"{record.source_executable_op_id}"
                )
        diagnostics.extend(semantic_report.diagnostics)

    source_op_ids = {op.source_fiber_op_id for op in program.executable_ops}
    steps: list[FiberScheduleStep] = []
    seen_step_ids: set[str] = set()

    for op in sorted(program.executable_ops, key=_schedule_sort_key):
        semantic = semantics_by_executable_id.get(op.id)
        if semantic_report is not None and semantic is None:
            diagnostics.append(f"missing semantic record for executable op: {op.id}")
        for dependency_id in op.dependency_source_ids:
            if dependency_id not in source_op_ids:
                diagnostics.append(
                    f"unresolved dependency source for {op.id}: {dependency_id}"
                )
        step = FiberScheduleStep(
            id=f"schedule:{op.id}",
            executable_op_id=op.id,
            source_fiber_id=op.source_fiber_id,
            source_fiber_op_id=op.source_fiber_op_id,
            source_order_index=op.source_order_index,
            stream_id=op.stream_id,
            role=op.role,
            phase=_phase_for_executable_op(op),
            loop_axis=op.loop_axis,
            loop_instance_key=op.loop_instance_key,
            dependency_source_ids=op.dependency_source_ids,
            proof_status="unknown" if semantic is None else semantic.proof_status,
            semantic_kind="unknown" if semantic is None else semantic.semantic_kind,
            candidate_mechanism=(
                "unknown" if semantic is None else semantic.candidate_mechanism
            ),
            attrs={
                "source_ir": "FiberExecutableProgram",
                "symbolic_status": op.attrs.get("symbolic_status"),
                "subtask_role": op.attrs.get("subtask_role"),
            },
        )
        if step.id in seen_step_ids:
            diagnostics.append(f"duplicate schedule step id: {step.id}")
        seen_step_ids.add(step.id)
        steps.append(step)

    return RawFiberExecutionSchedule(steps=tuple(steps), diagnostics=tuple(diagnostics))


def verify_fiber_execution_schedule(
    schedule: FiberExecutionSchedule,
) -> ValidatedFiberExecutionSchedule:
    """Validate raw schedule facts before folding consumes them."""

    verifier_diagnostics: list[str] = []
    step_ids: set[str] = set()
    source_op_ids: set[str] = set()
    executable_op_ids: set[str] = set()
    for step in schedule.steps:
        if step.id in step_ids:
            verifier_diagnostics.append(f"duplicate schedule step id: {step.id}")
        step_ids.add(step.id)
        if step.source_fiber_op_id in source_op_ids:
            verifier_diagnostics.append(
                f"duplicate source fiber op id: {step.source_fiber_op_id}"
            )
        source_op_ids.add(step.source_fiber_op_id)
        if step.executable_op_id in executable_op_ids:
            verifier_diagnostics.append(f"duplicate executable op id: {step.executable_op_id}")
        executable_op_ids.add(step.executable_op_id)
        if step.phase == "unknown":
            verifier_diagnostics.append(f"unknown schedule phase for step: {step.id}")
        if step.phase == "loop_body":
            if step.loop_instance_key is None:
                verifier_diagnostics.append(
                    f"loop body step lacks region instance key: {step.id}"
                )
        elif step.loop_instance_key is not None:
            verifier_diagnostics.append(
                f"non-loop step has region instance key {step.loop_instance_key}: {step.id}"
            )

    for step in schedule.steps:
        for dependency_id in step.dependency_source_ids:
            if dependency_id not in source_op_ids:
                verifier_diagnostics.append(
                    f"unresolved dependency source for {step.id}: {dependency_id}"
                )

    statuses: tuple[ScheduleValidationStatus, ...]
    if schedule.diagnostics or verifier_diagnostics:
        statuses = ("constructed",)
    else:
        statuses = ("constructed", "binding_verified", "resource_verified")
    return ValidatedFiberExecutionSchedule(
        steps=schedule.steps,
        diagnostics=tuple(schedule.diagnostics),
        validation_statuses=statuses,
        verifier_diagnostics=tuple(verifier_diagnostics),
    )


def ensure_validated_fiber_execution_schedule(
    schedule: FiberExecutionSchedule,
) -> ValidatedFiberExecutionSchedule:
    if isinstance(schedule, ValidatedFiberExecutionSchedule):
        return schedule
    return verify_fiber_execution_schedule(schedule)


def summarize_fiber_execution_schedule(
    schedule: FiberExecutionSchedule,
) -> dict[str, object]:
    """Return stable counts for focused checks and demo output."""

    phase_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    proof_status_counts: dict[str, int] = {}
    semantic_kind_counts: dict[str, int] = {}
    loop_instance_counts: dict[str, int] = {}
    steps_per_fiber: dict[str, int] = {}
    dependency_count = 0
    unproven_role_counts: dict[str, int] = {}
    forbidden_tile_micro_block_fields = 0

    for step in schedule.steps:
        phase_counts[step.phase] = phase_counts.get(step.phase, 0) + 1
        role_counts[step.role] = role_counts.get(step.role, 0) + 1
        proof_status_counts[step.proof_status] = (
            proof_status_counts.get(step.proof_status, 0) + 1
        )
        semantic_kind_counts[step.semantic_kind] = (
            semantic_kind_counts.get(step.semantic_kind, 0) + 1
        )
        steps_per_fiber[step.source_fiber_id] = (
            steps_per_fiber.get(step.source_fiber_id, 0) + 1
        )
        dependency_count += len(step.dependency_source_ids)
        if step.loop_instance_key is not None:
            loop_instance_counts[step.loop_instance_key] = (
                loop_instance_counts.get(step.loop_instance_key, 0) + 1
            )
        if step.proof_status != "proven":
            unproven_role_counts[step.role] = unproven_role_counts.get(step.role, 0) + 1
        for key in step.attrs:
            if key.startswith("source_tile_micro_block") or key == "tile_micro_block_kind":
                forbidden_tile_micro_block_fields += 1

    return {
        "step_count": len(schedule.steps),
        "fiber_count": len(steps_per_fiber),
        "steps_per_fiber": sorted(set(steps_per_fiber.values())),
        "dependency_ref_count": dependency_count,
        "phase_counts": dict(sorted(phase_counts.items())),
        "role_counts": dict(sorted(role_counts.items())),
        "proof_status_counts": dict(sorted(proof_status_counts.items())),
        "semantic_kind_counts": dict(sorted(semantic_kind_counts.items())),
        "loop_instance_counts": dict(sorted(loop_instance_counts.items())),
        "unproven_role_counts": dict(sorted(unproven_role_counts.items())),
        "diagnostic_count": len(schedule.diagnostics),
        "forbidden_tile_micro_block_field_count": forbidden_tile_micro_block_fields,
    }


def _schedule_sort_key(op: ExecutableFiberOp) -> tuple[str, int, str]:
    return (op.source_fiber_id, op.source_order_index, op.id)


def _phase_for_executable_op(op: ExecutableFiberOp) -> SchedulePhase:
    placement = str(op.placement)
    if placement in {"tile_body", "tile_store", "pre_loop", "loop_body", "post_loop"}:
        return placement  # type: ignore[return-value]
    return "unknown"


__all__ = [
    "FiberExecutionSchedule",
    "FiberScheduleStep",
    "RawFiberExecutionSchedule",
    "ScheduleValidationStatus",
    "ValidatedFiberExecutionSchedule",
    "build_fiber_execution_schedule",
    "ensure_validated_fiber_execution_schedule",
    "summarize_fiber_execution_schedule",
    "verify_fiber_execution_schedule",
]
