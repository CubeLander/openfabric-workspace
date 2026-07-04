# RFC: B-line Log10max Operand Chain Closure

## Status

Draft for review.

Reviewer disposition:

```text
Accept.
Proceed as the next report-only phase.
Tighten continuity, counting, blocker, and placeholder-contract wording before
implementation.
```

Decision under review:

```text
After the ring-update OperandPlaceholder / OperandAllocation /
InstOperandPatch stop-bleed work, the next B-line log10max task is to close the
operand continuity chain around the ring:

local_reduce_max output
  -> first route_push.src
  -> initial globalmax_acc_in / first FMAX.src_current when that PE needs a seed
  -> route_recv.dst
  -> FMAX.src_received
  -> FMAX.dst
  -> next route_push.src or max_with_floor.globalmax_src
```

Current recommendation:

```text
Accept as the next report-only implementation phase.
Do not proceed to final CBUF/MICC component insertion until this chain is
allocation-backed and checked end-to-end.
```

This RFC is not a request to enable `runtime_ready`.  It is the next hardening
step before final component integration.

## Summary

The previous operand allocation RFC established the missing B-line contract:

```text
OperandPlaceholder
  -> OperandAllocation
  -> InstOperandPatch
  -> candidate pack/decode proof
  -> final component row later
```

The current implementation checkpoint has closed the receiver-side FMAX update
candidate path:

```text
30 ring update FMAX rows
90 OperandPlaceholder records
90 OperandAllocation records
30 allocation-backed FMAX InstOperandPatch records
60 route push/recv operand patch candidates
```

The gate remains honest:

```text
runtime_ready = false
uploadable = false
```

The remaining exposed report-level blocker is:

```text
log10max_ring_route_push_local_reduce_operand_allocation_missing
```

This blocker is real.  Some `route_push_global_max` rows are not sourcing the
output of a previous FMAX update.  They source the initial local maximum from:

```text
FiberOp(local_reduce_max_tile)
```

That producer is currently outside the ring-update operand allocation report.
If we skip this connection, the first route push in each reduce/broadcast chain
could read a fabricated operand index.  That would reintroduce the exact class
of bug the operand allocation RFC was designed to kill.

There is a second endpoint trap: the first receiver-side FMAX update on a PE
also needs a current accumulator value.  When that accumulator is seeded by the
same PE's local reduce result, the report must also prove:

```text
local_reduce_max_out == initial globalmax_acc_in / first FMAX.src_current
```

Otherwise the route push source may be correct while the first local update
still reads a fabricated accumulator operand.

## Current State

### Already modeled

The log10max ring-first path already has semantic and scheduling structure:

```text
RingEdgeRecord
  source_stream_action_id
  recv_stream_action_id
  update_action_id
  src_pe / dst_pe
  phase
  route_role = GlobalMax

StreamAction(route_push_global_max / route_recv_global_max / max_update_global_max)
  -> FiberOp(fragment_route_push / fragment_route_recv / global_max_tile)
  -> route_path proof
  -> RouteRoleBinding(GlobalMax)
```

The ring update template work added:

```text
FiberOp(global_max_tile, semantic_op=max_update_global_max)
  -> TemplateExpansion(dfu3500_log10max_ring_globalmax_update)
  -> BinaryLayout row candidate
  -> FMAX InstOperandPatch candidate
```

The route patch checkpoint added report-only route operand patch candidates:

```text
route_recv.dst == allocation(globalmax_recv)
FMAX.src_received == allocation(globalmax_recv)
FMAX.dst == allocation(globalmax_acc_out)
next route_push.src == allocation(previous globalmax_acc_out)
```

### Still missing

The current report cannot yet prove:

```text
local_reduce_max_tile.output == first route_push.src
local_reduce_max_tile.output == first FMAX.src_current when used as local seed
final globalmax_acc_out == max_with_floor_tile.globalmax_src
```

The first condition blocks initial ring propagation.  The second condition
blocks the first receiver-side update on PEs whose current accumulator is
seeded from local reduce.  The third condition is required before postprocess
rows can be allocation-backed.

### Related existing evidence

The old vendor/A-line path has a tag-to-operand model through
`Task_Resource`.  COPY/COPYT endpoint patching is not a cosmetic late write;
it mutates operand fields based on allocated tags and receiver ownership.

B-line should use that as evidence, not as semantic authority.

## Problem

The current report-only chain proves the middle of the ring but not the ends:

```text
middle:
  route_recv -> FMAX update -> later route_push

unclosed ends:
  local_reduce_max -> first route_push
  local_reduce_max -> first FMAX current accumulator
  final FMAX update -> max_with_floor postprocess
```

Without closing those ends, a later byte writer has two unsafe choices:

```text
1. invent operand indices for the initial local_reduce output
2. invent operand indices for the first FMAX current accumulator
3. invent operand indices for the final GlobalMax consumer
```

Both are forbidden.

The B-line compiler must keep the same authority split:

```text
FiberOp names semantic actions.
Template/BinaryLayout rows name operand roles.
OperandAllocation assigns physical operand indices.
InstOperandPatch writes row operand fields.
Serializer only packs already-patched rows.
```

If `route_push`, `local_reduce_max`, or `max_with_floor` rows write operand
fields without this chain, the serializer becomes a hidden backend again.

## Goals / Non-goals

### Goals

1. Add report-only operand placeholders for log10max chain endpoints:

```text
local_reduce_max_out
max_with_floor_globalmax_src
```

2. Prove allocation continuity:

```text
local_reduce_max_out allocation == first route_push.src allocation
local_reduce_max_out allocation == initial globalmax_acc_in allocation
  when the first FMAX update is seeded by local reduce
final globalmax_acc_out allocation == max_with_floor.globalmax_src allocation
```

3. Keep allocation scoped by:

```text
(app_id, task_id, pe)
```

4. Preserve task-local ring assumptions:

```text
task_axis = 1 for one-app ring
cross-task cooperation requires app boundary or explicit materialization
```

5. Convert current blocker:

```text
log10max_ring_route_push_local_reduce_operand_allocation_missing
```

into a narrower final blocker:

```text
log10max_local_reduce_row_bytes_missing
log10max_route_row_bytes_missing
log10max_max_with_floor_row_bytes_missing
log10max_component_integration_missing
```

only after endpoint operand patch reports pass.

### Non-goals

This RFC does not:

```text
emit final CBUF/MICC bytes
write COPY/LDN route row bytes
rebase exeBlock/subtask PC or active row counts
claim numerical correctness
claim SimICT execution
turn runtime_ready true
implement generic register allocation
implement direct_route_reduce_broadcast
allow cross-task operand sharing
```

## Proposed Design

### 1. Add endpoint operand placeholders

Introduce a report-only endpoint view for log10max.  This may use a
log10max-specific DTO for readability, but it must project into the same
generic `OperandPlaceholder` records consumed by the unified allocator.  It
must not become a second allocation contract.

```python
@dataclass(frozen=True)
class Log10MaxEndpointOperandPlaceholder:
    placeholder_id: str
    operator: Literal["log10max"]
    source_fiber_op_id: str
    source_stream_action_id: str | None
    app_id: int
    task_id: int
    pe: str
    role: Literal[
        "local_reduce_max_out",
        "max_with_floor_globalmax_src",
    ]
    value_kind: Literal["replicated_vector"]
    dtype: Literal["fp32"]
    allocation_scope: str
    producer_placeholder_ids: tuple[str, ...]
    consumer_placeholder_ids: tuple[str, ...]
    consumer_stream_action_ids: tuple[str, ...]
    alias_policy: Literal["forbidden"]
```

These records are derived from existing log10max fiber/ring reports.  They are
not new semantic IR.  The allocator consumes their projected
`OperandPlaceholder` form, not a private endpoint-only type.

Expected ids must be deterministic:

```text
opnd:log10max:t0:pe0_0:local_reduce_max_out
opnd:log10max:t0:pe0_0:max_with_floor_globalmax_src
```

Endpoint counts must be derived from the ring participating and final consumer
PE sets:

```json
{
  "participating_pe_count": 16,
  "consumer_pe_count": 16,
  "local_reduce_endpoint_placeholder_count": 16,
  "max_with_floor_endpoint_placeholder_count": 16
}
```

The values above are the current 4x4 representative ring expectation.  The
implementation must derive them rather than hardcode them.

### 2. Bind first route push to local reduce output

For every `route_push_global_max` whose source is not a previous
`globalmax_acc_out`, the report must point at:

```text
local_reduce_max_out
```

and the route patch must satisfy:

```text
route_push.src == allocation(local_reduce_max_out)
```

This clears:

```text
log10max_ring_route_push_local_reduce_operand_allocation_missing
```

only if every initial push has a concrete endpoint allocation.

### 2b. Bind initial FMAX current input to local reduce output

For every PE whose first `global_max_tile` update needs a local current
accumulator seed, the report must also satisfy:

```text
FMAX.src_current == allocation(local_reduce_max_out)
globalmax_acc_in == local_reduce_max_out
```

This is value identity reuse across producer and consumer rows.  It is not
instruction-level src/dst aliasing.

### 3. Bind final GlobalMax to postprocess consumer

For every final GlobalMax value in a PE:

```text
final globalmax_acc_out
```

the report must create or reuse:

```text
max_with_floor_globalmax_src
```

with value identity reuse:

```text
allocation(max_with_floor_globalmax_src)
  == allocation(final globalmax_acc_out)
```

The postprocess row itself may remain without final bytes in this RFC, but it
must no longer have a symbolic GlobalMax operand.

### 4. Keep value identity reuse distinct from instruction aliasing

This RFC continues the previous distinction:

```text
value identity reuse:
  required when a consumer reads a producer output

instruction operand aliasing:
  forbidden in V1 unless row semantics prove it
```

So this is required:

```text
local_reduce_max_out -> route_push.src
local_reduce_max_out -> initial FMAX.src_current
final globalmax_acc_out -> max_with_floor.globalmax_src
```

But this remains forbidden:

```text
FMAX.src0 == FMAX.dst0
```

### 5. Do not turn endpoint reports into component rows

Endpoint reports may produce candidate operand patches, but they must carry:

```text
final_row_bytes_claim = false
component_integration_claim = false
runtime_ready = false
```

until a separate component-integration RFC or implementation phase proves:

```text
exact route COPY/LDN row bytes
local_reduce row bytes
max_with_floor row bytes
subtask/exeBlock placement
decode/provenance roundtrip
package gate conformance
```

## Data Flow

The intended report chain is:

```text
Log10MaxRingPlanReport
  -> Log10MaxRingFiberProjectionReport
  -> RingUpdateTemplate/BinaryLayout reports
  -> RingUpdate OperandPlaceholder report
  -> Endpoint OperandPlaceholder report
  -> unified OperandAllocation report
  -> FMAX InstOperandPatch report
  -> RouteOperandPatch report
  -> EndpointConsumerPatch report
  -> final component integration later
```

The route patch report consumes the unified allocation report.  It does not
perform allocation itself.

## Invariants

### Authority

```text
StreamAction / FiberOp remain semantic authority.
Endpoint operand reports are derived binding artifacts.
Route patch reports are target binding artifacts.
Serializer never allocates operands.
```

### Scope

```text
allocation_scope = (app_id, task_id, pe)
```

Same numeric `operand_idx` in two different tasks is not a data dependency.
Cross-task data movement cannot be represented by shared operand identity.

Route direction also fixes ownership:

```text
route_push.src is allocated in sender (app_id, task_id, src_pe) scope
route_recv.dst is allocated in receiver (app_id, task_id, dst_pe) scope
```

Numeric operand equality without matching scope is not continuity.

### Continuity

The following must all hold before final component integration:

```text
local_reduce_max_tile.output
  == first route_push_global_max.src

local_reduce_max_tile.output
  == first ring_update_FMAX.src_current
  when that PE's update uses local seed

route_recv_global_max.dst
  == ring_update_FMAX.src_received

ring_update_FMAX.dst
  == next route_push_global_max.src
  or max_with_floor_tile.globalmax_src
```

### Shape

V1 endpoint values must match the GlobalMax ring representation:

```text
value_kind = replicated_vector
dtype = fp32
```

If `local_reduce_max_tile` produces an incompatible physical shape, the report
must fail closed with:

```text
log10max_local_reduce_globalmax_shape_mismatch
```

### No hidden final bytes

No endpoint patch may be used as final bytes unless it has:

```text
InstOperandPatch
decode roundtrip
provenance roundtrip
component row placement
source FiberOp id
source stream action id when applicable
```

## Alternatives Considered

### Alternative A: Let route push read a hardcoded operand index

Rejected.

This reintroduces the bug class the operand allocation RFC fixed.

### Alternative B: Treat local reduce output as implicit GlobalMax seed

Rejected for final lowering.

It is acceptable as prose, but not as binary lowering.  The seed must be an
explicit allocated value.

### Alternative C: Delay endpoint allocation until component writer

Rejected.

The component writer would become an allocator and hidden scheduler.

### Alternative D: Implement full liveness / register allocation now

Deferred.

V1 needs deterministic, monotonic, task/PE-scoped allocation with capacity
guards.  Liveness optimization can wait.

### Alternative E: Use PE00 or direct allreduce instead

Rejected for this phase.

The selected delivery strategy is still:

```text
ring_spmd_row_then_col
```

PE00 remains an escape hatch only if ring evidence stalls.  Direct physical
allreduce remains deferred.

## Migration / Implementation Plan

### Phase 0: Gate wording and blockers

Add or preserve blockers:

```text
log10max_endpoint_operand_placeholders_missing
log10max_endpoint_operand_allocation_missing
log10max_ring_route_push_local_reduce_operand_allocation_missing
log10max_max_with_floor_globalmax_operand_allocation_missing
log10max_endpoint_operand_patch_missing
log10max_local_reduce_row_bytes_missing
log10max_route_row_bytes_missing
log10max_max_with_floor_row_bytes_missing
log10max_component_integration_missing
```

None of these may be cleared by raw skeleton rows.

### Phase 1: Endpoint placeholder report

Build:

```text
Log10MaxEndpointOperandPlaceholderReport
```

Minimum checks:

```text
one local_reduce_max_out placeholder per PE participating in ring
one max_with_floor_globalmax_src placeholder per final consumer PE
counts derived from ring participating_pe_set and consumer_pe_set
endpoint records project to generic OperandPlaceholder records
all ids deterministic
all placeholders carry app_id / task_id / pe
all are fp32 replicated_vector for V1
all are unallocated
runtime_ready = false
```

Consumer checks:

```text
each local_reduce_max_out feeds initial route_push.src or initial FMAX.src_current
each max_with_floor_globalmax_src is produced by final globalmax_acc_out
```

### Phase 2: Unified allocation report

Extend the existing allocation report so it includes:

```text
ring update placeholders
local_reduce_max_out placeholders
max_with_floor_globalmax_src placeholders
```

Rules:

```text
local_reduce_max_out:
  new monotonic allocation in task_pe scope

first route_push.src:
  value identity reuse of local_reduce_max_out

initial globalmax_acc_in / FMAX.src_current:
  value identity reuse of local_reduce_max_out when local seed is required

max_with_floor_globalmax_src:
  value identity reuse of final globalmax_acc_out
```

The report summary must split:

```text
placeholder_count
allocation_record_count
new_operand_allocation_count
value_identity_reuse_count
source_template_fixed_count
blocked_count
```

### Phase 3: Route patch closure

Update the route patch report so:

```text
initial route_push rows are patched from local_reduce_max_out allocation
initial FMAX.src_current is patched from local_reduce_max_out allocation
recv rows remain patched to globalmax_recv allocation
later push rows remain patched from previous globalmax_acc_out allocation
```

After this phase, the route patch report should no longer carry:

```text
log10max_ring_route_push_local_reduce_operand_allocation_missing
```

It must still carry component/row-byte blockers.

### Phase 4: Max-with-floor GlobalMax source patch

Add a report-only patch candidate for:

```text
max_with_floor_tile.globalmax_src
```

It must prove:

```text
GlobalMax source operand is final globalmax_acc_out allocation
log_spec source operand is separately named or explicitly deferred
output placeholder is allocated or explicitly deferred
```

This phase only clears the GlobalMax source allocation blocker.  It does not
claim `max_with_floor_tile` is fully patched, and it may keep local elementwise
row bytes blocked.

### Phase 5: Component integration proposal

Only after Phases 1-4 pass should a later phase propose:

```text
route COPY/LDN raw bytes
local_reduce row bytes
max_with_floor row bytes
subtask/exeBlock row placement
final CBUF/MICC insertion
runtime_ready gate transition
```

That work should be reviewed separately.

## Validation Plan

Add focused tools:

```text
compiler/tools/check_stream_compiler_log10max_endpoint_operand_placeholders.py
compiler/tools/check_stream_compiler_log10max_endpoint_operand_allocation.py
compiler/tools/check_stream_compiler_log10max_ring_route_operand_patch.py
compiler/tools/check_stream_compiler_log10max_max_with_floor_operand_patch.py
```

Required checks:

```text
endpoint placeholder counts match ring consumer PE set
all endpoint placeholders are task_pe scoped
local_reduce_max_out allocations are new or source-template fixed with evidence
initial route_push.src uses local_reduce_max_out allocation
final max_with_floor.globalmax_src uses final globalmax_acc_out allocation
no endpoint patch claims final row bytes
runtime_ready remains false
```

Regression checks to keep running:

```bash
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_ring_update_operand_placeholders.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_ring_update_operand_allocation.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_ring_update_inst_operand_patch.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_ring_route_operand_patch.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_bline_runtime_ready_preintegration.py
```

Expected gate state after this RFC:

```text
runtime_ready = false
uploadable = false
log10max blocked on row bytes / component integration
```

## Risks and Mitigations

### Risk: endpoint reports become a second allocator

Mitigation:

Endpoint reports only name placeholders and continuity.  The unified allocator
still owns operand indices.

### Risk: local reduce output shape is not compatible with GlobalMax route value

Mitigation:

V1 requires:

```text
value_kind = replicated_vector
dtype = fp32
```

If local reduce produces a different physical shape, this RFC must stop at a
shape blocker instead of patching route rows.

### Risk: max_with_floor needs more than GlobalMax operand binding

Mitigation:

This RFC only closes the GlobalMax source.  `log_spec` source, constants, and
output operands must be named explicitly or left as blockers.

### Risk: cross-task values are accidentally shared

Mitigation:

Every allocation and placeholder carries `(app_id, task_id, pe)`.  Any
cross-task transition must use app boundary or explicit materialization.

### Risk: route COPY/LDN byte semantics are guessed

Mitigation:

This RFC does not emit COPY/LDN bytes.  It only proves operand continuity
required by those future rows.

## Expected Effect

If accepted and implemented, B-line log10max will have an allocation-backed
logical value chain from local reduce through ring movement into postprocess:

```text
local_reduce_max_out
  -> route_push.src
  -> route_recv.dst
  -> FMAX.src_received
  -> FMAX.dst
  -> next route_push.src
  -> max_with_floor.globalmax_src
```

The immediate practical effect is:

```text
the current local_reduce route-push blocker is removed
the remaining blockers become row-byte/component-integration blockers
runtime_ready remains honest
```

## Open Questions

| Question | Recommended V1 answer |
| --- | --- |
| How many local_reduce endpoint placeholders? | One per task/PE that participates in the single-task ring. |
| Is local_reduce output scalar or vector? | Treat as replicated fp32 vector for V1, matching GlobalMax route/FMAX representation. |
| Can max_with_floor reuse final acc_out allocation directly? | Yes, as value identity reuse. It is not instruction aliasing. |
| Does max_with_floor output allocation belong in this RFC? | Only as a named/deferred blocker unless it is trivial to add report-only. Do not block endpoint closure on full postprocess bytes. |
| Can this clear runtime_ready? | No. It can only move log10max from operand-continuity blockers to row-byte/component blockers. |
| Can endpoint values cross tasks by sharing operand_idx? | No. Cross-task cooperation requires app boundary or explicit materialization. |

## Recommended Decision

Accept this RFC as the next B-line log10max implementation phase.

Immediate execution:

```text
1. Add endpoint placeholders for local_reduce_max_out and max_with_floor_globalmax_src.
2. Fold endpoints into the existing task_pe allocation report.
3. Re-run route operand patch continuity so initial route_push rows are allocation-backed.
4. Add max_with_floor GlobalMax source patch report.
5. Keep runtime_ready false and final component integration blocked.
```

The goal is not to ship bytes in this step.  The goal is to make sure that when
bytes are shipped, every operand-bearing row is already backed by a B-line
allocation artifact rather than a guessed operand number.
