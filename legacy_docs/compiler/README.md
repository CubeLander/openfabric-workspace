# Legacy Compiler Notes

状态：历史编译器事实和设计经验入口。

当前 OpenFabric 编译抽象以根目录 `next_stage_refactor_direction.md` 为准：

```text
Tensor
  -> StreamTensorView
  -> FiberTensorView
  -> TypedTileValue
  -> Operand
  -> Instruction / Binary
```

因此，本目录里的旧 `DTensor`、`ProcessorTileProgram`、`TileMicroBlock`、
`StreamTilePlan`、B-line/Plan-B 语言都只能当历史上下文使用。

## 推荐读取顺序

- 当前设计原则：`../../next_stage_refactor_direction.md`
- 当前 docs 入口：`../../docs/README.md`
- vendor assembler input：`../../docs/vendor-assembler-input-protocol.md`
- runtime image：`../../docs/runtime-plan-image.md`
- operator coverage：`../../docs/operator-coverage-checklist.md`

本目录内仍可参考：

- [binary_packaging](binary_packaging/README.md)：binary/package raw audit、
  decoder coverage 和 runtime guard 经验。
- [design](design/)：SUMMA/GEMM、TT-Metal、tile residency、DFU lowering 等历史
  设计经验。
- [frontend](frontend/README.md)、[chip_level_ir](chip_level_ir/README.md)、
  [cases](cases/README.md)：旧 compiler 分层和 case 线索。

## 降权规则

如果本目录和当前根目录/docs 设计冲突：

```text
硬件事实、ISA 事实、vendor source 行为优先保留；
旧 IR / lowering route / B-line 实现计划不作为新代码依据。
```
