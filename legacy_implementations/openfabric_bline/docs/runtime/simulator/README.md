# 模拟器（Simulator）

关注点：simict 与本地 mock 的执行一致性。

- 主要文档：
  - [vendor_reference/runtime_evidence/simict-runtime.md](../../vendor_reference/runtime_evidence/simict-runtime.md)
  - [runtime/simulator/local-mock-runtime.md](local-mock-runtime.md)
  - [runtime/data/README.md](../data/README.md)

- 核查点：
  - bundle -> 可执行映射是否一致
  - runtime 与编译假设是否偏移
  - 调试数据如何映射回 compiler 层字段
  - 镜像字段在内存里的具体落点是否一致

对应知识字段：
- `runtime_contract`
- `runtime_workflow`（待补充，作为待定字段）

执行链证据（用于模拟器核验）

- [vendor_reference/runtime_evidence/simict-runtime.md](../../vendor_reference/runtime_evidence/simict-runtime.md)
- [runtime/simulator/local-mock-runtime.md](local-mock-runtime.md)
- [vendor_reference/common_oper/task-creation-generategraph-chain.md](../../vendor_reference/common_oper/task-creation-generategraph-chain.md)
- [vendor_reference/common_oper/subtask-graph-compile-chain.md](../../vendor_reference/common_oper/subtask-graph-compile-chain.md)
- [vendor_reference/common_oper/binary-artifact-generation-pipeline.md](../../vendor_reference/common_oper/binary-artifact-generation-pipeline.md)
