#!/usr/bin/env python3
"""Focused check for S2 TaskResource replay row-authority reporting."""

from __future__ import annotations

import json

from gpdpu_compiler.core.dfu3500.task_resource_replay import (
    build_task_resource_replay_authority_report,
)
from gpdpu_compiler.core.stream_compiler.debug_emit import emit_debug_row_artifact
from gpdpu_compiler.core.stream_compiler.field_offsets import (
    build_field_offset_preflight_plan,
)
from gpdpu_compiler.core.stream_compiler.folding import analyze_stream_loop_folding
from gpdpu_compiler.core.stream_compiler.inst_writers import (
    build_exact_template_binding_seed_report,
    build_template_evidence_binding_report,
    summarize_exact_template_binding_seed_report,
)
from gpdpu_compiler.core.stream_compiler.micc_component_writers import (
    build_subtask_instance_semantics_report,
)
from gpdpu_compiler.core.stream_compiler.serializer_readiness import (
    build_serializer_readiness_plan,
)
from gpdpu_compiler.core.stream_compiler.vendor_components import (
    build_vendor_component_plan,
)
from gpdpu_compiler.core.stream_compiler.vendor_groups import (
    group_debug_rows_vendor_like,
    remap_vendor_like_groups_locally,
)
from stream_compiler_demo_pipeline import build_demo_pipeline


EXPECTED_COVERED_ROLE_COUNTS = {
    "operand_route_recv:A|ROUTE_RECV_VISIBILITY": 192,
}


def main() -> None:
    failures: list[str] = []
    pipeline = build_demo_pipeline("gemm_no_relu")
    s1_semantics_report = _build_s1_semantics_report(pipeline)
    evidence_report = build_template_evidence_binding_report(pipeline.binary_layout)
    seed_report = build_exact_template_binding_seed_report(
        pipeline.binary_layout,
        evidence_report,
        s1_representation_selection_complete=s1_semantics_report.selection_complete,
    )
    seed_summary = summarize_exact_template_binding_seed_report(seed_report)
    authority_report = build_task_resource_replay_authority_report(
        s2_bindings=seed_report.bindings,
    )
    authority_plan = authority_report.to_plan()

    if authority_plan["authority_status"] != "partial":
        failures.append(
            "expected partial authority, got "
            f"{authority_plan['authority_status']}"
        )
    if authority_plan["covered_role_counts"] != EXPECTED_COVERED_ROLE_COUNTS:
        failures.append(
            "unexpected covered role counts: "
            f"{authority_plan['covered_role_counts']}"
        )
    if not authority_plan["open_blockers"]:
        failures.append("expected fail-closed open blockers")
    if seed_summary["exact_seed_candidate_status_counts"] != {
        "partial_candidate_pending_task_resource_replay_row_authority": 192,
        "partial_multi_candidate_pending_local_order": 704,
    }:
        failures.append(
            "unexpected S2 seed status split: "
            f"{seed_summary['exact_seed_candidate_status_counts']}"
        )
    route_status = authority_plan["role_statuses"].get(
        "operand_route_recv:A|ROUTE_RECV_VISIBILITY",
        {},
    )
    if route_status.get("authority_status") != "partial":
        failures.append(f"route recv A should be partial: {route_status}")
    if "inst_t.dst_operands_idx[0]" not in route_status.get("closed_fields", []):
        failures.append(
            f"route recv A missing COPY dst operand closure: {route_status}"
        )

    if failures:
        print("stream compiler TaskResource replay authority check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler TaskResource replay authority check OK")
    print(f"authority_status={authority_plan['authority_status']}")
    print(
        "covered_role_counts="
        f"{json.dumps(authority_plan['covered_role_counts'], sort_keys=True)}"
    )
    print(
        "open_blockers="
        f"{json.dumps(authority_plan['open_blockers'], sort_keys=True)}"
    )
    print(
        "s2_seed_statuses="
        f"{json.dumps(seed_summary['exact_seed_candidate_status_counts'], sort_keys=True)}"
    )


def _build_s1_semantics_report(pipeline):
    artifact = emit_debug_row_artifact(pipeline.binary_layout)
    groups = group_debug_rows_vendor_like(artifact)
    remap = remap_vendor_like_groups_locally(groups)
    component_plan = build_vendor_component_plan(
        remap,
        loop_fold_report=analyze_stream_loop_folding(pipeline.schedule),
    )
    offset_plan = build_field_offset_preflight_plan(component_plan)
    build_serializer_readiness_plan(component_plan, offset_plan)
    return build_subtask_instance_semantics_report(component_plan)


if __name__ == "__main__":
    main()
