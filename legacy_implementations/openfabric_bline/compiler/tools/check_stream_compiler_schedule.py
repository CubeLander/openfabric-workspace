#!/usr/bin/env python3
"""Focused validation for B-line fiber execution schedule rows."""

from __future__ import annotations

from gpdpu_compiler.core.op_specs import MATMUL_SPEC
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
from gpdpu_compiler.core.stream_compiler.schedule import (
    FiberScheduleStep,
    RawFiberExecutionSchedule,
    build_fiber_execution_schedule,
    summarize_fiber_execution_schedule,
    verify_fiber_execution_schedule,
)
from gpdpu_compiler.core.stream_compiler.template_records import (
    lower_symbolic_bindings_to_template_records,
)


EXPECTED_PHASE_COUNTS = {
    "loop_body": 768,
    "post_loop": 192,
    "pre_loop": 64,
}

EXPECTED_LOOP_INSTANCE_COUNTS = {
    "k0": 192,
    "k1": 192,
    "k2": 192,
    "k3": 192,
}

EXPECTED_PROOF_STATUS_COUNTS = {
    "proven": 960,
    "unproven": 64,
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
    template_records = lower_symbolic_bindings_to_template_records(bindings)
    semantic_report = lower_template_records_to_dfu3500_semantics(template_records)
    raw_schedule = build_fiber_execution_schedule(executable, semantic_report)
    schedule = verify_fiber_execution_schedule(raw_schedule)
    summary = summarize_fiber_execution_schedule(schedule)
    failures: list[str] = []

    if summary["step_count"] != 1024:
        failures.append(f"expected 1024 schedule steps, got {summary['step_count']}")
    if summary["fiber_count"] != 64:
        failures.append(f"expected 64 fibers, got {summary['fiber_count']}")
    if summary["steps_per_fiber"] != [16]:
        failures.append(f"expected 16 steps per fiber, got {summary['steps_per_fiber']}")
    if summary["dependency_ref_count"] != 960:
        failures.append(f"expected 960 dependency refs, got {summary['dependency_ref_count']}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected phase counts: {summary['phase_counts']}")
    if summary["loop_instance_counts"] != EXPECTED_LOOP_INSTANCE_COUNTS:
        failures.append(f"unexpected loop instance counts: {summary['loop_instance_counts']}")
    if summary["proof_status_counts"] != EXPECTED_PROOF_STATUS_COUNTS:
        failures.append(f"unexpected proof status counts: {summary['proof_status_counts']}")
    if summary["unproven_role_counts"] != EXPECTED_UNPROVEN_ROLE_COUNTS:
        failures.append(f"unexpected unproven role counts: {summary['unproven_role_counts']}")
    if summary["forbidden_tile_micro_block_field_count"] != 0:
        failures.append("schedule rows contain forbidden TileMicroBlock provenance fields")
    if summary["diagnostic_count"] != 0:
        failures.append(f"unexpected schedule diagnostics: {schedule.diagnostics}")
    if schedule.verifier_diagnostics:
        failures.append(
            f"unexpected schedule verifier diagnostics: {schedule.verifier_diagnostics}"
        )
    if schedule.validation_statuses != (
        "constructed",
        "binding_verified",
        "resource_verified",
    ):
        failures.append(
            f"unexpected schedule validation statuses: {schedule.validation_statuses}"
        )

    first_fiber_steps = [
        step
        for step in schedule.steps
        if step.source_fiber_id == schedule.steps[0].source_fiber_id
    ]
    first_roles = [step.role for step in first_fiber_steps]
    expected_first_roles = [
        "accumulator_prepare",
        "operand_materialize:A",
        "operand_materialize:B",
        "compute_core:gemm_update",
        "operand_materialize:A",
        "operand_materialize:B",
        "compute_core:gemm_update",
        "operand_materialize:A",
        "operand_materialize:B",
        "compute_core:gemm_update",
        "operand_materialize:A",
        "operand_materialize:B",
        "compute_core:gemm_update",
        "accumulator_finalize",
        "tile_op:relu",
        "tile_store",
    ]
    if first_roles != expected_first_roles:
        failures.append(f"unexpected first fiber role order: {first_roles}")
    invalid_schedule = RawFiberExecutionSchedule(
        steps=(
            FiberScheduleStep(
                id="schedule:invalid",
                executable_op_id="exe:invalid",
                source_fiber_id="fiber:invalid",
                source_fiber_op_id="fiber_op:invalid",
                source_order_index=0,
                stream_id="stream:invalid",
                role="compute_core:synthetic",
                phase="loop_body",
                loop_axis="synthetic",
                loop_instance_key=None,
            ),
        ),
    )
    invalid_validated = verify_fiber_execution_schedule(invalid_schedule)
    if invalid_validated.validation_statuses != ("constructed",):
        failures.append("invalid schedule unexpectedly passed verifier status gates")
    if not any(
        "lacks region instance key" in diagnostic
        for diagnostic in invalid_validated.verifier_diagnostics
    ):
        failures.append(
            "invalid schedule did not report missing region instance key"
        )

    if failures:
        print("stream compiler schedule check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler schedule check OK")
    print(f"steps={summary['step_count']}")


if __name__ == "__main__":
    main()
