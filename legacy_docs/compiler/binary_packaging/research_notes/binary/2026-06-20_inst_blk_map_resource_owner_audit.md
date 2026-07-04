# inst_blk_map Resource Owner Audit

Date: 2026-06-20

Status: binary note, source-first audit for operand/block/resource ownership

This note records the vendor `inst_blk_map.cpp` resource mapping sequence that
must be preserved by B-line before byte-level CBUF/MICC emission.  It complements:

```text
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_common_oper_task_graph_exeblock_audit.md
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_task_print_component_writer_audit.md
```

## Source Fingerprint

Source root:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper
```

Audited file:

```text
44a469f28bf92a7c79beedbd98611bd83828e82058d0a2a5b0e182b6e3254624  inst_blk_map.cpp
```

Warning: local source appears to contain extracted/annotated markdown fragments
in places.  Use it as algorithm evidence, but verify exact source and binary
behavior against arch-13 when a field becomes payload-critical.

## 1. Mapping Is Scoped By App, Then Task, Then Subtask

The vendor control flow is app-scoped, then task-scoped, while each subtask is
mapped into the current task resource window:

```text
start_map_app()
  for each task:
    start_map_task()
      for each subtask:
        map_subtask(...)
    end_map_task()
end_map_app()
```

Source evidence:

```text
task_create.cpp map flow, summarized in common audit
inst_blk_map.cpp:3279-3291
inst_blk_map.cpp:3331-3349
inst_blk_map.cpp:3353-3363
inst_blk_map.cpp:3425-3434
inst_blk_map.cpp:3471-3497
```

### B-line implication

A task is not merely a named row in MICC.  It is a resource allocation scope:

```text
operand tag allocation
PE-local block index allocation
instruction resource counting
copy destination patching
```

B-line should make this explicit with a task/window owner even if high-level IR
uses a soft processor mesh.

## 2. `start_map_task` Freezes Per-PE Task Resource Start Points

`start_map_task()` creates one `Task_Resource` per PE and records:

```text
block_idx_start = current PE block slots used
node_idx_start  = current PE graph node count
```

Source evidence:

```text
inst_blk_map.cpp:3279-3291
```

### B-line implication

Later task resource replay only scans graph nodes added after `node_idx_start`.
This matters when multiple tasks/subtasks share a PE: a PE-local block index is
not simply `enumerate(all nodes)` in the final app; it is allocated within nested
resource windows.

Required owner candidate:

```text
TaskResourceWindow:
  task_id
  pe_id
  node_start
  block_start
  operand_start
```

## 3. Operand Allocation Happens Before COPY Destination Patching

`end_map_task()` runs this sequence:

```text
distribute_task_resource()
rectify_copy_inst()
counting_task_resource()
get_app_max_resource()
```

Source evidence:

```text
inst_blk_map.cpp:3331-3349
```

`distribute_task_resource()` first calls `distribute_operand()`, then assigns
PE-local block indices to graph nodes in the current task window.

Source evidence:

```text
inst_blk_map.cpp:3091-3120
```

`distribute_operand()` scans every new graph node and every stage in order:

```text
LD -> CAL -> FLOW -> ST
```

and calls `Task_Resource::fill_reg_idx()` / `fill_reg_idx_rd()`.

Source evidence:

```text
inst_blk_map.cpp:3021-3087
```

### B-line implication

COPY route instructions cannot be patched until receiver operand tags have been
allocated.  The correct order is:

```text
1. allocate normal source/destination operand tags for all task nodes;
2. assign PE-local block indices;
3. patch COPY destination block/PE/operand fields from child task resource;
4. count final valid instruction/block/operand usage.
```

This is a key answer to the old CBUF diffs: receiver operand indices are not
local guesses at the route site; they are retrieved from the child PE's task
resource.

## 4. COPY Destination Fields Are Child-owned

`fill_copy_inst()` traverses a parent node's child relationships.  For each valid
COPY-like instruction attached to that edge, it patches:

```text
dst_blocks_idx[0]   = child.block_idx
dst_pes_pos[0].x/y  = child PE position
dst_operands_idx[0] = childTaskResource.retrieve_reg_idx(dst_reg_idx_tag)
```

Source evidence:

```text
inst_blk_map.cpp:3165-3252
```

For `COPYT`, following lane instructions are normalized into `COPY` and their
destination operand indices advance by:

```text
i_following_inst * OPERANDS_PER_OPERAND_RAM
```

Source evidence:

```text
inst_blk_map.cpp:3205-3228
```

### B-line implication

Route materialization needs a two-sided contract:

```text
producer side:
  owns the COPY instruction row

consumer side:
  owns destination PE/block/operand identity
```

A flat stream/fiber action can stay simple, but the route edge must retain enough
lineage to patch the producer instruction with consumer block and operand fields.

Required owner candidate:

```text
RouteEndpointBinding:
  source_action_id
  destination_action_id
  destination_pe
  destination_pe_local_block
  destination_operand_tag
  destination_operand_index
```

## 5. Local COPY Is Rewritten Into Normal COPY

`alter_local_copy_inst()` rewrites local copy opcodes:

```text
OP_LCOPY / OP_LCOPYT -> OP_COPY
```

and points destination block/PE fields back to the current node's own block/PE.
For tensor local copies, following lane rows inherit the same destination PE/block
metadata.

Source evidence:

```text
inst_blk_map.cpp:3123-3162
```

### B-line implication

There should not be a separate forever-visible “local route instruction family”
at final template binding unless the hardware really requires it.  Local route
materialization can lower into ordinary COPY with self destination.

This fits B-line's flat IR idea:

```text
semantic local visibility action
  -> final route/copy binding chooses self-COPY projection
```

## 6. Task Resource Counts Feed App Resource Maxima

`counting_task_resource()` accumulates per-task usage:

```text
exeBlock count
operand count
instruction count
instruction RAM count
```

Source evidence:

```text
inst_blk_map.cpp:2973-3018
```

`get_app_max_resource()` updates app resource maxima and `inst_ram_cnt[pe]`, then
deletes task resources.

Source evidence:

```text
inst_blk_map.cpp:3295-3327
```

`end_map_app()` later calls `distribute_app_resource()`, which updates PE-global
counters and checks capacity:

```text
m_inst_slots_used_counter = inst_ram_cnt[pe]
m_blk_slots_used_counter  = app_res.exeBlock_cnt
m_reg_counter            += app_res.operand_cnt
```

Source evidence:

```text
inst_blk_map.cpp:3367-3421
inst_blk_map.cpp:3425-3434
```

### B-line implication

Capacity checks are not only serializer checks.  They are resource planning facts:

```text
per-PE instruction RAM pressure
per-PE block capacity
per-PE operand capacity
```

B-line should make these verifier-visible before writing binary files.

Required owner candidate:

```text
ResourceCapacityPlan:
  pe_inst_count
  pe_block_count
  pe_operand_count
  limits from dfu3500 profile
```

## 7. App Resource Uses Maxima, Task Resource Uses Windows

Task resources are scoped to one task window.  App resources summarize what the
whole app/package needs to cover on each PE.  The vendor flow uses both:

```text
TaskResource:
  current task scan window and tag map

APP_Resource:
  app-level start indices and capacity maxima
```

### B-line implication

Do not collapse these into one global dict.  A-line pain came partly from mixing
semantic active work, padded capacity, and runtime launch facts.  Here the source
shows another split:

```text
resource allocation window
resource capacity accounting
component file padding
runtime launch counts
```

All four are related, but none should silently replace another.

## 8. B-line Design Rule

The B-line stream/fiber compiler can avoid legacy `program_task_*` scaffolding,
but it cannot avoid these facts:

```text
1. each executable action belongs to a task resource window;
2. PE-local block ids are assigned after graph/fiber placement;
3. operand tags are allocated in final stage order;
4. route COPY destinations are patched from receiver-side owner state;
5. app-level resource maxima are verified before component writing.
```

This is the core difference between a clean IR and a runnable vendor image.  The
IR can be flat; the binary writer must still have typed ownership plans.

## Immediate Verifier Candidates

```text
1. Every route/copy action has a destination action/block owner.
2. Every destination operand tag exists in the receiver task resource map.
3. COPY/COPYT patching runs after receiver operand allocation.
4. PE-local block ids are unique within a PE and task/app package window.
5. Operand allocation order is deterministic and stage-aware.
6. App resource maxima do not exceed DFU3500 profile limits.
7. Final component writer consumes resource plans, not ad-hoc action order.
```

## Remaining Research Gaps

```text
1. Exact `Task_Resource::layout_operand_idx` constants in current arch-13 build.
2. Full pseudo-op expansion rules for COPYT/LCOPYT in `csv_oper.cpp` vs mapper.
3. Whether local annotated source fragments match arch-13 `inst_blk_map.cpp`.
4. How `REDUCE` compile-time mode changes operand allocation in deployed cases.
5. Which cases exercise `fill_reg_idx_rd()` in current vendor workflows.
```
