#!/usr/bin/env python3
"""Check log10max ring StreamAction -> FiberOp projection."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gpdpu_compiler.core.stream_compiler.log10max_ring_fiber_projection import (  # noqa: E402
    build_log10max_ring_fiber_projection_report,
    summarize_log10max_ring_fiber_projection_report,
)


EXPECTED_PHASE_COUNTS = {
    "col_broadcast": 3,
    "col_reduce": 3,
    "row_broadcast": 12,
    "row_reduce": 12,
}
EXPECTED_FIBER_OP_COUNTS = {
    "fragment_route_push": 30,
    "fragment_route_recv": 30,
    "global_max_tile": 30,
}


def main() -> None:
    args = _parse_args()
    report = build_log10max_ring_fiber_projection_report()
    plan = report.to_plan()
    summary = summarize_log10max_ring_fiber_projection_report(report)
    failures: list[str] = []

    if summary["strategy"] != "ring_spmd_row_then_col":
        failures.append(f"unexpected strategy: {summary['strategy']}")
    if summary["task_axis"] != 1:
        failures.append(f"task_axis must be 1: {summary}")
    if summary["runtime_ordering_domain"] != "single_task_group":
        failures.append(f"unexpected ordering domain: {summary}")
    if summary["record_count"] != 30:
        failures.append(f"representative ring must project 30 edges: {summary}")
    if summary["fiber_count"] != 16:
        failures.append(f"4x4 task-local ring should produce 16 fibers: {summary}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected phase counts: {summary['phase_counts']}")
    if summary["fiber_op_counts"] != EXPECTED_FIBER_OP_COUNTS:
        failures.append(f"unexpected FiberOp counts: {summary['fiber_op_counts']}")
    if summary["route_path_proof_status_counts"] != {"satisfied": 30}:
        failures.append(f"route proofs should be satisfied: {summary}")
    if summary["blocker_counts"] != {}:
        failures.append(f"projection blockers must be empty: {summary['blocker_counts']}")
    if summary["diagnostic_count"] != 0:
        failures.append(f"projection diagnostics must be empty: {plan['diagnostics']}")
    if summary["communication_ir_created"] is not False:
        failures.append("projection must not create communication IR")
    if summary["one_app_cross_task_route_edge_allowed"] is not False:
        failures.append("one-app cross-task route edges must remain forbidden")

    projection_summary = plan["projection_summary"]
    if projection_summary["proof_kind_counts"] != {"route_path": 30}:
        failures.append(
            "projection should prove receiver visibility through route_path: "
            f"{projection_summary}"
        )
    if projection_summary["block_kind_counts"] != EXPECTED_FIBER_OP_COUNTS:
        failures.append(f"unexpected block projection counts: {projection_summary}")

    _check_records(plan, failures)
    _check_fibers(plan, failures)

    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))

    if failures:
        print("stream compiler log10max ring fiber projection check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max ring fiber projection check OK")


def _check_records(plan: dict[str, object], failures: list[str]) -> None:
    records = plan["records"]
    assert isinstance(records, list)
    for record in records:
        assert isinstance(record, dict)
        if not record["projected"]:
            failures.append(f"record did not project cleanly: {record}")
        if record["task_id"] != 0:
            failures.append(f"record crosses task boundary: {record}")
        if record["recv_dependency_expected_satisfaction"] != "route_or_local_materialization":
            failures.append(f"recv dependency uses wrong satisfaction: {record}")
        route_fragment = record["route_fragment"]
        assert isinstance(route_fragment, dict)
        if route_fragment["role"] != "GlobalMax":
            failures.append(f"ring route fragment must be GlobalMax: {record}")
        route_trace = record["route_path_stream_action_ids"]
        assert isinstance(route_trace, list)
        if len(route_trace) < 2:
            failures.append(f"route trace should include push and recv: {record}")
            continue
        if record["source_stream_action_id"] not in route_trace:
            failures.append(f"route trace must include source push action: {record}")
        if route_trace[-1] != record["recv_stream_action_id"]:
            failures.append(f"route trace must end at recv action: {record}")


def _check_fibers(plan: dict[str, object], failures: list[str]) -> None:
    fibers = plan["fibers"]
    assert isinstance(fibers, list)
    for fiber in fibers:
        assert isinstance(fiber, dict)
        if fiber["attrs"].get("communication_ir_created") is not False:
            failures.append(f"fiber must not create communication IR: {fiber['id']}")
        if fiber["attrs"].get("task_local_only") is not True:
            failures.append(f"fiber must be task-local only: {fiber['id']}")
        for op in fiber["ops"]:
            assert isinstance(op, dict)
            attrs = op["attrs"]
            assert isinstance(attrs, dict)
            if attrs.get("route_role") != "GlobalMax":
                failures.append(f"ring FiberOp must carry GlobalMax role: {op}")
            if attrs.get("task_id") != 0:
                failures.append(f"ring FiberOp must stay in task 0: {op}")
            if op["op"] == "fragment_route_recv":
                if not op["outputs"]:
                    failures.append(f"route recv must output GlobalMax fragment: {op}")
                if attrs.get("template_evidence_id") != (
                    "pending_globalmax_existing_route_template_binding"
                ):
                    failures.append(f"route recv must carry route evidence id: {op}")
            if op["op"] == "global_max_tile":
                if attrs.get("template_evidence_id") != (
                    "dfu3500_log10max_ring_globalmax_update_fmax_candidate_unproven"
                ):
                    failures.append(f"global max update must carry update evidence id: {op}")
                if attrs.get("template_blocker") != "ring_edge_update_template_missing":
                    failures.append(f"global max update must carry precise blocker: {op}")
                deps = op["depends_on"]
                assert isinstance(deps, list)
                if len(deps) != 1:
                    failures.append(f"max update must depend on route recv: {op}")
                    continue
                dep = deps[0]
                assert isinstance(dep, dict)
                if dep["expected_satisfaction"] != "route_or_local_materialization":
                    failures.append(f"max update dependency is not route proof: {op}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check log10max ring StreamAction -> FiberOp projection.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
