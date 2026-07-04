# FADD

- docx_family: float

- docx_typed_view: 128 lanes x 32 bits = 4096 bits

## Extracted Text

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Operand index 0和Operand index 1的128个SIMD分量相加，每个分量32bit，结果存入Operand index 2

Value(Operand index 2) (127:0)= Value(Operand index 0) (127：0) + Value(Operand index 1) (127:0)；

Assembly Code：

[image: image11.png]
