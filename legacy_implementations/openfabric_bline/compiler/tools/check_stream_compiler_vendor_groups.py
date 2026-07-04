#!/usr/bin/env python3
"""Focused validation for B-line vendor-like debug row grouping."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from gpdpu_compiler.core.stream_compiler.debug_emit import emit_debug_row_artifact
from gpdpu_compiler.core.stream_compiler.vendor_groups import (
    group_debug_rows_vendor_like,
    summarize_vendor_like_row_group_plan,
)
from stream_compiler_demo_pipeline import build_demo_pipeline


EXPECTED_TASK_GROUP_COUNTS = {
    "0": 6,
    "1": 6,
    "2": 6,
    "3": 6,
}

EXPECTED_SUBTASK_GROUP_COUNTS = {
    "subtask0_accumulator_prepare": 4,
    "subtask1_k_stream": 16,
    "subtask3_finalize_store": 4,
}

EXPECTED_LOOP_GROUP_COUNTS = {
    "k0": 4,
    "k1": 4,
    "k2": 4,
    "k3": 4,
    "none": 8,
}


def main() -> None:
    failures: list[str] = []

    artifact = emit_debug_row_artifact(build_demo_pipeline("gemm_no_relu").binary_layout)
    groups = group_debug_rows_vendor_like(artifact)
    summary = summarize_vendor_like_row_group_plan(groups)

    if summary["runnability_state"] != "emittable_debug":
        failures.append(f"unexpected runnability state: {summary['runnability_state']}")
    if summary["group_count"] != 24:
        failures.append(f"expected 24 vendor-like groups, got {summary['group_count']}")
    if summary["instruction_row_count"] != 896:
        failures.append(f"expected 896 grouped instruction rows, got {summary['instruction_row_count']}")
    if summary["zero_boundary_count"] != 64:
        failures.append(f"expected 64 grouped zero boundaries, got {summary['zero_boundary_count']}")
    if summary["task_group_counts"] != EXPECTED_TASK_GROUP_COUNTS:
        failures.append(f"unexpected task group counts: {summary['task_group_counts']}")
    if summary["subtask_group_counts"] != EXPECTED_SUBTASK_GROUP_COUNTS:
        failures.append(f"unexpected subtask group counts: {summary['subtask_group_counts']}")
    if summary["loop_group_counts"] != EXPECTED_LOOP_GROUP_COUNTS:
        failures.append(f"unexpected loop group counts: {summary['loop_group_counts']}")
    if summary["missing_provenance_count"] != 0:
        failures.append("vendor-like groups contain rows missing provenance")
    if summary["forbidden_tile_micro_block_field_count"] != 0:
        failures.append("vendor-like groups contain TileMicroBlock fields")
    if summary["diagnostic_count"] != 0:
        failures.append(f"expected no group diagnostics, got {summary['diagnostic_count']}")

    k_stream_groups = [
        group
        for group in groups.groups
        if group.subtask_slot == "subtask1_k_stream"
    ]
    if len(k_stream_groups) != 16:
        failures.append(f"expected 16 k-stream groups, got {len(k_stream_groups)}")
    elif any(group.zero_boundaries for group in k_stream_groups):
        failures.append("k-stream groups must not contain zero boundaries")
    elif any(len(group.instruction_rows) != 48 for group in k_stream_groups):
        failures.append("each task/k-loop group should contain 48 instruction rows")

    post_groups = [
        group
        for group in groups.groups
        if group.subtask_slot == "subtask3_finalize_store"
    ]
    if len(post_groups) != 4:
        failures.append(f"expected 4 finalize/store groups, got {len(post_groups)}")
    elif any(len(group.instruction_rows) != 16 for group in post_groups):
        failures.append("each finalize/store group should contain 16 store rows")
    elif any(len(group.zero_boundaries) != 16 for group in post_groups):
        failures.append("each finalize/store group should contain 16 zero boundaries")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "vendor_groups.json"
        content = json.dumps(groups.to_plan()["groups"], indent=2, sort_keys=True) + "\n"
        path.write_text(content, encoding="utf-8")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if loaded != [group.to_plan() for group in groups.groups]:
            failures.append("vendor group JSON does not round-trip")

    relu_artifact = emit_debug_row_artifact(build_demo_pipeline("gemm_relu").binary_layout)
    relu_groups = group_debug_rows_vendor_like(relu_artifact)
    relu_summary = summarize_vendor_like_row_group_plan(relu_groups)
    if relu_summary["group_count"] != 0:
        failures.append("gemm_relu fail-closed artifact must not produce groups")
    if relu_summary["diagnostic_severity_counts"] != {"error": 3}:
        failures.append(f"unexpected ReLU group diagnostics: {relu_summary['diagnostic_severity_counts']}")

    if failures:
        print("stream compiler vendor-like group check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler vendor-like group check OK")
    print(f"groups={summary['group_count']}")
    print(f"instruction_rows={summary['instruction_row_count']}")


if __name__ == "__main__":
    main()
