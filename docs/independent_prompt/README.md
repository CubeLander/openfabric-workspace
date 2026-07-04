# Independent Bot Prompts

These prompts are intended for parallel Codex runs. Each prompt is scoped to a
low-coupling deliverable and should avoid touching active implementation files
unless its prompt explicitly says otherwise.

General rules for every spawned bot:

- Treat `simict3500final/` as the active source of truth.
- Treat `legacy_implementations/openfabric_bline/` as archive evidence only.
- Do not revive the old B-line final-binary generator route.
- Assume the worktree may already contain unrelated documentation edits. Do not
  revert or re-create deleted `drafts/` files.
- Prefer report-only work unless the prompt explicitly asks for code changes.
- Write results only to the file named by the prompt.
- If implementation looks necessary but the prompt is report-only, stop at a
  concrete recommendation and risk assessment.

Suggested dispatch order:

1. `01-address-slot-usage-inventory.md`
2. `02-runtime-artifact-lifecycle-audit.md`
3. `03-log10max-handoff-package-spec-audit.md`
4. `04-spm-data-generation-inventory.md`
5. `05-graph-trace-projection-inventory.md`
6. `06-gemm-address-auto-compilation-status.md`
