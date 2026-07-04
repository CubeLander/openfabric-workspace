#!/usr/bin/env python3
"""Focused validation for B-line debug row artifact emission."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from gpdpu_compiler.core.stream_compiler.debug_emit import (
    emit_debug_row_artifact,
    summarize_debug_row_artifact,
)
from stream_compiler_demo_pipeline import build_demo_pipeline


EXPECTED_OPCODE_COUNTS = {
    "ACC_PREPARE": 64,
    "HMMAL_OR_GEMM_UPDATE": 256,
    "LOAD_OR_COPY": 128,
    "ROUTE_RECV_VISIBILITY": 384,
    "STD": 64,
}


def main() -> None:
    failures: list[str] = []

    no_relu = emit_debug_row_artifact(build_demo_pipeline("gemm_no_relu").binary_layout)
    no_relu_summary = summarize_debug_row_artifact(no_relu)
    if no_relu_summary["instruction_row_count"] != 896:
        failures.append(f"expected 896 debug instruction rows, got {no_relu_summary['instruction_row_count']}")
    if no_relu_summary["zero_boundary_count"] != 64:
        failures.append(f"expected 64 debug zero boundaries, got {no_relu_summary['zero_boundary_count']}")
    if no_relu_summary["runnability_state"] != "emittable_debug":
        failures.append(f"unexpected no-ReLU runnability state: {no_relu_summary['runnability_state']}")
    if no_relu_summary["opcode_counts"] != EXPECTED_OPCODE_COUNTS:
        failures.append(f"unexpected debug opcode counts: {no_relu_summary['opcode_counts']}")
    if no_relu_summary["zero_boundary_role_counts"] != {"accumulator_finalize": 64}:
        failures.append(f"unexpected zero-boundary roles: {no_relu_summary['zero_boundary_role_counts']}")
    if no_relu_summary["diagnostic_count"] != 0:
        failures.append(f"expected no no-ReLU debug diagnostics, got {no_relu_summary['diagnostic_count']}")
    if no_relu_summary["missing_template_provenance_count"] != 0:
        failures.append("debug rows are missing TemplateOp provenance")
    if no_relu_summary["missing_fiber_provenance_count"] != 0:
        failures.append("debug rows are missing FiberOp provenance")
    if no_relu_summary["forbidden_tile_micro_block_field_count"] != 0:
        failures.append("debug rows contain TileMicroBlock provenance fields")
    if any(row["role"] == "tile_op:relu" for row in no_relu.instruction_rows):
        failures.append("no-ReLU debug rows must not contain tile_op:relu")
    if any(row["role"] == "accumulator_finalize" for row in no_relu.instruction_rows):
        failures.append("accumulator_finalize must remain a zero boundary")
    if any(row["pc"] is not None for row in no_relu.zero_boundaries):
        failures.append("zero boundaries must not allocate PCs")

    with tempfile.TemporaryDirectory() as tmpdir:
        out_dir = Path(tmpdir)
        (out_dir / "instruction_rows.json").write_text(
            json.dumps(no_relu.to_plan()["instruction_rows"], indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        loaded = json.loads((out_dir / "instruction_rows.json").read_text(encoding="utf-8"))
        if loaded != list(no_relu.instruction_rows):
            failures.append("debug instruction rows do not JSON round-trip")

    relu = emit_debug_row_artifact(build_demo_pipeline("gemm_relu").binary_layout)
    relu_summary = summarize_debug_row_artifact(relu)
    if relu_summary["instruction_row_count"] != 0:
        failures.append("gemm_relu layout_candidate must not emit debug instruction rows")
    if relu_summary["diagnostic_severity_counts"] != {"error": 3}:
        failures.append(f"unexpected gemm_relu fail-closed diagnostics: {relu_summary['diagnostic_severity_counts']}")

    if failures:
        print("stream compiler debug emit check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler debug emit check OK")
    print(f"instruction_rows={no_relu_summary['instruction_row_count']}")
    print(f"zero_boundaries={no_relu_summary['zero_boundary_count']}")


if __name__ == "__main__":
    main()
