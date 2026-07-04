# DFU3500 SIMD 图片 OCR 整理笔记

本文基于 `docx/media/` 中图片的 OCR 结果、Excel 指令表、以及仓库 examples
交叉整理。OCR 原文可能有错字；下文把置信度较高的结论写成 agent 友好的短上下文。

阅读本文前建议先看 `OPERAND_LANE_MODEL.md`。本文提到的 `simd32`、`simd128`、
`32bits*simd32`、`8bits*simd128` 都建立在同一个基础模型上：`Operand index`
指向 raw 128-byte slot，具体 lane 划分由 opcode、`imm`、`simd_mode` 和
`extra_fields` 决定。

原始 OCR 入口：

- `docx/media_ocr/media_ocr.md`: 按图片编号排列的 OCR 结果。
- `docx/media_ocr/media_ocr_index.jsonl`: 每张图的尺寸、OCR 分数、标签和文本。
- `docx/media_ocr/raw/imageNN.txt`: 单张图片的原始 OCR 文本。

## 可靠性分层

- 高置信：能被 xlsx 指令卡片或 examples 同时支持的语义，例如 `SHFL` 模式、
  `QMADD + TRCT8`、`RXIN/RXOUT`、`COPYT`。
- 中置信：来自图片 OCR，但和 docx 正文描述一致的位域，例如 `ILDMT`
  的 `simd_mode` 拆分、`MASK` 的 14-bit 配置。
- 低置信：图片中的复杂位图布局和中文细节，例如 `TRCT8` 某些 imm 分支的完整
  拼接顺序，后续应结合 simulator 或最小 examples 验证。

## SHFL

来源：`image43.png` 到 `image50.png`，以及 softmax examples 中大量
`SHFL,...,imm=3` 行。

`SHFL` 用于重排 SIMD 分量，`imm[1:0]` 决定模式：

- `imm[1:0] = 0`: old immediate mode。`Operand index 0[59:0]` 编码
  6 组 `{dst, src}`，从 `Operand index 1` 取最多 6 个 simd32 分量，放到
  `Operand index 2`。`dsti == 0 && i > 0` 表示该位置禁用。特殊用法：
  `Operand index 0 == 0` 时，交换 `Operand index 2` 的上下 512-bit。
- `imm[1:0] = 1`: fp32 merge simd32 mode。idx 为 32-bit 数，最多 shuffle
  8 个 32-bit SIMD 分量。可用于把某个分量 broadcast 到全部 32 个 simd32。
- `imm[1:0] = 2`: fp64 merge simd16 mode。最多 shuffle 8 个 64-bit SIMD
  分量。可用于把某个分量 broadcast 到全部 16 个 simd64。
- `imm[1:0] = 3`: shift simd32 mode。`shift_num = Operand0(0)`，
  把 `Operand index 1` 的高低分量与 `Operand index 2` 拼接，常见于 softmax
  归约/滑动式后处理。

额外控制：

- `imm[2]` 到 `imm[5]` 分别控制四组 1024-bit 数据是否在组内 shuffle：
  `0` 表示 shuffle，`1` 表示保持原数据。

从 examples 看，softmax 的归约阶段常见：

```csv
SHFL,SHFL30,rShflF0,sum_tmp_1_0,rKernelSF_1,,3,0
```

这说明 `imm=3` 的 shift 模式被用作局部 reduction 的数据移动，而不是普通
算术运算。

## COPYT

来源：`image53.png`、指令卡片、gemm template examples。

语义是把源 PE 上一个 operand slot 的内容复制到目的 PE 的 operand slot：

```csv
COPYT,COPYT1,rKernel0,,rKernel0,1,,1
```

CSV 字段可理解为：

- `src_reg_idx0`: 源 operand tag。
- `dst_reg_idx`: 目的 operand tag。
- `dst_pe_idx`: 目的 PE 编号或相邻 PE 方向编码，examples 中 GEMM 常用 `0/1`。
- `iteration`: 与依赖/flow ack 有关，常见为 `1`。

GEMM template 中 `COPYT` 由开发者脚本手动生成，用来把左侧/右侧 PE 已经加载的
A tile 沿 mesh 传播给相邻 PE，减少 SPM/DRAM 访存。

## 访存类指令

来源：docx 正文、`image54.png` 到 `image70.png`，以及 generated CSV。

统一地址模型：

```text
DFU 访存地址 = imm + instance_baseaddr(iteration field)
```

也就是说 CSV 的 `imm` 是相对偏移，`iteration` 选择某个 runtime/baseaddr
槽位。此前 `inst_t.iter_exe_cond` 被 RTL packing 用作 `base_addr_idx`，这和
这里的 `iteration field` 描述相互支持。

### HLDT

- 对齐：`(32 * 4) Bytes = 128 Bytes`。
- docx 写法为 `4 * (regbase + imm)`，结合 1024-bit chunk / 4096-bit
  SIMD128 logical operand，可先理解为以 32-bit word 为基本地址单位，最终落到
  128B 对齐的 chunk 数据块。

### ILDMT

- 对齐：`4 Bytes`。
- 用于从 SPM 取较小粒度/多种类型数据，并按 SIMD mode 扩展/排布到 operand。
- `simd_mode[0]` 使用 `dst_pe_idx[0]` 表示。
- `simd_mode[1]` 使用 `extra_fields[0][0]` 表示。
- 8-bit/16-bit 偏移使用 `extra_fields[1][1:0]` 表示。

`simd_mode[1:0]` 对应：

- `0`: multiple `32 x 32bits`
- `1`: multiple `16 x 64bits`
- `2`: multiple `64 x 16bits`
- `3`: multiple `128 x 8bits`

图片示例还显示：

- `imm`: 4 bytes 地址偏移。
- `dst_pe_idx[0]`: 数据类型/`simd_mode[0]`。
- `dst_pe_idx[?:1]`: `(n + 1) * 4 Bytes` 的硬件指令间偏移。
- `extra_fields[2][1:0]` 在图中被用来标记 fp16/fp8 一类模式；这里还需要
  examples 或 simulator 行为确认。

### SLDSHIF / SSTSHIF

- `SLDSHIF` 对齐：`128 Bytes`。
- `SSTSHIF` 与 `SLDSHIF` 相同，但加入 `other` 段的 mask 信息。
- `RXIN` 的 `imm=4..11` 会初始化 `LRX0..LRX7`，docx 说明这些 32-bit LRX
  用于 `sldshif`/`sstshif` 的间接寻址。

### HSTT

- 对齐：`128 Bytes`。
- 可以带 mask 寄存器，也可以不带 mask 寄存器。
- GEMM 输出阶段大量使用 `HSTT`，形如：

```csv
HSTT,HSTT0,,,gemm0_output0_0_0,7,0,0
```

这里 `dst_reg_idx` 实际上是 store 的源 operand tag，`dst_pe_idx/imm/iteration`
共同决定写回地址/通道。这个命名来自 CSV 模板，不应按普通 ALU 的 dst 字段理解。

## MASK

来源：xlsx 指令卡片、`image71.png` 到 `image77.png`。

`MASK` 修改运算部件内部的 8 个 mask 寄存器，主要服务 store 屏蔽某些 SIMD
分量。配置来自 `Operand index 0` 的 simd0 分量低 14 bit：

```text
{Ext_flag, Ext_offset[1:0], Regid_off[1:0], double_mark, Maskregno[7:5], mask_val[4:0]}
```

字段含义：

- `double_mark`: 是否开启双 SIMD 分量写回模式。
- `Maskregno[7:5]`: 选择 mask0 到 mask7。
- `mask_val[4:0]`: 对应 32-bit 分量粒度的 mask 值。
- `Regid_off[1:0]`: SIMD128/64/32 模式下的寄存器编号偏移。
- `Ext_offset[1:0]`: 8-bit 分量索引，和 `mask_val[4:0]` 组合使用。
- `Ext_flag`: 与 `double_mark` 组合，决定最终按 8/16/32/64-bit 分量写回。

图片补充的高置信结论：

- `Ext_flag,double_mark == 00`: 最终取 32-bit 数据。1024-bit 可看成
  32 个 32-bit 分量，`mask_val[4:0]` 取值 `0..31`。
- `Ext_flag,double_mark == 10`: 最终取 8-bit 数据。
- `Ext_flag,double_mark == 11`: 最终取 16-bit 数据。
- docx 文字更正：选中 32-bit 和 64-bit 时不用选 `ext_offset`；选中 8-bit 时
  `ext_offset` 可用 `0,1,2,3`；选中 16-bit 时使用 `0` 和 `2`。

## RXIN / RXOUT / QMADD / TRCT8 / EXPD32

这组指令解释了 int8 乘加为什么需要内部暂存器。

### RXIN

`RXIN` 把 operand slot 写入内部暂存器：

- `imm=0..3`: `RX0..RX3 <= src0`，用于 int8 计算。
- `imm=12`: 清零 `RX0..RX3`。
- `imm=4..11`: `LRX0..LRX7 <= src0[0]`，用于 shift load/store 的间接寻址。

### QMADD

`QMADD` 是 uint8 的特殊乘加，输入是两个 `8bits * simd128` operand，输出不是
普通 `dst operand`，而是累加到内部 `RX0..RX3`：

```text
{RX3, RX2, RX1, RX0} += Operand0 * Operand1
```

图片和指令卡片给出的低层关系：

```text
RX0[0] += src0[0] * src1[0]
RX1[0] += src0[1] * src1[1]
RX2[0] += src0[2] * src1[2]
RX3[0] += src0[3] * src1[3]
RX0[1] += src0[4] * src1[4]
...
```

所以 QMADD 的结果必须再经 `TRCT8` 或 `RXOUT` 一类指令取回；不能把 CSV 里的
dummy `Operand index 2` 当成真正结果。

### TRCT8

`TRCT8` 把 `RX0..RX3` 中的 32-bit 累加结果截断/重排为目标 operand。

图片 `image90.png` 的高置信部分：

- `imm=0`: 把 4 个 `RX` 寄存器中 `128 x 32bits` 截断成 `128 x 8bits`，
  以 `RX0/RX1/RX2/RX3` 分块拼接到 result。
- `imm=1`: 也是 8-bit 截断拼接，但按 `RX3_i, RX2_i, RX1_i, RX0_i` 的交织方式
  组织若干 1024-bit result 块。
- `imm=2/4/8/16`: 用于 QMADD 之后，从不同 RX 分量组抽取结果。OCR 对完整伪代码
  的行列关系识别不够稳，需要后续结合最小 QMADD example 或 simulator 输出确认。

### EXPD32

`EXPD32` 把一个 operand 中的 8-bit lane 扩展成 int32 lane：

- `imm=0`: 取每个 32-bit 分量的 `[7:0]`。
- `imm=1`: 取 `[15:8]`。
- `imm=2`: 取 `[23:16]`。
- `imm=3`: 取 `[31:24]`。

结果是 `32bits * simd32 <= 8bits * simd32`。

## 对 mock/runtime 编译器有用的结论

1. CSV 的 `dst_reg_idx` 在不同指令族里语义不同：ALU 是目的 operand，
   store 类常常是“要写回的源 operand”，QMADD 是 dummy。
2. `imm` 不只是算术立即数；在访存中是地址偏移，在 SHFL/MASK/EXPD32/TRCT8
   中是模式选择。
3. `iteration`/`iter_exe_cond` 很可能对应 runtime base address selector。
4. `extra_fields` 是逃逸字段，至少承载 ILDMT 的高位 `simd_mode`、低精度偏移、
   以及部分 fp8/fp16 模式信息。
5. 对 agent context，优先加载：
   `instruction_cards.jsonl` 中对应 mnemonic 的卡片，加上本文对应小节；
   只有当字段不清楚时才读取 `docx/media_ocr/raw/imageNN.txt` 或打开原图。
