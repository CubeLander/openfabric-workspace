# docs 内容盘点

调查日期：2026-06-15（更新于 2026-06-16）

这份盘点记录 `docs/` 当前已经整理出的知识结构、主要内容、阅读路线和继续收敛点。它不是新的 source of truth，而是给后续维护者快速定位材料用的工作索引。

## 1. 总体定位

`docs/` 当前已经从"空索引平面"演进成一套混合知识库：

- 顶层索引：说明双主线制度、知识字段归属和验收规则。
- 架构层：收口 shared 知识，包括内存系统、执行模型、PE mesh、指令语义。
- 编译主线：主要还是索引和设计摘录，很多真相文档仍在 `the old compiler notes tree` 旧树。
- 运行主线：已经形成较完整的 control/data/workflow/debug 结构。
- vendor reference：沉淀甲方原始工具链、SimICT、CSV 到 binary、softmax/GEMM case 等证据材料。
- instruction-set：包含 DFU3500 SIMD/Tensor 指令材料的文本化抽取，体量最大。

当前目录约包含：

| 类型 | 数量 |
|---|---:|
| Markdown | 161 |
| OCR raw txt | 97 |
| JSONL | 2 |
| CSV | 2 |
| Markdown 总行数 | 约 26k |

按一级目录粗略分布：

| 目录 | 文件数 | 角色 |
|---|---:|---|
| `architecture/` | 212 | shared 架构事实、指令集抽取、执行模型 |
| `compiler/` | 21 | 编译主线索引、设计摘录、debug trace 设计 |
| `runtime/` | 16 | runtime 控制面、数据面、workflow、debug |
| `vendor_reference/` | 29 | 甲方工具链和 case 工作流证据 |
| 顶层文件 | 5 | 总入口、RFC、知识字段归属表 |

## 2. 顶层制度

顶层文件负责定义这套文档库的治理方式：

- [README.md](README.md)：说明 `docs/` 是可导航知识树，不是简单搬库。
- [INDEX.md](INDEX.md)：总入口，按 architecture/compiler/runtime 分流。
- [rfc-knowledge-index-refactor-2026-06-14.md](rfc-knowledge-index-refactor-2026-06-14.md)：解释为什么建立统一索引、双主线、知识主权链。
- [knowledge-field-owner.md](knowledge-field-owner.md)：登记 `execution_model`、`memory_model`、`binary_packaging`、`runtime_contract` 等字段的 `source_of_truth`。

关键制度是：

```text
Markdown
  -> Knowledge Item
  -> Knowledge Field
  -> source_of_truth / context / history
```

也就是说，文档是否“当前有效”不靠文件新旧判断，而靠 `source_of_truth`、`supersedes`、`authority_level` 和 `knowledge_fields`。

需要注意：`knowledge-field-owner.md` 中仍有多条 truth_doc 指向旧路径，例如 `docs/`、`the old compiler notes tree`。这说明知识主权链已经设计出来，但还没有完全迁移到 `docs/` 内部。

## 3. Architecture

入口：[architecture/README.md](architecture/README.md)

架构层负责 shared 知识，不属于 compiler 或 runtime 私有。它的主图是：

```text
RISC-V control program
  -> MMIO / DMA
  -> DRAM image
  -> CBUF / MICC / SPM
  -> task / subtask / instance
  -> GRAPH_NODE / exeBlock
  -> PE mesh
  -> PE-local operand RAM + instruction memory
  -> LD / CAL / FLOW / ST execution
```

当前最核心的架构文档：

| 文档 | 内容 |
|---|---|
| [storage-hierarchy-overview.md](architecture/soc-system/storage-hierarchy-overview.md) | DRAM、SPM、CBUF/MICC、operand RAM 的层次和职责 |
| [cbuf-micc-config-channel.md](architecture/soc-system/cbuf-micc-config-channel.md) | CBUF/MICC 指令和任务配置通道 |
| [data-pathway.md](architecture/soc-system/data-pathway.md) | SPM 与 operand RAM 数据通路 |
| [device-boot-sequence.md](architecture/soc-system/device-boot-sequence.md) | Device 启动流程 |
| [task-subtask-instance-runtime-model.md](architecture/runtime-model/task-subtask-instance-runtime-model.md) | task/subtask/instance 与 graph/exeBlock 的运行时模型 |
| [pe-microarchitecture-execution-model.md](architecture/pe-microarchitecture/pe-microarchitecture-execution-model.md) | 单 PE 内部 `exeBlock -> LD/CAL/FLOW/ST` 执行模型 |
| [pe-mesh-and-task-model.md](architecture/pe-microarchitecture/pe-mesh-and-task-model.md) | 4x4 PE mesh、任务分片和拓扑事实 |
| [pe-register-architecture.md](architecture/pe-microarchitecture/pe-register-architecture.md) | mask、RX/LRX、operand slots、PE-local index |
| [instruction-format-and-rtl-packing.md](architecture/instruction-encoding/instruction-format-and-rtl-packing.md) | `inst_t` 与 RTL packing 关系 |
| [inst-t-to-physical-resources.md](architecture/instruction-encoding/inst-t-to-physical-resources.md) | `inst_t` 字段如何落到 PE 物理资源 |
| [simd-lane-interpretation.md](architecture/pe-microarchitecture/simd-lane-interpretation.md) | SIMD lane、mask、RX/LRX 等解释模型 |
| [gemm-template-fusion-task0-dataflow.md](architecture/gemm-case-study/gemm-template-fusion-task0-dataflow.md) | GEMM template fusion task0 的数据流 |
| [hmmal-rx-accumulator-binding.md](architecture/gemm-case-study/hmmal-rx-accumulator-binding.md) | HMMAL / RX / tensor tmp register 绑定 |

架构层当前已经比较成体系，尤其是内存、执行、PE stage 的边界很清楚：

```text
数据线:
DRAM <-> DMA <-> SPM <-> PE operand RAM <-> compute

指令/配置线:
DRAM cbuf_file.bin/micc_file.bin
  -> DMA
  -> CBUF/MICC
  -> MICC/PE config and inst distribution
  -> PE inst_list / exeBlock control
```

## 4. Instruction Set

入口：[architecture/instruction-set/README.md](architecture/instruction-set/README.md)

这是架构层下面最大的材料库，来自甲方 Office 原始资料的文本抽取。

主要分两类：

- [dfu3500-simd/README.md](architecture/instruction-set/dfu3500-simd/README.md)
- [dfu3500-tensor/README.md](architecture/instruction-set/dfu3500-tensor/README.md)

SIMD 子树包含：

- `xlsx/Sheet1.csv`、`xlsx/Sheet2.csv`：表格抽取。
- `instruction_cards.jsonl`：每行一个 mnemonic，适合 agent 检索。
- `instruction_cards.md`：人类可读指令卡片。
- `OPERAND_LANE_MODEL.md`：SIMD128、1024-bit chunk、4096-bit operand 的 lane 解释。
- `UNCLEAR_SEMANTICS_BACKLOG.md`：暂不阻塞的语义疑点。
- `docx/instruction_sections/`：按 mnemonic 切分的 docx 原文段落。
- `docx/media_ocr/`：图片 OCR 原文和索引。
- `OCR_DERIVED_NOTES.md`：高信号图片 OCR 的整理推断。

Tensor 子树的关键结论是：

```text
HMMAL 属于 tensor 指令，不属于 SIMD 指令。
HMMAL imm[9:7] 选择 dst tmp0..tmp7。
RXINT/TRCTT 在普通 operand 和 tensor tmp state 之间搬运/转换数据。
```

使用建议：

1. 查具体 mnemonic 时先读 `instruction_cards.jsonl` 或 `instruction_cards.md`。
2. 查 lane/operand 宽度时先读 `OPERAND_LANE_MODEL.md`。
3. 查原始出处时再读 `docx/instruction_sections/<MNEMONIC>.md`。
4. 不要一次性把整份 docx Markdown 或全部 OCR raw 放进上下文。

## 5. Compiler

入口：[compiler/README.md](compiler/README.md)

编译主线回答“上层算子图如何变成 runtime 可消费的交付物”。当前目录分为：

| 子目录 | 关注点 |
|---|---|
| [frontend/README.md](compiler/frontend/README.md) | 算子语义、placement、DTensor 与 SRAM 声明边界 |
| [chip_level_ir/README.md](compiler/chip_level_ir/README.md) | chip-level tensor/program 的图层边界和状态模型 |
| [lowering/README.md](compiler/lowering/README.md) | chip-level 到 tile/physical program 的转换 |
| [binary_packaging/README.md](compiler/binary_packaging/README.md) | processor tile program 到 vendor executable 的协议边界 |
| [design/README.md](compiler/design/README.md) | 旧设计材料中仍有价值的思想摘录 |
| [cases/README.md](compiler/cases/README.md) | 编译案例入口，目前内容较少 |

当前 compiler 子树的特点：

- README 结构已经搭好，但很多当前真相仍指向 `compiler/notes/refactor/*` 和 `compiler/notes/env_refactor_chip_level_program.md`。
- `design/` 不是 source of truth，而是保留 DeviceMesh、SUMMA、tile residency、LocalPhase/CollectivePhase 等设计思想。
- 新增设计文档中较重要的是 [dfu-backend-lowering-principles.md](compiler/design/dfu-backend-lowering-principles.md)，它明确后端应该分成：

```text
TileAction / RouteAction
  -> DFUAssemblyRecord (symbolic)
  -> DFUBinaryInstruction (binary)
```

并强调 task/subtask/instance packing 是独立 pass，binary encoder 只做窄编码。

与 AGENTS.md 当前方向最相关的 compiler 结论：

- 前端只维护 chip-level tensor program / DTensor program。
- DTensor 不应凭空声明为输入，应通过 chip-level `load` 从 SRAM tensor 读入。
- 输出应先声明 output SRAM tensor，再通过 `store` 写回。
- op-time 不应直接维护 PE / Tensor Core / vendor binary program。
- 降层应在 `env.generate()` 之后通过显式 pipeline 完成。

## 6. Runtime

入口：[runtime/README.md](runtime/README.md)

runtime 主线回答“编译器产物进入 runtime 后如何装载、触发、执行和回收”。当前是整理最完整的一条主线。

子树如下：

| 子目录 | 内容 |
|---|---|
| [control/README.md](runtime/control/README.md) | task/subtask/exeblock/instance、MICC doorbell、RISC-V 控制时序 |
| [data/README.md](runtime/data/README.md) | CBUF/MICC/RTL/messages 字节布局 |
| [workflow/README.md](runtime/workflow/README.md) | case/bundle/config 生成和 replay 路径 |
| [simulator/README.md](runtime/simulator/README.md) | SimICT 与 local mock runtime 一致性 |
| [debug/README.md](runtime/debug/README.md) | 手写/生成路径对比、结果核验 |
| [cases/README.md](runtime/cases/README.md) | runtime case 入口，目前内容较少 |

runtime 当前固定执行链：

```text
编译器/离线生成
  -> insts_file.bin
  -> exeblock_conf_info_file.bin
  -> instance_conf_info_file.bin
  -> tasks_conf_info_file.bin
  -> subtasks_conf_info_file.bin
  -> cbuf_file.bin / micc_file.bin
  -> RISC-V guest 通过 MMIO 发起执行
  -> MICC doorbell 触发 device kernel
  -> runtime/simulator 推进 task/subtask/PE
  -> 结果写回并校验
```

最重要的 control 结论：

- `is_exe_start` / `is_exe_end` 是图结构标记，不是启动信号。
- 真正启动 device 的是 `DPU_Kernel_Start()` 写 `MICC_BUFx_START = 1`。
- `instance` 是运行时地址环境，核心是 `base_addr[4]`。
- `instances_conf_mem_based_addr = m_instance_start_idx * sizeof(instance_conf_info_t)`。

data 子树固定的二进制布局：

```text
cbuf_file.bin = insts_file.bin
              + exeblock_conf_info_file.bin
              + instance_conf_info_file.bin

micc_file.bin = tasks_conf_info_file.bin
              + subtasks_conf_info_file.bin
```

关键尺寸：

| 文件 | 固定尺寸 |
|---|---:|
| `insts_file.bin` | 21,168,128 B |
| `exeblock_conf_info_file.bin` | 266,240 B |
| `instance_conf_info_file.bin` | 2,097,152 B |
| `cbuf_file.bin` | 23,531,520 B |
| `tasks_conf_info_file.bin` | 480 B |
| `subtasks_conf_info_file.bin` | 8,522,496 B |
| `micc_file.bin` | 8,522,976 B |

## 7. Vendor Reference

入口：[vendor_reference/README.md](vendor_reference/README.md)

这部分不是 OpenFabric compiler 文档，而是甲方原始工具链和 bring-up 环境的证据库。它的价值是帮助 OpenFabric 做 binary-compatible output consumer。

推荐阅读顺序：

1. [overview/from-torch-view.md](vendor_reference/overview/from-torch-view.md)
2. [overview/end-to-end-flow.md](vendor_reference/overview/end-to-end-flow.md)
3. [case_authoring/operator-case-development.md](vendor_reference/case_authoring/operator-case-development.md)
4. [common_oper/csv-to-binary-pipeline.md](vendor_reference/common_oper/csv-to-binary-pipeline.md)
5. [runtime_evidence/riscv-control-and-dpuapi.md](vendor_reference/runtime_evidence/riscv-control-and-dpuapi.md)
6. [runtime_evidence/simict-runtime.md](vendor_reference/runtime_evidence/simict-runtime.md)
7. [cases/softmax/softmax-case-walkthrough.md](vendor_reference/cases/softmax/softmax-case-walkthrough.md)
8. [case_authoring/manual-vs-generated.md](vendor_reference/case_authoring/manual-vs-generated.md)
9. [runtime/simulator/local-mock-runtime.md](runtime/simulator/local-mock-runtime.md)
10. [cases/gemm/gemm-template-fusion-task-reuse.md](vendor_reference/cases/gemm/gemm-template-fusion-task-reuse.md)
11. [common_oper/dfu3500-gemm-binary-replay.md](vendor_reference/common_oper/dfu3500-gemm-binary-replay.md)
12. [common_oper/openfabric-vs-vendor-compile-flow-report.md](vendor_reference/common_oper/openfabric-vs-vendor-compile-flow-report.md)
13. [common_oper/dfu3500-hardware-constraints-from-vendor-algorithms.md](vendor_reference/common_oper/dfu3500-hardware-constraints-from-vendor-algorithms.md)

vendor reference 当前覆盖的几条证据链：

- `overview/`：从 PyTorch mental model 到端到端 vendor workflow。
- `case_authoring/`：case 手写/生成边界和模板前端链路。
- `common_oper/`：CSV、task/subtask、exeBlock、inst、binary artifact 生成证据。
- `runtime_evidence/`：RISC-V 控制程序、DpuAPI、SimICT runtime 证据。
- `cases/`：GEMM / softmax 等具体 case 调查。
- `remote_ops/`：arch-13 与远程执行环境证据。
- 从 `run_app_riscv.sh` 到 SimICT runtime 的端到端流程。
- CSV 生成、common_oper 汇编、graph extend、inst/block map、task_print 打包。
- RISC-V guest 程序如何加载 `cbuf_file.bin`、`micc_file.bin` 和 `input_data.bin`。
- softmax_1 当前真实工作流。
- elementwise template 的前端生成链。
- GEMM template fusion 的 task 复用和并发数据流。
- 手写文件、生成文件、闭源/外部预构建文件清单。

这部分应作为证据和兼容目标，不应反向污染 OpenFabric 的新 compiler 分层。

## 8. 建议阅读路线

### 8.1 先建立系统全貌

1. [README.md](README.md)
2. [INDEX.md](INDEX.md)
3. [architecture/README.md](architecture/README.md)
4. [vendor_reference/overview/end-to-end-flow.md](vendor_reference/overview/end-to-end-flow.md)
5. [runtime/control/README.md](runtime/control/README.md)
6. [runtime/data/README.md](runtime/data/README.md)

### 8.2 查 runtime / simulator 交付链路

1. [vendor_reference/runtime_evidence/riscv-control-and-dpuapi.md](vendor_reference/runtime_evidence/riscv-control-and-dpuapi.md)
2. [runtime/control/README.md](runtime/control/README.md)
3. [runtime/data/cbuf.md](runtime/data/cbuf.md)
4. [runtime/data/micc.md](runtime/data/micc.md)
5. [vendor_reference/runtime_evidence/simict-runtime.md](vendor_reference/runtime_evidence/simict-runtime.md)
6. [runtime/workflow/README.md](runtime/workflow/README.md)

### 8.3 查 compiler 分层和后端方向

1. [compiler/README.md](compiler/README.md)
2. [compiler/frontend/README.md](compiler/frontend/README.md)
3. [compiler/chip_level_ir/README.md](compiler/chip_level_ir/README.md)
4. [compiler/lowering/README.md](compiler/lowering/README.md)
5. [compiler/binary_packaging/README.md](compiler/binary_packaging/README.md)
6. [compiler/design/dfu-backend-lowering-principles.md](compiler/design/dfu-backend-lowering-principles.md)

然后回到旧树中的 source_of_truth：

- `compiler/notes/env_refactor_chip_level_program.md`
- `docs/compiler/binary_packaging/research_notes/archive/rfc-dfu-graph-lowering-from-processor-tile.md`
- `docs/compiler/binary_packaging/research_notes/archive/rfc-tileloop-to-vendor-lowering-execution-plan.md`
- `docs/compiler/binary_packaging/research_notes/archive/rfc-program-bin-serializer.md`

### 8.4 查指令语义

1. [architecture/instruction-set/README.md](architecture/instruction-set/README.md)
2. [architecture/instruction-set/dfu3500-simd/README.md](architecture/instruction-set/dfu3500-simd/README.md)
3. 具体 mnemonic 先查 `instruction_cards.jsonl` 或 `instruction_cards.md`
4. lane/operand 问题查 `OPERAND_LANE_MODEL.md`
5. tensor HMMAL/RXINT/TRCTT 问题查 [architecture/instruction-set/dfu3500-tensor/README.md](architecture/instruction-set/dfu3500-tensor/README.md)

## 9. 当前收敛度评估

| 区域 | 收敛度 | 说明 |
|---|---|---|
| Runtime control | 高 | 控制时序、doorbell、instance base 语义已清楚 |
| Runtime data | 高 | CBUF/MICC/RTL 布局已有字节级文档 |
| Architecture memory/execution | 中高 | 大图清楚，部分硬件事实仍需和代码常量持续对齐 |
| Instruction set | 中 | 抽取完整，但语义仍有 OCR 和 unclear backlog |
| Vendor reference | 中高 | 证据链丰富，但需要避免变成 OpenFabric 当前设计主线 |
| Compiler frontend/chip IR | 中低 | 入口已搭好，source_of_truth 多在旧树 |
| Compiler lowering/packaging | 中 | 原则清楚，但 current path 仍散在 notes/refactor 与 vendor_reference |
| Cases | 低 | compiler/runtime cases 目录目前主要是占位入口 |

## 10. 待整理点

优先级较高：

1. 补齐 `knowledge-map.yaml`，让 `knowledge-field-owner.md` 里的表格可机器校验。
2. 把 `knowledge-field-owner.md` 中仍指向旧 `docs/`、`the old compiler notes tree` 的 truth_doc 做一次迁移或显式 crosswalk。
3. 为 compiler 主线建立 1 到 3 篇真正的 current 根文档，减少读者跳回旧 notes 的次数。
4. 明确 `vendor_reference/*` 的 authority_level，避免 vendor 工具链现状被误读成 OpenFabric 新架构设计。
5. 给 `runtime/cases/` 和 `compiler/cases/` 补 softmax/GEMM 两个导航页，把 case 证据与主线字段绑定起来。

优先级中等：

1. 建立 `crosswalk.md`，记录旧路径到新路径的映射。
2. 为 instruction-set 增加 mnemonic 索引表，链接到 instruction_cards 和 docx sections。
3. 把 `runtime_workflow` 加入 `knowledge-field-owner.md`，目前多个 README 已引用这个待定字段。
4. 对长文档补 front matter：`status`、`authority_level`、`knowledge_fields`、`last_reviewed`、`supersedes`。
5. 给 vendor binary layout 文档增加代码常量核验脚本入口，降低尺寸和 offset 漂移风险。

## 11. 一句话结论

`docs/` 已经能作为 OpenFabric 当前 DFU-first 工作的主要知识入口使用；runtime 和 architecture 两条线较成熟，compiler 主线还处在"索引已立、真相未完全迁入"的阶段。后续整理的重心应放在 compiler current path、知识字段机器索引、旧路径 crosswalk，以及 case 导航收口上。
