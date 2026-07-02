# 6. Evaluation

## Job of This Section

Evaluate the programming model, not just the implementation.

Every result should answer:

```text
Does OpenFabric's DTensor model expose the right semantic surfaces and lower
them into vendor-compatible artifacts across diverse spatial operators?
```

## Evaluation Thesis

The evaluation should establish:

```text
OpenFabric covers multiple spatial-operator exposure surfaces with one DTensor
and Tile Program model, while reducing handwritten vendor case surface and
preserving auditable lowering provenance.
```

## Evaluation Questions

### EQ1: Expressiveness Across Exposure Surfaces

Question:

```text
Can the model represent the key placement, visibility, tile, and runtime
surfaces of several different operator families?
```

Report per operator:

- placement pattern;
- tile action chain;
- logical collective / visibility needs;
- storage and runtime materialization needs;
- vendor surfaces generated or explained.

### EQ2: Handwritten Surface Reduction

Question:

```text
How much case-authoring material moves from scattered handwritten files to
OpenFabric plans/generators?
```

Metrics:

- number of handwritten source files removed or centralized;
- generated files by category;
- lines/files in maintained source vs vendor generated artifacts;
- number of duplicated task/subtask/template surfaces eliminated.

### EQ3: Vendor Compatibility

Question:

```text
Can OpenFabric-generated or replayed case material continue through the existing
vendor assembler/package flow?
```

Evidence:

- build/package success;
- CBUF/MICC package comparison where available;
- graph plugin compatibility;
- runtime control trace comparison;
- SimICT/runtime execution when available.

### EQ4: Provenance and Debuggability

Question:

```text
Can high-level DTensor/TileAction decisions be traced to generated template,
graph, and runtime artifacts?
```

Evidence:

- provenance manifest examples;
- one tile value drill-down;
- one collective/route drill-down;
- one runtime-control action drill-down.

### EQ5: Exposure-Case Coverage

Question:

```text
Do the chosen operators demonstrate distinct model surfaces rather than many
variants of the same GEMM path?
```

Use `07_operator_exposure_cases.md` as the evaluation matrix.

## Baselines

Compare against workflows:

1. Handwritten vendor case authoring.
2. Binary-first reverse engineering / direct byte emission.
3. Per-operator ad hoc generator.

The comparison should emphasize maintainability, semantic clarity, provenance,
and compatibility, not only runtime speed.

## Risks

- If no operator reaches vendor package/run status, evaluation becomes too
  aspirational.
- If only GEMM has strong equivalence data, reviewers may see the model as
  GEMM-specific.
- If metrics only count files/LOC, the paper may look like refactoring rather
  than programming-model work.
