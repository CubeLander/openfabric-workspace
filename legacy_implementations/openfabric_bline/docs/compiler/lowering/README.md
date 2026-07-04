# 编译降层（Lowering）

关注点：`chip-level` 到物理执行结构（tile/physical program）的转换。

- 当前主链文档：
  - [docs/compiler/binary_packaging/research_notes/archive/rfc-dfu-graph-lowering-from-processor-tile.md](../binary_packaging/research_notes/archive/rfc-dfu-graph-lowering-from-processor-tile.md)
  - [docs/compiler/binary_packaging/research_notes/archive/rfc-tileloop-to-vendor-lowering-execution-plan.md](../binary_packaging/research_notes/archive/rfc-tileloop-to-vendor-lowering-execution-plan.md)
  - [docs/compiler/binary_packaging/research_notes/archive/rfc-tile-microblock-as-lowering-authority.md](../binary_packaging/research_notes/archive/rfc-tile-microblock-as-lowering-authority.md)

- 常见问题：
  - 何时认为 tile 是当前粒度
  - 何时允许在 phase 里做 fused 后处理
  - 如何把 `route_policy` 与 `tile_action` 对齐

对应知识字段：
- `tile_routing`
- `load_store_boundary`
