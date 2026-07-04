# log10_test refactored integration plan

## Evidence

`log10_test` was recovered from screenshot-only source material.  The tracked
OCR recovery now contains only source files; no makefiles, run scripts, SPM data
generator, `spm_data/data.h`, generated binaries, or package outputs were
invented.

The active template logic is small:

```text
HLDT vec, base slot -1, imm 0, iteration 0
FLOG2 vec -> vec
HSTT vec, base slot -1, imm 0, iteration 1
```

The visible config generator facts are:

```text
task_count = 4
subtask_count = 1
instances_per_subtask = 2048
graph_height = 1
graph_width = 1
INPUT_ADDRESS = 0x00000000
OUTPUT_ADDRESS = 0x00000080
ROW_OFFSET = 256
```

The recovered RISC-V control source transfers:

```text
input bytes  = 0x80000
output bytes = 0x80000
TASK_NUM     = 1
```

Despite the directory name, the executable CSV logic is `FLOG2`, not `log10`.
The commented-out clamp/log10/scale sketch from the screenshots is not active
vendor behavior and should not be treated as a source of truth.

## Fit with the current refactored layout

The existing refactored cases use this ownership split:

- `operator_sources/<op>/case_plan.json` records the mapping from vendor layout
  to maintained source.
- `operator_sources/<op>/device_program/` owns the centralized CSV/config/graph
  generation source.
- The operator plan emits RuntimePlanImage control data; replay embeds that
  image into the common RISC-V executor instead of maintaining per-operator
  RISC-V control source.
- The task/subtask directories are replay/package compatibility surfaces, not
  maintained source.
- Replay materializes a disposable vendor-shaped case and compares generated
  binary/package artifacts against a trusted baseline when enough evidence
  exists.

`log10_test` should follow the softmax shape more than the GEMM shape: it is a
simple per-PE elementwise operator with one subtask and no graph edges beyond
one node per task/subtask/PE site.

## Proposed target shape

Create:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/log10_refactored/
  CMakeLists.txt
  README.md
  operator_sources/log10/
    case_plan.json
    device_program/
      main.cpp
      log10_template_program.h
```

The maintained device program should:

1. Declare a `DistributedPlan` with 4 tasks, 1 subtask, 16 PEs, and
   `uniform_instance_layout(4, 2048, 1)`.
2. Declare one input tensor and one output tensor using the recovered base
   addresses and 256-element row stride.
3. Emit one instruction block per PE:
   `load_h256_tile` or a small log-specific load wrapper, `flog2`, then store.
4. Emit graph trace data with one node per task/subtask/PE and no edges.
5. Generate app conf and instance config through
   `vendor_write_app_conf_files()` and `vendor_write_instance_config_files()`.
6. Emit RuntimePlanImage control data for the recovered input/output DMA and
   kernel launch sequence, then validate the common executor API trace against
   the plan API trace.

Add `RegisterActions::flog2()` to `common_app_builder/register_actions.h` as a
thin wrapper around the existing generic `emit_fp_unary(..., "FLOG2", ...)`.
That keeps `FLOG2` as a shared target instruction instead of hiding it in the
log operator.

## Replay/package plan

Start with a syntax-only `log10_refactored_syntax` target.  Full replay should
wait until the missing vendor package surface is resolved.

Full replay needs:

1. `case_specs()["log10"]` in `tools/vendor_case/openfabric_vendor_case/refactored_replay.py`.
2. `materialize_log10_refactored()` that copies centralized source into a
   vendor-shaped disposable `log10_refactored_build_case`.
3. Local script patching equivalent to softmax/GEMM once the original
   `run.sh`, `clean.sh`, RISC-V makefile, and data generation surface are known.
4. Binary/package comparison against a trusted `log10_test` baseline.

Do not add `log10_test` to `vendor_cases_package` yet.  The recovered OCR tree
lacks the runnable packaging surface required by `build_vendor_package()`.

## Open risks

- The recovered runtime source includes `../spm_data/data.h`, but no such file
  exists in the screenshot recovery.
- There is no trusted generated CBUF/MICC package for comparison.
- The case name says `log10`, but active behavior is `FLOG2`; changing it to
  mathematical log10 would be a new operator behavior, not a refactor.
- The OCR CSV tags use underscore forms such as `FLOG2_1`, while the shared
  refactored CSV backend currently emits tags such as `FLOG21`. Existing
  refactored cases treat CSV text as assembler input detail and compare final
  binaries instead, so this should be validated at the binary boundary before
  tightening CSV text compatibility.

## Recommended next step

Implement the syntax-only `log10_refactored` operator source and CMake target,
plus `RegisterActions::flog2()`.  After that, use the generated CSV/config
outputs for local inspection, but defer replay/package comparison until the
missing vendor `spm_data` and build scripts are available or recovered from a
trusted source.
