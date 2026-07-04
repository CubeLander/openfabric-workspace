#!/usr/bin/env python3
"""Guard the partner-validation upload entrypoint against stale payloads.

The remote commander runs ``dfu3500_partner_validation/run.sh``.  This guard
parses that entrypoint, finds the payload directories it will actually select,
rebuilds those cases in a temporary directory, and verifies that the committed
``payloads/<case>/`` trees are byte-identical to the fresh build.

This catches the dangerous failure mode where a developer validates a temporary
payload directory locally but packages an older payload tree for arch-13.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import shutil
import sys
import tempfile
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPILER_ROOT = REPO_ROOT / "compiler"
VALIDATION_ROOT = (
    COMPILER_ROOT
    / "gpdpu_compiler"
    / "validation"
    / "dfu3500_partner_validation"
)
for path in (str(COMPILER_ROOT), str(VALIDATION_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import build_payloads  # noqa: E402
from gpdpu_compiler.decoder.profiles import DFU3500_SIMICT_LEGACY_PROFILE  # noqa: E402
from gpdpu_compiler.validation.dfu_binary_checks import (  # noqa: E402
    ReadinessLevel,
    run_archived_report_freshness_check,
)


ARCHIVED_VALIDATION_REPORTS = {Path("validation/runtime_ready.json")}
PROGRESS_UPLOAD_CASES = {
    "bline_gemm_no_relu",
    "bline_gemm_relu",
    "log10max_single_task",
}
PROGRESS_REQUIRED_FILES = (
    Path("MANIFEST.txt"),
    Path("result/cbuf_file.bin"),
    Path("result/micc_file.bin"),
    Path("config/cbuf_file.bin"),
    Path("config/micc_file.bin"),
    Path("simulator_bin/insts_file.bin"),
    Path("simulator_bin/exeblock_conf_info_file.bin"),
    Path("simulator_bin/instance_conf_info_file.bin"),
    Path("simulator_bin/tasks_conf_info_file.bin"),
    Path("simulator_bin/subtasks_conf_info_file.bin"),
    Path("validation/runtime_ready.json"),
)


def _sha256(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _case_by_id(case_id: str) -> build_payloads.PayloadCase:
    for case in build_payloads.PAYLOAD_CASES:
        if case.case_id == case_id:
            return case
    raise AssertionError("run.sh selects unknown payload case: %s" % case_id)


def _manifest(path: Path) -> dict[str, str]:
    result: dict[str, str] = {}
    for line in path.read_text().splitlines():
        if not line.strip() or "=" not in line:
            continue
        key, value = line.split("=", 1)
        result[key.strip()] = value.strip()
    return result


def _selected_payload_cases(run_sh: Path) -> tuple[str, ...]:
    text = run_sh.read_text()
    pattern = re.compile(
        r'ln\s+-s\s+"\$SCRIPT_DIR/payloads/([^"]+)"\s*'
        r'(?:\\\s*\n\s*)?'
        r'"\$SELECTED_PAYLOADS_DIR/([^"]+)"'
    )
    cases: list[str] = []
    for match in pattern.finditer(text):
        source_case, selected_case = match.groups()
        if source_case != selected_case:
            raise AssertionError(
                "run.sh symlink source/destination case mismatch: %s -> %s"
                % (source_case, selected_case)
            )
        cases.append(source_case)
    if not cases:
        raise AssertionError("run.sh does not select any payloads via payloads/<case>")
    duplicates = sorted(case for case in set(cases) if cases.count(case) > 1)
    if duplicates:
        raise AssertionError("run.sh selects duplicate payload cases: %s" % duplicates)
    return tuple(cases)


def _relative_files(root: Path) -> set[Path]:
    return {
        path.relative_to(root)
        for path in root.rglob("*")
        if path.is_file()
    }


def _compare_payload_tree(actual: Path, expected: Path) -> None:
    actual_files = _relative_files(actual) - ARCHIVED_VALIDATION_REPORTS
    expected_files = _relative_files(expected) - ARCHIVED_VALIDATION_REPORTS
    missing = sorted(expected_files - actual_files)
    extra = sorted(actual_files - expected_files)
    if missing or extra:
        raise AssertionError(
            "payload file set mismatch for %s: missing=%s extra=%s"
            % (actual.name, [str(p) for p in missing], [str(p) for p in extra])
        )
    mismatches = []
    for rel in sorted(expected_files):
        actual_path = actual / rel
        expected_path = expected / rel
        if actual_path.stat().st_size != expected_path.stat().st_size:
            mismatches.append(
                "%s size %s != %s"
                % (rel, actual_path.stat().st_size, expected_path.stat().st_size)
            )
            continue
        actual_sha = _sha256(actual_path)
        expected_sha = _sha256(expected_path)
        if actual_sha != expected_sha:
            mismatches.append("%s sha %s != %s" % (rel, actual_sha, expected_sha))
    if mismatches:
        preview = "; ".join(mismatches[:12])
        suffix = "" if len(mismatches) <= 12 else " ... (+%d more)" % (len(mismatches) - 12)
        raise AssertionError("stale payload tree for %s: %s%s" % (actual.name, preview, suffix))


def _require_runtime_consistency(payload: Path, case: build_payloads.PayloadCase) -> None:
    manifest_path = payload / "MANIFEST.txt"
    control_path = payload / "runtime" / "riscv_src" / "riscv_control.json"
    conf_path = payload / "runtime" / "riscv_src" / "csv_generate" / "conf.h"
    testarm_path = payload / "runtime" / "riscv_src" / "riscv" / "testarm.c"
    for path in (manifest_path, control_path, conf_path, testarm_path):
        if not path.exists():
            raise AssertionError("selected payload missing runtime artifact: %s" % path)

    manifest = _manifest(manifest_path)
    if manifest.get("case_id") != case.case_id:
        raise AssertionError("manifest case_id mismatch for %s" % case.case_id)
    if manifest.get("task_num") != str(case.task_num):
        raise AssertionError(
            "manifest task_num mismatch for %s: %r != %s"
            % (case.case_id, manifest.get("task_num"), case.task_num)
        )
    if manifest.get("runtime_runnable") != "1":
        raise AssertionError("selected payload is not runtime_runnable=1: %s" % case.case_id)

    control = json.loads(control_path.read_text())
    launches = control.get("launches", [])
    if len(launches) != 1:
        raise AssertionError("guard currently expects one launch for %s" % case.case_id)
    if int(launches[0].get("task_count", -1)) != int(case.task_num):
        raise AssertionError(
            "runtime_control task_count mismatch for %s: %r != %s"
            % (case.case_id, launches[0].get("task_count"), case.task_num)
        )

    conf_text = conf_path.read_text()
    expected_define = "#define TASK_NUM %d" % int(case.task_num)
    if expected_define not in conf_text:
        raise AssertionError("conf.h missing %s for %s" % (expected_define, case.case_id))

    testarm_text = testarm_path.read_text()
    expected_start = "DPU_Kernel_Start(1, %d," % int(case.task_num)
    if expected_start not in testarm_text:
        raise AssertionError(
            "testarm.c does not launch expected task count for %s: missing %s"
            % (case.case_id, expected_start)
        )

    micc_path = payload / "result" / "micc_file.bin"
    manifest_micc_size = manifest.get("result_micc_file.bin_size")
    if manifest_micc_size != str(micc_path.stat().st_size):
        raise AssertionError(
            "manifest/result MICC size mismatch for %s: %s != %s"
            % (case.case_id, manifest_micc_size, micc_path.stat().st_size)
        )

    freshness = run_archived_report_freshness_check(
        payload,
        DFU3500_SIMICT_LEGACY_PROFILE,
        requested_gate=ReadinessLevel.RUNTIME_READY,
    )
    if freshness.status != "pass":
        issue_codes = [issue.code for issue in freshness.issues]
        raise AssertionError(
            "archived validation report is stale for %s: %s"
            % (case.case_id, issue_codes)
        )


def _require_progress_payload_consistency(payload: Path, case_id: str) -> None:
    missing = [
        str(rel)
        for rel in PROGRESS_REQUIRED_FILES
        if not (payload / rel).exists()
    ]
    if missing:
        raise AssertionError(
            "progress payload missing required files for %s: %s"
            % (case_id, missing)
        )

    manifest = _manifest(payload / "MANIFEST.txt")
    if case_id.startswith("bline_gemm_"):
        expected_operator = {
            "bline_gemm_no_relu": "gemm_no_relu",
            "bline_gemm_relu": "gemm_relu",
        }[case_id]
        if manifest.get("operator") != expected_operator:
            raise AssertionError("progress manifest operator mismatch for %s" % case_id)
        if manifest.get("payload_status") != "progress_first_tactical_binary_seed":
            raise AssertionError("unexpected progress payload status for %s" % case_id)
        required_extra = (
            Path("PROGRESS_METADATA.json"),
            Path("runtime/input_data.bin"),
            Path("runtime/input_data_m.bin"),
            Path("runtime/riscv_src/riscv/testarm.c"),
            Path("runtime/riscv_src/riscv/dpuctrl.c"),
            Path("runtime/riscv_src/riscv/makefile"),
            Path("runtime/riscv_src/csv_generate/conf.h"),
            Path("runtime/riscv_src/dpuapi/DpuAPI.c"),
            Path("runtime/riscv_src/dpuapi/DpuAPI.h"),
        )
    elif case_id == "log10max_single_task":
        if manifest.get("case_id") != case_id:
            raise AssertionError("log10max manifest case_id mismatch")
        if manifest.get("runtime_package_complete") != "1":
            raise AssertionError("log10max progress payload is not package-complete")
        expected_strategy_fields = {
            "collective_strategy": "ring_spmd_row_then_col",
            "customer_collective_label": "spmd_ring_materialized_reduce",
            "direct_route_reduce_broadcast": "deferred",
            "task_axis": "1",
            "runtime_ordering_domain": "single_task_group",
            "cross_task_one_app_ring": "forbidden",
            "cross_task_visibility_claim": "0",
        }
        for key, expected_value in expected_strategy_fields.items():
            if manifest.get(key) != expected_value:
                raise AssertionError(
                    "log10max manifest %s mismatch: expected %s, got %s"
                    % (key, expected_value, manifest.get(key))
                )
        required_extra = (
            Path("chip_program.json"),
            Path("runtime/input_data.bin"),
            Path("runtime/riscv_src/riscv_control.json"),
            Path("runtime/riscv_src/riscv/testarm.c"),
            Path("runtime/riscv_src/riscv/makefile"),
            Path("runtime/riscv_src/csv_generate/conf.h"),
            Path("runtime/riscv_src/dpuapi/DpuAPI.c"),
            Path("runtime/riscv_src/dpuapi/DpuAPI.h"),
            Path("reference/Y.fp32.bin"),
            Path("reference/mel_spec.fp32.bin"),
            Path("reference/reference.json"),
        )
    else:
        raise AssertionError("unknown progress upload case: %s" % case_id)

    for rel in required_extra:
        if not (payload / rel).exists():
            raise AssertionError(
                "progress payload missing %s for %s" % (rel, case_id)
            )

    _require_manifest_file_records(payload, manifest)
    report = json.loads((payload / "validation" / "runtime_ready.json").read_text())
    if report.get("final_status") not in {"pass", "fail"}:
        raise AssertionError("runtime_ready report missing final_status for %s" % case_id)
    if case_id == "log10max_single_task":
        operator_metadata = report.get("operator_metadata", {})
        if operator_metadata.get("collective_strategy") != "ring_spmd_row_then_col":
            raise AssertionError("runtime_ready metadata missing log10max ring strategy")
        if operator_metadata.get("runtime_ordering_domain") != "single_task_group":
            raise AssertionError("runtime_ready metadata missing ordering domain")


def _require_manifest_file_records(payload: Path, manifest: dict[str, str]) -> None:
    for rel in PROGRESS_REQUIRED_FILES:
        if rel.name == "MANIFEST.txt":
            continue
        key = str(rel).replace("/", "_")
        size = manifest.get("%s_size" % key)
        digest = manifest.get("%s_sha256" % key)
        path = payload / rel
        if size is not None and size != str(path.stat().st_size):
            raise AssertionError("manifest size mismatch for %s" % rel)
        if digest is not None and digest != _sha256(path):
            raise AssertionError("manifest sha mismatch for %s" % rel)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--validation-root",
        type=Path,
        default=VALIDATION_ROOT,
        help="dfu3500_partner_validation directory",
    )
    args = parser.parse_args()

    validation_root = args.validation_root.resolve()
    run_sh = validation_root / "run.sh"
    payload_root = validation_root / "payloads"
    selected_cases = _selected_payload_cases(run_sh)

    with tempfile.TemporaryDirectory(prefix="openfabric_entrypoint_guard_") as tmp:
        expected_root = Path(tmp) / "payloads"
        for case_id in selected_cases:
            actual_payload = payload_root / case_id
            if not actual_payload.exists():
                raise AssertionError("selected payload directory missing: %s" % actual_payload)
            if case_id in PROGRESS_UPLOAD_CASES:
                _require_progress_payload_consistency(actual_payload, case_id)
                continue
            case = _case_by_id(case_id)
            build_payloads.build_case(case, expected_root)
            expected_payload = expected_root / case.case_id
            _compare_payload_tree(actual_payload, expected_payload)
            _require_runtime_consistency(actual_payload, case)

    print("partner_validation_entrypoint_guard=PASS")
    print("validation_root=%s" % validation_root)
    print("selected_payloads=%s" % ",".join(selected_cases))


if __name__ == "__main__":
    main()
