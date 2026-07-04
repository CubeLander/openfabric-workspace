# CSV 到二进制打包流程

## CSV 是什么

CSV 是这个工具链里的类汇编中间表示。它不是最终机器码，也不是纯数据表。

每个 PE 会有自己的 CSV，例如：

```text
task0/subtask1/template/0.csv
task0/subtask1/template/1.csv
...
```

CSV 中会描述 load、compute、copy/flow、store 等指令。后面的 `common_oper` 会把这些文本指令解析成内部 `inst_t`，再经过映射和打包生成 simulator/RTL 所需二进制。

## 入口位置

每个 subtask 的编译入口通常在：

```text
task*/subtask*/build_so/run.sh
```

它依赖：

```text
task*/subtask*/template/*.csv
testcase/common_oper/libapp_build_common.so
common/src/libcommon.so
```

构建出来的 subtask shared object / packer 会调用 common_oper 中的公共编译逻辑。

## common_oper 的角色

`testcase/common_oper` 是 CSV 到 DPU packed binary 的核心工具层。它做的事情包括：

- 解析 CSV；
- 生成 instruction block；
- 建 graph；
- 将 graph node 映射到 PE；
- 分配和修正寄存器资源；
- 修正 copy 指令目的地；
- 生成 exe_block metadata；
- 写 simulator_bin 和 RTL bin。

可以把它理解成这个项目真正的“后端汇编器 + mapper + packer”。

## 主要阶段

### 1. Csv_Operate

`Csv_Operate` 读取 `template/*.csv`，把文本形式的 op 转成内部指令结构。

它会处理：

- op name；
- 源/目的寄存器；
- PE destination；
- immediate；
- iteration condition；
- 额外字段。

这一步会把类似：

```text
FADD
FEXP2
HSTT
COPY
LCOPY
```

这样的文本 op 转成 `inst_t` 中的 opcode / field。

注意：CSV 中的寄存器名或编号还不是最终硬件资源分配结果。后面的 mapper 还可能改写。

### 2. Inst_Block

`Inst_Block::process()` 把 CSV 指令分阶段组织成 instruction block template。

根据现有代码观察，它假设 CSV 指令顺序已经按阶段排列：

```text
LD stage
CAL / FDIV stage
FLOW / COPY stage
ST stage
```

如果 CSV 顺序不符合预期，可能报类似：

```text
block inst amount != csv inst amount
```

所以 CSV 生成模板必须遵守后端期望的 stage ordering。

### 3. Graph_Extend

`Graph_Extend` 把 instruction block template 扩展成 graph node。

它的作用大致是：

```text
block template
  -> graph nodes
  -> node dependencies
  -> per-node instruction block
```

这个阶段开始把“一个模板”实例化为实际任务图。

### 4. inst_blk_map_bat

`inst_blk_map_bat` 是当前 `common_oper/run.sh` 默认选择的 mapper：

```sh
map_algorithm=inst_blk_map_bat
cp map/${map_algorithm}.cpp ./inst_blk_map.cpp
cp map/${map_algorithm}.h ./inst_blk_map.h
```

它负责：

- 按图深度或资源约束排序 node；
- 将 node 放到具体 PE；
- 分配/记录 task 级和 app 级资源；
- 修正 copy / local copy 指令；
- 统计每个 PE 的指令 RAM、寄存器、operand 等资源；
- 维护 task/app resource offset。

简单说，CSV 里描述的是相对抽象的 PE 指令模板，`inst_blk_map_bat` 会把它放到更具体的硬件资源坐标里。

### 5. exe_block_gen

`exe_block_gen` 负责生成每个 PE 的 executable block metadata。

它会处理：

- per-PE exe_block index；
- block predecessor/successor；
- `stages_start_pc`；
- 每个 PE 的指令 offset。

这一步把图和指令块组织成 DPU 执行时可调度的 block 结构。

### 6. task_print

`task_print` 是最终写文件阶段。

它有两类输出路径：

1. simulator path：写模拟器直接消费的结构体二进制。
2. RTL path：按 opcode family 转成更窄的 RTL encoding。

常见输出包括：

```text
simulator_bin/task_conf_info_file.bin
simulator_bin/subtask_conf_info_file.bin
simulator_bin/exeBlock_conf_info_file.bin
simulator_bin/inst_file.bin
rtl_bin/*
```

不同指令族会被打包成不同 RTL struct：

- load/store；
- copy；
- immediate；
- special function / shuffle / transform；
- ordinary compute。

因此 RTL 输出不是简单 dump `inst_t`，而是第二次 packing。

## 输出物如何继续流动

subtask 编译阶段输出的文件最终会被 app-level packaging 收集，形成：

```text
result/cbuf_file.bin
result/micc_file.bin
result/input_data.bin
```

RISC-V 控制程序后续会通过 DpuAPI 让模拟设备加载这些文件对应的内存区域：

```text
CBUF_DDR_ADDR
MICC_DDR_ADDR
SPM_DDR_ADDR
SPM_RST_DDR_ADDR
```

## 对开发者的实际含义

修改 `template/*.cpp` 后，CSV 会重新生成；但只有经过 `common_oper` 之后，它才会变成真正可执行的 DPU task 配置。

调试时应该区分：

- CSV 生成错：看 `gpdpu_TestOp/task*/subtask*/template/*.cpp` 和生成的 `*.csv`。
- CSV 解析/汇编错：看 `csv_oper.*`、`inst_blk_gen.*`。
- PE mapping 或 copy 目的地错：看 `inst_blk_map_bat.*`。
- 输出 binary 结构错：看 `task_print.*` 和 `simulator_bin/*`。

