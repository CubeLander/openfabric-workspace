# Legacy OpenFabric B-line Archive

This folder archives the pre-`second_wind` OpenFabric/B-line implementation,
documentation, notes, materials, papers, baseline records, and validation
artifacts.  It is preserved as reference material, not as the active
development path.

The active ground-truth implementation is now:

```text
../../simict3500final
```

## Contents

```text
compiler/      old OpenFabric/B-line compiler package, tools, validation payloads
tests/         tests for the archived compiler path
tools/         extraction/OCR helper tools from the old repo layout
report/        old report drafts and B-line progress payload notes
research/      old research notes
docs/          archived design docs and vendor_reference evidence
notes/         archived working notes
materials/     archived original/reference materials
IEEE_Conference_Template/
               archived paper draft workspace
RUNNABLE_BASELINE.md
               archived baseline note
*.md           handoff, reliability, and B-line checkpoint notes
*.tgz          old upload/validation bundle
*.sh           old remote comparison helper scripts
```

## How To Read This Folder

Use this folder to mine failed-route lessons:

```text
template/fiber abstractions
binary ABI experiments
runtime-ready gates
validation scripts
partner upload packaging
```

Do not resume development here by default.  New work should start from the
vendor case authoring contract and the runnable `simict3500final` cases, then
pull ideas from this archive only when they can be grounded back to real vendor
case evidence.

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
