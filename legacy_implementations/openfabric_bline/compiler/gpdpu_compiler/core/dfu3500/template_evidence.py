"""DFU3500 target evidence for operator template intent records.

This module is target/profile-owned evidence.  Operator specs describe intent;
this module describes what the current DFU3500 legacy GEMM profile can prove or
only carry symbolically.
"""

from __future__ import annotations

from gpdpu_compiler.core.op_specs.lowering_profiles import (
    TargetTemplateStatus,
    TemplateEvidenceProfile,
    TemplateIntentSetProfile,
)


DFU3500_LEGACY_GEMM_SYMBOLIC_PROFILE_ID = "dfu3500_legacy_gemm_symbolic"


_LEGACY_TEMPLATE_CANDIDATES = {
    "compute_core:gemm_tile": (
        "legacy_expanded_gemm_tile_template_span",
        (
            "atomic GEMM fiber op binds to a deterministic DFU3500 GEMM tile "
            "template expansion; internal K/update rows are physical lowering "
            "content, not FiberOps",
        ),
    ),
    "accumulator_prepare": (
        "accumulator_prepare",
        ("direct legacy GEMM template candidate",),
    ),
    "operand_materialize:A": (
        "route_source_materialize",
        ("source-side operand materialization candidate",),
    ),
    "operand_materialize:B": (
        "route_source_materialize",
        ("source-side operand materialization candidate",),
    ),
    "operand_route_recv:A": (
        "route_forward",
        (
            "endpoint visibility role; legacy template source may execute on sender/route side",
        ),
    ),
    "operand_route_recv:B": (
        "route_forward",
        (
            "endpoint visibility role; legacy template source may execute on sender/route side",
        ),
    ),
    "operand_route_push:A": (
        "route_forward",
        ("sender-side route role candidate",),
    ),
    "operand_route_push:B": (
        "route_forward",
        ("sender-side route role candidate",),
    ),
    "operand_route_recv:GlobalMax": (
        "route_forward",
        (
            "GlobalMax scalar recv reuses the existing operand route visibility "
            "family; receiver-owned destination operand proof is enforced by "
            "the RouteRoleBinding report before runtime_ready",
        ),
    ),
    "operand_route_push:GlobalMax": (
        "route_forward",
        (
            "GlobalMax scalar push reuses the existing sender-side route role "
            "candidate; no new communication IR or direct-route collective is "
            "introduced",
        ),
    ),
    "compute_core:gemm_update": (
        "compute_update",
        ("direct GEMM K-update template candidate",),
    ),
    "tile_store": (
        "tile_store",
        ("direct output store template candidate",),
    ),
    "tile_op:relu": (
        "dfu3500_explicit_relu_tile_op",
        (
            "independent ReLU tile op maps to max-with-zero local template "
            "shape; an explicit IMM-zero plus HMAX materializer candidate is "
            "source-backed by the vendor secondary-fusion subtask4 generator, "
            "while active generated CSV/runtime row selection remains "
            "writer-level evidence",
        ),
    ),
    "tile_op:clamp_min": (
        "dfu3500_log10max_clamp_min_tile",
        ("local log10max FMAX immediate clamp template candidate",),
    ),
    "tile_op:log10": (
        "dfu3500_log10max_log10_tile",
        ("local log10max FLOG2 plus FMUL log10(2) template candidate",),
    ),
    "tile_reduce:local_reduce_max": (
        "dfu3500_log10max_local_reduce_max_tile",
        ("local log10max SHFL plus FMAX reduce template candidate",),
    ),
    "tile_op:affine_scale": (
        "dfu3500_log10max_affine_scale_tile",
        ("local log10max FADD bias plus FMUL scale template candidate",),
    ),
}


_ZERO_INSTRUCTION_EVIDENCE = {
    "accumulator_finalize": (
        "zero_instruction_accumulator_value_boundary",
        ("no explicit legacy TileMicroBlock slot; keep role visible",),
    ),
}


_SYMBOLIC_UNRESOLVED_EVIDENCE = {
    "collective:global_max": (
        "symbolic_pe00_global_max_tile_blocked",
        (
            "PE00 aggregate/materialize contract is selected but row-byte "
            "lowering and runtime execution proof remain blocked",
        ),
    ),
    "tile_op:max_with_floor": (
        "symbolic_max_with_floor_waiting_on_global_scalar",
        (
            "local FMAX vector-scalar shape is known, but scalar visibility "
            "from global_max_tile remains blocked",
        ),
    ),
}


def resolve_dfu3500_legacy_template_evidence(
    intents: TemplateIntentSetProfile,
    *,
    target_profile_id: str = DFU3500_LEGACY_GEMM_SYMBOLIC_PROFILE_ID,
) -> tuple[TemplateEvidenceProfile, ...]:
    """Resolve operator template intent against the current DFU3500 profile."""

    evidence: list[TemplateEvidenceProfile] = []
    for intent in intents.intents:
        role_text = intent.executable_role.text()
        status: TargetTemplateStatus
        template_role: str | None
        evidence_refs: tuple[str, ...]

        if role_text in _LEGACY_TEMPLATE_CANDIDATES:
            status = "legacy_candidate"
            template_role, evidence_refs = _LEGACY_TEMPLATE_CANDIDATES[role_text]
        elif role_text in _ZERO_INSTRUCTION_EVIDENCE and intent.may_be_zero_instruction:
            status = "zero_instruction"
            template_role = None
            evidence_refs = _ZERO_INSTRUCTION_EVIDENCE[role_text]
        elif role_text in _SYMBOLIC_UNRESOLVED_EVIDENCE:
            status = "symbolic_unresolved"
            template_role = None
            evidence_refs = _SYMBOLIC_UNRESOLVED_EVIDENCE[role_text]
        else:
            status = intent.fallback_status
            template_role = None
            evidence_refs = ("no DFU3500 legacy template evidence for role",)

        evidence.append(
            TemplateEvidenceProfile(
                executable_role=intent.executable_role,
                target_profile_id=target_profile_id,
                resolved_status=status,
                template_role=template_role,
                evidence_refs=evidence_refs,
            )
        )
    return tuple(evidence)


__all__ = [
    "DFU3500_LEGACY_GEMM_SYMBOLIC_PROFILE_ID",
    "resolve_dfu3500_legacy_template_evidence",
]
