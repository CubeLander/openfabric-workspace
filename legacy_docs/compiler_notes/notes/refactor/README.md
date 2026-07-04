# Refactor Notes Index

Status: legacy compiler-refactor notes

This directory keeps current compiler semantics and layering guidance. Historical
stage reports, landed RFCs, and binary/runtime-package transition notes belong
elsewhere:

- binary / runtime package evidence: `docs/compiler/binary_packaging/research_notes/`
- stable binary docs: `docs/compiler/binary_packaging/` and `docs/runtime/data/`
- old implementation reports: `compiler/notes/archive/`

The current architecture anchor has moved to the root workspace note:

```text
next_stage_refactor_direction.md
```

That note uses:

```text
Tensor
  -> StreamTensorView
  -> FiberTensorView
  -> TypedTileValue
  -> Operand
  -> Instruction / Binary
```

Older fiber-first / StreamTilePlan notes are historical precursors. They are
useful for failure lessons and vocabulary archaeology, but they are not the
starting point for new implementation.

Current starting points:

- `../../../../next_stage_refactor_direction.md`
- `../../../../docs/README.md`
- `../../../../docs/vendor-assembler-input-protocol.md`

## Active Refactor Notes

- `topology_parametric_frontend.md`
  DFU-first project boundary and frontend/backend layering principle.
- `logical-plan-naming-and-layering.md`
  Current LogicalPlan / LogicalApp / LogicalStream naming and soft-mesh ownership.
- `rfc-app-task-fusion-region-semantics.md`
  App/task/fusion-region semantic boundary, especially for staged ops.
- `rfc-soft-device-mesh-task-axis.md`
  Restricted soft task axis model and value-scope rules.

Related notes outside this directory:

- `compiler/notes/log10max/` for staged operator research.
- `../../compiler/binary_packaging/research_notes/archive/app-plan-vs-runtime-image.md`
  for compile-time app versus runtime image/package boundary.
- `../../compiler/binary_packaging/research_notes/archive/rfc-vendor-multi-app-package-semantics.md`
  for OpenFabric semantic app versus vendor package terminology.

## Archive Rule

Move a note to `compiler/notes/archive` when it is:

- a stage report,
- an implementation plan that already landed,
- a compiler-layering note superseded by a newer active refactor note,
- an exploratory note whose stable principle is captured by one of the active
  entries above.

Move binary/runtime-package notes to `docs/compiler/binary_packaging/research_notes/`,
not to this directory.
