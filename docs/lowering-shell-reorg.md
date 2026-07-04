# DFU3500 Lowering Shell Reorganization

Date: 2026-07-03

This repository now makes the OpenFabric-owned DFU3500 lowering sources visible
outside the customer SimICT testcase shell:

```text
openfabric/dfu3500/
  support/
    common_app_builder/        # OpenFabric common lowering/runtime support
    legacy_graph_compat/       # vendor graph-hook ABI compatibility only
    customer_abi.h             # copied customer ABI facts for config rows
    write_file.*               # local writer for OpenFabric lowering outputs
  operators/
    gemm/
    gemm_relu/
    softmax/
    log10max-fp32/
  probes/
    hldt_hstt_probe/
    ildmt_probe/
  toolchain/
    untrusted_assembler/       # local diagnostic fingerprint path only
```

The checked-in vendor SimICT tree has been removed.  Customer-side SimICT is
still the authoritative execution substrate, but repo-local source now lives
under `openfabric/dfu3500/`.

## Default Lowering Flow

The root CMake build enters `openfabric/dfu3500` directly.  The primary local
targets are still:

```sh
cmake --build build-lowering-reorg --target \
  gemm_refactored_syntax \
  gemm_relu_refactored_syntax \
  softmax_refactored_syntax \
  log10max_refactored_syntax \
  hldt_hstt_probe_config \
  ildmt_probe_config
```

These targets compile OpenFabric operator/probe generators from
`openfabric/dfu3500`, generate lowering bundles, run RuntimePlanImage trace
checks where available, and write
`openfabric_lowering_bundle_manifest.json` beside each generated bundle.

`support/customer_abi.h` is a copied customer ABI contract, not a hardware
model.  It carries only the config-row facts needed by current lowering code:
`instance_conf_info_t`, `MAX_INSTANCES_PER_SUBTASK`,
`MAX_BASE_ADDR_PER_SUBTASK`, `MAX_SUBTASK_PER_TASK`, and `DMA_BAND_WIDTH`.
The default generator compile path uses this shim plus `support/write_file.*`
instead of depending on `testcase/common_oper/write_file.cpp`, `pe_com_def.h`,
or `dma_com_def.h`.

## Customer Package Flow

Customer package generation still stages a vendor-shaped bundle because the
customer simulator and toolchain are the authoritative execution surface.
For log10max-fp32:

```sh
cmake --build build-lowering-reorg --target log10max_delivery_package
```

This emits:

```text
build-lowering-reorg/customer_delivery/log10max-fp32.tar.gz
```

The package `run.sh` keeps the established customer defaults:

```text
SIMICT_ROOT=/project/home-new/huake02/simict3500final
VENDOR_TOOLCHAIN_HOME=/project/home-new/huake01
```

The package can still be overridden with environment variables or a
`SIMICT_ROOT` argument.

## Legacy Diagnostic Flow

The local assembler remains untrusted as semantic truth.  It is still useful as
a hash/checksum machine for regression alarms, so the repository keeps only the
extracted assembler/toolchain pieces under:

```text
openfabric/dfu3500/toolchain/untrusted_assembler/
```

Legacy repo-local vendor baseline replay (`tools/vendor_case` and
`refactored_replay_*`) has been removed with the checked-in vendor package.
Current local drift checks should be operator-owned snapshots or package
fingerprints, not reconstructed vendor baseline cases.

The graph hook files that include `graph_extend.h` and `inst_block_gen.h` live
under `openfabric/dfu3500/support/legacy_graph_compat/` and are not part of the
default lowering compile closure.  Package/replay flows copy them only when the
customer `libsubtask.so` compatibility ABI is needed.

## Approved Operator Snapshots

An operator may keep an approved snapshot under its own source tree:

```text
openfabric/dfu3500/operators/<op>/snapshots/approved/<case>/
```

The snapshot stores the customer-approved operator package plus file-level
manifests and diagnostic fingerprints.  It does not store assembler rebuild
outputs or scratch result trees.  The local assembler fingerprint is only a
drift alarm for a previously approved point; a matching fingerprint does not
prove customer-side semantic correctness.

For `log10max-fp32`, the current approved snapshot is:

```sh
cmake --build build --target log10max_approved_snapshot_test
```

That target regenerates the package and local diagnostic probe, then compares
their manifests against:

```text
openfabric/dfu3500/operators/log10max-fp32/snapshots/approved/default/
```

Updating a snapshot is intentionally explicit:

```sh
cmake --build build --target log10max_approve_snapshot
```

Only run the approve target after a fresh customer-side PASS.  Normal tests
should use the read-only snapshot test target.

## Acceptance Policy

CSV files are lowering inputs and debug artifacts.  They are not the default
acceptance gate.

Prefer, in order:

- customer-side simulator/toolchain run summaries and checker output;
- runtime/package/support binary hashes;
- generated lowering bundle manifests;
- local assembler hashes only as diagnostic regression alarms.

Hash stability from the local assembler does not prove customer-side semantic
correctness.
