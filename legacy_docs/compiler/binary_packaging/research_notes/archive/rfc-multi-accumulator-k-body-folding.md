# RFC: Multi-Accumulator K-Body Folding

## Context

Legacy GEMM folds the K loop at the subtask / instance level. The repeated
subtask body includes A visibility, A COPYT route, B load, and C accumulator
update. This is simple and ABI-friendly, but it means loop-body communication is
re-executed for every K instance.

That folding unit is correct for preserving vendor repeat semantics, but it can
miss tile reuse opportunities. A tile can naturally feed multiple output tiles;
if the repeated body only updates one accumulator, reusable A/B visibility may
be consumed too narrowly.

## Idea

Fold a larger K body that updates several output accumulators at once.

Core rule:

```text
Loop folding is not an annotation on repeated compute.
Loop folding is a closed tile microprogram region with explicit carried state.
```

Example shape:

```text
for k in K:
  make A_k visible once
  make B_k0 visible
  make B_k1 visible
  make B_k2 visible
  make B_k3 visible

  C0 += A_k @ B_k0
  C1 += A_k @ B_k1
  C2 += A_k @ B_k2
  C3 += A_k @ B_k3
```

This is a multi-output / multi-accumulator K-body. It keeps the vendor-friendly
subtask repeat model, while improving reuse inside the repeated body.

The symmetric form is also possible:

```text
for k in K:
  make B_k visible once
  make A_k0/A_k1/A_k2/A_k3 visible

  C0 += A_k0 @ B_k
  C1 += A_k1 @ B_k
  C2 += A_k2 @ B_k
  C3 += A_k3 @ B_k
```

The compiler should choose the direction based on which tile visibility is more
expensive to materialize and which output blocking fits operand / instruction
capacity.

## Legacy Evidence

Observed DFU3500 limits:

```text
per PE instruction slots : 4352
per PE exeblock slots    : 32
per PE operand slots     : 1536
operand RAM banks        : 12
entries per bank         : 128
base_addr slots          : 4
```

A legacy single-accumulator `subtask2` compute block has roughly:

```text
loadB      : 16
HMUL       : 16
RXINT      : 16
HMMAL      : 512
TRCTT      : 16
----------------
total      : 576 instructions
```

A four-accumulator body would roughly replicate the compute-side part four
times, while sharing one side of route / visibility. This likely stays below the
4352 instruction-slot limit for the current 64x64-style template, but must be
validated with concrete instruction emission.

## Important Distinction

This is not the same as splitting one output accumulator across four K chunks
and reducing later. That would introduce a new accumulator reduction problem.

The intended form is:

```text
same K instance -> multiple independent output accumulators
```

Each accumulator corresponds to a different output tile. The K loop remains a
serial loop-carried update for each accumulator, but one loop body updates a
small vector of accumulators.

The verifier should enforce:

```text
each carried C_i is a distinct output tile
each C_i has its own self-recurrence along K
there is no cross-accumulator reduction edge
```

## Lowering Implications

`TileLoop` should be modeled as a tile-level microprogram, not merely as an
annotation on a flat action graph.

At the outer level, `ProcessorTileProgram` is an ordered sequence of regular
tile operations and tile loops:

```text
ProcessorTileProgram:
  TileOp*          # prologue / one-shot tile actions
  TileLoop         # repeated tile microprogram
  TileOp*          # epilogue / one-shot tile actions
```

This maps naturally to vendor task structure:

```text
regular TileOp region before loop -> subtask(s) with Instance Times = 1
TileLoop microprogram             -> subtask with Instance Times = repeat
regular TileOp region after loop  -> subtask(s) with Instance Times = 1
```

The loop body is still expressed in tile-level terms. It owns route/load,
compute, and optional store/fused-local actions that execute once per instance.
Each action inside the loop may reference a tile offset expression instead of a
concrete tile index:

```text
tile_k = loop.iv("k")
A_tile(m, tile_k)
B_tile(tile_k, n)
C_acc(m, n)
```

The backend lowers these symbolic per-instance offsets into instance base_addr
rows and instruction immediates.

The loop region should not become an opaque black-box node. It should be a
region in the same tile-action plane:

```text
LoopRegion:
  entry metadata
  body TileAction graph
  carried values
  captures
  iv bindings
```

Passes such as resource analysis, operand binding, base address assignment,
instruction counting, and dependency legalization should still see the body
actions.

`ProcessorTileProgram` should eventually support a folded phase shape like:

```text
TileKBodyPhase:
  loop_axis: K
  repeat: k_tiles
  shared_visibility:
    - A_k visible to processor group
  per_accumulator_visibility:
    - B_k0 visible
    - B_k1 visible
    - B_k2 visible
    - B_k3 visible
  accumulator_updates:
    - C0 += A_k @ B_k0
    - C1 += A_k @ B_k1
    - C2 += A_k @ B_k2
    - C3 += A_k @ B_k3
```

`DFUPackingProgram` should treat the whole folded body as one repeated subtask
candidate, not as separate vendor graph edges between K instances.

## Loop-Body Closure Rule

If a GEMM tile phase is folded into a subtask instance loop, the loop body must
be closed over every per-iteration tile action that the GEMM update needs.

There are two valid shapes.

### Shape 1: Hoisted-Invariant Visibility

```text
prologue subtask:
  load / route all loop-invariant tiles

repeated GEMM subtask:
  only compute repeated accumulator updates
```

Use this only when the loaded / routed tiles are genuinely invariant across the
instance loop. In this shape, the repeated compute body may reference values
materialized by a previous subtask, but those values must not require
per-instance address changes or per-instance route changes.

### Shape 2: Closed Repeated Tile Body

```text
repeated GEMM subtask:
  load / route loop-variant tiles
  compute repeated accumulator updates
  optional per-iteration fused epilogue action
```

Use this when any input tile changes with the instance index. The repeated
subtask body owns all per-instance visibility and compute actions. This is the
legacy-compatible shape for K-body folding.

The invalid middle ground is:

```text
load / route action lives outside the repeated body
but compute inside the repeated body depends on a different tile every iteration
```

That shape breaks because the vendor instance loop only repeats the subtask
body. Any tile visibility that varies with the instance must either be hoisted
only when it is truly loop-invariant, or included in the repeated body.

Legacy GEMM follows the second shape for `subtask2`: A visibility, A COPYT, B
load, and compute are all part of the repeated K body. `subtask1` and
`subtask3` act more like prologue / epilogue around that repeated body.

The verifier should reject ghost visibility:

```text
B[k,n] is used inside K loop but its producer is outside the repeated body.
Move the load/route into the TileLoop body or prove it is loop-invariant.
```

## Compiler Pass Shape

Use two explicit passes.

### Pass 1: KBody Closure Formation

Input:

```text
flat tile action graph
or single-accumulator KBodyPhase candidates
```

Output:

```text
KBodyClosure:
  loop_axis
  repeat_count
  body_actions
  carried_values
  captured_values
  instance_bindings
```

Hard rule:

```text
loop-variant visibility must be inside the repeated body
```

An action must be inside the loop body if it:

```text
depends on the loop IV through address / tile index
depends on the loop IV through route / visibility
produces a PE-local value used by loop-body compute
is a required control predecessor of a loop-body action
```

An action may be hoisted only if it:

```text
does not depend on the loop IV
does not change route / visibility per instance
has lifetime covering the whole loop
does not cross app boundary as PE-local state
is not clobbered by loop-body actions
```

### Pass 2: Multi-Accumulator Body Grouping

Input:

```text
single-accumulator KBodyClosure[]
```

Output:

```text
MultiAccumulatorKBodyClosure[]
```

Conservative grouping requirements:

```text
same loop axis
same repeat count
same task / app context candidate
compatible processor group
same K tile schedule
same shared visibility pattern
independent output accumulators
capacity check passes
```

The grouping pass is optional and semantics-preserving. If grouping fails any
capacity or ABI check, the compiler must emit the original single-accumulator
repeated bodies without changing observable behavior.

Prefer a simple fallback ladder:

```text
try group_size = 4
try group_size = 2
fallback group_size = 1
```

For the current DFU3500 path, keep grouping inside one task context first. Do
not depend on cross-task PE-local reuse until the vendor task / operand context
ABI is fully characterized.

## Vendor Repeat Semantics

K-instance ordering should be represented by vendor instance repeat semantics,
not by explicit graph edges between expanded K bodies.

In IR, it is valid to express:

```text
C_i[k+1] = update(C_i[k], A[k], B_i[k])
```

In vendor packing, this should become:

```text
one repeated subtask
Instance Times = K
carried accumulator lives across instances
```

It should not become:

```text
compute_k0 -> compute_k1 -> compute_k2 -> ...
```

Before relying on larger loop bodies, confirm the vendor ABI repeats the whole
subtask body as an instance unit. Legacy `subtask2` is the key evidence because
it places A visibility, COPYT, B load, and compute in one repeated subtask.

## Verifier Rules

The loop folding verifier should check:

```text
1. loop body closure:
   every loop-variant tile producer is inside the LoopRegion

2. app boundary:
   PE-local carried / captured values do not cross app boundary

3. accumulator independence:
   multi-accumulator grouping does not create partial-K reduction

4. instance isomorphism:
   each instance has the same instruction/dependency/resource shape;
   only base_addr, immediate, tile index, and instance id may vary
```

## Capacity Risks

- Operand residency: multiple C accumulators must remain live together.
- Instruction slots: HMMAL count scales with accumulator count.
- Exeblock layout: the larger body should still fit a small number of blocks.
- Base address slots: only four base address entries exist; multiple tensor
  bases may need to share a region and use instruction immediates for offsets.
- Dependency ABI: route / compute dependencies remain within one repeated body;
  K-instance ordering should not become vendor graph edge fanout.

## Current Recommendation

Keep the first binary-aligned implementation close to legacy:

```text
single-accumulator K-body repeat
```

Then add this as an optimization pass:

```text
single-accumulator KBodyPhase[]
  -> grouped MultiAccumulatorKBodyPhase
```

The pass should be guarded by explicit capacity checks before emitting vendor
ABI rows.

MVP lowering pipeline:

```text
1. identify single-accumulator KBodyPhase
2. form KBodyClosure
3. verify closed repeated body
4. optionally group by shared A or shared B
5. run capacity checks
6. lower LoopRegion to repeated subtask
7. fallback to single-accumulator body when checks fail
```
