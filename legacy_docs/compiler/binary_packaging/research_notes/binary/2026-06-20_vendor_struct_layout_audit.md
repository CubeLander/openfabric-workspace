# Vendor Struct Layout Audit

Date: 2026-06-20

Status: binary note, clean-header audit for simulator component row layouts

This note records authoritative local `common/src` header evidence for core
simulator structs and component-size formulas.  It fixes one of the biggest
research gaps from A-line: we should not infer row size and field stride from
remote byte diffs when local headers already define them.

## Source Fingerprints

Clean source headers:

```text
b263f25e62403d4f1e365aafcec046e76c0c0030f1b6590ac4fb0d90aaa04a4a  common/src/inst_def.h
2d06ba8afb6f84cc50d120f3a9c6e3612d0b3fe2f48f42349ff27b211099bcae  common/src/pe_com_def.h
42bd0593d6dfc4b7e361c49d8191049addb2f851162bccec66575b36fe31fa8b  common/src/dma_com_def.h
a336aca7dec1f40a666f1ef45affb5048e3dcf3e79bb155663faef8c8f1218b7  common/src/basic_def.h
```

Important: these clean headers exist alongside OCR headers under `common/src_ocr`.
For binary interface work, prefer `common/src` unless a remote arch-13 mismatch is
proven.

## 1. Key Capacity Constants

Source evidence:

```text
common/src/pe_com_def.h:9-98
common/src/basic_def.h:77-82
```

Current local constants:

```text
PE_ARRAY_X_LEN = 4
PE_ARRAY_Y_LEN = 4
PE_AMOUNT      = 16

MAX_INST_AMOUT_PER_PE        = 4352
MAX_INST_BLOCK_AMOUNT_PER_PE = 32
MAX_EXE_BLOCK                = PE_AMOUNT * MAX_INST_BLOCK_AMOUNT_PER_PE = 512

MAX_APP_AMOUNT             = 1
MAX_CUR_TASK_CONF_PER_APP  = 4
MAX_SUBTASK_PER_TASK       = 8
MAX_TASK_AMOUNT            = 4
MAX_SUBTASK_AMOUNT         = 32
MAX_INSTANCES_PER_SUBTASK  = 2048
MAX_INSTANCE_AMOUNT        = 4 * 8 * 2048 = 65536
MAX_BASE_ADDR_PER_SUBTASK  = 4
```

`position_t` is three `uint64_t` fields:

```text
sizeof(position_t) = 24
```

### B-line implication

These constants belong in the DFU3500 profile layer, not scattered through op
lowering or validation scripts.

Required owner candidate:

```text
Dfu3500RuntimeProfile / VendorComponentProfile:
  pe_shape
  task/subtask/instance capacities
  per-PE inst/block capacities
  struct row sizes
```

## 2. `inst_t` Layout

Source evidence:

```text
common/src/inst_def.h:220-238
```

Local compiled layout:

```text
sizeof(inst_t) = 304
```

Field offsets:

```text
opCode                offset=0    size=4
unit_inst_type        offset=8    size=8
latency               offset=16   size=8
imms                  offset=24   size=24
src_operands_idx      offset=48   size=24
dst_operands_idx      offset=72   size=24
dst_pes_pos           offset=96   size=72
dst_blocks_idx        offset=168  size=24
forwarding_bits       offset=192  size=24
bypass_bits           offset=216  size=24
iter_exe_cond         offset=240  size=8
src_operands_fetched  offset=248  size=3
dst_operands_fetched  offset=251  size=3
block_idx             offset=256  size=8
flow_ack              offset=264  size=8
end_inst              offset=272  size=8
extra_fields          offset=280  size=24
```

### Why this matters

A-line repeatedly saw structured CBUF diffs with stride:

```text
0x130 = 304 bytes
```

That was not magic.  It is exactly `sizeof(inst_t)`.  Any repeated diff at this
stride is almost certainly the same field across consecutive instruction rows.

### B-line implication

Before touching instruction-row bytes, B-line should decode them by this struct
layout and report field names, not raw offsets only.

Required owner candidate:

```text
InstructionRowLayout:
  inst_t field map
  offset-to-field decoder
  row-stride guard = 304
```

## 3. `instance_conf_info_t` Layout

Source evidence:

```text
common/src/pe_com_def.h:132-134
```

Local compiled layout:

```text
sizeof(instance_conf_info_t) = 32
base_addr offset=0 size=32
```

It contains:

```text
uint64_t base_addr[4]
```

### B-line implication

Instance rows are simple base address tables, but there are two different
addressing concepts:

```text
physical fixed CBUF instance row:
  task * 8 * 2048 + subtask * 2048 + instance

compact active subtask instance base address:
  writer-side running active instance offset
```

Do not merge these again.

## 4. `exeBlock_conf_t` And `exeBlock_conf_info_t` Layout

Source evidence:

```text
common/src/pe_com_def.h:136-154
common/src/pe_com_def.h:219-225
```

Local compiled layouts:

```text
sizeof(exeBlock_conf_t)      = 472
sizeof(exeBlock_conf_info_t) = 520
```

`exeBlock_conf_t` key offsets:

```text
req_activations       offset=0    size=8
has_stages            offset=8    size=5
stages_start_pc       offset=16   size=40
predecessors          offset=56   size=160
successors            offset=216  size=160
block_idx             offset=376  size=8
subtask_idx           offset=384  size=8
task_idx              offset=392  size=8
instances_amount      offset=400  size=8
child_amount          offset=408  size=8
block_class           offset=416  size=8
inst_mem_based_addr   offset=424  size=8
ld_stage_inst_amount  offset=432  size=8
cal_stage_inst_amount offset=440  size=8
flow_stage_inst_amount offset=448 size=8
st_stage_inst_amount  offset=456  size=8
is_leaf               offset=464  size=1
```

`exeBlock_conf_info_t` key offsets:

```text
valid          offset=0   size=1
block_idx      offset=8   size=8
pe_dst         offset=16  size=24
priority       offset=40  size=8
exeBlock_conf  offset=48  size=472
```

### B-line implication

The outer `exeBlock_conf_info_t.block_idx` and inner
`exeBlock_conf_t.block_idx` can both exist.  B-line should keep decoded reports
explicit about which one it is writing or comparing.

Required owner candidate:

```text
ExeBlockRowLayout:
  outer row validity / destination / priority
  inner graph-control metadata
```

## 5. MICC Task/Subtask Layout

Source evidence:

```text
common/src/pe_com_def.h:227-247
```

Local compiled layouts:

```text
sizeof(task_conf_info_t)     = 120
sizeof(sub_task_conf_info_t) = 266328
```

`task_conf_info_t` offsets:

```text
is_exe_start   offset=0  size=1
is_exe_end     offset=1  size=1
subtasks_amount offset=8 size=8
execute_times  offset=16 size=8
subtasks_idx   offset=24 size=64
suc_tasks      offset=88 size=32
```

`sub_task_conf_info_t` offsets:

```text
is_exe_start                   offset=0      size=1
is_exe_end                     offset=1      size=1
instances_amount               offset=8      size=8
instances_conf_mem_based_addr  offset=16     size=8
suc_subtasks                   offset=24     size=32
root_block_amount              offset=56     size=8
block_amount                   offset=64     size=8
exeBlocks_conf_info            offset=72     size=266240
subtask_idx                    offset=266312 size=8
task_idx                       offset=266320 size=8
```

Why `sub_task_conf_info_t` is huge:

```text
exeBlocks_conf_info = MAX_EXE_BLOCK * sizeof(exeBlock_conf_info_t)
                    = 512 * 520
                    = 266240 bytes
```

### B-line implication

MICC subtask rows embed a full fixed-capacity exeBlock table.  This is why the
MICC file is dominated by subtask rows and why active-vs-padded semantics are so
expensive to get wrong.

Required owner candidate:

```text
MiccRowLayout:
  task rows
  subtask rows with embedded fixed-capacity exeBlock rows
```

## 6. Component Address And Size Formulas

Source evidence:

```text
common/src/dma_com_def.h:114-145
```

Formula source:

```text
CBUF_INST_BASE = SPM_MAX + 1
CBUF_INST_MAX  = CBUF_INST_BASE + sizeof(inst_t) * MAX_INST_AMOUT_PER_PE * PE_AMOUNT - 1

CBUF_BLCK_BASE = CBUF_INST_MAX + 1
CBUF_BLCK_MAX  = CBUF_BLCK_BASE + sizeof(exeBlock_conf_info_t) * MAX_INST_BLOCK_AMOUNT_PER_PE * PE_AMOUNT - 1

CBUF_ISTC_BASE = CBUF_BLCK_MAX + 1
CBUF_ISTC_MAX  = CBUF_ISTC_BASE + sizeof(instance_conf_info_t) * MAX_INSTANCE_AMOUNT - 1

CBUF_ISTC_CONST_BASE = CBUF_ISTC_MAX + 1
CBUF_ISTC_CONST_MAX  = CBUF_ISTC_CONST_BASE + sizeof(instance_conf_info_t) * MAX_SUBTASK_PER_TASK * MAX_ISTC_CONST_PER_TASK - 1

MICC_BASE_ADDR = CBUF_ISTC_CONST_MAX + 1
MICC_MAX       = MICC_BASE_ADDR + sizeof(task_conf_info_t) * MAX_CUR_TASK_CONF_PER_APP - 1

MICC_SUB_BASE  = MICC_MAX + 1
MICC_SUB_MAX   = MICC_SUB_BASE + sizeof(sub_task_conf_info_t) * MAX_CUR_TASK_CONF_PER_APP * MAX_SUBTASK_PER_TASK - 1
```

Local evaluated sizes:

```text
CBUF inst section      = 21,168,128 bytes
CBUF exeBlock section  =    266,240 bytes
CBUF instance section  =  2,097,152 bytes
CBUF instance-const section = 1,280 bytes

MICC task section      =        480 bytes
MICC subtask section   =  8,522,496 bytes
MICC total             =  8,522,976 bytes
```

Observed A-line/vendor payload sizes:

```text
cbuf_file.bin = 23,531,520 bytes
micc_file.bin =  8,522,976 bytes
```

Explanation:

```text
23,531,520 = inst + exeBlock + instance
           = 21,168,128 + 266,240 + 2,097,152
```

The `CBUF_ISTC_CONST` section is defined by address macros but is not included in
the observed `cbuf_file.bin` size from A-line/vendor runtime config.

### B-line implication

Keep two concepts separate:

```text
address-space macro range:
  includes CBUF_ISTC_CONST before MICC_BASE_ADDR

actual emitted simulator cbuf_file.bin:
  observed as inst + exeBlock + instance only
```

Do not blindly use `CBUF_ISTC_CONST_MAX - CBUF_INST_BASE + 1` as emitted CBUF
file size without case/runtime evidence.

## 7. Header Include Order Is Part Of The Build Contract

`dma_com_def.h` uses `inst_t`, `exeBlock_conf_info_t`, `instance_conf_info_t`,
`task_conf_info_t`, and capacity macros, but does not define them itself.  A
layout probe must include `pe_com_def.h` before `dma_com_def.h`.

### B-line implication

Generated C/C++ validators and probes should include headers in vendor-compatible
order.  A failing include order does not necessarily mean the macro is missing;
it may mean the original build relies on transitive include sequencing.

## 8. Immediate Verifier / Tooling Candidates

```text
1. Add a Python or C++ layout probe that records sizeof/offsetof into a JSON artifact.
2. Assert inst_t row stride is 304 before decoding instruction diffs.
3. Assert expected cbuf_file.bin size is inst+exeBlock+instance unless const section is explicitly enabled.
4. Assert expected micc_file.bin size is task+subtask = 8,522,976 for current profile.
5. Decode binary diffs by field name using this layout instead of raw offsets only.
6. Keep clean-header fingerprints in every binary-layout audit.
```

## Remaining Research Gaps

```text
1. Confirm arch-13 clean header fingerprints and sizes.
2. Find the writer/reader path for the optional CBUF_ISTC_CONST section.
3. Confirm whether simulator ever expects `CBUF_ISTC_CONST` in cbuf_file.bin.
4. Build a reusable layout decoder for `inst_t`, `exeBlock_conf_info_t`, task rows, and subtask rows.
5. Cross-check local `common/src` against original documents in `tmp/华科算子库编写`.
```

## Parallel Audit Addendum: `CBUF_ISTC_CONST`

A follow-up source search found no local writer/reader that directly emits or
consumes `CBUF_ISTC_CONST` records.  The observed package scripts concatenate
only:

```text
insts_file.bin
exeblock_conf_info_file.bin
instance_conf_info_file.bin
```

into `cbuf_file.bin`.  Therefore current B-line should treat `CBUF_ISTC_CONST`
as part of the address-space macro model, not part of the emitted simulator
`cbuf_file.bin`, unless closed SimICT/runtime or arch-13 evidence proves
otherwise.
