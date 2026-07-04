# second_wind docs

这里是 `second_wind` 之后新的活文档目录。仓库已经重新以
`simict3500final` 为中心，后续真正要推进的原则、契约、验证入口和当前实现证据
放在这里。

## Core Principles

先读这些，它们定义当前路线的设计边界：

```text
handwritten-operator-contract.md
vendor-assembler-input-protocol.md
openfabric-lowering-principles.md
runtime-plan-image.md
operator-coverage-checklist.md
draft-convergence-audit.md
chip-program-plan.md
dtensor-stage-shard-address-plan.md
address-binding-projections.md
partial-reduce-stage-binding.md
typed-vector-operand-design.md
openfabric-vector-hardware-coverage.md
```

## Current Case Evidence

这些记录当前 active cases 的 vendor/package 事实：

```text
gemm-vendor-graph-csv-layout.md
gemm-subtask-blocks-and-graph-dependency.md
graph-plan-projection.md
softmax-subtask-site-refactor.md
isa/hmmal.md
vendor-workflow-evidence/
```

## Local Validation

这些只服务本地验证和工具链入口：

```text
environment.md
cmake-shadow-build.md
```

## Cleanup Policy

`docs/` 只放未来仍应遵守或查证的内容。已经被实现、源码 README、更高层原则文档
覆盖的过程草稿应删除，不在这里长期堆积。仍然带有未完成任务、开放风险或后续路线的
设计讨论继续保留在 `../drafts/`；本轮逐篇 triage 记录见
`draft-convergence-audit.md`。

旧的 OpenFabric / B-line 文档已经收进旧实现目录：

```text
../legacy_implementations/openfabric_bline/docs/
```

不要默认把旧文档树搬回来。只有当某份文档重新成为
`simict3500final` 优先路线的一部分时，再把它提升回这里。
