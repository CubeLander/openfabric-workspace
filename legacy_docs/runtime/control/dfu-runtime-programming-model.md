# DFU Runtime 编程模型：可重定位 Kernel 与运行期调用协议

日期：2026-06-02

本文只讨论 DFU runtime 的底层编程模型：如何从当前“固定地址 case”演进到可以接受动态 tensor buffer 的调用协议。

核心结论：

```text
不要把动态 tensor 地址做成每次实时重编译汇编；
应该把 kernel 编译成可重定位 artifact，
运行期通过 call frame 绑定真实 tensor buffer、SPM base 和 instance base_addr。
```

## 1. 当前固定地址模型的问题

当前 softmax 等 case 的地址绑定发生得太早：

```text
conf.h / conf_PEmap.h
  -> 固定 input/output DDR offset
  -> 固定 input/output SPM offset
  -> 固定 task/subtask/PE 切分
  -> 固定 HLDT/HSTT offset
  -> 编译生成 cbuf_file.bin / micc_file.bin
  -> testarm.c 按固定地址 DMA 搬运并启动
```

这对芯片功能验证是足够的，但对 runtime / torch 抽象不够。torch op 需要接受每次调用传入的 tensor：

```python
y = torch.ops.dfu.softmax(x, dim=-1)
```

这里 `x` 的 host pointer、device buffer、batch size、stride、输出地址都可能和上一次不同。如果每次地址变化都重新生成 CSV、重新 build_so、重新 build_app，runtime 开销会很高，也不符合正常 accelerator 调用模型。

## 2. 设计原则

地址绑定应该分成两层：

```text
编译期固定访问模式
运行期绑定真实地址
```

编译期决定：

```text
op 类型
shape / dtype / layout 约束
tiling 策略
task/subtask/PE/exeBlock 图
每个 PE 访问 tensor 内部的 offset pattern
operand RAM 分配
CBUF/MICC template
SPM scratch 需求
```

运行期决定：

```text
input tensor 实际 buffer
output tensor 实际 buffer
本次调用分配到的 SPM base
本次调用使用的 instance_conf.base_addr[]
DMA H2D / D2H descriptor
kernel launch 参数
```

换句话说：

```text
shape/layout/tiling 变化 -> 需要重新编译或换一个 cached kernel artifact
buffer 地址变化       -> 只需要 patch call frame / instance_conf / DMA descriptor
```

## 3. Kernel Artifact

编译器输出的不是一次性 case，而应该是可重定位 kernel artifact。

建议结构：

```text
CompiledKernel
  op_schema
  shape_constraints
  dtype_constraints
  layout_constraints
  task_subtask_plan
  pe_schedule_plan
  cbuf_template
  micc_template
  relocation_table
  base_slot_abi
  spm_requirement
  dma_plan_template
  debug_metadata
```

### 3.1 base slot ABI

当前指令模型里，LD/ST 类指令可以理解为：

```text
effective_spm_addr = instance_conf.base_addr[base_addr_idx] + inst_offset
```

这里：

- `base_addr_idx` 来自指令字段。
- `inst_offset` 来自 CSV/inst 中的立即数或地址字段。
- `instance_conf.base_addr[]` 来自运行时 instance 配置。

所以 kernel artifact 应该声明每个 base slot 的含义：

```text
base slot 0: scratch / sum_tmp
base slot 1: input0
base slot 2: output0
base slot 3: reserved / aux
```

具体 slot 编号可以根据现有 case 兼容调整，但必须形成稳定 ABI。这样指令可以固定写成：

```text
LD  base=input0_slot,  offset=row_offset + chunk_offset
ST  base=output0_slot, offset=row_offset + chunk_offset
```

运行期只 patch：

```text
instance_conf.base_addr[input0_slot]  = input_spm_base
instance_conf.base_addr[output0_slot] = output_spm_base
```

不用修改每条指令。

### 3.2 relocation table

并不是所有地址都一定能通过 base slot 表达。artifact 中应该记录需要运行期 patch 的字段：

```text
RelocEntry
  target_blob: cbuf | micc | instance_conf | dma_plan
  offset
  type: base_addr | size | stride | ddr_addr | spm_addr
  symbol: input0 | output0 | scratch0 | instance_base
```

MVP 可以先只支持：

```text
instance_conf.base_addr[] patch
DMA descriptor patch
```

后续如果发现某些指令 immediate 必须随 shape/stride 变化，再把它纳入 relocation table。

## 4. Runtime Call Frame

每次调用 kernel 时，runtime 构造一个 call frame：

```text
DfuCallFrame
  kernel_id
  tensor_bindings[]
  spm_allocations[]
  instance_conf_patch
  dma_h2d_plan
  dma_d2h_plan
  launch_desc
  sync_policy
```

其中 tensor binding 描述用户传入的 tensor：

```text
TensorBinding
  arg_id
  role: input | output | weight | scratch
  dtype
  shape
  stride
  layout
  host_ptr / device_buffer_handle
  byte_offset
  nbytes
```

SPM allocation 描述本次调用在片上 SPM 的布局：

```text
SpmAllocation
  symbol: input0 | output0 | scratch0
  spm_base
  bytes
  alignment
```

调用流程：

```text
1. runtime 接收 TensorBinding
2. 检查 shape/dtype/layout 是否匹配 kernel artifact
3. 为 input/output/scratch 分配 SPM base
4. patch instance_conf.base_addr[]
5. patch DMA descriptor，把 tensor buffer 搬到对应 SPM base
6. load 或复用 cbuf/micc
7. launch MICC
8. wait/sync
9. DMA output 从 SPM 搬回 output buffer
```

## 5. Host Tensor 地址如何进入 DFU

Linux 上普通 PyTorch CPU tensor 是进程虚拟地址，DFU/DMA 不能直接把这个地址当物理地址使用。

因此 runtime 需要两种 buffer 模型。

### 5.1 MVP：runtime-owned DMA buffer

第一版建议使用 runtime/driver 自己分配的 DMA buffer：

```text
torch CPU tensor
  -> memcpy 到 dfu_alloc() 返回的 pinned/coherent DMA buffer
  -> driver/DMA 把 buffer 搬到 SPM
  -> DFU 执行
  -> DMA 输出到 runtime buffer
  -> memcpy 回 torch CPU tensor
```

优点：

- driver 简单；
- cache coherency 容易处理；
- 适合先验证功能和数值正确性。

缺点：

- 多一次 host memcpy；
- 不是最终最高性能路径。

### 5.2 后续：pin 用户页并 dma_map

成熟版本可以支持用户传入普通 CPU tensor：

```text
runtime 接收 user virtual address
  -> driver pin user pages
  -> dma_map_sg
  -> DFU DMA 访问 scatter-gather 或合并后的 bounce buffer
```

这里需要处理：

- page pin/unpin 生命周期；
- cache flush/invalidate；
- IOMMU；
- scatter-gather 能力；
- 对齐和连续性限制；
- 异步调用期间 tensor 不能释放或移动。

如果硬件 DMA 不支持 scatter-gather，则仍然需要 driver bounce buffer。

## 6. 与现有 CBUF/MICC/SPM 的关系

现有模型：

```text
DRAM
  -> DMA
      -> CBUF / MICC / SPM
          -> PE operand RAM
              -> compute
```

新的编程模型不改变硬件执行路径，只改变“地址和调用参数何时绑定”：

```text
旧模型:
  编译 case 时写死 DDR/SPM 地址

新模型:
  编译 kernel 时只固定 tensor 内部 offset pattern
  launch 时绑定 tensor buffer 和 SPM base
```

CBUF/MICC 的使用方式：

```text
CBUF:
  存放可复用的 inst / exeBlock / instance template

MICC:
  存放 task/subtask config
  启动时根据 patched instance_conf 激活 PE

SPM:
  每次调用动态分配 input/output/scratch base
```

如果同一个 kernel 多次调用，理想情况是：

```text
第一次:
  load CBUF/MICC
  patch instance_conf
  launch

后续:
  复用 CBUF/MICC
  只更新 instance_conf / DMA plan
  launch
```

是否能做到只更新 instance_conf，需要进一步确认硬件/MICC 是否支持不重装全部 CBUF。当前 `DPU_Kernel_Start(inst_reload, ...)` 中已经有 `inst_reload` 参数，暗示至少存在“保留指令、只启动”的模式。

## 7. MVP 约束

为了尽快从固定 demo case 过渡到可调用 runtime，第一版建议强约束：

```text
只支持静态 shape
只支持 contiguous tensor
只支持 fp16 或当前 case 已验证 dtype
只支持同步 launch
只支持 runtime-owned DMA buffer
只支持单 DFU / 单 tile
只支持 input/output/scratch 的简单 SPM 静态分配
只通过 instance_conf.base_addr[] 和 DMA descriptor 做地址绑定
```

第一版不支持：

```text
动态 shape
任意 stride tensor
异步 stream
用户页直接 DMA
多 kernel 并发
跨芯片调度
完整 torch.device backend
```

这不是能力边界，而是为了把风险压到最低，先验证核心 ABI。

## 8. 对 softmax 的示例

当前 softmax `{64, 512}` 可以抽象为：

```text
CompiledKernel: softmax_lastdim_64x512_fp16
  input0 slot  = base_addr[1]
  output0 slot = base_addr[2]
  scratch slot = base_addr[0]
  task_num = 4
  each task uses 16 PE
  each PE handles one row of 512 fp16
```

编译期固定：

```text
row -> task/PE 映射
每行 512 fp16 的 LD/ST offset pattern
subtask 内部 reduce / exp / div 指令序列
```

运行期绑定：

```text
input tensor buffer
output tensor buffer
input_spm_base
output_spm_base
sum_tmp_spm_base
DMA input from tensor -> input_spm_base
DMA output output_spm_base -> tensor
```

如果下一次调用仍是 `{64,512}`，但 input/output buffer 变了：

```text
不重新编译 softmax 指令
只重新分配/绑定 SPM base 和 DMA buffer
```

如果 shape 变成 `{128,512}` 或 `{64,1024}`：

```text
需要查找 cached kernel artifact
如果没有，则重新编译一个新 artifact
```

## 9. 需要继续确认的问题

当前设计依赖几个硬件/模拟器假设，需要后续实验确认：

- `instance_conf.base_addr[]` 是否确实能作为 LD/ST 的运行期 base。
- `base_addr_idx` 与 `instance_conf.base_addr[]` 的真实绑定规则。
- 是否可以只更新 instance config，而不重装完整 CBUF/MICC。
- MICC 启动时是否会重新读取 instance_conf，还是只在 CBUF 装载时读取一次。
- `inst_reload = 0` 时硬件具体保留哪些状态。
- DMA 是否支持真实硬件上的 scatter-gather。
- SPM 是否需要软件 allocator，还是硬件/MICC 有隐藏分配机制。
- 多 task/subtask 并发时，不同 call frame 的 SPM 生命周期如何管理。

这些问题不影响 MVP 编程模型成立，但会影响 runtime 的性能和可复用程度。

## 10. 最终抽象

目标抽象可以概括为：

```text
CompiledKernel = 可重定位的 DFU 低层程序
CallFrame      = 一次具体调用的地址绑定和资源绑定
Runtime        = 负责 buffer、SPM、DMA、CBUF/MICC、launch/sync
Torch op       = Runtime 之上的用户接口
```

也就是：

```text
torch tensor
  -> TensorBinding
      -> DfuCallFrame
          -> patch instance_conf / DMA plan
              -> launch CompiledKernel
                  -> result tensor
```

