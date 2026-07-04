#!/usr/bin/env python3
"""Build OpenFabric operator payloads for arch-13 validation.

This script is intentionally local-side only. It uses the current compiler
checkout to regenerate payloads under
``dfu3500_partner_validation/payloads/<case>/``. The remote arch-13 script
consumes those payload directories and does not need to import OpenFabric
Python code.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import shutil
import struct
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path


WORKFLOW_ROOT = Path(__file__).resolve().parent
COMPILER_ROOT = WORKFLOW_ROOT.parents[2]
SPM_IMAGE_SIZE_BYTES = 3 * 1024 * 1024
LOG10MAX_SHAPE = (64, 512)
LOG10MAX_INPUT_OFFSET_BYTES = 0x00000
LOG10MAX_OUTPUT_OFFSET_BYTES = 0x80000
LOG10MAX_DTYPE = "fp32"
FUNCTIONAL_MAXIMUM_SHAPE = (64, 512)
FUNCTIONAL_MAXIMUM_INPUT_OFFSET_BYTES = 0x00000
FUNCTIONAL_MAXIMUM_OUTPUT_OFFSET_BYTES = 0x80000
FUNCTIONAL_MAXIMUM_DTYPE = "fp32"
FUNCTIONAL_MAXIMUM_THRESHOLD = 3.5

if str(COMPILER_ROOT) not in sys.path:
    sys.path.insert(0, str(COMPILER_ROOT))

from gpdpu_compiler.core import ChipEnv, DFU3500_GEMM_REGIONS  # noqa: E402
from gpdpu_compiler.core.ops import (  # noqa: E402
    add_scalar,
    clamp_min,
    log10,
    maximum,
    maximum_scalar,
    mul_scalar,
    reduce_max,
    relu,
)
from gpdpu_compiler.placements import Replicate, Shard, TaskShard  # noqa: E402
from gpdpu_compiler.validation.dfu_binary_checks.runtime_ready_gate import (  # noqa: E402
    archive_runtime_ready_gate,
)
from runtime_control import (  # noqa: E402
    RuntimeControlPlan,
    RuntimeDmaTransfer,
    RuntimeKernelLaunch,
    RuntimeTensorRegion,
    write_runtime_control_artifacts,
)


@dataclass(frozen=True)
class PayloadCase:
    case_id: str
    app_name: str
    task_num: int
    vendor_inst_mode: str


PAYLOAD_CASES: tuple[PayloadCase, ...] = (
    PayloadCase(
        case_id="log10max_single_task",
        app_name="CASE/softmax_1",
        task_num=1,
        vendor_inst_mode="legacy_log10max_compat",
    ),
    PayloadCase(
        case_id="functional_maximum_single_app",
        app_name="CASE/softmax_1",
        task_num=1,
        vendor_inst_mode="legacy_template_compat",
    ),
)


def sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def copy_tree_contents(src: Path, dst: Path) -> None:
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    for child in src.iterdir():
        target = dst / child.name
        if child.is_dir():
            shutil.copytree(child, target)
        else:
            shutil.copy2(child, target)


def generate_gemm_template_fusion(output_dir: Path, vendor_inst_mode: str) -> None:
    env = ChipEnv("gemm_template_fusion_openfabric")
    lhs = env.load(
        env.sram_tensor_from_region("A", DFU3500_GEMM_REGIONS["A"]),
        placements=[Shard(0), Replicate()],
    )
    rhs = env.load(
        env.sram_tensor_from_region("B", DFU3500_GEMM_REGIONS["B"]),
        placements=[Replicate(), Shard(1)],
    )
    output = relu(lhs @ rhs)
    env.store(output, env.sram_tensor_from_region("Y", DFU3500_GEMM_REGIONS["C"]))
    env.generate(output_dir=output_dir, vendor_inst_mode=vendor_inst_mode)


def generate_log10max_single_task(output_dir: Path, vendor_inst_mode: str) -> None:
    """Generate the current log10max functional-validation payload.

    This is intentionally a narrow old-pipeline payload.  It borrows the
    softmax_1 RISC-V control-program shape while carrying its own runtime input
    image and source-side RISC-V build scaffolding.  The remote validation
    script should not need the vendor case directory to stage input data.
    """

    env = ChipEnv("log10max_single_task_openfabric")
    env.configure_task_axis(task_axis_size=1, physical_mesh_shape=(4, 4))
    mel_sram = env.sram_tensor(
        "mel_spec",
        shape=LOG10MAX_SHAPE,
        dtype=LOG10MAX_DTYPE,
        offset_bytes=LOG10MAX_INPUT_OFFSET_BYTES,
        role="input",
    )
    out_sram = env.sram_tensor(
        "Y",
        shape=LOG10MAX_SHAPE,
        dtype=LOG10MAX_DTYPE,
        offset_bytes=LOG10MAX_OUTPUT_OFFSET_BYTES,
        role="output",
    )
    mel = env.load(
        mel_sram,
        placements=[TaskShard("log10max_single_task"), Shard(0), Shard(1)],
    )
    log_spec = log10(clamp_min(mel, min_value=1.0e-10))
    global_max = reduce_max(log_spec)
    threshold = add_scalar(global_max, -8.0)
    clipped = maximum(log_spec, threshold)
    normalized = mul_scalar(add_scalar(clipped, 4.0), 0.25)
    env.store(normalized, out_sram)
    env.output("Y", out_sram)
    env.generate(output_dir=output_dir, vendor_inst_mode=vendor_inst_mode)


def generate_functional_maximum_single_app(
    output_dir: Path,
    vendor_inst_mode: str,
) -> None:
    """Generate the first current-core functional probe.

    The payload intentionally stays inside one semantic app and one task-axis
    shard.  It should exercise ordinary input visibility, one lane-wise local
    compute op, and ordinary store without reduce/broadcast/app-storage roles.
    Runtime execution remains gated until the target binder proves real
    instruction rows for this non-GEMM local compute path.
    """

    env = ChipEnv("functional_maximum_single_app_openfabric")
    env.configure_task_axis(task_axis_size=1, physical_mesh_shape=(4, 4))
    input_sram = env.sram_tensor(
        "X",
        shape=FUNCTIONAL_MAXIMUM_SHAPE,
        dtype=FUNCTIONAL_MAXIMUM_DTYPE,
        offset_bytes=FUNCTIONAL_MAXIMUM_INPUT_OFFSET_BYTES,
        role="input",
    )
    output_sram = env.sram_tensor(
        "Y",
        shape=FUNCTIONAL_MAXIMUM_SHAPE,
        dtype=FUNCTIONAL_MAXIMUM_DTYPE,
        offset_bytes=FUNCTIONAL_MAXIMUM_OUTPUT_OFFSET_BYTES,
        role="output",
    )
    x = env.load(
        input_sram,
        placements=[TaskShard("functional_maximum_single_app"), Shard(0), Shard(1)],
    )
    y = maximum_scalar(x, FUNCTIONAL_MAXIMUM_THRESHOLD)
    env.store(y, output_sram)
    env.output("Y", output_sram)
    env.generate(output_dir=output_dir, vendor_inst_mode=vendor_inst_mode)


def log10max_input_values() -> list[float]:
    rows, cols = LOG10MAX_SHAPE
    values: list[float] = []
    for row in range(rows):
        for col in range(cols):
            # Deterministic, positive, non-constant values.  Keep them in a
            # mild range so the first functional smoke is not dominated by
            # underflow/overflow behavior.
            value = 0.001 + ((row * 131 + col * 17 + 7) % 4096) / 512.0
            values.append(float(value))
    return values


def log10max_reference_values(input_values: list[float]) -> tuple[list[float], float]:
    log_values = [math.log10(max(value, 1.0e-10)) for value in input_values]
    global_max = max(log_values)
    threshold = global_max - 8.0
    output = [(max(value, threshold) + 4.0) * 0.25 for value in log_values]
    return output, global_max


def pack_fp32_values(values: list[float]) -> bytes:
    return b"".join(struct.pack("<f", value) for value in values)


def write_log10max_runtime_data(payload_dir: Path) -> None:
    runtime_dir = payload_dir / "runtime"
    reference_dir = payload_dir / "reference"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)

    input_values = log10max_input_values()
    reference_values, global_max = log10max_reference_values(input_values)

    spm_image = bytearray(SPM_IMAGE_SIZE_BYTES)
    input_blob = pack_fp32_values(input_values)
    input_start = LOG10MAX_INPUT_OFFSET_BYTES
    input_end = input_start + len(input_blob)
    if input_end > len(spm_image):
        raise ValueError("log10max input does not fit in SPM image")
    spm_image[input_start:input_end] = input_blob

    (runtime_dir / "input_data.bin").write_bytes(bytes(spm_image))
    (reference_dir / "mel_spec.fp32.bin").write_bytes(input_blob)
    (reference_dir / "Y.fp32.bin").write_bytes(pack_fp32_values(reference_values))
    (reference_dir / "reference.json").write_text(
        json.dumps(
            {
                "case_id": "log10max_single_task",
                "shape": list(LOG10MAX_SHAPE),
                "dtype": LOG10MAX_DTYPE,
                "spm_image_size_bytes": SPM_IMAGE_SIZE_BYTES,
                "input_offset_bytes": LOG10MAX_INPUT_OFFSET_BYTES,
                "output_offset_bytes": LOG10MAX_OUTPUT_OFFSET_BYTES,
                "global_max": global_max,
                "formula": "Y=(maximum(log10(clamp_min(X,1e-10)), max(log10(X))-8)+4)*0.25",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def log10max_runtime_control_plan(task_num: int) -> RuntimeControlPlan:
    tensor_nbytes = LOG10MAX_SHAPE[0] * LOG10MAX_SHAPE[1] * 4
    return RuntimeControlPlan(
        case_id="log10max_single_task",
        spm_image_size_bytes=SPM_IMAGE_SIZE_BYTES,
        tensors=(
            RuntimeTensorRegion(
                name="mel_spec",
                dtype=LOG10MAX_DTYPE,
                shape=LOG10MAX_SHAPE,
                byte_offset=LOG10MAX_INPUT_OFFSET_BYTES,
                byte_size=tensor_nbytes,
                direction="input",
                reference_path="reference/mel_spec.fp32.bin",
            ),
            RuntimeTensorRegion(
                name="Y",
                dtype=LOG10MAX_DTYPE,
                shape=LOG10MAX_SHAPE,
                byte_offset=LOG10MAX_OUTPUT_OFFSET_BYTES,
                byte_size=tensor_nbytes,
                direction="output",
                reference_path="reference/Y.fp32.bin",
            ),
        ),
        transfers=(
            RuntimeDmaTransfer(
                transfer_id="load_mel_spec",
                tensor_name="mel_spec",
                direction="ddr_to_spm",
                ddr_offset=LOG10MAX_INPUT_OFFSET_BYTES,
                spm_offset=LOG10MAX_INPUT_OFFSET_BYTES,
                byte_size=tensor_nbytes,
                phase="before_launch",
                group_id="input",
            ),
            RuntimeDmaTransfer(
                transfer_id="store_Y",
                tensor_name="Y",
                direction="spm_to_ddr",
                ddr_offset=LOG10MAX_OUTPUT_OFFSET_BYTES,
                spm_offset=LOG10MAX_OUTPUT_OFFSET_BYTES,
                byte_size=tensor_nbytes,
                phase="after_launch",
                group_id="output",
            ),
        ),
        launches=(
            RuntimeKernelLaunch(
                launch_id="kernel0",
                task_count=int(task_num),
                instance_count=1,
                micc_buffer=0,
                wait=True,
                input_transfer_group="input",
                output_transfer_group="output",
            ),
        ),
    )


def functional_maximum_input_values() -> list[float]:
    rows, cols = FUNCTIONAL_MAXIMUM_SHAPE
    values: list[float] = []
    for row in range(rows):
        for col in range(cols):
            value = ((row * 97 + col * 29 + 11) % 4096) / 512.0
            values.append(float(value))
    return values


def functional_maximum_reference_values(input_values: list[float]) -> list[float]:
    return [
        max(value, FUNCTIONAL_MAXIMUM_THRESHOLD)
        for value in input_values
    ]


def write_functional_maximum_runtime_data(payload_dir: Path) -> None:
    runtime_dir = payload_dir / "runtime"
    reference_dir = payload_dir / "reference"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    reference_dir.mkdir(parents=True, exist_ok=True)

    input_values = functional_maximum_input_values()
    reference_values = functional_maximum_reference_values(input_values)

    spm_image = bytearray(SPM_IMAGE_SIZE_BYTES)
    input_blob = pack_fp32_values(input_values)
    input_start = FUNCTIONAL_MAXIMUM_INPUT_OFFSET_BYTES
    input_end = input_start + len(input_blob)
    if input_end > len(spm_image):
        raise ValueError("functional maximum input does not fit in SPM image")
    spm_image[input_start:input_end] = input_blob

    (runtime_dir / "input_data.bin").write_bytes(bytes(spm_image))
    (reference_dir / "X.fp32.bin").write_bytes(input_blob)
    (reference_dir / "Y.fp32.bin").write_bytes(pack_fp32_values(reference_values))
    (reference_dir / "reference.json").write_text(
        json.dumps(
            {
                "case_id": "functional_maximum_single_app",
                "shape": list(FUNCTIONAL_MAXIMUM_SHAPE),
                "dtype": FUNCTIONAL_MAXIMUM_DTYPE,
                "spm_image_size_bytes": SPM_IMAGE_SIZE_BYTES,
                "input_offset_bytes": FUNCTIONAL_MAXIMUM_INPUT_OFFSET_BYTES,
                "output_offset_bytes": FUNCTIONAL_MAXIMUM_OUTPUT_OFFSET_BYTES,
                "threshold": FUNCTIONAL_MAXIMUM_THRESHOLD,
                "formula": "Y=maximum(X,threshold)",
            },
            indent=2,
            sort_keys=True,
        )
        + "\n"
    )


def functional_maximum_runtime_control_plan(task_num: int) -> RuntimeControlPlan:
    tensor_nbytes = FUNCTIONAL_MAXIMUM_SHAPE[0] * FUNCTIONAL_MAXIMUM_SHAPE[1] * 4
    return RuntimeControlPlan(
        case_id="functional_maximum_single_app",
        spm_image_size_bytes=SPM_IMAGE_SIZE_BYTES,
        tensors=(
            RuntimeTensorRegion(
                name="X",
                dtype=FUNCTIONAL_MAXIMUM_DTYPE,
                shape=FUNCTIONAL_MAXIMUM_SHAPE,
                byte_offset=FUNCTIONAL_MAXIMUM_INPUT_OFFSET_BYTES,
                byte_size=tensor_nbytes,
                direction="input",
                reference_path="reference/X.fp32.bin",
            ),
            RuntimeTensorRegion(
                name="Y",
                dtype=FUNCTIONAL_MAXIMUM_DTYPE,
                shape=FUNCTIONAL_MAXIMUM_SHAPE,
                byte_offset=FUNCTIONAL_MAXIMUM_OUTPUT_OFFSET_BYTES,
                byte_size=tensor_nbytes,
                direction="output",
                reference_path="reference/Y.fp32.bin",
            ),
        ),
        transfers=(
            RuntimeDmaTransfer(
                transfer_id="load_X",
                tensor_name="X",
                direction="ddr_to_spm",
                ddr_offset=FUNCTIONAL_MAXIMUM_INPUT_OFFSET_BYTES,
                spm_offset=FUNCTIONAL_MAXIMUM_INPUT_OFFSET_BYTES,
                byte_size=tensor_nbytes,
                phase="before_launch",
                group_id="input",
            ),
            RuntimeDmaTransfer(
                transfer_id="store_Y",
                tensor_name="Y",
                direction="spm_to_ddr",
                ddr_offset=FUNCTIONAL_MAXIMUM_OUTPUT_OFFSET_BYTES,
                spm_offset=FUNCTIONAL_MAXIMUM_OUTPUT_OFFSET_BYTES,
                byte_size=tensor_nbytes,
                phase="after_launch",
                group_id="output",
            ),
        ),
        launches=(
            RuntimeKernelLaunch(
                launch_id="kernel0",
                task_count=int(task_num),
                instance_count=1,
                micc_buffer=0,
                wait=True,
                input_transfer_group="input",
                output_transfer_group="output",
            ),
        ),
    )


def _template_unsupported_role_counts(plan: dict[str, object]) -> dict[str, int]:
    template_program = (
        plan.get("dfu3500_template_bound_program", {})
        if isinstance(plan.get("dfu3500_template_bound_program"), dict)
        else {}
    )
    unsupported = template_program.get("unsupported_micro_ops", {})
    role_counts: dict[str, int] = {}
    if not isinstance(unsupported, dict):
        return role_counts
    for record in unsupported.values():
        if not isinstance(record, dict):
            continue
        role = str(record.get("role", "unknown"))
        role_counts[role] = role_counts.get(role, 0) + 1
    return role_counts


def _runtime_control_gate_status(payload_dir: Path) -> dict[str, bool]:
    runtime_control_path = payload_dir / "runtime" / "riscv_src" / "riscv_control.json"
    testarm_path = payload_dir / "runtime" / "riscv_src" / "riscv" / "testarm.c"
    conf_path = payload_dir / "runtime" / "riscv_src" / "csv_generate" / "conf.h"
    input_data_path = payload_dir / "runtime" / "input_data.bin"
    required_assets_exist = all(
        path.exists()
        for path in (runtime_control_path, testarm_path, conf_path, input_data_path)
    )
    output_collection_supported = False
    reference_check_available = False
    if runtime_control_path.exists():
        runtime_control = json.loads(runtime_control_path.read_text())
        tensors = runtime_control.get("tensors", [])
        transfers = runtime_control.get("transfers", [])
        output_names = {
            str(tensor.get("name"))
            for tensor in tensors
            if isinstance(tensor, dict) and tensor.get("direction") == "output"
        }
        output_collection_supported = any(
            isinstance(transfer, dict)
            and transfer.get("direction") == "spm_to_ddr"
            and str(transfer.get("tensor_name")) in output_names
            for transfer in transfers
        )
        reference_check_available = bool(output_names)
        for tensor in tensors:
            if not isinstance(tensor, dict) or tensor.get("direction") != "output":
                continue
            reference_path = tensor.get("reference_path")
            if not isinstance(reference_path, str):
                reference_check_available = False
                break
            if not (payload_dir / reference_path).exists():
                reference_check_available = False
                break
    return {
        "runtime_control_assets_valid": required_assets_exist,
        "output_collection_supported": output_collection_supported,
        "reference_check_available": reference_check_available,
    }


def write_manifest(case: PayloadCase, payload_dir: Path) -> None:
    plan_path = payload_dir / "chip_program.json"
    program_status = "missing_chip_program"
    load_rows_functional = False
    local_compute_rows_functional = False
    store_rows_functional = False
    inst_rows_functional = False
    runtime_package_complete = False
    runtime_runnable = False
    runtime_expectation = "skip_functional_runtime"
    runtime_blocking_reasons: list[str] = []
    if plan_path.exists():
        plan = json.loads(plan_path.read_text())
        program_status = str(plan.get("status", "unknown"))
        bin_validation = (
            plan.get("program_bin_rows", {}).get("validation", {})
            if isinstance(plan.get("program_bin_rows"), dict)
            else {}
        )
        inst_report = (
            plan.get("program_bin_rows", {}).get("inst_conf_report", {})
            if isinstance(plan.get("program_bin_rows"), dict)
            else {}
        )
        component_validation = (
            plan.get("program_bin_components", {}).get("validation", {})
            if isinstance(plan.get("program_bin_components"), dict)
            else {}
        )
        template_validation = (
            plan.get("dfu3500_template_bound_program", {}).get("validation", {})
            if isinstance(plan.get("dfu3500_template_bound_program"), dict)
            else {}
        )
        complete_runtime_package = all(
            bool(component_validation.get(key))
            for key in (
                "component_bytes_emitted",
                "package_bytes_emitted",
                "instance_conf_info_file_ready",
                "tasks_conf_info_file_ready",
                "exeblock_conf_info_file_ready",
                "subtasks_conf_info_file_ready",
                "insts_file_ready",
                "cbuf_file_ready",
                "micc_file_ready",
            )
        )
        functional_encoding = bool(inst_report.get("functional_encoding"))
        all_templates_bound = bool(
            template_validation.get("all_micro_ops_have_template_bindings", True)
        )
        unsupported_role_counts = _template_unsupported_role_counts(plan)
        load_rows_functional = not any(
            unsupported_role_counts.get(role, 0)
            for role in ("broadcast_load", "load", "input_load")
        )
        local_compute_rows_functional = (
            unsupported_role_counts.get("local_compute", 0) == 0
        )
        store_rows_functional = not any(
            unsupported_role_counts.get(role, 0)
            for role in ("tile_store", "store", "output_store")
        )
        inst_rows_functional = functional_encoding and all_templates_bound
        runtime_package_complete = complete_runtime_package
        for role, count in sorted(unsupported_role_counts.items()):
            runtime_blocking_reasons.append(
                "unsupported_micro_op_role_%s_count_%d" % (role, count)
            )
        if not runtime_package_complete:
            runtime_blocking_reasons.append("runtime_package_incomplete")
        if not inst_rows_functional:
            runtime_blocking_reasons.append("inst_rows_not_functional")
        if not load_rows_functional:
            runtime_blocking_reasons.append("load_rows_not_functional")
        if not local_compute_rows_functional:
            runtime_blocking_reasons.append("local_compute_rows_not_functional")
        if not store_rows_functional:
            runtime_blocking_reasons.append("store_rows_not_functional")
        if not functional_encoding:
            runtime_blocking_reasons.append("instruction_rows_not_functional")
        if not all_templates_bound:
            runtime_blocking_reasons.append("template_bindings_incomplete")

    runtime_gates = _runtime_control_gate_status(payload_dir)
    for gate, value in sorted(runtime_gates.items()):
        if not value:
            runtime_blocking_reasons.append("%s_false" % gate)
    runtime_runnable = (
        inst_rows_functional
        and runtime_package_complete
        and runtime_gates["runtime_control_assets_valid"]
        and runtime_gates["output_collection_supported"]
        and runtime_gates["reference_check_available"]
    )
    if runtime_runnable:
        runtime_expectation = "run_functional_runtime"

    lines = [
        "case_id=%s" % case.case_id,
        "app_name=%s" % case.app_name,
        "task_num=%d" % case.task_num,
        "vendor_inst_mode=%s" % case.vendor_inst_mode,
        "program_status=%s" % program_status,
        "load_rows_functional=%d" % int(load_rows_functional),
        "local_compute_rows_functional=%d" % int(local_compute_rows_functional),
        "store_rows_functional=%d" % int(store_rows_functional),
        "inst_rows_functional=%d" % int(inst_rows_functional),
        "runtime_package_complete=%d" % int(runtime_package_complete),
        "runtime_control_assets_valid=%d"
        % int(runtime_gates["runtime_control_assets_valid"]),
        "output_collection_supported=%d"
        % int(runtime_gates["output_collection_supported"]),
        "reference_check_available=%d"
        % int(runtime_gates["reference_check_available"]),
        "runtime_runnable=%d" % int(runtime_runnable),
        "runtime_expectation=%s" % runtime_expectation,
    ]
    if case.case_id == "log10max_single_task":
        lines.extend(
            [
                "collective_strategy=ring_spmd_row_then_col",
                "customer_collective_label=spmd_ring_materialized_reduce",
                "direct_route_reduce_broadcast=deferred",
                "task_axis=1",
                "runtime_ordering_domain=single_task_group",
                "cross_task_one_app_ring=forbidden",
                "cross_task_visibility_claim=0",
            ]
        )
    for reason in sorted(set(runtime_blocking_reasons)):
        lines.append("runtime_blocking_reason=%s" % reason)

    runtime_control_path = payload_dir / "runtime" / "riscv_src" / "riscv_control.json"
    if runtime_control_path.exists():
        runtime_control = json.loads(runtime_control_path.read_text())
        for tensor in runtime_control.get("tensors", []):
            if tensor.get("direction") != "output":
                continue
            name = str(tensor["name"])
            shape = "x".join(str(dim) for dim in tensor.get("shape", []))
            lines.extend(
                [
                    "output_%s_dtype=%s" % (name, tensor.get("dtype", "")),
                    "output_%s_shape=%s" % (name, shape),
                    "output_%s_spm_offset=%s" % (name, tensor.get("byte_offset", "")),
                    "output_%s_byte_size=%s" % (name, tensor.get("byte_size", "")),
                    "output_%s_reference=%s" % (name, tensor.get("reference_path", "")),
                ]
            )
    for rel in (
        "result/cbuf_file.bin",
        "result/micc_file.bin",
        "config/cbuf_file.bin",
        "config/micc_file.bin",
        "simulator_bin/insts_file.bin",
        "simulator_bin/exeblock_conf_info_file.bin",
        "simulator_bin/instance_conf_info_file.bin",
        "simulator_bin/tasks_conf_info_file.bin",
        "simulator_bin/subtasks_conf_info_file.bin",
        "runtime/input_data.bin",
        "runtime/riscv_program",
        "runtime/riscv_src/README.txt",
        "runtime/riscv_src/riscv_control.json",
        "runtime/riscv_src/riscv/testarm.c",
        "runtime/riscv_src/csv_generate/conf.h",
        "runtime/riscv_src/spm_data/data.h",
        "reference/X.fp32.bin",
        "reference/mel_spec.fp32.bin",
        "reference/Y.fp32.bin",
        "reference/reference.json",
    ):
        path = payload_dir / rel
        if path.exists():
            lines.append("%s_size=%d" % (rel.replace("/", "_"), path.stat().st_size))
            lines.append("%s_sha256=%s" % (rel.replace("/", "_"), sha256_file(path)))
    (payload_dir / "MANIFEST.txt").write_text("\n".join(lines) + "\n")


def write_payload_indexes(payload_root: Path) -> None:
    sha_lines: list[str] = []
    size_lines: list[str] = []
    for path in sorted(p for p in payload_root.rglob("*") if p.is_file()):
        rel = path.relative_to(payload_root)
        sha_lines.append("%s  %s" % (sha256_file(path), rel))
        size_lines.append("%s %d" % (rel, path.stat().st_size))
    (WORKFLOW_ROOT / "sha256.txt").write_text("\n".join(sha_lines) + "\n")
    (WORKFLOW_ROOT / "sizes.txt").write_text("\n".join(size_lines) + "\n")


def parse_manifest(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text().splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def validate_built_payload(payload_dir: Path) -> None:
    archive_runtime_ready_gate(payload_dir, require_pass=False)
    manifest = parse_manifest(payload_dir / "MANIFEST.txt")
    if manifest.get("case_id") != "log10max_single_task":
        return
    report_path = payload_dir / "validation" / "runtime_ready.json"
    report = json.loads(report_path.read_text())
    report["operator_metadata"] = {
        "operator": "log10max",
        "collective_strategy": "ring_spmd_row_then_col",
        "customer_collective_label": "spmd_ring_materialized_reduce",
        "direct_route_reduce_broadcast": "deferred",
        "task_axis": 1,
        "runtime_ordering_domain": "single_task_group",
        "cross_task_one_app_ring": "forbidden",
        "cross_task_visibility_claim": False,
    }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")


def build_case(case: PayloadCase, payload_root: Path) -> None:
    payload_dir = payload_root / case.case_id
    with tempfile.TemporaryDirectory(prefix="openfabric_payload_") as tmp:
        generated = Path(tmp) / case.case_id
        if case.case_id == "gemm_template_fusion":
            generate_gemm_template_fusion(generated, case.vendor_inst_mode)
        elif case.case_id == "log10max_single_task":
            generate_log10max_single_task(generated, case.vendor_inst_mode)
        elif case.case_id == "functional_maximum_single_app":
            generate_functional_maximum_single_app(generated, case.vendor_inst_mode)
        else:
            raise ValueError("unknown payload case: %s" % case.case_id)

        if payload_dir.exists():
            shutil.rmtree(payload_dir)
        payload_dir.mkdir(parents=True)
        copy_tree_contents(generated / "config", payload_dir / "config")
        copy_tree_contents(generated / "simulator_bin", payload_dir / "simulator_bin")
        (payload_dir / "result").mkdir()
        shutil.copy2(
            generated / "config" / "cbuf_file.bin",
            payload_dir / "result" / "cbuf_file.bin",
        )
        shutil.copy2(
            generated / "config" / "micc_file.bin",
            payload_dir / "result" / "micc_file.bin",
        )
        for plan_file in sorted(generated.glob("*.json")):
            shutil.copy2(plan_file, payload_dir / plan_file.name)
        if case.case_id == "log10max_single_task":
            write_log10max_runtime_data(payload_dir)
            write_runtime_control_artifacts(
                log10max_runtime_control_plan(task_num=case.task_num),
                payload_dir,
            )
        elif case.case_id == "functional_maximum_single_app":
            write_functional_maximum_runtime_data(payload_dir)
            write_runtime_control_artifacts(
                functional_maximum_runtime_control_plan(task_num=case.task_num),
                payload_dir,
            )
        write_manifest(case, payload_dir)
        validate_built_payload(payload_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--payload-root",
        type=Path,
        default=WORKFLOW_ROOT / "payloads",
        help="directory that receives payload case folders",
    )
    parser.add_argument(
        "--case",
        choices=[case.case_id for case in PAYLOAD_CASES],
        action="append",
        help="case to build; may be repeated; default builds all cases",
    )
    args = parser.parse_args()

    selected = set(args.case or [case.case_id for case in PAYLOAD_CASES])
    if args.case is None and args.payload_root.exists():
        shutil.rmtree(args.payload_root)
    args.payload_root.mkdir(parents=True, exist_ok=True)
    for case in PAYLOAD_CASES:
        if case.case_id in selected:
            print("building payload:", case.case_id)
            build_case(case, args.payload_root)
    write_payload_indexes(args.payload_root)
    print("payload_root=%s" % args.payload_root)


if __name__ == "__main__":
    main()
