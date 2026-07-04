# SIMD Lane Interpretation Model

这一页是对旧 `docs/architecture/05-simd-lane-interpretation.md` 的架构层收口。

核心结论：

```text
operand 是原始 bits
lane 解释由 opcode / imm / simd_mode / special state 决定
```

## 宽度尺度

```text
SIMD128 logical operand = 4096 bits = 4 x 1024-bit chunks
unit_t / chunk          = 1024 bits = 128 bytes
```

因此一个 operand slot 不是固定类型对象，而是一段可被不同指令以不同方式解释的 bits。

## 决定 lane 布局的因素

1. opcode family，例如 `ADD`、`HADD`、`HMMAL`、`LDSHIF`
2. 指令名本身
3. `imm` 低位模式字段
4. load/store 的 `simd_mode` 与 `extra_fields`
5. 特殊状态，例如 `MASK`、`RX0..RX3`、`LRX0..LRX7`

## 典型例子

- 普通算术通常按 32-bit / 16-bit / 64-bit lane 解释
- `MASK` 直接修改 PE 内部的 8 个 mask 寄存器
- `RXIN/RXOUT` 处理 RX / LRX 内部状态
- `ILDMT/HSTT/SSTSHIF` 还会受 `simd_mode`、offset、mask 等字段影响

## 建议交叉阅读

- [pe-register-architecture.md](pe-register-architecture.md)
- [instruction-set/README.md](../instruction-set/README.md)
- [runtime/data/rtl.md](../../runtime/data/rtl.md)
