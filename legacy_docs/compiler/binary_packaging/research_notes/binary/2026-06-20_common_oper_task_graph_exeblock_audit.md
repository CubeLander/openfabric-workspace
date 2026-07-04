# common_oper Task / Graph / ExeBlock Source Audit

Date: 2026-06-20

Status: binary note, source-first audit before docs cleanup

This note records source-backed behavior from vendor `common_oper` that affects
MICC/CBUF task, graph, exeBlock, and instruction-stage metadata.  It is written
in `docs/compiler/binary_packaging/research_notes/binary` first because these facts are still active working
knowledge for B-line, not polished docs.

## Source Tree And Fingerprints

Source root:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper
```

Local fingerprints used for this audit:

```text
31a4ba6f4b9201a2a282b889b5cf4f7c95797342fc55806dc2931224d9968ca5  task_create.cpp
cd5a2196700c9b0bb52e566de02864829af98171d8f109f89c25940763bfea22  graph_extend.cpp
4457bd232c4da6237bd60ffd90fc038e706df1b0fd3ac1769c84cf0ad06cc6c7  inst_blk_gen.cpp
bdc8a311d801be6501f88c4de1af757f699aeae2a97dcd04334213dd42561eaa  exe_block_gen.cpp
d9c1af31a926e3f960706827f0bd15df7676656f2b491325f226637b48a1bef2  task_print.cpp
229af09d1eaf831bbd6deb44c35ec74a1c43019f877f32c42c568d08059069fa  common_app_build.cpp
bc91510345ee8473e065ee6449c8a776ef1c120469ae5a75ae10d9a20c4d401b  csv2bin.cpp
58fa864f09b8be1b163a4bf90e33a4d426ca32bb3755b4f1224fd0d1e8819b26  csv2bin.h
```

Warning: local source may differ from arch-13.  Treat this as algorithm evidence
and keep remote binary/runtime validation for constants and exact layouts.

## Pipeline Slice Covered Here

This note covers this vendor chain:

```text
app.conf / task config
  -> Task_Group / Task / SubTask
  -> CSV template Inst_Block collection
  -> generateGraph() from per-subtask libsubtask.so
  -> Graph_Extend relationships and copy edge ownership
  -> INST_BLK_MAP resource replay
  -> exe_block_gen stage PC / predecessor / successor metadata
  -> task_print task/subtask/exeBlock component rows
```

It does not cover final byte conversion of every struct field.  That remains in
`task_print.cpp` and existing CBUF/MICC notes.

## 1. Task Config Parsing Is A Strict Nested Grammar

`Task_Group::readFromTaskFile` parses a task config with nested blocks:

```text
Task(...){ SubTask(...)(...) }
```

For each task it:

```text
1. parses task-level fields,
2. parses exactly the declared number of subtask parentheses,
3. errors on missing or extra delimiters,
4. pushes the task into `m_tasks`,
5. increments `m_task_num`.
```

Source:

```text
task_create.cpp:307-375
```

`Task::create_task` reads:

```text
task_name
reuse input regs
reuse output regs
execute_times
subtask_Number
```

Source:

```text
task_create.cpp:178-240
```

`SubTask::create_subtask` reads:

```text
subTask_name
reuse input regs
reuse output regs
instance_times
code_Path
csv_Amount
graph_height
graph_width
```

Source:

```text
task_create.cpp:22-111
```

### B-line implication

A B-line task/subtask plan should be explicit and strict.  Do not infer subtask
count from “number of emitted blocks” after the fact.  The vendor flow has a
front-loaded declaration, and missing/extra structure is fatal.

Required owner:

```text
TaskControlPlan:
  task_id
  execute_times
  subtask_count

SubtaskPlan:
  subtask_id
  instance_times
  csv/template count or generated template-op count
  graph shape metadata when needed
```

## 2. Subtask Construction Loads CSV Templates Before Graph Expansion

`SubTask::read_inst_block_collect` loads every `template/<i>.csv` into an
`Inst_Block`, calls `readFromTemplate()`, and then calls `process()`.

Source:

```text
task_create.cpp:113-123
```

`Task::subtaskConstruct` then does:

```text
read_inst_block_collect()
subtask_graph_extend()
count_root_block_amount()
```

Source:

```text
task_create.cpp:275-280
```

### B-line implication

Template parsing and graph placement are separate phases:

```text
TemplateOpPlan / TemplateInstructionPlan
  before
Graph/Fiber/Stream placement and edge construction
```

Do not let op specs create final graph edges and final instruction rows in one
step.  The vendor flow first has reusable block templates, then places/copies
them into a graph.

## 3. `generateGraph` Is Case-specific Dynamic Code

`SubTask::subtask_graph_extend` opens:

```text
<task>/<subtask>/build_so/libsubtask.so
```

and looks up:

```c
generateGraph(string task_name,
              string subTask_name,
              vector<GRAPH_NODE> &m_nodes,
              Inst_Block_Collect &inst_block_collect,
              uint64_t graph_height,
              uint64_t graph_width)
```

Source:

```text
task_create.cpp:134-169
```

### B-line implication

The vendor graph is not a generic hardcoded graph in `common_oper`; every case
ships a graph generator.  OpenFabric B-line should not try to encode GEMM,
softmax, route topology, and future ops inside one legacy global pass.  The
right analog is:

```text
op/fiber planner produces graph/fiber actions
common lowering consumes those actions
```

But the result must still satisfy the same binary-facing contracts:

```text
node order
root block amount
parent/child edge metadata
copy instruction ownership
```

## 4. Graph_Extend Makes COPY Edge-owned

`Graph_Extend::set_relationship_node` builds a parent-child relationship and
collects COPY-like flow instructions from the parent node:

```text
for each parent flow-stage instruction:
  if inst.dst_pes_pos[0].x == relationship type
  and opcode is not LCOPY/LCOPYT:
    push instruction pointer into child and parent relationship copy list
```

Source:

```text
graph_extend.cpp:7-32
```

### B-line implication

Route materialization has two pieces:

```text
semantic edge:
  parent action/value -> child action/value

copy instruction ownership:
  parent node contains the copy instruction pointer used for that child edge
```

A B-line flat IR can keep actions simple, but route edges need enough identity to
later answer:

```text
which copy/template operation satisfies this edge?
which receiver block and receiver operand does it target?
```

Do not erase this edge identity during stream/fiber flattening.

## 5. Inst_Block Splits CSV Rows Into Fixed Stage Order

`Inst_Block::process` partitions processed CSV instructions by scanning in a
fixed order:

```text
LD stage
CAL stage
FLOW stage
ST stage
```

It keeps consuming rows while the current `unit_inst_type` belongs to the stage.
If any rows remain after these four scans, it errors.

Source:

```text
inst_blk_gen.cpp:27-85
```

It also counts `valid_cp_inst_cnt` while scanning FLOW-stage instructions.

### B-line implication

The stage order is not a presentation preference; it is a binary metadata source.
`exeBlock_conf.stages_start_pc[]` later assumes this order.

Required owner:

```text
TemplateStagePlan:
  ld_actions[]
  cal_actions[]
  flow_actions[]
  st_actions[]
```

Even if B-line keeps one flat fiber action list for readability, the final
binding must project actions into this stage order before CBUF rows are emitted.

## 6. ExeBlock Index Is PE-local

`exe_block_gen` assigns `exe_block_idx` by PE-local counter:

```text
for each PE:
  for each graph node newly added to that PE:
    exe_block_idx = pPe->m_exeBlock_cnt
    pPe->m_exeBlock_cnt++
```

Source:

```text
exe_block_gen.cpp:198-219
```

### B-line implication

Block ids in final CBUF/MICC metadata are not globally unique graph ids.  They
are PE-local block indices, qualified by PE coordinate.

Required owner:

```text
VendorBlockIndexPlan:
  stream/fiber/block id -> (pe_x, pe_y, pe_local_block_idx)
```

This is why a pretty global action id cannot be directly serialized into
`dst_blocks_idx` / successors / predecessors.

## 7. ExeBlock Successors / Predecessors Are Built From Graph Edges

`set_parent_successor` traverses every PE's graph nodes and calls:

```text
add_successor(current_pe_pos, node)
add_predecessor(current_pe_pos, node)
```

`add_successor` iterates a child node's parent list and appends the child as a
successor to each parent exeBlock.  It also increments the child exeBlock's
`req_activations`.

Source:

```text
exe_block_gen.cpp:137-181
exe_block_gen.cpp:184-196
```

`add_predecessor` appends the parent block/PE position to the child exeBlock.

Source:

```text
exe_block_gen.cpp:106-135
```

### B-line implication

`req_activations`, predecessor rows, and successor rows are not arbitrary
control knobs.  They are derived from graph edges and PE-local block indices.

A-line pain context:

```text
Manual task/subtask/successor edits caused runtime hangs because control-plane
metadata and graph-derived block completion expectations diverged.
```

Required owner:

```text
BlockDependencyPlan:
  semantic dependencies -> graph edge set
  graph edge set -> successor/predecessor/req_activations projection
```

## 8. Stage Start PCs Are Per-PE Running Instruction Counters

`organize_block_conf` computes stage start PCs using a per-PE instruction counter:

```text
inst_start_pos = *pInsts_cnt_per_pe
stages_start_pc[LD]   = inst_start_pos
advance by valid LD count
stages_start_pc[CAL]  = inst_start_pos
advance by valid CAL count
stages_start_pc[FLOW] = inst_start_pos
advance by valid FLOW count
stages_start_pc[ST]   = inst_start_pos
advance by valid ST count
stages_start_pc[MAX]  = end
*pInsts_cnt_per_pe    = end
```

Source:

```text
exe_block_gen.cpp:16-76
```

It counts only `inst.valid` rows for each stage.

### B-line implication

Instruction PC in exeBlock metadata is:

```text
PE-local instruction-stream offset
```

not:

```text
global package byte offset
flat action order
fiber order index
```

Required owner:

```text
InstructionLayoutPlan:
  per-PE instruction stream
  stage-local valid instruction counts
  block stage_start_pc[]
```

This directly explains why final binary emission must happen after all template
expansion, pseudo-op lowering, validity filtering, and operand patching.

## 9. task_print Later Re-patches Task/Subtask/Instance Fields

`exe_block_gen` builds graph/block metadata, but `task_print.cpp` patches final
fields using subtask metadata:

```text
exeBlock_conf.instances_amount = subtask.instances_amount
exeBlock_conf.task_idx         = subtask.task_idx
exeBlock_conf.subtask_idx      = subtask.subtask_idx
exeBlock_conf.block_idx        = dst.block_idx
```

Source:

```text
task_print.cpp:332-387
```

`set_instance_amount_to_exeblock` also writes subtask instance count into every
exeBlock in that subtask.

Source:

```text
task_print.cpp:403-407
```

### B-line implication

There are two phases:

```text
1. graph/block formation without final task/subtask patching,
2. subtask packaging that stamps task/subtask/instance fields.
```

B-line should not ask a low-level block emitter to infer `task_idx` by itself.
It should consume an already-decided task/subtask owner.

## 10. Subtask Rows Use Compact Active Instance Addressing

`print_task` sets:

```text
sub_task_conf_info.instances_amount = task.m_subtasks[i].instance_times
sub_task_conf_info.instances_conf_mem_based_addr =
    m_instance_start_idx * sizeof(instance_conf_info_t)
m_instance_start_idx += task.m_subtasks[i].instance_times
```

Source:

```text
task_print.cpp:662-710
```

This is the active compact instance address used by subtask rows.  It is not the
same thing as the physical fixed CBUF instance table index:

```text
physical row = task * 8 * 2048 + subtask * 2048 + instance
```

### B-line implication

Keep these separate:

```text
SubtaskRuntimeInstanceBaseAddr:
  compact active stream offset for MICC/subtask rows

PhysicalInstanceRow:
  fixed CBUF table row for padded component file
```

A-line already suffered here; do not merge these concepts again.

## 11. Subtask Successor Chain Is Linear By Default

In `print_task`, when `subtask_counter > 0`, the previous subtask's first
successor is patched to the current subtask global index:

```text
sub_tasks_conf_info[all_subtask_idx - 1].suc_subtasks[0] =
    all_subtask_idx + m_subtask_start_idx
```

The first emitted subtask is marked start; the last emitted subtask is marked
end.

Source:

```text
task_print.cpp:689-699
```

### B-line implication

For legacy single-chain tasks, subtask sequencing is linear:

```text
subtask0 -> subtask1 -> ... -> subtaskN
```

But this linear chain is a packaging/control projection.  It should be generated
from the task/subtask plan, not hardcoded independently in RISC-V, MICC rows, and
exeBlock rows.

Required guard:

```text
last subtask must have is_exe_end=true and no bogus successor
non-last subtask successor must point to the next active subtask
runtime task_num must match active task rows
```

## 12. Fixed Padding Happens After Active Rows

`task_print.cpp` pads task/subtask and CBUF components to vendor fixed-size
capacity.  Relevant behavior:

```text
subtask_slots = max(1, task_amount) * MAX_SUBTASK_PER_TASK
write active subtasks, then zero subtasks up to subtask_slots
then complete empty task/subtask rows to MAX_CUR_TASK_CONF_PER_APP
```

Source:

```text
task_print.cpp:747-796
```

It also pads per-PE instruction and block streams before merging.

Source:

```text
task_print.cpp:514-580
```

### B-line implication

B-line needs an explicit distinction:

```text
active semantic/package rows
fixed-capacity padded component rows
```

Do not make runtime task count equal padded task capacity.  This was an A-line
bug class.

## 13. `csv2bin.cpp` Is A Stub In This Snapshot

The local `csv2bin.cpp` is effectively empty:

```text
#include "csv2bin.h"
```

and `csv2bin.h` only defines an empty `INST_PRINT` class.

Source:

```text
csv2bin.cpp:1
csv2bin.h:1-7
```

### B-line implication

In this source snapshot, core CSV-to-binary behavior is not in `csv2bin.cpp`.
The actual source of truth is:

```text
csv_oper.cpp       CSV parse/pseudo expansion
inst_blk_gen.cpp   stage split
task_print.cpp     binary struct conversion / writing
```

Do not waste time looking for a hidden row serializer in local `csv2bin.cpp`.
If arch-13 has a different non-stub version, record its fingerprint separately.

## 14. `common_app_build.cpp` Is Utility Glue Only

Local `common_app_build.cpp` contains string helpers:

```text
ToUpperString / ToLowerString
mySplit
myReplaceAll
myTrim
```

Source:

```text
common_app_build.cpp:1-76
```

### B-line implication

The local file is not the app packager.  App-package assembly behavior is spread
across case scripts, `Task_Group`, `INST_BLK_MAP`, and `task_print`.  If there is
a vendor shared object with more behavior, treat it as a versioned binary-source
boundary and fingerprint it.

## B-line Owner Map

| Vendor behavior | B-line owner candidate |
| --- | --- |
| strict task/subtask declaration | `TaskControlPlan` / `SubtaskPlan` |
| CSV template stage split | `TemplateStagePlan` |
| dynamic graph generation result | `StreamPlan` / `FiberPlan` action graph |
| edge-owned COPY instructions | `RouteEndpointPlan` |
| PE-local block index | `VendorBlockIndexPlan` |
| successor/predecessor/req activation projection | `BlockDependencyPlan` |
| per-PE instruction PC | `InstructionLayoutPlan` |
| compact instance base addr vs physical instance row | `InstanceAddressPlan` + `VendorComponentPlan` |
| active rows vs padded rows | `VendorComponentPlan` |

## Immediate Follow-up Checklist

Before B-line attempts functional GEMM byte emission:

```text
1. Prove every fiber/block action has a task/subtask owner.
2. Project actions into LD/CAL/FLOW/ST stage groups.
3. Allocate PE-local block indices before successor/predecessor rows.
4. Allocate PE-local instruction PCs after final template expansion.
5. Keep compact instance offsets and physical padded instance rows separate.
6. Emit runtime task count from active task rows, not fixed capacity.
7. Fail if a route edge has no copy/materialization action lineage.
```

## Why This Matters

The A-line maximum probe became runnable only after repeated manual correction of
control metadata.  This source audit shows why manual patching is the wrong long
term path: vendor metadata is derived from a graph/task/stage pipeline.  If B-line
keeps those derivations explicit and typed, the same class of mistakes can become
local verifier failures instead of remote SimICT hangs.
