# 编译案例（Compiler Cases）

关注点：典型算子（如 softmax、gemm）在 compiler 主线下的构图路径是否稳定。

- 当前建议入口：
  - [vendor_reference/cases/softmax/softmax-case-walkthrough.md](../../vendor_reference/cases/softmax/softmax-case-walkthrough.md)

- 用法：
  - 先从 compiler README 找主链入口
  - 再回到该文档校验前后端边界是否一致
  - 若涉及当前架构判断，回到根目录 `next_stage_refactor_direction.md`
    和 `docs/README.md` 复核。
