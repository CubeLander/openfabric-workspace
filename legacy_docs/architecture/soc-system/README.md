# SoC 系统架构

这个主题聚焦 DFU3500 SoC 的宏观结构：从 DRAM 到片上 CBUF/MICC/SPM，再到
PE 执行面的全局存储层次和数据通路。

## 阅读顺序

1. [存储层次总览](storage-hierarchy-overview.md) — DRAM / SPM / operand RAM
   三层显式内存的全局视图
2. [CBUF/MICC 配置通道](cbuf-micc-config-channel.md) — 指令和任务配置如何
   通过 CBUF/MICC 装载到 device
3. [SPM 与 operand RAM 数据通路](data-pathway.md) — LD/ST/COPY 如何在 SPM、
   operand RAM 和 PE 之间搬数据
4. [Device 启动流程](device-boot-sequence.md) — 从 host 文件到 RISC-V 启动
   的完整链路

## 交叉阅读

- [PE 微架构](../pe-microarchitecture/README.md)
- [运行时模型](../runtime-model/README.md)
