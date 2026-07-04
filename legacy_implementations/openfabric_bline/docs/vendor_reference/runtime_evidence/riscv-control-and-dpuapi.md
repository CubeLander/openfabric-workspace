# RISC-V 控制程序与 DpuAPI

## 这部分代码的位置

RISC-V 控制程序位于每个 case 的：

```text
testcase/application/CASE/<case>/riscv/
```

以 softmax 为例：

```text
testcase/application/CASE/softmax_1/riscv/testarm.c
testcase/application/CASE/softmax_1/riscv/makefile
dpuapi/DpuAPI.c
```

`riscv/makefile` 用交叉编译器构建：

```text
riscv64-unknown-elf-gcc
```

生成：

```text
riscv/riscv
riscv/riscv.lst
```

## 它不是 host 程序

`testarm.c` 不是 x86 主机程序，也不是模拟器主入口。

它会被编译成 RISC-V binary，然后由顶层脚本复制为：

```text
config/riscv_program
```

SimICT runtime 启动后，模拟器中的 RISC-V 设备模型会加载并执行这个程序。

## testarm.c 做什么

典型执行顺序：

```text
1. DPU_CbufTransfer(CBUF_DDR_ADDR)
2. 等待 CBUF DMA 完成
3. DPU_MiccTransfer(MICC_DDR_ADDR)
4. 等待 MICC DMA 完成
5. DMA input: DDR -> SPM
6. DPU_Kernel_Start(...)
7. DPU_Kernel_Wait_Finish(...)
8. DMA output: SPM -> DDR
9. DPU_App_Finish()
```

如果有多 app 或 ping-pong buffer，`testarm.c` 会在 loop 中切换 buffer 和 task instance。

## DpuAPI.c 的角色

`DpuAPI.c` 是 RISC-V 侧访问 DPU 模拟设备的 API 层。

它主要通过内存映射寄存器控制硬件模块，例如：

```text
DMA register
MICC register
CBUF register
APP finish register
```

关键函数包括：

```text
DPU_CbufTransfer(...)
DPU_MiccTransfer(...)
DMA_Transfer_inoutArray(...)
DPU_Kernel_Start(...)
DPU_Kernel_Wait_Finish(...)
DPU_App_Finish()
```

`DPU_Kernel_Start()` 是真正发出 DPU task start 信号的地方。它会写 MICC 相关寄存器，例如：

```text
MICC_INSTANCE_BASE
MICC_BUF0_INST / MICC_BUF1_INST
MICC_BUF0_TASK / MICC_BUF1_TASK
MICC_BUF0_START / MICC_BUF1_START
```

`DPU_Kernel_Wait_Finish()` 则轮询：

```text
MICC_BUF0_FINISH
MICC_BUF1_FINISH
```

## 地址常量

常见地址来自 common headers，例如：

```text
CBUF_DDR_ADDR = 0x10000000
MICC_DDR_ADDR = 0x30000000
SPM_DDR_ADDR  = 0x40000000
SPM_RST_DDR_ADDR = 0x50000000
```

这些地址在真实硬件上可能对应 DDR 中的固定布局；在模拟器里则由 memory / DMA / MICC / SPM 等模块解释。

## 和 result/ 的关系

app build / run_mtr 阶段会把编译结果整理到：

```text
result/
```

顶层测试脚本复制：

```text
cp testcase/application/${app_name}/result ./config -r
cp testcase/application/${app_name}/input_data.bin ./config
cp testcase/application/${app_name}/riscv/riscv ./config/riscv_program
```

所以 RISC-V 程序不会自己从源码目录解析 CSV。它看到的是模拟器已经布置好的内存和配置文件。

## 和 SimICT runtime 的关系

RISC-V 程序执行 MMIO/DMA 操作时，实际上是在和模拟器中的 device module 交互。

可以理解为：

```text
RISC-V 程序写寄存器
  -> 模拟器 device module 收到访问
  -> DMA/MICC/SPM/PE 模块通过 SimICT port/message 互动
  -> runtime 调度这些模块的 timed messages
```

因此：

- `DpuAPI.c` 是 guest/control-plane API；
- `runtime` 是 host-side simulator scheduler；
- `testarm.c` 负责告诉模拟 DPU “什么时候搬数据、什么时候启动 task”。

