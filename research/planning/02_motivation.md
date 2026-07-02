# 2. Motivation

## Job of This Section

Show why spatial accelerator operator development needs a programming model
above vendor case artifacts.

The section should use concrete vendor-flow evidence but avoid getting lost in
file names. The reader should leave believing:

```text
These artifacts are symptoms of missing tensor placement and visibility
abstractions.
```

## Motivation Case Shape

Use two running examples:

1. GEMM, because it exposes shard/replicate placement and cross-PE A-tile
   visibility.
2. Softmax or log10max, because it proves the problem is not GEMM-only.

## Current Workflow

Summarize the handwritten workflow:

```text
operator intent
  -> hand-maintained case contract
  -> hand-maintained PE map and memory layout
  -> template C/C++ emits per-PE CSV
  -> graph hook encodes subtask dataflow
  -> runtime control program stages data and launches kernels
  -> vendor common_oper/build_app assembles package
```

The problem is not that each file exists. The problem is that semantic facts are
split across them:

- tensor ownership is in config headers;
- PE visibility is in template code and graph hooks;
- runtime materialization is in control code;
- final operand/resource assignment happens later in vendor assembler.

## Why Existing Abstractions Are Not Enough

The section should distinguish OpenFabric from:

- library-call programming, which hides too much and cannot expose case
  authoring surfaces;
- per-PE instruction programming, which exposes too much and duplicates
  placement logic;
- graph-only IR, which captures dependencies but not tile residency and value
  visibility as first-class programming objects;
- binary-first reverse engineering, which attacks the wrong layer first.

## Key Motivating Observation

```text
Spatial accelerator programming is a visibility problem over distributed tensor
tiles. Computation, routing, graph dependency, and runtime staging are all
different projections of this visibility problem.
```

## Evidence To Use

Local source references:

- `OpenFabric/legacy_implementations/openfabric_bline/docs/vendor_reference/case_authoring/handwritten-operator-contract.md`
- `OpenFabric/legacy_implementations/openfabric_bline/docs/compiler/design/tile-program-as-source-of-truth.md`
- `OpenFabric/legacy_implementations/openfabric_bline/docs/compiler/planB.md`
- `OpenFabric/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_refactored/README.md`
