# GEMM Operand Strip And Memory Access Model

This note records the extra lowering layer between a logical GEMM tile and the
PE load/compute/store sequence. It answers a practical compiler question:

```text
Can the compiler assume that the data touched by one load operation maps to a
simple contiguous region of A/B/C memory?
```

The short answer is:

```text
CSV-level HLDT/HSTT pseudo instruction:
  no, it maps to a regular rectangular strip with row stride.

Lower 1024-bit unit load/store after pseudo expansion:
  yes, it should correspond to one contiguous row segment.
```

For v1, model this as:

```text
64x64 hardware tile
  -> 16 operand strips
  -> many HMMAL tensor ticks selected by operand index + immediate fragment bits
```

## Evidence From Legacy GEMM

The source generator uses:

```text
tmp  = 16
type = 16
```

and comments that 16 registers can hold one 64x64 matrix. For fp16 SIMD128,
one logical operand is:

```text
4096 bits = 512 bytes = 256 fp16 elements
```

So one 64x64 fp16 tile contains:

```text
64 * 64 = 4096 fp16 elements
4096 / 256 = 16 logical operands
```

The legacy templates load C/A/B with loops over `i = 0..15`.

For C load/store:

```c
HLDT/HSTT offset =
  taskAddr_per_pe_C[pe_id][unroll_i]
  + i * (4 * strideB * 16 / 32)
```

For A load:

```c
HLDT offset =
  taskAddr_per_pe_A[pe_id][task]
  + i * (4 * strideA * 16 / 32)
```

For B load:

```c
HLDT offset =
  taskAddr_per_pe_B[pe_id][task]
  + i * (4 * strideB * 16 / 32)
```

The factor `4 * stride * 16 / 32` is:

```text
4 rows * stride elements * sizeof(fp16) / sizeof(uint32 word)
```

So each operand strip advances by 4 matrix rows.

## Operand Strip Shape

For row-major fp16 matrix storage, one operand strip is best understood as:

```text
4 rows x 64 columns = 256 fp16 elements = 512 bytes
```

For a C tile:

```text
C_strip(i):
  rows = tile_m + 4*i .. tile_m + 4*i + 3
  cols = tile_n .. tile_n + 63
```

For an A tile in K block `k_block`:

```text
A_strip(j):
  rows = tile_m + 4*j .. tile_m + 4*j + 3
  cols = k_block .. k_block + 63
```

For a B tile:

```text
B_strip(i):
  rows = k_block + 4*i .. k_block + 4*i + 3
  cols = tile_n .. tile_n + 63
```

Each row segment inside the strip is contiguous. The whole CSV-level 4x64 strip
is a flat contiguous interval only when the matrix row stride equals 64. In the
current example:

```text
A stride = 256
B stride = 512
C stride = 512
```

so the strip is a regular strided rectangle, not a single flat contiguous
memory interval.

This is still compiler-friendly: a strip is described by:

```text
base
row_count = 4
col_count = 64
row_stride
dtype = fp16
```

The existing CSV-level `HLDT/HSTT` pseudo instruction appears to encode the row
stride in its immediate field and the starting offset in the address field.
4096-bit pseudo instructions are expanded into four 1024-bit lower
instructions:

```text
one CSV HLDT/HSTT
  -> four lower 1024-bit unit loads/stores
  -> each unit touches one contiguous 64-fp16 row segment
  -> the four units together form one 4x64 strided operand strip
```

Treat `OperandStrip` as the CSV/template-level LD/ST unit, while remembering
that its lower physical memory transactions are likely contiguous row segments.

## HMMAL Granularity

After A and B strips are loaded, the template emits many HMMAL instructions.
The source uses nested loops over A and B strip indices and encodes fragment
selection in the immediate:

```text
HMMAL(A_strip_j, B_strip_i, imm_fragment_selector)
```

The generator groups the 16 A strips and 16 B strips into front/back halves:

```text
A[0..7]  x B[0..7]
A[0..7]  x B[8..15]
A[8..15] x B[0..7]
A[8..15] x B[8..15]
```

Within those groups, immediate bits select tensor fragments. The HMMAL row has
no explicit C destination operand in the CSV; the result flows through the
tensor/RX internal accumulator and is later materialized with TRCTT.

For v1 IR, use these layers:

```text
GemmTile64:
  logical 64x64x64 GEMM update.

OperandStrip:
  4x64 fp16 rectangular strip loaded into one logical operand.

TensorTick:
  one HMMAL instruction using A_strip, B_strip, and imm fragment selector.
```

The compiler can generate tile-level schedules first, then lower each 64x64x64
update into the fixed strip/tensor-tick template.

## Implications For The Compiler

The tile DAG should not expose every HMMAL instruction as a high-level dataflow
node. That would make the scheduler too low-level too early.

Recommended layering:

```text
PE logical action:
  local_matmul(C_tile, A_tile, B_tile)

tile scheduler:
  schedules 64x64 C tiles and K blocks.

operand-strip lowering:
  expands one tile update into HLDT/COPYT/HMMAL/TRCTT/HSTT template pieces.

instruction emitter:
  assigns operand names, operand indices, immediate fragment selectors, and
  base_addr_idx/offset fields.
```

Contiguity rule for v1:

```text
Require A/B/C tiles to be row-major rectangular regions with constant row
stride. Do not require a whole CSV-level 4x64 operand strip to be one flat
contiguous interval. Do require each lower row segment in the strip to be
contiguous.
```

This is enough for the current GEMM templates and keeps the compiler model
compatible with padded/dummy edge tiles.
