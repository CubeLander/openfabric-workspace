# OpenFabric 理想抽象模型笔记

状态：历史讨论笔记；已被 `TWO_LEVEL_DTENSOR_NOTES_CN.md` 修正命名。

日期：2026-07-04

这份笔记记录一个更理想化的 OpenFabric 抽象方向：OpenFabric 不应该只是把
DFU3500 vendor CSV / register helper 包一层更好看的 API，而应该建立清晰的
逻辑模型和物理 lowering 边界。

2026-07-04 后续修正：本文里的 `DTensor tile` 是过渡命名。当前更推荐的语言是：

```text
Tensor
  -> StreamTensorView
  -> FiberTensorView
  -> TileRef / TypedTileValue
  -> Operand
```

因此，本文仍保留“只应该有一种 tile”和“逻辑运算先于物理指令”的判断，但不再把
`DTensorTile` 作为最终命名。

核心观点：

```text
OpenFabric 里只应该有一种 tile：DTensor tile。
开发者应该面对逻辑运算，不应该直接面对物理指令。
物理指令、operand symbol、base slot、imm offset 都是 backend lowering 的结果。
```

## 只保留一种 Tile：DTensor Tile

理想状态下，OpenFabric 里的 tile 应该只有一种：

```text
DTensorTile / DTensorTileRef / DTensorTileView
```

它表达的是一个逻辑 tensor 的局部区域，而不是某种寄存器形态。

一个 DTensor tile 应该回答：

```text
这是哪个 tensor 的 tile？
它覆盖哪些 row/col/window？
元素类型是什么？
逻辑 shape 是什么？
这个 tile 在哪个 task / PE / stage context 中被使用？
这个 tile 当前对哪个 stage/window 可见？
```

也就是说，DTensor tile 是逻辑数据视图。它不是：

```text
H256 operand
F32 vector
GEMM A strip
GEMM B strip
tensor tmp accumulator
CSV register symbol
PE-local operand RAM index
```

这些都应该是 tile 被物化之后的 value / fragment / operand 形态，而不是新的
tile 种类。

因此，现在一些名字里带 `Tile` 的对象，长期看可能需要重新命名或重新分层：

```text
FiberH256Tile
FiberF32Tile
GemmLocalTile
GemmAccumulatorTile
```

它们不一定都是错的，但它们容易让人误以为 OpenFabric 里存在多种 tile。更理想
的名字可能是：

```text
FiberTileValue
TileFragmentValue
MaterializedTileValue
GemmOperandBundle
GemmAccumulatorValue
```

关键区别是：

```text
DTensor tile:
  逻辑数据区域。

Tile value / fragment / operand bundle:
  某个 DTensor tile 在某个 backend / stage / PE 上的物化形态。
```

## 增加逻辑运算层

开发者不应该直接写：

```cpp
fadd(...)
fmul(...)
hadd(...)
hmax(...)
h2fp(...)
fp2h(...)
hldt(...)
hstt(...)
hmmal(...)
```

这些名字已经是 DFU3500 物理或准物理指令语义。它们适合出现在 backend
lowering 层，不适合作为 OpenFabric 的主要编程表面。

开发者更应该面对逻辑运算：

```cpp
add(...)
mul(...)
max(...)
convert(...)
load(...)
store(...)
matmul_accumulate(...)
```

这些运算的含义由输入输出 value 的类型、tile 的 dtype/shape、以及当前 backend
lowering context 决定。

例如：

```text
add(F32Vector, F32Vector)
  -> DFU3500 FADD

add(H256HalfVector, H256HalfVector)
  -> DFU3500 HADD, if supported and semantically correct

max(F32Vector, F32Vector)
  -> DFU3500 FMAX

max(HalfTileValue, HalfTileValue)
  -> DFU3500 HMAX or another typed lowering path

convert(H256TileChunk -> F32Vector)
  -> DFU3500 H2FP

convert(F32Vector -> H256TileChunk)
  -> DFU3500 FP2H or a packed store path

load(DTensorTileView, H256TileChunk)
  -> DFU3500 HLDT / LDN pseudo lowering

store(DTensorTileView, H256TileChunk)
  -> DFU3500 HSTT / STD pseudo lowering

matmul_accumulate(GemmAStrip, GemmBStrip, GemmAccumulatorValue)
  -> DFU3500 RXINT / HMMAL / TRCTT sequence
```

这样，`FADD` / `HADD` / `HMMAL` 不再是开发者主动选择的公共抽象，而是 backend
根据类型和目标硬件选择的物理实现。

## 理想分层

更理想的 OpenFabric 可以分成五层：

```text
1. DTensor tile layer
   只有一种 tile：DTensorTileRef / DTensorTileView。

2. Logical value layer
   描述一个 tile 或 tile fragment 当前作为什么逻辑值存在。

3. Logical operation layer
   add, mul, max, convert, load, store, matmul_accumulate 等。

4. Physical operation layer
   FADD, FMUL, HADD, HMAX, H2FP, FP2H, HLDT, HSTT, HMMAL, RXINT, TRCTT 等。

5. Operand / address materialization layer
   OperandHandle, OperandProjectionPath, normal/reuse/tensor-tmp class,
   base slot, imm offset, reg offset, vendor CSV fields。
```

这五层解决的是不同问题。

### 1. DTensor Tile Layer

这一层只表达逻辑数据区域：

```text
tensor
dtype
shape
tile coordinates
task / PE ownership
stage/window visibility
```

它不关心这个 tile 最后会被加载到几个 operand symbol，也不关心 vendor pseudo op
会展开成几条底层指令。

### 2. Logical Value Layer

这一层表达“某个逻辑 tile 当前以什么值形态参与计算”。

例子：

```text
H256TileChunkValue
F32VectorValue
F32ScalarValue
SummaryScratchValue
GemmAStripValue
GemmBStripValue
GemmAccumulatorValue
```

这些 value 应该带有：

```text
owner DTensor tile/view
value kind
element type
lane/chunk shape
PE context
logical identity path
```

其中 logical identity path 可以继续由 `OperandProjectionPath` 或未来的
`ValueProjectionPath` 表达。

### 3. Logical Operation Layer

这一层是开发者和 operator author 最应该面对的层。

它的 API 应该表达算法意图：

```cpp
auto x = load(input_tile);
auto xf = convert<F32Vector>(x);
auto y = add(xf, bias);
auto z = max(y, zero);
store(output_tile, z);
```

在当前 OpenFabric 仍然是 imperative emitter 的情况下，也可以先写成更显式的
形式：

```cpp
auto x = site.load_h256(input_tile);
auto xf = site.convert<F32Vector>(dst0, x);
auto y = site.add(dst1, xf, bias);
auto z = site.max(dst2, y, zero);
site.store(output_tile, z);
```

重点不是马上做表达式模板，而是让 `add` / `max` / `convert` 成为逻辑操作，而
不是让业务代码直接选择 `FADD` / `HMAX` / `H2FP`。

### 4. Physical Operation Layer

这一层是 target backend 的责任。

它负责把逻辑操作落到 DFU3500 指令或 pseudo 指令：

```text
add(F32Vector) -> FADD
mul(F32Vector) -> FMUL
max(F32Vector) -> FMAX
convert(H256 -> F32) -> H2FP
load(H256 chunk) -> HLDT
store(H256 chunk) -> HSTT
matmul_accumulate -> RXINT / HMMAL / TRCTT
```

这一层应该保留 target-specific 事实，不要把硬件语义藏没：

```text
HMMAL 的 data_select_type 不是 B lane。
HMMAL 的 dst_tmp 不是普通 destination operand。
matrix half 和 register half 不是同一件事。
ILDMT grouped load 不是完整 fp32 vector load。
HLDT/HSTT 是 pseudo memory op，会继续被 vendor lowering 展开。
```

也就是说，逻辑操作层可以隐藏物理指令名字，但不能撒谎。遇到 GEMM/HMMAL 这类
不是普通 elementwise op 的能力，逻辑 API 也应该显式叫：

```text
matmul_accumulate
contract
mma_accumulate
```

而不是强行伪装成普通 `add`。

### 5. Operand / Address Materialization Layer

这一层负责真正对接 vendor-visible fields：

```text
OperandHandle
OperandProjectionPath
OperandClass
legacy symbol
normal operand
reuse operand
tensor tmp selector
base_addr slot
reg_offset
imm_offset
CSV row fields
```

这一层是必要的，因为 DFU3500 的 vendor assembler 还会继续做 symbol 到
PE-local operand RAM index 的分配。

因此 OpenFabric 不应该过早把逻辑 value 绑定成最终物理 index。它应该保留：

```text
逻辑 value identity
typed value kind
symbolic materialization handle
backend lowering evidence
```

## 类型如何参与 Lowering

类型系统应该服务于两个目标：

```text
1. 让逻辑操作可以根据 value kind 选择正确 physical op。
2. 阻止明显错误的 value / opcode 组合。
```

例如：

```cpp
add(F32Vector, F32Vector)
```

可以合法 lowering 到 `FADD`。

但下面这些应该在编译期或早期验证时报错：

```cpp
add(H256TileChunk, F32Vector)
fadd(H256TileChunk, H256TileChunk)
hmmal(F32Vector, F32Vector, NormalOperand)
store(F32Vector, Fp16TileWithoutConvert)
```

模板和 traits 可以帮助表达这种规则：

```cpp
template <class ValueKind>
struct ValueTraits;

template <class Op, class Lhs, class Rhs>
struct LogicalOpLowering;
```

但模板不应该承载所有东西。它适合表达稳定的语义类别：

```text
F32Vector
H256TileChunk
H64ScratchChunk
GemmOperandStrip
GemmAccumulatorValue
```

它不适合表达大量动态事实：

```text
task_id
subtask_index
instance_id
pe_id
row_start
col_start
runtime window index
base address
CSV imm
```

这些动态事实应该留在 plan/view/materialization object 里，并通过运行时或
生成期 fail-fast 检查保证正确。

## Address 也应该遵守同样分层

地址不应该在业务代码里表现为普通整数到处传。

理想分层是：

```text
DTensorTileView:
  逻辑 tensor tile。

StageTensorWindowScope:
  当前 stage instance 可见的 tensor window。

StageBaseRowProjection:
  stage/subtask/instance 的 base_addr row。

TileAccessPlan:
  某个 PE/lane 在 stage-visible window 内访问哪个 tile 区域。

TileMemoryAccess:
  backend memory reference: base slot + reg offset + imm offset。
```

这样可以避免一个整数同时被误解为：

```text
SPM byte address
vendor word address
element offset
tile row
lane offset
base_addr slot
CSV imm
```

地址 lowering 和 register lowering 其实是同一类问题：逻辑事实、类型事实和
物理字段必须分开。

## 开发者理想体验

理想状态下，operator author 写的是：

```cpp
DTensorTileView x_tile = site.tile(input);
DTensorTileView y_tile = site.tile(output);

auto x = site.load(x_tile);
auto xf = site.convert<F32Vector>(x);
auto y = site.add(xf, bias);
site.store(y_tile, y);
```

GEMM 类 operator 则写：

```cpp
auto a = site.load_gemm_a(a_tile);
auto b = site.load_gemm_b(b_tile);
auto acc = site.accumulator(c_tile);

site.matmul_accumulate(acc, a, b);
site.store(c_tile, acc);
```

这里的 `load_gemm_a` / `load_gemm_b` 仍然可以是 target-aware logical helper，
因为 GEMM 的物化形态和普通 vector load 不一样。关键是它们仍然返回 typed
logical value，而不是让业务代码直接拼 `HMMAL` 的 CSV fields。

## 和当前代码的关系

当前代码已经有一些正确方向：

```text
DTensorTileRef
ContextTileView
OperandProjectionPath
OperandHandle
VecH256 / VecH64 / VecF32
FiberH256Tile / FiberF32Tile
GEMM accumulator context
```

但理想模型会进一步要求：

```text
1. 不再扩散新的 tile 概念，统一回 DTensor tile。
2. 把 FiberH256Tile / GemmLocalTile 这类对象解释为 value/materialization，
   而不是 tile 本身。
3. 把 fadd/fmul/h2fp/hmmal 等 API 下沉为 physical register actions。
4. 在更高层提供 add/mul/max/convert/load/store/matmul_accumulate。
5. 由 typed value + lowering context 选择具体 physical instruction。
```

## 近期可行路线

不要一上来重写成完整 DSL。更稳的路线是：

```text
1. 先统一术语：
   只有 DTensor tile 是 tile。
   其他是 value / fragment / materialization。

2. 增加 typed logical value：
   H256TileChunkValue, F32VectorValue, GemmOperandStripValue,
   GemmAccumulatorValue。

3. 在现有 RegisterActions 上方加一层 LogicalActions：
   add, mul, max, convert, load, store。

4. LogicalActions 内部继续调用现有 RegisterActions：
   add(F32Vector) -> reg.fadd
   convert(H256,F32) -> reg.h2fp
   load(H256) -> reg.load_h256

5. GEMM 单独加 target-aware logical helpers：
   load_gemm_a, load_gemm_b, matmul_accumulate, store_gemm_output。

6. 等 imperative typed API 稳定后，再考虑表达式模板或更高级 DSL。
```

## 判断一个抽象是否正确

一个新抽象应该通过这些检查：

```text
它有没有把新的东西叫成 tile？
如果叫 tile，它是不是真的代表 DTensor tile？

它有没有让业务代码直接选择 FADD/HMMAL/HLDT？
如果有，它是不是已经越过了 logical op boundary？

它有没有把 HMMAL tensor tmp 伪装成普通 destination operand？

它有没有把 dtype/chunk/lane/operand class/base slot 混成一个 int/string？

它能不能解释同一个 logical add 在不同 value type 下选择不同 physical op？

它能不能解释为什么 ILDMT 不能被当成普通 fp32 vector load？
```

## 总结

理想状态下，OpenFabric 的抽象中心不是 DFU3500 指令，也不是 operand symbol，
而是：

```text
DTensor tile + typed logical value + logical operation
```

DFU3500 的物理指令、CSV row、operand symbol、base_addr slot、imm offset 都应该
是 lowering 的结果。

这条边界一旦立住，OpenFabric 才能同时获得两件事：

```text
对开发者：更像写 tensor/tile 算法，而不是写 vendor assembly。
对 backend：仍然能精确表达 DFU3500 的 HMMAL、HLDT、HSTT、tensor tmp 等硬件事实。
```
