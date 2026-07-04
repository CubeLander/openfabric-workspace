# EQ

- docx_family: signed_int_imm_mode

- docx_typed_view: imm==0: signed int32[128]; imm==1: signed int8[512]

## Extracted Text

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = Value(Operand index 0) == Value(Operand index 1)? 1:0

Assembly Code：

[image: image21.png]

Unsigned Int32 /unsigned Int8指令

根据汇编指令中，imm数值判断是uint8 还是uint32

imm==0 ,uint32 ; imm==1,uint8;
