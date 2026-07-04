# OpenFabric 文档统一索引（总层）

`docs/` 的目标不是搬库，是把散落文档整理成**可导航**的知识树。

目录采用"总览 -> 两条主线 -> 子目录"的结构：

- [INDEX](INDEX.md)：全局入口与验收规则
- [Architecture 总览](architecture/README.md)：shared 知识收口页
- [Compiler 主线](compiler/README.md)：从前端图到二进制/打包产物
- [Runtime 主线](runtime/README.md)：从 bundle 到 simulator/芯片执行
- [Runtime 控制面](runtime/control/README.md)：task / subtask / exeblock / instance 与 MICC 启动链路
- [Runtime 数据面](runtime/data/README.md)：二进制镜像、字段布局与内存映射
- [Knowledge Field Owner](knowledge-field-owner.md)：每个关键字段的 `source_of_truth`

## 设计约束（核心）

- 两条主线并行，但不混在一起：
  - compiler：回答"编译器怎么运行"
  - runtime：回答"程序怎么在 simulator/芯片上跑"
- `shared` 领域（如执行语义、拓扑、内存模型、指令语义）会先回到 [Architecture 总览](architecture/README.md)，再分流到具体主线入口。
- 真相判定不是按"最近更新"排序，而是按 `source_of_truth` + `supersedes` 链 + `authority_level`。

## 目录骨架

```text
docs/
  README.md
  INDEX.md
  architecture/
    soc-system/
    pe-microarchitecture/
    runtime-model/
    instruction-encoding/
    gemm-case-study/
    instruction-set/
  knowledge-field-owner.md
  compiler/
    README.md
    frontend/
    chip_level_ir/
    lowering/
    binary_packaging/
    cases/
  runtime/
    README.md
    control/
    data/
    simulator/
    workflow/
    cases/
    debug/
  vendor_reference/
    README.md
    overview/
    case_authoring/
    common_oper/
    runtime_evidence/
    cases/
    remote_ops/
```

每个子目录都应保持 README 说明"该层为什么存在、先读什么、对应哪些知识字段"。

## B 线二进制施工总入口

B 线 agent 如果要改 `stream_compiler`、template binding、runtime package、
CBUF/MICC serializer、RISC-V validation bundle，先不要直接从源码猜 ABI。先按
下面的坑位路牌定位资料，再动代码。

总原则：

```text
runtime bytes 怎么长        -> docs/runtime/data
compiler 应该怎么生成      -> docs/compiler/binary_packaging
vendor 为什么这么做        -> docs/vendor_reference/common_oper
opcode / operand 怎么解释  -> docs/architecture/instruction-set
runtime 谁负责发车         -> docs/vendor_reference/runtime_evidence
```

### 按坑位找路

| 你遇到的症状 / 要改的东西 | 先看哪里 | 为什么 |
| --- | --- | --- |
| 想用工具判断 payload 好坏、查字段偏移、比较 `cbuf_file.bin` / `micc_file.bin` 差异 | [DFU binary decoder coverage](compiler/binary_packaging/decoder_coverage.md)；`compiler/tools/decode_dfu_binary.py`；`compiler/tools/compare_dfu_payloads.py` | decoder 是二进制显微镜：能解释字节、抓 size/control mismatch，但不能替代 serializer 或 runtime runnable verifier。 |
| `cbuf_file.bin` / `micc_file.bin` 尺寸、hash、字段偏移不对 | [Runtime 数据面](runtime/data/README.md)；[CBUF](runtime/data/cbuf.md)；[MICC](runtime/data/micc.md) | 这里是 runtime-consumed binary layout 的入口，不要从 compiler plan 反推字节布局。 |
| `data_inst_replace.bin`、`instEnable.bin`、`taskEnable.bin` 看起来像 runtime 输入 | [辅助兼容产物](runtime/data/auxiliary-artifacts.md) | 这些目前是 optional sidecar / RTL-debug collateral，不是 active task 或 readiness 的 truth。 |
| 1 个 task 被跑成 4 个 task，或 padded rows 被当成 active work | [二进制打包 guard](compiler/binary_packaging/README.md)；[MICC](runtime/data/micc.md) | active rows 和 padded capacity 必须分离；runtime launch count 只能来自 active package/control plan。 |
| subtask 退不出、successor/start/end flag 怀疑不对 | [二进制打包 guard](compiler/binary_packaging/README.md)；[common_oper evidence](vendor_reference/common_oper/README.md) | task/subtask chain 是控制面元数据，不要靠手填补洞；需要和 component rows 同源。 |
| `exeblock_conf_info.bin`、block PC、stage PC、PE-local 指令流错位 | [二进制打包](compiler/binary_packaging/README.md)；[source fingerprint index](vendor_reference/common_oper/source-fingerprint-index.md) | block 起始 PC 需要 late rebase；vendor writer 和 stage split 是证据源。 |
| COPY / COPYT / LCOPY endpoint、receiver operand index 或 route patch 不对 | [二进制打包 owner map](compiler/binary_packaging/README.md)；[operand-resource-and-route-audit](vendor_reference/common_oper/operand-resource-and-route-audit.md) | destination operand/block 属于 receiver/consumer owner，不能由 sender action 本地猜。 |
| operand offset、block id、instruction count、TaskResource replay 顺序不稳 | [二进制打包 owner map](compiler/binary_packaging/README.md)；[source fingerprint index](vendor_reference/common_oper/source-fingerprint-index.md) | vendor 顺序是先资源窗口/operand allocation，再 block id，再 COPY patch，再 capacity count。 |
| `iter_exe_cond`、`flow_ack`、base address selector 字段不知道归谁管 | [二进制打包 owner map](compiler/binary_packaging/README.md)；[instruction-set notes](architecture/instruction-set/dfu3500-simd/README.md) | 这些字段是 base-address / execution condition 相关绑定，必须进 typed binding plan，不能散落在模板里。 |
| `FMAX`、`FLOG2`、`FEXP2`、`FRCP` family、operand lane 或 RTL 投影搞混 | [DFU3500 SIMD 指令集](architecture/instruction-set/dfu3500-simd/README.md)；[MEMORY_AND_TEMPLATE_EXECUTION_NOTES](architecture/instruction-set/dfu3500-simd/MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md) | SimICT `inst_t` 行和 RTL narrow projection 不是同一个层次；不要把 RTL fold 规则误当 simulator opcode。 |
| `LegacyInst`、`legacy_template_compat`、template row binding 不清楚 | [binary research notes](compiler/binary_packaging/research_notes/README.md)；[`rfc-core-functional-template-binding`](compiler/binary_packaging/research_notes/enhancements/rfc-core-functional-template-binding.md)；[`rfc-b-line-template-op-binary-plan`](compiler/binary_packaging/research_notes/enhancements/rfc-b-line-template-op-binary-plan.md) | 模板绑定是 B 线可执行语义到 vendor instruction row 的桥，不要藏在 GEMM 名字或 structural smoke 里。 |
| RISC-V control、DMA、DPU API、runtime 谁启动 kernel 不清楚 | [runtime_evidence](vendor_reference/runtime_evidence/README.md) | RISC-V control 只负责加载、DMA、start/wait/finish；不生成 PE/device instructions。 |
| 不确定某个 vendor 源文件是不是本次审计版本 | [source fingerprint index](vendor_reference/common_oper/source-fingerprint-index.md) | 二进制接口不能靠“我记得”；先查 source root、hash、文件角色和 evidence boundary。fingerprint 是证据，不是 OpenFabric 设计真相。 |
| 想知道 A 线为什么痛、哪些泥不能带进 B 线 | [二进制打包](compiler/binary_packaging/README.md)；`docs/compiler/binary_packaging/research_notes/binary/2026-06-20_a_line_pain_retrospective.md` | A 线踩过 task count、template、memory layout、manual ABI metadata 的坑；B 线要用 typed owner/guard 拦住。 |

### B 线写代码前的最低阅读包

如果你是新来的 B 线施工 agent，至少读完这些再碰 binary/runtime 相关代码：

1. [docs/compiler/binary_packaging/README.md](compiler/binary_packaging/README.md)
2. [docs/compiler/binary_packaging/decoder_coverage.md](compiler/binary_packaging/decoder_coverage.md)
3. [docs/runtime/data/README.md](runtime/data/README.md)
4. [docs/runtime/control/README.md](runtime/control/README.md)
5. [docs/vendor_reference/common_oper/source-fingerprint-index.md](vendor_reference/common_oper/source-fingerprint-index.md)
6. [docs/architecture/instruction-set/dfu3500-simd/README.md](architecture/instruction-set/dfu3500-simd/README.md)
7. [docs/vendor_reference/runtime_evidence/README.md](vendor_reference/runtime_evidence/README.md)

如果你的改动会让 `runtime_runnable=true`，还必须能回答：

```text
active rows 从哪里来？
padded rows 为什么没有变成 runtime work？
每个 route endpoint 谁拥有？
每个 PE-local PC 是否已经 rebase？
runtime control plan 与 component rows 是否同源？
CBUF/MICC 主镜像和 optional sidecar 是否分清？
```

答不上来就先别标 runnable。这里不是胆小，是我们已经用 A 线的痛买过票了。
