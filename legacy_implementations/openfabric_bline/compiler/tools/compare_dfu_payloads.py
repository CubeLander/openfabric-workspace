#!/usr/bin/env python3
"""Compare two DFU payload directories with the profile-driven binary decoder."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gpdpu_compiler.decoder.binary_diff import diff_binary_bytes  # noqa: E402
from gpdpu_compiler.decoder.binary_decoder import get_profile  # noqa: E402
from gpdpu_compiler.decoder.dfu3500_diagnostics import (  # noqa: E402
    diff_dfu3500_micc_control,
    summarize_dfu3500_micc_control,
)


PAYLOAD_FILES = {
    "cbuf": (
        "result/cbuf_file.bin",
        "config/cbuf_file.bin",
        "cbuf_file.bin",
    ),
    "micc": (
        "result/micc_file.bin",
        "config/micc_file.bin",
        "micc_file.bin",
    ),
}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", default=None)
    parser.add_argument("--good", type=Path, required=True)
    parser.add_argument("--bad", type=Path, required=True)
    parser.add_argument("--max-diffs", type=int, default=200)
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--fail-on-diff", action="store_true")
    args = parser.parse_args(argv)

    profile = get_profile(args.profile)
    reports = []
    diagnostics = []
    micc_control = {}
    good_manifest = _read_manifest(args.good)
    bad_manifest = _read_manifest(args.bad)
    file_conformance = {}
    for file_kind in ("cbuf", "micc"):
        good_path = _find_payload_file(args.good, file_kind)
        bad_path = _find_payload_file(args.bad, file_kind)
        if good_path is None or bad_path is None:
            diagnostics.append(
                {
                    "severity": "error",
                    "file_kind": file_kind,
                    "message": (
                        f"missing {file_kind}: good={good_path} bad={bad_path}"
                    ),
                }
            )
            continue
        file_conformance[file_kind] = _file_conformance(
            profile=profile,
            file_kind=file_kind,
            good_path=good_path,
            bad_path=bad_path,
            good_manifest=good_manifest,
            bad_manifest=bad_manifest,
        )
        report = diff_binary_bytes(
            good_path.read_bytes(),
            bad_path.read_bytes(),
            file_kind=file_kind,
            profile=profile,
            max_diffs=args.max_diffs,
        )
        report["left"]["path"] = str(good_path)
        report["right"]["path"] = str(bad_path)
        reports.append(report)
        if file_kind == "micc":
            good_control = summarize_dfu3500_micc_control(
                good_path.read_bytes(),
                profile=profile,
            )
            bad_control = summarize_dfu3500_micc_control(
                bad_path.read_bytes(),
                profile=profile,
            )
            micc_control = {
                "good": good_control,
                "bad": bad_control,
                "diff": diff_dfu3500_micc_control(good_control, bad_control),
            }

    payload = {
        "schema_version": "dfu_payload_compare_report_v1",
        "profile": {
            "profile_id": profile.profile_id,
            "profile_sha256": profile.profile_sha256(),
            "target": profile.target,
        },
        "good": str(args.good),
        "bad": str(args.bad),
        "status": "error" if diagnostics else "ok",
        "diagnostics": diagnostics,
        "manifest": {
            "good": good_manifest,
            "bad": bad_manifest,
        },
        "file_conformance": file_conformance,
        "reports": reports,
        "micc_control": micc_control,
        "summary": _summarize_reports(reports),
    }
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True),
            encoding="utf-8",
        )
    _emit(payload, args.format)
    if diagnostics:
        return 3
    if args.fail_on_diff and payload["summary"]["byte_diff_count"]:
        return 1
    return 0


def _find_payload_file(root: Path, file_kind: str) -> Path | None:
    for relative in PAYLOAD_FILES[file_kind]:
        path = root / relative
        if path.is_file():
            return path
    matches = sorted(root.rglob(PAYLOAD_FILES[file_kind][-1]))
    return matches[0] if matches else None


def _read_manifest(root: Path) -> dict[str, str]:
    manifest_path = root / "MANIFEST.txt"
    if not manifest_path.is_file():
        matches = sorted(root.rglob("MANIFEST.txt"))
        manifest_path = matches[0] if matches else manifest_path
    if not manifest_path.is_file():
        return {}
    values: dict[str, str] = {}
    for line in manifest_path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _file_conformance(
    *,
    profile: Any,
    file_kind: str,
    good_path: Path,
    bad_path: Path,
    good_manifest: dict[str, str],
    bad_manifest: dict[str, str],
) -> dict[str, Any]:
    expected_size = profile.files[file_kind].size(profile)
    good_size = good_path.stat().st_size
    bad_size = bad_path.stat().st_size
    return {
        "expected_profile_size": expected_size,
        "good": _side_conformance(good_path, good_size, expected_size, good_manifest),
        "bad": _side_conformance(bad_path, bad_size, expected_size, bad_manifest),
        "ok": good_size == expected_size and bad_size == expected_size,
    }


def _side_conformance(
    path: Path,
    actual_size: int,
    expected_profile_size: int,
    manifest: dict[str, str],
) -> dict[str, Any]:
    manifest_sizes = {
        key: int(value)
        for key, value in manifest.items()
        if key.endswith(f"{path.name}_size") and value.isdigit()
    }
    return {
        "path": str(path),
        "actual_size": actual_size,
        "profile_size_ok": actual_size == expected_profile_size,
        "manifest_declared_sizes": manifest_sizes,
        "manifest_size_ok": (
            all(size == actual_size for size in manifest_sizes.values())
            if manifest_sizes
            else None
        ),
    }


def _summarize_reports(reports: list[dict[str, Any]]) -> dict[str, Any]:
    summary = {
        "byte_diff_count": 0,
        "diff_group_count": 0,
        "field_diff_count": 0,
        "padding_diff_count": 0,
        "unknown_range_diff_count": 0,
        "files": {},
    }
    for report in reports:
        file_kind = report["left"]["kind"]
        file_summary = {
            "byte_diff_count": report["byte_diff_count"],
            "diff_group_count": report["diff_group_count"],
            "field_diff_count": report["field_diff_count"],
            "padding_diff_count": report["padding_diff_count"],
            "unknown_range_diff_count": report["unknown_range_diff_count"],
            "top_diff_paths": [
                diff.get("path")
                for diff in report.get("diffs", [])[:10]
            ],
        }
        summary["files"][file_kind] = file_summary
        for key in (
            "byte_diff_count",
            "diff_group_count",
            "field_diff_count",
            "padding_diff_count",
            "unknown_range_diff_count",
        ):
            summary[key] += file_summary[key]
    return summary


def _emit(payload: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
        return
    print(
        f"compare good={payload['good']} bad={payload['bad']} "
        f"status={payload['status']}"
    )
    summary = payload["summary"]
    print(
        f"total: byte_diff_count={summary['byte_diff_count']} "
        f"diff_group_count={summary['diff_group_count']} "
        f"field_diff_count={summary['field_diff_count']} "
        f"padding_diff_count={summary['padding_diff_count']} "
        f"unknown_range_diff_count={summary['unknown_range_diff_count']}"
    )
    for file_kind, conformance in payload.get("file_conformance", {}).items():
        if conformance["ok"]:
            continue
        print(
            f"{file_kind}_conformance: expected={conformance['expected_profile_size']} "
            f"good={conformance['good']['actual_size']} "
            f"bad={conformance['bad']['actual_size']}"
        )
        if not conformance["good"]["profile_size_ok"]:
            print(f"  good size mismatch: {conformance['good']['path']}")
        if not conformance["bad"]["profile_size_ok"]:
            print(f"  bad size mismatch: {conformance['bad']['path']}")
    for file_kind, file_summary in summary["files"].items():
        print(
            f"{file_kind}: byte_diff_count={file_summary['byte_diff_count']} "
            f"diff_group_count={file_summary['diff_group_count']} "
            f"field_diff_count={file_summary['field_diff_count']}"
        )
        for path in file_summary["top_diff_paths"]:
            print(f"  {path}")
    control = payload.get("micc_control", {})
    control_diff = control.get("diff", {})
    if control_diff.get("available"):
        task_count = control_diff["active_task_count"]
        subtask_count = control_diff["active_subtask_count"]
        print(
            "micc_control: "
            f"active_tasks {task_count['left']} -> {task_count['right']}; "
            f"active_subtasks {subtask_count['left']} -> {subtask_count['right']}; "
            f"task_diff_count={control_diff['task_diff_count']} "
            f"subtask_diff_count={control_diff['subtask_diff_count']}"
        )
        for task_diff in control_diff["task_diffs"][:8]:
            print(
                f"  task{task_diff['task_id']} changed: "
                f"{', '.join(task_diff['changed_fields'])}"
            )
        for subtask_diff in control_diff["subtask_diffs"][:8]:
            print(
                f"  task{subtask_diff['task']}/subtask{subtask_diff['subtask']} "
                f"changed: {', '.join(subtask_diff['changed_fields'])}"
            )
    for diagnostic in payload["diagnostics"]:
        print(f"diagnostic[{diagnostic['severity']}]: {diagnostic['message']}")


if __name__ == "__main__":
    raise SystemExit(main())
