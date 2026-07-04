# Chip-level Program Plan

日期：2026-06-28

本文记录 `second_wind` 路线里一个更高层的设计判断：

```text
OpenFabric 不应该让 device 侧计划和 runtime 主控计划各自成为真相源。
它们应该都是同一个 chip-level program plan 的投影。
```

当前讨论从 softmax refactor 触发，但目标不是做一个 softmax-only 结构。目标是为
后续 NoC mesh accelerator 算子编译建立一个稳定边界：同一个 chip-level program
入口同时领导 device 侧模板/镜像、RISC-V 主控程序、runtime package material 和
vendor compatibility exports。

## 背景

当前 refactored softmax 已经把很多事实收进 `SoftmaxDistributedPlan`：

```text
mesh size
task/subtask count
PE list
instance layout
tensor names
tensor shapes
SPM base addresses
base slots
sharding
scratch layout
```

这让 CSV template 和 `instance_conf_info*.bin` 可以从同一个 distributed tensor
memory plan 派生。

但 `conf.h` 和 `conf_PEmap.h` 暴露了另一个问题：RISC-V 主控程序和 graph hook
仍然需要一套 runtime/control 视角的数据，比如 DMA input/output、kernel start
参数、app buffer 形态、PE graph placement 等。

如果我们只做两个平级计划：

```text
DeviceExecutionPlan
RuntimeLaunchPlan
```

那仍然会有同步风险。比如 output tensor 的 device instruction SPM base 是
`16384`，而 RISC-V DMA 头里的 `spmStartAddr[1]` 是 `65536`。这两个值不应该手工
维护两份。它们应该由同一个 memory allocation 决定，然后按不同后端的地址单位
投影出来。

## 设计判断

正确层级应该是：

```text
ChipProgramPlan
  -> DeviceExecutionPlan
  -> RuntimeLaunchPlan
  -> GraphPlan
  -> ArtifactManifest
```

`DeviceExecutionPlan` 和 `RuntimeLaunchPlan` 不是两个 source of truth。它们是
`ChipProgramPlan` 的不同视图。

`ChipProgramPlan` 应该领导这些事实：

```text
Program IO contract
  input/output tensor name, shape, dtype, external memory binding

Chip resource allocation
  tensor/temp lives in which memory scope
  SPM/operand regions
  base allocation and address-unit contract

Work partition
  task/subtask/instance split
  PE ownership
  statement/tile mapping

Device execution intent
  per-PE fiber/template work
  CSV/device image requirements
  base slots, imm offsets, route/reduction behavior

Runtime staging intent
  input/output DMA schedule
  kernel launch order
  app/double-buffer behavior
  runtime-visible address units

Artifact contract
  which vendor files must be emitted
  where generated files live
  which compiler/assembler consumes them
```

从这个角度看，`conf.h` 不是真相源。它只是
`ChipProgramPlan -> RuntimeLaunchPlan -> vendor C header` 的兼容导出。

## 和现有平台的类比

CUDA/HIP 也有 host/device 两侧编译。它们通常通过 compiler driver 把 device
code 分出去编译，再以 fat binary 或 code object 的形式嵌回 host object。用户看
到的是一个 kernel entry 和 launch API，但工具链内部会生成 host launcher 和
device image 两类产物。

Ascend C 的边界更接近我们：host 侧 tiling 根据 shape/layout 计算 tiling data、
block dim、workspace 等，device kernel 消费这些 runtime-visible 参数。host 侧和
device 侧不是各自维护配置，而是服从同一个 op/shape/tiling contract。

DFU3500/SimICT 当前没有把这些东西包装成一个 fatbin。它的真实产物更原始：

```text
RISC-V control program
CSV templates
app*.conf
instance_conf_info*.bin
graph plugin
result/cbuf_file.bin
result/micc_file.bin
runtime package material
```

所以 OpenFabric 需要的不是照搬 CUDA/HIP 的 binary container，而是建立自己的
package compiler boundary：

```text
ChipProgramPlan
  -> host/control-side artifacts
  -> device-side artifacts
  -> vendor assembler/package inputs
```

## 投影关系

一个事实只在顶层分配一次，然后按后端投影。

例子：output tensor SPM allocation。

```text
ChipProgramPlan:
  tensor "softmax0_output0"
  memory scope: SPM
  base allocation: 16384
  allocation unit: device instruction base unit

DeviceExecutionPlan projection:
  instance base row slot uses 16384
  CSV memory refs use base slot + imm

RuntimeLaunchPlan projection:
  output DMA spmStartAddr uses 65536
  derived by converting allocation base into runtime DMA address unit
```

这比在 runtime plan 里手写 `65536` 更符合唯一真相源原则。

## 当前 softmax 的落地形态

短期不需要一次性设计完整 IR。可以先把现有结构扶到正确层级：

```text
make_softmax_chip_program_plan()
  -> plan.device()
  -> plan.runtime()
  -> plan.graph()
```

当前已经存在的 `SoftmaxDistributedPlan` 可以先被视为 device-facing projection。
下一步增加一个很薄的 `SoftmaxChipProgramPlan` 包住它：

```cpp
struct SoftmaxChipProgramPlan {
  SoftmaxDistributedPlan device_plan;
  SoftmaxRuntimeLaunchPlan runtime_plan;

  const SoftmaxDistributedPlan &device() const;
  const SoftmaxRuntimeLaunchPlan &runtime() const;
};
```

然后现有 writers 不需要马上大改，只改变入口：

```cpp
SoftmaxChipProgramPlan plan = make_softmax_chip_program_plan();

vendor_write_app_conf_files(plan.device());
vendor_write_instance_config_files(plan.device(), SoftmaxInstanceBaseRowBuilder());
vendor_write_runtime_headers(plan);
```

这样可以先建立顶层入口，再逐步把重复事实吸收到 chip-level plan 中。

## Artifact 后端

目标后端可以这样分：

```text
Device backend
  task*/subtask*/template/*.csv
  instance_conf_info_file*.bin
  instance_conf_info_for_rtl_file*.bin
  app*.conf

Runtime backend
  conf.h compatibility export
  RISC-V control-program inputs
  future runtime launch table

Graph backend
  conf_PEmap.h compatibility export
  graph hook source or generated graph data

Package backend
  common_oper/build_app input bundle
  result/cbuf_file.bin
  result/micc_file.bin
```

`conf.h` 和 `conf_PEmap.h` 应该先作为 compatibility exports 生成，而不是作为维护源
保留。等生成等价后，再缩小下游消费者：

```text
RISC-V consumes generated runtime config
graph hook consumes generated graph config
legacy conf.h/conf_PEmap.h disappears from maintained source
```

## 实现路线

建议按最小风险推进：

1. 为 softmax 引入 `SoftmaxChipProgramPlan`，内部先包现有
   `SoftmaxDistributedPlan` 和一个小的 runtime launch binding。

2. 让 `device_program/main.cpp` 从 `make_softmax_chip_program_plan()` 开始。
   现有 device writers 先继续吃 `plan.device()`。

3. 增加 runtime header writer，从 `SoftmaxChipProgramPlan` 生成当前
   `conf.h` / `conf_PEmap.h` 的兼容内容。

4. 在 `csv_generate` 分支生成这些头文件，停止从源码树复制维护版头文件。

5. 用文本对比和最终二进制/运行结果对比确认兼容 export 没有改变行为。

6. 再考虑把 graph hook 和 RISC-V 程序改成消费更小、更明确的 generated config。

## 不做什么

当前阶段不应该：

```text
把旧 B-line final-binary generator 恢复为默认路线
让 conf.h 重新成为 source of truth
把 RuntimeLaunchPlan 和 DeviceExecutionPlan 设计成平级手写配置
在没有 binary/behavior 对比的情况下清理 vendor compatibility 字段
```

## 工作原则

OpenFabric 的 chip-level program plan 应该是唯一权威入口：

```text
operator intent
  + target chip model
  + external IO binding
  -> ChipProgramPlan
  -> device projection
  -> runtime projection
  -> graph projection
  -> vendor package artifacts
```

后端可以有很多，vendor 兼容文件也可以很多，但每个 shape、placement、memory
allocation、task/PE ownership、runtime binding 都应该能追溯回这个顶层计划。

