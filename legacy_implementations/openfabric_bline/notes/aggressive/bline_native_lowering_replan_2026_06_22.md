# RFC: Re-center Delivery On B-line-native Lowering

## Status

Accepted direction for the next implementation phase.

## Summary

We should stop trying to make tactical binary seeds pass `runtime_ready`.
Progress-first does not mean papering over known failures.  The delivery path
must return to the original B-line design: B-line semantic/tile/template plans
produce target component rows, component writers produce DFU binary sections,
and only then do we package a runtime candidate.

The A-line GEMM seed remains useful as template evidence and a byte-level
comparison baseline, but it must not become the implementation trunk.

## Current State

The current three-operator upload bundle exists, but it is not a native B-line
runtime-ready bundle.

- Partner package entrypoint guard passes for the default conservative smoke
  payload.
- `gemm_no_relu`, `gemm_relu`, and `log10max` all fail the local
  `check_dfu_delivery_candidate.py --min-state runtime_ready` gate.
- `gemm_no_relu` and `gemm_relu` are tactical A-line binary seeds.
- `log10max` is a current-validation structural payload with
  `runtime_runnable=0`.

Focused stream checks show the real B-line implementation state:

- MICC/control writers can emit debug-only bytes:
  - `task_conf_info_t`: 4 rows, 480 bytes
  - `exeBlock_conf_info_t`: 384 rows, 199680 bytes
  - `sub_task_conf_info_t`: 12 selected rows, debug-only
  - selected representations: `zero_instance_control` and `folded_k_stream`
- `inst_t` writer is still blocked as a final byte writer:
  - 896 B-line instruction rows
  - 896 matched template evidence records
  - 0 exact bound raw rows
  - 896 span materialization candidates
  - 93739008 candidate span bytes
  - 0 raw-template-row-hash-ready rows

## Problem

The previous tactical packaging path mixed two objectives:

1. produce something upload-shaped quickly;
2. make a real B-line lowering implementation.

That was useful to expose the validation boundary, but it is now the wrong
primary workstream.  If we continue patching tactical payloads until they pass
local gates, we will spend effort on compatibility glue instead of closing the
B-line compiler.

## Goals

- Implement the B-line-native path as fast as possible.
- Use A-line artifacts only as template evidence or comparison baselines.
- Keep `runtime_ready` as the minimum local upload gate.
- Avoid broad reliability work; run only focused checks needed for the current
  implementation phase.
- Make the GEMM-family fiber/tile-job template materializer the first native
  binary-lowering spine, then express GEMM and GEMM+ReLU as different op-chain
  compositions on that spine, then close log10max.

## Non-goals

- Do not relax validation to make tactical seeds pass.
- Do not hand-edit existing `cbuf_file.bin` or `micc_file.bin`.
- Do not treat `emit_bline_progress_payload.py` as the real compiler backend.
- Do not prove numerical correctness in this phase.
- Do not finish a generic multi-backend abstraction.

## Proposed Design

### Phase 1: GEMM-family B-line fiber instruction materializer

Implement the smallest B-line-native `inst_t` materialization path that consumes
the existing span-candidate reports and emits an instruction section candidate.

Current source files:

- `compiler/gpdpu_compiler/core/stream_compiler/inst_writers.py`
- `compiler/tools/check_stream_compiler_inst_writer.py`
- `compiler/gpdpu_compiler/core/stream_compiler/aline_gemm_evidence.py`

Design boundary:

- A-line CSV/template rows are evidence.
- B-line instruction rows remain the source of row identity.
- Fiber/tile-job atomic template ops are the composition unit.
- GEMM lowering must not branch on an op-level `has_relu` flag.  It should
  lower the fiber's ordered atomic template-op chain.
- The materializer may consume closed span policies and A-line catalog spans.
- The materializer must emit an artifact that is explicitly marked
  `span_materialized`, not `raw_template_overlay`.

Expected first artifact:

```text
b_line_inst_span_materialization_report
  operator_family = gemm
  instruction_rows = 896
  emitted_inst_bytes = true
  emitted_byte_count > 0
  source = B-line layout rows + A-line template span evidence
  not_claimed = final raw-template-overlay exact row binding
```

This is not hand-fixing a binary.  It is B-line target binding using template
evidence as intended.

### Phase 2: GEMM-family component assembly

Join the native instruction materialization with the existing MICC/control
writers.

Current source files:

- `compiler/gpdpu_compiler/core/stream_compiler/micc_component_writers.py`
- `compiler/gpdpu_compiler/core/stream_compiler/component_writers.py`
- `compiler/gpdpu_compiler/core/stream_compiler/operator_payload_assembly.py`

Required output:

```text
native_<gemm_variant>_payload/
  result/cbuf_file.bin
  result/micc_file.bin
  config/cbuf_file.bin
  config/micc_file.bin
  simulator_bin/insts_file.bin
  simulator_bin/exeblock_conf_info_file.bin
  simulator_bin/instance_conf_info_file.bin
  simulator_bin/subtasks_conf_info_file.bin
  simulator_bin/tasks_conf_info_file.bin
  runtime/riscv_src/...
  MANIFEST.txt
```

The same assembly machinery should serve `gemm_no_relu` and `gemm_relu`.
The difference is the fiber/tile-job op-chain, not a special GEMM backend
branch.  The first pass may still be profile-specific for DFU3500.  It should
not become a CUDA/CANN/general backend abstraction.

### Phase 3: Runtime assets from B-line payload, not copied seed

Generate or derive runtime control/assets from the B-line-native payload and
chip program, instead of copying A-line runtime shells.

Current source files:

- `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/runtime_control.py`
- `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/build_payloads.py`

The runtime asset step should be a payload builder phase, not a validation
workaround.

### Phase 4: GEMM+ReLU as fiber/tile-job op-chain composition

Represent GEMM+ReLU as the same GEMM-family materialization path with an
additional atomic ReLU template op in the fiber/tile-job chain.  ReLU is not a
property the GEMM writer should inspect; it is an operation in the ordered
template-op chain consumed by the materializer.

Current source files:

- `compiler/gpdpu_compiler/core/stream_compiler/relu_binding.py`
- `compiler/tools/check_stream_compiler_relu_binding.py`

Preferred V1:

- explicit tile/fiber op-chain binding;
- store must consume the last value produced by the chain;
- if the chain contains ReLU, store must consume ReLU output;
- do not silently alias a chain containing ReLU to a chain without ReLU.

Correct model:

```text
fiber/tile job:
  load/materialize operands
  -> route/visibility ops
  -> gemm update/finalize atomic template ops
  -> optional relu atomic template op
  -> store atomic template op
```

The lowering code should be generic over this ordered chain.  Any fused vendor
template is still represented as an atomic template op or closed template span
inside the chain, not as an op-level special case in GEMM.

### Phase 5: log10max native strategy closure

Close log10max through B-line source/tile/template lowering, not by trying to
make the current structural payload look runnable.

Current source files:

- `compiler/gpdpu_compiler/validation/dfu3500_partner_validation/build_payloads.py`
- `compiler/gpdpu_compiler/core/stream_compiler/log10max_collective_strategy.py`
- `compiler/gpdpu_compiler/core/stream_compiler/log10max_template_pack.py`

Priority:

1. keep the source expression and local template pack;
2. choose and implement scalar visibility strategy;
3. emit functional rows for load/local compute/reduce/store;
4. only then ask `runtime_ready`.

## Invariants

- B-line rows own logical identity.
- A-line rows are evidence, not semantic authority.
- No validation relaxation is allowed to convert known-bad payloads into
  runtime-ready payloads.
- `runtime_ready` means local structural/package/runtime readiness only.
- A payload that fails `runtime_ready` is not uploaded as a customer candidate.

## Implementation Plan

P0:

1. Add a real span materializer artifact in `inst_writers.py`.
2. Add a focused checker for emitted span bytes, separate from raw-template
   overlay readiness.
3. Emit `simulator_bin/insts_file.bin` from B-line GEMM-family fiber rows plus
   span evidence.
4. Join with MICC debug/control bytes into a native GEMM-family payload shell.
5. Run `check_dfu_delivery_candidate.py --min-state runtime_ready`.

P1:

1. Replace debug-only MICC/control bytes with runtime-shaped selected subtask
   bytes where necessary.
2. Promote the first GEMM-family payload from shell to runtime candidate.
3. Emit `gemm_no_relu` and `gemm_relu` by selecting different fiber/tile-job
   op chains on the same materializer.

P2:

1. Close log10max scalar visibility and functional row emission.
2. Produce log10max native payload.
3. Rebuild the three-operator bundle only after all three pass the local minimum
   gate.

## Validation Plan

Run focused checks only:

```bash
PYTHONPATH=compiler python3 compiler/tools/check_stream_compiler_inst_writer.py
PYTHONPATH=compiler python3 compiler/tools/check_stream_compiler_micc_writers.py
PYTHONPATH=compiler python3 compiler/tools/check_stream_compiler_operator_payload_assembly.py
PYTHONPATH=compiler python3 compiler/tools/check_dfu_delivery_candidate.py <payload> --operator <op> --min-state runtime_ready
```

Do not run broad validation suites unless the focused checks pass or a failure
needs deeper diagnosis.

## Recommended Decision

Reject further work on making tactical seeds pass `runtime_ready`.

Proceed immediately with the B-line-native GEMM `inst_t` span materializer as
the first implementation cut, but make it a GEMM-family fiber/tile-job
materializer rather than a GEMM-vs-ReLU branch.  Once the materializer can emit
one native GEMM-family payload, use ordered atomic template-op chains to produce
both `gemm_no_relu` and `gemm_relu`, then return to log10max scalar visibility
and functional row emission.
