# HSIS

- docx_family: half

## Extracted Text

Source operand：

Operand index 0，

Destination  operand：

Operand index 2

Function：超越函数，根据imm值，选择指令功能

imm[7:0] |  | 
8'b00000001 | 1/a | Value(Operand index 2)  = 1/(Value(Operand index 0))
8'b00000010 | sqrt(a) | Value(Operand index 2)  = Sqrt(Value(Operand index 0))
8'b00000100 | 1/sqrt(a) | Value(Operand index 2)  = 1/Sqrt(Value(Operand index 0))
8'b00001000 | sin(a) | Value(Operand index 2)  = sin(Value(Operand index 0))
8'b00010000 | cos(a) | Value(Operand index 2)  = cos(Value(Operand index 0))
8'b00100000 | log2(a) | Value(Operand index 2)  = LOG2(Value(Operand index 0))
8'b01000000 | 2^a | Value(Operand index 2)  = EXP2(Value(Operand index 0))

Assembly Code：

[image: image10.png]

float 指令
