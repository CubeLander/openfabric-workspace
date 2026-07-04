# Instruction Set Notes

这里整理从甲方原始 Office 材料抽取出来的指令集 Markdown。仓库 `.gitignore` 会忽略
Office 文件和图片，所以这里保留的是轻量文本化版本，方便 agent context、代码审查和
后续后端实现引用。

## Available Families

1. [DFU3500 SIMD 指令集](dfu3500-simd/README.md)
   - 来源：`2、DFU3500-SIMD指令集.xlsx`
   - 来源：`3、DFU3500-SIMD指令集文档.docx`
   - 重点：SIMD lane 解释、普通算术、类型转换、RX/QMADD/TRCT8 等 SIMD 侧内部状态指令。
   - 注意：仅看 mnemonic/lane 语义不足以安全发射二进制；访存 `base_addr`、伪指令展开、template evidence 见 `dfu3500-simd/MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md`。

2. [DFU3500 Tensor 指令集](dfu3500-tensor/README.md)
   - 来源：`（这个文档先不看）DFU3500-tensor指令集.xlsx`
   - 来源：`（这个文档先不看）DFU3500-tensor指令集.docx`
   - 重点：`RXINT`、`TRCTT`、`IMMA*`、`HMMA`、`HMMAL`，以及 tensor tmp register 绑定规则。

## Tensor Extracts

Tensor 指令集的完整抽取文件：

```text
docs/instruction-set/dfu3500-tensor/xlsx/README.md
docs/instruction-set/dfu3500-tensor/xlsx/Sheet1.md
docs/instruction-set/dfu3500-tensor/docx/README.md
docs/instruction-set/dfu3500-tensor/docx/dfu3500-tensor-instruction-doc.md
```

当前最重要的结论：

```text
HMMAL 属于 tensor 指令，不属于 SIMD 指令。
HMMAL imm[9:7] 选择 dst tmp0..tmp7。
RXINT/TRCTT 在普通 operand 和 tensor tmp state 之间搬运/转换数据。
```
