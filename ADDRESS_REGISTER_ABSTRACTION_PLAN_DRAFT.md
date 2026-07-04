# Address And Register Abstraction Plan Draft

Status: discussion draft.

Date: 2026-07-03

This draft records the next abstraction plan for DFU3500 address and register
lowering. It is intentionally conservative: the goal is to stabilize names,
ownership boundaries, and evidence gates before changing GEMM/GEMM+ReLU address
or register emission again.

## Current Concern

The current source already has useful projection objects:

```text
TensorAccessRef
TensorAccessSpmBinding
RuntimeSpmWindowProjection
StageBaseRowProjection
TileMemoryAccess
OperandHandle
OperandProjectionPath
ContextTileView
FiberEndpoint
```

The risk is that the next refactor may mix several different meanings of
"address" and "register":

```text
SPM byte address
vendor base-address unit
instance_conf_info.base_addr[slot]
CSV base slot
CSV immediate offset
tile row/column/lane coordinate
logical tensor access
storage tensor alias
physical register symbol
logical operand value
reuse operand lifetime
```

If these are treated as plain integers or plain strings, OpenFabric will slide
back toward duplicated vendor-template truth. The next step should therefore be
a small typed plan layer, not a broad scheduler or automatic lowering rewrite.

## Non-Goals

Do not start with:

- automatic `ChipProgramPlan -> FiberActions` lowering;
- a universal register allocator;
- a generic memory-layout optimizer;
- a rewrite of GEMM onto softmax `InstructionStreams`;
- changing vendor instruction semantics without probe or replay evidence;
- replacing customer package or SimICT validation.

The immediate target is to make current address/register facts easier to inspect
and harder to desynchronize.

## Address Model

OpenFabric should keep the address chain split by consumer:

```text
DistributedPlan / DTensor
  -> TensorAccessRef
  -> TensorAccessSpmBinding
  -> StageTensorWindowScope
  -> StageBaseRowProjection
  -> TileAccessPlan
  -> TileMemoryAccess
  -> vendor CSV fields
```

### TensorAccessRef

`TensorAccessRef` is the semantic access:

```text
read(A)
read(B)
read(C)
write(C)
write(Y)
```

It is not a storage location. It must remain distinct from the tensor that owns
SPM storage, because aliases such as GEMM+ReLU matmul output and final output
may share storage while occupying different access roles and vendor slots.

### TensorAccessSpmBinding

`TensorAccessSpmBinding` resolves an access to target-visible storage:

```text
access
storage_tensor_name
TensorMemory
base_slot
element_type
```

This is the first place where type matters. Any offset measured in elements must
be converted with `element_type`, not by assuming fp16. Existing fp16-only
helpers are acceptable as GEMM-local adapters, but they should not become the
generic interface.

### StageTensorWindowScope

This is the missing thin object we should introduce before further base-row
work. It should describe which region of a tensor access is visible to one
stage instance:

```text
StageTensorWindowScope {
  TensorAccessSpmBinding binding;
  int task_id;
  int subtask_index;
  int instance_index;
  uint64_t element_offset;
  uint64_t element_count;        // optional at first
}
```

The important point is not this exact struct shape. The important point is that
the `element_offset` is paired with the binding's element type and storage
tensor. This prevents fp16/fp32 drift.

For current cases:

- GEMM subtask0: output read/prefill scope.
- GEMM subtask1: input A/B K-window scopes.
- GEMM subtask2: output write/store scope.
- GEMM+ReLU subtask3: matmul-output read scope and final-output write scope.
- softmax/log10max: mostly static stage scopes from subtask slot policy.

### StageBaseRowProjection

`StageBaseRowProjection` should stay a projection, not become the source of
stage intent. It answers only:

```text
For this task/subtask/instance, what vendor base address is written into each
base_addr[slot]?
```

It should be produced from `StageTensorWindowScope`:

```text
StageTensorWindowScope
  -> vendor_base_addr =
       spm_binding_vendor_base_addr(binding)
       + vendor_units(element_offset, binding.element_type)
  -> StageBaseRowProjection.bind_access(binding, vendor_base_addr)
```

This is a good first implementation cut because the output is a small binary
surface: `instance_conf_info_file*.bin` and RTL companion rows.

### TileAccessPlan

`TileAccessPlan` is the corresponding PE-local side. It should describe which
tile and lane a PE instruction accesses inside a stage-visible scope:

```text
TileAccessPlan {
  TensorAccessSpmBinding binding;
  DTensorTileRef tile;
  int pe_id;
  int lane;
  int lane_count;
}
```

It should lower to `TileMemoryAccess`:

```text
TileAccessPlan
  -> base_slot
  -> tile_offset
  -> lane_offset
  -> imm_offset
  -> reg_offset
```

This keeps the split explicit:

```text
StageBaseRowProjection owns the large stage base.
TileMemoryAccess owns the PE-local instruction offset.
```

For GEMM, this should eventually make the same matmul ownership fact explain:

```text
runtime materialization window
external DDR layout
instance base row
CSV task address projection
CSV HLDT/HSTT memory refs
```

## Register And Operand Model

The register side has a similar split:

```text
logical tensor/tile value
  -> ContextTileView
  -> OperandProjectionPath
  -> OperandHandle
  -> materialized vendor symbol
  -> RegisterActions emit vendor row
```

## Operand Slot And Content Type Problem

The hard part is not just choosing a symbolic operand name. Fiber tile actions
and register actions are both constrained by two facts at the same time:

```text
which operand slot / symbol is being used
what kind of content lives in that slot
```

The current source already shows several distinct content kinds:

```text
VecH256
  logical half tile chunk loaded by HLDT/HSTT-style block ops

VecH64
  grouped half/scratch value loaded by ILDMT/LDM-style summary ops

VecF32
  fp32 vector compute operand

FiberOperandValue
  scalar or reduction-like PE-local operand tied to a ContextTileView

GEMM operand strip
  ordinary operand/register strip consumed by HMMAL

GEMM tensor tmp accumulator
  tensor-unit tmp state selected by HMMAL/RXINT/TRCTT immediates, not an
  ordinary operand slot
```

These must not collapse into a plain `Operand`. A plain `Operand` only knows
the target-facing symbol and operand class. It does not say whether an opcode is
allowed to consume the value, how many chunks exist, whether `ILDMT` is safe,
or whether a field is an ordinary register versus tensor-unit tmp state.

### External Models To Borrow

Mature compiler systems usually solve this by separating value identity, value
type, operation legality, and final physical register assignment.

The useful lessons are:

```text
MLIR:
  Values have Types. Operations declare operands/results and verify
  constraints through traits/interfaces. The type is not hidden inside a
  register name.

LLVM codegen:
  instruction selection creates target instructions over virtual registers.
  Register allocation later maps virtual registers to physical registers.
  Each virtual register has a register class; instruction operands constrain
  the register classes they can accept.

Triton:
  tensors carry dtype and shape/block information. load/store behavior depends
  on whether the pointer is scalar, tensor-of-pointers, or block pointer.

LLVM TableGen-style target descriptions:
  instruction and register constraints are data, not scattered ad hoc checks.
```

For OpenFabric this suggests a four-layer model:

```text
Value identity:
  which logical value is this?
  Example: input0 tile lane 3, local max, GEMM A strip.

Value content type:
  what kind of payload is in the operand?
  Example: h256 chunk, h64 grouped scratch, f32 vector, GEMM operand strip,
  tensor tmp accumulator.

Instruction contract:
  which value kinds can this opcode consume/produce?
  Example: H2FP consumes H256 and produces F32; FADD consumes F32; HMMAL
  consumes GEMM strips and updates tensor tmp.

Physical materialization:
  which vendor symbol/operand slot/register class does the backend use?
  Example: normal operand, reuse operand, tensor tmp selector, base slot.
```

This means "one operand type" is acceptable only if it is a thin handle that
points to a richer typed value record. It should not be a single universal
payload type that pretends all operands are interchangeable.

### Candidate OpenFabric Model

The likely durable shape is:

```cpp
struct ValueType {
  ValueKind kind;
  ElementType element;
  int lanes;
  int chunks;
  StorageClass storage;
};

struct ValueRef {
  ValueId id;
  ValueType type;
  ContextTileView context;
  OperandProjectionPath projection_path;
};

struct OperandHandle {
  ValueRef value;
  OperandClass operand_class;
  optional<string> legacy_symbol;
};
```

In this model, the "one operand type" is `ValueRef` or `OperandHandle`, but all
interesting decisions inspect `ValueType`.

OpenFabric should probably use a small enum/traits set before introducing a
large class hierarchy:

```cpp
enum class ValueKind {
  H256TileChunk,
  H64ScratchChunk,
  F32Vector,
  F32Scalar,
  GemmOperandStrip,
  GemmTensorTmp,
};

enum class StorageClass {
  NormalOperand,
  ReuseOperand,
  TensorTmp,
  MemoryOnly,
};
```

Then opcode contracts can be encoded as traits:

```cpp
template <typename Op> struct OpContract;

template <> struct OpContract<FAddOp> {
  using Inputs = TypeList<F32Vector, F32Vector>;
  using Output = F32Vector;
};

template <> struct OpContract<H2FpOp> {
  using Inputs = TypeList<H256TileChunk>;
  using Output = F32Vector;
};

template <> struct OpContract<HmmalOp> {
  using Inputs = TypeList<GemmOperandStrip, GemmOperandStrip>;
  using Effect = Updates<GemmTensorTmp>;
};
```

This can stay as C++ templates/overloads for now. Later, if target coverage
grows, these contracts can move toward a table-driven description.

### Why One Plain Operand Type Is Not Enough

A single plain operand type is attractive because it simplifies signatures:

```cpp
Operand fadd(Operand dst, Operand lhs, Operand rhs);
```

But it loses the safety we need:

```text
fadd(H256 chunk, F32 vector) should be rejected.
ILDMT result should not masquerade as a full fp32 vector.
HMMAL tensor tmp should not be an ordinary dst operand.
reuse constants should not be silently allocated like normal operands.
```

The better compromise is:

```text
one common ValueRef / OperandHandle identity object,
plus a required ValueType / ValueKind attached to it,
plus typed wrappers or templates at instruction boundaries.
```

In other words:

```text
unify identity, not payload semantics.
```

### Current Partial Solution

The existing code already uses the right direction for softmax/log10max:

```text
VecH256 / VecH64 / VecF32 are typed wrappers around Operand.
FiberH256Tile / FiberF32Tile carry ContextTileView plus typed chunks.
FiberOperandValue carries ContextTileView plus a local Operand.
OperandHandle carries projection path, operand class, site context, and late
materialization.
```

This is good because symbolic operand tags must remain symbolic. The vendor
assembler later maps CSV operand tags to final PE-local operand RAM indices.
OpenFabric should not pre-bake those final operand RAM indices.

The missing part is a unified value-kind protocol that lets `FiberActions` and
`RegisterActions` agree on what an operand contains.

### Template / Traits Direction

The next abstraction should be a small C++ traits layer, not a full expression
template system. A useful shape is:

```cpp
enum class RegisterValueKind {
  H256TileChunk,
  H64ScratchChunk,
  F32Vector,
  F32Scalar,
  GemmOperandStrip,
  GemmTensorTmp,
};

template <RegisterValueKind Kind> struct RegisterValueTraits;

template <RegisterValueKind Kind> struct TypedOperand {
  Operand operand;
};
```

Then higher-level values can be composed from typed operands:

```cpp
template <RegisterValueKind ChunkKind> struct FiberTileValue {
  ContextTileView context;
  vector<TypedOperand<ChunkKind>> chunks;
};

using FiberH256Tile = FiberTileValue<RegisterValueKind::H256TileChunk>;
using FiberF32Tile = FiberTileValue<RegisterValueKind::F32Vector>;
```

The first implementation does not need to replace current structs immediately.
It can start by adding traits around the existing wrappers:

```text
VecH256 -> RegisterValueKind::H256TileChunk
VecH64  -> RegisterValueKind::H64ScratchChunk
VecF32  -> RegisterValueKind::F32Vector
```

### RegisterActions Should Be Type-Constrained

Register actions should encode opcode legality:

```text
HLDT/HSTT block load/store:
  consume or produce H256TileChunk / block-shaped operands

ILDMT/LDM grouped load:
  produce H64ScratchChunk or another explicitly probed grouped value

FADD/FMUL/FMAX/FLOG2:
  consume and produce F32Vector or scalar-compatible fp32 operands

H2FP/FP2H:
  cross the H256 <-> F32 boundary and must name which half/lane mode is used

HMMAL:
  consumes GEMM operand strips and updates GemmTensorTmp, not a normal dst
  register
```

This suggests overloads or constrained templates such as:

```cpp
VecF32 fadd(VecF32 dst, VecF32 lhs, VecF32 rhs);
VecF32 h2fp(VecF32 dst, VecH256 src, int fp32_lane);
VecH256 load_h256(VecH256 dst, TileMemoryAccess mem);
void store_h256(VecH256 src, TileMemoryAccess mem);
```

The important rule: use templates/overloads to reject invalid combinations at
compile time where possible, and keep runtime context checks for PE/block/tile
ownership.

### FiberActions Should Be Typed Recipes

Fiber actions should describe operator-local recipes over typed values:

```cpp
FiberF32Tile log10_tile(FiberF32Tile input);
FiberOperandValue local_max_from_log10_tile(FiberF32Tile tile);
GemmAccumulatorTile gemm_tile(GemmOperandTile a, GemmOperandTile b, GemmAccumulatorTile c);
```

They should not emit raw CSV fields directly, and they should not erase value
kind into bare `Operand` unless they are calling a target-specific register
action that knows the expected kind.

For GEMM, the type split is especially important:

```text
ordinary operand strip:
  A_reg / B_reg / C_reg symbols

register half:
  ordinary operand slots 0..7 or 8..15

matrix half:
  HMMAL immediate selector for A/B[2047:0] or A/B[4095:2048]

data_select_type:
  tensor-unit compute mode, not a B lane and not an operand register index

tensor tmp:
  accumulator state selected by imm[9:7], not a normal destination operand
```

This means GEMM should probably get a local typed materializer first, rather
than forcing it into the same `VecF32` vector path used by log10max.

### Why Not Expression Templates Yet

Expression templates are tempting:

```cpp
auto y = exp2(min(x * rLog2E, imm100));
```

But the current emitter is side-effecting:

```text
each helper appends CSV rows
each helper may allocate or reuse operand symbols
instruction order matters
normal and reuse operands are different target resources
some pseudo rows expand later inside vendor common_oper
```

So the safer path is:

```text
1. Keep imperative emission.
2. Make values typed.
3. Make register actions accept typed operands.
4. Make fiber actions return typed recipe values.
5. Only then consider expression templates for local arithmetic sugar.
```

### Proposed Implementation Seam

The smallest useful implementation seam is:

```text
TypedOperand<T>
RegisterValueTraits<T>
typed load/store overloads
typed fp32 unary/binary overloads
typed H2FP/FP2H boundary overloads
```

This can coexist with current `Operand` APIs. Existing operators can migrate one
action at a time:

```text
softmax:
  keep VecH256/VecF32 wrappers, add traits

log10max-fp32:
  make fp32 tile chunks explicit instead of returning raw Operand inside VecF32

GEMM:
  introduce GEMM-specific operand-strip and tensor-tmp typed wrappers before
  changing HMMAL loops
```

The success condition is not prettier C++; it is catching invalid combinations
such as "ILDMT as full fp32 vector load" or "HMMAL dst tmp as ordinary register"
before they become invisible CSV bugs.

### ContextTileView

`ContextTileView` ties a planned `DTensorTileRef` to a PE context. It is the
minimum guardrail against accidentally using a value in the wrong PE. Cross-PE
movement should go through explicit endpoints, not through an arithmetic helper
that appears PE-local.

### OperandProjectionPath

`OperandProjectionPath` names the logical value path:

```text
input0.lane_0
output.lane_7
sum.slot_3
shuffle_tmp
```

It is not just a pretty symbol generator. It is the intended durable key for
explaining why two vendor symbols are the same logical operand or why they must
be separate.

### OperandHandle

`OperandHandle` carries:

```text
operand class: normal / reuse
site context: task / subtask / PE / instruction block
projection path
legacy symbol, when preserving vendor naming is necessary
```

The next abstraction should keep legacy symbols as compatibility material, not
as the long-term source of operand identity.

### RegisterActions

`RegisterActions` should remain the target row emitter. It may materialize
operands and write HLDT/HSTT/ILDMT/FMUL/FADD/etc., but it should not decide:

- which tensor tile is being accessed;
- which stage window is visible;
- which PE owns a tile;
- whether an access is read/write aliasing another tensor.

Those belong to plan, stage, tile, and operand objects above it.

## Type Rules

The next code changes should follow these rules:

1. Every tensor access that participates in address lowering must carry
   `TensorElementType` through `TensorAccessSpmBinding` or an equivalent typed
   binding.
2. New generic helpers must convert element offsets with
   `vendor_base_addr_units_for_element_count(element_count, element_bytes)`.
3. Existing fp16 helpers should either remain explicitly GEMM-local or be
   replaced with type-aware helpers before reuse.
4. `TileMemoryAccess` must not assume fp16 when the tile's `DTensor` is fp32.
5. Register chunk counts and lane counts must be named by value type:
   h256/fp16 tile chunks, fp32 SIMD chunks, scalar operand, tensor-unit tmp.
6. Opcode helpers should prefer typed operands over bare `Operand` whenever the
   opcode has content-type restrictions.
7. GEMM tensor tmp state must not be represented as an ordinary destination
   operand.

## Proposed Phases

### Phase 0: Name The Boundaries

No behavior change.

- Add a short design note or expand this draft with the final names.
- Decide whether `StageTensorWindowScope` and `TileAccessPlan` are the right
  names.
- Decide whether the first register traits names should be `RegisterValueKind`,
  `OperandValueKind`, or something more OpenFabric-specific.
- Mark fp16-only helpers as such.
- Record which existing helpers are generic and which are GEMM adapters.

Evidence: documentation review only.

### Phase 1: Type-Aware Base Row Helper

Small behavior-preserving source change.

- Introduce a type-aware helper for:

  ```text
  TensorAccessSpmBinding + element_offset -> vendor base addr
  ```

- Re-express GEMM/GEMM+ReLU current base-row builders through that helper while
  preserving the exact generated instance config binaries.
- Keep GEMM's current subtask-specific branch structure for now.

Evidence:

```sh
cmake --build build --target gemm_refactored_syntax gemm_relu_refactored_syntax
cmake --build build --target refactored_replay_compare_gemm refactored_replay_compare_gemm_relu
```

### Phase 2: StageTensorWindowScope

Introduce the missing stage-window object.

- Convert GEMM subtask0/1/2 and GEMM+ReLU subtask3 base-row derivation to build
  explicit scopes first.
- Keep the same `StageBaseRowProjection` output.
- Add a tiny dump or trace only if it helps compare source facts; do not make a
  dump a new source of truth.

Evidence:

- instance config binaries unchanged or differences classified and explained;
- replay package/support binary comparison for GEMM and GEMM+ReLU.

### Phase 3: TileAccessPlan

Unify CSV memory refs with the same typed access facts.

- Build `TileAccessPlan` before GEMM HLDT/HSTT emission.
- Lower `TileAccessPlan` into existing `TileMemoryAccess`.
- Keep row emission in current GEMM register actions.
- Avoid rewriting GEMM onto softmax-style instruction streams in this phase.

Evidence:

- generated CSV may be inspected, but binary/package/support comparison remains
  the main safety gate;
- no unexplained changes in vendor-visible memory references.

### Phase 4: Register Value Cleanup

Only after address projections are stable.

- Add traits for existing wrappers: `VecH256`, `VecH64`, `VecF32`, and
  `FiberOperandValue`.
- Add typed overloads for the safest register actions first: fp32 binary/unary,
  `h2fp`, `load_h256`, `store_h256`.
- Replace more GEMM legacy register symbols with logical `OperandProjectionPath`
  where comparison remains stable.
- Keep target-specific tensor-unit tmp and HMMAL/TRCTT semantics visible.
- Do not introduce a broad allocator until two operators prove the same need.

Evidence:

- syntax gates;
- replay compare when package/support binaries are touched;
- operator-local trace when register provenance changes but binaries are meant
  to remain stable.

## Smell Tests

Pause if a proposed change does any of the following:

- passes `instance_id * stride` as an untyped integer through several layers;
- computes base slot in one file and CSV memory selector in another from
  unrelated facts;
- assumes fp16 in a helper intended for log10max-fp32 or future mixed-type
  operators;
- passes a bare `Operand` through an opcode whose valid content type is known;
- models HMMAL `dst_tmp` as a normal destination register;
- treats `data_select_type` as a B lane or operand register index;
- uses `ILDMT` as a full fp32 vector load without probe-backed evidence;
- lets `RegisterActions` choose tensor tile ownership;
- lets `StageBaseRowProjection` decide PE-local lane offsets;
- hides cross-PE movement inside a PE-local arithmetic-looking helper;
- treats a debug dump as the durable source of truth;
- changes vendor-visible binaries without a clear comparison story.

## Open Questions

1. Should `StageTensorWindowScope` include byte offsets, element offsets, or
   both? Current preference: element offsets plus typed binding, with byte
   addresses derived only at target projection boundaries.

2. Should `TileAccessPlan` include `TensorAccessRef` directly or only
   `TensorAccessSpmBinding`? Current preference: include the binding so alias
   and base-slot facts remain attached.

3. Should register value type be explicit in `OperandHandle`? Current
   preference: not yet. Start by making tile/fiber value structs carry type or
   chunk shape clearly, then decide whether operand handles need type.

4. Should GEMM A broadcast be a `TileAccessPlan` fact or a separate collective
   / visibility fact? Current preference: keep it target-local and explicit in
   GEMM materializer until `CollectivePlan` has stronger evidence.

5. How much of this belongs in `docs/` versus `drafts/`? Current preference:
   keep this root draft while discussing; promote stable boundary rules to
   `docs/address-binding-projections.md` and implementation tasks to
   `drafts/gemm-dtensor-address-auto-planning-cn.md`.

## Near-Term Discussion Target

Before coding, agree on these three statements:

```text
StageBaseRowProjection is only the stage-instance base table.
TileMemoryAccess is only the PE-local CSV memory reference.
OperandProjectionPath is the logical register/value identity, not merely a
generated symbol name.
```

If these hold, the next implementation step can be deliberately small:

```text
Add one type-aware stage-window-to-base-row helper, then re-express GEMM and
GEMM+ReLU base-row derivation through it without changing outputs.
```
