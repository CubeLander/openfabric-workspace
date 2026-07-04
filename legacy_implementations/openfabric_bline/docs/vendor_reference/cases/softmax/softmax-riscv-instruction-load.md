# softmax_1 RISC-V 侧如何装载 device 指令

这篇笔记记录 `testcase/application/CASE/softmax_1/riscv/testarm.c` 里 CPU/RISC-V 侧控制逻辑，以及实际 device 侧指令/config 是怎样被装进 DFU/仿真器设备空间的。

## 结论

`testarm.c` 不是 device 指令生成器，也不是 kernel compiler。它是 RISC-V/CPU 侧的控制程序：

1. 先用 DMA 把 `cbuf_file.bin` 对应的 CBUF payload 从 DDR 搬到设备内部 CBUF 区域。
2. 再用 DMA 把 `micc_file.bin` 对应的 MICC task/subtask payload 从 DDR 搬到 MICC 配置区。
3. 再把输入数据从 DDR 搬到 SPM。
4. 调 `DPU_Kernel_Start(...)` 写 MICC start/task-enable 寄存器启动 device kernel。
5. 轮询 finish 寄存器，最后把输出从 SPM 搬回 DDR。

所以实际 device 指令“装进去”的路径是：

```text
build_app
  -> simulator_bin/insts_file.bin
  -> simulator_bin/exeblock_conf_info_file.bin
  -> simulator_bin/instance_conf_info_file.bin
  -> result/cbuf_file.bin
  -> simulator runtime 预载到 DDR CBUF_DDR_ADDR
  -> RISC-V 调 DPU_CbufTransfer(CBUF_DDR_ADDR)
  -> DMA 写入 CBUF_INST_BASE / CBUF_BLCK_BASE

build_app
  -> simulator_bin/tasks_conf_info_file.bin
  -> simulator_bin/subtasks_conf_info_file.bin
  -> result/micc_file.bin
  -> simulator runtime 预载到 DDR MICC_DDR_ADDR
  -> RISC-V 调 DPU_MiccTransfer(MICC_DDR_ADDR)
  -> DMA 写入 MICC_BASE_ADDR
```

这里的“搬运”不是 CPU 通过 `memcpy` 完成的。`DPU_CbufTransfer`/`DPU_MiccTransfer` 做的是典型 DMA 控制器编程：

```text
CPU/RISC-V 写 MMIO 寄存器:
  DMA_DDR_ADDRx    = DDR 源地址
  DMA_INACC_ADDRx  = device 内部目标地址
  DMA_X_SLICE/Y... = 搬运长度和形状
  DMA_TRANS_DIRECx = 方向
  DMA_STARTx       = 2

DMA engine / simulator DMA model:
  看到 DMA_STARTx 后，从 DDR 读 payload，写入 CBUF/MICC/SPM，
  完成后把 DMA_TRANS_DONEx 置 1。

CPU/RISC-V:
  轮询 DMA_TRANS_DONEx，读到 1 后写 2 清除 done。
```

所以它和 Linux 里常见的 “driver 配 DMA descriptor / 写 doorbell / 轮询或中断等待完成” 是同一个控制模式。区别是这里不是 Linux kernel driver，而是裸机/仿真 RISC-V 程序直接把物理 MMIO 地址强转成指针写寄存器。

## 关键源码位置

`testarm.c` 的主入口在 `do_dpuctrl/main`：

```c
DPU_CbufTransfer((void*)CBUF_DDR_ADDR);
while (!(DPU_DMATransferFinish(2)));

DPU_MiccTransfer((void*)MICC_DDR_ADDR);
while (!(DPU_DMATransferFinish(0)));
```

随后进入输入搬运、kernel start、输出搬运：

```c
DMA_Transfer_inoutArray(... + SPM_DDR_ADDR, ...);

DPU_Kernel_Start(inst_reload, TASK_NUM,
                 (void*)(((app_num % 2) * 0x400000) / 4),
                 0, (app_num % 2), 0);

while (!DPU_Kernel_Wait_Finish(...));

DMA_Transfer_inoutArray(... + SPM_RST_DDR_ADDR, ...);
```

`DpuAPI.c` 里真正做 DMA MMIO 写寄存器的是：

- `DPU_CbufTransfer(void *MemAddr)`
- `DPU_MiccTransfer(void *MemAddr)`
- `DPU_Kernel_Start(...)`
- `DPU_DMATransferFinish(...)`

`DPU_CbufTransfer` 做双通道 DMA：

```text
channel 0:
  DDR source = MemAddr = CBUF_DDR_ADDR
  device dst = CBUF_INST_BASE
  length     = 0x1298500

channel 1:
  DDR source = MemAddr = CBUF_DDR_ADDR
  device dst = CBUF_BLCK_BASE
  length     = 0x141500
```

注意这里两个 channel 的 DDR source 都写成 `MemAddr`。从 `build_app/run_mtr.sh` 看，`cbuf_file.bin` 是把 `insts_file.bin`、`exeblock_conf_info_file.bin`、`instance_conf_info_file.bin` 顺序拼成一个文件；而当前 `DPU_CbufTransfer` 的 channel 1 没显式加 exeblock 在 DDR 里的偏移。这一点需要继续确认 simulator DMA 对 CBUF 目的地址/源地址是否有特殊解释，或者这里是否依赖固定镜像布局/历史代码问题。

`DPU_MiccTransfer` 做单通道 DMA：

```text
DDR source = MemAddr = MICC_DDR_ADDR
device dst = MICC_BASE_ADDR
length     = 0x480
```

## 地址和文件绑定

公共定义在 `common/src/mem_com_def.h`：

```c
#define CBUF_DDR_ADDR    0x10000000ULL
#define MICC_DDR_ADDR    0x30000000ULL
#define SPM_DDR_ADDR     0x40000000ULL
#define SPM_RST_DDR_ADDR 0x50000000ULL
```

仿真器配置文件名在 `common/src/basic_def.h`：

```c
#define CBUF_MEM_FILE "./config/cbuf_file.bin"
#define SPM_MEM_FILE  "./config/input_data.bin"
#define MICC_MEM_FILE "./config/micc_file.bin"
```

`test/run_app_riscv.sh` 会把 app 的 `result/` 目录复制到根目录 `./config`，并把 RISC-V 程序复制成 `./config/riscv_program`，然后启动：

```sh
../../core/bin/runtime ./ top.so topPara.so common/src/libcommon.so
```

当前快照里有 `simict3500final/gpdpu/core`，但只看到 `bin/env.sh`、`bin/gen-runtime-info`、`bin/run-module` 和一些截图/头文件，没有 `core/bin/runtime` 或 runtime 源码。因此 runtime 如何把 `./config/cbuf_file.bin` 映射到 `CBUF_DDR_ADDR`、把 `./config/micc_file.bin` 映射到 `MICC_DDR_ADDR` 的最后一环，当前仍不能从本地源码确认。但从 `basic_def.h` 的文件名约定和 `run_app_riscv.sh` 的复制流程看，这个预载动作应在外部 simulator runtime 里完成。

## 2026-05-31 更新：模拟器启动链路基本破案

现在可以更明确地说：`testarm.c` 之前的文件读取不应该发生在 RISC-V guest 程序里；如果存在“文件 -> 模拟 DDR”的动作，它只能发生在 host 侧 SimICT runtime / simulator module 初始化阶段。

本地启动脚本给出的链路是：

```sh
cd testcase/application/${app_name}
./run.sh

cd testcase/application/build_app
./run_mtr.sh ${app_name} ${Duplicate_Application_Amount} ${app_num}

rm -rf stat log rtl_trace sim_trace config
cp testcase/application/${app_name}/result ./config -r
cp testcase/application/${app_name}/input_data.bin ./config
cp testcase/application/${app_name}/riscv/riscv ./config/riscv_program

../../core/bin/runtime ./ top.so topPara.so common/src/libcommon.so
```

因此 `runtime` 启动时当前目录下已经具备：

```text
./config/cbuf_file.bin
./config/micc_file.bin
./config/input_data.bin
./config/riscv_program
```

`riscv_program` 是 guest/control 程序；`cbuf_file.bin`、`micc_file.bin`、`input_data.bin` 是脚本明确准备给 host simulator 的 payload。`testarm.c` 运行时只写 DMA/MICC MMIO，让仿真 DMA 从固定 DDR 地址搬数据。

本地还有两个支持这个判断的文件：

```c
// common/src/basic_def.h
#define CBUF_MEM_FILE "./config/cbuf_file.bin"
#define SPM_MEM_FILE  "./config/input_data.bin"
#define MICC_MEM_FILE "./config/micc_file.bin"
```

```c
// common/src/common_func.c
int64_t read_file(...)
int64_t read_file_with_pos(...)
```

但这里需要纠正一个重要点：这些宏和 `read_file(...)` 只能证明“曾经设计过 config 文件读取约定”，不能证明当前有效路径真的使用它们。当前本地快照里没有看到 `CBUF_MEM_FILE` / `MICC_MEM_FILE` / `SPM_MEM_FILE` 的引用；用户在服务器完整源码里也没有搜到这些宏的其它引用。因此它们很可能是旧接口或死代码。

如果 `config/*.bin` 确实被消费，调用点不一定表现为这些宏名，可能在：

```text
users/risc_nn_riscv/mem/src
users/risc_nn_riscv/dma/src
users/risc_nn_riscv/core/src
users/risc_nn_riscv/micc/src
users/risc_nn_riscv/spm/src
gpdpu/core/runtime
top.so / topPara.so / module .so 的二进制字符串或参数表
```

远端完整源码/二进制里优先搜索：

```sh
rg -n "cbuf_file\\.bin|micc_file\\.bin|input_data\\.bin|riscv_program|read_file_with_pos|read_file\\(|fopen|ifstream|open\\(" /project/new-home/simict3500final
find /project/new-home/simict3500final -name '*.so' -o -name runtime -o -name runtime_verbose \
  | xargs -r strings -a 2>/dev/null \
  | rg "cbuf_file|micc_file|input_data|riscv_program|config/"
```

最希望找到的证据形态是以下之一：

```text
mem/spm/micc/core module 初始化
  -> fopen/open/read/mmap
  -> cbuf_file.bin / micc_file.bin / input_data.bin / riscv_program
  -> 写入模拟 DDR 地址 CBUF_DDR_ADDR / MICC_DDR_ADDR / SPM_DDR_ADDR

或者：
topPara.so / generated parameter table
  -> 把文件名/地址作为参数传给 mem/core/dma module

或者：
runtime / module .so
  -> 硬编码读取 ./config 目录下的固定文件名
```

如果源码搜索仍然没有结果，最可靠的确认方式是对实际运行做 `strace`：

```sh
cd /project/new-home/simict3500final/gpdpu/users/risc_nn_riscv
# 先让 run_app_riscv.sh 准备好 ./config、top.so/topPara.so 等，再对 runtime 本体追踪 open/read。
strace -f -s 200 -e trace=openat,open,read,mmap,stat \
  -o /tmp/gpdpu_runtime_files.trace \
  ../../core/bin/runtime ./ top.so topPara.so common/src/libcommon.so

rg "cbuf_file|micc_file|input_data|riscv_program|config/" /tmp/gpdpu_runtime_files.trace
```

这个比猜宏名可靠：只要 simulator 真的从文件系统读了 `.bin`，`strace` 会直接显示是谁打开了哪个路径。

还有一个反证提示我们不能把 `cbuf_file.bin` / `micc_file.bin` 理解成“整包直接 DMA 进去”：

```text
softmax_1/result/cbuf_file.bin = 0x1671000 bytes
softmax_1/result/micc_file.bin = 0x820ce0 bytes

DPU_CbufTransfer:
  channel 0 length = 0x1298500
  channel 1 length = 0x141500
  total            = 0x13d9a00

DPU_MiccTransfer:
  length           = 0x480

simulator_bin/tasks_conf_info_file.bin    = 0x480
simulator_bin/subtasks_conf_info_file.bin = 0x820b00
```

`DPU_MiccTransfer` 的 `0x480` 正好只覆盖 task 级入口配置，不覆盖巨大的 subtask 配置；`DPU_CbufTransfer` 的长度也和 `cbuf_file.bin` 总大小对不上。因此当前更谨慎的判断是：

```text
result/*.bin 的确是 build_app 生成并被 run_app_riscv.sh 放进 config；
RISC-V guest 的 DpuAPI 确实写 DMA 寄存器去搬固定 DDR 地址；
但 config/*.bin 是否被完整预载、按什么 offset 映射到 DDR、以及哪些部分由 DMA 搬/哪些部分由模块直接访问，目前还没有闭合证据。
```

下一步必须通过 `strace` 或模块源码/二进制字符串来确认真实文件访问和地址布局，不能再把 `CBUF_MEM_FILE` / `MICC_MEM_FILE` 当成有效证据。

## build_app 侧如何生成 payload

`testcase/application/build_app/run_mtr.sh` 里把 simulator bin 拼成最终给 runtime 用的两个文件：

```sh
cat ./simulator_bin/insts_file.bin >> ./simulator_bin_multi_app/cbuf_file.bin
cat ./simulator_bin/exeblock_conf_info_file.bin >> ./simulator_bin_multi_app/cbuf_file.bin
cat ./simulator_bin/instance_conf_info_file.bin >> ./simulator_bin_multi_app/cbuf_file.bin

cat ./simulator_bin/tasks_conf_info_file.bin >> ./simulator_bin_multi_app/micc_file.bin
cat ./simulator_bin/subtasks_conf_info_file.bin >> ./simulator_bin_multi_app/micc_file.bin

cp cbuf_file.bin ../result/
cp micc_file.bin ../result/
```

以 `softmax_1` 当前产物为例：

- `result/cbuf_file.bin` 约 22 MB
- `result/micc_file.bin` 约 8.1 MB
- `simulator_bin/insts_file.bin` 约 20 MB
- `simulator_bin/exeblock_conf_info_file.bin` 约 260 KB
- `simulator_bin/instance_conf_info_file.bin` 约 2 MB
- `simulator_bin/tasks_conf_info_file.bin` 约 480 B
- `simulator_bin/subtasks_conf_info_file.bin` 约 8.1 MB

这说明 device 指令/config 的主体不是 RISC-V ELF 里的代码段，而是外部二进制 payload。

## 汇编侧确认

`riscv/riscv.lst` 中 `main` 调用了：

```text
DPU_CbufTransfer
DPU_MiccTransfer
DPU_Kernel_Start
```

`DPU_CbufTransfer` 展开后可以看到大量对 `0x0220a***` DMA 寄存器的 `sw`。例如：

```text
DMA_CHANNEL_MASK = 2
DMA_TRANS_DIREC0 = 2
DMA_DDR_ADDR0 = CBUF_DDR_ADDR
DMA_INACC_ADDR0 = CBUF_INST_BASE
DMA_START0 = 2
DMA_START1 = 2
```

所以从汇编逆向也能还原出同一个结论：RISC-V 侧只负责写 DMA/MICC 控制寄存器，device 指令本体来自 `cbuf_file.bin` / `micc_file.bin`。

## 当前未完全确认

1. `core/bin/runtime` 不在当前仓库快照里，所以 simulator 如何把 `./config/cbuf_file.bin`、`./config/micc_file.bin` 放到 DDR 地址空间还不能从源码确认。
2. `DPU_CbufTransfer` 的 channel 1 DDR source 没有显式加 `insts_file.bin` 长度偏移，这里需要继续追 simulator DMA 语义或对比历史实现。
3. `DPU_MiccTransfer` 固定搬 `0x480` 字节，但 `result/micc_file.bin` 远大于这个大小；这可能意味着一次启动只搬 task 级入口配置，subtask 区域通过 MICC 内部地址布局/其它机制访问，或者当前 API 是过时/特殊化版本。需要继续核对 MICC 地址布局和 runtime 预载逻辑。

## 关于“谁从文件读到 DDR”

进一步检查后，可以把这个问题分清楚：

`testarm.c` 是被编译成 RISC-V ELF 的 guest 程序，它运行在被模拟的 RISC-V CPU 上。它不负责从 host 文件系统打开 `cbuf_file.bin` / `micc_file.bin`。从它的视角看，`CBUF_DDR_ADDR`、`MICC_DDR_ADDR`、`SPM_DDR_ADDR` 这些 DDR 地址上已经有数据了。

文件读入 DDR 的动作应该发生在 host simulator runtime 初始化阶段，也就是 RISC-V guest 开始执行之前。现有证据：

1. `test/run_app_riscv.sh` 在启动 runtime 之前执行：

   ```sh
   cp testcase/application/${app_name}/result ./config -r
   cp testcase/application/${app_name}/input_data.bin ./config
   cp testcase/application/${app_name}/riscv/riscv ./config/riscv_program
   ../../core/bin/runtime ./ top.so topPara.so common/src/libcommon.so
   ```

   这说明 runtime 的工作目录下会有：

   ```text
   ./config/cbuf_file.bin
   ./config/micc_file.bin
   ./config/input_data.bin
   ./config/riscv_program
   ```

2. `common/src/basic_def.h` 定义了 simulator 侧约定文件名：

   ```c
   #define CBUF_MEM_FILE "./config/cbuf_file.bin"
   #define SPM_MEM_FILE  "./config/input_data.bin"
   #define MICC_MEM_FILE "./config/micc_file.bin"
   ```

3. `common/src/common_func.c` 里有 host 侧文件读取 helper：

   ```c
   int64_t read_file(void *data, uint64_t data_element_size, char *sub_file_name)
   {
       sprintf(file_name, "config/%s", sub_file_name);
       pFile = fopen(file_name, "rb");
       ...
       fread(data, data_element_size, amount, pFile);
   }
   ```

4. 顶层 `Makefile` 原本会编译这些 simulator 模块：

   ```make
   for dir in 'core' 'common' 'pe' 'spm' 'dma' 'mem' 'router' 'micc'; do ...
   ```

   但当前快照里实际只有 `common/` 和部分 `pe/`，没有 `dma/`、`mem/`、`micc/`、`spm/`、`router/`、`core/` 的用户侧源码，也没有 `top.so`、`topPara.so`、`core/bin/runtime`。因此，真正调用 `read_file(...)` 并把文件内容挂到 DDR 地址空间的模块不在当前快照里。

所以现在最合理的模型是：

```text
host shell:
  把 result/cbuf_file.bin 等复制到 ./config

host simulator runtime:
  读取 ./config/riscv_program，加载 RISC-V ELF
  读取 ./config/cbuf_file.bin，放入模拟 DDR 的 CBUF_DDR_ADDR 区域
  读取 ./config/micc_file.bin，放入模拟 DDR 的 MICC_DDR_ADDR 区域
  读取 ./config/input_data.bin，放入模拟 DDR 的 SPM_DDR_ADDR 区域
  启动 RISC-V guest

RISC-V guest testarm.c:
  DPU_CbufTransfer(CBUF_DDR_ADDR)
  DPU_MiccTransfer(MICC_DDR_ADDR)
  DPU_Kernel_Start(...)
```

也就是说，`DPU_CbufTransfer` 之前确实应该已经有“文件 -> DDR”的动作；只是这个动作不是 RISC-V 程序做的，而是 host simulator runtime 做的。当前仓库缺少 runtime/mem/dma 模块源码，所以这一环只能从脚本和公共 helper 推断，暂时不能源码级闭合。
