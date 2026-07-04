# GEMM 架构案例

这个主题以 GEMM（矩阵乘法）为核心案例，记录从逻辑 tile 到 PE 执行体的完整
dataflow。GEMM 是我们理解整个系统最稳定的 example。

## 阅读顺序

1. [GEMM Template Fusion Task0 Dataflow](gemm-template-fusion-task0-dataflow.md) —
   task0 的三段主线：读 C → A 广播 + B 读取 + 累加 → 写回 C
2. [GEMM Tile DAG 从 Legacy 示例还原](gemm-tile-dag-from-legacy.md) — 64x64
   硬件 tile、PE 映射、A 广播模式、K-slice 调度
3. [GEMM Operand Strip 与内存访问模型](gemm-operand-strip-memory-model.md) —
   4x64 operand strip、HMMAL tensor tick、编译器 IR 分层建议
4. [HMMAL / RX 累加器绑定模型](hmmal-rx-accumulator-binding.md) — HMMAL 属于
   tensor 指令族，结果经 tmp/accumulator 再通过 TRCTT/RXINT 导出

## 交叉阅读

- [运行时模型](../runtime-model/README.md) — task/subtask/instance 如何组织
- [PE 微架构](../pe-microarchitecture/README.md) — operand strip 在 PE 上的存储
- [指令编码](../instruction-encoding/README.md) — HMMAL 编码和容量约束
