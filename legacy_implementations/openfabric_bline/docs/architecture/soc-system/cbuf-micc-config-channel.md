# CBUF 和 MICC：指令/配置通道

这篇聚焦 CBUF 和 MICC 这两个控制面通道。它们不是普通数据计算区，而是承载
device 执行所需的配置、指令和调度材料。

## 1. device local address map

CBUF/MICC 和 SPM 是同一个 device local address map 里的相邻区域；从功能语义
上看，它们更像和 SPM 平行的片上模块，而不是 SPM 内部的一段普通数据 buffer。
源码里 `CBUF_INST_BASE = SPM_MAX + 1`、`MICC_BASE_ADDR = CBUF_ISTC_CONST_MAX + 1`
说明它们在内部地址空间中连续排布，但 DMA API 会把 SPM、CBUF、MICC 当成不同
目的区域使用。

```text
device local address map:

0x00000000 ... SPM_MAX
  SPM data scratchpad

SPM_MAX + 1 ... CBUF_ISTC_CONST_MAX
  CBUF instruction / exeBlock / instance backing store

CBUF_ISTC_CONST_MAX + 1 ... MICC_SUB_MAX
  MICC task / subtask configuration area
```

所以如果从"地址"角度看，CBUF/MICC 接在 SPM 后面；如果从"硬件职责"角度看，
SPM 负责数据，CBUF 负责指令和 block/instance 材料，MICC 负责任务配置和调度控制。

## 2. 全局结构 vs PE 私有

从当前源码看，**CBUF/MICC 更像 tile 级共享结构，而不是每个 PE 私有一份**。不过
CBUF 内部内容会按 PE/block 分片，最后下发到各 PE 的私有执行状态里。

可以这样理解：

```text
CBUF:
  tile 级 instruction/config backing store
  里面存放全 PE 的指令、exeBlock 配置、instance 配置
  内容按 PE/block/instance 编排

MICC:
  tile 级任务/控制器
  持有 task/subtask 配置
  负责启动 task、发送 PE 配置/指令/active 消息

PE:
  每个 PE 有自己的 inst_list[]
  每个 PE 有自己的 exe_blocks_ctrl[]
  每个 PE 有自己的 operand RAM
```

所以不是：

```text
PE0: CBUF + MICC
PE1: CBUF + MICC
...
```

而更像：

```text
          MICC controller
                |
          shared CBUF region
                |
          control / router mesh
      +---------+---------+
      |         |         |
     PE0       PE1      ... PE15
  inst_list  inst_list      inst_list
  operand    operand        operand
  RAM        RAM            RAM
```

CBUF 是共享 backing store；PE 私有的是被装载/分发后的 `inst_list`、
`exe_block_manage` 和 operand RAM。

## 3. 生成阶段

```text
simulator_bin/insts_file.bin
simulator_bin/exeblock_conf_info_file.bin
simulator_bin/instance_conf_info_file.bin
  -> result/cbuf_file.bin

simulator_bin/tasks_conf_info_file.bin
simulator_bin/subtasks_conf_info_file.bin
  -> result/micc_file.bin
```

RISC-V/control 程序中：

```c
DPU_CbufTransfer((void*)&inst_in_mem);
DPU_MiccTransfer((void*)&conf_in_mem);
```

其中：

```c
inst_in_mem = CBUF_DDR_ADDR;
conf_in_mem = MICC_DDR_ADDR;
```

## 4. CBUF DMA 装载

`DPU_CbufTransfer()` 通过 DMA 把 DDR 里的 CBUF payload 搬到片上 CBUF 布局：

```c
DMA_INACC_ADDR0 = CBUF_INST_BASE;
DMA_INACC_ADDR1 = CBUF_BLCK_BASE;
```

也就是至少分成：

- instruction 区：`CBUF_INST_BASE`
- exeBlock config 区：`CBUF_BLCK_BASE`
- instance config 区：另有 `CBUF_ISTC_BASE`

`common/src/dma_com_def.h` 中的 CBUF/MICC 地址布局也证明了这一点：

```c
CBUF_INST_BASE = SPM_MAX + 1
CBUF_INST_MAX  = CBUF_INST_BASE
               + sizeof(inst_t) * MAX_INST_AMOUT_PER_PE * PE_AMOUNT - 1

CBUF_BLCK_BASE = CBUF_INST_MAX + 1
CBUF_BLCK_MAX  = CBUF_BLCK_BASE
               + sizeof(exeBlock_conf_info_t)
                 * MAX_INST_BLOCK_AMOUNT_PER_PE * PE_AMOUNT - 1

CBUF_ISTC_BASE = CBUF_BLCK_MAX + 1
CBUF_ISTC_MAX  = CBUF_ISTC_BASE
               + sizeof(instance_conf_info_t) * MAX_INSTANCE_AMOUNT - 1
```

这里的 `* PE_AMOUNT` 很重要：instruction 区和 exeBlock 区不是某个 PE 私有，
而是一个全局 CBUF 区中容纳所有 PE 的材料。前面 `task_print.cpp` 生成
`insts_file.bin` 时也是按 PE 顺序拼接：

```text
PE0 instruction slots
PE1 instruction slots
...
PE15 instruction slots
```

每个 PE 的本地指令槽上限是：

```c
MAX_INST_AMOUT_PER_PE = 4352
```

所以 CBUF instruction 区可以看成：

```text
CBUF_INST[PE_AMOUNT][MAX_INST_AMOUT_PER_PE]
```

exeBlock 配置区类似：

```text
CBUF_BLOCK[PE_AMOUNT][MAX_INST_BLOCK_AMOUNT_PER_PE]
```

## 5. MICC DMA 装载与控制消息

`DPU_MiccTransfer()` 则把 task/subtask 配置搬到：

```c
DMA_INACC_ADDR0 = MICC_BASE_ADDR;
```

启动时：

```c
DPU_Kernel_Start(inst_reload, TASK_NUM, instance_base, ...)
```

它会写 MICC 寄存器：

```c
MICC_INSTANCE_BASE
MICC_BUFx_INST
MICC_BUFx_TASK
MICC_BUFx_START
```

所以 CBUF/MICC 负责"让 PE 知道要执行哪些 task/subtask/exeBlock/inst"，
不是算子输入数据本身。

## 6. MICC 到 PE 的控制消息

`mesh_com_def.h` 里有 MICC 到 PE 的控制消息：

```text
MICC2PE_CONF
MICC2PE_INST
MICC2PE_ACTIVE
```

对应的消息结构包括：

```c
micc2pe_exeBlock_config_msg_t {
    exe_block_ctrl_t exe_block_ctrl;
    position_t pe_dst;
}

micc2pe_inst_msg_t {
    uint64_t block_idx[4];
    inst_t inst[4];
    position_t pe_dst;
}

micc2pe_active_msg_t {
    instance_idx;
    subtask_idx;
    task_idx;
    instance_conf_info;
    position_t pe_dst;
}
```

这说明 MICC 会把 CBUF/MICC 中的全局材料按 `pe_dst` 发给目标 PE。PE 侧则有
自己的私有结构：

```c
inst_t inst_list[MAX_INST_AMOUT_PER_PE];
exe_block_ctrl_t exe_blocks_ctrl[MAX_INST_BLOCK_AMOUNT_PER_PE];
```

因此 CBUF/MICC 和 PE 私有状态的关系是：

```text
CBUF global instruction/config material
  -> MICC/control mesh 按 PE 发送
  -> PE.inst_list / PE.exe_blocks_ctrl
  -> PE 执行时按 block/stage pc 取本地 inst_list
```

## 交叉阅读

- [存储层次总览](storage-hierarchy-overview.md)
- [../runtime-model/vendor-exeblock-subtask-struct.md](../runtime-model/vendor-exeblock-subtask-struct.md)
- [../instruction-encoding/instruction-capacity-model.md](../instruction-encoding/instruction-capacity-model.md)
