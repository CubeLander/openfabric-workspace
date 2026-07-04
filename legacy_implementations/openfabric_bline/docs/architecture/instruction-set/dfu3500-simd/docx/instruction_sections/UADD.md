# UADD

- docx_family: unsigned_int_imm_mode

- docx_typed_view: imm==0: 128 lanes x 32 bits; imm==1: 512 lanes x 8 bits

## Extracted Text

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Operand index 0和Operand index 1的128/512个SIMD分量相加，每个分量32bit/8bit，结果存入Operand index 2

Value(Operand index 2) = Value(Operand index 0) + Value(Operand index 1)；

Assembly Code：

[image: image22.png]
