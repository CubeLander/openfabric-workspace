# Remote `result/` / `config/` Diff Runtime-State Notes

Date: 2026-06-15

Scope: `gemm_template_fusion` arch-13 vendor workflow versus local vendor workflow
outputs.

## 1. Why This Note Exists

Earlier comparisons looked at `simulator_bin/*.bin` component files. That was
the wrong primary runtime target: `run_mtr.sh` cats component files into
`result/cbuf_file.bin` and `result/micc_file.bin`, and `run_app_riscv.sh` copies
`result/` into test-time `config/`.

This note records the new comparison that targets:

```text
case result:
  testcase/application/gemm_template_fusion/result/cbuf_file.bin
  testcase/application/gemm_template_fusion/result/micc_file.bin

runtime config:
  test/config/cbuf_file.bin
  test/config/micc_file.bin
```

The OCR source was a run of:

```text
local_vendor_result_diff_bundle_20260615_202234/run_diff_on_arch13.sh
```

on arch-13.

## 2. Captured Environment

```text
date=2026-06-15T20:38:30+0800
host=arch-13
APP_NAME=gemm_template_fusion
SIMICT_ROOT=/project/home-new/huake01/simict3500final
REMOTE_CASE=/project/home-new/huake01/simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion
TEST_ROOT=/project/home-new/huake01/simict3500final/gpdpu/users/risc_nn_riscv/test
LOCAL_ROOT=/home/huake02/local_vendor_result_diff_bundle_20260615_202234/local_vendor_gemm
```

## 3. Top-Level File Results

### 3.1 Case `result/cbuf_file.bin`

```text
local_size=23531520
local_sha=2e83d38ba24ba3a55c7920e971b1493706a330bb66bf3ca7bb74a69ace3c29cb

remote_size=2097152
remote_sha=3b9d70247acc9832d71d73ec88f044d5b083aea7f07a42c191e90fb994b19414

status=DIFF
```

Important: `2097152` bytes equals the size of
`instance_conf_info_file.bin`.

### 3.2 Case `result/micc_file.bin`

```text
local_size=8522976
local_sha=17e78755ceb408f19b222640dcdcdfdd27f53338b81cbe07e57516b6dc695978

remote_size=0
remote_sha=e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855

status=DIFF
```

Important: `e3b0...` is SHA256 of an empty file.

### 3.3 Runtime `test/config`

```text
remote test/config/cbuf_file.bin: MISSING
remote test/config/micc_file.bin: MISSING
```

Therefore the observed arch-13 filesystem state was **not** a complete runtime
input state after a successful `run_app_riscv.sh` run.

## 4. Local Vendor Blob Layout

The local vendor workflow output used in this comparison has:

```text
local result/cbuf_file.bin = 23531520 bytes
  insts_file.bin              21168128 bytes = 69632 * 304
  exeblock_conf_info_file.bin   266240 bytes =   512 * 520
  instance_conf_info_file.bin  2097152 bytes = 65536 * 32

local result/micc_file.bin = 8522976 bytes
  tasks_conf_info_file.bin         480 bytes =  4 * 120
  subtasks_conf_info_file.bin  8522496 bytes = 32 * 266328
```

This layout is still consistent with the local reconstructed vendor workflow
and with OpenFabric's current serializer layout.

## 5. What The Remote State Proves

The remote `result/cbuf_file.bin` captured by the diff appears to contain only
the 2MB `instance_conf_info_file.bin` payload:

```text
remote result/cbuf_file.bin size = 2097152
remote result/cbuf_file.bin sha  = 3b9d70247acc...
```

The remote `result/micc_file.bin` captured by the diff is empty:

```text
remote result/micc_file.bin size = 0
```

Combined with missing runtime `test/config/cbuf_file.bin` and
`test/config/micc_file.bin`, this does **not** describe a valid runtime state
for a simulator run that completed successfully.

## 6. What This Does *Not* Prove

Do not conclude from this OCR run alone that:

```text
arch-13 runtime intentionally uses a folded 2MB-only cbuf layout
```

or:

```text
arch-13 runtime intentionally drops micc_file.bin
```

Those conclusions conflict with `run_app_riscv.sh`, which copies `result/` into
`test/config`, and with the simulator requirement for CBUF/MICC config files.

The safer conclusion is:

```text
The compared arch-13 directory was not the directory state used by the
successful simulator execution, or it was observed after a later failed/partial
build/clean state.
```

This is the small but important ghost in the machine: we were probably looking
at the correct filenames, but at the wrong moment/state.

## 7. Working Hypotheses

### Hypothesis A: Stale or partial build state

`run_mtr.sh` may have failed or been interrupted after writing
`instance_conf_info_file.bin` and before writing/concatenating inst/exeBlock and
MICC content. Because the shell scripts do not consistently use `set -e`, a
partial result can remain on disk.

Evidence:

```text
result/cbuf_file.bin == instance_conf_info_file.bin
result/micc_file.bin == empty
test/config/*.bin == missing
```

### Hypothesis B: Successful run used another `config/` state

The simulator run that completed successfully may have happened before the
observed filesystem state, and later commands may have cleaned or overwritten
`result/` / `config/`.

Evidence:

```text
test/config/cbuf_file.bin == missing
test/config/micc_file.bin == missing
```

A currently missing `test/config` cannot be the exact runtime input state of a
completed simulator run.

### Hypothesis C: Different wrapper/user/current directory

The user may have run a wrapper that copied/used another config directory, or
the compare was run in a different account/path state than the successful
runtime invocation.

Evidence:

```text
host=arch-13
user/path context in OCR comes from /home/huake02 bundle,
while SIMICT_ROOT is /project/home-new/huake01/simict3500final.
```

This is not necessarily wrong, but it means runtime state should be captured
immediately inside the workflow.

## 8. Required Next Probe

To settle this, capture file sizes and SHA immediately inside
`run_app_riscv.sh`:

1. after `run_mtr.sh`,
2. after `cp testcase/application/${app_name}/result ./config -r`,
3. after runtime exits.

Suggested insert after the copy into `config`:

```bash
echo "=== CONFIG AFTER COPY ==="
pwd
ls -lh config
sha256sum config/cbuf_file.bin config/micc_file.bin config/input_data.bin 2>/dev/null || true
wc -c config/cbuf_file.bin config/micc_file.bin config/input_data.bin 2>/dev/null || true
```

Suggested insert after runtime:

```bash
echo "=== CONFIG AFTER RUNTIME ==="
ls -lh config
sha256sum config/cbuf_file.bin config/micc_file.bin 2>/dev/null || true
wc -c config/cbuf_file.bin config/micc_file.bin 2>/dev/null || true
```

Also capture case `result/` immediately after `run_mtr.sh`:

```bash
echo "=== CASE RESULT AFTER run_mtr ==="
ls -lh testcase/application/${app_name}/result
sha256sum testcase/application/${app_name}/result/cbuf_file.bin \
          testcase/application/${app_name}/result/micc_file.bin 2>/dev/null || true
wc -c testcase/application/${app_name}/result/cbuf_file.bin \
      testcase/application/${app_name}/result/micc_file.bin 2>/dev/null || true
```

## 9. Current Actionable Conclusion

The local-vs-remote binary-content diff cannot be interpreted yet, because the
remote `result/` and `config/` inputs captured in this run were incomplete.

Before continuing field-level parity work, obtain a remote snapshot from the
same successful simulator run state:

```text
case result/cbuf_file.bin
case result/micc_file.bin
test/config/cbuf_file.bin
test/config/micc_file.bin
```

If that snapshot still shows `result/cbuf_file.bin=2MB` and `micc=0B` while the
simulator completed, then the workflow is not using these files and we need to
trace the runtime file opens directly. Until then, the likely issue is state
capture timing, not a new 2MB-only vendor format.

