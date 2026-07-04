# Compiler Notes

`compiler/notes/` 是编译器设计和重构施工现场，应该保留。

边界很重要：已经被吸收的二进制 / image / runtime package 知识不放在这里作为入口。
这些内容统一从 `docs/` 消费：

- `docs/README.md` 的 B 线二进制施工总入口
- `docs/compiler/binary_packaging/README.md`
- `docs/compiler/binary_packaging/research_notes/README.md`
- `docs/runtime/data/README.md`
- `docs/vendor_reference/common_oper/source-fingerprint-index.md`

## 当前目录用途

- `refactor/`：语义分层、App/Task/Fusion、op spec、soft task axis 等设计。
- `archive/`：非 binary 的历史设计和退场路线。
- `enhancements/`：非 binary 专属的 B 线 stream/fiber 施工想法。
- `log10max/`：算子语义和 staged lowering 研究。若内容进入 binary/image 细节，应迁到 `docs/compiler/binary_packaging/research_notes/`。
- `env_refactor_chip_level_program.md`：ChipEnv / chip-level program 分层边界。

## 禁止事项

不要在这里新增已经可被 docs 消费的二进制事实，例如：

```text
CBUF/MICC row layout
component file size/hash
TaskResource replay
route endpoint binary patching
LegacyInst/template binding
runtime_runnable guard
RISC-V control bundle
A-line manual ABI assumptions
```

这些内容要进 `docs/compiler/binary_packaging/`、`docs/runtime/data/`、
`docs/vendor_reference/common_oper/` 或 `docs/architecture/instruction-set/`。
