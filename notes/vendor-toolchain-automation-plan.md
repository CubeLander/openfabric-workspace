# Vendor Toolchain Automation Plan

This plan turns the customer SimICT/GPDPU vendor flow into a reproducible
OpenFabric-controlled engineering workflow without replacing the vendor
assembler too early.

## Goal

Build durable infrastructure that can:

```text
inspect a runnable vendor case
generate or refresh a case manifest
materialize vendor-shaped assembler inputs
run the real common_oper/build_app flow
assemble a runtime payload
compare it against a trusted baseline
optionally run it on the closed SimICT runtime
```

The first target cases are:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/softmax_1
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion
```

The first refactored cases to wire into the same workflow are:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/softmax_refactored
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_refactored
```

## Non-Goals

Do not implement a new final-binary generator in this phase.

Do not treat archived B-line compiler code as the active route.

Do not make `simulator_bin/*.bin` the source of truth for OpenFabric operator
intent. They are comparison targets and vendor-owned assembler outputs.

Do not depend on local absolute paths. All generated outputs should live under
the CMake build directory or another explicit local build/output directory.

## Architecture

The automation should have four layers:

```text
1. case manifest and role audit
2. assembler-input materialization
3. vendor package execution
4. validation payload and comparison
```

### Layer 1: Case Manifest And Role Audit

Add a small Python package under a new active tooling area:

```text
tools/vendor_case/
  openfabric_vendor_case/
    __init__.py
    manifest.py
    scan.py
    hash.py
    roles.py
  scan_vendor_case.py
```

The scanner should emit:

```text
build/vendor_cases/<case>/VendorCaseInputManifest.json
```

Suggested schema:

```json
{
  "schema_version": 1,
  "case_id": "softmax_1",
  "source_case": "simict3500final/.../application/softmax_1",
  "operator": "softmax",
  "roles": [
    {
      "path": "csv_generate/conf.h",
      "role": "case_contract",
      "owner": "vendor_source",
      "generated": false,
      "sha256": "...",
      "size": 1234
    }
  ],
  "tasks": [
    {
      "app_conf": "app0.conf",
      "task_count": 1,
      "subtasks": [
        {
          "name": "subtask1",
          "instance_times": 1,
          "csv_amount": 16,
          "graph_height": 4,
          "graph_width": 4
        }
      ]
    }
  ],
  "runtime_surface": {
    "expects_input_data": true,
    "expects_riscv_program": true
  }
}
```

The first version can be mostly file-role and hash based. Parsing `app*.conf`
is the only required semantic parse in phase 1.

Acceptance:

```text
python3 tools/vendor_case/scan_vendor_case.py \
  simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/softmax_1 \
  --out build/vendor_cases/softmax_1/VendorCaseInputManifest.json

python3 tools/vendor_case/scan_vendor_case.py \
  simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion \
  --out build/vendor_cases/gemm_template_fusion/VendorCaseInputManifest.json
```

Both manifests should be deterministic and should contain no machine-specific
absolute paths except optional provenance fields explicitly marked as local.

### Layer 2: Assembler-Input Materialization

Add a materializer that can copy or generate the vendor assembler-minimal bundle:

```text
tools/vendor_case/materialize_vendor_inputs.py
```

Initial mode should be copy-based:

```text
source vendor case
  -> build/vendor_cases/<case>/assembler_input/
       app*.conf
       task*/subtask*/template/*.csv
       task*/subtask*/build_so/libsubtask.so
       manifest.json
       provenance.json
```

For refactored cases, the materializer should later support generated CSV and
graph hook outputs from centralized OpenFabric source. In phase 1, it is enough
to copy the trusted vendor case output and record roles/hashes.

Acceptance:

```text
build/vendor_cases/softmax_1/assembler_input/app0.conf
build/vendor_cases/softmax_1/assembler_input/task0/subtask1/template/0.csv
build/vendor_cases/softmax_1/assembler_input/task0/subtask1/build_so/libsubtask.so
```

The materialized bundle must match source hashes for copied files.

### Layer 3: Vendor Package Execution

Wrap the vendor flow as CMake custom targets, using the CMake shadow build as the
entrypoint.

Suggested target names:

```text
softmax_1_vendor_refresh
gemm_template_fusion_vendor_refresh
softmax_refactored_vendor_package
gemm_refactored_vendor_package
```

The target should run the vendor case in a build-local working copy, not directly
inside the source tree. The goal is to prevent generated `task*/`, `result/`,
`simulator_bin/`, `rtl_bin/`, and RISC-V build products from churning tracked
source directories.

Recommended staging:

```text
build/vendor_cases/<case>/work/
  application/<case>/
  application/build_app/
  testcase/common_oper/
  common/src/
  dpuapi/
```

The first implementation may copy only the needed subtree from
`simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/<case>` plus
the shared `build_app`, `common_oper`, `common/src`, and `dpuapi` inputs.

Package command:

```text
cd build/vendor_cases/<case>/work/application/<case>
./run.sh

cd ../build_app
./run_mtr.sh <app_name> <duplicate_num> <app_num>
```

The exact arguments should come from the manifest or a small case profile, not
from hardcoded shell snippets.

Acceptance:

```text
build/vendor_cases/<case>/package/simulator_bin/insts_file.bin
build/vendor_cases/<case>/package/simulator_bin/exeblock_conf_info_file.bin
build/vendor_cases/<case>/package/simulator_bin/instance_conf_info_file.bin
build/vendor_cases/<case>/package/simulator_bin/tasks_conf_info_file.bin
build/vendor_cases/<case>/package/simulator_bin/subtasks_conf_info_file.bin
build/vendor_cases/<case>/package/config/cbuf_file.bin
build/vendor_cases/<case>/package/config/micc_file.bin
```

### Layer 4: Validation Payload And Comparison

Add a package builder:

```text
tools/vendor_case/build_validation_payload.py
```

It should produce a B-line-inspired active payload:

```text
build/vendor_cases/<case>/payload/
  MANIFEST.txt
  SOURCE_MANIFEST.txt
  config/cbuf_file.bin
  config/micc_file.bin
  runtime/input_data.bin
  runtime/riscv_program
  runtime/riscv_src/...
  simulator_bin/*.bin
  validation/runtime_ready.json
  reference/*
```

Add a comparison tool:

```text
tools/vendor_case/compare_payloads.py
```

The first comparison mode should compare:

```text
config/cbuf_file.bin
config/micc_file.bin
runtime/input_data.bin
runtime/riscv_program
simulator_bin/insts_file.bin
simulator_bin/exeblock_conf_info_file.bin
simulator_bin/instance_conf_info_file.bin
simulator_bin/tasks_conf_info_file.bin
simulator_bin/subtasks_conf_info_file.bin
```

The comparison report should classify:

```text
same
missing
size_mismatch
sha_mismatch
first_byte_mismatch
record_diff_summary when record size is known
```

Known record sizes from archived comparison helpers can be reused as defaults,
but the tool should make them explicit and easy to override.

Acceptance:

```text
python3 tools/vendor_case/compare_payloads.py \
  --baseline build/vendor_cases/softmax_1/payload \
  --candidate build/vendor_cases/softmax_refactored/payload \
  --out build/vendor_cases/softmax_refactored/compare.json
```

The compare report must be machine-readable JSON and should also print a short
human summary.

## CMake Integration

Extend the current CMake shadow build with custom targets:

```text
vendor_case_scan_softmax_1
vendor_case_scan_gemm_template_fusion
vendor_case_package_softmax_1
vendor_case_package_gemm_template_fusion
vendor_case_payload_softmax_1
vendor_case_payload_gemm_template_fusion
```

Then add refactored targets:

```text
vendor_case_package_softmax_refactored
vendor_case_package_gemm_refactored
vendor_case_compare_softmax_refactored
vendor_case_compare_gemm_refactored
```

Recommended top-level convenience targets:

```text
vendor_cases_scan
vendor_cases_package
vendor_cases_compare
```

Keep generated outputs under:

```text
build/vendor_cases/
```

Do not commit generated payloads by default.

## Implementation Phases

### Phase 0: Preserve Current Editor Build

Keep the CMake analysis targets and generated `compile_commands.json` working.
The package automation should be additive and should not destabilize clangd.

Deliverable:

```text
cmake --build build --target softmax_refactored_syntax gemm_refactored_syntax
```

still passes.

### Phase 1: Read-Only Vendor Case Manifests

Implement `scan_vendor_case.py`, file hashing, role classification, and
`app*.conf` parsing.

Deliverable:

```text
build/vendor_cases/softmax_1/VendorCaseInputManifest.json
build/vendor_cases/gemm_template_fusion/VendorCaseInputManifest.json
```

This phase is low risk because it does not run vendor scripts or mutate source
cases.

### Phase 2: Build-Local Vendor Refresh

Implement build-local staging and run the existing vendor scripts in the staging
copy.

Deliverable:

```text
build/vendor_cases/<case>/work/
build/vendor_cases/<case>/package/
```

This phase proves we can drive the customer toolchain without source-tree
generated churn.

### Phase 3: Payload Builder And Baseline Diff

Build active validation payloads from the package outputs and add component-level
diff against trusted vendor packages.

Deliverable:

```text
build/vendor_cases/<case>/payload/MANIFEST.txt
build/vendor_cases/<case>/compare.json
```

The first comparisons should be vendor case vs freshly staged vendor case. That
tests the automation before comparing refactored cases.

### Phase 4: Refactored Case Integration

Teach `softmax_refactored` and `gemm_refactored` to materialize equivalent
vendor inputs.

Softmax should go first because its refactored source is already more centralized
and CMake analysis covers device, graph, and RISC-V sources.

Deliverable:

```text
vendor_case_compare_softmax_refactored
```

with byte-identical outputs or a small, explained diff report.

### Phase 5: Remote Runtime Validation

Only after local package and byte comparison are stable, add an upload bundle
compatible with the B-line validation wrapper style.

Deliverable:

```text
build/vendor_cases/dfu3500-validation.tgz
```

The remote command should stay fixed and boring:

```text
tar -xzf dfu3500-validation.tgz
cd dfu3500_partner_validation
./run.sh
```

## First Concrete Patch Set

The smallest valuable implementation patch should include:

```text
tools/vendor_case/openfabric_vendor_case/
tools/vendor_case/scan_vendor_case.py
tests or smoke script for app*.conf parsing
CMake target vendor_case_scan_softmax_1
CMake target vendor_case_scan_gemm_template_fusion
```

Expected command:

```text
cmake --build build --target vendor_cases_scan
```

Expected result:

```text
build/vendor_cases/softmax_1/VendorCaseInputManifest.json
build/vendor_cases/gemm_template_fusion/VendorCaseInputManifest.json
```

## Design Risks

1. Vendor scripts assume relative paths and source-tree layout.

   Mitigation: use a staged work directory that preserves the expected relative
   structure instead of trying to call scripts from arbitrary directories.

2. Generated artifacts may depend on stale files left in the source case.

   Mitigation: always stage from clean source inputs and run the vendor `clean.sh`
   inside the work directory.

3. Refactored cases may produce semantically equivalent but byte-different
   packages.

   Mitigation: compare simulator components separately, then compare final
   `cbuf_file.bin` and `micc_file.bin`; classify differences by layer.

4. B-line record-size knowledge may be stale or case-specific.

   Mitigation: keep record sizes in a visible table used by the diff tool, and
   allow per-case overrides in the manifest.

5. Remote runtime validation can be slow or flaky.

   Mitigation: make local byte comparison the gate before remote runs; keep
   remote scripts fixed, timed, and payload-local.

## Success Criteria

The workflow is healthy when a developer can run:

```text
cmake -S . -B build
cmake --build build --target vendor_cases_scan
cmake --build build --target vendor_cases_package
cmake --build build --target vendor_cases_compare
```

and get deterministic manifests, runtime payloads, and comparison reports
without hand-editing paths or committing generated vendor outputs.

The long-term OpenFabric value comes from making these facts explicit:

```text
operator shape
task/subtask partition
PE work ownership
template CSV rows
graph dependencies
runtime control material
package bytes
comparison evidence
```

Once those facts are explicit, OpenFabric can gradually replace copied vendor
case material with generated material while the vendor assembler remains the
behavioral guardrail.
