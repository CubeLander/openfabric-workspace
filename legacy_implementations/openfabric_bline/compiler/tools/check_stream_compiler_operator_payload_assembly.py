#!/usr/bin/env python3
"""Focused validation for S3 operator payload assembly shells."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPILER_ROOT = REPO_ROOT / "compiler"
if str(COMPILER_ROOT) not in sys.path:
    sys.path.insert(0, str(COMPILER_ROOT))

from gpdpu_compiler.core.stream_compiler.component_writers import (  # noqa: E402
    emit_debug_instance_conf_info_component,
    summarize_debug_component_writer_artifact,
)
from gpdpu_compiler.core.stream_compiler.debug_emit import (  # noqa: E402
    emit_debug_row_artifact,
)
from gpdpu_compiler.core.stream_compiler.field_offsets import (  # noqa: E402
    build_field_offset_preflight_plan,
)
from gpdpu_compiler.core.stream_compiler.folding import (  # noqa: E402
    analyze_stream_loop_folding,
)
from gpdpu_compiler.core.stream_compiler.log10max_collective_strategy import (  # noqa: E402
    build_current_log10max_plan,
    build_log10max_capacity_proof_report,
    summarize_log10max_capacity_proof_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_template_pack import (  # noqa: E402
    build_log10max_status_report,
)
from gpdpu_compiler.core.stream_compiler.micc_component_writers import (  # noqa: E402
    emit_micc_sub_task_conf_info_component,
    summarize_micc_component_writer_artifact,
)
from gpdpu_compiler.core.op_specs import LOG10MAX_SPEC  # noqa: E402
from gpdpu_compiler.core.stream_compiler.executable import (  # noqa: E402
    lower_fibers_to_executable_ops,
)
from gpdpu_compiler.core.stream_compiler.log10max_fiber_chain import (  # noqa: E402
    build_log10max_production_fiber,
)
from gpdpu_compiler.core.stream_compiler.operator_payload_assembly import (  # noqa: E402
    build_operator_payload_assembly_report,
    gemm_no_relu_stream_statuses,
    gemm_relu_stream_statuses,
    log10max_stream_statuses,
    summarize_operator_payload_assembly_report,
)
from gpdpu_compiler.core.stream_compiler.route_role_binding import (  # noqa: E402
    build_route_role_binding_report,
    summarize_route_role_binding_report,
)
from gpdpu_compiler.core.stream_compiler.relu_binding import (  # noqa: E402
    bind_explicit_relu_subtasks,
    summarize_explicit_relu_subtask_binding_report,
)
from gpdpu_compiler.core.stream_compiler.serializer_readiness import (  # noqa: E402
    build_serializer_readiness_plan,
    summarize_serializer_readiness_plan,
)
from gpdpu_compiler.core.stream_compiler.vendor_components import (  # noqa: E402
    build_vendor_component_plan,
    summarize_vendor_component_plan,
)
from gpdpu_compiler.core.stream_compiler.vendor_groups import (  # noqa: E402
    group_debug_rows_vendor_like,
    remap_vendor_like_groups_locally,
)
from stream_compiler_demo_pipeline import build_demo_pipeline  # noqa: E402


EXPECTED_FINAL_STATES = {
    "gemm_no_relu": "blocked",
    "gemm_relu": "blocked",
    "log10max": "blocked",
}


def main() -> None:
    args = _parse_args()
    reports = {
        "gemm_no_relu": _build_gemm_no_relu_report(),
        "gemm_relu": _build_gemm_relu_report(),
        "log10max": _build_log10max_report(),
    }
    summaries = {
        operator: summarize_operator_payload_assembly_report(report)
        for operator, report in reports.items()
    }
    failures = _validate_summaries(summaries, reports)

    if args.json:
        print(
            json.dumps(
                {
                    operator: report.to_plan()
                    for operator, report in reports.items()
                },
                indent=2,
                sort_keys=True,
            )
        )

    if failures:
        print("stream compiler operator payload assembly check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler operator payload assembly check OK")
    for operator in ("gemm_no_relu", "gemm_relu", "log10max"):
        summary = summaries[operator]
        print(
            "operator=%s final_state=%s runtime_ready=%s uploadable=%s "
            "blocker_count=%s labels=%s"
            % (
                operator,
                summary["final_state"],
                summary["runtime_ready"],
                summary["uploadable"],
                summary["blocker_count"],
                ",".join(summary["customer_labels"]),
            )
        )
    print("placeholder_rule=placeholder_files_present=>runtime_ready_false/uploadable_false")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check S3 report-only operator payload assembly shells.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print full S3 report JSON after validation.",
    )
    return parser.parse_args()


def _build_gemm_no_relu_report():
    component_plan, readiness_plan = _component_and_readiness("gemm_no_relu")
    writer = emit_debug_instance_conf_info_component(
        component_plan,
        readiness_plan,
    )
    micc_writer = emit_micc_sub_task_conf_info_component(
        component_plan,
        readiness_plan,
    )
    micc_summary = summarize_micc_component_writer_artifact(micc_writer)
    selected_rows = micc_summary.get("row_status_counts", {}).get("selected")
    if isinstance(selected_rows, int):
        micc_summary["selected_rows"] = selected_rows
    if isinstance(micc_writer.semantics_report, dict):
        micc_summary["selection_complete"] = micc_writer.semantics_report.get(
            "selection_complete"
        )
    statuses = gemm_no_relu_stream_statuses(
        vendor_component_summary=summarize_vendor_component_plan(component_plan),
        serializer_summary=summarize_serializer_readiness_plan(readiness_plan),
        component_writer_summary=summarize_debug_component_writer_artifact(writer),
        micc_component_writer_summary=micc_summary,
    )
    return build_operator_payload_assembly_report(
        "gemm_no_relu",
        stream_artifacts=statuses,
    )


def _build_gemm_relu_report():
    pipeline = build_demo_pipeline("gemm_relu")
    relu_report = bind_explicit_relu_subtasks(pipeline.template_plan)
    statuses = gemm_relu_stream_statuses(
        relu_binding_summary=summarize_explicit_relu_subtask_binding_report(
            relu_report
        ),
    )
    return build_operator_payload_assembly_report(
        "gemm_relu",
        stream_artifacts=statuses,
    )


def _build_log10max_report():
    collective_report = build_log10max_capacity_proof_report(
        build_current_log10max_plan()
    )
    template_status = build_log10max_status_report()
    production_fiber = build_log10max_production_fiber()
    executable = lower_fibers_to_executable_ops(
        (production_fiber,),
        executable_role_profile=LOG10MAX_SPEC.executable_role_profile(),
    )
    route_role_report = build_route_role_binding_report(executable)
    statuses = log10max_stream_statuses(
        collective_summary=summarize_log10max_capacity_proof_report(
            collective_report
        ),
        template_summary=template_status["summary"],
        route_role_summary=summarize_route_role_binding_report(route_role_report),
    )
    return build_operator_payload_assembly_report(
        "log10max",
        stream_artifacts=statuses,
    )


def _component_and_readiness(profile: str):
    pipeline = build_demo_pipeline(profile)
    artifact = emit_debug_row_artifact(pipeline.binary_layout)
    groups = group_debug_rows_vendor_like(artifact)
    remap = remap_vendor_like_groups_locally(groups)
    component_plan = build_vendor_component_plan(
        remap,
        loop_fold_report=analyze_stream_loop_folding(pipeline.schedule),
    )
    offset_plan = build_field_offset_preflight_plan(component_plan)
    readiness_plan = build_serializer_readiness_plan(component_plan, offset_plan)
    return component_plan, readiness_plan


def _validate_summaries(summaries: dict[str, dict[str, object]], reports) -> list[str]:
    failures: list[str] = []
    for operator, expected_state in EXPECTED_FINAL_STATES.items():
        summary = summaries[operator]
        if summary["final_state"] != expected_state:
            failures.append(
                f"{operator} final_state drifted: {summary['final_state']}"
            )
        if summary["runtime_ready"] is not False:
            failures.append(f"{operator} must not be runtime_ready")
        if summary["uploadable"] is not False:
            failures.append(f"{operator} must not be uploadable")
        if int(summary["blocker_count"]) <= 0:
            failures.append(f"{operator} must expose at least one blocker")

    no_relu = reports["gemm_no_relu"].to_plan()
    no_relu_sections = {
        section["name"]: section
        for section in no_relu["package_shell_sections"]
    }
    for section_name in ("manifest", "runtime_assets", "cbuf", "micc"):
        section = no_relu_sections.get(section_name)
        if section is None:
            failures.append(f"gemm_no_relu missing shell section {section_name}")
        elif section["status"] != "expected_not_emitted":
            failures.append(f"gemm_no_relu {section_name} must not be emitted")
    if no_relu_sections.get("cbuf", {}).get("expected_sections") != [
        "insts",
        "exeblock_conf_info",
        "instance_conf_info",
    ]:
        failures.append("gemm_no_relu CBUF expected sections drifted")
    if no_relu_sections.get("micc", {}).get("expected_sections") != [
        "tasks_conf_info",
        "subtasks_conf_info",
    ]:
        failures.append("gemm_no_relu MICC expected sections drifted")
    if "S2:" not in " ".join(no_relu["blockers"]):
        failures.append("gemm_no_relu must remain blocked by S2 readiness/writer")
    if "S2:S2_component_writer_debug_only_not_runtime_payload" not in no_relu["blockers"]:
        failures.append("gemm_no_relu must keep debug-only component writer blocker")
    if "S2:S2_subtask_bytes_debug_only_not_runtime_payload" not in no_relu["blockers"]:
        failures.append("gemm_no_relu must keep MICC subtask bytes debug-only blocker")

    no_relu_labels = set(summaries["gemm_no_relu"]["customer_labels"])
    if "micc_selected_subtask_bytes_present" not in no_relu_labels:
        failures.append("gemm_no_relu metadata must consume selected MICC bytes")
    if "subtask_bytes_debug_only" not in no_relu_labels:
        failures.append("gemm_no_relu metadata must mark subtask bytes debug-only")

    no_relu_s2_artifacts = [
        artifact
        for artifact in no_relu["stream_artifacts"]
        if artifact["stage"] == "S2"
    ]
    if not no_relu_s2_artifacts:
        failures.append("gemm_no_relu missing S2 serializer/writer artifact")
    else:
        micc_summary = (
            no_relu_s2_artifacts[0]
            .get("summary", {})
            .get("micc_component_writer", {})
        )
        if micc_summary.get("struct_name") != "sub_task_conf_info_t":
            failures.append(f"unexpected MICC writer struct summary: {micc_summary}")
        if micc_summary.get("payload_size_bytes") != 2130624:
            failures.append(
                "gemm_no_relu must report selected MICC subtask payload bytes: "
                f"{micc_summary}"
            )
        if micc_summary.get("selected_rows") != 8:
            failures.append(f"unexpected selected MICC row total: {micc_summary}")
        if micc_summary.get("row_status_counts") != {"selected": 8}:
            failures.append(f"unexpected selected MICC row counts: {micc_summary}")
        if micc_summary.get("selection_complete") is not True:
            failures.append(f"MICC subtask selection must be complete: {micc_summary}")
        if micc_summary.get("runtime_ready_candidate") is not False:
            failures.append(f"MICC selected bytes must not be runtime-ready: {micc_summary}")

    relu_labels = set(summaries["gemm_relu"]["customer_labels"])
    if "blocked_symbolic_relu" not in relu_labels:
        failures.append("gemm_relu metadata must carry blocked_symbolic_relu")

    log10_labels = set(summaries["log10max"]["customer_labels"])
    if "ring_spmd_row_then_col_first_delivery" not in log10_labels:
        failures.append("log10max metadata must carry ring-first customer label")
    if "globalmax_route_role_binding_required" not in log10_labels:
        failures.append("log10max metadata must require GlobalMax route binding")
    if "physical_allreduce_not_claimed" not in log10_labels:
        failures.append("log10max metadata must avoid physical-allreduce claim")

    placeholder_report = build_operator_payload_assembly_report(
        "gemm_no_relu",
        stream_artifacts=reports["gemm_no_relu"].stream_artifacts,
        placeholder_files_present=True,
    )
    if placeholder_report.uploadable or placeholder_report.runtime_ready:
        failures.append("placeholder_files_present must force not uploadable/runtime")
    if "placeholder_files_present" not in placeholder_report.blockers:
        failures.append("placeholder shell blocker missing")

    return failures


if __name__ == "__main__":
    main()
