# Compiler 主线（程序如何被编译）

这条主线回答一个核心问题：**上层算子图如何变成可落地的 runtime 交付物**。
它不负责“怎么执行”，而是负责把“语义”稳定地变成“执行可消费结构”。

## 1. 总览（先看这段）

- `Compiler` 主线是**语义收敛**线：
  - 先把用户语义转成可控的中间表达；
  - 再通过降层规则把表达固定成 tile/物理可执行结构；
  - 最后把结构打包成 runtime 能消费的二进制协议输入。
- 与 runtime 分工上：
  - runtime 只消费“打包好的目标”；
  - compiler 只保证“目标的一致性、边界与可追踪性”。
- 任何 `shared` 领域（如执行模型、拓扑约束）必须通过这条主线的入口回到 source_of_truth 再回流到 runtime。

可以把编译主线看成四层树：

1. **前端语义边界层**：算子输入约束、placement、DTensor 与 SRAM 声明前提。
2. **Chip-level IR 层**：把图语义固定为 chip-level program。
3. **Lowering 层**：确定 tile route/compute/action 的边界。
4. **打包层**：映射到 component / range / instance / blob。

## 2. 当前事实链（请先读）

这组文档是本主线“先决真相”的最小闭包，读懂它们就能理解我们当前默认行为：

- [compiler/notes/env_refactor_chip_level_program.md](../../compiler/notes/env_refactor_chip_level_program.md)
  （`knowledge field`: `chip_level_pipeline`, `load_store_boundary`）
- [docs/compiler/binary_packaging/research_notes/archive/rfc-tileloop-to-vendor-lowering-execution-plan.md](binary_packaging/research_notes/archive/rfc-tileloop-to-vendor-lowering-execution-plan.md)
- [docs/compiler/binary_packaging/research_notes/archive/rfc-dfu-graph-lowering-from-processor-tile.md](binary_packaging/research_notes/archive/rfc-dfu-graph-lowering-from-processor-tile.md)
- [docs/compiler/binary_packaging/research_notes/archive/rfc-program-bin-serializer.md](binary_packaging/research_notes/archive/rfc-program-bin-serializer.md)
- [docs/compiler/binary_packaging/research_notes/archive/stage-report-post-tile-binary-lowering.md](binary_packaging/research_notes/archive/stage-report-post-tile-binary-lowering.md)

补充：运行侧和离线打包链路的执行模型资料（与本主线交叉使用）：

- [vendor_reference/common_oper/task-creation-generategraph-chain.md](../vendor_reference/common_oper/task-creation-generategraph-chain.md)
- [vendor_reference/common_oper/subtask-graph-compile-chain.md](../vendor_reference/common_oper/subtask-graph-compile-chain.md)
- [vendor_reference/common_oper/binary-artifact-generation-pipeline.md](../vendor_reference/common_oper/binary-artifact-generation-pipeline.md)
- [vendor_reference/common_oper/csv-to-binary-pipeline.md](../vendor_reference/common_oper/csv-to-binary-pipeline.md)
- [docs/compiler/binary_packaging/research_notes/archive/rfc-program-bin-serializer.md](binary_packaging/research_notes/archive/rfc-program-bin-serializer.md)

## 3. 这条线的“目录”不是分类，而是“深度”

你不需要在顶层读完所有内容。按“问题优先”下钻即可：

- 你关心语义边界：看 [frontend](frontend/README.md)
- 你关心 chip-level 表述是否稳：看 [chip_level_ir](chip_level_ir/README.md)
- 你关心 tile 降层是否正确：看 [lowering](lowering/README.md)
- 你关心二进制打包规范与兼容：看 [binary_packaging](binary_packaging/README.md)
- 你关心编译器视角案例复盘：看 [cases](cases/README.md)

## 4. 历史与上下文分离

`compiler/notes/archive/*` 以及已退场的 `refactor` 文档会放在上下文/历史入口，默认不作为起点。
当你需要“为什么是这个方案”时再回看它们，不让历史污染当前工作路径。

## 5. 与主线绑定的知识字段

- `chip_level_pipeline`
- `load_store_boundary`
- `tile_routing`
- `binary_packaging`

## 6. 设计摘录

历史设计摘录已收口到：

- [design/README.md](design/README.md)
