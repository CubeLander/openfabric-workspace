"""Fail-closed ReLU binding report for GEMM+ReLU TemplateOps.

This layer is intentionally narrow.  The old fused GEMM+ReLU fiber path is not
allowed in B-line.  Until explicit tile op-chain lowering produces first-class
ReLU TemplateOps, this report must remain fail-closed and must not make the
missing ReLU rows look runnable.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from gpdpu_compiler.core.dfu3500 import DFU3500_DEFAULT_TILE, DFU3500_GEMM_REGIONS
from gpdpu_compiler.core.program_legacy_inst import (
    decode_legacy_inst_skeleton,
    legacy_relu_hmax_zero_template,
    pack_legacy_inst,
)

from .template_ops import Diagnostic, JsonValue, TemplateOp, TemplateOpPlan

ReluBindingStatus = Literal["concrete_row_plan_candidate", "fail_closed"]
EvidenceRequirementStatus = Literal["available", "closed", "p0_blocked"]

EXPECTED_RELU_TEMPLATE_COUNT = 64
EXPLICIT_RELU_OPERATOR = "gemm_relu"
EXPLICIT_RELU_LAYOUT = "explicit_subtask"
EXPLICIT_RELU_OP = "FMAX_OR_HMAX"
ACTIVE_RELU_SELECTOR_PROOF = "active_relu_template_family_selector_proof"
ACTIVE_RELU_SOURCE_ARTIFACTS = (
    "generated_subtask4_relu_template_csv_for_customer_shape",
    "app_conf_subtask_num_4_or_equivalent_explicit_relu_task",
    "secondary_fusion_array_or_bline_op_chain_activation_record",
    "decoded_subtask4_imm_hmax_roundtrip",
)
ACTIVE_RELU_RUNTIME_TRACE_ARTIFACT = "active_subtask4_runtime_selector_trace"


@dataclass(frozen=True)
class ExplicitReluSubtaskBinding:
    """One explicit ReLU subtask/template binding candidate."""

    id: str
    relu_template_op_id: str
    store_template_op_id: str | None
    source_schedule_step_id: str
    primary_fiber_op_id: str
    store_primary_fiber_op_id: str | None
    stream_id: str | None
    task_id: int | None
    source_template_status: str
    source_instruction_opcode: str | None
    dtype_decision: "ReluDtypeDecision"
    zero_constant_policy: "ReluZeroConstantPolicy"
    exact_row_evidence: "ReluExactRowEvidence"
    binding_seed: "ReluTemplateBindingSeed"
    store_operand_lifetime: "ReluStoreOperandLifetime"
    operator: str = EXPLICIT_RELU_OPERATOR
    relu_layout: str = EXPLICIT_RELU_LAYOUT
    relu_op: str = EXPLICIT_RELU_OP
    expected_relu_template_count: int = EXPECTED_RELU_TEMPLATE_COUNT
    store_input: str = "relu_output"
    pre_relu_store_forbidden: bool = True
    attrs: tuple[tuple[str, JsonValue], ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "operator": self.operator,
            "relu_layout": self.relu_layout,
            "relu_op": self.relu_op,
            "expected_relu_template_count": self.expected_relu_template_count,
            "store_input": self.store_input,
            "pre_relu_store_forbidden": self.pre_relu_store_forbidden,
            "relu_template_op_id": self.relu_template_op_id,
            "store_template_op_id": self.store_template_op_id,
            "source_schedule_step_id": self.source_schedule_step_id,
            "primary_fiber_op_id": self.primary_fiber_op_id,
            "store_primary_fiber_op_id": self.store_primary_fiber_op_id,
            "stream_id": self.stream_id,
            "task_id": self.task_id,
            "source_template_status": self.source_template_status,
            "source_instruction_opcode": self.source_instruction_opcode,
            "dtype_decision": self.dtype_decision.to_plan(),
            "zero_constant_policy": self.zero_constant_policy.to_plan(),
            "exact_row_evidence": self.exact_row_evidence.to_plan(),
            "binding_seed": self.binding_seed.to_plan(),
            "store_operand_lifetime": self.store_operand_lifetime.to_plan(),
            "attrs": _attrs_to_plan(self.attrs),
        }


@dataclass(frozen=True)
class ExplicitReluSubtaskBindingReport:
    """Fail-closed ReLU binding report consumable by later row planning."""

    profile_id: str
    binding_status: ReluBindingStatus
    bindings: tuple[ExplicitReluSubtaskBinding, ...]
    evidence_requirements: tuple["ReluEvidenceRequirement", ...] = ()
    diagnostics: tuple[Diagnostic, ...] = ()
    blockers: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "ir": "experimental_explicit_relu_subtask_binding_report",
            "profile_id": self.profile_id,
            "binding_status": self.binding_status,
            "operator": EXPLICIT_RELU_OPERATOR,
            "relu_layout": EXPLICIT_RELU_LAYOUT,
            "relu_op": EXPLICIT_RELU_OP,
            "expected_relu_template_count": EXPECTED_RELU_TEMPLATE_COUNT,
            "store_input": "relu_output",
            "pre_relu_store_forbidden": True,
            "bindings": [binding.to_plan() for binding in self.bindings],
            "evidence_requirements": [
                requirement.to_plan()
                for requirement in self.evidence_requirements
            ],
            "diagnostics": [
                diagnostic.to_plan()
                for diagnostic in self.diagnostics
            ],
            "blockers": list(self.blockers),
            "layering_policy": (
                "explicit_relu_subtask_binding_consumes_template_ops;"
                "does_not_emit_instructions_or_vendor_binary;"
                "unresolved_relu_templates_fail_closed"
            ),
        }


@dataclass(frozen=True)
class ReluEvidenceRequirement:
    """One short evidence item needed before ReLU rows are runnable."""

    id: str
    status: EvidenceRequirementStatus
    category: str
    requirement: str
    evidence_refs: tuple[str, ...] = ()
    missing_reason: str | None = None
    attrs: tuple[tuple[str, JsonValue], ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "status": self.status,
            "category": self.category,
            "requirement": self.requirement,
            "evidence_refs": list(self.evidence_refs),
            "missing_reason": self.missing_reason,
            "attrs": _attrs_to_plan(self.attrs),
        }


@dataclass(frozen=True)
class ReluDtypeDecision:
    """Concrete opcode recommendation for ReLU dtype."""

    status: EvidenceRequirementStatus
    recommended_opcode: str | None
    lane_dtype: str | None
    source: str
    evidence_refs: tuple[str, ...]
    blocker: str | None = None

    def to_plan(self) -> dict[str, object]:
        return {
            "status": self.status,
            "recommended_opcode": self.recommended_opcode,
            "lane_dtype": self.lane_dtype,
            "source": self.source,
            "evidence_refs": list(self.evidence_refs),
            "blocker": self.blocker,
        }


@dataclass(frozen=True)
class ReluZeroConstantPolicy:
    """Zero operand materialization policy for one ReLU candidate."""

    status: EvidenceRequirementStatus
    policy: str
    zero_value: str
    materialization_opcode: str | None
    operand_tag: str
    operand_index: int | None
    blocker: str | None

    def to_plan(self) -> dict[str, object]:
        return {
            "status": self.status,
            "policy": self.policy,
            "zero_value": self.zero_value,
            "materialization_opcode": self.materialization_opcode,
            "operand_tag": self.operand_tag,
            "operand_index": self.operand_index,
            "blocker": self.blocker,
        }


@dataclass(frozen=True)
class ReluExactRowEvidence:
    """Exact row selector/proof status for one ReLU tile op."""

    status: EvidenceRequirementStatus
    selector_status: str
    recommended_max_opcode: str | None
    zero_opcode: str | None
    legacy_gemm_hmax_rows: int
    legacy_gemm_fmax_rows: int
    legacy_gemm_imm_rows: int
    doc_hmax_shape_rows: int
    functional_probe_fmax_rows: int
    functional_probe_imm_rows: int
    evidence_refs: tuple[str, ...]
    required_writer_inputs: tuple[str, ...]
    missing_writer_inputs: tuple[str, ...]
    row_byte_proof_plan: "ReluRowByteProofPlan"
    blocker: str | None

    def to_plan(self) -> dict[str, object]:
        return {
            "status": self.status,
            "selector_status": self.selector_status,
            "recommended_max_opcode": self.recommended_max_opcode,
            "zero_opcode": self.zero_opcode,
            "legacy_gemm_profile": {
                "hmax_rows": self.legacy_gemm_hmax_rows,
                "fmax_rows": self.legacy_gemm_fmax_rows,
                "imm_rows": self.legacy_gemm_imm_rows,
            },
            "doc_hmax_shape_profile": {
                "hmax_shape_rows": self.doc_hmax_shape_rows,
                "source": "dfu3500 instruction docs OCR row shape",
            },
            "functional_maximum_probe": {
                "fmax_rows": self.functional_probe_fmax_rows,
                "imm_rows": self.functional_probe_imm_rows,
            },
            "evidence_refs": list(self.evidence_refs),
            "required_writer_inputs": list(self.required_writer_inputs),
            "missing_writer_inputs": list(self.missing_writer_inputs),
            "row_byte_proof_plan": self.row_byte_proof_plan.to_plan(),
            "blocker": self.blocker,
        }


@dataclass(frozen=True)
class ReluRowByteProofRequirement:
    """One machine-checkable requirement before ReLU row bytes can be claimed."""

    id: str
    status: EvidenceRequirementStatus
    category: str
    requirement: str
    evidence_refs: tuple[str, ...] = ()
    missing_reason: str | None = None
    attrs: tuple[tuple[str, JsonValue], ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "status": self.status,
            "category": self.category,
            "requirement": self.requirement,
            "evidence_refs": list(self.evidence_refs),
            "missing_reason": self.missing_reason,
            "attrs": _attrs_to_plan(self.attrs),
        }


@dataclass(frozen=True)
class ReluRowByteProofPlan:
    """Fail-closed plan for IMM-zero + HMAX/FMAX row-byte materialization."""

    status: str
    selected_max_opcode: str | None
    zero_opcode: str | None
    row_family: str
    materializer_candidate: "ReluHmaxMaterializerCandidate | None"
    row_bytes_claim: bool
    raw_template_row_sha256_claim: bool
    proof_requirements: tuple[ReluRowByteProofRequirement, ...]
    required_artifacts: tuple[str, ...]
    missing_artifacts: tuple[str, ...]

    def to_plan(self) -> dict[str, object]:
        return {
            "status": self.status,
            "selected_max_opcode": self.selected_max_opcode,
            "zero_opcode": self.zero_opcode,
            "row_family": self.row_family,
            "materializer_candidate": (
                None
                if self.materializer_candidate is None
                else self.materializer_candidate.to_plan()
            ),
            "row_bytes_claim": self.row_bytes_claim,
            "raw_template_row_sha256_claim": self.raw_template_row_sha256_claim,
            "proof_requirements": [
                requirement.to_plan()
                for requirement in self.proof_requirements
            ],
            "required_artifacts": list(self.required_artifacts),
            "missing_artifacts": list(self.missing_artifacts),
        }


@dataclass(frozen=True)
class ReluHmaxMaterializerCandidate:
    """Explicit IMM-zero + HMAX candidate rows for one ReLU tile op."""

    status: str
    selector_kind: str
    expected_ops: tuple[str, ...]
    row_count: int
    input_operand_index: int
    zero_operand_index: int
    output_operand_index: int
    max_src0_operand_role: str
    max_src1_operand_role: str
    local_order: tuple[int, ...]
    csv_rows: tuple[tuple[str, ...], ...]
    raw_inst_t_byte_count: int
    raw_template_row_sha256: str
    per_row_sha256: tuple[str, ...]
    candidate_row_bytes_claim: bool
    candidate_raw_template_row_sha256_claim: bool
    active_selector_claim: bool
    activation_record: "ReluSubtask4ActivationRecord"
    blocker: str

    def to_plan(self) -> dict[str, object]:
        return {
            "status": self.status,
            "selector_kind": self.selector_kind,
            "expected_ops": list(self.expected_ops),
            "row_count": self.row_count,
            "operand_indexes": {
                "input": self.input_operand_index,
                "zero": self.zero_operand_index,
                "output": self.output_operand_index,
            },
            "max_operand_roles": {
                "src0": self.max_src0_operand_role,
                "src1": self.max_src1_operand_role,
            },
            "local_order": list(self.local_order),
            "csv_rows": [list(row) for row in self.csv_rows],
            "raw_inst_t_byte_count": self.raw_inst_t_byte_count,
            "raw_template_row_sha256": self.raw_template_row_sha256,
            "per_row_sha256": list(self.per_row_sha256),
            "candidate_row_bytes_claim": self.candidate_row_bytes_claim,
            "candidate_raw_template_row_sha256_claim": (
                self.candidate_raw_template_row_sha256_claim
            ),
            "active_selector_claim": self.active_selector_claim,
            "activation_record": self.activation_record.to_plan(),
            "blocker": self.blocker,
        }


@dataclass(frozen=True)
class ReluSubtask4ActivationRecord:
    """Source-backed activation candidate for explicit ReLU subtask4."""

    status: str
    source_kind: str
    subtask_slot: str
    generated_csv_candidate_status: EvidenceRequirementStatus
    explicit_task_activation_status: EvidenceRequirementStatus
    op_chain_activation_status: EvidenceRequirementStatus
    local_decode_roundtrip_status: EvidenceRequirementStatus
    runtime_selector_trace_status: EvidenceRequirementStatus
    decoded_ops: tuple[str, ...]
    decoded_opcode_values: tuple[int, ...]
    decoded_src_operands: tuple[tuple[int, int, int], ...]
    decoded_dst_operands: tuple[tuple[int, int, int], ...]
    source_refs: tuple[str, ...]
    remaining_artifacts: tuple[str, ...]
    blocker: str

    def to_plan(self) -> dict[str, object]:
        return {
            "status": self.status,
            "source_kind": self.source_kind,
            "subtask_slot": self.subtask_slot,
            "generated_csv_candidate_status": self.generated_csv_candidate_status,
            "explicit_task_activation_status": self.explicit_task_activation_status,
            "op_chain_activation_status": self.op_chain_activation_status,
            "local_decode_roundtrip_status": self.local_decode_roundtrip_status,
            "runtime_selector_trace_status": self.runtime_selector_trace_status,
            "decoded_ops": list(self.decoded_ops),
            "decoded_opcode_values": list(self.decoded_opcode_values),
            "decoded_src_operands": [
                list(operands) for operands in self.decoded_src_operands
            ],
            "decoded_dst_operands": [
                list(operands) for operands in self.decoded_dst_operands
            ],
            "source_refs": list(self.source_refs),
            "remaining_artifacts": list(self.remaining_artifacts),
            "blocker": self.blocker,
        }


@dataclass(frozen=True)
class ReluTemplateBindingSeed:
    """S2-facing exact template binding seed skeleton."""

    seed_schema: str
    seed_status: EvidenceRequirementStatus
    template_op_id: str
    role: str
    template_family: str
    template_path: str | None
    template_index: int
    row_span_start: int | None
    row_span_end: int | None
    expected_ops: tuple[str, ...]
    expected_row_count: int
    required_writer_inputs: tuple[str, ...]
    missing_writer_inputs: tuple[str, ...]
    template_row_sha256: str | None
    raw_template_bytes_sha256: str | None
    blocker: str | None

    def to_plan(self) -> dict[str, object]:
        return {
            "seed_schema": self.seed_schema,
            "seed_status": self.seed_status,
            "template_op_id": self.template_op_id,
            "role": self.role,
            "template_family": self.template_family,
            "template_path": self.template_path,
            "template_index": self.template_index,
            "row_span": {
                "start": self.row_span_start,
                "end": self.row_span_end,
                "expected_row_count": self.expected_row_count,
            },
            "expected_ops": list(self.expected_ops),
            "required_writer_inputs": list(self.required_writer_inputs),
            "missing_writer_inputs": list(self.missing_writer_inputs),
            "template_row_sha256": self.template_row_sha256,
            "raw_template_bytes_sha256": self.raw_template_bytes_sha256,
            "blocker": self.blocker,
        }


@dataclass(frozen=True)
class ReluStoreOperandLifetime:
    """Store-consumes-ReLU-output proof at TemplateOp graph level."""

    status: EvidenceRequirementStatus
    required_store_input: str
    forbidden_store_input: str
    relu_output_fragment: str
    store_template_op_id: str | None
    store_dependency_source: str | None
    blocker: str | None

    def to_plan(self) -> dict[str, object]:
        return {
            "status": self.status,
            "required_store_input": self.required_store_input,
            "forbidden_store_input": self.forbidden_store_input,
            "relu_output_fragment": self.relu_output_fragment,
            "store_template_op_id": self.store_template_op_id,
            "store_dependency_source": self.store_dependency_source,
            "blocker": self.blocker,
        }


def bind_explicit_relu_subtasks(
    template_plan: TemplateOpPlan,
    *,
    expected_relu_template_count: int = EXPECTED_RELU_TEMPLATE_COUNT,
) -> ExplicitReluSubtaskBindingReport:
    """Build an explicit GEMM+ReLU binding report from TemplateOps.

    The report creates concrete-shaped candidate rows only when the ReLU
    operation and store dependency are visible.  It remains fail-closed until
    the source TemplateOps are already concrete templates.
    """

    diagnostics: list[Diagnostic] = list(template_plan.diagnostics)
    blockers: list[str] = []
    relu_ops = tuple(
        op for op in template_plan.template_ops if op.role == "tile_op:relu"
    )
    store_ops = tuple(
        op for op in template_plan.template_ops if op.role == "tile_store"
    )
    finalize_source_ids = {
        op.provenance.primary_fiber_op_id
        for op in template_plan.template_ops
        if op.role == "accumulator_finalize"
    }
    relu_by_source_id = {
        op.provenance.primary_fiber_op_id: op
        for op in relu_ops
    }
    stores_by_relu_source_id: dict[str, list[TemplateOp]] = {
        source_id: []
        for source_id in relu_by_source_id
    }
    pre_relu_store_ops: list[TemplateOp] = []

    for store_op in store_ops:
        dependency_ids = set(store_op.provenance.dependency_fiber_op_ids)
        matched_relu_ids = sorted(dependency_ids & set(relu_by_source_id))
        for relu_source_id in matched_relu_ids:
            stores_by_relu_source_id[relu_source_id].append(store_op)
        if dependency_ids & finalize_source_ids and not matched_relu_ids:
            pre_relu_store_ops.append(store_op)

    if len(relu_ops) != expected_relu_template_count:
        blockers.append(
            "expected "
            f"{expected_relu_template_count} ReLU TemplateOps, got {len(relu_ops)}"
        )
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="unexpected_relu_template_count",
                subject_id="ExplicitReluSubtaskBindingReport",
                message=blockers[-1],
            )
        )

    if pre_relu_store_ops:
        blockers.append(
            "tile_store depends on accumulator_finalize without ReLU for "
            f"{len(pre_relu_store_ops)} stores"
        )
        diagnostics.extend(
            Diagnostic(
                severity="error",
                code="pre_relu_store_forbidden",
                subject_id=op.id,
                message="GEMM+ReLU store must consume explicit ReLU output",
            )
            for op in pre_relu_store_ops
        )

    bindings: list[ExplicitReluSubtaskBinding] = []
    concrete_relu_template_count = 0
    symbolic_relu_template_count = 0
    dtype_decision = _dtype_decision()
    zero_constant_policy = _zero_constant_policy(dtype_decision)
    exact_row_evidence = _exact_row_evidence(
        dtype_decision=dtype_decision,
        zero_constant_policy=zero_constant_policy,
    )

    for relu_index, relu_op in enumerate(
        sorted(relu_ops, key=lambda op: op.provenance.source_schedule_ordinal)
    ):
        diagnostics.extend(relu_op.diagnostics)
        if relu_op.template_status == "concrete_template":
            concrete_relu_template_count += 1
        elif relu_op.template_status == "symbolic_unresolved":
            symbolic_relu_template_count += 1
        else:
            blockers.append(
                f"ReLU TemplateOp {relu_op.id} has unsupported status "
                f"{relu_op.template_status}"
            )
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="unsupported_relu_template_status",
                    subject_id=relu_op.id,
                    message=blockers[-1],
                )
            )

        candidate_intents = tuple(
            intent
            for intent in relu_op.instruction_intents
            if intent.emits_instruction
        )
        source_opcode = candidate_intents[0].opcode if candidate_intents else None
        if not candidate_intents:
            blockers.append(f"ReLU TemplateOp {relu_op.id} lacks instruction intent")
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="relu_instruction_intent_missing",
                    subject_id=relu_op.id,
                    message=blockers[-1],
                )
            )
        elif source_opcode not in {"HMAX_OR_FMAX", "FMAX_OR_HMAX", "HMAX", "FMAX"}:
            blockers.append(
                f"ReLU TemplateOp {relu_op.id} has unexpected opcode {source_opcode}"
            )
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="relu_instruction_opcode_unexpected",
                    subject_id=relu_op.id,
                    message=blockers[-1],
                )
            )

        store_matches = stores_by_relu_source_id.get(
            relu_op.provenance.primary_fiber_op_id,
            [],
        )
        if len(store_matches) != 1:
            blockers.append(
                f"ReLU TemplateOp {relu_op.id} must feed exactly one tile_store, "
                f"got {len(store_matches)}"
            )
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="relu_store_dependency_not_one_to_one",
                    subject_id=relu_op.id,
                    message=blockers[-1],
                )
            )
        store_op = store_matches[0] if store_matches else None
        stream_id = _attr_str(relu_op, "stream_id")
        binding_seed = _binding_seed_for_relu(
            relu_op,
            template_index=relu_index,
            dtype_decision=dtype_decision,
            zero_constant_policy=zero_constant_policy,
        )
        store_lifetime = _store_lifetime_for_relu(
            relu_op,
            store_op=store_op,
        )
        bindings.append(
            ExplicitReluSubtaskBinding(
                id=f"explicit_relu_binding:{relu_index:04d}",
                relu_template_op_id=relu_op.id,
                store_template_op_id=None if store_op is None else store_op.id,
                source_schedule_step_id=relu_op.provenance.source_schedule_step_id,
                primary_fiber_op_id=relu_op.provenance.primary_fiber_op_id,
                store_primary_fiber_op_id=(
                    None if store_op is None else store_op.provenance.primary_fiber_op_id
                ),
                stream_id=stream_id,
                task_id=_task_id_from_stream_id(stream_id),
                source_template_status=relu_op.template_status,
                source_instruction_opcode=source_opcode,
                dtype_decision=dtype_decision,
                zero_constant_policy=zero_constant_policy,
                exact_row_evidence=exact_row_evidence,
                binding_seed=binding_seed,
                store_operand_lifetime=store_lifetime,
                attrs=(
                    ("subtask_slot", "subtask4_relu_explicit"),
                    ("store_dependency", "relu_output"),
                    (
                        "source_intent_statuses",
                        tuple(intent.intent_status for intent in candidate_intents),
                    ),
                ),
            )
        )

    evidence_requirements = _relu_evidence_requirements(
        relu_ops=relu_ops,
        concrete_relu_template_count=concrete_relu_template_count,
        symbolic_relu_template_count=symbolic_relu_template_count,
        store_dependency_count=sum(
            1 for binding in bindings if binding.store_template_op_id
        ),
        pre_relu_store_count=len(pre_relu_store_ops),
        dtype_decision=dtype_decision,
        zero_constant_policy=zero_constant_policy,
        exact_row_evidence=exact_row_evidence,
    )
    missing_evidence = tuple(
        requirement
        for requirement in evidence_requirements
        if requirement.status == "p0_blocked"
    )
    if bindings and missing_evidence:
        blocker = (
            "explicit ReLU subtask writer is not runnable until exact row-byte "
            "evidence closes: "
            + ", ".join(requirement.id for requirement in missing_evidence)
        )
        blockers.append(blocker)
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="explicit_relu_writer_inputs_missing",
                subject_id="ExplicitReluSubtaskBindingReport",
                message=blocker,
                evidence_refs=tuple(requirement.id for requirement in missing_evidence),
            )
        )

    if concrete_relu_template_count != expected_relu_template_count:
        blocker = (
            "explicit ReLU subtask rows are not runnable until the shortest "
            "evidence path closes: relu_dtype_selection, "
            "zero_constant_materialization, template_row_evidence, "
            "store_operand_lifetime"
        )
        blockers.append(blocker)
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="explicit_relu_templates_not_concrete",
                subject_id="ExplicitReluSubtaskBindingReport",
                message=blocker,
                evidence_refs=tuple(requirement.id for requirement in missing_evidence),
            )
        )

    binding_status: ReluBindingStatus = (
        "concrete_row_plan_candidate"
        if not blockers and concrete_relu_template_count == expected_relu_template_count
        else "fail_closed"
    )
    return ExplicitReluSubtaskBindingReport(
        profile_id=template_plan.profile_id,
        binding_status=binding_status,
        bindings=tuple(bindings),
        evidence_requirements=evidence_requirements,
        diagnostics=tuple(diagnostics),
        blockers=tuple(blockers),
    )


def summarize_explicit_relu_subtask_binding_report(
    report: ExplicitReluSubtaskBindingReport,
) -> dict[str, object]:
    """Return stable counts for focused ReLU binding checks."""

    diagnostic_severity_counts: dict[str, int] = {}
    source_template_status_counts: dict[str, int] = {}
    task_binding_counts: dict[int, int] = {}
    evidence_status_counts: dict[str, int] = {}
    p0_blocker_categories: dict[str, int] = {}
    closed_evidence_categories: dict[str, int] = {}
    seed_status_counts: dict[str, int] = {}
    seed_schema_counts: dict[str, int] = {}
    seed_expected_ops_counts: dict[str, int] = {}
    dtype_opcode_counts: dict[str, int] = {}
    zero_policy_status_counts: dict[str, int] = {}
    exact_row_status_counts: dict[str, int] = {}
    exact_selector_status_counts: dict[str, int] = {}
    exact_missing_writer_input_counts: dict[str, int] = {}
    row_byte_proof_status_counts: dict[str, int] = {}
    row_byte_proof_requirement_status_counts: dict[str, int] = {}
    row_byte_proof_missing_artifact_counts: dict[str, int] = {}
    store_lifetime_status_counts: dict[str, int] = {}
    store_dependency_count = 0
    pre_relu_store_forbidden_count = 0
    concrete_relu_template_count = 0
    symbolic_relu_template_count = 0
    source_op_ids: set[str] = set()
    store_op_ids: set[str] = set()

    for diagnostic in report.diagnostics:
        diagnostic_severity_counts[diagnostic.severity] = (
            diagnostic_severity_counts.get(diagnostic.severity, 0) + 1
        )
        if diagnostic.code == "pre_relu_store_forbidden":
            pre_relu_store_forbidden_count += 1

    for binding in report.bindings:
        source_template_status_counts[binding.source_template_status] = (
            source_template_status_counts.get(binding.source_template_status, 0) + 1
        )
        if binding.source_template_status == "concrete_template":
            concrete_relu_template_count += 1
        if binding.source_template_status == "symbolic_unresolved":
            symbolic_relu_template_count += 1
        if binding.task_id is not None:
            task_binding_counts[binding.task_id] = (
                task_binding_counts.get(binding.task_id, 0) + 1
            )
        source_op_ids.add(binding.primary_fiber_op_id)
        if binding.store_template_op_id is not None:
            store_dependency_count += 1
        if binding.store_primary_fiber_op_id is not None:
            store_op_ids.add(binding.store_primary_fiber_op_id)
        seed_status_counts[binding.binding_seed.seed_status] = (
            seed_status_counts.get(binding.binding_seed.seed_status, 0) + 1
        )
        seed_schema_counts[binding.binding_seed.seed_schema] = (
            seed_schema_counts.get(binding.binding_seed.seed_schema, 0) + 1
        )
        expected_ops_key = ",".join(binding.binding_seed.expected_ops)
        seed_expected_ops_counts[expected_ops_key] = (
            seed_expected_ops_counts.get(expected_ops_key, 0) + 1
        )
        if binding.dtype_decision.recommended_opcode is not None:
            dtype_opcode_counts[binding.dtype_decision.recommended_opcode] = (
                dtype_opcode_counts.get(binding.dtype_decision.recommended_opcode, 0) + 1
            )
        zero_policy_status_counts[binding.zero_constant_policy.status] = (
            zero_policy_status_counts.get(binding.zero_constant_policy.status, 0) + 1
        )
        exact_row_status_counts[binding.exact_row_evidence.status] = (
            exact_row_status_counts.get(binding.exact_row_evidence.status, 0) + 1
        )
        exact_selector_status_counts[binding.exact_row_evidence.selector_status] = (
            exact_selector_status_counts.get(
                binding.exact_row_evidence.selector_status,
                0,
            )
            + 1
        )
        row_byte_proof_status = binding.exact_row_evidence.row_byte_proof_plan.status
        row_byte_proof_status_counts[row_byte_proof_status] = (
            row_byte_proof_status_counts.get(row_byte_proof_status, 0) + 1
        )
        for requirement in (
            binding.exact_row_evidence.row_byte_proof_plan.proof_requirements
        ):
            row_byte_proof_requirement_status_counts[requirement.status] = (
                row_byte_proof_requirement_status_counts.get(requirement.status, 0)
                + 1
            )
        for artifact in binding.exact_row_evidence.row_byte_proof_plan.missing_artifacts:
            row_byte_proof_missing_artifact_counts[artifact] = (
                row_byte_proof_missing_artifact_counts.get(artifact, 0) + 1
            )
        for missing_input in binding.exact_row_evidence.missing_writer_inputs:
            exact_missing_writer_input_counts[missing_input] = (
                exact_missing_writer_input_counts.get(missing_input, 0) + 1
            )
        store_lifetime_status_counts[binding.store_operand_lifetime.status] = (
            store_lifetime_status_counts.get(binding.store_operand_lifetime.status, 0) + 1
        )

    for requirement in report.evidence_requirements:
        evidence_status_counts[requirement.status] = (
            evidence_status_counts.get(requirement.status, 0) + 1
        )
        if requirement.status == "p0_blocked":
            p0_blocker_categories[requirement.category] = (
                p0_blocker_categories.get(requirement.category, 0) + 1
            )
        if requirement.status == "closed":
            closed_evidence_categories[requirement.category] = (
                closed_evidence_categories.get(requirement.category, 0) + 1
            )

    return {
        "profile_id": report.profile_id,
        "binding_status": report.binding_status,
        "operator": EXPLICIT_RELU_OPERATOR,
        "relu_layout": EXPLICIT_RELU_LAYOUT,
        "relu_op": EXPLICIT_RELU_OP,
        "expected_relu_template_count": EXPECTED_RELU_TEMPLATE_COUNT,
        "binding_count": len(report.bindings),
        "unique_relu_source_fiber_op_count": len(source_op_ids),
        "unique_store_source_fiber_op_count": len(store_op_ids),
        "concrete_relu_template_count": concrete_relu_template_count,
        "symbolic_relu_template_count": symbolic_relu_template_count,
        "source_template_status_counts": dict(
            sorted(source_template_status_counts.items())
        ),
        "task_binding_counts": dict(sorted(task_binding_counts.items())),
        "store_dependency_count": store_dependency_count,
        "pre_relu_store_forbidden": True,
        "pre_relu_store_forbidden_count": pre_relu_store_forbidden_count,
        "evidence_status_counts": dict(sorted(evidence_status_counts.items())),
        "closed_evidence_categories": dict(
            sorted(closed_evidence_categories.items())
        ),
        "p0_blocker_categories": dict(
            sorted(p0_blocker_categories.items())
        ),
        "p0_blocker_ids": [
            requirement.id
            for requirement in report.evidence_requirements
            if requirement.status == "p0_blocked"
        ],
        "closed_evidence_ids": [
            requirement.id
            for requirement in report.evidence_requirements
            if requirement.status == "closed"
        ],
        "binding_seed_status_counts": dict(sorted(seed_status_counts.items())),
        "binding_seed_schema_counts": dict(sorted(seed_schema_counts.items())),
        "binding_seed_expected_ops_counts": dict(
            sorted(seed_expected_ops_counts.items())
        ),
        "recommended_relu_opcode_counts": dict(sorted(dtype_opcode_counts.items())),
        "zero_policy_status_counts": dict(sorted(zero_policy_status_counts.items())),
        "exact_row_evidence_status_counts": dict(
            sorted(exact_row_status_counts.items())
        ),
        "exact_row_selector_status_counts": dict(
            sorted(exact_selector_status_counts.items())
        ),
        "row_byte_proof_plan_status_counts": dict(
            sorted(row_byte_proof_status_counts.items())
        ),
        "row_byte_proof_requirement_status_counts": dict(
            sorted(row_byte_proof_requirement_status_counts.items())
        ),
        "row_byte_proof_missing_artifact_counts": dict(
            sorted(row_byte_proof_missing_artifact_counts.items())
        ),
        "exact_row_missing_writer_input_counts": dict(
            sorted(exact_missing_writer_input_counts.items())
        ),
        "store_lifetime_status_counts": dict(
            sorted(store_lifetime_status_counts.items())
        ),
        "store_input_counts": {
            "relu_output": sum(
                1
                for binding in report.bindings
                if binding.store_input == "relu_output"
            ),
        },
        "diagnostic_severity_counts": dict(
            sorted(diagnostic_severity_counts.items())
        ),
        "diagnostic_count": len(report.diagnostics),
        "blocker_count": len(report.blockers),
        "blockers": list(report.blockers),
    }


def _relu_evidence_requirements(
    *,
    relu_ops: tuple[TemplateOp, ...],
    concrete_relu_template_count: int,
    symbolic_relu_template_count: int,
    store_dependency_count: int,
    pre_relu_store_count: int,
    dtype_decision: ReluDtypeDecision,
    zero_constant_policy: ReluZeroConstantPolicy,
    exact_row_evidence: ReluExactRowEvidence,
) -> tuple[ReluEvidenceRequirement, ...]:
    return (
        ReluEvidenceRequirement(
            id="relu_capability:fmax_fp32",
            status="available",
            category="hmax_fmax_dtype",
            requirement="FMAX implements fp32 lane-wise max over 128 lanes",
            evidence_refs=(
                "docs/architecture/instruction-set/dfu3500-simd/"
                "instruction_cards.md:FMAX",
                "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:FMAX",
                "compiler/gpdpu_compiler/validation/dfu3500_package_checks/"
                "opcode_conformance_check.py",
            ),
            attrs=(
                ("mnemonic", "FMAX"),
                ("opcode", "0x027"),
                ("lane_dtype", "fp32"),
                ("lane_count", 128),
                ("unit_inst_type", "0x2"),
                ("latency", 72),
                ("src_count", 2),
            ),
        ),
        ReluEvidenceRequirement(
            id="relu_capability:hmax_fp16",
            status="available",
            category="hmax_fmax_dtype",
            requirement="HMAX implements fp16 lane-wise max over 256 lanes",
            evidence_refs=(
                "docs/architecture/instruction-set/dfu3500-simd/"
                "instruction_cards.md:HMAX",
                "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:HMAX",
                "compiler/gpdpu_compiler/validation/dfu3500_package_checks/"
                "opcode_conformance_check.py",
            ),
            attrs=(
                ("mnemonic", "HMAX"),
                ("opcode", "0x053"),
                ("lane_dtype", "fp16"),
                ("lane_count", 256),
                ("unit_inst_type", "0x2"),
                ("latency", 72),
                ("src_count", 2),
            ),
        ),
        ReluEvidenceRequirement(
            id="relu_closed:dtype_selection",
            status=dtype_decision.status,
            category="hmax_fmax_dtype",
            requirement=(
                "bind each ReLU TemplateOp to exact HMAX or FMAX from source/output "
                "fragment dtype"
            ),
            evidence_refs=(
                "docs/compiler/binary_packaging/research_notes/enhancements/"
                "2026-06-19_relu_tile_op_vendor_evidence.md",
            ),
            missing_reason=dtype_decision.blocker,
            attrs=(
                ("recommended_opcode", dtype_decision.recommended_opcode),
                ("lane_dtype", dtype_decision.lane_dtype),
                ("relu_template_op_count", len(relu_ops)),
                ("symbolic_relu_template_count", symbolic_relu_template_count),
            ),
        ),
        ReluEvidenceRequirement(
            id="relu_p0:zero_constant_materialization",
            status=zero_constant_policy.status,
            category="zero_constant_materialization",
            requirement=(
                "prove the zero operand for ReLU is materialized in the active "
                "subtask via IMM/FIMM or an equivalent constant template"
            ),
            evidence_refs=(
                "docs/architecture/instruction-set/dfu3500-simd/docx/"
                "instruction_sections/IMM.md",
                "docs/compiler/binary_packaging/research_notes/enhancements/"
                "2026-06-19_relu_tile_op_vendor_evidence.md",
                "docs/compiler/binary_packaging/research_notes/enhancements/"
                "rfc-core-functional-template-binding.md",
            ),
            missing_reason=zero_constant_policy.blocker,
        attrs=(
            ("policy", zero_constant_policy.policy),
                (
                    "materialization_opcode",
                    zero_constant_policy.materialization_opcode,
                ),
                ("operand_tag", zero_constant_policy.operand_tag),
                ("operand_index", zero_constant_policy.operand_index),
            ),
        ),
        ReluEvidenceRequirement(
            id="relu_p0:template_row_evidence",
            status=exact_row_evidence.status,
            category="template_row_evidence",
            requirement=(
                "attach 64 active concrete ReLU template rows or an explicit "
                "local elementwise tile-op template family"
            ),
            evidence_refs=(
                "docs/compiler/binary_packaging/README.md",
                "docs/architecture/instruction-set/dfu3500-simd/"
                "MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md",
                "compiler/gpdpu_compiler/decoder/dfu3500_isa.py",
                "compiler/gpdpu_compiler/core/program_legacy_inst.py:"
                "legacy_maximum_scalar_template",
            ),
            missing_reason=exact_row_evidence.blocker,
            attrs=(
                (
                    "expected_concrete_relu_template_count",
                    EXPECTED_RELU_TEMPLATE_COUNT,
                ),
                ("concrete_relu_template_count", concrete_relu_template_count),
                (
                    "missing_writer_inputs",
                    exact_row_evidence.missing_writer_inputs,
                ),
                (
                    "selector_status",
                    exact_row_evidence.selector_status,
                ),
                (
                    "legacy_gemm_hmax_rows",
                    exact_row_evidence.legacy_gemm_hmax_rows,
                ),
                (
                    "legacy_gemm_fmax_rows",
                    exact_row_evidence.legacy_gemm_fmax_rows,
                ),
                (
                    "functional_probe_fmax_rows",
                    exact_row_evidence.functional_probe_fmax_rows,
                ),
            ),
        ),
        ReluEvidenceRequirement(
            id="relu_closed:store_operand_lifetime",
            status=(
                "closed"
                if store_dependency_count == len(relu_ops) and pre_relu_store_count == 0
                else "p0_blocked"
            ),
            category="store_operand_lifetime",
            requirement=(
                "prove store consumes the ReLU output operand after HMAX/FMAX and "
                "keeps the operand live through the STD/HSTT store template"
            ),
            evidence_refs=(
                "docs/architecture/instruction-set/dfu3500-simd/"
                "MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md",
                "docs/compiler/binary_packaging/README.md",
            ),
            missing_reason=(
                None
                if store_dependency_count == len(relu_ops) and pre_relu_store_count == 0
                else "store dependency graph does not prove every store consumes ReLU output"
            ),
            attrs=(
                ("store_dependency_count", store_dependency_count),
                ("pre_relu_store_count", pre_relu_store_count),
                ("required_store_input", "relu_output"),
                ("forbidden_store_input", "pre_relu_accumulator"),
            ),
        ),
    )


def _dtype_decision() -> ReluDtypeDecision:
    output_dtype = DFU3500_GEMM_REGIONS["C"].dtype
    default_tile_dtype = str(DFU3500_DEFAULT_TILE["dtype"])
    if output_dtype == "fp16" and default_tile_dtype == "fp16":
        return ReluDtypeDecision(
            status="closed",
            recommended_opcode="HMAX",
            lane_dtype="fp16",
            source=(
                "DFU3500_GEMM_REGIONS['C'].dtype and "
                "DFU3500_DEFAULT_TILE['dtype']"
            ),
            evidence_refs=(
                "compiler/gpdpu_compiler/core/dfu3500/__init__.py:DFU3500_GEMM_REGIONS",
                "compiler/gpdpu_compiler/core/dfu3500/__init__.py:DFU3500_DEFAULT_TILE",
                "docs/architecture/instruction-set/dfu3500-simd/instruction_cards.md:HMAX",
            ),
        )
    if output_dtype == "fp32" or default_tile_dtype == "fp32":
        return ReluDtypeDecision(
            status="closed",
            recommended_opcode="FMAX",
            lane_dtype="fp32",
            source=(
                "DFU3500_GEMM_REGIONS['C'].dtype or "
                "DFU3500_DEFAULT_TILE['dtype']"
            ),
            evidence_refs=(
                "compiler/gpdpu_compiler/core/dfu3500/__init__.py:DFU3500_GEMM_REGIONS",
                "compiler/gpdpu_compiler/core/dfu3500/__init__.py:DFU3500_DEFAULT_TILE",
                "docs/architecture/instruction-set/dfu3500-simd/instruction_cards.md:FMAX",
            ),
        )
    return ReluDtypeDecision(
        status="p0_blocked",
        recommended_opcode=None,
        lane_dtype=None,
        source="DFU3500 GEMM dtype evidence",
        evidence_refs=(
            "compiler/gpdpu_compiler/core/dfu3500/__init__.py:DFU3500_GEMM_REGIONS",
            "compiler/gpdpu_compiler/core/dfu3500/__init__.py:DFU3500_DEFAULT_TILE",
        ),
        blocker=(
            "GEMM output/default tile dtype does not select fp16 HMAX or fp32 FMAX"
        ),
    )


def _zero_constant_policy(dtype_decision: ReluDtypeDecision) -> ReluZeroConstantPolicy:
    materialization_opcode = "IMM" if dtype_decision.recommended_opcode else None
    return ReluZeroConstantPolicy(
        status="available" if materialization_opcode is not None else "p0_blocked",
        policy="imm_broadcast_zero_candidate",
        zero_value="0x00000000",
        materialization_opcode=materialization_opcode,
        operand_tag="ZERO_relu",
        operand_index=None,
        blocker=(
            "ZERO_relu requires an exact active IMM/FIMM/zero-register row and "
            "operand index before ReLU can become runnable"
        ),
    )


def _exact_row_evidence(
    *,
    dtype_decision: ReluDtypeDecision,
    zero_constant_policy: ReluZeroConstantPolicy,
) -> ReluExactRowEvidence:
    required_writer_inputs = (
        ACTIVE_RELU_SELECTOR_PROOF,
        *ACTIVE_RELU_SOURCE_ARTIFACTS,
        ACTIVE_RELU_RUNTIME_TRACE_ARTIFACT,
        "candidate_relu_zero_constant_row_selector",
        "candidate_relu_max_row_selector",
        "candidate_relu_input_operand_binding",
        "candidate_relu_zero_operand_index",
        "candidate_relu_output_operand_binding",
        "candidate_relu_local_order",
        "candidate_raw_inst_t_row_bytes",
        "candidate_raw_template_row_sha256",
    )
    missing_writer_inputs = (
        ACTIVE_RELU_SELECTOR_PROOF,
        ACTIVE_RELU_RUNTIME_TRACE_ARTIFACT,
    )
    row_byte_proof_plan = _row_byte_proof_plan(
        dtype_decision=dtype_decision,
        zero_constant_policy=zero_constant_policy,
        required_writer_inputs=required_writer_inputs,
    )
    blocker = (
        "DFU3500 docs source a standalone HMAX row shape and the explicit "
        "vendor-subtask4-shaped IMM-zero + HMAX materializer closes candidate "
        "row bytes/hashes; B-line explicit relu_tile activation now supplies "
        "a source-backed subtask4 activation candidate and local IMM/HMAX "
        "decode skeleton, but runtime selector trace is still missing before "
        "candidate bytes may be claimed as active runtime rows"
    )
    return ReluExactRowEvidence(
        status="p0_blocked",
        selector_status=(
            "candidate_hmax_materializer_bline_activation_closed_"
            "runtime_selector_missing"
        ),
        recommended_max_opcode=dtype_decision.recommended_opcode,
        zero_opcode=zero_constant_policy.materialization_opcode,
        legacy_gemm_hmax_rows=0,
        legacy_gemm_fmax_rows=0,
        legacy_gemm_imm_rows=128,
        doc_hmax_shape_rows=1,
        functional_probe_fmax_rows=16,
        functional_probe_imm_rows=16,
        evidence_refs=(
            "simict3500final/.../gemm_template_fusion/task*/subtask1/template/*.csv:IMM",
            "compiler/tools/inspect_legacy_gemm_templates.py:task*/subtask1 IMM",
            "docs/architecture/instruction-set/dfu3500-simd/docx/media_ocr/raw/image4.txt:HMAX",
            "docs/architecture/instruction-set/dfu3500-simd/docx/media_ocr/media_ocr.md:image4",
            "docs/architecture/instruction-set/dfu3500-simd/instruction_cards.md:HMAX",
            "compiler/tools/check_core_functional_probe_report.py:functional_maximum_single_app",
            "compiler/gpdpu_compiler/core/program_legacy_inst.py:legacy_maximum_scalar_template",
            "compiler/gpdpu_compiler/core/program_legacy_inst.py:legacy_relu_hmax_zero_template",
            "compiler/gpdpu_compiler/core/program_legacy_inst.py:LEGACY_OPS.HMAX",
            "simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/"
            "gemm_template_fusion/task*/subtask4/template/new_temp.cpp:RELU",
            "simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/"
            "gemm_template_fusion/gpdpu_tensor/task_main.cpp:SUBTASK_COUNT",
            "simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/"
            "gemm_template_fusion/csv_generate/conf_PEmap.h:Secondary_Fusion_Array",
            "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:HMAX",
        ),
        required_writer_inputs=required_writer_inputs,
        missing_writer_inputs=missing_writer_inputs,
        row_byte_proof_plan=row_byte_proof_plan,
        blocker=blocker,
    )


def _row_byte_proof_plan(
    *,
    dtype_decision: ReluDtypeDecision,
    zero_constant_policy: ReluZeroConstantPolicy,
    required_writer_inputs: tuple[str, ...],
) -> ReluRowByteProofPlan:
    selected_opcode = dtype_decision.recommended_opcode
    zero_opcode = zero_constant_policy.materialization_opcode
    materializer_candidate = (
        _hmax_materializer_candidate()
        if selected_opcode == "HMAX" and zero_opcode == "IMM"
        else None
    )
    missing_artifacts = (
        ACTIVE_RELU_SELECTOR_PROOF,
        ACTIVE_RELU_RUNTIME_TRACE_ARTIFACT,
    )
    return ReluRowByteProofPlan(
        status=(
            "candidate_hmax_materializer_bline_activation_closed_"
            "runtime_selector_missing"
        ),
        selected_max_opcode=selected_opcode,
        zero_opcode=zero_opcode,
        row_family="imm_zero_plus_hmax_relu_tile",
        materializer_candidate=materializer_candidate,
        row_bytes_claim=False,
        raw_template_row_sha256_claim=False,
        proof_requirements=(
            ReluRowByteProofRequirement(
                id="relu_row_proof:hmax_opcode_metadata",
                status=(
                    "closed" if selected_opcode == "HMAX" else "p0_blocked"
                ),
                category="opcode_metadata",
                requirement=(
                    "HMAX opcode/latency/unit/source operand count are source-backed "
                    "for fp16 ReLU"
                ),
                evidence_refs=(
                    "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:HMAX",
                    "docs/architecture/instruction-set/dfu3500-simd/instruction_cards.md:HMAX",
                ),
                missing_reason=(
                    None
                    if selected_opcode == "HMAX"
                    else "current dtype does not select HMAX"
                ),
                attrs=(
                    ("opcode", "0x053"),
                    ("unit_inst_type", "0x2"),
                    ("latency", 72),
                    ("src_count", 2),
                    ("lane_dtype", "fp16"),
                ),
            ),
            ReluRowByteProofRequirement(
                id="relu_row_proof:doc_hmax_row_shape",
                status=(
                    "closed" if selected_opcode == "HMAX" else "p0_blocked"
                ),
                category="row_selector",
                requirement=(
                    "source a standalone HMAX row shape and opcode family usable "
                    "as a ReLU selector candidate"
                ),
                evidence_refs=(
                    "docs/architecture/instruction-set/dfu3500-simd/docx/media_ocr/raw/image4.txt",
                    "docs/architecture/instruction-set/dfu3500-simd/docx/media_ocr/media_ocr.md:image4",
                    "docs/architecture/instruction-set/dfu3500-simd/instruction_cards.md:HMAX",
                    "compiler/gpdpu_compiler/core/program_legacy_inst.py:LEGACY_OPS.HMAX",
                ),
                missing_reason=(
                    None
                    if selected_opcode == "HMAX"
                    else "current dtype does not select HMAX"
                ),
                attrs=(
                    ("doc_row", "HMAX,HMAX15,A1,A2,B4,,,0"),
                    ("selector_kind", "doc_shape_candidate_not_active_template"),
                    ("doc_hmax_shape_rows", 1),
                    ("active_selector_claim", False),
                ),
            ),
            ReluRowByteProofRequirement(
                id="relu_row_proof:vendor_subtask4_generator_source",
                status="available",
                category="row_selector",
                requirement=(
                    "vendor GEMM secondary-fusion subtask4 generator emits "
                    "IMM ZERO_relu followed by HMAX ZERO_relu,input,output"
                ),
                evidence_refs=(
                    "simict3500final/gpdpu/users/risc_nn_riscv/testcase/"
                    "application/gemm_template_fusion/task0/subtask4/template/"
                    "new_temp.cpp:OpType::RELU",
                    "simict3500final/gpdpu/users/risc_nn_riscv/testcase/"
                    "application/gemm_template_fusion/task*/subtask4/template/"
                    "new_temp.cpp",
                ),
                attrs=(
                    ("generator_status", "source_available_default_inactive"),
                    ("expected_ops", ("IMM", "HMAX")),
                    ("hmax_src0_role", "zero"),
                    ("hmax_src1_role", "input"),
                    ("hmax_dst_role", "relu_output"),
                    ("active_selector_claim", False),
                ),
            ),
            ReluRowByteProofRequirement(
                id="relu_row_proof:active_template_family_selector",
                status="p0_blocked",
                category="row_selector",
                requirement=(
                    "prove the explicit IMM-zero + HMAX candidate family is the "
                    "active DFU3500 ReLU tile template family for each relu_tile"
                ),
                evidence_refs=(
                    "compiler/tools/inspect_legacy_gemm_templates.py",
                    "compiler/gpdpu_compiler/core/program_legacy_inst.py:LegacyCsvEncoder",
                    "compiler/gpdpu_compiler/core/program_legacy_inst.py:"
                    "legacy_relu_hmax_zero_template",
                    "docs/architecture/instruction-set/dfu3500-simd/docx/media_ocr/raw/image4.txt",
                    "simict3500final/gpdpu/users/risc_nn_riscv/testcase/"
                    "application/gemm_template_fusion/gpdpu_tensor/Makefile:"
                    "SUBTASK_COUNT",
                    "simict3500final/gpdpu/users/risc_nn_riscv/testcase/"
                    "application/gemm_template_fusion/gpdpu_tensor/task_main.cpp:"
                    "do_task*_subtask4",
                    "simict3500final/gpdpu/users/risc_nn_riscv/testcase/"
                    "application/gemm_template_fusion/csv_generate/conf_PEmap.h:"
                    "Secondary_Fusion_Array",
                ),
                missing_reason=(
                    "candidate IMM-zero + HMAX row bytes, B-line explicit "
                    "subtask4 activation, source CSV shape, and local decode "
                    "skeleton are closed, but no runtime selector trace proves "
                    "the candidate family is active in the runnable "
                    "GEMM+ReLU SimICT/template path"
                ),
                attrs=(
                    ("legacy_gemm_hmax_rows", 0),
                    ("legacy_gemm_fmax_rows", 0),
                    ("doc_hmax_shape_rows", 1),
                    ("vendor_subtask4_generator_source", "available"),
                    ("observed_default_subtask_count", 3),
                    ("observed_secondary_fusion_array", "empty"),
                    ("bline_explicit_relu_task_activation", "closed"),
                    ("generated_csv_candidate_for_customer_shape", "closed"),
                    ("local_imm_hmax_decode_roundtrip", "closed"),
                    (
                        "activation_guards",
                        (
                            "SUBTASK_COUNT == 4",
                            "Secondary_Fusion_Array non-empty",
                            "or explicit B-line relu_tile task activation",
                        ),
                    ),
                    ("required_opcode", selected_opcode),
                    (
                        "required_artifact",
                        ACTIVE_RELU_SELECTOR_PROOF,
                    ),
                    (
                        "required_source_artifacts",
                        ACTIVE_RELU_SOURCE_ARTIFACTS,
                    ),
                    ("candidate_bytes_available", materializer_candidate is not None),
                    (
                        "remaining_runtime_artifact",
                        ACTIVE_RELU_RUNTIME_TRACE_ARTIFACT,
                    ),
                    ("active_selector_claim", False),
                ),
            ),
            ReluRowByteProofRequirement(
                id="relu_row_proof:bline_explicit_subtask4_activation_record",
                status=(
                    "closed" if materializer_candidate is not None else "p0_blocked"
                ),
                category="row_selector",
                requirement=(
                    "record the B-line explicit relu_tile activation equivalent "
                    "to legacy SUBTASK_COUNT==4 subtask4 enablement without "
                    "placing ReLU inside GEMM"
                ),
                evidence_refs=(
                    "compiler/gpdpu_compiler/core/stream_compiler/relu_fiber_chain.py:"
                    "gemm_tile->relu_tile->store_tile",
                    "simict3500final/gpdpu/users/risc_nn_riscv/testcase/"
                    "application/gemm_template_fusion_bash_semantics_probe/"
                    "gpdpu_tensor/task_main.cpp:SUBTASK_COUNT==4",
                    "simict3500final/gpdpu/users/risc_nn_riscv/testcase/"
                    "application/gemm_template_fusion_bash_semantics_probe/"
                    "gpdpu_tensor/task*/subtask4/template/new_temp.cpp:OpType::RELU",
                ),
                missing_reason=(
                    None
                    if materializer_candidate is not None
                    else "explicit ReLU materializer candidate missing"
                ),
                attrs=(
                    ("activation_kind", "bline_explicit_relu_tile_task"),
                    ("subtask_slot", "subtask4_relu_explicit"),
                    ("forbidden", "gemm_fused_relu_or_epilogue"),
                    (
                        "remaining_runtime_artifact",
                        ACTIVE_RELU_RUNTIME_TRACE_ARTIFACT,
                    ),
                ),
            ),
            ReluRowByteProofRequirement(
                id="relu_row_proof:local_imm_hmax_decode_roundtrip",
                status=(
                    "closed" if materializer_candidate is not None else "p0_blocked"
                ),
                category="raw_inst_t_bytes",
                requirement=(
                    "pack the candidate IMM/HMAX rows and locally decode opcode, "
                    "operand indexes, and local order back from inst_t bytes"
                ),
                evidence_refs=(
                    "compiler/gpdpu_compiler/core/program_legacy_inst.py:"
                    "decode_legacy_inst_skeleton",
                    "compiler/gpdpu_compiler/core/program_legacy_inst.py:"
                    "legacy_relu_hmax_zero_template",
                ),
                missing_reason=(
                    None
                    if materializer_candidate is not None
                    else "candidate row bytes missing"
                ),
                attrs=(
                    (
                        "decoded_ops",
                        ()
                        if materializer_candidate is None
                        else materializer_candidate.activation_record.decoded_ops,
                    ),
                    (
                        "runtime_selector_trace_status",
                        "p0_blocked"
                        if materializer_candidate is not None
                        else "missing_candidate",
                    ),
                ),
            ),
            ReluRowByteProofRequirement(
                id="relu_row_proof:explicit_hmax_materializer_candidate",
                status=(
                    "closed" if materializer_candidate is not None else "p0_blocked"
                ),
                category="row_selector",
                requirement=(
                    "construct explicit IMM-zero + HMAX candidate rows with "
                    "operand indexes, local_order, packed bytes, and raw hashes"
                ),
                evidence_refs=(
                    "compiler/gpdpu_compiler/core/program_legacy_inst.py:"
                    "legacy_relu_hmax_zero_template",
                    "compiler/gpdpu_compiler/core/program_legacy_inst.py:"
                    "pack_legacy_inst",
                ),
                missing_reason=(
                    None
                    if materializer_candidate is not None
                    else "selected ReLU dtype/opcode cannot use HMAX materializer"
                ),
                attrs=(
                    (
                        "selector_kind",
                        None
                        if materializer_candidate is None
                        else materializer_candidate.selector_kind,
                    ),
                    (
                        "candidate_row_count",
                        0 if materializer_candidate is None else materializer_candidate.row_count,
                    ),
                    (
                        "candidate_raw_inst_t_byte_count",
                        0
                        if materializer_candidate is None
                        else materializer_candidate.raw_inst_t_byte_count,
                    ),
                    (
                        "candidate_row_bytes_claim",
                        False
                        if materializer_candidate is None
                        else materializer_candidate.candidate_row_bytes_claim,
                    ),
                    (
                        "candidate_raw_template_row_sha256_claim",
                        False
                        if materializer_candidate is None
                        else materializer_candidate.candidate_raw_template_row_sha256_claim,
                    ),
                    ("active_selector_claim", False),
                ),
            ),
            ReluRowByteProofRequirement(
                id="relu_row_proof:zero_imm_metadata",
                status=zero_constant_policy.status,
                category="zero_constant_materialization",
                requirement="IMM can materialize the zero operand tag for ReLU",
                evidence_refs=(
                    "docs/architecture/instruction-set/dfu3500-simd/instruction_cards.md:IMM",
                    "compiler/gpdpu_compiler/decoder/dfu3500_isa.py:IMM",
                ),
                missing_reason=zero_constant_policy.blocker,
                attrs=(
                    ("zero_opcode", zero_opcode),
                    ("zero_value", zero_constant_policy.zero_value),
                    ("operand_tag", zero_constant_policy.operand_tag),
                ),
            ),
            ReluRowByteProofRequirement(
                id="relu_row_proof:zero_imm_selector",
                status=(
                    "closed" if materializer_candidate is not None else "p0_blocked"
                ),
                category="zero_constant_materialization",
                requirement=(
                    "construct the IMM zero candidate row and operand index consumed "
                    "by HMAX"
                ),
                evidence_refs=(
                    "compiler/gpdpu_compiler/core/program_legacy_inst.py:"
                    "legacy_relu_hmax_zero_template",
                ),
                missing_reason=(
                    None
                    if materializer_candidate is not None
                    else "zero IMM candidate could not be constructed"
                ),
                attrs=(
                    (
                        "zero_operand_index",
                        None
                        if materializer_candidate is None
                        else materializer_candidate.zero_operand_index,
                    ),
                    ("active_selector_claim", False),
                ),
            ),
            ReluRowByteProofRequirement(
                id="relu_row_proof:operand_binding",
                status=(
                    "closed" if materializer_candidate is not None else "p0_blocked"
                ),
                category="operand_binding",
                requirement=(
                    "bind HMAX src0=gemm_tile output, src1=zero operand, "
                    "dst=relu output consumed by store_tile"
                ),
                missing_reason=(
                    None
                    if materializer_candidate is not None
                    else "ReLU TemplateOps do not yet assign DFU operand indexes/local_order"
                ),
                attrs=(
                    ("required_inputs", required_writer_inputs),
                    ("store_input", "relu_output"),
                    (
                        "input_operand_index",
                        None
                        if materializer_candidate is None
                        else materializer_candidate.input_operand_index,
                    ),
                    (
                        "zero_operand_index",
                        None
                        if materializer_candidate is None
                        else materializer_candidate.zero_operand_index,
                    ),
                    (
                        "output_operand_index",
                        None
                        if materializer_candidate is None
                        else materializer_candidate.output_operand_index,
                    ),
                    (
                        "local_order",
                        ()
                        if materializer_candidate is None
                        else materializer_candidate.local_order,
                    ),
                    ("active_selector_claim", False),
                ),
            ),
            ReluRowByteProofRequirement(
                id="relu_row_proof:raw_bytes_hash",
                status=(
                    "closed" if materializer_candidate is not None else "p0_blocked"
                ),
                category="raw_inst_t_bytes",
                requirement=(
                    "pack candidate IMM-zero and HMAX rows into vendor inst_t bytes "
                    "and hash the raw byte payload without claiming runtime readiness"
                ),
                evidence_refs=(
                    "compiler/gpdpu_compiler/core/program_legacy_inst.py:pack_legacy_inst",
                ),
                missing_reason=(
                    None
                    if materializer_candidate is not None
                    else "raw bytes cannot be emitted until selector and operand binding close"
                ),
                attrs=(
                    ("row_bytes_claim", False),
                    ("raw_template_row_sha256_claim", False),
                    (
                        "candidate_row_bytes_claim",
                        False
                        if materializer_candidate is None
                        else materializer_candidate.candidate_row_bytes_claim,
                    ),
                    (
                        "candidate_raw_template_row_sha256_claim",
                        False
                        if materializer_candidate is None
                        else materializer_candidate.candidate_raw_template_row_sha256_claim,
                    ),
                    (
                        "candidate_raw_template_row_sha256",
                        None
                        if materializer_candidate is None
                        else materializer_candidate.raw_template_row_sha256,
                    ),
                    (
                        "candidate_raw_inst_t_byte_count",
                        0
                        if materializer_candidate is None
                        else materializer_candidate.raw_inst_t_byte_count,
                    ),
                ),
            ),
        ),
        required_artifacts=(
            ACTIVE_RELU_SELECTOR_PROOF,
            *ACTIVE_RELU_SOURCE_ARTIFACTS,
            ACTIVE_RELU_RUNTIME_TRACE_ARTIFACT,
            "candidate_relu_zero_imm_selector_report",
            "candidate_relu_operand_binding_report",
            "candidate_relu_local_order_report",
            "candidate_relu_raw_inst_t_bytes",
            "candidate_relu_raw_template_row_sha256",
        ),
        missing_artifacts=missing_artifacts,
    )


def _hmax_materializer_candidate() -> ReluHmaxMaterializerCandidate:
    insts = legacy_relu_hmax_zero_template()
    if len(insts) != 2:
        raise ValueError("ReLU HMAX materializer must produce exactly two rows")
    row_bytes = tuple(pack_legacy_inst(inst) for inst in insts)
    payload = b"".join(row_bytes)
    hmax_inst = insts[1]
    activation_record = _subtask4_activation_record(insts=insts, row_bytes=row_bytes)
    return ReluHmaxMaterializerCandidate(
        status=(
            "candidate_bytes_and_bline_activation_closed_"
            "runtime_selector_missing"
        ),
        selector_kind="vendor_subtask4_hmax_zero_materializer_candidate_v1",
        expected_ops=tuple(inst.op_name for inst in insts),
        row_count=len(insts),
        input_operand_index=hmax_inst.src_operands_idx[1],
        zero_operand_index=hmax_inst.src_operands_idx[0],
        output_operand_index=hmax_inst.dst_operands_idx[0],
        max_src0_operand_role="zero",
        max_src1_operand_role="input",
        local_order=(0, 1),
        csv_rows=(
            ("IMM", "IMM_relu_zero", "", "", "ZERO_RELU", "", "0", "0"),
            ("HMAX", "HMAX_relu", "ZERO_RELU", "Y_IN", "Y_OUT", "", "", "0"),
        ),
        raw_inst_t_byte_count=len(payload),
        raw_template_row_sha256=hashlib.sha256(payload).hexdigest(),
        per_row_sha256=tuple(hashlib.sha256(row).hexdigest() for row in row_bytes),
        candidate_row_bytes_claim=True,
        candidate_raw_template_row_sha256_claim=True,
        active_selector_claim=False,
        activation_record=activation_record,
        blocker=(
            "candidate rows are packed from the vendor subtask4 IMM+HMAX source "
            "shape with stable bytes, hashes, a B-line explicit relu_tile "
            "activation candidate, and a local decode skeleton, but no active "
            "SimICT/GEMM+ReLU runtime selector trace has selected them yet"
        ),
    )


def _subtask4_activation_record(
    *,
    insts: tuple[object, ...],
    row_bytes: tuple[bytes, ...],
) -> ReluSubtask4ActivationRecord:
    decoded_rows = tuple(decode_legacy_inst_skeleton(row) for row in row_bytes)
    decoded_ops = tuple(getattr(inst, "op_name") for inst in insts)
    decoded_opcode_values = tuple(int(row["opcode"]) for row in decoded_rows)
    decoded_src_operands = tuple(
        tuple(int(value) for value in row["src_operands_idx"])
        for row in decoded_rows
    )
    decoded_dst_operands = tuple(
        tuple(int(value) for value in row["dst_operands_idx"])
        for row in decoded_rows
    )
    local_decode_closed = (
        decoded_ops == ("IMM", "HMAX")
        and decoded_opcode_values == (0x22, 0x53)
        and decoded_src_operands[1][:2] == (128, 0)
        and decoded_dst_operands[1][0] == 256
    )
    return ReluSubtask4ActivationRecord(
        status=(
            "bline_explicit_activation_candidate_runtime_selector_missing"
        ),
        source_kind="bline_explicit_relu_tile_task_activation",
        subtask_slot="subtask4_relu_explicit",
        generated_csv_candidate_status="closed",
        explicit_task_activation_status="closed",
        op_chain_activation_status="closed",
        local_decode_roundtrip_status=(
            "closed" if local_decode_closed else "p0_blocked"
        ),
        runtime_selector_trace_status="p0_blocked",
        decoded_ops=decoded_ops,
        decoded_opcode_values=decoded_opcode_values,
        decoded_src_operands=decoded_src_operands,
        decoded_dst_operands=decoded_dst_operands,
        source_refs=(
            "compiler/gpdpu_compiler/core/stream_compiler/relu_fiber_chain.py:"
            "gemm_tile->relu_tile->store_tile",
            "simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/"
            "gemm_template_fusion_bash_semantics_probe/gpdpu_tensor/"
            "task_main.cpp:SUBTASK_COUNT==4",
            "simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/"
            "gemm_template_fusion_bash_semantics_probe/gpdpu_tensor/"
            "task*/subtask4/template/new_temp.cpp:OpType::RELU",
        ),
        remaining_artifacts=(ACTIVE_RELU_RUNTIME_TRACE_ARTIFACT,),
        blocker=(
            "B-line can explicitly activate relu_tile as its own task/subtask4 "
            "candidate, but runtime start/wait/selector trace is still needed "
            "before claiming active row-family selection"
        ),
    )


def _binding_seed_for_relu(
    relu_op: TemplateOp,
    *,
    template_index: int,
    dtype_decision: ReluDtypeDecision,
    zero_constant_policy: ReluZeroConstantPolicy,
) -> ReluTemplateBindingSeed:
    expected_ops = tuple(
        op
        for op in (
            zero_constant_policy.materialization_opcode,
            dtype_decision.recommended_opcode,
        )
        if op is not None
    )
    required_writer_inputs = (
        "template_path",
        "template_index",
        "row_span_or_local_orders",
        "relu_zero_constant_row_selector",
        "relu_max_row_selector",
        "relu_input_operand_binding",
        "relu_zero_operand_index",
        "relu_output_operand_binding",
        "raw_inst_t_row_bytes",
        "raw_template_row_sha256",
    )
    return ReluTemplateBindingSeed(
        seed_schema="s2_exact_template_binding_seed_v0",
        seed_status="p0_blocked",
        template_op_id=relu_op.id,
        role=relu_op.role,
        template_family="dfu3500_explicit_relu_tile_op",
        template_path=None,
        template_index=template_index,
        row_span_start=None,
        row_span_end=None,
        expected_ops=expected_ops,
        expected_row_count=len(expected_ops),
        required_writer_inputs=required_writer_inputs,
        missing_writer_inputs=required_writer_inputs,
        template_row_sha256=None,
        raw_template_bytes_sha256=None,
        blocker=(
            "S2 needs exact template path/template_index/local_order, zero "
            "operand binding, raw inst_t row bytes, and template row hashes "
            "for IMM+HMAX/FMAX"
        ),
    )


def _store_lifetime_for_relu(
    relu_op: TemplateOp,
    *,
    store_op: TemplateOp | None,
) -> ReluStoreOperandLifetime:
    if store_op is None:
        return ReluStoreOperandLifetime(
            status="p0_blocked",
            required_store_input="relu_output",
            forbidden_store_input="pre_relu_accumulator",
            relu_output_fragment="Y",
            store_template_op_id=None,
            store_dependency_source=None,
            blocker="no tile_store TemplateOp consumes this ReLU output",
        )
    return ReluStoreOperandLifetime(
        status="closed",
        required_store_input="relu_output",
        forbidden_store_input="pre_relu_accumulator",
        relu_output_fragment="Y",
        store_template_op_id=store_op.id,
        store_dependency_source=relu_op.provenance.primary_fiber_op_id,
        blocker=None,
    )


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
    "EXPECTED_RELU_TEMPLATE_COUNT",
    "EXPLICIT_RELU_LAYOUT",
    "EXPLICIT_RELU_OP",
    "EXPLICIT_RELU_OPERATOR",
    "ExplicitReluSubtaskBinding",
    "ExplicitReluSubtaskBindingReport",
    "ReluDtypeDecision",
    "ReluEvidenceRequirement",
    "ReluExactRowEvidence",
    "ReluStoreOperandLifetime",
    "ReluTemplateBindingSeed",
    "ReluZeroConstantPolicy",
    "bind_explicit_relu_subtasks",
    "summarize_explicit_relu_subtask_binding_report",
]
