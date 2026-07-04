# RTL 编码层

这一页只讲一件事：`inst_t` 是怎么被打成 RTL 侧的窄格式位域的。

和 [CBUF 数据面](cbuf.md) 不同，这里不再讨论 simulator 的宽结构镜像，而是直接看 `task_print.cpp` 里写给 `rtl_bin/` 的那条输出线。

## 1. 这条线的定位

`insts_file.bin` 里的 `inst_t` 是宽语义记录，给 simulator / 编译器共享使用。

`rtl_bin/*` 里的内容才是窄格式编码结果。它们来自同一条编译链，但不是同一个消费对象：

```text
CSV / template
  -> inst_t 宽结构
  -> simulator_bin/insts_file.bin
  -> task_print.cpp 再打包
  -> rtl_bin/*
```

源码入口：

- [task_print.cpp](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/task_print.cpp)
- [inst_def.h](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/common/src/inst_def.h)

## 2. RTL 结构总览

`task_print.cpp` 会把宽 `inst_t` 分流成这些 RTL 结构：

| 宽指令族 | RTL 结构 | 说明 |
|---|---|---|
| `OP_STM` | `inst_t_stm_for_rtl` | store with shift/mask style 控制 |
| `OP_STD / OP_STCNST / OP_LDN / OP_LDM / OP_LDSHIF / OP_STSHIF / OP_LDMD64 / OP_STMD64 / OP_LDCNST` | `inst_t_ldst_for_rtl` | load/store 窄格式 |
| `OP_FRCP / OP_FSQRT / OP_FRSQRT / OP_FSIN / OP_FCOS / OP_FLOG2 / OP_FEXP2` | `inst_t_cal2_for_rtl` | special cal family |
| `OP_MOVE` | `inst_t_move_for_rtl` | move 窄格式 |
| `OP_FXP2FP` | `inst_t_cal_for_rtl` | 8-bit imm 的 cal family |
| `OP_COPY` | `inst_t_copy_for_rtl` | flow/copy 侧的专用编码 |
| `OP_IMM / OP_FIMM` | `inst_t_imm_for_rtl` | immediate family |
| 其他普通 CAL 指令 | `inst_t_cal2_for_rtl` | 默认 cal 窄格式 |

## 3. 位域骨架

### `inst_t_cal_for_rtl`

```text
opCode:8
base_addr_idx:4
src_operands_idx0:12
src_operands_idx1:12
dst_operands_idx0:12
imm:8
no_use:2
end_inst_flag:1
block_idx:5
```

### `inst_t_cal2_for_rtl`

```text
opCode:8
base_addr_idx:4
src_operands_idx0:12
src_operands_idx1:12
dst_operands_idx0:12
imm:10
end_inst_flag:1
block_idx:5
```

### `inst_t_imm_for_rtl`

```text
opCode:8
base_addr_idx:4
imm_1:24
dst_operands_idx0:12
imm_2:8
no_use:2
end_inst_flag:1
block_idx:5
```

### `inst_t_move_for_rtl`

```text
opCode:8
base_addr_idx:4
src_operands_idx0:12
src_operands_idx1:12
no_use:22
end_inst_flag:1
block_idx:5
```

### `inst_t_ldst_for_rtl`

```text
opCode:8
base_addr_idx:4
imm:21
dst_operands_idx0:12
simd_mode:2
int8_offset:1
shiftR_idx:3
shiftR_cnt:6
mask_enable:1
end_inst_flag:1
block_idx:5
```

### `inst_t_copy_for_rtl`

```text
opCode:8
base_addr_idx:4
src_operands_idx0:12
dst_operands_idx0:12
pos_x:2
pos_y:2
no_use:18
end_inst_flag:1
block_idx:5
```

### `inst_t_stm_for_rtl`

```text
opCode:8
base_addr_idx:4
imm:21
dst_operands_idx0:12
simd_mode:2
int8_offset:1
shiftR_idx:3
shiftR_cnt:6
no_use:1
end_inst_flag:1
block_idx:5
```

## 4. 宽字段到窄字段的来源

`task_print.cpp` 的核心规则可以压缩成下面几条：

```text
大多数指令:
  base_addr_idx = iter_exe_cond

COPY:
  base_addr_idx = flow_ack

STM / LDST:
  从 dst_pes_pos[0] / extra_fields 拆出 shift, mask, simd_mode
```

这说明 `inst_t` 里的以下字段都不是冗余：

- `iter_exe_cond`
- `flow_ack`
- `dst_pes_pos`
- `extra_fields`

它们是给不同 opcode family 预留的编码入口。

## 5. 关键映射

### `iter_exe_cond`

大多数 opcode 会把它直接映射到 `base_addr_idx`。结合 `instance_conf_info_t` 的 `base_addr[4]`，就得到：

```text
effective_addr = base_addr[base_addr_idx] + imm
```

### `flow_ack`

`OP_COPY` 是例外，它把 `flow_ack` 直接写成 `base_addr_idx`。这说明 flow/copy 的 base slot 语义和普通 load/store 不是同一路。

### `dst_pes_pos[0]`

这个字段会在不同指令里被复用成控制位来源：

- `OP_STM`：拆 `shiftR_idx` / `shiftR_cnt`
- `OP_LDSHIF` / `OP_STSHIF`：拆 shift 和 int8 标记
- `OP_LDM`：并入 `simd_mode`
- `OP_LDCNST`：并入 `simd_mode`
- `OP_COPY`：编码 PE 相对位置

### `extra_fields`

`extra_fields` 是逃逸位。常见用途包括：

- `OP_STD / OP_LDN`：mask / int8 / simd / shift
- `OP_LDM`：simd / mask / end flag
- `OP_STSHIF`：补充 mask / simd
- `OP_LDCNST`：int8 / mask / end flag

### `FRCP` 系列

`FRCP / FSQRT / FRSQRT / FSIN / FCOS / FLOG2 / FEXP2` 在 RTL 层会被折叠成同一个窄 opcode family，再用 `imm` 的 bit 位区分子类型。

所以这里的 `imm` 更像 mode mask，而不是普通算术立即数。

## 6. 这页怎么用

如果你在查：

- 某个 opcode 的 RTL 位域怎么拼
- `iter_exe_cond` 为什么会变成 base slot
- 为什么 `COPY` 要走 `flow_ack`

那就看这一页。

如果你在查：

- `insts_file.bin` 的文件布局
- `exeBlock_conf_info_t` / `instance_conf_info_t` 的字节偏移

那就回到 [CBUF 数据面](cbuf.md)。
