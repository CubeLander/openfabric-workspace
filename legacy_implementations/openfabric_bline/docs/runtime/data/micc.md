# MICC 数据面

MICC 这页专门讲 `tasks_conf_info_file.bin`、`subtasks_conf_info_file.bin`，以及它们对应的控制表结构。

它们在运行时会被拼进同一个镜像：

```text
micc_file.bin = tasks_conf_info_file.bin
              + subtasks_conf_info_file.bin
```

## 1. MICC 区间图

```text
MICC region
  [tasks]   -> MICC_BASE_ADDR
  [subtask] -> MICC_SUB_BASE
```

逻辑边界定义在：

- [micc_com_def.h](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/common/src/micc_com_def.h)
- [dma_com_def.h](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/common/src/dma_com_def.h)

## 2. 文件尺寸

| 文件 | 固定尺寸 | 说明 |
|---|---|---|
| `tasks_conf_info_file.bin` | 480 B | `4 task * 120 B` |
| `subtasks_conf_info_file.bin` | 8,522,496 B | `4 task * 8 subtask * 266,328 B` |

合起来，`micc_file.bin` 的主线固定镜像大小是：

```text
8,522,976 bytes
```

## 3. `task_conf_info_t`

`task_conf_info_file.bin` 装的是 `task_conf_info_t`。

### `task_conf_info_t` 总尺寸

```text
sizeof(task_conf_info_t) = 120 bytes
```

### 字节布局

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `is_exe_start` | 1 B | task 图入口 |
| 1 | `is_exe_end` | 1 B | task 图出口 |
| 8 | `subtasks_amount` | 8 B | subtask 数 |
| 16 | `execute_times` | 8 B | 重复执行次数 |
| 24 | `subtasks_idx[0..7]` | 64 B | subtask 索引表 |
| 88 | `suc_tasks[0..3]` | 32 B | 后继 task 索引表 |

### 这条布局线怎么读

`task_conf_info_t` 不描述 PE 级细节，它只描述：

- task 级顺序
- task 是否是入口/出口
- task 里有哪些 subtask

## 4. `sub_task_conf_info_t`

`subtasks_conf_info_file.bin` 装的是 `sub_task_conf_info_t`。

### `sub_task_conf_info_t` 总尺寸

```text
sizeof(sub_task_conf_info_t) = 266,328 bytes
```

### 字节布局

| 偏移 | 字段 | 大小 | 含义 |
|---|---|---|---|
| 0 | `is_exe_start` | 1 B | subtask 图入口 |
| 1 | `is_exe_end` | 1 B | subtask 图出口 |
| 8 | `instances_amount` | 8 B | 当前 subtask 要执行多少个 instance |
| 16 | `instances_conf_mem_based_addr` | 8 B | instance 表偏移 |
| 24 | `suc_subtasks[0..3]` | 32 B | 后继 subtask 索引表 |
| 56 | `root_block_amount` | 8 B | root block 数 |
| 64 | `block_amount` | 8 B | block 总数 |
| 72 | `exeBlocks_conf_info[0]` | 520 B | 第一个 block |
| ... | `exeBlocks_conf_info[]` | 266,240 B | 整块 block 表 |
| 266,312 | `subtask_idx` | 8 B | subtask 编号 |
| 266,320 | `task_idx` | 8 B | task 编号 |

### `exeBlocks_conf_info[]` 的尺寸

```text
sizeof(exeBlock_conf_info_t) = 520 bytes
32 blocks * 520 bytes = 16,640 bytes / subtask
```

但这里要注意：`sub_task_conf_info_t` 不是只放 block 表。它还包含完整的控制骨架，所以总尺寸会到 266 KB 级别。

### 这条布局线怎么读

`sub_task_conf_info_t` 是 MICC 侧最重要的 subtask 控制体。它同时携带：

- 实例数
- instance 表偏移
- block 数
- root block 数
- block 详细表

所以它是“subtask 的运行时控制包”，不是单纯的索引表。

## 5. `subtask` 和 `instance` 的关系

当前主线里，subtask 的实例数和 instance 表不是同一件事：

- `instances_amount` 说明这个 subtask 需要执行多少次
- `instances_conf_mem_based_addr` 说明它在 instance 表里从哪里取基址信息

运行时真正执行时，MICC 还会把当前 instance 的 `base_addr[4]` 送到 PE / 执行块上下文里。

## 6. MICC 相关写入口

- [task_create.cpp](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/task_create.cpp)
- [task_print.cpp](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/task_print.cpp)
- [build_app/main.cpp](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/build_app/main.cpp)
- [run_mtr.sh](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/build_app/run_mtr.sh)

## 7. 运行时提醒

`is_exe_start` / `is_exe_end` 是图结构标记，不是 device start doorbell。

真正让 device 动起来的，仍然是 `DPU_Kernel_Start()` 写 MICC start 寄存器那一步。
