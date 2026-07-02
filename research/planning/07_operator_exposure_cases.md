# 7. Operator Exposure Cases

## Job of This Section

Use operators as model-coverage evidence.

Do not present them as ordinary benchmarks. Each operator should expose a
different programming-model surface.

## Exposure Matrix

| Operator | Exposed surface | Why it matters |
| --- | --- | --- |
| Elementwise Add/ReLU | embarrassingly parallel tile map | proves model handles the simple case without GEMM-specific machinery |
| GEMM | shard/replicate placement, A broadcast/COPYT, B readonly sharing, C partition | canonical spatial tensor compute with nontrivial visibility |
| GEMM+ReLU | tile op-chain and fusion boundary | ReLU is an independent tile op, not a hidden GEMM flag |
| Softmax | row partition, local reduce, exp/sum/div pipeline, materialization | exposes reduction and staged subtask pipeline |
| log10max | chained non-GEMM ops, global scalar/reduction, fallback collective | tests local compute plus global visibility strategy |

## GEMM

Main message:

```text
GEMM demonstrates that placement and visibility are separate: A must be made
visible across a PE group, B may be read as shared/replicated input, and C is
partitioned output.
```

Artifacts to cite:

- `gemm_template_fusion` vendor case;
- `gemm_refactored` replay and RuntimePlanImage path;
- B-line GEMM exposure notes.

## GEMM+ReLU

Main message:

```text
Fusion should appear as a tile op-chain:
gemm_tile -> relu_tile -> store_tile
```

Do not encode ReLU as an `include_relu` flag in GEMM semantics.

## Softmax

Main message:

```text
Softmax stresses staged local reductions and materialization boundaries, not
GEMM-like matrix tile ownership.
```

It is useful as the first case-authoring automation target because its graph
shape is relatively simple.

## log10max

Main message:

```text
log10max exposes the limits of local-only tile programs: global scalar
visibility and reduction/fallback strategy must be first-class.
```

This case is useful precisely because it is awkward.

## How To Write This Section

For each case:

1. Give the operator expression.
2. State the exposed model surface.
3. Show the DTensor placement / Tile Program sketch.
4. Show the generated or explained vendor surfaces.
5. State current evidence and limitations honestly.
