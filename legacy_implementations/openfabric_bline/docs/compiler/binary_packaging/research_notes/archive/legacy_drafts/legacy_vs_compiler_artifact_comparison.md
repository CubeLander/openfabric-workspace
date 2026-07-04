# Legacy vs Compiler GEMM Artifact Comparison

## Current baseline

- Legacy build command:
  - `DUPLICATE_APPLICATION_AMOUNT=4 APP_NUM=1 bash simict3500final/gpdpu/users/risc_nn_riscv/testcase/workflow/scripts/build_package.sh application/CASE/gemm_template_fusion`
- Legacy accelerator artifacts:
  - `simict3500final/gpdpu/users/risc_nn_riscv/testcase/build_out/gemm_template_fusion/worktree/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/simulator_bin/`
  - `simict3500final/gpdpu/users/risc_nn_riscv/testcase/build_out/gemm_template_fusion/worktree/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion/simulator_bin_multi_app/`
- Compiler artifacts:
  - `tmp/gpdpu_compiler_examples/gemm/simulator_bin/`
  - `tmp/gpdpu_compiler_examples/gemm/config/`
- Compare command:
  - `python3 compiler/tools/compare_simict_artifacts.py --samples 5`
- Legacy-compatible compiler mode:
  - `GPDPU_VENDOR_INST_MODE=legacy_gemm_compat python3 compiler/examples/gemm.py`
  - This mode intentionally replays the vendor CSV pseudo-op expansion for GEMM only.

The legacy build currently exits non-zero only at package collection because `riscv/riscv` is missing. The accelerator-side binary products are complete before that point.

## Confirmed binary layout

Both legacy and compiler now produce the same file sizes and final concatenation boundaries:

- `simulator_bin/insts_file.bin`: `21168128` bytes = `16 * 4352 * sizeof(inst_t)`.
- `simulator_bin/exeblock_conf_info_file.bin`: `266240` bytes = `512 * sizeof(exeBlock_conf_info_t)`.
- `simulator_bin/instance_conf_info_file.bin`: `2097152` bytes = `65536 * sizeof(instance_conf_info_t)`.
- `simulator_bin/tasks_conf_info_file.bin`: `480` bytes = `4 * sizeof(task_conf_info_t)`.
- `simulator_bin/subtasks_conf_info_file.bin`: `8522496` bytes = `32 * sizeof(sub_task_conf_info_t)`.
- `cbuf_file.bin` is `insts_file + exeblock_conf_info_file + instance_conf_info_file`.
- `micc_file.bin` is `tasks_conf_info_file + subtasks_conf_info_file`.

## Fixes made from comparison

- Legacy `task_print.cpp` had a real stack overflow: it read `16 * sizeof(inst_t) = 4864` bytes into `char tmp_data[4096]`. This is now `sizeof(inst_t) * 16`.
- Compiler `task_conf_info_t` serialization now matches legacy multi-app semantics:
  - all four tasks are independent `is_exe_start=1, is_exe_end=1` rows;
  - no task-to-task successors;
  - task subtask slots are `task_idx * MAX_SUBTASK_PER_TASK + local_subtask_idx`, e.g. task1 uses `8,9,10`.
- Compiler `sub_task_conf_info_t` emission now writes rows into fixed global slots (`0,1,2,8,9,10,16,17,18,24,25,26`) instead of compacting active rows.
- Compiler k-stream subtask `root_block_amount` now matches legacy (`4`, one left-column root per PE row), while prologue/finalize remain `16`.

## Current comparison result

The compiler now has two explicit `inst_t` modes:

- `native_symbolic` is the normal compiler path. It uses the compiler's own row/column shard schedule plus folded symbolic templates. It is not expected to be byte-identical with legacy GEMM `insts_file.bin`.
- `legacy_gemm_compat` is a golden compatibility path for the restored GEMM template-fusion case. It replays the legacy CSV pipeline and is expected to be byte-identical with legacy artifacts.

In `legacy_gemm_compat` mode, the full accelerator package is byte-identical:

- `insts_file.bin`: sha `2b15c1016136cc64aeb08fa5d406ce4ac7b1d8435220c2c0f18b0c621e3cab7e`.
- `exeblock_conf_info_file.bin`: sha `b3a328f3773151f28fadcd1d284edebb6ee6d6a29d4743e6dd537d9b0d9ae9e4`.
- `instance_conf_info_file.bin`: sha `3b9d70247acc9832d71d73ec88f044d5b083aea7f07a42c191e90fb994b19414`.
- `tasks_conf_info_file.bin`: sha `6599f6c9114b05977b25a04819f474a5d73bb56d3c6ac3b175ba4c26ee328d8e`.
- `subtasks_conf_info_file.bin`: sha `fc0a8a187cfa0f24ff7e6fe4082111db7961dc385180e412b1973f2c1cf58d31`.
- `cbuf_file.bin`: sha `2e83d38ba24ba3a55c7920e971b1493706a330bb66bf3ca7bb74a69ace3c29cb`.
- `micc_file.bin`: sha `17e78755ceb408f19b222640dcdcdfdd27f53338b81cbe07e57516b6dc695978`.

In default `native_symbolic` mode, `tasks`, `subtasks`, `exeblock`, `instance`, and `micc` remain ABI-aligned, while `insts_file.bin`/`cbuf_file.bin` are allowed to differ because the compiler scheduler is intentionally not the legacy CSV schedule.

## Legacy exeBlock ABI facts now matched

- File layout is PE-major: `16` PEs, `32` `exeBlock_conf_info_t` slots per PE.
- Padding rows are not all-zero; each inactive slot preserves the PE coordinate and PE-local `block_idx`.
- `block_idx` is PE-local across all duplicated tasks, not reset per task.
- Per-task active role sequence by PE column:
  - `y=0`: `prologue(LD64+CAL18)`, `source_ld(LD64)`, `forward(FLOW64)`, `compute(LD64+CAL560)`, `store(ST64)`.
  - `y=1/2`: `prologue`, `forward(FLOW64)`, `compute(LD64+CAL560)`, `store(ST64)`.
  - `y=3`: `prologue`, `compute(LD64+CAL560)`, `store(ST64)`.
- Stage PCs accumulate within each PE instruction memory from zero; `inst_mem_based_addr` is `0` in the legacy `exeBlock_conf_info_t` rows.
- K-stream dependency slots are vertical dataflow edges only; prologue/store are not wired as row predecessors/successors in `exeBlock_conf_info_t`.

## Legacy inst_t generation facts

- The first legacy instruction is `OP_LDN = 0x40`, `unit_inst_type = LD_UNIT_INST_TYPE = 0x8`, `latency = 1`.
- `inst_t` is `304` bytes and comes from `common/src/inst_def.h`.
- Legacy path is CSV-driven:
  - `common_oper/inst_blk_gen.cpp` calls `Csv_Operate::readFromCsv()` and `Csv_Operate::process()`.
  - `Csv_Operate::process()` maps CSV fields into `inst_t`, expands pseudo ops, and optionally sets forwarding/bypass bits.
  - `Inst_Block::process()` splits the expanded instructions into LD/CAL/FLOW/ST stages purely by `unit_inst_type`.
- Pseudo op expansion is important:
  - `HLDT`/`ILDT` expand to `LDN`.
  - `HSTT`/`ISTT` expand to `STD`.
  - `COPYT` expands to `COPY`.
  - Expansion emits `OPERANDS_RAM_NUM_PER_GROUP_ADAPTIVE` lanes; for GEMM this is why many one-line CSV templates become `64` long-struct records.
- The GEMM `test_graph_extend.cpp` files do not always pass the printed `realcsv` number into `initNode()`:
  - `subtask1` and `subtask3` use one node per PE and directly initialize from `index`.
  - `subtask2` prints logical labels such as `pe_id+32`, but the actual `initNode()` argument is the sequential node `index`.
  - Therefore a reproducer must mirror `Inst_Block_Collect` order and graph node order, not simply open `template/<realcsv>.csv`.
- Legacy active `inst_t` counts match the already-aligned exeBlock PCs:
  - `y=0`: `3592` active records per PE.
  - `y=1/2`: `3336` active records per PE.
  - `y=3`: `3080` active records per PE.
  - Total active records: `53376`.
- Current compiler active `inst_t` count is `37312`, because it still emits symbolic/folded templates rather than replaying the CSV pseudo-op expansion.

## Remaining alignment tasks

1. Keep `legacy_gemm_compat` as a regression/golden mode for customer bundle flow validation and binary-format de-risking.
2. Validate default `native_symbolic` by ABI self-consistency and numerical output, not by byte-identical comparison with legacy GEMM scheduling.
3. If strict golden comparison is needed for another operator, add a dedicated `legacy_*_compat` path instead of forcing native scheduling to mimic legacy.
4. Use legacy exeBlock stage counts and `inst_t` PE image capacity as invariants for future native serializer hardening.

## Useful commands

```bash
DUPLICATE_APPLICATION_AMOUNT=4 APP_NUM=1 \
  bash simict3500final/gpdpu/users/risc_nn_riscv/testcase/workflow/scripts/build_package.sh \
  application/CASE/gemm_template_fusion

python3 compiler/examples/gemm.py
python3 compiler/tools/compare_simict_artifacts.py --samples 5

GPDPU_VENDOR_INST_MODE=legacy_gemm_compat python3 compiler/examples/gemm.py
python3 compiler/tools/compare_simict_artifacts.py --samples 5

pytest -q tests/test_tile_dependency_network.py
```
