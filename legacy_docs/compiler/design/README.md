# Compiler Design Notes

这里收录从旧 `docs/design/` 提炼出来、但仍然对当前编译器主线有用的设计思想。

这些不是当前实现的 source of truth。当前实现与分层说明以：

- [`../README.md`](../README.md)
- [`../frontend/README.md`](../frontend/README.md)
- [`../chip_level_ir/README.md`](../chip_level_ir/README.md)
- [`../lowering/README.md`](../lowering/README.md)
- [`../binary_packaging/README.md`](../binary_packaging/README.md)

为准。

## 保留下来的两条设计线

1. [DFU Tiny Distributed Tensor Compiler](dfu-tiny-distributed-tensor-compiler.md)
2. [V1 SUMMA GEMM Backend Design](v1-summa-gemm-backend.md)
3. [B-line Compiler Organization RFC](bline-organization-rfc.md)
4. [TT-Metal Lessons For OpenFabric](tt-metal-lessons-for-openfabric.md)
5. [TT-Metal Simulator Lessons For OpenFabric](tt-metal-simulator-lessons-for-openfabric.md)
6. [B-line Current Architecture Review](bline-current-architecture-review.md)
7. [B-line Boundary Hardening RFC](bline-boundary-hardening-rfc.md)
8. [B-line Log10max Task-Local Ring Execution RFC](bline-log10max-task-local-ring-execution-rfc.md)
9. [B-line Log10max Ring Update Template RFC](bline-log10max-ring-update-template-rfc.md)
10. [B-line Operand Placeholder and Allocation RFC](bline-operand-placeholder-allocation-rfc.md)
11. [B-line Log10max Operand Chain Closure RFC](bline-log10max-operand-chain-closure-rfc.md)
12. [B-line inst_t Row Bytes Field Provenance RFC](bline-inst-row-byte-field-provenance-rfc.md)
13. [B-line Route Row Bytes and Layout Closure RFC](bline-route-row-bytes-layout-rfc.md)
14. [B-line Route Row Byte Family Decision RFC](bline-route-row-byte-family-rfc.md)
15. [B-line Route COPY Candidate Bytes and FlowAck Closure RFC](bline-route-row-candidate-bytes-rfc.md)
16. [B-line Route Final FlowAck and Component Integration RFC](bline-route-final-component-integration-rfc.md)
17. [B-line Log10max Operator Payload Integration and Runtime Gate RFC](bline-log10max-operator-payload-integration-rfc.md)
18. [B-line Log10max Ring FMAX Update Slice Integration RFC](bline-log10max-ring-fmax-update-slice-rfc.md)

## 这层只保留什么

- DeviceMesh / PE mesh 的分布式视角
- 显式 load/store 边界
- tile residency / resource-legal slicing
- LocalPhase / CollectivePhase 的分层
- SUMMA 作为 GEMM baseline
- row/column reuse、vertical fusion、chunked collective 的思想

## 不再保留什么

- 过宽的早期 dataflow 搜索设想
- 还没进入当前 compiler 分层的旧 API 叙述
- 已经被 `compiler/notes/refactor/*` 吃掉的具体实现草图
