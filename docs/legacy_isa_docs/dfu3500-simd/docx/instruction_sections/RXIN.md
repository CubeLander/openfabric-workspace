# RXIN

- docx_family: half

## Extracted Text

Source operand：

Operand index 0

Destination  operand：NULL

Function：

RX  LRX 寄存器初始化操作

将opMem数值赋值到暂存器RX/LRX里:

1）RX0,RX1,RX2,RX3用于int8计算；

imm=0: RX0 <= src0     imm=1: RX1 <= src0

imm=2: RX2 <= src0     imm=3: RX3 <= src0

imm=12: 对RX0,RX1,RX2,RX3清零

2）LRX0，LRX1，LRX2，LRX3，LRX4，LRX5，LRX6，LRX7的(32bits)用于sldshif和sstshif指令间接寻址

imm=4: LRX0 <= src0  imm=5: LRX1 <= src0

imm=6: LRX2 <= src0  imm=7: LRX3 <= src0

imm=8: LRX4 <= src0  imm=9: LRX5 <= src0

imm=10: LRX6 <= src0 imm=11: LRX7 <= src0

Assembly Code：

[image: image51.png]
