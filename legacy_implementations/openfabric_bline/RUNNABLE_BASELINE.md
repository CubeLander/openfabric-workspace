# Runnable Baseline: GEMM on DFU3500 / SimICT

This file is an archive marker for the first OpenFabric-generated GEMM image
that successfully runs to completion in the vendor DFU3500 / SimICT workflow.
Treat this baseline as a resurrection point and a behavioral guardrail for
future refactors.

## Status

```text
status: runnable baseline accepted
case: gemm_template_fusion
vendor workflow: run_app_riscv.sh gemm_template_fusion 4
verified on: huake02@arch-13
recorded date: 2026-06-18
```

The OpenFabric image is not byte-identical to the vendor original, but it is now
accepted by the vendor runtime and runs to completion.  Remaining byte diffs are
no longer the primary correctness target unless they are tied to a functional
failure.

## Git Pointer

```text
branch: main
baseline_head: ffd5b27ec658e6c07b0f257c38fb852562061d41
baseline_tag: baseline/gemm-runnable-2026-06-18
original_generator_head: f94409fc103fc854ce5e7fa4738f4b765110b8df
```

Important nuance: the runnable payload was first generated from
`original_generator_head`, then archived under `baseline_head` together with the
formal `dfu3500_partner_validation` workflow. If resurrecting this state later,
use the baseline tag first, then inspect
`compiler/gpdpu_compiler/validation/dfu3500_partner_validation/sha256.txt` and
this document to restore the exact validation package.

## Artifact Fingerprints

Current OpenFabric payload in `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/payloads/gemm_template_fusion/result/`:

```text
cbuf_file.bin  23531520 bytes  sha256=809a447dec84db46026c8ffc6dada8aff0b5644dc57362d88d8823e29c2e2506
micc_file.bin   8522976 bytes  sha256=ab56e64bff6f0d9b469146ef04d4584c2597f4bcbb1b951d49c43601eb2a9980
```

Upload package:

```text
dfu3500-validation.tgz  sha256=3b019c2cd44d559c8c70c8bdafde4f352b5072a8ee66aa3c871647a0129b8568
```

The package contains refreshed `dfu3500_partner_validation/payloads/*` payloads and arch-13 helper
scripts.  It intentionally does not contain the remote vendor tree or simulator.

## Reproduction Path

On the local machine, the payload was generated with the current compiler path
using `vendor_inst_mode="legacy_gemm_compat"` for the fused GEMM+ReLU-style
baseline shape.

On `huake02@arch-13`:

```bash
cd /home/huake02
tar -xzf dfu3500-validation.tgz
cd dfu3500_partner_validation
./validate_on_arch13.sh
```

Useful logs after running:

```text
dfu3500_partner_validation/run/summary.tsv
dfu3500_partner_validation/run/gemm_template_fusion/runtime.log
dfu3500_partner_validation/run/gemm_template_fusion/run.log
```

The optional diff helper only compares the first useful wave:

```text
payload result/cbuf_file.bin  vs vendor result/cbuf_file.bin
payload result/micc_file.bin  vs vendor result/micc_file.bin
```

It deliberately avoids repeated runtime/config/section summaries.

## Why This Matters

This baseline proves that the current OpenFabric DFU path can emit a SimICT
runnable image, including:

```text
CBUF/MICC package shape
vendor task/subtask/instance control tables
instance base-address table layout
legacy GEMM-compatible instruction stream
runtime config staging path
```

Future architecture refactors may replace this implementation, but they should
preserve this behavioral milestone:

```text
same case + task_num=4 must produce a vendor-runtime-runnable image
```

Byte-for-byte parity is useful evidence, not the top-level goal.  A refactor is
acceptable if it keeps or improves functional runtime behavior while explaining
any intentional binary differences.

## Guardrail for Future Agents

Do not casually delete or rewrite the current GEMM binary path just because a
new IR design looks cleaner.  This is the first known live path through the
vendor runtime.  Use strangler-style replacement: keep this baseline runnable
while moving one layer at a time to the new architecture.
