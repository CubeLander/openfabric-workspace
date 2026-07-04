# DFU3500 GEMM Binary Replay and TaskResource Notes

Date: 2026-06-16

This note extracts vendor-workflow knowledge from the current OpenFabric diff
review.  It documents the original customer workflow facts that matter for GEMM
binary compatibility.  It is **not** a generic OpenFabric design document; it is
a vendor reference for SimICT / GPDPU / DFU3500 artifact generation.

## 1. Why this matters

The current GEMM binary work is no longer blocked by file sizes or top-level
bundle layout:

```text
result/cbuf_file.bin
  = insts_file.bin
  + exeblock_conf_info_file.bin
  + instance_conf_info_file.bin

result/micc_file.bin
  = tasks_conf_info_file.bin
  + subtasks_conf_info_file.bin
```

The remaining hard problems are inside the generated `inst_t` rows and a few
vendor-control metadata fields.  In particular, many CBUF byte diffs are caused
by operand indices in `inst_t`, not by serializer padding or component order.
Those operand fields are finalized by vendor `common_oper/inst_blk_map.cpp`, via
`Task_Resource`, after CSV parsing.

The practical lesson is:

```text
CSV template operands are not final hardware operands.
Task_Resource replay is part of the vendor assembler semantics.
```

## 2. Vendor workflow facts confirmed by diff review

### 2.1 Runtime consumes case `result/` copied into runtime `config/`

The useful comparison target is not a stale `simulator_bin/` directory; it is
the case result copied to runtime config:

```text
testcase/application/gemm_template_fusion/result/cbuf_file.bin
  == gpdpu/users/risc_nn_riscv/config/cbuf_file.bin

testcase/application/gemm_template_fusion/result/micc_file.bin
  == gpdpu/users/risc_nn_riscv/config/micc_file.bin
```

Earlier observations of a 2MB-only `cbuf_file.bin` and empty `micc_file.bin`
were partial/stale build states, not the completed simulator input state.  A
successful workflow state has full-size files:

```text
cbuf_file.bin = 23,531,520 bytes
micc_file.bin =  8,522,976 bytes
```

### 2.2 arch-13 active environment is huake02-rooted

The current confirmed remote path is:

```text
/project/home-new/huake02/simict3500final
```

`run_app_riscv.sh gemm_template_fusion 4` uses four duplicate applications for
this GEMM case.  Helper scripts should default to `huake02`, not older `huake01`
paths, unless an experiment explicitly targets a different account.

### 2.3 `run_app_riscv.sh` is a wrapper, not the binary producer

`run_app_riscv.sh` sets toolchain paths, enters the case directory, runs the case
build flow, copies case `result/` into runtime `config/`, installs the RISC-V
program, and launches:

```text
core/bin/runtime ./top.so topPara.so common/src/libcommon.so
```

The actual binary producer is the case/application build path, especially:

```text
testcase/application/build_app/run_mtr.sh
testcase/application/build_app/main.cpp
testcase/common_oper/task_print.cpp
testcase/common_oper/inst_blk_map.cpp
testcase/common_oper/exe_block_gen.cpp
```

## 3. Binary component layout

### 3.1 CBUF

```text
cbuf_file.bin
  offset 0
    insts_file.bin
    size = 69,632 * 304 = 21,168,128 bytes

  offset 21,168,128
    exeblock_conf_info_file.bin
    size = 512 * 520 = 266,240 bytes

  offset 21,434,368
    instance_conf_info_file.bin
    size = 65,536 * 32 = 2,097,152 bytes
```

`insts_file.bin` is PE-major:

```text
for pe_idx in 0..15:
  emit MAX_INST_AMOUNT_PER_PE instruction records
```

`exeblock_conf_info_file.bin` is also PE-major:

```text
for pe_idx in 0..15:
  emit MAX_INST_BLOCK_AMOUNT_PER_PE exeBlock records
```

### 3.2 MICC

```text
micc_file.bin
  offset 0
    tasks_conf_info_file.bin
    size = 4 * 120 = 480 bytes

  offset 480
    subtasks_conf_info_file.bin
    size = 32 * 266,328 = 8,522,496 bytes
```

`sub_task_conf_info_t` embeds exeBlock rows.  The embedded bytes must come from
the same row source as `exeblock_conf_info_file.bin`; do not serialize two
independent versions of exeBlock metadata.

## 4. Task / subtask / instance index spaces

The vendor workflow uses multiple index spaces.  Mixing them is a classic source
of plausible-looking but wrong MICC bytes.

### 4.1 Task and subtask rows

```text
task row index           = 0..3
local subtask index      = 0..7 within one task
global subtask row index = task_index * 8 + local_subtask_index
```

Current evidence:

- `task_conf_info_t.subtasks_idx[]` uses global subtask row indices.
- `sub_task_conf_info_t.subtask_idx` uses local subtask index.
- `sub_task_conf_info_t.suc_subtasks[]` matches vendor local successor indices,
  while the task row still uses fixed/global slots.
- unused fixed-width slots are `0` padding controlled by active count fields; do
  not treat padding `0` as a semantic edge.

### 4.2 Instance table

`instance_conf_info_file.bin` is physically fixed-size:

```text
4 tasks * 8 subtask slots/task * 2048 instance slots/subtask = 65536 rows
physical_instance_row = task_index * 8 * 2048
                      + local_subtask_index * 2048
                      + instance_index
```

But `instances_conf_mem_based_addr` in subtask rows remains compact in active
execution order.  Do **not** rewrite it to the physical row byte offset.

This split is subtle:

```text
MICC control field: compact semantic offset
CBUF instance file: fixed physical table
```

## 5. CSV rows are not final `inst_t` rows

`Csv_Operate` preserves symbolic operand tags:

```text
src_reg_idx0_tag
src_reg_idx1_tag
dst_reg_idx_tag
```

It also expands pseudo tensor ops such as `HLDT`, `HSTT`, and `COPYT` into lane
instructions.  However, the operand indices visible in CSV-derived instructions
are still not the final hardware operands.

The final `inst_t` operand fields are rewritten during graph mapping by
`Task_Resource::fill_reg_idx()` and later by `INST_BLK_MAP::fill_copy_inst()`.

## 6. Vendor TaskResource behavior

### 6.1 Macro state observed in local vendor source

The current full `common_oper/inst_blk_map.cpp` contains:

```cpp
//#define REDUCE 1
#define RANDOM 1
#define ORDER 1
```

With this macro state, GEMM should model normal `fill_reg_idx()`, not
`fill_reg_idx_rd()`, unless arch-13 proves different compile flags.

### 6.2 One TaskResource per PE per task mapping window

The vendor mapper keeps one `Task_Resource` per PE while mapping a task.  In
`start_map_task()` / `end_map_task()` flow, each PE's graph nodes are scanned in
PE-local graph-node order.  For each exeBlock, stages are processed in order:

```text
LD -> CAL -> FLOW -> ST
```

This order mutates the tag-to-operand map.  Therefore final operand allocation
is order-sensitive.

### 6.3 Regular operand ORDER pool

`PE::PE()` initializes regular operand RAM pools as:

```text
m_reg_lists[ram_idx] = [ram_idx * 128 + 0,
                        ram_idx * 128 + 1,
                        ...,
                        ram_idx * 128 + 127]
```

With `ORDER`, `alloc_operand_slot()` chooses the first available RAM index in
the stage-local free-RAM list, then `pop_back()` from that RAM.  Therefore the
first few regular allocations in a fresh stage look like:

```text
ram0 high line -> 127
ram1 high line -> 255
ram2 high line -> 383
...
```

Regular allocation also removes the corresponding first tensor slot from the
available tensor pool, because normal and tensor registers share physical
operand storage.

### 6.4 Stage-local RAM reuse window

`fill_reg_idx()` builds a stage-local list of free RAM indices with
`get_rest_ram_rec()`.  After each instruction it records the RAMs used by that
instruction.  Once more than `MAX_OPERAND_RAM_ZONE = 3` recent instruction
records exist, the oldest RAMs may be reinserted into the free list if not used
by newer records.

This creates deterministic but nontrivial counter drift.  Small `N -> N+1` CBUF
operand diffs often indicate that OpenFabric visited tags in a different order
or released/reused a RAM at a different moment.

### 6.5 Tensor pseudo operand allocation

Tensor pseudo ops allocate a base in a RAM group.  The vendor routine chooses an
available tensor group with the most free slots, then pops high-to-low within
that group.  Lane operands follow:

```text
lane_operand = base + lane * OPERANDS_PER_OPERAND_RAM
```

For four-lane mode this yields bases such as:

```text
base, base + 128, base + 256, base + 384
```

If a CSV/template field forces a group through `extra_fields[2]`, the forced
1-based field maps to zero-based group:

```text
forced_group = extra_fields[2] - 1
```

### 6.6 COPY / COPYT receiver patch

Vendor `fill_copy_inst(parent_node)` runs after normal operand allocation.  It
patches COPY instructions attached to a parent-child graph edge:

```text
copy.dst_blocks_idx[0]    = child.block_idx
copy.dst_pes_pos[0]       = child PE position
copy.dst_operands_idx[0]  = child TaskResource.retrieve_reg_idx(dst_tag)
```

For `COPYT`, following lane rows receive:

```text
dst_operand = base + lane * 128
```

This is the key rule behind many route-forward diffs: the sender owns the COPY
instruction, but the destination operand is the receiver/child PE's operand.

## 7. OpenFabric mapping of these facts

Current OpenFabric diff work introduced a dedicated home for this behavior:

```text
compiler/gpdpu_compiler/core/dfu3500/task_resource_replay.py
```

The intended layering is:

```text
DFU template-bound instructions
  -> optional TaskResource replay / operand patching
  -> ProgramVendorABI
  -> ProgramBinRows
  -> serializer bytes
```

`program_bin.py` should not rediscover graph semantics.  It may serialize
already-final rows and patch mechanical COPY PE/block targets from row
provenance.  Operand allocation belongs to TaskResource replay or to the
existing default seed-table approximation.

Current implementation state:

```text
Default path:
  seed-table approximation remains enabled and stable.

Opt-in candidate:
  OPENFABRIC_ENABLE_DFU3500_TASK_RESOURCE_REPLAY=1
  enables source-derived TaskResource replay.
```

Current local candidate hashes:

```text
Default cbuf:        809a447dec84db46026c8ffc6dada8aff0b5644dc57362d88d8823e29c2e2506
Default micc:        ab56e64bff6f0d9b469146ef04d4584c2597f4bcbb1b951d49c43601eb2a9980

ORDER replay cbuf:  8b72f4fd5eeef7653a200736e047b2fe249dda8cc016ee7acf8f28cce347a33c
ORDER replay micc:  ab56e64bff6f0d9b469146ef04d4584c2597f4bcbb1b951d49c43601eb2a9980
```

Do not enable replay by default until remote arch-13 diff proves it improves
against vendor `result/cbuf_file.bin`.

## 8. How to interpret remaining CBUF diffs

Structured CBUF diffs with stride `304` bytes are almost always `inst_t` field
diffs.  Common patterns:

```text
value N -> N+1
  likely tag traversal / RAM reuse window drift

high byte 2/3 -> 0/1 or ±512
  likely tensor group mismatch

COPY dst differs but src matches
  likely receiver-side TaskResource patch mismatch

MICC matches but CBUF differs
  task/subtask layout is probably stable; focus on instruction fields
```

The biggest warning sign is a fix that changes MICC while trying to fix an
operand-index CBUF diff.  Most remaining GEMM replay work should only affect
`insts_file.bin` / `cbuf_file.bin`, not `micc_file.bin`.

## 9. Current open questions

1. Does arch-13 use exactly the same `REDUCE` macro state as local source?
2. Does OpenFabric's `VendorExeBlockRow` order match vendor `pPe->m_pGraph_nodes[i]`?
3. Does pseudo tensor handling happen at the same point relative to regular tag
   allocation in all stages?
4. Is `reg_start_idx` truly captured by current task index / seed-table logic,
   or should it be replayed from vendor `APP_Resource` counters?
5. Are remaining differences due to legal but manually chosen vendor template
   constants, or all algorithmic?

Keep these open until arch-13 diff validates the replay candidate.

## 10. Practical guidance for future agents

- Do not add more magic byte patches in `program_bin.py` unless the field is a
  confirmed serializer flag.
- Prefer consuming `common_oper` source (`inst_blk_map.cpp`, `task_print.cpp`,
  `exe_block_gen.cpp`) before interpreting OCR diff patterns.
- Treat `TaskResource` as vendor assembler state, not as front-end IR.
- Keep replay opt-in until remote diff proves it is better than the default
  seed-table path.
- Record every remote diff with the exact arch-13 path, username, app name, and
  whether it compared case `result/` or runtime `config/`.
