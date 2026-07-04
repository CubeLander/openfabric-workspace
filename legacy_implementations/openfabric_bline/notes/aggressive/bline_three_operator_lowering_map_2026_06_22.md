# B-line Three-operator Lowering Map

Date: 2026-06-22

This note is the aggressive-delivery locator for the current three-operator
bundle: `gemm_no_relu`, `gemm_relu`, and `log10max`.

The important truth: the bundle was produced quickly because it is a
progress-first upload bundle, not because all three operators already completed
final B-line-native binary lowering.  GEMM/GEMM+ReLU currently use an A-line
successful binary/template baseline as a tactical seed.  log10max currently
uses the existing B-line validation structural payload.  The final B-line byte
writers still need to replace the tactical seeds.

## Current Bundle Entry Points

- Upload bundle:
  - `bline-three-operator-upload-validation.tgz`
- Partner validation package note:
  - `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/BLINE_THREE_OPERATOR_UPLOAD.md`
- Three-operator launcher inside the package:
  - `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/scripts/run_bline_progress_payloads.sh`
- Launcher-selected payloads:
  - `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/payloads/bline_gemm_no_relu`
  - `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/payloads/bline_gemm_relu`
  - `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/payloads/log10max_single_task`
- Progress payload archive in repo:
  - `report/b_line_progress_payloads/gemm_no_relu`
  - `report/b_line_progress_payloads/gemm_relu`
  - `report/b_line_progress_payloads/log10max`

## Fast Path That Produced The Three Payloads

### GEMM no-ReLU

Status: tactical binary seed.

Payload writer:

- `compiler/tools/emit_bline_progress_payload.py`

Evidence selector:

- `compiler/gpdpu_compiler/core/stream_compiler/aline_gemm_evidence.py`

Actual binary/template source:

- `/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion_bash_semantics_probe`

Copied binary outputs:

- `result/cbuf_file.bin`
- `result/micc_file.bin`
- `simulator_bin/insts_file.bin`
- `simulator_bin/exeblock_conf_info_file.bin`
- `simulator_bin/instance_conf_info_file.bin`
- `simulator_bin/subtasks_conf_info_file.bin`
- `simulator_bin/tasks_conf_info_file.bin`

Known sharp edge:

- The source case is `gemm_template_fusion_bash_semantics_probe`; this is a
  fast delivery seed and may contain fused semantics.  It is not proof that the
  no-ReLU B-line-native lowering is finished.

### GEMM+ReLU

Status: tactical binary seed.

Payload writer:

- `compiler/tools/emit_bline_progress_payload.py`

Evidence selector:

- `compiler/gpdpu_compiler/core/stream_compiler/aline_gemm_evidence.py`

Actual binary/template source:

- `/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion_bash_semantics_probe`

Current ReLU binding report code:

- `compiler/gpdpu_compiler/core/stream_compiler/relu_binding.py`
- `compiler/tools/check_stream_compiler_relu_binding.py`

Known sharp edge:

- This payload is also copied from the A-line fused GEMM/ReLU baseline.  It is
  useful for upload/runtime-path bring-up, but final B-line must still bind ReLU
  through explicit B-line tile/template semantics and must not silently drop the
  post-op.

### log10max

Status: B-line/current-validation structural seed.

Payload source:

- `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/payloads/log10max_single_task`

Payload builder:

- `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/build_payloads.py`

Source-level program construction in the builder:

- `ChipEnv("log10max_single_task_openfabric")`
- SRAM input/output declarations
- explicit `load`
- `clamp_min`
- `log10`
- `reduce_max`
- `maximum`
- scalar add/mul
- explicit `store`

Strategy/report code:

- `compiler/gpdpu_compiler/core/stream_compiler/log10max_collective_strategy.py`
- `compiler/gpdpu_compiler/core/stream_compiler/log10max_template_pack.py`
- `compiler/tools/check_stream_compiler_log10max_collective.py`
- `compiler/tools/check_stream_compiler_log10max_templates.py`

Known sharp edge:

- The manifest says `runtime_runnable=0`.
- The current program status is
  `program_bin_package_structural_smoke_ready_functional_blocked`.
- Current blockers include non-functional instruction rows and unsupported
  `broadcast_load`, `local_compute`, and `reduce_store` rows.
- This is a package/control-path seed, not completed log10max functional
  lowering.

## B-line Lowering Code To Inspect First

These are the files to inspect when debugging how a real B-line binary is
supposed to emerge, rather than how the progress bundle was assembled.

### Source and tile program

- `compiler/gpdpu_compiler/core/chip_env.py`
- `compiler/gpdpu_compiler/core/ops.py`
- `compiler/gpdpu_compiler/core/program_tile.py`
- `compiler/gpdpu_compiler/core/dfu3500/task_resource_replay.py`

### Stream compiler semantic/template reports

- `compiler/gpdpu_compiler/core/stream_compiler/template_ops.py`
- `compiler/gpdpu_compiler/core/stream_compiler/binary_plan.py`
- `compiler/gpdpu_compiler/core/stream_compiler/vendor_components.py`
- `compiler/gpdpu_compiler/core/stream_compiler/serializer_readiness.py`

### Component and byte-writer work

- `compiler/gpdpu_compiler/core/stream_compiler/component_writers.py`
- `compiler/gpdpu_compiler/core/stream_compiler/micc_component_writers.py`
- `compiler/gpdpu_compiler/core/stream_compiler/inst_writers.py`
- `compiler/gpdpu_compiler/core/stream_compiler/operator_payload_assembly.py`

Important caveat:

- `inst_writers.py` is currently fail-closed/report-oriented raw-template
  overlay readiness.  It does not yet emit the final functional `inst_t` bytes.
- `operator_payload_assembly.py` is report-only package shell logic.  It does
  not create runnable CBUF/MICC bytes.
- `micc_component_writers.py` contains concrete debug MICC/control byte writer
  pieces and the important `InstanceTableAddress` contract.

## Template And Binary Material Locations

### A-line GEMM/GEMM+ReLU template material

Primary seed root:

- `/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion_bash_semantics_probe`

Look under that root for:

- `gpdpu_tensor/task*/subtask*/template/*.csv`
- `result/cbuf_file.bin`
- `result/micc_file.bin`
- `simulator_bin/*.bin`
- `riscv/testarm.c`
- `riscv/dpuctrl.c`
- `csv_generate/conf.h`

The A-line evidence scanner records the CSV/template and binary evidence in:

- `compiler/gpdpu_compiler/core/stream_compiler/aline_gemm_evidence.py`

The progress payload metadata records exact hashes in:

- `report/b_line_progress_payloads/gemm_no_relu/PROGRESS_METADATA.json`
- `report/b_line_progress_payloads/gemm_relu/PROGRESS_METADATA.json`

Current GEMM/GEMM+ReLU seed hashes:

- CBUF: `2e83d38ba24ba3a55c7920e971b1493706a330bb66bf3ca7bb74a69ace3c29cb`
- MICC: `17e78755ceb408f19b222640dcdcdfdd27f53338b81cbe07e57516b6dc695978`

### log10max template/material seed

Current payload:

- `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/payloads/log10max_single_task`

Progress metadata:

- `report/b_line_progress_payloads/log10max/PROGRESS_METADATA.json`

Current log10max seed hashes:

- CBUF: `28c44e44bf986527e40044b1e00f56b13fba4ad799bfd31d6e22d31c09ce4eb2`
- MICC: `f455dc68b061bda23b1f6c3a2703568019838eecc8e566b60c5e58aec20ee492`

Local template intent report:

- `compiler/gpdpu_compiler/core/stream_compiler/log10max_template_pack.py`

Collective/allreduce strategy report:

- `compiler/gpdpu_compiler/core/stream_compiler/log10max_collective_strategy.py`

## If Something Breaks, Start Here

### Upload package missing one of the three payloads

Inspect:

- `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/scripts/run_bline_progress_payloads.sh`
- `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/BLINE_THREE_OPERATOR_UPLOAD.md`
- `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/scripts/package_upload_bundle.sh`

Expected selected payload names:

- `bline_gemm_no_relu`
- `bline_gemm_relu`
- `bline_log10max`, symlinked to `payloads/log10max_single_task`

### GEMM bytes are missing or hash mismatch

Inspect:

- `compiler/tools/emit_bline_progress_payload.py`
- `compiler/gpdpu_compiler/core/stream_compiler/aline_gemm_evidence.py`
- `report/b_line_progress_payloads/gemm_no_relu/MANIFEST.txt`
- `report/b_line_progress_payloads/gemm_relu/MANIFEST.txt`

Then inspect the A-line seed root:

- `/home/flecther/workspace/dpu_project/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion_bash_semantics_probe`

### ReLU appears dropped

Inspect:

- `compiler/gpdpu_compiler/core/stream_compiler/relu_binding.py`
- `compiler/tools/check_stream_compiler_relu_binding.py`
- `report/b_line_progress_payloads/gemm_relu/PROGRESS_METADATA.json`

Remember:

- Current upload payload is a tactical fused baseline seed.
- Final B-line should make ReLU binding explicit and reject a store that consumes
  pre-ReLU accumulator output when the operator claim is GEMM+ReLU.

### log10max loads but does not execute functionally

Inspect:

- `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/payloads/log10max_single_task/MANIFEST.txt`
- `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/build_payloads.py`
- `compiler/gpdpu_compiler/core/stream_compiler/log10max_collective_strategy.py`
- `compiler/gpdpu_compiler/core/stream_compiler/log10max_template_pack.py`

Expected current answer:

- This is known.  `runtime_runnable=0` is intentional in the current structural
  seed.  The next real work is functional instruction rows plus PE00/global
  scalar visibility.

### Final B-line-native binary writer question

Inspect:

- `compiler/gpdpu_compiler/core/stream_compiler/inst_writers.py`
- `compiler/gpdpu_compiler/core/stream_compiler/micc_component_writers.py`
- `compiler/gpdpu_compiler/core/stream_compiler/component_writers.py`
- `compiler/gpdpu_compiler/core/stream_compiler/operator_payload_assembly.py`

Expected current answer:

- MICC/control writer contracts are partially concrete.
- `inst_t` is not yet the final functional byte writer.
- The progress bundle exists because we intentionally allowed tactical binary
  seeds while final B-line byte emission catches up.

## One-line Accountability Summary

If the three-operator upload bundle fails at packaging, look at the validation
launcher/package paths first.  If GEMM bytes are questioned, look at the A-line
seed and `emit_bline_progress_payload.py`.  If log10max is questioned, look at
`log10max_single_task` and its manifest.  If someone claims all three are
already final B-line-native lowerings, point them back to this note.
