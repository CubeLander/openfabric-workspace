"""Generate RISC-V runtime-control artifacts for partner validation payloads.

This module is local-side only.  It creates payload-local RISC-V source and
reviewable JSON metadata.  The generated RISC-V program is a guest/control-plane
program: it stages CBUF/MICC, moves SPM data, starts the kernel, waits, and
finishes the app.  It must not encode device/PE instructions.
"""

from __future__ import annotations

import json
import shutil
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal


REPO_ROOT = Path(__file__).resolve().parents[4]
LOCAL_RISC_ROOT = REPO_ROOT / "simict3500final" / "gpdpu" / "users" / "risc_nn_riscv"


TensorDirection = Literal["input", "output", "scratch", "reference"]
DmaDirection = Literal["ddr_to_spm", "spm_to_ddr"]
TransferPhase = Literal["before_launch", "after_launch", "custom"]


@dataclass(frozen=True)
class RuntimeTensorRegion:
    name: str
    dtype: str
    shape: tuple[int, ...]
    byte_offset: int
    byte_size: int
    direction: TensorDirection
    reference_path: str | None = None


@dataclass(frozen=True)
class RuntimeDmaTransfer:
    transfer_id: str
    tensor_name: str
    direction: DmaDirection
    ddr_offset: int
    spm_offset: int
    byte_size: int
    phase: TransferPhase = "custom"
    group_id: str = "default"
    task_id: int | None = None
    instance_id: int | None = None


@dataclass(frozen=True)
class RuntimeKernelLaunch:
    launch_id: str
    task_count: int
    instance_count: int
    micc_buffer: int = 0
    wait: bool = True
    input_transfer_group: str = "input"
    output_transfer_group: str = "output"


@dataclass(frozen=True)
class RuntimeControlPlan:
    case_id: str
    spm_image_size_bytes: int
    tensors: tuple[RuntimeTensorRegion, ...]
    transfers: tuple[RuntimeDmaTransfer, ...]
    launches: tuple[RuntimeKernelLaunch, ...]
    finish_app: bool = True


def validate_runtime_control_plan(plan: RuntimeControlPlan) -> None:
    tensor_names = {tensor.name for tensor in plan.tensors}
    if len(tensor_names) != len(plan.tensors):
        raise ValueError("RuntimeControlPlan tensor names must be unique")
    if len(plan.launches) != 1:
        raise NotImplementedError("generated RISC-V control currently supports exactly one launch")
    for tensor in plan.tensors:
        if tensor.byte_offset < 0 or tensor.byte_size <= 0:
            raise ValueError("invalid tensor region: %s" % tensor.name)
        if tensor.byte_offset + tensor.byte_size > plan.spm_image_size_bytes:
            raise ValueError("tensor region does not fit SPM image: %s" % tensor.name)
    for transfer in plan.transfers:
        if transfer.tensor_name not in tensor_names:
            raise ValueError("DMA transfer references unknown tensor: %s" % transfer.tensor_name)
        if transfer.phase == "custom":
            raise NotImplementedError("custom transfer phase is not supported by generated RISC-V control")
        if transfer.byte_size <= 0:
            raise ValueError("invalid DMA transfer byte size: %s" % transfer.transfer_id)


def runtime_control_dict(plan: RuntimeControlPlan) -> dict[str, object]:
    return asdict(plan)


def write_riscv_control_json(plan: RuntimeControlPlan, src_root: Path) -> None:
    validate_runtime_control_plan(plan)
    src_root.mkdir(parents=True, exist_ok=True)
    (src_root / "riscv_control.json").write_text(
        json.dumps(runtime_control_dict(plan), indent=2, sort_keys=True) + "\n"
    )


def _first_tensor(plan: RuntimeControlPlan, direction: TensorDirection) -> RuntimeTensorRegion:
    for tensor in plan.tensors:
        if tensor.direction == direction:
            return tensor
    raise ValueError("missing %s tensor region" % direction)


def write_conf_h_from_runtime_control_plan(plan: RuntimeControlPlan, src_root: Path) -> None:
    validate_runtime_control_plan(plan)
    csv_dir = src_root / "csv_generate"
    spm_dir = src_root / "spm_data"
    csv_dir.mkdir(parents=True, exist_ok=True)
    spm_dir.mkdir(parents=True, exist_ok=True)

    input_tensor = _first_tensor(plan, "input")
    output_tensor = _first_tensor(plan, "output")
    launch = plan.launches[0]
    if input_tensor.dtype != "fp32" or output_tensor.dtype != "fp32":
        raise NotImplementedError("first conf.h projection only supports fp32 tensors")
    input_elements = input_tensor.byte_size // 4
    output_elements = output_tensor.byte_size // 4
    batch = input_tensor.shape[0] if input_tensor.shape else 1

    conf_h = f"""#define softmax0_input0_SIZE {input_elements}
#define softmax0_output0_SIZE {output_elements}

#define softmax0_input0_SIZE_app {input_elements}
#define softmax0_output0_SIZE_app {output_elements}
#define rope0_output0_SIZE_app 0
#define rmsnorm_output_app 0
static int rmsnorm_output_dim[3] = {{0,0,0}};

#define MEM_softmax0_input0_ADDR 0
#define MEM_softmax0_output0_ADDR 0

#define SPM_softmax0_input0_ADDR {input_tensor.byte_offset}
#define SPM_softmax0_output0_ADDR {output_tensor.byte_offset}
#define SPM_SUM_ADDR 32768
#define softmax_batch {batch}

#define LARGE_SCALE 0
#define INPUT_BATCH_SIZE 1
#define APP_NUM 1
#define SUBTASK_NUM 2
#define TASK_NUM {int(launch.task_count)}
#define PE_NUM_BASE 1
static int input_group_base[1] = {{256}};
static int output_group_base[1] = {{256}};
static int PE[16] = {{0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15}};
static int PER_TASK_PE_NUMBER[4] = {{16, 16, 16, 16}};
static int PER_TASK_INSTANCE_NUMBER[4] = {{1, 1, 1, 1}};
static int task_order[4] = {{0, 1, 2, 3}};
static int PER_INSTANCE_STATEMENT_NUMBER[1] = {{{batch}}};

#ifdef RTL_SIM
static uint64_t softmax0_input0_ddrStartAddr[1] = {{
{input_tensor.byte_offset}, }};
#else
static unsigned softmax0_input0_ddrStartAddr[1] = {{
{input_tensor.byte_offset}, }};
#endif
static unsigned softmax0_input0_spmStartAddr[1] = {{
{input_tensor.byte_offset}, }};
static unsigned softmax0_input0_x_Slice[1] = {{
{input_tensor.byte_size}, }};
static unsigned softmax0_input0_y_Slice[1] = {{
1, }};
static unsigned softmax0_input0_x_Full[1] = {{
{input_tensor.byte_size}, }};
static unsigned softmax0_input0_regular_mark[1] = {{
0, }};
static unsigned softmax0_input0_regular_conf[1][4] = {{
{{0, 0, 0, 0}},
}};
#ifdef RTL_SIM
static uint64_t softmax0_output0_ddrStartAddr[2] = {{
0, {output_tensor.byte_offset}, }};
#else
static unsigned softmax0_output0_ddrStartAddr[2] = {{
0, {output_tensor.byte_offset}, }};
#endif
static unsigned softmax0_output0_spmStartAddr[2] = {{
0, {output_tensor.byte_offset}, }};
static unsigned softmax0_output0_x_Slice[2] = {{
0, {output_tensor.byte_size}, }};
static unsigned softmax0_output0_y_Slice[2] = {{
0, 1, }};
static unsigned softmax0_output0_x_Full[2] = {{
0, {output_tensor.byte_size}, }};
static unsigned softmax0_output0_regular_mark[2] = {{
0, 0, }};
static unsigned softmax0_output0_regular_conf[2][4] = {{
{{0, 0, 0, 0}},
{{0, 0, 0, 0}},
}};
"""
    (csv_dir / "conf.h").write_text(conf_h)
    (spm_dir / "data.h").write_text("\n")


def _transfer_c_statement(transfer: RuntimeDmaTransfer) -> str:
    if transfer.direction == "ddr_to_spm":
        ddr_base = "SPM_DDR_ADDR"
        trans_direc = 2
    elif transfer.direction == "spm_to_ddr":
        ddr_base = "SPM_RST_DDR_ADDR"
        trans_direc = 0
    else:
        raise ValueError("unknown DMA direction: %s" % transfer.direction)
    return (
        "    dma_transfer_simple((unsigned)(%s + 0x%x), "
        "(unsigned)0x%x, (unsigned)0x%x, (unsigned)%d);"
        % (ddr_base, transfer.ddr_offset, transfer.spm_offset, transfer.byte_size, trans_direc)
    )


def write_riscv_control_source(plan: RuntimeControlPlan, src_root: Path) -> None:
    validate_runtime_control_plan(plan)
    riscv_dir = src_root / "riscv"
    riscv_dir.mkdir(parents=True, exist_ok=True)
    launch = plan.launches[0]
    before = [transfer for transfer in plan.transfers if transfer.phase == "before_launch"]
    after = [transfer for transfer in plan.transfers if transfer.phase == "after_launch"]
    lines: list[str] = [
        "#include \"DpuAPI.h\"",
        "#include <stdio.h>",
        "#include \"../csv_generate/conf.h\"",
        "",
        "static void wait_dma(int flag)",
        "{",
        "    while (!DPU_DMATransferFinish(flag));",
        "}",
        "",
        "static void dma_transfer_simple(unsigned ddr_addr, unsigned spm_addr, unsigned byte_size, unsigned trans_direc)",
        "{",
        "    DPU_SpmTransfer((void*)ddr_addr, 0, (void*)spm_addr, 0,",
        "                    byte_size, 1, byte_size, trans_direc, 0, 0);",
        "    wait_dma(0);",
        "}",
        "",
        "int main(void)",
        "{",
        '    printf("openfabric generated riscv control: %s\\n");' % plan.case_id,
        "    DPU_CbufTransfer((void*)CBUF_DDR_ADDR);",
        "    wait_dma(2);",
        "    DPU_MiccTransfer((void*)MICC_DDR_ADDR);",
        "    wait_dma(0);",
        "",
        "    /* before_launch DMA transfers */",
    ]
    lines.extend(_transfer_c_statement(transfer) for transfer in before)
    lines.extend(
        [
            "",
            "    DPU_Kernel_Start(1, %d, (void*)0, 0, %d, 0);"
            % (launch.task_count, launch.micc_buffer),
        ]
    )
    if launch.wait:
        lines.append("    while (!DPU_Kernel_Wait_Finish(%d));" % launch.micc_buffer)
    lines.append("")
    lines.append("    /* after_launch DMA transfers */")
    lines.extend(_transfer_c_statement(transfer) for transfer in after)
    if plan.finish_app:
        lines.append("    DPU_App_Finish();")
    lines.extend(
        [
            '    printf("openfabric generated riscv control done\\n");',
            "    return 0;",
            "}",
            "",
        ]
    )
    (riscv_dir / "testarm.c").write_text("\n".join(lines))
    (riscv_dir / "makefile").write_text(
        "\n".join(
            [
                "CC ?= riscv64-unknown-elf-gcc",
                "OBJDUMP ?= riscv64-unknown-elf-objdump",
                "COMMON_SRC ?= $(SIMICT_ROOT)/gpdpu/users/risc_nn_riscv/common/src",
                "CFLAGS ?= -mabi=lp64d -march=rv64imafdc -static -std=gnu99 -Wno-error=int-conversion",
                "API_SOURCE := ../dpuapi/DpuAPI.c",
                "all: riscv",
                "riscv: testarm.c $(API_SOURCE)",
                "\t$(CC) $(CFLAGS) -o $@ testarm.c $(API_SOURCE) -I../dpuapi -I$(COMMON_SRC)",
                "\t$(OBJDUMP) -D $@ > riscv.lst || true",
                "clean:",
                "\trm -f riscv riscv.lst",
                "",
            ]
        )
    )


def write_payload_local_dpuapi(src_root: Path) -> None:
    """Copy the local DpuAPI source into the payload runtime source tree."""
    dpuapi_src = LOCAL_RISC_ROOT / "dpuapi"
    dpuapi_dst = src_root / "dpuapi"
    dpuapi_dst.mkdir(parents=True, exist_ok=True)
    for name in ("DpuAPI.c", "DpuAPI.h"):
        source = dpuapi_src / name
        if not source.exists():
            raise FileNotFoundError("missing local DpuAPI source: %s" % source)
        shutil.copy2(source, dpuapi_dst / name)


def write_runtime_control_artifacts(plan: RuntimeControlPlan, payload_dir: Path) -> None:
    src_root = payload_dir / "runtime" / "riscv_src"
    write_riscv_control_json(plan, src_root)
    write_conf_h_from_runtime_control_plan(plan, src_root)
    write_riscv_control_source(plan, src_root)
    write_payload_local_dpuapi(src_root)
    (src_root / "README.txt").write_text(
        "Generated RISC-V control source for partner validation. The payload "
        "carries dpuapi/DpuAPI.c and dpuapi/DpuAPI.h locally; build on arch-13 "
        "with the validation script or runtime/riscv_src/riscv/makefile, using "
        "common headers from SIMICT_ROOT.\n"
    )
