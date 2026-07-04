# GEMM Tile DAG Notes From Legacy Example

Source inspected:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/build_out/gemm_template_fusion_new_temp_analysis/sources
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/CASE/gemm_template_fusion/csv_generate/conf_PEmap.h
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/CASE/gemm_template_fusion/csv_generate/test_app_conf_generate.c
```

## Observed Legacy Structure

The generated GEMM runtime package splits one GEMM into four tasks:

```text
task0..task3
```

Each task has three non-fusion subtasks:

```text
subtask1: load C tile and multiply by beta
subtask2: load/broadcast A, load B, scale A by alpha, run HMMAL accumulation
subtask3: store C tile
```

`app*.conf` shows:

```text
subtask1 Instance Times: 1
subtask2 Instance Times: 4
subtask3 Instance Times: 1
```

The four instances of `subtask2` correspond to K-slice hardware looping.
`test_app_conf_generate.c` advances the subtask2 base table as:

```c
base_addr0 += 64 * sizeof(short) / sizeof(float);                  // A K offset
base_addr1 += 64 * GEMM_INPUT2_WIDTH_app * sizeof(short)/sizeof(float); // B K offset
```

## Hardware Tile Shape In The Example

For the configured case:

```text
M = 512
K = 256
N_app = 512
PE mesh = 4 x 4
TASK_NUM = 4
subtask2 instance count = 4
```

The legacy template uses a 64x64 C hardware tile:

```text
C_tile = 64 x 64
A_tile per K instance = 64 x 64
B_tile per K instance = 64 x 64
```

Evidence:

```text
task*_subtask*.c comments: "16 registers can hold one 64*64 matrix"
tmp = 16
type = 16
one fp16 SIMD128 operand = 4096b = 256 fp16 lanes
16 operands * 256 fp16 = 4096 fp16 = 64 * 64
```

Within one 64x64 tile:

```text
A uses 16 operands: each operand is one 4x64 row strip.
B uses 16 operands: each operand is loaded from memory as one 4x64 row-major
  strip of B's KxN matrix. HMMAL's immediate controls how that fragment is
  interpreted by the tensor pipeline.
C uses 16 operands: each operand is one 4x64 row strip of output/accumulator materialization.
```

`HMMAL` is then emitted for combinations of A/B operand strips. The exact tensor
pipeline is encoded in `imm`; the compiler IR should not expose this at the
logical tile-DAG layer. Treat it as device lowering detail.

## PE Mapping Observed

`conf_PEmap.h` maps each task to 16 physical PE jobs. For task0, those 16 jobs
cover:

```text
M rows: two 64-row bands
N cols: eight 64-col bands
```

In other words, the legacy physical schedule for one task is closer to:

```text
2 x 8 logical output tiles mapped onto 16 PEs
```

than a simple 4x4 output-sharded DTensor view. Four tasks advance the M band,
covering the full M=512.

This means our current DTensor logical shard, for example 128x128 per PE, should
be further tiled before device lowering:

```text
128x128 local_matmul
  -> four 64x64 hardware C tiles
```

The backend is free to schedule those 64x64 tiles across tasks/subtasks/instances.

## Legacy Schedule vs DTensor Example

The DTensor-first compiler direction keeps logical output ownership stable and
then lowers it with a row/column broadcast schedule over the mesh.

For `C = 512 x 512`, this gives each PE a logical output shard:

```text
C local per PE = 128 x 128
```

The legacy physical schedule is different. In each task, 16 PE jobs cover:

```text
2 M-tiles x 8 N-tiles
each tile = 64 x 64
```

Across four tasks, M advances by 128 rows per task:

```text
task0: C rows   0..127
task1: C rows 128..255
task2: C rows 256..383
task3: C rows 384..511
```

These are two different physical schedules for the same global GEMM:

```text
DTensor square ownership:
  + clean 4x4 logical mapping
  + each PE owns a compact 128x128 C block
  + can tile locally into four 64x64 C tiles
  - naive SPM loads replicate A across mesh columns and B across mesh rows
  - efficient implementation needs explicit broadcast/redistribute bundles

Legacy 2x8 per-task schedule:
  + matches observed COPYT pattern: A is loaded by row leaders and copied along rows
  + keeps one 64x64 C tile as the immediate working unit
  + may fit mesh COPY paths and operand pressure better
  - B is loaded by every compute PE and appears to be reloaded across M tasks
  - PE output ownership is less contiguous and less DTensor-like
```

Keep these layers separate:

```text
DTensor placement:
  logical tensor ownership and user-visible layout contract

tile scheduler:
  chooses how logical local shards are decomposed and mapped to physical PE work

device lowering:
  chooses COPYT/HLDT/HMMAL/HSTT sequences for the scheduled tiles
```

## Concrete Matrix And Address Mapping

The example computes:

```text
C[M, N] = A[M, K] @ B[K, N]

A = 512 x 256
B = 256 x 512
C = 512 x 512
```

The runtime addresses are in 32-bit word units, while matrix elements are fp16.
So one address unit holds two fp16 values.

For a row-major fp16 matrix:

```text
word_offset(row, col, stride_cols) = (row * stride_cols + col) / 2
```

The SPM bases in `conf_PEmap.h` are:

```text
A_base = 0
B_base = A_base + 512 * 256 / 2 = 65536
C_base = B_base + 256 * 512 / 2 = 131072
```

K is split by hardware instances:

```text
K = 256 = 4 * 64
subtask2 Instance Times = 4
```

Each subtask2 instance advances:

```text
A base by 64 fp16 columns = 32 words
B base by 64 rows of B    = 64 * N / 2 = 16384 words
```

Thus the same CSV offsets are reused for four K slices:

```text
k0: A[:,   0: 64] x B[  0: 64, :]
k1: A[:,  64:128] x B[ 64:128, :]
k2: A[:, 128:192] x B[128:192, :]
k3: A[:, 192:256] x B[192:256, :]
```

## A Broadcast Pattern

The legacy implementation does not load A on every PE.

`loadA`:

```text
PE 0, 4, 8, 12 load A from SPM
```

`copyA`:

```text
0 -> 1 -> 2 -> 3
4 -> 5 -> 6 -> 7
8 -> 9 -> 10 -> 11
12 -> 13 -> 14 -> 15
```

So A is loaded by the first PE in each physical mesh row and propagated with
`COPYT`. B is loaded locally by each compute PE.

Tile DAG implication:

```text
A_tile_load(row_leader)
  -> A_tile_copy(row_leader, col1)
  -> A_tile_copy(col1, col2)
  -> A_tile_copy(col2, col3)

B_tile_load(each compute PE)

C_tile_init/load
  -> HMMAL accumulation over K instances
  -> C_tile_store
```

The COPY chain is a cross-PE dependency bundle and must be scheduled atomically
or with explicit BSP alignment.

## Suggested IR Split

Do not lower `local_matmul` directly into instructions. Add one middle layer:

```text
PELogicalAction(local_matmul)
  -> HardwareGemmTile DAG
  -> DeviceTileAction DAG
  -> BSP/subtask schedule
  -> CSV/instructions
```

First tile-DAG node types:

```text
GemmCInitTile      // load existing C and beta-scale, or zero-init
GemmALoadTile      // load A 64x64 tile from SPM
GemmACopyTile      // COPYT A tile across a mesh row
GemmBLoadTile      // load B 64x64 tile from SPM
GemmScaleATile     // alpha-scale A operands
GemmHMMALTile      // device-level matmul template over A/B operand strips
GemmCStoreTile     // store C 64x64 tile
```

Dependencies for one C tile:

```text
C_init -> HMMAL(k0) -> HMMAL(k1) -> HMMAL(k2) -> HMMAL(k3) -> C_store
A_load/copy(k_i) -> HMMAL(k_i)
B_load(k_i)      -> HMMAL(k_i)
```

Fusion should attach after `GemmHMMALTile` or before `GemmCStoreTile`, depending
on whether it consumes the C tile in operand/accumulator form or after
materialization.
