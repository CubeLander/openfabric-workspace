# Runtime Control Source Audit

Date: 2026-06-20

Status: original-materials + source audit card

This note anchors the runtime-control facts that OpenFabric must preserve when
it generates validation bundles or future RISC-V control programs.  It exists so
we do not infer launch/DMA semantics from remote logs alone.

## Source Materials

Original materials:

```text
tmp/华科算子库编写/4、DFU3500-汇编编程介绍.docx
tmp/华科算子库编写/5、DFU3500-模拟器使用方法.docx
tmp/华科算子库编写/6、DFU3500-DMA数据传输介绍.docx
```

Vendor implementation:

```text
simict3500final/gpdpu/users/risc_nn_riscv/dpuapi/DpuAPI.h
simict3500final/gpdpu/users/risc_nn_riscv/dpuapi/DpuAPI.c
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/CASE/softmax_1/riscv/testarm.c
```

OpenFabric owner:

```text
RuntimeControlPlan / generated RISC-V control assets
compiler/gpdpu_compiler/validation/dfu3500_partner_validation
```

## Kernel Launch Contract

The assembly-programming document describes `DPU_Kernel_Start` as the runtime
entry that starts DFU execution.  The source prototype is:

```c
int DPU_Kernel_Start(int inst_reload, int task_num, void* instance_base,
                     unsigned instance_base_noneed, int buf_num, int time_type);
```

`DpuAPI.c` operationalizes this as MICC register programming:

```text
task_num=1 -> task_enable=1
task_num=2 -> task_enable=3
task_num=3 -> task_enable=7
task_num=4 -> task_enable=15

MICC_INSTANCE_BASE        <- instance_base
MICC_INSTANCE_BASE_NONEED <- instance_base_noneed
MICC_BUF{0,1}_INST        <- inst_reload
MICC_BUF{0,1}_TASK        <- task_enable
MICC_BUF{0,1}_START       <- 1
```

Reference source:

```text
simict3500final/gpdpu/users/risc_nn_riscv/dpuapi/DpuAPI.h:95
simict3500final/gpdpu/users/risc_nn_riscv/dpuapi/DpuAPI.c:351
```

### Compiler implications

`task_num` is not cosmetic.  It becomes a task-enable bitmask.  A payload that
claims one task in its package but starts four tasks in RISC-V control is asking
MICC to wait for work that does not exist.

Required OpenFabric check:

```text
RuntimeControlPlan.task_num == VendorComponentPlan.active_task_count
RuntimeControlPlan.task_num <= legacy_profile.max_task_rows_per_package
```

This exact mismatch caused an A-line hang; it now needs a guard, not tribal
memory.

## `instance_base_noneed`

The assembly-programming document says `instance_base_noneed` corresponds to
MICC's `micc_base_addr_noneed` register.  It is indexed per subtask/base slot:

```text
micc_base_addr_noneed[(subtask_id << 2) + i], i in {0,1,2,3}
```

Interpretation for OpenFabric:

```text
instance_base_noneed bit = 0:
  address uses dynamic `MICC_INSTANCE_BASE` plus instance table/base slot.

instance_base_noneed bit = 1:
  subtask/base slot can use the global SPM address space form described by the
  vendor runtime interface.
```

This is not yet fully operationalized in OpenFabric.  Until it is, generated
functional payloads should keep `instance_base_noneed=0` unless a specific case
is source-backed and runtime-tested.

Required future owner:

```text
RuntimeControlPlan.instance_base_noneed_mask
MemoryAccessPlan.base_slot_policy
```

## CBUF / MICC Loading Contract

`DPU_CbufTransfer` and `DPU_MiccTransfer` are not CPU-side `memcpy`.  They write
DMA registers and start the DMA engine.

CBUF transfer uses two DMA channels:

```text
channel 0: DDR -> CBUF_INST_BASE, size 0x1298500
channel 1: DDR -> CBUF_BLCK_BASE, size 0x141500
```

MICC transfer uses channel 0:

```text
DDR -> MICC_BASE_ADDR, size 0x480
```

Reference source:

```text
simict3500final/gpdpu/users/risc_nn_riscv/dpuapi/DpuAPI.c:236
simict3500final/gpdpu/users/risc_nn_riscv/dpuapi/DpuAPI.c:278
```

### Compiler implications

OpenFabric's runtime bundle must treat CBUF/MICC payloads as simulator/runtime
DDR payloads that the RISC-V control program asks DMA to load.  RISC-V control
source should not regenerate or inspect device instructions.

Current unresolved point:

```text
DPU_CbufTransfer channel 1 uses the same MemAddr in source code.
```

This likely depends on simulator-side payload layout.  Do not change CBUF
component packing based only on this API without also checking the simulator
bundle staging behavior.

## Softmax Runtime Sequence Evidence

`softmax_1/riscv/testarm.c` gives a concrete sequence:

```text
1. DPU_CbufTransfer
2. wait DPU_DMATransferFinish(2)
3. DPU_MiccTransfer
4. wait DPU_DMATransferFinish(0)
5. DMA input DDR -> SPM
6. DPU_Kernel_Start
7. DPU_Kernel_Wait_Finish for previous/current app buffer
8. DMA output SPM -> DDR
```

Reference source:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/CASE/softmax_1/riscv/testarm.c:296
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/CASE/softmax_1/riscv/testarm.c:316
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/CASE/softmax_1/riscv/testarm.c:349
```

## RuntimeControlPlan Required Fields

A generated validation bundle needs an explicit control plan with at least:

```text
cbuf_payload_ddr_addr
micc_payload_ddr_addr
input_transfers[]:
  ddr_addr
  spm_addr
  x_slice / y_slice / x_full
  direction
  regular_mode fields
kernel_launches[]:
  inst_reload
  task_num
  instance_base
  instance_base_noneed
  buf_num
  time_type
output_transfers[]:
  ddr_addr
  spm_addr
  x_slice / y_slice / x_full
  direction
```

It should generate `testarm.c`/`conf.h` as projections, not treat those files as
primary truth.

## Current Status

```text
Extracted:
  DPU_Kernel_Start prototype and DpuAPI implementation are identified.

Absorbed:
  Runtime/control split is documented in vendor_reference/runtime_evidence.

Operationalized:
  Partial.  A-line has guards around stale payload/task mismatch, but B-line
  still needs a typed RuntimeControlPlan before generated packages are trusted.

Runtime-proven:
  A-line maximum probe ran after task count and package metadata were corrected.
```

## Guardrails

Do not ship a runnable payload unless:

```text
1. RISC-V task_num matches active MICC task rows.
2. instance_base and instance_base_noneed are explicit in plan metadata.
3. CBUF/MICC payloads are staged at addresses used by DPU_CbufTransfer and
   DPU_MiccTransfer.
4. Input/output DMA regions match declared SRAM/SPM tensor regions.
5. Runtime control source is generated from RuntimeControlPlan, not patched from
   a random vendor case without manifest evidence.
```
