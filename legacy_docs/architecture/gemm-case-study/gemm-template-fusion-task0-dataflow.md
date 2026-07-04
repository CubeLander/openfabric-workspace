# GEMM Template Fusion Task0 Dataflow

这一页是对旧 `docs/architecture/06-gemm-template-fusion-task0-dataflow.md` 的架构层收口。

它不追求把每个 CSV 行都重新讲一遍，而是把 task0 的 dataflow shape 固定下来。

## task0 的三段主线

```text
subtask1: 读 C 并乘 beta
subtask2: A 广播 + B 读取 + GEMM 累加
subtask3: 写回 C
```

在这个模板里：

- `task0..task3` 更像并行 task slot / 轮次分片
- `subtask` 是 runtime 可见的 dataflow stage
- `subtask2` 里 repeat 4 次，对应 K slice 的重复执行

## 为什么这个页要保留

因为 GEMM 是我们理解整个系统最稳定的 example：

- 它把 task / subtask / instance 说清楚了
- 它把 A/B/C 数据流说清楚了
- 它把 PE mesh 上的 broadcast / copy / compute 说清楚了

## 建议交叉阅读

- [task-subtask-instance-runtime-model.md](../runtime-model/task-subtask-instance-runtime-model.md)
- [pe-microarchitecture-execution-model.md](../pe-microarchitecture/pe-microarchitecture-execution-model.md)
- [runtime/data/cbuf.md](../../runtime/data/cbuf.md)
