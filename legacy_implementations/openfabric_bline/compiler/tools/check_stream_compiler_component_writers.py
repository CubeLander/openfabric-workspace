#!/usr/bin/env python3
"""Focused validation for B-line debug-only component byte writers."""

from __future__ import annotations

import struct
import tempfile
from pathlib import Path

from gpdpu_compiler.core.stream_compiler.component_writers import (
    emit_debug_instance_conf_info_component,
    summarize_debug_component_writer_artifact,
)
from gpdpu_compiler.core.stream_compiler.debug_emit import emit_debug_row_artifact
from gpdpu_compiler.core.stream_compiler.field_offsets import (
    build_field_offset_preflight_plan,
)
from gpdpu_compiler.core.stream_compiler.folding import analyze_stream_loop_folding
from gpdpu_compiler.core.stream_compiler.serializer_readiness import (
    build_serializer_readiness_plan,
)
from gpdpu_compiler.core.stream_compiler.vendor_components import (
    build_vendor_component_plan,
)
from gpdpu_compiler.core.stream_compiler.vendor_groups import (
    group_debug_rows_vendor_like,
    remap_vendor_like_groups_locally,
)
from stream_compiler_demo_pipeline import build_demo_pipeline


EXPECTED_NO_RELU_SUMMARY = {
    "profile_id": "dfu3500_legacy_gemm_symbolic",
    "component": "instance_rows",
    "struct_name": "instance_conf_info_t",
    "writer_status": "debug_only",
    "record_format": "<4Q",
    "row_count": 16,
    "record_size_bytes": 32,
    "payload_size_bytes": 512,
    "diagnostic_count": 0,
    "diagnostic_severity_counts": {},
    "row_status_counts": {"packed": 16},
    "base_addr_slot_count": 4,
    "debug_only": True,
}


def main() -> None:
    failures: list[str] = []

    no_relu_component, no_relu_readiness = _component_and_readiness("gemm_no_relu")
    no_relu_writer = emit_debug_instance_conf_info_component(
        no_relu_component,
        no_relu_readiness,
    )
    no_relu_summary = summarize_debug_component_writer_artifact(no_relu_writer)

    if no_relu_summary != EXPECTED_NO_RELU_SUMMARY:
        failures.append(f"unexpected no-ReLU writer summary: {no_relu_summary}")
    if no_relu_writer.payload:
        first_record = struct.unpack("<4Q", no_relu_writer.payload[:32])
        second_record = struct.unpack("<4Q", no_relu_writer.payload[32:64])
        if first_record != (0, 65536, 0xFFFFFFFF, 0xFFFFFFFF):
            failures.append(f"unexpected first instance record: {first_record}")
        if second_record != (32, 81920, 0xFFFFFFFF, 0xFFFFFFFF):
            failures.append(f"unexpected second instance record: {second_record}")
    if len(no_relu_writer.row_records) != 16:
        failures.append("expected 16 row provenance records")
    elif any(record.get("binary_encoding_policy") != "debug_only_instance_conf_info_t_4x_u64" for record in no_relu_writer.row_records):
        failures.append("row records must stay marked debug-only")

    with tempfile.TemporaryDirectory() as tmpdir:
        out_path = Path(tmpdir) / "instance_conf_info_file.debug.bin"
        out_path.write_bytes(no_relu_writer.payload)
        if out_path.read_bytes() != no_relu_writer.payload:
            failures.append("debug instance component bytes do not round-trip")

    relu_component, relu_readiness = _component_and_readiness("gemm_relu")
    relu_writer = emit_debug_instance_conf_info_component(
        relu_component,
        relu_readiness,
    )
    relu_summary = summarize_debug_component_writer_artifact(relu_writer)
    if relu_summary["writer_status"] != "blocked":
        failures.append(f"gemm_relu writer must fail closed: {relu_summary}")
    if relu_summary["payload_size_bytes"] != 0:
        failures.append(f"blocked writer must not emit payload bytes: {relu_summary}")
    if relu_summary["diagnostic_severity_counts"].get("error", 0) < 1:
        failures.append(f"blocked writer must expose an error diagnostic: {relu_summary}")

    plan_view = no_relu_writer.to_plan()
    if "debug_only_not_runnable_package" not in str(plan_view["layering_policy"]):
        failures.append(f"writer layering policy is too weak: {plan_view}")

    if failures:
        print("stream compiler component writer check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler component writer check OK")
    print(f"instance_rows={no_relu_summary['row_count']}")
    print(f"payload_size_bytes={no_relu_summary['payload_size_bytes']}")


def _component_and_readiness(profile: str):
    pipeline = build_demo_pipeline(profile)
    artifact = emit_debug_row_artifact(pipeline.binary_layout)
    groups = group_debug_rows_vendor_like(artifact)
    remap = remap_vendor_like_groups_locally(groups)
    component_plan = build_vendor_component_plan(
        remap,
        loop_fold_report=analyze_stream_loop_folding(pipeline.schedule),
    )
    offset_plan = build_field_offset_preflight_plan(component_plan)
    readiness = build_serializer_readiness_plan(component_plan, offset_plan)
    return component_plan, readiness


if __name__ == "__main__":
    main()
