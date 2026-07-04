#!/usr/bin/env python3
"""OCR extracted instruction-document media into reviewable text files."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Dict, Iterable, List, Tuple


PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def png_size(path: Path) -> Tuple[int, int]:
    data = path.read_bytes()[:24]
    if not data.startswith(PNG_SIGNATURE) or data[12:16] != b"IHDR":
        return (0, 0)
    return (int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big"))


def natural_key(path: Path) -> Tuple[str, int]:
    match = re.search(r"(\d+)", path.stem)
    return (re.sub(r"\d+", "", path.stem), int(match.group(1)) if match else -1)


def normalize_ocr_text(text: str) -> str:
    lines = []
    for raw in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        line = raw.strip()
        if line:
            lines.append(re.sub(r"[ \t]+", " ", line))
    return "\n".join(lines)


def ocr_image(path: Path, lang: str, psm_modes: Iterable[int]) -> Tuple[str, int]:
    best_text = ""
    best_psm = 0
    for psm in psm_modes:
        result = subprocess.run(
            ["tesseract", str(path), "stdout", "-l", lang, "--psm", str(psm)],
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            text=True,
        )
        text = normalize_ocr_text(result.stdout)
        if score_text(text) > score_text(best_text):
            best_text = text
            best_psm = psm
    return best_text, best_psm


def score_text(text: str) -> int:
    compact = re.sub(r"\s+", "", text)
    alnum_or_cjk = re.findall(r"[A-Za-z0-9_\u4e00-\u9fff]+", compact)
    return sum(len(part) for part in alnum_or_cjk)


def classify_text(text: str) -> List[str]:
    tags = []
    if re.search(r"\b(imm|extra_fields|src|dst|simd|mode|bit|Byte|operand|index)\b", text, re.I):
        tags.append("encoding")
    if re.search(r"\b(Value|Operand|RX|src\d|dst\d|HMMAL|QMADD|TRCTT|COPY|SHFL)\b", text):
        tags.append("semantics")
    if re.search(r"[\u4e00-\u9fff]", text):
        tags.append("zh")
    if not tags:
        tags.append("low-signal")
    return tags


def write_markdown(path: Path, records: List[Dict[str, object]]) -> None:
    lines = [
        "# DFU3500 SIMD Docx Media OCR",
        "",
        "本文件由 `tools/ocr_instruction_media.py` 生成。",
        "OCR 是原始识别文本，可能有错字；需要和图片、xlsx 指令卡片、examples 交叉确认。",
        "",
    ]
    for record in records:
        media = record["media"]
        width = record["width"]
        height = record["height"]
        tags = ", ".join(record["tags"])  # type: ignore[arg-type]
        lines.extend([
            f"## {media}",
            "",
            f"- size: {width}x{height}",
            f"- psm: {record['psm']}",
            f"- tags: {tags}",
            f"- text_score: {record['text_score']}",
            "",
            f"![{media}](../media/{media})",
            "",
            "```text",
            str(record["text"]),
            "```",
            "",
        ])
    path.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--media-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--lang", default="chi_sim+eng")
    parser.add_argument("--psm", nargs="*", type=int, default=[6, 11])
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    raw_dir = args.out / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    records: List[Dict[str, object]] = []
    images = sorted(args.media_dir.glob("*.png"), key=natural_key)
    for image in images:
        width, height = png_size(image)
        text, psm = ocr_image(image, args.lang, args.psm)
        (raw_dir / f"{image.stem}.txt").write_text(text + "\n", encoding="utf-8")
        record = {
            "media": image.name,
            "width": width,
            "height": height,
            "psm": psm,
            "text_score": score_text(text),
            "tags": classify_text(text),
            "text": text,
        }
        records.append(record)

    with (args.out / "media_ocr_index.jsonl").open("w", encoding="utf-8") as f:
        for record in records:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
    write_markdown(args.out / "media_ocr.md", records)
    print(f"wrote {args.out}")
    print(f"ocr images: {len(records)}")


if __name__ == "__main__":
    main()
