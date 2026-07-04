# How To Read A PE Debug Trace

This note explains how to read a per-PE debug trace such as:

```text
tmp/gpdpu_compiler_examples/gemm_relu/debug_ir/pe/PE00.trace.txt
```

The file answers one question at several lowering levels:

```text
What data does this PE see?
What logical operations does it run?
How are those operations split into tile phases?
Which K instances update each output tile?
Which logical collective bundles provide the required A/B tiles?
```

The trace is a review artifact only. It is not an input to later lowering.
Downstream compiler stages should consume structured IR objects or `plan.json`.

## File Header

Example:

```text
PE pe=PE00 mesh=row/col coord=0,0
```

This file describes one core: `PE00`. Its coordinate in the `4x4` mesh is:

```text
row = 0
col = 0
```

## Layer 0: Global Logical Trace For This PE

Example:

```text
GLOBAL_NODE id=matmul#0 op=matmul inputs=A,B outputs=%t1 pe_action=act_0000 pe_op=local_matmul pe_inputs=lv_A_PE00,lv_B_PE00 pe_outputs=lv_tmp_t1_PE00
GLOBAL_NODE id=relu#1 op=relu inputs=%t1 outputs=%t2 pe_action=act_0016 pe_op=local_relu pe_inputs=lv_tmp_t1_PE00 pe_outputs=lv_tmp_t2_PE00
```

This layer connects the source-level operator graph to this PE's local action
ids.

For the user program:

```text
%t1 = A @ B
%t2 = relu(%t1)
```

the global graph contains:

```text
matmul#0:
  inputs=A,B
  outputs=%t1

relu#1:
  inputs=%t1
  outputs=%t2
```

On `PE00`, those global nodes dispatch to:

```text
matmul#0 -> act_0000 / local_matmul
relu#1   -> act_0016 / local_relu
```

This layer exists so later references such as `producer=act_0000` and
`fused_actions=act_0016` are not floating ids.

## Layer 1: Local Values

Example:

```text
LOCAL pe=PE00 id=lv_A_PE00 tensor=A shape=128x256 offset=0,0 placements=Shard(0),Replicate() producer=-
LOCAL pe=PE00 id=lv_B_PE00 tensor=B shape=256x128 offset=0,0 placements=Replicate(),Shard(1) producer=-
LOCAL pe=PE00 id=lv_tmp_t1_PE00 tensor=%t1 shape=128x128 offset=0,0 placements=Shard(0),Shard(1) producer=act_0000
LOCAL pe=PE00 id=lv_tmp_t2_PE00 tensor=%t2 shape=128x128 offset=0,0 placements=Shard(0),Shard(1) producer=act_0016
```

This layer shows the logical tensor shards visible to this PE.

For `PE00` in the default GEMM example:

```text
A local shard  = A[0:128, 0:256]
B local shard  = B[0:256, 0:128]
%t1 local shard = pre-ReLU matmul result / accumulator view
%t2 local shard = post-ReLU output view
```

At this level, PE00's high-level job is:

```text
%t1[0:128, 0:128] = A[0:128, 0:256] @ B[0:256, 0:128]
%t2[0:128, 0:128] = relu(%t1[0:128, 0:128])
```

## Layer 2: PE Logical Actions

Example:

```text
ACTION pe=PE00 id=act_0000 op=local_matmul node=matmul#0 inputs=lv_A_PE00,lv_B_PE00 outputs=lv_tmp_t1_PE00
ACTION pe=PE00 id=act_0016 op=local_relu node=relu#1 inputs=lv_tmp_t1_PE00 outputs=lv_tmp_t2_PE00
```

This layer is the symbolic per-PE execution trace produced at operator dispatch
time. It is still tensor-shard-level, not tile-level.

For this example:

```text
act_0000:
  local_matmul(A shard, B shard) -> %t1 shard

act_0016:
  local_relu(%t1 shard) -> %t2 shard
```

## Layer 3: Tile-centered Compute Plan

Example:

```text
TILE tile0 wave=wave0 task=0 output=y0->%t2:Y[m=0:64,n=0:64]
  inputs:
    a0 = A[m=0:64,k=0:256] via row_broadcast split=Kx4
    b0 = B[k=0:256,n=0:64] via column_broadcast split=Kx4
  compute:
    c0 = matmul_reduce_k(a0, b0) -> %t1:Cacc[m=0:64,n=0:64]
    y0 = relu(c0) -> %t2:Y[m=0:64,n=0:64]
  output:
    y0 -> %t2:Y[m=0:64,n=0:64]
```

This layer shows the tile-level mini program for each output tile. It is meant
for human review, so it is organized around dataflow rather than raw compiler
fields.

The default example produces four tile programs:

```text
tile0 / wave0 / task0 -> Y[0:64,   0:64]
tile1 / wave1 / task1 -> Y[0:64,   64:128]
tile2 / wave2 / task2 -> Y[64:128, 0:64]
tile3 / wave3 / task3 -> Y[64:128, 64:128]
```

The local names are debug references inside this tile program:

```text
a0, b0:
  input tile spans consumed by this tile phase.

c0:
  accumulator/pre-post-op result. For GEMM, this is %t1:Cacc.

y0:
  final tile result after local post ops. For gemm_relu, this is %t2:Y.
```

The compute chain should be read as:

```text
c0 = matmul_reduce_k(a0, b0) -> %t1:Cacc[...]
y0 = relu(c0)                -> %t2:Y[...]
```

That means GEMM accumulates into `%t1`, then fused ReLU writes `%t2`. It does not
mean GEMM directly writes the final output tile.

Layer 3 intentionally summarizes A/B input spans as `split=Kx4`. The exact K
blocks are shown in Layer 4. Route details are not expanded here; materialize
actions only carry visibility, an obligation key, and a route reference.

## Layer 4: Tile Action Timeline

Example:

```text
K_TILE_STEPS tile0 wave=wave0 task=0 instance_count=4 step_op=gemm_tile_update tile_shape=64x64x64 acc=%t1:Cacc[m=0:64,n=0:64]
  inst0:
    MATERIALIZE ... operand=A tile=A[m=0:64,k=0:64] visibility=row route_ref=route:task0:k0:row0:A:m0:gm0 obligation_key=task0:k0:row0:A:m0:gm0
    MATERIALIZE ... operand=B tile=B[k=0:64,n=0:64] visibility=column route_ref=route:task0:k0:col0:B:n0:gn0 obligation_key=task0:k0:col0:B:n0:gn0
    COMPUTE tile0 inst=0 op=gemm_tile_update tile_shape=64x64x64 inputs=tile:A:A:0:0,tile:B:B:0:0
  inst1:
    MATERIALIZE ...
    MATERIALIZE ...
    COMPUTE ...
```

This is the main tile action timeline. It deliberately puts materialization and
compute on the same program plane:

```text
MATERIALIZE A tile
MATERIALIZE B tile
COMPUTE gemm_tile_update
```

`MATERIALIZE` does not mean "always issue a physical load". It means the
visibility contract for that tile must be satisfied at this point. In V1 the
architecture-independent logical mesh route is lowered, but the physical DFU
COPY/COPYT/DMA instruction route is still not lowered. The line carries:

```text
visibility=row/column
obligation_key=...
route_ref=route:...
```

The logical path through the mesh belongs to the global route lowering file,
not inline in this PE trace. Future physical COPY/COPYT instruction realization
will be a later backend step.

For `wave0`, PE00 computes:

```text
C[0:64, 0:64]
```

with four K instances:

```text
inst=0:
  C_acc[0:64,0:64] += gemm_tile_update(A[0:64,0:64], B[0:64,0:64])

inst=1:
  C_acc[0:64,0:64] += gemm_tile_update(A[0:64,64:128], B[64:128,0:64])

inst=2:
  C_acc[0:64,0:64] += gemm_tile_update(A[0:64,128:192], B[128:192,0:64])

inst=3:
  C_acc[0:64,0:64] += gemm_tile_update(A[0:64,192:256], B[192:256,0:64])
```

This is the core SUMMA-style streaming pattern:

```text
for each C tile:
  for each K block:
    materialize one A tile
    materialize one B tile
    update the same C accumulator view
```

Layer 4 is architecture-independent. It uses `gemm_tile_update`, not `HMMAL`,
because the hundreds of HMMAL/load/convert/template records are backend
expansion details.

The validator checks the GEMM range rule for every K step:

```text
A.m range == C.m range
B.n range == C.n range
A.k range == B.k range
```

## Layer 5: K Tile Step Program

Layer 5 is a compact, backend-independent per-instance program view. It keeps
the same semantic content as Layer 4, but is organized as named K steps and
tile/member values rather than a BSP timeline.

Use it when checking which semantic tile value is produced by each K instance:

```text
m0_0 = gemm_tile_update(A[m=0:64,k=0:64], B[k=0:64,n=0:64])
m0_0.owner = tile_scope:tmp_t1:PE00:0:0
m0_0.view  = tile:tmp_t1:PE00:Cacc:0:0
```

This layer is useful for reasoning about TileScope:

```text
TileScope
  owns member values m0_*
TileView
  projects those resident members as %t1:Cacc
Post-op
  consumes the TileView and writes %t2:Y
```

## Layer 6: Architecture Expansion

Layer 6 answers a different question:

```text
How does this backend implement gemm_tile_update?
```

For the current symbolic `legacy_dfu` backend:

```text
gemm_tile_update 64x64x64
  -> B_HLDT x16
  -> HMUL_A x16
  -> RXINT  x16
  -> HMMAL  x512
  -> TRCTT  x16
```

This is compute/backend instruction lowering. It must not contain route details
such as COPY/COPYT paths, source PE, relay PE, or mesh topology choices.

## Layer 7: Route Summary

Layer 7 is intentionally small:

```text
ROUTE_SUMMARY pe=PE00 derived_obligations=32 route_lowered=32 unresolved_physical=32
  ROUTE_KIND visibility=column obligations=16 physical=unlowered
  ROUTE_KIND visibility=row obligations=16 physical=unlowered
```

It tells you how many visibility obligations this PE participates in and
whether route lowering has happened. V1 lowers architecture-independent logical
mesh routes, while physical instruction routes remain unlowered.

The full derived obligation table is global:

```text
10_derived_collective_obligations.lines.txt
```

That file is a validation view, not source IR. Most rows are derivable from
layout + tile timeline + materialization rules. Logical route patterns live in
the default human-facing file:

```text
11_route_lowering.lines.txt
```

The exhaustive per-route view is kept for deep debugging:

```text
11_route_lowering.verbose.lines.txt
```

Per-PE traces should only reference route ids and summaries because a route is a
cross-PE object.

## Layer 8: DFU Assembly Summary

Layer 8 is the first target-level symbolic assembly surface:

```text
DFU_ASM_SUMMARY pe=PE00 records=...
  ASM_ROLE role=gemm_inner_update count=16
  ASM_ROLE role=materialize_route_edge count=...
  ASM_ROLE role=store_tile count=4
```

It is still not binary. It tells you which structured `DFUAssemblyRecord`
objects this PE owns or participates in. The compact global file is:

```text
14_dfu_assembly.lines.txt
```

The exhaustive record dump is:

```text
14_dfu_assembly.verbose.lines.txt
```

## Reading Order

Use this order when reviewing a PE trace:

```text
0. GLOBAL LOGICAL TRACE
   Check which source graph nodes produced this PE's action ids.

1. LOCAL VALUES
   Check what tensor shards this PE owns or sees.

2. PE LOGICAL ACTIONS
   Check the user-level computation after symbolic per-PE dispatch.

3. TILE-CENTERED COMPUTE PLAN
   Check each output tile's inputs, named compute chain, and final output ref.

4. K INSTANCE STEPS
   Check the materialize/compute timeline for each K block.

5. K TILE STEP PROGRAM
   Check named semantic member values and TileView ownership.

6. ARCHITECTURE EXPANSION
   Check how semantic tile ops expand into backend instruction templates.

7. ROUTE SUMMARY
   Check route-lowering status and global route/obligation file refs.

8. DFU ASSEMBLY SUMMARY
   Check target-level symbolic records before binary encoding.
```

## One-sentence Summary For PE00

```text
PE00 owns the top-left 128x128 output shard; splits it into four 64x64 phases;
each phase streams four K blocks; each K block consumes one row-broadcast A tile
and one column-broadcast B tile; GEMM accumulates into %t1, then fused ReLU
writes %t2.
```
