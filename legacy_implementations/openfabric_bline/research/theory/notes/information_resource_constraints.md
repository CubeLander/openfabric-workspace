# Information Resource State and Constraints: Research Note

本文继续推进 `information_reaction_rules.md`，专门处理一个容易被忽略但非常关键的问题：

> Resource availability is information.

更准确地说，resource 不需要成为一套独立于信息场的特殊机制。Resource 只需要老老实实维护自己的 resource-state information；当条件满足时，reaction rule 触发，结果同样只是 information state 的变化。

前几份 note 已经把 data、program、control 都纳入 information state。Resource 一开始看起来像例外，因为它似乎是物理实体：

```text
Tensor Core
SRAM Port
Link
Queue Slot
Dispatch Slot
ROB Entry
MSHR
NCCL Channel
DFU Task Slot
```

但调度器和执行语义真正观察到的，不是物理实体本身，而是资源状态：

```text
TensorCoreAvailable
TensorCoreBusy
SRAMPortFree
SRAMPortOccupied
LinkCredit = 3
QueueSlotFree
DispatchSlotReserved
ROBEntryAllocated
```

这些状态本身就是信息。因此完整的场不只是：

```text
data state
program state
control state
```

而是：

```text
Information State:
  kind = data | program | control | resource | constraint | proof
```

## Resource State Is Not A Separate Ontology

Resource 是物理或逻辑能力；Resource State 是该能力在某一时间和边界下的可用性信息。

```text
I_resource = (
  kind = resource,
  resource_id,
  state,
  location,
  capacity_unit,
  lifetime,
  ownership,
  validity
)
```

例子：

```text
TensorCoreAvailable(pe_0, slot_0)
SRAMPortBusy(bank_1, read_port_0, until=t+4)
LinkCredit(edge=pe_0->pe_1, credit=2)
TaskSlotFree(dfu_task_id=3)
WarpSchedulerReady(sm_7)
MSHREntryAvailable(cpu_core_0)
```

这使 resource scheduling 可以直接写成 information transformation：

```text
Start compute:
  consume:
    TensorCoreAvailable
    A_tile
    B_tile
    ProgramRule(gemm_update)
  produce:
    TensorCoreBusy
    AccUpdateInFlight

Finish compute:
  consume:
    TensorCoreBusy
    AccUpdateInFlight
  produce:
    TensorCoreAvailable
    Acc'
```

Resource occupancy 就是 resource-state worldline 在时间轴上的分布：

```text
Occupancy(resource)
  = lifetime distribution of resource states
```

这与 tensor lifetime、visibility-token lifetime、program residency 是同一种东西的不同 kind。

所以模型里不需要一个额外的 `ResourceModel` 或一套外部资源调度语义。需要的只是普通 information states 和 ordinary reaction rules：

```text
resource state before
  + data/control/program states
  + enabled condition
  -> resource state after
     + output states
```

例如 tensor core 的占用可以写成：

```text
TensorCoreAvailable
  + A_tile
  + B_tile
  + Acc
  + ProgramRule(gemm_update)
  -> TensorCoreBusy(until=t+latency)
     + AccUpdateInFlight
```

完成也不是外部事件，而是更底层的时间/完成 rule：

```text
ClockTick / CompletionEvent
  + TensorCoreBusy(until <= now)
  + AccUpdateInFlight
  -> TensorCoreAvailable
     + Acc'
```

也就是说：

```text
计时、等待、释放资源
```

都可以继续降成更底层的信息反应变化。

## Resource Tokens As A Convenient Encoding

很多系统里的“资源”可以更自然地表示成 token 或 credit：

```text
DMA_Credit = 1
LinkCredit = N
QueueSlots = K
TensorCoreSlots = M
SRAMReadPorts = R
```

一次 rule firing 会消费 token，完成后释放 token：

```text
Start DMA:
  consume DMA_Credit
  produce DMA_InFlight

Finish DMA:
  consume DMA_InFlight
  produce DMA_Credit
```

这与 Petri Net 的 token 形式非常接近，但这里的目标不是引入一个通用并发表达语言，而是把资源状态纳入同一个 information field，用来解释性能 envelope。

这里的 token/credit 只是 resource-state information 的一种编码，不是新的基本对象。也可以用 counter state、interval state、reservation state、busy-until state 表达同一件事：

```text
LinkCredit = 3
QueueFreeSlots = 7
TensorCoreBusy(until=t+8)
SRAMPortReserved(interval=[t, t+2])
```

## Constraint System

继续往下推，Resource State 也不是第一性概念。真正的基础可能是约束：

```text
Constraint:
  which states may coexist,
  which rules may fire concurrently,
  which state transitions are legal,
  which capacities cannot be exceeded.
```

资源有限性最终体现为：

```text
某些 states 不能同时存在
某些 rules 不能同时 firing
某些 state lifetime 不能超过 capacity
某些 movement rate 不能超过 bandwidth
某些 program states 不能超过 table/cache/blob capacity
```

这些约束也不必作为独立“物件”存在。它们可以表现为：

```text
state invariants:
  at most one TensorCoreBusy per tensor core
  LinkCredit >= 0
  live SRAM bytes <= capacity

rule guards:
  fire only when QueueFreeSlots > 0
  fire only when ProgramRowsUsed + needed <= capacity

conservation laws:
  AvailableSlots + BusySlots = TotalSlots
  FreeCredits + InFlightTransfers = TotalCredits
```

因此约束是 rule system 对合法 state space 的限制，而不是另一个背景板。

因此更稳定的理论核心应是三元组：

```text
Information System = (
  Information States,
  Transformation Rules,
  Constraint System
)
```

而不是：

```text
Data / Program / Resource
```

Data、program、control、resource 都只是 information state 的角色或 kind。真正决定系统行为的是：

1. 哪些信息状态存在。
2. 哪些规则允许状态变化。
3. 哪些约束阻止或限制规则发生。

## Rule Family Constraints

`InformationReactionSystem` 太强了。它强到可以表达 CPU、GPU、DFU、runtime、OS、compiler、network protocol。这个表达能力本身不是贡献；如果不加限制，它会退化成万能建模语言，什么都能表达，什么都预测不了。

所以必须引入：

```text
RuleFamily(F)
```

它描述某个 fabric 天然支持哪些 rule family，以及这些 rule 的限制。

例如：

```text
CPU Rule Family:
  supports:
    fine-grained runtime branch
    pointer chasing
    out-of-order issue
    speculative execution
    cache/TLB state transitions
  constraints:
    limited ROB entries
    limited MSHR
    branch mispredict penalty
    memory-level parallelism bound

GPU Rule Family:
  supports:
    SIMD/SIMT lane-parallel object transformations
    coalesced memory movement
    warp-level predicate masks
  constraints:
    divergence serializes rule paths
    coalescing requires address structure
    occupancy bound by registers/shared memory/warps

DFU / Spatial Accelerator Rule Family:
  supports:
    staged tile compute
    explicit route/copy
    static loop/task/subtask program
  constraints:
    weak runtime rule selection
    limited vendor task/program capacity
    route visibility must be staged/proven
    resource slots are explicit bottlenecks

FPGA Rule Family:
  supports:
    fabric-time rule topology specialization
    custom pipelines
  constraints:
    area/timing/routing resource limits
    runtime flexibility costs additional control fabric
```

设备差异来自：

```text
which rule families exist,
which guards may depend on runtime state,
which control choices are staged,
which resource tokens constrain firing,
which constraints dominate the envelope.
```

这比说 CPU 是 latency optimized、GPU 是 throughput optimized 更接近原因。

## Scheduler as Resource-State Transformer

传统说法：

```text
Scheduler manages resources.
```

在这个模型里更准确：

```text
Scheduler transforms resource-state information.
```

调度器的输入不是物理资源，而是：

```text
ready tasks
dependency tokens
resource availability states
program states
priority / policy states
```

调度器 firing 后产生：

```text
reserved resource tokens
dispatch tokens
updated queues
updated ownership states
new enabled rules
```

因此 scheduling 本身也是 information transformation。它不是 execution 的外部控制器，而是 information reaction system 内部的一组 meta-rules。

## Performance Envelope With Resource States

只有 data/program/control state 还不足以预测性能 envelope。必须纳入 resource-state information，否则解释不了“理论 FLOPS 达不到”的常见原因。

典型 bottleneck 可以统一写成 resource-state constraint：

```text
CPU:
  ROBEntry, MSHREntry, LoadQueueSlot, StoreQueueSlot

GPU:
  WarpSchedulerSlot, RegisterFileCapacity, SharedMemoryCapacity,
  MemoryCoalescingGroup, ActiveWarpSlot

DFU:
  TaskSlot, SubtaskSlot, VendorProgramRow, RouteVisibilityEndpoint,
  SRAMPort, LinkCredit

Network / NCCL:
  ChannelCredit, QueueDepth, NICDoorbellSlot, PacketBuffer

FPGA:
  RoutingTrack, LUT/BRAM/DSP occupancy, pipeline register budget
```

这些资源状态通过普通 rule guard、state invariant、conservation law 决定：

```text
which rules can fire
how many can fire concurrently
how long a state must wait
which supposedly valid schedule is actually infeasible
```

因此 capability envelope 应从：

```text
value_rate / movement_rate / storage_capacity / program_capacity
```

扩展为：

```text
value_transform envelope
movement envelope
lifetime envelope
program-state envelope
control-selection envelope
resource-token envelope
constraint envelope
```

## Resource State vs Physical Resource

需要保持一个区分：

```text
Physical Resource:
  the actual hardware or logical capacity provider

Resource State:
  information about availability, occupancy, ownership, lifetime, credit, and validity
```

理论不是说物理资源“只是信息”。物理资源当然存在。理论说的是：

> 对编译器、调度器、性能模型而言，资源通过 resource-state information 进入计算场。

这可以避免把模型说成玄学。我们不是否认硬件物理性，而是在定义可计算的语义接口。

## 对 DFU 的直接含义

DFU 的 `InformationReactionSystem` 至少需要这些 resource states：

```text
SRAMRegionAvailable / SRAMRegionOccupied
SRAMReadPortAvailable / SRAMWritePortAvailable
RouteLinkCredit
TileVisibilityEndpointCapacity
TaskSlotAvailable
SubtaskSlotAvailable
VendorProgramRowCapacity
DispatchSlotAvailable
TensorCoreSlotAvailable
```

一个 GEMM tile update rule 不应只匹配：

```text
A_tile
B_tile
Accumulator
```

还要匹配：

```text
A visible at consumer
B visible at consumer
program row enabling update
tensor core slot
required SRAM/link/dispatch resource states
dependency token
```

否则 validator 会误以为 data state 足够，实际上 rule 并不能 fire。

Fusion 的 cost 也应包括 resource-state 变化：

```text
benefit:
  fewer intermediate data states
  shorter SRAM occupancy
  fewer movement rules

cost:
  larger program-state residency
  more constrained dispatch/resource slots
  longer specialized rule lifetime
  possible vendor table capacity failure
```

## 如何实验攻击

### Attack 1: Missing Resource Reactant

人为构造一个 schedule，让 data/control/program states 都存在，但缺少某个 resource state：

```text
TensorCoreAvailable missing
SRAMPortAvailable missing
TaskSlotAvailable missing
```

成功标准：

- reaction validator 判定 rule not enabled。

失败信号：

- 只要 tensor 和 program 存在，模型就允许 rule firing。

### Attack 2: Resource Bottleneck Trend

改变某个 resource token 数量：

```text
TaskSlot count
SRAM port count
RouteLinkCredit
VendorProgramRow capacity
```

成功标准：

- predicted envelope 随 token count 改变，且趋势与模拟/实测一致。

失败信号：

- 模型只受 FLOPS/bytes 影响，对 slot/credit/capacity 不敏感。

### Attack 3: Program-State Explosion

比较 fused/unrolled/staged variants：

```text
same boundary-visible computation,
different program-state and resource-state pressure.
```

成功标准：

- 模型能预测某些 fusion/unroll 在 vendor table、instruction cache、dispatch slot、task row 上失败。

### Attack 4: Cross-Device Rule Family

同一 workload：

```text
dense GEMM
pointer chasing
sparse gather
AllReduce
```

放到不同 RuleFamily：

```text
CPU
GPU
DFU
FPGA
```

成功标准：

- 性能 envelope 的差异来自 rule family constraints，而不是事后贴标签。

### Attack 5: Constraint Projection

把 resource-state model 退化成传统模型：

```text
only value transform + memory movement
```

应能得到类似 Roofline 的投影。再逐步加入：

```text
program-state
control-selection
resource-token
```

观察是否解释传统 Roofline 无法解释的瓶颈。

## 当前判断

Resource state 让 reaction-rule 理论真正开始有预测性能的可能。但它不应该变成独立机制；它只是普通 information state 的一类。真实系统达不到理论峰值，往往不是缺少 data，也不是缺少 program，而是当前 field state 缺少某些能让 rule enabled 的 resource-state information：

```text
credit
slot
port
queue entry
program row
dispatch token
visibility endpoint
```

更稳的理论核心因此是：

> A computing system is an information-state reaction system constrained by rule
> families, state invariants, and resource-state transitions.

这句话比“compute/storage/communication 统一”更接近可验证的性能模型。它明确告诉我们应该建模什么，也明确告诉我们怎么被打脸：如果某个瓶颈无法表示为 state、rule 或 constraint，那模型还不够细；如果什么都能表示但不能给出 envelope，那 rule family constraints 还不够硬。
