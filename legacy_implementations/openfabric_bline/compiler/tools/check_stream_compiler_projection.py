#!/usr/bin/env python3
"""Focused validation for the experimental stream compiler projection.

This is intentionally a small check script rather than a production compiler
pass.  The block projection is a validation microscope for the stream/fiber
branch; it must not become the main lowering source of truth.
"""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.blocks import (
    probe_tile_micro_block_compat,
    project_fiber_to_blocks,
    summarize_fiber_block_projections,
    summarize_legacy_like_sequence,
    validate_fiber_block_projection,
)
from gpdpu_compiler.core.stream_compiler.gemm_demo import (
    build_demo_fibers,
    build_demo_gemm_stream_plan,
)


def main() -> None:
    plan = build_demo_gemm_stream_plan()
    fibers = build_demo_fibers(plan)
    failures: list[str] = []

    if len(fibers) != 64:
        failures.append(f"expected 64 demo fibers, got {len(fibers)}")
    _check_stream_plan_fragment_axes(plan, failures)

    expected_profile_step_ids = {
        "accumulator_prepare",
        "finalize_accumulator",
        "gemm_update",
        "materialize_A",
        "materialize_B",
        "store_fragment",
    }
    expected_step_order = (
        "accumulator_prepare",
        "materialize_A",
        "materialize_B",
        "gemm_update",
        "finalize_accumulator",
        "store_fragment",
    )
    seen_profile_step_ids: set[str] = set()
    seen_route_path = False
    seen_local_read = False
    saw_reduction_fragment_axis = False
    saw_reduction_fragment_index = False
    projections = []
    for fiber in fibers:
        if (
            fiber.attrs.get("fiber_pattern_plan")
            != "matmul_sequential_reduction_transitional"
        ):
            failures.append(
                f"{fiber.id}: expected stream-owned fiber pattern provenance, "
                f"got {fiber.attrs.get('fiber_pattern_plan')!r}"
            )
        if fiber.attrs.get("fiber_pattern_step_order") != expected_step_order:
            failures.append(
                f"{fiber.id}: unexpected pattern step order "
                f"{fiber.attrs.get('fiber_pattern_step_order')!r}"
            )
        for op in fiber.ops:
            step_id = op.attrs.get("profile_step_id")
            profile_role = op.attrs.get("profile_role")
            for fragment in (*op.inputs, *op.outputs):
                axes = {axis for axis, _value in fragment.axes}
                if "k_block" in axes:
                    failures.append(
                        f"{op.id}: fragment coordinate leaked schedule-ish k_block: "
                        f"{fragment}"
                    )
                if "reduction_fragment" in axes:
                    saw_reduction_fragment_axis = True
            if op.attrs.get("placement") == "loop_body" and "k_block" in op.attrs:
                failures.append(f"{op.id}: FiberOp leaked projection-only k_block attr")
            if (
                op.attrs.get("placement") == "loop_body"
                and isinstance(op.attrs.get("reduction_fragment_index"), int)
            ):
                saw_reduction_fragment_index = True
            if not isinstance(step_id, str):
                failures.append(f"{op.id}: missing profile_step_id")
            else:
                seen_profile_step_ids.add(step_id)
            if not isinstance(profile_role, str):
                failures.append(f"{op.id}: missing profile_role")
        projection = project_fiber_to_blocks(fiber, stream_plan=plan)
        projections.append(projection)
        report = validate_fiber_block_projection(fiber, projection)
        if not report.ok:
            failures.extend(f"{fiber.id}: {diagnostic}" for diagnostic in report.diagnostics)

        if len(projection.blocks) != len(fiber.ops):
            failures.append(
                f"{fiber.id}: expected one block per fiber op; "
                f"ops={len(fiber.ops)} blocks={len(projection.blocks)}"
            )

        for dependency in projection.dependencies:
            if dependency.proof is None:
                failures.append(f"{fiber.id}: dependency {dependency.id} has no proof")
                continue
            if "route_path" in dependency.proof.proven_by:
                seen_route_path = True
            if "block_order" in dependency.proof.proven_by:
                seen_local_read = True

    if not seen_route_path:
        failures.append("expected at least one route_path proof")
    if not seen_local_read:
        failures.append("expected at least one local SRAM/block_order proof")
    if seen_profile_step_ids != expected_profile_step_ids:
        failures.append(
            "unexpected profile step ids: "
            f"{sorted(seen_profile_step_ids)}"
        )
    if not saw_reduction_fragment_axis:
        failures.append("expected fiber value coordinates to use reduction_fragment")
    if not saw_reduction_fragment_index:
        failures.append("expected loop body attrs to carry reduction_fragment_index")

    aggregate = summarize_fiber_block_projections(tuple(projections))
    expected_block_counts = {
        "accumulator_prepare": 64,
        "finalize_accumulator": 64,
        "fragment_route_recv": 384,
        "fragment_sram_read": 128,
        "gemm_update": 256,
        "store_fragment": 64,
    }
    if aggregate["block_kind_counts"] != expected_block_counts:
        failures.append(
            "unexpected aggregate block counts: "
            f"{aggregate['block_kind_counts']}"
        )
    if aggregate["placement_counts"] != {
        "loop_body": 768,
        "post_loop": 128,
        "pre_loop": 64,
    }:
        failures.append(
            "unexpected placement counts: "
            f"{aggregate['placement_counts']}"
        )
    if aggregate["proof_status_counts"] != {"satisfied": 896}:
        failures.append(
            "unexpected proof status counts: "
            f"{aggregate['proof_status_counts']}"
        )
    if aggregate["route_trace_lengths"] != {3: 128, 5: 128, 7: 128}:
        failures.append(
            "unexpected route trace lengths: "
            f"{aggregate['route_trace_lengths']}"
        )

    compat_probe = probe_tile_micro_block_compat(tuple(projections))
    if compat_probe["mapped_kind_counts"] != {
        "accumulator_prepare": 64,
        "compute_update": 256,
        "route_forward": 384,
        "route_source_materialize": 128,
        "tile_store": 64,
    }:
        failures.append(
            "unexpected compat mapped kind counts: "
            f"{compat_probe['mapped_kind_counts']}"
        )
    if compat_probe["unsupported_kind_counts"] != {"finalize_accumulator": 64}:
        failures.append(
            "unexpected compat unsupported kind counts: "
            f"{compat_probe['unsupported_kind_counts']}"
        )

    legacy_like = summarize_legacy_like_sequence(tuple(projections))
    if legacy_like["pre_loop_counts"] != {"accumulator_prepare": 64}:
        failures.append(
            "unexpected legacy-like pre-loop counts: "
            f"{legacy_like['pre_loop_counts']}"
        )
    if not legacy_like["k_loop_is_uniform"]:
        failures.append("expected uniform legacy-like K-loop body shape")
    expected_k_body = [
        [
            ("compute_update", 64),
            ("route_forward", 96),
            ("route_source_materialize", 32),
        ]
    ]
    if legacy_like["canonical_k_body_shapes"] != expected_k_body:
        failures.append(
            "unexpected legacy-like K body shape: "
            f"{legacy_like['canonical_k_body_shapes']}"
        )
    if legacy_like["post_loop_counts"] != {"tile_store": 64}:
        failures.append(
            "unexpected legacy-like post-loop counts: "
            f"{legacy_like['post_loop_counts']}"
        )
    if legacy_like["unsupported_post_loop_counts"] != {"finalize_accumulator": 64}:
        failures.append(
            "unexpected legacy-like unsupported post-loop counts: "
            f"{legacy_like['unsupported_post_loop_counts']}"
        )

    no_relu_fibers = build_demo_fibers(plan)
    no_relu_op_count = sum(len(fiber.ops) for fiber in no_relu_fibers)
    if no_relu_op_count != 960:
        failures.append(f"expected 960 no-ReLU fiber ops, got {no_relu_op_count}")
    if any(
        "relu" in str(op.op).lower()
        or "relu" in str(op.attrs.get("profile_step_id", "")).lower()
        for fiber in no_relu_fibers
        for op in fiber.ops
    ):
        failures.append("GEMM fibers must not materialize ReLU operations")

    if failures:
        print("stream compiler projection check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler projection check OK")
    print(f"fibers={len(fibers)}")
    print(f"blocks={aggregate['total_blocks']}")


def _check_stream_plan_fragment_axes(
    plan: object,
    failures: list[str],
) -> None:
    saw_reduction_fragment_axis = False
    for value in plan.visible_values.values():  # type: ignore[attr-defined]
        tile_axes = value.attrs.get("tile_axes")
        if not isinstance(tile_axes, tuple):
            continue
        if "k_block" in tile_axes:
            failures.append(
                f"{value.id}: StreamPlan tile_axes leaked schedule-ish k_block: "
                f"{tile_axes}"
            )
        if "reduction_fragment" in tile_axes:
            saw_reduction_fragment_axis = True
    if not saw_reduction_fragment_axis:
        failures.append("expected StreamPlan tile_axes to use reduction_fragment")


if __name__ == "__main__":
    main()
