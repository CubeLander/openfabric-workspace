# Runtime 案例（Runtime Cases）

关注点：案例链路是否能重现，是否与当前运行主线一致。

- 当前建议：
  - [vendor_reference/cases/softmax/softmax-case-walkthrough.md](../../vendor_reference/cases/softmax/softmax-case-walkthrough.md)
  - [vendor_reference/case_authoring/manual-vs-generated.md](../../vendor_reference/case_authoring/manual-vs-generated.md)

- 建议动作：
  - 每条案例先声明其入口（runtime/main、control）。
  - 再声明依赖哪些 `knowledge field` 被验证通过。
