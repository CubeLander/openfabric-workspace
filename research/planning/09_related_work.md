# 9. Related Work

## Job of This Section

Position OpenFabric among programming models, tensor compilers, distributed
tensor systems, and spatial accelerator toolchains.

## Buckets

### DTensor and distributed tensor programming

Compare on:

- mesh and placement semantics;
- shard/replicate/partial concepts;
- collectives and redistribution.

Distinction:

```text
OpenFabric adapts DTensor semantics inside one spatial accelerator, where
placement movement lowers to explicit PE/tile/route/runtime artifacts.
```

### Tensor compilers

Likely systems:

- TVM;
- MLIR/IREE;
- XLA;
- Triton;
- Halide-style scheduling.

Distinction:

```text
OpenFabric's key object is not only loop/tile scheduling, but explicit
TileValue visibility across a PE mesh and projection into vendor case-authoring
surfaces.
```

### Spatial accelerator programming models

Likely systems:

- systolic array compilers;
- CGRA/spatial mapping systems;
- dataflow accelerators;
- TT-Metal-style tile programming.

Distinction:

```text
OpenFabric emphasizes DTensor placement and vendor-compatible case generation
for an existing closed/runtime-backed spatial accelerator.
```

### Vendor SDK and case-authoring workflows

Discuss vendor-provided flows as the practical baseline:

- handwritten case config;
- template emitters;
- graph plugins;
- runtime control programs;
- assembler/packer.

OpenFabric automates the handwritten operator surface while preserving the
assembler path.

## Related Work Risk

Do not overstate novelty as "first DTensor for accelerators" unless the survey
supports it. Safer claim:

```text
OpenFabric brings DTensor-style placement and visibility into a practical
case-authoring compiler path for spatial accelerators.
```
