# Fiber Projection Review Note

Date: 2026-06-19
Status: design note / review routing
Scope: `compiler/gpdpu_compiler/core/stream_compiler`

## Short Answer

Yes, this topic deserves an RFC before implementation goes much further.

The rename from `ir.py` to `stream.py`, the demo dumps, and the flat
`Fiber/FiberOp/FiberDependency` skeleton are small enough to live as development
notes.  But the next step is larger:

```text
flat stream/fiber IR
  -> block projection
  -> existing TileMicroBlock / TileMicroOp / DFU template path
```

That boundary decides how the new architecture reconnects to the old executable
backend.  It is therefore review-worthy.

The current RFC draft is:

```text
docs/compiler/binary_packaging/research_notes/enhancements/rfc-fiber-flat-ops-to-block-projection.md
```

## Why This Needs Review

The key design choice is not naming.  It is authority transfer.

At the fiber layer, the compiler preserves semantic obligations:

```text
fragment visibility
carried accumulator state
phase order
epilogue/store order
```

At the block projection layer, the compiler starts proving how those obligations
are structurally satisfied:

```text
route/local materialization
loop instance order
subtask order
same-block or explicit block dependency
```

If this layer is wrong, later passes may accidentally treat an unsatisfied
semantic dependency as "handled by layout" or "handled by vendor order".  That
is exactly the kind of invisible coupling this refactor is trying to remove.

## What Should Be Sent For Review

Send a narrow RFC, not a giant StreamTilePlan RFC.

Recommended review packet:

```text
1. Fiber remains flat.
2. FiberOp dependencies are semantic obligations, not final backend proof.
3. Block projection is the next compatibility seam.
4. First projection may be conservative: one FiberOp -> one block.
5. Fragment materialization resolution can be a later pass against StreamPlan.
6. Existing vendor serializer / template binding stays untouched.
```

The reviewer should mainly judge:

```text
Is TileMicroBlock-compatible projection the right jump-back point?
Should proof/satisfaction live on projected block dependencies?
Should fragment materialization be resolved during projection or after it?
```

## What Should Not Be Reviewed Yet

Do not ask reviewers to bless:

```text
micro-fiber dataflow as a new authoritative plan
new user API knobs for fiber strategy
DFU serializer changes
optimized fragment fanout / prefetch
full replacement of ProcessorTileProgram
```

Those are either explicitly rejected for the current line, or future work.

## Current Working Decision

For now:

```text
Fiber is the semantic source.
FiberBlockProjection is the next implementation target.
TileMicroBlock remains the compatibility seam.
```

Important refinement after review:

```text
The compatibility seam is a validation branch, not the new trunk.
```

The refactored stream/fiber workflow may temporarily jump back into the existing
`TileMicroBlock -> TileMicroOp -> DFU template` path to prove functional
equivalence.  It should not permanently inherit the old backend's concepts as
its main architecture.  Otherwise the refactor only wraps the debt instead of
removing it.

The desired steady state is:

```text
fine-grained FiberOp
  -> one FiberBlock
  -> one low-level instruction block role
```

So if a `FiberOp` currently projects to many blocks, that is a signal that the
earlier `StreamOp -> FiberOp` lowering is still too coarse.  The preferred fix
is to split the FiberOp earlier, not to hide the split inside block projection.

This gives us a clean bridge:

```text
StreamPlan
  owns inter-stream topology and whole-value visibility

Fiber
  owns stream-local fragment timing and semantic dependencies

FiberBlockProjection
  proves how fiber dependencies map to loop/subtask/route/block structure

Existing backend
  continues from micro-block / micro-op / template-bound lowering
```

## Practical Next Step

Implement `stream_compiler/blocks.py` experimentally:

```text
FiberBlock
FiberBlockDependency
FiberBlockProjection
project_fiber_to_blocks(fiber)
```

Start with one block per `FiberOp`.  Do not group aggressively.  The first goal
is a readable block report that can be compared against current GEMM
`TileMicroBlock` shape, not optimal block packing.

## Implementation Checkpoint

Current experimental implementation:

```text
compiler/gpdpu_compiler/core/stream_compiler/fiber.py
  fine-grained terminal fragment visibility ops:
    fragment_sram_read
    fragment_route_recv
    fragment_route_push reserved for route expansion

compiler/gpdpu_compiler/core/stream_compiler/blocks.py
  FiberBlock
  FiberBlockDependency
  DependencyProof
  FiberBlockProjection
  project_fiber_to_blocks(fiber)
  validate_fiber_block_projection(fiber, projection)
  summarize_fiber_block_projections(projections)
  probe_tile_micro_block_compat(projections)
  summarize_legacy_like_sequence(projections)
```

The demo currently proves:

```text
one FiberOp -> one FiberBlock
local SRAM fragment visibility -> satisfied proof
route-received fragment visibility -> route_path proof from StreamPlan dependency trace
carried accumulator dependencies -> loop_instance_order proof
phase dependencies -> subtask_order proof
epilogue/store dependencies -> same_block_order proof
```

Important implementation detail:

```text
StreamPlan.trace_action_dependencies(action_id)
```

is a derived view over `StreamAction.depends_on`.  It is not a second route
graph and must not become route authority.  The proof says:

```text
this fragment recv uses the already-selected stream-level visibility suffix
```

not:

```text
block projection found a new route path
```

Representative proof shape:

```text
fragment_route_recv(A m0 k0)
  -> gemm_update(k0)
  proof = route_path
  stream_plan_edge_ids = [
    sram_read_A,
    route_push_A,
    route_recv_A,
  ]
```

Focused check:

```bash
python -m py_compile compiler/gpdpu_compiler/core/stream_compiler/*.py
PYTHONPATH=compiler python -m gpdpu_compiler.core.stream_compiler.gemm_demo
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_projection.py
```

This check is intentionally outside the main lowering path.  It protects the
validation view:

```text
one FiberOp -> one FiberBlock
all FiberDependency proofs satisfied
route_path proof derived from StreamPlan depends_on
```

It must not become a reason to route production lowering through
`FiberBlockProjection`.  The main IR remains the flat fiber op sequence.

The aggregate report is also validation-only.  It answers:

```text
How many block-shaped obligations exist across the whole GEMM forest?
How are they distributed by placement, loop instance, and block kind?
Are all semantic dependencies proven?
```

It does not define execution order or become a new plan layer.

The `TileMicroBlock` compatibility probe is one more validation-only view.  It
does not construct old `TileMicroBlock` objects.  It asks:

```text
If we had to compare this branch against old micro-block reports,
which old block kinds could each FiberBlock resemble?
Which old fields would need synthetic validation ids?
Where do old semantics not match the new flat model?
```

Current GEMM probe result:

```text
mapped:
  accumulator_prepare     64
  compute_update          256
  route_forward           384
  route_source_materialize 128
  tile_store              64

unsupported:
  finalize_accumulator    64
  epilogue_relu           64
```

The important findings are:

```text
1. loop_region_id can be synthesized for validation from fiber_id/k-loop shape,
   but should not be backfilled into FiberBlock as old-backend state.

2. old route_forward is sender-executed, while the fiber-level
   fragment_route_recv is endpoint visibility.  The compat view can compare
   them, but production lowering must preserve this semantic distinction.

3. finalize_accumulator and epilogue_relu currently have no direct old
   TileMicroBlock kind.  That is a useful gap report, not a reason to hide them
  by grouping too early.
```

The legacy-like sequence report gives a coarse old-shape rhythm without
constructing old objects:

```text
pre_loop:
  accumulator_prepare 64

K loop body, uniform across k=0..3:
  route_source_materialize 32
  route_forward 96
  compute_update 64

post_loop:
  tile_store 64

explicit new semantics with no old direct block kind:
  finalize_accumulator 64
  epilogue_relu 64
```

This report is useful because it separates:

```text
old-shape comparable blocks:
  route/source/compute/store rhythm

new explicit fiber semantics:
  finalize and epilogue
```

It should remain an A-line probe/report, not a lowering plan.
