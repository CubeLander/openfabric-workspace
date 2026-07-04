# Vendor Toolchain Artifact Summary

This note summarizes the current evidence about the customer SimICT/GPDPU
toolchain artifact format and the archived B-line validation package shape. The
purpose is to keep the next automation work grounded in the active
`simict3500final` vendor cases while still reusing the useful validation lessons
from `legacy_implementations/openfabric_bline`.

## Working Model

The customer flow is not one artifact format. It has three different layers:

```text
handwritten vendor case inputs
  -> common_oper / build_app assembler outputs
  -> runtime package consumed by SimICT
```

OpenFabric should automate the first layer and package/check the later layers.
It should not start by replacing `common_oper` or reviving the archived B-line
final-binary generator as the default route.

## Layer 1: Vendor Case Inputs

The assembler-minimal input bundle is:

```text
app*.conf
task*/subtask*/template/*.csv
task*/subtask*/build_so/libsubtask.so
```

The full runnable case also carries:

```text
csv_generate/conf.h
csv_generate/conf_PEmap.h
spm_data/data_generate.c or generated input_data.bin
riscv/testarm.c or generated riscv_program
application/template/input_data_convert.c
common/src/*
dpuapi/DpuAPI.*
```

Observed active examples:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/softmax_1
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion
```

The top-level case `run.sh` scripts currently call `csv_generate/run.sh` and
then build the RISC-V control program. The `csv_generate/run.sh` scripts compile
`test_app_conf_generate.c`, materialize instance config binaries, run the
template generator (`gpdpu_TestOp` or `gpdpu_tensor`), build each graph hook, and
run `spm_data/run.sh`.

Important classification:

```text
conf.h / conf_PEmap.h       source-like case contract
template/*.cpp or *.c       vendor authoring source
template/*.csv              generated assembler input
build_so/test_graph_extend  vendor graph-hook source
build_so/libsubtask.so      generated assembler input
```

`app*.conf` describes the task/subtask container shape. For example, softmax has
four application conf files, each with one task and two subtasks; GEMM has four
application conf files, each with one task and three subtasks, where subtask2 has
`Instance Times : 4` and `csv_amount:32`.

## Layer 2: Assembler Outputs

`application/build_app/main.cpp` reads each `app*.conf`, constructs task groups,
maps instruction blocks, generates execute blocks, and prints simulator and RTL
artifacts through `common_oper`.

The main simulator outputs are:

```text
simulator_bin/insts_file.bin
simulator_bin/exeblock_conf_info_file.bin
simulator_bin/instance_conf_info_file.bin
simulator_bin/tasks_conf_info_file.bin
simulator_bin/subtasks_conf_info_file.bin
simulator_bin/data_inst_replace.bin
```

The corresponding RTL/debug collateral includes files under `rtl_bin/`, such as
`cbufData_inst.bin`, `cbufData_exeblock.bin`, `cbufData_instance.bin`,
`miccData_task.bin`, `miccData_subtask.bin`, `instEnable.bin`, and
`taskEnable.bin`.

Current evidence says these binary rows are target-owned output of the vendor
assembler path. They are excellent comparison targets, but they should not be
the first source of truth for OpenFabric case authoring.

## Layer 3: Runtime Package

`application/build_app/run_mtr.sh` assembles the runtime-facing files by
concatenating simulator components:

```text
insts_file.bin
+ exeblock_conf_info_file.bin
+ instance_conf_info_file.bin
  -> cbuf_file.bin

tasks_conf_info_file.bin
+ subtasks_conf_info_file.bin
  -> micc_file.bin
```

The effective runtime package surface is:

```text
config/cbuf_file.bin
config/micc_file.bin
config/input_data.bin
config/riscv_program
```

Depending on the staging script, the same bytes may also appear under
`result/`. `result/` is useful for local build outputs; `config/` is the shape
expected by the runtime staging flow.

## Legacy B-line Validation Package

The archived B-line validation package is a delivery and verification wrapper,
not the customer source format. The package
`legacy_implementations/openfabric_bline/bline-three-operator-upload-validation.tgz`
contains:

```text
dfu3500_partner_validation/
  build_payloads.py
  validate_on_arch13.sh
  scripts/*.sh
  tools/diff_vendor_bytes.py
  sha256.txt
  sizes.txt
  payloads/<case>/
```

Each payload usually has:

```text
payloads/<case>/MANIFEST.txt
payloads/<case>/config/cbuf_file.bin
payloads/<case>/config/micc_file.bin
payloads/<case>/result/cbuf_file.bin
payloads/<case>/result/micc_file.bin
payloads/<case>/simulator_bin/*.bin
payloads/<case>/runtime/input_data.bin
payloads/<case>/runtime/riscv_program
payloads/<case>/runtime/riscv_src/...
payloads/<case>/validation/runtime_ready.json
payloads/<case>/reference/*
```

This shape is valuable because it keeps together:

```text
runtime bytes
component bytes
runtime control material
reference/check data
hash and size manifests
remote validation scripts
optional byte diff tools
```

The useful lesson is packaging discipline, not the old compiler implementation.

## What To Reuse

Reuse these ideas from B-line:

```text
payload-local MANIFEST / SOURCE_MANIFEST
sha256 and size indexes
config/result/simulator_bin separation
runtime_ready metadata
fixed remote validation entrypoint
component-level diff for cbuf/micc and simulator_bin
```

Do not reuse these as the active path:

```text
old final-binary generator as default route
symbolic B-line CSV rows as assembler-ready CSV
archived compiler module layout as the source of truth
```

## Engineering Direction

The near-term OpenFabric automation should generate a vendor-shaped case input
bundle, run the real vendor `common_oper/build_app` package flow, then wrap the
result in a B-line-inspired validation payload.

The intended bridge is:

```text
VendorCaseInputManifest
  -> materialized assembler input bundle
  -> vendor common_oper/build_app outputs
  -> runtime payload bundle
  -> byte comparison and optional remote runtime validation
```

This keeps the customer assembler in the loop while moving the hand-maintained
case facts into explicit, reviewable OpenFabric-owned manifests and generators.
