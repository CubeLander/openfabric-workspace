# arch-13 huake02 GEMM Binary Diff Field Investigation

Date: 2026-06-15

Scope: local vendor/OpenFabric-compatible GEMM output versus arch-13
`huake02` vendor workflow output, captured before runtime.

Input OCR files:

```text
tmp/diffs/0~10.md
tmp/diffs/13~21.md
tmp/diffs/25.md
tmp/diffs/33~41.md
tmp/diffs/44~52.md
tmp/diffs/54~62.md
tmp/diffs/65~73.md
tmp/diffs/75~88.md
tmp/diffs/90~100.md
```

## 1. Correct Comparison Target Is Now Confirmed

The fixed-path probe compared the correct runtime objects:

```text
case result:
  /project/home-new/huake02/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/result/cbuf_file.bin
  /project/home-new/huake02/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/result/micc_file.bin

runtime config:
  /project/home-new/huake02/simict3500final/gpdpu/users/risc_nn_riscv/config/cbuf_file.bin
  /project/home-new/huake02/simict3500final/gpdpu/users/risc_nn_riscv/config/micc_file.bin
```

Key result:

```text
remote result/cbuf_file.bin == remote runtime config/cbuf_file.bin
remote result/micc_file.bin == remote runtime config/micc_file.bin
```

So runtime is consuming the case `result/` blobs copied into
`gpdpu/users/risc_nn_riscv/config/`. Previous `test/config` probes were looking
at the wrong directory.

## 2. Top-Level Diff Summary

```text
cbuf:
  local_size  = 23531520
  remote_size = 23531520
  diff bytes  = 283360

micc:
  local_size  = 8522976
  remote_size = 8522976
  diff bytes  = 527
```

The file layouts and sizes match. The mismatch is content-level, not file shape.

## 3. CBUF Layout

The diff script split `cbuf_file.bin` as:

```text
insts:
  offset      = 0
  size        = 21168128
  record_size = 304
  rows        = 69632
  diff bytes  = 282848

exeblock:
  offset      = 21168128
  size        = 266240
  record_size = 520
  rows        = 512
  diff bytes  = 512

instance:
  offset      = 21434368
  size        = 2097152
  record_size = 32
  rows        = 65536
  status      = MATCH
```

Important: `instance_conf_info_file.bin` is still solved and should not be
changed by the next fixes.

## 4. `inst_t` Diff: First Field Mismatch Is `dst_operands_idx[0]`

The first cbuf differences are:

```text
offset 72, 376, 680, 984, ...
```

These are separated by:

```text
304 bytes = sizeof(inst_t)
```

The `inst_t` structure is:

```text
opCode                 offset 0
unit_inst_type          offset 8
latency                 offset 16
imms[0..2]              offset 24,32,40
src_operands_idx[0..2]  offset 48,56,64
dst_operands_idx[0..2]  offset 72,80,88
```

Source evidence:

```text
simict3500final/gpdpu/users/risc_nn_riscv/common/src/inst_def.h
compiler/gpdpu_compiler/core/program_legacy_inst.py
```

Therefore the first recurring inst diff is:

```text
inst_t.dst_operands_idx[0]
```

### 4.1 Observed Pattern

Remote `dst_operands_idx[0]` begins with values consistent with:

```text
127, 255, 383, 511,
126, 254, 382, 510,
125, 253, ...
```

The local side begins with values consistent with a different operand layout
order:

```text
0, 0, 0, 0,
128, 128, ...
```

The opcode stream shape is aligned enough that record boundaries match, but
operand allocation differs immediately.

### 4.2 Probable Source

Vendor C++ derives operand indices through CSV tags and register allocation:

```text
Csv_Operate::process()
Task_Resource::fill_reg_idx()
fillRegIdx()
```

Current Python compatibility path derives these through:

```text
compiler/gpdpu_compiler/core/program_legacy_inst.py
  LegacyCsvEncoder._get_reg_idx()
  legacy_gemm_micro_block_template()
  _legacy_gemm_seed_before_input0()
  _legacy_gemm_seed_after_input0()
  _legacy_gemm_seed_after_input1()

compiler/gpdpu_compiler/core/dfu3500/legacy_templates.py
  legacy_gemm_template_for_micro_block_refs()
  _legacy_template_index_for_micro_block()
  _legacy_input0_preallocated_for_micro_block()
```

The local code also reads legacy templates from a local reconstructed
`build_out` path:

```text
compiler/gpdpu_compiler/core/program_legacy_inst.py
  _legacy_gemm_template_root()
```

This local source is not byte-identical to the arch-13 vendor packer.

### 4.3 Fingerprint Evidence

Remote `libapp_build_common.so` from OCR:

```text
e46d0f8870a0478133e02747de01297a30a1beb8b06fb413256d565af0d5938d
size=3970464
```

Local checked-in `libapp_build_common.so`:

```text
246236162a29eb3f45d2abcc324c326931e8944e0638b035dff42bb8aaaa611b
size=3886360
```

Conclusion:

```text
The local reconstructed vendor packer is not the arch-13 vendor packer.
Instruction operand-index parity must follow arch-13 behavior, not local
build_out parity.
```

## 5. CBUF `exeblock` Diff: Stage Instruction Count Fields

`exeblock_conf_info_file.bin` differs by only:

```text
512 bytes
```

First differences include:

```text
section offset 480: local 64, remote 0
section offset 488: local 18, remote 0
section offset 976: local 2,  remote 0
section offset 1000: local 64, remote 0
...
```

These offsets map into fields at the end of `exeBlock_conf_t`:

```text
ld_stage_inst_amount
cal_stage_inst_amount
flow_stage_inst_amount
st_stage_inst_amount
```

Current serializer writes these fields from `stage_instruction_counts`:

```text
compiler/gpdpu_compiler/core/program_serializer.py
  _pack_exeblock_conf_row()
```

Remote arch-13 output has these count fields zero for active rows while keeping
stage start PCs valid.

### 5.1 Important Contradiction With Local Source

The local C++ source in `exe_block_gen.cpp` writes these fields:

```text
pExeBlock_conf->ld_stage_inst_amount = ld_inst_amount;
pExeBlock_conf->cal_stage_inst_amount = cal_inst_amount;
pExeBlock_conf->flow_stage_inst_amount = flow_inst_amount;
pExeBlock_conf->st_stage_inst_amount = st_inst_amount;
```

But arch-13 binary output zeros them. This is consistent with the observed
`libapp_build_common.so` mismatch: the source file visible locally is not enough
to infer the exact remote binary behavior.

### 5.2 Candidate Fix

For `legacy_gemm_compat`, serialize exeblock stage instruction count fields as
zero while preserving:

```text
has_stages
stages_start_pc
predecessors
successors
block_idx/subtask_idx/task_idx/instances_amount
inst_mem_based_addr
```

Expected effect:

```text
exeblock diff bytes should drop by ~512
subtasks embedded-exeblock diff should also drop heavily
```

## 6. MICC `tasks` Diff: `subtasks_idx` Uses Local Subtask Indices

`tasks` section:

```text
size        = 480
record_size = 120
rows        = 4
diff bytes  = 9
```

Differences:

```text
task1: local 8,9,10   remote 0,1,2
task2: local 16,17,18 remote 0,1,2
task3: local 24,25,26 remote 0,1,2
```

Current OpenFabric/local behavior:

```text
task_conf_info.subtasks_idx = global physical subtask row index
task1 -> 8,9,10
task2 -> 16,17,18
task3 -> 24,25,26
```

Arch-13 behavior:

```text
task_conf_info.subtasks_idx = local subtask index
taskN -> 0,1,2
```

Current code source:

```text
compiler/gpdpu_compiler/core/program_bin.py
  _build_task_conf_rows()
  dfu3500_legacy_subtask_row_index()
```

The existing code uses `dfu3500_legacy_subtask_row_index()` when building task
row `subtasks_idx_slots`. That policy is wrong for arch-13 runtime.

### Candidate Fix

Keep physical `subtasks_conf_info_file.bin` row placement as:

```text
physical row = task_index * 8 + local_subtask_index
```

but serialize `task_conf_info.subtasks_idx[]` as:

```text
local_subtask_index
```

not the physical/global row.

Expected effect:

```text
tasks diff bytes should drop from 9 to 0
```

## 7. MICC `subtasks` Diff: Mostly Embedded ExeBlock Count Fields

`subtasks` section:

```text
size        = 8522496
record_size = 266328
rows        = 32
diff bytes  = 518
```

The first subtask differences are:

```text
global offset 1032 / section offset 552: local 64, remote 0
global offset 1040 / section offset 560: local 18, remote 0
...
```

These offsets are inside embedded `exeBlock_conf_info_t` rows within
`sub_task_conf_info_t`.

Therefore the subtasks diff is mostly the same as the standalone exeblock diff:

```text
embedded exeBlock stage instruction counts are nonzero locally and zero remotely
```

There are also subtask record diffs at rows:

```text
0,1,2,8,9,10,16,17,18,24,25,26
```

which correspond to the active task windows.

### Candidate Fix

After zeroing exeblock stage count fields in `_pack_exeblock_conf_row()`, ensure
`sub_task_conf_info_t` embeds those exact same packed exeblock bytes.

The current serializer already uses one source for standalone and embedded
exeblock rows:

```text
ProgramBinRows.exeBlock_conf_rows
  -> exeblock_conf_info_file.bin
  -> embedded exeBlock bytes inside sub_task_conf_info_t
```

So a single exeblock field fix should repair both cbuf/exeblock and
micc/subtasks.

## 8. Current Fix Priority

### P0: Fix task row `subtasks_idx`

Change:

```text
task_conf_info.subtasks_idx_slots = global physical subtask rows
```

to:

```text
task_conf_info.subtasks_idx_slots = local subtask indices
```

while preserving physical subtask table placement.

### P0: Zero exeblock stage instruction count fields in legacy compat

For `legacy_gemm_compat`:

```text
ld_stage_inst_amount   -> 0
cal_stage_inst_amount  -> 0
flow_stage_inst_amount -> 0
st_stage_inst_amount   -> 0
```

Do not zero `stages_start_pc`.

### P1: Investigate operand index allocation

`inst_t.dst_operands_idx[0]` differs from record 0. This is likely the
instruction-level root cause for runtime failures such as:

```text
Error: hmma memory out of range!
```

The arch-13 pattern suggests a reversed / banked operand layout not captured by
the local Python compatibility encoder.

Needed next evidence:

1. decode first 32 local and remote inst rows fully, not just diff bytes;
2. compare opcode, imms, src/dst operands, block_idx, iter/base fields;
3. infer arch-13 operand allocation formula;
4. patch `LegacyCsvEncoder` seed/layout or `legacy_gemm_micro_block_template`
   compatibility path accordingly.

## 9. Do Not Regress These Solved Pieces

Do not disturb:

```text
instance_conf_info_file.bin
cbuf/micc top-level section sizes
physical exeblock row count
physical subtask row count
runtime config copy path
```

Remote result and runtime config now match. The remaining problem is binary
field parity, not workflow pathing.

## 10. 2026-06-15 P0 Fixes Implemented From `0~10.md`

Implemented the two byte-field fixes that are directly supported by
`tmp/diffs/0~10.md` and vendor struct evidence:

```text
compiler/gpdpu_compiler/core/program_bin.py
  _build_task_conf_rows()

compiler/gpdpu_compiler/core/program_serializer.py
  _pack_exeblock_conf_row()
```

### 10.1 `task_conf_info_t.subtasks_idx[]` Uses Local Subtask Indices

The `micc_file.bin` task-row diff showed:

```text
task1: local 8,9,10   remote 0,1,2
task2: local 16,17,18 remote 0,1,2
task3: local 24,25,26 remote 0,1,2
```

Fix:

```text
task_conf_info.subtasks_idx[] = local subtask index
```

while preserving physical `subtasks_conf_info_file.bin` row placement:

```text
physical subtask row = task_index * 8 + local_subtask_index
```

Expected remote diff effect:

```text
tasks section diff should drop by 9 bytes
```

### 10.2 Legacy GEMM `exeBlock_conf_t` Stage Count Fields Are Zeroed

The `cbuf_file.bin` exeblock diff and `micc_file.bin` embedded-subtask diff both
point to:

```text
ld_stage_inst_amount
cal_stage_inst_amount
flow_stage_inst_amount
st_stage_inst_amount
```

Arch-13 output leaves these C-struct count fields as zero for legacy GEMM while
preserving:

```text
has_stages
stages_start_pc
inst_mem_based_addr
predecessor/successor slots
```

Fix:

```text
legacy_gemm_compat byte serializer writes stage count fields as 0
```

The real counts remain in OpenFabric IR/debug reports; only the vendor byte
projection applies this arch-13 compatibility quirk.

Expected remote diff effect:

```text
standalone exeblock diff should drop by ~512 bytes
subtasks embedded-exeblock diff should drop by most of its ~518 bytes
```

### 10.3 Validation Run

Targeted tests after the fixes:

```text
pytest -q tests/test_chip_program_frontend.py -k "program_bin or legacy_gemm or task_conf"
  4 passed, 5 deselected

pytest -q tests/test_tile_dependency_network.py -k "program_bin or vendor_abi or exeblock or instance_conf or task_conf"
  11 passed, 53 deselected
```

## 17. 2026-06-15 Tensor Tag Reuse and Cross-Template Seeding

After the first tensor allocator fix, the initial HLDT-expanded LDN destination
operands matched the arch-13 OCR pattern, but later template fragments could
still allocate or reference the same GEMM tensor tags through the regular
operand path.

This round extends `LegacyCsvEncoder` in:

```text
compiler/gpdpu_compiler/core/program_legacy_inst.py
```

### 17.1 What Changed

`LegacyCsvEncoder` now accepts:

```text
initial_tensor_tags_by_group
```

and keeps a first-class tensor tag table separate from the scalar/regular
operand table.

The encoder now:

```text
1. seeds known GEMM tensor tags into vendor tensor register groups,
2. resolves any already-known tensor tag before falling back to regular regs,
3. infers HSTT tensor group from tag names when CSV extra_fields[2] is absent,
4. carries output / input0 / input1 tensor tag seeds across filtered templates.
```

Relevant seed model:

```text
output0 -> tensor group 0
input0  -> tensor group 1
input1  -> tensor group 2
```

This means filtered `compute_update` and `tile_store` template slices no longer
forget tensor register assignments established by preceding legacy CSV rows.

### 17.2 Local Determinism After Reuse Fix

Two local runs still match byte-for-byte:

```text
OUT /tmp/openfabric_tensor_reuse_determinism
ALL_MATCH 1

config/cbuf_file.bin
  sha256 = daa951f3791d34e9fa27f94f814ef98675d444e1f496773bfd112ac076c7d59f

config/micc_file.bin
  sha256 = 99909698f348b083edf171e26a9fa31422afb29ff726d92738c14814ea3348b4

simulator_bin/insts_file.bin
  sha256 = 18af63ea06d50780f2a54d0df8a0c98705f1cde0655de8ac606e6e44105a3263

simulator_bin/exeblock_conf_info_file.bin
  sha256 = ddb1af41f8e685085ef4143c3f82f803c9e0c9b777d0f71ee1f33ebc68fefa42

simulator_bin/instance_conf_info_file.bin
  sha256 = 3b9d70247acc9832d71d73ec88f044d5b083aea7f07a42c191e90fb994b19414

simulator_bin/tasks_conf_info_file.bin
  sha256 = 2cb27a71c30553ee1c639225f235ca8a606a87a09d8b592ead0aea91985a5a0b

simulator_bin/subtasks_conf_info_file.bin
  sha256 = 29b12bafdcc4d0068fae0d258a50ab92027572905cb03f155cd4791b249f01c0
```

The control-table files remain stable relative to the previous tensor allocator
fix.  The intended change is isolated to `insts_file.bin` and therefore to
`config/cbuf_file.bin`.

### 17.3 Same-Style Old-to-Current Diff

New report:

```text
tmp/local_old_vs_current_binary_diff_20260615_tensor_reuse.txt
```

Compared against the preserved original local artifact:

```text
tmp/local_vendor_result_diff_bundle_20260615_202234/local_vendor_gemm
```

Key shape:

```text
simulator_bin/insts_file.bin
  old_sha = 2b15c1016136cc64aeb08fa5d406ce4ac7b1d8435220c2c0f18b0c621e3cab7e
  new_sha = 18af63ea06d50780f2a54d0df8a0c98705f1cde0655de8ac606e6e44105a3263
  diff_byte_count = 177376

simulator_bin/exeblock_conf_info_file.bin
  new_sha = ddb1af41f8e685085ef4143c3f82f803c9e0c9b777d0f71ee1f33ebc68fefa42

simulator_bin/instance_conf_info_file.bin
  MATCH

simulator_bin/tasks_conf_info_file.bin
  new_sha = 2cb27a71c30553ee1c639225f235ca8a606a87a09d8b592ead0aea91985a5a0b

simulator_bin/subtasks_conf_info_file.bin
  new_sha = 29b12bafdcc4d0068fae0d258a50ab92027572905cb03f155cd4791b249f01c0
```

The first HLDT rows now show the expected descending tensor destination pattern:

```text
127,255,383,511,
126,254,382,510,
125,253,381,509,
...
```

Later changed records show the reuse effect explicitly:

```text
HMUL:
  old src/dst followed regular operand allocation
  new src/dst reuse seeded tensor regs, e.g. 127,126,125...

COPY:
  old source/destination followed regular-like tensor indices
  new source/destination reuse tensor group 1 assignment, e.g. 639,767,895,1023...
```

### 17.4 Validation Run

```text
pytest -q tests/test_chip_program_frontend.py -k "legacy_csv_encoder"
  2 passed, 7 deselected

pytest -q tests/test_chip_program_frontend.py -k "legacy_gemm or program_bin or task_conf"
  4 passed, 5 deselected

pytest -q tests/test_tile_dependency_network.py -k "program_bin or vendor_abi or exeblock or instance_conf or task_conf"
  11 passed, 53 deselected
```

### 17.5 Next Investigation Target

This fix is still local old-to-current evidence, not direct arch-13 byte parity.
The next remote diff should reveal whether remaining `insts_file.bin` mismatch
is now dominated by:

```text
1. source operand field families after tensor reuse,
2. immediate / extra_fields differences,
3. forwarding / bypass bits,
4. instruction ordering or filtered-template selection differences.
```

If arch-13 still reports HMMA memory range issues, prioritize comparing the
`HMMAL` rows for PE(0,3) / nearby PC against the new tensor seeded image.

### 10.4 Remaining P1: Operand Index Allocation

The largest remaining diff in `0~10.md` is still instruction row field:

```text
inst_t.dst_operands_idx[0]
```

Remote arch-13 begins with a pattern like:

```text
127, 255, 383, 511, 126, 254, 382, 510, ...
```

Current local/OpenFabric begins with a different register-bank order.  This is
still the most likely explanation for runtime failures such as:

```text
Error: hmma memory out of range!
```

Next investigation should decode the first 32 local/remote `inst_t` records
fully and infer the arch-13 operand allocation formula before touching
`LegacyCsvEncoder`.

## 11. 2026-06-15 `13~21.md` Follow-up

`tmp/diffs/13~21.md` mostly continues the same field families from
`0~10.md`, but it exposes one additional serialized exeBlock field:

```text
child_amount
```

Representative mapping:

```text
267336 0x41448 local 2 remote 0
267856 0x41650 local 2 remote 0
268896 0x41a60 local 2 remote 0
269936 0x41e70 local 1 remote 0
```

These offsets map to:

```text
micc_file.bin
  sub_task_conf_info_t row 1
    embedded exeBlock slot N
      exeBlock_conf_t.child_amount
```

The same page also repeats:

```text
ld_stage_inst_amount
cal_stage_inst_amount
flow_stage_inst_amount
```

for embedded exeBlock slots.

### 11.1 Field Mapping

Using the vendor struct layout:

```text
sub_task_conf_info_t header size = 72
embedded exeBlock_conf_info_t size = 520
exeBlock_conf_info_t prefix size = 48

inside exeBlock_conf_t:
  child_amount              at exeBlock row offset 456
  ld_stage_inst_amount      at exeBlock row offset 480
  cal_stage_inst_amount     at exeBlock row offset 488
  flow_stage_inst_amount    at exeBlock row offset 496
  st_stage_inst_amount      at exeBlock row offset 504
```

### 11.2 Implemented Fix

`legacy_gemm_compat` now serializes:

```text
child_amount -> 0
```

while still preserving:

```text
successor records copied from legacy GEMM edge slots
OpenFabric IR/debug successor ids
OpenFabric IR/debug child_amount
```

This is intentionally a vendor byte-projection quirk, not a semantic graph
change.

Expected remote diff effect:

```text
subtasks diff should lose the remaining child_amount bytes exposed in 13~21
```

### 11.3 Validation Run

Targeted tests after the 13~21 fix:

```text
pytest -q tests/test_chip_program_frontend.py -k "program_bin or legacy_gemm or task_conf"
  4 passed, 5 deselected

pytest -q tests/test_tile_dependency_network.py -k "program_bin or vendor_abi or exeblock or instance_conf or task_conf"
  11 passed, 53 deselected
```

## 12. `25.md` Follow-up

`tmp/diffs/25.md` does not introduce a new field family.  It continues the same
embedded `exeBlock_conf_t` differences already mapped in `13~21.md`:

```text
ld_stage_inst_amount
cal_stage_inst_amount
flow_stage_inst_amount
child_amount
```

The important new confirmation in this page is comparison target validity:

```text
remote testcase result/cbuf_file.bin == remote runtime config/cbuf_file.bin
remote testcase result/micc_file.bin == remote runtime config/micc_file.bin
```

So the runtime consumes the exact `result/` blobs produced by the vendor
workflow.  Remaining byte mismatches are OpenFabric/vendor binary generation
issues, not config-copy or runtime staging issues.

## 13. `33~41.md` and `44~52.md`: Operand Allocator Evidence

`tmp/diffs/33~41.md` confirms that the `insts` section is structurally aligned:

```text
record_size = 304
record_count = 69632
first 32 record boundaries align
```

The first recurring differing field is still:

```text
inst_t.dst_operands_idx[0]
```

for the first 32 records, which decode locally as the first prologue `LDN`
rows expanded from `HLDT`:

```text
record 0..31:
  opCode = 0x40
  unit_inst_type = 0x8
  block_idx = 0
```

Current OpenFabric local pattern:

```text
dst0 = 0,0,0,0, 128,128,128,128, 256,256,256,256, ...
```

Arch-13 OCR pattern:

```text
dst0 = 127,255,383,511,
       126,254,382,510,
       125,253,381,509,
       ...
```

This is now explainable from vendor source:

```text
common_oper/inst_map_common.cpp
  PE::m_tensor_regs_available[group] is initialized ascending
  PE::pop_tensor_regs_available_general(group) returns regs->back()

common_oper/csv_oper.cpp
  HLDT/COPYT/HSTT pseudo instructions expand into
  OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE lanes
```

So arch-13 tensor destination allocation for this first `HLDT` group is:

```text
base = pop_tensor_regs_available_general(group0)
     = 127, then 126, then 125, ...

lane-expanded operand = base + lane * 128
```

That exactly produces:

```text
127,255,383,511
126,254,382,510
...
```

### 13.1 Root Cause

Current Python compatibility encoding assigns regular operands too early:

```text
LegacyCsvEncoder._get_reg_idx()
  _layout_operand_idx(raw_reg_idx)
```

That matches the visible local reconstructed `Task_Resource::get_reg_idx`
source, but not arch-13's effective tensor-register behavior for tensor pseudo
ops.  The arch-13 packer treats tensor values through PE tensor register pools,
not through the normal regular-register layout formula.

### 13.2 Required Fix Direction

Do not globally replace `_layout_operand_idx`.

Instead, split operand allocation into at least two paths:

```text
regular/scalar tags:
  current regular register allocation path

tensor tags used by HLDT/HSTT/COPYT/HMMAL/TRCTT:
  DFU3500 tensor register pool allocation
  group_base = group_index * 4 * 128
  tensor_base = group_base + (127 - allocation_index_in_group)
  expanded_lane_operand = tensor_base + lane * 128
```

The tensor group appears to be encoded by CSV `extra_fields[2]` for GEMM
templates:

```text
subtask1 output HLDT: extra_fields[2] = 1 -> group0
subtask2 input0 HLDT/COPYT: extra_fields[2] = 2 -> group1
subtask2 input1 HLDT: extra_fields[2] = 3 -> group2
```

This should be implemented in `LegacyCsvEncoder` or a DFU3500 GEMM-specific
template binding layer, not in `program_bin.py` byte packing.

### 13.3 `44~52.md`

`tmp/diffs/44~52.md` is the standalone `exeblock` section equivalent of the
embedded exeblock diffs already fixed in sections 10 and 11:

```text
record_size = 520
diff_byte_count = 512
```

The listed byte offsets map to:

```text
child_amount
ld_stage_inst_amount
cal_stage_inst_amount
flow_stage_inst_amount
st_stage_inst_amount
```

Those are covered by the legacy byte-projection quirks already implemented.

## 14. `54~62.md` and `65~73.md`: Repeated Evidence, No New Field Family

`tmp/diffs/54~62.md` repeats the `insts` section evidence:

```text
insts:
  record_size = 304
  section_status = DIFF

instance:
  record_size = 32
  section_status = MATCH
```

This strengthens the current boundary:

```text
instance_conf_info_file.bin is solved.
insts_file.bin differs mainly through instruction operand/register allocation.
```

`tmp/diffs/65~73.md` repeats the standalone `exeblock` section evidence:

```text
exeblock:
  record_size = 520
  section_diff_byte_count = 512
```

The listed byte values are the same small metadata field family already mapped
from `44~52.md`:

```text
child_amount
ld_stage_inst_amount
cal_stage_inst_amount
flow_stage_inst_amount
st_stage_inst_amount
```

No additional action is needed for these two OCR files beyond the fixes already
implemented for sections 10 and 11.

## 15. `75~88.md` and `90~100.md`: MICC Tail and Remote Fingerprints

The final OCR files repeat the MICC section structure:

```text
tasks:
  offset = 0
  size = 480
  record_size = 120
  rows = 4
  diff_byte_count = 9

subtasks:
  offset = 480
  size = 8522496
  record_size = 266328
  rows = 32
  diff_byte_count = 518
```

The task diff is exactly the already-fixed local/global subtask index-space
issue:

```text
task1: local 8,9,10   remote 0,1,2
task2: local 16,17,18 remote 0,1,2
task3: local 24,25,26 remote 0,1,2
```

The subtask diff rows are:

```text
0,1,2, 8,9,10, 16,17,18, 24,25,26
```

which correspond to the active subtask windows for four tasks.  The byte fields
inside those rows are the same embedded `exeBlock_conf_t` byte-projection
quirks already mapped:

```text
child_amount
stage instruction count fields
```

No additional code fix is indicated by these OCR files.

### 15.1 Remote Packer Fingerprint

The remote fingerprint at the end of `90~100.md` is important operational
evidence.  In particular, the arch-13 packer binary differs from the local
restored one:

```text
remote common_oper/libapp_build_common.so
  sha256 = e46d0f8870a0478133e02747de01297a30a1beb8b06fb413256d565af0d5938d
  size   = 3970464
```

Therefore local visible/restored C++ source can explain field families, but
arch-13 bytes are the final authority for compatibility decisions.

### 15.2 Current Post-OCR State

After reading all OCR files:

```text
instance_conf_info_file.bin:
  MATCH, solved

tasks_conf_info_file.bin:
  explained by local subtask index-space
  fix implemented

exeblock_conf_info_file.bin:
  explained by legacy byte-projection zero fields
  fixes implemented

subtasks_conf_info_file.bin:
  explained by embedded exeblock byte-projection zero fields
  fixes implemented

insts_file.bin:
  remaining major mismatch
  root cause: tensor register allocator, not struct layout
```

The next engineering task should focus on the DFU3500 legacy tensor register
allocator path for `inst_t` operands.

## 16. 2026-06-15 Tensor Register Allocator Fix

Implemented the first `insts_file.bin` fix in:

```text
compiler/gpdpu_compiler/core/program_legacy_inst.py
```

### 16.1 What Changed

`LegacyCsvEncoder` now has a separate tensor destination allocation path for:

```text
HLDT
HSTT
COPYT
```

when the CSV row carries a valid GEMM tensor group in `extra_fields[2]`.

The new behavior mirrors vendor evidence from:

```text
common_oper/inst_map_common.cpp
  PE::m_tensor_regs_available[group]
  PE::pop_tensor_regs_available_general(group)
```

Allocation formula:

```text
group_base = group_index * 4 * 128
tensor_base = group_base + (127 - allocation_index_in_group)
expanded_lane_operand = tensor_base + lane * 128
```

The regular/scalar operand path still uses the old regular allocator; this fix
does not globally replace `_layout_operand_idx`.

### 16.2 First 32 `inst_t` Rows Now Match the Arch-13 OCR Pattern

Before:

```text
dst0 = 0,0,0,0, 128,128,128,128, ...
```

After:

```text
dst0 = 127,255,383,511,
       126,254,382,510,
       125,253,381,509,
       ...
```

This matches the arch-13 `0~10.md` / `33~41.md` OCR pattern for the initial
HLDT-derived LDN records.

### 16.3 Local Determinism After Fix

Two local runs of the current compiler match byte-for-byte:

```text
OUT /tmp/openfabric_tensor_allocator_determinism
ALL_MATCH 1

config/cbuf_file.bin
  sha256 = ad893eeed556cccb1e10df703bc8ab02abfd82e626a597f13fd5803e20e401a9

config/micc_file.bin
  sha256 = 99909698f348b083edf171e26a9fa31422afb29ff726d92738c14814ea3348b4

simulator_bin/insts_file.bin
  sha256 = c1d75d639c2653872782019efaac2dac483aa7d974f8dda06c7ce5b484e734af
```

The `insts_file.bin` sha still does not prove full arch-13 parity; it only
confirms the first exposed tensor-destination allocation family has been
corrected.  A new remote diff is needed to reveal the next remaining `inst_t`
field family.

### 16.4 Validation Run

```text
pytest -q tests/test_chip_program_frontend.py -k "legacy_gemm or program_bin or task_conf"
  4 passed, 5 deselected

pytest -q tests/test_tile_dependency_network.py -k "program_bin or vendor_abi or exeblock or instance_conf or task_conf"
  11 passed, 53 deselected
```

## 17. 2026-06-15 Diff2: MICC Successor and Tensor Scalar Register Fixes

The newly pulled OCR bundle under:

```text
tmp/diff2/
```

was generated from the `tensor_reuse` local bundle and is much more structured
than previous OCR logs.

### 17.1 Diff2 Status Before This Patch Set

Diff2 showed the following component state:

```text
CBUF:
  insts      DIFF
  exeblock   MATCH
  instance   MATCH

MICC:
  tasks      MATCH
  subtasks   DIFF, only 6 bytes
```

The 6 MICC bytes were all in subtask rows:

```text
subtask[8]   9  -> 1
subtask[9]   10 -> 2
subtask[16]  17 -> 1
subtask[17]  18 -> 2
subtask[24]  25 -> 1
subtask[25]  26 -> 2
```

This proved that `task_conf_info_t.subtasks_idx` uses the DFU3500 fixed global
subtask row index, while `sub_task_conf_info_t.suc_subtasks` stores local
subtask indices.  The serializer now preserves that split:

```text
task slots:       global subtask row index
subtask trailer:  local subtask index
successors:       local subtask index
```

After the fix, representative MICC OCR offsets all match, and the current local
MICC sha is:

```text
config/micc_file.bin
  sha256 = ab56e64bff6f0d9b469146ef04d4584c2597f4bcbb1b951d49c43601eb2a9980
```

This matches the arch-13 OCR value from `tmp/diff2`.

### 17.2 Inst Field Families Found in Diff2

The remaining CBUF differences were all inside the `insts` section.  Mapping
absolute offsets through the real vendor `inst_t` layout:

```text
record_size = 304
format      = <I4xQQ3Q3Q3Q9Q3Q3Q3QQ3B3B2xQQQ3Q
```

showed the following field families:

```text
record 63 inner 272: end_inst
record 64 inner 72:  dst0
record 65 inner 72:  dst0
record 65 inner 192: fwd0
record 65 inner 200: iter_exe_cond
record 65 inner 216: src_fetch1
record 66 inner 16:  latency
record 66 inner 56:  src1
```

The byte patterns had very clear meanings:

```text
72 -> 2
  HMUL/FLOAT latency in the current arch-13 GEMM byte stream is 2, even though
  the visible common header still contains an older OP_FLT_LATENCY=72 constant.

1 -> 0 in forwarding/fetch-ish fields
  The arch-13 `inst_t` stream does not carry the Python forwarding/bypass bits
  we previously derived locally, so legacy GEMM compat encoding now disables
  forwarding application and treats the byte stream as ABI truth.

0 -> 1 at record 63 end_inst
  Stage/end flags are set at contiguous `unit_inst_type` boundaries, and
  `program_bin.py` must not clear legacy template end flags while assigning
  block indices.
```

### 17.3 Tensor Scalars: ALPHA/BET Are Tensor-Bank Values

The most important remaining inst mismatch after the tensor allocator patch was
not a layout problem.  It was scalar tensor-bank allocation.

Diff2 exposed:

```text
IMM ALPHA dst0:
  local  = 0
  remote = 639  = group1 tail slot

IMM BET dst0:
  local  = 128
  remote = 1151 = group2 tail slot

HMUL src1 for BET:
  local  = 128
  remote = 1151
```

This means `ALPHA` and `BET` are not regular scalar operands in the legacy GEMM
compat stream.  They are kept in tensor-register banks:

```text
ALPHA -> tensor group 1 tail slot
BET   -> tensor group 2 tail slot
```

Therefore input tile allocation starts one slot earlier:

```text
input0 first dst:
  expected = 638, not 639

input1 first dst:
  expected = 1150, not 1151
```

Implemented behavior in `program_legacy_inst.py`:

```text
_legacy_gemm_tensor_seed_before_input0:
  group0: output tiles
  group1: ALPHA
  group2: BET

_legacy_gemm_tensor_seed_after_input0:
  group1: ALPHA, then input0 tiles

_legacy_gemm_tensor_seed_after_input1:
  group2: BET, then input1 tiles
```

Representative CBUF offsets from `tmp/diff2` now all match locally after this
patch.  Current local bytes were generated under:

```text
/tmp/openfabric_scalar_tensor_seed_check_v2/run1
```

and produced:

```text
config/cbuf_file.bin
  sha256 = ccee18b6f7e91507c5f71241a861ec69dd3b7f84d485bbb6f22000d99c1091de

simulator_bin/insts_file.bin
  sha256 = cc0c6a71de2b1afe31c5e2bd01c25eb819c392cbed73d4dce6140f0d8104757e

config/micc_file.bin
  sha256 = ab56e64bff6f0d9b469146ef04d4584c2597f4bcbb1b951d49c43601eb2a9980
```

### 17.4 Validation

Targeted new-pipeline tests:

```text
pytest -q tests/test_chip_program_frontend.py -k "legacy_gemm or program_bin or task_conf"
  4 passed, 5 deselected

pytest -q tests/test_tile_dependency_network.py -k "program_bin or vendor_abi or exeblock or instance_conf or task_conf"
  11 passed, 53 deselected
```

One broader selected test still fails because `core_legacy` looks for the old
removed path:

```text
simict3500final/.../testcase/application/CASE/gemm_template_fusion
```

That failure is unrelated to the refactored `core` binary path investigated
here.

### 17.5 Next Remote Check

The current OCR diff2 bundle was generated before the latency/end flag and
ALPHA/BET tensor-scalar fixes.  A new remote pre-runtime byte diff is required.
Expected outcome:

```text
MICC should match exactly.
exeblock/instance/tasks/subtasks should match exactly.
remaining CBUF diff, if any, should be much smaller and localized to inst_t
fields not exposed by the sampled diff2 offsets.
```

## Diff3 Follow-up: Remaining CBUF Inst Field Families

`tmp/diff3` showed that MICC, exeBlock, and instance tables had reached byte
parity with arch-13.  The remaining visible mismatch was confined to
`cbuf_file.bin` / `insts_file.bin`.

Visible field families:

- Global inst record 65 (`IMM`): local `end_inst=1`, vendor `end_inst=0`.
- Global inst records 146..176 (`COPY` rows from route-forward `COPYT`):
  - input0 tensor source/destination indices were one slot too high;
  - expanded lanes needed source operand advancement by `+128 * lane`;
  - `src_operands_idx[1]` needed to carry the legacy `iter_exe_cond` value.

Applied fix:

- `route_forward` templates now seed input0 tensor tags before parsing.
- `COPYT` pseudo expansion now lane-adjusts the source operand and copies
  `iter_exe_cond` into the second source operand field for the expanded `COPY`.
- Synthetic stage-end flags are not emitted for FIX/IMM rows.

Local sample validation against exposed `diff3` offsets passed for all checked
bytes (29/29 known remote bytes matched after regeneration).

## Diff4 Follow-up: Tensor Scratch and Cross-task Tensor Seed

`tmp/diff4` still differed only in CBUF `insts`.  The representative offsets
mapped to `inst_t.dst0`, `src0`, `src1`, and one `end_inst` byte.

Key interpretation:

- `0 -> 6` at `dst0` byte 1 means vendor expects tensor compute rows to write to
  tensor scratch operand `1536`.
- `old - 16` / `old - 17` across later ranges means tensor operand banks are not
  reset per task; later GEMM task slots continue after previous task-local
  output/input/scalar tensor tags.
- CAL-like rows should not inherit synthetic stage-end markers.

Applied fix:

- `HMMAL` / `RXINT` rows use tensor scratch destination `1536`.
- Tensor seed state includes prior task slots and per-task ALPHA/BET scalar
  occupancy.
- Synthetic `end_inst` is restricted to LD/FLOW/ST boundaries.

Visible `diff4` sample validation: 42/42 representative offsets matched locally.
