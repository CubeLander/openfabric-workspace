# DFU3500 Partner Validation

This package is the DFU3500 / SimICT runnable-baseline validation workflow.
It is no longer a binary-diff archaeology toolbox.  Its main job is to package
OpenFabric operator payloads locally and batch-validate them on `huake02@arch-13`.

See [`../../../../RUNNABLE_BASELINE.md`](../../../../RUNNABLE_BASELINE.md) for the baseline Git
pointer, artifact fingerprints, and resurrection notes.

## Layout

```text
build_payloads.py          local-side payload builder
run.sh                     one-button arch-13 entrypoint; edit before upload
validate_on_arch13.sh      remote-side batch runtime validator
scripts/*.sh               fixed arch-13 launcher commands with env defaults
payloads/<case>/           generated OpenFabric runtime payloads
smoke/current.sh           editable arch-13 smoke-test hook
tools/diff_vendor_bytes.py optional old-Python byte diff helper
sha256.txt                 payload fingerprint index
sizes.txt                  payload size index
```

Payload shape:

```text
payloads/<case>/MANIFEST.txt
payloads/<case>/result/cbuf_file.bin
payloads/<case>/result/micc_file.bin
payloads/<case>/config/cbuf_file.bin
payloads/<case>/config/micc_file.bin
payloads/<case>/simulator_bin/*
```

Current default payload:

```text
case_id=functional_maximum_single_app
app_name=CASE/softmax_1
task_num=1
vendor shell: CASE/softmax_1
```

## Local: Build Payloads

From repo root:

```bash
python3 compiler/gpdpu_compiler/validation/dfu3500_partner_validation/build_payloads.py
```

This regenerates every known payload under `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/payloads/` and refreshes:

```text
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/sha256.txt
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/sizes.txt
```

To build one case:

```bash
python3 compiler/gpdpu_compiler/validation/dfu3500_partner_validation/build_payloads.py --case log10max_single_task
```

## Local: Make Upload Bundle

From repo root:

```bash
./compiler/gpdpu_compiler/validation/dfu3500_partner_validation/scripts/package_upload_bundle.sh \
  dfu3500-validation.tgz
```

The package script first runs
`compiler/tools/check_partner_validation_entrypoint.py`.  That guard parses
`run.sh`, rebuilds the payloads it will actually select, and fails if
`payloads/<case>/` is stale or inconsistent with the generated RISC-V launch
configuration.

Then upload:

```bash
scp dfu3500-validation.tgz huake02@arch-13:/home/huake02/
```

## Remote: Batch Validate

On `huake02@arch-13`:

```bash
cd /home/huake02
tar -xzf dfu3500-validation.tgz
cd dfu3500_partner_validation
./run.sh
```

`run.sh` is the preferred control panel.  Future agents should edit it locally
before packaging to encode the exact payload/smoke they intend to run.  The
commander should only need the fixed remote command.  It currently defaults to generated payload validation.

Preferred fixed-command launchers:

```bash
# Smoke only: for quick instruction/control-flow experiments.
./scripts/run_smoke.sh

# Normal generated payload validation.
./scripts/run_payloads.sh

# Smoke first, then generated payloads.
./scripts/run_smoke_then_payloads.sh

# Verbose runtime for generated payloads.
./scripts/run_verbose_payloads.sh

# Rebuild vendor case result, then run generated payloads.
./scripts/run_payloads_with_vendor_refresh.sh
```

Workflow principle:

```text
Keep the upload bundle name fixed:
  dfu3500-validation.tgz

Prefer editing package scripts locally and re-uploading the bundle over typing
long environment-variable commands in nested arch-13 shell sessions.
```

The environment defaults live in:

```text
scripts/env_arch13.sh
```

If a test needs a different `SIMICT_ROOT`, `SMOKE_SCRIPT`, `RUNTIME_MODE`, or
other knob, the acting agent should edit `run.sh`, `scripts/env_arch13.sh`, or a
launcher script locally, rebuild `dfu3500-validation.tgz`, upload, and keep the
remote command unchanged.

Default arch-13 assumptions:

```text
SIMICT_ROOT=/project/home-new/huake02/simict3500final
PAYLOADS_DIR=./payloads
RUN_DIFF=0
RUN_PAYLOADS=1
RUN_SMOKE=0
RUNTIME_TIMEOUT_SECONDS=900
```

The validator stages each payload into the vendor runtime `config/` directory,
then runs SimICT.  New payloads should be self-contained and provide:

```text
runtime/input_data.bin
runtime/riscv_program
```

or:

```text
runtime/input_data.bin
runtime/riscv_src/riscv/testarm.c
runtime/riscv_src/csv_generate/conf.h
runtime/riscv_src/spm_data/data.h
```

When `runtime/riscv_program` is missing, the arch-13 script builds it from the
payload-local RISC-V source using the shared `dpuapi` and `common/src` under
`SIMICT_ROOT`.  This intentionally avoids depending on a vendor case directory
for input experiment data.  Older payloads may still fall back to
`testcase/application/<app_name>/input_data.bin` and `riscv/riscv`.

Runtime stdout/stderr is streamed to the console with `tee` and also saved to
`run/<case>/runtime.log`.  This is intentional: partner runtime experiments can
deadlock, so validation must stay visible in the shell instead of redirecting
everything silently to a file.  Set `RUNTIME_TIMEOUT_SECONDS=0` to disable the
timeout guard.

The run writes:

```text
run/summary.tsv
run/<case>/run.log
run/<case>/runtime.log
```

Useful knobs:

```bash
# Rebuild the vendor case result first with run.sh + run_mtr.sh <app> <task_num> 1.
REFRESH_VENDOR=1 ./validate_on_arch13.sh

# Stop after the first failing payload.
STOP_ON_FAIL=1 ./validate_on_arch13.sh

# Run runtime_verbose instead of runtime.
RUNTIME_MODE=verbose SIMICT_VERBOSE_AFTER=1000 ./validate_on_arch13.sh

# Change or disable the runtime timeout.
RUNTIME_TIMEOUT_SECONDS=1800 ./validate_on_arch13.sh
RUNTIME_TIMEOUT_SECONDS=0 ./validate_on_arch13.sh

# Run only the editable smoke hook.
RUN_SMOKE=1 RUN_PAYLOADS=0 ./validate_on_arch13.sh

# Run smoke first, then all generated payloads.
RUN_SMOKE=1 ./validate_on_arch13.sh
```

The knobs above remain available for emergencies, but the preferred workflow is
to encode them into `scripts/*.sh` before upload.

## Smoke Hook

For quick arch-13 experiments, edit:

```text
smoke/current.sh
```

Then rebuild/upload the bundle and run:

```bash
RUN_SMOKE=1 RUN_PAYLOADS=0 ./validate_on_arch13.sh
```

This is intentionally not a maintained payload registry.  Use it for small
instruction/runtime experiments such as:

```text
SHFL + FMAX reduction
FLOG2 spelling
single-task COPYT gather
```

Logs are written to:

```text
run/smoke/run.log
```

## Optional Diff Tool

`tools/diff_vendor_bytes.py` is deliberately outside the main validation path.
Use it only when a functional regression suggests the binary difference itself
matters:

```bash
RUN_DIFF=1 MAX_DIFF_BYTES=200000 ./validate_on_arch13.sh
```

The diff helper is old-Python compatible and only compares:

```text
payload result/cbuf_file.bin  vs vendor result/cbuf_file.bin
payload result/micc_file.bin  vs vendor result/micc_file.bin
```

No repeated section summaries or runtime/config duplicate comparisons are
emitted.
