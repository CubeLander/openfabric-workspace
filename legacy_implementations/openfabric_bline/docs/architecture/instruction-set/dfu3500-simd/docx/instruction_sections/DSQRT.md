# DSQRT

- docx_family: double

## Extracted Text

Source operand：

Operand index 0，

Destination  operand：

Operand index 2

Function：

Value(Operand index 2)  = Sqrt(Value(Operand index 0))

Assembly Code：

[image: image18.png]

Int32 /Int8指令

根据汇编指令中，imm数值判断是int8 还是int32

imm==0 ,int32 ; imm==1,int8;
