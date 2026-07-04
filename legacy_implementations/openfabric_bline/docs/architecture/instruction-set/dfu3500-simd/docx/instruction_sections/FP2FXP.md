# FP2FXP

- docx_family: special

## Extracted Text

imm是全1的时候，只有RX0被赋值

Source operand：

Operand index 0

Destination  operand：

Operand index 2

Function：

根据imm[4:0] 字段，imm[4:0]=[四舍五入/舍弃尾数，toRX3, toRX2, toRX1, toRX0] ，判断如何进行类型转换

Value(Operand index 2) = int(Value(Operand index 0))  simd32->simd32

Assembly Code：

[image: image40.png]
