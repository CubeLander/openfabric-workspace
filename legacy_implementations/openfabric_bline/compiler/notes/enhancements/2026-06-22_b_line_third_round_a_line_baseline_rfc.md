# RFC: B-line Third-Round Blockers Against A-line Baseline

## Status

Draft for immediate execution, 2026-06-22.

## Summary

The third parallel round is not blocked by lack of direction.  It is blocked by
two places where B-line must import A-line success evidence without importing
A-line technical debt: instance/base-address semantics and exact `inst_t`
row/span authority.  A-line proved the DFU/SimICT runtime path works for a
small functional probe and for the `gemm_template_fusion` artifact workflow.
B-line should now use that success as a binary reference and validation oracle,
not as a semantic source of truth.

## Current State

The first two B-line parallel rounds produced fail-closed artifacts:

```text
GEMM no-ReLU:
  MICC task/exeBlock debug writers exist.
  subtask writer is blocked on instance representation selection.
  inst_t writer has 896 candidate evidence matches but no exact row seed.

GEMM+ReLU:
  explicit ReLU subtask is selected.
  dtype is closed to HMAX based on current fp16 GEMM tile evidence.
  store lifetime is closed: store must consume relu_output.
  zero constant and row evidence remain blocked.

log10max:
  local template pack exists.
  PE00 materialized scalar is the recommended delivery strategy.
  selected_delivery_strategy remains None until PE00 evidence closes.
```

The runtime-ready validation chain is now stricter and aligned with A-line
lessons.  One bug was found and fixed: `memory_template_check` was treating
`sub_task_conf_info_t.instances_conf_mem_based_addr` as a physical CBUF row.
The A-line/GEMM replay notes show the correct split:

```text
MICC instances_conf_mem_based_addr = compact active-instance byte offset
CBUF instance_conf_info_file.bin  = fixed task/subtask/instance window
physical_instance_row = task * 8 * 2048 + subtask * 2048 + instance
```

That fix is guarded by a new regression test.

## Problem

The remaining hard point is not validation and not package layout.  It is binary
authority.

S1 cannot emit a trustworthy `sub_task_conf_info_t` row until B-line explicitly
selects the instance representation:

```text
8 non-k-stream subtasks:
  derived active instance count = 0
  current candidate instances_amount = 1

4 k-stream subtasks:
  derived active instance count = 4
  folded overlay instances_amount = 4
  current expanded candidate instances_amount = 1
```

S2 cannot emit trustworthy `inst_t` rows because role/opcode evidence is not
enough to select one raw legacy row:

```text
accumulator_prepare        candidate_raw_row_count = 82
compute_core:gemm_update   candidate_raw_row_count = 512
operand_materialize:A      candidate_raw_row_count = 64
operand_materialize:B      candidate_raw_row_count = 64
operand_route_recv:A       candidate_raw_row_count = 64
operand_route_recv:B       candidate_raw_row_count = 64
tile_store                 candidate_raw_row_count = 64
```

Therefore `template_row_sha256` cannot be inferred.  It must come from A-line
successful row/span evidence or from a new B-line TaskResource replay authority.

## Goals / Non-goals

Goals:

```text
1. Use A-line success to close B-line binary facts.
2. Keep B-line semantic authority in B-line IR and explicit target bindings.
3. Close GEMM no-ReLU first, because it is the binary lowering spine.
4. Keep every gate fail-closed until exact row/span or representation evidence exists.
```

Non-goals:

```text
1. Do not revive A-line as the main development path.
2. Do not infer inst_t rows from role/opcode counts.
3. Do not silently mix expanded and folded k-stream representation.
4. Do not label log10max redundant SPMD as customer delivery.
```

## Proposed Design

### 1. A-line Baseline as Evidence, Not Authority

The successful A-line artifacts may provide:

```text
result/cbuf_file.bin
result/micc_file.bin
simulator_bin/*.bin
task*/subtask*/template/*.csv
common_oper TaskResource replay behavior
```

B-line may consume those through typed evidence records only:

```text
AlineBinaryEvidence:
  case_id
  artifact_path
  component
  physical_row_index
  row_sha256
  task
  subtask
  pe
  block
  stage
  local_order
  source_csv_path
```

It must not consume A-line compatibility projections as semantic truth.

### 2. S1 Representation Selection

S1 should add explicit selection:

```text
non-k-stream:
  selected_representation = zero_instance_control
  instances_amount = 0
  address = 0
  rule = address ignored because instances_amount == 0

k-stream:
  selected_representation = folded_k_stream_explicit
  instances_amount = 4
  address = first active instance byte offset
  rule = folded overlay is selected explicitly
```

If this selection is emitted, the package metadata must declare mixed
representation explicitly:

```json
{
  "default": "expanded",
  "subtasks": {
    "subtask1_k_stream": "folded_k_stream_explicit"
  }
}
```

### 3. S2 Exact Row Seed

S2 should stop treating role/opcode evidence as near-enough.  It needs an exact
seed:

```text
TemplateRowSpanBinding:
  source_plan_id
  logical_row_id
  template_op_id
  role
  opcode
  phase
  aline_case_id
  source_csv_path
  template_index
  local_order or row_span
  task_resource_replay_status
  raw_template_row_sha256
```

If A-line artifact decoding can map B-line logical rows to A-line physical rows,
S2 may compute `template_row_sha256`.  Otherwise it must stay blocked.

### 4. log10max PE00 Contract

PE00 materialized scalar should be treated as B-line collective lowering:

```text
reduce local maxima
PE00 combines ordered FMAX chain
PE00 stores global scalar to explicit scratch
all PEs read/broadcast-load that scalar
postprocess consumes concrete global scalar source
```

The missing item is not “whether allreduce belongs in B-line”; it does.  The
missing item is the concrete scratch/base_addr/order/receiver binding.

## Invariants

```text
MICC compact offset and CBUF physical row are separate index spaces.
instances_amount == 0 means address 0 is ignored.
instances_amount > 0 and address 0 means row0.
template_row_sha256 must be computed from exact raw row bytes.
A-line artifacts are evidence, not B-line semantic authority.
PE00 materialized scalar is not direct physical route allreduce.
runtime_ready is local package/structural readiness, not numerical proof.
```

## Implementation Plan

Phase 1, now:

```text
S1:
  implement explicit representation selection artifact.

S2:
  add A-line evidence seed shape and candidate distribution summary.

Main:
  add regression test for compact-vs-physical instance lookup.
  keep runtime_ready gate strict.
```

Phase 2:

```text
Extract A-line row/span evidence for gemm_template_fusion.
Map B-line GEMM no-ReLU rows to A-line physical inst rows.
Compute template_row_sha256 for rows with exact authority.
```

Phase 3:

```text
Emit first GEMM no-ReLU CBUF/MICC candidate.
Run runtime_ready.
Only then promote GEMM+ReLU row evidence and log10max PE00 scratch binding.
```

## Validation Plan

Already passing:

```text
PYTHONPATH=compiler pytest -q tests/test_dfu_binary_validation.py -k memory_template
  4 passed
```

Required after third round:

```text
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_micc_writers.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_inst_writer.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_operator_payload_assembly.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_collective.py
for script in compiler/tools/check_stream_compiler_*.py; do
  PYTHONPATH=compiler:compiler/tools python "$script"
done
PYTHONPATH=compiler pytest -q tests/test_dfu_binary_validation.py
PYTHONPATH=compiler:compiler/tools python3 compiler/tools/check_partner_validation_entrypoint.py
```

## Risks and Mitigations

Risk: A-line evidence is stale or from the wrong runtime path.
Mitigation: only use successful `result/` artifacts copied into runtime
`config/`, not stale `simulator_bin` fragments.

Risk: folded k-stream becomes implicit.
Mitigation: package manifest must declare selected representation per subtask.

Risk: row hashes are guessed from role/opcode.
Mitigation: check must reject rows lacking `source_csv_path` and
`local_order_or_row_span`.

## Recommended Decision

Continue parallel work, but narrow it to A-line-baseline-backed closure:

```text
Accept:
  A-line successful artifacts as binary evidence.
  explicit folded k-stream selection for GEMM if S1 proves it.
  PE00 materialized scalar as B-line log10max delivery strategy.

Reject:
  inferred template_row_sha256.
  implicit expanded/folded mixing.
  customer delivery labels for internal redundant SPMD.
```

The next decisive milestone is not another report.  It is the first set of
GEMM no-ReLU rows with exact A-line row/span authority.
