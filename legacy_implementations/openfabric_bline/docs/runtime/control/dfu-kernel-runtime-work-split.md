# DFU Kernel / Runtime 工作拆分：加载、通信、同步、内存和 Swap

日期：2026-06-02

本文承接 `dfu_runtime_programming_model.md`，把下一阶段需要做的 kernel 侧和 runtime 侧工作拆开。这里的 “kernel” 有两层含义：

```text
DFU device kernel:
  编译出来给 DFU 执行的 cbuf/micc/instance/spm 相关 artifact。

Linux kernel driver:
  Linux 内核中的 /dev/dfu0 驱动，负责 MMIO、DMA buffer、ioctl、interrupt、内存映射。
```

runtime 则是用户态库，例如 `libdfu_runtime.so`，位于 PyTorch extension 和 Linux driver 之间。

## 1. 总体分层

建议软件栈分成 5 层：

```text
PyTorch / Python
  -> torch.ops.dfu.* / FX lowering
      -> libdfu_runtime.so
          -> Linux driver: /dev/dfu0
              -> DFU hardware: DMA + CBUF/MICC/SPM + PE
```

对应职责：

```text
PyTorch 层:
  tensor 语义、op schema、golden test、用户 API。

runtime 层:
  kernel cache、call frame、buffer 管理、SPM planning、DMA plan、launch/sync。

Linux driver 层:
  MMIO、DMA mapping、interrupt、fence/event、进程隔离、资源回收。

DFU device kernel/artifact:
  cbuf/micc/instance template、base slot ABI、task/subtask/PE schedule。

hardware 层:
  DMA 搬运、MICC 调度、PE 执行、SPM/operand RAM 访问。
```

## 2. DFU device kernel 如何传进去

当前固定 case 的输入是：

```text
cbuf_file.bin
micc_file.bin
input_data.bin
riscv_program
```

面向 runtime 后，应该拆成：

```text
CompiledKernel package
  cbuf_template
  micc_template
  instance_template
  relocation_table
  metadata.json
```

传入硬件时分两步：

```text
1. load kernel artifact
   runtime -> driver -> DMA -> CBUF/MICC 区

2. launch call frame
   runtime patch instance_conf / DMA descriptor
   driver 写 MICC start/task/instance_base
   hardware 执行
```

推荐 API：

```c
dfu_kernel_t* dfu_load_kernel(dfu_device_t* dev,
                              const dfu_kernel_package_t* package);

int dfu_launch_kernel(dfu_device_t* dev,
                      dfu_kernel_t* kernel,
                      const dfu_call_frame_t* frame,
                      dfu_event_t* done);
```

这里要区分：

```text
kernel load:
  重的操作，涉及 CBUF/MICC 装载，可以缓存。

kernel launch:
  轻的操作，只绑定本次 tensor、SPM base、instance_conf 和 DMA plan。
```

如果硬件支持 `inst_reload = 0`，同一个 kernel 多次调用时应优先复用已装载 CBUF/MICC，只更新本次 call frame。

## 3. 通信模型

runtime 和 driver 的通信建议走 ioctl + mmap：

```text
open("/dev/dfu0")
  -> ioctl(DFU_ALLOC_BUFFER)
  -> mmap DMA buffer 或 command/status region
  -> ioctl(DFU_LOAD_KERNEL)
  -> ioctl(DFU_SUBMIT)
  -> wait event / poll / epoll
```

最小 ioctl 集合：

```text
DFU_GET_INFO
DFU_ALLOC_BUFFER
DFU_FREE_BUFFER
DFU_LOAD_CBUF
DFU_LOAD_MICC
DFU_PATCH_INSTANCE
DFU_SUBMIT_DMA
DFU_SUBMIT_KERNEL
DFU_WAIT
DFU_QUERY_STATUS
DFU_RESET
```

MVP 可以更简单：

```text
DFU_GET_INFO
DFU_ALLOC_BUFFER
DFU_FREE_BUFFER
DFU_RUN
DFU_WAIT
```

其中 `DFU_RUN` 一次性带上：

```text
cbuf/micc 是否需要重装
DMA H2D plan
instance_conf patch
launch desc
DMA D2H plan
```

这样先建立功能闭环，之后再拆成更细粒度的异步 submit。

## 4. 同步模型

同步需要同时覆盖三类事件：

```text
DMA H2D 完成
DFU kernel 完成
DMA D2H 完成
```

最小同步流程：

```text
submit H2D DMA
wait H2D done
write MICC start
wait MICC finish
submit D2H DMA
wait D2H done
return to user
```

早期可以用 polling：

```text
轮询 DMA_TRANS_DONE
轮询 MICC_BUF_FINISH
```

工程化版本应使用 interrupt + event/fence：

```text
dfu_event_t
  status: pending | complete | error
  timeline_seq
  error_code
  profiling timestamps
```

PyTorch custom op 第一版可以同步等待：

```python
y = torch.ops.dfu.softmax(x)
# 返回时结果已经可用
```

后续再支持异步：

```python
event = dfu.launch(...)
event.wait()
```

不建议一开始设计复杂 stream。先做单 queue / in-order execution：

```text
queue0:
  H2D -> kernel -> D2H
  H2D -> kernel -> D2H
```

等单队列稳定后，再考虑多 queue、多 stream、重叠 DMA 和 compute。

## 5. 结果回收模型

结果回收本质是 output tensor 的所有权和可见性问题。

MVP：

```text
runtime 分配 output DMA buffer
DFU 写 SPM output
runtime/driver DMA SPM -> output DMA buffer
runtime memcpy 到 torch CPU tensor
返回 torch tensor
```

更成熟版本：

```text
torch tensor 绑定到 pinned/mapped buffer
DFU D2H 直接写到该 buffer
runtime 做 cache invalidate / sync
返回时 tensor 可读
```

需要定义 buffer state：

```text
HostClean:
  host 可读写，device 不持有最新数据。

DeviceClean:
  device 侧/SPM/DRAM 中有最新数据，host 需要同步后才能读。

InFlight:
  DMA 或 kernel 正在使用，不能释放或复用。

Error:
  上一次执行失败，需要 reset 或丢弃。
```

每次 launch 结束后，runtime 根据 output policy 决定：

```text
copy_back:
  立即 D2H，返回 CPU tensor。

keep_on_device:
  保留在 DFU DRAM/SPM/device buffer 中，作为下一个 kernel 输入。

discard:
  中间 scratch，生命周期结束后释放。
```

对于 torch custom op 第一版，建议全走 `copy_back`。对于 transformer block 和 Qwen 部署，必须逐步支持 `keep_on_device`，否则每个算子都回 CPU 会完全吃掉性能。

## 6. 内存 claim / allocator

需要至少三类内存管理：

```text
Host DMA buffer allocator:
  Linux driver/runtime 管理 pinned/coherent buffer。

Device DRAM allocator:
  管理 DFU 可访问的外部 DRAM 或 simulator DDR 地址空间。

SPM allocator:
  管理每次 kernel 调用的片上 SPM input/output/scratch base。
```

### 6.1 Host DMA buffer

MVP 使用 runtime-owned buffer：

```c
dfu_buffer_t dfu_alloc_host_dma(size_t bytes, size_t align);
void*        dfu_buffer_host_ptr(dfu_buffer_t);
uint64_t     dfu_buffer_dma_addr(dfu_buffer_t);
```

后续支持 user tensor pin：

```c
dfu_buffer_t dfu_pin_user_pages(void* ptr, size_t bytes);
```

### 6.2 Device DRAM allocator

如果真实硬件有 DFU 可访问的片外 DRAM，需要 runtime 管理逻辑地址：

```text
device_dram_malloc(bytes)
device_dram_free(handle)
device_dram_to_spm(handle, spm_base, bytes)
spm_to_device_dram(spm_base, handle, bytes)
```

这层会变成模型权重、KV cache 和中间 tensor 的主要驻留地。

### 6.3 SPM allocator

SPM 是每次执行的高价值临时资源。第一版用静态规划：

```text
input0_spm_base
input1_spm_base
output0_spm_base
scratch0_spm_base
```

成熟版本需要 lifetime-based planner：

```text
根据 graph 中 tensor 生命周期复用 SPM 区域
根据 kernel spm_requirement 分配 scratch
根据 task/subtask 并发关系避免冲突
```

SPM allocator 应该是 runtime 管理，不建议让每个 op 手写固定 SPM 地址。

## 7. 自动/半自动 DRAM swap

这里的 swap 不应一开始做成完全自动、不可见的系统级换页。更现实的路线是分层演进。

### 7.1 第一阶段：显式 copy

runtime API 显式管理：

```text
copy host -> device DRAM
copy device DRAM -> SPM
launch kernel
copy SPM -> device DRAM
copy device DRAM -> host
```

优点是行为可控，便于 debug。

### 7.2 第二阶段：半自动 residency manager

runtime 维护 tensor residency：

```text
TensorStorage
  host_state
  device_dram_state
  spm_state
  last_use
  size
  pin_priority
```

当 kernel 需要输入时：

```text
if tensor already in SPM:
  直接绑定 SPM base
elif tensor in device DRAM:
  DMA device DRAM -> SPM
elif tensor in host:
  DMA host -> SPM 或 host -> device DRAM -> SPM
```

当 SPM/DRAM 不够时：

```text
evict clean tensor
writeback dirty tensor
prefer evict low-priority / far-next-use tensor
```

这就是半自动 swap：runtime 负责搬，但 compiler/scheduler 可以给出 hint。

### 7.3 第三阶段：面向模型的 memory scheduler

Qwen 这种模型需要根据层顺序和 KV cache 生命周期做调度：

```text
权重:
  分层驻留或流式加载。

KV cache:
  频繁读写，优先放 device DRAM；
  当前层/当前 token 需要的 tile 进入 SPM；
  长上下文时可考虑压缩、分片、host offload。

中间激活:
  生命周期短，优先 SPM 复用。
```

这里应该采用 compiler/runtime 协作：

```text
compiler:
  提供每个 tensor 的 size、lifetime、next_use、reuse distance。

runtime:
  根据实际内存压力执行 prefetch / evict / writeback。
```

## 8. Kernel package 和 Runtime 的 ABI

为了让 runtime 能管理内存和 swap，kernel artifact 不能只是裸 `cbuf_file.bin/micc_file.bin`，必须带 metadata。

建议 metadata：

```text
kernel_name
version
op_schema
input_desc[]
output_desc[]
scratch_desc[]
base_slot_abi[]
spm_requirement
device_dram_requirement
dma_plan_template
relocation_table
profile_points
debug_symbols
```

示例：

```text
input0:
  dtype = fp16
  shape = [64, 512]
  layout = contiguous
  base_slot = 1
  access_pattern = read_only

output0:
  dtype = fp16
  shape = [64, 512]
  layout = contiguous
  base_slot = 2
  access_pattern = write_only

scratch0:
  bytes = 4096
  base_slot = 0
```

没有这层 ABI，runtime 就无法知道哪些 buffer 要搬、哪些结果要回收、哪些 scratch 可以复用。

## 9. 推荐 MVP 工作包

### W1：Kernel package 格式

交付：

```text
CompiledKernel metadata schema
cbuf/micc/instance template 打包格式
base_slot_abi
relocation_table MVP
```

### W2：Runtime buffer 和 SPM allocator

交付：

```text
runtime-owned DMA buffer
简单 device DRAM address allocator
静态 SPM planner
TensorBinding -> SpmAllocation
```

### W3：Driver 最小 ioctl

交付：

```text
/dev/dfu0
alloc/free DMA buffer
load CBUF/MICC
submit H2D/kernel/D2H
poll/wait finish
error/status query
```

### W4：同步和结果回收

交付：

```text
in-order queue
dfu_event_t
copy_back output policy
buffer state machine
```

### W5：Softmax 端到端验证

交付：

```text
softmax kernel package
runtime call frame
torch.ops.dfu.softmax
PyTorch golden diff
simulator backend 和 board backend 对齐
```

## 10. 关键判断

我们需要的不是“每个算子写死 DMA 地址”的接口，而是：

```text
kernel artifact 描述访问模式；
runtime call frame 绑定真实 tensor；
driver 保证 DMA/MMIO/sync；
memory manager 决定数据在哪一层驻留；
scheduler 决定何时 prefetch、何时 evict。
```

第一版可以非常朴素：

```text
host tensor -> runtime DMA buffer -> SPM -> DFU -> SPM -> runtime DMA buffer -> host tensor
```

但接口设计必须给后续演进留下位置：

```text
keep_on_device
device DRAM residency
SPM reuse
async event
semi-auto DRAM swap
KV cache special policy
```

