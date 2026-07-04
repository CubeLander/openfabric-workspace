#!/usr/bin/env python3
"""Focused validation for B-line FiberOp -> ExecutableFiberOp lowering."""

from __future__ import annotations

from gpdpu_compiler.core.op_specs import MATMUL_SPEC
from gpdpu_compiler.core.stream_compiler.blocks import project_fiber_to_blocks
from gpdpu_compiler.core.stream_compiler.executable import (
    lower_fibers_to_executable_ops,
    summarize_executable_program,
)
from gpdpu_compiler.core.stream_compiler.gemm_demo import (
    build_demo_fibers,
    build_demo_gemm_stream_plan,
)


EXPECTED_ROLE_COUNTS = {
    "accumulator_finalize": 64,
    "accumulator_prepare": 64,
    "compute_core:gemm_update": 256,
    "tile_op:relu": 64,
    "operand_materialize:A": 64,
    "operand_materialize:B": 64,
    "operand_route_recv:A": 192,
    "operand_route_recv:B": 192,
    "tile_store": 64,
}


def main() -> None:
    plan = build_demo_gemm_stream_plan()
    fibers = build_demo_fibers(plan)
    projections = tuple(
        project_fiber_to_blocks(fiber, stream_plan=plan)
        for fiber in fibers
    )
    program = lower_fibers_to_executable_ops(
        fibers,
        projections=projections,
        executable_role_profile=MATMUL_SPEC.executable_role_profile(),
    )
    summary = summarize_executable_program(program)
    failures: list[str] = []

    if summary["executable_op_count"] != 1024:
        failures.append(f"expected 1024 executable ops, got {summary['executable_op_count']}")
    if summary["unique_source_fiber_op_count"] != 1024:
        failures.append(
            "expected 1024 unique source FiberOps, got "
            f"{summary['unique_source_fiber_op_count']}"
        )
    if summary["role_counts"] != EXPECTED_ROLE_COUNTS:
        failures.append(f"unexpected role counts: {summary['role_counts']}")
    if summary["forbidden_tile_micro_block_field_count"] != 0:
        failures.append(
            "B-line executable ops contain forbidden TileMicroBlock provenance fields"
        )
    if summary["diagnostic_count"] != 0:
        failures.append(f"unexpected executable diagnostics: {program.diagnostics}")
    if summary["proof_status_counts"] != {"satisfied": 960}:
        failures.append(f"unexpected proof status counts: {summary['proof_status_counts']}")
    if summary["role_counts"].get("accumulator_finalize") != 64:
        failures.append("accumulator_finalize role disappeared")
    if summary["role_counts"].get("tile_op:relu") != 64:
        failures.append("tile_op:relu role disappeared")
    _check_reduction_fragment_index_policy(program, failures)

    if failures:
        print("stream compiler executable check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler executable check OK")
    print(f"executable_ops={summary['executable_op_count']}")


def _check_reduction_fragment_index_policy(program: object, failures: list[str]) -> None:
    saw_reduction_fragment_index = False
    saw_projection_compat_k_block = False
    for op in program.executable_ops:  # type: ignore[attr-defined]
        if op.placement != "loop_body":
            continue
        if not isinstance(op.attrs.get("reduction_fragment_index"), int):
            failures.append(
                f"{op.id}: loop executable op lacks reduction_fragment_index"
            )
        else:
            saw_reduction_fragment_index = True
        if "k_block" in op.attrs:
            saw_projection_compat_k_block = True
        if op.loop_axis != "reduction_fragment":
            failures.append(f"{op.id}: unexpected loop axis {op.loop_axis!r}")
    if not saw_reduction_fragment_index:
        failures.append("expected loop executable ops to carry reduction_fragment_index")
    if not saw_projection_compat_k_block:
        failures.append("expected loop executable ops to retain k_block compatibility attr")


if __name__ == "__main__":
    main()
