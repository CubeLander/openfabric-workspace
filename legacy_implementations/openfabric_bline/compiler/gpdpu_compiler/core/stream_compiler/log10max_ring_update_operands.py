"""Operand placeholder/allocation/patch reports for log10max ring updates.

This module is the B-line stop-bleed layer between TemplateOp/BinaryLayout
intent and final ``inst_t`` bytes.  It deliberately stays report-only:
allocation-backed candidate rows may be packed and decoded here, but they are
not final CBUF component rows and do not clear runtime_ready.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Literal

from gpdpu_compiler.core.program_legacy_inst import (
    INST_RECORD_SIZE_BYTES,
    OPERANDS_PER_OPERAND_RAM,
    OPERANDS_RAM_NUM,
    LegacyInst,
    decode_legacy_inst_skeleton,
    pack_legacy_inst,
)

from .log10max_ring_update_template import (
    RING_UPDATE_BYPASS_BITS,
    RING_UPDATE_FMAX_ITER_EXE_COND,
    RING_UPDATE_FMAX_LATENCY,
    RING_UPDATE_FMAX_OPERAND_FIELD_USAGE,
    RING_UPDATE_FMAX_OPCODE,
    RING_UPDATE_FMAX_UNIT_INST_TYPE,
    RING_UPDATE_FORWARDING_BITS,
    RingUpdateBinaryLayoutCandidateReport,
    RingUpdateBinaryLayoutRowCandidate,
    build_log10max_ring_update_binary_layout_candidate_report,
)


EXPECTED_PHASE_COUNTS = {
    "col_broadcast": 3,
    "col_reduce": 3,
    "row_broadcast": 12,
    "row_reduce": 12,
}
PLACEHOLDER_ROLES = (
    "globalmax_acc_in",
    "globalmax_recv",
    "globalmax_acc_out",
)
ENDPOINT_PLACEHOLDER_ROLES = (
    "local_reduce_max_out",
    "max_with_floor_globalmax_src",
)
EXPECTED_PHASE_PLACEHOLDER_COUNTS = {
    phase: count * len(PLACEHOLDER_ROLES)
    for phase, count in EXPECTED_PHASE_COUNTS.items()
}
LOG10MAX_RING_UPDATE_ALLOCATOR = "dfu3500_bline_linear_task_pe_allocator"
LOG10MAX_RING_UPDATE_LAYOUT_PROFILE = "dfu3500_operand_idx_layout_v1"
DFU3500_BLINE_LINEAR_ALLOCATOR_ID = LOG10MAX_RING_UPDATE_ALLOCATOR
DFU3500_OPERAND_LAYOUT_PROFILE_ID = LOG10MAX_RING_UPDATE_LAYOUT_PROFILE
LOG10MAX_RING_UPDATE_PATCH_BLOCKER = "log10max_ring_update_route_operand_patch_missing"
LOG10MAX_RING_UPDATE_COMPONENT_BLOCKER = (
    "log10max_ring_update_component_integration_missing"
)
LOG10MAX_RING_ROUTE_LOCAL_REDUCE_BLOCKER = (
    "log10max_ring_route_push_local_reduce_operand_allocation_missing"
)
LOG10MAX_ROUTE_ROW_BYTES_BLOCKER = "log10max_route_row_bytes_missing"
LOG10MAX_MAX_WITH_FLOOR_ROW_BYTES_BLOCKER = (
    "log10max_max_with_floor_row_bytes_missing"
)
LOG10MAX_COMPONENT_INTEGRATION_BLOCKER = "log10max_component_integration_missing"
LOG10MAX_MAX_WITH_FLOOR_LOG_SPEC_DEFERRED_BLOCKER = (
    "log10max_max_with_floor_log_spec_operand_deferred"
)
LOG10MAX_MAX_WITH_FLOOR_CONSTANTS_DEFERRED_BLOCKER = (
    "log10max_max_with_floor_constants_deferred"
)
LOG10MAX_MAX_WITH_FLOOR_OUTPUT_DEFERRED_BLOCKER = (
    "log10max_max_with_floor_output_operand_deferred"
)
LOG10MAX_ENDPOINT_PLACEHOLDER_BLOCKER = (
    "log10max_endpoint_operand_placeholders_missing"
)
LOG10MAX_ENDPOINT_ALLOCATION_BLOCKER = (
    "log10max_endpoint_operand_allocation_missing"
)
LOG10MAX_ENDPOINT_PATCH_BLOCKER = "log10max_endpoint_operand_patch_missing"
LOG10MAX_MAX_WITH_FLOOR_GLOBALMAX_BLOCKER = (
    "log10max_max_with_floor_globalmax_operand_allocation_missing"
)


@dataclass(frozen=True)
class Dfu3500OperandIndexLayout:
    """Canonical operand index layout mirrored from vendor Task_Resource."""

    profile_id: str
    operands_ram_num: int = OPERANDS_RAM_NUM
    operands_per_operand_ram: int = OPERANDS_PER_OPERAND_RAM

    def operand_idx_from_logical_reg(self, reg_idx: int) -> int:
        reg_idx = int(reg_idx)
        return (
            (reg_idx % self.operands_ram_num) * self.operands_per_operand_ram
            + reg_idx // self.operands_ram_num
        )

    def split_operand_idx(self, operand_idx: int) -> tuple[int, int]:
        operand_idx = int(operand_idx)
        return (
            operand_idx // self.operands_per_operand_ram,
            operand_idx % self.operands_per_operand_ram,
        )

    @property
    def capacity(self) -> int:
        return self.operands_ram_num * self.operands_per_operand_ram

    def to_plan(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "layout_profile_id": self.profile_id,
            "operands_ram_num": self.operands_ram_num,
            "operands_per_operand_ram": self.operands_per_operand_ram,
            "capacity": self.capacity,
            "formula": (
                "operand_idx=(reg_idx % operands_ram_num) * "
                "operands_per_operand_ram + reg_idx // operands_ram_num"
            ),
            "layout_formula": (
                "(reg_idx % operands_ram_num) * operands_per_operand_ram "
                "+ reg_idx // operands_ram_num"
            ),
        }


@dataclass(frozen=True)
class OperandPlaceholder:
    """Logical operand role for one ring-update row candidate."""

    schema_version: str
    placeholder_id: str
    operator: Literal["log10max"]
    row_candidate_id: str
    role: Literal[
        "globalmax_acc_in",
        "globalmax_recv",
        "globalmax_acc_out",
        "local_reduce_max_out",
        "max_with_floor_globalmax_src",
    ]
    value_kind: Literal["replicated_vector"]
    app_id: int
    task_id: int
    pe: str
    allocation_scope: str
    source_ring_edge_id: str
    source_stream_action_id: str
    source_fiber_op_id: str
    template_expansion_id: str
    recv_stream_action_id: str
    paired_push_stream_action_id: str
    producer_placeholder_ids: tuple[str, ...]
    producer_stream_action_ids: tuple[str, ...]
    consumer_stream_action_ids: tuple[str, ...]
    consumer_placeholder_ids: tuple[str, ...]
    alias_policy: Literal["forbidden"]

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "placeholder_id": self.placeholder_id,
            "operator": self.operator,
            "row_candidate_id": self.row_candidate_id,
            "role": self.role,
            "value_kind": self.value_kind,
            "dtype": "fp32",
            "app_id": self.app_id,
            "task_id": self.task_id,
            "pe": self.pe,
            "allocation_scope": self.allocation_scope,
            "source_ring_edge_id": self.source_ring_edge_id,
            "source_stream_action_id": self.source_stream_action_id,
            "source_fiber_op_id": self.source_fiber_op_id,
            "template_expansion_id": self.template_expansion_id,
            "recv_stream_action_id": self.recv_stream_action_id,
            "paired_push_stream_action_id": self.paired_push_stream_action_id,
            "producer_placeholder_ids": list(self.producer_placeholder_ids),
            "producer_stream_action_ids": list(self.producer_stream_action_ids),
            "consumer_stream_action_ids": list(self.consumer_stream_action_ids),
            "consumer_placeholder_ids": list(self.consumer_placeholder_ids),
            "consumer_refs": list(
                self.consumer_stream_action_ids
                + self.consumer_placeholder_ids
                + (
                    (f"route_recv:{self.recv_stream_action_id}",)
                    if self.role == "globalmax_recv"
                    else ()
                )
            ),
            "alias_policy": self.alias_policy,
            "allocation_required": True,
            "allocation_status": "unallocated",
            "source_template_fixed_allowed": False,
            "hardcoded_operand_idx_allowed": False,
            "blockers": [_placeholder_allocation_blocker(self.role)],
            "source_binary_row_candidate_id": self.row_candidate_id,
        }


@dataclass(frozen=True)
class RingUpdateOperandPlaceholderReport:
    """Phase-1 operand placeholders for the 30 FMAX update rows."""

    profile_id: str
    source_layout_report_id: str
    placeholders: tuple[OperandPlaceholder, ...]

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        if not self.placeholders:
            return ("log10max_ring_update_operand_placeholders_missing",)
        return ("log10max_ring_update_operand_allocation_missing",)

    @property
    def runtime_ready(self) -> bool:
        return False

    def summary(self) -> dict[str, object]:
        role_counts: dict[str, int] = {}
        phase_counts: dict[str, int] = {}
        scope_counts: dict[str, int] = {}
        producer_linked = 0
        consumer_linked = 0
        for placeholder in self.placeholders:
            role_counts[placeholder.role] = role_counts.get(placeholder.role, 0) + 1
            phase = _phase_from_edge_id(placeholder.source_ring_edge_id)
            phase_counts[phase] = phase_counts.get(phase, 0) + 1
            scope_counts[placeholder.allocation_scope] = (
                scope_counts.get(placeholder.allocation_scope, 0) + 1
            )
            if (
                placeholder.producer_placeholder_ids
                or placeholder.producer_stream_action_ids
            ):
                producer_linked += 1
            if (
                placeholder.consumer_placeholder_ids
                or placeholder.consumer_stream_action_ids
            ):
                consumer_linked += 1
        return {
            "profile_id": self.profile_id,
            "source_layout_report_id": self.source_layout_report_id,
            "placeholder_count": len(self.placeholders),
            "row_candidate_count": len({p.row_candidate_id for p in self.placeholders}),
            "role_counts": dict(sorted(role_counts.items())),
            "phase_placeholder_counts": dict(sorted(phase_counts.items())),
            "phase_counts": dict(sorted(phase_counts.items())),
            "allocation_scope_count": len(scope_counts),
            "owner_scope_counts": {"task_pe": len(self.placeholders)},
            "producer_linked_placeholder_count": producer_linked,
            "consumer_linked_placeholder_count": consumer_linked,
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "component_integration_claim": False,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_ring_update_operand_placeholder_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "blocker_ids": list(self.blocker_ids),
            "layout_profile": Dfu3500OperandIndexLayout(
                LOG10MAX_RING_UPDATE_LAYOUT_PROFILE
            ).to_plan(),
            "placeholders": [placeholder.to_plan() for placeholder in self.placeholders],
            "layering_policy": (
                "placeholders name logical operands only; no physical operand "
                "indices or final inst_t rows are emitted"
            ),
        }


@dataclass(frozen=True)
class Log10MaxEndpointOperandPlaceholderReport:
    """Endpoint placeholders that project into the generic OperandPlaceholder."""

    profile_id: str
    source_layout_report_id: str
    participating_pes: tuple[str, ...]
    consumer_pes: tuple[str, ...]
    placeholders: tuple[OperandPlaceholder, ...]

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        if not self.placeholders:
            return (LOG10MAX_ENDPOINT_PLACEHOLDER_BLOCKER,)
        return (LOG10MAX_ENDPOINT_ALLOCATION_BLOCKER,)

    @property
    def runtime_ready(self) -> bool:
        return False

    def summary(self) -> dict[str, object]:
        role_counts: dict[str, int] = {}
        scope_counts: dict[str, int] = {}
        for placeholder in self.placeholders:
            role_counts[placeholder.role] = role_counts.get(placeholder.role, 0) + 1
            scope_counts[placeholder.allocation_scope] = (
                scope_counts.get(placeholder.allocation_scope, 0) + 1
            )
        return {
            "profile_id": self.profile_id,
            "source_layout_report_id": self.source_layout_report_id,
            "participating_pe_count": len(self.participating_pes),
            "consumer_pe_count": len(self.consumer_pes),
            "local_reduce_endpoint_placeholder_count": role_counts.get(
                "local_reduce_max_out", 0
            ),
            "max_with_floor_endpoint_placeholder_count": role_counts.get(
                "max_with_floor_globalmax_src", 0
            ),
            "placeholder_count": len(self.placeholders),
            "role_counts": dict(sorted(role_counts.items())),
            "allocation_scope_count": len(scope_counts),
            "blocker_ids": list(self.blocker_ids),
            "runtime_ready": self.runtime_ready,
            "component_integration_claim": False,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_endpoint_operand_placeholder_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "blocker_ids": list(self.blocker_ids),
            "participating_pes": list(self.participating_pes),
            "consumer_pes": list(self.consumer_pes),
            "placeholders": [placeholder.to_plan() for placeholder in self.placeholders],
            "layering_policy": (
                "endpoint records are log10max-specific views projected into "
                "generic OperandPlaceholder records; the allocator contract is "
                "not duplicated"
            ),
        }


@dataclass(frozen=True)
class OperandAllocation:
    """Physical DFU operand index assignment for one placeholder."""

    schema_version: str
    allocation_id: str
    placeholder_id: str
    allocator: Literal["dfu3500_bline_linear_task_pe_allocator"]
    allocation_kind: Literal["new_monotonic_no_reuse", "value_identity_reuse", "blocked"]
    app_id: int
    task_id: int
    pe: str
    layout_profile_id: str
    logical_reg_idx: int
    operand_idx: int
    operand_ram: int
    operand_line: int
    allocation_scope: str
    alias_group: str | None
    producer_allocation_ids: tuple[str, ...]
    allocation_status: Literal["allocated", "blocked"]
    evidence_refs: tuple[str, ...]
    blockers: tuple[str, ...]

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "allocation_id": self.allocation_id,
            "placeholder_id": self.placeholder_id,
            "allocator": self.allocator,
            "allocation_kind": self.allocation_kind,
            "app_id": self.app_id,
            "task_id": self.task_id,
            "pe": self.pe,
            "layout_profile_id": self.layout_profile_id,
            "logical_reg_idx": self.logical_reg_idx,
            "operand_idx": self.operand_idx,
            "operand_ram": self.operand_ram,
            "operand_line": self.operand_line,
            "allocation_scope": self.allocation_scope,
            "alias_group": self.alias_group,
            "producer_allocation_ids": list(self.producer_allocation_ids),
            "allocation_status": self.allocation_status,
            "evidence_refs": list(self.evidence_refs),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class RingUpdateOperandAllocationReport:
    """Phase-2 deterministic task_pe allocation report."""

    profile_id: str
    source_placeholder_report_id: str
    allocations: tuple[OperandAllocation, ...]

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.allocations:
            blockers.append("log10max_ring_update_operand_allocation_missing")
        for allocation in self.allocations:
            blockers.extend(allocation.blockers)
        if not blockers:
            blockers.append("log10max_ring_update_inst_operand_patch_missing")
        return tuple(dict.fromkeys(blockers))

    @property
    def runtime_ready(self) -> bool:
        return False

    def summary(self) -> dict[str, object]:
        status_counts: dict[str, int] = {}
        kind_counts: dict[str, int] = {}
        scope_counts: dict[str, int] = {}
        new_physical: set[tuple[str, int]] = set()
        duplicate_new_operand_count = 0
        for allocation in self.allocations:
            status_counts[allocation.allocation_status] = (
                status_counts.get(allocation.allocation_status, 0) + 1
            )
            kind_counts[allocation.allocation_kind] = (
                kind_counts.get(allocation.allocation_kind, 0) + 1
            )
            scope_counts[allocation.allocation_scope] = (
                scope_counts.get(allocation.allocation_scope, 0) + 1
            )
            if allocation.allocation_kind == "new_monotonic_no_reuse":
                key = (allocation.allocation_scope, allocation.operand_idx)
                if key in new_physical:
                    duplicate_new_operand_count += 1
                new_physical.add(key)
        return {
            "profile_id": self.profile_id,
            "source_placeholder_report_id": self.source_placeholder_report_id,
            "allocator": LOG10MAX_RING_UPDATE_ALLOCATOR,
            "layout_profile_id": LOG10MAX_RING_UPDATE_LAYOUT_PROFILE,
            "allocation_count": len(self.allocations),
            "allocation_kind_counts": dict(sorted(kind_counts.items())),
            "allocation_status_counts": dict(sorted(status_counts.items())),
            "allocation_scope_count": len(scope_counts),
            "duplicate_new_operand_count": duplicate_new_operand_count,
            "blocker_ids": list(self.blocker_ids),
            "allocation_ready_for_patch": bool(self.allocations)
            and all(
                allocation.allocation_status == "allocated"
                for allocation in self.allocations
            ),
            "runtime_ready": self.runtime_ready,
            "component_integration_claim": False,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_ring_update_operand_allocation_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "blocker_ids": list(self.blocker_ids),
            "layout": Dfu3500OperandIndexLayout(
                LOG10MAX_RING_UPDATE_LAYOUT_PROFILE
            ).to_plan(),
            "layout_profile": Dfu3500OperandIndexLayout(
                LOG10MAX_RING_UPDATE_LAYOUT_PROFILE
            ).to_plan(),
            "allocations": [allocation.to_plan() for allocation in self.allocations],
            "allocator_policy": {
                "allocator": LOG10MAX_RING_UPDATE_ALLOCATOR,
                "scope": "task_pe",
                "monotonic_no_reuse": True,
                "capacity_guard": True,
                "instruction_src_dst_aliasing": "forbidden",
                "value_identity_reuse": "allowed_for_single_producer_placeholder",
            },
        }


@dataclass(frozen=True)
class Log10MaxUnifiedOperandAllocationReport:
    """Unified allocation report for ring-update and endpoint placeholders."""

    profile_id: str
    source_placeholder_report_id: str
    allocations: tuple[OperandAllocation, ...]
    placeholder_count: int
    ring_update_placeholder_count: int
    endpoint_placeholder_count: int

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.allocations:
            blockers.append(LOG10MAX_ENDPOINT_ALLOCATION_BLOCKER)
        for allocation in self.allocations:
            blockers.extend(allocation.blockers)
        if not blockers:
            blockers.append(LOG10MAX_ENDPOINT_PATCH_BLOCKER)
        return tuple(dict.fromkeys(blockers))

    @property
    def runtime_ready(self) -> bool:
        return False

    def summary(self) -> dict[str, object]:
        status_counts: dict[str, int] = {}
        kind_counts: dict[str, int] = {}
        scope_counts: dict[str, int] = {}
        new_physical: set[tuple[str, int]] = set()
        duplicate_new_operand_count = 0
        endpoint_allocation_count = 0
        ring_update_allocation_count = 0
        for allocation in self.allocations:
            status_counts[allocation.allocation_status] = (
                status_counts.get(allocation.allocation_status, 0) + 1
            )
            kind_counts[allocation.allocation_kind] = (
                kind_counts.get(allocation.allocation_kind, 0) + 1
            )
            scope_counts[allocation.allocation_scope] = (
                scope_counts.get(allocation.allocation_scope, 0) + 1
            )
            if _placeholder_role_from_id(allocation.placeholder_id) in ENDPOINT_PLACEHOLDER_ROLES:
                endpoint_allocation_count += 1
            else:
                ring_update_allocation_count += 1
            if allocation.allocation_kind == "new_monotonic_no_reuse":
                key = (allocation.allocation_scope, allocation.operand_idx)
                if key in new_physical:
                    duplicate_new_operand_count += 1
                new_physical.add(key)
        return {
            "profile_id": self.profile_id,
            "source_placeholder_report_id": self.source_placeholder_report_id,
            "allocator": LOG10MAX_RING_UPDATE_ALLOCATOR,
            "layout_profile_id": LOG10MAX_RING_UPDATE_LAYOUT_PROFILE,
            "placeholder_count": self.placeholder_count,
            "allocation_record_count": len(self.allocations),
            "allocation_count": len(self.allocations),
            "ring_update_placeholder_count": self.ring_update_placeholder_count,
            "endpoint_placeholder_count": self.endpoint_placeholder_count,
            "ring_update_allocation_count": ring_update_allocation_count,
            "endpoint_allocation_count": endpoint_allocation_count,
            "new_operand_allocation_count": kind_counts.get(
                "new_monotonic_no_reuse", 0
            ),
            "value_identity_reuse_count": kind_counts.get("value_identity_reuse", 0),
            "source_template_fixed_count": 0,
            "blocked_count": status_counts.get("blocked", 0),
            "allocation_kind_counts": dict(sorted(kind_counts.items())),
            "allocation_status_counts": dict(sorted(status_counts.items())),
            "allocation_scope_count": len(scope_counts),
            "duplicate_new_operand_count": duplicate_new_operand_count,
            "blocker_ids": list(self.blocker_ids),
            "allocation_ready_for_endpoint_patch": bool(self.allocations)
            and all(
                allocation.allocation_status == "allocated"
                for allocation in self.allocations
            ),
            "runtime_ready": self.runtime_ready,
            "final_row_bytes_claim": False,
            "component_integration_claim": False,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_unified_operand_allocation_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "blocker_ids": list(self.blocker_ids),
            "layout": Dfu3500OperandIndexLayout(
                LOG10MAX_RING_UPDATE_LAYOUT_PROFILE
            ).to_plan(),
            "layout_profile": Dfu3500OperandIndexLayout(
                LOG10MAX_RING_UPDATE_LAYOUT_PROFILE
            ).to_plan(),
            "allocations": [allocation.to_plan() for allocation in self.allocations],
            "allocator_policy": {
                "allocator": LOG10MAX_RING_UPDATE_ALLOCATOR,
                "scope": "task_pe",
                "monotonic_no_reuse": True,
                "capacity_guard": True,
                "instruction_src_dst_aliasing": "forbidden",
                "value_identity_reuse": (
                    "required for local_reduce->initial_acc_in and "
                    "final_acc_out->max_with_floor_globalmax_src"
                ),
            },
        }


@dataclass(frozen=True)
class InstOperandPatch:
    """Patch record for one FMAX update row candidate."""

    schema_version: str
    patch_id: str
    row_candidate_id: str
    opcode: Literal["FMAX"]
    source_ring_edge_id: str
    source_stream_action_id: str
    source_fiber_op_id: str
    template_expansion_id: str
    allocation_ids: tuple[str, ...]
    src_placeholders: tuple[str, ...]
    dst_placeholders: tuple[str, ...]
    src_operands_idx: tuple[int, int, int]
    dst_operands_idx: tuple[int, int, int]
    operand_field_usage: tuple[tuple[str, str], ...]
    raw_inst_t_byte_count: int
    raw_inst_t_sha256: str
    patch_status: Literal["patched", "blocked"]
    decode_roundtrip_status: Literal["not_run", "candidate_decode_roundtrip"]
    provenance_roundtrip_status: Literal["candidate_report_roundtrip"]
    route_continuity_status: Literal["blocked_missing_route_row_patch"]
    route_continuity_blockers: tuple[str, ...]
    blocker_ids: tuple[str, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def final_row_bytes_claim(self) -> bool:
        return False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "patch_id": self.patch_id,
            "row_candidate_id": self.row_candidate_id,
            "opcode": self.opcode,
            "source_ring_edge_id": self.source_ring_edge_id,
            "source_stream_action_id": self.source_stream_action_id,
            "source_fiber_op_id": self.source_fiber_op_id,
            "template_expansion_id": self.template_expansion_id,
            "allocation_ids": list(self.allocation_ids),
            "src_placeholders": list(self.src_placeholders),
            "dst_placeholders": list(self.dst_placeholders),
            "src_operands_idx": list(self.src_operands_idx),
            "dst_operands_idx": list(self.dst_operands_idx),
            "operand_field_usage": dict(self.operand_field_usage),
            "raw_inst_t_byte_count": self.raw_inst_t_byte_count,
            "raw_inst_t_sha256": self.raw_inst_t_sha256,
            "patch_status": self.patch_status,
            "decode_roundtrip_status": self.decode_roundtrip_status,
            "provenance_roundtrip_status": self.provenance_roundtrip_status,
            "route_continuity_status": self.route_continuity_status,
            "route_continuity_blockers": list(self.route_continuity_blockers),
            "blocker_ids": list(self.blocker_ids),
            "final_row_bytes_claim": self.final_row_bytes_claim,
            "runtime_ready": self.runtime_ready,
        }


@dataclass(frozen=True)
class RingUpdateInstOperandPatchReport:
    """Phase-3 allocation-backed patch report for FMAX update candidates."""

    profile_id: str
    source_allocation_report_id: str
    patches: tuple[InstOperandPatch, ...]

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.patches:
            blockers.append("log10max_ring_update_inst_operand_patch_missing")
        for patch in self.patches:
            blockers.extend(patch.blocker_ids)
        return tuple(dict.fromkeys(blockers))

    @property
    def runtime_ready(self) -> bool:
        return False

    def summary(self) -> dict[str, object]:
        status_counts: dict[str, int] = {}
        decode_counts: dict[str, int] = {}
        continuity_counts: dict[str, int] = {}
        byte_count = 0
        for patch in self.patches:
            status_counts[patch.patch_status] = (
                status_counts.get(patch.patch_status, 0) + 1
            )
            decode_counts[patch.decode_roundtrip_status] = (
                decode_counts.get(patch.decode_roundtrip_status, 0) + 1
            )
            continuity_counts[patch.route_continuity_status] = (
                continuity_counts.get(patch.route_continuity_status, 0) + 1
            )
            byte_count += patch.raw_inst_t_byte_count
        return {
            "profile_id": self.profile_id,
            "source_allocation_report_id": self.source_allocation_report_id,
            "patch_count": len(self.patches),
            "patch_status_counts": dict(sorted(status_counts.items())),
            "decode_roundtrip_status_counts": dict(sorted(decode_counts.items())),
            "route_continuity_status_counts": dict(sorted(continuity_counts.items())),
            "raw_inst_t_byte_count": byte_count,
            "blocker_ids": list(self.blocker_ids),
            "candidate_decode_roundtrip_claim": bool(self.patches),
            "final_row_bytes_claim": False,
            "component_integration_claim": False,
            "runtime_ready": self.runtime_ready,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_ring_update_inst_operand_patch_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "blocker_ids": list(self.blocker_ids),
            "patches": [patch.to_plan() for patch in self.patches],
            "layering_policy": (
                "patches consume OperandAllocation records and create "
                "allocation-backed candidate pack/decode rows only; route rows "
                "and final components are not patched here"
            ),
        }


@dataclass(frozen=True)
class RouteOperandPatch:
    """Report-only operand patch candidate for GlobalMax route push/recv rows."""

    schema_version: str
    patch_id: str
    direction: Literal["push", "recv"]
    source_ring_edge_id: str
    source_stream_action_id: str
    source_fiber_op_id: str
    paired_stream_action_id: str
    task_id: int
    src_pe: str
    dst_pe: str
    expected_allocation_scope: str
    allocation_scope: str
    scope_status: Literal["sender_task_pe", "receiver_task_pe", "blocked"]
    src_placeholders: tuple[str, ...]
    dst_placeholders: tuple[str, ...]
    allocation_ids: tuple[str, ...]
    src_operands_idx: tuple[int, int, int]
    dst_operands_idx: tuple[int, int, int]
    operand_field_usage: tuple[tuple[str, str], ...]
    patch_status: Literal["patched", "blocked"]
    blockers: tuple[str, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def final_row_bytes_claim(self) -> bool:
        return False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "patch_id": self.patch_id,
            "direction": self.direction,
            "source_ring_edge_id": self.source_ring_edge_id,
            "source_stream_action_id": self.source_stream_action_id,
            "source_fiber_op_id": self.source_fiber_op_id,
            "paired_stream_action_id": self.paired_stream_action_id,
            "task_id": self.task_id,
            "src_pe": self.src_pe,
            "dst_pe": self.dst_pe,
            "expected_allocation_scope": self.expected_allocation_scope,
            "allocation_scope": self.allocation_scope,
            "scope_status": self.scope_status,
            "src_placeholders": list(self.src_placeholders),
            "dst_placeholders": list(self.dst_placeholders),
            "allocation_ids": list(self.allocation_ids),
            "src_operands_idx": list(self.src_operands_idx),
            "dst_operands_idx": list(self.dst_operands_idx),
            "operand_field_usage": dict(self.operand_field_usage),
            "patch_status": self.patch_status,
            "blockers": list(self.blockers),
            "final_row_bytes_claim": self.final_row_bytes_claim,
            "runtime_ready": self.runtime_ready,
        }


@dataclass(frozen=True)
class RingRouteOperandPatchReport:
    """Phase-3b route push/recv operand patch continuity report."""

    profile_id: str
    source_allocation_report_id: str
    patches: tuple[RouteOperandPatch, ...]

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.patches:
            blockers.append("log10max_ring_route_operand_patch_missing")
        for patch in self.patches:
            blockers.extend(patch.blockers)
        return tuple(dict.fromkeys(blockers))

    @property
    def runtime_ready(self) -> bool:
        return False

    def summary(self) -> dict[str, object]:
        direction_counts: dict[str, int] = {}
        status_counts: dict[str, int] = {}
        blocker_counts: dict[str, int] = {}
        for patch in self.patches:
            direction_counts[patch.direction] = (
                direction_counts.get(patch.direction, 0) + 1
            )
            status_counts[patch.patch_status] = (
                status_counts.get(patch.patch_status, 0) + 1
            )
            for blocker in patch.blockers:
                blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
        return {
            "profile_id": self.profile_id,
            "source_allocation_report_id": self.source_allocation_report_id,
            "patch_count": len(self.patches),
            "direction_counts": dict(sorted(direction_counts.items())),
            "patch_status_counts": dict(sorted(status_counts.items())),
            "blocker_counts": dict(sorted(blocker_counts.items())),
            "blocker_ids": list(self.blocker_ids),
            "final_row_bytes_claim": False,
            "component_integration_claim": False,
            "runtime_ready": self.runtime_ready,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_ring_route_operand_patch_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "blocker_ids": list(self.blocker_ids),
            "patches": [patch.to_plan() for patch in self.patches],
            "layering_policy": (
                "route operand patches bind existing GlobalMax route push/recv "
                "roles to OperandAllocation records; they do not emit route "
                "row bytes or final component rows"
            ),
        }


@dataclass(frozen=True)
class MaxWithFloorGlobalMaxOperandPatch:
    """Report-only patch for the max_with_floor GlobalMax source operand.

    This proves only the GlobalMax input continuity.  It does not claim the
    log_spec source, constants, output, row bytes, or component placement.
    """

    schema_version: str
    patch_id: str
    consumer_fiber_op: Literal["max_with_floor_tile"]
    consumer_operand_role: Literal["globalmax_src"]
    app_id: int
    task_id: int
    pe: str
    allocation_scope: str
    source_ring_edge_id: str
    source_stream_action_id: str
    source_fiber_op_id: str
    producer_placeholder_id: str
    consumer_placeholder_id: str
    allocation_id: str
    producer_allocation_id: str
    operand_idx: int
    operand_ram: int
    operand_line: int
    value_identity_reuse: bool
    globalmax_source_patch_status: Literal["patched", "blocked"]
    log_spec_source_status: Literal["deferred_named"]
    constants_status: Literal["deferred_named"]
    output_operand_status: Literal["deferred_named"]
    final_row_bytes_claim: bool
    component_integration_claim: bool
    blocker_ids: tuple[str, ...]

    @property
    def runtime_ready(self) -> bool:
        return False

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "patch_id": self.patch_id,
            "consumer_fiber_op": self.consumer_fiber_op,
            "consumer_operand_role": self.consumer_operand_role,
            "app_id": self.app_id,
            "task_id": self.task_id,
            "pe": self.pe,
            "allocation_scope": self.allocation_scope,
            "source_ring_edge_id": self.source_ring_edge_id,
            "source_stream_action_id": self.source_stream_action_id,
            "source_fiber_op_id": self.source_fiber_op_id,
            "producer_placeholder_id": self.producer_placeholder_id,
            "consumer_placeholder_id": self.consumer_placeholder_id,
            "allocation_id": self.allocation_id,
            "producer_allocation_id": self.producer_allocation_id,
            "operand_idx": self.operand_idx,
            "operand_ram": self.operand_ram,
            "operand_line": self.operand_line,
            "value_identity_reuse": self.value_identity_reuse,
            "globalmax_source_patch_status": self.globalmax_source_patch_status,
            "log_spec_source_status": self.log_spec_source_status,
            "constants_status": self.constants_status,
            "output_operand_status": self.output_operand_status,
            "final_row_bytes_claim": self.final_row_bytes_claim,
            "component_integration_claim": self.component_integration_claim,
            "runtime_ready": self.runtime_ready,
            "blocker_ids": list(self.blocker_ids),
            "scope_policy": "consumer-owned task_pe operand identity",
            "postprocess_completion_claim": False,
        }


@dataclass(frozen=True)
class MaxWithFloorGlobalMaxOperandPatchReport:
    """Phase-4 report for max_with_floor GlobalMax source continuity."""

    profile_id: str
    source_allocation_report_id: str
    patches: tuple[MaxWithFloorGlobalMaxOperandPatch, ...]

    @property
    def blocker_ids(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.patches:
            blockers.append("log10max_max_with_floor_globalmax_operand_allocation_missing")
        for patch in self.patches:
            blockers.extend(patch.blocker_ids)
        return tuple(dict.fromkeys(blockers))

    @property
    def runtime_ready(self) -> bool:
        return False

    def summary(self) -> dict[str, object]:
        status_counts: dict[str, int] = {}
        blocker_counts: dict[str, int] = {}
        pe_set: set[str] = set()
        scope_set: set[str] = set()
        value_identity_reuse_count = 0
        for patch in self.patches:
            status_counts[patch.globalmax_source_patch_status] = (
                status_counts.get(patch.globalmax_source_patch_status, 0) + 1
            )
            if patch.value_identity_reuse:
                value_identity_reuse_count += 1
            pe_set.add(patch.pe)
            scope_set.add(patch.allocation_scope)
            for blocker in patch.blocker_ids:
                blocker_counts[blocker] = blocker_counts.get(blocker, 0) + 1
        return {
            "profile_id": self.profile_id,
            "source_allocation_report_id": self.source_allocation_report_id,
            "patch_count": len(self.patches),
            "consumer_pe_count": len(pe_set),
            "allocation_scope_count": len(scope_set),
            "globalmax_source_patch_status_counts": dict(sorted(status_counts.items())),
            "value_identity_reuse_count": value_identity_reuse_count,
            "blocker_counts": dict(sorted(blocker_counts.items())),
            "blocker_ids": list(self.blocker_ids),
            "globalmax_source_allocation_claim": bool(self.patches)
            and all(
                patch.globalmax_source_patch_status == "patched"
                and patch.value_identity_reuse
                for patch in self.patches
            ),
            "postprocess_completion_claim": False,
            "final_row_bytes_claim": False,
            "component_integration_claim": False,
            "runtime_ready": self.runtime_ready,
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_max_with_floor_globalmax_operand_patch_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "blocker_ids": list(self.blocker_ids),
            "patches": [patch.to_plan() for patch in self.patches],
            "layering_policy": (
                "max_with_floor GlobalMax source patches consume final "
                "globalmax_acc_out OperandAllocation records through value "
                "identity reuse; they do not claim max_with_floor row bytes or "
                "complete postprocess lowering"
            ),
        }


def build_log10max_ring_update_operand_placeholder_report(
    layout_report: RingUpdateBinaryLayoutCandidateReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_ring_update_operand_placeholder_v1",
) -> RingUpdateOperandPlaceholderReport:
    layout = layout_report or build_log10max_ring_update_binary_layout_candidate_report()
    placeholders = _build_placeholders(layout.row_candidates)
    return RingUpdateOperandPlaceholderReport(
        profile_id=profile_id,
        source_layout_report_id=layout.profile_id,
        placeholders=placeholders,
    )


def build_log10max_endpoint_operand_placeholder_report(
    layout_report: RingUpdateBinaryLayoutCandidateReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_endpoint_operand_placeholder_v1",
) -> Log10MaxEndpointOperandPlaceholderReport:
    layout = layout_report or build_log10max_ring_update_binary_layout_candidate_report()
    participating_pes = _participating_pes(layout.row_candidates)
    final_value_by_pe = _final_globalmax_placeholder_by_pe(layout.row_candidates)
    placeholders = _build_endpoint_placeholders(
        layout.row_candidates,
        participating_pes=participating_pes,
        final_value_by_pe=final_value_by_pe,
    )
    return Log10MaxEndpointOperandPlaceholderReport(
        profile_id=profile_id,
        source_layout_report_id=layout.profile_id,
        participating_pes=participating_pes,
        consumer_pes=participating_pes,
        placeholders=placeholders,
    )


def summarize_log10max_endpoint_operand_placeholder_report(
    report: Log10MaxEndpointOperandPlaceholderReport,
) -> dict[str, object]:
    return report.summary()


def summarize_log10max_ring_update_operand_placeholder_report(
    report: RingUpdateOperandPlaceholderReport,
) -> dict[str, object]:
    return report.summary()


def build_log10max_ring_update_operand_allocation_report(
    placeholder_report: RingUpdateOperandPlaceholderReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_ring_update_operand_allocation_v1",
) -> RingUpdateOperandAllocationReport:
    placeholders = (
        placeholder_report or build_log10max_ring_update_operand_placeholder_report()
    )
    allocations = _allocate_placeholders(placeholders.placeholders)
    return RingUpdateOperandAllocationReport(
        profile_id=profile_id,
        source_placeholder_report_id=placeholders.profile_id,
        allocations=allocations,
    )


def build_log10max_unified_operand_allocation_report(
    layout_report: RingUpdateBinaryLayoutCandidateReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_unified_operand_allocation_v1",
) -> Log10MaxUnifiedOperandAllocationReport:
    layout = layout_report or build_log10max_ring_update_binary_layout_candidate_report()
    endpoint_report = build_log10max_endpoint_operand_placeholder_report(layout)
    ring_placeholders = _build_placeholders(
        layout.row_candidates,
        local_reduce_seed_placeholders=True,
    )
    local_reduce_placeholders = tuple(
        placeholder
        for placeholder in endpoint_report.placeholders
        if placeholder.role == "local_reduce_max_out"
    )
    max_with_floor_placeholders = tuple(
        placeholder
        for placeholder in endpoint_report.placeholders
        if placeholder.role == "max_with_floor_globalmax_src"
    )
    all_placeholders = (
        local_reduce_placeholders + ring_placeholders + max_with_floor_placeholders
    )
    allocations = _allocate_placeholders(all_placeholders)
    return Log10MaxUnifiedOperandAllocationReport(
        profile_id=profile_id,
        source_placeholder_report_id=(
            f"{endpoint_report.profile_id}+"
            "dfu3500_log10max_ring_update_operand_placeholder_v1"
        ),
        allocations=allocations,
        placeholder_count=len(all_placeholders),
        ring_update_placeholder_count=len(ring_placeholders),
        endpoint_placeholder_count=len(endpoint_report.placeholders),
    )


def summarize_log10max_unified_operand_allocation_report(
    report: Log10MaxUnifiedOperandAllocationReport,
) -> dict[str, object]:
    return report.summary()


def summarize_log10max_ring_update_operand_allocation_report(
    report: RingUpdateOperandAllocationReport,
) -> dict[str, object]:
    return report.summary()


def build_log10max_ring_update_inst_operand_patch_report(
    layout_report: RingUpdateBinaryLayoutCandidateReport | None = None,
    allocation_report: RingUpdateOperandAllocationReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_ring_update_inst_operand_patch_v1",
) -> RingUpdateInstOperandPatchReport:
    layout = layout_report or build_log10max_ring_update_binary_layout_candidate_report()
    allocations = allocation_report or build_log10max_ring_update_operand_allocation_report(
        build_log10max_ring_update_operand_placeholder_report(layout)
    )
    patches = _build_patches(layout.row_candidates, allocations.allocations)
    return RingUpdateInstOperandPatchReport(
        profile_id=profile_id,
        source_allocation_report_id=allocations.profile_id,
        patches=patches,
    )


def summarize_log10max_ring_update_inst_operand_patch_report(
    report: RingUpdateInstOperandPatchReport,
) -> dict[str, object]:
    return report.summary()


def build_log10max_ring_route_operand_patch_report(
    layout_report: RingUpdateBinaryLayoutCandidateReport | None = None,
    allocation_report: RingUpdateOperandAllocationReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_ring_route_operand_patch_v1",
) -> RingRouteOperandPatchReport:
    layout = layout_report or build_log10max_ring_update_binary_layout_candidate_report()
    allocations = allocation_report or build_log10max_unified_operand_allocation_report(
        layout
    )
    patches = _build_route_patches(layout.row_candidates, allocations.allocations)
    return RingRouteOperandPatchReport(
        profile_id=profile_id,
        source_allocation_report_id=allocations.profile_id,
        patches=patches,
    )


def summarize_log10max_ring_route_operand_patch_report(
    report: RingRouteOperandPatchReport,
) -> dict[str, object]:
    return report.summary()


def build_log10max_max_with_floor_operand_patch_report(
    placeholder_report: Log10MaxEndpointOperandPlaceholderReport | None = None,
    allocation_report: Log10MaxUnifiedOperandAllocationReport | None = None,
    *,
    profile_id: str = "dfu3500_log10max_max_with_floor_globalmax_operand_patch_v1",
) -> MaxWithFloorGlobalMaxOperandPatchReport:
    if placeholder_report is None:
        layout = build_log10max_ring_update_binary_layout_candidate_report()
        endpoint_report = build_log10max_endpoint_operand_placeholder_report(layout)
        ring_report = build_log10max_ring_update_operand_placeholder_report(layout)
        placeholders = endpoint_report.placeholders + ring_report.placeholders
    else:
        placeholders = placeholder_report.placeholders
    allocations = allocation_report or build_log10max_unified_operand_allocation_report()
    patches = _build_max_with_floor_globalmax_patches(
        placeholders,
        allocations.allocations,
    )
    return MaxWithFloorGlobalMaxOperandPatchReport(
        profile_id=profile_id,
        source_allocation_report_id=allocations.profile_id,
        patches=patches,
    )


def summarize_log10max_max_with_floor_operand_patch_report(
    report: MaxWithFloorGlobalMaxOperandPatchReport,
) -> dict[str, object]:
    return report.summary()


def _build_placeholders(
    rows: tuple[RingUpdateBinaryLayoutRowCandidate, ...],
    *,
    local_reduce_seed_placeholders: bool = False,
) -> tuple[OperandPlaceholder, ...]:
    current_value_by_pe: dict[tuple[int, str], str] = {}
    producer_consumers: dict[str, list[str]] = {}
    placeholders: list[OperandPlaceholder] = []

    for row in rows:
        scope = _allocation_scope(row.task_id, row.dst_pe)
        source_scope = _allocation_scope(row.task_id, row.src_pe)
        source_current = current_value_by_pe.get((row.task_id, row.src_pe))
        if source_current is not None and source_current.startswith("opnd:"):
            producer_consumers.setdefault(source_current, []).append(
                row.paired_push_stream_action_id
            )
        acc_in_producers: tuple[str, ...] = ()
        previous_dst_value = current_value_by_pe.get((row.task_id, row.dst_pe))
        if previous_dst_value is not None and previous_dst_value.startswith("opnd:"):
            acc_in_producers = (previous_dst_value,)
        elif local_reduce_seed_placeholders:
            acc_in_producers = (
                _endpoint_placeholder_id(
                    row.task_id,
                    row.dst_pe,
                    "local_reduce_max_out",
                ),
            )
        acc_in = _placeholder_for_row(
            row=row,
            role="globalmax_acc_in",
            scope=scope,
            producer_placeholder_ids=acc_in_producers,
            producer_stream_action_ids=(),
            consumer_stream_action_ids=(row.source_stream_action_id,),
            consumer_placeholder_ids=(),
        )
        recv = _placeholder_for_row(
            row=row,
            role="globalmax_recv",
            scope=scope,
            producer_placeholder_ids=(),
            producer_stream_action_ids=(row.recv_stream_action_id,),
            consumer_stream_action_ids=(row.source_stream_action_id,),
            consumer_placeholder_ids=(),
        )
        acc_out = _placeholder_for_row(
            row=row,
            role="globalmax_acc_out",
            scope=scope,
            producer_placeholder_ids=(),
            producer_stream_action_ids=(row.source_stream_action_id,),
            consumer_stream_action_ids=(),
            consumer_placeholder_ids=(),
        )
        producer_consumers.setdefault(acc_in.placeholder_id, []).append(
            row.source_stream_action_id
        )
        producer_consumers.setdefault(recv.placeholder_id, []).append(
            row.source_stream_action_id
        )
        placeholders.extend((acc_in, recv, acc_out))
        current_value_by_pe[(row.task_id, row.dst_pe)] = acc_out.placeholder_id
        if source_current is None:
            current_value_by_pe.setdefault(
                (row.task_id, row.src_pe),
                _endpoint_placeholder_id(
                    row.task_id,
                    row.src_pe,
                    "local_reduce_max_out",
                )
                if local_reduce_seed_placeholders
                else f"external:local_reduce_max:{source_scope}",
            )

    row_by_acc_in = {
        placeholder.placeholder_id: placeholder
        for placeholder in placeholders
        if placeholder.role == "globalmax_acc_in"
    }
    acc_in_by_producer: dict[str, list[str]] = {}
    for placeholder in row_by_acc_in.values():
        for producer in placeholder.producer_placeholder_ids:
            acc_in_by_producer.setdefault(producer, []).append(placeholder.placeholder_id)

    enriched: list[OperandPlaceholder] = []
    final_current_values = set(current_value_by_pe.values())
    for placeholder in placeholders:
        consumers = list(producer_consumers.get(placeholder.placeholder_id, ()))
        consumer_placeholders = list(acc_in_by_producer.get(placeholder.placeholder_id, ()))
        if placeholder.placeholder_id in final_current_values:
            consumers.append(f"max_with_floor_tile:{placeholder.allocation_scope}")
        enriched.append(
            OperandPlaceholder(
                **{
                    **placeholder.__dict__,
                    "consumer_stream_action_ids": tuple(dict.fromkeys(consumers)),
                    "consumer_placeholder_ids": tuple(dict.fromkeys(consumer_placeholders)),
                }
            )
        )
    return tuple(enriched)


def _placeholder_for_row(
    *,
    row: RingUpdateBinaryLayoutRowCandidate,
    role: Literal["globalmax_acc_in", "globalmax_recv", "globalmax_acc_out"],
    scope: str,
    producer_placeholder_ids: tuple[str, ...],
    producer_stream_action_ids: tuple[str, ...],
    consumer_stream_action_ids: tuple[str, ...],
    consumer_placeholder_ids: tuple[str, ...],
) -> OperandPlaceholder:
    return OperandPlaceholder(
        schema_version="1",
        placeholder_id=_placeholder_id(row, role),
        operator="log10max",
        row_candidate_id=row.row_candidate_id,
        role=role,
        value_kind="replicated_vector",
        app_id=0,
        task_id=row.task_id,
        pe=row.dst_pe,
        allocation_scope=scope,
        source_ring_edge_id=row.source_ring_edge_id,
        source_stream_action_id=row.source_stream_action_id,
        source_fiber_op_id=row.source_fiber_op_id,
        template_expansion_id=row.template_expansion_id,
        recv_stream_action_id=row.recv_stream_action_id,
        paired_push_stream_action_id=row.paired_push_stream_action_id,
        producer_placeholder_ids=producer_placeholder_ids,
        producer_stream_action_ids=producer_stream_action_ids,
        consumer_stream_action_ids=consumer_stream_action_ids,
        consumer_placeholder_ids=consumer_placeholder_ids,
        alias_policy="forbidden",
    )


def _build_endpoint_placeholders(
    rows: tuple[RingUpdateBinaryLayoutRowCandidate, ...],
    *,
    participating_pes: tuple[str, ...],
    final_value_by_pe: dict[str, str],
) -> tuple[OperandPlaceholder, ...]:
    placeholders: list[OperandPlaceholder] = []
    first_update_by_dst = _first_update_placeholder_by_dst_pe(rows)
    first_push_by_src = _first_push_stream_action_by_src_pe(rows)
    for pe in participating_pes:
        task_id = _task_id_for_pe(rows, pe)
        local_id = _endpoint_placeholder_id(task_id, pe, "local_reduce_max_out")
        consumers: list[str] = []
        if pe in first_push_by_src:
            consumers.append(first_push_by_src[pe])
        if pe in first_update_by_dst:
            consumers.append(first_update_by_dst[pe])
        placeholders.append(
            OperandPlaceholder(
                schema_version="1",
                placeholder_id=local_id,
                operator="log10max",
                row_candidate_id=f"endpoint:local_reduce_max_out:{_pe_token(pe)}",
                role="local_reduce_max_out",
                value_kind="replicated_vector",
                app_id=0,
                task_id=task_id,
                pe=pe,
                allocation_scope=_allocation_scope(task_id, pe),
                source_ring_edge_id="endpoint:local_reduce_max_out",
                source_stream_action_id=f"log10max_ring:local_reduce_max:{_pe_token(pe)}",
                source_fiber_op_id=f"fiber:log10max:ring:{_pe_token(pe)}:local_reduce_max_tile",
                template_expansion_id=(
                    "template_expansion:dfu3500_log10max_local_reduce_max_tile:"
                    f"{_pe_token(pe)}"
                ),
                recv_stream_action_id="",
                paired_push_stream_action_id="",
                producer_placeholder_ids=(),
                producer_stream_action_ids=(
                    f"log10max_ring:local_reduce_max:{_pe_token(pe)}",
                ),
                consumer_stream_action_ids=tuple(dict.fromkeys(consumers)),
                consumer_placeholder_ids=(),
                alias_policy="forbidden",
            )
        )
    for pe in participating_pes:
        task_id = _task_id_for_pe(rows, pe)
        producer = final_value_by_pe.get(pe)
        placeholders.append(
            OperandPlaceholder(
                schema_version="1",
                placeholder_id=_endpoint_placeholder_id(
                    task_id,
                    pe,
                    "max_with_floor_globalmax_src",
                ),
                operator="log10max",
                row_candidate_id=f"endpoint:max_with_floor_globalmax_src:{_pe_token(pe)}",
                role="max_with_floor_globalmax_src",
                value_kind="replicated_vector",
                app_id=0,
                task_id=task_id,
                pe=pe,
                allocation_scope=_allocation_scope(task_id, pe),
                source_ring_edge_id="endpoint:max_with_floor_globalmax_src",
                source_stream_action_id=f"log10max_ring:max_with_floor:{_pe_token(pe)}",
                source_fiber_op_id=f"fiber:log10max:ring:{_pe_token(pe)}:max_with_floor_tile",
                template_expansion_id=(
                    "template_expansion:dfu3500_log10max_max_with_floor_tile:"
                    f"{_pe_token(pe)}"
                ),
                recv_stream_action_id="",
                paired_push_stream_action_id="",
                producer_placeholder_ids=(producer,) if producer else (),
                producer_stream_action_ids=(),
                consumer_stream_action_ids=(
                    f"log10max_ring:max_with_floor:{_pe_token(pe)}",
                ),
                consumer_placeholder_ids=(),
                alias_policy="forbidden",
            )
        )
    return tuple(placeholders)


def _allocate_placeholders(
    placeholders: tuple[OperandPlaceholder, ...],
) -> tuple[OperandAllocation, ...]:
    layout = Dfu3500OperandIndexLayout(LOG10MAX_RING_UPDATE_LAYOUT_PROFILE)
    next_reg_by_scope: dict[str, int] = {}
    allocation_by_placeholder: dict[str, OperandAllocation] = {}
    allocations: list[OperandAllocation] = []

    for placeholder in placeholders:
        blockers: tuple[str, ...] = ()
        allocation_kind: Literal[
            "new_monotonic_no_reuse", "value_identity_reuse", "blocked"
        ]
        logical_reg_idx = -1
        producer_allocation_ids: tuple[str, ...] = ()
        if len(placeholder.producer_placeholder_ids) > 1:
            blockers = ("log10max_ring_update_ambiguous_producer_placeholder",)
            operand_idx = -1
            alias_group = None
            allocation_kind = "blocked"
        elif len(placeholder.producer_placeholder_ids) == 1:
            producer_id = placeholder.producer_placeholder_ids[0]
            producer_allocation = allocation_by_placeholder.get(producer_id)
            if producer_allocation is None:
                blockers = ("log10max_ring_update_producer_allocation_missing",)
                operand_idx = -1
                alias_group = None
                allocation_kind = "blocked"
            else:
                operand_idx = producer_allocation.operand_idx
                logical_reg_idx = producer_allocation.logical_reg_idx
                alias_group = f"value_identity:{producer_id}"
                allocation_kind = "value_identity_reuse"
                producer_allocation_ids = (producer_allocation.allocation_id,)
        else:
            reg_idx = next_reg_by_scope.get(placeholder.allocation_scope, 0)
            if reg_idx >= layout.capacity:
                blockers = ("log10max_ring_update_operand_capacity_exceeded",)
                operand_idx = -1
                alias_group = None
                allocation_kind = "blocked"
            else:
                operand_idx = layout.operand_idx_from_logical_reg(reg_idx)
                logical_reg_idx = reg_idx
                next_reg_by_scope[placeholder.allocation_scope] = reg_idx + 1
                alias_group = None
                allocation_kind = "new_monotonic_no_reuse"
        if operand_idx >= 0:
            operand_ram, operand_line = layout.split_operand_idx(operand_idx)
        else:
            operand_ram, operand_line = -1, -1
        allocation = OperandAllocation(
            schema_version="1",
            allocation_id=f"alloc:{placeholder.placeholder_id}",
            placeholder_id=placeholder.placeholder_id,
            allocator=LOG10MAX_RING_UPDATE_ALLOCATOR,
            allocation_kind=allocation_kind,
            app_id=placeholder.app_id,
            task_id=placeholder.task_id,
            pe=placeholder.pe,
            layout_profile_id=layout.profile_id,
            logical_reg_idx=logical_reg_idx,
            operand_idx=operand_idx,
            operand_ram=operand_ram,
            operand_line=operand_line,
            allocation_scope=placeholder.allocation_scope,
            alias_group=alias_group,
            producer_allocation_ids=producer_allocation_ids,
            allocation_status="blocked" if blockers else "allocated",
            evidence_refs=(
                "simict3500final/gpdpu/users/risc_nn_riscv/testcase/"
                "common_oper/inst_blk_map.cpp:Task_Resource::get_reg_idx",
                "compiler/gpdpu_compiler/core/dfu3500/"
                "task_resource_replay.py:layout_operand_idx",
            ),
            blockers=blockers,
        )
        allocation_by_placeholder[placeholder.placeholder_id] = allocation
        allocations.append(allocation)
    return tuple(allocations)


def _build_patches(
    rows: tuple[RingUpdateBinaryLayoutRowCandidate, ...],
    allocations: tuple[OperandAllocation, ...],
) -> tuple[InstOperandPatch, ...]:
    allocation_by_placeholder = {
        allocation.placeholder_id: allocation for allocation in allocations
    }
    patches: list[InstOperandPatch] = []
    for row in rows:
        src_placeholders = (
            _placeholder_id(row, "globalmax_acc_in"),
            _placeholder_id(row, "globalmax_recv"),
        )
        dst_placeholders = (_placeholder_id(row, "globalmax_acc_out"),)
        required = src_placeholders + dst_placeholders
        selected_allocations = tuple(
            allocation_by_placeholder.get(placeholder_id)
            for placeholder_id in required
        )
        missing = tuple(
            placeholder_id
            for placeholder_id, allocation in zip(required, selected_allocations)
            if allocation is None or allocation.allocation_status != "allocated"
        )
        alias_ok = True
        if not missing:
            assert selected_allocations[0] is not None
            assert selected_allocations[1] is not None
            assert selected_allocations[2] is not None
            alias_ok = (
                selected_allocations[2].operand_idx
                not in {
                    selected_allocations[0].operand_idx,
                    selected_allocations[1].operand_idx,
                }
            )
        blockers: list[str] = []
        if missing:
            blockers.append("log10max_ring_update_inst_operand_patch_missing")
        if not alias_ok:
            blockers.append("log10max_ring_update_operand_alias_without_proof")
        patch_status: Literal["patched", "blocked"] = (
            "patched" if not blockers else "blocked"
        )
        if patch_status == "patched":
            src_operands = (
                selected_allocations[0].operand_idx,  # type: ignore[union-attr]
                selected_allocations[1].operand_idx,  # type: ignore[union-attr]
                0,
            )
            dst_operands = (
                selected_allocations[2].operand_idx,  # type: ignore[union-attr]
                0,
                0,
            )
            raw_bytes = _pack_and_check_patch(row, src_operands, dst_operands)
            decode_status: Literal["not_run", "candidate_decode_roundtrip"] = (
                "candidate_decode_roundtrip"
            )
            raw_sha = hashlib.sha256(raw_bytes).hexdigest()
        else:
            src_operands = (0, 0, 0)
            dst_operands = (0, 0, 0)
            decode_status = "not_run"
            raw_bytes = b""
            raw_sha = ""
        route_blockers = (
            "log10max_ring_update_route_recv_operand_patch_missing",
            "log10max_ring_update_route_push_operand_patch_missing",
        )
        all_blockers = tuple(
            dict.fromkeys(
                blockers
                + [
                    LOG10MAX_RING_UPDATE_PATCH_BLOCKER,
                    LOG10MAX_RING_UPDATE_COMPONENT_BLOCKER,
                ]
            )
        )
        patches.append(
            InstOperandPatch(
                schema_version="1",
                patch_id=f"patch:{row.row_candidate_id}",
                row_candidate_id=row.row_candidate_id,
                opcode="FMAX",
                source_ring_edge_id=row.source_ring_edge_id,
                source_stream_action_id=row.source_stream_action_id,
                source_fiber_op_id=row.source_fiber_op_id,
                template_expansion_id=row.template_expansion_id,
                allocation_ids=tuple(
                    allocation.allocation_id
                    for allocation in selected_allocations
                    if allocation is not None
                ),
                src_placeholders=src_placeholders,
                dst_placeholders=dst_placeholders,
                src_operands_idx=src_operands,
                dst_operands_idx=dst_operands,
                operand_field_usage=RING_UPDATE_FMAX_OPERAND_FIELD_USAGE,
                raw_inst_t_byte_count=len(raw_bytes),
                raw_inst_t_sha256=raw_sha,
                patch_status=patch_status,
                decode_roundtrip_status=decode_status,
                provenance_roundtrip_status="candidate_report_roundtrip",
                route_continuity_status="blocked_missing_route_row_patch",
                route_continuity_blockers=route_blockers,
                blocker_ids=all_blockers,
            )
        )
    return tuple(patches)


def _build_route_patches(
    rows: tuple[RingUpdateBinaryLayoutRowCandidate, ...],
    allocations: tuple[OperandAllocation, ...],
) -> tuple[RouteOperandPatch, ...]:
    allocation_by_placeholder = {
        allocation.placeholder_id: allocation for allocation in allocations
    }
    current_value_by_pe: dict[tuple[int, str], str] = {}
    patches: list[RouteOperandPatch] = []
    for row in rows:
        source_key = (row.task_id, row.src_pe)
        push_source = current_value_by_pe.get(source_key)
        if push_source is None:
            push_source = _endpoint_placeholder_id(
                row.task_id,
                row.src_pe,
                "local_reduce_max_out",
            )
        patches.append(
            _route_push_patch_for_row(
                row,
                push_source=push_source,
                allocation_by_placeholder=allocation_by_placeholder,
            )
        )
        recv_placeholder = _placeholder_id(row, "globalmax_recv")
        patches.append(
            _route_recv_patch_for_row(
                row,
                recv_placeholder=recv_placeholder,
                allocation_by_placeholder=allocation_by_placeholder,
            )
        )
        current_value_by_pe[(row.task_id, row.dst_pe)] = _placeholder_id(
            row, "globalmax_acc_out"
        )
        current_value_by_pe.setdefault(source_key, push_source)
    return tuple(patches)


def _build_max_with_floor_globalmax_patches(
    placeholders: tuple[OperandPlaceholder, ...],
    allocations: tuple[OperandAllocation, ...],
) -> tuple[MaxWithFloorGlobalMaxOperandPatch, ...]:
    allocation_by_placeholder = {
        allocation.placeholder_id: allocation for allocation in allocations
    }
    final_acc_out_by_endpoint: dict[str, OperandPlaceholder] = {}
    for placeholder in placeholders:
        if placeholder.role != "globalmax_acc_out":
            continue
        if not any(
            str(consumer).startswith("max_with_floor_tile:")
            for consumer in placeholder.consumer_stream_action_ids
        ):
            continue
        endpoint_id = _endpoint_placeholder_id(
            placeholder.task_id,
            placeholder.pe,
            "max_with_floor_globalmax_src",
        )
        final_acc_out_by_endpoint[endpoint_id] = placeholder
    patches: list[MaxWithFloorGlobalMaxOperandPatch] = []
    for placeholder in placeholders:
        if placeholder.role != "max_with_floor_globalmax_src":
            continue
        allocation = allocation_by_placeholder.get(placeholder.placeholder_id)
        producer = final_acc_out_by_endpoint.get(placeholder.placeholder_id)
        producer_allocation = (
            allocation_by_placeholder.get(producer.placeholder_id)
            if producer is not None
            else None
        )
        producer_placeholder_id = (
            placeholder.producer_placeholder_ids[0]
            if len(placeholder.producer_placeholder_ids) == 1
            else ""
        )
        blockers: list[str] = [
            LOG10MAX_MAX_WITH_FLOOR_LOG_SPEC_DEFERRED_BLOCKER,
            LOG10MAX_MAX_WITH_FLOOR_CONSTANTS_DEFERRED_BLOCKER,
            LOG10MAX_MAX_WITH_FLOOR_OUTPUT_DEFERRED_BLOCKER,
            LOG10MAX_MAX_WITH_FLOOR_ROW_BYTES_BLOCKER,
            LOG10MAX_COMPONENT_INTEGRATION_BLOCKER,
        ]
        producer_matches = (
            producer is not None
            and producer_allocation is not None
            and producer_placeholder_id == producer.placeholder_id
            and allocation is not None
            and allocation.producer_allocation_ids == (producer_allocation.allocation_id,)
            and allocation.operand_idx == producer_allocation.operand_idx
            and allocation.allocation_scope == producer_allocation.allocation_scope
        )
        if (
            allocation is None
            or allocation.allocation_status != "allocated"
            or allocation.allocation_kind != "value_identity_reuse"
            or not producer_matches
        ):
            blockers.insert(
                0, "log10max_max_with_floor_globalmax_operand_allocation_missing"
            )
            allocation_id = ""
            producer_allocation_id = (
                producer_allocation.allocation_id
                if producer_allocation is not None
                else ""
            )
            operand_idx = -1
            operand_ram = -1
            operand_line = -1
            status: Literal["patched", "blocked"] = "blocked"
            value_identity_reuse = False
        else:
            allocation_id = allocation.allocation_id
            producer_allocation_id = producer_allocation.allocation_id
            operand_idx = allocation.operand_idx
            operand_ram = allocation.operand_ram
            operand_line = allocation.operand_line
            status = "patched"
            value_identity_reuse = True
        patches.append(
            MaxWithFloorGlobalMaxOperandPatch(
                schema_version="1",
                patch_id=f"patch:max_with_floor_globalmax:{placeholder.allocation_scope}",
                consumer_fiber_op="max_with_floor_tile",
                consumer_operand_role="globalmax_src",
                app_id=placeholder.app_id,
                task_id=placeholder.task_id,
                pe=placeholder.pe,
                allocation_scope=placeholder.allocation_scope,
                source_ring_edge_id=placeholder.source_ring_edge_id,
                source_stream_action_id=placeholder.source_stream_action_id,
                source_fiber_op_id=placeholder.source_fiber_op_id,
                producer_placeholder_id=producer_placeholder_id,
                consumer_placeholder_id=placeholder.placeholder_id,
                allocation_id=allocation_id,
                producer_allocation_id=producer_allocation_id,
                operand_idx=operand_idx,
                operand_ram=operand_ram,
                operand_line=operand_line,
                value_identity_reuse=value_identity_reuse,
                globalmax_source_patch_status=status,
                log_spec_source_status="deferred_named",
                constants_status="deferred_named",
                output_operand_status="deferred_named",
                final_row_bytes_claim=False,
                component_integration_claim=False,
                blocker_ids=tuple(dict.fromkeys(blockers)),
            )
        )
    return tuple(patches)


def _route_push_patch_for_row(
    row: RingUpdateBinaryLayoutRowCandidate,
    *,
    push_source: str,
    allocation_by_placeholder: dict[str, OperandAllocation],
) -> RouteOperandPatch:
    expected_scope = _allocation_scope(row.task_id, row.src_pe)
    blockers: list[str] = [
        LOG10MAX_ROUTE_ROW_BYTES_BLOCKER,
        LOG10MAX_RING_UPDATE_COMPONENT_BLOCKER,
    ]
    allocation = allocation_by_placeholder.get(push_source)
    if allocation is None or allocation.allocation_status != "allocated":
        blockers.insert(0, LOG10MAX_RING_ROUTE_LOCAL_REDUCE_BLOCKER)
        allocation_ids: tuple[str, ...] = ()
        src_operands = (0, 0, 0)
        allocation_scope = ""
        scope_status: Literal["sender_task_pe", "receiver_task_pe", "blocked"] = (
            "blocked"
        )
        patch_status: Literal["patched", "blocked"] = "blocked"
    else:
        allocation_ids = (allocation.allocation_id,)
        src_operands = (allocation.operand_idx, 0, 0)
        allocation_scope = allocation.allocation_scope
        if allocation_scope != expected_scope:
            blockers.insert(0, "log10max_ring_route_push_sender_scope_mismatch")
            scope_status = "blocked"
            patch_status = "blocked"
        else:
            scope_status = "sender_task_pe"
            patch_status = "patched"
    return RouteOperandPatch(
        schema_version="1",
        patch_id=f"patch:route_push:{row.source_ring_edge_id}",
        direction="push",
        source_ring_edge_id=row.source_ring_edge_id,
        source_stream_action_id=row.paired_push_stream_action_id,
        source_fiber_op_id=f"fiber:log10max_ring:edge:{row.source_ring_edge_id}:route_push",
        paired_stream_action_id=row.recv_stream_action_id,
        task_id=row.task_id,
        src_pe=row.src_pe,
        dst_pe=row.dst_pe,
        expected_allocation_scope=expected_scope,
        allocation_scope=allocation_scope,
        scope_status=scope_status,
        src_placeholders=(push_source,) if push_source.startswith("opnd:") else (),
        dst_placeholders=(),
        allocation_ids=allocation_ids,
        src_operands_idx=src_operands,
        dst_operands_idx=(0, 0, 0),
        operand_field_usage=(
            ("src0", "used" if allocation_ids else "blocked_missing_source"),
            ("src1", "unused_zero_fill"),
            ("src2", "unused_zero_fill"),
            ("dst0", "unused_zero_fill"),
            ("dst1", "unused_zero_fill"),
            ("dst2", "unused_zero_fill"),
        ),
        patch_status=patch_status,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def _route_recv_patch_for_row(
    row: RingUpdateBinaryLayoutRowCandidate,
    *,
    recv_placeholder: str,
    allocation_by_placeholder: dict[str, OperandAllocation],
) -> RouteOperandPatch:
    expected_scope = _allocation_scope(row.task_id, row.dst_pe)
    blockers: list[str] = [
        LOG10MAX_ROUTE_ROW_BYTES_BLOCKER,
        LOG10MAX_RING_UPDATE_COMPONENT_BLOCKER,
    ]
    allocation = allocation_by_placeholder.get(recv_placeholder)
    if allocation is None or allocation.allocation_status != "allocated":
        blockers.insert(0, "log10max_ring_route_recv_operand_allocation_missing")
        allocation_ids: tuple[str, ...] = ()
        dst_operands = (0, 0, 0)
        allocation_scope = ""
        scope_status: Literal["sender_task_pe", "receiver_task_pe", "blocked"] = (
            "blocked"
        )
        patch_status: Literal["patched", "blocked"] = "blocked"
    else:
        allocation_ids = (allocation.allocation_id,)
        dst_operands = (allocation.operand_idx, 0, 0)
        allocation_scope = allocation.allocation_scope
        if allocation_scope != expected_scope:
            blockers.insert(0, "log10max_ring_route_recv_receiver_scope_mismatch")
            scope_status = "blocked"
            patch_status = "blocked"
        else:
            scope_status = "receiver_task_pe"
            patch_status = "patched"
    return RouteOperandPatch(
        schema_version="1",
        patch_id=f"patch:route_recv:{row.source_ring_edge_id}",
        direction="recv",
        source_ring_edge_id=row.source_ring_edge_id,
        source_stream_action_id=row.recv_stream_action_id,
        source_fiber_op_id=f"fiber:log10max_ring:edge:{row.source_ring_edge_id}:route_recv",
        paired_stream_action_id=row.paired_push_stream_action_id,
        task_id=row.task_id,
        src_pe=row.src_pe,
        dst_pe=row.dst_pe,
        expected_allocation_scope=expected_scope,
        allocation_scope=allocation_scope,
        scope_status=scope_status,
        src_placeholders=(),
        dst_placeholders=(recv_placeholder,),
        allocation_ids=allocation_ids,
        src_operands_idx=(0, 0, 0),
        dst_operands_idx=dst_operands,
        operand_field_usage=(
            ("src0", "unused_zero_fill"),
            ("src1", "unused_zero_fill"),
            ("src2", "unused_zero_fill"),
            ("dst0", "used" if allocation_ids else "blocked_missing_destination"),
            ("dst1", "unused_zero_fill"),
            ("dst2", "unused_zero_fill"),
        ),
        patch_status=patch_status,
        blockers=tuple(dict.fromkeys(blockers)),
    )


def _pack_and_check_patch(
    row: RingUpdateBinaryLayoutRowCandidate,
    src_operands: tuple[int, int, int],
    dst_operands: tuple[int, int, int],
) -> bytes:
    if row.opcode != "FMAX":
        raise ValueError(f"Phase-3 patch V1 only supports FMAX: {row.opcode}")
    inst = LegacyInst(
        op_name="FMAX",
        opcode=RING_UPDATE_FMAX_OPCODE,
        unit_inst_type=RING_UPDATE_FMAX_UNIT_INST_TYPE,
        latency=RING_UPDATE_FMAX_LATENCY,
        imms=(0, 0, 0),
        src_operands_idx=src_operands,
        dst_operands_idx=dst_operands,
        forwarding_bits=RING_UPDATE_FORWARDING_BITS,
        bypass_bits=RING_UPDATE_BYPASS_BITS,
        iter_exe_cond=RING_UPDATE_FMAX_ITER_EXE_COND,
        block_idx=row.row_index,
        end_inst=0,
    )
    raw_bytes = pack_legacy_inst(inst)
    decoded = decode_legacy_inst_skeleton(raw_bytes)
    expected = {
        "opcode": RING_UPDATE_FMAX_OPCODE,
        "unit_inst_type": RING_UPDATE_FMAX_UNIT_INST_TYPE,
        "latency": RING_UPDATE_FMAX_LATENCY,
        "imms": (0, 0, 0),
        "src_operands_idx": src_operands,
        "dst_operands_idx": dst_operands,
        "forwarding_bits": RING_UPDATE_FORWARDING_BITS,
        "bypass_bits": RING_UPDATE_BYPASS_BITS,
        "iter_exe_cond": RING_UPDATE_FMAX_ITER_EXE_COND,
        "block_idx": row.row_index,
        "end_inst": 0,
    }
    for key, value in expected.items():
        if decoded[key] != value:
            raise ValueError(
                "ring update InstOperandPatch decode mismatch: "
                f"row={row.row_candidate_id}, key={key}, "
                f"expected={value!r}, got={decoded[key]!r}"
            )
    return raw_bytes


def _placeholder_allocation_blocker(role: str) -> str:
    if role in ENDPOINT_PLACEHOLDER_ROLES:
        return LOG10MAX_ENDPOINT_ALLOCATION_BLOCKER
    return "log10max_ring_update_operand_allocation_missing"


def _placeholder_role_from_id(placeholder_id: str) -> str:
    return placeholder_id.rsplit(":", 1)[-1]


def _placeholder_id(
    row: RingUpdateBinaryLayoutRowCandidate,
    role: Literal["globalmax_acc_in", "globalmax_recv", "globalmax_acc_out"],
) -> str:
    edge_number = row.source_ring_edge_id.split(":", 2)[1]
    pe = row.dst_pe.removeprefix("PE(").removesuffix(")").replace(",", "_")
    return f"opnd:log10max:t{row.task_id}:pe{pe}:ring_edge_{edge_number}:{role}"


def _endpoint_placeholder_id(
    task_id: int,
    pe: str,
    role: Literal["local_reduce_max_out", "max_with_floor_globalmax_src"],
) -> str:
    return f"opnd:log10max:t{task_id}:{_pe_token_from_label(pe)}:{role}"


def _participating_pes(
    rows: tuple[RingUpdateBinaryLayoutRowCandidate, ...],
) -> tuple[str, ...]:
    labels = {row.src_pe for row in rows} | {row.dst_pe for row in rows}
    return tuple(sorted(labels, key=_pe_sort_key))


def _task_id_for_pe(
    rows: tuple[RingUpdateBinaryLayoutRowCandidate, ...],
    pe: str,
) -> int:
    for row in rows:
        if row.src_pe == pe or row.dst_pe == pe:
            return row.task_id
    raise ValueError(f"PE does not participate in log10max ring rows: {pe}")


def _first_push_stream_action_by_src_pe(
    rows: tuple[RingUpdateBinaryLayoutRowCandidate, ...],
) -> dict[str, str]:
    current_value_by_pe: dict[tuple[int, str], str] = {}
    first_push: dict[str, str] = {}
    for row in rows:
        source_key = (row.task_id, row.src_pe)
        if source_key not in current_value_by_pe:
            first_push.setdefault(row.src_pe, row.paired_push_stream_action_id)
            current_value_by_pe[source_key] = _endpoint_placeholder_id(
                row.task_id,
                row.src_pe,
                "local_reduce_max_out",
            )
        current_value_by_pe[(row.task_id, row.dst_pe)] = _placeholder_id(
            row, "globalmax_acc_out"
        )
    return first_push


def _first_update_placeholder_by_dst_pe(
    rows: tuple[RingUpdateBinaryLayoutRowCandidate, ...],
) -> dict[str, str]:
    current_value_by_pe: dict[tuple[int, str], str] = {}
    first_update: dict[str, str] = {}
    for row in rows:
        dst_key = (row.task_id, row.dst_pe)
        if dst_key not in current_value_by_pe:
            first_update.setdefault(row.dst_pe, _placeholder_id(row, "globalmax_acc_in"))
            current_value_by_pe[dst_key] = _endpoint_placeholder_id(
                row.task_id,
                row.dst_pe,
                "local_reduce_max_out",
            )
        source_key = (row.task_id, row.src_pe)
        current_value_by_pe.setdefault(
            source_key,
            _endpoint_placeholder_id(row.task_id, row.src_pe, "local_reduce_max_out"),
        )
        current_value_by_pe[dst_key] = _placeholder_id(row, "globalmax_acc_out")
    return first_update


def _final_globalmax_placeholder_by_pe(
    rows: tuple[RingUpdateBinaryLayoutRowCandidate, ...],
) -> dict[str, str]:
    current_value_by_pe: dict[tuple[int, str], str] = {}
    task_by_pe: dict[str, int] = {}
    for row in rows:
        source_key = (row.task_id, row.src_pe)
        current_value_by_pe.setdefault(
            source_key,
            _endpoint_placeholder_id(row.task_id, row.src_pe, "local_reduce_max_out"),
        )
        current_value_by_pe[(row.task_id, row.dst_pe)] = _placeholder_id(
            row, "globalmax_acc_out"
        )
        task_by_pe[row.src_pe] = row.task_id
        task_by_pe[row.dst_pe] = row.task_id
    return {
        pe: current_value_by_pe.get(
            (task_id, pe),
            _endpoint_placeholder_id(task_id, pe, "local_reduce_max_out"),
        )
        for pe, task_id in task_by_pe.items()
    }


def _allocation_scope(task_id: int, pe: str) -> str:
    return f"app0:task{task_id}:{_pe_token_from_label(pe)}"


def _pe_token_from_label(pe: str) -> str:
    pe_key = pe.removeprefix("PE(").removesuffix(")").replace(",", "_")
    return f"pe{pe_key}"


def _pe_token(pe: str) -> str:
    return _pe_token_from_label(pe)


def _pe_sort_key(pe: str) -> tuple[int, int, str]:
    body = pe.removeprefix("PE(").removesuffix(")")
    parts = body.split(",")
    if len(parts) != 2:
        return (0, 0, pe)
    try:
        return (int(parts[0]), int(parts[1]), pe)
    except ValueError:
        return (0, 0, pe)


def _phase_from_edge_id(edge_id: str) -> str:
    parts = edge_id.split(":")
    if len(parts) < 3:
        return "unknown"
    return parts[2]


__all__ = [
    "Dfu3500OperandIndexLayout",
    "OperandPlaceholder",
    "RingUpdateOperandPlaceholderReport",
    "Log10MaxEndpointOperandPlaceholderReport",
    "OperandAllocation",
    "RingUpdateOperandAllocationReport",
    "Log10MaxUnifiedOperandAllocationReport",
    "InstOperandPatch",
    "RingUpdateInstOperandPatchReport",
    "RouteOperandPatch",
    "RingRouteOperandPatchReport",
    "MaxWithFloorGlobalMaxOperandPatch",
    "MaxWithFloorGlobalMaxOperandPatchReport",
    "PLACEHOLDER_ROLES",
    "EXPECTED_PHASE_COUNTS",
    "EXPECTED_PHASE_PLACEHOLDER_COUNTS",
    "LOG10MAX_RING_UPDATE_ALLOCATOR",
    "LOG10MAX_RING_UPDATE_LAYOUT_PROFILE",
    "DFU3500_BLINE_LINEAR_ALLOCATOR_ID",
    "DFU3500_OPERAND_LAYOUT_PROFILE_ID",
    "LOG10MAX_RING_UPDATE_PATCH_BLOCKER",
    "LOG10MAX_RING_UPDATE_COMPONENT_BLOCKER",
    "LOG10MAX_RING_ROUTE_LOCAL_REDUCE_BLOCKER",
    "LOG10MAX_ROUTE_ROW_BYTES_BLOCKER",
    "LOG10MAX_ENDPOINT_PLACEHOLDER_BLOCKER",
    "LOG10MAX_ENDPOINT_ALLOCATION_BLOCKER",
    "LOG10MAX_ENDPOINT_PATCH_BLOCKER",
    "LOG10MAX_MAX_WITH_FLOOR_GLOBALMAX_BLOCKER",
    "LOG10MAX_MAX_WITH_FLOOR_ROW_BYTES_BLOCKER",
    "LOG10MAX_COMPONENT_INTEGRATION_BLOCKER",
    "LOG10MAX_MAX_WITH_FLOOR_LOG_SPEC_DEFERRED_BLOCKER",
    "LOG10MAX_MAX_WITH_FLOOR_CONSTANTS_DEFERRED_BLOCKER",
    "LOG10MAX_MAX_WITH_FLOOR_OUTPUT_DEFERRED_BLOCKER",
    "build_log10max_ring_update_operand_placeholder_report",
    "build_log10max_endpoint_operand_placeholder_report",
    "build_log10max_ring_update_operand_allocation_report",
    "build_log10max_unified_operand_allocation_report",
    "build_log10max_ring_update_inst_operand_patch_report",
    "build_log10max_ring_route_operand_patch_report",
    "build_log10max_max_with_floor_operand_patch_report",
    "summarize_log10max_ring_update_operand_placeholder_report",
    "summarize_log10max_endpoint_operand_placeholder_report",
    "summarize_log10max_ring_update_operand_allocation_report",
    "summarize_log10max_unified_operand_allocation_report",
    "summarize_log10max_ring_update_inst_operand_patch_report",
    "summarize_log10max_ring_route_operand_patch_report",
    "summarize_log10max_max_with_floor_operand_patch_report",
]
