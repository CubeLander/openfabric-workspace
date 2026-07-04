# Runtime Package Build Flow

This note records what we currently understand about the open part of the
operator build flow. The goal is to rebuild the files consumed by the closed
runtime without invoking legacy case-level shell entrypoints.

The verified command is:

```sh
make package CASE=application/CASE/softmax_1
```

The command produces:

```text
runtime_packages/<case>/
  config/
    cbuf_file.bin
    micc_file.bin
    input_data.bin
    riscv_program
  build.log
  metadata.json
  source_manifest.txt
```

The closed runtime only needs the four files under `config/`.

## Phase Map

| Phase | Direct action | Main source inputs | Main outputs |
| --- | --- | --- | --- |
| Stage source tree | Copy source case and shared source trees into `build_out/<case>/worktree/` | `application/<case>`, `application/build_app`, `application/template`, `common_oper`, `../common/src`, `../dpuapi` | Isolated build worktree |
| Build common simulator library | `make -C common/src` | `../common/src/Makefile`, `../common/src/*.c`, `../common/src/*.h` | `libcommon.so` |
| Build app compiler library | `make -C testcase/common_oper` | `common_oper/Makefile`, `common_oper/*.{c,cpp,h}`, `common_oper/map/*.{cpp,h}` | `libapp_build_common.so` |
| Generate app configs | Compile and run `csv_generate/test_app_conf_generate.c` directly | case `csv_generate/test_app_conf_generate.c`, `conf.h`, `conf_PEmap.h`, `common_oper/write_file.cpp` | `app*.conf`, `simulator_bin/instance_conf_info_file.bin`, `rtl_bin/cbufData_instance.bin` |
| Generate task CSV/templates | `make -C gpdpu_TestOp`, run `gpdpu_TestOp/app_build`, then build each `task*/subtask*/build_so` | case `gpdpu_TestOp/Makefile`, `task_main.cpp`, `task_main.h`, plus generated or existing `task*/subtask*/build_so/{Makefile,*.cpp}` | `task*/subtask*/template/*.csv`, `libsubtask.so` |
| Generate SPM input | Compile and run `spm_data/data_generate.c` directly | case `spm_data/data_generate.c`, generated `csv_generate/conf*.h` | case root `input_data.bin` |
| Convert SPM layout | Compile and run `application/template/input_data_convert.c` directly | `application/template/input_data_convert.c`, `common_oper/write_file.cpp`, case `input_data.bin` | `rtl_bin/spmData.bin`, optional `rtl_bin/spmResult.bin` |
| Build RISC-V program | `make -C riscv riscv.bin` | case `riscv/makefile`, `riscv/testarm.c`, `../dpuapi/DpuAPI.c`, `../dpuapi/DpuAPI.h` | `riscv/riscv`, `riscv/riscv.lst` |
| Build runtime materials | Build `application/build_app/main.cpp` in case root and run `build_app app0.conf` | `application/build_app/Makefile`, `application/build_app/main.cpp`, case root `*.cpp`, generated `app*.conf`, generated `task*/...`, shared libraries | `simulator_bin/insts_file.bin`, `exeblock_conf_info_file.bin`, `tasks_conf_info_file.bin`, `subtasks_conf_info_file.bin`, RTL mirror files |
| Collect package | Concatenate/copy runtime-facing outputs | `result/cbuf_file.bin`, `result/micc_file.bin`, `input_data.bin`, `riscv/riscv` | `runtime_packages/<case>/config/*` |

## Source Files We Must Keep

For the direct workflow, the important source closure is smaller than the old
mixed source/build directory suggests.

Shared common simulator sources:

```text
../common/src/Makefile
../common/src/*.c
../common/src/*.h
```

Shared app compiler sources:

```text
common_oper/Makefile
common_oper/*.{c,cpp,h}
common_oper/map/*.{cpp,h}
```

Shared application builder:

```text
application/build_app/Makefile
application/build_app/main.cpp
```

Shared SPM converter:

```text
application/template/input_data_convert.c
```

RISC-V API support:

```text
../dpuapi/DpuAPI.c
../dpuapi/DpuAPI.h
```

For a case shaped like `application/CASE/softmax_1`, the per-case source inputs
are:

```text
<case>/csv_generate/test_app_conf_generate.c
<case>/csv_generate/conf.h
<case>/csv_generate/conf_PEmap.h
<case>/csv_generate/tempfile.h

<case>/gpdpu_TestOp/Makefile
<case>/gpdpu_TestOp/task_main.cpp
<case>/gpdpu_TestOp/task_main.h
<case>/gpdpu_TestOp/task*/subtask*/build_so/Makefile
<case>/gpdpu_TestOp/task*/subtask*/build_so/*.cpp

<case>/spm_data/data_generate.c
<case>/spm_data/data.h                 # conservative keep; not always included

<case>/riscv/makefile
<case>/riscv/testarm.c

<case>/elementwise_template.cpp
<case>/riscv_main.cpp
<case>/riscv_main.h
```

`app*.conf`, `input_data.bin`, `task*/subtask*/template/*.csv`,
`simulator_bin/*`, `rtl_bin/*`, `result/*`, `*_multi_app/*`, `*.o`, `.so`, and
case-local `build_app` binaries are generated materials. They may exist in the
restored examples, but the direct workflow should be able to regenerate the
runtime package without treating them as canonical source.

## Important Boundaries

The workflow does not invoke these old entry scripts:

```text
<case>/run.sh
<case>/clean.sh
<case>/csv_generate/run.sh
<case>/gpdpu_TestOp/run.sh
<case>/spm_data/run.sh
application/build_app/run_mtr.sh
```

Some old C generators have unstable process exit codes on macOS. The workflow
therefore logs their exit status but uses file existence and non-empty checks as
the actual success condition for:

```text
csv_generate/test_app_conf_generate.c -> instance_conf_info_file*.bin
spm_data/data_generate.c              -> input_data.bin
application/template/input_data_convert.c -> spmData.bin
```

`instance_conf_info_file.bin` belongs to the config-generation phase. It should
not be deleted before `build_app` aggregation, because `build_app` generates
instruction/exeblock/task/subtask materials but does not rebuild instance
configuration.

If the local RISC-V toolchain cannot rebuild `riscv/riscv`, the workflow may
fall back to a prebuilt source `riscv/riscv` file and records that in
`metadata.json` as `riscv_program_source: source_prebuilt`.

## What This Means For Future Cleanup

A cleaned case directory should keep source inputs and allow generated outputs
to move under `build_out/` and `runtime_packages/`. We should be conservative
for now: first batch-test more examples, then decide whether checked-in
generated files can be removed from the private repo or merely ignored by the
workflow.
