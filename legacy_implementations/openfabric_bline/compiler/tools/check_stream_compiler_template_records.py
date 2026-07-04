#!/usr/bin/env python3
"""Focused validation for B-line symbolic template records."""

from __future__ import annotations

from gpdpu_compiler.core.op_specs import MATMUL_SPEC
from gpdpu_compiler.core.stream_compiler.binding import bind_executable_roles_symbolically
from gpdpu_compiler.core.stream_compiler.blocks import project_fiber_to_blocks
from gpdpu_compiler.core.stream_compiler.executable import lower_fibers_to_executable_ops
from gpdpu_compiler.core.stream_compiler.gemm_demo import (
    build_demo_fibers,
    build_demo_gemm_stream_plan,
)
from gpdpu_compiler.core.stream_compiler.template_records import (
    lower_symbolic_bindings_to_template_records,
    summarize_template_record_program,
)


EXPECTED_STATUS_COUNTS = {
    "symbolic_only": 128,
    "template_candidate": 896,
}

EXPECTED_STAGE_COUNTS = {
    "loop_body": 768,
    "post_loop": 192,
    "pre_loop": 64,
}

EXPECTED_TEMPLATE_ROLE_COUNTS = {
    "accumulator_prepare": 64,
    "compute_update": 256,
    "route_forward": 384,
    "route_source_materialize": 128,
    "tile_store": 64,
}

EXPECTED_SYMBOLIC_ROLE_COUNTS = {
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
    records = lower_symbolic_bindings_to_template_records(bindings)
    summary = summarize_template_record_program(records)
    failures: list[str] = []

    if summary["record_count"] != 1024:
        failures.append(f"expected 1024 template records, got {summary['record_count']}")
    if summary["status_counts"] != EXPECTED_STATUS_COUNTS:
        failures.append(f"unexpected record status counts: {summary['status_counts']}")
    if summary["stage_counts"] != EXPECTED_STAGE_COUNTS:
        failures.append(f"unexpected stage counts: {summary['stage_counts']}")
    if summary["template_role_counts"] != EXPECTED_TEMPLATE_ROLE_COUNTS:
        failures.append(f"unexpected template role counts: {summary['template_role_counts']}")
    if summary["symbolic_role_counts"] != EXPECTED_SYMBOLIC_ROLE_COUNTS:
        failures.append(f"unexpected symbolic role counts: {summary['symbolic_role_counts']}")
    if summary["emission_status_counts"] != {"symbolic_report_only": 1024}:
        failures.append(f"unexpected emission status counts: {summary['emission_status_counts']}")
    if summary["forbidden_tile_micro_block_field_count"] != 0:
        failures.append("template records contain forbidden TileMicroBlock provenance fields")
    if summary["diagnostic_count"] != 0:
        failures.append(f"unexpected template record diagnostics: {records.diagnostics}")

    if failures:
        print("stream compiler template record check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler template record check OK")
    print(f"records={summary['record_count']}")


if __name__ == "__main__":
    main()
