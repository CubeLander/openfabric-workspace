# 运行时执行模型

这个主题聚焦 MICC/runtime 层面的任务生命周期：task / subtask / instance 如何
组织，Vendor ABI 如何描述任务并行，以及 exeBlock/subtask 结构体的具体定义。

## 阅读顺序

1. [Task/Subtask Instance 运行时模型](task-subtask-instance-runtime-model.md) —
   task → subtask → instance → graph → exeBlock 的生命周期
2. [Vendor ABI: 任务并行与资源依赖](vendor-abi-task-parallelism.md) — 4 task
   slot、共享 operand 空间、exeBlock 数据流边
3. [Vendor ExeBlock/Subtask 结构体定义](vendor-exeblock-subtask-struct.md) —
   `exeBlock_conf_info_t` 和 `sub_task_conf_info_t` 的字段含义

## 交叉阅读

- [SoC 系统架构](../soc-system/README.md) — CBUF/MICC 装载流程
- [PE 微架构](../pe-microarchitecture/README.md) — PE 侧 exeBlock 如何被执行
- [GEMM 案例](../gemm-case-study/README.md) — runtime 模型在 GEMM 中的具体体现
