# OpenFabric Paper 导师简报

## 一句话定位

OpenFabric 提出一种面向 spatial accelerator 的 DTensor programming model：
把 PE mesh 看成单机内的 distributed tensor machine，用 shape、placement、
logical collective、tile program 和 storage boundary 表达算子，再逐层 lowering
到现有 vendor case/toolchain 能消费的执行材料。

## 为什么不是 GEMM demo

GEMM 只是暴露面之一。真正问题是甲方需要持续把不同模型、不同算子、不同 shape
部署到空间型加速器上，而当前 workflow 依赖手写 case contract、PE map、CSV
template、graph hook、RISC-V control material。这种方式无法支撑长期的多算子、
融合、可重定位和调试需求。

## 核心主张

```text
Spatial accelerator operator programming can be expressed as DTensor placement
and tile-value visibility, then systematically lowered to hardware task,
subtask, PE-template, graph, and runtime-control surfaces.
```

## 技术贡献

1. **DTensor programming model for spatial accelerators**
   用 mesh、Shard/Replicate/Partial-like placement、explicit storage boundary、
   logical collective 表达空间加速器算子。

2. **Tile Program as source of truth**
   每个 PE/Tensor Core 维护本地 tile action sequence，同时引用全局唯一
   TileValue 和 shared LogicalCollective；全局 dependency graph 是派生视图。

3. **Vendor-compatible lowering strategy**
   不先替代 vendor assembler，而是生成 case-authoring material：
   case config、PE work partition、template CSV、subtask graph、runtime control。

4. **Exposure-case validation**
   用 GEMM、GEMM+ReLU、softmax、log10max、elementwise 展示模型覆盖不同
   编程暴露面，而不是只报告单一 benchmark。

## 主要评测问题

```text
EQ1: 这个模型能否表达不同算子的 placement / visibility / tile action？
EQ2: OpenFabric 能否减少手写 vendor surface，同时保持可审计 provenance？
EQ3: 生成的 vendor-compatible material 能否被现有 toolchain/package flow 接收？
EQ4: 不同算子暴露面是否证明模型不是 GEMM-only？
```

## 当前风险

- 不能声称已经覆盖所有 spatial accelerators。
- 不能声称完全替代 vendor assembler/runtime。
- 如果只展示 GEMM，会被看成 case generator；必须把 exposure cases 组织成模型覆盖性证据。
- `runtime_ready`、binary parity、SimICT execution、numerical correctness 需要分层陈述，不能混在一起。
