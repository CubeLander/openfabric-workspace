# RFC: B-line inst_t Row Bytes Field Provenance

## Status

Draft for review.

Recommended decision: accept as the hard design contract before B-line emits
new functional `inst_t` row bytes for log10max route/local-reduce/max-with-floor
or any native ReLU/native GEMM rows.

## Summary

B-line cannot treat raw `inst_t` bytes as a simple serializer problem.  In the
original A-line / vendor flow, final instruction row fields are determined by a
pipeline:

```text
CSV row
  -> Csv_Operate opcode / latency / unit / template-local operands
  -> Inst_Block stage split
  -> graph / node / PE placement
  -> Task_Resource operand allocation
  -> COPY/COPYT receiver endpoint patch
  -> exeBlock index and stage PC generation
  -> task_print full inst_t write and RTL projection
```

The final row bytes are therefore the result of several binding passes, not one
writer.  B-line must model this explicitly:

```text
FiberOp / TemplateExpansion
  -> InstFieldIntent
  -> OperandPlaceholder / OperandAllocation / InstOperandPatch
  -> RouteEndpointPatch
  -> InstructionLayoutPlan
  -> ExeBlockWriterPlan
  -> InstRowByteCandidateRecord
  -> component writer
```

The byte writer may pack rows, but it must not allocate operands, invent route
destinations, decide block indices, or finalize stage PCs.

## Current State

### Existing evidence

The original implementation is under:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper
```

The important source facts are:

1. `csv_oper.cpp` parses CSV rows into `inst_t` skeleton fields.
2. `inst_blk_gen.cpp` splits instructions into fixed stages:
   `LD -> CAL -> FLOW -> ST`.
3. `inst_map_common.cpp` and `inst_blk_map.cpp` allocate PE-local operands and
   patch COPY/COPYT destination fields.
4. `exe_block_gen.cpp` assigns PE-local `exe_block_idx`, predecessor/successor
   metadata, and stage PCs.
5. `task_print.cpp` writes full simulator `inst_t` rows and also projects them
   into narrower RTL/debug structs.

B-line already has partial receivers for these concepts:

```text
compiler/gpdpu_compiler/decoder/profiles/dfu3500.py
compiler/gpdpu_compiler/core/program_legacy_inst.py
compiler/gpdpu_compiler/core/dfu3500/task_resource_replay.py
compiler/gpdpu_compiler/core/program_bin.py
compiler/gpdpu_compiler/core/stream_compiler/log10max_ring_update_operands.py
compiler/gpdpu_compiler/core/stream_compiler/inst_writers.py
compiler/gpdpu_compiler/core/stream_compiler/micc_component_writers.py
```

### Current gap

B-line can now describe log10max ring operand continuity at report level:

```text
local_reduce_max_out
  -> first route_push.src
  -> route_recv.dst
  -> FMAX.src_received
  -> FMAX.dst
  -> next route_push.src
  -> max_with_floor.globalmax_src
```

But it must still emit real row bytes for:

```text
route COPY/COPYT/LDN-like rows
local_reduce_max rows
max_with_floor rows
component placement / exeBlock integration
```

Those bytes are blocked because several fields still need source-backed owners.

## Problem

The phrase "write raw bytes" hides multiple field authorities.

If B-line lets an `inst_t` writer fill missing fields directly, the writer will
become a hidden backend.  The most dangerous examples are:

```text
src_operands_idx / dst_operands_idx:
  must come from allocation artifacts, not hardcoded template numbers.

dst_pes_pos / dst_blocks_idx:
  for route/COPY rows, must come from receiver endpoint placement.

flow_ack:
  for COPY RTL projection, acts as base_addr_idx; cannot be a spare flag.

block_idx / stages_start_pc:
  are late PE-local layout results, not FiberOp attributes.

end_inst:
  is stage / valid-instruction boundary policy, not TaskResource authority.
```

The serializer must be boring.  It packs already-decided fields and records
decode/provenance roundtrip.  It does not decide fields.

## Goals / Non-goals

Goals:

- Record how the original implementation determines each important `inst_t`
  field.
- Define the B-line artifact that must own each field before byte emission.
- Keep B-line faithful to flat FiberOp semantics: template/physical lowering may
  expand a FiberOp, but fiber does not contain vendor staging.
- Allow fast progress using A-line/vendor evidence without making A-line the new
  semantic authority.
- Define fail-closed gates for route/local_reduce/max_with_floor raw row bytes.

Non-goals:

- Implement a generic optimizing register allocator.
- Claim numerical correctness or SimICT execution.
- Introduce new communication IR.
- Rebuild `common_oper` inside B-line.
- Emit final CBUF/MICC bytes in this RFC.

## A-line Field Provenance

### CSV-owned skeleton fields

`Csv_Operate::process()` sets the first version of these fields from CSV and
opcode tables:

```text
opCode
unit_inst_type
latency
imms[0]
iter_exe_cond
src_operands_idx[0]
src_operands_idx[1]
dst_operands_idx[0]
dst_pes_pos[0].x
dst_pes_pos[0].y = 0
dst_pes_pos[0].z = 0
extra_fields[0..2]
```

Source evidence:

```text
common_oper/csv_oper.cpp:
  constructOneCsvItem()
  process()
  registerOp()
```

Important detail: CSV operand fields are template-local register tags / indices
before PE-local resource binding.  They are not always final hardware operand
indices.

### Pseudo-op expansion fields

`Csv_Operate::appendExpandedPseudoInsts()` expands pseudo/template ops such as
`COPYT` / tensor lane ops into multiple rows.  Follow-lane rows may adjust:

```text
opCode
latency
unit_inst_type
imms[0]
dst_pes_pos[0].x
operand lane offsets
```

Source evidence:

```text
common_oper/csv_oper.cpp:
  expandedPseudoName()
  pseudoDstPeX()
  appendExpandedPseudoInsts()
```

Compiler implication: B-line may use a template expansion record, but the
expansion must remain after FiberOp and preserve row-to-FiberOp provenance.

### Stage split

`Inst_Block::process()` consumes the CSV-produced instruction list in strict
stage order:

```text
LD stage
CAL stage
FLOW stage
ST stage
```

It fails if remaining instructions do not match this ordering.

Source evidence:

```text
common_oper/inst_blk_gen.cpp:
  Inst_Block::process()
```

Compiler implication: B-line row bytes need an `InstructionLayoutPlan` with
stage classification and local order.  Stage cannot be guessed from FiberOp
order alone.

### Operand allocation

The original mapper assigns final PE-local operand indices after node placement.
There are two observed models:

1. Common path in `inst_map_common.cpp`:

```text
fillRegIdx(insts, start_reg_idx):
  inst.src_operands_idx[j] += node.start_reg_idx
  inst.dst_operands_idx[j] += node.start_reg_idx
```

2. Full `Task_Resource` path in `inst_blk_map.cpp`, modeled in B-line as
   `Dfu3500TaskResourceState`:

```text
tag -> Task_Resource.get_reg_idx(tag)
COPY destination -> receiver Task_Resource.retrieve_reg_idx(tag)
COPYT follow lanes -> base + lane * OPERANDS_PER_OPERAND_RAM
```

Source evidence:

```text
common_oper/inst_map_common.cpp:
  setNodes()
  fillRegIdx()
  fillCpInst()

compiler/gpdpu_compiler/core/dfu3500/task_resource_replay.py:
  Dfu3500TaskResourceState
```

Compiler implication: B-line native rows must go through:

```text
OperandPlaceholder
  -> OperandAllocation
  -> InstOperandPatch
```

`source_template_fixed` is allowed only when source row bytes, template hash,
role match, and decode proof are present.

### Route / COPY destination patch

For inter-node COPY instructions, the original implementation patches
destination fields from the child/receiver node:

```text
dst_blocks_idx[0] = child.block_idx
dst_pes_pos[0].x = child.x
dst_pes_pos[0].y = child.y
dst_operands_idx[0] = child Task_Resource / start_reg_idx + dst tag
flow_ack = child edge index in parent child list
```

For local copy, `LCOPY` / `LCOPYT` is rewritten to `COPY` with self destination:

```text
opCode = OP_COPY
dst_blocks_idx[0] = self.block_idx
dst_pes_pos[0] = self PE
```

Source evidence:

```text
common_oper/inst_map_common.cpp:
  setACKInst()
  fillCpInst()
  fillLocalCpInst()

common_oper/inst_blk_map.cpp:
  fill_copy_inst()
```

Compiler implication: route action lowering must produce a `RouteEndpointPatch`
before bytes:

```text
sender executor PE/block
receiver logical owner PE/block
receiver-owned destination operand
flow_ack / child edge slot
```

Numeric operand equality is not enough; the allocation scope must match
`(app_id, task_id, receiver_pe)` for receive destinations.

### ExeBlock index and stage PC

`exe_block_gen.cpp` assigns PE-local block indices and predecessor/successor
metadata.  `organize_block_conf()` computes stage counts and stage start PCs
from valid instruction counts:

```text
stages_start_pc[LD]   = inst_start_pos
stages_start_pc[CAL]  = after LD rows
stages_start_pc[FLOW] = after CAL rows
stages_start_pc[ST]   = after FLOW rows
stages_start_pc[END]  = after ST rows
```

`task_print.cpp::print_block_conf()` then re-bases stage PCs using a static
per-PE running instruction counter:

```text
stages_start_pc[pc] = pc_temp[pc] + pe_inst_count[pe_idx] - pc_temp[0]
pe_inst_count[pe_idx] = end_pc
```

Source evidence:

```text
common_oper/exe_block_gen.cpp:
  exe_block_gen()
  organize_block_conf()

common_oper/task_print.cpp:
  print_block_conf()
```

Compiler implication: `block_idx` and `stages_start_pc` belong to PE-local
block/layout planning.  They cannot be finalized in op spec, FiberOp, or
TemplateOp.

### Full simulator row write and RTL projection

`task_print.cpp::print_inst_stage()` copies full `inst_t` records to the
simulator instruction stream and stamps:

```text
block_idx = exeBlock_conf_info.block_idx
```

`write_rtl_inst()` then maps full `inst_t` into opcode-family-specific RTL
records.  Examples:

```text
LD/ST-like:
  base_addr_idx = iter_exe_cond

COPY:
  base_addr_idx = flow_ack
  pos_x / pos_y = dst_pes_pos[0]

FLOG2 / FEXP2 family:
  project to FRCP-family RTL opcode with imm selector bits

IMM/FIMM:
  imm split into imm_1 / imm_2
```

Source evidence:

```text
common_oper/task_print.cpp:
  print_inst_stage()
  write_rtl_inst()
```

Compiler implication: simulator `inst_t` row bytes and RTL/debug projection are
different views.  B-line runtime payload currently needs simulator-style
`inst_t` rows; any RTL/debug projection must be generated from the same
field-bound source, not from a separate semantic path.

## Field Ownership Table

| Field | A-line source of truth | B-line required owner before bytes |
| --- | --- | --- |
| `opCode` | `Csv_Operate::registerOp` + CSV op name; pseudo expansion may rewrite | `TemplateExpansion` / opcode evidence |
| `unit_inst_type` | opcode table in `Csv_Operate` | `TemplateExpansion` / opcode evidence |
| `latency` | opcode latency table in `Csv_Operate` | `TemplateExpansion` / opcode evidence |
| `imms[0..2]` | CSV immediate plus pseudo expansion / op-family rules | `ImmediateBinding` or `source_template_fixed` |
| `src_operands_idx` | CSV tags, then `fillRegIdx` / `Task_Resource` | `InstOperandPatch` from `OperandAllocation` |
| `dst_operands_idx` | CSV tags, then resource allocation; COPY dst uses receiver | `InstOperandPatch`; route dst must be receiver-owned |
| `dst_pes_pos` | CSV placeholder, then COPY/local-copy receiver patch | `RouteEndpointPatch` or template-fixed evidence |
| `dst_blocks_idx` | COPY child block or local self block | `RouteEndpointPatch` / `ExeBlockWriterPlan` |
| `forwarding_bits` | optional CSV neighbor analysis in `set_forwarding_bypass` | `ForwardingBypassPlan` or zero-with-evidence |
| `bypass_bits` | optional CSV neighbor analysis | `ForwardingBypassPlan` or zero-with-evidence |
| `iter_exe_cond` | CSV field; RTL base selector for LD/ST/CAL/IMM | `BaseAddressBindingPlan` / immediate binding |
| `src_operands_fetched` | zero/default or opcode-specific writer policy | `OperandFetchPolicy` |
| `dst_operands_fetched` | zero/default or opcode-specific writer policy | `OperandFetchPolicy` |
| `block_idx` | `exe_block_gen` PE-local block index, stamped at print | `ExeBlockWriterPlan` |
| `flow_ack` | COPY child edge index; RTL COPY base selector | `RouteEndpointPatch` / child edge slot plan |
| `end_inst` | stage boundary / last valid instruction policy | `InstructionBoundaryPlan` |
| `extra_fields` | CSV extra fields; opcode-family-specific meaning | `ExtraFieldBinding` by opcode family |
| row byte offset | PE-local stream, padded and PE-major merged | `ComponentPlacementPlan` |

For execution planning, each field also receives a V1 gate classification:

| Field class | V1 row-body candidate status | Blocks component integration? |
| --- | --- | --- |
| Opcode / unit / latency | Required before packing | Yes |
| Used operand fields | Required via `InstOperandPatch` before packing | Yes |
| Unused operand fields | May be `zero_with_evidence` | Yes if unknown |
| Immediate / constant fields | Required when opcode consumes them | Yes if used or unknown |
| Route destination PE/block | Not needed for non-route FMAX row body | Yes for route rows |
| `block_idx` / component offset | May remain pending for unplaced candidates | Yes |
| `end_inst` | May remain pending for unplaced candidates | Yes |
| forwarding / bypass / fetch flags | May be `zero_with_evidence` | Yes if unknown |

## Proposed Design

### 1. Add `InstFieldBindingRecord`

B-line row byte materialization should consume one typed record per future row:

```python
@dataclass(frozen=True)
class InstFieldOwnerBinding:
    field_path: str
    owner_kind: Literal[
        "opcode_binding",
        "operand_patch",
        "route_endpoint_patch",
        "immediate_binding",
        "instruction_layout",
        "exe_block_writer_plan",
        "component_placement_plan",
        "boundary_policy",
        "fetch_policy",
        "forwarding_bypass_plan",
        "extra_field_binding",
        "zero_with_evidence",
        "source_template_fixed",
    ]
    owner_id: str
    binding_status: Literal["bound", "blocked", "zero_with_evidence"]
    decoded_value: object | None
    blockers: tuple[str, ...]


@dataclass(frozen=True)
class InstFieldBindingRecord:
    row_id: str
    source_fiber_op_id: str
    template_expansion_id: str
    opcode_binding_id: str
    operand_patch_id: str | None
    route_endpoint_patch_id: str | None
    immediate_binding_id: str | None
    instruction_layout_plan_id: str | None
    exe_block_writer_plan_id: str | None
    component_placement_plan_id: str | None
    boundary_policy_id: str
    field_bindings: tuple[InstFieldOwnerBinding, ...]
    field_status: Literal["bound", "blocked"]
    missing_fields: tuple[str, ...]
```

This is not a new semantic layer.  It is a join record proving that all field
owners have produced their artifacts.

The field-level map is mandatory.  A coarse `missing_fields=("extra_fields",)`
is not enough for debug or gate decisions; each concrete field path must name
its owner or blocker.

### 2. Zero is also a field binding

The writer must not silently zero-fill fields.  A zero is legal only when a
field binding says why:

```json
{
  "field_path": "src_operands_idx[2]",
  "owner_kind": "zero_with_evidence",
  "owner_id": "fmax_operand_field_usage_v1",
  "binding_status": "zero_with_evidence",
  "decoded_value": 0
}
```

This distinguishes:

```text
0 as unused field
0 as a real operand index
0 as unknown / blocked
```

### 3. Split byte materialization into base row plus patches

The row mode is not exclusive.  Route rows often use a source skeleton plus
field patches.  Use:

```python
base_materialization: Literal[
    "source_template_fixed",
    "native_template_row",
]

field_patch_kinds: tuple[
    Literal[
        "operand_patch",
        "route_endpoint_patch",
        "immediate_binding",
        "layout_binding",
        "boundary_policy",
        "zero_with_evidence",
    ],
    ...
]
```

#### Base: `source_template_fixed`

Used for GEMM legacy/template spans and any row whose full or partial `inst_t`
fields already exist as source-backed evidence.

Required:

```text
template_row_sha256
source file / row id
decoded fields
role match
FiberOp provenance
source_template_fixed evidence id
```

No hidden reallocation is allowed.

#### Base: `native_template_row`

Used for log10max ring FMAX updates, ReLU HMAX, local_reduce, max_with_floor,
and native elementwise rows.

Required:

```text
TemplateExpansion
OperandPlaceholder
OperandAllocation
InstOperandPatch
ImmediateBinding when needed
InstructionLayoutPlan
InstructionBoundaryPlan
pack -> decode field roundtrip
```

#### Patch kind: `route_endpoint_patch`

Used for COPY/COPYT/LDN-like route rows.

Required:

```text
sender executor placement
receiver logical owner placement
receiver-owned dst operand allocation
child/block edge slot or flow_ack
source operand allocation
COPY/COPYT lane policy
pack -> decode route field roundtrip
```

### 4. Byte writer contract

The writer may only pack:

```text
InstFieldBindingRecord(field_status="bound")
```

It must reject:

```text
missing operand_patch_id for operand-bearing rows
missing route_endpoint_patch_id for route rows
missing instruction_layout_plan_id / exe_block_writer_plan_id when required
missing boundary_policy_id
hardcoded operand index without source_template_fixed evidence
COPY dst operand from sender scope
route row with dst block/PE unset
```

The writer output is:

```python
@dataclass(frozen=True)
class InstRowByteCandidateRecord:
    row_id: str
    component_name: Literal["insts_file.bin"]
    component_byte_offset: int | None
    placement_status: Literal[
        "unplaced_candidate",
        "placed_candidate",
        "component_integrated",
    ]
    raw_inst_t_row_bytes_sha256: str
    decoded_fields: dict[str, object]
    field_binding_record_id: str
    source_fiber_op_id: str
    runtime_ready_claim: bool = False
```

Phase 1 emits `InstRowByteCandidateRecord`, not final component rows.
`component_byte_offset` may be `None` until component placement.
`runtime_ready_claim` remains false until component placement and preintegration
gates pass.

## Invariants

1. FiberOp remains the atomic semantic unit.
2. TemplateExpansion may expand a FiberOp into rows, but every row keeps
   `source_fiber_op_id`.
3. Serializer is not allocator.
4. Serializer is not route planner.
5. Serializer is not exeBlock scheduler.
6. Every operand-bearing row must have `InstOperandPatch` or
   `source_template_fixed` evidence.
7. COPY/COPYT destination operands are receiver-owned.
8. Same numeric operand index across different task/PE scopes is not a data
   dependency.
9. `block_idx` and `stages_start_pc` are late PE-local layout fields.
10. `flow_ack` is a route/control field and may affect COPY projection.
11. `iter_exe_cond` is a base/address selector for several opcode families.
12. `end_inst` requires explicit stage boundary policy.
13. Candidate skeleton bytes are diagnostic only until all field owners close.

## Alternatives Considered

### Alternative A: Let the writer fill missing fields

Rejected.  This recreates a hidden backend inside the serializer and bypasses
the operand allocation and route endpoint contracts we just added.

### Alternative B: Replay `common_oper` wholesale

Deferred.  It is useful as an evidence generator, but making it the B-line
trunk would reintroduce A-line coupling and hide field ownership.  B-line should
reuse source-backed algorithms, not outsource authority.

### Alternative C: Use exact A-line bytes for all three operators

Partially accepted only for compatibility spans.  GEMM can use
`source_template_fixed` evidence when exact rows exist.  Native ReLU/log10max
rows still need B-line field binding because their operator composition and
ring route are B-line decisions.

## Migration / Implementation Plan

### Phase 0: Field provenance report

Add a report-only field binding summary for each candidate row family:

```text
gemm source_template_fixed rows
relu HMAX/IMM candidate rows
log10max ring FMAX update rows
log10max route rows
log10max local_reduce rows
log10max max_with_floor rows
```

Pass condition:

```text
every row lists field owners
missing fields are explicit blockers
runtime_ready remains false
```

### Phase 1: log10max ring FMAX update bytes

Use existing allocation-backed 30 FMAX patches.

Allowed:

```text
pack allocation-backed FMAX rows
decode opcode/src/dst/zero-with-evidence fields
emit InstRowByteCandidateRecord records
```

Still blocked:

```text
block_idx if no ExeBlockWriterPlan
end_inst if no InstructionBoundaryPlan
component integration
route row bytes
max_with_floor full row bytes
runtime_ready
```

### Phase 2: route row field binding

Close route-specific fields:

```text
source operand
receiver dst operand
receiver dst PE/block
flow_ack child slot
COPY/COPYT lane expansion
end_inst policy
```

This phase should be RFC-reviewed because route rows are high-risk.

Hard rule:

```text
No route row bytes may be emitted from RingEdgeRecord alone.
```

### Phase 3: local_reduce and max_with_floor native rows

Close remaining local compute fields:

```text
local_reduce source/output operands
log_spec source operand
globalmax source operand
constants / immediates
output operand
FLOG2/FMAX/FADD/FMUL or selected opcode rows
```

### Phase 4: component integration

Only after all row byte records exist:

```text
place rows into PE-major insts_file offsets
update exeBlock stage PCs
update component manifests
run decoder/resource/package gates
then consider runtime_ready transition
```

## Validation Plan

Add focused gates:

```bash
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_inst_field_binding.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_ring_update_inst_row_bytes.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_route_row_field_binding.py
PYTHONPATH=compiler python compiler/tools/check_stream_compiler_log10max_local_postprocess_row_fields.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_bline_runtime_ready_preintegration.py
```

Required checks:

```text
no operand-bearing final row without InstOperandPatch/source_template_fixed
route dst operand allocation scope == receiver task_pe
COPY dst PE/block present
flow_ack owner present for COPY rows
block_idx present from ExeBlockWriterPlan
end_inst present from InstructionBoundaryPlan
iter_exe_cond owner present for LD/ST/CAL/IMM rows
pack/decode roundtrip matches all bound fields
candidate bytes do not imply component integration
runtime_ready remains false until component gate passes
```

## Risks and Mitigations

### Risk: B-line field owners become too many artifacts

Mitigation: `InstFieldBindingRecord` is a join/proof artifact, not a new
semantic source.  Semantic authority remains FiberOp / StreamAction.

### Risk: source_template_fixed hides stale A-line rows

Mitigation: require row hash, decoded fields, role match, FiberOp provenance,
and source evidence id.

### Risk: route bytes are guessed

Mitigation: route rows need a dedicated route endpoint patch gate.  Route bytes
must not be emitted from `RingEdgeRecord` alone.

### Risk: endpoint operand continuity passes but postprocess is incomplete

Mitigation: max_with_floor GlobalMax source patch only clears the GlobalMax
source blocker.  `log_spec`, constants, output, row bytes, and component
integration remain separate blockers.

## Expected Effect

After this RFC is accepted, the next engineering step is no longer vague
"write bytes".  It becomes:

```text
for each row family:
  close field owner blockers
  pack row bytes
  decode and compare fields
  keep runtime_ready false until component integration
```

This lets us use A-line/vendor content aggressively while preventing the old
hidden-backend failure mode from entering B-line.

## Open Questions

1. For log10max ring route, should V1 use direct `COPY`, expanded `COPYT`, or a
   source-template-fixed sender COPY span?
2. Which exact `end_inst` policy applies to report-generated ring route rows?
3. Should B-line first emit simulator `inst_t` only, or also maintain RTL/debug
   projections in parallel?
4. For local_reduce, is the first delivery row family `SHFL+FMAX`,
   repeated FMAX, or source-template-fixed evidence from an A-line reduction
   probe?
5. For max_with_floor, should `global_max - 8.0` be an immediate, operand-RAM
   constant, or source-template-fixed constant row?

## Recommended Decision

Accept this RFC as the raw-byte field ownership contract.

Immediate next phase:

```text
Implement Phase 0 InstFieldBindingRecord reports.
Then implement Phase 1 log10max ring FMAX update row bytes only.
Do not implement route COPY/LDN row bytes without a route-row RFC.
Do not clear runtime_ready or uploadable.
```

The important boundary is simple:

```text
raw bytes may be packed only after field ownership is closed.
```
