# 可重定位 DFU Kernel 的实现方案

日期：2026-06-02

本文回答一个具体问题：在当前已经还原出的底层 ABI 背景下，“可重定位 kernel”应该如何实现。

核心判断：

```text
当前 ABI 已经有可重定位雏形：

LD/ST 指令:
  base_addr_idx + imm offset

instance_conf_info_t:
  base_addr[MAX_BASE_ADDR_PER_SUBTASK]

tempfile.h:
  tensor name -> base slot 编号
```

所以第一版不需要每次 tensor 地址变化时重编译 CSV/汇编/CBUF；应该把 `instance_conf_info_file.bin` 变成运行期可 patch 的 instance template。

## 1. 当前 ABI 的重定位抓手

### 1.1 base_addr_idx

底层 LD/ST RTL 指令中有：

```c
uint64_t base_addr_idx:4;
uint64_t imm:21;
```

在 `task_print.cpp` 写 RTL 指令时，LD/ST 的 `base_addr_idx` 来自：

```c
ldst_inst.base_addr_idx = tmp_inst.iter_exe_cond;
ldst_inst.imm = tmp_inst.imms[0];
```

也就是说，一条 LD/ST 指令不是只带一个绝对地址，而是可以理解为：

```text
effective_spm_addr = base_addr[base_addr_idx] + imm
```

这里 `imm` 是编译期固定的 tensor 内部 offset，`base_addr[base_addr_idx]` 可以运行期替换。

### 1.2 instance_conf_info_t

当前结构体：

```c
typedef struct _instance_conf_info_t {
    uint64_t base_addr[MAX_BASE_ADDR_PER_SUBTASK];
} instance_conf_info_t;
```

这就是最自然的运行期重定位表。

对 softmax，当前 `tempfile.h` 已经给出了 base slot 语义：

```c
static map<string, int> array_name_to_base_num = {
  {"SUM", 0},
  {"softmax0_input0", 1},
  {"softmax0_output0", 2}
};
```

因此第一版 ABI 可以定义为：

```text
base slot 0: scratch / SUM
base slot 1: input0
base slot 2: output0
base slot 3: reserved
```

## 2. 实现策略

### 2.1 编译期仍然生成完整 case

第一版不要大改现有编译链。仍然使用当前流程生成：

```text
insts_file.bin
exeblock_conf_info_file.bin
tasks_conf_info_file.bin
subtasks_conf_info_file.bin
instance_conf_info_file.bin
cbuf_file.bin
micc_file.bin
```

但在打包成 runtime kernel package 时，把这些产物拆开保存：

```text
kernel.pkg/
  cbuf_template.bin
  micc_template.bin
  instance_template.bin
  metadata.json
```

其中：

```text
cbuf_template.bin:
  insts_file.bin + exeblock_conf_info_file.bin + instance_template.bin

micc_template.bin:
  tasks_conf_info_file.bin + subtasks_conf_info_file.bin
```

注意：当前 `cbuf_file.bin` 里包含 instance 配置。因此如果要运行期 patch instance，有两种方式：

1. patch `cbuf_template.bin` 中 instance 区后，再整体 load CBUF；
2. 如果硬件支持单独更新 CBUF instance 区，则只 DMA 更新 `CBUF_ISTC_BASE` 对应区域。

MVP 可以先选择方式 1，虽然慢一点，但验证最稳。

### 2.2 metadata 记录 base slot ABI

`metadata.json` 必须记录：

```json
{
  "kernel_name": "softmax_lastdim_64x512_fp16",
  "base_slots": [
    {"slot": 0, "symbol": "SUM", "role": "scratch"},
    {"slot": 1, "symbol": "softmax0_input0", "role": "input"},
    {"slot": 2, "symbol": "softmax0_output0", "role": "output"}
  ],
  "instance_conf": {
    "entry_size": 32,
    "entries": 8,
    "base_addr_count": 4
  }
}
```

后续再增加：

```text
shape constraints
dtype constraints
SPM bytes
DMA plan template
relocation table
debug symbols
```

### 2.3 运行期 patch instance_conf

runtime 每次 launch 时：

```text
1. 为 input/output/scratch 分配 SPM base
2. 复制 instance_template
3. 遍历每个 instance_conf_info_t entry
4. 根据 base slot ABI 写入新的 base_addr[]
5. 生成 patched_instance.bin 或 patched_cbuf.bin
```

伪代码：

```c
for each instance in instance_template:
    instance.base_addr[SUM_SLOT]    = call_frame.scratch_spm_base + instance.scratch_delta;
    instance.base_addr[INPUT0_SLOT] = call_frame.input0_spm_base  + instance.input0_delta;
    instance.base_addr[OUTPUT0_SLOT]= call_frame.output0_spm_base + instance.output0_delta;
```

这里有一个重要细节：原始 `instance_conf_info_file.bin` 里每个 instance 的 base_addr 可能不是同一个值，而是已经包含了 task/instance 的行偏移。

所以 patch 时不能简单把所有 entry 写成同一个 base；应该保留每个 entry 相对第一个 entry 的 delta：

```text
delta[entry][slot] = original_base_addr[entry][slot] - original_base_addr[first_valid_entry][slot]

patched_base_addr[entry][slot]
  = runtime_symbol_base[slot] + delta[entry][slot]
```

这一步是实现可重定位 kernel 的关键。

## 3. Relocation Table 如何生成

第一版 relocation table 可以从 `instance_template.bin` 和 `metadata.json` 推导，不需要解析每条 inst：

```text
RelocEntry
  target = instance_conf
  entry_idx
  base_slot
  symbol
  delta
```

生成方法：

```text
读取 instance_conf_info_file.bin
读取 tempfile.h 中 tensor -> slot
找每个 slot 的第一个有效 base
对每个 instance entry 计算 delta
写入 metadata.json
```

示例：

```json
{
  "relocations": [
    {"entry": 0, "slot": 1, "symbol": "input0", "delta": 0},
    {"entry": 1, "slot": 1, "symbol": "input0", "delta": 256},
    {"entry": 2, "slot": 1, "symbol": "input0", "delta": 512}
  ]
}
```

对于 softmax，这些 delta 对应“每个 PE/instance 处理哪一行”的 SPM offset。

## 4. CBUF/MICC 装载方式

### 4.1 最保守方式：每次 patch 后整体重装

流程：

```text
runtime patch cbuf_template 中的 instance 区
  -> DPU_CbufTransfer(patched_cbuf)
  -> DPU_MiccTransfer(micc_template)
  -> DPU_Kernel_Start(inst_reload=1, ...)
```

优点：

- 最接近当前固定 case；
- 不依赖硬件是否支持局部更新 instance 区；
- 最适合 MVP 验证。

缺点：

- 每次 launch 都重装 CBUF/MICC，性能差。

### 4.2 中间方式：只更新 CBUF instance 区

如果 DMA 可以写 `CBUF_ISTC_BASE`：

```text
第一次:
  load insts + exeblock + instance + micc

后续:
  只 DMA patched_instance 到 CBUF_ISTC_BASE
  DPU_Kernel_Start(inst_reload=0, ...)
```

这需要确认：

- MICC/PE 每次启动时是否重新读取 instance_conf。
- `inst_reload=0` 时是否会保留旧指令但接受新 instance。
- `DPU_Cbuf_ISTC_Transfer()` 是否能独立更新 instance 区。

当前 `DpuAPI.c` 里确实有 `DPU_Cbuf_ISTC_Transfer()`，这是很好的线索。

### 4.3 理想方式：runtime command buffer

成熟后可以把 instance patch 做成真正的 command buffer：

```text
command buffer:
  load/patch instance
  H2D DMA
  launch
  D2H DMA
```

但这需要 driver/runtime 更完整，不是第一版目标。

## 5. DMA 地址也要重定位

可重定位 kernel 只解决 PE 侧 LD/ST 对 SPM 的访问。真正的 tensor buffer 还要通过 DMA 进入 SPM。

因此每次 call frame 还要 patch DMA plan：

```text
input tensor host/device address -> input_spm_base
output_spm_base -> output tensor host/device address
```

这部分不应进入 DFU 指令，而是 runtime/driver 的责任：

```text
TensorBinding
  host/device buffer handle
  byte offset
  nbytes

SpmAllocation
  symbol
  spm_base
  bytes

DMA plan:
  src buffer + offset
  dst spm_base
  bytes / slice info
```

所以完整重定位有两类：

```text
PE-side relocation:
  patch instance_conf.base_addr[]

DMA-side relocation:
  patch H2D/D2H DMA descriptors
```

## 6. 哪些变化需要重新编译

不需要重新编译：

```text
input/output buffer 地址变化
本次 SPM base 变化
host DMA buffer 变化
output 选择 copy_back 或 keep_on_device
```

需要换 kernel artifact 或重新编译：

```text
shape 改变导致 task/PE 切分改变
dtype 改变
layout/stride 改变
softmax axis 改变
tiling 策略改变
operand RAM 分配改变
LD/ST offset pattern 改变
```

可以通过 kernel cache 管理：

```text
cache_key = op + dtype + normalized_shape + layout + tiling_policy
```

## 7. MVP 实现步骤

### Step 1：抽取 kernel package

从现有 case 产物生成：

```text
metadata.json
cbuf_template.bin
micc_template.bin
instance_template.bin
```

先以 softmax `{64,512}` 为样例。

### Step 2：生成 base slot metadata

解析或复用 `tempfile.h`：

```text
SUM -> slot 0
input0 -> slot 1
output0 -> slot 2
```

建议后续不要依赖 C++ `map` 文本，而是在编译器里直接输出 JSON。

### Step 3：生成 instance relocation delta

读取 `instance_template.bin`，对每个 slot 计算：

```text
delta = original_base - first_valid_original_base
```

写入 metadata。

### Step 4：实现 runtime patcher

输入：

```text
kernel package
call_frame.spm_bases
```

输出：

```text
patched_instance.bin
patched_cbuf.bin
```

### Step 5：保守启动验证

每次 launch：

```text
load patched_cbuf
load micc
DMA input -> SPM
start kernel
DMA SPM -> output
```

先验证“换 SPM base 后仍然输出正确”。

### Step 6：优化为只更新 instance

验证 `DPU_Cbuf_ISTC_Transfer()` / `inst_reload=0` 路径：

```text
第一次 load full cbuf/micc
后续只更新 instance_conf
launch
```

## 8. 对 softmax 的具体例子

当前 softmax 指令里的 LD/ST offset 已经表达了行内访问模式：

```text
PE0 row0:  offset 0, 128
PE1 row1:  offset 256, 384
...
PE15 row15: offset 3840, 3968
```

这些 offset 不需要随 tensor buffer 地址变化而变化。

运行期只需要改变：

```text
input0 base slot:
  本次 input_spm_base

output0 base slot:
  本次 output_spm_base

SUM base slot:
  本次 scratch_spm_base
```

最终 PE 看到的是：

```text
LD input0_base + row_offset + chunk_offset
ST output0_base + row_offset + chunk_offset
```

这就是 softmax 的可重定位形式。

## 9. 主要风险

需要用实验确认：

- 硬件执行时是否真的使用 `instance_conf.base_addr[base_addr_idx] + imm`。
- simulator 和 RTL 对 base_addr 的单位是否一致。
- 原始 `instance_conf_info_file.bin` 的 base_addr 单位是否和 LD/ST imm 单位一致。
- `0xffffffff` 这类无效 base 的处理规则。
- `DPU_Cbuf_ISTC_Transfer()` 是否能用于独立更新 instance 区。
- `inst_reload=0` 是否会重新读取 instance，还是只复用旧 instance。
- 多 subtask 的 instance entry 顺序如何和 MICC/subtask config 关联。

这些风险不会推翻方案，但会决定 patcher 的具体单位、偏移和装载策略。

## 10. 一句话实现方案

第一版可重定位 kernel 就是：

```text
把当前固定 case 生成的 cbuf/micc/instance 拆成 kernel package；
把 instance_conf.base_addr[] 视为 relocation target；
为每个 base slot 记录 symbol 和 per-instance delta；
运行期按 call frame 的 SPM base 重写 instance_conf；
同时 patch DMA descriptor，把真实 tensor buffer 搬到对应 SPM base；
再启动原有 MICC/PE 执行流。
```

