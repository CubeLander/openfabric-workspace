# openfabric-workspace

This workspace keeps the active OpenFabric implementation and the surrounding
research/planning material side by side.

## Layout

```text
OpenFabric/          GitHub-backed submodule with the active implementation
.codex/skills/       symlinks to the OpenFabric repo-local Codex skills
research/planning/   paper and research planning notes
research/audit/      coverage and evidence audits
docs/                current workspace-level design and hardware evidence
drafts/              unfinished design discussions
legacy_implementations/
                     archived B-line implementation and evidence
```

## Current Design North Star

The current workspace-level design direction is `Scoped Tensor Projection`,
recorded in:

```text
TWO_LEVEL_DTENSOR_NOTES_CN.md
SCOPED_TENSOR_PROJECTION_CLEANUP_AUDIT_CN.md
OPENFABRIC_IDEAL_ABSTRACTION_NOTES_CN.md
LOGICAL_TILE_MATERIALIZED_OPERAND_MODEL.md
```

Use `TWO_LEVEL_DTENSOR_NOTES_CN.md` as the highest-level naming guidance. Older
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

Use `research/` for paper/planning discussion and `OpenFabric/` for the active
implementation evidence. The checked-in SimICT vendor package has been removed
from the submodule; active source lives under `OpenFabric/openfabric/dfu3500/`.
The local untrusted assembler is retained only as a diagnostic fingerprint path.

The workspace-level `.codex/skills/` entries are symlinks into the submodule so
Codex sessions started from the workspace root can use the same OpenFabric
operator-development, delivery, and research-roadmap skills without duplicating
their contents.
