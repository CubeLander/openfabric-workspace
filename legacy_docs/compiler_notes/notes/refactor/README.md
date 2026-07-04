# Refactor Notes Index

Status: active compiler-refactor entrypoint

This directory keeps current compiler semantics and layering guidance. Historical
stage reports, landed RFCs, and binary/runtime-package transition notes belong
elsewhere:

- binary / runtime package evidence: `docs/compiler/binary_packaging/research_notes/`
- stable binary docs: `docs/compiler/binary_packaging/` and `docs/runtime/data/`
- old implementation reports: `compiler/notes/archive/`

The current tile-layer design anchor is fiber-first:

```text
stream-visible shard
  -> tile-level DTensor partitioning
  -> fragment spaces
  -> fiber access relations
  -> deterministic fiber schedule
  -> materialized StreamTilePlan actions
```

Do not use archived tile-action-first notes as the starting point for new
`core/stream_compiler` work. Start from:

- `compiler/notes/enhancements/2026-06-18_fiber_first_stream_tile_design.md`
- `docs/compiler/binary_packaging/research_notes/enhancements/pro-fiber-comments.md`
- `docs/compiler/binary_packaging/research_notes/enhancements/rfc-stream-tile-plan-flat-lowering.md`

## Active Refactor Notes

- `topology_parametric_frontend.md`
  DFU-first project boundary and frontend/backend layering principle.
- `logical-plan-naming-and-layering.md`
  Current LogicalPlan / LogicalApp / LogicalStream naming and soft-mesh ownership.
- `rfc-app-task-fusion-region-semantics.md`
  App/task/fusion-region semantic boundary, especially for staged ops.
- `rfc-soft-device-mesh-task-axis.md`
  Restricted soft task axis model and value-scope rules.
- `rfc-op-lowering-spec-strangler.md`
  Incremental op spec strategy; keep specs declarative and pass-owned IR intact.

Related notes outside this directory:

- `compiler/notes/log10max/` for staged operator research.
- `docs/compiler/binary_packaging/research_notes/archive/app-plan-vs-runtime-image.md`
  for compile-time app versus runtime image/package boundary.
- `docs/compiler/binary_packaging/research_notes/archive/rfc-vendor-multi-app-package-semantics.md`
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
