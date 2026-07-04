# FXP2FP

- docx_family: special

## Extracted Text

imm的4bit只能有一个bit为1，只能从4个RX中选择1个赋值给目的寄存器

Source operand：

Operand index 0

Destination  operand：

Operand index 2

Function：

根据imm[3:0] 字段imm[3:0]=[RX3toSrc, RX2toSrc, RX1toSrc, RX0toSrc] ，是将RX寄存器内容，传入源寄存器

，判断如何进行类型转换

Value(Operand index 2) = float(Value(Operand index 0))  simd32->simd32

Assembly Code：

[image: image39.png]
