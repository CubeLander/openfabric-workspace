# Device 启动流程

这篇聚焦指令内容和启动命令如何从 host 文件经过 RISC-V 控制程序最终进入 device
执行。

核心结论：

**指令内容是文件，经 runtime 先放进 DDR，再由 RISC-V 通过 DMA 装进 CBUF；
启动命令不是文件，而是 RISC-V 写 MICC 寄存器触发。**

## 1. 两段装载

这里要分清两段：

```text
host/runtime 初始化阶段:
  文件 -> simulator DDR 镜像

RISC-V/control program 阶段:
  DDR 镜像 -> CBUF/MICC/SPM
  写 MICC 寄存器 -> 启动 kernel
```

## 2. host/runtime 如何准备文件

外层脚本：

```text
test/run_app_riscv.sh
```

顺序是：

```bash
cd testcase/application/${app_name}
./run.sh

cd testcase/application/build_app
./run_mtr.sh ${app_name} ...

rm -rf stat log rtl_trace sim_trace config
mkdir -p log stat rtl_trace sim_trace ...

cp testcase/application/${app_name}/result ./config -r
cp testcase/application/${app_name}/input_data.bin ./config
cp testcase/application/${app_name}/riscv/riscv ./config/riscv_program

../../core/bin/runtime ./ top.so topPara.so common/src/libcommon.so
```

所以 simulator 启动前，`config/` 下已经有：

```text
config/cbuf_file.bin
config/micc_file.bin
config/input_data.bin
config/riscv_program
```

这些文件如何被真正读入 simulator 的 DDR/设备模型，目前在可见源码里没有完全
展开；这部分很可能在闭源的：

```text
core/bin/runtime
top.so
topPara.so
```

里完成。我们能确认的是，`common/src/basic_def.h` 里定义了 runtime 约定的
文件名：

```c
#define CBUF_MEM_FILE "./config/cbuf_file.bin"
#define MICC_MEM_FILE "./config/micc_file.bin"
#define SPM_MEM_FILE  "./config/input_data.bin"
```

因此合理链路是：

```text
runtime 启动
  -> 读取 config/cbuf_file.bin 到 DDR CBUF_DDR_ADDR 镜像
  -> 读取 config/micc_file.bin 到 DDR MICC_DDR_ADDR 镜像
  -> 读取 config/input_data.bin 到 DDR SPM_DDR_ADDR 镜像
  -> 加载 config/riscv_program 作为 RISC-V 控制程序
```

这一步属于 host simulator/runtime 装载，不是 `testarm.c` 里显式 `fopen/read`。

## 3. 指令内容如何从 DDR 进 CBUF

RISC-V 程序 `riscv/testarm.c` 开头会做：

```c
uint64_t inst_in_mem = CBUF_DDR_ADDR;
DPU_CbufTransfer((void*)&inst_in_mem);
while (!(DPU_DMATransferFinish(2)));
```

非 RTL 路径则是：

```c
DPU_CbufTransfer((void*)CBUF_DDR_ADDR);
while (!(DPU_DMATransferFinish(2)));
```

`DPU_CbufTransfer()` 本质是写 DMA MMIO 寄存器：

```c
DMA_CHANNEL_MASK = 2;

DMA_TRANS_DIREC0 = 2;          // DDR -> CBUF/internal
DMA_DDR_ADDR0    = MemAddr;
DMA_INACC_ADDR0  = CBUF_INST_BASE;
DMA_X_SLICE0     = 0x1298500;
DMA_START0       = 2;

DMA_TRANS_DIREC1 = 2;
DMA_DDR_ADDR16   = MemAddr;
DMA_INACC_ADDR1  = CBUF_BLCK_BASE;
DMA_X_SLICE1     = 0x141500;
DMA_START1       = 2;
```

所以指令内容进入 device 的链路是：

```text
config/cbuf_file.bin
  -> runtime 预装到 DDR[CBUF_DDR_ADDR]
  -> RISC-V 调 DPU_CbufTransfer
  -> DMA 从 DDR[CBUF_DDR_ADDR] 搬到 CBUF_INST_BASE / CBUF_BLCK_BASE
  -> MICC/PE 后续从 CBUF 中取 inst/exeBlock/instance
```

注意：当前 `DPU_CbufTransfer()` 的两个 DMA channel 都使用同一个 `MemAddr`
作为 DDR source，目的地址不同。这一点我们之前标过疑点：它可能依赖
runtime/设备模型对 CBUF 文件布局的特殊解释，也可能是历史硬编码。可见源码里
不能完全解释。

## 4. 任务配置如何从 DDR 进 MICC

RISC-V 程序接着做：

```c
uint64_t conf_in_mem = MICC_DDR_ADDR;
DPU_MiccTransfer((void*)&conf_in_mem);
while (!(DPU_DMATransferFinish(0)));
```

非 RTL 路径：

```c
DPU_MiccTransfer((void*)MICC_DDR_ADDR);
while (!(DPU_DMATransferFinish(0)));
```

`DPU_MiccTransfer()` 也是写 DMA MMIO：

```c
DMA_TRANS_MODE0  = 0;
DMA_TRANS_DIREC0 = 2;
DMA_CHANNEL_MASK = 0;
DMA_DDR_ADDR0    = MemAddr;
DMA_INACC_ADDR0  = MICC_BASE_ADDR;
DMA_X_SLICE0     = 0x480;
DMA_START0       = 2;
```

链路是：

```text
config/micc_file.bin
  -> runtime 预装到 DDR[MICC_DDR_ADDR]
  -> RISC-V 调 DPU_MiccTransfer
  -> DMA 搬到 MICC_BASE_ADDR
  -> MICC 获得 task/subtask 配置
```

## 5. 输入数据如何进 SPM

输入数据由 RISC-V 程序显式调用：

```c
DMA_Transfer_inoutArray(
    softmax0_input0_ddrStartAddr[app_num] + SPM_DDR_ADDR,
    softmax0_input0_spmStartAddr[app_num],
    ...
);
```

底层会调用 `DPU_SpmTransfer()` / `DPU_Transfer()`，写 DMA 寄存器，把 DDR 中
的 input 区搬进 SPM。

链路是：

```text
config/input_data.bin
  -> runtime 预装到 DDR[SPM_DDR_ADDR + input offset]
  -> RISC-V 调 DPU_SpmTransfer
  -> DMA 搬到 SPM input region
```

## 6. 启动命令如何进入 device

真正的"启动命令"不是一个文件，而是 RISC-V 程序写 MICC MMIO 寄存器。

在 softmax 中：

```c
int inst_reload = app_num > 0 ? 0 : 1;

DPU_Kernel_Start(
    inst_reload,
    TASK_NUM,
    (void*)(((app_num % 2) * 0x400000) / 4),
    0,
    (app_num % 2),
    0
);
```

`DPU_Kernel_Start()` 内部写：

```c
MICC_INSTANCE_BASE
MICC_INSTANCE_BASE_NONEED
MICC_BUF0_INST / MICC_BUF1_INST
MICC_BUF0_TASK / MICC_BUF1_TASK
MICC_BUF0_START / MICC_BUF1_START
```

其中：

- `inst_reload`：是否让 MICC/PE 重新加载指令。
- `TASK_NUM`：启用多少个 task，会被编码成 task enable bitmask。
- `instance_base`：当前 app/buffer 对应的 instance 配置基址。
- `buf_num`：使用 MICC buffer 0 还是 buffer 1。
- `MICC_BUFx_START = 1`：真正发出启动命令。

所以启动链路是：

```text
RISC-V control program
  -> DPU_Kernel_Start()
  -> 写 MICC MMIO 寄存器
  -> MICC 根据 task/subtask/exeBlock/instance 配置激活 PE
  -> PE 从 CBUF/inst_list 执行对应 block
```

## 交叉阅读

- [存储层次总览](storage-hierarchy-overview.md)
- [CBUF/MICC 配置通道](cbuf-micc-config-channel.md)
- [../runtime-model/task-subtask-instance-runtime-model.md](../runtime-model/task-subtask-instance-runtime-model.md)
