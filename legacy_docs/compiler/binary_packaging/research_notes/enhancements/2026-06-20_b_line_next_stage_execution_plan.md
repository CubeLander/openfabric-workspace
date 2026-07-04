# B-line Runtime Struct Plan

Date: 2026-06-20
Status: legacy execution-plan evidence. Current architecture is
`../../../../../../next_stage_refactor_direction.md`.
Scope: `compiler/gpdpu_compiler/core/stream_compiler`

This file records a historical B-line engineering plan. Use it for runtime
struct, folding, and failure lessons; do not use it as the next implementation
plan.

The core rule is:

```text
Fiber semantics first. Vendor struct shape second. Bytes last.
```

Loop folding must be decided from the fiber execution model: which fiber actions
are repeated, which actions are invariant, which values are carried, and which
materializations can be reused.  It must not be derived by reverse-engineering a
vendor row count and then forcing fiber IR to fit it.

Important refinement:

```text
The proof comes from fiber semantics.
The folded runtime scale is stream / PE-local subtask loop.
```

Vendor `sub_task_conf_info_t` is one subtask-level runtime container embedding
many PE-local `exeBlock_conf_info_t` rows.  Therefore different streams may run
different PE-local programs inside the same folded task/subtask loop.  Folding
must preserve that shape instead of assuming one global loop body for all
streams.

## References

Primary B-line references:

- `docs/compiler/binary_packaging/research_notes/enhancements/2026-06-18_fiber_first_stream_tile_design.md`
- `docs/compiler/binary_packaging/research_notes/enhancements/2026-06-19_b_line_fiber_executable_lowering.md`
- `docs/compiler/binary_packaging/research_notes/enhancements/2026-06-20_b_line_vs_a_line_pain_review.md`
- `docs/compiler/binary_packaging/research_notes/enhancements/rfc-fiber-executable-role-binding.md`
- `docs/compiler/binary_packaging/research_notes/enhancements/rfc-b-line-template-op-binary-plan.md`

Removed StreamTilePlan / flat-op bridge RFCs are superseded by the Scoped Tensor
Projection model.

Task / app / mesh semantics that constrain the plan:

- `compiler/notes/refactor/rfc-soft-device-mesh-task-axis.md`
- `compiler/notes/refactor/rfc-app-task-fusion-region-semantics.md`
- `docs/compiler/binary_packaging/research_notes/archive/rfc-vendor-multi-app-package-semantics.md`

Legacy loop / vendor ABI references, useful only as evidence:

- `docs/compiler/binary_packaging/research_notes/binary/2026-06-20_a_line_pain_retrospective.md`
- `docs/compiler/binary_packaging/research_notes/archive/rfc-folded-tileloop-vendor-repeat.md`
- `docs/compiler/binary_packaging/research_notes/archive/stage-report-folded-vendor-repeat.md`
- `docs/compiler/binary_packaging/research_notes/archive/rfc-program-bin-serializer.md`
- `docs/architecture/runtime-model/task-subtask-instance-runtime-model.md`
- `docs/architecture/runtime-model/vendor-exeblock-subtask-struct.md`
- `docs/architecture/gemm-case-study/gemm-tile-dag-from-legacy.md`
- `docs/vendor_reference/common_oper/subtask-graph-compile-chain.md`
- `docs/runtime/data/cbuf.md`
- `docs/runtime/data/micc.md`

## Current Baseline

Current B-line report-only pipeline:

```text
StreamPlan
  -> Fiber / FiberOp
  -> ExecutableFiberOp
  -> SymbolicRoleBinding
  -> SymbolicTemplateRecord
  -> Dfu3500RoleSemanticReport
  -> FiberExecutionSchedule
  -> TemplateOpPlan
  -> BinaryLayoutPlan
  -> DebugRowArtifact
  -> VendorLikeRowGroupPlan
  -> VendorLikeLocalRemapPlan
  -> VendorComponentPlan
```

Current `gemm_no_relu` report-only facts:

```text
fibers = 64
executable_ops = 1024
template_ops = 960
instruction_rows = 896
zero_boundaries = 64
exeBlock rows = 384
task rows = 4
subtask rows = 12
instance rows = 16
```

Current B-line candidate struct coverage:

```text
inst rows:
  candidate PE-local PC assigned

exeBlock rows:
  predecessor / successor endpoint slots
  stage start PC candidates
  inst_mem_based_addr candidates
  exeBlock_conf_info_candidate

task/subtask rows:
  task_conf_info_candidate
  sub_task_conf_info_candidate
```

Current intentional boundary:

```text
subtask1_k_stream:
  instances_amount = 1
  observed_loop_instance_count = 4
  instances_amount_policy = expanded_loop_instances_as_exeblocks_report_only
```

This is intentionally not yet the folded vendor representation.

## Design Principles For This Stage

### 1. Fiber proves repeat semantics; stream owns fold scope

A loop can be folded only if the fiber schedule proves:

```text
1. repeated actions have identical executable shape;
2. repeated actions differ only by loop instance / base address / fragment coord;
3. carried values are represented explicitly;
4. pre-loop actions are invariant or explicitly re-materialized;
5. post-loop actions depend only on the final carried state;
6. dependency proofs survive the folded representation.
```

The vendor field `instances_amount` is a projection of this proof.  It is not the
source of truth.

The vendor execution scale is not one fiber row.  Evidence from
`vendor-exeblock-subtask-struct.md` shows:

```text
sub_task_conf_info_t
  -> instances_amount
  -> exeBlocks_conf_info[MAX_EXE_BLOCK]
       -> exeBlock_conf_info_t has pe_dst, block_idx, stage PCs, successors
```

So a folded subtask instance repeats the subtask's PE-local graph.  Each stream
/ PE can have its own executable body under the same task/subtask loop.  B-line
should therefore report fold candidates at stream/subtask-loop scope, while
using fiber ops as the semantic proof source.

### 2. Report-only views must not lie

A candidate field can be present before byte emission, but it must carry policy
metadata when not final:

```text
binary_encoded = false
*_policy = ...
```

If the B-line cannot prove a field, keep it unresolved.  Do not fill a convenient
zero unless vendor evidence says zero is the visible convention.

### 3. Keep B-line independent from A-line compatibility artifacts

B-line may compare against A-line reports, but must not consume:

```text
TileMicroBlock
legacy source_tile_micro_block_kind
old ProgramBinRows as semantic authority
```

### 4. Keep instruction memory and data memory separate

The A-line retrospective identifies a very specific trap:

```text
STD used iter_exe_cond = 2
therefore STD consumed instance base_addr2
but the instance row originally populated the wrong base slot
```

That failure is data-memory base-slot binding.  It is not fixed by candidate
PE-local PCs, stage_start_pc, or inst_mem_based_addr.  Those are instruction
memory layout fields.

Therefore this plan treats the two domains separately:

```text
Instruction-side layout:
  candidate_pe_local_pc
  stages_start_pc
  inst_mem_based_addr
  stage instruction counts

Data-side layout:
  storage region
  base_addr slot
  offset unit
  iter_exe_cond / base slot selection
  instance_conf_info.base_addr[4]
```

No loop folding decision is valid until data-side base slots are visible in a
report and tied back to fiber memory roles.

### 5. Preserve the local feedback loop

B-line's main advantage over A-line is not beauty.  It is observability before
runtime upload:

```text
focused local check
  -> deterministic report
  -> candidate policy flag
  -> no binary_encoded claim
```

Every phase below must add a focused local check before moving to the next
phase.  If a phase requires remote SimICT to understand a basic field shape, it
is too opaque and should be split.

## Phase Plan

### Phase 1: Instance table candidate view

Goal: give `instance_rows` a report-only `instance_conf_info_candidate`.

Work items:

```text
1. Attach base_addr[4] candidate shape to every instance row.
2. Keep values unresolved if B-line cannot prove base address layout yet.
3. Add summary counts:
   - instance_candidate_struct_view_count
   - instance_candidate_struct_binary_encoded_count
   - instance_candidate_base_addr_resolved_count
   - instance_candidate_base_addr_unresolved_count
4. Extend `check_stream_compiler_vendor_components.py`.
5. Update this plan or the B-line lowering note with the checkpoint.
```

Expected initial policy:

```text
base_addr_policy = unresolved_pending_fiber_fragment_to_instance_base_mapping
binary_encoded = false
```

Reason: base addresses should be derived from fiber fragment identity and
storage layout, not from vendor row position.

Additional A-line guardrail:

```text
Do not fill base_addr[2] just because a legacy STD template happens to need it.
First expose the memory role -> base slot requirement as report data.
```

The initial Phase 1 artifact may therefore contain unresolved base slots, but it
must also show:

```text
which fiber/storage role wants which base slot
which slots are known unresolved
whether the row is byte-emittable
```

Checkpoint implemented:

```text
instance_conf_info_candidate attached to every active instance row
instance_candidate_struct_view_count = 16
instance_candidate_struct_binary_encoded_count = 0
instance_candidate_base_addr_resolved_count = 0
instance_candidate_base_addr_unresolved_count = 64
instance_candidate_base_addr_slot_shape_error_count = 0
```

The current candidate intentionally exposes only the four-slot
`instance_conf_info_t.base_addr[4]` shape.  Every slot is explicit and
unresolved:

```text
base_addr_policy = unresolved_pending_fiber_fragment_to_instance_base_mapping
data_memory_policy = data_base_slots_are_distinct_from_instruction_pc_layout
binary_encoded = false
```

Validated locally with:

```text
PYTHONPATH=compiler:compiler/tools python3 compiler/tools/check_stream_compiler_vendor_components.py
for script in compiler/tools/check_stream_compiler_*.py; do
  PYTHONPATH=compiler:compiler/tools python3 "$script"
done
```

### Phase 2: Fiber repeat/folding analysis report

Goal: add a report-only analysis that identifies foldable fiber segments without
changing component rows yet.

Work items:

```text
1. Group schedule rows by `(task_id, stream_id, subtask role, loop axis)`.
2. Identify pre-loop, loop-body, post-loop roles.
3. Compare loop-body executable shapes across k instances.
4. Emit `StreamLoopFoldCandidate` report records.
5. Add summary counts:
   - fold_candidate_count
   - fold_candidate_loop_instance_total
   - fold_candidate_rejected_count
   - fold_candidate_rejection_reasons
6. Keep current expanded component rows unchanged.
```

A fold candidate should answer:

```text
which actions repeat?
which actions are invariant?
which carried value crosses instances?
which materializations are per-instance?
which instance base rows are needed?
which base slots change across loop instances?
```

The fold report must explicitly distinguish:

```text
loop-invariant instruction shape
loop-varying data base rows
loop-carried accumulator state
```

Checkpoint implemented:

```text
StreamLoopFoldReport added as report-only analysis.
candidate_record_count = 64
fold_candidate_count = 64
fold_candidate_loop_instance_total = 256
fold_candidate_repeated_action_total = 768
fold_candidate_materialization_action_total = 512
fold_candidate_carried_dependency_total = 192
fold_candidate_instance_base_mapping_unresolved_count = 64
fold_candidate_rejected_count = 0
```

The analysis intentionally does not claim a single global loop body shape.
Current GEMM has four stream-visibility shapes, all uniform across K within
their own stream/subtask loop:

```text
A local / B local  : 4 streams
A local / B route  : 12 streams
A route / B local  : 12 streams
A route / B route  : 36 streams
```

This distinction matters: folding is stream-scoped.  A later folded overlay may
project different materialization/route body shapes for different streams under
one task/subtask loop, while still using the same fiber proof rule.

Validated locally with:

```text
PYTHONPATH=compiler:compiler/tools python3 compiler/tools/check_stream_compiler_folding.py
for script in compiler/tools/check_stream_compiler_*.py; do
  PYTHONPATH=compiler:compiler/tools python3 "$script"
done
```

### Phase 3: Folded subtask candidate overlay

Goal: add a second report-only overlay for `subtask1_k_stream` showing the folded
shape, while retaining expanded rows as the current executable debug view.

Work items:

```text
1. Produce `folded_subtask_conf_candidate` for k-stream subtasks.
2. Set candidate `instances_amount = 4` only in the overlay.
3. Point the overlay at one canonical loop body shape.
4. Preserve expanded rows and current `sub_task_conf_info_candidate`.
5. Add validation that overlay is not treated as byte-emittable.
```

Important: this phase must not delete `k1/k2/k3` expanded exeBlocks yet.  It is a
proof overlay, not a transformation.

Also important: this phase must not set `instances_amount = 4` unless Phase 2
has already proven a repeated fiber body and Phase 1/4 have made base-slot
semantics visible enough to explain each instance row.

Checkpoint implemented:

```text
folded_subtask_conf_candidate attached to k-stream subtask rows
folded_subtask_candidate_overlay_count = 4
folded_subtask_candidate_binary_encoded_count = 0
folded_subtask_candidate_instances_amount_total = 16
folded_subtask_candidate_stream_total = 64
folded_subtask_candidate_shape_total = 16
```

The overlay is produced only when `VendorComponentPlan` receives a
`StreamLoopFoldReport`.  The default component projection remains expanded and
does not infer folded shape by row count alone.

For each task's `subtask1_k_stream` overlay:

```text
instances_amount = 4
instances_amount_policy = stream_loop_fold_report_candidate
fold_scope = stream_subtask_loop
stream_candidate_count = 16
stream_body_shape_counts = {1, 3, 3, 9} across the four visibility shapes
instance_base_mapping_status = unresolved_pending_phase4
expanded_rows_remain_authoritative = true
folded_overlay_does_not_delete_expanded_exeblocks = true
binary_encoded = false
```

This is intentionally not runnable and not byte-emittable.  It only proves that
the stream-level subtask loop has a repeated K-body shape and that the future
folded representation should be attached to subtask/instance semantics, not to a
single global fiber body.

Validated locally with:

```text
PYTHONPATH=compiler:compiler/tools python3 compiler/tools/check_stream_compiler_vendor_components.py
for script in compiler/tools/check_stream_compiler_*.py; do
  PYTHONPATH=compiler:compiler/tools python3 "$script"
done
```

### Phase 4: Instance base mapping from fiber fragments

Goal: resolve `instance_conf_info_candidate.base_addr[4]` from fiber/storage
semantics.

Work items:

```text
1. Define which four base slots correspond to A/B/C/output or legacy roles.
2. Derive per-k instance offsets from fiber fragment coordinates.
3. Keep address units explicit:
   - byte offset
   - legacy uint32-word offset
4. Add validation that base rows match observed loop instances.
```

This phase should cite the SRAM region facts from
`compiler/gpdpu_compiler/core/dfu3500` and must not invent frontend DTensor inputs.

This phase is where the A-line `base_addr2` pain must be paid off properly:

```text
store/output memory role
  -> explicit base slot requirement
  -> instance_conf_info_candidate.base_addr[slot]
  -> offset unit documented as byte and/or legacy uint32-word offset
```

The result should be reviewable locally without uploading to SimICT.

Checkpoint implemented:

```text
instance_candidate_base_addr_resolved_count = 32
instance_candidate_base_addr_unresolved_count = 0
instance_candidate_base_addr_disabled_count = 32
instance_candidate_base_addr_slot_shape_error_count = 0
```

For current GEMM k-stream instance rows:

```text
slot0 = A base
slot1 = B base
slot2 = disabled_sentinel(0xffffffff)
slot3 = disabled_sentinel(0xffffffff)
base_addr_unit = uint32_words
word_bytes = 4
binary_encoded = false
```

The resolved A/B slots are derived from DFU3500 region facts:

```text
A_base_word = 0x00000000
B_base_word = 0x00010000
K_tile = 64
fp16_bytes = 2

A_increment_words_per_instance = 64 * 2 / 4 = 32
B_increment_words_per_instance = 64 * 512 * 2 / 4 = 16384
```

So:

```text
k0: base_addr0 = 0,  base_addr1 = 65536
k1: base_addr0 = 32, base_addr1 = 81920
...
```

The folded k-stream overlay now reports:

```text
instance_base_mapping_status = resolved_for_gemm_k_stream_a_b_slots
instance_base_mapping_policy =
  slot0_A_slot1_B_resolved_from_dfu3500_regions;
  slot2_slot3_disabled_sentinel_for_k_stream
```

Important boundary:

```text
This resolves GEMM k-stream A/B instance bases only.
It does not claim that final store/output base_addr2 is solved for every
future template family.
```

The A-line `base_addr2` pain remains represented as a compiler invariant:
store/output template families must export their selected `iter_exe_cond` /
base slot requirement before a runnable byte emitter may claim support.  This
Phase 4 step simply prevents the opposite bug: a folded K loop whose A/B
effective address remains stuck at k0.

Evidence path:

```text
Original-material audit:
  docs/vendor_reference/original_materials_audit.md

OpenFabric region facts:
  compiler/gpdpu_compiler/core/dfu3500/__init__.py

Legacy GEMM K-instance evidence:
  docs/architecture/gemm-case-study/gemm-tile-dag-from-legacy.md

Instruction/data memory split:
  docs/compiler/binary_packaging/research_notes/enhancements/2026-06-20_a_line_binary_memory_mud_for_b_line.md
```

Validated locally with:

```text
PYTHONPATH=compiler:compiler/tools python3 compiler/tools/check_stream_compiler_vendor_components.py
for script in compiler/tools/check_stream_compiler_*.py; do
  PYTHONPATH=compiler:compiler/tools python3 "$script"
done
```

### Phase 5: Folded component row experiment

Goal: optionally build a separate folded component candidate plan.

Work items:

```text
1. Introduce a separate artifact, not a mutation of current VendorComponentPlan.
2. Collapse k-stream exeBlocks only when Phase 2/3/4 proofs pass.
3. Compare expanded vs folded summaries.
4. Keep `runnability_state` as report-only / layout-candidate until byte rules are proven.
```

This is the first phase where row counts may change.  Before this phase, row
counts should remain stable to protect the current B-line debug feedback loop.

Checkpoint:

```text
Status: implemented as a report-only side artifact.

Implementation:
  compiler/gpdpu_compiler/core/stream_compiler/folded_components.py

Focused check:
  compiler/tools/check_stream_compiler_folded_components.py

Observed no-ReLU GEMM candidate:
  expanded inst rows     = 896
  folded inst rows       = 320
  inst row reduction     = 576
  expanded exeBlock rows = 384
  folded exeBlock rows   = 192
  exeBlock row reduction = 192
  task candidates        = 4
  instances_amount total = 16

Boundary:
  This artifact does not mutate VendorComponentPlan.
  It does not delete expanded rows.
  It does not emit binary bytes.
  It does not claim binary encoding.
```

Validated locally with:

```text
PYTHONPATH=compiler:compiler/tools python3 compiler/tools/check_stream_compiler_folded_components.py
for script in compiler/tools/check_stream_compiler_*.py; do
  PYTHONPATH=compiler:compiler/tools python3 "$script"
done
```

### Phase 6: Field-offset preflight, still no bytes

Goal: generate a field offset / size report for all candidate structs.

Work items:

```text
1. Report `inst_t`, `exeBlock_conf_info_t`, `instance_conf_info_t`,
   `task_conf_info_t`, `sub_task_conf_info_t` field offsets.
2. Map every candidate field to an offset and struct size.
3. Mark unresolved fields clearly.
4. Do not emit binary blobs yet.
```

This phase prepares byte emission without letting serializer details contaminate
fiber-level decisions.

Checkpoint:

```text
Status: implemented as report-only field-offset preflight.

Implementation:
  compiler/gpdpu_compiler/core/stream_compiler/field_offsets.py

Focused check:
  compiler/tools/check_stream_compiler_field_offsets.py

Observed no-ReLU GEMM candidate:
  struct reports             = 5
  known struct sizes         = 5
  field records              = 178
  known field offsets        = 36
  unresolved field offsets   = 142
  binary encoded fields      = 0

Struct row counts:
  inst_t                     = 896
  exeBlock_conf_info_t       = 384
  instance_conf_info_t       = 16
  task_conf_info_t           = 4
  sub_task_conf_info_t       = 12

Known offset sources:
  docs/runtime/data/cbuf.md
  docs/runtime/data/micc.md
  docs/compiler/binary_packaging/research_notes/archive/rfc-program-bin-serializer.md

Boundary:
  This phase reports known offsets and unresolved fields.
  It does not guess missing C/C++ layout fields.
  It does not serialize bytes.
  It does not make `inst_t` symbolic fields runnable.
```

Validated locally with:

```text
PYTHONPATH=compiler:compiler/tools python3 compiler/tools/check_stream_compiler_field_offsets.py
for script in compiler/tools/check_stream_compiler_*.py; do
  PYTHONPATH=compiler:compiler/tools python3 "$script"
done
```

### Phase 7: Serializer-readiness report, still no bytes

Goal: decide which component family is safe to target first without pretending
the full runtime package is serializable.

Work items:

```text
1. Combine field-offset preflight with candidate values.
2. Classify required serializer fields as ready or blocked.
3. Recommend the first writer only when every required field has:
   - known byte offset,
   - concrete candidate value,
   - no unresolved placeholder.
4. Keep output report-only.
```

Checkpoint:

```text
Status: implemented as report-only serializer-readiness view.

Implementation:
  compiler/gpdpu_compiler/core/stream_compiler/serializer_readiness.py

Focused check:
  compiler/tools/check_stream_compiler_serializer_readiness.py

Observed no-ReLU GEMM candidate:
  struct readiness records      = 5
  packable struct candidates    = 1
  blocked struct candidates     = 4
  required fields               = 42
  known required offsets        = 41
  ready required values         = 34
  blocked required fields       = 8
  recommended first writer      = instance_conf_info_t

Current blockers:
  inst_t:
    inst_t_fields lack known field offsets.
  exeBlock_conf_info_t:
    predecessor/successor invalid-slot representation and block_class remain unresolved.
  task_conf_info_t:
    subtasks_idx/suc_tasks padding sentinel policy remains unresolved.
  sub_task_conf_info_t:
    instances_conf_mem_based_addr and suc_subtasks padding policy remain unresolved.

Boundary:
  This phase does not serialize bytes.
  It does not make `instance_conf_info_t` runnable alone.
  It only identifies `instance_conf_info_t` as the safest first writer target.
```

Validated locally with:

```text
PYTHONPATH=compiler:compiler/tools python3 compiler/tools/check_stream_compiler_serializer_readiness.py
for script in compiler/tools/check_stream_compiler_*.py; do
  PYTHONPATH=compiler:compiler/tools python3 "$script"
done
```

## Immediate Next Task

Continue after Phase 7:

```text
Prototype a debug-only `instance_conf_info_t` writer or first add a
padding-sentinel policy report for task/subtask/exeBlock rows.
```

The safest narrow byte writer is now clear:

```text
instance_conf_info_t:
  format = <4Q
  required fields = base_addr[0..3]
  current candidate values = concrete
```

But that writer must remain a debug component writer, not a runnable package
writer.  Full package emission still depends on `inst_t`, exeBlock graph slots,
task/subtask padding sentinels, and compact instance table offset policy.

## Stop Conditions

Stop and write a note before proceeding if any of the following happens:

```text
1. A pass needs to inspect TileMicroBlock or legacy block kind.
2. A field can only be filled by guessing vendor bytes.
3. Loop folding requires deleting expanded fiber ops before an overlay proof exists.
4. ReLU unresolved status is accidentally made runnable.
5. A candidate struct field lacks policy metadata.
```
