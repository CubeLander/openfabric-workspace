# 控制面（Control）

这页是 runtime 主线里的“执行控制面”文档。我们把它写成一条端到端时序：

1. 哪些源码产生 `task/subtask/exeblock/instance` 语义。
2. 哪些工具把它们打成 `cbuf_file.bin/micc_file.bin`。
3. RISC-V 控制程序如何把这些镜像交给 MICC。
4. MICC 真正启动执行的时刻与信号。

## 先读什么（最短路径）

- [runtime/data/README.md](../data/README.md)
- [runtime/data/cbuf.md](../data/cbuf.md)
- [runtime/data/micc.md](../data/micc.md)
- [runtime/data/messages.md](../data/messages.md)
- [vendor_reference/runtime_evidence/riscv-control-and-dpuapi.md](../../vendor_reference/runtime_evidence/riscv-control-and-dpuapi.md)
- [vendor_reference/runtime_evidence/simict-runtime.md](../../vendor_reference/runtime_evidence/simict-runtime.md)
- [vendor_reference/common_oper/task-creation-generategraph-chain.md](../../vendor_reference/common_oper/task-creation-generategraph-chain.md)
- [vendor_reference/common_oper/subtask-graph-compile-chain.md](../../vendor_reference/common_oper/subtask-graph-compile-chain.md)
- [vendor_reference/common_oper/binary-artifact-generation-pipeline.md](../../vendor_reference/common_oper/binary-artifact-generation-pipeline.md)
- [vendor_reference/cases/softmax/softmax-riscv-instruction-load.md](../../vendor_reference/cases/softmax/softmax-riscv-instruction-load.md)

## 控制面对象层级

核心语义关系是：

- `task`：应用层一个可复用调度单元。
- `subtask`：task 内的顺序片段（`suc_subtasks` 形成链）。
- `exeblock`：PE 上一个可执行块，含 stage 边界和前驱后继。
- `instance`：一个 subtask 的运行时地址上下文，核心是 `base_addr[4]`。

这四层在源码里最终落成如下结构：

- `tasks_conf_info_file.bin`（`task_conf_info_t[]`）
- `subtasks_conf_info_file.bin`（`sub_task_conf_info_t[]`）
- `exeblock_conf_info_file.bin`（`exeBlock_conf_info_t[]`）
- `instance_conf_info_file.bin`（`instance_conf_info_t[]`）

合并结果为：

- `cbuf_file.bin`：`insts + exeblock + instance`
- `micc_file.bin`：`tasks + subtasks`

## 控制链的关键点

这条链里最重要的不是“文件名”，而是控制动作的顺序：

```text
app*.conf
  -> task_create.cpp 解析 task/subtask 语义
  -> task_print.cpp 组织 task / subtask / exeblock / instance
  -> CBUF / MICC 二进制镜像落盘
  -> RISC-V guest 通过 DPU_CbufTransfer / DPU_MiccTransfer 装载
  -> DPU_Kernel_Start 写 MICC 寄存器
  -> MICC doorbell 触发 device 侧执行
  -> DPU_Kernel_Wait_Finish 轮询完成位
  -> DPU_App_Finish 收尾
```

这里有两个容易混淆的边界：

1. `is_exe_start / is_exe_end` 只是在 `task/subtask` 图里做结构标记，不是启动门铃。
2. 真正的启动信号是 `MICC_BUFx_START = 1`，也就是 `DPU_Kernel_Start()` 里写出去的 MMIO。

`instance` 也不是附属元数据，它是运行时地址环境本身。

`task_print.cpp` 会把每个 `subtask` 的 `instances_conf_mem_based_addr` 写成：

```text
m_instance_start_idx * sizeof(instance_conf_info_t)
```

随后 `DPU_Kernel_Start()` 再把当前 `instance_base` 写入 `MICC_INSTANCE_BASE`，让 device 侧在本次执行中读取对应的 `base_addr[4]` 槽位。

所以在这个项目里，`instance` 的阅读方式应该是：

```text
subtask 选择哪一段 instance 表
  -> instance 表决定 base_addr[4]
  -> base_addr[4] 决定当前 instance 看到的 address space
```

## 端到端时序（ping-pong buffer 版）

在典型 case 里（如 `softmax_1` / `gemm_template_fusion`），主循环是：

```text
run_app_riscv.sh / testcase workflow
  -> build_app/run_mtr.sh 或 testcase/application/build_app/main.cpp
  -> result/cbuf_file.bin, result/micc_file.bin, input_data.bin, riscv_program
  -> SimICT runtime 启动
  -> RISC-V riscv_program: DPU_CbufTransfer / DPU_MiccTransfer
  -> (可选) DMA 输入
  -> DPU_Kernel_Start(inst_reload, TASK_NUM, instance_base, noneed, buf_num, ...)
  -> DPU_Kernel_Wait_Finish(buf_num_prev)
  -> (可选) DMA 输出
  -> DPU_App_Finish()
```

`testarm.c` 的多 app 场景中常见于两个 buffer 轮换：

- `app_num` 奇偶决定 `buf_num = app_num % 2`。
- `inst_reload` 首次为 `1`，之后为 `0`（避免重复 reload）。
- 下一次启动前等待上一轮 `MICC_BUFx_FINISH`。

这个模式能做到“计算流水线与 host 侧 DMA 的重叠”。

## 启动寄存器读法

`DPU_Kernel_Start()` 里那几个参数可以直接按 runtime 角色来读：

| 参数 | 写入寄存器 | 语义 |
|---|---|---|
| `inst_reload` | `MICC_BUFx_INST` | 是否重载 inst 镜像 |
| `task_num` | `MICC_BUFx_TASK` | task mask，`1/2/3/4` -> `1/3/7/15` |
| `instance_base` | `MICC_INSTANCE_BASE` | 当前 instance 表基址 |
| `instance_base_noneed` | `MICC_INSTANCE_BASE_NONEED` | 兼容/扩展字段 |
| `buf_num` | `MICC_BUFx_START` 选择 | 选择 `buf0` 或 `buf1` |

也就是说，`start` 不是抽象意义上的“开始算”，而是一个很具体的 MMIO doorbell。

## 配置链：`app.conf` 如何变成控制结构

`Task` 和 `SubTask` 来自 `app*.conf`，解析链在这两个文件：

- `task_create.cpp`（读取 `task_name / Execute Times / subtask_num`，`SubTask::create_subtask` 读 `Instance Times / code_path / csv_amount / graph height / graph width`）
- `task_print.cpp`（把 `task/subtask`、`graph`、`exeblock`、`instance` 写入二进制）

更细一点可以认为有两层边界：

```text
app*.conf（语义参数）
  -> task_create.cpp 生产 task/subtask 内部图节点
  -> build_app/main.cpp / INST_BLK_MAP
  -> task_print.cpp 产出 MICC + CBUF 二进制表
```

其中 `task_print.cpp` 的关键点：

- `subtask` 链：`sub_tasks_conf_info[prev].suc_subtasks[0]` 自动串联。
- `task` 链：`tasks_conf_info[prev].suc_tasks[0]` 自动串联。
- `instances_conf_mem_based_addr`：`m_instance_start_idx * sizeof(instance_conf_info_t)`。
- `is_exe_start / is_exe_end` 只用于图结构标识。
- `exeBlock_conf_info_t` 会被按 PE 维度写回，成为 runtime/simulator 侧的 block 调度信息。

## `DPU_Kernel_Start` 与 MICC 寄存器（真启动信号）

`dpuapi/DpuAPI.c` 的实现可直接确认：

```c
int DPU_Kernel_Start(int inst_reload, int task_num, void* instance_base,
                     unsigned instance_base_noneed, int buf_num, int time_type)
{
    int task_enable = 0;
    switch (task_num) {
    case 1: task_enable = 1; break;
    case 2: task_enable = 3; break;
    case 3: task_enable = 7; break;
    case 4: task_enable = 15; break;
    }
    *(unsigned*)MICC_INSTANCE_BASE = (unsigned)instance_base;
    *(unsigned*)MICC_INSTANCE_BASE_NONEED = (unsigned)instance_base_noneed;
    if (buf_num) {
        *(unsigned*)MICC_BUF1_INST = (unsigned)inst_reload;
        *(unsigned*)MICC_BUF1_TASK = task_enable;
        *(unsigned*)MICC_BUF1_START = 1;
    } else {
        *(unsigned*)MICC_BUF0_INST = (unsigned)inst_reload;
        *(unsigned*)MICC_BUF0_TASK = task_enable;
        *(unsigned*)MICC_BUF0_START = 1;
    }
}
```

所以它真正做了三件事：

1. 写入 instance 基址。
2. 写入 per-buffer 的 inst/reload 与 task mask。
3. 拉起 `MICC_BUFx_START`。

这也是为什么我们把“执行控制面”的最高优先级放在 `runtime/control`：

```text
控制面
  = 结构如何组织
  + 镜像如何装载
  + doorbell 如何触发
  + 完成位如何回收
```

`DPU_Kernel_Wait_Finish` 是轮询 `MICC_BUF0_FINISH / MICC_BUF1_FINISH`。

## 关键寄存器映射（控制信号对照）

`MICC` 寄存器定义在：

- [micc_com_def.h](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/common/src/micc_com_def.h)

| 字段 | 写入点 | 语义 |
|---|---|---|
| `MICC_BUF0_INST / MICC_BUF1_INST` | `DPU_Kernel_Start()` | inst_reload 标记（通常首轮 1，之后 0） |
| `MICC_BUF0_TASK / MICC_BUF1_TASK` | `DPU_Kernel_Start()` | task_mask: task_num=1/2/3/4 -> 1/3/7/15 |
| `MICC_BUF0_START / MICC_BUF1_START` | `DPU_Kernel_Start()` | **启动门铃（doorbell）** |
| `MICC_BUF0_FINISH / MICC_BUF1_FINISH` | `DPU_Kernel_Wait_Finish()` | 完成位 |
| `MICC_INSTANCE_BASE` | `DPU_Kernel_Start()` | 运行时 instance table 基址（host 侧视图） |
| `MICC_INSTANCE_BASE_NONEED` | `DPU_Kernel_Start()` | 旁路/扩展字段（当前代码有入参，部分 case 用于 `DPU_Kernel_Start_noneed` 流） |
| `MICC_APP_FINISH` | `DPU_App_Finish()` | app 结束信号 |

`DPU_CbufTransfer()` / `DPU_MiccTransfer()` 写路径在 `DpuAPI.c` 中分别触发 CBUF/MICC 的 DMA 通道；`DPU_DMATransferFinish(flag)` 轮询 DMA 完成位。

## 连接到脚本和 workflow 的入口

- 测试脚本：
  - [test/run_app_riscv.sh](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/test/run_app_riscv.sh)
  - [testcase/workflow/scripts/replay_package.sh](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/workflow/scripts/replay_package.sh)
- 打包入口：
  - [testcase/application/build_app/run_mtr.sh](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/build_app/run_mtr.sh)
  - [testcase/application/build_app/main.cpp](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/build_app/main.cpp)
  - [testcase/workflow/README.md](/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/workflow/README.md)

## 目前可确认 / 仍需确认

已确认（高可信）：

- 控制面二进制生成链路（`build_app` 到 `result`/`runtime config`）有清晰源码链。
- `DPU_Kernel_Start` 写入 `MICC_BUFx_START` 的时序是硬启动点。
- `is_exe_start/is_exe_end` 是图结构标记，不是 start 信号。

待确认（低优先）:

- `DPU_Kernel_Start_noneed()` 在当前 snapshot 中未在 `DpuAPI` 看到定义，但若调用存在，说明有一条外部扩展路径。
- SIMICT 端对 `MICC_*` 的具体读写路径细节（关闭源码限制，待通过 trace 或模块行为验证）。

## 控制面到数据面、行为面的阅读建议

如果你想继续下一层：

1. 先看 [runtime/data](../data/README.md) 完整确认字段。
2. 再看 [runtime evidence](../../vendor_reference/runtime_evidence/README.md)
   看 RISC-V / DpuAPI / SimICT 行为证据。
3. case / bundle / build workflow 事实优先看
   [vendor_reference/cases](../../vendor_reference/cases/README.md) 和
   [common_oper](../../vendor_reference/common_oper/README.md)。
4. 少量 runtime binary/OCR 追溯材料保留在
   [runtime_ocr](../debug/runtime_ocr/README.md)。
