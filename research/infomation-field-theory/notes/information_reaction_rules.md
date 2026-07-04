# Information Reaction Rules: Research Note

本文继续推进 `information_meta_transformation.md` 的动态路径观点，尝试回答：

> 具体计算是怎么发生的？

一个有用的比喻是化学反应。整个 fabric 中存在许多 live information states。当局部或全局状态满足某个 transformation rule 的前置条件时，该 rule 被 enabled；如果调度/仲裁选择它，它就消耗、读取或保留一些信息状态，产生新的信息状态，并推进整个系统。

这使执行不再只是：

```text
static graph node A -> B -> C
```

而是：

```text
information field state
  + enabled transformation rules
  + scheduling / arbitration policy
  -> next information field state
```

## 基本模型

可以把一次执行写成状态转移系统：

```text
Field State S_t:
  all live information states in the fabric at time t

Rule Set R:
  transformation rules supplied by hardware, firmware, runtime, and compiled program

Enabled(S_t, R, F):
  rules whose preconditions are satisfied under fabric constraints

Policy(S_t, Enabled):
  chooses which enabled rules fire, or which subset may fire concurrently

Step:
  S_{t+1} = fire(Policy(S_t, Enabled(S_t, R, F)), S_t)
```

这比单纯 dataflow graph 更一般。Dataflow graph 可以看成 rule set 很固定、路径大多静态、enabled condition 主要是 input readiness 的特例。

## Transformation Rule

一个 rule 至少包含：

```text
Rule rho = (
  name,
  match,
  guard,
  consume,
  read,
  produce,
  update,
  resource,
  cost,
  boundary_effect
)
```

其中：

- `match`: 需要哪些 kind/role/location/representation 的信息状态。
- `guard`: 值、predicate、token、ownership、validity、capacity 等条件。
- `consume`: 被消耗或失效的信息状态。
- `read`: 只读参与的信息状态，例如 program row、descriptor、route table。
- `produce`: 新生成的信息状态。
- `update`: 原地更新的状态，例如 program counter、loop counter、ready queue。
- `resource`: 占用哪些 fabric primitive，例如 ALU、DMA、link、decoder、SRAM port。
- `cost`: latency、energy、bandwidth occupancy、program-state occupancy、sync cost。
- `boundary_effect`: 对外部观察边界可见的 transformation 摘要。

例子：

```text
MAC rule:
  match:
    A_tile visible at PE_i
    B_tile visible at PE_i
    Acc state at PE_i
    instruction/program state enabling gemm_update
  guard:
    dependency token ready
    tensor representation supported by PE_i
  read:
    program state
    A_tile
    B_tile
  update:
    Acc state
  resource:
    tensor core slot
  cost:
    compute cycles + register/SRAM port occupancy
```

```text
COPY route rule:
  match:
    source tile visible at PE_i
    route selector / copy instruction
    destination endpoint capacity
  guard:
    link available
  read:
    route program state
    source tile
  produce:
    visibility endpoint at PE_j
  resource:
    interconnect edge PE_i -> PE_j
```

```text
Pointer-chase load rule:
  match:
    pointer value p at CPU register
    load instruction
  guard:
    p is valid / translated / permitted
  read:
    pointer p
    memory state at address p
  produce:
    loaded value v
  update:
    maybe cache state, TLB state, program counter
```

## 反应式执行

在这个模型里，计算不是由外部图强行推进，而是由信息场状态触发 rule：

```text
if all reactants are present and guards hold:
  reaction may fire
```

这里的 reactants 不只是 data：

```text
data reactants:
  tensor tile, scalar, partial sum

control reactants:
  predicate, pointer, route selector, dependency token

program reactants:
  instruction, loop descriptor, vendor task row, template field

resource reactants:
  available port, link credit, queue slot, buffer capacity
```

这让“程序不是免费的”变成非常具体的规则：program state 是许多 rule 的必要 reactant。没有 program reactant，硬件 primitive 不能自动发生。

## 硬件 Rule 与软件 Rule

最底层 rule 由硬件提供：

```text
ISA instruction semantics
clock / pipeline step
memory load/store protocol
cache coherence transition
DMA transfer rule
network packet forwarding rule
tensor core operation
```

这些是 fabric 的 primitive reaction rules。软件做的事情，是组合、约束、stage 或生成更高层 rule：

```text
for loop:
  repeated application of a body rule family

kernel:
  rule set instantiated over many indices

compiler schedule:
  partial order and resource plan over rule firings

runtime:
  dynamic policy for selecting enabled rules

vendor program:
  staged control information that exposes a restricted rule set to DFU hardware
```

所以软件不是“漂浮在硬件上方的描述”。软件本身提供 reaction rule 的抽象：

```text
high-level software rule
  lowered into
lower-level rule composition
  eventually grounded in
hardware primitive rules
```

## Rule 的递归组合

一个 macro rule 可以由许多 micro rules 组合而成：

```text
rho_macro = compose_rules(rho_1, rho_2, ..., constraints)
```

例如：

```text
GEMM tile update macro rule:
  route A fragment
  route B fragment
  wait for visibility endpoints
  update accumulator
```

从外部边界看，它是：

```text
(A_tile, B_tile, Acc) -> Acc'
```

从内部看，它包含 route、visibility、compute、program-state read、dependency update 等 micro reactions。

一个 rule 能被摘要成 macro rule，需要满足：

```text
closure:
  internal intermediate states do not escape boundary,
  or their boundary effects are explicitly summarized

cost summary:
  internal resource/cost can be conservatively summarized

validity:
  macro preconditions imply all required internal preconditions,
  possibly under a chosen schedule/policy
```

这和 fabric composition 是同构的：

```text
compose fabric -> macro fabric
compose rules  -> macro rule
```

真正有理论价值的问题是：

```text
macro rule capability / cost
能不能从 micro rules + topology + policy 计算出来？
```

## Time / Clock 的角色

时钟不是外部背景，也可以建模为 rule firing 的节拍约束：

```text
clock tick:
  enables pipeline stage transition
  advances lifetime
  releases or consumes resource tokens
```

异步系统则不是没有时间，而是 rule firing 由 handshake、credit、event token 决定。

因此：

```text
synchronous device:
  clock provides global or local firing cadence

asynchronous device:
  token / handshake state provides firing condition
```

两者都可以写成 reaction rules；区别在于 enabled/firing policy 的形式。

## Control Materialization as Rule Staging

上一份 note 提到：

```text
CPU:
  runtime materialization

GPU:
  kernel-launch-time materialization

DFU:
  compile-time materialization

FPGA:
  fabric-time materialization
```

在 rule 视角下，这可以写得更精确：

```text
dynamic control:
  rule guards and next-rule selection depend on runtime information states

staged control:
  many guards / selections are precomputed and materialized as program states

fabric control:
  rule topology itself is encoded into hardware structure
```

编译器做的是：

```text
general rule space
  -> staged specialized rule set
  -> lower runtime choice cost
  -> higher program-state / specialization cost
```

这解释了 fusion 的两面性：

```text
benefit:
  fewer intermediate object states
  fewer runtime rule firings
  shorter data lifetime

cost:
  larger specialized rule
  more program-state residency
  less dynamic flexibility
  possible vendor table / instruction cache / dispatch pressure
```

## 设备差异的新坐标

传统坐标：

```text
CPU = latency optimized / control-oriented
GPU = throughput optimized
TPU/DFU = accelerator
FPGA = reconfigurable hardware
```

Rule 视角下可以改写为：

```text
CPU:
  high runtime rule-selection capability
  cheap data -> control -> data role switching
  supports pointer chasing and irregular paths

GPU:
  high object-rule throughput
  moderate staged/runtime control
  efficient when many lanes share rule shape
  expensive when each lane selects different path

TPU / DFU:
  very high staged object-rule throughput
  weak runtime rule-selection capability
  strong compile-time control materialization

FPGA:
  rule topology can be materialized into fabric
  excellent fixed-path specialization
  runtime flexibility costs area/timing/control complexity
```

这解释的是原因，而不只是现象。设备差异来自：

```text
what rule families exist,
which guards may depend on runtime information,
how expensive rule selection is,
where control information is materialized,
how much rule specialization the fabric can hold.
```

## 对 OpenFabric / DFU 的含义

OpenFabric 的 lowering pipeline 可以被解释为 rule staging：

```text
Chip-level tensor program:
  target transformation family

Logical plan:
  processor-level rule decomposition

Tile / Fiber:
  tile-local rule instances and dependencies

Schedule:
  rule firing constraints and partial order

Vendor program:
  staged control information that lets DFU hardware fire primitive rules
```

因此未来的 `InformationTransformationGraph` 可以进一步演化为：

```text
InformationReactionSystem:
  states
  rules
  dependencies
  enabled conditions
  resource tokens
  cost summaries
  boundary effects
```

对 DFU 来说，最重要的是显式区分：

```text
object states:
  tensor fragments, accumulators, stores

control states:
  route selectors, dependency tokens, loop counters

program states:
  task rows, subtask descriptors, template fields, vendor blobs

resource states:
  SRAM region occupancy, link credits, task slots, dispatch slots
```

很多调度 bug 可以转写成：

```text
某个 rule 被认为 enabled，
但其实缺少 object/control/program/resource reactant。
```

很多性能问题可以转写成：

```text
某类 reactant 或 resource token 成为 bottleneck。
```

## 如何实验攻击

### Attack 1: Rule Completeness

问题：

```text
一个 DFU schedule 中每个 vendor-visible action
是否都能找到对应 rule？
```

成功标准：

- route、compute、store、loop、dependency、program row 都能被 rule 表达。
- 没有“凭空发生”的 transformation。

失败信号：

- 需要依赖隐式外部魔法，例如“scheduler naturally does this”。

### Attack 2: Enabled Condition

问题：

```text
rule enabled 条件是否能捕获 visibility/lifetime/dependency bug？
```

实验：

- 人为删除 route endpoint、dependency token 或 program descriptor。
- 检查 validator 是否能阻止 compute/store rule firing。

### Attack 3: Staging Tradeoff

问题：

```text
compile-time staged control 是否降低 runtime firing cost，
同时增加 program-state cost？
```

实验：

- 比较 looped、unrolled、fused、unfused vendor program。
- 统计 rule firing count、program-state size、dispatch slots、data lifetime。

### Attack 4: Irregular Workload

问题：

```text
模型是否能解释 CPU/GPU/DFU 对 pointer chasing、sparse routing、dense GEMM 的差异？
```

成功标准：

- Dense GEMM 主要受 object-rule throughput 与 movement 约束。
- Pointer chasing 主要受 runtime rule-selection 与 data-control role switching 约束。
- DFU/GPU 在 irregular dynamic path 上 envelope 明显塌陷。

### Attack 5: Macro Rule Composition

问题：

```text
能否把多个 micro rules 摘要成 macro rule，
并保守计算 boundary effect 与 cost？
```

成功标准：

- GEMM tile update macro rule 能从 route + visibility + compute micro rules 得到。
- Fusion macro rule 能解释中间 state 删除与 program-state 增长。

## 当前判断

Information reaction rules 把整个理论推进到更可执行的形式：

> Computation happens when information-state configurations enable transformation rules; programs, pointers, predicates, schedules, and hardware resources are themselves information reactants that select, parameterize, or permit those rules to fire.

这层模型很适合接住两个关键问题：

1. 设备能力为什么不同？
   因为设备提供的 rule families、runtime rule-selection capability、control materialization stage、resource token constraints 不同。

2. 编译器到底在做什么？
   编译器把高层 transformation space 改写成低层 staged reaction rule system，把运行时选择成本转移为 program-state 成本。

如果这套 rule 语义能落到 DFU Fusion 上，OpenFabric 就不仅是在生成 vendor binary，而是在构造一个可验证、可组合、可估价的 reaction system。这比单纯 IR lowering 更接近理论核心。
