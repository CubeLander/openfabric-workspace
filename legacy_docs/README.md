# Legacy Docs

状态：降权事实档案。

本目录保存历史整理出的 DFU3500 / vendor toolchain / runtime / ISA / case
证据。它不是 OpenFabric 当前架构设计的 source of truth。

当前设计入口在仓库根目录：

```text
next_stage_refactor_direction.md
SCOPED_TENSOR_PROJECTION_CLEANUP_AUDIT_CN.md
docs/README.md
```

阅读本目录时采用这条规则：

```text
硬件事实、ISA 事实、runtime ABI、vendor workflow evidence 可以引用；
旧 ProcessorTileProgram / TileMicroBlock / StreamTilePlan / B-line 施工路线
只能作为历史经验，不能作为新实现的架构权威。
```

## 保留内容

- `architecture/`：SoC、PE、runtime model、instruction encoding、GEMM case
  等硬件和 ISA 事实。
- `runtime/`：runtime control/data 和 binary layout 事实。
- `vendor_reference/`：customer/vendor workflow、common_oper、runtime evidence、
  GEMM/softmax case 证据。
- `compiler/binary_packaging/`：binary/package 相关 raw audit 和 decoder coverage。
- `compiler/design/`、`compiler_notes/notes/`：仍有参考价值的设计经验、failure
  lessons、operator/case notes。

## 清扫原则

本目录已经删除旧知识治理索引和一批旧路线文档。后续继续清扫时优先删除：

```text
只把 tile / microblock / processor tile program 当语义真相的文档；
只服务旧 B-line 实现路线、且事实已被 docs/ 或 vendor_reference/ 吸收的文档；
断链索引、待办式 README、mock runtime 替代方案；
可以由源码或更小摘要再生成的大体积交付产物。
```

谨慎保留：

```text
PE / SPM / operand RAM / instruction encoding / runtime ABI；
vendor common_oper 行为；
remote/customer workflow；
失败复盘和仍未归约的 binary/runtime facts。
```
