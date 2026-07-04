"""Runtime package planning for app-level compiler programs.

This layer consumes ``AppPlan`` and records how semantic OpenFabric apps would
be grouped into DFU runtime packages.  It does not lower tasks, subtasks,
instructions, or binary rows; those remain downstream responsibilities.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from gpdpu_compiler.core.dfu3500 import VendorRuntimeProfile
from gpdpu_compiler.core.program_app import AppPlan


RuntimePackageStatus = Literal[
    "runnable_single_package",
    "requires_runtime_launch_plan",
    "unsupported_vendor_profile",
]


@dataclass(frozen=True)
class Pe00MaterializedScalarRuntimeOrderContract:
    """Report-only runtime ordering contract for PE00 scalar materialization.

    This is intentionally not a vendor subtask writer.  It names the ordering
    obligation that later MICC/runtime lowering must preserve: local maxima are
    combined and stored before any consumer reads the replicated scalar.
    """

    source_id: str
    producer_processor: str
    consumer_processors: tuple[str, ...]
    status: str = "available"

    def to_plan(self) -> dict[str, Any]:
        ordered_subtask_slots = [
            "subtask_log10max_local_reduce",
            "subtask_log10max_global_max_pe00_combine",
            "subtask_log10max_global_max_pe00_store",
            "subtask_log10max_global_max_consumer_readback",
            "subtask_log10max_max_with_floor",
        ]
        successor_edges = [
            [
                "subtask_log10max_local_reduce",
                "subtask_log10max_global_max_pe00_combine",
            ],
            [
                "subtask_log10max_global_max_pe00_combine",
                "subtask_log10max_global_max_pe00_store",
            ],
            [
                "subtask_log10max_global_max_pe00_store",
                "subtask_log10max_global_max_consumer_readback",
            ],
            [
                "subtask_log10max_global_max_consumer_readback",
                "subtask_log10max_max_with_floor",
            ],
        ]
        stage_row_id_contract = {
            "subtask_log10max_local_reduce": {
                "source_fiber_op": "local_reduce_max_tile",
                "expected_row_id_prefix": "local_reduce_max_tile",
                "row_id_status": "external_to_pe00_contract",
            },
            "subtask_log10max_global_max_pe00_combine": {
                "source_fiber_op": "global_max_tile",
                "expected_row_ids": [
                    f"global_max_tile.pe00_fmax_combine.{index:02d}"
                    for index in range(max(len(self.consumer_processors) - 1, 1))
                ],
                "row_id_status": "contract_available_rows_missing",
            },
            "subtask_log10max_global_max_pe00_store": {
                "source_fiber_op": "global_max_tile",
                "expected_row_ids": ["global_max_tile.pe00_scalar_store.00"],
                "row_id_status": "contract_available_rows_missing",
            },
            "subtask_log10max_global_max_consumer_readback": {
                "source_fiber_op": "global_max_tile",
                "expected_row_ids": [
                    f"global_max_tile.consumer_readback.{index:02d}"
                    for index, _processor in enumerate(self.consumer_processors)
                ],
                "row_id_status": "contract_available_rows_missing",
            },
            "subtask_log10max_max_with_floor": {
                "source_fiber_op": "max_with_floor_tile",
                "expected_row_id_prefix": "max_with_floor_tile",
                "row_id_status": "external_to_pe00_contract",
            },
        }
        decoded_order_contract = {
            "schema_version": 1,
            "artifact_kind": "pe00_materialized_scalar_decoded_micc_order_contract",
            "source_id": self.source_id,
            "status": "contract_available_decoded_rows_missing",
            "expected_decoded_order": ordered_subtask_slots,
            "expected_successor_edges": successor_edges,
            "stage_row_id_contract": stage_row_id_contract,
            "must_decode_components": [
                "task_conf_info_t",
                "sub_task_conf_info_t",
                "exeBlock_conf_info_t",
            ],
            "roundtrip_artifact": "decoded_micc_order.json",
            "runtime_runnable_claim": False,
            "row_bytes_claim": False,
            "physical_route_allreduce": False,
        }
        runtime_trace_contract = {
            "schema_version": 1,
            "artifact_kind": "pe00_materialized_scalar_runtime_trace_contract",
            "source_id": self.source_id,
            "status": "contract_available_trace_missing",
            "required_runtime_trace_events": [
                "local_reduce_complete",
                "pe00_fmax_combine_complete",
                "pe00_scalar_store_complete",
                "consumer_readback_complete",
                "max_with_floor_start",
            ],
            "required_precedence_pairs": [
                ["local_reduce_complete", "pe00_fmax_combine_complete"],
                ["pe00_fmax_combine_complete", "pe00_scalar_store_complete"],
                ["pe00_scalar_store_complete", "consumer_readback_complete"],
                ["consumer_readback_complete", "max_with_floor_start"],
            ],
            "roundtrip_artifact": "runtime_start_wait_trace.json",
            "runtime_runnable_claim": False,
            "row_bytes_claim": False,
            "physical_route_allreduce": False,
        }
        runtime_order_proof_plan = {
            "schema_version": 1,
            "artifact_kind": "pe00_materialized_scalar_runtime_order_proof_plan",
            "source_id": self.source_id,
            "status": "blocked_structured_runtime_proof_missing",
            "closed_fields": [
                "producer_processor",
                "consumer_processors",
                "ordered_stages",
                "ordered_subtask_slots",
                "successor_edges",
            ],
            "missing_fields": [
                "task_conf_info_active_subtask_indices",
                "sub_task_conf_successor_row_bytes",
                "exeBlock_conf_wait_or_dependency_flags",
                "decoded_micc_roundtrip_order",
                "runtime_start_wait_trace",
            ],
            "expected_decoded_order": ordered_subtask_slots,
            "expected_successor_edges": successor_edges,
            "stage_row_id_contract": stage_row_id_contract,
            "decoded_order_contract": decoded_order_contract,
            "runtime_trace_contract": runtime_trace_contract,
            "micc_materialization_request": {
                "schema_version": 1,
                "artifact_kind": (
                    "pe00_materialized_scalar_micc_order_materialization_request"
                ),
                "source_id": self.source_id,
                "status": "materialization_request_available_rows_missing",
                "ordered_subtask_slots": ordered_subtask_slots,
                "successor_edges": successor_edges,
                "stage_row_id_contract": stage_row_id_contract,
                "expected_struct_rows": {
                    "task_conf_info_t": 1,
                    "sub_task_conf_info_t": len(ordered_subtask_slots),
                    "exeBlock_conf_info_t": len(ordered_subtask_slots),
                },
                "decoded_order_contract_artifact": (
                    decoded_order_contract["roundtrip_artifact"]
                ),
                "runtime_trace_contract_artifact": (
                    runtime_trace_contract["roundtrip_artifact"]
                ),
                "required_output_artifacts": [
                    "pe00_micc_task_conf_info_rows.bin",
                    "pe00_micc_sub_task_conf_info_rows.bin",
                    "pe00_micc_exeBlock_conf_info_rows.bin",
                    "decoded_micc_order.json",
                    "decoded_task_subtask_exeblock_rows.json",
                    "runtime_start_wait_trace.json",
                ],
                "blocked_on": [
                    "runtime_subtask_order_proof_missing",
                    "micc_successor_wait_row_bytes_missing",
                ],
                "runtime_runnable_claim": False,
                "row_bytes_claim": False,
                "physical_route_allreduce": False,
            },
            "micc_field_contract": {
                "task_conf_info_t": [
                    "active_subtask_count",
                    "active_subtask_indices",
                    "task_follow_or_wait_policy",
                ],
                "sub_task_conf_info_t": [
                    "subtask_slot_index",
                    "successor_subtask_index",
                    "instances_conf_mem_based_addr",
                    "instances_amount",
                ],
                "exeBlock_conf_info_t": [
                    "exe_block_index",
                    "dependency_or_wait_flags",
                    "instruction_range_for_subtask",
                ],
            },
            "required_runtime_trace_events": runtime_trace_contract[
                "required_runtime_trace_events"
            ],
            "required_proof_artifacts": [
                "decoded_micc_order.json",
                "decoded_task_subtask_exeblock_rows.json",
                "runtime_start_wait_trace.json",
            ],
            "proof_blockers": [
                {
                    "blocker_id": "runtime_subtask_order_proof_missing",
                    "status": "blocked_missing_decoded_micc_order_proof",
                    "needed_evidence": (
                        "decoded MICC rows and runtime trace preserve "
                        "PE00 combine/store before consumer readback"
                    ),
                },
                {
                    "blocker_id": "micc_successor_wait_row_bytes_missing",
                    "status": "blocked_missing_micc_row_bytes",
                    "needed_evidence": (
                        "task/subtask/exeBlock rows encode the successor and "
                        "wait order named by this contract"
                    ),
                },
            ],
            "runtime_runnable_claim": False,
            "row_bytes_claim": False,
            "physical_route_allreduce": False,
        }
        micc_order_lowering_intent = {
            "schema_version": 1,
            "artifact_kind": "pe00_materialized_scalar_micc_order_lowering_intent",
            "source_id": self.source_id,
            "status": "micc_order_intent_available_rows_missing",
            "enforcement_components": [
                "task_conf_info_t",
                "sub_task_conf_info_t",
                "exeBlock_conf_info_t",
            ],
            "ordered_subtask_slots": ordered_subtask_slots,
            "successor_edges": successor_edges,
            "stage_row_id_contract": stage_row_id_contract,
            "required_decoded_order_artifacts": [
                "decoded_micc_order.json",
                "decoded_task_subtask_exeblock_rows.json",
            ],
            "blocked_on": [
                "runtime_subtask_order_proof_missing",
                "micc_successor_wait_row_bytes_missing",
            ],
            "runtime_order_proof_plan": runtime_order_proof_plan,
            "runtime_runnable_claim": False,
            "row_bytes_claim": False,
            "physical_route_allreduce": False,
        }
        return {
            "schema_version": 1,
            "artifact_kind": "pe00_materialized_scalar_runtime_order_contract",
            "source_id": self.source_id,
            "producer_processor": self.producer_processor,
            "consumer_processors": list(self.consumer_processors),
            "consumer_count": len(self.consumer_processors),
            "status": self.status,
            "order_kind": "materialize_before_readback",
            "ordered_stages": [
                "local_reduce_max_tile",
                "global_max_tile.pe00_fmax_combine",
                "global_max_tile.pe00_scalar_store",
                "global_max_tile.consumer_scalar_readback",
                "max_with_floor_tile",
            ],
            "enforcement_point": "runtime_subtask_order",
            "must_preserve": [
                "PE00 FMAX combine completes before scalar store",
                "PE00 scalar store completes before per-PE readback",
                "per-PE readback completes before max_with_floor_tile consumes scalar",
            ],
            "runtime_order_proof_plan": runtime_order_proof_plan,
            "micc_order_lowering_intent": micc_order_lowering_intent,
            "runtime_runnable_claim": False,
            "row_bytes_claim": False,
            "physical_route_allreduce": False,
        }


@dataclass(frozen=True)
class RuntimePackage:
    """One planned vendor runtime package emission unit."""

    package_id: str
    package_index: int
    semantic_app_ids: tuple[int, ...]
    app_names: tuple[str, ...]
    binary_emission_status: RuntimePackageStatus
    mapping_kind: str = "greedy_semantic_app_group"
    storage_inputs: tuple[str, ...] = ()
    storage_outputs: tuple[str, ...] = ()
    refusal_reasons: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "package_id": self.package_id,
            "package_index": self.package_index,
            "semantic_app_ids": list(self.semantic_app_ids),
            "app_names": list(self.app_names),
            "mapping_kind": self.mapping_kind,
            "binary_emission_status": self.binary_emission_status,
            "storage_inputs": list(self.storage_inputs),
            "storage_outputs": list(self.storage_outputs),
            "refusal_reasons": list(self.refusal_reasons),
            "attrs": dict(self.attrs),
        }


@dataclass(frozen=True)
class RuntimePackageAssignment:
    """Greedy app-to-package assignment plus runtime legality report."""

    source_program: str
    runtime_profile: VendorRuntimeProfile
    packages: tuple[RuntimePackage, ...]
    assignment_policy: str = "greedy_app_order_capacity_first"
    attrs: dict[str, Any] = field(default_factory=dict)

    @property
    def package_count(self) -> int:
        return len(self.packages)

    @property
    def semantic_app_count(self) -> int:
        return sum(len(package.semantic_app_ids) for package in self.packages)

    def validate(self) -> dict[str, Any]:
        assigned_app_ids = [
            app_id for package in self.packages for app_id in package.semantic_app_ids
        ]
        all_apps_assigned_once = len(assigned_app_ids) == len(set(assigned_app_ids))
        packages_within_runtime_app_capacity = all(
            len(package.semantic_app_ids)
            <= self.runtime_profile.max_runtime_apps_per_package
            for package in self.packages
        )
        has_multi_package_program = self.package_count > 1
        requires_runtime_launch_plan = has_multi_package_program
        runtime_launch_supported = (
            not has_multi_package_program
            or self.runtime_profile.supports_multi_package_launch
        )
        single_package_multi_app_supported = all(
            len(package.semantic_app_ids) <= 1
            or self.runtime_profile.supports_single_package_multi_semantic_app
            for package in self.packages
        )
        complete_program_runnable = (
            packages_within_runtime_app_capacity
            and runtime_launch_supported
            and single_package_multi_app_supported
            and all_apps_assigned_once
            and all(
                package.binary_emission_status == "runnable_single_package"
                for package in self.packages
            )
        )

        blocking_reasons: list[str] = []
        if not all_apps_assigned_once:
            blocking_reasons.append("semantic apps are not assigned exactly once")
        if not packages_within_runtime_app_capacity:
            blocking_reasons.append("package exceeds runtime app capacity")
        if not runtime_launch_supported:
            blocking_reasons.append(
                "runtime profile does not support multi-package launch"
            )
        if not single_package_multi_app_supported:
            blocking_reasons.append(
                "runtime profile does not support multi-semantic-app packages"
            )

        return {
            "all_apps_assigned_once": all_apps_assigned_once,
            "packages_within_runtime_app_capacity": (
                packages_within_runtime_app_capacity
            ),
            "requires_runtime_launch_plan": requires_runtime_launch_plan,
            "runtime_launch_supported": runtime_launch_supported,
            "single_package_multi_app_supported": single_package_multi_app_supported,
            "complete_program_runnable": complete_program_runnable,
            "blocking_reasons": blocking_reasons,
            "ok": complete_program_runnable,
        }

    def to_plan(self) -> dict[str, Any]:
        validation = self.validate()
        return {
            "ir": "runtime_package_assignment",
            "source_ir": "app_plan",
            "source_program": self.source_program,
            "assignment_policy": self.assignment_policy,
            "runtime_profile": self.runtime_profile.to_plan(),
            "packages": {
                package.package_id: package.to_plan() for package in self.packages
            },
            "totals": {
                "semantic_app_count": self.semantic_app_count,
                "package_count": self.package_count,
            },
            "validation": validation,
            "attrs": dict(self.attrs),
        }


def assign_app_plan_to_runtime_packages(
    app_plan: AppPlan,
    runtime_profile: VendorRuntimeProfile,
) -> RuntimePackageAssignment:
    """Greedily pack semantic apps into runtime package slots.

    Current DFU3500 SimICT evidence supports one runtime app image per runnable
    package.  Multi-app OpenFabric programs can still be planned, but they need
    an explicit runtime launch plan before becoming one complete runnable
    program.
    """

    ordered_app_ids = tuple(range(app_plan.app_count))
    if runtime_profile.max_runtime_apps_per_package <= 0:
        return RuntimePackageAssignment(
            source_program=app_plan.source_program,
            runtime_profile=runtime_profile,
            packages=(),
            attrs={
                "lowering_status": "unsupported_vendor_profile",
                "reason": "max_runtime_apps_per_package must be positive",
            },
        )

    package_groups: list[list[int]] = []
    current_group: list[int] = []
    for app_id in ordered_app_ids:
        if len(current_group) >= runtime_profile.max_runtime_apps_per_package:
            package_groups.append(current_group)
            current_group = []
        current_group.append(app_id)
    if current_group:
        package_groups.append(current_group)

    multi_package_program = len(package_groups) > 1
    packages: list[RuntimePackage] = []
    for package_index, group in enumerate(package_groups):
        semantic_app_ids = tuple(group)
        app_names = tuple(f"app{app_id}" for app_id in group)
        storage_inputs = tuple(
            storage_ref
            for app_id in group
            for storage_ref in app_plan.app_input_storage_refs[app_id]
            if storage_ref not in app_plan.app_output_storage_refs[app_id]
        )
        storage_outputs = tuple(
            storage_ref
            for app_id in group
            for storage_ref in app_plan.app_output_storage_refs[app_id]
        )
        refusal_reasons: list[str] = []
        status: RuntimePackageStatus = "runnable_single_package"
        if len(group) > 1 and not runtime_profile.supports_single_package_multi_semantic_app:
            status = "unsupported_vendor_profile"
            refusal_reasons.append(
                "runtime profile does not support multi-semantic-app packages"
            )
        elif multi_package_program and not runtime_profile.supports_multi_package_launch:
            status = "requires_runtime_launch_plan"
            refusal_reasons.append(
                "complete program needs an explicit multi-package launch plan"
            )
        packages.append(
            RuntimePackage(
                package_id=f"package{package_index}",
                package_index=package_index,
                semantic_app_ids=semantic_app_ids,
                app_names=app_names,
                binary_emission_status=status,
                mapping_kind="greedy_semantic_app_group",
                storage_inputs=storage_inputs,
                storage_outputs=storage_outputs,
                refusal_reasons=tuple(refusal_reasons),
                attrs={
                    "semantic_app_count": len(group),
                    "runtime_profile_id": runtime_profile.profile_id,
                },
            )
        )

    return RuntimePackageAssignment(
        source_program=app_plan.source_program,
        runtime_profile=runtime_profile,
        packages=tuple(packages),
    )
