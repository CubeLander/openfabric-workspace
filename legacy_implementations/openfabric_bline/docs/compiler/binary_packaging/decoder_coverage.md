# DFU Binary Decoder Coverage Map

Status: implementation coverage audit, updated 2026-06-21

This page answers one question:

```text
Which pieces of our binary/runtime knowledge are embodied in the decoder,
and which pieces are still documentation-only or future verifier work?
```

The decoder lives under:

```text
compiler/gpdpu_compiler/decoder/
compiler/tools/decode_dfu_binary.py
compiler/tools/compare_dfu_payloads.py
```

The important boundary is:

```text
decoder = diagnostic microscope
serializer = byte writer
runtime/package validator = runnable truth
```

The decoder may explain bytes and compare payloads. It must not become a second
serializer, and it must not infer runtime readiness from names, padding, or
auxiliary files.

## Current Tooling

| Tool | Scope | Use it for |
| --- | --- | --- |
| `compiler/tools/decode_dfu_binary.py` | Generic profile-driven DFU binary decoder | Summary, row decode, byte-offset lookup, field-aware diff. |
| `compiler/tools/compare_dfu_payloads.py` | Payload directory comparator | Compare `cbuf_file.bin` / `micc_file.bin`, catch size mismatches, show DFU3500 MICC control deltas. |
| `compiler/tools/decode_dfu_binary.py --coverage` | Machine-readable coverage map | Report implemented, diagnostic-only, documentation-only, and out-of-scope knowledge areas. |
| `compiler/gpdpu_compiler/decoder/binary_layout.py` | Generic schema | File/section/struct/field/profile metadata. |
| `compiler/gpdpu_compiler/decoder/coverage.py` | Coverage declarations | Keeps missing binary knowledge visible to tests and CLI reports. |
| `compiler/gpdpu_compiler/decoder/profiles/dfu3500.py` | First concrete profile | DFU3500 SimICT legacy CBUF/MICC/component layouts. |
| `compiler/gpdpu_compiler/decoder/dfu3500_diagnostics.py` | Target-specific view | Active-ish task/subtask and control-field diagnostics built on top of generic decode. |
| `compiler/gpdpu_compiler/decoder/dfu3500_isa.py` | ISA annotation view | Maps decoded `inst_t.opCode` values to DFU3500 mnemonics for diagnostics. |

## Coverage Matrix

| Knowledge area | Source docs | Decoder status | Notes |
| --- | --- | --- | --- |
| `cbuf_file.bin = insts + exeblock + instance` | [CBUF](../../runtime/data/cbuf.md) | Implemented | Section offsets, row sizes, dimensions, row decode, offset lookup, and file-size guard are in the DFU3500 profile. |
| `micc_file.bin = tasks + subtasks` | [MICC](../../runtime/data/micc.md) | Implemented | Task/subtask rows are profile-backed; MICC active-ish diagnostics are DFU3500-specific helper views. |
| Component files: `insts_file.bin`, `exeblock_conf_info_file.bin`, `instance_conf_info_file.bin`, `tasks_conf_info_file.bin`, `subtasks_conf_info_file.bin` | [binary packaging](README.md) | Implemented + validated | Each component is modeled as a file kind sharing the same struct/section metadata as the combined image. `dfu3500_component_consistency` now verifies component bytes against `result/` images for `RUNTIME_READY`. |
| Struct sizes and field offsets | [vendor struct audit](research_notes/binary/2026-06-20_vendor_struct_layout_audit.md) | Implemented for known fields | Profile status is `complete_for_known_fields`; padding is reported as padding, not guessed. |
| Source fingerprints | [source fingerprint index](../../vendor_reference/common_oper/source-fingerprint-index.md) | Partially implemented | Profile embeds audited hashes for clean common headers; automated local source verification is not implemented yet. |
| Field-aware offset lookup | Decoder RFC and tests | Implemented | Reports section, row indices, struct, field, byte-in-field, raw hex, decoded value, and padding/unknown classification. |
| Field-aware binary diff | Decoder RFC and tests | Implemented | Groups multi-byte field changes; preserves raw byte count; classifies value/padding/unknown/length diff. |
| Active rows vs padded capacity | [MICC](../../runtime/data/micc.md); [A-line pain retrospective](research_notes/binary/2026-06-20_a_line_pain_retrospective.md) | Diagnostic-only | `active-ish` is nonzero-row heuristic; runnable task count must come from package/control validation, not decoder heuristics. |
| A-line task-count failures | [A-line pain retrospective](research_notes/binary/2026-06-20_a_line_pain_retrospective.md) | Diagnostic support | `compare_dfu_payloads.py` can expose `4 -> 1` active-task/subtask deltas and short MICC image staging mistakes. |
| `data_inst_replace.bin`, `instEnable.bin`, `taskEnable.bin` | [auxiliary artifacts](../../runtime/data/auxiliary-artifacts.md) | Closed as optional collateral | Boundary is known: optional sidecars, not CBUF/MICC truth. They must not drive runtime readiness, active task count, or instruction readiness unless new consumer evidence appears. |
| RTL narrow instruction encoding | [RTL](../../runtime/data/rtl.md) | Not decoded yet | Current profile decodes wide SimICT `inst_t` rows only. RTL `inst_t_*_for_rtl` bitfields need a separate file/profile view. |
| Runtime messages and mesh/control packets | [messages](../../runtime/data/messages.md) | Out of scope | These runtime in-flight structures are not current payload images and are intentionally not a decoder priority. |
| Opcode mnemonic annotation | [DFU3500 SIMD ISA](../../architecture/instruction-set/dfu3500-simd/README.md) | Implemented | `inst_t.opCode` rows now annotate values such as `FMAX`, `FLOG2`, `STD`, `COPY`, and tensor opcodes. |
| Operand/template instruction semantics | [DFU3500 SIMD ISA](../../architecture/instruction-set/dfu3500-simd/README.md); [memory/template notes](../../architecture/instruction-set/dfu3500-simd/MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md) | Out of scope | Decoder names opcodes but does not prove operand ownership, pseudo expansion, memory binding, or runnable template legality. |
| Route endpoint ownership and operand-resource semantics | [operand/resource audit](../../vendor_reference/common_oper/operand-resource-and-route-audit.md) | Not validated yet | Decoder exposes fields; semantic checks such as receiver-owned destination operands belong in a package/template verifier layer. |
| Task/subtask/exeBlock graph legality | [common task graph audit](research_notes/binary/2026-06-20_common_oper_task_graph_exeblock_audit.md) | Partially validated | Fields such as start/end flags, task/subtask stamps, active task count, block counts, stage PC ranges, and explicitly declared exeBlock predecessor/successor reciprocity are checked by `dfu3500_control_graph`. Richer multi-block vendor evidence remains future work; enable sidecars stay non-authoritative. |
| RISC-V runtime control / launch contract | [runtime evidence](../../vendor_reference/runtime_evidence/README.md) | Out of scope | Decoder can inspect emitted files but does not decide DMA/start/wait/finish correctness. |
| Manifest/runtime readiness | [binary packaging](README.md) | Minimal compare support | `compare_dfu_payloads.py` reads manifests and catches file conformance, but full `runtime_runnable` validation belongs outside the decoder. |

## What “Done” Means For Decoder Coverage

The decoder is not done until every binary knowledge area is in one of these
explicit buckets:

```text
implemented:
  profile-backed decode/diff/lookup exists and tests cover it

diagnostic-only:
  decoder reports suspicious facts but does not claim semantic truth

documentation-only:
  source facts are indexed here, with an owner for future implementation

out-of-scope:
  explicitly belongs to runtime/package/template verifier instead
```

Current state:

```text
Phase 1/2 core decoder: strong
DFU3500 CBUF/MICC/component profile: useful and tested
sidecars: closed as optional collateral
RTL: not yet embodied
runtime messages: intentionally out of scope
opcode mnemonic annotation: implemented
operand/template semantics: intentionally outside decoder
semantic package legality: intentionally outside decoder
```

So the honest answer is:

```text
The decoder is usable now, but it is not complete as a total binary knowledge
repository yet.
```

## Near-Term Gaps To Close

1. Keep auxiliary sidecars optional and non-authoritative unless new runtime
   consumer evidence appears.
2. Add source-fingerprint verification against the local vendor tree.
3. Add RTL narrow encoding profile only after deciding which RTL files are stable
   mainline validation inputs.
4. Strengthen graph-legality checks outside the generic decoder, especially
   multi-block vendor evidence while keeping enable sidecars non-authoritative.

## Practical Usage

Decode a combined CBUF summary:

```bash
python compiler/tools/decode_dfu_binary.py \
  --kind cbuf \
  --input path/to/cbuf_file.bin \
  --summary
```

Look up a suspicious MICC byte offset:

```bash
python compiler/tools/decode_dfu_binary.py \
  --kind micc \
  --input path/to/micc_file.bin \
  --offset 0x1234
```

Compare a known-good and suspicious payload:

```bash
python compiler/tools/compare_dfu_payloads.py \
  --good tmp/good_payload \
  --bad tmp/bad_payload \
  --format json
```

Print the decoder coverage boundary:

```bash
python compiler/tools/decode_dfu_binary.py --coverage
```
