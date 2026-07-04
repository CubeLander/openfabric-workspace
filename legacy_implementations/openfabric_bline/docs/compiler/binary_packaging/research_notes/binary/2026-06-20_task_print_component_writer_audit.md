# task_print Component Writer Audit

Date: 2026-06-20

Status: binary note, source-first audit for MICC/CBUF writer behavior

This note narrows in on vendor `task_print.cpp`: the place where graph/task
metadata becomes simulator component files.  It complements:

```text
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_common_oper_task_graph_exeblock_audit.md
```

The important lesson from A-line is brutal but useful: even when instructions
execute, wrong writer-side control metadata can make SimICT hang in `rest(1)`,
`recv inst conf`, or phantom padded task states.  B-line must model these writer
facts explicitly instead of hand-filling bytes.

## Source Fingerprint

Source root:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper
```

Audited file:

```text
d9c1af31a926e3f960706827f0bd15df7676656f2b491325f226637b48a1bef2  task_print.cpp
```

Warning: local source may differ from arch-13.  Use this as algorithm evidence
and continue remote binary validation for exact struct layout and constants.

## 1. Simulator `inst_t` And RTL Projection Are Different Views

`write_rtl_inst()` converts vendor `inst_t` into several RTL structs, selected
by opcode class.  This is not the simulator CBUF `insts_file.bin` itself; it is
a debug/RTL projection with its own packing rules.

Source evidence:

```text
task_print.cpp:15-191
```

Important mappings observed:

```text
LD/ST-like ops:
  base_addr_idx = iter_exe_cond

Special CAL ops:
  base_addr_idx = iter_exe_cond

COPY:
  base_addr_idx = flow_ack
  dst_pe_x / dst_pe_y copied into flow RTL struct

IMM/FIMM:
  imm_1 = imm
  imm_2 = imm >> 24
  base_addr_idx = iter_exe_cond
```

The FRCP-family special CAL path folds multiple opcodes into `OP_FRCP` and uses
immediate bits to distinguish variants.  In the audited source, examples include:

```text
FLOG2 -> imm |= 1 << 5
FEXP2 -> imm |= 1 << 6
```

### B-line implication

Do not treat one opcode integer as the whole executable contract.  A binding
layer needs at least two projections:

```text
simulator instruction row:
  CBUF inst_t fields consumed by SimICT

RTL/debug projection:
  op-family compact structs used by writer-side debug/RTL files
```

Required owner candidate:

```text
InstructionEncodingPlan:
  simulator_inst_fields
  rtl_debug_projection_fields
```

## 2. `iter_exe_cond` Is A Real Address/Base Selector Field

Several instruction families write `iter_exe_cond` into `base_addr_idx` in the
RTL projection.  A-line repeatedly hit memory-layout/control-plane confusion;
this source confirms `iter_exe_cond` is not a harmless spare flag.

Observed users:

```text
STM / LD-ST-like rows
special CAL rows
IMM / FIMM rows
```

COPY is different:

```text
COPY base_addr_idx comes from flow_ack, not iter_exe_cond
```

### B-line implication

The field named `iter_exe_cond` has at least one vendor-facing role as an address
or base-address selector in generated artifacts.  Do not overload it as an
arbitrary loop/debug flag in B-line.

Required owner candidate:

```text
BaseAddressBindingPlan:
  per-op base slot source
  iter_exe_cond assignment
  copy/route flow_ack assignment
```

## 3. `print_inst` Writes Per-PE Instruction Streams Before Global Merge

`print_inst()` traverses each PE's graph nodes, filters valid instructions stage
by stage, writes a PE-local temporary instruction stream, and records:

```text
exe_block_conf.inst_mem_based_addr = file_start_pos
```

Source evidence:

```text
task_print.cpp:597-658
```

The stage order is fixed:

```text
LD -> CAL -> FLOW -> ST
```

Only valid instructions are counted and written.

### B-line implication

`inst_mem_based_addr` is not global package position and not fiber action order.
It is the start offset of this block in the PE-local instruction stream before
fixed-capacity padding and final PE-order merge.

Required owner candidate:

```text
InstructionLayoutPlan:
  per_pe_stream[pe]
  block_inst_start_offset[pe, block]
  valid_inst_filter
  stage_order = LD/CAL/FLOW/ST
```

## 4. `print_block_conf` Re-bases Stage PCs With Per-PE Running Counters

`print_block_conf()` converts each graph node's exeBlock into per-PE block rows.
It patches final task/subtask metadata, then adjusts `stages_start_pc[]` using a
static per-PE running instruction counter:

```text
stages_start_pc[pc] = pc_temp[pc] + pe_inst_count[pe_idx] - pc_temp[0]
pe_inst_count[pe_idx] = end_pc
```

Source evidence:

```text
task_print.cpp:332-400
```

### B-line implication

Stage PCs are late-bound.  They cannot be finalized when a stream/fiber action is
created, because pseudo-op expansion, validity filtering, and PE-local merge
order are still unsettled.

Required owner candidate:

```text
VendorBlockWriterPlan:
  task/subtask stamp
  pe-local block index
  stage_pc_rebase
  pe_inst_count accumulator
```

## 5. ExeBlock Task/Subtask Fields Are Stamped Late

The writer stamps every block row with subtask control metadata:

```text
instances_amount
instances_idx
instances_addr_mem_based_addr
task_idx
subtask_idx
block_idx
```

Source evidence:

```text
task_print.cpp:332-400
task_print.cpp:403-407
```

### B-line implication

Block formation and task packaging are separate.  A block can know its graph
identity and PE-local block index before it knows its final package task/subtask
row ownership.

Required owner candidate:

```text
TaskPackagingPlan:
  active_task_rows
  active_subtask_rows
  block_owner(task, subtask, instance_policy)
```

## 6. Component Files Are Padded Per PE And Then Merged In PE Order

`fill_max_inst_per_pe()` pads every PE-local instruction stream to fixed vendor
capacity, pads every PE-local block-conf stream, then merges the per-PE files into
final simulator component files.

Source evidence:

```text
task_print.cpp:514-580
```

Final simulator merge shape:

```text
for pe in PE order:
  append tmp inst stream for this PE

for pe in PE order:
  append tmp exeBlock stream for this PE
```

### B-line implication

CBUF physical file size and section order are capacity-driven, not active-row
count-driven.  Runtime counts must come from active task/subtask metadata, while
component blobs must still include padded capacity.

This distinction directly explains the A-line class of bugs where a payload had
one active task but runtime/control metadata still behaved like four tasks.

Required owner candidate:

```text
VendorComponentPlan:
  active_rows
  padded_capacity_rows
  merge_order
  component_file_size_guard
```

## 7. Task/Subtask Rows Are Active First, Then Padded

`print_task_group()` writes active task rows and active subtask rows, then pads
subtask capacity for the active task range and finally pads empty task/subtask
rows up to `MAX_CUR_TASK_CONF_PER_APP`.

Source evidence:

```text
task_print.cpp:722-796
```

`fill_task_simulator()` pads from active task count to fixed task capacity:

```text
for empty task slots:
  write empty task row
  write MAX_SUBTASK_PER_TASK empty subtask rows
```

Source evidence:

```text
task_print.cpp:798-818
```

### B-line implication

These are two different numbers:

```text
active task amount:
  what MicC/runtime should start or expect

fixed task capacity:
  how many padded rows exist in component files
```

A-line guard requirement:

```text
runtime task count must equal active task rows, not padded task capacity
```

## 8. Subtask And Task Successor Chains Are Writer-generated Defaults

`print_task()` links subtasks linearly by patching the previous active subtask's
first successor to the current active subtask global index.  The first active
subtask is marked `is_exe_start`, and the final active subtask is marked
`is_exe_end`.

Source evidence:

```text
task_print.cpp:662-720
```

`print_task_group()` similarly links tasks linearly and marks group start/end.

Source evidence:

```text
task_print.cpp:722-760
```

### B-line implication

Legacy task/subtask sequencing is a packaging projection.  It should be emitted
from one task/subtask chain plan, not copied separately into MICC, exeblock rows,
runtime control, and validation scripts.

Required owner candidate:

```text
TaskControlPlan:
  active task order
  active subtask order per task
  start/end flags
  successor rows
```

## 9. `taskEnable.bin` Is Not Automatically Runtime Truth

`task_inst_enable_print()` emits RTL/debug helper files including:

```text
instEnable.bin
taskEnable.bin
data_inst_replace.bin
```

Source evidence:

```text
task_print.cpp:820-859
```

The audited `taskEnable.bin` logic writes zeroes for early slots and ones for the
last `task_num` slots:

```text
if i < MAX_CUR_TASK_CONF_PER_APP - task_num:
  write 0
else:
  write 1
```

### B-line implication

This looks reversed compared with active task rows written from index zero.  Treat
it as RTL/debug-side evidence until proven otherwise.  Do not use this file as the
source of runtime `task_num` or MicC active task selection.

Required guard:

```text
runtime task_count must be explicitly derived from active package rows
not inferred from taskEnable.bin text projection
```

## 10. Inst/Block Writer And Runtime Control Must Agree

A-line pain showed several failure modes:

```text
rest(1): active completion expectation mismatched emitted tasks/blocks
recv inst conf hang: runtime expected more instruction config than blob supplied
phantom task count: one active task but 4-task runtime/control metadata
```

The writer-side source explains why these happened: the vendor flow derives
control metadata from graph/task/package writers in one coherent sequence.  When
OpenFabric manually patched only one layer, SimICT waited for metadata promised
elsewhere.

### B-line invariant

Before a package is considered runnable:

```text
active_task_count == runtime launch task count
active_subtask rows match task successor/end flags
exeBlock rows have final task/subtask owner stamps
per-PE instruction counts match emitted instruction stream capacity
padded rows exist only as capacity, not runtime work
```

## B-line Owner Map

| Writer fact | B-line owner candidate |
| --- | --- |
| simulator vs RTL instruction projection | `InstructionEncodingPlan` + optional `RtlDebugProjection` |
| `iter_exe_cond` / `flow_ack` base selector behavior | `BaseAddressBindingPlan` |
| valid instruction filtering and stage order | `InstructionLayoutPlan` |
| late stage PC rebase | `VendorBlockWriterPlan` |
| late task/subtask block stamps | `TaskPackagingPlan` |
| active rows vs padded capacity | `VendorComponentPlan` |
| task/subtask linear start/end/successor flags | `TaskControlPlan` |
| runtime/task count agreement | `RuntimeControlPlan` guard |

## Immediate Verifier Candidates

These should become B-line guards before another functional payload is called
runnable:

```text
1. active_task_count != padded_task_capacity unless all tasks are truly active.
2. runtime launch task_count == active_task_count.
3. every active subtask chain has exactly one start and one end.
4. no non-last active subtask has missing successor.
5. no last active subtask has a bogus successor.
6. every active exeBlock row has stamped task_idx/subtask_idx.
7. stage_start_pc[MAX] equals the PE-local end PC for that block.
8. inst_mem_based_addr points inside that PE's instruction stream.
9. component file sizes equal fixed vendor capacities.
10. padded rows are zero/disabled and are not counted as active runtime work.
```

## Open Research Gaps

Still not fully audited here:

```text
1. Exact simulator struct definitions for task/subtask/exeBlock rows.
2. Which runtime-side fields consume `taskEnable.bin`, if any.
3. Whether arch-13 `task_print.cpp` differs from this local snapshot.
4. Exact relationship between `instEnable.bin` and simulator instruction config.
5. How data_inst_replace rows are consumed by runtime / RTL / SimICT.
```

These should stay in `docs/compiler/binary_packaging/research_notes/binary` until proven and then graduate to
`docs/vendor_reference`.
