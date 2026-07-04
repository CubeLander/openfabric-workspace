# Task/Subtask Instance Runtime Model

这一页是对旧 `docs/architecture/08-task-subtask-instance-runtime-model.md` 的架构层收口。

先给结论：

```text
task 负责外层轮次
subtask 负责 dataflow 生命周期
instance 负责重复执行次数
graph/exeBlock 负责把这一层落到 PE
```

## 两类 stage

```text
runtime/dataflow 层:
  task -> subtask -> instance -> graph -> exeBlock

PE component 层:
  exeBlock -> LD -> CAL -> FLOW -> ST
```

不要把这两层混在一起读。前者回答“什么时候启动一段工作”，后者回答“一个 PE
内部这段工作怎么被拆开执行”。

## repeat 语义

`subtask2 repeat 4 times` 不是某条 tensor 指令内部的循环立即数，而是 subtask / exeBlock
级的 instance count。runtime 看到这个数后，会对同一张 PE-local graph 启动多个 instance。

不同 instance 通过不同的 base address 处理不同数组区域，但 graph 结构和指令模板可以复用。

## 典型 GEMM 形态

```text
subtask1: load / prepare C
subtask2: repeated A/B compute
subtask3: store C
subtask4: optional fusion epilogue
```

这类结构在 GEMM template fusion case 里最明显，也是我们理解 runtime / MICC / CBUF
关系的最好抓手。

## 交叉阅读

- [pe-microarchitecture-execution-model.md](../pe-microarchitecture/pe-microarchitecture-execution-model.md)
- [runtime/data/cbuf.md](../../runtime/data/cbuf.md)
- [runtime/control/README.md](../../runtime/control/README.md)
