# RFC: Remote Runtime Result Evidence and Output Closure

## Status

Draft for review.

## Summary

OpenFabric now has a local `RUNTIME_READY` validation gate that proves a DFU
payload is structurally ready to run: binary sizes match the profile,
component files match combined CBUF/MICC images, runtime-control metadata
exists, and the DFU3500 MICC control graph passes basic task/subtask/exeBlock
sanity checks.  The next desired milestone is operator-level value closure:
a payload should not be called functionally validated merely because SimICT
exited.

However, the current collaboration environment has a hard practical limit:
we cannot reliably download post-runtime binary artifacts from the customer
machine.  At most, we can read shell text, logs, screenshots, or OCRed files.
That changes the near-term design.  The immediate goal should not be a local
runtime-output artifact pipeline.  The immediate goal should be an
OCR-friendly remote self-check that runs on arch-13 and prints a small,
structured pass/fail summary.

This RFC therefore splits the design into two horizons:

```text
Now:
  local RUNTIME_READY guard
  -> remote SimICT run
  -> remote-side self-check / summary text
  -> OCR/log-readable result evidence

Later, when artifact access improves or simulator source/runtime is shared:
  remote artifacts
  -> local RuntimeOutputCapture
  -> local RuntimeReferenceCheck
  -> archived value reports
```

The key decision is that `RuntimeControlPlan` remains the source of truth for
output tensor regions and references, but current implementation must not assume
we can pull full output bytes back to the local repo.

## Current State

### Local payload validation

Payload construction currently auto-runs:

```text
validate_payload(..., requested_gate=RUNTIME_READY)
```

and archives:

```text
payloads/<case>/validation/runtime_ready.json
```

The current local gate checks:

```text
profile_conformance
source_fingerprint_check          # diagnostic unless strict source root exists
payload_conformance
runtime_readiness
dfu3500_component_consistency
dfu3500_control_graph
```

`dfu3500_control_graph` checks task, subtask, and exeBlock graph consistency
using `RuntimeControlPlan + MICC rows` as truth.  It deliberately does not use
`taskEnable.bin`, `instEnable.bin`, or other sidecars as runtime graph truth.

### Runtime control generation

The payload-local runtime metadata already describes the output region:

```python
RuntimeTensorRegion(
    name="Y",
    dtype="fp32",
    shape=(64, 512),
    byte_offset=0x80000,
    byte_size=131072,
    direction="output",
    reference_path="reference/Y.fp32.bin",
)

RuntimeDmaTransfer(
    tensor_name="Y",
    direction="spm_to_ddr",
    spm_offset=0x80000,
    ddr_offset=0x80000,
    byte_size=131072,
    phase="after_launch",
    group_id="output",
)
```

The generated RISC-V control source performs `after_launch` DMA transfers after
`DPU_Kernel_Wait_Finish`.

### Remote arch-13 runner

`validate_on_arch13.sh` stages payload files into the vendor runtime and records:

```text
run/summary.tsv
run/<case>/run.log
run/<case>/runtime.log
```

The script streams logs to the terminal.  This is currently the most reliable
feedback channel.  We should assume binary files under `run/<case>/` may not be
retrievable locally.

## Problem

The old phrasing of this RFC assumed we could collect remote output bytes and
analyze them locally.  That assumption is too strong for the current project
state.

The real current problem is narrower:

```text
SimICT can run remotely.
Local code can package payloads and validate binary/control structure.
But the only practical result channel may be terminal text / OCR.
```

Therefore a near-term value-closure design must answer:

```text
Can arch-13 itself compute a compact pass/fail result?
Can it print enough structured evidence for OCR/manual review?
Can it avoid dumping huge binary tensors into the human feedback path?
Can it remain driven by RuntimeControlPlan rather than ad-hoc shell guesses?
```

Without this adjustment, we risk designing a beautiful local artifact pipeline
that cannot be exercised under current permissions.

## Goals / Non-goals

### Goals

1. Reframe runtime output closure around current access constraints.
2. Add a remote-side self-check path that prints a small deterministic summary.
3. Use `RuntimeControlPlan` as the source of truth for output regions,
   references, dtype, and compare policy.
4. Keep local `RUNTIME_READY` separate from remote value evidence.
5. Make remote output evidence OCR-friendly: scalar counts, hashes, max errors,
   and first mismatch samples, not full tensor dumps.
6. Preserve a later path to full local artifact capture if customer cooperation
   or simulator/source access improves.

### Non-goals

1. Do not assume full remote output binaries can be downloaded today.
2. Do not block current validation work on obtaining simulator source.
3. Do not turn terminal logs into the semantic source of tensor layout.
4. Do not move output correctness into the generic decoder.
5. Do not require vendor sidecars for value comparison.
6. Do not implement multi-launch output handoff in the first remote self-check.

## Proposed Design

### Authority model

```text
RuntimeControlPlan:
  semantic source of truth for output tensor region, reference path, dtype,
  shape, and compare policy.

RemoteSelfCheck:
  remote-side executable checker that consumes RuntimeControlPlan, payload
  reference bytes, and runtime-produced output bytes on arch-13.

OCRSummary:
  compact text evidence printed to stdout and saved to run.log.

LocalArtifactClosure:
  deferred richer mode when remote binary artifacts become available locally.
```

The local decoder remains a byte/field microscope for payload binaries.  It does
not own runtime tensor values.

### Near-term remote self-check

Add a small arch-13-compatible script or generated checker under:

```text
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/
  runtime_value_check.py
```

The script runs on the customer machine after SimICT exits.  It should:

1. Load payload-local `runtime/riscv_src/riscv_control.json`.
2. Identify output tensors with `direction="output"` and `reference_path`.
3. Locate the runtime output memory image on the remote machine, if available.
4. Slice only the declared output range.
5. Compare against payload-local reference.
6. Print a compact deterministic summary.

The important change from the previous RFC version is that this summary is the
primary near-term result channel.  Full output files are optional remote
artifacts, not required local inputs.

### OCR-friendly summary format

The checker should print line-oriented records that survive terminal copy/OCR:

```text
OF_OUTPUT_CHECK_BEGIN case=functional_maximum_single_app schema=v1
OF_OUTPUT tensor=Y dtype=fp32 elements=32768 bytes=131072 status=PASS
OF_OUTPUT_HASH tensor=Y actual_sha256=<hex> reference_sha256=<hex>
OF_OUTPUT_ERROR tensor=Y max_abs=0 max_rel=0 mismatches=0 first_index=-1
OF_OUTPUT_CHECK_END status=PASS
```

For failure:

```text
OF_OUTPUT_CHECK_BEGIN case=functional_maximum_single_app schema=v1
OF_OUTPUT tensor=Y dtype=fp32 elements=32768 bytes=131072 status=FAIL
OF_OUTPUT_HASH tensor=Y actual_sha256=<hex> reference_sha256=<hex>
OF_OUTPUT_ERROR tensor=Y max_abs=1.25 max_rel=0.42 mismatches=17 first_index=4096
OF_OUTPUT_FIRST_MISMATCH tensor=Y index=4096 actual=3.5 reference=4.75
OF_OUTPUT_CHECK_END status=FAIL
```

If the output memory source cannot be located:

```text
OF_OUTPUT_CHECK_BEGIN case=functional_maximum_single_app schema=v1
OF_OUTPUT tensor=Y status=BLOCKED reason=output_source_missing
OF_OUTPUT_CHECK_END status=BLOCKED
```

This format is intentionally boring.  It can be read by humans, grep, OCR, or a
future parser.  It avoids huge tensor dumps.

### Runtime integration

After `run_runtime` in `validate_on_arch13.sh`:

```text
if runtime_rc == 0:
  run remote output self-check
  append OCR-friendly lines to run.log
  update summary.tsv with output_check_status
```

Extend `summary.tsv` from:

```text
case_id app_name task_num diff_status runtime_rc
```

to:

```text
case_id app_name task_num diff_status runtime_rc output_check_status
```

Possible statuses:

```text
PASS
FAIL
BLOCKED
SKIPPED
```

`BLOCKED` means the runtime ran, but the checker lacked evidence, for example
because the output memory image path is unknown.

### Output source discovery

The weakest current link is still the runtime output source path.  Under current
permissions, this should be investigated remotely with small shell probes and
OCR-friendly listings, not by assuming local artifact download.

A probe should print compact evidence such as:

```text
OF_OUTPUT_PROBE_BEGIN
OF_OUTPUT_PROBE_FILE path=config/<candidate> size=<n> sha256=<hex>
OF_OUTPUT_PROBE_FILE path=stat/<candidate> size=<n> sha256=<hex>
OF_OUTPUT_PROBE_FILE path=sim_trace/<candidate> size=<n> sha256=<hex>
OF_OUTPUT_PROBE_END candidates=<n>
```

If no stable output source exists, the near-term value check should remain
`BLOCKED`, and the project should continue with structural/runtime-exit
validation until cooperation deepens.

### Later full artifact mode

If customer collaboration later provides either:

```text
1. downloadable runtime artifacts,
2. access to simulator/runtime source,
3. a documented output dump path,
4. or a sanctioned output extraction API,
```

then we can add the richer local closure pipeline:

```text
RuntimeOutputCapture
  -> outputs/<tensor>.<dtype>.bin
  -> validation/output_reference.json
  -> local post-run report archive
```

This later mode is still valuable, but it should not be the immediate plan.

## Invariants

1. `RuntimeControlPlan` owns tensor shape, dtype, byte size, output offset, and
   reference path.
2. Remote output self-checks may only compare tensors with `direction="output"`
   and non-empty `reference_path`.
3. Missing output source is `BLOCKED`, not numerical `FAIL`.
4. Runtime exit code `0` does not imply operator correctness.
5. OCR summary must include status, tensor name, dtype, byte size, mismatch
   count, and hash evidence when available.
6. Tolerance policy must be explicit.  It must not silently downgrade exact
   comparison to approximate comparison.
7. The generic decoder must not learn operator output semantics.
8. Local `RUNTIME_READY` remains pre-run.  Remote value evidence is a separate
   post-run stage.
9. The current workflow must remain useful even without simulator source or
   downloadable runtime artifacts.

## Alternatives Considered

### Keep the previous local artifact capture plan as Phase 1

Rejected for now.  It assumes file access we do not currently have.  It can be
kept as a later phase, but not as the immediate engineering plan.

### Wait until the customer shares simulator source

Rejected as the only plan.  Simulator source would greatly improve confidence
and reduce reverse engineering, but we can still improve local packaging guards,
remote self-check summaries, and runtime-control evidence now.

### Treat runtime logs/OCR as sufficient correctness evidence

Rejected.  Logs are a transport channel for compact evidence; they are not the
semantic source of tensor layout or expected values.

### Compare inside generated RISC-V control code

Deferred.  It might be useful if Python/runtime file access is too limited on
arch-13, but it would couple test policy into generated guest control.  First
try a remote-side script or simple post-runtime checker.

### Stop writing local validation because simulator source would make it easier

Rejected.  Local validation prevents bad packages from reaching arch-13 at all.
Even with simulator source, profile conformance, component consistency,
control-graph checks, and stale-report guards remain useful compiler-side
contracts.

## Migration / Implementation Plan

### Phase 0: Re-scope the current RFC and notes

Accept that full local output artifact closure is blocked by access limits.
Record this constraint explicitly so future agents do not build on the wrong
premise.

### Phase 1: Remote output source probe

Add a tiny remote-side probe that prints OCR-friendly candidate output files and
sizes after runtime exits.

Output example:

```text
OF_OUTPUT_PROBE_FILE path=config/output_data.bin size=131072 sha256=<hex>
```

This phase does not compare values yet.

### Phase 2: Remote self-check skeleton

Add `runtime_value_check.py` that can:

```text
load RuntimeControlPlan
load reference file
attempt to locate output source
print PASS / FAIL / BLOCKED summary lines
```

If output source is unknown, it exits with a controlled blocked status and
prints `OF_OUTPUT_CHECK_END status=BLOCKED`.

### Phase 3: Functional maximum value check

Enable fp32 comparison for:

```text
functional_maximum_single_app
```

only after Phase 1 proves an output source.

### Phase 4: Integrate summary status into `validate_on_arch13.sh`

Add `output_check_status` to `summary.tsv`.  Keep terminal output concise and
OCR-friendly.

### Phase Later: Full artifact capture

When artifact access improves, add:

```text
run/<case>/outputs/*.bin
run/<case>/runtime_result.json
run/<case>/validation/output_reference.json
```

and make those reports consumable locally.

## Validation Plan

### Local tests

Synthetic tests can still cover the checker logic without real SimICT:

```text
fake runtime output source exists -> PASS/FAIL comparison
fake output source missing -> BLOCKED
reference missing -> BLOCKED
size mismatch -> FAIL or BLOCKED depending evidence
explicit tolerance pass/fail
OCR summary format is stable
```

### Remote tests

Initial remote target:

```text
functional_maximum_single_app
runtime_rc = 0
OF_OUTPUT_CHECK_END status = PASS | FAIL | BLOCKED
```

`BLOCKED` is acceptable until we identify the output memory source.  It is still
better than pretending runtime exit proves value correctness.

## Risks and Mitigations

### Risk: arch-13 cannot run Python checker

Mitigation: keep the checker simple and compatible with the available Python.
If needed, generate a shell/C/RISC-V-side checker later.

### Risk: output memory image cannot be found

Mitigation: report `BLOCKED` and keep the structural/runtime-exit validation
path useful.  Do not fake comparison.

### Risk: OCR corrupts long hashes or floats

Mitigation: print both status and short summaries.  Hashes are useful when
cleanly copied, but pass/fail/mismatch counts should remain readable even with
OCR noise.

### Risk: exact fp32 comparison is too strict

Mitigation: compare policy must be explicit and printed in the summary once
non-exact comparison is enabled.

### Risk: this duplicates work if simulator source arrives later

Mitigation: remote self-check is a bridge.  If simulator/runtime source arrives,
its evidence should replace guesses and feed the later full artifact mode.

## Expected Effect

Near term, a successful remote validation should mean:

```text
payload passed local RUNTIME_READY
runtime executed on arch-13
remote checker printed compact value evidence
```

If the checker is `BLOCKED`, we still learn something precise: the missing piece
is output-source access, not local binary packaging or control graph structure.

Long term, if artifact access improves, the same `RuntimeControlPlan` authority
can drive full local output capture and reference comparison.

## Open Questions

1. Does SimICT leave any stable file containing the post-runtime output DDR/SPM
   bytes that a remote script can read?
2. Is Python available and reliable enough on arch-13 for post-runtime checking?
3. If not, should the checker be shell, C, or RISC-V-side?
4. Should `BLOCKED` output checks fail the batch, or should the batch pass with
   `runtime_rc=0` and `output_check_status=BLOCKED` during the transition?
5. What exact tolerance is valid for future nontrivial fp32 ops such as log10?

## Recommended Decision

Accept the re-scoped direction.

Implement now:

```text
Phase 1: remote output source probe with OCR-friendly output
Phase 2: remote self-check skeleton that can PASS / FAIL / BLOCKED
Phase 3: functional_maximum_single_app fp32 comparison if output source is found
Phase 4: summary.tsv output_check_status integration
```

Defer until cooperation/access improves:

```text
local output artifact capture
full runtime_result.json archive
local output_reference.json archive
multi-launch output closure
simulator-source-backed extraction
```

The corrected boundary is: local `RUNTIME_READY` keeps bad packages away from
arch-13; remote self-checks provide the best value evidence available under
current permissions; full output artifact closure waits until the project has a
real way to access runtime outputs.
