# DFU3500 `instance_conf_info_file.bin` Investigation

Date: 2026-06-15

## Summary

这次调查的核心结论是：

```text
instance_conf_info_file.bin 在 legacy DFU3500 / SimICT workflow 里是固定物理槽位表，
不是只包含 active subtask instances 的 compact 表。
```

当前 OpenFabric `ProgramBinRows` 已经把 `task_conf_info_t` /
`sub_task_conf_info_t` 的 active row 控制表对齐到 legacy，但
`instance_conf_info_file.bin` 仍然只填 active semantic rows，其他位置留 0。
这和甲方原始实现不一致。

更精确地说：

```text
task/subtask MICC table:
  active subtask control rows are sparse by task 8-slot window.

instance_conf_info_file.bin:
  physical table is 4 tasks * 8 subtasks * 2048 instances.
  every physical row is written by testcase generator.

instances_conf_mem_based_addr:
  still comes from task_print.cpp active-instance counter.
  It must not be used as proof that the physical instance table is compact.
```

这不是一个单纯的 byte-parity 问题。`instance_conf_info_t.base_addr[4]`
直接参与 PE 侧有效地址计算：

```text
effective_addr = base_addr[base_addr_idx] + imm
```

所以这张表是 runtime 地址环境的一部分。

## Sources Checked

### Local Refactored Notes

`docs_refactored/runtime/data/cbuf.md` already records the important layout
facts:

```text
instance_conf_info_file.bin = 2,097,152 B
                            = 4 task * 8 subtask * 2048 instance * 32 B
```

and:

```text
instance_conf_info_t:
  base_addr[0..3]

effective_addr = base_addr[base_addr_idx] + imm
```

The document also states that `instance_conf_info_file.bin` is finally written
as a fixed slot table. This investigation found original-vendor evidence that
supports that direction.

### Vendor Generator

The strongest generation-side evidence is:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/build_out/gemm_template_fusion/worktree/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/csv_generate/test_app_conf_generate.c
```

Relevant observations:

1. The generator loops over four task files:

```c
for (int j = 0; j < 4; j++) {
    sprintf(basepath, "instance_conf_info_file%d.bin", j);
    ...
}
```

2. Inside each task file, it loops over `MAX_SUBTASK_NUM`.

3. For each subtask branch, it writes up to `2048` instance rows.

4. For GEMM:

```text
subtask n == 0:
  base_addr[0] = SPM_GEMM_INPUT3_ADDR
  base_addr[1..3] = 0xffffffff

subtask n == 1:
  base_addr[0] = SPM_GEMM_INPUT1_ADDR
  base_addr[1] = SPM_GEMM_INPUT2_ADDR
  base_addr[2..3] = 0xffffffff
  then increments base_addr[0] and base_addr[1] per instance

subtask n == 2:
  base_addr[0] = SPM_GEMM_INPUT3_ADDR
  base_addr[1..3] = 0xffffffff

inactive / otherwise:
  base_addr[0..3] = 0xffffffff
```

5. The case `csv_generate/run.sh` concatenates the four task-local files:

```sh
for((i=0;i<4;i++))
do
    cat instance_conf_info_file$i.bin >> instance_conf_info_file.bin
done
```

This proves that the physical instance table is task-windowed and fixed-size.

### Vendor CBUF Transfer

The RISC-V runtime does not transfer instance config as a standalone compact
side table for this flow. It calls:

```c
DPU_CbufTransfer((void*)CBUF_DDR_ADDR);
```

`DPU_CbufTransfer()` transfers the combined `cbuf_file.bin` layout:

```text
insts_file.bin
+ exeblock_conf_info_file.bin
+ instance_conf_info_file.bin
```

The CBUF DMA size in `DpuAPI.c` covers this combined region.

### Vendor Kernel Start

`DPU_Kernel_Start()` writes:

```c
*(unsigned*)MICC_INSTANCE_BASE = (unsigned)instance_base;
*(unsigned*)MICC_INSTANCE_BASE_NONEED = (unsigned)instance_base_noneed;
```

So runtime instance addressing has at least two layers:

```text
1. static CBUF instance table
2. runtime MICC_INSTANCE_BASE / optional NONEED field
```

This explains why `instances_conf_mem_based_addr` alone is insufficient to
infer the physical row address.

### Vendor Task/Subtask Printer

The task/subtask printer writes:

```c
sub_task_conf_info.instances_conf_mem_based_addr =
    m_instance_start_idx * sizeof(instance_conf_info_t);
m_instance_start_idx += task.m_subtasks[i].instance_times;
```

This is active-instance compact metadata. It is a MICC subtask field.

But the same legacy package still uses a fixed physical
`instance_conf_info_file.bin`. Therefore:

```text
instances_conf_mem_based_addr compactness
  !=
instance_conf_info_file.bin physical compactness
```

This distinction is the main trap.

## Observed Legacy Rows

Using the generated legacy file:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/build_out/gemm_template_fusion/worktree/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/simulator_bin/instance_conf_info_file.bin
```

Observed size:

```text
bytes = 2,097,152
rows  = 65,536
```

Important physical rows:

```text
row 0:
  (0x20000, 0xffffffff, 0xffffffff, 0xffffffff)

row 2048:
  (0x0, 0x10000, 0xffffffff, 0xffffffff)

row 2049:
  (0x20, 0x14000, 0xffffffff, 0xffffffff)

row 2050:
  (0x40, 0x18000, 0xffffffff, 0xffffffff)

row 4096:
  (0x20000, 0xffffffff, 0xffffffff, 0xffffffff)

row 6144:
  (0xffffffff, 0xffffffff, 0xffffffff, 0xffffffff)

row 16384:
  (0x20000, 0xffffffff, 0xffffffff, 0xffffffff)

row 32768:
  (0x20000, 0xffffffff, 0xffffffff, 0xffffffff)
```

This exactly matches the generator pattern:

```text
task 0 subtask 0 window begins at row 0
task 0 subtask 1 window begins at row 2048
task 0 subtask 2 window begins at row 4096
task 0 inactive subtask 3 begins at row 6144
task 1 begins at row 16384
task 2 begins at row 32768
```

Physical row formula:

```text
physical_instance_row =
  task_index * 8 * 2048
  + local_subtask_index * 2048
  + instance_index
```

## Current OpenFabric Mismatch

Current OpenFabric code path:

```text
compiler/gpdpu_compiler/core/program_bin.py::_build_instance_conf_rows()
```

currently allocates instance rows compactly:

```text
global_row_index = 0
for active vendor_subtask:
  for instance_key in subtask.instance_keys:
    row.global_row_index = global_row_index
    global_row_index += 1
```

Current serializer:

```text
compiler/gpdpu_compiler/core/program_serializer.py::_serialize_instance_conf_component()
```

allocates the full 65,536-row buffer, but only writes rows present in
`bin_rows.instance_rows`. Unwritten rows remain zero.

So the current binary shape is:

```text
file size:
  correct

active semantic row count:
  compact 24 rows

physical row placement:
  wrong for legacy DFU3500

inactive/filler rows:
  zero-filled, not legacy 0xffffffff or role-specific defaults
```

## Important Distinctions

### 1. Subtask Row Index Policy Is Already Separate

Task/subtask control table indexing uses:

```text
global_subtask_row = task_index * 8 + local_subtask_index
```

This was correct for MICC rows and should stay separate from instance rows.

### 2. Instance Rows Need Physical Fixed Windows

`instance_conf_info_file.bin` uses:

```text
task_index * 8 * 2048 + local_subtask_index * 2048 + instance_index
```

This is different from compact active subtask row allocation.

### 3. `instances_conf_mem_based_addr` Still Needs Care

The vendor `task_print.cpp` writes active-instance compact offsets. The exact
MICC internal formula likely combines:

```text
MICC_INSTANCE_BASE
subtask_idx / task_idx
instances_conf_mem_based_addr
instance_idx
possibly MICC_INSTANCE_BASE_NONEED
```

We do not yet have the closed simulator source proving the final formula.

Practical consequence:

```text
Do not infer physical CBUF row placement from instances_conf_mem_based_addr alone.
```

For byte/package parity and safer simulator bring-up, the physical file should
match the legacy fixed-window table.

## Recommendation

Implement a DFU3500 legacy instance table placement policy:

```text
dfu3500_legacy_instance_conf_row_index(
    task_index,
    local_subtask_index,
    instance_index,
) =
    task_index * 8 * 2048
    + local_subtask_index * 2048
    + instance_index
```

Then build rows for all physical windows:

```text
for each task in 0..3:
  for each local subtask slot in 0..7:
    for each instance slot in 0..2047:
      emit an InstanceConfBinRow
```

Row values:

```text
active GEMM subtask 0:
  base_addr[0] = SPM_GEMM_INPUT3_ADDR
  base_addr[1..3] = 0xffffffff

active GEMM subtask 1:
  base_addr[0] = SPM_GEMM_INPUT1_ADDR + instance_idx * A_stride
  base_addr[1] = SPM_GEMM_INPUT2_ADDR + instance_idx * B_stride
  base_addr[2..3] = 0xffffffff

active GEMM subtask 2:
  base_addr[0] = SPM_GEMM_INPUT3_ADDR
  base_addr[1..3] = 0xffffffff

inactive slots:
  base_addr[0..3] = 0xffffffff
```

Keep a separate semantic report for active rows:

```text
semantic_active_instance_rows = 24
physical_instance_rows = 65536
```

This prevents future agents from mistaking the full table for 65,536
semantically executed instances.

## Open Questions

1. Does `instances_conf_mem_based_addr` need to be changed after fixed-window
   physical placement?

   Current evidence says **not yet**. `task_print.cpp` writes compact offsets,
   and task/subtask row parity already matches legacy. Change only if simulator
   traces prove it.

2. Should we implement only active windows or all 65,536 rows?

   For SimICT/vendor bring-up and byte-level diff, implement all 65,536 rows.
   The file is fixed capacity and legacy fills every row.

3. Should this policy live in generic `program_bin.py`?

   No. This is DFU3500 / legacy SimICT ABI behavior. Keep the formula and
   constants named with `dfu3500_legacy_*` or under `core/dfu3500`.

