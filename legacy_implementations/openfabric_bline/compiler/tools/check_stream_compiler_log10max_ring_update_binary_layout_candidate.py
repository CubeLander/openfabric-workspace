#!/usr/bin/env python3
"""Check Phase-2/3 log10max ring update TemplateOp/Layout candidates."""

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
        failures.append(f"expected 30 BinaryLayout row candidates: {summary}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected phase distribution: {summary}")
    if summary["opcode_counts"] != {"FMAX": 30}:
        failures.append(f"fp32 V1 must keep FMAX row candidates: {summary}")
    if summary["subtask_counts"] != {"log10max_ring_globalmax_update": 30}:
        failures.append(f"unexpected subtask placement: {summary}")
    if summary["template_status_counts"] != {"layout_candidate": 30}:
        failures.append(f"unexpected TemplateOp status counts: {summary}")
    if summary["layout_status_counts"] != {"layout_candidate": 30}:
        failures.append(f"unexpected row layout status counts: {summary}")
    if summary["row_byte_status_counts"] != {"row_bytes_missing": 60}:
        failures.append(f"unexpected row byte status counts: {summary}")
    if summary["blocker_ids"] != ["log10max_ring_update_row_bytes_missing"]:
        failures.append(f"Phase 3 must keep row-byte blocker: {summary}")
    if summary["runtime_ready"] is not False:
        failures.append("BinaryLayout candidates must not claim runtime_ready")
    if summary["row_bytes_claim"] is not False:
        failures.append("BinaryLayout candidates must not claim row bytes")
    if summary["concrete_template_claim"] is not False:
        failures.append("Phase 3 must not claim concrete templates")
    if summary["inst_t_row_count"] != 0:
        failures.append("Phase 3 must not allocate inst_t rows")
    if summary["vendor_row_count"] != 0:
        failures.append("Phase 3 must not allocate vendor rows")
    if summary["raw_inst_t_byte_count"] != 0:
        failures.append("Phase 3 must not emit raw inst_t bytes")
    if summary["inst_t_bytes_emitted"] is not False:
        failures.append("Phase 3 must not emit inst_t bytes")
    if summary["decode_roundtrip_claim"] is not False:
        failures.append("Phase 3 must not claim decode roundtrip")

    template_ops = plan["template_ops"]
    row_candidates = plan["binary_layout_row_candidates"]
    template_op_ids = {str(op["template_op_id"]) for op in template_ops}
    edge_ids = {str(op["source_ring_edge_id"]) for op in template_ops}

    if len(template_op_ids) != 30:
        failures.append("TemplateOp candidate ids must be unique")
    if len(edge_ids) != 30:
        failures.append("Ring edge provenance ids must be unique")

    for op in template_ops:
        if op["role"] != "collective:global_max":
            failures.append(f"unexpected TemplateOp role: {op}")
        if op["template_family"] != "dfu3500_log10max_ring_globalmax_update":
            failures.append(f"unexpected template family: {op}")
        if op["template_status"] != "layout_candidate":
            failures.append(f"unexpected TemplateOp status: {op}")
        if op["row_byte_status"] != "row_bytes_missing":
            failures.append(f"TemplateOp must keep byte blocker visible: {op}")
        if op["instruction_intent_opcode"] != "FMAX":
            failures.append(f"unexpected TemplateOp opcode intent: {op}")
        if op["operand_policy"] != "globalmax_acc_in_recv_acc_out_non_inplace":
            failures.append(f"unexpected operand policy: {op}")
        if not op["source_fiber_op_id"]:
            failures.append(f"TemplateOp missing FiberOp provenance: {op}")
        if not op["source_stream_action_id"]:
            failures.append(f"TemplateOp missing stream action provenance: {op}")
        if not op["template_expansion_id"]:
            failures.append(f"TemplateOp missing expansion provenance: {op}")
        if op["row_bytes_claim"] is not False:
            failures.append(f"TemplateOp must not claim row bytes: {op}")

    seen_rows: set[int] = set()
    for row in row_candidates:
        row_index = int(row["row_index"])
        if row_index in seen_rows:
            failures.append(f"duplicate row index: {row}")
        seen_rows.add(row_index)
        if row["pc"] != row["row_index"]:
            failures.append(f"Phase 3 row pc must match candidate row index: {row}")
        if row["template_op_id"] not in template_op_ids:
            failures.append(f"row missing TemplateOp provenance: {row}")
        if not row["source_fiber_op_id"]:
            failures.append(f"row missing FiberOp provenance: {row}")
        if not row["source_stream_action_id"]:
            failures.append(f"row missing stream action provenance: {row}")
        if not row["source_ring_edge_id"]:
            failures.append(f"row missing ring edge provenance: {row}")
        if not row["template_expansion_id"]:
            failures.append(f"row missing template expansion provenance: {row}")
        if row["layout_status"] != "layout_candidate":
            failures.append(f"row must stay layout-candidate: {row}")
        if row["row_byte_status"] != "row_bytes_missing":
            failures.append(f"row must keep byte blocker visible: {row}")
        if row["created_directly_from_ring_edge"] is not False:
            failures.append(f"row must not shortcut directly from RingEdgeRecord: {row}")
        if row["inst_t_row_count"] != 0:
            failures.append(f"row must not allocate inst_t rows: {row}")
        if row["vendor_row_count"] != 0:
            failures.append(f"row must not allocate vendor rows: {row}")
        if row["raw_inst_t_byte_count"] != 0:
            failures.append(f"row must not emit raw inst_t bytes: {row}")
        if row["inst_t_bytes_emitted"] is not False:
            failures.append(f"row must not emit inst_t bytes: {row}")
        if row["decode_roundtrip_claim"] is not False:
            failures.append(f"row must not claim decode roundtrip: {row}")

    if failures:
        print("stream compiler log10max ring update layout candidate check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max ring update layout candidate check OK")
    print(f"template_op_count={summary['template_op_count']}")
    print(f"row_candidate_count={summary['row_candidate_count']}")
    print(f"blocker_ids={summary['blocker_ids']}")


if __name__ == "__main__":
    main()
