# GEMM vendor graph / CSV layout notes

Date: 2026-06-29

这份笔记记录 `gemm_template_fusion` 里一个容易误解的事实：
vendor 的 `task*/subtask*/template/<N>.csv` 不是严格意义上的
“PE 文件”，而是 **graph node 绑定的 instruction block 文件**。

这个结论解释了为什么 GEMM 的 `subtask2` 会有 `csv_amount:32`。
它不是 32 个 PE，也不是 “16 个汇编文件 + 16 个 graph 依赖文件”；
它是 32 个 graph node，各自绑定一个 CSV instruction block。

## Vendor package shape

每个 vendor subtask 目录大致有两类输入：

```text
task0/subtask2/template/0.csv
task0/subtask2/template/1.csv
...
task0/subtask2/template/31.csv

task0/subtask2/build_so/test_graph_extend.cpp
```

`template/<N>.csv` 是一块 instruction template。`build_so/test_graph_extend.cpp`
实现：

```cpp
extern "C" void generateGraph(...);
```

它创建 `GRAPH_NODE`，并通过：

```cpp
m_graph_extend.initNode(m_nodes[index], index, ..., inst_block_collect);
```

把 graph node `index` 绑定到 `template/<index>.csv`。

依赖关系不是另一批单独的文件。依赖边由同一个 `generateGraph(...)`
里的 `set_relationship_node(...)` 调用创建。

## What `csv_amount` means

`app0.conf` 里 GEMM 的三个 subtask 是：

```text
subtask1: csv_amount:16
subtask2: csv_amount:32
subtask3: csv_amount:16
```

这里的 `csv_amount` 是当前 subtask 的 graph-node / instruction-block
数量，也就是 `template/0.csv` 到 `template/<csv_amount-1>.csv` 的数量。

对 `subtask1` 和 `subtask3`，vendor graph 形态比较接近一 PE 一个 node：

```text
16 PE-like graph nodes
16 CSV instruction blocks
```

对 `subtask2`，vendor 把一个 GEMM 协作阶段拆成多类 graph nodes：

```text
4  input0 root-load nodes
12 input0 copy nodes
16 input1 load + compute nodes
---
32 graph nodes / CSV instruction blocks
```

所以 `subtask2/template/0.csv..31.csv` 的逻辑分段是：

```text
0..3    input0 root-load instruction blocks
4..15   input0 copy instruction blocks
16..31  input1 load + compute instruction blocks
```

这些 node 仍然带有 PE 位置。例如 graph code 会设置：

```cpp
m_nodes[index].m_pos_idx_df = pe_id;
```

但是 vendor graph node 数量不等于 PE 数量。

## Dependency shape in subtask2

`subtask2/build_so/test_graph_extend.cpp` 还会在这些 node 之间建边。
重要关系包括：

```text
root-load -> compute
root-load -> copy
copy -> copy
copy -> compute
```

这说明 vendor 用 “多个 graph nodes + 每 node 一个 CSV block” 来表达
GEMM 中 input0 广播、PE 间 copy、以及 input1 load/compute 的合作关系。

## OpenFabric interpretation

OpenFabric 不应该把 vendor 的 32 个 CSV block 暴露成 32 个逻辑 PE sink。

更合适的抽象是：

```text
SubtaskSite(task, subtask)
  owns the logical subtask program surface
  tracks the active subject PE
  accepts local and cross-PE actions

Vendor backend
  lowers those actions into vendor graph nodes
  writes each node's instruction rows into the required template/<N>.csv
  emits the graph edges required by generateGraph(...)
```

也就是说：

```text
OpenFabric logical view:
  16 PE positions running a flat subtask program with communication actions

Vendor package view:
  subtask2 is serialized as 32 graph-node instruction blocks
```

当前手写算子阶段先不自动推断这些 graph-node / instruction-block 归属。
更直接的程序形态是：每个原子 fiber 动作直接接收 `instruction_block_id`，
这个动作本身就是一个 vendor instruction block 的生成边界。

例如 `subtask2` 的主程序可以显式写出：

```text
input0_root_load(0..3, ...)
input0_copy(4..15, ...)
input1_load_and_compute(16..31, ...)
```

subtask site 持有当前 subtask 的文件集合和 assembler 协议，负责把动作
append 到 `template/<instruction_block_id>.csv`，并校验 block id 是否落在
当前 subtask 的 `csv_amount` 范围内。主过程不直接 fopen，也不操作 CSV 路径；
但它应该清楚暴露 vendor block 编号，因为这是当前甲方硬件/assembler 协议的
真实复杂度。

## Practical consequence for the GEMM refactor

不要把 `csv_amount:32` 直接解释成 “subtask2 有 32 个 OpenFabric sinks”。
它只是当前 vendor assembler/package surface 的 graph-node 数量。

因此，GEMM device source 里的目标方向应该是：

```text
flat subtask program
  -> explicit data refs and communication actions
  -> atomic actions carry instruction block ids
  -> site/backend writes those actions to vendor graph-node CSV blocks
```

而不是：

```text
subtask program
  -> root-load table + copy table + compute table as first-class logical sinks
```

后者会把 vendor graph-node layout 泄漏到 OpenFabric 的主程序形态里。
