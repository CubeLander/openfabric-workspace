# RFC: Fiber Structure Owns Loop Folding

## Status

RFC-level: accepted.

Implementation-level: accepted with hard gates.

This RFC responds to the review objection raised on 2026-06-21:

```text
MatMul op spec should not care about loop-body structure.  Loop-body folding
should be operator-independent and should depend only on the stream/fiber
structure.
```

The objection is accepted.  The current B-line op-spec migration pushed too much
stream/fiber scheduling vocabulary into `MatmulOpSpec`.  This RFC corrects that
boundary.

Review decision:

```text
RFC-level: Accept.
Implementation-level: Accept with hard gates.
```

Accepted review changes in this revision:

```text
1. Replace op-spec "carried state" with reduction / recurrence semantics.
2. Replace "materialized A/B" wording with logical fragment/value wording.
3. State that FiberPatternPlan may propose repetition but cannot prove folding.
4. Define normalized fold body signatures and alpha-renaming requirements.
5. Require typed schedule/dependency metadata instead of higher-level role strings.
6. Reorder migration: add new bridge first, switch MatMul, then remove old APIs.
7. Strengthen static checks across op specs, folding, and backend projection.
8. Clarify that schedule validation status is a precondition, not fold proof.
9. Add axis/K boundary rules: K must not become a folding-planner special case.
10. Replace single-kind schedule enums with typed semantics plus traits.
11. Require poison tests for deprecated phase APIs.
12. Add binary policy schema guards.
13. Mark generic mixed-region fold planning as a follow-up research item.
14. Forbid folding/backend proof shortcuts through `graph_kind` or axis names.
15. Require explicit reduction numeric and ordering policy.
16. Split loop uniformity proof from target projection eligibility.
17. Require schedule validation status to come from a verifier.
18. Require carry-chain correctness, not only `REDUCTION_CARRY` counts.
19. Version the binary policy schema.
```

## Summary

`MatmulOpSpec` may describe MatMul semantic access relations:

```text
A(m,k), B(k,n), accumulator(m,n,k-1) -> accumulator(m,n,k)
```

It must not describe stream schedule phases such as:

```text
pre_loop
loop_body
post_loop
fold_scope=stream_subtask_loop
body_roles=(...)
```

Those are properties of the materialized fiber/schedule structure, not of the
MatMul operator contract.

The corrected direction is:

```text
OpSpec semantic access contract
  -> fiber builder chooses and materializes a Fiber structure
  -> schedule builder emits raw schedule facts
  -> schedule verifier validates construction, binding, and resources
  -> folding analyzer proves repeated structure from validated schedule facts
  -> target/backend proves projection eligibility and emits vendor rows
```

Loop folding is therefore operator-independent.  MatMul can create a repeated
fiber shape, but it does not own the folding method.

## Current State

### Current op spec descriptors

`compiler/gpdpu_compiler/core/op_specs/matmul.py` currently exposes:

```text
fiber_graph_profile()
  graph_kind = sequential_k_matmul
  steps:
    accumulator_prepare phase=pre_loop
    materialize_A       phase=loop_body repeat_axis=k_block
    materialize_B       phase=loop_body repeat_axis=k_block
    gemm_update         phase=loop_body repeat_axis=k_block
    finalize_accumulator phase=post_loop
    epilogue_relu        phase=post_loop
    store_fragment       phase=post_loop

folding_profile()
  fold_scope = stream_subtask_loop
  loop_axis = k_block
  invariant_roles = (...)
  body_roles = (...)
  post_loop_roles = (...)
```

This makes `MatmulOpSpec` aware of loop-body placement and folding policy.

### Current fiber builder

`compiler/gpdpu_compiler/core/stream_compiler/fiber.py` now accepts
`FiberGraphProfile` in `build_sequential_k_fiber()`.  It validates the MatMul
profile and uses profile step order to emit:

```text
materialize_A -> materialize_B -> gemm_update
```

This was intended as a source-of-authority migration, but it exposed the wrong
authority boundary: the operator spec is becoming the schedule/fiber pattern
owner.

### Current folding analyzer

`compiler/gpdpu_compiler/core/stream_compiler/folding.py` is closer to the
correct model.  It consumes `FiberExecutionSchedule` and groups schedule steps by
stream, phase, loop axis, and loop instance key.  It proves:

```text
loop body exists
more than one loop instance exists
all loop instances have the same shape
all loop-body roles are proven
```

However, it still contains some role-string heuristics:

```text
materialization_action_count:
  role startswith operand_materialize or operand_route_recv

carried_dependency_count:
  role == compute_core:gemm_update and dependency mentions gemm_update
```

These should also become structure/provenance based rather than MatMul-role
based.

## Problem

The current design collapses three distinct authorities:

```text
operator semantics
fiber materialization strategy
loop folding proof
```

That creates several failures:

1. `MatmulOpSpec` starts describing an executable schedule, not only MatMul
   semantics.
2. Adding another operator would require it to describe `pre_loop` /
   `loop_body` / `post_loop`, even when those phases are a chosen fiber
   materialization strategy.
3. Loop folding becomes a property that operators declare, rather than a proof
   derived from repeated fiber structure.
4. The compiler can no longer compare two different materializations of the
   same operator, because the schedule shape is baked into the op spec.
5. The B-line pipeline risks recreating the old cross-layer state problem under
   cleaner dataclass names.

The main bug is conceptual:

```text
MatMul has a K recurrence.
MatMul does not have a "loop_body phase" in the compiler pipeline.
```

`loop_body` exists only after a fiber builder chooses to materialize that
recurrence as a repeated stream-local schedule.

## Goals / Non-goals

### Goals

1. Remove loop phase and fold policy authority from op specs.
2. Keep operator specs useful for operator semantics and access relations.
3. Make loop folding a generic proof over `FiberExecutionSchedule`.
4. Keep current GEMM B-line report counts stable during the migration.
5. Preserve explicit reduction / recurrence semantics, but move schedule-carried
   dependency ownership to fiber/schedule structures.

### Non-goals

1. Do not remove MatMul-specific fiber construction immediately.
2. Do not make a fully generic fiber expander in one patch.
3. Do not change DFU3500 binary layout or vendor serializers in this RFC.
4. Do not make elementwise/reduce runnable as part of this correction.

## Proposed Design

### 1. Separate operator access contracts from fiber patterns

Operator specs may expose an access contract like:

```python
@dataclass(frozen=True)
class OperatorAccessProfile:
    op_name: str
    fragment_spaces: tuple[FragmentSpaceProfile, ...]
    relations: tuple[AccessRelationProfile, ...]
    reductions: tuple[ReductionProfile, ...] = ()
```

For MatMul, this can say:

```text
fragment spaces:
  A_tiles(m_tile, reduction_fragment)
  B_tiles(reduction_fragment, n_tile)
  C_acc_tiles(m_tile, n_tile, reduction_fragment)
  C_tiles(m_tile, n_tile)

relations:
  accumulator initial value exists for C(m,n)
  A_tile(m,k) is an input to update(m,n,k)
  B_tile(k,n) is an input to update(m,n,k)
  update consumes reduction_state(m,n,k-1), A_tile(m,k), B_tile(k,n)
  update produces reduction_state(m,n,k)
  C_tile(m,n) is derived from final reduction_state

reduction:
  axis = k
  identity = zero
  update = acc + A * B
  output = reduce over k
```

This is still operator-local semantic information.

It must not say:

```text
phase = loop_body
repeat_axis = k_block
fold_scope = stream_subtask_loop
body_roles = (...)
```

It also must not say:

```text
carried dependency over k_block
materialize A
materialize B
route A/B
```

`carried dependency` and `materialization` are facts created by a chosen fiber
pattern.  The operator owns the reduction relation; the schedule owns any
carried dependency edge that materializes that relation.

A safer reduction descriptor is:

```python
@dataclass(frozen=True)
class ReductionProfile:
    axis: str
    identity: ValueExpr
    update_relation: AccessRelationProfile
    output_relation: AccessRelationProfile
    numeric_policy: NumericPolicy
    ordering: OrderingPolicy
    associativity: AssociativityPolicy
```

`ordering` is required.  If the implementation needs a default for the current
MatMul path, use an explicit policy such as:

```text
OrderingPolicy.STRICT_SEQUENTIAL
```

`NumericPolicy` must carry target-observable numeric facts, at least:

```text
input dtype
accumulator dtype
rounding mode
saturation / overflow behavior
allowed reassociation
determinism requirement
```

Fold proof does not imply reassociation permission.  Any transform that changes
reduction order, accumulator precision, rounding, or saturation behavior must
be separately authorized by numeric policy and legacy byte review.

The fiber builder may later decide:

```text
this reduction is materialized as a sequential reduction-region dependency
```

That decision does not belong to `MatmulOpSpec`.

Axis naming must also stay layered:

```text
mathematical axis:
  k

logical fragment axis:
  reduction_fragment or any local fragment coordinate chosen by tiling

materialized schedule axis:
  region_instance_key / repeated_region coordinate owned by FiberExecutionSchedule

backend projection name:
  vendor K-loop / instances_amount / target-specific row field, if needed
```

`OperatorAccessProfile` may mention a mathematical reduction axis.  It may also
mention logical tiled fragment coordinates if the profile is explicitly a tiled
semantic contract.  Those names must not imply:

```text
loop_instance_key
phase placement
schedule-carried dependency edges
fold body identity
```

The long-term ideal is stronger:

```text
K is internalized into fiber partitioning and topology.
The fold planner does not need explicit K, or even an implicit K convention.
It sees repeated structure over normalized fiber-region coordinates.
Only subtask/backend projection may reintroduce a target-facing K-like loop name.
```

After fiber construction, the planner should not carry a privileged axis called
`K` forward.  If a MatMul reduction becomes four repeated fiber partitions, the
fold planner should observe four normalized region instances with equivalent
body signatures.  It should not ask whether those instances came from `k`,
`k_block`, `reduction_fragment`, or any operator-specific axis name.

### 2. Move fiber schedule phases to fiber pattern plans

The stream compiler may generate an internal fiber pattern plan:

```python
@dataclass(frozen=True)
class FiberPatternPlan:
    graph_kind: FiberPatternKind | TransitionalPatternId
    pre_region: tuple[FiberPatternStep, ...]
    repeated_regions: tuple[FiberRepeatedRegion, ...]
    post_region: tuple[FiberPatternStep, ...]
```

`graph_kind` is construction metadata only.  It may guide fiber construction,
diagnostics, retirement tracking, or backend projection naming.  Folding
analyzers and backend serializers must not branch on:

```text
graph_kind == "sequential_k_matmul"
axis == "k"
axis == "k_block"
```

If a string-valued transitional id remains during migration, wrap it in metadata
that makes its temporary status auditable:

```python
@dataclass(frozen=True)
class TransitionalPatternId:
    name: str
    owner: str
    retirement_condition: str
    allowed_consumers: tuple[str, ...]
```

The current `pre_region / repeated_regions / post_region` shape is also
transitional.  It is a construction model for the current GEMM path, not the
long-term generic region model.  Generic mixed-region planning should move
toward a region DAG or region tree once the first boundary repair is complete.

For the current GEMM path, the stream compiler can still have a transitional
MatMul-specific builder:

```text
OperatorAccessProfile(MatMul)
  -> build_sequential_k_fiber_pattern(...)
  -> FiberPatternPlan
  -> materialized FiberOps
```

The important change is ownership:

```text
MatmulOpSpec owns access relations.
stream_compiler owns "this relation is materialized as a loop body".
```

`FiberPatternPlan` is a construction plan, not a proof artifact:

```text
FiberPatternPlan:
  may propose repeated regions;
  may guide FiberOp construction;
  must not be consumed as evidence that folding is valid.

FiberExecutionSchedule:
  is the materialized fact table.

LoopUniformityProof:
  is derived from the normalized schedule/dependency graph.
```

In short:

```text
pattern can suggest structure;
schedule is the fact;
fold proof grows from facts only.
```

### 3. Make folding prove repeated regions from schedule structure

`analyze_stream_loop_folding(schedule)` should not consume an op-specific
`folding_profile()`.  It should also not consume unverified builder claims.

The schedule lifecycle is:

```text
RawFiberExecutionSchedule
  -> verify_schedule(...)
  -> ValidatedFiberExecutionSchedule
  -> analyze_stream_loop_folding(...)
```

Schedule builders may emit raw schedule facts.  A schedule verifier owns
`ScheduleValidationStatus`.  Folding consumes only a
`ValidatedFiberExecutionSchedule`.

It should prove foldability from schedule facts:

```text
stream_id
phase / region id
candidate_region_id
region_instance_key
source_order_index
dependency kinds
step semantics
validation status
resource requirements
```

Here `validation status` does not mean "already foldable."  The schedule may
record construction and binding validation as preconditions:

```python
class ScheduleValidationStatus(Enum):
    CONSTRUCTED = auto()
    BINDING_VERIFIED = auto()
    RESOURCE_VERIFIED = auto()
```

The folding analyzer may require those statuses before attempting a fold proof.
It must not trust those statuses when they are self-reported by the builder.
It must not consume fields such as:

```text
is_foldable_hint
folding_proven
loop_body_proven
```

Schedule validation says the fact table is well formed.  Folding proves that the
well-formed facts contain a repeated foldable structure.

The proof must compare normalized candidate-body signatures rather than raw role
strings or instance-local ids:

```python
@dataclass(frozen=True)
class FoldBodySignature:
    step_kinds: tuple[ScheduleStepKind, ...]
    resource_kinds: tuple[ResourceKind, ...]
    dependency_topology: tuple[CanonicalEdge, ...]
    memory_spaces: tuple[MemorySpace, ...]
    semantic_categories: tuple[SemanticCategory, ...]
```

Loop uniformity and target projection eligibility are separate artifacts:

```python
@dataclass(frozen=True)
class LoopUniformityProof:
    uniformity_signature: FoldBodySignature
    region_instances: tuple[RegionInstanceKey, ...]
    dependency_proof: DependencyProof


@dataclass(frozen=True)
class TargetFoldProjectionProof:
    target: TargetId
    source_loop_proof_id: ProofId
    target_requirements: tuple[TargetRequirement, ...]
```

`LoopUniformityProof` answers whether the schedule contains a repeated
structure.  `TargetFoldProjectionProof` answers whether a target backend may
encode that structure using target-specific fields such as `instances_amount`.
Target requirements must not participate in the definition of whether a loop
exists.

Canonicalization must alpha-rename instance-local facts:

```text
region_instance_key values normalize to 0, 1, 2, ...
derived loop_instance_key values, if present, normalize equivalently
source_order_index normalizes inside the candidate body
instance-local op ids / row ids / component ids do not participate directly
concrete hashes or vendor row ids do not participate directly
```

`source_order_index` may be alpha-renamed, but the order model observed by the
serializer must be preserved.  Dependency topology proves partial order;
`source_order_index` may encode a chosen total order.  Fold equivalence must
compare the order information that is semantically or target-observably
significant.

This avoids both false negatives and false positives:

```text
same structure with different local ids       -> equal signature
same role strings with different dependencies -> different signature
```

The current shape already mostly does this.  The remaining role-string checks
should be replaced by generic metadata:

```text
materialization_action_count:
  count steps with schedule attrs/resource_kind indicating materialization

carried_dependency_count:
  count dependencies whose kind is REDUCTION_CARRY

requires_instance_base_rows:
  derived from resource requirements, not from operand role strings
```

This keeps folding operator-independent while still allowing MatMul to produce a
foldable repeated structure.

The `REDUCTION_CARRY` edge kind is not sufficient by itself.  Folding must prove
carry-chain correctness across region instances:

```text
1. every repeated instance except the first has a carry edge from the previous
   instance;
2. the first instance receives the reduction identity / initial state;
3. the final instance flows to the declared final output relation;
4. no skipped carry edges are allowed, such as instance 0 -> instance 2;
5. no duplicate producers may write the same accumulator state;
6. independent reduction states must not collapse into one carry chain.
```

`REDUCTION_CARRY` is an edge type.  Carry-chain correctness is a graph property.

The generic metadata must be typed.  It must not become another layer of string
roles.  A single enum value is also not enough, because one step can be compute,
reduction update, resource consumer, and target-template candidate at the same
time.

Use typed step semantics with traits:

```python
class ScheduleStepKind(Enum):
    INPUT_PROJECTION = auto()
    MATERIALIZATION = auto()
    ROUTE_RECV = auto()
    COMPUTE = auto()
    STORE = auto()
    EPILOGUE = auto()


class ScheduleStepTrait(Enum):
    REDUCTION_UPDATE = auto()
    ACCUMULATOR_CONSUMER = auto()
    ACCUMULATOR_PRODUCER = auto()
    CROSS_STREAM = auto()
    TARGET_TEMPLATE_CANDIDATE = auto()


@dataclass(frozen=True)
class ScheduleStepSemantics:
    primary_kind: ScheduleStepKind
    traits: frozenset[ScheduleStepTrait]
    resource_requirements: tuple[ResourceRequirement, ...]


class ScheduleDependencyKind(Enum):
    DATA = auto()
    CONTROL = auto()
    RESOURCE = auto()
    REDUCTION_CARRY = auto()
    INSTANCE_ORDER = auto()
```

Folding may read `ScheduleStepSemantics`, `ScheduleDependencyKind`, resource
requirements, and normalized dependency topology.  Folding must not read
operator-specific role strings such as `compute_core:gemm_update`, and it must
not import `MatmulOpSpec`.

The primary kind describes the action class.  Traits describe orthogonal facts
such as recurrence participation, accumulator use, cross-stream behavior, or
target projection readiness.  This avoids making every future op family add a
new primary kind just to preserve one operator-specific distinction.

### 4. Derive loops from processor / stream / fiber structure

The next design discussion should focus on this principle:

```text
Loops are not declared by op specs.
Loops are derived from repeated processor / stream / fiber structure.
```

A fold planner should start from what each materialized fiber step does:

```text
step kind
logical inputs / outputs
memory spaces
resource requirements
dependency edges
cross-stream dependencies
region-instance-local ids after normalization
```

It should then discover repeated regions from the schedule graph:

```text
FiberExecutionSchedule
  -> typed schedule steps
  -> typed dependency graph
  -> region discovery
  -> normalized body signatures
  -> repeated-region proof
  -> LoopUniformityProof
  -> TargetFoldProjectionProof, if a backend can encode it
  -> backend / subtask projection
```

For a pipeline such as:

```text
matmul -> collective -> matmul
```

the fold planner should not need to know that the first and third regions are
MatMul operators.  It should see structure:

```text
region A:
  stream-local repeated compute/update body
  normalized region-instance signatures are equivalent
  dependencies stay inside the repeated region except declared inputs/outputs
  => LoopUniformityProof A

region B:
  cross-stream collective / route / synchronization dependencies
  forms a region boundary
  may produce a CollectiveRegionProof, but is not part of region A or C's loop

region C:
  another stream-local repeated compute/update body
  independently proves LoopUniformityProof C
```

The backend projection then decides how those proofs map to runtime containers:

```text
LoopUniformityProof A        -> target projection candidate
CollectiveRegionProof B      -> collective / route subtask candidate
LoopUniformityProof C        -> target projection candidate
TargetFoldProjectionProof A  -> subtask / instance loop candidate
TargetFoldProjectionProof C  -> subtask / instance loop candidate
```

This makes subtask planning a downstream projection of proven structure, not the
source of folding truth:

```text
subtask is not the proof source;
subtask is one packaging form for proof results.
```

The open research item is therefore a generic fold planner that can segment a
mixed stream/fiber graph into repeated local regions, collective boundaries, and
post-collective repeated regions using only schedule facts.  Operator type may
influence how fibers were generated, but it must not participate in the folding
proof.

This generic mixed-region planner is a follow-up RFC / research item.  It should
not block phases 1-4 of this boundary repair.  The immediate migration should
prepare the required facts and proofs without committing to the full graph
segmentation algorithm.

### 5. Remove `folding_profile()` from operator specs

`LoopFoldingProfile` and `OperatorLoweringSpec.folding_profile()` should be
removed or marked deprecated immediately.

If a temporary compatibility report needs expected role groups, keep it in a
test fixture or stream-compiler validation helper, not in `core/op_specs`.

### 6. Replace `FiberStepProfile.phase` with semantic relation metadata

`FiberStepProfile.phase` and `repeat_axis` are schedule-placement fields.  They
should not live in operator-owned descriptor classes.

Short-term options:

```text
Option A:
  Move FiberStepProfile to stream_compiler/fiber_patterns.py.
  Rename op spec descriptor to AccessRelationProfile.

Option B:
  Keep class name temporarily but stop returning it from concrete op specs.
  Introduce OperatorAccessProfile beside it and migrate callers.
```

Recommended: Option A.  It makes the layer ownership visible in imports.

## Invariants

1. Operator specs do not mention `pre_loop`, `loop_body`, `post_loop`, or
   `fold_scope`.
2. Operator specs may describe reduction / recurrence semantics, but not how a
   recurrence is scheduled or carried between loop instances.
3. Fiber builders own materialized phase/region assignment.
4. Schedules own derived region / loop instance keys and phase/region rows.
5. Folding consumes schedule/fiber structure only; it does not ask the operator
   whether a loop is foldable.
6. Folding may use typed generic semantic categories or resource requirements,
   but not MatMul role strings as proof authority.
7. Vendor `instances_amount` / folded component rows are downstream projections
   of `TargetFoldProjectionProof`, not loop uniformity proof inputs.
8. Current expanded component rows remain authoritative until a folded writer is
   explicitly validated.
9. `FiberPatternPlan` may propose repeated regions, but folding must only trust
   the materialized `FiberExecutionSchedule` and normalized dependency graph.
10. Backend/vendor serializers must not decide foldability; they may only
    consume explicit loop uniformity and target projection proofs.
11. Schedule validation status is not fold proof.  It is only a precondition for
    running fold analysis.
12. Mathematical axis names such as `k` must not be used as fold planner
    special cases.  Fold discovery operates on normalized fiber-region
    coordinates and dependency topology.
13. Schedule step metadata uses typed semantics plus traits; free-form category
    strings are not proof authority.
14. `graph_kind` and operator-origin axis names may be retained for diagnostics
    and projection naming, but they are not proof authority.
15. The `pre/repeated/post` pattern shape is transitional; the durable generic
    model is discovered region structure, not a fixed three-part template.
16. Reduction profiles carry explicit numeric and ordering policy.  Fold proof
    does not authorize numeric reassociation.
17. Schedule validation status is produced by a verifier.  Builders do not
    validate themselves.
18. Loop uniformity proof and target projection eligibility are separate
    artifacts.
19. A `REDUCTION_CARRY` edge type is not a carry-chain proof.  Folding must
    prove the chain topology.
20. `source_order_index` may be normalized only if target-observable order
    semantics are preserved.

## Alternatives Considered

### Alternative A: Keep loop phases in MatMul op spec

Rejected.

This makes the op spec a schedule template.  It may work for GEMM, but it would
force every future operator to carry B-line implementation phases in its
operator contract.

### Alternative B: Keep `folding_profile()` as a hint only

Rejected for now.

Even a hint creates pressure for folding to ask the operator for permission.
The foldability question should be answered by the materialized fiber structure.

### Alternative C: Move all fiber construction into op specs

Rejected.

That would create operator-owned mini backends and violate the compiler
layering principle.

### Alternative D: Let folding keep role-string heuristics temporarily

Deferred only as migration scaffolding.

The current role-string heuristics can remain for one compatibility checkpoint,
but they must be tracked as debt and replaced with schedule/resource metadata.

## Migration / Implementation Plan

### Phase 0: Freeze the boundary correction

1. Add this RFC.
2. Mark the previous B-line op-spec RFC sections about `fiber_graph_profile()`
   phases and `folding_profile()` as superseded by this RFC.
3. Stop advancing op-spec-owned loop-body migration.

### Phase 1: Add the new bridge without deleting old APIs

1. Add `OperatorAccessProfile` and `ReductionProfile` under `core/op_specs`.
2. Add `stream_compiler/fiber_patterns.py` with `FiberPatternPlan`.
3. Add typed `ScheduleStepKind` and `ScheduleDependencyKind`.
4. Add `ScheduleStepSemantics` / `ScheduleStepTrait` and typed resource
   requirements.
5. Add explicit `NumericPolicy` and required `OrderingPolicy` for reductions.
6. Add `RawFiberExecutionSchedule`, `ValidatedFiberExecutionSchedule`, and a
   verifier-owned `ScheduleValidationStatus`.
7. Keep current old APIs in place but mark `folding_profile()` and
   phase-carrying `FiberStepProfile` as deprecated migration artifacts.
8. Keep all current B-line checks green.

### Phase 2: Switch current MatMul builder to stream-owned pattern

1. `build_sequential_k_fiber()` creates/consumes a stream-owned
   `FiberPatternPlan`.
2. `MatmulOpSpec` provides reduction/access semantics only.
3. The builder no longer trusts `MatmulOpSpec` phase fields.
4. `MatmulOpSpec` may temporarily expose old phase APIs only for compatibility,
   with checks proving the new path does not depend on them.
5. Add poison tests proving deprecated phase APIs are not trusted:

   ```text
   deprecated fiber_graph_profile may raise;
   deprecated phase data may return wrong order;
   build_sequential_k_fiber still uses stream-owned FiberPatternPlan;
   generated schedule remains unchanged.
   ```

6. Keep folding counts and binary-plan counts unchanged.

### Phase 3: Remove op-spec-owned fold/phase APIs

1. Remove `folding_profile()` from `OperatorLoweringSpec`.
2. Remove `LoopFoldingProfile` returns from `MatmulOpSpec` and
   `ElementwiseFamilySpec`.
3. Stop returning `FiberStepProfile(phase=...)` from concrete op specs.
4. Add static bans for `pre_loop`, `loop_body`, `post_loop`, `fold_scope`, and
   `body_roles` in `core/op_specs`.
5. Update `check_op_specs_strategy_profiles.py` so role/folding validation is
   not based on op spec fold groups.

### Phase 4: Make folding role-independent

1. Add generic schedule metadata for:
   - materialization;
   - compute/update;
   - store;
   - reduction-carry dependency;
   - resource/base-row requirement.
2. Replace role-prefix checks in `folding.py` with that metadata.
3. Replace reduction-carry counts with carry-chain topology proof.
4. Produce `LoopUniformityProof` before any target projection proof.
5. Keep the same fold candidate counts for GEMM.

### Phase 5: Revisit generic fiber expansion

Only after phases 1-4:

1. Decide whether the stream compiler needs a generic access-profile expander.
2. Keep `sequential_k_matmul` as an explicit transitional pattern until a second
   non-MatMul repeated fiber proves the abstraction.

## Validation Plan

### Static checks

Add focused checks.  These must not be grep-only checks.

AST import checks:

```text
core/op_specs must not import:
  stream_compiler
  FiberExecutionSchedule
  FiberPatternPlan
  LoopFoldingProfile

stream_compiler/folding.py must not import:
  core/op_specs/<operator>.py
  MatmulOpSpec
  ElementwiseFamilySpec

backend/vendor serializer code must not decide foldability;
it may only consume LoopUniformityProof / TargetFoldProjectionProof artifacts.
```

AST attribute/string checks:

```text
core/op_specs must not contain:
  phase="loop_body"
  phase="pre_loop"
  phase="post_loop"
  fold_scope=
  body_roles=
  FiberPatternPlan
  FiberExecutionSchedule
  LoopFoldingProfile
  k_block as a schedule loop marker
```

Text grep may remain as an auxiliary check for non-Python snapshots or config
files, but not as the primary proof.

Allowlist:

```text
negative tests may contain forbidden strings only under tests/static_negative/
RFC docs may contain forbidden strings
stream/fiber/schedule modules may contain schedule-owned terms
```

`folding.py` must also fail checks if it branches on:

```text
graph_kind == "sequential_k_matmul"
axis == "k"
axis == "k_block"
```

Deprecated API poison checks:

```text
During Phase 2, deprecated op-spec phase APIs must be poison-testable.
The MatMul stream-owned builder must continue to produce identical schedules
when those old APIs are unavailable or deliberately return invalid phase data.
```

Binary policy schema checks:

```text
program_bin_rows["binary_policy"] must have an explicit versioned schema:
  schema_version = "binary_policy.v1"

Compatibility diagnostics must not appear in production binary policy fields
unless the schema is updated by review.

Debug/report-only fields belong under:
  binary_policy            production serializer contract
  debug_policy
  report_only_policy       readiness / planned behavior
  compat_diagnostics
```

### Behavior checks

Existing B-line checks must remain stable:

```bash
python compiler/tools/check_stream_compiler_projection.py
python compiler/tools/check_stream_compiler_executable.py
python compiler/tools/check_stream_compiler_role_binding.py
python compiler/tools/check_stream_compiler_template_ops.py
python compiler/tools/check_stream_compiler_binary_plan.py
python compiler/tools/check_stream_compiler_folding.py
python compiler/tools/check_stream_compiler_no_relu_safe_subset.py
```

Expected GEMM counts should remain:

```text
fibers=64
blocks=1024
executable_ops=1024
bindings=1024
instruction_rows=896
zero_boundaries=64
fold_candidates=64
```

### Legacy byte stability

This RFC fixes B-line ownership boundaries.  It does not authorize changes to
the legacy GEMM byte stream.

Validation rule:

```text
B-line may add fold proof / binary writer readiness reports.
B-line must not silently change A-line legacy golden hashes.
```

If a legacy CBUF/MICC/vendor blob hash changes, the change must be handled as a
separate ABI/golden update:

```text
1. show the byte diff;
2. explain the changed field semantics;
3. explicitly update the golden only after review.
```

### Negative checks

1. A new operator spec that declares `phase="loop_body"` must fail.
2. A folding analyzer that imports `core/op_specs/<operator>.py` must fail.
3. A fold candidate whose loop instances differ structurally must be rejected
   without consulting the operator.
4. A reduction-carry fold count must be derived from dependency metadata, not a
   role named `gemm_update`.
5. Two loop instances with alpha-equivalent ids but identical normalized
   topology must compare equal.
6. Two loop instances with the same role strings but different dependency
   topology must compare unequal.
7. A schedule entry with `folding_proven=True` or similar hint must fail schema
   validation.
8. A fold planner branch that special-cases an axis named `k` or `k_block` must
   fail static checks.
9. A fold planner branch that special-cases
   `graph_kind == "sequential_k_matmul"` must fail static checks.
10. A builder-created schedule with self-reported `RESOURCE_VERIFIED` status
    must be rejected unless it passed the verifier.
11. A missing carry edge must fail fold proof.
12. A skipped carry edge must fail fold proof.
13. A duplicate carry producer must fail fold proof.
14. A carry chain with the same role strings but wrong topology must fail fold
    proof.
15. A source-order mismatch that is target-observable must fail fold equivalence.
16. A binary policy report with unreviewed compatibility fields must fail schema
   validation.
17. A `binary_policy` report without `schema_version = "binary_policy.v1"` must
    fail schema validation.

## Risks and Mitigations

### Risk: Losing useful MatMul structure

Mitigation:

Keep MatMul recurrence in the operator access profile.  Remove only schedule
phase ownership.

### Risk: The fiber builder becomes too MatMul-specific again

Mitigation:

Allow `sequential_k_matmul` as an explicit transitional fiber pattern with
retirement metadata.  Do not disguise it as generic.

### Risk: `graph_kind` becomes a new role string

Mitigation:

Keep graph-kind provenance for construction, diagnostics, and retirement
tracking only.  Static checks must reject folding or backend serializer branches
on `graph_kind == "sequential_k_matmul"`.

### Risk: Folding loses target-relevant information

Mitigation:

Move target-relevant facts into generic schedule/resource metadata before
removing role heuristics.

Keep target projection eligibility separate from loop uniformity proof.  A
different backend may reject projection without changing whether the schedule
contains a repeated region.

### Risk: Generic metadata becomes disguised role strings

Mitigation:

Use typed enums/dataclasses for step kinds, dependency kinds, resource
requirements, and fold signatures.  Do not encode fold authority in free-form
strings.

### Risk: K becomes an implicit folding convention

Mitigation:

Keep `k` as a mathematical reduction-axis name only.  Normalize fiber-region
coordinates before folding.  Reintroduce target-facing K-like names only during
subtask/backend projection.

### Risk: Schedule validation becomes self-certification

Mitigation:

Use a verifier-owned `ValidatedFiberExecutionSchedule` type.  Builders may emit
facts, but they do not certify construction, binding, or resource validity.

### Risk: Carry counts replace carry-chain proof

Mitigation:

Treat `REDUCTION_CARRY` as edge metadata only.  Folding must prove adjacent
chain topology, identity/init entry, final output flow, and absence of skipped
or duplicate producers.

### Risk: Fold proof is mistaken for numeric rewrite permission

Mitigation:

Require explicit `NumericPolicy` and `OrderingPolicy`.  Structural folding does
not permit reassociation, precision changes, rounding changes, saturation
changes, or byte-stream changes without separate authorization.

## Expected Effect

After this correction:

```text
MatMul op spec:
  says what logical values relate to what logical values.
  says reduction semantics.
  does not say materialization, loop phase, or fold policy.

Fiber builder:
  decides how those relations become repeated local work.

Schedule:
  records raw repeated instances, phase/region structure, typed step kinds,
  typed dependency kinds, source order, and resource facts.

Verifier:
  validates construction, binding, and resource facts.
  produces ValidatedFiberExecutionSchedule.

Folding:
  proves uniform repeated structure from normalized schedule facts.
  proves carry-chain topology when reduction carry edges are present.
  does not know or care whether a repeated coordinate came from K.
  does not decide target projection eligibility.

DFU backend:
  proves target projection eligibility.
  projects eligible proofs to vendor folding fields.
```

This returns the B-line work to the project layering principle: no compiler
layer should ask a higher semantic layer to maintain lower executable-state
facts.

## Open Questions

1. Should the operator access profile name fragment operations like
   `materialize_A`, or should those names be introduced only by the fiber
   pattern builder?

   Recommendation: op specs should name semantic inputs and relations; fiber
   builders should name materialization actions.

2. Should `accumulator_prepare` / `finalize_accumulator` remain operator
   semantic relations?

   Recommendation: keep reduction identity / update / output semantics in the
   op spec.  Let fiber patterns name prepare/finalize actions if they choose to
   materialize those lifecycle points.

3. Should fused ReLU remain in MatMul access profile?

   Recommendation: keep the current fused epilogue as transitional metadata,
   but model long-term elementwise fusion as a fiber-chain concern.

## Recommended Decision

Accept this boundary correction.

Immediately stop treating `MatmulOpSpec.fiber_graph_profile().steps[*].phase`
and `MatmulOpSpec.folding_profile()` as the desired architecture.  Treat them as
temporary migration artifacts to remove.

Next implementation phase:

```text
1. Add OperatorAccessProfile / ReductionProfile.
2. Add stream-owned FiberPatternPlan.
3. Add explicit NumericPolicy / OrderingPolicy to reductions.
4. Add typed ScheduleStepSemantics, ScheduleStepTrait, dependency kinds, and
   verifier-owned validation statuses.
5. Switch current MatMul builder to the stream-owned pattern while keeping
   counts stable.
6. Add poison tests for deprecated op-spec phase APIs.
7. Add versioned binary_policy schema guards.
8. Add carry-chain topology proof.
9. Then remove folding_profile() and op-spec-owned phase descriptors.
```

Implementation PR hard gates:

```text
1. MatmulOpSpec exposes access / reduction semantics only.
2. MatmulOpSpec no longer provides folding authority.
3. build_sequential_k_fiber does not read deprecated phase APIs.
4. deprecated phase APIs have poison tests.
5. folding.py does not import MatmulOpSpec or ElementwiseFamilySpec.
6. folding.py does not branch on graph_kind == "sequential_k_matmul".
7. folding proof uses normalized topology and typed dependency kinds.
8. carry-chain correctness is proven, not inferred from REDUCTION_CARRY counts.
9. binary_policy has a versioned schema guard.
```
