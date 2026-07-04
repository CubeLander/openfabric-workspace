# log10max Handoff Package Spec Audit

## Scope

This audit inspected the current `log10max_refactored` package tooling only:

- `simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/log10max_refactored/CMakeLists.txt`
- `simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/log10max_refactored/tools/build_test_package.py`
- `simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/log10max_refactored/tools/package_run.sh`
- `docs/vendor-workflow-evidence/runtime-package-build-flow.md`

The result below is a minimal handoff-package shape proven by log10max. It
does not claim a shared package contract for GEMM or softmax yet.

## Validation

Command run:

```sh
cmake --build build --target log10max_refactored_test_package
```

Result: failed in the final package-builder step while compiling
`config/riscv_program`. The prior analysis, runtime-plan trace, executor trace,
device-program analysis, and `build_app` bundle-generation steps completed.

The failure is environment/toolchain-related:

```text
/usr/lib/gcc/riscv64-unknown-elf/10.2.0/include/stdint.h:9:16:
fatal error: stdint.h: No such file or directory
```

The failing log is:

```text
build/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/log10max_refactored/test_package/bundle_logs/riscv_build.log
```

Static inspection continued because the package file layout is explicitly
defined in `build_test_package.py`, and the failed build left enough intermediate
bundle material to confirm the `build_app` side creates `result/cbuf_file.bin`,
`result/micc_file.bin`, and optional `result/data_inst_replace.bin`.

## Emitted Package Inventory

`build_test_package.py` emits an archive:

```text
test_package/log10max_refactored_test_package.tar.gz
```

containing a `package/` root with this intended layout:

```text
package/
  README.md
  MANIFEST.txt
  manifest.json
  run.sh
  config/
    input_data.bin
    cbuf_file.bin
    micc_file.bin
    riscv_program
    data_inst_replace.bin                  # optional
    runtime_plan.bin
    runtime_plan.dump
    summary.txt
    address_projection_dump.txt
    plan_api_trace.txt
    runtime_plan_api_trace.txt
    runtime_plan_executor_api_trace.txt
  reference/
    Y.fp32.bin
    output_data.bin
    reference.json
  vendor_layout/
    app0.conf
    csv_generate/
      instance_conf_info_file0.bin
      instance_conf_info_for_rtl_file0.bin
      graph_trace/openfabric_graph_trace_data.cpp
      task0/
        subtask1/template/{0..15}.csv
        subtask2/template/{0..15}.csv
        subtask3/template/{0..15}.csv
  runtime/
    runtime_plan.bin
    riscv_program
    openfabric_runtime_plan_image_embedded.c
    openfabric_runtime_plan_image.h
    openfabric_runtime_plan_riscv_executor.c
    openfabric_runtime_plan_riscv_executor.h
    openfabric_runtime_plan_riscv_program.c
  source/
    CMakeLists.txt                         # optional copy
    operator_sources/log10max/
      README.md
      case_plan.json
      device_program/...                   # full operator source tree
  build_logs/
    compat_graph_hook_build.log
    build_app_run_mtr.log
    riscv_build.log
    riscv_objdump.log                      # only if objdump is available
```

The package builder also uses a temporary `bundle_build/` worktree and
`compat_graph_hook/libsubtask.so` while building the runtime bundle. Those are
builder internals, not intended package payloads.

## Fact Classification

### Operator Contract

These facts describe the operator or the intended OpenFabric lowering result:

- Operator identity: `log10max_refactored`.
- Case identity in source plan: `log10max_refactored_v0`.
- Element type and logical shape: `fp32`, `64 x 512`.
- Formula from `case_plan.json`:
  `Y=(maximum(log10(clamp_min(X,1e-10)), max(log10(clamp_min(X,1e-10)))-8)+4)*0.25`.
- SPM image facts from `case_plan.json`: image size `3145728` bytes, input
  offset `0`, output offset `524288`.
- Lowering status: `runtime_plan_and_naive_staged_reduce_scaffold`.
- Work shape currently emitted by log10max: one app config, one task, three
  subtasks, sixteen PE CSV templates per subtask.
- OpenFabric runtime plan image and its API traces as the contract guardrail:
  source plan trace, runtime-plan reader trace, and RISC-V executor trace are
  expected to match.

### Runtime Artifact

These are runtime-visible files consumed directly by `package/run.sh` or by the
closed SimICT runtime staging flow:

- `config/cbuf_file.bin`
- `config/micc_file.bin`
- `config/input_data.bin`
- `config/riscv_program`
- Optional `config/data_inst_replace.bin`

`config/runtime_plan.bin` is also runtime-intent material for the OpenFabric
RISC-V executor, but `package_run.sh` does not stage it directly into SimICT
`config/`; it is already embedded into the built `riscv_program` path in this
package flow.

### Source Bundle

These files make the package inspectable and rebuildable around the OpenFabric
runtime-plan executor:

- `runtime/openfabric_runtime_plan_image.h`
- `runtime/openfabric_runtime_plan_riscv_executor.c`
- `runtime/openfabric_runtime_plan_riscv_executor.h`
- `runtime/openfabric_runtime_plan_riscv_program.c`
- `runtime/openfabric_runtime_plan_image_embedded.c`
- `runtime/runtime_plan.bin`
- `runtime/riscv_program`
- `source/operator_sources/log10max/...`
- Optional `source/CMakeLists.txt`

The temporary copied SimICT shared trees under `bundle_build/gpdpu/users/...`
are build inputs used by the package builder, not shipped source-bundle payload.

### Vendor Compatibility Layout

These files preserve the shape expected by vendor config/build tooling:

- `vendor_layout/app0.conf`
- `vendor_layout/csv_generate/instance_conf_info_file0.bin`
- `vendor_layout/csv_generate/instance_conf_info_for_rtl_file0.bin`
- `vendor_layout/csv_generate/graph_trace/openfabric_graph_trace_data.cpp`
- `vendor_layout/csv_generate/task0/subtask*/template/*.csv`

The build-time case directory also contains `task0/subtask*/build_so/libsubtask.so`
to satisfy `build_app`. The final handoff package intentionally ships the
vendor-layout CSV/config evidence, not the temporary compatibility `.so` files.

### Validation / Reference Payload

These files support comparison, review, or host-side validation:

- `reference/Y.fp32.bin`
- `reference/output_data.bin`
- `reference/reference.json`
- `config/summary.txt`
- `config/address_projection_dump.txt`
- `config/runtime_plan.dump`
- `config/plan_api_trace.txt`
- `config/runtime_plan_api_trace.txt`
- `config/runtime_plan_executor_api_trace.txt`
- `build_logs/*`
- `MANIFEST.txt`
- `manifest.json`

`manifest.json` is especially useful as package integrity metadata because it
records each shipped file's relative path, size, and SHA-256 digest.

### Accidental Script Detail

These facts should not become first-class handoff spec fields:

- The package app name string
  `openfabric_log10max_refactored_package`.
- Temporary paths such as `bundle_build/`, `bundle_logs/`,
  `compat_graph_hook/`, and `riscv_build/`.
- The hard-coded Python copy order.
- The use of `g++ -shared -fPIC -std=c++11 -O0 -g` for the compatibility graph
  hook.
- The exact `run_mtr.sh` invocation used internally:
  `sh ./run_mtr.sh openfabric_log10max_refactored_package 1 1`.
- The choice to duplicate the same reference output as both
  `reference/Y.fp32.bin` and `reference/output_data.bin`.
- `README.md` prose, including the GEMM launch note used as background context.
- Timeout defaults, interactive prompting behavior, and `OUT_DIR` naming in
  `run.sh`.
- Optional `riscv_objdump.log` generation depending on local `objdump`
  availability.
- Picolibc specs discovery paths and generated semihost specs file names.

## Minimal OperatorHandoffPackageSpec

The minimal spec should describe only package facts proven by this log10max
flow. A compact data shape is:

```yaml
OperatorHandoffPackageSpec:
  version: 1
  operator:
    name: log10max_refactored
    case_id: log10max_refactored_v0
    dtype: fp32
    shape:
      rows: 64
      cols: 512
    formula: "Y=(maximum(log10(clamp_min(X,1e-10)), max(log10(clamp_min(X,1e-10)))-8)+4)*0.25"
    spm_image:
      size_bytes: 3145728
      input_offset_bytes: 0
      output_offset_bytes: 524288
    lowering_status: runtime_plan_and_naive_staged_reduce_scaffold

  launch_shape:
    app_conf_count: 1
    task_count: 1
    subtasks:
      - name: subtask1
        pe_template_count: 16
      - name: subtask2
        pe_template_count: 16
      - name: subtask3
        pe_template_count: 16

  entrypoint:
    command: "./run.sh [SIMICT_ROOT]"
    stages_prebuilt_runtime_bundle: true

  runtime_artifacts:
    required:
      cbuf_file: config/cbuf_file.bin
      micc_file: config/micc_file.bin
      input_data: config/input_data.bin
      riscv_program: config/riscv_program
    optional:
      data_inst_replace: config/data_inst_replace.bin

  openfabric_runtime_plan:
    image: config/runtime_plan.bin
    dump: config/runtime_plan.dump
    embedded_source: runtime/openfabric_runtime_plan_image_embedded.c
    executor_sources:
      - runtime/openfabric_runtime_plan_image.h
      - runtime/openfabric_runtime_plan_riscv_executor.c
      - runtime/openfabric_runtime_plan_riscv_executor.h
      - runtime/openfabric_runtime_plan_riscv_program.c
    guardrail_traces:
      source_plan: config/plan_api_trace.txt
      runtime_plan_reader: config/runtime_plan_api_trace.txt
      riscv_executor: config/runtime_plan_executor_api_trace.txt
      expected_relation: identical

  vendor_compat_layout:
    app_confs:
      - vendor_layout/app0.conf
    instance_config:
      simulator: vendor_layout/csv_generate/instance_conf_info_file0.bin
      rtl: vendor_layout/csv_generate/instance_conf_info_for_rtl_file0.bin
    graph_trace_source: vendor_layout/csv_generate/graph_trace/openfabric_graph_trace_data.cpp
    task_templates_root: vendor_layout/csv_generate/task0

  validation_payload:
    reference_output: reference/output_data.bin
    reference_aliases:
      - reference/Y.fp32.bin
    reference_metadata: reference/reference.json
    summary: config/summary.txt
    address_projection_dump: config/address_projection_dump.txt
    build_logs_dir: build_logs

  source_bundle:
    operator_source_root: source/operator_sources/log10max
    package_cmake: source/CMakeLists.txt

  integrity_manifest:
    json: manifest.json
    text: MANIFEST.txt
```

The important boundary is that `OperatorHandoffPackageSpec` should identify
semantic roles and relative package paths. It should not prescribe the Python
builder's temporary worktree, copy sequence, local compiler flags, or archive
creation mechanics.

## What Not To Generalize Yet

Do not generalize these log10max facts to GEMM or softmax yet:

- One app config. GEMM's known vendor launch includes a duplicate application
  package count, and softmax/GEMM should be re-audited from their runnable cases.
- One task, three subtasks, and sixteen PE templates per subtask.
- The `log10max` staged-reduction structure or its `LOG10_STAGE` /
  `GLOBAL_CLIP_FLOOR` behavior.
- The exact `fp32 64 x 512` shape, SPM offsets, SPM image size, or formula.
- The presence of an OpenFabric `RuntimePlanImage` executor bundle in the same
  form. That is proven for this refactored log10max package, not for current
  GEMM/softmax handoff.
- The requirement that trace guardrails are exactly the three log10max trace
  files listed above.
- The final package directory names `runtime/`, `reference/`, `vendor_layout/`,
  and `source/` as a cross-operator compatibility promise. They are good
  candidates, but only log10max proves them today.
- The optional `data_inst_replace.bin` behavior.
- The direct SimICT runtime-only `run.sh` as the universal operator entrypoint.
- The current compatibility graph hook strategy.

## Recommendation

Adopt the proposed spec only as `OperatorHandoffPackageSpec v1 for proven
log10max-style handoff packages`. The next useful step is not to force GEMM or
softmax into it, but to audit one of those runnable vendor cases against the same
fact classes and promote only the overlapping, behavior-backed fields.
