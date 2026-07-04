# DPU 指令集和执行模型阶段性还原

这篇笔记记录当前能从可见源码中还原出的 device 指令集、CSV 到二进制的编译路径，以及 PE 侧执行方式。结论先行：**指令编码和打包路径基本可从源码确认；PE 内部真正执行每条指令的 C 实现目前只看到 OCR 头文件，执行细节需要继续补源码或用运行结果校验。**

## 1. 当前可见程度

可直接确认的部分：

- 指令助记符、opcode、unit 类型、latency 定义。
- CSV 指令行如何解析成 `Inst` / `inst_t`。
- CSV 如何按阶段拆成 `LD -> CAL -> FLOW -> ST`。
- `inst_t` 如何输出到 simulator 用的 `insts_file.bin`。
- `inst_t` 如何转换成 RTL 用的 64-bit bitfield 指令，输出到 `cbufData_inst.bin`。
- `HLDT/HSTT/ILDMT/COPYT/LCOPYT` 等伪指令如何展开/降级成真实硬件 opcode。

只能部分推断的部分：

- PE pipeline 每周期如何 issue、stall、forward。
- ALU/FPU/FDIV/Tensor 单元内部如何计算。
- LD/ST/COPY 访问 SPM/CBUF/PE-to-PE message 的完整行为。

原因是 `pe/src` 当前只有 OCR 头文件，缺少对应 `.c/.cpp` 实现；不过这些头文件已经暴露出执行模型骨架。

## 2. 指令集定义

核心文件：

```text
simict3500final/gpdpu/users/risc_nn_riscv/common/src/inst_def.h
simict3500final/gpdpu/users/risc_nn_riscv/common/src/inst_def.c
```

`inst_def.h` 里定义了 unit 类型：

```c
FIX_UNIT_INST_TYPE    = 0x1
FLT_UNIT_INST_TYPE    = 0x2
FDIV_UNIT_INST_TYPE   = 0x4
LD_UNIT_INST_TYPE     = 0x8
FLOW_UNIT_INST_TYPE   = 0x10
ST_UNIT_INST_TYPE     = 0x20
TENSOR_UNIT_INST_TYPE = 0x40
```

并定义：

```c
CAL_INST_TYPE  = FIX | FLT | FDIV | TENSOR
TRAN_INST_TYPE = LD | FLOW | ST
```

这说明指令天然被分成计算类和传输类。后续 `Inst_Block::process()` 正是用这个类型把一个 CSV block 拆成阶段。

opcode 空间里，真实硬件 opcode 在 `0..255`，例如：

```text
0x01  ADD
0x22  IMM
0x24  FADD
0x26  FMUL
0x29  SHFL
0x40  LDN
0x41  LDM
0x80  STD
0xc0  COPY
0xd0  FSQRT
0xd5  FEXP2
```

`0x100` 之后是 assembler-only pseudo inst：

```text
LCOPY
COPYT
LCOPYT
HLDT
ILDT
HSTT
ISTT
ILDMT
SLDM
...
```

这点非常重要：`HLDT/HSTT/ILDMT` 不是最终硬件 opcode，它们是 CSV/编译层使用的伪指令。

## 3. CSV 指令格式

核心文件：

```text
testcase/common_oper/csv_oper.h
testcase/common_oper/csv_oper.cpp
```

CSV 固定字段为 8 列：

```text
inst_name, inst_tag_name, src_reg_idx0, src_reg_idx1,
dst_reg_idx, dst_pe_idx, imm, iteration
```

后面还可以追加 `extra_fields[0..2]`。

以 softmax 为例：

```csv
HLDT,HLDT0,,,softmax0_input0_0_0_0,0,0,1
IMM,IMM7,,,rLog2E,,1069066811,0
H2FP,H2FP10,softmax0_input0_0_0_0,,FP0_softmax0_input0_0_0_0,,0,0
FMUL,FMUL11,FP0_softmax0_input0_0_0_0,rLog2E,FP0_softmax0_input0_0_0_0,,,1
FEXP2,FEXP213,FP0_softmax0_input0_0_0_0,,FP0_softmax0_input0_0_0_0,,,1
HSTT,HSTT40,,,sum_tmp_0_0,0,0,0
```

字段含义目前可还原为：

- `inst_name`：助记符。
- `inst_tag_name`：指令标签，主要用于去重、调试和 graph/copy 关系引用。
- `src_reg_idx0/src_reg_idx1`：源 operand 的符号名。
- `dst_reg_idx`：目标 operand 的符号名。
- `dst_pe_idx`：COPY 或部分 pseudo inst 的目标 PE / 模式编码。
- `imm`：立即数或地址偏移。
- `iteration`：执行条件 / base address index。源码里对应 `iter_exe_cond`，枚举为 `START/ALL/END`，但在 LD/ST/RTL 输出中也被当作 `base_addr_idx` 使用。
- `extra_fields`：部分 LD/ST/RTL 编码的 mask、simd mode、shift 等附加控制。

## 4. CSV 到 inst_t

核心逻辑在 `Csv_Operate::process()`：

```text
csv_oper.cpp
  readFromCsv()
    -> constructOneCsvItem()
  process()
    -> op name 查表
    -> 填 inst_t
    -> 展开 pseudo inst
    -> set_forwarding_bypass()
```

`registerOp()` 建立助记符到 opcode/unit/latency 的映射，例如：

```c
registerOp(OP_FADD,  "FADD",  OP_FLT_LATENCY, 2, false, FLT_UNIT_INST_TYPE);
registerOp(OP_FEXP2, "FEXP2", OP_TRAN_LATENCY, 1, false, FDIV_UNIT_INST_TYPE);
registerOp(OP_LDN,   "LDN",   OP_LD_LATENCY,  1, false, LD_UNIT_INST_TYPE);
registerOp(OP_STD,   "STD",   OP_STD_LATENCY, 1, false, ST_UNIT_INST_TYPE);
registerOp(OP_COPY,  "COPY",  OP_COPY_LATENCY,1, true,  FLOW_UNIT_INST_TYPE);
registerOp(OP_HLDT,  "HLDT",  OP_LD_LATENCY,  1, false, LD_UNIT_INST_TYPE);
registerOp(OP_HSTT,  "HSTT",  OP_STD_LATENCY, 1, false, ST_UNIT_INST_TYPE);
registerOp(OP_ILDMT, "ILDMT", OP_LD_LATENCY,  1, false, LD_UNIT_INST_TYPE);
```

`inst_t` 是 simulator 侧使用的完整内部指令结构：

```c
typedef struct _inst_t {
    opCode_t opCode;
    uint64_t unit_inst_type;
    uint64_t latency;
    uint64_t imms[3];
    uint64_t src_operands_idx[3];
    uint64_t dst_operands_idx[3];
    position_t dst_pes_pos[3];
    uint64_t dst_blocks_idx[3];
    uint64_t forwarding_bits[3];
    uint64_t bypass_bits[3];
    uint64_t iter_exe_cond;
    char src_operands_fetched[3];
    char dst_operands_fetched[3];
    uint64_t block_idx;
    uint64_t flow_ack;
    uint64_t end_inst;
    uint64_t extra_fields[3];
} inst_t;
```

寄存器编号不是 CSV 里直接给数字，而是由 `Csv_Operate::getRegIdx()` 根据符号名分配：

- 普通符号名进入 `m_reg_idx_list`。
- 以 `r` 开头的符号名进入 `m_reuse_reg_idx_list`，看起来用于复用/常量类寄存器。

## 5. 伪指令展开

`csv_oper.cpp` 中 `expandedPseudoName()` 定义了伪指令到真实 opcode 的映射：

```text
HLDT/ILDT  -> LDN
ILDMT/SLDM -> LDM
HSTT/ISTT  -> STD
COPYT      -> COPY
LCOPYT     -> LCOPY
SLDSHIF    -> LDSHIF
SLDMD64    -> LDMD64
SLDCNST    -> LDCNST
SSTM       -> STM
SSTMD64    -> STMD64
SSTCNST    -> STCNST
SSTSHIF    -> STSHIF
```

展开规则是：先保留第一条原始/调整后的指令，再追加 `OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE - 1` 条真实指令。对非 copy pseudo inst，追加指令的 `imm` 会按 stride 增加：

```c
stride = (dst_pe_x + 1) * 32;
append_imm = original_imm + i * stride;
```

所以 softmax 里的：

```csv
HLDT,...,dst_pe_idx=0,imm=0
```

会对应一组 `LDN` 风格的多 lane / 多 operand RAM 访问。`ILDMT` 的 `dst_pe_idx=-2` 会通过 `pseudoDstPeX()` 取低位，实际影响 LDM 的 `simd_mode` 和地址步进。

## 6. 指令 block 阶段

核心文件：

```text
testcase/common_oper/inst_blk_gen.cpp
```

`Inst_Block::process()` 对 `csv_oper.m_insts` 做严格阶段划分：

```text
LD stage   : unit_inst_type & LD_UNIT_INST_TYPE
CAL stage  : unit_inst_type & CAL_INST_TYPE
FLOW stage : unit_inst_type & FLOW_UNIT_INST_TYPE
ST stage   : unit_inst_type & ST_UNIT_INST_TYPE
```

如果 CSV 中出现非 `LD -> CAL -> FLOW -> ST` 顺序，最后会触发：

```text
Error:block inst amount != csv inst amount
```

所以 CSV 不是普通汇编列表，而是带硬件阶段约束的 microprogram block。

## 7. inst_t 到二进制文件

核心文件：

```text
testcase/common_oper/task_print.cpp
```

`Print_Task_Group::print_inst()` 遍历每个 PE 上的 graph node：

```text
for each PE:
  for each GRAPH_NODE on this PE:
    get Inst_Block / Exe_Block
    print ld_stage
    print cal_stage
    print flow_stage
    print st_stage
    exeBlock_conf.inst_mem_based_addr = 当前 PE 内指令起始 byte offset
  write simulator_bin/tmpinsts_file.bin<pe>
```

随后 `fill_max_inst_per_pe()`：

```text
1. 把每个 PE 的 tmpinsts_file.bin<pe> padding 到 MAX_INST_AMOUT_PER_PE
2. 按 PE 顺序拼成 simulator_bin/insts_file.bin
3. 把 RTL 侧每 PE 的压缩指令拼成 rtl_bin/cbufData_inst.bin
```

因此：

```text
simulator_bin/insts_file.bin
  = PE0 的固定指令槽
  + PE1 的固定指令槽
  + ...
  + PE15 的固定指令槽
```

每个槽位是一个完整 `inst_t`，这是 simulator 更容易消费的格式。

## 8. RTL 64-bit 指令编码

`inst_def.h` 里定义了 RTL 侧 bitfield 结构。它们都正好是 64-bit。`task_print.cpp::write_rtl_inst()` 根据 opcode 选择格式。

普通 cal2 格式：

```c
opCode            : 8
base_addr_idx     : 4
src_operands_idx0 : 12
src_operands_idx1 : 12
dst_operands_idx0 : 12
imm               : 10
end_inst_flag     : 1
block_idx         : 5
```

LD/ST 格式：

```c
opCode            : 8
base_addr_idx     : 4
imm               : 21
dst_operands_idx0 : 12
simd_mode         : 2
int8_offset       : 1
shiftR_idx        : 3
shiftR_cnt        : 6
mask_enable       : 1
end_inst_flag     : 1
block_idx         : 5
```

COPY 格式：

```c
opCode            : 8
base_addr_idx     : 4
src_operands_idx0 : 12
dst_operands_idx0 : 12
pos_x             : 2
pos_y             : 2
no_use            : 18
end_inst_flag     : 1
block_idx         : 5
```

`IMM/FIMM` 还有特殊格式，把 32-bit immediate 拆成 `imm_1:24` 和 `imm_2:8`。

特殊 transcendental 指令在 RTL 输出时进一步编码：

```text
FRCP/FSQRT/FRSQRT/FSIN/FCOS/FLOG2/FEXP2
```

这些在 RTL 里统一写成 `opCode = OP_FRCP`，再用 `imm` 的 bit 标识具体函数：

```text
FRCP   -> 1 << 0
FSQRT  -> 1 << 1
FRSQRT -> 1 << 2
FSIN   -> 1 << 3
FCOS   -> 1 << 4
FLOG2  -> 1 << 5
FEXP2  -> 1 << 6
```

这说明 `FEXP2` 在 CSV/`inst_t` 层是独立 opcode，但在 RTL 指令编码层可能共享同一个特殊函数单元 opcode。

## 9. PE 执行模型

当前 `pe/src` 只有 OCR 头文件，但已经暴露出主要结构：

```text
pe/src/pe_common_def.h
pe/src/execute_inst.h
pe/src/pipeline.h
pe/src/alu_unit.h
pe/src/transfer_unit.h
```

从这些头文件能推断：

1. 每条指令执行时会被包装成 `inst_param_t`：

```c
inst_t* pInst;
int64_t block_idx;
uint64_t subtask_idx;
uint64_t instance_idx;
unit_t* operands;
unit_t* tmp_regs;
...
```

2. PE 内有多类 pipeline：

```text
pipeline_fix
pipeline_flt
pipeline_fdiv
pipeline_tensor
pipeline_load
pipeline_store
pipeline_copy
```

3. `execute_inst()` 会按指令类型选择 ALU、transfer 或 pipeline：

```c
execute_inst(...)
fetch_operands_by_bypass_and_forward(...)
get_compete_operands(...)
check_RAM_occupied(...)
```

4. ALU 侧入口是：

```c
process_alu_inst(...)
```

5. transfer 侧入口是：

```c
process_tran_inst(...)
pack_spm_load_msg(...)
pack_spm_store_msg(...)
pack_pe_msg(...)
send_msg(...)
tran_unit_recv_data(...)
send_active_msg(...)
send_instance_done_msg(...)
```

这和前面对 `LD/CAL/FLOW/ST` 的阶段划分吻合：

- `LD` 走 load pipeline / transfer unit，从 SPM/内存读 operand。
- `CAL` 走 fix/flt/fdiv/tensor pipeline。
- `FLOW` 走 copy pipeline / PE-to-PE message，用 graph edge 的 copy 指令搬中间结果。
- `ST` 走 store pipeline / transfer unit，把 operand 写回 SPM/输出区域。

## 10. softmax 中一条指令的还原例子

以 `task0/subtask1/template/0.csv` 中的：

```csv
FEXP2,FEXP213,FP0_softmax0_input0_0_0_0,,FP0_softmax0_input0_0_0_0,,,1
```

流程是：

```text
CSV row
  -> op_name = FEXP2
  -> opcode = OP_FEXP2
  -> unit_inst_type = FDIV_UNIT_INST_TYPE
  -> latency = OP_TRAN_LATENCY
  -> src0 = getRegIdx("FP0_softmax0_input0_0_0_0")
  -> dst0 = 同一个 operand idx
  -> iter_exe_cond = 1
  -> cal_stage_insts
  -> simulator insts_file.bin 中写完整 inst_t
  -> RTL cbufData_inst.bin 中写 cal2 格式:
       opCode = OP_FRCP
       imm = 1 << 6
       base_addr_idx = 1
       src/dst operand idx = 上面分配出的编号
       block_idx = graph node 映射后的 block id
```

以：

```csv
HLDT,HLDT0,,,softmax0_input0_0_0_0,0,0,1
```

流程是：

```text
CSV row
  -> pseudo opcode OP_HLDT
  -> 第一条保留/调整 dst_pe_x
  -> 追加展开为 LDN 类真实指令
  -> stage = LD
  -> RTL 输出时按 LDN/LDST 格式写:
       opCode = OP_LDN
       base_addr_idx = iteration
       imm = 地址偏移
       dst_operands_idx0 = 目标 operand 编号
       simd/mask/shift 来自 dst_pe_idx 和 extra_fields
```

## 11. 当前判断

可以比较有把握地说：

1. 当前 CSV 就是 PE 侧 microprogram IR。
2. `csv_oper.cpp` 是 micro-assembler 前端。
3. `inst_blk_gen.cpp` 是 stage splitter。
4. `generateGraph()` / `Graph_Extend` 把 inst block 放进 graph node，并建立可能的 copy/依赖边。
5. `INST_BLK_MAP` 决定 graph node 和 operand 如何落到具体 PE/block/register。
6. `task_print.cpp` 是二进制后端，分别输出 simulator 格式和 RTL 格式。
7. simulator 使用完整 `inst_t`，RTL 使用 64-bit packed instruction。
8. PE 执行模型可以推断为多 pipeline issue/execute/transfer，但缺少实现源码，所以现在不能精确说明每个 opcode 的运算语义和每周期行为。

下一步最值得做的是写一个小 decoder：

```text
读取 softmax_1/simulator_bin/insts_file.bin
按 inst_t 解析 PE0 前几十条指令
和 task0/subtask1/template/0.csv 对齐
再读取 rtl_bin/cbufData_inst.bin
验证同一条 FEXP2/HLDT/HSTT 的 64-bit 编码
```

这样可以把源码推断和真实生成物逐字节对上。

## 12. PE 内部体系结构

从 `common/src/pe_com_def.h`、`common/src/basic_def.h`、`common/src/mesh_com_def.h` 和 `pe/src/*.h` OCR 头文件可以还原出一个比较清楚的 PE 结构。

### 12.1 PE 阵列和单 PE 资源

当前配置是：

```c
PE_ARRAY_X_LEN = 4
PE_ARRAY_Y_LEN = 4
PE_AMOUNT      = 16
```

所以当前可见模型是一个 4x4 PE tile，而不是完整大芯片。

每个 PE 有：

```c
MAX_INST_AMOUT_PER_PE        = 4352
MAX_OPERAND_RAM_AMOUNT_PER_PE = 1536
MAX_REGS_AMOUNT_PER_PE        = 8
```

`pe/src/pe.h` 里 PE 私有状态包含：

```c
unit_t operands[MAX_REGS_AMOUNT_PER_PE + MAX_OPERAND_RAM_AMOUNT_PER_PE];
unit_t tmp_regs[4][4][20];
unit_t tensor_tmp_regs[4][4];
unit_t mp_tmp_regs[4][64];
inst_t inst_list[MAX_INST_AMOUT_PER_PE];
exe_block_manage_t exe_block_manage;
transfer_unit_t transfer_unit;
pipeline_unit_t pipeline_unit;
```

也就是说，PE 本地有：

- operand/register file：统一存在 `operands[]` 里，前一小段像寄存器，后面大段像 operand RAM。
- instruction memory：`inst_list[]`。
- execute block controller：管理 block active/ack/finish。
- transfer unit：处理 LD/ST/COPY 和消息。
- pipeline unit：处理各类流水线。
- 若干临时寄存器：用于 int8、shift load/store、mask SIMD、tensor sparse bit、mixed precision。

### 12.2 数据宽度和 SIMD

`unit_t` 是一个 128-byte 的 SIMD 数据容器：

```c
#define SIMD_UNIT 32

typedef union {
    int fix[32];
    unsigned int ufix[32];
    float flt[32];
    unsigned short flt_16[64];
    char fix_8[128];
    unsigned char ufix_8[128];
} unit_t;
```

所以一条普通 operand 实际上是一整个 SIMD128 byte lane group：

- 32 x int32
- 32 x uint32
- 32 x fp32
- 64 x fp16
- 128 x int8/uint8

这解释了 softmax CSV 里为什么一个 `HLDT`/`HSTT` 常常以 128 为地址步进，也解释了 `FP2H` 后面经常配合 `SHFL` 把两个 fp32 vector 合成/排列成 fp16 输出。

### 12.3 Operand RAM 组织

当前宏：

```c
OPERANDS_RAM_GROUP_NUM = 3
OPERANDS_RAM_NUM_PER_GROUP = 4
OPERANDS_RAM_NUM = 12
OPERANDS_PER_OPERAND_RAM = 1536 / 12 = 128
```

这和 pseudo inst 展开逻辑吻合。`HLDT/HSTT/ILDMT` 这类伪指令会展开成多条底层 LD/ST 指令，覆盖一个 operand group 里的多个 RAM bank/lane。

### 12.4 PE 内执行组件

`pe_com_def.h` 把执行组件分成：

```c
LD_COMPONENT_IDX = 0
CAL_COMPONENT_IDX
FLOW_COMPONENT_IDX
ST_COMPONENT_IDX
```

`pipeline_unit_t` 里进一步有：

```text
pipeline_fix
pipeline_flt
pipeline_fdiv
pipeline_tensor
pipeline_load
pipeline_store
pipeline_copy
```

因此我们目前理解的 PE 微结构是：

```text
             MICC / control mesh
                    |
              exe block ctrl
                    |
        +-----------+-----------+
        |           |           |
      LD stage   CAL stage   FLOW stage   ST stage
        |           |           |           |
   load pipe   fix/flt/fdiv/  copy pipe   store pipe
                tensor pipe
        |           |           |           |
        +------ operand RAM / regs --------+
                    |
              SPM / PE mesh
```

### 12.5 网络和存储消息

`mesh_com_def.h` 定义了 3 条 mesh：

```text
MEM_ACCESS_MESH
PE2PE_MESH
CTRL_MESH
```

消息类型包括：

```text
PE2SPM_LOAD_REQ
SPM2PE_LOAD_DATA
PE2SPM_STORE_REQ
SPM2PE_STORE_ACK
PE2PE_COPY_DATA
PE2PE_ACTIVE
PE2PE_ACK
PE2PE_FLOW_ACK
MICC2PE_CONF
MICC2PE_ACTIVE
MICC2PE_INST
PE2MICC_DONE
```

这说明：

- LD/ST 不是 CPU 搬数据，而是 PE transfer unit 发 SPM load/store 请求。
- COPY 不是内存 load/store，而是 PE-to-PE copy data message。
- graph node 依赖中的 activation/ack 也是 PE-to-PE 或 MICC-to-PE 控制消息。

## 13. 指令效果的可确认程度

目前可以按三档理解每条指令效果。

### 13.1 高可信：名称、类型、字段都能对上的指令

这些指令的效果基本可以从名称、数据类型和 opcode 分组直接判断：

| 指令族 | unit | 作用 |
|---|---:|---|
| `ADD/SUB/MUL/MAX/MIN/EQ/LT/GT` | FIX | 对 `unit_t.fix[32]` 做 int32 SIMD 运算/比较 |
| `UADD/USUB/UMUL/UMAX/UMIN/ULT/UGT` | FIX | 对 `unit_t.ufix[32]` 做 uint32 SIMD 运算/比较 |
| `LSL/LSR/ASR/OR/AND/NOT/XOR` | FIX | SIMD 整数位运算/移位 |
| `MADD/UMADD/COND/DP4A/QMADD` | FIX | 整数乘加、条件选择、dot/int8 或量化乘加类操作 |
| `FADD/FSUB/FMUL/FMAX/FMIN/FLT/FGT/FMADD` | FLT | 对 `unit_t.flt[32]` 做 fp32 SIMD 运算/比较 |
| `DADD/DSUB/DMUL/DMAX/DMIN/DLT/DGT/DMADD` | FLT | double 语义的浮点运算，具体 lane 组织待实现源码确认 |
| `HADD/HSUB/HMUL/HMAX/HMIN/HLT/HGT/HMADD` | FLT | fp16/half 语义的 SIMD 运算，通常作用于 `unit_t.flt_16[64]` |
| `H2FP` | FLT | half/fp16 转 fp32 |
| `FP2H` | FLT | fp32 转 half/fp16 |
| `FDIV/DDIV/HDIV/DIV/UDIV` | FDIV | 除法类运算 |
| `FRCP/FSQRT/FRSQRT/FSIN/FCOS/FLOG2/FEXP2` | FDIV | 特殊函数单元；RTL 中统一编码到 `OP_FRCP + imm bit` |
| `IMM/FIMM` | FIX | 写 immediate 到目标 operand |
| `MOVE` | FIX/special | 移动/复制 operand 内部数据，RTL 有专门 `move` 格式 |

这些指令的具体 corner case，比如舍入、溢出、NaN、比较结果掩码格式，目前还不能从已见源码完全确认。

### 13.2 中可信：访存和通信指令

这些指令的硬件元素和方向可以确认，但精确地址计算还需要 `transfer_unit.c`：

| 指令 | unit | 作用 |
|---|---:|---|
| `LDN` | LD | 从 SPM/内存读取一个 SIMD atom 到 PE operand |
| `LDM` | LD | 带 mask/simd mode 的 load，多用于中间值或特殊布局 |
| `LDSHIF` | LD | 带 shift 参数的 load |
| `LDMD64` | LD | 64-bit/d64 模式 load |
| `LDCNST` | LD | load constant |
| `STD` | ST | 把 PE operand store 到 SPM/输出区域 |
| `STM` | ST | 带 mask/simd mode 的 store |
| `STSHIF` | ST | 带 shift 参数的 store |
| `STMD64` | ST | 64-bit/d64 模式 store |
| `STCNST` | ST | store constant 或常量区相关 store |
| `COPY` | FLOW | 通过 PE2PE mesh 把源 operand 发送到目标 PE/block/operand |
| `LCOPY` | FLOW | local copy pseudo，map 后会改成目标为本 PE、本 block 的 `COPY` |

访存相关 RTL 字段：

```text
base_addr_idx     <- iteration / iter_exe_cond
imm               <- CSV imm
dst_operands_idx0 <- PE operand index
simd_mode/int8_offset/shift/mask <- dst_pe_idx + extra_fields
block_idx         <- graph node 映射出的 block id
```

通信相关 RTL 字段：

```text
src_operands_idx0
dst_operands_idx0
pos_x / pos_y
block_idx
base_addr_idx = flow_ack
```

### 13.3 低到中可信：需要实现源码或 trace 校验的指令

这些名字能猜出大意，但不能只靠当前头文件断言精确效果：

| 指令 | 初步理解 |
|---|---|
| `SHFL` | SIMD lane shuffle / pack / cross-lane 重排。softmax 中用于 reduction 和 `FP2H` 后半区拼接。 |
| `MASK` | 生成或应用 SIMD mask。 |
| `RXIN/RXOUT/RXINT` | 和 reduce/cross-lane/tensor 输入输出相关，需实现确认。 |
| `TRCT8/TRCTT` | transpose/trace/transform 类操作，可能服务 int8/tensor 数据重排。 |
| `EXPD32` | expand 32-bit 或扩展数据布局。 |
| `LOFST` | load offset 或 offset 生成。 |
| `QMPAD/QMADD` | quantized matrix/packed add/madd 相关。 |
| `HMMA/HMMAQ/HMMAL` | half matrix multiply accumulate / tensor core 操作。 |
| `IMMA/IMMAU/IMMAIU/IMMAUI` | int matrix multiply accumulate 及有符号/无符号组合。 |
| `SSET` | tensor/sparse setting。 |
| `GINST/GIBSN/GSIMD` | getter/debug/config 类指令，具体效果不明。 |

`tensor_op.h` 里能看到：

```c
hmma(...)
hmma_64(...)
hmma_lp(...)
imma(...)
qmadd/qmma...
sparse2dense(...)
fp8/fp16 conversion...
```

所以 tensor 指令族的硬件方向可以确认：它们对应 tensor/MMA 单元和 mixed precision/sparse 数据通路。但没有实现源码时，矩阵 tile 形状、累加顺序和量化规则还不能定死。

## 14. 从指令效果看 softmax

当前 softmax 的两段 subtask 可以这样解释：

### subtask1：局部 exp 和局部 sum

典型序列：

```text
HLDT input chunk
IMM  log2(e), 100, shfl offsets, sum=0
H2FP fp16 input -> fp32
FMUL x * log2(e)
FMIN clamp to 100
FEXP2 exp2(x * log2(e)) = exp(x)
FADD accumulate local sum
SHFL + FADD 做 PE 内 SIMD reduction
HSTT 把局部 sum 写到 SUM 中间区
```

这里 `FEXP2` 的物理执行单元应是 FDIV/特殊函数 pipeline。`SHFL` 应该是 lane shuffle，用 16/8/4/2/1 这些 offset 做树形规约。

### subtask2：全局 sum 合并和归一化输出

典型序列：

```text
ILDMT load 多份 SUM partial
FADD 合并 partial sum
FDIV exp(x) / sum
FP2H fp32 -> fp16
SHFL 重排/拼接 fp16 lane
HSTT store softmax output
```

这里 `ILDMT` 加载的是 subtask1 写出的 SUM 中间结果。`FDIV` 负责归一化，`FP2H + SHFL + HSTT` 负责把 fp32 结果转回 fp16 并写回输出。

## 15. 当前缺口

现在最大的缺口不是 opcode 表，而是 PE 执行实现：

```text
process_alu_inst()
process_tran_inst()
execute_inst()
advance_alu_pipeline()
advance_tran_pipeline()
fetch_operands_by_bypass_and_forward()
check_RAM_occupied()
```

这些函数在 OCR 头文件里出现了声明，但当前本地没有对应 `.c/.cpp`。因此：

- 每条常规指令的“大语义”可以推断。
- 指令驱动的硬件元素可以大致确定。
- 但精确到每个 lane、mask、shift、rounding、stall、forwarding 的行为，还需要补 PE 实现源码，或者从 simulator trace/二进制运行结果反向校验。
