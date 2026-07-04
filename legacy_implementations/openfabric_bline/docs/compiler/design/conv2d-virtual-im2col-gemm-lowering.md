# Conv2d Lowering: Virtual Im2col GEMM And Tile-based Backends

本文解释两个问题：

```text
1. virtual_im2col_gemm 是什么意思。
2. conv2d 在一般 tile-based 后端里通常怎么实现，以及它怎样接到当前
   OpenFabric compiler 的 Tile Program / DFU Graph 链路。
```

结论先放前面：当前 compiler 已经有 GEMM+ReLU 的 tile lowering、collective、
DFU graph、packing、residency、storage/runtime-frame 骨架；conv2d 可以先通过
`virtual_im2col_gemm` 接入这个骨架，再逐步发展成 direct conv2d tile primitive。

## Conv2d 的本质

先看普通 NCHW conv2d：

```text
X: [N, C_in, H, W]
W: [C_out, C_in, K_h, K_w]
Y: [N, C_out, H_out, W_out]
```

对每个输出元素：

```text
Y[n, oc, oh, ow] =
  sum over ic, kh, kw:
    X[n, ic, oh * stride_h + kh * dilation_h - pad_h,
             ow * stride_w + kw * dilation_w - pad_w]
  * W[oc, ic, kh, kw]
```

所以 conv2d 是一个带规则地址映射的 reduction：

```text
output index = (n, oc, oh, ow)
reduction index = (ic, kh, kw)
```

GEMM 也是 reduction：

```text
C[m, n] = sum over k: A[m, k] * B[k, n]
```

conv2d 能映射成 GEMM，是因为可以把索引重命名：

```text
M = N * H_out * W_out
N_gemm = C_out
K = C_in * K_h * K_w

A_im2col[M, K] = X 的滑窗展开
B_col[K, N_gemm] = W reshape 后的权重矩阵
C[M, N_gemm] = Y reshape 后的输出
```

换句话说：

```text
conv2d(X, W) 等价于 im2col(X) @ reshape(W)
```

这里的 `im2col` 不是数学必须物化的真实大矩阵，它只是说明每个 GEMM A 元素
应该从 X 的哪个位置读取。

## 什么是 Im2col

`im2col` 的意思是 image-to-column，把每个输出位置对应的 input patch 拉平成
一行或一列。

例如单 batch、单输出位置 `(oh, ow)` 的 patch 是：

```text
X[:, oh:oh+K_h, ow:ow+K_w]
```

如果 `C_in=3, K_h=3, K_w=3`，这个 patch 有：

```text
3 * 3 * 3 = 27
```

个元素。im2col 会把它变成 GEMM 的一条 K 向量。

所有 `(n, oh, ow)` 输出位置组成 GEMM 的 M 维：

```text
m = ((n * H_out) + oh) * W_out + ow
```

所有 `(ic, kh, kw)` 组成 GEMM 的 K 维：

```text
k = ((ic * K_h) + kh) * K_w + kw
```

权重映射到 GEMM B：

```text
B[k, oc] = W[oc, ic, kh, kw]
```

输出映射回来：

```text
Y[n, oc, oh, ow] = C[m, oc]
```

## 什么是 Virtual Im2col GEMM

naive im2col 会真的生成一个大矩阵：

```text
A_im2col: [N * H_out * W_out, C_in * K_h * K_w]
```

这个矩阵通常很大，而且包含重复数据。相邻输出窗口会复用大量 input 像素。

`virtual_im2col_gemm` 的意思是：

```text
逻辑上按 im2col + GEMM 来规划。
实际 lowering 时不物化完整 im2col 矩阵。
每个 tile / k-block 需要 A_im2col 的哪个片段，就按索引公式从 X 中取对应窗口。
```

也就是把 GEMM 的 A tile 从普通矩阵 tile 变成一个 `TileView`：

```text
A_view[m_tile, k_block]
  = virtual_im2col_view(
      X,
      output_position_range = m_tile,
      reduction_patch_range = k_block,
      stride / padding / dilation / layout
    )

B_tile[k_block, oc_tile]
  = weight_view(W, oc_tile, ic/kh/kw range)

C_tile[m_tile, oc_tile]
  = gemm_reduce_k(A_view, B_tile)
```

关键点是：`A_view` 是 view，不一定是 materialized tile。

如果硬件指令可以按 stride/window 地址直接取数，后端可以直接用这个 view。
如果硬件只能吃连续 operand tile，后端就要在每个 k-block 之前加一个
materialization step：

```text
gather/im2col_tile_materialize(X window -> operand A tile)
gemm_tile_update(A operand tile, B operand tile -> C accumulator)
```

这就是 virtual 的含义：编译器 IR 里保留 im2col 语义，但把“是否真的搬成连续
A tile”推迟到后端/资源调度层决定。

## Tile-based 后端里的常见 Conv2d 实现

一般 tile-based accelerator / compiler 后端里，conv2d 常见有三类实现。

### 1. Explicit Im2col + GEMM

流程：

```text
1. 把 input feature map 展开成 A_im2col。
2. 把 weight reshape 成 B。
3. 调 GEMM kernel。
4. 把 C reshape 回 Y。
```

优点：

```text
GEMM 后端最容易复用。
调度、tiling、accumulator、post-op fusion 都可以沿用 GEMM。
```

缺点：

```text
im2col buffer 巨大。
读写放大明显。
相邻窗口的输入复用被破坏。
```

这个方法适合快速验证，不适合作为最终高性能后端。

### 2. Virtual Im2col + GEMM

流程：

```text
1. 不生成全局 A_im2col。
2. 输出 tile 仍按 GEMM C tile 规划。
3. reduction 轴按 ic/kh/kw 分块。
4. 每个 k-block 只生成当前 GEMM update 需要的 A tile view。
5. 后端选择直接读取 view，或局部 materialize 成 operand tile。
```

优点：

```text
复用 GEMM 的 tile/reduction/accumulator 结构。
避免全局 im2col 存储爆炸。
可以逐步接入 input-window 复用、halo、padding mask。
```

缺点：

```text
A tile 的地址映射比普通 GEMM 复杂。
需要表示 TileView、materialization policy、padding/halo。
如果硬件只支持连续 operand tile，仍然需要局部 gather/materialize。
```

这通常是从 GEMM-only compiler 走向 conv2d 的最稳第一步。

### 3. Direct Conv Tile Primitive

流程：

```text
for output tile:
  init accumulator
  for ic_tile:
    for kh:
      for kw:
        load/reuse input activation tile/window
        load/reuse weight tile
        conv_update accumulator
  apply post ops
  store output tile
```

优点：

```text
能显式利用 input tile / halo / weight / output-stationary 复用。
更接近高性能手写 conv kernel。
可以针对 1x1、3x3、depthwise、group conv 做专门模板。
```

缺点：

```text
需要新的 tile phase 和 backend instruction template。
调度复杂度比 GEMM 大。
需要更强的 resource/lifetime/scratchpad 规划。
```

这个适合成为第二阶段或性能阶段。

## Tile Schedule 视角

把 conv2d 看成 tile program，可以写成：

```text
for each output tile Y_tile over (m_tile, oc_tile):
  init C_acc
  for each reduction block r_block over (ic, kh, kw):
    A_view = input_window_view(X, m_tile, r_block)
    B_tile = weight_tile(W, r_block, oc_tile)
    C_acc += A_view @ B_tile
  post_ops(C_acc)
  store Y_tile
```

其中：

```text
m_tile covers a range of (n, oh, ow)
oc_tile covers output channels
r_block covers some slice of (ic, kh, kw)
```

这个结构和当前 GEMM 的 K stream 很像：

```text
GEMM:
  for k_block:
    A[m_tile, k_block]
    B[k_block, n_tile]
    C[m_tile, n_tile] += A @ B

Conv2d virtual im2col:
  for r_block=(ic,kh,kw):
    A_view[(n,oh,ow), r_block]
    B[r_block, oc_tile]
    Y[(n,oh,ow), oc_tile] += A_view @ B
```

所以第一阶段可以复用 `local_gemm_summa` 的很多结构，但不能假装它还是普通
matrix A tile。A 的 descriptor 要从：

```text
tensor=A, role=A, global_m, global_k
```

扩展成：

```text
tensor=X, role=activation_window_view
logical_m_range
logical_reduction_range
source_layout=NCHW
window_formula:
  n, oh, ow, ic, kh, kw -> X[n, ic, ih, iw]
padding_policy
materialization_policy
```

## Distributed / Mesh 视角

当前 GEMM baseline 的 mesh 语义是：

```text
A[M,K]: [Shard(0), Replicate()]
B[K,N]: [Replicate(), Shard(1)]
C[M,N]: [Shard(0), Shard(1)]
```

conv2d virtual GEMM 可以先选类似的布局：

```text
X/im2col A[M,K]: [Shard(0), Replicate()]
W/B[K,C_out]:   [Replicate(), Shard(1)]
Y/C[M,C_out]:   [Shard(0), Shard(1)]
```

含义：

```text
mesh row shards output positions: N * H_out * W_out
mesh col shards output channels: C_out
activation windows are visible across a mesh row
weight output-channel tiles are visible across a mesh column
```

这和 SUMMA 的通信形态一致：

```text
row_broadcast activation-window A_view
column_broadcast weight B_tile
local reduction update into Y accumulator
```

但 conv2d 多了一个重要问题：halo。

如果 mesh row 按 output positions 切分，某个 PE 的 output tile 可能需要 input
边界外的一圈邻居数据：

```text
needed input range =
  output_range projected through stride/dilation/kernel/padding
```

这个 needed input range 可能超过本 PE 原本拥有的 X shard。后端有两种处理：

```text
1. source layout 让 X 的 activation shard 带 halo 或 replicated window。
2. lowering 显式插入 halo materialization / collective / DMA copy。
```

第一版为了简单，建议限制到：

```text
X placements match output-position sharding and require explicit halo-ready input,
or accept only shapes where each PE's needed input window is locally available.
```

不要偷偷插入 halo 通信。和当前 TODO 里的 layout policy 一样：layout movement 必须
来自 source-visible intent 或明确 lowering rule。

更长期的抽象计划见 `rfc-current-status-and-next-plan.md` 中的
"Stencil SPMD And Halo Exchange"。那里的核心观点是：GEMM 是
broadcast-style SPMD，conv2d / stencil 是 neighbor-visibility SPMD；二者都应
落到 `TileCollectiveAction -> DFU Graph` 的同一条链路里。

## 接到当前 Compiler 的方式

当前代码里：

```text
ops.matmul(...)
  -> node op = matmul
  -> PE action = local_matmul
  -> phase_kind = local_gemm_summa
  -> legacy_dfu expands only local_gemm_summa
```

conv2d 需要新增：

```text
ops.conv2d(...)
  -> node op = conv2d
  -> PE action = local_conv2d
  -> strategy = virtual_im2col_gemm or direct_conv2d
```

第一阶段建议 lowering 成：

```text
phase_kind = local_conv2d_virtual_im2col_gemm
payload:
  template_family = reduction_stream
  semantic_op = conv2d
  algorithm = virtual_im2col_gemm
  input_layout = NCHW
  output_layout = NCHW
  stride / padding / dilation / groups
  output_tile descriptor
  reduction_blocks over ic/kh/kw
  activation_window_views
  weight_tiles
  accumulator_view
  post_ops
```

随后可以让 architecture backend 做两种选择：

```text
if activation_window_view can be consumed directly:
  expand_conv2d_virtual_gemm_update(...)
else:
  materialize_activation_window_tile(...)
  expand_gemm_tile_update(...)
```

这样即使第一版最终仍然调 GEMM tile update，IR 也不会撒谎：它知道 A tile 是
conv2d window view，不是普通 dense input matrix。

## Instruction-set Support

当前抽取出的指令集文档里没有看到直接的 `CONV` / `CONV2D` 指令。对 conv2d
最有用的是两组能力：

```text
1. tensor matrix multiply-accumulate:
   HMMAL / HMMA / IMMA / IMMAU / IMMAIU / IMMAUI

2. activation-window materialization and boundary handling:
   HLDT / ILDMT / LDM / LDN / LDSHIF / SLDSHIF
   HSTT / STM / SSTM / STSHIF / SSTSHIF
   SHFL / MASK / COPYT
```

### Tensor Compute Instructions

`docs/instruction-set/dfu3500-tensor/README.md` identifies the GEMM-relevant
tensor path as:

```text
RXINT   operand -> tensor tmp register
HMMAL   fp16 matrix multiply-accumulate, operand A/B -> tmp register
TRCTT   tensor tmp register -> operand
```

For fp16 conv2d, the most relevant instruction is `HMMAL`:

```text
HMMAL:
  fp16 64x64 matrix multiply
  supports sparse mode
  source operands come from opmem
  destination is tmp0..tmp7
```

This is exactly why `virtual_im2col_gemm` is attractive. Once the compiler has
formed a dense activation-window A tile and a dense weight B tile, the inner
conv update can reuse the same tensor-multiply path as GEMM:

```text
activation_window_tile @ weight_tile -> output accumulator
```

For int8 / quantized conv2d, the tensor instruction docs also list `IMMA`,
`IMMAU`, `IMMAIU`, and `IMMAUI`:

```text
IMMA    int8  * int8  + int32
IMMAU   uint8 * uint8 + uint32
IMMAIU  int8  * uint8 + int32
IMMAUI  uint8 * int8  + int32
```

Those are the likely quantized-conv path. SIMD-side `DP4A` / `QMADD` can also
express 8-bit dot products, but they look more like a fallback or small-vector
path than the main tensor-tile path.

### Window Materialization Instructions

The missing piece for conv2d is not multiply-add. It is how to feed `HMMAL` with
the right activation-window tile.

The SIMD memory instruction table has several useful candidates:

```text
LDN:
  Value(dst) = SPM(LD Base Reg X + IMM) * 4Byte

LDM:
  Value(dst) = 32{SPM(LD Base Reg X + IMM)}

LDSHIF:
  Value(dst) = SPM(LD Base Reg X + IMM (+/-) LRX[shft_No] * shft_cnt)

SLDSHIF:
  4096-bit pseudo instruction.
  Assembler-visible, translated into four LDSHIF instructions.
```

The important one for conv2d is `LDSHIF` / `SLDSHIF`: it can add or subtract a
runtime shift term from the base address. That is relevant to sliding-window
access because conv2d addresses are affine in output position and kernel offset:

```text
ih = oh * stride_h + kh * dilation_h - pad_h
iw = ow * stride_w + kw * dilation_w - pad_w
```

A first lowering can use this in a conservative way:

```text
for each output-position tile and r_block=(ic,kh,kw):
  compute/load base address for the X window
  use HLDT/ILDMT/SLDSHIF to materialize a contiguous A operand tile
  feed that A tile to HMMAL with the corresponding weight B tile
```

This still does not prove direct strided window consumption by `HMMAL`; it only
shows the instruction set has enough memory/addressing pieces to materialize the
window tile locally.

### Shuffle And Mask Instructions

`SHFL` can permute SIMD lanes and has a shift mode used by existing reductions.
For conv2d, it can help with local rearrangement after loading partial windows,
especially when a window fragment is almost contiguous but needs lane rotation or
packing before becoming the GEMM A tile.

`MASK`, `STD`, `STM`, `HSTT`, `SSTM`, `STSHIF`, and `SSTSHIF` matter for output
boundary and padding behavior:

```text
MASK configures store masks.
HSTT can combine with MASK for masked 4096-bit stores.
STM/SSTM can write only a low/high subset of 8-bit indexed components.
STSHIF/SSTSHIF combine shifted addressing with masked store behavior.
```

These are more directly useful for:

```text
right/bottom output edge stores
partial tiles
padding-derived dummy lanes
post-conv quantized writeback
```

For input padding, the compiler may prefer to materialize missing input lanes as
zero inside the activation-window tile, then use the normal `HMMAL` path. Store
masks are better for output boundary writes than for making invalid input lanes
disappear inside the multiply.

### Cross-PE Reuse

`COPYT` copies a raw logical operand from one PE to another. Existing notes say
GEMM templates use it to propagate A tiles along the mesh and reduce SPM/DRAM
loads.

For conv2d, this can support two reuse patterns:

```text
1. broadcast/reuse weight tiles across PEs that share output-channel blocks.
2. share activation-window tiles or halo materialization results across adjacent
   PEs when their output-position tiles overlap.
```

The second point should be treated as a later optimization. First implementation
should keep halo/window movement explicit and simple.

### Practical Conclusion

The instruction docs support the following staged conv2d plan:

```text
V1:
  virtual_im2col_gemm
  materialize activation-window A tiles with memory/shift/shuffle instructions
  compute with HMMAL/HMMA or IMMA-family tensor instructions
  store with HSTT/STM/SSTM plus MASK for partial output tiles

V2:
  improve window materialization using SLDSHIF/ILDMT/SHFL
  add explicit halo movement with COPYT / route lowering

V3:
  consider direct_conv2d tile primitive if hardware templates or simulator
  examples show a better non-GEMM instruction sequence
```

So the answer is:

```text
No direct conv2d instruction is visible in the extracted docs.
Yes, the instruction set has the right building blocks to implement conv2d
through virtual_im2col_gemm, and probably quantized conv through IMMA-family
instructions.
```

## 为什么不要只写成 matmul

如果 frontend 直接把 conv2d 改写成普通 matmul，会丢掉这些关键信息：

```text
原始 X/W/Y tensor 形状和布局。
stride/padding/dilation/groups。
input window 与 output tile 的对应关系。
halo / boundary mask。
是否真的物化了 im2col。
后续 direct conv 优化机会。
```

对甲方或后续后端来说，`conv2d` 必须在 IR 中保留 semantic identity。GEMM 只能是
它的一个 lowering strategy。

推荐表述是：

```text
Conv2d is represented as a semantic operator in the compiler frontend.
The first backend strategy lowers it to a virtual-im2col reduction stream that
reuses the existing GEMM tile update path where legal. The im2col matrix is not
globally materialized; activation tiles are represented as window TileViews and
are materialized only if the selected hardware template requires contiguous
operand tiles.
```

中文版本：

```text
conv2d 在前端仍然是语义算子，不会被永久抹平成 matmul。
第一阶段后端策略把它 lower 成 virtual-im2col 的 reduction stream，从而复用已有
GEMM tile update 能力。im2col 大矩阵不全局物化；activation 输入以窗口
TileView 表示，只有当硬件模板需要连续 operand tile 时，才在局部 tile/k-block
范围内 materialize。
```

## 当前 Compiler 需要补的最小工程项

```text
1. Frontend op:
   add conv2d(input, weight, bias=None, stride, padding, dilation, groups)

2. Shape rule:
   compute Y shape and fail fast for unsupported rank/layout/groups.

3. Strategy registry:
   op=conv2d -> strategy=virtual_im2col_gemm for supported cases.

4. Tile phase:
   add local_conv2d_virtual_im2col_gemm.

5. Tile descriptor:
   add activation_window_view descriptor, not only A/B/C matrix descriptors.

6. Route/collective:
   reuse row/column visibility where layout matches SUMMA-like decomposition;
   add explicit halo/materialization obligations later.

7. Architecture backend:
   first implementation may reuse GEMM update after local materialization;
   later add direct conv2d template.

8. Validator/tests:
   validate output shape, reduction block coverage, padding mask, tile use-def,
   and no implicit layout/halo movement.
```

## Current Implemented Slice

The current tree now implements the first pre-binary slice of the plan above.
It is deliberately symbolic after tile/graph/assembly boundaries, but it is
structured enough for later lowering passes to consume.

Implemented:

```text
1. Frontend:
   ops.conv2d(input, weight, stride, padding, dilation, groups)
   with rank-4 NCHW/OIHW shape checks.

2. Supported v1 layout:
   input  X[N,C,H,W]      placements=[Shard(2), Replicate()]
   weight W[O,C,K_h,K_w]  placements=[Replicate(), Shard(0)]
   output Y[N,O,H_o,W_o]  placements=[Shard(2), Shard(1)]

3. Tile phase:
   phase_kind=local_conv2d_virtual_im2col_gemm
   semantic_op=conv2d
   algorithm=virtual_im2col_gemm
   payload includes GEMM view M/N/K, activation_window_view, weight_view,
   output_tile, and halo_obligations.

4. Communication:
   spatial row halos become logical collective_bundles with
   collective_kind=halo_exchange.
   Route lowering honors the source_pe chosen by the halo obligation.

5. DFU graph:
   halo_exchange routes become tile_collective_action nodes before conv2d
   compute nodes; conv2d outputs feed store_tile nodes.

6. Symbolic assembly:
   conv2d compute records use role=conv2d_virtual_im2col and remain
   binary_status=unencoded.
   The template records include VIM2COL_VIEW_SYMBOLIC and HMMAL_SYMBOLIC.

7. Runtime/output ABI:
   env.output("Y", y) becomes per-PE store_tile nodes and runtime-frame
   output_store base symbols for Y.
```

Validated example:

```text
compiler/examples/conv2d.py
X: [1, 3, 32, 32], W: [16, 3, 3, 3], stride=1, padding=1

to_plan() currently produces:
  16 local_conv2d_virtual_im2col_gemm phases
  24 halo_exchange bundles/routes
  16 conv2d DFU graph nodes
  24 tile_collective_action nodes
  16 store_tile nodes
  16 conv2d_virtual_im2col assembly payloads
  16 output_store runtime symbols for Y
```

Still not implemented:

```text
1. Physical halo exchange instruction selection and exact COPY/COPYT schedule.
2. Direct conv2d hardware template; v1 is virtual-im2col symbolic lowering.
3. Bias, groups/depthwise, NHWC, width-sharded halo, asymmetric padding tuple
   beyond the current shape/metadata path.
4. Exact per-k-block im2col materialization into operand slots.
5. Binary serialization for the conv2d/halo templates.
```

## What To Tell A Reviewer

如果 reviewer 问“你们是不是只能做 GEMM”，回答应该是：

```text
当前验证样例是 GEMM+ReLU，但 IR 的真实边界是 Tile Program / TileValue /
TileCollectiveAction / DFU Graph，不是 GEMM 本身。GEMM 是第一条已经展开到
legacy DFU symbolic assembly 的 backend strategy。conv2d 的第一条可落地路线是
virtual_im2col_gemm：把 conv2d 表达为带窗口 TileView 的 reduction-stream tile
program，从而复用现有 GEMM accumulator、collective、DFU graph、packing 和
residency 层。后续 direct conv2d 只是替换 architecture template 和 tile
materialization policy，不需要推翻上层 IR。
```

这句话的重点是：

```text
GEMM is the first specialization.
Tile Program is the abstraction boundary.
Conv2d is a semantic op with multiple lowering strategies.
```
