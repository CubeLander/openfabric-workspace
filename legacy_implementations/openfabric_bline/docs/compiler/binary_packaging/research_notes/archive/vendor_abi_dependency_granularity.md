# Vendor ABI Dependency Granularity Note

Date: 2026-06-14

## Why We Stopped Here

The current `ProgramVendorABI` prototype exposes non-zero predecessor/successor
overflow:

```text
predecessor_overflow_count = 48
successor_overflow_count = 64
```

This is not a small serializer bug. It is a granularity mismatch.

The current path is accidentally projecting too many tile/action dependencies
into vendor `exeBlock` predecessor/successor slots. A vendor `exeBlock` has a
small fixed graph ABI surface, while the compiler IR deliberately has a richer
tile/dataflow dependency graph.

These are different dependency layers and must not be collapsed mechanically.

## User Intuition To Preserve

The important correction is:

> A tile-level compute block should not have a huge number of ABI graph
> dependencies. Conceptually, one GEMM tile update only needs its local A tile
> and B tile visibility before compute.

Even that statement needs a layer distinction:

- At the **tile IR** level, a compute action may depend on two visible operands:
  A tile and B tile.
- At the **route expansion** level, each visible operand may be produced by a
  chain of route actions.
- At the **vendor exeBlock ABI** level, those route details should usually not
  become predecessor slots.

The current overflow happens because we let several lower-level relations leak
into `vendor_graph_edges`.

## Dependency Classes

We should classify dependencies before vendor ABI projection.

### 1. Operand Visibility Dependencies

Example:

```text
TileRouteAction(A visible)
TileRouteAction(B visible)
  -> TileComputeAction(gemm_k_update)
```

These are true tile semantics. But in vendor ABI, they should normally become
visibility obligations / payload requirements / local materialization ordering,
not ordinary `exeBlock` predecessor slots.

For GEMM, the executable block is not supposed to wait on every fine-grained
route hop through four fixed graph slots.

Important correction:

```text
routeA endpoint
routeB endpoint
  -> compute(A, B)
```

This dependency is real and must be preserved at the program level. The compute
program cannot run before its A/B tile visibility endpoints are materialized.

The problem is not that these dependencies exist. The problem is letting every
internal route step and every loop-carried update become a vendor
predecessor/successor slot.

### 2. Route Step Dependencies

Example:

```text
route hop 0 -> route hop 1 -> route hop 2 -> route hop 3
```

This is a route program order. It is needed for route lowering and instruction
ordering, but it is not a general vendor graph edge between arbitrary exeBlocks.

If route is implemented as sender-push COPY/COPYT, this dependency should be
encoded inside route materialization schedule / instruction order / route
payload plan, not by consuming many predecessor/successor ABI slots.

The required shape is a chain:

```text
route_hop_0 -> route_hop_1 -> route_hop_2 -> route_hop_3
```

The wrong shape is fan-in to every later hop:

```text
route_hop_0 -> route_hop_1
route_hop_0 -> route_hop_2
route_hop_0 -> route_hop_3
route_hop_1 -> route_hop_2
...
```

In other words, `route_hop_3` should depend on `route_hop_2`, not directly on
`route_hop_0`, unless there is a specific hardware/runtime reason to add that
extra edge. For normal path propagation, predecessor is just the previous hop.

### 3. K-Loop Accumulator Dependencies

Example:

```text
C += A[k0] @ B[k0]
C += A[k1] @ B[k1]
C += A[k2] @ B[k2]
C += A[k3] @ B[k3]
```

This should not become four separate strict vendor graph nodes connected by
explicit predecessor slots.

The intended representation is:

```text
subtask repeat / instance loop / folded k-stream
```

The K dimension is a loop carried by subtask/instance structure, not a wide DAG
of ABI graph edges. The compiler may keep accumulator dependencies in
`ProcessorTileProgram` for correctness and audit, but the vendor ABI layer must
fold them into repeated instance execution or PC order.

Stronger rule for current GEMM:

```text
k0 -> k1 -> k2 -> k3
```

is a logical/tile-level accumulator order, but it should lower into:

```text
subtask repeat / instance loop over k
```

It should not produce four independent vendor graph nodes with slot-consuming
dependencies. If the vendor runtime requires sequential execution, that order
belongs in the subtask instance repeat semantics or instruction PC order.

### 4. Store Dependencies

Example:

```text
final C tile -> store tile
```

This is likely a real phase boundary:

```text
k_stream/final compute block -> finalize_store block
```

This kind of edge is a reasonable candidate for a vendor predecessor/successor
slot, because it crosses coarse execution phases.

### 5. Independent DAG Components

Independent tile DAGs should remain independent. Do not introduce artificial
dependencies just because two actions are in the same task, same processor, or
same output operator.

If two output tile waves do not consume each other, there should be no graph
edge between them.

## Correct ABI Projection Principle

`ProgramVendorABI` must not treat `ProgramAsmDependency` as a direct source of
vendor graph edges.

Instead it needs an explicit classification pass:

```text
ProgramAsmDependency
  -> VendorGraphActivationEdge
  -> VendorVisibilityObligation
  -> VendorRouteScheduleEdge
  -> VendorLoopCarriedOrder
  -> VendorLocalInstructionOrder
  -> DroppedAuditOnlyEdge
```

Only `VendorGraphActivationEdge` should consume `exeBlock` predecessor/successor
slots.

## Expected Vendor Slot Shape

For current GEMM, the fixed vendor `exeBlock` slots should mostly describe
coarse block activation, not every tile dependency.

Likely slot-worthy edges:

```text
prologue/materialize -> k_stream
k_stream -> finalize_store
local split role order if split roles exist
inter-block activation edges required by vendor runtime
```

Likely not slot-worthy:

```text
route hop order except where a coarse route block activation edge is required
route endpoint visibility before compute, if represented as same-block/local
  materialization obligation
k0 -> k1 -> k2 -> k3 accumulator chain
same-block local instruction order
parallel independent tile waves
```

Nuance:

If route materialization and compute are placed into different vendor exeBlocks,
then the route endpoint to compute edge may be slot-worthy as a coarse block
activation edge:

```text
route_block(A/B ready) -> compute_block(A,B)
```

But it should be one edge per coarse materialization block, not every internal
route hop projected as graph activation.

## Legacy Evidence

The legacy path already points in this direction.

In `core_legacy/dfu_vendor_graph_abi.py`:

- `EDGE_SLOT_COUNT = 4`.
- The graph ABI rows expose predecessor/successor slots.
- `route_visibility_policy` is explicitly
  `instance_visibility_obligation_not_row_predecessor`.
- Overflow makes a row not serializer-ready.

Then in `core_legacy/dfu_vendor_exeblock_conf_serializer.py`, GEMM serialization
does not blindly trust all symbolic graph ABI edges. It applies
`_legacy_gemm_layouts()` and `_legacy_edge_slots()` to produce a small
legacy-compatible graph shape.

That means legacy effectively performs a GEMM-specific dependency compression /
layout override before bytes.

## What This Means For New Refactor

Before `program_bin.py`, add an ABI normalization step:

```text
ProgramVendorABI
  -> normalize_vendor_dependency_classes()
  -> ProgramVendorABIReadyForBin
  -> ProgramBin
```

The ready-for-bin invariant should be:

```text
predecessor_overflow_count == 0
successor_overflow_count == 0
all slot-consuming dependencies are coarse ABI activation edges
route visibility is represented outside predecessor slots
k-loop order is represented by subtask repeat / instance loop / PC order
```

## Vendor Task/Subtask Planning Questions

The remaining big design question is not just "how to serialize edges"; it is
how to plan vendor tasks/subtasks so the ABI graph naturally stays small.

Current open questions:

1. Should one output tile wave become one vendor task, as in the current
   refactor?

2. Should GEMM use a legacy-like subtask shape?

   ```text
   prologue/materialize
   k_stream_repeat
   finalize_store
   ```

   Or should the new compiler use a smaller shape first?

3. Where do route A/B materialization programs live?

   Possible placements:

   ```text
   same k_stream subtask as compute
   separate materialize subtask before compute
   synthetic prologue/forward split roles like legacy
   ```

4. How is the K-loop represented?

   Preferred current answer:

   ```text
   k_stream subtask with repeat/instances over K
   ```

   Avoid:

   ```text
   one vendor exeBlock per k with explicit graph edges k0->k1->...
   ```

5. What is a vendor `exeBlock` in the new model?

   Candidate:

   ```text
   one exeBlock = one coarse role on one PE within one task/subtask
   ```

   Not:

   ```text
   one exeBlock = every tiny tile route/compute action
   ```

6. How do independent DAG components remain independent?

   Vendor task/subtask packing should not introduce ordering across output tile
   waves or independent tile components unless the runtime launch protocol
   requires it.

Concrete near-term planning target:

```text
GEMM task per output tile wave
  subtask_materialize_or_prologue
  subtask_k_stream_repeat(K instances)
  subtask_finalize_store
```

Then classify dependencies into:

```text
route chain order -> route program local order
route endpoint -> compute operand visibility
k accumulator -> subtask repeat / PC order
final compute -> store -> coarse activation edge if separate block
```

## Open Design Questions

1. Where exactly should route visibility live in the new ABI model?
   - visibility obligations attached to vendor instance rows?
   - noncompute route payload rows?
   - source/destination exeBlock payload annotations?

2. How should K-loop folding be represented?
   - one compute exeBlock with multiple k instances?
   - one subtask with `instances_amount = K`?
   - one folded instruction range replayed over K?

3. Do we need synthetic prologue / split-role exeBlocks like legacy?
   - legacy uses roles such as prologue, source_ld, forward, compute, store.
   - new IR currently maps one packing instance to one asm block, which may be
     too literal for final vendor ABI.

4. What is the minimum ABI-compatible graph for current GEMM?
   - this should be derived by comparing legacy valid edge slots against the
     semantic dependencies in `ProgramVendorABI`.

## Current Recommendation

Do not start real `program_bin.py` yet.

First implement dependency classification and ABI graph normalization. The
compiler can keep the rich tile DAG for review, but vendor binary rows need a
compressed ABI graph.

In one sentence:

> Tile dependencies are compiler truth; vendor predecessor slots are runtime
> activation ABI. They are related, but not the same object.
