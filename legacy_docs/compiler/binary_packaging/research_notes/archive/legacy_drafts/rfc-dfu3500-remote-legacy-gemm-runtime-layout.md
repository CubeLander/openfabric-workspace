# RFC: Align DFU3500 GEMM Runtime Layout With arch-13 Application Legacy

Date: 2026-06-15
Status: Draft for implementation
Scope: DFU3500 / SimICT / GEMM `legacy_gemm_compat` backend only

## 1. Background

OpenFabric now emits full-sized DFU3500 binary components for GEMM. The bundle reaches simulator execution, but remote execution fails with:

```text
Error: hmma memory out of range!
```

A remote static diff was run on arch-13 between:

```text
OpenFabric bundle: bundles/gemm
Remote legacy: /project/home-new/huake01/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion
```

The component sizes match. `instance_conf_info_file.bin` matches byte-for-byte. The remaining differences are in:

```text
tasks_conf_info_file.bin
subtasks_conf_info_file.bin
exeblock_conf_info_file.bin
insts_file.bin
```

Important context: the local checked-in/build_out legacy artifact previously used by OpenFabric is not equivalent to the arch-13 application legacy artifact. Local reports in `docs/compiler/binary_packaging/research_notes/archive/legacy_drafts/legacy_gemm_compat_row_diff_report.json` show four active task rows and local parity, while the remote OCR shows only task0 active.

## 2. Current State

### 2.1 What is already aligned

`instance_conf_info_file.bin` matches remote exactly:

```text
record_size=32
rows=65536
diff_rows=0
```

Current OpenFabric code already implements the fixed physical CBUF instance table:

```text
physical_instance_row = task_index * 8 * 2048 + local_subtask_index * 2048 + instance_index
```

Evidence:

- `compiler/gpdpu_compiler/core/program_bin.py:1290`
- OCR screenshots 22-23: `instances file diff same=True`

Do not change this table in the next fix.

### 2.2 Current task/subtask/exeBlock policy

Current packing explicitly says it is not final vendor schedule and uses one task per output tile wave:

```text
compiler/gpdpu_compiler/core/program_packing.py:265
  task_policy = task_per_output_tile_wave

compiler/gpdpu_compiler/core/program_packing.py:433
  task_id = f"task{assignment.wave_id}"
```

This creates active `task0`, `task1`, `task2`, and `task3` for a 2x2 output tile grid.

Current binary row planning then correctly applies fixed physical windows:

```text
subtask row = task_index * 8 + local_subtask_index
exeBlock row = pe_index * 32 + pe_local_block_idx
```

Evidence:

- `compiler/gpdpu_compiler/core/program_bin.py:1629`
- `compiler/gpdpu_compiler/core/program_bin.py:1516`

The formulas are correct, but the active task set and PE-local block ordering do not match arch-13 application legacy.

## 3. Evidence From Remote OCR

### 3.1 Task activity mismatch

Remote OCR:

```text
=== tasks row diff ===
record_size=120 rows=4 diff_rows=3
```

Rows 1/2/3:

```text
ours:   start=1 end=1 subtask_amount=3 subtasks=(8,9,10)/(16,17,18)/(24,25,26)
theirs: start=0 end=0 subtask_amount=0 subtasks=(0,0,0,0,0,0,0,0)
```

Conclusion:

```text
arch-13 application legacy only activates task0 for GEMM.
OpenFabric activates task0..task3.
```

### 3.2 Subtask activity mismatch

Remote OCR:

```text
=== subtasks row diff ===
record_size=266328 rows=32 diff_rows=12
```

Rows 0/1/2 have matching visible control metadata but differ in embedded exeBlock payload. Rows 8/9/10, 16/17/18, 24/25/26 are active in OpenFabric and zero in remote legacy.

Conclusion:

```text
arch-13 application legacy only activates global subtask rows 0,1,2.
OpenFabric activates four task windows.
```

### 3.3 ExeBlock physical layout mismatch

Remote OCR:

```text
=== exeblocks row diff ===
record_size=520 rows=512 diff_rows=256
```

Observed pattern:

```text
row0..4: both active for PE(0,0), task0 rows.
row5..19: OpenFabric active, remote legacy zero.
row32..35: both active for PE(0,1), task0 rows.
```

Conclusion:

- Remote legacy uses PE-local fixed windows (`pe_index * 32 + local_block`), which OpenFabric also implements.
- OpenFabric fills each PE-local window with blocks for four wave/tasks; remote legacy fills only task0 blocks in those windows.

### 3.4 ExeBlock field mismatch even where active rows align

For active rows 0..4:

```text
stage_start_pc mostly matches.
OpenFabric writes stage_instruction_counts=(64,18,...) / (64,560,...) / etc.
Remote legacy has stage_instruction_counts=(0,0,0,0,0).
```

Some row fields such as `child_amount` also differ:

```text
row1/row2: ours child_amount=2, theirs child_amount=0
```

Code evidence:

```text
compiler/gpdpu_compiler/core/program_serializer.py:496
  _pack_exeblock_conf_row writes req_activations, child_amount, stage counts.
```

Conclusion:

Once task layout is fixed, exeblock serializer field parity remains a separate issue.

### 3.5 Inst row mismatch

Remote OCR:

```text
=== insts row diff ===
record_size=304 rows=69632 diff_rows=53376
first_diff_offset_top=[(0,40032), (48,9216), (72,3616), (16,512)]
```

Opcode-pair summary shows many OpenFabric nonzero rows where remote legacy is zero:

```text
(HMMAL, 0x0): 24576
(LDN,   0x0): 6912
(STD,   0x0): 3072
(COPY,  0x0): 2304
...
```

This is consistent with four-wave/task over-emission.

There is also a true operand field mismatch on rows that are LDN on both sides:

```text
row0 ours dst=(0,0,0)   theirs dst=(127,0,0)
row1 ours dst=(0,0,0)   theirs dst=(255,0,0)
row2 ours dst=(0,0,0)   theirs dst=(383,0,0)
row3 ours dst=(0,0,0)   theirs dst=(511,0,0)
row4 ours dst=(128,0,0) theirs dst=(126,0,0)
...
```

Code evidence for current template source:

```text
compiler/gpdpu_compiler/core/program_legacy_inst.py:435
  _legacy_gemm_template_root() points to local build_out/gemm_template_fusion/worktree/.../application/gemm_template_fusion
```

Conclusion:

The current template source and/or operand layout seed does not match arch-13 application legacy. This is directly relevant to `hmma memory out of range`.

## 4. Problem Statement

OpenFabric currently has a hybrid mismatch:

```text
High-level tile semantics: multiple output tile waves.
Current DFU packing: maps each wave to a vendor task.
Remote application legacy: appears to encode all GEMM work under task0 runtime rows.
```

As a result:

1. MICC task/subtask rows over-activate task1..task3.
2. ExeBlock rows for each PE are over-filled with four wave/task groups.
3. Instruction rows are nonzero in places where remote legacy expects zero.
4. Even aligned instruction rows have operand destination mismatches due to local build_out template source divergence.

## 5. Non-Goals

This RFC does not:

1. Change `instance_conf_info_file.bin` physical layout.
2. Re-open tile route semantics or loop folding semantics.
3. Claim arch-13 application legacy is runtime-correct; remote legacy itself may fail. This RFC only aligns the emitted binary layout with the arch-13 application artifact currently being compared.
4. Generalize to CUDA/CANN or non-DFU backends.

## 6. Proposed Solution

### 6.1 Introduce a DFU3500 legacy runtime profile

Add an explicit profile for `legacy_gemm_compat` runtime row layout, e.g.:

```text
Dfu3500LegacyRuntimeProfile(
  task_activity_policy="single_active_task0",
  subtask_activity_policy="task0_subtasks_0_1_2_only",
  instance_conf_policy="fixed_physical_table_keep_existing",
  exeblock_row_policy="pe_fixed_32_slot_window",
  exeblock_field_policy="remote_application_legacy",
  inst_template_source="arch13_application_legacy_captured",
)
```

Do not hide this inside `program_serializer.py`. Task/subtask/exeBlock row activity is vendor ABI packing, not byte serialization.

### 6.2 Collapse vendor task activity for legacy GEMM compat

For `legacy_gemm_compat`, preserve `wave_id` as debug/origin metadata, but do not use it as vendor `task_id`.

Target:

```text
task row0: active, start=1, end=1, subtasks=(0,1,2,0,0,0,0,0)
task row1: zero
task row2: zero
task row3: zero
```

Preferred location:

- `compiler/gpdpu_compiler/core/program_packing.py`, because current task creation happens there.
- Alternatively, a dedicated DFU runtime packing pass between `ProgramAsm` and `ProgramVendorABI`, if changing packing directly is too invasive.

Key design rule:

```text
wave_id remains a logical/debug dimension.
vendor task_id becomes a backend packing dimension.
```

### 6.3 Emit only subtask rows 0/1/2 as active

For the same profile:

```text
subtask row0: prepare / accumulator seed
subtask row1: k_stream repeated body
subtask row2: finalize/store
rows 3..31: zero/inactive
```

Do not use active rows 8/9/10, 16/17/18, or 24/25/26 unless the selected profile is explicitly `four_wave_tasks`.

### 6.4 Recompute PE-local exeBlock order after task collapse

Current physical row formula is correct:

```text
exeblock_row = pe_index * 32 + pe_local_block_idx
```

But `pe_local_block_idx` must be assigned after the legacy task-collapse/profile ordering. For remote application parity, PE00 should not contain task1/task2/task3 blocks in rows 5..19.

Acceptance shape from OCR:

```text
PE00: rows 0..4 active, rows 5..31 inactive
PE01: rows 32..35 active, then inactive until next PE window
```

The exact active count per PE should be decoded from the remote binary rather than inferred only from screenshots.

### 6.5 Match remote exeblock field policy

After row placement aligns, fix row fields that remote legacy leaves zero:

```text
stage_instruction_counts fields: likely serialize as zero in legacy_gemm_compat.
child_amount / req_activations: verify against remote row decoder; do not blindly use symbolic dependency counts if legacy rows keep zero.
```

Possible implementation:

```text
legacy_gemm_compat:
  stage_start_pc: keep computed/canonical values
  stage_instruction_counts: zero in serialized exeBlock row if remote confirms
  child_amount: use remote/legacy edge record policy instead of symbolic fanout count
```

This belongs in a named compatibility policy, not as an unexplained zeroing hack.

### 6.6 Replace stale local template source

Current template root points to local build_out:

```text
compiler/gpdpu_compiler/core/program_legacy_inst.py:435
```

This reference has already diverged from arch-13 application legacy.

Options:

1. Capture arch-13 application generated templates/CSV into a stable repo-side fixture under `core/dfu3500`.
2. Parameterize template source root and make the bundle builder import the intended source explicitly.
3. Decode remote `insts_file.bin` into a canonical fixture for GEMM compat.

For simulator bring-up, prefer option 1 or 3. Do not keep relying on `testcase/build_out/...` as an implicit ambient source.

### 6.7 Fix operand-index layout after template source is corrected

The visible LDN mismatch:

```text
ours:   0,0,0,0,128,128,128,128,...
theirs: 127,255,383,511,126,254,382,510,...
```

is a hard verifier target. Add a test that decodes the first 32 LDN rows for PE00 and checks the remote pattern.

Relevant current code:

```text
compiler/gpdpu_compiler/core/program_legacy_inst.py:408  _layout_operand_idx()
compiler/gpdpu_compiler/core/program_bin.py:2049         _raw_operand_idx()
compiler/gpdpu_compiler/core/program_bin.py:2053         _layout_operand_idx()
```

## 7. Implementation Plan

### Phase 0: Improve diff capture

- Update the remote diff script to always save the full text report and copy it back from first-hop, avoiding screenshot OCR.
- Add active row counts for task/subtask/exeBlock/inst components.
- Add PE-local active row histograms for exeblock and inst tables.

### Phase 1: Add profile and task-collapse planning

- Add `Dfu3500LegacyRuntimeProfile` or equivalent in `core/dfu3500`.
- For `legacy_gemm_compat`, use `single_active_task0` task packing.
- Keep `wave_id` metadata for reverse maps and debugging.
- Ensure `instance_conf_info_file.bin` remains byte-identical.

### Phase 2: Subtask and exeBlock row placement

- Emit active subtask rows only at 0/1/2.
- Recompute PE-local exeBlock order under collapsed task layout.
- Verify exeblock active windows against remote:

```text
row0..4 active for PE00
row32..35 active for PE01
```

- Re-run component diff. Expected reduction:
  - task row diff rows should drop from 3 to 0.
  - subtask row diff rows should drop at least from 12 to rows 0/1/2 embedded payload only.
  - inst opcode-pair `op vs 0x0` mismatch should drop substantially.

### Phase 3: ExeBlock field parity

- Zero or profile-control fields that remote legacy leaves zero (`stage_counts`, possibly `child_amount`).
- Keep stage start PCs intact.
- Verify rows 0..4 active PE00 exeblocks against remote.

### Phase 4: Template/operand source correction

- Replace stale local build_out template source with arch-13 application-equivalent fixture.
- Add focused tests for first 32 LDN rows of PE00.
- Verify LDN `dst_operands_idx` pattern matches remote.

### Phase 5: Runtime re-test

- Repackage GEMM bundle.
- Upload and run on first-hop/arch-13 workflow.
- If runtime still fails, use simulator trace around first HMMA memory check and reverse-map failing PC to `ProgramBinRow -> VendorABI -> ASM -> TileMicroBlock`.

## 8. Expected Target Outcomes

After Phase 1-2:

```text
tasks_conf_info_file.bin: should be much closer, ideally match.
subtasks_conf_info_file.bin: only embedded exeBlock payload should remain different.
exeblock_conf_info_file.bin: active row placement should match remote.
insts_file.bin: large op-vs-zero mismatch should shrink.
instance_conf_info_file.bin: must remain MATCH.
```

After Phase 3-4:

```text
active exeblock row fields match remote application legacy.
first LDN operand rows match remote pattern.
HMMA memory out-of-range risk from operand slot mismatch should be reduced.
```

## 9. Validation Gates

1. `instance_conf_info_file.bin` remains byte-identical.
2. Task rows 1..3 are inactive under `legacy_gemm_compat` remote application profile.
3. Subtask rows 8/9/10, 16/17/18, 24/25/26 are inactive under that profile.
4. ExeBlock rows follow PE-local 32-row physical windows and no longer overfill PE00 rows 5..19 with task1/task2/task3 blocks.
5. ExeBlock stage count fields match remote policy.
6. PE00 first 32 LDN destination operand indices match remote.
7. Bundle generation still includes reverse-map metadata for debugging.

## 10. Open Questions

1. Is arch-13 application legacy a complete golden artifact or a partially generated artifact caused by the known original workflow failure?
2. Does the simulator expect single active task0 for this application, or is this only an artifact of the failed legacy build?
3. Should OpenFabric support both profiles?
   - `local_build_out_four_task_profile`
   - `arch13_application_single_task_profile`
4. Which artifact should be treated as the real customer target for byte parity?

Recommendation: implement the single-task profile as an explicit `legacy_gemm_compat` runtime profile for the current customer simulator target, while preserving enough metadata to revisit multi-task packing later.
