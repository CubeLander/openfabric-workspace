# SPM 与 operand RAM 数据通路

这篇聚焦数据面：SPM 如何作为片上数据缓冲层工作，operand RAM 如何作为 PE 工作台，
以及 LD/ST/COPY 如何在它们之间搬运数据。

## 1. SPM：片上数据缓冲层

SPM 是 PE 可以通过 transfer unit 访问的数据存储层。它处在 DRAM 和 PE operand
RAM 之间。

核心定义：

```c
#define SPM_BUFFER_NUM 2
#define SPM_BANK_NUM 8
#define SPM_BLOCK_NUM_PER_BANK 32
#define IO_CHANNEL_PER_SPM_BANK 4
#define SPM_SIZE ((1UL << 20) * 4)      // 4 MiB
#define SPM_CONST_SIZE (1UL << 18)      // 256 KiB
```

DMA 本地地址布局里还能看到双 buffer：

```c
#define SPM_BUF0_BASE 0x00000000
#define SPM_BUF1_BASE 0x00400000
#define SPM_MAX       (0x00840000 - 1)
```

这说明 SPM 侧至少有两个 buffer 区，典型用途是输入/输出 ping-pong 或多
app/buffer 轮换。

RISC-V 侧把数据从 DRAM 搬到 SPM 用：

```c
DPU_SpmTransfer(...)
```

底层会写 DMA 寄存器：

```c
DMA_DDR_ADDR0/1
DMA_INACC_ADDR0/1
DMA_X_SLICE0/1
DMA_Y_SLICE0/1
DMA_X_FULL0/1
DMA_TRANS_DIREC0/1
DMA_START0/1
```

方向：

```c
DMA_TRANS_DIREC = 1  // DDR -> device/SPM
DMA_TRANS_DIREC = 0  // SPM -> DDR
DMA_TRANS_DIREC = 2  // DDR -> CBUF/MICC 类内部区域
```

SPM 不是 cache。输入数据必须显式 DMA 进来，输出数据也必须显式 DMA 回去。

## 2. PE operand RAM：真正执行指令的工作区

operand RAM 是 PE 内部的本地 SIMD operand 存储。它更接近 GPU register file /
local scratchpad，而不是 CPU cache。

核心定义：

```c
#define MAX_REGS_AMOUNT_PER_PE 8
#define MAX_OPERAND_RAM_AMOUNT_PER_PE 1536
```

PE 私有结构里：

```c
unit_t operands[MAX_REGS_AMOUNT_PER_PE + MAX_OPERAND_RAM_AMOUNT_PER_PE];
```

`unit_t` 是 128-byte SIMD 容器：

```c
typedef union {
    int fix[32];
    unsigned int ufix[32];
    float flt[32];
    unsigned short flt_16[64];
    char fix_8[128];
    unsigned char ufix_8[128];
} unit_t;
```

所以：

```text
1 operand slot = 1 unit_t = 128 bytes
1536 operand slots = 1536 * 128B = 192 KiB / PE
```

operand RAM 的组织：

```c
#define OPERANDS_RAM_GROUP_NUM 3
#define OPERANDS_RAM_NUM_PER_GROUP 4
#define OPERANDS_RAM_NUM (3 * 4)              // 12
#define OPERANDS_PER_OPERAND_RAM (1536 / 12)  // 128
```

也就是：

```text
每 PE 有 12 个 operand RAM bank
每 bank 有 128 个 unit_t 槽
每槽是 128B SIMD 数据
```

编译器会把 CSV 中的符号 operand 分配到这些槽里。当前还原出的映射函数是：

```c
physical_idx = (logical_idx % OPERANDS_RAM_NUM) * OPERANDS_PER_OPERAND_RAM
             + logical_idx / OPERANDS_RAM_NUM;
```

这是一种 bank-interleaving：连续 logical operand 会分散到不同 bank，降低
bank conflict。

## 3. 指令如何在 operand RAM 上工作

一条 PE 指令通常不携带 DRAM 地址，而是携带 operand index：

```c
src_operands_idx[0]
src_operands_idx[1]
dst_operands_idx[0]
```

这些 index 指向 PE 本地 operand RAM。

因此普通计算指令的数据流是：

```text
read operands[src0]
read operands[src1]
compute in fix/flt/fdiv/tensor pipeline
write operands[dst0]
```

例如：

```csv
FMUL,FMUL11,FP0_input,rLog2E,FP0_input,,,1
FEXP2,FEXP213,FP0_input,,FP0_input,,,1
FADD,FADD14,FP0_input,sum_tmp,sum_tmp,,,1
```

实际效果是：

```text
operands[FP0_input] = operands[FP0_input] * operands[rLog2E]
operands[FP0_input] = exp2(operands[FP0_input])
operands[sum_tmp]   = operands[FP0_input] + operands[sum_tmp]
```

这里每个 operand 都是 SIMD 向量，不是 scalar。

## 4. SPM 和 operand RAM 之间的通信

LD/ST 指令负责在 SPM 和 operand RAM 之间搬数据。

从 `mesh_com_def.h` 的消息结构看，LD/ST 会走 SPM message：

```text
PE2SPM_LOAD_REQ
SPM2PE_LOAD_DATA
PE2SPM_STORE_REQ
SPM2PE_STORE_ACK
```

load 请求包含：

```c
spm_addr
load_type
simd_mode
INT8_offset
shift_cnt
shift_reg_idx
mask_enable
ld_mask
return_dst.operand_idx
return_dst.block_idx
return_dst.subtask_idx
return_dst.task_idx
```

store 请求包含：

```c
spm_addr
store_type
value
return_dst
mask
mask_enable
ld_mask
```

所以 LD/ST 的语义是：

```text
LD:
  PE transfer unit 发送 SPM load request
  SPM 返回 SIMD data
  PE 写入 operand RAM dst slot

ST:
  PE 从 operand RAM 读 value
  transfer unit 发送 SPM store request
  SPM 写入片上数据区
  返回 store ack
```

CSV 中的 `HLDT/HSTT/ILDMT` 是编译层伪指令，最终会展开/降级成 `LDN/LDM/STD`
等底层 LD/ST 指令。

## 5. PE 到 PE：operand RAM 之间的通信

PE-to-PE 通信由 `COPY` / flow stage 负责。

消息类型：

```text
PE2PE_COPY_DATA
PE2PE_ACTIVE
PE2PE_ACK
PE2PE_FLOW_ACK
```

copy data message：

```c
typedef struct _pe2pe_copy_data_msg_t {
    unit_t value;
    uint64_t operand_idx;
    uint64_t block_idx;
    uint64_t subtask_idx;
    uint64_t task_idx;
    position_t pe_dst;
    uint64_t ld_mask;
    uint64_t addr;
} pe2pe_copy_data_msg_t;
```

这说明 COPY 不是"写 SPM 再读 SPM"，而是：

```text
源 PE operand RAM
  -> PE2PE mesh
  -> 目标 PE operand RAM
```

graph node 之间的依赖边如果需要跨 PE 传数据，会在 flow stage 里补 copy 指令。
copy 指令里会写：

```text
src operand idx
dst operand idx
dst PE pos_x/pos_y
dst block_idx
flow_ack
```

因此可以说，**算子内部的中间结果主要在 operand RAM 里流动；跨 PE 时通过 PE2PE
mesh 直接从一个 operand RAM 搬到另一个 operand RAM。**

## 6. softmax 里的内存流

以当前 `softmax_1` 为例，输入输出 shape 是 `{64,512}`，每个 PE 处理一行的
一部分/一行的 vector 化片段。

### 启动前

```text
input_data.bin
  -> DDR SPM_DDR_ADDR + input offset
  -> DPU_SpmTransfer
  -> SPM input region
```

指令和配置：

```text
cbuf_file.bin -> DDR CBUF_DDR_ADDR -> CBUF
micc_file.bin -> DDR MICC_DDR_ADDR -> MICC
```

### subtask1

```text
HLDT:
  SPM input -> operand RAM

H2FP/FMUL/FMIN/FEXP2/FADD/SHFL:
  operand RAM -> compute pipeline -> operand RAM

HSTT:
  operand RAM sum_tmp -> SPM SUM intermediate region
```

### subtask2

```text
ILDMT:
  SPM SUM intermediate region -> operand RAM

FADD/FDIV/FP2H/SHFL:
  operand RAM -> compute pipeline -> operand RAM

HSTT:
  operand RAM output vector -> SPM output region
```

### 结束后

```text
SPM output region
  -> DPU_SpmTransfer
  -> DDR output area
  -> result check / host output file
```

## 交叉阅读

- [存储层次总览](storage-hierarchy-overview.md)
- [../pe-microarchitecture/pe-register-architecture.md](../pe-microarchitecture/pe-register-architecture.md)
- [../pe-microarchitecture/simd-lane-interpretation.md](../pe-microarchitecture/simd-lane-interpretation.md)
