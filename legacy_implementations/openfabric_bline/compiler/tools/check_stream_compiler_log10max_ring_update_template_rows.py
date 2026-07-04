#!/usr/bin/env python3
"""Check Phase-3 log10max ring update BinaryLayout row candidates."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gpdpu_compiler.core.stream_compiler.log10max_ring_update_template import (
    build_log10max_ring_update_binary_layout_candidate_report,
    summarize_log10max_ring_update_binary_layout_candidate_report,
)


EXPECTED_PHASE_COUNTS = {
    "col_broadcast": 3,
    "col_reduce": 3,
    "row_broadcast": 12,
    "row_reduce": 12,
}


def main() -> None:
    report = build_log10max_ring_update_binary_layout_candidate_report()
    summary = summarize_log10max_ring_update_binary_layout_candidate_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["template_op_count"] != 30:
        failures.append(f"expected 30 TemplateOp candidates: {summary}")
    if summary["row_candidate_count"] != 30:
        failures.append(f"expected 30 row candidates: {summary}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected phase distribution: {summary}")
    if summary["opcode_counts"] != {"FMAX": 30}:
        failures.append(f"fp32 V1 must use FMAX row candidates: {summary}")
    if summary["subtask_counts"] != {"log10max_ring_globalmax_update": 30}:
        failures.append(f"unexpected subtask distribution: {summary}")
    if summary["template_status_counts"] != {"layout_candidate": 30}:
        failures.append(f"TemplateOps must stop at layout_candidate: {summary}")
    if summary["layout_status_counts"] != {"layout_candidate": 30}:
        failures.append(f"row candidates must stop at layout_candidate: {summary}")
    if summary["row_byte_status_counts"] != {"row_bytes_missing": 60}:
        failures.append(f"TemplateOp/Layout candidates must keep bytes missing: {summary}")
    if summary["blocker_ids"] != ["log10max_ring_update_row_bytes_missing"]:
        failures.append(f"Phase 3 must keep row-byte blocker: {summary}")
    if summary["runtime_ready"] is not False:
        failures.append("Phase 3 row candidates must keep runtime_ready false")
    if summary["row_bytes_claim"] is not False:
        failures.append("Phase 3 must not claim row bytes")
    if summary["concrete_template_claim"] is not False:
        failures.append("Phase 3 must not claim concrete_template")
    if summary["inst_t_row_count"] != 0:
        failures.append("Phase 3 must not create inst_t rows")
    if summary["vendor_row_count"] != 0:
        failures.append("Phase 3 must not create vendor rows")
    if summary["raw_inst_t_byte_count"] != 0:
        failures.append("Phase 3 must not create raw inst_t bytes")
    if summary["inst_t_bytes_emitted"] is not False:
        failures.append("Phase 3 must not emit inst_t bytes")
    if summary["decode_roundtrip_claim"] is not False:
        failures.append("Phase 3 must not claim decode roundtrip")
    if plan["source_artifact_kind"] != "log10max_ring_update_template_binding_report":
        failures.append(f"unexpected source artifact: {plan['source_artifact_kind']}")

    template_ops = plan["template_ops"]
    rows = plan["binary_layout_row_candidates"]
    template_ids = {str(op["template_op_id"]) for op in template_ops}
    expansion_ids = {str(op["template_expansion_id"]) for op in template_ops}
    seen_rows: set[str] = set()
    seen_edges: set[str] = set()

    for op in template_ops:
        if not op["source_binding_id"]:
            failures.append(f"TemplateOp candidate missing binding provenance: {op}")
        if not op["source_ring_edge_id"]:
            failures.append(f"TemplateOp candidate missing edge provenance: {op}")
        if not op["source_fiber_op_id"]:
            failures.append(f"TemplateOp candidate missing FiberOp provenance: {op}")
        if not op["source_stream_action_id"]:
            failures.append(f"TemplateOp candidate missing stream provenance: {op}")
        if not op["template_expansion_id"]:
            failures.append(f"TemplateOp candidate missing expansion id: {op}")
        if op["template_status"] != "layout_candidate":
            failures.append(f"unexpected TemplateOp candidate status: {op}")
        if op["template_status"] == "concrete_template":
            failures.append(f"TemplateOp candidate must not be concrete_template: {op}")
        if op["source_fiber_op_kind"] != "global_max_tile":
            failures.append(f"TemplateOp must bind atomic global_max_tile FiberOp: {op}")
        if op["semantic_op"] != "max_update_global_max":
            failures.append(f"TemplateOp must bind only ring max_update_global_max: {op}")
        if op["route_role"] != "GlobalMax":
            failures.append(f"TemplateOp must bind only GlobalMax route role: {op}")
        if op["fiber_op_atomicity"] != "fiber_atomic_tile_job":
            failures.append(f"TemplateOp must preserve FiberOp atomicity: {op}")
        if op["role"] == "generic_collective":
            failures.append(f"TemplateOp must not use generic collective role: {op}")
        if op["instruction_intent_opcode"] != "FMAX":
            failures.append(f"unexpected TemplateOp opcode: {op}")
        if op["row_byte_status"] != "row_bytes_missing":
            failures.append(f"TemplateOp candidate must keep row bytes missing: {op}")
        if op["row_bytes_claim"] is not False:
            failures.append(f"TemplateOp candidate must not claim row bytes: {op}")

    for row in rows:
        row_id = str(row["row_candidate_id"])
        edge_id = str(row["source_ring_edge_id"])
        if row_id in seen_rows:
            failures.append(f"duplicate row candidate id: {row_id}")
        seen_rows.add(row_id)
        if edge_id in seen_edges:
            failures.append(f"duplicate row for ring edge: {edge_id}")
        seen_edges.add(edge_id)
        if row["template_op_id"] not in template_ids:
            failures.append(f"row missing TemplateOp provenance: {row}")
        if row["template_expansion_id"] not in expansion_ids:
            failures.append(f"row missing template expansion provenance: {row}")
        if not row["source_binding_id"]:
            failures.append(f"row missing binding provenance: {row}")
        if not row["source_fiber_op_id"]:
            failures.append(f"row missing FiberOp provenance: {row}")
        if not row["source_stream_action_id"]:
            failures.append(f"row missing stream provenance: {row}")
        if row["opcode"] != "FMAX":
            failures.append(f"unexpected row opcode: {row}")
        if row["source_fiber_op_kind"] != "global_max_tile":
            failures.append(f"row must retain source FiberOp kind: {row}")
        if row["semantic_op"] != "max_update_global_max":
            failures.append(f"row must retain ring update semantic_op: {row}")
        if row["route_role"] != "GlobalMax":
            failures.append(f"row must retain GlobalMax route role: {row}")
        if row["fiber_op_atomicity"] != "fiber_atomic_tile_job":
            failures.append(f"row must retain FiberOp atomicity: {row}")
        if row["role"] == "generic_collective":
            failures.append(f"row must not use generic collective role: {row}")
        if row["subtask_slot"] != "log10max_ring_globalmax_update":
            failures.append(f"unexpected subtask slot: {row}")
        if row["src_current_operand"] != "globalmax_acc_in":
            failures.append(f"unexpected src_current operand: {row}")
        if row["src_received_operand"] != "globalmax_recv":
            failures.append(f"unexpected src_received operand: {row}")
        if row["dst_updated_operand"] != "globalmax_acc_out":
            failures.append(f"unexpected dst operand: {row}")
        if row["layout_status"] != "layout_candidate":
            failures.append(f"row should only be layout-candidate: {row}")
        if row["row_byte_status"] != "row_bytes_missing":
            failures.append(f"row must keep row bytes missing: {row}")
        if row["blocker_ids"] != ["log10max_ring_update_row_bytes_missing"]:
            failures.append(f"row must keep byte blocker: {row}")
        if row["row_bytes_claim"] is not False:
            failures.append(f"row must not claim bytes: {row}")
        if row["inst_t_row_count"] != 0:
            failures.append(f"row must not materialize inst_t rows: {row}")
        if row["vendor_row_count"] != 0:
            failures.append(f"row must not materialize vendor rows: {row}")
        if row["raw_inst_t_byte_count"] != 0:
            failures.append(f"row must not materialize raw inst_t bytes: {row}")
        if row["inst_t_bytes_emitted"] is not False:
            failures.append(f"row must not emit inst_t bytes: {row}")
        if row["decode_roundtrip_claim"] is not False:
            failures.append(f"row must not claim decode roundtrip: {row}")
        if row["created_directly_from_ring_edge"] is not False:
            failures.append(f"row must not be direct RingEdge emission: {row}")

    if failures:
        print("stream compiler log10max ring update template rows check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max ring update template rows check OK")
    print(f"row_candidate_count={summary['row_candidate_count']}")
    print(f"blocker_ids={summary['blocker_ids']}")


if __name__ == "__main__":
    main()
