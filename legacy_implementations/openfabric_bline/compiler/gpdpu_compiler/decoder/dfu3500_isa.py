"""DFU3500 ISA annotations for decoder diagnostics.

This module annotates instruction rows; it does not define a lowering contract.
Template legality, operand ownership, pseudo expansion, and runnable proof stay
in the template/package verifier layers.

The opcode metadata is source-backed by the vendor ``Csv_Operate::registerOp``
table and ``common/src/inst_def.h`` latency / unit-type constants.  Pseudo
instructions are intentionally retained so the decoder can identify them, while
validation can reject them when they appear in final CBUF rows.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class OpcodeInfo:
    opcode: int
    mnemonic: str
    category: str
    source: str
    latency: int | None = None
    src_count: int | None = None
    need_pe_idx: bool | None = None
    unit_inst_type: int | None = None
    pseudo: bool = False

    def to_json(self) -> dict[str, object]:
        return {
            "opcode": self.opcode,
            "mnemonic": self.mnemonic,
            "category": self.category,
            "source": self.source,
            "latency": self.latency,
            "src_count": self.src_count,
            "need_pe_idx": self.need_pe_idx,
            "unit_inst_type": self.unit_inst_type,
            "pseudo": self.pseudo,
        }


_SOURCE = "common/src/inst_def.h + testcase/common_oper/csv_oper.cpp::registerOp"


def _opcode_category(opcode: int, mnemonic: str) -> str:
    if opcode >= 0x100:
        return "pseudo_assembler_only"
    if mnemonic in {"LDN", "LDM", "LDSHIF", "LDMD64", "LDCNST"}:
        return "load"
    if mnemonic in {"STD", "STM", "STMD64", "STCNST", "STSHIF"}:
        return "store"
    if mnemonic in {"COPY", "LCOPY", "COPYT", "LCOPYT"}:
        return "flow"
    if mnemonic in {
        "HMMA",
        "IMMA",
        "SSET",
        "RXINT",
        "TRCTT",
        "HMMAQ",
        "IMMAU",
        "IMMAIU",
        "IMMAUI",
        "HMMAL",
    }:
        return "tensor"
    if mnemonic.startswith(("F", "D", "H")) or mnemonic in {"SHFL", "RXIN", "RXOUT"}:
        return "simd_numeric"
    return "scalar_or_control"


def _op(
    opcode: int,
    mnemonic: str,
    latency: int,
    src_count: int,
    need_pe_idx: bool,
    unit_inst_type: int,
) -> OpcodeInfo:
    return OpcodeInfo(
        opcode=opcode,
        mnemonic=mnemonic,
        category=_opcode_category(opcode, mnemonic),
        source=_SOURCE,
        latency=latency,
        src_count=src_count,
        need_pe_idx=need_pe_idx,
        unit_inst_type=unit_inst_type,
        pseudo=opcode >= 0x100,
    )


_OPCODE_INFOS: tuple[OpcodeInfo, ...] = (
    _op(0x001, "ADD", 1, 2, False, 0x1),
    _op(0x002, "SUB", 1, 2, False, 0x1),
    _op(0x003, "MUL", 1, 2, False, 0x1),
    _op(0x004, "MAX", 1, 2, False, 0x1),
    _op(0x005, "MIN", 1, 2, False, 0x1),
    _op(0x006, "EQ", 1, 2, False, 0x1),
    _op(0x007, "LT", 1, 2, False, 0x1),
    _op(0x008, "GT", 1, 2, False, 0x1),
    _op(0x009, "MADD", 1, 3, False, 0x1),
    _op(0x00A, "UADD", 1, 2, False, 0x1),
    _op(0x00B, "USUB", 1, 2, False, 0x1),
    _op(0x00C, "UMUL", 1, 2, False, 0x1),
    _op(0x00D, "UMAX", 1, 2, False, 0x1),
    _op(0x00E, "DP4A", 1, 3, False, 0x1),
    _op(0x00F, "ULT", 1, 2, False, 0x1),
    _op(0x010, "UGT", 1, 2, False, 0x1),
    _op(0x011, "UMADD", 1, 3, False, 0x1),
    _op(0x012, "COND", 1, 3, False, 0x1),
    _op(0x013, "ULTS", 1, 2, False, 0x1),
    _op(0x014, "LSL", 1, 2, False, 0x1),
    _op(0x015, "LSR", 1, 2, False, 0x1),
    _op(0x016, "OR", 1, 2, False, 0x1),
    _op(0x017, "AND", 1, 2, False, 0x1),
    _op(0x018, "NOT", 1, 1, False, 0x1),
    _op(0x019, "XOR", 1, 2, False, 0x1),
    _op(0x01A, "ASR", 1, 2, False, 0x1),
    _op(0x01B, "SHA_CH", 1, 3, False, 0x1),
    _op(0x01C, "SHA_MAJ", 1, 3, False, 0x1),
    _op(0x01D, "SHA_SO", 1, 2, False, 0x1),
    _op(0x01E, "SHA_S1", 1, 2, False, 0x1),
    _op(0x01F, "SHA_SS0", 1, 2, False, 0x1),
    _op(0x020, "SHA_SS1", 1, 2, False, 0x1),
    _op(0x021, "BTM_LG", 1, 2, False, 0x1),
    _op(0x022, "IMM", 1, 1, False, 0x1),
    _op(0x023, "FIMM", 1, 1, False, 0x1),
    _op(0x024, "FADD", 72, 2, False, 0x2),
    _op(0x025, "FSUB", 72, 2, False, 0x2),
    _op(0x026, "FMUL", 72, 2, False, 0x2),
    _op(0x027, "FMAX", 72, 2, False, 0x2),
    _op(0x028, "FMIN", 72, 2, False, 0x2),
    _op(0x029, "SHFL", 72, 3, False, 0x2),
    _op(0x02A, "FLT", 72, 2, False, 0x2),
    _op(0x02B, "FGT", 72, 2, False, 0x2),
    _op(0x02C, "FMADD", 72, 3, False, 0x2),
    _op(0x02D, "FDIV", 9, 2, False, 0x4),
    _op(0x02E, "FRCP", 4, 1, False, 0x4),
    _op(0x02F, "QMPAD", 4, 2, False, 0x4),
    _op(0x031, "FP2DB", 72, 1, False, 0x2),
    _op(0x032, "DB2FP", 72, 2, False, 0x2),
    _op(0x033, "FXP2FP", 72, 1, False, 0x2),
    _op(0x034, "FP2FXP", 72, 1, False, 0x2),
    _op(0x035, "DADD", 72, 2, False, 0x2),
    _op(0x036, "DSUB", 72, 2, False, 0x2),
    _op(0x037, "DMUL", 72, 2, False, 0x2),
    _op(0x038, "DMAX", 72, 2, False, 0x2),
    _op(0x039, "DMIN", 72, 2, False, 0x2),
    _op(0x03A, "DLT", 72, 2, False, 0x2),
    _op(0x03B, "DGT", 72, 2, False, 0x2),
    _op(0x03C, "DMADD", 72, 3, False, 0x2),
    _op(0x03D, "DDIV", 9, 2, False, 0x4),
    _op(0x03E, "DSQRT", 9, 1, False, 0x4),
    _op(0x03F, "MASK", 1, 1, False, 0x1),
    _op(0x040, "LDN", 1, 1, False, 0x8),
    _op(0x041, "LDM", 1, 1, False, 0x8),
    _op(0x042, "LDSHIF", 1, 1, False, 0x8),
    _op(0x043, "LDMD64", 1, 1, False, 0x8),
    _op(0x044, "LDCNST", 1, 1, False, 0x8),
    _op(0x050, "HADD", 72, 2, False, 0x2),
    _op(0x051, "HSUB", 72, 2, False, 0x2),
    _op(0x052, "HMUL", 72, 2, False, 0x2),
    _op(0x053, "HMAX", 72, 2, False, 0x2),
    _op(0x054, "HMIN", 72, 2, False, 0x2),
    _op(0x055, "HLT", 72, 2, False, 0x2),
    _op(0x056, "HGT", 72, 2, False, 0x2),
    _op(0x057, "HMADD", 72, 3, False, 0x2),
    _op(0x058, "HDIV", 9, 2, False, 0x4),
    _op(0x059, "H2FP", 72, 1, False, 0x2),
    _op(0x05A, "FP2H", 72, 2, False, 0x2),
    _op(0x05B, "HSIS", 5, 1, False, 0x2),
    _op(0x080, "STD", 2, 1, False, 0x20),
    _op(0x081, "STM", 2, 1, False, 0x20),
    _op(0x082, "STMD64", 2, 1, False, 0x20),
    _op(0x083, "STCNST", 2, 1, False, 0x20),
    _op(0x084, "STSHIF", 2, 1, False, 0x20),
    _op(0x0C0, "COPY", 2, 1, True, 0x10),
    _op(0x0C1, "GINST", 1, 0, False, 0x1),
    _op(0x0C2, "GIBSN", 1, 0, False, 0x1),
    _op(0x0C3, "GSIMD", 1, 0, False, 0x1),
    _op(0x0C4, "RXIN", 72, 1, False, 0x2),
    _op(0x0C5, "RXOUT", 72, 0, False, 0x2),
    _op(0x0C6, "TRCT8", 1, 0, False, 0x1),
    _op(0x0C7, "QMADD", 1, 2, False, 0x1),
    _op(0x0C8, "EXPD32", 1, 1, False, 0x1),
    _op(0x0C9, "LOFST", 1, 1, False, 0x1),
    _op(0x0CA, "UMIN", 1, 2, False, 0x1),
    _op(0x0CB, "HMMA", 2, 2, False, 0x40),
    _op(0x0CC, "IMMA", 2, 2, False, 0x40),
    _op(0x0CD, "SSET", 1, 1, False, 0x40),
    _op(0x0CE, "RXINT", 1, 1, False, 0x40),
    _op(0x0CF, "TRCTT", 1, 0, False, 0x40),
    _op(0x0D0, "FSQRT", 4, 1, False, 0x4),
    _op(0x0D1, "FRSQRT", 4, 1, False, 0x4),
    _op(0x0D2, "FSIN", 4, 1, False, 0x4),
    _op(0x0D3, "FCOS", 4, 1, False, 0x4),
    _op(0x0D4, "FLOG2", 4, 1, False, 0x4),
    _op(0x0D5, "FEXP2", 4, 1, False, 0x4),
    _op(0x0D6, "ASL", 1, 2, False, 0x1),
    _op(0x0D7, "MOVE", 1, 1, False, 0x1),
    _op(0x0D8, "NONE", 1, 0, False, 0x0),
    _op(0x0D9, "NOP", 1, 0, False, 0x0),
    _op(0x0DA, "UDIV", 9, 2, False, 0x4),
    _op(0x0DB, "DIV", 9, 2, False, 0x4),
    _op(0x0DC, "UROTR", 1, 2, False, 0x1),
    _op(0x0DD, "HMMAQ", 2, 2, False, 0x40),
    _op(0x0DE, "IMMAU", 2, 2, False, 0x40),
    _op(0x0DF, "IMMAIU", 2, 2, False, 0x40),
    _op(0x0E0, "IMMAUI", 2, 2, False, 0x40),
    _op(0x0E1, "HMMAL", 2, 2, False, 0x40),
    _op(0x100, "LCOPY", 2, 1, False, 0x10),
    _op(0x101, "COPYT", 2, 1, True, 0x10),
    _op(0x102, "LCOPYT", 2, 1, False, 0x10),
    _op(0x103, "HLDT", 1, 1, False, 0x8),
    _op(0x104, "ILDT", 1, 1, False, 0x8),
    _op(0x105, "HSTT", 2, 1, False, 0x20),
    _op(0x106, "ISTT", 2, 1, False, 0x20),
    _op(0x107, "ILDMT", 1, 1, False, 0x8),
    _op(0x108, "SLDM", 1, 1, False, 0x8),
    _op(0x109, "SLDSHIF", 1, 1, False, 0x8),
    _op(0x10A, "SLDMD64", 1, 1, False, 0x8),
    _op(0x10B, "SLDCNST", 1, 1, False, 0x8),
    _op(0x10C, "SSTM", 2, 1, False, 0x20),
    _op(0x10D, "SSTMD64", 2, 1, False, 0x20),
    _op(0x10E, "SSTCNST", 2, 1, False, 0x20),
    _op(0x10F, "SSTSHIF", 2, 1, False, 0x20),
)

_OPCODE_TABLE: dict[int, OpcodeInfo] = {info.opcode: info for info in _OPCODE_INFOS}


def annotate_opcode(opcode: int) -> dict[str, object]:
    info = _OPCODE_TABLE.get(opcode)
    if info is None:
        return {
            "opcode": opcode,
            "mnemonic": None,
            "category": "unknown",
            "source": "common/src/inst_def.h",
            "latency": None,
            "src_count": None,
            "need_pe_idx": None,
            "unit_inst_type": None,
            "pseudo": False,
        }
    return info.to_json()
