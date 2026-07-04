# DFU3500 SIMD Docx Media OCR

本文件由 `tools/ocr_instruction_media.py` 生成。
OCR 是原始识别文本，可能有错字；需要和图片、xlsx 指令卡片、examples 交叉确认。

## image1.png

- size: 258x23
- psm: 6
- tags: low-signal
- text_score: 17

![image1.png](../media/image1.png)

```text
HADD ,HADD11,A1,A2,B0,,,0
```

## image2.png

- size: 257x23
- psm: 6
- tags: low-signal
- text_score: 17

![image2.png](../media/image2.png)

```text
HSUB ,HSUB12,A1,A2,B1,，,,9
```

## image3.png

- size: 271x26
- psm: 6
- tags: low-signal
- text_score: 18

![image3.png](../media/image3.png)

```text
_HMUL,HMUL13,A1,A2,B2,，,，,9
```

## image4.png

- size: 260x22
- psm: 6
- tags: low-signal
- text_score: 17

![image4.png](../media/image4.png)

```text
HMAX,HMAX15,A1,A2,B4,,,0
```

## image5.png

- size: 262x23
- psm: 6
- tags: low-signal
- text_score: 17

![image5.png](../media/image5.png)

```text
HMIN ,HMIN16 ,A1,A2,B5,, ,9
```

## image6.png

- size: 292x28
- psm: 11
- tags: low-signal
- text_score: 21

![image6.png](../media/image6.png)

```text
HMADD ,HMADD14 A1,A2 E3550
```

## image7.png

- size: 262x22
- psm: 6
- tags: low-signal
- text_score: 17

![image7.png](../media/image7.png)

```text
HDIV,HDIV11,A1,A2,B0,,,0
```

## image8.png

- size: 245x22
- psm: 6
- tags: low-signal
- text_score: 15

![image8.png](../media/image8.png)

```text
HLT ,HLT18,A1,A2,B7,,,0
```

## image9.png

- size: 253x22
- psm: 6
- tags: low-signal
- text_score: 14

![image9.png](../media/image9.png)

```text
) [GT ,HGT17,A1,A2,B6,,,0
```

## image10.png

- size: 277x45
- psm: 6
- tags: low-signal
- text_score: 33

![image10.png](../media/image10.png)

```text
HSIS,HSIS11,A1, ,B0,,8,0
HSIS,HSIS12,A2, ,B1,,16,0
```

## image11.png

- size: 445x367
- psm: 6
- tags: zh
- text_score: 571

![image11.png](../media/image11.png)

```text
四ADD ,FADD4,KernetLg ,KerneL1,Kernel3,,,1
”FSUB ,FSUB5,KernetLg,KernetL1,KerneL4，，，1
3 FMUL, FMUL6 ,KernelO,Kernel1,Kernel5,,,1
) FMADD , FMADD7 ,KernelO,Kernel1,Kernel6, , ,1
) FMIN, FMIN8 ,KernelO,Kernel1,Kernel7,,,1
| FMIN, FMINS,Kernel1,KernelO,Kernel8,,,1
> FMIN, FMIN10 ,Kernel2,Kernel2,Kernel9, ,,1
3 FMAX, FMAX11,Kerneld,Kernel1,Kernel10, ,,1
| FMAX, FMAX12,Kernel1,Kernelo,Kerneli1,,,1
> FMAX, FMAX13,Kernel2,Kernel2,Kernel12, , ,1
> EQ, E014 ,Kernelo,Kernel1,Kernel13, ,,1
” EQ, E015,Kernel2,Kernel2,Kernel14, , 1
3 FLT,FLT16,KernelO,Kernel1,Kernel15,,,1
) FLT, FLT17,Kernel1,KernelO,Kernel16,,,1
) FLT, FLT18,Kernel2,Kernel2,Kernel17,,,1
| FGT,FGT19,KernelO,Kernel1,Kernel18, ,,1
2 FGT ,FGT20,Kernel1,KernelO,Kernel19,, ,1
3 FGT,FGT21,Kernel2,Kernel2,Kernel20,,,1
```

## image12.png

- size: 432x26
- psm: 11
- tags: zh
- text_score: 31

![image12.png](../media/image12.png)

```text
由
| FDIV, FDIV2,Kernel0,Kernel1,Kernel2,,,
```

## image13.png

- size: 832x500
- psm: 6
- tags: encoding, semantics
- text_score: 309

![image13.png](../media/image13.png)

```text
FRCP )Value(Operand index 2) = 1/(Value(Operand index 0))
FSQRT \Value(Operand index 2) = Sqrt(Value(Operand index 0))
FRSQRT )Value(Operand index 2) = 1/Sqrt(Value(Operand index 0))
FSIN )Value(Operand index 2) = sin(Value(Operand index 0))
FCOS )Value(Operand index 2) = cos(Value(Operand index 0))
FLOG2 \Value(Operand index 2) = LOG2(Value(Operand index 0))
FEXP2 )Value(Operand index 2) = EXP2(Value(Operand index 0))
```

## image14.png

- size: 243x25
- psm: 11
- tags: low-signal
- text_score: 17

![image14.png](../media/image14.png)

```text
_—
a
a
FRCP,FRCP11,A1,.B0,,,
```

## image15.png

- size: 312x20
- psm: 6
- tags: low-signal
- text_score: 19

![image15.png](../media/image15.png)

```text
FRSORT,FRSORT11,A1,,.B0,,,.0
```

## image16.png

- size: 421x202
- psm: 6
- tags: low-signal
- text_score: 322

![image16.png](../media/image16.png)

```text
DADD ,DADD8 ,KernelO,Kernel1,Kernel3,, ,1
DSUB , DSUB9 , KernelO,Kernel1,Kernel4, , 1
DMUL, DMUL10,KernelO,Kernel1,Kernel5, , ,1
DMADD ,DMADD11,Kernel@,Kernel1,Kernel6, ,,1
DMIN , DMIN12,KernelO,Kernel1,Kernel7, , ,1
DMIN , DMIN13,Kernel1,KernelO,Kernel8, , ,1
DMIN , DMIN14,Kernel2,Kernel2,Kernel9, , 1
DMAX, DMAX15,KernelO,Kernel1,Kernel10,,,1
DMAX, DMAX16 ,Kernel1,KernelO,Kernel11,,,1
DMAX, DMAX17,Kernel2,Kernel2,Kernel12,,,1
```

## image17.png

- size: 412x25
- psm: 6
- tags: low-signal
- text_score: 31

![image17.png](../media/image17.png)

```text
DDIV,DDIV2,KernelO,Kernel1,Kernel2,,,1
```

## image18.png

- size: 397x75
- psm: 6
- tags: low-signal
- text_score: 66

![image18.png](../media/image18.png)

```text
HLDT,HLDT9，，,Kernet9,-1,9,9
DSQRT,DSQRT1,KernetLg, ,KernetL1,，,1
| HSTT,HSTT2, , ,Kernel1,-1,0,1
```

## image19.png

- size: 475x206
- psm: 6
- tags: low-signal
- text_score: 299

![image19.png](../media/image19.png)

```text
ADD, ADD4,Kernel0,Kernel1,Kernel3,,,1
SUB , SUB5 ,KerneLO,Kernel1,Kernel4,,,1
MUL, MUL6 ,KerneLO,Kernel1,Kernel5,,,1
MADD , MADD7 ,KernelO,Kernel1,Kernel6, , ,1
MIN, MIN8 ,KernelO,Kernel1,Kernel7,,,1
MIN, MINS ,Kernel1,KernelO,Kernel8,,,1
MIN, MIN10,Kernel2,Kernel2,Kernel9, 1
MAX, MAX11,Kernelo,Kernel1,Kernel10, ,,1
MAX, MAX12,Kernel1,Kernelo,Kernel11, ,,1
MAX,MAX13,Kernel2,Kernel2,Kernel12, ,,1
```

## image20.png

- size: 405x123
- psm: 6
- tags: low-signal
- text_score: 176

![image20.png](../media/image20.png)

```text
LT,LT16,KernelL9,KerneL1,KerneL15，，，,1
) LT,LT17,Kernel1,Kerneld,Kernel16,,,1
) LT, LT18,Kernel2,Kernel2,Kernel17,,,1
_ GT,GT19,Kerneld,Kernel1,Kernel18,,,1
- GT, GT20,Kernel1,Kerneld,Kernel19, ,,1
. GT,GT21,Kernel2,Kernel2,Kernel20,,,1
```

## image21.png

- size: 397x42
- psm: 11
- tags: low-signal
- text_score: 57

![image21.png](../media/image21.png)

```text
EQ,£014,KernelO,Kernel1,Kernel13, ,,1_
E0,E015,Kernel2,Kernel2,Kerneli4,,.
```

## image22.png

- size: 440x297
- psm: 6
- tags: low-signal
- text_score: 465

![image22.png](../media/image22.png)

```text
VADD , VADD4 ,KernelO,Kerneli,Kernets,,,1
USUB , USUB5 ,KernelO,Kernel1,Kernel4, , 1
UMUL , UMUL6 ,KernelO,Kernel1,Kernel5, , ,1
UMADD , UMADD7 ,KerneL9,Kernel1,Kernel6,,,1
UMAX, UMAX8 , KernelO,Kernel1,Kernel10, , 1
UMAX, UMAX9, Kernel1,Kernelo,Kerneli1,,,1
UMAX, UMAX10,Kernel2,Kernel2,Kernel12,,,1
EQ, £011,KernelO,Kernel1,Kernel13,, ,1
EQ, £012,Kernel2,Kernel2,Kernel14,, ,1
ULT,ULT13,Kernelo,Kernel1,Kernel15, , 1
ULT,ULT14 ,Kernel1,Kernelo,Kernel16, , 1
ULT,ULT15 ,Kernel2,Kernel2,Kernel17, , ,1
UGT ,UGT16 ,KernelO,Kernel1,KerneL18, , 1
UGT ,UGT17 ,Kernel1,Kernelo,Kernel19, , 1
UGT,UGT18,Kernel2,Kernel2,Kernel20,,,1
```

## image23.png

- size: 397x30
- psm: 11
- tags: low-signal
- text_score: 27

![image23.png](../media/image23.png)

```text
a
ae
- COND , COND6 , Inst, ZERO,Kerneld, ,,
```

## image24.png

- size: 448x81
- psm: 6
- tags: low-signal
- text_score: 72

![image24.png](../media/image24.png)

```text
HLDT,HLDT9，,，, ,KernetLg,-1;,9,9
_HLDT,HLDT1，，,KerneL1, -1,32,0
ULTS ,ULTS2,Kernelo,Kernel1,Kernel2, ,,1
```

## image25.png

- size: 533x141
- psm: 6
- tags: encoding, zh
- text_score: 120

![image25.png](../media/image25.png)

```text
INTS8 混合精度乘加指令 A(8bits) * B(8bits) + 32(bits)
imm='b00,A(uint8) * B(uint8) + uint32;
imm='b01,A(int8) * B(uint8) + int32;
imm='b10,A(uint8) * B(int8) + int32;
imm='b11,A(int8) * B(int8) + int32;
```

## image26.png

- size: 977x128
- psm: 6
- tags: encoding, semantics
- text_score: 233

![image26.png](../media/image26.png)

```text
Value(Operand index 2)(i) += Value(Operand index 0)(i)[7:0] * Value(Operand index 1)(i)[7:0]
+= Value(Operand index 0)(i)[15:8] * Value(Operand index 1)(i)[15:8]
+= Value(Operand index 0)(i)[23:16] * Value(Operand index 1)(i)[23:16]
+= Value(Operand index 0)(i)[31:24] * Value(Operand index 1)(i)[31:24]
32bits*simd32 {4*8bits}*simd32 {4*8bits}*simd32
```

## image27.png

- size: 448x92
- psm: 11
- tags: low-signal
- text_score: 142

![image27.png](../media/image27.png)

```text
OEM POAT 9 SUE UTI yh
D
>
DP4A,DP4A10, Inst00, Inst10,OUTPUTO, ,0,0
3
DP4A,DP4A11, Inst00, Inst10,OUTPUT1, ,1,0
-
DP4A,DP4A12, Inst@0, Inst10,OUTPUT2, ,2,0
7
DP4A,DP4A13, Inst00, Inst10, OUTPUT3, ,3,0
```

## image28.png

- size: 1104x185
- psm: 11
- tags: low-signal
- text_score: 71

![image28.png](../media/image28.png)

```text
ee
en 4
for(k = 0; k <4; ks+){
for(i
=
=
0; i < SIMD_UNIT
i++) {
results[k] .ufix[i]
= inst_trace_info->instance_ idx
}
_
}
```

## image29.png

- size: 287x32
- psm: 11
- tags: low-signal
- text_score: 25

![image29.png](../media/image29.png)

```text
out een ee ee
GINST,GINST4,,,Inst,,,
```

## image30.png

- size: 763x187
- psm: 6
- tags: low-signal
- text_score: 41

![image30.png](../media/image30.png)

```text
RN
for(k = 0; k < 4; k++){
for(i = 0; i < SIMD_UNIT; i++) {
results[k].ufix[i] = i;
}
_ +
```

## image31.png

- size: 297x75
- psm: 6
- tags: encoding
- text_score: 45

![image31.png](../media/image31.png)

```text
IMM, IMMO,,,Inst,,0,0 —
| GSIMD,GSIMD1,,,Inst,,,1
| HSTT,HSTT2,,,Inst,0,0,1
```

## image32.png

- size: 810x168
- psm: 6
- tags: low-signal
- text_score: 45

![image32.png](../media/image32.png)

```text
for(k = 0; k < 4; k++){
for(i = 0; i < SIMD_UNIT; i++) {
results[k].ufix[i] = task_idx;
}
}
```

## image33.png

- size: 372x162
- psm: 6
- tags: encoding
- text_score: 124

![image33.png](../media/image33.png)

```text
HLDT,HLDT9,，,,KernelL9,9,9,9
IMM, IMM1，, ,INT1, ,1,9
IMM, IMM2，, ZERO, ,0,0
IMM, IMM3,,,T, 0,0
GTASK,GTASK4,,,T,, 1
AND,AND5,T,INT1,T,,,1
COND ,COND6 ,T,ZERO,Kernelo, ,,1
HSTT,HSTT7,, ,Kernel0,0,0,1
```

## image34.png

- size: 350x66
- psm: 6
- tags: low-signal
- text_score: 77

![image34.png](../media/image34.png)

```text
LSL,LSL33, Inst9,NUM9,OUTPUTL6，,，, ,9
LSR,LSR34,Inst6,NUM9,OUTPUTR6，，,9
ASR, ASR35, InstO ,NUM@, OUTPUTAQ, , ,9
```

## image35.png

- size: 417x82
- psm: 6
- tags: low-signal
- text_score: 107

![image35.png](../media/image35.png)

```text
4 AND, AND2,Kernel1,Kernel2,Kernel3,,,,
5 OR, OR3,Kernel1,Kernel2,Kernel4,,,,
5 NOT,NOT4,Kernel1, ,Kernel5,,,,
7 XOR,XOR5,Kernel1,Kernel2,Kernel6,,,,
```

## image36.png

- size: 880x178
- psm: 6
- tags: encoding
- text_score: 257

![image36.png](../media/image36.png)

```text
L nst _ name, inst tag_name,src_reg_Ldqxo,src_reg_Ldxl,dst_ reg_Ldqx:dqst pe_Ldx, unm, iteration
2 HLDT,HLDTO, , ,KernetL9,-1,9,9
3 IMM,IMM1,, ,KerneL1, ,824633721,1
| FIMM,FIMM2,,,Kernel1, , 1068280840, 1
5 DMUL,DMUL3,KernelO,Kernel1,Kernel2,,,1
5 DADD ,DADD4 ,KernelO,Kernel1,Kernel3,, ,1
7 HSTT,HSTT5, , ,Kernel2,-1,0,1
3 HSTT,HSTT6, , ,Kernel3,-1,0,2
```

## image37.png

- size: 417x118
- psm: 6
- tags: low-signal
- text_score: 124

![image37.png](../media/image37.png)

```text
HLDT,HLDT9，,, ,Kernet9, -1,9,9
FP2DB,FP2DB1,KernetLg, ,KernetL1,,9,1
| FP2DB, FP2DB2, Kernel, ,Kernel2, ,1,1
; DADD ,DADD3, Kernel1,Kernel2,Kernel3, , 1
. HSTT,HSTT4, , ,Kernel3,-1,0,1
```

## image38.png

- size: 367x18
- psm: 6
- tags: low-signal
- text_score: 26

![image38.png](../media/image38.png)

```text
DB2FP,DB2FP4,Kernel1, ,Kernel3,,,1
```

## image39.png

- size: 335x81
- psm: 6
- tags: low-signal
- text_score: 94

![image39.png](../media/image39.png)

```text
FXP2FP,FXP2FP8,, ,rOUTPUT9, ,1,9
FXP2FP,FXP2FP9, , ,rOUTPUT1, ,2,0
FXP2FP,FXP2FP10, , ,rOUTPUT2, ,4,0
FXP2FP,FXP2FP11, ,, rOUTPUT3, ,8,0
```

## image40.png

- size: 395x47
- psm: 6
- tags: low-signal
- text_score: 56

![image40.png](../media/image40.png)

```text
| FP2FXP,FP2FXP2,KerneLg, ,Kernel2,,,1
| FP2FXP, FP2FXP3,Kernel1, ,Kernel3,,,1
```

## image41.png

- size: 262x25
- psm: 11
- tags: zh
- text_score: 16

![image41.png](../media/image41.png)

```text
有
H2FP,H2FP3,A1, ,B0, ,9,9
```

## image42.png

- size: 262x25
- psm: 6
- tags: low-signal
- text_score: 15

![image42.png](../media/image42.png)

```text
FP2H,FP2H11,A1,,B0,,,0
```

## image43.png

- size: 791x306
- psm: 6
- tags: encoding, zh
- text_score: 359

![image43.png](../media/image43.png)

```text
重排simd各个分量的位置
imm[1:0]=0，为之前旧的 idx压缩成5bit，最多shuffle6个32数的模式
imm[1:0]=1，为新的idx为32bit数，最多shuffle8个32数的模式
imm[1:0]=2，为新的idx为32bit数，最多shuffle8个64数的模式
imm[1:0]=3，为shift模式，2个数高低simd32分量拼接的模式
目的寄存器src2谨记事先初始化
imm[2]=0, 第一组1024bit数内部shuffle; imm[2]=1, 第一组1024bit数内部数据保持;
imm[3]=0, 第二组1024bit数内部shuffle; imm[3]=1, 第二组1024bit数内部数据保持;
imm[4]=0, 第三组1024bit数内部shuffle; imm[4]=1, 第三组1024bit数内部数据保持;
imm[5]=0, 第四组1024bit数内部shuffle; imm[5]=1, 第四组1024bit数内部数据保持;
```

## image44.png

- size: 973x292
- psm: 11
- tags: encoding, semantics, zh
- text_score: 444

![image44.png](../media/image44.png)

```text
imm[1:0]==0 immediate mode:
Value(Operand index 0)[59:0] = [dst5,dst4,dst3,dst2,dst1,dst0,
src5,src4,src3,src2,srclisrc0]:
(1)select 6 simds( src5,src4,src3,src2,src1,src0) from Value(Operand index 1),
(2)place them to 6 simds(dst5,dst4,dst3,dst2,dst1,dst0) position of Value(Operand index 2).
32>dst5>dst4>dst3>dst2>dst1>dst0>=0; srci < 32; dsti==0 and i>0, disable i postion
special use: when Val(Operand index 0)==zeros, exchange up[1023:512] and down[511:0] of Val(Operand idx2)
指令写法参考:
IMM, , , idx_reg, 321579821758215(60位的index编码立即数)
shfl, idx_reg, vall val2
special use:shfl, idx_reg , val2
```

## image45.png

- size: 990x267
- psm: 6
- tags: encoding, semantics, zh
- text_score: 459

![image45.png](../media/image45.png)

```text
imm[1:0]==1 fp32-merge simd32 mode:
Value(Operand index 0)(15:0) =
[dst7,dst6,dst5,dst4,dst3,dst2,dst1,dst0, —_src7,src6,src5,src4,src3,src2,src1,srcO]:
(1)select 8 simds( src7,src6,src5,src4,src3,src2,src1,src0) from Value(Operand index 1)(31:0),
(2)place them to 8 simds(dst7,dst6,dst5,dst4,dst3,dst2,dst1,dst0) position of Value(Operand index 2)(31:0).
32>dst7>dst6>dst5>dst4>dst3>dst2>dst1>dst0>=0; srci < 32; dsti==0 and i>0, disable i postion
special use: when srcO=srcl=dst0=dst1, broadcase Value(Operand index 1)(src0) to all 32 simds
指令写法参考:
LDN, ,, idx_reg (16个simd分量分别指定16个index位置)
shfl, idx_reg, vall, val2
```

## image46.png

- size: 997x187
- psm: 6
- tags: encoding, semantics
- text_score: 398

![image46.png](../media/image46.png)

```text
imm[1:0]==2 fp64-merge simd16 mode:
Value(Operand index 0)(15:0) =
[dst7,dst6,dst5,dst4,dst3,dst2,dst1,dst0, —_src7,src6,src5,src4,src3,src2,src1,srcO]:
(1)select 8 simds( src7,src6,src5,src4,src3,src2,src1,src0) from Value(Operand index 1)(15:0),
(2)place them to 8 simds(dst7,dst6,dst5,dst4,dst3,dst2,dst1,dst0) position of Value(Operand index 2)(15:0).
16>dst7>dst6>dst5>dst4>dst3>dst2>dst1>dst0>=0; srci < 32; dsti==0 and i>0, disable i postion
easy use: when src0=srcl=dst0=dst1, broadcase Value(Operand index 1)(src0) to all 16 simds
```

## image47.png

- size: 1011x91
- psm: 6
- tags: encoding, semantics
- text_score: 167

![image47.png](../media/image47.png)

```text
imm[1:0]==3 shift simd32 mode:
shift_num = Value(Operand index 0)(0), shifting low simds of val2 to the high simds of val1
\Value(Operand index 2) = {Value(Operand index 2)(shift_num-1:0), Value(Operand index 1)(31:shift_num)}
```

## image48.png

- size: 1191x568
- psm: 6
- tags: encoding, semantics, zh
- text_score: 255

![image48.png](../media/image48.png)

```text
a
imm==0: Value(index 0)[59:0] = [dst5,dst4,dst3,dst2,dst1,dst0, src5,src4,src3,src2,src1,src0]
源数据Src1l-1024bits-simd32
GR)
CEP ECE EPP EEE
Srcolis30bits, oa 7一
1, 3, 6, 8, 12, 14
Src0的31-60bits，6个目的idx:
10.
— 后5个idx不能为0
[apelsalslslslalslalslalslslell
源数据Src2-1024bits-simd32
CRM) wy
Telefe ieee te]
目的数据Src2-1024bits-simd32
r CRIB
```

## image49.png

- size: 1240x540
- psm: 11
- tags: low-signal
- text_score: 117

![image49.png](../media/image49.png)

```text
vall(shift_num:31)
val2(shift_num-1:0)
o [i [2 Ts Ya Js Jo Fr Js Yo Trlr sfuafishiahug
WA | 19]20]21]22]23]24]25] 26]27]28]29]30]31
shift_num=2
naaaqgammeRrrrn
```

## image50.png

- size: 453x117
- psm: 11
- tags: semantics
- text_score: 182

![image50.png](../media/image50.png)

```text
SSHFL , SHFL75, Inst0,KernelO,OUTPUTO, ,0,0
SHFL , SHFL76, ZERO , Kerne19, OUTPUT1, ,0,0
SHFL,SHFL77, Inst1,Kernel@, QUTPUT2, ,1,0
SHFL , SHFL78 , ZERO , Kerne19 , OUTPUT3, ,1,0
SHFL , SHFL79, Inst1,KernelO, OUTPUT, ,2,0
SHFL.SHFL80,ZERO,.KernelO,OUTPUTS, ,2,0
```

## image51.png

- size: 253x22
- psm: 6
- tags: low-signal
- text_score: 15

![image51.png](../media/image51.png)

```text
RXIN,RXIN3,ZERO,,,,0,0
```

## image52.png

- size: 317x30
- psm: 6
- tags: low-signal
- text_score: 21

![image52.png](../media/image52.png)

```text
RXOUT,RXOUT8,,,rOUTPUTO, ,0,0
```

## image53.png

- size: 912x72
- psm: 6
- tags: encoding
- text_score: 127

![image53.png](../media/image53.png)

```text
Bnst_name, inst_tag_name,src_reg_idx0,src_reg_idx1,dst_reg_idx,dst_pe idx, imm, iteration
HLDT,HLDTO, , ,rKernelo, -1,0,0
COPYT,COPYT1, rKernelO, ,rKernelO,1,,1
```

## image54.png

- size: 1077x57
- psm: 6
- tags: encoding
- text_score: 103

![image54.png](../media/image54.png)

```text
inst_name,inst_tag_name,Src_reg_idx9,src_reg_idx1l,dst_reg_idx,dst_pe_idx,imm,iteration,other_info
LDM,LDMO,,,idx0,,0,1,
```

## image55.png

- size: 345x177
- psm: 6
- tags: low-signal
- text_score: 165

![image55.png](../media/image55.png)

```text
? HLDT HLDTO, , ,Kernet9,9,9,9
3 HLDT,HLDT1,, ,Kernel1,0,128,0
| HLDT,HLDT2,, ,Kernel2,0,256,0
> HLDT HLDT3, , ,Kernel3,0,384,0
) HSTT,HSTT4,, ,Kernel,0,0,1
/ HSTT,HSTTS, , ,Kernel1,0,128,1
3 HSTT,HSTT6, , ,Kernel2,0,256,1
) HSTT,HSTT7, , ,Kernel3, 0,384, 1
```

## image56.png

- size: 1238x648
- psm: 11
- tags: encoding, zh
- text_score: 121

![image56.png](../media/image56.png)

```text
HLDT
Fe Ricore
imm
4Bytes
地址偏移
dst_pe_idx
(n+1)*32*4Bytes
硬件指令间偏移
(n+1)*1024bits
128
硬件指令0
硬件指令1
imm =0
硬件指令2
dst_pe_idx =0
硬件指令3
三三国王一
fp16
simd128
spm数据
```

## image57.png

- size: 1202x661
- psm: 11
- tags: encoding, zh
- text_score: 124

![image57.png](../media/image57.png)

```text
HLDT
Fe RIcoRE
imm
4Bytes
地址偏移
(n+1)*32*4Bytes
dst_pe_idx
(n+1)*1024bits
硬件指令间偏移
128
硬件指令0
32*4Bytes
硬件指令1
imm =0
硬件指令2
硬件指令3
dst_pe_idx = 1
fp16
simd128
spm数据
```

## image58.png

- size: 1227x648
- psm: 11
- tags: encoding, zh
- text_score: 125

![image58.png](../media/image58.png)

```text
HLDT
re RicoRe
imm
4Bytes
地址偏移
(n+1)*32*4Bytes
dst_pe_idx
(n+1)*1024bits
硬件指令间偏移
128
1024bits
硬件指令0
硬件指令1
imm = 32
硬件指令2
硬件指令3
dst_pe_idx = 1
fp16
simd128
spm数据
```

## image59.png

- size: 1227x666
- psm: 11
- tags: encoding, zh
- text_score: 124

![image59.png](../media/image59.png)

```text
HLDT
re RicoRe
imm
4Bytes
地址偏移
dst_pe_idx
(n+1)*32*4Bytes
硬件指令间偏移
(n+1)*1024bits
128
硬件指令0
32*4Bytes
硬件指令1
硬件指令2
imm =0
硬件指令3
dst_pe_idx = 3
fp16
simd128
spm数据
```

## image60.png

- size: 1223x653
- psm: 11
- tags: encoding, zh
- text_score: 164

![image60.png](../media/image60.png)

```text
HLDT
re RICORE
imm
4Bytes
地址偏移
dst_pe_idx
(n+1)*32*4Bytes
硬件指令间偏移
(n+1)*1024bits
128
1024bits
32*4Bytes
硬件指令0
1024bits
硬件指令1
1024bits
硬件指令2
1024bits
imm =0
dst_pe_idx = -1
硬件指令3
1024bits
fp16
simd128
spm数据
```

## image61.png

- size: 437x261
- psm: 6
- tags: low-signal
- text_score: 330

![image61.png](../media/image61.png)

```text
: ILDMT, ILDMT19,,,Kerneli9, -1,8,0,1,3
:ILDMT, ILDMT20,,,Kernel20, -1,9,0,1
:ILDMT,ILDMT21,,,Kernel21, -1,9,0,1,1
: ILDMT, ILDMT22,, ,Kernel22, -1,9,0,1,2
: ILDMT, ILDMT23,, ,Kernel23, -1,9,0,1,3
:ILDMT, ILDMT24,,,Kernel24, -1,10,0,1
:ILDMT,ILDMT25,,,Kernel25, -1,10,0,1,1
: ILDMT, ILDMT26,,,Kernel26, -1,10,0,1,2
: ILDMT, ILDMT27,,,Kernel27, -1,10,0,1,3
:ILDMT, ILDMT28,, ,Kernel28, -1,11,0,1
:ILDMT,ILDMT29,,,Kernel29, -1,11,0,1,1
: ILDMT, ILDMT30,, ,Kernel30, -1,11,0,1,2
: ILDMT, ILDMT31,, ,Kernel31, -1,11,0,1,3
```

## image62.png

- size: 321x25
- psm: 6
- tags: low-signal
- text_score: 21

![image62.png](../media/image62.png)

```text
ILDMT,ILDMTO,,,KernelO, 0,0,0
```

## image63.png

- size: 907x161
- psm: 6
- tags: encoding, zh
- text_score: 202

![image63.png](../media/image63.png)

```text
simd_mode[0]用dst_pe idx[0]表示，simd_mode[1]用extra_fields【0】[0]表示，8bit/16bit的偏移用
extra fields【1】[1:0]表示;
simd_ mode[1:0]=0 multiple 32x32bits模式
simd mode[1:0]=1 multiple 16x64bits模式
simd_ mode[1:0]=2 multiple 64x16bits模式
simd_ mode[1:0]=3 multiple 128x8bits模式
```

## image64.png

- size: 1258x687
- psm: 6
- tags: encoding, zh
- text_score: 172

![image64.png](../media/image64.png)

```text
ILDMT Fe Ricore
imm 4Bytes 地址偏移
dst_pe_idx[0] = 数据类型
dst_pe_idx[:1] (n+1)*4Bytes 硬件指令间偏移
4Bytes
硬fHS0 Ft it ttt ft
oe Pte tt ttt
硬件指S2 [| | | | | imm =o
硬件指令3 8 [| tT tT fF ast. pe ia = (-1<<1) 0
px ttt Tt Tt
[TEEPE TT
simd128 Lt ttt ft tt
LEE EEET
spm数据
```

## image65.png

- size: 1260x691
- psm: 6
- tags: encoding, zh
- text_score: 159

![image65.png](../media/image65.png)

```text
ILDMT Fe Ricore
imm 4Bytes 地址偏移
dst_pe_idx[0] = 数据类型
dst_pe_idx[:1] (n+1)*4Bytes 硬件指令间偏移
4Bytes
硬fHS0 Pte ttt ft
而伯指人1 Lt yy yy yy
硬件指S2 [| | | | | imm =o
硬件指令3 8 [| astpe jax = (o<<t)) 0
pot ttt tt
(| |] | | yy
simd128 Pi}, ty
Litt? TT yy
spm数据
```

## image66.png

- size: 1262x708
- psm: 6
- tags: encoding, zh
- text_score: 171

![image66.png](../media/image66.png)

```text
ILDMT re RICORE
imm 4Bytes 地址偏移
dst_pe_idx[0] - 数据类型
dst_pe_idx[:1] (n+1)*4Bytes 硬件指令间偏移
4Bytes
醒作指0 Ft tt ey tt
aoe : |} ttt tt yt
硬件指S2 [| | | | | imm =o
BESS 0 FETT ext ne iax= ren 10
px ttt Tt Tt
LPT Tt yyy
simd128 Pt tt tt ty
LET TTT TT
spm数据
```

## image67.png

- size: 1297x717
- psm: 11
- tags: encoding, zh
- text_score: 388

![image67.png](../media/image67.png)

```text
|simd_modefo]用dst_pe idx[0]表示，simd_mode[l]用extra_fields [0] [0]表示，8bit/16bit的偏移用extra fields [1] [1:0]
表示;
ILDMT
simd_mode[101=1 multiple 16x64bits模式
|simd_mode[101=0 multiple 32x32bits模式
RICORE
simd_mode(1:0]=2 multiple 64xl6bits模式
|simd_mode[l01=3 multiple 128x8bits模式
imm
4Bytes
地址偏移
-
dst_pe_idx[0]
数据类型
dst_pe_idx[:1]
(n+1)*4Bytes
硬件指令间偏移
1Bytes
硬件指令0
1024bits
硬件指令1
1024bits
imm =0
硬件指令2
1024bits
dst_pe_idx = (-1<<1)10
extra_fields [0] [0] =1
硬件指令3
1024bits
fp16
extra_fields [2] [1:0] = 1
spm数据
```

## image68.png

- size: 1308x722
- psm: 11
- tags: encoding, zh
- text_score: 386

![image68.png](../media/image68.png)

```text
simd_modef0]用dst_pe_idx[0]表示，simd_mode[1]用extra_fields【0】[0]表示，8bit/16bit的偏移用extra_fields [1] [1:0]
表示;
multiple 32x32bits模式
ILDMT
simd_mod
simd_mode[l01=0
1
multiple 16x64bits模式
simd_mode[10]=2
multiple 64x16bits模式
RE
|simd_mode[1:0]=3
multiple 128x8bits模式
imm
4Bytes
地址偏移
dst_pe_idx[0]
-
数据类型
dst_pe_idx[:1]
(n+1)*4Bytes
硬件指令间偏移
1Byte
1024bits
硬件指令0
硬件指令1
1024bits
imm =0
硬件指令2
1024bits
dst_pe_idx = (-1<<1)11
extra_fields [0] [0] =1
硬件指令3
1024bits
fp8
extra_fields [2] [1:0] = 2
simd128
spm数据
```

## image69.png

- size: 403x161
- psm: 6
- tags: low-signal
- text_score: 232

![image69.png](../media/image69.png)

```text
SLDSHIF,SLDSHIF8,, ,Kernel8,16,0,0
SLDSHIF ,SLDSHIF9, , ,Kernel9,17,128,0
SLDSHIF ,SLDSHIF10, , ,Kernel10, 18,256,
SLDSHIF ,SLDSHIF11,, ,Kernel11, 19,384,
SLDSHIF ,SLDSHIF12, , ,Kernel12,20,512,0
SLDSHIF , SLDSHIF13,, ,Kernel13,21,640,0
SLDSHIF ,SLDSHIF14, , ,Kernel14,22,768,0
SLDSHIF ,SLDSHIF15, , .Kernel15,23,896,0
```

## image70.png

- size: 1130x492
- psm: 6
- tags: encoding, zh
- text_score: 154

![image70.png](../media/image70.png)

```text
SLDSHIFT ré Ricc
2m 单位 作用 |
imm 4Bytes 地址偏移
dst_pe_idx[2:0] 4Bytes Shift_No
dst_pe_idx[8:3] 4Bytes Shift_cnt
9 0-加上和暂存的地址偏移， =
est-pe texte] 1 BE PRICE,
(n+1)*32*4Bytes 、
dst_pe_idx[:10] (n+1)*1024bits 硬件指令间偏移
```

## image71.png

- size: 592x130
- psm: 11
- tags: zh
- text_score: 313

![image71.png](../media/image71.png)

```text
ve yp tte mm ere
摊作数0的simad0分量的[13:0]比特 = {Ext flag.Ext_offset[1:0] Regid_off[1:0]. double mark,
Maskregno[7:5,mask_val[4:0}
1) double mark: 指示-是天开启双simd分重写回模式
2)
Maskregno[7:5]:
要填入mask0到mask7的8个中的哪个寺存袁
3)
mask_val[4:0]: 表示要填入mask暂存咒的值，对应32bit分重粒度
14)
5)
Regid_off[1:0|: 表示SIMD128/64/32樟式下寺存句编号偏移
a)
Ext_offset[1:0}: 表示8bit分重素引，与mask_val[4:0]组合使用
Ext flan: En hn组入伟用 36558/16/29/eahit4>we EGS. Bike words be
```

## image72.png

- size: 515x91
- psm: 11
- tags: zh
- text_score: 61

![image72.png](../media/image72.png)

```text
H
MASK暂存器
|
{Ext_flag, Ext_offset[1:0],Regid_off{1:0],double_mark,mask_val[4:0]}
H
```

## image73.png

- size: 480x261
- psm: 6
- tags: low-signal
- text_score: 289

![image73.png](../media/image73.png)

```text
) MUL,MUL28 ,DOUBLE_SIMD_0,N256,TMP3,, ,0
| ADD, ADD29, TMP4, TMP3, TMP4add3, , ,9
> ASR, ASR30, rInstO,N1,rInstDiv2,,,0
3 MUL,MUL31, rInstDiv2,N2,rInstDiv2Mul2,, ,0
| ADD, ADD32, rInstDiv2Mul2, TMP4add3,TMP101,, ,9
> MUL,MUL33,N@,N32,TMP2,,,0
5 ADD, ADD34,TMP101,TMP2,mask0,, ,9
7 ASK ,MASK35 ,maskg 2330
3 MUL,MUL36,N1,N32,TMP2,,,0
) ADD, ADD37,TMP101, TMP2,mask1,, ,0
) MASK ,MASK38 maski, ,,,,0
| MUL,MUL39,N2,N32,TMP2,,,0
—
```

## image74.png

- size: 1517x442
- psm: 6
- tags: zh
- text_score: 251

![image74.png](../media/image74.png)

```text
Extflag, double_mark==00
(CT simi PT
#4 ‘
7 N
44 Ae
5 AN
“ ‘
“ SS,
四 AN
Ext_flag,double_mark==00，这两位生效优先级最高，意指取最终取到的一定是32位数据.
1024bit分成32个32bit，val (4: 0) 只能取0-31
reg_idx位为取4个reg的哪一个reg，= =01章指取第2个reg
然后在第二个reg内取32位数据，怎么取:
1, val (4: 0) 位为取哪一个simd分量，比如00011，是了编号3的simd分量
2、ext_offset位，在编号3的分量基础上生效，偏移0/1/2/3个8bit，来取32bit数据。
```

## image76.png

- size: 1506x557
- psm: 6
- tags: zh
- text_score: 267

![image76.png](../media/image76.png)

```text
Extflag，double mark==10
& a
3 =
LT LT nan T T
Va N.
7 NY
J AN
7 \
a \
va \
(Tae TT |] Re Oo
[L_ Tastl | (4: 0) BRB: 0-31
S%
53
Ext_flag,double_mark==10，这两位生效优先豚最高，意指取最终取到的一定是8位数据.。
reg_idx们为取4个reg的哪一个reg，= =01意指取第2个reg
然后在第二个reg内取8们数据，怎么取:
1, val (4: 0) 位为取哪一个simd分量，比如00011，是取编号3的simd分量
2、ext_offset位，在编号3的分量生础上生效，信称0/1/2/3个8bit，来取8bit数据。
比如==01，夫示信物8bit，取8bit的数据，
```

## image77.png

- size: 1531x512
- psm: 6
- tags: zh
- text_score: 272

![image77.png](../media/image77.png)

```text
Ext_flag, double_mark==11
é &
名 2
TT sing T T |
cf NS，
rl AN
/ N
a SS,
/ 、
7 .
a NY
ee ea T 1 aE et
L_ Tris [ (4: 0) 取值: 0-31
Se
Ext flag.double_mark==11, 这两位生效优先级最高，意措取最终取到的一十是16位数据.
reg_idx们为取4人reg的哪一人reg，==01意指取第2个reg
然后在第二个reg内取16位数据，怎么取:
1、val (4: 0) 位为取电一个simd分县，比各00011，是到编号3的simd分量
2、ext_offset位，在六号3的分量基础上生效，信移0/1/2/3个8bit，来取16bit数据。
比如==01，夫示信物8bit，取16bit的数据.
```

## image78.png

- size: 297x165
- psm: 11
- tags: low-signal
- text_score: 131

![image78.png](../media/image78.png)

```text
Too5LLI27， AL
HSTT,HSTT58，,,A1, ,128,1,2
HSTT,HSTT59,，,A1, ,256,1,3
HSTT,HSTT60, , ,A1, ,384,1,4
HSTT,HSTT61, , ,A1, ,512,1,5
HSTT,HSTT62, , ,A1, ,640,1,6
HSTT,HSTT63, , ,A1, ,768,1,7
MisTT HSTT64,, .A1, .896,1,8
```

## image79.png

- size: 352x97
- psm: 6
- tags: low-signal
- text_score: 86

![image79.png](../media/image79.png)

```text
GSTT.HSTT5,, ,rOUTPUTO,0,0,1
HSTT,HSTT6, , ,rOUTPUT1,0, 128, 1
HSTT,HSTT7, , ,rOUTPUT2,0,256,1
HSTT,HSTTS, , ,rOUTPUT3, 0,384, 1
```

## image80.png

- size: 1195x622
- psm: 11
- tags: encoding, zh
- text_score: 163

![image80.png](../media/image80.png)

```text
HSTT
1 RICORE
Imm
ABytes
地址偏移
dst_pe_idx
(n+1)*32*4Bytes
硬件指令间偏移
(n+1)*1024bits
128
1024bits
硬件指令0
1024bits
32*4Bytes
硬件指令1
1024bits
硬件指令2
1024bits
imm = 0
1024bits
dst_pe_idx = 0
硬件指令3
fp16
simd128
spm数所
```

## image81.png

- size: 1165x613
- psm: 11
- tags: encoding, zh
- text_score: 155

![image81.png](../media/image81.png)

```text
HSTT
r¢ RIcoRE
imm
ABytes
地址偏移
dst_pe_idx
(n+1)*32*4Bytes
硬件指令间偏移
(n+1)*1024bits
128
1024bits
硬件指令0
1024bits
硬件指令1
1024bits
imm = 0
硬件指令2
1024bits
硬件指令3
1024bits
dst_pe_idx = 1
fp16
simd128
spm数所
```

## image82.png

- size: 1175x642
- psm: 11
- tags: encoding, zh
- text_score: 158

![image82.png](../media/image82.png)

```text
HSTT
Fe RiIcoRe
Imm
ABytes
地址偏移
dst_pe_idx
(n+1)*32*4Bytes
硬件指令间偏移
(n+1)*1024bits
128
32*4Bytes
硬件指令0
1024bits
硬件指令1
1024bits
imm = 32
硬件指令2
1024bits
硬件指令3
1024bits
dst_pe_idx = 1
fp16
simd128
spm数所
```

## image83.png

- size: 1158x615
- psm: 11
- tags: encoding, zh
- text_score: 148

![image83.png](../media/image83.png)

```text
HSTT
Fe RICORe
Imm
ABytes
地址偏移
(n+1)*32*4Bytes
dst_pe_idx
硬件指令间偏移
(n+1)*1024bits
128
硬件指令0
1024bits
硬件指令1
1024bits
imm = 0
硬件指令2
1024bits
硬件指令3
1024bits
dst_pe_idx = 3
|
fp16
simd128
spm数所
```

## image84.png

- size: 1168x627
- psm: 11
- tags: encoding, zh
- text_score: 148

![image84.png](../media/image84.png)

```text
HSTT
Fe RICORE
Imm
ABytes
地址偏移
dst_pe_idx
(n+1)*32*4Bytes
硬件指令间偏移
(n+1)*1024bits
128
硬件指令0
1024bits
硬件指令1
1024bits
硬件指令2
1024bits
imm = 0
1024bits
dst_pe_idx = -1
硬件指令3
fp16
simd128
spm数所
```

## image85.png

- size: 1223x759
- psm: 11
- tags: encoding, zh
- text_score: 169

![image85.png](../media/image85.png)

```text
HSTT
re RICORE
imm
4Bytes
地址偏移
(n+1)*32*4Bytes
硬件指令间偏移
dst_pe_idx
(n+1)*1024bits
0: KE Amasks et
extr_feild[0]
1-8: 结合mask寄存器，mask编号
从1开始，一共8个mask寄存器
128
硬件指令0
硬件指令1
硬件指令2
imm =0
=
dst_pe_idx
= -
硬件指令3
fp16
simd128
Spm数据
```

## image86.png

- size: 387x162
- psm: 6
- tags: low-signal
- text_score: 224

![image86.png](../media/image86.png)

```text
SBTSHIF,SSTSHIF64,, ,Kernel0,64,0,1,1
SSTSHIF ,SSTSHIF65, , ,Kernel1,65,0,1,1
SSTSHIF ,SSTSHIF66, , ,Kernel2,66,0,1,1
SSTSHIF ,SSTSHIF67, , ,Kernel3,67,0,1,1
SSTSHIF ,SSTSHIF68, , ,Kernel4,68,0,1,1
SSTSHIF ,SSTSHIF69, , ,Kernel5,69,0,1,1
SSTSHIF ,SSTSHIF70, , ,Kernel6,70,0,1,1
SSTSHIF ,SSTSHIF71,, ,Kernel7,71,0,1,.1
```

## image87.png

- size: 507x197
- psm: 6
- tags: low-signal
- text_score: 137

![image87.png](../media/image87.png)

```text
1,,,Kernel0,0,0,1
， 2,,,Kernel0,128,128,1
， 3,,,Kernel0,129,256,1
， 4，，,KerneL9,130,384，,1
， 5,,,Kernelo, 131,512,1
， 6,,,KernelO,132,640,1
， 7，，,KerneL9,133,768,1
， 8,,,KernelO, 134,896,1
， 9，，,KernelL9,135,1924,1
ee eg
```

## image88.png

- size: 1271x317
- psm: 11
- tags: zh
- text_score: 177

![image88.png](../media/image88.png)

```text
dst_pe_idx[10:9]=0x00:regidx索引，选择regidx=0的寄存器;
dst_pe_idx[6:5]: [high,low]=0x01;
dst_pe_idx[4:0]: 0x00000
dst_pe_idx[8:7]: 0x01
写回regidx寄存器内最高的128-1个分量，编号大于此寄存器的其它寄存器全部写回。 如下疼中黄色部分所未，
Regidx 3
Regidx 2
Regidx 1
Regidx 0
Po 国
```

## image89.png

- size: 1283x362
- psm: 6
- tags: zh
- text_score: 174

![image89.png](../media/image89.png)

```text
dst_pe_idx[10:9]=0x00:regidx索引，选择regidx=0的寄存器;
dst_pe_idx[6:5]: [high,low]=0x10;
dst_pe_idx[4:0]: 0x00000
dst_pe_idx[8:7]: 0x01
写回regidx寄存器内最低的128-1个分量，编号小于此寄存器的其它寄存器全部写回。 如下图中黄色部分所示:
Regidx 3 Regidx 2 Regidx 1 Regidx 0
```

## image90.png

- size: 1464x1197
- psm: 11
- tags: encoding, zh
- text_score: 1033

![image90.png](../media/image90.png)

```text
1) 把4个Rx寄存器128*32bits的数截断成128*8bits|，拼接方式|
imm==0[) |results的第1个1924bit = Rx6截断 results的第2个1924biit
=
=
Rx1截断
results的第3个1924bit = Rx2截断 results的第4个1924biit
=
=
Rx3截断
2) |把4个Rx寄存器128*32bits的数截断成128*8bitsl，昱接方式 |
imm==1: results的第1个19624bit=Rx3_6[31],Rx2_6[31],Rxl 6e[31],Rxe_e[31]，
, Rx3_@[0],Rx2_@[0],Rx1_@[2],Rx@_@[2]
resultsfJ#21024bit=Rx3_1[31],Rx2_1[31],Rx1_1[31],Rx@_1[31],
, Rx3_1[@],Rx2_1[@],Rx1_1[@],Rx@_1[2]
resultsfJ#31024bit=Rx3_2[31],Rx2_2[31],Rx1_2[31],Rx@_2[31],
, Rx3_2[@],Rx2_2[@],Rx1_2[0],Rx@_2[2]
resultsfJ#841024bit=Rx3_3[31],Rx2_3[31],Rx1_3[31],Rx@_3[31],
, Rx3_3[0],Rx2_3[@],Rx1_3[0],Rx@_3[2]
3) 用于QMADp之后
for(i = 6; i < 32; i++)
if(imm == 2){
//用Rx的第1个1924bit分量
results[6] .
simd32[i]
Rx[i%4]
simd32[i/4];
results[1].
simd32[i]
Rx[i%4]
simd32[i/4+8];
results[2].
simd32[i]
Rx[i%4]
simd32[i/4+16];
results[3].
simd32[i]
Rx[i%4]
simd32[i/4+24];
Jelse if (imm
== 4){
//用Rx的第2个1624bit分
=
Ss
results[6] .
simd32[i]
Rx[i%4]
simd32[i/4];
results[1].
simd32[i]
Rx[i%4]
simd32[i/4+8];
results[2].
simd32[i]
Rx[i%4]
simd32[i/4+16];
results[3].
simd32[i]
Rx[i%4]
simd32[i/4+24];
Jelse if (imm
== 8){
//用Rx的第3个1624bit分
=
Ss
results[6] .
simd32[i]
Rx[i%4]
simd32[i/4];
results[1].
simd32[i]
Rx[i%4]
simd32[i/4+8];
results[2].
simd32[i]
Rx[i%4]
simd32[i/4+16];
results[3].
simd32[i]
Rx[i%4]
simd32[i/4+24];
}else if(imm == 16){
//用Rx的第4个1624bit分
=
Ss
results[6] .
simd32[i]
Rx[i%4]
simd32[i/4];
results[1].
simd32[i]
Rx[i%4]
simd32[i/4+8];
results[2].
simd32[i]
Rx[i%4]
simd32[i/4+16];
results[3].
simd32[i]
Rx[i%4]
simd32[i/4+24];
yelse{
results[6] .
simd32[i]
Q;
```

## image91.png

- size: 959x190
- psm: 11
- tags: low-signal
- text_score: 63

![image91.png](../media/image91.png)

```text
results[@].simd32[i]
8;
results[1].simd32[i]
8;
results[2].simd32[i]
8;
results[3].simd32[i]
8;
```

## image92.png

- size: 317x82
- psm: 6
- tags: low-signal
- text_score: 89

![image92.png](../media/image92.png)

```text
TRCT8, TRCT816, , ,rOUTPUTO, ,2,0
TRCT8,TRCT817,,,rOUTPUT1, 4,0
TRCT8, TRCT818, , ,rOUTPUT2, ,8,0
TRCT8,TRCT819, , , rOUTPUT3, ,16,0
```

## image93.png

- size: 920x155
- psm: 6
- tags: encoding, semantics
- text_score: 291

![image93.png](../media/image93.png)

```text
imm==0: Val(Operand index 2) = int32( Val(Operand index0)(0)[7:0], ..., Val(Operand index0)(31)[7:0] )
imm==1: Val(Operand index 2) = int32( Val(Operand index0)(0)[15:8], ... , Val(Operand index0)(31)[15:8] )
imm==2: Val(Operand index 2) = int32( Val(Operand index0)(0)[23:16], ... , Val(Operand index0)(31)[23:16] )
imm==3: Val(Operand index 2) = int32( Val(Operand index0)(0)[31:24], ..., Val(Operand index0)(31)[31:24] )
32bits*simd32_ <= 8bitsrsimd32
```

## image94.png

- size: 363x82
- psm: 6
- tags: low-signal
- text_score: 108

![image94.png](../media/image94.png)

```text
EXPD32,EXPD321, Inst, , rOUTPUTO, ,0,0
EXPD32, EXPD322, Inst, ,rOUTPUT1, ,1,0
EXPD32, EXPD323, Inst, , rOUTPUT2, ,2,0
EXPD32, EXPD324, Inst, , rOUTPUT3, ,3,0
```

## image95.png

- size: 693x50
- psm: 6
- tags: encoding, semantics
- text_score: 85

![image95.png](../media/image95.png)

```text
{Rx3,Rx2,Rx1,Rx0} += Value(Operand index 0) * Value(Operand index 1)
32bits*simd128 8bits*simd128 8bits*simd128
```

## image96.png

- size: 1041x381
- psm: 11
- tags: encoding, semantics, zh
- text_score: 234

![image96.png](../media/image96.png)

```text
{Rx3,Rx2,Rx1,Rx0}
+=
Value(Operand index 0) * Value(Operand index 1)
32bits*simd128
8bits*simd128
8bits*simd128
只支持无符号uint8 的计算
ae
QMADD计算完之后，需
2a
结合:
TRCT8指令，才
He.
拿到正确结果
Rx0[0] += srcO[0]*src1[0]
32bits
8bits*8bits
Rx1[0] += srcO[1]*src1[1]
Rx2[0] += srcO[2]*src1[2]
Rx3[0] += srcO[3]*src1[3]
RxO[1] += srcO[4]*src1[4]
32bits
8bits*8bits
```

## image97.png

- size: 1779x761
- psm: 11
- tags: low-signal
- text_score: 297

![image97.png](../media/image97.png)

```text
Simd128*8bit
Simd128*8bit
SRC1_0
SRCO_O
SRCO_1
SRC1_1
=e
SRCO_2
SRC1_2
coeeeccecneeeeeeeneeeeeeeneeeeetnnseeeeenneeeeeennseeeeeenueeeeeenueeeeeeeeneeeSRCO_3
RS
aaa eee eee eee
—
Src0_0[0]*src1_0[0]+RXO
_0[0]=RXO_0[0]
Simd32*32bit
Simd32*32bit
Simd32*32bit
RX0_0
RX1_0
RX2_0
RX3_0
RXO_1
RX1_1
RX2_1
RX3_1
RXO_2
RX1_2
RX2_2
RX3_2
RXO_3
RX1_3
RX2_3
RX3_3
```

## image98.png

- size: 327x22
- psm: 6
- tags: semantics
- text_score: 24

![image98.png](../media/image98.png)

```text
QMADD ,QMADD7 , Inst00,Inst10,,,,0
```
