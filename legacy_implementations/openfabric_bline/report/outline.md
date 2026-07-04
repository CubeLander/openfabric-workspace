# DFU 算子编译器汇报大纲

## 0. 汇报主线

这次汇报的中心不是“我们实现了一个 GEMM demo”，而是：

```text
甲方需要持续把各种模型部署到 DFU 芯片上。
现有算子开发 workflow 依赖半人工维护底层 C/template/CSV/tensor-core 指令，
无法支撑多模型、多算子、融合、可重定位 kernel 的长期需求。

我们的解法是建设一个 DFU 算子编译器：
把 DFU 看成一个 mini distributed tensor machine，
借用 torch.distributed / DTensor 的 mesh、shard、replicate、partial、collective 思想，
再逐层 lowering 到 DFU 的 PE、tile、task、subtask、instance 和指令 package。
```

一句话版本：

```text
我们不是复刻甲方闭源 runtime，而是把甲方手写算子的流程编译器化。
runtime 是黑盒承载端，compiler 是我们能够掌控、积累和扩展的部分。
```

## 1. 问题是什么

甲方的真实目标不是交付单个算子，而是把各种各样的模型持续部署到自己的芯片上。

这个目标会不断带来新的算子开发需求：

```text
1. 新模型带来新算子和新 shape。
2. 大模型推理带来 matmul、RMSNorm、RoPE、Attention、Softmax、KV cache update 等关键算子。
3. 前后处理链路带来非 GEMM 融合算子，例如 log10 + max reduce + maximum。
4. 性能优化要求算子融合，减少中间写回和重复搬运。
5. 部署工程要求 kernel 可重定位，不能把地址和数据位置写死在一份手工实现里。
6. 多 PE 并行要求系统处理 tensor 切分、跨 PE broadcast/reduce、局部内存复用和调度边界。
```

所以核心问题不是：

```text
某一个算子怎么手写出来？
```

而是：

```text
如何把算子开发从 case-by-case 的半人工底层工程，
变成可复用、可验证、可扩展的编译流程？
```

## 2. 现状是什么

当前甲方算子开发 workflow 大致是：

```text
开发者理解芯片和工具链细节
  -> 手工维护 case contract / PE map / shape / memory layout
  -> 在 template C/C++ 里生成每个 PE 的 CSV
  -> 手工处理 task/subtask/instance 结构
  -> 手工处理 operand tag、base address、COPY/COPYT、tile 切分
  -> common_oper 再把 CSV 映射和打包成 runtime 消费的 binary
  -> 闭源 runtime 执行
```

这个 workflow 的问题：

```text
1. 算子语义和硬件细节混在一起。
2. 每个新算子都需要重新维护大量底层表格和模板。
3. 融合逻辑难以系统化复用。
4. 可重定位 kernel 依赖手工维护 base address / instance table，容易出错。
5. 很难从一个模型迁移到另一个模型，工程积累弱。
6. 调试成本高：出错时不清楚是全局算子语义错、PE 切分错、tile schedule 错，还是最终指令/地址错。
```

因此，现状无法满足“持续自动化部署多种模型”的需求。

## 3. 我们的核心解法

我们的核心思想：

```text
把 DFU 抽象成一个 mini distributed 单机多卡系统。
把 PE / Tensor Core 看成 mesh 上的 device/rank。
把 DFU 算子编译看成 distributed tensor program 到设备任务包的 lowering。
```

为什么用 torch.distributed / DTensor 做设计模型：

```text
torch.distributed / DTensor 已经提供了一套成熟的思路：
  在 device mesh 上表达 tensor 如何 shard、replicate、partial；
  区分 local compute 和 collective communication；
  平衡计算并行、通信代价和布局转换。

DFU 算子开发面对的是相似问题：
  tensor 怎么切到 4x4 PE mesh；
  每个 PE 负责哪块 shard/tile；
  哪些操作是 PE-local；
  哪些操作需要 row/column broadcast、all_reduce、reduce_scatter；
  什么时候可以 fusion；
  什么时候必须切开形成 collective/reduce boundary。
```

注意：这里不是要在 DFU 上运行 PyTorch runtime。

更准确的说法是：

```text
我们借用 torch.distributed / DTensor 的语义模型，
为 DFU 构建自己的静态算子编译器。
```

## 4. 架构总览

建议用一张分层图讲：

```text
Layer 1: Chip-level logical operator
  全芯片视角的算子语义。
  例：Y = relu(A @ B)

Layer 2: PE-level logical actions
  把全局算子展开到每个 PE 上。
  例：PE(i,j) 负责 C_ij shard 的 local_matmul / local_relu。

Layer 3: PE tile scopes / tile actions
  把每个 PE 的 local action 拆成 tile-level scope。
  tile scope 内维护 compute、collective、view、materialize 等 action。
  tile 内尽量 fusion；遇到跨 PE broadcast/reduce/reshard 才切开。

Layer 4: DFU-specific runtime package plan
  继续 lowering 到 launch_group / task / subtask / instance /
  operand slot / base_addr / instruction template / CSV package。
```

这四层分别解决不同问题：

```text
Layer 1 解决模型/算子语义。
Layer 2 解决 distributed tensor placement 到 PE local work 的映射。
Layer 3 解决 tile 粒度的数据复用、fusion、collective boundary，
同时保留 tensor 指令产生 fragment/tmp value 再组成 tile view 的事实。
Layer 4 解决 DFU 闭源 runtime/toolchain 能消费的执行材料。
```

这个分层的关键价值是：

```text
不让用户直接写 PE、CSV、COPYT、task/subtask、operand index。
用户写 operator program，compiler 负责逐层降低。
```

## 5. Layer 1: Chip-level Logical Operator

这一层回答：

```text
这个算子在全局 tensor 语义上是什么？
输入输出 ABI 是什么？
shape / dtype / layout 是什么？
tensor 在 4x4 mesh 上如何放置？
```

示例：

```python
env = OperatorEnv("gemm_relu")
mesh = env.mesh("pe", (4, 4), dim_names=("row", "col"))

A = env.input("A", shape=(M, K), dtype="fp16",
              placements=[Shard(0), Replicate()], mesh=mesh)
B = env.input("B", shape=(K, N), dtype="fp16",
              placements=[Replicate(), Shard(1)], mesh=mesh)

C = A @ B
Y = relu(C)
env.output("Y", Y)
```

这里的重点：

```text
1. 用户描述的是 operator ABI，不是底层 runtime package。
2. placements 表达 tensor 的分布式布局。
3. Shard / Replicate / Partial 是从 DTensor 借来的语义。
4. compiler 不自动偷偷 redistribute；layout movement 必须显式出现在源程序和 plan 中。
```

为什么不能自动 redistribute：

```text
这是低层 deployable operator compiler，不是 PyTorch eager runtime。
每次数据移动都对应 DFU 上真实的 COPY/COPYT、broadcast、reduce、base address 和调度成本。
如果 compiler 静默插入 layout movement，生成物会很难审阅和调试。
```

## 6. Layer 2: PE-level Logical Actions

这一层把全芯片 operator 展开到 16 个 PE 的局部工作。

以 GEMM 为例：

```text
A[M,K] placements = [Shard(0), Replicate()]
B[K,N] placements = [Replicate(), Shard(1)]
C[M,N] placements = [Shard(0), Shard(1)]

PE(i,j) 负责：
  C_ij = A_i @ B_j
```

在当前 4x4 PE mesh 下：

```text
PE00 负责 top-left C shard
PE01 负责 row 0 / col 1 的 C shard
...
PE33 负责 bottom-right C shard
```

这一层输出的是 PE logical action，而不是指令：

```text
PE00:
  local_matmul(lv_A_PE00, lv_B_PE00) -> lv_C_PE00
  local_relu(lv_C_PE00) -> lv_Y_PE00

PE01:
  local_matmul(lv_A_PE01, lv_B_PE01) -> lv_C_PE01
  local_relu(lv_C_PE01) -> lv_Y_PE01
```

这一层的意义：

```text
1. 建立 source-level operator node 到每个 PE action 的可追踪关系。
2. 明确每个 PE 看到的 local shard shape 和 global offset。
3. 后续 tile lowering 可以基于 PE-local action 做局部计划。
```

## 7. Layer 3: PE Tile Scopes / Tile Actions

这一层是当前设计的核心。

PE-local action 仍然太粗，需要拆成 tile-level phase：

```text
TileScope / TilePhase 是最小可审阅计划单元。
它记录一个 PE 在一个 tile/wave 上做什么、依赖哪些 input tile、产生哪些 value/view、
需要哪些 collective action、对应哪个 launch_group/task/subtask/instance。
```

为什么必须保留 tile 层：

```text
1. DFU 的 task/subtask/instance 切分天然在 tile/K-block 级别表达。
2. GEMM 的 A/B 复用和 K streaming 是 tile-level 结构。
3. row/column broadcast 必须跨 PE 对齐，tile 是合适的原子单元。
4. padding、dummy tile、output mask 都是 tile 级属性。
5. fusion/reduce 需要 tile-level producer/consumer 边。
6. 如果直接吐指令，会丢失 C tile、K block、collective bundle 这些可审阅结构。
```

最近的实现和设计笔记里，Layer 3 进一步从“tile-shaped buffer”细化为：

```text
TileScope:
  一个 schedulable union container。
  它有 logical tile identity、owner PE、global range、member values、views 和 materialization state。

Value:
  硬件指令真实产生/消费的东西。
  例如 HMMAL tmp fragment、operand strip、local max summary。

TileView:
  对一组 tile-owned values 的结构化解释。
  例如多个 HMMAL tmp/member values 可以被解释成 C[0:64,0:64] 的 accumulator view。
```

这个调整来自一个硬件事实：

```text
HMMAL 不直接写普通 C operand。
HMMAL 写 tensor tmp state；
RXINT / TRCTT 负责 tmp state 与普通 operand 之间的 import/export。
```

所以 Layer 3 不能假装每条 compute 都立刻产生完整 materialized tile。更准确的模型是：

```text
TileScope C_tile:
  collective_in:
    A tile visible on this PE
    B tile visible on this PE

  values:
    m0 = HMMAL(A_k0, B_k0) -> owner C_tile
    m1 = HMMAL(A_k1, B_k1) -> owner C_tile
    m2 = HMMAL(A_k2, B_k2) -> owner C_tile
    m3 = HMMAL(A_k3, B_k3) -> owner C_tile

  view:
    C_view = tile_view(C_tile.members, layout=hmmal64_tmp_layout)

  ops:
    Y_view = relu(C_view)

  materialization:
    store or expose Y_view as output tile
```

这个模型保留两件事：

```text
1. tile 仍然是调度、审阅、task/subtask 切分和 collective 对齐的单位。
2. value/view 才是后续 tensor instruction lowering、tmp lifetime、fusion 和 materialization 的真实边界。
```

统一 action 模型：

```text
LocalPhase:
  对 PE-local tile/shard 做计算。
  例如 local matmul、elementwise、local reduce。

CollectivePhase:
  对 local phase 产生的 tile/scalar/shard 做跨 PE 通信或 reduce。
  例如 row_broadcast、column_broadcast、all_reduce、reduce_scatter。

PostCollectiveLocalPhase:
  collective 结果回来后，继续在 PE-local tile 上做 fusion。
```

更程序化地说，TileScope 内部应该是一串 action：

```text
TileAction =
  CollectiveTileAction
  ComputeTileAction
  ViewAction
  MaterializeTileAction
  BarrierAction
```

这样 collective 不再只是 compute 旁边的说明表，而是和 compute 一样处在 PE/tile
program 的时间线里。

`CollectiveBundle` 仍然有价值，但它更像 registry view：

```text
Program view:
  这个 PE 在这个 tile scope 里先做 collective_in，再 compute，再 view/materialize。

Registry view:
  某个 collective protocol instance 的全局事实：
  kind、participants、roles、logical source、physical_route。
```

tile fusion 原则：

```text
先在 PE 级别收集任务。
再在 tile 级别收集作用于同一个 tile 的任务。
对每个 tile，尽量一口气完成所有 PE-local producer/consumer。
只有遇到跨 tile / 跨 PE 的 reduce、broadcast、reshard 或 barrier 才切开。
```

GEMM baseline：

```text
local_gemm_summa phase:
  init C accumulator
  stream K blocks
  each K block consumes one A tile and one B tile
  update C accumulator
  apply fused post-op, e.g. relu
  store output tile
```

非 GEMM 融合算子也能表达：

```text
log_spec = clamp(mel_spec, min=1e-10).log10()
global_max = log_spec.max()
out = maximum(log_spec, global_max - 8.0)
out = (out + 4.0) / 4.0

phase 1:
  PE-local clamp + log10 + local max

phase 2:
  all_reduce(MAX) over 16 PE-local maxima

phase 3:
  PE-local maximum + affine scale + store
```

这说明 backend 不能写成 `GemmTile64`，而要写成更通用的 tile phase system。

## 8. Layer 4: DFU-specific Lowering

这一层把 tile plan 继续降低成甲方工具链/runtime 能消费的材料。

目标结构：

```text
TileScope / TileAction / CollectiveBundle
  -> launch_group
  -> task
  -> subtask
  -> instance
  -> exeBlock / LD-CAL-FLOW-ST stage
  -> operand tag / operand index
  -> base_addr_idx / instance base table
  -> instruction template / CSV
  -> runtime package
```

当前已确认的 runtime/dataflow 层级：

```text
task -> subtask -> exeBlock graph
exeBlock -> LD stage -> CAL stage -> FLOW stage -> ST stage
```

可以这样解释：

```text
subtask:
  runtime-visible dataflow lifecycle boundary。
  例如 load/init、K streaming compute、store、post-op fusion。

instance:
  对同一个 subtask graph 的硬件循环。
  同一份指令模板复用，不同 instance 使用不同 base address。

base address table:
  每个 instance 的地址环境。
  使 kernel template 可以重定位到不同 tile / K slice / data window。
```

GEMM 的直觉例子：

```text
subtask1:
  初始化 C accumulator。

subtask2:
  repeat 4 times，对应 K 维 4 个 slice。
  每个 instance 的 A/B base address 不同。

subtask3:
  store C tile。

subtask4:
  optional fused post-op。
```

这一层是 compiler 相比 DTensor 真正新增的硬件价值：

```text
DTensor 不关心 PE instruction memory、operand slots、task/subtask 限制。
DFU compiler 必须把 distributed tensor semantics 压进闭源 runtime 的调度模型里。
```

从最新设计看，Layer 4 的输入不只是 `TilePhase.local_ops + collective_refs`，
而更应该是：

```text
TileScope.actions[]
  CollectiveTileAction(kind=collective_in / row_broadcast / all_reduce / collective_store)
  ComputeTileAction(kind=HMMAL / SIMD / reduce / elementwise)
  ViewAction(kind=tile_view)
  MaterializeTileAction(kind=TRCTT / store / expose)
```

然后 Layer 4 再把这些 action 分配到：

```text
LD / CAL / FLOW / ST stage
task / subtask / instance
RXINT / HMMAL / TRCTT / COPYT / HSTT 等指令模板
```

## 9. 用熟悉模型理解 DFU 硬件

建议用一页表格讲：

| DFU 概念 | 熟悉模型里的类比 | compiler 中的作用 |
| --- | --- | --- |
| DFU chip | 单机多卡节点 | 一个固定规模的 distributed tensor machine |
| 4x4 PE mesh | 16-rank DeviceMesh | tensor sharding / collective 的拓扑 |
| PE / Tensor Core | rank / device | 执行 local shard/tile compute |
| PE operand RAM | rank-local memory / register file | 保存 local tile、temporary、accumulator |
| SPM | shared/global scratchpad | tile load/store 的主要数据源/目标 |
| COPY/COPYT | point-to-point communication primitive | lowering row/column broadcast、reshard |
| MICC/CBUF/DMA | runtime/data movement substrate | 承载 task graph、指令和数据搬运 |
| task/subtask | runtime-visible schedule boundary | 表达阶段、barrier、资源切分 |
| instance | hardware loop / stream cursor | 复用同一 subtask graph 处理不同 tile/base address |
| base_addr table | per-instance address environment | 支持可重定位 kernel |
| CSV/template | low-level instruction template | compiler 最终要生成的目标之一 |

当前硬件事实可以系统介绍：

```text
PE mesh:
  4 x 4 = 16 PE。
  PE id 按 row-major 映射到 PE00..PE33。

Per PE resources:
  instruction block slots : 32
  instruction slots       : 4352
  general register slots  : 8
  operand slots           : 1536

Operand memory:
  1536 logical operand registers。
  12 RAM banks，每 bank 128 项。
  SIMD128 下一个 logical operand 可理解为 4096-bit。

Runtime package:
  包含 task config、subtask config、exeBlock config、instance config、
  per-PE instruction stream。
```

讲法重点：

```text
这些硬件参数不是散乱细节，而是 compiler lowering 的约束。

例如：
  operand slots 限制 tile live set；
  instruction slots 限制每个 PE 的程序长度；
  subtask/instance 决定 tile stream 怎么切；
  base_addr table 决定 kernel 如何可重定位；
  COPY/COPYT 决定 collective 如何物理化。
```

## 10. 为什么这个设计能成立

### 10.1 它贴合 DFU 的硬件事实

DFU 的执行材料本来就是：

```text
PE mesh
tile/shard
operand RAM
tensor tmp state
COPY/COPYT
task/subtask/instance
base_addr
instruction template / CSV
```

我们的 IR 正是在这些层级上建立抽象，不是空中楼阁。

最近整理 tensor 指令集后，可以更明确地说明：

```text
RXINT:
  ordinary operand -> tensor tmp state

HMMAL:
  A/B operand -> tmp0..tmp7 selected by imm fields

TRCTT:
  tensor tmp state -> ordinary operand
```

这说明 tile backend 需要同时表达：

```text
1. tile scope:
   用于调度、审阅、collective 对齐和 task/subtask 切分。

2. member values / tmp values:
   用于表达 HMMAL 等 tensor 指令真实产生和累积的中间状态。

3. tile view:
   用于把 tmp/member values 解释成后续 relu/store/collective 能消费的 tile-shaped value。
```

因此，`TileScope + Value + TileView` 不是过度设计，而是对 tensor instruction
和 tile-level schedule 之间张力的直接回应。

### 10.2 它利用了成熟的分布式张量模型

模型算子虽然很多，但底层模式可以归纳：

```text
matmul / GEMM
elementwise
local reduction
cross-PE collective reduction
layout transform / broadcast / gather / scatter
post-op fusion
```

这些模式正好能被：

```text
Shard / Replicate / Partial
LocalPhase / CollectivePhase
TilePhase / CollectiveBundle
```

表达。

### 10.3 它能解释并替代现有手工 workflow

现有手工维护内容：

```text
conf.h / conf_PEmap.h
template/*.cpp
template/*.csv
task/subtask conf
instance base table
operand tag mapping
PE copy plan
```

在 compiler 中对应为：

```text
operator ABI
placement / mesh
tile phase plan
collective bundle
task/subtask/instance plan
base_addr environment
instruction template expansion
```

也就是说，它不是另起炉灶，而是在把已有人工知识结构化、自动化。

### 10.4 它对未来需求有扩展性

未来新模型进来时，不应该每个算子都重新手写底层模板。

更理想的工程方式是：

```text
新增 operator / fusion pattern
  -> 增加 frontend op schema
  -> 增加 placement rule
  -> 增加 tile lowering rule
  -> 复用已有 task/subtask/instance 和 instruction lowering 基础设施
```

这把算子开发从“个案工程”变成“可积累的编译器工程”。

## 11. 架构问题回应

这一节用于提前回应 review 中最可能被追问的四个问题：

```text
1. Attention 怎么表达？
2. Partial 怎么落地？
3. Redistribute 怎么设计？
4. Collective bundle 怎么验证？
```

汇报时不要把这些问题讲成“以后再说”。更好的说法是：

```text
这些问题正好说明为什么我们需要 DTensor-like frontend + tile backend 两层。
DTensor-like frontend 负责表达分布式 tensor 语义；
tile backend 负责把这些语义变成 DFU 上可检查、可 lowering 的 phase / collective / task plan。
```

### 11.1 Attention 怎么表达？

回答要点：

```text
Attention 不应该在第一版 IR 里被当成一个完全 opaque 的大算子。
它应该先表达成一组可组合的 distributed tensor ops 和 fusion pattern。
```

标准 attention 可以拆成：

```text
Q = X @ Wq
K = X @ Wk
V = X @ Wv

S = Q @ K^T / sqrt(d)
P = softmax(S)
O = P @ V
Y = O @ Wo
```

在我们的 compiler 里，它对应几类 primitive：

```text
1. projection GEMM:
   X @ Wq, X @ Wk, X @ Wv, O @ Wo

2. score GEMM:
   Q @ K^T

3. row-wise softmax:
   local max / reduce max
   subtract max
   exp
   local sum / reduce sum
   divide by sum

4. value aggregation GEMM:
   P @ V

5. optional fusion:
   scale、mask、causal mask、dropout-free inference path、post projection。
```

Attention 的关键不是“有没有 Attention 这个 op 名字”，而是 placement strategy：

```text
head-parallel:
  heads 在 mesh 某一维 shard，不同 PE 处理不同 head。
  大部分 QK^T / softmax / PV 可以在 head-local 范围内完成。

sequence-sharded:
  sequence/token 维被 shard。
  softmax 的 max/sum 可能跨 PE，需要 Partial(max/sum) + collective reduce。

hidden/output-sharded:
  projection GEMM 输出按 hidden/output 维 shard。
  后续如果算子需要完整 hidden，就需要 explicit redistribute。
```

用我们的四层架构描述 Attention：

```text
Layer 1:
  Attention 被表达成 matmul、transpose/view、scale、mask、softmax、matmul 的 operator graph。

Layer 2:
  每个 PE 拿到自己负责的 head/token/hidden shard 上的 local actions。

Layer 3:
  tile backend 把 GEMM、softmax max/sum、elementwise 和 PV aggregation 拆成 tile phases。
  遇到 softmax row max/sum 或 K-sharded GEMM partial sum 时，插入 collective boundary。

Layer 4:
  对每个 phase 生成 task/subtask/instance，复用 base_addr table 支持 tile stream 和可重定位 kernel。
```

可以给一个 softmax 子结构作为例子：

```text
if one PE owns the full softmax row:
  LocalPhase:
    max -> subtract -> exp -> sum -> divide

if softmax row is sharded across PE:
  LocalPhase:
    local_max
  CollectivePhase:
    all_reduce(MAX)
  LocalPhase:
    subtract_global_max -> exp -> local_sum
  CollectivePhase:
    all_reduce(SUM)
  LocalPhase:
    divide_by_global_sum
```

这说明 Attention 能成立的原因是：

```text
Attention = GEMM + elementwise + local reduce + collective reduce + fusion。
这些都是当前 architecture 设计的基本积木。
```

### 11.2 Partial 怎么落地？

回答要点：

```text
Partial 不是一种存储布局，而是一种 reduction obligation。
它表示每个 PE 上的 local value 只是全局结果的一部分贡献，
必须经过指定 reduce op 才能成为普通 Shard/Replicate tensor。
```

在 DTensor-like frontend 中：

```text
Partial("sum"):
  表示当前 tensor 在某个 mesh dimension 上有待求和的 partial result。

Partial("max"):
  表示当前 tensor 在某个 mesh dimension 上有待求 max 的 partial result。
```

典型例子 1：K-sharded GEMM。

```text
A[M,K]: placements = [Replicate(), Shard(1)]
B[K,N]: placements = [Shard(0), Replicate()]

每个 PE 只计算一段 K slice 的局部乘加：
  C_partial = local_matmul(A_k_slice, B_k_slice)

全局 C 需要对 K shard 维做 sum reduce：
  C = all_reduce_sum(C_partial)
```

在 IR 里的表达：

```text
C_partial:
  placements = [Partial("sum"), ...]
  reduce_obligation = {
    op: "sum",
    mesh_dims: [...]
    source_node: "matmul#..."
  }
```

在 tile backend 里的落地：

```text
LocalPhase:
  compute partial C tile

CollectivePhase:
  all_reduce(SUM) or reduce_scatter(SUM)
  participants = PE group along partial mesh dim

PostCollectiveLocalPhase:
  consume reduced C tile
  allow nonlinear post-op such as relu / gelu / maximum
```

典型例子 2：softmax 的 max/sum。

```text
local_max = max(local_score_tile)
global_max = all_reduce(MAX)(local_max)

local_sum = sum(exp(local_score_tile - global_max))
global_sum = all_reduce(SUM)(local_sum)
```

Partial 的规则：

```text
1. Partial tensor 不能直接作为 final output。
2. Partial tensor 不能直接喂给 nonlinear pointwise op。
   例如 relu(Partial("sum")) 不合法，必须先 reduce。
3. Partial 可以继续参与线性可结合的 accumulation，但必须保留 reduce obligation。
4. reduce 后的 tensor placement 必须变成 Shard 或 Replicate，不能继续假装普通 tensor。
```

validator 应检查：

```text
1. 每个 Partial tensor 是否有明确 reduce obligation。
2. 每个 reduce obligation 是否被 CollectivePhase 消解。
3. nonlinear op 的输入是否不含 unresolved Partial。
4. output tensor 是否不含 unresolved Partial。
5. reduce op 是否和 Partial kind 匹配，例如 Partial("sum") 不能用 MAX reduce 消解。
```

一句话回答：

```text
Partial 落地为 compiler 中显式的 reduce obligation，
再 lowering 成 tile-level CollectiveBundle 和 CollectivePhase。
```

### 11.3 Redistribute 怎么设计？

回答要点：

```text
Redistribute 必须是显式 source-level op，不能由 compiler 静默插入。
```

原因：

```text
DFU 上每次 layout movement 都是真实硬件动作：
COPY/COPYT、broadcast、gather/scatter、all_reduce、reduce_scatter、SPM load/store。

它会影响 task/subtask 切分、operand live range、instruction count、base address、
collective route 和最终性能。

因此 redistribute 必须在 source program、plan.json 和 debug trace 里可追踪。
```

用户层 API 形态可以是：

```python
B2 = redistribute(
    B,
    placements=[Replicate(), Shard(1)],
    reason="prepare_for_output_sharded_gemm",
)
```

或者：

```python
X = X.redistribute([Shard(0), Replicate()])
```

plan 中记录：

```text
RedistributeIntent:
  source_tensor
  source_placements
  target_placements
  mesh
  allowed_strategy
  source_node
  reason
```

lowering 策略按 placement change 分类：

```text
Shard -> Replicate:
  all_gather / broadcast / gather+copy

Replicate -> Shard:
  local slice / scatter / copy selected shard

Partial -> Replicate:
  all_reduce

Partial -> Shard:
  reduce_scatter

Shard(dim A) -> Shard(dim B):
  reshard, usually gather+scatter or staged route

Replicate -> Replicate:
  no-op unless mesh changes
```

进入 tile backend 后：

```text
RedistributeIntent
  -> one or more CollectiveBundle
  -> optional LocalPhase for slice/pack/unpack
  -> optional CollectivePhase for movement/reduction
  -> output LocalValue with target placement
```

validator 应检查：

```text
1. 所有 layout movement 都来自 explicit redistribute 或 explicit collective op。
2. matmul/pointwise 等普通 op 不允许偷偷修复 layout。
3. RedistributeIntent 的 source/target placement 合法。
4. 生成的 CollectiveBundle participant 覆盖了需要参与的 PE group。
5. reshape/pack/slice 后的 local shape 和 global offset 一致。
```

一句话回答：

```text
Redistribute 是显式 layout transform intent，
由 frontend 记录语义，由 backend lowering 成 collective/data movement bundle。
```

### 11.4 Collective bundle 怎么验证？

回答要点：

```text
Collective 不能只当作 debug 文本。
它必须同时有两个结构化视图，并且在写出前经过 validator 检查：

1. `CollectiveTileAction`:
   出现在每个 PE / TileScope 的 program view 中，说明这个 PE 在什么时候参与
   collective、产生或消费哪个 local visible value。

2. `CollectiveBundle`:
   出现在全局 registry view 中，说明这个 collective protocol instance 的
   kind、participants、roles、logical source 和 physical route。
```

`CollectiveTileAction` 至少需要记录：

```text
action_id
collective_kind
bundle_id
pe
role
input_refs
output_refs
owner_tile_ref or summary_value_ref
phase / tile_scope
```

`CollectiveBundle` 至少需要记录：

```text
bundle_id
collective_kind
participants
roles
input_refs
output_refs
logical_source
source_node / source_phase
mesh_axis or mesh_group
consumer phases
physical_route, initially unresolved
attrs
```

第一层验证：拓扑和 participant 合法。

```text
row_broadcast:
  participants 必须在同一 mesh row。

column_broadcast:
  participants 必须在同一 mesh column。

all_reduce:
  participants 必须覆盖指定 mesh group。

point-to-point copy:
  src/dst PE 必须存在，且 route 合法。
```

第二层验证：数据语义合法。

```text
1. producer tile 的 global range 与 consumer 需要的 range 一致。
2. A/B/C tile 的 GEMM range rule 成立：
   A.m == C.m
   B.n == C.n
   A.k == B.k
3. reduce bundle 的 op 和 Partial kind 一致。
4. bundle output placement 与目标 tensor placement 一致。
5. collective 的 input/output dtype、shape、tile_ref 合法。
```

第三层验证：phase schedule 合法。

```text
1. consumer action 引用的 bundle 必须存在。
2. bundle 引用的 producer/consumer action 必须存在。
3. collective input action 必须先于 consuming compute action，或处于明确的 same-tile streaming 规则中。
4. 所有 PE 的 phase/action sequence 在需要 BSP 同步的地方同构。
5. 每个 logical action 要么被 lowered，要么被标记为 fused。
6. 每个 fused action 必须有 source action 和 output ref 可追踪。
```

第四层验证：物理 lowering 前后的对应关系。

```text
logical collective bundle:
  row_broadcast(A tile)

physical route:
  PE00 -> PE01 -> PE02 -> PE03
  or PE00 fanout to row participants

需要检查：
  physical route 覆盖所有 logical participants；
  每个 consumer 的最终 tile identity 与 logical bundle 一致；
  route 没有引入错误的跨 row/col movement；
  COPY/COPYT 的 src/dst operand index 属于各自 PE-local address space。
```

当前已经实现的 validator 能覆盖：

```text
1. 所有 PE tile phase sequence 同构。
2. PE logical action 是否被 lowered 或 fused。
3. GEMM K-step 的 A/B/C range rule。
4. row_broadcast participant 是否在同一 row。
5. column_broadcast participant 是否在同一 column。
6. phase 引用的 bundle 是否存在。
```

后续需要扩展的 validator：

```text
1. Partial reduce obligation 是否被 collective 消解。
2. RedistributeIntent 是否完整 lowered。
3. all_reduce / reduce_scatter / all_gather 的 participant group 是否正确。
4. 每个 CollectiveTileAction 是否对应一个 CollectiveBundle。
5. 每个 CollectiveBundle 的 participants/roles 是否覆盖所有 per-PE action。
6. physical COPY/COPYT route 是否覆盖 logical bundle。
7. base_addr / operand index 是否和 tile identity 对齐。
```

一句话回答：

```text
Collective bundle 的验证分两步：
先验证 program view 中的 CollectiveTileAction 是否和 registry view 中的 CollectiveBundle 对齐；
再验证 physical COPY/COPYT route 是否忠实实现这个 logical bundle。
```

## 12. 当前开发进度

当前 compiler 已经完成第一版骨架，不只是设计文档：

```text
1. OperatorEnv 用户入口。
2. DTensor-like DeviceMesh / Placement / DTensorSpec / DTensor。
3. matmul + relu frontend op。
4. PE logical action dispatch。
5. LocalValue 记录 PE-local shard shape 和 global offset。
6. PETileProgram / TilePhase / TileScope / CollectiveBundle。
7. launch_group / task / subtask / instance plan。
8. plan.json 输出。
9. human-readable debug_ir 输出。
10. structural validator。
```

当前 baseline example：

```bash
python3 compiler/examples/gemm_relu.py
```

生成：

```text
tmp/gpdpu_compiler_examples/gemm_relu/plan.json
tmp/gpdpu_compiler_examples/gemm_relu/debug_ir/
```

当前生成结果可以这样汇报：

```text
operator: gemm_relu
mesh: 4 x 4 PE = 16 PE programs
global graph nodes: matmul + relu
per PE:
  4 local_gemm_summa tile phases
  each phase has 4 K-block updates
  relu fused as tile-local post-op before store
global tile backend:
  128 logical row/column collective bundles
  1 launch group
  4 task plan entries
```

最近几次 git / workspace 同步后的新增进展：

```text
1. tensor instruction set 已整理：
   明确 HMMAL / HMMA / RXINT / TRCTT 属于 tensor instruction family，
   HMMAL 通过 imm 字段写 tmp0..tmp7。

2. HMMAL / RX accumulator binding 已形成文档：
   GEMM 的 C accumulator 不是普通单一 operand，
   而是 RXINT / HMMAL / TRCTT 之间维护的 tensor tmp state。

3. tile-scope / value / view tension 已明确：
   tile 是调度和审阅单位，
   value 是硬件 producer/consumer 单位，
   tile view 是把 tmp/member values 解释成 tile-shaped value 的桥。

4. 活跃工作区已经开始把这个模型落进 plan/debug：
   k_block_updates 增加 owner_tile_ref、member_value_ref、member_kind、
   accumulator_view_ref 和 produces 字段；
   phase payload 增加 tile_scope；
   debug dump 从 TILE 改向 TILE_SCOPE / values / view / ops / output。

5. collective action 设计正在推进：
   collective 不再只是 Layer 5 provenance/bundle 表，
   后续应作为 CollectiveTileAction 进入每个 PE 的 tile program 时间线；
   CollectiveBundle 保留为全局 registry/source of truth。
```

validator 当前检查：

```text
1. 所有 PE tile phase sequence 同构。
2. 每个 PE logical action 都已经 lowered 或标记为 fused。
3. GEMM phase 的 K instance count 符合预期。
4. 每个 K step 满足 A.m == C.m, B.n == C.n, A.k == B.k。
5. row/column collective bundle participant 合法。
```

debug trace 的作用：

```text
帮助 reviewer 从 source graph 一路看到：
  tensor placement
  PE-local shard
  PE logical action
  tile phase
  K instance
  collective bundle
  task/subtask/instance mapping

debug_ir 只是人工审阅材料；
后续 lowering 应使用 structured IR 或 plan.json，不解析这些 text dump。
```

## 13. 下一步计划

短期目标：

```text
1. 继续把 plan.json 与甲方现有 GEMM/template_fusion 生成物对齐。
2. 从 TilePhase 展开到 operand/base_addr/instruction template。
3. 将 row/column logical collective bundle 物理化为 COPY/COPYT route。
4. 支持 explicit redistribute() frontend op。
5. 在 plan.json 中表达 layout-transform / collective intent。
6. 支持 Partial("sum") 以及 reduce/all-reduce 后接非线性 pointwise op。
7. 把 CollectiveTileAction 放进每个 PE 的 TileScope program view。
8. 把 TileScope / member values / TileView 从 debug trace 进一步沉淀为结构化 IR。
```

中期目标：

```text
1. 支持 K-sharded partial GEMM。
2. 支持更多 pointwise / reduce / normalize 算子。
3. 覆盖 log10 + max reduce + maximum 这类非 GEMM 融合算子。
4. 建立可重定位 kernel 的统一 base_addr / instance environment 生成逻辑。
5. 输出甲方 runtime/toolchain 可消费的 CSV / instruction package。
```

长期目标：

```text
1. 面向 Qwen3 / ASR / LLM 等模型建立关键算子 coverage。
2. 形成从模型 operator pattern 到 DFU kernel package 的自动化路径。
3. 让新模型部署主要变成 compiler rule 扩展和性能调优，而不是重写底层算子。
```

## 14. 汇报中的推荐说法

### 14.1 开场说法

```text
甲方的核心需求不是某一个算子，而是持续把不同模型部署到 DFU 芯片上。
当前半人工维护 tensor-core 汇编/CSV/task 结构的 workflow，无法支撑这个过程的自动化。
所以我们的工作重点是构建一个 DFU 算子编译器，把手写底层算子的过程编译器化。
```

### 14.2 解释 torch.distributed 类比

```text
我们不是要在 DFU 上跑 PyTorch distributed。
我们是借 torch.distributed / DTensor 的成熟抽象：
mesh、shard、replicate、partial、collective，
来描述 DFU 上 PE mesh 之间的计算和通信关系。

然后再把这套语义静态 lowering 到 DFU 的 task/subtask/instance 和 instruction package。
```

### 14.3 解释为什么不是 mock runtime

```text
runtime 是甲方闭源黑盒，我们拿不到源码，也不把复刻 runtime 作为目标。
我们的目标是 compiler：生成甲方现有 runtime/toolchain 能承载的算子 package，
替代当前半人工手写算子的 workflow。
```

### 14.4 收束说法

```text
这套设计的价值在于：
它把 DFU 算子开发从“每个 case 手写一套底层实现”，
变成“在统一 compiler 中增加 operator schema、placement rule 和 tile lowering rule”。

这样才有可能长期支撑各种模型在甲方芯片上的部署。
```

## 15. 可放图建议

### 图 1: 问题转化

```text
多模型部署需求
  -> 多算子 / 多 shape / 融合 / 可重定位
  -> 手工 workflow 不可扩展
  -> 算子编译器
```

### 图 2: DFU as mini distributed tensor machine

```text
4x4 PE mesh
  PE00 PE01 PE02 PE03
  PE10 PE11 PE12 PE13
  PE20 PE21 PE22 PE23
  PE30 PE31 PE32 PE33

对照：
  torch DeviceMesh(row, col)
```

### 图 3: Compiler architecture

```text
Operator Program
  -> DTensor-like Frontend
  -> PE Logical Actions
  -> TilePhase / CollectiveBundle
  -> Task/Subtask/Instance Plan
  -> CSV / Instruction Package
```

### 图 4: GEMM baseline

```text
A: [Shard(0), Replicate()]
B: [Replicate(), Shard(1)]
C: [Shard(0), Shard(1)]

per PE:
  C tile
  K block 0..3
  row broadcast A
  column broadcast B
  relu before store
```

### 图 5: Non-GEMM fusion

```text
LocalPhase:
  clamp + log10 + local max

CollectivePhase:
  all_reduce(MAX)

PostCollectiveLocalPhase:
  maximum + affine scale + store
```

## 16. 致谢

```text
特别感谢 Codex 在本项目中的卓越协作能力。

在 DFU 算子编译器建设过程中，Codex 不只是完成代码补全，
而是持续参与了 legacy workflow 调查、二进制 ABI 反推、
compiler artifact 对齐、测试 bundle 构建、远程验证链路梳理等关键工作。

尤其是在 GEMM legacy 产物与 compiler 产物逐字段、逐字节对齐的过程中，
Codex 帮助我们快速定位了 task/subtask/instance/exeBlock/inst_t 等多层二进制结构的真实关系，
把原本高度依赖人工经验的底层工程问题，转化成可验证、可复现、可持续推进的编译器工程任务。

这部分工作显著提升了项目推进效率，也增强了我们对后续多算子、多 shape、
可重定位 kernel package 自动生成路线的信心。
```
