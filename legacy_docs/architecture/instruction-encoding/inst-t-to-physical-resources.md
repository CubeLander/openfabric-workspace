# inst_t 到 PE 物理资源的映射

这一页是对旧 `docs/architecture/04-inst-t-to-physical-resources.md` 的架构层收口。

一句话概括：

```text
inst_t 不是一条抽象指令，而是一条带有 PE 资源落点的信息包。
```

## 主要落点

`inst_t` 里的字段会落到这些 PE 资源：

- operand slots
- instruction memory
- block control table
- LD/ST / FLOW 传输状态
- PE-to-PE copy message
- pipeline / execution component

## 关键映射

- `src_operands_idx[]` / `dst_operands_idx[]` -> PE-local operand index
- `block_idx` -> PE 内 block control slot
- `dst_pes_pos[]` -> 目标 PE 坐标
- `stages_start_pc[]` -> block 对应 stage 的 instruction PC
- `extra_fields[]` -> mask / simd mode / shift / 其它 opcode 扩展信息

## 资源边界

PE 里最容易混的两条边是：

```text
SPM <-> PE operand RAM
PE operand RAM <-> compute/tensor pipeline
```

前者属于 LD/ST / transfer 语义，后者属于计算语义。`inst_t` 里的字段会同时
描述这两种边界，但不要把它们混成一个地址空间。

## 交叉阅读

- [pe-register-architecture.md](../pe-microarchitecture/pe-register-architecture.md)
- [pe-microarchitecture-execution-model.md](../pe-microarchitecture/pe-microarchitecture-execution-model.md)
- [runtime/data/rtl.md](../../runtime/data/rtl.md)
