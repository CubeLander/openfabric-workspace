# GEMM Subtask Blocks And Graph Dependency

Date: 2026-06-30

Status: current evidence note.

Implementation note: this route is now represented in the refactored GEMM
source. `device_program/main.cpp` writes
`gpdpu_tensor/graph_trace/openfabric_graph_trace_data.h` during replay. GEMM no
longer maintains `operator_sources/gemm/graph_program`; replay builds one
common compatibility `libsubtask.so` from `common_app_builder/` and copies it to
the vendor `task*/subtask*/build_so/` locations required by
`common_oper/task_create.cpp`. The shim parses runtime `task*/subtask*` names
and reads generated graph content. Active subtasks 1..3 have generated trace
content; inactive `subtask4` will fail explicitly if enabled without adding
trace generation. `refactored_replay_compare_gemm` has verified binary/package
equivalence after the switch.

## Purpose

This note records the current GEMM refactored device code blocks and graph
dependencies side by side. It is kept in `docs/` because the implementation has
already converged on the graph-trace route described here.

Active source paths:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_refactored/operator_sources/gemm/device_program/main.cpp
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_refactored/operator_sources/gemm/device_program/gemm_template_program.h
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/common_app_builder/openfabric_graph_trace_hook.cpp
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/common_app_builder/openfabric_graph_trace_reader.h
```

Vendor subtask numbering and device-program subtask indexes are offset:

| Vendor directory | Device `subtask_index` | Active? | Meaning |
| --- | ---: | --- | --- |
| `subtask1` | 0 | yes | output/C prefill |
| `subtask2` | 1 | yes | load/broadcast A, load B, HMMA accumulate |
| `subtask3` | 2 | yes | output/C store |
| `subtask4` | none in current device main | no, `need_add_subtask=0` | secondary fusion path stub/evidence |

`device_program/config_run.sh` is materialized as vendor `csv_generate/run.sh`
and currently sets:

```text
task_num=4
need_add_subtask=0
subtask_count=3
```

So only vendor subtasks 1, 2, and 3 are active in the default GEMM replay.

## Upper Half: Device Subtask Code Blocks

The current device source constructs:

```text
GemmDistributedPlan program = make_gemm_distributed_plan();
```

and emits task/subtask instruction blocks from that plan. There are 4 tasks and
16 PEs.

### Subtask 1 / `subtask_index == 0`: Output Prefill

Source owner:

```text
device_program/main.cpp
```

Block count:

```text
16 blocks
```

Block table:

| Block id | Name | PE | Meaning |
| ---: | --- | ---: | --- |
| 0 | `output_prefill` | 0 | load output/C tile, emit `ALPHA`, `BET`, scale output by `BET` |
| 1 | `output_prefill` | 1 | same |
| 2 | `output_prefill` | 2 | same |
| 3 | `output_prefill` | 3 | same |
| 4 | `output_prefill` | 4 | same |
| 5 | `output_prefill` | 5 | same |
| 6 | `output_prefill` | 6 | same |
| 7 | `output_prefill` | 7 | same |
| 8 | `output_prefill` | 8 | same |
| 9 | `output_prefill` | 9 | same |
| 10 | `output_prefill` | 10 | same |
| 11 | `output_prefill` | 11 | same |
| 12 | `output_prefill` | 12 | same |
| 13 | `output_prefill` | 13 | same |
| 14 | `output_prefill` | 14 | same |
| 15 | `output_prefill` | 15 | same |

Program facts used:

- `program.task_count()`
- `program.subtask_count()`
- `site.pe_count()`
- `site.output_tile_ref()`
- `site.context_tile_view(output_tile_ref)`

This subtask is naturally graph-simple: one block/node per PE, no inter-node
dependencies declared by the current graph hooks.

### Subtask 2 / `subtask_index == 1`: A Broadcast And Compute

Source owner:

```text
device_program/main.cpp
device_program/gemm_template_program.h
```

Block count:

```text
input0 root load blocks: 4
input0 copy blocks:      12
input1 load+compute:     16
total:                   32
```

The block layout is computed in device source:

```text
input0_root_load_block_count = input0_broadcast_root_count(program)
input0_copy_block_begin = input0_root_load_block_count
input1_load_and_compute_block_begin = input0_copy_block_begin + input0_copy_block_count
```

Current constants:

```text
PE count = 16
input0 broadcast group width = 4
root PEs = 0, 4, 8, 12
copy PEs = 0, 1, 2, 4, 5, 6, 8, 9, 10, 12, 13, 14
compute PEs = 0..15
```

#### Subtask 2 Block Table

| Block id | Name | PE | Target PE | Meaning |
| ---: | --- | ---: | ---: | --- |
| 0 | `input0_root_load` | 0 | 0 | root PE loads A/input0 tile for group 0 |
| 1 | `input0_root_load` | 4 | 4 | root PE loads A/input0 tile for group 1 |
| 2 | `input0_root_load` | 8 | 8 | root PE loads A/input0 tile for group 2 |
| 3 | `input0_root_load` | 12 | 12 | root PE loads A/input0 tile for group 3 |
| 4 | `input0_copy` | 0 | 1 | copy A/input0 from PE0 to PE1 |
| 5 | `input0_copy` | 1 | 2 | copy A/input0 from PE1 to PE2 |
| 6 | `input0_copy` | 2 | 3 | copy A/input0 from PE2 to PE3 |
| 7 | `input0_copy` | 4 | 5 | copy A/input0 from PE4 to PE5 |
| 8 | `input0_copy` | 5 | 6 | copy A/input0 from PE5 to PE6 |
| 9 | `input0_copy` | 6 | 7 | copy A/input0 from PE6 to PE7 |
| 10 | `input0_copy` | 8 | 9 | copy A/input0 from PE8 to PE9 |
| 11 | `input0_copy` | 9 | 10 | copy A/input0 from PE9 to PE10 |
| 12 | `input0_copy` | 10 | 11 | copy A/input0 from PE10 to PE11 |
| 13 | `input0_copy` | 12 | 13 | copy A/input0 from PE12 to PE13 |
| 14 | `input0_copy` | 13 | 14 | copy A/input0 from PE13 to PE14 |
| 15 | `input0_copy` | 14 | 15 | copy A/input0 from PE14 to PE15 |
| 16 | `input1_load_and_compute` | 0 | 0 | load B/input1 and compute output tile on PE0 |
| 17 | `input1_load_and_compute` | 1 | 1 | load B/input1 and compute output tile on PE1 |
| 18 | `input1_load_and_compute` | 2 | 2 | load B/input1 and compute output tile on PE2 |
| 19 | `input1_load_and_compute` | 3 | 3 | load B/input1 and compute output tile on PE3 |
| 20 | `input1_load_and_compute` | 4 | 4 | load B/input1 and compute output tile on PE4 |
| 21 | `input1_load_and_compute` | 5 | 5 | load B/input1 and compute output tile on PE5 |
| 22 | `input1_load_and_compute` | 6 | 6 | load B/input1 and compute output tile on PE6 |
| 23 | `input1_load_and_compute` | 7 | 7 | load B/input1 and compute output tile on PE7 |
| 24 | `input1_load_and_compute` | 8 | 8 | load B/input1 and compute output tile on PE8 |
| 25 | `input1_load_and_compute` | 9 | 9 | load B/input1 and compute output tile on PE9 |
| 26 | `input1_load_and_compute` | 10 | 10 | load B/input1 and compute output tile on PE10 |
| 27 | `input1_load_and_compute` | 11 | 11 | load B/input1 and compute output tile on PE11 |
| 28 | `input1_load_and_compute` | 12 | 12 | load B/input1 and compute output tile on PE12 |
| 29 | `input1_load_and_compute` | 13 | 13 | load B/input1 and compute output tile on PE13 |
| 30 | `input1_load_and_compute` | 14 | 14 | load B/input1 and compute output tile on PE14 |
| 31 | `input1_load_and_compute` | 15 | 15 | load B/input1 and compute output tile on PE15 |

Subtask 2 high-level meaning:

```text
for each 4-PE row group:
  root PE loads A/input0
  PE0->PE1->PE2->PE3 style copy chain distributes A/input0
  every PE loads its B/input1 tile
  every PE runs HMMA accumulation for its output tile
```

The device source already owns enough information to describe this graph:

- `input0_broadcast_root_count(program)`
- `input0_broadcast_root_pe(root_index)`
- `pe_copies_input0_to_next_lane(pe_id)`
- `input0_broadcast_group_id`
- `input0_copy_block_begin`
- `input1_load_and_compute_block_begin`
- `source_block`
- `target_block`
- `target_pe_id`

### Subtask 3 / `subtask_index == 2`: Output Store

Source owner:

```text
device_program/main.cpp
```

Block count:

```text
16 blocks
```

Block table:

| Block id | Name | PE | Meaning |
| ---: | --- | ---: | --- |
| 0 | `output_store` | 0 | store output/C tile |
| 1 | `output_store` | 1 | same |
| 2 | `output_store` | 2 | same |
| 3 | `output_store` | 3 | same |
| 4 | `output_store` | 4 | same |
| 5 | `output_store` | 5 | same |
| 6 | `output_store` | 6 | same |
| 7 | `output_store` | 7 | same |
| 8 | `output_store` | 8 | same |
| 9 | `output_store` | 9 | same |
| 10 | `output_store` | 10 | same |
| 11 | `output_store` | 11 | same |
| 12 | `output_store` | 12 | same |
| 13 | `output_store` | 13 | same |
| 14 | `output_store` | 14 | same |
| 15 | `output_store` | 15 | same |

This subtask is also graph-simple: one block/node per PE, no inter-node
dependencies declared by the current graph hooks.

### Inactive Subtask 4

There are checked-in graph hook sources for vendor `subtask4`, but current
device main does not emit a corresponding subtask, and `run.sh` does not build
it because `need_add_subtask=0`.

Treat subtask4 as inactive secondary-fusion evidence, not part of the current
single-truth convergence target.

## Lower Half: Graph Nodes And Edge Dependencies

Historical vendor graph hooks included:

```text
../../../../csv_generate/conf_PEmap.h
```

That header provided external facts such as:

```text
taskAddr_per_pe_A
taskAddr_per_pe_B
taskAddr_per_pe_C
copyA
loadA
HASCP2CP
```

Those vendor `conf_PEmap.h` values relevant to graph construction were:

```text
loadA roots: 0, 4, 8, 12
loadA[root] = {0, 1, 2, 3} for every root

copyA[0] = copyA[1] = copyA[2] = copyA[3]
         = {(0,1),(1,2),(2,3),
            (4,5),(5,6),(6,7),
            (8,9),(9,10),(10,11),
            (12,13),(13,14),(14,15)}

HASCP2CP = 1
```

Because every `loadA[root]` covers tasks 0..3 and every `copyA[task]` is the
same, active graph topology is the same for task0, task1, task2, and task3.
Only the source expression selects a different task/unroll index.

### Graph For Subtasks 1 And 3

Active shape:

```text
16 graph nodes
node index == CSV block id == PE id
m_pos_idx_df == PE id
initNode(..., node_index, true, inst_block_collect)
no set_relationship_node calls
```

This matches the device code block layout:

```text
subtask1 output_prefill block id == PE id
subtask3 output_store block id == PE id
```

### Graph For Subtask 2: Node Dump

Important observation:

The graph source prints and stores a legacy key like `pe + 0`, `pe + 16`, or
`pe + 32`, but it calls:

```text
initNode(m_nodes[index], index, ..., inst_block_collect)
```

So the actual graph node index / CSV block id is the compact `index`, not the
printed legacy key. `nodeMap` translates from the old key space into compact
block ids.

This is the key convergence point:

```text
graph node index == device CSV block id
```

Node table:

| Node index / CSV block id | Legacy key used by `nodeMap` | Node kind | PE | `initNode` third arg | Meaning |
| ---: | ---: | --- | ---: | --- | --- |
| 0 | 0 | `input0_root_load` | 0 | `false` | root A load |
| 1 | 4 | `input0_root_load` | 4 | `false` | root A load |
| 2 | 8 | `input0_root_load` | 8 | `false` | root A load |
| 3 | 12 | `input0_root_load` | 12 | `false` | root A load |
| 4 | 16 | `input0_copy` | 0 | `false` | A copy PE0 -> PE1 |
| 5 | 17 | `input0_copy` | 1 | `false` | A copy PE1 -> PE2 |
| 6 | 18 | `input0_copy` | 2 | `false` | A copy PE2 -> PE3 |
| 7 | 20 | `input0_copy` | 4 | `false` | A copy PE4 -> PE5 |
| 8 | 21 | `input0_copy` | 5 | `false` | A copy PE5 -> PE6 |
| 9 | 22 | `input0_copy` | 6 | `false` | A copy PE6 -> PE7 |
| 10 | 24 | `input0_copy` | 8 | `false` | A copy PE8 -> PE9 |
| 11 | 25 | `input0_copy` | 9 | `false` | A copy PE9 -> PE10 |
| 12 | 26 | `input0_copy` | 10 | `false` | A copy PE10 -> PE11 |
| 13 | 28 | `input0_copy` | 12 | `false` | A copy PE12 -> PE13 |
| 14 | 29 | `input0_copy` | 13 | `false` | A copy PE13 -> PE14 |
| 15 | 30 | `input0_copy` | 14 | `false` | A copy PE14 -> PE15 |
| 16 | 32 | `input1_load_and_compute` | 0 | `true` | load B and compute |
| 17 | 33 | `input1_load_and_compute` | 1 | `true` | load B and compute |
| 18 | 34 | `input1_load_and_compute` | 2 | `true` | load B and compute |
| 19 | 35 | `input1_load_and_compute` | 3 | `true` | load B and compute |
| 20 | 36 | `input1_load_and_compute` | 4 | `true` | load B and compute |
| 21 | 37 | `input1_load_and_compute` | 5 | `true` | load B and compute |
| 22 | 38 | `input1_load_and_compute` | 6 | `true` | load B and compute |
| 23 | 39 | `input1_load_and_compute` | 7 | `true` | load B and compute |
| 24 | 40 | `input1_load_and_compute` | 8 | `true` | load B and compute |
| 25 | 41 | `input1_load_and_compute` | 9 | `true` | load B and compute |
| 26 | 42 | `input1_load_and_compute` | 10 | `true` | load B and compute |
| 27 | 43 | `input1_load_and_compute` | 11 | `true` | load B and compute |
| 28 | 44 | `input1_load_and_compute` | 12 | `true` | load B and compute |
| 29 | 45 | `input1_load_and_compute` | 13 | `true` | load B and compute |
| 30 | 46 | `input1_load_and_compute` | 14 | `true` | load B and compute |
| 31 | 47 | `input1_load_and_compute` | 15 | `true` | load B and compute |

### Graph For Subtask 2: Edge Dump

All active tasks produce the same edge set.

#### Root A Load To Local Compute

Source code shape:

```text
set_relationship_node(nodeMap[pe], nodeMap[pe + 32], 0xffffffff)
```

| Edge kind | Source node | Destination node | PE relation | Parameter |
| --- | ---: | ---: | --- | ---: |
| root-load -> compute | 0 | 16 | PE0 -> PE0 | `0xffffffff` |
| root-load -> compute | 1 | 20 | PE4 -> PE4 | `0xffffffff` |
| root-load -> compute | 2 | 24 | PE8 -> PE8 | `0xffffffff` |
| root-load -> compute | 3 | 28 | PE12 -> PE12 | `0xffffffff` |

#### Root A Load To First Copy

Source code shape:

```text
set_relationship_node(nodeMap[pe], nodeMap[pe + 16], 0xffffffff)
```

| Edge kind | Source node | Destination node | PE relation | Parameter |
| --- | ---: | ---: | --- | ---: |
| root-load -> copy | 0 | 4 | PE0 -> PE0 copy | `0xffffffff` |
| root-load -> copy | 1 | 7 | PE4 -> PE4 copy | `0xffffffff` |
| root-load -> copy | 2 | 10 | PE8 -> PE8 copy | `0xffffffff` |
| root-load -> copy | 3 | 13 | PE12 -> PE12 copy | `0xffffffff` |

#### Copy To Copy

Source code shape:

```text
set_relationship_node(nodeMap[p.first + 16], nodeMap[p.first + 17], 0)
```

| Edge kind | Source node | Destination node | PE relation | Parameter |
| --- | ---: | ---: | --- | ---: |
| copy -> copy | 4 | 5 | PE0 copy -> PE1 copy | 0 |
| copy -> copy | 5 | 6 | PE1 copy -> PE2 copy | 0 |
| copy -> copy | 7 | 8 | PE4 copy -> PE5 copy | 0 |
| copy -> copy | 8 | 9 | PE5 copy -> PE6 copy | 0 |
| copy -> copy | 10 | 11 | PE8 copy -> PE9 copy | 0 |
| copy -> copy | 11 | 12 | PE9 copy -> PE10 copy | 0 |
| copy -> copy | 13 | 14 | PE12 copy -> PE13 copy | 0 |
| copy -> copy | 14 | 15 | PE13 copy -> PE14 copy | 0 |

Note: the current source checks `next(p)->first` inside the loop. The intended
edge set is clear from the produced chain, but the expression is fragile around
the last vector element and should not be copied into the future source of
truth.

#### Copy To Target Compute

Source code shape:

```text
set_relationship_node(nodeMap[pe + 16], nodeMap[pe + 33], HASCP2CP ? 1 : 0)
```

Current `HASCP2CP = 1`.

| Edge kind | Source node | Destination node | PE relation | Parameter |
| --- | ---: | ---: | --- | ---: |
| copy -> compute | 4 | 17 | PE0 copy -> PE1 compute | 1 |
| copy -> compute | 5 | 18 | PE1 copy -> PE2 compute | 1 |
| copy -> compute | 6 | 19 | PE2 copy -> PE3 compute | 1 |
| copy -> compute | 7 | 21 | PE4 copy -> PE5 compute | 1 |
| copy -> compute | 8 | 22 | PE5 copy -> PE6 compute | 1 |
| copy -> compute | 9 | 23 | PE6 copy -> PE7 compute | 1 |
| copy -> compute | 10 | 25 | PE8 copy -> PE9 compute | 1 |
| copy -> compute | 11 | 26 | PE9 copy -> PE10 compute | 1 |
| copy -> compute | 12 | 27 | PE10 copy -> PE11 compute | 1 |
| copy -> compute | 13 | 29 | PE12 copy -> PE13 compute | 1 |
| copy -> compute | 14 | 30 | PE13 copy -> PE14 compute | 1 |
| copy -> compute | 15 | 31 | PE14 copy -> PE15 compute | 1 |

## Stare Test: Can This Converge To One Source Of Truth?

Yes, for the active GEMM graph topology, this looks very convergent.

The current graph can be projected from the same facts already used by
`device_program/main.cpp`:

```text
PE count = 16
task count = 4
subtask count = 3
input0 broadcast group width = 4
root PE for group = group * 4
copy edge exists when pe % 4 != 3
compute block exists for every PE
HASCP2CP = true
```

These facts produce:

```text
subtask2 root-load block ids: 0..3
subtask2 copy block ids:      4..15
subtask2 compute block ids:   16..31
subtask2 graph node ids:      same as block ids
```

The graph's `nodeMap` is not a separate semantic source. It is a compatibility
adapter from legacy PE-key values:

```text
root-load legacy key = pe + 0
copy legacy key      = pe + 16
compute legacy key   = pe + 32
```

to current compact block ids:

```text
root-load block id = root_group_index
copy block id      = 4 + copy_order
compute block id   = 16 + pe
```

This should be modeled explicitly in a future `GemmSubtask2GraphProjection`,
instead of re-deriving graph topology from `conf_PEmap.h`.

## Proposed Single-Truth Shape

The next small abstraction should be local to GEMM and should describe subtask2
block and graph topology together:

```cpp
enum GemmSubtask2NodeKind {
  GemmSubtask2Input0RootLoad,
  GemmSubtask2Input0Copy,
  GemmSubtask2Input1LoadAndCompute,
};

struct GemmSubtask2Node {
  int node_id;
  int csv_block_id;
  int pe_id;
  int target_pe_id;
  GemmSubtask2NodeKind kind;
  bool init_node_third_arg;
  int legacy_key;
};

struct GemmSubtask2Edge {
  int source_node_id;
  int destination_node_id;
  int relationship_param;
  const char *kind;
};
```

Authority should be:

```text
GemmDistributedPlan
  + GEMM broadcast/copy schedule helpers
  -> subtask2 block schedule
  -> CSV emission
  -> graph node/edge projection
  -> generated graph trace data
```

## Suggested Next Implementation Unit

Add a read-only checker/generator first:

```text
tools/vendor_case/.../dump_gemm_graph_projection.py
```

or a small C++/Python-independent local report if preferred by the build
system. It should print:

```text
task, subtask, node_id, csv_block_id, pe_id, node_kind, legacy_key
task, subtask, edge_kind, source_node_id, destination_node_id, relationship_param
```

Then compare the generated projection against this note's tables and the
current graph source behavior.

Acceptance for the first checker:

- subtask1 emits 16 simple nodes and no edges
- subtask2 emits 32 nodes and the 28 edges listed above
- subtask3 emits 16 simple nodes and no edges
- block ids match `device_program/main.cpp`
- no package-generation behavior changes
