"""Experimental fiber-to-block projection.

This module is a validation branch, not the new production backend trunk.

The projection keeps the intended steady-state grain:

    one FiberOp -> one FiberBlock

If a future op needs to explode into many low-level blocks, the preferred fix is
to split that operation earlier in StreamOp -> FiberOp lowering.  The block
projection should prove and report how flat fiber dependencies are structurally
satisfied; it should not hide route policy or GEMM policy inside the adapter.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

from .fiber import Fiber, FiberDependency, FiberOp, FragmentRef
from .stream import StreamAction, StreamPlan


ProjectionOrigin = Literal["direct_fiber_op", "unresolved_placeholder", "adapter_synthetic"]
BlockDependencyKind = Literal["semantic", "structural", "adapter_required"]
ProofStatus = Literal["pending", "satisfied", "unsatisfied"]
ProofKind = Literal[
    "subtask_order",
    "loop_instance_order",
    "route_path",
    "block_order",
    "same_block_order",
    "unresolved",
]


@dataclass(frozen=True)
class DependencyProof:
    """Proof or diagnostic attached to a projected block dependency."""

    source_fiber_dependency_id: str
    expected_satisfaction: str
    status: ProofStatus
    proven_by: tuple[ProofKind, ...]
    block_ids: tuple[str, ...] = ()
    stream_plan_edge_ids: tuple[str, ...] = ()
    loop_region_id: str | None = None
    loop_instance_ids: tuple[int, ...] = ()
    notes: tuple[str, ...] = ()

    def label(self) -> str:
        proof = ",".join(self.proven_by) or "-"
        return f"{self.status}:{self.expected_satisfaction}->{proof}"

    def to_plan(self) -> dict[str, object]:
        return {
            "source_fiber_dependency_id": self.source_fiber_dependency_id,
            "expected_satisfaction": self.expected_satisfaction,
            "status": self.status,
            "proven_by": list(self.proven_by),
            "block_ids": list(self.block_ids),
            "stream_plan_edge_ids": list(self.stream_plan_edge_ids),
            "loop_region_id": self.loop_region_id,
            "loop_instance_ids": list(self.loop_instance_ids),
            "notes": list(self.notes),
        }


@dataclass(frozen=True)
class FiberBlock:
    """Block-sized projection of one flat FiberOp."""

    id: str
    stream_id: str
    fiber_id: str
    block_kind: str
    source_fiber_op_id: str
    projection_origin: ProjectionOrigin
    placement: str
    loop_region_id: str | None = None
    loop_axis: str | None = None
    loop_instance_id: int | None = None
    input_fragments: tuple[FragmentRef, ...] = ()
    output_fragments: tuple[FragmentRef, ...] = ()
    input_visibility_refs: tuple[str, ...] = ()
    output_visibility_refs: tuple[str, ...] = ()
    attrs: dict[str, object] = field(default_factory=dict)

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "stream_id": self.stream_id,
            "fiber_id": self.fiber_id,
            "block_kind": self.block_kind,
            "source_fiber_op_id": self.source_fiber_op_id,
            "projection_origin": self.projection_origin,
            "placement": self.placement,
            "loop_region_id": self.loop_region_id,
            "loop_axis": self.loop_axis,
            "loop_instance_id": self.loop_instance_id,
            "input_fragments": [fragment.to_plan() for fragment in self.input_fragments],
            "output_fragments": [fragment.to_plan() for fragment in self.output_fragments],
            "input_visibility_refs": list(self.input_visibility_refs),
            "output_visibility_refs": list(self.output_visibility_refs),
            "attrs": dict(self.attrs),
        }


@dataclass(frozen=True)
class FiberBlockDependency:
    """Projected dependency edge between FiberBlocks."""

    id: str
    src_block_id: str
    dst_block_id: str
    dependency_kind: BlockDependencyKind
    source_fiber_dependency_id: str | None = None
    expected_satisfaction: str | None = None
    proof: DependencyProof | None = None
    attrs: dict[str, object] = field(default_factory=dict)

    def to_plan(self) -> dict[str, object]:
        return {
            "id": self.id,
            "src_block_id": self.src_block_id,
            "dst_block_id": self.dst_block_id,
            "dependency_kind": self.dependency_kind,
            "source_fiber_dependency_id": self.source_fiber_dependency_id,
            "expected_satisfaction": self.expected_satisfaction,
            "proof": None if self.proof is None else self.proof.to_plan(),
            "attrs": dict(self.attrs),
        }


@dataclass(frozen=True)
class FiberBlockProjection:
    """Block projection for one fiber."""

    fiber_id: str
    stream_id: str
    blocks: tuple[FiberBlock, ...]
    dependencies: tuple[FiberBlockDependency, ...]
    diagnostics: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "fiber_id": self.fiber_id,
            "stream_id": self.stream_id,
            "blocks": [block.to_plan() for block in self.blocks],
            "dependencies": [dependency.to_plan() for dependency in self.dependencies],
            "diagnostics": list(self.diagnostics),
        }


@dataclass(frozen=True)
class ProjectionValidationReport:
    """Validation-only report for the fiber/block debug projection."""

    ok: bool
    diagnostics: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "ok": self.ok,
            "diagnostics": list(self.diagnostics),
        }


def summarize_fiber_block_projections(
    projections: tuple[FiberBlockProjection, ...],
) -> dict[str, object]:
    """Return a validation-only aggregate view for many projections.

    This intentionally returns a plain report dictionary.  It is a microscope
    for debugging the experimental branch, not an IR object for lowering.
    """

    block_kind_counts: dict[str, int] = {}
    placement_counts: dict[str, int] = {}
    proof_status_counts: dict[str, int] = {}
    proof_kind_counts: dict[str, int] = {}
    loop_instance_counts: dict[str, dict[str, int]] = {}
    route_trace_lengths: dict[int, int] = {}
    streams = set()
    fiber_ids = set()
    total_blocks = 0
    total_dependencies = 0

    for projection in projections:
        streams.add(projection.stream_id)
        fiber_ids.add(projection.fiber_id)
        total_blocks += len(projection.blocks)
        total_dependencies += len(projection.dependencies)
        for block in projection.blocks:
            block_kind_counts[block.block_kind] = block_kind_counts.get(block.block_kind, 0) + 1
            placement_counts[block.placement] = placement_counts.get(block.placement, 0) + 1
            if block.loop_instance_id is not None:
                loop_key = f"{block.loop_axis or 'loop'}:{block.loop_instance_id}"
                by_kind = loop_instance_counts.setdefault(loop_key, {})
                by_kind[block.block_kind] = by_kind.get(block.block_kind, 0) + 1
        for dependency in projection.dependencies:
            if dependency.proof is None:
                proof_status_counts["missing"] = proof_status_counts.get("missing", 0) + 1
                continue
            proof_status_counts[dependency.proof.status] = (
                proof_status_counts.get(dependency.proof.status, 0) + 1
            )
            for proof_kind in dependency.proof.proven_by:
                proof_kind_counts[proof_kind] = proof_kind_counts.get(proof_kind, 0) + 1
            if dependency.proof.stream_plan_edge_ids:
                trace_len = len(dependency.proof.stream_plan_edge_ids)
                route_trace_lengths[trace_len] = route_trace_lengths.get(trace_len, 0) + 1

    return {
        "projection_count": len(projections),
        "stream_count": len(streams),
        "fiber_count": len(fiber_ids),
        "total_blocks": total_blocks,
        "total_dependencies": total_dependencies,
        "blocks_per_projection": sorted({len(projection.blocks) for projection in projections}),
        "dependencies_per_projection": sorted(
            {len(projection.dependencies) for projection in projections}
        ),
        "block_kind_counts": dict(sorted(block_kind_counts.items())),
        "placement_counts": dict(sorted(placement_counts.items())),
        "loop_instance_counts": {
            loop_key: dict(sorted(by_kind.items()))
            for loop_key, by_kind in sorted(loop_instance_counts.items())
        },
        "proof_status_counts": dict(sorted(proof_status_counts.items())),
        "proof_kind_counts": dict(sorted(proof_kind_counts.items())),
        "route_trace_lengths": dict(sorted(route_trace_lengths.items())),
    }


def probe_tile_micro_block_compat(
    projections: tuple[FiberBlockProjection, ...],
) -> dict[str, object]:
    """Probe how close projected blocks are to old TileMicroBlock rows.

    This is a validation-only gap report.  It deliberately returns plain data
    instead of constructing TileMicroBlock or a new compat IR class.
    """

    mapped_kind_counts: dict[str, int] = {}
    unsupported_kind_counts: dict[str, int] = {}
    missing_field_counts: dict[str, int] = {}
    notes_counts: dict[str, int] = {}
    example_rows: list[dict[str, object]] = []

    for projection in projections:
        for block in projection.blocks:
            row = _compat_probe_row(block)
            mapped_kind = row["compat_block_kind"]
            if mapped_kind is None:
                unsupported_kind_counts[block.block_kind] = (
                    unsupported_kind_counts.get(block.block_kind, 0) + 1
                )
            else:
                mapped_kind_counts[str(mapped_kind)] = mapped_kind_counts.get(str(mapped_kind), 0) + 1
            for field in row["missing_fields"]:
                missing_field_counts[str(field)] = missing_field_counts.get(str(field), 0) + 1
            for note in row["notes"]:
                notes_counts[str(note)] = notes_counts.get(str(note), 0) + 1
            if len(example_rows) < 12:
                example_rows.append(row)

    return {
        "projection_count": len(projections),
        "mapped_kind_counts": dict(sorted(mapped_kind_counts.items())),
        "unsupported_kind_counts": dict(sorted(unsupported_kind_counts.items())),
        "missing_field_counts": dict(sorted(missing_field_counts.items())),
        "notes_counts": dict(sorted(notes_counts.items())),
        "example_rows": example_rows,
    }


def summarize_legacy_like_sequence(
    projections: tuple[FiberBlockProjection, ...],
) -> dict[str, object]:
    """Return a validation-only old-shape sequence summary.

    The report is intentionally coarse: it groups projected fiber blocks by the
    old pre-loop / K-loop / post-loop rhythm and counts compatible old block
    kinds.  It does not define execution order and it does not create old
    TileMicroBlock objects.
    """

    pre_loop_counts: dict[str, int] = {}
    post_loop_counts: dict[str, int] = {}
    unsupported_post_loop_counts: dict[str, int] = {}
    k_loop_counts: dict[int, dict[str, int]] = {}
    k_loop_unsupported_counts: dict[int, dict[str, int]] = {}

    for projection in projections:
        for block in projection.blocks:
            compat_kind = _compat_block_kind(block.block_kind)
            if block.placement == "pre_loop":
                key = compat_kind or f"unsupported:{block.block_kind}"
                pre_loop_counts[key] = pre_loop_counts.get(key, 0) + 1
                continue
            if block.placement == "post_loop":
                if compat_kind is None:
                    unsupported_post_loop_counts[block.block_kind] = (
                        unsupported_post_loop_counts.get(block.block_kind, 0) + 1
                    )
                else:
                    post_loop_counts[compat_kind] = post_loop_counts.get(compat_kind, 0) + 1
                continue
            if block.placement == "loop_body" and block.loop_instance_id is not None:
                if compat_kind is None:
                    by_kind = k_loop_unsupported_counts.setdefault(block.loop_instance_id, {})
                    by_kind[block.block_kind] = by_kind.get(block.block_kind, 0) + 1
                else:
                    by_kind = k_loop_counts.setdefault(block.loop_instance_id, {})
                    by_kind[compat_kind] = by_kind.get(compat_kind, 0) + 1

    k_loop_counts = {
        k_index: dict(sorted(by_kind.items()))
        for k_index, by_kind in sorted(k_loop_counts.items())
    }
    k_loop_unsupported_counts = {
        k_index: dict(sorted(by_kind.items()))
        for k_index, by_kind in sorted(k_loop_unsupported_counts.items())
    }
    canonical_k_body_shapes = sorted({tuple(by_kind.items()) for by_kind in k_loop_counts.values()})
    return {
        "pre_loop_counts": dict(sorted(pre_loop_counts.items())),
        "k_loop_counts": k_loop_counts,
        "k_loop_unsupported_counts": k_loop_unsupported_counts,
        "post_loop_counts": dict(sorted(post_loop_counts.items())),
        "unsupported_post_loop_counts": dict(sorted(unsupported_post_loop_counts.items())),
        "canonical_k_body_shapes": [list(shape) for shape in canonical_k_body_shapes],
        "k_loop_is_uniform": len(canonical_k_body_shapes) <= 1,
    }


def project_fiber_to_blocks(
    fiber: Fiber,
    *,
    stream_plan: StreamPlan | None = None,
) -> FiberBlockProjection:
    """Project one flat Fiber into a conservative one-op/one-block view."""

    blocks: list[FiberBlock] = []
    block_by_op_id: dict[str, FiberBlock] = {}
    diagnostics: list[str] = []

    for op in fiber.ops:
        block = _block_from_op(op)
        blocks.append(block)
        block_by_op_id[op.id] = block

    dependencies: list[FiberBlockDependency] = []
    for op in fiber.ops:
        dst_block = block_by_op_id[op.id]
        for index, dependency in enumerate(op.depends_on):
            src_block = block_by_op_id.get(dependency.source_op_id)
            dependency_id = f"{dst_block.id}:dep{index:02d}"
            if src_block is None:
                diagnostics.append(
                    f"missing source block for dependency {dependency.source_op_id} -> {op.id}"
                )
                dependencies.append(
                    FiberBlockDependency(
                        id=dependency_id,
                        src_block_id=dependency.source_op_id,
                        dst_block_id=dst_block.id,
                        dependency_kind="semantic",
                        source_fiber_dependency_id=_dependency_id(op, dependency, index),
                        expected_satisfaction=dependency.expected_satisfaction,
                        proof=_proof(
                            op=op,
                            dependency=dependency,
                            dependency_id=_dependency_id(op, dependency, index),
                            status="unsatisfied",
                            src_block_id=dependency.source_op_id,
                            dst_block_id=dst_block.id,
                        ),
                    )
                )
                continue

            dependencies.append(
                FiberBlockDependency(
                    id=dependency_id,
                    src_block_id=src_block.id,
                    dst_block_id=dst_block.id,
                    dependency_kind="semantic",
                    source_fiber_dependency_id=_dependency_id(op, dependency, index),
                    expected_satisfaction=dependency.expected_satisfaction,
                    proof=_proof(
                        op=op,
                        dependency=dependency,
                        dependency_id=_dependency_id(op, dependency, index),
                        status=_proof_status(dependency, src_block, stream_plan),
                        src_block_id=src_block.id,
                        dst_block_id=dst_block.id,
                        src_block_kind=src_block.block_kind,
                        route_trace=_route_trace(src_block, stream_plan),
                    ),
                )
            )

    return FiberBlockProjection(
        fiber_id=fiber.id,
        stream_id=fiber.stream_id,
        blocks=tuple(blocks),
        dependencies=tuple(dependencies),
        diagnostics=tuple(diagnostics),
    )


def validate_fiber_block_projection(
    fiber: Fiber,
    projection: FiberBlockProjection,
) -> ProjectionValidationReport:
    """Validate the debug projection without making it a new source of truth."""

    diagnostics: list[str] = []
    fiber_op_ids = tuple(op.id for op in fiber.ops)
    block_source_ids = tuple(block.source_fiber_op_id for block in projection.blocks)

    missing = sorted(set(fiber_op_ids) - set(block_source_ids))
    extra = sorted(set(block_source_ids) - set(fiber_op_ids))
    if missing:
        diagnostics.append(f"fiber ops missing projected blocks: {missing}")
    if extra:
        diagnostics.append(f"blocks reference unknown fiber ops: {extra}")

    for op_id in fiber_op_ids:
        count = block_source_ids.count(op_id)
        if count != 1:
            diagnostics.append(f"fiber op {op_id} has {count} projected blocks; expected 1")

    block_ids = {block.id for block in projection.blocks}
    for dependency in projection.dependencies:
        if dependency.src_block_id not in block_ids:
            diagnostics.append(f"dependency {dependency.id} has unknown src block {dependency.src_block_id}")
        if dependency.dst_block_id not in block_ids:
            diagnostics.append(f"dependency {dependency.id} has unknown dst block {dependency.dst_block_id}")
        if dependency.proof is None:
            diagnostics.append(f"dependency {dependency.id} has no proof")
            continue
        if dependency.proof.status != "satisfied":
            diagnostics.append(
                f"dependency {dependency.id} proof is {dependency.proof.status}; expected satisfied"
            )
        if not dependency.proof.proven_by:
            diagnostics.append(f"dependency {dependency.id} has no proof mechanism")

    for diagnostic in projection.diagnostics:
        diagnostics.append(f"projection diagnostic: {diagnostic}")

    return ProjectionValidationReport(ok=not diagnostics, diagnostics=tuple(diagnostics))


def _compat_probe_row(block: FiberBlock) -> dict[str, object]:
    compat_block_kind = _compat_block_kind(block.block_kind)
    missing_fields: list[str] = []
    notes: list[str] = []

    if compat_block_kind is None:
        notes.append("no old TileMicroBlock block_kind equivalent")

    if block.placement == "loop_body":
        if block.loop_region_id is None:
            notes.append("loop_region_id can be synthesized from fiber_id for validation")
        if block.loop_axis is None:
            missing_fields.append("loop_axis")
        if block.loop_instance_id is None:
            missing_fields.append("loop_instance_id")
    if compat_block_kind in {"route_source_materialize", "route_forward"}:
        if not block.output_visibility_refs:
            notes.append("route visibility refs require synthetic fragment visibility ids")
    if compat_block_kind == "compute_update":
        if not block.input_fragments:
            missing_fields.append("input_value_refs")
        if not block.output_fragments:
            missing_fields.append("output_value_refs")
    if compat_block_kind == "tile_store":
        if not block.input_fragments:
            missing_fields.append("input_value_refs")

    if compat_block_kind == "route_forward" and block.block_kind == "fragment_route_recv":
        notes.append("old route_forward is sender-executed; fiber recv is endpoint visibility")

    return {
        "fiber_block_id": block.id,
        "source_fiber_op_id": block.source_fiber_op_id,
        "block_kind": block.block_kind,
        "compat_block_kind": compat_block_kind,
        "candidate_fields": {
            "block_id": f"compat:{block.id}",
            "processor": block.stream_id,
            "source_phase_id": _compat_source_phase(block),
            "loop_region_id": block.loop_region_id or (
                f"{block.fiber_id}:k_loop" if block.placement == "loop_body" else None
            ),
            "loop_instance_id": block.loop_instance_id,
            "loop_axis": block.loop_axis,
            "fold_policy": (
                "vendor_instance_repeat_candidate"
                if block.placement == "loop_body"
                else None
            ),
            "action_ids": (block.source_fiber_op_id,),
            "route_action_ids": (
                (block.source_fiber_op_id,)
                if compat_block_kind in {"route_source_materialize", "route_forward"}
                else ()
            ),
            "compute_action_ids": (
                (block.source_fiber_op_id,)
                if compat_block_kind in {"accumulator_prepare", "compute_update"}
                else ()
            ),
            "store_action_ids": (
                (block.source_fiber_op_id,)
                if compat_block_kind == "tile_store"
                else ()
            ),
            "input_visibility_refs": block.input_visibility_refs,
            "output_visibility_refs": block.output_visibility_refs,
            "input_value_refs": tuple(fragment.label() for fragment in block.input_fragments),
            "output_value_refs": tuple(fragment.label() for fragment in block.output_fragments),
        },
        "missing_fields": tuple(missing_fields),
        "notes": tuple(notes),
    }


def _compat_block_kind(block_kind: str) -> str | None:
    if block_kind == "fragment_sram_read":
        return "route_source_materialize"
    if block_kind == "fragment_route_recv":
        return "route_forward"
    if block_kind == "accumulator_prepare":
        return "accumulator_prepare"
    if block_kind == "gemm_update":
        return "compute_update"
    if block_kind == "store_fragment":
        return "tile_store"
    return None


def _compat_source_phase(block: FiberBlock) -> str | None:
    if block.block_kind in {"accumulator_prepare", "gemm_update"}:
        return "gemm"
    if block.block_kind == "store_fragment":
        return "store"
    return None


def _block_from_op(op: FiberOp) -> FiberBlock:
    placement = str(op.attrs.get("placement", "unknown"))
    loop_instance_id = _reduction_fragment_index(op)
    block_kind = _block_kind(op)
    visibility_ref = op.attrs.get("stream_visibility_action_id")
    visibility_refs = (str(visibility_ref),) if visibility_ref is not None else ()
    return FiberBlock(
        id=f"block:{op.id}",
        stream_id=op.stream_id,
        fiber_id=op.fiber_id,
        block_kind=block_kind,
        source_fiber_op_id=op.id,
        projection_origin="direct_fiber_op",
        placement=placement,
        loop_region_id=op.attrs.get("loop_region_id") if isinstance(op.attrs.get("loop_region_id"), str) else None,
        loop_axis=(
            str(op.attrs.get("loop_axis", "reduction_fragment"))
            if placement == "loop_body"
            else None
        ),
        loop_instance_id=loop_instance_id,
        input_fragments=op.inputs,
        output_fragments=op.outputs,
        input_visibility_refs=visibility_refs if op.op.startswith("fragment_") else (),
        output_visibility_refs=visibility_refs if op.op.startswith("fragment_") else (),
        attrs=dict(op.attrs),
    )


def _block_kind(op: FiberOp) -> str:
    if op.op == "fragment_sram_read":
        return "fragment_sram_read"
    if op.op == "fragment_route_push":
        return "fragment_route_push"
    if op.op == "fragment_route_recv":
        return "fragment_route_recv"
    return op.op


def _dependency_id(op: FiberOp, dependency: FiberDependency, index: int) -> str:
    return f"{op.id}:fiber_dep{index:02d}:{dependency.kind}"


def _proof_status(
    dependency: FiberDependency,
    src_block: FiberBlock,
    stream_plan: StreamPlan | None,
) -> ProofStatus:
    if dependency.expected_satisfaction == "route_or_local_materialization":
        if src_block.block_kind == "fragment_sram_read":
            return "satisfied"
        if src_block.block_kind == "fragment_route_recv" and _route_trace(src_block, stream_plan):
            return "satisfied"
        return "pending"
    if dependency.expected_satisfaction == "unresolved":
        return "pending"
    return "satisfied"


def _proof(
    *,
    op: FiberOp,
    dependency: FiberDependency,
    dependency_id: str,
    status: ProofStatus,
    src_block_id: str,
    dst_block_id: str,
    src_block_kind: str = "",
    route_trace: tuple[StreamAction, ...] = (),
) -> DependencyProof:
    proven_by: tuple[ProofKind, ...]
    loop_region_id = None
    loop_instance_ids: tuple[int, ...] = ()
    notes: tuple[str, ...] = ()

    if status == "unsatisfied":
        proven_by = ()
    elif dependency.expected_satisfaction == "subtask_order":
        proven_by = ("subtask_order",)
    elif dependency.expected_satisfaction == "loop_instance_order":
        proven_by = ("loop_instance_order",)
        loop_region_id = op.attrs.get("loop_region_id")
        if not isinstance(loop_region_id, str):
            loop_region_id = None
        reduction_fragment_index = _reduction_fragment_index(op)
        if reduction_fragment_index is not None:
            loop_instance_ids = (
                reduction_fragment_index - 1,
                reduction_fragment_index,
            )
    elif dependency.expected_satisfaction == "same_block_order":
        proven_by = ("same_block_order",)
    elif dependency.expected_satisfaction == "route_or_local_materialization":
        if src_block_kind == "fragment_sram_read":
            proven_by = ("block_order",)
            notes = ("fragment is produced by a local SRAM read block",)
        elif src_block_kind == "fragment_route_recv" and route_trace:
            proven_by = ("route_path",)
            notes = (
                "fragment visibility follows the selected StreamPlan action dependency trace",
            )
        else:
            proven_by = ()
            notes = ("fragment visibility is preserved but not route-proven in Phase 2",)
    else:
        proven_by = ("unresolved",)

    return DependencyProof(
        source_fiber_dependency_id=dependency_id,
        expected_satisfaction=dependency.expected_satisfaction,
        status=status,
        proven_by=proven_by,
        block_ids=(src_block_id, dst_block_id),
        stream_plan_edge_ids=tuple(action.id for action in route_trace),
        loop_region_id=loop_region_id,
        loop_instance_ids=loop_instance_ids,
        notes=notes,
    )


def _reduction_fragment_index(op: FiberOp) -> int | None:
    value = op.attrs.get("reduction_fragment_index")
    if isinstance(value, int):
        return value
    return None


def _route_trace(
    block: FiberBlock,
    stream_plan: StreamPlan | None,
) -> tuple[StreamAction, ...]:
    if stream_plan is None:
        return ()
    if block.block_kind != "fragment_route_recv":
        return ()
    if not block.output_visibility_refs:
        return ()
    action_id = block.output_visibility_refs[0]
    try:
        trace = stream_plan.trace_action_dependencies(action_id)
    except KeyError:
        return ()
    if not trace:
        return ()
    if not trace[-1].op.startswith("route_recv"):
        return ()
    return trace


__all__ = [
    "DependencyProof",
    "FiberBlock",
    "FiberBlockDependency",
    "FiberBlockProjection",
    "ProjectionValidationReport",
    "project_fiber_to_blocks",
    "probe_tile_micro_block_compat",
    "summarize_legacy_like_sequence",
    "summarize_fiber_block_projections",
    "validate_fiber_block_projection",
]
