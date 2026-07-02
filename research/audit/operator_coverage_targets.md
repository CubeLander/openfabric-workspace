# Operator Coverage Targets

Status: planning audit for paper evidence and future OpenFabric development.

This document turns the operator coverage ambition into reviewable targets.
The paper can use these targets to argue for a DTensor programming model for
spatial accelerators, while development can use them as a backlog for filling
coverage gaps.

## Claim Boundary

Do not claim:

```text
OpenFabric already supports all PyTorch operators end to end.
```

Claim:

```text
OpenFabric identifies the spatial lowering patterns behind broad PyTorch-style
operator families, validates representative exposure cases, and keeps explicit
capability gaps for future implementation.
```

The key paper object is not a long operator list. It is a coverage envelope:

```text
DTensor placement
  + Tile Program
  + LogicalCollective / visibility
  + storage/runtime materialization
  + vendor-compatible lowering
```

## Evidence Levels

Use these labels consistently in paper text, planning docs, and future audits.

| Level | Meaning |
| --- | --- |
| `E2E_REPLAY` | Generated/refactored path is compared against vendor-visible package/support artifacts. |
| `RUNTIME_TRACE` | RuntimePlanImage/API/common executor traces exist and are comparable. |
| `PACKAGE_SCAFFOLD` | Case/package material exists but is not full runtime/numerical proof. |
| `STRUCTURAL_PLAN` | DTensor/Tile/graph/runtime intent is explicit and inspectable. |
| `DESIGN_ONLY` | Coverage argument exists, but implementation evidence is not yet sufficient. |
| `NOT_COVERED` | Outside the current envelope; must not be claimed as supported. |

## Strong Paper Combination

The strongest near-term paper story should combine:

| Case | Role in the paper | Desired evidence |
| --- | --- | --- |
| GEMM | compute-heavy spatial tiling, shard/replicate placement, A broadcast/COPYT, B sharing, C partition | `E2E_REPLAY` |
| GEMM+ReLU | fusion as tile op-chain, not an epilogue flag | `E2E_REPLAY` or `RUNTIME_TRACE` |
| Softmax | row-wise reduce, staged scratch/materialization, normalize/store | `E2E_REPLAY` or `RUNTIME_TRACE` |
| log10max | chained non-GEMM ops plus global scalar/reduction visibility | `PACKAGE_SCAFFOLD` now, improve toward `RUNTIME_TRACE` |
| Broadcast/reduce microcases | NoC-first LogicalCollective exposure independent of GEMM | add `STRUCTURAL_PLAN`, then package/run evidence |
| Attention design case | Torch-level composite: GEMM + softmax + GEMM + lifetime/materialization | `DESIGN_ONLY` first, then structural plan |
| Conv2d virtual im2col | layout/gather/materialization boundary | `DESIGN_ONLY`; keep direct gather unclaimed |

## Pattern Coverage Matrix

| Pattern | Torch-style operator families | Spatial difficulty exposed | Current evidence target |
| --- | --- | --- | --- |
| PE-local map | ReLU, Add, Mul, GELU approximation, epilogues | tile-local vector op, storage aliasing, tail/dtype policy | GEMM+ReLU plus standalone pointwise target |
| Tile contraction | matmul, linear, batched GEMM | shard/replicate placement, tile accumulation, task/PE ownership | GEMM |
| Row-wise reduce | softmax, layernorm, RMSNorm, row max/sum | scratch lifetime, reduce-store, staged materialization | Softmax, future norm |
| Global scalar/reduce | max, arg-free global max, log10max components | global visibility, scalar fanout, runtime ordering | log10max |
| Explicit collective | broadcast, reduce, allreduce, reduce-scatter-like patterns | NoC route topology, graph edges, participant roles | new microcases |
| Materialized composite | attention, MLP block fragments | lifetime across op chain, intermediate storage/materialization | attention design case |
| Layout/gather transform | conv2d im2col, transpose-like movement, slice/concat | virtual gather, contiguous tile materialization, nonlocal access | conv2d virtual im2col design |

## Operator Target Backlog

### P0: Paper-Critical Exposure Cases

These are the minimum targets for a strong programming-model paper.

1. **GEMM**
   - Evidence goal: `E2E_REPLAY`.
   - Must show: A visibility/broadcast, B read sharing, C partition/store,
     RuntimePlanImage or equivalent runtime material.
   - Existing lead: `gemm_refactored`.

2. **GEMM+ReLU**
   - Evidence goal: `E2E_REPLAY` or at least `RUNTIME_TRACE`.
   - Must show: `gemm_tile -> relu_tile -> store_tile`.
   - Guardrail: no `include_relu`-style fused semantic flag as the model
     authority.

3. **Softmax**
   - Evidence goal: `E2E_REPLAY` or `RUNTIME_TRACE`.
   - Must show: row-wise partition, reduction scratch, normalization pipeline,
     materialization boundaries.

4. **log10max / global scalar**
   - Evidence goal: upgrade from `PACKAGE_SCAFFOLD` toward `RUNTIME_TRACE`.
   - Must show: local chain plus global scalar visibility/fanout.
   - Guardrail: do not label PE00 materialized scalar as direct physical
     allreduce unless route evidence exists.

5. **NoC-first microcases**
   - Evidence goal: `STRUCTURAL_PLAN` first, then package evidence.
   - Suggested cases:
     - row broadcast;
     - column broadcast;
     - scalar reduce-to-one;
     - scalar broadcast-from-one;
     - ring or tree allreduce sketch.
   - Must show: LogicalCollective participants, local roles, graph/dependency
     projection, and target route/COPY/COPYT intent.

### P1: Torch-Level Coverage Expansion

These strengthen the claim that the model can approach PyTorch-level operator
families.

1. **Standalone pointwise**
   - Operators: add, multiply, relu, clamp, simple affine.
   - Purpose: prove the model is not overbuilt for GEMM.
   - Evidence goal: `STRUCTURAL_PLAN`, then package.

2. **Norm family**
   - Operators: layernorm, RMSNorm.
   - Purpose: row-wise reduce plus scale/bias views.
   - Evidence goal: `STRUCTURAL_PLAN`.

3. **Attention design case**
   - Operators: materialized attention path.
   - Purpose: composite graph made from GEMM, softmax, GEMM, and explicit
     lifetime/materialization.
   - Evidence goal: `DESIGN_ONLY` to `STRUCTURAL_PLAN`.

4. **Conv2d virtual im2col**
   - Purpose: expose layout transform and gather/materialization boundary.
   - Evidence goal: `DESIGN_ONLY`.
   - Guardrail: direct arbitrary gather remains unclaimed.

### P2: Explicitly Not Yet Covered

These should remain outside the main claim until target evidence and capability
checks exist.

| Family | Why not yet covered |
| --- | --- |
| Arbitrary gather/scatter | Nonlocal addressing and irregular materialization not proven. |
| Per-lane predication | Tail/lane mask semantics need target evidence. |
| Scan/prefix operators | Ordering and carried-state semantics not covered by current reduce model. |
| Arg/value pair reductions | Requires paired value/index lifetime and compare-select evidence. |
| True atomic updates | Requires target atomic semantics or serialized update proof. |
| Cross-task collective inside one app | Needs route/runtime ordering proof beyond current envelope. |

## Development Rule

When adding a target, update this audit with:

```text
operator / family
pattern category
current evidence level
source paths
generated artifacts
known unsupported semantics
next evidence upgrade
```

Do not move an operator to a stronger evidence level because a placeholder,
debug row, package shell, or design note exists. Evidence must be source-backed
and auditable.

## Paper Wording

Recommended wording:

```text
We select exposure cases that stress distinct spatial-programming surfaces:
tile contraction, PE-local map, staged row reduction, global scalar visibility,
and NoC-mediated collectives. Together, they define a coverage envelope for
DTensor-style programming on spatial accelerators.
```

Avoid:

```text
OpenFabric supports PyTorch operators.
```

Use instead:

```text
OpenFabric provides a path toward Torch-level operator coverage by identifying
the spatial lowering patterns shared by broad operator families.
```
