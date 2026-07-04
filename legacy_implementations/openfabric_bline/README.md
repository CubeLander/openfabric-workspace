# Legacy OpenFabric B-line Archive

This folder archives the pre-`second_wind` OpenFabric/B-line documentation,
notes, baseline records, and vendor/reference evidence. It is preserved as
reference material, not as the active development path.

Cleanup note, 2026-07-04: the old Python compiler implementation, tests, helper
tools, validation payloads, progress payloads, historical upload bundle, and IEEE
template workspace were removed from this archive. Their useful lessons are
covered by the scoped tensor projection notes and the active OpenFabric
implementation; the Python code itself was not runnable enough to keep as a
working baseline.

The active ground-truth implementation is now:

```text
../../simict3500final
```

## Contents

```text
compiler/      old compiler notes only; Python package removed
report/        old report outline; generated progress payloads removed
research/      old research notes
docs/          archived design docs and vendor_reference evidence
notes/         archived working notes
RUNNABLE_BASELINE.md
               archived baseline note
*.md           handoff, reliability, and B-line checkpoint notes
*.sh           old remote comparison helper scripts
```

## How To Read This Folder

Use this folder to mine failed-route lessons:

```text
template/fiber abstractions
binary ABI experiments
runtime-ready gates
partner upload packaging notes
```

Do not resume development here. New work should start from the scoped tensor
projection model and the active OpenFabric implementation, then pull facts from
this archive only when they can be grounded back to real vendor case evidence.

## Current Boundary

The old B-line path tried to synthesize final vendor-like runtime packages too
early.  The new path first automates the hand-written vendor operator inputs:

```text
operator / shape / placement intent
  -> case contract
  -> PE work partition
  -> template CSV program
  -> subtask graph plan
  -> runtime control material
  -> vendor common_oper/build_app package generation
```

See:

```text
docs/vendor_reference/case_authoring/handwritten-operator-contract.md
docs/vendor_reference/case_authoring/manual-vs-generated.md
docs/vendor_reference/overview/end-to-end-flow.md
```
