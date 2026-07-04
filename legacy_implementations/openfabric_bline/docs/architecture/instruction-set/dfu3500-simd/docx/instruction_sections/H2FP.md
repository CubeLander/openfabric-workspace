# H2FP

- docx_family: special

## Extracted Text

Source operand：

Operand index 0

Destination  operand：

Operand index 2

Function：

根据imm 字段，判断哪半部分进行类型转换

imm==0: Value(Operand index 2) = float(Value(Operand index 0)(31:0))  simd64->simd32

imm>0: Value(Operand index 2) = float (Value(Operand index 0)(63:32))  simd64->simd32

Assembly Code：

[image: image41.png]
