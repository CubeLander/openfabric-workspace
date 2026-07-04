# Functional Probe Manual ABI Assumptions

Date: 2026-06-20

Status: active caution note

Scope:

```text
functional_maximum_single_app
vendor_inst_mode = legacy_template_compat
```

This note records the fields we currently hand-filled or hard-coded while bringing
up the first OpenFabric-generated non-GEMM functional probe.  These values are
not a general DFU3500 compiler contract yet.  Treat them as explicitly named
scaffolding with guards, not as invisible backend truth.

The immediate goal is narrow:

```text
OpenFabric core pipeline
  -> real legacy inst_t rows
  -> runnable SimICT package
  -> one closed-loop local elementwise operator
```

The current probe is intentionally tiny:

```text
Y = maximum(X, 3.5)
```

It is not `log10max`, not GEMM, not a reduce/allreduce workload, and not a
general elementwise backend.

## Why This Note Exists

We hit several low-level control/runtime failures where a single manually filled
field made the remote simulator hang:

- stale package selection made a 1-task payload run with a 4-task start config;
- MICC/component sizes looked locally reasonable but did not match runtime layout;
- `STD` used a different instance base slot than the one we had populated;
- hand-built vendor-like reference cases were useful for byte comparison, but not
  automatically runtime-valid examples.

The lesson is simple: every manually filled ABI field must be visible, guarded,
and eventually replaced by a real lowering rule or target profile fact.  No more
magic pebbles hidden in the grass. 🪨

## Current Guardrail Commands

Use these before packaging or uploading the functional probe:

```bash
PYTHONPATH=compiler python3 \
  compiler/gpdpu_compiler/validation/dfu3500_partner_validation/build_payloads.py \
  --case functional_maximum_single_app \
  --payload-root compiler/gpdpu_compiler/validation/dfu3500_partner_validation/payloads

PYTHONPATH=compiler python3 compiler/tools/check_core_functional_probe_report.py
PYTHONPATH=compiler python3 compiler/tools/check_partner_validation_entrypoint.py

./compiler/gpdpu_compiler/validation/dfu3500_partner_validation/scripts/package_upload_bundle.sh dfuval.tgz
```

Do not manually tar a random payload directory.  The package script runs the
entrypoint guard and prevents the “rebuilt payload differs from selected upload”
mistake.

## Manual / Hard-Coded Items

### 1. `legacy_template_compat` Mode

Code locations:

```text
compiler/gpdpu_compiler/core/program_bin.py
compiler/gpdpu_compiler/core/program_serializer.py
compiler/gpdpu_compiler/core/program_legacy_inst.py
compiler/gpdpu_compiler/core/dfu3500/legacy_templates.py
```

Hand-filled behavior:

```text
vendor_inst_mode = legacy_template_compat
```

Meaning:

```text
Use real vendor-style legacy inst_t template rows for non-GEMM local compute,
but do not apply the GEMM-specific route/resource replay path.
```

Why it exists:

```text
legacy_gemm_compat
  = GEMM byte-compat path with GEMM route/resource assumptions

legacy_template_compat
  = minimal non-GEMM template-bound instruction row path
```

Risk:

```text
This is still a small compatibility bridge, not a general DFU target binder.
Do not use the name to imply log10/reduce/allreduce support.
```

Future replacement:

```text
Executable role / template binding should own supported op families explicitly:
  maximum_scalar
  affine
  log10
  reduce
  broadcast/materialize
```

### 2. Functional Probe Shape And Tensor Layout

Code location:

```text
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/build_payloads.py
```

Hand-filled values:

```text
case_id        = functional_maximum_single_app
shape          = 64 x 512
dtype          = fp32
threshold      = 3.5
input offset   = 0x00000000
output offset  = 0x00080000
task count     = 1
physical mesh  = 4 x 4
task mesh      = task_axis_size=1, physical_mesh_shape=(4, 4)
```

Placement shape:

```text
[TaskShard("functional_maximum_single_app"), Shard(0), Shard(1)]
```

Why it exists:

```text
We wanted a full-mesh closed-loop functional probe that avoids partial-mesh
runtime questions and avoids reduce/app-storage semantics.
```

Risk:

```text
This is a validation probe shape, not an operator API requirement.
The 4x4 full mesh is used because partial mesh emission is not implemented yet.
```

Future replacement:

```text
Use target/profile capacity plus user/developer task-axis placement to choose
mesh usage.  The probe shape can then be just one test case rather than a baked
backend assumption.
```

### 3. Local Compute Operand Template

Code locations:

```text
compiler/gpdpu_compiler/core/program_legacy_inst.py
compiler/gpdpu_compiler/core/dfu3500/legacy_templates.py
```

Hand-filled instruction shape:

```text
local maximum:
  ILDMT input
  IMM scalar
  FMAX

store:
  HSTT / ISTT-style template expanded to STD
```

Hand-filled operand role convention:

```text
regular slot 0 = input value
regular slot 1 = scalar immediate
regular slot 2 = output value for store
```

Important limitation:

```text
There is no general register allocator here.
This is a fixed tiny template for the first functional probe.
```

Risk:

```text
Any new local op that needs more operands, different lifetimes, or real register
allocation must fail closed until a proper template/binder exists.
```

Future replacement:

```text
Dfu3500 local-compute binder should expose small supported templates first,
then graduate toward a constrained allocator only when needed.
```

### 4. Vendor CSV Pseudo Expansion Rules

Code location:

```text
compiler/gpdpu_compiler/core/program_legacy_inst.py
```

Hand-copied behavior:

```text
ILDT / ILDMT -> LDM-family expanded rows
ISTT / HSTT  -> STD-family expanded rows
COPYT        -> COPY-family expanded rows
```

Current observed rule:

```text
lane expansion count = adaptive operand group width
immediate advances by lane-shaped offsets
destination operand does not advance for non-COPYT pseudo expansion
COPYT remains special because route-copy destination lane behavior differs
```

Local functional probe float op setting:

```text
FMAX latency / wait field = 72
iter_exe_cond             = 1 for local FMAX template rows
stage-end flags           = disabled for this tiny local template
```

Why it exists:

```text
The local `common_oper` source tree is not guaranteed to be arch-13-identical,
but the vendor CSV expansion algorithm clearly treats tensor pseudo ops as
expanded physical rows.  Our earlier operand mismatch came from assuming a
simpler expansion.
```

Risk:

```text
Do not globally apply this latency or end-flag behavior to GEMM.  GEMM has its
own observed byte-compatible path.
```

Future replacement:

```text
Move pseudo expansion into an explicit DFU3500 template encoder contract, with
per-template tests against source evidence and runtime cases.
```

### 5. Instance Base Address Slots

Code location:

```text
compiler/gpdpu_compiler/core/program_bin.py
```

Hand-filled values for `legacy_template_compat`:

```text
subtask0 / load:
  row 0 base words =
    base_addr0 = input1_base_word = 0x00000000
    base_addr1 = 0xffffffff
    base_addr2 = 0xffffffff
    base_addr3 = 0xffffffff

subtask1 / store:
  row 2048 base words =
    base_addr0 = 0xffffffff
    base_addr1 = 0xffffffff
    base_addr2 = input3_base_word = 0x00020000
    base_addr3 = 0xffffffff

subtask2 / extra padded store-compatible row:
  row 4096 base words =
    base_addr0 = 0xffffffff
    base_addr1 = 0xffffffff
    base_addr2 = input3_base_word = 0x00020000
    base_addr3 = 0xffffffff
```

Why slot 2 matters:

```text
The local store template expands to STD rows using iter_exe_cond = 2.
Therefore it reads base_addr2, not base_addr0.
```

Bug fixed:

```text
We initially populated the wrong base slot for the store subtask.
That made STD use an invalid base and the PE could fail to finish.
```

Guard:

```text
compiler/tools/check_core_functional_probe_report.py
  verifies store subtask output base is bound to STD base slot 2.
```

Risk:

```text
This slot mapping is template-specific.  It must not silently propagate to other
store templates.
```

Future replacement:

```text
Instance base rows should be derived from each memory op's selected base slot
and storage region, not filled from probe-specific conditionals.
```

### 6. Fixed Runtime Component Sizes

Code locations:

```text
compiler/gpdpu_compiler/core/program_serializer.py
simict3500final/gpdpu/users/risc_nn_riscv/dpuapi/DpuAPI.h
```

Hard runtime sizes:

```text
CBUF size = 23531520 bytes
MICC size = 8522976 bytes = 0x820ce0
```

MICC component layout currently emitted:

```text
tasks_conf_info_file.bin    = 480 bytes
subtasks_conf_info_file.bin = 8522496 bytes
```

Why it exists:

```text
Vendor `DpuAPI.h` defines MICC_CONFIG_SIZE = 0x820ce0.  Although one observed
`DPU_MiccTransfer` call can transfer a smaller region, the runtime package file
layout/preload expects the fixed MICC blob size.
```

Important warning:

```text
Do not shrink MICC to the number of active task/subtask rows just because a
short hand-built case looks cleaner.  The simulator package path expects fixed
capacity files.
```

Future replacement:

```text
These capacities belong in DFU3500 target profile/config, with serializer tests
checking final package size.
```

### 7. Exeblock Inactive Row Prefill

Code location:

```text
compiler/gpdpu_compiler/core/program_serializer.py
```

Hand-filled behavior:

```text
legacy_gemm_compat and legacy_template_compat both serialize exeblock metadata
with vendor-like inactive row prefill instead of arbitrary zero-only rows.
```

Why it exists:

```text
The runtime scans fixed-capacity exeblock metadata.  Inactive rows still need to
look like valid inactive records, not random default bytes.
```

Risk:

```text
The current inactive-row bytes are compatibility-derived.  If another vendor
profile changes this structure, the serializer needs a target-profile rule.
```

Future replacement:

```text
Document `exeBlock_conf_info_t` fully and generate inactive rows from the struct
schema rather than a compatibility branch.
```

### 8. RISC-V Runtime Control Source

Code location:

```text
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/runtime_control.py
```

Generated call shape:

```c
DPU_CbufTransfer((void*)CBUF_DDR_ADDR);
DPU_MiccTransfer((void*)MICC_DDR_ADDR);
DPU_SpmTransfer(... input ..., trans_direc=2);
DPU_Kernel_Start(1, task_num, (void*)0, 0, 0, 0);
while (!DPU_Kernel_Wait_Finish(0));
DPU_SpmTransfer(... output ..., trans_direc=0);
DPU_App_Finish();
```

Current probe values:

```text
task_num      = 1
instance_base = (void*)0
buf_num       = 0
time_type     = 0
```

Why it exists:

```text
The first functional probe is a single-launch single-task validation package.
We intentionally avoid vendor case templates and generate a boring control
program from RuntimeControlPlan.
```

Risk:

```text
No multi-launch, no multi-app, no multi-buffer, no runtime storage handoff.
This source should not learn PE instruction semantics.
```

Guard:

```text
compiler/tools/check_partner_validation_entrypoint.py
  verifies `DPU_Kernel_Start(1, task_num, ...)` matches manifest/control JSON.
```

Future replacement:

```text
RuntimeControlPlan should grow only as validation/runtime orchestration grows:
launch sequence, DMA groups, output collection, and reference checking.
It must remain separate from device instruction lowering.
```

### 9. Full-Mesh Task Start Configuration

Code locations:

```text
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/build_payloads.py
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/runtime_control.py
compiler/tools/check_partner_validation_entrypoint.py
```

Hand-filled behavior:

```text
functional_maximum_single_app is a 1-task payload.
Runtime control must start exactly 1 task.
```

Bug fixed:

```text
We previously allowed stale selected payload/runtime control to drift from the
rebuilt formal payload.  That made a 1-task payload look like it was being run
with a 4-task launch expectation.
```

Guard:

```text
check_partner_validation_entrypoint.py compares:
  MANIFEST task_num
  riscv_control.json task_count
  conf.h TASK_NUM
  generated testarm.c DPU_Kernel_Start argument
  rebuilt payload hashes
```

Risk:

```text
If this guard is bypassed, runtime logs become misleading.  A control-plane
mistake can look like an instruction or MICC bug.
```

Future replacement:

```text
Keep this guard permanently.  It is cheap and catches embarrassing stale-package
mistakes before arch-13 does.
```

### 10. Hand-Built Vendor-Like Reference Case

Local path currently seen:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/openfabric_functional_maximum_vendor/
```

What it was used for:

```text
Byte-level comparison of inst/exeblock/tasks/subtasks/instance component shapes
against a vendor-workflow-generated case with similar intent.
```

Important warning:

```text
This case is not automatically an oracle for runtime-valid OpenFabric payloads.
If its metadata was generated with mismatched config assumptions, copying it can
copy the mistake.
```

Current safe interpretation:

```text
Use it as field evidence, not as law.
Prefer comparing specific components and checking each field against runtime
behavior and guards.
```

Future replacement:

```text
Create minimal, documented vendor-derived cases only when needed, and record:
  source CSV
  generated component hashes
  task/subtask counts
  runtime result
  exact fields used as evidence
```

## Current Known Good Local Build Snapshot

After the latest instance-base-slot fix, the regenerated functional probe had:

```text
result/cbuf_file.bin
  size = 23531520
  sha256 = 40f84f145605e32c8ed7485bf832ba5a7b691fc5d6841b97a0427161c1dcf903

result/micc_file.bin
  size = 8522976
  sha256 = 9e19f6c288e86d9bcd4ada2a9413665ed5a32a0ae63c9b27c22b05275b353128

simulator_bin/instance_conf_info_file.bin
  size = 2097152
  sha256 = 207c16c9b80fd2a31a642f9f6448f1fb4e6b1f987c4b6c2a4216e07ab2aac608
```

Packaged upload bundle:

```text
dfuval.tgz
sha256 = 6772c0d38cf6703c6c4f4b4fbc674ca910d6749542af4422252f8570cf888d36
```

These hashes are not permanent golden values.  They are here to anchor the
current debugging session.

## A-Line Closure Pit Log

This section records the additional lessons from the active A-line worktree after
the functional probe successfully ran through remote SimICT.  These are the
things that were easy to misread while debugging.

### 1. `run_payload_selection/` Is Not Payload Truth

Active local directory:

```text
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/run_payload_selection/
```

Important rule:

```text
Treat this as a temporary run-time selection directory, not as the canonical
payload tree.
```

The canonical tree is:

```text
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/payloads/<case>/
```

Why this matters:

```text
At one point `run_payload_selection/functional_maximum_single_app` still showed
short MICC/task/subtask blobs from an older experiment, while the actual
`payloads/functional_maximum_single_app` tree had the fixed runtime-size MICC.
```

Guard:

```text
compiler/tools/check_partner_validation_entrypoint.py
```

This guard parses `run.sh`, rebuilds the selected payload cases, and compares
the canonical `payloads/<case>/` tree against a fresh build.  It intentionally
does not trust a stale pre-existing `run_payload_selection/` directory.

Packaging script:

```text
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/scripts/package_upload_bundle.sh
```

This script excludes `run_payload_selection/` from the upload bundle.  Remote
`run.sh` recreates the selection directory.

### 2. `app_name=CASE/softmax_1` Is A Runtime Shell Hook

Manifest field:

```text
app_name=CASE/softmax_1
```

This does not mean the payload is semantically based on vendor softmax.  It is a
temporary partner-validation shell hook because the current remote validation
driver still expects a vendor-style case name / runtime directory shape.

Actual OpenFabric case:

```text
case_id=functional_maximum_single_app
formula=Y=maximum(X,3.5)
```

Risk:

```text
Do not infer softmax task/subtask semantics from this app_name.  The functional
probe is OpenFabric-generated and only borrows the vendor runtime shell shape.
```

Future replacement:

```text
The validator should stop requiring a fake vendor case name once generated
runtime-control bundles are first-class.
```

### 3. `program_status` Is Conservative, Manifest Gates Are The Runtime Contract

Current `chip_program.json` still reports:

```text
status = program_bin_package_legacy_template_compat_ready_runtime_validation_blocked
```

But the generated manifest reports the actual runtime gate:

```text
load_rows_functional=1
local_compute_rows_functional=1
store_rows_functional=1
inst_rows_functional=1
runtime_package_complete=1
runtime_control_assets_valid=1
output_collection_supported=1
reference_check_available=1
runtime_runnable=1
runtime_expectation=run_functional_runtime
```

Interpretation:

```text
`program_status` is a coarse compiler-status string.
`MANIFEST.txt` is the validation packaging contract.
```

Risk:

```text
If future debugging keys off `program_status` alone, it may incorrectly classify
a runnable payload as blocked.
```

Future cleanup:

```text
Either retire the conservative status string for this path or make it align with
the manifest runtime gates.
```

### 4. Old Row-Level Validation And Component-Level Validation Diverge

Current `program_bin_rows.validation` still contains old row-layer blockers such
as:

```text
complete_runtime_package_emitted = false
binary_components_emitted        = false
instruction_layout_ready         = false
component_serializers_not_started
```

But `program_bin_components.validation` reports the real serialized component
state:

```text
component_bytes_emitted=1
package_bytes_emitted=1
insts_file_ready=1
cbuf_file_ready=1
micc_file_ready=1
instance_conf_info_file_ready=1
tasks_conf_info_file_ready=1
subtasks_conf_info_file_ready=1
exeblock_conf_info_file_ready=1
```

Interpretation:

```text
The old row-layer validation was written before the component serializer became
the runtime package source of truth for this path.
```

Risk:

```text
Two validation layers currently speak with different maturity levels.  This is a
source of false negatives during debugging.
```

Future cleanup:

```text
Unify row-layer and component-layer validation so `ProgramBinRows` does not
claim component serialization has not started after `ProgramBinComponents`
successfully emits files.
```

### 5. Non-GEMM Store Must Be `subtask1`, GEMM Store Remains `subtask2`

Code location:

```text
compiler/gpdpu_compiler/core/program_packing.py
```

Critical rule:

```text
GEMM tile_store:
  task_assignment exists through source_final_tile
  store maps to vendor subtask2

functional maximum tile_store:
  no GEMM task_assignment
  store maps to vendor subtask1
```

Why this matters:

```text
The functional probe has only two subtasks:
  subtask0 = load/local_compute
  subtask1 = store/final
```

Correct active task/subtask layout:

```text
task0 active_subtask_indices = [0, 1]
subtask0 instances_amount = 1, is_exe_end = false
subtask1 instances_amount = 1, is_exe_end = true
```

Previous trap:

```text
Accidentally inheriting GEMM's subtask2 store shape creates a gap in the active
subtask sequence and can make MicC wait for work that the payload does not own.
```

Guard:

```text
compiler/tools/check_core_functional_probe_report.py
  verifies active_subtask_indices == [0, 1]
  verifies subtask0 is non-terminal
  verifies subtask1 is terminal
```

### 6. Functional Probe Instruction Count Is Tiny And Intentional

Current template-bound totals:

```text
legacy_op_counts:
  LDM  = 64
  IMM  = 16
  FMAX = 16
  STD  = 64

template_bound_instruction_count = 160
unsupported_micro_op_count       = 0
PE instruction count             = 10 per PE
```

Per-PE shape:

```text
4 LDM rows
1 IMM row
1 FMAX row
4 STD rows
```

Why it matters:

```text
This is the first closed-loop non-GEMM current-core path.  Its value is that it
is boring.  If this count grows unexpectedly, someone probably taught the probe
to test more than one thing.
```

Guard:

```text
compiler/tools/check_core_functional_probe_report.py
  verifies LDM/IMM/FMAX/STD counts.
```

### 7. `compute_attrs` Must Survive Tile -> MicroOp -> Template Binding

Code locations:

```text
compiler/gpdpu_compiler/core/program_tile.py
compiler/gpdpu_compiler/core/program_micro_ops.py
compiler/gpdpu_compiler/core/dfu3500/legacy_templates.py
```

Manual bridge:

```text
Tile compute action attrs["attrs"]["scalar"]
  -> TileMicroBlock attrs["compute_attrs"]
  -> TileMicroOp attrs["compute_attrs"]
  -> _maximum_scalar_template_for_micro_op(...)
```

Why it matters:

```text
The `FMAX` immediate is not recoverable from the op name alone.  Losing
`compute_attrs.scalar` would silently produce an unbindable or wrong template.
```

Risk:

```text
This is still an ad-hoc bridge for local scalar elementwise ops.
```

Future replacement:

```text
Op/template binding should define a typed operand/attribute contract instead of
passing a nested attrs dictionary through several layers.
```

### 8. Runtime Runnable Means Package-Complete + Control-Complete, Not Just `inst_t`

Manifest gate:

```text
runtime_runnable =
  inst_rows_functional
  && runtime_package_complete
  && runtime_control_assets_valid
  && output_collection_supported
  && reference_check_available
```

Why it matters:

```text
Earlier structural probes had plausible `chip_program.json` data but were not
runtime payloads.  The functional probe only became upload-worthy after all of
these gates were true.
```

Risk:

```text
`functional_encoding=true` alone is not enough.  It only means instruction rows
are real template-bound rows; it says nothing about MICC/CBUF packaging,
RISC-V control, output DMA, or reference assets.
```

Guard:

```text
compiler/tools/check_core_functional_probe_report.py
compiler/tools/check_partner_validation_entrypoint.py
```

### 9. Generated RISC-V Control Uses Real Output DMA But Does Not Compare Locally

Current generated `testarm.c`:

```text
input:
  SPM_DDR_ADDR + 0x0 -> SPM 0x0, 0x20000 bytes

launch:
  DPU_Kernel_Start(1, 1, (void*)0, 0, 0, 0)
  DPU_Kernel_Wait_Finish(0)

output:
  SPM 0x80000 -> SPM_RST_DDR_ADDR + 0x80000, 0x20000 bytes
```

Reference assets:

```text
reference/X.fp32.bin
reference/Y.fp32.bin
reference/reference.json
```

Important distinction:

```text
The payload contains enough metadata and output DMA to support result checking.
The generated RISC-V program itself does not compare values.
```

Future replacement:

```text
The partner validator should collect the output buffer and compare it to
`reference/Y.fp32.bin` with a probe-specific dtype/tolerance rule.
```

### 10. Closed-Loop Success Does Not Generalize To `log10max`

Now proven by remote run:

```text
single-app local maximum_scalar
full 4x4 mesh
one task
ordinary input DMA
ordinary output DMA
real LDM/IMM/FMAX/STD template rows
```

Still not proven by this run:

```text
FLOG2
FMUL/FADD affine chain
clamp_min
reduce_max
allreduce / PE00 gather / SHFL tree
app-storage materialize/reload
multi-app sequencing
partial mesh
general register allocation
```

Correct next interpretation:

```text
This run validates the smallest current-core functional instruction smoke.
It does not validate the staged audio preprocessing/log10max design yet.
```

## What Is Still Not Proven

- Automated output collection and numeric comparison against `reference/Y.fp32.bin`.
- Whether every lane's remote output has been checked against the reference blob.
- Whether `FLOG2`, affine chains, clamp, or conversion behavior work in the same
  local-template path.
- Any reduce/allreduce/app-storage/broadcast/multi-app behavior.
- Partial physical mesh use.

## If The Remote Run Still Hangs

Do not blindly edit `inst_t` fields.  First collect:

```text
runtime.log final 200 lines
run.log
summary.tsv
MANIFEST.txt
sha256sum result/*.bin config/*.bin simulator_bin/*.bin
```

Then check in order:

1. `check_partner_validation_entrypoint.py` passes on the exact uploaded bundle.
2. `DPU_Kernel_Start` task count is `1`.
3. `micc_file.bin` is the fixed `8522976` byte package.
4. `instance_conf_info_file.bin` row 2048 has output base in `base_addr2`.
5. Active subtask compact slots are 0..15 for both load/compute and store.
6. `insts_file.bin` still has functional non-placeholder rows for LDM/IMM/FMAX/STD.

The order matters.  Control-plane drift has already wasted time once; let the
guards catch boring mistakes before we go hunting dragons in instruction bytes.
