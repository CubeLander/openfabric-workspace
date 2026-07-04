# Agent Notes

## Current Ground Truth

This branch is intentionally centered on OpenFabric-owned DFU3500 sources:

```text
openfabric/dfu3500/
```

The checked-in SimICT vendor package has been removed.  Treat customer-side
SimICT runs, approved operator snapshots, and checked package artifacts as the
execution evidence.  The repo-local untrusted assembler is only a diagnostic
fingerprint path:

```text
openfabric/dfu3500/toolchain/untrusted_assembler/
```

## Archive Boundary

Everything outside the clean SimICT starting point has been archived under:

```text
legacy_implementations/openfabric_bline/
```

That archive includes the old compiler, tests, tools, reports, docs, notes,
materials, paper drafts, and baseline records.  It is useful evidence, but it is
not the active implementation path.

Useful archived references:

```text
legacy_implementations/openfabric_bline/README.md
legacy_implementations/openfabric_bline/docs/vendor_reference/case_authoring/handwritten-operator-contract.md
legacy_implementations/openfabric_bline/docs/vendor_reference/case_authoring/manual-vs-generated.md
legacy_implementations/openfabric_bline/RUNNABLE_BASELINE.md
```

The first live `second_wind` doc is:

```text
docs/handwritten-operator-contract.md
docs/vendor-assembler-input-protocol.md
```

## Work Rule

Do not revive the old B-line final-binary generator as the default route.
OpenFabric should now grow bottom-up:

```text
vendor runnable case
  -> hand-written operator contract
  -> manifest / checker
  -> local generator for vendor inputs
  -> common_oper/build_app package generation
```

Keep new changes grounded in customer-side execution evidence, approved
operator snapshots, or repo-local untrusted-assembler fingerprints unless the
user explicitly asks to mine or restore something from the archive.
