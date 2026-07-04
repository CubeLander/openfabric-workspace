# 算子开发方法

## 开发者真正写什么

当前仓库暴露出来的算子开发方式比较原始。开发者通常不是写一个高层 kernel，然后由编译器自动 lower。开发者需要直接维护 case 配置、任务拆分、PE 映射、SPM/DDR 地址规划，以及能生成 CSV 指令的 C++ 模板。

主要手写或手工维护文件：

```text
testcase/application/CASE/<case>/csv_generate/conf.h
testcase/application/CASE/<case>/csv_generate/conf_PEmap.h
testcase/application/CASE/<case>/gpdpu_TestOp/task*/subtask*/template/*.cpp
testcase/application/CASE/<case>/riscv/testarm.c
```

对于 `softmax_1`，这些文件共同定义：

- app 数量、task 数量、subtask 数量；
- 每个 tensor 的 shape、DDR/SPM 布局；
- task/subtask 如何拆；
- 每个 PE 应该生成什么 CSV 指令；
- RISC-V 控制程序如何搬数据、加载 CBUF/MICC、启动 DPU；
- 输入和输出如何落盘或校验。

## conf.h

`conf.h` 是 case contract 的核心。它描述的是这个 case 的静态参数，而不是通用工具链逻辑。

常见内容包括：

```text
APP_NUM
TASK_NUM
SUBTASK_NUM
INSTANCE_NUM
DMA input/output plan
DDR address
SPM base slot
tensor shape / size
```

它会被多个阶段消费：

```text
csv_generate/test_app_conf_generate.c
gpdpu_TestOp/task_main.cpp
gpdpu_TestOp/task*/subtask*/template/*.cpp
task*/subtask*/build_so/test_graph_extend.cpp
riscv/testarm.c
spm_data/*.c
```

因此 `conf.h` 是连接“编译器侧”和“运行控制侧”的桥。改错这里，后面 CSV、SPM、RISC-V DMA、MICC 启动都可能一起错。

## conf_PEmap.h

`conf_PEmap.h` 描述和 PE/task mapping 相关的 case 信息。

在 softmax case 中，最关键的是：

```text
case_name = "softmax"
```

`gpdpu_TestOp/task_main.cpp` 根据 `case_name` 选择 op 类型，然后调用不同的 task/subtask template 生成 CSV。

因此，`riscv_main.h` 里有很多 `OpType` 并不代表“要编译哪个算子”的信息来自那里。真正对当前 runnable flow 生效的是：

```text
conf_PEmap.h::case_name
```

## task*/subtask*/template/*.cpp

这些文件是当前仓库里最接近“算子逻辑”的地方，但它们不是 CUDA 式 kernel，也不是数学 DSL。

它们做的是后端代码生成：

```text
输入：case 配置、PE id、subtask 信息、SPM base 映射
输出：task*/subtask*/template/<pe_id>.csv
```

典型代码会：

- 遍历 PE；
- 根据 task/subtask id 判断这一段算子要做什么；
- 拼出 load / compute / flow / store 指令；
- 写入 CSV 文件。

这意味着开发者写的是“如何生成硬件汇编”，而不是“这个算子数学上是什么”。

## task_main.cpp

`gpdpu_TestOp/task_main.cpp` 是 CSV 生成阶段的入口。它大致做：

```text
读取 conf.h / conf_PEmap.h
根据 case_name 构造 op
调用 task/subtask template 生成 CSV
```

它不是最终模拟器入口，也不是 RISC-V 程序入口。

## riscv/testarm.c

`riscv/testarm.c` 是控制面程序。它会被 RISC-V 交叉编译器编成：

```text
riscv/riscv
```

然后顶层测试脚本复制为：

```text
config/riscv_program
```

模拟器运行时，这个程序在模拟 RISC-V 核上执行。它通常负责：

- 调 `DPU_CbufTransfer(...)` 加载 CBUF；
- 调 `DPU_MiccTransfer(...)` 加载 MICC/task 配置；
- 调 DMA 把 input 从 DDR 搬到 SPM；
- 调 `DPU_Kernel_Start(...)` 启动 task；
- 轮询 `DPU_Kernel_Wait_Finish(...)`；
- 调 DMA 把输出从 SPM 搬回 DDR；
- 调 `DPU_App_Finish()` 通知 app 完成。

## 关于 conf.h 是否自动生成

当前判断：在这个仓库实际可见流程里，`conf.h` / `conf_PEmap.h` 应视为手写或手工改出来的文件。

理由：

- `csv_generate/run.sh` 不生成它们，只消费它们。
- `test_app_conf_generate.c` 包含 `conf.h`，但只写 app/task/subtask 配置。
- `gpdpu_TestOp/task_main.cpp` 包含 `conf_PEmap.h`，但只读取 `case_name` 等信息。
- `riscv_main.cpp` / `elementwise_template.cpp` 中虽然有一些生成 `conf.h` 的残留函数，但没有可见 `main()` 或实际调用链。
- 完整仓库中也没有找到自动生成脚本。

所以更合理的开发模型是：

```text
开发者手工维护 conf.h / conf_PEmap.h
工具链从这些 header 继续往后生成 CSV 和 binary
```

## 修改一个算子时该动哪里

如果只是换 shape 或 task 数量：

```text
csv_generate/conf.h
csv_generate/conf_PEmap.h
spm_data/*
```

如果改变 PE 上的计算算法：

```text
gpdpu_TestOp/task*/subtask*/template/*.cpp
```

如果改变输入输出、DMA 或启动顺序：

```text
riscv/testarm.c
dpuapi/DpuAPI.c
```

如果改变 CSV 到 binary 的编译逻辑：

```text
testcase/common_oper/csv_oper.*
testcase/common_oper/inst_blk_gen.*
testcase/common_oper/graph_extend.*
testcase/common_oper/map/inst_blk_map_bat.*
testcase/common_oper/exe_block_gen.*
testcase/common_oper/task_print.*
```

如果改变模拟设备行为：

```text
common/src
pe/src
其他 DMA/SPM/MICC/router/mem 模块源码
```

