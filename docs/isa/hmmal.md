# HMMAL ISA Notes

This note records the current OpenFabric understanding of DFU3500/GPDPU
`HMMAL`.  It is grounded in the active SimICT GEMM vendor case and in archived
DFU3500 tensor instruction notes.  The goal is to make the instruction model
usable for bottom-up operator lowering without confusing vendor loop variables
with hardware semantics.

## Status

The HMMAL operating model is now understood well enough for GEMM refactoring:

```text
RXINT   imports an operand strip into tensor tmp state
HMMAL   updates one selected tensor tmp from A/B operand strips
TRCTT   exports tensor tmp state back to an operand strip
```

For dense GEMM, the logical fragment coordinate table is understood:
`data_select_type` selects one 4-wide K fragment inside the selected A half,
and the corresponding B operand register carries the matching 4-row K fragment.
The remaining unknown is lower-level physical ordering inside the tensor unit,
such as exact lane/scalar wiring within that logical fragment.

## Sources

Primary evidence:

```text
legacy_implementations/openfabric_bline/docs/architecture/instruction-set/dfu3500-tensor/README.md
legacy_implementations/openfabric_bline/docs/architecture/instruction-set/dfu3500-tensor/xlsx/Sheet1.md
legacy_implementations/openfabric_bline/docs/architecture/instruction-set/dfu3500-tensor/docx/dfu3500-tensor-instruction-doc.md
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/task*/subtask2/template/new_temp.c
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_refactored/operator_sources/gemm/device_program/main.cpp
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_refactored/operator_sources/gemm/device_program/gemm_template_program.h
```

The archived B-line documents are evidence only.  The active implementation
path remains the runnable SimICT vendor case under `simict3500final`.

## Instruction Shape

The useful lowering interface is:

```text
HMMAL(src0_reg, src1_reg, dst_tmp, data_select_type, a_half, b_half)
```

Field roles:

```text
src0_reg          ordinary operand/register strip carrying Matrix A data
src1_reg          ordinary operand/register strip carrying Matrix B data
dst_tmp           tensor tmp accumulator selected by imm[9:7]
data_select_type  tensor-unit compute/data-selection mode selected by imm[6:4]
a_half            lower or upper 2048-bit half inside the 4096-bit A operand
b_half            lower or upper 2048-bit half inside the 4096-bit B operand
```

`src0_reg` and `src1_reg` are normal operand/register names.  `dst_tmp` is not a
normal destination register; it selects tensor tmp state inside the tensor unit.

## Immediate Layout

For dense HMMAL, the immediate is:

```text
imm = (dst_tmp << 7)
    | (data_select_type << 4)
    | (b_half << 3)
    | (a_half << 2)
    | base_mode
```

Field meaning:

```text
imm[1:0]  base matrix mode
  0       hmma.64
  1       hmma.sparse

imm[2]    Matrix A half selector
  0       Matrix A[2047:0]
  1       Matrix A[4095:2048]

imm[3]    Matrix B half selector
  0       Matrix B[2047:0]
  1       Matrix B[4095:2048]

imm[6:4]  data_select_type0..7
imm[9:7]  dst tmp0..tmp7
```

The common dense GEMM path uses `base_mode = 0`.

## Register Half vs Matrix Half

Do not collapse these two concepts even when their values are both lower/upper:

```text
register half       selects ordinary operand/register slots 0..7 or 8..15
tensor matrix half  selects Matrix A/B[2047:0] or Matrix A/B[4095:2048]
```

The refactored GEMM device program represents them separately:

```text
GemmRegisterHalf
GemmTensorMatrixHalf
```

This distinction prevents a common misread of vendor code: operand register
indexing and HMMAL half selection are different hardware decisions.

## Data Select Type

`data_select_type` is the HMMAL compute mode.  It selects how the tensor unit
pairs internal fragments or scalar groups inside the already selected A/B
operand halves.

It is not:

```text
not a B lane
not an ordinary register index
not a tensor tmp selector
```

It is:

```text
a local compute/data-selection mode within one A/B half pair
```

For a fixed pair of A/B operand strips, one HMMAL row is only one tensor-unit
micro-op.  Dense matrix multiply needs a set of HMMAL rows with different
`data_select_type` values so that internal A and B fragments are paired across
the combinations required by matrix multiplication.

For GEMM, the logical mapping is:

```text
data_select_type = t

A fragment:
  rows = selected A operand strip rows
  cols = selected A half base + 4*t .. selected A half base + 4*t + 3

B fragment:
  rows = selected A half base + 4*t .. selected A half base + 4*t + 3
  cols = selected B half base .. selected B half base + 31

C/tmp fragment updated:
  rows = selected dst_tmp/output row group
  cols = selected B half base .. selected B half base + 31
```

where:

```text
selected A half base = 0  if a_half = lower
selected A half base = 32 if a_half = upper
selected B half base = 0  if b_half = lower
selected B half base = 32 if b_half = upper
```

So `data_select_type=t` selects the K slice
`[4*t, 4*t+3]` inside the selected A half.  `b_half` selects whether the HMMAL
micro-op updates the left or right 32 columns of the C/output strip.

The physical scalar/lane order inside the selected 4-wide K fragment and
32-wide N half is still a hardware-detail question.  The OpenFabric lowering
does not need to expose that order as long as it emits the vendor-compatible
HMMAL fields.

OpenFabric code should name this field `data_select_type` or `compute_mode`,
not `lane`.

## Operand Strip Coordinates

For row-major fp16 GEMM, one 4096-bit operand register stores:

```text
4096 bits = 256 fp16 elements = 4 rows x 64 columns
```

Within one 64x64x64 GEMM tile:

```text
A_reg[j]:
  A rows = tile_m + 4*j .. tile_m + 4*j + 3
  A cols = tile_k .. tile_k + 63

B_reg[i]:
  B rows = tile_k + 4*i .. tile_k + 4*i + 3
  B cols = tile_n .. tile_n + 63

C_reg[j]:
  C rows = tile_m + 4*j .. tile_m + 4*j + 3
  C cols = tile_n .. tile_n + 63
```

The HMMAL row:

```text
HMMAL(A_reg[j], B_reg[i], dst_tmp=j, data_select_type=t, a_half, b_half)
```

is valid for GEMM when `i` and `(a_half, t)` refer to the same K fragment:

```text
i = 8*a_half + t
```

That equation is the reason vendor loops often use the same local variable for
`B_reg[i]` and `data_select_type=t`.  It is not because B register selection
and compute mode are the same semantic object; it is because dense GEMM pairs
them by K-fragment coordinate.

The logical micro-op performed is:

```text
C[tile_m + 4*j : tile_m + 4*j + 3,
  tile_n + 32*b_half : tile_n + 32*b_half + 31]

  +=

A[tile_m + 4*j : tile_m + 4*j + 3,
  tile_k + 32*a_half + 4*t : tile_k + 32*a_half + 4*t + 3]

  x

B[tile_k + 32*a_half + 4*t : tile_k + 32*a_half + 4*t + 3,
  tile_n + 32*b_half : tile_n + 32*b_half + 31]
```

This formula is the practical fragment coordinate table for dense GEMM
lowering.

## GEMM Loop Interpretation

The vendor GEMM template uses variables named like ordinary loop indices, but
those indices carry distinct meanings.

In the active 64x64 dense GEMM tile:

```text
type  = effective K-fragment compute mode count, grouped by 4 elements
tmp   = effective M/output accumulator group count, grouped by 4 rows
group = 8 HMMAL modes/tmp destinations per operand half
```

Historical vendor boundary logic shows:

```text
type = ceil(effective_K / 4), capped at 16
tmp  = ceil(effective_M / 4), capped at 16
```

The current refactored GEMM case is a full tile, so:

```text
type = 16
tmp  = 16
group = 8
```

A full tile therefore expands into two halves in each direction:

```text
lower K half: data_select_type = 0..7, a_half/b_half selected separately
upper K half: data_select_type = 0..7, a_half/b_half selected separately

lower M accumulator half: dst_tmp = 0..7 using register slots 0..7
upper M accumulator half: dst_tmp = 0..7 using register slots 8..15
```

For a K-tail tile, `type` can be smaller:

```text
lower_k_modes = min(type, 8)
upper_k_modes = max(type - 8, 0)
```

This explains the vendor loops:

```text
for i in 0..newType-1:
  HMMAL(..., data_select_type=i, ...)

if type > 8:
  for i in 0..type-8-1:
    HMMAL(..., data_select_type=i, a_half=upper, ...)
```

The upper half still uses `data_select_type = 0..7`; the half selector moves the
operation to the upper 2048-bit Matrix A/B half.  `data_select_type` is local to
the selected half, not a global `0..15` mode field.

Similarly, for an M-tail tile:

```text
lower_m_accumulators = min(tmp, 8)
upper_m_accumulators = max(tmp - 8, 0)
```

The loop variable commonly named `j` selects the local tensor tmp destination
and the matching A/output register group.  This is why full GEMM has many rows
of the shape:

```text
HMMAL(A_reg[j], B_reg[i], dst_tmp=j, data_select_type=i, a_half, b_half)
```

The numeric equality between `B_reg[i]` and `data_select_type=i` in the vendor
template is a consequence of the dense GEMM coordinate rule `i = 8*a_half + t`.
The semantic objects are still different:

```text
B_reg[i]           ordinary operand/register strip selection
data_select_type   tensor-unit internal compute mode
```

## Dense GEMM Microprogram

For one tile-level dense GEMM update:

```text
C_tile = beta * C_tile + alpha * (A_tile x B_tile)
```

HMMAL appears inside the tile microprogram:

```text
1. load/import C accumulator groups with RXINT
2. issue HMMAL rows over A/B operand strips, matrix halves, and compute modes
3. export accumulator groups with TRCTT
```

The public tile-level operation should remain a GEMM tile update.  Individual
HMMAL rows are lowering details of that tile op, not separate high-level
OpenFabric fiberops.

Dense GEMM generally needs the full set of valid compute modes for each
relevant A/B half pair.  Other tensor operators may use only a subset if their
internal tensor microprogram does not require every fragment pairing.

## Related ISA Intuition

External tensor/matrix ISAs should not be treated as DFU3500 facts, but they are
useful design intuition.

NVIDIA PTX exposes matrix operations such as `wmma.mma` and `mma.sync` with
explicit matrix shapes and operand register groups.  The programmer selects the
matrix operation and operand fragments, while some execution details such as
accumulation order can remain unspecified in the ISA contract.  This is similar
in spirit to keeping HMMAL as a tensor micro-op over A/B operand fragments and
tensor tmp state, rather than forcing it into a scalar ALU model.

Intel AMX exposes 2D tile registers and TMUL instructions.  Software configures
tile dimensions, loads tiles with row stride, runs tile matrix multiply, and
stores tile data back.  Intel's public examples also show tail/remainder cases
handled by changing tile or stride parameters rather than inventing a different
scalar instruction stream.  This supports the same instinct for DFU3500 HMMAL:
model the tile/fragment contract first, then validate physical details by
experiment.

References:

```text
NVIDIA PTX ISA:
https://docs.nvidia.com/cuda/parallel-thread-execution/index.html

Intel AMX / TMUL overview and sample:
https://www.intel.com/content/www/us/en/developer/articles/code-sample/advanced-matrix-extensions-intrinsics-functions.html
https://www.intel.com/content/www/us/en/products/docs/accelerator-engines/what-is-intel-amx.html
```

## Simulator Probe Plan

The customer simulator can turn the remaining HMMAL details into checked facts.
The probe should be a minimal single-tile program that emits hand-controlled
HMMAL rows and inspects the final C/output matrix.

### Probe 1: data_select_type Coordinate Table

Goal:

```text
Confirm the exact output footprint of each data_select_type and half selector.
```

Method:

```text
for a_half in {lower, upper}
for b_half in {lower, upper}
for data_select_type in 0..7
for dst_tmp in a small selected set
  initialize C to zero
  initialize A with one nonzero marker in the expected 4-wide K fragment
  initialize B with one nonzero marker in the matching 4-row K fragment
  issue RXINT(C), one HMMAL, TRCTT(C)
  inspect which C elements changed
```

Expected dense-GEMM logical result:

```text
data_select_type=t touches K rows/cols:
  tile_k + 32*a_half + 4*t .. tile_k + 32*a_half + 4*t + 3

b_half selects output columns:
  tile_n + 32*b_half .. tile_n + 32*b_half + 31
```

Use different marker values for A and B so the changed C value identifies the
exact pair that multiplied.

### Probe 2: Physical Lane/Scalar Ordering

Goal:

```text
Recover the physical scalar order inside one logical HMMAL fragment.
```

Method:

```text
Set A fragment values to unique powers or small primes.
Set B fragment values to unique powers or small primes.
Run one HMMAL mode.
Decode each changed C element from the product/sum signature.
```

This should reveal whether the internal 4-wide K fragment is consumed in normal
row-major order, column-major order, lane-swizzled order, or another fixed
hardware order.

### Probe 3: dst_tmp And Accumulation Lifecycle

Goal:

```text
Confirm tensor tmp initialization, accumulation, and export behavior.
```

Cases:

```text
RXINT(C=0) -> HMMAL -> TRCTT
RXINT(C=pattern) -> HMMAL -> TRCTT
RXINT(C=0) -> HMMAL(mode0) -> HMMAL(mode1) -> TRCTT
HMMAL without RXINT -> TRCTT
RXINT(tmp0) plus HMMAL(dst_tmp=1) -> TRCTT(tmp0/tmp1)
```

Expected dense-GEMM behavior:

```text
RXINT seeds tmp with C.
HMMAL accumulates into selected dst_tmp.
TRCTT exports selected tmp back to C/output operand.
Different dst_tmp values are independent unless a conversion mode groups tmp
resources.
```

### Probe 4: Boundary Cropping

Goal:

```text
Check that irregular matrix tails are handled by issuing fewer modes/tmp rows,
not by hidden HMMAL masking.
```

Method:

```text
Run K-tail cases with type = 1, 2, 7, 8, 9, 15.
Run M-tail cases with tmp = 1, 2, 7, 8, 9, 15.
Compare against a scalar CPU reference using only the active logical rows/cols.
```

Expected:

```text
Only emitted data_select_type values contribute.
Only emitted dst_tmp/output row groups are exported.
Padding behavior should be treated as layout/toolchain responsibility unless
the simulator proves a hardware mask exists.
```

### Probe 5: Sparse And Conversion Modes

Goal:

```text
Separate dense HMMAL facts from sparse and conversion-mode facts.
```

Cases:

```text
imm[1:0] = 1 sparse HMMAL with controlled A/B patterns
RXINT/TRCTT conversion modes around HMMAL
tmp pressure cases where conversion modes may reserve grouped tmp resources
```

These should be run after dense GEMM probes pass, because sparse and conversion
behavior can otherwise obscure the basic HMMAL mapping.

## Naming Guidance

Preferred names in lowering code:

```text
k_fragment_count       instead of type
m_accumulator_count    instead of tmp
lower_k_modes
upper_k_modes
lower_m_accumulators
upper_m_accumulators
data_select_type or compute_mode
dst_tmp
a_half / b_half
```

Avoid names that imply false identity:

```text
input1_lane for data_select_type
lane_half for HMMAL matrix half
dst_reg for dst_tmp
```

## Current Confidence

High confidence:

```text
HMMAL is a tensor instruction, not ordinary SIMD arithmetic.
HMMAL writes tensor tmp state selected by imm[9:7].
RXINT/HMMAL/TRCTT form the accumulator lifecycle.
imm[6:4] is compute/data-selection mode, not an operand lane.
Dense GEMM logical fragment coordinates are described by the A/B/C formula
above.
type controls effective K-fragment compute modes and is boundary-cropped.
tmp controls effective M/output accumulator groups and is boundary-cropped.
```

Still open:

```text
Sparse HMMAL mode semantics for imm[1:0] = 1.
Physical lane/scalar order inside each selected logical fragment.
Detailed resource constraints between RXINT conversion groups and HMMAL tmp
usage outside the observed dense fp16 GEMM path.
```
