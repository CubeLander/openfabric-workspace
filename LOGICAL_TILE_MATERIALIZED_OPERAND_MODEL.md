# Logical Tile And Materialized Operand Model

Status: discussion note, superseded in naming by
`TWO_LEVEL_DTENSOR_NOTES_CN.md`.

Date: 2026-07-04

This note records the working model from the current OpenFabric tile/register
discussion. It is meant to sit beside:

- `ADDRESS_REGISTER_ABSTRACTION_PLAN_DRAFT.md`
- `DFU3500_ADDRESS_COMPOSITION_NOTES.md`

The short version is:

```text
Tile is a logical data/view concept.
Operand is a target-facing materialization concept.
```

Naming update on 2026-07-04: the durable model is now better described as:

```text
Tensor
  -> StreamTensorView
  -> FiberTensorView
  -> TileRef / TypedTileValue
  -> Operand
```

So this note remains useful for the logical-vs-materialized split, but old
`DTensorTileRef` wording should be read as a historical name for the newer
scoped projection model.

More precisely, on the DFU3500 path an `Operand` is not necessarily the final
PE-local operand RAM index. It is a symbolic materialization handle that the
vendor assembler may still map to a physical resource. OpenFabric should
therefore separate logical identity, value content type, instruction legality,
and final vendor materialization.

## Core Split

### Logical Tile

A tile-level object should answer:

```text
Which tensor/view is this?
Which logical tile coordinates does it cover?
Which element type and shape does it carry?
Which PE/context owns this use?
Which stage/window/scope makes the data visible?
```

Current objects in this family include:

```text
DTensorTileRef
ContextTileView
TensorAccessRef
TensorAccessSpmBinding
StageTensorWindowScope
TileAccessPlan
FiberH256Tile
FiberF32Tile
GemmAccumulatorTile context ownership
```

These objects should not be treated as register names. They describe logical
data ownership and visibility.

### Materialized Operand

An operand-level object should answer:

```text
Which target-facing symbol or slot class is used?
Is this a normal operand, reuse operand, tensor tmp selector, or memory-only value?
What content kind lives behind the symbol?
Which instruction contracts allow this value?
How does this preserve or replace legacy vendor symbols?
```

Current objects in this family include:

```text
Operand
OperandHandle
OperandProjectionPath
VecH256
VecH64
VecF32
GEMM local tile operand symbols
GEMM tensor tmp accumulator selectors
```

The important rule is:

```text
Unify identity through handles.
Do not unify payload semantics into one plain Operand.
```

## Four-Layer Model

OpenFabric should keep four facts distinct:

```text
1. Logical tile / view
   DTensorTileRef, ContextTileView, TensorAccessRef, stage/window scope.

2. Logical value identity
   OperandProjectionPath or a future ValueRef.
   Example: input0.lane_3, output.tile, sum.slot_0, gemm.a_strip_5.

3. Value content kind
   H256TileChunk, H64ScratchChunk, F32Vector, F32Scalar,
   GemmOperandStrip, GemmTensorTmp.

4. Target materialization
   OperandHandle, OperandClass, legacy symbol, normal/reuse pool,
   tensor tmp selector, vendor CSV fields.
```

This is close to the usual compiler split between value identity, type,
operation contract, and physical register assignment.

## C++ Shape

The preferred first step is a small typed wrapper and traits layer, not a full
expression-template DSL.

One possible shape:

```cpp
struct H256TileChunk {};
struct H64ScratchChunk {};
struct F32Vector {};
struct F32Scalar {};
struct GemmOperandStrip {};
struct GemmTensorTmp {};

template <class Kind>
struct TypedOperand {
  Operand root;
};

template <class ChunkKind>
struct FiberTileValue {
  ContextTileView context;
  vector<TypedOperand<ChunkKind>> chunks;
};

using FiberH256Tile = FiberTileValue<H256TileChunk>;
using FiberF32Tile = FiberTileValue<F32Vector>;
```

Opcode helpers can then use overloads or constrained templates:

```cpp
TypedOperand<F32Vector> fadd(
    TypedOperand<F32Vector> dst,
    TypedOperand<F32Vector> lhs,
    TypedOperand<F32Vector> rhs);

TypedOperand<F32Vector> h2fp(
    TypedOperand<F32Vector> dst,
    TypedOperand<H256TileChunk> src,
    int fp32_lane);

TypedOperand<H256TileChunk> load_h256(
    TypedOperand<H256TileChunk> dst,
    TileMemoryAccess mem);

void store_h256(
    TypedOperand<H256TileChunk> src,
    TileMemoryAccess mem);
```

For GEMM, use GEMM-specific wrappers instead of forcing tensor-unit behavior
into the same vector path:

```cpp
struct GemmAStrip {
  TypedOperand<GemmOperandStrip> operand;
};

struct GemmBStrip {
  TypedOperand<GemmOperandStrip> operand;
};

struct GemmTensorTmpAccumulator {
  ContextTileView context;
  int tmp_count;
};

void hmmal(
    GemmAStrip a,
    GemmBStrip b,
    GemmTensorTmpAccumulator &acc,
    int data_select_type,
    GemmTensorMatrixHalf a_half,
    GemmTensorMatrixHalf b_half);
```

The goal is to reject invalid instruction combinations early:

```text
fadd(H256, F32) should not compile.
ILDMT grouped scratch should not masquerade as full F32 vector data.
HMMAL tensor tmp should not be modeled as a normal destination operand.
data_select_type should not be confused with a B lane or operand RAM index.
```

## What Templates Should And Should Not Encode

Templates are useful for relatively stable semantic categories:

```text
H256TileChunk
H64ScratchChunk
F32Vector
GemmOperandStrip
GemmTensorTmp
normal/reuse/tensor-tmp materialization class, when stable enough
opcode input/output contracts
```

Templates should not try to encode every dynamic planning fact:

```text
task_id
subtask_index
instance_id
pe_id
tile row/column
runtime window index
stage base address
CSV immediate offset
```

Those belong in plan objects and runtime checks:

```text
ContextTileView
StageTensorWindowScope
TileAccessPlan
TileMemoryAccess
StageBaseRowProjection
```

In short:

```text
C++ types answer "what kind of value is this?"
Plan/view objects answer "where is this value and who owns it?"
Backend materialization answers "which vendor field/symbol represents it?"
```

## Relation To Address Model

The same logic applies to address lowering:

```text
StageBaseRowProjection:
  stage-instance base table, large window movement.

TileAccessPlan:
  logical tile/lane access inside a stage-visible scope.

TileMemoryAccess:
  PE-local CSV memory reference: base slot, reg offset, imm offset.
```

This prevents a single integer from accidentally standing for:

```text
SPM byte address
vendor base-address unit
base_addr slot
CSV imm
tile row
lane offset
element offset
```

## Why Not Expression Templates Yet

Expression templates may be attractive later:

```cpp
auto y = exp2(min(x * rLog2E, imm100));
```

But the current emitter is imperative and side-effecting:

```text
each helper appends CSV rows
each helper may allocate or reuse operand symbols
instruction order matters
normal and reuse operands are different target resources
pseudo rows expand later in vendor common_oper
```

So the safer sequence is:

```text
1. Keep imperative emission.
2. Make values typed.
3. Make register actions accept typed operands.
4. Make fiber actions return typed recipe values.
5. Consider expression-template syntax only after the above is stable.
```

## Migration Strategy

The change should coexist with current APIs.

Near-term path:

```text
1. Add RegisterValueKind or small tag structs.
2. Add traits for existing VecH256, VecH64, VecF32.
3. Add TypedOperand<T> as a thin wrapper around Operand.
4. Add typed overloads for safe register actions first:
   load_h256, store_h256, h2fp, fp2h, fadd, fmul, fmax, flog2.
5. Introduce GEMM-specific typed wrappers:
   GemmOperandStrip and GemmTensorTmpAccumulator.
6. Gradually restrict upper-layer FiberActions from passing bare Operand when
   the opcode value kind is known.
```

Compatibility rule:

```text
Existing Operand APIs may remain as low-level escape hatches.
New operator-facing code should prefer typed wrappers.
```

## Current Risk Signal

Current `VecH256`, `VecH64`, and `VecF32` wrappers can implicitly convert back
to `Operand`. This is useful for incremental migration, but it can also erase
the value kind too early.

Long-term preference:

```text
Only low-level register/materialization helpers should unwrap typed values.
Fiber-level code should pass typed values unless it is intentionally crossing
into a target-specific emission boundary.
```

## Discussion Checkpoints

Before implementing broadly, agree on these statements:

```text
Tile is logical data/view ownership.
Operand is target-facing materialization.
OperandProjectionPath names logical value identity.
Value kind is not the same thing as operand class.
GEMM tensor tmp is not an ordinary destination operand.
Templates should encode value kind and opcode contracts, not dynamic tile
coordinates.
```

If these hold, the first implementation step can be small:

```text
Add a lightweight register-value traits layer around existing wrappers, then
add typed overloads for a few register actions without changing generated CSV.
```
