#!/usr/bin/env python3
"""Focused validation for B-line DFU3500 role semantic reports."""

from __future__ import annotations

from gpdpu_compiler.core.op_specs import MATMUL_SPEC
from gpdpu_compiler.core.stream_compiler.binding import bind_executable_roles_symbolically
from gpdpu_compiler.core.stream_compiler.blocks import project_fiber_to_blocks
from gpdpu_compiler.core.stream_compiler.dfu3500_semantics import (
    lower_template_records_to_dfu3500_semantics,
    summarize_dfu3500_semantic_report,
)
from gpdpu_compiler.core.stream_compiler.executable import lower_fibers_to_executable_ops
from gpdpu_compiler.core.stream_compiler.gemm_demo import (
    build_demo_fibers,
    build_demo_gemm_stream_plan,
)
from gpdpu_compiler.core.stream_compiler.template_records import (
    lower_symbolic_bindings_to_template_records,
)


EXPECTED_PROOF_STATUS_COUNTS = {
    "proven": 960,
    "unproven": 64,
}

EXPECTED_SEMANTIC_KIND_COUNTS = {
    "accumulator_boundary": 64,
    "accumulator_prepare": 64,
    "gemm_k_update": 256,
    "local_elementwise_tile_op": 64,
    "operand_materialization": 128,
    "operand_route_visibility": 384,
    "tile_store": 64,
}

EXPECTED_UNPROVEN_ROLE_COUNTS = {
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
    report = lower_template_records_to_dfu3500_semantics(records)
    summary = summarize_dfu3500_semantic_report(report)
    failures: list[str] = []

    if summary["record_count"] != 1024:
        failures.append(f"expected 1024 semantic records, got {summary['record_count']}")
    if summary["proof_status_counts"] != EXPECTED_PROOF_STATUS_COUNTS:
        failures.append(f"unexpected proof status counts: {summary['proof_status_counts']}")
    if summary["semantic_kind_counts"] != EXPECTED_SEMANTIC_KIND_COUNTS:
        failures.append(f"unexpected semantic kind counts: {summary['semantic_kind_counts']}")
    if summary["unproven_role_counts"] != EXPECTED_UNPROVEN_ROLE_COUNTS:
        failures.append(f"unexpected unproven role counts: {summary['unproven_role_counts']}")
    if summary["forbidden_tile_micro_block_field_count"] != 0:
        failures.append("DFU3500 semantic records contain forbidden TileMicroBlock provenance fields")
    if summary["diagnostic_count"] != 0:
        failures.append(f"unexpected semantic diagnostics: {report.diagnostics}")

    if failures:
        print("stream compiler DFU3500 semantics check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler DFU3500 semantics check OK")
    print(f"records={summary['record_count']}")


if __name__ == "__main__":
    main()
