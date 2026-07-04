# DFU3500 SIMD 指令集文档

Half float 指令

HADD

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Operand index 0和Operand index 1的256个SIMD分量相加，每个分量16bit，结果存入Operand index 2

Value(Operand index 2) (255:0)= Value(Operand index 0) (255:0) + Value(Operand index 1) (255:0)；

Assembly Code：

![image1.png](media/image1.png)

HSUB

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Operand index 0和Operand index 1的256个SIMD分量相减，每个分量16bit，结果存入Operand index 2

Value(Operand index 2) (255:0)= Value(Operand index 0) (255:0) - Value(Operand index 1) (255:0)；

Assembly Code：

![image2.png](media/image2.png)

HMUL

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Operand index 0和Operand index 1的256个SIMD分量相乘，每个分量16bit，结果存入Operand index 2

Value(Operand index 2) (255:0)= Value(Operand index 0) (255:0) * Value(Operand index 1) (255:0)；

Assembly Code：

![image3.png](media/image3.png)

HMAX

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Operand index 0和Operand index 1的256个SIMD分量比较大小，结果存入Operand index 2

Value(Operand index 2) (255:0)= max(Value(Operand index 0) (255:0) , Value(Operand index 1)) (255:0)

Assembly Code：

![image4.png](media/image4.png)

HMIN

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Operand index 0和Operand index 1的256个SIMD分量比较大小，结果存入Operand index 2

Value(Operand index 2) (255:0)= min (Value(Operand index 0) (255:0) , Value(Operand index 1)) (255:0)

Assembly Code：

![image5.png](media/image5.png)

HMADD

Source operand：

Operand index 0，Operand index 1, Operand index 2

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (255:0) = Value(Operand index 0) (255:0) * Value(Operand index 1) (255:0) + Value(Operand index 2) (255:0)

Assembly Code：

![image6.png](media/image6.png)

HDIV

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (255:0)= Value(Operand index 0) (255:0)/ Value(Operand index 1) (255:0)

Assembly Code：

![image7.png](media/image7.png)

HLT:

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (255:0) = Value(Operand index 0) (255:0) < Value(Operand index 1) (255:0) ? 1:0

Assembly Code：

![image8.png](media/image8.png)

HGT

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (255:0)  = Value(Operand index 0) (255:0) > Value(Operand index 1) (255:0) ? 1:0

Assembly Code：

![image9.png](media/image9.png)

HSIS

Source operand：

Operand index 0，

Destination  operand：

Operand index 2

Function：超越函数，根据imm值，选择指令功能

| imm[7:0] |  |  |
| --- | --- | --- |
| 8'b00000001 | 1/a | Value(Operand index 2)  = 1/(Value(Operand index 0)) |
| 8'b00000010 | sqrt(a) | Value(Operand index 2)  = Sqrt(Value(Operand index 0)) |
| 8'b00000100 | 1/sqrt(a) | Value(Operand index 2)  = 1/Sqrt(Value(Operand index 0)) |
| 8'b00001000 | sin(a) | Value(Operand index 2)  = sin(Value(Operand index 0)) |
| 8'b00010000 | cos(a) | Value(Operand index 2)  = cos(Value(Operand index 0)) |
| 8'b00100000 | log2(a) | Value(Operand index 2)  = LOG2(Value(Operand index 0)) |
| 8'b01000000 | 2^a | Value(Operand index 2)  = EXP2(Value(Operand index 0)) |

Assembly Code：

![image10.png](media/image10.png)

float 指令

FADD

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Operand index 0和Operand index 1的128个SIMD分量相加，每个分量32bit，结果存入Operand index 2

Value(Operand index 2) (127:0)= Value(Operand index 0) (127：0) + Value(Operand index 1) (127:0)；

Assembly Code：

![image11.png](media/image11.png)

FSUB

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (127:0)= Value(Operand index 0) (127:0) - Value(Operand index 1) (127:0)；

Assembly Code：

![image11.png](media/image11.png)

FMUL

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (127:0)= Value(Operand index 0) (127:0) * Value(Operand index 1) (127:0)；

Assembly Code：

![image11.png](media/image11.png)

FMAX

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (127:0)= max(Value(Operand index 0) (127:0) , Value(Operand index 1)) (127:0)

Assembly Code：

![image11.png](media/image11.png)

FMIN

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (127:0)= min (Value(Operand index 0) (127:0) , Value(Operand index 1)) (127:0)

Assembly Code：

![image11.png](media/image11.png)

FMADD

Source operand：

Operand index 0，Operand index 1, Operand index 2

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (127:0) = Value(Operand index 0) (127:0) * Value(Operand index 1) (127:0) + Value(Operand index 2) (127:0)

Assembly Code：

![image11.png](media/image11.png)

FDIV

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (127:0)= Value(Operand index 0) (127:0)/ Value(Operand index 1) (127:0)

Assembly Code：

![image12.png](media/image12.png)

FLT:

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (127:0) = Value(Operand index 0) (127:0) < Value(Operand index 1) (127:0) ? 1:0

Assembly Code：

![image11.png](media/image11.png)

FGT

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (127:0)  = Value(Operand index 0) (127:0)> Value(Operand index 1) (127:0) ? 1:0

Assembly Code：

![image11.png](media/image11.png)

FRCP/ FSQRT/ FRSQRT/ FSIN/ FCOS/ FLOG2/ FEXP2

Source operand：

Operand index 0，

Destination  operand：

Operand index 2

Function：

Assembly Code：

![image13.png](media/image13.png)

![image14.png](media/image14.png)

![image15.png](media/image15.png)

double 指令

DADD

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Operand index 0和Operand index 1的64个SIMD分量相加，每个分量64bit，结果存入Operand index 2

Value(Operand index 2) (63:0)= Value(Operand index 0) (63:0) + Value(Operand index 1) (63:0)；

Assembly Code：

![image16.png](media/image16.png)

DSUB

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (63:0)= Value(Operand index 0) (63:0) - Value(Operand index 1) (63:0)；

Assembly Code：

![image16.png](media/image16.png)

DMUL

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (63:0)= Value(Operand index 0) (63:0) * Value(Operand index 1) (63:0)；

Assembly Code：

![image16.png](media/image16.png)

DMAX

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (63:0)= max(Value(Operand index 0) (63:0) , Value(Operand index 1)) (63:0)

Assembly Code：

![image16.png](media/image16.png)

DMIN

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (63:0)= min (Value(Operand index 0) (63:0) , Value(Operand index 1)) (63:0)

Assembly Code：

![image16.png](media/image16.png)

DMADD

Source operand：

Operand index 0，Operand index 1, Operand index 2

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (63:0) = Value(Operand index 0) (63:0) * Value(Operand index 1) (63:0) + Value(Operand index 2) (63:0)

Assembly Code：

![image16.png](media/image16.png)

DDIV

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (63:0)= Value(Operand index 0) (63:0)/ Value(Operand index 1) (63:0)

Assembly Code：

![image17.png](media/image17.png)

DLT:

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (63:0) = Value(Operand index 0) (63:0) < Value(Operand index 1) (63:0)? 1:0

Assembly Code：

![image16.png](media/image16.png)

DGT

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) (63:0)= Value(Operand index 0) (63:0)> Value(Operand index 1) (63:0) ? 1:0

Assembly Code：

![image16.png](media/image16.png)

DSQRT

Source operand：

Operand index 0，

Destination  operand：

Operand index 2

Function：

Value(Operand index 2)  = Sqrt(Value(Operand index 0))

Assembly Code：

![image18.png](media/image18.png)

Int32 /Int8指令

根据汇编指令中，imm数值判断是int8 还是int32

imm==0 ,int32 ; imm==1,int8;

ADD

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Operand index 0和Operand index 1的128/512个SIMD分量相加，每个分量32bit/8bit，结果存入Operand index 2

Value(Operand index 2) = Value(Operand index 0) + Value(Operand index 1)；

Assembly Code：

![image19.png](media/image19.png)

SUB

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = Value(Operand index 0) - Value(Operand index 1)；

Assembly Code：

![image19.png](media/image19.png)

MUL

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = Value(Operand index 0) * Value(Operand index 1)；

Assembly Code：

![image19.png](media/image19.png)

MAX

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = max(Value(Operand index 0), Value(Operand index 1))

Assembly Code：

![image19.png](media/image19.png)

MIN

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = min (Value(Operand index 0) , Value(Operand index 1))

Assembly Code：

![image19.png](media/image19.png)

MADD

Source operand：

Operand index 0，Operand index 1, Operand index 2

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = Value(Operand index 0) * Value(Operand index 1) + Value(Operand index 2)

Assembly Code：

![image19.png](media/image19.png)

LT:

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = Value(Operand index 0) < Value(Operand index 1)? 1:0

Assembly Code：

![image20.png](media/image20.png)

GT

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = Value(Operand index 0) > Value(Operand index 1) ? 1:0

Assembly Code：

![image20.png](media/image20.png)

EQ

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = Value(Operand index 0) == Value(Operand index 1)? 1:0

Assembly Code：

![image21.png](media/image21.png)

Unsigned Int32 /unsigned Int8指令

根据汇编指令中，imm数值判断是uint8 还是uint32

imm==0 ,uint32 ; imm==1,uint8;

UADD

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Operand index 0和Operand index 1的128/512个SIMD分量相加，每个分量32bit/8bit，结果存入Operand index 2

Value(Operand index 2) = Value(Operand index 0) + Value(Operand index 1)；

Assembly Code：

![image22.png](media/image22.png)

USUB

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = Value(Operand index 0) - Value(Operand index 1)；

Assembly Code：

![image22.png](media/image22.png)

UMUL

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = Value(Operand index 0) * Value(Operand index 1)；

Assembly Code：

![image22.png](media/image22.png)

UMAX

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = max(Value(Operand index 0), Value(Operand index 1))

Assembly Code：

![image22.png](media/image22.png)

UMIN

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = min (Value(Operand index 0) , Value(Operand index 1))

Assembly Code：

![image22.png](media/image22.png)

UMADD

Source operand：

Operand index 0，Operand index 1, Operand index 2

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = Value(Operand index 0) * Value(Operand index 1) + Value(Operand index 2)

Assembly Code：

![image22.png](media/image22.png)

ULT:

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = Value(Operand index 0) < Value(Operand index 1)? 1:0

Assembly Code：

![image22.png](media/image22.png)

UGT

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = Value(Operand index 0) > Value(Operand index 1) ? 1:0

Assembly Code：

![image22.png](media/image22.png)

COND

Source operand：

Operand index 0，Operand index 1，Operand index 2

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = Value(Operand index 0) > 0 ? Value(Operand index 1) : Value(Operand index 2)

Assembly Code：

![image23.png](media/image23.png)

ULTS

结束当前的app，执行下一次app

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：PE阵列停止指令，如果结果是1，那么在PE阵列上运行的程序停止，只要有一个分量结果是1，就停止。

Value(Operand index 2) = Value(Operand index 0) < Value(Operand index 1)? 1:0

Assembly Code：

![image24.png](media/image24.png)

特殊指令

DP4A

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

![image25.png](media/image25.png)

![image26.png](media/image26.png)

Assembly Code：

![image27.png](media/image27.png)

GINST

Source operand：

Destination  operand：

Operand index 2

Function：

把当前的instance赋值给寄存器

![image28.png](media/image28.png)

Value(Operand index 2)  = inst_num

Assembly Code：

![image29.png](media/image29.png)

GSIMD

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

![image30.png](media/image30.png)

初始化寄存器

Value(Operand index 2)  = {31,30,…,1,0}

Assembly Code：

![image31.png](media/image31.png)

GTASK

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

![image32.png](media/image32.png)

把当前的task编号赋值给寄存器

Value(Operand index 2)  = task_num

Assembly Code：

![image33.png](media/image33.png)

Logic Inst

根据汇编指令中，imm数值判断是integer 8bit 还是integer 32

imm==0 ,integer 32bit ; imm==1,integer 8bit;

LSL

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2)  = Value(Operand index 0) << Value(Operand index 1)

Assembly Code：

![image34.png](media/image34.png)

LSR  只用于无符号数

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2)  = Value(Operand index 0) >> Value(Operand index 1)

Assembly Code：

![image34.png](media/image34.png)

OR

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2)  = Value(Operand index 0) | Value(Operand index 1)

Assembly Code：

![image35.png](media/image35.png)

AND

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2)  = Value(Operand index 0) & Value(Operand index 1)

Assembly Code：

![image35.png](media/image35.png)

NOT

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2)  = ! Value(Operand index 0)

Assembly Code：

![image35.png](media/image35.png)

XOR

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2) = Value(Operand index 0) ^ Value(Operand index 1)

Assembly Code：

![image35.png](media/image35.png)

ASR 只用于有符号数

Source operand：

Operand index 0，Operand index 1

Destination  operand：

Operand index 2

Function：

Value(Operand index 2)  = Value(Operand index 0) >> Value(Operand index 1)  Assembly Code：

![image34.png](media/image34.png)

立即数指令

IMM

Source operand：

Destination  operand：

Operand index 2

Function：

IMM(31:0)以广播的形式，赋值给Operand index 2

Value(Operand index 2) （127：0）= IMM

Assembly Code：

![image36.png](media/image36.png)

FIMM

Source operand：

Destination  operand：

Operand index 2

Function：

跟IMM(31:0)字段的32bit数，一起拼接成64bit的数据

Value(Operand index 2)  = ｛IMM,opr2(30) IMM,opr2(28),IMM,opr2(26),IMM,opr2(24),IMM,opr2(22),IMM,opr2(20),IMM,opr2(18),IMM,opr2(16),IMM,opr2(14),IMM,opr2(12),IMM,opr2(10),IMM,opr2(8),IMM,opr2(6),IMM,opr2(4),IMM,opr2(2),IMM,opr2(0)}

Assembly Code：

![image36.png](media/image36.png)

类型转换

FP2DB

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

![image37.png](media/image37.png)

DB2FP

Source operand：

Operand index 0

Destination  operand：

Operand index 2

Function：

根据imm 字段，判断哪半部分进行类型转换

(Value(Operand index 0) (15:0)(47:32)(79:64)(96:111))= float(Value(Operand index 0))

Assembly Code：

![image38.png](media/image38.png)

FXP2FP

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

![image39.png](media/image39.png)

FP2FXP

imm是全1的时候，只有RX0被赋值

Source operand：

Operand index 0

Destination  operand：

Operand index 2

Function：

根据imm[4:0] 字段，imm[4:0]=[四舍五入/舍弃尾数，toRX3, toRX2, toRX1, toRX0] ，判断如何进行类型转换

Value(Operand index 2) = int(Value(Operand index 0))  simd32->simd32

Assembly Code：

![image40.png](media/image40.png)

H2FP

Source operand：

Operand index 0

Destination  operand：

Operand index 2

Function：

根据imm 字段，判断哪半部分进行类型转换

imm==0: Value(Operand index 2) = float(Value(Operand index 0)(31:0))  simd64->simd32

imm>0: Value(Operand index 2) = float (Value(Operand index 0)(63:32))  simd64->simd32

Assembly Code：

![image41.png](media/image41.png)

FP2H

Source operand：

Operand index 0

Destination  operand：

Operand index 2

Function：

根据imm 字段，判断哪半部分进行类型转换

Value(Operand index 2)(15:0) = half float(Value(Operand index 0))  simd32->simd64

Assembly Code：

![image42.png](media/image42.png)

SHFL

Source operand：

Operand index 0

Destination  operand：

Operand index 1 ，Operand index 2

Function：

![image43.png](media/image43.png)

![image44.png](media/image44.png)

广播给oprand2广播给oprand2

![image45.png](media/image45.png)

广播给oprand2广播给oprand2

![image46.png](media/image46.png)

![image47.png](media/image47.png)

![image48.png](media/image48.png)

![image49.png](media/image49.png)

Assembly Code：

![image50.png](media/image50.png)

RXIN

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

![image51.png](media/image51.png)

RXOUT

Source operand：NULL

Destination  operand：Operand index 2

Function：

把用于int8计算的RX[0-3]值取回到目的寄存器里：

imm=0: RX0 => src2     imm=1: RX1 => src2

imm=2: RX2 => src2     imm=3: RX3 => src2

(LRX不适用)

Assembly Code：

![image52.png](media/image52.png)

COPYT指令

Source operand：

Operand index 0

Destination  operand：

Operand index 2

Function：

将源PE上的寄存器内容，拷贝到目的PE上的寄存器，目的寄存器编号在dst_pe_idx；

Assembly Code：

![image53.png](media/image53.png)

访存指令

DFU访存指令地址= imm + instance_baseaddr(iteration field)，例如下面的指令：

![image54.png](media/image54.png)

HLDT

对齐方式：（32*4 ）Bytes对齐 4*（regbase+imm）

Assembly Code：

![image55.png](media/image55.png)

![image56.png](media/image56.png)

![image57.png](media/image57.png)

![image58.png](media/image58.png)

![image59.png](media/image59.png)

![image60.png](media/image60.png)

ILDMT

对齐方式：4Bytes对齐

Assembly Code：

带extra_field

![image61.png](media/image61.png)

不带extra_field，默认其它域为0：

![image62.png](media/image62.png)

![image63.png](media/image63.png)

![image64.png](media/image64.png)

![image65.png](media/image65.png)

![image66.png](media/image66.png)

![image67.png](media/image67.png)

![image68.png](media/image68.png)

SLDSHIF

对齐方式：128Bytes对齐

Assembly Code：

![image69.png](media/image69.png)

![image70.png](media/image70.png)

MASK

Source operand：

Operand index 0

Destination  operand：

Function：根据Operand Index0的值，给Mask寄存器赋值；

![image71.png](media/image71.png)

![image72.png](media/image72.png)

Assembly Code：

![image73.png](media/image73.png)

详细信息如下：更正一下：ext offset：当选中32bit和64bit时，不用选择。选中8bit的时候，用0，1，2，3.选中16bit，用0和2

![image74.png](media/image74.png)

![image76.png](media/image76.png)

![image75.emf](media/image75.emf)

![image77.png](media/image77.png)

HSTT

对齐方式：128Bytes对齐

Assembly Code：

带mask寄存器：

![image78.png](media/image78.png)

不带mask寄存器：

![image79.png](media/image79.png)

![image80.png](media/image80.png)

![image81.png](media/image81.png)

![image82.png](media/image82.png)

![image83.png](media/image83.png)

![image84.png](media/image84.png)

![image85.png](media/image85.png)

SSTSHIF

对齐方式：128Bytes对齐

![image86.png](media/image86.png)

与SLDSHIF相同，加入了other段的mask信息；

SSTM（很少用到）

![image87.png](media/image87.png)

索引粒度为8bit，写回最低K={dst_pe_idx[4:0]，dst_pe_idx[8:7]}个分量，或者最高128-K个分量。

dst_pe_idx[4:0]:

dst_pe_idx[6:5]: [hign,low]

dst_pe_idx[8:7]:

dst_pe_idx[10:9]:regidx索引，SIMD128模式对应选择4个regid中的一个，SIMD64，SIMD32按比例减少。

[high,low]为2'b01，根据regidx选择某个寄存器，写regidx寄存器内最高的128-K个分量，同时编号大于此寄存器的其它寄存器全部写回；

[high,low]为2'b10，根据regidx选择某个寄存器，写regidx寄存器内最低的128-K个分量，同时编号小于此寄存器的全部写回；

[high,low]为2'b00，表示所有分量全部写回;

K==0,所有分量全部写回；

![image88.png](media/image88.png)

![image89.png](media/image89.png)

TRCT8

Source operand：

Destination  operand：

Operand index 2

Function：

![image90.png](media/image90.png)

![image91.png](media/image91.png)

Assembly Code：

![image92.png](media/image92.png)

EXPD32

Source operand：Operand index 0

Destination  operand：Operand index 2

Function：

根据imm字段的值判断int8扩展成int32的方式：

Assembly Code：

![image93.png](media/image93.png)

![image94.png](media/image94.png)

QMADD

Source operand：Operand index 0， Operand index 1

Destination  operand：

Function：

int8数据类型的乘法

![image95.png](media/image95.png)

![image96.png](media/image96.png)

![image97.png](media/image97.png)

Assembly Code：

![image98.png](media/image98.png)
