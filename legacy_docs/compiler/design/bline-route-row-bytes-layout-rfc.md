# RFC: B-line Route Row Bytes and Layout Closure

## Status

Draft for review.

Recommended decision: accept Phase 0/1 as the next report-only construction
step, and require a separate approval before any route/COPY/COPYT row enters
final CBUF/MICC component integration.

## Summary

The previous inst-row field provenance RFC made log10max ring FMAX update rows
safe at the row-body candidate level:

```text
InstOperandPatch
  -> InstFieldBindingRecord
  -> InstRowByteCandidateRecord
```

That is not enough for route rows.  A route row is not only an opcode plus
operands.  It joins:

```text
sender source operand
receiver PE position
receiver exeBlock / block_idx
receiver destination operand
COPY/COPYT lane expansion policy
flow_ack / child slot policy
instruction stage layout
exeBlock stages_start_pc
end_inst boundary
component byte placement
```

The next B-line step must therefore be route-and-layout closure, not a direct
raw byte writer.  The smallest safe design is:

```text
RingEdgeRecord / FiberOp route action
  -> RouteEndpointPatch
  -> InstructionLayoutPlan
  -> ExeBlockWriterPlan
  -> InstructionBoundaryPlan
  -> ComponentPlacementPlan
  -> RouteInstRowByteCandidateRecord
```

Only after these artifacts agree may route rows move from candidate bytes to
component-integrated bytes.

## Current State

### B-line checkpoint

Current B-line report-only work can describe log10max GlobalMax continuity:

```text
local_reduce_max_out
  -> first route_push.src
  -> route_recv.dst
  -> FMAX.src_received
  -> FMAX.dst
  -> next route_push.src
  -> max_with_floor.globalmax_src
```

It also has 30 allocation-backed FMAX update row-body candidates.  These
candidates intentionally leave:

```text
block_idx
end_inst
exeBlock writer plan
component placement
route row bytes
```

as blockers.

The preintegration gate now correctly reports:

```text
runtime_ready = false
uploadable = false
```

and distinguishes candidate decode from final component bytes.

### A-line / vendor facts

The original implementation does not decide route row fields in one writer.
The relevant source is:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper
```

Important observed facts:

1. `inst_map_common.cpp::setNodes()` assigns PE coordinates and PE-local
   `block_idx` from node placement.

2. `inst_map_common.cpp::fillRegIdx()` offsets template-local
   `src_operands_idx` / `dst_operands_idx` by a node-local `start_reg_idx`.

3. `inst_map_common.cpp::fillCpInst()` patches parent COPY rows using the child
   node:

```text
dst_blocks_idx[0] = child.block_idx
dst_pes_pos[0].x = child.x
dst_pes_pos[0].y = child.y
dst_operands_idx[0] = child.start_reg_idx + child_csv_reg(tag)
flow_ack = child index
```

4. The `Task_Resource` path in `inst_blk_map.cpp::fill_copy_inst()` performs
   the same receiver-owned idea, but the receiver destination operand comes
   from the receiver PE resource:

```text
dst_operands_idx[0] = receiver_task_resource.retrieve_reg_idx(dst_tag)
```

5. COPYT is not a single ordinary COPY row.  It expands/follows lanes.  Follow
   rows reuse receiver PE/block and use destination offsets such as:

```text
dst_operands_idx[0] = base_dst + lane * OPERANDS_PER_OPERAND_RAM
```

6. `exe_block_gen.cpp` owns stage counts and `stages_start_pc`:

```text
LD start pc
CAL start pc
FLOW start pc
ST start pc
MAX/end pc
```

7. `task_print.cpp` writes simulator `inst_t` rows and separately projects RTL
   rows.  RTL projection reinterprets some fields, for example `flow_ack` can
   become a base/address slot for COPY-like RTL materialization.  B-line V1
   should bind simulator `inst_t` first; RTL/debug projection is derived and
   must not become a second semantic path.

8. B-line already contains a legacy compatibility route patch in
   `compiler/gpdpu_compiler/core/program_bin.py`, notably
   `_legacy_copy_inst_with_route_target()`.  That path is useful evidence, but
   it is not a native B-line route-byte authority.

## Problem

If B-line writes route bytes directly from `RingEdgeRecord`, it will recreate a
hidden backend in the serializer.  The route row writer would be forced to
invent:

```text
receiver block_idx
receiver PE coordinates
receiver dst operand index
COPYT lane rows
flow_ack / child slot
end_inst
block_idx
component offsets
exeBlock stage PCs
```

That violates the existing B-line layering rule:

```text
FiberOp and StreamAction describe semantic execution.
Template / physical lowering binds target rows.
Serializer only packs already-bound fields.
```

The immediate risk is a row that decodes correctly in isolation but is not
connected to the MICC control graph, or a COPY row whose sender writes one
value while the receiver/FMAX reads another.

## Goals / Non-goals

Goals:

- Define route row field owners before raw route bytes are emitted.
- Keep route row emission within existing B-line primitives:
  `StreamAction(route_push/route_recv)`, `FiberOp(fragment_route_push/recv)`,
  `RouteRoleBinding`, `OperandAllocation`, and `InstFieldBindingRecord`.
- Make route endpoint closure machine-checkable.
- Define instruction layout / exeBlock / boundary / placement artifacts needed
  to turn row-body candidates into component-integrated bytes.
- Preserve `runtime_ready=false` until component bytes and MICC control rows are
  both coherent.

Non-goals:

- Implement generic allreduce or direct physical allreduce.
- Introduce new communication IR.
- Emit final route/COPY/COPYT rows in this RFC.
- Solve all local_reduce/max_with_floor bytes.
- Claim numerical correctness or SimICT execution.
- Support cross-task in-app cooperation.  Cross-task phases still require app
  boundaries or explicit materialization.

## Proposed Design

### 1. RouteEndpointPatch

Add a route-specific patch artifact that joins a ring edge to sender and
receiver execution placement.

```python
@dataclass(frozen=True)
class RouteEndpointPatch:
    schema_version: str
    patch_id: str
    operator: Literal["log10max"]
    collective_strategy: Literal["ring_spmd_row_then_col"]

    logical_route_edge_id: str
    source_ring_edge_id: str
    physical_route_row_candidate_ids: tuple[str, ...]
    phase: Literal["row_reduce", "col_reduce", "col_broadcast", "row_broadcast"]
    app_id: int
    task_id: int

    src_pe: str
    dst_pe: str
    sender_stream_action_id: str
    receiver_stream_action_id: str
    sender_fiber_op_id: str
    receiver_fiber_op_id: str

    route_opcode_family: Literal[
        "COPY",
        "COPYT",
        "LDN",
        "source_template_fixed",
        "undecided",
    ]
    route_family_status: Literal[
        "pending_phase2_decision",
        "selected",
        "blocked",
    ]
    route_family_decision_id: str | None
    base_materialization: Literal["native_template_row", "source_template_fixed"]

    src_operand_allocation_id: str
    dst_operand_allocation_id: str
    src_route_operand_patch_id: str | None
    dst_route_operand_patch_id: str | None
    src_operand_idx: int
    dst_operand_idx: int

    dst_pe_pos: tuple[int, int, int]
    dst_pe_coord_status: Literal["source_backed", "profile_backed", "blocked"]
    dst_block_idx: int | None
    dst_block_binding_status: Literal["bound", "pending_layout"]

    flow_ack: int | None
    flow_ack_policy_id: str | None
    flow_ack_status: Literal["bound", "pending_policy"]

    lane_policy_id: str | None
    lane_count: int
    lane_stride: int | None

    patch_status: Literal[
        "endpoint_bound_layout_pending",
        "endpoint_bound",
        "blocked",
    ]
    blocker_ids: tuple[str, ...]
```

V1 route endpoint patch may bind operands and PE coordinates while leaving
`dst_block_idx` and `flow_ack` pending.  It must not claim row bytes until
layout and boundary owners close.

`route_opcode_family="undecided"` is valid in Phase 0.  That status means the
logical endpoint is closed, but COPY/COPYT/LDN/source-template byte family
selection is intentionally deferred to Phase 2.  Phase 0 must not fill `COPY`
just to satisfy a schema.

The logical endpoint and physical row plan are deliberately separate.  One
`logical_route_edge_id` may later expand into multiple
`physical_route_row_candidate_ids`, especially if Phase 2 chooses COPYT lane
expansion.

### 2. InstructionLayoutPlan

Route rows need PE-local stage placement.  B-line should not infer this inside
the serializer.

```python
@dataclass(frozen=True)
class InstructionLayoutPlan:
    plan_id: str
    app_id: int
    task_id: int
    pe: str
    exe_block_id: str
    stage: Literal["LD", "CAL", "FLOW", "ST"]
    local_order: int
    local_pc: int | None
    row_candidate_ids: tuple[str, ...]
    ordering_predecessor_row_ids: tuple[str, ...]
    ordering_status: Literal[
        "stage_order_proven",
        "block_order_proven",
        "subtask_order_proven",
        "app_boundary_proven",
        "blocked",
    ]
    layout_status: Literal["planned", "pc_assigned", "blocked"]
    blocker_ids: tuple[str, ...]
```

For log10max ring route rows, stage should default to `FLOW` unless source
evidence proves a different family.  FMAX update rows may live in `CAL` only
when `route_recv -> FMAX -> next route_push` ordering is proven by stage order,
block order, subtask order, or app boundary.  A row whose fields are bound but
whose ordering is reversed is still blocked.

### 3. ExeBlockWriterPlan

`block_idx` and `stages_start_pc` are control-plane facts.  They must be owned
by a MICC/exeBlock writer plan.

```python
@dataclass(frozen=True)
class ExeBlockWriterPlan:
    plan_id: str
    app_id: int
    task_id: int
    subtask_id: int
    pe: str
    block_idx: int
    predecessor_block_refs: tuple[str, ...]
    successor_block_refs: tuple[str, ...]
    stage_start_pc: Mapping[str, int]
    stage_instruction_counts: Mapping[str, int]
    root_or_child_status: Literal["root", "child", "mixed", "unknown"]
    writer_status: Literal["planned", "micc_candidate", "blocked"]
    blocker_ids: tuple[str, ...]
```

This plan is also responsible for proving that a postprocess consumer depends
on its `global_max_ready[pe]` action.

V1 default phase/block policy:

```text
row_reduce      -> one exeBlock
col_reduce      -> one exeBlock
col_broadcast   -> one exeBlock
row_broadcast   -> one exeBlock
postprocess     -> one consumer exeBlock, unless existing evidence proves safe merge
```

Phase/block fusion is deferred.  It requires an explicit ordering proof and is
not part of first delivery.

### 4. InstructionBoundaryPlan

`end_inst` is not an opcode property.  It depends on stage-local valid row
boundaries.

```python
@dataclass(frozen=True)
class InstructionBoundaryPlan:
    plan_id: str
    app_id: int
    task_id: int
    pe: str
    stage: str
    row_candidate_ids: tuple[str, ...]
    end_inst_by_row_candidate_id: Mapping[str, bool]
    policy: Literal["last_valid_in_stage", "source_template_fixed"]
    boundary_status: Literal["bound", "blocked"]
    blocker_ids: tuple[str, ...]
```

### 5. ComponentPlacementPlan

Component placement turns candidate rows into PE-major `inst_t` component
offsets.

```python
@dataclass(frozen=True)
class ComponentPlacementPlan:
    plan_id: str
    component_name: Literal["insts"]
    app_id: int
    task_id: int
    pe: str
    row_candidate_id: str
    pe_local_pc: int
    global_row_index: int
    component_byte_offset: int | None
    placement_status: Literal[
        "unplaced_candidate",
        "placed_candidate",
        "component_integrated",
        "blocked",
    ]
    blocker_ids: tuple[str, ...]
```

Only `component_integrated` may feed runtime_ready.

For `placement_status="unplaced_candidate"` or `"blocked"`,
`component_byte_offset` must be `None`.  For `"placed_candidate"` and
`"component_integrated"`, `component_byte_offset` must be present.

### 6. RouteInstRowByteCandidateRecord

Route row bytes can only be a candidate after route endpoint, layout, boundary,
and field bindings exist.

```python
@dataclass(frozen=True)
class RouteInstRowByteCandidateRecord:
    row_byte_candidate_id: str
    source_ring_edge_id: str
    route_endpoint_patch_id: str
    inst_field_binding_id: str
    instruction_layout_plan_id: str
    exe_block_writer_plan_id: str | None
    instruction_boundary_plan_id: str | None
    component_placement_plan_id: str | None

    opcode: Literal["COPY", "COPYT", "LDN"]
    decoded_fields: Mapping[str, object]
    pending_decoded_fields: Mapping[str, object]
    field_owner_status: Mapping[str, Literal["bound", "pending", "blocked"]]
    field_owner_ids: Mapping[str, str]
    raw_inst_t_row_bytes_sha256: str | None

    decode_roundtrip_status: Literal[
        "not_emitted",
        "candidate_route_decode_roundtrip",
    ]
    placement_status: Literal[
        "unplaced_candidate",
        "placed_candidate",
        "component_integrated",
    ]
    component_byte_offset: int | None

    final_row_bytes_claim: bool
    component_integration_claim: bool
    runtime_ready_claim: bool
    blocker_ids: tuple[str, ...]
```

For Phase 1, `raw_inst_t_row_bytes_sha256` may remain `None`.  The first useful
artifact is route endpoint closure, not bytes.

## Invariants

1. No route row may be emitted from `RingEdgeRecord` alone.

2. `route_push.src` must use the sender `(app_id, task_id, pe)` allocation
   scope.

3. `route_recv.dst` must use the receiver `(app_id, task_id, pe)` allocation
   scope.

4. `route_recv.dst` must equal the `globalmax_recv` operand consumed by the
   paired FMAX update.

5. A route row's `dst_pes_pos` and `dst_blocks_idx` must come from receiver
   placement/exeBlock plans, not from serializer constants.

6. COPYT lane expansion must be explicit.  If lane policy is unresolved, the
   route row remains blocked.

7. `flow_ack` must be owned by a route child-slot or base-slot policy.  It
   cannot be zero-filled by default.

   Blocker:

```text
log10max_route_flow_ack_policy_missing
```

8. `block_idx`, `stages_start_pc`, and `end_inst` must be owned by layout /
   exeBlock / boundary artifacts.

9. Candidate bytes are not final bytes.  `candidate_route_decode_roundtrip`
   cannot imply `runtime_ready`.

10. Cross-task ring cooperation inside one app is forbidden in V1.  If a ring
    phase crosses independent tasks, it must be split by app boundary or remain
    blocked.

11. Phase 0 endpoint closure may leave `route_family_status` as
    `pending_phase2_decision`.  It may not pretend `COPY` is selected without a
    Phase 2 decision record.

12. Every route dependency must have an ordering proof.  Value continuity alone
    is insufficient.

13. V1 uses one collective phase per exeBlock.  Any phase fusion requires an
    explicit ordering proof and is outside Phase 0/1.

## Alternatives Considered

### Emit route bytes from the ring plan directly

Rejected.  This makes the byte writer invent receiver block/operand fields and
violates B-line authority boundaries.

### Reuse `program_bin.py` legacy compatibility patch as the trunk path

Rejected as trunk authority.  `_legacy_copy_inst_with_route_target()` is useful
evidence for how receiver patching works, but it is a legacy GEMM compatibility
adapter.

### Use source-template-fixed COPY spans for all route rows

Deferred.  This may be a good emergency source of candidate bytes when exact
evidence exists, but it must still pass `RouteEndpointPatch` and layout
continuity.  Source spans are not allowed to hide missing endpoint ownership.

### Jump straight to component insertion

Rejected.  Component insertion also requires MICC exeBlock rows and stage PCs.
Without them, CBUF rows can decode but still be unreachable or unordered.

## Migration / Implementation Plan

### Phase 0: route endpoint report only

Implement:

```text
RouteEndpointPatchReport
check_stream_compiler_log10max_route_endpoint_patch.py
```

Pass conditions:

```text
route edge count = 30 for current 4x4 representative ring
route endpoint count by phase = 12 / 3 / 3 / 12
route push/recv pairs are unique
logical route edges do not directly claim physical route rows
sender src operand allocation exists
receiver dst operand allocation exists
receiver dst == paired FMAX globalmax_recv
sender next/globalmax src continuity holds
dst PE position is concrete
dst PE coordinate status is source_backed or profile_backed
dst block/layout may remain pending with explicit blocker
route_family_status may be pending_phase2_decision
flow_ack_status may be pending_policy but must carry log10max_route_flow_ack_policy_missing
runtime_ready = false
uploadable = false
```

### Phase 1: layout and boundary planning

Implement report-only:

```text
InstructionLayoutPlan
ExeBlockWriterPlan
InstructionBoundaryPlan
ComponentPlacementPlan
```

Pass conditions:

```text
every candidate row has stage and local order
FLOW route rows have stage ownership
FMAX update rows have CAL stage ownership or explicit chosen stage evidence
route_recv -> FMAX -> next route_push has ordering_status != blocked
V1 uses one collective phase per exeBlock unless an ordering proof allows fusion
stage spans fit PE-local instruction capacity
end_inst is assigned only by boundary plan
component_byte_offset is absent until placement
```

### Phase 2: route row byte candidate RFC

Write a follow-up RFC before coding bytes.  It must choose:

```text
COPY vs COPYT vs LDN/source-template route row family
flow_ack policy
COPYT lane policy
source_template_fixed evidence requirements
decode fields required for route rows
```

### Phase 3: candidate route bytes

Allowed only after Phase 2 acceptance.

### Phase 4: component integration

Allowed only after route bytes, FMAX update bytes, local_reduce bytes,
max_with_floor bytes, MICC exeBlock rows, and placement rows all have matching
decode/provenance reports.

## Validation Plan

Phase 0 checks:

```bash
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_route_endpoint_patch.py
```

The check must fail if:

```text
route_recv.dst != FMAX.src_received
route_push.src does not match local_reduce or previous FMAX output
receiver allocation scope is wrong
sender allocation scope is wrong
dst PE is symbolic
dst block is claimed without layout evidence
flow_ack is silently zero-filled
route family is selected without Phase 2 decision
phase distribution differs from 12 / 3 / 3 / 12
```

Phase 1 checks:

```bash
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_instruction_layout_plan.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_exeblock_writer_plan.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_instruction_boundary_plan.py
```

Preintegration gate:

```text
runtime_ready remains false until:
  route_endpoint_status = bound
  instruction_layout_status = pc_assigned
  exe_block_writer_status = micc_candidate
  boundary_status = bound
  component_placement_status = component_integrated
```

Validation framework hooks:

```text
dfu3500_memory_template_check:
  flow/base slots, active memory/template fields

dfu3500_control_graph_check:
  exeBlock successor/predecessor consistency
  stage_start_pc range and span
  root reachability
```

These framework checks are not substitutes for B-line report ownership.  They
are final artifact judges after B-line emits candidate components.

## Risks and Mitigations

### Risk: route rows become a new communication backend

Mitigation: Route rows must consume existing `StreamAction` / `FiberOp` /
`RingEdgeRecord` provenance and may not introduce new communication IR.

### Risk: COPYT lane expansion grows scope

Mitigation: V1 may choose COPY-only source-template evidence if sufficient.
COPYT lane policy requires explicit lane count and stride report.

### Risk: layout planning delays progress

Mitigation: Phase 0 endpoint closure can proceed without bytes.  Phase 1 may
assign stage/local order before final component offsets.

### Risk: candidate decode is mistaken for uploadable

Mitigation: gate states must remain:

```text
candidate_route_decode_roundtrip != component_integrated
component_integrated != numerically_checked
runtime_ready = false until component + MICC control graph checks pass
```

### Risk: task-axis semantics are violated

Mitigation: log10max V1 ring route rows may only operate inside a single task
ordering domain.  Cross-task cooperation must use app boundaries or stay
blocked.

## Expected Effect

After Phase 0/1, B-line should be able to say:

```text
For every log10max ring route edge:
  sender source operand is known
  receiver destination operand is known
  receiver PE is known
  route row stage/order is planned
  unresolved fields are named blockers
```

But B-line should still say:

```text
route raw bytes are not final
component bytes are not integrated
runtime_ready is false
uploadable is false
```

This turns the next blocker from:

```text
route row bytes missing
```

into:

```text
route endpoint/layout/boundary/component placement status
```

which is much easier to parallelize safely.

## Open Questions

1. For GlobalMax route rows, should V1 use native COPY, COPYT lane expansion,
   or source-template-fixed COPY spans?

   Phase 0/1 answer: do not choose.  Record
   `route_family_status=pending_phase2_decision`.

2. Does the current log10max route value need tensor-lane COPYT semantics, or
   can replicated fp32 vector movement use COPY-like rows with existing route
   evidence?

3. What exact `flow_ack` policy is required for simulator `inst_t` route rows,
   and what should remain RTL-only derived metadata?

   Phase 0/1 answer: add `FlowAckPolicy` as an explicit pending owner and keep
   `log10max_route_flow_ack_policy_missing` until Phase 2.

4. Should FMAX update rows live in CAL stage between route recv and next route
   push, or should they be modeled as FLOW-adjacent compute rows with explicit
   ordering?

   Phase 0/1 answer: do not rely on stage names.  Require an
   `ordering_status` proof for every `route_recv -> FMAX -> next route_push`
   edge.

5. How many exeBlocks are needed per PE for row_reduce / col_reduce /
   col_broadcast / row_broadcast phases?  One phase per block is safer; fewer
   blocks may be faster but needs ordering proof.

   V1 answer: one collective phase per exeBlock.  Fusion is deferred.

## Recommended Decision

Accept Phase 0/1 only:

```text
Do:
  implement RouteEndpointPatch report
  implement InstructionLayoutPlan / ExeBlockWriterPlan / BoundaryPlan reports
  connect them to preintegration blockers
  keep runtime_ready/uploadable false

Do not:
  emit route/COPY/COPYT raw bytes yet
  insert route rows into final CBUF/MICC
  claim direct physical allreduce
  allow cross-task in-app route cooperation
  let serializer fill missing route/layout fields
```

Then write a focused Phase 2 RFC for the actual route row byte family:

```text
COPY vs COPYT vs source-template-fixed
flow_ack policy
lane policy
decode roundtrip requirements
component integration criteria
```

This keeps B-line moving toward binary emission while preserving the core rule:
bytes are the end of a field ownership chain, not the place where missing
semantics are invented.
