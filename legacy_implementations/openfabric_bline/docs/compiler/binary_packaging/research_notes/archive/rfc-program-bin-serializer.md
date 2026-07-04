# RFC: ProgramBin Serializer After Folded VendorABI

Date: 2026-06-14

## Status

Accepted with blocking gates.

This RFC defines how the new refactored backend should move from folded
`ProgramVendorABI` to vendor simulator binary component files.

The central rule is:

```text
program_bin.py must serialize already-decided VendorABI rows.
It must not rediscover loop semantics, route paths, dependency classes,
or K-instance recurrence.
```

The binary serializer should be boring. All interesting decisions should happen
before it.

## Current Input

The current lowering stack is:

```text
ChipProgram
  -> ProcessorLogicalProgram
  -> ProcessorTileProgram
  -> ProgramNodeProgram
  -> DFUPackingProgram
  -> ProgramAsm
  -> ProgramVendorABI
  -> ProgramBin        # this RFC
```

`ProgramVendorABI` is already folded:

```text
k_stream:
  emit only template instance k0 exeBlocks
  VendorSubtaskRow.instances_amount = TileLoopRegion.repeat_count
  repeat_semantics = vendor_instance_repeat_whole_subtask_body

finalize_store:
  emit single-pass store exeBlocks
```

For current GEMM+ReLU:

```text
ProgramAsm:
  expanded symbolic blocks       = 832
  expanded k_stream blocks       = 768

ProgramVendorABI:
  folded vendor exeBlocks        = 256
  folded k_stream exeBlocks      = 192
  folded vendor graph edges      = 224
  symbolic_vendor_instance_row_count = 8
  predecessor/successor overflow = 0
```

`symbolic_vendor_instance_row_count` counts symbolic `VendorInstanceRow`
records. It does not count expanded logical K executions. Effective repeated
execution is represented by `VendorSubtaskRow.instances_amount`.

The `folded_vendor_report` is a mandatory input contract for binary lowering.
It tells the serializer which expanded edges were absorbed and must not be
re-emitted:

```text
absorbed_loop_carried_edges            = 192
absorbed_cross_subtask_store_edges     = 64
debug_expanded_edge_count              = 672
variant_binding_status                 = symbolic_only_not_binary_bound
```

The final field means binary lowering is not allowed to begin full emission
until per-instance variant binding is explicit.

The immediate next implementation target is not five `.bin` files. It is:

```text
ProgramBinRows
VendorLoopVariantBinding
InstructionLayoutPlan
instance_conf_info_t serializer
task_conf_info_t serializer
```

Full component/package emission is blocked until variant binding and
instruction layout are proven.

## Legacy Evidence To Preserve

The earlier legacy path already recovered most simulator binary surfaces. The
new implementation should reuse those facts, not re-investigate from scratch.

### Struct Sizes And Capacities

From `DFU3500_STRUCT_SIZES` and legacy header probes:

```text
inst_t                    = 304 bytes
exeBlock_conf_info_t       = 520 bytes
instance_conf_info_t       = 32 bytes
task_conf_info_t           = 120 bytes
sub_task_conf_info_t       = 266328 bytes
```

Vendor capacities:

```text
PEs                        = 16
inst_t per PE              = 4352
inst_t total padded rows   = 69632

exeBlock_conf_info_t rows  = 512

instance_conf_info_t rows  = 4 tasks * 8 subtasks * 2048 instances
                           = 65536

task_conf_info_t rows      = 4

sub_task_conf_info_t rows  = 4 tasks * 8 subtasks
                           = 32
```

### Simulator Component Files

The vendor simulator bundle has five long-struct component files:

```text
simulator_bin/insts_file.bin
simulator_bin/exeblock_conf_info_file.bin
simulator_bin/instance_conf_info_file.bin
simulator_bin/tasks_conf_info_file.bin
simulator_bin/subtasks_conf_info_file.bin
```

Final runtime blobs are concatenations:

```text
config/cbuf_file.bin =
  simulator_bin/insts_file.bin
  + simulator_bin/exeblock_conf_info_file.bin
  + simulator_bin/instance_conf_info_file.bin

config/micc_file.bin =
  simulator_bin/tasks_conf_info_file.bin
  + simulator_bin/subtasks_conf_info_file.bin
```

The runtime package also needs:

```text
config/input_data.bin
config/riscv_program
```

Those are host / test harness artifacts, not accelerator serializer rows.

### Legacy Serializer Code To Reuse

The old `core_legacy` code contains reusable byte layout evidence:

```text
dfu_vendor_instance_conf_serializer.py
  instance_conf_info_t = <4Q>
  base_addr[4], little-endian uint64
  unused slot = 0xffffffff

dfu_vendor_task_conf_serializer.py
  task_conf_info_t = <BB6x14Q>
  is_exe_start, is_exe_end, subtasks_amount, execute_times,
  subtasks_idx[8], suc_tasks[4]

dfu_vendor_exeblock_conf_serializer.py
  exeBlock_conf_info_t = 520-byte reconstructed C++ ABI layout
  PE-major padded order, 32 exeBlock slots per PE
  predecessor/successor slots = 4 each

dfu_vendor_subtask_conf_serializer.py
  sub_task_conf_info_t = 266328 bytes
  embeds 512 exeBlock_conf_info_t rows
  carries instances_amount and instances_conf_mem_based_addr

dfu_vendor_inst_serializer.py
  simulator inst_t long struct = 304 bytes
  per-PE instruction images padded to 4352 records
  RTL 8-byte instruction encoding remains out of scope

dfu_vendor_final_blob_writer.py
  appends simulator components into cbuf/micc blobs
```

## Non-Negotiable Binary Boundaries

### 1. No K Re-Expansion

Do not emit k1/k2/k3 k-stream exeBlocks as vendor rows.

Allowed:

```text
ProgramAsm expanded rows for debug
```

Forbidden:

```text
ProgramBin re-expands folded VendorABI into k-expanded exeBlock_conf rows
```

The binary layer must serialize:

```text
VendorSubtaskRow.instances_amount = repeat_count
```

not:

```text
one exeBlock row per expanded K instance
```

### 2. No Loop-Carried Graph Edges

Do not serialize:

```text
compute_k0 -> compute_k1 -> compute_k2 -> compute_k3
```

as vendor graph predecessor / successor slots.

Those edges were already absorbed into repeated subtask carried state.

### 3. No Debug-Expanded Edges

The `folded_vendor_report.debug_expanded_edge_count` edges remain debug evidence
only. Binary lowering must ignore them.

### 4. Variant Binding Before Bytes

The folded body template is k0-shaped. Each runtime instance must still select
the correct K-specific inputs.

Binary emission must not proceed until every loop variant binding maps to
concrete symbolic vendor fields:

```text
A tile offset
B tile offset
SPM / SRAM address offset
base_addr row selection
route bundle id
visibility ref id
instruction immediate fields
```

Otherwise the simulator may execute:

```text
for k:
  repeat k0 addresses
```

which is the worst possible folded-loop bug: structurally valid, semantically
wrong.

## Proposed New Layers

Do not put byte serialization directly inside `ProgramVendorABI`.

Recommended structure:

```text
ProgramVendorABI
  -> ProgramBinRows
  -> ProgramBinComponents
  -> ProgramBinPackage
```

### ProgramBinRows

Purpose:

```text
Convert folded VendorABI rows into concrete symbolic binary rows.
No bytes yet.
```

Outputs:

```text
inst_rows
exeBlock_conf_rows
instance_conf_rows
task_conf_rows
subtask_conf_rows
variant_binding_rows
instruction_layout_rows
```

This layer should attach every field needed by serializers:

```text
record index
global slot index
PE-major slot index
task/subtask index
instances_amount
stage PC/count fields
base_addr[4]
predecessor/successor slot rows
```

Minimum schema:

```python
@dataclass(frozen=True)
class ProgramBinRows:
    folded_vendor_report: FoldedVendorReport
    task_successor_policy: Literal[
        "unset",
        "legacy_chain",
        "independent_start_end",
        "single_task",
    ]
    instances_conf_mem_based_addr_unit: Literal["bytes"]

    variant_bindings: dict[str, VendorLoopVariantBinding]
    instruction_layout_rows: tuple[InstructionLayoutRow, ...]

    inst_rows: tuple[InstBinRow, ...]
    exe_block_rows: tuple[ExeBlockConfBinRow, ...]
    instance_rows: tuple[InstanceConfBinRow, ...]
    task_rows: tuple[TaskConfBinRow, ...]
    subtask_rows: tuple[SubtaskConfBinRow, ...]

    reverse_map: ProgramBinReverseMap
    validation_report: ProgramBinValidationReport
```

Every row should carry reverse provenance:

```text
row_id
global_row_index
component_name
component_byte_offset
source_vendor_row_id
source_asm_block_id | None
source_tile_micro_block_id | None
source_tile_action_ids
```

### InstructionLayoutPlan

`InstructionLayoutPlan` is part of `ProgramBinRows`.

Purpose:

```text
Choose the final instruction layout before exeBlock_conf rows are serialized.
```

Why it exists:

```text
exeBlock_conf_info_t contains stage start PCs, stage instruction counts,
and inst_mem_based_addr.
```

Those fields depend on the selected instruction mode:

```text
native_symbolic:
  one simple inst_t per symbolic instruction

legacy_gemm_compat:
  one symbolic compute row expands to recovered GEMM template rows
```

Therefore:

```text
exeBlock_conf rows may be built before inst_t bytes,
but not before InstructionLayoutPlan fixes final PC/count/range facts.
```

Suggested fields:

```text
layout_id
vendor_inst_mode
pe
vendor_exeblock_id
source_asm_block_id
stage
start_pc
end_pc
instruction_count
template_id | placeholder_kind
capacity_status
```

### ProgramBinComponents

Purpose:

```text
Serialize ProgramBinRows into component byte images.
```

Outputs:

```text
simulator_bin/insts_file.bin bytes
simulator_bin/exeblock_conf_info_file.bin bytes
simulator_bin/instance_conf_info_file.bin bytes
simulator_bin/tasks_conf_info_file.bin bytes
simulator_bin/subtasks_conf_info_file.bin bytes
```

Each component exposes:

```text
semantic_record_count
padded_record_count
record_size_bytes
semantic_size_bytes
padded_size_bytes
semantic_sha256
padded_sha256
padding_policy
component_bytes_ready
```

### ProgramBinPackage

Purpose:

```text
Write component files and compose final cbuf/micc blobs.
```

Outputs:

```text
config/cbuf_file.bin
config/micc_file.bin
```

It may also copy externally supplied:

```text
config/input_data.bin
config/riscv_program
```

but should not invent those artifacts.

## Variant Binding Design

This is the most important pre-byte step.

### Required Abstraction

Add a first-class table:

```text
VendorLoopVariantBinding
```

Suggested fields:

```text
binding_id
template_id
vendor_subtask_id
instance_key
loop_axis
loop_index

source_tile_refs
source_visibility_refs
route_bundle_refs

base_addr_slot_bindings
immediate_bindings
instruction_range_bindings
binding_target_kind
logical_address_expr
effective_address_expr
target_proof_status
```

`binding_target_kind` must be one of:

```text
instance_base_addr
instruction_static_immediate
instruction_parametric_immediate
route_param
debug_only
```

`target_proof_status` must be one of:

```text
legacy_confirmed
assumed_symbolic
debug_only
unsupported
```

This field is a hard safety rail. The verifier must reject a K-varying value if
it can only be represented by a static instruction field while the folded body
emits one shared k0 instruction image.

The verifier must also reject full component/package emission for unsafe
symbolic targets:

```text
route_param + assumed_symbolic                    -> full emission blocked
instruction_parametric_immediate + assumed_symbolic -> full emission blocked
debug_only                                        -> never functional emission
unsupported                                       -> always invalid
```

`logical_address_expr` and `effective_address_expr` make the folded address
equation explicit enough to audit against the expanded debug view. For example:

```text
logical_address_expr:
  A[k, m_tile] in SRAM region A

effective_address_expr:
  4 * (base_addr_word[0] + imm_word_offset_A(k, pe, tile))
```

This prevents the worst folded-loop failure mode:

```text
repeat_count = K
instance_conf rows exist
but effective address still equals k0 for every repeated instance
```

Immediate fields must be classified:

```text
static instruction immediate:
  encoded once in inst_t;
  cannot vary across repeated instances

parametric / instance-bound immediate:
  may vary only if vendor ABI has a proven per-instance substitution mechanism

instance_base_addr:
  preferred target for K-varying address roots / offsets
```

Example shape:

```text
template: repeated_loop_template:tile_loop:processor_1_2:...
instance: k2

A tile:
  logical tile ref = tile:dtensor_0000:A:128:128
  base_addr slot   = 0
  imm_word_offset  = ...

B tile:
  logical tile ref = tile:dtensor_0001:B:128:256
  base_addr slot   = 1
  imm_word_offset  = ...
```

### Relationship To InstanceConf

Legacy evidence:

```text
instance_conf_info_t:
  uint64_t base_addr[4]

effective address formula:
  effective_byte_addr = 4 * (base_addr_word + imm_word_offset)
```

`instance_conf_info_t` rows are subtask-instance level rows, not PE-local
exeBlock rows, unless future vendor evidence proves otherwise. That means all
PEs / exeBlocks in one subtask instance share the same four base address slots.

Implication:

```text
PE-specific variation must be represented by instruction offsets,
tile-coordinate-derived offsets, or static layout rules.

It must not assume PE-local base_addr[4] rows.
```

Suggested row shape:

```python
@dataclass(frozen=True)
class InstanceConfBinRow:
    global_row_index: int
    task_idx: int
    subtask_idx: int
    instance_idx: int
    base_addr_words: tuple[int, int, int, int]
    source_binding_ids: tuple[str, ...]
    component_byte_offset: int
```

Subtask rows reference these rows through:

```text
instances_conf_mem_based_addr + instance_idx
```

The exact field unit must be made explicit in `ProgramBinRows`:

```text
instances_conf_mem_based_addr_unit = bytes
```

Legacy serializer evidence currently uses byte offsets for
`instances_conf_mem_based_addr`.

Effective subtask instance count is defined as:

```text
effective_instance_count =
  sum over VendorSubtaskRow:
    subtask.instances_amount
```

This is the semantic count of repeated subtask instances that need
`instance_conf_info_t` coverage. It is distinct from
`symbolic_vendor_instance_row_count`.

Known DFU3500 memory facts:

```text
offset unit             = bytes
legacy base addr unit   = uint32 words
word size               = 4 bytes
base_addr slots         = 4
unused slot sentinel    = 0xffffffff
```

For current GEMM regions:

```text
A base word32 = 0x00000
B base word32 = 0x10000
C base word32 = 0x20000
```

Legacy K-stream stride evidence:

```text
A K stride word32 = 0x20
B K stride word32 = 0x4000
```

The new code should not hardcode those GEMM strides forever, but the first
implementation can use them as a compatibility check while deriving offsets
from tensor shape / tile coordinates.

### Verifier

Before byte emission:

```text
for each repeated_loop_template:
  for each expanded_debug_instance_key:
    assert variant binding exists
    assert every loop_variant_ref is bound
    assert base_addr slots <= 4
    assert byte offsets are word-addressable
    assert required alignment constraints pass
```

At minimum, preserve the old offset audit constraints:

```text
byte_offset % 4 == 0
byte_offset % 128 == 0
```

The 128B rule is conservative, based on 4096-bit movement alignment.

## Do Not Start Full Byte Emission Until

Full component emission must stay blocked until these checks pass:

```text
1. VendorLoopVariantBinding exists.
2. folded_vendor_report.variant_binding_status is no longer symbolic_only_not_binary_bound.
3. instance_conf rows represent all effective subtask instances.
4. k_stream subtasks keep folded exeBlock rows and repeat_count instances.
5. no loop_carried / debug_expanded edge is vendor-graph eligible.
6. every byte row has a reverse provenance path to VendorABI and tile micro-block.
7. InstructionLayoutPlan fixes final PC/count/range facts.
8. no K-varying field is bound to a static inst_t immediate.
```

Until then, `program_bin.py` may emit plans and partial byte images, but should
not claim:

```text
complete_runtime_package_emitted = true
```

## Component Mapping

### 1. `inst_t`

Input:

```text
ProgramVendorABI.instruction_ranges
ProgramVendorABI.vendor_exeblocks
ProgramVendorABI.repeated_loop_templates
VendorLoopVariantBinding
```

Output:

```text
simulator_bin/insts_file.bin
```

Known layout:

```text
record size = 304 bytes
PE-major image
4352 records per PE
69632 padded records total
```

Important distinction:

```text
ProgramAsm symbolic_instruction_count != final inst_t count
```

Current symbolic rows are one row per `ProgramNode`. Final `inst_t` may expand
one symbolic compute instruction into a vendor template sequence. The legacy
path had a folded GEMM compute template of 576 simulator `inst_t` rows per
folded group.

First implementation options:

```text
Option A: native symbolic placeholder mode
  serialize one simple inst_t per symbolic instruction
  fastest for plumbing
  not expected to match vendor compute behavior

Option B: legacy GEMM compatibility mode
  reuse recovered GEMM HMMAL template expansion
  compare counts / hashes against legacy where possible
  best route for simulator bring-up
```

Recommendation:

```text
Implement both modes behind an explicit policy:
  vendor_inst_mode = native_symbolic | legacy_gemm_compat

Do not pretend native_symbolic is final correctness.
```

Required mode semantics:

```text
vendor_inst_mode = native_symbolic
  component_semantics = structural_smoke_only
  complete_runtime_package_semantics = false

vendor_inst_mode = legacy_gemm_compat
  component_semantics = functional_gemm_candidate
  allowed only after route/store placeholders and variant binding are acceptable
```

### 2. `exeBlock_conf_info_t`

Input:

```text
ProgramVendorABI.vendor_exeblocks
ProgramVendorABI.vendor_graph_edges
ProgramVendorABI.instruction_ranges
InstructionLayoutPlan
```

Output:

```text
simulator_bin/exeblock_conf_info_file.bin
```

Known layout:

```text
record size = 520 bytes
capacity = 512 records
PE-major padded order
32 slots per PE
predecessor slots = 4
successor slots = 4
```

Important fields from legacy serializer:

```text
valid
block_idx
pe_dst
priority
req_activations
has_stages[LD,CAL,FLOW,ST,END]
stages_start_pc[...]
predecessors[4]
successors[4]
task_idx
subtask_idx
instances_amount
child_amount
block_class
inst_mem_based_addr
ld/cal/flow/st stage counts
is_leaf
```

New folded requirement:

```text
instances_amount must come from the owning VendorSubtaskRow,
not from expanded K row count.
```

`exeBlock_conf_info_t` stage PC/count fields must come from
`InstructionLayoutPlan`, not from stale symbolic `ProgramAsm` counts if the
selected `vendor_inst_mode` expands instructions.

### 3. `instance_conf_info_t`

Input:

```text
VendorLoopVariantBinding
VendorSubtaskRow.instances_amount
base_addr assignment rows
```

Output:

```text
simulator_bin/instance_conf_info_file.bin
```

Known layout:

```text
record size = 32 bytes
format = <4Q
base_addr[4]
capacity = 65536 rows
unused slot = 0xffffffff
```

This component is where folded repeat becomes concrete variant behavior. Each
subtask instance needs a row or a clear shared-row rule.

Critical rule:

```text
Do not serialize only k0 base_addr rows while instances_amount=K,
unless the immediate fields independently encode all K variation.
```

For current design, the safer path is:

```text
one instance_conf row per effective subtask instance
```

while exeBlock rows remain folded.

### 4. `task_conf_info_t`

Input:

```text
ProgramVendorABI.vendor_tasks
```

Output:

```text
simulator_bin/tasks_conf_info_file.bin
```

Known layout:

```text
record size = 120 bytes
format = <BB6x14Q
capacity = 4 rows
```

Fields:

```text
is_exe_start
is_exe_end
subtasks_amount
execute_times
subtasks_idx[8]
suc_tasks[4]
```

Current refactor has four independent output-wave tasks. The binary RFC should
decide whether task successor chaining is needed or whether task rows are all
start/end singletons for current simulator workflow. Legacy task serializer
used a successor chain for multi-task execution.

Before `config/micc_file.bin` emission, task successor policy must be explicit:

```text
ProgramBinRows.task_successor_policy =
  legacy_chain
  | independent_start_end
  | single_task
```

The task serializer must consume `ProgramBinRows.task_successor_policy`; it must
not infer a default policy locally.

The package report must print:

```text
task_idx
is_exe_start
is_exe_end
subtasks_idx
suc_tasks
```

### 5. `sub_task_conf_info_t`

Input:

```text
ProgramVendorABI.vendor_subtasks
ProgramBinRows.instance_conf rows
ProgramBinComponents.exeBlock_conf rows
```

Output:

```text
simulator_bin/subtasks_conf_info_file.bin
```

Known layout:

```text
record size = 266328 bytes
capacity = 32 rows
embeds 512 exeBlock_conf_info_t slots
```

Important fields:

```text
is_exe_start
is_exe_end
instances_amount
instances_conf_mem_based_addr
suc_subtasks[4]
root_block_amount
block_amount
exeBlocks_conf_info[512]
subtask_idx
task_idx
```

New folded requirement:

```text
k_stream subtask:
  instances_amount = repeat_count
  block_amount = number of folded template exeBlocks
  exeBlocks_conf_info embeds only folded template body rows

finalize_store subtask:
  instances_amount = 1
  block_amount = store exeBlocks
```

`sub_task_conf_info_t` embeds `exeBlock_conf_info_t` rows. There must be one
source of truth:

```text
ProgramBinRows.exeBlock_conf_rows
  -> exeblock_conf_info_file.bin
  -> byte-for-byte embedded rows inside sub_task_conf_info_t
```

Validation:

```text
subtask_embedded_exeblock_bytes == exeblock_component_bytes_for_same_rows
```

Do not let the exeBlock component serializer and subtask serializer generate
two independently “similar” exeBlock records.

## Serialization Order

Recommended implementation order:

```text
1. ProgramBinRows
   - build variant bindings
   - build instruction layout rows
   - build instance/task/subtask/exeBlock symbolic binary rows
   - no bytes

2. VariantBinding verifier
   - prove every loop_variant_ref has a concrete binary target
   - reject illegal static-immediate variation

3. InstructionLayoutPlan verifier
   - select vendor_inst_mode
   - assign final PC/count/ranges
   - check per-PE instruction capacity

4. instance_conf_info_t serializer
   - easiest byte format
   - proves variant binding rows are concrete

5. task_conf_info_t serializer
   - small and stable

6. exeBlock_conf_info_t serializer
   - consumes folded graph rows and instruction ranges
   - validates predecessor/successor <= 4

7. sub_task_conf_info_t serializer
   - embeds exeBlock_conf rows
   - validates folded instances_amount and block_amount

8. inst_t serializer
   - initially native_symbolic or legacy_gemm_compat
   - must respect per-PE 4352 record capacity

9. component file writer
   - writes simulator_bin/*.bin

10. final blob composer
   - writes config/cbuf_file.bin and config/micc_file.bin
```

Why instance/task before inst_t?

```text
They are small, structurally proven, and expose variant binding / repeat count
bugs before full instruction byte encoding begins.
```

Important order constraint:

```text
exeBlock_conf can serialize before inst_t bytes,
but only after InstructionLayoutPlan has fixed final stage PC/count fields.
```

## Validation Gates

### Gate A: Folded ABI Contract

```text
folded_vendor_report.folded_repeat_mode == emit_vendor_rows
folded_vendor_report.variant_binding_status != symbolic_only_not_binary_bound
no k>0 k_stream asm block appears in vendor exeBlocks
no loop_carried edge appears in vendor graph edges
no debug_expanded edge appears in vendor graph edges
```

Before variant binding is implemented, this gate should fail intentionally for
full binary emission.

### Gate B: Variant Binding

```text
every repeated_loop_template has bindings for all expanded instance keys
every loop_variant_ref is bound
every loop_variant_ref has concrete binary target_kind
no K-varying field is bound to instruction_static_immediate
base_addr slots per instance <= 4
offsets are word-addressable
alignment constraints pass
```

### Gate C: Instruction Layout

```text
selected vendor_inst_mode creates final PC/count/ranges
per-PE inst_t rows <= 4352
exeBlock stage ranges point to final instruction layout
native_symbolic is marked structural_smoke_only
legacy_gemm_compat is required before functional GEMM claim
```

### Gate D: Row Capacity

```text
inst_t rows per PE <= 4352
exeBlock rows <= 512
instance rows <= 65536
task rows <= 4
subtask rows <= 32
subtask embedded exeBlock rows <= 512
```

### Gate E: Struct Size / Padding

Each serialized component must expose:

```text
record_size_bytes == DFU3500_STRUCT_SIZES[struct_name]
padded_size_bytes == expected capacity * record_size_bytes
```

Hard expected sizes:

```text
insts_file.bin:
  69632 * 304 = 21168128 bytes

exeblock_conf_info_file.bin:
  512 * 520 = 266240 bytes

instance_conf_info_file.bin:
  65536 * 32 = 2097152 bytes

tasks_conf_info_file.bin:
  4 * 120 = 480 bytes

subtasks_conf_info_file.bin:
  32 * 266328 = 8522496 bytes

cbuf_file.bin:
  21168128 + 266240 + 2097152 = 23531520 bytes

micc_file.bin:
  480 + 8522496 = 8522976 bytes
```

### Gate F: Store Ordering Proof

Before complete package emission:

```text
finalize_store subtask has LoopRegionExitToken provenance
or explicit subtask successor/order proof
```

Folded VendorABI may absorb `compute_k_last -> store` into subtask order, but
the binary report must show why this is safe.

### Gate G: Stable Debug Reverse Map

Every byte row should map back to symbolic rows:

```text
byte row
  -> ProgramBinRow
  -> VendorABI row
  -> ASM block/instruction
  -> tile micro-block
  -> tile action
```

Without this reverse map, simulator failures become too hard to debug.

## Expected First Milestone

The first milestone should not claim full simulator correctness.

Recommended milestone:

```text
ProgramBinRows exists.
folded VendorABI report is consumed.
variant binding table exists and is validated.
InstructionLayoutPlan exists and fixes PC/count/range facts.
instance_conf_info_t and task_conf_info_t bytes serialize.
No final cbuf/micc package emitted yet.
```

That milestone proves the most dangerous folded-loop problem: per-instance
variant binding.

## Expected Second Milestone

```text
exeBlock_conf_info_t and sub_task_conf_info_t serialize.
folded k_stream subtask embeds only template body exeBlocks.
instances_amount is repeat_count.
predecessor/successor slots remain within capacity.
subtask embedded exeBlock bytes match the exeBlock component source rows.
```

At this point `micc_file.bin` composition can be tested only after
`task_successor_policy` is explicit and store ordering has a
`LoopRegionExitToken` or equivalent proof.

## Expected Third Milestone

```text
inst_t serializer works in one explicit mode:
  native_symbolic
  or legacy_gemm_compat

component writer emits all five simulator_bin files.
final blob composer emits cbuf_file.bin and micc_file.bin.
```

At this point the bundle can be tested against the vendor simulator workflow,
with `input_data.bin` and `riscv_program` still supplied by the runtime bundle
layer.

## Open Questions

### Q1: Which inst_t mode should be first?

`native_symbolic` is faster to implement but may not execute meaningful GEMM.
`legacy_gemm_compat` is more useful for simulator bring-up but requires mapping
current folded HMMAL symbolic rows to the recovered legacy template.

Recommendation:

```text
Implement native_symbolic as plumbing only.
Implement legacy_gemm_compat before claiming functional GEMM binary.
```

### Q2: Where should task successor semantics live?

Current refactored GEMM has four output-wave tasks. Legacy task rows often form
a task successor chain.

Binary RFC follow-up must decide:

```text
task0 -> task1 -> task2 -> task3
```

versus independent start/end task rows, based on vendor workflow expectation.

### Q3: Are route/store symbolic placeholders enough?

The legacy inst serializer still marks:

```text
COPYT_SYMBOLIC
STORE_TILE_SYMBOLIC
```

as placeholders. For true simulator execution, route and store may need real
instruction templates.

This should be tracked separately from the struct serialization problem.

## Implementation Recommendation

Start with a new file:

```text
compiler/gpdpu_compiler/core/program_bin.py
```

Do not spread byte emission across existing IR files.

Export from `core/__init__.py`:

```text
ProgramBinRows
ProgramBinComponents
ProgramBinPackage
lower_vendor_abi_to_program_bin_rows
```

Initial implementation should be narrow:

```text
ProgramVendorABI -> ProgramBinRows
```

and should intentionally refuse full component emission while:

```text
folded_vendor_report.variant_binding_status == symbolic_only_not_binary_bound
```

This makes the next failure clean and honest:

```text
binary serialization blocked by missing variant binding
```

instead of silently producing repeated k0 data.
