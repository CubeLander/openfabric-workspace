#!/usr/bin/env python3
"""Focused validation for B-line report-only BinaryLayoutPlan."""

from __future__ import annotations

from gpdpu_compiler.core.op_specs import MATMUL_SPEC
from gpdpu_compiler.core.stream_compiler.binary_plan import (
    lower_template_ops_to_binary_layout,
    summarize_binary_layout_plan,
)
from gpdpu_compiler.core.stream_compiler.binding import bind_executable_roles_symbolically
from gpdpu_compiler.core.stream_compiler.blocks import project_fiber_to_blocks
from gpdpu_compiler.core.stream_compiler.dfu3500_semantics import (
    lower_template_records_to_dfu3500_semantics,
)
from gpdpu_compiler.core.stream_compiler.executable import lower_fibers_to_executable_ops
from gpdpu_compiler.core.stream_compiler.gemm_demo import (
    build_demo_fibers,
    build_demo_gemm_stream_plan,
)
from gpdpu_compiler.core.stream_compiler.schedule import build_fiber_execution_schedule
from gpdpu_compiler.core.stream_compiler.template_ops import lower_schedule_to_template_ops
from gpdpu_compiler.core.stream_compiler.template_records import (
    lower_symbolic_bindings_to_template_records,
)


EXPECTED_PHASE_INSTRUCTION_COUNTS = {
    "loop_body": 768,
    "post_loop": 64,
    "pre_loop": 64,
}

EXPECTED_ZERO_BOUNDARY_PHASE_COUNTS = {
    "post_loop": 64,
}

EXPECTED_SUBTASK_INSTRUCTION_COUNTS = {
    "subtask0_accumulator_prepare": 64,
    "subtask1_k_stream": 768,
    "subtask3_finalize_store": 64,
}

EXPECTED_TASK_INSTRUCTION_COUNTS = {
    0: 224,
    1: 224,
    2: 224,
    3: 224,
}

EXPECTED_OPCODE_COUNTS = {
    "ACC_PREPARE": 64,
    "HMMAL_OR_GEMM_UPDATE": 256,
    "LOAD_OR_COPY": 128,
    "ROUTE_RECV_VISIBILITY": 384,
    "STD": 64,
}


def main() -> None:
    stream_plan = build_demo_gemm_stream_plan()
    fibers = build_demo_fibers(stream_plan)
    projections = tuple(
        project_fiber_to_blocks(fiber, stream_plan=stream_plan)
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
    template_records = lower_symbolic_bindings_to_template_records(bindings)
    semantic_report = lower_template_records_to_dfu3500_semantics(template_records)
    schedule = build_fiber_execution_schedule(executable, semantic_report)
    template_plan = lower_schedule_to_template_ops(
        schedule,
        semantic_report=semantic_report,
        template_records=template_records,
    )
    layout = lower_template_ops_to_binary_layout(template_plan)
    summary = summarize_binary_layout_plan(layout)
    failures: list[str] = []

    if summary["runnability_state"] != "layout_candidate":
        failures.append(f"unexpected runnability state: {summary['runnability_state']}")
    if summary["validation_status"] != "valid":
        failures.append(f"unexpected validation status: {summary['validation_status']}")
    if summary["instruction_row_count"] != 896:
        failures.append(f"expected 896 instruction rows, got {summary['instruction_row_count']}")
    if summary["zero_instruction_boundary_count"] != 64:
        failures.append(
            "expected 64 zero-instruction boundaries, got "
            f"{summary['zero_instruction_boundary_count']}"
        )
    if summary["task_row_count"] != 4:
        failures.append(f"expected 4 task rows, got {summary['task_row_count']}")
    if summary["instance_row_count"] != 4:
        failures.append(f"expected 4 loop instance rows, got {summary['instance_row_count']}")
    if summary["phase_instruction_counts"] != EXPECTED_PHASE_INSTRUCTION_COUNTS:
        failures.append(f"unexpected phase instruction counts: {summary['phase_instruction_counts']}")
    if summary["zero_boundary_phase_counts"] != EXPECTED_ZERO_BOUNDARY_PHASE_COUNTS:
        failures.append(f"unexpected zero-boundary phase counts: {summary['zero_boundary_phase_counts']}")
    if summary["subtask_instruction_counts"] != EXPECTED_SUBTASK_INSTRUCTION_COUNTS:
        failures.append(f"unexpected subtask instruction counts: {summary['subtask_instruction_counts']}")
    if summary["task_instruction_counts"] != EXPECTED_TASK_INSTRUCTION_COUNTS:
        failures.append(f"unexpected task instruction counts: {summary['task_instruction_counts']}")
    if summary["opcode_counts"] != EXPECTED_OPCODE_COUNTS:
        failures.append(f"unexpected opcode counts: {summary['opcode_counts']}")
    if summary["duplicate_pc_count"] != 0:
        failures.append("layout has duplicate symbolic PCs")
    if summary["forbidden_tile_micro_block_field_count"] != 0:
        failures.append("layout rows contain forbidden TileMicroBlock provenance fields")
    if summary["diagnostic_severity_counts"] != {"warning": 128}:
        failures.append(
            "expected 128 report-only warnings for unresolved ReLU/candidate intents, got "
            f"{summary['diagnostic_severity_counts']}"
        )

    if any(row.role == "tile_op:relu" for row in layout.instruction_rows):
        failures.append("unresolved ReLU must not allocate instruction rows")
    if any(row.role == "accumulator_finalize" for row in layout.instruction_rows):
        failures.append("zero-instruction finalize must not allocate instruction rows")
    if any(boundary.to_plan()["pc"] is not None for boundary in layout.zero_instruction_boundaries):
        failures.append("zero-instruction boundaries must not have PCs")
    if any(boundary.role != "accumulator_finalize" for boundary in layout.zero_instruction_boundaries):
        failures.append("only accumulator_finalize should be zero-instruction in this profile")
    expected_pcs = list(range(len(layout.instruction_rows)))
    actual_pcs = [row.pc for row in layout.instruction_rows]
    if actual_pcs != expected_pcs:
        failures.append("symbolic PCs are not dense and deterministic")

    if failures:
        print("stream compiler BinaryLayoutPlan check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler BinaryLayoutPlan check OK")
    print(f"instruction_rows={summary['instruction_row_count']}")
    print(f"zero_boundaries={summary['zero_instruction_boundary_count']}")


if __name__ == "__main__":
    main()
