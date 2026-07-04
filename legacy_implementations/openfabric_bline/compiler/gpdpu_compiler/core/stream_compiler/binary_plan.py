"""Report-only BinaryLayoutPlan for B-line TemplateOps.

This layer places TemplateOps into symbolic binary layout rows.  It does not
emit bytes, does not bind missing templates, and does not consume old
TileMicroBlock compatibility fields.

Current authority split:

    TemplateOpPlan   = target-template content authority
    BinaryLayoutPlan = placement / numbering report

Only concrete instruction intents receive symbolic PC / row slots.
Zero-instruction boundaries remain first-class rows but do not consume PC.
Unresolved candidate intents remain visible and unallocated.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .template_ops import Diagnostic, JsonValue, TemplateOp, TemplateOpPlan

ValidationStatus = Literal["valid", "invalid"]


@dataclass(frozen=True)
class BinaryInstructionPlan:
    """Symbolic instruction-row placement for one concrete TemplateOp intent."""

    id: str
    row_index: int
    pc: int
    template_op_id: str
    source_schedule_step_id: str
    primary_fiber_op_id: str
    role: str
    opcode: str
    phase: str
    loop_instance: str | None
    task_id: int | None
    stream_id: str | None
    subtask_slot: str
    attrs: tuple[tuple[str, JsonValue], ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "row_index": self.row_index,
            "pc": self.pc,
            "template_op_id": self.template_op_id,
            "source_schedule_step_id": self.source_schedule_step_id,
            "primary_fiber_op_id": self.primary_fiber_op_id,
            "role": self.role,
            "opcode": self.opcode,
            "phase": self.phase,
            "loop_instance": self.loop_instance,
            "task_id": self.task_id,
            "stream_id": self.stream_id,
            "subtask_slot": self.subtask_slot,
            "occupies_instruction_row": True,
            "attrs": _attrs_to_plan(self.attrs),
        }


@dataclass(frozen=True)
class BinaryZeroInstructionBoundary:
    """Semantic boundary that deliberately consumes no PC / instruction row."""

    id: str
    template_op_id: str
    source_schedule_step_id: str
    primary_fiber_op_id: str
    role: str
    phase: str
    loop_instance: str | None
    task_id: int | None
    stream_id: str | None
    subtask_slot: str
    boundary_kind: str
    attrs: tuple[tuple[str, JsonValue], ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "template_op_id": self.template_op_id,
            "source_schedule_step_id": self.source_schedule_step_id,
            "primary_fiber_op_id": self.primary_fiber_op_id,
            "role": self.role,
            "phase": self.phase,
            "loop_instance": self.loop_instance,
            "task_id": self.task_id,
            "stream_id": self.stream_id,
            "subtask_slot": self.subtask_slot,
            "boundary_kind": self.boundary_kind,
            "occupies_instruction_row": False,
            "pc": None,
            "attrs": _attrs_to_plan(self.attrs),
        }


@dataclass(frozen=True)
class BinaryTaskPlan:
    """Per-task symbolic placement summary."""

    task_id: int
    instruction_row_count: int
    zero_instruction_boundary_count: int
    unresolved_template_op_count: int

    def to_plan(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "instruction_row_count": self.instruction_row_count,
            "zero_instruction_boundary_count": self.zero_instruction_boundary_count,
            "unresolved_template_op_count": self.unresolved_template_op_count,
        }


@dataclass(frozen=True)
class BinarySubtaskPlan:
    """Symbolic subtask-slot placement summary."""

    subtask_slot: str
    instruction_row_count: int
    zero_instruction_boundary_count: int
    unresolved_template_op_count: int

    def to_plan(self) -> dict[str, object]:
        return {
            "subtask_slot": self.subtask_slot,
            "instruction_row_count": self.instruction_row_count,
            "zero_instruction_boundary_count": self.zero_instruction_boundary_count,
            "unresolved_template_op_count": self.unresolved_template_op_count,
        }


@dataclass(frozen=True)
class BinaryInstancePlan:
    """Symbolic loop-instance placement summary."""

    loop_instance: str
    instruction_row_count: int

    def to_plan(self) -> dict[str, object]:
        return {
            "loop_instance": self.loop_instance,
            "instruction_row_count": self.instruction_row_count,
        }


@dataclass(frozen=True)
class BinaryBlobRegionPlan:
    """Placeholder for future CBUF/MICC/blob placement regions."""

    region_id: str
    region_kind: str
    status: str

    def to_plan(self) -> dict[str, object]:
        return {
            "region_id": self.region_id,
            "region_kind": self.region_kind,
            "status": self.status,
        }


@dataclass(frozen=True)
class BinaryLayoutPlan:
    """Report-only B-line binary placement plan."""

    profile_id: str
    runnability_state: str
    validation_status: ValidationStatus
    instruction_rows: tuple[BinaryInstructionPlan, ...]
    zero_instruction_boundaries: tuple[BinaryZeroInstructionBoundary, ...]
    task_rows: tuple[BinaryTaskPlan, ...]
    subtask_rows: tuple[BinarySubtaskPlan, ...]
    instance_rows: tuple[BinaryInstancePlan, ...]
    blob_regions: tuple[BinaryBlobRegionPlan, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "ir": "experimental_binary_layout_plan",
            "profile_id": self.profile_id,
            "runnability_state": self.runnability_state,
            "validation_status": self.validation_status,
            "instruction_rows": [row.to_plan() for row in self.instruction_rows],
            "zero_instruction_boundaries": [
                boundary.to_plan()
                for boundary in self.zero_instruction_boundaries
            ],
            "task_rows": [row.to_plan() for row in self.task_rows],
            "subtask_rows": [row.to_plan() for row in self.subtask_rows],
            "instance_rows": [row.to_plan() for row in self.instance_rows],
            "blob_regions": [region.to_plan() for region in self.blob_regions],
            "diagnostics": [
                diagnostic.to_plan() for diagnostic in self.diagnostics
            ],
            "layering_policy": (
                "binary_layout_plan_consumes_template_ops;"
                "places_concrete_template_content_without_emitting_bytes"
            ),
        }


def lower_template_ops_to_binary_layout(
    template_plan: TemplateOpPlan,
    *,
    requested_runnability_state: str = "layout_candidate",
) -> BinaryLayoutPlan:
    """Build a report-only symbolic layout from TemplateOps."""

    diagnostics = list(template_plan.diagnostics)
    instruction_rows: list[BinaryInstructionPlan] = []
    zero_boundaries: list[BinaryZeroInstructionBoundary] = []
    unresolved_ops: list[TemplateOp] = []
    row_index = 0

    for op in sorted(
        template_plan.template_ops,
        key=lambda item: item.provenance.source_schedule_ordinal,
    ):
        diagnostics.extend(op.diagnostics)
        stream_id = _attr_str(op, "stream_id")
        task_id = _task_id_from_stream_id(stream_id)
        subtask_slot = _subtask_slot_for_op(op)
        if op.template_status == "concrete_template":
            concrete_intents = [
                intent
                for intent in op.instruction_intents
                if intent.intent_status == "concrete" and intent.emits_instruction
            ]
            if not concrete_intents:
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="concrete_template_without_instruction_intent",
                        subject_id=op.id,
                        message="concrete TemplateOp has no concrete instruction intent",
                    )
                )
            for intent_index, intent in enumerate(concrete_intents):
                if intent.opcode is None:
                    diagnostics.append(
                        Diagnostic(
                            severity="error",
                            code="concrete_intent_without_opcode",
                            subject_id=op.id,
                            message="concrete instruction intent has no opcode",
                        )
                    )
                    continue
                instruction_rows.append(
                    BinaryInstructionPlan(
                        id=f"bin_instr:{op.id}:{intent_index}",
                        row_index=row_index,
                        pc=row_index,
                        template_op_id=op.id,
                        source_schedule_step_id=op.provenance.source_schedule_step_id,
                        primary_fiber_op_id=op.provenance.primary_fiber_op_id,
                        role=op.role,
                        opcode=intent.opcode,
                        phase=op.phase,
                        loop_instance=op.loop_instance,
                        task_id=task_id,
                        stream_id=stream_id,
                        subtask_slot=subtask_slot,
                        attrs=(
                            ("intent_role", intent.role),
                            ("operand_policy", intent.operand_policy),
                            ("immediate_policy", intent.immediate_policy),
                        ),
                    )
                )
                row_index += 1
        elif op.template_status == "zero_instruction":
            if any(intent.emits_instruction for intent in op.instruction_intents):
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="zero_instruction_boundary_has_instruction_intent",
                        subject_id=op.id,
                        message="zero-instruction TemplateOp must not emit instructions",
                    )
                )
            zero_boundaries.append(
                BinaryZeroInstructionBoundary(
                    id=f"bin_zero_boundary:{op.id}",
                    template_op_id=op.id,
                    source_schedule_step_id=op.provenance.source_schedule_step_id,
                    primary_fiber_op_id=op.provenance.primary_fiber_op_id,
                    role=op.role,
                    phase=op.phase,
                    loop_instance=op.loop_instance,
                    task_id=task_id,
                    stream_id=stream_id,
                    subtask_slot=subtask_slot,
                    boundary_kind=op.template_kind,
                    attrs=(("reason", "semantic_boundary_no_instruction_row"),),
                )
            )
        else:
            unresolved_ops.append(op)
            if any(
                intent.intent_status == "candidate_unproven"
                for intent in op.instruction_intents
            ):
                diagnostics.append(
                    Diagnostic(
                        severity="warning",
                        code="candidate_intent_not_allocated",
                        subject_id=op.id,
                        message="candidate-unproven instruction intent was not allocated a PC row",
                    )
                )
            if op.template_status == "unsupported":
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="unsupported_template_op",
                        subject_id=op.id,
                        message="unsupported TemplateOp cannot be laid out as runnable",
                    )
                )

    if requested_runnability_state in {"emittable_debug", "runnable_candidate"} and unresolved_ops:
        diagnostics.append(
            Diagnostic(
                severity="warning",
                code="requested_emission_has_unresolved_template_ops",
                subject_id="BinaryLayoutPlan",
                message=(
                    "requested runnability was downgraded because unresolved "
                    "TemplateOps remain"
                ),
            )
        )
        runnability_state = "layout_candidate"
    else:
        runnability_state = requested_runnability_state

    validation_status: ValidationStatus = (
        "invalid"
        if any(diagnostic.severity == "error" for diagnostic in diagnostics)
        else "valid"
    )
    return BinaryLayoutPlan(
        profile_id=template_plan.profile_id,
        runnability_state=runnability_state,
        validation_status=validation_status,
        instruction_rows=tuple(instruction_rows),
        zero_instruction_boundaries=tuple(zero_boundaries),
        task_rows=_task_rows(instruction_rows, zero_boundaries, unresolved_ops),
        subtask_rows=_subtask_rows(instruction_rows, zero_boundaries, unresolved_ops),
        instance_rows=_instance_rows(instruction_rows),
        blob_regions=(
            BinaryBlobRegionPlan(
                region_id="instruction_rows",
                region_kind="symbolic_instruction_region",
                status="report_only",
            ),
        ),
        diagnostics=tuple(diagnostics),
    )


def summarize_binary_layout_plan(plan: BinaryLayoutPlan) -> dict[str, object]:
    """Return stable counts for focused checks and reports."""

    phase_counts: dict[str, int] = {}
    opcode_counts: dict[str, int] = {}
    subtask_instruction_counts: dict[str, int] = {}
    task_instruction_counts: dict[int, int] = {}
    diagnostic_severity_counts: dict[str, int] = {}
    forbidden_tile_micro_block_fields = 0
    duplicate_pc_count = 0
    unresolved_template_op_count = 0
    seen_pcs: set[int] = set()

    for diagnostic in plan.diagnostics:
        diagnostic_severity_counts[diagnostic.severity] = (
            diagnostic_severity_counts.get(diagnostic.severity, 0) + 1
        )
        if diagnostic.code in {
            "candidate_intent_not_allocated",
            "unsupported_template_op",
        }:
            unresolved_template_op_count += 1
    for row in plan.instruction_rows:
        phase_counts[row.phase] = phase_counts.get(row.phase, 0) + 1
        opcode_counts[row.opcode] = opcode_counts.get(row.opcode, 0) + 1
        subtask_instruction_counts[row.subtask_slot] = (
            subtask_instruction_counts.get(row.subtask_slot, 0) + 1
        )
        if row.task_id is not None:
            task_instruction_counts[row.task_id] = (
                task_instruction_counts.get(row.task_id, 0) + 1
            )
        if row.pc in seen_pcs:
            duplicate_pc_count += 1
        seen_pcs.add(row.pc)
        for key, _value in row.attrs:
            if key.startswith("source_tile_micro_block") or key == "tile_micro_block_kind":
                forbidden_tile_micro_block_fields += 1

    zero_boundary_phase_counts: dict[str, int] = {}
    for boundary in plan.zero_instruction_boundaries:
        zero_boundary_phase_counts[boundary.phase] = (
            zero_boundary_phase_counts.get(boundary.phase, 0) + 1
        )
        for key, _value in boundary.attrs:
            if key.startswith("source_tile_micro_block") or key == "tile_micro_block_kind":
                forbidden_tile_micro_block_fields += 1

    return {
        "profile_id": plan.profile_id,
        "runnability_state": plan.runnability_state,
        "validation_status": plan.validation_status,
        "instruction_row_count": len(plan.instruction_rows),
        "zero_instruction_boundary_count": len(plan.zero_instruction_boundaries),
        "task_row_count": len(plan.task_rows),
        "subtask_row_count": len(plan.subtask_rows),
        "instance_row_count": len(plan.instance_rows),
        "phase_instruction_counts": dict(sorted(phase_counts.items())),
        "zero_boundary_phase_counts": dict(sorted(zero_boundary_phase_counts.items())),
        "opcode_counts": dict(sorted(opcode_counts.items())),
        "subtask_instruction_counts": dict(sorted(subtask_instruction_counts.items())),
        "task_instruction_counts": dict(sorted(task_instruction_counts.items())),
        "diagnostic_severity_counts": dict(sorted(diagnostic_severity_counts.items())),
        "diagnostic_count": len(plan.diagnostics),
        "unresolved_template_op_count": unresolved_template_op_count,
        "duplicate_pc_count": duplicate_pc_count,
        "forbidden_tile_micro_block_field_count": forbidden_tile_micro_block_fields,
    }


def _task_rows(
    instruction_rows: list[BinaryInstructionPlan],
    zero_boundaries: list[BinaryZeroInstructionBoundary],
    unresolved_ops: list[TemplateOp],
) -> tuple[BinaryTaskPlan, ...]:
    task_ids = {
        item.task_id
        for item in (*instruction_rows, *zero_boundaries)
        if item.task_id is not None
    }
    task_ids.update(
        task_id
        for task_id in (_task_id_from_stream_id(_attr_str(op, "stream_id")) for op in unresolved_ops)
        if task_id is not None
    )
    rows = []
    for task_id in sorted(task_ids):
        rows.append(
            BinaryTaskPlan(
                task_id=task_id,
                instruction_row_count=sum(
                    1 for row in instruction_rows if row.task_id == task_id
                ),
                zero_instruction_boundary_count=sum(
                    1 for boundary in zero_boundaries if boundary.task_id == task_id
                ),
                unresolved_template_op_count=sum(
                    1
                    for op in unresolved_ops
                    if _task_id_from_stream_id(_attr_str(op, "stream_id")) == task_id
                ),
            )
        )
    return tuple(rows)


def _subtask_rows(
    instruction_rows: list[BinaryInstructionPlan],
    zero_boundaries: list[BinaryZeroInstructionBoundary],
    unresolved_ops: list[TemplateOp],
) -> tuple[BinarySubtaskPlan, ...]:
    slots = {
        item.subtask_slot
        for item in (*instruction_rows, *zero_boundaries)
    }
    slots.update(_subtask_slot_for_op(op) for op in unresolved_ops)
    rows = []
    for slot in sorted(slots):
        rows.append(
            BinarySubtaskPlan(
                subtask_slot=slot,
                instruction_row_count=sum(
                    1 for row in instruction_rows if row.subtask_slot == slot
                ),
                zero_instruction_boundary_count=sum(
                    1 for boundary in zero_boundaries if boundary.subtask_slot == slot
                ),
                unresolved_template_op_count=sum(
                    1 for op in unresolved_ops if _subtask_slot_for_op(op) == slot
                ),
            )
        )
    return tuple(rows)


def _instance_rows(
    instruction_rows: list[BinaryInstructionPlan],
) -> tuple[BinaryInstancePlan, ...]:
    keys = {
        row.loop_instance
        for row in instruction_rows
        if row.loop_instance is not None
    }
    return tuple(
        BinaryInstancePlan(
            loop_instance=key,
            instruction_row_count=sum(
                1 for row in instruction_rows if row.loop_instance == key
            ),
        )
        for key in sorted(keys)
    )


def _subtask_slot_for_op(op: TemplateOp) -> str:
    if op.role == "compute_core:gemm_tile":
        return "subtask1_gemm_tile_template_span"
    if op.role == "tile_store" and op.phase == "tile_store":
        return "subtask3_store_tile"
    if op.role == "accumulator_prepare":
        return "subtask0_accumulator_prepare"
    if op.phase == "loop_body":
        return "subtask1_k_stream"
    if op.role == "tile_op:relu":
        return "subtask4_relu_candidate"
    if op.phase == "post_loop":
        return "subtask3_finalize_store"
    return f"subtask_unknown:{op.phase}"


def _attr_str(op: TemplateOp, key: str) -> str | None:
    for attr_key, value in op.attrs:
        if attr_key == key:
            return None if value is None else str(value)
    return None


def _task_id_from_stream_id(stream_id: str | None) -> int | None:
    if stream_id is None or not stream_id.startswith("t"):
        return None
    task_text = stream_id.split("_", 1)[0][1:]
    try:
        return int(task_text)
    except ValueError:
        return None


def _attrs_to_plan(attrs: tuple[tuple[str, JsonValue], ...]) -> dict[str, object]:
    return {key: _json_stable_value(value) for key, value in attrs}


def _json_stable_value(value: JsonValue) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, tuple):
        if all(
            isinstance(item, tuple)
            and len(item) == 2
            and isinstance(item[0], str)
            for item in value
        ):
            return {
                str(key): _json_stable_value(item_value)
                for key, item_value in value
            }
        return [_json_stable_value(item) for item in value]
    return repr(value)


__all__ = [
    "BinaryBlobRegionPlan",
    "BinaryInstructionPlan",
    "BinaryInstancePlan",
    "BinaryLayoutPlan",
    "BinarySubtaskPlan",
    "BinaryTaskPlan",
    "BinaryZeroInstructionBoundary",
    "lower_template_ops_to_binary_layout",
    "summarize_binary_layout_plan",
]
