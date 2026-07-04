# 仓库知识归类与整理计划（非代码改动版）

## 1. 当前知识分布（简要盘点）

我先按“目录+文件名语义”做了快速盘点，先给一个客观图：

- `docs/`：110 个 md，属于“对外阅读主干”
  - `docs/instruction-set/`：86（占比最高）
  - `docs/architecture/`：10
  - `docs_refactored/compiler/design/`：3
  - `docs/vendor/`：1
- `the old compiler notes tree`：66 个 md（主要是工程实现演进记录）
  - `archive/`：51（历史里程碑/路线汇总）
  - `refactor/`：11（当前改造进行中或接力文档）
  - `enhancements/`：1（最近新增改造建议）
  - `log10max/`：1
  - 根文件：2（含 `vendor_abi_dependency_granularity.md` 与 `env_refactor_chip_level_program.md`）
- `notes/`：21 个 md（横向观察/实验/案例）
- `docs/compiler/binary_packaging/research_notes/archive/legacy_drafts/`：binary/runtime 旧草稿归档
- `simict3500final/`：11 个 md（legacy 工作流和源码环境手册）

## 2. 现存知识碎片化症状

1. **同一主题跨目录重复**
   - 例如二进制制品、编译链、vendor 打包、runtime 工作流相关内容同时在 `docs`、`notes`、`the old compiler notes tree`、`drafts`、`simict3500final` 出现。
2. **“历史”与“当前决策”混在一起**
   - `the old compiler notes tree` 下 `archive` 和 `refactor` 都有大量里程碑性内容，但缺少统一“有效性状态”标注。
3. **文件命名与粒度不统一**
   - 有不少 `stage-report-*`、`rfc-*`、`rfc*`、`todo-*`，以及 `notes/` 下的一次性长文，读者很难第一眼判断优先级。
4. **主题入口不统一**
   - 当前 `instruction-set` 在 `docs` 已较完整；`notes`/`drafts` 里也有独立抽取（如执行模型重建），未统一回链。

## 3. 建议的知识分类体系（先“聚合”不先“搬迁”）

### A. 架构抽象层（Architecture & 抽象）
- 目标：回答“这套系统怎么运转”。
- 收口位置：
  - `docs/architecture/*`
  - `docs_refactored/compiler/design/*`
  - `notes/design/*`（若仍需要保留历史观点）
  - `notes/onchip_memory_system_*`, `notes/internal_team_architecture_observation.md`

### B. 指令集与语义层（Instruction Set & 语义）
- 目标：回答“算子最终怎么落到硬件指令语义”。
- 收口位置：
  - `docs/instruction-set/*`
  - `notes/isa_and_execution_model_reconstruction.md`（作为 reconstruction 补充）

### C. 编译器中间表示与抽象降链（Compiler IR & Pass）
- 目标：回答“从 Tensor 到 Tile 到 Vendor 的层次边界在哪”。
- 收口位置：
  - `compiler/notes/refactor/*`（当前进展）
  - `docs/compiler/binary_packaging/research_notes/enhancements/*`（当前计划）
  - `compiler/notes/env_refactor_chip_level_program.md`
  - `docs/compiler/binary_packaging/research_notes/archive/vendor_abi_dependency_granularity.md`
  - `compiler/notes/archive/*`（作为历史背景，不再用于新任务第一入口）

### D. 二进制协议与打包接口（Binary Protocol & Packaging）
- 目标：回答“CBUF/MICC/Instance/Subtask 等字段如何组装”。
- 收口位置：
  - `docs/03-csv-to-binary-pipeline.md`
  - `notes/binary_artifact_generation_pipeline.md`
  - `docs/compiler/binary_packaging/research_notes/archive/rfc-program-bin-serializer.md`
  - `docs/compiler/binary_packaging/research_notes/archive/stage-report-post-tile-binary-lowering.md`
  - `compiler/notes/archive/stage-report-vendor-*`

### E. Runtime/案例路径层（Runtime & Case/Workflow）
- 目标：回答“怎样从 case 到运行，SimICT 或本地 mock runtime 如何消费产物”。
- 收口位置：
  - `docs/04-riscv-control-and-dpuapi.md`
  - `docs/05-simict-runtime.md`
  - `docs/06-softmax-case-walkthrough.md`
  - `simict3500final/gpdpu/users/risc_nn_riscv/testcase/workflow/*`
  - `docs/compiler/binary_packaging/research_notes/archive/legacy_drafts/testcase_*`

## 4. 执行计划（建议）

### 第一阶段（1 天）：建立“知识目录服务”
1. 新增一个索引入口（不改现有内容）：
   - `docs/compiler/binary_packaging/research_notes/enhancements/knowledge-index.md`（或放在 `notes`/`docs/` 下，先统一）
2. 增加三类标签：`status`（active / stable / archive / draft）、`topic`（architecture/instruction/ir/runtime/binary/protocol）、`audience`（dev/reader/maintainer）。
3. 先做“目录级聚合”，不移动文件，只补交叉引用。

### 第二阶段（2 天）：高价值文档聚合（先做 4 组）
1. **架构主线页**（基于 docs 架构顺序补齐）
   - 新增“统一入口：从抽象到执行到二进制到 runtime”的 reading map。
2. **编译层主线页**
   - 汇总 `refactor + enhancements + vendor_abi_*` 的“当前有效链路”。
3. **指令集主线页**
   - 在 `docs/instruction-set/README.md` 内，明确 `dfu3500-simd` 与 `dfu3500-tensor` 版本边界。
4. **案例链条页**
   - 将 `softmax/gemm` 相关 case 流程链接集中到一页，避免散落。

### 第三阶段（2~3 天）：整理归档策略
1. 将 `compiler/notes/archive` 标注为只读历史，不作为新任务起点。
2. 为每篇 archive 文档补充一行状态行（`superseded by` / `still relevant` / `historical context`）。
3. `drafts` 里的可复用内容入 `notes/design` 或 `compiler/notes/refactor`，原文件保留但改为指向新入口。
4. 建立“知识去重清单”（重复主题 top 文件）：
   - `binary pipeline`
   - `tile 降级路线`
   - `vendor binding/offset/ABI`
   - `runtime workflow`

### 第四阶段（1 天）：验收与发布
1. 文档检索测试：
   - 同一主题 1 分钟内能从一个入口找到 1 个“当前主线”+2 个“背景历史”。
2. 变更边界检查：
   - 不删任何 md，仅新增索引/重定向与必要交叉引用。
3. 输出“知识地图快照”：
   - `topic -> source doc list -> 最近一次更新`，用于后续接力。

## 5. 下一步（如果同意）

我建议先从**不改文件位置**开始，做 1 个轻量版本：
- `docs/compiler/binary_packaging/research_notes/enhancements/2026-06-14_knowledge_index_bootstrap.md`
- 收敛 6~8 个一级入口。
- 用 1~2 页补齐关键主题（架构、IR、二进制、runtime、指令集、case）；
- 然后按上面第四阶段做一次 15 分钟人工导航验证。
