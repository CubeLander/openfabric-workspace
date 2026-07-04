"""DFU3500 legacy ``Task_Resource`` modelling helpers.

Vendor ``testcase/common_oper/inst_blk_map.cpp`` gives operand allocation an
uncomfortably important role: it is not just bookkeeping; it mutates final
``inst_t`` operand fields before CBUF serialization.  This module is the
intended home for that behaviour so ``program_bin.py`` remains a serializer /
row planner instead of growing a second hidden backend.

The production pass is intentionally conservative: replay is default-off and
only runs when explicitly requested through
``OPENFABRIC_ENABLE_DFU3500_TASK_RESOURCE_REPLAY``.  The model below keeps the
source-derived allocation rules explicit:

* regular ``Task_Resource::get_reg_idx`` allocates first-use tags with
  ``layout_operand_idx(counter + reg_start_idx)`` in non-REDUCE mode;
* tensor pseudo instructions allocate a group-local base and expand lanes as
  ``base + lane * OPERANDS_PER_OPERAND_RAM``;
* COPY/COPYT destination patching must use the receiver/child task resource,
  matching vendor ``fill_copy_inst``.

Do not move template selection or byte packing here.  This layer should only
model resource state and, once enabled, patch already-template-bound
instructions before ``ProgramBinRows`` are serialized.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field, replace
from typing import Any, Iterable

from gpdpu_compiler.core.program_legacy_inst import (
    LegacyInst,
    OPERANDS_PER_OPERAND_RAM,
    OPERANDS_RAM_NUM,
    OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE,
)
from gpdpu_compiler.core.program_vendor_abi import ProgramVendorABI, VendorExeBlockRow


TASK_RESOURCE_REPLAY_ENV = "OPENFABRIC_ENABLE_DFU3500_TASK_RESOURCE_REPLAY"
STAGE_ORDER = {"LD": 0, "CAL": 1, "FLOW": 2, "ST": 3}
TASK_RESOURCE_REPLAY_ROW_AUTHORITY_FIELD = "task_resource_replay_row_authority"


@dataclass(frozen=True)
class TaskResourceReplayAuthorityRoleStatus:
    """S2-consumable field authority grouped by B-line role/opcode."""

    role: str
    opcode: str
    row_count: int
    blocked_on_task_resource_row_count: int
    authority_status: str
    closed_fields: tuple[str, ...]
    non_replay_closed_fields: tuple[str, ...]
    open_fields: tuple[str, ...]
    open_blockers: tuple[str, ...]

    def to_plan(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "opcode": self.opcode,
            "row_count": self.row_count,
            "blocked_on_task_resource_row_count": (
                self.blocked_on_task_resource_row_count
            ),
            "authority_status": self.authority_status,
            "closed_fields": list(self.closed_fields),
            "non_replay_closed_fields": list(self.non_replay_closed_fields),
            "open_fields": list(self.open_fields),
            "open_blockers": list(self.open_blockers),
        }


@dataclass(frozen=True)
class TaskResourceReplayAuthorityReport:
    """Report-only TaskResource replay authority surface for S2 rows.

    The report does not enable replay and does not patch rows.  It only names
    fields whose authority is already represented by the opt-in replay model,
    and keeps uncertain fields open.
    """

    authority_status: str
    role_statuses: tuple[TaskResourceReplayAuthorityRoleStatus, ...]
    covered_role_counts: tuple[tuple[str, int], ...]
    open_blockers: tuple[str, ...]
    vendor_abi_field_status: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "artifact": "task_resource_replay_row_authority_report",
            "authority_status": self.authority_status,
            "covered_role_counts": dict(self.covered_role_counts),
            "open_blockers": list(self.open_blockers),
            "role_statuses": {
                f"{status.role}|{status.opcode}": status.to_plan()
                for status in self.role_statuses
            },
            "vendor_abi_field_status": self.vendor_abi_field_status,
            "layering_policy": (
                "report_only;"
                "does_not_enable_task_resource_replay;"
                "does_not_change_program_bin_defaults;"
                "fail_closed_for_unproven_row_fields"
            ),
        }


def layout_operand_idx(reg_idx: int) -> int:
    """Mirror vendor ``layout_operand_idx`` for regular operands."""

    reg_idx = int(reg_idx)
    return (
        (reg_idx % OPERANDS_RAM_NUM) * OPERANDS_PER_OPERAND_RAM
        + reg_idx // OPERANDS_RAM_NUM
    )


@dataclass
class Dfu3500TaskResourceState:
    """Small source-derived model of vendor ``Task_Resource``.

    The model is deliberately narrow: it captures first-use tag allocation and
    receiver-side COPY destination lookup, which are the behaviours implicated
    by the remaining CBUF operand-index diffs.  More complex arch-13 REDUCE
    allocator details can be layered in without changing call sites.
    """

    reg_start_idx: int = 0
    reg_idx_counter: int = 0
    allocation_mode: str = "layout_counter"
    tag_to_operand_idx: dict[str, int] = field(default_factory=dict)
    tensor_group_next_idx: dict[int, int] = field(default_factory=dict)
    operand_ram_free: dict[int, list[int]] = field(default_factory=dict)
    tensor_group_free: dict[int, list[int]] = field(default_factory=dict)
    stage_free_ram_indices: list[int] = field(default_factory=list)
    stage_recent_used_ram_indices: list[list[int]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.operand_ram_free:
            self.operand_ram_free = {
                ram_idx: [
                    ram_idx * OPERANDS_PER_OPERAND_RAM + line_idx
                    for line_idx in range(OPERANDS_PER_OPERAND_RAM)
                ]
                for ram_idx in range(OPERANDS_RAM_NUM)
            }
        if not self.tensor_group_free:
            self.tensor_group_free = {
                group_idx: [
                    group_idx
                    * OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE
                    * OPERANDS_PER_OPERAND_RAM
                    + line_idx
                    for line_idx in range(OPERANDS_PER_OPERAND_RAM)
                ]
                for group_idx in range(
                    OPERANDS_RAM_NUM // OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE
                )
            }

    def begin_stage(self) -> None:
        """Mirror vendor ``fill_reg_idx`` stage-local free-RAM window."""

        self.stage_free_ram_indices = [
            ram_idx
            for ram_idx in range(OPERANDS_RAM_NUM)
            if self.operand_ram_free.get(ram_idx)
        ]
        self.stage_recent_used_ram_indices = []

    def finish_instruction(self, operand_indices: tuple[int, ...]) -> None:
        """Update the vendor 3-instruction RAM reuse window."""

        if self.allocation_mode != "order_pool":
            return
        used = sorted(
            {
                int(operand_idx) // OPERANDS_PER_OPERAND_RAM
                for operand_idx in operand_indices
                if int(operand_idx) > 0
            }
        )
        self.stage_recent_used_ram_indices.append(used)
        if len(self.stage_recent_used_ram_indices) <= 3:
            return
        expired = self.stage_recent_used_ram_indices.pop(0)
        still_used = {
            ram_idx
            for recent in self.stage_recent_used_ram_indices
            for ram_idx in recent
        }
        for ram_idx in expired:
            if (
                ram_idx not in still_used
                and ram_idx not in self.stage_free_ram_indices
                and self.operand_ram_free.get(ram_idx)
            ):
                self.stage_free_ram_indices.append(ram_idx)

    def get_reg_idx(self, tag: str) -> int:
        """Return existing tag operand or allocate a regular operand."""

        tag = tag.strip()
        if not tag:
            return 0
        existing = self.tag_to_operand_idx.get(tag)
        if existing is not None:
            return existing
        if self.allocation_mode == "order_pool":
            operand_idx = self._alloc_regular_order_pool()
        else:
            operand_idx = layout_operand_idx(self.reg_idx_counter + self.reg_start_idx)
        self.tag_to_operand_idx[tag] = operand_idx
        self.reg_idx_counter += 1
        return operand_idx

    def retrieve_reg_idx(self, tag: str) -> int:
        """Mirror vendor COPY patch lookup.

        In the fully checked vendor source this is a hard lookup.  Some local
        stub versions allocate on miss, but that masks graph-order mistakes.
        Keep the strict behaviour here so missing child-side tags fail loudly
        when the replay pass is enabled.
        """

        tag = tag.strip()
        if not tag:
            return 0
        if tag not in self.tag_to_operand_idx:
            raise KeyError(f"receiver TaskResource missing tag: {tag}")
        return self.tag_to_operand_idx[tag]

    def seed_regular(self, tags: tuple[str, ...]) -> None:
        for tag in tags:
            self.get_reg_idx(tag)

    def seed_tensor(self, tag: str, group_idx: int) -> int:
        """Allocate a pseudo-tensor base in a fixed RAM group.

        Vendor tensor pseudo ops consume the high line numbers first within a
        group: 127, 126, ... .  Lanes are then formed by adding
        ``OPERANDS_PER_OPERAND_RAM``.
        """

        tag = tag.strip()
        if not tag:
            return 0
        existing = self.tag_to_operand_idx.get(tag)
        if existing is not None:
            return existing
        group_idx = int(group_idx)
        group_count = OPERANDS_RAM_NUM // OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE
        if group_idx < 0 or group_idx >= group_count:
            raise ValueError(f"invalid tensor operand group: {group_idx}")
        if self.allocation_mode == "order_pool":
            operand_idx = self._alloc_tensor_order_pool((group_idx,))
            self.tag_to_operand_idx[tag] = operand_idx
            return operand_idx
        next_idx = self.tensor_group_next_idx.get(
            group_idx,
            OPERANDS_PER_OPERAND_RAM - 1,
        )
        operand_idx = (
            group_idx
            * OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE
            * OPERANDS_PER_OPERAND_RAM
            + next_idx
        )
        self.tag_to_operand_idx[tag] = operand_idx
        self.tensor_group_next_idx[group_idx] = next_idx - 1
        return operand_idx

    @staticmethod
    def tensor_lane_operand(base_operand_idx: int, lane: int) -> int:
        """Return COPYT/HLDT/HSTT follow-lane operand index."""

        return int(base_operand_idx) + int(lane) * OPERANDS_PER_OPERAND_RAM

    def _alloc_regular_order_pool(self) -> int:
        if not self.stage_free_ram_indices:
            self.begin_stage()
        if not self.stage_free_ram_indices:
            raise RuntimeError("no operand RAM slot available")
        ram_idx = self.stage_free_ram_indices.pop(0)
        if not self.operand_ram_free.get(ram_idx):
            raise RuntimeError(f"operand RAM {ram_idx} is empty")
        operand_idx = self.operand_ram_free[ram_idx].pop()
        self._erase_tensor_slot_for_regular_operand(operand_idx)
        return operand_idx

    def _alloc_tensor_order_pool(self, candidate_groups: tuple[int, ...]) -> int:
        if not candidate_groups:
            candidate_groups = tuple(sorted(self.tensor_group_free))
        best_group = max(
            candidate_groups,
            key=lambda group_idx: len(self.tensor_group_free.get(group_idx, ())),
        )
        if not self.tensor_group_free.get(best_group):
            raise RuntimeError(f"tensor operand group {best_group} is empty")
        return self.tensor_group_free[best_group].pop()

    def _erase_tensor_slot_for_regular_operand(self, operand_idx: int) -> None:
        group_idx = int(operand_idx) // (
            OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE * OPERANDS_PER_OPERAND_RAM
        )
        line_idx = int(operand_idx) % OPERANDS_PER_OPERAND_RAM
        first_reg = (
            group_idx
            * OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE
            * OPERANDS_PER_OPERAND_RAM
            + line_idx
        )
        slots = self.tensor_group_free.get(group_idx)
        if slots is None:
            return
        try:
            slots.remove(first_reg)
        except ValueError:
            pass


@dataclass
class _ReplayBindingContext:
    """Track old template bases so pseudo-lane deltas can be preserved."""

    resource: Dfu3500TaskResourceState
    template_base_by_key: dict[tuple[str, str], int] = field(default_factory=dict)

    def bind_operand(
        self,
        *,
        role: str,
        tag: str,
        old_operand_idx: int,
        forced_group: int | None,
    ) -> int:
        tag = tag.strip()
        if not tag:
            return 0
        if forced_group is None:
            base = self.resource.get_reg_idx(tag)
        else:
            base = self.resource.seed_tensor(tag, forced_group)
        template_key = (role, tag)
        old_base = self.template_base_by_key.setdefault(
            template_key,
            int(old_operand_idx),
        )
        lane_delta = int(old_operand_idx) - old_base
        if (
            lane_delta < 0
            or lane_delta % OPERANDS_PER_OPERAND_RAM != 0
            or lane_delta >= OPERANDS_PER_OPERAND_RAM * OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE
        ):
            lane_delta = 0
        return base + lane_delta


def replay_legacy_task_resource(
    vendor_abi: ProgramVendorABI,
) -> ProgramVendorABI:
    """Optionally replay source-derived TaskResource operand binding.

    The replay is gated by ``OPENFABRIC_ENABLE_DFU3500_TASK_RESOURCE_REPLAY``.
    Default-off keeps the currently validated bundle stable while letting us
    produce a candidate artifact for arch-13 byte-diff validation.
    """

    if os.environ.get(TASK_RESOURCE_REPLAY_ENV) not in {"1", "true", "TRUE", "yes"}:
        return vendor_abi
    return _replay_legacy_task_resource_enabled(vendor_abi)


def _replay_legacy_task_resource_enabled(
    vendor_abi: ProgramVendorABI,
) -> ProgramVendorABI:
    """Return a vendor ABI copy with replay-patched template instructions."""

    contexts: dict[tuple[int, str], _ReplayBindingContext] = {}
    patched = dict(vendor_abi.template_bound_instructions)
    ranges_by_exeblock = _instruction_ranges_by_exeblock(vendor_abi)

    for exeblock in sorted(
        vendor_abi.vendor_exeblocks.values(),
        key=_exeblock_replay_sort_key,
    ):
        context = contexts.setdefault(
            (exeblock.task_index, exeblock.processor),
            _ReplayBindingContext(
                resource=Dfu3500TaskResourceState(
                    reg_start_idx=_legacy_reg_start_idx_for_task(exeblock.task_index),
                    allocation_mode="order_pool",
                )
            ),
        )
        for range_row in sorted(
            ranges_by_exeblock.get(exeblock.id, ()),
            key=lambda row: (STAGE_ORDER.get(row.stage, 99), row.start_pc, row.id),
        ):
            context.resource.begin_stage()
            for instruction_id in range_row.template_bound_instruction_ids:
                template_instruction = patched[instruction_id]
                legacy_inst = _bind_legacy_inst_operands(
                    template_instruction.legacy_inst,
                    context,
                ).clone_with(block_idx=exeblock.pe_local_block_idx)
                patched[instruction_id] = replace(
                    template_instruction,
                    legacy_inst=legacy_inst,
                )

    _patch_copy_destinations(
        patched,
        vendor_abi=vendor_abi,
        contexts=contexts,
        ranges_by_exeblock=ranges_by_exeblock,
    )

    folded_vendor_report = dict(vendor_abi.folded_vendor_report)
    folded_vendor_report["task_resource_replay"] = {
        "enabled": True,
        "env": TASK_RESOURCE_REPLAY_ENV,
        "scope": "template_bound_instruction_operand_fields",
        "copy_destination_operand_patched": True,
        "copy_destination_pe_block_patched_by_serializer": True,
        "candidate_status": "opt_in_arch13_diff_validation_required",
    }

    return replace(
        vendor_abi,
        template_bound_instructions=patched,
        folded_vendor_report=folded_vendor_report,
    )


def _bind_legacy_inst_operands(
    inst: LegacyInst,
    context: _ReplayBindingContext,
) -> LegacyInst:
    forced_group = _forced_tensor_group(inst)
    src0 = (
        context.bind_operand(
            role="src0",
            tag=inst.src_reg_idx0_tag,
            old_operand_idx=inst.src_operands_idx[0],
            forced_group=forced_group,
        )
        if inst.src_reg_idx0_tag
        else None
    )
    src1 = (
        context.bind_operand(
            role="src1",
            tag=inst.src_reg_idx1_tag,
            old_operand_idx=inst.src_operands_idx[1],
            forced_group=forced_group,
        )
        if inst.src_reg_idx1_tag
        else None
    )
    dst0 = (
        context.bind_operand(
            role="dst0",
            tag=inst.dst_reg_idx_tag,
            old_operand_idx=inst.dst_operands_idx[0],
            forced_group=forced_group,
        )
        if inst.dst_reg_idx_tag
        else None
    )
    rebound = inst.clone_with(
        src_operand_idx0=src0,
        src_operand_idx1=src1,
        dst_operand_idx0=dst0,
    )
    context.resource.finish_instruction(
        tuple(
            operand_idx
            for operand_idx in (
                rebound.src_operands_idx[0],
                rebound.src_operands_idx[1],
                rebound.dst_operands_idx[0],
            )
            if operand_idx
        )
    )
    return rebound


def _patch_copy_destinations(
    patched: dict[str, object],
    *,
    vendor_abi: ProgramVendorABI,
    contexts: dict[tuple[int, str], _ReplayBindingContext],
    ranges_by_exeblock: dict[str, tuple[object, ...]],
) -> None:
    for exeblock in vendor_abi.vendor_exeblocks.values():
        if "route_forward" not in exeblock.source_tile_micro_block_kinds:
            continue
        endpoint_processor = _endpoint_processor_from_micro_block_ids(
            exeblock.source_tile_micro_block_ids
        )
        if endpoint_processor is None:
            continue
        receiver = contexts.get((exeblock.task_index, endpoint_processor))
        if receiver is None:
            continue
        for range_row in ranges_by_exeblock.get(exeblock.id, ()):
            if range_row.stage != "FLOW":
                continue
            for instruction_id in range_row.template_bound_instruction_ids:
                template_instruction = patched[instruction_id]
                inst = template_instruction.legacy_inst
                if inst.op_name != "COPY" or not inst.dst_reg_idx_tag:
                    continue
                base = receiver.resource.retrieve_reg_idx(inst.dst_reg_idx_tag)
                old_base = receiver.template_base_by_key.get(
                    ("dst0", inst.dst_reg_idx_tag),
                    inst.dst_operands_idx[0],
                )
                lane_delta = inst.dst_operands_idx[0] - old_base
                if (
                    lane_delta < 0
                    or lane_delta % OPERANDS_PER_OPERAND_RAM != 0
                    or lane_delta >= OPERANDS_PER_OPERAND_RAM * OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE
                ):
                    lane_delta = 0
                patched[instruction_id] = replace(
                    template_instruction,
                    legacy_inst=inst.clone_with(dst_operand_idx0=base + lane_delta),
                )


def _instruction_ranges_by_exeblock(vendor_abi: ProgramVendorABI) -> dict[str, tuple[object, ...]]:
    grouped: dict[str, list[object]] = {}
    for row in vendor_abi.instruction_ranges.values():
        grouped.setdefault(row.vendor_exeblock_id, []).append(row)
    return {
        exeblock_id: tuple(rows)
        for exeblock_id, rows in grouped.items()
    }


def _forced_tensor_group(inst: LegacyInst) -> int | None:
    group = int(inst.extra_fields[2]) - 1
    if group >= 0:
        return group
    return None


def _legacy_reg_start_idx_for_task(task_index: int) -> int:
    # Current legacy GEMM compatibility templates use a 50-regular-tag stride
    # per task.  Keep this local to the replay candidate so the source-derived
    # pass can later replace it with a true app-resource counter if needed.
    return int(task_index) * 50


def _exeblock_replay_sort_key(row: VendorExeBlockRow) -> tuple[int, int, int, int, str]:
    return (
        row.task_index,
        _pe_index_for_processor(row.processor),
        row.subtask_index,
        row.pe_local_block_idx,
        row.id,
    )


def _pe_index_for_processor(processor: str) -> int:
    parts = str(processor).split("_")
    if len(parts) == 3 and parts[0] == "processor":
        return int(parts[1]) * 4 + int(parts[2])
    return 0


def _endpoint_processor_from_micro_block_ids(block_ids: tuple[str, ...]) -> str | None:
    for block_id in block_ids:
        marker = "processor_"
        index = str(block_id).rfind(marker)
        if index < 0:
            continue
        tail = str(block_id)[index:].split("_")
        if len(tail) >= 3 and tail[0] == "processor":
            return f"processor_{tail[1]}_{tail[2]}"
    return None


def build_task_resource_replay_authority_report(
    vendor_abi: ProgramVendorABI | None = None,
    *,
    s2_bindings: Iterable[object] = (),
) -> TaskResourceReplayAuthorityReport:
    """Build a report-only S2 TaskResource row-authority summary.

    ``TaskResource`` replay currently proves a narrow set of row fields: normal
    operand-index rebinding for template-bound legacy rows, and receiver-side
    COPY destination operand rebinding.  COPY destination PE/block and
    instruction ``block_idx`` are closed by vendor row provenance rather than
    TaskResource state.  ``end_inst`` is deliberately left open here because the
    replay model has no authority over instruction boundary policy.
    """

    role_statuses = _s2_role_statuses(s2_bindings)
    covered_role_counts = tuple(
        sorted(
            (
                f"{status.role}|{status.opcode}",
                status.blocked_on_task_resource_row_count,
            )
            for status in role_statuses
            if status.closed_fields or status.non_replay_closed_fields
        )
    )
    open_blockers = _sorted_unique(
        blocker
        for status in role_statuses
        for blocker in status.open_blockers
    )
    vendor_abi_field_status = (
        {} if vendor_abi is None else _vendor_abi_task_resource_field_status(vendor_abi)
    )
    has_closed = bool(covered_role_counts) or bool(
        vendor_abi_field_status.get("closed_field_counts")
    )
    authority_status = "closed" if has_closed and not open_blockers else "open"
    if has_closed and open_blockers:
        authority_status = "partial"
    elif not has_closed and open_blockers:
        authority_status = "blocked"
    return TaskResourceReplayAuthorityReport(
        authority_status=authority_status,
        role_statuses=role_statuses,
        covered_role_counts=covered_role_counts,
        open_blockers=open_blockers,
        vendor_abi_field_status=vendor_abi_field_status,
    )


def _s2_role_statuses(
    bindings: Iterable[object],
) -> tuple[TaskResourceReplayAuthorityRoleStatus, ...]:
    grouped: dict[tuple[str, str], list[object]] = {}
    for binding in bindings:
        role = str(getattr(binding, "role", "unknown"))
        opcode = str(getattr(binding, "opcode", "unknown"))
        grouped.setdefault((role, opcode), []).append(binding)

    statuses: list[TaskResourceReplayAuthorityRoleStatus] = []
    for (role, opcode), group in sorted(grouped.items()):
        blocked_on_task_resource = [
            binding
            for binding in group
            if _binding_needs_task_resource_row_authority(binding)
        ]
        closed_fields, non_replay_closed_fields, open_fields, blockers = (
            _role_opcode_authority_fields(role, opcode)
        )
        if not blocked_on_task_resource:
            closed_fields = ()
            non_replay_closed_fields = ()
            open_fields = ()
            blockers = ()
            status = "not_blocked_on_task_resource_replay"
        elif closed_fields and blockers:
            status = "partial"
        elif closed_fields and not blockers:
            status = "closed"
        else:
            status = "open"
        statuses.append(
            TaskResourceReplayAuthorityRoleStatus(
                role=role,
                opcode=opcode,
                row_count=len(group),
                blocked_on_task_resource_row_count=len(blocked_on_task_resource),
                authority_status=status,
                closed_fields=closed_fields,
                non_replay_closed_fields=non_replay_closed_fields,
                open_fields=open_fields,
                open_blockers=blockers,
            )
        )
    return tuple(statuses)


def _binding_needs_task_resource_row_authority(binding: object) -> bool:
    candidate_status = str(getattr(binding, "exact_seed_candidate_status", ""))
    required_status = str(getattr(binding, "required_raw_template_bytes_status", ""))
    if candidate_status or required_status:
        return (
            "task_resource_replay_row_authority" in candidate_status
            or "task_resource_replay_row_authority" in required_status
        )
    missing_seed_fields = tuple(getattr(binding, "missing_seed_fields", ()))
    return TASK_RESOURCE_REPLAY_ROW_AUTHORITY_FIELD in missing_seed_fields


def _role_opcode_authority_fields(
    role: str,
    opcode: str,
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    if role == "operand_route_recv:A" and opcode == "ROUTE_RECV_VISIBILITY":
        return (
            (
                "inst_t.dst_operands_idx[0]",
                "inst_t.src_operands_idx[0]",
            ),
            (
                "inst_t.dst_pes_pos[0]",
                "inst_t.dst_blocks_idx[0]",
                "inst_t.block_idx",
            ),
            (
                "inst_t.raw_template_row_bytes",
                "inst_t.local_order_or_row_span",
                "inst_t.template_row_sha256",
                "inst_t.end_inst",
            ),
            (
                "route_forward COPY still needs exact sender raw row/local_order",
                "end_inst is instruction-boundary policy, not TaskResource authority",
            ),
        )
    return (
        (),
        ("inst_t.block_idx",),
        (
            "inst_t.src_operands_idx[0]",
            "inst_t.src_operands_idx[1]",
            "inst_t.dst_operands_idx[0]",
            "inst_t.raw_template_row_bytes",
            "inst_t.local_order_or_row_span",
            "inst_t.template_row_sha256",
            "inst_t.end_inst",
        ),
        (
            "no role/opcode-specific TaskResource row authority is proven yet",
            "exact raw row/local_order remains required before operand fields can be consumed",
            "end_inst is instruction-boundary policy, not TaskResource authority",
        ),
    )


def _vendor_abi_task_resource_field_status(
    vendor_abi: ProgramVendorABI,
) -> dict[str, Any]:
    field_counts: dict[str, int] = {}
    opcode_counts: dict[str, int] = {}
    copy_route_rows = 0
    range_by_instruction = _range_by_template_instruction(vendor_abi)

    for (
        instruction_id,
        template_instruction,
    ) in vendor_abi.template_bound_instructions.items():
        inst = template_instruction.legacy_inst
        opcode_counts[inst.op_name] = opcode_counts.get(inst.op_name, 0) + 1
        if inst.src_reg_idx0_tag.strip():
            field_counts["inst_t.src_operands_idx[0]"] = (
                field_counts.get("inst_t.src_operands_idx[0]", 0) + 1
            )
        if inst.src_reg_idx1_tag.strip():
            field_counts["inst_t.src_operands_idx[1]"] = (
                field_counts.get("inst_t.src_operands_idx[1]", 0) + 1
            )
        if inst.dst_reg_idx_tag.strip():
            field_counts["inst_t.dst_operands_idx[0]"] = (
                field_counts.get("inst_t.dst_operands_idx[0]", 0) + 1
            )
        range_row = range_by_instruction.get(instruction_id)
        if range_row is not None and _is_route_forward_copy(vendor_abi, range_row, inst):
            copy_route_rows += 1

    return {
        "status": "report_only",
        "template_bound_instruction_count": len(vendor_abi.template_bound_instructions),
        "opcode_counts": dict(sorted(opcode_counts.items())),
        "closed_field_counts": dict(sorted(field_counts.items())),
        "copy_route_row_count": copy_route_rows,
        "copy_route_closed_fields": [
            "inst_t.dst_operands_idx[0]",
            "inst_t.dst_pes_pos[0] (serializer row provenance)",
            "inst_t.dst_blocks_idx[0] (serializer row provenance)",
        ],
        "open_fields": [
            "inst_t.raw_template_row_bytes",
            "inst_t.template_row_sha256",
            "inst_t.end_inst",
        ],
    }


def _range_by_template_instruction(vendor_abi: ProgramVendorABI) -> dict[str, object]:
    result: dict[str, object] = {}
    for range_row in vendor_abi.instruction_ranges.values():
        for instruction_id in range_row.template_bound_instruction_ids:
            result[instruction_id] = range_row
    return result


def _is_route_forward_copy(
    vendor_abi: ProgramVendorABI,
    range_row: object,
    inst: LegacyInst,
) -> bool:
    if inst.op_name != "COPY":
        return False
    exeblock = vendor_abi.vendor_exeblocks.get(range_row.vendor_exeblock_id)
    return (
        exeblock is not None
        and "route_forward" in exeblock.source_tile_micro_block_kinds
    )


def _sorted_unique(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(sorted({value for value in values if value}))


__all__ = [
    "Dfu3500TaskResourceState",
    "TASK_RESOURCE_REPLAY_ENV",
    "TASK_RESOURCE_REPLAY_ROW_AUTHORITY_FIELD",
    "TaskResourceReplayAuthorityReport",
    "TaskResourceReplayAuthorityRoleStatus",
    "build_task_resource_replay_authority_report",
    "layout_operand_idx",
    "replay_legacy_task_resource",
]
