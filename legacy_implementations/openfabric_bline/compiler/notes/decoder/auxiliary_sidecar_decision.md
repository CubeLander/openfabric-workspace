# Auxiliary Sidecar Decision

Date: 2026-06-21

Status: closed unless new runtime consumer evidence appears

## Decision

OpenFabric should not treat these files as runtime truth:

```text
data_inst_replace.bin
instEnable.bin
taskEnable.bin
```

They are vendor compatibility / RTL collateral in the currently audited flow.
They may be copied when present, but they must not drive `RUNTIME_READY`, active
task selection, instruction readiness, CBUF/MICC size checks, or graph legality.

## Evidence

`Print_Task_Group::task_inst_enable_print()` writes all three files:

```text
rtl_bin/instEnable.bin        -> "1\n"
rtl_bin/taskEnable.bin        -> reversed-looking 4-char task mask
simulator_bin/data_inst_replace.bin -> "1 1\n"
```

Source:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/task_print.cpp:801
```

Packaging appends `data_inst_replace.bin` separately from CBUF/MICC:

```text
simulator_bin/insts_file.bin              -> cbuf_file.bin
simulator_bin/exeblock_conf_info_file.bin -> cbuf_file.bin
simulator_bin/instance_conf_info_file.bin -> cbuf_file.bin
simulator_bin/tasks_conf_info_file.bin    -> micc_file.bin
simulator_bin/subtasks_conf_info_file.bin -> micc_file.bin
simulator_bin/data_inst_replace.bin       -> data_inst_replace.bin
```

Sources:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/app_build/run_mtr.sh:68
simict3500final/gpdpu/users/risc_nn_riscv/testcase/workflow/scripts/build_package.sh:276
```

Partner runtime staging copies `result/data_inst_replace.bin` into `config/`
only if it exists:

```text
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/validate_on_arch13.sh:267
```

The real runtime task-enable source is RISC-V control:

```text
DPU_Kernel_Start(task_num)
  task_num=1 -> task_enable=1
  task_num=2 -> task_enable=3
  task_num=3 -> task_enable=7
  task_num=4 -> task_enable=15
  writes MICC_BUF{0,1}_TASK
```

Source:

```text
simict3500final/gpdpu/users/risc_nn_riscv/dpuapi/DpuAPI.c:351
```

## Validation Policy

Do:

```text
- allow payloads to include result/data_inst_replace.bin as optional compatibility collateral
- copy result/data_inst_replace.bin during partner staging if present
- report sidecar presence in manifests or diagnostics if useful
```

Do not:

```text
- infer task_count from taskEnable.bin
- infer active MICC task rows from taskEnable.bin
- infer instruction readiness from instEnable.bin
- include data_inst_replace.bin in CBUF/MICC byte sizes or hashes
- fail RUNTIME_READY merely because these sidecars are absent
```

## Reopen Criteria

Reopen this topic only if one of these appears:

```text
1. source-level SimICT/runtime consumer for config/data_inst_replace.bin,
2. vendor-provided runtime ABI statement for instEnable/taskEnable,
3. remote evidence proving absence/presence changes current mainline runtime behavior,
4. a future RTL validation workflow that explicitly consumes rtl_bin collateral.
```
