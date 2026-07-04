# DFU Tiny Distributed Tensor Compiler

Status: historical notes only. The old Python compiler implementation was
removed on 2026-07-04 because it is superseded by the scoped tensor projection
model and the active OpenFabric implementation.

This file is kept as a tombstone for the old route. The text below describes a
pre-scoped-projection plan and should not be treated as runnable guidance.

The old idea was to build a deliberately small compiler: support output-sharded
GEMM, emit inspectable IR and schedules first, then lower to CSV/runtime package
once the plan matches the known vendor examples.

The removed Python package was named `gpdpu_compiler`. Its core logical tensor
metadata intentionally mirrored PyTorch DTensor where it helped developer
intuition:

```text
gpdpu_compiler.core.DeviceMesh        inspired by torch.distributed.device_mesh
gpdpu_compiler.core.Placement         inspired by torch.distributed.tensor.placement_types
gpdpu_compiler.core.DTensorSpec       inspired by torch.distributed.tensor._dtensor_spec
gpdpu_compiler.core.OpSchema          inspired by torch.distributed.tensor._op_schema
gpdpu_compiler.core.DTensor           inspired by torch.distributed.tensor._api
```

This is a source-level homage and a compatibility-shaped API, not a copy of
PyTorch's runtime machinery. Our `DTensor` is a static compiler IR object, not a
`torch.Tensor` subclass.


## Runnable Baseline

The current DFU GEMM path has a vendor-runtime-runnable baseline archived at
[`../RUNNABLE_BASELINE.md`](../RUNNABLE_BASELINE.md).  Treat that generated
image as a behavioral guardrail while refactoring compiler layers: new IR work
may change byte layout, but it must not regress the ability to run
`gemm_template_fusion` with `task_num=4` through SimICT.

The former partner validation entry under
`gpdpu_compiler/validation/dfu3500_partner_validation/` was also removed with
the Python package and generated payloads. Future validation should be rebuilt
from the active OpenFabric package flow, not resurrected from this archive.

## First Implementation Slice

The first slice should implement:

```text
OperatorEnv user program
  -> DTensor-like logical frontend
  -> per-device logical actions
  -> per-TensorCore Tile Program
  -> shared LogicalCollective references
  -> derived Global Tile Dependency Network
  -> TileCollectiveAction lowering
  -> PE-local DFU Graph Skeleton
  -> graph-level task/subtask/instance packing plan
  -> plan.json for inspection
```

CSV/runtime package generation comes after `plan.json` is easy to compare with
`gemm_template_fusion`.

The next backend-lowering challenges are tracked in
[`docs/compiler/design/dfu-backend-lowering-principles.md`](../docs/compiler/design/dfu-backend-lowering-principles.md).
Conv2d and similar complex operator expansion is sketched in
[`docs/compiler/design/conv2d-virtual-im2col-gemm-lowering.md`](../docs/compiler/design/conv2d-virtual-im2col-gemm-lowering.md).
The current recommendation is to use a two-layer instruction path:

```text
TileAction / RouteAction
  -> structured DFU assembly records
  -> binary instruction records
```

Current implemented output:

```text
env.generate(...)
  -> plan.json
     - DTensor-like graph metadata
     - PE logical actions
     - tile_backend
       - PETileProgram per PE
       - TilePhase records
       - CollectiveBundle records
       - launch_group/task/subtask/instance mapping
```

The current source-of-truth rule is:

```text
Tile Program is the program.
Dependency graph is a derived view.
Backend graph is a lowering result.
```

The archived compiler documentation index is [`docs/compiler/README.md`](../docs/compiler/README.md).
Historical construction notes live under [`compiler/notes/`](notes/), while binary/package
facts are centralized under [`docs/compiler/binary_packaging/`](../docs/compiler/binary_packaging/).

Each Tensor Core owns a local Tile Program, but TileValue names and
LogicalCollective ids are global. When a value must become visible across
Tensor Cores, the compiler records a shared `LogicalCollective`; later lowering
expands it into per-participant `TileCollectiveAction` objects. For the legacy
DFU backend, those actions lower further into PE-local `GRAPH_NODE` records and
cross-PE graph edges. A DFU `GRAPH_NODE` is therefore not a collective-wide
node; it is a local execution block assigned to one PE.

Historical examples such as:

```bash
python3 compiler/examples/gemm.py
```

no longer exist in this archive. Generated bundle descriptions below are kept
only to explain what the old route attempted.

```text
tmp/gpdpu_compiler_examples/gemm/plan.json
tmp/gpdpu_compiler_examples/gemm/simulator_bin/*.bin
tmp/gpdpu_compiler_examples/gemm/config/cbuf_file.bin
tmp/gpdpu_compiler_examples/gemm/config/micc_file.bin
```

This is the accelerator-side simulator binary bundle. Runtime input data and
the RISC-V host program remain outside the current compiler layer.

For the fused baseline example:

```bash
python3 compiler/examples/gemm_relu.py
```

the generated files include:

```text
tmp/gpdpu_compiler_examples/gemm_relu/plan.json
tmp/gpdpu_compiler_examples/gemm_relu/simulator_bin/*.bin
tmp/gpdpu_compiler_examples/gemm_relu/config/cbuf_file.bin
tmp/gpdpu_compiler_examples/gemm_relu/config/micc_file.bin
```

The important inspection surface is `tile_backend`. For the default
`512x256 @ 256x512` GEMM on a `4x4` mesh, it should contain 16 PE tile programs,
4 `local_gemm_summa` phases per PE, 4 K-block updates per GEMM phase, and
logical row/column broadcast bundles. Physical COPY/COPYT routes are deliberately
left unresolved in V1.

The same generate step also emits human-readable debug dumps:

```text
tmp/gpdpu_compiler_examples/gemm_relu/debug_ir/
```

These files are one-line-per-record views for developer review:

```text
00_chip_logical_actions.lines.txt
00_global_logical_trace.lines.txt
01_tensors.lines.txt
02_graph_nodes.lines.txt
03_local_values.lines.txt
04_pe_logical_actions.lines.txt
05_tile_phases.lines.txt
06_spmd_materialization.lines.txt
07_k_steps.lines.txt
08_architecture_expansion.lines.txt
09_instruction_instances.lines.txt
10_derived_collective_obligations.lines.txt
11_route_lowering.lines.txt
11_route_lowering.verbose.lines.txt
12_route_summary.lines.txt
13_task_plan.lines.txt
14_dfu_assembly.lines.txt
14_dfu_assembly.verbose.lines.txt
15_tile_dependencies.lines.txt
15_tile_dependencies.verbose.lines.txt
16_dfu_graph.lines.txt
16_dfu_graph.verbose.lines.txt
17_dfu_packing.lines.txt
17_dfu_packing.verbose.lines.txt
18_dfu_residency.lines.txt
18_dfu_residency.verbose.lines.txt
19_dfu_storage_binding.lines.txt
19_dfu_storage_binding.verbose.lines.txt
20_dfu_runtime_frame.lines.txt
20_dfu_runtime_frame.verbose.lines.txt
21_dfu_assembly_attachment.lines.txt
21_dfu_assembly_attachment.verbose.lines.txt
22_dfu_base_table.lines.txt
22_dfu_base_table.verbose.lines.txt
23_vendor_runtime_package.lines.txt
23_vendor_runtime_package.verbose.lines.txt
24_vendor_blob_schema.lines.txt
24_vendor_blob_schema.verbose.lines.txt
25_vendor_aligned_packing.lines.txt
25_vendor_aligned_packing.verbose.lines.txt
26_vendor_exeblock.lines.txt
26_vendor_exeblock.verbose.lines.txt
27_vendor_instance_table.lines.txt
27_vendor_instance_table.verbose.lines.txt
28_vendor_base_addr_compatibility.lines.txt
28_vendor_base_addr_compatibility.verbose.lines.txt
29_vendor_instruction_offset_binding.lines.txt
29_vendor_instruction_offset_binding.verbose.lines.txt
30_vendor_offset_field_audit.lines.txt
30_vendor_offset_field_audit.verbose.lines.txt
pe/PE00.trace.txt ... pe/PE33.trace.txt
```

`debug_ir` is intentionally a debug output only. Downstream lowering must use
structured IR objects or `plan.json`, not parse these readable text files.
The global `*.lines.txt` files keep a compact one-record-per-line shape for
diffing and validation. The per-PE trace files add a more human-facing Layer 3:
each output tile is shown as an `inputs -> compute -> output` mini program with
named debug-local refs such as `a0`, `b0`, `c0`, and `y0`.

`15_tile_dependencies.lines.txt` is the default tile-program review surface. It
is organized as:

```text
TILE_VALUE_ALIAS      # short id -> logical tile value
TILE_INSTANCE_ALIAS   # short id -> value at a location
TC_PROGRAM / TC_OP    # each Tensor Core manipulates tile instance ids
```

The exhaustive dependency edge view remains in
`15_tile_dependencies.verbose.lines.txt`. That file is for backend auditing and
tests; humans should normally start from the registry + per-TC program view.

`16_dfu_graph.lines.txt` is the first executable dependency view over the Tile
Program. It is not final task/subtask scheduling. It records PE-local graph
nodes for `TileOp` / `TileCollectiveAction` and graph edges for value or
visibility dependencies.

`17_dfu_packing.lines.txt` is the first graph-level runtime-container packing
view. It binds every `GraphNode` into a current-heuristic task/subtask/instance
container without using assembly payloads as the scheduling unit:

```text
GraphNode is the scheduling unit.
TileResidency is the allocation unit.
AssemblyPayload is implementation payload, not truth.
BinaryInstruction is serialization.
```

For the baseline GEMM, V1 uses `task = one output-wave region` as a heuristic
and emits k-stream loop-folding candidates. This is not final vendor package
scheduling; tile residency planning and final assembly/binary emission remain
later backend passes.

`18_dfu_residency.lines.txt` is the first tile-level lifetime and resource
pressure view. It still does not allocate concrete operand indices or binary
fields. It records where each `TileInstance` is expected to reside, how long it
is live across packing instances/containers, and whether the conservative
resource model is obviously exceeded.

Current resource facts:

```text
operand slots per PE: 1536
SIMD128 operand width: 4096 bit = 512 bytes
64x64 fp16 tile: 8192 bytes = 16 operand slots
max 64x64 fp16 operand tiles per PE: 96
tensor tmp registers per PE: 16
one 64x64 HMMAL accumulator tile uses 16 tensor tmp registers
```

For the baseline GEMM, the current residency pressure is:

```text
k_stream instance:
  A tile + B tile = 32 operand slots
  C accumulator   = 16 tensor tmp registers

finalize/store instance:
  Y tile          = 16 operand slots
  C accumulator  = 16 tensor tmp registers
```

This layer is the right place to grow future operand-slot planning. It should
not start emitting binary or concrete bitfields.

`19_dfu_storage_binding.lines.txt` is the first symbolic storage binding view.
It consumes `TileResidency` entries and assigns conservative symbolic storage
ranges:

```text
operand-backed tile      -> instance-local operand slot ranges
HMMAL accumulator tile   -> tensor tmp range
tile view                -> alias / no storage
```

For the current GEMM baseline:

```text
operand high watermark      = 32 / 1536 slots
tensor tmp high watermark   = 16 / 16 registers
SPM / on-chip SRAM bindings = 0
```

This means operand RAM remains loose, while the tensor tmp accumulator path is
already saturated. Layer 19 therefore keeps `tensor_tmp_saturated` explicit in
both global and PE-local dumps. It still does not assign base address table
slots, SPM addresses, instruction bitfields, or binary encodings.

In compiler docs, `SPM` should be read as the chip-local scratchpad SRAM. We use
`on_chip_sram_spm` in new binding surfaces when the intent is a generic on-chip
SRAM workspace, and reserve vendor-specific `SPM` details for backend lowering.

`20_dfu_runtime_frame.lines.txt` is the first symbolic runtime frame view. It
separates runtime-visible address symbols from PE-local storage bindings:

```text
operand slot range:
  PE-local tile storage / tensor tmp storage

base_addr symbol:
  runtime frame entry for an external input/output/workspace address
```

For the current GEMM baseline:

```text
base_addr_symbols = 192
  input materialize = 128
  output store      = 64

A symbols = 64
B symbols = 64
Y symbols = 64

max base symbols per instance = 2 / 4
concrete addresses            = 0
binary encoded                = false
```

Only the source PE of a materialized route receives an input base symbol. PEs
that consume a tile through mesh visibility depend on the corresponding
`TileCollectiveAction`, but they do not get duplicate runtime input addresses.
Output store nodes receive output base symbols. This layer still does not assign
concrete DDR/SPM addresses, final base-table rows, instruction bitfields, or
binary encodings.

`21_dfu_assembly_attachment.lines.txt` closes the current provenance loop
without changing the scheduling unit:

```text
GraphNode / BaseAddrSymbol
  -> AssemblyPayload attachment
```

It answers:

```text
why does this assembly payload exist?
which GraphNode owns the payload?
which runtime base_addr symbol does it touch, if any?
```

For the current GEMM baseline:

```text
assembly_payloads = 704
attached         = 704
unattached       = 0

exact_graph_node_payload      = 256  # GEMM updates
multi_node_route_payload      = 384  # route edges touch source/destination TC actions
multi_node_fused_store_payload = 64  # ReLU + store_tile share one store payload

graph_node_payloads = 896
base_symbol_payloads = 192
binary encoded = false
```

This layer is an audit bridge. Assembly records remain implementation payloads;
they are not task/subtask scheduling units and they are not binary instructions.

`22_dfu_base_table.lines.txt` is the first symbolic base-table and runtime
package metadata view. It consumes `RuntimeFrame` instance frames and turns each
instance into a four-slot symbolic base-table row:

```text
RuntimeFrame / BaseAddrSymbol Plan
  -> symbolic base-table rows
  -> task/subtask/PE metadata
```

For the current GEMM baseline:

```text
base_table_rows  = 320
slot_entries     = 1280
active_slots     = 192
unused_slots     = 1088
subtask_tables   = 128
tasks            = 4
PEs              = 16

max active slots per row    = 2 / 4
max rows per subtask table  = 4 / 2048
max subtasks per task       = 2 / 8

concrete addresses     = 0
runtime package emitted = false
binary encoded          = false
```

This layer is still not the final vendor package. It is a PE-projected symbolic
view that preserves the four-slot base-table contract while keeping concrete
DDR/SPM addresses, final vendor table layout, and binary encoding out of scope.

`23_vendor_runtime_package.lines.txt` is the first vendor runtime package layout
view. It records the contract recovered from the workflow scripts:

```text
runtime_packages/<case>/config/cbuf_file.bin
runtime_packages/<case>/config/micc_file.bin
runtime_packages/<case>/config/input_data.bin
runtime_packages/<case>/config/riscv_program
```

The closed runtime only checks and copies those four `config/` files, but the
legacy workflow builds `cbuf_file.bin` and `micc_file.bin` from finer simulator
surfaces:

```text
cbuf_file.bin =
  simulator_bin/insts_file.bin
  + simulator_bin/exeblock_conf_info_file.bin
  + simulator_bin/instance_conf_info_file.bin

micc_file.bin =
  simulator_bin/tasks_conf_info_file.bin
  + simulator_bin/subtasks_conf_info_file.bin
```

Layer 23 maps those vendor surfaces back to compiler facts:

```text
insts_file              <- AssemblyPayloads
exeblock_conf_info_file <- DFU Graph / Packing / AssemblyPayloadAttachment
instance_conf_info_file <- BaseTable / RuntimeFrame
tasks_conf_info_file    <- Packing / BaseTable
subtasks_conf_info_file <- Packing / BaseTable
```

It still does not write any `.bin` file. It only freezes the package layout and
the composition rules that later binary/schema emitters must satisfy.

`24_vendor_blob_schema.lines.txt` maps those simulator surfaces to the record
families observed in the legacy headers and writers:

```text
insts_file.bin              = inst_t records
exeblock_conf_info_file.bin = exeBlock_conf_info_t records
instance_conf_info_file.bin = instance_conf_info_t records
tasks_conf_info_file.bin    = task_conf_info_t records
subtasks_conf_info_file.bin = sub_task_conf_info_t records
```

This layer separates OpenFabric semantic counts from vendor padded capacity
counts. For the current `gemm_relu` plan, the base table has 320 semantic
`instance_conf_info_t` rows, while the vendor blob capacity is
`4 tasks * 8 subtasks * 2048 instances = 65536` rows. It also records the
current instruction-pressure risk: the legacy-style expanded instruction
estimate exceeds one padded `insts_file.bin` capacity, so later task/subtask
splitting, template shrinking, or multi-launch slicing must resolve it before
binary emission.

`25_vendor_aligned_packing.lines.txt` is the first projection from OpenFabric's
graph-level packing model into the legacy vendor task/subtask/exeBlock ontology.
It does not emit vendor binary tables. It explains why the OpenFabric counts and
legacy counts live in different coordinate systems:

```text
OpenFabric containers       = graph-level runtime regions
OpenFabric base-table rows  = PE-projected runtime-frame rows

Vendor subtasks             = global task-level subtask rows
Vendor instance rows        = global subtask hardware-loop rows shared by PEs
Vendor exeBlocks            = PE-specific execution blocks under global subtasks
```

For the current `gemm_relu` baseline, the vendor-aligned projection targets the
legacy GEMM shape:

```text
tasks = 4
active subtasks per task = 3
subtask instance pattern = 1,4,1
semantic vendor instance rows = 24
valid exeBlocks = 256
vendor subtask slots = 32
vendor instance capacity = 65536

OpenFabric containers = 128
OpenFabric runtime rows = 320
```

The important boundary is:

```text
Layer 25 is a projection / count bridge.
It is not final exeBlock lowering.
It is not shared instance table emission.
It is not binary encoding.
```

`26_vendor_exeblock.lines.txt` is the first symbolic vendor exeBlock row plan.
It consumes Layer 25 and creates candidate `exeBlock_conf_info_t` rows while
keeping instruction offsets and binary fields unresolved.

For the current `gemm_relu` baseline:

```text
vendor exeBlocks = 256 / 512
subtask ranges = 12
mapped OpenFabric containers = 128 / 128
synthetic prologue exeBlocks = 64

role counts:
  prologue_materialize = 64
  k_stream_materialize_compute = 128
  epilogue_finalize_store = 64
```

The plan also preserves provenance:

```text
synthetic prologue exeBlocks:
  source_container = -

k_stream exeBlocks:
  source_container = taskX:PEYY:subtask0

epilogue/store exeBlocks:
  source_container = taskX:PEYY:subtask1
```

Layer 26 is still not final vendor emission. It is the symbolic row-level
bridge that later passes must use to assign instruction ranges and write
`exeBlock_conf_info_t` binary records.

`27_vendor_instance_table.lines.txt` is the first symbolic shared
`instance_conf_info_t` row plan. It consumes the PE-projected Layer 22
base-table rows and folds them into the vendor subtask-instance coordinate
system:

```text
Layer 22 PE-projected rows:
  task / PE / OpenFabric subtask / OpenFabric instance

Layer 27 vendor rows:
  task / vendor subtask / shared hardware-loop instance
```

For the current `gemm_relu` baseline:

```text
vendor instance rows = 24
vendor instance capacity = 65536
subtask instance ranges = 12
OpenFabric base-row mappings = 320 / 320

role counts:
  prologue_materialize = 4
  k_stream_materialize_compute = 16
  epilogue_finalize_store = 4
```

The per-task shape is the recovered legacy pattern:

```text
subtask0 prologue_materialize:
  instances_amount = 1

subtask1 k_stream_materialize_compute:
  instances_amount = 4

subtask2 epilogue_finalize_store:
  instances_amount = 1
```

Layer 27 also calculates the symbolic `instances_conf_mem_based_addr` for each
vendor subtask range. For example, `task0:vendor_subtask1` starts at byte offset
`32`, because `instance_conf_info_t` is 32 bytes and task0 subtask0 consumes one
row first.

This layer still does not write concrete `uint64_t base_addr[4]` values. Each
row records folded slot evidence:

```text
slot0: input_A source symbols
slot1: input_B source symbols
slot0: output_Y source symbols
```

The open follow-up is to prove that per-PE instruction offsets can turn these
symbolic folded slots into legal shared vendor `base_addr[4]` rows, and then
emit padded `instance_conf_info_file.bin`.

`28_vendor_base_addr_compatibility.lines.txt` is the first symbolic proof that
the folded Layer 27 slots can be represented by shared vendor base-address
entries plus per-PE/per-instruction offsets:

```text
VendorInstanceTablePlan
  -> tensor_root_base + row-major byte offset proof
```

For the current `gemm_relu` baseline:

```text
row proofs = 24
slot proofs = 96
active slot proofs = 36
compatible active slots = 36
incompatible active slots = 0

concrete addresses = 0
instruction offsets = 0
binary encoded = false
```

The proof model is conservative:

```text
base_addr[slot] = tensor_root_base:<tensor>
instruction/runtime offset = row_major_byte_offset(tile)
```

Examples:

```text
task0 k0 A slot:
  shared_base = tensor_root_base:A
  offsets = A[m=0,k=0], A[m=128,k=0], A[m=256,k=0], A[m=384,k=0]

task0 k0 B slot:
  shared_base = tensor_root_base:B
  offsets = B[k=0,n=0], B[k=0,n=128], B[k=0,n=256], B[k=0,n=384]

task0 store Y slot:
  shared_base = tensor_root_base:Y
  offsets = all PE-local output tiles for that C wave
```

Layer 28 is still not final address allocation. It proves that the folded slots
have a coherent tensor-root base model and records the byte-offset evidence that
later instruction-range/offset assignment must consume.

`29_vendor_instruction_offset_binding.lines.txt` consumes that Layer 28 evidence
and binds runtime-visible assembly payloads to:

```text
vendor_instance_row + base_addr_slot + tensor_root_base + symbolic_byte_offset
```

For the current `gemm_relu` baseline:

```text
offset bindings = 256
runtime base payloads = 256
compatible bindings = 256
misaligned bindings = 0

materialize_route_edge bindings = 192
store_tile bindings = 64
concrete bases = 0
instruction immediates = 0
binary encoded = false
```

This layer is intentionally narrower than binary encoding. It proves that
runtime-facing payloads can point at the shared vendor base row plus a byte
offset, but it does not yet prove that the final vendor instruction immediate
field can encode that offset. `gemm_inner_update` payloads are PE-local tile
payloads and do not directly bind external runtime base addresses in this pass.

`30_vendor_offset_field_audit.lines.txt` consumes Layer 29's offset bindings and
checks the vendor memory-offset constraints we currently know from the SIMD
instruction materials and legacy GEMM notes:

```text
effective_addr = 4 * (instance_baseaddr[base_addr_idx] + imm_word_offset)
byte_offset must be divisible by 4
HLDT/HSTT-style 4096-bit movement requires 128-byte alignment
```

For the current `gemm_relu` baseline:

```text
offset field rows = 256
known constraints ok = 256
known constraint failures = 0
word addressable = 256
128B aligned = 256

materialize_route_edge rows = 192
store_tile rows = 64

bitwidth verified = 0
bitwidth unknown = 256
binary encoded = false
```

This is a legality audit, not an encoder. It proves the symbolic byte offsets
can be converted into vendor word offsets and satisfy the known alignment rule,
but it still does not assign final immediate field width, signedness, split
rules, concrete base addresses, or binary instruction records.

The current compiler stack models the accelerator-side runtime payload only.
A full vendor operator can also contain one or more RISC-V/CPU-side apps that
control DRAM/SRAM movement and kernel launch order. That host-control layer is
tracked as future runtime orchestration work, not as part of the current
task/subtask/instance accelerator plan.

Addressing should keep two levels separate:

```text
DRAM tensor roots:
  dynamic / relocatable per launch

SPM / on-chip SRAM scratchpad:
  mostly static kernel-local layout
```

So PE-side instructions do not need to be fully relocatable. A later
RISC-V/DMA orchestration layer can move arbitrary DRAM tensor chunks into fixed
SPM slots, let the accelerator consume hardcoded SPM offsets, then copy outputs
back to DRAM. Vendor dataflow graph leaf-node declarations are also a future ABI
surface; current graph layers record dependencies but do not yet emit that final
leaf-node declaration format.

`env.generate(...)` also runs structural validation before writing the artifacts.
The first validator checks:

```text
all PE tile programs have a homogeneous phase sequence
every PE logical action is lowered or explicitly marked as fused
each GEMM phase has the expected K-instance count
each KSTEP satisfies A.m == C.m, B.n == C.n, and A.k == B.k
each referenced derived row/column visibility obligation exists
row visibility participants stay on one mesh row
column visibility participants stay on one mesh column
```

This is deliberately stronger than a pretty-printer check. The readable trace is
for humans; the validator is the first guardrail that the compiler plan still
matches the SUMMA/dataflow invariants.

## DTensor-like Frontend / DFU Backend Boundary

The compiler has a clean boundary:

```text
DTensor-like frontend:
  Responsible for logical distributed tensor semantics.
  Produces logical tensors, placement propagation, and collective intent.

DFU backend:
  Responsible for hardware-specific lowering.
  Produces tile ownership, tile actions, collective tile bundles,
  BSP/subtask schedules, instance base tables, and eventually CSV/runtime package.
```

The frontend can strongly borrow from PyTorch DTensor:

```text
DeviceMesh
Placement: Shard / Replicate / Partial
DTensorSpec-like logical tensor spec
TensorMeta-like shape/dtype/stride metadata
OpSchema-like operator input/output schema
ShardingPropagator-like rule registry
Redistribute / collective insertion intent
```

This borrowed layer should stop at device logical actions:

```text
LogicalTensor
  -> OpSchema
  -> placement propagation
  -> output LogicalTensor
  -> required redistribute / collective intent
  -> per-device logical op
```

Then the DFU backend starts:

```text
per-device logical op
  -> MaterializedTilePlan
  -> TileAction
  -> CollectiveTileBundle
  -> BSP/subtask schedule
  -> instance base table
  -> instruction template / CSV
```

Do not copy PyTorch's full runtime dispatch, fake tensor mode, autograd, or
collective execution. We only need the small static compiler subset:

```text
spec dataclasses
placement helpers
op schema
rule registry
matmul and pointwise propagation rules
redistribute intent representation
```

## User Programming Model: Operator ABI

The user-facing model should define an operator, not just an arbitrary tensor
program. An operator has an explicit ABI:

```text
named inputs
named outputs
input/output shapes and dtypes
input placements on a 4x4 PE mesh
output placement inherited from the returned/bound tensor
operator computation
optional fusion/post-processing computation
```

Recommended first-version API shape:

```python
def main():
    env = OperatorEnv("gemm_relu")
    mesh = env.mesh("pe", (4, 4), dim_names=("row", "col"))

    A = env.input(
        "A",
        shape=(M, K),
        dtype="fp16",
        placements=[Shard(0), Replicate()],
        mesh=mesh,
    )
    B = env.input(
        "B",
        shape=(K, N),
        dtype="fp16",
        placements=[Replicate(), Shard(1)],
        mesh=mesh,
    )

    C = A @ B
    Y = relu(C)

    env.output("Y", Y)

    env.generate(output_dir="build/gemm_relu")


if __name__ == "__main__":
    main()
```

This is still a distributed tensor model, but it is framed as an operator
contract:

```text
external input memory  -> InputTensor
external output memory -> OutputTensor
intermediate tensors   -> compiler-managed temporaries
```

`env.output(name, tensor)` does not need a placement argument in the first
version. The output tensor already carries its logical distributed placement
from the operation graph. `env.output(...)` only binds that tensor to a named
external SPM/runtime output buffer. If the user wants a different output layout,
they should insert an explicit layout transform before binding the output.

The user should not mention PE IDs, CSV files, operand slots, `COPYT`,
task/subtask folders, or temporary SPM addresses.

## Explicit Layout Rule

This compiler never automatically redistributes a tensor.

GPDPU operators are low-level deployable kernels. If an operator needs data to
move across PE layout boundaries, that movement must appear explicitly in the
source program as `redistribute(...)` or another explicit collective/layout
operation.

Hard rules:

```text
1. Illegal shapes fail fast.
2. Legal shape with unsupported placements fails fast.
3. Matmul and pointwise ops do not silently repair layouts.
4. The compiler must not add an `auto_redistribute` option.
5. Every collective/layout movement in `plan.json` must be traceable to an
   explicit source-level operation.
```

Example:

```python
A2 = redistribute(A, placements=[Shard(0), Replicate()])
B2 = redistribute(B, placements=[Replicate(), Shard(1)])
C = A2 @ B2
```

The first `redistribute` implementation may only record intent in the graph.
Lowering that intent into COPY/COPYT, broadcast, gather, reduce, or SPM
workspace movement is a later DFU backend step.

## Compiler Dispatch Point

The compiler should align its control flow with PyTorch DTensor's eager dispatch
model.

In PyTorch DTensor, an expression such as `A @ B` immediately enters DTensor
operator dispatch:

```text
operator call
  -> unwrap args and specs
  -> sharding propagation
  -> optional explicit/runtime redistribute in PyTorch
  -> execute local tensor op on each rank
  -> wrap output DTensor
```

For GPDPU, the same source-level call point should trigger compiler dispatch,
but the "execution" is symbolic:

```text
operator call
  -> validate shape/dtype/layout contract
  -> create output DTensor spec
  -> register graph node
  -> symbolically execute across the 4x4 PE mesh
  -> append PE-local logical actions
  -> return output DTensor
```

So `A @ B` should be the place where the compiler discovers:

```text
PE(i,j):
  local_matmul(A shard visible to PE(i,j), B shard visible to PE(i,j))
    -> C shard owned by PE(i,j)
```

and `relu(C)` should similarly append:

```text
PE(i,j):
  local_relu(C shard owned by PE(i,j)) -> Y shard owned by PE(i,j)
```

The first concrete trace format is:

```text
local_values:
  LocalValue objects describing each PE-visible tensor shard, including
  local_shape and global_offset.

pe_programs:
  One PEProgram per PE. Each PEProgram owns an ordered list of PELogicalAction
  objects created at operator dispatch time.
```

`env.generate(...)` must not invent these high-level semantics later. It should
only finalize and lower what compiler dispatch has already produced:

```text
PE-local logical actions
  -> tile action expansion
  -> dependency and collective-bundle validation
  -> BSP/subtask packing
  -> resource-aware scheduling
  -> plan.json / CSV / runtime package
```

This keeps the mental model aligned with PyTorch:

```text
PyTorch DTensor dispatch executes local tensor ops immediately.
GPDPU compiler dispatch symbolically executes PE-local logical ops immediately.
```

## API Design Notes

`OperatorEnv` is the recommended first API because it gives the compiler one
place to collect ABI declarations, tensor layout, graph construction, final
outputs, and generation options. This is close to a Flink-style operator context
while still allowing normal tensor expressions. The first version should be an
explicit script-style builder, not a decorator-based API.

The first API should support:

```text
OperatorEnv(name)
env.mesh(...)
env.input(...)
env.output(name, tensor)
env.generate(...)
env.workspace_hint(...)      # optional, later
tensor operators: @, +, -, *, /, max, relu, log2, etc.
explicit ops: matmul(A, B), maximum(A, B), reduce_max(A, dim=...)
```

Naive graph construction is preferred for the first version:

```text
Tensor objects carry a reference to their OperatorEnv.
Tensor operators fetch env from their input tensors.
Each op allocates a compiler temporary tensor.
Each op registers one graph node into env.
env keeps all tensors and nodes until generate().
```

Example:

```python
C = A @ B
Y = relu(C)
```

Can be implemented as:

```text
A.__matmul__(B):
  env = A.env
  C = env.temp(dtype=..., shape=..., placements=...)
  env.add_node("matmul", inputs=[A, B], outputs=[C])
  return C

relu(C):
  env = C.env
  Y = env.temp(dtype=C.dtype, shape=C.shape, placements=C.placements)
  env.add_node("relu", inputs=[C], outputs=[Y])
  return Y
```

This is intentionally simple. The first compiler does not need a sophisticated
context manager, ownership system, memory manager, or reference-counting model.
Intermediate tensors can be kept in the environment until `generate()` and then
discarded after the compiler emits `plan.json`.

The output boundary should be explicit. The compiler should treat
`env.output(...)` as the operator ABI:

```python
Y = relu(A @ B)
env.output("Y", Y)
env.generate(output_dir="build/gemm_relu")
```

For the first version, avoid implicit output inference from Python `return`.
Runtime packages need named output buffers, so explicit `env.output(...)` keeps
the ABI easy to inspect.

Alternative API shapes considered:

```text
decorator function:
  @operator("name")
  def op(env): ...
  Looks neat, but adds unnecessary API magic for the first version.

decorator arguments:
  @operator(... inputs=[...], outputs=[...])
  Less convenient for expressions with inferred intermediate tensors.

function annotations:
  def op(A: InputTensor(...), B: InputTensor(...)) -> OutputTensor(...):
  Nice-looking, but harder to make dynamic shape/layout declarations ergonomic.

all tensors are inputs:
  Simple on paper, but bad for fusion and temporaries because compiler-managed
  intermediates become confused with user-provided memory.
```

## Memory Model

Not every tensor is an input. Treating all tensors as user-provided memory would
make simple fusion and scheduling awkward. The compiler should distinguish:

```text
InputTensor:
  Externally supplied memory.
  Read-only from the operator's point of view.
  Materialization provides concrete SPM/runtime input address metadata.

OutputTensor:
  Externally visible memory written by the operator.
  Logical placement is inherited from the bound tensor.
  Materialization provides concrete SPM/runtime output address metadata.

TemporaryTensor:
  Compiler-managed intermediate.
  May live in PE operand slots, accumulator state, SPM workspace, or be eliminated.
  Not part of the operator ABI. The first version does not promise stable
  temporary addresses, reusable temporary buffers, or user-visible temporary
  lifetime.

Workspace:
  Compiler-allocated scratch memory in SPM/runtime package when an intermediate
  cannot remain PE-local across stages.
```

The first version should use explicit memory effects:

```text
read(InputTensor tile)
write(OutputTensor tile)
allocate TemporaryTensor / Workspace when required
free/release TemporaryTensor when its last consumer is scheduled
```

First-version ABI boundary:

```text
InputTensor is read-only.
OutputTensor is explicitly written.
TemporaryTensor is compiler-managed and not a stable external contract.
No in-place input mutation, input/output aliasing, or user-visible out= semantics.
```

Temporary allocation policy:

```text
1. Prefer PE-local operand/accumulator lifetime for short-lived temporaries.
2. If a temporary crosses a subtask boundary and cannot be kept live, store it
   into compiler-managed SPM workspace.
3. If a temporary is only used to feed one local action, eliminate it as a named
   tensor and keep it as an action edge.
4. If workspace size cannot be bounded under current tiling, report resource overflow.
```

The allocation pass should operate on semantic tile residency:

```text
TileValue / TileInstance -> TileResidency -> OperandSlot / Accumulator / SPM
```

It should not infer operand lifetime from already-expanded assembly payloads.

Therefore the operator is not simply "how to read and write all tensor memory".
It is:

```text
explicit external input/output contract
+ compiler-managed plan for intermediate data movement and workspace.
```

## Relocatable Kernel And Dynamic Shape Direction

DFU kernels have a limited form of relocatability through the instance base
address table. LD/ST instructions encode:

```text
effective_address = current_instance.base_addr[base_addr_idx] + instruction_offset
```

So the same PE instruction template can be reused across different memory
regions when:

```text
tile shape is unchanged
instruction offsets are unchanged
instance count is unchanged
only input/output/workspace base addresses change
```

This is the natural first notion of a relocatable kernel:

```text
compile once for a fixed operator shape and tiling
materialize many times with different base addresses
```

Potential dynamic-address strategy, not implemented in the first slice:

```text
OperatorTemplate:
  owns PE instruction templates and symbolic logical buffers.

MaterializationContext:
  binds logical buffers to concrete SPM/runtime base addresses.
  e.g. A_base, B_base, Y_base, workspace_base.

InstanceBaseTableBuilder:
  converts each tile stream element into base_addr[0..3].
  keeps instruction offsets unchanged.

Plan/runtime package metadata:
  records which logical buffer maps to each base_addr_idx for each subtask.
```

This means a template can remain relocatable only if all per-tile offsets stay
valid. Changing base addresses is cheap; changing shape, tile count, or
subtask/instance structure is not.

Dynamic data sizes are a different problem. They affect tile counts, instance
counts, subtask packing, resource usage, and sometimes instruction templates.
The first version should not solve fully dynamic shapes.

Mature systems use several related strategies:

```text
specialization / recompile:
  Generate a program for one concrete shape. If shape changes, compile or select
  another program. This is simple and often fastest for accelerators.

bounded dynamic shapes:
  Allow a dimension to vary within a static upper bound. Allocate and schedule
  for the bound, then guard/mask unused lanes or tiles.

shape buckets / optimization profiles:
  Precompile a small set of shape ranges such as small/medium/large sequence
  length. At runtime, dispatch to the matching package and optionally pad.

symbolic materialization:
  allow symbolic M/N/K at Stage 1, but specialize before Stage 2 emits plan.json.

runtime-dispatched packages:
  select a pre-materialized package based on concrete shape.
```

For DFU, the most realistic future path is:

```text
1. fixed-shape packages first.
2. shape buckets with padding/masking second.
3. bounded dynamic dimensions only when we know the worst-case resource budget.
4. full symbolic dynamic shapes only as a research direction.
```

For now:

```text
dynamic addresses: supported through materialization metadata and instance base tables.
dynamic shapes: not supported in first version; specialize or reject.
```

## Two-stage Compiler Model

The compiler should separate operator structure from concrete tensor layout and
runtime package materialization.

```text
Stage 1: Template generator compile
  operator definition
    -> operator template generator
       - input/output ABI
       - logical tensors
       - placement constraints
       - supported tiling strategy
       - per-op lowering recipes
       - required collective bundle patterns
       - temporary/workspace requirements

Stage 2: Layout/materialization compile
  operator template generator
  + concrete input/output shape/layout/address metadata
  + workspace allocation policy
    -> per-PE tile ownership
    -> per-PE tile action graph
    -> collective tile bundles
    -> BSP/subtask schedule
    -> plan.json
    -> CSV/runtime package
```

This matters because the same operator implementation may be reused across
different concrete tensor shapes and memory layouts. The template generator is
the reusable artifact; `plan.json` and runtime package are materialized for one
specific invocation.

The first compiler milestone should therefore be:

```text
operator definition
  -> template generator object
  -> materialized PE task description
```

not immediately:

```text
operator definition
  -> CSV files
```

## PE Task Description

The materialized PE task description is the first important compiler output.
It should be easy to inspect and simulator-friendly.

For each PE, it should list:

```text
PE id
owned output tiles
required input tiles
tile source:
  input SPM address
  workspace SPM address
  local producer
  collective bundle
local tile actions:
  LOAD
  COMPUTE
  COPY_IN / COPY_OUT
  REDUCE
  STORE
  RELEASE
subtask assignment
instance loop metadata
live tile/operand lifetime
temporary/workspace allocation and release
```

For collective communication, it should list bundle-level facts once:

```text
CollectiveTileBundle id
participants
source tile(s)
destination tile(s)
communication pattern
assigned BSP/subtask
```

This `plan.json` can become the bridge to a local mock simulator before we trust
CSV/runtime package generation.

## Minimal IR

Start with small dataclasses under `compiler/gpdpu_compiler/`:

```text
DeviceMesh
TensorSpec
DTensorSpec
Placement: Shard / Replicate / Partial
Tile
TileAction
CollectiveTileBundle
SubtaskPlan
```

The first target is not a full compiler framework. The target is a transparent
plan that says, for each PE:

```text
which tiles it owns
which tiles it needs
where each tile comes from
which local compute actions run
which collective tile bundles must be aligned across PEs
which BSP superstep/subtask contains each action
```

## First GEMM Strategy

Only support the current output-sharded GEMM strategy first:

```text
A[M, K]: placements = [Shard(0), Replicate()]
B[K, N]: placements = [Replicate(), Shard(1)]
C[M, N]: placements = [Shard(0), Shard(1)]
```

If inputs have legal GEMM shapes but different placements, v1 `matmul` rejects
them. The source program must use explicit `redistribute(...)` or a different
explicit collective strategy before calling `matmul`.

Lowering intent:

```text
C load/init
A row broadcast bundle
B column broadcast bundle
HMMAL local compute
C store
```

The v1 backend should use a regular SUMMA-style streaming schedule:

```text
for each k_block:
  all 16 PEs execute the same stage shape
  A fragments are shared along mesh rows
  B fragments are shared along mesh columns
  every PE runs the same local compute template with different coordinates/base addresses
```

The first implementation should prefer homogeneous PE behavior over clever
schedule search. If matrix dimensions are not multiples of the hardware tile
shape, the backend pads the internal tile grid with dummy regions. Dummy A/B
tiles map to pre-zeroed padding tile regions, dummy compute follows the same
template, and stores must only write the real output shape.

The first scheduler rule is:

```text
one BSP superstep ~= one DFU subtask
```

`CollectiveTileBundle` is atomic for a subtask:

```text
If the whole bundle fits, schedule it in the current subtask.
If any participant PE would exceed resources, postpone the whole bundle.
If a single bundle cannot fit into an empty subtask, report tile shape/resource overflow.
```

## Instruction Capability Registry

Before writing a large CSV emitter, create a capability table:

```text
logical op + dtype + tile shape -> instruction/template
```

Initial examples:

```text
fp32.add          -> FADD
fp32.mul          -> FMUL
fp32.max          -> FMAX
fp32.log2         -> FLOG2
fp16.add          -> HADD
fp16.mul          -> HMUL
fp16.max          -> HMAX
gemm.fp16         -> HMMAL template
spm_load.fp16     -> HLDT
spm_store.fp16    -> HSTT
pe_copy           -> COPYT
```

`log10(x)` should not be treated as a primitive unless we confirm one exists.
Current instruction materials show `FLOG2`, so `log10(x)` can be represented as:

```text
FLOG2(x) / log2(10)
```

For fp16 inputs, the compiler may need an fp32 intermediate path such as
`H2FP -> FLOG2 -> FP2H`, or it may keep the intermediate tensor in fp32.

## Implementation Order

1. Build IR dataclasses.
2. Build a GEMM frontend adapter from the existing examples into compiler IR.
3. Generate PE tile ownership and tile action graphs.
4. Generate `CollectiveTileBundle` for A row broadcast.
5. Implement BSP/subtask packing with atomic bundle scheduling.
6. Emit `plan.json`.
7. Compare `plan.json` against `gemm_template_fusion` notes.
8. Add an instruction capability registry.
9. Add CSV emitters for the small GEMM subset.
10. Add runtime package generation only after CSV shape is stable.

## Reference Docs

Read these first:

```text
docs_refactored/compiler/design/README.md
docs/architecture/06-gemm-template-fusion-task0-dataflow.md
docs/architecture/01-pe-mesh-and-task-model.md
docs/architecture/08-task-subtask-instance-runtime-model.md
docs/instruction-set/dfu3500-simd/OPERAND_LANE_MODEL.md
docs/instruction-set/dfu3500-simd/instruction_cards.jsonl
docs/03-csv-to-binary-pipeline.md
```

Do not load the full instruction document into context. Prefer
`instruction_cards.jsonl` for specific mnemonics, and then open the matching
section only when necessary.
