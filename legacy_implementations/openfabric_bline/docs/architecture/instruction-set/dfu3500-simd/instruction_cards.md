# DFU3500 SIMD Instruction Cards

## ADD
- category: int arith inst
- docx_typed_view: imm==0: 128 lanes x 32 bits; imm==1: 512 lanes x 8 bits
- docx_family: signed_int_imm_mode
- docx_section: docx/instruction_sections/ADD.md
- operand_view: imm==0: int32[128]; imm==1: int8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: int32 or int8
- view_confidence: documented by docx Int32/Int8 section
- typed_semantics: imm==0: for i in 0..127 operate on signed 32-bit lanes; imm==1: for i in 0..511 operate on signed 8-bit lanes; dst[i] = src0[i] + src1[i]
- function: Value(Operand index 2)  = Value(Operand index 0) + Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## AND
- category: logic inst
- docx_family: special
- docx_section: docx/instruction_sections/AND.md
- operand_view: uint32/bit32[128] over one logical 4096-bit/512-byte operand unless imm selects int8-style mode
- lane_count: 128 or instruction-specific
- lane_dtype: uint32/bit32
- view_confidence: partly inferred; docx gives detailed typed views for arithmetic families
- function: Value(Operand index 2)  = Value(Operand index 0) & Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## ASR
- category: logic inst
- operand_view: int32[128] over one logical 4096-bit/512-byte operand unless imm selects int8-style mode
- lane_count: 128 or instruction-specific
- lane_dtype: int32
- view_confidence: partly inferred; docx gives detailed typed views for arithmetic families
- function: Value(Operand index 2)  = Value(Operand index 0) >> Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2
- 备注: 只用于int类型 操作数

## COND
- category: unsigned int arith inst
- docx_typed_view: imm==0: uint32[128]; imm==1: uint8[512]
- docx_family: unsigned_int_imm_mode
- docx_section: docx/instruction_sections/COND.md
- operand_view: imm==0: uint32[128]; imm==1: uint8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: uint32 or uint8
- view_confidence: documented by docx Unsigned Int32/unsigned Int8 section
- typed_semantics: imm==0: for i in 0..127 over uint32 lanes; imm==1: for i in 0..511 over uint8 lanes; dst[i] = (src0[i] > 0) ? src1[i] : old_dst[i]
- function: Value(Operand index 2)  = Value(Operand index 0) > 0 ? Value(Operand index 1) : Value(Operand index 2)
- sources: Operand index 0, Operand index 1, Operand index 2
- destinations: Operand index 2
- 备注: 3操作数

## COPYT
- category: Flow指令
- operand_view: copies a raw logical operand between PEs; SIMD128 COPYT is expanded into 4 x 1024-bit COPY chunks
- lane_count: not interpreted
- lane_dtype: raw logical operand / 1024-bit chunks
- view_confidence: documented by function text and examples
- typed_semantics: target_pe.operand[dst_idx].logical_bits[0..4095] = source_pe.operand[src_idx].logical_bits[0..4095]; lowered as 4 x 1024-bit COPY chunks
- function: Value(Operand index 1, pe index 1)  = Value(Operand index 0)
- sources: Operand index 0, Operand index 1
- destinations: PE index 1
- pipelined: Y
- 拍数: 1
- 备注: 将一个PE上寄存器的值，拷贝到另一个PE上的寄存器上

## DADD
- category: double arith inst
- docx_typed_view: 64 lanes x 64 bits = 4096 bits
- docx_family: double
- docx_section: docx/instruction_sections/DADD.md
- operand_view: fp64[64] over one logical 4096-bit/512-byte operand
- lane_count: 64
- lane_dtype: fp64
- view_confidence: documented by docx double section
- typed_semantics: for i in 0..63: dst.fp64[i] = src0.fp64[i] + src1.fp64[i]
- function: Value(Operand index 2)  = Value(Operand index 0) + Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2
- pipelined: Y
- 拍数: 2拍

## DB2FP
- category: Type conversion
- docx_family: special
- docx_section: docx/instruction_sections/DB2FP.md
- operand_view: conversion; source/destination lane views are specified by function text
- lane_count: instruction-specific
- lane_dtype: conversion
- view_confidence: documented by function text, but exact rounding may be unspecified
- function: Value(Operand index 2)(15:0) = float(Value(Operand index 0))  simd16->simd32
imm>0: Value(Operand index 2)(31:16) = float(Value(Operand index 0))  simd16->simd32
is disable for dc timing. Please use SHFL to reverse up and down
- sources: Operand index 0, Operand index 2
- destinations: Operand index 2
- 备注: 双精度转单精度
目的寄存器src2谨记事先初始化

## DDIV
- category: double arith inst
- docx_typed_view: 64 lanes x 64 bits = 4096 bits
- docx_family: double
- docx_section: docx/instruction_sections/DDIV.md
- operand_view: fp64[64] over one logical 4096-bit/512-byte operand
- lane_count: 64
- lane_dtype: fp64
- view_confidence: documented by docx double section
- typed_semantics: for i in 0..63: dst.fp64[i] = src0.fp64[i] / src1.fp64[i]
- function: Value(Operand index 2)  = Value(Operand index 0) / Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2
- pipelined: N
- 拍数: 34

## DGT
- category: double arith inst
- docx_typed_view: 64 lanes x 64 bits = 4096 bits
- docx_family: double
- docx_section: docx/instruction_sections/DGT.md
- operand_view: fp64[64] over one logical 4096-bit/512-byte operand
- lane_count: 64
- lane_dtype: fp64
- view_confidence: documented by docx double section
- typed_semantics: for i in 0..63: dst.fp64[i] = (src0.fp64[i] > src1.fp64[i]) ? 1 : 0
- function: Value(Operand index 2)  = Value(Operand index 0) > Value(Operand index 1) ? 1:0
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## DLT
- category: double arith inst
- docx_typed_view: 64 lanes x 64 bits = 4096 bits
- docx_family: double
- docx_section: docx/instruction_sections/DLT.md
- operand_view: fp64[64] over one logical 4096-bit/512-byte operand
- lane_count: 64
- lane_dtype: fp64
- view_confidence: documented by docx double section
- typed_semantics: for i in 0..63: dst.fp64[i] = (src0.fp64[i] < src1.fp64[i]) ? 1 : 0
- function: Value(Operand index 2)  = Value(Operand index 0) < Value(Operand index 1) ? 1:0
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## DMADD
- category: double arith inst
- docx_typed_view: 64 lanes x 64 bits = 4096 bits
- docx_family: double
- docx_section: docx/instruction_sections/DMADD.md
- operand_view: fp64[64] over one logical 4096-bit/512-byte operand
- lane_count: 64
- lane_dtype: fp64
- view_confidence: documented by docx double section
- typed_semantics: for i in 0..63: dst.fp64[i] = src0.fp64[i] * src1.fp64[i] + old_dst.fp64[i]
- function: Value(Operand index 2)  = Value(Operand index 0) * Value(Operand index 1) + Value(Operand index 2)
- sources: Operand index 0, Operand index 1, Operand index 2
- destinations: Operand index 2

## DMAX
- category: double arith inst
- docx_typed_view: 64 lanes x 64 bits = 4096 bits
- docx_family: double
- docx_section: docx/instruction_sections/DMAX.md
- operand_view: fp64[64] over one logical 4096-bit/512-byte operand
- lane_count: 64
- lane_dtype: fp64
- view_confidence: documented by docx double section
- typed_semantics: for i in 0..63: dst.fp64[i] = max(src0.fp64[i], src1.fp64[i])
- function: Value(Operand index 2) = max(Value(Operand index 0) , Value(Operand index 1))
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## DMIN
- category: double arith inst
- docx_typed_view: 64 lanes x 64 bits = 4096 bits
- docx_family: double
- docx_section: docx/instruction_sections/DMIN.md
- operand_view: fp64[64] over one logical 4096-bit/512-byte operand
- lane_count: 64
- lane_dtype: fp64
- view_confidence: documented by docx double section
- typed_semantics: for i in 0..63: dst.fp64[i] = min(src0.fp64[i], src1.fp64[i])
- function: Value(Operand index 2) = min(Value(Operand index 0) , Value(Operand index 1))
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## DMUL
- category: double arith inst
- docx_typed_view: 64 lanes x 64 bits = 4096 bits
- docx_family: double
- docx_section: docx/instruction_sections/DMUL.md
- operand_view: fp64[64] over one logical 4096-bit/512-byte operand
- lane_count: 64
- lane_dtype: fp64
- view_confidence: documented by docx double section
- typed_semantics: for i in 0..63: dst.fp64[i] = src0.fp64[i] * src1.fp64[i]
- function: Value(Operand index 2)  = Value(Operand index 0) * Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## DP4A
- category: unsigned int arith inst
- docx_family: special
- docx_section: docx/instruction_sections/DP4A.md
- operand_view: src int8/uint8 sublanes inside 128 x 32-bit words over one logical 4096-bit operand; dst int32/uint32[128]
- lane_count: 128
- lane_dtype: mixed int8 dot into int32/uint32
- view_confidence: documented by function text and metadata
- typed_semantics: for i in 0..127: dst.word32[i] accumulates four 8-bit products from src0.word32[i] and src1.word32[i]; imm selects signed/unsigned interpretation
- function: Value(Operand index 2)(i) += Value(Operand index 0)(i)[7:0] * Value(Operand index 1)(i)[7:0]
                                       += Value(Operand index 0)(i)[15:8] * Value(Operand index 1)(i)[15:8]
                                       += Value(Operand index 0)(i)[23:16] * Value(Operand index 1)(i)[23:16]
                                       += Value(Operand index 0)(i)[31:24] * Value(Operand index 1)(i)[31:24]
32bits*simd32                            {4*8bits}*simd32                     {4*8bits}*simd32
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2
(dummy Reg)
- 备注: INT8 混合进度乘加指令  A(8bits) * B(8bits) + 32(bits)
imm='b00,A(uint8) * B(uint8) + uint32；
imm='b01,A(int8) * B(uint8) + int32；
imm='b10,A(uint8) * B(int8) + int32；
imm='b11,A(int8) * B(int8) + int32；

## DSQRT
- category: double arith inst
- docx_family: double
- docx_section: docx/instruction_sections/DSQRT.md
- operand_view: fp64[64] over one logical 4096-bit/512-byte operand
- lane_count: 64
- lane_dtype: fp64
- view_confidence: documented by docx double section
- typed_semantics: for i in 0..63: dst.fp64[i] = sqrt(src0.fp64[i])
- function: Value(Operand index 2)  = Sqrt(Value(Operand index 0))
- sources: Operand index 0
- destinations: Operand index 2
- pipelined: N
- 拍数: 19

## DSUB
- category: double arith inst
- docx_typed_view: 64 lanes x 64 bits = 4096 bits
- docx_family: double
- docx_section: docx/instruction_sections/DSUB.md
- operand_view: fp64[64] over one logical 4096-bit/512-byte operand
- lane_count: 64
- lane_dtype: fp64
- view_confidence: documented by docx double section
- typed_semantics: for i in 0..63: dst.fp64[i] = src0.fp64[i] - src1.fp64[i]
- function: Value(Operand index 2)  = Value(Operand index 0) - Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## EQ
- category: int arith inst
- docx_typed_view: imm==0: signed int32[128]; imm==1: signed int8[512]
- docx_family: signed_int_imm_mode
- docx_section: docx/instruction_sections/EQ.md
- operand_view: imm==0: int32[128]; imm==1: int8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: int32 or int8
- view_confidence: documented by docx Int32/Int8 section
- typed_semantics: imm==0: for i in 0..127 compare signed 32-bit lanes; imm==1: for i in 0..511 compare signed 8-bit lanes; dst[i] = (src0[i] == src1[i]) ? 1 : 0
- function: Value(Operand index 2)  = Value(Operand index 0) == Value(Operand index 1) ? 1:0
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## EXPD32
- category: Special Integer instruction
- docx_family: half
- docx_section: docx/instruction_sections/EXPD32.md
- operand_view: extract one byte position from each 32-bit lane and expand to int32[128]
- lane_count: 128
- lane_dtype: int8 to int32
- view_confidence: documented by function text
- typed_semantics: for i in 0..127: dst.int32[i] = sign/zero-extended selected byte from src0.word32[i]; imm=0/1/2/3 selects bits [7:0]/[15:8]/[23:16]/[31:24]
- function: imm==0:  Val(Operand index 2) = int32( Val(Operand index0)(0)[7:0], … , Val(Operand index0)(31)[7:0] )
imm==1:  Val(Operand index 2) = int32( Val(Operand index0)(0)[15:8], … , Val(Operand index0)(31)[15:8] )
imm==2:  Val(Operand index 2) = int32( Val(Operand index0)(0)[23:16], … , Val(Operand index0)(31)[23:16] )
imm==3:  Val(Operand index 2) = int32( Val(Operand index0)(0)[31:24], … , Val(Operand index0)(31)[31:24] )
       32bits*simd32     <=         8bits*simd32
- sources: Operand index 0
- destinations: Operand index 2
- pipelined: Y
- 拍数: 1
- 备注: 根据imm字段的值判断int8扩展成int32的方式：
0:[simd124,simd120,…,simd4,simd0],  1:[simd125,simd121,…,simd5,simd1]
2:[simd126,simd122,…,simd6,simd2],  3:[simd127,simd123,…,simd7,simd3]
把寄存器128*8的数据取四分之一扩充成32*32

## FADD
- category: float arith inst
- docx_typed_view: 128 lanes x 32 bits = 4096 bits
- docx_family: float
- docx_section: docx/instruction_sections/FADD.md
- operand_view: fp32[128] over one logical 4096-bit/512-byte operand
- lane_count: 128
- lane_dtype: fp32
- view_confidence: documented by docx float section
- typed_semantics: for i in 0..127: dst.fp32[i] = src0.fp32[i] + src1.fp32[i]
- function: Value(Operand index 2)  = Value(Operand index 0) + Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2
- pipelined: Y
- 拍数: 2拍
FADD R0,r1,r2
nop
FADD r2,r3,r4

## FCOS
- category: Transcendental Functions
- operand_view: fp32[128] over one logical 4096-bit/512-byte operand
- lane_count: 128
- lane_dtype: fp32
- view_confidence: documented by docx float section
- typed_semantics: for i in 0..127: dst.fp32[i] = cos(src0.fp32[i])
- function: Value(Operand index 2)  = cos(Value(Operand index 0))
- sources: Operand index 0
- destinations: Operand index 2
- 含义: cos(a)

## FDIV
- category: float arith inst
- docx_typed_view: 128 lanes x 32 bits = 4096 bits
- docx_family: float
- docx_section: docx/instruction_sections/FDIV.md
- operand_view: fp32[128] over one logical 4096-bit/512-byte operand
- lane_count: 128
- lane_dtype: fp32
- view_confidence: documented by docx float section
- typed_semantics: for i in 0..127: dst.fp32[i] = src0.fp32[i] / src1.fp32[i]
- function: Value(Operand index 2)  = Value(Operand index 0) / Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2
- pipelined: N
- 拍数: 12拍数
FADD R0,r1,r2
11 nop
FADD r2,r3,r4

## FEXP2
- category: Transcendental Functions
- operand_view: fp32[128] over one logical 4096-bit/512-byte operand
- lane_count: 128
- lane_dtype: fp32
- view_confidence: documented by docx float section
- typed_semantics: for i in 0..127: dst.fp32[i] = exp2(src0.fp32[i])
- function: Value(Operand index 2)  = EXP2(Value(Operand index 0))
- sources: Operand index 0
- destinations: Operand index 2
- 含义: 2^a
- 备注: 可以把LOG2(E)当作常数load进来，实现e^a = 2^(log2(e) * a)

## FGT
- category: float arith inst
- docx_typed_view: 128 lanes x 32 bits = 4096 bits
- docx_family: float
- docx_section: docx/instruction_sections/FGT.md
- operand_view: fp32[128] over one logical 4096-bit/512-byte operand
- lane_count: 128
- lane_dtype: fp32
- view_confidence: documented by docx float section
- typed_semantics: for i in 0..127: dst.fp32[i] = (src0.fp32[i] > src1.fp32[i]) ? 1 : 0
- function: Value(Operand index 2)  = Value(Operand index 0) > Value(Operand index 1) ? 1:0
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## FIMM
- category: imm inst
- docx_family: special
- docx_section: docx/instruction_sections/FIMM.md
- operand_view: writes immediate values into selected 32-bit lanes of a logical operand
- lane_count: 128 in SIMD128 mode
- lane_dtype: raw32/immediate
- view_confidence: documented by function text and notes
- function: Value(Operand index 2)  = ｛IMM,opr2(30),IMM,opr2(28),IMM,opr2(26),IMM,opr2(24),IMM,opr2(22),IMM,opr2(20),IMM,opr2(18),IMM,opr2(16),IMM,opr2(14),IMM,opr2(12),IMM,opr2(10),IMM,opr2(8),IMM,opr2(6),IMM,opr2(4),IMM,opr2(2),IMM,opr2(0)}
- sources: IMM(31:0), Operand index 2
- destinations: Operand index 2
- 备注: IMM+FIMM组合使用：其中FIMM把立即数赋值到[1,3,5,…,31]的16个simd分量中，用于拼接64bit的数

## FLOG2
- category: Transcendental Functions
- operand_view: fp32[128] over one logical 4096-bit/512-byte operand
- lane_count: 128
- lane_dtype: fp32
- view_confidence: documented by docx float section
- typed_semantics: for i in 0..127: dst.fp32[i] = log2(src0.fp32[i])
- function: Value(Operand index 2)  = LOG2(Value(Operand index 0))
- sources: Operand index 0
- destinations: Operand index 2
- 含义: log2(a)
- 备注: 可以把LOG2(E)当作常数load进来，实现ln(a) = log2(a)/log2(e)

## FLT
- category: float arith inst
- docx_typed_view: 128 lanes x 32 bits = 4096 bits
- docx_family: float
- docx_section: docx/instruction_sections/FLT.md
- operand_view: fp32[128] over one logical 4096-bit/512-byte operand
- lane_count: 128
- lane_dtype: fp32
- view_confidence: documented by docx float section
- typed_semantics: for i in 0..127: dst.fp32[i] = (src0.fp32[i] < src1.fp32[i]) ? 1 : 0
- function: Value(Operand index 2)  = Value(Operand index 0) < Value(Operand index 1) ? 1:0
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## FMADD
- category: float arith inst
- docx_typed_view: 128 lanes x 32 bits = 4096 bits
- docx_family: float
- docx_section: docx/instruction_sections/FMADD.md
- operand_view: fp32[128] over one logical 4096-bit/512-byte operand
- lane_count: 128
- lane_dtype: fp32
- view_confidence: documented by docx float section
- typed_semantics: for i in 0..127: dst.fp32[i] = src0.fp32[i] * src1.fp32[i] + old_dst.fp32[i]
- function: Value(Operand index 2)  = Value(Operand index 0) * Value(Operand index 1) + Value(Operand index 2)
- sources: Operand index 0, Operand index 1, Operand index 2
- destinations: Operand index 2

## FMAX
- category: float arith inst
- docx_typed_view: 128 lanes x 32 bits = 4096 bits
- docx_family: float
- docx_section: docx/instruction_sections/FMAX.md
- operand_view: fp32[128] over one logical 4096-bit/512-byte operand
- lane_count: 128
- lane_dtype: fp32
- view_confidence: documented by docx float section
- typed_semantics: for i in 0..127: dst.fp32[i] = max(src0.fp32[i], src1.fp32[i])
- function: Value(Operand index 2) = max(Value(Operand index 0) , Value(Operand index 1))
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## FMIN
- category: float arith inst
- docx_typed_view: 128 lanes x 32 bits = 4096 bits
- docx_family: float
- docx_section: docx/instruction_sections/FMIN.md
- operand_view: fp32[128] over one logical 4096-bit/512-byte operand
- lane_count: 128
- lane_dtype: fp32
- view_confidence: documented by docx float section
- typed_semantics: for i in 0..127: dst.fp32[i] = min(src0.fp32[i], src1.fp32[i])
- function: Value(Operand index 2) = min(Value(Operand index 0) , Value(Operand index 1))
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## FMUL
- category: float arith inst
- docx_typed_view: 128 lanes x 32 bits = 4096 bits
- docx_family: float
- docx_section: docx/instruction_sections/FMUL.md
- operand_view: fp32[128] over one logical 4096-bit/512-byte operand
- lane_count: 128
- lane_dtype: fp32
- view_confidence: documented by docx float section
- typed_semantics: for i in 0..127: dst.fp32[i] = src0.fp32[i] * src1.fp32[i]
- function: Value(Operand index 2)  = Value(Operand index 0) * Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## FP2DB
- category: Type conversion
- docx_family: special
- docx_section: docx/instruction_sections/FP2DB.md
- operand_view: conversion; source/destination lane views are specified by function text
- lane_count: instruction-specific
- lane_dtype: conversion
- view_confidence: documented by function text, but exact rounding may be unspecified
- function: imm==0: Value(Operand index 2) = double(Value(Operand index 0)(15:0))  simd32->simd16
imm>0: Value(Operand index 2) = double(Value(Operand index 0)(31:16))  simd32->simd16
- sources: Operand index 0, IMM(7:0)
- destinations: Operand index 2
- pipelined: Y
- 拍数: 6拍
- 备注: 单精度转双精度

## FP2FXP
- category: Type conversion
- docx_family: special
- docx_section: docx/instruction_sections/FP2FXP.md
- operand_view: conversion; source/destination lane views are specified by function text
- lane_count: instruction-specific
- lane_dtype: conversion
- view_confidence: documented by function text, but exact rounding may be unspecified
- function: Value(Operand index 2) = int(Value(Operand index 0))  simd32->simd32
- sources: Operand index 0
- destinations: Operand index 2
- imm低字段: imm[4:0]=
[四舍五入/舍弃尾数，toRX3, toRX2, toRX1, toRX0]
- 备注: 浮点转定点-立即数imm字段起控制作用：

## FP2H
- category: half float arith inst
- docx_family: special
- docx_section: docx/instruction_sections/FP2H.md
- operand_view: conversion between fp16[64] and fp32[32] slices
- lane_count: 64 input/output fp16 or 32 input/output fp32 depending on direction
- lane_dtype: fp16/fp32 conversion
- view_confidence: documented by function text
- function: Value(Operand index 2)(15:0) = half float(Value(Operand index 0))  simd32->simd64
imm>0: Value(Operand index 2)(31:16) = float(Value(Operand index 0))  simd16->simd32
is disable for dc timing. Please use SHFL to reverse up and down
- sources: Operand index 0, Operand index 2
- destinations: Operand index 2

## FRCP
- category: Transcendental Functions
- operand_view: fp32[128] over one logical 4096-bit/512-byte operand
- lane_count: 128
- lane_dtype: fp32
- view_confidence: documented by docx float section
- typed_semantics: for i in 0..127: dst.fp32[i] = rcp(src0.fp32[i])
- function: Value(Operand index 2)  = 1/(Value(Operand index 0))
- sources: Operand index 0
- destinations: Operand index 2
- pipelined: N
- 拍数: 5拍
- 含义: 1/a

## FRSQRT
- category: Transcendental Functions
- operand_view: fp32[128] over one logical 4096-bit/512-byte operand
- lane_count: 128
- lane_dtype: fp32
- view_confidence: documented by docx float section
- typed_semantics: for i in 0..127: dst.fp32[i] = rsqrt(src0.fp32[i])
- function: Value(Operand index 2)  = 1/Sqrt(Value(Operand index 0))
- sources: Operand index 0
- destinations: Operand index 2
- 含义: 1/sqrt(a)

## FSIN
- category: Transcendental Functions
- operand_view: fp32[128] over one logical 4096-bit/512-byte operand
- lane_count: 128
- lane_dtype: fp32
- view_confidence: documented by docx float section
- typed_semantics: for i in 0..127: dst.fp32[i] = sin(src0.fp32[i])
- function: Value(Operand index 2)  = sin(Value(Operand index 0))
- sources: Operand index 0
- destinations: Operand index 2
- 含义: sin(a)

## FSQRT
- category: Transcendental Functions
- operand_view: fp32[128] over one logical 4096-bit/512-byte operand
- lane_count: 128
- lane_dtype: fp32
- view_confidence: documented by docx float section
- typed_semantics: for i in 0..127: dst.fp32[i] = sqrt(src0.fp32[i])
- function: Value(Operand index 2)  = Sqrt(Value(Operand index 0))
- sources: Operand index 0
- destinations: Operand index 2
- 含义: sqrt(a)

## FSUB
- category: float arith inst
- docx_typed_view: 128 lanes x 32 bits = 4096 bits
- docx_family: float
- docx_section: docx/instruction_sections/FSUB.md
- operand_view: fp32[128] over one logical 4096-bit/512-byte operand
- lane_count: 128
- lane_dtype: fp32
- view_confidence: documented by docx float section
- typed_semantics: for i in 0..127: dst.fp32[i] = src0.fp32[i] - src1.fp32[i]
- function: Value(Operand index 2)  = Value(Operand index 0) - Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## FXP2FP
- category: Type conversion
- docx_family: special
- docx_section: docx/instruction_sections/FXP2FP.md
- operand_view: conversion; source/destination lane views are specified by function text
- lane_count: instruction-specific
- lane_dtype: conversion
- view_confidence: documented by function text, but exact rounding may be unspecified
- function: Value(Operand index 2) = float(Value(Operand index 0))  simd32->simd32
- sources: Operand index 0
- destinations: Operand index 2
- imm低字段: imm[3:0]=
[RX3toSrc, RX2toSrc, RX1toSrc, RX0toSrc]
- 备注: 定点转浮点，只用于int类型 操作数

## GINST
- category: Special Integer instruction
- docx_family: special
- docx_section: docx/instruction_sections/GINST.md
- operand_view: special integer/control semantics; inspect function text
- lane_count: instruction-specific
- lane_dtype: instruction-specific
- view_confidence: requires per-instruction reading
- function: Value(Operand index 2)  = inst_num
- destinations: Operand index 2
- pipelined: Y
- 拍数: 1拍

## GSIMD
- category: Special Integer instruction
- docx_family: special
- docx_section: docx/instruction_sections/GSIMD.md
- operand_view: special integer/control semantics; inspect function text
- lane_count: instruction-specific
- lane_dtype: instruction-specific
- view_confidence: requires per-instruction reading
- function: Value(Operand index 2)  = {31,30,…,1,0}
- destinations: Operand index 2

## GT
- category: int arith inst
- docx_typed_view: imm==0: signed int32[128]; imm==1: signed int8[512]
- docx_family: signed_int_imm_mode
- docx_section: docx/instruction_sections/GT.md
- operand_view: imm==0: int32[128]; imm==1: int8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: int32 or int8
- view_confidence: documented by docx Int32/Int8 section
- typed_semantics: imm==0: for i in 0..127 compare signed 32-bit lanes; imm==1: for i in 0..511 compare signed 8-bit lanes; dst[i] = (src0[i] > src1[i]) ? 1 : 0
- function: Value(Operand index 2)  = Value(Operand index 0) > Value(Operand index 1) ? 1:0
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## GTASK
- category: Special Integer instruction
- docx_family: special
- docx_section: docx/instruction_sections/GTASK.md
- operand_view: special integer/control semantics; inspect function text
- lane_count: instruction-specific
- lane_dtype: instruction-specific
- view_confidence: requires per-instruction reading
- function: Value(Operand index 2)  = task_num
- destinations: Operand index 2

## H2FP
- category: half float arith inst
- docx_family: special
- docx_section: docx/instruction_sections/H2FP.md
- operand_view: conversion between fp16[64] and fp32[32] slices
- lane_count: 64 input/output fp16 or 32 input/output fp32 depending on direction
- lane_dtype: fp16/fp32 conversion
- view_confidence: documented by function text
- function: imm==0: Value(Operand index 2) = float(Value(Operand index 0)(31:0))  simd64->simd32
imm>0: Value(Operand index 2) = float(Value(Operand index 0)(63:32))  simd64->simd32
- sources: Operand index 0, IMM(7:0)
- destinations: Operand index 2

## HADD
- category: half float arith inst
- docx_typed_view: 256 lanes x 16 bits = 4096 bits
- docx_family: half
- docx_section: docx/instruction_sections/HADD.md
- operand_view: fp16[256] over one logical 4096-bit/512-byte operand
- lane_count: 256
- lane_dtype: fp16
- view_confidence: documented by docx half-float section
- typed_semantics: for i in 0..255: dst.fp16[i] = src0.fp16[i] + src1.fp16[i]
- function: Value(Operand index 2)  = Value(Operand index 0) + Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2
- pipelined: Y
- 拍数: 2拍

## HDIV
- category: half float arith inst
- docx_typed_view: 256 lanes x 16 bits = 4096 bits
- docx_family: half
- docx_section: docx/instruction_sections/HDIV.md
- operand_view: fp16[256] over one logical 4096-bit/512-byte operand
- lane_count: 256
- lane_dtype: fp16
- view_confidence: documented by docx half-float section
- typed_semantics: for i in 0..255: dst.fp16[i] = src0.fp16[i] / src1.fp16[i]
- function: Value(Operand index 2)  = Value(Operand index 0) / Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2
- pipelined: N
- 拍数: 5拍

## HGT
- category: half float arith inst
- docx_typed_view: 256 lanes x 16 bits = 4096 bits
- docx_family: half
- docx_section: docx/instruction_sections/HGT.md
- operand_view: fp16[256] over one logical 4096-bit/512-byte operand
- lane_count: 256
- lane_dtype: fp16
- view_confidence: documented by docx half-float section
- typed_semantics: for i in 0..255: dst.fp16[i] = (src0.fp16[i] > src1.fp16[i]) ? 1 : 0
- function: Value(Operand index 2)  = Value(Operand index 0) > Value(Operand index 1) ? 1:0
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## HLT
- category: half float arith inst
- docx_typed_view: 256 lanes x 16 bits = 4096 bits
- docx_family: half
- docx_section: docx/instruction_sections/HLT.md
- operand_view: fp16[256] over one logical 4096-bit/512-byte operand
- lane_count: 256
- lane_dtype: fp16
- view_confidence: documented by docx half-float section
- typed_semantics: for i in 0..255: dst.fp16[i] = (src0.fp16[i] < src1.fp16[i]) ? 1 : 0
- function: Value(Operand index 2)  = Value(Operand index 0) < Value(Operand index 1) ? 1:0
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## HMADD
- category: half float arith inst
- docx_typed_view: 256 lanes x 16 bits = 4096 bits
- docx_family: half
- docx_section: docx/instruction_sections/HMADD.md
- operand_view: fp16[256] over one logical 4096-bit/512-byte operand
- lane_count: 256
- lane_dtype: fp16
- view_confidence: documented by docx half-float section
- typed_semantics: for i in 0..255: dst.fp16[i] = src0.fp16[i] * src1.fp16[i] + old_dst.fp16[i]
- function: Value(Operand index 2)  = Value(Operand index 0) * Value(Operand index 1) + Value(Operand index 2)
- sources: Operand index 0, Operand index 1, Operand index 2
- destinations: Operand index 2

## HMAX
- category: half float arith inst
- docx_typed_view: 256 lanes x 16 bits = 4096 bits
- docx_family: half
- docx_section: docx/instruction_sections/HMAX.md
- operand_view: fp16[256] over one logical 4096-bit/512-byte operand
- lane_count: 256
- lane_dtype: fp16
- view_confidence: documented by docx half-float section
- typed_semantics: for i in 0..255: dst.fp16[i] = max(src0.fp16[i], src1.fp16[i])
- function: Value(Operand index 2) = max(Value(Operand index 0) , Value(Operand index 1))
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## HMIN
- category: half float arith inst
- docx_typed_view: 256 lanes x 16 bits = 4096 bits
- docx_family: half
- docx_section: docx/instruction_sections/HMIN.md
- operand_view: fp16[256] over one logical 4096-bit/512-byte operand
- lane_count: 256
- lane_dtype: fp16
- view_confidence: documented by docx half-float section
- typed_semantics: for i in 0..255: dst.fp16[i] = min(src0.fp16[i], src1.fp16[i])
- function: Value(Operand index 2) = min(Value(Operand index 0) , Value(Operand index 1))
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## HMUL
- category: half float arith inst
- docx_typed_view: 256 lanes x 16 bits = 4096 bits
- docx_family: half
- docx_section: docx/instruction_sections/HMUL.md
- operand_view: fp16[256] over one logical 4096-bit/512-byte operand
- lane_count: 256
- lane_dtype: fp16
- view_confidence: documented by docx half-float section
- typed_semantics: for i in 0..255: dst.fp16[i] = src0.fp16[i] * src1.fp16[i]
- function: Value(Operand index 2)  = Value(Operand index 0) * Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## HSIS
- category: half float arith inst
- docx_family: half
- docx_section: docx/instruction_sections/HSIS.md
- operand_view: fp16[256] over one logical 4096-bit/512-byte operand
- lane_count: 256
- lane_dtype: fp16
- view_confidence: documented by docx half-float section
- typed_semantics: for i in 0..255: dst.fp16[i] = selected special function(src0.fp16[i]); imm[7:0] selects function
- function: 超函数
- sources: Operand index 0
- destinations: Operand index 2
- imm低字段: imm[7:0]

## HSUB
- category: half float arith inst
- docx_typed_view: 256 lanes x 16 bits = 4096 bits
- docx_family: half
- docx_section: docx/instruction_sections/HSUB.md
- operand_view: fp16[256] over one logical 4096-bit/512-byte operand
- lane_count: 256
- lane_dtype: fp16
- view_confidence: documented by docx half-float section
- typed_semantics: for i in 0..255: dst.fp16[i] = src0.fp16[i] - src1.fp16[i]
- function: Value(Operand index 2)  = Value(Operand index 0) - Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## IMM
- category: imm inst
- docx_family: special
- docx_section: docx/instruction_sections/IMM.md
- operand_view: writes immediate values into selected 32-bit lanes of a logical operand
- lane_count: 128 in SIMD128 mode
- lane_dtype: raw32/immediate
- view_confidence: documented by function text and notes
- function: Value(Operand index 2)  = IMM
- sources: IMM(31:0)
- destinations: Operand index 2

## LSL
- category: logic inst
- docx_family: special
- docx_section: docx/instruction_sections/LSL.md
- operand_view: uint32/bit32[128] over one logical 4096-bit/512-byte operand unless imm selects int8-style mode
- lane_count: 128 or instruction-specific
- lane_dtype: uint32/bit32
- view_confidence: partly inferred; docx gives detailed typed views for arithmetic families
- function: Value(Operand index 2)  = Value(Operand index 0) << Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## LSR
- category: logic inst
- operand_view: uint32/bit32[128] over one logical 4096-bit/512-byte operand unless imm selects int8-style mode
- lane_count: 128 or instruction-specific
- lane_dtype: uint32/bit32
- view_confidence: partly inferred; docx gives detailed typed views for arithmetic families
- function: Value(Operand index 2)  = Value(Operand index 0) >> Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2
- 备注: 只用于uint类型 操作数

## LT
- category: int arith inst
- docx_typed_view: imm==0: signed int32[128]; imm==1: signed int8[512]
- docx_family: signed_int_imm_mode
- docx_section: docx/instruction_sections/LT.md
- operand_view: imm==0: int32[128]; imm==1: int8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: int32 or int8
- view_confidence: documented by docx Int32/Int8 section
- typed_semantics: imm==0: for i in 0..127 compare signed 32-bit lanes; imm==1: for i in 0..511 compare signed 8-bit lanes; dst[i] = (src0[i] < src1[i]) ? 1 : 0
- function: Value(Operand index 2)  = Value(Operand index 0) < Value(Operand index 1) ? 1:0
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## MADD
- category: int arith inst
- docx_typed_view: imm==0: signed int32[128]; imm==1: signed int8[512]
- docx_family: signed_int_imm_mode
- docx_section: docx/instruction_sections/MADD.md
- operand_view: imm==0: int32[128]; imm==1: int8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: int32 or int8
- view_confidence: documented by docx Int32/Int8 section
- function: Value(Operand index 2)  = Value(Operand index 0) * Value(Operand index 1) + Value(Operand index 2)
- sources: Operand index 0, Operand index 1, Operand index 2
- destinations: Operand index 2

## MASK
- category: modify exception regs
- docx_family: half
- docx_section: docx/instruction_sections/MASK.md
- operand_view: Operand0 simd0 low bits encode mask register configuration
- lane_count: configuration bits, not vector arithmetic
- lane_dtype: bitfield
- view_confidence: documented by function text and OCR notes
- typed_semantics: reads Operand0 simd0 low 14 bits as {Ext_flag, Ext_offset, Regid_off, double_mark, Maskregno, mask_val}
- function: 功能：修改运算部件内部8个mask寄存器（store执行时屏蔽某些simd分量）
操作数0的simd0分量的[13:0]比特 =  {Ext_flag,Ext_offset[1:0],Regid_off[1:0],double_mark, Maskregno[7:5],mask_val[4:0]}
1）double_mark: 指示-是否开启双simd分量写回模式
2）Maskregno[7:5]: 表示要填入mask0到mask7的8个中的哪个寄存器
3）mask_val[4:0]: 表示要填入mask暂存器的值，对应32bit分量粒度
4）Regid_off[1:0]: 表示SIMD128模式下寄存器编号偏移
5）Ext_offset[1:0]: 表示8bit分量索引，与mask_val[4:0]组合使用
6）Ext_flag: 与double_mark组合使用，表示8/16/32/64bit分量写回模式，具体参考word图中描述。
- sources: Operand index 0
- destinations: Operand index 0
(dummy Reg)
- pipelined: Y
- 拍数: 1拍
- 备注: 功能：修改运算部件内部8个mask寄存器（store执行时屏蔽某些simd分量）
操作数0的simd0分量的[13:0]比特 =  {Ext_flag,Ext_offset[1:0],Regid_off[1:0],double_mark, Maskregno[7:5],mask_val[4:0]}
1）double_mark: 指示-是否开启双simd分量写回模式
2）Maskregno[7:5]: 表示要填入mask0到mask7的8个中的哪个寄存器
3）mask_val[4:0]: 表示要填入mask暂存器的值，对应32bit分量粒度
4）Regid_off[1:0]: 表示SIMD128/64/32模式下寄存器编号偏移
5）Ext_offset[1:0]: 表示8bit分量索引，与mask_val[4:0]组合使用
6）Ext_flag: 与double_mark组合使用，表示8/16/32/64bit分量写回模式，具体参考word图中描述。

## MAX
- category: int arith inst
- docx_typed_view: imm==0: signed int32[128]; imm==1: signed int8[512]
- docx_family: signed_int_imm_mode
- docx_section: docx/instruction_sections/MAX.md
- operand_view: imm==0: int32[128]; imm==1: int8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: int32 or int8
- view_confidence: documented by docx Int32/Int8 section
- typed_semantics: imm==0: for i in 0..127 operate on signed 32-bit lanes; imm==1: for i in 0..511 operate on signed 8-bit lanes; dst[i] = max(src0[i], src1[i])
- function: Value(Operand index 2) = max(Value(Operand index 0) , Value(Operand index 1))
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## MIN
- category: int arith inst
- docx_typed_view: imm==0: signed int32[128]; imm==1: signed int8[512]
- docx_family: signed_int_imm_mode
- docx_section: docx/instruction_sections/MIN.md
- operand_view: imm==0: int32[128]; imm==1: int8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: int32 or int8
- view_confidence: documented by docx Int32/Int8 section
- typed_semantics: imm==0: for i in 0..127 operate on signed 32-bit lanes; imm==1: for i in 0..511 operate on signed 8-bit lanes; dst[i] = min(src0[i], src1[i])
- function: Value(Operand index 2) = min(Value(Operand index 0) , Value(Operand index 1))
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## MUL
- category: int arith inst
- docx_typed_view: imm==0: signed int32[128]; imm==1: signed int8[512]
- docx_family: signed_int_imm_mode
- docx_section: docx/instruction_sections/MUL.md
- operand_view: imm==0: int32[128]; imm==1: int8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: int32 or int8
- view_confidence: documented by docx Int32/Int8 section
- typed_semantics: imm==0: for i in 0..127 operate on signed 32-bit lanes; imm==1: for i in 0..511 operate on signed 8-bit lanes; dst[i] = src0[i] * src1[i]
- function: Value(Operand index 2)  = Value(Operand index 0) * Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## NOP
- category: int arith inst
- operand_view: imm==0: int32[128]; imm==1: int8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: int32 or int8
- view_confidence: documented by docx Int32/Int8 section
- pipelined: Y
- 拍数: 2拍，插一条不相关指令
add r1,r2,r3
nop
add r3,r4,r5
- imm低字段: 0：INT32
1： INT8

## NOT
- category: logic inst
- docx_family: special
- docx_section: docx/instruction_sections/NOT.md
- operand_view: uint32/bit32[128] over one logical 4096-bit/512-byte operand unless imm selects int8-style mode
- lane_count: 128 or instruction-specific
- lane_dtype: uint32/bit32
- view_confidence: partly inferred; docx gives detailed typed views for arithmetic families
- function: Value(Operand index 2)  = ! Value(Operand index 0)
- sources: Operand index 0
- destinations: Operand index 2

## OR
- category: logic inst
- docx_family: special
- docx_section: docx/instruction_sections/OR.md
- operand_view: uint32/bit32[128] over one logical 4096-bit/512-byte operand unless imm selects int8-style mode
- lane_count: 128 or instruction-specific
- lane_dtype: uint32/bit32
- view_confidence: partly inferred; docx gives detailed typed views for arithmetic families
- function: Value(Operand index 2)  = Value(Operand index 0) | Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## QMADD
- category: Special Integer instruction
- docx_family: half
- docx_section: docx/instruction_sections/QMADD.md
- operand_view: uint8[512] sources accumulated into internal RX0..RX3 int32 lanes over a logical SIMD128 operand
- lane_count: 512 source lanes; RX accumulators are 1024-bit chunks used by int8 pipeline
- lane_dtype: uint8 multiply into int32 accumulator
- view_confidence: documented by function text and OCR notes
- typed_semantics: for byte lane k in 0..511: RX/chunk accumulators += uint8(src0[k]) * uint8(src1[k]); result is read back by TRCT8/RXOUT
- function: {Rx3,Rx2,Rx1,Rx0}       +=        Value(Operand index 0) * Value(Operand index 1)
32bits*simd128                            8bits*simd128                     8bits*simd128
只支持无符号uint8 的计算
QMADD计算完之后，需结合TRCT8指令，才能拿到正确结果
Rx0[0] += src0[0]*src1[0]
  32bits        8bits*8bits
Rx1[0] += src0[1]*src1[1]
Rx2[0] += src0[2]*src1[2]
Rx3[0] += src0[3]*src1[3]
Rx0[1] += src0[4]*src1[4]
  32bits        8bits*8bits
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2
(dummy Reg)
- pipelined: Y
- 拍数: 2

## RXIN
- category: Special Integer instruction
- docx_family: half
- docx_section: docx/instruction_sections/RXIN.md
- operand_view: moves raw 1024-bit chunks to/from internal RX/LRX registers
- lane_count: mode-specific
- lane_dtype: raw/RX internal
- view_confidence: documented by function text
- function: 将opMem数值赋值到暂存器RX/LRX里: 
1）RX0,RX1,RX2,RX3用于int8计算； 
imm=0: RX0 <= src0     imm=1: RX1 <= src0
imm=2: RX2 <= src0     imm=3: RX3 <= src0
imm=12: 对RX0,RX1,RX2,RX3清零

2）LRX0，LRX1，LRX2，LRX3，LRX4，LRX5，LRX6，LRX7的(32bits)用于sldshif和sstshif指令间接寻址  
imm=4: LRX0 <= src0  imm=5: LRX1 <= src0
imm=6: LRX2 <= src0  imm=7: LRX3 <= src0
imm=8: LRX4 <= src0  imm=9: LRX5 <= src0
imm=10: LRX6 <= src0 imm=11: LRX7 <= src0
- sources: Operand index 0
- destinations: Operand index 2
(dummy Reg)
- 备注: 从opMem中取1个1024位的oprand放到暂存器RX/LRX里: 
1）RX[0-3](1024bits)用于int8计算； 
imm=0: RX0 <= src0     imm=1: RX1 <= src0
imm=2: RX2 <= src0     imm=3: RX3 <= src0
imm=12: 对RX0,RX1,RX2,RX3清零

2）LRX[0-7](32bits)用于ldshift STshift间接寻址
imm=4: LRX0 <= src0[0]  imm=5: LRX1 <= src0[0]
imm=6: LRX2 <= src0[0]  imm=7: LRX3 <= src0[0]
imm=8: LRX4 <= src0[0]  imm=9: LRX5 <= src0[0]
imm=10: LRX6 <= src0[0]  imm=11: LRX7 <= src0[0]

## RXOUT
- category: Special Integer instruction
- docx_family: half
- docx_section: docx/instruction_sections/RXOUT.md
- operand_view: moves raw 1024-bit chunks to/from internal RX/LRX registers
- lane_count: mode-specific
- lane_dtype: raw/RX internal
- view_confidence: documented by function text
- function: 把用于int8计算的RX[0-3]值取回到目的寄存器里： 
imm=0: RX0 => src2     imm=1: RX1 => src2
imm=2: RX2 => src2     imm=3: RX3 => src2
(LRX不适用)
- destinations: Operand index 2
- 备注: 把用于int8计算的RX[0-3](1024bits)值取回到目的寄存器里： 
imm=0: RX0 => src2     imm=1: RX1 => src2
imm=2: RX2 => src2     imm=3: RX3 => src2
(LRX不适用)

## SHFL
- category: float arith inst
- docx_family: half
- docx_section: docx/instruction_sections/SHFL.md
- operand_view: lane permutation; lane width selected by imm[1:0]
- lane_count: 32 or 16 depending on mode
- lane_dtype: fp32/fp64-style lane index, not arithmetic dtype
- view_confidence: documented by function text and OCR notes
- typed_semantics: permutes lanes of Operand1/Operand2 according to index operand and imm[1:0] mode
- function: imm[1:0]==0   immediate mode:
Value(Operand index 0)[59:0] = [dst5,dst4,dst3,dst2,dst1,dst0,    src5,src4,src3,src2,src1,src0]:
 (1)select 6 simds( src5,src4,src3,src2,src1,src0) from Value(Operand index 1),
 (2)place them to 6 simds(dst5,dst4,dst3,dst2,dst1,dst0) position of Value(Operand index 2).
32>dst5>dst4>dst3>dst2>dst1>dst0>=0;  srci < 32;  dsti==0 and i>0,  disable i postion
special use:  when Val(Operand index 0)==zeros, exchange up[1023:512] and down[511:0] of Val(Operand idx2)
指令写法参考：
IMM, , , idx_reg, 321579821758215(60位的index编码立即数)
shfl, idx_reg, val1, val2    
special use:shfl, idx_reg, , val2
- sources: Operand index 0[59:0], Operand index 1, Operand index 2
- destinations: Operand index 2
- pipelined: N
- 拍数: 6拍
FADD R0,r1,r2
5nop
FADD r2,r3,r4
- imm低字段: imm[1:0]=
0: old_imm_fp32_merge
1: fp32 merge
2: fp64 merge
3: fp32 shift
- 备注: 重排simd各个分量的位置
imm=0，为之前旧的 idx压缩成5bit，最多shuffle6个32数的模式
imm=1，为新的idx为32bit数，最多shuffle8个32数的模式
imm=2，为新的idx为32bit数，最多shuffle8个64数的模式
imm=3，为shift模式，2个数高低simd32分量拼接的模式
目的寄存器src2谨记事先初始化 

imm[2]=0, 第一组1024bit数内部shuffle;   imm[2]=1, 第一组1024bit数内部数据保持;
imm[3]=0, 第二组1024bit数内部shuffle;   imm[3]=1, 第二组1024bit数内部数据保持;
imm[4]=0, 第三组1024bit数内部shuffle;   imm[4]=1, 第三组1024bit数内部数据保持;
imm[5]=0, 第四组1024bit数内部shuffle;   imm[5]=1, 第四组1024bit数内部数据保持;

## SUB
- category: int arith inst
- docx_typed_view: imm==0: signed int32[128]; imm==1: signed int8[512]
- docx_family: signed_int_imm_mode
- docx_section: docx/instruction_sections/SUB.md
- operand_view: imm==0: int32[128]; imm==1: int8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: int32 or int8
- view_confidence: documented by docx Int32/Int8 section
- typed_semantics: imm==0: for i in 0..127 operate on signed 32-bit lanes; imm==1: for i in 0..511 operate on signed 8-bit lanes; dst[i] = src0[i] - src1[i]
- function: Value(Operand index 2)  = Value(Operand index 0) - Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## TRCT8
- category: Special Integer instruction
- docx_family: half
- docx_section: docx/instruction_sections/TRCT8.md
- operand_view: truncate/reorder RX int32 accumulators into uint8/int8 lanes
- lane_count: mode-specific; 512 output lanes in a full SIMD128 logical operand
- lane_dtype: int32 accumulator to 8-bit lane
- view_confidence: documented at high level; some imm modes still need verification
- typed_semantics: writes Operand2 by truncating/reordering RX0..RX3 int32 accumulators to 8-bit lanes; imm selects the packing mode
- function: imm==0:  
Val(Operand index 2) = Truncate( {Rx3,Rx2,Rx1,Rx0} )[7:0]  
imm==1:  
Val(Operand index 2)=Truncate( {Rx3(31),Rx2(31),Rx1(31),Rx0(31)},.., {Rx3(0),Rx2(0),Rx1(0),Rx0(0)} )[7:0]
       8bits*simd128              32bits*simd128 
用于QMADD后的TRCT8：
imm[1]=1: Rx0 => src2;
imm[2]=1: Rx1 => src2;
imm[3]=1: Rx2 => src2;
imm[4]=1: Rx3 => src2;
- destinations: Operand index 2
- pipelined: N
- 拍数: 5拍
- 备注: 把4个Rx寄存器128*32bits的数截断成128*8bits，拼接方式：
imm[0]=0：Rx3,Rx2,Rx1,Rx0
imm[0]=1：Rx3[31],Rx2[31],Rx1[31],Rx0[31],..,Rx3[0],Rx2[0],Rx1[0],Rx0[0]

用于QMADD后的TRCT8：
imm[1]=1: Rx0 => src2;
imm[2]=1: Rx1 => src2;
imm[3]=1: Rx2 => src2;
imm[4]=1: Rx3 => src2;

## UADD
- category: unsigned int arith inst
- docx_typed_view: imm==0: 128 lanes x 32 bits; imm==1: 512 lanes x 8 bits
- docx_family: unsigned_int_imm_mode
- docx_section: docx/instruction_sections/UADD.md
- operand_view: imm==0: uint32[128]; imm==1: uint8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: uint32 or uint8
- view_confidence: documented by docx Unsigned Int32/unsigned Int8 section
- typed_semantics: imm==0: for i in 0..127 operate on unsigned 32-bit lanes; imm==1: for i in 0..511 operate on unsigned 8-bit lanes; dst[i] = src0[i] + src1[i]
- function: Value(Operand index 2)  = Value(Operand index 0) + Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## UGT
- category: unsigned int arith inst
- docx_typed_view: imm==0: uint32[128]; imm==1: uint8[512]
- docx_family: unsigned_int_imm_mode
- docx_section: docx/instruction_sections/UGT.md
- operand_view: imm==0: uint32[128]; imm==1: uint8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: uint32 or uint8
- view_confidence: documented by docx Unsigned Int32/unsigned Int8 section
- typed_semantics: imm==0: for i in 0..127 compare unsigned 32-bit lanes; imm==1: for i in 0..511 compare unsigned 8-bit lanes; dst[i] = (src0[i] > src1[i]) ? 1 : 0
- function: Value(Operand index 2)  = Value(Operand index 0) > Value(Operand index 1) ? 1:0
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## ULT
- category: unsigned int arith inst
- docx_typed_view: imm==0: uint32[128]; imm==1: uint8[512]
- docx_family: unsigned_int_imm_mode
- docx_section: docx/instruction_sections/ULT.md
- operand_view: imm==0: uint32[128]; imm==1: uint8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: uint32 or uint8
- view_confidence: documented by docx Unsigned Int32/unsigned Int8 section
- typed_semantics: imm==0: for i in 0..127 compare unsigned 32-bit lanes; imm==1: for i in 0..511 compare unsigned 8-bit lanes; dst[i] = (src0[i] < src1[i]) ? 1 : 0
- function: Value(Operand index 2)  = Value(Operand index 0) < Value(Operand index 1) ? 1:0
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## ULTS
- category: unsigned int arith inst
- docx_typed_view: imm==0: uint32[128]; imm==1: uint8[512]
- docx_family: unsigned_int_imm_mode
- docx_section: docx/instruction_sections/ULTS.md
- operand_view: imm==0: uint32[128]; imm==1: uint8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: uint32 or uint8
- view_confidence: documented by docx Unsigned Int32/unsigned Int8 section
- typed_semantics: imm==0: for i in 0..127 compare unsigned 32-bit lanes; imm==1: for i in 0..511 compare unsigned 8-bit lanes; dst[i] = (src0[i] < src1[i]) ? 1 : 0
- function: Value(Operand index 2)  = Value(Operand index 0) < Value(Operand index 1) ? 1:0
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2
- 备注: 只用于uint类型 操作数

## UMADD
- category: unsigned int arith inst
- docx_typed_view: imm==0: uint32[128]; imm==1: uint8[512]
- docx_family: unsigned_int_imm_mode
- docx_section: docx/instruction_sections/UMADD.md
- operand_view: imm==0: uint32[128]; imm==1: uint8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: uint32 or uint8
- view_confidence: documented by docx Unsigned Int32/unsigned Int8 section
- function: Value(Operand index 2)  = Value(Operand index 0) * Value(Operand index 1) + Value(Operand index 2)
- sources: Operand index 0, Operand index 1, Operand index 2
- destinations: Operand index 2

## UMAX
- category: unsigned int arith inst
- docx_typed_view: imm==0: uint32[128]; imm==1: uint8[512]
- docx_family: unsigned_int_imm_mode
- docx_section: docx/instruction_sections/UMAX.md
- operand_view: imm==0: uint32[128]; imm==1: uint8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: uint32 or uint8
- view_confidence: documented by docx Unsigned Int32/unsigned Int8 section
- typed_semantics: imm==0: for i in 0..127 operate on unsigned 32-bit lanes; imm==1: for i in 0..511 operate on unsigned 8-bit lanes; dst[i] = max(src0[i], src1[i])
- function: Value(Operand index 2) = max(Value(Operand index 0) , Value(Operand index 1))
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## UMUL
- category: unsigned int arith inst
- docx_typed_view: imm==0: uint32[128]; imm==1: uint8[512]
- docx_family: unsigned_int_imm_mode
- docx_section: docx/instruction_sections/UMUL.md
- operand_view: imm==0: uint32[128]; imm==1: uint8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: uint32 or uint8
- view_confidence: documented by docx Unsigned Int32/unsigned Int8 section
- typed_semantics: imm==0: for i in 0..127 operate on unsigned 32-bit lanes; imm==1: for i in 0..511 operate on unsigned 8-bit lanes; dst[i] = src0[i] * src1[i]
- function: Value(Operand index 2)  = Value(Operand index 0) * Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## USUB
- category: unsigned int arith inst
- docx_typed_view: imm==0: uint32[128]; imm==1: uint8[512]
- docx_family: unsigned_int_imm_mode
- docx_section: docx/instruction_sections/USUB.md
- operand_view: imm==0: uint32[128]; imm==1: uint8[512], over one logical 4096-bit/512-byte operand
- lane_count: 128 or 512
- lane_dtype: uint32 or uint8
- view_confidence: documented by docx Unsigned Int32/unsigned Int8 section
- typed_semantics: imm==0: for i in 0..127 operate on unsigned 32-bit lanes; imm==1: for i in 0..511 operate on unsigned 8-bit lanes; dst[i] = src0[i] - src1[i]
- function: Value(Operand index 2)  = Value(Operand index 0) - Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2

## XOR
- category: logic inst
- docx_family: special
- docx_section: docx/instruction_sections/XOR.md
- operand_view: uint32/bit32[128] over one logical 4096-bit/512-byte operand unless imm selects int8-style mode
- lane_count: 128 or instruction-specific
- lane_dtype: uint32/bit32
- view_confidence: partly inferred; docx gives detailed typed views for arithmetic families
- function: Value(Operand index 2)  = Value(Operand index 0) ^ Value(Operand index 1)
- sources: Operand index 0, Operand index 1
- destinations: Operand index 2
