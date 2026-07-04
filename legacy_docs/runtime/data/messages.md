# 消息层（Messages）

这一页讲的不是落盘文件，而是 runtime 运行时在 mesh / control 路径上交换的消息体。

这里的核心点是：

- 静态文件告诉 runtime “表长什么样”
- 消息体告诉 runtime “现在该把哪个表发给谁”

这里反复出现的 `pe_dst` / `src_pe_pos` / `src_pe_dst` 都是 `position_t`：

```text
position_t = { x: uint64_t, y: uint64_t, z: uint64_t }
size = 24 bytes
```

## 1. 总包头 `router_msg_t`

`router_msg_t` 是运行时控制总线上的通用包头。

### 总尺寸

```text
sizeof(router_msg_t) = 104 bytes
```

### 字节布局

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `type` | 4 B | 消息类型 |
| 8 | `way` | 8 B | 路由方式 / 路径信息 |
| 16 | `pData` | 8 B | 负载指针 |
| 24 | `send_time` | 8 B | 发送时间 |
| 32 | `src_blk_idx` | 8 B | 源 block |
| 40 | `subtask_idx` | 8 B | subtask 编号 |
| 48 | `src_pe_pos` | 24 B | 源 PE 坐标 |
| 72 | `count` | 8 B | 计数 |
| 80 | `flow_ack` | 8 B | flow ack |
| 88 | `pe_sel[16]` | 16 B | PE 选择掩码 |

### 常见消息类型

`router_msg_type_t` 里和当前主线最相关的类型包括：

- `MICC2PE_CONF`
- `MICC2PE_ACTIVE`
- `MICC2PE_INST`
- `PE2MICC_ACK`
- `PE2MICC_DONE`
- `PE2PE_ACTIVE`
- `PE2PE_COPY_DATA`
- `PE2SPM_LOAD_REQ`
- `PE2SPM_STORE_REQ`
- `SEND_EXEBLOCK_CONF_INFO`
- `SEND_INST_CONF_INFO`
- `SEND_ACTIVE_MSG`
- `BLOCK_CONF_IS_SENT`
- `INST_CONF_IS_SENT`

这些类型不是文件名，而是运行时模块之间的控制信号分类。

## 2. MICC -> PE 消息

### `micc2pe_exeBlock_config_msg_t`

```text
sizeof(micc2pe_exeBlock_config_msg_t) = 616 bytes
```

字节布局：

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `exe_block_ctrl` | 592 B | PE 内部 block 控制上下文 |
| 592 | `pe_dst` | 24 B | 目标 PE 坐标 |

`exe_block_ctrl_t` 的总尺寸是：

```text
sizeof(exe_block_ctrl_t) = 592 bytes
```

它的核心字段布局如下：

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `selected` | 1 B | 是否被选中 |
| 1 | `valid` | 1 B | 是否有效 |
| 2 | `enabled` | 1 B | 是否启用 |
| 8 | `priority` | 8 B | 优先级 |
| 16 | `block_idx` | 8 B | block 编号 |
| 24 | `subtask_idx` | 8 B | subtask 编号 |
| 32 | `instance_idx` | 8 B | instance 编号 |
| 40 | `task_idx` | 8 B | task 编号 |
| 48 | `pending_activations` | 8 B | 待激活数 |
| 56 | `pending_acks` | 8 B | 待 ack 数 |
| 64 | `instance_conf_info` | 32 B | 当前 instance 的 base table |
| 96 | `inst_write_counter` | 8 B | 已写入指令计数 |
| 104 | `pre_active` | 1 B | 前置 active 标记 |
| 105 | `pre_ack` | 1 B | 前置 ack 标记 |
| 106 | `is_stages_waiting[0..4]` | 5 B | stage 等待状态 |
| 111 | `is_ld_finish` | 1 B | LD 是否完成 |
| 112 | `exeBlock_conf` | 472 B | block 详细配置 |
| 584 | `disable_subtask` | 1 B | 是否禁用 subtask |

### `micc2pe_inst_msg_t`

```text
sizeof(micc2pe_inst_msg_t) = 1,272 bytes
```

字节布局：

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `block_idx[4]` | 32 B | 每包 4 个 block index |
| 32 | `inst[4]` | 1,216 B | 每包 4 条 `inst_t` |
| 1,248 | `pe_dst` | 24 B | 目标 PE 坐标 |

这里的 `inst[4]` 是宽指令本体，所以消息体很大。

### `micc2pe_active_msg_t`

```text
sizeof(micc2pe_active_msg_t) = 120 bytes
```

字节布局：

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `buf_idx` | 8 B | 当前 buffer |
| 8 | `pe_scale` | 8 B | PE scale |
| 16 | `base_peidx` | 8 B | 基准 PE id |
| 24 | `instance_idx` | 8 B | 当前 instance id |
| 32 | `subtask_idx` | 8 B | subtask id |
| 40 | `task_idx` | 8 B | task id |
| 48 | `instance_conf_info` | 32 B | 当前 instance 的 base table |
| 80 | `pe_dst` | 24 B | 目标 PE 坐标 |
| 96 | `instance_base` | 8 B | instance base 指针/偏移 |
| 104 | `instance_base_noneed` | 4 B | 辅助控制位 |

这里的总尺寸是 120 B，末尾还有对齐填充。

### `pe2micc_instance_done_msg_t`

```text
sizeof(pe2micc_instance_done_msg_t) = 56 bytes
```

字节布局：

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `subtask_idx` | 8 B | subtask id |
| 8 | `task_idx` | 8 B | task id |
| 16 | `pe_dst` | 24 B | PE 坐标 |
| 32 | `disable_subtask` | 1 B | 是否禁用 subtask |
| 40 | `block_idx` | 8 B | block id |

## 3. PE 间与 SPM 消息

### `pe2pe_active_msg_t`

```text
sizeof(pe2pe_active_msg_t) = 96 bytes
```

字节布局：

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `block_idx` | 8 B | 当前 block |
| 8 | `subtask_idx` | 8 B | subtask id |
| 16 | `task_idx` | 8 B | task id |
| 24 | `pe_dst` | 24 B | 目标 PE 坐标 |
| 48 | `instance_conf_info` | 32 B | 当前 instance 的 base table |
| 80 | `src_block_idx` | 8 B | 源 block |
| 88 | `dst_block_idx` | 8 B | 目标 block |

### `pe2pe_copy_data_msg_t`

```text
sizeof(pe2pe_copy_data_msg_t) = 200 bytes
```

字节布局：

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `value` | 128 B | `unit_t` 载荷 |
| 128 | `operand_idx` | 8 B | operand 编号 |
| 136 | `block_idx` | 8 B | block id |
| 144 | `subtask_idx` | 8 B | subtask id |
| 152 | `task_idx` | 8 B | task id |
| 160 | `pe_dst` | 24 B | 目标 PE 坐标 |
| 184 | `ld_mask` | 8 B | load mask |
| 192 | `addr` | 8 B | 地址 |

### `spm_return_dst_t`

```text
sizeof(spm_return_dst_t) = 56 bytes
```

字节布局：

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `src_pe_dst` | 24 B | 源 PE 坐标 |
| 24 | `operand_idx` | 8 B | operand 编号 |
| 32 | `block_idx` | 8 B | block id |
| 40 | `subtask_idx` | 8 B | subtask id |
| 48 | `task_idx` | 8 B | task id |

### `pe2spm_load_msg_t`

```text
sizeof(pe2spm_load_msg_t) = 160 bytes
```

关键偏移：

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `spm_addr` | 8 B | 目标 SPM 地址 |
| 8 | `load_type` | 8 B | load 类型 |
| 16 | `simd_mode` | 8 B | SIMD 模式 |
| 24 | `INT8_offset` | 8 B | int8 偏移 |
| 32 | `shift_cnt` | 8 B | shift 计数 |
| 40 | `shift_reg_idx` | 8 B | shift 寄存器索引 |
| 48 | `mask_enable` | 8 B | mask 开关 |
| 56 | `ld_mask` | 8 B | load mask |
| 64 | `Loadflag` | 1 B | load 标记 |
| 72 | `spec_addr_offset` | 8 B | 特殊地址偏移 |
| 80 | `return_dst` | 56 B | 返回目的地 |
| 136 | `pe_dst` | 24 B | 目标 PE 坐标 |

### `pe2spm_store_msg_t`

```text
sizeof(pe2spm_store_msg_t) = 280 bytes
```

关键偏移：

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `spm_addr` | 8 B | 目标 SPM 地址 |
| 8 | `store_type` | 8 B | store 类型 |
| 16 | `INT8_offset` | 8 B | int8 偏移 |
| 24 | `shift_cnt` | 8 B | shift 计数 |
| 32 | `shift_reg_idx` | 8 B | shift 寄存器索引 |
| 40 | `value` | 128 B | `unit_t` 写回值 |
| 168 | `return_dst` | 56 B | 返回目的地 |
| 224 | `pe_dst` | 24 B | 目标 PE 坐标 |
| 240 | `mask` | 8 B | mask |
| 248 | `mask_enable` | 8 B | mask 开关 |
| 256 | `ld_mask` | 8 B | load mask |
| 264 | `Loadflag` | 1 B | load 标记 |

## 4. MICC / task 载体消息

### `task_conf_info_msg_t`

```text
sizeof(task_conf_info_msg_t) = 136 bytes
```

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `task_conf_info_addr` | 8 B | task 表地址 |
| 8 | `task_idx` | 8 B | task id |
| 16 | `task_conf_info` | 120 B | task 控制体 |

### `sub_task_conf_info_msg_t`

```text
sizeof(sub_task_conf_info_msg_t) = 266,352 bytes
```

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `task_idx` | 8 B | task id |
| 8 | `subtask_conf_info_addr` | 8 B | subtask 表地址 |
| 16 | `subtask_idx` | 8 B | subtask id |
| 24 | `sub_task_conf_info` | 266,328 B | subtask 控制体 |

### `instance_conf_info_msg_t`

```text
sizeof(instance_conf_info_msg_t) = 144 bytes
```

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `subtask_idx` | 8 B | subtask id |
| 8 | `instances_conf_mem_addr` | 8 B | instance 表偏移 |
| 16 | `instances_conf_info[0..3]` | 128 B | 4 个 instance base table |

## 5. 运行时怎么理解这些消息

这些消息体不是落盘二进制，它们是 runtime 里“传对象”的方式。

可以把它们理解成：

```text
静态文件
  -> 变成 message
  -> runtime mesh 发送
  -> MICC / PE / SPM 执行
```

## 6. RTL 紧凑表

### `task_for_rtl_t`

```text
sizeof(task_for_rtl_t) = 32 bytes
```

字节布局：

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `execute_times` | 8 B | 执行次数 |
| 8 | `noused` | 8 B | 保留 |
| 16 | `nouse1` | 8 B | 保留 |
| 24 | `nouse2` | 8 B | 保留 |

### `subtask_for_rtl_t`

```text
sizeof(subtask_for_rtl_t) = 8 bytes
```

它是一个 64-bit packed 控制字：

| bit range | 字段 | 含义 |
|---|---|---|
| 0..4 | `block_amount` | block 数 |
| 5..9 | `root_block_amount` | root block 数 |
| 10..31 | `instances_amount` | instance 数 |
| 32..63 | `nouse` | 保留 |

它们是更窄的控制面输出，主要服务 RTL / 调试，不是 simulator 主表。

## 7. 相关代码入口

- [mesh_com_def.h](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/common/src/mesh_com_def.h)
- [pe_com_def.h](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/common/src/pe_com_def.h)
- [DpuAPI.c](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/dpuapi/DpuAPI.c)
