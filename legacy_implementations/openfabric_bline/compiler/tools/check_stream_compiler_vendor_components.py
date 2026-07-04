#!/usr/bin/env python3
"""Focused validation for B-line vendor component skeletons."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from gpdpu_compiler.core.stream_compiler.debug_emit import emit_debug_row_artifact
from gpdpu_compiler.core.stream_compiler.folding import analyze_stream_loop_folding
from gpdpu_compiler.core.stream_compiler.vendor_components import (
    build_vendor_component_plan,
    summarize_vendor_component_plan,
)
from gpdpu_compiler.core.stream_compiler.vendor_groups import (
    group_debug_rows_vendor_like,
    remap_vendor_like_groups_locally,
)
from stream_compiler_demo_pipeline import build_demo_pipeline


EXPECTED_OPCODE_COUNTS = {
    "ACC_PREPARE": 64,
    "HMMAL_OR_GEMM_UPDATE": 256,
    "LOAD_OR_COPY": 128,
    "ROUTE_RECV_VISIBILITY": 384,
    "STD": 64,
}

EXPECTED_SUBTASK_INST_COUNTS = {
    "subtask0_accumulator_prepare": 64,
    "subtask1_k_stream": 768,
    "subtask3_finalize_store": 64,
}

EXPECTED_INSTANCE_INST_COUNTS = {
    "k0": 192,
    "k1": 192,
    "k2": 192,
    "k3": 192,
    "None": 128,
}


def main() -> None:
    failures: list[str] = []

    pipeline = build_demo_pipeline("gemm_no_relu")
    artifact = emit_debug_row_artifact(pipeline.binary_layout)
    groups = group_debug_rows_vendor_like(artifact)
    remap = remap_vendor_like_groups_locally(groups)
    component_plan = build_vendor_component_plan(
        remap,
        loop_fold_report=analyze_stream_loop_folding(pipeline.schedule),
    )
    summary = summarize_vendor_component_plan(component_plan)

    if summary["runnability_state"] != "emittable_debug":
        failures.append(f"unexpected runnability state: {summary['runnability_state']}")
    if summary["inst_row_count"] != 896:
        failures.append(f"expected 896 inst rows, got {summary['inst_row_count']}")
    if summary["exeblock_row_count"] != 384:
        failures.append(
            f"expected 384 exeblock rows, got {summary['exeblock_row_count']}"
        )
    if summary["task_row_count"] != 4:
        failures.append(f"expected 4 task rows, got {summary['task_row_count']}")
    if summary["subtask_row_count"] != 12:
        failures.append(f"expected 12 subtask rows, got {summary['subtask_row_count']}")
    if summary["instance_row_count"] != 16:
        failures.append(f"expected 16 instance rows, got {summary['instance_row_count']}")
    if summary["zero_boundary_count"] != 64:
        failures.append(f"expected 64 zero boundaries, got {summary['zero_boundary_count']}")
    if not summary["modeled_component_capacity_ok"]:
        failures.append("modeled component rows exceed DFU3500 capacity")
    if summary["missing_required_component_kinds"] != []:
        failures.append(
            "all report-only component kinds should now be projected, got "
            f"{summary['missing_required_component_kinds']}"
        )
    capacity_report = component_plan.capacity_report
    if capacity_report["inst_rows"]["capacity"] != 69632:
        failures.append(f"unexpected inst capacity: {capacity_report['inst_rows']}")
    if capacity_report["task_rows"]["capacity"] != 4:
        failures.append(f"unexpected task capacity: {capacity_report['task_rows']}")
    if capacity_report["subtask_rows"]["capacity"] != 32:
        failures.append(f"unexpected subtask capacity: {capacity_report['subtask_rows']}")
    if capacity_report["instance_rows"]["capacity"] != 65536:
        failures.append(f"unexpected instance capacity: {capacity_report['instance_rows']}")
    if capacity_report["exeblock_rows"]["modeled"] is not True:
        failures.append("exeblock rows should be report-projected")
    if capacity_report["exeblock_rows"]["active_row_count"] != 384:
        failures.append(f"unexpected exeblock count: {capacity_report['exeblock_rows']}")
    if capacity_report["exeblock_rows"]["capacity"] != 512:
        failures.append(f"unexpected exeblock capacity: {capacity_report['exeblock_rows']}")
    if summary["opcode_counts"] != EXPECTED_OPCODE_COUNTS:
        failures.append(f"unexpected opcode counts: {summary['opcode_counts']}")
    if summary["subtask_inst_counts"] != EXPECTED_SUBTASK_INST_COUNTS:
        failures.append(f"unexpected subtask inst counts: {summary['subtask_inst_counts']}")
    if summary["instance_inst_counts"] != EXPECTED_INSTANCE_INST_COUNTS:
        failures.append(f"unexpected instance inst counts: {summary['instance_inst_counts']}")
    if summary["task_exeblock_counts"] != {"0": 96, "1": 96, "2": 96, "3": 96}:
        failures.append(f"unexpected task exeblock counts: {summary['task_exeblock_counts']}")
    if summary["subtask_exeblock_counts"] != {
        "subtask0_accumulator_prepare": 64,
        "subtask1_k_stream": 256,
        "subtask3_finalize_store": 64,
    }:
        failures.append(
            f"unexpected subtask exeblock counts: {summary['subtask_exeblock_counts']}"
        )
    if set(summary["pe_local_exeblock_counts"].values()) != {24}:
        failures.append(
            "expected every physical PE to have 24 report-only exeBlocks, got "
            f"{summary['pe_local_exeblock_counts']}"
        )
    if summary["pe_local_exeblock_overflow_count"] != 0:
        failures.append("PE-local exeblock indices overflow DFU3500 limits")
    if summary["exeblock_dependency_edge_count"] != 320:
        failures.append(
            "expected 320 report-only exeblock dependency edges, got "
            f"{summary['exeblock_dependency_edge_count']}"
        )
    if summary["exeblock_dependency_proof_counts"] != {
        "loop_instance_order": 192,
        "subtask_order": 128,
    }:
        failures.append(
            "unexpected exeblock dependency proofs: "
            f"{summary['exeblock_dependency_proof_counts']}"
        )
    if summary["exeblock_predecessor_overflow_count"] != 0:
        failures.append("exeblock predecessor slots overflow")
    if summary["exeblock_successor_overflow_count"] != 0:
        failures.append("exeblock successor slots overflow")
    if summary["exeblock_slot_shape_error_count"] != 0:
        failures.append("exeblock report slots do not have fixed 4-slot shape")
    if summary["exeblock_vendor_row_slot_shape_error_count"] != 0:
        failures.append("candidate vendor-row slots do not have fixed 4-slot shape")
    if summary["exeblock_candidate_endpoint_slot_shape_error_count"] != 0:
        failures.append("candidate endpoint slots do not have fixed 4-slot shape")
    if summary["exeblock_candidate_vendor_row_identity_count"] != 384:
        failures.append(
            "expected dense component-index identity candidate row mapping, got "
            f"{summary['exeblock_candidate_vendor_row_identity_count']}"
        )
    if summary["exeblock_candidate_endpoint_valid_count"] != 640:
        failures.append(
            "expected 640 valid predecessor/successor endpoint slots, got "
            f"{summary['exeblock_candidate_endpoint_valid_count']}"
        )
    if summary["exeblock_candidate_struct_view_count"] != 384:
        failures.append(
            "expected 384 candidate exeBlock struct views, got "
            f"{summary['exeblock_candidate_struct_view_count']}"
        )
    if summary["exeblock_candidate_struct_binary_encoded_count"] != 0:
        failures.append("candidate exeBlock struct views must not claim binary encoding")
    if summary["exeblock_candidate_struct_candidate_pc_count"] != 384:
        failures.append(
            "expected candidate PE-local stage PCs on all candidate struct views, got "
            f"{summary['exeblock_candidate_struct_candidate_pc_count']}"
        )
    if summary["exeblock_candidate_struct_unresolved_pc_count"] != 0:
        failures.append(
            "expected no unresolved stage PC policies after candidate PC assignment, got "
            f"{summary['exeblock_candidate_struct_unresolved_pc_count']}"
        )
    if summary["exeblock_candidate_struct_inst_base_count"] != 384:
        failures.append(
            "expected candidate instruction base on all candidate struct views, got "
            f"{summary['exeblock_candidate_struct_inst_base_count']}"
        )
    if summary["candidate_pe_local_pc_row_count"] != 896:
        failures.append(
            "expected every instruction row to have a candidate PE-local PC, got "
            f"{summary['candidate_pe_local_pc_row_count']}"
        )
    if summary["candidate_pe_local_pc_missing_count"] != 0:
        failures.append("instruction rows are missing candidate PE-local PCs")
    if summary["candidate_pe_local_pc_binary_encoded_count"] != 0:
        failures.append("candidate PE-local PCs must not claim binary encoding")
    if summary["task_candidate_struct_view_count"] != 4:
        failures.append(
            f"expected 4 task candidate struct views, got {summary['task_candidate_struct_view_count']}"
        )
    if summary["task_candidate_struct_binary_encoded_count"] != 0:
        failures.append("task candidate struct views must not claim binary encoding")
    if summary["task_candidate_active_subtask_total"] != 12:
        failures.append(
            "expected 12 active subtasks across task candidates, got "
            f"{summary['task_candidate_active_subtask_total']}"
        )
    if summary["subtask_candidate_struct_view_count"] != 12:
        failures.append(
            "expected 12 subtask candidate struct views, got "
            f"{summary['subtask_candidate_struct_view_count']}"
        )
    if summary["subtask_candidate_struct_binary_encoded_count"] != 0:
        failures.append("subtask candidate struct views must not claim binary encoding")
    if summary["subtask_candidate_successor_edge_count"] != 8:
        failures.append(
            "expected two subtask successor edges per task, got "
            f"{summary['subtask_candidate_successor_edge_count']}"
        )
    if summary["subtask_candidate_root_block_total"] != 192:
        failures.append(
            "expected 192 subtask-local root blocks, got "
            f"{summary['subtask_candidate_root_block_total']}"
        )
    if summary["subtask_candidate_block_total"] != 384:
        failures.append(
            "expected 384 subtask candidate blocks, got "
            f"{summary['subtask_candidate_block_total']}"
        )
    if summary["subtask_candidate_observed_loop_instance_total"] != 16:
        failures.append(
            "expected 16 observed loop instances across k-stream subtasks, got "
            f"{summary['subtask_candidate_observed_loop_instance_total']}"
        )
    if summary["folded_subtask_candidate_overlay_count"] != 4:
        failures.append(
            "expected one folded k-stream overlay per task, got "
            f"{summary['folded_subtask_candidate_overlay_count']}"
        )
    if summary["folded_subtask_candidate_binary_encoded_count"] != 0:
        failures.append("folded subtask overlays must not claim binary encoding")
    if summary["folded_subtask_candidate_instances_amount_total"] != 16:
        failures.append(
            "expected folded overlay instances_amount total of 16, got "
            f"{summary['folded_subtask_candidate_instances_amount_total']}"
        )
    if summary["folded_subtask_candidate_stream_total"] != 64:
        failures.append(
            "expected folded overlays to cover 64 stream candidates, got "
            f"{summary['folded_subtask_candidate_stream_total']}"
        )
    if summary["folded_subtask_candidate_shape_total"] != 16:
        failures.append(
            "expected four stream body shapes per task overlay, got "
            f"{summary['folded_subtask_candidate_shape_total']}"
        )
    if summary["folded_subtask_candidate_signature_total"] != 16:
        failures.append(
            "expected four normalized fold signatures per task overlay, got "
            f"{summary['folded_subtask_candidate_signature_total']}"
        )
    if summary["folded_subtask_candidate_projection_proof_count"] != 4:
        failures.append(
            "expected one target projection proof per folded overlay, got "
            f"{summary['folded_subtask_candidate_projection_proof_count']}"
        )
    if summary["instance_candidate_struct_view_count"] != 16:
        failures.append(
            "expected 16 instance candidate struct views, got "
            f"{summary['instance_candidate_struct_view_count']}"
        )
    if summary["instance_candidate_struct_binary_encoded_count"] != 0:
        failures.append("instance candidate struct views must not claim binary encoding")
    if summary["instance_candidate_base_addr_resolved_count"] != 32:
        failures.append(
            "expected A/B base slots resolved across 16 k-stream instances, got "
            f"{summary['instance_candidate_base_addr_resolved_count']}"
        )
    if summary["instance_candidate_base_addr_unresolved_count"] != 0:
        failures.append(
            "expected no unresolved k-stream base slots after Phase 4 A/B mapping, got "
            f"{summary['instance_candidate_base_addr_unresolved_count']}"
        )
    if summary["instance_candidate_base_addr_disabled_count"] != 32:
        failures.append(
            "expected C/output spare slots to be disabled sentinel candidates, got "
            f"{summary['instance_candidate_base_addr_disabled_count']}"
        )
    if summary["instance_candidate_base_addr_slot_shape_error_count"] != 0:
        failures.append("instance candidate base_addr slots do not have fixed 4-slot shape")
    if summary["exeblock_padded_slot_row_count"] != 384:
        failures.append(
            "expected all 384 exeBlocks to have zero-filled invalid endpoint slots, got "
            f"{summary['exeblock_padded_slot_row_count']}"
        )
    first_exeblock = component_plan.exeblock_rows[0]
    if first_exeblock["predecessor_slots"] != [0, 0, 0, 0]:
        failures.append(f"unexpected first predecessor slots: {first_exeblock}")
    if first_exeblock["successor_slots"] != [1, 0, 0, 0]:
        failures.append(f"unexpected first successor slots: {first_exeblock}")
    if first_exeblock["slot_policy"] != "report_only_padded_component_indices":
        failures.append(f"unexpected slot policy: {first_exeblock}")
    if first_exeblock["slot_values_are_vendor_row_indices"] is not False:
        failures.append("report-only slots must not claim vendor row-index semantics")
    if first_exeblock["candidate_vendor_row_index"] != 0:
        failures.append(f"unexpected candidate vendor row index: {first_exeblock}")
    if first_exeblock["successor_vendor_row_slots"] != [1, 0, 0, 0]:
        failures.append(f"unexpected first vendor-row successor slots: {first_exeblock}")
    if first_exeblock["vendor_row_slots_are_binary_encoded"] is not False:
        failures.append("candidate vendor-row slots must not claim binary encoding")
    if first_exeblock["predecessor_endpoint_slots"] != [
        {"pe_pos": {"x": 0, "y": 0, "z": 0}, "block_idx": 0, "valid": False, "invalid_slot_policy": "zero_fill_gated_by_valid_false"},
        {"pe_pos": {"x": 0, "y": 0, "z": 0}, "block_idx": 0, "valid": False, "invalid_slot_policy": "zero_fill_gated_by_valid_false"},
        {"pe_pos": {"x": 0, "y": 0, "z": 0}, "block_idx": 0, "valid": False, "invalid_slot_policy": "zero_fill_gated_by_valid_false"},
        {"pe_pos": {"x": 0, "y": 0, "z": 0}, "block_idx": 0, "valid": False, "invalid_slot_policy": "zero_fill_gated_by_valid_false"},
    ]:
        failures.append(f"unexpected first predecessor endpoint slots: {first_exeblock}")
    if first_exeblock["successor_endpoint_slots"] != [
        {"pe_pos": {"x": 0, "y": 0, "z": 0}, "block_idx": 1, "valid": True},
        {"pe_pos": {"x": 0, "y": 0, "z": 0}, "block_idx": 0, "valid": False, "invalid_slot_policy": "zero_fill_gated_by_valid_false"},
        {"pe_pos": {"x": 0, "y": 0, "z": 0}, "block_idx": 0, "valid": False, "invalid_slot_policy": "zero_fill_gated_by_valid_false"},
        {"pe_pos": {"x": 0, "y": 0, "z": 0}, "block_idx": 0, "valid": False, "invalid_slot_policy": "zero_fill_gated_by_valid_false"},
    ]:
        failures.append(f"unexpected first successor endpoint slots: {first_exeblock}")
    if first_exeblock["endpoint_slots_are_binary_encoded"] is not False:
        failures.append("candidate endpoint slots must not claim binary encoding")
    first_struct = first_exeblock["exeBlock_conf_info_candidate"]
    first_conf = first_struct["exeBlock_conf"]
    if first_struct["binary_encoded"] is not False:
        failures.append("candidate exeBlock struct must not claim binary encoding")
    if first_struct["block_idx"] != 0 or first_struct["pe_dst"] != {"x": 0, "y": 0, "z": 0}:
        failures.append(f"unexpected first candidate struct header: {first_struct}")
    if first_conf["req_activations"] != 0 or first_conf["child_amount"] != 1:
        failures.append(f"unexpected first candidate dependency fields: {first_conf}")
    if first_conf["stage_inst_amounts"] != {"LD": 0, "CAL": 1, "FLOW": 0, "ST": 0}:
        failures.append(f"unexpected first candidate stage counts: {first_conf}")
    if first_conf["stages_start_pc"] != {
        "LD": 0,
        "CAL": 0,
        "FLOW": 1,
        "ST": 1,
        "MAX_COMPONENT": 1,
    }:
        failures.append(f"unexpected first candidate stage PCs: {first_conf}")
    if first_conf["inst_mem_based_addr"] != 0:
        failures.append(f"unexpected first candidate inst base: {first_conf}")
    if first_conf["block_class"] != 0 or first_conf["block_class_policy"] != "reserved_zero_from_vendor_memset_evidence":
        failures.append(f"unexpected first candidate block_class policy: {first_conf}")
    if first_conf["stage_start_pc_policy"] != "candidate_dense_per_physical_pe_instruction_order":
        failures.append(f"unexpected candidate stage PC policy: {first_conf}")
    k0_struct = component_plan.exeblock_rows[1]["exeBlock_conf_info_candidate"]
    k0_conf = k0_struct["exeBlock_conf"]
    if k0_conf["stage_inst_amounts"] != {"LD": 2, "CAL": 1, "FLOW": 0, "ST": 0}:
        failures.append(f"unexpected k0 candidate stage counts: {k0_conf}")
    if k0_conf["stages_start_pc"] != {
        "LD": 1,
        "CAL": 3,
        "FLOW": 4,
        "ST": 4,
        "MAX_COMPONENT": 4,
    }:
        failures.append(f"unexpected k0 candidate stage PCs: {k0_conf}")
    if k0_conf["inst_mem_based_addr"] != 304:
        failures.append(f"unexpected k0 candidate inst base: {k0_conf}")
    if k0_conf["req_activations"] != 1 or k0_conf["child_amount"] != 1:
        failures.append(f"unexpected k0 candidate dependency fields: {k0_conf}")
    final_struct = component_plan.exeblock_rows[5]["exeBlock_conf_info_candidate"]
    final_conf = final_struct["exeBlock_conf"]
    if final_conf["stage_inst_amounts"] != {"LD": 0, "CAL": 0, "FLOW": 0, "ST": 1}:
        failures.append(f"unexpected final candidate stage counts: {final_conf}")
    if final_conf["stages_start_pc"] != {
        "LD": 13,
        "CAL": 13,
        "FLOW": 13,
        "ST": 13,
        "MAX_COMPONENT": 14,
    }:
        failures.append(f"unexpected final candidate stage PCs: {final_conf}")
    if final_conf["inst_mem_based_addr"] != 3952:
        failures.append(f"unexpected final candidate inst base: {final_conf}")
    if final_conf["is_leaf"] is not True or final_conf["child_amount"] != 0:
        failures.append(f"unexpected final candidate leaf fields: {final_conf}")
    if summary["missing_provenance_count"] != 0:
        failures.append("component rows are missing provenance")
    if summary["forbidden_tile_micro_block_field_count"] != 0:
        failures.append("component rows contain TileMicroBlock fields")
    if summary["non_dense_component_index_count"] != 0:
        failures.append("component indices are not dense")
    if summary["diagnostic_count"] != 0:
        failures.append(f"expected no component diagnostics, got {summary['diagnostic_count']}")

    task_inst_counts = {
        row["task_id"]: row["inst_count"]
        for row in component_plan.task_rows
    }
    if task_inst_counts != {0: 224, 1: 224, 2: 224, 3: 224}:
        failures.append(f"unexpected per-task inst counts: {task_inst_counts}")
    task_zero_counts = {
        row["task_id"]: row["zero_boundary_count"]
        for row in component_plan.task_rows
    }
    if task_zero_counts != {0: 16, 1: 16, 2: 16, 3: 16}:
        failures.append(f"unexpected per-task zero counts: {task_zero_counts}")
    first_task_conf = component_plan.task_rows[0]["task_conf_info_candidate"]
    if first_task_conf["subtasks_idx"] != [0, 1, 3, 0, 0, 0, 0, 0]:
        failures.append(f"unexpected task0 subtask slots: {first_task_conf}")
    if first_task_conf["subtasks_idx_padding_policy"] != "zero_fill_ignored_by_subtasks_amount":
        failures.append(f"unexpected task0 subtask padding policy: {first_task_conf}")
    if first_task_conf["suc_tasks"] != [0, 0, 0, 0]:
        failures.append(f"task0 should have no successor tasks: {first_task_conf}")
    if first_task_conf["suc_tasks_padding_policy"] != "zero_fill_independent_start_end_task_policy":
        failures.append(f"unexpected task0 successor padding policy: {first_task_conf}")
    first_subtask_conf = component_plan.subtask_rows[0]["sub_task_conf_info_candidate"]
    if first_subtask_conf["suc_subtasks"] != [1, 0, 0, 0]:
        failures.append(f"unexpected subtask0 successor chain: {first_subtask_conf}")
    if first_subtask_conf["suc_subtasks_padding_policy"] != "zero_fill_ignored_by_subtask_successor_chain_policy":
        failures.append(f"unexpected subtask0 successor padding policy: {first_subtask_conf}")
    if first_subtask_conf["root_block_amount"] != 16 or first_subtask_conf["block_amount"] != 16:
        failures.append(f"unexpected subtask0 block shape: {first_subtask_conf}")
    k_stream_conf = component_plan.subtask_rows[1]["sub_task_conf_info_candidate"]
    if k_stream_conf["suc_subtasks"] != [3, 0, 0, 0]:
        failures.append(f"unexpected k-stream successor chain: {k_stream_conf}")
    if k_stream_conf["instances_amount"] != 1:
        failures.append(f"k-stream report should remain expanded-loop instances: {k_stream_conf}")
    if k_stream_conf["observed_loop_instance_count"] != 4:
        failures.append(f"k-stream should report four observed loop instances: {k_stream_conf}")
    if k_stream_conf["root_block_amount"] != 16 or k_stream_conf["block_amount"] != 64:
        failures.append(f"unexpected k-stream block shape: {k_stream_conf}")
    folded_k_stream_conf = component_plan.subtask_rows[1]["folded_subtask_conf_candidate"]
    if folded_k_stream_conf["binary_encoded"] is not False:
        failures.append("folded k-stream overlay must not claim binary encoding")
    if folded_k_stream_conf["overlay_only"] is not True:
        failures.append(f"folded k-stream candidate must be overlay-only: {folded_k_stream_conf}")
    if folded_k_stream_conf["instances_amount"] != 4:
        failures.append(f"unexpected folded k-stream instances amount: {folded_k_stream_conf}")
    if folded_k_stream_conf["instances_amount_policy"] != "stream_loop_fold_report_candidate":
        failures.append(f"unexpected folded k-stream policy: {folded_k_stream_conf}")
    if folded_k_stream_conf["fold_scope"] != "stream_subtask_loop":
        failures.append(f"unexpected folded k-stream scope: {folded_k_stream_conf}")
    if folded_k_stream_conf["stream_candidate_count"] != 16:
        failures.append(f"unexpected folded k-stream stream count: {folded_k_stream_conf}")
    if folded_k_stream_conf["loop_instance_keys"] != ["k0", "k1", "k2", "k3"]:
        failures.append(f"unexpected folded k-stream loop keys: {folded_k_stream_conf}")
    if folded_k_stream_conf["loop_axis"] != "reduction_fragment":
        failures.append(f"unexpected folded source loop axis: {folded_k_stream_conf}")
    if folded_k_stream_conf["derived_region_axis"] != "derived_region":
        failures.append(f"unexpected folded derived region axis: {folded_k_stream_conf}")
    if folded_k_stream_conf["derived_instance_keys"] != [
        "region0",
        "region1",
        "region2",
        "region3",
    ]:
        failures.append(f"unexpected folded derived instance keys: {folded_k_stream_conf}")
    if folded_k_stream_conf["source_to_derived_instance_keys"] != [
        {"source": "k0", "derived": "region0"},
        {"source": "k1", "derived": "region1"},
        {"source": "k2", "derived": "region2"},
        {"source": "k3", "derived": "region3"},
    ]:
        failures.append(f"unexpected folded source-to-derived mapping: {folded_k_stream_conf}")
    if folded_k_stream_conf["fold_proof_instance_key_policy"] != (
        "derived_instance_keys_are_fold_proof_authority;"
        "loop_instance_keys_are_projection_compatibility_labels"
    ):
        failures.append(f"unexpected folded instance key policy: {folded_k_stream_conf}")
    if folded_k_stream_conf["stream_fold_body_signature_policy"] != (
        "normalized_semantics_and_dependency_topology;"
        "role_strings_are_diagnostics_only"
    ):
        failures.append(f"unexpected folded signature policy: {folded_k_stream_conf}")
    signature_counts = folded_k_stream_conf["stream_fold_body_signature_counts"]
    if sorted(signature_counts.values()) != [1, 3, 3, 9]:
        failures.append(f"unexpected folded signature counts: {folded_k_stream_conf}")
    if any(
        "operand_materialize:" in key
        or "operand_route_recv:" in key
        or "compute_core:" in key
        for key in signature_counts
    ):
        failures.append(
            "folded signature counts must not use operator role strings: "
            f"{signature_counts}"
        )
    if folded_k_stream_conf["stream_body_shape_policy"] != (
        "per_stream_body_shapes_not_global_single_body"
    ):
        failures.append(f"unexpected folded k-stream shape policy: {folded_k_stream_conf}")
    if sorted(folded_k_stream_conf["stream_body_shape_counts"].values()) != [1, 3, 3, 9]:
        failures.append(f"unexpected folded k-stream shape counts: {folded_k_stream_conf}")
    projection_proof = folded_k_stream_conf["target_fold_projection_proof"]
    expected_projection_proof_keys = {
        "schema_version",
        "target",
        "projection_status",
        "binary_encoded",
        "source_loop_uniformity_proof_ids",
        "projection_fields",
        "derived_instance_keys",
        "source_to_derived_instance_keys",
        "projection_compatibility_labels",
        "target_requirements",
        "policy",
    }
    if set(projection_proof) != expected_projection_proof_keys:
        failures.append(f"unexpected target projection proof schema: {projection_proof}")
    if projection_proof["schema_version"] != "target_fold_projection_proof.v1":
        failures.append(f"unexpected target projection proof schema version: {projection_proof}")
    if projection_proof["target"] != "dfu3500_vendor_component_overlay":
        failures.append(f"unexpected target projection proof: {projection_proof}")
    if projection_proof["projection_status"] != "report_only_eligible":
        failures.append(f"unexpected target projection status: {projection_proof}")
    if projection_proof["binary_encoded"] is not False:
        failures.append(f"target projection proof must be report-only: {projection_proof}")
    if projection_proof["derived_instance_keys"] != [
        "region0",
        "region1",
        "region2",
        "region3",
    ]:
        failures.append(f"target projection proof lost derived keys: {projection_proof}")
    if projection_proof["projection_compatibility_labels"] != ["k0", "k1", "k2", "k3"]:
        failures.append(f"target projection proof lost compatibility labels: {projection_proof}")
    if projection_proof["policy"] != (
        "target_projection_eligibility_consumes_loop_uniformity_proof;"
        "does_not_define_foldability_or_emit_binary_bytes"
    ):
        failures.append(f"unexpected target projection policy: {projection_proof}")
    if folded_k_stream_conf["instance_base_mapping_status"] != "resolved_for_gemm_k_stream_a_b_slots":
        failures.append(f"unexpected folded k-stream base mapping status: {folded_k_stream_conf}")
    if folded_k_stream_conf["instance_base_mapping_policy"] != (
        "slot0_A_slot1_B_resolved_from_dfu3500_regions;"
        "slot2_slot3_disabled_sentinel_for_k_stream"
    ):
        failures.append(f"unexpected folded k-stream base mapping policy: {folded_k_stream_conf}")
    if folded_k_stream_conf["expanded_rows_remain_authoritative"] is not True:
        failures.append(f"folded overlay must preserve expanded authority: {folded_k_stream_conf}")
    if folded_k_stream_conf["folded_overlay_does_not_delete_expanded_exeblocks"] is not True:
        failures.append(f"folded overlay must not delete expanded exeBlocks: {folded_k_stream_conf}")
    final_subtask_conf = component_plan.subtask_rows[2]["sub_task_conf_info_candidate"]
    if final_subtask_conf["suc_subtasks"] != [0, 0, 0, 0]:
        failures.append(f"final subtask should have no successor subtasks: {final_subtask_conf}")
    if final_subtask_conf["is_exe_end"] is not True:
        failures.append(f"final subtask should be end marker: {final_subtask_conf}")
    first_instance_conf = component_plan.instance_rows[0]["instance_conf_info_candidate"]
    if first_instance_conf["binary_encoded"] is not False:
        failures.append("instance candidate struct must not claim binary encoding")
    if first_instance_conf["task_idx"] != 0:
        failures.append(f"unexpected first instance task idx: {first_instance_conf}")
    if first_instance_conf["subtask_idx"] != 1:
        failures.append(f"unexpected first instance subtask idx: {first_instance_conf}")
    if first_instance_conf["instance_idx"] != 0:
        failures.append(f"unexpected first instance idx: {first_instance_conf}")
    if first_instance_conf["base_addr_slot_count"] != 4:
        failures.append(f"unexpected first instance base slot count: {first_instance_conf}")
    if first_instance_conf["base_addr_policy"] != (
        "gemm_k_stream_profile_backed_a_b_slots_output_slots_disabled"
    ):
        failures.append(f"unexpected first instance base policy: {first_instance_conf}")
    if first_instance_conf["data_memory_policy"] != (
        "data_base_slots_are_distinct_from_instruction_pc_layout"
    ):
        failures.append(f"unexpected first instance data memory policy: {first_instance_conf}")
    expected_k0_slots = [
        {
            "slot": 0,
            "role": "A",
            "region_name": "gemm_input1_a",
            "base_addr_word": 0,
            "base_addr_word_hex": "0x00000000",
            "base_addr_byte": 0,
            "base_addr_byte_hex": "0x00000000",
            "status": "resolved",
            "resolution_policy": "dfu3500_gemm_k_stream_legacy_region_base_plus_k_offset",
            "increment_words_per_instance": 32,
            "instance_idx": 0,
            "base_addr_idx": 0,
            "expected_iter_exe_cond": 0,
            "logical_address_expr": "A[:, 0*64:1*64]",
            "effective_address_expr": "4 * (base_addr[0] + instruction_imm_word_offset)",
            "binary_encoded": False,
        },
        {
            "slot": 1,
            "role": "B",
            "region_name": "gemm_input2_b",
            "base_addr_word": 65536,
            "base_addr_word_hex": "0x00010000",
            "base_addr_byte": 262144,
            "base_addr_byte_hex": "0x00040000",
            "status": "resolved",
            "resolution_policy": "dfu3500_gemm_k_stream_legacy_region_base_plus_k_offset",
            "increment_words_per_instance": 16384,
            "instance_idx": 0,
            "base_addr_idx": 1,
            "expected_iter_exe_cond": 1,
            "logical_address_expr": "B[0*64:1*64, :]",
            "effective_address_expr": "4 * (base_addr[1] + instruction_imm_word_offset)",
            "binary_encoded": False,
        },
        {
            "slot": 2,
            "role": "unused",
            "base_addr_word": 4294967295,
            "base_addr_word_hex": "0xffffffff",
            "base_addr_byte": None,
            "status": "disabled_sentinel",
            "resolution_policy": "slot_not_consumed_by_gemm_k_stream_body",
            "base_addr_idx": 2,
            "binary_encoded": False,
        },
        {
            "slot": 3,
            "role": "unused",
            "base_addr_word": 4294967295,
            "base_addr_word_hex": "0xffffffff",
            "base_addr_byte": None,
            "status": "disabled_sentinel",
            "resolution_policy": "slot_not_consumed_by_gemm_k_stream_body",
            "base_addr_idx": 3,
            "binary_encoded": False,
        },
    ]
    if first_instance_conf["base_addr"] != expected_k0_slots:
        failures.append(f"unexpected first instance base slots: {first_instance_conf}")
    second_instance_conf = component_plan.instance_rows[1]["instance_conf_info_candidate"]
    if second_instance_conf["base_addr"][0]["base_addr_word"] != 32:
        failures.append(f"unexpected k1 A base slot: {second_instance_conf}")
    if second_instance_conf["base_addr"][1]["base_addr_word"] != 81920:
        failures.append(f"unexpected k1 B base slot: {second_instance_conf}")
    if second_instance_conf["base_addr"][2]["status"] != "disabled_sentinel":
        failures.append(f"unexpected k1 disabled slot: {second_instance_conf}")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "vendor_components.json"
        content = json.dumps(component_plan.to_plan(), indent=2, sort_keys=True) + "\n"
        path.write_text(content, encoding="utf-8")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if loaded != component_plan.to_plan():
            failures.append("vendor component JSON does not round-trip")

    relu_artifact = emit_debug_row_artifact(build_demo_pipeline("gemm_relu").binary_layout)
    relu_components = build_vendor_component_plan(
        remap_vendor_like_groups_locally(group_debug_rows_vendor_like(relu_artifact))
    )
    relu_summary = summarize_vendor_component_plan(relu_components)
    if relu_summary["inst_row_count"] != 0:
        failures.append("gemm_relu fail-closed artifact must not produce component inst rows")
    if relu_summary["exeblock_row_count"] != 0:
        failures.append("gemm_relu fail-closed artifact must not produce exeblock rows")
    if relu_summary["diagnostic_severity_counts"] != {"error": 3}:
        failures.append(
            "unexpected ReLU component diagnostics: "
            f"{relu_summary['diagnostic_severity_counts']}"
        )

    if failures:
        print("stream compiler vendor component check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler vendor component check OK")
    print(f"inst_rows={summary['inst_row_count']}")
    print(f"task_rows={summary['task_row_count']}")


if __name__ == "__main__":
    main()
