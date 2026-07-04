"""Experimental B-line executable lowering from flat FiberOps.

This module is intentionally separate from the A-line TileMicroBlock
compatibility probe.  The source of truth is `FiberOp`, not `FiberBlock` and
not old `TileMicroBlock` rows.

Phase 1 is symbolic: it assigns executable roles and provenance, but it does not
bind DFU3500 templates, ASM, packing, ABI rows, or vendor serializers.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from gpdpu_compiler.core.op_specs.lowering_profiles import ExecutableRoleSetProfile

from .blocks import FiberBlockProjection
from .fiber import Fiber, FiberOp, FragmentRef


@dataclass(frozen=True)
class ExecutableFiberOp:
    """Executable-role view of one source FiberOp."""

    id: str
    stream_id: str
    source_fiber_id: str
    source_fiber_op_id: str
    source_fiber_op_kind: str
    source_order_index: int
    role: str
    placement: str
    loop_axis: str | None = None
    loop_instance_key: str | None = None
    input_fragments: tuple[FragmentRef, ...] = ()
    output_fragments: tuple[FragmentRef, ...] = ()
    visibility_refs: tuple[str, ...] = ()
    dependency_source_ids: tuple[str, ...] = ()
    proof_summary: tuple[dict[str, object], ...] = ()
    attrs: dict[str, object] = field(default_factory=dict)

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "stream_id": self.stream_id,
            "source_fiber_id": self.source_fiber_id,
            "source_fiber_op_id": self.source_fiber_op_id,
            "source_fiber_op_kind": self.source_fiber_op_kind,
            "source_order_index": self.source_order_index,
            "role": self.role,
            "placement": self.placement,
            "loop_axis": self.loop_axis,
            "loop_instance_key": self.loop_instance_key,
            "input_fragments": [fragment.to_plan() for fragment in self.input_fragments],
            "output_fragments": [fragment.to_plan() for fragment in self.output_fragments],
            "visibility_refs": list(self.visibility_refs),
            "dependency_source_ids": list(self.dependency_source_ids),
            "proof_summary": list(self.proof_summary),
            "attrs": dict(self.attrs),
        }


@dataclass(frozen=True)
class FiberExecutableProgram:
    """Symbolic executable-role program for a fiber forest."""

    executable_ops: tuple[ExecutableFiberOp, ...]
    diagnostics: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "ir": "experimental_fiber_executable_program",
            "executable_ops": [op.to_plan() for op in self.executable_ops],
            "diagnostics": list(self.diagnostics),
        }


def lower_fibers_to_executable_ops(
    fibers: tuple[Fiber, ...],
    *,
    projections: tuple[FiberBlockProjection, ...] = (),
    executable_role_profile: ExecutableRoleSetProfile,
) -> FiberExecutableProgram:
    """Lower flat fibers to symbolic executable roles.

    Optional projections are consumed only for proof summaries.  This function
    must not consume TileMicroBlock-compatible rows or old block-kind mappings.
    """

    projection_by_fiber = {projection.fiber_id: projection for projection in projections}
    role_resolver = _ExecutableRoleResolver(executable_role_profile)
    executable_ops: list[ExecutableFiberOp] = []
    diagnostics: list[str] = []
    seen_source_ops: set[str] = set()

    for fiber in fibers:
        projection = projection_by_fiber.get(fiber.id)
        proof_by_dst_op = _proofs_by_dst_fiber_op(projection) if projection else {}
        for fiber_op in fiber.ops:
            if fiber_op.id in seen_source_ops:
                diagnostics.append(f"duplicate source FiberOp id: {fiber_op.id}")
            seen_source_ops.add(fiber_op.id)
            executable_ops.append(
                _executable_op_from_fiber_op(
                    fiber=fiber,
                    fiber_op=fiber_op,
                    role=role_resolver.role_for(fiber_op),
                    proof_summary=proof_by_dst_op.get(fiber_op.id, ()),
                )
            )
            if executable_ops[-1].role.startswith("unknown:"):
                diagnostics.append(
                    f"unknown executable role for FiberOp {fiber_op.id}: {fiber_op.op}"
                )

    return FiberExecutableProgram(
        executable_ops=tuple(executable_ops),
        diagnostics=tuple(diagnostics),
    )


def summarize_executable_program(program: FiberExecutableProgram) -> dict[str, object]:
    """Return a validation summary for the symbolic executable program."""

    role_counts: dict[str, int] = {}
    placement_counts: dict[str, int] = {}
    source_kind_counts: dict[str, int] = {}
    proof_status_counts: dict[str, int] = {}
    source_ids: set[str] = set()
    forbidden_tile_micro_block_fields = 0

    for op in program.executable_ops:
        role_counts[op.role] = role_counts.get(op.role, 0) + 1
        placement_counts[op.placement] = placement_counts.get(op.placement, 0) + 1
        source_kind_counts[op.source_fiber_op_kind] = source_kind_counts.get(op.source_fiber_op_kind, 0) + 1
        source_ids.add(op.source_fiber_op_id)
        for proof in op.proof_summary:
            status = str(proof.get("status", "missing"))
            proof_status_counts[status] = proof_status_counts.get(status, 0) + 1
        for key in op.attrs:
            if key.startswith("source_tile_micro_block") or key == "tile_micro_block_kind":
                forbidden_tile_micro_block_fields += 1

    return {
        "executable_op_count": len(program.executable_ops),
        "unique_source_fiber_op_count": len(source_ids),
        "role_counts": dict(sorted(role_counts.items())),
        "placement_counts": dict(sorted(placement_counts.items())),
        "source_fiber_op_kind_counts": dict(sorted(source_kind_counts.items())),
        "proof_status_counts": dict(sorted(proof_status_counts.items())),
        "diagnostic_count": len(program.diagnostics),
        "forbidden_tile_micro_block_field_count": forbidden_tile_micro_block_fields,
    }


def _executable_op_from_fiber_op(
    *,
    fiber: Fiber,
    fiber_op: FiberOp,
    role: str,
    proof_summary: tuple[dict[str, object], ...],
) -> ExecutableFiberOp:
    reduction_fragment_index = _reduction_fragment_index(fiber_op)
    loop_axis = (
        str(fiber_op.attrs.get("loop_axis", "reduction_fragment"))
        if reduction_fragment_index is not None
        else None
    )
    visibility_action_id = fiber_op.attrs.get("stream_visibility_action_id")
    visibility_refs = (str(visibility_action_id),) if visibility_action_id is not None else ()
    return ExecutableFiberOp(
        id=f"exec:{fiber_op.id}",
        stream_id=fiber_op.stream_id,
        source_fiber_id=fiber.id,
        source_fiber_op_id=fiber_op.id,
        source_fiber_op_kind=fiber_op.op,
        source_order_index=fiber_op.order_index,
        role=role,
        placement=str(fiber_op.attrs.get("placement", "unknown")),
        loop_axis=loop_axis,
        loop_instance_key=(
            f"k{reduction_fragment_index}"
            if reduction_fragment_index is not None
            else None
        ),
        input_fragments=fiber_op.inputs,
        output_fragments=fiber_op.outputs,
        visibility_refs=visibility_refs,
        dependency_source_ids=tuple(dependency.source_op_id for dependency in fiber_op.depends_on),
        proof_summary=proof_summary,
        attrs={
            "symbolic_status": "template_unbound",
            "subtask_role": fiber_op.attrs.get("subtask_role"),
            "operand": fiber_op.attrs.get("operand"),
            "visibility_kind": fiber_op.attrs.get("visibility_kind"),
            "source_value_kind": fiber_op.attrs.get("source_value_kind"),
            "destination_value_kind": fiber_op.attrs.get("destination_value_kind"),
            "receiver_destination_operand": fiber_op.attrs.get(
                "receiver_destination_operand"
            ),
            "receiver_destination_block": fiber_op.attrs.get(
                "receiver_destination_block"
            ),
            "route_template_family": fiber_op.attrs.get("route_template_family"),
            "template_evidence_id": fiber_op.attrs.get("template_evidence_id"),
            "reduction_fragment_index": fiber_op.attrs.get("reduction_fragment_index"),
            "k_block": reduction_fragment_index,
            "role_profile_source": "core/op_specs.executable_role_profile",
        },
    )


def _reduction_fragment_index(fiber_op: FiberOp) -> int | None:
    value = fiber_op.attrs.get("reduction_fragment_index")
    if isinstance(value, int):
        return value
    return None


class _ExecutableRoleResolver:
    """Resolve FiberOps through the operator executable role profile."""

    def __init__(self, profile: ExecutableRoleSetProfile) -> None:
        self.profile = profile
        self._by_step_namespace_operand: dict[tuple[str, str, str | None], str] = {}
        self._by_step: dict[str, list[str]] = {}
        for role_profile in profile.roles:
            role_id = role_profile.role
            role_text = role_id.text()
            for step_id in role_profile.source_step_ids:
                self._by_step_namespace_operand[
                    (step_id, role_id.namespace, role_id.operand_role)
                ] = role_text
                self._by_step.setdefault(step_id, []).append(role_text)

    def role_for(self, fiber_op: FiberOp) -> str:
        query = _role_query_for_fiber_op(fiber_op)
        if query is None:
            return f"unknown:{fiber_op.op}"
        step_id, namespace, operand_role = query
        role = self._by_step_namespace_operand.get((step_id, namespace, operand_role))
        if role is not None:
            return role

        step_roles = self._by_step.get(step_id, ())
        if len(step_roles) == 1:
            return step_roles[0]
        return f"unknown:{fiber_op.op}"


def _role_query_for_fiber_op(fiber_op: FiberOp) -> tuple[str, str, str | None] | None:
    if fiber_op.op == "gemm_tile":
        return "gemm_tile", "compute_core", None
    if fiber_op.op == "relu_tile":
        return "relu_tile", "tile_op", None
    if fiber_op.op == "clamp_min_tile":
        return "clamp_min_tile", "tile_op", None
    if fiber_op.op == "log10_tile":
        return "log10_tile", "tile_op", None
    if fiber_op.op == "local_reduce_max_tile":
        return "local_reduce_max_tile", "tile_reduce", None
    if fiber_op.op == "global_max_tile":
        return "global_max_tile", "collective", None
    if fiber_op.op == "max_with_floor_tile":
        return "max_with_floor_tile", "tile_op", None
    if fiber_op.op == "affine_scale_tile":
        return "affine_scale_tile", "tile_op", None
    if fiber_op.op == "store_tile":
        return "store_fragment", "store", None
    if fiber_op.op == "fragment_sram_read":
        operand = _operand_role(fiber_op)
        return f"materialize_{operand}", "operand_materialize", operand
    if fiber_op.op == "fragment_route_recv":
        operand = _operand_role(fiber_op)
        return f"materialize_{operand}", "operand_route_recv", operand
    if fiber_op.op == "fragment_route_push":
        operand = _operand_role(fiber_op)
        return f"materialize_{operand}", "operand_route_push", operand
    if fiber_op.op == "accumulator_prepare":
        return "accumulator_prepare", "accumulator", None
    if fiber_op.op == "gemm_update":
        return "gemm_update", "compute_core", None
    if fiber_op.op == "finalize_accumulator":
        return "finalize_accumulator", "accumulator", None
    if fiber_op.op == "store_fragment":
        return "store_fragment", "store", None
    return None


def _operand_role(fiber_op: FiberOp) -> str:
    operand = fiber_op.attrs.get("operand")
    if operand in {"A", "B", "GlobalMax"}:
        return str(operand)
    for fragment in (*fiber_op.inputs, *fiber_op.outputs):
        if fragment.role in {"A", "B", "GlobalMax"}:
            return fragment.role
    return "operand"


def _proofs_by_dst_fiber_op(
    projection: FiberBlockProjection | None,
) -> dict[str, tuple[dict[str, object], ...]]:
    if projection is None:
        return {}
    source_op_by_block = {
        block.id: block.source_fiber_op_id
        for block in projection.blocks
    }
    grouped: dict[str, list[dict[str, object]]] = {}
    for dependency in projection.dependencies:
        dst_op_id = source_op_by_block.get(dependency.dst_block_id)
        if dst_op_id is None:
            continue
        proof = dependency.proof
        grouped.setdefault(dst_op_id, []).append(
            {
                "source_fiber_dependency_id": dependency.source_fiber_dependency_id,
                "status": None if proof is None else proof.status,
                "proven_by": () if proof is None else proof.proven_by,
                "expected_satisfaction": dependency.expected_satisfaction,
            }
        )
    return {
        op_id: tuple(proofs)
        for op_id, proofs in grouped.items()
    }


__all__ = [
    "ExecutableFiberOp",
    "FiberExecutableProgram",
    "lower_fibers_to_executable_ops",
    "summarize_executable_program",
]
