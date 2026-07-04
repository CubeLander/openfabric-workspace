#!/usr/bin/env python3
"""Focused validation for B-line executable-role symbolic binding."""

from __future__ import annotations

from gpdpu_compiler.core.op_specs import MATMUL_SPEC
from gpdpu_compiler.core.stream_compiler.binding import (
    bind_executable_roles_symbolically,
    summarize_role_binding_program,
)
from gpdpu_compiler.core.stream_compiler.blocks import project_fiber_to_blocks
from gpdpu_compiler.core.stream_compiler.executable import lower_fibers_to_executable_ops
from gpdpu_compiler.core.stream_compiler.gemm_demo import (
    build_demo_fibers,
    build_demo_gemm_stream_plan,
)


EXPECTED_STATUS_COUNTS = {
    "legacy_template_candidate": 896,
    "symbolic_unsupported": 128,
}

EXPECTED_TEMPLATE_ROLE_COUNTS = {
    "accumulator_prepare": 64,
    "compute_update": 256,
    "route_forward": 384,
    "route_source_materialize": 128,
    "tile_store": 64,
}

EXPECTED_UNSUPPORTED_ROLE_COUNTS = {
    "accumulator_finalize": 64,
    "tile_op:relu": 64,
}


def main() -> None:
    plan = build_demo_gemm_stream_plan()
    fibers = build_demo_fibers(plan)
    projections = tuple(
        project_fiber_to_blocks(fiber, stream_plan=plan)
        for fiber in fibers
    )
    executable = lower_fibers_to_executable_ops(
        fibers,
        projections=projections,
        executable_role_profile=MATMUL_SPEC.executable_role_profile(),
    )
    bindings = bind_executable_roles_symbolically(
        executable,
        template_intents=MATMUL_SPEC.template_intent_profile(),
    )
    summary = summarize_role_binding_program(bindings)
    failures: list[str] = []

    if summary["binding_count"] != 1024:
        failures.append(f"expected 1024 bindings, got {summary['binding_count']}")
    if summary["status_counts"] != EXPECTED_STATUS_COUNTS:
        failures.append(f"unexpected binding status counts: {summary['status_counts']}")
    if summary["template_role_counts"] != EXPECTED_TEMPLATE_ROLE_COUNTS:
        failures.append(f"unexpected template role counts: {summary['template_role_counts']}")
    if summary["unsupported_role_counts"] != EXPECTED_UNSUPPORTED_ROLE_COUNTS:
        failures.append(f"unexpected unsupported role counts: {summary['unsupported_role_counts']}")
    if summary["forbidden_tile_micro_block_field_count"] != 0:
        failures.append("symbolic bindings contain forbidden TileMicroBlock provenance fields")
    if summary["diagnostic_count"] != 0:
        failures.append(f"unexpected binding diagnostics: {bindings.diagnostics}")

    if failures:
        print("stream compiler role binding check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler role binding check OK")
    print(f"bindings={summary['binding_count']}")


if __name__ == "__main__":
    main()
