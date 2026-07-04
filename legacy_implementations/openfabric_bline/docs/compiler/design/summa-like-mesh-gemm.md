# SUMMA-like Mesh GEMM Schedule

This note records the default GEMM backend direction for the GPDPU compiler.
It is intentionally separate from the legacy GEMM notes because this is not just
an observation from the vendor example. It is a general scheduling idea for
reusing data on a 4x4 PE mesh.

## Core Idea

For a DTensor-style output-sharded GEMM:

```text
A: [M, K] placements = [Shard(0), Replicate()]
B: [K, N] placements = [Replicate(), Shard(1)]
C: [M, N] placements = [Shard(0), Shard(1)]
mesh = 4 x 4
```

logical ownership is:

```text
PE(i,j) owns C_ij

A_i = A rows owned by mesh row i
B_j = B columns owned by mesh column j
C_ij = A_i @ B_j
```

For the current example:

```text
M = 512
K = 256
N = 512
PE(i,j) owns C[i*128:(i+1)*128, j*128:(j+1)*128]
A_i shape = 128 x 256
B_j shape = 256 x 128
C_ij shape = 128 x 128
```

The key sharing pattern is:

```text
All PEs in mesh row i need the same A_i.
All PEs in mesh column j need the same B_j.
```

So the natural mesh communication skeleton is:

```text
A_i: broadcast along mesh row i
B_j: broadcast along mesh column j
PE(i,j): local accumulate into C_ij
```

This is a SUMMA-like schedule specialized to the 4x4 PE mesh.

## Homogeneous Stages

The compiler should avoid thinking in terms of "write 16 unrelated PE programs".
Instead, it should find homogeneous stages:

```text
stage t:
  each PE(i,j) receives the A/B fragments required for this stage
  each PE(i,j) runs the same local microprogram shape
  each PE(i,j) accumulates into its local C tile
```

Only parameters vary:

```text
pe_coord
tile_coord
k_block
base_addr
stride
stage_id
```

This suggests a backend target:

```text
one PE kernel template
+ per-PE/per-stage parameterization
```

## Streaming K Blocks

The PE does not need to hold the full local logical inputs:

```text
A_i = 128 x 256
B_j = 256 x 128
```

at once. The scheduler can stream the reduction dimension:

```text
for k_block in K blocks:
  make A_i[:, k_block] available along mesh row i
  make B_j[k_block, :] available along mesh column j
  update local C tiles that depend on this k_block
```

For the current example:

```text
local C per PE = 128 x 128
hardware C tile = 64 x 64
K block = 64
```

So each PE can decompose:

```text
local C 128x128
  -> 2 x 2 C hardware tiles
  -> 4 K stages per C tile
```

One possible loop order is C-tile first:

```text
for m_tile in local M tiles:
  for n_tile in local N tiles:
    init C[m_tile, n_tile]
    for k_block in K blocks:
      receive/reuse A[m_tile, k_block]
      receive/reuse B[k_block, n_tile]
      accumulate C[m_tile, n_tile]
    store C[m_tile, n_tile]
```

Another possible loop order is K-stage first:

```text
for k_block in K blocks:
  row-broadcast A fragments for this k_block
  column-broadcast B fragments for this k_block
  update all local C tiles that depend on those fragments
```

The K-stage-first order may reduce repeated A/B movement because one incoming
A/B fragment can update multiple C tiles before being evicted, subject to
operand and accumulator capacity.

For the first implementation, use a regular SUMMA-style streaming schedule as
the production rule:

```text
for each k_block:
  all PEs execute the same stage shape
  mesh rows receive/broadcast their A fragments
  mesh columns receive/broadcast their B fragments
  every PE runs the same local compute template
```

The priority is homogeneous PE behavior, not global scheduler optimality. This
regular schedule is already a low-live-window special case: shared A/B fragments
are brought in, consumed by the participating row/column PEs, and then released
in a short window. It also matches the DFU task/subtask/instance model better
than an irregular greedy schedule.

If matrix shapes are not exact multiples of the chosen tile shape, the backend
should pad the internal tile grid with dummy regions:

```text
padded_M = ceil_div(M, tile_M) * tile_M
padded_N = ceil_div(N, tile_N) * tile_N
padded_K = ceil_div(K, tile_K) * tile_K
```

Dummy tiles participate in the same homogeneous schedule. Dummy A/B tiles should
map to pre-zeroed padding tile regions, and stores must only write the real
output region. Padding is an internal lowering detail; it must not change the
operator ABI or visible tensor shape.

The more general tile live-window scheduler remains the future optimization
direction:

```text
docs/compiler/design/tile-live-window-scheduler.md
```

## V1 Task/Subtask/Instance Slicing

The regular SUMMA schedule gives each PE a stable internal tile sequence. For
the first backend, lower that sequence into DFU runtime stages as follows:

```text
launch group = up to MAX_TASKS regular C hardware-tile waves
task         = one regular C hardware-tile wave inside the launch group

subtask1:
  initialize the current C tile accumulator.
  Usually this means load C and multiply by beta, or zero-init for beta=0.

subtask2:
  stream K blocks with the hardware instance loop.
  Each instance uses the same PE instruction template and a different instance
  base-address table entry.

subtask3:
  store the completed C tile to the visible output region.

subtask4:
  optional post-op/fusion stage when the fused op can be expressed after GEMM.
```

For the current 512x256 by 256x512 example:

```text
mesh = 4 x 4
per-PE logical C shard = 128 x 128
hardware C tile = 64 x 64
K block = 64
K block count = 4
```

Each PE's logical shard splits into:

```text
2 x 2 C hardware tiles = 4 C waves
```

The v1 mapping can therefore use:

```text
task0..task3:
  each task handles one C hardware-tile wave for every PE in launch group 0.

each task:
  subtask1 Instance Times = 1
  subtask2 Instance Times = K block count
  subtask3 Instance Times = 1
```

For this example, `subtask2 Instance Times = 4`.

If a larger GEMM creates more than 4 C waves per PE, V1 should emit multiple
launch groups / dataset slices rather than pretending one runtime launch can
hold more than `MAX_TASK_AMOUNT` tasks.

This mirrors the vendor GEMM structure while keeping our logical ownership more
regular. The `task` boundary handles C-tile waves, `subtask` handles runtime
visible lifecycle phases, and `instance` handles repeated K streaming with
different base addresses.

Slicing priority:

```text
1. Use instance loop for repeated K-block work whenever the instruction template
   is identical and only base addresses change.
2. Use subtask boundaries for load/init, compute-stream, store, and optional
   fusion barriers.
3. Use more task slices only when the C tile waves or resource limits no longer
   fit in one task's subtask/instance structure.
```

The task scheduler still works at 64x64 tile granularity. Actual PE instruction
emission has one more lowering layer:

```text
64x64 tile -> 16 operand strips -> HMMAL tensor ticks
```

See:

```text
docs/architecture/gemm-case-study/gemm-operand-strip-memory-model.md
```

## Why This Is More General Than Legacy

The vendor GEMM example uses a legacy physical schedule:

```text
one task: 2 M-tiles x 8 N-tiles mapped onto 16 PE jobs
four tasks advance M
A is copied horizontally
B is loaded by compute PEs
```

That schedule is a useful baseline. However, the SUMMA-like schedule keeps a
cleaner distributed tensor ownership:

```text
PE(i,j) owns one stable C_ij block
A is row-shared
B is column-shared
```

This is more composable for fusion and easier to generalize across operators.
The backend can still choose a legacy-like physical schedule later if the
measured mesh/SPM cost model prefers it.

## Compiler Skeleton

This GEMM schedule is one instance of a broader compiler skeleton:

```text
partition tensors
-> derive the dependency frontier for the next stage
-> stream the minimal required tiles
-> distribute tiles across row/column/mesh collectives
-> run homogeneous PE-local microprograms
-> accumulate/store outputs
```

For GEMM, the dependency frontier is:

```text
A[:, k_block] and B[k_block, :]
```

For other operators, similar patterns should exist:

```text
elementwise:
  local map, no cross-PE dependency unless layout changes.

softmax:
  local max/sum, axis collective reduce, normalize.

layernorm:
  local sum/sumsq, axis collective reduce, affine.

attention:
  Q block with streaming K/V blocks and online softmax state.

transpose:
  tile shuffle / layout transform.
```

## Design Principle

The compiler core should be an SPM-aware dataflow compiler:

```text
DFU compiler core = tensor layout + streaming frontier + mesh collective + local compute.
```

The important job is to find stage-level minimal data dependencies, then emit
homogeneous PE-local work wherever possible. This should make the implementation
more reusable than per-PE hand-written schedules while still leaving enough room
for hardware-aware tile and operand scheduling.
