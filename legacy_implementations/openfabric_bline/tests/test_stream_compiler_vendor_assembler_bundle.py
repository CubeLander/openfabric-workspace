from __future__ import annotations

import csv
import json
from pathlib import Path

from gpdpu_compiler.core.stream_compiler.vendor_assembler_bundle import (
    build_vendor_assembler_input_bundle,
    summarize_vendor_assembler_input_bundle,
    write_vendor_assembler_input_bundle,
)
from stream_compiler_demo_pipeline import build_demo_pipeline


def test_vendor_assembler_input_bundle_summarizes_gemm_no_relu() -> None:
    artifacts = build_demo_pipeline("gemm_no_relu")

    bundle = build_vendor_assembler_input_bundle(artifacts.binary_layout)
    summary = summarize_vendor_assembler_input_bundle(bundle)

    assert summary["bundle_status"] == "report_only_symbolic_csv_not_assembler_ready"
    assert summary["assembler_ready"] is False
    assert summary["task_count"] == 4
    assert summary["subtask_count"] == 8
    assert summary["template_csv_count"] == 128
    assert summary["nonempty_template_csv_count"] == 128
    assert summary["csv_row_count"] == 128
    assert summary["csv_row_status_counts"] == {
        "symbolic_csv_candidate": 64,
        "symbolic_template_span_needs_vendor_expansion": 64,
    }


def test_vendor_assembler_input_bundle_writes_case_package(tmp_path: Path) -> None:
    artifacts = build_demo_pipeline("gemm_no_relu")
    bundle = build_vendor_assembler_input_bundle(artifacts.binary_layout)

    summary = write_vendor_assembler_input_bundle(bundle, tmp_path)

    assert summary["csv_row_count"] == 128
    app_conf = tmp_path / "app0.conf"
    manifest = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    provenance = json.loads((tmp_path / "provenance.json").read_text(encoding="utf-8"))
    assert app_conf.is_file()
    assert "task_name:task0" in app_conf.read_text(encoding="utf-8")
    assert manifest["assembler_ready"] is False
    assert len(provenance["rows"]) == 128

    csv_path = tmp_path / "task0/subtask1/template/0.csv"
    rows = list(csv.reader(csv_path.read_text(encoding="utf-8").splitlines()))
    assert rows[0][:8] == [
        "inst_name",
        "inst_tag_name",
        "src_reg_idx0",
        "src_reg_idx1",
        "dst_reg_idx",
        "dst_pe_idx",
        "imm",
        "iteration",
    ]
    assert rows[1][0] == "GEMM_TILE_TEMPLATE_SPAN"
    assert (tmp_path / "task0/subtask1/build_so/test_graph_extend.cpp").is_file()
    assert (tmp_path / "task0/subtask1/build_so/Makefile").is_file()
