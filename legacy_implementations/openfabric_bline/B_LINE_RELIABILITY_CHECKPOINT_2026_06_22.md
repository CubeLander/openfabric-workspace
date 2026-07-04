# B-line Reliability Checkpoint - 2026-06-22

This document freezes the current reliability-oriented B-line work as a project
checkpoint.  From this point forward, the mainline delivery policy shifts to
progress-first binary generation for the three required customer operators:

- `gemm`
- `gemmrelu`
- `log10max`

Reliability work below remains useful as a local safety net, but it must not
expand into new framework work or block tactical binary lowering unless it
protects against emitting a known-bad or uninspectable payload.

## Checkpoint Decision

```text
decision: reliability node saved
new execution mode: progress-first binary delivery
validation policy: use existing gates only
new validation framework work: deferred
customer priority: produce operator binaries as fast as possible
```

The current validation/runtime-ready work has reached a good enough node for
delivery-week engineering.  It can classify payload state, preserve known
blockers, reject stale/placeholder/runtime_ready claims, and keep evidence
traceable.  We will stop broadening this area for now.

## Frozen Reliability Baseline

Current accepted reliability artifacts:

- `runtime_ready` local gate semantics are defined as local structural/package
  readiness, not SimICT execution or numerical correctness.
- Delivery contracts exist for operator payload state and package manifests.
- Partner validation entrypoint guard is wired and passing.
- Stream compiler focused checks cover S0-S6 report artifacts.
- B-line GEMM A-line evidence is cataloged and auditable.
- ReLU explicit-subtask binding is fail-closed and cannot silently drop ReLU.
- log10max PE00 materialized-scalar fallback is explicit and does not pretend
  to be direct physical allreduce.

Latest known passing checks at this node:

```text
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_inst_writer.py
  OK

PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_collective.py
  OK

for script in compiler/tools/check_stream_compiler_*.py; do
  PYTHONPATH=compiler:compiler/tools python "$script"
done
  all pass

PYTHONPATH=compiler pytest -q tests/test_dfu_binary_validation.py
  48 passed

PYTHONPATH=compiler pytest -q tests/test_dfu_delivery_contracts.py
  4 passed

PYTHONPATH=compiler pytest -q tests/test_chip_program_frontend.py -k 'template_bound_shadow_ir or app_storage or materialize or store'
  3 passed, 25 deselected

PYTHONPATH=compiler:compiler/tools python compiler/tools/check_partner_validation_entrypoint.py
  PASS
```

## Current Operator State

### GEMM

```text
state: binary-lowering spine, still blocked from runtime_ready
concrete B-line instruction rows: 896
zero instruction boundaries: 64
A-line row catalog rows: 53376
span materialization candidates: 896
span materialization total candidate bytes: 93739008
raw overlay consumable rows: 0
raw template row hash ready: 0
raw template row hash blocked: 896
```

Remaining delivery work:

```text
build real span-aware inst_t byte materializer
decide span-aware writer contract vs single-row template_row_sha256 contract
emit inst_t bytes into CBUF payload
keep MICC/control writers aligned with emitted inst rows
assemble payload and run runtime_ready gate
```

### GEMM+ReLU

```text
state: explicit ReLU subtask selected, fail-closed
symbolic ReLU templates: 64
explicit ReLU bindings: 64
store dependencies: 64
recommended ReLU opcode: HMAX
closed evidence: dtype selection, store operand lifetime
P0 blockers: zero constant materialization, template row evidence
```

Remaining delivery work:

```text
materialize zero constant
bind ReLU HMAX/IMM template rows
connect ReLU output to store source
reuse GEMM binary-lowering spine once inst_t byte path exists
```

### log10max

```text
state: PE00 materialized-scalar fallback selected as delivery work item
direct physical allreduce: not claimed
redundant SPMD: internal waiver only
local template pack steps: 7
PE00 scratch address candidate: compiler_allocated_address_candidate_available
scratch address: sram@0xA0000..0xA0004
runtime_ready: false
```

Remaining PE00 blockers:

```text
producer_pe00_physical_store
consumer_physical_readback
runtime_subtask_order
receiver_binding
pe00_fmax_combine_order
```

## Progress-First Rules After This Checkpoint

The following reliability work is deferred:

```text
general validation framework expansion
formal operator semantic proof
generic allreduce route framework
general fusion graph cleanup
perfect folded/expanded abstraction cleanup
new broad decoder/package audits that do not unblock binary emission
```

The following gates still apply because they prevent unusable payloads:

```text
no placeholder package may be marked runtime_ready
no symbolic_unresolved row may be emitted as concrete binary
no ReLU may be silently dropped from gemmrelu
log10max may not label PE00 materialized scalar as direct physical allreduce
manifest hashes/sizes must match emitted files
runtime_ready remains local readiness only, not numerical correctness
```

## Next Execution Order

```text
1. GEMM inst_t byte materializer
2. GEMM CBUF assembly and payload emission
3. GEMM runtime_ready / uploadable candidate
4. GEMM+ReLU zero constant + HMAX template binding
5. GEMM+ReLU payload emission
6. log10max PE00 physical store/readback + runtime subtask ordering
7. log10max payload emission
8. customer bundle with honest per-operator status labels
```

## Status Summary

This checkpoint intentionally saves reliability progress without turning it into
the next bottleneck.  The project now moves from:

```text
prove the lowering path is well guarded
```

to:

```text
emit operator binaries, accept tactical narrowing, and repair reliability gaps later
```

