# Unclear Semantics Backlog

本文记录当前已经抽取到、但还不适合过早写死的指令语义。它们暂时不阻塞
mock runtime、算子编译 workflow 或核心算术指令建模；等实际写算子/编译器遇到
对应指令时，再结合 examples、生成 CSV、runtime package 产物和甲方说明继续确认。

当前稳定结论仍以 `OPERAND_LANE_MODEL.md` 和 `instruction_cards.md` 为准：

```text
SIMD128 logical operand = 4096 bits = 512 bytes
SIMD32/chunk/unit_t     = 1024 bits = 128 bytes
```

A-line runtime bring-up 后，访存/template 执行上下文已有单独补遗：

```text
MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md
```

其中 `iteration/base_addr`、`ILDMT/HSTT/COPYT` 伪指令展开、template evidence
状态已经不应只当作“未知 ISA 表字段”处理。真正仍需继续研究的是各 template family
在更多算子/数据类型下的完整 byte/runtime 证据。

## 不清楚的类型

### 逻辑/位运算指令

涉及指令：

```text
AND, OR, XOR, NOT, LSL, LSR, ASR
```

当前判断：

- 大概率在 SIMD128 logical operand 上按 `128 x 32-bit` lane 或 raw bit32 view 操作。
- `ASR` 明确偏 signed int32 语义；`LSR` 明确偏 unsigned int32 语义。
- 其它逻辑指令更像 raw `uint32/bit32` 操作。

未确认点：

- 是否存在类似 int arith 指令的 `imm==1` int8/uint8 模式。
- shift amount 是逐 lane 读取 `src1[i]`，还是只取某个 lane/低位字段。
- `NOT` 是 bitwise not 还是逻辑 not。xlsx 里写成 `! Value(...)`，但硬件逻辑类指令更可能需要结合 examples 判断。

后续触发条件：

- 算子模板或 DSL 需要生成 bitwise/shift 指令。
- examples 中出现这些指令且结果可对照。

### 类型转换指令

涉及指令：

```text
FP2DB, DB2FP, FP2FXP, FXP2FP
```

当前判断：

- 输入/输出 lane view 能从文档函数说明中读出。
- `FP2DB/DB2FP` 涉及 fp32/fp64 lane 数变化和上下半区选择。
- `FP2FXP/FXP2FP` 涉及 float/int32 转换，并使用 `imm` 控制 RX 或 rounding/truncation 相关行为。

未确认点：

- rounding、截断、饱和、NaN/Inf 等边界行为。
- `imm` 各 bit 对 RX0..RX3 或上下半区的精确选择。
- 写回时是否要求目的 operand 预初始化，以及未写 lane 是否保持旧值。

后续触发条件：

- 需要在 mock runtime 中做 bit-exact 对照。
- 算子里实际使用类型转换，并且本地形式验证不足。

### 特殊/控制类指令

涉及指令：

```text
GINST, GSIMD, GTASK
```

当前判断：

- `GINST` 写入 inst count 或当前指令相关数值。
- `GSIMD` 写入 SIMD lane index 序列。
- `GTASK` 写入 task number 或当前 task 相关数值。

未确认点：

- 这些值的精确 lane layout。
- 是写入完整 SIMD128 logical operand，还是只写一个 1024-bit chunk 后再复制/扩展。
- 与 task/subtask、iteration、硬件调度状态之间的对应关系。

后续触发条件：

- DSL/编译器需要生成依赖当前 task/index 的程序。
- runtime package 中出现这些指令，且影响计算结果。

### RX/LRX 内部状态指令

涉及指令：

```text
RXIN, RXOUT
```

当前判断：

- `RXIN/RXOUT` 与内部 `RX0..RX3`、`LRX0..LRX7` 状态有关。
- 文档里多处写到 RX 是 `1024bits`，更接近 chunk 级内部暂存器。
- 这些指令经常和 int8 pipeline、`QMADD/TRCT8`、shift 地址计算相关。

未确认点：

- RX0..RX3 与 SIMD128 logical operand 的 4 个 chunk 的精确映射。
- `LRX` 只取 operand 的哪 32bit。
- `RXOUT` 写回时是否只覆盖一个 chunk，还是由外层伪指令/多条指令完成完整写回。

后续触发条件：

- 需要实现 int8/tensor 辅助 pipeline。
- examples 中出现 `RXIN/RXOUT/QMADD/TRCT8` 且需要模拟数值。

### Tensor HMMAL tmp binding

涉及指令：

```text
RXINT, HMMAL, TRCTT
```

当前判断：

- 这些指令属于 tensor 指令集，不属于 SIMD 指令集。
- tensor xlsx/docx 已经确认 `HMMAL` destination 由 `imm[9:7]` 选择 `tmp0..tmp7`。
- tensor xlsx/docx 已经确认 `RXINT/TRCTT` 负责 operand 和 tensor tmp state 之间的
  import/export 以及类型转换。
- SIMD 文档里的 `RXIN/RXOUT/QMADD/TRCT8` 仍可作为“内部状态再 materialize”的类比，
  但不是 `HMMAL` 的来源规格。

未确认点：

- `data_select_type0..7` 的精确子矩阵选择语义。
- `HMMAL imm[1:0]=1` sparse mode 的完整语义。
- tensor tmp 的 banking、hazard 和可并发 live tmp 规则。
- `RXINT/TRCTT` conversion group size 与 `HMMAL tmp0..tmp7` 写入之间的资源约束。

后续触发条件：

- instruction lowerer 开始从 `C_acc += HMMAL(A, B)` 生成 CSV/二进制模板。
- 需要做 tensor tmp pressure / banking 的资源检查。

### mask/store/shuffle 细节字段

涉及指令：

```text
MASK, SHFL, STM/SSTM, HSTT/SSTSHIF 等带 mask 或重排字段的指令
```

当前判断：

- `MASK` 的字段结构已经抽取出来，但 store 部件如何消费 mask 仍需结合 store 指令确认。
- `SHFL` 的大方向是 lane rearrange，`imm[1:0]` 决定 32/64-bit lane 相关模式。
- store 类 4096-bit 指令会被展开为 4 条 1024-bit 底层指令。

未确认点：

- mask register 的 `Ext_flag/Ext_offset/Regid_off/double_mark/mask_val` 在每种 dtype 下如何精确影响写回。
- `SHFL` 各 imm mode 的完整 index 编码、禁用位置、旧值保持规则。
- store mask 与目的 operand/目的 SPM 地址间的精确对应。

后续触发条件：

- 算子里实际出现 masked store、复杂 shuffle、非连续写回。
- 需要做 bit-exact mock，而不是仅生成 runtime 可消费文件。

## 当前可以先放心使用的范围

以下部分目前已经足够支撑第一阶段实现：

- SIMD128/SIMD32 尺度模型。
- `ADD/SUB/MUL/MAX/MIN/EQ/LT/GT` 及 unsigned 变体的主 lane view。
- `FADD/FSUB/FMUL/FMAX/FMIN/FLT/FGT/FMADD/FDIV` 的 fp32 lane view。
- `HADD/HSUB/HMUL/HMAX/HMIN/HLT/HGT/HMADD/HDIV/HSIS` 的 fp16 lane view。
- `DADD/DSUB/DMUL/DMAX/DMIN/DLT/DGT/DMADD/DDIV/DSQRT` 的 fp64 lane view。
- `HLDT/HSTT/COPYT/SSTM/SSTSHIF` 等 4096-bit 指令拆成 `4 x 1024-bit chunk` 的模型。

## 使用方式

实际开发时如果遇到本文中的指令，建议按下面顺序补证：

1. 查 `instruction_cards.md` 对应 mnemonic。
2. 查 `docx/instruction_sections/<MNEMONIC>.md` 原始章节。
3. 查 examples 里该 mnemonic 的 CSV 生成代码和实际 CSV。
4. 如有必要，用最小输入 pattern 做远程结果对照。
5. 将新结论回写到 `instruction_cards` 生成脚本或本 backlog。
