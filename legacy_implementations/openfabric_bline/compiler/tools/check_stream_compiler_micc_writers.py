#!/usr/bin/env python3
"""Focused validation for B-line MICC/control component writers."""

from __future__ import annotations

import struct

from gpdpu_compiler.core.stream_compiler.debug_emit import emit_debug_row_artifact
from gpdpu_compiler.core.stream_compiler.field_offsets import (
    build_field_offset_preflight_plan,
)
from gpdpu_compiler.core.stream_compiler.folding import analyze_stream_loop_folding
from gpdpu_compiler.core.stream_compiler.micc_component_writers import (
    build_gemm_no_relu_micc_final_candidate_report,
    build_subtask_instance_semantics_report,
    derive_instance_table_addresses,
    emit_micc_exeBlock_conf_info_component,
    emit_micc_sub_task_conf_info_component,
    emit_micc_task_conf_info_component,
    summarize_micc_component_writer_artifact,
)
from gpdpu_compiler.core.stream_compiler.serializer_readiness import (
    build_serializer_readiness_plan,
)
from gpdpu_compiler.core.stream_compiler.vendor_components import (
    build_vendor_component_plan,
)
from gpdpu_compiler.core.stream_compiler.vendor_groups import (
    group_debug_rows_vendor_like,
    remap_vendor_like_groups_locally,
)
from stream_compiler_demo_pipeline import build_demo_pipeline


EXPECTED_TASK_SUMMARY = {
    "profile_id": "dfu3500_legacy_gemm_symbolic",
    "component": "task_rows",
    "struct_name": "task_conf_info_t",
    "writer_status": "debug_only",
    "record_format": "<BB6xQQ8Q4Q",
    "row_count": 4,
    "record_size_bytes": 120,
    "payload_size_bytes": 480,
    "diagnostic_count": 0,
    "diagnostic_severity_counts": {},
    "address_record_count": 0,
    "semantics_blocked_subtask_count": 0,
    "runtime_ready_candidate": None,
    "row_status_counts": {"packed": 4},
    "debug_only": True,
}

EXPECTED_EXEBLOCK_SUMMARY = {
    "profile_id": "dfu3500_legacy_gemm_symbolic",
    "component": "exeblock_rows",
    "struct_name": "exeBlock_conf_info_t",
    "writer_status": "debug_only",
    "record_format": "<B7xQ3QQ+<Q5B3x5Q20Q20Q11QB7x",
    "row_count": 128,
    "record_size_bytes": 520,
    "payload_size_bytes": 66560,
    "diagnostic_count": 0,
    "diagnostic_severity_counts": {},
    "address_record_count": 0,
    "semantics_blocked_subtask_count": 0,
    "runtime_ready_candidate": None,
    "row_status_counts": {"packed": 128},
    "debug_only": True,
}

EXPECTED_SUBTASK_SUMMARY = {
    "profile_id": "dfu3500_legacy_gemm_symbolic",
    "component": "subtask_rows",
    "struct_name": "sub_task_conf_info_t",
    "writer_status": "debug_only",
    "record_format": "<BB6xQQ4QQQ+512*exeBlock_conf_info_t+<QQ",
    "row_count": 8,
    "record_size_bytes": 266328,
    "payload_size_bytes": 2130624,
    "diagnostic_count": 0,
    "diagnostic_severity_counts": {},
    "address_record_count": 8,
    "semantics_blocked_subtask_count": 0,
    "runtime_ready_candidate": False,
    "row_status_counts": {"selected": 8},
    "debug_only": True,
}


def main() -> None:
    failures: list[str] = []

    component_plan, readiness = _component_and_readiness("gemm_no_relu")

    address_plan = derive_instance_table_addresses(component_plan)
    address_records = [address.to_plan() for address in address_plan.addresses]
    if len(address_records) != 8:
        failures.append(f"expected 8 instance table address records: {address_records}")
    if address_plan.diagnostics:
        failures.append(f"unexpected address diagnostics: {address_plan.to_plan()}")
    _expect_address(
        address_records,
        failures,
        task_idx=0,
        subtask_idx=1,
        row_index=0,
        instances_amount=0,
        address=0,
    )
    _expect_address(
        address_records,
        failures,
        task_idx=1,
        subtask_idx=1,
        row_index=0,
        instances_amount=0,
        address=0,
    )

    semantics_report = build_subtask_instance_semantics_report(component_plan)
    semantics_plan = semantics_report.to_plan()
    _check_semantics_report(semantics_plan, failures)

    task_artifact = emit_micc_task_conf_info_component(component_plan, readiness)
    task_summary = summarize_micc_component_writer_artifact(task_artifact)
    if task_summary != EXPECTED_TASK_SUMMARY:
        failures.append(f"unexpected task writer summary: {task_summary}")
    if task_artifact.payload:
        first_task = struct.unpack("<BB6xQQ8Q4Q", task_artifact.payload[:120])
        if first_task != (1, 1, 2, 1, 1, 3, 0, 0, 0, 0, 0, 0, 0, 0, 0, 0):
            failures.append(f"unexpected first task row bytes: {first_task}")
    _expect_evidence(
        task_artifact.to_plan(),
        failures,
        "active task rows are distinct from padded 4-row task capacity",
    )

    exeblock_artifact = emit_micc_exeBlock_conf_info_component(
        component_plan,
        readiness,
    )
    exeblock_summary = summarize_micc_component_writer_artifact(exeblock_artifact)
    if exeblock_summary != EXPECTED_EXEBLOCK_SUMMARY:
        failures.append(f"unexpected exeBlock writer summary: {exeblock_summary}")
    if exeblock_artifact.payload:
        first_outer = struct.unpack("<B7xQ3QQ", exeblock_artifact.payload[:48])
        if first_outer != (1, 0, 0, 0, 0, 0):
            failures.append(f"unexpected first exeBlock outer row: {first_outer}")
    if exeblock_artifact.row_records:
        first_record = exeblock_artifact.row_records[0]
        if first_record.get("is_leaf_serialized") != 0:
            failures.append(f"is_leaf must serialize as conservative zero: {first_record}")
    _expect_evidence(
        exeblock_artifact.to_plan(),
        failures,
        "exeBlock_conf_t.is_leaf lacks a proven explicit writer; debug bytes serialize 0",
    )

    subtask_artifact = emit_micc_sub_task_conf_info_component(
        component_plan,
        readiness,
    )
    subtask_summary = summarize_micc_component_writer_artifact(subtask_artifact)
    if subtask_summary != EXPECTED_SUBTASK_SUMMARY:
        failures.append(f"unexpected subtask writer summary: {subtask_summary}")
    if len(subtask_artifact.payload) != 8 * 266328:
        failures.append(
            "selected subtask debug bytes should advance beyond payload_size_bytes=0: "
            f"{len(subtask_artifact.payload)}"
        )
    else:
        first_header = struct.unpack(
            "<BB6xQQ4QQQ",
            subtask_artifact.payload[:72],
        )
        if first_header != (1, 0, 0, 0, 3, 0, 0, 0, 16, 16):
            failures.append(f"unexpected first selected subtask header: {first_header}")
        first_trailer_start = 266328 - 16
        first_trailer = struct.unpack(
            "<QQ",
            subtask_artifact.payload[first_trailer_start:266328],
        )
        if first_trailer != (1, 0):
            failures.append(f"unexpected first selected subtask trailer: {first_trailer}")
        first_embedded = subtask_artifact.payload[72 : 72 + 520]
        if first_embedded != exeblock_artifact.payload[:520]:
            failures.append("first embedded exeBlock row did not reuse exeBlock bytes")

    blocker_codes = {diagnostic.code for diagnostic in subtask_artifact.diagnostics}
    if blocker_codes:
        failures.append(f"unexpected subtask blocker codes: {blocker_codes}")
    if len(subtask_artifact.row_records) != 8:
        failures.append(
            f"expected 8 selected subtask row records: {subtask_artifact.row_records}"
        )
    else:
        selection_counts: dict[str, int] = {}
        policy_counts: dict[str, int] = {}
        for record in subtask_artifact.row_records:
            representation = str(record.get("selected_representation"))
            selection_counts[representation] = (
                selection_counts.get(representation, 0) + 1
            )
            policy = str(record.get("selection_policy"))
            policy_counts[policy] = policy_counts.get(policy, 0) + 1
            if (
                record.get("runtime_payload_status")
                != "debug_only_runtime_shaped_bytes"
            ):
                failures.append(f"unexpected selected row runtime status: {record}")
            if record.get("runtime_ready_candidate") is not False:
                failures.append(f"selected row must remain non-runnable: {record}")
            source_backing = record.get("source_backing")
            if not isinstance(source_backing, dict):
                failures.append(f"missing selected row source backing: {record}")
            if representation == "zero_instance_control":
                if record.get("instances_amount") != 0:
                    failures.append(f"zero-instance row must serialize amount=0: {record}")
                if record.get("instances_amount_source") != (
                    "derived InstanceTableAddress.instances_amount"
                ):
                    failures.append(f"zero-instance row lacks derived source: {record}")
        if selection_counts != {"zero_instance_control": 8}:
            failures.append(f"unexpected selected row counts: {selection_counts}")
        if policy_counts != {"zero_instance_control": 8}:
            failures.append(f"unexpected selected policy counts: {policy_counts}")
    _expect_evidence(
        subtask_artifact.to_plan(),
        failures,
        "selected subtask bytes are debug-only evidence, not runnable vendor payload bytes",
    )
    artifact_semantics = subtask_artifact.to_plan().get("semantics_report")
    if artifact_semantics != semantics_plan:
        failures.append("subtask artifact semantics_report does not match standalone report")

    micc_final = build_gemm_no_relu_micc_final_candidate_report(
        task_artifact=task_artifact,
        subtask_artifact=subtask_artifact,
        exeblock_artifact=exeblock_artifact,
    )
    if micc_final.get("status") != (
        "decoded_wait_leaf_policy_available_runtime_trace_missing"
    ):
        failures.append(f"unexpected MICC final status: {micc_final}")
    if micc_final.get("struct_bytes_available") is not True:
        failures.append(f"MICC struct bytes should be available: {micc_final}")
    if micc_final.get("decoded_struct_roundtrip_available") is not True:
        failures.append(f"MICC decoded roundtrip should be available: {micc_final}")
    if micc_final.get("runtime_ready_candidate") is not False:
        failures.append(f"MICC final report must fail closed: {micc_final}")
    if micc_final.get("final_micc_file_claim") is not False:
        failures.append(f"MICC final file claim must stay false: {micc_final}")
    if micc_final.get("section_statuses") != {
        "tasks_conf_info": "decoded_roundtrip_available_runtime_trace_missing",
        "subtasks_conf_info": "decoded_roundtrip_available_runtime_trace_missing",
        "exeblock_conf_info": "decoded_roundtrip_available_runtime_trace_missing",
    }:
        failures.append(f"unexpected MICC section final statuses: {micc_final}")
    for section in micc_final.get("sections", ()):
        if not isinstance(section, dict):
            failures.append(f"MICC section must be a mapping: {section}")
            continue
        proof_plan = section.get("decoded_roundtrip_proof_plan")
        if not isinstance(proof_plan, dict):
            failures.append(f"missing decoded roundtrip proof plan: {section}")
            continue
        if proof_plan.get("status") != "decoded_roundtrip_available":
            failures.append(f"unexpected decoded proof status: {proof_plan}")
        if proof_plan.get("decoded_roundtrip_claim") is not True:
            failures.append(f"decoded roundtrip claim should be true: {proof_plan}")
        if proof_plan.get("runtime_runnable_claim") is not False:
            failures.append(f"decoded proof must not claim runtime: {proof_plan}")
        if proof_plan.get("proof_blockers") != []:
            failures.append(f"decoded proof blockers should be empty: {proof_plan}")
        if "decoded_rows_sample" not in proof_plan:
            failures.append(f"decoded proof must include a bounded sample: {proof_plan}")
        if "decoded_rows" in proof_plan:
            failures.append(f"decoded proof should not dump all rows: {proof_plan}")
    runtime_order = micc_final.get("runtime_order_proof_plan", {})
    if not isinstance(runtime_order, dict) or runtime_order.get("status") != (
        "decoded_wait_leaf_policy_available_runtime_trace_missing"
    ):
        failures.append(f"MICC runtime order proof has unexpected status: {micc_final}")
    if runtime_order.get("decoded_struct_roundtrip_claim") is not True:
        failures.append(f"MICC runtime order should consume decoded structs: {micc_final}")
    if runtime_order.get("local_order_policy_claim") is not True:
        failures.append(f"MICC local order policy should be closed: {micc_final}")
    if runtime_order.get("runtime_start_wait_trace_claim") is not False:
        failures.append(f"MICC runtime trace must remain unclaimed: {micc_final}")
    if runtime_order.get("runtime_ready_candidate") is not False:
        failures.append(f"MICC runtime order must remain non-runnable: {micc_final}")
    expected_proof_statuses = {
        "task_active_subtask_order": "available",
        "task_start_end_policy": "available",
        "subtask_successor_order": "available",
        "embedded_exeblock_roundtrip": "available",
        "instance_table_address_roundtrip": "available",
        "exeBlock_instruction_range_roundtrip": "available",
        "exeBlock_wait_or_dependency_flags": (
            "available_debug_structural_dependency_policy"
        ),
        "exeBlock_is_leaf_policy": "available_debug_conservative_zero_policy",
        "runtime_start_wait_trace": "blocked_missing_runtime_trace",
    }
    if runtime_order.get("proof_statuses") != expected_proof_statuses:
        failures.append(
            f"unexpected MICC runtime proof statuses: {runtime_order}"
        )
    final_blockers = set(micc_final.get("blockers", ()))
    for closed_blocker in (
        "decoded_task_conf_info_roundtrip_missing",
        "decoded_sub_task_conf_info_roundtrip_missing",
        "decoded_exeBlock_conf_info_roundtrip_missing",
        "runtime_order_decoded_roundtrip_missing",
        "task_active_subtask_order_proof_missing",
        "task_start_end_runtime_policy_unproven",
        "subtask_successor_order_proof_missing",
        "embedded_exeblock_roundtrip_missing",
        "instance_table_address_roundtrip_missing",
        "exeBlock_instruction_range_roundtrip_missing",
        "exeBlock_wait_or_dependency_flags_unproven",
        "exeBlock_is_leaf_policy_unproven",
    ):
        if closed_blocker in final_blockers:
            failures.append(f"closed decoded blocker still present: {closed_blocker}")
    if set(runtime_order.get("closed_blockers", ())) != {
        "task_active_subtask_order_proof_missing",
        "task_start_end_runtime_policy_unproven",
        "subtask_successor_order_proof_missing",
        "embedded_exeblock_roundtrip_missing",
        "instance_table_address_roundtrip_missing",
        "exeBlock_instruction_range_roundtrip_missing",
        "exeBlock_wait_or_dependency_flags_unproven",
        "exeBlock_is_leaf_policy_unproven",
    }:
        failures.append(f"unexpected runtime closed blockers: {runtime_order}")
    if "runtime_start_wait_trace_missing" not in final_blockers:
        failures.append(f"runtime trace blocker must remain: {micc_final}")
    if final_blockers != {"runtime_start_wait_trace_missing"}:
        failures.append(f"unexpected final MICC blockers: {final_blockers}")
    if runtime_order.get("wait_dependency_policy_proof", {}).get("status") != (
        "available_debug_structural_dependency_policy"
    ):
        failures.append(f"wait/dependency proof should be available: {runtime_order}")
    if runtime_order.get("is_leaf_policy_proof", {}).get("status") != (
        "available_debug_conservative_zero_policy"
    ):
        failures.append(f"is_leaf proof should be available: {runtime_order}")

    if failures:
        print("stream compiler MICC writer check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler MICC writer check PASS")
    print("task_conf_info_t=debug_only rows=4 payload_size_bytes=480")
    print("exeBlock_conf_info_t=debug_only rows=128 payload_size_bytes=66560")
    print(
        "sub_task_conf_info_t=debug_only selected_rows=8 "
        "payload_size_bytes=2130624 advanced_from_payload_size_bytes=0"
    )
    print("runtime_ready_candidate=False")
    print("selection_complete=True")
    print("selected_representations=8 zero_instance_control")
    print(
        "remaining_runtime_gaps="
        "decoded MICC order/wait/leaf policy available; runtime trace missing"
    )


def _component_and_readiness(profile: str):
    pipeline = build_demo_pipeline(profile)
    artifact = emit_debug_row_artifact(pipeline.binary_layout)
    groups = group_debug_rows_vendor_like(artifact)
    remap = remap_vendor_like_groups_locally(groups)
    component_plan = build_vendor_component_plan(
        remap,
        loop_fold_report=analyze_stream_loop_folding(pipeline.schedule),
    )
    offset_plan = build_field_offset_preflight_plan(component_plan)
    readiness = build_serializer_readiness_plan(component_plan, offset_plan)
    return component_plan, readiness


def _expect_address(
    records: list[dict[str, object]],
    failures: list[str],
    *,
    task_idx: int,
    subtask_idx: int,
    row_index: int,
    instances_amount: int,
    address: int,
) -> None:
    matches = [
        record
        for record in records
        if record["task_idx"] == task_idx and record["subtask_idx"] == subtask_idx
    ]
    if len(matches) != 1:
        failures.append(f"expected one address for task/subtask: {task_idx}/{subtask_idx}")
        return
    observed = matches[0]
    expected = {
        "row_index": row_index,
        "byte_offset": row_index * 32,
        "instances_amount": instances_amount,
        "address": address,
        "addr_space": "instance_component_offset",
        "unit": "bytes",
    }
    for key, value in expected.items():
        if observed.get(key) != value:
            failures.append(
                f"unexpected address {task_idx}/{subtask_idx} {key}: "
                f"expected {value}, got {observed.get(key)}"
            )


def _expect_evidence(
    plan: dict[str, object],
    failures: list[str],
    expected_text: str,
) -> None:
    evidence = plan.get("evidence_report")
    if not isinstance(evidence, dict):
        failures.append(f"missing evidence_report: {plan}")
        return
    haystack = str(evidence.get("source_backed", [])) + str(
        evidence.get("fail_closed", [])
    )
    if expected_text not in haystack:
        failures.append(f"missing evidence text {expected_text!r}: {evidence}")


def _check_semantics_report(
    plan: dict[str, object],
    failures: list[str],
) -> None:
    if plan.get("selection_complete") is not True:
        failures.append(f"selection should be complete: {plan}")
    if plan.get("selection_status") != "complete":
        failures.append(f"unexpected selection_status: {plan}")
    if plan.get("runtime_ready_candidate") is not False:
        failures.append(f"runtime bytes should remain non-runnable: {plan}")
    if plan.get("runtime_ready_status") != "runtime_bytes_deferred":
        failures.append(f"unexpected runtime_ready_status: {plan}")
    if plan.get("blocked_subtask_count") != 0:
        failures.append(f"expected 0 blocked subtasks after selection: {plan}")
    if plan.get("selected_subtask_count") != 8:
        failures.append(f"expected 8 selected subtasks: {plan}")
    records = plan.get("records")
    if not isinstance(records, list) or len(records) != 8:
        failures.append(f"expected 8 semantics records: {plan}")
        return
    selected_counts: dict[str, int] = {}
    policy_counts: dict[str, int] = {}
    selected_amount_counts: dict[int, int] = {}
    address_policy_counts: dict[str, int] = {}
    for record in records:
        selected = str(record.get("selected_representation"))
        selected_counts[selected] = selected_counts.get(selected, 0) + 1
        policy = str(record.get("selection_policy"))
        policy_counts[policy] = policy_counts.get(policy, 0) + 1
        if record.get("selection_status") != "selected":
            failures.append(f"record should be selected: {record}")
        selected_amount = record.get("selected_instances_amount")
        if not isinstance(selected_amount, int):
            failures.append(f"missing selected_instances_amount: {record}")
        else:
            selected_amount_counts[selected_amount] = (
                selected_amount_counts.get(selected_amount, 0) + 1
            )
        address_policy = str(record.get("address_policy"))
        address_policy_counts[address_policy] = (
            address_policy_counts.get(address_policy, 0) + 1
        )
        invariant = record.get("address_invariant")
        if invariant != (
            "instances_amount==0 => address=0 ignored; "
            "instances_amount>0 and address=0 => row0"
        ):
            failures.append(f"missing address invariant: {record}")
    expected_selected = {"zero_instance_control": 8}
    if selected_counts != expected_selected:
        failures.append(f"unexpected selected representations: {selected_counts}")
    expected_policies = {"zero_instance_control": 8}
    if policy_counts != expected_policies:
        failures.append(f"unexpected selection policies: {policy_counts}")
    if selected_amount_counts != {0: 8}:
        failures.append(f"unexpected selected instance counts: {selected_amount_counts}")
    expected_address_policies = {"zero_instances_address_ignored": 8}
    if address_policy_counts != expected_address_policies:
        failures.append(f"unexpected address policies: {address_policy_counts}")
    rules = plan.get("representation_rules")
    if not isinstance(rules, dict):
        failures.append(f"missing representation rules: {plan}")
        return
    if "no_implicit_mixing" not in rules:
        failures.append(f"missing no_implicit_mixing rule: {rules}")
    if "folded_k_stream_required_when" not in rules:
        failures.append(f"missing folded rule: {rules}")
    if "zero_instance_control_allowed_when" not in rules:
        failures.append(f"missing zero-instance rule: {rules}")
    selection = plan.get("selection_artifact")
    if not isinstance(selection, dict):
        failures.append(f"missing selection artifact: {plan}")
        return
    if selection.get("artifact") != "b_line_subtask_instance_representation_selection":
        failures.append(f"unexpected selection artifact name: {selection}")
    if selection.get("selection_complete") is not True:
        failures.append(f"selection artifact should be complete: {selection}")
    if selection.get("selected_representation_counts") != expected_selected:
        failures.append(f"unexpected selection artifact counts: {selection}")
    if selection.get("selection_policy_counts") != expected_policies:
        failures.append(f"unexpected selection artifact policies: {selection}")
    remaining = plan.get("remaining_runtime_gaps")
    if not isinstance(remaining, list) or not remaining:
        failures.append(f"missing remaining runtime gaps: {plan}")


if __name__ == "__main__":
    main()
