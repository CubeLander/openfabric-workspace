# DFU3500 GEMM Binary Diff3 Notes

Date: 2026-06-16

## Context

`tmp/diff3` compares the current OpenFabric `legacy_gemm_compat` package against
arch-13 `gemm_template_fusion` runtime input blobs.  At this point MICC already
matches the vendor output byte-for-byte; the remaining visible differences are
inside the CBUF `insts` section.

## Confirmed Diff Shape

- `micc_file.bin`: matched vendor output.
- `exeblock_conf_info_file.bin`: matched vendor output.
- `instance_conf_info_file.bin`: matched vendor output.
- `cbuf_file.bin`: differed only through the `insts_file.bin` section.
- Visible `diff3` byte families:
  - record 65: `end_inst` byte was `1` locally and `0` remotely.
  - records 146..176: route `COPY` rows had operand-index mismatches:
    - `src_operands_idx[0]` / `dst_operands_idx[0]` were one tensor slot too high.
    - lane-expanded `COPY` source operand did not advance by `128` per pseudo lane.
    - `src_operands_idx[1]` was `0` locally and `1` remotely.

## Applied Interpretation

The route-forward micro-blocks parse legacy `COPYT` templates after input0 has
already been materialized.  Therefore they must seed the tensor allocator with
input0 tensor tags, not just regular scalar tags.  Without that seed, input0
route tensors are allocated one slot later than the vendor packer.

Vendor pseudo `COPYT -> COPY` expansion is lane-shaped.  The destination operand
was already lane-adjusted by `+128 * lane`, but the source operand also needs the
same lane adjustment for route-forward records.  The vendor-visible second source
field for these `COPY` records follows the legacy template iteration condition
(`1` in the observed route-forward rows).

The `IMM` row at global record 65 should not inherit the synthetic stage-end flag
that is used for non-FIX stage boundaries.  Treating every `unit_inst_type`
boundary as `end_inst=1` is too broad for arch-13 GEMM bytes.

## Remaining Caution

The `COPYT` second-source field is inferred from arch-13 bytes plus the legacy
CSV `iteration` field.  If future vendor cases use a different encoding for that
field, the rule should be checked against the corresponding `fill_copy_inst` /
CSV path evidence.

The source-lane adjustment is currently applied to `COPYT` expansion.  HSTT/HLDT
pseudo lane semantics may need separate investigation if future diffs expose
store/load tensor operand lane mismatches.

## Follow-up: Why No Further Encoder Patch From Current OCR

The visible `tmp/diff3` text only expands the first 32 differing instruction
records and the first byte window.  Those records all belonged to the same
route-forward `COPYT` field family, and the current patch fixes that family
across all locally generated route-forward records.

The remaining `section_diff_byte_count` was not field-expanded in the OCR text,
so additional encoder changes would be speculative.  The `gemmfix` diff script
now emits an `inst_field_diff_summary` with record ranges and `inst_t` field
names.  The next arch-13 run should be collected with a larger field window, for
example:

```bash
MAX_FIRST_DIFFS=2048 MAX_RECORD_DIFFS=2048 MAX_FIELD_DIFF_RECORDS=20000 ./run_diff_on_arch13.sh
```

That output should identify whether the remaining bytes are concentrated in
`src0/src1/dst0`, PE positions, block indices, forwarding/bypass bits,
`iter_exe_cond`, `end_inst`, or extra fields.

## Diff4 Follow-up: Tensor Scratch Destination and Cross-task Tensor Allocator

`tmp/diff4` exposed deeper `insts_file.bin` byte families after the route-forward
COPYT fixes:

- Many offsets were `0 -> 6` at `inst_t.dst0` byte 1.  These map to `dst0 =
  1536`, the tensor scratch destination used by tensor compute rows such as
  `RXINT`/`HMMAL`.
- Large `old - 16` / `old - 17` families appeared in `src0`, `src1`, and `dst0`.
  These correspond to later legacy GEMM task slots continuing the same tensor
  operand-bank allocator instead of resetting per task.
- One visible `HMUL` `end_inst` bit needed to remain clear; synthetic stage-end
  flags should be emitted only for LD/FLOW/ST boundaries, not for FIX/FLT/TENSOR
  CAL-like rows.

Applied fix:

- Tensor compute rows (`HMMAL`, `RXINT`) now receive `dst0 = 1536` as the legacy
  tensor scratch destination.
- GEMM tensor seeds now account for prior task slots in each tensor bank.  Each
  task contributes output tags plus per-task ALPHA/BET scalar slots and input
  tags, matching the descending vendor tensor-register allocation pattern.
- Synthetic `end_inst` is limited to LD/FLOW/ST unit-type boundaries.

Local validation against all visible `diff4` representative offsets passed
(42/42 known remote bytes matched after regeneration).  Further remote diff may
still expose fields outside the sampled ranges, but the currently visible CBUF
patterns are covered.

## 2026-06-16 new_diff guardrail: do not byte-fit operand indices

`tmp/new_diff.md` is a representative OCR/sample diff for the remaining CBUF
`inst_t` bytes.  The first pass reduced the sample mismatch by applying only
logic-backed fixes:

- Template-final instruction records keep their legacy `end_inst` bit.  FLOW
  template-final instructions also carry `flow_ack=1`.
- Route-forward COPY rows keep the CSV/template operand destination and only
  patch destination PE/block from the route endpoint.  The previous
  `col2 -> col3` special case that rewrote `dst_operand_idx0` to the child
  compute window was not supported by the sampled vendor rows.
- Last-column compute treats row-wise A visibility as a normal pre-materialized
  input.  This follows the tile route semantics: the final A route hop produces
  endpoint visibility before the compute micro-block consumes A.

Important guardrail: do not apply the remaining OCR byte deltas as direct row or
offset-specific patches.  The remaining differences must be explained through
compiler IR semantics, such as:

- tile route endpoint visibility ownership;
- tensor operand resource lifetime across task / wave / micro-block boundaries;
- how accumulator-prepare templates seed output, ALPHA, and BET tensor slots;
- whether a vendor template uses persistent task-level tensor resources or a
  fresh per-micro-block allocator.

A tempting experiment showed that manually changing the initial tensor seed table
can make a few `processor_0_3` wave1 accumulator-prepare rows match the OCR
sample.  This is not accepted as a fix yet, because it does not explain the
program-level ownership/lifetime rule.  Future changes should be made at the
level of template binding / tensor resource modeling, with a clear invariant and
cross-check against multiple tasks/waves, not by fitting individual byte ranges.

## 2026-06-16 follow-up: remaining two byte families are allocator semantics, not byte constants

After checking the local ABI notes and the restored vendor mapper source, the
remaining representative `new_diff` families look solvable, but they should not
be patched as literal record/offset deltas.

### Evidence

Vendor `inst_blk_map.cpp` has an explicit task-level operand resource model:

- `Task_Resource::get_reg_idx()` assigns a tag by
  `layout_operand_idx(m_reg_idx_counter + reg_start_idx)` and memoizes it in
  `m_reg_idx_list`.
- `Task_Resource::fill_reg_idx()` walks each node's LD, CAL, FLOW, and ST stage
  instructions in order and binds `src_reg_idx*_tag` / `dst_reg_idx_tag` through
  that task resource.
- `INST_BLK_MAP::fill_copy_inst()` is the key COPY/COPYT rule: route COPY
  destination PE/block are taken from the graph child node, and destination
  operand is `child Task_Resource.retrieve_reg_idx(dst_reg_idx_tag)`. Tensor
  COPY lanes then add `n * OPERANDS_PER_OPERAND_RAM`.
- `start_map_task()` resets `Task_Resource` per PE at task start, while
  `distribute_operand()` processes all nodes appended during that task.  This
  means operand numbers are a function of graph-node order inside a task, not a
  local CSV-template parse alone.

The instruction docs agree that operand index fields are semantic PE operand
slots: COPYT uses source operand 0 and destination operand 2, and HMUL uses
source operands 0/1 with destination operand 2.  Therefore the remaining src/dst
bytes are not cosmetic padding.

### Interpretation of the remaining families

1. `COPYT15 final-lane dst0 wants previous bank (-512)` is almost certainly the
   current OpenFabric route patch still missing vendor's child-resource lookup.
   We now correctly patch destination PE/block from the route endpoint, but the
   operand destination still comes from the template-local encoder.  Vendor
   instead asks the child processor's task resource for the COPY destination tag
   and only then lane-expands it.

2. `wave1 accumulator_prepare LDN/HMUL src/dst/BET seed` is the same family at a
   wider scope: our Python `LegacyCsvEncoder` currently simulates vendor state
   with static initial seed tables.  Vendor actually allocates tags while walking
   the PE task's node list.  When the second wave/task reaches accumulator
   prepare, the set and order of previously seen output/ALPHA/BET/input tags is
   determined by that task-resource walk.  The visible +/-1 and bank changes are
   symptoms of allocator state being close but not identical.

3. The one `last-column HMMAL A operand edge case` is already mostly addressed by
   treating row-wise A visibility as pre-materialized for compute.  If it remains
   after a true task-resource pass, it should be checked as a route endpoint tag
   ownership issue, not a last-column special constant.

### Required fix shape

The next safe implementation should introduce a DFU3500 legacy GEMM task-resource
binding pass before `InstBinRow` emission:

```text
TemplateBoundInstructions
  -> group by (task_index, processor)
  -> walk vendor node/stage order
  -> bind regular/tensor operand tags via a modeled TaskResource
  -> patch COPY destinations through child TaskResource.retrieve(tag)
  -> emit inst_t rows
```

This should replace the most brittle parts of the current static seed tables in
`program_legacy_inst.py`.  The static tables were useful to reach parity quickly,
but they are only an approximation of vendor `Task_Resource` behavior.  Remaining
fixes must move toward the allocator model, not further tune seed constants.


## 2026-06-16 correction: input0 strip15 stays in input0 tensor bank

The later direct byte-diff batch contradicted the earlier “input0 strip15 spills
into output/accumulator bank” hypothesis.  The cleaner evidence is:

```text
record 206..209 COPYT15 src0/dst0:
  local 111/239/367/495
  vendor 623/751/879/1007

record 577+ final-column HMMAL src0:
  local high byte 0
  vendor high byte 2

task1 accumulator_prepare output HLDT dst0:
  local 110/238/...
  vendor 111/239/...
```

Interpreted through the `inst_t` layout, byte `49` is `src_operands_idx[0]`
and byte `72/73` are `dst_operands_idx[0]`.  The vendor values are therefore
not flags or padding: `input0_15` belongs to the normal input0 tensor bank
(group1, +512), and should not consume an output/accumulator-bank slot before
the next task's accumulator prepare.

The corrected model is:

```text
A/input0 strips 0..15 -> primary A/input0 tensor bank
output0 strips        -> output/accumulator tensor bank
```

This remains an allocator/resource-lifetime fix, not a byte-level patch.

Representative local validation against the 2026-06-16 direct diff excerpt:

```text
sampled inst_t byte deltas: 64
matched after regeneration: 64
MICC sha256 remains ab56e64bff6f0d9b469146ef04d4584c2597f4bcbb1b951d49c43601eb2a9980
```

This supersedes the previous `input0 strip15 spill` note above.  Future agents
should treat that earlier interpretation as disproven by the direct byte diff.

## 2026-06-16 correction: BET remains in input1/B tensor bank

The next reported remaining range was:

```text
0x477d8 .. 0x4aed8
```

Mapping these offsets to `inst_t` records shows:

```text
0x477d8 = record 963 byte 72 = task1 accumulator_prepare IMM17 dst0
record 964..979               = task1 accumulator_prepare HMUL src1(BET)
record 980..1009              = task1/k0 A/input0 source materialize HLDT dst0
```

The previous code had placed task1 `BET` into the ALPHA/input0 tensor bank
(group1).  That made:

```text
BET = 621 (0x026d)
task1 input0_0 = 620
```

The vendor layout instead keeps `BET` in the input1/B tensor bank (group2), while
group1 continues with ALPHA and input0.  The corrected allocator state is:

```text
ALPHA = 622
BET   = 1134 (group2)
task1 input0_0 = 621
```

This patch changes only the tensor seed/lifetime model.  It does not patch
records directly.  Local validation:

```text
previous representative offsets: 64/64 still matched
new target range 0x477d8..0x4aed8: exactly 64 bytes changed locally
first changed byte: 0x477d8, matching the reported start of the remaining diff
MICC sha256 unchanged: ab56e64bff6f0d9b469146ef04d4584c2597f4bcbb1b951d49c43601eb2a9980
```

## 2026-06-16 follow-up: shallow receiver lookup is not enough

A minimal implementation was added to preserve raw CSV operand tags on
`LegacyInst` and to let `program_bin.py` build a receiver-side
`(task, processor, tag) -> operand_idx` view from template-bound instructions.
This is architecturally cleaner than patching byte offsets, and it matches the
shape of vendor `fill_copy_inst()`:

```text
COPY/COPYT source operand   = sender resource
COPY/COPYT destination PE   = child node PE
COPY/COPYT destination block= child node block
COPY/COPYT destination slot = child Task_Resource.retrieve(dst_reg_idx_tag)
```

However, this shallow receiver lookup currently does not change the remaining
arch-13 CBUF bytes.  The reason is important: the receiver-side view is still
built from the already-parsed static template rows, so it inherits the same
approximate seed model as `LegacyCsvEncoder`.  Vendor does not use a local
per-template resource table.  It walks the PE's task graph nodes in stage order
and mutates one `Task_Resource` for the whole `(task, PE)` mapping window before
`fill_copy_inst()` asks the child resource for the destination tag.

Therefore the real next fix is not another COPYT special case.  It is a real
DFU3500 legacy task-resource binding pass:

```text
ProgramVendorABI / TemplateBoundInstructions
  -> group exeBlocks by (task_index, processor)
  -> sort in vendor node/block order
  -> replay LD, CAL, FLOW, ST tag binding into modeled TaskResource
  -> run COPY/COPYT child-resource destination patch
  -> emit final InstBinRow.legacy_inst
```

The shallow receiver lookup is still useful scaffolding because it stores raw
CSV tags and centralizes COPY destination patching at the binary-row boundary,
but it should be treated as a transitional step, not the final allocator model.

Focused regression after this transitional step:

```text
pytest -q tests/test_chip_program_frontend.py -k \
  "legacy_gemm_template_keeps_input0_strip15 or legacy_gemm_compat_bundle or legacy_gemm or program_bin or task_conf"

5 passed, 5 deselected
```
