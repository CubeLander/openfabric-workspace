"""Binary-row planning boundary for the folded DFU vendor ABI.

This layer is deliberately boring: it consumes already-decided
``ProgramVendorABI`` rows and prepares binary-facing row plans. It must not
rediscover loops, route paths, dependency classes, K recurrence, or tile
micro-block ownership. Full component bytes are blocked until variant binding
and instruction layout gates are satisfied.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from gpdpu_compiler.core.dfu3500.legacy_templates import TemplateBoundInstruction
from gpdpu_compiler.core.program_legacy_inst import (
    OPERANDS_PER_OPERAND_RAM,
    LegacyInst,
)
from gpdpu_compiler.core.program_vendor_abi import ProgramVendorABI, VendorSubtaskRow


INSTANCE_CONF_RECORD_SIZE_BYTES = 32
INSTANCE_CONF_CAPACITY = 65536
INST_RECORD_SIZE_BYTES = 304
MAX_INST_AMOUNT_PER_PE = 4352
PE_AMOUNT = 16
INST_CAPACITY = MAX_INST_AMOUNT_PER_PE * PE_AMOUNT
TASK_CONF_RECORD_SIZE_BYTES = 120
TASK_CONF_CAPACITY = 4
TASK_SUBTASK_SLOT_COUNT = 8
TASK_SUCCESSOR_SLOT_COUNT = 4
EXEBLOCK_CONF_RECORD_SIZE_BYTES = 520
EXEBLOCK_CONF_CAPACITY = 512
EXEBLOCK_EDGE_SLOT_COUNT = 4
DFU3500_LEGACY_EXEBLOCKS_PER_PE = EXEBLOCK_CONF_CAPACITY // PE_AMOUNT
SUBTASK_CONF_RECORD_SIZE_BYTES = 266328
SUBTASK_CONF_CAPACITY = 32
SUBTASK_EMBEDDED_EXEBLOCK_SLOT_COUNT = 512
UNUSED_BASE_ADDR_WORD = 0xFFFFFFFF
UNUSED_TASK_FIELD = 0xFFFFFFFF
UNUSED_EXEBLOCK_FIELD = "__unused__"
DFU3500_LEGACY_TASK_COUNT = TASK_CONF_CAPACITY
DFU3500_LEGACY_SUBTASK_SLOT_COUNT_PER_TASK = TASK_SUBTASK_SLOT_COUNT
DFU3500_LEGACY_INSTANCES_PER_SUBTASK_SLOT = 2048
DFU3500_LEGACY_GEMM_INPUT1_BASE_WORD = 0x00000
DFU3500_LEGACY_GEMM_INPUT2_BASE_WORD = 0x10000
DFU3500_LEGACY_GEMM_INPUT3_BASE_WORD = 0x20000
DFU3500_LEGACY_GEMM_A_INSTANCE_STRIDE_WORDS = 0x20
DFU3500_LEGACY_GEMM_B_INSTANCE_STRIDE_WORDS = 0x4000
_BINARY_POLICY_SCHEMA_VERSION = "binary_policy.v1"
_BINARY_POLICY_ALLOWED_KEYS = frozenset(
    {
        "schema_version",
        "component_bytes_emitted",
        "complete_runtime_package_emitted",
        "program_bin_role",
        "vendor_inst_modes",
        "native_symbolic_semantics",
    }
)


def _checked_binary_policy(policy: dict[str, Any]) -> dict[str, Any]:
    keys = set(policy)
    if keys != _BINARY_POLICY_ALLOWED_KEYS:
        extra = sorted(keys - _BINARY_POLICY_ALLOWED_KEYS)
        missing = sorted(_BINARY_POLICY_ALLOWED_KEYS - keys)
        raise ValueError(
            "binary_policy schema mismatch: "
            f"extra={extra}, missing={missing}"
        )
    if policy["schema_version"] != _BINARY_POLICY_SCHEMA_VERSION:
        raise ValueError(
            "binary_policy schema version mismatch: "
            f"{policy['schema_version']!r}"
        )
    return policy

InstancesConfMemBasedAddrUnit = Literal["bytes"]
TaskSuccessorPolicy = Literal[
    "unset",
    "legacy_chain",
    "independent_start_end",
    "single_task",
]
VendorInstMode = Literal[
    "native_symbolic",
    "legacy_gemm_compat",
    "legacy_template_compat",
]
BindingTargetKind = Literal[
    "instance_base_addr",
    "instruction_static_immediate",
    "instruction_parametric_immediate",
    "route_param",
    "debug_only",
]
TargetProofStatus = Literal[
    "legacy_confirmed",
    "assumed_symbolic",
    "debug_only",
    "unsupported",
]
InstanceConfRowKind = Literal[
    "semantic_active",
    "role_filled_window",
    "inactive_filler",
]


@dataclass(frozen=True)
class Dfu3500LegacyGemmProfile:
    """DFU3500 legacy GEMM instance-conf address profile."""

    input1_base_word: int = DFU3500_LEGACY_GEMM_INPUT1_BASE_WORD
    input2_base_word: int = DFU3500_LEGACY_GEMM_INPUT2_BASE_WORD
    input3_base_word: int = DFU3500_LEGACY_GEMM_INPUT3_BASE_WORD
    a_instance_stride_words: int = DFU3500_LEGACY_GEMM_A_INSTANCE_STRIDE_WORDS
    b_instance_stride_words: int = DFU3500_LEGACY_GEMM_B_INSTANCE_STRIDE_WORDS


@dataclass(frozen=True)
class VendorLoopVariantBinding:
    """Symbolic binding for one folded-loop variant value.

    The binding is a safety rail before binary emission. A K-varying value must
    be mapped to a proven binary target, not silently encoded into the shared
    k0 instruction image.
    """

    id: str
    template_id: str
    vendor_subtask_id: str
    instance_key: str
    loop_axis: str
    loop_index: int
    source_tile_refs: tuple[str, ...] = ()
    source_visibility_refs: tuple[str, ...] = ()
    route_bundle_refs: tuple[str, ...] = ()
    operand_role: str = ""
    base_addr_slot_bindings: dict[int, str] = field(default_factory=dict)
    base_addr_word_bindings: dict[int, int] = field(default_factory=dict)
    immediate_bindings: dict[str, str] = field(default_factory=dict)
    instruction_range_bindings: tuple[str, ...] = ()
    binding_target_kind: BindingTargetKind = "debug_only"
    logical_address_expr: str = ""
    effective_address_expr: str = ""
    target_proof_status: TargetProofStatus = "debug_only"

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "template_id": self.template_id,
            "vendor_subtask_id": self.vendor_subtask_id,
            "instance_key": self.instance_key,
            "loop_axis": self.loop_axis,
            "loop_index": self.loop_index,
            "source_tile_refs": list(self.source_tile_refs),
            "source_visibility_refs": list(self.source_visibility_refs),
            "route_bundle_refs": list(self.route_bundle_refs),
            "operand_role": self.operand_role,
            "base_addr_slot_bindings": {
                str(slot): expr
                for slot, expr in sorted(self.base_addr_slot_bindings.items())
            },
            "base_addr_word_bindings": {
                str(slot): word
                for slot, word in sorted(self.base_addr_word_bindings.items())
            },
            "base_addr_word_bindings_hex": {
                str(slot): f"0x{word:08x}"
                for slot, word in sorted(self.base_addr_word_bindings.items())
            },
            "immediate_bindings": dict(sorted(self.immediate_bindings.items())),
            "instruction_range_bindings": list(self.instruction_range_bindings),
            "binding_target_kind": self.binding_target_kind,
            "logical_address_expr": self.logical_address_expr,
            "effective_address_expr": self.effective_address_expr,
            "target_proof_status": self.target_proof_status,
            "binary_bound": self.target_proof_status == "legacy_confirmed"
            and self.binding_target_kind == "instance_base_addr",
        }


@dataclass(frozen=True)
class InstanceConfBinRow:
    """Subtask-instance level ``instance_conf_info_t`` row plan."""

    id: str
    global_row_index: int
    task_id: str
    task_index: int
    vendor_subtask_id: str
    subtask_index: int
    instance_key: str
    subtask_instance_index: int
    base_addr_words: tuple[int, int, int, int]
    source_binding_ids: tuple[str, ...]
    source_vendor_instance_ids: tuple[str, ...]
    component_byte_offset: int
    physical_task_index: int
    physical_subtask_slot_index: int
    physical_instance_slot_index: int
    row_kind: InstanceConfRowKind
    is_semantic_active: bool
    semantic_row_index: int | None = None
    semantic_component_byte_offset: int | None = None
    record_size_bytes: int = INSTANCE_CONF_RECORD_SIZE_BYTES
    component_name: str = "instance_conf_info_file.bin"

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "global_row_index": self.global_row_index,
            "component_name": self.component_name,
            "component_byte_offset": self.component_byte_offset,
            "record_size_bytes": self.record_size_bytes,
            "task_id": self.task_id,
            "task_index": self.task_index,
            "vendor_subtask_id": self.vendor_subtask_id,
            "subtask_index": self.subtask_index,
            "instance_key": self.instance_key,
            "subtask_instance_index": self.subtask_instance_index,
            "physical_task_index": self.physical_task_index,
            "physical_subtask_slot_index": self.physical_subtask_slot_index,
            "physical_instance_slot_index": self.physical_instance_slot_index,
            "row_kind": self.row_kind,
            "is_semantic_active": self.is_semantic_active,
            "semantic_row_index": self.semantic_row_index,
            "semantic_component_byte_offset": self.semantic_component_byte_offset,
            "base_addr_words": list(self.base_addr_words),
            "base_addr_words_hex": [f"0x{word:08x}" for word in self.base_addr_words],
            "unused_slot_sentinel": f"0x{UNUSED_BASE_ADDR_WORD:08x}",
            "source_binding_ids": list(self.source_binding_ids),
            "source_binding_count": len(self.source_binding_ids),
            "source_vendor_instance_ids": list(self.source_vendor_instance_ids),
            "binary_encoded": False,
        }


@dataclass(frozen=True)
class TaskConfBinRow:
    """Global ``task_conf_info_t`` row plan."""

    id: str
    global_row_index: int
    task_id: str
    task_index: int
    is_exe_start: bool
    is_exe_end: bool
    execute_times: int
    active_subtask_ids: tuple[str, ...]
    active_subtask_indices: tuple[int, ...]
    subtasks_idx_slots: tuple[int, ...]
    successor_task_indices: tuple[int, ...]
    successor_task_slots: tuple[int, ...]
    task_successor_policy: TaskSuccessorPolicy
    component_byte_offset: int
    record_size_bytes: int = TASK_CONF_RECORD_SIZE_BYTES
    component_name: str = "tasks_conf_info_file.bin"

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "global_row_index": self.global_row_index,
            "component_name": self.component_name,
            "component_byte_offset": self.component_byte_offset,
            "record_size_bytes": self.record_size_bytes,
            "task_id": self.task_id,
            "task_index": self.task_index,
            "is_exe_start": self.is_exe_start,
            "is_exe_end": self.is_exe_end,
            "execute_times": self.execute_times,
            "active_subtask_ids": list(self.active_subtask_ids),
            "active_subtask_count": len(self.active_subtask_ids),
            "active_subtask_indices": list(self.active_subtask_indices),
            "subtasks_idx_slots": list(self.subtasks_idx_slots),
            "successor_task_indices": list(self.successor_task_indices),
            "suc_tasks_slots": list(self.successor_task_slots),
            "task_successor_policy": self.task_successor_policy,
            "unused_field_sentinel": f"0x{UNUSED_TASK_FIELD:08x}",
            "binary_encoded": False,
        }


@dataclass(frozen=True)
class ExeBlockConfBinRow:
    """PE-local ``exeBlock_conf_info_t`` row plan."""

    id: str
    global_row_index: int
    vendor_exeblock_id: str
    source_asm_block_id: str
    task_id: str
    task_index: int
    vendor_subtask_id: str
    subtask_index: int
    role: str
    processor: str
    pe: str
    pe_pos: tuple[int, int, int]
    block_idx: int
    instance_key: str
    source_tile_micro_block_ids: tuple[str, ...]
    source_tile_micro_block_kinds: tuple[str, ...]
    instruction_layout_row_ids: tuple[str, ...]
    instruction_ids: tuple[str, ...]
    inst_mem_based_addr: int
    stage_start_pc: dict[str, int]
    stage_instruction_counts: dict[str, int]
    predecessor_ids: tuple[str, ...]
    successor_ids: tuple[str, ...]
    predecessor_slots: tuple[str, ...]
    successor_slots: tuple[str, ...]
    req_activations: int
    child_amount: int
    component_byte_offset: int
    vendor_inst_mode: VendorInstMode = "native_symbolic"
    record_size_bytes: int = EXEBLOCK_CONF_RECORD_SIZE_BYTES
    component_name: str = "exeblock_conf_info_file.bin"

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "global_row_index": self.global_row_index,
            "component_name": self.component_name,
            "component_byte_offset": self.component_byte_offset,
            "record_size_bytes": self.record_size_bytes,
            "vendor_exeblock_id": self.vendor_exeblock_id,
            "source_asm_block_id": self.source_asm_block_id,
            "task_id": self.task_id,
            "task_index": self.task_index,
            "vendor_subtask_id": self.vendor_subtask_id,
            "subtask_index": self.subtask_index,
            "role": self.role,
            "processor": self.processor,
            "pe": self.pe,
            "pe_pos": list(self.pe_pos),
            "block_idx": self.block_idx,
            "instance_key": self.instance_key,
            "source_tile_micro_block_ids": list(self.source_tile_micro_block_ids),
            "source_tile_micro_block_kinds": list(self.source_tile_micro_block_kinds),
            "instruction_layout_row_ids": list(self.instruction_layout_row_ids),
            "instruction_ids": list(self.instruction_ids),
            "instruction_count": len(self.instruction_ids),
            "inst_mem_based_addr": self.inst_mem_based_addr,
            "stage_start_pc": dict(sorted(self.stage_start_pc.items())),
            "stage_instruction_counts": dict(sorted(self.stage_instruction_counts.items())),
            "ld_stage_inst_amount": self.stage_instruction_counts.get("LD", 0),
            "cal_stage_inst_amount": self.stage_instruction_counts.get("CAL", 0),
            "flow_stage_inst_amount": self.stage_instruction_counts.get("FLOW", 0),
            "st_stage_inst_amount": self.stage_instruction_counts.get("ST", 0),
            "predecessors": list(self.predecessor_ids),
            "successors": list(self.successor_ids),
            "predecessor_slots": list(self.predecessor_slots),
            "successor_slots": list(self.successor_slots),
            "req_activations": self.req_activations,
            "child_amount": self.child_amount,
            "vendor_inst_mode": self.vendor_inst_mode,
            "edge_slot_count": EXEBLOCK_EDGE_SLOT_COUNT,
            "unused_slot_sentinel": UNUSED_EXEBLOCK_FIELD,
            "binary_encoded": False,
        }


@dataclass(frozen=True)
class SubtaskConfBinRow:
    """Global ``sub_task_conf_info_t`` row plan."""

    id: str
    global_row_index: int
    vendor_subtask_id: str
    task_id: str
    task_index: int
    subtask_index: int
    role: str
    is_exe_start: bool
    is_exe_end: bool
    instances_amount: int
    instances_conf_mem_based_addr: int
    instance_conf_row_ids: tuple[str, ...]
    embedded_exe_block_row_ids: tuple[str, ...]
    embedded_exe_block_slots: tuple[str, ...]
    valid_exe_blocks: int
    repeat_mode: str
    repeat_semantics: str | None
    template_instance_key: str | None
    component_byte_offset: int
    record_size_bytes: int = SUBTASK_CONF_RECORD_SIZE_BYTES
    component_name: str = "subtasks_conf_info_file.bin"

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "global_row_index": self.global_row_index,
            "component_name": self.component_name,
            "component_byte_offset": self.component_byte_offset,
            "record_size_bytes": self.record_size_bytes,
            "vendor_subtask_id": self.vendor_subtask_id,
            "task_id": self.task_id,
            "task_index": self.task_index,
            "subtask_index": self.subtask_index,
            "role": self.role,
            "is_exe_start": self.is_exe_start,
            "is_exe_end": self.is_exe_end,
            "instances_amount": self.instances_amount,
            "instances_conf_mem_based_addr": self.instances_conf_mem_based_addr,
            "instances_conf_mem_based_addr_unit": "bytes",
            "instance_conf_row_ids": list(self.instance_conf_row_ids),
            "embedded_exe_block_row_ids": list(self.embedded_exe_block_row_ids),
            "embedded_exe_block_slot_count": len(self.embedded_exe_block_slots),
            "embedded_exe_block_slots": list(self.embedded_exe_block_slots),
            "valid_exe_blocks": self.valid_exe_blocks,
            "repeat_mode": self.repeat_mode,
            "repeat_semantics": self.repeat_semantics,
            "template_instance_key": self.template_instance_key,
            "embedded_exeblock_source": (
                "ProgramBinRows.exe_block_rows byte-for-byte source rows"
            ),
            "binary_encoded": False,
        }


@dataclass(frozen=True)
class InstructionLayoutRow:
    """Final symbolic PC/count/range plan used before exeBlock bytes exist."""

    id: str
    vendor_instruction_range_id: str
    vendor_exeblock_id: str
    processor: str
    pe: str
    stage: str
    start_pc: int
    end_pc: int
    instruction_ids: tuple[str, ...]
    vendor_inst_mode: VendorInstMode = "native_symbolic"
    component_semantics: str = "structural_smoke_only"
    complete_runtime_package_semantics: bool = False

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "vendor_instruction_range_id": self.vendor_instruction_range_id,
            "vendor_exeblock_id": self.vendor_exeblock_id,
            "processor": self.processor,
            "pe": self.pe,
            "stage": self.stage,
            "start_pc": self.start_pc,
            "end_pc": self.end_pc,
            "instruction_count": len(self.instruction_ids),
            "instruction_ids": list(self.instruction_ids),
            "vendor_inst_mode": self.vendor_inst_mode,
            "component_semantics": self.component_semantics,
            "complete_runtime_package_semantics": self.complete_runtime_package_semantics,
        }


@dataclass(frozen=True)
class InstBinRow:
    """Native-symbolic ``inst_t`` row plan.

    This is a structural smoke row only. It preserves final PC placement,
    stage/unit class, block index, and provenance, but it is not a functional
    GEMM instruction encoding.
    """

    id: str
    global_row_index: int
    local_pc: int
    pe: str
    pe_index: int
    processor: str
    vendor_exeblock_id: str
    instruction_layout_row_id: str
    source_instruction_id: str
    stage: str
    opcode_name: str
    opcode_value: int
    unit_inst_type: int
    latency: int
    block_idx: int
    end_inst: bool
    imms: tuple[int, int, int]
    extra_fields: tuple[int, int, int]
    component_byte_offset: int
    record_size_bytes: int = INST_RECORD_SIZE_BYTES
    component_name: str = "insts_file.bin"
    vendor_inst_mode: VendorInstMode = "native_symbolic"
    component_semantics: str = "structural_smoke_only"
    legacy_inst: LegacyInst | None = None

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "global_row_index": self.global_row_index,
            "component_name": self.component_name,
            "component_byte_offset": self.component_byte_offset,
            "record_size_bytes": self.record_size_bytes,
            "local_pc": self.local_pc,
            "pe": self.pe,
            "pe_index": self.pe_index,
            "processor": self.processor,
            "vendor_exeblock_id": self.vendor_exeblock_id,
            "instruction_layout_row_id": self.instruction_layout_row_id,
            "source_instruction_id": self.source_instruction_id,
            "stage": self.stage,
            "opcode_name": self.opcode_name,
            "opcode_value": self.opcode_value,
            "unit_inst_type": self.unit_inst_type,
            "latency": self.latency,
            "block_idx": self.block_idx,
            "end_inst": self.end_inst,
            "imms": list(self.imms),
            "extra_fields": list(self.extra_fields),
            "vendor_inst_mode": self.vendor_inst_mode,
            "component_semantics": self.component_semantics,
            "functional_encoding": self.legacy_inst is not None,
            "legacy_inst": (
                {
                    "op_name": self.legacy_inst.op_name,
                    "opcode": self.legacy_inst.opcode,
                    "unit_inst_type": self.legacy_inst.unit_inst_type,
                    "latency": self.legacy_inst.latency,
                    "src_operands_idx": list(self.legacy_inst.src_operands_idx),
                    "dst_operands_idx": list(self.legacy_inst.dst_operands_idx),
                    "dst_pes_pos": [list(pos) for pos in self.legacy_inst.dst_pes_pos],
                    "iter_exe_cond": self.legacy_inst.iter_exe_cond,
                    "forwarding_bits": list(self.legacy_inst.forwarding_bits),
                    "bypass_bits": list(self.legacy_inst.bypass_bits),
                }
                if self.legacy_inst is not None
                else None
            ),
            "binary_encoded": False,
        }


@dataclass(frozen=True)
class ProgramBinReverseMap:
    """Stable provenance hooks from future byte rows back to IR rows."""

    instruction_layout_to_vendor_range: dict[str, str] = field(default_factory=dict)
    bin_row_to_vendor_row: dict[str, str] = field(default_factory=dict)
    status: str = "skeleton_not_emitted"

    def to_plan(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "instruction_layout_to_vendor_range": dict(
                sorted(self.instruction_layout_to_vendor_range.items())
            ),
            "bin_row_to_vendor_row": dict(sorted(self.bin_row_to_vendor_row.items())),
            "byte_row_reverse_map_complete": False,
        }


@dataclass(frozen=True)
class ProgramBinValidationReport:
    """Validation gates for binary-facing row planning."""

    folded_vendor_report_consumed: bool
    folded_abi_contract_ready: bool
    variant_binding_ready: bool
    address_variant_binding_ready: bool
    instance_conf_rows_ready: bool
    task_conf_rows_ready: bool
    exe_block_conf_rows_ready: bool
    subtask_conf_rows_ready: bool
    embedded_exe_block_rows_consistent: bool
    instruction_layout_ready: bool
    instance_conf_address_unit_is_bytes: bool
    task_successor_policy_explicit: bool
    full_component_emission_allowed: bool
    binary_components_emitted: bool
    complete_runtime_package_emitted: bool
    blocking_reasons: tuple[str, ...]

    def to_plan(self) -> dict[str, Any]:
        return {
            "folded_vendor_report_consumed": self.folded_vendor_report_consumed,
            "folded_abi_contract_ready": self.folded_abi_contract_ready,
            "variant_binding_ready": self.variant_binding_ready,
            "address_variant_binding_ready": self.address_variant_binding_ready,
            "instance_conf_rows_ready": self.instance_conf_rows_ready,
            "task_conf_rows_ready": self.task_conf_rows_ready,
            "exe_block_conf_rows_ready": self.exe_block_conf_rows_ready,
            "subtask_conf_rows_ready": self.subtask_conf_rows_ready,
            "embedded_exe_block_rows_consistent": (
                self.embedded_exe_block_rows_consistent
            ),
            "instruction_layout_ready": self.instruction_layout_ready,
            "instance_conf_address_unit_is_bytes": self.instance_conf_address_unit_is_bytes,
            "task_successor_policy_explicit": self.task_successor_policy_explicit,
            "full_component_emission_allowed": self.full_component_emission_allowed,
            "binary_components_emitted": self.binary_components_emitted,
            "complete_runtime_package_emitted": self.complete_runtime_package_emitted,
            "blocking_reasons": list(self.blocking_reasons),
        }


@dataclass
class ProgramBinRows:
    """Symbolic binary-row plan derived from folded ``ProgramVendorABI``."""

    chip: str
    source_program: str
    source_ir: str
    folded_vendor_report: dict[str, Any]
    task_successor_policy: TaskSuccessorPolicy
    instances_conf_mem_based_addr_unit: InstancesConfMemBasedAddrUnit
    variant_bindings: dict[str, VendorLoopVariantBinding]
    instruction_layout_rows: dict[str, InstructionLayoutRow]
    inst_rows: dict[str, InstBinRow]
    exe_block_rows: dict[str, ExeBlockConfBinRow]
    instance_rows: dict[str, InstanceConfBinRow]
    task_rows: dict[str, TaskConfBinRow]
    subtask_rows: dict[str, SubtaskConfBinRow]
    reverse_map: ProgramBinReverseMap
    validation_report: ProgramBinValidationReport
    source_counts: dict[str, int | str]

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "ir": "program_bin_rows",
            "backend": "dfu3500_symbolic_binary_rows",
            "chip": self.chip,
            "source_program": self.source_program,
            "source_ir": self.source_ir,
            "layering_policy": (
                "program_bin_rows_consumes_folded_vendor_abi;"
                "does_not_rediscover_loop_route_or_dependency_semantics;"
                "full_byte_emission_blocked_until_variant_binding_and_instruction_layout"
            ),
            "binary_policy": _checked_binary_policy(
                {
                    "schema_version": _BINARY_POLICY_SCHEMA_VERSION,
                    "component_bytes_emitted": False,
                    "complete_runtime_package_emitted": False,
                    "program_bin_role": "row_planning_only",
                    "vendor_inst_modes": sorted(
                        {row.vendor_inst_mode for row in self.inst_rows.values()}
                    ),
                    "native_symbolic_semantics": "structural_smoke_only",
                }
            ),
            "compat_diagnostics": {
                "schema_version": "compat_diagnostics.v1",
                "legacy_gemm_compat_semantics": (
                    "real_vendor_inst_t_encoding_runtime_validation_blocked"
                ),
                "legacy_template_compat_semantics": (
                    "real_vendor_inst_t_encoding_without_gemm_resource_replay"
                ),
            },
            "task_successor_policy": self.task_successor_policy,
            "instances_conf_mem_based_addr_unit": self.instances_conf_mem_based_addr_unit,
            "folded_vendor_report": self.folded_vendor_report,
            "variant_bindings": {
                row_id: row.to_plan()
                for row_id, row in sorted(self.variant_bindings.items())
            },
            "variant_binding_report": self._variant_binding_report(),
            "instruction_layout_rows": {
                row_id: row.to_plan()
                for row_id, row in sorted(self.instruction_layout_rows.items())
            },
            "inst_rows": {
                row_id: row.to_plan()
                for row_id, row in sorted(self.inst_rows.items())
            },
            "inst_conf_report": self._inst_conf_report(),
            "exe_block_rows": {
                row_id: row.to_plan()
                for row_id, row in sorted(self.exe_block_rows.items())
            },
            "exe_block_conf_report": self._exe_block_conf_report(),
            "instance_rows": {
                row_id: row.to_plan()
                for row_id, row in sorted(self.instance_rows.items())
            },
            "instance_conf_report": self._instance_conf_report(),
            "task_rows": {
                row_id: row.to_plan()
                for row_id, row in sorted(self.task_rows.items())
            },
            "task_conf_report": self._task_conf_report(),
            "subtask_rows": {
                row_id: row.to_plan()
                for row_id, row in sorted(self.subtask_rows.items())
            },
            "subtask_conf_report": self._subtask_conf_report(),
            "reverse_map": self.reverse_map.to_plan(),
            "validation": self.validation_report.to_plan(),
            "totals": self._totals(),
        }

    def _totals(self) -> dict[str, Any]:
        totals = dict(sorted(self.source_counts.items()))
        totals.update(
            {
                "variant_binding_count": len(self.variant_bindings),
                "instruction_layout_row_count": len(self.instruction_layout_rows),
                "inst_bin_row_count": len(self.inst_rows),
                "exe_block_bin_row_count": len(self.exe_block_rows),
                "instance_conf_bin_row_count": len(self.instance_rows),
                "task_conf_bin_row_count": len(self.task_rows),
                "subtask_conf_bin_row_count": len(self.subtask_rows),
                "bin_component_count": 0,
                "full_emission_blocked": not self.validation_report.full_component_emission_allowed,
            }
        )
        return totals

    def _inst_conf_report(self) -> dict[str, Any]:
        stage_counts: dict[str, int] = {}
        pe_counts: dict[str, int] = {}
        mode_counts: dict[str, int] = {}
        semantics_counts: dict[str, int] = {}
        functional_count = 0
        for row in self.inst_rows.values():
            stage_counts[row.stage] = stage_counts.get(row.stage, 0) + 1
            pe_counts[row.pe] = pe_counts.get(row.pe, 0) + 1
            mode_counts[row.vendor_inst_mode] = mode_counts.get(row.vendor_inst_mode, 0) + 1
            semantics_counts[row.component_semantics] = (
                semantics_counts.get(row.component_semantics, 0) + 1
            )
            if row.legacy_inst is not None:
                functional_count += 1
        return {
            "row_count": len(self.inst_rows),
            "record_size_bytes": INST_RECORD_SIZE_BYTES,
            "capacity": INST_CAPACITY,
            "padded_component_size_bytes": INST_CAPACITY * INST_RECORD_SIZE_BYTES,
            "max_inst_amount_per_pe": MAX_INST_AMOUNT_PER_PE,
            "stage_counts": dict(sorted(stage_counts.items())),
            "pe_instruction_counts": dict(sorted(pe_counts.items())),
            "vendor_inst_mode_counts": dict(sorted(mode_counts.items())),
            "component_semantics_counts": dict(sorted(semantics_counts.items())),
            "functional_inst_row_count": functional_count,
            "functional_encoding": functional_count == len(self.inst_rows)
            and bool(self.inst_rows),
            "component_bytes_emitted": False,
        }

    def _variant_binding_report(self) -> dict[str, Any]:
        role_counts: dict[str, int] = {}
        target_counts: dict[str, int] = {}
        proof_counts: dict[str, int] = {}
        for binding in self.variant_bindings.values():
            role_counts[binding.operand_role] = role_counts.get(binding.operand_role, 0) + 1
            target_counts[binding.binding_target_kind] = (
                target_counts.get(binding.binding_target_kind, 0) + 1
            )
            proof_counts[binding.target_proof_status] = (
                proof_counts.get(binding.target_proof_status, 0) + 1
            )
        return {
            "binding_count": len(self.variant_bindings),
            "operand_role_counts": dict(sorted(role_counts.items())),
            "binding_target_kind_counts": dict(sorted(target_counts.items())),
            "target_proof_status_counts": dict(sorted(proof_counts.items())),
            "address_equation_count": sum(
                1
                for binding in self.variant_bindings.values()
                if binding.effective_address_expr
            ),
            "address_equation_audit_status": (
                "legacy_base_addr_equations_symbolically_audited"
                if self.variant_bindings
                else "not_started"
            ),
        }

    def _task_conf_report(self) -> dict[str, Any]:
        start_count = sum(1 for row in self.task_rows.values() if row.is_exe_start)
        end_count = sum(1 for row in self.task_rows.values() if row.is_exe_end)
        successor_edges = sum(len(row.successor_task_indices) for row in self.task_rows.values())
        return {
            "row_count": len(self.task_rows),
            "record_size_bytes": TASK_CONF_RECORD_SIZE_BYTES,
            "capacity": TASK_CONF_CAPACITY,
            "padded_component_size_bytes": TASK_CONF_CAPACITY * TASK_CONF_RECORD_SIZE_BYTES,
            "task_successor_policy": self.task_successor_policy,
            "start_task_count": start_count,
            "end_task_count": end_count,
            "successor_edge_count": successor_edges,
            "subtask_slot_count": TASK_SUBTASK_SLOT_COUNT,
            "successor_slot_count": TASK_SUCCESSOR_SLOT_COUNT,
            "component_bytes_emitted": False,
        }

    def _exe_block_conf_report(self) -> dict[str, Any]:
        role_counts: dict[str, int] = {}
        stage_counts: dict[str, int] = {}
        max_predecessors = 0
        max_successors = 0
        for row in self.exe_block_rows.values():
            role_counts[row.role] = role_counts.get(row.role, 0) + 1
            max_predecessors = max(max_predecessors, len(row.predecessor_ids))
            max_successors = max(max_successors, len(row.successor_ids))
            for stage, count in row.stage_instruction_counts.items():
                stage_counts[stage] = stage_counts.get(stage, 0) + count
        return {
            "row_count": len(self.exe_block_rows),
            "record_size_bytes": EXEBLOCK_CONF_RECORD_SIZE_BYTES,
            "capacity": EXEBLOCK_CONF_CAPACITY,
            "padded_component_size_bytes": (
                EXEBLOCK_CONF_CAPACITY * EXEBLOCK_CONF_RECORD_SIZE_BYTES
            ),
            "role_counts": dict(sorted(role_counts.items())),
            "stage_instruction_counts": dict(sorted(stage_counts.items())),
            "edge_slot_count": EXEBLOCK_EDGE_SLOT_COUNT,
            "max_predecessor_count": max_predecessors,
            "max_successor_count": max_successors,
            "component_bytes_emitted": False,
        }

    def _subtask_conf_report(self) -> dict[str, Any]:
        role_counts: dict[str, int] = {}
        valid_exe_blocks_total = 0
        max_valid_exe_blocks = 0
        for row in self.subtask_rows.values():
            role_counts[row.role] = role_counts.get(row.role, 0) + 1
            valid_exe_blocks_total += row.valid_exe_blocks
            max_valid_exe_blocks = max(max_valid_exe_blocks, row.valid_exe_blocks)
        return {
            "row_count": len(self.subtask_rows),
            "record_size_bytes": SUBTASK_CONF_RECORD_SIZE_BYTES,
            "capacity": SUBTASK_CONF_CAPACITY,
            "padded_component_size_bytes": (
                SUBTASK_CONF_CAPACITY * SUBTASK_CONF_RECORD_SIZE_BYTES
            ),
            "embedded_exe_block_slot_count": SUBTASK_EMBEDDED_EXEBLOCK_SLOT_COUNT,
            "role_counts": dict(sorted(role_counts.items())),
            "valid_exe_blocks_total": valid_exe_blocks_total,
            "max_valid_exe_blocks": max_valid_exe_blocks,
            "embedded_exe_block_source": "ProgramBinRows.exe_block_rows",
            "component_bytes_emitted": False,
        }

    def _instance_conf_report(self) -> dict[str, Any]:
        filled_slot_counts: dict[int, int] = {}
        row_kind_counts: dict[str, int] = {}
        semantic_active_count = 0
        for row in self.instance_rows.values():
            row_kind_counts[row.row_kind] = row_kind_counts.get(row.row_kind, 0) + 1
            semantic_active_count += int(row.is_semantic_active)
            for slot, word in enumerate(row.base_addr_words):
                if word != UNUSED_BASE_ADDR_WORD:
                    filled_slot_counts[slot] = filled_slot_counts.get(slot, 0) + 1
        return {
            "row_count": len(self.instance_rows),
            "physical_instance_row_count": len(self.instance_rows),
            "semantic_active_instance_row_count": semantic_active_count,
            "role_filled_window_row_count": (
                semantic_active_count + row_kind_counts.get("role_filled_window", 0)
            ),
            "nonsemantic_role_filled_window_row_count": row_kind_counts.get(
                "role_filled_window", 0
            ),
            "inactive_filler_row_count": row_kind_counts.get("inactive_filler", 0),
            "row_kind_counts": dict(sorted(row_kind_counts.items())),
            "legacy_fixed_window_layout": True,
            "record_size_bytes": INSTANCE_CONF_RECORD_SIZE_BYTES,
            "capacity": INSTANCE_CONF_CAPACITY,
            "padded_component_size_bytes": (
                INSTANCE_CONF_CAPACITY * INSTANCE_CONF_RECORD_SIZE_BYTES
            ),
            "instances_conf_mem_based_addr_unit": self.instances_conf_mem_based_addr_unit,
            "unused_slot_sentinel": f"0x{UNUSED_BASE_ADDR_WORD:08x}",
            "filled_slot_counts": {
                str(slot): count for slot, count in sorted(filled_slot_counts.items())
            },
            "component_bytes_emitted": False,
        }


def lower_vendor_abi_to_program_bin_rows(
    vendor_abi: ProgramVendorABI,
    *,
    vendor_inst_mode: VendorInstMode = "native_symbolic",
    task_successor_policy: TaskSuccessorPolicy = "independent_start_end",
) -> ProgramBinRows:
    """Create binary-facing row plans without emitting component bytes."""

    variant_bindings = _build_variant_bindings(vendor_abi)
    instance_rows = _build_instance_conf_rows(
        vendor_abi,
        variant_bindings,
        vendor_inst_mode,
    )
    task_rows = _build_task_conf_rows(vendor_abi, task_successor_policy)
    instruction_layout_rows = _build_instruction_layout_rows(vendor_abi, vendor_inst_mode)
    exe_block_rows = _build_exe_block_conf_rows(
        vendor_abi,
        instruction_layout_rows,
        vendor_inst_mode,
    )
    inst_rows = _build_inst_rows(
        instruction_layout_rows,
        exe_block_rows,
        vendor_abi.template_bound_instructions,
        vendor_inst_mode,
        task_resource_replayed=_task_resource_replay_applied(vendor_abi),
    )
    subtask_rows = _build_subtask_conf_rows(
        vendor_abi,
        instance_rows,
        exe_block_rows,
    )
    reverse_map = ProgramBinReverseMap(
        instruction_layout_to_vendor_range={
            row.id: row.vendor_instruction_range_id
            for row in instruction_layout_rows.values()
        },
        bin_row_to_vendor_row={
            row.id: row.vendor_subtask_id
            for row in instance_rows.values()
        }
        | {
            row.id: row.task_id
            for row in task_rows.values()
        }
        | {
            row.id: row.vendor_exeblock_id
            for row in exe_block_rows.values()
        }
        | {
            row.id: row.source_instruction_id
            for row in inst_rows.values()
        }
        | {
            row.id: row.vendor_subtask_id
            for row in subtask_rows.values()
        }
    )
    validation_report = _build_validation_report(
        vendor_abi,
        variant_bindings=variant_bindings,
        instance_rows=instance_rows,
        task_rows=task_rows,
        exe_block_rows=exe_block_rows,
        subtask_rows=subtask_rows,
        instruction_layout_rows=instruction_layout_rows,
        task_successor_policy=task_successor_policy,
    )
    return ProgramBinRows(
        chip=vendor_abi.chip,
        source_program=vendor_abi.source_program,
        source_ir="program_vendor_abi",
        folded_vendor_report=dict(vendor_abi.folded_vendor_report),
        task_successor_policy=task_successor_policy,
        instances_conf_mem_based_addr_unit="bytes",
        variant_bindings=variant_bindings,
        instruction_layout_rows=instruction_layout_rows,
        inst_rows=inst_rows,
        exe_block_rows=exe_block_rows,
        instance_rows=instance_rows,
        task_rows=task_rows,
        subtask_rows=subtask_rows,
        reverse_map=reverse_map,
        validation_report=validation_report,
        source_counts=_source_counts(
            vendor_abi,
            vendor_inst_mode=vendor_inst_mode,
        ),
    )


def _build_instruction_layout_rows(
    vendor_abi: ProgramVendorABI,
    vendor_inst_mode: VendorInstMode,
) -> dict[str, InstructionLayoutRow]:
    if _uses_template_bound_instruction_rows(vendor_inst_mode):
        return _build_template_instruction_layout_rows(vendor_abi, vendor_inst_mode)

    rows: dict[str, InstructionLayoutRow] = {}
    for index, (range_id, range_row) in enumerate(
        sorted(vendor_abi.instruction_ranges.items())
    ):
        row_id = f"instruction_layout:{index:06d}"
        rows[row_id] = InstructionLayoutRow(
            id=row_id,
            vendor_instruction_range_id=range_id,
            vendor_exeblock_id=range_row.vendor_exeblock_id,
            processor=range_row.processor,
            pe=range_row.pe,
            stage=range_row.stage,
            start_pc=range_row.start_pc,
            end_pc=range_row.end_pc,
            instruction_ids=range_row.instruction_ids,
            vendor_inst_mode=vendor_inst_mode,
        )
    return rows


def _build_template_instruction_layout_rows(
    vendor_abi: ProgramVendorABI,
    vendor_inst_mode: VendorInstMode,
) -> dict[str, InstructionLayoutRow]:
    rows: dict[str, InstructionLayoutRow] = {}
    next_pc_by_processor: dict[str, int] = {}
    range_rows = sorted(
        vendor_abi.instruction_ranges.items(),
        key=lambda item: (
            _pe_index_for_processor(item[1].processor),
            item[1].start_pc,
            item[0],
        ),
    )
    for index, (range_id, range_row) in enumerate(range_rows):
        template_instruction_ids = range_row.template_bound_instruction_ids
        if not template_instruction_ids:
            raise ValueError(
                f"{vendor_inst_mode} requires template-bound instruction ids "
                f"for vendor range {range_id}"
            )
        template_stages = _template_bound_stage_runs(
            template_instruction_ids,
            vendor_abi,
        )
        for stage, stage_instruction_ids in template_stages:
            start_pc = next_pc_by_processor.get(range_row.processor, 0)
            end_pc = start_pc + len(stage_instruction_ids)
            next_pc_by_processor[range_row.processor] = end_pc
            if end_pc > MAX_INST_AMOUNT_PER_PE:
                raise ValueError(
                    f"legacy GEMM instruction image exceeds PE capacity for "
                    f"{range_row.processor}: {end_pc} > {MAX_INST_AMOUNT_PER_PE}"
                )
            row_id = f"instruction_layout:{len(rows):06d}"
            rows[row_id] = InstructionLayoutRow(
                id=row_id,
                vendor_instruction_range_id=range_id,
                vendor_exeblock_id=range_row.vendor_exeblock_id,
                processor=range_row.processor,
                pe=range_row.pe,
                stage=stage,
                start_pc=start_pc,
                end_pc=end_pc,
                instruction_ids=tuple(stage_instruction_ids),
                vendor_inst_mode=vendor_inst_mode,
                component_semantics=f"{vendor_inst_mode}_micro_block_templates",
                complete_runtime_package_semantics=False,
            )
    return rows


def _build_inst_rows(
    instruction_layout_rows: dict[str, InstructionLayoutRow],
    exe_block_rows: dict[str, ExeBlockConfBinRow],
    template_bound_instructions: dict[str, TemplateBoundInstruction],
    vendor_inst_mode: VendorInstMode,
    *,
    task_resource_replayed: bool = False,
) -> dict[str, InstBinRow]:
    rows: dict[str, InstBinRow] = {}
    exe_block_by_vendor_id = {
        row.vendor_exeblock_id: row
        for row in exe_block_rows.values()
    }
    compute_exe_block_by_task_processor = {
        (row.task_index, row.processor): row
        for row in exe_block_rows.values()
        if row.role == "k_stream"
        and "compute_update" in row.source_tile_micro_block_kinds
    }
    receiver_operand_idx_by_task_processor_tag: dict[tuple[int, str, str], int] = {}
    if vendor_inst_mode == "legacy_gemm_compat" and not task_resource_replayed:
        receiver_operand_idx_by_task_processor_tag = _legacy_operand_idx_by_task_processor_tag(
            instruction_layout_rows,
            exe_block_rows,
            template_bound_instructions,
        )
    for layout_row in sorted(
        instruction_layout_rows.values(),
        key=lambda row: (_pe_index_for_processor(row.processor), row.start_pc, row.id),
    ):
        exe_block = exe_block_by_vendor_id[layout_row.vendor_exeblock_id]
        for offset, source_instruction_id in enumerate(layout_row.instruction_ids):
            local_pc = layout_row.start_pc + offset
            pe_index = _pe_index_for_processor(layout_row.processor)
            global_row_index = pe_index * MAX_INST_AMOUNT_PER_PE + local_pc
            row_id = f"inst:{layout_row.pe}:pc{local_pc:04d}"
            legacy_inst = None
            if _uses_template_bound_instruction_rows(vendor_inst_mode):
                template_instruction = _template_bound_instruction(
                    source_instruction_id,
                    layout_row,
                    template_bound_instructions,
                )
                legacy_inst = template_instruction.legacy_inst.clone_with(
                    block_idx=exe_block.block_idx,
                )
            if vendor_inst_mode == "legacy_gemm_compat" and legacy_inst is not None:
                legacy_inst = _legacy_copy_inst_with_route_target(
                    legacy_inst,
                    exe_block=exe_block,
                    compute_exe_block_by_task_processor=(
                        compute_exe_block_by_task_processor
                    ),
                    operand_idx_by_task_processor_tag=(
                        receiver_operand_idx_by_task_processor_tag
                    ),
                    patch_dst_operand=not task_resource_replayed,
                )
            end_inst = offset == len(layout_row.instruction_ids) - 1
            if vendor_inst_mode == "legacy_gemm_compat":
                end_inst = False
            rows[row_id] = InstBinRow(
                id=row_id,
                global_row_index=global_row_index,
                local_pc=local_pc,
                pe=layout_row.pe,
                pe_index=pe_index,
                processor=layout_row.processor,
                vendor_exeblock_id=layout_row.vendor_exeblock_id,
                instruction_layout_row_id=layout_row.id,
                source_instruction_id=source_instruction_id,
                stage=layout_row.stage,
                opcode_name="OP_GINST",
                opcode_value=0xC1,
                unit_inst_type=_unit_inst_type_for_stage(layout_row.stage),
                latency=1,
                block_idx=exe_block.block_idx,
                end_inst=end_inst,
                imms=(
                    _stage_code(layout_row.stage),
                    exe_block.task_index,
                    exe_block.subtask_index,
                ),
                extra_fields=(
                    global_row_index,
                    local_pc,
                    exe_block.block_idx,
                ),
                component_byte_offset=global_row_index * INST_RECORD_SIZE_BYTES,
                vendor_inst_mode=vendor_inst_mode,
                component_semantics=(
                    f"{vendor_inst_mode}_micro_block_templates"
                    if legacy_inst is not None
                    else "structural_smoke_only"
                ),
                legacy_inst=legacy_inst,
            )
    return rows


def _legacy_copy_inst_with_route_target(
    inst: LegacyInst,
    *,
    exe_block: ExeBlockConfBinRow,
    compute_exe_block_by_task_processor: dict[tuple[int, str], ExeBlockConfBinRow],
    operand_idx_by_task_processor_tag: dict[tuple[int, str, str], int],
    patch_dst_operand: bool = True,
) -> LegacyInst:
    """Patch COPY/COPYT-derived route targets from vendor row provenance.

    Vendor ``fill_copy_inst`` overwrites COPY destination PE/block fields from
    the graph child node.  The CSV template only carries a placeholder
    ``dst_pe_idx``.  Our semantic route is already represented by the
    micro-block id, so use that provenance to bind COPY to the destination
    processor's compute block in the same task.
    """

    if inst.op_name != "COPY":
        return inst
    if "route_forward" not in exe_block.source_tile_micro_block_kinds:
        return inst
    endpoint_processor = _endpoint_processor_from_micro_block_ids(
        exe_block.source_tile_micro_block_ids
    )
    if endpoint_processor is None:
        return inst
    target_block = compute_exe_block_by_task_processor.get(
        (exe_block.task_index, endpoint_processor)
    )
    if target_block is None:
        return inst
    dst_operand_idx0 = None
    if patch_dst_operand:
        dst_operand_idx0 = _legacy_copy_receiver_dst_operand_idx0(
            inst,
            exe_block=exe_block,
            endpoint_processor=endpoint_processor,
            operand_idx_by_task_processor_tag=operand_idx_by_task_processor_tag,
        )
    return inst.clone_with(
        dst_pe0=_processor_to_pe_pos(endpoint_processor),
        dst_block_idx0=target_block.block_idx,
        dst_operand_idx0=dst_operand_idx0,
    )


def _task_resource_replay_applied(vendor_abi: ProgramVendorABI) -> bool:
    replay = vendor_abi.folded_vendor_report.get("task_resource_replay", {})
    return isinstance(replay, dict) and bool(replay.get("enabled"))


def _legacy_operand_idx_by_task_processor_tag(
    instruction_layout_rows: dict[str, InstructionLayoutRow],
    exe_block_rows: dict[str, ExeBlockConfBinRow],
    template_bound_instructions: dict[str, TemplateBoundInstruction],
) -> dict[tuple[int, str, str], int]:
    """Build the receiver-side tag view used by vendor ``fill_copy_inst``.

    Vendor maps COPY/COPYT destination operands through the child PE's
    ``Task_Resource``.  At this layer we already have template-bound rows for
    every executable micro-block, so preserve the first operand index observed
    for each ``(task, processor, tag)``.  COPYT expands one tensor-copy CSV row
    into four lane rows; the first row is the resource base and following rows
    are lane offsets, so first-wins mirrors ``Task_Resource::get_reg_idx``.
    """

    exe_block_by_vendor_id = {
        row.vendor_exeblock_id: row
        for row in exe_block_rows.values()
    }
    operand_idx_by_key: dict[tuple[int, str, str], int] = {}
    for layout_row in sorted(
        instruction_layout_rows.values(),
        key=lambda row: (_pe_index_for_processor(row.processor), row.start_pc, row.id),
    ):
        exe_block = exe_block_by_vendor_id[layout_row.vendor_exeblock_id]
        for instruction_id in layout_row.instruction_ids:
            inst = _template_bound_instruction(
                instruction_id,
                layout_row,
                template_bound_instructions,
            ).legacy_inst
            _record_legacy_operand_tag(
                operand_idx_by_key,
                task_index=exe_block.task_index,
                processor=layout_row.processor,
                tag=inst.src_reg_idx0_tag,
                operand_idx=inst.src_operands_idx[0],
            )
            _record_legacy_operand_tag(
                operand_idx_by_key,
                task_index=exe_block.task_index,
                processor=layout_row.processor,
                tag=inst.src_reg_idx1_tag,
                operand_idx=inst.src_operands_idx[1],
            )
            _record_legacy_operand_tag(
                operand_idx_by_key,
                task_index=exe_block.task_index,
                processor=layout_row.processor,
                tag=inst.dst_reg_idx_tag,
                operand_idx=inst.dst_operands_idx[0],
            )
    return operand_idx_by_key


def _record_legacy_operand_tag(
    operand_idx_by_key: dict[tuple[int, str, str], int],
    *,
    task_index: int,
    processor: str,
    tag: str,
    operand_idx: int,
) -> None:
    tag = str(tag).strip()
    if not tag:
        return
    operand_idx_by_key.setdefault((task_index, processor, tag), int(operand_idx))


def _legacy_copy_receiver_dst_operand_idx0(
    inst: LegacyInst,
    *,
    exe_block: ExeBlockConfBinRow,
    endpoint_processor: str,
    operand_idx_by_task_processor_tag: dict[tuple[int, str, str], int],
) -> int | None:
    tag = inst.dst_reg_idx_tag.strip()
    if not tag:
        return None
    receiver_base = operand_idx_by_task_processor_tag.get(
        (exe_block.task_index, endpoint_processor, tag)
    )
    if receiver_base is None:
        return None
    sender_base = operand_idx_by_task_processor_tag.get(
        (exe_block.task_index, exe_block.processor, tag)
    )
    lane_delta = 0
    if sender_base is not None:
        lane_delta = inst.dst_operands_idx[0] - sender_base
        if (
            lane_delta < 0
            or lane_delta % OPERANDS_PER_OPERAND_RAM != 0
            or lane_delta >= OPERANDS_PER_OPERAND_RAM * 4
        ):
            lane_delta = 0
    return int(receiver_base) + lane_delta


def _build_variant_bindings(
    vendor_abi: ProgramVendorABI,
) -> dict[str, VendorLoopVariantBinding]:
    bindings: dict[str, VendorLoopVariantBinding] = {}
    for template_id, template in sorted(vendor_abi.repeated_loop_templates.items()):
        vendor_subtask_id = _k_stream_subtask_id_for_task(
            vendor_abi,
            str(template["task_id"]),
        )
        repeat_count = int(template["repeat_count"])
        for tile_ref in template.get("loop_variant_refs", ()):
            parsed = _parse_tile_ref(str(tile_ref))
            if parsed is None:
                continue
            role = parsed["role"]
            if role not in {"A", "B"}:
                continue
            loop_index = _loop_index_for_tile_ref(parsed)
            if loop_index < 0 or loop_index >= repeat_count:
                continue
            binding_id = (
                f"variant_binding:{_sanitize_binding_id(template_id)}:"
                f"k{loop_index}:{role}"
            )
            bindings[binding_id] = _make_gemm_address_binding(
                binding_id=binding_id,
                template_id=template_id,
                vendor_subtask_id=vendor_subtask_id,
                loop_axis=str(template["loop_axis"]),
                loop_index=loop_index,
                role=role,
                tile_ref=str(tile_ref),
                parsed=parsed,
            )
    return bindings


def _build_instance_conf_rows(
    vendor_abi: ProgramVendorABI,
    variant_bindings: dict[str, VendorLoopVariantBinding],
    vendor_inst_mode: VendorInstMode,
) -> dict[str, InstanceConfBinRow]:
    bindings_by_subtask_instance: dict[tuple[str, str], list[VendorLoopVariantBinding]] = {}
    for binding in variant_bindings.values():
        key = (binding.vendor_subtask_id, binding.instance_key)
        bindings_by_subtask_instance.setdefault(key, []).append(binding)

    vendor_instances_by_subtask_instance: dict[tuple[str, str], list[str]] = {}
    for instance in vendor_abi.vendor_instances.values():
        key = (instance.vendor_subtask_id, instance.instance_key)
        vendor_instances_by_subtask_instance.setdefault(key, []).append(instance.id)

    active_subtask_by_slot = {
        (subtask.task_index, subtask.subtask_index): subtask
        for subtask in vendor_abi.vendor_subtasks.values()
    }
    semantic_instance_by_slot: dict[
        tuple[int, int, int],
        tuple[VendorSubtaskRow, str, int],
    ] = {}
    semantic_row_index = 0
    for subtask in sorted(
        vendor_abi.vendor_subtasks.values(),
        key=lambda row: (row.task_index, row.subtask_index),
    ):
        for instance_index, instance_key in enumerate(subtask.instance_keys):
            semantic_instance_by_slot[
                (subtask.task_index, subtask.subtask_index, instance_index)
            ] = (subtask, instance_key, semantic_row_index)
            semantic_row_index += 1

    gemm_profile = Dfu3500LegacyGemmProfile()
    rows: dict[str, InstanceConfBinRow] = {}
    for task_index in range(DFU3500_LEGACY_TASK_COUNT):
        for local_subtask_index in range(DFU3500_LEGACY_SUBTASK_SLOT_COUNT_PER_TASK):
            subtask = active_subtask_by_slot.get((task_index, local_subtask_index))
            for instance_index in range(DFU3500_LEGACY_INSTANCES_PER_SUBTASK_SLOT):
                global_row_index = dfu3500_legacy_instance_conf_row_index(
                    task_index,
                    local_subtask_index,
                    instance_index,
                )
                semantic_info = semantic_instance_by_slot.get(
                    (task_index, local_subtask_index, instance_index)
                )
                if semantic_info is not None:
                    semantic_subtask, instance_key, semantic_index = semantic_info
                    key = (semantic_subtask.id, instance_key)
                    source_bindings = tuple(
                        sorted(
                            binding.id
                            for binding in bindings_by_subtask_instance.get(key, ())
                        )
                    )
                    source_vendor_instance_ids = tuple(
                        sorted(vendor_instances_by_subtask_instance.get(key, ()))
                    )
                    row_id = f"instance_conf:{semantic_subtask.id}:{instance_key}"
                    vendor_subtask_id = semantic_subtask.id
                    task_id = semantic_subtask.task_id
                    row_subtask_index = semantic_subtask.subtask_index
                    row_kind: InstanceConfRowKind = "semantic_active"
                    semantic_component_byte_offset = (
                        semantic_index * INSTANCE_CONF_RECORD_SIZE_BYTES
                    )
                else:
                    source_bindings = ()
                    source_vendor_instance_ids = ()
                    row_id = (
                        "instance_conf:"
                        f"task{task_index}:slot{local_subtask_index}:i{instance_index:04d}"
                    )
                    vendor_subtask_id = (
                        subtask.id
                        if subtask is not None
                        else f"unused_subtask_slot:task{task_index}:slot{local_subtask_index}"
                    )
                    task_id = subtask.task_id if subtask is not None else f"task{task_index}"
                    row_subtask_index = local_subtask_index
                    row_kind = (
                        "role_filled_window"
                        if local_subtask_index in {0, 1, 2}
                        else "inactive_filler"
                    )
                    semantic_index = None
                    semantic_component_byte_offset = None

                base_addr_words = _legacy_instance_base_addr_words(
                    vendor_inst_mode=vendor_inst_mode,
                    task_index=task_index,
                    local_subtask_index=local_subtask_index,
                    instance_index=instance_index,
                    profile=gemm_profile,
                )
                rows[row_id] = InstanceConfBinRow(
                    id=row_id,
                    global_row_index=global_row_index,
                    task_id=task_id,
                    task_index=task_index,
                    vendor_subtask_id=vendor_subtask_id,
                    subtask_index=row_subtask_index,
                    instance_key=(
                        semantic_info[1] if semantic_info is not None else f"i{instance_index}"
                    ),
                    subtask_instance_index=instance_index,
                    base_addr_words=base_addr_words,
                    source_binding_ids=source_bindings,
                    source_vendor_instance_ids=source_vendor_instance_ids,
                    component_byte_offset=(
                        global_row_index * INSTANCE_CONF_RECORD_SIZE_BYTES
                    ),
                    physical_task_index=task_index,
                    physical_subtask_slot_index=local_subtask_index,
                    physical_instance_slot_index=instance_index,
                    row_kind=row_kind,
                    is_semantic_active=semantic_info is not None,
                    semantic_row_index=semantic_index,
                    semantic_component_byte_offset=semantic_component_byte_offset,
                )
    return rows


def _legacy_instance_base_addr_words(
    *,
    vendor_inst_mode: VendorInstMode,
    task_index: int,
    local_subtask_index: int,
    instance_index: int,
    profile: Dfu3500LegacyGemmProfile,
) -> tuple[int, int, int, int]:
    if vendor_inst_mode == "legacy_template_compat":
        if local_subtask_index == 0:
            return (
                profile.input1_base_word,
                UNUSED_BASE_ADDR_WORD,
                UNUSED_BASE_ADDR_WORD,
                UNUSED_BASE_ADDR_WORD,
            )
        if local_subtask_index in {1, 2}:
            return (
                UNUSED_BASE_ADDR_WORD,
                UNUSED_BASE_ADDR_WORD,
                profile.input3_base_word,
                UNUSED_BASE_ADDR_WORD,
            )
    return dfu3500_legacy_gemm_instance_base_addr_words(
        task_index=task_index,
        local_subtask_index=local_subtask_index,
        instance_index=instance_index,
        profile=profile,
    )


def dfu3500_legacy_instance_conf_row_index(
    task_index: int,
    local_subtask_index: int,
    instance_index: int,
) -> int:
    """Return the DFU3500/SimICT physical instance-conf table row.

    This is the CBUF ``instance_conf_info_file.bin`` physical layout:
    4 task windows, 8 subtask slots per task, and 2048 instance slots per
    subtask.  It is intentionally distinct from
    ``sub_task_conf_info_t.instances_conf_mem_based_addr``, which follows the
    legacy MICC compact active-instance order.
    """

    return (
        task_index
        * DFU3500_LEGACY_SUBTASK_SLOT_COUNT_PER_TASK
        * DFU3500_LEGACY_INSTANCES_PER_SUBTASK_SLOT
        + local_subtask_index * DFU3500_LEGACY_INSTANCES_PER_SUBTASK_SLOT
        + instance_index
    )


def dfu3500_legacy_gemm_instance_base_addr_words(
    *,
    task_index: int,
    local_subtask_index: int,
    instance_index: int,
    profile: Dfu3500LegacyGemmProfile,
) -> tuple[int, int, int, int]:
    """Return legacy GEMM ``base_addr[4]`` for one physical instance row."""

    del task_index  # Current legacy GEMM profile is task-independent.
    if local_subtask_index == 0:
        return (
            profile.input3_base_word,
            UNUSED_BASE_ADDR_WORD,
            UNUSED_BASE_ADDR_WORD,
            UNUSED_BASE_ADDR_WORD,
        )
    if local_subtask_index == 1:
        return (
            profile.input1_base_word
            + instance_index * profile.a_instance_stride_words,
            profile.input2_base_word
            + instance_index * profile.b_instance_stride_words,
            UNUSED_BASE_ADDR_WORD,
            UNUSED_BASE_ADDR_WORD,
        )
    if local_subtask_index == 2:
        return (
            profile.input3_base_word,
            UNUSED_BASE_ADDR_WORD,
            UNUSED_BASE_ADDR_WORD,
            UNUSED_BASE_ADDR_WORD,
        )
    return (
        UNUSED_BASE_ADDR_WORD,
        UNUSED_BASE_ADDR_WORD,
        UNUSED_BASE_ADDR_WORD,
        UNUSED_BASE_ADDR_WORD,
    )


def _build_task_conf_rows(
    vendor_abi: ProgramVendorABI,
    task_successor_policy: TaskSuccessorPolicy,
) -> dict[str, TaskConfBinRow]:
    if task_successor_policy == "unset":
        return {}

    task_rows = sorted(
        vendor_abi.vendor_tasks.values(),
        key=lambda row: row.task_index,
    )
    rows: dict[str, TaskConfBinRow] = {}
    for row_index, task in enumerate(task_rows):
        successor_indices = _successor_indices_for_task(
            task_index=task.task_index,
            task_count=len(task_rows),
            policy=task_successor_policy,
        )
        active_subtask_indices = tuple(
            vendor_abi.vendor_subtasks[subtask_id].subtask_index
            for subtask_id in task.active_subtask_ids
        )
        is_exe_start, is_exe_end = _task_start_end_flags(
            task_index=task.task_index,
            task_count=len(task_rows),
            policy=task_successor_policy,
        )
        bin_row_id = f"task_conf:{task.id}"
        rows[bin_row_id] = TaskConfBinRow(
            id=bin_row_id,
            global_row_index=row_index,
            task_id=task.id,
            task_index=task.task_index,
            is_exe_start=is_exe_start,
            is_exe_end=is_exe_end,
            execute_times=1,
            active_subtask_ids=task.active_subtask_ids,
            active_subtask_indices=active_subtask_indices,
            subtasks_idx_slots=_pad_legacy_micc_slots(
                active_subtask_indices,
                TASK_SUBTASK_SLOT_COUNT,
            ),
            successor_task_indices=successor_indices,
            successor_task_slots=_pad_legacy_micc_slots(
                successor_indices,
                TASK_SUCCESSOR_SLOT_COUNT,
            ),
            task_successor_policy=task_successor_policy,
            component_byte_offset=row_index * TASK_CONF_RECORD_SIZE_BYTES,
        )
    return rows


def _build_exe_block_conf_rows(
    vendor_abi: ProgramVendorABI,
    instruction_layout_rows: dict[str, InstructionLayoutRow],
    vendor_inst_mode: VendorInstMode,
) -> dict[str, ExeBlockConfBinRow]:
    layout_rows_by_exeblock: dict[str, list[InstructionLayoutRow]] = {}
    for row in instruction_layout_rows.values():
        layout_rows_by_exeblock.setdefault(row.vendor_exeblock_id, []).append(row)

    rows: dict[str, ExeBlockConfBinRow] = {}
    for vendor_row in sorted(
        vendor_abi.vendor_exeblocks.values(),
        key=lambda row: (
            _pe_index_for_processor(row.processor),
            row.pe_local_block_idx,
            row.task_index,
            row.subtask_index,
            row.id,
        ),
    ):
        layout_rows = sorted(
            layout_rows_by_exeblock.get(vendor_row.id, ()),
            key=lambda row: (row.start_pc, row.stage, row.id),
        )
        stage_instruction_counts = {
            row.stage: row.end_pc - row.start_pc
            for row in layout_rows
        }
        stage_start_pc = _canonical_exeblock_stage_start_pc(
            layout_rows,
            stage_instruction_counts,
        )
        inst_mem_based_addr = 0
        instruction_ids: tuple[str, ...] = tuple(
            instruction_id
            for row in layout_rows
            for instruction_id in row.instruction_ids
        )
        row_index = dfu3500_legacy_exeblock_conf_row_index(
            processor=vendor_row.processor,
            pe_local_block_idx=vendor_row.pe_local_block_idx,
        )
        row_id = f"exeblock_conf:{vendor_row.id}"
        rows[row_id] = ExeBlockConfBinRow(
            id=row_id,
            global_row_index=row_index,
            vendor_exeblock_id=vendor_row.id,
            source_asm_block_id=vendor_row.source_asm_block_id,
            task_id=vendor_row.task_id,
            task_index=vendor_row.task_index,
            vendor_subtask_id=vendor_row.vendor_subtask_id,
            subtask_index=vendor_row.subtask_index,
            role=vendor_row.role,
            processor=vendor_row.processor,
            pe=vendor_row.pe,
            pe_pos=vendor_row.pe_pos,
            block_idx=vendor_row.pe_local_block_idx,
            instance_key=vendor_row.instance_key,
            source_tile_micro_block_ids=vendor_row.source_tile_micro_block_ids,
            source_tile_micro_block_kinds=vendor_row.source_tile_micro_block_kinds,
            instruction_layout_row_ids=tuple(row.id for row in layout_rows),
            instruction_ids=instruction_ids,
            inst_mem_based_addr=inst_mem_based_addr,
            stage_start_pc=stage_start_pc,
            stage_instruction_counts=stage_instruction_counts,
            predecessor_ids=vendor_row.predecessor_ids,
            successor_ids=vendor_row.successor_ids,
            predecessor_slots=_pad_string_slots(
                vendor_row.predecessor_ids,
                EXEBLOCK_EDGE_SLOT_COUNT,
            ),
            successor_slots=_pad_string_slots(
                vendor_row.successor_ids,
                EXEBLOCK_EDGE_SLOT_COUNT,
            ),
            req_activations=len(vendor_row.predecessor_ids)
            + vendor_row.predecessor_overflow_count,
            child_amount=len(vendor_row.successor_ids)
            + vendor_row.successor_overflow_count,
            vendor_inst_mode=vendor_inst_mode,
            component_byte_offset=row_index * EXEBLOCK_CONF_RECORD_SIZE_BYTES,
        )
    return rows


def _canonical_exeblock_stage_start_pc(
    layout_rows: list[InstructionLayoutRow],
    stage_instruction_counts: dict[str, int],
) -> dict[str, int]:
    """Return legacy-style cumulative stage boundaries for one exeBlock.

    Vendor ``organize_block_conf`` records a start PC for every stage boundary,
    even when that stage has zero instructions.  Missing stages inherit the
    cumulative PC reached by previous stages instead of being serialized as 0.
    """

    base_pc = min((row.start_pc for row in layout_rows), default=0)
    current_pc = base_pc
    starts: dict[str, int] = {}
    for stage in ("LD", "CAL", "FLOW", "ST"):
        starts[stage] = current_pc
        current_pc += stage_instruction_counts.get(stage, 0)
    starts["END"] = current_pc
    return starts


def dfu3500_legacy_exeblock_conf_row_index(
    *,
    processor: str,
    pe_local_block_idx: int,
) -> int:
    """Return the DFU3500/SimICT physical exeBlock table row.

    Vendor ``fill_max_inst_per_pe`` pads each PE-local temporary block file to
    32 rows and then concatenates PE0..PE15 into
    ``exeblock_conf_info_file.bin``.  The physical file row is therefore
    ``pe_index * 32 + pe_local_block_idx``.  This is separate from per-subtask
    embedded exeBlock slot order inside ``sub_task_conf_info_t``.
    """

    if pe_local_block_idx < 0 or pe_local_block_idx >= DFU3500_LEGACY_EXEBLOCKS_PER_PE:
        raise ValueError(
            f"DFU3500 exeBlock slot out of range for {processor}: "
            f"{pe_local_block_idx} >= {DFU3500_LEGACY_EXEBLOCKS_PER_PE}"
        )
    return (
        _pe_index_for_processor(processor) * DFU3500_LEGACY_EXEBLOCKS_PER_PE
        + pe_local_block_idx
    )


def _build_subtask_conf_rows(
    vendor_abi: ProgramVendorABI,
    instance_rows: dict[str, InstanceConfBinRow],
    exe_block_rows: dict[str, ExeBlockConfBinRow],
) -> dict[str, SubtaskConfBinRow]:
    instance_rows_by_subtask: dict[str, list[InstanceConfBinRow]] = {}
    for row in instance_rows.values():
        if row.is_semantic_active:
            instance_rows_by_subtask.setdefault(row.vendor_subtask_id, []).append(row)

    exe_block_rows_by_subtask: dict[str, list[ExeBlockConfBinRow]] = {}
    for row in exe_block_rows.values():
        exe_block_rows_by_subtask.setdefault(row.vendor_subtask_id, []).append(row)

    subtask_ids_by_task: dict[str, tuple[str, ...]] = {
        task.id: tuple(
            sorted(
                task.active_subtask_ids,
                key=lambda subtask_id: vendor_abi.vendor_subtasks[subtask_id].subtask_index,
            )
        )
        for task in vendor_abi.vendor_tasks.values()
    }
    rows: dict[str, SubtaskConfBinRow] = {}
    for vendor_subtask in sorted(
        vendor_abi.vendor_subtasks.values(),
        key=lambda row: (row.task_index, row.subtask_index),
    ):
        task_subtask_ids = subtask_ids_by_task[vendor_subtask.task_id]
        first_subtask_id = task_subtask_ids[0]
        last_subtask_id = task_subtask_ids[-1]
        row_index = dfu3500_legacy_subtask_row_index(
            vendor_subtask.task_index,
            vendor_subtask.subtask_index,
        )
        subtask_instance_rows = tuple(
            sorted(
                instance_rows_by_subtask.get(vendor_subtask.id, ()),
                key=lambda row: row.subtask_instance_index,
            )
        )
        subtask_exe_block_rows = tuple(
            sorted(
                exe_block_rows_by_subtask.get(vendor_subtask.id, ()),
                key=lambda row: row.global_row_index,
            )
        )
        embedded_row_ids = tuple(row.id for row in subtask_exe_block_rows)
        row_id = f"subtask_conf:{vendor_subtask.id}"
        # Do not derive instances_conf_mem_based_addr from the physical
        # instance_conf_info_file.bin row index.
        #
        # Legacy MICC keeps compact instance_conf offsets in subtask rows,
        # while the physical CBUF instance table is emitted as a fixed
        # DFU3500 task/subtask/instance window.
        instances_conf_mem_based_addr = (
            subtask_instance_rows[0].semantic_component_byte_offset
            if subtask_instance_rows
            and subtask_instance_rows[0].semantic_component_byte_offset is not None
            else 0
        )
        rows[row_id] = SubtaskConfBinRow(
            id=row_id,
            global_row_index=row_index,
            vendor_subtask_id=vendor_subtask.id,
            task_id=vendor_subtask.task_id,
            task_index=vendor_subtask.task_index,
            subtask_index=vendor_subtask.subtask_index,
            role=vendor_subtask.role,
            is_exe_start=vendor_subtask.id == first_subtask_id,
            is_exe_end=vendor_subtask.id == last_subtask_id,
            instances_amount=_instances_amount(vendor_subtask),
            instances_conf_mem_based_addr=instances_conf_mem_based_addr,
            instance_conf_row_ids=tuple(row.id for row in subtask_instance_rows),
            embedded_exe_block_row_ids=embedded_row_ids,
            embedded_exe_block_slots=_pad_string_slots(
                embedded_row_ids,
                SUBTASK_EMBEDDED_EXEBLOCK_SLOT_COUNT,
            ),
            valid_exe_blocks=len(embedded_row_ids),
            repeat_mode=vendor_subtask.repeat_mode,
            repeat_semantics=vendor_subtask.repeat_semantics,
            template_instance_key=vendor_subtask.template_instance_key,
            component_byte_offset=row_index * SUBTASK_CONF_RECORD_SIZE_BYTES,
        )
    return rows


def dfu3500_legacy_subtask_row_index(
    task_index: int,
    local_subtask_index: int,
) -> int:
    """Return the DFU3500/SimICT legacy physical subtask table row.

    This is a vendor MICC ABI fact, not a generic OpenFabric subtask policy.
    Each task owns a fixed 8-row physical window in
    ``subtasks_conf_info_file.bin``.  Instance rows remain compact; do not use
    this helper for ``instance_conf_info_t`` addressing.
    """

    return (
        task_index * DFU3500_LEGACY_SUBTASK_SLOT_COUNT_PER_TASK
        + local_subtask_index
    )


def _build_validation_report(
    vendor_abi: ProgramVendorABI,
    *,
    variant_bindings: dict[str, VendorLoopVariantBinding],
    instance_rows: dict[str, InstanceConfBinRow],
    task_rows: dict[str, TaskConfBinRow],
    exe_block_rows: dict[str, ExeBlockConfBinRow],
    subtask_rows: dict[str, SubtaskConfBinRow],
    instruction_layout_rows: dict[str, InstructionLayoutRow],
    task_successor_policy: TaskSuccessorPolicy,
) -> ProgramBinValidationReport:
    folded_report = vendor_abi.folded_vendor_report
    folded_vendor_report_consumed = bool(folded_report)
    folded_abi_contract_ready = (
        folded_report.get("folded_repeat_mode") == "emit_vendor_rows"
        and folded_report.get("folded_repeat_unit") == "whole_subtask_body"
    )
    instruction_layout_ready = len(instruction_layout_rows) == len(
        vendor_abi.instruction_ranges
    )
    expected_address_binding_count = (
        len(vendor_abi.repeated_loop_templates)
        * _max_k_stream_repeat_count(vendor_abi)
        * 2
    )
    address_variant_binding_ready = (
        bool(variant_bindings)
        and len(variant_bindings) == expected_address_binding_count
        and all(
            binding.binding_target_kind == "instance_base_addr"
            and binding.target_proof_status == "legacy_confirmed"
            and binding.effective_address_expr
            for binding in variant_bindings.values()
        )
    )
    expected_semantic_instance_row_count = sum(
        _instances_amount(subtask)
        for subtask in vendor_abi.vendor_subtasks.values()
    )
    semantic_instance_row_count = sum(
        int(row.is_semantic_active)
        for row in instance_rows.values()
    )
    instance_conf_rows_ready = (
        len(instance_rows) == INSTANCE_CONF_CAPACITY
        and semantic_instance_row_count == expected_semantic_instance_row_count
        and len(instance_rows) <= INSTANCE_CONF_CAPACITY
        and all(
            len(row.base_addr_words) == 4
            and row.component_byte_offset
            == row.global_row_index * INSTANCE_CONF_RECORD_SIZE_BYTES
            for row in instance_rows.values()
        )
    )
    task_conf_rows_ready = (
        task_successor_policy != "unset"
        and len(task_rows) == len(vendor_abi.vendor_tasks)
        and len(task_rows) <= TASK_CONF_CAPACITY
        and all(
            len(row.subtasks_idx_slots) == TASK_SUBTASK_SLOT_COUNT
            and len(row.successor_task_slots) == TASK_SUCCESSOR_SLOT_COUNT
            and row.component_byte_offset == row.global_row_index * TASK_CONF_RECORD_SIZE_BYTES
            for row in task_rows.values()
        )
    )
    exe_block_conf_rows_ready = (
        len(exe_block_rows) == len(vendor_abi.vendor_exeblocks)
        and len(exe_block_rows) <= EXEBLOCK_CONF_CAPACITY
        and all(
            len(row.predecessor_slots) == EXEBLOCK_EDGE_SLOT_COUNT
            and len(row.successor_slots) == EXEBLOCK_EDGE_SLOT_COUNT
            and row.component_byte_offset
            == row.global_row_index * EXEBLOCK_CONF_RECORD_SIZE_BYTES
            and row.req_activations <= EXEBLOCK_EDGE_SLOT_COUNT
            and row.child_amount <= EXEBLOCK_EDGE_SLOT_COUNT
            for row in exe_block_rows.values()
        )
    )
    subtask_conf_rows_ready = (
        len(subtask_rows) == len(vendor_abi.vendor_subtasks)
        and len(subtask_rows) <= SUBTASK_CONF_CAPACITY
        and all(
            len(row.embedded_exe_block_slots) == SUBTASK_EMBEDDED_EXEBLOCK_SLOT_COUNT
            and row.component_byte_offset
            == row.global_row_index * SUBTASK_CONF_RECORD_SIZE_BYTES
            and row.valid_exe_blocks == len(row.embedded_exe_block_row_ids)
            for row in subtask_rows.values()
        )
    )
    embedded_exe_block_rows_consistent = all(
        exe_block_row_id in exe_block_rows
        for row in subtask_rows.values()
        for exe_block_row_id in row.embedded_exe_block_row_ids
    ) and sum(len(row.embedded_exe_block_row_ids) for row in subtask_rows.values()) == len(
        exe_block_rows
    )
    variant_binding_ready = (
        folded_report.get("variant_binding_status") == "binary_bound"
        and address_variant_binding_ready
    )
    task_successor_policy_explicit = task_successor_policy != "unset"
    full_component_emission_allowed = (
        folded_vendor_report_consumed
        and folded_abi_contract_ready
        and variant_binding_ready
        and instance_conf_rows_ready
        and task_conf_rows_ready
        and exe_block_conf_rows_ready
        and subtask_conf_rows_ready
        and embedded_exe_block_rows_consistent
        and instruction_layout_ready
        and task_successor_policy_explicit
    )

    blocking_reasons: list[str] = []
    if not folded_vendor_report_consumed:
        blocking_reasons.append("folded_vendor_report_missing")
    if not folded_abi_contract_ready:
        blocking_reasons.append("folded_vendor_abi_contract_not_ready")
    if not variant_binding_ready:
        variant_status = folded_report.get("variant_binding_status", "missing")
        blocking_reasons.append(f"variant_binding_{variant_status}")
    if not address_variant_binding_ready:
        blocking_reasons.append("address_variant_binding_incomplete")
    blocking_reasons.append("route_visibility_variant_binding_not_started")
    if not instance_conf_rows_ready:
        blocking_reasons.append("instance_conf_rows_incomplete")
    if not task_conf_rows_ready:
        blocking_reasons.append("task_conf_rows_incomplete")
    if not exe_block_conf_rows_ready:
        blocking_reasons.append("exe_block_conf_rows_incomplete")
    if not subtask_conf_rows_ready:
        blocking_reasons.append("subtask_conf_rows_incomplete")
    if not embedded_exe_block_rows_consistent:
        blocking_reasons.append("embedded_exe_block_rows_inconsistent")
    if not instruction_layout_ready:
        blocking_reasons.append("instruction_layout_missing_or_incomplete")
    if not task_successor_policy_explicit:
        blocking_reasons.append("task_successor_policy_unset")
    blocking_reasons.append("component_serializers_not_started")

    return ProgramBinValidationReport(
        folded_vendor_report_consumed=folded_vendor_report_consumed,
        folded_abi_contract_ready=folded_abi_contract_ready,
        variant_binding_ready=variant_binding_ready,
        address_variant_binding_ready=address_variant_binding_ready,
        instance_conf_rows_ready=instance_conf_rows_ready,
        task_conf_rows_ready=task_conf_rows_ready,
        exe_block_conf_rows_ready=exe_block_conf_rows_ready,
        subtask_conf_rows_ready=subtask_conf_rows_ready,
        embedded_exe_block_rows_consistent=embedded_exe_block_rows_consistent,
        instruction_layout_ready=instruction_layout_ready,
        instance_conf_address_unit_is_bytes=True,
        task_successor_policy_explicit=task_successor_policy_explicit,
        full_component_emission_allowed=full_component_emission_allowed,
        binary_components_emitted=False,
        complete_runtime_package_emitted=False,
        blocking_reasons=tuple(blocking_reasons),
    )


def _source_counts(
    vendor_abi: ProgramVendorABI,
    *,
    vendor_inst_mode: VendorInstMode,
) -> dict[str, int | str]:
    counts: dict[str, int | str] = {
        "source_vendor_task_count": len(vendor_abi.vendor_tasks),
        "source_vendor_subtask_count": len(vendor_abi.vendor_subtasks),
        "source_vendor_instance_count": len(vendor_abi.vendor_instances),
        "source_vendor_exeblock_count": len(vendor_abi.vendor_exeblocks),
        "source_vendor_instruction_range_count": len(vendor_abi.instruction_ranges),
        "source_vendor_graph_edge_count": len(vendor_abi.vendor_graph_edges),
        "source_repeated_loop_template_count": len(vendor_abi.repeated_loop_templates),
        "effective_subtask_instance_count": sum(
            _instances_amount(subtask)
            for subtask in vendor_abi.vendor_subtasks.values()
        ),
        "effective_k_stream_repeated_execution_count": sum(
            _instances_amount(subtask)
            for subtask in vendor_abi.vendor_subtasks.values()
            if subtask.role == "k_stream"
        ),
    }
    if vendor_inst_mode == "legacy_gemm_compat":
        counts.update(
            {
                "legacy_runtime_projection": "full_vendor_task_set",
                "emitted_vendor_task_count": len(vendor_abi.vendor_tasks),
                "emitted_vendor_subtask_count": len(vendor_abi.vendor_subtasks),
                "emitted_vendor_exeblock_count": len(vendor_abi.vendor_exeblocks),
            }
        )
    return counts


def _uses_template_bound_instruction_rows(vendor_inst_mode: VendorInstMode) -> bool:
    return vendor_inst_mode in {"legacy_gemm_compat", "legacy_template_compat"}


def _instances_amount(subtask: VendorSubtaskRow) -> int:
    if subtask.instances_amount_override is not None:
        return subtask.instances_amount_override
    return len(subtask.instance_keys)


def _k_stream_subtask_id_for_task(vendor_abi: ProgramVendorABI, task_id: str) -> str:
    matches = [
        subtask.id
        for subtask in vendor_abi.vendor_subtasks.values()
        if subtask.task_id == task_id and subtask.role == "k_stream"
    ]
    if len(matches) != 1:
        raise ValueError(f"expected one k_stream subtask for {task_id}, got {matches}")
    return matches[0]


def _parse_tile_ref(tile_ref: str) -> dict[str, Any] | None:
    parts = tile_ref.split(":")
    if len(parts) != 5 or parts[0] != "tile":
        return None
    try:
        coord0 = int(parts[3])
        coord1 = int(parts[4])
    except ValueError:
        return None
    return {
        "logical_tensor_id": parts[1],
        "role": parts[2],
        "coord0": coord0,
        "coord1": coord1,
    }


def _loop_index_for_tile_ref(parsed: dict[str, Any]) -> int:
    role = parsed["role"]
    if role == "A":
        return int(parsed["coord1"]) // 64
    if role == "B":
        return int(parsed["coord0"]) // 64
    return -1


def _make_gemm_address_binding(
    *,
    binding_id: str,
    template_id: str,
    vendor_subtask_id: str,
    loop_axis: str,
    loop_index: int,
    role: str,
    tile_ref: str,
    parsed: dict[str, Any],
) -> VendorLoopVariantBinding:
    if role == "A":
        slot = 0
        base_word = loop_index * 0x20
        immediate_word_offset = int(parsed["coord0"]) * 0x80
        logical_address_expr = f"A[k{loop_index}, m_start={parsed['coord0']}]"
        base_expr = f"0x00000 + k_index*0x20 = 0x{base_word:05x}"
        immediate_expr = f"m_start*0x80 = 0x{immediate_word_offset:05x}"
    else:
        slot = 1
        base_word = 0x10000 + loop_index * 0x4000
        immediate_word_offset = int(parsed["coord1"]) // 2
        logical_address_expr = f"B[k{loop_index}, n_start={parsed['coord1']}]"
        base_expr = f"0x10000 + k_index*0x4000 = 0x{base_word:05x}"
        immediate_expr = f"n_start/2 = 0x{immediate_word_offset:05x}"

    effective_word = base_word + immediate_word_offset
    effective_address_expr = (
        f"4 * (base_addr_word[{slot}]={base_expr} + "
        f"imm_word_offset={immediate_expr}) = 0x{effective_word * 4:08x} bytes"
    )

    return VendorLoopVariantBinding(
        id=binding_id,
        template_id=template_id,
        vendor_subtask_id=vendor_subtask_id,
        instance_key=f"k{loop_index}",
        loop_axis=loop_axis,
        loop_index=loop_index,
        source_tile_refs=(tile_ref,),
        operand_role=role,
        base_addr_slot_bindings={slot: base_expr},
        base_addr_word_bindings={slot: base_word},
        immediate_bindings={"word_offset": immediate_expr},
        binding_target_kind="instance_base_addr",
        logical_address_expr=logical_address_expr,
        effective_address_expr=effective_address_expr,
        target_proof_status="legacy_confirmed",
    )


def _max_k_stream_repeat_count(vendor_abi: ProgramVendorABI) -> int:
    repeat_counts = [
        _instances_amount(subtask)
        for subtask in vendor_abi.vendor_subtasks.values()
        if subtask.role == "k_stream"
    ]
    if not repeat_counts:
        return 0
    return max(repeat_counts)


def _successor_indices_for_task(
    *,
    task_index: int,
    task_count: int,
    policy: TaskSuccessorPolicy,
) -> tuple[int, ...]:
    if policy == "legacy_chain":
        if task_index + 1 < task_count:
            return (task_index + 1,)
        return ()
    if policy in {"independent_start_end", "single_task", "unset"}:
        return ()
    raise ValueError(f"unknown task successor policy: {policy}")


def _task_start_end_flags(
    *,
    task_index: int,
    task_count: int,
    policy: TaskSuccessorPolicy,
) -> tuple[bool, bool]:
    if policy == "legacy_chain":
        return task_index == 0, task_index == task_count - 1
    if policy == "independent_start_end":
        return True, True
    if policy == "single_task":
        return task_index == 0, task_index == 0
    if policy == "unset":
        return False, False
    raise ValueError(f"unknown task successor policy: {policy}")


def _pad_slots(values: tuple[int, ...], slot_count: int) -> tuple[int, ...]:
    if len(values) > slot_count:
        raise ValueError(f"too many values for {slot_count} slots: {values}")
    return values + (UNUSED_TASK_FIELD,) * (slot_count - len(values))


def _pad_legacy_micc_slots(values: tuple[int, ...], slot_count: int) -> tuple[int, ...]:
    """Pad DFU3500 legacy MICC task/subtask slots with zero bytes.

    Legacy GEMM relies on count fields to distinguish active entries from
    zero-filled unused slots, even though zero can also be a valid row index.
    Keep this policy local to MICC byte compatibility; do not use it for graph
    semantics.
    """

    if len(values) > slot_count:
        raise ValueError(f"too many values for {slot_count} slots: {values}")
    return values + (0,) * (slot_count - len(values))


def _pad_string_slots(values: tuple[str, ...], slot_count: int) -> tuple[str, ...]:
    if len(values) > slot_count:
        raise ValueError(f"too many values for {slot_count} slots: {values}")
    return values + (UNUSED_EXEBLOCK_FIELD,) * (slot_count - len(values))


def _template_bound_stage_runs(
    instruction_ids: tuple[str, ...],
    vendor_abi: ProgramVendorABI,
) -> tuple[tuple[str, tuple[str, ...]], ...]:
    runs: list[tuple[str, list[str]]] = []
    for instruction_id in instruction_ids:
        instruction = _template_bound_instruction(
            instruction_id,
            None,
            vendor_abi.template_bound_instructions,
        )
        stage = instruction.stage
        if not runs or runs[-1][0] != stage:
            runs.append((stage, []))
        runs[-1][1].append(instruction_id)
    return tuple((stage, tuple(ids)) for stage, ids in runs)


def _template_bound_instruction(
    instruction_id: str,
    layout_row: InstructionLayoutRow | None,
    template_bound_instructions: dict[str, TemplateBoundInstruction],
) -> TemplateBoundInstruction:
    try:
        return template_bound_instructions[instruction_id]
    except KeyError as exc:
        range_hint = (
            f" in instruction layout row {layout_row.id}"
            if layout_row is not None
            else ""
        )
        raise ValueError(
            f"missing template-bound instruction {instruction_id!r}{range_hint}"
        ) from exc


def _pe_index_for_processor(processor: str) -> int:
    parts = str(processor).split("_")
    if len(parts) == 3 and parts[0] == "processor":
        return int(parts[1]) * 4 + int(parts[2])
    return 0


def _processor_to_pe_pos(processor: str) -> tuple[int, int, int]:
    parts = str(processor).split("_")
    if len(parts) == 3 and parts[0] == "processor":
        return (int(parts[1]), int(parts[2]), 0)
    return (0, 0, 0)


def _processor_to_col(processor: str) -> int:
    parts = str(processor).split("_")
    if len(parts) == 3 and parts[0] == "processor":
        return int(parts[2])
    return 0


def _raw_operand_idx(layout_operand_idx: int) -> int:
    return (int(layout_operand_idx) % 128) * 12 + int(layout_operand_idx) // 128


def _layout_operand_idx(raw_operand_idx: int) -> int:
    return (int(raw_operand_idx) % 12) * 128 + int(raw_operand_idx) // 12


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


def _unit_inst_type_for_stage(stage: str) -> int:
    return {
        "LD": 0x8,
        "CAL": 0x40,
        "FLOW": 0x10,
        "ST": 0x20,
    }.get(stage, 0)


def _stage_code(stage: str) -> int:
    return {
        "LD": 1,
        "CAL": 2,
        "FLOW": 3,
        "ST": 4,
    }.get(stage, 0)


def _sanitize_binding_id(value: str) -> str:
    return "".join(char if char.isalnum() else "_" for char in value)
