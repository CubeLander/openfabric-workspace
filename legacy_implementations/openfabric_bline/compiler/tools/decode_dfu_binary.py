#!/usr/bin/env python3
"""Decode DFU binary artifacts with an explicit target profile."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gpdpu_compiler.decoder.binary_decoder import (  # noqa: E402
    decode_row,
    decode_summary,
    get_profile,
    list_profiles,
    lookup_offset,
)
from gpdpu_compiler.decoder.binary_diff import diff_binary_bytes  # noqa: E402
from gpdpu_compiler.decoder.coverage import make_coverage_report  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--list-profiles", action="store_true")
    parser.add_argument("--dump-profile", action="store_true")
    parser.add_argument("--coverage", action="store_true")
    parser.add_argument("--kind", help="file kind, e.g. cbuf, micc, insts")
    parser.add_argument("--input", type=Path)
    parser.add_argument("--right", type=Path, help="right-hand input for --diff")
    parser.add_argument("--summary", action="store_true")
    parser.add_argument("--only-nonzero", action="store_true")
    parser.add_argument("--section", help="section name for multi-section files")
    parser.add_argument("--row", type=int, help="decode one row in a section")
    parser.add_argument("--row-range", help="decode row range START:END")
    parser.add_argument("--max-array-elements", type=int, default=16)
    parser.add_argument("--max-records", type=int, default=200)
    parser.add_argument("--offset", help="decode a byte offset, accepts 0x...")
    parser.add_argument("--diff", action="store_true")
    parser.add_argument("--fail-on-diff", action="store_true")
    parser.add_argument("--fail-on-padding-diff", action="store_true")
    parser.add_argument("--fail-on-unknown-range", action="store_true")
    parser.add_argument("--max-diffs", type=int, default=200)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    profile = get_profile(args.profile)
    if args.list_profiles:
        for builtin in list_profiles():
            print(f"{builtin.profile_id}\t{builtin.target}\t{builtin.layout_status}")
        return 0
    if args.dump_profile:
        _emit(profile.to_json(), args.format)
        return 0
    if args.coverage:
        _emit(make_coverage_report(profile.profile_id), args.format)
        return 0

    if not args.kind:
        parser.error("--kind is required unless listing/dumping profiles or coverage")
    if not args.input:
        parser.error("--input is required")
    data = args.input.read_bytes()

    if args.summary:
        report = decode_summary(
            data,
            file_kind=args.kind,
            profile=profile,
            only_nonzero=args.only_nonzero,
        )
        report["input"]["path"] = str(args.input)
        _emit(report, args.format)
        return 3 if report["status"] == "error" else 0

    if args.row is not None:
        report = decode_row(
            data,
            file_kind=args.kind,
            section_name=args.section,
            row_index=args.row,
            profile=profile,
            max_array_elements=args.max_array_elements,
        )
        report["input"]["path"] = str(args.input)
        _emit(report, args.format)
        return 3 if report["status"] == "error" else 0

    if args.row_range is not None:
        try:
            start, end = _parse_row_range(args.row_range)
        except argparse.ArgumentTypeError as exc:
            parser.error(str(exc))
        records = []
        status = "ok"
        diagnostics = []
        for row_index in range(start, min(end, start + args.max_records)):
            row_report = decode_row(
                data,
                file_kind=args.kind,
                section_name=args.section,
                row_index=row_index,
                profile=profile,
                max_array_elements=args.max_array_elements,
            )
            if row_report["status"] != "ok":
                status = "error"
                diagnostics.extend(row_report.get("diagnostics", []))
                break
            records.append(row_report["row"])
        report = {
            "schema_version": "dfu_binary_row_range_report_v1",
            "profile": {
                "profile_id": profile.profile_id,
                "profile_sha256": profile.profile_sha256(),
                "target": profile.target,
            },
            "input": {
                "path": str(args.input),
                "kind": args.kind,
                "size": len(data),
            },
            "status": status,
            "row_range": {"start": start, "end": end, "emitted": len(records)},
            "rows": records,
            "diagnostics": diagnostics,
        }
        _emit(report, args.format)
        return 3 if status == "error" else 0

    if args.offset is not None:
        offset = int(args.offset, 0)
        _emit(
            lookup_offset(
                data,
                file_kind=args.kind,
                offset=offset,
                profile=profile,
            ).to_json(),
            args.format,
        )
        return 0

    if args.diff:
        if args.right is None:
            parser.error("--right is required with --diff")
        report = diff_binary_bytes(
            data,
            args.right.read_bytes(),
            file_kind=args.kind,
            profile=profile,
            max_diffs=args.max_diffs,
        )
        _emit(report, args.format)
        if _diff_should_fail(report, args):
            return 1
        return 0

    parser.error(
        "one of --summary, --row, --row-range, --offset, --diff, "
        "--list-profiles, --dump-profile is required"
    )
    return 2


def _parse_row_range(value: str) -> tuple[int, int]:
    if ":" not in value:
        raise argparse.ArgumentTypeError("--row-range must be START:END")
    start_text, end_text = value.split(":", 1)
    start = int(start_text, 0)
    end = int(end_text, 0)
    if start < 0 or end < start:
        raise argparse.ArgumentTypeError("--row-range must satisfy 0 <= START <= END")
    return start, end


def _diff_should_fail(report: dict[str, Any], args: argparse.Namespace) -> bool:
    if args.fail_on_diff and report["byte_diff_count"]:
        return True
    if args.fail_on_padding_diff and report["padding_diff_count"]:
        return True
    if args.fail_on_unknown_range and report["unknown_range_diff_count"]:
        return True
    return False


def _emit(payload: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    if "row" in payload:
        _emit_row_text(payload)
        return
    if payload.get("schema_version") == "dfu_binary_decode_report_v1":
        _emit_summary_text(payload)
        return
    if payload.get("schema_version") == "dfu_binary_diff_report_v1":
        _emit_diff_text(payload)
        return
    if payload.get("schema_version") == "dfu_binary_row_range_report_v1":
        _emit_row_range_text(payload)
        return
    if payload.get("schema_version") == "dfu_binary_decoder_coverage_v1":
        _emit_coverage_text(payload)
        return
    if "classification" in payload:
        _emit_lookup_text(payload)
        return
    print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))


def _emit_summary_text(report: dict[str, Any]) -> None:
    print(
        f"{report['input']['kind']}: size={report['input']['size']} "
        f"sha256={report['input']['sha256']}"
    )
    print(
        f"profile={report['profile']['profile_id']} "
        f"status={report['status']}"
    )
    for diagnostic in report.get("diagnostics", []):
        print(f"diagnostic[{diagnostic['severity']}]: {diagnostic['message']}")
    for section in report.get("sections", []):
        active = section["active_ish"]
        print(
            f"section {section['name']}: offset={section['offset']} "
            f"size={section['size']} row={section['row_struct']} "
            f"row_size={section['row_size']} rows={section['row_count']} "
            f"active-ish={active['nonzero_row_count']}"
        )


def _emit_lookup_text(lookup: dict[str, Any]) -> None:
    print(f"classification={lookup['classification']}")
    if lookup.get("path"):
        print(f"path={lookup['path']}")
    if lookup.get("section"):
        print(
            f"section={lookup['section']} row_index={lookup['row_index']} "
            f"row_offset={lookup['row_offset']}"
        )
    if lookup.get("field"):
        annotation = lookup.get("annotation") or {}
        mnemonic = annotation.get("mnemonic")
        suffix = f" mnemonic={mnemonic}" if mnemonic else ""
        print(
            f"field={lookup['field']} type={lookup['field_type']} "
            f"byte_index={lookup['byte_index_in_field']} "
            f"value={lookup['value']} raw=0x{lookup['raw_hex']}{suffix}"
        )
    if lookup.get("diagnostic"):
        print(f"diagnostic={lookup['diagnostic']}")


def _emit_row_text(report: dict[str, Any]) -> None:
    row = report["row"]
    print(
        f"{row['path']}: offset={row['row_abs_offset']} "
        f"size={row['row_size']} struct={row['struct']} nonzero={row['row_nonzero']}"
    )
    for field in row["fields"]:
        if field["decode_status"] == "array_summary":
            print(
                f"  {field['field']}: {field['field_type']}[{field['count']}] "
                f"summary nonzero_elements={field['nonzero_element_count']}"
            )
        elif "values" in field:
            values = ", ".join(str(item["value"]) for item in field["values"])
            print(f"  {field['field']}: {values}")
        else:
            print(
                f"  {field['field']}: {field.get('struct_name')}[{field['count']}] "
                f"decoded"
            )


def _emit_row_range_text(report: dict[str, Any]) -> None:
    print(
        f"rows {report['row_range']['start']}:{report['row_range']['end']} "
        f"emitted={report['row_range']['emitted']} status={report['status']}"
    )
    for row in report["rows"]:
        print(
            f"{row['path']}: offset={row['row_abs_offset']} "
            f"struct={row['struct']} nonzero={row['row_nonzero']}"
        )


def _emit_diff_text(report: dict[str, Any]) -> None:
    print(
        f"byte_diff_count={report['byte_diff_count']} "
        f"diff_group_count={report['diff_group_count']} "
        f"field_diff_count={report['field_diff_count']} "
        f"padding_diff_count={report['padding_diff_count']} "
        f"unknown_range_diff_count={report['unknown_range_diff_count']}"
    )
    for diff in report.get("diffs", []):
        print(
            f"{diff['field_abs_offset']}: {diff['diff_kind']} {diff.get('path')} "
            f"bytes={diff['byte_offsets']} "
            f"raw={diff['left']['raw_hex']}->{diff['right']['raw_hex']}"
        )


def _emit_coverage_text(report: dict[str, Any]) -> None:
    counts = report["status_counts"]
    print(
        f"coverage profile={report['profile_id']} "
        f"implemented={counts['implemented']} "
        f"diagnostic_only={counts['diagnostic_only']} "
        f"documentation_only={counts['documentation_only']} "
        f"out_of_scope={counts['out_of_scope']}"
    )
    for item in report["items"]:
        print(f"{item['status']}: {item['area']} -> {item['owner']}")


if __name__ == "__main__":
    raise SystemExit(main())
