# DFU3500 TaskResource ORDER Replay Update

Date: 2026-06-16

## Source evidence

Local `simict3500final/.../common_oper/inst_blk_map.cpp` now contains the full
vendor `Task_Resource` implementation, not just the older stub.  The active
compile-time path has:

```cpp
//#define REDUCE 1
#define RANDOM 1
#define ORDER 1
```

Therefore GEMM binary compatibility should model normal `fill_reg_idx()`, not
`fill_reg_idx_rd()`, unless future arch-13 evidence shows different macros.

Key source facts:

- `INST_BLK_MAP::start_map_task()` creates one `Task_Resource` per PE and runs
  graph nodes from `node_idx_start` to the end for that PE.
- For each exeBlock it calls `fill_reg_idx()` in stage order:
  `LD -> CAL -> FLOW -> ST`.
- `fill_reg_idx()` calls `get_rest_ram_rec()` at stage start, creating a
  stage-local list of free operand RAM indices.
- With `ORDER`, `alloc_operand_slot()` picks the first available RAM index and
  pops the high line from that RAM's `m_reg_lists[ram_idx]`.
- `PE::PE()` initializes regular RAM pools as:
  `ram_idx * 128 + line_idx`, pushed low-to-high, so `pop_back()` returns
  `ram_idx * 128 + 127` first.
- Tensor pseudo operands use `alloc_operand_slot4tensor()`: choose the available
  tensor group with most free slots, then pop high-to-low inside that group.
- Regular allocation erases the corresponding first tensor slot via
  `erase_value_from_tensor_regs_available_general()`.
- `fill_copy_inst()` patches COPY destination PE/block and destination operand
  from the child/receiver PE's `Task_Resource.retrieve_reg_idx()`.

## Implemented in OpenFabric

`compiler/gpdpu_compiler/core/program_task_resource.py` now includes:

- `Dfu3500TaskResourceState(allocation_mode="layout_counter")` for existing
  source-derived layout tests and default-safe behavior.
- `Dfu3500TaskResourceState(allocation_mode="order_pool")` for opt-in replay.
- Stage-local `begin_stage()` and 3-instruction RAM reuse window
  `finish_instruction()`.
- Regular ORDER pool allocation and tensor high-to-low group allocation.
- Opt-in replay behind:

```bash
OPENFABRIC_ENABLE_DFU3500_TASK_RESOURCE_REPLAY=1
```

When replay is enabled, `ProgramVendorABI.folded_vendor_report` receives a
`task_resource_replay` marker.  `program_bin.py` reads this marker and avoids
re-patching COPY destination operands in the serializer; it still patches COPY
PE/block targets there, because replay only owns operand fields.

## Local candidate hashes

Default seed-table output remains unchanged:

```text
config/cbuf_file.bin         809a447dec84db46026c8ffc6dada8aff0b5644dc57362d88d8823e29c2e2506
config/micc_file.bin         ab56e64bff6f0d9b469146ef04d4584c2597f4bcbb1b951d49c43601eb2a9980
simulator_bin/insts_file.bin a674fade6910f013fe447cb4932fc5d252a5c58ce1b95b9de6edceebc602cb44
```

ORDER replay candidate:

```text
config/cbuf_file.bin         8b72f4fd5eeef7653a200736e047b2fe249dda8cc016ee7acf8f28cce347a33c
config/micc_file.bin         ab56e64bff6f0d9b469146ef04d4584c2597f4bcbb1b951d49c43601eb2a9980
simulator_bin/insts_file.bin be2178315aae18711f263bf605c9993d4276744d3fe6228bb290ecd94db0f32a
```

Diff counts:

```text
layout-counter replay -> ORDER replay: 22960 CBUF/insts bytes
current default       -> ORDER replay: 90416 CBUF/insts bytes
MICC unchanged in all variants
```

## Current conclusion

Do not enable replay by default yet.  The newest arch-13 diff before this work
was only about `14944` CBUF bytes, so the ORDER replay candidate is still a
validation branch rather than a replacement for the seed-table path.

Likely remaining mismatches are not byte-packing issues; they are algorithmic:

1. exact vendor graph-node traversal order per `(task, PE)`, especially whether
   OpenFabric exeblock order matches `pPe->m_pGraph_nodes[i]`;
2. exact pseudo tensor instruction handling inside `fill_reg_idx()` before the
   regular operand binding step;
3. `reg_start_idx` / app resource counter semantics across tasks;
4. whether arch-13 runtime uses the same `REDUCE` macro state as local source.

The next useful remote experiment is to upload the ORDER replay candidate and
compare against arch-13 vendor `result/cbuf_file.bin`; if the diff grows, keep
replay off and refine traversal/order before touching default output.
