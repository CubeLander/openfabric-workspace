# HMMAL / RX Accumulator Binding Model

这一页是对旧 `docs/architecture/09-hmmal-rx-accumulator-binding.md` 的架构层收口。

## 核心结论

`HMMAL` 不是 SIMD 指令页里的普通算术，它属于 tensor 指令族，并且会把结果先落到
PE 内部的 tensor tmp / accumulator 状态，再通过 `TRCTT` / `RXINT` 一类指令导出。

可以先记成：

```text
RXINT  ->  operand / tmp import
HMMAL  ->  tensor tmp update
TRCTT  ->  tmp export back to operand
```

## 为什么要单独成页

因为 GEMM 里那段最费力的 compute 不是“普通寄存器算术”，而是：

- operand strip 进 tmp
- 多条 HMMAL 更新 tmp
- 再把 tmp 导回 operand

这个路径决定了 backend 的 tmp 压力、tmp 生命周期和编译器 lower 顺序。

## 交叉阅读

- [instruction-set/dfu3500-tensor/README.md](../instruction-set/dfu3500-tensor/README.md)
- [instruction-set/dfu3500-tensor/docx/dfu3500-tensor-instruction-doc.md](../instruction-set/dfu3500-tensor/docx/dfu3500-tensor-instruction-doc.md)
- [task-subtask-instance-runtime-model.md](../runtime-model/task-subtask-instance-runtime-model.md)
