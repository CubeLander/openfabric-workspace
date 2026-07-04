# 调试与验证（Debug）

关注点：模拟器/真机差异、运行结果核验、回归对比方式。

- 相关文档：
  - [vendor_reference/case_authoring/manual-vs-generated.md](../../vendor_reference/case_authoring/manual-vs-generated.md)
  - [runtime/simulator/local-mock-runtime.md](../simulator/local-mock-runtime.md)

- 验证动作：
  - 先确认 runtime contract 与控制面参数一致
  - 再对比手工/自动路径差异
  - 需要回溯时进入 compiler 主线核对同名 field 定义


## Raw Runtime OCR / Dump Trail

- [runtime_ocr](runtime_ocr/) 保存早期 runtime ELF / strings / symbols / dump 的 OCR 或文本化结果。
  它只用于追溯；稳定 runtime 控制面入口仍是 `docs/runtime/control/` 和
  `docs/vendor_reference/runtime_evidence/`。
