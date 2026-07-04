# DFU3500 Tensor Instruction Notes

This directory records the tensor instruction material extracted from:

```text
tmp/华科算子库编写/（这个文档先不看）DFU3500-tensor指令集.xlsx
tmp/华科算子库编写/（这个文档先不看）DFU3500-tensor指令集.docx
```

The `.~...` files in the same source directory are Office temporary lock files
and should not be treated as real source documents.

Full Markdown extracts:

```text
xlsx/README.md
xlsx/Sheet1.md
xlsx/Sheet2.md
xlsx/Sheet3.md
docx/README.md
docx/dfu3500-tensor-instruction-doc.md
```


## Source Audit Cards

- [TYPE_CONVERSION_SOURCE_AUDIT.md](TYPE_CONVERSION_SOURCE_AUDIT.md): source-backed RXINT/TRCTT conversion modes, tmp resource implications, and compiler-owner requirements.

## Why This Matters

`HMMAL`, `HMMA`, `RXINT`, and `TRCTT` are tensor instructions, not SIMD
instructions. They are therefore absent from the SIMD instruction-set docs under
`docs/instruction-set/dfu3500-simd/`.

For GEMM lowering, this is the authoritative instruction family:

```text
RXINT   operand -> tensor tmp register
HMMAL   fp16 matrix multiply-accumulate, operand A/B -> tmp register
TRCTT   tensor tmp register -> operand
```

## Register / Tmp Model

The tensor instruction xlsx states:

```text
There are 16 tmp registers.
Each tmp register is 4096 bit.
```

`RXINT` imports a normal operand into tensor tmp state and can perform type
conversion. `TRCTT` exports tensor tmp state back to a normal operand and can
also perform type conversion.

## RXINT

Source operand:

```text
Operand index 0
```

Destination operand:

```text
blank / tensor tmp state
```

Immediate layout:

```text
imm[4:0]  tmp register number
  0..15   tmp0..tmp15
  16      clear

imm[7:5]  conversion mode
  0       int8  -> int32
  1       fp8   -> fp16
  2       fp8   -> fp32
  3       fp16  -> fp32
  4       fp32  -> fp32
  5       uint8 -> uint32
  6       int32 -> int32
```

The xlsx notes that widened modes occupy grouped tmp resources. For example,
`int8 -> int32` expands one 4096-bit int8 operand into `4 x 4096-bit` int32
tmp data and uses `tmp0..tmp3` as a group.

## TRCTT

Source operand:

```text
blank / tensor tmp state
```

Destination operand:

```text
Operand index 2
```

Immediate layout:

```text
imm[3:0]  tmp register number
  0..15   tmp0..tmp15

imm[6:4]  conversion mode
  0       int32 -> int8
  1       fp16  -> fp8
  2       fp32  -> fp8
  3       fp32  -> fp16
  4       fp32  -> fp32
  5       int32 -> int32
```

The docx says `TRCTT` generally appears in pairs with `RXINT`.

## HMMA

Source operands:

```text
Operand index 0, Operand index 1
```

Destination:

```text
tmp0..tmp7 selected by imm[9:7]
```

Function:

```text
fp16 * fp16 + fp32, result goes into tensor tmp state.
```

The docx states that in SIMD128 mode, one `HMMA` computes eight `4x4` matrix
multiplications.

Immediate layout:

```text
imm[1:0]  base matrix size
  0       hmma.4
  1       hmma.8
  2       hmma.16
  3       hmma.32

imm[2]    A half selector
  0       Matrix A[2047:0]
  1       Matrix A[4095:2048]

imm[3]    B half selector
  0       Matrix B[2047:0]
  1       Matrix B[4095:2048]

imm[6:4]  data_select_type0..7
imm[9:7]  dst tmp0..tmp7
```

## HMMAL

Source operands:

```text
Operand index 0, Operand index 1
```

Destination:

```text
tmp0..tmp7 selected by imm[9:7]
```

Function:

```text
fp16 64x64 matrix multiply, sparse mode supported.
```

Immediate layout:

```text
imm[1:0]  base matrix
  0       hmma.64
  1       hmma.sparse

imm[2]    A half selector
  0       Matrix A[2047:0]
  1       Matrix A[4095:2048]

imm[3]    B half selector
  0       Matrix B[2047:0]
  1       Matrix B[4095:2048]

imm[6:4]  data_select_type0..7
imm[9:7]  dst tmp0..tmp7
```

This matches the legacy GEMM template pattern:

```text
imm = (tmp_id << 7)
    | (data_select_type << 4)
    | (b_half << 3)
    | (a_half << 2)
    | base_mode
```

For the common dense `hmma.64` path, `base_mode = 0`.

The HMMAL docx images also show the legacy-style generated rows:

```text
HMMAL,HMMAL24,MATRIXA0,MATRIXB0,,,,0,0
HMMAL,HMMAL25,MATRIXA1,MATRIXB0,,,,128,0
HMMAL,HMMAL26,MATRIXA2,MATRIXB0,,,,256,0
...
HMMAL,HMMAL32,MATRIXA0,MATRIXB0,,,,8,0
HMMAL,HMMAL33,MATRIXA1,MATRIXB0,,,,136,0
```

These rows decode as:

```text
0    = tmp0, data_select_type0, B first half, A first half, hmma.64
128  = tmp1, data_select_type0, B first half, A first half, hmma.64
8    = tmp0, data_select_type0, B second half, A first half, hmma.64
136  = tmp1, data_select_type0, B second half, A first half, hmma.64
```

## Consequence For Compiler IR

For GEMM, `C_acc += HMMAL(A, B)` should now be understood as a tensor tmp update,
not a vague hidden accumulator:

```text
RXINT   C operand strip -> tmp group
HMMAL   A/B operand strips -> selected tmp0..tmp7
TRCTT   tmp group -> C operand strip
```

The lowerer must track:

- which tmp register or tmp group holds each partial result,
- which conversion mode is used by `RXINT/TRCTT`,
- the `HMMAL` base mode, half selectors, data select type, and tmp destination.
