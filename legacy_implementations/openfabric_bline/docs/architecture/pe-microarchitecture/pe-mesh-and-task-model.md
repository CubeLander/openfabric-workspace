# PE Mesh 与任务模型

这一页是对旧 `docs/architecture/01-pe-mesh-and-task-model.md` 的架构层收敛。

核心事实先放前面：

```text
PE mesh = 4x4，共 16 个 PE
PE id   = row-major 编号
PE 资源 = 32 个 block slot / 4352 条 instruction / 8 个通用寄存器 / 1536 个 operand slot
```

## 拓扑

```text
PE00 PE01 PE02 PE03
PE10 PE11 PE12 PE13
PE20 PE21 PE22 PE23
PE30 PE31 PE32 PE33
```

每个 PE 都有自己的 instruction memory、block control 和 operand 空间。`COPY/COPYT`
在 PE 之间移动数据，但不会把多个 PE 合并成一个共享寄存器文件。

## 任务分片

当前更稳的高层模型是：

```text
task group
  -> task0..task3
      -> subtask1..subtaskN
          -> graph nodes / exeBlocks
```

在 GEMM 模板里，`task0..task3` 更像并行 task slot / 轮次分片，而不是顺序执行的
四个阶段。真正的顺序主要存在于每个 task 内部的 subtask 链和 PE-local graph 里。

## 这页负责什么

- 说明 PE mesh 怎么编号、怎么映射
- 说明 task / subtask / PE-local block 的关系
- 说明 operand index 是 PE-local 的，不是全局共享的

## 交叉阅读

- [pe-register-architecture.md](pe-register-architecture.md)
- [task-subtask-instance-runtime-model.md](../runtime-model/task-subtask-instance-runtime-model.md)
- [pe-microarchitecture-execution-model.md](pe-microarchitecture-execution-model.md)
