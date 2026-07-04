# Functional Probe Policy for DFU3500 Validation

Date: 2026-06-19

## Decision

Future DFU3500 validation probes should be functional operator closures, even
when they are intentionally tiny.

A probe workload is not acceptable if it only exercises package shape,
manifest layout, serializer structure, or runtime-control staging.  Those are
useful infrastructure checks, but they should not be named or treated as
operator smoke tests.

## Why

The project has already proven that structural payloads can be generated and
staged.  The remaining risk is different: whether OpenFabric-generated inputs,
current-core binary artifacts, runtime control, device execution, output
collection, and reference checking can form a real closed loop.

Vendor cases such as `softmax_1` are valuable evidence for hardware/runtime
behavior, but simply deriving from a known-runnable vendor case mostly proves
that the vendor workflow still works.  It does not prove enough about the
OpenFabric generation path.

## Probe Contract

A functional probe, no matter how small, must provide:

1. Deterministic input data.
2. Real device-side operations, not structural placeholder rows.
3. A generated or otherwise OpenFabric-owned runtime control path.
4. Output materialization into a declared runtime-visible region.
5. A deterministic reference output.
6. A checkable pass/fail result.

The probe may still use the OpenFabric old pipeline for binary generation.  In
this note, "old pipeline" means the current compiler path under
`compiler/gpdpu_compiler/core` outside the experimental `stream_compiler`
branch.  It does not mean the partner's original
`testcase/application/*` / `build_app/run_mtr.sh` workflow.

For near-term DFU3500 functional work, prefer making the current non-stream
`core` path emit real runnable rows for a small operator, then route the same
semantics through the stream compiler branch later.

## Current Classification

`log10max_single_task` in `dfu3500_partner_validation` is currently a
runtime-control / package-structure validation payload.  It is not a functional
operator smoke because the generated chip program reports structural smoke only
and marks the runtime as non-runnable.

It is still useful for validating:

- payload-local `RuntimeControlPlan`,
- generated `riscv_control.json`,
- generated RISC-V source,
- manifest guard behavior,
- arch-13 staging independence from vendor case assets.

It must not be used to decide whether log10max device semantics work.

## OpenFabric Core-Pipeline Functional Probe Direction

The next functional probes should be OpenFabric-owned cases generated through
the current OpenFabric `core` pipeline, not copied vendor success cases and not
staged through the partner's original case generator.  Suggested first probes:

1. Row-wise max:
   - use real `FMAX` and horizontal shuffle/reduction structure;
   - verify one row or a small set of rows against a reference.

2. Log10 elemental transform:
   - use `FLOG2 * log10(2)` or equivalent;
   - verify deterministic fp32 outputs within tolerance.

3. Minimal log10max closure:
   - combine clamp/log, max threshold, affine normalize, and store;
   - start with same-app redundant/SPMD strategy if that avoids unproven
     cross-task allreduce semantics.

The true allreduce design remains a later probe: local max, gather/merge,
materialize scratch, reload/broadcast, then postprocess.

## Naming Rule

Payload names and manifests must make the distinction visible:

- `structural_*` or `runtime_control_*` for infrastructure probes.
- `functional_*` for runnable operator closures.

A functional payload must not set `runtime_runnable=0` in its manifest.  If it
is blocked, it should be classified as infrastructure/structural until the
blocking reason is removed.

## Engineering Rule

Do not hide core-pipeline functional probes behind structural placeholders.
Treat them as a bridge:

```text
OpenFabric-owned probe description
  -> current core pipeline runnable artifact generation
  -> RuntimeControlPlan
  -> arch-13 execution
  -> output/reference check
```

This keeps the validation standard high while still letting the compiler
refactor progress independently.
