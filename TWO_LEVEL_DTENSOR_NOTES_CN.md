# Scoped Tensor Projection 抽象笔记

状态：讨论笔记。

日期：2026-07-04

这份笔记记录 OpenFabric 数据抽象的一次命名和模型修正：我们不再把核心问题
描述成“两层 DTensor”，而是描述成 **Tensor 在不同 execution scope 中的连续
投影**。

核心想法：

```text
Tensor
  -> StreamTensorView
  -> FiberTensorView
  -> TypedTileValue
  -> Operand
  -> Instruction / Binary
```

这里真正发生的是：

```text
同一个逻辑 Tensor 被投影到不同 execution scope。
```

而不是：

```text
Tensor 变成另一个 Tensor。
```

因此，`GlobalDTensor / LocalDTensor` 可以保留为历史讨论名或临时实现名，但不
应该成为 OpenFabric 的最终语言。`DTensor` 这个词太容易把设计拉回 PyTorch-style
“distributed tensor”直觉，而 OpenFabric 更关心的是 spatial execution 中的
scope、visibility、materialization 和 lowering。

旧讨论名和新语言的对应关系可以暂时这样理解：

```text
GlobalDTensor
  -> Tensor truth + StreamTensorView projection

LocalDTensor / LocalDTensorView
  -> FiberTensorView projection

LocalTileRef / DTensorTileRef
  -> TileRef

Operand / register value / tensor tmp
  -> TypedTileValue materialized into a physical operand space
```

这里也顺手固定一个命名原则：OpenFabric 不需要很多种 tile。真正的 tile 应该只
出现在 `FiberTensorView` 被 materialize 之后；在此之前讨论的是 tensor view /
projection，不是 tile 本体。

## 命名哲学

OpenFabric 已经有一条 execution hierarchy：

```text
Application
  -> Stream
  -> Fiber
  -> Binary / ISA
```

数据层可以与它形成对称：

```text
Tensor
  -> StreamTensorView
  -> FiberTensorView
  -> TypedTileValue
  -> Operand
```

这个对称性很重要。它让 `Stream` / `Fiber` 不只是一种执行组织方式，也自然成为
数据作用域：

```text
Stream:
  一个 execution context。它可以对应一个 PE、一组 PE、一个 cluster、一个
  subtask window、一个 repeated body，或者未来 Tenstorrent 上的一片 core grid。

StreamTensorView:
  Tensor projected into a Stream scope。

Fiber:
  Stream 内更小的 local compute / materialization recipe scope。

FiberTensorView:
  StreamTensorView projected into a Fiber scope。
```

一个简化图：

```text
Program
  |
  v
Application
  |
  v
Stream ------------------+
  |                      |
  v                      v
Fiber              StreamTensorView
  |                      |
  +----------+-----------+
             v
       FiberTensorView
             v
       TypedTileValue
             v
          Operand
             v
      Instruction / Binary
```

## 关键不变量

`Tensor` 是 truth source：

```text
logical identity
shape
dtype
semantic role
storage role / access role
placement policy, if already known
```

`StreamTensorView` 和 `FiberTensorView` 不是新的 truth source。它们是 scoped
projection：

```text
Tensor + Stream scope
  -> StreamTensorView

StreamTensorView + Fiber scope
  -> FiberTensorView
```

所以文档和实现里最好带 `View` 或 `Projection`。这可以防止大家误以为：

```text
Tensor -> StreamTensor -> FiberTensor
```

是在创建三份独立 tensor truth。正确理解应该是：

```text
一个 Tensor truth，在不同 execution scope 下被投影成不同 view。
```

## 为什么需要 StreamTensorView / FiberTensorView

此前讨论中有一个盲点：

```text
Tensor 和 tile 不一定是一一对应。
```

更自然的过程可能是：

```text
Tensor
  -> StreamTensorView
  -> FiberTensorView
  -> Tile / fragment / operand materialization
```

也就是说，tensor 先被投影到某个 stream 可见的数据窗口；这个 stream 内的 fiber
再取得更小的 local view，并把它切成适合本地计算、load/store、operand
materialization 的 tile 或 fragment。

如果不显式表达这两个 projection scope，很多动态事实会挤在旧实现里的
`DTensorTileRef` 或
`TileMemoryAccess` 里：

```text
global tensor coordinates
stream visibility
PE / cluster / participant ownership
stage/window lifetime
fiber-local shard coordinates
tile coordinates
chunk index
lane index
SPM offset
operand symbol
```

这会让 `row_start`、`col_start`、`lane`、`imm`、`chunk_idx` 这些字段慢慢变成
多个概念的混合物。

## StreamTensorView

`StreamTensorView` 回答的是：

```text
这个 Stream 看到 Tensor 的哪一段？
这个 Stream 的 participant 是哪些 PE / cluster / core？
这个 view 的 stage/window/lifetime 是什么？
这个 view 需要 route / broadcast / reduce / copy 吗？
这个 view 如何绑定到 SPM/L1/DRAM 等 storage boundary？
```

它不是“另一个 tensor”，而是：

```text
Tensor projected into Stream scope。
```

在这一层，tile 还不是主要概念。这里更关注 tensor domain 如何投影到空间执行
资源和 stage/window 可见性。

## FiberTensorView

`FiberTensorView` 回答的是：

```text
这个 Fiber 真正拿来计算的是 StreamTensorView 的哪一块？
这个 local view 内部如何切成 tile？
tile shape / chunk shape / lane grouping 是什么？
边界 tile 如何处理？
这个 local tile 如何 materialize 成 H256 chunk、F32 vector、GEMM operand strip、
tensor tmp accumulator、Tenstorrent circular-buffer tile 或 Dst tile？
```

它也不是独立 truth source。它应该是：

```text
StreamTensorView + Fiber scope
  -> fiber-local projection
```

一个重要不变量：

```text
FiberTensorView 不能和 Tensor / StreamTensorView 各自维护一套互相独立的
shape/range truth。

FiberTensorView 的 local domain 应该从 StreamTensorView projection 推导。
```

## TileRef

在这个模型里，tile ref 应该更轻：

```text
TileRef = FiberTensorView identity + tile coordinate
```

tile 的实际信息应该推导出来：

```text
global element range
local shard offset
tile shape
chunk count
lane count
SPM offset
memory access plan
operand materialization plan
```

如果当前实现里旧的 `DTensorTileRef` 存了 `row_start`、`row_count`、`col_start`、
`col_count`，这些更像 projection cache 或 implementation convenience，不应该
成为长期 truth source。

## 运算 Lowering

Scoped tensor projection 后，logical operation lowering 可以变成：

```text
Tensor-level logical op
  add(A, B)
  matmul(A, B)

-> StreamTensorView logical op
  add(A_stream, B_stream)
  matmul shard update / broadcast / reduce

-> FiberTensorView logical op
  add(A_fiber, B_fiber)
  matmul shard update / broadcast / reduce

-> tile-level logical op
  add(tile_a, tile_b)
  matmul_accumulate(tile_a, tile_b, acc_tile)

-> physical operation
  FADD / HADD / HLDT / HSTT / HMMAL / COPYT / RXINT / TRCTT
```

也就是说，Fiber 内部 `FiberTensorView` 之间的逻辑运算，会继续被 lowering 成
tile/value 之间的逻辑运算，再由 backend 选择物理指令。

## 对 GEMM 的意义

GEMM 很可能是这个分层最有价值的例子。

`StreamTensorView` 层负责：

```text
A/B/C tensor 在 PE mesh 上的 ownership
A 是否需要 broadcast
B 是否 PE-local load
C accumulator 属于哪个 output shard
K window 是否通过 subtask instance 推进
```

`FiberTensorView` 层负责：

```text
当前 PE 的 A local shard 如何切成 A strips
当前 PE 的 B local shard 如何切成 B strips
C accumulator tile 如何映射到 tensor tmp
HMMAL 所需 register half / matrix half / data_select_type 如何从 local tile
space 推导
```

这样就不会把 `data_select_type`、B lane、operand RAM index、matrix half、
register half 都揉成同一类整数。

## 是否值得做取决于硬件事实

这个抽象的代价不低，所以需要用甲方硬件事实和目标可移植性判断是否值得。

需要调查的问题：

```text
1. 每个 PE 能容纳多少 operand / local register state？
2. PE-local operand RAM 的分组、bank、entry 数、每 entry 宽度是多少？
3. SPM 总大小有多大？是全 chip 共享，还是按 PE/cluster 分区？
4. 一个 PE 常见情况下能同时驻留几个 tile / fragment？
5. HLDT/HSTT/ILDMT 这种 pseudo op 一次实际覆盖多少数据？
6. GEMM HMMAL 的 A/B operand strip 和 tensor tmp accumulator 占用多大？
```

判断倾向：

```text
如果 PE-local 空间非常小：
  FiberTensorView 可以先只是轻量 projection/helper，不必做成完整一等 IR。

如果 PE-local 空间足够大，能容纳多个 tile/fragment/window：
  FiberTensorView 这层就值得认真设计，因为 PE 内部的数据布局、tile scheduling、
  operand lifetime 和 materialization policy 会成为真正的优化空间。
```

当前还没有客户硬件完全拨下来，所以这份笔记只是设计假设。下一步应该调查仓库
里已经积累的 vendor / customer facts，再决定是否把 scoped tensor projection
推进为正式设计。

## 初步硬件事实调查

本节记录 2026-07-04 对仓库内已有资料的初步调查。结论不是最终硬件规格，只是
用来判断 scoped tensor projection 抽象是否值得继续投入。

### PE 拓扑与 PE-local 资源

当前 active vendor tree 的 `common/src/pe_com_def.h` 给出：

```text
PE_ARRAY_X_LEN = 4
PE_ARRAY_Y_LEN = 4
PE_AMOUNT      = 16

MAX_INST_BLOCK_AMOUNT_PER_PE = 32
MAX_INST_AMOUNT_PER_PE       = 4352
MAX_REGS_AMOUNT_PER_PE       = 8
```

同一文件给出 PE-local operand RAM 结构：

```text
MAX_OPERAND_RAM_AMOUNT_PER_PE = 1536
OPERANDS_RAM_GROUP_NUM        = 3
OPERANDS_RAM_NUM_PER_GROUP    = 4
OPERANDS_RAM_NUM              = 12
OPERANDS_PER_OPERAND_RAM      = 128
```

`docs/vendor-workflow-evidence/pe-operand-index-model.md` 已经整理出当前工作模型：

```text
每个 PE 有 1536 个 operand slot。
这些 slot 组织成 12 个 operand RAM bank。
每个 bank 有 128 项。
最终 operand index = bank * 128 + row。
```

这说明 PE 内部不是只有几个临时寄存器。虽然普通 scalar register 只有 8 个，但
真正承载 tensor/vector 数据的是 PE-local operand RAM。

### SPM / Local Memory 事实

`common/src/mem_com_def.h` 给出：

```text
SPM_BUFFER_NUM          = 2
SPM_BANK_NUM            = 8
SPM_BLOCK_NUM_PER_BANK  = 32
IO_CHANNEL_PER_SPM_BANK = 4
SPM_SIZE                = 4 MB
SPM_CONST_SIZE          = 256 KB
MEM_ACCESS_ATOM_SIZE    = 128 bytes
SIMD_SIZE               = 128 bytes
```

`common/src/dma_com_def.h` 给出 local memory layout：

```text
SPM_BUF0_BASE = 0x00000000
SPM_BUF1_BASE = 0x00400000
SPM_MAX       = 0x00840000 - 1
SPM_NUM       = 2
```

同一文件还给出：

```text
SPM_BUF_SIZE = 3145728  // 3 MB
```

这里存在一个需要继续确认的冲突：

```text
mem_com_def.h: SPM_SIZE = 4 MB
dma_com_def.h: SPM_BUF_SIZE = 3 MB
address layout: SPM_BUF1_BASE = 4 MB, SPM_MAX ~= 8.25 MB
```

暂时不能把这些常量解释成完整硬件规格。更稳妥的说法是：

```text
SPM 至少是 MB 级、banked、双 buffer/多区域的 local memory。
OpenFabric 不应该把 SPM 当成几个固定小 scratch slot。
```

### Memory Op Granularity

`docs/isa/HLDT.md` 和 `docs/isa/HSTT.md` 的工作模型显示：

```text
HLDT -> LDN x 4
HSTT -> STD x 4
```

每条 CSV pseudo op 在 normal mode 下覆盖四个 1024-bit chunk：

```text
一个 1024-bit chunk = 一个 128-byte SPM block
四个 chunk         = 一个 4096-bit logical operand group
```

这说明 PE 内部的 tile/materialization 边界不是 scalar，也不是单一 element。
一个 memory op 本身就已经在处理 vector/tensor fragment 级别的数据。

`docs/isa/ILDMT.md` 还说明 `ILDMT/LDM` 不是普通完整 fp32 vector load：

```text
ILDMT -> LDM x 4
simd_mode 选择 element-group width
不要把 ILDMT 当成可靠的完整 4096-bit fp32 vector load
```

这进一步支持“FiberTensorView / local tile-space / materialization policy”需要显式：
同样是 PE 内部 load，不同 pseudo op 的 value 语义不一样。

### GEMM 证据

`drafts/gemm-fiberop-design-notes.md` 记录了 GEMM 当前重要事实：

```text
tile lanes              = 16
MMA group lanes         = 8
A broadcast group lanes = 4
A root PEs              = 0, 4, 8, 12
B load                  = lane-local, based on pe_id % 8
C load/store            = PE-local
```

HMMAL 不是普通 register arithmetic：

```text
src0_reg          ordinary operand/register strip carrying Matrix A data
src1_reg          ordinary operand/register strip carrying Matrix B data
dst_tmp           tensor tmp accumulator selected by imm[9:7]
a_half / b_half   lower or upper 2048-bit half inside the 4096-bit operand
data_select_type  tensor-unit compute/data-selection mode selected by imm[6:4]
```

这非常像 scoped tensor projection 里的分工：

```text
Tensor / StreamTensorView:
  决定 A/B/C 的全局语义，以及它们在 Stream participant 上的 ownership、
  broadcast、K window、subtask instance。

FiberTensorView:
  决定当前 Fiber/local compute scope 内 A/B/C view 如何切成 operand strips、
  register halves、matrix halves、tensor tmp accumulator。
```

### Softmax / Scratch 证据

`docs/dtensor-stage-shard-address-plan.md` 记录 softmax 的 SUM scratch：

```text
Tensor X[64,512]
Tensor SUM_scratch[64,256]  // SPM internal
Tensor Y[64,512]
```

每个 PE row 处理连续 row tile：

```text
PE(row) owns X[row, 0:512]
  chunk0 = X[row, 0:256]
  chunk1 = X[row, 256:512]
```

SUM scratch 则是：

```text
SUM[row, 0:256]
  slot0 = SUM[row, 0:64]
  slot1 = SUM[row, 64:128]
  slot2 = SUM[row, 128:192]
  slot3 = SUM[row, 192:256]
```

这也是 scoped tensor projection 的证据：

```text
Tensor / StreamTensorView:
  softmax X/Y/SUM_scratch 的 global shape、stage visibility、SPM binding，
  以及当前 stream/subtask 可见的 row/window。

FiberTensorView:
  当前 fiber/PE row 内如何切成 H256 chunks、H64/summary slots、store/load
  fragments。
```

## 初步判断

从目前证据看，硬件空间和数据粒度都不算“小到不值得抽象”：

```text
16 个 PE，4x4 mesh。
每 PE 1536 operand slots，12 banks x 128 entries。
SPM 是 MB 级、banked、双 buffer/多区域。
HLDT/HSTT 一条 pseudo op 覆盖 4096-bit logical operand group。
GEMM 有明确的 PE 内 operand strip / tensor tmp / matrix half 语义。
softmax 有跨 subtask SPM scratch Tensor/View 和 PE-local chunk/slot 语义。
```

因此，倾向判断是：

```text
值得保留 scoped tensor projection 的设计方向。
```

但不建议马上实现一个重型二级 IR。更稳妥的是：

```text
1. 设计上承认 Tensor truth、StreamTensorView 和 FiberTensorView 的区别。
2. 当前实现先把 Stream/Fiber view 做成 projection/query/helper，而不是完整
   ownership IR。
3. 用 GEMM 和 softmax 两个 case 验证：
   - StreamTensorView 能否解释 participant ownership / stage window / SPM binding。
   - FiberTensorView 能否解释 PE 内 tile chunks / summary slots / GEMM strips。
4. 如果后续硬件资料确认 PE-local capacity 和 bank/port 约束更复杂，再把
   FiberTensorView 升级成更正式的一等 abstraction。
```

## Operator Coverage 视角下的抽象重量

`docs/operator-coverage-checklist.md` 给出的 v1 coverage envelope 是：

```text
contiguous tile/vector movement
PE-local vector map or reduce
explicit route/copy/reduce/materialization boundary
explicit task/subtask/app lifetime
target runtime action stream
```

这组能力本身已经隐含两类 scope：

```text
Stream / chip / task / subtask scope:
  placement, stage/window, route/copy/reduce/materialization lifetime,
  runtime-visible storage boundary.

Fiber / PE / tile scope:
  PE-local vector map/reduce, tile fragment, dtype conversion, chunk/slot,
  operand/materialization policy.
```

所以问题不应该问：

```text
scoped tensor projection 会不会太重？
```

而应该问：

```text
如果没有 scoped tensor projection，coverage checklist 里的语义会不会散落到每个 operator
自己的 task_id / pe_id / lane / chunk / imm / operand symbol 规则里？
```

初步判断：

```text
没有这个抽象，OpenFabric 仍然可以覆盖当前少数 runnable case。
但没有这个抽象，OpenFabric 很难可组合地覆盖更广泛 operator family。
```

特别是：

```text
Row-wise reduce / norm:
  需要 global row shard + PE-local summary slots + SPM scratch lifetime。

Batched GEMM / app_M / app_K / batch expansion:
  需要 global batch/K/window 分片 + PE-local A/B strips + accumulator tile。

Attention:
  materialized GEMM + softmax + GEMM 需要跨 stage tensor/scratch 生命周期；
  fused attention 更需要 local tile lifetime 模型。

Conv2d virtual im2col:
  materialized contiguous tile path 需要 global logical view 到 local contiguous
  tile 的 projection。
```

`operator-coverage-checklist.md` 还明确说 RuntimePlanImage 不应该变成 vector
program image；vector opcodes、tile fragments、tail policy、dtype conversion、
scratch lifetime、collective topology 应该属于 device/package lowering plan。这
基本说明：这些语义需要一个中间表达层，不能塞进 runtime action stream，也不能
散落在 vendor CSV helper 里。

因此，更准确的结论是：

```text
Scoped tensor projection 不是过重抽象，而是当前 coverage envelope 的自然边界。
过重的是马上把 Stream/Fiber view 做成完整调度 IR。
```

推荐落地形态：

```text
Tensor:
  全局 shape/dtype/storage role/semantic role 的 truth source。

StreamTensorView:
  Tensor 在某个 stream/task/subtask/window/participant set 下的 projection。
  不独立拥有 truth，只引用 Tensor + stream context + visible domain。

FiberTensorView:
  StreamTensorView 在某个 fiber/local compute scope 下的 projection。
  不独立拥有 truth，只引用 StreamTensorView + fiber context + local domain。

TileRef:
  FiberTensorView 的 tile coordinate。

TypedTileValue / OperandValue:
  fiber-local tile 被 materialize 成 H256/F32/GEMM strip/SUM slot 等。
```

`StreamTensorView` / `FiberTensorView` 初期应该只是 query/projection object：

```cpp
auto stream_tensor = project(tensor, stream);
auto fiber_tensor = project(stream_tensor, fiber);
auto tile = fiber_tensor.tile(tile_coord);
auto chunk = tile.chunk(0);
```

它统一回答：

```text
这个 Stream / Fiber 拿到 Tensor 的哪一块？
这块怎么切 tile？
tile 的 shape / offset / chunk / slot 怎么推导？
```

它暂时不负责：

```text
全局自动 scheduling
复杂 allocator
通用 memory optimizer
跨 operator fusion planner
```

这个轻量形态可以用 GEMM、softmax、norm、batched GEMM 逐步验证。如果它能减少
重复规则和歧义，就说明这不是为了抽象而抽象，而是在把已经存在的 operator
coverage 边界显式化。

## Tenstorrent 对照初查

OpenFabric 未来如果想服务 Tenstorrent，或者至少证明自己能产出 Tenstorrent 风格
的算子，那么 scoped tensor projection 方向反而更有必要。Tenstorrent 公开软件栈里的基本
边界非常接近：

```text
global tensor / sharded tensor placement
  -> per-Tensix local L1 tile residency
  -> circular buffers
  -> Dst register tile workspace
  -> FPU/SFPU physical compute APIs
```

初步资料来源：

```text
TT-Metalium docs:
  https://docs.tenstorrent.com/tt-metal/latest/tt-metalium/index.html

Tiles:
  https://docs.tenstorrent.com/tt-metal/latest/tt-metalium/tt_metal/advanced_topics/tiles.html

Memory for kernel developers:
  https://docs.tenstorrent.com/tt-metal/latest/tt-metalium/tt_metal/advanced_topics/memory_for_kernel_developers.html

Compute Engines and Data Flow within Tensix:
  https://docs.tenstorrent.com/tt-metal/latest/tt-metalium/tt_metal/advanced_topics/compute_engines_and_dataflow_within_tensix.html

Tenstorrent tt-metal METALIUM_GUIDE:
  https://github.com/tenstorrent/tt-metal/blob/main/METALIUM_GUIDE.md

Tenstorrent FlashAttention report:
  https://github.com/tenstorrent/tt-metal/blob/main/tech_reports/FlashAttention/FlashAttention.md

Tenstorrent CNN report:
  https://github.com/tenstorrent/tt-metal/blob/main/tech_reports/CNNs/ttcnn.md
```

### Tensix Local Capacity

Tenstorrent public material repeatedly describes a Tensix core as having about
1.5MB local SRAM / L1. Official card specs also list aggregate SRAM as:

```text
Blackhole p100a/p150:
  120 Tensix cores
  180MB SRAM
  => 1.5MB per Tensix core
```

Wormhole public docs / reports similarly describe 1.5MB L1 per Tensix core, and
the FlashAttention report describes Wormhole as:

```text
8x10 grid of Tensix cores
120MB total L1 SRAM
1.5MB L1 per Tensix core
```

This is a much larger per-core local memory than a tiny register-only model.
But it is still small compared with full tensors, so it naturally wants:

```text
global tensor sharding
local L1 tile/block residency
explicit tile movement and reuse
```

### Tile Shape

Tenstorrent hardware natively uses 32x32 tiles. The tile docs describe the common
internal layout as:

```text
32x32 tile
  -> four 16x16 faces
  -> faces stored sequentially in memory
```

For bfloat16, the docs give a 32x32 tile size example:

```text
32 * 32 * 2 bytes = 2048 bytes = 2KB
```

This is directly compatible with an OpenFabric split like:

```text
Tensor / StreamTensorView:
  logical tensor domain and projection across a Tensix core grid or stream.

FiberTensorView:
  local L1-resident shard / tile-space inside one Tensix or compute fiber.

TileRef:
  coordinate of a 32x32 tile or block inside the local shard.

TypedTileValue:
  tile resident in circular buffer or Dst register set.
```

### Dst Register Workspace

The TT-Metalium compute-engine docs make another important split: L1 circular
buffers are not the same thing as compute registers.

`Dst` register capacity depends on configuration:

```text
16-bit Dst, double buffering on:   8 tiles visible
16-bit Dst, double buffering off: 16 tiles visible
32-bit Dst, double buffering on:   4 tiles visible
32-bit Dst, double buffering off:  8 tiles visible
```

This maps very well to the OpenFabric distinction between:

```text
FiberTensorView:
  local shard/tile-space in L1 / circular buffers.

TypedTileValue / PhysicalValue:
  a tile currently materialized in Dst registers, matrix engine source registers,
  SFPU view, or output circular buffer.
```

In other words, Tenstorrent also has at least two local levels:

```text
L1/circular-buffer tile residency
Dst/Src register tile workspace
```

This supports not collapsing tile, value, and operand/materialization into one
object.

### Data Movement / Compute Split

TT-Metalium examples use separate data-movement and compute kernels. The
single-core matmul example describes:

```text
reader kernel:
  reads tiles from DRAM into circular buffers

compute kernel:
  consumes circular-buffer tiles and uses matrix engine

writer kernel:
  writes output circular-buffer tiles back to DRAM
```

The multi-core matmul example then distributes work across a grid of Tensix
cores, creates circular buffers on all participating cores, and sets per-core
runtime arguments such as tile count and starting tile index.

This is nearly the same separation OpenFabric is trying to encode:

```text
StreamTensorView placement:
  which stream/core group owns which tensor tile range?

FiberTensorView:
  which local tiles does this fiber/core process?

Logical operation:
  add / matmul / softmax / conv block update.

Physical lowering:
  TT-Metal reader/writer/compute kernels, circular buffers, FPU/SFPU APIs.
```

### Attention / Conv Evidence

Tenstorrent's own public reports reinforce the point:

```text
FlashAttention:
  naive matmul -> softmax -> matmul used sharded memory to fuse operations, but
  larger sequence lengths can exceed L1 and spill intermediates to DRAM.

CNN / convolution:
  local L1 is not big enough for whole input/output tensors; implementations
  load blocks into local L1, compute partial outputs, and move results back.
  The report explicitly discusses sharded local tensors where each core owns a
  distinct contiguous chunk in local L1.
```

This means the interesting abstraction is not just "tile op", but:

```text
global tensor shard
local block/tile residency
local compute tile workspace
materialization / spill / reuse policy
```

### Tenstorrent Implication

For Tenstorrent portability, scoped tensor projection should not be seen as
DFU3500-specific complexity. It aligns with a public tile/NoC accelerator stack:

```text
Tensor / StreamTensorView
  -> TT tensor / sharded tensor / logical tile grid over Tensix cores or streams

FiberTensorView
  -> per-core local L1 shard and circular-buffer tile-space

TypedTileValue
  -> tile resident in CB, Dst, SrcA/SrcB, SFPU view, or packed output

Physical lowering
  -> TT-Metalium reader / writer / compute kernels and FPU/SFPU tile APIs
```

This strengthens the earlier conclusion:

```text
FiberTensorView is not an overfit to DFU3500.
Scoped tensor projection is likely the portable abstraction boundary for
tile/NoC accelerators.
```

The caution remains:

```text
Do not build a full Tenstorrent backend claim until a runnable TT-Metalium or
ttsim artifact exists.
Do not overfit to exact current Dst/LReg tile counts; Tenstorrent docs warn that
some register dimensions can change across hardware generations.
```
