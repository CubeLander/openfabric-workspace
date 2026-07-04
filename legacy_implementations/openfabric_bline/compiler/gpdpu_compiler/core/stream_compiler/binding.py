"""Symbolic executable-role binding for the experimental B-line.

This layer is deliberately small: it consumes `ExecutableFiberOp.role` and
reports the current DFU3500 legacy-template support status.  It must not bind
through TileMicroBlock compatibility rows, old block kinds, ASM, packing, ABI
rows, or vendor serializers.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from gpdpu_compiler.core.dfu3500.template_evidence import (
    DFU3500_LEGACY_GEMM_SYMBOLIC_PROFILE_ID,
    resolve_dfu3500_legacy_template_evidence,
)
from gpdpu_compiler.core.op_specs.lowering_profiles import (
    TargetTemplateStatus,
    TemplateEvidenceProfile,
    TemplateIntentSetProfile,
)

from .executable import ExecutableFiberOp, FiberExecutableProgram

BindingStatus = Literal[
    "legacy_template_candidate",
    "symbolic_unsupported",
    "unknown_role",
]


@dataclass(frozen=True)
class Pe00ScalarReceiverBindingContract:
    """Receiver-owned binding contract for PE00 materialized scalar reads."""

    source_id: str
    scratch_slot: str
    consumer_processors: tuple[str, ...]
    dtype: str = "fp32"
    status: str = "available"

    def to_plan(self) -> dict[str, object]:
        per_consumer_binding_contract = [
            {
                "consumer_processor": processor,
                "expected_readback_row_id": (
                    f"global_max_tile.consumer_readback.{index:02d}"
                ),
                "producer_fiber_op": "global_max_tile",
                "consumer_fiber_op": "max_with_floor_tile",
                "load_stage": "consumer_physical_readback",
                "source": self.scratch_slot,
                "destination_operand": "receiver_owned_global_max_scalar_operand",
                "destination_scope": "receiver_owned_scalar_operand",
                "dtype": self.dtype,
                "required_decoded_fields": [
                    "consumer_processor",
                    "scratch_address_operand",
                    "destination_operand_index",
                    "destination_scope",
                ],
            }
            for index, processor in enumerate(self.consumer_processors)
        ]
        per_consumer_roundtrip_recipe = [
            {
                "consumer_processor": processor,
                "expected_readback_row_id": (
                    f"global_max_tile.consumer_readback.{index:02d}"
                ),
                "readback_stage": "consumer_physical_readback",
                "decoded_row_artifact": "pe00_scalar_readback_decoded_rows.json",
                "decoded_row_index": index,
                "source_operand": self.scratch_slot,
                "destination_operand": "receiver_owned_global_max_scalar_operand",
                "consumer_fiber_op": "max_with_floor_tile",
                "operand_link_artifact": "max_with_floor_operand_link.json",
                "status": "blocked_missing_decoded_readback_row",
            }
            for index, processor in enumerate(self.consumer_processors)
        ]
        scalar_visibility_proof_matrix = [
            {
                "consumer_processor": processor,
                "readback_row_id": f"global_max_tile.consumer_readback.{index:02d}",
                "producer_fiber_op": "global_max_tile",
                "consumer_fiber_op": "max_with_floor_tile",
                "source_scratch_slot": self.scratch_slot,
                "receiver_destination_operand": (
                    "receiver_owned_global_max_scalar_operand"
                ),
                "required_readback_decode_artifact": (
                    "pe00_scalar_readback_decoded_rows.json"
                ),
                "required_operand_link_artifact": (
                    "max_with_floor_operand_link.json"
                ),
                "proof_status": (
                    "blocked_until_readback_decode_and_operand_link_roundtrip"
                ),
                "row_bytes_claim": False,
                "physical_route_allreduce": False,
            }
            for index, processor in enumerate(self.consumer_processors)
        ]
        synthetic_receiver_operand_link_matrix = [
            {
                "consumer_processor": processor,
                "readback_row_id": f"global_max_tile.consumer_readback.{index:02d}",
                "synthetic_decoded_destination_operand_index": 512 + index,
                "destination_operand": "receiver_owned_global_max_scalar_operand",
                "consumer_fiber_op": "max_with_floor_tile",
                "operand_link_artifact": "max_with_floor_operand_link.json",
                "status": (
                    "synthetic_readback_destination_operand_link_available_"
                    "active_decode_roundtrip_missing"
                ),
                "synthetic_decode_roundtrip_claim": True,
                "active_operand_decode_claim": False,
                "row_bytes_claim": False,
                "physical_route_allreduce": False,
            }
            for index, processor in enumerate(self.consumer_processors)
        ]
        receiver_binding_proof_plan = {
            "schema_version": 1,
            "artifact_kind": "pe00_scalar_receiver_binding_proof_plan",
            "source_id": self.source_id,
            "scratch_slot": self.scratch_slot,
            "status": (
                "blocked_synthetic_receiver_operand_link_available_"
                "active_decode_roundtrip_missing"
            ),
            "consumer_count": len(self.consumer_processors),
            "closed_fields": [
                "producer_fiber_op",
                "consumer_fiber_op",
                "load_stage",
                "destination_scope",
                "dtype",
                "consumer_processors",
                "synthetic_receiver_operand_link_matrix",
            ],
            "missing_fields": [
                "active_per_consumer_vendor_operand_indices",
                "active_readback_inst_t_destination_encoding",
                "active_max_with_floor_source_operand_link",
                "active_decoded_operand_binding_roundtrip",
            ],
            "per_consumer_binding_contract": per_consumer_binding_contract,
            "per_consumer_roundtrip_recipe": per_consumer_roundtrip_recipe,
            "scalar_visibility_proof_matrix": scalar_visibility_proof_matrix,
            "synthetic_receiver_operand_link_matrix": (
                synthetic_receiver_operand_link_matrix
            ),
            "roundtrip_contract": {
                "decoded_row_source": "pe00_scalar_readback_decoded_rows.json",
                "must_match_consumer_count": len(self.consumer_processors),
                "expected_readback_row_ids": [
                    f"global_max_tile.consumer_readback.{index:02d}"
                    for index, _processor in enumerate(self.consumer_processors)
                ],
                "must_decode_to_destination": (
                    "receiver_owned_global_max_scalar_operand"
                ),
                "must_feed_consumer_fiber_op": "max_with_floor_tile",
            },
            "receiver_roundtrip_request": {
                "schema_version": 1,
                "artifact_kind": "pe00_scalar_receiver_roundtrip_request",
                "source_id": self.source_id,
                "scratch_slot": self.scratch_slot,
                "status": "roundtrip_request_available_rows_missing",
                "consumer_count": len(self.consumer_processors),
                "expected_readback_row_count": len(self.consumer_processors),
                "expected_readback_row_ids": [
                    f"global_max_tile.consumer_readback.{index:02d}"
                    for index, _processor in enumerate(self.consumer_processors)
                ],
                "scalar_visibility_proof_matrix": scalar_visibility_proof_matrix,
                "decoded_row_source": "pe00_scalar_readback_decoded_rows.json",
                "required_destination_operand": (
                    "receiver_owned_global_max_scalar_operand"
                ),
                "required_consumer_fiber_op": "max_with_floor_tile",
                "synthetic_receiver_operand_link_matrix": (
                    synthetic_receiver_operand_link_matrix
                ),
                "per_consumer_roundtrip_recipe_artifact": (
                    "receiver_operand_roundtrip_recipe.json"
                ),
                "required_output_artifacts": [
                    "pe00_scalar_readback_decoded_rows.json",
                    "receiver_operand_roundtrip_recipe.json",
                    "receiver_operand_roundtrip.json",
                    "max_with_floor_operand_link.json",
                ],
                "blocked_on": [
                    "receiver_global_scalar_binding_proof_missing",
                    "consumer_physical_readback_row_bytes_missing",
                ],
                "runtime_runnable_claim": False,
                "row_bytes_claim": False,
                "physical_route_allreduce": False,
            },
            "required_proof_artifacts": [
                "pe00_scalar_readback_decoded_rows.json",
                "receiver_operand_roundtrip_recipe.json",
                "receiver_operand_roundtrip.json",
                "max_with_floor_operand_link.json",
            ],
            "proof_blockers": [
                {
                    "blocker_id": "receiver_global_scalar_binding_proof_missing",
                    "status": "blocked_missing_vendor_operand_binding_proof",
                    "needed_evidence": (
                        "active vendor/A-line readback rows decode into the "
                        "receiver-owned operand consumed by max_with_floor_tile"
                    ),
                },
                {
                    "blocker_id": "consumer_physical_readback_row_bytes_missing",
                    "status": "blocked_missing_readback_row_bytes",
                    "needed_evidence": (
                        "readback inst_t row bytes carry the destination "
                        "operand indices named by this binding"
                    ),
                },
            ],
            "runtime_runnable_claim": False,
            "row_bytes_claim": False,
            "physical_route_allreduce": False,
        }
        receiver_bindings = [
            {
                "consumer_processor": processor,
                "load_kind": "pe00_scalar_load_or_broadcast",
                "source_id": self.source_id,
                "scratch_slot": self.scratch_slot,
                "destination_scope": "receiver_owned_scalar_operand",
                "dtype": self.dtype,
            }
            for processor in self.consumer_processors
        ]
        vendor_operand_binding_intent = {
            "schema_version": 1,
            "artifact_kind": "pe00_scalar_receiver_operand_binding_intent",
            "source_id": self.source_id,
            "scratch_slot": self.scratch_slot,
            "status": "operand_binding_intent_available_proof_missing",
            "consumer_count": len(self.consumer_processors),
            "bindings": [
                dict(binding, binding_proof_status="blocked_missing_vendor_operand_rows")
                for binding in per_consumer_binding_contract
            ],
            "synthetic_receiver_operand_link_matrix": (
                synthetic_receiver_operand_link_matrix
            ),
            "roundtrip_contract": receiver_binding_proof_plan["roundtrip_contract"],
            "blocked_on": [
                "receiver_global_scalar_binding_proof_missing",
                "consumer_physical_readback_row_bytes_missing",
            ],
            "receiver_binding_proof_plan": receiver_binding_proof_plan,
            "runtime_runnable_claim": False,
            "row_bytes_claim": False,
            "physical_route_allreduce": False,
        }
        return {
            "schema_version": 1,
            "artifact_kind": "pe00_scalar_receiver_binding_contract",
            "source_id": self.source_id,
            "scratch_slot": self.scratch_slot,
            "dtype": self.dtype,
            "status": self.status,
            "consumer_count": len(self.consumer_processors),
            "receiver_bindings": receiver_bindings,
            "receiver_binding_proof_plan": receiver_binding_proof_plan,
            "vendor_operand_binding_intent": vendor_operand_binding_intent,
            "receiver_owned_destination_binding": True,
            "physical_route_allreduce": False,
            "runtime_runnable_claim": False,
            "row_bytes_claim": False,
        }


@dataclass(frozen=True)
class SymbolicRoleBinding:
    """Symbolic target/profile binding for one executable fiber op."""

    id: str
    executable_op_id: str
    role: str
    source_fiber_op_id: str
    source_fiber_op_kind: str
    profile_id: str
    status: BindingStatus
    template_role: str | None = None
    binding_source: str | None = None
    notes: tuple[str, ...] = ()
    attrs: dict[str, object] = field(default_factory=dict)

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "executable_op_id": self.executable_op_id,
            "role": self.role,
            "source_fiber_op_id": self.source_fiber_op_id,
            "source_fiber_op_kind": self.source_fiber_op_kind,
            "profile_id": self.profile_id,
            "status": self.status,
            "template_role": self.template_role,
            "binding_source": self.binding_source,
            "notes": list(self.notes),
            "attrs": dict(self.attrs),
        }


@dataclass(frozen=True)
class SymbolicRoleBindingProgram:
    """Symbolic binding report for a FiberExecutableProgram."""

    profile_id: str
    bindings: tuple[SymbolicRoleBinding, ...]
    diagnostics: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "ir": "experimental_symbolic_role_binding_program",
            "profile_id": self.profile_id,
            "bindings": [binding.to_plan() for binding in self.bindings],
            "diagnostics": list(self.diagnostics),
        }


def bind_executable_roles_symbolically(
    program: FiberExecutableProgram,
    *,
    profile_id: str = DFU3500_LEGACY_GEMM_SYMBOLIC_PROFILE_ID,
    template_intents: TemplateIntentSetProfile,
    template_evidence: tuple[TemplateEvidenceProfile, ...] | None = None,
) -> SymbolicRoleBindingProgram:
    """Bind executable roles to symbolic DFU3500 profile support.

    The binding key is `ExecutableFiberOp.role`.  This function intentionally
    knows nothing about TileMicroBlock compatibility mappings.
    """

    evidence = template_evidence or resolve_dfu3500_legacy_template_evidence(
        template_intents,
        target_profile_id=profile_id,
    )
    resolver = _TemplateBindingResolver(
        template_intents=template_intents,
        template_evidence=evidence,
    )
    bindings: list[SymbolicRoleBinding] = []
    diagnostics: list[str] = []
    seen_ids: set[str] = set()

    for op in program.executable_ops:
        if op.id in seen_ids:
            diagnostics.append(f"duplicate executable op id: {op.id}")
        seen_ids.add(op.id)
        bindings.append(resolver.binding_for_executable_op(op, profile_id=profile_id))

    diagnostics.extend(program.diagnostics)
    return SymbolicRoleBindingProgram(
        profile_id=profile_id,
        bindings=tuple(bindings),
        diagnostics=tuple(diagnostics),
    )


def summarize_role_binding_program(program: SymbolicRoleBindingProgram) -> dict[str, object]:
    """Return a stable summary for focused B-line checks."""

    status_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    template_role_counts: dict[str, int] = {}
    binding_source_counts: dict[str, int] = {}
    unsupported_role_counts: dict[str, int] = {}
    forbidden_tile_micro_block_fields = 0

    for binding in program.bindings:
        status_counts[binding.status] = status_counts.get(binding.status, 0) + 1
        role_counts[binding.role] = role_counts.get(binding.role, 0) + 1
        if binding.template_role is not None:
            template_role_counts[binding.template_role] = template_role_counts.get(binding.template_role, 0) + 1
        if binding.binding_source is not None:
            binding_source_counts[binding.binding_source] = binding_source_counts.get(binding.binding_source, 0) + 1
        if binding.status != "legacy_template_candidate":
            unsupported_role_counts[binding.role] = unsupported_role_counts.get(binding.role, 0) + 1
        for key in binding.attrs:
            if key.startswith("source_tile_micro_block") or key == "tile_micro_block_kind":
                forbidden_tile_micro_block_fields += 1

    return {
        "binding_count": len(program.bindings),
        "status_counts": dict(sorted(status_counts.items())),
        "role_counts": dict(sorted(role_counts.items())),
        "template_role_counts": dict(sorted(template_role_counts.items())),
        "binding_source_counts": dict(sorted(binding_source_counts.items())),
        "unsupported_role_counts": dict(sorted(unsupported_role_counts.items())),
        "diagnostic_count": len(program.diagnostics),
        "forbidden_tile_micro_block_field_count": forbidden_tile_micro_block_fields,
    }


class _TemplateBindingResolver:
    """Compose operator template intent with target/profile evidence."""

    def __init__(
        self,
        *,
        template_intents: TemplateIntentSetProfile,
        template_evidence: tuple[TemplateEvidenceProfile, ...],
    ) -> None:
        self._intent_by_role = {
            intent.executable_role.text(): intent
            for intent in template_intents.intents
        }
        self._evidence_by_role = {
            evidence.executable_role.text(): evidence
            for evidence in template_evidence
        }

    def binding_for_executable_op(
        self,
        op: ExecutableFiberOp,
        *,
        profile_id: str,
    ) -> SymbolicRoleBinding:
        intent = self._intent_by_role.get(op.role)
        evidence = self._evidence_by_role.get(op.role)
        status, template_role, source, notes = _binding_status_from_intent_evidence(
            intent_present=intent is not None,
            evidence=evidence,
        )
        attrs: dict[str, object] = {
            "source_ir": "FiberExecutableProgram",
            "binding_key": "ExecutableFiberOp.role",
            "intent_source": "core/op_specs.template_intent_profile",
            "target_evidence_source": "core/dfu3500.template_evidence",
        }
        if intent is not None:
            attrs.update(
                {
                    "intent_template_family": intent.template_family,
                    "intent_resource_intent": intent.resource_intent,
                    "intent_may_be_zero_instruction": intent.may_be_zero_instruction,
                }
            )
        if evidence is not None:
            attrs.update(
                {
                    "evidence_status": evidence.resolved_status,
                    "evidence_refs": evidence.evidence_refs,
                }
            )
        return SymbolicRoleBinding(
            id=f"bind:{op.id}",
            executable_op_id=op.id,
            role=op.role,
            source_fiber_op_id=op.source_fiber_op_id,
            source_fiber_op_kind=op.source_fiber_op_kind,
            profile_id=profile_id,
            status=status,
            template_role=template_role,
            binding_source=source,
            notes=notes,
            attrs=attrs,
        )


def _binding_status_from_intent_evidence(
    *,
    intent_present: bool,
    evidence: TemplateEvidenceProfile | None,
) -> tuple[BindingStatus, str | None, str | None, tuple[str, ...]]:
    if not intent_present:
        return (
            "unknown_role",
            None,
            None,
            ("no operator template intent for executable role",),
        )
    if evidence is None:
        return (
            "unknown_role",
            None,
            None,
            ("no target evidence for executable role",),
        )

    if evidence.resolved_status == "legacy_candidate":
        return (
            "legacy_template_candidate",
            evidence.template_role,
            "dfu3500_legacy_gemm_template",
            evidence.evidence_refs,
        )

    if evidence.resolved_status in _SYMBOLIC_BINDING_STATUSES:
        return (
            "symbolic_unsupported",
            evidence.template_role,
            None,
            evidence.evidence_refs,
        )

    return (
        "unknown_role",
        evidence.template_role,
        None,
        evidence.evidence_refs,
    )


_SYMBOLIC_BINDING_STATUSES: set[TargetTemplateStatus] = {
    "candidate_unproven",
    "zero_instruction",
    "symbolic_unresolved",
    "unsupported",
}


__all__ = [
    "SymbolicRoleBinding",
    "SymbolicRoleBindingProgram",
    "bind_executable_roles_symbolically",
    "summarize_role_binding_program",
]
