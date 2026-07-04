# PE 微架构

这个主题聚焦 PE mesh 拓扑、PE 私有寄存器/operand 布局、微架构执行模型和
SIMD lane 解释规则。

## 阅读顺序

1. [PE Mesh 与任务模型](pe-mesh-and-task-model.md) — 4x4 mesh 拓扑、任务
   分片、operand index 是 PE-local 的
2. [PE 寄存器架构与 operand 布局](pe-register-architecture.md) — 通用寄存器、
   mask、RX/LRX、1536 operand slots
3. [PE 微架构执行模型](pe-microarchitecture-execution-model.md) —
   exeBlock → LD / CAL / FLOW / ST 四阶段
4. [SIMD Lane 解释模型](simd-lane-interpretation.md) — operand bits 如何被
   不同 opcode 解释为不同 lane 宽度

## 交叉阅读

- [SoC 系统架构](../soc-system/README.md) — 存储层次和 CBUF/MICC 配置通道
- [指令编码](../instruction-encoding/README.md) — inst_t 字段如何映射到 PE 资源
- [GEMM 案例](../gemm-case-study/README.md) — 这些 PE 能力在 GEMM 中如何使用
