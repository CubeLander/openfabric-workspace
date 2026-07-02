# OpenFabric Paper 总体设计报告

日期：2026-07-02

本文档是 OpenFabric paper 当前内部规划稿，用于统一论文主线、技术贡献、章节结构、
评测计划和风险边界。

## 1. 论文定位

OpenFabric paper 的研究对象不是某个具体 DFU 算子的实现，而是：

```text
DTensor programming model for spatial accelerators
```

更具体地说，论文要回答：

```text
如何把空间型加速器上的算子开发，从手写 PE/template/graph/runtime package，
提升为可组合、可检查、可 lowering 的 distributed tensor programming model？
```

当前 vendor workflow 暴露了一个很清楚的工程事实：算子作者真正手写的是
case contract、PE work partition、template CSV 生成逻辑、subtask graph hook、
data/control material。vendor `common_oper/build_app` 才继续负责 CSV parse、
operand/resource allocation、COPY/COPYT endpoint patching 和 binary packaging。

OpenFabric 的第一阶段不应该推翻 vendor assembler，而应该替代手写 case authoring
这一层。

## 2. 核心问题

Spatial accelerator 上的算子开发困难，不是因为单条指令难写，而是因为程序员必须
同时维护：

```text
tensor placement
PE ownership
tile residency
cross-PE visibility
collective / route dependency
task-subtask-instance packing
operand/base address/runtime package constraints
```

传统手写 workflow 把这些语义分散在 `conf.h`、`conf_PEmap.h`、template C/C++、
graph plugin、RISC-V control program 和 shell scripts 里。结果是：

- 算子语义和 target artifact 混在一起；
- 新 shape / 新算子 / 新 fusion 很难系统复用；
- COPY/COPYT、broadcast、reduce、store 的依赖关系不具备统一语义层；
- 出错时很难定位是 placement、tile schedule、graph edge、operand allocation
  还是 runtime-control 问题；
- 最终 binary diff 过早成为开发主战场，容易陷入 ABI 泥潭。

## 3. OpenFabric 的核心思想

OpenFabric 把 spatial accelerator 建模成一个 mini distributed tensor machine：

```text
PE mesh          -> DeviceMesh
PE-local storage -> rank-local memory / tile residency
SPM/SRAM         -> explicit storage boundary
COPY/COPYT       -> visibility / route lowering primitive
task/subtask     -> backend execution/package structure
```

用户或上层 compiler 表达的是：

```text
tensor shape / dtype / placement
explicit load/store boundary
logical compute op
logical collective / visibility intent
```

编译器逐层 lower：

```text
DTensor Program
  -> ProcessorTileProgram
  -> TileValue / LogicalCollective dependency view
  -> Template / Graph / RuntimeControl plans
  -> VendorAssemblerInputBundle
  -> existing vendor assembler/runtime
```

## 4. 关键设计判断

### Tile Program 是语义主 IR

每个 PE/Tensor Core 有自己的 tile program：

```text
materialize(A_tile)
materialize(B_tile)
gemm_tile_update(A_visible, B_visible)
relu_tile(C_tile)
store(Y_tile)
```

TileValue 名字全局唯一，logical collective 是共享程序对象。全局 dependency graph
不是第一主存储，而是从 tile program 和 value use-def 关系派生出来的视图。

### Fiber 不是语义中心

B-line 文档明确指出，Fiber 更适合作为 execution-organization view。语义主干应该是
`ChipProgram -> ProcessorTileProgram -> TemplateExpansion / PhysicalProgram`。

### 不先替代 vendor assembler

旧 B-line 最大教训是太早手写 final CBUF/MICC binary。新路线应该先生成 vendor
assembler input bundle：

```text
CaseConfigPlan
TemplateCsvProgram
SubtaskGraphPlan
GraphPluginBuildPlan
RuntimeControlPlan
```

然后交给 `common_oper/build_app`。

## 5. 贡献点

### C1. DTensor programming model for spatial accelerators

定义 mesh、placement、storage boundary、logical collective、tile action 等对象，让
空间加速器算子可以用 distributed tensor 语义表达。

### C2. Tile Program and LogicalCollective IR

提出 per-PE Tile Program + globally named TileValues + shared
LogicalCollective 的中间表示，连接 DTensor 语义和硬件执行。

### C3. Vendor-compatible lowering without binary-first trap

提出把编译目标设为 vendor case-authoring material，而不是直接生成 final binary。
这保留现有 assembler/toolchain 可信路径，同时自动化最脆弱的人工部分。

### C4. Exposure-case validation methodology

用不同算子暴露模型不同边界：

- GEMM：shard/replicate、A broadcast/COPYT、B readonly sharing、C partition。
- GEMM+ReLU：tile op-chain 和 fusion boundary。
- Softmax：row partition、local reduction、subtask materialization。
- log10max：chain op、global scalar/reduction、fallback collective strategy。
- Elementwise：简单 per-tile parallel baseline。

## 6. 评测计划

评测不应只报告性能数字，而要证明 programming model 的表达力、lowering 可行性、
artifact 可审计性和 vendor-flow 兼容性。

建议 evaluation questions：

```text
EQ1 Expressiveness:
  不同 exposure cases 能否映射到统一 DTensor/Tile Program 模型？

EQ2 Surface reduction:
  OpenFabric 减少或集中维护了多少手写 case surface？

EQ3 Lowering validity:
  生成的 template/graph/runtime material 能否解释或复现 vendor case artifacts？

EQ4 Provenance and debug:
  high-level tile/action 是否能追踪到 template CSV / graph node / runtime plan？

EQ5 Compatibility:
  是否能继续使用 vendor common_oper/build_app 生成 package？
```

## 7. 风险边界

不能声称：

```text
OpenFabric 已经是完整通用 spatial compiler。
OpenFabric 已替代 vendor runtime。
OpenFabric 已自动优化所有 collective。
当前所有 exposure cases 都已有完整 numerical/runtime proof。
```

可以稳健声称：

```text
OpenFabric identifies and implements a DTensor-to-tile-to-vendor-case lowering
path, validated on multiple operator surfaces extracted from real vendor
workflow evidence.
```
