#!/usr/bin/env python3
"""Check generated RISC-V runtime-control payload artifacts."""

from __future__ import annotations

import json
import shutil
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
COMPILER_ROOT = REPO_ROOT / "compiler"
VALIDATION_ROOT = COMPILER_ROOT / "gpdpu_compiler" / "validation" / "dfu3500_partner_validation"
for path in (str(COMPILER_ROOT), str(VALIDATION_ROOT)):
    if path not in sys.path:
        sys.path.insert(0, path)

import build_payloads  # noqa: E402


def assert_ordered(text: str, needles: tuple[str, ...]) -> None:
    cursor = -1
    for needle in needles:
        next_cursor = text.find(needle, cursor + 1)
        if next_cursor < 0:
            raise AssertionError("missing expected text: %s" % needle)
        cursor = next_cursor


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="openfabric_runtime_control_check_") as tmp:
        payload_root = Path(tmp) / "payloads"
        case = build_payloads.PAYLOAD_CASES[0]
        if case.case_id != "log10max_single_task":
            raise AssertionError("expected default validation case to be log10max_single_task")
        build_payloads.build_case(case, payload_root)
        payload = payload_root / case.case_id

        control_json = payload / "runtime" / "riscv_src" / "riscv_control.json"
        testarm = payload / "runtime" / "riscv_src" / "riscv" / "testarm.c"
        conf_h = payload / "runtime" / "riscv_src" / "csv_generate" / "conf.h"
        manifest = payload / "MANIFEST.txt"
        for required in (control_json, testarm, conf_h, manifest):
            if not required.exists():
                raise AssertionError("missing generated artifact: %s" % required)

        control = json.loads(control_json.read_text())
        if control["case_id"] != "log10max_single_task":
            raise AssertionError("unexpected case_id in runtime control")
        if len(control["launches"]) != 1:
            raise AssertionError("first generated control plan must be single-launch")
        tensors = {tensor["name"]: tensor for tensor in control["tensors"]}
        if tensors["Y"]["byte_offset"] != build_payloads.LOG10MAX_OUTPUT_OFFSET_BYTES:
            raise AssertionError("output tensor offset mismatch")

        source = testarm.read_text()
        if "softmax0_input0_ddrStartAddr" in source:
            raise AssertionError("generated testarm.c still depends on vendor conf arrays")
        if "CASE/softmax_1" in source:
            raise AssertionError("generated testarm.c references vendor case path")
        assert_ordered(
            source,
            (
                "DPU_CbufTransfer",
                "DPU_MiccTransfer",
                "before_launch DMA transfers",
                "DPU_Kernel_Start",
                "DPU_Kernel_Wait_Finish",
                "after_launch DMA transfers",
                "DPU_App_Finish",
            ),
        )

        manifest_text = manifest.read_text()
        for expected in (
            "runtime_riscv_src_riscv_control.json_size=",
            "runtime_riscv_src_riscv_testarm.c_size=",
            "output_Y_dtype=fp32",
            "output_Y_shape=64x512",
            "output_Y_spm_offset=%d" % build_payloads.LOG10MAX_OUTPUT_OFFSET_BYTES,
            "output_Y_reference=reference/Y.fp32.bin",
        ):
            if expected not in manifest_text:
                raise AssertionError("missing manifest line: %s" % expected)

        # Ensure the validation builder source no longer names the copied vendor
        # RISC-V template hook.  Old-payload fallback belongs to arch-13 staging,
        # not generated payload construction.
        builder_source = Path(build_payloads.__file__).read_text()
        forbidden = (
            "LOCAL_RISCV_TEMPLATE",
            "softmax_1/riscv/testarm.c",
            "shutil.copy2(LOCAL_RISCV_TEMPLATE",
        )
        for needle in forbidden:
            if needle in builder_source:
                raise AssertionError("builder still references vendor testarm template: %s" % needle)

        print("runtime_control_generation_check=PASS")
        print("payload_root=%s" % payload_root)
        # Keep temp tree alive only for the duration of assertions; explicitly
        # remove it to make intent obvious even if TemporaryDirectory changes.
        shutil.rmtree(payload_root, ignore_errors=True)


if __name__ == "__main__":
    main()
