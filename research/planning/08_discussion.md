# 8. Discussion

## Job of This Section

Clarify boundaries, limitations, and broader implications without weakening the
main claim.

## Topics To Cover

### Why DTensor for spatial accelerators?

DTensor is useful because it names placement and visibility. OpenFabric does not
inherit PyTorch runtime assumptions; it borrows the semantic idea and adapts it
to static operator compilation.

### Why not replace the vendor assembler first?

The assembler encodes many target facts: operand allocation, pseudo-op
expansion, COPY/COPYT endpoint patching, and binary serialization. Replacing it
first risks losing a validated backend path. OpenFabric targets the human
case-authoring surface first.

### What is portable?

Portable:

- tensor shape/dtype/placement model;
- TileValue naming;
- logical collective;
- tile action dependency view;
- provenance discipline.

Target-specific:

- PE count/capacity;
- task/subtask/instance packaging;
- CSV instruction vocabulary;
- graph plugin ABI;
- runtime control API;
- binary package format.

### What remains hard?

- automatic collective strategy selection;
- resource-legal packing under tight instruction/operand limits;
- performance modeling;
- numerical validation across all generated cases;
- multi-target backend abstraction after DFU3500.

## Anti-Overclaiming Paragraph

The paper should include a clear sentence:

```text
OpenFabric does not claim to be a complete optimizing compiler for all spatial
accelerators. It demonstrates that DTensor placement and tile-value visibility
form a practical semantic layer, and that this layer can drive real
vendor-compatible operator surfaces.
```
