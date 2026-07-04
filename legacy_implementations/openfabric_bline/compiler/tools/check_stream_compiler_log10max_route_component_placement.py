#!/usr/bin/env python3
"""Check Phase-4B log10max route component placement candidates."""

from __future__ import annotations

from collections import defaultdict

from gpdpu_compiler.core.program_bin import MAX_INST_AMOUNT_PER_PE
from gpdpu_compiler.core.program_legacy_inst import INST_RECORD_SIZE_BYTES
from gpdpu_compiler.core.stream_compiler.log10max_route_component_placement import (
    LOG10MAX_ROUTE_COMPONENT_OVERWRITE_CHECK_SCOPED,
    LOG10MAX_ROUTE_FULL_LAYOUT_EPOCH_NOT_FROZEN,
    ROUTE_COMPONENT_INTEGRATION_STATUS,
    ROUTE_COMPONENT_NAME,
    ROUTE_COMPONENT_PLACEMENT_STATUS,
    ROUTE_LAYOUT_EPOCH,
    ROUTE_RESERVED_ROW_POLICY_ID,
    build_log10max_route_component_placement_report,
    summarize_log10max_route_component_placement_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_route_row_bytes import (
    LOG10MAX_ROUTE_COMPONENT_INTEGRATION_MISSING,
)


EXPECTED_PHASE_COUNTS = {
    "col_broadcast": 12,
    "col_reduce": 12,
    "row_broadcast": 48,
    "row_reduce": 48,
}


def main() -> None:
    report = build_log10max_route_component_placement_report()
    summary = summarize_log10max_route_component_placement_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["placement_count"] != 120:
        failures.append(f"expected 120 route placement records: {summary}")
    if summary["lane_group_completion_count"] != 30:
        failures.append(f"expected 30 lane group completions: {summary}")
    if summary["phase_counts"] != EXPECTED_PHASE_COUNTS:
        failures.append(f"unexpected phase counts: {summary}")
    if summary["placement_status_counts"] != {ROUTE_COMPONENT_PLACEMENT_STATUS: 120}:
        failures.append(f"unexpected placement status: {summary}")
    if summary["component_integration_status_counts"] != {
        ROUTE_COMPONENT_INTEGRATION_STATUS: 120
    }:
        failures.append(f"must not claim component integration: {summary}")
    if summary["micc_coherence_status_counts"] != {"not_integrated": 120}:
        failures.append(f"must not claim MICC coherence: {summary}")
    if summary["payload_manifest_status_counts"] != {
        "route_candidate_manifest_bound": 120
    }:
        failures.append(f"unexpected manifest status: {summary}")
    if summary["lane_group_completion_status_counts"] != {"bound": 30}:
        failures.append(f"lane group completion must be bound: {summary}")
    if summary["duplicate_component_byte_offset_count"] != 0:
        failures.append(f"component offsets must be unique: {summary}")
    if summary["overwritten_row_count"] != 0:
        failures.append(f"route placement must not overwrite rows: {summary}")
    if summary["runtime_ready_claim_count"] != 0:
        failures.append(f"placement must not claim runtime_ready: {summary}")
    if summary["uploadable_claim_count"] != 0:
        failures.append(f"placement must not claim uploadable: {summary}")
    if summary["route_component_integrated_claim"] is not False:
        failures.append("route component must not be integrated in Phase 4B")
    for blocker in (
        LOG10MAX_ROUTE_COMPONENT_INTEGRATION_MISSING,
        LOG10MAX_ROUTE_FULL_LAYOUT_EPOCH_NOT_FROZEN,
        LOG10MAX_ROUTE_COMPONENT_OVERWRITE_CHECK_SCOPED,
    ):
        if blocker not in summary["blocker_ids"]:
            failures.append(f"expected blocker {blocker}: {summary}")
    if summary["runtime_ready"] is not False or summary["uploadable"] is not False:
        failures.append(f"readiness claims forbidden: {summary}")
    if summary["layout_epoch"] != ROUTE_LAYOUT_EPOCH:
        failures.append(f"unexpected layout epoch: {summary}")
    if not summary["layout_plan_sha256"]:
        failures.append(f"layout hash missing: {summary}")
    if summary["inst_per_pe"] != MAX_INST_AMOUNT_PER_PE:
        failures.append(f"unexpected inst_per_pe: {summary}")
    if plan["payload_manifest_entries"] != []:
        failures.append("route placement must not enter operator payload manifest")

    offsets: set[int] = set()
    local_pcs_by_pe: dict[str, list[int]] = defaultdict(list)
    rows_by_edge: dict[str, list[dict[str, object]]] = defaultdict(list)
    for placement in plan["placements"]:
        if placement["component_name"] != ROUTE_COMPONENT_NAME:
            failures.append(f"unexpected component name: {placement}")
        if placement["record_size_bytes"] != INST_RECORD_SIZE_BYTES:
            failures.append(f"unexpected record size: {placement}")
        if placement["layout_epoch"] != ROUTE_LAYOUT_EPOCH:
            failures.append(f"bad layout epoch: {placement}")
        if placement["layout_plan_sha256"] != summary["layout_plan_sha256"]:
            failures.append(f"layout hash mismatch: {placement}")
        if placement["reserved_row_policy_id"] != ROUTE_RESERVED_ROW_POLICY_ID:
            failures.append(f"reserved policy missing: {placement}")
        if placement["overwrite_policy"] != "reserved_slot_only":
            failures.append(f"bad overwrite policy: {placement}")
        if placement["overwritten_row_ids"] != []:
            failures.append(f"must not overwrite rows: {placement}")
        if placement["component_integration_scope"] != "route_rows_only":
            failures.append(f"bad integration scope: {placement}")
        if placement["component_integration_status"] != ROUTE_COMPONENT_INTEGRATION_STATUS:
            failures.append(f"bad integration status: {placement}")
        if placement["micc_coherence_scope"] != "route_rows_only":
            failures.append(f"bad MICC scope: {placement}")
        if placement["micc_coherence_status"] != "not_integrated":
            failures.append(f"bad MICC status: {placement}")
        if placement["payload_manifest_status"] != "route_candidate_manifest_bound":
            failures.append(f"bad payload manifest status: {placement}")
        if placement["runtime_ready"] is not False or placement["uploadable"] is not False:
            failures.append(f"readiness claims forbidden: {placement}")
        if placement["blocker_ids"] != [
            LOG10MAX_ROUTE_FULL_LAYOUT_EPOCH_NOT_FROZEN,
            LOG10MAX_ROUTE_COMPONENT_OVERWRITE_CHECK_SCOPED,
            LOG10MAX_ROUTE_COMPONENT_INTEGRATION_MISSING,
        ]:
            failures.append(f"unexpected per-row blockers: {placement}")

        pe_index = int(placement["pe_index"])
        pe_local_pc = int(placement["pe_local_pc"])
        component_row_index = int(placement["component_row_index"])
        component_byte_offset = int(placement["component_byte_offset"])
        if not (0 <= pe_local_pc < MAX_INST_AMOUNT_PER_PE):
            failures.append(f"PE-local PC outside capacity: {placement}")
        expected_row_index = pe_index * MAX_INST_AMOUNT_PER_PE + pe_local_pc
        if component_row_index != expected_row_index:
            failures.append(f"component row index formula mismatch: {placement}")
        expected_offset = component_row_index * INST_RECORD_SIZE_BYTES
        if component_byte_offset != expected_offset:
            failures.append(f"component byte offset formula mismatch: {placement}")
        if component_byte_offset in offsets:
            failures.append(f"duplicate component offset: {placement}")
        offsets.add(component_byte_offset)
        local_pcs_by_pe[str(placement["source_pe"])].append(pe_local_pc)
        rows_by_edge[str(placement["logical_route_edge_id"])].append(placement)

    for pe, local_pcs in local_pcs_by_pe.items():
        if len(local_pcs) != len(set(local_pcs)):
            failures.append(f"{pe} has duplicate local PCs: {sorted(local_pcs)}")

    completions_by_edge = {
        str(completion["logical_route_edge_id"]): completion
        for completion in plan["lane_group_completions"]
    }
    if len(completions_by_edge) != 30:
        failures.append("lane group completion ids must cover 30 route edges")
    for edge_id, rows in rows_by_edge.items():
        lanes = sorted(
            int(row["physical_row_plan_id"].rsplit("copy_lane", 1)[1])
            for row in rows
        )
        if lanes != [0, 1, 2, 3]:
            failures.append(f"{edge_id} must have lanes 0..3 exactly once: {lanes}")
        completion = completions_by_edge.get(edge_id)
        if completion is None:
            failures.append(f"missing lane completion for {edge_id}")
            continue
        if int(completion["lane_count"]) != 4:
            failures.append(f"{edge_id} completion must cover four lanes: {completion}")
        if int(completion["completion_lane_index"]) != 3:
            failures.append(f"{edge_id} completion lane must be lane 3: {completion}")
        if int(completion["completion_flow_ack_value"]) != 1:
            failures.append(f"{edge_id} completion must use flow_ack=1: {completion}")
        if completion["completion_status"] != "bound":
            failures.append(f"{edge_id} completion must be bound: {completion}")
        if not str(completion["receiver_ready_value_id"]).startswith(
            "globalmax_route_ready:"
        ):
            failures.append(f"{edge_id} ready token missing: {completion}")
        if completion["blocker_ids"] != []:
            failures.append(f"{edge_id} completion should have no blocker: {completion}")

    if failures:
        print("stream compiler log10max route component placement check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max route component placement check OK")
    print(f"placement_count={summary['placement_count']}")
    print(f"phase_counts={summary['phase_counts']}")
    print(f"lane_group_completion_count={summary['lane_group_completion_count']}")
    print(f"blocker_ids={summary['blocker_ids']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"uploadable={summary['uploadable']}")


if __name__ == "__main__":
    main()
