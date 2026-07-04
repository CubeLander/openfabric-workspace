# 指令编码

这个主题聚焦 DFU3500 的指令集还原、编码格式、物理资源映射和容量模型。
它回答：CSV 如何变成二进制，inst_t 和 RTL bitfield 有什么关系，一条指令的字段
如何落到 PE 物理资源。

## 阅读顺序

1. [DPU 指令集和执行模型阶段性还原](isa-execution-model.md) — 指令集全景：
   opcode 表、CSV 格式、伪指令展开、PE 执行模型推断
2. [Instruction Format 与 RTL Packing](instruction-format-and-rtl-packing.md) —
   宽 inst_t vs 64-bit RTL bitfield 的两条输出路径
3. [inst_t 到 PE 物理资源的映射](inst-t-to-physical-resources.md) — inst_t
   字段如何对应 operand slot、block control、PE 坐标
4. [Instruction Capacity Model](instruction-capacity-model.md) — 每 PE 4352 条
   指令的容量约束和 K-instance folding 策略

## 交叉阅读

- [指令集原始材料](../instruction-set/README.md) — 从甲方 Office 文档抽取的
  SIMD/Tensor 指令语义
- [PE 微架构](../pe-microarchitecture/README.md) — PE 寄存器和执行模型
