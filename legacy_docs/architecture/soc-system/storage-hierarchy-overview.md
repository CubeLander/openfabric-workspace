# 片上存储层次总览

这篇是 SoC 存储体系的入口页。它先把系统存储的全局视图画出来，再指向其他三篇
细节文档。

## 核心观点

**PE 指令不直接在 DRAM 上工作，也不直接在 SPM 上做算术；真正的算术输入/输出
是 PE 本地 operand RAM。SPM 是 PE 之间和 DRAM 之间的数据缓冲层，CBUF/MICC
是指令和任务配置通道。**

## 1. 全局视图

当前可见执行链路可以抽象成：

```text
外部文件 / host simulator
  -> DDR 地址空间镜像
      -> CBUF 区: 指令、exeBlock、instance 配置
      -> MICC 区: task/subtask 配置
      -> SPM 区: 输入/输出数据
          -> 片上 SPM
              -> PE transfer unit
                  -> PE operand RAM
                      -> PE compute pipeline
                  -> PE operand RAM
              -> SPM / PE-to-PE mesh
          -> DDR / output
```

数据和控制大致分两条线：

```text
数据线:
DRAM <-> DMA <-> SPM <-> PE operand RAM <-> compute

指令/配置线:
DRAM cbuf_file.bin/micc_file.bin
  -> DMA
  -> CBUF/MICC
  -> MICC/PE config and inst distribution
  -> PE inst_list / exeBlock control
```

所以用户态/RISC-V 侧看到的是 DMA、CBUF、MICC、SPM 这些寄存器/API；PE 内部
真正执行时看到的是 `inst_t`、`exeBlock_conf`、`instance_conf` 和 operand RAM
index。

## 2. DRAM 地址空间

核心定义在：

```text
common/src/mem_com_def.h
```

当前有几个重要 DDR 起始地址：

```c
#define CBUF_DDR_ADDR 0x10000000ULL
#define MICC_DDR_ADDR 0x30000000ULL
#define SPM_DDR_ADDR  0x40000000ULL
#define SPM_RST_DDR_ADDR 0x50000000ULL
```

含义可以这样理解：

- `CBUF_DDR_ADDR`：host/simulator 把 `cbuf_file.bin` 映射到 DDR 后，RISC-V 侧
  从这里触发装载。
- `MICC_DDR_ADDR`：host/simulator 把 `micc_file.bin` 映射到 DDR 后，RISC-V 侧
  从这里触发装载。
- `SPM_DDR_ADDR`：输入/输出数据在 DDR 中的基址。case 里的输入输出地址常常写成
  `xxx_ddrStartAddr + SPM_DDR_ADDR`。

这里的 DRAM 在当前环境里更多是 simulator 的内存镜像；实际硬件上可以对应外部
DDR/HBM 地址空间。

## 3. 三层显式内存

现在可以把系统理解成三层显式内存：

```text
DRAM
  大容量外部内存；host/simulator 文件映射和输入输出驻留处。

SPM
  片上 scratchpad；DMA 显式搬入搬出；PE 通过 LD/ST 显式访问。

operand RAM
  PE 本地 SIMD operand 存储；算术指令真正读写的地方；COPY 可在 PE 之间
  直接搬 operand。
```

这和 CPU cache 模型不同：

```text
CPU cache:
  由硬件自动按地址缓存，程序通常不显式分配 cache line。

这里:
  编译器显式分配 operand RAM 槽；
  DMA 显式搬 DRAM <-> SPM；
  LD/ST 显式搬 SPM <-> operand RAM；
  COPY 显式搬 PE operand RAM <-> PE operand RAM；
  CAL 指令只在 operand RAM 上工作。
```

一句话总结：

**SPM 是片上数据仓库，operand RAM 是 PE 的工作台。指令不是对 DRAM 做计算，而是
在 PE 工作台上的 SIMD operand 之间计算；需要数据时从 SPM 装进来，算完再写回 SPM，
跨 PE 则通过 COPY 直接搬 operand。**

## 交叉阅读

- [CBUF/MICC 配置通道](cbuf-micc-config-channel.md)
- [SPM 与 operand RAM 数据通路](data-pathway.md)
- [Device 启动流程](device-boot-sequence.md)
- [../pe-microarchitecture/pe-register-architecture.md](../pe-microarchitecture/pe-register-architecture.md)
