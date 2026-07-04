# PE Microarchitecture Execution Model

这一页是对旧 `docs/architecture/07-pe-microarchitecture-execution-model.md` 的架构层收口。

核心模型：

```text
graph node
  -> exeBlock
      -> LD stage
      -> CAL stage
      -> FLOW stage
      -> ST stage
```

## 关键边界

- `LD` 负责 SPM -> PE operand RAM
- `CAL` 只看 PE-local operand RAM 和内部状态
- `FLOW` 负责 PE 间数据流
- `ST` 负责 PE operand RAM -> SPM

这意味着计算指令并不直接操作 SPM；SPM 是通过 LD/ST 和更外层 runtime 流程进入 PE 的。

## 对 runtime 的意义

一个 PE 上的 block 不是一条指令，而是一段按 stage 组织的执行片段。`block_idx`、
`stages_start_pc[]`、`pending_activations`、`pending_acks` 这类字段就是在支撑这个模型。

## 对 GEMM 的意义

GEMM 的 compute node 之所以看起来“很大”，是因为它往往把一批 LD/CAL/FLOW/ST 指令
都挂在同一个 PE-local graph node 上，而不是把每个 scalar 操作拆成一个 node。

## 交叉阅读

- [inst-t-to-physical-resources.md](../instruction-encoding/inst-t-to-physical-resources.md)
- [task-subtask-instance-runtime-model.md](../runtime-model/task-subtask-instance-runtime-model.md)
- [runtime/data/rtl.md](../../runtime/data/rtl.md)
