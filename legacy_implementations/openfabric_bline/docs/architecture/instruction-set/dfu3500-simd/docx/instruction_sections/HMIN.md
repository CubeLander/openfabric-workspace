# HMIN

- docx_family: half

- docx_typed_view: 256 lanes x 16 bits = 4096 bits

## Extracted Text

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Operand index 0和Operand index 1的256个SIMD分量比较大小，结果存入Operand index 2

Value(Operand index 2) (255:0)= min (Value(Operand index 0) (255:0) , Value(Operand index 1)) (255:0)

Assembly Code：

[image: image5.png]
