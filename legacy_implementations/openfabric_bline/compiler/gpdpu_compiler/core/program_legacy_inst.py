"""Legacy DFU ``inst_t`` encoding helpers.

This module mirrors the vendor testcase CSV assembler path used by
``common_oper/csv_oper.cpp``.  It is intentionally narrow: it converts legacy
CSV template rows into hardware ``inst_t`` records and packs those records with
the vendor struct layout.  It does not know about OpenFabric loops, routes,
dependencies, packing, or binary package composition.
"""

from __future__ import annotations

import csv
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


INST_RECORD_SIZE_BYTES = 304
INST_STRUCT_FORMAT = "<I4xQQ3Q3Q3Q9Q3Q3Q3QQ3B3B2xQQQ3Q"
MAX_INST_EXTRA_FIELD = 3
OPERANDS_RAM_NUM = 12
OPERANDS_PER_OPERAND_RAM = 128
OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE = 4
LEGACY_GEMM_REGULAR_OPERANDS_PER_TASK_PER_PE = 50
LEGACY_GEMM_TENSOR_SCRATCH_DST_BASE = OPERANDS_RAM_NUM * OPERANDS_PER_OPERAND_RAM

NONE_INST_TYPE = 0
FIX_UNIT_INST_TYPE = 0x1
FLT_UNIT_INST_TYPE = 0x2
LD_UNIT_INST_TYPE = 0x8
FLOW_UNIT_INST_TYPE = 0x10
ST_UNIT_INST_TYPE = 0x20
TENSOR_UNIT_INST_TYPE = 0x40
CAL_INST_TYPE = FIX_UNIT_INST_TYPE | FLT_UNIT_INST_TYPE | 0x4 | TENSOR_UNIT_INST_TYPE

OP_FIX_LATENCY = 1
# Arch-13's current GEMM application builder emits HMUL/FLOAT template rows
# with latency 2 in the simulator inst_t stream.  The runtime common header
# still contains an older OP_FLT_LATENCY=72 constant, so treat the observed
# GEMM compat byte stream as the ABI source of truth here.
OP_FLT_LATENCY = 2
OP_FLT_VENDOR_CSV_LATENCY = 72
OP_LD_LATENCY = 1
OP_COPY_LATENCY = 2
OP_STD_LATENCY = 2
OP_MMA_LATENCY = 2

INST_EXE_IN_ALL = 0


@dataclass(frozen=True)
class LegacyOp:
    opcode: int
    latency: int
    src_count: int
    need_pe_idx: bool
    unit_inst_type: int


@dataclass
class LegacyInst:
    """Vendor ``inst_t`` record before byte packing."""

    op_name: str
    op_tag_name: str = ""
    src_reg_idx0_tag: str = ""
    src_reg_idx1_tag: str = ""
    dst_reg_idx_tag: str = ""
    opcode: int = 0
    unit_inst_type: int = NONE_INST_TYPE
    latency: int = 0
    imms: tuple[int, int, int] = (0, 0, 0)
    src_operands_idx: tuple[int, int, int] = (0, 0, 0)
    dst_operands_idx: tuple[int, int, int] = (0, 0, 0)
    dst_pes_pos: tuple[tuple[int, int, int], tuple[int, int, int], tuple[int, int, int]] = (
        (0, 0, 0),
        (0, 0, 0),
        (0, 0, 0),
    )
    dst_blocks_idx: tuple[int, int, int] = (0, 0, 0)
    forwarding_bits: tuple[int, int, int] = (0, 0, 0)
    bypass_bits: tuple[int, int, int] = (0, 0, 0)
    iter_exe_cond: int = INST_EXE_IN_ALL
    src_operands_fetched: tuple[int, int, int] = (0, 0, 0)
    dst_operands_fetched: tuple[int, int, int] = (0, 0, 0)
    block_idx: int = 0
    flow_ack: int = 0
    end_inst: int = 0
    extra_fields: tuple[int, int, int] = (0, 0, 0)

    def clone_with(
        self,
        *,
        op_name: str | None = None,
        opcode: int | None = None,
        latency: int | None = None,
        unit_inst_type: int | None = None,
        imm0: int | None = None,
        dst_pe_x: int | None = None,
        dst_pe0: tuple[int, int, int] | None = None,
        dst_block_idx0: int | None = None,
        src_operand_idx0: int | None = None,
        src_operand_idx1: int | None = None,
        dst_operand_idx0: int | None = None,
        block_idx: int | None = None,
        end_inst: int | None = None,
    ) -> "LegacyInst":
        dst_pes_pos = self.dst_pes_pos
        if dst_pe_x is not None:
            dst_pes_pos = (
                (dst_pe_x, dst_pes_pos[0][1], dst_pes_pos[0][2]),
                dst_pes_pos[1],
                dst_pes_pos[2],
            )
        if dst_pe0 is not None:
            dst_pes_pos = (dst_pe0, dst_pes_pos[1], dst_pes_pos[2])
        dst_blocks_idx = self.dst_blocks_idx
        if dst_block_idx0 is not None:
            dst_blocks_idx = (dst_block_idx0, dst_blocks_idx[1], dst_blocks_idx[2])
        src_operands_idx = self.src_operands_idx
        if src_operand_idx0 is not None:
            src_operands_idx = (
                src_operand_idx0,
                src_operands_idx[1],
                src_operands_idx[2],
            )
        if src_operand_idx1 is not None:
            src_operands_idx = (
                src_operands_idx[0],
                src_operand_idx1,
                src_operands_idx[2],
            )
        dst_operands_idx = self.dst_operands_idx
        if dst_operand_idx0 is not None:
            dst_operands_idx = (
                dst_operand_idx0,
                dst_operands_idx[1],
                dst_operands_idx[2],
            )
        imms = self.imms
        if imm0 is not None:
            imms = (imm0, imms[1], imms[2])
        return LegacyInst(
            op_name=op_name if op_name is not None else self.op_name,
            op_tag_name=self.op_tag_name,
            src_reg_idx0_tag=self.src_reg_idx0_tag,
            src_reg_idx1_tag=self.src_reg_idx1_tag,
            dst_reg_idx_tag=self.dst_reg_idx_tag,
            opcode=opcode if opcode is not None else self.opcode,
            unit_inst_type=(
                unit_inst_type if unit_inst_type is not None else self.unit_inst_type
            ),
            latency=latency if latency is not None else self.latency,
            imms=imms,
            src_operands_idx=src_operands_idx,
            dst_operands_idx=dst_operands_idx,
            dst_pes_pos=dst_pes_pos,
            dst_blocks_idx=dst_blocks_idx,
            forwarding_bits=self.forwarding_bits,
            bypass_bits=self.bypass_bits,
            iter_exe_cond=self.iter_exe_cond,
            src_operands_fetched=self.src_operands_fetched,
            dst_operands_fetched=self.dst_operands_fetched,
            block_idx=block_idx if block_idx is not None else self.block_idx,
            flow_ack=self.flow_ack,
            end_inst=end_inst if end_inst is not None else self.end_inst,
            extra_fields=self.extra_fields,
        )


LEGACY_OPS: dict[str, LegacyOp] = {
    "IMM": LegacyOp(0x22, OP_FIX_LATENCY, 1, False, FIX_UNIT_INST_TYPE),
    "FIMM": LegacyOp(0x23, OP_FIX_LATENCY, 1, False, FIX_UNIT_INST_TYPE),
    "FADD": LegacyOp(0x24, OP_FLT_LATENCY, 2, False, FLT_UNIT_INST_TYPE),
    "FMUL": LegacyOp(0x26, OP_FLT_LATENCY, 2, False, FLT_UNIT_INST_TYPE),
    "FMAX": LegacyOp(0x27, OP_FLT_LATENCY, 2, False, FLT_UNIT_INST_TYPE),
    "FMIN": LegacyOp(0x28, OP_FLT_LATENCY, 2, False, FLT_UNIT_INST_TYPE),
    "HMUL": LegacyOp(0x52, OP_FLT_LATENCY, 2, False, FLT_UNIT_INST_TYPE),
    # HMAX is not present in the active legacy GEMM CSV templates, but the
    # DFU3500 ISA table and instruction docs source the opcode/latency shape.
    # Keep it available for ReLU proof rows without claiming an active selector.
    "HMAX": LegacyOp(0x53, OP_FLT_VENDOR_CSV_LATENCY, 2, False, FLT_UNIT_INST_TYPE),
    "LDN": LegacyOp(0x40, OP_LD_LATENCY, 1, False, LD_UNIT_INST_TYPE),
    "LDM": LegacyOp(0x41, OP_LD_LATENCY, 1, False, LD_UNIT_INST_TYPE),
    "STD": LegacyOp(0x80, OP_STD_LATENCY, 1, False, ST_UNIT_INST_TYPE),
    "COPY": LegacyOp(0xC0, OP_COPY_LATENCY, 1, True, FLOW_UNIT_INST_TYPE),
    "RXINT": LegacyOp(0xCE, OP_FIX_LATENCY, 1, False, TENSOR_UNIT_INST_TYPE),
    "TRCTT": LegacyOp(0xCF, OP_FIX_LATENCY, 0, False, TENSOR_UNIT_INST_TYPE),
    "HMMAL": LegacyOp(0xE1, OP_MMA_LATENCY, 2, False, TENSOR_UNIT_INST_TYPE),
    "HLDT": LegacyOp(0x103, OP_LD_LATENCY, 1, False, LD_UNIT_INST_TYPE),
    "ILDT": LegacyOp(0x104, OP_LD_LATENCY, 1, False, LD_UNIT_INST_TYPE),
    "HSTT": LegacyOp(0x105, OP_STD_LATENCY, 1, False, ST_UNIT_INST_TYPE),
    "ISTT": LegacyOp(0x106, OP_STD_LATENCY, 1, False, ST_UNIT_INST_TYPE),
    "ILDMT": LegacyOp(0x107, OP_LD_LATENCY, 1, False, LD_UNIT_INST_TYPE),
    "COPYT": LegacyOp(0x101, OP_COPY_LATENCY, 1, True, FLOW_UNIT_INST_TYPE),
}

PSEUDO_EXPANSIONS = {
    "HLDT": "LDN",
    "ILDT": "LDN",
    "ILDMT": "LDM",
    "HSTT": "STD",
    "ISTT": "STD",
    "COPYT": "COPY",
}


class LegacyCsvEncoder:
    """Small Python equivalent of vendor ``Csv_Operate`` for GEMM templates."""

    def __init__(
        self,
        *,
        initial_regular_tags: Iterable[str] = (),
        initial_regular_index: int = 0,
        initial_tensor_tags_by_group: Mapping[int, Iterable[str]] | None = None,
        layout_regular_operands: bool = True,
    ) -> None:
        self._reg_idx_counter = int(initial_regular_index)
        self._reuse_reg_idx_counter = 0
        self._reg_idx_by_tag: dict[str, int] = {}
        self._reuse_reg_idx_by_tag: dict[str, int] = {}
        self._tensor_idx_by_tag: dict[str, int] = {}
        self._tensor_group_next_idx: dict[int, int] = {}
        self._layout_regular_operands = layout_regular_operands
        for tag in initial_regular_tags:
            self._seed_regular_tag(tag)
        for group_idx, tags in (initial_tensor_tags_by_group or {}).items():
            for tag in tags:
                self._seed_tensor_tag(tag, int(group_idx))

    def parse_file(self, path: str | Path) -> tuple[LegacyInst, ...]:
        with Path(path).open(newline="") as csv_file:
            reader = csv.reader(csv_file)
            next(reader, None)
            return self.parse_rows(row for row in reader if row and row[0].strip())

    def parse_rows(self, rows: Iterable[list[str]]) -> tuple[LegacyInst, ...]:
        rows = tuple(list(row) for row in rows)
        return self._parse_rows(
            rows,
            apply_forwarding=False,
            set_stage_end_flags=True,
        )

    def _parse_rows(
        self,
        rows: Iterable[list[str]],
        *,
        apply_forwarding: bool,
        set_stage_end_flags: bool,
    ) -> tuple[LegacyInst, ...]:
        insts: list[LegacyInst] = []
        for row in rows:
            insts.extend(self._expand_row(row))
        if set_stage_end_flags:
            _set_stage_end_inst_flags(insts)
        else:
            for inst in insts:
                inst.end_inst = 0
                inst.flow_ack = 0
        if apply_forwarding:
            local_insts = LegacyCsvEncoder(
                layout_regular_operands=False,
            )._parse_rows(
                rows,
                apply_forwarding=False,
                set_stage_end_flags=set_stage_end_flags,
            )
            _set_forwarding_bypass(list(local_insts))
            for inst, local_inst in zip(insts, local_insts, strict=True):
                inst.forwarding_bits = local_inst.forwarding_bits
                inst.bypass_bits = local_inst.bypass_bits
        return tuple(insts)

    def _expand_row(self, row: list[str]) -> list[LegacyInst]:
        row = [item.strip() for item in row]
        while len(row) < 11:
            row.append("")
        op_name = row[0].upper()
        if op_name not in LEGACY_OPS:
            raise ValueError(f"unsupported legacy CSV op: {op_name}")

        op = LEGACY_OPS[op_name]
        extra_fields = tuple(
            _parse_int(row[8 + index], default=0)
            for index in range(MAX_INST_EXTRA_FIELD)
        )
        tensor_dst_idx = self._tensor_dst_reg_idx(op_name, row[4], extra_fields)
        if tensor_dst_idx is None and op_name in {"HMMAL", "RXINT"}:
            tensor_dst_idx = LEGACY_GEMM_TENSOR_SCRATCH_DST_BASE
        inst = LegacyInst(
            op_name=op_name,
            op_tag_name=row[1],
            src_reg_idx0_tag=row[2],
            src_reg_idx1_tag=row[3],
            dst_reg_idx_tag=row[4],
            opcode=op.opcode,
            unit_inst_type=op.unit_inst_type,
            latency=op.latency,
            imms=(_parse_int(row[6], default=0), 0, 0),
            src_operands_idx=(
                self._get_reg_idx(row[2]),
                self._get_reg_idx(row[3]),
                0,
            ),
            dst_operands_idx=(
                tensor_dst_idx
                if tensor_dst_idx is not None
                else self._get_reg_idx(row[4]),
                0,
                0,
            ),
            dst_pes_pos=((_parse_int(row[5], default=0), 0, 0), (0, 0, 0), (0, 0, 0)),
            iter_exe_cond=_parse_int(row[7], default=INST_EXE_IN_ALL),
            extra_fields=extra_fields,
        )

        expanded_name = PSEUDO_EXPANSIONS.get(op_name)
        if expanded_name is None:
            return [inst]

        expanded_op = LEGACY_OPS[expanded_name]
        first = inst.clone_with(
            op_name=expanded_name,
            opcode=expanded_op.opcode,
            latency=expanded_op.latency,
            unit_inst_type=expanded_op.unit_inst_type,
            dst_pe_x=_pseudo_dst_pe_x(op_name, inst.dst_pes_pos[0][0]),
            src_operand_idx1=(
                inst.iter_exe_cond if op_name == "COPYT" else None
            ),
        )
        expanded = [first]
        for index in range(1, OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE):
            append_inst = first.clone_with()
            source_operand_idx0 = first.src_operands_idx[0]
            if op_name == "COPYT":
                source_operand_idx0 += index * OPERANDS_PER_OPERAND_RAM
            append_inst = append_inst.clone_with(
                src_operand_idx0=source_operand_idx0,
                dst_operand_idx0=(
                    first.dst_operands_idx[0]
                    + index * OPERANDS_PER_OPERAND_RAM
                    if op_name == "COPYT"
                    else first.dst_operands_idx[0]
                ),
            )
            if op_name not in {"COPYT"}:
                stride = (inst.dst_pes_pos[0][0] + 1) * 32
                append_inst = append_inst.clone_with(
                    imm0=inst.imms[0] + index * stride
                )
            expanded.append(append_inst)
        return expanded

    def _get_reg_idx(self, tag: str) -> int:
        tag = tag.strip()
        if not tag:
            return 0
        if tag in self._tensor_idx_by_tag:
            return self._tensor_idx_by_tag[tag]
        if tag.startswith("r"):
            if tag not in self._reuse_reg_idx_by_tag:
                self._reuse_reg_idx_by_tag[tag] = self._reuse_reg_idx_counter
                self._reuse_reg_idx_counter += 1
            return self._reuse_reg_idx_by_tag[tag]
        if tag not in self._reg_idx_by_tag:
            self._reg_idx_by_tag[tag] = (
                _layout_operand_idx(self._reg_idx_counter)
                if self._layout_regular_operands
                else self._reg_idx_counter
            )
            self._reg_idx_counter += 1
        return self._reg_idx_by_tag[tag]

    def _seed_regular_tag(self, tag: str) -> None:
        tag = tag.strip()
        if not tag or tag in self._reg_idx_by_tag:
            return
        self._reg_idx_by_tag[tag] = (
            _layout_operand_idx(self._reg_idx_counter)
            if self._layout_regular_operands
            else self._reg_idx_counter
        )
        self._reg_idx_counter += 1

    def _seed_tensor_tag(self, tag: str, group_idx: int) -> None:
        tag = tag.strip()
        if not tag or tag in self._tensor_idx_by_tag:
            return
        if group_idx < 0 or group_idx >= OPERANDS_RAM_NUM // OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE:
            return
        next_idx = self._tensor_group_next_idx.get(
            group_idx,
            OPERANDS_PER_OPERAND_RAM - 1,
        )
        self._tensor_idx_by_tag[tag] = (
            group_idx
            * OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE
            * OPERANDS_PER_OPERAND_RAM
            + next_idx
        )
        self._tensor_group_next_idx[group_idx] = next_idx - 1

    def _tensor_dst_reg_idx(
        self,
        op_name: str,
        tag: str,
        extra_fields: tuple[int, int, int],
    ) -> int | None:
        tag = tag.strip()
        if not tag or op_name not in {"HLDT", "ILDT", "ILDMT", "HSTT", "ISTT", "COPYT"}:
            return None
        group_idx = int(extra_fields[2]) - 1
        if group_idx < 0:
            group_idx = _legacy_gemm_tensor_group_for_tag(tag)
        if group_idx < 0 or group_idx >= OPERANDS_RAM_NUM // OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE:
            return None
        self._seed_tensor_tag(tag, group_idx)
        return self._tensor_idx_by_tag[tag]


def legacy_maximum_scalar_template(
    *,
    input_tag: str,
    output_tag: str,
    scalar: float,
) -> tuple[LegacyInst, ...]:
    """Return a tiny fixed template for ``maximum_scalar`` local compute.

    This is intentionally not a general register allocator.  It binds one
    input local value, one float immediate threshold, and one output local value
    to the vendor CSV-compatible ``IMM`` + ``FMAX`` instruction shape.
    """

    scalar_tag = f"{output_tag}_scalar_threshold"
    scalar_bits = _fp32_bits(float(scalar))
    insts = LegacyCsvEncoder()._parse_rows(
        (
            ["ILDMT", "ILDMT_input", "", "", input_tag, "3", "0", "0"],
            ["IMM", "IMM_scalar", "", "", scalar_tag, "", str(scalar_bits), "0"],
            [
                "FMAX",
                "FMAX_maximum_scalar",
                input_tag,
                scalar_tag,
                output_tag,
                "",
                "",
                "0",
            ],
        ),
        apply_forwarding=True,
        set_stage_end_flags=False,
    )
    for inst in insts:
        if inst.unit_inst_type == FLT_UNIT_INST_TYPE:
            inst.latency = OP_FLT_VENDOR_CSV_LATENCY
            inst.iter_exe_cond = 1
    return insts


def legacy_relu_hmax_zero_template(
    *,
    input_tag: str = "Y_IN",
    zero_tag: str = "ZERO_RELU",
    output_tag: str = "Y_OUT",
) -> tuple[LegacyInst, ...]:
    """Return the explicit candidate rows for fp16 ReLU ``max(x, 0)``.

    This is a source-backed materializer candidate, not an active legacy
    template selector.  It mirrors the vendor subtask4 ReLU generator's
    operand order, ``HMAX ZERO_relu, input, output``, so ReLU proof reports can
    expose concrete row bytes while still failing closed until an activated
    SimICT/template artifact selects this family.
    """

    return LegacyCsvEncoder(
        initial_regular_tags=(input_tag,),
    ).parse_rows(
        (
            ["IMM", "IMM_relu_zero", "", "", zero_tag, "", "0", "0"],
            ["HMAX", "HMAX_relu", zero_tag, input_tag, output_tag, "", "", "0"],
        )
    )


def legacy_single_value_store_template(
    *,
    input_tag: str,
    input_regular_index: int = 2,
) -> tuple[LegacyInst, ...]:
    """Return the fixed vendor-style store template for one local value.

    ``HSTT`` is a vendor pseudo op.  The CSV assembler expands one row into
    four ``STD`` instructions for the adaptive operand groups.  This template
    is used by non-GEMM functional probes; GEMM keeps using its legacy
    subtask3 store CSV rows.

    Phase-1 local-compute probes intentionally use a fixed operand layout
    instead of a general register allocator:

    * slot 0: input fragment
    * slot 1: scalar immediate
    * slot 2: compute output fragment
    """

    return LegacyCsvEncoder(
        initial_regular_tags=(input_tag,),
        initial_regular_index=input_regular_index,
    )._parse_rows(
        (
            ["HSTT", "HSTT_store", "", "", input_tag, "0", "0", "2"],
        ),
        apply_forwarding=False,
        set_stage_end_flags=False,
    )


def _fp32_bits(value: float) -> int:
    if not math.isfinite(value):
        raise ValueError(f"non-finite FP32 immediate is not supported: {value!r}")
    return struct.unpack("<I", struct.pack("<f", value))[0]


def parse_legacy_csv_template(
    path: str | Path,
    *,
    initial_regular_tags: Iterable[str] = (),
    initial_regular_index: int = 0,
    initial_tensor_tags_by_group: Mapping[int, Iterable[str]] | None = None,
) -> tuple[LegacyInst, ...]:
    """Parse one vendor CSV template into expanded legacy ``inst_t`` rows."""

    return LegacyCsvEncoder(
        initial_regular_tags=initial_regular_tags,
        initial_regular_index=initial_regular_index,
        initial_tensor_tags_by_group=initial_tensor_tags_by_group,
    ).parse_file(path)


def legacy_gemm_micro_block_template(
    block_kind: str,
    *,
    task_index: int = 0,
    template_index: int | None = None,
    input0_preallocated: bool = True,
) -> tuple[LegacyInst, ...]:
    """Return a canonical legacy GEMM instruction sequence for a micro-block.

    The current refactored pipeline splits legacy GEMM behavior into smaller
    executable tile micro-blocks.  Vendor CSV templates are therefore consumed
    as source material, then filtered by micro-block kind instead of being
    treated as one-to-one exeBlock definitions.
    """

    template_root = _legacy_gemm_template_root()
    task_index = int(task_index)
    task_dir = template_root / f"task{task_index}"
    initial_regular_index = (
        task_index * LEGACY_GEMM_REGULAR_OPERANDS_PER_TASK_PER_PE
    )
    if block_kind == "accumulator_prepare":
        index = 0 if template_index is None else int(template_index)
        return parse_legacy_csv_template(
            task_dir / f"subtask1/template/{index}.csv",
            initial_regular_index=initial_regular_index,
            initial_tensor_tags_by_group=_legacy_gemm_tensor_seed_before_input0(
                task_index
            ),
        )
    if block_kind == "route_source_materialize":
        index = 0 if template_index is None else int(template_index)
        return parse_legacy_csv_template(
            task_dir / f"subtask2/template/{index}.csv",
            initial_regular_tags=_legacy_gemm_seed_before_input0(task_index),
            initial_regular_index=initial_regular_index,
            initial_tensor_tags_by_group=_legacy_gemm_tensor_seed_before_input0(
                task_index
            ),
        )
    if block_kind == "route_forward":
        index = 10 if template_index is None else int(template_index)
        return parse_legacy_csv_template(
            task_dir / f"subtask2/template/{index}.csv",
            initial_regular_tags=_legacy_gemm_seed_after_input0(task_index),
            initial_regular_index=initial_regular_index,
            initial_tensor_tags_by_group=_legacy_gemm_tensor_seed_after_input0(
                task_index
            ),
        )
    if block_kind == "compute_update":
        index = 16 if template_index is None else int(template_index)
        initial_tags = (
            _legacy_gemm_seed_after_input0(task_index)
            if input0_preallocated
            else _legacy_gemm_seed_before_input0(task_index)
        )
        return _parse_filtered_legacy_csv(
            task_dir / f"subtask2/template/{index}.csv",
            {"HLDT", "LDN", "HMUL", "RXINT", "HMMAL", "TRCTT"},
            initial_regular_tags=initial_tags,
            initial_regular_index=initial_regular_index,
            initial_tensor_tags_by_group=(
                _legacy_gemm_tensor_seed_after_input0(task_index)
                if input0_preallocated
                else _legacy_gemm_tensor_seed_before_input0(task_index)
            ),
        )
    if block_kind == "tile_store":
        index = 0 if template_index is None else int(template_index)
        return parse_legacy_csv_template(
            task_dir / f"subtask3/template/{index}.csv",
            initial_regular_tags=_legacy_gemm_seed_after_input1(task_index),
            initial_regular_index=initial_regular_index,
            initial_tensor_tags_by_group=_legacy_gemm_tensor_seed_after_input1(
                task_index
            ),
        )
    raise ValueError(f"unsupported legacy GEMM micro-block kind: {block_kind}")


def pack_legacy_inst(inst: LegacyInst) -> bytes:
    """Pack one ``LegacyInst`` using vendor ``inst_t`` layout."""

    encoded = struct.pack(
        INST_STRUCT_FORMAT,
        inst.opcode,
        inst.unit_inst_type,
        inst.latency,
        *inst.imms,
        *inst.src_operands_idx,
        *inst.dst_operands_idx,
        *(coord for pos in inst.dst_pes_pos for coord in pos),
        *inst.dst_blocks_idx,
        *inst.forwarding_bits,
        *inst.bypass_bits,
        inst.iter_exe_cond,
        *inst.src_operands_fetched,
        *inst.dst_operands_fetched,
        inst.block_idx,
        inst.flow_ack,
        inst.end_inst,
        *inst.extra_fields,
    )
    if len(encoded) != INST_RECORD_SIZE_BYTES:
        raise ValueError("inst_t serializer size mismatch")
    return encoded


def decode_legacy_inst_skeleton(record: bytes) -> dict[str, object]:
    """Decode the locally known ``inst_t`` fields used by proof reports.

    This is intentionally a skeleton decoder.  It roundtrips the fields that
    the legacy CSV packer owns and does not claim runtime task/subtask
    activation or final component placement.
    """

    if len(record) != INST_RECORD_SIZE_BYTES:
        raise ValueError(
            f"inst_t skeleton decode size mismatch: got {len(record)}, "
            f"expected {INST_RECORD_SIZE_BYTES}"
        )
    fields = struct.unpack(INST_STRUCT_FORMAT, record)
    return {
        "opcode": int(fields[0]),
        "unit_inst_type": int(fields[1]),
        "latency": int(fields[2]),
        "imms": tuple(int(value) for value in fields[3:6]),
        "src_operands_idx": tuple(int(value) for value in fields[6:9]),
        "dst_operands_idx": tuple(int(value) for value in fields[9:12]),
        "dst_pes_pos": tuple(
            tuple(int(value) for value in fields[start : start + 3])
            for start in (12, 15, 18)
        ),
        "dst_blocks_idx": tuple(int(value) for value in fields[21:24]),
        "forwarding_bits": tuple(int(value) for value in fields[24:27]),
        "bypass_bits": tuple(int(value) for value in fields[27:30]),
        "iter_exe_cond": int(fields[30]),
        "src_operands_fetched": tuple(int(value) for value in fields[31:34]),
        "dst_operands_fetched": tuple(int(value) for value in fields[34:37]),
        "block_idx": int(fields[37]),
        "flow_ack": int(fields[38]),
        "end_inst": int(fields[39]),
        "extra_fields": tuple(int(value) for value in fields[40:43]),
    }


def _parse_int(value: str, *, default: int) -> int:
    value = value.strip()
    if not value:
        return default
    return int(value, 0)


def _layout_operand_idx(reg_idx: int) -> int:
    return (reg_idx % OPERANDS_RAM_NUM) * OPERANDS_PER_OPERAND_RAM + (
        reg_idx // OPERANDS_RAM_NUM
    )


def _parse_filtered_legacy_csv(
    path: Path,
    op_names: set[str],
    *,
    initial_regular_tags: Iterable[str] = (),
    initial_regular_index: int = 0,
    initial_tensor_tags_by_group: Mapping[int, Iterable[str]] | None = None,
) -> tuple[LegacyInst, ...]:
    with path.open(newline="") as csv_file:
        reader = csv.reader(csv_file)
        next(reader, None)
        rows = [
            row
            for row in reader
            if row and row[0].strip().upper() in op_names
        ]
    return LegacyCsvEncoder(
        initial_regular_tags=initial_regular_tags,
        initial_regular_index=initial_regular_index,
        initial_tensor_tags_by_group=initial_tensor_tags_by_group,
    ).parse_rows(rows)


def _legacy_gemm_template_root() -> Path:
    return (
        Path(__file__).resolve().parents[3]
        / "simict3500final/gpdpu/users/risc_nn_riscv/testcase/build_out"
        / "gemm_template_fusion/worktree/gpdpu/users/risc_nn_riscv/testcase"
        / "application/gemm_template_fusion"
    )


def _legacy_gemm_output_tags(task_index: int = 0) -> tuple[str, ...]:
    return tuple(f"gemm0_output0_{int(task_index)}_{index}" for index in range(16))


def _legacy_gemm_input0_tags(task_index: int = 0) -> tuple[str, ...]:
    return tuple(f"gemm0_input0_{int(task_index)}_{index}" for index in range(16))


def _legacy_gemm_input0_primary_tags(task_index: int = 0) -> tuple[str, ...]:
    return _legacy_gemm_input0_tags(task_index)


def _legacy_gemm_input0_spill_tags(task_index: int = 0) -> tuple[str, ...]:
    return ()


def _legacy_gemm_input1_tags(task_index: int = 0) -> tuple[str, ...]:
    return tuple(f"gemm0_input1_{int(task_index)}_{index}" for index in range(16))


def _legacy_gemm_task_alpha_tag(task_index: int = 0) -> str:
    task_index = int(task_index)
    return "ALPHA" if task_index == 0 else f"ALPHA@task{task_index}"


def _legacy_gemm_task_bet_tag(task_index: int = 0) -> str:
    task_index = int(task_index)
    return "BET" if task_index == 0 else f"BET@task{task_index}"


def _legacy_gemm_alpha_tags_through(task_index: int = 0) -> tuple[str, ...]:
    task_index = int(task_index)
    return (
        *(
            tag
            for index in range(task_index)
            for tag in (
                f"ALPHA@task{index}",
                *_legacy_gemm_input0_primary_tags(index),
            )
        ),
        "ALPHA",
    )


def _legacy_gemm_alpha_bet_tags_through(task_index: int = 0) -> tuple[str, ...]:
    return _legacy_gemm_alpha_tags_through(task_index)


def _legacy_gemm_bet_tags_through(task_index: int = 0) -> tuple[str, ...]:
    task_index = int(task_index)
    return (
        *(
            tag
            for index in range(task_index)
            for tag in (
                f"BET@task{index}",
                *_legacy_gemm_input1_tags(index),
            )
        ),
        "BET",
    )


def _legacy_gemm_output_tags_through(task_index: int = 0) -> tuple[str, ...]:
    task_index = int(task_index)
    tags: list[str] = []
    for index in range(task_index + 1):
        tags.extend(_legacy_gemm_output_tags(index))
    return tuple(tags)


def _legacy_gemm_input0_tags_before(task_index: int = 0) -> tuple[str, ...]:
    return tuple(
        tag
        for index in range(int(task_index))
        for tag in _legacy_gemm_input0_tags(index)
    )


def _legacy_gemm_input0_tags_through(task_index: int = 0) -> tuple[str, ...]:
    return (
        *_legacy_gemm_input0_tags_before(task_index),
        *_legacy_gemm_input0_tags(task_index),
    )


def _legacy_gemm_input1_tags_before(task_index: int = 0) -> tuple[str, ...]:
    return tuple(
        tag
        for index in range(int(task_index))
        for tag in _legacy_gemm_input1_tags(index)
    )


def _legacy_gemm_input1_tags_through(task_index: int = 0) -> tuple[str, ...]:
    return (
        *_legacy_gemm_input1_tags_before(task_index),
        *_legacy_gemm_input1_tags(task_index),
    )


def _legacy_gemm_seed_before_input0(task_index: int = 0) -> tuple[str, ...]:
    return (*_legacy_gemm_output_tags(task_index), "ALPHA", "BET")


def _legacy_gemm_seed_after_input0(task_index: int = 0) -> tuple[str, ...]:
    return (
        *_legacy_gemm_seed_before_input0(task_index),
        *_legacy_gemm_input0_tags(task_index),
    )


def _legacy_gemm_seed_after_input1(task_index: int = 0) -> tuple[str, ...]:
    return (
        *_legacy_gemm_seed_after_input0(task_index),
        *_legacy_gemm_input1_tags(task_index),
    )


def _legacy_gemm_tensor_seed_before_input0(
    task_index: int = 0,
) -> dict[int, tuple[str, ...]]:
    task_index = int(task_index)
    # Vendor per-PE TaskResource allocates tags in subtask processing order:
    #   subtask1 (accumulator_prepare): output0, ALPHA, BET
    #   subtask2 (compute): input0, input1
    #   subtask3 (store): output0
    #
    # Seed order within each group must be DESCENDING by vendor slot.
    # Encoder assigns slots 127, 126, 125... in seed order.
    #
    # IMPORTANT: ALPHA and BET are allocated in task 0 and persist across all tasks.
    # They must appear as the FIRST two tags in Group 1 seed, followed by input0 tags.
    return {
        0: (
            # Group 0: output tags, task 0..(task_index-1)
            # Vendor: output0_0_0=127, ..., output0_0_15=112, output0_1_0=111, ..., output0_1_15=96
            *(
                tag
                for index in range(task_index)
                for tag in _legacy_gemm_output_tags(index)
            ),
        ),
        1: (
            # Group 1: ALPHA, BET (from task 0), then input0 tags, task 0..(task_index-1)
            # Vendor: ALPHA=127, BET=126, input0_0_0=125, ..., input0_0_15=110, input0_1_0=109, ..., input0_1_15=94
            *(
                ["ALPHA", "BET"] if task_index > 0 else []
            ),
            *(
                tag
                for index in range(task_index)
                for tag in _legacy_gemm_input0_primary_tags(index)
            ),
        ),
        2: (
            # Group 2: input1 tags, task 0..(task_index-1)
            # Vendor: input1_0_0=127, ..., input1_0_15=112, input1_1_0=111, ..., input1_1_15=96
            *(
                tag
                for index in range(task_index)
                for tag in _legacy_gemm_input1_tags(index)
            ),
        ),
    }


def _legacy_gemm_tensor_seed_after_input0(
    task_index: int = 0,
) -> dict[int, tuple[str, ...]]:
    task_index = int(task_index)
    # Seed table after input0 has been allocated in the current task
    # Contains: prior tasks' tags + current task's output0 + ALPHA/BET + input0
    return {
        0: (
            # Group 0: output tags, task 0..task_index (including current task)
            *(
                tag
                for index in range(task_index + 1)
                for tag in _legacy_gemm_output_tags(index)
            ),
        ),
        1: (
            # Group 1: ALPHA, BET (from task 0), then input0 tags, task 0..task_index
            "ALPHA", "BET",
            *(
                tag
                for index in range(task_index + 1)
                for tag in _legacy_gemm_input0_primary_tags(index)
            ),
        ),
        2: (
            # Group 2: input1 tags, task 0..(task_index-1) only
            # (input1 for current task not yet allocated)
            *(
                tag
                for index in range(task_index)
                for tag in _legacy_gemm_input1_tags(index)
            ),
        ),
    }


def _legacy_gemm_tensor_seed_after_input1(
    task_index: int = 0,
) -> dict[int, tuple[str, ...]]:
    task_index = int(task_index)
    # Seed table after input1 has been allocated in the current task
    # Contains: prior tasks' tags + current task's output0 + ALPHA/BET + input0 + input1
    return {
        0: (
            # Group 0: output tags, task 0..task_index (including current task)
            *(
                tag
                for index in range(task_index + 1)
                for tag in _legacy_gemm_output_tags(index)
            ),
        ),
        1: (
            # Group 1: ALPHA, BET (from task 0), then input0 tags, task 0..task_index
            "ALPHA", "BET",
            *(
                tag
                for index in range(task_index + 1)
                for tag in _legacy_gemm_input0_primary_tags(index)
            ),
        ),
        2: (
            # Group 2: input1 tags, task 0..task_index (including current task)
            *(
                tag
                for index in range(task_index + 1)
                for tag in _legacy_gemm_input1_tags(index)
            ),
        ),
    }


def _legacy_gemm_tensor_group_for_tag(tag: str) -> int:
    if "_output0_" in tag:
        return 0
    if tag == "ALPHA" or tag.startswith("ALPHA@"):
        return 1
    if tag == "BET" or tag.startswith("BET@"):
        return 1
    if "_input0_" in tag:
        return 1
    if "_input1_" in tag:
        return 2
    return -1


def _pseudo_dst_pe_x(op_name: str, raw_dst_pe: int) -> int:
    if op_name == "ILDMT":
        return raw_dst_pe & 0x1
    if op_name == "SLDCNST":
        return raw_dst_pe & 0x3
    return raw_dst_pe


def _set_forwarding_bypass(insts: list[LegacyInst]) -> None:
    for previous, current in zip(insts, insts[1:]):
        if not (previous.unit_inst_type & CAL_INST_TYPE):
            continue
        if not (current.unit_inst_type & CAL_INST_TYPE):
            continue
        previous_dst = previous.dst_operands_idx[0]
        forwarding_bits = list(current.forwarding_bits)
        bypass_bits = list(previous.bypass_bits)
        if previous_dst == current.src_operands_idx[0]:
            bypass_bits[0] = 1
            forwarding_bits[0] = 1
        if previous_dst == current.src_operands_idx[1]:
            bypass_bits[0] = 1
            forwarding_bits[1] = 1
        if previous_dst == current.dst_operands_idx[0]:
            bypass_bits[0] = 1
            forwarding_bits[2] = 1
        previous.bypass_bits = tuple(bypass_bits)
        current.forwarding_bits = tuple(forwarding_bits)


def _set_stage_end_inst_flags(insts: list[LegacyInst]) -> None:
    if not insts:
        return
    for inst in insts:
        inst.end_inst = 0
        inst.flow_ack = 0
    for index, inst in enumerate(insts):
        next_inst = insts[index + 1] if index + 1 < len(insts) else None
        if next_inst is None:
            inst.end_inst = 1
        elif inst.unit_inst_type in {
            LD_UNIT_INST_TYPE,
            FLOW_UNIT_INST_TYPE,
            ST_UNIT_INST_TYPE,
        } and next_inst.unit_inst_type != inst.unit_inst_type:
            inst.end_inst = 1
        if inst.unit_inst_type == FLOW_UNIT_INST_TYPE and inst.end_inst:
            inst.flow_ack = 1
