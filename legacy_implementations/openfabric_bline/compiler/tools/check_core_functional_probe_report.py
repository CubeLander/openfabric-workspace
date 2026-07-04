#!/usr/bin/env python3
"""Check the current-core functional probe report stays honest."""

from __future__ import annotations

import json
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


def _case_by_id(case_id: str) -> build_payloads.PayloadCase:
    for case in build_payloads.PAYLOAD_CASES:
        if case.case_id == case_id:
            return case
    raise AssertionError("missing payload case: %s" % case_id)


def _manifest_lines(path: Path) -> set[str]:
    return {
        line.strip()
        for line in path.read_text().splitlines()
        if line.strip()
    }


def main() -> None:
    case = _case_by_id("functional_maximum_single_app")
    with tempfile.TemporaryDirectory(prefix="openfabric_functional_probe_check_") as tmp:
        payload_root = Path(tmp) / "payloads"
        build_payloads.build_case(case, payload_root)
        payload = payload_root / case.case_id

        manifest = payload / "MANIFEST.txt"
        chip_program = payload / "chip_program.json"
        control_json = payload / "runtime" / "riscv_src" / "riscv_control.json"
        reference_y = payload / "reference" / "Y.fp32.bin"
        for required in (manifest, chip_program, control_json, reference_y):
            if not required.exists():
                raise AssertionError("missing generated artifact: %s" % required)
        size_expectations = {
            payload / "simulator_bin" / "tasks_conf_info_file.bin": 480,
            payload / "simulator_bin" / "subtasks_conf_info_file.bin": 8522496,
            payload / "result" / "micc_file.bin": 8522976,
            payload / "config" / "micc_file.bin": 8522976,
        }
        for path, expected_size in size_expectations.items():
            actual_size = path.stat().st_size
            if actual_size != expected_size:
                raise AssertionError(
                    "unexpected functional probe component size for %s: %s != %s"
                    % (path, actual_size, expected_size)
                )

        lines = _manifest_lines(manifest)
        expected_lines = {
            "case_id=functional_maximum_single_app",
            "vendor_inst_mode=legacy_template_compat",
            "load_rows_functional=1",
            "local_compute_rows_functional=1",
            "store_rows_functional=1",
            "inst_rows_functional=1",
            "runtime_package_complete=1",
            "runtime_control_assets_valid=1",
            "output_collection_supported=1",
            "reference_check_available=1",
            "runtime_runnable=1",
            "runtime_expectation=run_functional_runtime",
            "output_Y_reference=reference/Y.fp32.bin",
        }
        missing = sorted(expected_lines - lines)
        if missing:
            raise AssertionError("missing manifest lines: %s" % ", ".join(missing))

        plan = json.loads(chip_program.read_text())
        chip_ops = [
            op.get("op")
            for op in plan.get("chip_program", {}).get("ops", [])
            if isinstance(op, dict)
        ]
        if "maximum_scalar" not in chip_ops:
            raise AssertionError("probe must exercise maximum_scalar")
        forbidden_ops = {
            "reduce_max",
            "reduce_sum",
            "log10",
            "clamp_min",
            "broadcast_load",
            "reduce_store",
        }
        forbidden_present = sorted(forbidden_ops.intersection(chip_ops))
        if forbidden_present:
            raise AssertionError(
                "probe must avoid collective/log paths: %s"
                % ", ".join(forbidden_present)
            )

        template_program = plan.get("dfu3500_template_bound_program", {})
        unsupported = (
            template_program.get("unsupported_micro_ops", {})
            if isinstance(template_program, dict)
            else {}
        )
        role_counts: dict[str, int] = {}
        for record in unsupported.values():
            if isinstance(record, dict):
                role = str(record.get("role", "unknown"))
                role_counts[role] = role_counts.get(role, 0) + 1
        if role_counts:
            raise AssertionError("unexpected unsupported roles: %r" % role_counts)
        template_program = plan.get("dfu3500_template_bound_program", {})
        legacy_op_counts = template_program.get("totals", {}).get("legacy_op_counts", {})
        if (
            legacy_op_counts.get("LDM") != 64
            or legacy_op_counts.get("IMM") != 16
            or legacy_op_counts.get("FMAX") != 16
            or legacy_op_counts.get("STD") != 64
        ):
            raise AssertionError(
                "maximum scalar must bind compact input/IMM/FMAX/store templates: %r"
                % legacy_op_counts
            )
        active_instances = [
            row
            for row in plan.get("program_bin_rows", {})
            .get("instance_rows", {})
            .values()
            if isinstance(row, dict) and row.get("is_semantic_active")
        ]
        active_base_by_subtask = {
            int(row["subtask_index"]): row.get("base_addr_words_hex")
            for row in active_instances
        }
        if active_base_by_subtask.get(0) != [
            "0x00000000",
            "0xffffffff",
            "0xffffffff",
            "0xffffffff",
        ]:
            raise AssertionError(
            "local compute subtask must read the functional input base: %r"
                % active_base_by_subtask.get(0)
            )
        if active_base_by_subtask.get(1) != [
            "0xffffffff",
            "0xffffffff",
            "0x00020000",
            "0xffffffff",
        ]:
            raise AssertionError(
                "store subtask must bind the output base to STD base slot 2: %r"
                % active_base_by_subtask.get(1)
            )
        task_rows = plan.get("program_bin_rows", {}).get("task_rows", {})
        task0 = task_rows.get("task_conf:task0", {})
        if task0.get("active_subtask_indices") != [0, 1]:
            raise AssertionError(
                "functional probe must use compact subtask slots [0, 1]: %r"
                % task0.get("active_subtask_indices")
            )
        subtask_rows = plan.get("program_bin_rows", {}).get("subtask_rows", {})
        subtask0 = subtask_rows.get("subtask_conf:task0:vendor_subtask0", {})
        subtask1 = subtask_rows.get("subtask_conf:task0:vendor_subtask1", {})
        if subtask0.get("is_exe_end"):
            raise AssertionError("functional probe subtask0 must not be terminal")
        if not subtask1.get("is_exe_end"):
            raise AssertionError("functional probe subtask1 must be terminal")
        inst_report = plan.get("program_bin_rows", {}).get("inst_conf_report", {})
        if not inst_report.get("functional_encoding"):
            raise AssertionError("functional probe inst rows must be functional")

        control = json.loads(control_json.read_text())
        if control.get("case_id") != "functional_maximum_single_app":
            raise AssertionError("runtime control case id mismatch")
        if len(control.get("launches", [])) != 1:
            raise AssertionError("functional probe must remain single-launch")

        print("core_functional_probe_report_check=PASS")
        print("payload_root=%s" % payload_root)
        shutil.rmtree(payload_root, ignore_errors=True)


if __name__ == "__main__":
    main()
