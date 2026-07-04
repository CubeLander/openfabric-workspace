# Instance Config Generator Notes

This note documents the role of:

```text
application/CASE/softmax_1/csv_generate/test_app_conf_generate.c
```

## Role

The file is an instance-level memory layout generator. It does not generate the
operator instruction CSVs themselves. Instead, it generates the task/subtask
metadata and the per-instance base addresses that later stages use when
building the runtime package.

In the direct workflow, this phase produces:

```text
app0.conf ... app3.conf
csv_generate/instance_conf_info_file0.bin ... instance_conf_info_file3.bin
csv_generate/instance_conf_info_for_rtl_file0.bin ... instance_conf_info_for_rtl_file3.bin
```

The workflow then concatenates those files into:

```text
simulator_bin/instance_conf_info_file.bin
rtl_bin/cbufData_instance.bin
```

## What `app*.conf` Describes

`app*.conf` is a text description consumed later by the application builder. It
records:

```text
task name
subtask count
subtask names
instance count per subtask
template path
CSV count per subtask
graph height and width
```

For `softmax_1`, these values come mainly from:

```text
csv_generate/conf.h
  SUBTASK_NUM
  TASK_NUM
  PER_TASK_PE_NUMBER
  PER_TASK_INSTANCE_NUMBER
  PE_NUM_BASE
```

## What `instance_conf_info_file*.bin` Describes

Each instance config entry contains up to four base addresses:

```c
typedef struct _instance_conf_info_t {
  uint64_t base_addr[4];
} instance_conf_info_t;
```

For `softmax_1`, the initial addresses are supplied by
`Secondary_Fusion_Array` in `conf_PEmap.h`:

```text
SUM              -> 32768
softmax0_input0  -> 0
softmax0_output0 -> 16384
```

The generator writes the current base addresses for each instance, then advances
them according to the selected address-update rule.

## Meaning Of `mark_op`

`mark_op` is defined in `csv_generate/conf_PEmap.h`:

```c
#define mark_op "SOFTMAX"
```

Despite the name, it should be read as an address layout rule selector. The
generator is a reused elementwise/fusion template, so it still contains branches
for other layouts:

```text
RMSNORM
RMSNORM_TRANSPOSE
SOFTMAX
ROPE
ROPE_TRANSPOSE
SCALE
default
```

For the current `softmax_1` case, only the `SOFTMAX` branch is intended to be
active. The other branches are template leftovers for other operators and are
effectively dead code for this case.

## Important Refactor Boundary

Safe to extract into common code:

```text
app.conf writer format
instance_conf_info_t structs
RTL paired-write format
output file naming and aggregation
generated-file validation
```

Keep case-specific for now:

```text
subtask count calculation
instance count calculation
CSV count calculation
base address initialization
base address increment rule
operator/fusion memory layout policy
```

The better abstraction is therefore:

```text
common instance-config runner + common output contract
case-specific address-layout strategy
```

