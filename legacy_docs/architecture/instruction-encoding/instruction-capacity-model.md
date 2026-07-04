# Instruction Capacity Model

The DFU3500 `insts_file.bin` is a padded per-PE instruction RAM image:

```text
PE_AMOUNT * MAX_INST_AMOUNT_PER_PE = 16 * 4352 = 69632 inst_t records
```

## Vendor Capacity Model

Evidence from `task_print.cpp`:

```text
inst_t insts_c[MAX_INST_AMOUT_PER_PE];
...
for each PE:
  for each GRAPH_NODE/exeBlock:
    copy valid ld/cal/flow/st stage instructions into insts_c
...
write tmp insts_file for this PE
```

The important capacity question is:

```text
How many inst_t records are resident in each PE instruction RAM image?
```

not:

```text
How many semantic execution events happen across all instances?
```

## Legacy GEMM Evidence

The checked-in legacy `gemm_template_fusion` simulator blob is padded to the
same capacity:

```text
simulator_bin/insts_file.bin
  bytes   = 21168128
  records = 69632
```

Counting non-zero records inside the padded file:

```text
PE00/10/20/30: 3592 nonzero records
PE01/02/11/12/21/22/31/32: 3336 nonzero records
PE03/13/23/33: 3080 nonzero records
total nonzero: 53376
```

All are under 4352 records per PE.

## Instruction Template Reuse

The vendor execution model is closer to:

```text
one PE-local exeBlock instruction range
  reused by multiple subtask instances through instance_conf base_addr rows
```

than to:

```text
one complete instruction copy per instance event
```

Do not use `expanded_instruction_records = compute_events * template_size` as
the final `insts_file.bin` emission count. Use it only as a pessimistic
pressure upper bound until vendor instruction reuse/folding maps graph-level
repeated regions to PE instruction RAM ranges.

## Compression/Folding Space

The first folding target is K-instance reuse:

```text
gemm_update(k0)
gemm_update(k1)
gemm_update(k2)
gemm_update(k3)
```

If these differ only by `instance_conf.base_addr[]` and immediate offsets, they
should be emitted as:

```text
one exeBlock instruction range
4 subtask instances
```

not:

```text
4 instruction ranges
```

The second folding target is wave/template reuse. For the current GEMM shape,
each task has a regular C-wave region. If wave-local instruction shape is
identical except for base rows, offsets, or output tile identity, some of that
may also fold into shared vendor exeBlock templates.

## Naive vs Folded Counts For GEMM Baseline

Naive expansion:

```text
256 compute records * 576 template instructions = 147456 inst_t records
```

Where 256 compute records = 16 PE * 4 C waves * 4 K updates.

After K-instance folding:

```text
64 fold groups (1 per PE per C wave)
template_instruction_count = 576
folded_compute_inst = 64 * 576 = 36864
capacity = 69632
folded capacity_ok = true
```

Per PE:

```text
fold_groups = 4
assigned_compute_inst = 2304
capacity = 4352
unused = 2048
capacity_ok = true
```
