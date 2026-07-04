#!/usr/bin/env python3
"""Focused validation for B-line serializer-readiness reports."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.debug_emit import emit_debug_row_artifact
from gpdpu_compiler.core.stream_compiler.field_offsets import (
    build_field_offset_preflight_plan,
)
from gpdpu_compiler.core.stream_compiler.folding import analyze_stream_loop_folding
from gpdpu_compiler.core.stream_compiler.serializer_readiness import (
    build_serializer_readiness_plan,
    summarize_serializer_readiness_plan,
)
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
    "runnability_state": "report_only",
    "struct_readiness_count": 5,
    "packable_struct_count": 3,
    "blocked_struct_count": 2,
    "recommended_first_writer": "instance_conf_info_t",
    "required_field_count": 42,
    "known_required_offset_count": 41,
    "ready_required_value_count": 40,
    "blocked_required_field_count": 2,
    "diagnostic_count": 0,
    "serializer_status_counts": {
        "blocked_pending_evidence": 2,
        "packable_candidate": 3,
    },
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
    offset_plan = build_field_offset_preflight_plan(component_plan)
    readiness = build_serializer_readiness_plan(component_plan, offset_plan)
    summary = summarize_serializer_readiness_plan(readiness)

    if summary != EXPECTED_SUMMARY:
        failures.append(f"unexpected serializer readiness summary: {summary}")

    by_struct = {item.struct_name: item for item in readiness.struct_readiness}
    instance = by_struct.get("instance_conf_info_t")
    if instance is None:
        failures.append("missing instance serializer readiness")
    elif instance.serializer_status != "packable_candidate":
        failures.append(f"instance_conf_info_t should be packable first: {instance}")
    else:
        if [field.field_path for field in instance.required_fields] != [
            "base_addr.0.base_addr_word",
            "base_addr.1.base_addr_word",
            "base_addr.2.base_addr_word",
            "base_addr.3.base_addr_word",
        ]:
            failures.append(f"unexpected instance required fields: {instance}")
        if any(field.blocker_reason for field in instance.required_fields):
            failures.append(f"instance writer should have no field blockers: {instance}")

    expected_blockers = {
        "inst_t": {"inst_t_fields": "missing_known_field_offset"},
        "sub_task_conf_info_t": {
            "instances_conf_mem_based_addr": (
                "candidate_value_contains_unresolved_placeholder"
            ),
        },
    }
    for struct_name, blockers in expected_blockers.items():
        readiness_item = by_struct.get(struct_name)
        if readiness_item is None:
            failures.append(f"missing readiness for {struct_name}")
            continue
        observed = {
            field.field_path: field.blocker_reason
            for field in readiness_item.required_fields
            if field.blocker_reason is not None
        }
        if observed != blockers:
            failures.append(
                f"unexpected blockers for {struct_name}: expected {blockers}, got {observed}"
            )

    plan_view = readiness.to_plan()
    if plan_view["runnability_state"] != "report_only":
        failures.append(f"readiness must remain report-only: {plan_view}")
    if "serializing_binary_bytes" not in str(plan_view["layering_policy"]):
        failures.append(f"serializer readiness layering policy is too weak: {plan_view}")

    if failures:
        print("stream compiler serializer readiness check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler serializer readiness check OK")
    print("recommended_first_writer=instance_conf_info_t")


if __name__ == "__main__":
    main()
