# openfabric-workspace

This workspace keeps the active OpenFabric implementation and the remaining
research/evidence material side by side.

## Layout

```text
OpenFabric/          GitHub-backed submodule with the active implementation
.codex/skills/       symlinks to the OpenFabric repo-local Codex skills
docs/                current workspace-level design and hardware evidence
research/            remaining research notes and target scouts
legacy_docs/         extracted old B-line documents kept for evidence mining
legacy_implementations/
                     archived B-line implementation and evidence
```

## Current Design North Star

The current workspace-level design direction is `Scoped Tensor Projection`,
recorded in:

```text
next_stage_refactor_direction.md
SCOPED_TENSOR_PROJECTION_CLEANUP_AUDIT_CN.md
```

Use `next_stage_refactor_direction.md` as the highest-level naming guidance. Older
`DTensor`, `Tile Program`, `TileValue`, and `ProcessorTileProgram` language in
research or legacy documents should be treated as historical unless it is
explicitly reconciled with:

```text
Tensor
  -> StreamTensorView
  -> FiberTensorView
  -> TypedTileValue
  -> Operand
```

The `OpenFabric` submodule URL remains the GitHub repository, while this local
checkout uses the original Desktop `OpenFabric` repository moved into the
workspace. It is currently pinned to the refreshed log10max-fp32 approved
snapshot line:

```text
1d7e936 updated log10max snapshot
```

Use `research/` only for remaining research notes and target scouting.
Use `OpenFabric/` for active implementation evidence. The checked-in SimICT
vendor package has been removed from the submodule; active source lives under
`OpenFabric/openfabric/dfu3500/`. The local untrusted assembler is retained
only as a diagnostic fingerprint path.

The workspace-level `.codex/skills/` entries are symlinks into the submodule so
Codex sessions started from the workspace root can use the same OpenFabric
operator-development, delivery, and research-roadmap skills without duplicating
their contents.
