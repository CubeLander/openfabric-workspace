# 5. Lowering and Implementation

## Job of This Section

Show how the model becomes real artifacts.

This is where the paper can use concrete DFU3500/vendor workflow details, but
the text must keep the layered story:

```text
DTensor model -> Tile Program -> vendor-compatible case material
```

## Lowering Pipeline

Recommended subsection order:

1. Chip-level operator and storage boundary.
2. Placement to PE work ownership.
3. Tile action construction.
4. Logical collective and visibility lowering.
5. Task/subtask/instance and graph planning.
6. Template CSV and graph plugin generation.
7. Runtime control material.
8. Vendor assembler invocation and package validation.

## VendorAssemblerInputBundle

Make this a named artifact:

```text
VendorAssemblerInputBundle:
  CaseConfigPlan
  MemoryLayoutPlan
  PEWorkPartition
  TemplateCsvProgram
  SubtaskGraphPlan
  GraphPluginBuildPlan
  RuntimeControlPlan
  CaseDataPlan
  ProvenanceManifest
```

This artifact is the contract between OpenFabric and the existing vendor
assembler/packer.

## Current Implementation Evidence

Use `gemm_refactored` carefully:

```text
gemm_refactored demonstrates that operator-owned source can generate the
vendor-visible GEMM surfaces: CSV streams, graph trace, app config, input data,
and RuntimePlanImage control material, while replay checks package equivalence.
```

But say explicitly:

```text
gemm_refactored is evidence for the case-authoring automation path, not the full
DTensor frontend.
```

## Provenance

Every lowering artifact should carry source identity:

```text
source operator
source placement
source TileAction
source LogicalCollective
source template op
source graph node
source runtime action
```

This supports debugging and reviewer confidence.

## Validation Contracts

Separate validation levels:

- structural plan validity;
- generated case material validity;
- vendor assembler/package success;
- binary/package equivalence where applicable;
- runtime execution;
- numerical correctness.

Do not collapse them into one `works` claim.
