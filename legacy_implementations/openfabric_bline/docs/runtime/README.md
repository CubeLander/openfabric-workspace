# Runtime 运行主线

这一条主线只回答一件事：**编译器产物进入 runtime 之后，是怎么被装载、触发、执行并回收的**。

runtime 现在按两大块组织：

1. **运行时行为面**：执行时序、控制动作、调度过程。
2. **运行时数据面**：`cbuf/micc/instance/insts` 这些二进制到底长什么样、怎么装载、谁在读。

先从这两个入口开始：

- [runtime/control/README.md](control/README.md)
- [runtime/data/README.md](data/README.md)

如果你现在就是在查字节布局，直接下钻：

- [runtime/data/cbuf.md](data/cbuf.md)
- [runtime/data/rtl.md](data/rtl.md)
- [runtime/data/micc.md](data/micc.md)
- [runtime/data/messages.md](data/messages.md)

## 这条主线的三层视角

1. `workflow` 讲的是 case / bundle / config 怎么准备。
2. `control` 讲的是 task / subtask / exeblock / instance 怎么组织，以及 MICC 怎么被触发。
3. `data` 讲的是二进制镜像和内存布局。
4. `simulator` 讲的是这些控制信号在 simulator 里怎么被消费。

如果只先读一个地方，先读 [control/README.md](control/README.md)。如果你现在关心的是 `cbuf_file.bin` / `micc_file.bin` 怎么排布，就先读 [data/README.md](data/README.md)。

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

## 读图方式

- 你关心“控制面配置从哪来”，看 `control/README.md`
- 你关心“二进制布局和字段”，看 `data/README.md`
- 你关心“case 怎么跑”，看 `workflow/README.md`
- 你关心“模拟器本体怎么消费这些镜像”，看 `simulator/README.md`
- 你关心“错误和调试”，看 `debug/README.md`

## 证据入口

- [vendor_reference/common_oper/csv-to-binary-pipeline.md](../vendor_reference/common_oper/csv-to-binary-pipeline.md)
- [vendor_reference/runtime_evidence/riscv-control-and-dpuapi.md](../vendor_reference/runtime_evidence/riscv-control-and-dpuapi.md)
- [vendor_reference/runtime_evidence/simict-runtime.md](../vendor_reference/runtime_evidence/simict-runtime.md)
- [runtime/simulator/local-mock-runtime.md](simulator/local-mock-runtime.md)
- [vendor_reference/common_oper/task-creation-generategraph-chain.md](../vendor_reference/common_oper/task-creation-generategraph-chain.md)
- [vendor_reference/common_oper/subtask-graph-compile-chain.md](../vendor_reference/common_oper/subtask-graph-compile-chain.md)
- [vendor_reference/common_oper/binary-artifact-generation-pipeline.md](../vendor_reference/common_oper/binary-artifact-generation-pipeline.md)
