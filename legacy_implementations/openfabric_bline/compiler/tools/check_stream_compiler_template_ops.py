#!/usr/bin/env python3
"""Focused validation for B-line report-only TemplateOpPlan."""

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
from gpdpu_compiler.core.stream_compiler.schedule import build_fiber_execution_schedule
from gpdpu_compiler.core.stream_compiler.template_ops import (
    lower_schedule_to_template_ops,
    summarize_template_op_plan,
)
from gpdpu_compiler.core.stream_compiler.template_records import (
    lower_symbolic_bindings_to_template_records,
)


EXPECTED_STATUS_COUNTS = {
    "concrete_template": 896,
    "symbolic_unresolved": 64,
    "zero_instruction": 64,
}

EXPECTED_PHASE_COUNTS = {
    "loop_body": 768,
    "post_loop": 192,
    "pre_loop": 64,
}

EXPECTED_UNRESOLVED_ROLE_COUNTS = {
    "tile_op:relu": 64,
}

EXPECTED_INTENT_STATUS_COUNTS = {
    "candidate_unproven": 64,
    "concrete": 896,
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
    summary = summarize_template_op_plan(template_plan)
    failures: list[str] = []

    if summary["template_op_count"] != 1024:
        failures.append(f"expected 1024 TemplateOps, got {summary['template_op_count']}")
    if summary["unique_source_fiber_op_count"] != 1024:
        failures.append(
            "expected every TemplateOp to map to one unique FiberOp, got "
            f"{summary['unique_source_fiber_op_count']}"
        )
    if summary["runnability_state"] != "report_only":
        failures.append(f"unexpected runnability state: {summary['runnability_state']}")
    if summary["status_counts"] != EXPECTED_STATUS_COUNTS:
        failures.append(f"unexpected status counts: {summary['status_counts']}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected phase counts: {summary['phase_counts']}")
    if summary["unresolved_role_counts"] != EXPECTED_UNRESOLVED_ROLE_COUNTS:
        failures.append(f"unexpected unresolved roles: {summary['unresolved_role_counts']}")
    if summary["unsupported_role_counts"] != {}:
        failures.append(f"unexpected unsupported roles: {summary['unsupported_role_counts']}")
    if summary["intent_status_counts"] != EXPECTED_INTENT_STATUS_COUNTS:
        failures.append(f"unexpected intent status counts: {summary['intent_status_counts']}")
    if summary["forbidden_tile_micro_block_field_count"] != 0:
        failures.append("TemplateOps contain forbidden TileMicroBlock provenance fields")
    if summary["zero_instruction_with_instruction_row_count"] != 0:
        failures.append("zero-instruction TemplateOps allocated instruction intents")
    if summary["candidate_unproven_instruction_intent_count"] != 64:
        failures.append(
            "expected 64 candidate ReLU instruction intents to stay report-only, got "
            f"{summary['candidate_unproven_instruction_intent_count']}"
        )
    if summary["non_json_stable_attr_count"] != 0:
        failures.append("TemplateOp attrs are not JSON-stable")
    if summary["diagnostic_severity_counts"] != {"warning": 64}:
        failures.append(
            "expected 64 report-only warnings for unresolved ReLU, got "
            f"{summary['diagnostic_severity_counts']}"
        )

    first_op = template_plan.template_ops[0]
    if first_op.provenance.source_schedule_ordinal != 0:
        failures.append("first TemplateOp does not preserve schedule ordinal 0")
    if first_op.provenance.primary_fiber_op_id is None:
        failures.append("first TemplateOp is missing FiberOp provenance")
    if any(
        "tile_micro_block" in key
        for op in template_plan.template_ops
        for key, _value in op.attrs
    ):
        failures.append("TemplateOp attrs mention tile_micro_block")

    relu_ops = [
        op
        for op in template_plan.template_ops
        if op.role == "tile_op:relu"
    ]
    if len(relu_ops) != 64:
        failures.append(f"expected 64 ReLU TemplateOps, got {len(relu_ops)}")
    elif any(op.template_status != "symbolic_unresolved" for op in relu_ops):
        failures.append("ReLU TemplateOps must remain symbolic_unresolved")
    elif any(
        intent.intent_status != "candidate_unproven"
        for op in relu_ops
        for intent in op.instruction_intents
    ):
        failures.append("ReLU instruction intents must remain candidate_unproven")

    finalize_ops = [
        op
        for op in template_plan.template_ops
        if op.role == "accumulator_finalize"
    ]
    if len(finalize_ops) != 64:
        failures.append(f"expected 64 finalize TemplateOps, got {len(finalize_ops)}")
    elif any(op.template_status != "zero_instruction" for op in finalize_ops):
        failures.append("finalize TemplateOps must be zero_instruction")
    elif any(op.instruction_intents for op in finalize_ops):
        failures.append("zero-instruction finalize TemplateOps must not carry intents")

    if failures:
        print("stream compiler TemplateOpPlan check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler TemplateOpPlan check OK")
    print(f"template_ops={summary['template_op_count']}")
    print(f"status_counts={summary['status_counts']}")


if __name__ == "__main__":
    main()
