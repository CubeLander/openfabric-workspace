# Information System Core: Synthesis Note

本文把前几份 note 收束成一个更稳定的核心形式。

前面的推进路径大致是：

```text
Information State
  -> Information Transformation
  -> Transformation Fabric
  -> Meta-Transformation / Control Information
  -> Reaction Rules
  -> Resource State and Constraints
```

现在可以进一步压缩成：

```text
Computing System
  =
  Information States
  + Reaction Rules
  + Constraint System
  + Rule Families
```

其中：

- `Information States` 描述“有什么”。
- `Reaction Rules` 描述“能发生什么”。
- `Constraint System` 描述“什么不能发生”。
- `Rule Families` 描述“这个 fabric 天生擅长发生什么”。

这比最开始的 compute/storage/communication 统一更深一层。它不再从资源类别出发，而是从一个计算系统允许哪些状态存在、哪些变化发生、哪些变化被禁止开始建模。

## 为什么要收束

前几份 note 有一个潜在风险：Information State 的种类不断膨胀。

```text
data
program
control
resource
proof
metadata
schedule
...
```

如果每发现一种东西都加一个新本体，理论会越来越胖。更好的收束是：

```text
data/program/control/resource/proof
```

都只是 `Information State` 的不同 kind 或 role。

真正决定系统行为的不是这些标签本身，而是：

```text
States:
  当前场里有哪些信息状态。

Rules:
  哪些状态组合满足条件后可以发生变化。

Constraints:
  哪些状态组合非法，哪些 rule 不能同时发生，哪些容量不能越界。

RuleFamilies:
  某类 fabric 原生支持哪些 rule、哪些 guard、哪些 staging 方式。
```

## Field State

一个计算系统在时刻 `t` 的状态可以写成：

```text
S(t) = set of live information states
```

这些状态可以包括：

```text
TensorTile(A, location=SRAM0, lifetime=[t0,t3])
VisibilityToken(A_tile visible at PE_7)
VendorTaskRow(row=3, resident=true)
DispatchSlotFree(slot=2)
TensorCoreBusy(pe=7, until=t+8)
RouteCredit(edge=PE_1->PE_7, credit=2)
LoopCounter(k=5)
DependencyToken(dep_17 ready)
```

这些共同构成 field state。系统演化不是“节点执行”，而是：

```text
S(t)
  -> enabled reaction rules fire
  -> S(t+1)
```

因此真正的对象不是某个单独 tensor，也不是某个外部 scheduler，而是整个场中的状态分布。

## State Worldline

许多传统概念可以统一成 state worldline：

```text
Tensor lifetime
Program residency
Visibility lifetime
Tensor core occupancy
Queue slot occupancy
Link credit lifetime
```

它们都可以写成：

```text
state exists at location x over interval [t0, t1]
```

于是：

```text
Occupancy(resource)
  = lifetime distribution of resource states
```

不再是一个特殊定义。它和 tensor lifetime、program row residency、visibility token lifetime 是同一种形式。

这也是为什么 resource 不需要单独建模。Resource 以 resource-state information 的形式进入场；计时、占用、释放都只是更底层 reaction rules。

## Reaction Rules

计算发生的基本形式是：

```text
reactants + guards + available state
  -> products + updated state
```

例子：

```text
GEMMUpdate:
  match:
    A_tile visible at PE_i
    B_tile visible at PE_i
    Acc state at PE_i
    ProgramRule(gemm_update)
    TensorCoreAvailable(PE_i)
  guard:
    dependency token ready
    representation supported
  produce:
    TensorCoreBusy(until=t+latency)
    AccUpdateInFlight
```

完成同样是 rule：

```text
GEMMComplete:
  match:
    TensorCoreBusy(until <= now)
    AccUpdateInFlight
  produce:
    TensorCoreAvailable
    Acc'
```

这消灭了外部魔法。没有任何东西“自然发生”；如果发生了，它应当能被解释成某个 rule firing。

## Scheduler Is Inside The Field

传统上 scheduler 常被当成外部控制器：

```text
CPU scheduler
GPU warp scheduler
NCCL scheduler
DFU scheduler
```

但在这个模型里，scheduler 也是场内居民。它消费状态，产生状态。

```text
SchedulerRule:
  match:
    ReadyTask
    ResourceAvailable
    PriorityState
    OwnershipState
  produce:
    DispatchToken
    ReservedSlot
    UpdatedQueueState
```

因此：

```text
Scheduler manages resources
```

可以改写为：

```text
Scheduler transforms resource-state and control-state information.
```

这很重要，因为它消除了一个常见的外部假设：调度器不再是理论之外的管理员，而是 reaction system 内部的一组 meta-rules。

## Constraint System

Constraint 也不应被理解为场外管理员。它限制合法状态空间和 rule firing。

约束可以有几种形式：

```text
state invariant:
  AvailableSlots + BusySlots = TotalSlots
  live SRAM bytes <= SRAM capacity

rule guard:
  fire only if LinkCredit > 0
  fire only if dependency token ready

mutual exclusion:
  two rules cannot consume the same TensorCoreAvailable state

rate constraint:
  at most N route transfers per time window

representation constraint:
  this tensor core only supports specific dtype/layout combinations
```

所以 constraint 不是一个新 kind 的“物体”，而是 rule system 对合法 state trajectory 的限制。

## Rule Families

`InformationReactionSystem` 表达能力太强。它可以表示 CPU、GPU、DFU、FPGA、OS、runtime、compiler、network protocol。这个强表达力本身不是贡献；没有限制就无法预测。

所以需要：

```text
RuleFamily(F)
```

Rule family 描述一个 fabric 原生允许哪些反应方式，以及哪些反应方式很贵、很弱、或者根本不支持。

例如：

```text
CPU:
  strong runtime rule selection
  cheap data -> control -> data role switching
  supports branch, pointer chasing, speculation, OoO
  constrained by ROB, MSHR, cache/TLB, branch predictor

GPU:
  strong bulk object-rule throughput
  moderate staged/runtime control
  efficient when lanes share rule shape
  constrained by divergence, coalescing, occupancy

DFU / spatial accelerator:
  strong staged rule execution
  weak runtime rule selection
  explicit visibility and route staging
  constrained by vendor program capacity, task slots, route endpoints

FPGA:
  rule topology materialized into fabric
  strong fixed-path specialization
  runtime flexibility costs area/timing/control complexity
```

这比“CPU latency optimized / GPU throughput optimized”更接近原因。设备差异来自：

```text
which rule families are available,
which guards can depend on runtime state,
where control information is materialized,
which state trajectories are cheap or expensive,
which constraints dominate the envelope.
```

Rule family 有点像系统领域里的“允许变换族”。它给 reaction system 加上硬边界，防止模型退化成万能表达器。

## Computing Device Capability

在这个核心模型下，设备能力不是：

```text
FLOPS + bandwidth + cache size
```

而是：

```text
Capability(F)
  = achievable state trajectories under
    RuleFamily(F) and ConstraintSystem(F)
```

更具体地：

```text
For target behavior B:
  min_cost(B, F)
    = minimal cost trajectory from initial state to boundary-equivalent final state
      using rules allowed by RuleFamily(F)
      subject to constraints of F
```

这自然包含：

- value transformation cost
- movement cost
- lifetime/storage occupancy
- program-state residency
- control-selection cost
- resource-state occupancy
- synchronization and dependency cost

## Compiler As Rule Staging Engine

编译器不只是 code generator，而是 rule staging engine。

```text
high-level dynamic rule space
  -> staged specialized rule system
  -> lower runtime selection cost
  -> higher program-state / specialization cost
```

不同设备对应不同 materialization stage：

```text
CPU:
  many rule choices materialized at runtime

GPU:
  many rule choices materialized at kernel-launch / SIMT structure

DFU:
  many rule choices materialized at compile-time vendor program

FPGA:
  many rule choices materialized at fabric-configuration time
```

Fusion 也可以这样理解：

```text
benefit:
  removes intermediate states
  shortens state worldlines
  reduces runtime rule firings

cost:
  creates larger staged rules
  increases program-state residency
  may tighten constraints
  may reduce dynamic flexibility
```

## OpenFabric Interpretation

OpenFabric 当前 pipeline 可以解释成：

```text
Chip-level tensor program:
  target state trajectory family

Logical plan:
  processor-level rule decomposition

Tile / Fiber:
  tile-local rule instances and dependencies

Schedule:
  constraints over rule firing order and resource-state occupancy

Vendor program:
  staged control information enabling hardware primitive rules
```

长期看，OpenFabric 的理论内核可能不是 `TensorProgram`，而是：

```text
InformationReactionSystem
```

其中 tensor、route、loop、vendor program、dependency、resource state 都只是不同 kind 的 field state。

## How To Attack This Core

### Attack 1: No External Magic

任意一次 lowering 或 execution step，都必须能解释成：

```text
state + rule + constraint -> new state
```

如果需要说“硬件自然会处理”或“scheduler 自然会安排”，说明模型漏了 state 或 rule。

### Attack 2: Rule Family Predictiveness

同一 workload 放到不同 `RuleFamily(F)` 下，必须推出不同 envelope：

```text
dense GEMM:
  GPU/DFU strong

pointer chasing:
  CPU strong, GPU/DFU weak

sparse gather:
  depends on metadata/control state cost

fusion:
  depends on program-state and constraint pressure
```

如果不同设备只是在事后贴标签，RuleFamily 不够硬。

### Attack 3: Constraint Sensitivity

改变某个约束：

```text
task slots
route credits
program rows
SRAM ports
queue depth
ROB/MSHR
```

模型应该预测 envelope 改变。如果不敏感，说明 resource-state worldline 没有真正进入模型。

### Attack 4: State Worldline Accounting

统计并比较：

```text
tensor lifetime
visibility lifetime
program residency
resource occupancy
dependency token lifetime
```

如果这些无法用统一 accounting 表示，说明 state 模型还没有收束。

### Attack 5: Staging Tradeoff

比较：

```text
dynamic schedule
looped schedule
unrolled schedule
fused schedule
fabric-specialized schedule
```

模型应解释 runtime control cost 与 staged program-state cost 的互换。

## Current Thesis

当前最稳定的理论表述可以是：

> A computing system is an information-state reaction system whose behavior is
> determined by live field states, enabled reaction rules, state-trajectory
> constraints, and fabric-specific rule families.

这句话把几条线合在一起：

- Data、program、control、resource 都是 state kind。
- Program、scheduler、resource availability 都在场内，不是外部魔法。
- Occupancy、lifetime、residency 都是 state worldline 的不同投影。
- 设备差异来自 rule family 和 constraint system。
- 性能 envelope 来自可达 state trajectory 的成本边界。

这已经不是“计算、存储、通信统一”的浅层说法，而是一个关于计算系统如何演化的语义框架。
