# OpenFabric Paper Planning Room

Status: historical paper-planning room. Its evidence map is still useful, but
the headline terminology predates `../../TWO_LEVEL_DTENSOR_NOTES_CN.md`.
Future paper drafts should use scoped tensor projection language instead of
the older `DTensor + Tile Program` framing.

This directory is the internal planning room for the OpenFabric paper:

```text
OpenFabric: Scoped Tensor Projection for Spatial Accelerators
```

It is not the public paper text. Each file designs one paper section: what the
section must accomplish, what claim it should make, what evidence it needs, and
how to avoid overclaiming.

## Core Thesis

Spatial accelerator programming is fundamentally a problem of making tensor
values visible at the right processing elements under explicit resource,
routing, storage, and runtime-package constraints.

OpenFabric now frames this as scoped tensor projection:

```text
Tensor
  -> StreamTensorView
  -> FiberTensorView
  -> TypedTileValue / Operand materialization
  -> vendor-compatible case-authoring material
  -> existing assembler/runtime toolchain
```

The paper is not primarily about generating one GEMM case. GEMM, GEMM+ReLU,
softmax, log10max, and elementwise operators are exposure cases that stress
different surfaces of the model.

## Section Files

0. `00_advisor_brief_zh.md`: short advisor-facing brief.
0. `00_overall_design_report_zh.md`: longer internal design report.
1. `01_introduction.md`
2. `02_motivation.md`
3. `03_programming_model.md`
4. `04_openfabric_design.md`
5. `05_lowering_and_implementation.md`
6. `06_evaluation.md`
7. `07_operator_exposure_cases.md`
8. `08_discussion.md`
9. `09_related_work.md`
10. `10_conclusion.md`
11. `evidence_map.md`: local evidence inventory and source-of-truth map.

The publication roadmap is tracked separately:

```text
../roadmap/openfabric-publication-roadmap.md
```

## Paper Boundary

OpenFabric studies a programming model and compiler architecture for spatial
accelerators. The current DFU3500/vendor flow is the strongest implementation
and validation target, not the conceptual boundary.

Do not frame the paper as:

```text
We built a GEMM generator.
We replaced the vendor assembler.
We proved a fully generic compiler for all accelerators.
```

Frame it as:

```text
We identify scoped tensor projection as the right semantic layer for spatial
accelerator operators: tensor truth is projected through stream/fiber execution
scopes before tile values are materialized into target operands. We show that
this layer can be lowered into real vendor-compatible operator surfaces across
several exposure cases.
```
