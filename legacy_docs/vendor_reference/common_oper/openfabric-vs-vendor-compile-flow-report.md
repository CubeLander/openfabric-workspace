# OpenFabric vs Vendor GEMM Compile Flow Report

Date: 2026-06-16

Status: investigation report / current understanding

Scope: `gemm_template_fusion` / DFU3500 / SimICT binary generation.

This note explains why OpenFabric now emits binaries that are **structurally
very close** to the vendor workflow, but not always byte-identical.  The short
answer is:

```text
Vendor workflow:
  source case + CSV templates
    -> common_oper C++ graph/resource mapper
    -> task_print binary writer
    -> result/cbuf_file.bin + result/micc_file.bin

OpenFabric workflow:
  ChipEnv / compiler IR
    -> tile/action/loop/micro-block lowering
    -> DFU3500 template binding
    -> Python VendorABI / serializer
    -> result/config cbuf_file.bin + micc_file.bin
```

OpenFabric is no longer inventing the outer ABI shape.  It now reproduces the
vendor component layout, task/subtask row model, legacy GEMM instruction
envelope, and most field-level behavior.  Remaining differences come from the
fact that vendor `common_oper` is not just a byte packer: it also contains a
late graph/resource allocation algorithm that mutates `inst_t` operands after
CSV parsing.

## 1. Current parity level

The latest confirmed alignment is:

```text
cbuf_file.bin size = 23,531,520 bytes
micc_file.bin size =  8,522,976 bytes
```

CBUF is split as:

```text
insts_file.bin
  69,632 rows * 304 bytes = 21,168,128 bytes

exeblock_conf_info_file.bin
  512 rows * 520 bytes = 266,240 bytes

instance_conf_info_file.bin
  65,536 rows * 32 bytes = 2,097,152 bytes
```

MICC is split as:

```text
tasks_conf_info_file.bin
  4 rows * 120 bytes = 480 bytes

subtasks_conf_info_file.bin
  32 rows * 266,328 bytes = 8,522,496 bytes
```

The important interpretation is:

- top-level file sizes match;
- component offsets match;
- `instance_conf_info_file.bin` was already matched during previous probes;
- latest `micc_file.bin` comparisons reached exact match in the remote pre-runtime
  comparison flow;
- remaining mismatch concentrates in CBUF `insts` fields, especially operand
  indices inside `inst_t`.

That is why current failures/diffs are no longer “layout is wrong” failures.
They are “late instruction/resource field differs” failures.

## 2. Vendor compile flow

For `run_app_riscv.sh gemm_template_fusion 4`, the remote workflow is roughly:

```text
test/run_app_riscv.sh
  -> testcase/application/gemm_template_fusion/run.sh
  -> csv_generate / app*.conf
  -> testcase/application/build_app/run_mtr.sh
  -> build_app/main.cpp
  -> common_oper:
       csv_oper.cpp
       graph_extend.cpp
       task_create.cpp
       inst_blk_map.cpp
       exe_block_gen.cpp
       task_print.cpp
  -> testcase/application/gemm_template_fusion/result/cbuf_file.bin
  -> testcase/application/gemm_template_fusion/result/micc_file.bin
  -> gpdpu/users/risc_nn_riscv/config/*
  -> core/bin/runtime ...
```

The critical vendor stages are:

### 2.1 CSV and template stage

`csv_oper.cpp` parses CSV rows and preserves symbolic operand tags:

```text
src_reg_idx0_tag
src_reg_idx1_tag
dst_reg_idx_tag
```

This stage gives instructions a shape, but the operand indices in the CSV-derived
rows are not final hardware operands.

### 2.2 Graph and route relation stage

`graph_extend.cpp` attaches copy instructions to parent-child graph edges.

This matters because route/COPY instructions are not purely sender-local.  Their
destination PE/block and destination operand are finalized according to the
consumer/child node.

### 2.3 TaskResource / inst_blk_map stage

`inst_blk_map.cpp` is the most important source of remaining byte differences.
It walks graph nodes and mutates final `inst_t` operand fields.

Key behavior:

```text
for each task:
  one Task_Resource per PE
  scan graph nodes for that PE
  for each node:
    process LD -> CAL -> FLOW -> ST
    first-use symbolic tag gets a physical operand index
  after normal allocation:
    patch COPY/COPYT destination through child Task_Resource
```

This means the vendor binary is not just:

```text
CSV template -> fixed inst bytes
```

It is:

```text
CSV template
  -> graph node order
  -> task/PE-local resource state
  -> edge-owned copy destination patching
  -> final inst bytes
```

### 2.4 task_print binary writer

`task_print.cpp` writes the final rows in fixed PE-major order:

```text
insts:
  for pe in 0..15:
    emit MAX_INST_AMOUNT_PER_PE inst rows

exeblock:
  for pe in 0..15:
    emit MAX_INST_BLOCK_AMOUNT_PER_PE block rows
```

OpenFabric already follows this outer layout.

## 3. OpenFabric compile flow

OpenFabric deliberately does not execute vendor C++ `common_oper`.  It generates
the same kind of result through a cleaner compiler pipeline:

```text
ChipEnv / ChipProgram
  -> ProcessorLogicalProgram
  -> ProcessorTileProgram
  -> TileLoopRegion + TileMicroBlock
  -> ProgramNode
  -> ProgramPacking
  -> ProgramAsm / template-bound instructions
  -> folded ProgramVendorABI
  -> ProgramBinRows / ProgramBinComponents
  -> cbuf_file.bin + micc_file.bin
```

The current Python path has several vendor-compatibility layers:

- `legacy_templates.py` chooses DFU3500 legacy GEMM template fragments for tile
  micro-blocks.
- `program_legacy_inst.py` encodes legacy-compatible `inst_t` rows and maintains
  seed tables for GEMM operand tags.
- `program_bin.py` lays out CBUF/MICC rows and performs final serializer-side
  patching that has not yet moved fully into a resource replay pass.
- `core/dfu3500/task_resource_replay.py` now contains an opt-in model of vendor
  `Task_Resource`.

The important architectural boundary is:

```text
program_bin.py should serialize already-decided rows.
It should not become a second hidden compiler backend.
```

This boundary is why recent work moved template selection and resource behavior
upstream of byte packing.

## 4. Where the flows are already aligned

### 4.1 Runtime comparison target

The correct remote comparison target is:

```text
testcase/application/gemm_template_fusion/result/*.bin
gpdpu/users/risc_nn_riscv/config/*.bin
```

Remote probes showed:

```text
result/cbuf_file.bin == runtime config/cbuf_file.bin
result/micc_file.bin == runtime config/micc_file.bin
```

So runtime is not secretly rewriting these files after build.  If OpenFabric
differs from the remote result/config files, the difference is in generation,
not runtime mutation.

### 4.2 Top-level binary layout

OpenFabric now emits full-size CBUF/MICC files with the same component structure
as vendor output.

Earlier observations of a 2MB CBUF or empty MICC were stale/partial build states
or wrong comparison paths, not the final successful runtime input state.

### 4.3 Task/subtask/instance table semantics

The current model distinguishes the important vendor index spaces:

```text
task row index           = 0..3
local subtask index      = 0..7 within task
global subtask row index = task_index * 8 + local_subtask_index

physical instance row =
    task_index * 8 * 2048
  + local_subtask_index * 2048
  + instance_index
```

But `instances_conf_mem_based_addr` remains compact in active execution order.
This split was necessary to align MICC and instance configuration behavior.

### 4.4 Legacy GEMM instruction envelope

OpenFabric has moved from symbolic “one tile action = one fake instruction”
toward legacy GEMM-compatible instruction templates:

```text
LDN / HLDT-like materialization
COPY / COPYT flow
IMM / HMUL / RXINT / HMMAL / TRCTT compute envelope
HSTT / store
```

This is why opcode counts and stage counts became close to, and in several local
checks aligned with, vendor output.

## 5. Where the flows still differ

### 5.1 Vendor graph traversal order vs OpenFabric IR order

Vendor `Task_Resource` allocation is order-sensitive.  A tag gets its operand
the first time it is encountered while walking graph nodes.

Vendor order is roughly:

```text
task
  -> PE-local graph node order
  -> stage order LD, CAL, FLOW, ST
  -> instruction order inside stage
```

OpenFabric order is compiler-derived:

```text
task
  -> processor
  -> subtask / TileLoopRegion / micro-block
  -> template-bound instruction sequence
```

These orders are intentionally similar but not automatically identical.  If two
tags are first seen in different order, the final operand indices can differ by
`±1`.  This explains structured diffs such as:

```text
local=N, vendor=N+1
```

with a 304-byte stride across `inst_t` records.

### 5.2 Seed-table approximation vs true TaskResource replay

Before the full source-derived model was added, OpenFabric used seed tables to
approximate vendor operand allocation.  That can match many regular patterns,
but it is not the same algorithm.

Seed tables answer:

```text
what operand should this known GEMM tag probably get?
```

Vendor TaskResource answers:

```text
given actual graph traversal and prior first-use tags, what operand does this
tag get now?
```

This is the most important conceptual difference.  It produces “mostly close”
binaries because GEMM is regular, but it can still leave structured operand
diffs.

### 5.3 COPY/COPYT destination ownership

Vendor route patching is edge/consumer-owned:

```text
parent COPY instruction
  destination PE/block = child node
  destination operand  = child Task_Resource.retrieve(dst_tag)
```

OpenFabric originally had sender-side route actions and then patched COPY fields
later.  This is close for PE/block fields, but operand fields require the child
resource map.  Without this, a route-forward instruction can be byte-correct in
opcode/stage but wrong in `dst_operands_idx[0]`.

This explains large-group diffs such as:

```text
delta = 512
```

because operand indices move between tensor/operand groups.

### 5.4 Local vendor source may not equal arch-13 vendor source

Local `simict3500final/testcase/common_oper` is valuable algorithm evidence, but
it may not be byte-identical to the arch-13 build environment.

Observed fingerprint mismatches included `libapp_build_common.so` and
`inst_blk_map.cpp` between local and OCR-captured arch-13 states.  Therefore:

- local source should guide algorithms;
- arch-13 diff should remain the final arbiter for compatibility;
- do not blindly optimize for local vendor build-out if it contradicts remote
  result/config output.

### 5.5 Hand-authored constants and inactive fields

Some vendor fields are ABI flags, padding, inactive row defaults, or historical
hand-filled values.  OpenFabric should reproduce them when they affect SimICT
or binary compatibility, but should not let them pollute higher compiler IR.

Examples:

- zero-filled or sentinel-filled inactive slots;
- fixed-size CBUF/MICC padding;
- stage count fields that arch-13 may zero even if local source writes counts;
- task/subtask fixed window rows.

These are serializer/profile facts, not tensor-program semantics.

## 6. Why the binary result is “大同小异”

The binaries are similar because OpenFabric has already matched the major
structural facts:

```text
same operator shape
same app/task count
same CBUF/MICC component sizes
same task/subtask/instance row capacity
same folded K-loop vendor repeat shape
same legacy GEMM instruction envelope
same PE-major row layout
same runtime config target
```

They are not always identical because OpenFabric is reconstructing the vendor
assembler in Python rather than executing the vendor C++ mapper:

```text
OpenFabric knows what the program means.
Vendor common_oper additionally decides exact physical operand/resource IDs
by walking its graph in a historically specific order.
```

So the current differences are usually not semantic operator differences.  They
are late-binding ABI/resource differences:

```text
which operand slot did this symbolic tag land in?
which child resource map patched this COPY destination?
which inactive field did the legacy writer zero or fill?
```

That is why diffs are often regular:

- stride `304` bytes means repeated `inst_t` field differences;
- `N -> N+1` means first-use counter/order drift;
- `+512` means operand group drift;
- MICC match with CBUF diff means control table is solved but instruction fields
  still differ.

## 7. Current OpenFabric mitigation strategy

The project should keep two layers distinct:

### 7.1 Default stable path

Keep the seed-table / template-bound path stable as the default until remote
validation proves a better replay candidate.

This path is already useful because:

- it produces correct shapes and sizes;
- it keeps MICC stable;
- it makes regressions easy to detect;
- tests lock known values and file hashes.

### 7.2 Opt-in TaskResource replay path

`core/dfu3500/task_resource_replay.py` contains an opt-in source-derived replay candidate:

```bash
OPENFABRIC_ENABLE_DFU3500_TASK_RESOURCE_REPLAY=1
```

It models:

- `layout_operand_idx`;
- regular ORDER pool allocation;
- tensor pseudo-operand high-to-low group allocation;
- stage-local free-RAM behavior;
- strict receiver-side COPY lookup.

This path should become the long-term fix only after arch-13 diff proves it
reduces remaining CBUF mismatches.  It should not be enabled by default merely
because it looks more source-faithful locally.

## 8. Recommended next investigation steps

### P0: Compare field summaries, not raw OCR byte walls

Use the old-Python-compatible diff script to extract `inst_t` field summaries:

```text
field=src0
field=src1
field=dst0
field=dst_pe0_x / dst_pe0_y
field=dst_block0
field=src_fetch*
field=dst_fetch*
```

Raw byte lists are useful only after field grouping fails.

### P0: Validate TaskResource replay against arch-13

Upload a package with replay enabled and compare:

```text
default seed-table diff count
vs
OPENFABRIC_ENABLE_DFU3500_TASK_RESOURCE_REPLAY=1 diff count
```

If replay worsens the diff, keep it off and investigate traversal order before
changing allocation rules.

### P1: Audit node traversal order

The central question is:

```text
Does OpenFabric visit template-bound instructions in the same order that vendor
Task_Resource sees graph nodes?
```

If not, a faithful allocator will still produce different operands.

### P1: Keep version fingerprints in reports

Every arch-13 comparison should include:

```text
run_app_riscv.sh sha
run_mtr.sh sha
libapp_build_common.so sha
inst_blk_map.cpp sha
task_create.cpp sha
task_print.cpp sha
case app*.conf sha
```

This prevents us from fitting against a stale or different vendor implementation.

## 9. Practical rule for future agents

Do not patch byte offsets directly unless the field is confirmed to be a static
ABI flag or padding constant.

For real instruction/resource fields, patch the algorithm:

```text
bad:
  if record_idx == 10454: dst0 += 1

good:
  align vendor graph traversal order
  replay TaskResource first-use allocation
  patch COPY destination from child resource map
  then serialize rows
```

The goal is not perfect byte mimicry by superstition.  The goal is to recover
the vendor backend semantics well enough that byte parity falls out naturally.

## 10. Related documents

- [dfu3500-gemm-binary-replay.md](dfu3500-gemm-binary-replay.md)
- [csv-to-binary-pipeline.md](csv-to-binary-pipeline.md)
- [task-creation-generategraph-chain.md](task-creation-generategraph-chain.md)
- [subtask-graph-compile-chain.md](subtask-graph-compile-chain.md)
- [binary-artifact-generation-pipeline.md](binary-artifact-generation-pipeline.md)
- [runtime_evidence/simict-runtime.md](../runtime_evidence/simict-runtime.md)
