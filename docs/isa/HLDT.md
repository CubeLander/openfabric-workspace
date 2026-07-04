# HLDT ISA Notes

This note records the current OpenFabric working model for DFU3500/GPDPU
`HLDT`.  It is grounded in the active SimICT assembler source, the vendor ISA
OCR notes, and current remote-test discussion.  Treat it as a checked lowering
model, not yet as a complete hardware proof.

## Status

`HLDT` is a CSV/template pseudo instruction.  The active vendor assembler lowers
it to four physical `LDN` rows in normal mode:

```text
HLDT -> LDN x 4
```

The four physical rows read four 1024-bit chunks from SPM into one logical
operand group.  Each 1024-bit chunk is one 128-byte SPM block.

## Sources

Primary evidence:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/csv_oper.cpp
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/task_print.cpp
simict3500final/gpdpu/users/risc_nn_riscv/common/src/pe_com_def.h
legacy_implementations/openfabric_bline/docs/architecture/instruction-set/dfu3500-simd/docx/instruction_sections/RXOUT.md
legacy_implementations/openfabric_bline/docs/architecture/instruction-set/dfu3500-simd/docx/media_ocr/raw/image56.txt
legacy_implementations/openfabric_bline/docs/architecture/instruction-set/dfu3500-simd/docx/media_ocr/raw/image58.txt
```

The archived B-line documents are evidence only.  The active implementation
path remains the runnable SimICT vendor tree under `simict3500final`.

## Address Model

Vendor documentation says `imm` is a 4-byte address offset and the final memory
address is aligned to `32 * 4` bytes:

```text
byte_addr = 4 * (base_addr[iteration] + expanded_imm)
```

In normal mode, one CSV `HLDT` expands to four physical `LDN` instructions:

```text
for k in 0..3:
  expanded_imm[k] = imm + k * (dst_pe_idx + 1) * 32
```

Equivalently, in 128-byte SPM block numbers:

```text
block[k] = imm / 32 + k * (dst_pe_idx + 1)
```

This assumes `imm` is 128-byte aligned, i.e. divisible by 32.  Current generated
operator CSVs use that aligned form for `HLDT`.

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

So `dst_pe_idx` acts as a block-stride selector for the four physical memory
chunks.  It is not simply a target PE number in the final address path.

## Source-Level Lowering

The active assembler uses one shared pseudo expansion path for tensor-style
load/store pseudo instructions:

```text
HLDT / ILDT -> LDN
HSTT / ISTT -> STD
```

For `HLDT`, the first physical row keeps the original `imm`.  Three follow rows
are appended with:

```text
stride = (dst_pe_idx + 1) * 32
follow_imm = imm + k * stride
```

After this expansion, `task_print.cpp` writes the physical LD/ST instruction
with:

```text
base_addr_idx = iteration
imm           = expanded_imm
```

The original `dst_pe_idx` has already affected the `expanded_imm` sequence.

## Special Case

Vendor examples mention `dst_pe_idx = -1`.  This appears to be a special mode,
possibly a single-block or nonstandard expansion form.  Do not lower ordinary
contiguous or strided tensor loads through `-1` until it has been verified with
a runtime probe.

For now, OpenFabric should only treat non-negative `dst_pe_idx` values as covered
by the block-stride formula above.
