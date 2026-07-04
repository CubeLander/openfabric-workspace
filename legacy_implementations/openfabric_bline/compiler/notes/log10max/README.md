# log10max 旧 pipeline 落地策略

Date: 2026-06-19
Status: current working note

本目录记录 `log10max` 音频预处理算子在旧 DFU3500 / SimICT pipeline
里的落地策略。旧笔记已归档到 `archive/`：

- `archive/2026-06-16_todo.md`
- `archive/2026-06-16_rfc-log10max-app-to-tile-lowering.md`

相关背景笔记仍可参考：

- `compiler/notes/archive/collective-task-app-strategy-notes.md`
- `docs/vendor_reference/cases/softmax/softmax-current-real-workflow.md`
- `docs/vendor_reference/cases/softmax/softmax-case-walkthrough.md`
- `docs/architecture/instruction-set/dfu3500-simd/`

## 目标表达式

目标算子来自音频预处理：

```text
log_spec = log10(clamp(mel_spec, min=1e-10))
global_max = reduce_max(log_spec)
out = maximum(log_spec, global_max - 8.0)
out = (out + 4.0) / 4.0
```

当前 compiler frontend 已经能描述这些 op：

```text
clamp_min
log10
reduce_max
maximum
add_scalar
mul_scalar
```

但旧 runnable binary pipeline 还不能把 `reduce_max` 的 `all_reduce(max)`
真正编码成 DFU3500 可执行通信程序。现有 IR 里的 `LogicalReduceEdge` /
tile collective 仍是 symbolic collective。

## 关键判断

不要在第一版里直接做真正 PE 间 allreduce。旧 pipeline 的第一目标应该是：

```text
先跑通一个 correctness-first 的 log10max binary，
再逐步替换成更高效的 collective 实现。
```

推荐第一版使用：

```text
same_app_redundant_spmd
```

也就是每个 PE / soft processor 独立从 SRAM 读取所需输入，自己算出同一个
`global_max`，然后继续计算自己负责的输出 shard。这个策略语义上等价于
allreduce 产生 replicated scalar，但不需要跨 PE 通信。

它很贵，但非常适合旧 pipeline：

- 不依赖尚未实现的 collective route / graph edge。
- 不依赖 task 间同步。
- 只要求 SRAM 输入稳定、可重复读取。
- 可以先验证 elementwise、local reduce、store、runtime package。

等第一版跑通后，再考虑：

```text
local_max per PE
  -> PE00 gather/reduce
  -> SRAM/SPM materialize global_max
  -> all PE load/broadcast global_max
  -> postprocess
```

或者更高性能的 pairwise reduce tree。

## 甲方 softmax 证据

`softmax_1` 是当前最接近 `log10max` 的参考 case。它不是 GEMM 模板，而是
典型 elementwise + reduce + postprocess 算子。

从 `docs/vendor_reference/cases/softmax/softmax-current-real-workflow.md`
可以确认：

```text
输入 shape:
  64 x 512

任务切分:
  4 tasks
  每 task 16 PE
  每 PE 处理 1 行 512 元素

subtask:
  subtask1: 读取输入，计算 exp / partial sum，写 SUM 或中间值
  subtask2: 读取 SUM 和中间值，做 div / pack / store 输出
```

softmax 的 subtask 内部没有显式 PE graph edge；顺序主要来自：

```text
task/subtask config:
  subtask1 -> subtask2

Inst_Block 内部:
  单 PE 指令序列顺序

SPM/SUM 中间区:
  subtask1 写，subtask2 读
```

这说明旧 pipeline 支持一种朴素但有效的 staged elementwise 算子路径：

```text
subtask1 materialize intermediate
subtask2 reload intermediate and finish
```

`log10max` 第一版可以借这个 workflow 形状，而不是借 GEMM 的 template
envelope。

## 指令层证据

参考 `docs/architecture/instruction-set/dfu3500-simd/docx/instruction_sections/`。

### 可直接使用的 elementwise 指令

```text
FMAX:
  fp32 lane-wise max
  128 lanes x 32 bits

FMIN:
  fp32 lane-wise min

FADD:
  fp32 lane-wise add

FMUL:
  fp32 lane-wise multiply

FLOG2:
  可见于 instruction set / vendor printer 线索。
  没有直接 LOG10，因此 log10(x) 应降为:
    FLOG2(x) * log10(2)

IMM / FIMM:
  常量广播 / float immediate materialization。
```

### reduce 的关键不是 FMAX，而是横向规约

`FMAX` 只做 lane-wise max：

```text
dst[lane] = max(src0[lane], src1[lane])
```

但 `reduce_max(log_spec)` 需要把一个 vector / tile / tensor 区域规约成
scalar 或 replicated scalar。因此还需要横向 lane movement。

softmax CSV 给出了重要线索：

```text
IMM rShflF0 = 16
IMM rShflF1 = 8
IMM rShflF2 = 4
IMM rShflF3 = 2
IMM rShflF4 = 1

SHFL + FADD
SHFL + FADD
SHFL + FADD
SHFL + FADD
SHFL + FADD
```

这正是 row-wise sum reduction 的形状。`log10max` 的 row/global max 可以
类比为：

```text
SHFL + FMAX
SHFL + FMAX
SHFL + FMAX
SHFL + FMAX
SHFL + FMAX
```

因此，`reduce_max` 的旧 pipeline 第一版应该优先复刻 softmax 的
`SHFL` reduction skeleton，只把 combine op 从 `FADD` 换成 `FMAX`。

## 推荐第一版：冗余 SPMD global max

如果目标语义确实是全 tensor global scalar：

```text
global_max = reduce_max(log_spec)
```

第一版可以这样实现：

```text
每个 PE:
  1. 读取完整 reduce domain 或一个预先约定的小测试 domain。
  2. 对输入做 clamp_min + log10。
  3. 用 SHFL + FMAX 得到本 PE 自己算出来的 global_max。
  4. 再读取自己负责的输出 shard。
  5. 重算 clamp_min + log10。
  6. threshold = global_max - 8.0。
  7. clipped = maximum(log_spec, threshold)。
  8. out = (clipped + 4.0) * 0.25。
  9. store out。
```

这个版本不是真正的通信 allreduce，而是：

```text
allreduce by redundant read-only recomputation
```

它的适用条件：

- 输入在 SRAM / SPM 中稳定，不被中途改写。
- reduce domain 在测试 shape 下足够小，能被每个 PE 重复扫描。
- 指令和 instance 容量不超限。

它的优点：

- 最少碰 vendor graph / route。
- 最少碰 task/subtask 控制表。
- 容易定位错误：先只看本 PE 指令和地址。
- 能快速得到第一个 simulator-valid binary。

它的缺点：

- 计算量和 SRAM 读取被 PE 数量放大。
- 不代表最终性能路径。
- 如果 reduce domain 很大，可能触发指令/instance/时间压力。

## 单 task 策略

`log10max` 旧 pipeline 第一阶段建议先做成单 vendor task，但这里的“单
task”要说清楚：

```text
不是：
  只用 1 个 PE。

而是：
  只使用 1 个 vendor task row / task context，
  在这个 task 内使用 16 个 PE 作为一个协作组。
```

原因：

- task 之间没有隐式同步和 PE-local state 共享。
- allreduce 第一版通信实现可以先限制在一个 task 的 16 个 PE 内。
- 避免一开始就做跨 task reduce / 二级 reduce。
- 让问题集中在：
  - vector lane 横向规约；
  - task-local PE 间通信；
  - scratch materialization；
  - postprocess reload。

因此初始 testing matrix 可以是：

```text
task_num = 1
PE group = 4 x 4
reduce scope = task-local 16 PE
shape = 16 x 512 或 64 x 512 with per-PE multiple rows
```

如果要借 softmax 的 `64 x 512 = 4 tasks * 16 PE` 现成 case contract，
也可以暂时保留 4 tasks，但每个 task 内独立做 16 PE local allreduce。
这时得到的是 per-task global max，而不是全 64 行 global max；只能作为
instruction / communication smoke，不代表最终全 tensor 语义。

真正全 tensor global max 的路线有两种：

```text
Option A:
  单 task 覆盖整个 reduce domain。

Option B:
  4 tasks 各自 local reduce，
  再通过 SRAM scratch 做 task-level second-stage reduce。
```

旧 pipeline 建议先 Option A，除非输入 shape 必须沿用 softmax 的 4-task
case。

## 推荐 shape 起点

为了借 softmax 经验，第一版建议优先使用：

```text
shape = 64 x 512
dtype = fp16 input/output 或 fp32 internal
task_num = 4
PE per task = 16
每 PE 处理 1 行
```

这和 softmax_1 的 case contract 对齐：

```text
64 rows = 4 tasks * 16 PE
每行 512 elements
```

如果必须从当前 compiler example 的 `128 x 512` 开始，也可以：

```text
每 PE 处理 2 行
或
每个 task 多 instance
```

但第一版最好少引入 instance 复杂性。先跑通 `64 x 512` 更稳。

## 初始子任务组织建议

旧 pipeline 的最小可运行形态可以先用一个或两个 subtask。

### Option A: 单 subtask

```text
subtask1:
  redundant global max
  local postprocess
  store output
```

优点：

- 最少控制表变化。
- 不需要中间 SPM/SUM 区。

缺点：

- 指令很长。
- global_max 只存在 PE-local 寄存器/operand 中。
- 不方便调试中间 scalar。

### Option B: softmax-style 两 subtask

```text
subtask1:
  redundant or local max reduction
  store global_max / local_max to SUM scratch

subtask2:
  load global_max / SUM scratch
  recompute local log_spec
  postprocess and store output
```

优点：

- 更接近 softmax 甲方工作流。
- 中间值可 dump / 比较。
- 后续可替换成 PE00 reduce + materialize。

缺点：

- 需要管理 SUM scratch base slot 和 instance_conf base_addr。

第一版建议从 Option B 开始，因为它和 softmax 的证据最吻合。

## 后续真正 allreduce 路线

当冗余 SPMD 版本跑通后，可以把 `global_max` 的产生替换为真正 collective。

推荐顺序：

```text
Phase 1:
  redundant_spmd_global_max
  每 PE 独立算 global_max

Phase 2:
  per-PE local_max -> SRAM/SPM scratch
  PE00 读取 16 个 local_max 做 FMAX chain
  PE00 写 global_max scratch
  所有 PE load global_max scratch

Phase 3:
  PE00 gather + COPY / route broadcast

Phase 4:
  pairwise reduce tree + broadcast
```

Phase 2 是第一个真正跨 PE 共享结果版本，但仍尽量通过 SRAM/SPM
materialization 避免复杂 graph edge。

## 第二版：通信 allreduce 能否接入？

结论：可以，但应该作为 `all_reduce_max_symbolic` 的一个明确 strategy，
不要散落成一堆临时 COPYT / FMAX 特判。

当前旧 pipeline 已经有几块可复用基础：

```text
LogicalReduceEdge:
  已经表达 reduce_op=max、participants、input/output value ids、
  visibility_kind=replicated_scalar。

TileCollectiveBundle:
  已经保存 all_reduce_max_symbolic bundle。

TileRouteAction:
  已经建模 DFU COPY/COPYT sender-push。
  可表达 execution_processor 和 endpoint_processor 不同。

ProgramAsm / ProgramLegacyInst / ProgramBin:
  已经有 route_materialize -> COPYT/COPY 的旧 GEMM 路径，
  并处理 COPYT destination PE / operand patching。
```

所以第二版的目标不是“重新发明通信系统”，而是：

```text
把 all_reduce_max_symbolic
  展开成一组已有 route action + local FMAX combine action。
```

### 推荐的最小通信版本

第一版 runnable 使用 redundant SPMD。第二版通信 allreduce 建议先做最朴素的：

```text
all PE local_max
  -> COPYT/gather 到 PE00
  -> PE00 FMAX combine
  -> PE00 store global_max to SRAM/SPM scratch
  -> all PE load global_max scratch
  -> postprocess
```

这不是最高性能实现，但有几个优点：

- 只需要 many-to-one gather，不需要复杂 tree。
- broadcast 可以先通过 SRAM/SPM materialization 规避。
- route 只用于 local_max scalar/tile 的搬运。
- 下游 postprocess 只依赖显式 loaded scalar。
- 对 task/subtask 顺序要求清晰：
  - subtask1: local reduce + gather + PE00 combine/store
  - subtask2: all PE load global_max + postprocess/store

这条路比直接做：

```text
PE00 combine -> COPYT broadcast to all PE -> same subtask continue
```

更稳，因为它把跨 PE visibility 明确落在 scratch storage 上。旧 pipeline 最怕的
不是多几条指令，而是 PE-local state 什么时候对谁可见讲不清。

### 后续优化版本

等 PE00 gather 版本跑通后，再做真正 replicated allreduce：

```text
local_max
  -> pairwise reduce tree
  -> global_max at root
  -> COPYT broadcast / route fanout
  -> all PE consume replicated scalar
```

这时 `TileCollectiveBundle` 可以带 strategy：

```text
strategy = pe00_gather_scratch
strategy = pe00_gather_copyt_broadcast
strategy = pairwise_tree_broadcast
strategy = redundant_spmd
```

而不是让 `collective_kind=all_reduce_max_symbolic` 永远停在 symbolic 状态。

### 需要新增的 IR / lowering 概念

第二版至少需要一个 explicit strategy 层：

```text
TileCollectiveBundle
  collective_kind = all_reduce_max
  strategy = pe00_gather_scratch
```

展开后产生：

```text
TileRouteAction:
  local_max from PEij -> PE00

TileComputeAction:
  PE00 collective_combine_max

TileStoreAction or TileAppStorageAction:
  PE00 materialize global_max scratch

TileComputeAction / load action:
  all PE reload global_max scratch before postprocess
```

核心 dependency：

```text
local_reduce_max on every PE
  before route_to_PE00
route_to_PE00 all complete
  before PE00 combine_max
PE00 combine_max
  before scratch store
scratch store
  before all PE global_max load
global_max load
  before maximum(log_spec, global_max - 8)
```

这个 dependency chain 很重要。allreduce 不是单条 route；它是通信、combine、
materialize/load、postprocess 之间的执行顺序证明。

### 可能踩坑

1. COPYT 搬运的是寄存器/operand 内容，不是 abstract scalar。
   需要确定 local_max 的 physical operand tag 能被 COPYT 源端引用，
   以及 PE00 目的端 operand tag 能被后续 FMAX chain 引用。

2. 当前 COPYT patching 很 GEMM 化。
   现有 `program_bin.py` 会根据 route_forward provenance patch COPY/COPYT
   目的 PE、block、operand。第二版如果复用这条路，需要确保 collective route
   也有足够 provenance；否则可能要做一个 generic COPYT patcher。

3. PE00 combine 可能需要多条 FMAX，而不是一条。
   16 个 PE 的 local_max 进入 PE00 后，PE00 要按 operand slots 做 FMAX chain。

4. 如果 local_max 是 vector lane replicated scalar，可以直接 FMAX lane-wise。
   如果 local_max 只在某个 lane 有效，则还要先广播/规整 lane。

5. scratch storage 地址要进入 instance base_addr / imm 体系。
   不能偷用 PE-local temporary 当跨 subtask 可见状态。

6. task 轴隔离仍然存在。
   初版通信 allreduce 最好先限制在一个 task 内 16 PE。
   跨 task allreduce 要么每 task 各自 reduce 后再第二级 reduce，
   要么通过 SRAM scratch 做 task-level merge；不能假设 task 间有隐式同步。

### 对 SoC 架构的意义

allreduce 不只是 `log10max` 的一个小功能。它会成为 SoC 编译器支持 staged
operators 的基础能力：

```text
softmax:
  reduce_max / reduce_sum + broadcast

layernorm/rmsnorm:
  reduce_sum / reduce_squares + broadcast

attention:
  row-wise max/sum + normalize

audio preprocessing:
  global or axis max + clipping
```

因此第二版 allreduce 应该以 `collective strategy` 形式进入 compiler，而不是作为
`log10max` 私有 hack。`log10max` 可以做第一个 consumer，但 IR 上要尽量写成：

```text
reduce_op = max
participants = task-local PE group
visibility = scratch_materialized_then_loaded
strategy = pe00_gather_scratch
```

这样后续 `reduce_sum` 只需要把 combine op 从 `FMAX` 换成 `FADD`，而不是重写
通信模型。

## 上传测试策略

`log10max` 测试比 GEMM 麻烦，因为它还没有完整 compiler binary path。
建议 validation bundle 同时带两类 payload / smoke：

### 1. Runtime payload

目标是真正运行 OpenFabric 生成的 `result/cbuf_file.bin` 和
`result/micc_file.bin`。

第一阶段可能只包含：

```text
case_id = log10max_single_task_redundant_spmd
app_name = <vendor case name or temporary copied case>
task_num = 1
```

验收标准：

```text
runtime_rc = 0
不追求 vendor byte parity
输出先做粗略 sanity check
```

### 2. Instruction smoke

目标不是验证完整 log10max 语义，而是快速回答底层指令问题：

```text
smoke_fmax_shfl_reduce:
  从 softmax 的 SHFL + FADD skeleton 派生，
  把 reduction combine op 改成 FMAX，
  验证 simulator 接受 SHFL + FMAX 横向 max。

smoke_flog2:
  验证 CSV / assembler / runtime 是否接受 FLOG2，
  或确认需要通过其他 opcode / imm mode 表达。

smoke_copyt_gather:
  单 task 内 16 PE local value -> PE00，
  验证 COPYT gather 和 PE00 combine 的基本通信路径。
```

这些 smoke 可以先放进 partner validation bundle 的独立目录，由远端脚本
按需运行。它们不必进入正式 payload 列表，也不必通过 output check；第一阶段只看
runtime 是否接受指令和控制流。

推荐执行顺序：

```text
1. smoke_fmax_shfl_reduce
2. smoke_flog2
3. log10max_single_task_redundant_spmd runtime payload
4. smoke_copyt_gather
5. log10max_single_task_pe00_gather_scratch runtime payload
```

这样每一步都只多验证一个未知数，避免一次上传后只得到一个大而模糊的
`runtime failed`。

## 旧 pipeline 实现切入点

当前目标不是重构新 stream compiler，而是在旧 runnable pipeline 里开一个窄路径。

建议新增一个 case-specific legacy profile：

```text
legacy_log10max_compat
```

它可以先是手工/模板驱动的 DFU3500 backend 路径，类似我们对 GEMM 做过的
legacy compat，但范围更窄：

```text
input:
  fixed case config
  fixed shape
  fixed task/subtask/PE mapping

output:
  result/cbuf_file.bin
  result/micc_file.bin
  validation payload
```

不要第一版就追求：

```text
generic reduce lowering
generic elementwise serializer
generic collective route
```

旧 pipeline 的第一版职责是把一个真实算子组合送进甲方 runtime 跑完。

## 待确认问题

1. `global_max` 的 reduce axes：
   - 当前 compiler example 默认 `axes=None`，即整个 tensor reduce 成 scalar。
   - 如果真实音频需求是 per-row / per-frame / per-channel max，implementation 会简单很多。

2. 输入/输出 dtype：
   - softmax case 是 half load/store、fp32 internal。
   - `log10max` 是否要求 fp32 input/output，需要和需求确认。

3. `FLOG2` 的实际 assembler spelling：
   - instruction docs / vendor printer 有线索。
   - 需要确认 CSV 是否直接接受 `FLOG2`，或是否通过某个 special opcode / imm mode 表达。

4. `FMAX` + `SHFL` 横向 max 是否 simulator-valid：
   - softmax 已证明 `SHFL + FADD` 可跑。
   - `SHFL + FMAX` 是合理推断，但仍需最小 CSV smoke test。

5. 常量 materialization：
   - `1e-10`
   - `log10(2)`
   - `-8.0`
   - `4.0`
   - `0.25`
   需要确定用 `IMM` / `FIMM` / preloaded constant operand 哪种最稳定。

## 下一步建议

1. 先做一个最小 softmax-derived CSV prototype：
   - 把 `SHFL + FADD` reduction 改成 `SHFL + FMAX`。
   - 确认 simulator 接受 `FMAX` reduction chain。

2. 确认 `FLOG2` 的 CSV spelling：
   - 搜索 vendor examples 是否存在真实 `FLOG2` CSV。
   - 如果没有，查 `task_print.cpp` / opcode map 的生成方式。

3. 在 validation workflow 中新增一个 `log10max` payload slot：
   - 初期可以只 package 手写/模板生成产物。
   - 后续再接入 compiler old pipeline。

4. 第一版 binary 目标：
   - 不追求 vendor byte parity。
   - 只要求 runtime 跑完，并能对输出做粗略数值 sanity check。

一句话：

```text
先用 softmax 的横向规约骨架和冗余 SPMD 策略绕开 allreduce 通信，
让 log10max 在旧 pipeline 里成为第二个 runnable 算子组合。
```
