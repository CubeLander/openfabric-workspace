# HANDOFF 1

## Current State

- Branch: `main`.
- Active source of truth remains `simict3500final/`.
- Archive boundary remains `legacy_implementations/openfabric_bline/`; do not revive the old B-line final-binary generator as the default route.
- Current work is focused on the DFU3500/OpenFabric address model: logical tensor/dataflow identity, storage placement, stage-local tensor access, and vendor base-slot projection must be separated.
- Working tree was clean before this handoff edit. Recent implementation commits are already on `main`.

## Recent Commits To Keep

```text
fcfbb0f Bind GEMM tensor access slots
1664d49 Bind GEMM ReLU input load slots
96ea673 Model GEMM ReLU tensor access bindings
52154f1 Clarify SPM address and slot projections
```

These commits are the latest safe checkpoint for the address/slot refactor.

## What Changed In This Batch

- Added plan-level storage alias support in `common_app_builder/dtensor_plan.h`.
  - `TensorStorageAlias` lets a logical tensor name share storage with a declared tensor.
  - `storage_tensor_name_for(...)` and `tensors_share_storage(...)` make the alias relationship queryable.
- Added plan-level stage access slot binding.
  - `TensorAccessKind::{Read, Write}` records the role of a tensor access.
  - `bind_tensor_access_base_slot(...)` and `tensor_access_base_slot(...)` make vendor base-slot selection come from the plan instead of scattered literals.
  - The fallback remains the storage tensor's default `base_slot`, so existing operators are not forced to opt in immediately.
- Added common config-row helpers in `common_app_builder/vendor_instance_config.h`.
  - `vendor_set_base_row_addr_at_slot(...)`
  - `vendor_set_tensor_access_base_addr(...)`
- GEMM+ReLU now models correct logical dataflow:
  - GEMM produces logical `C`: `gemm0_matmul_output_c`.
  - ReLU reads `C` and writes public output `D`: `gemm0_output0`.
  - `C` and `D` intentionally alias the same SPM storage today.
  - This means the semantic model is `D = relu(C)`, not an in-place `C = relu(C)` fiction.
- GEMM+ReLU stage-local access slots are now plan bindings:
  - `A/Input0 Read -> slot0`
  - `B/Input1 Read -> slot1`
  - `C Read -> slot0`
  - `C Write -> slot0`
  - `D Write -> slot1`
- Plain GEMM has also moved to access-slot bindings:
  - `A/Input0 Read -> slot0`
  - `B/Input1 Read -> slot1`
  - `Output0 Read -> slot0`
  - `Output0 Write -> slot0`
- GEMM and GEMM+ReLU fiber lowering now uses tensor access helpers instead of raw default tensor slots for the covered load/store paths.
- GEMM and GEMM+ReLU config projection now writes instance base rows through tensor access bindings instead of directly assigning those covered `base_addr[0]` / `base_addr[1]` entries.
- GEMM/GEMM+ReLU address explanation dumps were adjusted so they follow access bindings rather than silently re-deriving slots from storage tensors.

## Design Point To Preserve

The correct layering is:

```text
Logical tensor/dataflow:
  C -> relu -> D

Storage placement:
  C and D may alias the same SPM storage region

Stage-local access:
  read C, write D, read A, read B, read/write output

Vendor projection:
  each stage-local tensor access maps to a vendor base slot and base row
```

Do not collapse these layers back together. In particular:

- Do not model GEMM+ReLU as “read C, write C”.
- Do not treat vendor `base_slot` as a pure tensor-global property.
- Do not let an instruction helper silently fall back to storage default slots when the operation has a clear tensor access role.
- Do not treat C/D storage aliasing as proof that C and D are the same logical tensor.

## Validation Already Run

Commands run from repo root:

```sh
cmake --build build --target refactored_replay_compare_gemm_relu
cmake --build build --target refactored_replay_compare_gemm
git diff --check
```

Observed result:

- GEMM+ReLU API trace checks passed.
- GEMM+ReLU package/support binaries matched freshly rebuilt vendor baseline.
- GEMM API trace checks passed.
- GEMM package/support binaries matched freshly rebuilt vendor baseline.
- CSV text comparison remains skipped by policy; package/support binaries and API trace are the safety rope.

Also previously in this line of work:

```sh
cmake --build build --target refactored_replay_compare_softmax
cmake --build build --target log10max_refactored_runtime_plan_executor_trace_analysis log10max_refactored_syntax
```

Those passed before the final GEMM/GEMM+ReLU slot-binding commits.

## Known Caution Points

- Subtask0 GEMM output prefill is semantically beta/output accumulator seeding. It was made an explicit `Output0 Read -> slot0` access in plain GEMM, but do not casually rename it to matmul `C` without checking the math/dataflow meaning.
- GEMM+ReLU uses logical `C` for matmul output and `D` for public output. Plain GEMM does not currently need that split.
- `TensorAccessKind` is intentionally small right now (`Read`, `Write`). If later work needs stage names, app ids, or multiple read/write slots for the same tensor in different stages, add an explicit stage/access scope instead of overloading tensor names.
- Access binding is stage-local intent. Storage alias says where bytes live. These are related but not interchangeable.
- The current access helpers are still GEMM-family local in places. They can be generalized, but only after keeping behavior comparison-backed.
- Avoid running multiple replay targets concurrently. The replay infrastructure stages under `build/refactored_replay/`; concurrent runs can produce misleading vendor build failures.

## Suggested Next Work

1. Generalize the fiber load/store access helper shape now that both GEMM and GEMM+ReLU use the same idea.
2. Look for remaining direct `spm_tensor_vendor_base_slot(...)` use in operator lowering paths and decide whether it is a true storage default or should become a tensor access binding.
3. Continue moving config projection from direct `base_addr[]` writes toward `vendor_set_tensor_access_base_addr(...)`.
4. Revisit whether `TensorAccessKind` needs a scoped access object before handling more complex fusion or multi-stage reuse.
5. After any refactor touching common builder headers, run at least:

```sh
cmake --build build --target refactored_replay_compare_gemm
cmake --build build --target refactored_replay_compare_gemm_relu
git diff --check
```

This is a good stop point. The current mainline is comparison-backed and the next machine can continue from the committed access-binding design.
