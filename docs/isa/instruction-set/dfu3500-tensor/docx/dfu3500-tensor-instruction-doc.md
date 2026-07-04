# DFU3500 Tensor 指令集 docx Extract

Source: `tmp/华科算子库编写/（这个文档先不看）DFU3500-tensor指令集.docx`

This markdown preserves the document order. Embedded images are represented by OCR text blocks; the original Office/image files remain outside git.

## RXINT

**Source operand:**

Operand index 0

**Destination operand:**

**Function:**

将Operand index 0的数据存放到暂存器内，并且可以进行数据类型转化。

imm[4:0]设置暂存器编号，

imm[7:5]设置数据类型转换模式。

如下图，将寄存器内的int8数据存放入暂存器内，并将数据转化成int32：

### Image 1: image1.png

Source image in docx: `word/media/image1.png`

```text
[jh | 人值 | 人作 |
imm[4:0]                    0-15                  16个暂存器
imm{7:5]                    0-6                  数据类型转换
Ro                          src_reg_idx0 : RO                  on moines
R1                        imm[4:0] : 0 (0-3)                1: fp8一fp16
2: fp8—fp32
R2          4096bits            imm[7:5] : 0 (int8—int32)             3: fp16—fp32
R3                                                                                4: fp32—fp32
5: uin8-uint32
int8                                                  6: int32—int32
int32            16个暂存器
```

四个橘色的暂存器存放R0中的数据。（在此类存放模式下，四个橘色的暂存器可看成一个大暂存器，共有4个大暂存器，因此可用暂存器编号为0-3。）

### Image 2: image2.png

Source image in docx: `word/media/image2.png`

```text
[jh | 人值 | 人作 |
imm[4:0]                    0-15                  16个暂存器
imm[7:5]                    06                  数据类型转换
RO                          src_reg_idx0 : R1                  oa
R1                     imm[4:0] : 1 (0-3)              1: fp8一fp16
2: fp8—fp32
R2          4096bits            imm[7:5] : 0 (int8—int32)             3: fp16—fp32
R3                                                                                4: fp32—fp32
5: uin8uint32
int8                                                  6: int32—int32
int32            16个暂存器
```

四个黄色的暂存器存放R1中的数据。

### Assembly Code

寄存器中fp32数据存放到暂存器中，暂存器中数据为fp32：

### Image 3: image3.png

Source image in docx: `word/media/image3.png`

```text
for (int i = 0; i < 16; i++)
{
fprintf(fploldindex], "RXINT,RXINT%d,gemm@ output %d_%d,,,,%d,0\n",
count[oldindex]++, 0, i, (4 << 5) | (i & Oxlf));
+
```

### Image 4: image4.png

Source image in docx: `word/media/image4.png`

```text
RXINT, RXINT32,gemm0_output0_0_0,,,,128,0
RXINT, RXINT33, gemm@_output0_@ 1,,,,129,0
RXINT, RXINT34, gemmO_output0_0 2,,,,130,0
RXINT, RXINT35, gemmO_output0_6 3,,,,131,0
RXINT, RXINT36, gemm0_output0_0_4,,,,132,0
```

## TRCTT

**Source operand:**

**Destination operand:**

Operand index 2

**Function:**

将暂存器的数据存放到Operand index 0内，并且可以进行数据类型转化（一般与RXINT成对出现）。

imm[3:0]设置暂存器编号，

imm[6:4]设置数据类型转换模式。

如下图，将暂存器内的fp32数据存放入寄存器内，并将数据转化成fp16：

### Image 5: image5.png

Source image in docx: `word/media/image5.png`

```text
TRCTT                                           Te RICORE
[并 | B值 | 人 |
imm[3:0]                  0-15                 16个暂存器
imm[6:4]                   0-5                 数据类型转换
imm[6:4]=
RO          4096bits           dst_reg_idx : R1                      0: int32—int8
1     .01 -     _                        1: fp16—fp8
R1                       imm(3:0] : 0 (0-7)                  a eee
R2          4096bits           imm[6:4] : 3 (fp32一fp16)               3: fp32—fp16
                                         se inna tata
R3          全                                               5: int32一int32
fp16
{p32           16个暂存器
```

将两个浅橘色暂存器中存放到数据放入寄存器R0中，浅黄色暂存器中存放的数据放入寄存器R1中，……。（在此类存放模式下，了，两个小暂存器可看成一个大暂存器，共有8个大暂存器，因此可用暂存器编号为0-7。）

### Assembly Code

暂存器中fp32数据存放到寄存器中，寄存器器中数据为fp32：

### Image 6: image6.png

Source image in docx: `word/media/image6.png`

```text
for (int i = 0; i < 16; i++)
{
fprintf(fp[oldindex], “TRCTT,TRCTT%d,,,gemmO outputO_%d_%d,,%d,0\n",
count[oldindex]++, 0, i, (4 << 4) | (i & OxOf));
+
```

### Image 7: image7.png

Source image in docx: `word/media/image7.png`

```text
TRCTT,TRCTT304,，,gemmg_output9 0 90,,64,9
TRCTT, TRCTT305,, ,gemm@_output@ 01, ,65,0
TRCTT, TRCTT306,, ,gemm@_output@ 0 2, ,66,0
TRCTT, TRCTT307,, ,gemm@_output@ 0 3, ,67,0
TRCTT, TRCTT308, , ,gemm0_output0 0 4, ,68,0
```

## IMMA

**Source operand:**

Operand index 0 ,Operand index 1

**Destination operand:**

**Function:**

计算int8*int8+int32，将结果放入暂存器内。

imm[2:0]设置base矩阵大小：

0: base4x4

1: base8x8

2:base16x16

3:base32x32

4: base64x64

5: baseAI64

6: base sparse

7: base128x128

imm[7:3]设置计算模式：

0: data_select_type0

1: data_select_type1

2: data_select_type2

3: data_select_type3

…

31: data_select_type31

imm[9:8]设置暂存器编号(暂存器内只存放int32的数据)：

0: dst用tmp0

1: dst用tmp1

2: dst用tmp2

3: dst用tmp3

如下图，计算base8x8的矩阵，计算模式1，存放在1号暂存器

### Image 8: image8.png

Source image in docx: `word/media/image8.png`

```text
RO                                                             imm[2:0]=
R1                       src_reg_idx0 : RO             0: imma.

-            src_reg_idx1: R1              name
re        sores          imm{8:0] : (1<<8) | (1<«3) | 1      3: immaa2
R3                   4096bits                                         “                                        4: imma.64

int8                           base8 8                            5:imma.Al64
6: imma sparse
7: imma.128
int32           16个暂存器
```

### Image 9: image9.png

Source image in docx: `word/media/image9.png`

```text
8                    8
simd128，一条IMMA计算32个4*4和矩阵乘
8*8矩阵乘中含8次4*4和矩阵乘
8                    8                      4096bits含8个8*8规模的int8矩阵

需要64次4*4和矩阵乘
2种计算模式 (ae af ce cf，bg bh dg dh)

ae bg

af bh

ce dg

cf dh
```

### Assembly Code

base128x128，使用暂存器0~3，计算模式0~3：

### Image 10: image10.png

Source image in docx: `word/media/image10.png`

```text
for (j = 9; j < 32; j++){
fprintt(fp, "IMMA, IMMA%d,MATRIXAQO,MATRIXBO%d,, ,%d,@\n", j*4+0, j，((9 << 8)1(j << 3)17));
fprintt(fp, "IMMA, IMMA%d,MATRIXAQ1,MATRIXBO%d,,,%d,0\n", j*4+1, Jj, ((1 << 8)|(j << 3)17));
fprintf(fp, "IMMA, IMMA%d,MATRIXAQ2,MATRIXBO%d,, ,%d,@\n", j*44+2, Jj, ((2 << 8)|(j << 3)17));
fprintt(fp, "IMMA, IMMA%d, MATRIXAQ3,MATRIXBO%d,, ,%d,@\n", #443, Jj, ((3 << 8)1(j << 3)17));
+
```

j=0时，会打印出

### Image 11: image11.png

Source image in docx: `word/media/image11.png`

```text
IMMA, IMMAO ,MATRIXAOO ,MATRIXBOO, ,,7,0

IMMA, IMMA1,MATRIXAQ1,MATRIXBOO, , , 263, 0
IMMA, IMMA2 , MATRIXAQ2, MATRIXBOO, , ,519, 0
IMMA, IMMA3, MATRIXAQ3, MATRIXBOO, , ,775,0
```

## IMMAU

**Source operand:**

Operand index 0 ,Operand index 1

**Destination operand:**

**Function:**

计算uint8*uint8+uint32，将结果放入暂存器内。

imm设置与IMMA相同。

### Assembly Code

### Image 12: image12.png

Source image in docx: `word/media/image12.png`

```text
IMMAU , IMMAUO , MATRIXAQO , MATRIXBOO, , ,7,0

IMMAU, IMMAU1, MATRIXAQ1, MATRIXBOO, , ,263, 0
IMMAU,, IMMAU2 , MATRIXAQ2, MATRIXBOO, , ,519,0
IMMAU, IMMAU3 , MATRIXAQ3,MATRIXBOO, , ,775,0
```

## IMMAIU

**Source operand:**

Operand index 0 ,Operand index 1

**Destination operand:**

**Function:**

计算int8*uint8+int32，将结果放入暂存器内。

imm设置与IMMA相同。

### Assembly Code

### Image 13: image13.png

Source image in docx: `word/media/image13.png`

```text
IMMALIU, IMMAIUO , MATRIXAQO , MATRIXBOO, , ,7,0

IMMAIU, IMMAIU1, MATRIXAQ1, MATRIXBOO, , , 263, 0
IMMAIU, IMMAIU2 , MATRIXAQ2, MATRIXBOO, , ,519, 0
IMMAIU, IMMAIU3, MATRIXAO3,MATRIXBOO, , ,775,0
```

## IMMAUI

**Source operand:**

Operand index 0 ,Operand index 1

**Destination operand:**

**Function:**

计算uint8*int8+int32，将结果放入暂存器内。

imm设置与IMMA相同。

### Assembly Code

### Image 14: image14.png

Source image in docx: `word/media/image14.png`

```text
IMMAUI , IMMAUIO ,MATRIXA6 ,MATRIXBO, , ,0,0

IMMAUL, IMMAUI1, MATRIXA1, MATRIXB1, , ,256,0
IMMAUI, IMMAUI2 , MATRIXA2 , MATRIXB2, , ,512,0
IMMAUL , IMMAUI3 , MATRIXA3 , MATRIXB3, , , 768, 0
```

## HMMA

**Source operand:**

Operand index 0 ,Operand index 1

**Destination operand:**

**Function:**

计算fp16*fp16+fp32，将结果放入暂存器内。

simd128模式下，一条HMMA计算8个4*4矩阵乘

imm[1:0]设置base矩阵大小：

0:base4x4

1:base8x8

2: base16x16

3: base32x32

imm[2]设置A数组的前一半/后一半数据：

0: Matrix A-[2047:0]

1: Matrix A-[4095:2048]

imm[3]设置B数组的前一半/后一半数据：

0: Matrix B-[2047:0]

1: Matrix B-[4095:2048]

imm[6:4]设置计算模式：

0: data_select_type0

1: data_select_type1

2: data_select_type2

3: data_select_type3

…

7: data_select_type7

imm[9:7]设置暂存器编号：

0: dst用tmp0

1: dst用tmp1

2: dst用tmp2

3: dst用tmp3

4: dst用tmp4

5: dst用tmp5

6: dst用tmp6

7: dst用tmp7

如下图，imm[8:0]表示了计算base4x4的矩阵，计算A数组前一半，计算B数组前一半，存放在0号暂存器(因为只有一种计算模式，所以为默认值）：

### Image 15: image15.png

Source image in docx: `word/media/image15.png`

```text
RO
R1                             src_reg_idx0 : RO                    imm[1:0]=
-              src_reg_idx1 : R1                    0: hmma.4
Re      imm[8:0] : (0<<7) (0<<3)|(0<<2)I0        1 hmma.8
R3           4096bits                  base 4x4                          2: hmma.16
fp16                                                                      3: hmma.32
fp32           16个暂存器
```

### Assembly Code

以每个PE计算128x4x4的矩阵乘为例，每个寄存器可以存放16x4x4的矩阵，每个矩阵需要8个寄存器来存储，每个寄存器内存放的数据如下图所示：

### Image 16: image16.png

Source image in docx: `word/media/image16.png`

```text
Operand index 0                  Operand index 1
```

计算A数组和B数组前一半（上图的浅绿浅紫色部分。上图只表示1个寄存器，共有8个寄存器）需要8条HMMA，每条HMMA的计算结果存储在一个暂存器内，因此会使用8个暂存器：

### Image 17: image17.png

Source image in docx: `word/media/image17.png`

```text
for (int i= 0; i< 8; i ++){
fprintf(fp, "HMMA, HMMA%d, MATRIXA%d,MATRIXB%d,, ,%d,0\n", i, i, i, ((i<<7)| (O<<3) | (0<<2) |)
+
for (int i= 0; i< 8; i ++){
fprintt(fp, "HMMA, HMMA%d, MATRIXA%d,MATRIXB%d, , ,%d,0\n", i+8, i, i, ((i<<7)|(1<<3) | (1<<2)|0))
```

### Image 18: image18.png

Source image in docx: `word/media/image18.png`

```text
HMMA, HMMAO ,MATRIXAO , MATRIXBO,, ,0,0

HMMA, HMMA1, MATRIXA1, MATRIXB1, , ,128,0
HMMA, HMMA2 , MATRIXA2 , MATRIXB2, , ,256,0
HMMA , HMMA3 , MATRIXA3 , MATRIXB3, , ,384,0
HMMA, HMMA, MATRIXA4 , MATRIXB4, , ,512,0
HMMA, HMMAS , MATRIXAS , MATRIXB5, , ,640,0
HMMA, HMMA6 , MATRIXAG , MATRIXB6, , , 768,0
HMMA, HMMA7 , MATRIXA7, MATRIXB7, , ,896, 0
```

计算A数组和B数组后一半（上图的深绿深紫色部分）需要8条HMMA，每条HMMA的计算结果存储在一个暂存器内，因此会使用8个暂存器：

### Image 19: image19.png

Source image in docx: `word/media/image19.png`

```text
for (int i= 0; i< 8; i ++){
fprintf(fp, "HMMA, HMMA%d, MATRIXA%d,MATRIXB%d, , ,%d,0\n", i+8, i, i, ((i<<7)|(1<<3) | (1<<2)|0))
+
```

### Image 20: image20.png

Source image in docx: `word/media/image20.png`

```text
HMMA, HMMA8 , MATRIXAO ,MATRIXB9 , ,12,0

HMMA, HMMAQ, MATRIXA1, MATRIXB1, , ,140,0
HMMA, HMMA10 , MATRIXA2 , MATRIXB2, , ,268,0
HMMA, HMMA11, MATRIXA3 , MATRIXB3, , , 396,
HMMA, HMMA12, MATRIXA4 , MATRIXB4, , ,524,0
HMMA, HMMA13 , MATRIXA5 , MATRIXB5, , ,652,0
HMMA, HMMA14 , MATRIXA6 , MATRIXB6 , , , 780, 0
HMMA, HMMA15 , MATRIXA7 , MATRIXB7, , ,908, 0
```

## HMMAL

**Source operand:**

Operand index 0 ,Operand index 1

**Destination operand:**

**Function:**

imm[1:0]设置base矩阵：

0: hmma.64

1: hmma.sparse

imm[2]设置A数组的前一半/后一半数据：

0:  Matrix A-[2047:0]

1: Matrix A-[4095:2048]

imm[3]设置B数组的前一半/后一半数据：

0: Matrix B-[2047:0]

1: Matrix B-[4095:2048]

imm[6:4]设置计算模式：

0: data_select_type0

1: data_select_type1

2: data_select_type2

3: data_select_type3

…

7: data_select_type7

imm[9:7]设置暂存器编号：

0: dst用tmp0

1: dst用tmp1

2: dst用tmp2

3: dst用tmp3

4: dst用tmp4

5: dst用tmp5

6: dst用tmp6

7: dst用tmp7

### Assembly Code

以64X64矩阵乘为例，AB数组分区如下图所示，其中浅色部分表示数组的前一半，深色部分表示数组的后一半。

### Image 21: image21.png

Source image in docx: `word/media/image21.png`

```text
64             64
64             64
A             B
```

详细计算过程如下：

（1）

### Image 22: image22.png

Source image in docx: `word/media/image22.png`

```text
*
```

### Image 23: image23.png

Source image in docx: `word/media/image23.png`

```text
for (int i= 0; i < 8; i++) {
for (int j = 0; j < 8; j++) {
fprintt(fp[2], "HMMAL, HMMAL%d, MATRIXA%d , MATRIXB%d, , ,%d,@\n", count[2]++, j, i, ((j << 7)| (i << 4) | (O<<3) | (O<<2) 10)
a
for (int j = 0; j < 8 j++) {
fprintt(fp[2], "HMMAL, HMMAL%d, MATRIXA%d , MATRIXB%d, , ,%d,0\n", count[2]++, j, i, ((j << 7)| (i << 4) | (1<<3) | (O<<2) 10)
+
```

(2)

### Image 24: image24.png

Source image in docx: `word/media/image24.png`

```text
:
```

### Image 25: image25.png

Source image in docx: `word/media/image25.png`

```text
for (int i = 0; i < 8; i++) {
for (int j = 0; j < 8; j++) {
fprintf(fp[2], "HMMAL, HMMAL%d, MATRIXA%d , MATRIXB%d, , ,%d,0\n", count[2]++, j, i+8, ((j << 7)1(i << 4)1(9<<3)1(1<<2)19))
af
for (int j = 0; j < 8; j++) {
fprintt(fp[2], "HMMAL, HMMAL%d, MATRIXA%d , MATRIXB%d, , ,%d,0\n", count[2]++, j, i+8, ((j << 7)1(i << 4)| (1<<3) | (1<<2)|0))
+
}
```

(3)

### Image 26: image26.png

Source image in docx: `word/media/image26.png`

```text
«x
```

### Image 27: image27.png

Source image in docx: `word/media/image27.png`

```text
for (int i = 0; i < 8; i++) {
for (int j = 0; j < 8; j++) {
fprintf(fp[2], "HMMAL, HMMAL%d, MATRIXA%d , MATRIXB%d, , ,%d,0\n", count[2]++, j+8, i, ((j << 7)|(i << 4)1(9<<3)1(9<<2)19))
+
for (int j = 0; j < 8; j++) {
fprintf(fp[2], "HMMAL, HMMAL%d, MATRIXA%d , MATRIXB%d, , ,%d,0\n", count[2]++, j+8, i, ((j << 7)1(i << 4)1(1<<3)1(9<<2)19))
+
}
```

(4)

### Image 28: image28.png

Source image in docx: `word/media/image28.png`

```text
»:
```

### Image 29: image29.png

Source image in docx: `word/media/image29.png`

```text
for (int i= 0; i < 8; i++) {
for (int j = 0; j < 8; j++) {
fprintt(fp[2], "HMMAL, HMMAL%d, MATRIXA%d , MATRIXB%d, , ,%d,0\n", count[2]++, j+8, i+8, ((j << 7)| (i << 4) |(O<<3) | (1<<2)]0))
+
for (int j = 0; j < 8 j++) {
fprintt(fp[2], "HMMAL, HMMAL%d, MATRIXA%d , MATRIXB%d, , ,%d,0\n", count[2]++, j+8, i+8, ((j << 7)| (i << 4) | (1<<3) | (1<<2)]0))
+
}
```

i=0时，采用第一种计算模式，计算与数据存放区域如下图所示：

### Image 30: image30.png

Source image in docx: `word/media/image30.png`

```text
32            64
4 |    4(T YET iit
|    a |
|    a |
a |    re |
 Ee
|    |
HL |    上 |
CCL |    L_ |
A             B
B数组前一半
B数组后一半
i=0 第一种计算模式:                            -| tmpo
“A...    tmp1
j=0                               L
ist                                十
2
日  tmp7
```

i=1时，采用第一种计算模式，计算与数据存放区域如下图所示：

### Image 31: image31.png

Source image in docx: `word/media/image31.png`

```text
32           64
2 a   —
Co    Cope
FE |    |
co    —
8 EL 8) Et
co    |
Co    |
co    |
A           B
数组前一半
B数组后一半
i=1 第二种计算模式:                  TT) tmpo
°                             “A...  tmp1
ie
i                            十
j=2
第一种计算模式的结果累加第二种计算模式  [|
的结果存入相应mp        日
日  tmp7
```

生成指令如下图所示（部分）：

### Image 32: image32.png

Source image in docx: `word/media/image32.png`

```text
HMMAL , HMMAL24 , MATRIXAO ,MATRIXB0 ，，,9,9

HMMAL, HMMAL25 , MATRIXA1 , MATRIXBO, , ,128, 0
HMMAL, HMMAL26 , MATRIXA2 , MATRIXBO, , , 256, 0
HMMAL, HMMAL27 , MATRIXA3, MATRIXBO, , , 384, 0
HMMAL, HMMAL28 , MATRIXA4 , MATRIXBO, , ,512, 0
HMMAL, HMMAL29, MATRIXAS , MATRIXBO, , , 640, 0
HMMAL , HMMAL30 , MATRIXA6 , MATRIXBO, , , 768, 0
HMMAL, HMMAL31, MATRIXA7 , MATRIXBO, , ,896, 0
HMMAL , HMMAL32, MATRIXAO , MATRIXBO, , ,8, 0

HMMAL , HMMAL33, MATRIXA1 , MATRIXBO, , , 136, 0
HMMAL, HMMAL34, MATRIXA2 , MATRIXBO, , , 264, 0
HMMAL, HMMAL35 , MATRIXA3 , MATRIXBO, , , 392, 0
HMMAL , HMMAL36 , MATRIXA4 , MATRIXBO, , ,520, 0
HMMAL , HMMAL37 , MATRIXAS , MATRIXBO, , , 648, 0
HMMAL, HMMAL38 , MATRIXA6 , MATRIXBO, , , 776, 0
HMMAL, HMMAL39 , MATRIXA7,MATRIXBO, , ,904,0
```
