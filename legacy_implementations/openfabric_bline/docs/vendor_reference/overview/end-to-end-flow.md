# 端到端总览

## 总流程

以 `softmax_1` 为例，当前仓库的实际执行路径可以概括为：

```text
test/run_app_riscv.sh
  -> testcase/application/<app_name>/run.sh
      -> csv_generate/run.sh
          -> test_app_conf_generate.c
          -> gpdpu_TestOp/run.sh
              -> task_main.cpp
              -> task*/subtask*/template/*.cpp
              -> task*/subtask*/template/*.csv
          -> task*/subtask*/build_so/run.sh
              -> common_oper/libapp_build_common.so
              -> simulator_bin/*
          -> spm_data/run.sh
      -> riscv/makefile
          -> riscv/testarm.c + dpuapi/DpuAPI.c
          -> riscv/riscv
  -> testcase/application/build_app/run_mtr.sh
      -> result/*
  -> copy result/ and riscv/riscv into config/
  -> ../../core/bin/runtime ./ top.so topPara.so common/src/libcommon.so
```

从开发视角看，它分成四条线：

1. 算子和 case 配置线：决定这个 case 做什么、shape 是什么、任务如何拆。
2. 指令编译线：把算子模板生成的 CSV 汇编成 DPU 可消费的 packed binary。
3. 控制程序线：编译 RISC-V 程序，运行时由它触发 DMA、CBUF/MICC 加载和 kernel start。
4. 模拟器线：SimICT runtime 加载 `top.so` 等模块图，在 x86 主机上跑离散事件仿真。

## 第一阶段：case 准备

当前可见流程从这些文件开始：

```text
csv_generate/conf.h
csv_generate/conf_PEmap.h
gpdpu_TestOp/task*/subtask*/template/*.cpp
riscv/testarm.c
```

`conf.h` 和 `conf_PEmap.h` 不像是当前工具链自动生成的文件。仓库里虽然有 `elementwise_template.cpp::gen_confh(...)` 这类残留生成函数，但实际 `run.sh` 不调用它，也没有找到调用 `execute_elementwise(...)` 的 driver。因此在当前仓库里应当把它们视为手写或手工维护的 case 输入。

## 第二阶段：生成 app/task/subtask 配置

入口：

```text
testcase/application/CASE/softmax_1/csv_generate/run.sh
```

它先编译：

```sh
g++ -std=c++11 test_app_conf_generate.c ../../../common_oper/write_file.cpp \
    -o app_build \
    -I ../../../../common/src \
    -I ../../../common_oper
```

然后执行：

```sh
./app_build
```

`test_app_conf_generate.c` 消费 `conf.h` 和 `conf_PEmap.h`，写出 app/task/subtask/instance 相关的配置文件。它不是算子数学逻辑本身，也不生成 `conf.h`。

这一阶段会产生或整理：

```text
app*.conf
task*.conf
subtask*.conf
instance_conf_info_file*.bin
instance_conf_info_for_rtl_file*.bin
simulator_bin/instance_conf_info_file.bin
rtl_bin/cbufData_instance.bin
tempfile.h
```

其中 `tempfile.h` 记录数组名到 SPM base slot 的映射，后面的 CSV 生成模板会用到。

## 第三阶段：生成 CSV

`csv_generate/run.sh` 接着进入：

```text
gpdpu_TestOp/
```

执行：

```sh
make clean
rm task*/subtask*/template/*.csv
make -j
./app_build
```

这里的 `app_build` 来自 `gpdpu_TestOp/task_main.cpp` 和各个 `task*/subtask*/template/*.cpp`。

`task_main.cpp` 读取 `conf_PEmap.h` 中的 `case_name`，例如 softmax case 会选择 softmax 的 op 类型。真正展开到每个 PE 的指令流，是由：

```text
gpdpu_TestOp/task*/subtask*/template/*.cpp
```

这些文件写出的。它们最终输出：

```text
gpdpu_TestOp/task*/subtask*/template/0.csv
gpdpu_TestOp/task*/subtask*/template/1.csv
...
```

这些 CSV 是类汇编，不是最终二进制。

## 第四阶段：CSV 汇编、映射和打包

`csv_generate/run.sh` 对每个 task/subtask 进入：

```text
task<i>/subtask<j>/build_so
```

执行 `./run.sh`。该路径通常会构建并运行一个 subtask shared object / packer，依赖：

```text
testcase/common_oper/libapp_build_common.so
common/src/libcommon.so
```

核心流程在 `testcase/common_oper` 中：

```text
Csv_Operate
  -> Inst_Block
  -> Graph_Extend
  -> INST_BLK_MAP / inst_blk_map_bat
  -> exe_block_gen
  -> task_print
```

它会把 CSV 解析成内部 `inst_t`，做图扩展、PE 放置、寄存器和 copy 指令修正，然后写出 simulator/RTL 所需的 packed binary。

## 第五阶段：生成 SPM/input/result 数据

`csv_generate/run.sh` 最后进入：

```text
spm_data/
```

执行 `./run.sh`。这一阶段生成输入、SPM 初始数据、golden/check 数据等 case 相关文件。

之后 `run_mtr.sh` 会把应用结果整理到：

```text
result/
```

典型结果包括：

```text
result/cbuf_file.bin
result/micc_file.bin
result/input_data.bin
```

## 第六阶段：编译 RISC-V 控制程序

入口：

```text
riscv/makefile
```

它用 `riscv64-unknown-elf-gcc` 编译：

```text
riscv/testarm.c
dpuapi/DpuAPI.c
```

生成：

```text
riscv/riscv
riscv/riscv.lst
```

这个 `riscv/riscv` 不是主机程序，而是模拟器加载的 guest/control program。后续会被复制成：

```text
config/riscv_program
```

## 第七阶段：启动模拟器

顶层入口：

```text
test/run_app_riscv.sh
```

关键动作：

```sh
cp testcase/application/${app_name}/result ./config -r
cp testcase/application/${app_name}/input_data.bin ./config
cp testcase/application/${app_name}/riscv/riscv ./config/riscv_program
../../core/bin/runtime ./ top.so topPara.so common/src/libcommon.so
```

`runtime` 是 x86-64 主机 ELF。它会加载 `top.so`、`topPara.so`、`libcommon.so` 和模块 shared object，创建 SimICT object/port/thread 图，然后执行模拟。

## 本地 mock runtime 接入点

当前项目下一阶段要替换的是第七阶段的闭源 runtime，而不是前面的算子生成和打包流程。

目标流程变成：

```text
test/run_app_riscv.sh
  -> 前六阶段保持不变
  -> 生成 result/cbuf_file.bin、result/micc_file.bin、input_data.bin、riscv/riscv
  -> 本地 mock runtime 读取同一批生成物
  -> 模拟 DDR/SPM/DMA/CBUF/MICC/PE
  -> 输出 mock result / trace / check log
```

第一版 mock runtime 可以先绕开 `riscv/riscv`，直接执行 `testarm.c` 里表达的控制流程：

```text
加载 CBUF/MICC
DMA input 到 SPM
启动 kernel
等待完成
DMA output 回 DDR
```

后续如果需要验证 `DpuAPI.c` 和 RISC-V MMIO 控制面，再把同一个 mock executor 接入 QEMU 或 RISC-V harness。

## 关键理解

这个项目里“编译算子”不等于“从数学表达式自动合成硬件指令”。更准确的说法是：

```text
开发者手工维护 case contract 和后端模板
工具链把模板产出的 CSV 汇编、映射、打包
RISC-V 控制程序在模拟器里加载并启动任务
SimICT runtime 驱动整个设备模型
```
