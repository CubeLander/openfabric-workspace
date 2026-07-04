# Decoder / Validation Reorganization Plan

Date: 2026-06-21

Status: active guidance

## Core Decision

The package is named `decoder`, but the project goal is broader:

```text
prove emitted DFU artifacts are correct enough for the next local/remote validation stage
```

The split is:

```text
compiler/gpdpu_compiler/decoder/
  diagnostic microscope
  profile-driven byte/field decode
  offset lookup
  field-aware diff
  ISA annotation
  no serializer behavior
  no runnable truth

compiler/gpdpu_compiler/validation/
  tester / verifier workflows
  payload conformance checks
  runtime-control metadata checks
  package/runtime readiness checks
  partner SimICT execution workflows
```

Short version:

```text
decoder explains bytes
validation judges artifacts
```

Current binary-knowledge audit split:

```text
settled / do not re-audit casually:
  compiler/notes/decoder/settled_binary_knowledge_checklist.md

missing / execute next:
  compiler/notes/decoder/unimplemented_binary_knowledge_backlog.md
```

## Current Payload-Local Policy

Validation is attached to payload construction, not to upload packaging.  A
payload directory should validate immediately after `MANIFEST.txt`, CBUF/MICC,
runtime-control assets, input image, and references are generated.  Compression,
copying, uploading, and arch-13 execution should simply consume an already
validated payload.

Do not add a separate “upload gate” unless there is a future upload-specific
artifact with its own semantics.  Current gates are payload-local:

```text
PACKAGE_COMPLETE:
  final cbuf/micc files exist
  file sizes match the selected binary profile
  MANIFEST claims match actual size/hash

RUNTIME_READY:
  PACKAGE_COMPLETE passes
  runtime/riscv_src/riscv_control.json exists and parses
  generated RISC-V source/config assets exist
  input_data.bin exists
  output tensors have output DMA transfers
  reference paths exist when declared
```

`RUNTIME_READY` is still local artifact readiness.  It does not prove operator
math, template correctness, or SimICT execution success.

## What Should Stay In `decoder`

These are library-quality read-only tools:

```text
binary_layout.py
binary_decoder.py
binary_diff.py
coverage.py
profiles/dfu3500.py
dfu3500_isa.py
```

Responsibilities:

- Decode known file kinds into section / row / field.
- Report `known_field`, `known_padding`, `unknown_range`, `size_mismatch`.
- Provide deterministic JSON reports.
- Provide field-aware byte diffs.
- Annotate `inst_t.opCode` with mnemonic/category.
- Keep unknowns honest.

Non-responsibilities:

- Deciding payload readiness.
- Proving task graph legality.
- Proving operand/template runnable legality.
- Running SimICT.
- Owning packaging/upload workflow policy.
- Regenerating payloads.

## Validation Package Shape

```text
compiler/gpdpu_compiler/validation/
  dfu_binary_checks/
    report.py
    source_fingerprint_check.py
    payload_conformance.py
    profile_conformance.py
    runtime_readiness.py
  dfu3500_package_checks/
    control_graph_check.py
    component_consistency_check.py
  dfu3500_partner_validation/
    build_payloads.py
    validate_on_arch13.sh
    scripts/
```

`dfu_binary_checks` owns generic payload-local checks.  DFU3500 task graph
legality will live under `dfu3500_package_checks` when we are ready to make
control-plane semantics blocking.

## Tester Contract

Validation reports use stable status values:

```text
pass:
  check proves the target invariant

fail:
  check proves a violation

blocked:
  required evidence is missing

diagnostic_only:
  check reports useful information but is not authoritative for the requested gate
```

Suite aggregation rule:

```text
authoritative fail    -> final_status = fail
authoritative blocked -> final_status = blocked
no authoritative checks for requested gate -> final_status = blocked
```

## Migration Order

### Phase A: Keep current decoder stable

- Do not move decoder core while the mainline payload builder actively depends on it.
- Keep `compiler/tools/decode_dfu_binary.py` as a thin CLI.
- Keep `compiler/tools/compare_dfu_payloads.py` as a transitional CLI.

### Phase B: Add payload-local validation checks

- Add `validation/dfu_binary_checks/report.py`.
- Add `profile_conformance.py`, `payload_conformance.py`, and
  `source_fingerprint_check.py`.
- Add `runtime_readiness.py` for payload-local runtime/control/reference assets.
- Make payload construction call `validate_payload(..., RUNTIME_READY)` after
  manifest generation.

### Phase C: Add DFU3500 package/control verifier

- Validate component files against their combined `result/` images before
  runtime execution.
- Consume decoded MICC/CBUF rows.
- Verify active task/subtask/exeBlock graph semantics.
- Keep these checks separate from generic decoder logic.

Current implementation status:

```text
component_consistency_check:
  implemented as a RUNTIME_READY gate
  verifies config/result copies and simulator_bin section components

payload_conformance:
  implemented as PACKAGE_COMPLETE/RUNTIME_READY gate
  requires readiness-critical artifacts to carry manifest size/hash claims

runtime_memory_layout:
  implemented as a RUNTIME_READY gate
  verifies RuntimeControlPlan tensor SPM regions, dtype/shape byte sizes,
  input DMA coverage, output reference sizes, transfer size/offset/phase, and
  input/output region overlap

instruction_span_check:
  implemented as a RUNTIME_READY gate
  verifies active exeBlock stage spans point to valid PE-local CBUF instruction
  rows, rejects all-zero padding rows, and rejects unknown opCode values

opcode_conformance_check:
  implemented as a RUNTIME_READY gate
  verifies active CBUF instruction rows against source-backed registerOp
  metadata: pseudo opcode rejection, unit_inst_type match, and latency match
  src_count / need_pe_idx are retained as decoder metadata for future operand
  verification but are not blocking yet

operand_resource_check:
  implemented as a RUNTIME_READY gate
  verifies active CBUF operand/resource fields fit hardware bounds:
  operand indices, destination PE coordinates, destination block ids, and
  bool-like fetch/forward/bypass flags
  route endpoint ownership is still deferred until typed route plans exist

memory_template_check:
  implemented as a RUNTIME_READY gate
  verifies active memory/template rows consume valid base_addr slots:
  iter_exe_cond/flow_ack are in base_addr[0..3], and active instance rows do
  not expose disabled sentinels for consumed memory slots
  operator-specific MemoryAccessPlan matching is still future work

control_graph_check:
  implemented for core active task/subtask/exeBlock sanity
  verifies nonzero task successors point to active task rows
  verifies duplicate task successors and task successor cycles
  verifies nonzero subtask successors point to active subtasks for the task
  verifies duplicate subtask successors and subtask successor cycles
  verifies active subtask successor graphs reach every active referenced subtask
  verifies explicitly declared exeBlock predecessor/successor reciprocity
  verifies successor cycles as a deadlock-risk structural error
  next work is richer multi-block vendor evidence; enable sidecars stay non-authoritative

archived_report_freshness:
  implemented as an entrypoint/package-consumption guard

next local gate work:
  typed route endpoint ownership verifier once B-line emits route/resource plans
  typed MemoryAccessPlan/template verifier once executable roles expose storage intent
  verifies validation/runtime_ready.json still refers to current payload sha256 values
  intentionally not part of validate_payload(), because runtime_ready.json is validation output
```

### Phase D: Feed partner runtime only validated payloads

- Archive validation reports beside payloads.
- Keep remote arch-13 failures focused on runtime/simulator behavior, not local
  packaging mistakes.

## Next Mainline Work Plan

### Stage 1: Finish local artifact gates

1. Keep `component_consistency_check` blocking for `RUNTIME_READY`.
2. Keep sidecars optional and non-authoritative, per
   `compiler/notes/decoder/auxiliary_sidecar_decision.md`.
3. Keep `archived_report_freshness` in package/entrypoint guards so stale
   validation reports cannot masquerade as current evidence.
4. Next local gate work is opcode conformance metadata/checking.

### Stage 2: Strengthen graph checks with real evidence

1. Continue using `RuntimeControlPlan + MICC rows` as truth.
2. Add stronger checks only when supported by source or remote evidence.
3. Current safe next checks:
   - no active task row outside `runtime_control.launch.task_count`,
   - active task rows form an acyclic legal task chain if `suc_tasks` is nonzero,
   - active subtasks form an acyclic legal subtask chain if `suc_subtasks` is nonzero,
   - active subtasks with declared successor edges are reachable from the start subtask,
   - explicit subtask/exeBlock edges remain reciprocal,
   - exeBlock successor graph remains acyclic,
   - stage spans stay inside PE-local instruction capacity.
4. Do not use `taskEnable.bin` or `instEnable.bin` as graph truth.

### Stage 3: Runtime output closure

1. Define the output collection contract from generated `riscv_control.json`.
2. Archive output bytes and metadata beside `runtime_ready.json`.
3. Add reference comparison as a separate post-runtime check:
   - exact or tolerance-based by dtype/operator,
   - never mixed into local `RUNTIME_READY`.

### Stage 4: Developer ergonomics

1. Keep payload construction auto-validating by default.
2. Keep CLI tools thin and diagnostic only.
3. Prefer tests over manual shell probes for known binary failure modes.
