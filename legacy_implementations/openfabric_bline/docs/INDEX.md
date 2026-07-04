# Docs Refactored 索引（总入口）

## 0. 快速定位

- [Architecture 总览](architecture/README.md)
- [编译主线入口（Compiler）](compiler/README.md)
- [运行主线入口（Runtime）](runtime/README.md)
- [运行控制面（Runtime Control）](runtime/control/README.md)
- [运行数据面（Runtime Data）](runtime/data/README.md)
- [知识字段真相表（谁是 `source_of_truth`）](knowledge-field-owner.md)

## 1. 主线概览

- 编译主线优先看：输入语义 -> Chip 级 IR -> tile/物理降层 -> 二进制协议 -> 产物提交
- 运行主线优先看：Bundle -> runtime contract -> simulator/硬件调度 -> 执行结果验证

## 2. 主要域（按 `mainline` 标签分发）

- Architecture / Instruction / Memory / Topology：`shared`，先经 `architecture/README.md` 收口
- Compiler IR / Pass / Binary Packaging：`compiler`
- Runtime Contract / Driver / Workflow：`runtime`

## 3. 结构化验收

- 每条主线至少 1 个 `current` 根节点
- 每条主线都要有清晰父子树
- 每个关键 `knowledge field` 最多 2 条 `source_of_truth`
- 任何文档都能在对应主线树中找到“来源、上下文、历史”的位置
