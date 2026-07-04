# log10max Numeric Failure Notes

Status: hot customer-runtime diagnosis, not a fix.

## 2026-07-02 current checkpoint

This section supersedes the older early-suspicion notes below where they conflict
with the latest ISA reading.

### Algorithm meaning

The complete log10max signal-processing fragment is not "return only the max".
It is the ASR mel dynamic-range normalization pattern:

```text
log_spec = log10(clamp(mel_spec, min=1e-10))
global_max = max(log_spec)
threshold = global_max - 8.0
out = maximum(log_spec, threshold)
out = (out + 4.0) / 4.0
```

In words: the operator first converts the input signal into log-magnitude
space, then clips the log signal to an 8-decade window relative to the global
maximum log value, then applies the affine `(x + 4) / 4` post-scale.  The
`max()` is the global threshold source; the output is still an elementwise tensor
with the same shape as the input, not a scalar max result.

The active refactored C++ test data uses this deterministic input:

```text
slow_ramp = ((index % 4096) + 1) / 4096.0
row_bias = (index / 512) * 0.0007
input[index] = slow_ramp + row_bias + 1.0e-4
```

With the active `64 x 512` fp32 case, this produces:

```text
global_max ~= 0.0187836889
threshold  ~= -7.98121631
out[0]     ~= 0.134183986
out[1]     ~= 0.192396252
out[2]     ~= 0.230085871
out[-1]    ~= 1.00469592
```

This matches the customer checker's expected values:

```text
index=1 expected=0.192396224 actual=0.134183943
index=2 expected=0.230085850 actual=0.134183943
```

So the reference/checker formula is consistent with the intended signal
algorithm.  The suspicious part is that runtime `actual` repeats `out[0]`, which
points back to load/store/tile/operand coverage instead of a wrong
"log10max means max-only" interpretation.

Evidence:

```text
legacy_implementations/openfabric_bline/compiler/torch_examples/log10_maximum_dtensor.py
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/log10max_refactored/operator_sources/log10max/case_plan.json
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/log10max_refactored/operator_sources/log10max/device_program/main.cpp
```

`simict3500final/.../application/log10_test` is only an OCR-recovered `FLOG2`
smoke case:

```text
HLDT vec
FLOG2 vec -> vec
HSTT vec
```

It is useful for instruction smoke evidence, but it is not the full log10max
algorithm.

### HLDT/HSTT address-shape model

We now understand the non-negative `dst_pe_idx` rule better.  One CSV
`HLDT/HSTT` pseudo instruction expands to four physical `LDN/STD` rows.  In
128-byte SPM block units:

```text
block[k] = imm / 32 + k * (dst_pe_idx + 1)
```

Examples:

```text
(imm, dst_pe_idx) = (0, 0)  -> blocks 0, 1, 2, 3
(imm, dst_pe_idx) = (0, 1)  -> blocks 0, 2, 4, 6
(imm, dst_pe_idx) = (32, 1) -> blocks 1, 3, 5, 7
(imm, dst_pe_idx) = (0, 3)  -> blocks 0, 4, 8, 12
```

This applies to both `HLDT` and `HSTT`; direction is the only difference:

```text
HLDT: selected SPM blocks -> logical operand group
HSTT: logical operand group -> selected SPM blocks
```

The special `dst_pe_idx = -1` case is still not covered by this formula.  It may
mean a single-block or special expanded form and needs a runtime probe before
OpenFabric should generate it for new code.

The durable ISA notes are now:

```text
docs/isa/HLDT.md
docs/isa/HSTT.md
```

### What this says about the repeated-output failure

The new `HLDT/HSTT` model does not suggest changing log10max's current
`dst_pe_idx=0, imm += 128` pattern.  For fp32 contiguous tiles, that pattern
covers contiguous 512-byte logical operand windows:

```text
HLDT imm=0   -> blocks 0, 1, 2, 3
HLDT imm=128 -> blocks 4, 5, 6, 7
```

So the current generated CSV shape is plausible for contiguous fp32 tile windows.

The stronger current suspect is operand-group mapping after pseudo expansion.
The active `csv_oper.cpp` expands `HLDT/HSTT` addresses into four physical
`LDN/STD` rows, but the active `Task_Resource::fill_reg_idx()` path appears to
assign the same operand index to repeated follow rows with the same register tag.
For a true 4096-bit logical operand group, the four physical 1024-bit rows should
land in four operand RAM slices, likely:

```text
operand[k] = base_operand + k * OPERANDS_PER_OPERAND_RAM
```

There is explicit follow-row operand adjustment for `COPYT` in
`inst_blk_map.cpp`, but an equivalent adjustment for `HLDT/HSTT` has not yet been
confirmed in the active source.

This failure mode matches the customer symptom where most output elements are
equal or look like the first expected value:

```text
index=1 expected=0.192396224 actual=0.134183943
index=2 expected=0.230085850 actual=0.134183943
```

If the four memory chunks are loaded from different SPM blocks but repeatedly
bound to the same operand slice, later chunks can overwrite earlier chunks or
stores can write the same slice to multiple SPM blocks.

Additional static check on the generated log10max CSV confirms the shape of this
risk.  With the active constants:

```text
OPERANDS_RAM_NUM = 12
OPERANDS_PER_OPERAND_RAM = 128
```

the first CSV row:

```text
HLDT ... of_t0_mel_spec_f32_0, dst_pe_idx=0, imm=0
```

is expanded by the active `csv_oper.cpp` into:

```text
LDN imm=0
LDN imm=32
LDN imm=64
LDN imm=96
```

but the active `fill_reg_idx()` style tag binding gives all four rows the same
`dst_operands_idx0 = 0`.  If `HLDT` is a true 4096-bit logical operand
materialization, the likely grouped operand shape is:

```text
LDN imm=0   dst=0
LDN imm=32  dst=128
LDN imm=64  dst=256
LDN imm=96  dst=384
```

This `base + lane * OPERANDS_PER_OPERAND_RAM` rule is already used for `COPYT`
follow rows in the active `inst_blk_map.cpp`, and older arch-13 notes also list
the same rule for pseudo-tensor instruction follow rows.  This is not yet a
runtime-proven fix: one older B-line note claimed non-COPYT pseudo destinations
do not advance, so the next evidence should be either the customer ISA/manual
for `HLDT/HSTT -> LDN/STD` operand indices or a small runtime load/store probe.

### Current next steps

Updated ILDMT/LDM evidence now makes scalar-looking summary loads a higher
priority suspect than plain `HLDT/HSTT` round-trip storage.  The active source
confirms:

```text
ILDMT -> LDM x 4
LDM simd_mode = (dst_pe_idx & 1) | ((extra_fields[0] & 1) << 1)
```

The latest vendor OCR fragment gives the mode names:

```text
0: multiple 32 x 32bits
1: multiple 16 x 64bits
2: multiple 64 x 16bits
3: multiple 128 x 8bits
```

Our current `emit_ildmt()` writes no `extra_fields`, so log10max's fp32 summary
loads use `simd_mode=0`.  That is only proven to be a `multiple 32 x 32bits`
physical `LDM` mode; it is not proven to be "load one fp32 scalar and broadcast
to a full 128-lane fp32 logical operand".  This is now a plausible explanation
for the repeated-value output pattern: the global/local scalar used by later
`FMAX` operations may not be represented in the lane shape assumed by the
OpenFabric abstraction.

Durable note:

```text
docs/isa/ILDMT.md
```

1. Confirm the exact active vendor behavior for `HLDT/HSTT` follow-row operand
   indices.  Look for, or add, the same kind of operand-slice adjustment that
   `COPYT` gets.

2. Build a minimal load/store probe that writes distinct fp32 patterns through:

   ```text
   HLDT/HSTT with dst_pe_idx = 0, 1, 3
   HSTT of known constants
   ILDMT/LDM scalar-style loads
   ```

   The checker should dump raw uint32 and fp32 values by output block so the
   memory shape and operand group shape are visible.

   A first multi-PE `HLDT -> HSTT` probe package now exists:

   ```text
   simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/hldt_hstt_probe
   build/customer_delivery/hldt_hstt_probe.tar.gz
   ```

   It generates one task/subtask over all 16 PE templates.  Each PE runs four
   load/store pairs:

   ```text
   dst_pe_idx = 0, base_block = pe * 64 + 0
   dst_pe_idx = 1, base_block = pe * 64 + 16
   dst_pe_idx = 3, base_block = pe * 64 + 32
   dst_pe_idx = 1, base_block = pe * 64 + 49
   ```

   Input and reference output use unique fp32 values per PE/case/copy/lane, so a
   wrong block selection, operand-slice reuse, or broadcast-like load/store
   behavior should show up as a structured checker mismatch.  The package
   intentionally compiles the small RISC-V `testarm.c` harness on the customer
   machine, then builds the images with the customer `common_oper/build_app`
   toolchain before running the runtime.

   Customer runtime result:

   ```text
   mismatch_count = 0
   ```

   This strongly lowers the probability that plain `HLDT -> HSTT` block
   selection, non-negative `dst_pe_idx`, or customer-toolchain pseudo expansion
   is the root cause of the log10max broadcast-like output.  The next suspect
   should move downstream/upstream of this pure round-trip path: arithmetic over
   fp32 operands, `ILDMT/LDM` summary loads, staged `LOG10_STAGE` interaction
   with later subtasks, or the RISC-V/runtime/checker offset path.

3. Keep algorithm semantics separate from storage semantics.  The expected
   output should be the dynamic-range formula above.  A globally constant output
   is not expected unless the input/reference is intentionally degenerate.

The customer-side run now completes the simulator but fails numeric checking:

```text
runtime_rc=0
check_status=FAIL
mismatch_count=32736 / 32768
first mismatches:
  index=1 expected=0.192396224 actual=0.134183943
  index=2 expected=0.230085850 actual=0.134183943
```

`0.134183943` is not random.  It is the expected value for element 0.  The
current symptom therefore looks like a coverage/layout/broadcast failure rather
than a pure checker offset failure.

## Instruction-set evidence checked

Legacy customer instruction-set notes say:

```text
SIMD128 logical operand = 4096 bits = 512 bytes = 4 x 1024-bit chunks
unit_t = 1024 bits = 128 bytes
```

The same instruction cards describe:

```text
FLOG2: fp32[128], dst[i] = log2(src[i])
FMAX:  fp32[128], dst[i] = max(src0[i], src1[i])
FMUL:  fp32[128], dst[i] = src0[i] * src1[i]
```

So this is not explained by `FLOG2` or `FMAX` being scalar instructions.  If a
full fp32 SIMD128 logical operand is correctly loaded, these ops should act
lane-wise over 128 fp32 lanes.

`SHFL` remains relevant to the earlier simulator crash at `SHFL18`, but the
current numeric pattern appears before any final correctness decision that
depends only on the allreduce result.  A wrong global max or clip floor would
shift/clamp values; it would not naturally make elements 1..N equal element 0.

## Stronger local suspects

### 1. Address unit mismatch for fp32 tensors

`common_app_builder/dtensor_plan.h` defines the vendor SPM base-address unit as:

```c++
spm_vendor_base_addr_unit_bytes() == sizeof(float)
```

But multiple active helpers still compute offsets with
`vendor_base_addr_units_for_fp16_element_count()`:

```text
vendor_memory.h:
  tile_addr(...)
  tile_lane_addr(...)

spm_placement.h:
  stage_base_row_vendor_addr_for_statement(...)
```

That was compatible with fp16-oriented softmax/GEMM paths, but `log10max` is
declared and checked as fp32.  For fp32 tensors, these helpers halve row and
instance offsets.  This can make generated CSV and instance base rows address a
different layout than the checker's contiguous fp32 reference window.

### 2. Earlier hypothesis: template covers too little fp32 data per PE

The generated `log10max` app config currently has one instance per subtask:

```text
subtask1 Instance Times : 1
subtask2 Instance Times : 1
subtask3 Instance Times : 1
```

For a `64 x 512` fp32 tensor on 16 PEs, each PE owns 4 rows, or 2048 fp32
elements.  The current per-PE subtask1/subtask3 CSV only loads/stores two
logical `HLDT/HSTT` operands:

```csv
HLDT ... imm=0
HLDT ... imm=128
...
HSTT ... imm=0
HSTT ... imm=128
```

Given the legacy lane model, two fp32 SIMD128 operands cover 256 fp32 elements,
not 2048.  That is an 8x coverage gap.  This matches the shape of the failure
better than a single opcode semantics bug.

### 3. Earlier hypothesis: `ILDMT` is more suspicious than arithmetic opcodes

After widening to 16 fp32 windows, one customer run still repeated the first
lane-like value:

```csv
index=1 expected=0.192396224 actual=0.134183943
```

The stronger instruction-set evidence was not the student-authored `log10_test`
CSV style.  The legacy DFU3500 SIMD instruction materials and latest OCR point
toward this shape:

```text
FLOG2/FMAX/FMUL/FADD/FSUB are fp32[128] lane-wise over one 4096-bit operand.
LDM(1024bit): Value(Operand index 2) = 32{SPM(LD Base Reg X + IMM)}
ILDMT(4096bit) expands to LDM-family rows.
HLDT(4096bit) expands to LDN-family rows and is the aligned block-load family.
```

So one plausible semantic bug is that OpenFabric used `ILDMT` as if it were a
full-lane fp32 scalar/vector load without proving the `LDM` lane shape.  For
fp32 values that must be visible across all 128 logical lanes, `ILDMT/LDM` may be
the wrong abstraction unless its `simd_mode` behavior is explicitly selected and
runtime-proven.  This is compatible with the runtime pattern where many output
lanes equal the first expected value, but it still needs the dedicated
`ILDMT/LDM` probe described above.

Keep the arithmetic final-column question open, but do not lead with it.  The
instruction cards prove the arithmetic op lane semantics; the load family choice
better explains the observed broadcast-like output.

## Minimal next experiment

On the customer machine, inspect whether the expected contiguous fp32 sequence
exists elsewhere in `gpdpu_data`.  If it exists at a regular stride/offset, the
checker/layout is wrong.  If it does not, the generated template is computing or
storing the wrong values.

```sh
cd ~/log10max
python3 - <<'PY'
import struct

g = 'run/log10max_runtime/gpdpu_data'
r = 'runtime_support/reference_output_data.bin'
off = 524288

data = open(g, 'rb').read()
ref = open(r, 'rb').read()

actual = struct.unpack('<64f', data[off:off + 64 * 4])
expect = struct.unpack('<64f', ref[:64 * 4])

print('gpdpu size', len(data))
print('actual first64')
for i, (a, e) in enumerate(zip(actual, expect)):
    print(i, 'actual=', a, 'expect=', e, 'diff=', a - e)

print('search expected first16 in output region')
for i, e in enumerate(expect[:16]):
    b = struct.pack('<f', e)
    pos = data.find(b, off, min(len(data), off + 1024 * 1024))
    print(i, 'first_pos=', pos, 'relative_float=', (pos - off) // 4 if pos >= 0 else None)
PY
```

Local conclusion for now: prioritize fp32 layout/address-unit and per-PE coverage
before further SHFL/FLOG2 opcode hunting.

## Repair direction constraints

Do not fix this by globally changing all address helpers from fp16-style element
counts to fp32-style element counts.  That would likely break the existing GEMM
and softmax refactored paths, which were built around half/H256 data movement
and already use the current helper behavior as part of their assembler-input
contract.

Safer direction:

1. Add an explicit tensor element type or element-byte count to `DTensor`.
   Existing GEMM/softmax declarations should default to fp16 to preserve their
   current generated assembler inputs.  `log10max` input, output, and fp32
   scratch tensors should opt into fp32.

2. Replace ambiguous helpers such as `tile_addr`, `tile_lane_addr`, and
   `stage_base_row_vendor_addr_for_statement` with dtype-aware equivalents.
   The conversion rule should be:

   ```text
   vendor_addr_units = element_count * tensor.element_bytes / spm_vendor_base_addr_unit_bytes()
   ```

   Keep old fp16-named wrappers temporarily for GEMM/softmax parity, but route
   new code through typed helpers.

3. Separate logical tile width from operand/register carrier type.  A
   `FiberH256Tile` with two chunks is not a sound representation of a whole
   fp32 `64x512 / 16PE` tile.  For fp32, the lowering must explicitly account
   for `fp32[128]` SIMD operands and the number of operands needed per PE tile.

   Tile representation and tile operations must also be type-aware.  A tile is
   not just:

   ```text
   shape + row ownership + chunk count
   ```

   It also needs at least:

   ```text
   logical dtype / element bytes
   target SIMD mode and lane dtype
   lanes per logical operand
   bytes per logical operand
   operand carrier family (H256, F32, tensor-core accumulator, summary scalar)
   memory offset unit conversion
   number of operand windows needed to cover the tile
   ```

   Short-term implementation can be explicit and boring: add small typed
   descriptors/fields and helper functions such as `F32TileWindow`,
   `H256TileWindow`, or `TileOperandWindow{dtype, carrier, lane_count,
   window_index}`.  The important part is that callers cannot accidentally pass
   a half/H256 tile where the body expects fp32 SIMD128 coverage.

   Longer-term, this probably wants a tile-template or typed tile-family layer:

   ```text
   Tile<fp16, H256Carrier, 256 lanes>
   Tile<fp32, F32Simd128Carrier, 128 lanes>
   Tile<accumulator, TensorCoreCarrier, vendor-specific lanes>
   Tile<summary, ScalarOrVectorSummaryCarrier, reduction slots>
   ```

   That template layer should not be introduced all at once while the customer
   handoff is hot.  The migration path should first make the current concrete
   cases explicit and checkable, then collapse duplicated typed rules into a
   reusable tile-family abstraction once GEMM, softmax, and log10max all have
   evidence-backed contracts.

4. Make instance coverage a derived invariant, not a hand-written assumption.
   For log10max, each PE owns `4 x 512 = 2048` fp32 elements.  At 128 fp32 lanes
   per SIMD128 operand, each PE needs 16 logical fp32 operand windows across its
   tile, not two.  That can be represented either by more generated rows per
   single instance or by more instances with correct base rows, but the chosen
   route must be reflected in `app*.conf`, instance base rows, and CSV offsets.

5. Preserve old assembler-input parity by adding a comparison target before the
   typed-helper migration.  The useful contract is not local assembler output
   correctness; it is that GEMM/softmax generated assembler inputs and package
   surfaces stay equivalent to their pre-migration content.  Mark any known
   assembler/runtime caveat separately.

6. Add a layout/coverage audit to package generation.  It should fail before
   packaging if:

   ```text
   covered_elements_per_pe != tile_elements_per_pe
   CSV memory offsets disagree with tensor dtype/vendor-unit conversion
   app instance count cannot cover planned statement windows
   checker dtype/shape/offset disagrees with the generated plan
   tile carrier dtype disagrees with tensor dtype or op lane dtype
   ```

Implementation order should be: first introduce typed metadata with fp16
defaults and prove GEMM/softmax unchanged; then switch log10max to fp32 typed
addressing; then fix log10max per-PE coverage/instance shape; finally revisit
SHFL/FLOG2 row details only if numeric output still has a reduction-specific
failure.

## Runtime ILDMT probe result

The customer-side `ildmt_probe` run completed and showed that `ILDMT/LDM` does
not behave like the fp32 vector/broadcast operation log10max was implicitly
assuming.

Key aggregate result:

```text
total_vector_mismatch=14224
total_broadcast_mismatch=12288
best_model=closer_to_broadcast_first_word
```

Important per-case shape:

```text
simd_mode=0 raw_dst=0 extra0=0:
  vector_mismatch=127
  broadcast_mismatch=96
  first words: first fp32 word repeated

simd_mode=1 raw_dst=1 extra0=0:
  vector_mismatch=126
  broadcast_mismatch=112
  first words: first 64-bit pair repeated
```

The mismatch counts mean the observed value is not a contiguous 128-fp32 vector
load.  It is also not a clean 128-lane scalar broadcast.  It is a physical
grouped `LDM` behavior where `simd_mode` selects the element-group width and the
first physical slice dominates the round-trip observation.

The stronger inferred behavior is:

```text
mode0: replicate one 32-bit word across a 32-word / 128-byte physical slice
mode1: replicate one 64-bit pair across a 16-pair / 128-byte physical slice
mode2: replicate 16-bit groups; fp32 view becomes halfword-pattern garbage
mode3: replicate 8-bit groups; fp32 view mostly observed as zero-like data
```

The arithmetic is visible in the mismatch counts.  For mode0, if one 32-bit word
is repeated through the first 32-word slice, the vector-copy model only matches
lane 0 (`127` mismatches), while the first-word broadcast model matches exactly
that first 32-word slice and misses the other three slices (`96` mismatches).
For mode1, the repeated first 64-bit pair gives two vector matches (`126`
mismatches) and sixteen first-word matches in the first slice (`112`
mismatches).

This changes the log10max repair priority:

1. `HLDT/HSTT` block round-trip remains trusted by the earlier `hldt_hstt_probe`.
2. Log10max fp32 input windows and staged `LOG10_STAGE` windows should continue
   using the `HLDT/LDN` block path.
3. Log10max summary readback must not use `ILDMT/LDM` when the value is expected
   to be a full fp32 operand visible to later lane-wise arithmetic.

Current code action:

```text
planned_global_clip_floor: load_operand      -> load_operand_block
local_max table readback:  load_operand      -> load_operand_block
```

In other words, local/global max values are stored with `HSTT`, then read back
with `HLDT`, keeping the same block-shaped operand family.  `ILDMT/LDM` remains
reserved for vendor paths that intentionally rely on its grouped physical
semantics, such as the handwritten softmax summary pattern.
