# Archived RFC: B-line Finalize / Epilogue Template Semantics

Archived: 2026-06-19

Superseded by:

- `docs/compiler/binary_packaging/research_notes/enhancements/2026-06-19_relu_epilogue_vendor_evidence.md`
- `docs/compiler/binary_packaging/research_notes/enhancements/2026-06-19_b_line_fiber_executable_lowering.md`

This RFC captured the earlier uncertainty around `accumulator_finalize` and
`epilogue:relu`.  The current evidence split is:

```text
accumulator_finalize:
  proven zero-instruction accumulator/value boundary.

epilogue:relu:
  instruction-set supported via max-style SIMD ops and vendor subtask4 source,
  but unproven for the current 3-subtask runnable package.
```

Keep this file only as historical design context.

## Status

Archived.

## Summary

The experimental B-line stream compiler now reaches a report-only target binding
shape:

```text
StreamPlan
  -> Fiber / FiberOp
  -> FiberExecutableProgram / ExecutableFiberOp
  -> SymbolicRoleBinding
  -> SymbolicTemplateRecord
```

The next decision is whether `accumulator_finalize` and `epilogue:relu` should
remain first-class executable roles when we move toward DFU3500 template binding,
or whether they should be folded back into old `compute_update` / `tile_store`
shapes for compatibility.

This RFC recommends keeping them first-class in B-line.  The old backend may
continue hiding them inside legacy template/store behavior as a compatibility
path, but the new executable trunk must model them explicitly and either bind
them to real target semantics or report them as unsupported.  This prevents the
new stream/fiber architecture from quietly inheriting the exact semantic debt it
was created to remove.

## Known Facts / Assumptions / Open Questions / Non-goals

### Known facts

1. Current B-line GEMM demo has:

```text
fibers                  = 64
ExecutableFiberOp count = 1024
SymbolicTemplateRecord  = 1024
```

2. Current symbolic binding reports:

```text
template_candidate = 896
symbolic_only       = 128

symbolic_only roles:
  accumulator_finalize = 64
  epilogue:relu        = 64
```

3. The legacy DFU3500 GEMM template path only has canonical old micro-block
   categories:

```text
accumulator_prepare
route_source_materialize
route_forward
compute_update
tile_store
```

4. Current production tile lowering collects attached `relu` ops during matmul
   lowering and stores them in GEMM phase payload / tile loop metadata rather
   than creating a separate first-class executable op chain.

5. Current production final store phase is named `finalize_store` at subtask
   level, but the old executable micro-op/template path does not have distinct
   `accumulator_finalize` or `epilogue_relu` template roles.

6. Existing notes already identified that old graph counts differ from legacy
   because legacy represents additional finalize/assemble tile ops separately,
   while the current refactored tile path initially keeps GEMM post-op/finalize
   inside compute/store payloads.

### Assumptions

1. DFU3500 can represent at least one legal mechanism for finalize/store phase,
   because vendor GEMM+ReLU packages run.
2. The exact instruction-level mechanism for ReLU may be one of:
   - explicit CAL/FLOW/ST instructions in a vendor subtask template;
   - store-template side behavior;
   - a folded old CSV template envelope;
   - a no-op for current test if data path already materializes the desired
     value before store.
3. B-line should not claim binary-runnable support until the mechanism is proven
   by template records or by a deliberate compatibility fold policy.

### Open questions

1. Does vendor `subtask3/template/*.csv` contain explicit activation/finalize
   instructions for current GEMM+ReLU, or does it store an already-final value?
2. Is `accumulator_finalize` an actual hardware instruction sequence, or a
   semantic boundary indicating that the last K update has produced the final
   accumulator view?
3. Should `epilogue:relu` first bind as a target-independent local elementwise
   op, or as a DFU3500-specific fused store modifier?
4. Can legacy template rows be safely split into explicit finalize / epilogue /
   store roles without byte-level divergence?

### Non-goals

1. Do not emit DFU3500 binary from B-line in this phase.
2. Do not route B-line through `TileMicroBlock` compatibility rows.
3. Do not require exact byte parity for the new B-line before role semantics are
   proven.
4. Do not redesign task/subtask/instance packing in this RFC.
5. Do not generalize to non-DFU backends.

## Current State

### A-line compatibility branch

The A-line projection exists only as a microscope:

```text
FiberOp
  -> FiberBlockProjection
  -> TileMicroBlock compatibility probe
```

It answers:

```text
How close is the new flat FiberOp forest to the old TileMicroBlock rhythm?
```

It must not become the production semantic trunk.

Current A-line result for GEMM:

```text
mapped old categories:
  accumulator_prepare       64
  route_source_materialize  128
  route_forward             384
  compute_update            256
  tile_store                 64

unsupported old categories:
  finalize_accumulator       64
  epilogue_relu              64
```

This is not a failure of the new model.  It shows that the old model lacks an
explicit slot for roles that are semantically present.

### B-line executable branch

The B-line executable branch is now:

```text
FiberOp
  -> ExecutableFiberOp
  -> SymbolicRoleBinding
  -> SymbolicTemplateRecord
```

The authority boundary is:

```text
FiberOp is the semantic source of truth.
ExecutableFiberOp is the executable-role view.
SymbolicRoleBinding / SymbolicTemplateRecord are target support reports.
A-line compatibility projections are validation/debug views only.
```

Current symbolic template records explicitly retain:

```text
accumulator_finalize = symbolic_only
epilogue:relu        = symbolic_only
```

That is the correct failure mode.  It is honest and actionable.

### Legacy production path

The legacy production path remains:

```text
ProcessorTileProgram
  -> TileMicroBlock
  -> TileMicroOpProgram
  -> Dfu3500TemplateBoundProgram
  -> ProgramAsm
  -> ProgramVendorABI
  -> ProgramBinRows
```

The old template binder consumes `TileMicroOp.source_tile_micro_block_kind` and
selects vendor CSV template material from the five old categories.  It does not
consume `ExecutableFiberOp.role`.

Current production matmul lowering also collects attached ReLU operations during
matmul lowering, then carries them in `post_ops` / tile loop payload / fused
phase metadata.  This was useful for parity, but it is not the right long-term
executable IR shape.

## Problem

The next B-line step needs to approach real DFU3500 template semantics.  If we
bind `accumulator_finalize` and `epilogue:relu` by folding them back into old
categories:

```text
accumulator_finalize -> compute_update or tile_store
epilogue:relu        -> tile_store
```

then the refactor will preserve the old semantic bottleneck under new names.
That would cause four concrete failures:

1. **Semantic loss**: local finalize and epilogue actions disappear as separate
   executable responsibilities.
2. **Bad diagnostics**: unsupported activation/finalize support becomes
   invisible because the compiler pretends old templates already cover it.
3. **Wrong extension path**: future bias/GELU/SILU/fused epilogues have nowhere
   principled to attach except more store-template folklore.
4. **Authority inversion**: old compatibility categories become the source of
   truth again, instead of B-line executable roles.

The current symbolic-only status is therefore not a bug.  It is the necessary
checkpoint before target semantics are proven.

## Goals / Non-goals

### Goals

1. Keep `accumulator_finalize` and `epilogue:relu` first-class in B-line.
2. Define a target support lifecycle from symbolic role to concrete DFU3500
   template semantics.
3. Allow a narrow compatibility fold only as an explicit, reportable policy.
4. Preserve A-line compatibility probes as validation-only tools.
5. Add tests that prevent finalize/ReLU from disappearing.

### Non-goals

1. No binary emission in this phase.
2. No old `TileMicroBlock` source fields in B-line records.
3. No silent role folding.
4. No generic activation framework beyond the minimum ReLU epilogue role.

## Proposed Design

### 1. Add explicit role support states

Extend the B-line symbolic template support model conceptually into four states:

```text
template_candidate
  A role has a known legacy template candidate but is not yet emitted by B-line.

symbolic_only
  A role is semantically real but has no proven target template yet.

compat_fold_candidate
  A role may be represented by a legacy template envelope, but only through an
  explicit policy record that preserves provenance.

concrete_template_bound
  A role has target/profile-specific template semantics proven enough for later
  instruction/ASM lowering.
```

Current records use only:

```text
template_candidate
symbolic_only
```

The next implementation may introduce `compat_fold_candidate`, but it must not
replace `symbolic_only` silently.

### 2. Introduce explicit target semantic records for unsupported roles

For each symbolic-only role, create a target semantic record before any concrete
instruction binding:

```text
Dfu3500RoleSemanticRecord
  source_template_record_id
  executable_role
  source_fiber_op_id
  semantic_kind
  candidate_mechanism
  proof_status
  required_evidence
```

Initial records:

```text
accumulator_finalize:
  semantic_kind       = accumulator_boundary
  candidate_mechanism = last_k_update_output_view | finalize_subtask_marker
  proof_status        = unproven
  required_evidence   = prove final accumulator value consumed by store/epilogue

epilogue:relu:
  semantic_kind       = local_elementwise_epilogue
  candidate_mechanism = explicit_cal_template | fused_store_template | unsupported
  proof_status        = unproven
  required_evidence   = identify vendor ReLU semantics or reject runnable B-line
```

This layer is still report-only.  It is not an instruction binder.

### 3. Separate semantic support from compatibility folding

If the old vendor package can only be matched by folding finalize/ReLU into old
CSV envelopes, represent that as an explicit compatibility record:

```text
CompatibilityFoldRecord
  folded_roles: ("accumulator_finalize", "epilogue:relu", "tile_store")
  target_legacy_template_role: "tile_store"
  status: "candidate" | "proven" | "rejected"
  source_fiber_op_ids: (...)
  reason: "legacy path stores post-op/final output through subtask3 template"
  validation_required:
    - source roles preserved in metadata
    - folded record never becomes semantic source of truth
    - binary parity check if used for compatibility emission
```

This gives us a controlled escape hatch without lying about semantics.

### 4. Keep B-line template records authoritative above binary emission

The pipeline after this RFC should be:

```text
FiberOp
  -> ExecutableFiberOp
  -> SymbolicRoleBinding
  -> SymbolicTemplateRecord
  -> Dfu3500RoleSemanticReport
  -> future ConcreteDfu3500TemplateProgram
  -> future ASM / ABI / BinRows
```

The future concrete template layer must consume:

```text
ExecutableFiberOp.role
SymbolicTemplateRecord.status
Dfu3500RoleSemanticReport.proof_status
```

It must not consume:

```text
TileMicroBlock.block_kind
compat_probe.mapped_kind_counts
legacy-like sequence reports
```

### 5. Treat finalize and ReLU differently

`accumulator_finalize` and `epilogue:relu` should not be forced into one bucket.
They likely have different target meanings:

```text
accumulator_finalize
  May be a semantic boundary / value-version event.
  May not require a standalone instruction if the last K update already produces
  the final accumulator value.

epilogue:relu
  Is an actual local elementwise operation unless proven folded into a vendor
  template with equivalent semantics.
```

Therefore:

```text
accumulator_finalize may become concrete as a zero-instruction semantic boundary.
epilogue:relu must either bind to real compute/store semantics or remain unsupported.
```

This distinction is important.  A zero-instruction finalize is not the same as
silently deleting the role; it still provides value-version and dependency
meaning.

## Invariants

1. `FiberOp` remains the semantic source of truth for B-line.
2. `ExecutableFiberOp.role` remains the binding key.
3. `accumulator_finalize` and `epilogue:relu` must appear in B-line summaries
   until a later explicitly reviewed design changes the role model.
4. No B-line record may contain `source_tile_micro_block_id`,
   `source_tile_micro_block_kind`, or `tile_micro_block_kind` fields.
5. Compatibility projection may prove old-path resemblance, but B-line lowering
   must not consume compatibility-only fields as semantic authority.
6. A zero-instruction role must still emit a semantic/proof record.
7. A folded compatibility role must preserve all source role ids and must report
   the fold explicitly.
8. Binary emission from B-line is forbidden while any required role is
   `symbolic_only` or `unproven`.

## Alternatives Considered

### Alternative A: Fold finalize/ReLU into `tile_store` now

Rejected for B-line.

It may recreate old byte shape faster, but it erases the very semantic boundary
we need for future epilogues and generic fusion.  If we need this for binary
parity later, it should be a compatibility fold record, not the main role model.

### Alternative B: Treat current `tile_store` candidate as already covering ReLU

Rejected until proven.

The old workflow may do this, but B-line must know whether ReLU is implemented,
fused, no-op, or unsupported.  Assuming coverage would make diagnostics useless.

### Alternative C: Make `accumulator_finalize` a concrete CAL template

Deferred.

It may not need instructions at all.  First prove whether it is an actual
instruction sequence or a value-version/subtask-boundary event.

### Alternative D: Reuse `Dfu3500TemplateBoundProgram` directly

Rejected for B-line.

That object is shaped around `TileMicroOp` and old tile micro-block provenance.
B-line can borrow concepts like segment/stage/report, but not the source schema.

## Migration / Implementation Plan

### Phase 1: Keep current symbolic records stable

Already implemented:

```text
ExecutableFiberOp
SymbolicRoleBinding
SymbolicTemplateRecord
focused checks for 1024 records and explicit finalize/ReLU roles
```

### Phase 2: Add role semantic reports

Add a new report-only module, likely:

```text
compiler/gpdpu_compiler/core/stream_compiler/dfu3500_semantics.py
```

It should consume `SymbolicTemplateRecordProgram` and produce:

```text
Dfu3500RoleSemanticReport
```

with per-role proof status.

Initial behavior:

```text
accumulator_finalize -> unproven zero_or_boundary candidate
epilogue:relu        -> unproven local_epilogue candidate
```

### Phase 3: Inspect legacy CSV / template evidence

Research tasks:

1. Dump legacy `subtask3/template/*.csv` op names and stages.
2. Compare store template instruction rows against current GEMM+ReLU behavior.
3. Determine whether ReLU exists as explicit CAL/FLOW op, store modifier, or not
   in current vendor artifacts.
4. Determine whether final accumulator value is represented by last `HMMAL` /
   `TRCTT` rows and whether `finalize` can be zero-instruction.

### Phase 4: Add one of two proof paths

Path A: explicit concrete template semantics:

```text
accumulator_finalize -> zero_instruction_boundary or explicit template
epilogue:relu        -> explicit local elementwise template
```

Path B: compatibility fold semantics:

```text
(accumulator_finalize, epilogue:relu, tile_store)
  -> compatibility fold candidate
```

Path B may be acceptable only if metadata preserves all source roles and binary
parity validation is required before any runnable claim.

### Phase 5: Only then consider concrete instruction binding

After proof records exist, introduce:

```text
Dfu3500FiberTemplateProgram
```

This future layer may start generating concrete template segments or explicit
unsupported diagnostics.  It still should not jump directly to binary rows.

## Validation Plan

Existing checks remain required:

```bash
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_projection.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_executable.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_role_binding.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_template_records.py
```

Add new checks in Phase 2:

```text
test_dfu3500_role_semantic_report_counts
  expected records = 1024
  accumulator_finalize semantic records = 64
  epilogue_relu semantic records = 64

test_finalize_relu_not_silently_folded
  no record may convert these roles into tile_store without a fold record

test_zero_instruction_finalize_requires_proof_record
  if accumulator_finalize has zero instructions, it still has proof metadata

test_relu_requires_concrete_or_unsupported
  epilogue:relu cannot become template_candidate unless evidence is attached

test_no_tile_micro_block_provenance_in_b_line_semantics
  forbidden old fields remain absent
```

Add research utilities:

```text
print_legacy_template_summary.py
  dumps op/stage counts for subtask1/2/3 templates by task/PE/template index
```

## Risks and Mitigations

### Risk: too many symbolic layers before executable progress

Mitigation: keep each layer report-only, tiny, and count-checked.  Do not invent
large abstractions.  Each new record must answer a specific question:

```text
role exists?
role has candidate template?
role has proven DFU semantics?
```

### Risk: B-line diverges from byte-compatible legacy path

Mitigation: maintain A-line compatibility probes and later add explicit fold
records for byte-parity experiments.  Do not use A-line fields as B-line truth.

### Risk: ReLU support remains unclear

Mitigation: treat ReLU as unsupported until evidence exists.  This is better
than emitting a wrong runnable package.

### Risk: zero-instruction finalize gets mistaken for deleted finalize

Mitigation: require a semantic proof record for zero-instruction roles.

## Expected Effect

After this design, the compiler will be able to say precisely:

```text
These 896 executable roles have legacy template candidates.
These 64 finalize roles are semantic boundary candidates and need proof.
These 64 ReLU roles require concrete epilogue semantics or an explicit fold.
No B-line step has fallen back to old TileMicroBlock authority.
```

This turns the remaining gap from a vague “unsupported post-loop stuff” into two
small target-semantics questions:

```text
What is finalize on DFU3500?
What is ReLU epilogue on DFU3500?
```

## Open Questions

1. Does the current vendor GEMM+ReLU example actually exercise ReLU, or is the
   current demo using ReLU as compiler-side fused metadata only?
2. Which exact legacy CSV rows implement final output materialization?
3. Can `epilogue:relu` be represented by a small local CAL template independent
   of GEMM?
4. Is `accumulator_finalize` always zero-instruction for GEMM, or only for the
   current HMMAL/TRCTT template family?
5. If compatibility folding is needed, should it happen before or after
   concrete template segment generation?

## Recommended Decision

Accept the B-line direction with stricter Phase 2 semantics:

```text
1. Keep accumulator_finalize and epilogue:relu first-class.
2. Add report-only DFU3500 role semantic records next.
3. Research legacy subtask3/template evidence before claiming ReLU support.
4. Allow compatibility folding only as explicit, metadata-preserving policy.
5. Continue forbidding B-line binary emission while required roles are symbolic
   or unproven.
```

The next implementation phase should be:

```text
SymbolicTemplateRecordProgram
  -> Dfu3500RoleSemanticReport
```

not:

```text
SymbolicTemplateRecordProgram
  -> old TileMicroBlock / TileMicroOp / binary rows
```

## Evidence Checkpoint: Legacy GEMM Template Inspection

Added a read-only inspection helper:

```text
compiler/tools/inspect_legacy_gemm_templates.py
```

Focused command:

```bash
PYTHONPATH=compiler python compiler/tools/inspect_legacy_gemm_templates.py --subtask 3
```

Observed local legacy `gemm_template_fusion` template evidence:

```text
subtask3 template_count = 64
parse_errors = 0

for each task0..task3:
  templates = 16
  insts     = 1024
  stages    = {ST:1024}
  ops       = {STD:1024}
```

Per-template shape:

```text
taskN/subtask3/templateK:
  insts  = 64
  stages = {ST:64}
  ops    = {STD:64}
```

Interpretation:

1. Legacy `subtask3/template/*.csv` is a pure store envelope for the inspected
   GEMM package.
2. There is no explicit activation-like CAL/FLOW instruction in subtask3 by op
   name or stage.
3. This strengthens the current B-line classification:

```text
accumulator_finalize:
  likely a semantic boundary / final accumulator value-version event, not a
  standalone post-loop compute template in subtask3.

epilogue:relu:
  not proven by subtask3 template evidence; it must remain unproven unless
  evidence is found in another template layer or compatibility mechanism.
```

This does **not** prove ReLU is unsupported on DFU3500.  It only proves that the
current inspected legacy subtask3 CSV store template does not visibly implement
ReLU as a separate post-loop template stage.  The next evidence question is
whether ReLU is folded into earlier compute templates, omitted in this workload,
or represented outside the inspected CSV rows.
