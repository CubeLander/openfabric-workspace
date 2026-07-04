# Tile Level Legacy vs New Dump

Generated on the current refactor checkpoint.

## Source Plans

- Legacy GEMM: `tmp/gpdpu_compiler_examples/gemm/plan.json`
- Legacy GEMM + ReLU: `tmp/gpdpu_compiler_examples/gemm_relu/plan.json`
- New GEMM: `tmp/gpdpu_compiler_chip_examples/gemm/chip_program.json`
- New GEMM + ReLU: `tmp/gpdpu_compiler_chip_examples/gemm_relu/chip_program.json`

The `tmp/` directory is git-ignored, so this note keeps the persistent summary.

## Summary

| Case | Legacy Streams | New Streams | Legacy Phases | New Phases | Legacy Bundles | New Bundles |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| GEMM | 16 | 16 | 64 | 80 | 128 | 128 |
| GEMM + ReLU | 16 | 16 | 64 | 80 | 128 | 128 |

Both paths agree on:

- processor/tile stream count: `16`;
- GEMM tile phase count: `4` per processor;
- K-block count: `4` per GEMM tile phase;
- row/column collective refs: `8` per GEMM tile phase;
- collective bundle count: `128`;
- launch group count: `1`;
- task plan count: `4`;
- first GEMM tile coordinate ranges:
  - A `global_m = {start: 0, end: 64, padded_end: 64}`;
  - B `global_n = {start: 0, end: 64, padded_end: 64}`.

## Expected Difference

The new path has `80` tile phases instead of legacy `64` because the refactored
frontend explicitly models the SRAM boundary:

```text
ChipProgram.store_sram_tensor
  -> ProcessorLogicalAction.store_sram_tensor
  -> ProcessorTileProgram.store_sram_tensor phase
```

Legacy stores are handled later as backend-side `store_records` derived from
`local_gemm_summa` phases, not as explicit tile phases. Therefore the extra
`16` phases in the new path are expected: one explicit store phase per
processor.

## GEMM + ReLU Fusion

Both paths fuse immediate ReLU into the GEMM tile phase:

```text
legacy local_ops = [init_c, stream_k_gemm, relu, store_c]
new    local_ops = [init_c, stream_k_gemm, relu, store_c]
```

This means the new `ProcessorTileProgram` preserves the key legacy tile-level
semantic shape while keeping SRAM load/store boundaries explicit.
