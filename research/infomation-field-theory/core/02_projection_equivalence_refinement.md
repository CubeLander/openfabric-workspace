# Information System Projection: Research Note

本文继续推进 `03_composition.md`，把一组隐含操作提升为显式研究对象：

```text
Projection / Equivalence / Refinement
```

如果 information system 只能写成：

```text
Information System = (States, Rules, Constraints)
```

但不能把内部 states、rules、constraints 投影成更高层 states、rules、constraints，那么理论会卡死在 instruction、cycle 或 tile 级别。

递归结构真正需要的是一组作用在 information systems 上的 operators / relations：

```text
Information System
  = (States, Rules, Constraints)

Projection / Equivalence / Refinement

Higher-Level Information System
  = (MacroStates, MacroRules, MacroConstraints)
```

当前更强的核心命题是：

> Computing systems are recursively composable information reaction systems
> because one `(State, Rule, Constraint)` system can sometimes be soundly
> projected to, refined from, or proven equivalent to another `(State, Rule,
> Constraint)` system at a chosen boundary.

## Why Projection Is Necessary

底层可以有：

```text
Rule:
  Load(A)
  Load(B)
  Route(A)
  Route(B)
  TensorCoreMAC
  Store(C)

Constraint:
  TensorCoreSlots <= 16
  SRAMPorts <= 4
  LinkCredits <= 2
```

但上层不应永远处理这些 micro rules。它需要看到：

```text
MacroRule:
  GEMM Tile Update

Boundary effect:
  (A_tile, B_tile, Acc) -> Acc'

MacroConstraint:
  TileUpdateRate <= X
  RequiredSRAM >= Y
  DispatchOccupancy <= Z
```

这些 macro constraints 不是手写的新事实，而是底层 constraints 经过 projection / coarse-graining 后得到的边界表现。

继续往上：

```text
GEMM Tile Update -> GEMM Kernel
GEMM Kernel -> Transformer Layer
Transformer Layer -> Decode Step
Decode Step -> LLM Service
```

每一层都需要 projection，否则无法分析更大的系统。

## Coarse-Graining Analogy

这个过程很像物理里的粗粒化：

```text
10^23 molecules
  -> pressure / temperature / density
```

上层流体力学不会跟踪每个分子。但 projection 不是随便扔信息；它必须保留上层动力学需要的边界量。

计算系统里也是：

```text
many internal reaction rules
  -> macro behavior
  -> macro cost
  -> macro constraint envelope
```

例如：

```text
10000 DFU internal rules
  -> GEMM tile rule

many GEMM / attention / MLP rules
  -> transformer layer rule

many layer / sampling / cache rules
  -> decode step rule
```

如果 projection 太粗，上层会失去预测力；如果 projection 太细，上层分析会退化成重新展开所有 micro rules。

## Projection Operator

可以定义一个抽象 projection operator：

```text
project(IS_internal, boundary, abstraction)
  -> IS_macro
```

其中：

```text
IS_internal = (S, R, C)
IS_macro = (S_macro, R_macro, C_macro)
```

`boundary` 定义哪些状态和效果对外可见。

`abstraction` 定义保留哪些观测量，例如：

```text
value semantics
latency bound
throughput envelope
memory footprint
program-state footprint
resource occupancy
visibility guarantees
consistency guarantees
```

不同 abstraction 会产生不同 macro system。这个 macro system 仍然只是一个
`(State, Rule, Constraint)` 系统，不是第四种核心对象。

## State Projection

State projection 将内部状态分布映射成上层状态：

```text
sigma_S:
  S_internal -> S_macro
```

例子：

```text
many route tokens + tensor fragments + accumulator states
  -> GEMMTileInFlight(m, n)

many KV blocks + attention intermediate states
  -> DecodeContextState

TensorCoreBusy worldlines
  -> SMOccupancyProjection
```

State projection 必须保留上层 rules 的 preconditions 所需信息。

如果上层需要知道：

```text
output is visible in HBM
program state is resident
buffer ownership belongs to stream X
```

那么这些信息必须出现在 `S_macro` 里。

## Rule Projection

Rule projection 将内部合法 trajectory 映射成 macro rule：

```text
sigma_R:
  trajectories(R_internal, C_internal)
  -> R_macro
```

Macro rule 不只是规则名字，而是：

```text
MacroRule = (
  preconditions,
  effects,
  cost_projection,
  constraint_projection,
  refinement_witness_or_policy,
  boundary_equivalence
)
```

例如：

```text
Load + Route + MAC + Store
  -> GEMMTileUpdate
```

只有当存在一条满足内部 constraints 的合法 micro trajectory 时，macro rule 才成立。

## Constraint Projection

Constraint projection 是最重要也最难的一步：

```text
sigma_C:
  C_internal -> C_macro
```

底层 constraints：

```text
TensorCoreSlots = 16
SRAMPorts = 4
LinkCredits = 2
ProgramRows <= P
```

可能投影成：

```text
TileUpdateThroughput <= X
GEMMKernelLatency >= Y
LayerLatency >= Z
DecodeRate <= W tokens/sec
```

这就是性能 envelope 的来源。

因此：

```text
Capability Envelope
```

很可能就是：

```text
Constraint System
```

在某个 boundary 和 abstraction 下的 coarse-grained projection。

换句话说：

```text
Capability(IS, boundary, abstraction)
  = projection of feasible internal trajectories
    into boundary-visible behavior and cost space
```

## Soundness Conditions

Projection 不是任意压缩。它至少要满足以下条件。

### Semantic Soundness

Macro rule 的外部行为必须覆盖或等价于内部 behavior：

```text
observe_boundary(internal_execution)
  == apply_macro_rule(observed_initial_state)
```

若做保守抽象，可以允许 over-approximation，但必须标明方向。

### Constraint Soundness

Macro constraint 必须是内部约束的 sound projection：

```text
if macro says feasible:
  there should exist internal feasible trajectory

if macro gives lower bound:
  no internal trajectory can beat it

if macro gives upper bound:
  there exists an implementation with that cost
```

不能把不可实现的 macro behavior 当成可实现能力。

### Cost Soundness

Cost projection 必须保守：

```text
lower_bound <= true_cost <= known_upper_bound
```

如果只能给趋势或估计，也应明确是 heuristic projection。

### Interface Completeness

Projection 必须暴露下游组合所需的接口状态：

```text
representation
location
visibility
ownership
lifetime
consistency
rate/capacity contract
program/control protocol
```

接口信息缺失会导致 macro composition 虚假成立。

## Projection vs Lowering

传统编译器常说：

```text
lower high-level IR to low-level IR
```

OpenFabric 现在也有：

```text
Chip-level tensor program
  -> logical plan
  -> tile / fiber program
  -> vendor program
```

但理论上可以反过来看：

```text
lowering:
  refine macro rule into micro reaction system

projection:
  prove or project micro reaction system as macro rule
```

二者应形成关系：

```text
macro behavior
  refined by lowering
  implemented by micro states/rules/constraints
  projected back into macro behavior with cost/envelope
```

如果只有 lowering，没有 projection/equivalence，编译器能生成程序，但不能给出可组合语义和性能 envelope。

## Relation To OpenFabric

OpenFabric 一直在做多层 IR。新的解释是：

```text
Vendor Primitive
  <-> micro reaction rules

Tile Program
  <-> tile-level projected reaction system

Fiber Program
  <-> stream-local macro rules and dependencies

Logical Program
  <-> processor-level macro rules and visibility constraints

Tensor Program
  <-> boundary-visible target transformation
```

每一层都应该能回答：

```text
What internal states are hidden?
What macro states are exposed?
What rules are projected?
What constraints are projected?
What costs are preserved?
What refinement witness exists?
```

这比“IR lowering”更接近理论层面的解释。

## Attack Plan

### Attack 1: Tile Update Projection

输入：

```text
micro route / visibility / compute / store rules
```

输出：

```text
GEMMTileUpdate macro rule
```

检查：

- 是否保留 boundary-visible output。
- 是否隐藏内部 temporary states。
- 是否投影出 throughput / SRAM / dispatch constraints。

### Attack 2: Kernel Projection

把多个 tile update macro rules 投影成：

```text
GEMMKernel macro rule
```

检查：

- tile dependencies 是否闭合。
- cross-tile reductions 是否被正确暴露。
- kernel-level memory movement envelope 是否来自 tile constraints。

### Attack 3: Fusion Projection

比较：

```text
GEMM + Store + Load + ReLU
```

和：

```text
projected GEMMReLU macro rule
```

检查：

- boundary equivalence。
- internal state deletion。
- program-state growth。
- macro constraints 是否改变。

### Attack 4: Device Projection

把：

```text
PE rules + mesh rules + memory rules
```

投影成：

```text
Device capability envelope
```

检查 macro constraints 是否能解释：

```text
compute throughput
movement bottleneck
program capacity
route endpoint constraints
```

### Attack 5: Cross-Level Consistency

从两个方向验证：

```text
top-down lowering:
  Tensor Program -> Vendor Program

bottom-up projection:
  Vendor Program -> Tensor-level macro behavior
```

二者应在 boundary behavior 上相遇。

## Current Thesis

当前更强的理论表述是：

> A computing system is a recursively summarizable information reaction system:
> internal state trajectories, rule firings, and constraints can be projected
> into higher-level states, macro rules, and capability envelopes when semantic,
> constraint, cost, and interface soundness conditions hold.

这个命题把几条线合起来：

- 计算系统不是只由 state 组成，而是由 state/rule/constraint 三元结构组成。
- Macro rule 来自内部 reaction system 的封闭演化。
- Macro constraint 来自内部 constraint system 的投影。
- Capability envelope 是可行 internal trajectories 在边界上的粗粒化表现。
- Compiler lowering 和 system projection 应该互为 refinement/soundness 关系。

如果这个方向能做实，OpenFabric 就不只是多层 IR pipeline，而是在构造、细化、验证和投影 information reaction systems。
