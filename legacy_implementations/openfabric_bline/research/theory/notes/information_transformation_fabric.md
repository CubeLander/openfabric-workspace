# Information Transformation Fabric: Research Memo

本文把 `../archive/discussions.md` 里的想法收束成一个可研究、可实验攻击的理论草案。
暂时不要把它称为最终理论；更稳妥的名字是：

```text
Information-state transformation calculus for recursive compute fabrics
```

内部可以继续叫“信息场论”或“Information Relativity”，但对外表达应强调：

> Computing devices are recursive information-transformation fabrics, and their
> performance bounds are capability envelopes induced by primitive transformations,
> topology, capacity, and program-state constraints.

## 核心直觉

传统系统里常把设备能力拆成 compute、storage、communication 三类资源：

```text
FLOPS
memory capacity / bandwidth
network bandwidth / latency
```

这个拆法工程上有用，但不是第一性概念。更基础的对象是信息状态，以及信息状态在受约束 fabric 中如何变化。

Compute、storage、communication 不是三类绝对设备能力，而是 information transformation 在不同观察边界下的主导模式：

```text
compute       ~= value-dominant transformation
storage       ~= time/lifetime-dominant transformation
communication ~= space/location-dominant transformation
```

现实操作几乎都是混合态。一次 GEMM 不是纯 compute；它依赖 tile layout、SRAM lifetime、operand visibility、instruction stream、loop dispatch 和同步。一次 communication 也不是纯 movement；信道需要 encode、buffer、transmit、decode。一次 storage 也不是纯 retention；cache coherence、refresh、ECC、layout transform 都会参与。

因此理论的目标不是证明“计算、存储、通信是一回事”，而是证明：

> compute / storage / communication are derived views of constrained information-state transformations.

## 基本对象

### Information State

最小状态可以写成：

```text
I = (value, location, time)
```

面向真实计算设备，需要扩展成：

```text
I = (
  kind,
  value,
  representation,
  location,
  lifetime,
  validity,
  ownership
)
```

其中：

- `kind`: data、program、metadata、schedule、token、buffer 等信息类别。
- `value`: 语义值，例如 tensor tile、partial sum、instruction payload。
- `representation`: dtype、layout、encoding、sparsity、vendor binary format。
- `location`: register、SRAM region、PE、DFU mesh node、HBM、NIC、host memory。
- `lifetime`: 信息需要存在的时间窗口，或者 storage occupancy。
- `validity`: 可见性、一致性、freshness、fidelity。
- `ownership`: 哪个 executor / stream / processor 有权消费或更新该信息。

最关键的修正是：

> Program is also information state.

指令流、vendor task row、loop descriptor、ABI table、dispatch metadata 都不是免费的外部描述。它们占用空间、需要被搬运、被 decode、被保持、被同步，也可能成为性能上界的一部分。

### Transformation

Transformation 是信息状态之间的关系：

```text
T: I^n -> I^m
```

典型投影包括：

```text
Compute:
  (v, r, x, t) -> (f(v), r', x, t + dt)

Storage:
  (v, r, x, t0) -> (v, r, x, t1)

Communication:
  (v, r, x0, t) -> (v, r', x1, t + dt)

Program lowering:
  high-level program state -> low-level program state

Fusion:
  remove or shorten intermediate information states,
  while possibly increasing program/dispatch/representation cost
```

### Fabric

一个计算设备不是一组标量指标，而是一个 fabric：

```text
F = (Nodes, Edges, PrimitiveOps, Capacity, Cost, Boundary)
```

其中：

- `Nodes`: 能保存或变换信息的地点，例如 PE、SRAM bank、DMA endpoint、decoder。
- `Edges`: 信息可移动路径，例如 mesh link、bus、DMA route、network link。
- `PrimitiveOps`: fabric 支持的基本 transformation，例如 MAC、copy、load、store、decode、dispatch、sync。
- `Capacity`: compute issue rate、buffer capacity、program table size、bandwidth、lifetime capacity、concurrency slots。
- `Cost`: latency、energy、bandwidth occupancy、contention、program overhead、sync cost。
- `Boundary`: 该 fabric 对外可见的输入输出端口和状态摘要。

### Capability Envelope

设备能力不应压成一个点，而应是可行域：

```text
Capability(F)
  = set of boundary-visible transformations achievable by F
    under capacity and cost constraints
```

对目标 transformation `T`，调度问题是：

```text
min_cost(T, F)
  = min Cost(plan)
    subject to plan realizes T using primitives of F
```

这不是预测真实 latency 的万能公式，而是在给定抽象粒度下给出性能边界：

```text
lower bound: any valid plan must pay at least this much cost
upper bound: this concrete schedule realizes T with this cost
gap: model precision or scheduler quality issue
```

## 递归组合

理论硬核不在 value/space/time 三轴，而在 compose 算子：

```text
compose(F1, F2, ..., topology) -> F_macro
```

如果 `F_macro` 的 capability envelope 只能重新测量，递归只是命名结构；如果它能由子 fabric envelope 加拓扑约束计算或近似推出，这个模型才有理论牙齿。

一个最小 compose 模型可以先只包含：

```text
node:
  compute_rate
  storage_capacity
  storage_bandwidth
  program_capacity
  dispatch_rate

edge:
  bandwidth
  latency

constraints:
  cut bandwidth
  buffer lifetime
  synchronization order
  program residency
```

组合后的能力不是线性相加。两个 PE 的 compute rate 可以相加，但如果边界带宽不足、program table 不够、或者同步成本过高，某个目标 transformation 的有效 envelope 会塌陷。

## 对 DFU 的直接含义

OpenFabric 当前不应该把这层理论塞进 `ChipEnv` 或 op-time mutation。它应成为 IR / schedule / lowering / vendor program 之间的共同语义层：

```text
Chip-level tensor program
  -> logical / tile / fiber program
  -> information transformation graph
  -> proof / validation / cost envelope
  -> vendor program lowering
```

DFU Fusion 是最好的攻击样例，因为它足够脏：

```text
GEMM
+ Route
+ DMA
+ SRAM lifetime
+ Sync
+ Loop descriptor
+ Vendor task row
+ Dispatch / decode
+ Optional post-op
```

Fusion 的收益不应只说成“少写一次中间 tensor”。更精确地说，它改变了 information state graph：

- 删除或缩短中间 value state。
- 缩短或改变 SRAM lifetime。
- 减少某些 route/store/load transformation。
- 增加或改变 program-state transformation。
- 可能把成本从 data movement 转移到 program residency、dispatch、decode 或 vendor binary capacity。

如果模型能解释并量化这些 tradeoff，它就比普通 IR 注释更强。

## 如何实验攻击这个理论

### Attack 1: DFU GEMM Baseline

目标：

```text
C = A @ B
```

实验：

1. 从现有 tile/fiber program dump information transformation graph。
2. 统计 value transformation、movement、lifetime occupancy、program-state cost。
3. 对比已知 schedule 的 SimICT/vendor result。
4. 检查模型能否给出 tight enough upper bound。

成功标准：

- graph 能复原 visibility、dependency、lifetime。
- concrete schedule cost 能解释主要瓶颈。
- bound 与实际趋势一致，例如 tile size、K blocks、route pattern 改变时趋势正确。

失败标准：

- 只能事后描述，不能预测趋势。
- 关键瓶颈来自模型没有表达的状态，例如 hidden dispatch、vendor table capacity。

### Attack 2: DFU Fusion

目标：

```text
GEMM
GEMM + ReLU
GEMM + store/load + ReLU
```

实验：

1. 建模 fused 与 unfused 的 transformation graph。
2. 证明二者在 boundary-visible value transformation 上等价。
3. 比较中间 state 数量、lifetime、movement、program overhead。
4. 找到 fusion 何时有利，何时被 program/dispatch/vendor capacity 反噬。

成功标准：

- 模型不只说 fusion 好，而能预测 fusion 的失败区间。
- 能解释“省 data cost，但增加 program-state cost”的情况。

失败标准：

- 所有 fusion 都被模型判成更优。
- 无法表达 instruction/template/dispatch 成本。

### Attack 3: GPU Roofline Cross-check

目标：

把传统 Roofline 作为本理论的低维投影。

实验：

1. 只保留 value rate 与 memory movement。
2. 推出类似 operational intensity 的约束。
3. 再加入 representation/lifetime/program-state，看是否解释 Roofline 无法表达的优化，例如 fusion、recompute、persistent kernels。

成功标准：

- 退化模型能覆盖 Roofline 的核心结论。
- 扩展模型能解释至少一个 Roofline 描述不充分的 case。

失败标准：

- 退化不到已有模型。
- 扩展后只增加术语，不增加预测力。

### Attack 4: Cluster / AllReduce Boundary Shift

目标：

验证“操作角色由观察边界诱导”。

实验：

1. 从单 device 边界看 AllReduce 是 communication-heavy。
2. 从 cluster boundary 看 AllReduce 是 distributed reduction transformation。
3. 比较 ring、tree、hierarchical route 的 capability envelope。

成功标准：

- 同一 transformation 在不同 boundary 下得到不同 dominant mode。
- 模型能解释 hierarchical schedule 为什么优于 naive flat schedule。

失败标准：

- boundary shift 只是换名，没有带来不同约束或预测。

### Attack 5: Compose Operator

目标：

证明最小 compose 算子可计算。

实验：

1. 定义两个子 fabric 的 envelope。
2. 加一条 bandwidth/latency 有限的 boundary edge。
3. 推出 macro fabric 对 GEMM / reduce / copy 的 envelope。
4. 与直接全局求解或模拟结果对比。

成功标准：

- macro envelope 可由 child envelope + topology constraint 计算出保守 bound。
- 能展示非线性塌陷，例如 compute 相加但 boundary cut 限制整体 transformation rate。

失败标准：

- compose 后必须重新完整建模，无法复用子 envelope。

## 理论贡献边界

可以主张的贡献：

1. **统一建模对象**  
   把 data、program、metadata、schedule 都作为 information state，避免把 program 当作免费外部描述。

2. **设备能力的 envelope 视角**  
   把 FLOPS、bandwidth、capacity、dispatch、program table 都看成 capability envelope 的投影，而不是彼此独立的标量。

3. **调度即 transformation factorization**  
   schedule、placement、tiling、fusion、buffering、collective、recompute 都是把目标 transformation 分解到 fabric primitive 上的不同方式。

4. **递归 fabric composition**  
   子 fabric 可以被摘要成 macro node，但摘要必须保留 boundary-visible capability envelope，而不是只保留峰值指标。

5. **性能边界而非真实时间预言**  
   理论目标是给出 cost lower bound、schedule upper bound 和解释 gap 的结构，不是替代 simulator 或 profiler。

暂时不应主张的贡献：

- 不要声称可以预测任意设备的真实性能。
- 不要声称 value/space/time 是严格正交物理轴。
- 不要声称这是全新数学基础；它与 BSP、Roofline、red-blue pebble game、resource theory、communication-avoiding algorithms 有明显亲缘关系。
- 不要把所有现象都塞进框架当作胜利。理论价值来自约束力和可证伪性。

## 最小论文叙事

一篇系统论文可以这样讲：

1. 现有设备能力模型通常把 compute、storage、communication 分开建模；这在 fusion、program-state-heavy accelerators、recursive fabrics 上不够。
2. 我们提出 information transformation fabric：设备能力是可组合 transformation envelope。
3. Program state 是一等信息状态，因此 instruction stream、dispatch、vendor task rows、metadata 也参与性能边界。
4. 调度是目标 transformation 通过 fabric primitives 的 cost-aware factorization。
5. 在 DFU case study 中，我们 dump transformation graph，验证 visibility/lifetime/dependency/fusion equivalence，并解释 performance bound。
6. 在 GPU/Roofline 或 cluster/AllReduce case study 中，我们展示该模型可退化到已有模型，并在边界变化或 program-state cost 下给出更强解释。

## 近期路线

### Phase 0: 文档化

- 固化本文定义。
- 从 `../archive/discussions.md` 中抽取相关术语。
- 写一个 DFU scheduling semantics note。

### Phase 1: 只读 extractor

输入：

```text
ProcessorTileProgram 或 FiberExecutableProgram
```

输出：

```text
InformationTransformationGraph
```

第一版只需要覆盖：

- tile value state
- visibility state
- SRAM lifetime state
- route / compute / store transformation
- loop / vendor task projection as program state

### Phase 2: Validation

检查：

- 所有 compute 输入在本地 visible。
- store 之前 value 已 finalized。
- loop-carried accumulator 依赖闭合。
- cross-app dependency 必须 materialized。
- fused 与 unfused graph 在 boundary-visible outputs 上等价。

### Phase 3: Cost Summary

先做粗模型：

```text
value_ops
movement_edges
storage_lifetime
program_state_bytes_or_rows
sync_edges
```

不用一开始追求真实 latency，只看趋势和瓶颈解释。

### Phase 4: Compose Toy Model

构造两个小 fabric，通过有限 bandwidth edge 组合，证明 macro envelope 不是线性相加，并能推出保守上界。

## 当前判断

这个理论最有希望成立的版本不是“信息相对论解释一切”，而是：

> A program-aware, recursively composable capability-envelope model for computing fabrics.

它的第一块试金石应是 DFU Fusion。原因很简单：DFU Fusion 会同时攻击 data movement、SRAM lifetime、program state、dispatch、vendor capacity 和 dependency semantics。如果模型能在这块脏砖上站住，再去谈 GPU、cluster 和通用计算设备能力上界，底气会强很多。
