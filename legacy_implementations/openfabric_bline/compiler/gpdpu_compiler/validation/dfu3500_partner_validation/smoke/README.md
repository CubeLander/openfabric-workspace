# Smoke Scripts

This directory is a deliberately thin arch-13 smoke-test hook.

The normal validation path runs generated payloads under `payloads/*`.  Smoke
scripts are for quick experiments that are not ready to become maintained
payload cases yet, for example:

- `SHFL + FMAX` reduction experiments derived from `softmax_1`.
- `FLOG2` assembler/runtime acceptance tests.
- single-task `COPYT` gather experiments.
- one-off hand-patched vendor case runs.

## Usage

Edit:

```text
smoke/current.sh
```

Package and upload the validation bundle, then run on `huake02@arch-13`:

```bash
./run.sh
```

`run.sh` usually points at the workflow the acting agent wants to run.  For
smoke-only validation, point it at `scripts/run_smoke.sh` locally before
packaging.

For agents: to run smoke first and then the normal generated payloads, point
`run.sh` at:

```bash
exec "$SCRIPT_DIR/scripts/run_smoke_then_payloads.sh"
```

Agents should change `run.sh` and/or `smoke/current.sh`, then re-upload
`dfu3500-validation.tgz`, rather than asking the commander to type ad-hoc
environment variables in the remote shell.  The remote
servers often involve nested shell sessions; fixed package scripts are the
least error-prone workflow.

Logs are overwritten under:

```text
run/smoke/run.log
```

## Available Environment

`validate_on_arch13.sh` exports these variables before invoking `current.sh`:

```text
SIMICT_ROOT
VENDOR_HOME
RISC_ROOT
CONFIG_ROOT
BUILD_APP_DIR
RUNTIME_BIN
RUNTIME_VERBOSE_BIN
RUNTIME_MODE
SIMICT_VERBOSE_AFTER
OUT_DIR
SMOKE_OUT
SCRIPT_DIR
```

Keep smoke scripts simple.  They are intentionally not a second payload
framework.
