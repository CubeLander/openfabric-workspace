# ULTS

- docx_family: unsigned_int_imm_mode

- docx_typed_view: imm==0: uint32[128]; imm==1: uint8[512]

## Extracted Text

结束当前的app，执行下一次app

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：PE阵列停止指令，如果结果是1，那么在PE阵列上运行的程序停止，只要有一个分量结果是1，就停止。

Value(Operand index 2) = Value(Operand index 0) < Value(Operand index 1)? 1:0

Assembly Code：

[image: image24.png]

特殊指令
