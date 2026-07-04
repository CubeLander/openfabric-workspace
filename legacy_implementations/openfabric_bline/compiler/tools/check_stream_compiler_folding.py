#!/usr/bin/env python3
"""Focused validation for report-only B-line fiber loop folding analysis."""

from __future__ import annotations

from dataclasses import replace

from gpdpu_compiler.core.stream_compiler.folding import (
    analyze_stream_loop_folding,
    summarize_stream_loop_fold_report,
)
from stream_compiler_demo_pipeline import build_demo_pipeline


EXPECTED_LOOP_BODY_SHAPE_COUNTS = {
    (
        "operand_materialize:A:operand_materialization:"
        "legacy_route_source_materialize_template_candidate|"
        "operand_materialize:B:operand_materialization:"
        "legacy_route_source_materialize_template_candidate|"
        "compute_core:gemm_update:gemm_k_update:"
        "legacy_compute_update_template_candidate"
    ): 4,
    (
        "operand_materialize:A:operand_materialization:"
        "legacy_route_source_materialize_template_candidate|"
        "operand_route_recv:B:operand_route_visibility:"
        "legacy_route_forward_or_endpoint_visibility_candidate|"
        "compute_core:gemm_update:gemm_k_update:"
        "legacy_compute_update_template_candidate"
    ): 12,
    (
        "operand_route_recv:A:operand_route_visibility:"
        "legacy_route_forward_or_endpoint_visibility_candidate|"
        "operand_materialize:B:operand_materialization:"
        "legacy_route_source_materialize_template_candidate|"
        "compute_core:gemm_update:gemm_k_update:"
        "legacy_compute_update_template_candidate"
    ): 12,
    (
        "operand_route_recv:A:operand_route_visibility:"
        "legacy_route_forward_or_endpoint_visibility_candidate|"
        "operand_route_recv:B:operand_route_visibility:"
        "legacy_route_forward_or_endpoint_visibility_candidate|"
        "compute_core:gemm_update:gemm_k_update:"
        "legacy_compute_update_template_candidate"
    ): 36,
}


def _check_profile(profile: str, failures: list[str]) -> None:
    artifacts = build_demo_pipeline(profile)  # type: ignore[arg-type]
    report = analyze_stream_loop_folding(artifacts.schedule)
    summary = summarize_stream_loop_fold_report(report)

    if summary["candidate_record_count"] != 64:
        failures.append(
            f"{profile}: expected 64 fold candidate records, got "
            f"{summary['candidate_record_count']}"
        )
    if summary["fold_candidate_count"] != 64:
        failures.append(
            f"{profile}: expected 64 foldable candidates, got "
            f"{summary['fold_candidate_count']}"
        )
    if summary["fold_candidate_rejected_count"] != 0:
        failures.append(
            f"{profile}: expected no rejected fold candidates, got "
            f"{summary['fold_candidate_rejected_count']}"
        )
    if summary["fold_candidate_rejection_reasons"] != {}:
        failures.append(
            f"{profile}: unexpected fold rejection reasons: "
            f"{summary['fold_candidate_rejection_reasons']}"
        )
    if summary["fold_candidate_loop_instance_total"] != 256:
        failures.append(
            f"{profile}: expected 256 loop instances, got "
            f"{summary['fold_candidate_loop_instance_total']}"
        )
    if summary["fold_candidate_repeated_action_total"] != 768:
        failures.append(
            f"{profile}: expected 768 repeated loop-body actions, got "
            f"{summary['fold_candidate_repeated_action_total']}"
        )
    if summary["fold_candidate_materialization_action_total"] != 512:
        failures.append(
            f"{profile}: expected 512 materialization actions, got "
            f"{summary['fold_candidate_materialization_action_total']}"
        )
    if summary["fold_candidate_carried_dependency_total"] != 192:
        failures.append(
            f"{profile}: expected 192 carried dependencies, got "
            f"{summary['fold_candidate_carried_dependency_total']}"
        )
    if summary["fold_candidate_instance_base_mapping_unresolved_count"] != 64:
        failures.append(
            f"{profile}: expected every fold candidate to require unresolved "
            "instance base mapping, got "
            f"{summary['fold_candidate_instance_base_mapping_unresolved_count']}"
        )
    if summary["loop_body_shape_counts"] != EXPECTED_LOOP_BODY_SHAPE_COUNTS:
        failures.append(
            f"{profile}: unexpected loop body shape counts: "
            f"{summary['loop_body_shape_counts']}"
        )
    if summary["diagnostic_count"] != 0:
        failures.append(f"{profile}: unexpected folding diagnostics")

    first = report.candidates[0]
    if first.loop_instance_keys != ("k0", "k1", "k2", "k3"):
        failures.append(f"{profile}: unexpected first loop instances: {first}")
    if first.derived_region_axis != "derived_region":
        failures.append(f"{profile}: unexpected derived region axis: {first}")
    if first.derived_instance_keys != ("region0", "region1", "region2", "region3"):
        failures.append(f"{profile}: unexpected derived region instances: {first}")
    if first.source_to_derived_instance_keys != (
        ("k0", "region0"),
        ("k1", "region1"),
        ("k2", "region2"),
        ("k3", "region3"),
    ):
        failures.append(f"{profile}: unexpected source-to-derived instance map: {first}")
    first_plan = first.to_plan()
    if first_plan["derived_instance_keys"] != ["region0", "region1", "region2", "region3"]:
        failures.append(f"{profile}: fold plan omits neutral derived instance keys")
    expected_signature = {
        "step_semantics": [
            {
                "semantic_kind": "operand_materialization",
                "candidate_mechanism": "legacy_route_source_materialize_template_candidate",
            },
            {
                "semantic_kind": "operand_materialization",
                "candidate_mechanism": "legacy_route_source_materialize_template_candidate",
            },
            {
                "semantic_kind": "gemm_k_update",
                "candidate_mechanism": "legacy_compute_update_template_candidate",
            },
        ],
        "dependency_topology": [
            {
                "source_step_index": 0,
                "target_step_index": 2,
                "dependency_kind": "instance_local",
            },
            {
                "source_step_index": 1,
                "target_step_index": 2,
                "dependency_kind": "instance_local",
            },
        ],
        "order_model": "source_order",
    }
    if first_plan["fold_body_signature"] != expected_signature:
        failures.append(
            f"{profile}: unexpected normalized fold body signature: "
            f"{first_plan['fold_body_signature']}"
        )
    if first.pre_loop_roles != ("accumulator_prepare",):
        failures.append(f"{profile}: unexpected first pre-loop roles: {first}")
    if first.loop_axis != "reduction_fragment":
        failures.append(f"{profile}: unexpected first loop axis: {first}")
    if first.loop_body_proof_statuses != ("proven",):
        failures.append(f"{profile}: unexpected loop proof statuses: {first}")
    if first.fold_scope != "stream_subtask_loop":
        failures.append(f"{profile}: unexpected fold scope: {first}")
    if len(first.source_fiber_ids) != 1:
        failures.append(f"{profile}: current demo should have one fiber per stream: {first}")
    if first.requires_instance_base_rows is not True:
        failures.append(f"{profile}: fold candidate must require instance base rows")
    if first.instance_base_mapping_status != "unresolved_pending_phase4":
        failures.append(f"{profile}: unexpected instance base mapping status: {first}")
    if first.policy != (
        "report_only_stream_subtask_loop_analysis;"
        "expanded_component_rows_remain_authoritative"
    ):
        failures.append(f"{profile}: unexpected fold policy: {first}")

    expected_post_roles = (
        ("accumulator_finalize", "tile_store")
        if profile == "gemm_no_relu"
        else ("accumulator_finalize", "tile_op:relu", "tile_store")
    )
    if first.post_loop_roles != expected_post_roles:
        failures.append(
            f"{profile}: unexpected first post-loop roles: {first.post_loop_roles}"
        )
    _check_materialization_count_uses_semantic_kind(profile, artifacts, failures)
    _check_derived_region_proof_ignores_source_axis_names(profile, artifacts, failures)
    _check_non_uniform_body_topology_is_rejected(profile, artifacts, failures)
    _check_broken_carry_chain_is_rejected(profile, artifacts, failures)
    _check_skipped_carry_edge_is_rejected(profile, artifacts, failures)
    _check_duplicate_carry_producer_is_rejected(profile, artifacts, failures)
    _check_missing_final_carry_output_is_rejected(profile, artifacts, failures)
    _check_unverified_schedule_does_not_emit_fold_candidates(profile, artifacts, failures)


def _check_materialization_count_uses_semantic_kind(
    profile: str,
    artifacts: object,
    failures: list[str],
) -> None:
    original_report = analyze_stream_loop_folding(artifacts.schedule)  # type: ignore[attr-defined]
    original_summary = summarize_stream_loop_fold_report(original_report)
    mutated_steps = tuple(
        replace(step, role="semantic_materialization_without_role_prefix")
        if step.semantic_kind in {
            "operand_materialization",
            "operand_route_visibility",
        }
        else step
        for step in artifacts.schedule.steps  # type: ignore[attr-defined]
    )
    mutated_schedule = replace(
        artifacts.schedule,  # type: ignore[attr-defined]
        steps=mutated_steps,
    )
    mutated_summary = summarize_stream_loop_fold_report(
        analyze_stream_loop_folding(mutated_schedule)
    )
    if (
        mutated_summary["fold_candidate_materialization_action_total"]
        != original_summary["fold_candidate_materialization_action_total"]
    ):
        failures.append(
            f"{profile}: materialization count depended on role string prefixes"
        )


def _check_derived_region_proof_ignores_source_axis_names(
    profile: str,
    artifacts: object,
    failures: list[str],
) -> None:
    original_summary = summarize_stream_loop_fold_report(
        analyze_stream_loop_folding(artifacts.schedule)  # type: ignore[attr-defined]
    )
    source_key_map: dict[str, str] = {}
    mutated_steps = []
    for step in artifacts.schedule.steps:  # type: ignore[attr-defined]
        if step.loop_instance_key is None:
            mutated_steps.append(step)
            continue
        source_key_map.setdefault(
            step.loop_instance_key,
            f"opaque_instance_{len(source_key_map)}",
        )
        mutated_steps.append(
            replace(
                step,
                loop_axis="opaque_region_axis",
                loop_instance_key=source_key_map[step.loop_instance_key],
            )
        )
    mutated_schedule = replace(
        artifacts.schedule,  # type: ignore[attr-defined]
        steps=tuple(mutated_steps),
    )
    mutated_report = analyze_stream_loop_folding(mutated_schedule)
    mutated_summary = summarize_stream_loop_fold_report(mutated_report)
    if mutated_summary["fold_candidate_count"] != original_summary["fold_candidate_count"]:
        failures.append(f"{profile}: source axis names changed fold candidate count")
    if (
        mutated_summary["fold_candidate_carried_dependency_total"]
        != original_summary["fold_candidate_carried_dependency_total"]
    ):
        failures.append(f"{profile}: source axis names changed carry proof total")

    first = mutated_report.candidates[0]
    if first.derived_instance_keys != ("region0", "region1", "region2", "region3"):
        failures.append(
            f"{profile}: derived region keys depended on source labels: {first}"
        )
    if first.loop_instance_keys != (
        "opaque_instance_0",
        "opaque_instance_1",
        "opaque_instance_2",
        "opaque_instance_3",
    ):
        failures.append(f"{profile}: unexpected opaque source keys: {first}")


def _check_broken_carry_chain_is_rejected(
    profile: str,
    artifacts: object,
    failures: list[str],
) -> None:
    report = analyze_stream_loop_folding(artifacts.schedule)  # type: ignore[attr-defined]
    first = report.candidates[0]
    if len(first.loop_instance_keys) < 2:
        failures.append(f"{profile}: expected at least two loop instances")
        return

    first_fiber_id = first.source_fiber_ids[0]
    previous_instance = first.loop_instance_keys[0]
    broken_instance = first.loop_instance_keys[1]
    previous_instance_sources = {
        step.source_fiber_op_id
        for step in artifacts.schedule.steps  # type: ignore[attr-defined]
        if step.source_fiber_id == first_fiber_id
        and step.loop_instance_key == previous_instance
    }

    mutated_steps = []
    mutation_applied = False
    for step in artifacts.schedule.steps:  # type: ignore[attr-defined]
        if (
            not mutation_applied
            and step.source_fiber_id == first_fiber_id
            and step.loop_instance_key == broken_instance
            and any(
                dependency_id in previous_instance_sources
                for dependency_id in step.dependency_source_ids
            )
        ):
            mutated_steps.append(
                replace(
                    step,
                    dependency_source_ids=tuple(
                        dependency_id
                        for dependency_id in step.dependency_source_ids
                        if dependency_id not in previous_instance_sources
                    ),
                )
            )
            mutation_applied = True
        else:
            mutated_steps.append(step)

    if not mutation_applied:
        failures.append(f"{profile}: failed to construct broken carry-chain fixture")
        return

    broken_schedule = replace(
        artifacts.schedule,  # type: ignore[attr-defined]
        steps=tuple(mutated_steps),
    )
    broken_report = analyze_stream_loop_folding(broken_schedule)
    broken_candidate = next(
        candidate
        for candidate in broken_report.candidates
        if candidate.stream_id == first.stream_id
    )
    if broken_candidate.foldable:
        failures.append(f"{profile}: broken carry-chain candidate remained foldable")
    if "missing_adjacent_carry_edge" not in broken_candidate.rejection_reasons:
        failures.append(
            f"{profile}: broken carry chain was not rejected with missing edge: "
            f"{broken_candidate.rejection_reasons}"
        )


def _check_skipped_carry_edge_is_rejected(
    profile: str,
    artifacts: object,
    failures: list[str],
) -> None:
    report = analyze_stream_loop_folding(artifacts.schedule)  # type: ignore[attr-defined]
    first = report.candidates[0]
    if len(first.loop_instance_keys) < 3:
        failures.append(f"{profile}: expected at least three loop instances")
        return

    first_fiber_id = first.source_fiber_ids[0]
    first_instance = first.loop_instance_keys[0]
    previous_instance = first.loop_instance_keys[1]
    skipped_instance = first.loop_instance_keys[2]
    first_instance_sources = {
        step.source_fiber_op_id
        for step in artifacts.schedule.steps  # type: ignore[attr-defined]
        if step.source_fiber_id == first_fiber_id
        and step.loop_instance_key == first_instance
    }
    previous_instance_sources = {
        step.source_fiber_op_id
        for step in artifacts.schedule.steps  # type: ignore[attr-defined]
        if step.source_fiber_id == first_fiber_id
        and step.loop_instance_key == previous_instance
    }
    replacement_source = next(iter(sorted(first_instance_sources)), None)
    if replacement_source is None:
        failures.append(f"{profile}: failed to find skipped carry replacement source")
        return

    mutated_steps = []
    mutation_applied = False
    for step in artifacts.schedule.steps:  # type: ignore[attr-defined]
        if (
            not mutation_applied
            and step.source_fiber_id == first_fiber_id
            and step.loop_instance_key == skipped_instance
            and any(
                dependency_id in previous_instance_sources
                for dependency_id in step.dependency_source_ids
            )
        ):
            mutated_steps.append(
                replace(
                    step,
                    dependency_source_ids=tuple(
                        replacement_source
                        if dependency_id in previous_instance_sources
                        else dependency_id
                        for dependency_id in step.dependency_source_ids
                    ),
                )
            )
            mutation_applied = True
        else:
            mutated_steps.append(step)

    if not mutation_applied:
        failures.append(f"{profile}: failed to construct skipped carry fixture")
        return

    broken_candidate = _candidate_after_step_mutation(artifacts, first.stream_id, mutated_steps)
    if broken_candidate.foldable:
        failures.append(f"{profile}: skipped carry-edge candidate remained foldable")
    if "skipped_carry_edge" not in broken_candidate.rejection_reasons:
        failures.append(
            f"{profile}: skipped carry edge was not rejected: "
            f"{broken_candidate.rejection_reasons}"
        )


def _check_duplicate_carry_producer_is_rejected(
    profile: str,
    artifacts: object,
    failures: list[str],
) -> None:
    report = analyze_stream_loop_folding(artifacts.schedule)  # type: ignore[attr-defined]
    first = report.candidates[0]
    if len(first.loop_instance_keys) < 2:
        failures.append(f"{profile}: expected at least two loop instances")
        return

    first_fiber_id = first.source_fiber_ids[0]
    previous_instance = first.loop_instance_keys[0]
    current_instance = first.loop_instance_keys[1]
    previous_instance_sources = sorted(
        step.source_fiber_op_id
        for step in artifacts.schedule.steps  # type: ignore[attr-defined]
        if step.source_fiber_id == first_fiber_id
        and step.loop_instance_key == previous_instance
    )

    mutated_steps = []
    mutation_applied = False
    for step in artifacts.schedule.steps:  # type: ignore[attr-defined]
        previous_dependencies = tuple(
            dependency_id
            for dependency_id in step.dependency_source_ids
            if dependency_id in previous_instance_sources
        )
        extra_sources = tuple(
            source
            for source in previous_instance_sources
            if source not in previous_dependencies
        )
        if (
            not mutation_applied
            and step.source_fiber_id == first_fiber_id
            and step.loop_instance_key == current_instance
            and previous_dependencies
            and extra_sources
        ):
            mutated_steps.append(
                replace(
                    step,
                    dependency_source_ids=(
                        *step.dependency_source_ids,
                        extra_sources[0],
                    ),
                )
            )
            mutation_applied = True
        else:
            mutated_steps.append(step)

    if not mutation_applied:
        failures.append(f"{profile}: failed to construct duplicate carry fixture")
        return

    broken_candidate = _candidate_after_step_mutation(artifacts, first.stream_id, mutated_steps)
    if broken_candidate.foldable:
        failures.append(f"{profile}: duplicate carry-producer candidate remained foldable")
    if "duplicate_carry_producer" not in broken_candidate.rejection_reasons:
        failures.append(
            f"{profile}: duplicate carry producer was not rejected: "
            f"{broken_candidate.rejection_reasons}"
        )


def _check_missing_final_carry_output_is_rejected(
    profile: str,
    artifacts: object,
    failures: list[str],
) -> None:
    report = analyze_stream_loop_folding(artifacts.schedule)  # type: ignore[attr-defined]
    first = report.candidates[0]
    if not first.loop_instance_keys:
        failures.append(f"{profile}: expected loop instances")
        return

    first_fiber_id = first.source_fiber_ids[0]
    last_instance = first.loop_instance_keys[-1]
    last_instance_sources = {
        step.source_fiber_op_id
        for step in artifacts.schedule.steps  # type: ignore[attr-defined]
        if step.source_fiber_id == first_fiber_id
        and step.loop_instance_key == last_instance
    }

    mutated_steps = []
    mutation_applied = False
    for step in artifacts.schedule.steps:  # type: ignore[attr-defined]
        if (
            step.source_fiber_id == first_fiber_id
            and step.phase == "post_loop"
            and any(
                dependency_id in last_instance_sources
                for dependency_id in step.dependency_source_ids
            )
        ):
            mutated_steps.append(
                replace(
                    step,
                    dependency_source_ids=tuple(
                        dependency_id
                        for dependency_id in step.dependency_source_ids
                        if dependency_id not in last_instance_sources
                    ),
                )
            )
            mutation_applied = True
        else:
            mutated_steps.append(step)

    if not mutation_applied:
        failures.append(f"{profile}: failed to construct missing final carry fixture")
        return

    broken_candidate = _candidate_after_step_mutation(artifacts, first.stream_id, mutated_steps)
    if broken_candidate.foldable:
        failures.append(f"{profile}: missing final carry-output candidate remained foldable")
    if "missing_carry_final_output_edge" not in broken_candidate.rejection_reasons:
        failures.append(
            f"{profile}: missing final carry output was not rejected: "
            f"{broken_candidate.rejection_reasons}"
        )


def _candidate_after_step_mutation(
    artifacts: object,
    stream_id: str,
    mutated_steps: list[object],
) -> object:
    broken_schedule = replace(
        artifacts.schedule,  # type: ignore[attr-defined]
        steps=tuple(mutated_steps),
    )
    broken_report = analyze_stream_loop_folding(broken_schedule)
    return next(
        candidate
        for candidate in broken_report.candidates
        if candidate.stream_id == stream_id
    )


def _check_unverified_schedule_does_not_emit_fold_candidates(
    profile: str,
    artifacts: object,
    failures: list[str],
) -> None:
    steps = list(artifacts.schedule.steps)  # type: ignore[attr-defined]
    if len(steps) < 2:
        failures.append(f"{profile}: expected at least two schedule steps")
        return

    mutated_schedule = replace(
        artifacts.schedule,  # type: ignore[attr-defined]
        steps=(
            steps[0],
            replace(steps[1], source_fiber_op_id=steps[0].source_fiber_op_id),
            *steps[2:],
        ),
    )
    report = analyze_stream_loop_folding(mutated_schedule)
    if report.candidates:
        failures.append(
            f"{profile}: unverified schedule still produced fold candidates"
        )
    if "folding_requires_resource_verified_schedule" not in report.diagnostics:
        failures.append(
            f"{profile}: unverified schedule did not report folding gate: "
            f"{report.diagnostics}"
        )
    if not any(
        diagnostic.startswith("duplicate source fiber op id:")
        for diagnostic in report.diagnostics
    ):
        failures.append(
            f"{profile}: unverified fixture did not surface verifier diagnostic"
        )


def _check_non_uniform_body_topology_is_rejected(
    profile: str,
    artifacts: object,
    failures: list[str],
) -> None:
    report = analyze_stream_loop_folding(artifacts.schedule)  # type: ignore[attr-defined]
    first = report.candidates[0]
    if len(first.loop_instance_keys) < 2:
        failures.append(f"{profile}: expected at least two loop instances")
        return

    first_fiber_id = first.source_fiber_ids[0]
    broken_instance = first.loop_instance_keys[1]
    same_instance_sources = {
        step.source_fiber_op_id
        for step in artifacts.schedule.steps  # type: ignore[attr-defined]
        if step.source_fiber_id == first_fiber_id
        and step.loop_instance_key == broken_instance
    }

    mutated_steps = []
    mutation_applied = False
    for step in artifacts.schedule.steps:  # type: ignore[attr-defined]
        same_instance_dependencies = tuple(
            dependency_id
            for dependency_id in step.dependency_source_ids
            if dependency_id in same_instance_sources
        )
        if (
            not mutation_applied
            and step.source_fiber_id == first_fiber_id
            and step.loop_instance_key == broken_instance
            and same_instance_dependencies
        ):
            removed_dependency = same_instance_dependencies[0]
            mutated_steps.append(
                replace(
                    step,
                    dependency_source_ids=tuple(
                        dependency_id
                        for dependency_id in step.dependency_source_ids
                        if dependency_id != removed_dependency
                    ),
                )
            )
            mutation_applied = True
        else:
            mutated_steps.append(step)

    if not mutation_applied:
        failures.append(f"{profile}: failed to construct non-uniform topology fixture")
        return

    broken_schedule = replace(
        artifacts.schedule,  # type: ignore[attr-defined]
        steps=tuple(mutated_steps),
    )
    broken_report = analyze_stream_loop_folding(broken_schedule)
    broken_candidate = next(
        candidate
        for candidate in broken_report.candidates
        if candidate.stream_id == first.stream_id
    )
    if broken_candidate.foldable:
        failures.append(f"{profile}: non-uniform body topology remained foldable")
    if "non_uniform_loop_body_shape" not in broken_candidate.rejection_reasons:
        failures.append(
            f"{profile}: non-uniform topology was not rejected as body shape: "
            f"{broken_candidate.rejection_reasons}"
        )


def main() -> None:
    failures: list[str] = []
    _check_profile("gemm_no_relu", failures)
    _check_gemm_relu_inside_gemm_fiber_disabled(failures)

    if failures:
        print("stream compiler folding check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler folding check OK")
    print("fold_candidates=64")


def _check_gemm_relu_inside_gemm_fiber_disabled(failures: list[str]) -> None:
    artifacts = build_demo_pipeline("gemm_relu")
    if artifacts.binary_layout.runnability_state != "bline_atomic_fiber_op_chain_missing":
        failures.append(
            "gemm_relu must not enter folding through GEMM fiber internals; got "
            f"{artifacts.binary_layout.runnability_state}"
        )
    if artifacts.binary_layout.validation_status != "invalid":
        failures.append("gemm_relu GEMM-fiber-disabled layout must be invalid")
    diagnostic_codes = {diagnostic.code for diagnostic in artifacts.binary_layout.diagnostics}
    if "gemm_relu_inside_gemm_fiber_disabled" not in diagnostic_codes:
        failures.append(
            "gemm_relu disabled layout must carry "
            "gemm_relu_inside_gemm_fiber_disabled"
        )


if __name__ == "__main__":
    main()
