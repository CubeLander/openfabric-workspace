# Softmax Original Materials Audit

Date: 2026-06-20

Status: case-specific audit card

This note summarizes what the original `softmax详解.pptx` contributes to
OpenFabric.  It should be used as source evidence for staged non-GEMM operators,
not as a template to blindly copy into probes.

## Source Material

```text
tmp/华科算子库编写/7、softmax详解.pptx
```

Runtime/source implementation:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/CASE/softmax_1
```

Existing OpenFabric references:

```text
docs/vendor_reference/cases/softmax/softmax-current-real-workflow.md
docs/vendor_reference/cases/softmax/softmax-case-walkthrough.md
compiler/notes/log10max/README.md
```

## Shape And Case Facts

The PPT describes the current softmax case as:

```text
data type: fp16
input: 1 x 512
batch: 64
app_num: 1
TASK_NUM: 4
SUBTASK_NUM: 3
PE_NUM: 16
```

It also says this case does not need app splitting and can use simple transfer.

### Compiler implication

`app_num=1` here is a concrete case fact, not a general theorem.  It supports
the distinction:

```text
OpenFabric semantic app boundary != vendor task row != vendor appN.conf file
```

## Task And PE Mapping

The PPT maps the 64 batches over:

```text
4 tasks x 16 PEs
```

Each PE handles one row/batch at a time; larger batch counts are handled through
hardware loop/instance repetition.

### Compiler implication

This is direct evidence for the B-line soft task axis idea:

```text
soft processor = (task_id, physical_pe_id)
```

It also reinforces that task rows partition independent work.  They are not a
safe place to hide cross-task dependencies unless an explicit collect/materialize
strategy exists.

## Reduction Structure

The PPT decomposes PE-local softmax reduction into:

```text
1. inter-register accumulation: ADD/FADD family
2. intra-register lane reduction: SHFL chain
3. instance accumulation: not used in this specific case
```

For the implemented `softmax_1` case, representative CSVs show subtask1 doing
exp/sum and subtask2 reloading sum for normalize/store.  This is evidence that
non-GEMM staged operators can be encoded as multiple subtasks inside one runtime
case, but the dependency and storage path must be explicit.

### Compiler implication

For `log10max`, the source-backed conservative path is:

```text
local lane compute
  -> PE-local or row-local reduction pattern
  -> explicit materialization / reload if a later phase needs the result
```

Do not infer from softmax that arbitrary allreduce across task rows is free.
The PPT describes a concrete row-wise case with explicit subtask shape.

## Runtime Sequence

The associated `testarm.c` loads CBUF/MICC, transfers input to SPM, starts the
kernel, waits for completion, and transfers output back.  The runtime-control
facts are tracked in:

```text
docs/vendor_reference/runtime_evidence/runtime-control-source-audit.md
```

## Current Status

```text
Extracted:
  PPT shape/task/PE/reduction facts are identified.

Absorbed:
  This note and existing softmax workflow notes now record them.

Operationalized:
  Partial.  Current A-line functional probe does not implement softmax/log10max.
  B-line stream/fiber design can use these facts for staged non-GEMM planning.

Runtime-proven:
  Vendor `softmax_1` is a real workflow.  OpenFabric log10max is not yet a
  functional softmax-derived runnable path.
```
