# Validation Workflows

This package contains partner/runtime validation workflows that are part of the
compiler source tree.  They are not throwaway scratch scripts.

Current workflow:

```text
dfu3500_partner_validation/
```

Purpose:

```text
OpenFabric compiler payloads
  -> partner DFU3500 / SimICT runtime package staging
  -> batch runtime validation on arch-13
```

The current DFU3500 workflow is the official successor to the old `gemmfix`
binary-diff helper directory.  Generated payload binaries live under
`dfu3500_partner_validation/payloads/` and are intentionally ignored by Git; use
`dfu3500_partner_validation/build_payloads.py` to regenerate them.
