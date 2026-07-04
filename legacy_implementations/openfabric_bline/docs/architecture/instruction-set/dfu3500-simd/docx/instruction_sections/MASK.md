# MASK

- docx_family: half

## Extracted Text

Source operand：

Operand index 0

Destination  operand：

Function：根据Operand Index0的值，给Mask寄存器赋值；

[image: image71.png]

[image: image72.png]

Assembly Code：

[image: image73.png]

详细信息如下：更正一下：ext offset：当选中32bit和64bit时，不用选择。选中8bit的时候，用0，1，2，3.选中16bit，用0和2

[image: image74.png]

[image: image76.png]

[image: image75.emf]

[image: image77.png]

HSTT

对齐方式：128Bytes对齐

Assembly Code：

带mask寄存器：

[image: image78.png]

不带mask寄存器：

[image: image79.png]

[image: image80.png]

[image: image81.png]

[image: image82.png]

[image: image83.png]

[image: image84.png]

[image: image85.png]

SSTSHIF

对齐方式：128Bytes对齐

[image: image86.png]

与SLDSHIF相同，加入了other段的mask信息；

SSTM（很少用到）

[image: image87.png]

索引粒度为8bit，写回最低K={dst_pe_idx[4:0]，dst_pe_idx[8:7]}个分量，或者最高128-K个分量。

dst_pe_idx[4:0]:

dst_pe_idx[6:5]: [hign,low]

dst_pe_idx[8:7]:

dst_pe_idx[10:9]:regidx索引，SIMD128模式对应选择4个regid中的一个，SIMD64，SIMD32按比例减少。

[high,low]为2'b01，根据regidx选择某个寄存器，写regidx寄存器内最高的128-K个分量，同时编号大于此寄存器的其它寄存器全部写回；

[high,low]为2'b10，根据regidx选择某个寄存器，写regidx寄存器内最低的128-K个分量，同时编号小于此寄存器的全部写回；

[high,low]为2'b00，表示所有分量全部写回;

K==0,所有分量全部写回；

[image: image88.png]

[image: image89.png]
