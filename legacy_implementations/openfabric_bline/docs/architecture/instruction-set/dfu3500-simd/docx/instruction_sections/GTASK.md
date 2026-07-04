# GTASK

- docx_family: special

## Extracted Text

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

[image: image32.png]

把当前的task编号赋值给寄存器

Value(Operand index 2)  = task_num

Assembly Code：

[image: image33.png]

Logic Inst

根据汇编指令中，imm数值判断是integer 8bit 还是integer 32

imm==0 ,integer 32bit ; imm==1,integer 8bit;
