# ChipEnv Examples

This directory contains examples for the refactored DFU-first `ChipEnv`
frontend.

The new examples intentionally model the chip-visible SRAM boundary:

```text
declare SRAM tensors
  -> load SRAM tensors into logical DTensors
  -> run logical SPMD compute ops
  -> store logical DTensors back to SRAM tensors
  -> bind named outputs
```

`ChipEnv.generate()` records the chip-level program and then runs the explicit
lowering pipeline through processor logical/tile programs, DFU packing, vendor
ABI rows, and binary component packaging.

Examples may also declare the restricted soft task axis explicitly:

```python
env.configure_task_axis(task_axis_size=4, physical_mesh_shape=(4, 4))
a = env.load(
    a_sram,
    placements=[TaskReplicate(), Shard(0), Replicate()],
)
c = env.set_task_placement(
    c,
    TaskShard("gemm_output_tiles", work_axis_order=("m_tile", "n_tile")),
)
```

The physical mesh shape is still owned by the chip config.  The optional
`physical_mesh_shape` argument is a developer-side assertion; if it disagrees
with the loaded device shape, `ChipEnv` raises instead of silently creating a
fake mesh.  `TaskReplicate` means every task requires equivalent input
visibility, not free cross-task sharing.

The placement list is now conceptually three-dimensional:

```text
[task_axis, pe_row, pe_col]
```

For the current runnable path, axis 0 must not be `TaskPartial`, and transform
passes must not rewrite axis 0 implicitly.  Any task-axis merge/reduction needs
an explicit strategy before binary lowering.

TODO: future strategy search may allow configurable mesh-axis order, but the
current API intentionally fixes task as axis 0 to keep DFU task isolation rules
visible and verifier-friendly.

## GEMM

```bash
python3 compiler/examples/gemm.py
```

Writes:

```text
tmp/gpdpu_compiler_chip_examples/gemm/chip_program.json
```

This example uses the current `dfu3500` config regions:

- `A`: `gemm_input1_a`, SRAM offset `0x00000`
- `B`: `gemm_input2_b`, SRAM offset `0x40000`
- `C`: `gemm_input3_c_or_output`, SRAM offset `0x80000`

It declares four task-axis work groups manually.  A/B are task-replicated input
requirements; C is task-sharded by GEMM output tile work units.

## GEMM + ReLU

```bash
python3 compiler/examples/gemm_relu.py
```

Writes:

```text
tmp/gpdpu_compiler_chip_examples/gemm_relu/chip_program.json
```

This is the first fused MLP-style shape we want to preserve at chip level:

```text
Y = relu(A @ B)
```

It uses the same four-task GEMM output-tile work-domain mapping as `gemm.py`.

## Elementwise Add + ReLU

```bash
python3 compiler/examples/elementwise_add_relu.py
```

Writes:

```text
tmp/gpdpu_compiler_chip_examples/elementwise_add_relu/chip_program.json
```

This example does not use the GEMM regions. It declares a small custom SRAM
layout to demonstrate that examples can still describe non-GEMM SRAM tensors
explicitly while `ChipEnv` loads the `dfu3500` logical fabric from chip config.
It declares `task_axis_size=1` because no task-axis strategy is selected yet.

## Audio Log10 + Global Max + Maximum

```bash
python3 compiler/examples/log10_maximum.py
```

Writes:

```text
tmp/gpdpu_compiler_chip_examples/log10_maximum/chip_program.json
tmp/gpdpu_compiler_chip_examples/log10_maximum/app_plan.json
tmp/gpdpu_compiler_chip_examples/log10_maximum/task_partition_plan.json
```

This is intentionally `AppPlan`-only for now. It models the audio preprocessing
fragment:

```text
log_spec = log10(clamp(mel_spec, min=1e-10))
global_max = reduce_max(log_spec)
out = maximum(log_spec, global_max - 8.0)
out = (out + 4.0) / 4.0
```

The app planner cuts the program into:

```text
app0: materialize global max
app1: reload input + global max, recompute local log tile, post-process
```

This deliberately avoids carrying PE-local log tiles across app boundaries.
It currently declares `task_axis_size=1`; task-axis collective/reduce strategies
are intentionally deferred until the compiler has a proven same-app collective
or materialization strategy.
