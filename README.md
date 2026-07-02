# openfabric-workspace

This workspace keeps the active OpenFabric implementation and the surrounding
research/planning material side by side.

## Layout

```text
OpenFabric/          local submodule pointing at ../OpenFabric
research/planning/   paper and research planning notes
research/audit/      coverage and evidence audits
```

The `OpenFabric` submodule is pinned to the local milestone commit that records
the first customer-runnable `log10max` delivery:

```text
1846dca Document log10max customer milestone
```

Use `research/` for paper/planning discussion and `OpenFabric/` for the active
implementation evidence. The implementation source of truth remains the
`simict3500final/` tree inside the submodule.
