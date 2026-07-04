# Remote arch-13 GEMM Binary Diff OCR Notes

Date: 2026-06-15
Source screenshots: `/home/flecther/workspace/dpu_project/tmp/diff/1.png` ... `23.png`

Note: the local environment does not have an OCR engine (`tesseract`, `easyocr`, `paddleocr` are unavailable), so this is a structured manual OCR/digest of the visible terminal report. It preserves the useful row-level facts rather than every byte of the terminal dump.

## Compared Artifacts

Remote paths visible in screenshot 1:

```text
simict_root=/project/home-new/huake01/simict3500final
bundle_root=/project/home-new/huake01/openfabric_test_bundles/openfabric_simict_test_bundles_20260615_153813
ours_root=/project/home-new/huake01/openfabric_test_bundles/openfabric_simict_test_bundles_20260615_153813/bundles/gemm
legacy_root=/project/home-new/huake01/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion
```

## High-Level Component Status

From screenshots and previous SHA summary:

```text
MATCH simulator_bin/instance_conf_info_file.bin
MATCH config/input_data.bin in the earlier component summary
DIFF  simulator_bin/tasks_conf_info_file.bin
DIFF  simulator_bin/subtasks_conf_info_file.bin
DIFF  simulator_bin/exeblock_conf_info_file.bin
DIFF  simulator_bin/insts_file.bin
DIFF  config/cbuf_file.bin, config/micc_file.bin
```

Screenshot 23 additionally shows the script looked for `config/cbuf_file.bin`, `config/micc_file.bin`, and `config/input_data.bin` under the legacy application tree and printed `missing theirs=True` for those `config/*` paths. The earlier summary compared the right simulator/config locations and found input matched. Treat the screenshot-23 config section as a path-probing artifact, not as proof that the data differs.

## Tasks File OCR

Visible facts from screenshots 1-2:

```text
=== tasks file diff ===
same=False
ours_size=480 theirs_size=480
first_byte_diff=120

=== tasks row diff ===
record_size=120 rows=4 diff_rows=3 ours_extra=0 theirs_extra=0
first_diff_offset_top=[(0, 3)]
```

Rows:

```text
row0: not shown as a diff row; implied equal.

row1:
  ours_fields={start:1, end:1, subtask_amount:3,
               subtasks:(1, 8, 9, 10, 0, 0, 0, 0), successors:(0,0,0,0)}
  theirs_fields={start:0, end:0, subtask_amount:0,
                 subtasks:(0,0,0,0,0,0,0,0), successors:(0,0,0,0)}

row2:
  ours_fields={start:1, end:1, subtask_amount:3,
               subtasks:(1, 16, 17, 18, 0, 0, 0, 0), successors:(0,0,0,0)}
  theirs_fields={start:0, end:0, subtask_amount:0,
                 subtasks:(0,0,0,0,0,0,0,0), successors:(0,0,0,0)}

row3:
  ours_fields={start:1, end:1, subtask_amount:3,
               subtasks:(1, 24, 25, 26, 0, 0, 0, 0), successors:(0,0,0,0)}
  theirs_fields={start:0, end:0, subtask_amount:0,
                 subtasks:(0,0,0,0,0,0,0,0), successors:(0,0,0,0)}
```

Interpretation:

- Remote fresh legacy has only task row 0 active.
- OpenFabric currently emits task rows 0..3 as active.
- This contradicts the local `docs/compiler/binary_packaging/research_notes/archive/legacy_drafts/legacy_gemm_compat_row_diff_report.json`, where local build-out legacy also has four active task rows and matches OpenFabric. Therefore local build-out is not the same reference as arch-13 `application/gemm_template_fusion`.

## Subtasks File OCR

Visible facts from screenshots 2-5:

```text
=== subtasks file diff ===
same=False
ours_size=8522496 theirs_size=8522496
first_byte_diff=552

=== subtasks row diff ===
record_size=266328 rows=32 diff_rows=12 ours_extra=0 theirs_extra=0
first_diff_offset_top=[(0,3), (8,3), (1,3), (552,1), (528,1), (576,1)]
```

Rows 0/1/2:

- row0 visible fields match for control metadata:

```text
ours_fields={start:1, end:0, instances:1, instance_conf_addr:0,
             successors:(1,0,0,0), root_blocks:16, valid_exeblocks:16,
             subtask_idx_tail:0, task_idx_tail:0}
theirs_fields={same visible values}
first_byte=552 means the difference is later in the record, likely embedded exeBlock rows.
```

- row1 visible fields match for control metadata:

```text
ours_fields={start:0, end:0, instances:4, instance_conf_addr:32,
             successors:(2,0,0,0), root_blocks:4, valid_exeblocks:32,
             subtask_idx_tail:1, task_idx_tail:0}
theirs_fields={same visible values}
first_byte=528 means embedded/root block payload differs.
```

- row2 visible fields match for control metadata:

```text
ours_fields={start:0, end:1, instances:1, instance_conf_addr:160,
             successors:(0,0,0,0), root_blocks:16, valid_exeblocks:16,
             subtask_idx_tail:2, task_idx_tail:0}
theirs_fields={same visible values}
first_byte=576 means embedded/root block payload differs.
```

Rows 8/9/10, 16/17/18, 24/25/26:

```text
ours row8:  active task1/subtask0, instance_conf_addr=192, successor=9
ours row9:  active task1/subtask1, instances=4, instance_conf_addr=224, successor=10
ours row10: active task1/subtask2, instance_conf_addr=352

theirs rows8/9/10: inactive zero rows

ours row16/17/18: active task2 subtask0/1/2
theirs rows16/17/18: inactive zero rows

ours row24/25/26: active task3 subtask0/1/2
theirs rows24/25/26: inactive zero rows
```

Interpretation:

- Same as tasks: remote fresh legacy uses only global subtask rows 0/1/2 as active.
- OpenFabric currently emits four task windows: rows 0/1/2, 8/9/10, 16/17/18, 24/25/26.
- For rows 0/1/2, high-level subtask control metadata already matches, and the remaining difference is embedded exeBlock payload.

## ExeBlock File OCR

Visible facts from screenshots 5-14:

```text
=== exeblocks file diff ===
same=False
ours_size=266240 theirs_size=266240
first_byte_diff=480

=== exeblocks row diff ===
record_size=520 rows=512 diff_rows=256 ours_extra=0 theirs_extra=0
first_diff_offset_top=[(0,192), (480,32), (456,16), (504,16)]
```

Representative rows:

```text
row0, PE(0,0), block_idx=0:
  visible fields mostly match:
    valid=1, block_idx_prefix=0, pe=(0,0,0), req_activations=0,
    has_stages=(1,1,0,0,0), stage_start_pc=(0,64,82,82,82),
    task_idx=0, subtask_idx=0, instances=1, child_amount=0, inst_mem_addr=0
  difference:
    ours stage_counts=(64,18,0,0,0)
    theirs stage_counts=(0,0,0,0,0)

row1, PE(0,0), block_idx=1:
  both valid=1, task_idx=0, subtask_idx=1, instances=4,
  stage_start_pc=(82,146,146,146,146)
  differences:
    ours child_amount=2; theirs child_amount=0
    ours stage_counts=(64,0,0,0,0); theirs stage_counts=(0,0,0,0,0)

row2, PE(0,0), block_idx=2:
  both valid=1, task_idx=0, subtask_idx=1, instances=4,
  stage_start_pc=(146,146,146,210,210)
  differences:
    ours child_amount=2; theirs child_amount=0
    ours stage_counts=(0,0,64,0,0); theirs stage_counts=(0,0,0,0,0)

row3, PE(0,0), block_idx=3:
  both valid=1, task_idx=0, subtask_idx=1, instances=4,
  stage_start_pc=(210,274,834,834,834)
  differences:
    ours stage_counts=(64,560,0,0,0)
    theirs stage_counts=(0,0,0,0,0)

row4, PE(0,0), block_idx=4:
  both valid=1, task_idx=0, subtask_idx=2, instances=1,
  stage_start_pc=(834,834,834,834,898)
  differences:
    ours stage_counts=(0,0,0,64,0)
    theirs stage_counts=(0,0,0,0,0)

row5..19, PE(0,0):
  ours valid=1 and represents task1/task2/task3 blocks packed into PE00 block_idx 5..19.
  theirs valid=0 zero rows.

row32, PE(0,1), block_idx=0:
  both active and visible fields mostly match except ours writes stage_counts.

row33, PE(0,1), block_idx=1:
  both active, but visible child/stage_count fields differ similarly.

row34, PE(0,1), block_idx=2:
  both active, stage_start_pc=(146,210,770,770,770), stage_counts differs.

row35, PE(0,1), block_idx=3:
  both active, store block, stage_counts differs.
```

Interpretation:

1. Remote fresh legacy uses PE-local 32-row windows: row index `pe_index * 32 + pe_local_block_idx`.
2. OpenFabric already uses this formula in `program_bin.py`, but its `pe_local_block_idx` is assigned after packing four task/wave groups per PE. This makes PE00 rows 0..19 active, while remote legacy has only the task0 set active in PE00 rows 0..4.
3. Even where active rows align, OpenFabric writes fields that remote legacy leaves zero:
   - `stage_instruction_counts` at offsets visible around first_byte 480/504.
   - `child_amount` for some route/flow blocks.
4. The serializer currently writes these fields from symbolic analysis, while remote legacy appears to preserve zeros in those fields and relies on stage start PCs / embedded dependency records instead.

## Inst File OCR

Visible facts from screenshots 14-22:

```text
=== insts file diff ===
same=False
ours_size=21168128 theirs_size=21168128
first_byte_diff=72

=== insts row diff ===
record_size=304 rows=69632 diff_rows=53376 ours_extra=0 theirs_extra=0
first_diff_offset_top=[(0,40032), (48,9216), (72,3616), (16,512)]
```

Opcode-pair summary visible in screenshot 15:

```text
inst_op_diff_top=[
  (('HMMAL','0x0'), 24576),
  (('HMMAL','HMMAL'), 8192),
  (('LDN','0x0'), 6912),
  (('STD','0x0'), 3072),
  (('LDN','LDN'), 2304),
  (('COPY','0x0'), 2304),
  (('HMUL','0x0'), 1536),
  (('STD','STD'), 1024),
  (('COPY','COPY'), 768),
  (('RXINT','0x0'), 768),
  (('TRCTT','0x0'), 768),
  (('HMUL','HMUL'), 512),
  (('RXINT','RXINT'), 256),
  (('TRCTT','TRCTT'), 256),
  (('IMM','0x0'), 96),
  (('IMM','IMM'), 32),
]
```

This means many OpenFabric instruction rows are nonzero where remote legacy has zero. This is consistent with the same four-wave/task over-emission pattern seen in task/subtask/exeBlock tables.

First LDN rows also show a real field mismatch even where opcode is the same:

```text
row0:
  ours:   op=LDN opcode=64 unit=8 latency=1 imm=(0,0,0) dst=(0,0,0)   dst_pe0=(7,0,0)
  theirs: op=LDN opcode=64 unit=8 latency=1 imm=(0,0,0) dst=(127,0,0) dst_pe0=(7,0,0)

row1:
  ours dst=(0,0,0),   theirs dst=(255,0,0), imm=(256,0,0)
row2:
  ours dst=(0,0,0),   theirs dst=(383,0,0), imm=(512,0,0)
row3:
  ours dst=(0,0,0),   theirs dst=(511,0,0), imm=(768,0,0)
row4:
  ours dst=(128,0,0), theirs dst=(126,0,0), imm=(1024,0,0)
row5:
  ours dst=(128,0,0), theirs dst=(254,0,0), imm=(1280,0,0)
row6:
  ours dst=(128,0,0), theirs dst=(382,0,0), imm=(1536,0,0)
row7:
  ours dst=(128,0,0), theirs dst=(510,0,0), imm=(1792,0,0)
row8:
  ours dst=(256,0,0), theirs dst=(125,0,0), imm=(2048,0,0)
row9:
  ours dst=(256,0,0), theirs dst=(253,0,0), imm=(2304,0,0)
row10:
  ours dst=(256,0,0), theirs dst=(381,0,0), imm=(2560,0,0)
row11:
  ours dst=(256,0,0), theirs dst=(509,0,0), imm=(2816,0,0)
row12:
  ours dst=(384,0,0), theirs dst=(124,0,0), imm=(3072,0,0)
row13:
  ours dst=(384,0,0), theirs dst=(252,0,0), imm=(3328,0,0)
row14:
  ours dst=(384,0,0), theirs dst=(380,0,0), imm=(3584,0,0)
row15:
  ours dst=(384,0,0), theirs dst=(508,0,0), imm=(3840,0,0)
row16:
  ours dst=(512,0,0), theirs dst=(123,0,0), imm=(4096,0,0)
row17:
  ours dst=(512,0,0), theirs dst=(251,0,0), imm=(4352,0,0)
row18:
  ours dst=(512,0,0), theirs dst=(379,0,0), imm=(4608,0,0)
row19:
  ours dst=(512,0,0), theirs dst=(507,0,0), imm=(4864,0,0)
row20:
  ours dst=(640,0,0), theirs dst=(122,0,0), imm=(5120,0,0)
row21:
  ours dst=(640,0,0), theirs dst=(250,0,0), imm=(5376,0,0)
row22:
  ours dst=(640,0,0), theirs dst=(378,0,0), imm=(5632,0,0)
row23:
  ours dst=(640,0,0), theirs dst=(506,0,0), imm=(5888,0,0)
```

Interpretation:

- There are two instruction problems:
  1. Large placement/over-emission mismatch caused by four-wave/task packing vs remote single-task active layout.
  2. True operand-index mismatch in rows that both emit LDN. This points at legacy CSV template source, operand seeding, or `reg_idx` layout logic.
- The second point is directly relevant to `hmma memory out of range`: if destination operand slots differ, later HMMA reads can address the wrong operand/tensor window.

## Instance File OCR

Visible facts from screenshots 22-23:

```text
=== instances file diff ===
same=True
ours_size=2097152 theirs_size=2097152
sha matches

=== instances row diff ===
record_size=32 rows=65536 diff_rows=0 ours_extra=0 theirs_extra=0
first_diff_offset_top=[]
```

Interpretation:

- The previous instance-conf physical table fix worked.
- The CBUF instance table can remain as-is for now.
- Importantly, remote legacy can have task rows 1..3 inactive while still filling the physical instance table windows. Therefore task activity and instance_conf physical window filling are distinct ABI concepts.

## Cross-Validation Against Current Code

### Current OpenFabric creates one task per wave

`compiler/gpdpu_compiler/core/program_packing.py:265` declares:

```text
task_policy = task_per_output_tile_wave
```

`compiler/gpdpu_compiler/core/program_packing.py:433` binds nodes with:

```text
task_id = f"task{assignment.wave_id}"
```

`compiler/gpdpu_compiler/core/program_packing.py:905` also reconstructs task id from loop region path/wave id.

This matches OpenFabric OCR rows 1/2/3 being active and does not match remote fresh legacy.

### Current binary row planner already uses fixed instance_conf physical rows

`compiler/gpdpu_compiler/core/program_bin.py:1290` defines `dfu3500_legacy_instance_conf_row_index()` as:

```text
task * 8 * 2048 + local_subtask * 2048 + instance
```

This is why `instance_conf_info_file.bin` matches remote exactly.

### Current binary row planner uses fixed subtask windows

`compiler/gpdpu_compiler/core/program_bin.py:1629` defines:

```text
subtask_global_row = task_index * 8 + local_subtask_index
```

That formula is correct, but because the input `vendor_abi.vendor_tasks` contains task1/task2/task3, rows 8/9/10 etc become active. The issue is not the formula; the issue is the upstream active task set.

### Current exeBlock row planner uses fixed PE windows

`compiler/gpdpu_compiler/core/program_bin.py:1516` defines:

```text
exeblock_global_row = pe_index * 32 + pe_local_block_idx
```

This formula is correct, and remote row32/33/34 aligning with PE(0,1) confirms the PE-window policy. The issue is `pe_local_block_idx`: OpenFabric assigns many blocks to PE00 because four wave/tasks are packed into the same PE-local list.

### Current serializer writes fields remote legacy appears to leave zero

`compiler/gpdpu_compiler/core/program_serializer.py:496` packs exeblock rows. It writes:

```text
req_activations
child_amount
stage_instruction_counts[LD/CAL/FLOW/ST]
```

Screenshots show remote legacy has active `stage_start_pc` fields but zero `stage_counts` fields. OpenFabric writes nonzero stage counts. This is a separate field-parity issue after task layout is fixed.

### Current template source is local build_out, not remote application

`compiler/gpdpu_compiler/core/program_legacy_inst.py:435` points template parsing at:

```text
simict3500final/.../testcase/build_out/gemm_template_fusion/worktree/.../application/gemm_template_fusion
```

But the remote reference under comparison is:

```text
/project/home-new/huake01/simict3500final/.../testcase/application/gemm_template_fusion
```

The local `docs/compiler/binary_packaging/research_notes/archive/legacy_drafts/legacy_gemm_compat_row_diff_report.json` reports four active tasks and full parity against local build_out, while remote OCR shows one active task and operand-index differences. Therefore the local build_out artifact is not the same as the arch-13 application artifact.

## Current Problem List

1. **Reference mismatch**: local build_out reference matches OpenFabric but does not match arch-13 application legacy.
2. **Task activity mismatch**: OpenFabric emits task0..task3 active; remote application legacy has only task0 active.
3. **Subtask activity mismatch**: OpenFabric emits global subtask rows 0/1/2, 8/9/10, 16/17/18, 24/25/26; remote application legacy uses only 0/1/2.
4. **ExeBlock PE-window overfill**: OpenFabric places four wave/task blocks into each PE-local 32-row window; remote application legacy only places the task0 set in each PE window.
5. **ExeBlock field mismatch**: OpenFabric writes nonzero `stage_instruction_counts` and derived child/predecessor counts; remote active rows appear to leave some of those fields zero.
6. **Instruction row placement mismatch**: many OpenFabric inst rows are nonzero where remote legacy is zero, consistent with the over-emitted wave/task rows.
7. **Instruction operand-index mismatch**: first LDN rows differ in `dst_operands_idx` even when both sides emit LDN with the same immediate. This likely comes from template source or operand layout seeding.
8. **Instance table is solved**: `instance_conf_info_file.bin` matches exactly and should not be disturbed by the next fix.

## Immediate Implication

The `hmma memory out of range` failure is plausibly caused by instruction/operand field mismatch, not by `instance_conf` base addresses. The first instruction-level mismatch is already in LDN destination operands; if later HMMAL consumes a different operand slot than the legacy expects, simulator memory checks can fail.
