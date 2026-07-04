# Runtime Facts

状态：legacy runtime 事实入口。

这里保留 runtime control/data 和 vendor package 事实，不再维护旧 mock runtime 或
旧 workflow 索引。当前架构设计先读根目录 `next_stage_refactor_direction.md` 和
`docs/README.md`。

## 保留入口

- [control](control/README.md)：task / subtask / exeblock / instance 与 MICC
  启动链路。
- [data](data/README.md)：CBUF、MICC、RTL/debug sidecar、messages 等 binary
  layout。
- [runtime_ocr](debug/runtime_ocr/README.md)：少量 runtime binary/OCR 追溯材料。

如果正在查字节布局，直接读：

- [cbuf.md](data/cbuf.md)
- [rtl.md](data/rtl.md)
- [micc.md](data/micc.md)
- [messages.md](data/messages.md)

## 当前可确认的执行链

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

在这个链路里，`cbuf_file.bin` / `micc_file.bin` 是被 runtime 装载的镜像，`DPU_Kernel_Start()` 才是 device 计算的真实启动点。

## 证据入口

- [vendor_reference/common_oper/csv-to-binary-pipeline.md](../vendor_reference/common_oper/csv-to-binary-pipeline.md)
- [vendor_reference/runtime_evidence/riscv-control-and-dpuapi.md](../vendor_reference/runtime_evidence/riscv-control-and-dpuapi.md)
- [vendor_reference/runtime_evidence/simict-runtime.md](../vendor_reference/runtime_evidence/simict-runtime.md)
- [vendor_reference/common_oper/task-creation-generategraph-chain.md](../vendor_reference/common_oper/task-creation-generategraph-chain.md)
- [vendor_reference/common_oper/subtask-graph-compile-chain.md](../vendor_reference/common_oper/subtask-graph-compile-chain.md)
- [vendor_reference/common_oper/binary-artifact-generation-pipeline.md](../vendor_reference/common_oper/binary-artifact-generation-pipeline.md)
