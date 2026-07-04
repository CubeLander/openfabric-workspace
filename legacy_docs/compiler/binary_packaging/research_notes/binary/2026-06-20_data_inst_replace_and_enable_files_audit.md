# data_inst_replace / Enable Files Audit

Date: 2026-06-20

Status: binary note, source audit for auxiliary simulator/RTL files

This note records what we currently know about:

```text
data_inst_replace.bin
instEnable.bin
taskEnable.bin
```

These files are easy to over-interpret.  A-line taught us that guessing runtime
control semantics from auxiliary files is a trap, so this note is deliberately
conservative.

## Source Fingerprints

Relevant clean headers and writer:

```text
a336aca7dec1f40a666f1ef45affb5048e3dcf3e79bb155663faef8c8f1218b7  common/src/basic_def.h
d9c1af31a926e3f960706827f0bd15df7676656f2b491325f226637b48a1bef2  testcase/common_oper/task_print.cpp
```

Relevant scripts/docs:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/workflow/scripts/build_package.sh
simict3500final/gpdpu/users/risc_nn_riscv/test/README.md
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/validate_on_arch13.sh
```

## 1. File Names Come From `basic_def.h`

Source evidence:

```text
common/src/basic_def.h:22-33
```

Relevant defines:

```text
DATA_INST_REPLACE_FILE_NAME = "data_inst_replace.bin"
INSTS_FOR_RTL_FILE_NAME     = "cbufData_inst.bin"
MICC_INFO_FOR_RTL_FILE_NAME = "miccData_task.bin"
MICC_SUB_INFO_FOR_RTL_FILE_NAME = "miccData_subtask.bin"
CHAR_PER_LINE_IN_REPLACE_FILE = 2
```

### B-line implication

`data_inst_replace.bin` is a named vendor artifact, but its source definition is
only a filename/line-width hint.  The filename alone does not prove runtime data
patch semantics.

## 2. Writer Emits Fixed Minimal Content

`Print_Task_Group::task_inst_enable_print()` opens three files:

```text
./rtl_bin/instEnable.bin
./rtl_bin/taskEnable.bin
./simulator_bin/data_inst_replace.bin
```

Source evidence:

```text
task_print.cpp:801-829
```

For `application_num = 1`, it writes:

```text
instEnable.bin:
  1\n
simulator_bin/data_inst_replace.bin:
  1 1\n
rtl_bin/taskEnable.bin:
  one line of MAX_CUR_TASK_CONF_PER_APP chars
  early slots = 0
  last task_num slots = 1
```

This means local source does not generate rich data replacement rows.  It emits a
fixed-looking marker:

```text
1 1
```

### B-line implication

Until we find a runtime consumer, B-line should treat `data_inst_replace.bin` as a
required compatibility artifact for payload packaging, not as proven executable
semantics.

Required owner candidate:

```text
AuxiliaryArtifactPlan:
  data_inst_replace content policy
  instEnable content policy
  taskEnable content policy
  status = compatibility_required | runtime_semantic_proven
```

## 3. Package Scripts Append It Separately From CBUF/MICC

`build_package.sh` creates empty multi-app files, then after `build_app` appends:

```text
simulator_bin/insts_file.bin              -> simulator_bin_multi_app/cbuf_file.bin
simulator_bin/exeblock_conf_info_file.bin -> simulator_bin_multi_app/cbuf_file.bin
simulator_bin/instance_conf_info_file.bin -> simulator_bin_multi_app/cbuf_file.bin
simulator_bin/tasks_conf_info_file.bin    -> simulator_bin_multi_app/micc_file.bin
simulator_bin/subtasks_conf_info_file.bin -> simulator_bin_multi_app/micc_file.bin
simulator_bin/data_inst_replace.bin       -> simulator_bin_multi_app/data_inst_replace.bin
```

Source evidence:

```text
testcase/workflow/scripts/build_package.sh:222-231
testcase/workflow/scripts/build_package.sh:276-283
testcase/workflow/scripts/build_package.sh:305-307
```

The test README records the same flow:

```text
test/README.md:203-216
test/README.md:336-352
```

### B-line implication

`data_inst_replace.bin` is not part of observed `cbuf_file.bin` or `micc_file.bin`.
It is copied as a separate `result/` artifact.

This aligns with A-line payload handling:

```text
result/cbuf_file.bin
result/micc_file.bin
result/data_inst_replace.bin
```

## 4. Runtime Staging Copies It If Present

The partner validation script copies it into runtime `config/` only if it exists:

```text
if payload/result/data_inst_replace.bin exists:
  cp to config/data_inst_replace.bin
```

Source evidence:

```text
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/validate_on_arch13.sh:267-271
```

The vendor test README also shows `config/data_inst_replace.bin` after staging:

```text
test/README.md:385-400
```

However, current source search did not find a C/C++ runtime consumer in the local
clean source tree beyond filename generation/staging.

### B-line implication

For now:

```text
emit it for compatibility
copy it when present
but do not derive runtime task count, instruction count, or data-layout semantics from it
```

## 5. `taskEnable.bin` Looks RTL-oriented, Not Runtime-authoritative

The writer's `taskEnable.bin` uses a reversed-looking pattern:

```text
for i in 0..MAX_CUR_TASK_CONF_PER_APP-1:
  if i < MAX_CUR_TASK_CONF_PER_APP - task_num:
    write 0
  else:
    write 1
```

Source evidence:

```text
task_print.cpp:816-823
```

For `task_num = 1`, this produces:

```text
0001
```

But active task rows are written from task index 0 in the simulator task/subtask
component flow.  Therefore `taskEnable.bin` must not be used as source of truth
for MicC active task rows without more evidence.

### B-line implication

Runtime launch count and active task ids should come from `TaskControlPlan` /
`RuntimeControlPlan`, not from `taskEnable.bin`.

## 6. Current Evidence Classification

| Artifact | Current evidence | Safe B-line treatment |
| --- | --- | --- |
| `data_inst_replace.bin` | writer emits `1 1`; scripts append/copy; no local consumer found | emit/copy as compatibility artifact; semantics unproven |
| `instEnable.bin` | writer emits `1`; packed into RTL multi-app artifact | RTL/debug collateral unless runtime consumer found |
| `taskEnable.bin` | writer emits reversed-looking active mask; packed into RTL artifact | RTL/debug collateral; do not use for runtime task count |

## 7. Immediate Verifier / Packaging Rules

```text
1. Payloads may include `result/data_inst_replace.bin`; absence/presence should be explicit in manifest.
2. If emitted by current compatibility path, content should be deterministic (`1 1\n` for one app) unless proven otherwise.
3. Runtime task_count must not be inferred from taskEnable.bin.
4. cbuf/micc byte-size checks must not include data_inst_replace bytes.
5. Any future semantic use of data_inst_replace must cite a runtime consumer or remote evidence.
```

## Remaining Research Gaps

```text
1. Find the SimICT/runtime consumer, if any, of `config/data_inst_replace.bin`.
2. Determine whether `CHAR_PER_LINE_IN_REPLACE_FILE = 2` has a real parser contract.
3. Confirm whether arch-13 emits content other than `1 1` for multi-app / duplicate-app cases.
4. Decide whether OpenFabric should always emit this file for vendor compatibility.
5. If semantic, define typed row schema; if not, keep as auxiliary compatibility artifact.
```

## Parallel Audit Addendum

A wider source search found writer and staging evidence only.  No local
runtime/SimICT source-level consumer was found for `data_inst_replace.bin`,
`instEnable.bin`, or `taskEnable.bin`.  Local packaging and validation scripts may
copy the sidecar into `config/`, but OpenFabric should keep it optional and must
not count it toward runtime readiness, CBUF/MICC size checks, or active task
selection.
