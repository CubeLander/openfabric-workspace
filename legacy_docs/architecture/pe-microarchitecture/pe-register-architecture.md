# PE 寄存器架构与 operand 布局

这一页把 PE 侧的寄存器盘子收在一起看：

- 8 个通用寄存器槽
- 8 个 mask 寄存器
- 4 个 RX 暂存器
- 8 个 LRX 暂存器
- 1536 个 operand index 槽位

它的定位是硬件架构页，不是编译器里的 operand 分配说明。编译器怎么把符号
operand 摊到这些槽位上，只在最后一节做简短说明。

## 先看结论

PE 的可见状态可以先分成四类：

```text
1. General regs:  8 个通用寄存器槽
2. Mask regs:     8 个 mask0..mask7
3. RX/LRX temps:  RX0..RX3 + LRX0..LRX7
4. Operand slots: 1536 个 PE-local operand index
```

这四类不是同一个地址空间。

- `mask regs` 是控制掩码，给 masked store / 受控写回用。
- `RX regs` 是 int8 / 特殊乘加一类内部暂存区。
- `LRX regs` 是 32-bit 的间接寻址暂存区，给 shift load/store 用。
- `operand slots` 才是大部分计算指令真正读写的 PE-local 数据空间。

## 1. 通用寄存器槽

公共头文件里有：

```c
#define MAX_REGS_AMOUNT_PER_PE (8)

typedef struct _pe_reg_t {
    unit_t regs[MAX_REGS_AMOUNT_PER_PE];
} pe_reg_t;
```

这说明 PE 里确实存在一个 8 槽的通用寄存器文件。它和 operand RAM 不是一回事。

当前仓库里，真正被大量讨论和打包的是 operand index，但从 PE 架构角度看，
这 8 个通用寄存器槽仍然是 PE 私有状态的一部分。

## 2. Mask 寄存器

指令集抽取结果和 OCR 片段都确认了这件事：
PE 内部有 8 个 mask 寄存器，编号 `mask0..mask7`。

它们主要服务于带掩码的写回/访存类指令，例如 `HSTT`、`STM`、`SSTSHIF` 一类。

`MASK` 指令负责写这些寄存器。其配置来源于 `Operand index 0` 的低 14 bit：

```text
{Ext_flag, Ext_offset[1:0], Regid_off[1:0], double_mark, Maskregno[7:5], mask_val[4:0]}
```

常用理解可以简化成：

```text
MASK -> 选择一个 mask 寄存器 -> 写入 32-bit 粒度的 mask 描述
```

相关语义在：

- `../instruction-set/dfu3500-simd/docx/instruction_sections/MASK.md`
- `../instruction-set/dfu3500-simd/OCR_DERIVED_NOTES.md`

## 3. RX / LRX 暂存器

### RX0..RX3

`RXIN` 和 `RXOUT` 的文档把这组寄存器说得很清楚：

- `RX0..RX3` 用于 int8 相关计算和内部累加。
- `RXIN` 可以把 `Operand index 0` 装入某个 `RX`。
- `RXOUT` 可以把 `RX0..RX3` 的值取回到目标 operand。

这组寄存器更像 PE 内部的特殊计算暂存区，而不是普通的 operand slot。

### LRX0..LRX7

同样在 `RXIN` 的说明里，`LRX0..LRX7` 是 32-bit 暂存器，主要用于：

- `LDSHIF`
- `STSHIF`
- 以及相关的间接寻址 / 地址步进逻辑

因此可以把它们理解成 PE 里的“地址寄存器”或“偏移寄存器”。

相关文档：

- `../instruction-set/dfu3500-simd/docx/instruction_sections/RXIN.md`
- `../instruction-set/dfu3500-simd/docx/instruction_sections/RXOUT.md`
- `../instruction-set/dfu3500-simd/OCR_DERIVED_NOTES.md`

## 4. Operand slots

这是 PE 上最重要的“数据空间”。

公共头文件给出的默认配置是：

```c
#define MAX_OPERAND_RAM_AMOUNT_PER_PE 1536
#define OPERANDS_RAM_GROUP_NUM 3
#define OPERANDS_RAM_NUM_PER_GROUP 4
#define OPERANDS_RAM_NUM (OPERANDS_RAM_GROUP_NUM * OPERANDS_RAM_NUM_PER_GROUP)
#define OPERANDS_PER_OPERAND_RAM (MAX_OPERAND_RAM_AMOUNT_PER_PE / OPERANDS_RAM_NUM)
```

代入默认值后：

```text
OPERANDS_RAM_NUM         = 12
OPERANDS_PER_OPERAND_RAM = 128
MAX_OPERAND_RAM_AMOUNT   = 1536
```

所以一个 PE 的 operand 空间可以理解成：

```text
12 个 bank
每个 bank 128 个槽
总计 1536 个 operand index
```

每个 PE 都有自己独立的一套 `0..1535` 槽位。**不同 PE 上相同的 index 不是同一份数据。**

### 宽度视图

`unit_t` 是 1024-bit chunk 的 host-side 视图：

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

因此：

```text
sizeof(unit_t)     = 128 bytes
one chunk          = 1024 bits
SIMD128 logical op = 4 x 1024-bit chunks = 4096 bits
```

这里的含义是：operand slot 本身是 PE-local 的地址编号；它背后承载的 bits
在 SIMD128 语义下可以被看成 4096-bit logical operand。

## 5. 哪些指令会碰这些状态

### `MASK`

写 `mask0..mask7`。

### `RXIN`

把 `Operand index 0` 装入：

- `RX0..RX3`
- 或 `LRX0..LRX7`

### `RXOUT`

把 `RX0..RX3` 取回到目标 operand slot。

### `LDSHIF` / `STSHIF`

通过 `LRX` 做间接寻址和偏移控制。

### 普通算术 / tensor 指令

大多数 `ADD/FADD/HADD/HMMAL` 之类的计算，最终还是围绕 operand slots 读写，
只是它们可能额外依赖 `RX/LRX/mask` 这些内部状态。

### `COPYT`

跨 PE 复制 operand slot 内容。它不是“共享寄存器”，而是通过目标 PE 坐标和目标
operand index，把一份数据搬到另一颗 PE 的本地 operand 空间。

## 6. 来自 OCR PE 头文件的实现线索

OCR 恢复出的 `pe/src/pe.h` 给了一个很有价值的侧写：

```c
typedef struct _pe_private_t {
    position_t pos;
    unit_t operands[MAX_REGS_AMOUNT_PER_PE + MAX_OPERAND_RAM_AMOUNT_PER_PE];
    unit_t tmp_regs[4][4][20];
    int tmp_regs_valid[4][4][20];
    unit_t tensor_tmp_regs[4][4];
    unit_t mp_tmp_regs[4][64];
    inst_t inst_list[MAX_INST_AMOUT_PER_PE];
    exe_block_manage_t exe_block_manage;
    transfer_unit_t transfer_unit;
    pipeline_unit_t pipeline_unit;
} pe_private_t;
```

这里至少说明三件事：

1. PE 确实有自己的 `operands[]` 和 `inst_list[]`。
2. 还有额外的临时状态区 `tmp_regs / tensor_tmp_regs / mp_tmp_regs`。
3. PE 的执行不是只靠 operand slot，内部还有 pipeline / transfer / block control。

这些 OCR 结构不一定就是最终规格，但很适合帮助我们理解 PE 的内部层次。

## 7. 当前编译器怎么把符号名落到 operand slot

这部分只放一句话，避免把架构页又写回编译器页：

- CSV 里的字符串 operand tag 只是符号。
- 工具链当前会把它们分配到 PE-local operand index。
- `inst_blk_map.cpp` 里有一套 bank 交错的布局策略，把逻辑连续编号摊到 12 个 bank。

这意味着“operand index”是 PE 架构的一部分，而“怎么分配这些 index”是编译器/打包器的实现策略。

## 8. 读下一页

如果你接着看 PE 运行方式，建议下一页是：

- `../README.md`
- `../../runtime/data/cbuf.md`
- `../../runtime/data/rtl.md`

如果你接着看 instruction 语义，就看：

- `../instruction-set/README.md`
