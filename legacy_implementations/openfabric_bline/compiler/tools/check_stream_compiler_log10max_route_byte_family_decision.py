#!/usr/bin/env python3
"""Check Phase-2A log10max route byte family decision."""

from __future__ import annotations

from gpdpu_compiler.core.program_legacy_inst import (
    FLOW_UNIT_INST_TYPE,
    LEGACY_OPS,
    OP_COPY_LATENCY,
    OPERANDS_PER_OPERAND_RAM,
    OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE,
)
from gpdpu_compiler.core.stream_compiler.log10max_route_byte_family import (
    LOG10MAX_ROUTE_BYTE_FAMILY_DECISION_ID,
    build_log10max_route_byte_family_decision_report,
    summarize_log10max_route_byte_family_decision_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_route_endpoint_patch import (
    LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER,
    LOG10MAX_ROUTE_ROW_BYTES_BLOCKER,
)


def main() -> None:
    report = build_log10max_route_byte_family_decision_report()
    summary = summarize_log10max_route_byte_family_decision_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["decision_id"] != LOG10MAX_ROUTE_BYTE_FAMILY_DECISION_ID:
        failures.append(f"unexpected decision id: {summary}")
    if summary["logical_family"] != "copyt_logical_globalmax_route":
        failures.append(f"wrong logical family: {summary}")
    if summary["physical_family"] != "copyt_logical_expanded_copy_rows":
        failures.append(f"wrong physical family: {summary}")
    if summary["route_opcode_family"] != "COPYT":
        failures.append(f"route family must be logical COPYT: {summary}")
    if summary["physical_opcode_name"] != "COPY":
        failures.append(f"physical rows must be COPY: {summary}")
    if summary["physical_opcode"] != LEGACY_OPS["COPY"].opcode:
        failures.append(f"COPY opcode mismatch: {summary}")
    if summary["physical_unit_inst_type"] != FLOW_UNIT_INST_TYPE:
        failures.append(f"COPY must be FLOW unit: {summary}")
    if summary["physical_latency"] != OP_COPY_LATENCY:
        failures.append(f"COPY latency mismatch: {summary}")
    if summary["logical_value_kind"] != "replicated_vector":
        failures.append(f"GlobalMax must stay replicated vector: {summary}")
    if summary["dtype"] != "fp32":
        failures.append(f"GlobalMax dtype must be fp32: {summary}")
    if summary["logical_width_bits"] != 4096:
        failures.append(f"GlobalMax logical width must be 4096 bits: {summary}")
    if summary["lane_count"] != OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE:
        failures.append(f"COPYT lane count mismatch: {summary}")
    if summary["lane_stride"] != OPERANDS_PER_OPERAND_RAM:
        failures.append(f"COPYT lane stride mismatch: {summary}")
    if summary["route_family_status"] != "selected_candidate":
        failures.append(f"decision must be candidate-selected: {summary}")
    if summary["flow_ack_policy_status"] != "pending_policy":
        failures.append(f"flow_ack must remain pending policy: {summary}")
    if LOG10MAX_ROUTE_ENDPOINT_FLOW_ACK_BLOCKER not in summary["blocker_ids"]:
        failures.append(f"flow_ack blocker must remain: {summary}")
    if LOG10MAX_ROUTE_ROW_BYTES_BLOCKER not in summary["blocker_ids"]:
        failures.append(f"row bytes blocker must remain: {summary}")
    if summary["row_bytes_claim"] is not False:
        failures.append("Phase 2A decision must not claim row bytes")
    if summary["final_component_claim"] is not False:
        failures.append("Phase 2A decision must not claim final component")
    if summary["runtime_ready"] is not False:
        failures.append("Phase 2A decision must not claim runtime_ready")
    if summary["uploadable"] is not False:
        failures.append("Phase 2A decision must not claim uploadable")
    if plan["decision"]["row_bytes_claim"] is not False:
        failures.append(f"decision row bytes claim must be false: {plan}")
    if plan["decision"]["final_component_claim"] is not False:
        failures.append(f"decision component claim must be false: {plan}")

    if failures:
        print("stream compiler log10max route byte family decision check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max route byte family decision check OK")
    print(f"decision_id={summary['decision_id']}")
    print(f"physical_family={summary['physical_family']}")
    print(f"lane_count={summary['lane_count']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


if __name__ == "__main__":
    main()
