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
OpenFabric/openfabric/dfu3500/operators/gemm
```

Use for:

- operator-owned source surface;
- generated CSV, graph trace, input data, app config, RuntimePlanImage;
- replay comparison against vendor-visible artifacts.

Important caveat:

```text
This is case-authoring automation evidence, not the entire DTensor frontend.
```

### log10max Customer Milestone

Path:

```text
OpenFabric/openfabric/dfu3500/operators/log10max-fp32
OpenFabric/build/customer_delivery/log10max-fp32.tar.gz
OpenFabric/openfabric/dfu3500/operators/log10max-fp32/snapshots/approved/default/log10max-fp32.tar.gz
OpenFabric/README.md
```

Key commits:

```text
1846dca Document log10max customer milestone
47bcfb4 renamed log10max
1d7e936 updated log10max snapshot
```

Use for:

- first customer-runnable OpenFabric-generated operator package;
- non-GEMM exposure case;
- chained local tile work plus global scalar visibility;
- flat SPM layout and subtask-local tensor access slot policy;
- customer-side numerical checker evidence with `mismatch_count = 0`;
- checked approved snapshot package and diagnostic fingerprint gate.

Important caveat:

```text
The current package is valid delivery evidence, but the global scalar path
should still be upgraded into an explicit LogicalCollective plan before the
paper claims full collective lowering.
```

### Legacy GEMM Template Fusion

Path:

```text
OpenFabric/docs/handwritten-operator-contract.md
OpenFabric/docs/vendor-workflow-evidence/
OpenFabric/legacy_implementations/openfabric_bline/RUNNABLE_BASELINE.md
```

Use for:

- archived vendor case baseline evidence;
- A/B/C partition and COPYT behavior;
- task/subtask/template/graph surfaces.

Important caveat:

```text
The checked-in SimICT vendor package has been removed. Treat this as evidence
and workflow context, not as an active source path.
```

### Tenstorrent Portability Scout

Path:

```text
research/targets/tenstorrent-portability-scout.md
```

External anchors:

```text
https://docs.tenstorrent.com/tt-metal/latest/tt-metalium/index.html
https://docs.tenstorrent.com/tt-metal/latest/ttnn/ttnn/tensor.html
https://github.com/tenstorrent/ttsim
```

Use for:

- second-target roadmap;
- mapping OpenFabric mesh/tile/storage/collective concepts onto a public
  tile/NoC accelerator software stack;
- motivating a simulator-backed portability microcase.

Important caveat:

```text
This is currently a scout and target hypothesis, not implementation evidence.
Do not claim Tenstorrent support until a public TT-Metalium/TT-NN artifact runs
through simulator or device validation.
```

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
