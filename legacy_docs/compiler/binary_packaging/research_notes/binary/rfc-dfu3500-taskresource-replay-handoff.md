# RFC: DFU3500 Legacy GEMM TaskResource Replay Handoff

Date: 2026-06-16

Status: handoff / accepted direction

Audience: qwen-code / future coding agents

## 1. Context

OpenFabric is currently DFU-first.  The immediate goal is to generate a
SimICT-compatible GEMM bundle for the vendor DFU3500 workflow, not to design a
general multi-backend compiler.

The current compiler pipeline can already emit a vendor-shaped bundle:

```text
ChipEnv / ChipProgram
  -> ProcessorLogicalProgram
  -> ProcessorTileProgram
  -> TileMicroBlock / TileLoopRegion
  -> ProgramNode / Packing / ProgramAsm
  -> folded ProgramVendorABI
  -> ProgramBinRows / ProgramBinComponents
  -> config/cbuf_file.bin + config/micc_file.bin
```

Recent work aligned most of the vendor ABI:

- MICC binary now matches the vendor runtime config exactly in the latest
  arch-13 comparison.
- CBUF size/layout matches the vendor runtime config.
- Instruction counts, opcode counts, stage counts, task/subtask/instance table
  shape, and legacy GEMM template envelope have been brought into parity.
- Remaining differences are concentrated in the CBUF `insts` section, mostly
  `inst_t` operand index fields.

Do **not** continue by hand-patching binary bytes.  Remaining differences should
be fixed by modeling the vendor operand allocation algorithm.

## 2. Current Known Good Behavior

The following behavior is locked by tests:

- Input0 strip 15 remains in the input0 tensor bank.
- `BET` remains in the input1/B tensor bank.
- `LegacyInst` now preserves raw CSV operand tags:
  - `src_reg_idx0_tag`
  - `src_reg_idx1_tag`
  - `dst_reg_idx_tag`
- A shallow receiver-side COPY/COPYT lookup scaffold exists in
  `program_bin.py`, but it is only a transitional helper.

Focused regression command:

```bash
cd /home/flecther/workspace/dpu_project
pytest -q tests/test_chip_program_frontend.py -k \
  "legacy_gemm_template_keeps_input0_strip15 or legacy_gemm_compat_bundle or legacy_gemm or program_bin or task_conf"
```

Expected result at handoff:

```text
5 passed, 5 deselected
```

## 3. What To Run On arch-13

Use the short bundle:

```text
/home/flecther/workspace/dpu_project/gemmfix.tgz
```

It contains old-Python-compatible scripts.  The scripts already include the
usual arch-13 defaults:

```text
APP_NAME=gemm_template_fusion
SIMICT_ROOT=/project/home-new/huake02/simict3500final
LOCAL_ROOT=$SCRIPT_DIR/local
MAX_FIRST_DIFFS=4096
MAX_RECORD_DIFFS=4096
MAX_FIELD_DIFF_RECORDS=50000
MAX_FIELD_SAMPLES=64
VENDOR_HOME=/project/home-new/huake02
DUP_TASKS=4
```

On `huake02@arch-13`, run:

```bash
tar -xzf gemmfix.tgz
cd gemmfix
bash run_diff_on_arch13.sh
```

If the vendor case must be rebuilt and captured before runtime, run:

```bash
tar -xzf gemmfix.tgz
cd gemmfix
bash build_stop_and_diff_on_arch13.sh
```

## 4. What Results To Bring Back

The most important artifact is the generated diff report path printed at the
end:

```text
diff_report=/home/huake02/.../local_vs_arch13_result_config_byte_diff_*.log
```

Bring back or OCR the following sections:

### Required

1. Top-level summary:

```text
=== case result cbuf ===
=== case result micc ===
=== runtime config cbuf ===
=== runtime config micc ===
ALL_TOP_LEVEL_MATCH=...
```

2. CBUF section report:

```text
### section report: result/cbuf_file.bin vs remote case result ###
[insts]
section_status=...
section_diff_byte_count=...
```

3. Field-level summary:

```text
inst_field_diff_summary ...
field=...
sample rec=...
```

The new script prints field-level samples for each differing `inst_t` field.
This is much more useful than raw byte OCR.  Especially preserve samples for:

```text
field=src0
field=src1
field=dst0
field=dst_pe0_x / dst_pe0_y
field=dst_block0
field=src_fetch*
field=dst_fetch*
field=extra*
```

### Optional But Useful

If the log is very long, bring the first 200 lines around:

```text
inst_field_diff_summary
```

and the first 100 lines of:

```text
first_section_differing_bytes
```

Do not spend time copying huge repeated byte ranges if `field=` summaries are
available.

## 5. Problem Statement

The remaining CBUF diffs are not random and not merely file packing errors.
They are mostly operand-index fields inside `inst_t`.

Vendor evidence:

```text
common_oper/inst_blk_map.cpp
```

Key functions:

- `Task_Resource::get_reg_idx()`
- `Task_Resource::retrieve_reg_idx()`
- `Task_Resource::fill_reg_idx()`
- `INST_BLK_MAP::distribute_operand()`
- `INST_BLK_MAP::fill_copy_inst()`

Important vendor behavior:

```text
Task_Resource::get_reg_idx(tag):
  assigns layout_operand_idx(m_reg_idx_counter + reg_start_idx)
  memoizes tag -> operand_idx

distribute_operand():
  for each node in PE task window:
    bind LD stage tags
    bind CAL stage tags
    bind FLOW stage tags
    bind ST stage tags

fill_copy_inst(parent_node):
  for each child edge:
    COPY destination PE/block = child node PE/block
    COPY destination operand = child Task_Resource.retrieve(dst_reg_idx_tag)
    COPYT lanes add n * OPERANDS_PER_OPERAND_RAM
```

Current OpenFabric still approximates this with static template seed tables.
That was good enough to reach near-parity, but it cannot fully reproduce vendor
operand allocation.

## 6. Target Design

Add a DFU3500 legacy GEMM task-resource binding pass before final `InstBinRow`
emission.

Target pipeline:

```text
ProgramVendorABI / TemplateBoundInstructions
  -> group exeBlocks by (task_index, processor)
  -> sort by vendor node/block order
  -> replay LD, CAL, FLOW, ST tag binding into modeled TaskResource
  -> patch COPY/COPYT destination through child TaskResource.retrieve(tag)
  -> emit final InstBinRow.legacy_inst
```

This pass should replace the brittle parts of static seed inference, not add
more record/offset special cases.

## 7. Proposed Implementation Plan

### Step 1: Model TaskResource

Create a small Python equivalent of vendor `Task_Resource`:

```python
class LegacyTaskResource:
    reg_start_idx: int
    reg_idx_counter: int
    reg_idx_by_tag: dict[str, int]

    def get_reg_idx(tag: str) -> int:
        if tag exists:
            return existing
        idx = layout_operand_idx(reg_idx_counter + reg_start_idx)
        reg_idx_counter += 1
        memoize
        return idx

    def retrieve_reg_idx(tag: str) -> int:
        return existing if present else get_reg_idx(tag)
```

Use the same layout formula:

```text
layout_operand_idx(raw) = (raw % 12) * 128 + raw / 12
```

Existing helpers in `program_bin.py`:

```python
_raw_operand_idx()
_layout_operand_idx()
```

### Step 2: Build Vendor Node Order

For each `(task_index, processor)` group:

1. Collect active `ExeBlockConfBinRow`.
2. Sort in vendor-equivalent order.
   Likely first approximation:

```text
subtask_index, instance_key, block_idx, instruction layout start_pc
```

But be careful: vendor `distribute_operand()` walks graph nodes in PE-local
`m_pGraph_nodes` order, starting from `pTask_res->node_idx_start`.  If parity is
not reached, inspect `ProgramVendorABI` / `ProgramAsm` order and adjust sort to
match vendor graph insertion order.

### Step 3: Replay Stage Binding

For each exeBlock in the group, walk instructions by stage:

```text
LD
CAL
FLOW
ST
```

For every valid instruction:

```text
src_reg_idx0_tag -> get_reg_idx()
src_reg_idx1_tag -> get_reg_idx()
dst_reg_idx_tag  -> get_reg_idx()
```

This should produce a per-task, per-processor resource map:

```text
(task_index, processor, tag) -> operand_idx
```

### Step 4: Patch COPY/COPYT Destinations

For route COPY/COPYT instructions:

```text
sender source operand = sender TaskResource tag result
destination PE/block  = child endpoint
destination operand   = child TaskResource.retrieve(dst_reg_idx_tag)
COPYT lane n          = base + n * 128
```

This corresponds to vendor `fill_copy_inst()`.

### Step 5: Emit Inst Rows From Bound Results

Do not let `program_serializer.py` or byte packers make semantic decisions.
They should only serialize the already-bound `LegacyInst` records.

## 8. Invariants / Regression Tests

Keep these tests passing:

```bash
pytest -q tests/test_chip_program_frontend.py -k \
  "legacy_gemm_template_keeps_input0_strip15 or legacy_gemm_compat_bundle or legacy_gemm or program_bin or task_conf"
```

Add new tests once TaskResource replay is implemented:

1. Raw tag preservation:

```text
COPYT15.src_reg_idx0_tag == gemm0_input0_0_15
COPYT15.dst_reg_idx_tag  == gemm0_input0_0_15
HMMAL.src_reg_idx0_tag   == gemm0_input0_0_15
```

Already partially locked in `tests/test_chip_program_frontend.py`.

2. COPYT destination algorithm:

```text
route COPYT dst0 must come from child/receiver TaskResource,
not the sender template-local operand index.
```

3. Old behavior must not regress:

```text
PE00 -> PE01 COPYT cases that already matched vendor remain matched.
BET remains in input1/B tensor bank.
input0_15 remains in input0 tensor bank.
```

## 9. Expected Effect

After TaskResource replay:

- Remaining CBUF `insts` diffs should drop sharply.
- MICC should remain MATCH.
- File sizes should remain unchanged:

```text
cbuf_file.bin = 23531520
micc_file.bin = 8522976
```

If CBUF still differs, the enhanced diff script should identify the exact
remaining fields.  Do not continue with raw OCR byte ranges if field summaries
are available.

## 10. Current Caveats

The shallow receiver-side lookup currently in `program_bin.py` is not enough.
It preserves the right interface shape and raw tags, but it still reads operand
indices from template-bound rows that were created by the static seed model.

In other words:

```text
raw tags are now available ✅
COPY patching is centralized ✅
full vendor TaskResource replay ❌
```

The next agent should implement the full replay pass rather than tune the
existing seed tables further.

## 11. Handoff Summary

The project is very close to functional and byte-level parity:

```text
MICC: matched
CBUF layout: matched
CBUF insts: remaining operand-index diffs
Root cause: vendor TaskResource dynamic allocation not fully replayed
Next fix: implement TaskResource replay pass before InstBinRow emission
```

The correct mindset:

```text
Do not fit bytes.
Replay the vendor allocator.
Then serialize boring rows.
```

