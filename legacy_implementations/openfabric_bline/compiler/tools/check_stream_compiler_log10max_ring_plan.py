#!/usr/bin/env python3
"""Focused check for the log10max task-local ring delivery plan."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gpdpu_compiler.core.stream_compiler.log10max_ring_plan import (  # noqa: E402
    build_log10max_task_local_ring_plan,
    summarize_log10max_task_local_ring_plan,
)


EXPECTED_PHASE_COUNTS = {
    "col_broadcast": 3,
    "col_reduce": 3,
    "row_broadcast": 12,
    "row_reduce": 12,
}
EXPECTED_BLOCKERS = [
    "route_role_globalmax_unproven",
    "ring_edge_route_template_missing",
    "ring_edge_update_template_missing",
    "ring_edge_template_missing",
    "route_path_proof_missing",
    "consumer_global_max_binding_missing",
    "consumer_depends_on_global_ready_missing",
    "symbolic_global_max_reaches_postprocess",
]


def main() -> None:
    args = _parse_args()
    report = build_log10max_task_local_ring_plan()
    plan = report.to_plan()
    summary = summarize_log10max_task_local_ring_plan(report)
    failures: list[str] = []

    if summary["strategy"] != "ring_spmd_row_then_col":
        failures.append(f"unexpected strategy: {summary['strategy']}")
    if summary["customer_label"] != "spmd_ring_materialized_reduce":
        failures.append(f"unexpected customer label: {summary['customer_label']}")
    if summary["task_axis"] != 1:
        failures.append(f"task_axis must be 1 for one-app ring: {summary}")
    if summary["runtime_ordering_domain"] != "single_task_group":
        failures.append(f"unexpected ordering domain: {summary}")
    if summary["edge_count"] != 30:
        failures.append(f"representative 4x4 ring must emit 30 edges: {summary}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected phase counts: {summary['phase_counts']}")
    if summary["global_max_ready_count"] != 16:
        failures.append(f"each consumer PE needs global_max_ready: {summary}")
    if summary["postprocess_consumer_count"] != 16:
        failures.append(f"each PE needs a postprocess consumer binding: {summary}")
    if summary["postprocess_consumer_binding_count"] != 0:
        failures.append(
            "bare plan must not prove postprocess consumers before templates close: "
            f"{summary}"
        )
    if summary["symbolic_postprocess_consumer_count"] != 16:
        failures.append(f"bare plan must keep postprocess symbolic: {summary}")
    if summary["physical_allreduce_claim"] is not False:
        failures.append("ring plan must not claim physical allreduce")
    if summary["direct_route_reduce_broadcast"] != "deferred":
        failures.append("direct route reduce broadcast must stay deferred")
    if summary["one_app_cross_task_ring"] != "forbidden":
        failures.append("one-app cross-task ring must stay forbidden")
    if summary["runtime_ready"] is not False:
        failures.append("ring plan must fail closed until route proofs bind")
    if summary["runtime_ready_blockers"] != EXPECTED_BLOCKERS:
        failures.append(
            "unexpected runtime blockers: "
            f"expected {EXPECTED_BLOCKERS}, got {summary['runtime_ready_blockers']}"
        )

    role = plan["route_role_binding"]
    if role["role"] != "GlobalMax":
        failures.append(f"expected GlobalMax route role, got {role}")
    if role["authority_boundary"] != "role_generalization_only_reuses_existing_route_primitive":
        failures.append(f"route role must remain existing-primitive generalization: {role}")
    if role["proof_status"] != "unresolved":
        failures.append(f"GlobalMax route proof must start fail-closed: {role}")

    edges = plan["ring_edges"]
    if any(edge["task_id"] != 0 for edge in edges):
        failures.append("all first-delivery ring edges must stay inside task 0")
    if any(edge["cross_task_edge"] for edge in edges):
        failures.append("no ring edge may be marked cross_task_edge")
    if any(edge["route_role"] != "GlobalMax" for edge in edges):
        failures.append("all ring edges must use GlobalMax route role")
    if any(edge["update_op"] != "FMAX" for edge in edges):
        failures.append("fp32 log10max ring must use FMAX updates")
    if any(edge["route_template_status"] != "unresolved" for edge in edges):
        failures.append("route templates must start fail-closed before binding proof")
    if any(edge["update_template_status"] != "unresolved" for edge in edges):
        failures.append("update templates must start fail-closed before FMAX/HMAX proof")
    if any(edge["route_path_proof_status"] != "unresolved" for edge in edges):
        failures.append("route path proof must start fail-closed in bare plan")
    if any(not edge["route_template_evidence_id"] for edge in edges):
        failures.append("route template evidence id must be explicit per edge")
    if any(not edge["update_template_evidence_id"] for edge in edges):
        failures.append("update template evidence id must be explicit per edge")
    if any(
        edge["update_template_blocker"] != "ring_edge_update_template_missing"
        for edge in edges
    ):
        failures.append("update template blocker must be precise per edge")
    if any(edge["authority"] != "derived_from_stream_actions" for edge in edges):
        failures.append("ring edge records must be derived metadata")

    _check_phase_order(edges, failures)
    _check_stream_actions(plan, failures)
    _check_ready_tokens(plan, failures)
    _check_postprocess_consumers(plan, failures)

    if args.json:
        print(json.dumps(plan, indent=2, sort_keys=True))

    if failures:
        print("stream compiler log10max ring plan check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max ring plan check OK")


def _check_phase_order(edges: list[dict[str, object]], failures: list[str]) -> None:
    phases = [str(edge["phase"]) for edge in edges]
    expected = (
        ["row_reduce"] * 12
        + ["col_reduce"] * 3
        + ["col_broadcast"] * 3
        + ["row_broadcast"] * 12
    )
    if phases != expected:
        failures.append(f"unexpected representative phase order: {phases}")
    if edges[0]["src_pe"] != "PE(0,3)" or edges[0]["dst_pe"] != "PE(0,2)":
        failures.append(f"first row reduce edge should start at row0 col3: {edges[0]}")
    if edges[11]["src_pe"] != "PE(3,1)" or edges[11]["dst_pe"] != "PE(3,0)":
        failures.append(f"last row reduce edge should end at row3 col0: {edges[11]}")
    if edges[12]["src_pe"] != "PE(3,0)" or edges[14]["dst_pe"] != "PE(0,0)":
        failures.append("column reduce should run from PE(3,0) to PE(0,0)")
    if edges[15]["src_pe"] != "PE(0,0)" or edges[17]["dst_pe"] != "PE(3,0)":
        failures.append("column broadcast should run from PE(0,0) to PE(3,0)")
    if edges[18]["src_pe"] != "PE(0,0)" or edges[-1]["dst_pe"] != "PE(3,3)":
        failures.append("row broadcast should cover all row consumers")


def _check_stream_actions(plan: dict[str, object], failures: list[str]) -> None:
    stream_plan = plan["stream_plan"]
    streams = stream_plan["streams"]
    actions = [
        action
        for stream_actions in streams.values()
        for action in stream_actions
    ]
    route_push = [action for action in actions if action["op"] == "route_push_global_max"]
    route_recv = [action for action in actions if action["op"] == "route_recv_global_max"]
    updates = [action for action in actions if action["op"] == "max_update_global_max"]
    if len(route_push) != 30 or len(route_recv) != 30 or len(updates) != 30:
        failures.append(
            "each edge must have route_push, route_recv, max_update actions: "
            f"{len(route_push)}, {len(route_recv)}, {len(updates)}"
        )
    for recv in route_recv:
        deps = recv["depends_on"]
        if len(deps) != 1:
            failures.append(f"route_recv must depend on exactly one push: {recv}")
        elif not str(deps[0]).startswith("log10max_ring:route_push_global_max:"):
            failures.append(f"route_recv dependency must be route_push: {recv}")
    for update in updates:
        deps = update["depends_on"]
        if len(deps) != 2:
            failures.append(f"max_update must depend on prior value and recv: {update}")
        if not any(str(dep).startswith("log10max_ring:route_recv_global_max:") for dep in deps):
            failures.append(f"max_update must depend on route_recv: {update}")


def _check_ready_tokens(plan: dict[str, object], failures: list[str]) -> None:
    ready = plan["global_max_ready"]
    if len(set(ready)) != 16:
        failures.append("global_max_ready tokens must be unique per PE")
    for x in range(4):
        for y in range(4):
            prefix = f"global_max_ready[task=0,pe={x},{y}]<-"
            if not any(str(token).startswith(prefix) for token in ready):
                failures.append(f"missing ready token for PE({x},{y})")


def _check_postprocess_consumers(
    plan: dict[str, object],
    failures: list[str],
) -> None:
    consumers = plan["postprocess_consumer_bindings"]
    ready = set(plan["global_max_ready"])
    if len(consumers) != 16:
        failures.append(f"expected 16 postprocess consumer bindings: {consumers}")
        return
    if plan["consumer_global_max_binding"]["status"] != "unresolved":
        failures.append("bare consumer_global_max_binding must wait for templates")
    if plan["consumer_global_max_ready_dependencies"]["status"] != "unresolved":
        failures.append("bare consumer ready dependencies must wait for templates")
    if plan["symbolic_global_max_reaches_postprocess"] is not True:
        failures.append("bare postprocess must remain symbolic")
    for consumer in consumers:
        if consumer["consumer_fiber_op"] != "max_with_floor_tile":
            failures.append(f"wrong postprocess consumer op: {consumer}")
        if consumer["source_expression"] != "maximum(log_spec_tile, GlobalMax - 8.0)":
            failures.append(f"wrong postprocess expression: {consumer}")
        if consumer["global_max_input"] != "GlobalMax":
            failures.append(f"wrong global max input binding: {consumer}")
        if consumer["global_max_ready_token"] not in ready:
            failures.append(f"consumer token not in global_max_ready set: {consumer}")
        if consumer["depends_on_global_max_ready"] is not True:
            failures.append(f"consumer must depend on global_max_ready: {consumer}")
        if consumer["symbolic_global_max_reaches_postprocess"] is not True:
            failures.append(f"bare consumer should stay symbolic: {consumer}")
        if consumer["proof_status"] != "unresolved":
            failures.append(f"bare consumer binding should be unresolved: {consumer}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check the B-line log10max task-local ring plan.",
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


if __name__ == "__main__":
    main()
