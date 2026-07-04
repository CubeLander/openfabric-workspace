#!/usr/bin/env python3
"""Validate deterministic B-line snapshot export summaries."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from export_stream_compiler_snapshot import build_snapshot


def main() -> None:
    failures: list[str] = []

    relu_snapshot = build_snapshot("gemm_relu")
    no_relu_snapshot = build_snapshot("gemm_no_relu")

    relu_template = relu_snapshot["summaries"]["template_ops"]  # type: ignore[index]
    relu_layout = relu_snapshot["summaries"]["binary_layout"]  # type: ignore[index]
    no_relu_template = no_relu_snapshot["summaries"]["template_ops"]  # type: ignore[index]
    no_relu_layout = no_relu_snapshot["summaries"]["binary_layout"]  # type: ignore[index]

    if relu_template["template_op_count"] != 1024:  # type: ignore[index]
        failures.append(f"expected 1024 ReLU TemplateOps, got {relu_template['template_op_count']}")  # type: ignore[index]
    if relu_template["unresolved_role_counts"] != {"tile_op:relu": 64}:  # type: ignore[index]
        failures.append(f"unexpected ReLU unresolved roles: {relu_template['unresolved_role_counts']}")  # type: ignore[index]
    if relu_layout["runnability_state"] != "layout_candidate":  # type: ignore[index]
        failures.append(f"unexpected ReLU layout state: {relu_layout['runnability_state']}")  # type: ignore[index]
    if relu_layout["instruction_row_count"] != 896:  # type: ignore[index]
        failures.append(f"unexpected ReLU instruction rows: {relu_layout['instruction_row_count']}")  # type: ignore[index]

    if no_relu_template["template_op_count"] != 960:  # type: ignore[index]
        failures.append(f"expected 960 no-ReLU TemplateOps, got {no_relu_template['template_op_count']}")  # type: ignore[index]
    if no_relu_template["unresolved_role_counts"] != {}:  # type: ignore[index]
        failures.append(f"unexpected no-ReLU unresolved roles: {no_relu_template['unresolved_role_counts']}")  # type: ignore[index]
    if no_relu_layout["runnability_state"] != "emittable_debug":  # type: ignore[index]
        failures.append(f"unexpected no-ReLU layout state: {no_relu_layout['runnability_state']}")  # type: ignore[index]
    if no_relu_layout["instruction_row_count"] != 896:  # type: ignore[index]
        failures.append(f"unexpected no-ReLU instruction rows: {no_relu_layout['instruction_row_count']}")  # type: ignore[index]
    if no_relu_layout["diagnostic_count"] != 0:  # type: ignore[index]
        failures.append(f"expected no no-ReLU diagnostics, got {no_relu_layout['diagnostic_count']}")  # type: ignore[index]

    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "snapshot.json"
        content = json.dumps(no_relu_snapshot, indent=2, sort_keys=True) + "\n"
        path.write_text(content, encoding="utf-8")
        loaded = json.loads(path.read_text(encoding="utf-8"))
        if loaded != no_relu_snapshot:
            failures.append("snapshot JSON round-trip changed content")

    if failures:
        print("stream compiler snapshot export check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler snapshot export check OK")
    print(f"gemm_relu_state={relu_layout['runnability_state']}")  # type: ignore[index]
    print(f"gemm_no_relu_state={no_relu_layout['runnability_state']}")  # type: ignore[index]


if __name__ == "__main__":
    main()
