# RXOUT

- docx_family: half

## Extracted Text

Source operand：NULL

Destination  operand：Operand index 2

Function：

把用于int8计算的RX[0-3]值取回到目的寄存器里：

imm=0: RX0 => src2     imm=1: RX1 => src2

imm=2: RX2 => src2     imm=3: RX3 => src2

(LRX不适用)

Assembly Code：

[image: image52.png]

COPYT指令

Source operand：

Operand index 0

Destination  operand：

Operand index 2

Function：

将源PE上的寄存器内容，拷贝到目的PE上的寄存器，目的寄存器编号在dst_pe_idx；

Assembly Code：

[image: image53.png]

访存指令

DFU访存指令地址= imm + instance_baseaddr(iteration field)，例如下面的指令：

[image: image54.png]

HLDT

对齐方式：（32*4 ）Bytes对齐 4*（regbase+imm）

Assembly Code：

[image: image55.png]

[image: image56.png]

[image: image57.png]

[image: image58.png]

[image: image59.png]

[image: image60.png]

ILDMT

对齐方式：4Bytes对齐

Assembly Code：

带extra_field

[image: image61.png]

不带extra_field，默认其它域为0：

[image: image62.png]

[image: image63.png]

[image: image64.png]

[image: image65.png]

[image: image66.png]

[image: image67.png]

[image: image68.png]

SLDSHIF

对齐方式：128Bytes对齐

Assembly Code：

[image: image69.png]

[image: image70.png]
