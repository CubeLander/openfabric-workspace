#!/usr/bin/env python3
"""Focused validation for vendor-like group-local row remapping."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from gpdpu_compiler.core.stream_compiler.debug_emit import emit_debug_row_artifact
from gpdpu_compiler.core.stream_compiler.vendor_groups import (
    group_debug_rows_vendor_like,
    remap_vendor_like_groups_locally,
    summarize_vendor_like_local_remap_plan,
)
from stream_compiler_demo_pipeline import build_demo_pipeline


def main() -> None:
    failures: list[str] = []

    artifact = emit_debug_row_artifact(build_demo_pipeline("gemm_no_relu").binary_layout)
    groups = group_debug_rows_vendor_like(artifact)
    remap = remap_vendor_like_groups_locally(groups)
    summary = summarize_vendor_like_local_remap_plan(remap)

    if summary["runnability_state"] != "emittable_debug":
        failures.append(f"unexpected runnability state: {summary['runnability_state']}")
    if summary["group_count"] != 24:
        failures.append(f"expected 24 groups, got {summary['group_count']}")
    if summary["instruction_row_count"] != 896:
        failures.append(f"expected 896 remapped instruction rows, got {summary['instruction_row_count']}")
    if summary["zero_boundary_count"] != 64:
        failures.append(f"expected 64 zero boundaries, got {summary['zero_boundary_count']}")
    if summary["non_dense_local_pc_group_count"] != 0:
        failures.append(f"non-dense local PCs: {summary['non_dense_local_pc_groups']}")
    if summary["zero_boundaries_with_pc_count"] != 0:
        failures.append("zero boundaries must not have global or local PCs")
    if summary["missing_global_index_count"] != 0:
        failures.append("remapped rows must preserve global row/PC indices")
    if summary["forbidden_tile_micro_block_field_count"] != 0:
        failures.append("local remap rows contain TileMicroBlock fields")
    if summary["diagnostic_count"] != 0:
        failures.append(f"expected no remap diagnostics, got {summary['diagnostic_count']}")

    k_stream_groups = [
        group
        for group in remap.groups
        if group.subtask_slot == "subtask1_k_stream"
    ]
    if any([row["local_pc"] for row in group.instruction_rows] != list(range(48)) for group in k_stream_groups):
        failures.append("each K-stream group should have local PCs 0..47")

    post_groups = [
        group
        for group in remap.groups
        if group.subtask_slot == "subtask3_finalize_store"
    ]
    if any([row["local_pc"] for row in group.instruction_rows] != list(range(16)) for group in post_groups):
        failures.append("each finalize/store instruction group should have local PCs 0..15")
    if any(
        boundary["local_boundary_index"] != index
        for group in post_groups
        for index, boundary in enumerate(group.zero_boundaries)
    ):
        failures.append("zero boundary local indices are not dense")

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "vendor_local_remap.json"
        content = json.dumps(remap.to_plan()["groups"], indent=2, sort_keys=True) + "\n"
        path.write_text(content, encoding="utf-8")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if loaded != [group.to_plan() for group in remap.groups]:
            failures.append("local remap JSON does not round-trip")

    relu_artifact = emit_debug_row_artifact(build_demo_pipeline("gemm_relu").binary_layout)
    relu_remap = remap_vendor_like_groups_locally(group_debug_rows_vendor_like(relu_artifact))
    relu_summary = summarize_vendor_like_local_remap_plan(relu_remap)
    if relu_summary["group_count"] != 0:
        failures.append("gemm_relu fail-closed artifact must not produce remap groups")
    if relu_summary["diagnostic_severity_counts"] != {"error": 3}:
        failures.append(f"unexpected ReLU remap diagnostics: {relu_summary['diagnostic_severity_counts']}")

    if failures:
        print("stream compiler local remap check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler local remap check OK")
    print(f"groups={summary['group_count']}")
    print(f"instruction_rows={summary['instruction_row_count']}")


if __name__ == "__main__":
    main()
