# RFC: B-line Operator Specs as Lowering Strategy Owners
> Terminology update (2026-06-21): this document predates the decision to treat
> the stream/fiber route as the main compiler path. “B-line” below means the
> mainline stream/fiber lowering path, not a side branch or optional experiment.


## Status

Approved for Phase 0, Phase 1, and descriptor-only Phase 1.5 implementation.

Boundary correction:

```text
The sections that place loop phases, loop-body step order, or folding policy in
operator specs are superseded by
2026-06-21_fiber_structure_owns_loop_folding_rfc.md.
```

Deep stream/fiber migration is not approved yet; it requires the extra gates in this revision to be implemented or explicitly deferred.

Architecture direction accepted: use `core/op_specs` as the per-operator strategy home for B-line stream/fiber/executable/template lowering, while keeping B-line IR construction, stream topology, target evidence, and vendor binary emission owned by generic compiler passes.

Required amendments integrated in this revision:

```text
1. Model op specs as an operator base protocol plus concrete inherited specs.
2. Make fiber descriptors structured access/dependency graphs, not role lists.
3. Split template intent from target evidence.
4. Validate executable roles through typed IDs or a registry.
5. Strong-type visibility requirements.
6. Add an early descriptor-only symbolic ElementwiseFamilySpec sanity check.
7. Represent loop-carried state explicitly.
8. Define zero-instruction authority as hint / permission / proof.
9. Require target/profile modules to produce concrete evidence records.
10. Require graph_kind migration branches to have retirement metadata.
```

### Implementation alignment as of 2026-06-21

Current code has caught up with the approved descriptor-only part of this RFC:

```text
Phase 0 / 1 guard:
  compiler/tools/check_op_specs_strategy_profiles.py

Shared strategy schema:
  compiler/gpdpu_compiler/core/op_specs/operator_strategy.py
  compiler/gpdpu_compiler/core/op_specs/lowering_profiles.py

Registered descriptor providers:
  compiler/gpdpu_compiler/core/op_specs/matmul.py
  compiler/gpdpu_compiler/core/op_specs/elementwise.py
  compiler/gpdpu_compiler/core/op_specs/__init__.py
```

The implemented shape matches the decision in this note:

```text
MatmulOpSpec now exposes:
  stream_visibility_profile()
  fiber_graph_profile()
  executable_role_profile()
  template_intent_profile()
  folding_profile()
  graph_kind_allowlist()

ElementwiseFamilySpec now exists as a descriptor-only Phase 1.5 sanity target:
  local visibility
  no K loop
  no carried accumulator state
  symbolic template intent
  no runnable DFU3500 emission claim
```

This is still metadata-only B-line progress.  The existing stream/fiber/template
pipeline has not yet been deeply migrated to consume these profiles as its
authority.  In particular:

```text
stream_compiler/gemm_demo.py still owns concrete GEMM stream topology;
stream_compiler/fiber.py still owns sequential-K fiber expansion;
stream_compiler/folding.py still owns current GEMM loop folding recognition.
```

Phase 2 and Phase 3 have now started in code:

```text
stream_compiler/executable.py resolves FiberOp roles through
  MatmulOpSpec.executable_role_profile(), while preserving the current
  ExecutableFiberOp.role strings as the downstream report key.

stream_compiler/binding.py composes
  MatmulOpSpec.template_intent_profile()
  + core/dfu3500/template_evidence.py target evidence
  -> SymbolicRoleBinding rows.
```

Phase 4 has a first shallow adapter:

```text
stream_compiler/gemm_demo.py passes MatmulOpSpec.fiber_graph_profile() into
  build_sequential_k_fiber().

stream_compiler/fiber.py validates graph_kind / loop axis / carried state /
  required step ids, and records profile_step_id/profile_role provenance on
  emitted FiberOps.

The sequential-K adapter now derives its loop-body emission order from
  FiberGraphProfile.steps:
    materialize_A -> materialize_B -> gemm_update
```

That is still a metadata/source-of-authority migration, not deep stream/fiber
rewriting.  The current builder still materializes the existing sequential-K
flat op shape; it does not yet generically expand arbitrary FiberGraphProfile
steps.  Deep stream visibility migration also remains gated by the
visibility-scope checks described below.

## Summary

The current `core/op_specs` package already centralizes part of MatMul policy: semantic shape rules, DFU3500 lowering support, parallel/task decomposition profile, fusion compatibility, and tile lowering profile.  B-line, however, still carries many MatMul-specific decisions directly in `stream_compiler`: GEMM stream visibility shape, sequential-K fiber construction, `FiberOp -> ExecutableFiberOp.role`, symbolic template binding, and loop folding recognition.

This RFC proposes extending op specs from "policy descriptors for old lowering" into B-line operator strategy providers.  The goal is not to let an operator spec mutate downstream IR or become a backend serializer.  The goal is to make each operator provide typed, reviewable lowering strategies that generic B-line passes consume:

```text
Chip-level OpView
  -> OpSpec parallel / stream visibility profiles
  -> generic StreamPlan builder
  -> OpSpec tile access / fiber profiles
  -> generic Fiber builder
  -> OpSpec executable role profile
  -> generic FiberExecutionSchedule
  -> OpSpec template binding profile
  -> generic TemplateOpPlan / BinaryLayoutPlan / BinaryEmitter
```

The desired engineering outcome is: adding a new operator should primarily mean adding one op spec file, plus tests and registration.  The framework may still own shared helper code, target profiles, and vendor serializers, but operator-specific lowering and template policy should stop scattering across B-line pass files.

## Current State

### Existing `op_specs`

`compiler/gpdpu_compiler/core/op_specs/base.py` defines declarative descriptor classes and explicitly states:

```text
Op specs centralize operator policy, but they must not build downstream IR.
Lowering passes consume these descriptors and construct their own layer's
program objects.
```

`compiler/gpdpu_compiler/core/op_specs/matmul.py` currently exposes `MATMUL_SPEC` with:

```text
semantic_contract()
  rank2_mk_kn_to_mn
  lhs_rhs_same_dtype

dfu3500_lowering_contract()
  lowering_kind = summa_gemm
  target_profile_id = dfu3500_simict_legacy_gemm
  supported placements:
    A: Shard(0), Replicate()
    B: Replicate(), Shard(1)
    C: Shard(0), Shard(1)

parallel_profile()
  primary_schedule_kind = gemm_output_tiles
  task_decomposition = gemm_output_tiles
  max_task_rows = 4
  required subtask roles = accumulator_prepare, k_stream, finalize_store
  ReLU epilogue allowed only as tile-local post-op
  accumulator state is app-local explicit state

tile_lowering_profile()
  phase_kind = local_gemm_summa
  template_kind = summa_gemm_64x64x64_fp16
  loop_axis = K
  loop_fold_policy = vendor_instance_repeat_candidate
```

This is the right shape: descriptors are frozen, reviewable, and do not directly construct lower-layer programs.

### Current B-line hardcoded MatMul points

B-line currently proves the new stream/fiber/executable route, but MatMul knowledge is still distributed:

```text
stream_compiler/gemm_demo.py
  builds GEMM stream topology:
    A read by y=0 anchors and forwarded across each row
    B read by x=0 anchors and forwarded down each column
  computes local A/B/C shapes and assigned output tile coords

stream_compiler/fiber.py
  build_sequential_k_fiber()
  hardcodes flat GEMM fiber ops:
    accumulator_prepare
    fragment_sram_read / fragment_route_recv / fragment_route_push
    gemm_update
    finalize_accumulator
    epilogue_relu
    store_fragment

stream_compiler/executable.py
  _role_for_fiber_op()
  maps FiberOpKind to executable roles:
    gemm_update -> compute_core:gemm_update
    epilogue_relu -> epilogue:relu
    store_fragment -> tile_store

stream_compiler/binding.py
  _role_binding_policy()
  maps executable roles to symbolic / legacy-template candidates

stream_compiler/folding.py
  recognizes GEMM-related executable roles for loop folding reports

stream_compiler/vendor_components.py and field/binary files
  carry DFU3500 package / base-addr / row-layout facts
```

This was acceptable while B-line was a GEMM proof branch.  It becomes a blocker if B-line is expected to host more operators such as reduce, elementwise, softmax-like staged workloads, or the audio `log10max` preprocessing path.

## Problem

The current B-line architecture has a hidden scalability failure:

```text
Adding one operator requires editing many generic-looking B-line files.
```

For MatMul this is survivable because the whole prototype was built around GEMM.  For the next operators, the pattern would degrade quickly:

```text
new op
  -> add StreamPlan special cases
  -> add FiberOp special cases
  -> add executable role special cases
  -> add template binding special cases
  -> add folding special cases
  -> add binary support special cases
```

That is the old technical debt wearing a new stream/fiber coat.  It also makes roles like `compute_core:gemm_update` or `epilogue:relu` become implicit ABI facts scattered across files, rather than reviewable operator contracts.

At the same time, pushing too much into op specs would create the opposite problem: op specs would become miniature backends that construct routes, mutate stream programs, allocate binary rows, or encode vendor byte offsets.  That would violate the project layering principle and make `op_specs` an untestable god object.

The design needs a narrow middle:

```text
Operator specs own operator-local lowering strategy.
Generic passes own IR construction, topology realization, scheduling, and binary emission.
```

## Goals / Non-goals

### Goals

1. Make B-line operator-specific lowering policy discoverable in one op spec file.
2. Let generic B-line passes consume typed descriptors rather than hardcoded op-name branches.
3. Preserve B-line flat IRs:
   - stream actions remain flat;
   - fiber ops remain flat;
   - executable ops remain flat;
   - template/binary plans remain explicit.
4. Keep StreamPlan topology construction system-owned:
   - MatMul may say A needs row visibility and B needs column visibility;
   - MatMul must not manually add route actions.
5. Keep binary layout and byte serialization backend-owned:
   - op specs may declare template intent and resource requirements;
   - op specs must not own vendor row offsets, binary field offsets, or serializer quirks.
6. Make MatMul the first strangler migration target while keeping current B-line reports stable.
7. Set up a path where `ReduceMaxOpSpec`, `ElementwiseFamilySpec`, or `Log10Max`-related specs can be added without editing every B-line stage.

### Non-goals

1. Do not rewrite all B-line code in one patch.
2. Do not make op specs public user plugin APIs.
3. Do not move DFU3500 vendor byte layout, CBUF/MICC packing, or serializer readiness into op specs.
4. Do not consume A-line `TileMicroBlock` compatibility projections as B-line authority.
5. Do not make ReLU, reduce, or log10max runnable as part of this RFC.
6. Do not introduce multi-backend abstraction beyond what the current DFU-first path needs.

## Proposed Design

### 1. Use an operator base protocol with inherited operator specs

The design should be explicit: operators are objects with a common protocol, and concrete operators inherit/implement the protocol.

Conceptually:

```python
class OperatorLoweringSpec(Protocol):
    op_name: str

    def semantic_contract(self) -> SemanticContract: ...
    def dfu3500_lowering_contract(self) -> TargetLoweringContract: ...
    def parallel_profile(self) -> OpParallelProfile: ...

    def stream_visibility_profile(self, op: OpView) -> StreamVisibilityProfile: ...
    def fiber_graph_profile(self, op: OpView) -> FiberGraphProfile: ...
    def executable_role_profile(self, op: OpView) -> ExecutableRoleProfile: ...
    def template_intent_profile(self, op: OpView) -> TemplateIntentProfile: ...
    def folding_profile(self, op: OpView) -> LoopFoldingProfile: ...


class MatmulOpSpec(BaseOperatorLoweringSpec):
    op_name = "matmul"
    ...
```

The compiler lowering path dispatches through this protocol:

```text
spec = get_op_spec(op.op)

App/task planner:
  consumes spec.parallel_profile(op)

Stream builder:
  consumes spec.stream_visibility_profile(op)

Fiber builder:
  consumes spec.fiber_graph_profile(op)

Executable lowerer:
  consumes spec.executable_role_profile(op)

Template planner:
  consumes spec.template_intent_profile(op)
  composes it with target evidence

Folding analyzer:
  consumes spec.folding_profile(op)
```

The important distinction is: the framework invokes operator methods at well-defined phase boundaries, but the operator methods return immutable strategy data.  They do not mutate the pass.

This gives the desired extension shape:

```text
new operator
  -> add core/op_specs/<operator>.py
  -> implement the protocol methods
  -> register in get_op_spec()
  -> add operator-specific fixtures / reports
```

### 2. Keep descriptor classes under `core/op_specs`, but avoid a public "B-line" API name

Add the shared protocol and descriptors under an internal name such as:

```text
core/op_specs/operator_strategy.py
core/op_specs/lowering_profiles.py
```

Avoid making `b_line.py` the durable API name.  "B-line" is a current engineering route.  The descriptors are more general: they describe internal compiler lowering strategy for the stream/fiber/template pipeline.

Dependency direction remains:

```text
op_specs
  defines operator strategy protocols and descriptor records

stream_compiler
  imports descriptors and constructs StreamPlan / Fiber / ExecutableFiberOp /
  TemplateOpPlan objects

op_specs
  must not import stream_compiler builders
```

### 3. Descriptor data must be structured enough to build flat fiber ops

The previous `FiberAccessMapProfile` shape was too weak if it only listed roles.  A role list is not an access graph.

The fiber builder needs enough information to build flat `FiberOp` records and dependencies without rediscovering MatMul semantics.  The op spec therefore returns a small structured step graph:

```python
@dataclass(frozen=True)
class FiberStepProfile:
    step_id: str
    role: ExecutableRoleId | str  # reference to a declared executable role
    phase: Literal["pre_loop", "loop_body", "post_loop"]
    repeat_axis: str | None
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    depends_on: tuple[str, ...]
    attrs: tuple[tuple[str, JsonValue], ...] = ()
    zero_instruction_candidate: bool = False


@dataclass(frozen=True)
class FiberGraphProfile:
    graph_kind: str
    fiber_axes: tuple[str, ...]
    loop_axes: tuple[str, ...]
    fragment_spaces: tuple[FragmentSpaceProfile, ...]
    steps: tuple[FiberStepProfile, ...]
```

For MatMul, the profile should express the true graph shape:

```text
pre_loop:
  accumulator_prepare
    outputs: acc_init(m,n)

loop_body over k_block:
  materialize_A
    outputs: A(m,k)

  materialize_B
    outputs: B(k,n)

  gemm_update
    inputs: A(m,k), B(k,n), acc_prev(m,n,k-1)
    outputs: acc_next(m,n,k)
    depends_on: materialize_A, materialize_B, previous_accumulator

post_loop:
  finalize_accumulator
    inputs: acc_final(m,n)
    outputs: C(m,n)

  epilogue_relu
    inputs: C(m,n)
    outputs: Y(m,n)

  store_fragment
    inputs: Y(m,n) or C(m,n)
```

This still preserves flat IR.  The profile is not a nested executable program; it is a declarative recipe from which the generic builder emits a flat `Fiber.ops[]` list.

`FiberStepProfile.role` references a declared executable role.  `ExecutableRoleProfile` is the validation and metadata authority for those roles; it must not become a divergent remapping table.  If the fiber graph says a step role is `compute_core:gemm_update`, the executable role profile must validate that same role rather than remap it to a different role.

During migration, the builder may temporarily dispatch on `graph_kind="sequential_k_matmul"`, but the long-term target is that the step graph itself carries enough data to avoid rebuilding MatMul semantics from magic strings.

### 4. Represent loop-carried state explicitly

`FiberStepProfile.depends_on` is enough for static step dependencies, but it is not enough for recurrence.  MatMul needs to express:

```text
gemm_update[k] consumes accumulator[k-1]
gemm_update[k] produces accumulator[k]
finalize_accumulator consumes accumulator[last]
```

This is loop-carried state, not a normal same-iteration dependency.  It must be explicit so the generic builder does not infer recurrence semantics from role names such as `accumulator` or from `graph_kind="sequential_k_matmul"`.

Add a descriptor like:

```python
@dataclass(frozen=True)
class LoopCarriedStateProfile:
    state_id: str
    init_step: str
    update_step: str
    final_step: str | None
    axis: str
    initial_token: str
    previous_token: str
    next_token: str
```

Then `FiberGraphProfile` includes:

```python
carried_states: tuple[LoopCarriedStateProfile, ...] = ()
```

For MatMul:

```text
state_id = "accumulator"
axis = "k_block"
init_step = "accumulator_prepare"
update_step = "gemm_update"
final_step = "finalize_accumulator"
initial_token = "acc_init(m,n)"
previous_token = "acc_prev(m,n,k-1)"
next_token = "acc_next(m,n,k)"
```

This keeps recurrence structure in the operator strategy contract, while the generic Fiber builder remains responsible for emitting flat `FiberOp` records and explicit dependency edges.

### 5. Use typed role IDs or registry-validated role strings

Executable roles are semantic contracts.  They cannot remain loose strings forever.

Preferred shape:

```python
@dataclass(frozen=True)
class ExecutableRoleId:
    namespace: str       # "compute_core", "operand", "epilogue", "store", ...
    name: str            # "gemm_update", "materialize", "relu", ...
    operand_role: str | None = None

    def text(self) -> str:
        ...
```

If implementation keeps string roles initially, every role must be registry-validated:

```text
Every ExecutableRoleProfile.role must be either:
  1. known to template intent / target evidence resolution;
  2. known to folding analysis; or
  3. explicitly marked symbolic_unresolved / unsupported / zero_instruction.

Every LoopFoldingProfile role must correspond to an executable role declared by
the same operator spec.
```

This prevents `compute_core:gemm_update`, `compute:gemm_update`, and `compute_core:gemm` from silently becoming three different spells.

### 6. Split operator template intent from target evidence

Template binding should not be fully decided by the op spec.  The op spec expresses operator intent.  The target evidence layer proves or rejects that intent for a concrete DFU3500 profile.

Operator-owned:

```python
@dataclass(frozen=True)
class TemplateIntentProfile:
    executable_role: ExecutableRoleId | str
    template_family: str | None
    resource_intent: tuple[str, ...]
    may_be_zero_instruction: bool = False
    fallback_status: Literal[
        "symbolic_unresolved",
        "unsupported",
    ] = "symbolic_unresolved"
```

Target/evidence-owned:

```python
@dataclass(frozen=True)
class TemplateEvidenceProfile:
    executable_role: ExecutableRoleId | str
    target_profile_id: str
    resolved_status: Literal[
        "concrete",
        "legacy_candidate",
        "candidate_unproven",
        "zero_instruction",
        "symbolic_unresolved",
        "unsupported",
    ]
    template_role: str | None
    evidence_refs: tuple[str, ...]
```

Then:

```text
MatMul spec says:
  compute_core:gemm_update wants GEMM compute-update capability.

DFU3500 evidence says:
  on dfu3500_simict_legacy_gemm this role has a legacy template candidate.

Binary layout says:
  runnable only if every role is concrete or accepted zero-instruction.
```

This prevents `MatmulOpSpec` from becoming half of the target profile.

Concrete evidence ownership rule:

```text
core/op_specs may define the shared TemplateEvidenceProfile dataclass shape.
Concrete TemplateEvidenceProfile instances and evidence resolution logic are
produced by target/profile modules, not by concrete operator specs.
No concrete TemplateEvidenceProfile instances may live in core/op_specs/<operator>.py.
```

### 7. Define zero-instruction authority as hint / permission / proof

Several layers may need to talk about zero-instruction behavior, but they do not have the same authority.

```text
FiberStepProfile.zero_instruction_candidate:
  hint that this fiber step may be a semantic boundary without an emitted
  instruction.  It must not delete the step.

TemplateIntentProfile.may_be_zero_instruction:
  operator-level permission that an executable role may resolve to a
  zero-instruction boundary.

TemplateEvidenceProfile.resolved_status == "zero_instruction":
  target/profile proof that this role is zero-instruction for this concrete
  target profile.
```

For example, `accumulator_finalize` may exist as a first-class semantic boundary even when it emits no instruction.  It occupies provenance and dependency space, but it must not occupy PC or instruction-row space once target evidence proves it is zero-instruction.

### 8. Strong-type visibility requirements and scopes

Stream visibility should not be a free-form string field.  At minimum it should use a closed internal vocabulary:

```python
VisibilityKind = Literal[
    "local",
    "row_visible",
    "column_visible",
    "broadcast",
    "reduce_collective",
    "materialized_storage",
]

VisibilityCostModel = Literal[
    "local_only",
    "per_task_input_visibility",
    "task_local_route",
    "collective_required",
    "materialized_reload",
]
```

However, the builder needs more than a kind.  It needs to know which consumers require a fragment and which fragment axes define the visibility group.  Add a richer visibility scope descriptor:

```python
@dataclass(frozen=True)
class VisibilityScopeProfile:
    kind: VisibilityKind
    consumer_space: str
    consumer_axes: tuple[str, ...]
    producer_fragment_space: str
    producer_fragment_axes: tuple[str, ...]
    visibility_group_axes: tuple[str, ...]
    materialization_policy: VisibilityCostModel
```

For MatMul A:

```text
producer fragment = A(m,k)
consumers = C(m,*) streams
visibility group axes = (m_tile, k_block)
kind = row_visible or equivalent soft-mesh row visibility
```

For MatMul B:

```text
producer fragment = B(k,n)
consumers = C(*,n) streams
visibility group axes = (k_block, n_tile)
kind = column_visible or equivalent soft-mesh column visibility
```

For future reduce/log10max paths, the same schema can describe collective or materialized visibility without pretending they are MatMul row/column traffic.

### 9. Require retirement metadata for graph-kind migration branches

During migration, generic builders may temporarily dispatch on `graph_kind`, such as:

```text
graph_kind = "sequential_k_matmul"
```

This is allowed only as scaffolding.  Every graph-kind-specific branch must be allowlisted with owner, reason, and removal phase:

```python
GRAPH_KIND_ALLOWLIST = {
    "sequential_k_matmul": {
        "owner": "stream_compiler/fiber",
        "reason": "loop-carried accumulator descriptor not fully consumed generically yet",
        "must_be_removed_before": "Phase 5",
    },
}
```

`must_be_removed_before` means the branch may exist through the previous phase but must be removed or re-approved before entering the named phase.  If a branch has no retirement metadata, it is not migration scaffolding; it is a new hardcoded op switch.

### 10. Clarify MatMul ownership boundaries

MatMul should own:

```text
semantic rule:
  C[M,N] = A[M,K] @ B[K,N]

placement support:
  A sharded on M / replicated on K
  B replicated on K / sharded on N
  C sharded on M,N

operand visibility requirements:
  A(m,k) must become visible to streams computing C(m,*)
  B(k,n) must become visible to streams computing C(*,n)

tile/fiber access graph:
  fiber(m,n,k) consumes A(m,k), B(k,n), accumulator(m,n,k-1)
  produces accumulator(m,n,k)

executable roles:
  gemm_update -> compute_core:gemm_update
  finalize_accumulator -> accumulator_finalize
  epilogue_relu -> epilogue:relu

template intent:
  compute_core:gemm_update wants GEMM compute-update capability
  accumulator_finalize may be zero-instruction
  epilogue:relu wants ReLU/max capability but may remain unresolved
```

MatMul should not own:

```text
which stream route path is chosen;
the concrete route action chain;
task/subtask row packing;
instance base address table layout;
CBUF/MICC byte offsets;
vendor serializer field order;
runtime package grouping.
```

Core principle:

```text
MatMul does not own routes.  MatMul owns the fragment visibility requirements
that make routes necessary.
```

### 11. Generic B-line pass responsibilities

The resulting B-line shape becomes:

```text
App / task / soft-mesh planning
  consumes spec.parallel_profile(op)
  decides app-local work partition and soft processor layout

StreamPlan builder
  consumes spec.stream_visibility_profile(op)
  realizes row/column/local/collective/materialized visibility through stream
  actions and dependencies

Fiber builder
  consumes spec.fiber_graph_profile(op)
  expands the step graph into flat FiberOp sequences with explicit dependencies

Executable lowerer
  consumes spec.executable_role_profile(op)
  validates FiberOp roles and creates ExecutableFiberOp.role

Template planner
  consumes spec.template_intent_profile(op)
  composes operator intent with target evidence to create TemplateOpPlan

Folding planner
  consumes spec.folding_profile(op)
  reports stream/task/subtask loop folding candidates

Binary layout / vendor serializer
  consumes TemplateOpPlan and target layout facts
  never asks op specs for byte offsets
```

### 12. Introduce an internal resolver, not a plugin system

Add a tiny internal registry:

```python
def get_op_spec(op_name: str) -> OperatorLoweringSpec:
    ...
```

This is not a dynamic plugin system.  It is a frozen internal map:

```python
_OP_SPECS = {
    "matmul": MATMUL_SPEC,
}
```

Future operators add:

```text
core/op_specs/elementwise.py
core/op_specs/reduce.py
```

plus registration and tests.  Public API migration from `ops.py` to `ops/` remains out of scope.

### 13. Add an early symbolic second operator sanity check

Before deep stream/fiber migration is considered complete, add a non-MatMul symbolic proving operator.

Recommended first proving target:

```text
ElementwiseFamilySpec
  inputs:
    X(tile)
  output:
    Y(tile)
  visibility:
    local
  fiber graph:
    materialize_input -> elementwise_apply -> store_fragment
  carried state:
    none
  loop axes:
    none
  template intent:
    elementwise_apply -> symbolic_unresolved
  binary:
    non-runnable until target evidence exists
```

This profile should fail validation if the schema assumes A/B operands, K-loop recurrence, or accumulator state.

Recommended second proving target:

```text
ReduceMaxOpSpec
  collective visibility profile
  symbolic template status
  no runnable binary emission until collective support is proven
```

This prevents the schema from becoming a more polished GEMM palace with a "generic" sign on the door.

## Invariants

1. `core/op_specs` may define operator strategy protocols, base classes, descriptor dataclasses, and concrete operator specs.
2. `core/op_specs` must not import `stream_compiler` builders or vendor binary serializers.
3. Operator specs return frozen, serializable strategy records.  They do not mutate `StreamPlan`, `Fiber`, `FiberExecutableProgram`, `TemplateOpPlan`, or `BinaryLayoutPlan`.
4. Descriptor schemas must be structured enough that generic passes do not recover operator semantics from role-string conventions alone.
5. Stream topology remains generic pass authority.  Operator specs define visibility requirements, not concrete route paths.
6. Fiber IR remains flat.  Operator specs define access/dependency step graphs from which generic builders emit flat `FiberOp` records.
7. Every executable role emitted for an operator must be declared by that operator's `ExecutableRoleProfile` and validated against template/folding consumers.
8. Template binding is composed from operator intent and target evidence.  Op specs do not unilaterally decide target proof status.
9. `ExecutableFiberOp.role` is the source for template planning.  Binding must not consume `TileMicroBlock` compatibility fields.
10. Template/evidence profiles may mark roles as `symbolic_unresolved`, `candidate_unproven`, `zero_instruction`, or `unsupported`.  Binary layout must fail closed for runnable emission if unresolved/unsupported roles remain.
11. Fused epilogues must be represented explicitly as fused-op or epilogue policy, not hidden inside unrelated MatMul role strings.
12. Vendor binary layout facts stay in DFU3500 target modules and B-line binary/layout passes, not in op specs.
13. Current GEMM B-line reports must remain stable during metadata-only migration phases.
14. Migrated passes should not add raw `op == "matmul"` branches unless explicitly allowlisted with a removal note or test guard.
15. Loop-carried state must be represented explicitly; generic builders must not infer recurrence semantics from role names such as `accumulator` or graph-kind strings.
16. Concrete `TemplateEvidenceProfile` records are produced by target/profile modules, not by concrete operator specs.
17. Every graph-kind-specific migration branch must be allowlisted with owner, reason, and removal phase.
18. Visibility profiles must identify consumer fragment spaces/scopes, not only name a visibility kind.
19. Zero-instruction handling has three authorities: step-level hint, operator intent permission, and target evidence proof.  Only target evidence can prove zero-instruction status.

## Alternatives Considered

### Alternative A: Keep B-line hardcoded until another operator arrives

Rejected.

This preserves short-term velocity but guarantees that the second operator will copy GEMM's scattered structure.  By the time reduce/log10max arrives, roles, template bindings, and visibility rules will already be distributed across generic-looking files.

### Alternative B: Let op specs directly build stream/fiber/template IR

Rejected.

This would satisfy "one operator, one file" superficially, but it creates operator-owned mini-backends.  It violates the layer rule: generic passes would no longer own their IR construction, validation, or debug views.

### Alternative C: Put B-line op policy under `stream_compiler/op_specs`

Deferred.

This is tempting because the first consumers are B-line passes.  However, the existing `core/op_specs` already hosts MatMul policy, and the project goal is to centralize operator lowering policy.  Placing descriptors in `core/op_specs` keeps one operator home and avoids a split between "old op spec" and "B-line op spec".

### Alternative D: Move vendor template and binary details into op specs

Rejected.

Operator specs may declare template intent and resource requirements.  They must not own field offsets, CBUF/MICC rows, or serializer details.  Those facts are target/backend facts, not operator semantics.

## Migration / Implementation Plan

### Phase 0: Decision, string-role, and graph-kind inventory

Add a report/check that lists current B-line MatMul-specific decisions and their future owner:

```text
gemm_demo.py stream visibility      -> Matmul stream visibility profile + generic builder
fiber.py sequential K fiber         -> Matmul fiber graph profile + generic builder
executable.py role mapping          -> Matmul executable role profile
binding.py role binding             -> operator intent + target evidence
folding.py role recognition          -> Matmul loop folding profile
vendor_components.py byte/base facts -> target/backend-owned, not op spec
```

Also inventory all current raw executable role strings:

```text
operand_materialize:A/B
operand_route_recv:A/B
operand_route_push:A/B
accumulator_prepare
compute_core:gemm_update
accumulator_finalize
epilogue:relu
tile_store
```

Also inventory raw operator and graph-kind branches:

```text
op == "matmul"
graph_kind == "sequential_k_matmul"
role string switch statements
```

No behavior change.

### Phase 1: Add operator protocol, descriptor schema, and MatMul profiles

Add internal shared files such as:

```text
core/op_specs/operator_strategy.py
core/op_specs/lowering_profiles.py
```

Add:

```text
OperatorLoweringSpec protocol / base class
FiberGraphProfile + FiberStepProfile
LoopCarriedStateProfile
ExecutableRoleId or role registry validation
TemplateIntentProfile
TemplateEvidenceProfile shared dataclass shape
closed visibility vocabulary
VisibilityScopeProfile
graph-kind allowlist metadata shape
```

Extend `MatmulOpSpec` with methods such as:

```python
stream_visibility_profile(op)
fiber_graph_profile(op)
executable_role_profile(op)
template_intent_profile(op)
folding_profile(op)
```

No B-line pass consumes them yet.  Add JSON/frozen/purity/import-boundary tests.

### Phase 1.5: Add symbolic `ElementwiseFamilySpec` as a schema sanity check

Before MatMul descriptors are consumed deeply, add a symbolic non-MatMul op family:

```text
ElementwiseFamilySpec
  input: X(tile)
  output: Y(tile)
  visibility: local
  fiber graph: materialize_input -> elementwise_apply -> store_fragment
  carried state: none
  loop axes: none
  template intent: elementwise_apply -> symbolic_unresolved
  binary: non-runnable until target evidence exists
```

This phase exists to prove the descriptors are not GEMM-shaped.  It does not need runnable DFU3500 emission, and it may remain descriptor-only at first.

### Phase 2: Migrate executable role mapping

Replace `_role_for_fiber_op()` with a generic resolver consuming `ExecutableRoleProfile`.

Expected current MatMul behavior remains:

```text
fragment_sram_read(A/B)  -> operand_materialize:A/B
fragment_route_recv(A/B) -> operand_route_recv:A/B
fragment_route_push(A/B) -> operand_route_push:A/B
accumulator_prepare      -> accumulator_prepare
gemm_update              -> compute_core:gemm_update
finalize_accumulator     -> accumulator_finalize
epilogue_relu            -> epilogue:relu
store_fragment           -> tile_store
```

This is the safest cut because it only changes where role mapping data comes from.

### Phase 3: Split template intent and target evidence

Replace `_role_binding_policy()` with a composition step:

```text
operator TemplateIntentProfile
  + DFU3500 TemplateEvidenceProfile
  -> TemplateOp / symbolic role binding report
```

Current statuses should remain behaviorally equivalent:

```text
legacy template candidates:
  accumulator_prepare
  operand_materialize:A/B
  operand_route_recv:A/B
  operand_route_push:A/B
  compute_core:gemm_update
  tile_store

explicit non-runnable / symbolic or zero-instruction candidates:
  accumulator_finalize
  epilogue:relu
```

If target evidence proves `accumulator_finalize` is a zero-instruction semantic boundary, represent it as target evidence resolving operator intent, not as silent role deletion.

### Phase 4: Migrate fiber graph construction

Do not start this phase until `LoopCarriedStateProfile`, role validation, and graph-kind allowlist checks exist.

Refactor `build_sequential_k_fiber()` so the generic builder consumes the MatMul `FiberGraphProfile`:

```text
pre_loop:
  accumulator_prepare -> acc_init

loop_body over k_block:
  materialize A(m,k)
  materialize B(k,n)
  gemm_update(A(m,k), B(k,n), acc_prev -> acc_next)

post_loop:
  finalize_accumulator(acc_final -> C)
  optional epilogue_relu(C -> Y)
  store_fragment(Y or C)
```

The output remains a flat `Fiber` with flat `FiberOp` records.  The profile does not introduce nested plans.

### Phase 5: Migrate stream visibility profile

Do not start this phase until `VisibilityScopeProfile` is expressive enough to identify consumer fragment spaces/scopes, not just visibility kind names.

Move the MatMul operand visibility policy out of `gemm_demo.py`:

```text
A operand:
  fragment axes = (m_tile, k_block)
  consumer scope = C(m,*) streams
  visibility group = same m/k fragment group

B operand:
  fragment axes = (k_block, n_tile)
  consumer scope = C(*,n) streams
  visibility group = same k/n fragment group
```

The generic StreamPlan builder still chooses concrete route actions based on soft mesh coordinates and DFU3500 stream topology.  MatMul does not add routes directly.

### Phase 6: Migrate folding policy

Move loop folding recognition from role-string checks into `LoopFoldingProfile`.

The folding analyzer remains generic and still produces B-line reports / binary readiness data.  The op spec only describes which roles belong to the stream-level task/subtask loop and which roles are invariant/post-loop.

### Phase 7: Add `ReduceMaxOpSpec` symbolic proving target

After Elementwise proves the local path, add a symbolic reduce proving target:

```text
ReduceMaxOpSpec
  collective visibility profile
  explicit unresolved target support
  no runnable binary emission until collective support is proven
```

This checks that the visibility schema can express more than local/row/column MatMul traffic.

## Validation Plan

### Static / structural checks

1. `op_specs` import boundary:

```text
core/op_specs/* must not import:
  stream_compiler.*
  program_* builders
  vendor binary serializers
```

2. Descriptor serialization:

```text
Matmul strategy profiles produce deterministic JSON-friendly payloads.
Elementwise symbolic profiles produce deterministic JSON-friendly payloads.
```

3. Descriptor purity:

```text
Calling the same profile method twice with the same OpView returns equal frozen descriptors.
```

4. Role registry validation:

```text
Every emitted executable role is declared by the operator spec.
Every declared executable role is consumed by template intent, folding policy, or
explicitly marked symbolic/unsupported/zero-instruction.
No migrated pass can invent an undeclared role string.
```

5. Template intent / target evidence separation:

```text
Operator specs produce TemplateIntentProfile.
Target profile modules produce concrete TemplateEvidenceProfile records.
TemplateOpPlan records both sources or reports missing evidence.
Concrete operator specs must not produce concrete evidence records.
```

6. Loop-carried state validation:

```text
MatMul FiberGraphProfile declares accumulator recurrence through
LoopCarriedStateProfile.
Generic builders must not infer recurrence from role strings or graph_kind.
ElementwiseFamilySpec declares carried_states = ().
```

7. Visibility scope validation:

```text
Every visibility profile declares consumer_space, consumer_axes,
producer_fragment_space, producer_fragment_axes, visibility_group_axes, and
materialization_policy.
```

8. Graph-kind allowlist validation:

```text
Every graph_kind-specific migration branch has owner, reason, and removal phase.
No unregistered graph_kind branch may be added.
```

### B-line golden summaries

For the current GEMM+ReLU demo, profile-specific expected reports should remain stable during Phase 1-3:

```text
FiberOp count
ExecutableFiberOp count
TemplateOp count
role counts
template status counts
folded instruction/component summaries
forbidden TileMicroBlock field count = 0
```

The exact numbers are demo-profile expectations, not global invariants.

### Second-op schema sanity check

Add a symbolic `ElementwiseFamilySpec` fixture before deep stream/fiber migration is complete.

Expected validation:

```text
no K loop
local visibility only
flat FiberStepProfile graph
symbolic template intent
no runnable binary emission required
```

This fixture should fail if descriptors assume MatMul-only concepts such as A/B operands, K-loop, or accumulator recurrence.

### Negative tests

1. A migrated B-line pass must not consume `TileMicroBlock` compatibility fields as role authority.
2. Runnable binary emission must reject unresolved/unsupported template roles.
3. Unknown operator without registered op spec must produce a clear diagnostic.
4. Op spec route ownership violation should be caught by import/lint checks rather than convention.
5. A role referenced by folding but not declared by the operator spec must fail validation.
6. Target evidence must not invent a role that operator intent did not declare.
7. A raw `op == "matmul"` branch in a migrated pass must be allowlisted or rejected by a focused check.
8. A graph-kind branch without owner/reason/removal phase must fail validation.
9. A FiberGraphProfile using loop-carried tokens without LoopCarriedStateProfile must fail validation.
10. A visibility profile with only `kind` but no consumer scope must fail validation.

### Regression command group

The existing stream compiler checks remain the immediate guardrail:

```bash
python compiler/tools/check_op_specs_strategy_profiles.py
python compiler/tools/stream_compiler_demo_pipeline.py
python compiler/tools/check_stream_compiler_executable.py
python compiler/tools/check_stream_compiler_role_binding.py
python compiler/tools/check_stream_compiler_template_ops.py
python compiler/tools/check_stream_compiler_binary_plan.py
python compiler/tools/check_stream_compiler_folding.py
```

If script names change, the requirement is the same: B-line report-only and layout-candidate checks must pass after every migration phase.

## Risks and Mitigations

### Risk: Op specs become god objects

Mitigation:

```text
Strategy records only.
No downstream IR mutation.
No route path construction.
No binary serializer ownership.
Import boundary tests.
```

### Risk: Scattered hardcode becomes centralized strings

Mitigation:

Use structured step graph descriptors, typed/validated executable roles, and closed visibility vocabularies.  A role list alone is not sufficient for fiber construction.

### Risk: Generic Fiber builder still hides MatMul semantics

Mitigation:

`FiberGraphProfile` must express fragment inputs/outputs/dependencies, not just phase role names.  Temporary dispatch on `graph_kind="sequential_k_matmul"` is allowed during migration, but every such dispatch must be isolated and tracked.

### Risk: Template binding collapses operator intent and target proof

Mitigation:

Split `TemplateIntentProfile` from `TemplateEvidenceProfile`.  Operator specs say what capability a role wants.  Target evidence says whether a concrete DFU3500 profile can provide it.

### Risk: "One op file" becomes a giant unreadable file

Mitigation:

One operator file may contain multiple small sections, but each section must map to a phase:

```text
semantic
parallel/task
stream visibility
fiber graph
executable role
template intent
folding
```

If the file grows too large, split internal helper functions/classes inside the same operator module before creating cross-layer files.

### Risk: Route logic sneaks into MatMul spec

Mitigation:

Write the boundary into tests and docs:

```text
MatMul declares row/column visibility requirements.
StreamPlan builder realizes route paths.
```

### Risk: Template binding hides unresolved roles

Mitigation:

Template/evidence profiles must preserve:

```text
symbolic_unresolved
candidate_unproven
zero_instruction
unsupported
```

No role may silently disappear to make a runnable subset look clean.

### Risk: Target-specific policy leaks too high

Mitigation:

DFU-first is allowed.  DFU3500 target/profile IDs are allowed in target evidence records.  But byte layout, row offsets, base address packing, and serializer facts remain in DFU3500 backend modules.

## Expected Effect

After the first migration stages, MatMul B-line will still produce the same reports, but the source of decisions will change:

```text
before:
  stream_compiler files know MatMul by hardcoded strings and branches

after:
  MatmulOpSpec exposes descriptors;
  stream_compiler files remain generic descriptor consumers
```

When adding a future operator, the expected path becomes:

```text
1. Add core/op_specs/<op>.py.
2. Register it in the internal resolver.
3. Add operator-specific descriptor tests and B-line report fixtures.
4. Reuse generic StreamPlan / Fiber / Executable / Template / Binary passes.
```

This does not mean every operator becomes runnable immediately.  It means unsupported roles become first-class diagnostics rather than hidden holes.

## Open Questions

1. Should ReLU be modeled as part of `MatmulOpSpec` epilogue policy for now, or as the first `ElementwiseFamilySpec` consumed as a fused post-op?

   Recommendation: keep current MatMul epilogue compatibility descriptor for GEMM+ReLU, but mark it as temporary.  Fused epilogue policy must not become the general elementwise fusion model.

2. How much of `vendor_components.py` should remain GEMM-specific?

   Recommendation: keep it backend-owned for now.  Later extract generic component assembly only after B-line operator profiles are stable.

3. How quickly should raw strings be replaced by typed role IDs?

   Recommendation: allow registry-validated strings for the first implementation phase, but design the schema so `ExecutableRoleId` can replace raw strings without changing every pass.

4. Should `ReduceMaxOpSpec` or `ElementwiseFamilySpec` be the first proving operator?

   Recommendation: add `ElementwiseFamilySpec` first because it tests non-GEMM local tile lowering with minimal collective complexity.  Add `ReduceMaxOpSpec` second to test collective visibility and symbolic unsupported paths.

## Recommended Decision

Approve Phase 0 + Phase 1 implementation.

```text
core/op_specs becomes the source of operator-local B-line lowering and template
strategy descriptors, implemented as an operator base protocol plus concrete
operator spec classes.
```

Approved now:

```text
1. decision/string-role/graph-kind inventory;
2. operator protocol and strategy descriptor schema;
3. MatMul strategy profiles;
4. role registry validation;
5. import-boundary and deterministic descriptor tests;
6. descriptor-only symbolic ElementwiseFamilySpec sanity check.
```

Not approved yet:

```text
deep stream/fiber migration, especially replacing build_sequential_k_fiber()
or gemm_demo.py stream topology, until the Phase 4 gates below are satisfied.
```

Require these boundaries:

```text
1. Op specs are strategy-data providers, not IR builders.
2. Stream topology remains generic pass authority.
3. Fiber/executable/template plans remain flat B-line IRs.
4. Fiber graph descriptors must express access/dependency structure, not only
   role lists.
5. Loop-carried state must be explicit.
6. Executable roles must be typed or registry-validated.
7. Template planning must compose operator intent with target evidence.
8. Concrete target evidence is produced by target/profile modules, not op specs.
9. Visibility profiles must identify consumer scopes, not just visibility kind.
10. Vendor binary layout remains backend authority.
11. A-line / TileMicroBlock compatibility projections remain validation aids,
    not B-line semantic inputs.
```

Phase 4 fiber migration requires:

```text
1. LoopCarriedStateProfile implemented or explicitly deferred with an allowlist.
2. graph_kind-specific branches have owner/reason/removal phase metadata.
3. ElementwiseFamilySpec descriptor-only sanity check exists.
4. Role registry validation exists.
```

Phase 5 stream visibility migration requires:

```text
1. VisibilityScopeProfile is expressive enough for MatMul A/B consumer scopes.
2. The schema does not assume A/B/K/accumulator concepts.
3. ReduceMaxOpSpec remains possible without redesigning visibility fields.
```

Then migrate role mapping and template intent/evidence composition first.  Those are the smallest, safest cuts and will prove whether the operator strategy protocol feels pleasant before touching stream/fiber construction.
