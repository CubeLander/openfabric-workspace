# Evidence Map

This file tracks local evidence that can support the OpenFabric paper.

## Core B-line Planning Evidence

### DTensor-first / Plan B

Path:

```text
OpenFabric/legacy_implementations/openfabric_bline/docs/compiler/planB.md
```

Use for:

- DTensor-first architecture;
- StreamPlan/Fiber/TemplateOp historical route;
- decision to target VendorAssemblerInputBundle instead of final binary;
- guardrails against binary-first overreach.

### Current Architecture Review

Path:

```text
OpenFabric/legacy_implementations/openfabric_bline/docs/compiler/design/bline-current-architecture-review.md
```

Use for:

- `ChipProgram -> ProcessorTileProgram -> TemplateExpansion/PhysicalProgram`
  trunk;
- Fiber as execution organization, not semantic center;
- need for physical descriptor, simulator/resource stages, and provenance.

### Tile Program Source Of Truth

Path:

```text
OpenFabric/legacy_implementations/openfabric_bline/docs/compiler/design/tile-program-as-source-of-truth.md
```

Use for:

- per-PE Tile Program;
- globally unique TileValue names;
- LogicalCollective as shared program object;
- dependency graph as derived view.

### Handwritten Operator Contract

Path:

```text
OpenFabric/legacy_implementations/openfabric_bline/docs/vendor_reference/case_authoring/handwritten-operator-contract.md
```

Use for:

- what vendor engineers hand-maintain;
- OpenFabric's first automation target;
- division between OpenFabric and vendor `common_oper/build_app`.

## Implementation / Case Evidence

### GEMM Refactored

Path:

```text
OpenFabric/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_refactored
```

Use for:

- operator-owned source surface;
- generated CSV, graph trace, input data, app config, RuntimePlanImage;
- replay comparison against vendor-visible artifacts.

Important caveat:

```text
This is case-authoring automation evidence, not the entire DTensor frontend.
```

### Legacy GEMM Template Fusion

Path:

```text
OpenFabric/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion
```

Use for:

- vendor case baseline;
- A/B/C partition and COPYT behavior;
- task/subtask/template/graph surfaces.

### B-line Operator Status

Paths:

```text
OpenFabric/legacy_implementations/openfabric_bline/HANDOFF_REPORT.md
OpenFabric/legacy_implementations/openfabric_bline/B_LINE_RELIABILITY_CHECKPOINT_2026_06_22.md
OpenFabric/legacy_implementations/openfabric_bline/B_LINE_PROGRESS_TECH_DEBT_2026_06_22.md
```

Use for:

- GEMM no-ReLU, GEMM+ReLU, log10max exposure status;
- fail-closed `runtime_ready` discipline;
- distinction between progress payloads and semantic/runtime proof.

## Report / Paper Framing Evidence

### Old Report Outline

Path:

```text
OpenFabric/legacy_implementations/openfabric_bline/report/outline.md
```

Use for:

- high-level DFU as mini distributed tensor machine framing;
- motivation and architecture language;
- suggested section flow.

### Theory Notes

Path:

```text
OpenFabric/legacy_implementations/openfabric_bline/research/theory
```

Use carefully for:

- constrained information-state transition framing;
- projection/equivalence language.

Risk:

```text
May be too abstract for the main paper unless grounded in DTensor/Tile Program.
```
