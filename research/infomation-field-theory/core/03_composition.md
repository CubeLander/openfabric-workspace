# Information System Composition: Research Note

本文继续推进 `01_minimal_core_and_falsifiability.md`，讨论整个理论能否真正递归组合。

如果：

```text
States
Rules
Constraints
```

不能组合，那么这个理论只能描述一个固定系统，无法解释：

```text
Instruction -> Kernel -> Layer -> Model -> Service
PE -> Device -> Node -> Cluster -> Datacenter
```

这些递归层级。

当前最重要的命题是：

> A computing system is compositional not because its states compose, but because
> its states, rules, and constraints can all be recursively projected into
> higher-level states, rules, and constraints.

## 基本组合形式

一个 information system 可以写成：

```text
IS = (S, R, C, B)
```

其中：

- `S`: information state space。
- `R`: reaction rules。
- `C`: constraint system。
- `B`: boundary，定义外部可见的状态、事件、效果和成本。

组合问题是：

```text
IS_1 + IS_2 + InterfaceConstraints
  -> IS_macro
```

或者更一般：

```text
compose(IS_1, IS_2, ..., topology, interface_constraints)
  = IS_macro
```

其中：

```text
IS_macro = (S_macro, R_macro, C_macro, B_macro)
```

## Macro State

Macro state 是一组 internal states 在边界上的投影。

```text
S_macro = project_states(S_internal, boundary)
```

例子：

```text
Internal:
  A_tile in SRAM0
  B_tile visible at PE7
  Acc partial state
  TensorCoreBusy
  LoopCounter(k=3)

Boundary projection:
  GEMM tile update in flight
```

或者：

```text
Internal:
  many KV cache blocks
  attention scores
  softmax intermediates
  MLP activations

Boundary projection:
  DecodeStepState(token_t -> token_t+1)
```

Macro state 必须保留外部后续 rules 需要的所有信息，隐藏内部不再 relevant 的细节。

## Macro Rule

Macro rule 是一组 internal rules 的组合投影：

```text
R_macro = project_rules(R_internal, C_internal, boundary)
```

它对外暴露：

```text
MacroRule = (
  preconditions,
  effects,
  cost_projection,
  resource_projection,
  boundary_effects,
  validity_conditions
)
```

例子：

```text
Load + Route + MAC + Store
  -> GEMM Tile Update

GEMM Tile Updates + Reductions + Stores
  -> GEMM Kernel

Attention + MLP + Norm + Residual
  -> Transformer Layer

Transformer Layers + Sampling
  -> LLM Decode Step
```

从外部看：

```text
Token_t -> Token_{t+1}
```

可以是一个 macro rule。内部可能有数百万 micro rules firing。

## Macro Constraint

Macro constraint 是 internal constraints 经过边界投影和保守近似后的结果：

```text
C_macro = project_constraints(C_internal, R_internal, boundary)
```

这一步尤其关键。很多模型能组合状态和规则，但无法组合约束，于是性能上界无法自然出现。

例子：

```text
Tensor Core:
  one op per cycle

SM:
  number of tensor cores
  shared memory capacity
  register capacity
  warp scheduler slots

GPU:
  HBM bandwidth
  L2 capacity
  SM count
  launch/scheduling constraints

Node:
  PCIe/NVLink bandwidth
  CPU-GPU transfer constraints

Cluster:
  network topology
  AllReduce latency/bandwidth
```

这些不是互不相关的新约束，而是：

```text
micro constraints -> macro constraints
```

的递归投影。

## Macro Rule 合法性

一个 macro rule 不是随便把几条 micro rules 包起来就成立。它至少要满足三个 closure 条件。

### State Closure

内部状态不能以未声明方式泄露。

```text
All internal states are either:
  consumed,
  hidden,
  projected into macro state,
  or explicitly exposed through boundary.
```

如果外部后续 rule 需要内部细节，而 macro projection 没有保留，那么 state closure 失败。

### Constraint Closure

内部约束必须已经被满足，或者被投影成外部可检查的 macro constraint。

```text
Internal schedule respects:
  resource exclusion
  capacity
  ordering
  representation constraints
  lifetime constraints
```

如果 macro rule 声称可执行，但内部需要外部重新验证 hidden resource constraints，那么 constraint closure 失败。

### Cost Closure

内部成本必须能被保守投影：

```text
cost_macro >= true internal cost lower bound
cost_macro <= known concrete implementation cost, if used as upper bound
```

对性能上界/下界而言，cost closure 是关键。若内部成本无法投影，macro rule 只能作为语义抽象，不能用于性能 envelope。

可以扩展两个辅助条件：

### Boundary Equivalence

Macro rule 的外部效果必须与 internal execution 在边界上等价：

```text
observe_boundary(execute_internal(S))
  == apply_macro_rule(observe_boundary(S))
```

### Refinement

Macro rule 应当可 refinement 到至少一个合法 internal implementation：

```text
macro rule is valid
  only if exists internal trajectory satisfying R_internal and C_internal
```

## Capability Envelope

Capability envelope 可以重新定义为：

```text
Capability(IS, B)
  = set of boundary-visible macro rules / trajectories
    achievable by internal states, rules, and constraints
    with cost summaries
```

因此：

```text
Capability Envelope
  = Rule Family + Constraint System
    inducing feasible boundary trajectories
```

性能上界/下界自然来自：

```text
min_cost(behavior, IS)
  = minimal cost of internal trajectory
    whose boundary effect realizes behavior
```

而 macro composition 允许我们不必每次从最底层 instruction 重新分析：

```text
micro system
  -> capability envelope
  -> macro rule family
  -> compose into larger system
```

## Recursive Chains

同一个形式可以覆盖两条递归链。

### Hardware / Fabric Chain

```text
PE
  -> Tile / Core
  -> Device
  -> Node
  -> Cluster
  -> Datacenter
```

每一层都投影：

```text
internal states -> macro states
internal rules -> macro rules
internal constraints -> macro constraints
```

### Program / Workload Chain

```text
Instruction
  -> Basic Block
  -> Kernel
  -> Layer
  -> Model
  -> Service
```

每一层也投影：

```text
micro execution rules -> macro behavior rules
micro cost/constraint -> macro cost/constraint
```

这两条链可以交叉：

```text
Kernel rule
  realized by
Device fabric rule family

Layer rule
  realized by
Multi-device composition

Service rule
  realized by
Cluster/datacenter composition
```

这就是 theory 需要支持的真正递归结构。

## Interface Constraints

组合两个系统时，最容易出问题的是 interface constraints。

```text
IS_A boundary output
  must match
IS_B boundary input
```

匹配不只是 value 类型，还包括：

```text
representation
location
lifetime
ownership
visibility
consistency
rate
capacity
backpressure
program/control protocol
```

例如：

```text
GPU kernel output in HBM
  -> NCCL AllReduce input
```

需要满足 HBM visibility、stream synchronization、NCCL buffer protocol、network credit、collective ordering。

在 DFU 中：

```text
LogicalRouteEdge
  -> TileRouteAction
  -> Vendor COPY/COPYT program
```

每一层都需要 interface constraints 保证 endpoint、visibility、sender/receiver ownership、vendor descriptor 能对应起来。

## OpenFabric Case

OpenFabric pipeline 可以被解释为连续 composition/refinement：

```text
Chip-level tensor program
  -> Processor logical system
  -> Tile / Fiber reaction system
  -> Vendor program reaction system
  -> Binary / SimICT execution system
```

每一步都应该说明：

```text
which states are preserved?
which rules are refined?
which constraints are introduced?
which constraints are discharged?
which costs are projected?
which boundary effects remain equivalent?
```

这比单纯 IR lowering 更强。它要求每层不仅产生下一层结构，还要保留可验证的 semantic/cost relation。

## How To Attack Composition

### Attack 1: GEMM Tile Macro Rule

把：

```text
load A/B
route A/B
visibility endpoints
MAC update
accumulator carry
store
```

投影为：

```text
GEMM Tile Update MacroRule
```

检查：

- State closure: intermediate route tokens 是否隐藏或暴露正确。
- Constraint closure: tensor core slot、SRAM port、route credit 是否被满足。
- Cost closure: movement/compute/program cost 是否保守投影。

### Attack 2: Fusion Macro Rule

比较：

```text
GEMM + Store + Load + ReLU
```

和：

```text
GEMM_ReLU_Fused
```

检查二者 boundary equivalence，并比较 macro constraints：

```text
unfused:
  more data states and movement

fused:
  larger program state
  tighter rule specialization
```

### Attack 3: Device Composition

组合两个 device：

```text
DeviceA + Link + DeviceB
```

检查 macro envelope 是否能从：

```text
Capability(DeviceA)
Capability(DeviceB)
Link constraints
```

计算出保守结果，而不需要重新打开所有 micro rules。

### Attack 4: Constraint Projection

从 micro constraints 推出 macro constraints：

```text
N tensor cores, each one op/cycle
  -> macro compute throughput envelope

limited boundary link
  -> macro communication bottleneck

limited program table
  -> macro staging/fusion bound
```

失败信号：

- macro constraints 只能手写，不能从 micro constraints 投影。

### Attack 5: Refinement Check

给定 macro rule，检查是否存在合法 internal trajectory。

如果 macro rule 无法 refinement，就只是虚假的抽象。

## Current Thesis

当前最重要的组合命题是：

> Information systems compose when internal state trajectories can be projected
> into boundary states, internal rule firings into macro rules, and internal
> constraints into macro constraints with sound state, constraint, and cost
> closure.

如果这个命题成立，那么：

```text
PE -> Device -> Cluster
Instruction -> Kernel -> Model
```

可以放进同一个形式体系。Capability envelope 也不再是额外概念，而是 information system 在某个 boundary 上可实现 macro trajectories 的可行域。

这一步是理论能不能从“固定系统的语义模型”变成“递归计算系统代数”的关键。
