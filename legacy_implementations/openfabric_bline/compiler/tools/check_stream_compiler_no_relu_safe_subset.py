#!/usr/bin/env python3
"""Focused validation for the B-line GEMM fiber subset.

This check proves the current fiber invariant: GEMM fibers are GEMM-only and
must not contain ReLU or any downstream tile op-chain action.
"""

from __future__ import annotations

from gpdpu_compiler.core.op_specs import MATMUL_SPEC
from gpdpu_compiler.core.stream_compiler.aline_gemm_evidence import (
    build_aline_gemm_evidence_report,
)
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
from gpdpu_compiler.core.stream_compiler.inst_writers import (
    build_aline_template_span_candidate_report,
    build_compressed_template_span_authority_report,
    build_exact_span_row_selector_policy_report,
    build_exact_template_span_hash_candidate_report,
    build_template_span_materialization_candidate_report,
    summarize_template_span_materialization_candidate_report,
    summarize_exact_span_row_selector_policy_report,
)
from gpdpu_compiler.core.stream_compiler.schedule import build_fiber_execution_schedule
from gpdpu_compiler.core.stream_compiler.template_ops import (
    lower_schedule_to_template_ops,
    summarize_template_op_plan,
)
from gpdpu_compiler.core.stream_compiler.template_records import (
    lower_symbolic_bindings_to_template_records,
)


EXPECTED_TEMPLATE_STATUS_COUNTS = {
    "concrete_template": 128,
}

EXPECTED_BINARY_PHASE_COUNTS = {
    "tile_body": 64,
    "tile_store": 64,
}

EXPECTED_MATERIALIZATION_KIND_COUNTS = {
    "atomic_fiber_op_template_span": 64,
    "store_tile_template_span": 64,
}

EXPECTED_BYTE_MATERIALIZER_STATUS_COUNTS = {
    "raw_inst_t_row_bytes_available": 128,
}

EXPECTED_SELECTOR_STATUS_COUNTS = {
    "selector_policy_candidate_available": 128,
}

EXPECTED_SELECTOR_ROLE_SELECTED_ROW_COUNTS = {
    "compute_core:gemm_tile": 32768,
    "tile_store": 4096,
}

EXPECTED_RAW_INST_T_ROW_COUNT = 36864
EXPECTED_RAW_INST_T_BYTE_COUNT = EXPECTED_RAW_INST_T_ROW_COUNT * 304

EXPECTED_ROLE_RAW_BYTE_COUNTS = {
    "compute_core:gemm_tile": 32768 * 304,
    "tile_store": 4096 * 304,
}

ENABLED_NO_RELU_SPAN_POLICY_ROLES = {
    "compute_core:gemm_tile",
    "tile_store",
}


def main() -> None:
    stream_plan = build_demo_gemm_stream_plan(include_relu=False)
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
    template_summary = summarize_template_op_plan(template_plan)
    layout = lower_template_ops_to_binary_layout(
        template_plan,
        requested_runnability_state="emittable_debug",
    )
    layout_summary = summarize_binary_layout_plan(layout)
    aline_report = build_aline_gemm_evidence_report()
    aline_span_report = build_aline_template_span_candidate_report(
        layout,
        aline_report,
    )
    compressed_span_report = build_compressed_template_span_authority_report(
        layout,
        aline_span_report,
        enabled_role_span_policies=ENABLED_NO_RELU_SPAN_POLICY_ROLES,
    )
    exact_span_hash_report = build_exact_template_span_hash_candidate_report(
        layout,
        compressed_span_report,
    )
    exact_selector_report = build_exact_span_row_selector_policy_report(layout)
    exact_selector_summary = summarize_exact_span_row_selector_policy_report(
        exact_selector_report
    )
    span_materialization_report = build_template_span_materialization_candidate_report(
        layout,
        exact_span_hash_report,
        selector_policy_report=exact_selector_report,
    )
    span_materialization_summary = summarize_template_span_materialization_candidate_report(
        span_materialization_report,
    )
    failures: list[str] = []

    if len(fibers) != 64:
        failures.append(f"expected 64 fibers, got {len(fibers)}")
    if sorted({len(fiber.ops) for fiber in fibers}) != [2]:
        failures.append("GEMM fibers must be atomic gemm_tile -> store_tile sequences")
    if len(executable.executable_ops) != 128:
        failures.append(f"expected 128 executable ops, got {len(executable.executable_ops)}")
    if len(schedule.steps) != 128:
        failures.append(f"expected 128 schedule steps, got {len(schedule.steps)}")
    if template_summary["template_op_count"] != 128:
        failures.append(f"expected 128 TemplateOps, got {template_summary['template_op_count']}")
    if template_summary["status_counts"] != EXPECTED_TEMPLATE_STATUS_COUNTS:
        failures.append(f"unexpected TemplateOp statuses: {template_summary['status_counts']}")
    if template_summary["unresolved_role_counts"] != {}:
        failures.append(f"GEMM profile still has unresolved templates: {template_summary['unresolved_role_counts']}")
    if any("relu" in role for role in template_summary["role_counts"]):
        failures.append("GEMM source profile still produced ReLU roles")
    if template_summary["diagnostic_count"] != 0:
        failures.append(f"expected no TemplateOp diagnostics, got {template_summary['diagnostic_count']}")
    if layout_summary["runnability_state"] != "emittable_debug":
        failures.append(
            "expected emittable_debug layout, got "
            f"{layout_summary['runnability_state']}"
        )
    if layout_summary["validation_status"] != "valid":
        failures.append(f"unexpected layout validation status: {layout_summary['validation_status']}")
    if layout_summary["instruction_row_count"] != 128:
        failures.append(f"expected 128 instruction rows, got {layout_summary['instruction_row_count']}")
    if layout_summary["zero_instruction_boundary_count"] != 0:
        failures.append(
            "expected 0 zero-instruction boundaries, got "
            f"{layout_summary['zero_instruction_boundary_count']}"
        )
    if layout_summary["phase_instruction_counts"] != EXPECTED_BINARY_PHASE_COUNTS:
        failures.append(f"unexpected binary phase counts: {layout_summary['phase_instruction_counts']}")
    if layout_summary["diagnostic_count"] != 0:
        failures.append(f"expected no layout diagnostics, got {layout_summary['diagnostic_count']}")
    if layout_summary["unresolved_template_op_count"] != 0:
        failures.append("layout should not allocate unresolved atomic GEMM TemplateOps")
    if any("relu" in row.role for row in layout.instruction_rows):
        failures.append("GEMM layout must not contain ReLU instruction rows")
    if span_materialization_summary["instruction_row_count"] != 128:
        failures.append(
            "expected 128 template span materialization records, got "
            f"{span_materialization_summary['instruction_row_count']}"
        )
    if (
        span_materialization_summary["materialization_kind_counts"]
        != EXPECTED_MATERIALIZATION_KIND_COUNTS
    ):
        failures.append(
            "unexpected GEMM/store materialization kinds: "
            f"{span_materialization_summary['materialization_kind_counts']}"
        )
    if span_materialization_summary["raw_overlay_consumable_count"] != 0:
        failures.append("template span candidates must not become raw overlay inputs")
    if span_materialization_report.bytes_emitted is not True:
        failures.append("template span materialization report must emit exact raw bytes")
    if (
        span_materialization_summary["byte_materializer_status_counts"]
        != EXPECTED_BYTE_MATERIALIZER_STATUS_COUNTS
    ):
        failures.append(
            "unexpected byte materializer statuses: "
            f"{span_materialization_summary['byte_materializer_status_counts']}"
        )
    if (
        exact_selector_summary["selector_status_counts"]
        != EXPECTED_SELECTOR_STATUS_COUNTS
    ):
        failures.append(
            "unexpected exact selector statuses: "
            f"{exact_selector_summary['selector_status_counts']}"
        )
    if (
        exact_selector_summary["role_selected_row_counts"]
        != EXPECTED_SELECTOR_ROLE_SELECTED_ROW_COUNTS
    ):
        failures.append(
            "unexpected selected row counts: "
            f"{exact_selector_summary['role_selected_row_counts']}"
        )
    if exact_selector_report.bytes_emitted is not False:
        failures.append("exact selector report must not emit bytes")
    if (
        span_materialization_summary["raw_inst_t_row_count"]
        != EXPECTED_RAW_INST_T_ROW_COUNT
    ):
        failures.append(
            "unexpected raw inst_t row count: "
            f"{span_materialization_summary['raw_inst_t_row_count']}"
        )
    if (
        span_materialization_summary["raw_inst_t_byte_count"]
        != EXPECTED_RAW_INST_T_BYTE_COUNT
    ):
        failures.append(
            "unexpected raw inst_t byte count: "
            f"{span_materialization_summary['raw_inst_t_byte_count']}"
        )
    if (
        span_materialization_summary["role_raw_byte_counts"]
        != EXPECTED_ROLE_RAW_BYTE_COUNTS
    ):
        failures.append(
            "unexpected raw byte counts by role: "
            f"{span_materialization_summary['role_raw_byte_counts']}"
        )
    missing_materializer_inputs = span_materialization_summary[
        "missing_byte_materializer_input_counts"
    ]
    if missing_materializer_inputs.get("span_row_selector_policy", 0) != 0:
        failures.append(
            "GEMM selector policy should be closed before byte materialization"
        )
    if missing_materializer_inputs.get("store_output_binding", 0) != 0:
        failures.append(
            "store output binding should be selected before byte materialization"
        )
    if missing_materializer_inputs.get("raw_inst_t_row_bytes", 0) != 0:
        failures.append(
            "raw_inst_t_row_bytes should be materialized from exact selected rows"
        )
    if missing_materializer_inputs.get("raw_template_row_sha256", 0) != 0:
        failures.append(
            "raw_template_row_sha256 should be materialized from packed raw bytes"
        )
    if any(
        record.byte_materializer_status == "raw_inst_t_row_bytes_available"
        and (
            record.raw_inst_t_row_bytes_sha256 is None
            or record.raw_template_row_sha256 is None
            or record.raw_template_row_sha256
            != record.raw_inst_t_row_bytes_sha256
            or record.raw_template_row_sha256
            == record.selected_row_hash_sequence_sha256
        )
        for record in span_materialization_report.records
    ):
        failures.append(
            "raw_template_row_sha256 must come from packed row bytes, not selector/span metadata"
        )
    if any(
        record.primary_fiber_op_id.endswith(":gemm_tile")
        and record.provenance_policy
        != "template_span_may_expand_internal_dfu3500_rows_but_primary_fiber_op_remains_gemm_tile"
        for record in span_materialization_report.records
    ):
        failures.append("GEMM template spans must preserve gemm_tile provenance")

    if failures:
        print("stream compiler no-ReLU safe subset check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler no-ReLU safe subset check OK")
    print(f"template_ops={template_summary['template_op_count']}")
    print(f"instruction_rows={layout_summary['instruction_row_count']}")
    print(f"runnability_state={layout_summary['runnability_state']}")
    print(
        "materialization_kinds="
        f"{span_materialization_summary['materialization_kind_counts']}"
    )
    print(
        "selector_row_counts="
        f"{exact_selector_summary['role_selected_row_counts']}"
    )


if __name__ == "__main__":
    main()
