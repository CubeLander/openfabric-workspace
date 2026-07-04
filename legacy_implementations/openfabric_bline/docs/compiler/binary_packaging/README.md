# 二进制打包（Binary Packaging）

关注点：从 `processor tile program` / B-line binding plan 到 vendor
executable component files 的生成侧协议边界。

本目录是 **compiler 生成侧** 文档，不是 runtime binary layout 的唯一真相：

- `docs/compiler/binary_packaging/` 记录 OpenFabric 如何把 IR、placement、
  resource/binding plan 降到 vendor component package。
- `docs/runtime/data/` 记录 runtime 实际消费的 CBUF、MICC、RTL/debug sidecar
  等 binary image layout。
- `docs/vendor_reference/common_oper/` 记录 vendor source 行为与证据来源。

不要在本目录重新定义 runtime ABI；这里应说明 compiler 需要哪些 owner plan、
校验 guard 和 handoff 边界，才能安全地产生 runtime 所需的 image。

## 当前源文件

- [vendor_reference/common_oper/csv-to-binary-pipeline.md](../../vendor_reference/common_oper/csv-to-binary-pipeline.md)
- [vendor_reference/common_oper/binary-artifact-generation-pipeline.md](../../vendor_reference/common_oper/binary-artifact-generation-pipeline.md)
- [docs/compiler/binary_packaging/research_notes/archive/rfc-program-bin-serializer.md](research_notes/archive/rfc-program-bin-serializer.md)
- [docs/compiler/binary_packaging/research_notes/archive/stage-report-post-tile-binary-lowering.md](research_notes/archive/stage-report-post-tile-binary-lowering.md)
- [docs/compiler/binary_packaging/research_notes/archive/2026-06-20_binary_notes_to_docs_reduction_plan.md](research_notes/archive/2026-06-20_binary_notes_to_docs_reduction_plan.md)
- [docs/compiler/binary_packaging/research_notes/binary/2026-06-20_task_print_component_writer_audit.md](research_notes/binary/2026-06-20_task_print_component_writer_audit.md)
- [docs/compiler/binary_packaging/research_notes/binary/2026-06-20_inst_blk_map_resource_owner_audit.md](research_notes/binary/2026-06-20_inst_blk_map_resource_owner_audit.md)
- [docs/compiler/binary_packaging/research_notes/binary/2026-06-20_vendor_struct_layout_audit.md](research_notes/binary/2026-06-20_vendor_struct_layout_audit.md)
- [DFU binary decoder coverage map](decoder_coverage.md)

## 主要决策点

- component/range/subtask/instance 的对齐顺序。
- 地址空间 macro range 与实际 emitted simulator file size 的边界。
- active rows 与 padded capacity rows 的分离。
- schema 稳定性、source fingerprint 和兼容边界。
- runnable package 之前必须触发哪些 compiler-side guard。

## Decoder / Diff Tooling

如果问题已经落到“这个 payload 到底哪几个 byte / field 不对”，先用 decoder：

```text
compiler/tools/decode_dfu_binary.py
compiler/tools/compare_dfu_payloads.py
```

当前覆盖范围和缺口统一维护在 [DFU binary decoder coverage map](decoder_coverage.md)。
它是诊断工具，不是 serializer，也不是 `runtime_runnable=true` 的判定者。

## Runtime Validation Closure

本地 `RUNTIME_READY` 只证明 payload 结构上可运行；算子功能闭环还需要远端
runtime 结束后的 output capture 和 reference comparison。设计入口：

- [RFC: Runtime Output Closure and Reference Validation](research_notes/enhancements/rfc-runtime-output-closure.md)

## B-line Owner Map

| 生成侧事实 | B-line owner |
| --- | --- |
| component file 的 active rows、padded capacity、PE merge order、固定容量大小 | `VendorComponentPlan` |
| PE-local instruction stream、valid instruction filter、LD/CAL/FLOW/ST stage order、block 起始 PC late rebase | `InstructionLayoutPlan` |
| task-scoped PE resource 起点、operand/block/instruction allocation window | `TaskResourceWindow` |
| vendor `start_map_task` / `end_map_task` 顺序重放：先 operand allocation，再 block id，再 COPY patch，再 capacity count | `TaskResourceReplay` |
| COPY/COPYT/LCOPY endpoint patching；producer row 由 source action 拥有，destination PE/block/operand 由 consumer owner 提供 | `RouteEndpointBinding` |
| `iter_exe_cond` / `flow_ack` 这类 base-address selector 字段的来源与 per-op assignment | `BaseAddressBindingPlan` |
| active task/subtask count、launch metadata、task/subtask successor/start/end flags 与 component rows 的一致性 | `RuntimeControlPlan` guards |

这些 owner 只消费上一层 plan 并产出下一层 plan；不要在 frontend op 调用时直接回写
PE program、task row、subtask row 或 vendor binary state。

## Runnable Package Guard 原则

一个 package 只有在生成侧 guard 全部通过后，才能标记为
`runtime_runnable=true`：

- active task/subtask 数量来自 active package rows，不能从 padded capacity 或
  `taskEnable.bin` 推断。
- runtime launch task count 必须等于 active task count；padded rows 只是容量，
  不能成为 runtime work。
- 每条 active subtask chain 必须有唯一 start/end，并且 successor 链完整、无尾部
  bogus successor。
- 每个 active exeBlock row 必须已经 late-stamp `task_idx` / `subtask_idx`，stage PC
  与 PE-local instruction stream 重新基准化完成。
- 每条 route/copy action 必须能绑定到 destination action、PE-local block 和 receiver
  operand index；COPY patching 必须晚于 receiver operand allocation。
- per-PE instruction/block/operand usage 必须先过 DFU3500 profile capacity guard，再
  写 component file。
- component file size 必须匹配当前 vendor profile 的固定容量；CBUF address-space
  macro range 和实际 emitted `cbuf_file.bin` size 需要显式区分。
- runtime control plan、component rows、resource replay、base-address binding 必须来自
  同一组 plan，禁止手工只补一层 metadata 后声称 runnable。

对应知识字段：
- `binary_packaging`
