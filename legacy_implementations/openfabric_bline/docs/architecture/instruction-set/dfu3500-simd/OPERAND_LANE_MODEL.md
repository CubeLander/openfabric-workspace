# Operand Lane Model

本文是 DFU3500 SIMD operand/lane 尺度的短版入口。更完整的架构笔记见
`docs/architecture/02-pe-operand-index-model.md` 和
`docs/architecture/05-simd-lane-interpretation.md`。

## 当前结论

官方材料给出的关键尺度是：

```text
SIMD128 模式下，1536/4 个通用寄存器，每个寄存器 4096bit。
SIMD32  模式下，1536   个通用寄存器，每个寄存器 1024bit。
```

源码里的 `unit_t` 是 1024-bit chunk：

```c
typedef union {
    int fix[32];
    unsigned int ufix[32];
    float flt[32];
    unsigned short flt_16[64];
    char fix_8[128];
    unsigned char ufix_8[128];
} unit_t;
```

因此不能把 `unit_t == 一个完整 SIMD128 operand`。更准确的模型是：

```text
SIMD128 logical operand = 4096 bits = 512 bytes = 4 x unit_t chunks
SIMD32  logical operand = 1024 bits = 128 bytes = 1 x unit_t chunk
```

## HADD 结论

`HADD` 文档中“256 个 SIMD 分量，每个分量 16bit”是自洽的：

```text
256 lanes x 16 bits = 4096 bits
```

示例源码也支持源码层使用 `HADD` 作为半精度 elementwise add，例如
`softmax_1/task*/subtask1/template/task*_subtask1.cpp` 里会生成：

```csv
HADD,HADD...,input0_tag,input1_tag,output_tag,,0,0
```

CSV 里的长字符串只是 build 阶段的 operand tag；`common_oper/inst_blk_map.cpp`
会把 tag 分配成 PE-local operand index。最终指令里只有 index，没有字符串。

## 伪指令展开

`HLDT/HSTT/COPYT/SSTM/SSTSHIF` 等 4096-bit 指令在 `common_oper/csv_oper.cpp`
中会展开为 4 条底层 1024-bit 指令。这个展开与 `unit_t` 的 1024-bit chunk 尺度
一致。

补充：伪指令展开不仅影响 lane 数量，也影响 instruction row count、exeBlock PC
布局和访存 base-slot 校验。`ILDMT/HSTT/COPYT` 这类 template/runtime 语义见
`MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md`。

普通算术指令如 `HADD` 不在这个伪指令展开表里。mock/runtime 解释器应把它作为
SIMD128 logical operand 上的 4096-bit 运算处理，而不是只处理一个 128-byte
`unit_t`。
