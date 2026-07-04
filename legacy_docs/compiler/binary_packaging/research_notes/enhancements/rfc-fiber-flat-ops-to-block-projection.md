# RFC: Fiber Flat Ops to Block Projection

## Status

Accepted direction with required clarifications.

This RFC is not a proposal to merge the refactored stream/fiber line into the
production backend as the new trunk.  It defines a validation bridge:

```text
new stream/fiber branch
  -> block projection compatibility view
  -> existing backend only for functional / structural validation
```

The long-term target remains a cleaner flat lowering pipeline.  The old
`TileMicroBlock` path is a comparison and validation seam, not the architecture
that the refactor should permanently bend around.

## Motivation

The new experimental stream compiler line now has two flat layers:

```text
StreamPlan
  answers whole-value stream visibility and route/load paths

Fiber
  answers stream-local fragment timing for one assigned output tile
```

A `Fiber` is intentionally not a nested micro-plan.  It is a flat sequence of
`FiberOp` records with semantic dependencies:

```text
FiberOp
  order_index
  op
  inputs / outputs
  depends_on: FiberDependency[]
  attrs.placement = pre_loop | loop_body | post_loop
  attrs.subtask_role = accumulator_prepare | k_stream | finalize_store
```

The next question is how this new flat fiber layer connects back to the existing
compiler backend without rewriting vendor packing.

The old production pipeline already has a useful boundary after K-instance loop
planning:

```text
ProcessorTileProgram
  -> TileMicroBlock
  -> TileMicroOpProgram
  -> Dfu3500TemplateBoundProgram
  -> ProgramNodes / DFUPacking / ProgramAsm
  -> ProgramVendorABI
  -> ProgramBinRows / Serializer
```

`TileMicroBlock` is the first structure that the downstream executable/template
path really consumes.  Therefore the refactor should first target an equivalent
block projection boundary rather than jumping directly from fibers to DFU
instructions.

Important boundary:

```text
FiberBlockProjection is allowed to validate against TileMicroBlock.
FiberBlockProjection should not become a permanent wrapper around TileMicroBlock.
```

If the new branch only connects to the old backend by keeping all old concepts
alive, the technical debt remains.  The bridge is useful only if it lets us prove
the new flat model and then progressively remove the old scaffolding.

## Current Evidence From Existing Pipeline

After current GEMM tile lowering, the old code builds:

```text
TileRouteAction
TileComputeAction
TileStoreAction
TileLoopRegion
TileDependency
```

Then `_build_tile_micro_blocks()` projects actions into:

```text
TileMicroBlock
  block_kind = route_source_materialize | route_forward
             | accumulator_prepare
             | compute_update
             | tile_store

  loop_region_id
  loop_instance_id
  loop_axis
  fold_policy
  route_action_ids / compute_action_ids / store_action_ids
  input_visibility_refs / output_visibility_refs
  input_value_refs / output_value_refs
```

Then `lower_processor_tile_to_micro_ops()` currently emits one micro-op per
micro-block:

```text
TileMicroBlock -> TileMicroOp(role=...)
```

Then DFU3500 legacy template binding maps the micro-op source block kind to
legacy GEMM template instructions.

This means `TileMicroBlock` is the practical compatibility seam.

## Proposed Direction

Introduce a projection step in the experimental stream compiler line:

```text
StreamPlan + Fiber flat ops
  -> FiberBlockProjection / TileBlockPlan-like debug structure
  -> old TileMicroBlock-compatible shape
```

The projection should remain internal and experimental until it can reproduce a
small GEMM-equivalent block view.

The projection is not allowed to rediscover high-level route or GEMM policy.
It only consumes:

```text
1. StreamPlan route/load topology and visibility paths.
2. FiberOp fragment obligations and semantic dependency edges.
3. Task/subtask placement attrs already attached to FiberOp.
```

## FiberOp Granularity

The desired steady-state grain is:

```text
one FiberOp -> one FiberBlock -> one low-level instruction block role
```

That means `FiberOp` should already be small enough to name a single block-like
obligation:

```text
fragment_sram_read
fragment_route_push
fragment_route_recv
accumulator_prepare
gemm_update
finalize_accumulator
epilogue_relu
store_fragment
```

The current coarse `materialize_fragment` operation is acceptable only as an
early placeholder.  As lowering matures, `StreamOp -> FiberOp` should continue
to refine materialization so that block projection does not need to explode one
semantic FiberOp into a hidden route subgraph.

Required invariant:

```text
Every generated FiberBlock has lineage to exactly the FiberOp that represents
that block-level obligation.
```

Temporary exception:

```text
unresolved materialize_fragment FiberOp
  may project to one unresolved materialization FiberBlock
  until StreamPlan route expansion is implemented.
```

After route expansion exists, the preferred shape is not:

```text
materialize_fragment -> many route/read FiberBlocks
```

but rather:

```text
StreamOp visibility requirement
  -> fiber-level fragment_sram_read / fragment_route_push / fragment_route_recv FiberOps
  -> one FiberBlock per FiberOp
```

This keeps the "flat op is the truth" principle intact.

## Key Invariants

Fiber layer preserves semantic obligations.  Block projection proves how those
obligations are satisfied structurally.

Examples:

```text
FiberDependency(kind=phase_order, expected_satisfaction=subtask_order)
  may be satisfied by accumulator_prepare -> k_stream -> finalize_store subtask order

FiberDependency(kind=carried_state, expected_satisfaction=loop_instance_order)
  may be satisfied by K-loop instance order / carried accumulator state

FiberDependency(kind=fragment_visibility, expected_satisfaction=route_or_local_materialization)
  must be satisfied by fragment route/read materialization actions

FiberDependency(kind=epilogue_order, expected_satisfaction=same_block_order)
  may be satisfied by same-block or local block program order
```

Do not delete semantic dependency edges at fiber construction time.  Lowering can
attach proof/report metadata later:

```text
edge_id -> satisfied_by = subtask_order | loop_instance_order | route_pair | block_order
```

### Projection Coverage

Every `FiberOp` must produce one of:

```text
1. exactly one FiberBlock in the steady state;
2. one explicit unresolved placeholder block in early phases;
3. an explicit unsupported diagnostic.
```

Every `FiberBlock` must record:

```text
source_fiber_op_id
projection_origin = direct_fiber_op | unresolved_placeholder | adapter_synthetic
```

Adapter-synthetic blocks are allowed only in the validation bridge and must not
become semantic source objects.

### No Silent Dependency Deletion

Every `FiberDependency` must produce:

```text
1. a satisfied proof;
2. a pending proof;
3. or an explicit unsatisfied diagnostic.
```

If an edge is considered naturally satisfied by loop instance order, subtask
order, or same-block order, the proof should say so.  It should not disappear.

### Structured Dependency Proof

`satisfied_by` as a single enum is not enough for route/materialization
dependencies.  Use a proof record:

```text
DependencyProof
  source_fiber_dependency_id
  expected_satisfaction
  status = pending | satisfied | unsatisfied
  proven_by:
    - kind = subtask_order | loop_instance_order | route_path
           | block_order | same_block_order
      block_ids?
      stream_plan_edge_ids?
      loop_region_id?
      loop_instance_ids?
      notes?
```

Projected block dependencies should copy the expected satisfaction from the
source `FiberDependency` and attach the proven satisfaction locally, so reports
can be read without jumping back and forth between layers.

### Compatibility Adapter Preconditions

The adapter to old `TileMicroBlock`-compatible rows may run only when:

```text
1. no unresolved materialization placeholders remain;
2. no semantic dependency proof is pending or unsatisfied;
3. every block has stream/tile identity;
4. every loop-body compute/update block has loop_region_id, loop_axis,
   loop_instance_id, and k/fiber coordinate;
5. every route/store/compute block can map to legacy action ids or deterministic
   synthetic validation ids;
6. every block kind is supported by the validation adapter.
```

## Projection Sketch

For one GEMM fiber:

```text
#00 accumulator_prepare
#01 materialize A(k0)
#02 materialize B(k0)
#03 gemm_update(k0)
#04 materialize A(k1)
#05 materialize B(k1)
#06 gemm_update(k1)
...
#13 finalize_accumulator
#14 epilogue_relu
#15 store_fragment
```

Projection should produce block roles similar to:

```text
pre_loop:
  accumulator_prepare block

loop_body k0:
  A fragment materialization route/read blocks
  B fragment materialization route/read blocks
  compute_update block

loop_body k1..kN:
  same shape, different k_block / loop_instance_id

post_loop:
  finalize / epilogue / store block(s)
```

The exact grouping should be conservative:

```text
one FiberOp -> one projected block
```

Do not immediately group finalize / ReLU / store.  Keep them separate in the
debug projection:

```text
finalize_accumulator -> one block
epilogue_relu        -> one block
store_fragment       -> one block
```

Later grouping may be added only behind an explicit projection policy and must
preserve ordered `source_fiber_op_ids` plus internal dependency proof.  Early
grouping is risky because it hides whether `epilogue_order` was truly satisfied.

## Interaction With StreamPlan

`materialize_fragment` FiberOps are not enough by themselves.  They must be
resolved against StreamPlan whole-value visibility topology.

Example:

```text
StreamPlan whole-value path:
  pe00 reads A
  pe00 pushes A -> pe01
  pe01 receives A
  pe01 pushes A -> pe02
  ...

Fiber materialization obligation:
  stream pe02 needs A(m0,k1)
```

Projection should instantiate the same route path at fragment granularity:

```text
pe00 reads/pushes A(m0,k1)
pe01 receives/pushes A(m0,k1)
pe02 receives A(m0,k1)
```

The route topology is inherited from StreamPlan.  The fragment coordinate comes
from FiberOp.

For early phases, materialization can be a two-pass process:

```text
Pass A:
  FiberOp -> unresolved FiberBlock projection

Pass B:
  unresolved materialization block + StreamPlan path
    -> resolved fragment read / push / recv FiberOps or blocks
```

Longer term, route/read/push/recv should be expressed as finer FiberOps before
block projection, so the final projection remains one op to one block.

Fragment route resolution must be isomorphic to the selected StreamPlan
visibility path.  Projection must not invent a new route path:

```text
StreamPlan path:
  pe00 -> pe01 -> pe02

fragment path:
  pe00 push A(m0,k1)
  pe01 recv A(m0,k1)
  pe01 push A(m0,k1)
  pe02 recv A(m0,k1)
```

If multiple StreamPlan paths are possible, the selected visibility ref must
disambiguate them.  Otherwise projection should emit a diagnostic rather than
guessing.

## What This RFC Does Not Do

This RFC does not propose:

```text
1. exposing fiber strategy to user API;
2. changing DFU vendor serializer;
3. treating TileMicroBlock / micro-op / template-bound layers as the new trunk;
4. optimizing fragment fanout or prefetching;
5. replacing legacy GEMM replay logic immediately;
6. making the old backend compatibility adapter the permanent source of truth.
```

The first target is structural equivalence and a clean debug view.

## Suggested Implementation Phases

### Phase 1: Keep Fiber Flat Ops Stable

Current status:

```text
Fiber
FiberOp
FiberDependency
FragmentRef
```

Keep this layer flat.  No additional `MicroFiberDataflowPlan` authority.

### Phase 2: Add Fiber Block Projection Skeleton

Add an experimental projection module under:

```text
compiler/gpdpu_compiler/core/stream_compiler/
```

Possible file:

```text
blocks.py
```

Minimal structures:

```text
FiberBlock
  block_id
  stream_id
  fiber_id
  block_kind
  source_fiber_op_ids
  projection_origin
  placement
  loop_region_id?
  loop_axis?
  loop_instance_id?
  input_fragments
  output_fragments
  input_visibility_refs?
  output_visibility_refs?
  attrs

FiberBlockDependency
  src_block_id
  dst_block_id
  source_fiber_dependency_id?
  dependency_kind = semantic | structural | adapter_required
  expected_satisfaction?
  proven_satisfaction?
  proof_status?
  proof_detail?
```

### Phase 3: Project Existing Sequential-K GEMM Fibers

Start with:

```text
accumulator_prepare -> accumulator_prepare block
materialize_fragment(A/B) -> unresolved fragment materialization block
k update -> compute_update block
finalize/relu/store -> post_loop blocks
```

The output should be easy to compare with current `TileMicroBlock` reports.

Expected dependency pattern:

```text
accumulator_prepare -> gemm_update(k0)
materialize A(k0)  -> gemm_update(k0)
materialize B(k0)  -> gemm_update(k0)

gemm_update(k0)    -> gemm_update(k1)
materialize A(k1)  -> gemm_update(k1)
materialize B(k1)  -> gemm_update(k1)

...

gemm_update(kN)    -> finalize_accumulator
finalize           -> epilogue_relu
epilogue_relu      -> store_fragment
```

The carried state proof must use loop identity:

```text
loop_region_id
loop_axis = k
loop_instance_id
accumulator state identity
```

It must not rely only on `FiberOp.order_index`.

### Phase 4: Resolve Fragment Materialization Against StreamPlan

Use stream-level route topology to refine unresolved materialization into:

```text
fragment_sram_read
fragment_route_push
fragment_route_recv
```

Keep the route path isomorphic with the original StreamPlan.

If this phase still operates on unresolved blocks, each resolved block must keep
lineage to the source unresolved block and source FiberOp.  If this phase has
already been pushed earlier into `StreamOp -> FiberOp`, the result should be
fine-grained FiberOps that later project one-to-one into blocks.

### Phase 5: Compatibility Adapter To Existing TileMicroBlock Shape

Only after the debug block projection is stable, add an adapter that can produce
old-compatible block rows for GEMM-like cases.

This is the potential jump-back point into the existing backend:

```text
FiberBlock projection
  -> TileMicroBlock-compatible objects
  -> TileMicroOpProgram
  -> DFU3500 template binding
```

This is a validation branch.  It is not the desired final trunk.

The adapter should produce a separate compatibility row type rather than forcing
`FiberBlock` itself to carry every old field:

```text
TileMicroBlockCompatRow
  block_kind
  loop_region_id
  loop_instance_id
  loop_axis
  fold_policy
  route_action_ids / compute_action_ids / store_action_ids
  input_visibility_refs / output_visibility_refs
  input_value_refs / output_value_refs
  source_fiber_block_ids
```

`FiberBlock` stays the new debug/proof IR.  `TileMicroBlockCompatRow` is only the
old-backend validation projection.

## Review Questions

1. Should the first block projection be one `FiberOp -> FiberBlock`, or should
   post-loop finalize/relu/store be grouped immediately?

   Recommended answer: one `FiberOp -> FiberBlock`.  Do not group post-loop ops
   in the first projection.

2. Should fragment materialization projection happen in the same pass as block
   projection, or as a second pass that resolves unresolved materialization
   blocks against StreamPlan?

   Recommended answer: use two passes at first.  Long term, push route/read
   expansion earlier so fine-grained FiberOps still project one-to-one.

3. Should `expected_satisfaction` live only on `FiberDependency`, or should the
   projected block dependency carry both expected and proven satisfaction?

   Recommended answer: `FiberDependency` is the source of truth, but projected
   dependencies should copy expected satisfaction and attach structured proven
   satisfaction/proof status.

## Validation Tests

Minimum validation matrix:

```text
1. Single stream, K=1, no route
   expect prepare, local A/B materialize, update, finalize, relu, store

2. Single stream, K>1, no route
   expect carried_state edges proven by loop_instance_order

3. Multi-stream route chain
   StreamPlan path pe00 -> pe01 -> pe02
   target stream pe02 needs A(m0,k1)
   expect fragment route path isomorphic to StreamPlan path

4. A and B routed through different paths
   expect independent visibility proofs before the same gemm_update

5. Post-loop epilogue
   expect finalize, relu, store as separate blocks in early projection

6. Missing visibility path
   expect unsatisfied fragment_visibility diagnostic and no compat adapter output

7. Old GEMM structural comparison
   compare projected compat rows against old TileMicroBlock report
```

## Recommended Decision

Accept the direction.

Use flat fibers as the semantic source, and build a conservative block projection
next.  Keep downstream vendor code untouched until the new block view can explain
the old GEMM K-loop/micro-block structure.
