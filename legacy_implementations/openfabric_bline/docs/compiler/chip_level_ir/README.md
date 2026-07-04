# Chip-Level IR

关注点：chip-level tensor/program 的图层边界和状态模型。

- 当前 source_of_truth：
  - [compiler/notes/env_refactor_chip_level_program.md](../../../compiler/notes/env_refactor_chip_level_program.md)
- 核心约束：
  - 不在前端维护 lower-level tensor-core/PE 级状态
  - load/store 是明确边界动作
  - 通过 `knowledge field` 与 runtime 共享执行模型一致性

延申目录：
- 下一步把与该层强相关的 `route/packaging` 文档按 `depends_on` 链挂入 `lowering/` 和 `binary_packaging/`。
