# Tile Scope / Value / View Tension

Status: draft.

This note records an open design direction for the compiler IR. The core issue
is a structural tension in the current tile-centered model:

```text
Layer 3 wants to plan at tile granularity,
but real tensor instructions often produce values smaller than a tile,
and those smaller values can later be reassembled into a tile-shaped view.
```

This is not just a naming issue. It affects how we represent GEMM, fused local
ops, reductions, tensor tmp registers, debug traces, and future lowering.

## The Tension

The earlier Layer 3 design was tile-centered:

```text
input tile(s)
  -> compute
  -> output tile
```

That is friendly for scheduling, review, COPY/broadcast planning, and task /
subtask slicing. But tensor compute does not always produce a full materialized
tile as its immediate result.

For example, HMMAL-style matmul reduction may compute into `tmp0..tmp7`, or into
smaller fragment/partial values. A conceptual `64x64` C tile may actually be
formed from many internal values:

```text
v0, v1, v2, v3, ...
  -> arranged by tensor tmp / fragment layout
  -> viewed as C_tile
```

So the contradiction is:

```text
Tile is the useful planning and review unit.
Value is the real producer/consumer unit for many hardware operations.
```

If the IR only has tiles, it hides important hardware state. If the IR only has
fragments/values, it becomes unreadable and loses the structure that makes tile
scheduling tractable.

## Working Response

Keep Layer 3 tile-centered, but make each tile a scope that can contain a
structured value graph.

```text
TileScope
  inputs:
    TileValue / TileView / SummaryValue / external refs

  internal values:
    FragmentValue
    TmpValue
    SummaryValue
    TileView

  outputs:
    TileView or MaterializedTile
```

The key shift is:

```text
Tile is not always a materialized object.
Tile can also be a structured view over smaller values.
```

## Tile As A Union Container

The stronger model is:

```text
Tile = a schedulable union container for values that belong to one logical
       tensor region.
```

A tile is not merely a rectangular buffer. It is an identity and ownership
domain:

```text
TileIdentity:
  tensor / logical output name
  coordinate range
  owner PE / mesh placement
  member values
  layout relation between members and tile coordinates
  completeness state
  materialization state
```

Under this model, a fragment is not created outside a tile and later attached to
one. A fragment is born with an owner tile:

```text
%frag0 = HMMAL_fragment(...)
%frag0.owner_tile = C_tile[0:64,0:64]
%frag0.coverage = C_tile rows/cols or tensor-tmp fragment region
```

The moment the system creates `%frag0`, the owning tile becomes visible to the
scheduler:

```text
C_tile.members = [%frag0]
C_tile.state   = partially_produced
```

As more values appear, the same tile changes state:

```text
no members
  -> partially_produced
  -> view_ready
  -> materialized
  -> stored / released
```

This answers the structural tension directly:

```text
Fragments are members of a tile.
The tile is the union of its member values.
TileView is a way to interpret that union as a tile-shaped object.
```

The scheduler can still schedule tiles, but tile readiness and resource pressure
are driven by member values. A tile is schedulable because it has an identity and
dependency boundary; it is usable because its union can provide the view required
by a consumer.

## Creating Values

Any op that creates a non-tile value should answer four questions:

```text
1. Which tile owns this value?
2. Which region or fragment of that tile does it cover?
3. Which storage/resource class holds it?  tmp, operand, SPM, summary, etc.
4. Does adding this value make a new TileView available?
```

For example:

```text
%tmp0_fragment = HMMAL(...)
  owner_tile = C[0:64,0:64]
  storage    = tensor_tmp0
  coverage   = hmmal64_layout.fragment(tmp0)

%tmp1_fragment = HMMAL(...)
  owner_tile = C[0:64,0:64]
  storage    = tensor_tmp1
  coverage   = hmmal64_layout.fragment(tmp1)

%C_view = tile_view(C[0:64,0:64], layout=hmmal64_tmp_layout)
  available when required tmp fragments exist
```

So `TileView` is not a bag of arbitrary values. It is a view over one tile's
union of owned member values.

## Value Kinds

LogicalTensor:

```text
Global tensor meaning, such as A, B, C, Y.
```

TileValue:

```text
A tile-shaped value that the planner can schedule as a unit.
It may be materialized in operand/SPM, or it may be a higher-level reference.
```

FragmentValue:

```text
A smaller piece produced/consumed by instruction-level lowering.
Examples:
  HMMAL fragment result
  operand strip
  one part of a 1x4 @ 4x1 micro matmul
```

TmpValue:

```text
Tensor tmp state, such as tmp0..tmp15.
This is not a normal operand tile, but it can hold partial tile content.
```

SummaryValue:

```text
A reduced value smaller than the source tile.
Examples:
  local max over a tile
  local sum / sumsq
  partial reduce scalar/vector
```

TileView:

```text
A structured view over existing values.
It does not necessarily allocate or materialize new storage.
It says: these values can be interpreted as one tile-shaped object.
```

MaterializedTile:

```text
A tile-shaped value that has been explicitly written into ordinary operand RAM,
SPM, or output memory.
```

## Example: Reassembling Values Into A Tile

Suppose a micro matmul computes several smaller values:

```text
%v0 = matmul_micro(A0_1x4, B0_4x1)
%v1 = matmul_micro(A1_1x4, B1_4x1)
%v2 = matmul_micro(A2_1x4, B2_4x1)
%v3 = matmul_micro(A3_1x4, B3_4x1)
```

Those values can be reassembled as a tile-shaped view:

```text
%C_view = tile_view(
  values=[%v0, %v1, %v2, %v3],
  shape=(tile_m, tile_n),
  layout=some_tensor_tmp_or_fragment_layout,
)
```

Later ops should be allowed to consume `%C_view` as a tile:

```text
%Y_view = relu(%C_view)
store_tile(%Y_view, Y_out)
```

This avoids forcing a premature materialization step:

```text
fragment values -> materialized C tile -> reload C tile -> relu
```

when the backend may be able to fuse or lower through the view.

## Example: HMMAL

The tensor instruction notes tell us that HMMAL writes tensor tmp state selected
by `imm[9:7]`.

Layer 3 can describe the high-level tile scope:

```text
TileScope C[m:n]

inputs:
  A_tile
  B_tile

internal:
  %tmp0..%tmp7 += HMMAL(A_fragments, B_fragments)
  %C_view = tile_view(values=[%tmp0..%tmp7], layout=hmmal64_tmp_layout)

outputs:
  C_tile_view = %C_view
```

The instruction lowerer is responsible for:

```text
RXINT   C operand strip -> tmp group, if initialization is needed
HMMAL   A/B operand strips -> tmp0..tmp7
TRCTT   tmp group -> materialized C/Y operand strip, if materialization is needed
```

So debug dumps can stay human-readable:

```text
produce C_tile_view from HMMAL tmp values
```

while the lowerer still has enough information to emit tensor instructions.

## Current PE00 Trace Observation

The current debug trace for:

```text
tmp/gpdpu_compiler_examples/gemm_relu/debug_ir/pe/PE00.trace.txt
```

already points in this direction.

Layer 3 is tile-centered:

```text
TILE tile0 wave=wave0 task=0 output=y0->%t2:Y[m=0:64,n=0:64]
  inputs:
    a0 = A[m=0:64,k=0:256] via row_broadcast split=Kx4
    b0 = B[k=0:256,n=0:64] via column_broadcast split=Kx4
  compute:
    c0 = matmul_reduce_k(a0, b0) -> %t1:Cacc[m=0:64,n=0:64]
    y0 = relu(c0) -> %t2:Y[m=0:64,n=0:64]
```

This is good for human review: the reader sees one output tile, its input tile
streams, and its fused local post-op.

Layer 4 currently expands K instances:

```text
KSTEPS tile0 wave=wave0 task=0 acc=%t1:Cacc[m=0:64,n=0:64]
  inst0:
    C_acc += HMMAL(A[m=0:64,k=0:64], B[k=0:64,n=0:64])
  inst1:
    C_acc += HMMAL(A[m=0:64,k=64:128], B[k=64:128,n=0:64])
```

This is still readable, but it hides the union-container semantics. In the new
model, each HMMAL update should be seen as creating or updating member values of
`tile0`:

```text
Tile tile0 = %t1:Cacc[m=0:64,n=0:64]

members:
  inst0.tmp_fragments -> owner_tile=tile0
  inst1.tmp_fragments -> owner_tile=tile0
  inst2.tmp_fragments -> owner_tile=tile0
  inst3.tmp_fragments -> owner_tile=tile0

views:
  c0 = tile_view(tile0, layout=hmmal64_tmp_layout)
  y0 = relu(c0) -> tile_view(%t2:Y[m=0:64,n=0:64])
```

So a future debug dump should not merely say:

```text
C_acc += HMMAL(...)
```

It should make the ownership relationship explicit:

```text
VALUE v0 = HMMAL(A_k0, B_k0)
  owner_tile = tile0
  storage    = tmp0..tmp7
  contributes_to = c0

VIEW c0 = tile_view(tile0.members, layout=hmmal64_tmp_layout)
VALUE y0 = relu(c0)
  owner_tile = tile0 or output_tile_y0
```

This does not mean the trace should dump every micro-fragment by default. The
important part is the model:

```text
HMMAL produces/updates tile-owned values.
The tile is the union container.
The tile view is what later ops consume.
```

For the current `gemm_relu` trace, the immediate engineering improvement would
be to rename Layer 3 from "TILE-CENTERED COMPUTE PLAN" to something closer to:

```text
LAYER 3: TILE SCOPES
```

and make each tile section show:

```text
TileScope tile0 owns %t1:Cacc[m=0:64,n=0:64]
  inputs:
    A stream, B stream
  member producers:
    inst0..inst3 HMMAL tmp fragments
  views:
    c0 = tile_view(tile0)
    y0 = relu(c0)
  materialization:
    y0 -> %t2:Y[m=0:64,n=0:64]
```

Layer 4 can then become a lower-level expansion of the member producers, rather
than a separate conceptual model.

## Example: log10 -> max -> maximum

For signal-style fused ops:

```text
%L_tile = log10(%X_tile)
%local_max = reduce_max(%L_tile)
%global_max = all_reduce_max(%local_max)
%Y_tile = maximum(%L_tile, %global_max)
```

Here `%local_max` and `%global_max` are not tiles. They are `SummaryValue`s. But
they still live inside the tile-centered program and can feed later tile-shaped
work.

This means the IR must allow a tile scope to produce both:

```text
tile-shaped views
smaller summary values
```

and must allow later tile computation to consume summary values.

## Why This Helps

This model preserves both sides of the system:

```text
Tile-centered planning:
  good for scheduling, human review, task/subtask slicing, collective bundles.

Structured values:
  good for tensor tmp, fragments, reductions, fusion, and avoiding fake
  materialization.
```

It also gives future compiler passes a clean question to answer:

```text
Can this op consume the TileView directly,
or must the view be materialized into an ordinary TileValue first?
```

That is exactly the boundary between high-level tile IR and backend lowering.

## Open Design Questions

1. What is the minimal set of value kinds V1 needs?
   Current likely set:
   `TileValue`, `TmpValue`, `SummaryValue`, `TileView`, `MaterializedTile`.

2. Should `TileView` be first-class in `plan.json`, or only in debug dumps and
   lowering internals?

3. How much layout detail belongs in `TileView`?
   It probably needs at least:
   shape, element dtype, value list, value-to-tile layout, and materialization
   requirements.

4. When should a `TileView` be forced to materialize?
   Possible triggers:
   cross-PE communication, store to SPM/output, unsupported consumer op, subtask
   boundary, tmp pressure overflow.

5. Can collective bundles operate on `SummaryValue`, or should they always wrap
   summaries into a tiny tile-shaped view?

6. How should debug trace Layer 3 present this without becoming too noisy?
   A likely human-readable form is:

```text
TileScope C[0:64,0:64]
  inputs:
    A_tile, B_tile
  values:
    tmp_group = HMMAL(A_fragments, B_fragments)
    C_view = tile_view(tmp_group, layout=hmmal64)
  output:
    Y_tile = relu(C_view)
```

## One-Sentence Draft

Layer 3 should be a tile-centered structured value graph: tiles remain the unit
of scheduling and review, while fragments, tensor tmp values, and summaries are
allowed to exist inside a tile scope and can be reassembled into tile-shaped
views for later computation.
