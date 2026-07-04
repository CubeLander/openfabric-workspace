# gemm_template_fusion_new.zip Investigation

Date: 2026-06-15
Zip: `/home/flecther/workspace/dpu_project/gemm_template_fusion_new.zip`
Unpacked scratch dir: `/home/flecther/workspace/dpu_project/tmp/gemm_template_fusion_new_inspect/gemm_template_fusion`

## Summary

The new package is not a different generated binary/runtime artifact. It is best understood as a clean source-level `application/gemm_template_fusion` case.

Compared with the existing local application case at:

```text
/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion
```

all 97 common files are byte-identical. The visible differences are:

1. The new zip includes five root-level C++ generator/source files that are absent from the existing application directory.
2. The new zip omits generated artifacts already present in the existing application directory, such as `app*.conf`, generated CSV templates, simulator binaries, RTL binaries, generated task copies, and build outputs.

Therefore the teacher instruction to delete root-level `.cpp` files before compilation makes sense: after deleting those files, the zip becomes a clean source tree aligned with the existing application workflow shape.

## Root-level files only in the new zip

```text
OperatorGemm.cpp
riscv_main.cpp
gen_testarm.cpp
gen_dpuctrl.cpp
gen_dpuctrl_test.cpp
```

The existing application directory already has the corresponding headers:

```text
OperatorGemm.h
riscv_main.h
operator_conf.h
```

but does not have those root `.cpp` files.

## Generated artifacts present in existing application but absent from new zip

The existing application directory contains generated products, including:

```text
app0.conf
app1.conf
app2.conf
app3.conf
csv_generate/instance_conf_info_file.bin
gpdpu_tensor/task*/subtask*/template/*.csv
simulator_bin/*
rtl_bin/*
riscv/riscv
riscv/riscv.bin
```

The new zip does not include generated `.bin`, `.csv`, `.so`, `app*.conf`, or RISC-V binary products. It expects the vendor workflow to regenerate them.

## Common-source comparison

`gemm_template_fusion_new.zip` versus existing application source:

```text
common files: 97
changed common files: 0
identical common files: 97
```

This means the meaningful source files under `csv_generate/`, `gpdpu_tensor/`, `riscv/`, and `spm_data/` are identical to the existing local application copy.

## Build-out comparison

Compared with the local build-out reference:

```text
/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/build_out/gemm_template_fusion/worktree/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion
```

only one common source file differs:

```text
csv_generate/conf_PEmap.h
```

The only observed diff is that build-out includes an extra include:

```text
#include <string>
```

The new zip and the existing application version of `csv_generate/conf_PEmap.h` are identical.

## Workflow notes

Top-level `run.sh` in the new package performs the normal vendor workflow:

```text
./clean.sh
cd csv_generate/
./run.sh
cd ../riscv/
make
```

It does not call `exec.sh`.

Top-level `exec.sh` is the only script that directly compiles the root `.cpp` generator files:

```text
g++ riscv_main.cpp -c -o riscv_main.o
g++ OperatorGemm.cpp -c -o OperatorGemm.o
g++ gen_testarm.cpp -c -o gen_testarm.o
g++ gen_dpuctrl.cpp -c -o gen_dpuctrl.o
g++ riscv_main.o OperatorGemm.o gen_testarm.o gen_dpuctrl.o -o riscv_main
./riscv_main
```

Since the normal `run.sh` does not invoke `exec.sh`, the teacher instruction likely prevents accidental use of this root-level generator path or keeps the application tree consistent with the legacy source layout.

## Important implication for our current binary mismatch investigation

This new package does not by itself explain the remote diff where the arch-13 `application/gemm_template_fusion` legacy has only `task0` active while our OpenFabric output emits four active tasks. The new package source is identical to the existing local application source after ignoring/removing the root `.cpp` generator files.

So the next useful comparison is not source diff. It is to build this clean zip on arch-13 with the teacher-prescribed deletion step, then diff the generated runtime artifacts against:

1. arch-13 existing `application/gemm_template_fusion`, and
2. our OpenFabric bundle.

If the newly generated artifacts differ from the existing remote application artifacts, then the remote application directory is stale or partially generated. If they match, then the task0-only behavior is the active vendor reference for this case.

## Recommended handling

When using the new zip as a vendor source reference:

```bash
unzip gemm_template_fusion_new.zip
cd gemm_template_fusion
rm -f ./*.cpp
./run.sh
```

Do not delete `.cpp` files recursively. The tree contains `.cpp` sources below subdirectories that are part of the normal build/generation workflow, such as `gpdpu_tensor/task_main.cpp` and `spm_data/data_generate.cpp`.

