#!/usr/bin/env python3
"""Check Phase-2A log10max physical route COPY row plans."""

from __future__ import annotations

from gpdpu_compiler.core.program_legacy_inst import (
    FLOW_UNIT_INST_TYPE,
    LEGACY_OPS,
    OP_COPY_LATENCY,
    OPERANDS_PER_OPERAND_RAM,
    OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE,
)
from gpdpu_compiler.core.stream_compiler.log10max_ring_update_operands import (
    EXPECTED_PHASE_COUNTS,
)
from gpdpu_compiler.core.stream_compiler.log10max_route_byte_family import (
    LOG10MAX_ROUTE_BYTE_FAMILY_DECISION_ID,
    build_log10max_route_physical_row_plan_report,
    summarize_log10max_route_physical_row_plan_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_route_endpoint_patch import (
    LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER,
    LOG10MAX_ROUTE_ROW_BYTES_BLOCKER,
)


def main() -> None:
    report = build_log10max_route_physical_row_plan_report()
    summary = summarize_log10max_route_physical_row_plan_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    expected_phase_counts = {
        phase: count * OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE
        for phase, count in EXPECTED_PHASE_COUNTS.items()
    }
    if summary["decision_id"] != LOG10MAX_ROUTE_BYTE_FAMILY_DECISION_ID:
        failures.append(f"unexpected decision id: {summary}")
    if summary["logical_route_edge_count"] != 30:
        failures.append(f"expected 30 logical route edges: {summary}")
    if summary["physical_row_count"] != 120:
        failures.append(f"expected 120 physical COPY row plans: {summary}")
    if summary["phase_counts"] != expected_phase_counts:
        failures.append(f"unexpected physical phase distribution: {summary}")
    if summary["lane_counts"] != {"0": 30, "1": 30, "2": 30, "3": 30}:
        failures.append(f"unexpected lane distribution: {summary}")
    if summary["plan_status_counts"] != {"physical_row_planned": 120}:
        failures.append(f"unexpected row plan status: {summary}")
    if summary["physical_opcode_counts"] != {"COPY": 120}:
        failures.append(f"physical rows must all be COPY: {summary}")
    if summary["flow_ack_status_counts"] != {"pending_policy": 120}:
        failures.append(f"flow_ack must remain pending on all rows: {summary}")
    if summary["dst_block_binding_status_counts"] != {"bound": 120}:
        failures.append(f"dst block should be bound from layout report: {summary}")
    if summary["physical_local_pc_status_counts"] != {"candidate_bound": 120}:
        failures.append(f"physical local pc should be candidate-bound: {summary}")
    if LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER not in summary["blocker_ids"]:
        failures.append(f"flow_ack blocker must remain: {summary}")
    if LOG10MAX_ROUTE_ROW_BYTES_BLOCKER not in summary["blocker_ids"]:
        failures.append(f"route row bytes blocker must remain: {summary}")
    if summary["row_bytes_claim"] is not False:
        failures.append("physical row plan must not claim row bytes")
    if summary["final_component_claim"] is not False:
        failures.append("physical row plan must not claim final component")
    if summary["runtime_ready"] is not False:
        failures.append("physical row plan must not claim runtime_ready")
    if summary["uploadable"] is not False:
        failures.append("physical row plan must not claim uploadable")

    rows_by_edge: dict[str, list[dict[str, object]]] = {}
    seen_row_ids: set[str] = set()
    for row in plan["physical_rows"]:
        row_id = str(row["row_plan_id"])
        if row_id in seen_row_ids:
            failures.append(f"duplicate physical row plan id: {row}")
        seen_row_ids.add(row_id)
        edge_id = str(row["logical_route_edge_id"])
        rows_by_edge.setdefault(edge_id, []).append(row)

        lane = int(row["lane_index"])
        if lane not in range(OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE):
            failures.append(f"invalid lane index: {row}")
        if row["lane_count"] != OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE:
            failures.append(f"lane_count mismatch: {row}")
        if row["lane_stride"] != OPERANDS_PER_OPERAND_RAM:
            failures.append(f"lane_stride mismatch: {row}")
        if row["source_template_family"] != "COPYT":
            failures.append(f"source template must be COPYT: {row}")
        if row["physical_opcode_name"] != "COPY":
            failures.append(f"physical opcode name must be COPY: {row}")
        if row["physical_opcode"] != LEGACY_OPS["COPY"].opcode:
            failures.append(f"physical COPY opcode mismatch: {row}")
        if row["physical_unit_inst_type"] != FLOW_UNIT_INST_TYPE:
            failures.append(f"COPY rows must be FLOW unit: {row}")
        if row["physical_latency"] != OP_COPY_LATENCY:
            failures.append(f"COPY latency mismatch: {row}")
        expected_src = int(row["src_operand_base_idx"]) + lane * OPERANDS_PER_OPERAND_RAM
        expected_dst = int(row["dst_operand_base_idx"]) + lane * OPERANDS_PER_OPERAND_RAM
        if row["src_operand_idx"] != expected_src:
            failures.append(f"source lane operand mismatch: {row}")
        if row["dst_operand_idx"] != expected_dst:
            failures.append(f"destination lane operand mismatch: {row}")
        if row["src_allocation_scope"] != row["expected_src_allocation_scope"]:
            failures.append(f"source scope mismatch: {row}")
        if row["dst_allocation_scope"] != row["expected_dst_allocation_scope"]:
            failures.append(f"destination scope mismatch: {row}")
        if row["dst_block_idx"] is None:
            failures.append(f"dst block should be bound from receiver layout: {row}")
        if row["dst_block_binding_status"] != "bound":
            failures.append(f"dst block status should be bound: {row}")
        if row["receiver_exe_block_writer_plan_id"] is None:
            failures.append(f"receiver exeBlock owner missing: {row}")
        if row["physical_local_pc"] is None:
            failures.append(f"physical local pc candidate missing: {row}")
        if row["physical_local_pc_status"] != "candidate_bound":
            failures.append(f"physical local pc should be candidate-bound: {row}")
        if row["flow_ack"] is not None:
            failures.append(f"flow_ack must not be silently filled: {row}")
        if row["flow_ack_policy_id"] is not None:
            failures.append(f"flow_ack policy id must stay pending: {row}")
        if row["flow_ack_status"] != "pending_policy":
            failures.append(f"flow_ack status must stay pending_policy: {row}")
        if LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER not in row["blocker_ids"]:
            failures.append(f"flow_ack blocker missing: {row}")
        if LOG10MAX_ROUTE_ROW_BYTES_BLOCKER not in row["blocker_ids"]:
            failures.append(f"row bytes blocker missing: {row}")
        if row["row_bytes_claim"] is not False:
            failures.append(f"physical row plan must not claim bytes: {row}")
        if row["final_component_claim"] is not False:
            failures.append(f"physical row plan must not claim component: {row}")
        if row["runtime_ready"] is not False:
            failures.append(f"physical row plan must not claim runtime_ready: {row}")
        if row["uploadable"] is not False:
            failures.append(f"physical row plan must not claim uploadable: {row}")

    for edge_id, rows in rows_by_edge.items():
        lanes = sorted(int(row["lane_index"]) for row in rows)
        if lanes != [0, 1, 2, 3]:
            failures.append(f"edge {edge_id} must have lanes 0..3, got {lanes}")

    if failures:
        print("stream compiler log10max route physical row plan check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max route physical row plan check OK")
    print(f"logical_route_edge_count={summary['logical_route_edge_count']}")
    print(f"physical_row_count={summary['physical_row_count']}")
    print(f"phase_counts={summary['phase_counts']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


if __name__ == "__main__":
    main()
