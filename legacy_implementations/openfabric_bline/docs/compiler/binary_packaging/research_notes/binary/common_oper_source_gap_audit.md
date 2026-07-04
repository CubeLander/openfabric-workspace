# DFU3500 common_oper Source Gap Audit

Date: 2026-06-16

## Why This Note Exists

We were spending a lot of effort reverse-engineering CBUF `inst_t` diffs from OCR logs.
The remaining CBUF mismatch is structured and mostly points at operand index allocation
for COPY/COPYT / route-forward instructions. The current conclusion is that most of the
missing behavior is already present in vendor `testcase/common_oper` source, especially
`inst_blk_map.cpp`, `graph_extend.cpp`, `csv_oper.cpp`, and `task_print.cpp`.

This note records what must be consumed from source instead of guessed from OCR.

## Important Version Warning

The local source tree under:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper
```

may not match the arch-13 huake02 runtime exactly.

Local fingerprints observed here:

```text
246236162a29eb3f45d2abcc324c326931e8944e0638b035dff42bb8aaaa611b  libapp_build_common.so
b97408554aaac91d7adfdace59d1d4dbf9f6c06b4c96d97020d470fac85ae666  inst_blk_map.cpp
d9c1af31a926e3f960706827f0bd15df7676656f2b491325f226637b48a1bef2  task_print.cpp
cd5a2196700c9b0bb52e566de02864829af98171d8f109f89c25940763bfea22  graph_extend.cpp
a25a467d17d7c31223c9361e3bb406eca39b11a48ec8bbe6245deb042a4a76ef  inst_map_common.cpp
```

Earlier arch-13 huake02 OCR fingerprints included:

```text
e46d0f8870a0478133e02747de01297a30a1beb8b06fb413256d565af0d5938d  libapp_build_common.so
0f82e236b527460b66bd9713ae90215f1c5df762230b948c460a3202aaa54c17  exe_block_gen.cpp
3f9d7ba6ae5a88277ce3243d1203a98fc8bfb139f9b900bb2fdc93eafaee1f0b  inst_blk_map.cpp
b1335422e9b681478837572f2a21accbde42e0903151ec9b27ced717f3b8ec9e  task_create.cpp
```

Therefore, do not assume local `common_oper` is byte-identical to arch-13. Use it as
algorithm evidence, but verify critical constants/behavior against arch-13 diff outputs.


Active tracker:

```text
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_binary_research_gap_tracker.md
```

Use this tracker as the current index for unresolved binary/MICC/CBUF research
items before migrating mature knowledge to `docs/vendor_reference`.

## Source Files That Matter

Follow-up note:

```text
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_common_oper_task_graph_exeblock_audit.md
```

That note expands the `task_create.cpp` / `graph_extend.cpp` /
`inst_blk_gen.cpp` / `exe_block_gen.cpp` / `task_print.cpp` evidence for task,
graph, stage, exeBlock, compact instance offsets, and padded component rows.

Follow-up writer note:

```text
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_task_print_component_writer_audit.md
```

That note focuses on `task_print.cpp` as the component-file writer: simulator vs
RTL instruction projections, `iter_exe_cond` / `flow_ack` base selector behavior,
per-PE instruction stream padding, late stage PC rebasing, active rows vs padded
capacity, and task/subtask successor flags.

Follow-up resource-owner note:

```text
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_inst_blk_map_resource_owner_audit.md
```

That note focuses on `inst_blk_map.cpp` as the task/app resource owner: task
resource windows, operand allocation before COPY patching, child-owned COPY
destination fields, local COPY rewrite, and app-level capacity accounting.

Follow-up struct-layout note:

```text
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_vendor_struct_layout_audit.md
```

That note captures clean `common/src` struct definitions, `sizeof/offsetof`
layout facts, and CBUF/MICC component size formulas.  It explains the 304-byte
instruction-row stride and the observed CBUF size excluding `CBUF_ISTC_CONST`.

Follow-up auxiliary-artifacts note:

```text
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_data_inst_replace_and_enable_files_audit.md
```

That note records current evidence for `data_inst_replace.bin`, `instEnable.bin`,
and `taskEnable.bin`: generated contents, packaging behavior, staging behavior,
and why they should not be treated as runtime source of truth without a consumer.

### `csv_oper.cpp`

CSV parser preserves symbolic tags:

```text
src_reg_idx0_tag = elements[2]
src_reg_idxl_tag = elements[3]
dst_reg_idx_tag  = elements[4]
```

It assigns initial local CSV register ids via `Csv_Operate::getRegIdx`, but these are
later overwritten by `Task_Resource::fill_reg_idx` during mapping. For tensor pseudo ops
such as COPYT/LCOPYT, it expands one CSV row into multiple lane instructions using
`OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE`. This expansion is semantic and should not be
re-guessed in `program_bin.py`.

### `graph_extend.cpp`

`Graph_Extend::set_relationship_node` attaches copy instructions to graph edges:

```text
for each flow_stage_inst:
  if inst.dst_pes_pos[0].x == relationship type and op is not LCOPY/LCOPYT:
    relationship.pCopy_insts.push_back(inst)
```

This means COPY/COPYT route patching is edge-owned: parent node stores pointers to the
copy instructions that materialize data for a specific child node. OpenFabric currently
models route actions, but the final COPY destination operand must be patched using the
child processor/node TaskResource, exactly like this vendor edge relation.

### `inst_blk_map.cpp`

This is the key allocator and map finalizer.

`Task_Resource::get_reg_idx`:

```text
if tag already exists: return existing operand index
operand_idx = layout_operand_idx(m_reg_idx_counter + reg_start_idx)
m_reg_idx_list[tag] = operand_idx
m_reg_idx_counter++
```

`layout_operand_idx`:

```text
(reg_idx % OPERANDS_RAM_NUM) * OPERANDS_PER_OPERAND_RAM + reg_idx / OPERANDS_RAM_NUM
```

`Task_Resource::fill_reg_idx` scans each instruction stage in order and assigns operand
indices based on tags:

```text
LD stage -> CAL stage -> FLOW stage -> ST stage
```

within each graph node, and graph nodes are scanned in PE node order for the current task.
This order is the missing algorithm behind the remaining CBUF operand-index diffs.

`INST_BLK_MAP::end_map_task` performs the important sequence:

```text
distribute_task_resource()
rectify_copy_inst()
counting_task_resource()
get_app_max_resource()
```

Important: `rectify_copy_inst` runs after normal operand allocation. For each parent-child
edge, `fill_copy_inst` patches copy instructions to the child node:

```text
dst_blocks_idx[0] = child.block_idx
dst_pes_pos[0]   = child PE position
dst_operands_idx[0] = childTaskResource.retrieve_reg_idx(dst_reg_idx_tag)
```

If COPYT is converted to COPY, following lane instructions get:

```text
dst_operands_idx[0] = base + lane * OPERANDS_PER_OPERAND_RAM
```

This is almost certainly the algorithm needed to fix the remaining `(N -> N+1)` and
`2/3 -> 0/1` CBUF diffs without hard-fitting bytes.

### `task_create.cpp`

Mapping flow:

```text
Task_Group::map:
  start_map_app()
  for each task:
    start_map_task()
    for each subtask:
      map_subtask(subtask nodes, false, subtask_name)
    end_map_task()
  end_map_app()
```

This proves TaskResource is task-scoped but app resources provide starting counters. It
also means K-loop/subtask folding must preserve the vendor task/subtask grouping before
operand replay.

### `task_print.cpp`

Writer flow:

- `print_inst` writes per-PE tmp instruction streams by graph node order.
- `print_block_conf` writes block rows per PE and adjusts stage PC using per-PE running
  instruction counters.
- `fill_max_inst_per_pe` pads each PE instruction stream and block stream before merging.
- The final merged CBUF order is per PE:

```text
for pe_idx in 0..15:
  append tmp insts for this PE
for pe_idx in 0..15:
  append block conf for this PE
```

This matches the CBUF section model already implemented. Remaining problems are not file
layout; they are instruction field values generated before serialization.

## Missing Pieces In OpenFabric

### P0: Full TaskResource Replay Pass

Current OpenFabric has only partial/scaffolded tag lookup. It must grow a pass that replays
vendor `Task_Resource` behavior over the OpenFabric program:

```text
TemplateBoundInstructions / ProgramAsmBlocks
  -> group by (task_index, processor)
  -> sort by vendor graph node / block order
  -> scan each node in stage order: LD, CAL, FLOW, ST
  -> allocate tag -> operand index using layout_operand_idx(counter + app_reg_start)
  -> patch instruction src/dst operand fields
  -> after allocation, patch route COPY/COPYT dst fields through child TaskResource.retrieve(tag)
```

This pass must live before `program_bin.py` byte serialization. `program_bin.py` should only
serialize already-final instruction rows.

### P0: Explicit Graph Edge Copy Relation

OpenFabric must preserve a mapping equivalent to vendor `relationship_t.pCopy_insts`:

```text
parent micro-block/action -> child micro-block/action -> copy instruction ids
```

The child endpoint must own the destination operand allocation. Sender-side shallow lookup
is insufficient.

### P1: Vendor Node Order Audit

The TaskResource replay only works if OpenFabric node order matches vendor node order.
Need to confirm:

```text
per PE node order
per task/subtask order
per node stage instruction order
```

If diffs remain after TaskResource replay, inspect graph order before touching binary
fields.

### P1: Version Fingerprint Gate

Because local `common_oper` fingerprints may not match arch-13, add a note/report in future
bundle tooling:

```text
expected common_oper source/so SHA
observed local source/so SHA
observed arch-13 source/so SHA when available
```

This prevents chasing differences caused by a different vendor packer build.

## Recommended Next Implementation Shape

Add a DFU3500 backend pass, not binary hacks:

```text
program_templates / ProgramAsm
  -> Dfu3500TaskResourceReplayProgram
  -> ProgramVendorABI / ProgramBinRows
  -> serializer
```

Core structures:

```text
Dfu3500TaskResourceState:
  reg_start_idx
  counter
  tag_to_operand_idx

Dfu3500CopyPatch:
  parent_block_id
  child_block_id
  copy_instruction_ids
  dst_tag
```

Verifier targets:

```text
1. Tags used by COPY dst are allocated in child processor task resource.
2. COPYT following lanes equal base + lane * OPERANDS_PER_OPERAND_RAM.
3. ProgramBin serializer imports no template-selection or TaskResource logic.
4. Previously fixed MICC and CBUF layout tests stay locked.
```

## Current Practical Status

We are probably not missing a mysterious ABI document. The missing algorithm is in
`common_oper` source. The last large conceptual gap is to replay `Task_Resource` with the
same graph/task/edge order as vendor, then let existing serializer emit bytes.
