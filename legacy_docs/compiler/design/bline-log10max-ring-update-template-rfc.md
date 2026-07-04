# RFC: B-line Log10max Ring Update Template Design

## Status

Accepted direction.  Phase 1/2/3 implemented as progress-gated reports.
Phase 4 local pack/decode candidate implemented, but not integrated into the
final CBUF/MICC component writer.
Phase 5 component placement candidate implemented, but not integrated into
exeBlock CAL stages or final package bytes.

Current decision:

```text
Continue to final component integration only after OperandPlaceholder /
OperandAllocation / InstOperandPatch artifacts exist, then exeBlock CAL-stage
ownership and CBUF inst section insertion are explicit.
```

Follow-up stop-bleed RFC:

```text
docs/compiler/design/bline-operand-placeholder-allocation-rfc.md
```

This RFC covers the final known log10max ring-first local lowering blocker:

```text
log10max_ring_update_row_bytes_missing
```

It does not claim row bytes are already proven.  It defines the receiver-side
update template, the TemplateOp candidate, and the BinaryLayout row candidate
that must feed the later byte writer.

This is a delivery-week progress patch for the final local log10max blocker.
It must not grow into a ring collective subsystem.

## Summary

The B-line log10max ring-first path has already proven the communication and
consumer semantics:

```text
StreamAction(route_push_global_max / route_recv_global_max)
  -> FiberOp(fragment_route_push / fragment_route_recv)
  -> route_path proof
  -> GlobalMax route role binding
  -> global_max_ready[pe]
  -> max_with_floor_tile consumer binding
```

The remaining missing piece is the PE-local update performed at each receiving
PE after a `route_recv_global_max` action:

```text
current_global_max = max(current_global_max, received_global_max)
```

At Fiber level this is represented as:

```text
FiberOp(global_max_tile)
```

For the ring path, this `global_max_tile` is not a PE00 materialization step.
It is a receiver-side scalar/vector max update attached to each ring edge.
DFU3500 does not currently have a dedicated B-line binary template for this
atomic operation.  We must implement a new target-specific template expansion:

```text
FiberOp(global_max_tile, semantic_op=max_update_global_max)
  -> TemplateExpansion(dfu3500_log10max_ring_globalmax_update)
  -> one FMAX/HMAX-like update row candidate per ring edge
  -> later inst_t row bytes with FiberOp provenance
```

The key design boundary is:

```text
The FiberOp remains atomic.
The template layer may expand it into concrete DFU3500 rows.
The expansion must preserve provenance back to the original FiberOp and ring edge.
```

## Current State

### Already closed

The following are no longer the blocking issues:

```text
task_axis_scope_unproven
cross_task_one_app_ring_forbidden
representative_selection_missing
ring_edge_route_template_missing
route_role_globalmax_unproven
route_path_proof_missing
ring_phase_order_missing
global_max_distribution_missing
consumer_global_max_binding_missing
consumer_depends_on_global_ready_missing
symbolic_global_max_reaches_postprocess
```

Current local gate status:

```text
log10max blocker count = 1
remaining blocker = log10max_ring_update_row_bytes_missing
```

### New report-only contract

The current report-only contract is:

```text
compiler/gpdpu_compiler/core/stream_compiler/log10max_ring_update_template.py
```

It proves:

```text
30 ring update records exist for 4x4 representative row/column ring.
Each record uses FMAX for fp32.
Each record has a receiver-owned GlobalMax destination operand.
Opcode capability evidence exists in instruction docs / decoder / legacy op table.
No row bytes are claimed.
```

Phase 1/2/3 now additionally prove:

```text
30 RingUpdateTemplateBinding records.
30 RingUpdateTemplateOpCandidate records.
30 RingUpdateBinaryLayoutRowCandidate records.
phase distribution = 12 row_reduce / 3 col_reduce / 3 col_broadcast / 12 row_broadcast.
subtask_slot = log10max_ring_globalmax_update.
opcode = FMAX.
all candidates retain ring edge / StreamAction / FiberOp / TemplateExpansion provenance.
row_bytes_claim = false.
inst_t_bytes_emitted = false.
decode_roundtrip_claim = false.
```

Phase 4 local candidate now proves:

```text
30 RingUpdateFmaxInstCandidate records.
each candidate packs to one 304-byte inst_t row.
each candidate decodes back as opcode=FMAX, unit_inst_type=2, latency=72.
src_operands_idx = [0, 128, 0].
dst_operands_idx = [256, 0, 0].
operand_field_usage = {
  src0: used,
  src1: used,
  src2: unused_zero_fill,
  dst0: used,
  dst1: unused_zero_fill,
  dst2: unused_zero_fill,
}
operand_allocation_status = skeleton_operands_unallocated.
forwarding_bits = [0, 1, 0].
iter_exe_cond = 1.
component_integration_status = not_integrated.
runtime_ready = false.
```

The `src_operands_idx` / `dst_operands_idx` values above are skeleton row-shape
evidence only.  They are not final operand allocation.

Phase 5 placement candidate now proves:

```text
30 RingUpdateComponentPlacementCandidate records.
each candidate has a PE-major insts_file.bin component_byte_offset.
global_row_index = pe_index * MAX_INST_AMOUNT_PER_PE + local_pc.
component_byte_offset = global_row_index * 304.
local_pc is contiguous per destination PE.
stage = CAL.
exe_block_integration_status = not_integrated.
cbuf_section_integration_status = not_integrated.
operand_allocation_status = skeleton_operands_unallocated.
runtime_ready = false.
```

It intentionally keeps:

```text
log10max_ring_update_row_bytes_missing in the pre-integration gate
```

because these candidate bytes are not yet inserted into the PE-local PC stream,
exeBlock CAL stage, CBUF inst section, or package manifest.  After Phase-4
row bytes, if operands are still skeleton values, the narrower next blocker is:

```text
log10max_ring_update_operand_allocation_missing
```

At the Phase-5 component-placement report boundary, the blocker remains:

```text
log10max_ring_update_operand_allocation_missing
```

Only after operand allocation and inst operand patches exist may the blocker
advance to:

```text
log10max_ring_update_exeblock_cal_stage_missing
```

## Problem

The remaining gap exists because the current compiler has no B-line template
for this atomic action:

```text
receiver-side GlobalMax update
```

Existing evidence is adjacent but not sufficient:

```text
FMAX/HMAX opcode semantics exist.
ReLU has IMM-zero + HMAX/FMAX materializer evidence.
local_reduce_max has SHFL + FMAX local reduce template intent.
GlobalMax route push/recv can reuse route_forward family.
```

But none of those is exactly:

```text
Given:
  receiver current GlobalMax scalar/vector operand
  received GlobalMax scalar/vector operand

Emit:
  FMAX/HMAX current, received -> receiver-owned GlobalMax destination

For:
  every ring edge update in row_reduce / col_reduce / col_broadcast / row_broadcast
```

If we simply mark the current update template as proven, we would hide a real
binary lowering gap.  The correct fix is to design the template and its row
binding contract.

## Goals

1. Implement a DFU3500 B-line template expansion for ring receiver-side
   `global_max_tile` updates.
2. Keep `global_max_tile` atomic at Fiber level.
3. Use existing DFU3500 FMAX/HMAX opcode knowledge.
4. Preserve provenance from each emitted row back to:

```text
RingEdgeRecord
StreamAction(max_update_global_max)
FiberOp(global_max_tile)
TemplateExpansion(dfu3500_log10max_ring_globalmax_update)
```

5. Make the template fail closed until operand indices, row shape, and byte
   packing are proven.
6. Do not introduce a generic collective framework.
7. Do not claim direct physical allreduce.
8. Keep the gate at the precise `log10max_ring_update_row_bytes_missing` blocker
   until row bytes and decode roundtrip are proven.

## Non-goals

This RFC does not implement:

```text
direct_route_reduce_broadcast
generic allreduce
multi-app cross-task orchestration
numerical correctness proof
performance optimization
full row scheduler generalization
new frontend semantics
```

It also does not move route scheduling authority out of:

```text
StreamAction.depends_on
```

Ring graph metadata remains a derived validation/report view.

## V1 Decisions

The following are no longer open questions for first delivery:

```text
globalmax_representation = replicated_fp32_vector
operand_width = 4096 bits / 512 bytes
lane_count = 128
replication_invariant = all_lanes_equal
scalar_lane_policy = deferred

inplace_update_policy = forbidden

template_family = dfu3500_log10max_ring_globalmax_update
phase_policy = shared_template_family_with_phase_attrs

subtask_slot = log10max_ring_globalmax_update

packing_policy = use_existing_FMAX_packer_with_operand_allocation_adapter
```

The first implementation targets:

```text
dtype = fp32
update_op = FMAX
```

Aliases between destination and source operands are deferred.  V1 must allocate
logical operands as:

```text
globalmax_acc_in
globalmax_recv
globalmax_acc_out
```

## Missing Template Definition

### Template name

```text
dfu3500_log10max_ring_globalmax_update
```

### Source FiberOp

```text
FiberOp(
  op="global_max_tile",
  attrs={
    semantic_op: "max_update_global_max",
    route_role: "GlobalMax",
    update_op: "FMAX" | "HMAX",
    dtype: "fp32" | "fp16" | "bf16",
    task_id: ...,
    src_pe: ...,
    dst_pe: ...,
    phase: row_reduce | col_reduce | col_broadcast | row_broadcast,
  }
)
```

### Logical operation

For fp32:

```text
dst_global_max = FMAX(receiver_current_global_max, received_global_max)
```

For fp16/bf16, subject to dtype policy:

```text
dst_global_max = HMAX(receiver_current_global_max, received_global_max)
```

First delivery is currently fp32, so the first implementation should target:

```text
update_op = FMAX
```

### Template expansion shape

Minimal V1 expansion:

```text
TemplateExpansion(dfu3500_log10max_ring_globalmax_update)
  rows:
    0: FMAX src_current, src_received -> dst_global_max
```

No hidden route row should be emitted here.  Route push/recv is a separate
template family:

```text
route_forward
```

No postprocess maximum should be emitted here.  That belongs to:

```text
FiberOp(max_with_floor_tile)
```

## Required IR Inputs

The template cannot be generated from opcode alone.  It requires precise inputs
from previous lowering layers.

### From RingEdgeRecord

Each edge must provide:

```python
edge_id: str
phase: Literal[
  "row_reduce",
  "col_reduce",
  "col_broadcast",
  "row_broadcast",
]
task_id: int
src_pe: str
dst_pe: str
recv_stream_action_id: str
update_action_id: str
dtype: str
update_op: Literal["FMAX", "HMAX"]
route_role: Literal["GlobalMax"]
ordering_group: str
```

The template must consume:

```text
edge.update_action_id
edge.dst_pe
edge.dtype
edge.update_op
edge.phase
```

### From StreamAction

The relevant action is:

```text
StreamAction(max_update_global_max)
```

Required fields:

```text
inputs:
  current_value[dst]
  received_global_max

outputs:
  updated_global_max

depends_on:
  previous dst producer
  route_recv_global_max
```

The dependency must prove:

```text
update waits for route_recv
```

### From FiberOp projection

The projected FiberOp must carry:

```text
op = global_max_tile
inputs = GlobalMax route fragment / current global max operand
outputs = GlobalMax route fragment / updated global max operand
depends_on = FiberDependency(
  expected_satisfaction="route_or_local_materialization",
  proven_by=("route_path",)
)
```

Required attrs:

```text
semantic_op = max_update_global_max
route_role = GlobalMax
recv_stream_action_id
paired_push_stream_action_id
update_op
dtype
task_id
src_pe
dst_pe
phase
template_evidence_id
template_status
template_blocker
```

### From executable role lowering

The executable role must be:

```text
collective:global_max
```

For ring update template binding, the executable op must additionally expose:

```text
source_fiber_op_kind = global_max_tile
attrs.semantic_op = max_update_global_max
attrs.route_role = GlobalMax
attrs.update_op = FMAX | HMAX
proof_summary contains route_path satisfied
```

This distinguishes ring receiver-side update from older PE00 materialized
scalar semantics.

### From template binding

The binding layer needs a new special case:

```text
role = collective:global_max
source_fiber_op_kind = global_max_tile
attrs.semantic_op = max_update_global_max
attrs.route_role = GlobalMax

=> bind to dfu3500_log10max_ring_globalmax_update
```

It must not globally turn all `collective:global_max` into concrete templates.
Only this ring receiver-side update form may become concrete.

## Binary Background

### FMAX / HMAX opcode facts

Available evidence:

```text
docs/architecture/instruction-set/dfu3500-simd/instruction_cards.md:FMAX
docs/architecture/instruction-set/dfu3500-simd/instruction_cards.md:HMAX
compiler/gpdpu_compiler/decoder/dfu3500_isa.py:FMAX/HMAX
compiler/gpdpu_compiler/core/program_legacy_inst.py:LEGACY_OPS.FMAX/HMAX
```

Known semantic shape:

```text
FMAX:
  dst.fp32[i] = max(src0.fp32[i], src1.fp32[i])
  lanes = 128
  operand width = 4096 bits / 512 bytes

HMAX:
  dst.fp16[i] = max(src0.fp16[i], src1.fp16[i])
  lanes = 256
  operand width = 4096 bits / 512 bytes
```

The first log10max path uses fp32:

```text
update_op = FMAX
```

### What is known

We know:

```text
FMAX opcode exists.
FMAX is a two-source, one-destination operation.
The decoder knows opcode / latency / unit type.
The legacy packer can represent FMAX-like CSV rows.
ReLU and max_with_floor already rely on FMAX/HMAX capability reports.
```

### What is not yet known

We do not yet have:

```text
active vendor row shape for ring receiver-side GlobalMax update
operand index allocation for receiver_current_global_max
operand index allocation for received_global_max
operand index allocation for receiver-owned updated_global_max
subtask slot / exeBlock placement for each ring update row
row bytes roundtrip proof for the update row
integration with final inst_t component writer
```

This is why `log10max_ring_update_row_bytes_missing` is still legitimate after
Phase 1/2/3.

## Proposed Design

### 1. Add a ring update template binding layer

Add a narrow module:

```text
compiler/gpdpu_compiler/core/stream_compiler/log10max_ring_update_template.py
```

Current report-only contract already exists.  Extend it in phases.

New target data shape:

```python
@dataclass(frozen=True)
class RingUpdateTemplateBinding:
    schema_version: str
    binding_id: str

    edge_id: str
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    ordering_group: str
    task_id: int
    src_pe: str
    dst_pe: str

    source_fiber_op_id: str
    source_stream_action_id: str
    recv_stream_action_id: str
    update_stream_action_id: str
    paired_push_stream_action_id: str
    update_op: Literal["FMAX", "HMAX"]
    dtype: Literal["fp32", "fp16", "bf16"]
    globalmax_representation: Literal["replicated_vector", "scalar_lane"]
    lane_convention: str

    src_current_operand: str
    src_received_operand: str
    dst_updated_operand: str
    inplace_update_policy: Literal["allowed", "forbidden", "unknown"]

    route_recv_dependency_id: str
    subtask_slot: str | None
    exe_block_slot: str | None
    row_placement_status: Literal["unplaced", "placed"]

    template_family: Literal[
        "dfu3500_log10max_ring_globalmax_update"
    ]
    template_status: Literal[
        "candidate_available",
        "row_shape_bound",
        "row_bytes_emitted",
        "blocked",
    ]
    blocker_ids: tuple[str, ...]
```

### 2. Split template candidate from row bytes

Use a two-stage status:

```text
candidate_available:
  FMAX/HMAX opcode capability and operand semantics are known.
  status = diagnostic_only
  blocker = log10max_ring_update_row_bytes_missing

row_shape_bound:
  operand indices, subtask slot, and row placement are assigned.
  status = layout_candidate
  blocker = log10max_ring_update_row_bytes_missing

row_bytes_emitted:
  row can be packed and decoded back with provenance.
  status = binary_candidate
  blocker may be removed only after decode/provenance/dependency checks pass.
```

Hard gate:

```text
runtime_ready / uploadable binary package must require:
  row_bytes_emitted
  pack -> decode roundtrip
  opcode/source/destination match
  row provenance retained
  consumer dependencies still pass
```

`candidate_available` and `row_shape_bound` are progress states only.  They
must not clear uploadable/runtime_ready blockers.

### 3. Define operand policy

For every ring update edge:

```text
src_current_operand:
  receiver-local current GlobalMax accumulator operand

src_received_operand:
  receiver-owned operand produced by fragment_route_recv(GlobalMax)

dst_updated_operand:
  receiver-local GlobalMax accumulator operand for downstream edges/consumer
```

V1 uses non-in-place logical operands:

```text
globalmax_acc_in
globalmax_recv
globalmax_acc_out
```

and records:

```text
inplace_update_policy = forbidden
```

Physical operand coalescing is deferred until aliasing is proven.

### 4. Define phase placement policy

The update row must be placed after its matching recv:

```text
route_recv_global_max(edge_i)
  -> max_update_global_max(edge_i)
```

It must also be before any downstream push or consumer that uses the updated
GlobalMax value:

```text
max_update_global_max(edge_i)
  -> route_push_global_max(edge_j)
```

or:

```text
max_update_global_max(last_edge_for_pe)
  -> global_max_ready[pe]
  -> max_with_floor_tile
```

The template expansion must preserve:

```text
ordering_group = task0:row_reduce | task0:col_reduce | ...
```

### 5. Bind only ring receiver-side update, not all global_max_tile

The old PE00 strategy used:

```text
collective:global_max
  -> PE00 aggregate/materialize/readback
```

The ring path uses:

```text
collective:global_max
  -> receiver-side route update
```

Therefore binding must check:

```text
attrs.semantic_op == "max_update_global_max"
attrs.route_role == "GlobalMax"
attrs.selected_strategy == "ring_spmd_row_then_col" or source ring report id present
```

Do not make this rule:

```text
role == collective:global_max -> concrete FMAX
```

That would incorrectly bless non-ring collective forms.

### 6. Preserve row provenance

Every row emitted later must carry:

```text
source_ring_edge_id
source_stream_action_id
source_fiber_op_id
template_expansion_id
operator = log10max
collective_strategy = ring_spmd_row_then_col
route_role = GlobalMax
```

This must appear in:

```text
TemplateOp
BinaryLayout row
inst_t row writer record
delivery report
```

## Proposed Pipeline

Target implementation path:

```text
Log10MaxRingPlanReport
  -> Log10MaxRingFiberProjectionReport
  -> FiberExecutableProgram
  -> RouteRoleBindingReport
  -> GlobalMaxConsumerBindingReport
  -> RingUpdateTemplateReport
  -> RingUpdateTemplateBindingReport
  -> TemplateOpPlan update rows
  -> BinaryLayout rows
  -> inst_t writer
  -> runtime_ready gate
```

The new implementation should not skip directly from ring metadata to
`inst_t` bytes.

## Validation Plan

### Existing checks that must remain passing

```bash
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_ring_plan.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_ring_fiber_projection.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_globalmax_route_role_binding.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_globalmax_consumer_binding.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_ring_template_evidence.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_ring_update_template.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_bline_runtime_ready_preintegration.py
```

### New checks added for Phase 1/2/3

```bash
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_ring_update_template_binding.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_ring_update_template_rows.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_ring_update_binary_layout_candidate.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_ring_update_fmax_inst_candidate.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_ring_update_component_placement_candidate.py
```

The first check should verify:

```text
30 update template bindings
phase distribution:
  row_reduce = 12
  col_reduce = 3
  col_broadcast = 3
  row_broadcast = 12
all FMAX for fp32
all tied to RingEdgeRecord ids
all tied to global_max_tile FiberOps
all have route_recv dependency
all have explicit src_current/src_received/dst_updated operands
globalmax_representation = replicated_vector
lane_convention = replicated_fp32_vector_all_lanes_equal
inplace_update_policy = forbidden
subtask_slot = log10max_ring_globalmax_update
no row bytes claim yet
```

The row-candidate checks should verify:

```text
30 row candidates
opcode intent = FMAX
src operand fields match binding record
dst operand field matches receiver-owned updated GlobalMax
row provenance maps back to FiberOp(global_max_tile)
row order respects route_recv -> update
row_bytes_claim = false
inst_t_bytes_emitted = false
decode_roundtrip_claim = false
```

No-shortcut rule:

```text
check_stream_compiler_log10max_ring_update_template_rows.py must fail if:
  row.source_fiber_op_id is missing
  row.source_stream_action_id is missing
  row.source_ring_edge_id is missing
  row.template_expansion_id is missing
  row was created directly from RingEdgeRecord without TemplateOpPlan provenance
```

PE00/generic collective non-regression rule:

```text
Phase 2 checks must prove:
  PE00 materialized-scalar behavior is unchanged
  generic collective behavior is unchanged
  only semantic_op=max_update_global_max with ring provenance binds this template
```

The Phase-4 local candidate check should verify:

```text
30 inst_t candidate rows
each row byte size = 304
opcode = FMAX / 0x27
unit_inst_type = 0x2
latency = 72
src_operands_idx = [0, 128, 0]
dst_operands_idx = [256, 0, 0]
operand_allocation_status = skeleton_operands_unallocated
operand_field_usage marks src2/dst1/dst2 as unused_zero_fill
forwarding_bits = [0, 1, 0]
bypass_bits = [0, 0, 0]
iter_exe_cond = 1
candidate_pack_decode_roundtrip = true
final_row_bytes_claim = false
component_integration_claim = false
runtime_ready = false
```

These operand indices are skeleton evidence only.  The check must not treat
them as final allocation.

The Phase-5 placement candidate check should verify:

```text
30 placement candidates
component_name = insts_file.bin
global_row_index = pe_index * MAX_INST_AMOUNT_PER_PE + local_pc
component_byte_offset = global_row_index * 304
component_byte_offset is unique
local_pc is contiguous per destination PE
stage = CAL
opcode = FMAX
exe_block_integration_status = not_integrated
cbuf_section_integration_status = not_integrated
operand_allocation_status = skeleton_operands_unallocated
runtime_ready = false
```

### Runtime-ready gate transition

Current:

```text
log10max_ring_update_operand_placeholders_missing
```

After template binding / TemplateOp candidates / BinaryLayout row candidates
but before placeholders:

```text
log10max_ring_update_operand_placeholders_missing
```

After placeholder extraction but before allocation:

```text
log10max_ring_update_operand_allocation_missing
```

After allocation but before inst operand patch / decode:

```text
log10max_ring_update_inst_operand_patch_missing
```

After patch / decode proof but before final component bytes:

```text
log10max_ring_update_row_bytes_missing
```

After operand allocation and InstOperandPatch, but before exeBlock CAL
integration:

```text
placement candidate blocker becomes:
  log10max_ring_update_exeblock_cal_stage_missing
```

Do not remove the blocker without replacing it with the more precise next
blocker.

The runtime_ready report must continue to state:

```text
numerical_status = not_checked
simict_status = not_run | not_claimed
```

unless those later stages have actually run.

## Alternatives Considered

### Alternative A: Reuse PE00 FMAX combine template

Rejected for the ring-first path.

Reason:

```text
PE00 combine is a materialized scalar aggregation strategy.
Ring update is receiver-side point-to-point update.
```

They may share FMAX opcode semantics, but they do not share scheduling,
placement, operand ownership, or provenance.

### Alternative B: Treat route recv as automatically updating GlobalMax

Rejected.

Reason:

```text
route_recv makes a value visible.
max_update_global_max combines visible value with current accumulator.
```

Conflating these would hide compute semantics inside communication.

### Alternative C: Fold max update into max_with_floor_tile

Rejected.

Reason:

```text
max_with_floor_tile is postprocess:
  maximum(local_log10, global_max - 8)

ring update is collective accumulation:
  max(current_global_max, received_global_max)
```

They are different FiberOps and different dataflow phases.

### Alternative D: Mark update template proven from FMAX opcode docs

Rejected.

Opcode existence is necessary but insufficient.  We still need row shape,
operand binding, subtask/exeBlock placement, and byte decode proof.

## Implementation Plan

### Phase 1: Template binding contract

Add:

```text
RingUpdateTemplateBindingReport
```

Inputs:

```text
Log10MaxRingPlanReport
Log10MaxRingFiberProjectionReport
RouteRoleBindingReport
```

Output:

```text
30 candidate bindings
status = candidate_available
blocker = log10max_ring_update_row_bytes_missing
```

Expected gate change:

```text
log10max_ring_update_template_missing
  -> log10max_ring_update_row_bytes_missing
```

### Phase 2: TemplateOp integration

Add a special ring update template path to TemplateOp lowering:

```text
collective:global_max + semantic_op=max_update_global_max
  -> template_status = layout_candidate
  -> instruction_intent = FMAX
  -> row_bytes_claim = false
```

This must not change PE00 or generic collective behavior.

Do not call this `concrete_template` before row bytes exist.  In this RFC:

```text
layout_candidate != row_bytes_emitted
```

### Phase 3: BinaryLayout row candidates

Create row candidates:

```text
role = collective:global_max
opcode = FMAX
subtask_slot = log10max_ring_globalmax_update
source_ring_edge_id = ...
source_fiber_op_id = ...
```

At this phase, row bytes may still be blocked if operand index allocation is
not finished.

The blocker remains:

```text
log10max_ring_update_row_bytes_missing
```

### Phase 4: inst_t row writer

Emit candidate rows using existing FMAX pack/decode infrastructure.

Use the existing FMAX packer behind a GlobalMax operand allocation adapter.
Do not make the packer GlobalMax-aware; GlobalMax semantics belong to the
binding/adapter layer.

Required proof:

```text
pack -> decode -> opcode/source/destination/provenance roundtrip
```

### Phase 5: runtime_ready gate

Remove:

```text
log10max_ring_update_row_bytes_missing
```

only when:

```text
all ring update rows are emitted
all rows decode correctly
all rows retain provenance
all consumer dependencies still pass
```

## Invariants

1. `FiberOp(global_max_tile)` remains atomic.
2. Ring update template expansion happens after FiberOp lowering.
3. No new communication IR is introduced.
4. Route recv does not imply max update.
5. Max update does not imply postprocess max-with-floor.
6. PE00 materialization semantics are not reused as ring semantics.
7. `collective:global_max` may only bind to the ring update template when
   `semantic_op=max_update_global_max`.
8. Runtime-ready cannot pass on opcode capability alone.
9. Every emitted row must carry provenance back to the source FiberOp.
10. V1 GlobalMax is represented as a replicated fp32 vector operand.
11. V1 update is non-in-place; aliasing is deferred.
12. One shared update template family is used; ring phase is an attribute.
13. `stream_compiler` is a delivery-week tactical location, not permanent
    production authority for template rows.

## Risks and Mitigations

### Risk: FMAX scalar update is actually vector-lane update

DFU3500 FMAX is lane-wise over a 4096-bit operand.  If GlobalMax is represented
as a replicated scalar vector, FMAX is acceptable.  If it must be a true scalar
register, additional operand packing rules are needed.

Mitigation:

```text
V1 explicitly represents GlobalMax as replicated_fp32_vector:
  operand_width = 4096 bits / 512 bytes
  lane_count = 128
  invariant = all_lanes_equal
  scalar_lane_policy = deferred
```

### Risk: in-place update is unsafe

If DFU3500 does not allow destination to alias a source operand, in-place update
would be invalid.

Mitigation:

```text
Default to non-in-place symbolic operands until aliasing is proven.
```

### Risk: row count grows too large

For 4x4 representative ring:

```text
30 update rows
```

This is acceptable for V1.  Larger meshes must be capacity-checked before
runtime-ready.

### Risk: template binding accidentally blesses PE00 global_max_tile

Mitigation:

```text
Require semantic_op=max_update_global_max and ring edge provenance.
```

### Risk: tactical stream_compiler module becomes permanent authority

`log10max_ring_update_template.py` may live in `stream_compiler` during the
delivery week because that is where the current B-line evidence path lives.
Before this becomes a production runtime_ready trunk gate, it must either:

```text
migrate to TemplateOp/BinaryLayout-owned code
```

or:

```text
be consumed through an explicit migration adapter with no reverse dependency
from production core into stream_compiler reports
```

## Expected Effect

After Phase 1:

```text
runtime_ready remains false
remaining blocker becomes more precise:
  log10max_ring_update_row_bytes_missing
```

After Phase 2/3:

```text
TemplateOp/BinaryLayout can represent ring update rows.
runtime_ready remains false
remaining blocker stays:
  log10max_ring_update_row_bytes_missing
```

After Phase 4/5:

```text
log10max ring-first can clear its final local structural blocker.
```

This does not imply numerical correctness or SimICT execution.  It only means
the B-line lowering pipeline can honestly produce the required ring update
binary rows.

## Deferred Questions

The V1 decisions above close the delivery-blocking questions.  The following
remain deferred optimization / cleanup questions:

1. Can `replicated_fp32_vector` later be replaced by a true scalar-lane
   representation?
2. Can destination/source aliasing be proven and used to reduce operand
   pressure?
3. Do later dtype paths need a separate bf16 policy instead of HMAX?
4. Should phase-specific template ids be introduced after first delivery for
   profiling/debug clarity?

## Recommended Decision

Accept with small progress-gated amendments.  Phase 1/2/3 are implemented as
report-only progress gates; Phase 4/5 are implemented only as skeleton
row-shape / placement candidates:

```text
Delivered:
  1. RingUpdateTemplateBindingReport
  2. check_stream_compiler_log10max_ring_update_template_binding.py
  3. RingUpdateTemplateOpCandidate / RingUpdateBinaryLayoutRowCandidate report
  4. check_stream_compiler_log10max_ring_update_template_rows.py
  5. check_stream_compiler_log10max_ring_update_binary_layout_candidate.py
  6. RingUpdateFmaxInstCandidate pack/decode report
  7. RingUpdateComponentPlacementCandidate report
  8. runtime_ready remains blocked on:
       log10max_ring_update_operand_allocation_missing
```

Next implement OperandPlaceholder / OperandAllocation / InstOperandPatch before
any final component integration.  The existing FMAX bytes and placement records
must stay diagnostic until patched operands exist.

Do not mark the update template proven from opcode docs alone.  The template is
ours to design and implement, and the next implementation must carry the exact
IR-to-template-to-row provenance needed for binary lowering.

Phase 1 pass condition:

```text
30 bindings
phase distribution = 12 / 3 / 3 / 12
all dtype = fp32
all update_op = FMAX
all edge_id unique
all tied to RingEdgeRecord
all tied to FiberOp(global_max_tile)
all have route_recv_dependency_id
all have src_current/src_received/dst_updated operands
all use replicated_fp32_vector
all use non-in-place update policy
no row bytes claim
runtime_ready remains false
```

This RFC is the last-blocker progress patch, not a new ring collective
framework.
