# Tensor Type Conversion Source Audit

Date: 2026-06-20

Status: original-materials audit card

This note anchors the RXINT/TRCTT type-conversion facts needed before OpenFabric
attempts runnable log10 / fp16-fp32 conversion payloads.  These instructions are
binary-critical because they allocate tensor tmp resources and encode conversion
modes into immediates.

## Source Materials

Original material:

```text
tmp/华科算子库编写/8、类型转换指令.docx
tmp/华科算子库编写/（这个文档先不看）DFU3500-tensor指令集.xlsx
tmp/华科算子库编写/（这个文档先不看）DFU3500-tensor指令集.docx
```

Extracted OpenFabric references:

```text
docs/architecture/instruction-set/dfu3500-tensor/README.md
docs/architecture/instruction-set/dfu3500-tensor/xlsx/Sheet1.md
docs/architecture/instruction-set/dfu3500-tensor/docx/dfu3500-tensor-instruction-doc.md
```

## RXINT Contract

RXINT moves operand memory into tensor tmp state and may convert dtype.

Source operand:

```text
Operand index 0
```

Immediate fields:

```text
imm[4:0] = tmp register number / clear selector
imm[7:5] = conversion mode
```

The extracted tensor table gives these modes:

```text
0: int8  -> int32
1: fp8   -> fp16
2: fp8   -> fp32
3: fp16  -> fp32
4: fp32  -> fp32
5: uint8 -> uint32
6: int32 -> int32
```

Important resource rule:

```text
widening modes consume grouped tmp resources.
```

Examples from the extracted material:

```text
int8 -> int32 uses 4 x 4096-bit tmp storage
fp16 -> fp32 uses 2 x 4096-bit tmp storage
fp32 -> fp32 uses one 4096-bit tmp per tmp register
```

## TRCTT Contract

TRCTT moves tensor tmp state back to operand memory and may convert dtype.

Destination operand:

```text
Operand index 2
```

Immediate fields:

```text
imm[3:0] = tmp register number
imm[6:4] = conversion mode
```

The extracted tensor table gives these modes:

```text
0: int32 -> int8
1: fp16  -> fp8
2: fp32  -> fp8
3: fp32  -> fp16
4: fp32  -> fp32
5: int32 -> int32
```

The original type-conversion document says TRCTT generally appears paired with
RXINT.  Treat RXINT/TRCTT as a tmp-state lifetime pair unless a specific template
proves otherwise.

## Compiler Implications

A B-line tensor/template path needs:

```text
TensorTmpResourcePlan:
  tmp register id
  tmp group width
  dtype conversion mode
  lifetime from RXINT to TRCTT/HMMAL consumer

TemplateOpPlan:
  symbolic RXINT/TRCTT operations with explicit conversion kind

InstructionLayoutPlan:
  immediate packing for RXINT imm[4:0]/imm[7:5]
  immediate packing for TRCTT imm[3:0]/imm[6:4]
```

Do not treat RXINT/TRCTT as normal SIMD local compute.  They cross into tensor
tmp state and require resource tracking.

## Relation To Log10 / Elementwise Probes

The first OpenFabric functional maximum probe avoided this path.  That was good:
it tested SIMD local compute without tensor tmp conversion.

Before a runnable `log10(clamp(...))` path claims fp16 input/fp32 internal/fp16
output support, it must answer:

```text
1. Is conversion handled by SIMD H2FP/FP2H or tensor RXINT/TRCTT?
2. Which operand/tensor tmp resource owns the widened values?
3. Which immediate mode is emitted?
4. Which runtime tolerance is expected?
```

If these answers are missing, the payload can be a structural probe, not a
functional runtime target.

## Current Status

```text
Extracted:
  RXINT/TRCTT immediate fields and conversion modes are already extracted.

Absorbed:
  This note and dfu3500-tensor/README.md summarize the contract.

Operationalized:
  Not yet.  B-line needs TensorTmpResourcePlan and conversion-template checks.

Runtime-proven:
  Not by OpenFabric.  Vendor GEMM uses RXINT/HMMAL/TRCTT-style tensor flow, but
  OpenFabric has not yet isolated a conversion-only functional probe.
```
