# 手写文件和生成文件清单

这份清单用于回答一个非常关键的问题：开发者到底应该维护哪些文件，哪些文件只是工具链输出。

## 手写或手工维护

### case contract

```text
testcase/application/CASE/<case>/csv_generate/conf.h
testcase/application/CASE/<case>/csv_generate/conf_PEmap.h
```

当前应视为手写/手工维护。它们定义 shape、task/subtask、case name、DMA/SPM/DDR 布局等。

### 算子后端模板

```text
testcase/application/CASE/<case>/gpdpu_TestOp/task*/subtask*/template/*.cpp
```

这是当前仓库里真正的算子 lowering 逻辑。开发者在这里写如何生成每个 PE 的 CSV。

### RISC-V 控制程序

```text
testcase/application/CASE/<case>/riscv/testarm.c
dpuapi/DpuAPI.c
```

`testarm.c` 可能是模板派生或手工改写，但在当前 case 中应视为需要维护的控制程序。`DpuAPI.c` 是公共 API 层。

### 工具链源码

```text
testcase/common_oper/*
common/src/*
pe/src/*
gpdpu/core/bin/*.ss
gpdpu/core/include/*.h
```

这些是工具链或模拟器模块源码/脚本。正常写一个 case 不一定改它们。

## 工具生成或中间产物

### csv_generate 阶段

```text
csv_generate/app_build
csv_generate/app*.conf
csv_generate/task*.conf
csv_generate/subtask*.conf
csv_generate/tempfile.h
csv_generate/instance_conf_info_file*.bin
csv_generate/instance_conf_info_for_rtl_file*.bin
```

`test_app_conf_generate.c` 生成或整理这些文件。

### gpdpu_TestOp 阶段

```text
gpdpu_TestOp/app_build
gpdpu_TestOp/task*/subtask*/template/*.csv
```

`gpdpu_TestOp/run.sh` 会删除旧 CSV 并重新生成。

### build_so / common_oper 阶段

```text
task*/subtask*/build_so/libsubtask.so
task*/subtask*/simulator_bin/*
task*/subtask*/rtl_bin/*
```

这些来自 CSV 编译、映射和打包。

### app result 阶段

```text
result/cbuf_file.bin
result/micc_file.bin
result/input_data.bin
```

这些是顶层模拟器运行前的 app package。

### RISC-V build 阶段

```text
riscv/riscv
riscv/riscv.lst
```

由 `riscv/makefile` 生成。

### simulator config 阶段

```text
config/result/*
config/input_data.bin
config/riscv_program
```

由 `test/run_app_riscv.sh` 复制生成。

### runtime 输出

```text
run.log
gpdpu_data
stat/*
rtl_trace/*
sim_trace/*
test/check.log
```

由 SimICT runtime 和后处理脚本生成。

## 闭源或外部预构建

```text
core/bin/runtime
core/bin/runtime_verbose
top.so
topPara.so
```

`runtime` / `runtime_verbose` 是 SimICT runtime ELF。源码缺失。

`top.so` / `topPara.so` 是模拟器配置/参数 shared object。它们和 Scheme 工具链有关，通常不是算子 case 直接手写。

## 判断规则

看到一个文件时，可以按下面规则判断：

```text
被 run.sh 删除后重建的，多半是生成文件。
被多个阶段 include 的 header，尤其 conf.h/conf_PEmap.h，多半是 case contract。
template/*.cpp 是源码。
template/*.csv 是生成物。
build_so、simulator_bin、rtl_bin、result、config 基本都是构建/运行产物。
```

## 修改建议

想新增一个类似 softmax 的 case，最现实的做法不是从零写工具链，而是复制一个 case，然后改：

```text
csv_generate/conf.h
csv_generate/conf_PEmap.h
gpdpu_TestOp/task*/subtask*/template/*.cpp
spm_data/*
riscv/testarm.c
```

然后运行 case 的 `run.sh`，再由顶层 `test/run_app_riscv.sh` 进入模拟器。

