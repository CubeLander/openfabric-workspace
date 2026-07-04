"""Debug-only MICC/control component byte writers for B-line candidates.

These writers consume serializer-readiness and vendor component reports.  They
do not mutate frontend IR, op-time state, PE programs, or vendor package state.
Unknown or inconsistent semantic fields produce blocked artifacts with empty
payloads.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Any

from gpdpu_compiler.core.dfu3500 import (
    DFU3500_STRUCT_SIZES,
    DFU3500_VENDOR_LIMITS,
)

from .serializer_readiness import SerializerReadinessPlan
from .template_ops import Diagnostic
from .vendor_components import VendorComponentPlan

TASK_CONF_INFO_STRUCT = "task_conf_info_t"
TASK_CONF_INFO_FORMAT = "<BB6xQQ8Q4Q"
TASK_CONF_INFO_RECORD_SIZE = struct.calcsize(TASK_CONF_INFO_FORMAT)

EXEBLOCK_CONF_INFO_STRUCT = "exeBlock_conf_info_t"
EXEBLOCK_CONF_INFO_HEADER_FORMAT = "<B7xQ3QQ"
EXEBLOCK_CONF_FORMAT = "<Q5B3x5Q20Q20Q11QB7x"
EXEBLOCK_CONF_INFO_RECORD_SIZE = (
    struct.calcsize(EXEBLOCK_CONF_INFO_HEADER_FORMAT)
    + struct.calcsize(EXEBLOCK_CONF_FORMAT)
)

SUB_TASK_CONF_INFO_STRUCT = "sub_task_conf_info_t"
SUB_TASK_CONF_INFO_HEADER_FORMAT = "<BB6xQQ4QQQ"
SUB_TASK_CONF_INFO_TRAILER_FORMAT = "<QQ"
SUB_TASK_CONF_INFO_RECORD_SIZE = int(DFU3500_STRUCT_SIZES[SUB_TASK_CONF_INFO_STRUCT])
SUB_TASK_EMBEDDED_EXEBLOCK_OFFSET = 72

INSTANCE_CONF_INFO_STRUCT = "instance_conf_info_t"
INSTANCE_CONF_INFO_RECORD_SIZE = int(DFU3500_STRUCT_SIZES[INSTANCE_CONF_INFO_STRUCT])

INSTANCE_TABLE_ADDR_SPACE = "instance_component_offset"
INSTANCE_TABLE_ADDR_UNIT = "bytes"

MAX_SUBTASK_SLOTS = int(DFU3500_VENDOR_LIMITS["max_subtasks_per_task"])
MAX_TASK_FOLLOW_SLOTS = int(DFU3500_VENDOR_LIMITS["max_task_follow_per_task"])
MAX_EXEBLOCKS_PER_SUBTASK = int(DFU3500_VENDOR_LIMITS["max_exe_block"])


def build_pe00_materialized_scalar_micc_lowering_intent(
    runtime_order_contract: dict[str, object],
) -> dict[str, object]:
    """Build the MICC row-lowering entry for PE00 scalar ordering.

    This consumes the runtime order contract and names the MICC row families
    that must preserve the PE00 materialize-before-readback order.  It is not a
    byte writer and intentionally keeps the runtime gate fail-closed.
    """

    order_intent = runtime_order_contract.get("micc_order_lowering_intent")
    if not isinstance(order_intent, dict):
        return {
            "schema_version": 1,
            "artifact_kind": "pe00_materialized_scalar_micc_lowering_intent",
            "status": "blocked_missing_runtime_order_intent",
            "runtime_runnable_claim": False,
            "row_bytes_claim": False,
            "physical_route_allreduce": False,
        }

    ordered_subtask_slots = list(order_intent.get("ordered_subtask_slots", []))
    successor_edges = list(order_intent.get("successor_edges", []))
    stage_row_id_contract = dict(order_intent.get("stage_row_id_contract", {}))
    runtime_order_proof_plan = order_intent.get("runtime_order_proof_plan")
    if not isinstance(runtime_order_proof_plan, dict):
        runtime_order_proof_plan = {
            "schema_version": 1,
            "artifact_kind": "pe00_materialized_scalar_runtime_order_proof_plan",
            "status": "blocked_missing_runtime_order_proof_plan",
            "runtime_runnable_claim": False,
            "row_bytes_claim": False,
            "physical_route_allreduce": False,
        }
    return {
        "schema_version": 1,
        "artifact_kind": "pe00_materialized_scalar_micc_lowering_intent",
        "source_id": runtime_order_contract.get("source_id"),
        "status": "micc_lowering_intent_available_rows_missing",
        "input_contract_status": runtime_order_contract.get("status"),
        "ordered_subtask_slots": ordered_subtask_slots,
        "successor_edges": successor_edges,
        "stage_row_id_contract": stage_row_id_contract,
        "micc_materialization_request": runtime_order_proof_plan.get(
            "micc_materialization_request",
            {
                "schema_version": 1,
                "artifact_kind": (
                    "pe00_materialized_scalar_micc_order_materialization_request"
                ),
                "status": "blocked_missing_runtime_order_materialization_request",
                "runtime_runnable_claim": False,
                "row_bytes_claim": False,
                "physical_route_allreduce": False,
            },
        ),
        "decoded_order_contract": runtime_order_proof_plan.get(
            "decoded_order_contract",
            {
                "schema_version": 1,
                "artifact_kind": "pe00_materialized_scalar_decoded_micc_order_contract",
                "status": "blocked_missing_decoded_order_contract",
                "runtime_runnable_claim": False,
                "row_bytes_claim": False,
                "physical_route_allreduce": False,
            },
        ),
        "runtime_trace_contract": runtime_order_proof_plan.get(
            "runtime_trace_contract",
            {
                "schema_version": 1,
                "artifact_kind": "pe00_materialized_scalar_runtime_trace_contract",
                "status": "blocked_missing_runtime_trace_contract",
                "runtime_runnable_claim": False,
                "row_bytes_claim": False,
                "physical_route_allreduce": False,
            },
        ),
        "target_structs": [
            {
                "struct_name": "task_conf_info_t",
                "row_intent": "task active subtask list preserves PE00 order slots",
                "row_bytes_status": "blocked_missing_micc_writer_rows",
                "required_fields": [
                    "active_subtask_count",
                    "active_subtask_indices",
                    "task_follow_or_wait_policy",
                ],
                "decoded_field_contract": {
                    "active_subtask_indices": ordered_subtask_slots,
                    "must_include_ordered_slots": True,
                    "must_preserve_successor_edges": successor_edges,
                    "stage_row_id_contract": stage_row_id_contract,
                },
                "required_proof_artifacts": [
                    "decoded_task_conf_info_t_rows.json",
                ],
            },
            {
                "struct_name": "sub_task_conf_info_t",
                "row_intent": "subtask successor and instance fields encode order",
                "row_bytes_status": "blocked_missing_micc_writer_rows",
                "required_fields": [
                    "subtask_slot_index",
                    "successor_subtask_index",
                    "instances_conf_mem_based_addr",
                    "instances_amount",
                ],
                "decoded_field_contract": {
                    "successor_edges": successor_edges,
                    "stage_row_id_contract": stage_row_id_contract,
                    "address_zero_policy": (
                        "instances_amount==0 ignores address; "
                        "instances_amount>0 address zero means row0"
                    ),
                },
                "required_proof_artifacts": [
                    "decoded_sub_task_conf_info_t_rows.json",
                ],
            },
            {
                "struct_name": "exeBlock_conf_info_t",
                "row_intent": "execute block chain follows subtask slot order",
                "row_bytes_status": "blocked_missing_micc_writer_rows",
                "required_fields": [
                    "exe_block_index",
                    "dependency_or_wait_flags",
                    "instruction_range_for_subtask",
                ],
                "decoded_field_contract": {
                    "dependency_or_wait_flags": (
                        "consumer readback waits for PE00 scalar store"
                    ),
                    "instruction_ranges_reference_ordered_subtasks": True,
                    "stage_row_id_contract": stage_row_id_contract,
                },
                "required_proof_artifacts": [
                    "decoded_exeBlock_conf_info_t_rows.json",
                ],
            },
        ],
        "required_order_proof_artifacts": [
            "decoded_micc_order.json",
            "decoded_task_subtask_exeblock_rows.json",
            "runtime_start_wait_trace.json",
        ],
        "runtime_order_proof_plan": runtime_order_proof_plan,
        "blocked_on": [
            "runtime_subtask_order_proof_missing",
            "micc_successor_wait_row_bytes_missing",
        ],
        "runtime_runnable_claim": False,
        "row_bytes_claim": False,
        "physical_route_allreduce": False,
    }


def build_gemm_no_relu_micc_final_candidate_report(
    *,
    task_artifact: "MiccComponentWriterArtifact",
    subtask_artifact: "MiccComponentWriterArtifact",
    exeblock_artifact: "MiccComponentWriterArtifact",
) -> dict[str, Any]:
    """Summarize GEMM no-ReLU MICC bytes below final runtime readiness.

    This intentionally does not change the underlying component writers from
    debug-only artifacts.  It narrows the final-MICC blocker by separating
    available struct bytes from the decoded roundtrip/runtime-order proofs that
    are still missing before those bytes can become a runnable MICC payload.
    """

    sections = [
        _gemm_no_relu_micc_final_section(
            artifact=task_artifact,
            section="tasks_conf_info",
            final_role="task_conf_info_t",
            required_decoded_fields=(
                "is_exe_start",
                "is_exe_end",
                "subtasks_amount",
                "subtasks_idx",
                "suc_tasks",
            ),
            required_proof_artifacts=(
                "decoded_task_conf_info_t_rows.json",
                "decoded_task_subtask_exeblock_order.json",
            ),
            blockers=(
                "decoded_task_conf_info_roundtrip_missing",
                "task_active_subtask_order_proof_missing",
                "task_start_end_runtime_policy_unproven",
            ),
        ),
        _gemm_no_relu_micc_final_section(
            artifact=subtask_artifact,
            section="subtasks_conf_info",
            final_role="sub_task_conf_info_t",
            required_decoded_fields=(
                "is_exe_start",
                "is_exe_end",
                "instances_amount",
                "instances_conf_mem_based_addr",
                "suc_subtasks",
                "root_block_amount",
                "block_amount",
                "embedded_exeBlock_conf_info",
            ),
            required_proof_artifacts=(
                "decoded_sub_task_conf_info_t_rows.json",
                "decoded_instance_table_addresses.json",
                "decoded_task_subtask_exeblock_order.json",
            ),
            blockers=(
                "decoded_sub_task_conf_info_roundtrip_missing",
                "subtask_successor_order_proof_missing",
                "embedded_exeblock_roundtrip_missing",
                "instance_table_address_roundtrip_missing",
            ),
        ),
        _gemm_no_relu_micc_final_section(
            artifact=exeblock_artifact,
            section="exeblock_conf_info",
            final_role="exeBlock_conf_info_t",
            required_decoded_fields=(
                "valid",
                "block_idx",
                "pe_dst",
                "priority",
                "inst_mem_based_addr",
                "stage_inst_amounts",
                "predecessors",
                "successors",
                "is_leaf",
            ),
            required_proof_artifacts=(
                "decoded_exeBlock_conf_info_t_rows.json",
                "decoded_task_subtask_exeblock_order.json",
            ),
            blockers=(
                "decoded_exeBlock_conf_info_roundtrip_missing",
                "exeBlock_instruction_range_roundtrip_missing",
                "exeBlock_wait_or_dependency_flags_unproven",
                "exeBlock_is_leaf_policy_unproven",
            ),
        ),
    ]
    all_struct_bytes_available = all(
        section["struct_bytes_available"] is True for section in sections
    )
    all_decoded_roundtrip_available = all(
        _decoded_roundtrip_claim(section["decoded_roundtrip_proof_plan"])
        for section in sections
    )
    runtime_order_proof = _build_gemm_no_relu_runtime_order_proof_plan(
        task_artifact=task_artifact,
        subtask_artifact=subtask_artifact,
        exeblock_artifact=exeblock_artifact,
        struct_bytes_available=all_struct_bytes_available,
        decoded_roundtrip_available=all_decoded_roundtrip_available,
    )
    blockers: list[str] = []
    for section in sections:
        blockers.extend(str(item) for item in section["blockers"])
    closed_runtime_blockers = {
        str(item) for item in runtime_order_proof.get("closed_blockers", [])
    }
    blockers = [
        blocker for blocker in blockers if blocker not in closed_runtime_blockers
    ]
    blockers.extend(str(item) for item in runtime_order_proof["blockers"])
    status = (
        str(runtime_order_proof["status"])
        if all_decoded_roundtrip_available
        else "struct_bytes_available_final_proof_missing"
        if all_struct_bytes_available
        else "blocked_missing_struct_bytes"
    )
    return {
        "schema_version": 1,
        "artifact_kind": "gemm_no_relu_micc_final_candidate_report",
        "status": status,
        "runtime_ready_candidate": False,
        "uploadable_claim": False,
        "final_micc_file_claim": False,
        "struct_bytes_available": all_struct_bytes_available,
        "decoded_struct_roundtrip_available": all_decoded_roundtrip_available,
        "sections": sections,
        "section_statuses": {
            str(section["section"]): str(section["status"]) for section in sections
        },
        "payload_size_bytes": sum(int(section["payload_size_bytes"]) for section in sections),
        "runtime_order_proof_plan": runtime_order_proof,
        "blockers": _dedupe_strings(blockers),
        "layering_policy": (
            "micc_final_candidate_report_consumes_component_writer_artifacts;"
            "does_not_reclassify_debug_bytes_as_runtime_ready;"
            "requires_decoded_roundtrip_and_runtime_order_proof_before_final_micc"
        ),
    }


def _build_gemm_no_relu_runtime_order_proof_plan(
    *,
    task_artifact: "MiccComponentWriterArtifact",
    subtask_artifact: "MiccComponentWriterArtifact",
    exeblock_artifact: "MiccComponentWriterArtifact",
    struct_bytes_available: bool,
    decoded_roundtrip_available: bool,
) -> dict[str, object]:
    if not decoded_roundtrip_available:
        return {
            "schema_version": 1,
            "artifact_kind": "gemm_no_relu_micc_runtime_order_proof_plan",
            "status": "blocked_missing_decoded_runtime_order",
            "runtime_ready_candidate": False,
            "row_bytes_claim": struct_bytes_available,
            "decoded_struct_roundtrip_claim": False,
            "local_order_policy_claim": False,
            "runtime_start_wait_trace_claim": False,
            "ordered_structs": [
                "task_conf_info_t",
                "sub_task_conf_info_t",
                "exeBlock_conf_info_t",
            ],
            "required_proof_artifacts": [
                "decoded_task_conf_info_t_rows.json",
                "decoded_sub_task_conf_info_t_rows.json",
                "decoded_exeBlock_conf_info_t_rows.json",
                "decoded_task_subtask_exeblock_order.json",
                "runtime_start_wait_trace.json",
            ],
            "missing_fields": [
                "decoded_task_subtask_exeblock_order",
                "runtime_start_wait_trace",
                "task_subtask_successor_roundtrip",
                "exeBlock_instruction_range_roundtrip",
            ],
            "closed_blockers": [],
            "blockers": [
                "runtime_order_decoded_roundtrip_missing",
                "runtime_start_wait_trace_missing",
            ],
            "proof_scope": (
                "decoded_roundtrip_missing;does_not_prove_start_wait_trace_or_runtime"
            ),
        }

    task_records = list(task_artifact.row_records)
    subtask_records = list(subtask_artifact.row_records)
    exeblock_records = list(exeblock_artifact.row_records)
    subtask_by_key = {
        (record.get("task_idx"), record.get("subtask_idx")): record
        for record in subtask_records
    }
    exeblock_by_component = {
        record.get("component_index"): record for record in exeblock_records
    }

    task_active_blockers: list[str] = []
    start_end_blockers: list[str] = []
    successor_blockers: list[str] = []
    embedded_blockers: list[str] = []
    instance_blockers: list[str] = []
    instruction_range_blockers: list[str] = []
    wait_dependency_blockers: list[str] = []
    leaf_policy_blockers: list[str] = []
    active_chains: list[dict[str, object]] = []

    for task in task_records:
        task_idx = task.get("task_idx")
        amount = task.get("subtasks_amount")
        subtask_slots = tuple(task.get("subtasks_idx", ()))
        if not isinstance(amount, int) or amount <= 0:
            task_active_blockers.append(
                f"task_{task_idx}:invalid_active_subtask_amount={amount!r}"
            )
            continue
        active_subtasks = tuple(subtask_slots[:amount])
        if len(active_subtasks) != amount:
            task_active_blockers.append(
                f"task_{task_idx}:active_subtask_slots_truncated"
            )
            continue
        chain_rows: list[dict[str, object]] = []
        for subtask_idx in active_subtasks:
            subtask = subtask_by_key.get((task_idx, subtask_idx))
            if subtask is None:
                task_active_blockers.append(
                    f"task_{task_idx}:subtask_{subtask_idx}_missing"
                )
                continue
            chain_rows.append(subtask)
        if len(chain_rows) != len(active_subtasks):
            continue

        for position, subtask in enumerate(chain_rows):
            subtask_idx = subtask.get("subtask_idx")
            expected_start = position == 0
            expected_end = position == len(chain_rows) - 1
            if bool(subtask.get("is_exe_start")) is not expected_start:
                start_end_blockers.append(
                    f"task_{task_idx}:subtask_{subtask_idx}_start_flag_unexpected"
                )
            if bool(subtask.get("is_exe_end")) is not expected_end:
                start_end_blockers.append(
                    f"task_{task_idx}:subtask_{subtask_idx}_end_flag_unexpected"
                )
            successor_slots = tuple(subtask.get("suc_subtasks", ()))
            if expected_end:
                if any(int(slot) != 0 for slot in successor_slots):
                    successor_blockers.append(
                        f"task_{task_idx}:subtask_{subtask_idx}_terminal_successor_nonzero"
                    )
            else:
                expected_successor = active_subtasks[position + 1]
                if expected_successor not in successor_slots:
                    successor_blockers.append(
                        "task_%s:subtask_%s_missing_successor_%s"
                        % (task_idx, subtask_idx, expected_successor)
                    )

        active_chains.append(
            {
                "task_idx": task_idx,
                "active_subtasks": active_subtasks,
                "subtask_order": [
                    {
                        "subtask_idx": subtask.get("subtask_idx"),
                        "is_exe_start": subtask.get("is_exe_start"),
                        "is_exe_end": subtask.get("is_exe_end"),
                        "suc_subtasks": tuple(subtask.get("suc_subtasks", ())),
                    }
                    for subtask in chain_rows
                ],
            }
        )

    for subtask in subtask_records:
        task_idx = subtask.get("task_idx")
        subtask_idx = subtask.get("subtask_idx")
        instances_amount = subtask.get("instances_amount")
        address = subtask.get("instances_conf_mem_based_addr")
        if instances_amount == 0 and address != 0:
            instance_blockers.append(
                f"task_{task_idx}:subtask_{subtask_idx}_zero_instance_address_nonzero"
            )
        if instances_amount != 0:
            instance_blockers.append(
                f"task_{task_idx}:subtask_{subtask_idx}_nonzero_instance_count_unproven"
            )
        embedded_indices = tuple(subtask.get("embedded_exeblock_component_indices", ()))
        embedded_count = subtask.get("embedded_exeblock_count")
        block_amount = subtask.get("block_amount")
        if embedded_count != len(embedded_indices) or block_amount != len(embedded_indices):
            embedded_blockers.append(
                "task_%s:subtask_%s_embedded_count_mismatch"
                % (task_idx, subtask_idx)
            )
        for component_index in embedded_indices:
            exeblock = exeblock_by_component.get(component_index)
            if exeblock is None:
                embedded_blockers.append(
                    "task_%s:subtask_%s_embedded_exeblock_%s_missing"
                    % (task_idx, subtask_idx, component_index)
                )
                continue
            if exeblock.get("task_idx") != task_idx:
                embedded_blockers.append(
                    "task_%s:subtask_%s_embedded_exeblock_%s_task_mismatch"
                    % (task_idx, subtask_idx, component_index)
                )
            if exeblock.get("subtask_idx") != subtask_idx:
                embedded_blockers.append(
                    "task_%s:subtask_%s_embedded_exeblock_%s_subtask_mismatch"
                    % (task_idx, subtask_idx, component_index)
                )

    inst_row_size = 304
    instruction_offsets: list[int] = []
    for exeblock in exeblock_records:
        offset = exeblock.get("inst_mem_based_addr")
        if not isinstance(offset, int):
            instruction_range_blockers.append(
                "exeblock_%s_inst_mem_based_addr_not_int"
                % exeblock.get("component_index")
            )
            continue
        if offset < 0 or offset % inst_row_size:
            instruction_range_blockers.append(
                "exeblock_%s_inst_mem_based_addr_not_304_byte_aligned=%s"
                % (exeblock.get("component_index"), offset)
            )
        instruction_offsets.append(offset)

        predecessors = exeblock.get("predecessors")
        successors = exeblock.get("successors")
        predecessor_count = _endpoint_valid_count_from_record(predecessors)
        successor_count = _endpoint_valid_count_from_record(successors)
        if predecessor_count is None:
            wait_dependency_blockers.append(
                "exeblock_%s_predecessor_endpoint_records_missing"
                % exeblock.get("component_index")
            )
        elif exeblock.get("req_activations") != predecessor_count:
            wait_dependency_blockers.append(
                "exeblock_%s_req_activations_%s_expected_%s"
                % (
                    exeblock.get("component_index"),
                    exeblock.get("req_activations"),
                    predecessor_count,
                )
            )
        if successor_count is None:
            wait_dependency_blockers.append(
                "exeblock_%s_successor_endpoint_records_missing"
                % exeblock.get("component_index")
            )
        elif exeblock.get("child_amount") != successor_count:
            wait_dependency_blockers.append(
                "exeblock_%s_child_amount_%s_expected_%s"
                % (
                    exeblock.get("component_index"),
                    exeblock.get("child_amount"),
                    successor_count,
                )
            )
        if predecessor_count is not None and successor_count is not None:
            predecessor_components = tuple(
                exeblock.get("predecessor_component_indices", ())
            )
            successor_components = tuple(
                exeblock.get("successor_component_indices", ())
            )
            if predecessor_count != len(predecessor_components):
                wait_dependency_blockers.append(
                    "exeblock_%s_predecessor_count_%s_source_edges_%s"
                    % (
                        exeblock.get("component_index"),
                        predecessor_count,
                        len(predecessor_components),
                    )
                )
            if successor_count != len(successor_components):
                wait_dependency_blockers.append(
                    "exeblock_%s_successor_count_%s_source_edges_%s"
                    % (
                        exeblock.get("component_index"),
                        successor_count,
                        len(successor_components),
                    )
                )

            expected_leaf = successor_count == 0
            if exeblock.get("is_leaf_candidate") is not expected_leaf:
                leaf_policy_blockers.append(
                    "exeblock_%s_is_leaf_candidate_%s_expected_%s"
                    % (
                        exeblock.get("component_index"),
                        exeblock.get("is_leaf_candidate"),
                        expected_leaf,
                    )
                )
            if exeblock.get("is_leaf_serialized") != 0:
                leaf_policy_blockers.append(
                    "exeblock_%s_debug_leaf_serialization_not_zero"
                    % exeblock.get("component_index")
                )

    proof_statuses = {
        "task_active_subtask_order": (
            "available" if not task_active_blockers else "blocked"
        ),
        "task_start_end_policy": (
            "available" if not start_end_blockers else "blocked"
        ),
        "subtask_successor_order": (
            "available" if not successor_blockers else "blocked"
        ),
        "embedded_exeblock_roundtrip": (
            "available" if not embedded_blockers else "blocked"
        ),
        "instance_table_address_roundtrip": (
            "available" if not instance_blockers else "blocked"
        ),
        "exeBlock_instruction_range_roundtrip": (
            "available" if not instruction_range_blockers else "blocked"
        ),
        "exeBlock_wait_or_dependency_flags": (
            "available_debug_structural_dependency_policy"
            if not wait_dependency_blockers
            else "blocked"
        ),
        "exeBlock_is_leaf_policy": (
            "available_debug_conservative_zero_policy"
            if not leaf_policy_blockers
            else "blocked"
        ),
        "runtime_start_wait_trace": "blocked_missing_runtime_trace",
    }
    blocker_map = {
        "task_active_subtask_order_proof_missing": task_active_blockers,
        "task_start_end_runtime_policy_unproven": start_end_blockers,
        "subtask_successor_order_proof_missing": successor_blockers,
        "embedded_exeblock_roundtrip_missing": embedded_blockers,
        "instance_table_address_roundtrip_missing": instance_blockers,
        "exeBlock_instruction_range_roundtrip_missing": instruction_range_blockers,
        "exeBlock_wait_or_dependency_flags_unproven": wait_dependency_blockers,
        "exeBlock_is_leaf_policy_unproven": leaf_policy_blockers,
    }
    closed_blockers = [
        blocker for blocker, details in blocker_map.items() if not details
    ]
    local_blockers = [
        blocker for blocker, details in blocker_map.items() if details
    ]
    remaining_blockers = local_blockers + ["runtime_start_wait_trace_missing"]
    local_order_policy_claim = not local_blockers
    return {
        "schema_version": 1,
        "artifact_kind": "gemm_no_relu_micc_runtime_order_proof_plan",
        "status": (
            "decoded_wait_leaf_policy_available_runtime_trace_missing"
            if local_order_policy_claim
            else "decoded_order_available_start_wait_trace_missing"
        ),
        "runtime_ready_candidate": False,
        "row_bytes_claim": struct_bytes_available,
        "decoded_struct_roundtrip_claim": True,
        "local_order_policy_claim": local_order_policy_claim,
        "runtime_start_wait_trace_claim": False,
        "ordered_structs": [
            "task_conf_info_t",
            "sub_task_conf_info_t",
            "exeBlock_conf_info_t",
        ],
        "required_proof_artifacts": [
            "decoded_task_conf_info_t_rows.json",
            "decoded_sub_task_conf_info_t_rows.json",
            "decoded_exeBlock_conf_info_t_rows.json",
            "decoded_task_subtask_exeblock_order.json",
            "runtime_start_wait_trace.json",
        ],
        "proof_statuses": proof_statuses,
        "closed_blockers": closed_blockers,
        "missing_fields": [
            "runtime_start_wait_trace",
        ],
        "blockers": remaining_blockers,
        "active_chains": active_chains,
        "instruction_range_contract": {
            "inst_mem_based_addr_unit": "bytes",
            "inst_t_row_size_bytes": inst_row_size,
            "distinct_offsets": sorted(set(instruction_offsets)),
            "offset_count": len(instruction_offsets),
            "alignment_claim": not instruction_range_blockers,
        },
        "local_blocker_details": {
            key: details for key, details in blocker_map.items() if details
        },
        "wait_dependency_policy_proof": {
            "status": (
                "available_debug_structural_dependency_policy"
                if not wait_dependency_blockers
                else "blocked"
            ),
            "scope": (
                "decoded exeBlock req_activations/child_amount match "
                "predecessor/successor endpoint valid counts and source edge counts"
            ),
            "runtime_runnable_claim": False,
        },
        "is_leaf_policy_proof": {
            "status": (
                "available_debug_conservative_zero_policy"
                if not leaf_policy_blockers
                else "blocked"
            ),
            "scope": (
                "topological leaf is derived from successor count; debug writer "
                "still serializes is_leaf as conservative zero and does not claim "
                "final MICC runtime semantics"
            ),
            "runtime_runnable_claim": False,
        },
        "proof_scope": (
            "decoded_struct_order_wait_leaf_policy_only;"
            "does_not_prove_runtime_start_wait_trace_or_final_micc_file"
        ),
    }


def _gemm_no_relu_micc_final_section(
    *,
    artifact: "MiccComponentWriterArtifact",
    section: str,
    final_role: str,
    required_decoded_fields: tuple[str, ...],
    required_proof_artifacts: tuple[str, ...],
    blockers: tuple[str, ...],
) -> dict[str, Any]:
    diagnostic_count = len(artifact.diagnostics)
    payload_size = len(artifact.payload)
    struct_bytes_available = (
        artifact.struct_name == final_role
        and payload_size > 0
        and diagnostic_count == 0
    )
    decoded_roundtrip = _build_micc_decoded_roundtrip_proof_plan(artifact)
    decoded_available = _decoded_roundtrip_claim(decoded_roundtrip)
    status = (
        "decoded_roundtrip_available_runtime_trace_missing"
        if struct_bytes_available and decoded_available
        else
        "struct_bytes_available_final_proof_missing"
        if struct_bytes_available
        else "blocked_missing_struct_bytes"
    )
    section_blockers = list(blockers)
    if decoded_available:
        section_blockers = [
            blocker
            for blocker in section_blockers
            if not blocker.startswith("decoded_")
        ]
    if artifact.struct_name != final_role:
        section_blockers.append("unexpected_struct_name=%s" % artifact.struct_name)
    if payload_size <= 0:
        section_blockers.append("payload_bytes_missing")
    if diagnostic_count:
        section_blockers.append("diagnostics_present=%d" % diagnostic_count)
    return {
        "section": section,
        "struct_name": artifact.struct_name,
        "final_role": final_role,
        "status": status,
        "struct_bytes_available": struct_bytes_available,
        "runtime_ready_candidate": False,
        "row_bytes_claim": struct_bytes_available,
        "decoded_roundtrip_claim": decoded_available,
        "writer_status": artifact.writer_status,
        "row_count": artifact.row_count,
        "record_size_bytes": artifact.record_size_bytes,
        "payload_size_bytes": payload_size,
        "required_decoded_fields": list(required_decoded_fields),
        "required_proof_artifacts": list(required_proof_artifacts),
        "decoded_roundtrip_proof_plan": decoded_roundtrip,
        "blockers": section_blockers,
    }


def _decoded_roundtrip_claim(proof_plan: object) -> bool:
    return (
        isinstance(proof_plan, dict)
        and proof_plan.get("decoded_roundtrip_claim") is True
        and proof_plan.get("row_bytes_claim") is True
    )


def _build_micc_decoded_roundtrip_proof_plan(
    artifact: "MiccComponentWriterArtifact",
) -> dict[str, object]:
    if artifact.struct_name == TASK_CONF_INFO_STRUCT:
        return _decode_task_conf_info_roundtrip(artifact)
    if artifact.struct_name == SUB_TASK_CONF_INFO_STRUCT:
        return _decode_sub_task_conf_info_roundtrip(artifact)
    if artifact.struct_name == EXEBLOCK_CONF_INFO_STRUCT:
        return _decode_exeBlock_conf_info_roundtrip(artifact)
    return {
        "schema_version": 1,
        "artifact_kind": "micc_decoded_roundtrip_proof_plan",
        "struct_name": artifact.struct_name,
        "status": "blocked_unknown_micc_struct",
        "row_bytes_claim": False,
        "decoded_roundtrip_claim": False,
        "runtime_runnable_claim": False,
        "proof_blockers": [
            {"blocker_id": "unknown_micc_struct_for_decode_roundtrip"},
        ],
    }


def _decode_task_conf_info_roundtrip(
    artifact: "MiccComponentWriterArtifact",
) -> dict[str, object]:
    decoded_rows: list[dict[str, object]] = []
    blockers = _decode_common_blockers(artifact, TASK_CONF_INFO_RECORD_SIZE)
    if not blockers:
        for row_index, chunk in enumerate(
            _record_chunks(artifact.payload, TASK_CONF_INFO_RECORD_SIZE)
        ):
            values = struct.unpack(TASK_CONF_INFO_FORMAT, chunk)
            record = artifact.row_records[row_index]
            decoded = {
                "row_index": row_index,
                "is_exe_start": values[0],
                "is_exe_end": values[1],
                "subtasks_amount": values[2],
                "execute_times": values[3],
                "subtasks_idx": tuple(values[4 : 4 + MAX_SUBTASK_SLOTS]),
                "suc_tasks": tuple(values[4 + MAX_SUBTASK_SLOTS :]),
            }
            decoded_rows.append(decoded)
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "subtasks_amount",
                decoded["subtasks_amount"],
                record.get("subtasks_amount"),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "execute_times",
                decoded["execute_times"],
                record.get("execute_times"),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "subtasks_idx",
                decoded["subtasks_idx"],
                tuple(record.get("subtasks_idx", ())),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "suc_tasks",
                decoded["suc_tasks"],
                tuple(record.get("suc_tasks", ())),
            )
    return _decoded_roundtrip_plan(
        artifact,
        decoded_rows=decoded_rows,
        blockers=blockers,
        decoded_fields=(
            "is_exe_start",
            "is_exe_end",
            "subtasks_amount",
            "execute_times",
            "subtasks_idx",
            "suc_tasks",
        ),
    )


def _decode_sub_task_conf_info_roundtrip(
    artifact: "MiccComponentWriterArtifact",
) -> dict[str, object]:
    decoded_rows: list[dict[str, object]] = []
    blockers = _decode_common_blockers(artifact, SUB_TASK_CONF_INFO_RECORD_SIZE)
    if not blockers:
        for row_index, chunk in enumerate(
            _record_chunks(artifact.payload, SUB_TASK_CONF_INFO_RECORD_SIZE)
        ):
            header = struct.unpack(
                SUB_TASK_CONF_INFO_HEADER_FORMAT,
                chunk[:SUB_TASK_EMBEDDED_EXEBLOCK_OFFSET],
            )
            trailer_offset = SUB_TASK_CONF_INFO_RECORD_SIZE - struct.calcsize(
                SUB_TASK_CONF_INFO_TRAILER_FORMAT
            )
            trailer = struct.unpack(
                SUB_TASK_CONF_INFO_TRAILER_FORMAT,
                chunk[trailer_offset:SUB_TASK_CONF_INFO_RECORD_SIZE],
            )
            record = artifact.row_records[row_index]
            active_block_amount = int(header[9])
            active_embedded_bytes = active_block_amount * EXEBLOCK_CONF_INFO_RECORD_SIZE
            embedded_end = SUB_TASK_EMBEDDED_EXEBLOCK_OFFSET + active_embedded_bytes
            decoded = {
                "row_index": row_index,
                "is_exe_start": header[0],
                "is_exe_end": header[1],
                "instances_amount": header[2],
                "instances_conf_mem_based_addr": header[3],
                "suc_subtasks": tuple(header[4:8]),
                "root_block_amount": header[8],
                "block_amount": header[9],
                "subtask_idx": trailer[0],
                "task_idx": trailer[1],
                "active_embedded_exeBlock_count": active_block_amount,
                "active_embedded_exeBlock_bytes": active_embedded_bytes,
            }
            decoded_rows.append(decoded)
            if embedded_end > trailer_offset:
                blockers.append(
                    "%s:row_%d_embedded_exeBlock_region_overflows"
                    % (artifact.struct_name, row_index)
                )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "instances_amount",
                decoded["instances_amount"],
                record.get("instances_amount"),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "instances_conf_mem_based_addr",
                decoded["instances_conf_mem_based_addr"],
                record.get("instances_conf_mem_based_addr"),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "suc_subtasks",
                decoded["suc_subtasks"],
                tuple(record.get("suc_subtasks", ())),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "root_block_amount",
                decoded["root_block_amount"],
                record.get("root_block_amount"),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "block_amount",
                decoded["block_amount"],
                record.get("block_amount"),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "subtask_idx",
                decoded["subtask_idx"],
                record.get("subtask_idx"),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "task_idx",
                decoded["task_idx"],
                record.get("task_idx"),
            )
    return _decoded_roundtrip_plan(
        artifact,
        decoded_rows=decoded_rows,
        blockers=blockers,
        decoded_fields=(
            "is_exe_start",
            "is_exe_end",
            "instances_amount",
            "instances_conf_mem_based_addr",
            "suc_subtasks",
            "root_block_amount",
            "block_amount",
            "subtask_idx",
            "task_idx",
            "active_embedded_exeBlock_count",
        ),
    )


def _decode_exeBlock_conf_info_roundtrip(
    artifact: "MiccComponentWriterArtifact",
) -> dict[str, object]:
    decoded_rows: list[dict[str, object]] = []
    blockers = _decode_common_blockers(artifact, EXEBLOCK_CONF_INFO_RECORD_SIZE)
    header_size = struct.calcsize(EXEBLOCK_CONF_INFO_HEADER_FORMAT)
    if not blockers:
        for row_index, chunk in enumerate(
            _record_chunks(artifact.payload, EXEBLOCK_CONF_INFO_RECORD_SIZE)
        ):
            header = struct.unpack(
                EXEBLOCK_CONF_INFO_HEADER_FORMAT,
                chunk[:header_size],
            )
            inner = struct.unpack(EXEBLOCK_CONF_FORMAT, chunk[header_size:])
            record = artifact.row_records[row_index]
            decoded = {
                "row_index": row_index,
                "valid": header[0],
                "block_idx": inner[51],
                "header_block_idx": header[1],
                "pe_dst": {"x": header[2], "y": header[3], "z": header[4]},
                "priority": header[5],
                "req_activations": inner[0],
                "has_stages": tuple(inner[1:6]),
                "stages_start_pc": tuple(inner[6:11]),
                "predecessors": tuple(inner[11:31]),
                "successors": tuple(inner[31:51]),
                "subtask_idx": inner[52],
                "task_idx": inner[53],
                "instances_amount": inner[54],
                "child_amount": inner[55],
                "block_class": inner[56],
                "inst_mem_based_addr": inner[57],
                "stage_inst_amounts": tuple(inner[58:62]),
                "is_leaf": inner[62],
            }
            decoded_rows.append(decoded)
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "header_block_idx",
                decoded["header_block_idx"],
                record.get("block_idx"),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "block_idx",
                decoded["block_idx"],
                record.get("block_idx"),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "task_idx",
                decoded["task_idx"],
                record.get("task_idx"),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "subtask_idx",
                decoded["subtask_idx"],
                record.get("subtask_idx"),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "pe_dst",
                decoded["pe_dst"],
                record.get("pe_dst"),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "req_activations",
                decoded["req_activations"],
                record.get("req_activations"),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "child_amount",
                decoded["child_amount"],
                record.get("child_amount"),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "inst_mem_based_addr",
                decoded["inst_mem_based_addr"],
                record.get("inst_mem_based_addr"),
            )
            _expect_decoded_value(
                blockers,
                artifact.struct_name,
                row_index,
                "is_leaf",
                decoded["is_leaf"],
                record.get("is_leaf_serialized"),
            )
    return _decoded_roundtrip_plan(
        artifact,
        decoded_rows=decoded_rows,
        blockers=blockers,
        decoded_fields=(
            "valid",
            "block_idx",
            "pe_dst",
            "priority",
            "req_activations",
            "has_stages",
            "stages_start_pc",
            "predecessors",
            "successors",
            "subtask_idx",
            "task_idx",
            "instances_amount",
            "child_amount",
            "block_class",
            "inst_mem_based_addr",
            "stage_inst_amounts",
            "is_leaf",
        ),
    )


def _decode_common_blockers(
    artifact: "MiccComponentWriterArtifact",
    record_size: int,
) -> list[str]:
    blockers: list[str] = []
    if artifact.writer_status != "debug_only":
        blockers.append("%s:writer_status_not_debug_only" % artifact.struct_name)
    if artifact.diagnostics:
        blockers.append("%s:diagnostics_present" % artifact.struct_name)
    if not artifact.payload:
        blockers.append("%s:payload_missing" % artifact.struct_name)
    if artifact.record_size_bytes != record_size:
        blockers.append(
            "%s:record_size_mismatch=%s" % (
                artifact.struct_name,
                artifact.record_size_bytes,
            )
        )
    if artifact.payload and len(artifact.payload) % record_size:
        blockers.append("%s:payload_not_record_aligned" % artifact.struct_name)
    if artifact.payload and len(artifact.payload) // record_size != artifact.row_count:
        blockers.append("%s:row_count_mismatch" % artifact.struct_name)
    if artifact.row_count != len(artifact.row_records):
        blockers.append("%s:row_record_count_mismatch" % artifact.struct_name)
    return blockers


def _record_chunks(payload: bytes, record_size: int):
    for offset in range(0, len(payload), record_size):
        yield payload[offset : offset + record_size]


def _expect_decoded_value(
    blockers: list[str],
    struct_name: str,
    row_index: int,
    field: str,
    actual: object,
    expected: object,
) -> None:
    if actual != expected:
        blockers.append(
            "%s:row_%d_%s_roundtrip_mismatch=%r!=%r"
            % (struct_name, row_index, field, actual, expected)
        )


def _decoded_roundtrip_plan(
    artifact: "MiccComponentWriterArtifact",
    *,
    decoded_rows: list[dict[str, object]],
    blockers: list[str],
    decoded_fields: tuple[str, ...],
) -> dict[str, object]:
    decoded = not blockers
    return {
        "schema_version": 1,
        "artifact_kind": "micc_decoded_roundtrip_proof_plan",
        "struct_name": artifact.struct_name,
        "status": (
            "decoded_roundtrip_available"
            if decoded
            else "blocked_missing_decoded_roundtrip"
        ),
        "row_bytes_claim": bool(artifact.payload) and not artifact.diagnostics,
        "decoded_roundtrip_claim": decoded,
        "runtime_runnable_claim": False,
        "decoded_row_count": len(decoded_rows),
        "expected_row_count": artifact.row_count,
        "record_size_bytes": artifact.record_size_bytes,
        "decoded_fields": list(decoded_fields),
        "decoded_rows_sample": decoded_rows[:8],
        "decoded_rows_omitted": max(0, len(decoded_rows) - 8),
        "proof_blockers": [
            {"blocker_id": blocker}
            for blocker in _dedupe_strings(blockers)
        ],
        "proof_scope": (
            "local_struct_pack_unpack_roundtrip_only;"
            "does_not_claim_final_micc_file_or_runtime_start_wait"
        ),
    }


def _dedupe_strings(items: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


@dataclass(frozen=True)
class InstanceTableAddress:
    """Address of one subtask's first ``instance_conf_info_t`` row."""

    task_idx: int
    subtask_idx: int
    row_index: int
    instances_amount: int
    addr_space: str = INSTANCE_TABLE_ADDR_SPACE
    unit: str = INSTANCE_TABLE_ADDR_UNIT
    record_size_bytes: int = INSTANCE_CONF_INFO_RECORD_SIZE

    def __post_init__(self) -> None:
        if self.task_idx < 0:
            raise ValueError("task_idx must be non-negative")
        if self.subtask_idx < 0:
            raise ValueError("subtask_idx must be non-negative")
        if self.row_index < 0:
            raise ValueError("row_index must be non-negative")
        if self.instances_amount < 0:
            raise ValueError("instances_amount must be non-negative")
        if self.record_size_bytes != INSTANCE_CONF_INFO_RECORD_SIZE:
            raise ValueError("instance table row size must stay 32 bytes")

    @property
    def byte_offset(self) -> int:
        return self.row_index * self.record_size_bytes

    @property
    def address(self) -> int:
        if self.instances_amount == 0:
            return 0
        return self.byte_offset

    def to_plan(self) -> dict[str, object]:
        return {
            "task_idx": self.task_idx,
            "subtask_idx": self.subtask_idx,
            "addr_space": self.addr_space,
            "unit": self.unit,
            "row_index": self.row_index,
            "record_size_bytes": self.record_size_bytes,
            "byte_offset": self.byte_offset,
            "address": self.address,
            "instances_amount": self.instances_amount,
            "zero_instance_rule": "instances_amount==0 => address=0",
            "byte_offset_formula": "row_index * 32",
            "source_evidence": [
                "docs/runtime/data/micc.md: instances_conf_mem_based_addr is an 8-byte instance table offset",
                "docs/runtime/data/cbuf.md: instance_conf_info_t is 32 bytes",
                "docs/compiler/binary_packaging/README.md: active rows and padded capacity stay separate",
                "compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py: active subtasks are selected by subtasks_amount/subtasks_idx",
            ],
        }


@dataclass(frozen=True)
class InstanceTableAddressPlan:
    """Writer-local view of subtask to instance table addressing."""

    profile_id: str
    addresses: tuple[InstanceTableAddress, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_instance_table_address_plan",
            "profile_id": self.profile_id,
            "addr_space": INSTANCE_TABLE_ADDR_SPACE,
            "unit": INSTANCE_TABLE_ADDR_UNIT,
            "record_size_bytes": INSTANCE_CONF_INFO_RECORD_SIZE,
            "addresses": [address.to_plan() for address in self.addresses],
            "diagnostics": [
                diagnostic.to_plan() for diagnostic in self.diagnostics
            ],
            "evidence_report": _writer_evidence("InstanceTableAddress"),
            "layering_policy": (
                "writer_local_address_derivation_consumes_component_rows;"
                "does_not_mutate_frontend_or_vendor_component_plan"
            ),
        }


@dataclass(frozen=True)
class SubtaskInstanceSemanticsRecord:
    """One subtask's instance-count representation decision."""

    component_index: int | None
    task_idx: int | None
    subtask_idx: int | None
    subtask_slot: str
    classification: str
    candidate_instances_amount: int | None
    derived_active_instance_count: int | None
    folded_candidate_instances_amount: int | None
    selected_representation: str
    selected_instances_amount: int | None
    selection_policy: str
    selection_status: str
    address: int | None
    address_policy: str
    blocker_severity: str
    blocker_code: str | None
    blocker_message: str | None
    candidate_policy: str | None
    folded_policy: str | None

    def to_plan(self) -> dict[str, object]:
        return {
            "component_index": self.component_index,
            "task_idx": self.task_idx,
            "subtask_idx": self.subtask_idx,
            "subtask_slot": self.subtask_slot,
            "classification": self.classification,
            "candidate_instances_amount": self.candidate_instances_amount,
            "derived_active_instance_count": self.derived_active_instance_count,
            "folded_candidate_instances_amount": (
                self.folded_candidate_instances_amount
            ),
            "selected_representation": self.selected_representation,
            "selected_instances_amount": self.selected_instances_amount,
            "selection_policy": self.selection_policy,
            "selection_status": self.selection_status,
            "address": self.address,
            "address_policy": self.address_policy,
            "address_invariant": (
                "instances_amount==0 => address=0 ignored; "
                "instances_amount>0 and address=0 => row0"
            ),
            "blocker_severity": self.blocker_severity,
            "blocker_code": self.blocker_code,
            "blocker_message": self.blocker_message,
            "candidate_policy": self.candidate_policy,
            "folded_policy": self.folded_policy,
        }


@dataclass(frozen=True)
class SubtaskInstanceRepresentationSelection:
    """Explicit selected representation for subtask instance semantics."""

    profile_id: str
    records: tuple[SubtaskInstanceSemanticsRecord, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def selection_complete(self) -> bool:
        return not self.diagnostics and all(
            record.selection_status == "selected" for record in self.records
        )

    def to_plan(self) -> dict[str, object]:
        incomplete = [
            record.to_plan()
            for record in self.records
            if record.selection_status != "selected"
        ]
        return {
            "schema_version": 1,
            "artifact": "b_line_subtask_instance_representation_selection",
            "profile_id": self.profile_id,
            "selection_complete": self.selection_complete,
            "selection_status": (
                "complete" if self.selection_complete else "blocked"
            ),
            "record_count": len(self.records),
            "selected_record_count": len(self.records) - len(incomplete),
            "incomplete_record_count": len(incomplete),
            "selected_representation_counts": _record_value_counts(
                self.records,
                "selected_representation",
            ),
            "selection_policy_counts": _record_value_counts(
                self.records,
                "selection_policy",
            ),
            "records": [record.to_plan() for record in self.records],
            "incomplete_records": incomplete,
            "selection_rules": {
                "zero_instance_control": (
                    "non-k-stream subtasks with derived active instance count "
                    "0 select instances_amount=0 and address=0 ignored, only "
                    "when no active instance rows exist"
                ),
                "folded_k_stream_explicit": (
                    "k-stream subtasks may select folded_k_stream only when "
                    "the folded overlay count matches the derived active "
                    "instance count"
                ),
                "no_implicit_mixing": (
                    "folded_k_stream selection is explicit; writer does not "
                    "silently combine expanded candidate counts with folded "
                    "overlay counts"
                ),
                "address_invariant": (
                    "instances_amount==0 => address=0 ignored; "
                    "instances_amount>0 and address=0 => row0"
                ),
            },
            "diagnostics": [
                diagnostic.to_plan() for diagnostic in self.diagnostics
            ],
            "evidence_report": _writer_evidence(
                "SubtaskInstanceRepresentationSelection"
            ),
            "layering_policy": (
                "representation_selection_consumes_component_rows;"
                "does_not_rewrite_candidates_or_emit_runtime_bytes"
            ),
        }


@dataclass(frozen=True)
class SubtaskInstanceSemanticsReport:
    """Fail-closed representation report for subtask instance semantics."""

    profile_id: str
    records: tuple[SubtaskInstanceSemanticsRecord, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    @property
    def selection(self) -> SubtaskInstanceRepresentationSelection:
        return SubtaskInstanceRepresentationSelection(
            profile_id=self.profile_id,
            records=self.records,
            diagnostics=self.diagnostics,
        )

    @property
    def selection_complete(self) -> bool:
        return self.selection.selection_complete

    @property
    def runtime_ready_candidate(self) -> bool:
        return False

    def to_plan(self) -> dict[str, object]:
        blockers = [
            record.to_plan()
            for record in self.records
            if record.blocker_severity == "error"
        ]
        return {
            "schema_version": 1,
            "artifact": "b_line_subtask_instance_semantics_report",
            "profile_id": self.profile_id,
            "selection_complete": self.selection_complete,
            "selection_status": (
                "complete" if self.selection_complete else "blocked"
            ),
            "runtime_ready_candidate": self.runtime_ready_candidate,
            "runtime_ready_status": (
                "runtime_bytes_deferred"
                if self.selection_complete
                else "selection_blocked"
            ),
            "record_count": len(self.records),
            "blocked_subtask_count": len(blockers),
            "selected_subtask_count": sum(
                1
                for record in self.records
                if record.selection_status == "selected"
            ),
            "records": [record.to_plan() for record in self.records],
            "blockers": blockers,
            "selection_artifact": self.selection.to_plan(),
            "representation_rules": {
                "expanded_allowed_when": (
                    "the selected sub_task_conf_info_candidate is internally "
                    "consistent: candidate instances_amount equals the "
                    "derived active instance table row count"
                ),
                "folded_k_stream_required_when": (
                    "classification is k_stream, a folded overlay exists whose "
                    "instances_amount equals the derived active instance count, "
                    "and the expanded candidate count does not match; the "
                    "selection must explicitly mark "
                    "selected_representation=folded_k_stream"
                ),
                "zero_instance_control_allowed_when": (
                    "classification is non_k_stream and the derived active "
                    "instance count is 0, proving there are no active instance "
                    "rows for the subtask"
                ),
                "no_implicit_mixing": (
                    "writer must not combine expanded candidate fields with "
                    "folded overlay instance counts or addresses"
                ),
                "address_invariant": (
                    "instances_amount==0 => address=0 ignored; "
                    "instances_amount>0 and address=0 => row0"
                ),
            },
            "remaining_runtime_gaps": [
                "sub_task_conf_info_t selected row records can be packed as "
                "runtime-shaped debug bytes, but remain debug-only",
                "selected subtask bytes are not a runnable vendor payload until "
                "package-level runtime-ready validation accepts the full bundle",
            ],
            "diagnostics": [
                diagnostic.to_plan() for diagnostic in self.diagnostics
            ],
            "evidence_report": _writer_evidence("SubtaskInstanceSemantics"),
            "layering_policy": (
                "subtask_instance_semantics_report_consumes_component_rows;"
                "does_not_rewrite_candidates_or_emit_binary_bytes"
            ),
        }


@dataclass(frozen=True)
class MiccComponentWriterArtifact:
    """Debug-only byte artifact for one MICC/control struct family."""

    profile_id: str
    component: str
    struct_name: str
    writer_status: str
    byte_order: str
    record_format: str
    row_count: int
    record_size_bytes: int
    payload: bytes
    row_records: tuple[dict[str, object], ...]
    address_records: tuple[dict[str, object], ...] = ()
    semantics_report: dict[str, object] | None = None
    diagnostics: tuple[Diagnostic, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_micc_component_writer_artifact",
            "profile_id": self.profile_id,
            "component": self.component,
            "struct_name": self.struct_name,
            "writer_status": self.writer_status,
            "byte_order": self.byte_order,
            "record_format": self.record_format,
            "row_count": self.row_count,
            "record_size_bytes": self.record_size_bytes,
            "payload_size_bytes": len(self.payload),
            "payload_hex": self.payload.hex(),
            "row_records": list(self.row_records),
            "address_records": list(self.address_records),
            "semantics_report": self.semantics_report,
            "diagnostics": [
                diagnostic.to_plan() for diagnostic in self.diagnostics
            ],
            "evidence_report": _writer_evidence(self.struct_name),
            "layering_policy": (
                "micc_component_writer_consumes_serializer_readiness_and_"
                "vendor_component_candidates;debug_only_not_runnable_package"
            ),
        }


def derive_instance_table_addresses(
    component_plan: VendorComponentPlan,
) -> InstanceTableAddressPlan:
    """Derive writer-local ``instances_conf_mem_based_addr`` candidates."""

    diagnostics: list[Diagnostic] = []
    rows_by_subtask: dict[tuple[int, int], list[dict[str, object]]] = {}
    for row in component_plan.instance_rows:
        task_idx = row.get("task_id")
        subtask_idx = row.get("subtask_idx")
        component_index = row.get("component_index")
        if (
            not isinstance(task_idx, int)
            or not isinstance(subtask_idx, int)
            or not isinstance(component_index, int)
        ):
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="invalid_instance_table_source_row",
                    subject_id=str(row.get("component_index")),
                    message=(
                        "instance row lacks concrete task_idx, subtask_idx, "
                        "or component_index"
                    ),
                )
            )
            continue
        rows_by_subtask.setdefault((task_idx, subtask_idx), []).append(row)

    addresses: list[InstanceTableAddress] = []
    for row in component_plan.subtask_rows:
        task_idx = row.get("task_id")
        subtask_idx = row.get("subtask_idx")
        if not isinstance(task_idx, int) or not isinstance(subtask_idx, int):
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="invalid_subtask_address_key",
                    subject_id=str(row.get("component_index")),
                    message="subtask row lacks concrete task_idx/subtask_idx",
                )
            )
            continue
        instance_rows = sorted(
            rows_by_subtask.get((task_idx, subtask_idx), ()),
            key=lambda item: int(item.get("component_index", -1)),
        )
        indices = [
            int(item["component_index"])
            for item in instance_rows
            if isinstance(item.get("component_index"), int)
        ]
        if not indices:
            addresses.append(
                InstanceTableAddress(
                    task_idx=task_idx,
                    subtask_idx=subtask_idx,
                    row_index=0,
                    instances_amount=0,
                )
            )
            continue
        first_index = indices[0]
        expected = list(range(first_index, first_index + len(indices)))
        if indices != expected:
            diagnostics.append(
                Diagnostic(
                    severity="error",
                    code="non_contiguous_instance_table_rows",
                    subject_id=f"task{task_idx}:subtask{subtask_idx}",
                    message=(
                        "instance rows for a subtask must be contiguous in "
                        f"component order; got {indices}, expected {expected}"
                    ),
                )
            )
        addresses.append(
            InstanceTableAddress(
                task_idx=task_idx,
                subtask_idx=subtask_idx,
                row_index=first_index,
                instances_amount=len(indices),
            )
        )
    return InstanceTableAddressPlan(
        profile_id=component_plan.profile_id,
        addresses=tuple(addresses),
        diagnostics=tuple(diagnostics),
    )


def build_subtask_instance_semantics_report(
    component_plan: VendorComponentPlan,
    *,
    address_plan: InstanceTableAddressPlan | None = None,
) -> SubtaskInstanceSemanticsReport:
    """Build a fail-closed report for subtask instance-count semantics."""

    if address_plan is None:
        address_plan = derive_instance_table_addresses(component_plan)
    address_by_key = {
        (address.task_idx, address.subtask_idx): address
        for address in address_plan.addresses
    }
    records: list[SubtaskInstanceSemanticsRecord] = []
    diagnostics = list(address_plan.diagnostics)
    for row in component_plan.subtask_rows:
        task_idx = _optional_int(row.get("task_id"))
        subtask_idx = _optional_int(row.get("subtask_idx"))
        subtask_slot = str(row.get("subtask_slot"))
        classification = _subtask_instance_classification(row)
        candidate = row.get("sub_task_conf_info_candidate")
        folded = row.get("folded_subtask_conf_candidate")
        candidate_amount = (
            _optional_int(candidate.get("instances_amount"))
            if isinstance(candidate, dict)
            else None
        )
        folded_amount = (
            _optional_int(folded.get("instances_amount"))
            if isinstance(folded, dict)
            else None
        )
        candidate_policy = (
            str(candidate.get("instances_amount_policy"))
            if isinstance(candidate, dict)
            and candidate.get("instances_amount_policy") is not None
            else None
        )
        folded_policy = (
            str(folded.get("instances_amount_policy"))
            if isinstance(folded, dict)
            and folded.get("instances_amount_policy") is not None
            else None
        )
        address = (
            address_by_key.get((task_idx, subtask_idx))
            if task_idx is not None and subtask_idx is not None
            else None
        )
        derived_count = address.instances_amount if address is not None else None
        (
            selected,
            selected_amount,
            selection_policy,
            selection_status,
            severity,
            code,
            message,
        ) = _select_subtask_representation(
            classification=classification,
            candidate_amount=candidate_amount,
            derived_count=derived_count,
            folded_amount=folded_amount,
        )
        records.append(
            SubtaskInstanceSemanticsRecord(
                component_index=_optional_int(row.get("component_index")),
                task_idx=task_idx,
                subtask_idx=subtask_idx,
                subtask_slot=subtask_slot,
                classification=classification,
                candidate_instances_amount=candidate_amount,
                derived_active_instance_count=derived_count,
                folded_candidate_instances_amount=folded_amount,
                selected_representation=selected,
                selected_instances_amount=selected_amount,
                selection_policy=selection_policy,
                selection_status=selection_status,
                address=address.address if address is not None else None,
                address_policy=_address_policy(address),
                blocker_severity=severity,
                blocker_code=code,
                blocker_message=message,
                candidate_policy=candidate_policy,
                folded_policy=folded_policy,
            )
        )
    return SubtaskInstanceSemanticsReport(
        profile_id=component_plan.profile_id,
        records=tuple(records),
        diagnostics=tuple(diagnostics),
    )


def emit_micc_task_conf_info_component(
    component_plan: VendorComponentPlan,
    readiness_plan: SerializerReadinessPlan,
) -> MiccComponentWriterArtifact:
    """Pack debug-only ``task_conf_info_t`` rows."""

    diagnostics = _base_diagnostics(
        component_plan,
        readiness_plan,
        TASK_CONF_INFO_STRUCT,
        require_packable=True,
    )
    row_records: list[dict[str, object]] = []
    chunks: list[bytes] = []
    if not _has_errors(diagnostics):
        for row in component_plan.task_rows:
            record, encoded, error = _pack_task_record(row)
            if error is not None:
                diagnostics.append(error)
                continue
            chunks.append(encoded)
            row_records.append(record)
    if _has_errors(diagnostics):
        return _blocked_artifact(
            component_plan,
            "task_rows",
            TASK_CONF_INFO_STRUCT,
            TASK_CONF_INFO_FORMAT,
            TASK_CONF_INFO_RECORD_SIZE,
            tuple(diagnostics),
        )
    return _emitted_artifact(
        component_plan,
        "task_rows",
        TASK_CONF_INFO_STRUCT,
        TASK_CONF_INFO_FORMAT,
        TASK_CONF_INFO_RECORD_SIZE,
        b"".join(chunks),
        tuple(row_records),
        tuple(diagnostics),
    )


def emit_micc_exeBlock_conf_info_component(
    component_plan: VendorComponentPlan,
    readiness_plan: SerializerReadinessPlan,
) -> MiccComponentWriterArtifact:
    """Pack debug-only ``exeBlock_conf_info_t`` rows."""

    diagnostics = _base_diagnostics(
        component_plan,
        readiness_plan,
        EXEBLOCK_CONF_INFO_STRUCT,
        require_packable=True,
    )
    row_records: list[dict[str, object]] = []
    chunks: list[bytes] = []
    if not _has_errors(diagnostics):
        for row in component_plan.exeblock_rows:
            record, encoded, error = _pack_exeblock_record(row)
            if error is not None:
                diagnostics.append(error)
                continue
            chunks.append(encoded)
            row_records.append(record)
    if _has_errors(diagnostics):
        return _blocked_artifact(
            component_plan,
            "exeblock_rows",
            EXEBLOCK_CONF_INFO_STRUCT,
            EXEBLOCK_CONF_INFO_HEADER_FORMAT + "+" + EXEBLOCK_CONF_FORMAT,
            EXEBLOCK_CONF_INFO_RECORD_SIZE,
            tuple(diagnostics),
        )
    return _emitted_artifact(
        component_plan,
        "exeblock_rows",
        EXEBLOCK_CONF_INFO_STRUCT,
        EXEBLOCK_CONF_INFO_HEADER_FORMAT + "+" + EXEBLOCK_CONF_FORMAT,
        EXEBLOCK_CONF_INFO_RECORD_SIZE,
        b"".join(chunks),
        tuple(row_records),
        tuple(diagnostics),
    )


def emit_micc_sub_task_conf_info_component(
    component_plan: VendorComponentPlan,
    readiness_plan: SerializerReadinessPlan,
) -> MiccComponentWriterArtifact:
    """Pack or fail-close ``sub_task_conf_info_t`` rows.

    The writer may select a representation for
    ``instances_amount``/``instances_conf_mem_based_addr`` from the
    ``InstanceTableAddress`` plan.  Selection completion is explicit and still
    does not imply runnable runtime bytes.
    """

    address_plan = derive_instance_table_addresses(component_plan)
    semantics_report = build_subtask_instance_semantics_report(
        component_plan,
        address_plan=address_plan,
    )
    diagnostics = _base_diagnostics(
        component_plan,
        readiness_plan,
        SUB_TASK_CONF_INFO_STRUCT,
        require_packable=False,
    )
    diagnostics.extend(semantics_report.diagnostics)
    diagnostics.extend(_subtask_semantics_diagnostics(semantics_report))
    diagnostics.extend(_subtask_readiness_diagnostics(readiness_plan))

    address_by_key = {
        (address.task_idx, address.subtask_idx): address
        for address in address_plan.addresses
    }
    exeblocks_by_index = {
        row.get("component_index"): row
        for row in component_plan.exeblock_rows
        if isinstance(row.get("component_index"), int)
    }
    row_records: list[dict[str, object]] = []
    chunks: list[bytes] = []
    if not _has_errors(diagnostics):
        if semantics_report.selection_complete:
            semantics_by_key = _subtask_semantics_by_key(semantics_report)
            for row in component_plan.subtask_rows:
                record, encoded, error = _pack_selected_subtask_record(
                    row,
                    semantics_by_key=semantics_by_key,
                    address_by_key=address_by_key,
                    exeblocks_by_index=exeblocks_by_index,
                )
                if error is not None:
                    diagnostics.append(error)
                    continue
                chunks.append(encoded)
                row_records.append(record)
        else:
            for row in component_plan.subtask_rows:
                record, encoded, error = _pack_subtask_record(
                    row,
                    address_by_key=address_by_key,
                    exeblocks_by_index=exeblocks_by_index,
                )
                if error is not None:
                    diagnostics.append(error)
                    continue
                chunks.append(encoded)
                row_records.append(record)
    address_records = tuple(address.to_plan() for address in address_plan.addresses)
    semantics_plan = semantics_report.to_plan()
    if _has_errors(diagnostics):
        return _blocked_artifact(
            component_plan,
            "subtask_rows",
            SUB_TASK_CONF_INFO_STRUCT,
            SUB_TASK_CONF_INFO_HEADER_FORMAT
            + "+"
            + f"{MAX_EXEBLOCKS_PER_SUBTASK}*"
            + EXEBLOCK_CONF_INFO_STRUCT
            + "+"
            + SUB_TASK_CONF_INFO_TRAILER_FORMAT,
            SUB_TASK_CONF_INFO_RECORD_SIZE,
            tuple(diagnostics),
            address_records=address_records,
            semantics_report=semantics_plan,
        )
    return _emitted_artifact(
        component_plan,
        "subtask_rows",
        SUB_TASK_CONF_INFO_STRUCT,
        SUB_TASK_CONF_INFO_HEADER_FORMAT
        + "+"
        + f"{MAX_EXEBLOCKS_PER_SUBTASK}*"
        + EXEBLOCK_CONF_INFO_STRUCT
        + "+"
        + SUB_TASK_CONF_INFO_TRAILER_FORMAT,
        SUB_TASK_CONF_INFO_RECORD_SIZE,
        b"".join(chunks),
        tuple(row_records),
        tuple(diagnostics),
        address_records=address_records,
        semantics_report=semantics_plan,
    )


def summarize_micc_component_writer_artifact(
    artifact: MiccComponentWriterArtifact,
) -> dict[str, object]:
    """Return stable counts for focused checks."""

    diagnostic_counts: dict[str, int] = {}
    for diagnostic in artifact.diagnostics:
        diagnostic_counts[diagnostic.severity] = (
            diagnostic_counts.get(diagnostic.severity, 0) + 1
        )
    return {
        "profile_id": artifact.profile_id,
        "component": artifact.component,
        "struct_name": artifact.struct_name,
        "writer_status": artifact.writer_status,
        "record_format": artifact.record_format,
        "row_count": artifact.row_count,
        "record_size_bytes": artifact.record_size_bytes,
        "payload_size_bytes": len(artifact.payload),
        "diagnostic_count": len(artifact.diagnostics),
        "diagnostic_severity_counts": dict(sorted(diagnostic_counts.items())),
        "address_record_count": len(artifact.address_records),
        "semantics_blocked_subtask_count": _semantics_blocker_count(
            artifact.semantics_report
        ),
        "runtime_ready_candidate": _runtime_ready_candidate(
            artifact.semantics_report
        ),
        "row_status_counts": _row_status_counts(artifact.row_records),
        "debug_only": artifact.writer_status == "debug_only",
    }


def _pack_task_record(
    row: dict[str, object],
) -> tuple[dict[str, object], bytes, Diagnostic | None]:
    candidate = row.get("task_conf_info_candidate")
    if not isinstance(candidate, dict):
        return {}, b"", _row_error(
            TASK_CONF_INFO_STRUCT,
            row,
            "missing_task_conf_info_candidate",
            "missing task_conf_info_candidate",
        )
    try:
        subtasks_idx = _u64_slots(candidate.get("subtasks_idx"), MAX_SUBTASK_SLOTS)
        suc_tasks = _u64_slots(candidate.get("suc_tasks"), MAX_TASK_FOLLOW_SLOTS)
        values = (
            _bool_byte(candidate.get("is_exe_start")),
            _bool_byte(candidate.get("is_exe_end")),
            _u64(candidate.get("subtasks_amount")),
            _u64(candidate.get("execute_times")),
            *subtasks_idx,
            *suc_tasks,
        )
        encoded = struct.pack(TASK_CONF_INFO_FORMAT, *values)
    except ValueError as exc:
        return {}, b"", _row_error(
            TASK_CONF_INFO_STRUCT,
            row,
            "invalid_task_conf_info_candidate",
            str(exc),
        )
    return (
        {
            "component_index": row.get("component_index"),
            "task_idx": candidate.get("task_idx"),
            "status": "packed",
            "subtasks_amount": candidate.get("subtasks_amount"),
            "execute_times": candidate.get("execute_times"),
            "subtasks_idx": subtasks_idx,
            "suc_tasks": suc_tasks,
            "binary_encoding_policy": "debug_only_task_conf_info_t_vendor_layout",
        },
        encoded,
        None,
    )


def _pack_exeblock_record(
    row: dict[str, object],
) -> tuple[dict[str, object], bytes, Diagnostic | None]:
    candidate = row.get("exeBlock_conf_info_candidate")
    if not isinstance(candidate, dict):
        return {}, b"", _row_error(
            EXEBLOCK_CONF_INFO_STRUCT,
            row,
            "missing_exeBlock_conf_info_candidate",
            "missing exeBlock_conf_info_candidate",
        )
    conf = candidate.get("exeBlock_conf")
    if not isinstance(conf, dict):
        return {}, b"", _row_error(
            EXEBLOCK_CONF_INFO_STRUCT,
            row,
            "missing_exeBlock_conf",
            "missing nested exeBlock_conf",
        )
    try:
        pe_dst = _position(candidate.get("pe_dst"))
        has_stages = _stage_bool_slots(conf.get("has_stages"))
        stages_start_pc = _stage_u64_slots(conf.get("stages_start_pc"))
        predecessors = _endpoint_records(conf.get("predecessors"))
        successors = _endpoint_records(conf.get("successors"))
        stage_amounts = _stage_amount_slots(conf.get("stage_inst_amounts"))
        inner = struct.pack(
            EXEBLOCK_CONF_FORMAT,
            _u64(conf.get("req_activations")),
            *has_stages,
            *stages_start_pc,
            *predecessors,
            *successors,
            _u64(conf.get("block_idx")),
            _u64(conf.get("subtask_idx")),
            _u64(conf.get("task_idx")),
            _u64(conf.get("instances_amount")),
            _u64(conf.get("child_amount")),
            _u64(conf.get("block_class")),
            _u64(conf.get("inst_mem_based_addr")),
            *stage_amounts,
            0,
        )
        encoded = struct.pack(
            EXEBLOCK_CONF_INFO_HEADER_FORMAT,
            _bool_byte(candidate.get("valid")),
            _u64(candidate.get("block_idx")),
            *pe_dst,
            _u64(candidate.get("priority")),
        ) + inner
    except ValueError as exc:
        return {}, b"", _row_error(
            EXEBLOCK_CONF_INFO_STRUCT,
            row,
            "invalid_exeBlock_conf_info_candidate",
            str(exc),
        )
    if len(encoded) != EXEBLOCK_CONF_INFO_RECORD_SIZE:
        return {}, b"", _row_error(
            EXEBLOCK_CONF_INFO_STRUCT,
            row,
            "exeBlock_conf_info_size_mismatch",
            f"packed {len(encoded)} bytes, expected {EXEBLOCK_CONF_INFO_RECORD_SIZE}",
        )
    return (
        {
            "component_index": row.get("component_index"),
            "task_idx": conf.get("task_idx"),
            "subtask_idx": conf.get("subtask_idx"),
            "block_idx": conf.get("block_idx"),
            "status": "packed",
            "pe_dst": {"x": pe_dst[0], "y": pe_dst[1], "z": pe_dst[2]},
            "req_activations": conf.get("req_activations"),
            "child_amount": conf.get("child_amount"),
            "inst_mem_based_addr": conf.get("inst_mem_based_addr"),
            "has_stages": dict(conf.get("has_stages", {})),
            "stages_start_pc": dict(conf.get("stages_start_pc", {})),
            "stage_inst_amounts": dict(conf.get("stage_inst_amounts", {})),
            "predecessors": predecessors,
            "successors": successors,
            "predecessor_component_indices": tuple(
                row.get("predecessor_component_indices", ())
            ),
            "successor_component_indices": tuple(
                row.get("successor_component_indices", ())
            ),
            "dependency_policy": row.get("dependency_policy"),
            "dependency_proofs": tuple(row.get("dependency_proofs", ())),
            "is_leaf_candidate": conf.get("is_leaf"),
            "is_leaf_serialized": 0,
            "is_leaf_policy": (
                "fail_closed_to_memset_zero;visible vendor docs do not prove "
                "an explicit exeBlock_conf_t.is_leaf writer"
            ),
            "binary_encoding_policy": "debug_only_exeBlock_conf_info_t_vendor_layout",
        },
        encoded,
        None,
    )


def _pack_subtask_record(
    row: dict[str, object],
    *,
    address_by_key: dict[tuple[int, int], InstanceTableAddress],
    exeblocks_by_index: dict[object, dict[str, object]],
) -> tuple[dict[str, object], bytes, Diagnostic | None]:
    candidate = row.get("sub_task_conf_info_candidate")
    if not isinstance(candidate, dict):
        return {}, b"", _row_error(
            SUB_TASK_CONF_INFO_STRUCT,
            row,
            "missing_sub_task_conf_info_candidate",
            "missing sub_task_conf_info_candidate",
        )
    try:
        task_idx = _u64(candidate.get("task_idx"))
        subtask_idx = _u64(candidate.get("subtask_idx"))
        instances_amount = _u64(candidate.get("instances_amount"))
        address = address_by_key.get((task_idx, subtask_idx))
        if address is None:
            raise ValueError("missing derived InstanceTableAddress")
        if instances_amount != address.instances_amount:
            raise ValueError(
                "candidate instances_amount does not match derived "
                f"instance table count: {instances_amount} != "
                f"{address.instances_amount}"
            )
        suc_subtasks = _u64_slots(candidate.get("suc_subtasks"), MAX_TASK_FOLLOW_SLOTS)
        embedded_indices = candidate.get("embedded_exeblock_component_indices")
        if not isinstance(embedded_indices, list):
            raise ValueError("embedded_exeblock_component_indices must be a list")
        if len(embedded_indices) > MAX_EXEBLOCKS_PER_SUBTASK:
            raise ValueError("too many embedded exeBlock rows for subtask")
        embedded = bytearray(
            MAX_EXEBLOCKS_PER_SUBTASK * EXEBLOCK_CONF_INFO_RECORD_SIZE
        )
        for slot_index, component_index in enumerate(embedded_indices):
            if not isinstance(component_index, int):
                raise ValueError("embedded exeBlock component index is not int")
            exeblock_row = exeblocks_by_index.get(component_index)
            if exeblock_row is None:
                raise ValueError(
                    f"embedded exeBlock component {component_index} is missing"
                )
            _, encoded_exeblock, error = _pack_exeblock_record(exeblock_row)
            if error is not None:
                raise ValueError(error.message)
            offset = slot_index * EXEBLOCK_CONF_INFO_RECORD_SIZE
            embedded[offset : offset + len(encoded_exeblock)] = encoded_exeblock
        header = struct.pack(
            SUB_TASK_CONF_INFO_HEADER_FORMAT,
            _bool_byte(candidate.get("is_exe_start")),
            _bool_byte(candidate.get("is_exe_end")),
            instances_amount,
            address.address,
            *suc_subtasks,
            _u64(candidate.get("root_block_amount")),
            _u64(candidate.get("block_amount")),
        )
        trailer = struct.pack(SUB_TASK_CONF_INFO_TRAILER_FORMAT, subtask_idx, task_idx)
        encoded = header + bytes(embedded) + trailer
    except ValueError as exc:
        return {}, b"", _row_error(
            SUB_TASK_CONF_INFO_STRUCT,
            row,
            "invalid_sub_task_conf_info_candidate",
            str(exc),
        )
    if len(encoded) != SUB_TASK_CONF_INFO_RECORD_SIZE:
        return {}, b"", _row_error(
            SUB_TASK_CONF_INFO_STRUCT,
            row,
            "sub_task_conf_info_size_mismatch",
            f"packed {len(encoded)} bytes, expected {SUB_TASK_CONF_INFO_RECORD_SIZE}",
        )
    return (
        {
            "component_index": row.get("component_index"),
            "task_idx": task_idx,
            "subtask_idx": subtask_idx,
            "status": "packed",
            "instances_amount": instances_amount,
            "instances_conf_mem_based_addr": address.address,
            "instance_table_row_index": address.row_index,
            "embedded_exeblock_count": len(embedded_indices),
            "binary_encoding_policy": (
                "debug_only_sub_task_conf_info_t_with_embedded_exeBlock_rows"
            ),
        },
        encoded,
        None,
    )


def _pack_selected_subtask_record(
    row: dict[str, object],
    *,
    semantics_by_key: dict[tuple[int, int], SubtaskInstanceSemanticsRecord],
    address_by_key: dict[tuple[int, int], InstanceTableAddress],
    exeblocks_by_index: dict[object, dict[str, object]],
) -> tuple[dict[str, object], bytes, Diagnostic | None]:
    candidate = row.get("sub_task_conf_info_candidate")
    if not isinstance(candidate, dict):
        return {}, b"", _row_error(
            SUB_TASK_CONF_INFO_STRUCT,
            row,
            "missing_sub_task_conf_info_candidate",
            "missing sub_task_conf_info_candidate",
        )
    try:
        task_idx = _u64(candidate.get("task_idx"))
        subtask_idx = _u64(candidate.get("subtask_idx"))
        semantic = semantics_by_key.get((task_idx, subtask_idx))
        if semantic is None:
            raise ValueError("missing selected subtask semantics record")
        if semantic.selection_status != "selected":
            raise ValueError(
                "selected subtask byte packing requires selection_status=selected"
            )
        instances_amount = _u64(semantic.selected_instances_amount)
        address = address_by_key.get((task_idx, subtask_idx))
        if address is None:
            raise ValueError("missing derived InstanceTableAddress")
        if instances_amount != address.instances_amount:
            raise ValueError(
                "selected instances_amount does not match derived instance "
                f"table count: {instances_amount} != {address.instances_amount}"
            )
        instance_source = _selected_instances_amount_source(row, semantic)
        suc_subtasks = _u64_slots(candidate.get("suc_subtasks"), MAX_TASK_FOLLOW_SLOTS)
        embedded_indices = candidate.get("embedded_exeblock_component_indices")
        if not isinstance(embedded_indices, list):
            raise ValueError("embedded_exeblock_component_indices must be a list")
        if len(embedded_indices) > MAX_EXEBLOCKS_PER_SUBTASK:
            raise ValueError("too many embedded exeBlock rows for subtask")
        block_amount = _u64(candidate.get("block_amount"))
        if block_amount != len(embedded_indices):
            raise ValueError(
                "block_amount must match active embedded exeBlock row count: "
                f"{block_amount} != {len(embedded_indices)}"
            )
        embedded = bytearray(
            MAX_EXEBLOCKS_PER_SUBTASK * EXEBLOCK_CONF_INFO_RECORD_SIZE
        )
        for slot_index, component_index in enumerate(embedded_indices):
            if not isinstance(component_index, int):
                raise ValueError("embedded exeBlock component index is not int")
            exeblock_row = exeblocks_by_index.get(component_index)
            if exeblock_row is None:
                raise ValueError(
                    f"embedded exeBlock component {component_index} is missing"
                )
            _, encoded_exeblock, error = _pack_exeblock_record(exeblock_row)
            if error is not None:
                raise ValueError(error.message)
            offset = slot_index * EXEBLOCK_CONF_INFO_RECORD_SIZE
            embedded[offset : offset + len(encoded_exeblock)] = encoded_exeblock
        header = struct.pack(
            SUB_TASK_CONF_INFO_HEADER_FORMAT,
            _bool_byte(candidate.get("is_exe_start")),
            _bool_byte(candidate.get("is_exe_end")),
            instances_amount,
            address.address,
            *suc_subtasks,
            _u64(candidate.get("root_block_amount")),
            block_amount,
        )
        trailer = struct.pack(SUB_TASK_CONF_INFO_TRAILER_FORMAT, subtask_idx, task_idx)
        encoded = header + bytes(embedded) + trailer
    except ValueError as exc:
        return {}, b"", _row_error(
            SUB_TASK_CONF_INFO_STRUCT,
            row,
            "invalid_selected_sub_task_conf_info_record",
            str(exc),
        )
    if len(encoded) != SUB_TASK_CONF_INFO_RECORD_SIZE:
        return {}, b"", _row_error(
            SUB_TASK_CONF_INFO_STRUCT,
            row,
            "selected_sub_task_conf_info_size_mismatch",
            f"packed {len(encoded)} bytes, expected {SUB_TASK_CONF_INFO_RECORD_SIZE}",
        )
    record = semantic.to_plan()
    record.update(
        {
            "component_index": row.get("component_index"),
            "task_idx": task_idx,
            "subtask_idx": subtask_idx,
            "status": "selected",
            "instances_amount": instances_amount,
            "instances_amount_source": instance_source,
            "instances_conf_mem_based_addr": address.address,
            "instance_table_row_index": address.row_index,
            "is_exe_start": candidate.get("is_exe_start"),
            "is_exe_end": candidate.get("is_exe_end"),
            "suc_subtasks": suc_subtasks,
            "root_block_amount": candidate.get("root_block_amount"),
            "block_amount": block_amount,
            "embedded_exeblock_count": len(embedded_indices),
            "embedded_exeblock_component_indices": tuple(embedded_indices),
            "source_backing": {
                "is_exe_start": "sub_task_conf_info_candidate.is_exe_start",
                "is_exe_end": "sub_task_conf_info_candidate.is_exe_end",
                "instances_amount": instance_source,
                "instances_conf_mem_based_addr": (
                    "derived InstanceTableAddress.address"
                ),
                "suc_subtasks": "sub_task_conf_info_candidate.suc_subtasks",
                "root_block_amount": (
                    "sub_task_conf_info_candidate.root_block_amount"
                ),
                "block_amount": "sub_task_conf_info_candidate.block_amount",
                "embedded_exeBlock_rows": (
                    "sub_task_conf_info_candidate."
                    "embedded_exeblock_component_indices + "
                    "exeBlock_conf_info_candidate debug bytes"
                ),
                "subtask_idx": "sub_task_conf_info_candidate.subtask_idx",
                "task_idx": "sub_task_conf_info_candidate.task_idx",
            },
            "binary_encoding_policy": (
                "debug_only_selected_sub_task_conf_info_t_runtime_shaped_bytes;"
                "not_runnable_vendor_payload"
            ),
            "runtime_payload_status": "debug_only_runtime_shaped_bytes",
            "runtime_ready_candidate": False,
        }
    )
    return record, encoded, None


def _selected_instances_amount_source(
    row: dict[str, object],
    semantic: SubtaskInstanceSemanticsRecord,
) -> str:
    if semantic.selected_representation == "folded_k_stream":
        folded = row.get("folded_subtask_conf_candidate")
        if not isinstance(folded, dict):
            raise ValueError("folded_k_stream selection lacks folded candidate")
        folded_amount = _u64(folded.get("instances_amount"))
        if folded_amount != semantic.selected_instances_amount:
            raise ValueError(
                "folded_k_stream selected amount must match folded candidate: "
                f"{semantic.selected_instances_amount} != {folded_amount}"
            )
        return "folded_subtask_conf_candidate.instances_amount"
    if semantic.selected_representation == "zero_instance_control":
        if semantic.selected_instances_amount != 0:
            raise ValueError("zero_instance_control must select instances_amount=0")
        return "derived InstanceTableAddress.instances_amount"
    if semantic.selected_representation == "expanded":
        candidate = row.get("sub_task_conf_info_candidate")
        if not isinstance(candidate, dict):
            raise ValueError("expanded selection lacks subtask candidate")
        candidate_amount = _u64(candidate.get("instances_amount"))
        if candidate_amount != semantic.selected_instances_amount:
            raise ValueError(
                "expanded selected amount must match subtask candidate: "
                f"{semantic.selected_instances_amount} != {candidate_amount}"
            )
        return "sub_task_conf_info_candidate.instances_amount"
    raise ValueError(
        "unsupported selected subtask representation for byte packing: "
        f"{semantic.selected_representation}"
    )


def _base_diagnostics(
    component_plan: VendorComponentPlan,
    readiness_plan: SerializerReadinessPlan,
    struct_name: str,
    *,
    require_packable: bool,
) -> list[Diagnostic]:
    diagnostics = list(component_plan.diagnostics)
    diagnostics.extend(
        Diagnostic(
            severity="error",
            code="serializer_readiness_diagnostic",
            subject_id="SerializerReadinessPlan",
            message=message,
        )
        for message in readiness_plan.diagnostics
    )
    if component_plan.profile_id != readiness_plan.profile_id:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="micc_component_writer_profile_mismatch",
                subject_id=struct_name,
                message=(
                    "component plan and readiness plan profile ids differ: "
                    f"{component_plan.profile_id} != {readiness_plan.profile_id}"
                ),
            )
        )
    if component_plan.runnability_state != "emittable_debug":
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="micc_component_writer_requires_emittable_debug",
                subject_id=struct_name,
                message=(
                    "MICC component writer requires an emittable_debug "
                    f"component plan; got {component_plan.runnability_state}"
                ),
            )
        )
    if require_packable and not _struct_is_packable(readiness_plan, struct_name):
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="micc_component_writer_struct_not_packable",
                subject_id=struct_name,
                message=f"{struct_name} is not marked packable by readiness",
            )
        )
    return diagnostics


def _subtask_readiness_diagnostics(
    readiness_plan: SerializerReadinessPlan,
) -> tuple[Diagnostic, ...]:
    readiness = next(
        (
            item
            for item in readiness_plan.struct_readiness
            if item.struct_name == SUB_TASK_CONF_INFO_STRUCT
        ),
        None,
    )
    if readiness is None:
        return (
            Diagnostic(
                severity="error",
                code="missing_subtask_readiness",
                subject_id=SUB_TASK_CONF_INFO_STRUCT,
                message="missing sub_task_conf_info_t readiness record",
            ),
        )
    blockers = [
        field
        for field in readiness.required_fields
        if field.blocker_reason is not None
    ]
    unexpected = [
        field
        for field in blockers
        if field.field_path != "instances_conf_mem_based_addr"
    ]
    if unexpected:
        return tuple(
            Diagnostic(
                severity="error",
                code="subtask_writer_unexpected_readiness_blocker",
                subject_id=field.field_path,
                message=str(field.blocker_reason),
            )
            for field in unexpected
        )
    return ()


def _struct_is_packable(plan: SerializerReadinessPlan, struct_name: str) -> bool:
    return any(
        readiness.struct_name == struct_name
        and readiness.serializer_status == "packable_candidate"
        for readiness in plan.struct_readiness
    )


def _subtask_semantics_diagnostics(
    report: SubtaskInstanceSemanticsReport,
) -> tuple[Diagnostic, ...]:
    return tuple(
        Diagnostic(
            severity="error",
            code=record.blocker_code or "subtask_instance_semantics_blocked",
            subject_id=(
                f"task{record.task_idx}:subtask{record.subtask_idx}:"
                f"{record.subtask_slot}"
            ),
            message=record.blocker_message or "subtask instance semantics blocked",
        )
        for record in report.records
        if record.blocker_severity == "error"
    )


def _subtask_semantics_by_key(
    report: SubtaskInstanceSemanticsReport,
) -> dict[tuple[int, int], SubtaskInstanceSemanticsRecord]:
    records: dict[tuple[int, int], SubtaskInstanceSemanticsRecord] = {}
    for record in report.records:
        if record.task_idx is None or record.subtask_idx is None:
            continue
        records[(record.task_idx, record.subtask_idx)] = record
    return records


def _subtask_instance_classification(row: dict[str, object]) -> str:
    subtask_slot = str(row.get("subtask_slot"))
    if subtask_slot == "subtask1_k_stream":
        return "k_stream"
    if isinstance(row.get("folded_subtask_conf_candidate"), dict):
        return "k_stream"
    return "non_k_stream"


def _select_subtask_representation(
    *,
    classification: str,
    candidate_amount: int | None,
    derived_count: int | None,
    folded_amount: int | None,
) -> tuple[
    str,
    int | None,
    str,
    str,
    str,
    str | None,
    str | None,
]:
    if candidate_amount is None:
        return (
            "blocked_missing_candidate",
            None,
            "missing_candidate",
            "blocked",
            "error",
            "missing_candidate_instances_amount",
            "subtask candidate lacks concrete instances_amount",
        )
    if derived_count is None:
        return (
            "blocked_missing_derived_instance_count",
            None,
            "missing_derived_count",
            "blocked",
            "error",
            "missing_derived_instance_count",
            "cannot derive active instance table row count for subtask",
        )
    if candidate_amount == derived_count:
        if derived_count == 0:
            return (
                "zero_instance_control",
                0,
                "zero_instance_control",
                "selected",
                "none",
                None,
                None,
            )
        return (
            "expanded",
            derived_count,
            "expanded_candidate_matches_derived_count",
            "selected",
            "none",
            None,
            None,
        )
    if (
        classification == "k_stream"
        and folded_amount is not None
        and folded_amount == derived_count
        and derived_count > 0
    ):
        return (
            "folded_k_stream",
            derived_count,
            "folded_k_stream_explicit",
            "selected",
            "none",
            None,
            None,
        )
    if classification == "non_k_stream" and derived_count == 0:
        return (
            "zero_instance_control",
            0,
            "zero_instance_control",
            "selected",
            "none",
            None,
            None,
        )
    return (
        "blocked_instance_amount_mismatch",
        None,
        "unresolved_instance_amount_mismatch",
        "blocked",
        "error",
        "subtask_instance_amount_mismatch",
        (
            "candidate instances_amount does not match derived active instance "
            f"count: {candidate_amount} != {derived_count}"
        ),
    )


def _address_policy(address: InstanceTableAddress | None) -> str:
    if address is None:
        return "missing_address"
    if address.instances_amount == 0:
        return "zero_instances_address_ignored"
    if address.address == 0:
        return "positive_instances_address_zero_means_row0"
    return "positive_instances_address_byte_offset"


def _optional_int(value: object) -> int | None:
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    return None


def _semantics_blocker_count(report: dict[str, object] | None) -> int:
    if not isinstance(report, dict):
        return 0
    value = report.get("blocked_subtask_count")
    return value if isinstance(value, int) else 0


def _runtime_ready_candidate(report: dict[str, object] | None) -> bool | None:
    if not isinstance(report, dict):
        return None
    value = report.get("runtime_ready_candidate")
    return value if isinstance(value, bool) else None


def _u64(value: object) -> int:
    if isinstance(value, bool):
        value = int(value)
    if not isinstance(value, int):
        raise ValueError(f"expected uint64 int, got {value!r}")
    if value < 0 or value > 0xFFFFFFFFFFFFFFFF:
        raise ValueError(f"uint64 value out of range: {value!r}")
    return value


def _bool_byte(value: object) -> int:
    if isinstance(value, bool):
        return int(value)
    if value in (0, 1):
        return int(value)
    raise ValueError(f"expected boolean byte, got {value!r}")


def _u64_slots(value: object, slot_count: int) -> tuple[int, ...]:
    if not isinstance(value, list) or len(value) != slot_count:
        raise ValueError(f"expected list with {slot_count} uint64 slots")
    return tuple(_u64(item) for item in value)


def _position(value: object) -> tuple[int, int, int]:
    if not isinstance(value, dict):
        raise ValueError("position must be a dict")
    return (_u64(value.get("x")), _u64(value.get("y")), _u64(value.get("z")))


def _stage_bool_slots(value: object) -> tuple[int, int, int, int, int]:
    if not isinstance(value, dict):
        raise ValueError("has_stages must be a stage dict")
    return tuple(
        _bool_byte(value.get(stage, False))
        for stage in ("LD", "CAL", "FLOW", "ST", "MAX_COMPONENT")
    )


def _stage_u64_slots(value: object) -> tuple[int, int, int, int, int]:
    if not isinstance(value, dict):
        raise ValueError("stages_start_pc must be a stage dict")
    return tuple(_u64(value.get(stage)) for stage in ("LD", "CAL", "FLOW", "ST", "MAX_COMPONENT"))


def _stage_amount_slots(value: object) -> tuple[int, int, int, int]:
    if not isinstance(value, dict):
        raise ValueError("stage_inst_amounts must be a stage dict")
    return tuple(_u64(value.get(stage)) for stage in ("LD", "CAL", "FLOW", "ST"))


def _endpoint_records(value: object) -> tuple[int, ...]:
    if not isinstance(value, list) or len(value) != MAX_TASK_FOLLOW_SLOTS:
        raise ValueError(f"endpoint list must contain {MAX_TASK_FOLLOW_SLOTS} slots")
    records: list[int] = []
    for slot in value:
        if not isinstance(slot, dict):
            raise ValueError("endpoint slot must be a dict")
        pe_pos = _position(slot.get("pe_pos"))
        records.extend((*pe_pos, _u64(slot.get("block_idx")), _bool_byte(slot.get("valid"))))
    return tuple(records)


def _endpoint_valid_count_from_record(value: object) -> int | None:
    if not isinstance(value, (list, tuple)):
        return None
    if len(value) != MAX_TASK_FOLLOW_SLOTS * 5:
        return None
    return sum(1 for index in range(4, len(value), 5) if int(value[index]) != 0)


def _row_error(
    struct_name: str,
    row: dict[str, object],
    code: str,
    message: str,
) -> Diagnostic:
    return Diagnostic(
        severity="error",
        code=code,
        subject_id=f"{struct_name}:{row.get('component_index')}",
        message=message,
    )


def _has_errors(diagnostics: list[Diagnostic] | tuple[Diagnostic, ...]) -> bool:
    return any(diagnostic.severity == "error" for diagnostic in diagnostics)


def _blocked_artifact(
    component_plan: VendorComponentPlan,
    component: str,
    struct_name: str,
    record_format: str,
    record_size_bytes: int,
    diagnostics: tuple[Diagnostic, ...],
    *,
    address_records: tuple[dict[str, object], ...] = (),
    semantics_report: dict[str, object] | None = None,
) -> MiccComponentWriterArtifact:
    return MiccComponentWriterArtifact(
        profile_id=component_plan.profile_id,
        component=component,
        struct_name=struct_name,
        writer_status="blocked",
        byte_order="little",
        record_format=record_format,
        row_count=0,
        record_size_bytes=record_size_bytes,
        payload=b"",
        row_records=(),
        address_records=address_records,
        semantics_report=semantics_report,
        diagnostics=diagnostics,
    )


def _emitted_artifact(
    component_plan: VendorComponentPlan,
    component: str,
    struct_name: str,
    record_format: str,
    record_size_bytes: int,
    payload: bytes,
    row_records: tuple[dict[str, object], ...],
    diagnostics: tuple[Diagnostic, ...],
    *,
    address_records: tuple[dict[str, object], ...] = (),
    semantics_report: dict[str, object] | None = None,
) -> MiccComponentWriterArtifact:
    return MiccComponentWriterArtifact(
        profile_id=component_plan.profile_id,
        component=component,
        struct_name=struct_name,
        writer_status="debug_only",
        byte_order="little",
        record_format=record_format,
        row_count=len(row_records),
        record_size_bytes=record_size_bytes,
        payload=payload,
        row_records=row_records,
        address_records=address_records,
        semantics_report=semantics_report,
        diagnostics=diagnostics,
    )


def _row_status_counts(rows: tuple[dict[str, object], ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status"))
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _record_value_counts(
    records: tuple[SubtaskInstanceSemanticsRecord, ...],
    field_name: str,
) -> dict[str, int]:
    counts: dict[str, int] = {}
    for record in records:
        value = getattr(record, field_name)
        key = str(value)
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _writer_evidence(subject: str) -> dict[str, object]:
    common_sources = [
        "docs/runtime/data/README.md",
        "docs/compiler/binary_packaging/README.md",
        "docs/vendor_reference/common_oper/source-fingerprint-index.md",
    ]
    if subject == "InstanceTableAddress":
        return {
            "source_backed": [
                "addr_space=instance_component_offset is writer-local and points into instance_conf_info_file.bin",
                "unit=bytes",
                "row_size=sizeof(instance_conf_info_t)=32",
                "byte_offset=row_index*32",
                "instances_amount==0 => address=0",
            ],
            "fail_closed": [
                "do not derive runtime active work from padded instance capacity",
                "non-contiguous instance rows for one subtask are rejected",
            ],
            "active_vs_padded_policy": (
                "address rows are derived from active component_plan.instance_rows; "
                "CBUF padded instance capacity is not used as active work"
            ),
            "sources": common_sources
            + [
                "docs/runtime/data/cbuf.md",
                "docs/runtime/data/micc.md",
                "compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py",
            ],
        }
    if subject == TASK_CONF_INFO_STRUCT:
        return {
            "source_backed": [
                "is_exe_start/is_exe_end offsets and 1-byte flag layout",
                "subtasks_amount, execute_times, subtasks_idx[0..7], suc_tasks[0..3]",
                "active task rows are distinct from padded 4-row task capacity",
                "successor/start/end flags must be checked against active task/subtask graph",
            ],
            "fail_closed": [
                "non-scalar or wrong-width subtasks_idx/suc_tasks slots",
                "task rows from non-emittable_debug component plans",
                "task rows not marked packable by serializer readiness",
            ],
            "active_vs_padded_policy": (
                "writer emits active component_plan.task_rows only; runtime package "
                "padding remains a later package emitter concern"
            ),
            "sources": common_sources
            + [
                "docs/runtime/data/micc.md",
                "compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py",
            ],
        }
    if subject == EXEBLOCK_CONF_INFO_STRUCT:
        return {
            "source_backed": [
                "exeBlock_conf_info_t 520-byte layout and position_t 3x uint64",
                "successor_t/predecessor_t = position_t + block_idx + valid",
                "invalid predecessor/successor slots are zeroed and gated by valid",
                "LD/CAL/FLOW/ST/END stage PC order and LD/CAL/FLOW/ST amount fields",
                "block_class serializes as reserved zero from memset evidence",
            ],
            "fail_closed": [
                "exeBlock_conf_t.is_leaf lacks a proven explicit writer; debug bytes serialize 0",
                "endpoint rows with missing pe_pos/block_idx/valid are rejected",
                "runtime-runnable graph closure is deferred to control_graph_check",
            ],
            "active_vs_padded_policy": (
                "writer emits active component_plan.exeblock_rows only; subtask "
                "embedding/padded 512-slot layout is handled by sub_task writer"
            ),
            "sources": common_sources
            + [
                "docs/runtime/data/cbuf.md",
                "docs/architecture/runtime-model/vendor-exeblock-subtask-struct.md",
                "compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py",
            ],
        }
    if subject == SUB_TASK_CONF_INFO_STRUCT:
        return {
            "source_backed": [
                "sub_task_conf_info_t 266328-byte layout",
                "instances_amount and instances_conf_mem_based_addr are distinct fields",
                "suc_subtasks[0..3], root_block_amount, block_amount, subtask_idx, task_idx",
                "embedded exeBlocks_conf_info has 512 padded slots of 520 bytes",
                "active exeBlock rows are those inside block_amount and must have valid=1",
            ],
            "fail_closed": [
                "selected subtask bytes are debug-only evidence, not runnable vendor payload bytes",
                "subtask writer refuses to invent or rewrite instance loop semantics",
                "successor/start/end graph closure remains validation-backed, not guessed",
            ],
            "active_vs_padded_policy": (
                "task.subtasks_amount/subtasks_idx define active subtask rows; "
                "subtask.block_amount defines active embedded exeBlock rows"
            ),
            "sources": common_sources
            + [
                "docs/runtime/data/micc.md",
                "docs/architecture/runtime-model/vendor-exeblock-subtask-struct.md",
                "compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py",
            ],
        }
    if subject == "SubtaskInstanceSemantics":
        return {
            "source_backed": [
                "instances_amount controls subtask repetition count",
                "instances_conf_mem_based_addr points to instance table bytes",
                "active subtask rows are selected by task subtasks_amount/subtasks_idx",
                "active embedded exeBlock rows are selected by subtask block_amount",
            ],
            "fail_closed": [
                "expanded representation requires candidate amount to match derived active instance rows",
                "folded k-stream requires an explicit selected folded representation",
                "writer must not combine folded instance counts with expanded subtask fields",
                "non-k-stream subtasks with no active instance rows require instances_amount=0",
            ],
            "active_vs_padded_policy": (
                "derived active instance count comes from active instance rows, "
                "not padded instance table capacity"
            ),
            "sources": common_sources
            + [
                "docs/runtime/data/cbuf.md",
                "docs/runtime/data/micc.md",
                "docs/architecture/runtime-model/vendor-exeblock-subtask-struct.md",
                "compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py",
            ],
        }
    if subject == "SubtaskInstanceRepresentationSelection":
        return {
            "source_backed": [
                "zero_instance_control selects instances_amount=0 only when derived active instance rows are absent",
                "folded_k_stream selection is explicit and records selected_representation=folded_k_stream",
                "instances_amount==0 => address=0 ignored",
                "instances_amount>0 and address=0 => row0",
            ],
            "fail_closed": [
                "selection records are debug-only evidence, not runnable vendor payload bytes",
                "unmatched expanded/folded/derived counts remain blocked",
                "writer does not silently combine expanded candidates with folded overlay counts",
            ],
            "active_vs_padded_policy": (
                "selection consumes active instance rows derived from "
                "component_plan.instance_rows; padded capacity remains separate"
            ),
            "sources": common_sources
            + [
                "docs/runtime/data/cbuf.md",
                "docs/runtime/data/micc.md",
                "docs/architecture/runtime-model/vendor-exeblock-subtask-struct.md",
            ],
        }
    return {
        "source_backed": [],
        "fail_closed": ["no evidence map registered for subject"],
        "active_vs_padded_policy": "unregistered",
        "sources": common_sources,
    }


__all__ = [
    "InstanceTableAddress",
    "InstanceTableAddressPlan",
    "MiccComponentWriterArtifact",
    "SubtaskInstanceRepresentationSelection",
    "SubtaskInstanceSemanticsRecord",
    "SubtaskInstanceSemanticsReport",
    "build_pe00_materialized_scalar_micc_lowering_intent",
    "build_subtask_instance_semantics_report",
    "derive_instance_table_addresses",
    "emit_micc_exeBlock_conf_info_component",
    "emit_micc_sub_task_conf_info_component",
    "emit_micc_task_conf_info_component",
    "summarize_micc_component_writer_artifact",
]
