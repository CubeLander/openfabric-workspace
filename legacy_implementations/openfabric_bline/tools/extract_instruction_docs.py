#!/usr/bin/env python3
"""Extract DFU3500 instruction materials into agent-friendly text files.

The source .xlsx/.docx files are Office Open XML zip archives, so this script
uses only the Python standard library. It intentionally keeps the extraction
plain: CSV/JSONL for structured instruction rows, and Markdown for document
text with table and image placeholders.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import defaultdict
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Sequence
from xml.etree import ElementTree as ET
from zipfile import ZipFile


NS_XLSX = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
}
NS_DOCX = {
    "w": "http://schemas.openxmlformats.org/wordprocessingml/2006/main",
    "a": "http://schemas.openxmlformats.org/drawingml/2006/main",
    "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships",
    "wp": "http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing",
    "v": "urn:schemas-microsoft-com:vml",
}

MNEMONIC_RE = re.compile(r"^[A-Z][A-Z0-9_]*(?:/[A-Z][A-Z0-9_]*)*$")
DOC_SECTION_RE = re.compile(r"^\s*(\d+(?:\.\d+)*)\s*([A-Z][A-Z0-9_/ ]+)\s*$")
CATEGORY_ONLY_NAMES = {
    "FLOAT",
    "DOUBLE",
    "HALF",
    "HALF FLOAT",
}

ARITH_OPS = {
    "ADD": "+",
    "SUB": "-",
    "MUL": "*",
    "DIV": "/",
    "MAX": "max",
    "MIN": "min",
}
COMPARE_OPS = {
    "EQ": "==",
    "LT": "<",
    "GT": ">",
    "ULT": "<",
    "UGT": ">",
    "ULTS": "<",
    "FLT": "<",
    "FGT": ">",
    "HLT": "<",
    "HGT": ">",
    "DLT": "<",
    "DGT": ">",
}


def cell_ref_to_col(ref: str) -> int:
    letters = "".join(ch for ch in ref if ch.isalpha())
    value = 0
    for ch in letters:
        value = value * 26 + ord(ch.upper()) - ord("A") + 1
    return value


def read_shared_strings(zip_file: ZipFile) -> List[str]:
    try:
        root = ET.fromstring(zip_file.read("xl/sharedStrings.xml"))
    except KeyError:
        return []

    strings: List[str] = []
    for item in root.findall("a:si", NS_XLSX):
        text = "".join(t.text or "" for t in item.findall(".//a:t", NS_XLSX))
        strings.append(text)
    return strings


def read_xlsx_sheets(path: Path) -> Dict[str, List[List[str]]]:
    with ZipFile(path) as zip_file:
        shared_strings = read_shared_strings(zip_file)
        workbook = ET.fromstring(zip_file.read("xl/workbook.xml"))
        rels = ET.fromstring(zip_file.read("xl/_rels/workbook.xml.rels"))
        rid_to_target = {
            rel.attrib["Id"]: rel.attrib["Target"]
            for rel in rels
        }

        out: Dict[str, List[List[str]]] = {}
        for sheet in workbook.find("a:sheets", NS_XLSX) or []:
            name = sheet.attrib.get("name", "Sheet")
            rid = sheet.attrib.get(f"{{{NS_XLSX['r']}}}id")
            target = rid_to_target.get(rid or "")
            if not target:
                continue
            sheet_path = "xl/" + target.lstrip("/")
            root = ET.fromstring(zip_file.read(sheet_path))
            rows: List[List[str]] = []
            for row in root.findall(".//a:row", NS_XLSX):
                values: Dict[int, str] = {}
                max_col = 0
                for cell in row.findall("a:c", NS_XLSX):
                    ref = cell.attrib.get("r", "")
                    col = cell_ref_to_col(ref)
                    max_col = max(max_col, col)
                    cell_type = cell.attrib.get("t")
                    value = ""
                    if cell_type == "inlineStr":
                        value = "".join(
                            t.text or "" for t in cell.findall(".//a:t", NS_XLSX)
                        )
                    else:
                        v = cell.find("a:v", NS_XLSX)
                        if v is not None and v.text is not None:
                            value = v.text
                            if cell_type == "s":
                                idx = int(value)
                                value = shared_strings[idx] if idx < len(shared_strings) else ""
                    values[col] = value.replace("\r\n", "\n").replace("\r", "\n")
                if values:
                    rows.append([values.get(i, "") for i in range(1, max_col + 1)])
            out[name] = rows
        return out


def write_csv(path: Path, rows: Sequence[Sequence[str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerows(rows)


def row_to_dict(header: Sequence[str], row: Sequence[str]) -> Dict[str, str]:
    return {
        (header[i].strip() or f"column_{i + 1}"): (row[i].strip() if i < len(row) else "")
        for i in range(len(header))
    }


def is_mnemonic(value: str) -> bool:
    stripped = value.strip()
    return stripped not in CATEGORY_ONLY_NAMES and bool(MNEMONIC_RE.match(stripped))


def compact_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def lane_model_for_card(card: Dict[str, object]) -> Optional[Dict[str, str]]:
    name = str(card.get("name") or "")
    category = str(card.get("category") or "")

    if category == "int arith inst":
        return {
            "view": "imm==0: int32[128]; imm==1: int8[512], over one logical 4096-bit/512-byte operand",
            "lane_count": "128 or 512",
            "lane_dtype": "int32 or int8",
            "confidence": "documented by docx Int32/Int8 section",
        }
    if category == "unsigned int arith inst":
        if name == "DP4A":
            return {
                "view": "src int8/uint8 sublanes inside 128 x 32-bit words over one logical 4096-bit operand; dst int32/uint32[128]",
                "lane_count": "128",
                "lane_dtype": "mixed int8 dot into int32/uint32",
                "confidence": "documented by function text and metadata",
            }
        return {
            "view": "imm==0: uint32[128]; imm==1: uint8[512], over one logical 4096-bit/512-byte operand",
            "lane_count": "128 or 512",
            "lane_dtype": "uint32 or uint8",
            "confidence": "documented by docx Unsigned Int32/unsigned Int8 section",
        }
    if category == "float arith inst" or category == "Transcendental Functions":
        if name == "SHFL":
            return {
                "view": "lane permutation; lane width selected by imm[1:0]",
                "lane_count": "32 or 16 depending on mode",
                "lane_dtype": "fp32/fp64-style lane index, not arithmetic dtype",
                "confidence": "documented by function text and OCR notes",
            }
        return {
            "view": "fp32[128] over one logical 4096-bit/512-byte operand",
            "lane_count": "128",
            "lane_dtype": "fp32",
            "confidence": "documented by docx float section",
        }
    if category == "half float arith inst":
        if name in {"H2FP", "FP2H"}:
            return {
                "view": "conversion between fp16[64] and fp32[32] slices",
                "lane_count": "64 input/output fp16 or 32 input/output fp32 depending on direction",
                "lane_dtype": "fp16/fp32 conversion",
                "confidence": "documented by function text",
            }
        return {
            "view": "fp16[256] over one logical 4096-bit/512-byte operand",
            "lane_count": "256",
            "lane_dtype": "fp16",
            "confidence": "documented by docx half-float section",
        }
    if category == "double arith inst":
        return {
            "view": "fp64[64] over one logical 4096-bit/512-byte operand",
            "lane_count": "64",
            "lane_dtype": "fp64",
            "confidence": "documented by docx double section",
        }
    if category == "logic inst":
        dtype = "int32" if name == "ASR" else "uint32/bit32"
        return {
            "view": f"{dtype}[128] over one logical 4096-bit/512-byte operand unless imm selects int8-style mode",
            "lane_count": "128 or instruction-specific",
            "lane_dtype": dtype,
            "confidence": "partly inferred; docx gives detailed typed views for arithmetic families",
        }
    if category == "imm inst":
        return {
            "view": "writes immediate values into selected 32-bit lanes of a logical operand",
            "lane_count": "128 in SIMD128 mode",
            "lane_dtype": "raw32/immediate",
            "confidence": "documented by function text and notes",
        }
    if name == "EXPD32":
        return {
            "view": "extract one byte position from each 32-bit lane and expand to int32[128]",
            "lane_count": "128",
            "lane_dtype": "int8 to int32",
            "confidence": "documented by function text",
        }
    if name == "QMADD":
        return {
            "view": "uint8[512] sources accumulated into internal RX0..RX3 int32 lanes over a logical SIMD128 operand",
            "lane_count": "512 source lanes; RX accumulators are 1024-bit chunks used by int8 pipeline",
            "lane_dtype": "uint8 multiply into int32 accumulator",
            "confidence": "documented by function text and OCR notes",
        }
    if name == "TRCT8":
        return {
            "view": "truncate/reorder RX int32 accumulators into uint8/int8 lanes",
            "lane_count": "mode-specific; 512 output lanes in a full SIMD128 logical operand",
            "lane_dtype": "int32 accumulator to 8-bit lane",
            "confidence": "documented at high level; some imm modes still need verification",
        }
    if name in {"RXIN", "RXOUT"}:
        return {
            "view": "moves raw 1024-bit chunks to/from internal RX/LRX registers",
            "lane_count": "mode-specific",
            "lane_dtype": "raw/RX internal",
            "confidence": "documented by function text",
        }
    if category == "Special Integer instruction":
        return {
            "view": "special integer/control semantics; inspect function text",
            "lane_count": "instruction-specific",
            "lane_dtype": "instruction-specific",
            "confidence": "requires per-instruction reading",
        }
    if category == "Type conversion":
        return {
            "view": "conversion; source/destination lane views are specified by function text",
            "lane_count": "instruction-specific",
            "lane_dtype": "conversion",
            "confidence": "documented by function text, but exact rounding may be unspecified",
        }
    if category == "modify exception regs":
        return {
            "view": "Operand0 simd0 low bits encode mask register configuration",
            "lane_count": "configuration bits, not vector arithmetic",
            "lane_dtype": "bitfield",
            "confidence": "documented by function text and OCR notes",
        }
    if category == "Flow指令":
        return {
            "view": "copies a raw logical operand between PEs; SIMD128 COPYT is expanded into 4 x 1024-bit COPY chunks",
            "lane_count": "not interpreted",
            "lane_dtype": "raw logical operand / 1024-bit chunks",
            "confidence": "documented by function text and examples",
        }
    return None


def base_op_name(name: str) -> str:
    for prefix in ("U", "F", "H", "D"):
        if name.startswith(prefix) and len(name) > 1:
            rest = name[len(prefix):]
            if rest in ARITH_OPS or rest in {"MADD", "LT", "GT"}:
                return rest
    return name


def typed_semantics_for_card(card: Dict[str, object], lane_model: Optional[Dict[str, str]]) -> Optional[str]:
    if not lane_model:
        return None
    name = str(card.get("name") or "")
    dtype = lane_model.get("lane_dtype", "")
    count = lane_model.get("lane_count", "")
    category = str(card.get("category") or "")
    base = base_op_name(name)

    if name == "COND":
        return (
            "imm==0: for i in 0..127 over uint32 lanes; imm==1: for i in 0..511 over uint8 lanes; "
            "dst[i] = (src0[i] > 0) ? src1[i] : old_dst[i]"
        )
    if name == "DP4A":
        return (
            "for i in 0..127: dst.word32[i] accumulates four 8-bit products from "
            "src0.word32[i] and src1.word32[i]; imm selects signed/unsigned interpretation"
        )
    if name == "QMADD":
        return (
            "for byte lane k in 0..511: RX/chunk accumulators += "
            "uint8(src0[k]) * uint8(src1[k]); result is read back by TRCT8/RXOUT"
        )
    if name == "TRCT8":
        return (
            "writes Operand2 by truncating/reordering RX0..RX3 int32 accumulators to 8-bit lanes; "
            "imm selects the packing mode"
        )
    if name == "EXPD32":
        return (
            "for i in 0..127: dst.int32[i] = sign/zero-extended selected byte from src0.word32[i]; "
            "imm=0/1/2/3 selects bits [7:0]/[15:8]/[23:16]/[31:24]"
        )
    if name == "SHFL":
        return "permutes lanes of Operand1/Operand2 according to index operand and imm[1:0] mode"
    if name == "COPYT":
        return "target_pe.operand[dst_idx].logical_bits[0..4095] = source_pe.operand[src_idx].logical_bits[0..4095]; lowered as 4 x 1024-bit COPY chunks"
    if name == "MASK":
        return "reads Operand0 simd0 low 14 bits as {Ext_flag, Ext_offset, Regid_off, double_mark, Maskregno, mask_val}"
    if name in {"RXIN", "RXOUT", "GINST", "GTASK", "GSIMD", "IMM", "FIMM"}:
        return None

    if base == "MADD" and count.isdigit():
        return f"for i in 0..{int(count) - 1}: dst.{dtype}[i] = src0.{dtype}[i] * src1.{dtype}[i] + old_dst.{dtype}[i]"
    if base in ARITH_OPS and count.isdigit():
        end = int(count) - 1
        op = ARITH_OPS[base]
        if op in {"max", "min"}:
            return f"for i in 0..{end}: dst.{dtype}[i] = {op}(src0.{dtype}[i], src1.{dtype}[i])"
        if base == "DIV" and category == "double arith inst":
            return f"for i in 0..{end}: dst.{dtype}[i] = src0.{dtype}[i] / src1.{dtype}[i]"
        return f"for i in 0..{end}: dst.{dtype}[i] = src0.{dtype}[i] {op} src1.{dtype}[i]"
    if name in COMPARE_OPS and count.isdigit():
        end = int(count) - 1
        op = COMPARE_OPS[name]
        return (
            f"for i in 0..{end}: dst.{dtype}[i] = "
            f"(src0.{dtype}[i] {op} src1.{dtype}[i]) ? 1 : 0"
        )
    if category in {"int arith inst", "unsigned int arith inst"} and name in COMPARE_OPS:
        signed = "signed" if category == "int arith inst" else "unsigned"
        op = COMPARE_OPS[name]
        return (
            f"imm==0: for i in 0..127 compare {signed} 32-bit lanes; "
            f"imm==1: for i in 0..511 compare {signed} 8-bit lanes; "
            f"dst[i] = (src0[i] {op} src1[i]) ? 1 : 0"
        )
    if category in {"int arith inst", "unsigned int arith inst"} and base in ARITH_OPS:
        signed = "signed" if category == "int arith inst" else "unsigned"
        op = ARITH_OPS[base]
        if op in {"max", "min"}:
            expr = f"{op}(src0[i], src1[i])"
        else:
            expr = f"src0[i] {op} src1[i]"
        return (
            f"imm==0: for i in 0..127 operate on {signed} 32-bit lanes; "
            f"imm==1: for i in 0..511 operate on {signed} 8-bit lanes; dst[i] = {expr}"
        )
    if name in {"FRCP", "FSQRT", "FRSQRT", "FSIN", "FCOS", "FLOG2", "FEXP2"}:
        return f"for i in 0..127: dst.fp32[i] = {name[1:].lower()}(src0.fp32[i])"
    if name == "DSQRT":
        return "for i in 0..63: dst.fp64[i] = sqrt(src0.fp64[i])"
    if name == "HSIS":
        return "for i in 0..255: dst.fp16[i] = selected special function(src0.fp16[i]); imm[7:0] selects function"
    return None


def enrich_instruction_cards(cards: Sequence[Dict[str, object]]) -> None:
    for card in cards:
        lane_model = lane_model_for_card(card)
        if lane_model:
            card["operand_view"] = lane_model
            typed_semantics = typed_semantics_for_card(card, lane_model)
            if typed_semantics:
                card["typed_semantics"] = typed_semantics


def build_instruction_cards(sheets: Dict[str, List[List[str]]]) -> List[Dict[str, object]]:
    metadata_by_name: Dict[str, Dict[str, str]] = {}
    category_by_name: Dict[str, str] = {}

    sheet1 = sheets.get("Sheet1", [])
    if sheet1:
        header = sheet1[0]
        current_category = ""
        for row in sheet1[1:]:
            record = row_to_dict(header, row)
            category = record.get("type", "").strip()
            name = record.get("instruction", "").strip()
            if category:
                current_category = category
            if is_mnemonic(name):
                record["category"] = current_category
                metadata_by_name[name] = record
                category_by_name[name] = current_category

    cards: Dict[str, Dict[str, object]] = {}
    sheet2 = sheets.get("Sheet2", [])
    if sheet2:
        header = sheet2[0]
        current_category = ""
        for row in sheet2[1:]:
            record = row_to_dict(header, row)
            name = record.get("Name", "").strip()
            function = record.get("Function", "").strip()
            if name and not is_mnemonic(name):
                current_category = name
                continue
            if not is_mnemonic(name):
                continue

            sources = []
            for key in ("Source operand", "column_4", "column_5"):
                value = record.get(key, "").strip()
                if value:
                    sources.append(value)
            dest = record.get("Destination  operand", "").strip()
            cards[name] = {
                "name": name,
                "category": category_by_name.get(name) or current_category,
                "function": function,
                "source_operands": sources,
                "destination_operands": [dest] if dest else [],
                "metadata": metadata_by_name.get(name, {}),
            }

    for name, meta in metadata_by_name.items():
        if name not in cards:
            cards[name] = {
                "name": name,
                "category": meta.get("category", ""),
                "function": "",
                "source_operands": [],
                "destination_operands": [],
                "metadata": meta,
            }

    return [cards[name] for name in sorted(cards)]


def extract_docx_text(path: Path, media_dir: Path) -> Dict[str, object]:
    media_dir.mkdir(parents=True, exist_ok=True)
    with ZipFile(path) as zip_file:
        root = ET.fromstring(zip_file.read("word/document.xml"))
        body = root.find("w:body", NS_DOCX)
        if body is None:
            return {"blocks": [], "sections": {}}

        rels_root = ET.fromstring(zip_file.read("word/_rels/document.xml.rels"))
        rels = {
            rel.attrib["Id"]: rel.attrib.get("Target", "")
            for rel in rels_root
        }

        media_names = [
            name for name in zip_file.namelist()
            if name.startswith("word/media/")
        ]
        for name in media_names:
            target = media_dir / Path(name).name
            target.write_bytes(zip_file.read(name))

        blocks: List[Dict[str, object]] = []
        for child in list(body):
            tag = child.tag.rsplit("}", 1)[-1]
            if tag == "p":
                text = "".join(t.text or "" for t in child.findall(".//w:t", NS_DOCX)).strip()
                if text:
                    blocks.append({"type": "paragraph", "text": text})
                image_targets: List[str] = []
                for blip in child.findall(".//a:blip", NS_DOCX):
                    rid = blip.attrib.get(f"{{{NS_DOCX['r']}}}embed") or blip.attrib.get(
                        f"{{{NS_DOCX['r']}}}link"
                    )
                    if rid and rels.get(rid):
                        image_targets.append(rels[rid])
                for image_data in child.findall(".//v:imagedata", NS_DOCX):
                    rid = image_data.attrib.get(f"{{{NS_DOCX['r']}}}id")
                    if rid and rels.get(rid):
                        image_targets.append(rels[rid])
                for target in image_targets:
                    media_name = Path(target).name
                    blocks.append({"type": "image", "file": media_name})
            elif tag == "tbl":
                rows = []
                for tr in child.findall("w:tr", NS_DOCX):
                    row = []
                    for tc in tr.findall("w:tc", NS_DOCX):
                        cell_text = "".join(t.text or "" for t in tc.findall(".//w:t", NS_DOCX)).strip()
                        row.append(cell_text)
                    rows.append(row)
                blocks.append({"type": "table", "rows": rows})

        sections: Dict[str, List[Dict[str, object]]] = defaultdict(list)
        current = "front_matter"
        for block in blocks:
            if block["type"] == "paragraph":
                text = str(block["text"])
                match = DOC_SECTION_RE.match(text)
                if match:
                    names = [part.strip() for part in match.group(2).split("/") if part.strip()]
                    if names:
                        current = names[0]
            sections[current].append(block)

        return {"blocks": blocks, "sections": dict(sections), "media_count": len(media_names)}


def markdown_escape_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", "<br>")


def write_docx_markdown(path: Path, doc: Dict[str, object], media_rel: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["# DFU3500 SIMD 指令集文档", ""]
    for block in doc["blocks"]:  # type: ignore[index]
        if block["type"] == "paragraph":
            text = str(block["text"])
            if DOC_SECTION_RE.match(text):
                lines.extend([f"## {text}", ""])
            else:
                lines.extend([text, ""])
        elif block["type"] == "image":
            media_name = block.get("file", "")
            if media_name:
                lines.extend([f"![{media_name}]({media_rel}/{media_name})", ""])
            else:
                lines.extend([f"<!-- image extracted under {media_rel}/ -->", ""])
        elif block["type"] == "table":
            rows = block["rows"]
            if rows:
                width = max(len(row) for row in rows)
                padded = [row + [""] * (width - len(row)) for row in rows]
                lines.append("| " + " | ".join(markdown_escape_cell(v) for v in padded[0]) + " |")
                lines.append("| " + " | ".join("---" for _ in range(width)) + " |")
                for row in padded[1:]:
                    lines.append("| " + " | ".join(markdown_escape_cell(v) for v in row) + " |")
                lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def normalize_docx_heading(text: str) -> str:
    return text.strip().strip(":：").replace(" ", "")


def block_to_plain_text(block: Dict[str, object]) -> str:
    if block["type"] == "paragraph":
        return str(block["text"])
    if block["type"] == "image":
        media_name = str(block.get("file", ""))
        return f"[image: {media_name}]" if media_name else "[image]"
    if block["type"] == "table":
        rows = block.get("rows") or []
        if isinstance(rows, list):
            return "\n".join(" | ".join(str(cell) for cell in row) for row in rows)
    return ""


def docx_family_from_heading(text: str, current: str) -> str:
    compact = text.replace(" ", "").lower()
    if "halffloat" in compact or "half" in compact and "指令" in compact:
        return "half"
    if compact == "float指令":
        return "float"
    if compact == "double指令":
        return "double"
    if "int32/int8" in compact and "unsigned" not in compact:
        return "signed_int_imm_mode"
    if "unsignedint32/unsignedint8" in compact:
        return "unsigned_int_imm_mode"
    if "特殊指令" in compact:
        return "special"
    return current


def build_docx_instruction_sections(
    doc: Dict[str, object],
    known_names: Sequence[str],
) -> Dict[str, Dict[str, str]]:
    known = {name: name for name in known_names}
    sections: Dict[str, Dict[str, object]] = {}
    current_name: Optional[str] = None
    current_family = ""

    for block in doc["blocks"]:  # type: ignore[index]
        text = block_to_plain_text(block).strip()
        if not text:
            continue
        if block["type"] == "paragraph":
            normalized = normalize_docx_heading(text)
            current_family = docx_family_from_heading(text, current_family)
            if normalized in known:
                current_name = known[normalized]
                sections.setdefault(current_name, {"family": current_family, "blocks": []})
                sections[current_name]["family"] = current_family
                continue
        if current_name:
            sections[current_name].setdefault("blocks", []).append(text)

    out: Dict[str, Dict[str, str]] = {}
    for name, section in sections.items():
        blocks = [str(v) for v in section.get("blocks", [])]
        text = "\n\n".join(blocks).strip()
        out[name] = {
            "family": str(section.get("family", "")),
            "text": text,
            "typed_view": infer_docx_typed_view(name, str(section.get("family", "")), text),
        }
    return out


def infer_docx_typed_view(name: str, family: str, text: str) -> str:
    compact = compact_text(text)
    multi = re.search(
        r"(\d+)/(\d+)个SIMD分量.*?每个分量(\d+)bit/(\d+)bit",
        compact,
    )
    if multi:
        lanes0, lanes1, bits0, bits1 = multi.groups()
        return (
            f"imm==0: {lanes0} lanes x {bits0} bits; "
            f"imm==1: {lanes1} lanes x {bits1} bits"
        )

    single = re.search(r"(\d+)个SIMD分量.*?每个分量(\d+)bit", compact)
    if single:
        lanes, bits = single.groups()
        total_bits = int(lanes) * int(bits)
        return f"{lanes} lanes x {bits} bits = {total_bits} bits"

    value_range = re.search(r"Value\(Operand index 2\)\s*\((\d+):0\)", compact)
    if value_range:
        lanes = int(value_range.group(1)) + 1
        if family == "half":
            return f"{lanes} lanes x 16 bits = {lanes * 16} bits"
        if family == "float":
            return f"{lanes} lanes x 32 bits = {lanes * 32} bits"
        if family == "double":
            return f"{lanes} lanes x 64 bits = {lanes * 64} bits"

    if family == "signed_int_imm_mode":
        return "imm==0: signed int32[128]; imm==1: signed int8[512]"
    if family == "unsigned_int_imm_mode":
        return "imm==0: uint32[128]; imm==1: uint8[512]"
    return ""


def enrich_cards_with_docx_sections(
    cards: Sequence[Dict[str, object]],
    sections: Dict[str, Dict[str, str]],
) -> None:
    for card in cards:
        name = str(card.get("name") or "")
        section = sections.get(name)
        if not section:
            continue
        card["docx_section"] = f"docx/instruction_sections/{name}.md"
        if section.get("family"):
            card["docx_family"] = section["family"]
        if section.get("typed_view"):
            card["docx_typed_view"] = section["typed_view"]


def write_docx_instruction_sections(
    out_dir: Path,
    sections: Dict[str, Dict[str, str]],
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    for name, section in sorted(sections.items()):
        lines = [f"# {name}", ""]
        if section.get("family"):
            lines.extend([f"- docx_family: {section['family']}", ""])
        if section.get("typed_view"):
            lines.extend([f"- docx_typed_view: {section['typed_view']}", ""])
        lines.extend(["## Extracted Text", "", section.get("text", "").strip(), ""])
        (out_dir / f"{name}.md").write_text("\n".join(lines), encoding="utf-8")


def write_cards(cards: Sequence[Dict[str, object]], out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "instruction_cards.jsonl").open("w", encoding="utf-8") as f:
        for card in cards:
            f.write(json.dumps(card, ensure_ascii=False) + "\n")

    lines = ["# DFU3500 SIMD Instruction Cards", ""]
    for card in cards:
        lines.append(f"## {card['name']}")
        if card.get("category"):
            lines.append(f"- category: {card['category']}")
        if card.get("docx_typed_view"):
            lines.append(f"- docx_typed_view: {card['docx_typed_view']}")
        if card.get("docx_family"):
            lines.append(f"- docx_family: {card['docx_family']}")
        if card.get("docx_section"):
            lines.append(f"- docx_section: {card['docx_section']}")
        operand_view = card.get("operand_view") or {}
        if isinstance(operand_view, dict) and operand_view:
            view = operand_view.get("view")
            lane_count = operand_view.get("lane_count")
            lane_dtype = operand_view.get("lane_dtype")
            confidence = operand_view.get("confidence")
            if view:
                lines.append(f"- operand_view: {view}")
            if lane_count:
                lines.append(f"- lane_count: {lane_count}")
            if lane_dtype:
                lines.append(f"- lane_dtype: {lane_dtype}")
            if confidence:
                lines.append(f"- view_confidence: {confidence}")
        if card.get("typed_semantics"):
            lines.append(f"- typed_semantics: {card['typed_semantics']}")
        if card.get("function"):
            lines.append(f"- function: {card['function']}")
        sources = card.get("source_operands") or []
        dests = card.get("destination_operands") or []
        if sources:
            lines.append(f"- sources: {', '.join(str(v) for v in sources)}")
        if dests:
            lines.append(f"- destinations: {', '.join(str(v) for v in dests)}")
        metadata = card.get("metadata") or {}
        if isinstance(metadata, dict):
            notes = {
                k: v for k, v in metadata.items()
                if k not in {"type", "instruction", "category"} and str(v).strip()
            }
            for key, value in notes.items():
                lines.append(f"- {key}: {value}")
        lines.append("")
    (out_dir / "instruction_cards.md").write_text("\n".join(lines), encoding="utf-8")


def write_summary(path: Path, cards: Sequence[Dict[str, object]], doc: Dict[str, object]) -> None:
    categories: Dict[str, int] = defaultdict(int)
    for card in cards:
        categories[str(card.get("category") or "uncategorized")] += 1

    lines = [
        "# DFU3500 SIMD 指令材料抽取结果",
        "",
        "本目录由 `tools/extract_instruction_docs.py` 从原始 xlsx/docx 生成。",
        "原始材料不做修改。",
        "",
        "## 文件",
        "",
        "- `xlsx/Sheet1.csv`: 指令列表、pipeline、拍数、imm 字段等。",
        "- `xlsx/Sheet2.csv`: 指令功能和 operand 输入输出说明。",
        "- `OPERAND_LANE_MODEL.md`: 解释 SIMD128 logical operand 与 1024-bit chunk 如何按指令解释成不同 lane。",
        "- `UNCLEAR_SEMANTICS_BACKLOG.md`: 记录暂时不阻塞、等实际遇到再继续研究的指令语义疑点。",
        "- `instruction_cards.jsonl`: 每行一个指令卡片，适合 agent 按 mnemonic 检索。",
        "- `instruction_cards.md`: 人类可读的指令卡片。",
        "- `docx/dfu3500-simd-instruction-doc.md`: docx 正文和表格的 Markdown 抽取。",
        "- `docx/instruction_sections/`: 从 docx 按 mnemonic 切出的原文段落，适合追溯 typed view。",
        "- `docx/media/`: docx 中的图片原样抽取。",
        "- `docx/media_ocr/media_ocr.md`: docx 图片的 OCR 原文，按图片编号排列。",
        "- `docx/media_ocr/media_ocr_index.jsonl`: 每张图片的尺寸、OCR 分数、标签和文本。",
        "- `OCR_DERIVED_NOTES.md`: 对高信号图片 OCR 的整理和推断，适合放进 agent context。",
        "",
        "## 统计",
        "",
        f"- instruction cards: {len(cards)}",
        f"- docx media files: {doc.get('media_count', 0)}",
        "",
        "## 指令类别",
        "",
    ]
    for category, count in sorted(categories.items()):
        lines.append(f"- {category}: {count}")
    lines.extend([
        "",
        "## Agent 使用建议",
        "",
        "优先读取 `instruction_cards.jsonl` 中某个 mnemonic 的卡片；",
        "如果问题涉及 SIMD128/SIMD32 尺度、4096bit operand 或 1024bit chunk 如何划分成 lane，先读 `OPERAND_LANE_MODEL.md`；",
        "需要更详细叙述时，再读取 `docx/dfu3500-simd-instruction-doc.md` 中对应章节。",
        "如果该指令的关键解释藏在图片里，优先读取 `OCR_DERIVED_NOTES.md` 的对应小节；",
        "只有字段仍不清楚时，再打开 `docx/media_ocr/raw/imageNN.txt` 或原图。",
        "不要把整份 docx Markdown 一次塞进上下文。",
        "",
    ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--xlsx", type=Path, required=True)
    parser.add_argument("--docx", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=Path("docs/instruction-set/dfu3500-simd"))
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)

    sheets = read_xlsx_sheets(args.xlsx)
    xlsx_dir = args.out / "xlsx"
    for name, rows in sheets.items():
        write_csv(xlsx_dir / f"{name}.csv", rows)

    docx_dir = args.out / "docx"
    doc = extract_docx_text(args.docx, docx_dir / "media")
    write_docx_markdown(
        docx_dir / "dfu3500-simd-instruction-doc.md",
        doc,
        "media",
    )

    cards = build_instruction_cards(sheets)
    docx_sections = build_docx_instruction_sections(
        doc,
        [str(card.get("name")) for card in cards],
    )
    write_docx_instruction_sections(docx_dir / "instruction_sections", docx_sections)
    enrich_cards_with_docx_sections(cards, docx_sections)
    enrich_instruction_cards(cards)
    write_cards(cards, args.out)

    write_summary(args.out / "README.md", cards, doc)
    print(f"wrote {args.out}")
    print(f"instruction cards: {len(cards)}")
    print(f"docx media files: {doc.get('media_count', 0)}")


if __name__ == "__main__":
    main()
