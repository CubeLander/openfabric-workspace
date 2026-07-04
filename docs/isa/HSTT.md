# HSTT ISA Notes

This note records the current OpenFabric working model for DFU3500/GPDPU
`HSTT`.  It mirrors the `HLDT` address-shape model, but the data direction is
from a logical operand group back to SPM.

## Status

`HSTT` is a CSV/template pseudo instruction.  The active vendor assembler lowers
it to four physical `STD` rows in normal mode:

```text
HSTT -> STD x 4
```

The four physical rows write four 1024-bit chunks from one logical operand group
to SPM.  Each 1024-bit chunk is one 128-byte SPM block.

## Sources

Primary evidence:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/csv_oper.cpp
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/task_print.cpp
simict3500final/gpdpu/users/risc_nn_riscv/common/src/pe_com_def.h
legacy_implementations/openfabric_bline/docs/architecture/instruction-set/dfu3500-simd/docx/media_ocr/raw/image80.txt
legacy_implementations/openfabric_bline/docs/architecture/instruction-set/dfu3500-simd/docx/media_ocr/raw/image82.txt
```

The archived B-line documents are evidence only.  The active implementation
path remains the runnable SimICT vendor tree under `simict3500final`.

## Address Model

`HSTT` uses the same block-shape rule as `HLDT`.  In normal mode, one CSV `HSTT`
expands to four physical `STD` instructions:

```text
for k in 0..3:
  expanded_imm[k] = imm + k * (dst_pe_idx + 1) * 32
  byte_addr[k] = 4 * (base_addr[iteration] + expanded_imm[k])
```

Equivalently, in 128-byte SPM block numbers:

```text
block[k] = imm / 32 + k * (dst_pe_idx + 1)
```

This assumes `imm` is 128-byte aligned, i.e. divisible by 32.

## Examples

```text
(imm, dst_pe_idx) = (0, 0)
expanded_imm = 0, 32, 64, 96
blocks       = 0, 1, 2, 3

(imm, dst_pe_idx) = (0, 1)
expanded_imm = 0, 64, 128, 192
blocks       = 0, 2, 4, 6

(imm, dst_pe_idx) = (32, 1)
expanded_imm = 32, 96, 160, 224
blocks       = 1, 3, 5, 7

(imm, dst_pe_idx) = (0, 3)
expanded_imm = 0, 128, 256, 384
blocks       = 0, 4, 8, 12
```

So `dst_pe_idx` acts as the SPM block-stride selector for the four physical
store chunks.  `dst_pe_idx = 0` stores four contiguous 128-byte blocks;
`dst_pe_idx = 1` stores every other 128-byte block; `dst_pe_idx = 3` stores one
block every four 128-byte blocks.

## Direction Compared With HLDT

The address shape is shared:

```text
HLDT: SPM selected blocks -> operand group
HSTT: operand group -> SPM selected blocks
```

This shared behavior comes from the active assembler's common pseudo expansion
path:

```text
HLDT / ILDT -> LDN
HSTT / ISTT -> STD
```

After expansion, `task_print.cpp` writes each physical `STD` with:

```text
base_addr_idx = iteration
imm           = expanded_imm
```

The original `dst_pe_idx` has already affected the `expanded_imm` sequence.

## Special Case

Vendor examples mention `dst_pe_idx = -1`.  This appears to be a special mode,
possibly a single-block or nonstandard expansion form.  Do not lower ordinary
contiguous or strided tensor stores through `-1` until it has been verified with
a runtime probe.

For now, OpenFabric should only treat non-negative `dst_pe_idx` values as covered
by the block-stride formula above.
