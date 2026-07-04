# Instruction Format 与 RTL Packing

这一页是对旧 `docs/architecture/03-instruction-format-and-rtl-packing.md` 的架构层收口。

最关键的结论只有一个：

```text
simulator 路径使用宽 inst_t
RTL 路径使用 8-byte bitfield
```

## 两条输出路径

`task_print.cpp` 会把同一条逻辑指令拆成两种材料：

```text
simulator_bin/insts_file.bin
  -> 宽 inst_t，保留调试和调度元数据

rtl_bin/cbufData_inst.bin
  -> 64-bit bitfield，面向 RTL / 硬件验证
```

runtime package 当前消费的是前者，再把它和 `exeblock/instance` 一起拼成 CBUF 镜像。

## 宽指令为什么宽

宽 `inst_t` 要保留：

- opcode / latency / unit type
- 3 个 immediate
- 3 个 source / destination operand slot
- 目标 PE / 目标 block
- forwarding / bypass / flow ack / fetched flags
- extra fields

这些内容对 simulator、graph mapping、调试和运行时调度都很有用，但不需要全部下沉到
RTL bitfield。

## RTL 为什么窄

RTL 结构只保留硬件真正需要的字段，例如：

- opcode
- base address / iteration 相关字段
- operand index
- block index
- mode / mask / shift / PE 坐标

因此它更像“可编码的硬件配置包”，而不是完整的程序对象。

## 读哪里更细

- simulator 宽指令字段细节见 [runtime/data/cbuf.md](../../runtime/data/cbuf.md)
- RTL 64-bit packing 细节见 [runtime/data/rtl.md](../../runtime/data/rtl.md)
