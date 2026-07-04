# RFC: B-line TemplateOp and BinaryPlan Layering

## Status

Accepted with amendments.

## Summary

The B-line stream compiler has reached a stable report-only chain:

```text
StreamPlan
  -> Fiber / FiberOp
  -> ExecutableFiberOp
  -> SymbolicRoleBinding
  -> SymbolicTemplateRecord
  -> Dfu3500RoleSemanticReport
  -> FiberExecutionSchedule
```

The next decision is how B-line should cross from executable fiber scheduling
into DFU3500 template and binary generation without falling back into the old
`TileMicroBlock` authority model.

This RFC proposes the next layers:

```text
FiberExecutionSchedule
  -> TemplateOpPlan
  -> BinaryLayoutPlan
  -> BinaryEmitter
```

`TemplateOpPlan` describes target-template content: what operation each schedule
step wants to become.  `BinaryLayoutPlan` describes placement: where those
template ops live in task/subtask/instance/PC/blob space.  `BinaryEmitter` is
the final serializer: it writes bytes from a proven layout plan and must not
rediscover compute semantics.

The design keeps `FiberOp` as the semantic source of truth while giving the new
pipeline enough structure to grow real DFU3500 instruction rows gradually.

The required amendment is a Phase 0 feedback loop before treating the new
layers as architecturally clean.  Early B-line implementation may be muddy,
redundant, and report-only, but it must be observable, diffable, and
fail-closed.

## Development Principle: Feedback Before Cleanliness

B-line implementation is allowed to begin with incomplete, redundant, or
mechanically generated code if that code establishes a shorter feedback loop.

The first implementation goal is not elegance.  The first goal is to make the
lowering observable:

```text
FiberScheduleStep
  -> TemplateOp candidate
  -> status / proof / unresolved reason
  -> diffable report
```

A report-only implementation may be ugly.  It must not be opaque.

Phase 0 and Phase 1 code may duplicate logic temporarily, but every duplicated
decision must be visible in diagnostics or summary output.  Once the feedback
loop is stable, the implementation should be refactored into the authority
boundaries defined by this RFC.

Phase 0 rule:

```text
Make it exist.
Make it observable.
Make it explainable.
Only then make it clean.
```

## Current State

### B-line semantic chain

The active B-line note is:

```text
docs/compiler/binary_packaging/research_notes/enhancements/2026-06-19_b_line_fiber_executable_lowering.md
```

Current demo counts:

```text
FiberOp                  = 1024
ExecutableFiberOp        = 1024
SymbolicTemplateRecord   = 1024
Dfu3500RoleSemanticRecord= 1024
FiberScheduleStep        = 1024
```

`FiberExecutionSchedule` is a row view:

```text
one ExecutableFiberOp -> one FiberScheduleStep
```

It records phase, loop instance, proof status, semantic kind, role, and source
`FiberOp` dependencies.  It does not emit instructions or binary rows.

### A-line compatibility branch

The A-line block projection exists only as a validation/probing branch:

```text
FiberOp
  -> FiberBlockProjection
  -> legacy-like reports / TileMicroBlock compatibility probes
```

It asks whether the new fiber forest resembles the old backend rhythm.  It must
not become the new executable trunk.

### Existing production/core path

The existing core functional-probe path is still old-backend shaped:

```text
TileMicroOp
  -> Dfu3500TemplateBoundProgram
  -> ProgramBinRows
  -> binary serializers
```

See:

```text
docs/compiler/binary_packaging/research_notes/enhancements/rfc-core-functional-template-binding.md
```

That RFC remains valid for the current core functional smoke route.  It does
not define the new B-line template/binary architecture.

## Problem

The B-line now has stable executable fiber roles, but it has no real target
template layer.  If the next step jumps directly from `FiberScheduleStep` to
bytes, we will mix three responsibilities:

```text
1. template content selection;
2. binary placement / numbering / layout;
3. byte serialization.
```

That would recreate the same debugging problem the refactor is trying to avoid:
semantic decisions, layout decisions, and binary packing would become coupled in
one layer.

If instead B-line consumes old `TileMicroBlock` or `TileMicroOp` rows as the
source of template truth, it will inherit old hidden assumptions:

```text
source_tile_micro_block_kind
legacy block grouping
implicit finalize/store folding
template selection keyed by old block shape
```

That would make the new `FiberOp` model a decorative wrapper instead of the
actual compiler architecture.

## Goals / Non-goals

### Goals

1. Keep `FiberOp` as the semantic source of truth.
2. Make template content explicit before binary layout.
3. Make binary placement explicit before byte emission.
4. Allow zero-instruction semantic ops such as `accumulator_finalize`.
5. Preserve first-class unresolved roles such as `epilogue:relu`.
6. Keep old `TileMicroBlock` compatibility data out of B-line authority.
7. Support gradual implementation: first symbolic/report-only, then concrete
   instruction rows, then binary layout, then byte emission.

### Non-goals

1. Do not emit runnable DFU3500 binary from B-line in the first phase.
2. Do not replace the existing core functional-probe path immediately.
3. Do not solve register allocation or full operand-slot assignment in this RFC.
4. Do not implement ReLU runtime support in this RFC.
5. Do not make a generic multi-backend abstraction.  This is DFU3500-first.
6. Do not introduce a second authoritative dependency graph.  Dependency truth
   remains in `FiberOp` / schedule source references.

## Proposed Design

### Pipeline

```text
FiberExecutionSchedule
  -> TemplateOpPlan
  -> BinaryLayoutPlan
  -> BinaryEmitter
```

Expanded:

```text
FiberScheduleStep
  -> TemplateOp
  -> BinaryInstructionPlan / BinaryZeroInstructionBoundary / BinaryRegionPlan
  -> ProgramBinRows / vendor binary component bytes
```

The layers have different authority:

```text
FiberOp:
  semantic source of truth.

FiberScheduleStep:
  stable execution row view derived from ExecutableFiberOp.

TemplateOp:
  target-template content decision.

BinaryLayoutPlan:
  physical placement / numbering decision.

BinaryEmitter:
  pure serialization from a validated BinaryLayoutPlan.
```

### Shared schema rules

B-line reports must be deterministic and snapshot-friendly.  Use typed
diagnostics and JSON-stable attrs instead of arbitrary Python objects.

Sketch:

```python
JsonScalar = str | int | float | bool | None
JsonValue = JsonScalar | tuple["JsonValue", ...] | tuple[tuple[str, "JsonValue"], ...]

@dataclass(frozen=True)
class Diagnostic:
    severity: Literal["info", "warning", "error"]
    code: str
    subject_id: str
    message: str
    evidence_refs: tuple[str, ...] = ()
```

`diagnostics` are not all fatal.  Warnings and notes are expected in Phase 0 /
Phase 1 reports.  Runnable emission is rejected only for invalid state, error
diagnostics, or unresolved/unsupported content in a runnable request.

### Runnability state

B-line artifacts must carry an explicit runnability state:

```text
report_only:
  artifact exists only for inspection.

layout_candidate:
  placement has been computed, but bytes must not be emitted as runnable.

emittable_debug:
  bytes or row-like artifacts may be emitted for comparison/debug only.

runnable_candidate:
  all required template ops are concrete or proven zero-instruction, layout is
  valid, and emitter output may be considered for runtime smoke.
```

Unresolved or unsupported `TemplateOp`s are legal in `report_only` and
`layout_candidate`.  They are illegal in `runnable_candidate`.

### Relation to `SymbolicTemplateRecord`

`SymbolicTemplateRecord` is an evidence/support record.  It may inform
`TemplateOpPlan` construction, but it is not an authoritative B-line content
row.

`TemplateOp` is the first target-template content authority.  If both records
exist, `TemplateOp` must carry explicit references to the
`SymbolicTemplateRecord` or semantic report record that informed it.

### `TemplateOp`

`TemplateOp` is the first concrete target-template content layer in B-line.
It describes what each schedule step wants to become on DFU3500.

Sketch:

```python
@dataclass(frozen=True)
class TemplateOpProvenance:
    source_schedule_step_id: str
    source_schedule_ordinal: int
    source_executable_op_id: str
    primary_fiber_op_id: str
    dependency_fiber_op_ids: tuple[str, ...]
    semantic_report_record_id: str | None = None
    symbolic_template_record_id: str | None = None

@dataclass(frozen=True)
class TemplateOp:
    id: str
    provenance: TemplateOpProvenance
    role: str
    phase: str
    loop_instance: int | None
    template_kind: str
    template_status: Literal[
        "concrete_template",
        "zero_instruction",
        "symbolic_unresolved",
        "unsupported",
    ]
    instruction_intents: tuple[InstructionIntent, ...]
    required_resources: tuple[TemplateResourceRequirement, ...]
    diagnostics: tuple[Diagnostic, ...]
    attrs: tuple[tuple[str, JsonValue], ...]
```

Examples:

```text
accumulator_prepare:
  template_status = concrete_template
  template_kind   = legacy_accumulator_prepare_or_native_prepare

fragment_sram_read A:
  template_status = concrete_template
  template_kind   = operand_materialize

gemm_update:
  template_status = concrete_template
  template_kind   = hmma_k_update

accumulator_finalize:
  template_status = zero_instruction
  template_kind   = accumulator_value_boundary

epilogue:relu:
  template_status = symbolic_unresolved
  template_kind   = relu_max_zero_candidate

tile_store:
  template_status = concrete_template
  template_kind   = std_tile_store
```

`InstructionIntent` is not yet binary:

```python
@dataclass(frozen=True)
class InstructionIntent:
    opcode: str | None
    role: str
    intent_status: Literal[
        "concrete",
        "candidate_unproven",
        "symbolic_only",
    ]
    operand_policy: str
    immediate_policy: str | None
    emits_instruction: bool
    evidence_refs: tuple[str, ...]
```

For example:

```text
epilogue:relu candidate:
  IMM zero
  HMAX/FMAX input, zero -> output
```

But if package evidence is not proven, this remains unresolved and must not
silently become runnable.

A `TemplateOp` with `template_status = symbolic_unresolved` may carry candidate
instruction intents.  `BinaryLayoutPlan` must not allocate runnable PC rows for
those intents.

### `TemplateOpPlan`

`TemplateOpPlan` is a collection of `TemplateOp` rows plus diagnostics.

Sketch:

```python
@dataclass(frozen=True)
class TemplateOpPlan:
    profile_id: str
    runnability_state: Literal[
        "report_only",
        "layout_candidate",
        "emittable_debug",
        "runnable_candidate",
    ]
    template_ops: tuple[TemplateOp, ...]
    diagnostics: tuple[Diagnostic, ...]
```

Required first-phase invariant:

```text
one FiberScheduleStep -> one TemplateOp
```

The `TemplateOp` may contain zero instruction intents, one instruction intent,
or multiple instruction intents.  The one-to-one relationship is between
schedule steps and template content rows, not necessarily between schedule steps
and final hardware instructions.

### `BinaryLayoutPlan`

`BinaryLayoutPlan` is responsible for placement, numbering, and resource layout.
It consumes a `TemplateOpPlan` and decides where content goes.

Sketch:

```python
@dataclass(frozen=True)
class BinaryLayoutPlan:
    profile_id: str
    runnability_state: Literal[
        "report_only",
        "layout_candidate",
        "emittable_debug",
        "runnable_candidate",
    ]
    validation_status: Literal["valid", "invalid"]
    instruction_rows: tuple[BinaryInstructionPlan, ...]
    zero_instruction_boundaries: tuple[BinaryZeroInstructionBoundary, ...]
    task_rows: tuple[BinaryTaskPlan, ...]
    subtask_rows: tuple[BinarySubtaskPlan, ...]
    instance_rows: tuple[BinaryInstancePlan, ...]
    blob_regions: tuple[BinaryBlobRegionPlan, ...]
    diagnostics: tuple[Diagnostic, ...]
```

Use `BinaryZeroInstructionBoundary`, not a no-op-shaped schema name.  A hardware
NOP may consume PC.  A B-line zero-instruction semantic boundary must not.

`BinaryLayoutPlan` answers placement questions:

```text
Which task row owns this template op?
Which subtask receives it?
Is it pre-loop, loop body, or post-loop?
What loop instance / repeat region owns it?
What PC or row index does it get?
Does this semantic op occupy no instruction slot?
Which CBUF/MICC/blob component references it?
Does it fit vendor capacity limits?
```

It must not answer semantic questions like:

```text
Is ReLU max(x, 0)?
Is HMMAL a GEMM update?
Should this role be route or compute?
```

Those belong to `TemplateOpPlan`.

`BinaryLayoutPlan` may consume only:

```text
1. TemplateOp.role;
2. TemplateOp.template_kind;
3. TemplateOp.template_status;
4. TemplateOp.required_resources;
5. TemplateOp provenance schedule order / phase / loop instance;
6. explicit placement hints produced by TemplateOpPlan.
```

It must not inspect old backend block kinds, chip op internals, or original
`FiberOp` objects directly.

### `BinaryEmitter`

`BinaryEmitter` is a serializer:

```text
BinaryLayoutPlan -> bytes / files / ProgramBinRows components
```

It must not:

1. choose op semantics;
2. invent templates;
3. fold unresolved roles;
4. inspect chip ops or old TileMicroBlock kinds;
5. repair invalid layout.

`BinaryEmitter` must reject a layout if:

```text
1. validation_status = invalid;
2. any diagnostic has severity = error;
3. runnable output is requested while unresolved or unsupported TemplateOps
   remain;
4. any zero-instruction boundary has been allocated a PC or instruction row;
5. provenance from emitted row back to TemplateOp and FiberOp is missing.
```

Warnings and notes may exist in report-only or debug-emission modes.

## Authority Boundary

```text
FiberOp is the semantic source of truth.
FiberScheduleStep is a derived stable execution row view.
TemplateOp is the target-template content authority.
BinaryLayoutPlan is the binary placement authority.
BinaryEmitter is pure serialization.
```

Any mutation to `FiberOp` invalidates:

```text
ExecutableFiberOp
FiberScheduleStep
TemplateOp
BinaryLayoutPlan
emitted bytes
```

Any mutation to `TemplateOpPlan` invalidates:

```text
BinaryLayoutPlan
emitted bytes
```

Any mutation to `BinaryLayoutPlan` invalidates:

```text
emitted bytes
```

## Invariants

1. B-line template binding must consume `FiberScheduleStep` or
   `ExecutableFiberOp`, not `TileMicroBlock`.
2. B-line template binding key is role/template metadata from
   `ExecutableFiberOp.role` and semantic report, not old block kind.
3. Every `TemplateOp` has exactly one source schedule step.
4. Every source schedule step maps to exactly one `TemplateOp` in Phase 1.
5. A `TemplateOp` may be zero-instruction.
6. Zero-instruction template ops do not occupy PC or instruction row slots.
7. `TemplateOpPlan` may contain unresolved roles; `BinaryLayoutPlan` may not
   mark them runnable.
8. `epilogue:relu` remains unresolved until active `subtask4` evidence or a new
   explicit HMAX/FMAX epilogue template is bound.
9. `accumulator_finalize` is a proven zero-instruction accumulator/value
   boundary.
10. `BinaryLayoutPlan` must preserve provenance back to `FiberOp`.
11. `BinaryEmitter` must not inspect `FiberOp`, chip ops, or compatibility-only
    fields directly.
12. No B-line record may require `source_tile_micro_block_id`,
    `source_tile_micro_block_kind`, or `tile_micro_block_kind`.
13. Runtime-runnable flags require all required template ops and layout rows to
    be concrete or zero-instruction proven.
14. Structural/report-only rows must be clearly marked and must not be emitted
    as functional binary.
15. `SymbolicTemplateRecord` may be referenced as evidence but is not content
    authority.
16. `InstructionIntent(intent_status="candidate_unproven")` must never allocate
    a runnable PC row.
17. `attrs` must be immutable and JSON-stable for deterministic snapshots.
18. Demo count expectations are profile-specific, not global invariants.
19. A safe subset must come from a source profile whose semantics do not require
    unresolved roles.  The layout planner must not make an unresolved source
    program runnable by omitting unresolved `TemplateOp`s.

## Alternatives Considered

### A. Jump directly from `FiberScheduleStep` to binary rows

Rejected.

This would mix template content selection, layout, and serialization.  It would
make byte-level debugging opaque and recreate the old coupling.

### B. Reuse `TileMicroBlock -> TileMicroOp -> Dfu3500TemplateBoundProgram`

Rejected for B-line trunk.

The old path remains useful for current core functional probes and A-line
compatibility reports.  But consuming it as B-line authority would make
`FiberOp` non-authoritative and reintroduce old hidden grouping semantics.

### C. Make `TemplateOp` also decide PC/layout

Rejected.

Template content and binary placement evolve at different rates.  We need to
validate "what should be emitted" independently from "where it lands".

### D. Let `BinaryEmitter` fix unresolved roles

Rejected.

The emitter must be boring.  If it starts fixing roles or inventing templates,
the pipeline loses auditability.

### E. Wait until full register allocation is designed

Deferred.

The first `TemplateOpPlan` can use fixed symbolic operand policies and fail
closed.  Full register/operand allocation can be introduced as a later
layout-resource phase.

## Migration / Implementation Plan

### Phase 0: Observable feedback loop

Before B-line `TemplateOpPlan` is treated as architecturally correct, establish
a short feedback loop.

Phase 0 may contain incomplete, redundant, or mechanically generated code.  Its
goal is not architectural elegance.  Its goal is observability.

Required outputs:

```text
1. A deterministic JSON or markdown report for each demo profile.
2. A stable summary table:
   - FiberScheduleStep count
   - TemplateOp candidate count
   - concrete_template count
   - zero_instruction count
   - symbolic_unresolved count
   - unsupported count
   - forbidden TileMicroBlock field count
3. A diffable snapshot artifact checked by the review tool.
4. A fail-closed runnable status:
   report_only | layout_candidate | emittable_debug | runnable_candidate
```

Semantic ambiguity must be surfaced as typed diagnostics, not hidden behind
clean abstractions.

### Phase 1: Report-only `TemplateOpPlan`

Add:

```text
compiler/gpdpu_compiler/core/stream_compiler/template_ops.py
```

Implement:

```text
TemplateOp
TemplateOpPlan
lower_schedule_to_template_ops(schedule)
summarize_template_op_plan(plan)
```

Phase 1 output is report-only:

```text
FiberScheduleStep -> TemplateOp
```

Expected current GEMM+ReLU demo profile:

```text
TemplateOp count = 1024
concrete or zero-instruction proven = 960
unresolved = 64  # epilogue:relu
```

No binary output.

### Phase 2: Minimal concrete intent rows

Add `InstructionIntent` records for roles with proven semantics:

```text
accumulator_prepare
operand_materialize:A/B
operand_route_recv/push:A/B
compute_core:gemm_update
tile_store
accumulator_finalize zero-instruction boundary
```

Keep `epilogue:relu` unresolved unless an explicit ReLU template is attached.

### Phase 3: `BinaryLayoutPlan` skeleton

Add:

```text
compiler/gpdpu_compiler/core/stream_compiler/binary_plan.py
```

Implement report-only layout:

```text
instruction row count
zero-instruction boundary count
phase/subtask placement counts
loop instance placement counts
capacity diagnostics
```

No bytes yet.

### Phase 4: Concrete layout for one safe subset

Choose a subset that is already proven and does not require unresolved ReLU:

```text
GEMM without active ReLU
or a minimal functional local-compute probe
```

Emit layout rows, still optionally report-only.

For Phase 4, "GEMM without active ReLU" must be a distinct input/profile or an
explicitly lowered semantic variant.  The layout planner must not make a
ReLU-required source program runnable by dropping `epilogue:relu`.

### Phase 5: Binary emitter adapter

Add a serializer that consumes only validated `BinaryLayoutPlan`.

The first emitter may produce debug binary rows or compare against old replay
artifacts before writing final vendor blobs.

## Validation Plan

### Focused checks

Add:

```text
compiler/tools/check_stream_compiler_template_ops.py
compiler/tools/check_stream_compiler_binary_plan.py
```

Phase 1 checks:

```text
TemplateOp count = FiberScheduleStep count = 1024
every TemplateOp has source_schedule_step_id
every TemplateOp has source_schedule_ordinal
every TemplateOp has primary_fiber_op_id
no TileMicroBlock provenance fields
zero-instruction count includes accumulator_finalize = 64
unresolved role count includes epilogue:relu = 64
typed diagnostics are JSON-stable
summary includes runnability_state = report_only
```

Phase 3 checks:

```text
no unresolved TemplateOp is marked runnable
zero-instruction TemplateOps occupy no PC slot
every concrete instruction row traces to a TemplateOp
every TemplateOp traces to a FiberOp
capacity summaries are present
BinaryZeroInstructionBoundary records do not allocate instruction rows
```

### Negative tests

1. Reject B-line template binding that consumes `tile_micro_block_kind`.
2. Reject binary layout if `epilogue:relu` is unresolved but marked runnable.
3. Reject emission if `BinaryLayoutPlan` has error diagnostics.
4. Reject any emitted row without provenance back to `FiberOp`.
5. Reject any PC allocation for zero-instruction `accumulator_finalize`.
6. Reject runnable output if a candidate-unproven instruction intent remains.
7. Reject any B-line record with non-JSON-stable attrs.
8. Reject a runnable safe subset produced by silently dropping unresolved
   source `TemplateOp`s.

## Risks and Mitigations

### Risk: Too many layers

Mitigation: each layer has one job:

```text
TemplateOpPlan: content
BinaryLayoutPlan: placement
BinaryEmitter: bytes
```

If a layer starts doing another layer's job, that is a design bug.

### Risk: Old backend pressure pulls B-line back to `TileMicroBlock`

Mitigation: keep A-line compatibility probes separate.  Tests must reject
TileMicroBlock provenance fields in B-line records.

### Risk: TemplateOp becomes a hidden register allocator

Mitigation: Phase 1/2 use symbolic/fixed operand policies.  Real allocation is
a later layout/resource phase.

### Risk: Unresolved ReLU blocks progress

Mitigation: ReLU can remain unresolved while GEMM core progresses.  It is a
single role class with explicit proof status, not a reason to stop template
layering.

### Risk: BinaryPlan duplicates ProgramBinRows

Mitigation: `BinaryLayoutPlan` starts as B-line report-only layout.  Later it
may feed or replace pieces of `ProgramBinRows`, but should not be forced into
the old schema before the B-line content model is proven.

## Expected Effect

After Phase 1, reviewers should be able to inspect:

```text
FiberOp semantic source
Executable role
Schedule phase / loop instance
TemplateOp content choice
Proof / unresolved status
```

without opening binary serializers.

After Phase 3, reviewers should be able to inspect:

```text
template op -> instruction / zero-instruction boundary layout
task/subtask/instance/PC placement
capacity diagnostics
```

without reading bytes.

Only after those are stable should B-line emit binary.

## Open Questions

1. Should `BinaryLayoutPlan` target existing `ProgramBinRows` directly?

   Recommended answer: not in Phase 1/2.  Build a B-line layout report first,
   then decide the bridge.

2. Should `epilogue:relu` become a concrete `IMM + HMAX/FMAX` template now?

   Recommended answer: no.  Record the candidate, but keep it unresolved until
   package-level or new-template evidence is attached.

3. Should zero-instruction ops remain in later binary plans?

   Recommended answer: yes, as provenance/semantic boundaries, but they do not
   consume PC or instruction row slots.

## Recommended Decision

Accept the B-line layering:

```text
FiberExecutionSchedule
  -> TemplateOpPlan
  -> BinaryLayoutPlan
  -> BinaryEmitter
```

Implement Phase 0 and Phase 1 next:

```text
deterministic TemplateOp feedback report / snapshot
compiler/gpdpu_compiler/core/stream_compiler/template_ops.py
compiler/tools/check_stream_compiler_template_ops.py
```

Keep the first implementation report-only and fail-closed.  Do not emit binary.
Do not consume `TileMicroBlock` compatibility rows.  Preserve `FiberOp`
provenance through every record.
