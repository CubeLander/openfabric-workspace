#!/usr/bin/env python3
"""Focused validation for report-only folded B-line component candidates."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.debug_emit import emit_debug_row_artifact
from gpdpu_compiler.core.stream_compiler.folded_components import (
    build_folded_vendor_component_experiment,
    summarize_folded_vendor_component_experiment,
)
from gpdpu_compiler.core.stream_compiler.folding import analyze_stream_loop_folding
from gpdpu_compiler.core.stream_compiler.vendor_components import (
    VendorComponentPlan,
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
    "expanded_inst_row_count": 896,
    "folded_inst_row_count": 320,
    "inst_row_reduction_count": 576,
    "expanded_exeblock_row_count": 384,
    "folded_exeblock_row_count": 192,
    "exeblock_row_reduction_count": 192,
    "task_candidate_count": 4,
    "task_candidate_binary_encoded_count": 0,
    "task_candidate_instances_amount_total": 16,
    "task_candidate_stream_total": 64,
    "task_candidate_shape_total": 16,
    "task_candidate_signature_total": 16,
    "task_candidate_target_projection_report_only_count": 4,
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
    experiment = build_folded_vendor_component_experiment(component_plan)
    summary = summarize_folded_vendor_component_experiment(experiment)

    if summary != EXPECTED_SUMMARY:
        failures.append(f"unexpected folded component summary: {summary}")

    if experiment.diagnostics:
        failures.append(f"unexpected folded component diagnostics: {experiment.diagnostics}")

    if len(experiment.task_candidates) != 4:
        failures.append(
            f"expected four folded task candidates, got {len(experiment.task_candidates)}"
        )
    else:
        first = experiment.task_candidates[0]
        if first.task_id != 0:
            failures.append(f"unexpected first task id: {first}")
        if first.subtask_slot != "subtask1_k_stream":
            failures.append(f"unexpected first subtask slot: {first}")
        if first.instances_amount != 4:
            failures.append(f"unexpected first instances_amount: {first}")
        if first.stream_candidate_count != 16:
            failures.append(f"unexpected first stream count: {first}")
        if first.expanded_k_stream_exeblock_count != 64:
            failures.append(f"unexpected first expanded k exeblocks: {first}")
        if first.folded_k_stream_exeblock_count != 16:
            failures.append(f"unexpected first folded k exeblocks: {first}")
        if first.expanded_k_stream_instruction_count != 192:
            failures.append(f"unexpected first expanded k instructions: {first}")
        if first.folded_k_stream_instruction_count != 48:
            failures.append(f"unexpected first folded k instructions: {first}")
        if first.expanded_total_exeblock_count != 96:
            failures.append(f"unexpected first expanded total exeblocks: {first}")
        if first.folded_total_exeblock_count != 48:
            failures.append(f"unexpected first folded total exeblocks: {first}")
        if first.expanded_total_instruction_count != 224:
            failures.append(f"unexpected first expanded total instructions: {first}")
        if first.folded_total_instruction_count != 80:
            failures.append(f"unexpected first folded total instructions: {first}")
        if first.instance_base_mapping_status != (
            "resolved_for_gemm_k_stream_a_b_slots"
        ):
            failures.append(f"unexpected first base mapping status: {first}")
        if sorted(first.stream_fold_body_signature_counts.values()) != [1, 3, 3, 9]:
            failures.append(f"unexpected first signature counts: {first}")
        if any(
            "operand_materialize:" in key
            or "operand_route_recv:" in key
            or "compute_core:" in key
            for key in first.stream_fold_body_signature_counts
        ):
            failures.append(
                "folded component signatures must not use role strings: "
                f"{first.stream_fold_body_signature_counts}"
            )
        if first.target_projection_status != "report_only_eligible":
            failures.append(f"unexpected first target projection status: {first}")
        if first.target_projection_policy != (
            "target_projection_eligibility_consumes_loop_uniformity_proof;"
            "does_not_define_foldability_or_emit_binary_bytes"
        ):
            failures.append(f"unexpected first target projection policy: {first}")
        if first.binary_encoded:
            failures.append("folded component candidate must not claim binary encoding")
        if first.policy != (
            "report_only_folded_component_experiment;"
            "canonical_loop_body_selected_from_first_loop_instance;"
            "expanded_vendor_component_plan_remains_authoritative"
        ):
            failures.append(f"unexpected first folded policy: {first}")

    _check_invalid_projection_proof_schema_is_rejected(component_plan, failures)

    plan = experiment.to_plan()
    if plan["runnability_state"] != "layout_candidate":
        failures.append(f"unexpected plan runnability state: {plan}")
    if "binary" in str(plan["layering_policy"]).lower():
        if "does_not_mutate_expanded_rows_or_emit_binary_bytes" not in str(
            plan["layering_policy"]
        ):
            failures.append(f"folded plan layering policy is too weak: {plan}")

    if failures:
        print("stream compiler folded component check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler folded component check OK")
    print("folded_inst_rows=320")
    print("folded_exeblock_rows=192")


def _check_invalid_projection_proof_schema_is_rejected(
    component_plan: VendorComponentPlan,
    failures: list[str],
) -> None:
    mutated_subtask_rows: list[dict[str, object]] = []
    mutation_applied = False
    for row in component_plan.subtask_rows:
        overlay = row.get("folded_subtask_conf_candidate")
        if not mutation_applied and isinstance(overlay, dict):
            mutated_overlay = dict(overlay)
            proof = dict(mutated_overlay.get("target_fold_projection_proof", {}))
            proof["schema_version"] = "target_fold_projection_proof.future"
            mutated_overlay["target_fold_projection_proof"] = proof
            mutated_row = dict(row)
            mutated_row["folded_subtask_conf_candidate"] = mutated_overlay
            mutated_subtask_rows.append(mutated_row)
            mutation_applied = True
        else:
            mutated_subtask_rows.append(row)

    if not mutation_applied:
        failures.append("failed to construct invalid target projection proof fixture")
        return

    mutated_plan = VendorComponentPlan(
        profile_id=component_plan.profile_id,
        runnability_state=component_plan.runnability_state,
        inst_rows=component_plan.inst_rows,
        exeblock_rows=component_plan.exeblock_rows,
        task_rows=component_plan.task_rows,
        subtask_rows=tuple(mutated_subtask_rows),
        instance_rows=component_plan.instance_rows,
        zero_boundaries=component_plan.zero_boundaries,
        capacity_report=component_plan.capacity_report,
        diagnostics=component_plan.diagnostics,
    )
    experiment = build_folded_vendor_component_experiment(mutated_plan)
    if not experiment.task_candidates:
        failures.append("invalid target projection proof fixture produced no candidates")
        return
    first = experiment.task_candidates[0]
    if first.target_projection_status != "invalid_projection_proof_schema":
        failures.append(
            "invalid target projection proof schema was consumed as eligible: "
            f"{first}"
        )
    if first.target_projection_policy != (
        "unsupported_target_fold_projection_proof_schema"
    ):
        failures.append(f"unexpected invalid projection proof policy: {first}")


if __name__ == "__main__":
    main()
