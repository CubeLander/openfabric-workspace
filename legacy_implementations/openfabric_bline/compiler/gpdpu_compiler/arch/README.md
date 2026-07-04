# Architecture Backends

This package contains target-owned backend code.

The compiler core should remain device-independent:

```text
DTensor graph
  -> PE logical actions
  -> TileScope / K_TILE_STEP timeline
  -> visibility and route obligations
```

Architecture packages own hardware-specific lowering:

```text
semantic tile / route actions
  -> architecture symbolic records
  -> architecture binary encoders
  -> runtime-package details
```

For now, the backend lives directly in this repository for speed of development:

```text
gpdpu_compiler.arch.legacy_dfu
```

Later, this directory is the intended split point for private or dynamically
loaded backends. That matters because future customers may not be able to expose
instruction encodings, route protocols, or runtime package details in an open
compiler repository.

Rules:

1. Keep vendor/ISA/runtime-package details in `arch`, not `core`.
2. Keep `core` data structures generic enough for other mesh/tensor backends.
3. Keep binary encoders behind architecture-owned interfaces.
4. Use structured symbolic records before binary encoding so private backends
   remain debuggable without leaking unnecessary hardware details.

Current annotation policy:

```text
PORTABLE_BOUNDARY: core_ir
ARCH_BOUNDARY: backend_extension
VENDOR_BOUNDARY: legacy_dfu
TRANSITION_DEBT: vendor_in_core_until_binary_checkpoint
REVIEW_SURFACE: mixed_boundary
```

The detailed file map lives in
`docs/compiler/design/vendor-boundary-map.md`. During the binary-output
checkpoint, some legacy DFU ABI files still live under `core`; mark those sites
rather than moving them until the emitted component surface is stable.
