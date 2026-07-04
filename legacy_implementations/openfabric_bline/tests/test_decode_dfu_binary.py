from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "compiler"))

from gpdpu_compiler.decoder.binary_decoder import decode_row, decode_summary, lookup_offset
from gpdpu_compiler.decoder.binary_diff import diff_binary_bytes
from gpdpu_compiler.decoder.dfu3500_diagnostics import (
    diff_dfu3500_micc_control,
    summarize_dfu3500_micc_control,
)
from gpdpu_compiler.decoder.coverage import make_coverage_report
from gpdpu_compiler.decoder.profiles import DFU3500_SIMICT_LEGACY_PROFILE


def test_dfu3500_profile_sizes_and_invariants() -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE

    assert profile.validate() == ()
    assert profile.structs["inst_t"].size == 304
    assert profile.structs["exeBlock_conf_info_t"].size == 520
    assert profile.structs["sub_task_conf_info_t"].size == 266328
    assert profile.files["cbuf"].size(profile) == 23_531_520
    assert profile.files["micc"].size(profile) == 8_522_976
    assert len(profile.profile_sha256()) == 64
    assert profile.source_fingerprints["common/src/inst_def.h"] == (
        "b263f25e62403d4f1e365aafcec046e76c0c0030f1b6590ac4fb0d90aaa04a4a"
    )


def test_offset_lookup_decodes_known_inst_field() -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    data = bytearray(profile.files["cbuf"].size(profile))
    inst_offset = 18 * profile.structs["inst_t"].size
    struct.pack_into("<I", data, inst_offset, 80)
    struct.pack_into("<Q", data, inst_offset + 8, 20)

    opcode = lookup_offset(
        bytes(data),
        file_kind="cbuf",
        offset=inst_offset,
        profile=profile,
    )
    unit_type = lookup_offset(
        bytes(data),
        file_kind="cbuf",
        offset=inst_offset + 8,
        profile=profile,
    )

    assert opcode.classification == "known_field"
    assert opcode.path == "cbuf.insts[pe_index=0][inst_idx=18].opCode"
    assert opcode.value == 80
    assert opcode.annotation is not None
    assert opcode.annotation["opcode"] == 80
    assert opcode.annotation["mnemonic"] == "HADD"
    assert opcode.annotation["category"] == "simd_numeric"
    assert opcode.annotation["latency"] == 72
    assert opcode.annotation["src_count"] == 2
    assert opcode.annotation["unit_inst_type"] == 2
    assert opcode.annotation["pseudo"] is False
    assert unit_type.path == "cbuf.insts[pe_index=0][inst_idx=18].unit_inst_type"
    assert unit_type.value == 20


def test_offset_lookup_reports_padding() -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    data = bytes(profile.files["cbuf"].size(profile))

    lookup = lookup_offset(data, file_kind="cbuf", offset=4, profile=profile)

    assert lookup.classification == "known_padding"
    assert lookup.struct == "inst_t"


def test_offset_lookup_decodes_nested_micc_exeblock_field() -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    data = bytearray(profile.files["micc"].size(profile))
    offset = (
        480
        + 72
        + 48
        + 392
    )
    struct.pack_into("<Q", data, offset, 3)

    lookup = lookup_offset(bytes(data), file_kind="micc", offset=offset, profile=profile)

    assert lookup.classification == "known_field"
    assert lookup.path == (
        "micc.subtasks[task=0][subtask=0]."
        "exeBlocks_conf_info[0].exeBlock_conf.task_idx"
    )
    assert lookup.value == 3


def test_summary_reports_active_ish_rows_without_claiming_control_semantics() -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    data = bytearray(profile.files["micc"].size(profile))
    struct.pack_into("<Q", data, 8, 1)

    report = decode_summary(bytes(data), file_kind="micc", profile=profile)

    assert report["schema_version"] == "dfu_binary_decode_report_v1"
    assert report["status"] == "ok"
    tasks = report["sections"][0]
    assert tasks["name"] == "tasks"
    assert tasks["active_ish"]["summary_kind"] == "heuristic_nonzero_markers"
    assert tasks["active_ish"]["control_semantics_verified"] is False
    assert tasks["active_ish"]["nonzero_row_count"] == 1


def test_decode_row_reports_scalar_arrays_and_paths() -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    data = bytearray(profile.files["micc"].size(profile))
    struct.pack_into("<Q", data, 8, 2)
    struct.pack_into("<Q", data, 24, 5)

    report = decode_row(
        bytes(data),
        file_kind="micc",
        section_name="tasks",
        row_index=0,
        profile=profile,
    )

    assert report["status"] == "ok"
    assert report["row"]["path"] == "micc.tasks[task=0]"
    fields = {field["field"]: field for field in report["row"]["fields"]}
    assert fields["subtasks_amount"]["values"][0]["value"] == 2
    assert fields["subtasks_idx"]["values"][0]["path"] == (
        "micc.tasks[task=0].subtasks_idx[0]"
    )
    assert fields["subtasks_idx"]["values"][0]["value"] == 5


def test_decode_row_annotates_inst_opcode_mnemonics() -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    data = bytearray(profile.files["cbuf"].size(profile))
    struct.pack_into("<I", data, 0, 0x27)
    second_inst = profile.structs["inst_t"].size
    struct.pack_into("<I", data, second_inst, 0xD4)

    fmax = decode_row(
        bytes(data),
        file_kind="cbuf",
        section_name="insts",
        row_index=0,
        profile=profile,
    )
    flog2 = decode_row(
        bytes(data),
        file_kind="cbuf",
        section_name="insts",
        row_index=1,
        profile=profile,
    )

    fmax_fields = {field["field"]: field for field in fmax["row"]["fields"]}
    flog2_fields = {field["field"]: field for field in flog2["row"]["fields"]}
    assert fmax_fields["opCode"]["values"][0]["annotation"]["mnemonic"] == "FMAX"
    assert flog2_fields["opCode"]["values"][0]["annotation"]["mnemonic"] == "FLOG2"


def test_decode_row_summarizes_large_struct_arrays() -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    data = bytearray(profile.files["micc"].size(profile))
    struct.pack_into("<B", data, 480 + 72, 1)
    struct.pack_into("<Q", data, 480 + 72 + 520 + 8, 9)

    report = decode_row(
        bytes(data),
        file_kind="micc",
        section_name="subtasks",
        row_index=0,
        profile=profile,
        max_array_elements=4,
    )

    fields = {field["field"]: field for field in report["row"]["fields"]}
    embedded_blocks = fields["exeBlocks_conf_info"]
    assert embedded_blocks["decode_status"] == "array_summary"
    assert embedded_blocks["count"] == 512
    assert embedded_blocks["nonzero_element_count"] == 2


def test_json_report_is_deterministic_serializable() -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    report = decode_summary(
        bytes(profile.files["micc"].size(profile)),
        file_kind="micc",
        profile=profile,
    )

    first = json.dumps(report, sort_keys=True)
    second = json.dumps(report, sort_keys=True)

    assert first == second


def test_diff_groups_known_field_changes() -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    left = bytearray(profile.files["micc"].size(profile))
    right = bytearray(profile.files["micc"].size(profile))
    struct.pack_into("<Q", right, 8, 0x0102)

    report = diff_binary_bytes(
        bytes(left),
        bytes(right),
        file_kind="micc",
        profile=profile,
        max_diffs=10,
    )

    assert report["byte_diff_count"] == 2
    assert report["diff_group_count"] == 1
    assert report["field_diff_count"] == 1
    assert report["diffs"][0]["diff_kind"] == "value_diff"
    assert report["diffs"][0]["path"] == "micc.tasks[task=0].subtasks_amount"
    assert report["diffs"][0]["byte_offsets"] == [8, 9]
    assert report["diffs"][0]["right"]["value"] == 0x0102
    assert report["diffs"][0]["right"]["raw_hex"] == "0201000000000000"


def test_diff_classifies_padding_changes() -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    left = bytearray(profile.files["cbuf"].size(profile))
    right = bytearray(profile.files["cbuf"].size(profile))
    right[4] = 1

    report = diff_binary_bytes(
        bytes(left),
        bytes(right),
        file_kind="cbuf",
        profile=profile,
    )

    assert report["byte_diff_count"] == 1
    assert report["padding_diff_count"] == 1
    assert report["diffs"][0]["diff_kind"] == "padding_diff"
    assert report["diffs"][0]["classification"] == "known_padding"


def test_cli_offset_json(tmp_path: Path) -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    data = bytearray(profile.files["micc"].size(profile))
    struct.pack_into("<Q", data, 8, 7)
    path = tmp_path / "micc_file.bin"
    path.write_bytes(data)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "compiler/tools/decode_dfu_binary.py"),
            "--kind",
            "micc",
            "--input",
            str(path),
            "--offset",
            "8",
            "--format",
            "json",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(completed.stdout)

    assert payload["classification"] == "known_field"
    assert payload["path"] == "micc.tasks[task=0].subtasks_amount"
    assert payload["value"] == 7


def test_cli_row_json(tmp_path: Path) -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    data = bytearray(profile.files["micc"].size(profile))
    struct.pack_into("<Q", data, 8, 11)
    path = tmp_path / "micc_file.bin"
    path.write_bytes(data)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "compiler/tools/decode_dfu_binary.py"),
            "--kind",
            "micc",
            "--input",
            str(path),
            "--section",
            "tasks",
            "--row",
            "0",
            "--format",
            "json",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(completed.stdout)
    fields = {field["field"]: field for field in payload["row"]["fields"]}

    assert payload["row"]["path"] == "micc.tasks[task=0]"
    assert fields["subtasks_amount"]["values"][0]["value"] == 11


def test_cli_row_range_text(tmp_path: Path) -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    path = tmp_path / "tasks_conf_info_file.bin"
    path.write_bytes(bytes(profile.files["tasks"].size(profile)))

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "compiler/tools/decode_dfu_binary.py"),
            "--kind",
            "tasks",
            "--input",
            str(path),
            "--row-range",
            "0:2",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "rows 0:2 emitted=2 status=ok" in completed.stdout
    assert "tasks.tasks[task=0]" in completed.stdout


def test_cli_diff_fail_on_diff(tmp_path: Path) -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    left = bytearray(profile.files["micc"].size(profile))
    right = bytearray(profile.files["micc"].size(profile))
    struct.pack_into("<Q", right, 8, 1)
    left_path = tmp_path / "left_micc.bin"
    right_path = tmp_path / "right_micc.bin"
    left_path.write_bytes(left)
    right_path.write_bytes(right)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "compiler/tools/decode_dfu_binary.py"),
            "--kind",
            "micc",
            "--input",
            str(left_path),
            "--right",
            str(right_path),
            "--diff",
            "--fail-on-diff",
        ],
        text=True,
        capture_output=True,
    )

    assert completed.returncode == 1
    assert "diff_group_count=1" in completed.stdout


def test_dfu3500_micc_control_summary_detects_active_task_count() -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    good = bytearray(profile.files["micc"].size(profile))
    bad = bytearray(profile.files["micc"].size(profile))
    for task_id in range(4):
        task_offset = task_id * profile.structs["task_conf_info_t"].size
        struct.pack_into("<B", good, task_offset, 1)
        struct.pack_into("<B", good, task_offset + 1, 1)
        struct.pack_into("<Q", good, task_offset + 8, 3)
    struct.pack_into("<B", bad, 0, 1)
    struct.pack_into("<B", bad, 1, 1)
    struct.pack_into("<Q", bad, 8, 1)

    good_summary = summarize_dfu3500_micc_control(bytes(good), profile=profile)
    bad_summary = summarize_dfu3500_micc_control(bytes(bad), profile=profile)
    diff = diff_dfu3500_micc_control(good_summary, bad_summary)

    assert good_summary["active_task_count"] == 4
    assert bad_summary["active_task_count"] == 1
    assert diff["active_task_count"] == {"left": 4, "right": 1}
    assert diff["task_diff_count"] == 4
    assert diff["task_diffs"][1]["task_id"] == 1
    assert "active_ish" in diff["task_diffs"][1]["changed_fields"]


def test_payload_compare_cli_finds_cbuf_and_micc(tmp_path: Path) -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    (good / "result").mkdir(parents=True)
    (bad / "config").mkdir(parents=True)
    good_cbuf = bytearray(profile.files["cbuf"].size(profile))
    bad_cbuf = bytearray(profile.files["cbuf"].size(profile))
    good_micc = bytearray(profile.files["micc"].size(profile))
    bad_micc = bytearray(profile.files["micc"].size(profile))
    struct.pack_into("<I", bad_cbuf, 0, 80)
    struct.pack_into("<Q", bad_micc, 8, 1)
    (good / "result/cbuf_file.bin").write_bytes(good_cbuf)
    (good / "result/micc_file.bin").write_bytes(good_micc)
    (bad / "config/cbuf_file.bin").write_bytes(bad_cbuf)
    (bad / "config/micc_file.bin").write_bytes(bad_micc)
    report_path = tmp_path / "report.json"

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "compiler/tools/compare_dfu_payloads.py"),
            "--good",
            str(good),
            "--bad",
            str(bad),
            "--output",
            str(report_path),
            "--format",
            "json",
        ],
        check=True,
        text=True,
        capture_output=True,
    )
    payload = json.loads(completed.stdout)
    saved = json.loads(report_path.read_text())

    assert payload["summary"]["byte_diff_count"] == 2
    assert payload["micc_control"]["diff"]["active_task_count"] == {
        "left": 0,
        "right": 1,
    }
    assert saved["summary"]["files"]["cbuf"]["top_diff_paths"] == [
        "cbuf.insts[pe_index=0][inst_idx=0].opCode"
    ]
    assert saved["summary"]["files"]["micc"]["top_diff_paths"] == [
        "micc.tasks[task=0].subtasks_amount"
    ]


def test_payload_compare_cli_reports_profile_size_mismatch(tmp_path: Path) -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    good = tmp_path / "good"
    bad = tmp_path / "bad"
    (good / "result").mkdir(parents=True)
    (bad / "result").mkdir(parents=True)
    (good / "result/cbuf_file.bin").write_bytes(bytes(profile.files["cbuf"].size(profile)))
    (bad / "result/cbuf_file.bin").write_bytes(bytes(profile.files["cbuf"].size(profile)))
    (good / "result/micc_file.bin").write_bytes(bytes(profile.files["micc"].size(profile)))
    (bad / "result/micc_file.bin").write_bytes(bytes(120 + 2 * 266328))

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "compiler/tools/compare_dfu_payloads.py"),
            "--good",
            str(good),
            "--bad",
            str(bad),
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "micc_conformance: expected=8522976" in completed.stdout
    assert "bad size mismatch" in completed.stdout


def test_decoder_coverage_report_names_implemented_and_missing_areas() -> None:
    profile = DFU3500_SIMICT_LEGACY_PROFILE
    report = make_coverage_report(profile.profile_id)
    items = {item["area"]: item for item in report["items"]}

    assert report["schema_version"] == "dfu_binary_decoder_coverage_v1"
    assert items["cbuf_combined_image_layout"]["status"] == "implemented"
    assert items["auxiliary_sidecars"]["status"] == "documentation_only"
    assert items["route_endpoint_and_resource_semantics"]["status"] == "out_of_scope"


def test_cli_coverage_text_reports_boundaries() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "compiler/tools/decode_dfu_binary.py"),
            "--coverage",
        ],
        check=True,
        text=True,
        capture_output=True,
    )

    assert "coverage profile=dfu3500_simict_legacy_2026_06_20" in completed.stdout
    assert "implemented: cbuf_combined_image_layout" in completed.stdout
    assert "documentation_only: auxiliary_sidecars" in completed.stdout
