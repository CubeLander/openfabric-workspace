# Testcase 工作流重建方向

本目录承载当前 GPDPU / RISC-V examples 的算子编译、打包和运行准备流程。下一阶段我们的目标是把现在混在一起的源码、中间产物、构建产物和 runtime 输入重新分层，建立一个可重复、可本地执行、最终能直接喂给闭源 runtime 的工作流。

硬件工作模型记录在 [gpdpu-hardware-working-model.md](gpdpu-hardware-working-model.md)。后续 workflow、GEMM CSV 生成器和 runtime package 规范都以这份模型为当前对齐基线。

一句话目标：

```text
从干净的算子 example 源码出发，
本地构造出闭源 runtime 可消费的 runtime_package，
并且不再依赖远程机器上的神秘构建状态。
```

## 当前结论

闭源 `runtime` 参与的是“消费和执行”，不是“构造 runtime 输入文件”。

当前调查显示，构造 runtime 输入文件的过程主要依赖：

```text
common/src 源码
testcase/common_oper 源码
example 自己的 conf/template/spm_data/riscv 源码
gcc/g++/make
riscv64-unknown-elf-gcc
GMP/MPFR
```

没有发现生成 `cbuf_file.bin`、`micc_file.bin`、`input_data.bin`、`riscv_program` 时必须调用闭源 SimICT runtime、`top.so`、`topPara.so` 或 Scheme runtime graph 生成器。

因此可以把边界切成两段：

```text
算子编译/打包阶段:
  本地可重建。目标是生成 runtime_package。

闭源 runtime 执行阶段:
  依赖 core/bin/runtime、top.so、topPara.so、libcommon.so。
  只消费 runtime_package 中的 config 文件集合。
```

## 闭源 runtime 最终消费什么

顶层测试脚本 `../test/run_app_riscv.sh` 在启动 runtime 前会构造：

```text
config/cbuf_file.bin
config/micc_file.bin
config/input_data.bin
config/riscv_program
```

其中 `common/src/basic_def.h` 明确了模拟器模块读取的文件名：

```c
#define CBUF_MEM_FILE "./config/cbuf_file.bin"
#define MICC_MEM_FILE "./config/micc_file.bin"
#define SPM_MEM_FILE  "./config/input_data.bin"
```

`common/src/common_func.c` 会统一拼接：

```c
sprintf(file_name, "config/%s", sub_file_name);
```

`config/riscv_program` 由顶层脚本复制：

```sh
cp testcase/application/${app_name}/riscv/riscv ./config/riscv_program
```

它是 runtime 中 RISC-V 设备模型加载执行的 guest/control program。

## runtime_package 规范

后续我们希望把每个 example 的最终运行输入整理成独立包：

```text
runtime_packages/<case_name>/
  config/
    cbuf_file.bin
    micc_file.bin
    input_data.bin
    riscv_program
  metadata.json
  source_manifest.txt
  build.log
  check/
    check.sh
    golden 或 result_check 相关文件
```

最小可运行包只需要：

```text
config/cbuf_file.bin
config/micc_file.bin
config/input_data.bin
config/riscv_program
```

`metadata.json` 建议记录：

```text
case_name
source_app_path
build_time
toolchain versions
sha256 / size of every config file
original command
duplicate_application_amount
app_num
notes
```

这样团队可以把算子 example 源码和 runtime 可重放输入分开管理。

## 现有 example 到 runtime_package 的生成链路

以 `${app_name}` 表示一个算子 example。

当前脚本入口：

```sh
cd ../test
sh ./run_app_riscv.sh ${app_name} 1
```

这个脚本实际做了两件事：

```text
1. 构造 runtime 输入文件。
2. 启动闭源 runtime 执行并检查。
```

我们下一步要把它拆开。

### input_data.bin

来源：

```text
testcase/application/${app_name}/input_data.bin
```

典型生成路径：

```text
application/${app_name}/spm_data/run.sh
  -> data_generate.c
  -> input_data_convert.c
  -> write_file.cpp
```

依赖：

```text
g++
GMP/MPFR
common/src
common_oper/write_file.cpp
```

这一步不依赖闭源 runtime。

### riscv_program

来源：

```text
testcase/application/${app_name}/riscv/riscv
```

典型生成路径：

```text
application/${app_name}/riscv/makefile
  -> testarm.c
  -> dpuapi/DpuAPI.c
  -> common/src headers
```

依赖：

```text
riscv64-unknown-elf-gcc
riscv64-unknown-elf-objdump
```

这一步不依赖闭源 runtime。

`riscv/riscv` 不是 host 程序，而是 runtime 中 RISC-V 设备模型执行的 guest/control program。它负责通过 `DpuAPI.c` 写 MMIO，触发：

```text
DPU_CbufTransfer(CBUF_DDR_ADDR)
DPU_MiccTransfer(MICC_DDR_ADDR)
DMA input -> SPM
DPU_Kernel_Start(...)
DPU_Kernel_Wait_Finish(...)
DMA output -> DDR
DPU_App_Finish()
```

### cbuf_file.bin

runtime 消费：

```text
config/cbuf_file.bin
```

当前来源：

```text
application/${app_name}/result/cbuf_file.bin
```

由 `application/build_app/run_mtr.sh` 拼接得到：

```sh
cat simulator_bin/insts_file.bin              >> simulator_bin_multi_app/cbuf_file.bin
cat simulator_bin/exeblock_conf_info_file.bin >> simulator_bin_multi_app/cbuf_file.bin
cat simulator_bin/instance_conf_info_file.bin >> simulator_bin_multi_app/cbuf_file.bin
cp simulator_bin_multi_app/cbuf_file.bin result/
```

组成：

```text
insts_file.bin
  PE 指令列表，来自 CSV 解析、伪指令展开、PE mapping 和 task_print。

exeblock_conf_info_file.bin
  每个 PE/block 的执行 block 元数据，来自 exe_block_gen 和 task_print。

instance_conf_info_file.bin
  instance/base_addr 等运行期地址表，来自 csv_generate/test_app_conf_generate.c。
```

这一步不依赖闭源 runtime。

### micc_file.bin

runtime 消费：

```text
config/micc_file.bin
```

当前来源：

```text
application/${app_name}/result/micc_file.bin
```

由 `application/build_app/run_mtr.sh` 拼接得到：

```sh
cat simulator_bin/tasks_conf_info_file.bin    >> simulator_bin_multi_app/micc_file.bin
cat simulator_bin/subtasks_conf_info_file.bin >> simulator_bin_multi_app/micc_file.bin
cp simulator_bin_multi_app/micc_file.bin result/
```

组成：

```text
tasks_conf_info_file.bin
  task 级 MICC 配置。

subtasks_conf_info_file.bin
  subtask 级 MICC 配置。
```

这一步不依赖闭源 runtime。

## 当前构造链依赖图

现有 example 构造 runtime 文件大致经过：

```text
application/${app_name}/run.sh
  -> clean.sh
  -> csv_generate/run.sh
      -> test_app_conf_generate.c
      -> app*.conf / task*.conf / subtask*.conf
      -> simulator_bin/instance_conf_info_file.bin
      -> rtl_bin/cbufData_instance.bin
      -> gpdpu_TestOp 或 gpdpu_tensor
          -> task_main.cpp
          -> task*/subtask*/template/*.cpp
          -> task*/subtask*/template/*.csv
      -> task*/subtask*/build_so/run.sh
          -> test_graph_extend.cpp
          -> libsubtask.so
      -> spm_data/run.sh
          -> input_data.bin
  -> riscv/makefile
      -> riscv/riscv

application/build_app/run_mtr.sh
  -> build_app/main.cpp
  -> common_oper/libapp_build_common.so
  -> common/src/libcommon.so
  -> dlopen task*/subtask*/build_so/libsubtask.so
  -> simulator_bin/*
  -> result/cbuf_file.bin
  -> result/micc_file.bin
```

注意：`build_app/main.cpp` 会 `dlopen` 每个 subtask 的：

```text
task*/subtask*/build_so/libsubtask.so
```

但这些 `libsubtask.so` 是 example 自己通过 `test_graph_extend.cpp` 和 Makefile 本地编译出来的，不是闭源外部组件。

## 当前问题

现在的 workflow 非常难用，主要因为源码和产物混在同一个目录：

```text
conf.h / template.cpp / testarm.c
*.csv
*.bin
*.so
obj/
result/
rtl_bin/
simulator_bin/
rtl_bin_multi_app/
simulator_bin_multi_app/
input_data.bin
output_data.bin
riscv/riscv
run.log / check.log
```

这导致：

```text
很难判断哪些文件需要提交。
很难区分源码、临时中间产物和 runtime 最终输入。
clean.sh 会删除大量文件，容易误伤或掩盖状态。
构建结果和源码路径绑定，无法稳定复现。
不利于学校团队多人协作。
不利于后续把 examples 批量转换成 runtime_package。
```

## 下一步目标

我们要重建算子编译工作流，把“构造 runtime_package”作为明确产物。

建议拆成四层目录：

```text
operator_sources/
  只放干净源码：
    conf.h
    conf_PEmap.h
    template/*.cpp
    test_graph_extend.cpp
    testarm.c
    data_generate.c
    result_check.c

build/
  只放中间产物：
    app*.conf
    task*.conf
    subtask*.conf
    *.csv
    obj/
    libsubtask.so
    simulator_bin/*
    rtl_bin/*

runtime_packages/
  只放 runtime 最终输入：
    config/cbuf_file.bin
    config/micc_file.bin
    config/input_data.bin
    config/riscv_program
    metadata.json

run_outputs/
  只放闭源 runtime 执行结果：
    run.log
    stat/
    rtl_trace/
    sim_trace/
    gpdpu_data
    check.log
```

第一版不需要立刻改所有旧脚本。可以先写 wrapper：

```text
build_runtime_package.sh
  输入: application/${app_name}
  输出: runtime_packages/${app_name}
  行为:
    1. 调用现有 run.sh，但停止在 runtime 前。
    2. 调用现有 run_mtr.sh 生成 result。
    3. 拷贝 result/cbuf_file.bin、result/micc_file.bin、input_data.bin、riscv/riscv。
    4. 写 metadata.json 和 source_manifest.txt。
```

然后再逐步把旧 workflow 内部迁移到 out-of-tree build。

## 本地复现环境

为了在本地完全构造 runtime_package，需要准备：

```text
Linux x86_64 container 或 VM
gcc / g++
make
riscv64-unknown-elf-gcc
riscv64-unknown-elf-objdump
GMP / MPFR headers and libs
```

当前 Mac 本机调查到：

```text
riscv64-unknown-elf-gcc: not found
GMP: not found
MPFR: not found
```

所以当前机器还不能原样跑完整构造链。这个是普通工具链依赖，不是闭源组件依赖。

另外，为了执行闭源 runtime，还需要补齐 runtime 侧文件：

```text
core/bin/runtime
core/bin/runtime_verbose
top.so
topPara.so
common/src/libcommon.so
```

本地当前拷贝里缺少脚本期望路径下的 `core/bin/runtime`、`top.so`、`topPara.so`。这些属于执行阶段依赖，不属于 runtime_package 构造阶段依赖。

## 工作计划

### M1: 固化 runtime_package 提取器

目标：

```text
从已有 example 构造 runtime_packages/${app_name}/
```

产物：

```text
build_runtime_package.sh
runtime_packages/<case>/config/*
metadata.json
source_manifest.txt
```

### M2: 容器化构造环境

目标：

```text
在 Linux 容器中从 clean example 到 runtime_package 一键完成。
```

产物：

```text
Dockerfile 或 devcontainer
toolchain install notes
smoke test case
```

### M3: 分离源码和 build 产物

目标：

```text
旧 app 目录保留源码。
所有中间产物进入 build/<case>/。
runtime 最终输入进入 runtime_packages/<case>/。
```

产物：

```text
out-of-tree build wrapper
clean source manifest
artifact manifest
```

### M4: 批量 example 转换

目标：

```text
把远程 examples 批量转换为 runtime_package，
并用闭源 runtime 或后续 mock runner 做回归。
```

产物：

```text
runtime_packages/*
batch build report
batch replay report
```

## 判断标准

当一个 example 满足下面条件，就说明我们掌握了它的 runtime package 构造过程：

```text
1. 从干净源码目录出发。
2. 不调用 core/bin/runtime。
3. 不依赖远程机器残留中间产物。
4. 本地生成 config/cbuf_file.bin。
5. 本地生成 config/micc_file.bin。
6. 本地生成 config/input_data.bin。
7. 本地生成 config/riscv_program。
8. metadata 记录所有输入源码和工具链版本。
9. 用闭源 runtime 执行 package 时结果和远程一致。
```

这个 README 记录的是下一阶段的工作方向：先不要重写算子编译器，也不要先做完整 mock runtime。先把现有 example 到 runtime_package 的构造过程从混乱脚本中抽离出来，做成可重复、可审计、可团队协作的本地工作流。
