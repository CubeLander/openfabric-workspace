# 编译前端（Frontend）

关注点：算子语义、graph-to-program 的边界、以及 DTensor 与 placement 的契约。

- 当前真相：[isa-execution-model.md](../../architecture/instruction-encoding/isa-execution-model.md)（可复用理解执行兼容性）
- 关键问题：
  - 哪些逻辑该在前端描述，哪些必须下沉到后续 pass
  - placement 与 SRAM 声明边界
  - DTensor 输入是否允许缺省

关联主线：
- `compiler` -> 为 `chip_level_pipeline`、`load_store_boundary` 提供输入语义约束
