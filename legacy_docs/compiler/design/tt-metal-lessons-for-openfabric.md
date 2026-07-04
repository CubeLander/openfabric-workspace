# TT-Metal Lessons For OpenFabric

Status: investigation note
Date: 2026-06-23
Source: local checkout at `tmp/tt-metal`

## Summary

TT-Metal and OpenFabric are solving the same class of problem:

```text
high-level tensor intent
  -> explicit tensor layout / placement / memory contract
  -> tiled local execution
  -> explicit data movement and synchronization
  -> device program / binary artifacts
  -> traceable runtime execution
```

The useful lesson is not to copy TT-Metal's API. Its hardware, kernel language,
and multi-device runtime are Tenstorrent-specific. The useful lesson is how it
keeps the stack inspectable:

- TTNN owns high-level tensor operations and operation lifecycle.
- Metalium owns low-level programs, kernels, circular buffers, semaphores, and
  runtime args.
- Program descriptors provide a structured, cacheable physical program shape.
- Tensor specs make layout, memory, and topology part of the contract.
- Tracing/model-tracing capture real operation configurations and runtime facts.

For OpenFabric, this supports the current direction: flat IR, explicit lowering
passes, provenance, fail-closed target evidence, and no op-time mutation across
compiler layers.

## What TT-Metal Gets Right

### 1. Operation Lifecycle Is Explicit

TTNN device operations commonly define:

```text
operation_attributes_t
tensor_args_t
validate_on_program_cache_miss()
compute_output_specs()
compute_output_topologies()      optional
create_output_tensors()
compute_program_hash()
select_program_factory()
```

Representative files:

- `ttnn/cpp/ttnn/operations/matmul/device/matmul_device_operation.hpp`
- `ttnn/cpp/ttnn/operations/experimental/deepseek_prefill/offset_cumsum/device/offset_cumsum_device_operation.hpp`
- `ttnn/api/ttnn/device_operation.hpp`

OpenFabric should adopt the shape of this contract, not the C++ template
machinery. Each OpenFabric op spec should separate:

```text
semantic validation
output SRAM/DTensor spec computation
placement/topology computation
lowering strategy selection
program/cache identity
```

This maps cleanly onto current `op_specs` and B-line pass boundaries.

### 2. TensorSpec Is A Contract, Not A Convenience

TT-Metal's tensor model separates:

```text
logical shape
data type
page layout: row-major / tile
tile shape and face layout
memory config: DRAM / L1, interleaved / sharded
topology / mesh placement
computed padded and physical shape
```

Representative files:

- `tech_reports/tensor_layouts/tensor_layouts.md`
- `tt_metal/api/tt-metalium/experimental/tensor/spec/tensor_spec.hpp`
- `tt_metal/api/tt-metalium/experimental/tensor/spec/layout/tensor_layout.hpp`

OpenFabric currently has SRAM tensor declarations and DTensor placements, but
B-line would benefit from a stricter intermediate `TensorSpec`-like object at
each lowering boundary:

```text
ChipTensorSpec
ProcessorTensorSpec
TileFragmentSpec
TemplateOperandSpec
VendorBufferSpec
```

Each spec should include shape, dtype, address-space or region, tile/page
layout, placement/topology, and physical size/capacity facts.

### 3. Low-Level Program Shape Is Structured

Metalium `ProgramDescriptor` captures low-level program structure without
immediately becoming opaque bytes:

```text
ProgramDescriptor
  kernels[]
    source
    core ranges
    compile-time args
    runtime args
    buffer bindings
    reader/writer/compute config
  cbs[]
    total size
    core ranges
    buffer index
    data format
    page size
  semaphores[]
```

Representative file:

- `tt_metal/api/tt-metalium/program_descriptors.hpp`

This is a strong model for OpenFabric's post-template layer. Instead of jumping
directly from `FiberOp` or `TemplateOp` into vendor rows/components, OpenFabric
should preserve a structured physical-program product:

```text
DfuTemplateExpansion
  -> DfuPhysicalProgramDescriptor
       instruction spans
       operand buffers
       route resources
       synchronization resources
       runtime patch points
       provenance to FiberOp / TileAction
  -> vendor component rows
```

This would make B-line binary/debug artifacts easier to review and hash.

### 4. Cache Keys Exclude Patchable Runtime Values

TT-Metal program descriptors track buffer/runtime-arg bindings so cache hits can
patch buffer addresses without rebuilding the whole program. The structural hash
is separate from dispatch-time values.

Representative files:

- `ttnn/api/ttnn/device_operation.hpp`
- `tt_metal/api/tt-metalium/program_descriptors.hpp`

OpenFabric should use the same idea for vendor rows and SimICT bundles:

```text
structural identity:
  op kind, tile shape, template kind, row skeleton, resource shape

runtime patch values:
  SRAM offsets, package ids, buffer base addresses, scalar constants when safe
```

This would prevent the current exact-row/hash work from mixing "same executable
shape" with "same concrete runtime binding".

### 5. Data Movement Is First-Class

Metalium's normal low-level pattern is reader kernel, compute kernel, writer
kernel, coordinated by circular buffers. The docs explicitly teach data movement
and compute as separate concurrent components.

Representative file:

- `METALIUM_GUIDE.md`

OpenFabric should keep moving in the same direction:

```text
TileRouteAction / load visibility
  -> TileComputeAction
  -> TileStoreAction
```

and later:

```text
FiberOp(route/materialize)
FiberOp(compute)
FiberOp(store)
TemplateExpansion(...)
```

Do not collapse these back into fused GEMM flags or hidden physical row
mutation.

### 6. Mesh And Collective APIs Are Explicit

TTNN models multi-device work with:

```text
MeshDevice
TensorTopology
cluster_axis
topology: ring / linear / fabric
num_links
semaphores / barrier semaphores
CCL op as a device operation
```

Representative files:

- `tech_reports/Programming_Mesh_of_Devices/Programming_Mesh_of_Devices_with_TT-NN.md`
- `ttnn/cpp/ttnn/operations/ccl/README.md`
- `ttnn/cpp/ttnn/operations/ccl/all_gather/device/all_gather_device_operation.hpp`
- `ttnn/cpp/ttnn/operations/ccl/reduce_scatter/device/reduce_scatter_device_operation.hpp`

OpenFabric should not add premature multi-backend support, but it should make
collective semantics first-class in DFU3500 terms:

```text
CollectiveAction(kind=reduce_max, axis=task/mesh axis)
  -> Dfu3500CollectiveStrategy
  -> route/resource plan
  -> physical rows / runtime package
```

This is especially relevant for log10max. A direct PE00 bridge can remain a
delivery tactic, but the semantic source should be a collective action.

### 7. Tracing Is A Product Feature

TT-Metal captures graph/runtime facts through GraphProcessor, Inspector, model
tracer, and operation-parameter JSON files. It records shapes, dtypes, layouts,
storage, memory config, tensor placement, mesh shape, source test, and machine
info.

Representative files:

- `ttnn/core/graph/graph_processor.cpp`
- `ttnn/api/ttnn/graph/graph_processor.hpp`
- `model_tracer/README.md`

OpenFabric should treat compiler/runtime observability as a first-class output:

```text
compile trace:
  all IR products, schema versions, provenance edges, diagnostics

runtime/package trace:
  package components, sizes, hashes, patch points, validation gates

customer/debug trace:
  minimal reproducible operator config, chip config, SRAM regions, tensor specs
```

This is the fastest path to making B-line cooperation less fragile.

## What Not To Copy

Do not copy TT-Metal's user API shape. TTNN is a Python/C++ tensor library with
eager device execution. OpenFabric is currently a DFU-first compiler for
customer DFU/SimICT/GPDPU workflows.

Do not copy broad multi-device abstractions yet. Keep current hardware facts in
`core/dfu3500` until a real second chip/backend exists.

Do not copy TTNN's fused matmul activation style into B-line semantics. TTNN has
files such as fused matmul/bias/activation kernels because it is optimizing a
mature runtime. OpenFabric's current rule is first-class tile op chains:

```text
gemm_tile -> relu_tile -> store_tile
```

Do not make low-level program factories semantic authority. TT-Metal has many
specialized program factories. OpenFabric should keep specialized DFU3500
template/physical code downstream of semantic IR.

## Recommended OpenFabric Actions

### Short Term

1. Add `TensorSpec`-style records to B-line boundary docs before implementing a
   new generic class.
2. Split B-line package boundaries as described in
   `bline-organization-rfc.md`.
3. Add a structural-vs-runtime identity rule to exact template/hash reports.
4. Add import-boundary checks so semantic IR cannot depend on artifact writers.
5. Keep `StreamPlan`, `Fiber`, `Executable`, `Schedule`, `TemplateOp`, and
   `BinaryLayout` as flat records with stable ids and provenance.

### Medium Term

1. Introduce `DfuPhysicalProgramDescriptor` between `TemplateOpPlan` and vendor
   component rows.
2. Give route, buffer, semaphore/sync, and runtime patch-point rows explicit
   records, mirroring the useful parts of `ProgramDescriptor`.
3. Promote collective actions to first-class B-line IR and lower them through
   DFU3500 strategy reports.
4. Build a B-line trace export that captures operator config, tensor specs,
   every IR product, package hashes, and validation blockers.

### Long Term

1. Convert demo-only B-line input construction into a real
   `ProcessorTileProgram -> BLineStreamProgram` pass.
2. Treat model/customer traces as test vectors, not just debug dumps.
3. Add a program cache/replay model once structural program identity is stable.

## Bottom Line

TT-Metal shows that a hardware-specific tensor compiler/runtime can scale if
each layer has a narrow contract:

```text
TensorSpec
  -> DeviceOperation lifecycle
  -> ProgramFactory / ProgramDescriptor
  -> Program cache / runtime patching
  -> Trace and model-derived test vectors
```

OpenFabric should adapt that lesson as:

```text
ChipProgram / DTensor
  -> ProcessorTileProgram with op chains
  -> B-line flat IR products
  -> DFU3500 template/physical descriptors
  -> vendor components
  -> validation and trace artifacts
```

This reinforces the existing OpenFabric direction rather than replacing it.
