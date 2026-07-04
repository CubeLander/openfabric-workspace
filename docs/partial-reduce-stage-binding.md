# Partial Reduce Stage Binding 设计笔记

日期：2026-06-27

这份笔记记录 `softmax_refactored` 里 `emit_subtask1_compute_phase` 的下一步重构
方向。

当前代码里最刺眼的是一个很长的 `switch (operation.op_type)`。但真正的问题不是
`switch` 这个语法本身，而是它把两类语义混在了一起：

```text
tile-local compute recipe
partial-reduce stage binding
```

前者只是“当前 tile 上怎么算”。后者才是 subtask1 / subtask2 两阶段协作的核心
协议。

## 当前丑 switch 实际在做什么

`emit_subtask1_compute_phase(...)` 现在把所有 `OpType` 都放在同一个分发表里：

```text
ADD/SUB/MUL/DIV/AND
SIGMOID/SILU/RELU/CLIP/GELU
SCALE
ROPE/ROPE_TRANSPOSE
RMSNORM/RMSNORM_TRANSPOSE
SOFTMAX
```

这里面并不是所有分支都绑定 `subtask1`。

## 第一类：普通 tile-local recipe

这些分支主要只消费当前 tile 的 input operand，然后产出 output operand：

```text
ADD/SUB/MUL/DIV/AND
SIGMOID/SILU/RELU/CLIP/GELU
SCALE
ROPE/ROPE_TRANSPOSE
```

它们应该被看成可复用的 tile-local 算子模板。

这些 recipe 可以依赖：

```text
site.input(...)
site.output(...)
site.local(...)
site.reuse_const(...)
site.hmul / site.hadd / site.fmul / ...
```

但它们不应该知道：

```text
SUM scratch 如何跨 subtask 传递
subtask1 写 SUM 后 subtask2 怎么读回
partial reduction 的阶段边界
```

即使 `SCALE` 和 `ROPE` 在 load/store 上有特殊布局，它们的 compute 本身仍然更像
tile-local recipe，而不是 partial-reduce stage。

## 第二类：partial-reduce stage

真正绑定 subtask1 阶段语义的是：

```text
RMSNORM/RMSNORM_TRANSPOSE
SOFTMAX
```

它们共享同一个阶段协议：

```text
读 input tile/chunk
  -> 在 PE local operand 上做局部统计
  -> 累加到 site.sum()
  -> PE 内 shuffle reduce
  -> subtask1 把 site.sum() 写入 SUM scratch
  -> subtask2 从 SUM scratch 读回若干 slot
  -> subtask2 完成归一化/除法/pack/store
```

这里的 `SUM` 不是用户可见输出，而是 SPM 里的内部 scratch DTensor。

## 绑定关系到底绑在哪里

绑定关系分散在四个位置。

### 1. subtask1 load

`emit_subtask1_input_load_template(...)` 决定当前阶段读哪些 input tile/chunk：

```text
SOFTMAX:
  读 min_unit / 256 / instance_num_cal_unit 个 H256 chunk

RMSNORM:
  min_unit == 4096 时读 16 个 H256 lane
  否则读 1 个 H256 lane
```

这说明 partial reduce 的输入粒度应该参数化。

### 2. subtask1 compute

`emit_softmax_subtask1_template(...)` 和 `emit_rmsnorm_subtask1_template(...)`
都做三件事：

```text
emit constants
zero site.sum()
for each partial unit:
  emit one local partial contribution into site.sum()
emit_sum_shuffle_reduce(site, site.sum())
```

不同点只是：

```text
SOFTMAX partial:
  H256 -> two F32 lanes -> multiply log2e -> clamp -> exp2 -> add to SUM

RMSNORM partial:
  H256 -> two F32 lanes -> square -> add to SUM
```

这说明 compute 阶段可以抽成一个通用的 partial-reduce skeleton。

### 3. subtask1 store

`emit_subtask1_store_phase(...)` 把 `site.sum()` 写到 `"SUM"`：

```text
SOFTMAX:
  store_sum_operand(site.sum(), 256)

RMSNORM:
  store_sum_operand(site.sum(), min_unit == 4096 ? 256 : 128)
```

这说明 SUM scratch 的 store stride 应该属于 stage binding 参数。

### 4. subtask2 consume

`emit_softmax_subtask2_template(...)` 和 `emit_rmsnorm_subtask2_template(...)`
从 SUM scratch 读 slot：

```text
SOFTMAX:
  load 4 slots, stride 128
  add slots
  optional regular_unit correction
  divide exp result by sum
  pack back to H256

RMSNORM:
  load 2 or 4 slots
  add slots
  divide by IMAGE_W
  add EPSILON
  rsqrt
  apply weight
```

这说明 subtask2 并不是独立算子，而是同一组 reduction fiber ops 的 consume 阶段。

## 建议抽象：FiberOp 组合 + ReductionFiberTemplate

这里不应该再引入一个执行层的 `PartialReducePlan`。

更准确的分层是：

```text
执行层 / 调度层:
  FiberOp 组合

代码组织层 / 生成层:
  ReductionFiberTemplate / Pattern / Traits
```

再往上一层看，这些 FiberOp 应该被装进同一个：

```text
FiberProgram
```

`FiberProgram` 是 OpenFabric 未来真正统一规划的平面。它不应该只描述计算，
也应该描述 tile/fiber 通信和 scratch materialization：

```text
FiberCompute:
  TileToLocalReductionSummary
  NormalizeTileWithSummary

FiberCommunication:
  StoreReductionSummaryToScratch
  LoadReductionScratch
  StoreOutputTile
```

所以长期方向不是：

```text
VendorSoftmaxFiberEmitter -> FiberProgram
```

而是：

```text
OpenFabric tensor graph
  -> FiberProgram
  -> VendorSoftmaxFiberEmitter / vendor template emitter
  -> vendor csv
```

当前 `softmax_refactored` 里的 vendor fiber emitter 继承试点，只是在最底层先把甲方手写
模板收成可替换的 emitter 边界。它不能反过来成为最高层 IR。

也就是说，上层语义直接描述成 fiber ops：

```text
TileToLocalReductionSummary
StoreReductionSummaryToScratch
```

后续 subtask2 也会逐步描述成类似：

```text
LoadReductionScratch
ConsumeReductionScratchToOutputTile
StoreOutputTile
```

`ReductionFiberTemplate` 只是生成这些 fiber ops 的代码组织方式，不是调度节点、
执行节点，也不是 IR 节点。

第一步可以把 `SOFTMAX/RMSNORM` 从 switch 里提出来，抽成：

```cpp
template <class ReductionFiberTemplate>
void emit_tile_to_local_reduction_summary(EmitSite &site,
                                          int instance_num_cal_unit) {
  ReductionFiberTemplate::emit_tile_to_local_reduction_summary(
      site, instance_num_cal_unit);
}
```

对应的 scratch materialization 可以是：

```cpp
template <class ReductionFiberTemplate>
void emit_store_reduction_summary_to_scratch(EmitSite &site) {
  site.store_sum_operand(
      site.sum(),
      ReductionFiberTemplate::scratch_store_stride(site));
}
```

## Softmax template 草图

```cpp
struct SoftmaxReductionFiberTemplate {
  static void emit_tile_to_local_reduction_summary(EmitSite &site,
                                                   int instance_num_cal_unit) {
    // 内部仍然可以保留 chunk/lane/vendor lowering。
  }

  static int scratch_store_stride(EmitSite &) {
    return 256;
  }
};
```

## RMSNorm template 草图

```cpp
struct RmsNormReductionFiberTemplate {
  static void emit_tile_to_local_reduction_summary(EmitSite &site,
                                                   int instance_num_cal_unit) {
    // 内部仍然可以保留 chunk/lane/vendor lowering。
  }

  static int scratch_store_stride(EmitSite &) {
    return min_unit == 4096 ? 256 : 128;
  }
};
```

## 注意事项

第一步不要把所有 `OpType` 都塞进这个模型。

普通 activation 和 elementwise 算子应该走另一个方向：

```text
TileComputeRecipe
```

partial reduction 应该单独成体系：

```text
ReductionFiberTemplate + FiberOp 组合
```

因为它多了一个非常关键的阶段边界：

```text
stage1 partial result -> SUM scratch DTensor -> stage2 consume
```

这正是 OpenFabric 需要从 vendor 手写代码里提炼出来的东西。

## 和 legacy fiber ops 的关系

legacy B-line 里有一个有价值的经验，也有一个需要避免的坑。

有价值的经验是：`FiberOp` 当时被定义成 stream-local 的 atomic tile job。也就是：

```text
FiberOp 不直接等于一条 vendor 指令；
FiberOp 是一个可审阅、可调度、可绑定依赖的 tile 级语义动作。
```

但是 legacy 里也遇到过一个边界问题：有些动作表面上像一个 `FiberOp`，内部实际
包含 pre / repeated / post 区域。例如 GEMM 的旧 bridge 曾经有：

```text
accumulator_prepare
repeated:
  materialize_A
  materialize_B
  gemm_update
finalize_accumulator
store_fragment
```

这个经验可以迁移到 softmax / rmsnorm，但要换一种更稳的用法。

早期草稿里把这个组合层叫过 `PartialReducePlan`，但这个名字容易误导。它听起来
像一个执行层计划节点，实际上我们需要的是：

```text
FiberOp:
  TileToLocalReductionSummary

FiberOp:
  StoreReductionSummaryToScratch
```

而 `ReductionFiberTemplate` 只负责生成这些 fiberop，并在 fiberop 内部保留 vendor
lowering：

```text
ReductionFiberTemplate 是代码组织层；
FiberOp 才是执行层 / 调度层原子。
```

## Partial reduce 的内部 lowering 观察

下面这些内容只用于理解当前代码内部怎么展开，不是上层调度可见的 fiberop 分解。

### 1. 常数初始化

```text
EmitConstants
```

例子：

```text
softmax:
  rLog2E
  imm100
  shfl constants

rmsnorm:
  shfl constants
  later subtask2 also needs IMAGE_W / EPSILON
```

这个元模板关注：

```text
只在 is_first_item() 时发一次；
常数进入 normal symbol 还是 reuse symbol；
常数属于 stage1 还是 stage2。
```

### 2. 局部 accumulator 初始化

```text
InitAccumulator(site.sum(), identity)
```

当前就是：

```text
site.sum() = 0
```

但语义上应该叫：

```text
初始化 partial reduction accumulator
```

这样以后遇到 max-reduce 时，identity 就不一定是 0。

### 3. 输入 fragment 解释

```text
LoadOrBindPartialUnit
```

它描述一个 partial unit 是怎么来的：

```text
softmax:
  unit = H256 chunk

rmsnorm:
  unit = H256 lane
```

当前这部分分散在 subtask1 load 和 compute 两边。后续可以让 plan 描述：

```text
unit_count
unit_operand(unit)
unit_memory_layout
```

### 4. 类型展开

```text
UnpackH256ToF32Pair
```

当前 softmax / rmsnorm 都在用同一种基本动作：

```text
H256 -> F32 lane0
H256 -> F32 lane1
```

只是后续计算不同。

### 5. 局部贡献计算

```text
LocalContribution
```

softmax:

```text
fp = h2fp(x)
fp = fp * rLog2E
fp = min(fp, imm100)
fp = exp2(fp)
sum += fp
```

rmsnorm:

```text
fp = h2fp(x)
square = fp * fp
sum += square
```

这说明 `TileToLocalReductionSummary` 的内部 lowering 可以继续整理成：

```text
MapToContribution
AccumulateContribution
```

### 6. PE 内 reduction

```text
InPeTreeReduce
```

当前实现是固定的 shuffle reduce：

```text
for shfl in 16,8,4,2,1:
  tmp = shfl(sum)
  sum += tmp
```

这个是很典型的可复用 fiber-level 元模板。它不属于 softmax，也不属于 rmsnorm；
它属于：

```text
在一个 PE 内把 vector/scalar partial 归约成 local summary
```

### 7. scratch materialize

```text
StoreReductionScratch
```

当前就是：

```text
HSTT site.sum() -> SUM[row, :]
```

这个动作的语义不是普通 store output，而是：

```text
把 stage1 的 partial summary materialize 到 SPM scratch DTensor
```

### 8. scratch consume

```text
LoadReductionScratchSlots
CombineReductionScratchSlots
```

当前 subtask2 做：

```text
ILDMT SUM slot0..slotN
FADD 合并 slot
```

这和 stage1 是同一组 reduction fiber template 的另一半。

### 9. 归一化 / finalize

```text
FinalizeFromReducedSummary
```

softmax:

```text
exp(x) / sum
pack back to H256
```

rmsnorm:

```text
sum / IMAGE_W
sum + EPSILON
rsqrt(sum)
x * rsqrt(sum) * weight
```

## 当前实现里的 fiberop 原子边界修正

上面把 `TileToLocalReductionSummary` 的内部 lowering 继续拆成很多小步骤，有助于
读代码，但不能把那些小步骤都叫成 fiberop 原子任务。

fiberop 原子边界应该按 tile 语义划分。也就是说，一个 fiberop 应该说清楚：

```text
它消费哪个输入 tile；
它产生哪个 tile-level value / scratch value；
它和后续 fiberop 之间有什么依赖。
```

从上层调度来看，fiberop 的执行粒度就是 tile。tile 内部怎么拆 chunk/lane、怎么做
局部微运算、怎么安排 vendor operand，都是这个 fiberop 内部不可分的 lowering
内容。调度层不应该把这些内部步骤当成可单独重排、可单独依赖、可单独 materialize
的任务。

它不应该暴露：

```text
从 tile 里选第几个 chunk；
从 H256 里拆成哪两个 F32 lane；
用了几条 FADD / FEXP2 / SHFL；
vendor 需要怎样的 operand 命名。
```

这些都是 tile 原子内部的 lowering 细节。

因此对 stage1 来说，更合理的 fiberop 边界只有两个：

```text
1. TileToLocalReductionSummary
2. StoreReductionSummaryToScratch
```

### 1. TileToLocalReductionSummary

这个 fiberop 消费一个输入 tile，产出 PE-local 的 summary value。

softmax:

```text
input tile X
  -> local_sum = sum(exp(X))
```

rmsnorm:

```text
input tile X
  -> local_sum = sum(X * X)
```

当前代码里的这些动作：

```text
emit constants
zero site.sum()
for chunk/lane:
  H256 -> F32 pair
  contribution = exp(...) or square(...)
  sum += contribution
shuffle reduce
```

都属于 `TileToLocalReductionSummary` 这个 fiberop 的内部展开，不应该成为
fiberop 级原子。

这也解释了为什么 `EnumeratePartialUnits` / `BindInputUnit` 这种名字不应该站到
fiberop 层：它们只是说明 vendor 的一个 logical tile 在当前机器上如何被拆成
H256 chunk/lane 来算。

### 2. StoreReductionSummaryToScratch

这个 fiberop 消费 PE-local summary value，把它 materialize 到 `SUM` scratch
DTensor。

softmax:

```text
local_sum -> SUM_scratch[row, :]
```

rmsnorm:

```text
local_square_sum -> SUM_scratch[row, :]
```

这一项可以独立出来，因为它跨过了一个真实阶段边界：

```text
PE-local operand value
  -> SPM scratch DTensor
  -> subtask2 later consumes it
```

所以“写回 SUM”不是普通实现细节，而是一个明确的 materialization / stage boundary。

## 元模板和 fiberop 的关系

更准确的层次应该是：

```text
FiberOp:
  TileToLocalReductionSummary
    internal lowering:
      constants
      unit loop
      H2FP
      contribution formula
      local accumulation
      in-PE shuffle reduce

FiberOp:
  StoreReductionSummaryToScratch
    internal lowering:
      choose SUM scratch layout
      HSTT summary value
```

也就是说：

```text
元模板是 fiberop 内部 lowering 构件；
fiberop 原子仍然以 tile-level value / scratch materialization 为边界。
```

后续第一步重构也应该按这个边界做，而不是把 chunk/lane 级 helper 先提升成一堆
对象。

## 更准确的组织方式

因此下一步可以把层次改成：

```text
OpType dispatcher
  -> TileComputeRecipe            // elementwise / activation / rope / scale
  -> ReductionFiberTemplate       // softmax / rmsnorm 的生成模板
       -> FiberOps                // tile 粒度原子动作
            -> internal lowering  // tile 内部不可分展开
```

更具体一点：

```cpp
struct SoftmaxReductionFiberTemplate {
  static void emit_tile_to_local_reduction_summary(...);
  static int scratch_store_stride(...);
};
```

在 C++ 里未必一开始真要做这么多类型。比较稳的落地方式是：

```text
先按 tile-level fiberop 边界抽函数；
再把 softmax/rmsnorm 的变化点变成 ReductionFiberTemplate static 方法；
最后把 chunk/lane/H2FP/FADD/SHFL 等内部展开保留在 fiberop lowering 里。
```

这样不会回到 legacy 那种一上来架空 vendor 现实的路线。

## 带参数的 fiberop template

从这个视角看，当前 partial reduce 可以分解成带参数的 template。

但 template 的参数不必全是 tile。更准确地说：

```text
template 参数必须是调度层可见的语义对象。
```

这些对象可以是：

```text
TileRef:
  一个输入 / 输出 / scratch tile。

LocalValueRef:
  某个 fiberop 执行完成后产生的 PE-local 结果量。

ScratchValueRef:
  已经 materialize 到 SPM scratch 里的中间 tile/value。

LayoutRef:
  tile 或 scratch value 的布局规则。
```

关键边界是：template 可以引用原子 fiberop 的最终结果量，但不能引用这个 fiberop
内部的中间状态。

错误方向：

```text
chunk_idx
fp32_lane
H2FP temporary name
shuffle step index
vendor operand symbol
tile 内部 partial sum 的半路状态
```

这些都属于 fiberop 内部 lowering。

正确方向：

```text
input tile
local summary value
local contribution function
reduction operator
scratch DTensor / scratch layout
stage boundary
```

### Template 1: TileToLocalReductionSummary

这个 template 的通用形状是：

```text
TileToLocalReductionSummary<
  InputTile,
  SummaryValue,
  ContributionFn,
  ReduceOp,
  Identity
>
```

语义是：

```text
SummaryValue = reduce(ReduceOp, map(ContributionFn, InputTile), Identity)
```

softmax 实例：

```text
InputTile      = softmax0_input0[row]
SummaryValue   = local_softmax_sum[row]
ContributionFn = exp
ReduceOp       = sum
Identity       = 0
```

也就是：

```text
local_softmax_sum[row] = sum(exp(softmax0_input0[row]))
```

rmsnorm 实例：

```text
InputTile      = rmsnorm_input0[row]
SummaryValue   = local_square_sum[row]
ContributionFn = square
ReduceOp       = sum
Identity       = 0
```

也就是：

```text
local_square_sum[row] = sum(rmsnorm_input0[row] * rmsnorm_input0[row])
```

注意：`exp` 在 vendor lowering 里可能展开成 `H2FP -> FMUL rLog2E -> FMIN ->
FEXP2`；`square` 可能展开成 `H2FP -> FMUL`。这些展开不改变 fiberop
template 的 tile 级边界。

### Template 2: StoreReductionSummaryToScratch

这个 template 的通用形状是：

```text
StoreReductionSummaryToScratch<
  LocalSummaryValue,
  ScratchTensor,
  ScratchTile,
  ScratchLayout
>
```

语义是：

```text
ScratchTensor[ScratchTile] = LocalSummaryValue
```

softmax 实例：

```text
SummaryValue  = local_softmax_sum[row]
ScratchTensor = SUM_scratch
ScratchTile   = row
ScratchLayout = softmax SUM row layout
```

rmsnorm 实例：

```text
SummaryValue  = local_square_sum[row]
ScratchTensor = SUM_scratch
ScratchTile   = row
ScratchLayout = rmsnorm SUM row layout
```

这一步应该单独成为 fiberop，是因为它是 materialization boundary：

```text
PE-local summary value -> SPM scratch DTensor
```

### 对应到当前代码

当前 `emit_softmax_subtask1_template(...)` 和 `emit_rmsnorm_subtask1_template(...)`
其实都在实现：

```text
TileToLocalReductionSummary
```

当前 `emit_subtask1_store_phase(...)` 里的 `SOFTMAX/RMSNORM` 分支实现：

```text
StoreReductionSummaryToScratch
```

所以第一步代码重构不应该急着拆 chunk/lane。更合理的是先形成：

```cpp
template <class Plan>
void emit_tile_to_local_reduction_summary(EmitSite &site);

template <class Plan>
void emit_store_reduction_summary_to_scratch(EmitSite &site);
```

`Plan` 只提供调度层可见的语义参数：

```cpp
struct SoftmaxLocalSumPlan {
  static void emit_constants(EmitSite &site);
  static InputTileRef input_tile(EmitSite &site);
  static LocalValueRef local_summary_value(EmitSite &site);
  static ScratchTileRef scratch_tile(EmitSite &site);
  static void emit_tile_internal_lowering(EmitSite &site);
  static int scratch_store_stride(EmitSite &site);
};
```

这里 `emit_tile_internal_lowering(...)` 可以暂时保留当前 chunk/lane 循环。它是
template 的 lowering 实现，不是上层调度可见的 fiberop 分解。

## 原子性规则

这套设计里最重要的规则是：

```text
fiberop 的执行粒度是 tile；
tile 内部过程和局部状态对上层调度不可见、不可分、不可依赖。
```

所以 `TileToLocalReductionSummary` 可以被写成一个带参数 template，但它执行时仍然是
一个原子 fiberop：

```text
InputTile -> LocalSummaryValue
```

上层可以依赖：

```text
LocalSummaryValue
```

但不可以依赖：

```text
H2FP 后的 fp0/fp1；
某个 chunk 的 contribution；
shuffle reduce 中间第 3 步的 sum；
vendor operand RAM 里的临时 symbol。
```

`StoreReductionSummaryToScratch` 则引用 `LocalSummaryValue` 作为输入：

```text
LocalSummaryValue -> ScratchTensor[ScratchTile]
```

这不破坏原子性，因为 `LocalSummaryValue` 是上一个 fiberop 已完成后的出口值，而不是
上一个 fiberop 内部半路状态。

## 一个重要边界

legacy fiber RFC 里有一个正确提醒：

```text
operator semantics 不应该直接拥有 loop folding / phase placement 策略。
```

套到现在就是：

```text
Softmax/RMSNorm 知道自己有 reduction；
但 subtask1/subtask2 怎么切、SUM scratch 怎么 materialize，
应该逐步变成 stage binding / lowering 策略。
```

所以最终目标不是让 `SoftmaxReductionFiberTemplate` 变成一个新的大泥球，而是：

```text
Softmax/RMSNorm 提供 tile-level fiberop 的 lowering 模板；
stage binding 组合这些 fiberop；
vendor lowering 再把组合结果落成 HLDT/FEXP2/FADD/HSTT/ILDMT 等行。
```

## 下一步重构建议

推荐顺序：

1. 添加 `SoftmaxReductionFiberTemplate` / `RmsNormReductionFiberTemplate`。
2. 用 `emit_tile_to_local_reduction_summary<Template>(...)` 替换
   `emit_softmax_subtask1_template` 和 `emit_rmsnorm_subtask1_template` 的直接分支。
3. 把 `emit_subtask1_store_phase` 中的 `SUM` store 分支改成
   `emit_store_reduction_summary_to_scratch<Template>(site)`。
4. 最后再处理 subtask2 consume，不要第一步就把 subtask2 一起卷进去。

这样可以保持每一步都能做二进制 parity 检查。
