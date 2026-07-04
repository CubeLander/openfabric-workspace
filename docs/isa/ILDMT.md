# ILDMT ISA Notes

This note records the current OpenFabric working model for DFU3500/GPDPU
`ILDMT`.  It is grounded in the active SimICT assembler source and the latest
vendor ISA OCR fragment supplied during customer debugging.  Treat it as a
cross-checked working model, not yet as a complete hardware proof.

## Status

`ILDMT` is a CSV/template pseudo instruction.  The active vendor assembler
lowers it to physical `LDM` rows:

```text
ILDMT -> LDM x 4
```

This is different from `HLDT`:

```text
HLDT -> LDN x 4
```

So an `ILDMT` source row is not just a smaller spelling of `HLDT`.  It reaches
the `OP_LDM` packing path, where several low bits of `dst_pe_idx` and
`extra_fields` change RTL fields.

## Sources

Primary active-source evidence:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/csv_oper.cpp
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/task_print.cpp
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/task_print.md
simict3500final/gpdpu/users/risc_nn_riscv/common/src/inst_def.h
simict3500final/gpdpu/users/risc_nn_riscv/common/src/inst_def.md
```

Latest OCR fragment supplied by the customer-debugging loop:

```text
simd_mode[0] is represented by dst_pe_idx[0]
simd_mode[1] is represented by extra_fields[0][0]
8bit/16bit offset uses extra_fields[1][1:0]

simd_mode[1:0] = 0  multiple 32 x 32bits
simd_mode[1:0] = 1  multiple 16 x 64bits
simd_mode[1:0] = 2  multiple 64 x 16bits
simd_mode[1:0] = 3  multiple 128 x 8bits
```

## Source-Level Lowering

The active pseudo-expansion table maps:

```text
OP_ILDMT -> "LDM"
```

For `ILDMT`, the first physical row masks the CSV `dst_pe_idx` down to its low
bit before emitting the physical `LDM` row:

```text
physical_dst_pe_x = raw_dst_pe_idx & 0x1
```

The appended rows use the same physical `dst_pe_x`, but their `imm` advances
from the raw CSV `dst_pe_idx`:

```text
expanded_imm[k] = imm + k * (raw_dst_pe_idx + 1) * 32
```

That means the same CSV field has two roles:

```text
raw dst_pe_idx bit0 -> LDM simd_mode bit0
raw dst_pe_idx full value -> pseudo-expansion memory stride
```

This is why `ILDMT` is especially easy to misuse.  It does not have one clean
"target PE" meaning.

## RTL Field Packing

The active `task_print.cpp` code packs physical `OP_LDM` like this:

```text
ldst_inst.simd_mode =
  (dst_pes_pos[0].x & 0x1) |
  ((extra_fields[0] & 0x1) << 1)

ldst_inst.mask_enable   = extra_fields[1] & 0x1
ldst_inst.end_inst_flag = (extra_fields[1] >> 1) & 0x1
```

So the active source confirms the OCR statement for `simd_mode`:

```text
simd_mode[0] = dst_pe_idx[0]
simd_mode[1] = extra_fields[0][0]
```

The active source does not confirm the OCR wording that
`extra_fields[1][1:0]` is an 8bit/16bit offset for `OP_LDM`.  In the active
source, those two bits are named and packed as:

```text
extra_fields[1][0] -> mask_enable
extra_fields[1][1] -> end_inst_flag
```

`inst_t_ldst_for_rtl` does contain an `int8_offset` bit next to `simd_mode`, but
the active `OP_LDM` path leaves `int8_offset` at zero.  This discrepancy may be
a real OCR/document-page mismatch, a field-name mismatch, or a version skew
between documentation and source.  Do not build new lowering rules from the
`extra_fields[1]` offset claim until a runtime probe confirms it.

## SIMD Modes

The current combined source/OCR model is:

```text
simd_mode = (dst_pe_idx & 1) | ((extra_fields[0] & 1) << 1)
```

| simd_mode | OCR mode              |
|-----------|-----------------------|
| 0         | multiple 32 x 32bits  |
| 1         | multiple 16 x 64bits  |
| 2         | multiple 64 x 16bits  |
| 3         | multiple 128 x 8bits  |

For fp32 data, mode 0 is the only mode whose bit shape explicitly says
`32bits`.  That does not prove it broadcasts one fp32 scalar over a full logical
operand.  It more likely describes a 1024-bit physical `LDM` element layout.

## OpenFabric Risk

Current generated OpenFabric CSV calls `emit_ildmt()` without extra fields:

```text
ILDMT,...,dst_pe_idx=reg_offset,imm=imm_offset,iteration=base_selector
```

With no trailing extra CSV columns, the parser defaults:

```text
extra_fields[0] = 0
extra_fields[1] = 0
```

Most current scalar-looking loads therefore become:

```text
simd_mode = reg_offset & 1
mask_enable = 0
end_inst_flag = 0
```

For the active `log10max_refactored` case, scalar summary values such as
`global_clip_floor` and `local_log10_max_pe_*` are loaded with `reg_offset = 0`,
so they become:

```text
simd_mode = 0
```

The dangerous assumption is that this acts like:

```text
load one fp32 scalar and broadcast it to all fp32 lanes
```

The active source does not prove that assumption.  The OCR mode name
`multiple 32 x 32bits` suggests the physical operation may only materialize
32 fp32 values per 1024-bit slice, or materialize a repeated 32-lane pattern, not
a full logical 128-lane fp32 scalar broadcast.

## Probe Needed

The current runtime probe package makes `ILDMT/LDM` observable directly:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/ildmt_probe
build/customer_delivery/ildmt_probe.tar.gz
```

After unpacking on the customer machine:

```sh
cd ildmt_probe
./run.sh
```

The package builds with the customer SimICT assembler/runtime by default:

```text
/project/home-new/huake02/simict3500final
```

The probe does this:

```text
1. Put distinct fp32 values in SPM blocks selected by several (imm, dst_pe_idx)
   pairs.
2. Run ILDMT with simd_mode 0, 1, 2, 3 by varying dst_pe_idx bit0 and
   extra_fields[0] bit0.
3. Store the loaded operand back with HSTT or another trusted store path.
4. Compare raw uint32/fp32 output blocks against two candidate models:
   block-copy and first-word broadcast.
```

This should answer:

```text
Does mode 0 load 32 fp32 lanes, broadcast one fp32 scalar, or fill a full
logical operand group?

Does raw dst_pe_idx affect only simd_mode bit0 after expansion, or does its full
value still select strided SPM blocks through the appended imm rows?

Does extra_fields[1] really act as mask/end flags in this source version, or
does hardware reinterpret it as an 8/16-bit offset?
```

## Runtime Observation

The customer-side runtime probe has now run on `huake02@arch-13`.  The important
aggregate result was:

```text
total_vector_mismatch=14224
total_broadcast_mismatch=12288
best_model=closer_to_broadcast_first_word
```

This does not match a contiguous fp32 block-copy model.  It also is not a clean
full-operand scalar broadcast.  The per-case counts reveal the more useful
shape:

```text
mode0 raw_dst=0 extra0=0 simd_mode=0:
  vector_mismatch=127
  broadcast_mismatch=96
  first output words = first fp32 word repeated

mode1 raw_dst=1 extra0=0 simd_mode=1:
  vector_mismatch=126
  broadcast_mismatch=112
  first output words = first 64-bit pair repeated as fp32 words

mode2/mode3:
  tie_or_unknown, often zero or halfword/byte-shaped garbage when viewed as fp32
```

Interpreting the checker:

```text
vector_mismatch=127
```

means only one word out of the 128 words covered by the `ILDMT -> LDM x4` /
`HSTT -> STD x4` round trip matched the contiguous vector-copy expectation.

```text
broadcast_mismatch=96
```

means only the first 32-word physical slice matched a first-word broadcast
expectation.  The remaining three 32-word slices did not advance to the later
input blocks as a 4096-bit vector-copy model would predict.

So the current runtime evidence supports this working model:

```text
ILDMT/LDM is a physical grouped load whose simd_mode selects element-group
width, not a full 4096-bit fp32 vector load and not a reliable full-operand
fp32 scalar broadcast.
```

More concretely, for the tested fp32 input pattern:

```text
simd_mode=0:
  one 32-bit SPM word is replicated across a 32-word / 128-byte physical slice

simd_mode=1:
  one 64-bit SPM pair is replicated across a 16-pair / 128-byte physical slice

simd_mode=2:
  one 16-bit lane group is replicated; interpreting the result as fp32 produces
  halfword-pattern values such as 0x80008000, 0xc000c000, or 0x40004000

simd_mode=3:
  one 8-bit lane group is replicated; the current fp32-view probe mostly saw
  zero-like output
```

The `ILDMT` pseudo row still expands to four physical `LDM` rows in the image,
but this probe's round trip shows that those rows do not compose into a normal
four-slice fp32 vector load for a single operand symbol.  In the tested pattern,
the first physical slice explains the observable fp32 output, while the later
expected strided blocks do not appear as vector lanes in the `HSTT` output.

For OpenFabric lowering this is the practical rule:

```text
Do not use ILDMT/load_operand for fp32 vector windows or fp32 values that must
be visible across all 128 logical lanes unless a dedicated lowering/probe has
proved the intended grouped behavior.
```

Use `HLDT/LDN` for block-shaped operand materialization when the producer stored
the operand with `HSTT/STD`.  Keep `ILDMT/LDM` for the vendor summary/partial
patterns that are known to expect its grouped physical behavior, such as the
handwritten softmax summary path.
