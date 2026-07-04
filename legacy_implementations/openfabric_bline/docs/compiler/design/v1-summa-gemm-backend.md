# V1 SUMMA GEMM Backend Design

这份摘录保留的是 GEMM backend 里仍然有效的几条骨架思想：

```text
SUMMA 是第一版 GEMM baseline。
tile phase 是最小可检查计划单元。
row/column reuse 和 vertical fusion 是重要的编译策略。
```

## 保留下来的思想

- A 沿 mesh row 复用，B 沿 mesh column 复用。
- K 维通过 subtask instance loop 做 streaming reduce。
- 所有 PE 执行同构 tile 模板。
- row/column logical collective bundles 在 plan 中显式可见。
- `LocalPhase -> CollectivePhase -> LocalPhase` 是合理的顶层执行形态。

## 仍然有用的分层

```text
DTensor logical action
  -> PE logical action
  -> PE tile phases
  -> instruction template expansion
```

对当前 compiler 来说，这个分层的价值是：

- 保留高层语义；
- 让 tile residency 和 collective obligation 可检查；
- 让后续打包时不会把结构摊平成一坨指令。

## 现在仍值得强调的规则

- GEMM 不是整块 DAG 搜索问题，先用可解释的 SUMMA-style baseline。
- fusion 优先做 vertical tile fusion，不要先做横向摊平。
- `relu(C)` 这类 post-op 应尽量贴在生产 tile 的末尾。
- collective boundary 是硬边界，不能为了漂亮把它藏起来。

## 不再保留的内容

- 过于细碎的早期 backend class 设想。
- 尚未进入当前 lowering 树的旧字段名和旧计划草图。
- 已经被 `compiler/notes/refactor/*` 替代的实现路径。
