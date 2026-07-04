# GEMM FiberOp Design Notes

## Context

The refactored GEMM device program is now flattened enough that the real
operator shape is visible. The current active source is:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_refactored/operator_sources/gemm/device_program/main.cpp
```

The current code still emits vendor CSV rows directly through
`VendorCsvActions`. That is intentionally lower-level than the softmax
refactor, where operator logic is expressed through `EmitSite`,
`RegisterActions`, and `FiberActions`.

This note records a first design direction for the missing GEMM fiberop layer.
It is a design draft, not a final API contract.

## Softmax Reference Shape

Softmax currently has a useful split:

```text
main.cpp
  creates EmitSite
  locates DTensor tiles
  calls site.fiber.* semantic actions
  writes InstructionStreams to CSV

softmax_template_program.h
  declares DistributedPlan
  declares EmitSite
  attaches RegisterActions and operator-specific FiberActions

softmax_fiber_actions.cpp
  implements operator-specific fiber actions using register actions
```

The important property is not the file split. The useful abstraction shape is:

```text
DTensor tile refs
  -> typed fiber values
  -> register actions
  -> vendor instruction streams / CSV
```

Softmax fiber actions return values such as `FiberInputTile` and
`FiberScratchValue`, so the call site describes the operator dataflow instead
of directly listing vendor opcodes.

Example shape:

```cpp
const FiberInputTile input_tile = site.fiber.load_tile(x_tile);
const FiberScratchValue local_sum =
    site.fiber.softmax_tile_to_local_scratch_value(input_tile, sum_tile);
site.fiber.materialize(local_sum);
```

For GEMM, the equivalent abstraction should expose the distributed tile GEMM
intent while preserving the PE cooperation rules that make this vendor case
work.

## Current GEMM Device Facts

The flattened GEMM device program naturally separates into three vendor
subtasks:

```text
subtask1:
  load C tile per PE
  materialize ALPHA and BET immediates
  scale C by BET

subtask2:
  load A tile at A broadcast roots
  copy A within 4-lane broadcast groups
  load B tile per PE lane
  scale A by ALPHA
  run HMMAL/TRCTT accumulator program over 8-lane MMA groups

subtask3:
  store C tile per PE
```

Current important layout/cooperation facts:

```text
tile lanes: 16
MMA group lanes: 8
A broadcast group lanes: 4
A root PEs: 0, 4, 8, 12
A copy route: group-local chain 0->1->2->3
B load: lane-local, based on pe_id % 8
C load/store: PE-local, based on task_id and PE group/lane
```

The key observation: the GEMM fiberop is not one `HMMAL` instruction. It is
also not the whole device program. The useful semantic layer is one atomic tile
GEMM action:

```text
C_tile = beta * C_tile + alpha * (A_tile x B_tile)
```

with explicit NoC/PE cooperation facts:

```text
A is loaded once per broadcast group and copied across the group.
B is loaded per PE lane.
C is loaded/stored per PE.
MMA accumulation is scheduled across 8-lane MMA groups.
```

These cooperation facts are real and must stay visible to the lowering code.
They should not automatically become separate semantic FiberOps.

## HMMAL Operand And Compute Mode Model

The current evidence and code discussion resolve the confusing HMMAL parameter
names from the vendor template.  A HMMAL row should be read as a tensor-unit
micro-op over operand strips, not as a normal register arithmetic instruction:

```text
HMMAL(src0_reg, src1_reg, dst_tmp, data_select_type, a_half, b_half)
```

The roles are:

```text
src0_reg          ordinary operand/register strip carrying Matrix A data
src1_reg          ordinary operand/register strip carrying Matrix B data
dst_tmp           tensor tmp accumulator selected by imm[9:7]
a_half / b_half   lower or upper 2048-bit half inside the 4096-bit A/B operand
data_select_type  tensor-unit compute/data-selection mode selected by imm[6:4]
```

`data_select_type` is not an outer B lane and should not be named as a lane.
For a fixed pair of A/B operand strips, HMMAL still has to issue multiple
internal matrix micro-ops.  The compute mode chooses how the tensor unit pairs
internal fragments or scalar groups from the selected A half and B half.  Those
internal pairings collectively cover the element combinations required by the
matrix multiply.

In the vendor GEMM template, the same loop index happens to select both the B
operand strip and the `data_select_type`.  That is a template coincidence, not a
semantic identity.  The lowering code should keep these names separate, even
when their numeric values are equal for the dense GEMM case.

The exact mapping from `data_select_type0..7` to internal fragment/scalar
pairings is still not confirmed in the available hardware notes.  Dense GEMM
appears to need the full set for each relevant A/B strip pair.  Other tensor
operators may legally use only a subset if their intended tensor microprogram
does not need every pairing.

## Legacy B-line Intent

The archived B-line material is not the active implementation path, but it is
useful design evidence for the intended abstraction boundary. Its consistent
direction is:

```text
GEMM no-ReLU:  gemm_tile -> store_tile
GEMM+ReLU:     gemm_tile -> relu_tile -> store_tile
```

At that layer, `gemm_tile` is an atomic tile job. K-loop updates, accumulator
prepare/finalize, HMMAL/TRCTT rows, root/copy/load roles, and vendor subtask
staging are template or physical lowering details. The lowering may expand one
`gemm_tile` into a closed template span, but the span must preserve provenance
back to the single `gemm_tile` op instead of reintroducing many internal
FiberOps.

The same legacy notes explicitly keep post-ops as separate tile jobs. ReLU,
bias, clamp, elementwise chains, reductions, and store are not hidden flags
inside GEMM. They form an ordered op-chain after the GEMM tile output.

This slightly changes the first active refactor target:

```text
public semantic chain:
  gemm_tile -> store_tile

target-local GEMM materializer:
  C load / beta scale
  A root load and group broadcast
  B lane load
  alpha scale
  HMMAL/TRCTT accumulator template span

target-local store materializer:
  C store rows
```

So the first durable object should still be called `GemmTileFiberOp`, but it
should represent the atomic GEMM tile action, not only subtask2's visible
microkernel rows.

## Candidate First API

Keep the first GEMM API target-aware and close to the active vendor evidence.
Do not jump directly to a universal matrix IR.

```cpp
struct GemmTileOperands {
  DTensorTileRef input0_tile;
  DTensorTileRef input1_tile;
  DTensorTileRef output_tile;
};

struct GemmTileFiberOp {
  GemmTileOperands operands;

  int tile_lanes;
  int mma_group_lanes;
  int input0_broadcast_group_lanes;

  float alpha;
  float beta;
};
```

The first lowering surface can stay simple:

```cpp
emit_gemm_tile_fiberop(site, op);
```

`site` remains responsible for target-local placement answers:

```text
task_id
pe_count
input/output register names
input/output base addresses
element strides
vendor lane addresses
A broadcast root/copy predicates
```

`op` expresses the operator-level GEMM tile intent, already bound to concrete
DTensor tile operands, plus the cooperation parameters needed by the DFU3500
materializer:

```text
tile_lanes
mma_group_lanes
A broadcast group size
alpha / beta
input/output tensor tile refs
```

This is deliberately not yet a generic `FiberOp` base class. It is a concrete
GEMM tile description that can later be made common after a second operator
proves the same shape.

## Operand Binding From Context

The operand selection rule should follow the softmax shape:

```cpp
const ExecutionSite execution_site = site.current_site();
const DTensorTileRef x_tile = program.input(name).locate(execution_site);
```

For GEMM, the context is richer, but the source of truth should be the same
kind of object:

```text
task_id
subtask_index
instance / K-step when present
PE coordinate
role-local PE group/lane coordinate
original tensor slicing and layout
```

The GEMM emitter should therefore build operand refs before it enters vendor
row materialization:

```cpp
const GemmOutputTileContext output_tile = program.gemm_output_tile_for_site(site);
const GemmTileOperands operands = site.locate_gemm_tile_operands();
const GemmTileFiberOp op{operands, ...};
site.fiber.gemm_tile(op);
site.fiber.store_tile(op);
```

The output tile is not chosen by the GEMM row writer. It is assigned by the
macro plan: task partitioning, output tensor sharding, tile ownership, and PE
placement decide which output tile this site owns. GEMM operand binding starts
from that output tile ownership fact.

`locate_gemm_tile_operands()` may derive different role-specific sites from the
same output tile context:

```text
output_tile site:  task + output PE lane/group
input0_tile site:  task + A broadcast root/group projection
input1_tile site:  task/K + B lane projection
```

That projection belongs in the distributed plan / GEMM site layer. The vendor
materializer can ask the operand refs for tensor memory, tile position, stride,
lane-local offsets, and register naming, but it should not be the authority for
choosing which logical tensor slice is being consumed.

The intended authority chain is:

```text
chip/program macro plan
  -> output tile ownership and PE placement
  -> role-specific operand tile refs for A/B/C
  -> gemm_tile semantic action
  -> DFU3500 materializer stages
  -> vendor CSV/template rows
```

This keeps the source of truth aligned with softmax: first locate distributed
tensor slices from context, then emit target rows from those located operands.

## Relation To Softmax

The softmax pattern suggests a future GEMM shape like:

```cpp
struct GemmEmitSite : app_builder::VendorEmitSite<GemmDistributedPlan> {
  using RegisterActions = app_builder::RegisterActions<GemmEmitSite>;

  struct FiberActions : app_builder::FiberActions<GemmEmitSite> {
    GemmTileValue gemm_tile(...);
    void store_tile(...);
  };

  RegisterActions reg;
  FiberActions fiber;
};
```

The implementation of `gemm_tile(...)` can still call a target-local
materializer that writes the C load/beta, A root/copy, B load, alpha, and
HMMAL/TRCTT rows. Those are materializer stages, not public FiberActions.

This should still be a later step. The current GEMM row format uses
vendor-specific CSV headers and extra columns, and it writes multiple CSV files
per subtask according to root/copy/load/compute roles. Jumping immediately to
softmax-style `InstructionStreams` may obscure important GEMM placement facts.

## Proposed Migration Steps

1. Keep the current flattened `main.cpp` as the truth-preserving baseline.

2. Extract data-only `GemmOutputTileContext`, `GemmTileOperands`, and
   `GemmTileFiberOp` objects next to `GemmSubtaskSite`.
   This should not change generated output.

3. Replace repeated literal configuration in `main.cpp` with a single local
   `GemmTileFiberOp op` whose operands come from context-derived DTensor refs.
   Examples:

   ```text
   tile_lane_count()
   mma_group_lane_count()
   input0_broadcast_group_lanes
   ALPHA/BET policy
   macro-plan output tile context
   input0/input1/output tile refs derived from that context
   ```

4. Keep the public semantic chain small:

   ```text
   gemm_tile -> store_tile
   ```

   Inside the `gemm_tile` materializer, keep named stages for C load/beta,
   A/B materialization, and HMMAL/TRCTT only as lowering structure and debug
   evidence.

5. Once the tile op is explicit, decide whether GEMM can share the softmax
   `EmitSite + RegisterActions + FiberActions` model directly, or whether GEMM
   needs a lower-level "multi-template fiber action" concept because one
   semantic operation writes several PE/template CSV streams.

6. Only after binary comparison stays stable should we move opcode row emission
   from `site.csv.*` toward typed register actions.

## Open Questions

1. Should `beta * C` be part of `GemmTileFiberOp`, or should it be represented
   as a separate epilogue/prologue action?

   Legacy B-line intent favors keeping it inside `gemm_tile` because
   `alpha * A * B + beta * C` is GEMM semantics, not a separate post-op. The
   active vendor materializer may still implement it in subtask1.

2. Does GEMM need a new "distributed fiber action" layer above softmax-style
   per-PE `InstructionStreams`?

   Current evidence suggests yes. Softmax emits one CSV per PE per subtask.
   GEMM emits different CSV roles: C preload, A roots, A copies, B loads,
   compute templates, and stores. That is more like a role-partitioned
   distributed materializer under one semantic tile action.

3. Should A broadcast be represented as a tensor layout fact or as a GEMM
   microkernel cooperation rule?

   Current evidence favors treating it as a target-local visibility and
   cooperation rule first. It should be explicit in the GEMM materializer, but
   not as a separate public FiberOp.

4. When should `conf_PEmap.h` disappear from config/graph/SPM replay?

   Not in the first GEMM fiberop step. Device-side derivations are already
   independent of that header, but config/graph/SPM replay still uses it as
   vendor evidence.

## Current Preference

The next implementation step should be conservative:

```text
Introduce GemmTileFiberOp as a local semantic object.
Use it to name the current tile-lane, MMA-lane, broadcast, alpha, and beta
facts.
Treat gemm_tile as the public atomic tile job and store_tile as the public
store job.
Keep C preload/beta, A broadcast, B load, HMMAL/TRCTT, and vendor subtasks as
named materializer stages under gemm_tile.
Choose input0/input1/output operands from softmax-like context location before
vendor row emission; do not choose logical tensor slices from hand-written base
address arithmetic inside the CSV materializer.
Treat output tile ownership as a macro-plan result. GEMM operand binding starts
from that output tile and derives A/B/C tile refs from tensor layout and
role-specific placement rules.
Do not yet introduce a generic FiberOp hierarchy.
Do not yet rewrite GEMM onto softmax InstructionStreams.
Keep binary comparison as the guardrail after every small step.
```

This gives us a concrete object to discuss and refine while preserving the
current vendor-equivalent output.
