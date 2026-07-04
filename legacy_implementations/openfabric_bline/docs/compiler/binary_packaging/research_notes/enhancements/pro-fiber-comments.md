确实更成熟了，而且成熟的地方不是“多加了几个概念”，而是你们把核心难点命名出来了：**StreamPlan 负责拓扑和 whole-value visibility；StreamTilePlan 负责 topology-preserving slicing、tile access map、fragment reuse、fiber micro-distribution；FiberSchedule 再给 tile 层恢复一种确定性的 micro-SPMD 结构。** 这比上一版更像一个能落地的编译器中间层，而不是旧 `ProcessorTileProgram` 的轻量复刻。

我的评审结论更新为：

```text
Decision: Approve architecture direction.
Condition: before Phase 2/3, freeze the formal invariants for value/version,
dependency kinds, schedule authority, fragment fanout, and block projection lifecycle.
```

也就是说，我会把它从“方向可接受，但别急着实现”提升到“可以开始 Phase 1 skeleton + validator + demo lowering”，但还不建议直接进入真实 GEMM route/compute lowering。现在设计的骨架已经站起来了，接下来要给关节装轴承。

---

## 最大进步：你们找到了真正的 tile 层边界

上一版最大的问题之一是：`StreamTilePlan` 看起来像“把 stream actions 切成 tile actions”，但这句话对 elementwise 对，对 GEMM 不够对。

新版补上的 topology-preserving slicing / tile access maps / fibers 解决了这个盲点。文档现在明确说：stream-to-tile 不应该重新发现 inter-stream topology；StreamPlan 已经决定哪个 stream 给哪个 stream 发送、哪个 downstream action 依赖哪个 upstream action。tile lowering 的任务是保留这个拓扑形状，把 whole-stream values 细化为 tile fragments。

这个边界非常关键：

```text
StreamPlan:
  inter-stream topology
  whole-value visibility
  route / collective / materialization as stream actions

StreamTilePlan:
  tile-visible fragments
  operator-specific tile access maps
  local fragment reuse / fanout
  fibers and carried state

FiberSchedule:
  deterministic micro-SPMD generator for tile actions
```

这比“flat tile actions + depends_on”更完整。因为 flat actions 是 IR 表达形式，不是 lowering 算法本身。新版补上了生成这些 actions 的结构性来源。

---

## 我认可的新增设计

### 1. `StreamTilePlan` 是 topology-preserving slicer，不是 topology planner

这是新版里最重要的一句设计判断。你们把“route topology 已经被 StreamPlan 解决”和“tile micro-distribution 仍然是 operator-specific”分开了。这个切分很干净。

对编译器来说，这能避免两个灾难：

```text
1. tile lowering 重新规划 route，和 StreamPlan 打架；
2. matmul op spec 变成隐藏的小编译器，自己造 route、edge、visibility。
```

新版 boundary note 里也强调，`MatmulOpSpec` 可以描述 operand roles 和 local tile access pattern，但不应该构造 inter-stream route actions 或 dependency edges。route path、endpoint selection、cross-stream visibility 是系统层责任。

这个边界我强烈支持。

---

### 2. Operator-provided tile access maps 是必须的

新版明确指出 naive slicing 对 GEMM 失败：

```text
Elementwise:
  Y(i) <- X(i)

GEMM:
  C(m,n) <- A(m,k), B(k,n) for each k
```

这正好补上了上一版的核心漏洞。GEMM 的 tile lowering 不是 zip，不是“输出 tile 坐标对应输入 tile 坐标”。它是一个 access relation。文档现在提出：

```text
ElementwiseTileAccess:
  output_tile(i) <- input_tile(i)

MatmulTileAccess:
  output_tile(m,n) <- A_tile(m,k), B_tile(k,n) for k in K-blocks

StoreTileAccess:
  storage_tile(i) <- visible_value_tile(i)
```

这是非常正确的抽象。

我建议把它从 addendum 升级到 core RFC，因为这不是附加解释，而是 `StreamTilePlan` 能否正确 lower GEMM 的核心机制。

---

### 3. Fiber vocabulary 把 fragment reuse 讲清楚了

新版的 `GemmFiber(m_tile, n_tile, k_block)` 是个好概念。它直接表达了：

```text
fiber(m,n,k)
  consumes A(m,k)
  consumes B(k,n)
  contributes C(m,n)
```

然后 fragment reuse 自然出现：

```text
A(m,k) feeds C(m,n0,k), C(m,n1,k), ...
B(k,n) feeds C(m0,n,k), C(m1,n,k), ...
```

这比单纯说“compute_update depends_on A/B tile”更强，因为它告诉 lowerer：**input fragment 是可共享入口，不是每个 output fiber 私有拥有的读。** 文档里已经把这点称为 local fragment fanout / collective entrance，我觉得这个词非常有价值。

这会直接影响实现质量。如果没有 fiber/fanout 概念，开发者很容易写出：

```text
for each C(m,n):
  for each k:
    read A(m,k)
    read B(k,n)
    compute
```

然后同一个 A/B fragment 被重复 materialize，性能和 route 形状都会塌成小饼干。

---

### 4. Deterministic FiberSchedule 是正确的 loop metadata 来源

新版提出：

```text
FiberSchedule
  -> fragment materialization actions
  -> per-stream fiber compute actions
  -> carried-state / output actions
```

这比“先展开大图，再从 action graph 恢复 loop region”更稳。尤其是 GEMM 的 K loop，`repeat_axis=k`、`repeat_count`、loop body membership、step fragment set 都可以从 schedule generator 直接得到，不必让后端从一坨 expanded actions 里考古。

这也呼应了旧 tile layer 的经验：K recurrence 不应该当作 vendor graph predecessor/successor edges，而应该表达成 loop-carried state 或 local repeat semantics。RFC 原文已经保留了这一原则。

这里我会给高分。你们不是把 loop metadata 当装饰品，而是开始让它从 schedule structure 里长出来。

---

## 现在仍然需要补硬规格的地方

新版已经更可靠，但有几处必须从“概念正确”推进到“不可误解”。

### P0. `FiberSchedule` 和 `StreamTilePlan` 的 authority 边界必须写死

现在文档同时说：

```text
StreamTilePlan flat tile actions are authoritative.
FiberSchedule is deterministic generator of tile actions.
```

这两个都可以成立，但需要明确生命周期。

我建议定义成：

```text
FiberSchedule:
  pre-lowering generator / provenance object
  not an execution IR unless explicitly preserved as StreamTileLoopTemplate

StreamTilePlan:
  post-lowering authoritative semantic IR
  flat actions + values + dependencies are truth

Derived reports:
  loop report, route group, block view, packing projection
```

或者反过来：

```text
FiberSchedule is authoritative symbolic IR.
StreamTilePlan is expanded debug/materialized view.
```

但二者不能同时都当 authority。否则后面会出现：

```text
FiberSchedule says k0,k1,k2
StreamTilePlan actions got rewritten to k0,k2,k1
谁赢？
```

我的建议是 MVP 采用第一种：**FiberSchedule 是 generator/provenance，StreamTilePlan 是 authoritative materialized IR。** 如果未来要支持巨大 GEMM 的 symbolic loop template，再引入：

```text
StreamTileLoopTemplate
  body_actions
  repeat_axis
  repeat_count
  expansion_policy
```

并明确定义它什么时候比 expanded actions 更权威。

---

### P0. value/version 语义仍然需要补

新版增强了 fragment / fiber 叙事，但核心 IR 里的 `StreamTileValue` 还是：

```text
id
stream_id
logical_value_id
tile_coord
kind
producer_action_id
shape
global_offset
attrs
```

这还不够。`tile_visible[(stream_id, logical_value_id, tile_coord)]` 作为 current visible table 没问题，但它必须和 immutable provenance 分开。否则 ReLU、store、in-place-like lowering、fusion、overwrite 都会产生歧义。

建议改成：

```text
StreamTileValue
  id
  stream_id
  semantic_value_id        # e.g. A_dtensor, C_dtensor, Y_dtensor
  version_id               # producer-specific version
  tile_coord
  fragment_id?
  kind
  producer_action_id
  shape
  global_offset
  storage_class?
  attrs
```

并明确：

```text
tile_visible:
  current binding table

action.inputs / action.outputs:
  immutable TileValueRef provenance
```

也就是说：

```text
tile_visible[(S, C, m,n)] = c_final_v3
relu_tile.inputs = [c_final_v3]
relu_tile.outputs = [y_v1]
tile_visible[(S, Y, m,n)] = y_v1
store_tile.inputs = [y_v1]
```

不要让 `depends_on` 或 store 通过 `logical_value_id + tile_coord` 在事后查 current map。那会让时间变成汤。

---

### P0. `depends_on` 不能继续混 value 和 action

文档中的示例仍然有一点混用：

```text
compute_update_tile.depends_on = [
  tile_visible[(stream,A,m_tile,k)],
  tile_visible[(stream,B,k,n_tile)],
  accumulator_prepare if k == 0 else compute_update(k-1),
]
```

这里前两个是 value refs，后一个是 action ref。建议正式拆开：

```text
StreamTileAction
  inputs: list[TileValueRef]
  outputs: list[TileValueRef]
  depends_on: list[TileActionDependency]
```

其中：

```text
TileActionDependency
  action_id
  kind: data | order | visibility | loop_carried | resource | barrier
  via_value_id?
```

然后 `dependency_edges()` 可以从两处派生：

```text
1. action.inputs[*].producer_action_id => data edges
2. action.depends_on[*] => explicit non-data or annotated edges
```

这样你们仍然保留“dependency table 是 derived view”的原则，同时不会让 IR 使用者猜 `depends_on` 里到底塞的是 action 还是 value。原 RFC 明确说 dependency table 不应该是 authoritative，这一点是对的；现在需要把 field 语义拧紧。

---

### P0. accumulator 应该正式成为 carried value/state

新版有 `carried_refs`，但我建议把 accumulator 的例子改成正式 value flow：

```text
acc0 = accumulator_prepare_tile(m,n)

acc1 = compute_update_tile(
  fiber=(m,n,k0),
  inputs=[A(m,k0), B(k0,n), acc0],
  outputs=[acc1],
  carried_refs=[acc0 -> acc1],
)

acc2 = compute_update_tile(
  fiber=(m,n,k1),
  inputs=[A(m,k1), B(k1,n), acc1],
  outputs=[acc2],
  carried_refs=[acc1 -> acc2],
)

c_final = accumulator_finalize_tile(
  inputs=[accK],
  outputs=[C(m,n)],
)
```

这能同时满足三件事：

```text
1. expanded debug DAG 可读；
2. loop-carried recurrence 不会被误认为普通 vendor graph edge；
3. vendor repeat lowering 可以从 carried_refs/fiber schedule 派生。
```

这里不要只把 `carried_refs` 放进 attrs。它至少应该是 schema-checked structured field，否则后面 packer 又要在 `attrs["magic_loop_thing"]` 里捞鱼。

---

### P1. Tile access map 需要 schema，不要只写成解释性文字

我建议把 access map 设计成正式接口，哪怕 MVP 很小：

```text
TileAccessMap
  op
  output_fragment_space
  input_fragment_spaces
  fibers()
  inputs_for_fiber(fiber_id)
  outputs_for_fiber(fiber_id)
  carried_state_for_fiber(fiber_id)?
  step_key(fiber_id)?
```

GEMM 可以是：

```text
MatmulTileAccessMap
  fiber_id = (m_tile, n_tile, k_block)

  inputs:
    A_fragment(m_tile, k_block)
    B_fragment(k_block, n_tile)
    acc_fragment(m_tile, n_tile, k_block - 1)

  outputs:
    acc_fragment(m_tile, n_tile, k_block)

  final_output:
    C_fragment(m_tile, n_tile)
```

Elementwise 可以是：

```text
ElementwiseTileAccessMap
  fiber_id = output_tile_coord
  inputs = [input_fragment(output_tile_coord)]
  outputs = [output_fragment(output_tile_coord)]
```

Store 可以是：

```text
StoreTileAccessMap
  input = visible_fragment(tile_coord)
  output = storage_fragment(tile_coord)
```

这会让 `StreamTilePlan` 从“理念清楚”变成“实现不会跑偏”。

---

### P1. `tile_coord` 需要 named axes / fragment space

新版大量使用：

```text
A(m,k)
B(k,n)
C(m,n)
fiber(m,n,k)
```

这说明 tuple 已经不够了。建议别用裸 tuple 当核心语义：

```text
TileCoord
  fragment_space_id
  axes: dict[str, int]
```

例如：

```text
A_fragment:
  fragment_space = A_local_tiles
  axes = {m: 0, k: 2}

B_fragment:
  fragment_space = B_local_tiles
  axes = {k: 2, n: 1}

C_fragment:
  fragment_space = C_local_tiles
  axes = {m: 0, n: 1}
```

否则 `(0, 2)` 在 A 里是 `(m,k)`，在 B 里可能是 `(k,n)`，在 C 里是 `(m,n)`。靠 position 猜 axis，早晚会在 layout transform、transpose、padding、partial tiles 那里偷袭你。

---

### P1. Fragment fanout 要有显式策略

新版已经识别了 fragment reuse，但还需要定义 fanout 是否只是多条 data edges，还是一个显式概念。

MVP 可以简单：

```text
one StreamTileValue may be consumed by many actions
```

validator 检查：

```text
consumer input refs point to the same value_id
no duplicate materialization unless allowed
```

但后面 route/local broadcast 可能需要显式 fanout action：

```text
fragment_materialize_A(m,k)
  outputs = [A_fragment(m,k)]

compute_update(m,n0,k).inputs includes A_fragment(m,k)
compute_update(m,n1,k).inputs includes A_fragment(m,k)
```

或者：

```text
fragment_fanout_A(m,k)
  inputs = [A_fragment(m,k)]
  outputs = [A_fragment_view(m,k,n0), A_fragment_view(m,k,n1), ...]
```

我建议不要在 core IR 里急着引入 `FragmentFanout` action，但要在 RFC 里声明：

```text
Default fanout model:
  multiple consumers may reference the same StreamTileValue.

Explicit fanout action:
  introduced only when hardware/resource lowering requires distinct local copies,
  banked views, multicast tokens, or lifetime splitting.
```

这样可以保持 flat IR 简洁，同时为后端真实资源留门。

---

### P1. Route recv 的 logical / physical 双语义仍要正式化

新版保留了：

```text
execution_stream
endpoint_stream
```

这是正确方向。RFC 已经说明 logical level 上 recv 是 receiver-side visibility event，但 DFU tile execution 可能是 sender-side COPY/COPYT。

我建议固定成：

```text
StreamTileAction
  stream_id             # logical owner / where visibility belongs
  execution_stream_id?  # physical stream/engine that emits instruction
  endpoint_stream_id?   # destination visibility stream, for route-like ops
```

对 route recv：

```text
route_recv_tile
  stream_id = receiver
  execution_stream_id = sender or route engine
  endpoint_stream_id = receiver
  inputs = [source fragment or route token]
  outputs = [receiver-visible fragment]
```

这能避免 downstream 问出那个经典鬼问题：

```text
这个 tile value 到底是 sender 的 COPY 生产的，
还是 receiver 的 recv visibility token 生产的？
```

答案应是：

```text
logical producer = route_recv_tile
physical executor = sender-side copy action / execution_stream
```

两者都保留，不要互相覆盖。

---

### P1. Deterministic schedule group 需要定义成员、坐标映射和 mask

你们提出一组 streams 共享同一个 deterministic fiber schedule shape，这很有价值。

但正式实现前需要定义：

```text
FiberScheduleGroup
  id
  streams
  schedule_axes
  per_stream_coord_map
  active_mask / empty_fiber_policy
  step_order
```

比如：

```text
stream S00 -> owns C(m0,n0)
stream S01 -> owns C(m0,n1)
stream S10 -> owns C(m1,n0)
```

这些 stream 共享：

```text
for k in K:
  materialize A(*,k), B(k,*)
  compute local fiber
```

但每个 stream 的 local fiber coordinate 不同。这个映射必须是一等 metadata，否则 debug report 和 route matching 都会靠字符串约定。

还要处理：

```text
partial tiles
non-square mesh
ragged shard
some streams inactive for a step
```

建议加：

```text
FiberInstance
  schedule_id
  step_id
  stream_id
  local_coords
  active: bool
```

inactive fiber 不一定要 materialize action，但 schedule report 应该能解释它为什么不存在。

---

### P1. `StreamTilePlan` 的 stream action order 语义仍要明确

StreamPlan / StreamTilePlan 都是：

```text
streams[]
  actions[]
    depends_on[]
```

但 list order 是什么？

建议直接写：

```text
Action list order is stable presentation/generation order.
Execution legality is determined by explicit dependencies plus resource constraints.
```

如果硬件后端需要 per-stream PC order，可以由 block/micro-op pass 生成：

```text
program_order_edges
```

但不要让 list order 暗中成为第二套 dependency system。否则 `depends_on` 的“单一真相”会被悄悄削弱。

如果你们希望 FiberSchedule 的 step order 是语义顺序，也可以，但要明确：

```text
FiberSchedule step order produces explicit order / loop_carried dependencies
in StreamTilePlan.
```

也就是 schedule order 不应只藏在 generator 里，materialized plan 要能看见它。

---

### P1. Block projection 的冻结边界还需要写成生命周期规则

RFC 已经说 block/micro-op projection 是 later pass，但 once created 应该成为 micro-op/vendor-template lowering 的 authority。

建议加：

```text
StreamTilePlan
  authoritative before block partition

TileBlockPlan
  authoritative after block partition for executable grouping,
  block roles,
  micro-op lowering,
  vendor template selection

Any mutation to StreamTilePlan invalidates TileBlockPlan.
```

并让 `TileBlockPlan` 带：

```text
source_plan_id
source_plan_fingerprint
action_to_block
blocks
block_roles
loop_region_refs
route_group_refs
```

否则 derived block view 很容易在后端手里变成半权威、半缓存、半幽灵。

---

## 建议把 RFC 的结构调整一下

现在很多真正重要的内容还在 Addendum 里。我建议升格。

### Core RFC 应包含这些小节

```text
1. Authority model
   - StreamTilePlan vs FiberSchedule vs derived views

2. Value and fragment model
   - StreamTileValue versioning
   - tile_visible current map
   - immutable action inputs/outputs

3. Tile access maps
   - elementwise
   - matmul
   - store

4. Fiber model
   - TileFragment
   - TileFiber
   - FragmentProducer
   - default fanout semantics

5. FiberSchedule
   - schedule group
   - step order
   - stream-local coordinate mapping
   - generated loop metadata

6. Dependency model
   - inputs/outputs vs depends_on
   - dependency kinds

7. Block projection lifecycle
```

### Addendum 可以只保留直觉解释

比如 river model 很好，很适合作为设计 intuition：

```text
StreamPlan = topology / river direction
StreamTilePlan = longitudinal slicing
LoopRegion = cross-section view
```

但 tile access map、fiber、deterministic schedule 已经不是补充解释了。它们是方案的发动机，应该进入主设计舱。

---

## 我会要求新增的 validator gates

### Gate 1: value provenance

```text
for every action input:
  referenced value exists
  referenced value has producer_action_id
  producer action exists
  input value version is immutable
```

### Gate 2: visibility map coherence

```text
for every tile_visible[(stream, semantic_value, coord)] = value:
  value.stream_id == stream
  value.semantic_value_id == semantic_value
  value.tile_coord == coord
```

### Gate 3: dependency derivation

```text
derived data edge exists from each input producer to consumer
explicit depends_on edge kind is valid
no dangling action refs
no illegal cycles outside loop-carried regions
```

### Gate 4: tile access map coverage

For GEMM:

```text
every C(m,n) has exactly K compute_update fibers
each fiber consumes A(m,k) and B(k,n)
all required A/B fragments are materialized before use
final C visible only after last carried update/finalize
```

### Gate 5: fragment reuse

```text
same A(m,k) value_id may feed multiple n fibers
same B(k,n) value_id may feed multiple m fibers
duplicate materialization is rejected unless marked allowed
```

### Gate 6: schedule consistency

```text
every compute fiber references a schedule_id and step_id
step order matches loop_axis order
loop annotations derive from schedule
carried_refs connect consecutive steps for same output accumulator
```

### Gate 7: route tile matching

```text
route_recv_tile matches exactly one route_push/forward source unless fanin policy says otherwise
tile_coord / fragment_space match
logical source value matches
receiver-visible output is produced by recv visibility action
```

### Gate 8: block projection invalidation

```text
TileBlockPlan.source_plan_fingerprint == StreamTilePlan.fingerprint
each tile action belongs to zero or one executable block depending on op kind
block roles are schema-checked
```

---

## 推荐的实现顺序

我会把 Phase 1 拆细一点。

### Phase 1A: IR skeleton

```text
TileCoord / FragmentCoord
TileValueRef
StreamTileValue
StreamTileAction
StreamTilePlan
DependencyKind
TileActionDependency
```

先不要做 GEMM。

### Phase 1B: validator + derived dependency view

```text
validate_stream_tile_plan()
dependency_edges()
producer_consumers()
visible_fragments()
```

没有 validator 的 IR 会很快变成果冻城堡。

### Phase 1C: elementwise chain

```text
sram_read X
relu X -> Y
store Y
```

这个阶段专门打穿：

```text
value versioning
tile_visible current map
inputs/outputs
store depends on final value
```

### Phase 2: TileAccessMap interface

先实现：

```text
ElementwiseTileAccessMap
StoreTileAccessMap
FakeMatmulTileAccessMap
```

不要急着接 route。

### Phase 3: route materialization

实现：

```text
route_push_tile
route_recv_tile
execution_stream / endpoint_stream
matching validator
```

### Phase 4: GEMM fiber schedule

实现：

```text
MatmulTileAccessMap
GemmFiber
FiberSchedule
accumulator carried_refs
compute_update actions
loop report derived from schedule
```

### Phase 5: block projection

先做 debug block view，不立刻 vendor ABI。等 action/value/fiber 语义稳定后再接旧后端。

---

## 最终判断

这版比上一版明显成熟。上一版主要证明：

```text
我们应该有 flat StreamTilePlan，
不要克隆旧 ProcessorTileProgram。
```

新版进一步证明：

```text
为什么 tile lowering 不是 blind slicing；
为什么 GEMM 需要 tile access maps；
为什么 fragment reuse/fanout 是核心问题；
为什么 FiberSchedule 可以作为 deterministic micro-SPMD generator；
为什么 StreamPlan 和 StreamTilePlan 的边界不会互相吞掉。
```

我会给现在这版：

```text
Architecture: strong approve
Implementation readiness: Phase 1 ready
Production readiness: not yet
```

进入代码前需要冻结的最小 contract 是：

```text
1. StreamTilePlan 是 materialized authority，FiberSchedule 是 generator/provenance；
2. tile_visible 是 current map，action inputs/outputs 是 immutable provenance；
3. depends_on 只存 action dependencies，value flow 走 inputs/outputs；
4. TileAccessMap / Fiber / Fragment schema 正式化；
5. accumulator 用 carried value/state 表达；
6. route recv 保留 logical producer 与 physical execution 双语义；
7. block projection 有明确 authority transfer 和 invalidation 规则。
```

总体上，这是很好的演进。之前像是在铺一条干净的新路；现在你们已经把地形图画出来了：哪里是河道，哪里是纤维束，哪里有共享入口，哪里需要桥。下一步别急着修高速，先把路标和交通规则钉死。
