# RFC: B-line Binary Lowering And First Operator Delivery Plan

Date: 2026-06-22
Status: Mandatory execution plan for delivery week 2026-06-22..2026-06-28
Scope: B-line binary lowering, GEMM, GEMM+ReLU, log10max, DFU3500/SimICT delivery

## Summary

Customer pressure has changed the priority.  The first version must deliver all
three operators in the current delivery week:

```text
1. GEMM
2. GEMM+ReLU
3. log10max audio preprocess
```

This is not a best-effort enhancement track.  The working rule is:

```text
If an operator is theoretically implementable with current OpenFabric,
DFU3500 evidence, legacy template knowledge, hand-bound templates, or a
tactical bridge, we must use that path and deliver it this week.
```

Target schedule:

```text
2026-06-22 Mon:
  freeze scope and start binary writer completion

2026-06-23 Tue:
  GEMM uploadable binary package

2026-06-24 Wed:
  GEMM+ReLU uploadable binary package

2026-06-25 Thu:
  log10max uploadable binary package with declared DFU3500 allreduce strategy

2026-06-26 Fri:
  integration buffer, customer-facing bundle, issue triage
```

The current B-line GEMM path has enough structure to enter final binary
lowering:

```text
StreamPlan
  -> Fiber / ExecutableFiberOp / FiberExecutionSchedule
  -> TemplateOpPlan
  -> BinaryLayoutPlan
  -> VendorComponentPlan
  -> component writers
```

GEMM without ReLU is the closest path.  `instance_conf_info_t` already has a
debug-only writer.  `task_conf_info_t` and `exeBlock_conf_info_t` are now
packable candidates.  Remaining binary-lowering pressure is concentrated in:

```text
1. sub_task_conf_info_t.instances_conf_mem_based_addr
2. sub_task_conf_info_t writer with embedded exeBlock rows
3. inst_t long-struct instruction writer
4. final CBUF/MICC component assembly
5. ReLU concrete template binding
6. log10max local elementwise/reduce template path and mandatory V1 reduce strategy
```

The recommended decision is:

```text
Freeze non-critical B-line enhancements.
Deliver all three required first-version operator binaries this week.
Use the B-line programming model as the semantic authority.
Permit tactical target-specific bridges where the current B-line executable
path is not yet generic enough, but do not make those bridges new semantic
authority.
```

## Current State

### B-line GEMM / GEMM+ReLU

Current report/check facts:

```text
GEMM no-ReLU:
  TemplateOps = 960
  instruction rows = 896
  zero boundaries = 64
  runnability_state = emittable_debug

GEMM+ReLU:
  TemplateOps = 1024
  ReLU TemplateOps = 64 symbolic_unresolved
  current state = layout_candidate / fail-closed
```

Current component readiness:

```text
packable candidates:
  instance_conf_info_t
  task_conf_info_t
  exeBlock_conf_info_t

recommended first writer:
  instance_conf_info_t

blocked:
  inst_t_fields
  sub_task_conf_info_t.instances_conf_mem_based_addr
```

Current folded candidate:

```text
expanded inst rows     = 896
folded inst rows       = 320
expanded exeBlock rows = 384
folded exeBlock rows   = 192
```

The folded artifact is useful evidence but should not become the default
delivery path until the expanded path emits a working binary.  Row-count
optimization is not P0.

### ReLU

`epilogue:relu` is currently first-class in the B-line semantic path but not
concrete in the DFU3500 package:

```text
TemplateOp:
  role = epilogue:relu
  template_kind = relu_max_zero_candidate
  intent = candidate_unproven HMAX/FMAX with zero constant
```

The existing policy is correct for architecture, but customer delivery now
requires a concrete ReLU binding.  The first practical implementation should be
a local epilogue template:

```text
zero constant materialization
FMAX/HMAX input, zero -> output
store output
```

This may be encoded as a dedicated ReLU subtask or fused into the finalize/store
subtask depending on the smallest working vendor row shape.  For delivery, the
important boundary is not whether ReLU is "beautifully fused"; the boundary is
that B-line must not silently drop ReLU from a GEMM+ReLU program.

### log10max

The frontend can already describe the target expression:

```text
log_spec = log10(clamp(mel_spec, min=1e-10))
global_max = reduce_max(log_spec)
out = maximum(log_spec, global_max - 8.0)
out = (out + 4.0) / 4.0
```

Existing app-level notes already split the semantic problem:

```text
app0:
  compute/materialize global max

app1:
  reload input and global max
  recompute local log tile
  maximum / add_scalar / mul_scalar / store
```

The current compiler has symbolic all-reduce support:

```text
LogicalReduceEdge:
  reduce_op = max
  visibility_kind = replicated_scalar
  implementation_status = symbolic_collective_not_physical_route

TileCollectiveBundle:
  collective_kind = all_reduce_max_symbolic
```

This proves that the programming model can express allreduce-like collectives.
Customer delivery now requires closing the minimum DFU3500 physical allreduce
lowering for this operator family.  V1 does not need a generic or optimized
allreduce framework, but it must not leave `reduce_max -> replicated_scalar` as
symbolic-only technical debt.

## Problem

The main risk is not lack of IR expressiveness.  The main risk is spending the
current delivery week on generality while the customer needs runnable operator
binaries.

If we continue the enhancement track, we will improve:

```text
op-spec/folding purity
generic mixed-region fold planning
fully generic collective segmentation
folded component as default lowering
```

but still not deliver:

```text
GEMM binary
GEMM+ReLU binary
log10max binary
```

The delivery plan must therefore distinguish:

```text
Semantic authority:
  B-line programming model and explicit pipeline records.

Delivery bridge:
  narrow DFU3500 writer/template code that consumes B-line records or a
  mechanically derived compatibility view.

Deferred enhancement:
  generic, reusable abstractions that are not required for the first three
  operators.
```

## Goals / Non-goals

### Goals

1. Produce first-version binary lowering for GEMM.
2. Extend the same delivery path to GEMM+ReLU with explicit ReLU instructions.
3. Produce a first-version log10max operator binary this week.
4. Preserve B-line semantic ownership even when tactical target writers are used.
5. Make all operator delivery work DFU3500-first.
6. Keep allreduce/collective semantics visible in the programming model.
7. Implement the minimum DFU3500 allreduce lowering needed by log10max without
   waiting for a generic collective framework.

### Non-goals

1. Do not complete generic multi-backend abstraction.
2. Do not make folded rows the default before expanded binary emission works.
3. Do not finish op-spec/folding cleanup before the first operator binary.
4. Do not build a fully generic allreduce physical route in the first cut.
5. Do not optimize log10max performance in V1.
6. Do not treat validation framework work as part of this RFC.

## Engineering Pressure

### Pressure Level

```text
Overall: P0 mandatory customer delivery
GEMM binary: P0, due 2026-06-23
GEMM+ReLU binary: P0, due 2026-06-24
log10max binary: P0, due 2026-06-25
integration/customer bundle: P0, due 2026-06-26
generic B-line enhancements: frozen unless they directly unblock delivery
folded row optimization: frozen unless expanded binary cannot run
generic/optimized allreduce framework: frozen
minimum DFU3500 allreduce lowering for log10max: P0, due 2026-06-25
```

### Why GEMM Is The First Binary Target

GEMM no-ReLU has the smallest remaining gap:

```text
known:
  schedule
  template intents
  instruction rows
  task rows
  exeBlock candidate rows
  instance rows
  field offsets for most MICC/CBUF structs

missing:
  inst_t writer
  subtask writer
  final component assembly
```

It should be used as the binary-lowering spine.  GEMM+ReLU and log10max should
reuse the same writer and package path instead of inventing separate binary
pipelines.

### Why log10max Is The Hardest

log10max is not hard because the frontend cannot express it.  It is hard
because it needs a non-GEMM template family:

```text
elementwise:
  clamp_min
  log10 via FLOG2 * log10(2)
  maximum
  add_scalar
  mul_scalar

reduction:
  reduce_max over local lanes / tile
  replicated global max semantics

collective:
  allreduce-like global scalar visibility
```

The B-line model can represent the collective, but the physical route is not
ready.  The V1 plan must therefore choose a correctness-first strategy
immediately; log10max is a mandatory first-version deliverable, not a follow-up
operator.

## Proposed Design

### 0. Delivery State Contract

Every first-version operator artifact must report one explicit delivery state.
`package candidate` is not a state.

```text
binary_emitted:
  CBUF, MICC, and component files are produced
  file sizes match the selected DFU3500 profile
  byte writers did not emit from symbolic_unresolved rows

locally_inspectable:
  decoder/inspection can split sections and classify rows
  selected lowering representation is printed in the report
  unresolved, padding, and unknown classifications are explicit

uploadable:
  manifest, result/config/simulator_bin files, runtime assets, and reference
  assets are present
  hashes and sizes match manifest claims
  local package sanity checks pass

simict_loads:
  partner runtime accepts package and launch/control files
  upload/start path does not fail at packaging or runtime-control level

simict_executes:
  operator completes execution under SimICT

numerically_checked:
  collected output is compared with host reference under declared tolerance
```

Daily targets use these states:

```text
2026-06-23 GEMM:
  minimum = uploadable
  stretch = simict_executes

2026-06-24 GEMM+ReLU:
  minimum = uploadable with explicit ReLU concrete binding
  stretch = simict_executes

2026-06-25 log10max:
  minimum = uploadable with minimum DFU3500 allreduce lowering selected
  stretch = simict_executes

2026-06-26 customer bundle:
  customer-facing claim requires simict_executes or an explicit smoke-only tag
  numerical claims require numerically_checked
```

### 1. Delivery Pipeline

Use one delivery pipeline for all three operators:

```text
B-line semantic/source plan
  -> TemplateOpPlan or tactical TemplateBoundPlan
  -> BinaryLayoutPlan / component candidate rows
  -> ProgramBinRows-like component rows
  -> component byte writers
  -> CBUF/MICC assembly
  -> operator package
```

Authority boundary:

```text
B-line semantic/source plan is the source of truth.
Component rows are target binding.
Byte writers serialize already-decided rows.
Byte writers must not discover operator semantics.
```

### 1.1 Minimum Local Gate

All operator payloads must pass the common runtime-ready gate before they can be
called `uploadable`:

```text
archive_runtime_ready_gate(payload_dir)
  -> validate_payload(..., requested_gate=RUNTIME_READY)
  -> archive validation/runtime_ready.json
  -> fail closed on any authoritative error
```

This gate is not a new validation-framework expansion.  It is the minimum local
contract that prevents a binary-looking directory from becoming a deliverable
without manifest, runtime, component, graph, instruction-span, and memory-layout
evidence.

Additional operator-specific gate checks:

```text
GEMM:
  no symbolic_unresolved rows are emitted
  selected representation is explicit

GEMM+ReLU:
  epilogue:relu concrete count equals expected tile count
  store consumes ReLU output, not pre-ReLU accumulator

log10max:
  reduce_max remains visible in source/semantic plan
  collective_strategy is explicit
  minimum DFU3500 allreduce path is selected or a customer-approved waiver is
  recorded
  capacity proof is attached
```

### 2. Component Writer Order

Implement writers as three parallel tracks, not a single serial chain:

```text
Track A: MICC/control writers
  task_conf_info_t
  exeBlock_conf_info_t
  sub_task_conf_info_t
  instances_conf_mem_based_addr

Track B: CBUF/instruction writer
  inst_t minimal template-bound writer
  instruction-row zero-fill policy
  opcode/mnemonic sanity

Track C: package assembly/gate
  component concatenation
  manifest/runtime/reference assets
  runtime_ready report archive
```

Reasoning:

```text
task_conf_info_t and exeBlock_conf_info_t are now packable candidates.
sub_task_conf_info_t depends on compact instance table offset and embedded
exeBlock bytes.
inst_t is likely the long pole and must start in parallel with MICC writers.
Package assembly must be ready to reject incomplete artifacts immediately.
```

### 3. `instances_conf_mem_based_addr`

Resolve this before `sub_task_conf_info_t` writer:

```text
InstanceTableAddress:
  addr_space = instance_component_offset
  unit = bytes
  row_index = first instance_conf_info_t row used by this subtask
  byte_offset = row_index * sizeof(instance_conf_info_t)
  sizeof(instance_conf_info_t) = 32
  evidence = field-offset/readiness report plus writer invariant
```

Allowed `addr_space` values for reports:

```text
instance_component_offset:
  offset relative to instance_conf_info_file.bin

final_cbuf_offset:
  offset relative to final CBUF image

vendor_mem_based_addr:
  vendor-addressed value proven by external evidence

unknown:
  forbidden for uploadable artifacts
```

Zero-value invariant:

```text
if instances_amount == 0:
  instances_conf_mem_based_addr must be 0
  consumer must ignore it

if instances_amount > 0:
  instances_conf_mem_based_addr is a valid address
  0 means row_index 0, not disabled
```

Expanded GEMM delivery policy:

```text
subtask0_accumulator_prepare:
  instances_amount = 1
  instances_conf_mem_based_addr = 0 or a dedicated disabled/zero policy

subtask1_k_stream:
  instances_amount = 1 in expanded debug rows
  instance rows exist for k0..k3 in the current expanded view
  delivery may either:
    A. keep expanded exeBlocks and select one instance row per expanded k row
    B. switch to folded k-stream and use instances_amount = 4

Recommended for first binary:
  choose the representation that least disturbs current component rows.
  If expanded component rows already line up better with B-line reports,
  do not force folded rows yet.
```

If expanded rows become semantically awkward for instance selection, use the
folded side artifact only for the k-stream subtask.  This should be a controlled
switch, not a general folded pipeline migration.

Representation must be reported in manifest/package metadata:

```json
{
  "gemm_lowering_representation": {
    "default": "expanded",
    "subtasks": {
      "k_stream": "expanded"
    },
    "reason": "first binary uses current B-line component rows",
    "evidence": "serializer_readiness + component_writer reports"
  }
}
```

Gate rule:

```text
expanded exeBlock rows must not reference folded instance counts unless the
subtask representation explicitly says so.
```

### 4. GEMM Binary Strategy

First GEMM binary should use:

```text
operator profile:
  gemm_no_relu

component rows:
  current expanded VendorComponentPlan unless folded k-stream is required by
  vendor repeat semantics

templates:
  existing GEMM instruction intents and legacy template evidence

writer target:
  full component files, not just debug JSON
```

Deliverable:

```text
GEMM operator package with cbuf/micc files and runtime assets expected by the
existing SimICT workflow.
```

### 5. GEMM+ReLU Strategy

GEMM+ReLU should not wait for a general elementwise fusion graph.

Implement the narrow epilogue:

```text
input:
  accumulator/final GEMM output tile

ops:
  materialize zero
  FMAX/HMAX(tile, zero)

output:
  ReLU tile consumed by store
```

Two possible layouts:

```text
Option A: fused finalize/store subtask
  finalize_accumulator -> relu -> store

Option B: explicit ReLU subtask
  finalize_accumulator -> relu subtask -> store
```

Recommended:

```text
Default to Option B: explicit ReLU subtask.
Use fused finalize/store only if template evidence proves stage ordering and
operand lifetime.
```

Required invariant:

```text
GEMM+ReLU must never be made runnable by omitting epilogue:relu.
FMAX/HMAX dtype, zero constant dtype, NaN/Inf policy, and tolerance must be
declared before any numerical claim.
```

### 6. log10max Strategy

V1 should prioritize correctness and explicit allreduce lowering over physical
allreduce elegance.  The requirement is not "finish generic allreduce"; it is
"do not leave the B-line `reduce_max -> replicated_scalar` collective as
symbolic-only debt."

There are three candidate strategies:

#### Strategy A: minimum DFU3500 physical allreduce

```text
local max per PE
  -> gather/reduce through a declared DFU3500 PE route or PE00 reducer
  -> materialize scalar in explicit SRAM/SPM scratch
  -> broadcast/read scalar to participating PEs
  -> postprocess/store
```

Pros:

```text
matches B-line collective semantics directly
turns LogicalReduceEdge into a target strategy instead of symbolic debt
can be narrow and DFU3500-specific
```

Cons:

```text
requires route/reduce ordering, scalar scratch ownership, broadcast/readback,
and template support to be proven in B-line binary path
```

Decision:

```text
Primary customer-delivery path.
Implement the smallest DFU3500-specific allreduce strategy that satisfies the
B-line collective semantics; do not wait for a generic collective framework.
```

#### Strategy B: PE00 aggregate and materialize as allreduce strategy

```text
subtask1:
  each PE computes local max and writes local max to scratch

subtask2:
  PE00 reads local maxima, reduces to global max, writes scalar scratch

subtask3:
  all PEs read scalar scratch, recompute local log tile, postprocess/store
```

Pros:

```text
closer to real collective
uses staged memory instead of full allreduce route
can be the first implementation of Strategy A if represented as a declared
allreduce strategy, not as an ad hoc fallback
```

Cons:

```text
needs multi-subtask scratch protocol and PE00 special template
```

Decision:

```text
Allowed as the minimum physical allreduce implementation when the strategy
record explicitly says:
  collective_strategy = pe00_aggregate_materialize_allreduce
  visibility_kind = replicated_scalar
  scratch region = explicit
  broadcast/readback = explicit
```

#### Strategy C: redundant SPMD global max

```text
each PE independently scans the reduce domain
each PE computes the same global max
each PE postprocesses/stores its own output shard
```

Pros:

```text
no PE-to-PE route
no allreduce physical protocol
strong semantic match: replicated scalar by redundant computation
fastest correctness-first binary path
```

Cons:

```text
slow
more SRAM reads
may stress instruction/runtime duration for full-size input
```

Decision:

```text
Internal bring-up path only unless the customer explicitly accepts it.
It may be used to debug elementwise/log/reduce templates, but it is not the
default customer-delivery definition of "B-line allreduce implemented".
```

Reduced shape is acceptable only as an internal bring-up artifact unless the
customer explicitly accepts it as the first-version deliverable.

### 6.1 log10max Capacity And Visibility Proof

Before writing the log10max bridge, attach a capacity proof:

```text
required customer shape:
  input shape
  output shape
  dtype
  tile shape
  PE sharding

memory visibility:
  which PEs can read each input shard
  local-max scratch region
  global scalar scratch region
  broadcast/readback visibility

binary capacity:
  estimated instruction rows
  task/subtask/exeBlock rows
  component file sizes
  scratch bytes
  runtime launch count

decision:
  selected collective_strategy
  rejected strategies and exact trigger
```

Fallback triggers must be concrete:

```text
minimum physical allreduce -> PE00 aggregate flavor:
  if direct route/reduce/broadcast template evidence is insufficient by
  2026-06-25 12:00 Asia/Shanghai

PE00 aggregate flavor -> redundant SPMD bring-up:
  only for internal smoke or explicit customer waiver

reduced shape:
  internal_bringup_shape unless customer accepts it in writing
```

### 6.2 log10max Numerical Contract

Any numerical claim must state:

```text
dtype:
  input/output/scalars

constants:
  clamp_min = 1.0e-10
  log10(2) = 0.30102999566...
  floor_offset = -8.0
  add = 4.0
  mul = 0.25

domain:
  clamp happens before log
  zero/negative input policy
  NaN/Inf policy

tolerance:
  absolute tolerance
  relative tolerance
  ULP or percentile tolerance if used
```

### 7. B-line Collective Model

The current programming model should keep allreduce as a first-class concept:

```text
LogicalReduceEdge
  reduce_op = max
  participants = processors
  visibility_kind = replicated_scalar

TileCollectiveBundle
  collective_kind = all_reduce_max_symbolic
```

For V1 delivery, the lowering may choose a target strategy:

```text
collective_strategy:
  dfu3500_min_physical_allreduce
  pe00_aggregate_materialize_allreduce
  redundant_spmd_recompute_internal_only
```

Important:

```text
These strategies are implementations of the same B-line collective semantics.
They must not erase the logical allreduce from the IR.
Only the first two can satisfy the default customer-delivery definition of
B-line allreduce implemented.
```

### 8. Tactical Bridge Provenance

Any tactical bridge used for this delivery must emit a provenance record:

```python
TacticalBindingRecord:
  bridge_id: str
  operator: str
  semantic_source_plan_id: str
  template_evidence_id: str
  selected_strategy: str
  emitted_rows: tuple[str, ...]
  unresolved_fields: tuple[str, ...]
  assumptions: tuple[str, ...]
```

Gate rule:

```text
unresolved_fields non-empty -> not uploadable
assumptions must enter package report
bridge_id must enter customer bundle metadata
byte writer must not inspect frontend ops directly
```

### 9. `inst_t` Writer Field Contract

The first `inst_t` writer may use narrow template-backed encoding, but must
classify every field:

```text
must be source-backed or template-backed:
  opcode
  unit_inst_type
  source operand indices
  destination operand indices
  immediate constants
  predicate / valid / end flags
  stage PC / next relation if present
  PE position / route endpoint fields used by template
  data type / execution unit selection
  memory/store fields for store templates

may be zero-filled:
  confirmed padding
  unused operands for this template
  fields where vendor evidence shows zero in the equivalent template

forbidden:
  unknown semantic fields
  symbolic_unresolved fields
```

If the writer uses legacy rows as a skeleton, it must report:

```text
binding_mode = raw_template_overlay
template_row_sha256 = <sha256>
patched_fields = [...]
unpatched_fields_policy = source_evidence_same_template
```

### 10. Customer Bundle Metadata

Each bundled operator must include an honest status label:

```json
{
  "operator": "log10max",
  "delivery_state": "uploadable",
  "runtime_status": "simict_executes",
  "numerical_status": "not_checked",
  "lowering_strategy": "pe00_aggregate_materialize_allreduce",
  "shape": "64x512",
  "is_customer_shape": true,
  "known_limitations": [],
  "profile_id": "dfu3500...",
  "cbuf_sha256": "...",
  "micc_sha256": "..."
}
```

Reduced-shape payloads must be labeled:

```text
internal_bringup_shape = true
customer_deliverable = false
```

## Invariants

1. B-line semantic records remain the source of truth.
2. Byte writers serialize only already-decided component rows.
3. ReLU cannot be silently dropped from GEMM+ReLU.
4. log10max cannot erase `reduce_max`; default customer delivery must lower it
   to a declared DFU3500 allreduce strategy.
5. All scratch/materialized scalar regions must be explicit SRAM/SPM regions.
6. `instances_conf_mem_based_addr` unit must be explicit and byte-based unless
   new vendor evidence proves otherwise.
7. Expanded and folded GEMM views must not be mixed implicitly.
8. Tactical compatibility bridges may consume existing template evidence, but
   they do not become semantic authority.
9. First operator delivery may be inefficient; it must be inspectable and gated.
10. Runtime-ready gate must pass before any artifact is called uploadable.
11. No generic CUDA/CANN/multi-backend abstraction work belongs in this phase.

## Alternatives Considered

### A. Finish B-line enhancements first

Rejected for now.

This improves architecture but delays customer-visible binaries.

### B. Use old backend as the only delivery path

Rejected as the main direction.

Old backend evidence is useful for templates and struct layout, but making it
the sole path would strand B-line progress and reintroduce hidden state.

### C. Force folded GEMM rows before any binary

Deferred.

Folded rows reduce row count, but expanded B-line rows are currently easier to
debug.  Use folded k-stream only if vendor repeat semantics require it for the
first runnable binary.

### D. Finish generic allreduce before log10max V1

Deferred.

The model can express allreduce, and log10max V1 must implement a minimum
DFU3500 allreduce strategy.  What is deferred is the generic, optimized,
multi-strategy collective framework.

## Migration / Implementation Plan

### Phase 0: Freeze Enhancement Work

Pause:

```text
generic mixed-region fold planner
full op-spec/folding cleanup
folded component default migration
generic/optimized allreduce physical route
schema cleanup that does not unblock binary emission
```

Continue only if it directly unblocks the first three operators.

### Phase 1: Finish GEMM Binary Writers, due 2026-06-23

Work items:

```text
1. Resolve instances_conf_mem_based_addr.
2. Add task_conf_info_t writer.
3. Add exeBlock_conf_info_t writer.
4. Add sub_task_conf_info_t writer embedding exeBlock rows.
5. Add inst_t writer from current instruction/template rows.
6. Add final CBUF/MICC assembly.
```

Expected output:

```text
gemm_no_relu uploadable package
```

### Phase 2: GEMM+ReLU Concrete Template, due 2026-06-24

Work items:

```text
1. Bind epilogue:relu to concrete IMM/FMAX or equivalent template.
2. Choose fused finalize/store or explicit ReLU subtask.
3. Ensure ReLU TemplateOps become concrete_template.
4. Ensure GEMM+ReLU no longer fails closed.
5. Reuse Phase 1 component writers.
```

Expected output:

```text
gemm_relu uploadable package with concrete ReLU binding
```

### Phase 3: log10max V1 Semantic-to-Binary Bridge, due 2026-06-25

Work items:

```text
1. Complete capacity/memory visibility proof for the customer shape.
2. Choose V1 reduce strategy:
     primary = dfu3500_min_physical_allreduce
     allowed first implementation = pe00_aggregate_materialize_allreduce
     internal bring-up only = redundant_spmd_recompute_internal_only
3. Add log10max delivery profile:
     clamp_min
     log10 as FLOG2 * log10(2)
     local reduce_max
     declared allreduce strategy
     maximum
     add_scalar
     mul_scalar
     store
4. Add elementwise/reduce/allreduce template intents for the needed ops only.
5. Produce component rows through the same writer path.
6. Archive runtime_ready report and bundle metadata.
```

Expected output:

```text
log10max uploadable package with declared DFU3500 allreduce strategy
```

### Phase 4: Integration Buffer And Customer Bundle, due 2026-06-26

Work items:

```text
1. Put GEMM, GEMM+ReLU, and log10max uploadable packages in one handoff bundle.
2. Keep package reports explicit about selected lowering strategy.
3. Label runtime/numerical/shape status for each operator.
4. Fix only delivery-blocking issues.
5. Do not reopen generic B-line enhancement work.
```

Expected output:

```text
customer-facing first-version three-operator bundle with honest status labels
```

### Deferred Phase: Generalize log10max Allreduce

Only after V1 works:

```text
pe00_aggregate_materialize_allreduce or dfu3500_min_physical_allreduce
  -> generic route/reduce/broadcast planner
  -> optimized collective scheduling
```

This phase is performance and generality improvement, not permission to leave
V1 symbolic.

## Bring-up Checks

These are engineering checks, not a request to expand validation framework work.

```text
GEMM:
  component files exist
  row counts match package profile
  no unresolved TemplateOps
  no writer emits from symbolic_unresolved rows
  runtime_ready gate passes

GEMM+ReLU:
  epilogue:relu concrete count = expected tile count
  no ReLU TemplateOp remains symbolic_unresolved
  store consumes ReLU output, not pre-ReLU accumulator value
  runtime_ready gate passes

log10max:
  reduce_max remains visible in semantic/source plan
  selected collective_strategy is explicit
  selected strategy is a DFU3500 allreduce strategy unless customer waiver
  scratch/global_max storage region is explicit if used
  all elementwise scalar constants are explicit
  capacity/memory visibility proof exists
  runtime_ready gate passes
```

## Risks and Mitigations

### Risk: inst_t writer becomes the long pole

Mitigation:

```text
Start from the smallest existing template-bound instruction shape.
Do not implement a general instruction encoder in this RFC.
```

### Risk: ReLU operand lifetime is unclear

Mitigation:

```text
Prefer explicit ReLU subtask if fused finalize/store creates ambiguity.
```

### Risk: log10max minimum allreduce route is not proven fast enough

Mitigation:

```text
Use pe00_aggregate_materialize_allreduce as the first minimum implementation.
Use redundant_spmd only for internal bring-up or explicit customer waiver.
Do not call a symbolic-only reduce path delivered.
```

### Risk: tactical bridges pollute B-line semantics

Mitigation:

```text
Mark bridges as target delivery adapters.
Keep provenance from B-line records.
Do not let byte writers inspect frontend ops directly.
```

### Risk: expanded vs folded GEMM mismatch

Mitigation:

```text
Pick one representation for first binary.
Print the selected representation in package report.
Do not silently mix expanded exeBlocks with folded instances_amount.
```

## Expected Effect

After Phase 1:

```text
GEMM has a concrete binary-lowering path.
```

After Phase 2:

```text
GEMM+ReLU uses the same path plus concrete local epilogue.
```

After Phase 3:

```text
log10max has a correctness-first binary path with a declared DFU3500 allreduce
strategy.
B-line keeps allreduce semantics visible and no longer leaves reduce_max as
symbolic-only debt for the first customer operator.
```

The project then has three customer-facing operator binaries and can return to
cleaning up folded rows, generic allreduce routing, and generic op lowering.

## Open Questions

1. Which minimum DFU3500 allreduce implementation is feasible fastest for the
   required customer shape: direct route/reduce/broadcast or PE00 aggregate?
2. If a reduced log10max shape is needed for internal bring-up, what is the
   separate full-shape path for the customer deliverable?
3. For GEMM first binary, is expanded k-stream acceptable, or does SimICT
   require folded `instances_amount` semantics immediately?
4. Should GEMM+ReLU ReLU be a fused finalize/store template or an explicit
   subtask?
5. Which existing template evidence is sufficient for the initial `inst_t`
   writer, and which fields still require manual binding?

## Recommended Decision

Approve this delivery-first plan:

```text
P0:
  finish GEMM binary writers

P0:
  bind concrete GEMM+ReLU epilogue

P0:
  implement log10max V1 with explicit DFU3500 allreduce strategy, using the
  smallest target-specific path that satisfies B-line collective semantics

Frozen until delivery:
  resume B-line enhancements after the three operator binaries exist
```

This keeps the B-line programming model intact, acknowledges that it can
represent allreduce-like collectives, requires the first log10max delivery to
lower that collective into an explicit DFU3500 strategy, and still respects the
customer need for fast operator delivery.
