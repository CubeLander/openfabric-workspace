#!/usr/bin/env python3
"""Focused check for log10max source -> atomic FiberOp-chain lowering."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gpdpu_compiler.core.op_specs import LOG10MAX_SPEC
from gpdpu_compiler.core.stream_compiler.binding import (
    bind_executable_roles_symbolically,
    summarize_role_binding_program,
)
from gpdpu_compiler.core.stream_compiler.dfu3500_semantics import (
    lower_template_records_to_dfu3500_semantics,
    summarize_dfu3500_semantic_report,
)
from gpdpu_compiler.core.stream_compiler.executable import (
    lower_fibers_to_executable_ops,
    summarize_executable_program,
)
from gpdpu_compiler.core.stream_compiler.log10max_fiber_chain import (
    build_log10max_fiber_chain_report,
    build_log10max_production_fiber,
    summarize_log10max_fiber_chain_report,
)
from gpdpu_compiler.core.stream_compiler.schedule import (
    build_fiber_execution_schedule,
    summarize_fiber_execution_schedule,
)
from gpdpu_compiler.core.stream_compiler.template_ops import (
    lower_schedule_to_template_ops,
    summarize_template_op_plan,
)
from gpdpu_compiler.core.stream_compiler.template_records import (
    lower_symbolic_bindings_to_template_records,
    summarize_template_record_program,
)

EXPECTED_OP_SEQUENCE = [
    "clamp_min_tile",
    "log10_tile",
    "local_reduce_max_tile",
    "global_max_tile",
    "max_with_floor_tile",
    "affine_scale_tile",
    "store_tile",
]

EXPECTED_TEMPLATE_STATUS_COUNTS = {
    "blocked_on_collective_template": 1,
    "blocked_on_global_scalar": 1,
    "template_ready": 5,
}

EXPECTED_EXECUTABLE_ROLE_COUNTS = {
    "collective:global_max": 1,
    "tile_op:affine_scale": 1,
    "tile_op:clamp_min": 1,
    "tile_op:log10": 1,
    "tile_op:max_with_floor": 1,
    "tile_reduce:local_reduce_max": 1,
    "tile_store": 1,
}

EXPECTED_PRODUCTION_TEMPLATE_STATUS_COUNTS = {
    "concrete_template": 5,
    "symbolic_unresolved": 2,
}

EXPECTED_RING_FIRST_BLOCKERS = [
    "route_role_globalmax_unproven",
    "ring_edge_template_missing",
    "ring_phase_order_missing",
    "global_max_distribution_missing",
    "consumer_global_max_binding_missing",
    "consumer_depends_on_global_ready_missing",
    "route_path_proof_missing",
    "dtype_update_op_mismatch",
    "symbolic_global_max_reaches_postprocess",
]


def main() -> None:
    args = _parse_args()
    report = build_log10max_fiber_chain_report()
    plan = report.to_plan()
    summary = summarize_log10max_fiber_chain_report(report)
    failures: list[str] = []

    if summary["fiber_op_count"] != 7:
        failures.append(f"expected 7 fiber ops, got {summary['fiber_op_count']}")
    if summary["op_sequence"] != EXPECTED_OP_SEQUENCE:
        failures.append(f"unexpected op sequence: {summary['op_sequence']}")
    if summary["template_status_counts"] != EXPECTED_TEMPLATE_STATUS_COUNTS:
        failures.append(
            "unexpected template status counts: "
            f"{summary['template_status_counts']}"
        )
    if summary["template_ready_count"] != 5:
        failures.append(
            "expected 5 template-ready ops, got "
            f"{summary['template_ready_count']}"
        )
    if summary["blocked_ops"] != ["global_max_tile", "max_with_floor_tile"]:
        failures.append(f"unexpected blocked ops: {summary['blocked_ops']}")
    if summary["chain_template_complete"] is not False:
        failures.append("log10max chain must remain template-incomplete")
    if summary["runtime_ready_claim"] is not False:
        failures.append("fiber-chain report must not claim runtime_ready")
    if summary["row_bytes_claim"] is not False:
        failures.append("fiber-chain report must not claim binary row bytes")
    if summary["selected_collective_strategy"] != "ring_spmd_row_then_col":
        failures.append(
            "expected ring-first SPMD strategy, got "
            f"{summary['selected_collective_strategy']}"
        )

    ops = plan["fiber"]["ops"]
    if [op["order_index"] for op in ops] != list(range(7)):
        failures.append("fiber op order_index must be contiguous 0..6")
    if any(op["atom_boundary"] != "pe_local_fiber_op" for op in ops):
        failures.append("every log10max op must be marked PE-local atomic")
    _expect_dependency(
        plan,
        failures,
        "fiber:log10max:tile0:0000:clamp_min_tile",
        "fiber:log10max:tile0:0001:log10_tile",
    )
    _expect_dependency(
        plan,
        failures,
        "fiber:log10max:tile0:0001:log10_tile",
        "fiber:log10max:tile0:0002:local_reduce_max_tile",
    )
    _expect_dependency(
        plan,
        failures,
        "fiber:log10max:tile0:0002:local_reduce_max_tile",
        "fiber:log10max:tile0:0003:global_max_tile",
    )
    _expect_dependency(
        plan,
        failures,
        "fiber:log10max:tile0:0003:global_max_tile",
        "fiber:log10max:tile0:0004:max_with_floor_tile",
    )
    _expect_dependency(
        plan,
        failures,
        "fiber:log10max:tile0:0004:max_with_floor_tile",
        "fiber:log10max:tile0:0005:affine_scale_tile",
    )
    _expect_dependency(
        plan,
        failures,
        "fiber:log10max:tile0:0005:affine_scale_tile",
        "fiber:log10max:tile0:0006:store_tile",
    )

    by_op = {op["op"]: op for op in ops}
    if by_op["global_max_tile"]["template_ready"] is not False:
        failures.append("global_max_tile must be blocked until collective binds")
    if by_op["global_max_tile"]["blocker_ids"] != EXPECTED_RING_FIRST_BLOCKERS:
        failures.append(
            "global_max_tile blocker list must stay narrowed to ring-first "
            f"delivery proof blockers: {by_op['global_max_tile']['blocker_ids']}"
        )
    if by_op["global_max_tile"]["attrs"]["physical_allreduce_claim"] is not False:
        failures.append("global_max_tile must not claim physical allreduce")
    if (
        by_op["global_max_tile"]["attrs"]["preferred_v1_strategy"]
        != "ring_spmd_row_then_col"
    ):
        failures.append("global_max_tile must keep ring-first route as V1 strategy")
    if by_op["max_with_floor_tile"]["attrs"]["local_template_shape_ready"] is not True:
        failures.append("max_with_floor_tile must retain local shape readiness")
    if by_op["max_with_floor_tile"]["template_status"] != "blocked_on_global_scalar":
        failures.append("max_with_floor_tile must be blocked on global scalar")
    if by_op["affine_scale_tile"]["source_chip_ops"] != [
        "add_scalar",
        "mul_scalar",
    ]:
        failures.append("affine_scale_tile must sequence add_scalar then mul_scalar")
    if plan["upstream_template_summary"]["uploadable"] is not False:
        failures.append("upstream S6 template status should remain fail-closed")
    if (
        plan["upstream_template_summary"]["symbolic_unresolved_count_for_uploadable"]
        != 1
    ):
        failures.append("expected one upstream symbolic scalar blocker")

    production_fiber = build_log10max_production_fiber()
    executable = lower_fibers_to_executable_ops(
        (production_fiber,),
        executable_role_profile=LOG10MAX_SPEC.executable_role_profile(),
    )
    executable_summary = summarize_executable_program(executable)
    if executable_summary["role_counts"] != EXPECTED_EXECUTABLE_ROLE_COUNTS:
        failures.append(
            "unexpected production executable role counts: "
            f"{executable_summary['role_counts']}"
        )
    if executable_summary["diagnostic_count"] != 0:
        failures.append(
            f"unexpected executable diagnostics: {executable.diagnostics}"
        )
    if executable_summary["placement_counts"] != {"tile_body": 6, "tile_store": 1}:
        failures.append(
            "local log10max ops should be tile_body before store, got "
            f"{executable_summary['placement_counts']}"
        )

    bindings = bind_executable_roles_symbolically(
        executable,
        template_intents=LOG10MAX_SPEC.template_intent_profile(),
    )
    binding_summary = summarize_role_binding_program(bindings)
    if binding_summary["status_counts"] != {
        "legacy_template_candidate": 5,
        "symbolic_unsupported": 2,
    }:
        failures.append(f"unexpected binding statuses: {binding_summary['status_counts']}")
    if binding_summary["unsupported_role_counts"] != {
        "collective:global_max": 1,
        "tile_op:max_with_floor": 1,
    }:
        failures.append(
            "only global/scalar dependent log10max ops should remain blocked, got "
            f"{binding_summary['unsupported_role_counts']}"
        )

    template_records = lower_symbolic_bindings_to_template_records(bindings)
    record_summary = summarize_template_record_program(template_records)
    if record_summary["stage_counts"] != {"post_loop": 1, "tile_body": 6}:
        failures.append(f"unexpected template record stages: {record_summary['stage_counts']}")
    if record_summary["symbolic_role_counts"] != {
        "collective:global_max": 1,
        "tile_op:max_with_floor": 1,
    }:
        failures.append(
            "template records should block only global/max-with-floor roles, got "
            f"{record_summary['symbolic_role_counts']}"
        )

    semantic_report = lower_template_records_to_dfu3500_semantics(template_records)
    semantic_summary = summarize_dfu3500_semantic_report(semantic_report)
    if semantic_summary["proof_status_counts"] != {"proven": 5, "unproven": 2}:
        failures.append(
            "unexpected semantic proof status counts: "
            f"{semantic_summary['proof_status_counts']}"
        )
    if semantic_summary["unproven_role_counts"] != {
        "collective:global_max": 1,
        "tile_op:max_with_floor": 1,
    }:
        failures.append(
            "semantic blockers should stay on global/max-with-floor, got "
            f"{semantic_summary['unproven_role_counts']}"
        )

    schedule = build_fiber_execution_schedule(
        executable,
        semantic_report=semantic_report,
    )
    schedule_summary = summarize_fiber_execution_schedule(schedule)
    if schedule_summary["proof_status_counts"] != {"proven": 5, "unproven": 2}:
        failures.append(
            f"unexpected schedule proof statuses: {schedule_summary['proof_status_counts']}"
        )
    if schedule_summary["phase_counts"] != {"tile_body": 6, "tile_store": 1}:
        failures.append(f"unexpected schedule phases: {schedule_summary['phase_counts']}")

    template_plan = lower_schedule_to_template_ops(
        schedule,
        semantic_report=semantic_report,
        template_records=template_records,
        profile_id=LOG10MAX_SPEC.op_name,
    )
    template_summary = summarize_template_op_plan(template_plan)
    if template_summary["status_counts"] != EXPECTED_PRODUCTION_TEMPLATE_STATUS_COUNTS:
        failures.append(
            "unexpected production TemplateOp statuses: "
            f"{template_summary['status_counts']}"
        )
    if template_summary["unresolved_role_counts"] != {
        "collective:global_max": 1,
        "tile_op:max_with_floor": 1,
    }:
        failures.append(
            "TemplateOps should leave only global/max-with-floor unresolved, got "
            f"{template_summary['unresolved_role_counts']}"
        )
    if template_summary["intent_status_counts"] != {
        "candidate_unproven": 1,
        "concrete": 8,
        "symbolic_only": 1,
    }:
        failures.append(
            "unexpected production instruction-intent statuses: "
            f"{template_summary['intent_status_counts']}"
        )

    if args.write_report is not None:
        args.write_report.parent.mkdir(parents=True, exist_ok=True)
        args.write_report.write_text(
            json.dumps(plan, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if failures:
        print("stream compiler log10max fiber-chain check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler log10max fiber-chain check OK")
    print(f"fiber_ops={summary['fiber_op_count']}")
    print(f"op_sequence={summary['op_sequence']}")
    print(f"template_status_counts={summary['template_status_counts']}")
    print(f"blocked_ops={summary['blocked_ops']}")
    if args.write_report is not None:
        print(f"wrote_report={args.write_report}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check the log10max atomic FiberOp-chain report.",
    )
    parser.add_argument(
        "--write-report",
        type=Path,
        default=None,
        help="Optional path for the JSON report artifact.",
    )
    return parser.parse_args()


def _expect_dependency(
    plan: dict[str, object],
    failures: list[str],
    source: str,
    destination: str,
) -> None:
    edges = {tuple(edge) for edge in plan["fiber"]["dependency_edges_view"]}
    if (source, destination) not in edges:
        failures.append(f"missing dependency edge {source} -> {destination}")


if __name__ == "__main__":
    main()
