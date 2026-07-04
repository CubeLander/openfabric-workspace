# Scoped Tensor Projection 清扫审计

状态：活审计索引。

日期：2026-07-04

本文件记录一次以 `next_stage_refactor_direction.md` 为指导思想的 workspace
清扫计划。这里的目标不是把旧资料一把火烧掉，而是把它们重新分层：

```text
先进指导思想
  -> 当前应遵守的设计原则
  -> 仍有证据价值的硬件/legacy facts
  -> 只作历史参考的旧路线
  -> 可删除或外移的生成物/交付物
```

## 指导原则

当前先进模型是：

```text
Tensor
  -> StreamTensorView
  -> FiberTensorView
  -> TypedTileValue
  -> Operand
  -> Instruction / Binary
```

清扫时按这个标准审计旧文档和旧实现：

```text
1. `Tensor` 是 truth source，不再把 `DTensor` 当最终命名。
2. `Stream` / `Fiber` 既是 execution hierarchy，也是 data scope。
3. `StreamTensorView` / `FiberTensorView` 是 projection/view，不是新的 tensor truth。
4. OpenFabric 只有一种真正的 tile；tile 出现在 FiberTensorView materialization
   边界附近。
5. Operand、register、Dst、tensor tmp、SPM slot、CSV symbol 都是物理或准物理
   materialization 结果。
6. 开发者面对 `add/mul/max/load/store/matmul_accumulate` 这类逻辑运算；
   `FADD/HADD/HMMAL/HLDT/HSTT/COPYT` 是 backend lowering 结果。
```

## 审计范围

明确排除：

```text
OpenFabric/
  active implementation submodule，本轮不在 workspace 清扫里直接修改。

tt-metal/
  外部参考仓库，只作为 Tenstorrent 证据来源，不纳入清扫。
```

纳入：

```text
根目录 *.md
docs/
research/
notes/
legacy_implementations/openfabric_bline/
legacy_docs/
```

## 第一轮发现

### 根目录和 docs

这些文件应作为新阅读路径的核心：

```text
next_stage_refactor_direction.md
docs/operator-coverage-checklist.md
docs/runtime-plan-image.md
docs/vendor-workflow-evidence/
docs/isa/
```

但它们不是同一层级：

```text
next_stage_refactor_direction.md
  当前命名和模型的最高指导。
```

第一批需要更新旧术语的文件：

```text
research/targets/tenstorrent-portability-scout.md
```

`research/planning/` 曾是旧论文叙事集中区：大量使用
`DTensor programming model`、`Tile Program`、`TileValue`、
`ProcessorTileProgram`。这些不是全错，但已经被删除，后续论文叙事应该改写成：

```text
Scoped Tensor Projection for Spatial Accelerators
Tensor / StreamTensorView / FiberTensorView
TypedTileValue / Operand materialization
Stream/Fiber execution-data scope
```

### legacy_implementations/openfabric_bline

初步体积：

```text
legacy_implementations/openfabric_bline/                         387M
legacy_implementations/openfabric_bline/report/                  239M
legacy_implementations/openfabric_bline/compiler/                127M
legacy_implementations/openfabric_bline/compiler/.../payloads/   123M
legacy_implementations/openfabric_bline/docs/                    4.3M
```

这说明 legacy 的主要重量不是知识文档，而是历史 payload / report / validation
产物。文档本身不大，值得先精读和分类。

高价值，应该保留或摘录到当前 `docs/`：

```text
docs/architecture/instruction-set/
docs/architecture/pe-microarchitecture/
docs/architecture/soc-system/
docs/architecture/runtime-model/
docs/vendor_reference/common_oper/
docs/vendor_reference/runtime_evidence/
docs/vendor_reference/cases/gemm/
docs/vendor_reference/cases/softmax/
compiler/gpdpu_compiler/core/dfu3500/
compiler/gpdpu_compiler/validation/dfu_binary_checks/
```

理由：这些地方记录 DFU3500 的 ISA、PE-local resource、SPM/runtime、vendor
package、binary check、operand/resource 事实。它们不是先进抽象，但它们是
lowering 约束和事实来源。

中价值，作为历史设计经验保留，但不应直接继承架构：

```text
compiler/gpdpu_compiler/core/stream_compiler/
compiler/gpdpu_compiler/core/program_tile.py
compiler/gpdpu_compiler/core/program_*.py
docs/compiler/design/
docs/compiler/binary_packaging/research_notes/enhancements/
notes/aggressive/
tests/
```

理由：这里有很多 B-line 对 stream/fiber/tile/value 的探索，尤其
`pro-fiber-comments.md`、`rfc-stream-tile-plan-flat-lowering.md` 这类材料和当前
模型有亲缘关系。但旧 `ProcessorTileProgram` / `TileValue` 语义容易把我们拉回
tile-as-source-of-truth，不能直接照搬。

低价值或删除候选：

```text
report/b_line_progress_payloads/
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/payloads/
IEEE_Conference_Template/
历史 tgz / binary package / input_data.bin
大体积 generated chip_program.json / runtime bundle
```

理由：这些是历史交付或生成物，占空间大，且不应作为设计 truth。删除前需要确认
是否已经有 checksum、source recipe、或更小的摘要文档保留关键事实。

## 清扫动作建议

### 阶段 1：标记指导权威

已开始：

```text
1. 把 `next_stage_refactor_direction.md` 标记为最高设计指导。
2. 给旧 DTensor/tile 指导文档加状态说明。
3. 更新 workspace README / docs README 的阅读路径。
```

### 阶段 2：术语迁移

优先迁移这些旧词：

```text
DTensor
  -> Tensor / StreamTensorView，视上下文决定。

LocalDTensor / ShardTensor
  -> FiberTensorView。

DTensorTileRef / LocalTileRef
  -> TileRef。

TileValue
  -> TypedTileValue，除非它真的是历史 `TileValue` 对象。

Tile Program / ProcessorTileProgram
  -> Fiber-local lowering plan / materialization plan / action trace，
     不再作为语义主 IR。
```

不要机械替换。判断依据是：

```text
这个对象是不是 truth source？
它属于 stream scope 还是 fiber scope？
它是 view/projection，还是 materialized value？
它是逻辑 operation，还是物理 instruction？
```

### 阶段 3：legacy 价值提取

从 legacy 里提取三类东西：

```text
Hardware facts:
  PE mesh, operand RAM, SPM, instruction encoding, runtime ABI。

Lowering facts:
  CSV/graph/runtime/package 如何被 vendor 工具消费。

Failure lessons:
  为什么 ProcessorTileProgram、binary-first generator、payload-first workflow
  会变重。
```

提取后，legacy 目录本身可以更大胆地归档或瘦身。

### 阶段 4：删除或外移候选

原则：

```text
1. 不删除唯一事实来源。
2. 不删除仍能复现客户交付的唯一 recipe。
3. 优先删除可以从源码再生成的大体积 payload。
4. 删除前在本文件记录理由和替代索引。
```

第一批可审计删除候选：

```text
legacy_implementations/openfabric_bline/report/b_line_progress_payloads/
legacy_implementations/openfabric_bline/compiler/gpdpu_compiler/validation/dfu3500_partner_validation/payloads/
legacy_implementations/openfabric_bline/bline-three-operator-upload-validation.tgz
legacy_implementations/openfabric_bline/IEEE_Conference_Template/
```

建议先做：

```text
1. 给每个候选目录找 README / manifest / sha256。
2. 如果已有摘要和复现脚本，删除 generated payload。
3. 如果没有摘要，先写一个 `LEGACY_PAYLOAD_MANIFEST.md` 再删。
```

## 已执行清扫

### 2026-07-04 表层旧设计文档清理

用户判断：`next_stage_refactor_direction.md` 的新架构思想高于旧设计文档；被新架构
覆盖、明显落伍、或会误导后续实现的旧设计文档可以删除。

据此删除：

```text
ADDRESS_REGISTER_ABSTRACTION_PLAN_DRAFT.md
LOGICAL_TILE_MATERIALIZED_OPERAND_MODEL.md
OPENFABRIC_IDEAL_ABSTRACTION_NOTES_CN.md
SPM_PLAN_REFACTOR_PLAN.md
HANDOFF_1.md
drafts/
research/planning/
research/audit/operator_coverage_targets.md
research/roadmap/openfabric-publication-roadmap.md
docs/chip-program-plan.md
docs/dtensor-stage-shard-address-plan.md
docs/typed-vector-operand-design.md
docs/draft-convergence-audit.md
docs/log10-refactored-integration-plan.md
docs/lowering-shell-reorg.md
docs/vendor-toolchain-source-organization.md
docs/softmax-subtask-site-refactor.md
docs/independent_prompt/
docs/openfabric-lowering-principles.md
docs/address-binding-projections.md
docs/partial-reduce-stage-binding.md
```

保留原则：

```text
next_stage_refactor_direction.md
  继续作为最高架构指导。

DFU3500_ADDRESS_COMPOSITION_NOTES.md
  保留，因为主要记录 base_addr + imm 这类硬件/ABI address facts。

docs/isa/
docs/vendor-workflow-evidence/
docs/operator-coverage-checklist.md
docs/openfabric-vector-hardware-coverage.md
docs/runtime-plan-image.md
  保留，因为它们更像事实、能力边界或 target lowering 约束，而不是旧架构主张。
```

### 2026-07-04 legacy Python / payload 清理

用户判断：

```text
legacy_implementations 里的 Python 代码已经被新思想和 active OpenFabric 覆盖；
这些代码写得很糊，基本跑不通。被新思想覆盖或明显落伍的内容可以删除。
```

据此删除：

```text
legacy_implementations/openfabric_bline/compiler/gpdpu_compiler/
legacy_implementations/openfabric_bline/compiler/examples/
legacy_implementations/openfabric_bline/compiler/tools/
legacy_implementations/openfabric_bline/compiler/torch_examples/
legacy_implementations/openfabric_bline/tests/
legacy_implementations/openfabric_bline/tools/
legacy_implementations/openfabric_bline/report/b_line_progress_payloads/
legacy_implementations/openfabric_bline/bline-three-operator-upload-validation.tgz
legacy_implementations/openfabric_bline/IEEE_Conference_Template/
```

保留：

```text
legacy_implementations/openfabric_bline/docs/
legacy_implementations/openfabric_bline/compiler/notes/
legacy_implementations/openfabric_bline/research/
legacy_implementations/openfabric_bline/notes/
legacy_implementations/openfabric_bline/report/outline.md
legacy_implementations/openfabric_bline/*.md
```

删除前后：

```text
Python files: 223 -> 0
legacy archive size: 387M -> 5.3M
docs size retained: 4.3M
compiler notes retained: 584K
report retained: 44K
```

保留原则：文档和设计考古继续留下，因为里面仍可能有硬件事实、vendor evidence 和
失败路线经验。旧 Python 代码、测试、工具、payload 和历史交付包不再作为可运行
证据保留。

### 2026-07-04 legacy_docs 清理

用户继续授权：用 `next_stage_refactor_direction.md` 审计 `docs/`、`legacy_docs/`、
`notes/`。学习笔记、甲方硬件笔记、ISA 笔记、vendor workflow 证据要保留；被新架构
覆盖的旧设计路线可以删除。

本轮请 subagents 分区只读审计：

```text
legacy_docs/compiler/design/
legacy_docs/compiler_notes/ 与 legacy_docs/compiler/
legacy_docs/compiler/binary_packaging/research_notes/
legacy_docs/architecture/、legacy_docs/runtime/、legacy_docs/vendor_reference/、notes/
```

据此删除一批旧路线文档：

```text
legacy_docs/INDEX.md
legacy_docs/CONTENT_INVENTORY.md
legacy_docs/knowledge-field-owner.md
legacy_docs/rfc-knowledge-index-refactor-2026-06-14.md

legacy_docs/compiler/planB.md
legacy_docs/compiler/lowering/README.md
legacy_docs/compiler/design/README.md
legacy_docs/compiler/design/tile-program-as-source-of-truth.md
legacy_docs/compiler/design/global-tile-dependency-network.md
legacy_docs/compiler/design/bline-current-architecture-review.md
legacy_docs/compiler/design/bline-boundary-hardening-rfc.md
legacy_docs/compiler/design/bline-organization-rfc.md
legacy_docs/compiler/design/bline-log10max-ring-spmd-collective-rfc.md

legacy_docs/compiler_notes/README.md
legacy_docs/compiler_notes/TODO.md
legacy_docs/compiler_notes/notes/archive/2026-06-14_chipop_oo_refactor_plan.md
legacy_docs/compiler_notes/notes/archive/2026-06-14_knowledge_curation_plan.md
legacy_docs/compiler_notes/notes/archive/tile_level_legacy_vs_new_dump.md
legacy_docs/compiler_notes/notes/enhancements/2026-06-20_b_line_op_spec_driven_lowering_rfc.md
legacy_docs/compiler_notes/notes/enhancements/2026-06-22_b_line_aggressive_parallel_execution_rfc.md
legacy_docs/compiler_notes/notes/enhancements/2026-06-22_b_line_binary_operator_delivery_rfc.md
legacy_docs/compiler_notes/notes/enhancements/2026-06-22_b_line_parallel_kickoff_status.md
legacy_docs/compiler_notes/notes/log10max/archive/2026-06-16_rfc-log10max-app-to-tile-lowering.md
legacy_docs/compiler_notes/notes/log10max/archive/2026-06-16_todo.md
legacy_docs/compiler_notes/notes/log10max/archive/README.md
legacy_docs/compiler_notes/notes/refactor/rfc-op-lowering-spec-strangler.md

legacy_docs/compiler/binary_packaging/research_notes/archive/rfc-dfu-graph-lowering-from-processor-tile.md
legacy_docs/compiler/binary_packaging/research_notes/archive/rfc-multi-accumulator-k-body-folding.md
legacy_docs/compiler/binary_packaging/research_notes/archive/rfc-post-tile-lowering-branches.md
legacy_docs/compiler/binary_packaging/research_notes/archive/rfc-tile-microblock-as-lowering-authority.md
legacy_docs/compiler/binary_packaging/research_notes/archive/rfc-tileloop-to-vendor-lowering-execution-plan.md
legacy_docs/compiler/binary_packaging/research_notes/archive/legacy_drafts/testcase_runtime_package_workflow.md
legacy_docs/compiler/binary_packaging/research_notes/enhancements/2026-06-19_rfc-b-line-finalize-epilogue-template-semantics.archived.md
legacy_docs/compiler/binary_packaging/research_notes/enhancements/pro-fiber-comments.md
legacy_docs/compiler/binary_packaging/research_notes/enhancements/rfc-fiber-flat-ops-to-block-projection.md
legacy_docs/compiler/binary_packaging/research_notes/enhancements/rfc-stream-tile-plan-flat-lowering.md

legacy_docs/runtime/cases/README.md
legacy_docs/runtime/control/dfu-hardware-relocation.md
legacy_docs/runtime/control/dfu-kernel-runtime-work-split.md
legacy_docs/runtime/control/dfu-relocatable-kernel-impl.md
legacy_docs/runtime/control/dfu-runtime-programming-model.md
legacy_docs/runtime/debug/README.md
legacy_docs/runtime/simulator/README.md
legacy_docs/runtime/simulator/local-mock-runtime.md
legacy_docs/runtime/workflow/README.md
```

同时重写或修补这些入口，使它们不再把旧索引/旧 B-line 设计当权威：

```text
legacy_docs/README.md
legacy_docs/compiler/README.md
legacy_docs/runtime/README.md
legacy_docs/runtime/control/README.md
legacy_docs/compiler/cases/README.md
legacy_docs/compiler_notes/notes/refactor/README.md
legacy_docs/compiler/design/bline-vendor-assembler-input-bundle-rfc.md
legacy_docs/vendor_reference/runtime_evidence/README.md
legacy_docs/vendor_reference/cases/softmax/README.md
legacy_docs/compiler/binary_packaging/research_notes/archive/legacy_drafts/README.md
```

本轮明确保留：

```text
legacy_docs/architecture/
legacy_docs/runtime/data/
legacy_docs/vendor_reference/
legacy_docs/compiler/binary_packaging/
legacy_docs/compiler/design/ 中含 DFU facts、GEMM/SUMMA、TT-Metal lessons、
  route/operand/log10max binary evidence 的文档
legacy_docs/compiler_notes/notes/ 中含 operator、decoder、topology、failure lessons 的文档
notes/resolved/
notes/vendor-toolchain-artifact-summary.md
```

暂缓删除的边界：

```text
含旧 `ProcessorTileProgram` / `TileMicroBlock` / `StreamTilePlan` 词的文档不自动删除。
如果它们还保存 vendor row count、runtime struct、TaskResource replay、COPY patching、
remote binary diff、operator failure lessons，就先留作事实矿层。
下一轮应先把事实摘到当前 docs/ 或 vendor_reference/，再删除历史 RFC。
```

## 当前判断

这次清扫的核心不是“少一些文件”，而是让仓库的知识重心从旧的：

```text
DTensor Program -> ProcessorTileProgram -> TileValue -> vendor binary
```

迁移到新的：

```text
Tensor
  -> StreamTensorView
  -> FiberTensorView
  -> TypedTileValue
  -> Operand
  -> Instruction / Binary
```

旧仓库仍然有价值，但价值主要在硬件事实、vendor package 事实、失败经验和少数
stream/fiber 设计探索。它不应该继续充当 OpenFabric 的未来架构模板。
