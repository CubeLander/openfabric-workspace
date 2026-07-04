# 知识字段真相登记表（Knowledge Field Ownership）

**用途**：把"同一主题多个文档"转成"每个知识字段可追踪的主链真相"。
**来源**：`docs/` 索引计划（`rfc-knowledge-index-refactor-2026-06-14.md`）。

## 规则

- 每个 Knowledge Field 至少保留 1 个 `authority_level: source_of_truth` 文档。
- 同一字段可允许 1~2 个 `source_of_truth`（可用于主/备份或多源码视角）。
- `context` 文档用于解释、边界讨论、参数解释。
- `history` 文档保留演进痕迹（为什么改/为什么弃用）。
- 每个字段需显式声明归属主线：`compiler` / `runtime` / `shared`（shared 表示两条主线共同依赖）。
- 新文档添加时，必须显式声明是否修改哪个 field 的主权链（`supersedes` / `superseded_by`）。

建议字段名列表（可扩展）：
`execution_model`、`chip_topology`、`memory_model`、`chip_level_pipeline`、`tile_routing`、`load_store_boundary`、`binary_packaging`、`runtime_contract`、`instruction_semantics`。

| field_name | mainline | authority_level | truth_doc | context_docs | history_docs | decided_by | last_reviewed | notes |
|---|---|---|---|---|---|---|---|---|
| `execution_model` | shared | source_of_truth | `architecture/pe-microarchitecture/pe-microarchitecture-execution-model.md` | `architecture/instruction-encoding/isa-execution-model.md` | `architecture/instruction-encoding/isa-execution-model.md` | `code + design` | `2026-06-14` | 作为 DFU 执行语义的核心定义入口 |
| `chip_topology` | shared | source_of_truth | `architecture/pe-microarchitecture/pe-mesh-and-task-model.md` | `architecture/soc-system/storage-hierarchy-overview.md` | `docs/compiler/tile-centered-debug-trace-design.md` | `code + design` | `2026-06-14` | 决定 PE/mesh/任务边界 |
| `memory_model` | shared | source_of_truth | `architecture/soc-system/storage-hierarchy-overview.md` | - | `vendor_reference/common_oper/binary-artifact-generation-pipeline.md` | `code + experiment` | `2026-06-14` | SRAM/SPM 边界与访问约束 |
| `chip_level_pipeline` | compiler | source_of_truth | `compiler/notes/env_refactor_chip_level_program.md` | `architecture/instruction-encoding/inst-t-to-physical-resources.md` | `docs/compiler/binary_packaging/research_notes/archive/rfc-tileloop-to-vendor-lowering-execution-plan.md` | `maintainer_review` | `2026-06-14` | 对齐 AGENTS.md 的"分层编译流水线" |
| `load_store_boundary` | compiler | source_of_truth | `compiler/notes/env_refactor_chip_level_program.md` | `runtime/control/dfu-runtime-programming-model.md` | `vendor_reference/common_oper/task-creation-generategraph-chain.md` | `code + design` | `2026-06-14` | 明确 DTensor load/store 与 SRAM 声明边界 |
| `tile_routing` | compiler | source_of_truth | `docs/compiler/binary_packaging/research_notes/archive/rfc-tile-microblock-as-lowering-authority.md` | `architecture/instruction-encoding/instruction-format-and-rtl-packing.md` | `docs/compiler/binary_packaging/research_notes/archive/stage-report-post-tile-binary-lowering.md` | `maintainer_review` | `2026-06-14` | 关注 tile 级路由、phase 与动作链 |
| `binary_packaging` | compiler | source_of_truth | `vendor_reference/common_oper/csv-to-binary-pipeline.md` | `vendor_reference/common_oper/binary-artifact-generation-pipeline.md` | `docs/compiler/binary_packaging/research_notes/archive/rfc-program-bin-serializer.md` / `docs/compiler/binary_packaging/research_notes/archive/stage-report-post-tile-binary-lowering.md` | `maintainer_review` | `2026-06-14` | 覆盖 CBUF / packing / component 级结构 |
| `runtime_contract` | runtime | source_of_truth | `vendor_reference/runtime_evidence/riscv-control-and-dpuapi.md` | `vendor_reference/runtime_evidence/simict-runtime.md` | `simict3500final/gpdpu/users/risc_nn_riscv/testcase/workflow/README.md` | `maintainer_review` | `2026-06-14` | 从 bundle 到 RISC-V 调度的契约 |
| `instruction_semantics` | shared | source_of_truth | `architecture/instruction-set/dfu3500-simd/README.md` | `architecture/instruction-set/dfu3500-tensor/README.md` | `architecture/instruction-set/dfu3500-simd/OCR_DERIVED_NOTES.md` | `maintainer_review` | `2026-06-14` | 指令级语义的单一入口 |

## 字段状态模板（按需复制）

```yaml
field_name: execution_model
owner_state: source_of_truth
truth_doc: architecture/pe-microarchitecture/pe-microarchitecture-execution-model.md
context_docs:
  - architecture/instruction-encoding/isa-execution-model.md
history_docs:
  - compiler/notes/archive/...
supersedes:
  - compiler/notes/archive/stage-report-...
decided_by: "code+tests"
last_reviewed: "2026-06-14"
```

当新增/修改某 field 时，至少同步更新：
1. `rfc-knowledge-index-refactor-2026-06-14.md` 或下游 topic index；
2. 本文件的对应行；
3. 真相文档中的 `last_reviewed` 与 `supersedes` 关系。
