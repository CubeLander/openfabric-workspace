# openfabric-workspace

This workspace keeps the active OpenFabric implementation and the surrounding
research/planning material side by side.

## Layout

```text
OpenFabric/          GitHub-backed submodule with the active implementation
.codex/skills/       symlinks to the OpenFabric repo-local Codex skills
research/planning/   paper and research planning notes
research/audit/      coverage and evidence audits
```

The `OpenFabric` submodule URL remains the GitHub repository, while this local
checkout uses the original Desktop `OpenFabric` repository moved into the
workspace. It is currently pinned to the post-vendor-package cleanup line:

```text
56ed85d Add OpenFabric repo-local workflow skills
```

Use `research/` for paper/planning discussion and `OpenFabric/` for the active
implementation evidence. The checked-in SimICT vendor package has been removed
from the submodule; active source lives under `OpenFabric/openfabric/dfu3500/`.
The local untrusted assembler is retained only as a diagnostic fingerprint path.

The workspace-level `.codex/skills/` entries are symlinks into the submodule so
Codex sessions started from the workspace root can use the same OpenFabric
operator-development, delivery, and research-roadmap skills without duplicating
their contents.
