"""Vendor component skeletons for B-line debug rows.

This is the next report-only step after vendor-like local remapping.  It
projects local-remap groups into component-shaped JSON sections:

    inst_rows
    exeblock_rows
    task_rows
    subtask_rows
    instance_rows
    zero_boundaries

It still does not write bytes and does not claim vendor ABI compatibility.
"""

from __future__ import annotations

from dataclasses import dataclass

from gpdpu_compiler.core.dfu3500 import (
    DFU3500_DEFAULT_TILE,
    DFU3500_GEMM_REGIONS,
    DFU3500_MEMORY_LAYOUT,
    DFU3500_PHYSICAL_TOPOLOGY,
    DFU3500_STRUCT_SIZES,
    DFU3500_VENDOR_LIMITS,
)

from .folding import StreamLoopFoldCandidate, StreamLoopFoldReport
from .template_ops import Diagnostic
from .vendor_groups import VendorLikeLocalRemapPlan

UNUSED_BASE_ADDR_WORD = 0xFFFFFFFF


@dataclass(frozen=True)
class VendorComponentPlan:
    """Report-only vendor component skeleton."""

    profile_id: str
    runnability_state: str
    inst_rows: tuple[dict[str, object], ...]
    exeblock_rows: tuple[dict[str, object], ...]
    task_rows: tuple[dict[str, object], ...]
    subtask_rows: tuple[dict[str, object], ...]
    instance_rows: tuple[dict[str, object], ...]
    zero_boundaries: tuple[dict[str, object], ...]
    capacity_report: dict[str, object]
    diagnostics: tuple[Diagnostic, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_vendor_component_plan",
            "profile_id": self.profile_id,
            "runnability_state": self.runnability_state,
            "inst_rows": list(self.inst_rows),
            "exeblock_rows": list(self.exeblock_rows),
            "task_rows": list(self.task_rows),
            "subtask_rows": list(self.subtask_rows),
            "instance_rows": list(self.instance_rows),
            "zero_boundaries": list(self.zero_boundaries),
            "capacity_report": self.capacity_report,
            "diagnostics": [
                diagnostic.to_plan() for diagnostic in self.diagnostics
            ],
            "layering_policy": (
                "vendor_component_plan_consumes_vendor_like_local_remap_plan;"
                "projects_component_sections_without_writing_binary_bytes"
            ),
        }


def build_vendor_component_plan(
    remap: VendorLikeLocalRemapPlan,
    *,
    loop_fold_report: StreamLoopFoldReport | None = None,
) -> VendorComponentPlan:
    """Project local-remap groups into component-shaped sections."""

    inst_rows: list[dict[str, object]] = []
    zero_boundaries: list[dict[str, object]] = []
    exeblock_buckets: dict[tuple[int | None, str, str, str | None], dict[str, object]] = {}
    pe_local_exeblock_counts: dict[str, int] = {}
    task_accumulator: dict[int, dict[str, object]] = {}
    subtask_accumulator: dict[tuple[int | None, str], dict[str, object]] = {}
    instance_accumulator: dict[tuple[int | None, str, str], dict[str, object]] = {}

    for group in remap.groups:
        task_id = group.task_id
        _ensure_task(task_accumulator, task_id)
        subtask = _ensure_subtask(subtask_accumulator, task_id, group.subtask_slot)
        if group.loop_instance is not None:
            _ensure_instance(
                instance_accumulator,
                task_id,
                group.subtask_slot,
                group.loop_instance,
            )
        for row in group.instruction_rows:
            component_row = _inst_component_row(group, row, len(inst_rows))
            inst_rows.append(component_row)
            bucket = _ensure_exeblock_bucket(exeblock_buckets, group, component_row)
            bucket["source_instruction_component_indices"].append(
                component_row["component_index"]
            )
            bucket["source_global_pcs"].append(component_row["global_pc"])
            _record_bucket_stage(bucket, component_row)
            _increment(
                task_accumulator[task_id if task_id is not None else -1],
                "inst_count",
            )
            _increment(subtask, "inst_count")
            if group.loop_instance is not None:
                instance = _ensure_instance(
                    instance_accumulator,
                    task_id,
                    group.subtask_slot,
                    group.loop_instance,
                )
                _increment(instance, "inst_count")
        for boundary in group.zero_boundaries:
            zero_row = _zero_component_row(group, boundary, len(zero_boundaries))
            zero_boundaries.append(zero_row)
            bucket = _ensure_exeblock_bucket(exeblock_buckets, group, zero_row)
            bucket["source_zero_boundary_indices"].append(zero_row["component_index"])
            _increment(
                task_accumulator[task_id if task_id is not None else -1],
                "zero_boundary_count",
            )
            _increment(subtask, "zero_boundary_count")

    _assign_candidate_pe_local_instruction_pcs(inst_rows)

    exeblock_rows = _finalize_exeblock_rows(
        exeblock_buckets,
        inst_rows,
        pe_local_exeblock_counts,
        task_accumulator,
        subtask_accumulator,
    )
    task_rows = [
        task_accumulator[key]
        for key in sorted(task_accumulator)
    ]
    subtask_rows = [
        subtask_accumulator[key]
        for key in sorted(subtask_accumulator, key=_subtask_key_sort)
    ]
    instance_rows = [
        instance_accumulator[key]
        for key in sorted(instance_accumulator, key=_instance_key_sort)
    ]
    for component_index, row in enumerate(instance_rows):
        row["component_index"] = component_index
    _assign_report_only_micc_struct_views(
        task_rows,
        subtask_rows,
        instance_rows,
        exeblock_rows,
        loop_fold_report=loop_fold_report,
    )

    return VendorComponentPlan(
        profile_id=remap.profile_id,
        runnability_state=remap.runnability_state,
        inst_rows=tuple(inst_rows),
        exeblock_rows=tuple(exeblock_rows),
        task_rows=tuple(task_rows),
        subtask_rows=tuple(subtask_rows),
        instance_rows=tuple(instance_rows),
        zero_boundaries=tuple(zero_boundaries),
        capacity_report=_capacity_report(
            inst_count=len(inst_rows),
            task_count=len(task_accumulator),
            subtask_count=len(subtask_accumulator),
            instance_count=len(instance_accumulator),
            exeblock_count=len(exeblock_rows),
            zero_boundary_count=len(zero_boundaries),
        ),
        diagnostics=remap.diagnostics,
    )


def summarize_vendor_component_plan(plan: VendorComponentPlan) -> dict[str, object]:
    """Return stable component counts."""

    diagnostic_severity_counts: dict[str, int] = {}
    opcode_counts: dict[str, int] = {}
    task_inst_counts: dict[str, int] = {}
    task_exeblock_counts: dict[str, int] = {}
    subtask_inst_counts: dict[str, int] = {}
    subtask_exeblock_counts: dict[str, int] = {}
    instance_inst_counts: dict[str, int] = {}
    pe_local_exeblock_counts: dict[str, int] = {}
    task_candidate_struct_view_count = 0
    task_candidate_struct_binary_encoded_count = 0
    task_candidate_active_subtask_total = 0
    subtask_candidate_struct_view_count = 0
    subtask_candidate_struct_binary_encoded_count = 0
    subtask_candidate_successor_edge_count = 0
    subtask_candidate_root_block_total = 0
    subtask_candidate_block_total = 0
    subtask_candidate_observed_loop_instance_total = 0
    folded_subtask_candidate_overlay_count = 0
    folded_subtask_candidate_binary_encoded_count = 0
    folded_subtask_candidate_instances_amount_total = 0
    folded_subtask_candidate_stream_total = 0
    folded_subtask_candidate_shape_total = 0
    folded_subtask_candidate_signature_total = 0
    folded_subtask_candidate_projection_proof_count = 0
    instance_candidate_struct_view_count = 0
    instance_candidate_struct_binary_encoded_count = 0
    instance_candidate_base_addr_resolved_count = 0
    instance_candidate_base_addr_unresolved_count = 0
    instance_candidate_base_addr_disabled_count = 0
    instance_candidate_base_addr_slot_shape_error_count = 0
    forbidden_tile_micro_block_fields = 0
    missing_provenance_count = 0
    candidate_pe_local_pc_row_count = 0
    candidate_pe_local_pc_binary_encoded_count = 0
    candidate_pe_local_pc_missing_count = 0
    non_dense_component_index_count = 0
    non_dense_exeblock_index_count = 0
    pe_local_exeblock_overflow_count = 0
    exeblock_dependency_edge_count = 0
    exeblock_slot_shape_error_count = 0
    exeblock_vendor_row_slot_shape_error_count = 0
    exeblock_candidate_endpoint_slot_shape_error_count = 0
    exeblock_padded_slot_row_count = 0
    exeblock_candidate_vendor_row_identity_count = 0
    exeblock_candidate_endpoint_valid_count = 0
    exeblock_candidate_struct_view_count = 0
    exeblock_candidate_struct_binary_encoded_count = 0
    exeblock_candidate_struct_candidate_pc_count = 0
    exeblock_candidate_struct_unresolved_pc_count = 0
    exeblock_candidate_struct_inst_base_count = 0
    exeblock_dependency_proof_counts: dict[str, int] = {}
    exeblock_predecessor_overflow_count = 0
    exeblock_successor_overflow_count = 0

    for diagnostic in plan.diagnostics:
        diagnostic_severity_counts[diagnostic.severity] = (
            diagnostic_severity_counts.get(diagnostic.severity, 0) + 1
        )
    for expected_index, row in enumerate(plan.inst_rows):
        if row.get("component_index") != expected_index:
            non_dense_component_index_count += 1
        opcode = str(row.get("opcode"))
        opcode_counts[opcode] = opcode_counts.get(opcode, 0) + 1
        task_key = str(row.get("task_id"))
        subtask_key = str(row.get("subtask_slot"))
        loop_key = str(row.get("loop_instance"))
        task_inst_counts[task_key] = task_inst_counts.get(task_key, 0) + 1
        subtask_inst_counts[subtask_key] = subtask_inst_counts.get(subtask_key, 0) + 1
        instance_inst_counts[loop_key] = instance_inst_counts.get(loop_key, 0) + 1
        forbidden_tile_micro_block_fields += _forbidden_field_count(row)
        if not row.get("template_op_id") or not row.get("primary_fiber_op_id"):
            missing_provenance_count += 1
        if isinstance(row.get("candidate_pe_local_pc"), int):
            candidate_pe_local_pc_row_count += 1
        else:
            candidate_pe_local_pc_missing_count += 1
        if row.get("candidate_pe_local_pc_binary_encoded") is True:
            candidate_pe_local_pc_binary_encoded_count += 1
    for row in plan.task_rows:
        task_struct = row.get("task_conf_info_candidate")
        if isinstance(task_struct, dict):
            task_candidate_struct_view_count += 1
            if task_struct.get("binary_encoded") is True:
                task_candidate_struct_binary_encoded_count += 1
            task_candidate_active_subtask_total += int(
                task_struct.get("subtasks_amount", 0)
            )
    for row in plan.subtask_rows:
        subtask_struct = row.get("sub_task_conf_info_candidate")
        if isinstance(subtask_struct, dict):
            subtask_candidate_struct_view_count += 1
            if subtask_struct.get("binary_encoded") is True:
                subtask_candidate_struct_binary_encoded_count += 1
            successors = row.get("successor_subtask_indices", [])
            if isinstance(successors, list):
                subtask_candidate_successor_edge_count += len(successors)
            subtask_candidate_root_block_total += int(
                subtask_struct.get("root_block_amount", 0)
            )
            subtask_candidate_block_total += int(subtask_struct.get("block_amount", 0))
            subtask_candidate_observed_loop_instance_total += int(
                subtask_struct.get("observed_loop_instance_count", 0)
            )
        folded_struct = row.get("folded_subtask_conf_candidate")
        if isinstance(folded_struct, dict):
            folded_subtask_candidate_overlay_count += 1
            if folded_struct.get("binary_encoded") is True:
                folded_subtask_candidate_binary_encoded_count += 1
            folded_subtask_candidate_instances_amount_total += int(
                folded_struct.get("instances_amount", 0)
            )
            folded_subtask_candidate_stream_total += int(
                folded_struct.get("stream_candidate_count", 0)
            )
            shape_counts = folded_struct.get("stream_body_shape_counts", {})
            if isinstance(shape_counts, dict):
                folded_subtask_candidate_shape_total += len(shape_counts)
            signature_counts = folded_struct.get("stream_fold_body_signature_counts", {})
            if isinstance(signature_counts, dict):
                folded_subtask_candidate_signature_total += len(signature_counts)
            if isinstance(folded_struct.get("target_fold_projection_proof"), dict):
                folded_subtask_candidate_projection_proof_count += 1
    for row in plan.instance_rows:
        instance_struct = row.get("instance_conf_info_candidate")
        if isinstance(instance_struct, dict):
            instance_candidate_struct_view_count += 1
            if instance_struct.get("binary_encoded") is True:
                instance_candidate_struct_binary_encoded_count += 1
            base_addr_slots = instance_struct.get("base_addr", [])
            expected_slot_count = int(
                DFU3500_VENDOR_LIMITS["base_addr_slots_per_instance"]
            )
            if (
                not isinstance(base_addr_slots, list)
                or len(base_addr_slots) != expected_slot_count
            ):
                instance_candidate_base_addr_slot_shape_error_count += 1
                base_addr_slots = []
            for slot in base_addr_slots:
                if not isinstance(slot, dict):
                    instance_candidate_base_addr_slot_shape_error_count += 1
                    continue
                status = slot.get("status")
                if status == "resolved":
                    instance_candidate_base_addr_resolved_count += 1
                elif status == "unresolved":
                    instance_candidate_base_addr_unresolved_count += 1
                elif status == "disabled_sentinel":
                    instance_candidate_base_addr_disabled_count += 1
    for expected_index, row in enumerate(plan.exeblock_rows):
        if row.get("component_index") != expected_index:
            non_dense_exeblock_index_count += 1
        task_key = str(row.get("task_id"))
        subtask_key = str(row.get("subtask_slot"))
        pe_key = str(row.get("physical_pe_id"))
        task_exeblock_counts[task_key] = task_exeblock_counts.get(task_key, 0) + 1
        subtask_exeblock_counts[subtask_key] = (
            subtask_exeblock_counts.get(subtask_key, 0) + 1
        )
        pe_local_exeblock_counts[pe_key] = pe_local_exeblock_counts.get(pe_key, 0) + 1
        if row.get("pe_local_exeblock_index_overflows"):
            pe_local_exeblock_overflow_count += 1
        if row.get("candidate_vendor_row_index") == row.get("component_index"):
            exeblock_candidate_vendor_row_identity_count += 1
        struct_view = row.get("exeBlock_conf_info_candidate")
        if isinstance(struct_view, dict):
            exeblock_candidate_struct_view_count += 1
            if struct_view.get("binary_encoded") is True:
                exeblock_candidate_struct_binary_encoded_count += 1
            exe_block_conf = struct_view.get("exeBlock_conf", {})
            if (
                isinstance(exe_block_conf, dict)
                and exe_block_conf.get("stage_start_pc_policy")
                == "candidate_dense_per_physical_pe_instruction_order"
            ):
                exeblock_candidate_struct_candidate_pc_count += 1
            if (
                isinstance(exe_block_conf, dict)
                and exe_block_conf.get("stage_start_pc_policy")
                == "unresolved_pending_pe_local_pc_layout"
            ):
                exeblock_candidate_struct_unresolved_pc_count += 1
            if (
                isinstance(exe_block_conf, dict)
                and isinstance(exe_block_conf.get("inst_mem_based_addr"), int)
                and exe_block_conf.get("inst_mem_based_addr_policy")
                == "candidate_pe_local_start_pc_byte_offset"
            ):
                exeblock_candidate_struct_inst_base_count += 1
        predecessor_slots = row.get("predecessor_slots", ())
        successor_slots = row.get("successor_slots", ())
        predecessor_vendor_slots = row.get("predecessor_vendor_row_slots", ())
        successor_vendor_slots = row.get("successor_vendor_row_slots", ())
        predecessor_endpoint_slots = row.get("predecessor_endpoint_slots", ())
        successor_endpoint_slots = row.get("successor_endpoint_slots", ())
        slot_count = int(DFU3500_VENDOR_LIMITS["max_task_follow_per_task"])
        if (
            not isinstance(predecessor_slots, list)
            or not isinstance(successor_slots, list)
            or len(predecessor_slots) != slot_count
            or len(successor_slots) != slot_count
        ):
            exeblock_slot_shape_error_count += 1
        if (
            not isinstance(predecessor_vendor_slots, list)
            or not isinstance(successor_vendor_slots, list)
            or len(predecessor_vendor_slots) != slot_count
            or len(successor_vendor_slots) != slot_count
        ):
            exeblock_vendor_row_slot_shape_error_count += 1
        if (
            not isinstance(predecessor_endpoint_slots, list)
            or not isinstance(successor_endpoint_slots, list)
            or len(predecessor_endpoint_slots) != slot_count
            or len(successor_endpoint_slots) != slot_count
        ):
            exeblock_candidate_endpoint_slot_shape_error_count += 1
        else:
            for endpoint_slot in predecessor_endpoint_slots + successor_endpoint_slots:
                if not isinstance(endpoint_slot, dict):
                    exeblock_candidate_endpoint_slot_shape_error_count += 1
                    continue
                if endpoint_slot.get("valid") is True:
                    exeblock_candidate_endpoint_valid_count += 1
        if _has_invalid_endpoint_slot(predecessor_endpoint_slots) or _has_invalid_endpoint_slot(
            successor_endpoint_slots
        ):
            exeblock_padded_slot_row_count += 1
        successors = row.get("successor_component_indices", ())
        if isinstance(successors, list):
            exeblock_dependency_edge_count += len(successors)
        exeblock_predecessor_overflow_count += int(row.get("predecessor_overflow_count", 0))
        exeblock_successor_overflow_count += int(row.get("successor_overflow_count", 0))
        proofs = row.get("dependency_proofs", ())
        if isinstance(proofs, list):
            for proof in proofs:
                if not isinstance(proof, dict):
                    continue
                if proof.get("target_component_index") == row.get("component_index"):
                    proof_kind = str(proof.get("proof_kind"))
                    exeblock_dependency_proof_counts[proof_kind] = (
                        exeblock_dependency_proof_counts.get(proof_kind, 0) + 1
                    )
        forbidden_tile_micro_block_fields += _forbidden_field_count(row)
        if not row.get("source_instruction_component_indices"):
            missing_provenance_count += 1
    for row in plan.zero_boundaries:
        forbidden_tile_micro_block_fields += _forbidden_field_count(row)
        if not row.get("template_op_id") or not row.get("primary_fiber_op_id"):
            missing_provenance_count += 1

    return {
        "profile_id": plan.profile_id,
        "runnability_state": plan.runnability_state,
        "inst_row_count": len(plan.inst_rows),
        "exeblock_row_count": len(plan.exeblock_rows),
        "task_row_count": len(plan.task_rows),
        "subtask_row_count": len(plan.subtask_rows),
        "instance_row_count": len(plan.instance_rows),
        "zero_boundary_count": len(plan.zero_boundaries),
        "modeled_component_capacity_ok": _modeled_component_capacity_ok(
            plan.capacity_report
        ),
        "missing_required_component_kinds": _missing_required_component_kinds(
            plan.capacity_report
        ),
        "opcode_counts": dict(sorted(opcode_counts.items())),
        "task_inst_counts": dict(sorted(task_inst_counts.items())),
        "task_exeblock_counts": dict(sorted(task_exeblock_counts.items())),
        "subtask_inst_counts": dict(sorted(subtask_inst_counts.items())),
        "subtask_exeblock_counts": dict(sorted(subtask_exeblock_counts.items())),
        "instance_inst_counts": dict(sorted(instance_inst_counts.items())),
        "pe_local_exeblock_counts": dict(sorted(pe_local_exeblock_counts.items())),
        "diagnostic_severity_counts": dict(sorted(diagnostic_severity_counts.items())),
        "diagnostic_count": len(plan.diagnostics),
        "missing_provenance_count": missing_provenance_count,
        "candidate_pe_local_pc_row_count": candidate_pe_local_pc_row_count,
        "candidate_pe_local_pc_binary_encoded_count": (
            candidate_pe_local_pc_binary_encoded_count
        ),
        "candidate_pe_local_pc_missing_count": candidate_pe_local_pc_missing_count,
        "task_candidate_struct_view_count": task_candidate_struct_view_count,
        "task_candidate_struct_binary_encoded_count": (
            task_candidate_struct_binary_encoded_count
        ),
        "task_candidate_active_subtask_total": task_candidate_active_subtask_total,
        "subtask_candidate_struct_view_count": subtask_candidate_struct_view_count,
        "subtask_candidate_struct_binary_encoded_count": (
            subtask_candidate_struct_binary_encoded_count
        ),
        "subtask_candidate_successor_edge_count": (
            subtask_candidate_successor_edge_count
        ),
        "subtask_candidate_root_block_total": subtask_candidate_root_block_total,
        "subtask_candidate_block_total": subtask_candidate_block_total,
        "subtask_candidate_observed_loop_instance_total": (
            subtask_candidate_observed_loop_instance_total
        ),
        "folded_subtask_candidate_overlay_count": (
            folded_subtask_candidate_overlay_count
        ),
        "folded_subtask_candidate_binary_encoded_count": (
            folded_subtask_candidate_binary_encoded_count
        ),
        "folded_subtask_candidate_instances_amount_total": (
            folded_subtask_candidate_instances_amount_total
        ),
        "folded_subtask_candidate_stream_total": (
            folded_subtask_candidate_stream_total
        ),
        "folded_subtask_candidate_shape_total": (
            folded_subtask_candidate_shape_total
        ),
        "folded_subtask_candidate_signature_total": (
            folded_subtask_candidate_signature_total
        ),
        "folded_subtask_candidate_projection_proof_count": (
            folded_subtask_candidate_projection_proof_count
        ),
        "instance_candidate_struct_view_count": instance_candidate_struct_view_count,
        "instance_candidate_struct_binary_encoded_count": (
            instance_candidate_struct_binary_encoded_count
        ),
        "instance_candidate_base_addr_resolved_count": (
            instance_candidate_base_addr_resolved_count
        ),
        "instance_candidate_base_addr_unresolved_count": (
            instance_candidate_base_addr_unresolved_count
        ),
        "instance_candidate_base_addr_disabled_count": (
            instance_candidate_base_addr_disabled_count
        ),
        "instance_candidate_base_addr_slot_shape_error_count": (
            instance_candidate_base_addr_slot_shape_error_count
        ),
        "forbidden_tile_micro_block_field_count": forbidden_tile_micro_block_fields,
        "non_dense_component_index_count": non_dense_component_index_count,
        "non_dense_exeblock_index_count": non_dense_exeblock_index_count,
        "pe_local_exeblock_overflow_count": pe_local_exeblock_overflow_count,
        "exeblock_dependency_edge_count": exeblock_dependency_edge_count,
        "exeblock_dependency_proof_counts": dict(
            sorted(exeblock_dependency_proof_counts.items())
        ),
        "exeblock_predecessor_overflow_count": exeblock_predecessor_overflow_count,
        "exeblock_successor_overflow_count": exeblock_successor_overflow_count,
        "exeblock_slot_shape_error_count": exeblock_slot_shape_error_count,
        "exeblock_vendor_row_slot_shape_error_count": (
            exeblock_vendor_row_slot_shape_error_count
        ),
        "exeblock_candidate_endpoint_slot_shape_error_count": (
            exeblock_candidate_endpoint_slot_shape_error_count
        ),
        "exeblock_padded_slot_row_count": exeblock_padded_slot_row_count,
        "exeblock_candidate_vendor_row_identity_count": (
            exeblock_candidate_vendor_row_identity_count
        ),
        "exeblock_candidate_endpoint_valid_count": (
            exeblock_candidate_endpoint_valid_count
        ),
        "exeblock_candidate_struct_view_count": exeblock_candidate_struct_view_count,
        "exeblock_candidate_struct_binary_encoded_count": (
            exeblock_candidate_struct_binary_encoded_count
        ),
        "exeblock_candidate_struct_candidate_pc_count": (
            exeblock_candidate_struct_candidate_pc_count
        ),
        "exeblock_candidate_struct_unresolved_pc_count": (
            exeblock_candidate_struct_unresolved_pc_count
        ),
        "exeblock_candidate_struct_inst_base_count": (
            exeblock_candidate_struct_inst_base_count
        ),
    }


def _capacity_report(
    *,
    inst_count: int,
    task_count: int,
    subtask_count: int,
    instance_count: int,
    exeblock_count: int,
    zero_boundary_count: int,
) -> dict[str, object]:
    pe_amount = int(DFU3500_VENDOR_LIMITS["pe_amount"])
    max_inst_amount_per_pe = int(DFU3500_VENDOR_LIMITS["max_inst_amount_per_pe"])
    max_tasks = int(DFU3500_VENDOR_LIMITS["max_tasks"])
    max_subtasks_per_task = int(DFU3500_VENDOR_LIMITS["max_subtasks_per_task"])
    max_instances_per_subtask = int(DFU3500_VENDOR_LIMITS["max_instances_per_subtask"])
    max_exe_block = int(DFU3500_VENDOR_LIMITS["max_exe_block"])
    inst_capacity = pe_amount * max_inst_amount_per_pe
    subtask_capacity = max_tasks * max_subtasks_per_task
    instance_capacity = subtask_capacity * max_instances_per_subtask
    return {
        "inst_rows": _component_capacity(
            active=inst_count,
            capacity=inst_capacity,
            record_size_bytes=int(DFU3500_STRUCT_SIZES["inst_t"]),
            modeled=True,
        ),
        "task_rows": _component_capacity(
            active=task_count,
            capacity=max_tasks,
            record_size_bytes=int(DFU3500_STRUCT_SIZES["task_conf_info_t"]),
            modeled=True,
        ),
        "subtask_rows": _component_capacity(
            active=subtask_count,
            capacity=subtask_capacity,
            record_size_bytes=int(DFU3500_STRUCT_SIZES["sub_task_conf_info_t"]),
            modeled=True,
        ),
        "instance_rows": _component_capacity(
            active=instance_count,
            capacity=instance_capacity,
            record_size_bytes=int(DFU3500_STRUCT_SIZES["instance_conf_info_t"]),
            modeled=True,
        ),
        "exeblock_rows": _component_capacity(
            active=exeblock_count,
            capacity=max_exe_block,
            record_size_bytes=int(DFU3500_STRUCT_SIZES["exeBlock_conf_info_t"]),
            modeled=True,
            status="report_only_stream_local_blocks",
        ),
        "zero_boundaries": {
            "active_row_count": zero_boundary_count,
            "capacity": None,
            "record_size_bytes": 0,
            "fits_capacity": True,
            "modeled": True,
            "occupies_binary_rows": False,
            "status": "semantic_boundary_only",
        },
    }


def _component_capacity(
    *,
    active: int,
    capacity: int,
    record_size_bytes: int,
    modeled: bool,
    status: str = "modeled",
) -> dict[str, object]:
    return {
        "active_row_count": active,
        "capacity": capacity,
        "record_size_bytes": record_size_bytes,
        "padded_component_size_bytes": capacity * record_size_bytes,
        "fits_capacity": active <= capacity,
        "modeled": modeled,
        "status": status,
    }


def _modeled_component_capacity_ok(report: dict[str, object]) -> bool:
    for payload in report.values():
        if not isinstance(payload, dict):
            continue
        if payload.get("modeled") and not payload.get("fits_capacity"):
            return False
    return True


def _has_invalid_endpoint_slot(slots: object) -> bool:
    if not isinstance(slots, list):
        return False
    return any(
        isinstance(slot, dict) and slot.get("valid") is False
        for slot in slots
    )


def _missing_required_component_kinds(report: dict[str, object]) -> list[str]:
    missing: list[str] = []
    for name, payload in report.items():
        if isinstance(payload, dict) and not payload.get("modeled", True):
            missing.append(str(name))
    return sorted(missing)


def _inst_component_row(
    group: object,
    row: dict[str, object],
    component_index: int,
) -> dict[str, object]:
    return {
        "component": "inst_rows",
        "component_index": component_index,
        "task_id": row.get("task_id"),
        "subtask_slot": row.get("subtask_slot"),
        "loop_instance": row.get("loop_instance"),
        "group_id": group.group_id,
        "local_row_index": row.get("local_row_index"),
        "local_pc": row.get("local_pc"),
        "global_row_index": row.get("global_row_index"),
        "global_pc": row.get("global_pc"),
        "opcode": row.get("opcode"),
        "role": row.get("role"),
        "stream_id": row.get("stream_id"),
        "physical_pe_id": _physical_pe_id(row.get("stream_id")),
        "template_op_id": row.get("template_op_id"),
        "source_schedule_step_id": row.get("source_schedule_step_id"),
        "primary_fiber_op_id": row.get("primary_fiber_op_id"),
        "attrs": row.get("attrs", {}),
    }


def _zero_component_row(
    group: object,
    row: dict[str, object],
    component_index: int,
) -> dict[str, object]:
    return {
        "component": "zero_boundaries",
        "component_index": component_index,
        "task_id": row.get("task_id"),
        "subtask_slot": row.get("subtask_slot"),
        "loop_instance": row.get("loop_instance"),
        "group_id": group.group_id,
        "local_boundary_index": row.get("local_boundary_index"),
        "local_pc": None,
        "boundary_kind": row.get("boundary_kind"),
        "role": row.get("role"),
        "stream_id": row.get("stream_id"),
        "physical_pe_id": _physical_pe_id(row.get("stream_id")),
        "template_op_id": row.get("template_op_id"),
        "source_schedule_step_id": row.get("source_schedule_step_id"),
        "primary_fiber_op_id": row.get("primary_fiber_op_id"),
        "attrs": row.get("attrs", {}),
    }


def _assign_candidate_pe_local_instruction_pcs(rows: list[dict[str, object]]) -> None:
    pe_counts: dict[str, int] = {}
    for row in rows:
        physical_pe_id = str(row.get("physical_pe_id"))
        pe_local_pc = pe_counts.get(physical_pe_id, 0)
        pe_counts[physical_pe_id] = pe_local_pc + 1
        row["candidate_pe_local_pc"] = pe_local_pc
        row["candidate_pe_local_pc_policy"] = "dense_per_physical_pe_instruction_order"
        row["candidate_pe_local_pc_binary_encoded"] = False


def _ensure_exeblock_bucket(
    accumulator: dict[tuple[int | None, str, str, str | None], dict[str, object]],
    group: object,
    row: dict[str, object],
) -> dict[str, object]:
    stream_id = str(row.get("stream_id"))
    key = (group.task_id, stream_id, group.subtask_slot, group.loop_instance)
    if key not in accumulator:
        accumulator[key] = {
            "component": "exeblock_rows",
            "task_id": group.task_id,
            "stream_id": stream_id,
            "physical_pe_id": _physical_pe_id(stream_id),
            "subtask_slot": group.subtask_slot,
            "loop_instance": group.loop_instance,
            "source_group_id": group.group_id,
            "source_instruction_component_indices": [],
            "source_zero_boundary_indices": [],
            "source_global_pcs": [],
            "stage_instruction_counts": {},
            "stage_opcodes": {},
        }
    return accumulator[key]


def _candidate_stage_start_pcs(
    inst_rows: list[dict[str, object]],
    instruction_indices: tuple[object, ...],
) -> dict[str, int]:
    stage_counts = {"LD": 0, "CAL": 0, "FLOW": 0, "ST": 0}
    start_pcs: list[int] = []
    for instruction_index in instruction_indices:
        if not isinstance(instruction_index, int):
            continue
        if instruction_index < 0 or instruction_index >= len(inst_rows):
            continue
        row = inst_rows[instruction_index]
        stage = _stage_for_opcode(row.get("opcode"))
        if stage is None:
            continue
        pe_local_pc = row.get("candidate_pe_local_pc")
        if not isinstance(pe_local_pc, int):
            continue
        stage_counts[stage] += 1
        start_pcs.append(pe_local_pc)
    base_pc = min(start_pcs, default=0)
    current_pc = base_pc
    candidates: dict[str, int] = {}
    for stage in ("LD", "CAL", "FLOW", "ST"):
        candidates[stage] = current_pc
        current_pc += stage_counts[stage]
    candidates["MAX_COMPONENT"] = current_pc
    return candidates


def _finalize_exeblock_rows(
    buckets: dict[tuple[int | None, str, str, str | None], dict[str, object]],
    inst_rows: list[dict[str, object]],
    pe_local_counts: dict[str, int],
    task_accumulator: dict[int, dict[str, object]],
    subtask_accumulator: dict[tuple[int | None, str], dict[str, object]],
) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for key in sorted(buckets, key=_exeblock_key_sort):
        bucket = buckets[key]
        physical_pe_id = str(bucket["physical_pe_id"])
        pe_local_index = pe_local_counts.get(physical_pe_id, 0)
        pe_local_counts[physical_pe_id] = pe_local_index + 1
        task_id = bucket["task_id"]
        subtask_slot = str(bucket["subtask_slot"])
        instruction_indices = tuple(bucket["source_instruction_component_indices"])
        zero_indices = tuple(bucket["source_zero_boundary_indices"])
        global_pcs = tuple(
            pc for pc in bucket["source_global_pcs"] if isinstance(pc, int)
        )
        row = {
            "component": "exeblock_rows",
            "component_index": len(rows),
            "task_id": task_id,
            "stream_id": bucket["stream_id"],
            "physical_pe_id": physical_pe_id,
            "candidate_vendor_row_index": len(rows),
            "candidate_vendor_row_index_policy": "dense_component_index_identity",
            "pe_local_exeblock_index": pe_local_index,
            "pe_local_exeblock_index_overflows": pe_local_index
            >= int(DFU3500_VENDOR_LIMITS["max_exe_block_per_pe"]),
            "subtask_slot": subtask_slot,
            "loop_instance": bucket["loop_instance"],
            "source_group_id": bucket["source_group_id"],
            "source_instruction_component_indices": list(instruction_indices),
            "source_zero_boundary_indices": list(zero_indices),
            "stage_instruction_counts": dict(
                sorted(bucket["stage_instruction_counts"].items())
            ),
            "stage_opcodes": {
                stage: list(opcodes)
                for stage, opcodes in sorted(bucket["stage_opcodes"].items())
            },
            "stage_start_pc_candidates": _candidate_stage_start_pcs(
                inst_rows,
                instruction_indices,
            ),
            "stage_start_pc_candidate_policy": (
                "dense_per_physical_pe_instruction_order"
            ),
            "instruction_count": len(instruction_indices),
            "zero_boundary_count": len(zero_indices),
            "global_pc_start": min(global_pcs) if global_pcs else None,
            "global_pc_end_exclusive": (max(global_pcs) + 1) if global_pcs else None,
            "predecessor_component_indices": [],
            "successor_component_indices": [],
            "dependency_proofs": [],
            "predecessor_slots": [],
            "successor_slots": [],
            "edge_slot_count": int(DFU3500_VENDOR_LIMITS["max_task_follow_per_task"]),
            "predecessor_overflow_count": 0,
            "successor_overflow_count": 0,
            "dependency_policy": "report_only_structural_chain",
            "slot_policy": "not_assigned_yet",
            "binary_encoded": False,
        }
        rows.append(row)
        _increment(
            task_accumulator[task_id if isinstance(task_id, int) else -1],
            "exeblock_count",
        )
        _increment(subtask_accumulator[(task_id, subtask_slot)], "exeblock_count")
    _attach_report_only_exeblock_dependencies(rows)
    _assign_report_only_exeblock_slots(rows)
    _assign_report_only_exeblock_struct_views(rows)
    return rows


def _attach_report_only_exeblock_dependencies(rows: list[dict[str, object]]) -> None:
    rows_by_stream: dict[tuple[object, object], list[dict[str, object]]] = {}
    for row in rows:
        key = (row.get("task_id"), row.get("stream_id"))
        rows_by_stream.setdefault(key, []).append(row)

    for stream_rows in rows_by_stream.values():
        pre = _find_exeblock(stream_rows, "subtask0_accumulator_prepare", None)
        post = _find_exeblock(stream_rows, "subtask3_finalize_store", None)
        loop_rows = sorted(
            (
                row
                for row in stream_rows
                if row.get("subtask_slot") == "subtask1_k_stream"
            ),
            key=lambda row: _loop_instance_index(row.get("loop_instance")),
        )
        if pre is not None and loop_rows:
            _add_exeblock_dependency(
                pre,
                loop_rows[0],
                proof_kind="subtask_order",
                reason="accumulator_prepare_subtask_precedes_k_stream",
            )
        for previous, current in zip(loop_rows, loop_rows[1:]):
            _add_exeblock_dependency(
                previous,
                current,
                proof_kind="loop_instance_order",
                reason="carried_accumulator_state_between_k_instances",
            )
        if loop_rows and post is not None:
            _add_exeblock_dependency(
                loop_rows[-1],
                post,
                proof_kind="subtask_order",
                reason="final_k_stream_subtask_precedes_finalize_store",
            )


def _assign_report_only_exeblock_slots(rows: list[dict[str, object]]) -> None:
    slot_count = int(DFU3500_VENDOR_LIMITS["max_task_follow_per_task"])
    for row in rows:
        predecessors = row.get("predecessor_component_indices", [])
        successors = row.get("successor_component_indices", [])
        if not isinstance(predecessors, list):
            predecessors = []
        if not isinstance(successors, list):
            successors = []
        row["predecessor_slots"] = _padded_edge_slots(predecessors, slot_count)
        row["successor_slots"] = _padded_edge_slots(successors, slot_count)
        row["predecessor_vendor_row_slots"] = _padded_edge_slots(
            _candidate_vendor_row_indices(rows, predecessors),
            slot_count,
        )
        row["successor_vendor_row_slots"] = _padded_edge_slots(
            _candidate_vendor_row_indices(rows, successors),
            slot_count,
        )
        row["predecessor_endpoint_slots"] = _padded_endpoint_slots(
            _candidate_endpoint_slots(rows, predecessors),
            slot_count,
        )
        row["successor_endpoint_slots"] = _padded_endpoint_slots(
            _candidate_endpoint_slots(rows, successors),
            slot_count,
        )
        row["slot_policy"] = "report_only_padded_component_indices"
        row["vendor_row_slot_policy"] = "candidate_dense_component_index_identity"
        row["endpoint_slot_policy"] = "candidate_position_block_valid_tuple"
        row["slot_values_are_component_indices"] = True
        row["slot_values_are_vendor_row_indices"] = False
        row["vendor_row_slots_are_binary_encoded"] = False
        row["endpoint_slots_are_binary_encoded"] = False


def _assign_report_only_exeblock_struct_views(rows: list[dict[str, object]]) -> None:
    for row in rows:
        row["exeBlock_conf_info_candidate"] = {
            "candidate_struct_policy": "report_only_field_shape_no_byte_layout",
            "binary_encoded": False,
            "valid": True,
            "block_idx": row.get("pe_local_exeblock_index"),
            "pe_dst": _position_for_physical_pe(row.get("physical_pe_id")),
            "priority": 0,
            "exeBlock_conf": {
                "req_activations": _valid_endpoint_count(
                    row.get("predecessor_endpoint_slots")
                ),
                "has_stages": _candidate_has_stages(row),
                "stages_start_pc": row.get("stage_start_pc_candidates"),
                "stage_start_pc_policy": "candidate_dense_per_physical_pe_instruction_order",
                "predecessors": row.get("predecessor_endpoint_slots", []),
                "successors": row.get("successor_endpoint_slots", []),
                "block_idx": row.get("pe_local_exeblock_index"),
                "subtask_idx": _candidate_subtask_index(row.get("subtask_slot")),
                "task_idx": row.get("task_id"),
                "instances_amount": 1,
                "instances_amount_policy": "expanded_loop_instance_report_only",
                "child_amount": _valid_endpoint_count(row.get("successor_endpoint_slots")),
                "block_class": 0,
                "block_class_policy": "reserved_zero_from_vendor_memset_evidence",
                "inst_mem_based_addr": _candidate_inst_mem_based_addr(
                    row.get("stage_start_pc_candidates")
                ),
                "inst_mem_based_addr_policy": "candidate_pe_local_start_pc_byte_offset",
                "stage_inst_amounts": _candidate_stage_amounts(row),
                "is_leaf": _valid_endpoint_count(row.get("successor_endpoint_slots")) == 0,
            },
        }


def _assign_report_only_micc_struct_views(
    task_rows: list[dict[str, object]],
    subtask_rows: list[dict[str, object]],
    instance_rows: list[dict[str, object]],
    exeblock_rows: list[dict[str, object]],
    *,
    loop_fold_report: StreamLoopFoldReport | None = None,
) -> None:
    for row in instance_rows:
        _assign_report_only_instance_struct_view(row)

    subtasks_by_task: dict[int, list[dict[str, object]]] = {}
    for row in subtask_rows:
        task_id = row.get("task_id")
        if isinstance(task_id, int):
            subtasks_by_task.setdefault(task_id, []).append(row)

    exeblocks_by_subtask: dict[tuple[int, str], list[dict[str, object]]] = {}
    for row in exeblock_rows:
        task_id = row.get("task_id")
        subtask_slot = str(row.get("subtask_slot"))
        if isinstance(task_id, int):
            exeblocks_by_subtask.setdefault((task_id, subtask_slot), []).append(row)

    loop_instances_by_subtask: dict[tuple[int, str], set[str]] = {}
    for row in instance_rows:
        task_id = row.get("task_id")
        subtask_slot = str(row.get("subtask_slot"))
        loop_instance = row.get("loop_instance")
        if isinstance(task_id, int) and loop_instance is not None:
            loop_instances_by_subtask.setdefault((task_id, subtask_slot), set()).add(
                str(loop_instance)
            )
    fold_candidates_by_task = _fold_candidates_by_task(loop_fold_report)

    for task_id, rows in subtasks_by_task.items():
        sorted_rows = sorted(rows, key=lambda row: _candidate_subtask_index(row.get("subtask_slot")) or -1)
        active_indices = [
            _candidate_subtask_index(row.get("subtask_slot"))
            for row in sorted_rows
        ]
        active_indices = [index for index in active_indices if index is not None]
        successor_map = _candidate_subtask_successor_map(active_indices)
        for row in sorted_rows:
            subtask_slot = str(row.get("subtask_slot"))
            subtask_idx = _candidate_subtask_index(subtask_slot)
            successors = successor_map.get(subtask_idx, []) if subtask_idx is not None else []
            local_exeblocks = exeblocks_by_subtask.get((task_id, subtask_slot), [])
            loop_count = len(loop_instances_by_subtask.get((task_id, subtask_slot), set()))
            root_blocks = _subtask_local_root_block_count(local_exeblocks)
            row["subtask_idx"] = subtask_idx
            row["successor_subtask_indices"] = successors
            row["successor_subtask_slots"] = _padded_edge_slots(
                list(successors),
                int(DFU3500_VENDOR_LIMITS["max_task_follow_per_task"]),
            )
            row["root_block_amount"] = root_blocks
            row["block_amount"] = len(local_exeblocks)
            row["loop_instance_count"] = loop_count
            row["sub_task_conf_info_candidate"] = {
                "candidate_struct_policy": "report_only_field_shape_no_byte_layout",
                "binary_encoded": False,
                "is_exe_start": subtask_idx == active_indices[0] if active_indices else False,
                "is_exe_end": subtask_idx == active_indices[-1] if active_indices else False,
                "instances_amount": 1,
                "instances_amount_policy": "expanded_loop_instances_as_exeblocks_report_only",
                "observed_loop_instance_count": loop_count,
                "instances_conf_mem_based_addr": None,
                "instances_conf_mem_based_addr_policy": (
                    "unresolved_pending_instance_table_layout"
                ),
                "suc_subtasks": row["successor_subtask_slots"],
                "suc_subtasks_padding_policy": (
                    "zero_fill_ignored_by_subtask_successor_chain_policy"
                ),
                "root_block_amount": root_blocks,
                "block_amount": len(local_exeblocks),
                "subtask_idx": subtask_idx,
                "task_idx": task_id,
                "embedded_exeblock_component_indices": [
                    block["component_index"] for block in local_exeblocks
                ],
            }
            if subtask_slot == "subtask1_k_stream":
                fold_candidates = fold_candidates_by_task.get(task_id, ())
                if fold_candidates:
                    row["folded_subtask_conf_candidate"] = (
                        _folded_subtask_conf_candidate(
                            task_id=task_id,
                            subtask_idx=subtask_idx,
                            loop_count=loop_count,
                            root_blocks=root_blocks,
                            local_exeblocks=local_exeblocks,
                            fold_candidates=fold_candidates,
                        )
                    )

    for row in task_rows:
        task_id = row.get("task_id")
        if not isinstance(task_id, int):
            continue
        active_indices = [
            _candidate_subtask_index(subtask.get("subtask_slot"))
            for subtask in sorted(
                subtasks_by_task.get(task_id, []),
                key=lambda subtask: _candidate_subtask_index(subtask.get("subtask_slot")) or -1,
            )
        ]
        active_indices = [index for index in active_indices if index is not None]
        row["task_conf_info_candidate"] = {
            "candidate_struct_policy": "report_only_field_shape_no_byte_layout",
            "binary_encoded": False,
            "is_exe_start": True,
            "is_exe_end": True,
            "subtasks_amount": len(active_indices),
            "execute_times": 1,
            "execute_times_policy": "single_runtime_task_execution_report_only",
            "subtasks_idx": _padded_edge_slots(
                list(active_indices),
                int(DFU3500_VENDOR_LIMITS["max_subtasks_per_task"]),
            ),
            "subtasks_idx_padding_policy": (
                "zero_fill_ignored_by_subtasks_amount"
            ),
            "suc_tasks": _padded_edge_slots(
                [],
                int(DFU3500_VENDOR_LIMITS["max_task_follow_per_task"]),
            ),
            "suc_tasks_padding_policy": (
                "zero_fill_independent_start_end_task_policy"
            ),
            "task_idx": task_id,
        }


def _assign_report_only_instance_struct_view(row: dict[str, object]) -> None:
    slot_count = int(DFU3500_VENDOR_LIMITS["base_addr_slots_per_instance"])
    subtask_slot = str(row.get("subtask_slot"))
    loop_instance = row.get("loop_instance")
    instance_idx = _loop_instance_index(loop_instance)
    base_addr = (
        _gemm_k_stream_base_addr_slots(instance_idx)
        if subtask_slot == "subtask1_k_stream" and instance_idx >= 0
        else _unresolved_base_addr_slots(slot_count)
    )
    row["subtask_idx"] = _candidate_subtask_index(subtask_slot)
    row["instance_idx"] = instance_idx if instance_idx >= 0 else None
    row["instance_conf_info_candidate"] = {
        "candidate_struct_policy": (
            "report_only_base_addr_slot_shape_with_profile_backed_gemm_k_slots"
        ),
        "binary_encoded": False,
        "task_idx": row.get("task_id"),
        "subtask_idx": row.get("subtask_idx"),
        "instance_idx": row.get("instance_idx"),
        "loop_instance": loop_instance,
        "base_addr": base_addr,
        "base_addr_slot_count": slot_count,
        "base_addr_policy": (
            "gemm_k_stream_profile_backed_a_b_slots_output_slots_disabled"
            if subtask_slot == "subtask1_k_stream" and instance_idx >= 0
            else "unresolved_pending_fiber_fragment_to_instance_base_mapping"
        ),
        "base_addr_unit": "uint32_words",
        "base_addr_unit_policy": "dfu3500_legacy_base_addr_unit",
        "word_bytes": int(DFU3500_MEMORY_LAYOUT["word_bytes"]),
        "disabled_slot_sentinel": UNUSED_BASE_ADDR_WORD,
        "disabled_slot_sentinel_hex": f"0x{UNUSED_BASE_ADDR_WORD:08x}",
        "data_memory_policy": (
            "data_base_slots_are_distinct_from_instruction_pc_layout"
        ),
        "source_evidence_refs": [
            "docs/vendor_reference/original_materials_audit.md",
            "docs/architecture/gemm-case-study/gemm-tile-dag-from-legacy.md",
            "compiler/gpdpu_compiler/core/dfu3500/__init__.py",
        ],
    }


def _unresolved_base_addr_slots(slot_count: int) -> list[dict[str, object]]:
    return [
        {
            "slot": slot,
            "role": None,
            "base_addr_word": None,
            "base_addr_byte": None,
            "status": "unresolved",
            "resolution_policy": (
                "unresolved_pending_fiber_fragment_to_instance_base_mapping"
            ),
            "binary_encoded": False,
        }
        for slot in range(slot_count)
    ]


def _gemm_k_stream_base_addr_slots(instance_idx: int) -> list[dict[str, object]]:
    a_region = DFU3500_GEMM_REGIONS["A"]
    b_region = DFU3500_GEMM_REGIONS["B"]
    word_bytes = int(DFU3500_MEMORY_LAYOUT["word_bytes"])
    k_tile = int(DFU3500_DEFAULT_TILE["matmul_k"])
    a_increment_words = _byte_count_to_words(
        k_tile * _dtype_nbytes(a_region.dtype),
        word_bytes=word_bytes,
    )
    b_shape = b_region.shape
    if b_shape is None or len(b_shape) != 2:
        raise ValueError("expected rank-2 B GEMM region shape")
    b_increment_words = _byte_count_to_words(
        k_tile * int(b_shape[1]) * _dtype_nbytes(b_region.dtype),
        word_bytes=word_bytes,
    )
    a_word = _legacy_base_word(a_region) + instance_idx * a_increment_words
    b_word = _legacy_base_word(b_region) + instance_idx * b_increment_words
    return [
        _resolved_base_addr_slot(
            slot=0,
            role="A",
            region_name=a_region.name,
            instance_idx=instance_idx,
            base_addr_word=a_word,
            increment_words=a_increment_words,
            logical_address_expr=(
                f"A[:, {instance_idx}*{k_tile}:"
                f"{instance_idx + 1}*{k_tile}]"
            ),
        ),
        _resolved_base_addr_slot(
            slot=1,
            role="B",
            region_name=b_region.name,
            instance_idx=instance_idx,
            base_addr_word=b_word,
            increment_words=b_increment_words,
            logical_address_expr=(
                f"B[{instance_idx}*{k_tile}:"
                f"{instance_idx + 1}*{k_tile}, :]"
            ),
        ),
        _disabled_base_addr_slot(2),
        _disabled_base_addr_slot(3),
    ]


def _resolved_base_addr_slot(
    *,
    slot: int,
    role: str,
    region_name: str,
    instance_idx: int,
    base_addr_word: int,
    increment_words: int,
    logical_address_expr: str,
) -> dict[str, object]:
    word_bytes = int(DFU3500_MEMORY_LAYOUT["word_bytes"])
    return {
        "slot": slot,
        "role": role,
        "region_name": region_name,
        "base_addr_word": base_addr_word,
        "base_addr_word_hex": f"0x{base_addr_word:08x}",
        "base_addr_byte": base_addr_word * word_bytes,
        "base_addr_byte_hex": f"0x{base_addr_word * word_bytes:08x}",
        "status": "resolved",
        "resolution_policy": "dfu3500_gemm_k_stream_legacy_region_base_plus_k_offset",
        "increment_words_per_instance": increment_words,
        "instance_idx": instance_idx,
        "base_addr_idx": slot,
        "expected_iter_exe_cond": slot,
        "logical_address_expr": logical_address_expr,
        "effective_address_expr": (
            f"4 * (base_addr[{slot}] + instruction_imm_word_offset)"
        ),
        "binary_encoded": False,
    }


def _disabled_base_addr_slot(slot: int) -> dict[str, object]:
    return {
        "slot": slot,
        "role": "unused",
        "base_addr_word": UNUSED_BASE_ADDR_WORD,
        "base_addr_word_hex": f"0x{UNUSED_BASE_ADDR_WORD:08x}",
        "base_addr_byte": None,
        "status": "disabled_sentinel",
        "resolution_policy": "slot_not_consumed_by_gemm_k_stream_body",
        "base_addr_idx": slot,
        "binary_encoded": False,
    }


def _legacy_base_word(region: object) -> int:
    value = getattr(region, "legacy_base_word32", None)
    if not isinstance(value, int):
        raise ValueError(f"missing legacy base word for region {region!r}")
    return value


def _dtype_nbytes(dtype: object) -> int:
    if dtype in {"fp16", "float16", "half"}:
        return 2
    if dtype in {"fp32", "float32"}:
        return 4
    raise ValueError(f"unsupported dtype for base address derivation: {dtype}")


def _byte_count_to_words(byte_count: int, *, word_bytes: int) -> int:
    if byte_count % word_bytes != 0:
        raise ValueError(
            f"byte count {byte_count} is not divisible by word size {word_bytes}"
        )
    return byte_count // word_bytes


def _folded_subtask_conf_candidate(
    *,
    task_id: int,
    subtask_idx: int | None,
    loop_count: int,
    root_blocks: int,
    local_exeblocks: list[dict[str, object]],
    fold_candidates: tuple[StreamLoopFoldCandidate, ...],
) -> dict[str, object]:
    loop_instance_keys = sorted(
        {
            loop_key
            for candidate in fold_candidates
            for loop_key in candidate.loop_instance_keys
        },
        key=_loop_instance_sort_key,
    )
    derived_instance_keys = sorted(
        {
            derived_key
            for candidate in fold_candidates
            for derived_key in candidate.derived_instance_keys
        },
        key=_derived_instance_sort_key,
    )
    source_to_derived_instance_keys = sorted(
        {
            mapping
            for candidate in fold_candidates
            for mapping in candidate.source_to_derived_instance_keys
        },
        key=lambda mapping: (_loop_instance_sort_key(mapping[0]), mapping[1]),
    )
    derived_region_axes = sorted(
        {candidate.derived_region_axis for candidate in fold_candidates}
    )
    shape_counts: dict[str, int] = {}
    signature_counts: dict[str, int] = {}
    for candidate in fold_candidates:
        shape_key = "|".join(
            f"{role}:{semantic}:{mechanism}"
            for role, semantic, mechanism in candidate.loop_body_shape
        )
        shape_counts[shape_key] = shape_counts.get(shape_key, 0) + 1
        signature_key = _fold_body_signature_key(candidate)
        signature_counts[signature_key] = signature_counts.get(signature_key, 0) + 1
    instances_amount = len(loop_instance_keys) if loop_instance_keys else loop_count
    return {
        "candidate_struct_policy": "report_only_folded_stream_subtask_loop_overlay",
        "overlay_only": True,
        "binary_encoded": False,
        "task_idx": task_id,
        "subtask_idx": subtask_idx,
        "instances_amount": instances_amount,
        "instances_amount_policy": "stream_loop_fold_report_candidate",
        "observed_loop_instance_count": loop_count,
        "loop_instance_keys": loop_instance_keys,
        "loop_axis": fold_candidates[0].loop_axis,
        "derived_region_axis": (
            derived_region_axes[0] if len(derived_region_axes) == 1 else "mixed"
        ),
        "derived_instance_keys": derived_instance_keys,
        "source_to_derived_instance_keys": [
            {"source": source, "derived": derived}
            for source, derived in source_to_derived_instance_keys
        ],
        "fold_proof_instance_key_policy": (
            "derived_instance_keys_are_fold_proof_authority;"
            "loop_instance_keys_are_projection_compatibility_labels"
        ),
        "fold_scope": "stream_subtask_loop",
        "stream_candidate_count": len(fold_candidates),
        "stream_ids": [candidate.stream_id for candidate in fold_candidates],
        "stream_fold_body_signature_counts": dict(sorted(signature_counts.items())),
        "stream_fold_body_signature_policy": (
            "normalized_semantics_and_dependency_topology;"
            "role_strings_are_diagnostics_only"
        ),
        "stream_body_shape_counts": dict(sorted(shape_counts.items())),
        "stream_body_shape_policy": "per_stream_body_shapes_not_global_single_body",
        "source_fold_candidate_ids": [
            candidate.id for candidate in fold_candidates
        ],
        "target_fold_projection_proof": _target_fold_projection_proof(
            fold_candidates=fold_candidates,
            loop_instance_keys=loop_instance_keys,
            derived_instance_keys=derived_instance_keys,
            source_to_derived_instance_keys=source_to_derived_instance_keys,
        ),
        "instances_conf_mem_based_addr": None,
        "instances_conf_mem_based_addr_policy": (
            "unresolved_pending_instance_table_layout"
        ),
        "instance_base_mapping_status": "resolved_for_gemm_k_stream_a_b_slots",
        "instance_base_mapping_policy": (
            "slot0_A_slot1_B_resolved_from_dfu3500_regions;"
            "slot2_slot3_disabled_sentinel_for_k_stream"
        ),
        "root_block_amount": root_blocks,
        "block_amount": len(local_exeblocks),
        "expanded_exeblock_component_indices": [
            block["component_index"] for block in local_exeblocks
        ],
        "expanded_rows_remain_authoritative": True,
        "folded_overlay_does_not_delete_expanded_exeblocks": True,
    }


def _target_fold_projection_proof(
    *,
    fold_candidates: tuple[StreamLoopFoldCandidate, ...],
    loop_instance_keys: list[str],
    derived_instance_keys: list[str],
    source_to_derived_instance_keys: list[tuple[str, str]],
) -> dict[str, object]:
    return {
        "schema_version": "target_fold_projection_proof.v1",
        "target": "dfu3500_vendor_component_overlay",
        "projection_status": "report_only_eligible",
        "binary_encoded": False,
        "source_loop_uniformity_proof_ids": [
            candidate.id for candidate in fold_candidates
        ],
        "projection_fields": [
            "instances_amount",
            "derived_instance_keys",
            "source_to_derived_instance_keys",
            "loop_instance_keys",
        ],
        "derived_instance_keys": list(derived_instance_keys),
        "source_to_derived_instance_keys": [
            {"source": source, "derived": derived}
            for source, derived in source_to_derived_instance_keys
        ],
        "projection_compatibility_labels": list(loop_instance_keys),
        "target_requirements": [
            "expanded_rows_remain_authoritative",
            "overlay_only",
            "instance_base_mapping_resolved_for_gemm_k_stream_a_b_slots",
        ],
        "policy": (
            "target_projection_eligibility_consumes_loop_uniformity_proof;"
            "does_not_define_foldability_or_emit_binary_bytes"
        ),
    }


def _fold_body_signature_key(candidate: StreamLoopFoldCandidate) -> str:
    signature = candidate.fold_body_signature
    step_text = ",".join(
        f"{semantic}:{mechanism}"
        for semantic, mechanism in signature.step_semantics
    )
    edge_text = ",".join(
        f"{edge.source_step_index}>{edge.target_step_index}:{edge.dependency_kind}"
        for edge in signature.dependency_topology
    )
    return (
        f"steps[{step_text}]|deps[{edge_text}]|order[{signature.order_model}]"
    )


def _fold_candidates_by_task(
    report: StreamLoopFoldReport | None,
) -> dict[int, tuple[StreamLoopFoldCandidate, ...]]:
    if report is None:
        return {}
    grouped: dict[int, list[StreamLoopFoldCandidate]] = {}
    for candidate in report.candidates:
        if not candidate.foldable:
            continue
        task_id = _task_id_from_stream_id(candidate.stream_id)
        if task_id is None:
            continue
        grouped.setdefault(task_id, []).append(candidate)
    return {
        task_id: tuple(sorted(candidates, key=lambda candidate: candidate.stream_id))
        for task_id, candidates in grouped.items()
    }


def _task_id_from_stream_id(stream_id: object) -> int | None:
    text = str(stream_id)
    if not text.startswith("t") or "_pe" not in text:
        return None
    task_text = text[1:text.index("_pe")]
    if not task_text.isdigit():
        return None
    return int(task_text)


def _candidate_subtask_successor_map(indices: list[int]) -> dict[int, list[int]]:
    return {
        current: [next_index]
        for current, next_index in zip(indices, indices[1:])
    }


def _subtask_local_root_block_count(rows: list[dict[str, object]]) -> int:
    component_indices = {
        row.get("component_index")
        for row in rows
        if isinstance(row.get("component_index"), int)
    }
    roots = 0
    for row in rows:
        predecessors = row.get("predecessor_component_indices", [])
        if not isinstance(predecessors, list):
            predecessors = []
        if not any(predecessor in component_indices for predecessor in predecessors):
            roots += 1
    return roots


def _candidate_vendor_row_indices(
    rows: list[dict[str, object]],
    component_indices: list[object],
) -> list[object]:
    values: list[object] = []
    for component_index in component_indices:
        if not isinstance(component_index, int):
            values.append(None)
            continue
        if component_index < 0 or component_index >= len(rows):
            values.append(None)
            continue
        values.append(rows[component_index].get("candidate_vendor_row_index"))
    return values


def _record_bucket_stage(bucket: dict[str, object], row: dict[str, object]) -> None:
    stage = _stage_for_opcode(row.get("opcode"))
    if stage is None:
        return
    counts = bucket["stage_instruction_counts"]
    if isinstance(counts, dict):
        counts[stage] = int(counts.get(stage, 0)) + 1
    opcodes = bucket["stage_opcodes"]
    if isinstance(opcodes, dict):
        opcodes.setdefault(stage, []).append(row.get("opcode"))


def _stage_for_opcode(opcode: object) -> str | None:
    opcode_text = str(opcode)
    if opcode_text in {"LOAD_OR_COPY"}:
        return "LD"
    if opcode_text in {"ACC_PREPARE", "HMMAL_OR_GEMM_UPDATE"}:
        return "CAL"
    if opcode_text in {"ROUTE_RECV_VISIBILITY"}:
        return "FLOW"
    if opcode_text in {"STD"}:
        return "ST"
    return None


def _candidate_has_stages(row: dict[str, object]) -> dict[str, bool]:
    counts = row.get("stage_instruction_counts", {})
    if not isinstance(counts, dict):
        counts = {}
    return {
        stage: int(counts.get(stage, 0)) > 0
        for stage in ("LD", "CAL", "FLOW", "ST", "MAX_COMPONENT")
    }


def _candidate_stage_amounts(row: dict[str, object]) -> dict[str, int]:
    counts = row.get("stage_instruction_counts", {})
    if not isinstance(counts, dict):
        counts = {}
    return {
        stage: int(counts.get(stage, 0))
        for stage in ("LD", "CAL", "FLOW", "ST")
    }


def _unresolved_stage_pc_map() -> dict[str, None]:
    return {
        "LD": None,
        "CAL": None,
        "FLOW": None,
        "ST": None,
        "MAX_COMPONENT": None,
    }


def _candidate_inst_mem_based_addr(stage_start_pcs: object) -> int | None:
    if not isinstance(stage_start_pcs, dict):
        return None
    values = [value for value in stage_start_pcs.values() if isinstance(value, int)]
    if not values:
        return None
    return min(values) * int(DFU3500_STRUCT_SIZES["inst_t"])


def _valid_endpoint_count(value: object) -> int:
    if not isinstance(value, list):
        return 0
    return sum(
        1
        for item in value
        if isinstance(item, dict) and item.get("valid") is True
    )


def _candidate_subtask_index(value: object) -> int | None:
    text = str(value)
    if text.startswith("subtask"):
        digits = []
        for char in text[len("subtask"):]:
            if char.isdigit():
                digits.append(char)
            else:
                break
        if digits:
            return int("".join(digits))
    return None


def _candidate_endpoint_slots(
    rows: list[dict[str, object]],
    component_indices: list[object],
) -> list[dict[str, object]]:
    values: list[dict[str, object]] = []
    for component_index in component_indices:
        if not isinstance(component_index, int):
            values.append(_invalid_endpoint_slot())
            continue
        if component_index < 0 or component_index >= len(rows):
            values.append(_invalid_endpoint_slot())
            continue
        target = rows[component_index]
        values.append(
            {
                "pe_pos": _position_for_physical_pe(target.get("physical_pe_id")),
                "block_idx": target.get("pe_local_exeblock_index"),
                "valid": True,
            }
        )
    return values


def _padded_edge_slots(values: list[object], slot_count: int) -> list[object]:
    payload = list(values[:slot_count])
    payload.extend([0] * (slot_count - len(payload)))
    return payload


def _padded_endpoint_slots(
    values: list[dict[str, object]],
    slot_count: int,
) -> list[dict[str, object]]:
    payload = list(values[:slot_count])
    payload.extend(_invalid_endpoint_slot() for _ in range(slot_count - len(payload)))
    return payload


def _invalid_endpoint_slot() -> dict[str, object]:
    return {
        "pe_pos": {"x": 0, "y": 0, "z": 0},
        "block_idx": 0,
        "valid": False,
        "invalid_slot_policy": "zero_fill_gated_by_valid_false",
    }


def _find_exeblock(
    rows: list[dict[str, object]],
    subtask_slot: str,
    loop_instance: object,
) -> dict[str, object] | None:
    for row in rows:
        if row.get("subtask_slot") == subtask_slot and row.get("loop_instance") == loop_instance:
            return row
    return None


def _add_exeblock_dependency(
    source: dict[str, object],
    target: dict[str, object],
    *,
    proof_kind: str,
    reason: str,
) -> None:
    source_index = int(source["component_index"])
    target_index = int(target["component_index"])
    source["successor_component_indices"].append(target_index)
    target["predecessor_component_indices"].append(source_index)
    proof = {
        "source_component_index": source_index,
        "target_component_index": target_index,
        "proof_kind": proof_kind,
        "status": "structurally_projected",
        "reason": reason,
        "binary_encoded": False,
    }
    source["dependency_proofs"].append(proof)
    target["dependency_proofs"].append(proof)
    source["successor_overflow_count"] = max(
        0,
        len(source["successor_component_indices"])
        - int(DFU3500_VENDOR_LIMITS["max_task_follow_per_task"]),
    )
    target["predecessor_overflow_count"] = max(
        0,
        len(target["predecessor_component_indices"])
        - int(DFU3500_VENDOR_LIMITS["max_task_follow_per_task"]),
    )


def _loop_instance_index(value: object) -> int:
    text = str(value)
    if text.startswith("k") and text[1:].isdigit():
        return int(text[1:])
    return -1


def _loop_instance_sort_key(value: object) -> tuple[int, str]:
    text = str(value)
    if text.startswith("k") and text[1:].isdigit():
        return (int(text[1:]), text)
    return (-1, text)


def _derived_instance_sort_key(value: object) -> tuple[int, str]:
    text = str(value)
    prefix = "region"
    if text.startswith(prefix) and text[len(prefix):].isdigit():
        return (int(text[len(prefix):]), text)
    return (-1, text)


def _ensure_task(
    accumulator: dict[int, dict[str, object]],
    task_id: int | None,
) -> dict[str, object]:
    key = task_id if task_id is not None else -1
    if key not in accumulator:
        accumulator[key] = {
            "component": "task_rows",
            "task_id": task_id,
            "inst_count": 0,
            "exeblock_count": 0,
            "zero_boundary_count": 0,
        }
    return accumulator[key]


def _ensure_subtask(
    accumulator: dict[tuple[int | None, str], dict[str, object]],
    task_id: int | None,
    subtask_slot: str,
) -> dict[str, object]:
    key = (task_id, subtask_slot)
    if key not in accumulator:
        accumulator[key] = {
            "component": "subtask_rows",
            "task_id": task_id,
            "subtask_slot": subtask_slot,
            "inst_count": 0,
            "exeblock_count": 0,
            "zero_boundary_count": 0,
        }
    return accumulator[key]


def _ensure_instance(
    accumulator: dict[tuple[int | None, str, str], dict[str, object]],
    task_id: int | None,
    subtask_slot: str,
    loop_instance: str,
) -> dict[str, object]:
    key = (task_id, subtask_slot, loop_instance)
    if key not in accumulator:
        accumulator[key] = {
            "component": "instance_rows",
            "task_id": task_id,
            "subtask_slot": subtask_slot,
            "loop_instance": loop_instance,
            "inst_count": 0,
        }
    return accumulator[key]


def _increment(row: dict[str, object], key: str) -> None:
    row[key] = int(row[key]) + 1


def _subtask_key_sort(key: tuple[int | None, str]) -> tuple[int, str]:
    task_id, subtask_slot = key
    return (-1 if task_id is None else task_id, subtask_slot)


def _instance_key_sort(key: tuple[int | None, str, str]) -> tuple[int, str, str]:
    task_id, subtask_slot, loop_instance = key
    return (-1 if task_id is None else task_id, subtask_slot, loop_instance)


def _exeblock_key_sort(key: tuple[int | None, str, str, str | None]) -> tuple[int, str, str, str]:
    task_id, stream_id, subtask_slot, loop_instance = key
    return (
        -1 if task_id is None else task_id,
        stream_id,
        subtask_slot,
        "" if loop_instance is None else loop_instance,
    )


def _physical_pe_id(stream_id: object) -> str:
    text = str(stream_id)
    if "_" in text:
        return text.rsplit("_", 1)[-1]
    return text


def _position_for_physical_pe(physical_pe_id: object) -> dict[str, int] | None:
    text = str(physical_pe_id)
    if not text.startswith("pe") or not text[2:].isdigit():
        return None
    pe_index = int(text[2:])
    mesh_x = int(DFU3500_PHYSICAL_TOPOLOGY["shape"][0])
    return {
        "x": pe_index % mesh_x,
        "y": pe_index // mesh_x,
        "z": 0,
    }


def _forbidden_field_count(row: dict[str, object]) -> int:
    return sum(
        1
        for key in row
        if key.startswith("source_tile_micro_block") or key == "tile_micro_block_kind"
    )


__all__ = [
    "VendorComponentPlan",
    "build_vendor_component_plan",
    "summarize_vendor_component_plan",
]
