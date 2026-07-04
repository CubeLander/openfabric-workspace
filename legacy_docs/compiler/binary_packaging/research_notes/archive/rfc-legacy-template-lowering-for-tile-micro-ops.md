# RFC: Integrate Legacy GEMM Execution Templates Into Tile Micro-Op Lowering

Date: 2026-06-14

Status: Accepted with amendments

## Context

The refactored DFU-first pipeline now has an explicit lowering path:

```text
ChipProgram
  -> ProcessorLogicalProgram
  -> ProcessorTileProgram
  -> ProgramNodeProgram
  -> DFUPackingProgram
  -> ProgramAsm
  -> ProgramVendorABI
  -> ProgramBinRows
  -> ProgramBinComponents
```

Two major structural decisions are already in place:

1. `TileLoopRegion` is the authority for folded K-loop repeat.
2. `TileMicroBlock` is the authority for executable block boundaries.

The binary side can now emit two instruction modes:

```text
native_symbolic
  - structural smoke mode
  - emits OP_GINST rows
  - not functionally executable

legacy_gemm_compat
  - emits real vendor inst_t rows
  - currently selects canonical legacy CSV-derived instruction templates
  - still marked runtime-validation-blocked
```

The latest golden summary diff compares:

```text
legacy vendor build_out gemm_template_fusion/simulator_bin
vs
OpenFabric legacy_gemm_compat bundle
```

At ABI component level:

```text
component sizes: match
active exeBlock count: 256 vs 256
HMMAL count: 32768 vs 32768
STD count: 4096 vs 4096
```

But the instruction stream is not yet semantically complete:

```text
legacy active inst count:    53376
OpenFabric active inst count: 45056

legacy has:
  IMM   128
  HMUL  2048
  RXINT 1024
  TRCTT 1024

OpenFabric currently lacks these op classes.

OpenFabric also has:
  COPY 6144 vs legacy 3072
  LDN  2048 vs legacy 9216
```

This is not primarily a byte serializer problem.  The `inst_t` struct packing
now works.  The remaining problem is the ownership and lowering of legacy
execution templates into tile-level micro-ops.

The mismatch is numerically closed:

```text
missing CAL-side envelope:
  IMM   128
  HMUL  2048
  RXINT 1024
  TRCTT 1024
  ----------------
  total 4224

missing LDN:
  legacy LDN      9216
  OpenFabric LDN  2048
  ---------------------
  total 7168

extra COPY:
  OpenFabric COPY 6144
  legacy COPY     3072
  --------------------
  total 3072

active inst delta:
  4224 + 7168 - 3072 = 8320
```

This means the problem is concentrated in three areas:

```text
1. compute template envelope is incomplete
2. operand materialize/load roles are incomplete
3. route forwarding granularity is too fine
```

## Problem

Today `legacy_gemm_compat` is implemented too late in the stack:

```text
ProgramVendorABI exeBlock
  -> ProgramBinRows
  -> choose legacy instruction template by source_tile_micro_block_kind
```

This is useful as a bring-up scaffold, but architecturally wrong as the final
design.

The binary layer should only serialize already-decided rows.  It should not
decide that:

```text
compute_update -> HMMAL-only template
route_forward  -> COPYT template
tile_store     -> HSTT template
```

That mapping is lowering semantics.  It belongs closer to tile micro-op
lowering / backend template selection, not in `program_bin.py`.

The current symptoms follow directly from this late and incomplete binding:

### 1. Missing `IMM/HMUL`

Legacy has a prologue-like template:

```text
task*/subtask1/template/*.csv

HLDT x16
IMM  x2
HMUL x16
```

This appears to initialize or scale the output accumulator / beta path before
the K-loop compute stream.

In the refactored tile program, GEMM phases already contain local semantic ops:

```text
init_c
stream_k_gemm
relu
store_c
```

But `init_c` is still represented as payload semantics, not as first-class
tile micro-ops.  Therefore there is no micro-block that owns the legacy
`HLDT + IMM + HMUL` template.

### 2. Missing `RXINT/TRCTT`

Legacy compute template:

```text
task*/subtask2/template/16.csv

HLDT  x16
HMUL  x16
RXINT x16
HMMAL x512
TRCTT x16
```

OpenFabric currently binds `compute_update` only to the `HMMAL x512` slice.
This preserves the main matrix multiply count, but drops tensor input/output
conversion or accumulator finalization rows represented by `RXINT/TRCTT`.

### 3. `LDN` too low

Legacy `LDN` appears in multiple roles:

```text
input0 / A materialize:
  task*/subtask2/template/0.csv
  HLDT x16 -> LDN x64 after pseudo expansion

input1 / B materialize inside compute template:
  task*/subtask2/template/16.csv
  HLDT x16 -> LDN x64 after pseudo expansion

output / accumulator prologue:
  task*/subtask1/template/0.csv
  HLDT x16 -> LDN x64 after pseudo expansion
```

OpenFabric currently maps only `route_source_materialize` to one canonical
`HLDT` template and does not model all legacy load roles.

### 4. `COPY` too high

Legacy `COPYT` count is lower than OpenFabric's current `COPY` count.

The refactored tile program expands route hops explicitly:

```text
route_source_materialize
route_forward
route_forward
...
```

Each `route_forward` is currently mapped to a canonical `COPYT` template.  This
is likely too literal.  Legacy appears to group or schedule forwarding more
coarsely than the current per-hop micro-block template binding.

### 5. Stage count mismatch

Current golden summary:

```text
stage           legacy     OpenFabric
LD              9216       8192
CAL             36992      32768
FLOW            3072       0
ST              4096       4096
```

The `FLOW=0` candidate count is a strong sign that route-forward instructions
are currently emitted as real `COPY` inst rows, but their exeBlock stage
classification is still inherited from the symbolic pipeline incorrectly or
from different micro-block stage attribution.  Stage ownership must be made
explicit at the same layer as template binding.

More precisely, OpenFabric's current `LD=8192` is likely:

```text
LDN  2048
COPY 6144
---------
LD   8192
```

So `COPY` is being emitted but classified under the wrong stage.  Stage must be
owned by the template segment or final instruction, not by a coarse
micro-block-level default.

## Design Principle

Legacy execution templates should be selected by **tile micro-op lowering**,
not by the binary serializer.

The final boundary should be:

```text
ProcessorTileProgram
  owns semantic tile action graph

TileMicroOpProgram
  owns executable micro-op roles

Dfu3500TemplateBoundProgram
  owns DFU3500 legacy template selection and instruction expansion

ProgramAsm
  owns ordered symbolic / legacy-bound instruction streams

ProgramVendorABI
  owns task/subtask/exeBlock rows and folded repeat metadata

ProgramBinRows / Serializer
  owns byte row planning and packing only
```

In other words:

```text
program_bin.py must not decide instruction templates.
```

It should receive already-expanded symbolic/legacy instruction rows from
`ProgramAsm` or a nearby backend-lowering layer.

## Proposed IR Addition

Introduce two explicit layers:

```text
ProcessorTileProgram
  -> TileMicroOpProgram
  -> Dfu3500TemplateBoundProgram
```

### TileMicroOpProgram

This layer answers:

```text
What executable roles exist inside each TileMicroBlock?
```

It should not know CSV paths, vendor template filenames, or legacy op names.

### Dfu3500TemplateBoundProgram

This layer answers:

```text
How does each micro-op role expand under the DFU3500 legacy_gemm_compat profile?
```

This layer may know about:

```text
task*/subtask1/template/*.csv
task*/subtask2/template/16.csv
HLDT / HSTT / COPYT
IMM / HMUL / RXINT / HMMAL / TRCTT
```

Suggested file placement:

```text
core/program_micro_ops.py
core/dfu3500/legacy_templates.py
```

If we want a smaller transition step, a temporary
`core/program_legacy_template.py` is acceptable, but it should be documented as
transitional and should not be imported by `program_bin.py` long term.

Suggested dataclasses:

```python
@dataclass(frozen=True)
class TileMicroOp:
    id: str
    processor: str
    source_tile_micro_block_id: str
    role: str
    loop_region_id: str | None
    loop_instance_key: str | None
    input_refs: tuple[str, ...]
    output_refs: tuple[str, ...]
    attrs: dict[str, Any]


@dataclass(frozen=True)
class TemplateBoundSegment:
    id: str
    source_micro_op_id: str
    role: str
    stage: Literal["LD", "CAL", "FLOW", "ST"]
    source_csv_path: str | None
    legacy_ops: tuple[str, ...]
    repeat_policy: str
    parameter_bindings: dict[str, Any]


@dataclass(frozen=True)
class TemplateBoundInstruction:
    id: str
    source_segment_id: str
    source_micro_op_id: str
    stage: Literal["LD", "CAL", "FLOW", "ST"]
    legacy_inst: LegacyInst
    local_order: int
```

Stage intentionally lives on `TemplateBoundSegment` and
`TemplateBoundInstruction`, not on `TileMicroOp`.  A single semantic micro-op
can expand into a mixed-stage template envelope.

This creates a clean handoff:

```text
TileMicroBlock
  -> TileMicroOp[]
  -> TemplateBoundSegment[]
  -> TemplateBoundInstruction[]
  -> ProgramAsmInstruction
  -> VendorInstructionRange
  -> InstBinRow
```

## Proposed Micro-Op Roles

Current `TileMicroBlock` kinds are:

```text
route_source_materialize
route_forward
compute_update
tile_store
```

They are too coarse for legacy template fidelity.  We should add explicit
micro-op roles inside or adjacent to these blocks.

### GEMM prologue / accumulator init

New role:

```text
accumulator_prepare
```

Legacy source:

```text
task*/subtask1/template/*.csv
HLDT + IMM + HMUL
```

Possible semantic mapping:

```text
init_c / beta scaling / accumulator seed
```

Open question:

```text
Does current C = relu(A @ B) require this path if beta == 0?
```

For legacy parity, the first version can include it conservatively if the
legacy GEMM template includes it.  Later optimization can remove it when
semantics prove beta path is dead.

### A/B source materialize

Existing role:

```text
route_source_materialize
```

But it needs an operand role:

```text
A_materialize
B_materialize
C_materialize
```

Legacy templates distinguish:

```text
A/input0 materialize:
  HLDT extra_field role roughly 2

B/input1 materialize:
  HLDT extra_field role roughly 3

C/output/prologue materialize:
  HLDT extra_field role roughly 1
```

Template selection should use:

```text
operand_role
tile tensor role
loop context
source/destination storage role
```

not just `block_kind`.

### Route forwarding

Existing role:

```text
route_forward
```

Legacy source:

```text
COPYT -> COPY
```

But current per-hop template binding produces too many COPY rows.  The route
binding needs a grouping policy:

```text
per_route_hop
per_route_bundle
per_sender_processor_per_instance
legacy_grouped_route_bundle
```

The MVP target is stage correctness, not route count parity:

```text
COPY must be classified as FLOW.
COPY 6144 vs 3072 remains a known non-parity item.
```

Exact legacy route grouping should be handled later, because it can change
dependency, exeBlock grouping, barrier placement, and scheduling.

### Compute prelude / core / finalize

Current:

```text
compute_update -> HMMAL only
```

Proposed split:

```text
compute_operand_prepare
  RXINT x16

compute_core
  HMMAL x512

compute_accumulator_finalize
  TRCTT x16
```

The legacy `HLDT x16` and `HMUL x16` inside template `16.csv` need further
classification:

```text
HLDT x16:
  likely B/input1 materialize for this K body

HMUL x16:
  possibly beta/scale path or precompute for accumulation
```

We should not hide all of this in one opaque `compute_update` template.  At
minimum, `compute_update` should own a structured template sequence:

```text
compute_update:
  - b_tile_materialize?    (LD)
  - tensor_rxint           (CAL/TENSOR)
  - hmmal_core             (CAL/TENSOR)
  - tensor_trctt           (CAL/TENSOR)
```

Long term this should become first-class tile op-chain:

```text
TileComputeAction(gemm_load_operand)
TileComputeAction(tensor_rxint)
TileComputeAction(hmmal_core)
TileComputeAction(tensor_trctt)
TileComputeAction(relu/bias/finalize)
```

### Store

Existing role:

```text
tile_store
```

Legacy source:

```text
HSTT -> STD
```

This currently matches count:

```text
STD 4096 vs 4096
```

Keep as-is for MVP, but move template binding out of `program_bin.py`.

## Proposed Pipeline Change

Current:

```text
ProgramVendorABI
  -> ProgramBinRows
       if legacy_gemm_compat:
         inspect source_tile_micro_block_kinds
         choose CSV-derived template
         create LegacyInst rows
```

Proposed:

```text
ProcessorTileProgram
  -> TileMicroOpProgram
       inspect TileMicroBlock + tile action payload
       produce executable roles, not vendor CSV rows

  -> Dfu3500TemplateBoundProgram
       bind micro-op roles to DFU3500 legacy template segments
       produce TemplateBoundInstruction rows with stages

  -> ProgramNodes / Packing / ASM
       consume template-bound instructions

  -> ProgramVendorABI
       carry instruction ranges and folded repeat

  -> ProgramBinRows
       receives LegacyInst rows already attached

  -> Serializer
       pack inst_t bytes only
```

For implementation pragmatism, we can stage this migration:

### Phase 1: Move template selection out of `program_bin.py` without changing behavior

Create the backend template helper:

```text
core/dfu3500/legacy_templates.py
```

Temporary API:

```python
bind_dfu3500_legacy_template_for_micro_block(...)
```

This phase should keep the golden diff unchanged.  If `program_bin.py` still
calls the helper temporarily, the callsite must be marked as transitional.

### Phase 2: Add `TileMicroOpProgram` and `Dfu3500TemplateBoundProgram`

Introduce:

```text
TileMicroOp
TemplateBoundSegment
TemplateBoundInstruction
```

Move stage ownership to `TemplateBoundSegment` / `TemplateBoundInstruction`.

### Phase 3: Attach template-bound instructions to `ProgramAsm`

`ProgramAsmInstruction` should be able to carry:

```text
template_bound_instruction_id
legacy_inst
stage
```

Then `ProgramVendorABI` instruction ranges count real template instructions.

`program_bin.py` stops choosing templates and only maps attached `LegacyInst`
records to `InstBinRow`.

### Phase 4: Fix stage attribution first

Before changing instruction counts, make sure:

```text
COPY -> FLOW
LDN  -> LD
HMMAL/HMUL/RXINT/TRCTT/IMM -> CAL
STD  -> ST
```

This may make the diff look temporarily "worse" in LD/FLOW counts, but it will
be more honest.

### Phase 5: Expand compute template envelope

First expand:

```text
compute_update:
  RXINT
  HMMAL
  TRCTT
```

Then decide whether `HLDT/HMUL` from template `16.csv` should be included in
the same structured envelope or split into operand/accumulator roles.

### Phase 6: Add accumulator_prepare under legacy compat policy

In `legacy_gemm_compat`, conservatively emit:

```text
accumulator_prepare:
  LDN / IMM / HMUL
```

Later optimized modes may remove this if beta=0 or no read-modify-write is
proven.

### Phase 7: Decide route grouping in a separate pass/RFC

Only after compute/load parity improves, revisit:

```text
COPY 6144 vs 3072
```

Potential policies:

```text
per_route_hop
per_route_bundle
per_sender_processor_per_instance
legacy_grouped_route_bundle
```

## Expected Effects

After Phase 1/2:

```text
program_bin.py no longer owns legacy template selection.
InstBinRow receives already-bound LegacyInst records.
InstructionLayoutPlan uses real template instruction counts from ProgramAsm.
```

After Phase 4:

```text
COPY rows should be classified as FLOW instead of LD.
LD/FLOW stage counts may still differ from legacy, but the diff becomes
truthful instead of hidden behind symbolic stage inheritance.
```

After Phase 5/6:

```text
legacy_gemm_compat diff should show:

HMMAL  equal
STD    equal
RXINT  present
TRCTT  present
IMM    present if accumulator_prepare enabled
HMUL   present if beta/prologue path enabled
LDN    closer to legacy role counts
```

After Phase 7:

```text
COPY/FLOW count should either match legacy or have a documented route grouping
reason.
```

## Non-goals

This RFC does not attempt to solve everything at once.

```text
1. It does not require byte-for-byte parity with legacy vendor output.
2. It does not redesign route grouping in the first implementation step.
3. It does not make legacy templates the default optimized backend.
4. It does not decide whether beta=0 accumulator_prepare can be eliminated.
5. It does not move generic fusion into first-class tile op-chain immediately.
6. It only moves legacy template ownership out of ProgramBinRows and introduces
   template-bound instruction ownership before binary packing.
```

For `legacy_gemm_compat`, introduce an explicit policy:

```python
@dataclass(frozen=True)
class LegacyGemmCompatPolicy:
    emit_accumulator_prepare: bool = True
    emit_compute_envelope: bool = True
    route_grouping: Literal[
        "per_route_hop",
        "legacy_grouped_route_bundle",
    ] = "per_route_hop"
```

In compatibility mode, parity and explainability are more important than
removing every semantically dead legacy instruction.  Optimizations such as:

```text
beta_zero_accumulator_prepare_elimination
dead_load_elimination
route_bundle_coalescing
```

should be later passes.

## Validation Plan

Keep the existing tests:

```text
test_legacy_csv_encoder_matches_vendor_gemm_template_shape
test_legacy_csv_encoder_supports_current_gemm_op_set
test_legacy_gemm_compat_mode_uses_vendor_inst_encoding
test_chip_env_generate_can_emit_legacy_gemm_compat_bundle
test_legacy_gemm_compat_bundle_diff_against_vendor_build_out
```

Add tests for template-bound lowering:

```text
1. compute_update template includes HMMAL/RXINT/TRCTT roles.
2. tile_store template still emits STD count equal to legacy.
3. accumulator_prepare emits HLDT/IMM/HMUL when enabled.
4. ProgramBinRows no longer imports or calls legacy template selection directly.
5. ProgramAsm or template-bound IR instruction counts equal final inst row counts.
6. program_bin.py does not import dfu3500 legacy template registry.
```

Golden diff should remain summary-level, not byte-equal:

```text
byte equality is not required because scheduler structure differs.
ABI size, capacity, opcode distribution, stage counts, and key row counts are required.
```

## Open Questions

### Q1: Is legacy `HMUL/IMM` required for beta=0 GEMM?

Legacy emits it, but OpenFabric semantic GEMM may not need it if output is not
read-modify-write.  For simulator parity, first implementation may include it
as `accumulator_prepare`; later optimization can remove it based on operator
attributes.

### Q2: Should `RXINT/TRCTT` be separate micro-ops or part of compute template?

Architecturally, they look like tensor operand/accumulator adaptation and
should be first-class enough to appear in template-bound IR.  MVP can keep them
inside a structured `compute_update` template sequence.

### Q3: How should route forwarding be grouped?

Current explicit route-hop modeling is correct for dependency semantics but
may be too fine for legacy exeBlock/template parity.  Route grouping should be
a separate pass after compute template parity is improved.

### Q4: Where should template binding live?

Preferred final placement:

```text
core/program_micro_ops.py
  generic tile micro-op roles and dataclasses

core/dfu3500/legacy_templates.py
  DFU3500 legacy_gemm_compat template binding and CSV-derived instruction expansion
```

Acceptable transition:

```text
core/program_legacy_template.py
```

The transition file is acceptable only if it is treated as temporary and does
not become a dependency of `program_bin.py`.  The architectural target is to
keep template selection under the DFU3500 backend namespace, not beside the
binary serializer.

## Recommendation

Accept this RFC with the following hard boundary:

```text
ProcessorTileProgram
  owns semantic tile actions and TileMicroBlock boundaries

TileMicroOpProgram
  owns executable micro-op roles:
    accumulator_prepare
    operand_materialize:A/B/C
    route_forward
    compute_operand_prepare
    compute_core
    compute_accumulator_finalize
    tile_store

Dfu3500TemplateBoundProgram
  owns legacy template selection and CSV-derived instruction expansion

ProgramAsm
  owns ordered symbolic / legacy-bound instruction streams

ProgramVendorABI
  owns task/subtask/exeBlock ranges, folded repeat metadata, and instruction ranges

ProgramBinRows
  owns row layout only

Serializer
  owns byte packing only
```

Implementation order:

```text
1. Move current legacy template selection out of program_bin.py without changing output.
2. Add TileMicroOpProgram and Dfu3500TemplateBoundProgram.
3. Attach TemplateBoundInstruction records to ProgramAsm.
4. Fix stage attribution from template-bound instructions:
   COPY -> FLOW, LDN -> LD, compute ops -> CAL, STD -> ST.
5. Expand compute_update from HMMAL-only to structured template segments:
   RXINT/HMMAL/TRCTT first, then classify HLDT/HMUL.
6. Add accumulator_prepare under legacy_gemm_compat policy.
7. Re-run golden diff and only then write a separate route grouping RFC/pass.
```

Do not attempt to force byte-for-byte parity in the first pass.  The target is:

```text
semantic template parity and explainable summary-level ABI differences.
```
