# RFC: Generated RISC-V Control Programs for Operator Validation

## Status

Proposed for review.

## Summary

OpenFabric's DFU3500 validation workflow currently generates operator payloads
(`cbuf_file.bin`, `micc_file.bin`, input images, and reference output), but the
RISC-V side control program is still treated as a borrowed vendor artifact.  The
recent self-contained `log10max_single_task` payload improved this by bundling
`runtime/input_data.bin` and payload-local `runtime/riscv_src/riscv/testarm.c`,
but the source is still copied from the vendor `CASE/softmax_1` case and patched
through generated `conf.h`.

This RFC proposes making RISC-V control program generation a first-class part of
OpenFabric's validation toolchain:

```text
Compiler payload
  -> RuntimeControlPlan
  -> generated RISC-V control source
  -> riscv_program
  -> SimICT validation bundle
```

The goal is not to move device instruction generation into RISC-V.  The RISC-V
program remains the guest/control-plane program that loads CBUF/MICC, moves SPM
input/output data, starts kernels, waits for completion, and signals app finish.
OpenFabric should generate it because operator validation cannot be complete
without controlling how the simulated DPU is launched and how data moves through
runtime-visible memory.

## Current State

### Vendor runtime contract

Current vendor evidence says every runnable case eventually stages:

```text
config/cbuf_file.bin
config/micc_file.bin
config/input_data.bin
config/riscv_program
```

The RISC-V program is compiled from `riscv/testarm.c` plus `dpuapi/DpuAPI.c`:

```text
riscv64-unknown-elf-gcc -mabi=lp64d -march=rv64gcv -static \
  -o riscv testarm.c ../../../../dpuapi/DpuAPI.c ...
```

At runtime, SimICT loads `config/riscv_program` as a guest program.  The program
uses DpuAPI calls such as:

```text
DPU_CbufTransfer(...)
DPU_MiccTransfer(...)
DMA_Transfer_inoutArray(...)
DPU_Kernel_Start(...)
DPU_Kernel_Wait_Finish(...)
DPU_App_Finish()
```

It does not generate PE instructions.  Device-side work is already encoded in
`cbuf_file.bin` and `micc_file.bin`.

### Current OpenFabric validation path

The validation package under:

```text
compiler/gpdpu_compiler/validation/dfu3500_partner_validation
```

currently builds generated payloads.  For `log10max_single_task`, it now emits:

```text
payloads/log10max_single_task/result/cbuf_file.bin
payloads/log10max_single_task/result/micc_file.bin
payloads/log10max_single_task/runtime/input_data.bin
payloads/log10max_single_task/runtime/riscv_src/riscv/testarm.c
payloads/log10max_single_task/runtime/riscv_src/csv_generate/conf.h
payloads/log10max_single_task/reference/Y.fp32.bin
```

The arch-13 validator now prefers payload-local runtime assets and can compile
`runtime/riscv_src/riscv/testarm.c` into `runtime/riscv_program` using the shared
vendor `DpuAPI.c` and `common/src` headers.

This removes the immediate failure mode where validation needs
`testcase/application/<app_name>/input_data.bin` or `riscv/riscv` to already
exist.  However, the RISC-V source itself is still a copied vendor template,
not an OpenFabric-generated control program.

## Problem

RISC-V control is currently an implicit, under-modeled part of the validation
contract.

That creates several issues:

```text
1. Operator payload generation and RISC-V control generation are split across
   unrelated mechanisms.
2. New operator tests must borrow or patch a vendor case's `testarm.c` shape.
3. Runtime input/output offsets, tensor byte sizes, DMA slices, task count,
   instance count, and finish behavior are duplicated between compiler payloads
   and generated `conf.h` snippets.
4. Functional validation cannot confidently answer whether a failure came from
   compiler binary generation, data image layout, DMA control, or runtime launch
   sequencing.
5. Future staged operators and multi-app experiments will need explicit control
   flow, but the current model has no compiler-owned control plan to modify.
```

This is a layering gap, not just a missing script.  The compiler already owns
the operator payload and reference data; the validation toolchain must also own
the control program that tells SimICT how to execute that payload.

## Goals

1. Make RISC-V control generation a first-class validation artifact.
2. Keep RISC-V control separate from device instruction generation.
3. Generate self-contained validation bundles that do not require a vendor case
   directory for input data or RISC-V binaries.
4. Represent data image layout, DMA transfers, kernel starts, waits, and output
   copies in a reviewable `RuntimeControlPlan`.
5. Support current single-kernel operator tests first.
6. Preserve compatibility with arch-13's old toolchain and shell environment.
7. Allow future generated operator benchmarks to vary shapes, offsets, task
   counts, and input patterns without hand-editing `testarm.c`.

## Non-goals

This RFC does not propose:

```text
1. generating PE/device instructions from RISC-V;
2. replacing DpuAPI.c;
3. replacing SimICT runtime;
4. requiring local RISC-V cross compilation on developer machines;
5. implementing multi-package runtime sequencing immediately;
6. changing production compiler lowering semantics;
7. exposing RISC-V control generation in the frontend user API.
```

## Proposed Design

### 1. Add `RuntimeControlPlan`

Add a validation-layer data model describing how a payload is launched:

```python
@dataclass(frozen=True)
class RuntimeTensorRegion:
    name: str
    dtype: str
    shape: tuple[int, ...]
    byte_offset: int
    byte_size: int
    direction: Literal["input", "output", "scratch", "reference"]

@dataclass(frozen=True)
class RuntimeDmaTransfer:
    transfer_id: str
    tensor_name: str
    direction: Literal["ddr_to_spm", "spm_to_ddr"]
    ddr_offset: int
    spm_offset: int
    byte_size: int
    phase: Literal["before_launch", "after_launch", "custom"] = "custom"
    group_id: str = "default"
    task_id: int | None = None
    instance_id: int | None = None

@dataclass(frozen=True)
class RuntimeKernelLaunch:
    launch_id: str
    task_count: int
    instance_count: int
    micc_buffer: int = 0
    wait: bool = True
    input_transfer_group: str = "input"
    output_transfer_group: str = "output"

@dataclass(frozen=True)
class RuntimeControlPlan:
    case_id: str
    spm_image_size_bytes: int
    tensors: tuple[RuntimeTensorRegion, ...]
    transfers: tuple[RuntimeDmaTransfer, ...]
    launches: tuple[RuntimeKernelLaunch, ...]
    finish_app: bool = True
```

This plan belongs to validation/runtime packaging, not `ChipEnv`.  It may be
created from compiler output metadata and payload case configuration, but it
must not leak into chip-level graph construction.

For Phase 1/2, order semantics are intentionally simple:

```text
transfers with phase="before_launch" run in declared order before the first launch;
launches run in declared order;
transfers with phase="after_launch" run in declared order after the waited launch;
phase="custom" is rejected by the first generator unless a later scheduler handles it.
```

Multi-launch plans may exist as data for review, but the first source generator
must reject them with a clear unsupported diagnostic rather than emit guessed
control flow.

### 2. Generate RISC-V control source from the plan

Add a source generator:

```text
RuntimeControlPlan
  -> runtime/riscv_src/riscv/testarm.c
  -> runtime/riscv_src/riscv_control.json
```

The generated `testarm.c` should be intentionally boring:

```text
1. include DpuAPI headers;
2. transfer cbuf_file.bin from CBUF_DDR_ADDR;
3. transfer micc_file.bin from MICC_DDR_ADDR;
4. perform configured input DMA transfers;
5. start kernel launch(es);
6. wait for completion when requested;
7. perform configured output DMA transfers;
8. call DPU_App_Finish().
```

The generated C should avoid clever case-specific control flow until the control
plan has a stable representation.  The first version should emit exactly one
sequential single-kernel program and fail loudly for multi-launch control plans.

The first generated `testarm.c` should resemble a transparent ruler rather than
a clever runtime:

```c
int main(void) {
    DPU_CbufTransfer(...);
    DPU_MiccTransfer(...);
    /* declared before_launch DMA transfers */
    DPU_Kernel_Start(...);
    DPU_Kernel_Wait_Finish(...);
    /* declared after_launch DMA transfers */
    DPU_App_Finish();
    return 0;
}
```

### 3. Keep `conf.h` as compatibility output, not source of truth

Short term, the vendor RISC-V template and DpuAPI headers may still expect
selected constants through `conf.h`.  The generator may continue emitting:

```text
runtime/riscv_src/csv_generate/conf.h
runtime/riscv_src/spm_data/data.h
```

But these files should become projections from `RuntimeControlPlan`, not the
place where control semantics live.

Authority boundary:

```text
RuntimeControlPlan is the source of truth.
conf.h is a compatibility projection.
testarm.c is generated executable source.
riscv_control.json is the review/debug dump of the source of truth.
```

A generated payload must not read `CASE/softmax_1/riscv/testarm.c` or any other
vendor case `testarm.c`.  Old payload fallback remains allowed only inside the
arch-13 validator when a payload does not provide generated runtime assets.

### 4. Integrate with validation payloads

A generated payload should contain:

```text
result/cbuf_file.bin
result/micc_file.bin
runtime/input_data.bin
runtime/riscv_src/riscv/testarm.c
runtime/riscv_src/riscv_control.json
runtime/riscv_src/csv_generate/conf.h        # compatibility, optional later
runtime/riscv_src/spm_data/data.h           # compatibility, optional later
reference/<outputs>
MANIFEST.txt
```

`MANIFEST.txt` should include the runtime-control-relevant output metadata even
before reference checking is implemented:

```text
output tensor name
output dtype / shape
output SPM offset
output byte size
reference path
```

The arch-13 validator should continue this precedence:

```text
1. use runtime/riscv_program if present;
2. otherwise build runtime/riscv_src/riscv/testarm.c on arch-13;
3. fall back to vendor case riscv/riscv only for old payloads.
```

For generated payloads, fallback to vendor case assets should be treated as a
validation failure unless explicitly marked as legacy-compatible.  The whole
point is to keep generated operator cases self-contained.

### 5. Add operator benchmark generation

Add a small benchmark-case builder abstraction:

```python
@dataclass(frozen=True)
class OperatorValidationCase:
    case_id: str
    op_kind: str
    shape_config: dict[str, object]
    tensor_regions: tuple[RuntimeTensorRegion, ...]
    input_pattern: str
    reference_outputs: tuple[str, ...]
    vendor_inst_mode: str
    runtime_control: RuntimeControlPlan
```

This lets us generate families such as:

```text
log10max_single_task_64x512
log10max_single_task_128x256
gemm_relu_task4_64x64
future_softmax_axis1_64x512
```

without copying case-specific `testarm.c` files by hand.

## Invariants

1. RISC-V control source never generates device/PE instructions.
2. `RuntimeControlPlan` is the source of truth for runtime control semantics.
3. `testarm.c`, `conf.h`, and `riscv_control.json` are generated from the plan.
4. Payload validation must prefer payload-local runtime assets over vendor case
   assets.
5. Every input/output tensor region has explicit byte offset, byte size, dtype,
   shape, and direction.
6. Every DMA transfer references a known tensor region or explicit binary blob.
7. Every kernel launch has explicit task/instance count and wait policy.
8. Generated source must remain compatible with old arch-13 shell and compiler
   assumptions: portable C, no modern Python required remotely, no local import
   of OpenFabric on arch-13.
9. Functional reference data and runtime input image must be generated from the
   same tensor region metadata.
10. Missing RISC-V compile dependencies must produce clear diagnostics, not a
    silent fallback to unrelated vendor cases.
11. RISC-V control planning must not inspect `FiberOp`, `ExecutableFiberOp`,
    `TileMicroBlock`, or template-binding internals.  It consumes payload-level
    metadata: tensor regions, byte sizes, task/instance counts, and launch plan.
12. Generated payload cases must not read vendor `testarm.c` templates.

## Alternatives Considered

### Alternative A: Keep copying vendor `testarm.c`

This is sufficient for one narrow `softmax_1`-shaped validation, but it keeps
control semantics hidden in copied source and patched headers.  It also makes
new operator benchmarks brittle.

Reject as the long-term path.  Keep only as a compatibility fallback.

### Alternative B: Precompile every `riscv_program` locally

This would make arch-13 staging simpler, but it requires every developer machine
to have the exact RISC-V toolchain.  The current upload workflow is safer if it
can build on arch-13 using the vendor-installed compiler.

Defer.  Allow precompiled `runtime/riscv_program` as an optimization, but do not
require it.

### Alternative C: Bypass RISC-V and drive runtime directly

A local mock runtime may eventually bypass guest RISC-V for faster tests.  But
SimICT partner validation explicitly consumes `config/riscv_program`, and DpuAPI
behavior is part of the hardware/runtime contract we need to validate.

Reject for arch-13 validation.  Keep as a separate local simulator path.

### Alternative D: Encode control flow in `conf.h`

This matches parts of the vendor flow, but makes `conf.h` a semantic dumping
ground.  It also duplicates information already present in compiler tensor
metadata and payload manifests.

Reject as source of truth.  Permit `conf.h` as compatibility projection.

## Migration / Implementation Plan

### Phase 1: Plan and generated-source report

Add:

```text
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/runtime_control.py
```

with:

```text
RuntimeTensorRegion
RuntimeDmaTransfer
RuntimeKernelLaunch
RuntimeControlPlan
write_riscv_control_source(plan, output_dir)
write_riscv_control_json(plan, output_dir)
```

Update `build_payloads.py` so `log10max_single_task` builds a
`RuntimeControlPlan` and writes generated source from it.

Validation target:

```text
payload contains riscv_control.json
generated testarm.c exists
old copied template is no longer required for this case
build_payloads.py --case log10max_single_task does not read vendor testarm.c
MANIFEST.txt records output region metadata
```

### Phase 2: Single-kernel functional payload

Make generated `testarm.c` perform the current single-kernel sequence:

```text
CbufTransfer
MiccTransfer
input DMA
Kernel_Start
Kernel_Wait_Finish
output DMA
App_Finish
```

Keep generated `conf.h` only if DpuAPI/template includes require it.

Validation target:

```text
arch-13 can build runtime/riscv_program from generated source
runtime reaches SimICT launch without missing case directory assets
```

### Phase 3: Output collection and reference checking

Extend validation packaging so runtime output can be copied back and compared
against `reference/*.bin` or a generated checker script.

Validation target:

```text
case output region at configured SPM offset is collected
reference comparison reports max_abs_error / max_rel_error / mismatch count
```

### Phase 4: Benchmark family generation

Add command-line knobs:

```text
--case log10max_single_task
--shape 64x512
--input-pattern deterministic_positive
--task-axis-size 1
--output-offset 0x80000
```

Validation target:

```text
multiple payloads can be generated without hand-written RISC-V source edits
MANIFEST.txt records all runtime control metadata
```

### Phase 5: Multi-launch / staged control experiments

Only after single-kernel cases are stable, extend `RuntimeControlPlan` to handle:

```text
multiple kernel launches
multiple input/output transfer groups
explicit storage handoff between launches
ping-pong buffer policy
```

This is where future staged `log10max` / softmax experiments can be expressed.

## Validation Plan

Add focused tests or scripts for:

```text
1. RuntimeControlPlan JSON is deterministic.
2. Generated `testarm.c` contains the expected single-kernel DpuAPI call sequence:
   CBUF, MICC, input DMA, start, wait, output DMA, finish.
3. Tensor byte sizes and offsets match `runtime/input_data.bin` layout.
4. Generated `conf.h` values match `RuntimeControlPlan` projection.
5. `validate_on_arch13.sh` prefers payload-local assets.
6. Missing `DpuAPI.c` or RISC-V compiler produces a clear error.
7. `build_payloads.py --case log10max_single_task` no longer reads vendor
   `CASE/softmax_1/riscv/testarm.c`.
8. Generated payloads fail if they would fall back to vendor case runtime assets.
9. Existing smoke / explicitly legacy payload fallback still works.
10. Multi-launch RuntimeControlPlan is rejected by the first generator with a
    clear unsupported diagnostic.
```

The first implementation should remain local-side testable without contacting
arch-13.  Remote validation should be a final integration step, not the only
way to discover generator mistakes.

## Risks and Mitigations

### Risk: duplicating vendor DpuAPI semantics incorrectly

Mitigation:

```text
Use DpuAPI.c functions directly rather than reimplementing MMIO writes.
Generate conservative call sequences matching observed vendor `testarm.c` flow.
```

### Risk: generated control source becomes another hidden compiler layer

Mitigation:

```text
Keep `RuntimeControlPlan` as source of truth and dump it as JSON.
Do not let ad-hoc string generation become the only representation.
```

### Risk: overfitting to `log10max_single_task`

Mitigation:

```text
Model tensor regions, DMA transfers, and launches generically, but implement only
one single-kernel case first.
```

### Risk: remote toolchain constraints

Mitigation:

```text
Generated remote scripts and C source must avoid modern Python or host-only
OpenFabric imports.  Build RISC-V source on arch-13 with existing
riscv64-unknown-elf-gcc and shared vendor headers.
```

### Risk: confusing RISC-V control with device executable roles

Mitigation:

```text
Document the boundary: RISC-V launches and moves data; cbuf/micc contain device
program material.  Keep executable-role/template binding RFC separate.
```

## Expected Effect

After this change, each validation payload becomes a complete executable test
bundle rather than a half-generated binary blob plus borrowed vendor control
program.

Expected improvements:

```text
1. New operator validations can be generated without manually copying case
   directories.
2. Missing-case failures become structurally impossible for generated payloads.
3. Runtime control differences become reviewable as JSON and generated C.
4. Functional failures can be triaged into binary generation, data image layout,
   DMA/control, or runtime execution.
5. Future staged operators have a natural place to express multiple launches and
   storage handoff control flow.
```

## Open Questions

1. Which DpuAPI call sequence is the minimal stable sequence for a pure
   generated single-kernel payload?
2. Does the current softmax `testarm.c` rely on subtle side effects from
   `conf.h` arrays that need explicit representation in `RuntimeControlPlan`?
3. Should output collection be done by RISC-V DMA back to DDR, by SimICT file
   extraction, or both?
4. Should generated RISC-V source include debug counters / signatures for easier
   remote OCR/log diagnosis?
5. When multi-launch is introduced, does the vendor runtime permit sequential
   launches inside one `riscv_program` with the same cbuf/micc image, or must it
   stage new config between launches?

## Relationship To Fiber Executable Roles

This RFC is paired with, but separate from, the Fiber executable role binding
RFC.

```text
FiberOp / ExecutableFiberOp / cbuf / micc
  describe device-side executable content.

RuntimeControlPlan / generated testarm.c
  describe guest-side control: load, DMA, start, wait, finish.
```

Forbidden coupling:

```text
RuntimeControlPlan must not branch on compute_core:gemm_update, epilogue:relu,
or any other Fiber executable role.
RISC-V control generation must not consume TileMicroBlock or template-binding
internals.
```

The handshake point is the validation bundle: runtime control launches the
already-generated payload, but does not interpret its internal executable roles.

## Recommended Decision

Accept Phase 1 and Phase 2:

```text
1. Add `RuntimeControlPlan` under the partner validation toolchain.
2. Generate `riscv_control.json`, `testarm.c`, and compatibility `conf.h` from
   that plan for `log10max_single_task`.
3. Keep arch-13 compilation of `runtime/riscv_src/riscv/testarm.c` as the default
   path when `runtime/riscv_program` is absent.
4. Do not touch production compiler lowering or vendor serializers.
```

Defer:

```text
multi-launch control
benchmark search/generation matrix
local RISC-V toolchain requirement
mock-runtime bypass of RISC-V
full generated output checker integration
```
