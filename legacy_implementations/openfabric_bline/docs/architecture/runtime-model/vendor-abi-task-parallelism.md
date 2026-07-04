# Vendor ABI: Task Parallelism And Register Dependency

The DFU3500 ABI explicitly supports up to 4 tasks per app. The common_oper
source shows these tasks share the same operand/register address space on each
PE, with resource statistics aggregated at app level. However, the legacy
printer also writes task successor chains, so "4 task lock-free parallelism"
should be recorded as vendor engineer claim + source circumstantial evidence,
not fully proven semantics in common_oper.

## ABI Capacity Constants

From reconstructed vendor header `pe_com_def.h`:

```cpp
#define MAX_APP_AMOUNT (1)
#define MAX_CUR_TASK_CONF_PER_APP (4)
#define MAX_SUBTASK_PER_TASK (8)
#define MAX_TASK_FOLLOW_PER_TASK (4)
#define MAX_TASK_AMOUNT (MAX_APP_AMOUNT * MAX_CUR_TASK_CONF_PER_APP)
```

ABI shape:

```text
1 app * 4 task slots
each task * 8 subtask slots
task can name up to 4 successor tasks
```

## Task Config Struct

```cpp
typedef struct _task_conf_info_t {
    char is_exe_start;
    char is_exe_end;
    uint64_t subtasks_amount;
    uint64_t execute_times;
    uint64_t subtasks_idx[MAX_SUBTASK_PER_TASK];
    uint64_t suc_tasks[MAX_TASK_FOLLOW_PER_TASK];
} task_conf_info_t;
```

## Operand Allocation Shares App-Level Register Space

`INST_BLK_MAP::start_map_app` records one PE-local app resource base:

```cpp
pApp_res->block_idx_start = m_pes[i].m_blk_slots_used_counter;
pApp_res->node_idx_start = m_pes[i].m_pGraph_nodes.size();
pApp_res->inst_start_idx = m_pes[i].m_inst_slots_used_counter;
pApp_res->reg_start_idx = m_pes[i].m_reg_counter;
```

For each task, `start_map_task` initializes task state from the app start:

```cpp
m_pTask_res[i]->block_idx_start = m_pes[i].m_blk_slots_used_counter;
m_pTask_res[i]->node_idx_start = m_pes[i].m_pGraph_nodes.size();
if (m_pApp_res[i] != NULL) {
    m_pTask_res[i]->m_reg_start_idx = m_pApp_res[i]->reg_start_idx;
}
```

`get_app_max_resource` aggregates app resources with `max`, not sum:

```cpp
pApp_res->exeBlock_cnt = std::max(pApp_res->exeBlock_cnt, pTask_res->exeBlock_cnt);
pApp_res->inst_cnt = std::max(pApp_res->inst_cnt, pTask_res->inst_cnt);
pApp_res->operand_cnt = std::max(pApp_res->operand_cnt, pTask_res->operand_cnt);
```

Implication:

```text
Within one app, task operand/register addresses are not allocated as disjoint
per-task banks. The mapper treats task operand pressure as an app-level max.
```

## ExeBlock Dependencies Are Explicit Dataflow Edges

`Graph_Extend` creates `GRAPH_NODE` relationships with parent/child links.
`exe_block_gen.cpp` lowers those into exeBlock predecessor/successor fields:

```cpp
pPredecessor->block_idx = pParent_exe_block->exe_block_idx;
pPredecessor->pe_pos.x = pPos->x;
pPredecessor->pe_pos.y = pPos->y;
...
pSuccessor->block_idx = pChild_exe_block->exe_block_idx;
pSuccessor->pe_pos.x = pPos->x;
pSuccessor->pe_pos.y = pPos->y;
pChild_exe_block->req_activations++;
```

This is the strongest source-code evidence that vendor runtime scheduling is
graph/dataflow based at exeBlock granularity.

## Design Consequences

1. Do not model `task` as a sequential stage by default. Treat task ordering as
   explicit graph/config information. No successor edge means assume may run
   independently.

2. Do not allocate operand/register space per task by simply summing tasks.
   Keep a `TaskParallelismPolicy = worst_case_parallel` and
   `AppResourceScope = shared_pe_operand_space` until closed runtime semantics
   are tested.

3. Preserve task-level uncertainty in dumps.

4. For first binary/package work, use worst-case task parallelism unless a task
   successor edge explicitly orders the tasks.
