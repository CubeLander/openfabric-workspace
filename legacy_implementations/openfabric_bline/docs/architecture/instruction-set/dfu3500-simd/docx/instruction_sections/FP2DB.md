# FP2DB

- docx_family: special

## Extracted Text

每1024bit单独做自己的

Source operand：

Operand index 0

Destination  operand：

Operand index 2

Function：

根据imm 字段，判断哪半部分进行类型转换

imm==0:

Value(Operand index 2)=double(Value(Operand index 0) (15:0)(47:32)(79:64)(96:111))

imm>0:

Value(Operand index 2)=double(Value(Operand index 0)(31:16)(63:48)(95:80)(127:112))

Assembly Code：

[image: image37.png]
