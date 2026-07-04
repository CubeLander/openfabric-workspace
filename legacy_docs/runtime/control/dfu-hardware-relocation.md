# 基于硬件的可重定位 Kernel 路线与模拟器开放需求

日期：2026-06-02

本文记录一个更直接的路线判断：如果基于硬件 ABI 设计现代 runtime，可重定位 kernel 的本质并不复杂；真正复杂的是当前闭源、固定文件入口的 simulator/runtime 把地址绑定过程包死了。

## 1. 核心结论

当前底层 ABI 已经支持一种自然的重定位模式：

```text
LD/ST 指令:
  base_addr_idx + imm

instance_conf:
  base_addr[base_addr_idx]

实际访问:
  effective_addr = instance_conf.base_addr[base_addr_idx] + imm
```

因此可重定位 kernel 的硬件本质是：

```text
指令不动；
task/subtask/exeBlock 不动；
每次调用只换 instance_conf.base_addr[] 和 DMA src/dst。
```

也就是说，真正需要动态变化的是“本次调用的地址表”，不是 kernel 指令本身。

## 2. 基于硬件的理想调用流程

如果我们有硬件级 runtime/driver 控制权，kernel 可以这样执行：

```text
初始化 / 首次加载:
  1. 编译 kernel，得到 inst/exeBlock/task/subtask/instance template
  2. 把 inst/exeBlock 装入 CBUF
  3. 把 task/subtask 装入 MICC

每次调用:
  1. runtime 为 input/output/scratch 分配 SPM base
  2. runtime 写入 instance_conf.base_addr[]
  3. DMA 把 input tensor 搬到 input_spm_base
  4. 写 MICC start/task 寄存器启动
  5. 等待完成
  6. DMA 把 output_spm_base 搬回 output tensor
```

其中 kernel 指令只描述访问模式：

```text
LD input_slot  + row_offset + chunk_offset
ST output_slot + row_offset + chunk_offset
```

运行期只负责绑定：

```text
input_slot  -> 本次 input_spm_base
output_slot -> 本次 output_spm_base
scratch_slot -> 本次 scratch_spm_base
```

所以同一个 kernel 可以被不同 tensor buffer 重复调用。

## 3. 这条路线要求 runtime/driver 具备的能力

最小硬件级能力：

```text
1. 可以单独装载或更新 CBUF/MICC/instance 区。
2. 可以把 DMA 目的地址设为任意合法 SPM base。
3. 可以把 DMA 源/目的地址绑定到本次 tensor buffer。
4. 可以在不重新编译 kernel 的情况下启动 MICC。
5. 可以等待 DMA 和 MICC 完成，并读取错误状态。
```

更理想的能力：

```text
1. inst/exeBlock/task/subtask 可缓存，后续 launch 不重复装载。
2. instance_conf 可单独更新。
3. 支持 inst_reload=0 或等价机制。
4. driver/runtime 可以维护 kernel handle 和 call frame。
5. 支持 profiling timestamp 和错误定位。
```

如果这些能力存在，那么可重定位 kernel 就是一件相对直接的 runtime 工程：

```text
CompiledKernel = 固定执行程序
CallFrame = 本次地址绑定
```

## 4. 现有闭源 simulator/runtime 的问题

当前 simulator/runtime 的外部形态更像固定 case 执行器：

```text
config/cbuf_file.bin
config/micc_file.bin
config/input_data.bin
config/riscv_program
  -> run_app_riscv.sh
      -> 闭源 runtime/module/simulator
```

这套入口对芯片功能验证足够，但对现代调用模型不够友好：

```text
地址、输入、kernel、RISC-V 控制程序都通过固定文件和固定 DDR 地址进入。
runtime 何时读取文件、如何映射 DDR、如何装载 CBUF/MICC/SPM 都在闭源部分。
我们无法确认是否能局部更新 instance_conf。
我们无法确认 inst_reload=0 的真实语义。
我们无法直接实现 kernel handle / call frame / buffer residency。
```

因此，如果不改现有 runtime，只能做一种别扭的文件级重定位：

```text
每次调用前:
  patch cbuf_file.bin 里的 instance 区
  patch input_data.bin 或 DDR 镜像
  重新让闭源 runtime 读文件
  重新跑固定入口
```

这不是现代 runtime，而是对固定验证流程的外层包装。它可以用于实验，但不适合作为长期推理软件栈。

## 5. 为什么需要甲方开放模拟器/runtime

我们希望为 DFU 设计现代调用模型，至少需要知道以下事实：

### 5.1 CBUF/MICC/SPM 装载语义

需要确认：

```text
CBUF 各区真实布局。
MICC 各区真实布局。
instance_conf 是否属于 CBUF instance 区。
是否支持单独更新 instance_conf。
MICC 启动时是否重新读取 instance_conf。
inst_reload=0 到底保留哪些状态。
```

这些直接决定可重定位 kernel 是否能高效实现。

### 5.2 DMA 和地址空间语义

需要确认：

```text
DMA source/destination 可配置范围。
SPM base 地址单位。
instance_conf.base_addr[] 地址单位。
LD/ST imm 地址单位。
DDR/SPM/CBUF/MICC 地址空间映射关系。
真实硬件和 simulator 是否一致。
```

这些决定 runtime patch 地址是否正确。

### 5.3 同步和错误处理

需要确认：

```text
DMA done 状态如何产生。
MICC finish 状态如何产生。
PE 执行错误如何反馈。
非法地址/越界/未完成是否有状态寄存器。
是否有 profiling counter。
```

没有这些，runtime 很难做可靠的 launch/sync/error handling。

### 5.4 simulator 和真实硬件的一致性

我们需要把 simulator 作为开发期 reference backend。只有开放 simulator/runtime，才能：

```text
在没有板卡时验证 runtime 调用模型。
对比 simulator backend 和 hardware backend。
定位地址 patch、DMA、MICC 调度错误。
做 PyTorch differential test 和 CI。
```

如果 simulator 只提供闭源固定入口，就无法成为现代软件栈的开发平台。

## 6. 对甲方的沟通表述

可以这样向甲方说明：

```text
我们目前已经识别出 DFU 底层 ABI 具备可重定位 kernel 的基础：
PE 访存指令通过 base_addr_idx + imm 访问，
instance_conf.base_addr[] 可以作为运行期地址表。

如果要把当前验证型工具链升级为面向 PyTorch/大模型推理的现代 runtime，
关键不是每次重新编译 kernel，
而是建立 kernel handle + call frame 的调用模型：
kernel 指令固定，调用时只绑定 input/output/scratch 的地址。

但是当前 simulator/runtime 的文件入口和装载逻辑是闭源的，
我们无法确认 CBUF/MICC/instance 的真实装载语义，
也无法验证 instance_conf 是否可以单独更新、inst_reload=0 的真实行为、
DMA/SPM 地址单位和同步错误处理。

因此，希望甲方开放 simulator/runtime 相关源码或至少开放等价接口文档，
使我们能够基于硬件真实语义设计 Linux driver、runtime ABI 和 PyTorch 调用层。
否则我们只能在固定 case 文件入口外层做包装，
这会限制性能、可靠性和后续模型部署能力。
```

## 7. 我们希望甲方提供的材料

优先级从高到低：

```text
1. simulator/runtime/module 源码，尤其是读取 config 文件、映射 DDR、装载 CBUF/MICC/SPM、启动 MICC 的部分。
2. CBUF/MICC/SPM 地址布局和装载协议文档。
3. instance_conf/task_conf/subtask_conf/exeBlock_conf 的硬件消费语义。
4. DMA 寄存器、模式、地址单位、同步/错误状态文档。
5. inst_reload、task_enable、buf0/buf1 的准确语义。
6. Linux 板卡上的 DFU MMIO/DMA/interrupt 寄存器表。
7. simulator 与真实硬件差异说明。
```

如果源码不能完全开放，最低限度也需要：

```text
1. 可调用的 simulator runtime API，而不是固定文件入口。
2. 支持 load_kernel / patch_instance / dma_copy / launch / wait 的接口。
3. 明确每个接口对应的硬件语义。
```

## 8. 这条路线的最终目标

我们希望把 DFU 调用模型从：

```text
固定 case 文件
  -> 固定 runtime 入口
      -> 固定地址执行
```

升级为：

```text
CompiledKernel
  -> loaded once
      -> CallFrame(input/output/scratch addresses)
          -> launch
              -> result
```

这才是后续支持：

```text
torch.ops.dfu.*
FX graph lowering
Qwen3-8B 多算子流水
KV cache residency / swap
多芯片调度
```

的基础。

