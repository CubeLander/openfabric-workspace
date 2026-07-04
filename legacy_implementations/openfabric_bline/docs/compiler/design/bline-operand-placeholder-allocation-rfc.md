# RFC: B-line Operand Placeholder and Allocation Contract

## Status

Draft for immediate stop-bleed review.

Decision under review:

```text
B-line binary lowering must not write final inst_t operand indices directly from
template candidates.  It must first model operand placeholders, allocate them in
a target/profile-owned allocation pass, and only then patch inst_t rows with a
decode/provenance roundtrip.
```

Current recommendation:

```text
Accept as a required blocker before final ring update component integration.
```

Reviewer disposition:

```text
Accept.
Tighten stop-bleed gate.
Implement V1 as a narrow DFU3500 task_pe allocator, not a full register allocator.
```

The log10max ring update FMAX candidate rows may remain as diagnostic evidence,
but they must not be consumed by `runtime_ready` or final CBUF/MICC package
assembly until this operand allocation contract exists.

## Summary

B-line is now close enough to binary emission that operand indices have become
semantic, not cosmetic.  The current codebase has several partial mechanisms:

```text
program_asm.ProgramInstruction.symbolic_operands
template_ops.InstructionIntent.operand_policy
binding.py vendor_operand_binding_intent reports
relu_binding.py local ReLU operand binding reports
log10max_template_pack.py synthetic operand role roundtrips
dfu3500.task_resource_replay.Dfu3500TaskResourceState
program_bin._legacy_operand_idx_by_task_processor_tag
```

But these do not form a B-line trunk contract:

```text
OperandPlaceholder
  -> OperandAllocation
  -> InstOperandPatch
  -> pack/decode proof
  -> final component row
```

Without this contract, progressive binary writing will silently hardcode values
such as:

```text
src_operands_idx = [0, 128, 0]
dst_operands_idx = [256, 0, 0]
```

Those values are useful as local FMAX skeleton evidence, but they are not yet
valid final operand allocation for ring reduce, ReLU, or arbitrary op chains.

The revised blocker chain is:

```text
log10max_ring_update_template_missing
  -> log10max_ring_update_operand_placeholders_missing
  -> log10max_ring_update_operand_allocation_missing
  -> log10max_ring_update_inst_operand_patch_missing
  -> log10max_ring_update_row_bytes_missing / component integration blockers
```

`inst_t` writers and serializers must not skip any stage in this chain.

## Current State

### A-line / Vendor Evidence

The vendor path does have a placeholder/tag allocation model.  It is not a
late cosmetic patch.

Vendor `common_oper` carries tag strings in CSV/Inst records:

```text
csv_oper.h:
  src_reg_idx0_tag
  src_reg_idx1_tag
  dst_reg_idx_tag
```

Vendor `Task_Resource::get_reg_idx` in
`simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/inst_blk_map.cpp`
allocates first-use tags into operand indices.  In the normal layout-counter
path it uses:

```text
operand_idx =
  (reg_idx % OPERANDS_RAM_NUM) * OPERANDS_PER_OPERAND_RAM
  + reg_idx / OPERANDS_RAM_NUM
```

In the PE/order-pool path, `Task_Resource::fill_reg_idx` scans instruction
stages, calls `get_reg_idx` for non-empty source/destination tags, mutates:

```text
inst.src_operands_idx[0]
inst.src_operands_idx[1]
inst.dst_operands_idx[0]
```

and tracks operand RAM availability per PE/stage.  Pseudo tensor instructions
such as `HLDT` / `HSTT` / `COPYT` expand lanes by adding
`OPERANDS_PER_OPERAND_RAM` to the base operand.  COPY destination patching uses
the child/receiver task resource, not the sender's local tag table.

This matters for B-line: final `inst_t` operand fields must be the output of a
resource allocation/patch pass.  They must not be copied from an early template
candidate.

Baseline verdict:

```text
CSV-time operand indices are not the final binary authority.
Task_Resource owns final per-task / per-PE operand assignment.
COPY/COPYT destination operands are patched from the receiver Task_Resource.
```

The B-line equivalent must therefore expose the same three-step shape as
first-class artifacts:

```text
tag / logical role placeholder
  -> task_pe allocation
  -> inst_t operand field patch
```

This is not extra validation work.  It is part of binary lowering semantics.

### What Exists

`program_asm.py` has symbolic operand payloads:

```text
ProgramInstruction.symbolic_operands
```

These preserve frontend/source references but do not allocate final DFU operand
RAM indices.

`template_ops.py` has operand intent:

```text
InstructionIntent.operand_policy
```

This records policies such as:

```text
input_fragment_and_zero_constant
local_log10_fragment_and_global_threshold_scalar
globalmax_acc_in_recv_acc_out_non_inplace
```

But it is string policy, not an allocation artifact.

`binding.py`, `relu_binding.py`, and `log10max_template_pack.py` have local
binding reports.  They are useful evidence surfaces, but they are not a common
allocator or patch authority.

`dfu3500/task_resource_replay.py` models legacy vendor `Task_Resource`:

```text
Dfu3500TaskResourceState.get_reg_idx(tag)
Dfu3500TaskResourceState.seed_tensor(tag, group_idx)
layout_operand_idx(reg_idx)
COPY receiver destination patching
```

This is the closest allocator-like component.  However, it is legacy replay,
default-off, and not first-class B-line IR.

`program_bin.py` can patch COPY destination operands in the legacy GEMM path:

```text
_legacy_copy_receiver_dst_operand_idx0(...)
_legacy_operand_idx_by_task_processor_tag(...)
```

That is a compatibility patch, not a general B-line operand allocation contract.

### OpenFabric A-line / Legacy Python Findings

The current Python compatibility path mirrors parts of the vendor allocation
model, but it is split between a complete legacy CSV encoder, an opt-in replay
candidate, and a legacy GEMM compatibility patch.

1. `LegacyCsvEncoder._get_reg_idx` and `_tensor_dst_reg_idx` are tag-to-operand
   allocation for legacy CSV templates.

   Evidence:

   ```text
   compiler/gpdpu_compiler/core/program_legacy_inst.py:304
     src_operands_idx = _get_reg_idx(src tags)

   compiler/gpdpu_compiler/core/program_legacy_inst.py:309
     dst_operands_idx = _tensor_dst_reg_idx(...) or _get_reg_idx(dst tag)

   compiler/gpdpu_compiler/core/program_legacy_inst.py:359
     _get_reg_idx(tag)

   compiler/gpdpu_compiler/core/program_legacy_inst.py:408
     _tensor_dst_reg_idx(...)
   ```

   `_get_reg_idx` is a first-use tag table.  Regular tags get
   `_layout_operand_idx(counter)` unless `layout_regular_operands=False`.
   Reuse tags beginning with `r` use the reuse table.  Tensor tags are routed
   through `_tensor_idx_by_tag`.

   `_tensor_dst_reg_idx` is the tensor/pseudo-op allocator for
   `HLDT` / `ILDT` / `ILDMT` / `HSTT` / `ISTT` / `COPYT`; it assigns a
   group-local base and stores it in `_tensor_idx_by_tag`.  Pseudo expansion
   then uses lane offsets:

   ```text
   first.dst_operands_idx[0] + lane * OPERANDS_PER_OPERAND_RAM
   ```

2. `task_resource_replay` is a source-derived replay model, but production
   replay is opt-in and currently compatibility-scoped.

   Evidence:

   ```text
   compiler/gpdpu_compiler/core/dfu3500/task_resource_replay.py:1
     module states vendor Task_Resource mutates final inst_t operand fields

   compiler/gpdpu_compiler/core/dfu3500/task_resource_replay.py:41
     OPENFABRIC_ENABLE_DFU3500_TASK_RESOURCE_REPLAY

   compiler/gpdpu_compiler/core/dfu3500/task_resource_replay.py:204
     Dfu3500TaskResourceState.get_reg_idx(tag)

   compiler/gpdpu_compiler/core/dfu3500/task_resource_replay.py:221
     retrieve_reg_idx(tag) is strict receiver lookup

   compiler/gpdpu_compiler/core/dfu3500/task_resource_replay.py:241
     seed_tensor(tag, group_idx)

   compiler/gpdpu_compiler/core/dfu3500/task_resource_replay.py:363
     replay_legacy_task_resource(...)

   compiler/gpdpu_compiler/core/dfu3500/task_resource_replay.py:440
     _bind_legacy_inst_operands(...)
   ```

   Replay patches:

   ```text
   inst.src_operands_idx[0]
   inst.src_operands_idx[1]
   inst.dst_operands_idx[0]
   inst.block_idx
   COPY destination operand via receiver task resource
   ```

   It records:

   ```text
   folded_vendor_report["task_resource_replay"]["enabled"] = True
   folded_vendor_report["task_resource_replay"]["candidate_status"]
     = "opt_in_arch13_diff_validation_required"
   ```

   Therefore it is not yet the B-line trunk allocation artifact.

3. `program_bin` has a legacy GEMM COPY receiver patch.

   Evidence:

   ```text
   compiler/gpdpu_compiler/core/program_bin.py:1071
     builds receiver_operand_idx_by_task_processor_tag when
     vendor_inst_mode == "legacy_gemm_compat" and replay was not applied

   compiler/gpdpu_compiler/core/program_bin.py:1152
     _legacy_copy_inst_with_route_target(...)

   compiler/gpdpu_compiler/core/program_bin.py:1203
     _legacy_operand_idx_by_task_processor_tag(...)

   compiler/gpdpu_compiler/core/program_bin.py:1272
     _legacy_copy_receiver_dst_operand_idx0(...)
   ```

   `_legacy_operand_idx_by_task_processor_tag` walks template-bound rows and
   records the first observed operand for `(task_index, processor, tag)`.
   `_legacy_copy_receiver_dst_operand_idx0` then looks up the receiver-side base
   for the COPY destination tag and preserves lane delta from the sender row.
   This closes a specific legacy route/COPY compatibility hole; it is not a
   general B-line allocator.

4. A-line success baselines assert operand behavior directly.

   Evidence:

   ```text
   tests/test_chip_program_frontend.py:
     test_legacy_gemm_template_keeps_input0_strip15_in_input_bank
     test_chip_env_generate_can_emit_legacy_gemm_compat_bundle
     test_legacy_gemm_task_resource_replay_regression_lock
     test_dfu3500_task_resource_state_matches_vendor_regular_layout
     test_dfu3500_task_resource_state_allocates_tensor_lanes_by_group
     test_dfu3500_task_resource_order_pool_matches_vendor_pe_pool
     test_dfu3500_task_resource_receiver_lookup_is_strict
     test_dfu3500_task_resource_replay_is_opt_in
   ```

   These tests lock values such as COPYT lane destinations, HMMAL source
   operands, BET operands, LDN destinations, component hashes, and strict
   receiver-side lookup.  They prove the legacy/A-line path cared about operand
   allocation as a first-class binary fact.

5. B-line lacks the trunk artifact that turns this capability into a clean
   lowering stage.

   Existing B-line reports can name operand intent and local binding evidence,
   but there is no common artifact that owns:

   ```text
   placeholder identity
   allocation scope
   allocator source
   operand_idx result
   alias/lifetime policy
   row patch mapping
   decode proof
   final component provenance
   ```

   That missing artifact is the reason log10max ring update must stop at
   candidate bytes rather than entering final component integration.

   Additional B-line evidence:

   ```text
   compiler/gpdpu_compiler/core/stream_compiler/inst_writers.py:
     operand_route_recv:A currently requires task_resource_replay_authority
     route_forward COPY candidates can remain
       blocked_pending_task_resource_replay_row_authority
     exact seed still needs local_order_or_row_span
     exact seed still needs template_row_sha256
   ```

   In other words, the stream compiler already knows that some operand/route
   rows need TaskResource authority.  The missing piece is not awareness; it is
   a production artifact that carries allocation and patch results into
   final row emission.

### B-line GEMM Operand Allocation Audit

The current B-line GEMM progress does not prove that B-line owns a general
operand allocator.

For GEMM no-ReLU, the raw byte path is:

```text
BinaryLayout row
  -> exact A-line span selector
  -> legacy_gemm_template_for_micro_block_kind(
       block_kind,
       task_index=row.task_id,
       template_index=selector.template_index,
     )
  -> select legacy local_orders
  -> pack_legacy_inst(template[local_order])
  -> raw inst_t span bytes
```

Evidence:

```text
compiler/gpdpu_compiler/core/stream_compiler/inst_writers.py:
  _raw_inst_t_materialization_for_selector(...)
  legacy_gemm_template_for_micro_block_kind(...)
  pack_legacy_inst(...)

tests/test_chip_program_frontend.py:
  test_legacy_gemm_template_keeps_input0_strip15_in_input_bank
  test_dfu3500_task_resource_state_matches_vendor_regular_layout
  test_dfu3500_task_resource_receiver_lookup_is_strict
```

Those selected `LegacyInst` rows already contain concrete
`src_operands_idx` / `dst_operands_idx` values inherited from the A-line /
vendor template path.  The B-line materializer preserves those bytes.  It does
not allocate new operand indices from B-line placeholders.

Therefore GEMM currently has a compatibility-backed operand story:

```text
A-line / vendor Task_Resource and template rows allocated operands earlier.
B-line selects and packs those already-allocated rows.
```

It does not have a trunk allocation story:

```text
B-line FiberOp / TemplateOp
  -> OperandPlaceholder
  -> OperandAllocation
  -> InstOperandPatch
```

This is acceptable for GEMM no-ReLU as a progress bridge because the selected
template rows preserve A-line binary semantics, but it must not be treated as
evidence that arbitrary B-line op chains can safely emit final operands.

For GEMM+ReLU and log10max, any new row that is not copied from an already
allocated legacy template row must go through the new allocation contract.
In particular:

```text
relu_tile HMAX/FMAX rows need explicit input / zero / output allocation.
log10max ring update FMAX rows need GlobalMax allocation and patch records.
```

If a future GEMM path stops using exact A-line span bytes and starts emitting
native B-line GEMM rows, GEMM must also use the same placeholder/allocation/
patch pipeline.

### What Does Not Exist

There is no shared B-line data shape that says:

```text
this logical operand exists
this scope owns its lifetime
this allocator assigned this physical operand index
this inst_t row must patch these fields
this decoded row proved the patch
```

As a result, a template can pack bytes before its operands are truly allocated.
That is exactly the failure mode we must prevent before final component
integration.

## Problem

DFU3500 instruction rows encode operand identity directly:

```text
src_operands_idx[0..2]
dst_operands_idx[0..2]
```

These fields are not just row-local details.  They are constrained by:

```text
per-task / per-PE operand RAM scope
task-level parallel execution
producer-consumer lifetime
route recv visibility
non-in-place update policy
COPY/COPYT receiver-side patching
stage ordering
legacy Task_Resource allocation behavior
```

The current ring update Phase 4 candidate can pack:

```text
FMAX globalmax_acc_in, globalmax_recv -> globalmax_acc_out
```

using a local skeleton:

```text
src = [0, 128, 0]
dst = [256, 0, 0]
```

This proves `FMAX` row shape and local pack/decode mechanics.  It does not
prove:

```text
globalmax_acc_in is allocated before the row executes
globalmax_recv is the destination of the matching route_recv
globalmax_acc_out is the value consumed by the next edge/postprocess
the three operand indices are free and legal in this PE/task scope
the chosen indices do not collide with local log10/clamp/reduce/postprocess rows
```

If final binary integration proceeds without an allocation contract, B-line
will grow another hidden backend path.  That violates the fiber/template
layering principle and makes later arbitrary op composition unsafe.

The concrete failure mode is already visible in the log10max ring update
candidate:

```text
RING_UPDATE_SRC_CURRENT_OPERAND_IDX = 0
RING_UPDATE_SRC_RECEIVED_OPERAND_IDX = 128
RING_UPDATE_DST_UPDATED_OPERAND_IDX = 256
```

Those constants should be reclassified as skeleton evidence only.  They cannot
be consumed as final allocation because they do not know the task/PE operand
state produced by clamp/log/reduce, route receive, postprocess, or future
op-chain composition.

The same applies to any component placement candidate built on top of these
bytes.  A candidate may prove:

```text
pe_index
local_pc
global_row_index
component_byte_offset
record_size = 304
stage = CAL
```

but if its `LegacyInst` still carries unallocated skeleton operands, it must
remain blocked before exeBlock/CBUF integration.  Placement is not allocation.

## Goals

1. Make operand placeholders first-class after TemplateOp/BinaryLayout and
   before final inst_t emission.
2. Support progressive binary writing without hardcoded final operand indices.
3. Preserve provenance from FiberOp and TemplateExpansion into operand
   allocation and row patches.
4. Reuse DFU3500 `Task_Resource` knowledge where useful, but do not let legacy
   replay become the semantic authority.
5. Fail closed when any source/destination operand is unallocated.
6. Keep the design narrow enough to unblock:

```text
GEMM
GEMM+ReLU
log10max ring_spmd_row_then_col
```

## Non-goals

This RFC does not implement:

```text
generic global register allocation
multi-backend operand abstraction
performance-optimal operand reuse
full liveness analysis
direct_route_reduce_broadcast allreduce
numerical correctness proof
```

It also does not move fiber semantics into binary rows.  FiberOp remains the
atomic semantic unit; operand allocation is a target binding step after
TemplateOp/BinaryLayout.

## Proposed Design

### 0. Authority Split

The B-line lowering authority is:

```text
FiberOp
  semantic atomic action

TemplateOp / BinaryLayout
  names operand roles and row shape
  cannot assign final operand indices

OperandPlaceholder
  records logical operand identity and producer/consumer links

OperandAllocation
  assigns DFU operand indices in a target/profile-owned scope

InstOperandPatch
  writes allocated indices into src_operands_idx / dst_operands_idx

Serializer
  packs already-patched rows only
```

Forbidden shortcut:

```text
TemplateOp / RingEdgeRecord / serializer
  -> hardcoded operand idx
  -> final component row
```

### 1. OperandPlaceholder

Add a target-binding level record:

```python
@dataclass(frozen=True)
class OperandPlaceholder:
    schema_version: str
    placeholder_id: str
    role: str
    value_kind: Literal[
        "tile_fragment",
        "scalar",
        "replicated_vector",
        "scratch_scalar",
        "constant",
    ]
    dtype: str
    owner_scope: Literal["task_pe", "task", "subtask", "global"]
    app_id: int
    task_id: int
    pe: str
    parallel_scope: Literal[
        "task_pe",
        "single_task_group",
        "cross_app_boundary",
    ]
    producer_fiber_op_id: str | None
    consumer_fiber_op_ids: tuple[str, ...]
    producer_placeholder_ids: tuple[str, ...]
    consumer_placeholder_ids: tuple[str, ...]
    source_ring_edge_id: str | None = None
    source_stream_action_id: str | None = None
    source_template_op_id: str
    source_binary_row_candidate_id: str | None
    lifetime_group: str
    alias_policy: Literal["forbidden", "allowed", "unknown"]
    allocation_status: Literal["unallocated", "allocated", "blocked"]
    blockers: tuple[str, ...]
```

For log10max ring update V1:

```text
globalmax_acc_in:
  value_kind = replicated_vector
  owner_scope = task_pe
  producer = local_reduce_max or previous ring update

globalmax_recv:
  value_kind = replicated_vector
  owner_scope = task_pe
  producer = fragment_route_recv(GlobalMax)

globalmax_acc_out:
  value_kind = replicated_vector
  owner_scope = task_pe
  producer = global_max_tile(max_update_global_max)
  consumers = next ring edge update or max_with_floor_tile
  alias_policy = forbidden
```

V1 hard rules:

```text
globalmax_acc_in / globalmax_recv / globalmax_acc_out are separate placeholders.
alias_policy = forbidden.
globalmax_acc_out must have at least one consumer link.
globalmax_recv must be produced by the matching route_recv(GlobalMax).
```

Failing examples:

```text
globalmax_acc_out_has_no_consumer
globalmax_recv_without_route_recv_producer
log10max_ring_update_operand_alias_without_proof
```

Stable placeholder ids are mandatory.  V1 uses deterministic ids instead of
UUIDs:

```text
opnd:log10max:t0:pe0_1:ring_edge_017:globalmax_recv
opnd:log10max:t0:pe0_1:ring_edge_017:globalmax_acc_in
opnd:log10max:t0:pe0_1:ring_edge_017:globalmax_acc_out
```

The same stable suffix should flow into allocation and patch ids:

```text
alloc:opnd:log10max:t0:pe0_1:ring_edge_017:globalmax_recv
patch:log10max:ring_update:row_candidate_017
```

Producer placeholder tuple semantics:

```text
len(producer_placeholder_ids) == 0:
  allocate new value unless source_template_fixed evidence applies

len(producer_placeholder_ids) == 1:
  reuse the producer allocation as value identity

len(producer_placeholder_ids) > 1:
  blocked unless the placeholder is produced by an explicit merge/reduce op
```

The allocator must not silently pick one producer from a multi-producer tuple.

### 1.1 Route Operand Patch Continuity

`globalmax_recv` is not a synthetic value invented by the FMAX row.  It is the
destination of an existing `fragment_route_recv(GlobalMax)` action.

The patch chain must prove:

```text
route_recv(GlobalMax).dst
  == allocation(globalmax_recv)

FMAX.src_received
  == allocation(globalmax_recv)
```

If a PE forwards the updated max to another edge, the chain must also prove:

```text
FMAX.dst
  == allocation(globalmax_acc_out)

next route_push(GlobalMax).src
  == allocation(globalmax_acc_out)
```

For the final consumer path:

```text
FMAX.dst
  == allocation(globalmax_acc_out)

max_with_floor_tile.globalmax_src
  == allocation(globalmax_acc_out)
```

This rule prevents the false pass where route receive writes operand A but FMAX
reads operand B.  `pack/decode` can still pass in that failure mode, so the
continuity check must live at the placeholder/allocation/patch layer.

### 2. OperandAllocation

Add an allocation artifact that binds placeholders to DFU operand indices:

```python
@dataclass(frozen=True)
class OperandAllocation:
    schema_version: str
    allocation_id: str
    placeholder_id: str
    allocator: Literal[
        "dfu3500_task_resource_replay",
        "dfu3500_bline_linear_task_pe_allocator",
        "source_template_fixed",
    ]
    app_id: int
    task_id: int
    pe: str
    layout_profile_id: str
    operand_idx: int
    operand_ram: int
    operand_line: int
    allocation_scope: str
    alias_group: str | None
    allocation_status: Literal["allocated", "blocked"]
    evidence_refs: tuple[str, ...]
    blockers: tuple[str, ...]
```

The allocator may use `Dfu3500TaskResourceState` as implementation evidence,
but the resulting `OperandAllocation` is the artifact consumed by binary row
patching.

V1 allocator is intentionally narrow:

```text
allocator = dfu3500_bline_linear_task_pe_allocator
scope = task_pe
target operators = GEMM / GEMM+ReLU / log10max ring update
default value_kind = replicated_vector for GlobalMax
alias_policy = forbidden
```

V1 allocator does not perform:

```text
global liveness optimization
cross-task allocation
performance-optimal operand reuse
multi-backend abstraction
```

It may compare against `Dfu3500TaskResourceState`, but it must not expose
legacy replay as the trunk API.

### 2.0 Canonical DFU3500 Operand Index Layout

The allocator profile owns the canonical mapping between logical register
order and physical operand index.  No writer or checker should recompute this
with local ad hoc formulas.

```python
@dataclass(frozen=True)
class Dfu3500OperandIndexLayout:
    operands_ram_num: int
    operands_per_operand_ram: int

    def operand_idx_from_logical_reg(self, reg_idx: int) -> int:
        return (
            (reg_idx % self.operands_ram_num) * self.operands_per_operand_ram
            + reg_idx // self.operands_ram_num
        )

    def split_operand_idx(self, operand_idx: int) -> tuple[int, int]:
        operand_ram = operand_idx // self.operands_per_operand_ram
        operand_line = operand_idx % self.operands_per_operand_ram
        return (operand_ram, operand_line)
```

For V1 the profile uses the same constants as the DFU3500 vendor path:

```text
operands_ram_num = OPERANDS_RAM_NUM
operands_per_operand_ram = OPERANDS_PER_OPERAND_RAM
```

Every `OperandAllocation` must carry:

```text
operand_idx
operand_ram
operand_line
layout_profile_id
```

and checks must verify the three fields agree with the layout profile.

### 2.0.1 V1 Allocation Algorithm

V1 deliberately avoids full liveness.  Inside one `(app_id, task_id, pe)` scope
it uses monotonic no-reuse allocation with a capacity guard:

```python
for placeholder in deterministic_order(placeholders):
    if placeholder.source_template_fixed_allowed:
        allocate_from_source_template_fixed_evidence()
    elif placeholder.producer_placeholder_id:
        reuse_value_identity_allocation()
    else:
        allocate_next_free_operand_idx(task_id, pe)

if used_operands > capacity:
    allocation_status = "blocked"
    blocker = "operand_capacity_exceeded"
```

Deterministic order:

```text
app_id
task_id
pe
phase_order
ring_edge_order
operand_role_order
```

Role order for log10max ring update:

```text
globalmax_acc_in
globalmax_recv
globalmax_acc_out
```

The allocator does not reuse storage for unrelated unknown-live values in V1.
This is intentionally conservative and progress-oriented.

Important distinction:

```text
value identity reuse:
  allowed/required when a consumer reads a producer's output allocation

instruction operand aliasing:
  forbidden for FMAX src/dst in V1
```

Examples:

```text
globalmax_acc_in may reuse previous globalmax_acc_out allocation
globalmax_recv must reuse matching route_recv output allocation
globalmax_acc_out gets a new allocation because FMAX alias_policy=forbidden
```

### 2.1 Task Parallelism Contract

DFU tasks can execute independently.  The allocator must therefore treat
`task_id` as part of the physical allocation namespace.

V1 allocation scope:

```text
allocation_scope = (app_id, task_id, pe)
owner_scope = task_pe
```

Allowed:

```text
task 0 / PE(0,0) operand 128
task 1 / PE(0,0) operand 128
```

These do not alias because they live in different task contexts.

Forbidden:

```text
producer in task 0
consumer in task 1
same app
no explicit route/materialization/app barrier
```

Cross-task communication must not be modeled as shared operand allocation.
If values move between tasks, the movement must be represented by existing
B-line communication/materialization primitives and patched in the receiver's
allocation scope.

Receiver-owned patching rule:

```text
route_recv / COPY-like destination operand
  is allocated in receiver (app_id, task_id, pe)
  not sender (app_id, task_id, pe)
```

This mirrors the vendor `fill_copy_inst` rule: COPY destination operands are
looked up through the child/receiver `Task_Resource`.

If a value crosses an app boundary, the allocator must fail closed unless the
producer app materializes the value and the consumer app imports it through an
explicit load/materialization action.  App boundaries may serve as scheduling
barriers; task boundaries inside one app do not.

### 2.2 Source Template Fixed Allocations

`source_template_fixed` exists for rows whose operand fields are already proven
by source template bytes, especially current GEMM progress rows.

It is allowed only when all of the following are present:

```text
template_row_sha256
source evidence id
field provenance for src_operands_idx / dst_operands_idx
operand role matches placeholder role
decode confirms the same operand value
```

Missing any item blocks the row:

```text
source_template_fixed_without_evidence
```

Final row operand fields are allowed only if they are produced by:

```text
InstOperandPatch with dfu3500_bline_linear_task_pe_allocator allocation
or
InstOperandPatch with source_template_fixed allocation and evidence
```

The legacy comparison adapter may report mismatches, but it must not bypass the
allocation artifact.

### 2.3 Constants and Immediate Values

Not every constant is an operand.

V1 classification:

```text
constant_storage = operand_ram | immediate | source_template_fixed
```

Rules:

```text
constant_storage = operand_ram
  -> OperandPlaceholder(value_kind="constant")

constant_storage = immediate
  -> ImmediatePlaceholder, deferred unless required by the V1 row

constant_storage = source_template_fixed
  -> TemplateImmediateBinding or source_template_fixed evidence
```

For ReLU zero:

```text
if HMAX/FMAX template expects zero as source operand:
  OperandPlaceholder(value_kind="constant")
else if the template uses an immediate field:
  ImmediatePlaceholder / TemplateImmediateBinding
```

For log10max scalar constants:

```text
immediate fields should not be disguised as operand placeholders
operand-RAM materialized scalars must go through OperandPlaceholder
```

### 3. InstOperandPatch

Add a patch artifact that maps allocations into row fields:

```python
@dataclass(frozen=True)
class InstOperandPatch:
    schema_version: str
    patch_id: str
    row_candidate_id: str
    template_expansion_id: str
    source_fiber_op_id: str
    source_ring_edge_id: str | None = None
    source_stream_action_id: str | None = None
    opcode: str
    src_placeholders: tuple[str, ...]
    dst_placeholders: tuple[str, ...]
    allocation_ids: tuple[str, ...]
    operand_field_usage: Mapping[str, Literal[
        "used",
        "unused_zero_fill",
        "immediate",
        "template_fixed",
    ]]
    src_operands_idx: tuple[int, int, int]
    dst_operands_idx: tuple[int, int, int]
    patch_status: Literal["patched", "blocked"]
    decode_roundtrip_status: Literal[
        "not_run",
        "candidate_decode_roundtrip",
        "component_decode_roundtrip",
    ]
    blockers: tuple[str, ...]
```

The byte writer may only consume `InstOperandPatch` when:

```text
patch_status = patched
all referenced OperandAllocation records are allocated
alias_policy violations = none
decode_roundtrip_status is at least candidate_decode_roundtrip
```

For log10max ring update V1:

```text
src0 = allocation(globalmax_acc_in)
src1 = allocation(globalmax_recv)
dst0 = allocation(globalmax_acc_out)
src2 = 0
dst1 = 0
dst2 = 0
```

For that row shape:

```text
src0 = used
src1 = used
src2 = unused_zero_fill
dst0 = used
dst1 = unused_zero_fill
dst2 = unused_zero_fill
```

This mask is required because operand index `0` may be a real allocated
operand elsewhere.  Zero-filled unused fields are legal only when the opcode
row shape marks them unused.

### 4. Row Emission Rule

Final inst_t emission must follow:

```text
TemplateOp/BinaryLayout row candidate
  -> OperandPlaceholder records
  -> OperandAllocation records
  -> InstOperandPatch
  -> LegacyInst / native row pack
  -> decode roundtrip
  -> component insertion
```

Disallowed:

```text
RingEdgeRecord
  -> hardcoded src_operands_idx/dst_operands_idx
  -> final component row
```

Also disallowed:

```text
Template candidate
  -> final row bytes
```

unless an `InstOperandPatch` exists.

The contract applies to every operand-bearing `inst_t` row:

```text
route_push / route_recv / COPY-like rows
FMAX / HMAX rows
ReLU rows
GEMM native rows when not source-template-fixed
future elementwise rows
```

No row family is allowed to bypass the patch contract by calling itself
"routing" or "serializer-owned".

Hardcoded skeleton rows are always diagnostic-only:

```text
src_operands_idx = [0, 128, 0]
dst_operands_idx = [256, 0, 0]
row_bytes_claim = candidate_only
final_row_bytes_claim = false
runtime_ready = false
uploadable = false
```

They can prove opcode shape and pack/decode mechanics.  They cannot prove
allocation, lifetime, route receive binding, or collision freedom.

### 5. Legacy Evidence Adapter

Add a narrow adapter that can compare B-line allocation artifacts against
legacy `Task_Resource` behavior without making legacy replay the source of
truth.

```python
@dataclass(frozen=True)
class LegacyOperandAllocationEvidence:
    schema_version: str
    placeholder_id: str
    task_id: int
    pe: str
    tag: str
    legacy_source: Literal[
        "LegacyCsvEncoder",
        "Dfu3500TaskResourceState",
        "program_bin_copy_receiver_patch",
    ]
    legacy_operand_idx: int
    bline_operand_idx: int | None
    comparison_status: Literal["match", "mismatch", "not_comparable"]
    evidence_refs: tuple[str, ...]
```

For V1, this is a report-only guardrail.  It lets us answer:

```text
Does this B-line placeholder/allocation behave like the vendor path for the
same role and scope?
```

It must not be used to bypass `OperandAllocation`.

## Invariants

1. FiberOp remains atomic.  Operand allocation is not fiber semantics.
2. TemplateOp/BinaryLayout may name logical operand roles but must not silently
   assign final operand indices.
3. Every final `src_operands_idx` / `dst_operands_idx` must be backed by
   `InstOperandPatch`.
4. Every patch must point back to `OperandAllocation`.
5. Every allocation must point back to `OperandPlaceholder`.
6. `Task_Resource` replay is an allocator implementation/evidence source, not
   the semantic source of truth.
7. Candidate bytes with hardcoded operands are diagnostic only unless their
   operands are patched from allocation records.
8. `runtime_ready` cannot pass with any unallocated operand placeholder.
9. Ring update `globalmax_acc_out` must be the value consumed by the next ring
   edge or postprocess consumer; it cannot be an untracked scratch temporary.
10. A fixed operand index in a template candidate is evidence only unless it is
    reproduced by an `OperandAllocation` and consumed through an
    `InstOperandPatch`.
11. COPY/route receiver operands are receiver-owned.  Sender-side operand tags
    may help compute lane deltas, but receiver destination fields must be bound
    in the receiver task/PE scope.
12. The serializer is not an allocator.  It may only pack rows whose operand
    fields have already been patched by an explicit artifact.
13. Route continuity is part of operand patching: route receive destination,
    FMAX source, FMAX destination, next route push source, and postprocess
    source must agree through shared allocation records.
14. `source_template_fixed` is not a free pass.  It requires template hash,
    source evidence, field provenance, role match, and decode proof.
15. Constants must declare storage form.  Operand-RAM constants use
    `OperandPlaceholder`; immediate constants do not.
16. V1 allocation is monotonic no-reuse within one task_pe scope except for
    explicit value identity reuse across producer/consumer placeholders.
17. Instruction src/dst aliasing is forbidden for V1 FMAX/HMAX-style rows even
    when value identity reuse is required between different rows.

## Alternatives Considered

### Alternative A: Continue fixed operand indices for V1

Rejected.

Fixed values such as `[0, 128, 256]` prove only local pack/decode mechanics.
They do not prove lifetime, collision freedom, or route recv binding.

### Alternative B: Use legacy Task_Resource replay directly as B-line API

Rejected as trunk design.

`Dfu3500TaskResourceState` is valuable and should be reused, but B-line needs a
stable target-binding artifact.  Directly exposing legacy replay as the API
would make compatibility behavior the new semantic authority.

### Alternative C: Delay operand allocation until serializer

Rejected.

The serializer lacks enough semantic context to know producer/consumer lifetime
and ring ordering.  It should pack already-decided rows, not invent operands.

### Alternative D: Build full liveness/register allocation now

Deferred.

Eventually useful, but too broad for delivery.  The V1 allocator can be a
deterministic per-task-per-PE allocator for the three required operators.

## Migration / Implementation Plan

### Phase 0: Stop-bleed gate

Immediately enforce:

```text
ring update FMAX candidate bytes are diagnostic only
ring update component placement candidates are placement-only
preintegration gate remains blocked on placeholder/allocation/patch/row-byte status
component integration cannot consume hardcoded operand indices
```

Current log10max candidate classification:

```text
Phase 2/3 TemplateOp/BinaryLayout candidates:
  valid report-only lowering evidence

Phase 4 FMAX inst_t pack/decode candidates:
  valid row-shape / opcode / byte-packer evidence
  invalid as final component rows until operand patches exist

Phase 5 component placement candidates:
  valid offset/PC placement evidence
  invalid as exeBlock/CBUF integration until operand patches exist
```

Gate blocker should be refined from:

```text
log10max_ring_update_component_integration_missing
```

to:

```text
log10max_ring_update_operand_placeholders_missing
```

whenever the candidate row has TemplateOp/BinaryLayout evidence but no
placeholder artifact.

### Phase 1: Report-only placeholder extraction

For each ring update row candidate, emit placeholders:

```text
globalmax_acc_in
globalmax_recv
globalmax_acc_out
```

Expected blocker:

```text
log10max_ring_update_operand_allocation_missing
```

Minimum fields:

```text
placeholder_id
source_ring_edge_id
source_fiber_op_id
source_stream_action_id
template_op_id
binary_row_candidate_id
app_id
task_id
pe
value_kind
dtype
producer/consumer ids
owner_scope = task_pe
alias_policy = forbidden
```

Phase 1 exits only when:

```text
ring_update_row_count = 30
placeholder_count = 90
each update row has exactly:
  src_current placeholder
  src_received placeholder
  dst_updated placeholder
each placeholder belongs to exactly one task_pe owner scope
globalmax_recv has route_recv producer
globalmax_acc_out has next-update or postprocess consumer
no placeholder is directly backed by hardcoded operand indices
```

For the 4x4 representative ring:

```text
row_reduce:      12 update rows -> 36 placeholders
col_reduce:       3 update rows ->  9 placeholders
col_broadcast:    3 update rows ->  9 placeholders
row_broadcast:   12 update rows -> 36 placeholders
```

### Phase 2: Deterministic allocation candidate

Implement a narrow allocator:

```text
scope = task_pe
allocator = dfu3500_bline_linear_task_pe_allocator
value_kind = replicated_vector
alias_policy = forbidden
```

It may seed from known local reduce / route recv / postprocess operands through
producer placeholder links, but it must output explicit `OperandAllocation`
records.

V1 decision:

```text
Use a deterministic per-task-per-PE allocator for B-line artifacts.
Use monotonic no-reuse for unrelated unknown-live placeholders.
Use capacity guard instead of full liveness.
Use Dfu3500TaskResourceState as comparison/evidence.
Do not directly expose TaskResource replay as the B-line allocator API.
```

### Phase 3: InstOperandPatch candidate

Patch FMAX candidates from allocation records:

```text
src0 = allocation(globalmax_acc_in)
src1 = allocation(globalmax_recv)
dst0 = allocation(globalmax_acc_out)
```

Then run pack/decode roundtrip.

Patch validation must prove two things:

```text
byte fields roundtrip:
  patch -> row bytes -> decoded opcode/src/dst fields

provenance roundtrip:
  patch_id / allocation_ids / source_fiber_op_id /
  source_ring_edge_id / template_expansion_id are retained in writer report
```

Expected blocker transition:

```text
log10max_ring_update_operand_placeholders_missing
  -> log10max_ring_update_operand_allocation_missing
  -> log10max_ring_update_inst_operand_patch_missing
  -> log10max_ring_update_row_bytes_missing
  -> log10max_ring_update_component_integration_missing
```

### Phase 4: Component integration

Only after patches exist:

```text
InstOperandPatch
  -> InstBinRow(legacy_inst=patched FMAX)
  -> program_serializer._serialize_insts_component()
  -> CBUF inst section
```

### Phase 5: Package gate

Clear the blocker only when:

```text
all placeholders exist
all placeholders allocated
all patches decoded
all rows inserted at expected component offsets
exeBlock CAL stage owns the PCs
manifest hashes are fresh
consumer dependencies still pass
```

## Validation Plan

Add focused checks:

```bash
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_operand_placeholders.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_operand_allocation.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_inst_operand_patches.py
```

Minimum assertions:

```text
no final inst row has nonzero operand indices without InstOperandPatch
no serializer/inst writer performs allocation
no skeleton operand row enters final component integration
no InstOperandPatch references an unallocated placeholder
no source_template_fixed allocation lacks template hash/evidence/decode proof
no allocation record omits app_id/task_id/pe scope
no allocation record omits layout_profile_id
operand_idx / operand_ram / operand_line match Dfu3500OperandIndexLayout
multi-producer placeholder is blocked unless produced by explicit merge/reduce op
unused operand fields are zero-filled only when operand_field_usage marks them unused
no two live placeholders in one task_pe scope alias unless alias policy allows it
same operand_idx may repeat across different task_pe scopes
cross-task producer/consumer links require route/materialization/app-boundary proof
route_recv/COPY destination operands use receiver task_pe allocation scope
route_recv(GlobalMax).dst == allocation(globalmax_recv)
FMAX.src_received == allocation(globalmax_recv)
FMAX.dst == allocation(globalmax_acc_out)
next route_push src or max_with_floor source == allocation(globalmax_acc_out)
ring update uses non-in-place allocation unless aliasing is proven
globalmax_recv is produced by matching route_recv
globalmax_acc_out feeds next update or max_with_floor consumer
decode src/dst operands match patch records
writer report maps row offset / row id back to InstOperandPatch
```

Update `check_bline_runtime_ready_preintegration.py` so log10max cannot become
ready while:

```text
log10max_ring_update_operand_placeholders_missing
log10max_ring_update_operand_allocation_missing
log10max_ring_update_inst_operand_patch_missing
```

is present.

## Implementation Checkpoint

Current safe-scope implementation status:

```text
Phase 1:
  log10max ring update placeholders exist.
  30 FMAX update row candidates produce 90 OperandPlaceholder records.
  Phase distribution is 36 / 9 / 9 / 36.

Phase 2:
  dfu3500_bline_linear_task_pe_allocator produces 90 OperandAllocation records.
  Scope is app_id / task_id / pe.
  V1 uses monotonic no-reuse plus single-producer value identity reuse.

Phase 3:
  30 FMAX InstOperandPatch records exist.
  src0 = globalmax_acc_in allocation.
  src1 = globalmax_recv allocation.
  dst0 = globalmax_acc_out allocation.
  src2 / dst1 / dst2 are explicit unused_zero_fill fields.
  Candidate pack/decode roundtrip passes.

Phase 3b:
  60 GlobalMax route operand patch candidates exist.
  30 route_recv rows bind receiver-owned globalmax_recv allocations.
  route_push rows that source a previous globalmax_acc_out bind that allocation.
  route_push rows that source local_reduce_max remain blocked until the
  local_reduce output participates in the same allocation contract.
```

The current remaining report-level blockers are:

```text
log10max_ring_route_push_local_reduce_operand_allocation_missing
log10max_ring_update_component_integration_missing
```

This is still before final component integration.  The route patch report does
not emit COPY/LDN row bytes, does not rebase subtask/exeBlock layout, and does
not change `runtime_ready`.

## Risks and Mitigations

### Risk: Allocator becomes another hidden backend

Mitigation:

Keep allocator output as explicit artifacts.  The byte writer consumes
allocations and patches; it does not allocate.

### Risk: V1 allocator is too simple

Mitigation:

Scope it to the first three operators and use fail-closed collision checks.
General liveness can come later.

### Risk: Legacy Task_Resource and B-line allocation diverge

Mitigation:

Use `Dfu3500TaskResourceState` as comparison/evidence.  Do not consume it as
the only artifact.

### Risk: Ring update ordering is correct but operand lifetimes are wrong

Mitigation:

Require `globalmax_acc_out` consumer links in placeholder records.  The
allocation check must verify producer/consumer chain continuity.

### Risk: Task-parallel allocation accidentally becomes shared state

Mitigation:

Make `(app_id, task_id, pe)` part of every allocation key.  Reusing operand
index `128` in two different tasks is legal; using it as an implicit
cross-task communication channel is illegal.  Cross-task data movement must be
represented by route/materialization/app-boundary records and patched in the
receiver scope.

## Expected Effect

After this RFC is implemented:

```text
binary rows can be written progressively
operand indices are no longer hidden constants
ring update FMAX rows can safely move from diagnostic bytes to component rows
ReLU and later elementwise ops can share the same operand patch path
runtime_ready remains honest
```

This is not a numerical correctness proof and not a full allocator.  It is the
minimum missing contract that makes B-line binary lowering structurally sound.

## Open Questions

Recommended answers for V1:

| Question | V1 answer |
| --- | --- |
| Reuse `Dfu3500TaskResourceState` directly? | No. Implement `dfu3500_bline_linear_task_pe_allocator`; use `Dfu3500TaskResourceState` only as comparison/evidence. |
| How to model constants? | Operand-like constants may use `OperandPlaceholder(value_kind="constant")` only when they occupy operand RAM. Immediate fields should use a separate `ImmediatePlaceholder` later. |
| What aliasing is allowed? | None. `alias_policy = forbidden` for V1 ring update, ReLU, and elementwise patch rows. |
| What enters customer-facing metadata? | Allocator id, scope, placeholder count, allocation count, patch count, collision-check status, decode status. Not full internal lifetime graph. |
| Can hardcoded skeleton rows enter final payloads? | No. They remain diagnostic-only until replaced by `InstOperandPatch` output. |
| Does GEMM prove B-line allocation exists? | No. Current GEMM preserves operand indices from exact A-line/template span bytes. Native B-line GEMM rows must use this contract when they stop consuming already-allocated legacy rows. |
| How does task parallelism affect allocation? | Allocation scope is `(app_id, task_id, pe)`. Cross-task values require explicit communication/materialization; they cannot share operand state. |
| How are `source_template_fixed` rows allowed? | Only through `InstOperandPatch` backed by template hash, source evidence, field provenance, role match, and decode proof. |
| Are ids allowed to be random? | No. `placeholder_id`, `allocation_id`, and `patch_id` must be deterministic and diff-stable. |
| What is Phase 1 first target? | 30 log10max ring update rows, 90 placeholders, phase distribution 36/9/9/36, producer/consumer continuity closed. |
| How is route continuity enforced? | `route_recv.dst`, `FMAX.src_received`, `FMAX.dst`, and next `route_push.src` or `max_with_floor` source must share allocation records. |
| How is operand index `0` interpreted? | Only via `operand_field_usage`. It may be a real operand when a field is used, or zero-fill when the field is explicitly unused. |
| Do route/COPY rows need patches? | Yes. Every operand-bearing `inst_t` row, including route push/recv and COPY-like rows, must have `InstOperandPatch` or `source_template_fixed` evidence. |

## Recommended Decision

Accept this RFC as a hard blocker before final component integration.

This RFC is a stop-bleed contract, not permission to build a generic allocator.

Immediate action:

```text
Do not consume hardcoded ring update FMAX operand indices in runtime_ready.
Keep skeleton rows diagnostic-only.
Add OperandPlaceholder / OperandAllocation / InstOperandPatch report layers.
Use monotonic no-reuse task_pe allocation with capacity guard.
Require route operand patch continuity.
Allow GEMM legacy/template rows only through source_template_fixed evidence.
Reject operand-bearing route/COPY/FMAX/HMAX/ReLU/native rows without patch evidence.
Then resume log10max ring update component integration.
```

This is the smallest correction that preserves the B-line architecture:

```text
FiberOp is semantic.
TemplateOp names target intent.
OperandAllocation binds physical operand resources.
InstOperandPatch writes operand fields.
Serializer packs already-decided rows.
```
