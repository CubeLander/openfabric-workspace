# PE Operand Index Model

这份文档记录当前从恢复源码里观察到的 PE 内 operand 存储结构，以及 CSV 里的
符号 operand tag 如何变成最终 runtime/RTL 指令中的 operand index。

重点结论：

```text
最终指令里没有字符串寄存器名。
CSV 里的 gemm0_input0_0_0 / ALPHA 这类字段只是符号 operand tag。
build_app 会把这些 tag 分配成 PE-local operand RAM index。
每个 PE 有 1536 个 operand slot，组织成 12 个 operand RAM bank，每个 bank 128 项。
最终 operand index = bank * 128 + row。
```

## PE Array

公共头文件给出了 4x4 PE 拓扑：

```c
#define PE_ARRAY_X_LEN (4)
#define PE_ARRAY_Y_LEN (4)
#define PE_AMOUNT (PE_ARRAY_X_LEN * PE_ARRAY_Y_LEN)
```

`common_oper/inst_map_common.cpp` 和 `common_oper/inst_blk_map.cpp` 都使用同一套
row-major 映射：

```c
x = pe_idx / PE_ARRAY_Y_LEN;
y = pe_idx % PE_ARRAY_Y_LEN;
```

所以当前恢复源码里的 PE id 到坐标关系是：

```text
PE id 0  -> (x=0, y=0)  PE00
PE id 1  -> (x=0, y=1)  PE01
PE id 2  -> (x=0, y=2)  PE02
PE id 3  -> (x=0, y=3)  PE03
PE id 4  -> (x=1, y=0)  PE10
...
PE id 15 -> (x=3, y=3)  PE33
```

## PE Resource Limits

`common/src/pe_com_def.h` 给出了每个 PE 的主要资源上限：

```c
#define MAX_INST_BLOCK_AMOUNT_PER_PE (32)
#define MAX_INST_AMOUT_PER_PE (4352)
#define MAX_REGS_AMOUNT_PER_PE (8)

#define MAX_OPERAND_RAM_AMOUNT_PER_PE 1536
#define OPERANDS_RAM_GROUP_NUM 3
#define OPERANDS_RAM_NUM_PER_GROUP 4
#define OPERANDS_RAM_NUM (OPERANDS_RAM_GROUP_NUM * OPERANDS_RAM_NUM_PER_GROUP)
#define OPERANDS_PER_OPERAND_RAM (MAX_OPERAND_RAM_AMOUNT_PER_PE / OPERANDS_RAM_NUM)
```

在默认 `LOW_POWER == 0` 的配置下：

```text
每个 PE:
  inst block slots : 32
  instruction slots: 4352
  scalar regs      : 8
  operand slots    : 1536

operand RAM:
  group count      : 3
  banks per group  : 4
  total banks      : 12
  entries per bank : 128
```

这里的 `MAX_REGS_AMOUNT_PER_PE == 8` 更像普通 scalar register 文件。GEMM
模板里大量 `gemm0_input...` / `gemm0_output...` 使用的是 operand RAM，而不是
这 8 个 scalar reg。

## Operand Index Layout

最终 operand index 的核心公式在 `common_oper/inst_blk_map.cpp`：

```c
uint64_t layout_operand_idx(uint64_t reg_idx) {
    return (reg_idx % OPERANDS_RAM_NUM) * OPERANDS_PER_OPERAND_RAM +
           reg_idx / OPERANDS_RAM_NUM;
}
```

代入默认常量：

```text
OPERANDS_RAM_NUM         = 12
OPERANDS_PER_OPERAND_RAM = 128

bank        = reg_idx % 12
row         = reg_idx / 12
operand_idx = bank * 128 + row
```

也就是说，逻辑上连续分配的 `reg_idx` 会被交错铺到 12 个 RAM bank 上：

```text
logical reg_idx -> operand_idx  bank row
0               -> 0            0    0
1               -> 128          1    0
2               -> 256          2    0
3               -> 384          3    0
4               -> 512          4    0
5               -> 640          5    0
6               -> 768          6    0
7               -> 896          7    0
8               -> 1024         8    0
9               -> 1152         9    0
10              -> 1280         10   0
11              -> 1408         11   0
12              -> 1            0    1
13              -> 129          1    1
14              -> 257          2    1
15              -> 385          3    1
```

所以最终可用 operand index 集合不是简单从 0 连续用到 N，而是：

```text
bank0 : 0..127
bank1 : 128..255
bank2 : 256..383
...
bank11: 1408..1535
```

分配顺序则按 `0,128,256,...,1408,1,129,257,...` 交错前进。这样设计很可能是
为了让连续出现的输入/输出 operand 分散到不同 RAM bank，降低同一 bank 访存冲突。
这是从分配公式推断出的意图，源码没有直接注释说明。

## From CSV Tag To Final Operand Index

CSV 行里的 operand 字段通常长这样：

```text
gemm0_input0_0_0
gemm0_input1_0_7
gemm0_output0_0_3
ALPHA
BET
```

它们不是最终地址，只是符号 tag。转换链路分两层。

第一层在 `common_oper/csv_oper.cpp`：

```text
Csv_Operate::constructOneCsvItem()
  src_reg_idx0_tag = CSV 第 3 列
  src_reg_idxl_tag = CSV 第 4 列
  dst_reg_idx_tag  = CSV 第 5 列
  getRegIdx(tag)   = 生成 CSV block 内临时小编号
```

这一层会把 tag 写进 `Inst`，并暂时填充：

```text
inst.src_operands_idx[0]
inst.src_operands_idx[1]
inst.dst_operands_idx[0]
```

第二层在 `common_oper/inst_blk_map.cpp`：

```text
Task_Resource::fill_reg_idx()
  get_reg_idx(tag, reg_start_idx)
  layout_operand_idx(m_reg_idx_counter + reg_start_idx)
```

这一层才得到最终 PE-local operand index。`fill_reg_idx()` 会覆盖第一层的临时
编号，把最终整数写回 instruction IR。

## Task/App Resource Window

operand index 是 PE-local 的，不是全芯片全局编号。每个 PE 有自己的
`m_reg_counter`。

当前 app/task 资源分配流程是：

```text
start_map_app()
  每个 PE 记录 app 的 reg_start_idx = 当前 PE.m_reg_counter

start_map_task()
  每个 PE 创建 Task_Resource

end_map_task()
  distribute_operand()
    在当前 task 的节点/阶段内按 tag 分配 operand index
  counting_task_resource()
    统计 task 用了多少 operand
  get_app_max_resource()
    app.operand_cnt = max(app.operand_cnt, task.operand_cnt)

end_map_app()
  PE.m_reg_counter = app.reg_start_idx + app.operand_cnt
```

这个细节很重要：同一个 app 内的多个 task slice 当前不是简单把 operand 用量
累加起来，而是按各 task 的最大 operand 需求为 app 预留窗口。也就是说，task0、
task1、task2、task3 的 operand 空间可以在同一个 app window 内复用。runtime
依靠 task/subtask/block 调度保证同一窗口的生命周期合法。

## COPY/COPYT Operand Semantics

普通算术、load/store 和 copy 最终都只写整数 operand index。

`common/src/inst_def.h` 中 RTL 指令字段显示：

```text
CAL/CAL2:
  src_operands_idx0 : 12 bits
  src_operands_idx1 : 12 bits
  dst_operands_idx0 : 12 bits

IMM:
  dst_operands_idx0 : 12 bits

LD/ST/STM:
  dst_operands_idx0 : 12 bits

COPY:
  src_operands_idx0 : 12 bits
  dst_operands_idx0 : 12 bits
  pos_x             : 2 bits
  pos_y             : 2 bits
  block_idx         : 5 bits
```

对 `COPYT`/`COPY` 来说：

```text
src_operands_idx0 是当前/source PE 上的 operand index。
dst_operands_idx0 是目标/child PE 上同名 tag 对应的 operand index。
pos_x/pos_y       是目标 PE 坐标。
block_idx         是当前 COPY 指令所在的 source block。
dst_blocks_idx    在 IR 中记录目标 block，后续用于依赖/配置输出。
```

`fill_copy_inst()` 会通过目标 PE 的 `Task_Resource::retrieve_reg_idx(tag)` 反查
目标 operand index。因此 COPY 指令的两个 operand index 分别属于两个 PE 的
本地 operand RAM 地址空间，它们数值可以相同，也可以不同。

Tensor copy 还会展开成多条底层 COPY。展开时后续 COPY 的目的 operand index
按 bank stride 增加：

```c
dst_operands_idx[0] = first_dst_operand_idx + n * OPERANDS_PER_OPERAND_RAM;
```

默认 `OPERANDS_PER_OPERAND_RAM == 128`，所以这相当于把 tensor operand 的多个
lane/fragment 放到同一 group 内相邻 bank。

## What Are The Final Operand Indices?

如果只问“最终有哪些 operand index”，当前源码给出的答案是：

```text
每个 PE 有 1536 个 PE-local operand index:
  0..1535

它们按 12 个 bank 解释:
  bank = operand_idx / 128
  row  = operand_idx % 128

编译器按逻辑 reg_idx 交错分配:
  operand_idx = (reg_idx % 12) * 128 + reg_idx / 12
```

如果问某个具体 GEMM case 最终实际用了哪些 index，则答案取决于：

```text
1. 当前 PE 上有哪些 graph node 被映射进来。
2. distribute_operand() 遍历这些 node 的顺序。
3. 每个 node 中 ld/cal/flow/st stage 的指令顺序。
4. 每个指令第一次遇到哪些新的 operand tag。
5. app 的 reg_start_idx 是否已经被前一个 app 占用。
```

因此具体 case 的最终 index 是稳定可复现的编译结果，但不应该作为开发者手写
接口暴露。更合理的抽象是：开发者/DSL 使用符号 operand tag，workflow/编译器
根据 PE-local 资源模型统一分配最终 operand index。

## Open Questions

当前仍然需要继续确认的点：

```text
1. 12 个 operand RAM bank 在真实硬件上的读写端口数量和冲突规则。
2. tensor operand group 的硬件语义，尤其 group0/1/2 与 HMMAL 输入输出的关系。
3. LOW_POWER 模式是否会在客户实际环境中启用。
4. COPY 的 flow_ack、dst block 和 hardware dependency scheduler 的精确关系。
5. 8 个 scalar reg 与 operand RAM 在 ISA 层的边界。
```

