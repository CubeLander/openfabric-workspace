# Binary Packaging Research Notes

这里保存从旧 binary working notes 和 binary-related enhancement notes 迁入的 raw audit、
RFC、gap tracker、pain retrospective 和 B 线施工设计。

这不是二进制知识的主入口。主入口仍然是：

- [docs/README.md](../../../README.md)
- [二进制打包](../README.md)
- [Runtime 数据面](../../../runtime/data/README.md)
- [common_oper vendor evidence](../../../vendor_reference/common_oper/README.md)
- [DFU3500 SIMD 指令集](../../../architecture/instruction-set/dfu3500-simd/README.md)

## 子目录

- [binary](binary/)：A 线和 vendor binary / ABI / component writer / task resource
  相关审计笔记。
- [enhancements](enhancements/)：B 线 executable role、fiber projection、template
  binding、runtime control generation、binary decoder 等设计笔记。
- [archive](archive/)：binary notes -> docs reduction 的历史迁移计划。
  - [archive/legacy_drafts](archive/legacy_drafts/)：A 线早期 runtime package、remote diff、legacy workflow raw drafts。

## 使用规则

1. 先看稳定 docs，再看这里的 raw notes。
2. 如果 raw note 和稳定 docs 冲突，优先信稳定 docs；再回到 source fingerprint /
   runtime evidence 核实。
3. 新的 binary 事实不要直接写在这里当终点；先进入合适的 docs owner：
   - runtime byte layout -> `docs/runtime/data/`
   - compiler generation contract -> `docs/compiler/binary_packaging/`
   - vendor source evidence -> `docs/vendor_reference/common_oper/`
   - opcode / operand semantics -> `docs/architecture/instruction-set/`
4. 如果必须保留施工过程，才把 raw trail 放到本目录。

一句话：这里是矿渣场，不是地图。地图在 `docs/README.md`。
