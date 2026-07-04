# DFU Tiny Distributed Tensor Compiler

这份摘录保留的是一个核心判断：

```text
DFU 编译器应该先把用户程序解释成分布式 tensor 语义，
再逐层降低到 PE/tile 级别，最后才进入 task/subtask/instance 与二进制打包。
```

## 保留下来的思想

- 4x4 PE mesh 可以看成一个 16-rank DeviceMesh。
- PE operand RAM 是 rank-local memory。
- SPM 是 shared/global scratchpad memory。
- `COPY/COPYT` 是 point-to-point 或 collective lowering primitive。
- subtask instance times 可以视作 hardware loop / tile stream cursor。
- instance base table 是每个 stream element 的 base address environment。

## 三层编译模型

```text
Layer A: Distributed Tensor Program
  - tensor shape / dtype / layout
  - mesh placement
  - local vs collective semantic intent

Layer B: Per-device Execution Timeline
  - local tensor ops
  - collective/data-movement ops
  - tile residency decisions

Layer C: PE-local lowering
  - instruction/template lowering
  - task/subtask/instance runtime package
```

## 现在还值得保留的具体观点

- compiler 不能只生成“每个 PE 一条很长的程序”，还要先做 resource-legal slicing。
- collective 语义应该保留为 logical intent，再按 tile/chunk 下放。
- chunked collective 比“整块一次性 collective”更接近 DFU 的 runtime 边界。
- 如果 tile 太大，先切 task/subtask/instance，而不是强行塞进一个 PE 时间线。

## 现在不再强调的部分

- 过早假设一个通用、巨大的 dataflow IR。
- 过早把整个 compiler 目标讲成全局最优 scheduler。
- 过宽的 API 想象，尤其是还没有被当前 `compiler/notes/refactor`
  承认的接口形态。
