# 从类 Torch 视角理解这套 DPU 框架

这篇文档故意不从 `common_oper`、CSV、runtime 这些底层东西开始。我们先假设读者脑子里有一个熟悉的模型：

```python
y = torch.softmax(x, dim=-1)
```

然后问：如果这个 softmax 要放到这个 DPU/GPDPU 项目里执行，仓库里到底发生了什么？

先说结论：当前仓库里没有真正的 PyTorch frontend，也没有 `torch.ops.xxx` 这种 Python/C++ binding。这里的 "torch 视角" 是一个心智模型，用来帮助理解这套原始工具链如何手工模拟一个深度学习框架该做的事。

## 类 Torch 调用在这里对应什么

在 PyTorch 里，一个算子调用大概包含这些概念：

```text
operator name      softmax
input tensor       x
output tensor      y
shape              [batch, hidden]
device memory      x/y 在 GPU/NPU device 上的地址
kernel binary      编译好的 kernel
launch params      grid/block/shared memory/stream
copy in/out        host <-> device
runtime            CUDA/HIP/NPU runtime
```

在这个仓库里，对应关系大概是：

```text
operator name
  -> csv_generate/conf_PEmap.h::case_name
  -> mark_op
  -> gpdpu_TestOp/task_main.cpp 里的 op 选择

input/output tensor
  -> conf.h 里的 softmax0_input0 / softmax0_output0 size 和地址
  -> conf_PEmap.h 里的 name2arraysize / Secondary_Fusion_Array
  -> spm_data/input_data.bin / result_check.c

device memory
  -> DDR 固定地址段
  -> SPM base slot / SPM offset
  -> conf.h 中的 MEM_* / SPM_* / *_ddrStartAddr / *_spmStartAddr

kernel source
  -> gpdpu_TestOp/task*/subtask*/template/*.cpp

kernel assembly IR
  -> task*/subtask*/template/*.csv

kernel packed binary
  -> simulator_bin/*
  -> result/cbuf_file.bin
  -> result/micc_file.bin

kernel launch
  -> riscv/testarm.c
  -> DPU_Kernel_Start(...)
  -> MICC_* MMIO registers

copy in/out
  -> riscv/testarm.c
  -> DMA_Transfer_inoutArray(...)
  -> input DDR -> SPM
  -> output SPM -> DDR

runtime
  -> core/bin/runtime
  -> SimICT module graph
  -> top.so / topPara.so / libcommon.so
```

## 这套系统没有“张量对象”

现代框架里会有一个 tensor object，里面至少有：

```text
data pointer
shape
stride
dtype
device
```

这个仓库不是这样。它没有一个统一的 runtime tensor 对象。它更多是用一堆手写 C header 表达 tensor 的静态布局。

以 `softmax_1/csv_generate/conf.h` 为例：

```c
#define softmax0_input0_SIZE 32768
#define softmax0_output0_SIZE 32768

#define MEM_softmax0_input0_ADDR 0
#define MEM_softmax0_output0_ADDR 0

#define SPM_softmax0_input0_ADDR 0
#define SPM_softmax0_output0_ADDR 16384
#define SPM_SUM_ADDR 32768

#define APP_NUM 1
#define SUBTASK_NUM 2
#define TASK_NUM 4
```

这些宏和数组共同表达：

- input/output 有多大；
- 它们在 DDR 或 SPM 中从哪里开始；
- 中间 buffer 放哪里；
- 有多少 app/task/subtask；
- 每个 task 用多少 PE；
- DMA 应该搬多长。

所以如果从 torch 视角看，这个仓库把 tensor metadata 拆散到了：

```text
conf.h
conf_PEmap.h
spm_data/data.h
riscv/testarm.c
template cpp
```

而不是封装成一个对象。

## “调用 softmax”在这里怎么发生

在 PyTorch 里，用户写：

```python
y = torch.softmax(x)
```

runtime 会 dispatch 到某个 backend kernel。

在这个仓库里，没有这种动态 dispatch。它是静态 case 驱动：

```text
conf_PEmap.h:
  static string case_name = "softmax";
  #define mark_op "SOFTMAX"

gpdpu_TestOp/task_main.cpp:
  读取 case_name
  构造 softmax op
  调用对应 task/subtask template

template/*.cpp:
  生成每个 PE 的 CSV 指令
```

也就是说，"softmax 被引用"不是运行时用户调用发生的，而是 case 编译时由 `case_name` 选出来的。

更像这样：

```python
# 伪代码，不是仓库真实代码
case = load_static_case("softmax_1")
op = case.case_name              # "softmax"
templates = select_templates(op)
csv_files = templates.emit_csv(case.conf)
binary = common_oper.assemble(csv_files)
```

## 输入数据怎么进去

从 torch 视角，一般是：

```python
x_device = x_cpu.to("dpu")
```

在这个仓库里，输入进入 DPU 的路径更手工：

```text
spm_data/input_data.bin
  -> testcase/application/<app>/input_data.bin
  -> test/run_app_riscv.sh copies it to ./config/input_data.bin
  -> SimICT memory model exposes it as DDR content
  -> riscv_program runs DMA_Transfer_inoutArray(...)
  -> DMA copies input DDR -> SPM
```

关键脚本：

```sh
cp testcase/application/${app_name}/input_data.bin ./config
cp testcase/application/${app_name}/riscv/riscv ./config/riscv_program
```

关键 RISC-V 控制程序：

```text
riscv/testarm.c
```

关键地址：

```text
CBUF_DDR_ADDR
MICC_DDR_ADDR
SPM_DDR_ADDR
SPM_RST_DDR_ADDR
```

所以这里的输入不是通过一个 runtime tensor API 传进去，而是通过文件和模拟内存布局喂进去。

## device memory 怎么被引用

现代框架里，kernel 拿到的是 device pointer。

这个仓库里，算子模板和控制程序引用的是静态地址/slot：

```text
MEM_softmax0_input0_ADDR
MEM_softmax0_output0_ADDR
SPM_softmax0_input0_ADDR
SPM_softmax0_output0_ADDR
SPM_SUM_ADDR
softmax0_input0_ddrStartAddr[]
softmax0_input0_spmStartAddr[]
softmax0_output0_ddrStartAddr[]
softmax0_output0_spmStartAddr[]
```

还有 `conf_PEmap.h`：

```c
static map<string, pair<unsigned, unsigned>> Secondary_Fusion_Array = {
    {"SUM", {0,32768}},
    {"softmax0_input0", {0,0}},
    {"softmax0_output0", {0,16384}}
};

static map<string, pair<unsigned, unsigned>> name2arraysize = {
    {"softmax0_input0", {32768,0}},
    {"softmax0_output0", {32768,0}}
};
```

这些就是这个项目里的“device memory descriptor”。

但是它没有 allocator，没有 `cudaMalloc` 风格的 API，也没有动态 shape。地址和大小基本都是 case 里提前算好、写死或半手工维护。

## kernel binary 是什么

PyTorch/CUDA 里可能有 cubin、ptx、hsaco、engine binary。

这里的 kernel binary 分散成几类：

```text
CBUF binary
MICC/task config binary
SPM/input binary
subtask simulator_bin
RTL bin
```

关键生成链路：

```text
template/*.cpp
  -> template/*.csv
  -> common_oper
  -> simulator_bin/*
  -> result/cbuf_file.bin
  -> result/micc_file.bin
```

`CBUF` 可以理解为某类控制/配置 buffer；`MICC` 更接近任务调度/实例配置入口；`SPM` 是 device scratchpad memory。

## kernel 怎么 launch

PyTorch 里是 runtime 调 backend launch API。

这个仓库里是 RISC-V 控制程序写 MMIO：

```text
riscv/testarm.c
  -> DPU_Kernel_Start(...)
      -> writes MICC registers
```

关键点：

- host x86 不直接启动 DPU kernel；
- SimICT runtime 也不是直接说“跑 softmax”；
- 真正的启动信号来自模拟 RISC-V 程序；
- RISC-V 程序通过 `DpuAPI.c` 写 MICC/DMA/CBUF 寄存器；
- 模拟器 device module 收到这些 MMIO 后，才推动 MICC/PE/DMA/SPM 模块工作。

所以从上层看：

```text
run_app_riscv.sh starts simulator
simulator starts RISC-V program
RISC-V program starts DPU task
DPU modules execute packed binary
```

## 输出怎么拿出来

从 torch 视角：

```python
y_cpu = y_device.cpu()
```

在这里：

```text
DPU/PE writes output into SPM
  -> RISC-V 控制程序发起 output DMA
  -> output SPM -> DDR
  -> simulator dumps gpdpu_data
  -> run_app_riscv.sh copies gpdpu_data back to spm_data
  -> spm_data/check.sh checks result
```

顶层脚本最后做：

```sh
cp gpdpu_data testcase/application/${app_name}/spm_data
mv gpdpu_data testcase/application/${app_name}/rtl_bin_multi_app

cd testcase/application/${app_name}/spm_data
./check.sh > ../../../../test/check.log
```

所以输出不是返回给 Python 对象，而是通过模拟器 dump 文件和 check 脚本验证。

## 运行时到底知道不知道这是 softmax

基本不知道。

`core/bin/runtime` 看到的是：

```text
top.so
topPara.so
common/src/libcommon.so
module .so
port_info
object graph
thread args
messages
```

它关心的是 SimICT object/message graph，不关心“softmax”这个数学语义。

softmax 语义主要存在于：

```text
conf_PEmap.h::case_name
gpdpu_TestOp/task_main.cpp
task*/subtask*/template/*.cpp
生成出来的 CSV 指令序列
```

到 runtime 层时，softmax 已经变成：

```text
RISC-V 控制程序
CBUF/MICC/SPM binary
PE 指令流
device module message
```

## 自顶向下的一张图

```text
用户想跑一个算子
  |
  v
选择/复制一个 case 目录
  |
  v
手工维护 conf.h / conf_PEmap.h
  - op name
  - tensor size
  - DDR/SPM layout
  - task/subtask/PE mapping
  |
  v
手写/修改 task*/subtask*/template/*.cpp
  - 定义每个 PE 要生成什么 CSV
  |
  v
运行 case/run.sh
  |
  +--> csv_generate/run.sh
  |      -> app/task/subtask conf
  |      -> template/*.csv
  |      -> simulator_bin / rtl_bin
  |      -> spm_data
  |
  +--> riscv/make
         -> riscv/riscv
  |
  v
运行 test/run_app_riscv.sh
  |
  v
config/
  - result/*
  - input_data.bin
  - riscv_program
  |
  v
core/bin/runtime ./ top.so topPara.so common/src/libcommon.so
  |
  v
SimICT runtime
  - 加载模块图
  - 启动模拟 RISC-V
  - RISC-V 发 DMA/MICC MMIO
  - DPU 模块通过 timed messages 执行
  |
  v
gpdpu_data / check.log
```

## 如果要类比 PyTorch，这里每一层是谁

| PyTorch / CUDA 概念 | 本仓库里的对应物 |
| --- | --- |
| Python op call | 没有动态 frontend；由 case 目录和 `case_name` 静态选择 |
| Tensor metadata | `conf.h` / `conf_PEmap.h` / `spm_data/data.h` |
| Device allocator | 基本没有；SPM/DDR 地址手工静态规划 |
| Kernel source | `task*/subtask*/template/*.cpp` |
| IR / assembly | `template/*.csv` |
| Backend compiler | `testcase/common_oper` |
| Kernel binary | `simulator_bin/*`, `result/cbuf_file.bin`, `result/micc_file.bin` |
| Runtime launch API | `DPU_Kernel_Start()` 写 MICC MMIO |
| H2D/D2H copy | `DMA_Transfer_inoutArray(...)` |
| Device runtime | SimICT module graph + `core/bin/runtime` |
| Result tensor | `gpdpu_data` + `spm_data/check.sh` |

## 最重要的心智转换

不要从 “这个 op 的 C++ 函数在哪里被调用” 开始找。

更应该这样看：

```text
这个 case 静态声明了一个 op
这个 op 的后端模板静态生成 CSV
CSV 被工具链静态打包
RISC-V 程序按静态配置启动任务
runtime 只执行已经打包好的设备模型事件
```

这就是为什么这个技术栈看起来不像 torch，也不像 TVM/XLA。它更像一个早期芯片项目里的手工后端开发环境：开发者直接面对 tensor layout、SPM、PE、CSV 指令、MMIO 和模拟器。

