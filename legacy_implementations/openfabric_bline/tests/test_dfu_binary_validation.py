from __future__ import annotations

import json
import struct
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
import sys

sys.path.insert(0, str(ROOT / "compiler"))

from gpdpu_compiler.decoder.profiles import DFU3500_SIMICT_LEGACY_PROFILE
from gpdpu_compiler.validation.dfu_binary_checks import (
    ReadinessLevel,
    ValidationReport,
    aggregate_reports,
    run_archived_report_freshness_check,
    run_payload_conformance,
    run_profile_conformance,
    run_runtime_readiness,
    run_runtime_memory_layout_check,
    run_source_fingerprint_check,
    validate_payload,
)
from gpdpu_compiler.validation.dfu_binary_checks.report import ValidationIssue, sha256_file
from gpdpu_compiler.validation.dfu3500_package_checks import (
    run_dfu3500_component_consistency_check,
    run_dfu3500_control_graph_check,
    run_dfu3500_instruction_span_check,
    run_dfu3500_memory_template_check,
    run_dfu3500_opcode_conformance_check,
    run_dfu3500_operand_resource_check,
)


def _write_package_complete_payload(root: Path) -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    result = root / "result"
    result.mkdir(parents=True)
    cbuf = result / "cbuf_file.bin"
    micc = result / "micc_file.bin"
    cbuf_bytes = bytearray(profile.files["cbuf"].size(profile))
    _write_minimal_cbuf_instruction(cbuf_bytes)
    cbuf.write_bytes(cbuf_bytes)
    micc_bytes = bytearray(profile.files["micc"].size(profile))
    _write_minimal_micc_control(micc_bytes)
    micc.write_bytes(micc_bytes)
    manifest = [
        "readiness_claim=package_complete",
        "task_num=1",
        f"result_cbuf_file.bin_size={cbuf.stat().st_size}",
        f"result_cbuf_file.bin_sha256={sha256_file(cbuf)}",
        f"result_micc_file.bin_size={micc.stat().st_size}",
        f"result_micc_file.bin_sha256={sha256_file(micc)}",
    ]
    (root / "MANIFEST.txt").write_text("\n".join(manifest) + "\n")


def _append_manifest_claims(root: Path, paths: tuple[str, ...]) -> None:
    with (root / "MANIFEST.txt").open("a") as manifest:
        for rel_path in paths:
            path = root / rel_path
            manifest.write(f"{rel_path.replace('/', '_')}_size={path.stat().st_size}\n")
            manifest.write(f"{rel_path.replace('/', '_')}_sha256={sha256_file(path)}\n")


def _write_runtime_ready_assets(root: Path) -> None:
    runtime_src = root / "runtime/riscv_src"
    (runtime_src / "riscv").mkdir(parents=True)
    (runtime_src / "csv_generate").mkdir(parents=True)
    (root / "runtime").mkdir(exist_ok=True)
    (root / "reference").mkdir(exist_ok=True)
    (root / "runtime/input_data.bin").write_bytes(bytes(128))
    (runtime_src / "riscv/testarm.c").write_text("int main(void) { return 0; }\n")
    (runtime_src / "csv_generate/conf.h").write_text("#define TASK_NUM 1\n")
    (root / "reference/Y.fp32.bin").write_bytes(bytes(64))
    runtime_control = {
        "case_id": "unit_payload",
        "spm_image_size_bytes": 1024,
        "tensors": [
            {
                "name": "X",
                "dtype": "fp32",
                "shape": [4, 4],
                "byte_offset": 0,
                "byte_size": 64,
                "direction": "input",
                "reference_path": None,
            },
            {
                "name": "Y",
                "dtype": "fp32",
                "shape": [4, 4],
                "byte_offset": 512,
                "byte_size": 64,
                "direction": "output",
                "reference_path": "reference/Y.fp32.bin",
            },
        ],
        "transfers": [
            {
                "transfer_id": "input_X",
                "tensor_name": "X",
                "direction": "ddr_to_spm",
                "ddr_offset": 0,
                "spm_offset": 0,
                "byte_size": 64,
                "phase": "before_launch",
                "group_id": "input",
                "task_id": None,
                "instance_id": None,
            },
            {
                "transfer_id": "output_Y",
                "tensor_name": "Y",
                "direction": "spm_to_ddr",
                "ddr_offset": 512,
                "spm_offset": 512,
                "byte_size": 64,
                "phase": "after_launch",
                "group_id": "output",
                "task_id": None,
                "instance_id": None,
            },
        ],
        "launches": [
            {
                "launch_id": "kernel0",
                "task_count": 1,
                "instance_count": 1,
                "micc_buffer": 0,
                "wait": True,
                "input_transfer_group": "input",
                "output_transfer_group": "output",
            }
        ],
        "finish_app": True,
    }
    (runtime_src / "riscv_control.json").write_text(
        json.dumps(runtime_control, indent=2, sort_keys=True) + "\n"
    )
    _append_manifest_claims(
        root,
        (
            "runtime/input_data.bin",
            "runtime/riscv_src/riscv_control.json",
            "runtime/riscv_src/riscv/testarm.c",
            "runtime/riscv_src/csv_generate/conf.h",
            "reference/Y.fp32.bin",
        ),
    )


def _write_runtime_ready_payload(root: Path) -> None:
    _write_package_complete_payload(root)
    _write_component_files_from_result(root)
    _write_runtime_ready_assets(root)


def _write_component_files_from_result(root: Path) -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    result = root / "result"
    config = root / "config"
    simulator_bin = root / "simulator_bin"
    config.mkdir(exist_ok=True)
    simulator_bin.mkdir(exist_ok=True)
    component_paths: list[str] = []

    for file_kind, combined_name in (("cbuf", "cbuf_file.bin"), ("micc", "micc_file.bin")):
        combined_path = result / combined_name
        combined_bytes = combined_path.read_bytes()
        config_path = config / combined_name
        config_path.write_bytes(combined_bytes)
        component_paths.append(config_path.relative_to(root).as_posix())
        for section in profile.files[file_kind].sections:
            section_bytes = combined_bytes[section.offset : section.end_offset(profile)]
            for component_name in section.component_file_names:
                component_path = simulator_bin / component_name
                component_path.write_bytes(section_bytes)
                component_paths.append(component_path.relative_to(root).as_posix())

    _append_manifest_claims(root, tuple(sorted(component_paths)))


def _write_minimal_micc_control(data: bytearray) -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    task_base = 0
    struct.pack_into("<B", data, task_base, 1)
    struct.pack_into("<B", data, task_base + 1, 1)
    struct.pack_into("<Q", data, task_base + 8, 1)
    struct.pack_into("<Q", data, task_base + 16, 1)
    struct.pack_into("<Q", data, task_base + 24, 0)

    subtask_base = profile.files["micc"].sections[1].offset
    struct.pack_into("<B", data, subtask_base, 1)
    struct.pack_into("<B", data, subtask_base + 1, 1)
    struct.pack_into("<Q", data, subtask_base + 8, 1)
    struct.pack_into("<Q", data, subtask_base + 56, 1)
    struct.pack_into("<Q", data, subtask_base + 64, 1)
    struct.pack_into("<Q", data, subtask_base + 266312, 0)
    struct.pack_into("<Q", data, subtask_base + 266320, 0)

    block_base = subtask_base + 72
    conf_base = block_base + 48
    struct.pack_into("<B", data, block_base, 1)
    struct.pack_into("<Q", data, block_base + 8, 0)
    struct.pack_into("<Q", data, block_base + 40, 0)
    struct.pack_into("<Q", data, conf_base + 376, 0)
    struct.pack_into("<Q", data, conf_base + 384, 0)
    struct.pack_into("<Q", data, conf_base + 392, 0)
    struct.pack_into("<Q", data, conf_base + 400, 1)
    struct.pack_into("<Q", data, conf_base + 432, 1)


def _write_minimal_cbuf_instruction(data: bytearray, *, opcode: int = 0x22) -> None:
    struct.pack_into("<I", data, 0, opcode)
    struct.pack_into("<Q", data, 8, 1)
    struct.pack_into("<Q", data, 16, 1)


def test_profile_conformance_report_is_authoritative_for_package_gate() -> None:
    report = run_profile_conformance(
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.PACKAGE_COMPLETE,
    )

    assert report.status == "pass"
    assert report.authoritative is True
    assert report.profile_id == DFU3500_SIMICT_LEGACY_PROFILE.profile_id
    assert len(report.profile_sha256 or "") == 64
    json.dumps(report.to_json(), sort_keys=True)


def test_payload_conformance_accepts_manifest_and_profile_sized_files(tmp_path: Path) -> None:
    _write_package_complete_payload(tmp_path)

    report = run_payload_conformance(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.PACKAGE_COMPLETE,
    )

    assert report.status == "pass"
    assert report.authoritative is True
    assert set(report.input_paths) == {
        "MANIFEST.txt",
        "result/cbuf_file.bin",
        "result/micc_file.bin",
    }


def test_payload_conformance_catches_short_micc_and_stale_manifest(tmp_path: Path) -> None:
    _write_package_complete_payload(tmp_path)
    micc = tmp_path / "result/micc_file.bin"
    micc.write_bytes(b"short")

    report = run_payload_conformance(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.PACKAGE_COMPLETE,
    )

    assert report.status == "fail"
    codes = {issue.code for issue in report.issues}
    assert "payload_file_size_mismatch" in codes
    assert "manifest_size_mismatch" in codes
    assert "manifest_sha256_mismatch" in codes


def test_payload_conformance_requires_runtime_ready_manifest_claims(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)
    manifest_path = tmp_path / "MANIFEST.txt"
    manifest_path.write_text(
        "\n".join(
            line
            for line in manifest_path.read_text().splitlines()
            if not line.startswith("runtime_input_data.bin_")
            and not line.startswith("reference_Y.fp32.bin_")
        )
        + "\n"
    )

    report = run_payload_conformance(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "fail"
    codes = {issue.code for issue in report.issues}
    assert "manifest_size_claim_missing" in codes
    assert "manifest_sha256_claim_missing" in codes
    missing_artifacts = {
        issue.details["artifact"]
        for issue in report.issues
        if issue.code in {"manifest_size_claim_missing", "manifest_sha256_claim_missing"}
    }
    assert missing_artifacts == {
        "runtime/input_data.bin",
        "reference/Y.fp32.bin",
    }


def test_runtime_readiness_accepts_control_assets_and_reference(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)

    report = run_runtime_readiness(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "pass"
    assert report.authoritative is True
    assert "runtime/riscv_src/riscv_control.json" in report.input_paths


def test_runtime_readiness_catches_missing_output_reference(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)
    (tmp_path / "reference/Y.fp32.bin").unlink()

    report = run_runtime_readiness(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "fail"
    assert {issue.code for issue in report.issues} == {"runtime_output_reference_file_missing"}


def test_runtime_memory_layout_accepts_runtime_control_plan(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)

    report = run_runtime_memory_layout_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "pass"
    assert report.authoritative is True
    assert set(report.input_paths) == {
        "runtime/input_data.bin",
        "runtime/riscv_src/riscv_control.json",
        "reference/Y.fp32.bin",
    }


def test_runtime_memory_layout_catches_bad_regions_and_sizes(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)
    control_path = tmp_path / "runtime/riscv_src/riscv_control.json"
    control = json.loads(control_path.read_text())
    control["spm_image_size_bytes"] = 520
    control["tensors"][1]["byte_offset"] = 32
    control["tensors"][1]["byte_size"] = 128
    control["transfers"][1]["spm_offset"] = 512
    control["transfers"][1]["byte_size"] = 64
    control_path.write_text(json.dumps(control, indent=2, sort_keys=True) + "\n")
    (tmp_path / "reference/Y.fp32.bin").write_bytes(bytes(64))

    report = run_runtime_memory_layout_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "fail"
    codes = {issue.code for issue in report.issues}
    assert "runtime_tensor_region_overlap" in codes
    assert "runtime_tensor_shape_size_mismatch" in codes
    assert "runtime_reference_size_mismatch" in codes
    assert "runtime_transfer_size_mismatch" in codes
    assert "runtime_transfer_spm_offset_mismatch" in codes
    assert "runtime_transfer_region_out_of_bounds" in codes


def test_dfu3500_control_graph_accepts_minimal_single_task_payload(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)

    report = run_dfu3500_control_graph_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "pass"
    assert report.authoritative is True
    assert set(report.input_paths) == {
        "result/micc_file.bin",
        "runtime/riscv_src/riscv_control.json",
    }


def test_dfu3500_component_consistency_accepts_matching_payload(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)

    report = run_dfu3500_component_consistency_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "pass"
    assert report.authoritative is True
    assert "simulator_bin/instance_conf_info_file.bin" in report.input_paths


def test_dfu3500_component_consistency_catches_component_drift(
    tmp_path: Path,
) -> None:
    _write_runtime_ready_payload(tmp_path)
    task_component = tmp_path / "simulator_bin/tasks_conf_info_file.bin"
    component = bytearray(task_component.read_bytes())
    component[0] ^= 0x01
    task_component.write_bytes(component)

    report = run_dfu3500_component_consistency_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "fail"
    issue = report.issues[0]
    assert issue.code == "dfu3500_component_bytes_mismatch"
    assert issue.path == "simulator_bin/tasks_conf_info_file.bin"
    assert issue.details["section"] == "tasks"
    assert issue.details["first_mismatch_offset"] == 0


def test_dfu3500_component_consistency_catches_config_result_drift(
    tmp_path: Path,
) -> None:
    _write_runtime_ready_payload(tmp_path)
    config_micc = tmp_path / "config/micc_file.bin"
    data = bytearray(config_micc.read_bytes())
    data[0] ^= 0x01
    config_micc.write_bytes(data)

    report = run_dfu3500_component_consistency_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "fail"
    assert {issue.code for issue in report.issues} == {
        "dfu3500_config_result_mismatch"
    }


def test_dfu3500_instruction_span_accepts_active_stage_rows(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)

    report = run_dfu3500_instruction_span_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "pass"
    assert report.authoritative is True
    assert set(report.input_paths) == {
        "result/cbuf_file.bin",
        "result/micc_file.bin",
    }


def test_dfu3500_instruction_span_catches_zero_stage_row(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)
    cbuf_path = tmp_path / "result/cbuf_file.bin"
    cbuf = bytearray(cbuf_path.read_bytes())
    inst_size = DFU3500_SIMICT_LEGACY_PROFILE.structs["inst_t"].size
    cbuf[:inst_size] = bytes(inst_size)
    cbuf_path.write_bytes(cbuf)

    report = run_dfu3500_instruction_span_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "fail"
    assert {issue.code for issue in report.issues} == {"dfu3500_stage_inst_row_zero"}


def test_dfu3500_instruction_span_catches_unknown_opcode(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)
    cbuf_path = tmp_path / "result/cbuf_file.bin"
    cbuf = bytearray(cbuf_path.read_bytes())
    struct.pack_into("<I", cbuf, 0, 0xFFFF)
    cbuf_path.write_bytes(cbuf)

    report = run_dfu3500_instruction_span_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "fail"
    assert {issue.code for issue in report.issues} == {"dfu3500_stage_inst_opcode_unknown"}


def test_dfu3500_opcode_conformance_accepts_active_stage_rows(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)

    report = run_dfu3500_opcode_conformance_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "pass"
    assert report.authoritative is True
    assert set(report.input_paths) == {
        "result/cbuf_file.bin",
        "result/micc_file.bin",
    }


def test_dfu3500_opcode_conformance_catches_unit_type_mismatch(
    tmp_path: Path,
) -> None:
    _write_runtime_ready_payload(tmp_path)
    cbuf_path = tmp_path / "result/cbuf_file.bin"
    cbuf = bytearray(cbuf_path.read_bytes())
    struct.pack_into("<Q", cbuf, 8, 2)
    cbuf_path.write_bytes(cbuf)

    report = run_dfu3500_opcode_conformance_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "fail"
    assert {issue.code for issue in report.issues} == {
        "dfu3500_opcode_unit_type_mismatch"
    }


def test_dfu3500_opcode_conformance_catches_latency_mismatch(
    tmp_path: Path,
) -> None:
    _write_runtime_ready_payload(tmp_path)
    cbuf_path = tmp_path / "result/cbuf_file.bin"
    cbuf = bytearray(cbuf_path.read_bytes())
    struct.pack_into("<Q", cbuf, 16, 72)
    cbuf_path.write_bytes(cbuf)

    report = run_dfu3500_opcode_conformance_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "fail"
    assert {issue.code for issue in report.issues} == {
        "dfu3500_opcode_latency_mismatch"
    }


def test_dfu3500_opcode_conformance_rejects_pseudo_opcode_in_cbuf(
    tmp_path: Path,
) -> None:
    _write_runtime_ready_payload(tmp_path)
    cbuf_path = tmp_path / "result/cbuf_file.bin"
    cbuf = bytearray(cbuf_path.read_bytes())
    struct.pack_into("<I", cbuf, 0, 0x101)
    struct.pack_into("<Q", cbuf, 8, 0x10)
    struct.pack_into("<Q", cbuf, 16, 2)
    cbuf_path.write_bytes(cbuf)

    report = run_dfu3500_opcode_conformance_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "fail"
    assert {issue.code for issue in report.issues} == {
        "dfu3500_opcode_pseudo_in_cbuf"
    }


def test_dfu3500_operand_resource_accepts_active_stage_rows(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)

    report = run_dfu3500_operand_resource_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "pass"
    assert report.authoritative is True


def test_dfu3500_operand_resource_catches_operand_index_overflow(
    tmp_path: Path,
) -> None:
    _write_runtime_ready_payload(tmp_path)
    cbuf_path = tmp_path / "result/cbuf_file.bin"
    cbuf = bytearray(cbuf_path.read_bytes())
    struct.pack_into("<Q", cbuf, 48, 1536)
    cbuf_path.write_bytes(cbuf)

    report = run_dfu3500_operand_resource_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "fail"
    assert {issue.code for issue in report.issues} == {
        "dfu3500_operand_index_out_of_range"
    }


def test_dfu3500_operand_resource_catches_route_destination_overflow(
    tmp_path: Path,
) -> None:
    _write_runtime_ready_payload(tmp_path)
    cbuf_path = tmp_path / "result/cbuf_file.bin"
    cbuf = bytearray(cbuf_path.read_bytes())
    struct.pack_into("<Q", cbuf, 96, 4)
    cbuf_path.write_bytes(cbuf)

    report = run_dfu3500_operand_resource_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "fail"
    assert {issue.code for issue in report.issues} == {
        "dfu3500_dst_pe_position_out_of_range"
    }


def test_dfu3500_memory_template_accepts_active_stage_rows(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)

    report = run_dfu3500_memory_template_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "pass"
    assert report.authoritative is True


def test_dfu3500_memory_template_uses_fixed_instance_window_for_subtask(
    tmp_path: Path,
) -> None:
    _write_runtime_ready_payload(tmp_path)
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    cbuf_path = tmp_path / "result/cbuf_file.bin"
    micc_path = tmp_path / "result/micc_file.bin"
    cbuf = bytearray(cbuf_path.read_bytes())
    micc = bytearray(micc_path.read_bytes())

    task_base = 0
    struct.pack_into("<Q", micc, task_base + 24, 1)
    subtask_section = profile.files["micc"].sections[1]
    subtask_size = profile.structs["sub_task_conf_info_t"].size
    subtask_base = subtask_section.offset + subtask_size
    struct.pack_into("<B", micc, subtask_base, 1)
    struct.pack_into("<B", micc, subtask_base + 1, 1)
    struct.pack_into("<Q", micc, subtask_base + 8, 1)
    struct.pack_into("<Q", micc, subtask_base + 16, 32)
    struct.pack_into("<Q", micc, subtask_base + 56, 1)
    struct.pack_into("<Q", micc, subtask_base + 64, 1)
    struct.pack_into("<Q", micc, subtask_base + 266312, 1)
    struct.pack_into("<Q", micc, subtask_base + 266320, 0)

    block_base = subtask_base + 72
    conf_base = block_base + 48
    struct.pack_into("<B", micc, block_base, 1)
    struct.pack_into("<Q", micc, block_base + 8, 0)
    struct.pack_into("<Q", micc, block_base + 16, 0)
    struct.pack_into("<Q", micc, block_base + 24, 0)
    struct.pack_into("<Q", micc, block_base + 40, 0)
    struct.pack_into("<Q", micc, conf_base + 400, 1)
    struct.pack_into("<Q", micc, conf_base + 432, 1)

    struct.pack_into("<I", cbuf, 0, 0x80)
    struct.pack_into("<Q", cbuf, 240, 2)
    instance_base = profile.files["cbuf"].sections[2].offset
    instance_size = profile.structs["instance_conf_info_t"].size
    compact_row_1 = instance_base + instance_size
    physical_subtask_1_row_0 = instance_base + 2048 * instance_size
    struct.pack_into("<Q", cbuf, compact_row_1 + 16, 0xFFFFFFFF)
    struct.pack_into("<Q", cbuf, physical_subtask_1_row_0 + 16, 0x20000)
    cbuf_path.write_bytes(cbuf)
    micc_path.write_bytes(micc)

    report = run_dfu3500_memory_template_check(
        tmp_path,
        profile,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "pass"


def test_dfu3500_memory_template_catches_disabled_base_slot(
    tmp_path: Path,
) -> None:
    _write_runtime_ready_payload(tmp_path)
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    cbuf_path = tmp_path / "result/cbuf_file.bin"
    cbuf = bytearray(cbuf_path.read_bytes())
    struct.pack_into("<I", cbuf, 0, 0x80)
    struct.pack_into("<Q", cbuf, 8, 0x20)
    struct.pack_into("<Q", cbuf, 16, 2)
    struct.pack_into("<Q", cbuf, 240, 2)
    instance_base = profile.files["cbuf"].sections[2].offset
    struct.pack_into("<Q", cbuf, instance_base + 16, 0xFFFFFFFF)
    cbuf_path.write_bytes(cbuf)

    report = run_dfu3500_memory_template_check(
        tmp_path,
        profile,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "fail"
    assert {issue.code for issue in report.issues} == {
        "dfu3500_memory_base_slot_disabled"
    }


def test_dfu3500_memory_template_catches_base_slot_overflow(
    tmp_path: Path,
) -> None:
    _write_runtime_ready_payload(tmp_path)
    cbuf_path = tmp_path / "result/cbuf_file.bin"
    cbuf = bytearray(cbuf_path.read_bytes())
    struct.pack_into("<I", cbuf, 0, 0x80)
    struct.pack_into("<Q", cbuf, 8, 0x20)
    struct.pack_into("<Q", cbuf, 16, 2)
    struct.pack_into("<Q", cbuf, 240, 4)
    cbuf_path.write_bytes(cbuf)

    report = run_dfu3500_memory_template_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "fail"
    assert {issue.code for issue in report.issues} == {
        "dfu3500_iter_exe_cond_base_slot_out_of_range"
    }


def test_dfu3500_control_graph_catches_task_count_mismatch(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)
    runtime_control_path = tmp_path / "runtime/riscv_src/riscv_control.json"
    runtime_control = json.loads(runtime_control_path.read_text())
    runtime_control["launches"][0]["task_count"] = 2
    runtime_control_path.write_text(json.dumps(runtime_control, sort_keys=True) + "\n")

    report = run_dfu3500_control_graph_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "fail"
    assert {issue.code for issue in report.issues} == {
        "dfu3500_active_task_count_mismatch"
    }


def test_dfu3500_control_graph_catches_inactive_task_successor(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)
    micc_path = tmp_path / "result/micc_file.bin"
    micc = bytearray(micc_path.read_bytes())
    struct.pack_into("<Q", micc, 88, 1)
    micc_path.write_bytes(micc)

    report = run_dfu3500_control_graph_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    codes = {issue.code for issue in report.issues}
    assert "dfu3500_task_successor_inactive" in codes
    assert "dfu3500_task_successor_outside_expected_range" in codes


def test_dfu3500_control_graph_catches_duplicate_task_successor(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)
    micc_path = tmp_path / "result/micc_file.bin"
    micc = bytearray(micc_path.read_bytes())
    struct.pack_into("<Q", micc, 88, 1)
    struct.pack_into("<Q", micc, 96, 1)
    micc_path.write_bytes(micc)

    report = run_dfu3500_control_graph_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert "dfu3500_task_successor_duplicate" in {
        issue.code for issue in report.issues
    }


def test_dfu3500_control_graph_catches_task_successor_cycle(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)
    runtime_control_path = tmp_path / "runtime/riscv_src/riscv_control.json"
    runtime_control = json.loads(runtime_control_path.read_text())
    runtime_control["launches"][0]["task_count"] = 3
    runtime_control_path.write_text(json.dumps(runtime_control, sort_keys=True) + "\n")

    profile = DFU3500_SIMICT_LEGACY_PROFILE
    micc_path = tmp_path / "result/micc_file.bin"
    micc = bytearray(micc_path.read_bytes())
    task_size = profile.structs["task_conf_info_t"].size
    subtask_size = profile.structs["sub_task_conf_info_t"].size
    subtask_section_base = profile.files["micc"].sections[1].offset
    source_subtask = micc[subtask_section_base : subtask_section_base + subtask_size]
    for task_id in (1, 2):
        task_base = task_id * task_size
        struct.pack_into("<B", micc, task_base, 1)
        struct.pack_into("<B", micc, task_base + 1, 1)
        struct.pack_into("<Q", micc, task_base + 8, 1)
        struct.pack_into("<Q", micc, task_base + 16, 1)
        struct.pack_into("<Q", micc, task_base + 24, 0)

        subtask_base = subtask_section_base + task_id * 8 * subtask_size
        micc[subtask_base : subtask_base + subtask_size] = source_subtask
        struct.pack_into("<Q", micc, subtask_base + 266320, task_id)
        block_conf = subtask_base + 72 + 48
        struct.pack_into("<Q", micc, block_conf + 392, task_id)

    struct.pack_into("<Q", micc, task_size + 88, 2)
    struct.pack_into("<Q", micc, task_size * 2 + 88, 1)
    micc_path.write_bytes(micc)

    report = run_dfu3500_control_graph_check(
        tmp_path,
        profile,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert "dfu3500_task_successor_cycle" in {
        issue.code for issue in report.issues
    }


def test_dfu3500_control_graph_catches_inactive_subtask_successor(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)
    micc_path = tmp_path / "result/micc_file.bin"
    micc = bytearray(micc_path.read_bytes())
    subtask_base = DFU3500_SIMICT_LEGACY_PROFILE.files["micc"].sections[1].offset
    struct.pack_into("<Q", micc, subtask_base + 24, 1)
    micc_path.write_bytes(micc)

    report = run_dfu3500_control_graph_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert "dfu3500_subtask_successor_inactive" in {
        issue.code for issue in report.issues
    }


def test_dfu3500_control_graph_catches_duplicate_subtask_successor(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)
    micc_path = tmp_path / "result/micc_file.bin"
    micc = bytearray(micc_path.read_bytes())
    subtask_base = DFU3500_SIMICT_LEGACY_PROFILE.files["micc"].sections[1].offset
    struct.pack_into("<Q", micc, subtask_base + 24, 1)
    struct.pack_into("<Q", micc, subtask_base + 32, 1)
    micc_path.write_bytes(micc)

    report = run_dfu3500_control_graph_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert "dfu3500_subtask_successor_duplicate" in {
        issue.code for issue in report.issues
    }


def test_dfu3500_control_graph_catches_subtask_successor_cycle(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    micc_path = tmp_path / "result/micc_file.bin"
    micc = bytearray(micc_path.read_bytes())
    task_base = 0
    subtask_size = profile.structs["sub_task_conf_info_t"].size
    subtask_section_base = profile.files["micc"].sections[1].offset
    source_subtask = micc[subtask_section_base : subtask_section_base + subtask_size]

    struct.pack_into("<Q", micc, task_base + 8, 3)
    struct.pack_into("<Q", micc, task_base + 24, 0)
    struct.pack_into("<Q", micc, task_base + 32, 1)
    struct.pack_into("<Q", micc, task_base + 40, 2)

    for subtask_id in (1, 2):
        subtask_base = subtask_section_base + subtask_id * subtask_size
        micc[subtask_base : subtask_base + subtask_size] = source_subtask
        struct.pack_into("<B", micc, subtask_base, 0)
        struct.pack_into("<B", micc, subtask_base + 1, 0)
        struct.pack_into("<Q", micc, subtask_base + 266312, subtask_id)
        block_conf = subtask_base + 72 + 48
        struct.pack_into("<Q", micc, block_conf + 384, subtask_id)

    subtask0 = subtask_section_base
    struct.pack_into("<B", micc, subtask0, 1)
    struct.pack_into("<B", micc, subtask0 + 1, 0)
    subtask1 = subtask_section_base + subtask_size
    struct.pack_into("<Q", micc, subtask1 + 24, 2)
    subtask2 = subtask_section_base + 2 * subtask_size
    struct.pack_into("<B", micc, subtask2 + 1, 1)
    struct.pack_into("<Q", micc, subtask2 + 24, 1)
    micc_path.write_bytes(micc)

    report = run_dfu3500_control_graph_check(
        tmp_path,
        profile,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert "dfu3500_subtask_successor_cycle" in {
        issue.code for issue in report.issues
    }


def test_dfu3500_control_graph_catches_unreachable_subtask(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    micc_path = tmp_path / "result/micc_file.bin"
    micc = bytearray(micc_path.read_bytes())
    task_base = 0
    subtask_size = profile.structs["sub_task_conf_info_t"].size
    subtask_section_base = profile.files["micc"].sections[1].offset
    source_subtask = micc[subtask_section_base : subtask_section_base + subtask_size]

    struct.pack_into("<Q", micc, task_base + 8, 3)
    struct.pack_into("<Q", micc, task_base + 24, 0)
    struct.pack_into("<Q", micc, task_base + 32, 1)
    struct.pack_into("<Q", micc, task_base + 40, 2)

    for subtask_id in (1, 2):
        subtask_base = subtask_section_base + subtask_id * subtask_size
        micc[subtask_base : subtask_base + subtask_size] = source_subtask
        struct.pack_into("<B", micc, subtask_base, 0)
        struct.pack_into("<B", micc, subtask_base + 1, 0)
        struct.pack_into("<Q", micc, subtask_base + 266312, subtask_id)
        block_conf = subtask_base + 72 + 48
        struct.pack_into("<Q", micc, block_conf + 384, subtask_id)

    subtask0 = subtask_section_base
    struct.pack_into("<B", micc, subtask0, 1)
    struct.pack_into("<B", micc, subtask0 + 1, 0)
    struct.pack_into("<Q", micc, subtask0 + 24, 1)
    subtask2 = subtask_section_base + 2 * subtask_size
    struct.pack_into("<B", micc, subtask2 + 1, 1)
    micc_path.write_bytes(micc)

    report = run_dfu3500_control_graph_check(
        tmp_path,
        profile,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert "dfu3500_subtask_unreachable_from_start" in {
        issue.code for issue in report.issues
    }


def test_dfu3500_control_graph_catches_root_block_count_mismatch(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)
    micc_path = tmp_path / "result/micc_file.bin"
    micc = bytearray(micc_path.read_bytes())
    subtask_base = DFU3500_SIMICT_LEGACY_PROFILE.files["micc"].sections[1].offset
    struct.pack_into("<Q", micc, subtask_base + 56, 0)
    micc_path.write_bytes(micc)

    report = run_dfu3500_control_graph_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert "dfu3500_subtask_root_block_missing" in {
        issue.code for issue in report.issues
    }


def test_dfu3500_control_graph_catches_stage_span_out_of_range(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    micc_path = tmp_path / "result/micc_file.bin"
    micc = bytearray(micc_path.read_bytes())
    subtask_base = profile.files["micc"].sections[1].offset
    conf_base = subtask_base + 72 + 48
    inst_limit = profile.files["cbuf"].sections[0].dimensions[1].size
    struct.pack_into("<Q", micc, conf_base + 16, inst_limit - 1)
    struct.pack_into("<Q", micc, conf_base + 432, 2)
    micc_path.write_bytes(micc)

    report = run_dfu3500_control_graph_check(
        tmp_path,
        profile,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert "dfu3500_exeblock_stage_span_out_of_range" in {
        issue.code for issue in report.issues
    }


def test_dfu3500_control_graph_catches_unmatched_exeblock_successor(
    tmp_path: Path,
) -> None:
    _write_runtime_ready_payload(tmp_path)
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    micc_path = tmp_path / "result/micc_file.bin"
    micc = bytearray(micc_path.read_bytes())
    subtask_base = profile.files["micc"].sections[1].offset
    struct.pack_into("<Q", micc, subtask_base + 64, 2)

    block_size = profile.structs["exeBlock_conf_info_t"].size
    block0_base = subtask_base + 72
    block0_conf = block0_base + 48
    struct.pack_into("<Q", micc, block0_conf + 408, 1)
    struct.pack_into("<Q", micc, block0_conf + 216, 1)

    block1_base = block0_base + block_size
    block1_conf = block1_base + 48
    struct.pack_into("<B", micc, block1_base, 1)
    struct.pack_into("<Q", micc, block1_base + 8, 1)
    struct.pack_into("<Q", micc, block1_base + 40, 0)
    struct.pack_into("<Q", micc, block1_conf + 376, 1)
    struct.pack_into("<Q", micc, block1_conf + 384, 0)
    struct.pack_into("<Q", micc, block1_conf + 392, 0)
    struct.pack_into("<Q", micc, block1_conf + 400, 1)
    struct.pack_into("<Q", micc, block1_conf + 432, 1)
    micc_path.write_bytes(micc)

    report = run_dfu3500_control_graph_check(
        tmp_path,
        profile,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert "dfu3500_exeblock_successor_predecessor_mismatch" in {
        issue.code for issue in report.issues
    }


def test_dfu3500_control_graph_catches_missing_exeblock_predecessor(
    tmp_path: Path,
) -> None:
    _write_runtime_ready_payload(tmp_path)
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    micc_path = tmp_path / "result/micc_file.bin"
    micc = bytearray(micc_path.read_bytes())
    subtask_base = profile.files["micc"].sections[1].offset
    conf_base = subtask_base + 72 + 48
    struct.pack_into("<Q", micc, conf_base, 1)
    struct.pack_into("<Q", micc, conf_base + 56, 7)
    micc_path.write_bytes(micc)

    report = run_dfu3500_control_graph_check(
        tmp_path,
        profile,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert "dfu3500_exeblock_predecessor_missing" in {
        issue.code for issue in report.issues
    }
    assert "dfu3500_exeblock_root_count_mismatch" in {
        issue.code for issue in report.issues
    }


def test_dfu3500_control_graph_catches_exeblock_successor_cycle(
    tmp_path: Path,
) -> None:
    _write_runtime_ready_payload(tmp_path)
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    micc_path = tmp_path / "result/micc_file.bin"
    micc = bytearray(micc_path.read_bytes())
    subtask_base = profile.files["micc"].sections[1].offset
    struct.pack_into("<Q", micc, subtask_base + 56, 1)
    struct.pack_into("<Q", micc, subtask_base + 64, 3)

    block_size = profile.structs["exeBlock_conf_info_t"].size
    block0_base = subtask_base + 72
    block0_conf = block0_base + 48
    struct.pack_into("<Q", micc, block0_conf + 408, 1)
    struct.pack_into("<Q", micc, block0_conf + 216, 1)

    block1_base = block0_base + block_size
    block1_conf = block1_base + 48
    struct.pack_into("<B", micc, block1_base, 1)
    struct.pack_into("<Q", micc, block1_base + 8, 1)
    struct.pack_into("<Q", micc, block1_base + 40, 0)
    struct.pack_into("<Q", micc, block1_conf, 2)
    struct.pack_into("<Q", micc, block1_conf + 56, 0)
    struct.pack_into("<Q", micc, block1_conf + 64, 2)
    struct.pack_into("<Q", micc, block1_conf + 216, 2)
    struct.pack_into("<Q", micc, block1_conf + 376, 1)
    struct.pack_into("<Q", micc, block1_conf + 384, 0)
    struct.pack_into("<Q", micc, block1_conf + 392, 0)
    struct.pack_into("<Q", micc, block1_conf + 400, 1)
    struct.pack_into("<Q", micc, block1_conf + 408, 1)
    struct.pack_into("<Q", micc, block1_conf + 432, 1)

    block2_base = block1_base + block_size
    block2_conf = block2_base + 48
    struct.pack_into("<B", micc, block2_base, 1)
    struct.pack_into("<Q", micc, block2_base + 8, 2)
    struct.pack_into("<Q", micc, block2_base + 40, 0)
    struct.pack_into("<Q", micc, block2_conf, 1)
    struct.pack_into("<Q", micc, block2_conf + 56, 1)
    struct.pack_into("<Q", micc, block2_conf + 216, 1)
    struct.pack_into("<Q", micc, block2_conf + 376, 2)
    struct.pack_into("<Q", micc, block2_conf + 384, 0)
    struct.pack_into("<Q", micc, block2_conf + 392, 0)
    struct.pack_into("<Q", micc, block2_conf + 400, 1)
    struct.pack_into("<Q", micc, block2_conf + 408, 1)
    struct.pack_into("<Q", micc, block2_conf + 432, 1)
    micc_path.write_bytes(micc)

    report = run_dfu3500_control_graph_check(
        tmp_path,
        profile,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert "dfu3500_exeblock_successor_cycle" in {
        issue.code for issue in report.issues
    }


def test_source_fingerprint_warn_is_diagnostic_without_source_root() -> None:
    report = run_source_fingerprint_check(
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "diagnostic_only"
    assert report.authoritative is False
    assert report.issues[0].code == "source_root_missing"


def test_source_fingerprint_explicit_strict_blocks_without_source_root() -> None:
    report = run_source_fingerprint_check(
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
        mode="strict",
    )

    assert report.status == "blocked"
    assert report.authoritative is True
    assert report.issues[0].code == "source_root_missing"


def test_source_fingerprint_explicit_strict_detects_mismatch(tmp_path: Path) -> None:
    source_file = tmp_path / "common/src/inst_def.h"
    source_file.parent.mkdir(parents=True)
    source_file.write_text("wrong snapshot\n")

    report = run_source_fingerprint_check(
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
        source_root=tmp_path,
        mode="strict",
    )

    assert report.status == "fail"
    assert report.authoritative is True
    codes = {issue.code for issue in report.issues}
    assert "source_fingerprint_mismatch" in codes
    assert "source_file_missing" in codes


def test_validate_payload_passes_package_complete_with_warn_fingerprints(tmp_path: Path) -> None:
    _write_package_complete_payload(tmp_path)

    suite = validate_payload(tmp_path, requested_gate=ReadinessLevel.PACKAGE_COMPLETE)

    assert suite.final_status == "pass"
    assert suite.manifest_path == str(tmp_path / "MANIFEST.txt")
    statuses = {report.check_name: report.status for report in suite.reports}
    assert statuses["profile_conformance"] == "pass"
    assert statuses["payload_conformance"] == "pass"
    assert statuses["source_fingerprint_check"] == "diagnostic_only"
    assert "runtime_readiness" not in statuses


def test_validate_payload_passes_runtime_ready_with_runtime_metadata(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)

    suite = validate_payload(tmp_path, requested_gate=ReadinessLevel.RUNTIME_READY)

    assert suite.final_status == "pass"
    statuses = {report.check_name: report.status for report in suite.reports}
    assert statuses["payload_conformance"] == "pass"
    assert statuses["runtime_readiness"] == "pass"
    assert statuses["runtime_memory_layout"] == "pass"
    assert statuses["dfu3500_component_consistency"] == "pass"
    assert statuses["dfu3500_control_graph"] == "pass"
    assert statuses["dfu3500_instruction_span"] == "pass"
    assert statuses["dfu3500_opcode_conformance"] == "pass"
    assert statuses["dfu3500_operand_resource"] == "pass"
    assert statuses["dfu3500_memory_template"] == "pass"
    assert statuses["source_fingerprint_check"] == "diagnostic_only"


def test_partner_payload_build_archives_runtime_ready_report(tmp_path: Path) -> None:
    workflow_dir = ROOT / "compiler/gpdpu_compiler/validation/dfu3500_partner_validation"
    sys.path.insert(0, str(workflow_dir))
    try:
        from gpdpu_compiler.validation.dfu3500_partner_validation.build_payloads import (
            validate_built_payload,
        )
    finally:
        sys.path.remove(str(workflow_dir))

    _write_runtime_ready_payload(tmp_path)

    validate_built_payload(tmp_path)

    report_path = tmp_path / "validation/runtime_ready.json"
    report = json.loads(report_path.read_text())
    assert report["requested_gate"] == "runtime_ready"
    assert report["final_status"] == "pass"
    assert {entry["check_name"] for entry in report["reports"]} == {
        "profile_conformance",
        "source_fingerprint_check",
            "payload_conformance",
            "runtime_readiness",
            "runtime_memory_layout",
            "dfu3500_component_consistency",
            "dfu3500_control_graph",
            "dfu3500_instruction_span",
            "dfu3500_opcode_conformance",
            "dfu3500_operand_resource",
            "dfu3500_memory_template",
        }


def test_archived_report_freshness_accepts_current_payload(tmp_path: Path) -> None:
    workflow_dir = ROOT / "compiler/gpdpu_compiler/validation/dfu3500_partner_validation"
    sys.path.insert(0, str(workflow_dir))
    try:
        from gpdpu_compiler.validation.dfu3500_partner_validation.build_payloads import (
            validate_built_payload,
        )
    finally:
        sys.path.remove(str(workflow_dir))

    _write_runtime_ready_payload(tmp_path)
    validate_built_payload(tmp_path)

    report = run_archived_report_freshness_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "pass"
    assert "validation/runtime_ready.json" in report.input_paths


def test_archived_report_freshness_catches_stale_payload_bytes(tmp_path: Path) -> None:
    workflow_dir = ROOT / "compiler/gpdpu_compiler/validation/dfu3500_partner_validation"
    sys.path.insert(0, str(workflow_dir))
    try:
        from gpdpu_compiler.validation.dfu3500_partner_validation.build_payloads import (
            validate_built_payload,
        )
    finally:
        sys.path.remove(str(workflow_dir))

    _write_runtime_ready_payload(tmp_path)
    validate_built_payload(tmp_path)
    micc_path = tmp_path / "result/micc_file.bin"
    micc = bytearray(micc_path.read_bytes())
    micc[0] ^= 0x01
    micc_path.write_bytes(micc)

    report = run_archived_report_freshness_check(
        tmp_path,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )

    assert report.status == "fail"
    assert "archived_validation_report_input_sha256_mismatch" in {
        issue.code for issue in report.issues
    }


def test_aggregate_reports_blocks_when_no_authoritative_check_for_gate() -> None:
    report = ValidationReport(
        schema_version="dfu_validation_check_report_v1",
        check_name="diagnostic_probe",
        status="diagnostic_only",
        authoritative=False,
        requested_gate=ReadinessLevel.RUNTIME_READY,
        profile_id=None,
        profile_sha256=None,
        input_paths=(),
        input_sha256={},
        policy={},
        issues=(ValidationIssue(severity="info", code="note", message="not enough"),),
    )

    assert aggregate_reports([report], requested_gate=ReadinessLevel.RUNTIME_READY) == "blocked"
