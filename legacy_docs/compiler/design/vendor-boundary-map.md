# Vendor Boundary Annotation Map

This note marks the current boundary between portable compiler logic and
target/vendor-specific implementation details. It is intentionally an
annotation map, not a refactor plan: while binary output is being closed, files
should stay where they are unless a move is needed for the checkpoint.

## Why This Boundary Exists

OpenFabric currently has two product directions:

```text
portable operator generation
  fast path to CANN/CUDA-style generated kernels or vendor libraries

odd hardware backend generation
  full lowering to special targets such as legacy DFU/customer hardware
```

The first path needs clean semantic and scheduling facts without inheriting DFU
runtime-table assumptions. The second path needs enough freedom to encode
private instruction formats, runtime package files, graph ABIs, and simulator
components.

## Marker Vocabulary

Use these labels in docs and short file comments when touching boundary code:

```text
PORTABLE_BOUNDARY: core_ir
  Target-independent compiler facts. CANN/CUDA backends may consume this.

ARCH_BOUNDARY: backend_extension
  Explicit backend interface or backend implementation entrypoint.

VENDOR_BOUNDARY: legacy_dfu
  Legacy DFU / customer-hardware implementation detail.

TRANSITION_DEBT: vendor_in_core_until_binary_checkpoint
  Vendor-specific file still living under core during binary-output closure.

REVIEW_SURFACE: mixed_boundary
  File is useful today but mixes portable and vendor concerns.
```

These markers have no runtime effect. They are there so code review can ask the
right question: "is this portable compiler state, or is this a target contract?"

## Import Direction

Desired long-term direction:

```text
frontend ops / DTensor graph
  -> portable tile and graph IR
  -> architecture backend interface
  -> backend-owned symbolic assembly
  -> backend-owned binary / runtime package emission
```

Rules for new code:

```text
portable core must not import dfu_vendor_* directly
portable core must not depend on legacy_dfu fields
backend/vendor layers may consume portable plan layers
binary serializers stay behind backend-owned boundaries
env.py is allowed to violate this temporarily as the orchestration spine
```

## File Classification

### Portable compiler core

These files should remain backend-independent, or converge in that direction:

```text
compiler/gpdpu_compiler/core/_api.py
compiler/gpdpu_compiler/core/_dtensor_spec.py
compiler/gpdpu_compiler/core/device_mesh.py
compiler/gpdpu_compiler/core/placement_types.py
compiler/gpdpu_compiler/core/chip_logical_program.py
compiler/gpdpu_compiler/core/pe_trace.py
compiler/gpdpu_compiler/core/route_lowering.py
compiler/gpdpu_compiler/core/tile_dependency_network.py
compiler/gpdpu_compiler/core/dfu_graph.py
compiler/gpdpu_compiler/core/dfu_packing.py
compiler/gpdpu_compiler/core/dfu_residency.py
compiler/gpdpu_compiler/core/dfu_storage_binding.py
compiler/gpdpu_compiler/core/dfu_runtime_frame.py
compiler/gpdpu_compiler/core/dfu_assembly_attachment.py
compiler/gpdpu_compiler/core/dfu_base_table.py
```

Notes:

```text
pe_trace.py is mostly portable Tile Program, but current PE naming and tile
  sizes still reflect the active 4x4 target.
route_lowering.py is portable symbolic routing, but current route heuristics
  are tuned for the active mesh topology.
dfu_* graph/packing/runtime-frame files are portable in intent, but their names
  still carry the current DFU checkpoint history.
```

### Frontend operator layer

```text
compiler/gpdpu_compiler/ops.py
```

This layer should express semantic operator intent: matmul, elementwise,
reduction, conv2d, storage, and placement facts. It should not grow DFU runtime
package fields. Supported-layout checks are acceptable when they protect the
current lowerer, but the checks should be phrased as compiler support limits,
not vendor ABI constraints.

### Architecture extension point

```text
compiler/gpdpu_compiler/arch/base.py
compiler/gpdpu_compiler/arch/__init__.py
compiler/gpdpu_compiler/arch/legacy_dfu.py
compiler/gpdpu_compiler/core/architecture_backend.py
```

`arch/base.py` is the intended backend interface. `arch/legacy_dfu.py` is the
current target implementation. `core/architecture_backend.py` is a compatibility
shim and should not collect new target logic.

### Legacy DFU vendor ABI temporarily in core

These files are target/vendor specific, even though they still live under
`core` during binary-output closure:

```text
compiler/gpdpu_compiler/core/dfu_vendor_package.py
compiler/gpdpu_compiler/core/dfu_vendor_blob_schema.py
compiler/gpdpu_compiler/core/dfu_vendor_aligned_packing.py
compiler/gpdpu_compiler/core/dfu_vendor_exeblock.py
compiler/gpdpu_compiler/core/dfu_vendor_instance.py
compiler/gpdpu_compiler/core/dfu_vendor_base_addr.py
compiler/gpdpu_compiler/core/dfu_vendor_instruction_offset.py
compiler/gpdpu_compiler/core/dfu_vendor_offset_field.py
compiler/gpdpu_compiler/core/dfu_vendor_instruction_folding.py
compiler/gpdpu_compiler/core/dfu_vendor_instruction_range.py
compiler/gpdpu_compiler/core/dfu_vendor_noncompute_range.py
compiler/gpdpu_compiler/core/dfu_vendor_concrete_base_addr.py
compiler/gpdpu_compiler/core/dfu_vendor_graph_abi.py
compiler/gpdpu_compiler/core/dfu_vendor_instance_conf_serializer.py
compiler/gpdpu_compiler/core/dfu_vendor_task_conf_serializer.py
compiler/gpdpu_compiler/core/dfu_vendor_subtask_conf_serializer.py
compiler/gpdpu_compiler/core/dfu_vendor_exeblock_conf_serializer.py
compiler/gpdpu_compiler/core/dfu_vendor_simulator_bundle.py
compiler/gpdpu_compiler/core/dfu_vendor_component_file_writer.py
```

These files may consume portable plan layers, symbolic assembly, base table
facts, residency, and packing. Portable core files should not consume their
output except through explicit orchestration and debug surfaces.

### Mixed review surfaces

```text
compiler/gpdpu_compiler/core/env.py
compiler/gpdpu_compiler/core/debug_dump.py
compiler/gpdpu_compiler/core/plan_validator.py
```

Current status:

```text
env.py imports and sequences every portable and vendor pass.
debug_dump.py knows the full layer list, including vendor layers.
plan_validator.py validates both portable invariants and vendor ABI invariants.
```

These are acceptable while closing the object-generation checkpoint. Later they
should become thin dispatchers over per-backend registration, backend-owned
debug layers, and backend-owned validators.

### Examples and tests

```text
compiler/examples/gemm_relu.py
compiler/examples/log10_maximum.py
compiler/examples/conv2d.py
tests/test_log10_maximum_lowering.py
tests/test_conv2d_lowering.py
tests/test_tile_dependency_network.py
tests/test_dfu_assembly_invariants.py
```

Operator examples are semantic workloads, not vendor ABI examples. Tests that
assert `dfu_vendor_*` fields are legacy-DFU backend tests even if they currently
sit beside portable lowering tests.

## Adding a CANN/CUDA Path

A CANN/CUDA backend should consume the frontend graph and as much portable
tiling/scheduling information as is useful. It should not depend on:

```text
legacy_dfu instruction roles
dfu_vendor_* runtime tables
exeBlock_conf_info_t / instance_conf_info_t / task_conf_info_t records
base_addr slot semantics
simulator_bin component filenames
```

Likely split target:

```text
gpdpu_compiler.backends.cuda
gpdpu_compiler.backends.cann
```

Those backends can lower to generated CUDA/CANN source, library calls, or
backend-native graph APIs without inheriting the current legacy DFU ABI.

## Adding an Odd-Hardware Backend

A special hardware backend should follow the legacy DFU shape but own its
private ABI explicitly:

```text
consume portable tile/graph/runtime-frame facts
emit backend symbolic assembly records
keep binary serializers and runtime files backend-owned
expose debug metadata without leaking private bit encodings unnecessarily
```

Likely split target:

```text
gpdpu_compiler.backends.legacy_dfu
gpdpu_compiler.backends.<customer_or_arch>
```

## Known Transitional Debt

```text
TRANSITION_DEBT: vendor_in_core_until_binary_checkpoint
  dfu_vendor_* files live under core because the current priority is producing
  the simulator/object component files end to end.

REVIEW_SURFACE: mixed_boundary
  env.py, debug_dump.py, and plan_validator.py mix portable and vendor layers.

PORTABLE_BOUNDARY drift
  Some portable-intent modules still use dfu_* naming because they were born
  from the first target. Prefer adding target-neutral fields before renaming.
```

The split should happen after the binary/assembly checkpoint has a stable
surface. Until then, annotate aggressively and avoid adding new vendor facts to
operator semantics or portable graph IR.
