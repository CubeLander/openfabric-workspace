# Address Binding Projections

Status: current design note for the active `simict3500final` refactored
operators.

OpenFabric address binding is not a separate source of truth. It is the typed
projection that connects an operator tensor access to the target-visible SPM and
vendor address forms consumed by runtime DMA, instance base rows, and CSV memory
references.

The current code keeps the authority chain deliberately small:

```text
TensorAccessRef
  -> TensorAccessSpmBinding
  -> RuntimeSpmWindowProjection
  -> StageBaseRowProjection
  -> TileMemoryAccess
```

For GEMM-family cases there is one extra mental model: vendor addressing is
split. A logical tile address is not written as one absolute number. The target
combines a stage-visible base row with an instruction-local offset:

```text
logical tile/window placement
  -> base contribution written into instance_conf_info.base_addr[slot]
  -> instruction contribution written as CSV immediate/lane offset
  -> effective address at execution
```

OpenFabric should therefore model placement and visibility first, then project
them into base slots and CSV fields. Base slots are limited target resources;
they are not tensor identity.

## TensorAccessSpmBinding

`TensorAccessSpmBinding` binds a logical access, such as `read(A)` or
`write(C)`, to:

- the storage tensor that actually owns SPM memory;
- the tensor memory base;
- the vendor base slot used by CSV and instance config.

This is where aliases such as GEMM+ReLU's matmul output `C` and final output
`Y` become explicit. The access remains semantic, but the memory binding resolves
through the storage tensor.

## RuntimeSpmWindowProjection

`RuntimeSpmWindowProjection` describes the runtime app window in which an access
is visible to DMA and kernel launch code.

For current GEMM-family cases, the rule is:

```text
window_index = runtime_app_id % 2
spm_byte_addr = tensor_access_spm_base + window_index * ping_pong_stride_bytes
```

For current single-app softmax and log10max, the projection is static:

```text
window_index = 0
spm_byte_addr = tensor_access_spm_base
```

This projection owns the ping-pong runtime-window fact. It should feed runtime
DMA transfer construction. It is not high-level operator IR; it is target
runtime lowering.

## StageBaseRowProjection

`StageBaseRowProjection` describes which access bases are visible inside a
device stage instance. It is the OpenFabric-side explanation for a vendor
`instance_conf_info_t.base_addr[0..3]` row.

For current GEMM:

- subtask0 binds output `C` read/prefill;
- subtask1 binds input `A` and `B` reads, with K-instance offsets;
- subtask2 binds output `C` write/store.

For GEMM+ReLU, the ReLU stage binds a read access and a write access that may
share storage while still occupying distinct vendor base slots.

For softmax and log10max, the default plan-to-base-row projection binds ordinary
input/scratch reads and output writes from the `DistributedPlan` tensor memory
table, including the existing statement-index stride used by the vendor
instance config.

This projection should feed vendor instance row writers and address explanation
checks. It should not own runtime app ping-pong policy; that belongs to
`RuntimeSpmWindowProjection`.

## TileMemoryAccess

`TileMemoryAccess` is the CSV memory-reference projection for one lane of a
tile. It carries:

- access name and storage tensor;
- base slot;
- tile offset;
- lane offset;
- final CSV immediate offset;
- register offset.

This lets CSV HLDT/HSTT rows, stage base-row explanation, and runtime window
explanation talk about the same access binding instead of each recomputing slot
and address meaning separately.

## Memory Visibility

Runtime materialization establishes when a tensor access window is visible in
SPM. Stage base rows and CSV memory refs consume that visibility during kernel
execution. These two sides should be tied by the same access binding:

```text
Runtime action plan materializes read(A) for runtime_app
  -> RuntimeSpmWindowProjection gives the SPM window
  -> StageBaseRowProjection binds read(A) for a stage instance
  -> TileMemoryAccess emits lane/local CSV fields for the tile
```

For current GEMM, this explains why ping-pong runtime DMA and subtask base rows
must stay coordinated without making GEMM own generic materialization rules.
For softmax/log10max, the same projection chain degenerates to static SPM
windows.

## Boundary

These projections are intentionally small. They do not allocate memory, schedule
apps, infer graph dependencies, or replace the operator plan. They make existing
vendor-visible address facts explicit and checkable while preserving the
comparison-backed route:

```text
operator plan facts
  -> access binding projections
  -> vendor compatibility rows / runtime actions / CSV memory refs
  -> replay compare against runnable vendor cases
```

Debug dumps are useful while extracting a projection, but they are not a
long-term source of truth. Keep the lasting contract in typed projections and
comparison gates.
