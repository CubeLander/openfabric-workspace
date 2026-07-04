# Tile Program As Source Of Truth

一句话总结：OpenFabric 的主 IR 应该是 **每个 Tensor Core 上的
Tile Program**；全局依赖图不是主存储，而是从 Tile Program、全局唯一
TileValue 名字、以及共享 Logical Collective 引用推导出来的视图。

## Core Model

每个 Tensor Core 维护自己的 Tile Program：

```text
PE00:
  a0 = materialize(...)
  b0 = materialize(...)
  m0 = gemm_tile_update(a0, b0)
  c0 = tile_view(m0, ...)
  y0 = relu(c0)
  store(y0)
```

但这些程序里引用的 TileValue 名字必须是全局唯一的：

```text
tile:A:A:0:0
tile:B:B:0:0
tile_scope:tmp_t1:PE00:0:0:member:k0
tile:tmp_t1:PE00:Cacc:0:0
tile:tmp_t2:PE00:Y:0:0
```

因此，一个 Tensor Core 的本地 Tile Program 不是孤立日志。它是全局程序的
一个投影，因为它引用的是全局唯一的数据名字。

## Logical Collective Is A Shared Program Object

当某个 TileValue 需要在多个 Tensor Core 上可见时，编译器不应该让各个
Tensor Core 偷偷引用同一个值，而应该显式插入一个逻辑 collective /
materialize op：

```text
collective:task0:k0:row0:A:m0:gm0
  input_tile  = tile:A:A:0:0
  output_tile = visible:route:task0:k0:row0:A:m0:gm0
  visibility  = row
  participants = PE00,PE01,PE02,PE03
```

参与这个 collective 的 Tensor Core，在自己的 Tile Program 对应位置引用
同一个逻辑 collective 结果：

```text
PE00:
  a0 = collective:task0:k0:row0:A:m0:gm0.output
  m0 = gemm_tile_update(a0, b0)

PE01:
  a0 = collective:task0:k0:row0:A:m0:gm0.output
  m0 = gemm_tile_update(a0, b0)

PE02:
  a0 = collective:task0:k0:row0:A:m0:gm0.output
  m0 = gemm_tile_update(a0, b0)

PE03:
  a0 = collective:task0:k0:row0:A:m0:gm0.output
  m0 = gemm_tile_update(a0, b0)
```

这意味着：

```text
Logical Collective = 全局共享的可见性事实
Tensor Core Tile Program = 对这个事实的局部引用
```

`row_broadcast`、`column_broadcast`、`COPYT`、DMA fanout 等具体传播方式不
属于这个层级。它们是后续 route lowering / physical lowering 的选择。

## Logical Collective Lowers To Tile Collective Actions

Logical collective 不是后端原子操作。它可以继续分解：

```text
LogicalCollective
  -> TileCollectiveAction per participating Tensor Core
  -> PE-local DFU GRAPH_NODE / instruction block
  -> cross-PE graph edges
```

也就是说，logical collective 在 Tile Program 中是一个全局共享对象；参与同一个
logical collective 的 Tensor Core，在各自的本地 Tile Program 中引用同一个
`logical_collective_id`。随后 collective lowering 会为每个参与者生成更细粒度的
tile collective action：

```text
tile_collective_action:
  logical_collective_id = collective:task0:k0:row0:A:m0:gm0
  local_role            = source | forward | consumer | local_only
  input_tile            = ...
  output_visible_tile   = ...
  participant_pe        = PEij
```

这些 tile collective action 仍然属于 Tile Program / dependency world，而不是最终
二进制。DFU 后端再把它们 lower 成 PE-local graph nodes 和跨 PE graph edges。

这个分层很重要：

```text
logical collective:
  表达全局 visibility / materialization 语义。

tile collective action:
  表达每个 Tensor Core 在这个 collective 中负责哪一小段 tile 交换或可见性转换。

DFU graph node/edge:
  表达甲方 runtime 能执行的 PE-local code block 和跨 PE dependency。
```

因此，块依赖不必粗粒度依赖整个 logical collective。后续构建细粒度 DAG 时，一个
instruction block / graph node 可以声明自己依赖某些具体 tile collective actions：

```text
compute_tile(C_ij_k)
  depends_on:
    tile_collective_action(logical_collective=A_row_visible, output=A_i_k_visible)
    tile_collective_action(logical_collective=B_col_visible, output=B_k_j_visible)
```

这样既保留了 logical collective 的全局身份，又允许后端做更细粒度的 block dependency、
task/subtask packing 和 route scheduling。

## Dependency Graph Is A Derived View

只要 Tile Program 中的每个 TileOp 都记录：

```text
input_tiles[]
output_tiles[]
```

依赖关系就已经存在：

```text
input tile -> TileOp -> output tile
```

例如：

```text
gemm_tile_update
  inputs  = [A_visible, B_visible]
  outputs = [Cacc_member_k0]
```

天然推出：

```text
A_visible -> gemm_tile_update
B_visible -> gemm_tile_update
gemm_tile_update -> Cacc_member_k0
```

所以全量 dependency graph 不应该成为默认 dump，也不应该成为第一主存储
结构。它更像 LLVM 的 use-def chain：可以从程序中推导，可以用于分析和
lowering，但不应该压过程序本体。

## Preferred Layering

```text
Per-TensorCore Tile Program
  + globally unique TileValue names
  + shared Logical Collective references
    ↓
Derived Dependency View
    ↓
DFU Runtime Graph Lowering
    ↓
Task/Subtask/Instance Packing
    ↓
Operand/Base Allocation
    ↓
Binary Encoding
```

这条链路里：

```text
Tile Program
  是程序本体。

Dependency View
  是分析视图。

TraceTile
  是解释查询。

DFU Graph
  是 backend lowering 结果。
```

## Dump Implication

默认人类可读 dump 应该展示 Tile Program，而不是全量边表。

推荐默认视图：

```text
SUMMARY
  tile op / collective / trace 总数

TILE REGISTRY
  TILE_VALUE_ALIAS:
    短 id -> logical tile value
  TILE_INSTANCE_ALIAS:
    短 id -> (logical tile value, location)

TENSOR CORE TILE PROGRAM
  按 PE 展示 TC_OP 序列
  每条 TC_OP 只引用短 tile instance id
  collective lowering 作为 tile_collective_use / TileCollectiveAction 出现在程序中

DERIVED DEPENDENCY VIEW
  只展示依赖类型统计和少量代表样例
  完整 LOCAL_TILE_DEP / VISIBILITY_DEP / BLOCK_DEP_HINT 放 verbose dump

EXPLAIN
  展示少量 TRACE_TILE，说明 output tile 如何反向追溯到 input tiles
```

完整边表仍然有价值，但应该进入 verbose 文件：

```text
15_tile_dependencies.verbose.lines.txt
```

默认文件应该回答：

```text
这个 tile program 长什么样？
某个短 tile id 对应哪个逻辑 tile / 哪个位置？
哪些 collective 是全局共享对象？
一个 output tile 怎么来的？
完整依赖视图在哪里？
```

## Design Consequence

后续做 task/subtask/instance packing 时，算法可以从 Tile Program 派生出
dependency view，再在 dependency view 上识别：

```text
repeated tile program fragment
visibility/materialization boundary
resource-pressure boundary
backend-control edge
```

这比直接在全量 edge dump 上做算法更稳，因为程序结构仍然保留在
TileOp 序列里。
