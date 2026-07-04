#!/usr/bin/env python3
"""Focused check for the log10max collective strategy report."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gpdpu_compiler.core.stream_compiler.log10max_collective_strategy import (
    build_current_log10max_plan,
    build_log10max_capacity_proof_report,
    summarize_log10max_capacity_proof_report,
)


EXPECTED_SUMMARY = {
    "recommended_delivery_strategy": "ring_spmd_row_then_col",
    "recommended_delivery_customer_label": "spmd_ring_materialized_reduce",
    "selected_delivery_strategy": "ring_spmd_row_then_col",
    "selected_delivery_customer_label": "spmd_ring_materialized_reduce",
    "internal_waiver_strategy": "redundant_spmd_recompute",
    "internal_waiver_customer_label": "internal_redundant_recompute",
    "delivery_status": "delivery_selected_blocked_on_route_binding",
    "selected_strategy": "ring_spmd_row_then_col",
    "selected_customer_label": "spmd_ring_materialized_reduce",
    "selection_status": "delivery_selected_blocked_on_route_binding",
    "input_shape": [64, 512],
    "output_shape": [64, 512],
    "dtype": "fp32",
    "participant_count": 16,
    "scratch_bytes": 4,
    "runtime_launch_count": 2,
    "runtime_launch_supported": False,
    "runtime_ready": False,
    "delivery_blocked": True,
    "collective_strategy": "ring_spmd_row_then_col",
    "customer_collective_label": "spmd_ring_materialized_reduce",
    "direct_route_reduce_broadcast": "deferred",
    "task_axis": 1,
    "runtime_ordering_domain": "single_task_group",
    "cross_task_one_app_ring": "forbidden",
    "cross_task_visibility_claim": False,
    "strategy_status_counts": {
        "blocked": 1,
        "delivery_selected_blocked_on_route_binding": 1,
        "internal_waiver_available": 1,
        "ready": 1,
    },
    "selected_strategy_blockers": [
        "route_role_globalmax_unproven",
        "ring_edge_template_missing",
        "ring_phase_order_missing",
        "global_max_distribution_missing",
        "consumer_global_max_binding_missing",
        "consumer_depends_on_global_ready_missing",
        "route_path_proof_missing",
        "dtype_update_op_mismatch",
        "symbolic_global_max_reaches_postprocess",
    ],
    "delivery_blocker_count": 9,
    "pe00_plan_status": "closed",
    "pe00_open_requirement_count": 0,
}

EXPECTED_REMAINING_BLOCKER_IDS = [
    "producer_pe00_physical_store_row_bytes_missing",
    "pe00_fmax_combine_order_row_bytes_missing",
    "consumer_physical_readback_row_bytes_missing",
    "runtime_subtask_order_proof_missing",
    "receiver_global_scalar_binding_proof_missing",
]

EXPECTED_REMAINING_BLOCKER_REQUIREMENTS = {
    "producer_pe00_physical_store_row_bytes_missing": (
        "producer_pe00_physical_store"
    ),
    "pe00_fmax_combine_order_row_bytes_missing": "pe00_fmax_combine_order",
    "consumer_physical_readback_row_bytes_missing": "consumer_physical_readback",
    "runtime_subtask_order_proof_missing": "runtime_subtask_order",
    "receiver_global_scalar_binding_proof_missing": "receiver_binding",
}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the full report JSON after validation",
    )
    args = parser.parse_args()

    failures: list[str] = []
    full_plan = build_current_log10max_plan()
    report = build_log10max_capacity_proof_report(full_plan)
    summary = summarize_log10max_capacity_proof_report(report)
    plan_view = report.to_plan()

    if summary != EXPECTED_SUMMARY:
        failures.append(
            "unexpected log10max collective summary: "
            f"expected {EXPECTED_SUMMARY}, got {summary}"
        )

    evaluations = {
        item["strategy"]: item for item in plan_view["strategy_evaluations"]
    }
    direct = evaluations.get("direct_route_reduce_broadcast")
    if direct is None:
        failures.append("missing direct_route_reduce_broadcast evaluation")
    elif direct["customer_label"] != "physical_route_allreduce":
        failures.append(f"direct route label drifted: {direct}")
    elif "direct_route_evidence_missing" not in direct["blockers"]:
        failures.append(f"direct route must remain blocked by route evidence: {direct}")

    pe00 = evaluations.get("pe00_aggregate_materialize")
    if pe00 is None:
        failures.append("missing pe00_aggregate_materialize evaluation")
    elif pe00["customer_label"] != "pe00_materialized_scalar":
        failures.append(f"PE00 materialized scalar label drifted: {pe00}")
    elif "scratch_address_materialization" in pe00["blockers"]:
        failures.append(f"PE00 scratch address should be closed now: {pe00}")
    elif pe00["blockers"]:
        failures.append(f"PE00 requirements should be closed by contracts: {pe00}")

    ring = evaluations.get("ring_spmd_row_then_col")
    if ring is None:
        failures.append("missing ring_spmd_row_then_col evaluation")
    elif ring["customer_label"] != "spmd_ring_materialized_reduce":
        failures.append(f"ring customer label drifted: {ring}")
    elif ring["status"] != "delivery_selected_blocked_on_route_binding":
        failures.append(f"ring must be selected but blocked on binding: {ring}")
    elif "route_role_globalmax_unproven" not in ring["blockers"]:
        failures.append(f"ring must expose GlobalMax route role blocker: {ring}")

    redundant = evaluations.get("redundant_spmd_recompute")
    if redundant is None:
        failures.append("missing redundant_spmd_recompute evaluation")
    elif redundant["customer_label"] != "internal_redundant_recompute":
        failures.append(f"redundant label drifted: {redundant}")
    elif redundant["status"] != "internal_waiver_available":
        failures.append(f"redundant must remain internal waiver only: {redundant}")

    if plan_view["recommended_delivery_strategy"] != "ring_spmd_row_then_col":
        failures.append(f"ring must be first delivery work item: {plan_view}")
    if plan_view["selected_delivery_strategy"] != "ring_spmd_row_then_col":
        failures.append(f"delivery should select ring strategy: {plan_view}")
    if plan_view["direct_route_reduce_broadcast"] != "deferred":
        failures.append(f"direct route must be deferred: {plan_view}")
    if plan_view["task_axis"] != 1:
        failures.append(f"log10max ring profile must force task_axis=1: {plan_view}")
    if plan_view["runtime_ordering_domain"] != "single_task_group":
        failures.append(f"unexpected ring ordering domain: {plan_view}")
    if plan_view["cross_task_one_app_ring"] != "forbidden":
        failures.append(f"cross-task one-app ring must be forbidden: {plan_view}")
    if plan_view["internal_waiver_strategy"] != "redundant_spmd_recompute":
        failures.append(f"redundant waiver strategy missing: {plan_view}")
    if plan_view["runtime_ready"] is not False:
        failures.append(f"log10max report must remain runtime_ready=false: {plan_view}")
    if plan_view["delivery_blocked"] is not True:
        failures.append(f"log10max delivery must stay blocked until ring binds: {plan_view}")

    pe00_plan = plan_view["pe00_materialized_scalar_plan"]
    if pe00_plan["status"] != "closed":
        failures.append(f"PE00 plan must be closed by contracts: {pe00_plan}")
    if pe00_plan["runtime_ready"] is not False:
        failures.append(f"PE00 plan must not claim runtime ready: {pe00_plan}")
    if pe00_plan["delivery_blocked"] is not False:
        failures.append(f"PE00 plan should not be delivery blocked: {pe00_plan}")
    expected_open_requirements: list[str] = []
    if pe00_plan["open_requirement_ids"] != expected_open_requirements:
        failures.append(
            "unexpected PE00 open requirements: "
            f"expected {expected_open_requirements}, got {pe00_plan['open_requirement_ids']}"
        )
    requirement_status = {
        item["requirement_id"]: item["status"]
        for item in pe00_plan["requirements"]
    }
    expected_requirement_status = {
        "scratch_region_shape": "available",
        "source_scratch_allocation_contract": "available",
        "scratch_address_materialization": "available",
        "producer_pe00_store_action": "available",
        "producer_pe00_physical_store": "available",
        "consumer_broadcast_load_actions": "available",
        "consumer_physical_readback": "available",
        "materialize_before_readback_dependency": "available",
        "runtime_subtask_order": "available",
        "receiver_binding": "available",
        "pe00_fmax_combine_order": "available",
    }
    if requirement_status != expected_requirement_status:
        failures.append(
            "unexpected PE00 requirement status: "
            f"expected {expected_requirement_status}, got {requirement_status}"
        )
    if (
        bool(pe00_plan["open_requirement_ids"])
        and plan_view["selected_delivery_strategy"] is not None
    ):
        failures.append(
            "selected_delivery_strategy must stay None until all PE00 "
            f"requirements are closed: {pe00_plan}"
        )
    requirements_by_id = {
        item["requirement_id"]: item for item in pe00_plan["requirements"]
    }
    scratch_address = requirements_by_id["scratch_address_materialization"]
    if scratch_address["status"] != "available":
        failures.append(
            "current log10max source must close report-only scratch address "
            "materialization: "
            f"{scratch_address}"
        )
    if scratch_address["missing_reason"] is not None:
        failures.append(f"closed scratch address should not have missing reason: {scratch_address}")
    next_owners = {
        item["requirement_id"]: item["next_owner"]
        for item in pe00_plan["requirements"]
        if item["status"] != "available"
    }
    expected_next_owners: dict[str, object] = {}
    if next_owners != expected_next_owners:
        failures.append(
            "unexpected PE00 next owners: "
            f"expected {expected_next_owners}, got {next_owners}"
        )
    contract = pe00_plan["scratch_allocation_contract"]
    if contract["source_id"] != "app_storage:global_max:dtensor_0003":
        failures.append(f"unexpected scratch contract source id: {contract}")
    if contract["contract_level"] != "source_b_line_scratch_allocation":
        failures.append(f"unexpected scratch contract level: {contract}")
    if contract["address_space"] != "sram":
        failures.append(f"unexpected scratch contract address space: {contract}")
    if contract["size_bytes"] != 4 or contract["dtype"] != "fp32":
        failures.append(f"unexpected scratch contract size/dtype: {contract}")
    if contract["owner_processor"] != "processor_0_0":
        failures.append(f"unexpected scratch contract owner: {contract}")
    if contract["consumer_count"] != 16:
        failures.append(f"unexpected scratch contract consumers: {contract}")
    if contract["address_materialization_status"] != (
        "compiler_allocated_offset_candidate_available"
    ):
        failures.append(f"scratch address candidate status drifted: {contract}")
    candidate = pe00_plan["scratch_address_candidate"]
    if candidate["source_id"] != "app_storage:global_max:dtensor_0003":
        failures.append(f"unexpected PE00 scratch address candidate source: {candidate}")
    if candidate["logical_value_id"] != "dtensor_0003":
        failures.append(f"unexpected PE00 scratch address candidate value: {candidate}")
    if candidate["candidate_status"] != (
        "compiler_allocated_address_candidate_available"
    ):
        failures.append(
            "PE00 scratch address candidate must expose compiler allocation: "
            f"{candidate}"
        )
    if candidate["scratch_address_requirement_reason"] != (
        "compiler_allocated_offset_candidate_available"
    ):
        failures.append(
            "PE00 scratch address requirement reason must reflect allocation: "
            f"{candidate}"
        )
    if candidate["region_status"] != "compiler_allocated_region_candidate_available":
        failures.append(f"expected compiler allocated region candidate: {candidate}")
    if candidate["offset_bytes"] != 0xA0000 or candidate["offset_status"] != "present":
        failures.append(f"PE00 candidate scratch offset drifted: {candidate}")
    if candidate["address_space"] != "sram" or candidate["address_space_status"] != "present":
        failures.append(f"PE00 candidate address space drifted: {candidate}")
    if candidate["instance_base_addr_source"] != "dfu3500_sram_byte_offset_to_legacy_base_word32":
        failures.append(f"PE00 base addr source drifted: {candidate}")
    if candidate["size_bytes"] != 4:
        failures.append(f"PE00 scratch candidate must expose 4B size: {candidate}")
    expected_candidate_region = {
        "region_id": "app_storage:global_max:dtensor_0003",
        "address_space": "sram",
        "offset_bytes": 0xA0000,
        "end_offset_bytes": 0xA0004,
        "size_bytes": 4,
    }
    if candidate["region"] != expected_candidate_region:
        failures.append(
            "PE00 scratch candidate region report drifted: "
            f"expected {expected_candidate_region}, got {candidate['region']}"
        )
    if candidate["address_source_owner"] != "source_scratch_allocation":
        failures.append(f"unexpected PE00 address source owner: {candidate}")
    if candidate["address_record_status"] != (
        "compiler_allocated_address_candidate_available"
    ):
        failures.append(f"unexpected PE00 address record status: {candidate}")
    app_storage_address_record = candidate["app_storage_address_record"]
    if app_storage_address_record is None:
        failures.append(f"missing PE00 app storage address record: {candidate}")
    else:
        expected_record = {
            "record_kind": "app_storage_address_record",
            "source_id": "app_storage:global_max:dtensor_0003",
            "source_id_kind": "app_storage_region",
            "logical_value_id": "dtensor_0003",
            "address_space": None,
            "region_id": "app_storage:global_max:dtensor_0003",
            "offset_bytes": None,
            "size_bytes": 4,
            "instance_base_addr_source": None,
            "status": "candidate_address_record_present_but_unverified",
        }
        for key, value in expected_record.items():
            if app_storage_address_record.get(key) != value:
                failures.append(
                    "unexpected PE00 app storage address record field "
                    f"{key}: {app_storage_address_record}"
                )
    schema = candidate["required_source_record_schema"]
    if schema["record_kind"] != "app_storage_address_record":
        failures.append(f"unexpected PE00 address schema kind: {schema}")
    if schema["source_id"] != "app_storage:global_max:dtensor_0003":
        failures.append(f"unexpected PE00 address schema source: {schema}")
    if schema["expected_size_bytes"] != 4:
        failures.append(f"unexpected PE00 address schema size: {schema}")
    required_schema_fields = set(schema["required_fields"])
    for field in {
        "source_id",
        "source_id_kind",
        "logical_value_id",
        "address_space",
        "region_id",
        "offset_bytes",
        "size_bytes",
        "instance_base_addr_source",
    }:
        if field not in required_schema_fields:
            failures.append(f"PE00 address schema missing required field {field}: {schema}")
    for field in {
        "address_space",
        "offset_bytes",
        "instance_base_addr_source",
    }:
        if field not in schema["must_not_invent_or_default"]:
            failures.append(f"PE00 address schema must fail closed on {field}: {schema}")
    searched_sources = {
        item["source_name"]: item for item in candidate["searched_sources"]
    }
    expected_search_status = {
        "app_plan_materialize_ops": "storage_reference_present_no_address_record",
        "processor_tile_program_app_storage_regions": (
            "region_record_present_missing_address_fields"
        ),
        "processor_tile_program_app_storage_address_records": (
            "candidate_address_record_present_but_unverified"
        ),
        "stream_compiler_log10max_source_scratch_allocation": (
            "compiler_allocated_offset_candidate_available"
        ),
        "processor_tile_program_app_storage_edges_actions": (
            "symbolic_storage_boundary_no_address_record"
        ),
        "runtime_package_assignment_storage_refs": (
            "storage_reference_present_no_address_schema"
        ),
        "stream_compiler_vendor_instance_base_addr": (
            "not_usable_for_log10max_app_storage_source"
        ),
    }
    if set(searched_sources) != set(expected_search_status):
        failures.append(
            "unexpected PE00 address searched sources: "
            f"expected {sorted(expected_search_status)}, got {sorted(searched_sources)}"
        )
    for source_name, status in expected_search_status.items():
        source = searched_sources.get(source_name)
        if source is None:
            continue
        if source["status"] != status:
            failures.append(
                f"unexpected PE00 search status for {source_name}: {source}"
            )
        if source_name == "stream_compiler_log10max_source_scratch_allocation":
            if source["missing_fields"]:
                failures.append(f"compiler allocation should have no missing fields: {source}")
            continue
        if source_name != "stream_compiler_vendor_instance_base_addr":
            for field in {
                "address_space",
                "offset_bytes",
                "instance_base_addr_source",
            }:
                if field not in source["missing_fields"]:
                    failures.append(
                        f"PE00 search source {source_name} must report missing "
                        f"{field}: {source}"
                    )
    tile_region_source = searched_sources.get(
        "processor_tile_program_app_storage_regions", {}
    )
    if tile_region_source.get("record", {}).get("storage_id") != (
        "app_storage:global_max:dtensor_0003"
    ):
        failures.append(f"tile app storage region source drifted: {tile_region_source}")
    tile_address_source = searched_sources.get(
        "processor_tile_program_app_storage_address_records", {}
    )
    if tile_address_source.get("record", {}).get("status") != (
        "candidate_address_record_present_but_unverified"
    ):
        failures.append(f"tile app storage address record drifted: {tile_address_source}")
    tile_action_source = searched_sources.get(
        "processor_tile_program_app_storage_edges_actions", {}
    )
    if tile_action_source.get("matching_action_count") != 17:
        failures.append(f"expected 17 symbolic storage actions: {tile_action_source}")
    runtime_source = searched_sources.get("runtime_package_assignment_storage_refs", {})
    if len(runtime_source.get("matching_packages", [])) != 2:
        failures.append(f"expected two runtime package refs: {runtime_source}")
    interface = pe00_plan["scalar_visibility_interface"]
    if interface["global_scalar_source_name"] != "mel_spec_clamp_min_log10_reduce_max":
        failures.append(f"unexpected scalar source interface: {interface}")
    if interface["delivery_source_id"] != "app_storage:global_max:dtensor_0003":
        failures.append(f"unexpected delivery source id: {interface}")
    if interface["scratch_slot"]["storage_id"] != "app_storage:global_max:dtensor_0003":
        failures.append(f"unexpected scratch slot interface: {interface}")
    if interface["scratch_slot"]["allocation_contract_id"] != contract["contract_id"]:
        failures.append(f"scratch slot must point at allocation contract: {interface}")
    if interface["scratch_slot"]["address_candidate_id"] != candidate["candidate_id"]:
        failures.append(f"scratch slot must point at address candidate: {interface}")
    if interface["load_route_consumer_contract"]["consumer_count"] != 16:
        failures.append(f"unexpected consumer contract: {interface}")
    if interface["scratch_slot"]["template_contract_status"] != "available":
        failures.append(f"PE00 template contract should be available: {interface}")
    if (
        interface["load_route_consumer_contract"]["receiver_binding_contract_status"]
        != "available"
    ):
        failures.append(f"receiver binding contract should be available: {interface}")
    if interface["load_route_consumer_contract"]["physical_route_allreduce"] is not False:
        failures.append(f"PE00 contract must not claim physical allreduce: {interface}")
    runtime_order = pe00_plan["runtime_order_contract"]
    if runtime_order["status"] != "available":
        failures.append(f"runtime order contract should be available: {runtime_order}")
    if runtime_order["runtime_runnable_claim"] is not False:
        failures.append(f"runtime order must not claim runnable: {runtime_order}")
    runtime_order_intent = runtime_order["micc_order_lowering_intent"]
    if runtime_order_intent["status"] != "micc_order_intent_available_rows_missing":
        failures.append(f"unexpected runtime MICC order intent: {runtime_order_intent}")
    if runtime_order_intent["row_bytes_claim"] is not False:
        failures.append(f"runtime MICC order intent must not claim bytes: {runtime_order_intent}")
    if runtime_order_intent["physical_route_allreduce"] is not False:
        failures.append(f"runtime MICC order intent must not claim allreduce: {runtime_order_intent}")
    if runtime_order_intent["ordered_subtask_slots"] != [
        "subtask_log10max_local_reduce",
        "subtask_log10max_global_max_pe00_combine",
        "subtask_log10max_global_max_pe00_store",
        "subtask_log10max_global_max_consumer_readback",
        "subtask_log10max_max_with_floor",
    ]:
        failures.append(f"unexpected runtime order slots: {runtime_order_intent}")
    runtime_order_proof = runtime_order["runtime_order_proof_plan"]
    if runtime_order_proof["status"] != "blocked_structured_runtime_proof_missing":
        failures.append(f"unexpected runtime order proof: {runtime_order_proof}")
    if runtime_order_proof["row_bytes_claim"] is not False:
        failures.append(f"runtime proof must not claim bytes: {runtime_order_proof}")
    if runtime_order_proof["physical_route_allreduce"] is not False:
        failures.append(f"runtime proof must not claim allreduce: {runtime_order_proof}")
    if "decoded_micc_roundtrip_order" not in runtime_order_proof["missing_fields"]:
        failures.append(f"runtime proof must name decoded MICC gap: {runtime_order_proof}")
    if (
        runtime_order_proof["expected_decoded_order"]
        != runtime_order_intent["ordered_subtask_slots"]
    ):
        failures.append(f"runtime proof expected order drifted: {runtime_order_proof}")
    if (
        runtime_order_proof["expected_successor_edges"]
        != runtime_order_intent["successor_edges"]
    ):
        failures.append(f"runtime proof successor edges drifted: {runtime_order_proof}")
    decoded_order_contract = runtime_order_proof["decoded_order_contract"]
    if (
        decoded_order_contract["status"]
        != "contract_available_decoded_rows_missing"
    ):
        failures.append(f"unexpected decoded MICC order contract: {decoded_order_contract}")
    if (
        decoded_order_contract["expected_decoded_order"]
        != runtime_order_intent["ordered_subtask_slots"]
    ):
        failures.append(f"decoded MICC contract order drifted: {decoded_order_contract}")
    stage_row_contract = decoded_order_contract["stage_row_id_contract"]
    if stage_row_contract["subtask_log10max_global_max_pe00_combine"][
        "expected_row_ids"
    ][0] != "global_max_tile.pe00_fmax_combine.00":
        failures.append(f"PE00 combine row id contract drifted: {stage_row_contract}")
    if stage_row_contract["subtask_log10max_global_max_pe00_store"][
        "expected_row_ids"
    ] != ["global_max_tile.pe00_scalar_store.00"]:
        failures.append(f"PE00 store row id contract drifted: {stage_row_contract}")
    if len(
        stage_row_contract[
            "subtask_log10max_global_max_consumer_readback"
        ]["expected_row_ids"]
    ) != 16:
        failures.append(f"PE00 readback row id contract drifted: {stage_row_contract}")
    if decoded_order_contract["row_bytes_claim"] is not False:
        failures.append(f"decoded MICC contract must not claim bytes: {decoded_order_contract}")
    runtime_trace_contract = runtime_order_proof["runtime_trace_contract"]
    if runtime_trace_contract["status"] != "contract_available_trace_missing":
        failures.append(f"unexpected runtime trace contract: {runtime_trace_contract}")
    if [
        "pe00_scalar_store_complete",
        "consumer_readback_complete",
    ] not in runtime_trace_contract["required_precedence_pairs"]:
        failures.append(f"runtime trace contract missing store/readback precedence: {runtime_trace_contract}")
    if runtime_trace_contract["runtime_runnable_claim"] is not False:
        failures.append(f"runtime trace contract must not claim runnable: {runtime_trace_contract}")
    for artifact in (
        "decoded_micc_order.json",
        "decoded_task_subtask_exeblock_rows.json",
        "runtime_start_wait_trace.json",
    ):
        if artifact not in runtime_order_proof["required_proof_artifacts"]:
            failures.append(f"runtime proof missing artifact {artifact}: {runtime_order_proof}")
    if "pe00_scalar_store_complete" not in runtime_order_proof[
        "required_runtime_trace_events"
    ]:
        failures.append(f"runtime proof must require store trace: {runtime_order_proof}")
    micc_request = runtime_order_proof["micc_materialization_request"]
    if micc_request["status"] != "materialization_request_available_rows_missing":
        failures.append(f"unexpected MICC materialization request: {micc_request}")
    if micc_request["row_bytes_claim"] is not False:
        failures.append(f"MICC materialization request must not claim bytes: {micc_request}")
    if micc_request["physical_route_allreduce"] is not False:
        failures.append(f"MICC materialization request must not claim allreduce: {micc_request}")
    if micc_request["expected_struct_rows"] != {
        "task_conf_info_t": 1,
        "sub_task_conf_info_t": 5,
        "exeBlock_conf_info_t": 5,
    }:
        failures.append(f"unexpected MICC expected row counts: {micc_request}")
    if micc_request["stage_row_id_contract"] != stage_row_contract:
        failures.append(f"MICC request must carry row id contract: {micc_request}")
    if micc_request["decoded_order_contract_artifact"] != "decoded_micc_order.json":
        failures.append(f"MICC request decoded contract artifact drifted: {micc_request}")
    if micc_request["runtime_trace_contract_artifact"] != "runtime_start_wait_trace.json":
        failures.append(f"MICC request runtime trace artifact drifted: {micc_request}")
    for artifact in (
        "pe00_micc_task_conf_info_rows.bin",
        "pe00_micc_sub_task_conf_info_rows.bin",
        "pe00_micc_exeBlock_conf_info_rows.bin",
        "decoded_micc_order.json",
        "decoded_task_subtask_exeblock_rows.json",
        "runtime_start_wait_trace.json",
    ):
        if artifact not in micc_request["required_output_artifacts"]:
            failures.append(f"MICC request missing artifact {artifact}: {micc_request}")
    runtime_order_proof_blockers = [
        item["blocker_id"] for item in runtime_order_proof["proof_blockers"]
    ]
    if runtime_order_proof_blockers != [
        "runtime_subtask_order_proof_missing",
        "micc_successor_wait_row_bytes_missing",
    ]:
        failures.append(f"unexpected runtime proof blockers: {runtime_order_proof}")
    micc_intent = pe00_plan["micc_order_lowering_intent"]
    if micc_intent["status"] != "micc_lowering_intent_available_rows_missing":
        failures.append(f"unexpected MICC lowering intent: {micc_intent}")
    if micc_intent["row_bytes_claim"] is not False:
        failures.append(f"MICC lowering intent must not claim row bytes: {micc_intent}")
    if [item["struct_name"] for item in micc_intent["target_structs"]] != [
        "task_conf_info_t",
        "sub_task_conf_info_t",
        "exeBlock_conf_info_t",
    ]:
        failures.append(f"unexpected MICC target structs: {micc_intent}")
    if (
        micc_intent["runtime_order_proof_plan"]["status"]
        != "blocked_structured_runtime_proof_missing"
    ):
        failures.append(f"MICC intent must carry runtime proof plan: {micc_intent}")
    if micc_intent["required_order_proof_artifacts"] != [
        "decoded_micc_order.json",
        "decoded_task_subtask_exeblock_rows.json",
        "runtime_start_wait_trace.json",
    ]:
        failures.append(f"MICC intent proof artifact contract drifted: {micc_intent}")
    if micc_intent["micc_materialization_request"] != micc_request:
        failures.append(f"MICC intent must carry request from proof plan: {micc_intent}")
    if micc_intent["decoded_order_contract"] != decoded_order_contract:
        failures.append(f"MICC intent must carry decoded order contract: {micc_intent}")
    if micc_intent["runtime_trace_contract"] != runtime_trace_contract:
        failures.append(f"MICC intent must carry runtime trace contract: {micc_intent}")
    if micc_intent["stage_row_id_contract"] != stage_row_contract:
        failures.append(f"MICC intent row id contract drifted: {micc_intent}")
    required_struct_fields = {
        "task_conf_info_t": "active_subtask_indices",
        "sub_task_conf_info_t": "successor_subtask_index",
        "exeBlock_conf_info_t": "dependency_or_wait_flags",
    }
    for target_struct in micc_intent["target_structs"]:
        required_field = required_struct_fields[target_struct["struct_name"]]
        if required_field not in target_struct["required_fields"]:
            failures.append(f"MICC struct proof missing {required_field}: {target_struct}")
        if "decoded_field_contract" not in target_struct:
            failures.append(f"MICC struct missing decoded field contract: {target_struct}")
        elif (
            target_struct["decoded_field_contract"].get("stage_row_id_contract")
            != stage_row_contract
        ):
            failures.append(f"MICC struct row id contract drifted: {target_struct}")
        if not target_struct.get("required_proof_artifacts"):
            failures.append(f"MICC struct missing proof artifact names: {target_struct}")
    receiver_binding = pe00_plan["receiver_binding_contract"]
    if receiver_binding["status"] != "available":
        failures.append(f"receiver binding contract should be available: {receiver_binding}")
    if receiver_binding["receiver_owned_destination_binding"] is not True:
        failures.append(f"receiver binding must be receiver-owned: {receiver_binding}")
    if receiver_binding["physical_route_allreduce"] is not False:
        failures.append(f"receiver binding must not claim physical allreduce: {receiver_binding}")
    receiver_intent = receiver_binding["vendor_operand_binding_intent"]
    if receiver_intent["status"] != "operand_binding_intent_available_proof_missing":
        failures.append(f"unexpected receiver operand intent: {receiver_intent}")
    if receiver_intent["row_bytes_claim"] is not False:
        failures.append(f"receiver operand intent must not claim row bytes: {receiver_intent}")
    if receiver_intent["consumer_count"] != 16:
        failures.append(f"receiver operand intent consumer count drifted: {receiver_intent}")
    receiver_proof = receiver_binding["receiver_binding_proof_plan"]
    if receiver_proof["status"] != (
        "blocked_synthetic_receiver_operand_link_available_"
        "active_decode_roundtrip_missing"
    ):
        failures.append(f"unexpected receiver proof: {receiver_proof}")
    if receiver_proof["row_bytes_claim"] is not False:
        failures.append(f"receiver proof must not claim bytes: {receiver_proof}")
    if receiver_proof["physical_route_allreduce"] is not False:
        failures.append(f"receiver proof must not claim allreduce: {receiver_proof}")
    if (
        "active_per_consumer_vendor_operand_indices"
        not in receiver_proof["missing_fields"]
    ):
        failures.append(f"receiver proof must name operand index gap: {receiver_proof}")
    if len(receiver_proof["per_consumer_binding_contract"]) != 16:
        failures.append(f"receiver proof must bind 16 consumers: {receiver_proof}")
    if len(receiver_proof["per_consumer_roundtrip_recipe"]) != 16:
        failures.append(f"receiver proof must carry 16 roundtrip recipes: {receiver_proof}")
    scalar_visibility_matrix = receiver_proof["scalar_visibility_proof_matrix"]
    if len(scalar_visibility_matrix) != 16:
        failures.append(
            f"receiver proof must carry 16 scalar visibility matrix rows: {receiver_proof}"
        )
    for index, matrix_row in enumerate(scalar_visibility_matrix):
        if matrix_row["readback_row_id"] != f"global_max_tile.consumer_readback.{index:02d}":
            failures.append(f"scalar visibility matrix row id drifted: {matrix_row}")
        if matrix_row["producer_fiber_op"] != "global_max_tile":
            failures.append(f"scalar visibility matrix producer drifted: {matrix_row}")
        if matrix_row["consumer_fiber_op"] != "max_with_floor_tile":
            failures.append(f"scalar visibility matrix consumer drifted: {matrix_row}")
        if matrix_row["receiver_destination_operand"] != (
            "receiver_owned_global_max_scalar_operand"
        ):
            failures.append(f"scalar visibility matrix destination drifted: {matrix_row}")
        if matrix_row["proof_status"] != (
            "blocked_until_readback_decode_and_operand_link_roundtrip"
        ):
            failures.append(f"scalar visibility matrix must remain blocked: {matrix_row}")
        if matrix_row["row_bytes_claim"] is not False:
            failures.append(f"scalar visibility matrix must not claim bytes: {matrix_row}")
        if matrix_row["physical_route_allreduce"] is not False:
            failures.append(f"scalar visibility matrix must not claim allreduce: {matrix_row}")
    synthetic_link_matrix = receiver_proof["synthetic_receiver_operand_link_matrix"]
    if len(synthetic_link_matrix) != 16:
        failures.append(f"receiver synthetic link matrix should cover 16 consumers: {receiver_proof}")
    if receiver_intent["synthetic_receiver_operand_link_matrix"] != synthetic_link_matrix:
        failures.append(f"receiver intent synthetic matrix drifted: {receiver_intent}")
    for index, link_row in enumerate(synthetic_link_matrix):
        if link_row["readback_row_id"] != f"global_max_tile.consumer_readback.{index:02d}":
            failures.append(f"receiver synthetic link row id drifted: {link_row}")
        if link_row["synthetic_decoded_destination_operand_index"] != 512 + index:
            failures.append(f"receiver synthetic destination index drifted: {link_row}")
        if link_row["consumer_fiber_op"] != "max_with_floor_tile":
            failures.append(f"receiver synthetic link must feed max_with_floor_tile: {link_row}")
        if link_row["status"] != (
            "synthetic_readback_destination_operand_link_available_"
            "active_decode_roundtrip_missing"
        ):
            failures.append(f"receiver synthetic link status drifted: {link_row}")
        if link_row["synthetic_decode_roundtrip_claim"] is not True:
            failures.append(f"receiver synthetic link should claim only synthetic decode: {link_row}")
        if link_row["active_operand_decode_claim"] is not False:
            failures.append(f"receiver synthetic link must not claim active decode: {link_row}")
        if link_row["row_bytes_claim"] is not False:
            failures.append(f"receiver synthetic link must not claim final bytes: {link_row}")
        if link_row["physical_route_allreduce"] is not False:
            failures.append(f"receiver synthetic link must not claim allreduce: {link_row}")
    first_roundtrip_recipe = receiver_proof["per_consumer_roundtrip_recipe"][0]
    if (
        first_roundtrip_recipe["expected_readback_row_id"]
        != "global_max_tile.consumer_readback.00"
    ):
        failures.append(f"receiver recipe row id drifted: {receiver_proof}")
    if first_roundtrip_recipe["consumer_fiber_op"] != "max_with_floor_tile":
        failures.append(f"receiver recipe must feed max_with_floor_tile: {receiver_proof}")
    if first_roundtrip_recipe["status"] != "blocked_missing_decoded_readback_row":
        failures.append(f"receiver recipe must remain blocked on decoded rows: {receiver_proof}")
    if (
        receiver_proof["roundtrip_contract"]["must_feed_consumer_fiber_op"]
        != "max_with_floor_tile"
    ):
        failures.append(f"receiver proof must feed max_with_floor_tile: {receiver_proof}")
    receiver_roundtrip = receiver_proof["receiver_roundtrip_request"]
    if receiver_roundtrip["status"] != "roundtrip_request_available_rows_missing":
        failures.append(f"unexpected receiver roundtrip request: {receiver_roundtrip}")
    if receiver_roundtrip["row_bytes_claim"] is not False:
        failures.append(f"receiver roundtrip request must not claim bytes: {receiver_roundtrip}")
    if receiver_roundtrip["physical_route_allreduce"] is not False:
        failures.append(f"receiver roundtrip request must not claim allreduce: {receiver_roundtrip}")
    if receiver_roundtrip["expected_readback_row_count"] != 16:
        failures.append(f"receiver roundtrip should expect 16 readback rows: {receiver_roundtrip}")
    if receiver_roundtrip["expected_readback_row_ids"][15] != (
        "global_max_tile.consumer_readback.15"
    ):
        failures.append(f"receiver roundtrip row ids drifted: {receiver_roundtrip}")
    if (
        receiver_roundtrip["required_destination_operand"]
        != "receiver_owned_global_max_scalar_operand"
    ):
        failures.append(f"receiver roundtrip destination drifted: {receiver_roundtrip}")
    if (
        receiver_roundtrip["per_consumer_roundtrip_recipe_artifact"]
        != "receiver_operand_roundtrip_recipe.json"
    ):
        failures.append(f"receiver roundtrip recipe artifact drifted: {receiver_roundtrip}")
    if receiver_roundtrip["scalar_visibility_proof_matrix"] != scalar_visibility_matrix:
        failures.append(f"receiver roundtrip matrix drifted: {receiver_roundtrip}")
    if (
        receiver_roundtrip["synthetic_receiver_operand_link_matrix"]
        != synthetic_link_matrix
    ):
        failures.append(f"receiver roundtrip synthetic link matrix drifted: {receiver_roundtrip}")
    for artifact in (
        "pe00_scalar_readback_decoded_rows.json",
        "receiver_operand_roundtrip_recipe.json",
        "receiver_operand_roundtrip.json",
        "max_with_floor_operand_link.json",
    ):
        if artifact not in receiver_proof["required_proof_artifacts"]:
            failures.append(f"receiver proof missing artifact {artifact}: {receiver_proof}")
        if artifact not in receiver_roundtrip["required_output_artifacts"]:
            failures.append(f"receiver roundtrip missing artifact {artifact}: {receiver_roundtrip}")
    receiver_proof_blockers = [
        item["blocker_id"] for item in receiver_proof["proof_blockers"]
    ]
    if receiver_proof_blockers != [
        "receiver_global_scalar_binding_proof_missing",
        "consumer_physical_readback_row_bytes_missing",
    ]:
        failures.append(f"unexpected receiver proof blockers: {receiver_proof}")
    template_contract = pe00_plan["global_scalar_template_contract"]
    if template_contract["status"] != "available":
        failures.append(f"global scalar template contract should be available: {template_contract}")
    if template_contract["strategy"] != "pe00_aggregate_materialize":
        failures.append(f"unexpected PE00 template strategy: {template_contract}")
    if template_contract["customer_label"] != "pe00_materialized_scalar":
        failures.append(f"unexpected PE00 customer label: {template_contract}")
    for key in (
        "producer_pe00_physical_store",
        "consumer_physical_readback",
        "pe00_fmax_combine_order",
    ):
        if template_contract[key]["status"] != "available":
            failures.append(f"PE00 template contract field {key} not available: {template_contract}")
        if template_contract[key]["row_bytes_claim"] is not False:
            failures.append(f"PE00 template field {key} must not claim row bytes: {template_contract}")
    if template_contract["physical_route_allreduce"] is not False:
        failures.append(f"PE00 template contract must not claim direct allreduce: {template_contract}")
    scalar_source = template_contract["scalar_visibility_source"]
    if scalar_source["complete"] is not True:
        failures.append(f"scalar visibility source should be complete: {scalar_source}")
    if scalar_source["runtime_runnable_claim"] is not False:
        failures.append(f"scalar source must not claim runtime runnable: {scalar_source}")
    vendor_row_plan = template_contract["vendor_row_lowering_plan"]
    if vendor_row_plan["status"] != (
        "vendor_row_intents_available_synthetic_decode_roundtrip_available_active_selector_missing"
    ):
        failures.append(f"unexpected PE00 vendor row plan: {vendor_row_plan}")
    if vendor_row_plan["row_bytes_claim"] is not False:
        failures.append(f"PE00 vendor row plan must not claim bytes: {vendor_row_plan}")
    if vendor_row_plan["physical_route_allreduce"] is not False:
        failures.append(f"PE00 vendor row plan must not claim allreduce: {vendor_row_plan}")
    if vendor_row_plan["entry_count"] != 3:
        failures.append(f"expected 3 PE00 vendor row intent entries: {vendor_row_plan}")
    row_byte_summary = vendor_row_plan["row_byte_proof_summary"]
    if row_byte_summary["status"] != (
        "blocked_synthetic_decode_roundtrip_available_active_selector_missing"
    ):
        failures.append(f"unexpected PE00 row-byte proof summary: {row_byte_summary}")
    if row_byte_summary["row_bytes_claim"] is not False:
        failures.append(f"PE00 row-byte summary must not claim bytes: {row_byte_summary}")
    if row_byte_summary["physical_route_allreduce"] is not False:
        failures.append(f"PE00 row-byte summary must not claim allreduce: {row_byte_summary}")
    if row_byte_summary["blocker_ids"] != [
        "pe00_fmax_combine_order_row_bytes_missing",
        "producer_pe00_physical_store_row_bytes_missing",
        "consumer_physical_readback_row_bytes_missing",
    ]:
        failures.append(f"unexpected PE00 row-byte summary blockers: {row_byte_summary}")
    if row_byte_summary["materialization_request_count"] != 3:
        failures.append(f"PE00 row-byte summary must carry 3 materialization requests: {row_byte_summary}")
    if row_byte_summary["expected_row_counts"] != {
        "pe00_fmax_combine_order": 15,
        "producer_pe00_physical_store": 1,
        "consumer_physical_readback": 16,
    }:
        failures.append(f"PE00 row-byte expected counts drifted: {row_byte_summary}")
    if row_byte_summary["row_candidate_recipe_status_counts"] != {
        "candidate_recipe_available_synthetic_decode_roundtrip_available_active_selector_missing": 3,
    }:
        failures.append(f"PE00 recipe status counts drifted: {row_byte_summary}")
    if sorted(row_byte_summary["row_candidate_recipe_artifacts"]) != [
        "consumer_physical_readback",
        "pe00_fmax_combine_order",
        "producer_pe00_physical_store",
    ]:
        failures.append(f"PE00 recipe artifact stages drifted: {row_byte_summary}")
    row_intent_ids = [entry["row_intent_id"] for entry in vendor_row_plan["entries"]]
    if row_intent_ids != [
        "global_max_tile.pe00_fmax_combine.rows",
        "global_max_tile.pe00_scalar_store.rows",
        "global_max_tile.consumer_scalar_readback.rows",
    ]:
        failures.append(f"unexpected PE00 vendor row intents: {vendor_row_plan}")
    for entry in vendor_row_plan["entries"]:
        if entry["row_bytes_claim"] is not False:
            failures.append(f"PE00 vendor row entry must not claim bytes: {entry}")
        if entry["physical_route_allreduce"] is not False:
            failures.append(f"PE00 vendor row entry must not claim allreduce: {entry}")
        proof_plan = entry["row_byte_proof_plan"]
        if proof_plan["status"] != (
            "blocked_synthetic_decode_roundtrip_available_active_selector_missing"
        ):
            failures.append(f"unexpected PE00 row proof plan: {proof_plan}")
        if proof_plan["row_bytes_claim"] is not False:
            failures.append(f"PE00 row proof plan must not claim bytes: {proof_plan}")
        if proof_plan["physical_route_allreduce"] is not False:
            failures.append(f"PE00 row proof plan must not claim allreduce: {proof_plan}")
        if not any("template_family_source" in item for item in proof_plan["missing_fields"]):
            failures.append(f"PE00 row proof plan must name active source gap: {proof_plan}")
        if not any("roundtrip" in item for item in proof_plan["missing_fields"]):
            failures.append(f"PE00 row proof plan must name roundtrip gap: {proof_plan}")
        request = proof_plan["materialization_request"]
        if request["status"] != (
            "materialization_request_available_synthetic_decode_roundtrip_available_"
            "active_selector_missing"
        ):
            failures.append(f"unexpected PE00 row materialization request: {request}")
        if request["row_bytes_claim"] is not False:
            failures.append(f"PE00 materialization request must not claim bytes: {request}")
        if request["physical_route_allreduce"] is not False:
            failures.append(f"PE00 materialization request must not claim allreduce: {request}")
        expected_counts = {
            "pe00_fmax_combine_order": 15,
            "producer_pe00_physical_store": 1,
            "consumer_physical_readback": 16,
        }
        if request["expected_row_count"] != expected_counts[proof_plan["stage"]]:
            failures.append(f"PE00 request row count drifted: {request}")
        if request["stage"] != proof_plan["stage"]:
            failures.append(f"PE00 request stage drifted: {request}")
        if request["selector_id"] != proof_plan["selector_requirements"]["selector_id"]:
            failures.append(f"PE00 request selector drifted: {request}")
        for artifact in request["required_output_artifacts"]:
            if artifact not in proof_plan["required_proof_artifacts"]:
                failures.append(f"PE00 request artifact missing from proof plan: {proof_plan}")
        recipe = proof_plan["row_candidate_recipe"]
        if recipe["status"] != (
            "candidate_recipe_available_synthetic_decode_roundtrip_available_"
            "active_selector_missing"
        ):
            failures.append(f"unexpected PE00 row candidate recipe: {recipe}")
        if recipe["row_bytes_claim"] is not False:
            failures.append(f"PE00 row recipe must not claim bytes: {recipe}")
        if recipe["physical_route_allreduce"] is not False:
            failures.append(f"PE00 row recipe must not claim allreduce: {recipe}")
        if recipe["expected_row_count"] != request["expected_row_count"]:
            failures.append(f"PE00 row recipe count drifted: {recipe}")
        if recipe["actual_candidate_row_count"] != request["expected_row_count"]:
            failures.append(f"PE00 row recipe candidate count drifted: {recipe}")
        if request["row_candidate_recipe_artifact"] != recipe["row_candidate_recipe_artifact"]:
            failures.append(f"PE00 request recipe artifact drifted: {request}")
        if request["row_candidate_recipe_status"] != recipe["status"]:
            failures.append(f"PE00 request recipe status drifted: {request}")
        materializer_contract = proof_plan["materializer_input_contract"]
        if (
            materializer_contract["status"]
            != (
                "row_recipe_available_synthetic_decode_roundtrip_available_"
                "active_selector_missing"
            )
        ):
            failures.append(f"unexpected PE00 materializer contract: {materializer_contract}")
        if materializer_contract != request["materializer_input_contract"]:
            failures.append(f"PE00 request materializer contract drifted: {request}")
        if materializer_contract != recipe["materializer_input_contract"]:
            failures.append(f"PE00 recipe materializer contract drifted: {recipe}")
        if materializer_contract["row_bytes_claim"] is not False:
            failures.append(f"PE00 materializer contract must not claim bytes: {materializer_contract}")
        if materializer_contract["expected_row_count"] != request["expected_row_count"]:
            failures.append(f"PE00 materializer row count drifted: {materializer_contract}")
        if len(materializer_contract["expected_row_ids"]) != request["expected_row_count"]:
            failures.append(f"PE00 materializer row ids drifted: {materializer_contract}")
        raw_request = materializer_contract["raw_row_candidate_request"]
        if raw_request != recipe["raw_row_candidate_request"]:
            failures.append(f"PE00 raw row request drifted between contract and recipe: {recipe}")
        if raw_request["status"] != (
            "candidate_request_available_synthetic_decode_roundtrip_available_"
            "active_selector_missing"
        ):
            failures.append(f"unexpected PE00 raw row request: {raw_request}")
        if raw_request["row_bytes_claim"] is not False:
            failures.append(f"PE00 raw row request must not claim bytes: {raw_request}")
        if raw_request["physical_route_allreduce"] is not False:
            failures.append(f"PE00 raw row request must not claim allreduce: {raw_request}")
        if raw_request["row_count"] != request["expected_row_count"]:
            failures.append(f"PE00 raw row request count drifted: {raw_request}")
        if raw_request["row_ids"] != materializer_contract["expected_row_ids"]:
            failures.append(f"PE00 raw row request ids drifted: {raw_request}")
        expected_mnemonic_by_stage = {
            "pe00_fmax_combine_order": "FMAX",
            "producer_pe00_physical_store": "STD",
            "consumer_physical_readback": "ILDMT",
        }
        expected_opcode_by_stage = {
            "pe00_fmax_combine_order": 0x027,
            "producer_pe00_physical_store": 0x080,
            "consumer_physical_readback": 0x107,
        }
        synthetic_summary = raw_request["synthetic_candidate_summary"]
        if synthetic_summary["row_count"] != request["expected_row_count"]:
            failures.append(f"PE00 synthetic summary count drifted: {raw_request}")
        if synthetic_summary["row_size_bytes"] != 304:
            failures.append(f"PE00 synthetic row size drifted: {raw_request}")
        if synthetic_summary["total_byte_count"] != request["expected_row_count"] * 304:
            failures.append(f"PE00 synthetic byte count drifted: {raw_request}")
        if synthetic_summary["exact_legacy_row_selector_claim"] is not False:
            failures.append(f"PE00 synthetic summary must not claim selector: {raw_request}")
        if synthetic_summary["active_runtime_family_claim"] is not False:
            failures.append(f"PE00 synthetic summary must not claim active family: {raw_request}")
        if synthetic_summary["row_bytes_claim"] is not False:
            failures.append(f"PE00 synthetic summary must not claim final bytes: {raw_request}")
        if synthetic_summary["physical_route_allreduce"] is not False:
            failures.append(f"PE00 synthetic summary must not claim allreduce: {raw_request}")
        if synthetic_summary["synthetic_decode_roundtrip_claim"] is not True:
            failures.append(f"PE00 synthetic summary should claim synthetic decode only: {raw_request}")
        evidence_request = raw_request["active_selector_evidence_request"]
        if evidence_request["status"] != "blocked_missing_active_vendor_or_aline_artifact":
            failures.append(f"PE00 active selector request status drifted: {evidence_request}")
        if evidence_request["synthetic_candidate_is_not_final_row_bytes"] is not True:
            failures.append(f"PE00 selector request must keep synthetic non-final: {evidence_request}")
        if evidence_request["row_bytes_claim"] is not False:
            failures.append(f"PE00 selector request must not claim final bytes: {evidence_request}")
        if not evidence_request["required_external_artifacts"]:
            failures.append(f"PE00 selector request must name external artifacts: {evidence_request}")
        for raw_input in raw_request["per_row_inputs"]:
            if raw_input["mnemonic"] != expected_mnemonic_by_stage[proof_plan["stage"]]:
                failures.append(f"PE00 raw row mnemonic drifted: {raw_input}")
            if raw_input["opcode"] != expected_opcode_by_stage[proof_plan["stage"]]:
                failures.append(f"PE00 raw row opcode drifted: {raw_input}")
            if raw_input["row_candidate_status"] != (
                "synthetic_source_backed_row_candidate_decode_roundtrip_available_active_selector_missing"
            ):
                failures.append(f"PE00 raw row status drifted: {raw_input}")
            synthetic = raw_input.get("synthetic_raw_inst_t_row_candidate")
            if not isinstance(synthetic, dict):
                failures.append(f"PE00 raw row missing synthetic candidate: {raw_input}")
                continue
            if synthetic["status"] != (
                "synthetic_source_backed_row_candidate_decode_roundtrip_available_active_selector_missing"
            ):
                failures.append(f"PE00 synthetic status drifted: {synthetic}")
            if synthetic["op_name"] != expected_mnemonic_by_stage[proof_plan["stage"]]:
                failures.append(f"PE00 synthetic op drifted: {synthetic}")
            if synthetic["opcode"] != expected_opcode_by_stage[proof_plan["stage"]]:
                failures.append(f"PE00 synthetic opcode drifted: {synthetic}")
            if synthetic["raw_inst_t_row_byte_count"] != 304:
                failures.append(f"PE00 synthetic row size drifted: {synthetic}")
            if len(synthetic["raw_inst_t_row_bytes_hex"]) != 608:
                failures.append(f"PE00 synthetic hex size drifted: {synthetic}")
            if len(synthetic["raw_inst_t_row_sha256"]) != 64:
                failures.append(f"PE00 synthetic row hash drifted: {synthetic}")
            if synthetic["raw_template_row_sha256"] != synthetic["raw_inst_t_row_sha256"]:
                failures.append(f"PE00 synthetic template hash drifted: {synthetic}")
            synthetic_decode = synthetic.get("synthetic_decode_roundtrip")
            if not isinstance(synthetic_decode, dict):
                failures.append(f"PE00 synthetic missing decode roundtrip: {synthetic}")
            elif synthetic_decode["status"] != (
                "synthetic_decode_roundtrip_available_active_selector_missing"
            ):
                failures.append(f"PE00 synthetic decode status drifted: {synthetic_decode}")
            elif synthetic_decode["synthetic_decode_roundtrip_claim"] is not True:
                failures.append(f"PE00 synthetic decode should claim synthetic roundtrip: {synthetic_decode}")
            elif synthetic_decode["row_bytes_claim"] is not False:
                failures.append(f"PE00 synthetic decode must not claim final bytes: {synthetic_decode}")
            elif synthetic_decode["active_template_family_claim"] is not False:
                failures.append(f"PE00 synthetic decode must not claim active family: {synthetic_decode}")
            elif synthetic_decode["operand_role_roundtrip"]["status"] != (
                "synthetic_operand_roles_decode_roundtrip_available"
            ):
                failures.append(f"PE00 operand role roundtrip drifted: {synthetic_decode}")
            if raw_input.get("synthetic_decode_roundtrip") != synthetic_decode:
                failures.append(f"PE00 raw input decode should mirror synthetic candidate: {raw_input}")
            if synthetic["synthetic_operand_index_address_roundtrip_claim"] is not True:
                failures.append(f"PE00 synthetic should close synthetic operand decode: {synthetic}")
            if synthetic["synthetic_decoded_row_roundtrip_claim"] is not True:
                failures.append(f"PE00 synthetic should close synthetic row decode: {synthetic}")
            if synthetic["exact_legacy_row_selector_claim"] is not False:
                failures.append(f"PE00 synthetic must not claim exact selector: {synthetic}")
            if synthetic["active_runtime_family_claim"] is not False:
                failures.append(f"PE00 synthetic must not claim active family: {synthetic}")
            if synthetic["operand_index_address_roundtrip_claim"] is not False:
                failures.append(f"PE00 synthetic must not claim operand roundtrip: {synthetic}")
            if synthetic["decoded_row_roundtrip_claim"] is not False:
                failures.append(f"PE00 synthetic must not claim decode roundtrip: {synthetic}")
            if synthetic["row_bytes_claim"] is not False:
                failures.append(f"PE00 synthetic must not claim final row bytes: {synthetic}")
            if synthetic["physical_route_allreduce"] is not False:
                failures.append(f"PE00 synthetic must not claim allreduce: {synthetic}")
            for field in (
                "legacy_template_row",
                "operand_indices",
                "raw_inst_t_row_bytes",
                "raw_template_row_sha256",
                "decoded_row_roundtrip",
            ):
                if field not in raw_input["required_selector_outputs"]:
                    failures.append(f"PE00 raw row input missing selector field {field}: {raw_input}")
        expected_narrowed_prefix = {
            "pe00_fmax_combine_order": "pe00_fmax_",
            "producer_pe00_physical_store": "pe00_scalar_store_",
            "consumer_physical_readback": "pe00_scalar_readback_",
        }
        if not raw_request["narrowed_blockers"]:
            failures.append(f"PE00 raw row request must expose narrowed blockers: {raw_request}")
        for blocker in raw_request["narrowed_blockers"]:
            if not str(blocker).startswith(expected_narrowed_prefix[proof_plan["stage"]]):
                failures.append(f"PE00 narrowed blocker prefix drifted: {raw_request}")
        first_candidate_row = recipe["candidate_rows"][0]
        if first_candidate_row["row_id"] != materializer_contract["expected_row_ids"][0]:
            failures.append(f"PE00 candidate row id drifted: {recipe}")
        if first_candidate_row["subtask_slot"] != request["subtask_slot"]:
            failures.append(f"PE00 candidate subtask slot drifted: {recipe}")
        if "expected_decode_skeleton" not in first_candidate_row:
            failures.append(f"PE00 candidate missing decode skeleton: {recipe}")
        if "operand_role_map" not in first_candidate_row:
            failures.append(f"PE00 candidate missing operand role map: {recipe}")
        selector = proof_plan["selector_requirements"]
        if not str(selector["selector_id"]).startswith("PE00_"):
            failures.append(f"PE00 selector id must be explicit: {proof_plan}")
        if "direct" in str(selector["forbidden_shortcut"]):
            if proof_plan["stage"] != "pe00_fmax_combine_order":
                failures.append(f"unexpected direct-route shortcut marker: {proof_plan}")
        operand_contract = proof_plan["operand_encoding_contract"]
        if "destination_encoding" not in operand_contract:
            failures.append(f"PE00 operand contract missing destination: {proof_plan}")
        decode_contract = proof_plan["decode_roundtrip_contract"]
        if not decode_contract["roundtrip_artifact"].endswith("_decoded_rows.json"):
            failures.append(f"PE00 decode artifact must be decoded rows: {proof_plan}")
        for artifact in request["required_output_artifacts"]:
            if artifact not in proof_plan["required_proof_artifacts"]:
                failures.append(f"PE00 row proof missing artifact {artifact}: {proof_plan}")
    delivery_work_item = pe00_plan["delivery_work_item"]
    if delivery_work_item["source_id"] != "app_storage:global_max:dtensor_0003":
        failures.append(f"unexpected delivery work item source: {delivery_work_item}")
    if delivery_work_item["source_contract_id"] != contract["contract_id"]:
        failures.append(f"delivery work item must reference contract: {delivery_work_item}")
    minimum_owner_names = [
        item["owner"] for item in delivery_work_item["minimum_code_owners"]
    ]
    if minimum_owner_names != [
        "source_scratch_allocation",
        "tile_store_load_lowering",
        "runtime_subtask_order",
        "receiver_binding",
        "pe00_fmax_chain",
    ]:
        failures.append(f"unexpected delivery owner order: {delivery_work_item}")
    remaining_blockers = delivery_work_item["remaining_blockers"]
    remaining_blocker_ids = [
        blocker["blocker_id"] for blocker in remaining_blockers
    ]
    if remaining_blocker_ids != EXPECTED_REMAINING_BLOCKER_IDS:
        failures.append(
            "unexpected narrowed PE00 blocker list: "
            f"expected {EXPECTED_REMAINING_BLOCKER_IDS}, got {remaining_blocker_ids}"
        )
    if delivery_work_item["remaining_blocker_count"] != len(
        EXPECTED_REMAINING_BLOCKER_IDS
    ):
        failures.append(f"unexpected remaining blocker count: {delivery_work_item}")
    for blocker in remaining_blockers:
        blocker_id = blocker["blocker_id"]
        if blocker["requirement_id"] != EXPECTED_REMAINING_BLOCKER_REQUIREMENTS[
            blocker_id
        ]:
            failures.append(f"remaining blocker requirement drifted: {blocker}")
        if not str(blocker["status"]).startswith("contract_available_"):
            failures.append(f"remaining blocker must be contract-available: {blocker}")
        if "physical allreduce" in blocker["needed_evidence"]:
            failures.append(f"remaining blocker must not request allreduce: {blocker}")

    if plan_view["scratch"]["owner_processor"] != "processor_0_0":
        failures.append(f"expected PE00 scratch owner shape: {plan_view['scratch']}")
    if plan_view["capacity"]["redundant_recompute_total_read_bytes"] != 2_097_152:
        failures.append(f"unexpected redundant capacity: {plan_view['capacity']}")
    if "symbolic_collective_must_not_be_reported_as_physical_route" not in str(
        plan_view["layering_policy"]
    ):
        failures.append(f"layering policy must guard symbolic collective: {plan_view}")
    if "redundant_spmd_is_internal_waiver_not_customer_delivery_strategy" not in str(
        plan_view["layering_policy"]
    ):
        failures.append(f"layering policy must keep redundant internal-only: {plan_view}")

    if failures:
        print("stream compiler log10max collective check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler log10max collective check OK")
    print(f"recommended_delivery_strategy={summary['recommended_delivery_strategy']}")
    print(f"selected_delivery_strategy={summary['selected_delivery_strategy']}")
    print(f"delivery_status={summary['delivery_status']}")
    print(f"runtime_ready={summary['runtime_ready']}")
    print(f"delivery_blocked={summary['delivery_blocked']}")
    print(f"internal_waiver_strategy={summary['internal_waiver_strategy']}")
    print(f"internal_waiver_customer_label={summary['internal_waiver_customer_label']}")
    print(f"pe00_plan_status={summary['pe00_plan_status']}")
    print(
        "pe00_open_requirements="
        f"{plan_view['pe00_materialized_scalar_plan']['open_requirement_ids']}"
    )
    print(
        "pe00_delivery_source_id="
        f"{pe00_plan['delivery_work_item']['source_id']}"
    )
    print(
        "pe00_scratch_contract="
        f"{pe00_plan['scratch_allocation_contract']['contract_id']}"
    )
    print(
        "pe00_scratch_address_candidate="
        f"{pe00_plan['scratch_address_candidate']['candidate_status']}"
    )
    print("pe00_next_code_owners:")
    for owner in pe00_plan["delivery_work_item"]["minimum_code_owners"]:
        closes = ",".join(owner["closes"])
        print(
            "  - "
            f"{owner['owner']} -> {owner['pass_or_file']} "
            f"(closes: {closes})"
        )
    if args.json:
        print(json.dumps(plan_view, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
