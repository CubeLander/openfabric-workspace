#!/usr/bin/env python3
"""Export B-line debug row artifacts from an emittable-debug layout.

This tool writes quasi-binary row JSON.  It is intentionally not a vendor
binary writer.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gpdpu_compiler.core.stream_compiler.debug_emit import emit_debug_row_artifact
from gpdpu_compiler.core.stream_compiler.vendor_groups import (
    group_debug_rows_vendor_like,
    remap_vendor_like_groups_locally,
    summarize_vendor_like_local_remap_plan,
    summarize_vendor_like_row_group_plan,
)
from gpdpu_compiler.core.stream_compiler.vendor_components import (
    build_vendor_component_plan,
    summarize_vendor_component_plan,
)
from stream_compiler_demo_pipeline import SnapshotProfile, build_demo_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=("gemm_no_relu", "gemm_relu"),
        default="gemm_no_relu",
        help="Demo profile. Only gemm_no_relu currently emits debug rows.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        help="Directory for instruction_rows.json, zero_boundaries.json, summary.json.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print only summary JSON to stdout.",
    )
    return parser.parse_args()


def build_debug_row_artifact(profile: SnapshotProfile) -> dict[str, object]:
    artifacts = build_demo_pipeline(profile)
    artifact = emit_debug_row_artifact(artifacts.binary_layout)
    return json.loads(json.dumps(artifact.to_plan(), sort_keys=True))


def main() -> None:
    args = parse_args()
    artifact = build_debug_row_artifact(args.profile)
    summary = summarize_debug_row_artifact_from_plan(artifact)
    vendor_groups = group_debug_rows_vendor_like_from_plan(artifact)
    vendor_group_summary = summarize_vendor_like_row_group_plan(vendor_groups)
    vendor_local_remap = remap_vendor_like_groups_locally(vendor_groups)
    vendor_local_remap_summary = summarize_vendor_like_local_remap_plan(vendor_local_remap)
    vendor_components = build_vendor_component_plan(vendor_local_remap)
    vendor_component_summary = summarize_vendor_component_plan(vendor_components)
    summary["vendor_group_summary"] = vendor_group_summary
    summary["vendor_local_remap_summary"] = vendor_local_remap_summary
    summary["vendor_component_summary"] = vendor_component_summary

    if args.summary_only or args.out_dir is None:
        sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")
        if any(diagnostic["severity"] == "error" for diagnostic in artifact["diagnostics"]):
            raise SystemExit(1)
        return

    args.out_dir.mkdir(parents=True, exist_ok=True)
    (args.out_dir / "instruction_rows.json").write_text(
        json.dumps(artifact["instruction_rows"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.out_dir / "zero_boundaries.json").write_text(
        json.dumps(artifact["zero_boundaries"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.out_dir / "summary.json").write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.out_dir / "vendor_groups.json").write_text(
        json.dumps(vendor_groups.to_plan()["groups"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.out_dir / "vendor_local_remap.json").write_text(
        json.dumps(vendor_local_remap.to_plan()["groups"], indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.out_dir / "vendor_components.json").write_text(
        json.dumps(vendor_components.to_plan(), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(args.out_dir)
    if any(diagnostic["severity"] == "error" for diagnostic in artifact["diagnostics"]):
        raise SystemExit(1)


def summarize_debug_row_artifact_from_plan(artifact: dict[str, object]) -> dict[str, object]:
    instruction_rows = artifact["instruction_rows"]
    zero_boundaries = artifact["zero_boundaries"]
    diagnostics = artifact["diagnostics"]
    if not isinstance(instruction_rows, list) or not isinstance(zero_boundaries, list):
        raise TypeError("debug artifact rows must be lists")
    if not isinstance(diagnostics, list):
        raise TypeError("debug artifact diagnostics must be a list")
    opcode_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    zero_role_counts: dict[str, int] = {}
    diagnostic_severity_counts: dict[str, int] = {}
    for row in instruction_rows:
        if not isinstance(row, dict):
            raise TypeError("instruction row must be a dict")
        opcode = str(row["opcode"])
        role = str(row["role"])
        opcode_counts[opcode] = opcode_counts.get(opcode, 0) + 1
        role_counts[role] = role_counts.get(role, 0) + 1
    for row in zero_boundaries:
        if not isinstance(row, dict):
            raise TypeError("zero boundary row must be a dict")
        role = str(row["role"])
        zero_role_counts[role] = zero_role_counts.get(role, 0) + 1
    for diagnostic in diagnostics:
        if not isinstance(diagnostic, dict):
            raise TypeError("diagnostic must be a dict")
        severity = str(diagnostic["severity"])
        diagnostic_severity_counts[severity] = diagnostic_severity_counts.get(severity, 0) + 1
    return {
        "schema_version": 1,
        "artifact": "b_line_debug_row_summary",
        "profile_id": artifact["profile_id"],
        "runnability_state": artifact["runnability_state"],
        "instruction_row_count": len(instruction_rows),
        "zero_boundary_count": len(zero_boundaries),
        "opcode_counts": dict(sorted(opcode_counts.items())),
        "role_counts": dict(sorted(role_counts.items())),
        "zero_boundary_role_counts": dict(sorted(zero_role_counts.items())),
        "diagnostic_severity_counts": dict(sorted(diagnostic_severity_counts.items())),
    }


def group_debug_rows_vendor_like_from_plan(artifact: dict[str, object]):
    from gpdpu_compiler.core.stream_compiler.debug_emit import DebugRowArtifact

    diagnostics = artifact["diagnostics"]
    if not isinstance(diagnostics, list):
        raise TypeError("debug artifact diagnostics must be a list")
    diagnostic_objs = tuple(
        _diagnostic_from_plan(diagnostic)
        for diagnostic in diagnostics
        if isinstance(diagnostic, dict)
    )
    instruction_rows = artifact["instruction_rows"]
    zero_boundaries = artifact["zero_boundaries"]
    if not isinstance(instruction_rows, list) or not isinstance(zero_boundaries, list):
        raise TypeError("debug artifact rows must be lists")
    debug_artifact = DebugRowArtifact(
        profile_id=str(artifact["profile_id"]),
        runnability_state=str(artifact["runnability_state"]),
        instruction_rows=tuple(row for row in instruction_rows if isinstance(row, dict)),
        zero_boundaries=tuple(row for row in zero_boundaries if isinstance(row, dict)),
        diagnostics=diagnostic_objs,
    )
    return group_debug_rows_vendor_like(debug_artifact)


def _diagnostic_from_plan(payload: dict[str, object]):
    from gpdpu_compiler.core.stream_compiler.template_ops import Diagnostic

    evidence_refs = payload.get("evidence_refs", ())
    return Diagnostic(
        severity=str(payload["severity"]),  # type: ignore[arg-type]
        code=str(payload["code"]),
        subject_id=str(payload["subject_id"]),
        message=str(payload["message"]),
        evidence_refs=tuple(str(item) for item in evidence_refs) if isinstance(evidence_refs, list) else (),
    )


if __name__ == "__main__":
    main()
