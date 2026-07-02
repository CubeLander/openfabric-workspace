# 1. Introduction

## Job of This Section

Make reviewers see spatial accelerator programming as a distributed tensor
visibility problem, not as a pile of vendor CSV files or a one-off GEMM backend.

The introduction should move from:

```text
spatial accelerators are powerful but hard to program
```

to:

```text
the missing abstraction is a DTensor-like programming model that keeps tensor
placement and visibility explicit while lowering to PE/tile/runtime packages.
```

## Opening Hook

Possible opening:

```text
Spatial accelerators expose abundant parallel compute, but their operator
programs are often authored through low-level artifacts: per-PE instruction
templates, task/subtask tables, graph hooks, memory base tables, and runtime
control programs. These artifacts describe not just computation, but where
tensor values live, where they become visible, and when hardware resources can
fire.
```

Then sharpen:

```text
The hard part is not writing one matrix instruction. The hard part is making
the right tensor tile visible at the right PE under explicit resource and
routing constraints.
```

## Mental Model Shift

Use this contrast:

```text
Handwritten vendor case:
  files encode placement, visibility, graph, runtime, and package details.

OpenFabric:
  DTensor placements and tile programs encode semantics;
  backend lowering projects them into vendor-compatible case material.
```

## Contributions

Recommended contribution wording:

1. We propose a DTensor programming model for spatial accelerators, where
   tensor placement, explicit storage boundaries, and logical collectives are
   first-class programming concepts.
2. We introduce Tile Program as the semantic bridge from DTensor values to
   PE-local execution, using globally named TileValues and shared
   LogicalCollective objects.
3. We design a vendor-compatible lowering path that targets case-authoring
   material rather than prematurely replacing the vendor assembler.
4. We validate the model through exposure cases that stress different surfaces:
   GEMM, GEMM+ReLU, softmax, log10max, and elementwise operators.

## Reviewer Preemption

Anticipated attacks:

- "Is this just a GEMM generator?"
  Answer: no; GEMM is one exposure case. The programming model is evaluated by
  how it covers distinct placement, fusion, reduction, collective, and
  materialization surfaces.

- "Why not just use MLIR/TVM/Triton?"
  Answer: these systems do not directly model this vendor flow's explicit
  PE/tile visibility, graph plugin, task/subtask/instance, and runtime package
  surfaces. Related work can compare abstraction level and backend contract.

- "Do you replace the vendor compiler?"
  Answer: deliberately no. The first implementation target is the manually
  authored operator case surface, which is then consumed by the existing
  assembler/packer.
