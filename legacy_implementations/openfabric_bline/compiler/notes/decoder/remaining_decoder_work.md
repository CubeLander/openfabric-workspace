# Remaining DFU Decoder Work

Date: 2026-06-21

Status: decoder gap tracker for implementation work

This note records what is still missing after the generic DFU decoder and the
DFU3500 SimICT legacy profile landed.

Current audit split:

```text
already embodied in tooling:
  compiler/notes/decoder/settled_binary_knowledge_checklist.md

still missing / backlog:
  compiler/notes/decoder/unimplemented_binary_knowledge_backlog.md
```

Current position:

```text
Implemented:
  CBUF/MICC/component layout decode
  known struct field offsets
  padding/unknown classification
  row decode
  byte offset lookup
  field-aware diff
  DFU3500 MICC active-ish diagnostics
  DFU3500 opCode -> mnemonic annotation

Diagnostic-only:
  source fingerprints embedded in profile
  active rows vs padded capacity reports
  task/subtask/exeBlock fields are visible in decoder; graph proof lives in
  validation/dfu3500_package_checks
  manifest/file-size conformance in payload comparator

Intentionally out of decoder scope:
  runtime in-flight messages
  RISC-V DMA/start/wait/finish correctness
  operand/template runnable proof
  route/resource semantic ownership proof
```

## P0: Keep Decoder Honest

### Deferred: Source fingerprint verification

Owner target:

```text
compiler/gpdpu_compiler/decoder/profiles/dfu3500.py
compiler/tools/decode_dfu_binary.py
```

Current state:

- The DFU3500 profile embeds audited hashes for clean common headers.
- The tool can use profile fingerprints as diagnostic provenance.
- OCR-derived vendor implementation sources are not authoritative enough to
  become a near-term blocking gate.

Deferred idea:

```text
--verify-source-fingerprints
  checks configured local source paths when available
  reports missing source separately from hash mismatch
  never silently updates profile hashes
```

Re-open trigger:

```text
partner provides authoritative updated sources
simulator behavior seriously diverges from local binary/profile assumptions
source-level audit becomes necessary to explain a blocking runtime bug
```

## Closed: Auxiliary Sidecars

Decision note:

```text
compiler/notes/decoder/auxiliary_sidecar_decision.md
```

Files:

```text
data_inst_replace.bin
instEnable.bin
taskEnable.bin
```

Current policy:

```text
optional compatibility / RTL collateral
not RUNTIME_READY truth
not active task truth
not instruction readiness proof
not CBUF/MICC content
```

No implementation work is planned unless new source-level runtime consumer
evidence or remote behavior evidence appears.

## P1/P2: RTL Narrow Encoding Profile

### 3. RTL instruction bitfield decoder

Source docs:

```text
docs/runtime/data/rtl.md
docs/architecture/instruction-set/dfu3500-simd/MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md
```

Current state:

- Current decoder handles wide SimICT `inst_t` rows.
- RTL narrow structures are documented but not modeled as decoder profiles.

Needed only if B-line starts using RTL files as validation artifacts:

```text
profile/file kinds for rtl_bin outputs
bitfield decode for inst_t_*_for_rtl families
explicit relation back to wide inst_t opCode/mnemonic
```

Boundary:

```text
Do not confuse RTL narrow encoding with simulator CBUF inst_t rows.
```

## P2: Opcode Annotation Depth

### 4. ISA annotation enrichment

Current state:

- `inst_t.opCode` decodes to mnemonic/category/source.
- It does not include lane semantics, operand arity, or doc links.

Potential additions:

```text
annotation.doc_refs
annotation.operand_count
annotation.unit_family
annotation.is_pseudo_opcode
```

Source docs:

```text
docs/architecture/instruction-set/dfu3500-simd/README.md
docs/architecture/instruction-set/dfu3500-simd/instruction_cards.jsonl
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/csv_oper.cpp
simict3500final/gpdpu/users/risc_nn_riscv/common/src/inst_def.h
```

Boundary:

Opcode annotation is diagnostic metadata. It must not prove:

```text
operand ownership
memory base binding
pseudo expansion correctness
template runnable legality
```

Those belong to template/package verifier layers.

## Closed / Moved: Package-Control Verifier Adjacent To Decoder

### 5. Task/subtask/exeBlock graph legality checker

Current state:

- Implemented outside generic decoder as `dfu3500_control_graph`.
- Owner:

  ```text
  compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py
  ```

- Current coverage is tracked in:

  ```text
  compiler/notes/decoder/settled_binary_knowledge_checklist.md
  ```

- Remaining graph/template checks are tracked in:

  ```text
  compiler/notes/decoder/unimplemented_binary_knowledge_backlog.md
  ```

Boundary:

This consumes decoded facts, but it is not the generic binary decoder.  It is a
DFU3500 package/control verifier.

## Not Planned For Decoder

### Runtime messages

Reason:

```text
Runtime messages are in-flight simulator/control structs, not payload images.
They are noisy and not useful for current B-line binary payload validation.
```

Keep source docs available:

```text
docs/runtime/data/messages.md
```

But do not treat message decode as a blocker.

### RISC-V runtime control correctness

Reason:

```text
Decoder can inspect emitted files but cannot prove DMA/start/wait/finish behavior.
```

Owner should be runtime-control validation, not decoder.

### Template / route / operand semantic proof

Reason:

```text
Decoder sees bytes. It should not decide whether a template row sequence is a
legal implementation of an operator.
```

Owners:

```text
template verifier
package verifier
B-line binding checks
```

## Current Coverage Command

Use this command to keep the tool honest:

```bash
python compiler/tools/decode_dfu_binary.py --coverage
```

Expected current shape:

```text
implemented:
  CBUF/MICC/component layout
  struct fields
  field-aware lookup/diff
  opcode mnemonic annotation

diagnostic_only:
  source fingerprints
  active-ish rows
  control fields visible, not proven
  manifest/file-size conformance

documentation_only:
  sidecars
  RTL narrow encoding

out_of_scope:
  runtime messages
  operand/template semantics
  route/resource proof
  RISC-V runtime control
```
