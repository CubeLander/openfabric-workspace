# 关于 softmax_1 中 device 指令装载路径的阶段性结论

这份是给学校团队内部讨论用的版本，主要解释 `softmax_1/riscv/testarm.c` 这段 RISC-V/CPU 侧代码到底在做什么，以及 device 侧指令是怎么被装进 DPU/DFU 的。

## 一句话结论

`testarm.c` 不是 device kernel 指令生成器，它更像一个裸机 runtime/controller。真正的 device 指令和任务配置已经由 `build_app` 预先生成成二进制 payload；RISC-V 侧只是通过写 DMA/MICC 寄存器，把这些 payload 从 DDR 搬进 device 内部的 CBUF/MICC/SPM，然后启动计算。

换句话说，这里的模式不是：

```text
CPU 一条条写 device 指令
```

而是：

```text
build_app 生成 cbuf/micc payload
  -> simulator/runtime 预置到 DDR 地址空间
  -> RISC-V 程序写 DMA 控制寄存器
  -> DMA engine 自己从 DDR 读数据并写到 CBUF/MICC
  -> RISC-V 写 MICC start/task-enable 寄存器启动 kernel
```

## 关键链路

`build_app` 先把算子编译产物拼成两个 simulator 侧文件：

```text
result/cbuf_file.bin
result/micc_file.bin
```

其中：

- `cbuf_file.bin` 主要包含 device 指令、exeBlock 配置、instance 配置。
- `micc_file.bin` 主要包含 task/subtask 级调度配置。

在 `softmax_1` 当前产物中可以看到：

- `result/cbuf_file.bin` 约 22 MB
- `result/micc_file.bin` 约 8.1 MB
- `simulator_bin/insts_file.bin` 约 20 MB
- `simulator_bin/exeblock_conf_info_file.bin` 约 260 KB
- `simulator_bin/instance_conf_info_file.bin` 约 2 MB
- `simulator_bin/tasks_conf_info_file.bin` 约 480 B
- `simulator_bin/subtasks_conf_info_file.bin` 约 8.1 MB

这说明 device 指令主体不在 RISC-V ELF 代码段里，而是在外部二进制 payload 里。

## RISC-V 侧在做什么

`testarm.c` 的启动阶段先执行：

```c
DPU_CbufTransfer((void*)CBUF_DDR_ADDR);
while (!(DPU_DMATransferFinish(2)));

DPU_MiccTransfer((void*)MICC_DDR_ADDR);
while (!(DPU_DMATransferFinish(0)));
```

随后才做输入搬运、kernel start、输出搬运：

```c
DMA_Transfer_inoutArray(... + SPM_DDR_ADDR, ...);

DPU_Kernel_Start(inst_reload, TASK_NUM, ...);

while (!DPU_Kernel_Wait_Finish(...));

DMA_Transfer_inoutArray(... + SPM_RST_DDR_ADDR, ...);
```

这里 `CBUF_DDR_ADDR`、`MICC_DDR_ADDR` 等地址定义在 `common/src/mem_com_def.h`：

```c
#define CBUF_DDR_ADDR    0x10000000ULL
#define MICC_DDR_ADDR    0x30000000ULL
#define SPM_DDR_ADDR     0x40000000ULL
#define SPM_RST_DDR_ADDR 0x50000000ULL
```

也就是说，CPU 侧假设相关 payload 已经在 DDR 的固定地址上。

## 为什么 DPU_CbufTransfer 里没有 memcpy

这是最关键的理解点。

`DPU_CbufTransfer` 不是 CPU 自己搬数据，它是在编程 DMA 控制器。代码大概是：

```c
*(unsigned*)DMA_CHANNEL_MASK = 2;
*(unsigned*)DMA_TRANS_DIREC0 = 2;
*(unsigned*)DMA_DDR_ADDR0 = (unsigned)MemAddr;
*(unsigned*)DMA_INACC_ADDR0 = (unsigned)CBUF_INST_BASE;
*(unsigned*)DMA_X_SLICE0 = 0x1298500;
*(unsigned*)DMA_START0 = 2;

*(unsigned*)DMA_TRANS_DIREC1 = 2;
*(unsigned*)DMA_DDR_ADDR16 = (unsigned)MemAddr;
*(unsigned*)DMA_INACC_ADDR1 = (unsigned)CBUF_BLCK_BASE;
*(unsigned*)DMA_X_SLICE1 = 0x141500;
*(unsigned*)DMA_START1 = 2;
```

它写的是 MMIO 寄存器：

- `DMA_DDR_ADDRx`：DDR 源地址
- `DMA_INACC_ADDRx`：device 内部目的地址
- `DMA_X_SLICE/Y_SLICE/X_FULL`：搬运大小和形状
- `DMA_TRANS_DIRECx`：搬运方向
- `DMA_STARTx`：启动 DMA

`common/src/dma_com_def.h` 里也能看到寄存器语义：

```c
#define DMA_START0      0x0220a008  /* 2: start, other: stop. */
#define DMA_TRANS_DONE0 0x0220a00c  /* read 1: done, write 2: clear. */
```

因此这不是普通函数内存复制，而是：

```text
CPU/RISC-V 写 DMA 寄存器
  -> DMA engine 作为 bus master 访问 DRAM
  -> DMA engine 把数据搬到 CBUF/MICC/SPM
  -> DMA engine 置 done bit
  -> CPU/RISC-V 轮询 done bit
```

真实硬件上这就是 DMA 控制器访问 DRAM；仿真器里则应该是 DMA 模型捕捉这些 MMIO 写操作后，在仿真内存中模拟同样的数据搬运。

## 这和 Linux driver 的关系

这套代码的控制模式非常像 Linux driver 底层会做的事情：

```text
配置 DMA 源/目的/长度
写 start doorbell
等待 done 或中断
清 done
写计算单元 start/task enable
```

区别在于，当前 testcase 里不是 Linux kernel driver，而是裸机/仿真 RISC-V 程序直接把物理 MMIO 地址强转成指针写：

```c
*(unsigned*)0x0220a008 = 2;
```

如果是在 Linux 用户态，这种写法通常不能直接成立，需要 kernel driver 或 `/dev/mem + mmap` 之类机制先把 MMIO 区映射出来。所以甲方说 runtime/driver 在 DFU 代码中、由 DMA 驱动体现，目前从这份代码看，可以理解成：

```text
当前仓库里的 DpuAPI.c 是一个“裸机式 DMA driver/runtime API”雏形；
它通过 MMIO 配置 DMA 和 MICC，而不是提供标准 Linux driver 抽象。
```

## 还没完全钉死的点

1. 当前快照里没有可读的 `core/bin/runtime` 源码，因此 simulator 到底如何把 `result/cbuf_file.bin` 放到 `CBUF_DDR_ADDR`、把 `result/micc_file.bin` 放到 `MICC_DDR_ADDR`，还缺最后一环源码证据。
2. `DPU_CbufTransfer` 的 channel 1 源地址目前也写成同一个 `MemAddr`，没有显式加 `insts_file.bin` 的偏移；这可能依赖 simulator DMA 的特殊解释、固定镜像布局，或是历史代码遗留，需要继续确认。
3. `DPU_MiccTransfer` 里固定搬 `0x480` 字节，但 `micc_file.bin` 远大于这个大小；这说明 MICC 的 task/subtask 配置装载可能还有额外布局机制，或者当前 API 只搬入口配置。

## 对我们后续研究的影响

目前可以把系统分成两层看：

```text
离线编译层:
  CSV/template/generateGraph/build_app
  -> 生成 cbuf_file.bin / micc_file.bin

运行控制层:
  RISC-V testarm.c + DpuAPI.c
  -> DMA 装载 CBUF/MICC/SPM
  -> MICC 启动 task
  -> 轮询完成
```

所以后续如果要继续研究“device 指令怎么指定到硬件上”，重点还是：

- 在离线编译层追 `insts_file.bin`、`exeblock_conf_info_file.bin`、`instance_conf_info_file.bin` 的结构；
- 在运行控制层确认 DMA/MICC 地址布局，以及 simulator runtime 如何预置 DDR。

这比直接从 RISC-V 程序里找 device 指令更靠谱，因为 RISC-V ELF 里主要是控制流，device 指令本体在外部 payload 里。
