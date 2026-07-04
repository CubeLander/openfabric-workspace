"""Report-only TemplateOpPlan for the B-line stream compiler.

This is the first B-line layer that talks about target-template content.
It is intentionally not a binary layout and not an emitter:

    FiberExecutionSchedule -> TemplateOpPlan

The plan is allowed to be muddy and diagnostic-heavy while the feedback loop is
being built, but it must stay observable and fail-closed.  In particular, it
must not consume TileMicroBlock compatibility fields as authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from .dfu3500_semantics import Dfu3500RoleSemanticReport
from .schedule import FiberExecutionSchedule, FiberScheduleStep
from .template_records import SymbolicTemplateRecordProgram

DiagnosticSeverity = Literal["info", "warning", "error"]
RunnabilityState = Literal[
    "report_only",
    "layout_candidate",
    "emittable_debug",
    "runnable_candidate",
    "bline_atomic_gemm_tile_template_missing",
    "bline_atomic_fiber_op_chain_missing",
]
TemplateStatus = Literal[
    "concrete_template",
    "layout_candidate",
    "zero_instruction",
    "symbolic_unresolved",
    "unsupported",
]
InstructionIntentStatus = Literal[
    "concrete",
    "candidate_unproven",
    "symbolic_only",
]
JsonValue = object


@dataclass(frozen=True)
class Diagnostic:
    """Typed diagnostic suitable for deterministic reports."""

    severity: DiagnosticSeverity
    code: str
    subject_id: str
    message: str
    evidence_refs: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "severity": self.severity,
            "code": self.code,
            "subject_id": self.subject_id,
            "message": self.message,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class TemplateOpProvenance:
    """Stable source trail from TemplateOp back to FiberOp."""

    source_schedule_step_id: str
    source_schedule_ordinal: int
    source_executable_op_id: str
    primary_fiber_op_id: str
    dependency_fiber_op_ids: tuple[str, ...]
    semantic_report_record_id: str | None = None
    symbolic_template_record_id: str | None = None

    def to_plan(self) -> dict[str, object]:
        return {
            "source_schedule_step_id": self.source_schedule_step_id,
            "source_schedule_ordinal": self.source_schedule_ordinal,
            "source_executable_op_id": self.source_executable_op_id,
            "primary_fiber_op_id": self.primary_fiber_op_id,
            "dependency_fiber_op_ids": list(self.dependency_fiber_op_ids),
            "semantic_report_record_id": self.semantic_report_record_id,
            "symbolic_template_record_id": self.symbolic_template_record_id,
        }


@dataclass(frozen=True)
class TemplateResourceRequirement:
    """Symbolic resource requirement for future layout phases."""

    resource_kind: str
    requirement: str
    attrs: tuple[tuple[str, JsonValue], ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "resource_kind": self.resource_kind,
            "requirement": self.requirement,
            "attrs": _attrs_to_plan(self.attrs),
        }


@dataclass(frozen=True)
class InstructionIntent:
    """Template-level instruction intent, not a binary instruction row."""

    opcode: str | None
    role: str
    intent_status: InstructionIntentStatus
    operand_policy: str
    immediate_policy: str | None
    emits_instruction: bool
    evidence_refs: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "opcode": self.opcode,
            "role": self.role,
            "intent_status": self.intent_status,
            "operand_policy": self.operand_policy,
            "immediate_policy": self.immediate_policy,
            "emits_instruction": self.emits_instruction,
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class TemplateOp:
    """One target-template content row derived from one schedule step."""

    id: str
    provenance: TemplateOpProvenance
    role: str
    phase: str
    loop_instance: str | None
    template_kind: str
    template_status: TemplateStatus
    instruction_intents: tuple[InstructionIntent, ...]
    required_resources: tuple[TemplateResourceRequirement, ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    attrs: tuple[tuple[str, JsonValue], ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "provenance": self.provenance.to_plan(),
            "role": self.role,
            "phase": self.phase,
            "loop_instance": self.loop_instance,
            "template_kind": self.template_kind,
            "template_status": self.template_status,
            "instruction_intents": [
                intent.to_plan() for intent in self.instruction_intents
            ],
            "required_resources": [
                requirement.to_plan()
                for requirement in self.required_resources
            ],
            "diagnostics": [
                diagnostic.to_plan() for diagnostic in self.diagnostics
            ],
            "attrs": _attrs_to_plan(self.attrs),
        }


@dataclass(frozen=True)
class TemplateOpPlan:
    """Report-only target-template content plan."""

    profile_id: str
    runnability_state: RunnabilityState
    template_ops: tuple[TemplateOp, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "ir": "experimental_template_op_plan",
            "profile_id": self.profile_id,
            "runnability_state": self.runnability_state,
            "template_ops": [op.to_plan() for op in self.template_ops],
            "diagnostics": [
                diagnostic.to_plan() for diagnostic in self.diagnostics
            ],
            "layering_policy": (
                "template_op_plan_consumes_fiber_execution_schedule;"
                "describes_target_template_content_without_binary_layout_or_emission"
            ),
        }


def lower_schedule_to_template_ops(
    schedule: FiberExecutionSchedule,
    *,
    semantic_report: Dfu3500RoleSemanticReport | None = None,
    template_records: SymbolicTemplateRecordProgram | None = None,
    profile_id: str = "dfu3500_legacy_gemm_symbolic",
) -> TemplateOpPlan:
    """Lower schedule rows to report-only target-template content rows."""

    semantic_by_executable_id = {}
    template_record_by_executable_id = {}
    diagnostics = [
        Diagnostic(
            severity="error",
            code="upstream_schedule_diagnostic",
            subject_id="FiberExecutionSchedule",
            message=message,
        )
        for message in schedule.diagnostics
    ]

    if semantic_report is not None:
        profile_id = semantic_report.profile_id
        for record in semantic_report.records:
            previous = semantic_by_executable_id.setdefault(
                record.source_executable_op_id,
                record,
            )
            if previous is not record:
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="duplicate_semantic_record",
                        subject_id=record.source_executable_op_id,
                        message="duplicate semantic record for executable op",
                    )
                )
        diagnostics.extend(
            Diagnostic(
                severity="error",
                code="upstream_semantic_diagnostic",
                subject_id="Dfu3500RoleSemanticReport",
                message=message,
            )
            for message in semantic_report.diagnostics
        )

    if template_records is not None:
        profile_id = template_records.profile_id
        for record in template_records.records:
            previous = template_record_by_executable_id.setdefault(
                record.source_executable_op_id,
                record,
            )
            if previous is not record:
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="duplicate_symbolic_template_record",
                        subject_id=record.source_executable_op_id,
                        message="duplicate symbolic template record for executable op",
                    )
                )
        diagnostics.extend(
            Diagnostic(
                severity="error",
                code="upstream_template_record_diagnostic",
                subject_id="SymbolicTemplateRecordProgram",
                message=message,
            )
            for message in template_records.diagnostics
        )

    template_ops: list[TemplateOp] = []
    seen_ids: set[str] = set()

    for ordinal, step in enumerate(schedule.steps):
        semantic = semantic_by_executable_id.get(step.executable_op_id)
        template_record = template_record_by_executable_id.get(step.executable_op_id)
        template_op = _template_op_for_step(
            step,
            ordinal=ordinal,
            semantic=semantic,
            template_record=template_record,
        )
        if template_op.id in seen_ids:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="duplicate_template_op_id",
                    subject_id=template_op.id,
                    message="duplicate TemplateOp id",
                )
            )
        seen_ids.add(template_op.id)
        template_ops.append(template_op)

    return TemplateOpPlan(
        profile_id=profile_id,
        runnability_state="report_only",
        template_ops=tuple(template_ops),
        diagnostics=tuple(diagnostics),
    )


def summarize_template_op_plan(plan: TemplateOpPlan) -> dict[str, object]:
    """Return stable counts for focused checks and demo reports."""

    status_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    phase_counts: dict[str, int] = {}
    intent_status_counts: dict[str, int] = {}
    template_kind_counts: dict[str, int] = {}
    diagnostic_severity_counts: dict[str, int] = {}
    unresolved_role_counts: dict[str, int] = {}
    unsupported_role_counts: dict[str, int] = {}
    source_ids: set[str] = set()
    forbidden_tile_micro_block_fields = 0
    zero_instruction_with_instruction_rows = 0
    candidate_unproven_instruction_intents = 0
    non_json_stable_attr_count = 0

    for diagnostic in plan.diagnostics:
        diagnostic_severity_counts[diagnostic.severity] = (
            diagnostic_severity_counts.get(diagnostic.severity, 0) + 1
        )

    for op in plan.template_ops:
        status_counts[op.template_status] = status_counts.get(op.template_status, 0) + 1
        role_counts[op.role] = role_counts.get(op.role, 0) + 1
        phase_counts[op.phase] = phase_counts.get(op.phase, 0) + 1
        template_kind_counts[op.template_kind] = template_kind_counts.get(op.template_kind, 0) + 1
        source_ids.add(op.provenance.primary_fiber_op_id)
        if op.template_status == "symbolic_unresolved":
            unresolved_role_counts[op.role] = unresolved_role_counts.get(op.role, 0) + 1
        if op.template_status == "unsupported":
            unsupported_role_counts[op.role] = unsupported_role_counts.get(op.role, 0) + 1
        for intent in op.instruction_intents:
            intent_status_counts[intent.intent_status] = (
                intent_status_counts.get(intent.intent_status, 0) + 1
            )
            if intent.intent_status == "candidate_unproven":
                candidate_unproven_instruction_intents += 1
        if op.template_status == "zero_instruction" and any(
            intent.emits_instruction for intent in op.instruction_intents
        ):
            zero_instruction_with_instruction_rows += 1
        non_json_stable_attr_count += _non_json_stable_attr_count(op.attrs)
        for key, _value in op.attrs:
            if key.startswith("source_tile_micro_block") or key == "tile_micro_block_kind":
                forbidden_tile_micro_block_fields += 1
        for diagnostic in op.diagnostics:
            diagnostic_severity_counts[diagnostic.severity] = (
                diagnostic_severity_counts.get(diagnostic.severity, 0) + 1
            )

    return {
        "profile_id": plan.profile_id,
        "runnability_state": plan.runnability_state,
        "template_op_count": len(plan.template_ops),
        "unique_source_fiber_op_count": len(source_ids),
        "status_counts": dict(sorted(status_counts.items())),
        "role_counts": dict(sorted(role_counts.items())),
        "phase_counts": dict(sorted(phase_counts.items())),
        "template_kind_counts": dict(sorted(template_kind_counts.items())),
        "intent_status_counts": dict(sorted(intent_status_counts.items())),
        "unresolved_role_counts": dict(sorted(unresolved_role_counts.items())),
        "unsupported_role_counts": dict(sorted(unsupported_role_counts.items())),
        "diagnostic_severity_counts": dict(sorted(diagnostic_severity_counts.items())),
        "diagnostic_count": len(plan.diagnostics)
        + sum(len(op.diagnostics) for op in plan.template_ops),
        "forbidden_tile_micro_block_field_count": forbidden_tile_micro_block_fields,
        "zero_instruction_with_instruction_row_count": zero_instruction_with_instruction_rows,
        "candidate_unproven_instruction_intent_count": candidate_unproven_instruction_intents,
        "non_json_stable_attr_count": non_json_stable_attr_count,
    }


def _template_op_for_step(
    step: FiberScheduleStep,
    *,
    ordinal: int,
    semantic: object | None,
    template_record: object | None,
) -> TemplateOp:
    semantic_id = getattr(semantic, "id", None)
    template_record_id = getattr(template_record, "id", None)
    proof_status = str(getattr(semantic, "proof_status", step.proof_status))
    semantic_kind = str(getattr(semantic, "semantic_kind", step.semantic_kind))
    candidate_mechanism = str(
        getattr(semantic, "candidate_mechanism", step.candidate_mechanism)
    )
    source_template_role = getattr(template_record, "template_role", None)
    required_evidence = tuple(
        str(evidence)
        for evidence in getattr(semantic, "required_evidence", ())
    )
    notes = tuple(str(note) for note in getattr(semantic, "notes", ()))
    diagnostics = _diagnostics_for_step(
        step,
        proof_status=proof_status,
        required_evidence=required_evidence,
    )
    template_status = _template_status_for_step(step, proof_status=proof_status)
    instruction_intents = _instruction_intents_for_step(
        step,
        template_status=template_status,
        required_evidence=required_evidence,
    )
    return TemplateOp(
        id=f"template_op:{step.executable_op_id}",
        provenance=TemplateOpProvenance(
            source_schedule_step_id=step.id,
            source_schedule_ordinal=ordinal,
            source_executable_op_id=step.executable_op_id,
            primary_fiber_op_id=step.source_fiber_op_id,
            dependency_fiber_op_ids=step.dependency_source_ids,
            semantic_report_record_id=None if semantic_id is None else str(semantic_id),
            symbolic_template_record_id=(
                None if template_record_id is None else str(template_record_id)
            ),
        ),
        role=step.role,
        phase=step.phase,
        loop_instance=step.loop_instance_key,
        template_kind=_template_kind_for_step(
            step,
            template_status=template_status,
            candidate_mechanism=candidate_mechanism,
            source_template_role=None if source_template_role is None else str(source_template_role),
        ),
        template_status=template_status,
        instruction_intents=instruction_intents,
        required_resources=_resource_requirements_for_step(step, template_status),
        diagnostics=diagnostics,
        attrs=(
            ("source_ir", "FiberExecutionSchedule"),
            ("stream_id", step.stream_id),
            ("semantic_kind", semantic_kind),
            ("proof_status", proof_status),
            ("candidate_mechanism", candidate_mechanism),
            ("source_template_role", None if source_template_role is None else str(source_template_role)),
            ("semantic_notes", notes),
        ),
    )


def _template_status_for_step(
    step: FiberScheduleStep,
    *,
    proof_status: str,
) -> TemplateStatus:
    if step.role == "accumulator_finalize" and proof_status == "proven":
        return "zero_instruction"
    if proof_status == "proven":
        return "concrete_template"
    if proof_status == "unproven":
        return "symbolic_unresolved"
    return "unsupported"


def _template_kind_for_step(
    step: FiberScheduleStep,
    *,
    template_status: TemplateStatus,
    candidate_mechanism: str,
    source_template_role: str | None,
) -> str:
    if template_status == "zero_instruction":
        return "accumulator_value_boundary"
    if step.role == "compute_core:gemm_tile":
        return "dfu3500_gemm_tile_template_span"
    if step.role == "tile_op:relu":
        return "relu_max_zero_candidate"
    if step.role == "tile_op:clamp_min":
        return "dfu3500_log10max_clamp_min_tile"
    if step.role == "tile_op:log10":
        return "dfu3500_log10max_log10_tile"
    if step.role == "tile_reduce:local_reduce_max":
        return "dfu3500_log10max_local_reduce_max_tile"
    if step.role == "collective:global_max":
        return "dfu3500_log10max_pe00_global_max_symbolic"
    if step.role == "tile_op:max_with_floor":
        return "dfu3500_log10max_max_with_floor_symbolic"
    if step.role == "tile_op:affine_scale":
        return "dfu3500_log10max_affine_scale_tile"
    if source_template_role is not None:
        return source_template_role
    if candidate_mechanism != "unknown":
        return candidate_mechanism
    return f"unmapped_role:{step.role}"


def _instruction_intents_for_step(
    step: FiberScheduleStep,
    *,
    template_status: TemplateStatus,
    required_evidence: tuple[str, ...],
) -> tuple[InstructionIntent, ...]:
    if template_status == "zero_instruction":
        return ()
    if step.role == "accumulator_prepare":
        return (_concrete_intent("ACC_PREPARE", step.role, "accumulator_prepare_operands"),)
    if step.role in {"operand_materialize:A", "operand_materialize:B"}:
        return (_concrete_intent("LOAD_OR_COPY", step.role, "source_operand_fragment"),)
    if step.role in {"operand_route_recv:A", "operand_route_recv:B"}:
        return (_concrete_intent("ROUTE_RECV_VISIBILITY", step.role, "receiver_operand_fragment"),)
    if step.role in {"operand_route_push:A", "operand_route_push:B"}:
        return (_concrete_intent("ROUTE_PUSH", step.role, "sender_operand_fragment"),)
    if step.role == "compute_core:gemm_update":
        return (_concrete_intent("HMMAL_OR_GEMM_UPDATE", step.role, "gemm_a_b_accumulator"),)
    if step.role == "compute_core:gemm_tile":
        return (
            _concrete_intent(
                "GEMM_TILE_TEMPLATE_SPAN",
                step.role,
                "atomic_gemm_tile_template_span",
            ),
        )
    if step.role == "tile_store":
        return (_concrete_intent("STD", step.role, "output_tile_fragment"),)
    if step.role == "tile_op:relu":
        return (
            _concrete_intent(
                "HMAX",
                step.role,
                "input_fragment_and_zero_constant",
                immediate_policy="zero_constant_via_IMM_or_equivalent",
            ),
        )
    if step.role == "tile_op:clamp_min":
        return (
            _concrete_intent(
                "FMAX",
                step.role,
                "input_fragment_and_clamp_min_constant",
                immediate_policy="fp32_constant_1e-10",
            ),
        )
    if step.role == "tile_op:log10":
        return (
            _concrete_intent("FLOG2", step.role, "input_fragment"),
            _concrete_intent(
                "FMUL",
                step.role,
                "log2_fragment_and_log10_2_constant",
                immediate_policy="fp32_constant_log10_2",
            ),
        )
    if step.role == "tile_reduce:local_reduce_max":
        return (
            _concrete_intent("SHFL", step.role, "lane_shuffle_reduce_fragment"),
            _concrete_intent("FMAX", step.role, "lane_max_reduce_fragment"),
        )
    if step.role == "collective:global_max":
        return (
            InstructionIntent(
                opcode=None,
                role=step.role,
                intent_status="symbolic_only",
                operand_policy="pe00_materialized_scalar_blocked",
                immediate_policy=None,
                emits_instruction=False,
                evidence_refs=required_evidence,
            ),
        )
    if step.role == "tile_op:max_with_floor":
        return (
            InstructionIntent(
                opcode="FMAX",
                role=step.role,
                intent_status="candidate_unproven",
                operand_policy="local_log10_fragment_and_global_threshold_scalar",
                immediate_policy="global_max_plus_negative_8_scalar",
                emits_instruction=True,
                evidence_refs=required_evidence,
            ),
        )
    if step.role == "tile_op:affine_scale":
        return (
            _concrete_intent(
                "FADD",
                step.role,
                "clipped_fragment_and_output_bias",
                immediate_policy="fp32_constant_4",
            ),
            _concrete_intent(
                "FMUL",
                step.role,
                "biased_fragment_and_output_scale",
                immediate_policy="fp32_constant_0_25",
            ),
        )
    return (
        InstructionIntent(
            opcode=None,
            role=step.role,
            intent_status="symbolic_only",
            operand_policy="unknown",
            immediate_policy=None,
            emits_instruction=False,
            evidence_refs=required_evidence,
        ),
    )


def _concrete_intent(
    opcode: str,
    role: str,
    operand_policy: str,
    *,
    immediate_policy: str | None = None,
) -> InstructionIntent:
    return InstructionIntent(
        opcode=opcode,
        role=role,
        intent_status="concrete",
        operand_policy=operand_policy,
        immediate_policy=immediate_policy,
        emits_instruction=True,
        evidence_refs=(),
    )


def _resource_requirements_for_step(
    step: FiberScheduleStep,
    template_status: TemplateStatus,
) -> tuple[TemplateResourceRequirement, ...]:
    if template_status == "zero_instruction":
        return (
            TemplateResourceRequirement(
                resource_kind="semantic_boundary",
                requirement="no_pc_or_instruction_row",
            ),
        )
    if step.phase == "loop_body":
        return (
            TemplateResourceRequirement(
                resource_kind="loop_region",
                requirement="k_loop_instance_visible",
                attrs=(("loop_instance", step.loop_instance_key),),
            ),
        )
    return ()


def _diagnostics_for_step(
    step: FiberScheduleStep,
    *,
    proof_status: str,
    required_evidence: tuple[str, ...],
) -> tuple[Diagnostic, ...]:
    if proof_status == "unproven":
        return (
            Diagnostic(
                severity="warning",
                code="template_role_unproven",
                subject_id=step.id,
                message=f"template role remains unresolved: {step.role}",
                evidence_refs=required_evidence,
            ),
        )
    if proof_status in {"unsupported", "unknown"}:
        return (
            Diagnostic(
                severity="warning",
                code="template_role_unsupported",
                subject_id=step.id,
                message=f"template role is not concrete: {step.role}",
                evidence_refs=required_evidence,
            ),
        )
    return ()


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


def _non_json_stable_attr_count(attrs: tuple[tuple[str, JsonValue], ...]) -> int:
    return sum(0 if _is_json_stable_value(value) else 1 for _key, value in attrs)


def _is_json_stable_value(value: JsonValue) -> bool:
    if value is None or isinstance(value, (str, int, float, bool)):
        return True
    if isinstance(value, tuple):
        return all(_is_json_stable_value(item) for item in value)
    return False


__all__ = [
    "Diagnostic",
    "InstructionIntent",
    "TemplateOp",
    "TemplateOpPlan",
    "TemplateOpProvenance",
    "TemplateResourceRequirement",
    "lower_schedule_to_template_ops",
    "summarize_template_op_plan",
]
