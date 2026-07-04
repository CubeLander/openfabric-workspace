# First-Class Collective Actions

一句话总结：collective 不应该只是计算计划旁边的说明表，而应该和 compute 一样，成为 PE/tile program 时间线中的一等 action；区别只在于 collective action 需要跨 PE 的 participants、roles 和 physical route lowering。

## Motivation

当前 trace 把事情分成了：

```text
Layer 3/4:
  PE 内部 tile compute

Layer 5:
  consumed collective bundles
```

这种分层对阅读有帮助，但容易让人误解：好像 collective 只是 compute 的附属注释。

真实执行模型不是这样。一个 PE 实际做的事情应该是一串程序 action：

```text
PE program = Action*

Action =
  local compute
  data movement / collective
  materialize / store
  barrier
```

也就是说，collective 和 compute 在同一个程序平面内。Layer 5 现在更像一个 registry 或 data-origin index，而不是主程序时间线本身。

## Core Model

我们应该把 tile-level program 建模成：

```text
TileProgram
  actions[]

TileAction
  ComputeTileAction
  CollectiveTileAction
  MaterializeTileAction
  BarrierAction
```

Naming note: if `CollectiveTileAction` starts to feel too narrow for
`CollectiveLoad` / `CollectiveStore`, we can later rename the implementation
class to `DataMovementTileAction`. For V1, keep `CollectiveTileAction` because
the document defines collective broadly as any chip-level action that changes
visibility, ownership, or layout.

其中 compute 和 collective 都可以沿同一条 lowering 链路 materialize：

```text
tensor-level intent
  -> PE-level logical action
  -> tile-level action
  -> physical instruction / protocol
```

对于 compute：

```text
matmul / relu / log10 / maximum
  -> per-PE logical compute
  -> per-tile compute action
  -> HMMAL / SIMD / store instruction sequence
```

对于 collective：

```text
layout distribute / broadcast / reduce / redistribute
  -> per-PE logical collective role
  -> per-tile collective action
  -> DMA / COPY / COPYT / base-address protocol
```

## Compute vs Collective

Compute 的规律是：

```text
all PEs execute the same logical local kernel shape
parameters differ by PE coordinate / tile coordinate
```

例如 GEMM 的每个 PE 都在做：

```text
C_ij += A_i_k @ B_k_j
```

只是 `(i, j, k)` 不同。

Collective 的规律不同：

```text
all PEs participate in the same protocol instance
each PE derives its local behavior from the same SPMD rule
```

例如 row broadcast：

```text
collective_id = row0.A.k0.materialize

program:
  source_col = k_step % mesh_cols
  source_coord = (my_row, source_col)
  participate in row visibility materialization
```

所有 PE 执行同一份程序，只是 `my_row/my_col/k_step` 不同，所以本轮算出来的
`source_coord`、consumer group、local input view 不同。如果后端选择多跳
COPYT，physical route 里可能继续细分 source / relay / sink：

```text
source
relay
sink
consumer
```

但这些不应该在 chip-level 或 tile visibility planning 阶段手工写成
PE-specific 身份分配。它们应该来自同一份 Mesh-SPMD 程序的参数化实例，或者来自更靠后的 physical route lowering。

所以 collective 的同构性不在于“所有 PE 做完全相同的数据搬运”，而在于：

```text
所有参与 PE 执行同一个 Mesh-SPMD collective/materialization program。
```

## Logical And Physical Collective

Collective 也需要分层，不能一开始就落到 COPY/COPYT。更准确地说，route
应该是 tile action indifferent 的：tile action 描述“逻辑上发生了什么”，route
描述“物理上怎么搬”。两者处在不同决策阶段，V1 暂不做 compute/collective/route
的协同规划。

```text
Logical collective:
  kind
  tensor/tile identity
  participants
  source/destination layout
  per-PE logical role

Tile collective:
  tile_scope / tile_ref
  task / instance placement
  dependency edges with compute actions
  per-PE tile role

Physical collective:
  COPY/COPYT/DMA instructions
  concrete source PE / relay PE / sink PE
  base-address table / offset protocol
```

V1 可以先保留 physical route 为 `unresolved`，但 logical action 必须出现在程序时间线里。

这意味着：

```text
CollectiveTileAction is route-independent.
PhysicalCollectiveRoute is a later lowering artifact.
```

同一个 logical/tile collective action 可以被不同 physical route 实现：

```text
row_broadcast(A0)
  -> direct COPY from source PE
  -> multi-hop COPYT
  -> DMA/SPM-backed fan-out
```

这些 route 选择不应该反过来改变上层 tile action 的语义。

## Chip-Level Generalized Collectives

在继续设计前，最重要的事情是先想清楚：

```text
从整个 chip 视角看，有哪些逻辑广义 collective 动作？
```

这里的 collective 不限于传统分布式通信 API。只要一个动作改变了 tensor
在 chip 内部多个存储/PE 之间的可见性、所有权或 layout，就可以视为 generalized
collective。

V1 可以先列出这些 logical chip collective：

```text
CollectiveLoad:
  external/shared memory tensor region
    -> chip-visible logical tensor layout
  optional attrs:
    visibility_requirements = [
      tensor must become visible along mesh rows / mesh columns / full mesh / ...
    ]

MeshBroadcast:
  one tile/source endpoint
    -> a 2-D PE group

CollectiveReduce:
  partial tile/summary values on PE group
    -> reduced value on one or more destination PEs

ReduceScatter:
  partial values on PE group
    -> sharded reduced values

AllGather:
  sharded values on PE group
    -> replicated or wider visible value

CollectiveStore:
  distributed PE-local tile values
    -> external/shared memory tensor layout
```

The broader primitive set for model inference is:

```text
CollectiveLoad:
  global/shared tensor layout
    -> PE/TensorCore-visible logical values

CollectiveStore:
  PE/TensorCore-visible logical values
    -> global/shared tensor layout

Broadcast / MeshBroadcast:
  one logical value or shard
    -> replicated visibility over a PE group
  Row/column propagation can be selected by later lowering when the PE group is
  a mesh row or mesh column. It should not be forced into the chip-level
  `CollectiveLoad` layer as a parallel action.

Scatter / Shard:
  replicated/full logical value
    -> sharded logical values over a PE group

Gather:
  sharded logical values
    -> one destination logical value

AllGather:
  sharded logical values
    -> replicated wider/full logical values over a PE group

Reduce:
  partial logical values
    -> reduced logical value on one or more destination PEs

AllReduce:
  partial logical values
    -> replicated reduced logical value over the PE group

ReduceScatter:
  partial logical values
    -> sharded reduced logical values

Reshard / Redistribute:
  source DTensor layout
    -> destination DTensor layout
  This is a semantic layout transformation. It may lower to combinations of
  scatter, gather, all_gather, reduce_scatter, broadcast, or reduce.

AllToAll / Dispatch / Combine:
  token/expert or route-indexed logical values
    -> group-shuffled logical values
  This is mostly for future MoE-style kernels.
```

For the first two targets:

```text
SUMMA GEMM baseline:
  CollectiveLoad(A, with later row-visibility requirement)
  CollectiveLoad(B, with later column-visibility requirement)
  Matmul(A, B, with input visibility requirements)
  CollectiveStore

log10 -> max -> maximum:
  CollectiveLoad
  Reduce(max) or AllReduce(max)
  Broadcast/Replicate reduced max if needed
  CollectiveStore
```

The question each primitive answers is:

```text
What tensor value should become visible to which PE/TensorCore group,
under which logical layout?
```

It does not answer:

```text
What is the tile size?
Which COPY/COPYT/DMA route realizes it?
Which subtask contains the final instruction?
```

One important modeling rule:

```text
Do not put RowBroadcast / ColumnBroadcast beside CollectiveLoad at the same
chip-level layer when they merely describe how a loaded tensor may propagate.
```

At chip level, `CollectiveLoad` owns the ingress/layout materialization
semantics. A later compute action, such as `Matmul`, may attach requirements
like:

```text
A must be visible to all consumers in the same mesh row.
B must be visible to all consumers in the same mesh column.
```

Those are requirements, not physical or tile-level propagation actions. A later
lowering pass can choose row broadcast, column broadcast, DMA fan-out, direct
loads, multi-hop COPYT, or a mixed protocol based on mesh link pressure and
resource scheduling. This keeps the first layer route-independent and avoids
duplicating semantics between `CollectiveLoad` and `RowBroadcast`.

The dump should make that distinction visible:

```text
CollectiveLoad(A):
  visibility_contract = mesh_rows
  consumer_scope = matmul#0

Matmul(A, B):
  requires_visibility = A:mesh_rows, B:mesh_columns
```

`visibility_contract` answers what visibility is required. `consumer_scope`
answers which logical consumer introduced the requirement. Neither field says
which propagation protocol will be used.

`CollectiveLoad` 很关键，因为以 shard 形式 load tensor，本质上就是一个 chip
视角下的逻辑 collective：

```text
global tensor A
  -> layout [Shard(0), Replicate()]
  -> PE-local A shards / visible tile values
```

它不是单个 runtime op，也不是普通 load 指令的集合，而是一个有全局 layout
语义的 chip-level semantic action。它不应该直接展开成 tile action；中间必须
先落到 TensorCore-level logical collective action，再由后续 pass 选择 tile
粒度并展开成 tile-level actions，最后 materialize 成 DMA、SPM staging、
row/column fan-out 或 PE-local direct load：

```text
CollectiveLoad(A, layout=[Shard(0), Replicate()])
  -> TensorCoreLogicalCollectiveAction(group=PE mesh, layout obligation)
  -> many CollectiveTileAction / LoadTileAction records after tiling decision
  -> many physical DMA/COPY/COPYT/load commands
```

`CollectiveStore` 应该和 `CollectiveLoad` 对称进入 V1 schema。即使 GEMM V1
暂时只是把每个 PE 的 output shard 普通写回，chip 视角下它仍然是在 materialize
一个 global output layout：

```text
PE-local Y tile values
  -> CollectiveStore(Y, layout=[Shard(0), Shard(1)])
  -> external/shared memory tensor region
```

这样 input layout materialization 和 output layout materialization 共享同一个
generalized collective 语义框架。

The layering should stay deliberately gradual:

```text
Chip-level generalized collective:
  What layout/visibility/ownership transformation does the whole chip need?

TensorCore-level logical collective:
  What does each PE/TensorCore logically participate in?

Tile-level collective action:
  What concrete tile-sized value is produced/consumed by one scheduled region?

Physical route:
  Which DMA/COPY/COPYT/load command protocol realizes it?
```

Keeping this extra TensorCore-level layer preserves design space. Future
backends may change tile size, vector width, or scheduling granularity without
rewriting the chip-level `CollectiveLoad` / `CollectiveStore` semantics.

## Data Loading Is Collective

输入 tensor 的加载和扩散也应该被视为一种特殊 collective，而不是隐藏在 compute 前面的 magic load。这个动作可以具体命名为 `CollectiveLoad`。

例如 SUMMA GEMM 中：

```text
A tile from SPM/DRAM/CBUF
  -> row_broadcast
  -> PE operand view

B tile from SPM/DRAM/CBUF
  -> column_broadcast
  -> PE operand view
```

这可以被建模为 ingress collective，或者更一般地建模为 `CollectiveLoad`
携带的 visibility requirement。`row_broadcast` / `column_broadcast` 是后续
lowering 可能选出来的实现策略，而不是和 `CollectiveLoad` 平行的 chip-level
action：

```text
CollectiveLoad(A, layout=[Shard(0), Replicate()])
  attrs.visibility_requirements += [
    A visible along mesh rows for Matmul(A, B)
  ]
  -> TensorCoreLogicalCollectiveAction(kind=selected_by_lowering)
  -> many CollectiveTileAction(kind="ingress_row_broadcast")

CollectiveLoad(B, layout=[Replicate(), Shard(1)])
  attrs.visibility_requirements += [
    B visible along mesh columns for Matmul(A, B)
  ]
  -> TensorCoreLogicalCollectiveAction(kind=selected_by_lowering)
  -> many CollectiveTileAction(kind="ingress_column_broadcast")
```

如果 lowering 最终选择 SUMMA-style ingress，那么 tile 层可以出现
`ingress_row_broadcast` / `ingress_column_broadcast`。如果未来发现链路压力或
片上缓存状态更适合别的协议，chip-level program 不需要改。

它和 PE-to-PE collective 共用同一套逐层 lowering 表达，只是 source endpoint
不同：

```text
source endpoint = shared memory / DMA-visible region
source endpoint = another PE
```

这样 load 阶段和计算阶段就能被同一个 scheduler 看见：

```text
CollectiveLoad produces TensorCore-level logical obligations.
Tile collective actions produce local visible A/B tile values.
Compute tile actions consume those local visible values.
```

## Mesh-SPMD Tile Residency Planner

The collective planner should be modeled more precisely as a tile residency
planner. Visibility is the semantic contract exposed by upper IR layers;
residency is the planner's implementation-level state model.

The full lowering chain is:

```text
Logical DTensor Program
  -> Chip-level Collective / Compute Intent
  -> Visibility Contract
  -> Mesh-SPMD Tile Residency Plan
  -> Micro-Step BSP Schedule
  -> Per-PE Tile Actions
  -> Physical Route / Instruction Lowering
```

This is the point where the design becomes an intermediate representation for a
distributed tensor compiler, not merely a communication mechanism description.

It should not first ask:

```text
How do we load this whole tensor?
```

It should ask:

```text
For this TileScope / K-step / reduce step,
which logical input tile values must become visible to which PE group?
```

Internally, it should also ask:

```text
Where does this tile first appear?
Which PE/group owns or materializes it?
Who consumes it?
How long does it stay resident?
When can it be released or reused?
```

The planner output should therefore be a Mesh-SPMD tile residency program:

```text
chip-level visibility contracts
  -> tile demand
  -> Mesh-SPMD tile residency/materialization steps
  -> micro-step BSP schedule
  -> instantiated per-PE tile actions
  -> physical route lowering
```

This keeps the program homogeneous. We do not generate a separate hand-written
program for PE00, PE01, and so on. We generate one SPMD program for the mesh,
and each PE instantiates it with its coordinate:

```text
for step in steps:
  materialize_inputs(step, coord)
  barrier
  compute_local_tile(step, coord)
  barrier
```

`source rotation` is not a PE-specific role assignment. It is an expression in
the SPMD program:

```text
A row visibility:
  source_coord = (my_row, k_step % mesh_cols)
  consumer_group = row(my_row)

B column visibility:
  source_coord = (k_step % mesh_rows, my_col)
  consumer_group = column(my_col)
```

So every PE executes the same logical task:

```text
decide whether I am this step's source for my group
materialize / participate in visibility
consume the visible tile if my local compute needs it
```

The parameters differ by `coord`, `step_id`, `tile_ref`, and layout. This is a
Mesh-SPMD model:

```text
Single mesh program, multiple PE coordinates / tile data.
```

The key IR object is a residency/materialization step, not a broadcast command:

```text
SPMDMaterializeStep:
  step_id
  tile_ref
  visibility_contract = row | column | mesh | local | scalar_replicated
  residency = produced | resident | consumed | released
  source_policy = rotate_within_group(axis, step_id)
  source_coord_expr
  consumer_group_expr
  lifetime = [first_visible_step, last_consumer_step]
  route_status = unresolved

SPMDComputeStep:
  step_id
  op
  input_views
  output_view
  coord_exprs
```

For GEMM V1:

```text
A tile:
  visibility_contract = row
  source rotates across columns inside the row group

B tile:
  visibility_contract = column
  source rotates across rows inside the column group

C tile:
  owner PE accumulates locally
```

This lets A-load and B-load planning be aware of each other at the same
superstep. The physical route planner can later decide whether the two
materialization steps can run together, need staging, or should be serialized
because of mesh link pressure.

For `log10 -> max -> maximum`, the same model applies:

```text
local map:
  every PE applies log10 to its local tile view

collective reduce:
  every PE participates in one SPMD reduce visibility step
  coord decides source/sink/local contribution behavior

post-reduce map:
  every PE consumes the scalar/replicated max visibility and applies maximum
```

The important design principle:

```text
Propagation method is not semantics.
Visibility contract is semantics.
SPMD materialization is the first lowering of that semantics.
COPY/COPYT/DMA route is a later lowering.
```

## Ordered SPMD Demand-Frontier Materialization

Tile materialization should be just-in-time at the ordered tile-step level.

The planner should not materialize all A/B shards just because the whole
operator will eventually need them. Instead, it should follow the ordered SPMD
compute sequence:

```text
for each ordered SPMD tile step:
  derive the current tile demand frontier
  materialize only the input tiles needed by this frontier
  run local compute for this relative tile position
  keep visible values alive until the consumer window closes
  then reuse or evict storage
```

The "use" in just-in-time materialization is tile-level use, not
instruction-level use. V1 should stay at a coarse, reviewable granularity:

```text
task/subtask
  -> SPMD superstep
  -> TileScope / relative tile step
  -> K-step materialization
```

For GEMM, this is exactly why the regular SUMMA shape is a good first
specialization. Suppose each Tensor Core owns a local `3x3` region of C tiles
and all Tensor Cores visit the relative positions in the same order:

```text
1 2 3
4 5 6
7 8 9
```

When every PE computes its relative tile `1`, the absolute C tile differs by
PE coordinate, but the dependency pattern is homogeneous:

```text
relative C tile 1
  needs one A tile visible over the PE row
  needs one B tile visible over the PE column
```

That current demand frontier can be materialized with local micro-collectives:

```text
materialize A tile for row group
materialize B tile for column group
compute relative tile 1
```

Then all PEs advance to relative tile `2` and repeat. This gives high data
reuse because PEs aligned on the same relative tile step share row/column input
tiles at the same time. It also keeps chip storage pressure low because older
visible tiles can be released once their consumer window closes.

This schedule can be viewed as:

```text
SPMD ordered tile demand frontier
```

For V1, that frontier evolution is scheduled as a Micro-Step BSP program:

```text
for micro_step in ordered_frontier:
  materialize demand frontier
  visibility barrier
  compute frontier
  lifetime/update barrier
```

This means the compiler is not primarily emitting "the next instruction" at
this layer. It is emitting frontier evolution:

```text
which tiles appear
where they become visible
which local computation may fire
which values can be released
```

That is why this model matches DFU better than a single-core instruction
scheduler view. A 4x4 PE mesh behaves like a small distributed tensor machine;
Micro-Step BSP is the conservative V1 schedule form for that machine.

SUMMA is the GEMM-specific case where the frontier contains row-visible A tiles,
column-visible B tiles, and local C accumulation.

The key benefits are:

```text
1. avoid preloading whole tensors into limited on-chip storage
2. make row/column micro-collectives coincide with actual tile demand
3. maximize reuse inside one relative tile step
4. align naturally with task/subtask barriers
5. allow fused local ops to run while the TileScope values are still hot
```

## Tile-Centered Fusion And Tile Lifetime

Fusion is declared at the top-level DTensor program, but the useful fusion
object in this backend is a tile lifetime.

For example, the user writes:

```python
Y = relu(A @ B)
```

At the logical DTensor level, this is:

```text
Matmul
  -> Relu
```

At tile residency level, the actual opportunity is:

```text
materialize A/B tiles
  -> compute C tile members
  -> form C TileView
  -> relu(C TileView)
  -> store Y tile
  -> release C tile state
```

The fused unit is therefore not the whole intermediate tensor `%t1`; it is each
TileScope while its values are still resident. This is why Layer 3's
`inputs / values / view / ops / output` form is important: it shows tile value
lifetime directly.

This gives a different optimization target from traditional operator fusion:

```text
Traditional operator fusion:
  fuse Matmul + Relu at tensor/operator boundary

Tile-centered fusion:
  keep a produced tile view hot
  consume it immediately with local post-ops
  avoid materializing/reloading the intermediate tensor
```

The distinction matters for mixed local/collective chains such as:

```text
log10
  -> max reduce
  -> maximum
```

A tensor-level fusion pass may stop at the collective reduction. A
tile-lifetime view can still preserve useful local lifetimes:

```text
local tile
  -> log10
  -> local summary
  -> collective reduce(max)
  -> replicated/scalar max visibility
  -> maximum(local tile, max)
```

The compiler can therefore share one value dependency graph across compute,
collective materialization, and fusion:

```text
Visibility Contract
  -> Tile Materialization
  -> Tile Residency / Lifetime
  -> Tile-Centered Fusion
```

This is also measurable. A baseline may do:

```text
Matmul
  -> store C
Relu
  -> load C
  -> store Y
```

The tile-centered path does:

```text
C tile produced
  -> relu immediately
  -> store Y
```

Useful metrics include:

```text
intermediate tensor store/load bytes
SPM residency pressure
DDR bytes
materialization count
tile lifetime length
number of fused TileScope-local ops
```

This suggests a later `Tile Lifetime Optimizer`: maximize tile reuse while
minimizing materialization and intermediate residency cost. It is consistent
with the broader IR philosophy: the compiler is operating in a
`Tile / Visibility / Lifetime` coordinate system, while the user still writes a
normal DTensor program.

## V1 Scheduling Boundary

第一版不追求复杂 overlap。最稳的调度边界是 Micro-Step BSP tile superstep：

```text
for each micro-step / schedulable tile scope:
  1. materialize only this ordered demand frontier's input tile actions
  2. visibility barrier
  3. run local compute actions
  4. lifetime/update barrier
  5. materialize output collective actions if required
  6. store / move to next tile
```

也就是：

```text
collective_in
barrier
compute
barrier
collective_out
```

最多做到“算完一个 tile，collective 一次”。如果没有 output collective，就直接 store 或暴露 tile view 给后续本地 op。

So V1 is not:

```text
load all operator inputs
compute all local tiles
```

It is:

```text
for relative tile step in SPMD order:
  materialize the current frontier
  compute that frontier
  release or reuse values
```

这和 DFU 的 task/subtask/instance 模型比较契合：

```text
subtask as barrier-friendly region
collective participants align at region boundary
tile-level actions remain inspectable
```

未来优化可以考虑：

```text
collective_in(next tile) overlaps compute(current tile)
```

但 V1 暂不做 pipeline。

## Program View And Registry View

Trace 应该分成两个互补视图：

Each PE trace should explicitly say that it is a projection:

```text
TRACE_SCOPE pe_projection
mesh_shape=4x4
coord=(0,0)
projection_policy=chip_actions_projected_to_local_values
registry_scope=consumed_collectives_only
```

This matters because a single trace mixes local projection with selected global
registry facts. The header should make clear that the PE trace is not the full
global program.

### Program View

回答：

```text
这个 PE 按什么顺序做什么？
```

例子：

```text
TILE_SCOPE tile0:
  collective_in:
    a0 = materialize A[0:64,0:64] visibility=row route=unresolved
    b0 = materialize B[0:64,0:64] visibility=column route=unresolved

  values:
    m0_0 = HMMAL(a0, b0)
    m0_1 = HMMAL(...)

  view:
    c0 = tile_view(owner, values=m0_*, combine=matmul_reduce_k)

  ops:
    y0 = relu(c0)

  output:
    y0 -> %t2:Y[0:64,0:64]
```

The main narrative should use materialization and visibility wording. It should
not expose `row_broadcast` / `column_broadcast` as if they were high-level
semantics. Those names belong in the registry/route view as one possible
backend realization.

### Registry View

回答：

```text
某个 collective protocol instance 的全局事实是什么？
```

例子：

```text
COLLECTIVE row0.A.k0.broadcast:
  kind = row_broadcast
  realized_from = visibility(row)
  logical_tile = A[0:64,0:64]
  participants = PE00, PE01, PE02, PE03
  roles:
    PE00 = source_and_consumer
    PE01 = receiver_and_consumer
    PE02 = receiver_and_consumer
    PE03 = receiver_and_consumer
  physical_route = unresolved
```

Layer 5 更适合长期变成 registry view，而不是主程序叙事层。主程序叙事层应该直接包含 collective actions。

## Dependency Model

Compute action 和 collective action 都应该产生/消费 value。

```text
CollectiveTileAction:
  inputs:
    source tile or source value
  outputs:
    local visible tile value

ComputeTileAction:
  inputs:
    local visible tile values
  outputs:
    member values / tile views / summary values
```

这样调度器看到的是统一的 value dependency graph：

```text
collective_in(A_tile) -> local A value
collective_in(B_tile) -> local B value
local A/B values -> HMMAL member values
member values -> tile view
tile view -> relu / store / collective_out
```

这个统一依赖图能回答：

```text
一个 PE 什么时候可以开始算？
一个 tile 什么时候可以被 collective？
一个 collective group 中哪些 PE 必须对齐？
```

## Residency Planning, Not Manual Role Assignment

Collective 需要额外的 residency planning pass。这个 pass 不应该手工为每个
PE 写死 role，而应该生成 SPMD source/consumer/lifetime expressions。

输入：

```text
visibility contract
tile demand
consumer group expression
logical source tile identity
mesh topology
available data paths
```

输出：

```text
SPMD residency/materialization step
source_coord_expr
consumer_group_expr
lifetime_expr
per-PE tile action after instantiation
optional physical route after route lowering
```

V1 可以使用简单规则：

```text
row visibility:
  consumer_group_expr = row(my_row)
  source_coord_expr = (my_row, step_id % mesh_cols)

column visibility:
  consumer_group_expr = column(my_col)
  source_coord_expr = (step_id % mesh_rows, my_col)

reduce:
  consumer_group_expr = reduction_group(layout)
  sink_coord_expr chosen by output visibility/layout
  every PE contributes local summary if it owns one
```

如果无法决定 source/sink expression，V1 应 fail fast，而不是隐式猜测。

Route planning 是另一个更靠后的 pass。它只消费 residency/materialization step
和实例化后的 per-PE participation，不改变 action 本身：

```text
SPMDResidencyStep / SPMDMaterializeStep + instantiated participation
  -> PhysicalCollectiveRoute
  -> COPY/COPYT/DMA command protocol
```

这保持了两个性质：

```text
compute action and collective action are schedulable in one plane.
physical route remains pluggable and replaceable.
```

## Relation To Current IR

Current structure:

```text
TilePhase
  local_ops
  collective_refs[]

CollectiveBundle
  kind
  participants
  source_tile_identity
  physical_route
```

Problem:

```text
collective_refs make collective look like metadata beside compute.
```

Proposed direction:

```text
TilePhase / TileScope
  actions[]

actions:
  MaterializeTileAction(visibility=row, route=unresolved, output=a0)
  MaterializeTileAction(visibility=column, route=unresolved, output=b0)
  ComputeTileAction(kind=hmmal_k_update, inputs=a0,b0, output=m0_0)
  ViewAction(kind=tile_view, inputs=m0_*, output=c0)
  ComputeTileAction(kind=relu, input=c0, output=y0)
```

`CollectiveBundle` should remain as global registry/source of truth for the
protocol instance, but each PE should also hold explicit `CollectiveTileAction`
records in its own program.

Layer 4 / K-step dumps should separate three identities:

```text
tile_identity:
  A_tile=tile:A:A:0:0

visibility_obligation:
  A_visibility=vis:task0:k0:A:row0:m0

route_or_registry_bundle:
  A_route_bundle=bundle:matmul_0:lg0:task0:k0:row0:A:m0:gm0
```

The first is the logical tile value. The second is the SPMD visibility
obligation. The third is a registry/route artifact. Combining them into
`row_bundle=...` makes row broadcast look like semantic IR, which conflicts
with the visibility/residency model.

## First Layer Integration With Logical DTensor

The immediate implementation target is the first layer only:

```text
user DTensor program
  -> logical DTensor graph
  -> chip-level generalized collective intents
```

Stop there for now. Do not immediately lower these actions to TensorCore/PE
roles, tile actions, runtime subtasks, or physical routes.

At this layer, each logical DTensor op should do one of three things:

```text
1. Produce a local logical compute action.
2. Produce a chip-level generalized collective intent.
3. Fail fast if the required layout movement is not explicit or unsupported.
```

Inputs and outputs become explicit layout materialization:

```text
env.input("A", placements=[Shard(0), Replicate()])
  -> CollectiveLoad(A, layout=[Shard(0), Replicate()])

env.output("Y", y)
  -> CollectiveStore(Y, layout=y.placements)
```

Local ops remain ordinary logical compute if their input layouts are already
compatible:

```text
relu(x)
  -> local_compute(relu)
```

Layout-changing ops must be explicit:

```text
x.redistribute(...)
  -> Reshard / Redistribute collective intent
```

The compiler must not silently insert `redistribute`:

```text
matmul(A, B) with incompatible layouts
  -> fail fast
```

For GEMM V1, matmul may emit the logical requirements that later become SUMMA
row/column collectives:

```text
A visible along mesh rows
B visible along mesh columns
C produced in [Shard(0), Shard(1)] layout
```

But this first layer should express those as visibility requirements attached
to the chip-level program, not as separate `RowBroadcast` / `ColumnBroadcast`
actions:

```text
CollectiveLoad(A)
  visibility_requirements += [
    {tensor=A, visibility_contract=mesh_rows, consumer_scope=matmul#0}
  ]

CollectiveLoad(B)
  visibility_requirements += [
    {tensor=B, visibility_contract=mesh_columns, consumer_scope=matmul#0}
  ]

Matmul(A, B)
  input_visibility_requirements = [
    {tensor=A, visibility_contract=mesh_rows, consumer_scope=matmul#0},
    {tensor=B, visibility_contract=mesh_columns, consumer_scope=matmul#0},
  ]
```

The next lowering layer may choose SUMMA row/column broadcast to satisfy these
requirements, but it is still free to choose a different load/propagation
protocol. The first layer therefore records what the chip needs, not how the
4x4 mesh will physically spread it.

For `log10 -> max -> maximum`, the first layer should express:

```text
CollectiveLoad(input tensor)
local_compute(log10)
Reduce(max) or AllReduce(max), depending on required max visibility
local_compute(maximum)
CollectiveStore(output tensor)
```

Again, no tile size or physical route is decided at this layer.

The next layer, not this one, may lower chip-level intents to:

```text
TensorCore-level logical collective actions
SPMD participation / residency expressions
per-PE visible values
```

## Open Questions

1. Should input load from DRAM/SPM to the first source PE be a separate
   `LoadTileAction`, or folded into `CollectiveTileAction(kind=ingress_*)`?
   Current answer: model the chip-level semantic action as `CollectiveLoad`,
   lower it first to TensorCore-level logical collective actions, then lower
   those to many tile-level collective/load actions after tiling decisions.
2. How much residency / participation planning should happen before task/subtask packing?
3. Should physical route be chosen before resource scheduling, or after tile
   actions have been packed into task/subtask regions? Current leaning: route
   is tile action indifferent and should be chosen after logical/tile action
   planning, unless resource constraints force earlier feedback.
4. For reductions, should scalar summary values and tile values share the same
   `CollectiveTileAction` representation?
5. How should debug trace name collective outputs so they read like normal
   local values (`a0`, `b0`, `max0`) instead of bundle ids?
6. What is the minimal V1 set of chip-level generalized collectives needed for
   GEMM and `log10 -> max -> maximum`?

## Next Implementation Direction

1. Keep current `CollectiveBundle` plan records as registry/debug artifacts.
2. Add a Mesh-SPMD tile residency program before per-PE instantiation:

   ```text
   SPMDResidencyStep
   SPMDMaterializeStep
   SPMDComputeStep
   source_coord_expr
   consumer_group_expr
   visibility_contract
   lifetime_expr
   route_status=unresolved
   ```

3. Schedule the residency program as Micro-Step BSP for V1:

   ```text
   materialize frontier
   visibility barrier
   compute frontier
   lifetime/update barrier
   ```

4. Instantiate the SPMD residency/materialization program into explicit
   per-phase/per-tile `CollectiveTileAction` records that reference registry
   bundles only after tile demand, source expressions, and lifetime windows are
   known.
5. Change human-readable trace so Layer 3/4 program view includes:

   ```text
   collective_in
   values
   view
   ops
   collective_out/output
   ```

6. Keep route-specific terms out of the main narrative layers:

   ```text
   Layer 3:
     materialize visibility=row route=unresolved

   Layer 4:
     tile_identity
     visibility_obligation
     route_or_registry_bundle
   ```

   `row_broadcast` / `column_broadcast` may still appear in registry or route
   views as selected realizations.

7. Add the missing SPMD materialization layer, either as a new layer between
   TileScope and K-step instances or as a Layer 4A/4B split:

   ```text
   Layer 4A: SPMD materialization steps
   Layer 4B: K HMMAL instances
   ```

8. Improve chip action layout display. Compute actions such as `Matmul` and
   `Relu` should show output placements (`Shard(0),Shard(1)`) instead of
   `placements=-` when the output tensor layout is known.

9. Keep Layer 5 as registry view:

   ```text
   collective id -> participants -> roles -> physical route
   ```

10. For GEMM, lower current row/column bundle refs into Mesh-SPMD input
   materialization steps before HMMAL member values. In V1, use fixed source
   rotation expressions; later replace them with a cost model.
