# SPM Plan Refactor Plan

Status: useful engineering plan, but terminology predates
`TWO_LEVEL_DTENSOR_NOTES_CN.md`.

Terminology note: `DTensor` in this file should generally be read as `Tensor`
truth plus `StreamTensorView` / `FiberTensorView` projections. The SPM
base/slot distinction remains valid; the naming should be migrated during the
next rewrite.

This note tracks the current bad smells around OpenFabric SPM layout and
DFU3500 instance base slots. The goal is to make plan-level tensor placement
flat and inspectable, while keeping target-specific base-slot assignment in the
DFU lowering layer.

## Target Model

Plan-level tensor layout should be plain:

```text
DTensor -> physical_spm_byte_base + byte_size + dtype + sharding
```

Operator code should access tensor tiles through DTensor semantics. It should
not manually add hidden region offsets, and it should not choose DFU
`base_addr[0..3]` slots.

DFU lowering should translate the plan into each subtask/instance row:

```text
instance_conf.base_addr[auto_slot] = tensor.physical_spm_base
instruction.imm = tile_offset_inside_tensor
```

SPM overlap should be diagnosed as a warning, not a hard error. Some operators
will intentionally reuse SPM across non-overlapping lifetimes. Warnings should
make accidental overlap visible, and later lifetime annotations can suppress
expected reuse.

## Bad Smells

- Hidden region offsets in operator code.
  - Example: `kLog10maxLocalMaxRegionOffset` and
    `kLog10maxGlobalClipRegionOffset` made physical layout invisible to the
    plan and caused `GLOBAL_CLIP_FLOOR` to overwrite the middle of
    `LOG10_STAGE`.

- Tensor-owned DFU base slots.
  - `TensorMemory` currently stores both physical base and `base_slot`.
  - The physical tensor layout belongs in the plan. DFU base slots are a
    lowering decision for each subtask/instance/access set.

- Manual base-slot parameters in operator sources.
  - Helpers such as `tile_lane_mem_ref_with_base_slot` let operator code bypass
    `TensorAccessRef` and make instance-slot assignment hard to audit.

- Placement without diagnostics.
  - `SpmPlacementTable::apply_to()` currently assigns tensor bases but does not
    emit a layout report or overlap warnings.

- Summary scratch encoded through stride tricks and ad hoc offsets.
  - Summary tensors should still be ordinary DTensors with flat physical bases.
    Their sharding/stride should describe tile indexing only, not hidden arena
    placement.

## Repair Order

1. Remove log10max region offsets.
   - Give `LOG10_STAGE`, `LOCAL_LOG10_MAX`, and `GLOBAL_CLIP_FLOOR` flat,
     non-overlapping physical byte bases.
   - Make log10max CSV emission and instance rows use per-subtask automatic
     slot assignment.
   - Verify package generation and inspect generated CSV/base rows.
   - Status: done for the current log10max implementation.

2. Add warning-only layout diagnostics.
   - Emit a plan layout report with tensor byte ranges.
   - Warn on overlap unless the overlap is explicitly marked as planned reuse.
   - Do not fail generation for overlap yet.
   - Status: initial warning-only diagnostics are in `SpmPlacementTable::apply_to()`.

3. Move DFU slot assignment into common lowering.
   - Build a common per-subtask slot allocator from the tensor accesses used by
     that subtask.
   - Generate instance rows from that allocator.
   - Make CSV emission query the allocator instead of tensor-owned slots.
   - Status: `TensorAccessSlotPolicy` now owns per-subtask access-to-slot
     assignment. log10max, GEMM, and GEMM+ReLU query that policy for CSV memory
     selectors and instance-row bindings.

4. Remove manual base-slot APIs from operator-facing code.
   - Keep target-internal helpers if needed, but route operator loads/stores
     through `TensorAccessRef` or DTensor tile references.
   - Update GEMM and GEMM+ReLU after log10max is stable.
   - Status: done for log10max, GEMM, and GEMM+ReLU operator sources through
     `TensorAccessSlotPolicy`.

5. Revisit `TensorMemory`.
   - Split physical placement from DFU base-slot selection.
   - Keep compatibility shims while GEMM/softmax are being migrated.
   - Status: still open. `TensorMemory` still carries compatibility base-slot
     state even though covered operator lowering now queries access-slot policy.

## Validation Checklist

- `log10max_refactored_config_generator_analysis` builds.
- Generated log10max address projection shows flat tensor byte ranges.
- Generated instance rows bind only tensors used by each subtask.
- `log10max_delivery_package` builds.
- GEMM and GEMM+ReLU config-generation targets still build before common slot
  migration starts.
- `TensorAccessSlotPolicy` is the only operator-facing path for per-subtask DFU
  base-slot lookup in log10max, GEMM, and GEMM+ReLU.
