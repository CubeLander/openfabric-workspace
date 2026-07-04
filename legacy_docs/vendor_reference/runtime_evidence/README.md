# Runtime Evidence：甲方运行时证据

这里保存 vendor 原始 runtime / RISC-V / DpuAPI 行为证据。它是
[runtime](../../runtime/README.md) 主线的证据来源之一，但不是 OpenFabric runtime
模型本身。

## 文档

- [runtime-control-source-audit.md](runtime-control-source-audit.md)：`DPU_Kernel_Start`、CBUF/MICC DMA、`instance_base_noneed` 等 runtime-control 事实的原始文档和 DpuAPI 源码映射。
- [riscv-control-and-dpuapi.md](riscv-control-and-dpuapi.md)：RISC-V 控制程序和 DpuAPI。
- [dpu-dma-instruction-load-share.md](dpu-dma-instruction-load-share.md)：DMA、instruction load、payload 下发证据。
- [simict-runtime.md](simict-runtime.md)：闭源 SimICT runtime 行为整理。

## 边界

整理后的运行时模型放在 [runtime/control](../../runtime/control/README.md) 和
[runtime/data](../../runtime/data/README.md)。case / build workflow 事实看
[vendor cases](../cases/README.md) 与 [common_oper](../common_oper/README.md)。
本目录只保留原始证据和推断链。
