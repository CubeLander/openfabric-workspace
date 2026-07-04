# 编译案例（Compiler Cases）

关注点：典型算子（如 softmax、gemm）在 compiler 主线下的构图路径是否稳定。

- 当前建议入口：
  - [vendor_reference/cases/softmax/softmax-case-walkthrough.md](../../vendor_reference/cases/softmax/softmax-case-walkthrough.md)

- 用法：
  - 先从 compiler README 找主链入口
  - 再回到该文档校验前后端边界是否一致
  - 用 `knowledge-field-owner` 复核是否踩过 `source_of_truth` 之外的链路
