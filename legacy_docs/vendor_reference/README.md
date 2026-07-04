# Vendor Reference：甲方原始工具链证据库

这个目录只保存 **vendor / 甲方原始工作流的事实证据**，不作为 OpenFabric runtime
或 compiler 的架构真相来源。

如果你要理解 OpenFabric 自己的运行模型，请从：

- [compiler/README.md](../compiler/README.md)
- [runtime/README.md](../runtime/README.md)

如果你要解释“甲方原始流程为什么生成这些文件 / 这些字段从哪里来 / 为什么二进制
diff 长这样”，才进入本目录。


## Runnable Baseline Anchor

The first OpenFabric-generated GEMM image that runs to completion in the vendor
DFU3500 / SimICT workflow is recorded in
[`../../RUNNABLE_BASELINE.md`](../../RUNNABLE_BASELINE.md).  Vendor binary
differences after that point should be interpreted as evidence to classify, not
automatically as blockers.

## Original Materials Audit

Before changing binary/runtime-critical code, read
[`original_materials_audit.md`](original_materials_audit.md).  It maps the
original vendor Office documents and `common_oper` sources to the OpenFabric
reference notes that currently own each fact.  This is the guardrail against
guessing binary interfaces from partial logs.

## 目录结构

| 子目录 | 作用 |
| --- | --- |
| [original_materials_audit.md](original_materials_audit.md) | 原始 Office 文档、`common_oper` 源码、OpenFabric 引用位置的审计索引 |
| [overview](overview/README.md) | 从框架视角理解甲方工具链全链路 |
| [case_authoring](case_authoring/README.md) | case 是怎么手写、生成、组织出来的 |
| [common_oper](common_oper/README.md) | CSV -> task/subtask/exeBlock/inst -> binary 的核心证据 |
| [runtime_evidence](runtime_evidence/README.md) | RISC-V 控制程序、DpuAPI、SimICT 行为证据 |
| [cases](cases/README.md) | 具体 case 的调查记录 |
| [remote_ops](remote_ops/README.md) | arch-13 / 远程环境 / 上传运行链路证据 |

## 推荐阅读路径

### 先建立整体图

1. [overview/from-torch-view.md](overview/from-torch-view.md)
2. [overview/end-to-end-flow.md](overview/end-to-end-flow.md)
3. [case_authoring/operator-case-development.md](case_authoring/operator-case-development.md)
4. [case_authoring/handwritten-operator-contract.md](case_authoring/handwritten-operator-contract.md)

### 再看二进制生成链路

0. [original_materials_audit.md](original_materials_audit.md)
1. [common_oper/csv-to-binary-pipeline.md](common_oper/csv-to-binary-pipeline.md)
2. [common_oper/task-creation-generategraph-chain.md](common_oper/task-creation-generategraph-chain.md)
3. [common_oper/subtask-graph-compile-chain.md](common_oper/subtask-graph-compile-chain.md)
4. [common_oper/binary-artifact-generation-pipeline.md](common_oper/binary-artifact-generation-pipeline.md)
5. [common_oper/dfu3500-gemm-binary-replay.md](common_oper/dfu3500-gemm-binary-replay.md)
6. [common_oper/openfabric-vs-vendor-compile-flow-report.md](common_oper/openfabric-vs-vendor-compile-flow-report.md)
7. [common_oper/dfu3500-hardware-constraints-from-vendor-algorithms.md](common_oper/dfu3500-hardware-constraints-from-vendor-algorithms.md)

### 最后对齐 runtime 证据

1. [runtime_evidence/riscv-control-and-dpuapi.md](runtime_evidence/riscv-control-and-dpuapi.md)
2. [runtime_evidence/dpu-dma-instruction-load-share.md](runtime_evidence/dpu-dma-instruction-load-share.md)
3. [runtime_evidence/simict-runtime.md](runtime_evidence/simict-runtime.md)
4. [runtime/README.md](../runtime/README.md)

## 边界约定

- `vendor_reference` 记录 vendor 原始源码、脚本、diff、远程环境观察。
- `runtime` 负责沉淀 OpenFabric 对运行时控制面和数据面的整理后模型。
- `compiler` 负责沉淀 OpenFabric lowering / binary serializer 的实现设计。
- vendor 现状不自动等于 OpenFabric 长期架构；但当前 DFU-first 阶段必须尊重它的
  ABI 和 SimICT 工作流事实。
