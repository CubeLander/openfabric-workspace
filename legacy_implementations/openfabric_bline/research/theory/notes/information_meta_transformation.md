# Information Meta-Transformation: Research Note

本文继续推进 `information_transformation_fabric.md` 里的理论草案，关注一个更细也更危险的问题：

> 信息不仅被变换；信息也能控制信息如何被变换。

这意味着 transformation path 不是预先固定的静态路径。Program、pointer、address、predicate、route selector、scheduler state、dispatch metadata 都是信息状态；它们会参与决定下一步发生哪个 transformation、在哪里发生、何时发生、以什么 representation 发生。

这可能是整个理论里最锋利的一层。

## 从信息变换到信息元变换

第一层理论说：

```text
Information State --Transformation--> Information State
```

更细一层需要承认：

```text
Information State --controls--> Transformation Selection
```

也就是说 transformation 本身可以被信息参数化：

```text
T_controlled:
  (I_data, I_control) -> I_output
```

其中 `I_control` 可以是：

- pointer / address
- stride / layout descriptor
- route table entry
- predicate mask
- loop counter
- instruction word
- program counter
- dispatch token
- dependency token
- scheduler queue state
- runtime profile state

这时，所谓“执行路径”不是外部观察者预先画好的线，而是由信息状态在 fabric 中一步步选择出来的轨迹。

## 信息指针移动也是信息变换

如果建模足够细，设备上的每一次 pointer movement 都是 transformation：

```text
pointer p at location x
  -> address generation
  -> memory location x'
  -> value visible at executor y
```

传统模型常把 pointer 当成“取数据的手段”。但在这个理论里，pointer 本身是一种信息状态：

```text
I_pointer = (
  kind = pointer,
  value = address / offset / symbolic reference,
  representation = virtual / physical / SRAM region offset / route endpoint,
  location = register / descriptor table / instruction field,
  lifetime = valid window,
  validity = bounds / alias / coherence state
)
```

Pointer transformation 包括：

```text
base + offset
virtual -> physical
logical tensor index -> SRAM region offset
tile coordinate -> route endpoint
program label -> instruction address
dependency id -> ready queue slot
```

所以“搬运数据”常常隐含了至少两条信息流：

```text
control/info path:
  pointer / descriptor / route selector / predicate

data path:
  tensor fragment / scalar / program payload
```

这两条路径会互相影响。Pointer 先移动或被计算，才决定 data 从哪里移动；data 的 value 又可能反过来决定后续 pointer 或 route。

## Transformation Path 不是预先决定的

静态图模型默认：

```text
node A -> node B -> node C
```

但真实设备里经常是：

```text
I_control(t)
  determines next transformation edge
```

例如：

```text
if predicate:
  route tile to PE_0
else:
  route tile to PE_1
```

或者：

```text
next_address = base + f(index, layout_descriptor)
value = load(next_address)
```

或者：

```text
ready_token arrives
scheduler selects runnable task
dispatch emits instruction bundle
```

因此更一般的执行模型应是：

```text
State S_t = {information states currently alive}

EnabledTransforms(S_t, F)
  = transformations whose data/control/program preconditions are satisfied

Step:
  choose tau in EnabledTransforms(S_t, F)
  S_{t+1} = apply(tau, S_t)
```

这里 `choose` 不一定是外部 oracle。它本身可以由 scheduler state、program counter、priority queue、hardware arbitration、data-dependent predicate 这些信息状态决定。

## 元变换

可以把 transformation 分成两层：

### Object-level Transformation

直接改变 data/program/metadata state：

```text
load
store
copy
mac
decode
dispatch
sync
```

### Meta-level Transformation

改变 transformation 的选择、参数、顺序或可达性：

```text
address generation
predicate evaluation
route selection
loop counter update
program counter update
scheduler enqueue/dequeue
dependency resolution
layout descriptor rewrite
code generation / specialization
```

但这不是严格二分。Meta-level transformation 自己也可以被更高层信息控制：

```text
profile state -> chooses schedule
schedule state -> chooses dispatch
dispatch token -> chooses instruction
instruction -> chooses data transformation
data value -> chooses next predicate
```

所以理论如果继续递归，会变成：

```text
Information controls transformation,
and transformation changes the information that controls future transformation.
```

这是一个闭环系统，而不是单向 dataflow graph。

## Program-Data Duality

此前的关键命题是：

> Program is also information state.

这一层可以更进一步：

> Program is information that controls transformation paths.

Data 和 program 的区别不是本体区别，而是角色区别：

```text
data:
  information primarily transformed as object

program/control:
  information primarily used to select or parameterize transformations
```

但同一段信息可以换角色。

例子：

- JIT code generation: data becomes program.
- Interpreter: program becomes data read by interpreter.
- Sparse matrix indices: metadata controls which values participate in compute。
- Attention mask: data-like tensor controls compute/communication path。
- DFU vendor task row: binary data controls hardware transformation sequence。
- Pointer chasing: loaded value becomes next pointer。

因此理论不应把 data/program/control 写死成不同种类资源，而应允许 `kind` 和 `role` 随 observation boundary 改变。

## 对设备能力建模的影响

如果 transformation path 由信息动态决定，那么 capability envelope 不能只包含：

```text
how fast can the device transform values?
how fast can it move bytes?
how many bytes can it store?
```

还必须包含：

```text
how fast can it transform control information?
how much program/control state can it keep resident?
how expensive is address generation / dispatch / route selection?
how much dynamic choice does the fabric support?
what choices must be compiled statically?
what choices can be data-dependent at runtime?
```

这解释了很多设备差异：

- CPU: rich dynamic control, expensive per-op overhead, flexible pointer/path selection。
- GPU: SIMD/SIMT control with masks, high data throughput, branch divergence cost。
- DFU/spatial accelerator: strong static schedule, limited dynamic control, route/program tables are precious。
- NIC/DPU: strong movement/control offload, limited value transform。
- FPGA: path can be compiled into fabric, but runtime flexibility may be costly。

所以“设备能力”还包括：

```text
Control Transformation Capability
```

它描述设备对 transformation path 的动态选择能力。

## 对 DFU 的直接含义

DFU 调度里需要区分三种信息路径：

```text
data path:
  A/B/C tiles, partial sums, scalar outputs

visibility path:
  route endpoints, copy tokens, dependency tokens, ready states

program/control path:
  vendor task rows, subtask roles, loop descriptors,
  route selectors, template fields, dispatch order
```

很多 bug 或性能瓶颈并不是 data path 错，而是 control path 或 visibility path 没有被正确建模：

- compute 看起来有输入，但 visibility token 没有先到。
- route action 在 sender 执行，但 receiver endpoint 才是被消费的信息状态。
- fused op 省了中间 tensor，但增加了 vendor task/program residency pressure。
- loop body 看起来重复执行，但 loop counter / carried state / dispatch token 才决定每次执行是否合法。

因此未来的 `InformationTransformationGraph` 不应只画 data values。它至少应有三类 edge：

```text
object_transform edge:
  changes value / representation / location / lifetime

control_transform edge:
  changes which transformation is enabled or selected

proof/dependency edge:
  constrains validity, visibility, ordering, ownership
```

## 静态调度与动态调度的统一

静态 schedule 不是没有 control path，而是 control information 被提前 materialize 成 program state：

```text
dynamic choice at runtime
  -> compile-time choice
  -> program table / instruction stream / fixed route
```

这本质上是 transformation path 的 staging：

```text
runtime control information
  converted into
compile-time program information
```

所以静态编译器做的事情可以描述为：

```text
meta-transformation:
  high-level flexible transformation space
  -> low-level fixed or partially fixed transformation path
```

这对 DFU 特别重要。当前 DFU-first 工作流大量依赖静态 vendor program、task rows、template fields。它不是“没有动态控制”，而是把很多控制信息提前固化进 program state。

## 如何攻击这个想法

### Attack 1: Pointer/Address Cost

问题：

```text
如果 pointer movement 也是 transformation，
模型是否能解释 indirect access / sparse access 的成本？
```

实验：

- dense GEMM vs sparse/indirect gather。
- 统计 data movement 与 pointer/metadata movement。
- 检查模型是否能预测 sparse 在某些密度下不如 dense。

失败信号：

- 模型只统计 value bytes，不统计 index/descriptor/control bytes。

### Attack 2: Static vs Dynamic Control

问题：

```text
静态 schedule 和动态 schedule 是否能表示为同一种 control information staging？
```

实验：

- 同一个 tiled computation，比较 runtime scheduler、compiled loop、fully unrolled vendor task table。
- 统计 program-state size、dispatch overhead、runtime flexibility。

成功信号：

- 模型能说明何时 unroll 有利，何时 program table 反噬。

### Attack 3: DFU Route Selection

问题：

```text
route path 是 data movement，还是 program/control information 的结果？
```

实验：

- 显式建模 route selector / logical route step / tile visibility endpoint。
- 验证 receiver-side endpoint 与 sender-side executable action 的区别。

成功信号：

- 能捕获 “sender 执行 copy，但 receiver 消费 visibility” 这种非直觉语义。

### Attack 4: Data-Dependent Transformation

问题：

```text
data value 能否成为后续 transformation path 的控制信息？
```

实验：

- predicate mask / conditional store / sparse routing / pointer chasing。
- 建模 data -> control role shift。

成功信号：

- 模型能表达 role shift，而不是强行把它拆成互不相关的 data graph 和 control graph。

### Attack 5: Program-State Bottleneck

问题：

```text
有些优化省 data movement，却增加 program/control state。
模型能否预测这种反噬？
```

实验：

- DFU fusion variants。
- 比较 intermediate tensor cost 与 vendor task/program capacity cost。

成功信号：

- 模型能预测 fusion 失败区间，而不是永远认为 fusion 更优。

## 可能的形式化方向

可以把执行系统写成一个受约束的 transition system：

```text
S_t:
  set of live information states

F:
  fabric with primitive transformations and capacity constraints

Enabled(S_t, F):
  set of transformations whose object/control/program preconditions hold

Policy(S_t):
  chooses or prioritizes enabled transformations

S_{t+1}:
  apply chosen transformation and update states
```

其中 `Policy` 也可以是信息状态：

```text
Policy = program + scheduler state + arbitration state + runtime data
```

于是整个系统不是：

```text
static graph execution
```

而是：

```text
information-state transition system with information-controlled transitions
```

如果要更接近编译器，可以定义 staged forms：

```text
Fully dynamic:
  path chosen at runtime from live state

Partially staged:
  some choices compiled into descriptors / loops / templates

Fully static:
  path mostly materialized as program state
```

编译就是把 dynamic choice space 压缩成 staged program state，同时支付 program-state cost，并减少 runtime decision cost。

## 当前判断

“信息元变换”让理论从性能 envelope 继续前进一步：

> Device capability is not only the ability to transform information, but also
> the ability to let information select, parameterize, stage, and rewrite future
> transformations.

这解释了为什么 program 不是免费的，也解释了为什么不同设备的本质差异不只是 FLOPS/bandwidth，而是对 dynamic transformation path 的支持程度不同。

对 OpenFabric 来说，这意味着后续 graph dump 不能只记录 dataflow。它还要记录：

- 谁控制了 transformation selection。
- 哪些选择已经被 compile-time program state 固化。
- 哪些选择仍在 runtime 由 predicate/token/scheduler 决定。
- control state 自身的 movement、lifetime、capacity 和 cost。

如果这个层次能建模清楚，理论会从“设备能力 envelope”升级成“设备如何用信息组织自己的执行能力”的模型。这很可能就是最有趣的地方。
