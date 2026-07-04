# GEMM Template Fusion Generation Probe

Date: 2026-06-15
Context: investigate whether local and remote vendor workflows generate different artifacts from `gemm_template_fusion_new.zip`.

## Inputs

New vendor zip:

```text
/home/flecther/workspace/dpu_project/gemm_template_fusion_new.zip
```

Teacher instruction:

```text
Before compilation, delete `.cpp` files under the package root.
```

Important interpretation:

```bash
rm -f ./*.cpp
```

Do not delete `.cpp` recursively. Subdirectory `.cpp` files such as `spm_data/data_generate.cpp` and `gpdpu_tensor/task_main.cpp` are part of the normal workflow.

## Source-level result

The new zip is source-identical to the local existing application case for all common files:

```text
common files: 97
changed common files: 0
```

Only root-level generator `.cpp` files are extra in the zip:

```text
OperatorGemm.cpp
riscv_main.cpp
gen_testarm.cpp
gen_dpuctrl.cpp
gen_dpuctrl_test.cpp
```

Existing local application lacks these root `.cpp` files, matching the teacher's deletion instruction.

## Local clean-source probe

A probe case was prepared at:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion_new_probe_patched
```

Steps:

```bash
cp -a gemm_template_fusion_new gemm_template_fusion_new_probe_patched
rm -f gemm_template_fusion_new_probe_patched/*.cpp
mkdir -p simulator_bin rtl_bin
chmod +x all *.sh / clean helper scripts
```

Two local environment quirks were observed:

1. Zip script executable bits were not available after unzip/copy in this local environment, so `chmod +x` was needed.
2. Local GCC requires `#include <string>` in `csv_generate/conf_PEmap.h`; without it, `test_app_conf_generate.c` fails on `map<string, ...>`. The local build-out reference has this include; the new zip and existing application source do not.

After adding only that include for the local probe, `csv_generate/run.sh` completed and generated source/runtime inputs.

## Generated source/template artifacts

The patched local probe generated the same application-level artifacts as the existing local application/build_out reference:

```text
app0.conf: match existing application and build_out
app1.conf: match existing application and build_out
app2.conf: match existing application and build_out
app3.conf: match existing application and build_out
simulator_bin/instance_conf_info_file.bin: match build_out
rtl_bin/cbufData_instance.bin: match build_out
input_data.bin: match build_out
representative task*/subtask*/template/*.csv: match existing application and build_out
```

Counts:

```text
probe app_conf: 4
probe csv templates: 256
probe libsubtask.so: 12
```

Conclusion:

```text
The source-generation stage is inherently four-app/four-task at the application source level.
```

This is controlled by:

```text
csv_generate/conf_PEmap.h: TASK_NUM = 4
csv_generate/run.sh: task_num=4
csv_generate/test_app_conf_generate.c: writes app0.conf..app3.conf
```

## Vendor final packaging stage

`test/run_app_riscv.sh` has:

```text
Duplicate_Application_Amount=1
app_num=1
```

It calls:

```bash
./run_mtr.sh ${app_name} ${Duplicate_Application_Amount} ${app_num}
```

`application/build_app/run_mtr.sh` then computes:

```sh
app_num=`expr $3 - 1`
for t in $(seq 0 ${app_num})
```

and builds the argument list from duplicate amount:

```sh
duplicat_num=`expr $2 - 1`
for k in $(seq 0 ${duplicat_num})
do
    tmp=app${k}.conf
    Build_Conf_ARG="${Build_Conf_ARG} ${tmp}"
done
./build_app $Build_Conf_ARG
```

With the default values, the final packer consumes only:

```text
app0.conf
```

This is the strongest local cross-check for why remote generated control tables show only task0 active, even though source generation creates `app0.conf` through `app3.conf`.

## Local final-packaging probe

Running local `build_app/run_mtr.sh gemm_template_fusion_new_probe_patched 1 1` confirmed that the packer starts from `app0.conf` only:

```text
./build_app app0.conf
[readFromTaskFile-371]task number 1
```

It generated a one-task simulator view locally. This local `run_mtr.sh` is marked OCR-derived/reconstructed in our repo, so its exact table sizing may not match arch-13. Still, it validates the app-selection mechanism.

Observed local generated individual simulator sizes:

```text
simulator_bin/tasks_conf_info_file.bin: 120 bytes
simulator_bin/subtasks_conf_info_file.bin: 2130624 bytes
simulator_bin/exeblock_conf_info_file.bin: 266240 bytes
simulator_bin/insts_file.bin: 21168128 bytes
simulator_bin/instance_conf_info_file.bin: 2097152 bytes
```

The previous remote diff showed full fixed-size task/subtask files:

```text
tasks_conf_info_file.bin: 480 bytes
subtasks_conf_info_file.bin: 8522496 bytes
```

with only task0 active and task1..task3 zero. This suggests the remote real `build_app`/serializer pads to fixed table size, while our local reconstructed script/binary may emit compact one-task files in this probe.

## Implications for OpenFabric

OpenFabric currently emits four active task rows because its backend maps output tile waves to vendor tasks. This matches the source-level app/task generation, but not the default vendor run workflow.

The vendor default workflow is more subtle:

```text
source generation creates app0..app3
final run_app_riscv/build_app default consumes only app0.conf
final binary control table has only task0 active
```

Therefore the remote task0-only diff is not evidence that `conf_PEmap.h` or template generation changed. It is evidence that the final packaging workflow's `app_num=1` / duplicate amount selects only `app0.conf`.

## Current hypothesis

The immediate bug in OpenFabric is likely not source generation. It is that our `legacy_gemm_compat` packaging profile is aligned to the four-app source/template set instead of the default one-app vendor runtime selection used by `run_app_riscv.sh`.

Expected fix direction:

```text
For default gemm_template_fusion legacy_gemm_compat:
  compile the full logical GEMM source model if needed,
  but vendor task/subtask/exeblock/inst emission should match app0.conf-only packaging.
```

The existing `wave_id -> task_id` mapping in OpenFabric should be guarded by an explicit profile. For this specific runtime profile, task rows 1..3 should be inactive/padded, and task0 should own the app0 template blocks.

## Remote verification to run

On arch-13, use the teacher package and build it in a fresh case directory:

```bash
cd /project/home-new/huake01/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application
rm -rf gemm_template_fusion_new_probe
unzip /path/to/gemm_template_fusion_new.zip
mv gemm_template_fusion gemm_template_fusion_new_probe
cd gemm_template_fusion_new_probe
rm -f ./*.cpp
chmod +x clean clean.sh run.sh csv_generate/run.sh gpdpu_tensor/run.sh spm_data/*.sh gpdpu_tensor/task*/subtask*/build_so/run.sh
# If remote GCC needs it, add #include <string> to csv_generate/conf_PEmap.h.
./run.sh
```

Then run the normal packer with default one-app selection:

```bash
cd /project/home-new/huake01/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/build_app
./run_mtr.sh gemm_template_fusion_new_probe 1 1
```

Compare generated `simulator_bin` / `result` outputs against existing remote application and OpenFabric.

## Caution

Do not infer source-level `TASK_NUM=4` directly as final simulator task rows. In the default run workflow, `app_num=1` and `Duplicate_Application_Amount=1` collapse the final packer input to `app0.conf`.
