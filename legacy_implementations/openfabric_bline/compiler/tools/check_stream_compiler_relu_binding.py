#!/usr/bin/env python3
"""Check that ReLU-inside-GEMM-fiber binding is disabled fail-closed."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.relu_binding import (
    bind_explicit_relu_subtasks,
    summarize_explicit_relu_subtask_binding_report,
)
from gpdpu_compiler.core.stream_compiler.template_ops import (
    summarize_template_op_plan,
)
from stream_compiler_demo_pipeline import build_demo_pipeline


EXPECTED_TEMPLATE_STATUS_COUNTS = {
    "concrete_template": 128,
}

EXPECTED_RELU_BLOCKERS = [
    "expected 64 ReLU TemplateOps, got 0",
    (
        "explicit ReLU subtask rows are not runnable until the shortest "
        "evidence path closes: relu_dtype_selection, "
        "zero_constant_materialization, template_row_evidence, "
        "store_operand_lifetime"
    ),
]


def main() -> None:
    artifacts = build_demo_pipeline("gemm_relu")
    template_summary = summarize_template_op_plan(artifacts.template_plan)
    relu_report = bind_explicit_relu_subtasks(artifacts.template_plan)
    relu_summary = summarize_explicit_relu_subtask_binding_report(relu_report)
    diagnostic_codes = {
        diagnostic.code
        for diagnostic in artifacts.template_plan.diagnostics
    }
    failures: list[str] = []

    if artifacts.binary_layout.runnability_state != "bline_atomic_fiber_op_chain_missing":
        failures.append(
            "gemm_relu pipeline must be marked bline_atomic_fiber_op_chain_missing, got "
            f"{artifacts.binary_layout.runnability_state}"
        )
    if "gemm_relu_inside_gemm_fiber_disabled" not in diagnostic_codes:
        failures.append("missing gemm_relu_inside_gemm_fiber_disabled diagnostic")
    if template_summary["status_counts"] != EXPECTED_TEMPLATE_STATUS_COUNTS:
        failures.append(
            f"unexpected TemplateOp statuses: {template_summary['status_counts']}"
        )
    if template_summary["unresolved_role_counts"] != {}:
        failures.append(
            "GEMM+ReLU disabled path should not leave unresolved templates "
            "before explicit ReLU op-chain is connected, got "
            f"{template_summary['unresolved_role_counts']}"
        )
    if template_summary["candidate_unproven_instruction_intent_count"] != 0:
        failures.append(
            "GEMM fiber path must not emit candidate ReLU instruction intents, got "
            f"{template_summary['candidate_unproven_instruction_intent_count']}"
        )

    if relu_summary["binding_status"] != "fail_closed":
        failures.append(
            f"expected fail_closed ReLU report, got {relu_summary['binding_status']}"
        )
    if relu_summary["binding_count"] != 0:
        failures.append(
            "disabled GEMM fiber path must not produce ReLU bindings, got "
            f"{relu_summary['binding_count']}"
        )
    if relu_summary["symbolic_relu_template_count"] != 0:
        failures.append(
            "disabled GEMM fiber path must not produce symbolic ReLU templates, got "
            f"{relu_summary['symbolic_relu_template_count']}"
        )
    if relu_summary["store_dependency_count"] != 0:
        failures.append(
            "disabled GEMM fiber path must not report ReLU store dependencies, got "
            f"{relu_summary['store_dependency_count']}"
        )
    if relu_summary["pre_relu_store_forbidden_count"] != 0:
        failures.append(
            "GEMM+ReLU disabled path must not invent ReLU store-bypass proofs, got "
            f"{relu_summary['pre_relu_store_forbidden_count']}"
        )
    if relu_summary["blockers"] != EXPECTED_RELU_BLOCKERS:
        failures.append(f"unexpected blockers: {relu_summary['blockers']}")
    if relu_summary["diagnostic_severity_counts"] != {"error": 3}:
        failures.append(
            "expected disabled-path diagnostic shape {'error': 3}, got "
            f"{relu_summary['diagnostic_severity_counts']}"
        )

    if failures:
        print("stream compiler ReLU disabled-path check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler ReLU disabled-path check OK")
    print(f"runnability_state={artifacts.binary_layout.runnability_state}")
    print(f"template_status_counts={template_summary['status_counts']}")
    print(f"binding_status={relu_summary['binding_status']}")
    print(f"relu_bindings={relu_summary['binding_count']}")
    print(f"pre_relu_store_forbidden_count={relu_summary['pre_relu_store_forbidden_count']}")


if __name__ == "__main__":
    main()
