#!/usr/bin/env python3
"""Focused validation for B-line field-offset preflight reports."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.debug_emit import emit_debug_row_artifact
from gpdpu_compiler.core.stream_compiler.field_offsets import (
    build_field_offset_preflight_plan,
    summarize_field_offset_preflight_plan,
)
from gpdpu_compiler.core.stream_compiler.folding import analyze_stream_loop_folding
from gpdpu_compiler.core.stream_compiler.vendor_components import (
    build_vendor_component_plan,
)
from gpdpu_compiler.core.stream_compiler.vendor_groups import (
    group_debug_rows_vendor_like,
    remap_vendor_like_groups_locally,
)
from stream_compiler_demo_pipeline import build_demo_pipeline


EXPECTED_SUMMARY = {
    "profile_id": "dfu3500_legacy_gemm_symbolic",
    "runnability_state": "layout_candidate",
    "struct_report_count": 5,
    "struct_names": [
        "inst_t",
        "exeBlock_conf_info_t",
        "instance_conf_info_t",
        "task_conf_info_t",
        "sub_task_conf_info_t",
    ],
    "row_counts": {
        "inst_t": 896,
        "exeBlock_conf_info_t": 384,
        "instance_conf_info_t": 16,
        "task_conf_info_t": 4,
        "sub_task_conf_info_t": 12,
    },
    "known_struct_size_count": 5,
    "field_record_count": 199,
    "known_field_offset_count": 36,
    "unresolved_field_offset_count": 163,
    "binary_encoded_field_count": 0,
    "diagnostic_count": 0,
}


def main() -> None:
    failures: list[str] = []

    pipeline = build_demo_pipeline("gemm_no_relu")
    artifact = emit_debug_row_artifact(pipeline.binary_layout)
    groups = group_debug_rows_vendor_like(artifact)
    remap = remap_vendor_like_groups_locally(groups)
    component_plan = build_vendor_component_plan(
        remap,
        loop_fold_report=analyze_stream_loop_folding(pipeline.schedule),
    )
    plan = build_field_offset_preflight_plan(component_plan)
    summary = summarize_field_offset_preflight_plan(plan)

    if summary != EXPECTED_SUMMARY:
        failures.append(f"unexpected field offset summary: {summary}")

    reports = {report.struct_name: report for report in plan.struct_reports}
    _expect_known(
        reports,
        failures,
        "instance_conf_info_t",
        "base_addr.0.base_addr_word",
        0,
        8,
    )
    _expect_known(
        reports,
        failures,
        "instance_conf_info_t",
        "base_addr.3.base_addr_word",
        24,
        8,
    )
    _expect_known(reports, failures, "task_conf_info_t", "is_exe_start", 0, 1)
    _expect_known(reports, failures, "task_conf_info_t", "subtasks_idx", 24, 64)
    _expect_known(
        reports,
        failures,
        "sub_task_conf_info_t",
        "instances_amount",
        8,
        8,
    )
    _expect_known(
        reports,
        failures,
        "sub_task_conf_info_t",
        "embedded_exeblock_component_indices",
        72,
        266240,
    )
    _expect_known(
        reports,
        failures,
        "exeBlock_conf_info_t",
        "exeBlock_conf.inst_mem_based_addr",
        472,
        8,
    )
    _expect_known(
        reports,
        failures,
        "exeBlock_conf_info_t",
        "exeBlock_conf.stage_inst_amounts.CAL",
        488,
        8,
    )

    inst_report = reports.get("inst_t")
    if inst_report is None:
        failures.append("missing inst_t preflight report")
    elif inst_report.struct_size != 304:
        failures.append(f"unexpected inst_t size: {inst_report.struct_size}")
    elif any(record.offset_status == "known" for record in inst_report.records):
        failures.append("inst_t symbolic fields must remain unresolved in this preflight")

    plan_view = plan.to_plan()
    if plan_view["runnability_state"] != "layout_candidate":
        failures.append(f"unexpected plan runnability: {plan_view}")
    if "serializing_binary_bytes" not in str(plan_view["layering_policy"]):
        failures.append(f"field preflight layering policy is too weak: {plan_view}")

    if failures:
        print("stream compiler field offset check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler field offset check OK")
    print("known_field_offsets=36")
    print("unresolved_field_offsets=142")


def _expect_known(
    reports: dict[str, object],
    failures: list[str],
    struct_name: str,
    field_path: str,
    byte_offset: int,
    field_size: int,
) -> None:
    report = reports.get(struct_name)
    if report is None:
        failures.append(f"missing report for {struct_name}")
        return
    records = {
        record.candidate_field_path: record
        for record in getattr(report, "records")
    }
    record = records.get(field_path)
    if record is None:
        failures.append(f"missing field record {struct_name}.{field_path}")
        return
    if record.offset_status != "known":
        failures.append(f"expected known offset for {struct_name}.{field_path}: {record}")
    if record.byte_offset != byte_offset or record.field_size != field_size:
        failures.append(
            f"unexpected offset for {struct_name}.{field_path}: {record}"
        )
    if record.binary_encoded_count != 0:
        failures.append(f"field preflight must not claim binary encoding: {record}")


if __name__ == "__main__":
    main()
