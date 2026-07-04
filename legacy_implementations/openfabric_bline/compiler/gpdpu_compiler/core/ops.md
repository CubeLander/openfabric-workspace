# ChipProgram Ops Draft

This note is embedded beside the refactored `core.ops` prototype. It describes
candidate chip-level ops for the DFU-first SRAM program. These ops are logical
chip-level program records, not DFU PE instructions and not SimICT binary rows.

## Scope

`ChipProgram` models the SRAM boundary plus logical on-chip SPMD computation:

```text
SRAM tensor
  -> load_sram_tensor
  -> logical DTensor / tile values on a logical fabric
  -> compute / collective / view ops
  -> store_sram_tensor
  -> SRAM tensor
```

At this layer, it is OK to describe logical fabric concepts such as shard,
broadcast, reduce, and tile ownership. It is not OK to describe DFU vendor ABI
facts such as `inst_t`, `subtask_conf_info_t`, `exeBlock_conf_info_t`, CBUF/MICC
layout, PE-to-PE physical route edges, or HMMAL instruction counts.

## Tier 0: must work first

1. GEMM / MatMul
2. BiasAdd
3. ReLU / SiLU / GELU approximate
4. Elementwise Add / Mul
5. RMSNorm / simplified LayerNorm
6. Reshape / Transpose / Layout convert

## Tier 1: LLM / MLP common path

7. Batched GEMM
8. QKV projection
9. Fused MLP: MatMul + Bias + Activation
10. Reduce / simplified Softmax

## Tier 2: CNN / vision models

11. Conv2D 1x1
12. Conv2D 3x3 stride=1 padding=same
13. Depthwise Conv2D
14. Pooling
15. Im2col / virtual-im2col lowering

## Tier 3: later work

16. Full attention path
17. Dynamic shape
18. Sparse / gather / scatter
19. Weird layout + halo sharing

## Candidate op groups

### Program / declaration ops

- `declare_sram_tensor`: declare a chip-visible SRAM/SPM tensor with explicit
  address-space region, offset, shape, dtype, and layout. Output tensors are
  declared the same way before `store_sram_tensor` writes into them.
- `declare_const`: declare scalar/small constants such as epsilon, alpha, beta.
- `alias_view`: create an alias/view without copying data.
- `materialize`: force a logical value or view into a concrete logical tensor.

### SRAM boundary ops

- `load_sram_tensor`: read an SRAM tensor into a logical DTensor/tile value.
- `store_sram_tensor`: write a logical DTensor/tile value back to SRAM. Current
  first assumption: store writes a whole tensor, not arbitrary scattered slices.
- `copy_sram_tensor`: SRAM-to-SRAM copy, optional later.
- `fill_sram_tensor`: initialize SRAM tensor, output buffer, zero buffer, or
  padding buffer.

### Layout / shape ops

- `reshape`
- `transpose`
- `layout_convert`
- `slice_view`
- `concat`
- `split`
- `pad`
- `broadcast_shape`
- `contiguous`
- `im2col_view`
- `virtual_im2col_view`

### Elementwise ops

- `add`
- `mul`
- `sub`
- `div`
- `add_scalar`
- `mul_scalar`
- `maximum`
- `minimum`
- `clamp`
- `exp`
- `sqrt`
- `rsqrt`
- `tanh`
- `sigmoid`
- `relu`
- `silu`
- `gelu_approx`

### GEMM / dense ops

- `matmul`
- `batched_matmul`
- `bias_add`
- `linear`: matmul + bias.
- `qkv_projection`: multi-output projection for attention input.
- `mlp_fused`: matmul + bias + activation.
- `matmul_accumulate`: partial accumulation path for future schedules.

### Norm / reduce ops

- `reduce_sum`
- `reduce_max`
- `reduce_mean`
- `reduce_var`
- `rms_norm`
- `layer_norm`
- `normalize_affine`: norm result followed by scale/bias.
- `softmax_approx`

### CNN ops

- `conv2d_1x1`
- `conv2d_3x3_same`
- `depthwise_conv2d`
- `pool2d_max`
- `pool2d_avg`
- `im2col`
- `conv2d_virtual_im2col`

### Logical collective ops

These are logical collectives over logical DTensor values on a logical fabric.
They are not DFU physical route records yet.

- `broadcast`
- `reduce`
- `all_reduce`
- `all_gather`
- `reduce_scatter`
- `scatter`
- `gather`
- `exchange`
- `halo_exchange`

Current decision: do not introduce standalone "one PE owns this tile fragment"
objects at chip level yet. The chip-level program should stay dumb and SPMD.
Collectives operate on Tensor-like values, including scalar tensors. Placement
metadata describes whether the value is replicated, sharded, or partial.

For the first DFU-first implementation:

- `broadcast` should mean changing a tensor value's logical placement/visibility,
  not broadcasting an anonymous PE-local buffer.
- `reduce` should consume a Tensor with partial/sharded semantics and produce
  another Tensor value.
- `all_reduce` should consume a Tensor with partial semantics and produce a
  replicated Tensor value.
- scalar values such as max, mean, norm denominator, epsilon-adjusted scale, or
  reduction result are still Tensors, usually rank-0 or rank-1.

Avoid modeling internal matrix fragments as first-class chip-level objects until
we have a concrete lowering need. If DFU lowering needs row/column transfers for
GEMM, that should be derived later from `matmul` plus placements/fabric, not
hand-authored as chip-level broadcast of a local tile fragment.

### Fused / region ops

- `fused_matmul_bias_relu`
- `fused_matmul_bias_silu`
- `fused_matmul_bias_gelu`
- `fused_rmsnorm_matmul`
- `fused_conv_bias_activation`
- `fusion_region_begin`
- `fusion_region_end`

## Tier 0 minimal closed loop

A useful first SRAM program should support at least:

```text
declare_sram_tensor
load_sram_tensor
store_sram_tensor
matmul
bias_add
relu / silu / gelu_approx
add / mul
reduce_sum / reduce_mean
rms_norm / layer_norm
reshape / transpose / layout_convert
```

The first implementation may keep many of these as logical records only. DFU
physical lowering can then decide which records become route edges, task rows,
subtasks, instance tables, or vendor instruction templates.
