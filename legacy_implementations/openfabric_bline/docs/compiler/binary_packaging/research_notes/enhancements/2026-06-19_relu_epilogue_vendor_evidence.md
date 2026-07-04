# ReLU Epilogue Vendor Evidence

Date: 2026-06-19

## Summary

DFU3500 has instruction-level capability to implement ReLU:

```text
relu(x) = max(x, 0)
```

The SIMD instruction set documents `FMAX`, `HMAX`, and integer `MAX` as
lane-wise max operations:

- `docs/architecture/instruction-set/dfu3500-simd/instruction_cards.md:421`
  documents `FMAX` as fp32 lane-wise max.
- `docs/architecture/instruction-set/dfu3500-simd/instruction_cards.md:723`
  documents `HMAX` as fp16 lane-wise max.
- `docs/architecture/instruction-set/dfu3500-simd/instruction_cards.md:886`
  documents integer `MAX`.

The vendor GEMM template source also contains an explicit ReLU code generator in
`subtask4`:

```text
IMM ZERO_relu...
HMAX ZERO_relu, input, output
```

See:

- `simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/task0/subtask4/template/new_temp.cpp:173`

This proves the vendor source tree knows how to lower ReLU as `zero + HMAX`.

## Current Runnable Package Evidence

The currently generated / observed `gemm_template_fusion` app config does **not**
include `subtask4`:

- `simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/app0.conf:1`
  says `subtask_num:3`.
- The listed subtasks are only `subtask1`, `subtask2`, and `subtask3`.

`subtask4` is conditional:

- `simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/gpdpu_tensor/task_main.cpp:41`
  only invokes `do_task*_subtask4` when `SUBTASK_COUNT == 4`.
- `simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/gpdpu_tensor/Makefile:3`
  defaults `SUBTASK_COUNT ?= 3`.
- `simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/csv_generate/test_app_conf_generate.c:34`
  emits `subtask_num = 3` when `Secondary_Fusion_Array` is empty.
- `simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/csv_generate/conf_PEmap.h:45`
  currently defines `Secondary_Fusion_Array = {}`.

The generated build tree confirms no final `subtask4/template/*.csv` files are
present for the observed package, while `subtask3` has 16 store templates.

The current `subtask3` template evidence is store-only:

```text
task*/subtask3: ops={STD}
```

Therefore current `subtask3` does not prove ReLU.  It only proves tile store.

## Result Check Clue

`spm_data/result_check.c` contains ReLU reference snippets, but they are
commented out in the currently inspected source:

- `simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/spm_data/result_check.c:838`
- `simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/spm_data/result_check.c:914`
- `simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/spm_data/result_check.c:933`

This supports the interpretation that the currently runnable package is a GEMM
package with optional fusion scaffolding available, not necessarily an active
GEMM+ReLU package.

## B-line Implication

`accumulator_finalize` and `epilogue:relu` must be treated differently:

```text
accumulator_finalize
  can be proven as a zero-instruction accumulator/value boundary.

epilogue:relu
  is implementable on DFU3500 via IMM + HMAX/FMAX,
  but remains unproven for the current 3-subtask runnable package.
```

The correct current B-line status is:

```text
epilogue:relu:
  semantic_kind = local_elementwise_epilogue
  capability    = supported_by_instruction_set
  package_proof = unproven_for_current_3_subtask_package
  candidate     = subtask4_zero_plus_HMAX_when_secondary_fusion_enabled
```

Do not mark `epilogue:relu` as proven from current `subtask3` store evidence.
It can become proven only when one of these evidence paths is attached:

1. active `subtask4` CSV rows containing `IMM ZERO_relu` and `HMAX/FMAX`;
2. a documented store-side fused activation modifier;
3. a separate explicit local elementwise epilogue template bound by the new
   compiler path.
