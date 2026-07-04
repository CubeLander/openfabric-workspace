# RFC: 建立 `docs_refactored` 统一知识索引与跨目录知识收敛

> **注意**：本 RFC 中提到的 `docs_refactored` 目录已于 2026-06-16 重命名为 `docs/`。
> 下文保留原始内容作为历史记录，所有路径引用请自行将 `docs_refactored/` 替换为 `docs/`。

**状态**: Draft
**日期**: 2026-06-14
**作者**: OpenFabric 文档整理协作
**目标目录**: `/home/flecther/workspace/dpu_project/docs`

## 1. 背景与问题

当前仓库的知识文档分散在：

- `/notes`
- `/docs`
- `/compiler/notes`
- `/drafts`
- `/simict3500final`

存在三个问题：

1. 同一主题在多个树下重复；
2. `archive`/`draft` 与“当前有效知识”混在一起；
3. 缺少统一入口，读者很难从一个入口快速定位“当前要看的文档”。

`docs_refactored` 当前为空，适合作为**统一知识索引平面**（Index Plane），不强制替换现有文档，而是先做“轻量汇聚”。

## 2. 目标

- 建立一套稳定、可维护的知识索引制度，覆盖 **架构、指令集、编译器、二进制协议、运行时、案例工作流**。
- 用“两条主线”承载项目知识：
  - **主线一：运行主线**（编译产物如何在模拟器/芯片上运行）
  - **主线二：编译主线**（编译器如何从前端计算图走到可执行二进制）
- 保持现有文档可追溯，不先做大规模搬迁。
- 让任何人都能用统一路径快速找：
  - 当前决策链（single current path）
  - 历史背景（history / archive）
  - 证据或实验（evidence / notes）

## 3. 设计原则

1. **先索引后整理**：先建立索引，不做破坏性重排。  
2. **当前优先**：任何索引都要清楚标记 `current` / `draft` / `history`。
3. **可回溯**：每个知识项至少保留 1 条来源文档链路。 
4. **最小重复**：同主题多份文档只汇总到一个“主入口”，其余作为“补充/历史”。
5. **可自动化**：后续可按 `YAML` 元信息自动校验过期链接。

## 4. 建议的知识域与双主线归属

### 4.1 双主线定义

- **运行主线（Runtime Spine）**：围绕 “产物 -> runtime -> simulator/芯片执行” 的路径。  
  用于回答“程序如何跑起来”。
- **编译主线（Compiler Spine）**：围绕 “用户图 -> 编译器 IR/Pass -> 二进制边界” 的路径。  
  用于回答“编译器如何运行”。

每条文档都应挂到一个主线（或 `shared`）下，避免内容漂移。

### 4.2 知识域（总分）

### D1. 架构与模型（architecture）
- `docs/architecture/*`
- `docs_refactored/compiler/design/*`
- `notes/design/*`
- `notes/*` 中的架构观察文档

### D2. 指令集与执行语义（instruction-set）
- `docs/instruction-set/*`
- `docs_refactored/architecture/isa-execution-model.md`
- 与 SIMD / tensor 相关的 opcode 细节

### D3. 编译器IR与降层（compiler ir）
- `compiler/notes/refactor/*`
- `docs/compiler/binary_packaging/research_notes/enhancements/*`
- `docs/compiler/binary_packaging/research_notes/archive/vendor_abi_dependency_granularity.md`
- `compiler/notes/env_refactor_chip_level_program.md`
- `compiler/notes/archive/*`（历史)

### D4. 二进制协议与打包（binary / protocol）
- `docs_refactored/vendor_reference/common_oper/csv-to-binary-pipeline.md`
- `docs_refactored/vendor_reference/common_oper/binary-artifact-generation-pipeline.md`
- `docs/compiler/binary_packaging/research_notes/archive/rfc-program-bin-serializer.md`
- `docs/compiler/binary_packaging/research_notes/archive/stage-report-post-tile-binary-lowering.md`

### D5. 运行时与工作流（runtime / workflow）
- `docs_refactored/vendor_reference/runtime_evidence/riscv-control-and-dpuapi.md`
- `docs_refactored/vendor_reference/runtime_evidence/simict-runtime.md`
- `simict3500final/.../workflow/*.md`
- `docs/compiler/binary_packaging/research_notes/archive/legacy_drafts/testcase_*`

### D6. 算子案例与验证（operator cases）
- `docs_refactored/vendor_reference/cases/softmax/softmax-case-walkthrough.md`
- `notes/softmax*`
- `notes/onnchip_*`（涉及DRAM/SPM/IO的经验）
- `notes/*gemm*`, `notes/*matmul*`

### D7. 双主线总线（Cross Spine）
- `compiler/notes/env_refactor_chip_level_program.md`
- `docs_refactored/architecture/isa-execution-model.md`
- `docs_refactored/runtime/control/dfu-runtime-programming-model.md`

### 双主线映射

- `architecture / instruction-set / memory model / chip topology` 通常是 **shared**：它们同时服务编译器决策与运行时约束。
- `compiler ir / binary protocol / packing / serializer` 通常是 **compiler** 主线主导。
- `runtime / bundle execution / simulator workflow / driver` 通常是 **runtime** 主线主导。

## 4. 核心升级：从“文档真假”到“知识主权”

你这次 comment 的关键很准：问题本质是“知识债务”，不是“文档太多”。

所以应明确区分三层结构：

- `Markdown`：承载内容的载体
- `Knowledge Item`：对某个主题的知识碎片
- `Knowledge Field`：领域内一个可判定的字段（如 `execution_model` / `route_policy` / `memory_model` / `vendor_graph_binding`）

在同一个 field 有多个版本时，不靠“最近”来决断，而是靠主权链：

1. `authority_level: source_of_truth`（最终真相）
2. `authority_level: design_record`（设计决策）
3. `authority_level: discussion`（讨论）
4. `authority_level: experiment`（实验与验证）
5. `authority_level: historical`（仅历史参考）

同时保留 `supersedes / superseded_by` 形成 DAG，避免 `RFC-v1`、`RFC-v2`、`RFC-final` 的墓地化。

## 5. 整理方法（reduce into docs_refactored）

### 5.1 阶段 A：建立统一索引（不移动文档）

创建以下文件：

- `docs_refactored/README.md`：说明目录目标与使用方式（含双主线树模型）。
- `docs_refactored/INDEX.md`：总目录，含“编译主线 / 运行主线”快速入口。
- `docs_refactored/knowledge-map.yaml`：机器可读元数据索引（见 5.3）。
- `docs_refactored/compiler/README.md`：编译主线树。
- `docs_refactored/compiler/frontend/`：前端子树。
- `docs_refactored/compiler/chip_level_ir/`：chip-level IR 子树。
- `docs_refactored/compiler/lowering/`：降层子树。
- `docs_refactored/compiler/binary_packaging/`：打包子树。
- `docs_refactored/compiler/cases/`：编译案例子树。
- `docs_refactored/runtime/README.md`：运行主线树。
- `docs_refactored/runtime/control/`：控制面子树。
- `docs_refactored/runtime/simulator/`：模拟器子树。
- `docs_refactored/runtime/workflow/`：工作流子树。
- `docs_refactored/runtime/cases/`：运行案例子树。
- `docs_refactored/runtime/debug/`：调试子树。

### 5.2 阶段 B：知识归并（建立“reduce”关系）

对每篇现有文档补充三类关系：

- `role`: `current` / `context` / `history`
- `supersedes`/`superseded_by`
- `depends_on`（前置依赖文档）
- `authority_level`: `source_of_truth` / `design_record` / `discussion` / `experiment` / `historical`
- `knowledge_fields`: [`execution_model`, `route_policy`, ...]（该文档影响的关键字段）
- `owner_doc`: 指定该字段主链中是否可作为 `source_of_truth`

索引页内只显示：

1. 当前主线（1~3篇）
2. 辅助理解（2~6篇）
3. 历史记录（4~10篇）

### 5.3 阶段 C：元数据模式

`knowledge-map.yaml` 建议字段：

```yaml
- id: compiler.ir.tile-dedupe
  topic: compiler
  title: "Tile 路径与下沉边界"
  status: current
  authority_level: source_of_truth
  knowledge_fields:
    - "tile_lowering"
    - "route_policy"
  audience: maintainer, implementer
  summary: "..."
  sources:
    - path: docs/compiler/binary_packaging/research_notes/archive/rfc-dfu-graph-lowering-from-processor-tile.md
    - path: docs/compiler/binary_packaging/research_notes/archive/stage-report-post-tile-binary-lowering.md
  related:
    - docs/compiler/binary_packaging/research_notes/archive/rfc-tile-microblock-as-lowering-authority.md
  superseded_by: null
  last_reviewed: "2026-06-14"
```

### 5.4 阶段 D：归档清洗

- `compiler/notes/archive/*` 保留但标注为 `history`
- `docs/compiler/binary_packaging/research_notes/archive/legacy_drafts/*` 若有可复用内容，优先移入 `docs/compiler/` 或 `docs/runtime/` 的对应子目录；原始 draft 保留并加“迁移锚点”
- 重复高的 RFC / stage-report 做成“汇总对照页”（如 vendor binding、二进制打包、tile降层）

## 6. 文档组织（目标目录）

建议最终目录结构：

- `docs_refactored/`
  - `README.md`
  - `INDEX.md`
  - `knowledge-map.yaml`（待补）
  - `compiler/`
    - `README.md`
    - `frontend/README.md`
    - `chip_level_ir/README.md`
    - `lowering/README.md`
    - `binary_packaging/README.md`
    - `cases/README.md`
  - `runtime/`
    - `README.md`
    - `control/README.md`
    - `simulator/README.md`
    - `workflow/README.md`
    - `cases/README.md`
    - `debug/README.md`
  - `crosswalk.md`

> `crosswalk.md` 用于记录旧目录到新目录的映射（如“旧入口 -> 新入口”），便于团队迁移时平滑衔接。

## 7. 推进与里程碑

### Milestone 1（1 天）
- 完成 `docs_refactored` 目录骨架 + `INDEX.md` + `compiler/` 与 `runtime/` 双主线文件夹与入口 README
- 完成全部文档自动扫描与初始映射（静态清单）

### Milestone 2（1 天）
- 完成 10 个主干子目录 README（`compiler/*`、`runtime/*`）的主链索引
- 将 `notes/design` 与 `compiler/notes/refactor` 中的“当前决策链”提升到主入口级

### Milestone 3（1 天）
- 完成 `knowledge-map.yaml`
- 对 `archive`/`drafts` 添加状态注释（不删原文）
- 对关键知识字段建立 `source_of_truth` 与 `supersedes` 链（如 execution_model）

### Milestone 4（半天）
- 建立迁移检查清单和验收：链接可达、无核心主题“空洞”

## 8. 验收标准

1. 任何人能在 2 分钟内从 `docs_refactored/INDEX.md` 找到：
   - 当前 `compiler spine` 入口
   - 当前 `runtime spine` 入口
   - 当前 `architecture` 入口
   - 当前 `compiler ir` 入口
   - 当前 `binary` 入口
   - 当前 `runtime` 入口
2. 每条主线（compiler/runtime）至少有 1 个 `current` 主链节点，并存在清晰 parent-child 树。
3. 每个关键主题有且仅有 1 个 `current` 入口（允许 1~2 个）。
4. archive 文档可被过滤，不再干扰新任务阅读路径。
5. 所有入口文档在一份统一 YAML 中可枚举。
6. 每个关键知识字段存在且仅存在 1~2 个 `source_of_truth` 文档。

## 9. 风险与对策

- **风险**: 多主题文档边界不清，容易误标状态。
  - 对策：先按“谁是当前工程决策依据”定义状态，不追求一次到位。
- **风险**: 只建索引不改源码文档，读者习惯没变。
  - 对策：为旧目录关键入口添加回链指引，逐步收敛。
- **风险**: 元数据维护成本。
  - 对策：最初只保留 7 个字段，避免过度工程化。

## 10. 变更范围（本 RFC 产物）

- 已落地文件：
  - `docs_refactored/rfc-knowledge-index-refactor-2026-06-14.md`
  - `docs_refactored/README.md`
  - `docs_refactored/INDEX.md`
  - `docs_refactored/compiler/README.md`
  - `docs_refactored/runtime/README.md`
  - `docs_refactored/compiler/frontend/README.md`
  - `docs_refactored/compiler/chip_level_ir/README.md`
  - `docs_refactored/compiler/lowering/README.md`
  - `docs_refactored/compiler/binary_packaging/README.md`
  - `docs_refactored/compiler/cases/README.md`
  - `docs_refactored/runtime/control/README.md`
  - `docs_refactored/runtime/simulator/README.md`
  - `docs_refactored/runtime/workflow/README.md`
  - `docs_refactored/runtime/cases/README.md`
  - `docs_refactored/runtime/debug/README.md`
  - `docs_refactored/knowledge-field-owner.md`
- 后续实现建议追加：`knowledge-map.yaml`、`crosswalk.md`，不删除现有原始文档。

---

## 附：建议的标签词典（后续可复用）

`status`: `current|stable|context|history|draft`  
`topic`: `architecture|instruction|compiler|binary|runtime|cases|tools`  
`audience`: `dev|reader|maintainer|reviewer`  
`evidence`: `source-code|trace|experiment|community`  
`authority_level`: `source_of_truth|design_record|discussion|experiment|historical`

## 11. 知识字段主权表（知识债务治理）

新增 `docs_refactored/knowledge-field-owner.md`（轻量 Markdown 表），用于确保每个关键字段都有权威归属，而不是让多个 RFC 同级博弈：

- `field_name`: `execution_model`
- `truth_doc`: `compiler/notes/env_refactor_chip_level_program.md`
- `context_docs`: `docs_refactored/architecture/isa-execution-model.md`
- `history_docs`: `notes/design/...`, `compiler/notes/archive/...`
- `decided_by`: `code | code+tests`
- `last_reviewed`: `2026-06-14`

这个表能把“唯一真相”从口头约定变成可检索记录，减少新人与异步协作成本。

### 11.1 约束增强（建议立即执行）

- 同一 `knowledge_field` 在同一时间窗口内原则上只允许 `1~2` 条 `source_of_truth`。
- 新增或修改该字段定义时，必须给出 `supersedes / superseded_by` 关系。
- `source_of_truth` 必须有“代码对应关系”（哪一层代码实现了该定义），并在后续评审时复核一致性。
