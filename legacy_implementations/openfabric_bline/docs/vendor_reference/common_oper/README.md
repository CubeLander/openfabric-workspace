# Common Oper：CSV 到 Vendor Binary 的证据链

这里是当前最重要的 vendor evidence 子树：它解释 `common_oper` 如何把 CSV、task、
subtask、exeBlock、inst、resource state 打成 SimICT 可消费的二进制。

如果要改动或复刻 `common_oper` 行为，先看上层审计索引：
[`../original_materials_audit.md`](../original_materials_audit.md)。这里的源码事实必须和
原始 Office 文档、OpenFabric reference note、compiler owner/check 四者对齐，不能只靠
一段 remote log 猜 ABI。

## 文档

- [csv-to-binary-pipeline.md](csv-to-binary-pipeline.md)：CSV 到 binary 的主链路。
- [task-creation-generategraph-chain.md](task-creation-generategraph-chain.md)：task_create / GenerateGraph 证据。
- [subtask-graph-compile-chain.md](subtask-graph-compile-chain.md)：subtask graph 编译链路。
- [binary-artifact-generation-pipeline.md](binary-artifact-generation-pipeline.md)：binary artifact 生成路径。
- [vendor-assembler-composition-rules.md](vendor-assembler-composition-rules.md)：从甲方原始
  `build_app` / `common_oper` 源码重新提取的输入包、CSV、graph、resource、COPY、exeBlock
  拼装规则；B-line `VendorAssemblerInputBundle` 的源码依据。
- [dfu3500-gemm-binary-replay.md](dfu3500-gemm-binary-replay.md)：GEMM binary replay、TaskResource、CBUF diff 解释。
- [openfabric-vs-vendor-compile-flow-report.md](openfabric-vs-vendor-compile-flow-report.md)：OpenFabric 与甲方原始 GEMM 编译流程的综合差异报告。
- [dfu3500-hardware-constraints-from-vendor-algorithms.md](dfu3500-hardware-constraints-from-vendor-algorithms.md)：从 vendor 算法反推 DFU3500 硬件约束和 compiler 标准。
- [operand-resource-and-route-audit.md](operand-resource-and-route-audit.md)：`inst_map_common` / `inst_blk_map` 中 PE 坐标、operand offset、COPY/COPYT endpoint ownership 的源码审计。
- [source-fingerprint-index.md](source-fingerprint-index.md)：vendor source fingerprints、文件角色、相关 binary audit notes/docs 的入口索引；这是 vendor evidence，不是 OpenFabric 设计真相。

## 当前已知关键事实

- `Task_Resource` / `inst_blk_map.cpp` 会继续改写 CSV 阶段已经生成的 `inst_t` 字段。
- `fill_copy_inst` 会根据 source/destination PE patch COPY/COPYT 的接收端操作数。
- `ORDER` 分支下存在确定性的 PE operand / tensor pseudo operand 分配算法。
- CBUF/MICC 的文件尺寸、record size、task/subtask/instance index space 必须与 DFU3500
  legacy profile 对齐。

OpenFabric 的 binary serializer 不应该重新发明这些事实；它应该消费已经明确的 VendorABI
和 task resource replay 结果。
