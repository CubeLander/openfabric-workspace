# Vendor Assembler Composition Rules From Original Source

Date: 2026-06-24

Status: source-backed rule extraction for B-line assembler-input work

Scope:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/build_app
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper
simict3500final/gpdpu/users/risc_nn_riscv/common/src
```

## Summary

The customer "assembler" is not a thin final-byte writer.  It consumes a case
package, completes graph/resource binding, and only then prints simulator/RTL
binary components.  B-line should therefore generate the same input package
shape:

```text
app*.conf
  + task*/subtask*/template/*.csv
  + task*/subtask*/build_so/libsubtask.so::generateGraph(...)
  + optional runtime case material
  -> build_app/common_oper
  -> simulator_bin + rtl_bin
  -> result/cbuf_file.bin + result/micc_file.bin
```

The key stop-bleeding decision is:

```text
B-line owns semantic tile/fiber/template provenance.
VendorAssemblerInputBundle owns case/package projection.
common_oper owns final operand/resource/COPY/exeBlock/binary completion.
```

Local Python final-byte writers should remain comparison and evidence tools
until a narrower writer has source-backed proof and runtime validation.

## Source Caveat

Most files under `testcase/common_oper` are normal source evidence.  The local
`inst_blk_map.cpp` snapshot contains OCR/markdown fence fragments in addition
to C++ bodies, so this note treats it as algorithm evidence and cross-checks the
important rules against cleaner files where possible.  Any production replay of
the mapper must be validated against the real vendor build or the remote
arch-13 copy.

## Entry Rule: The Input Is A Case Package

`build_app/main.cpp` reads one or more `app*.conf` files, constructs every task
group, maps it through `INST_BLK_MAP`, then runs exeBlock generation and
printing:

```text
Task_Group::readFromTaskFile(...)
Task_Group::tasksConstruct()
Task_Group::map(...)
exe_block_gen(...)
Print_Task_Group::print_task_group(...)
Print_Task_Group::print_inst(...)
Print_Task_Group::fill_max_inst_per_pe(...)
Print_Task_Group::fill_task_simulator(...)
Print_Task_Group::task_inst_enable_print(...)
Print_Task_Group::print_for_micc_rtl(...)
```

Source anchors:

```text
application/build_app/main.cpp:38
application/build_app/main.cpp:39
application/build_app/main.cpp:42
application/build_app/main.cpp:71
application/build_app/main.cpp:78
application/build_app/main.cpp:79
application/build_app/main.cpp:80
application/build_app/main.cpp:81
application/build_app/main.cpp:82
```

Assembler input implication:

- `app*.conf` is the top-level task/subtask manifest.
- CSV files are not enough; every subtask also needs graph construction code.
- B-line should archive the generated input bundle before invoking the vendor
  assembler so binary diffs can be explained from stable sources.

## Task/Subtask Rule: Config Drives Template And Graph Loading

`Task_Group::tasksConstruct()` walks parsed tasks and calls subtask
construction.  Each subtask loads `template/<i>.csv`, then dynamically loads
`build_so/libsubtask.so` and calls `generateGraph(...)`.

The `app*.conf` fields are parsed as container metadata:

```text
task:
  task_name
  reuse_input_reg
  reuse_output_reg
  Execute Times
  subtask_num

subtask:
  subtask_name
  reuse_input_reg
  reuse_output_reg
  Instance Times
  code_path
  csv_amount
  graph height
  graph width
```

Source anchors:

```text
common_oper/task_create.cpp:287
common_oper/task_create.cpp:293
common_oper/task_create.cpp:307
common_oper/task_create.cpp:127
common_oper/task_create.cpp:146
common_oper/task_create.cpp:184
```

Assembler input implication:

- `csv_amount` must match the number of template CSV files the subtask expects.
- `graph height` / `graph width` are passed to `generateGraph(...)`; they are
  not merely UI/debug metadata.
- `Instance Times` and `Execute Times` flow into runtime task/subtask config,
  not into CSV instruction rows.

## CSV Rule: CSV Rows Are Template Instructions With Symbolic Operands

CSV parsing skips the header, reads non-empty lines, and expects fixed fields:

```text
inst_name,
inst_tag_name,
src_reg_idx0,
src_reg_idx1,
dst_reg_idx,
dst_pe_idx,
imm,
iteration,
extra_field0?,
extra_field1?,
extra_field2?
```

`Csv_Operate::getRegIdx(...)` assigns CSV-local symbolic operand IDs:

- blank field -> `0`;
- names beginning with `r` go into the reuse-register map;
- all other names go into the normal operand map.

These are local symbolic IDs, not final PE operand RAM indices.  Final binding
is later performed by `Task_Resource::fill_reg_idx(...)`.

Source anchors:

```text
common_oper/csv_oper.cpp:388
common_oper/csv_oper.cpp:412
common_oper/csv_oper.cpp:440
common_oper/csv_oper.cpp:462
common_oper/csv_oper.cpp:464
common_oper/csv_oper.cpp:466
common_oper/csv_oper.cpp:515
common_oper/inst_blk_map.cpp:568
```

Assembler input implication:

- B-line CSV output should preserve stable symbolic operand tags.
- B-line should not pre-bake final operand RAM numbers into CSV rows.
- Every emitted CSV row must retain provenance back to `TemplateOp` and
  `FiberOp`, because common_oper will mutate fields after CSV parse.

## CSV Pseudo-Op Rule: Some Rows Expand Before Stage Splitting

`Csv_Operate::process()` maps op names to opcode, unit type, latency, immediates,
iteration conditions, operand tags, destination PE field, and extra fields.
Some pseudo/vector rows are converted to an expanded opcode and append following
rows.

Important observed mappings include:

```text
HLDT / ILDT -> LDN
ILDMT / SLDM -> LDM
HSTT / ISTT -> STD
COPYT / LCOPYT -> COPY
SSTM -> STM
SSTMD64 -> STMD64
SSTCNST -> STCNST
SSTSHIF -> STSHIF
```

For appended pseudo rows, non-COPYT/non-LCOPYT immediates are shifted by:

```text
i * ((dst_pe_idx + 1) * 32)
```

Some pseudo rows also mask the raw `dst_pe_idx` before it becomes
`dst_pes_pos[0].x`:

```text
ILDMT   -> raw_dst_pe & 0x1
SLDCNST -> raw_dst_pe & 0x3
default -> raw_dst_pe
```

Source anchors:

```text
common_oper/csv_oper.cpp:133
common_oper/csv_oper.cpp:480
common_oper/csv_oper.cpp:503
common_oper/csv_oper.cpp:515
common_oper/csv_oper.cpp:558
common_oper/csv_oper.cpp:560
```

Assembler input implication:

- `TemplateCsvProgram` may emit pseudo rows if the vendor parser owns their
  expansion.
- B-line's debug binary rows must not assume a one-to-one mapping from CSV row
  to final instruction row.
- COPYT/LCOPYT are especially sensitive because later graph/resource passes
  patch the expanded destinations.

## Stage Rule: CSV Must Already Be LD -> CAL -> FLOW -> ST Ordered

`Inst_Block::process()` consumes the parsed instruction list in four contiguous
runs:

```text
LD stage
CAL stage
FLOW stage
ST stage
```

If any instruction remains after those four scans, it exits with
`block inst amount != csv inst amount`.

Source anchors:

```text
common_oper/inst_blk_gen.cpp:27
common_oper/inst_blk_gen.cpp:39
common_oper/inst_blk_gen.cpp:48
common_oper/inst_blk_gen.cpp:57
common_oper/inst_blk_gen.cpp:67
common_oper/inst_blk_gen.cpp:76
```

Assembler input implication:

- B-line CSV emitters need a deterministic per-block stage sorter.
- The sorter must be explicit in the bundle manifest so review can tell whether
  a row moved because of semantic scheduling or vendor stage legality.
- Fiber/tile op-chain semantics remain flat; the CSV block is a backend
  projection, not a reason to expand GEMM internals inside fiber.

## Graph Rule: `generateGraph(...)` Instantiates Blocks Into Nodes

`Graph_Extend::initNode(...)` clones one `Inst_Block` from
`inst_block_collect.inst_blocks[blk_type]`, attaches it to a `GRAPH_NODE`, marks
the node valid, and records the node type.

`GRAPH_NODE::m_pos_idx_df` defaults to `0xFFFFFFFF`.  If `generateGraph(...)`
sets it, `INST_BLK_MAP::map(...)` uses it as the PE index override.

Source anchors:

```text
common_oper/graph_extend.cpp:34
common_oper/graph_gen.h:53
common_oper/graph_gen.h:77
common_oper/inst_blk_map.cpp:3465
common_oper/inst_blk_map.cpp:3466
```

Assembler input implication:

- B-line needs a `SubtaskGraphPlan`, not just per-PE CSV rows.
- For simple cases, the first generated `generateGraph(...)` can be one node per
  active PE/template block with explicit `m_pos_idx_df`.
- For routed cases, `SubtaskGraphPlan` must name graph edges and their COPY
  ownership, not just node coordinates.

## COPY Edge Rule: Relationship Type Selects Parent Flow COPY Rows

`Graph_Extend::set_relationship_node(parent, child, type)` creates a parent-child
edge and scans the parent's flow-stage instructions.  A flow instruction is
attached to the edge when:

```text
inst.dst_pes_pos[0].x == type
and opcode is not LCOPY/LCOPYT
```

Those selected pointers are later patched by `INST_BLK_MAP::fill_copy_inst(...)`
using the child endpoint.

Source anchors:

```text
common_oper/graph_extend.cpp:7
common_oper/graph_extend.cpp:18
common_oper/graph_extend.cpp:21
common_oper/graph_extend.cpp:24
common_oper/inst_blk_map.cpp:3166
common_oper/inst_blk_map.cpp:3192
```

Assembler input implication:

- A graph edge's `type` must match the parent CSV COPY row's `dst_pe_idx` after
  CSV pseudo destination normalization.
- Route/COPY ownership is split: the parent executes the COPY row, but the child
  owns the destination block/PE/operand binding.
- B-line route actions should therefore carry both sender executor and receiver
  logical owner.

## Mapping Rule: Node Placement Creates PE Coordinates And Local Block Space

`setNodes(...)` maps a linear PE index to coordinates:

```text
x = pe_idx / PE_ARRAY_Y_LEN
y = pe_idx % PE_ARRAY_Y_LEN
```

It assigns:

```text
node.m_start_reg_idx = current PE register counter
node.m_pos.block_idx = current PE graph-node count
node.m_pos.pe_idx/x/y/z/graph_idx
node.m_node_name = n{x}_{y}_{block_idx}_{graph_idx}
```

Then it pushes the node into `PE::m_pGraph_nodes` and increments the PE register
counter by the count of normal CSV-local operand tags.

Source anchors:

```text
common_oper/inst_map_common.cpp:139
common_oper/inst_map_common.cpp:147
common_oper/inst_map_common.cpp:150
common_oper/inst_map_common.cpp:152
common_oper/inst_map_common.cpp:165
```

Assembler input implication:

- B-line should preserve stable logical tile/fiber identity, but final PE-local
  block indexes are mapper-owned.
- A reviewable `SubtaskGraphPlan` should include requested PE index and expected
  `(x, y)` for simple fixed-placement cases.

## Operand Resource Rule: Final Operand IDs Are Mapper-Owned

`INST_BLK_MAP::distribute_operand(...)` walks new PE graph nodes for the current
task and calls `Task_Resource::fill_reg_idx(...)` over stages in this order:

```text
LD
CAL
FLOW
ST
```

The mapper also respects `extra_fields[2]` as a RAM-group restriction by
reducing the candidate operand RAM set to `extra_fields[2] - 1`.

Source anchors:

```text
common_oper/inst_blk_map.cpp:3022
common_oper/inst_blk_map.cpp:3078
common_oper/inst_blk_map.cpp:3079
common_oper/inst_blk_map.cpp:3080
common_oper/inst_blk_map.cpp:3081
common_oper/inst_blk_map.cpp:568
common_oper/inst_blk_map.cpp:608
```

Assembler input implication:

- `TemplateCsvProgram` should pass symbolic operands and any intended RAM-group
  constraint separately.
- B-line should not claim final operand IDs until after common_oper replay or a
  source-equivalent mapper pass validates them.

## COPY Patch Rule: Receiver Endpoint Owns The Destination

`INST_BLK_MAP::fill_copy_inst(parent)` patches each selected parent COPY row
from the child node:

```text
dst_blocks_idx[0]    = child.m_pos.block_idx
dst_pes_pos[0].x/y   = child.m_pos.x/y
dst_operands_idx[0]  = child PE Task_Resource::retrieve_reg_idx(copy dst tag)
```

For `COPYT`, it converts the opcode to `COPY` and patches following expanded
rows with:

```text
dst_operand + i_following_inst * OPERANDS_PER_OPERAND_RAM
```

`alter_local_copy_inst(...)` similarly converts `LCOPY`/`LCOPYT` to `COPY`, but
the destination is the same node/block/PE.

Source anchors:

```text
common_oper/inst_blk_map.cpp:3166
common_oper/inst_blk_map.cpp:3192
common_oper/inst_blk_map.cpp:3193
common_oper/inst_blk_map.cpp:3194
common_oper/inst_blk_map.cpp:3195
common_oper/inst_blk_map.cpp:3197
common_oper/inst_blk_map.cpp:3201
common_oper/inst_blk_map.cpp:3124
common_oper/inst_blk_map.cpp:3137
```

Assembler input implication:

- Route rows are not complete at CSV emit time.
- The destination operand tag on a COPY row must be resolvable in the receiver's
  task resource map.
- B-line should model local moves and inter-node routes as separate action kinds
  until this binding step.

## Task Resource Rule: Mapping Completes Before exeBlock Generation

`end_map_task()` completes task mapping in this order:

```text
distribute_task_resource()
rectify_copy_inst()
counting_task_resource()
get_app_max_resource()
```

`start_map_app()` / `start_map_task()` snapshot resource starts.  `end_map_app()`
updates PE slot counters and checks app-level limits.

Source anchors:

```text
common_oper/inst_blk_map.cpp:3279
common_oper/inst_blk_map.cpp:3331
common_oper/inst_blk_map.cpp:3339
common_oper/inst_blk_map.cpp:3342
common_oper/inst_blk_map.cpp:3353
common_oper/inst_blk_map.cpp:3425
```

Assembler input implication:

- B-line should treat task/app resource offsets as derived mapper output.
- Bundle manifests can predict counts, but final resource starts belong after
  common_oper mapping.

## exeBlock Rule: Graph Edges Become Runtime Block Dependencies

`exe_block_gen(...)` assigns PE-local exeBlock indexes, writes predecessor and
successor arrays from graph relationships, increments child
`req_activations`, then computes stage start PCs and stage instruction amounts.

Source anchors:

```text
common_oper/exe_block_gen.cpp:17
common_oper/exe_block_gen.cpp:46
common_oper/exe_block_gen.cpp:52
common_oper/exe_block_gen.cpp:58
common_oper/exe_block_gen.cpp:68
common_oper/exe_block_gen.cpp:74
common_oper/exe_block_gen.cpp:79
common_oper/exe_block_gen.cpp:165
common_oper/exe_block_gen.cpp:184
common_oper/exe_block_gen.cpp:198
```

Assembler input implication:

- `SubtaskGraphPlan` is runtime-visible: graph edges affect activation counts,
  predecessor/successor metadata, and block start PCs.
- Stage counts are derived after CSV parsing, pseudo expansion, and stage
  splitting.  They should not be hand-authored in B-line.

## Print Rule: Binary Components Are A Late Product

`task_print.cpp` serializes tasks, subtasks, instance config, exeBlock config,
PE instruction streams, enable files, and MICC RTL output.  It also rebases
stage PCs as it prints task/subtask blocks.

Source anchors:

```text
common_oper/task_print.cpp:331
common_oper/task_print.cpp:371
common_oper/task_print.cpp:374
common_oper/task_print.cpp:387
common_oper/task_print.cpp:411
common_oper/task_print.cpp:490
common_oper/task_print.cpp:611
common_oper/task_print.cpp:659
common_oper/task_print.cpp:714
common_oper/task_print.cpp:778
common_oper/task_print.cpp:801
common_oper/task_print.cpp:434
```

Assembler input implication:

- Final `cbuf_file.bin` / `micc_file.bin` similarity is an output validation,
  not the first implementation target.
- B-line should diff these products against vendor output only after the
  assembler-input bundle has been archived and replayed.

## Capacity Rule: The Bundle Must Validate DFU3500 Limits Early

Common headers define the hard shape of the current target:

```text
PE mesh:                         4 x 4
PE_AMOUNT:                       16
MAX_INST_BLOCK_AMOUNT_PER_PE:    32
MAX_INST_AMOUT_PER_PE:           4352
MAX_OPERAND_RAM_AMOUNT_PER_PE:   1536
MAX_BASE_ADDR_PER_SUBTASK:       4
MAX_CUR_TASK_CONF_PER_APP:       4
MAX_SUBTASK_PER_TASK:            8
```

Source anchors:

```text
common/src/pe_com_def.h:12
common/src/pe_com_def.h:15
common/src/pe_com_def.h:16
common/src/pe_com_def.h:17
common/src/pe_com_def.h:20
common/src/pe_com_def.h:41
common/src/pe_com_def.h:49
common/src/pe_com_def.h:52
common/src/pe_com_def.h:64
common/src/pe_com_def.h:67
common/src/pe_com_def.h:132
common/src/pe_com_def.h:136
common/src/pe_com_def.h:227
common/src/pe_com_def.h:240
```

Assembler input implication:

- `VendorAssemblerInputBundle` should validate these limits before invoking the
  vendor assembler.
- For current project scope, hard-code DFU3500 target facts in the DFU3500
  backend profile rather than scattering them through frontend env/op code.

## B-line Export Mapping

Current B-line already has enough planning material to derive a report-only
assembler-input bundle:

```text
StreamPlan / Fiber provenance
  -> stable tile/fiber identities and logical route ownership

ValidatedFiberExecutionSchedule
  -> deterministic ordering and dependency evidence

TemplateOpPlan
  -> backend template intent, roles, phases, and row provenance

DFU3500 target profile
  -> PE mesh, operand capacity, task/subtask limits, base-address contract
```

The missing projection should be:

```text
TemplateOpPlan
  + schedule/provenance
  + target profile
  -> VendorAssemblerInputBundle
       CaseConfigPlan
       TemplateCsvProgram
       SubtaskGraphPlan
       GraphPluginBuildPlan
       RuntimeControlPlan?
```

First practical subset:

```text
1. Emit app0.conf from CaseConfigPlan.
2. Emit one staged CSV template per active PE/subtask bucket.
3. Generate simple generateGraph(...) with explicit m_pos_idx_df.
4. Archive manifest/provenance before assembler invocation.
5. Run build_app/common_oper as the assembler authority.
6. Compare produced simulator/RTL/CBUF/MICC files with existing debug decoders.
```

## Invariants For Implementation

- `ChipEnv` and op construction must not write CSV, graph plugins, task rows, or
  vendor binaries.
- Fiber/tile semantics remain first-class atomic op chains; backend CSV shape
  must not reintroduce GEMM internal K-loop expansion in fiber.
- CSV operands remain symbolic until mapper/resource binding.
- COPY destination binding is receiver-owned.
- Graph edges are source-visible and must carry provenance to route actions.
- Final binary writers are validators unless explicitly promoted behind source
  and runtime gates.

## Open Questions

- Which generated CSV vocabulary is the minimal runtime-valid subset for
  `gemm_no_relu` without copying old A-line final-byte assumptions?
- Do we have a clean, compilable `inst_blk_map.cpp` from the exact customer
  package that should become the local replay oracle?
- Should phase 1 generate `libsubtask.so` source only, or also invoke the vendor
  compiler to build it locally/remote?
- How much runtime case material belongs in the first bundle:
  `assembler_minimal` only, or full SimICT with `spm_data` and `riscv/testarm.c`?

## Recommended Direction

Use this rule set as the source-backed contract for the B-line
`VendorAssemblerInputBundle` RFC.  The next implementation phase should be a
report-only bundle emitter for one known profile, followed by an assembler
wrapper that treats `build_app/common_oper` as the binary authority and keeps
Python byte writers in the validation lane.
