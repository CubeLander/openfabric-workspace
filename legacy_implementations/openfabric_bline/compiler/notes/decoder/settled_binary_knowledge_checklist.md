# Settled Binary Knowledge Checklist

Date: 2026-06-21

Status: active audit checkpoint

Purpose:

```text
Record which DFU binary / memory-layout facts have already been embodied in
decoder or validation tooling, so future agents do not repeatedly re-audit the
same ground.
```

This is not a replacement for stable docs.  It is a working checklist for
engineering execution.

## Settled In Decoder

- [x] Generic profile model for DFU binary files, sections, rows, structs, and
  fields.
  - Owner: `compiler/gpdpu_compiler/decoder/binary_layout.py`
  - Tests: `tests/test_decode_dfu_binary.py`

- [x] DFU3500 SimICT legacy CBUF combined image layout:
  `insts + exeblocks + instances`.
  - Owner: `compiler/gpdpu_compiler/decoder/profiles/dfu3500.py`
  - Stable docs: `docs/runtime/data/cbuf.md`

- [x] DFU3500 SimICT legacy MICC combined image layout:
  `tasks + subtasks`.
  - Owner: `compiler/gpdpu_compiler/decoder/profiles/dfu3500.py`
  - Stable docs: `docs/runtime/data/micc.md`

- [x] Component file profiles for:
  `insts_file.bin`, `exeblock_conf_info_file.bin`,
  `instance_conf_info_file.bin`, `tasks_conf_info_file.bin`,
  `subtasks_conf_info_file.bin`.
  - Owner: `compiler/gpdpu_compiler/decoder/profiles/dfu3500.py`

- [x] Known struct sizes / known field offsets for wide SimICT rows:
  `inst_t`, `exeBlock_conf_t`, `exeBlock_conf_info_t`,
  `instance_conf_info_t`, `task_conf_info_t`, `sub_task_conf_info_t`.
  - Owner: `compiler/gpdpu_compiler/decoder/profiles/dfu3500.py`
  - Evidence: `docs/compiler/binary_packaging/research_notes/binary/2026-06-20_vendor_struct_layout_audit.md`

- [x] Padding and unknown ranges are classified honestly.
  - Owner: `compiler/gpdpu_compiler/decoder/binary_decoder.py`
  - Policy: do not guess unverified fields.

- [x] Summary / row decode / nested struct and array decode.
  - Owner: `compiler/gpdpu_compiler/decoder/binary_decoder.py`
  - CLI: `compiler/tools/decode_dfu_binary.py`

- [x] Byte-offset lookup with section / row / field / byte-in-field context.
  - Owner: `compiler/gpdpu_compiler/decoder/binary_decoder.py`

- [x] Field-aware binary diff.
  - Owner: `compiler/gpdpu_compiler/decoder/binary_diff.py`
  - CLI: `compiler/tools/decode_dfu_binary.py --diff`

- [x] Payload-level CBUF/MICC comparator.
  - Owner: `compiler/tools/compare_dfu_payloads.py`

- [x] DFU3500 wide `inst_t.opCode` annotation:
  mnemonic/category plus source-backed latency, src_count, need_pe_idx,
  unit_inst_type, and pseudo opcode status.
  - Owner: `compiler/gpdpu_compiler/decoder/dfu3500_isa.py`
  - Boundary: decoder metadata only; validation owns legality checks.

- [x] DFU3500 MICC active-ish diagnostic summary.
  - Owner: `compiler/gpdpu_compiler/decoder/dfu3500_diagnostics.py`
  - Boundary: active-ish is a heuristic, not runtime truth.

- [x] Auxiliary sidecars are classified as optional / non-authoritative:
  `data_inst_replace.bin`, `instEnable.bin`, `taskEnable.bin`.
  - Decision note: `compiler/notes/decoder/auxiliary_sidecar_decision.md`

## Settled In Validation

- [x] Validation report / readiness gate contract:
  `INSPECTABLE`, `PACKAGE_COMPLETE`, `RUNTIME_READY`.
  - Owner: `compiler/gpdpu_compiler/validation/dfu_binary_checks/report.py`

- [x] Payload conformance:
  required CBUF/MICC files exist, profile sizes match, and readiness-critical
  artifacts must have manifest size/hash claims that match actual files.
  - Owner: `compiler/gpdpu_compiler/validation/dfu_binary_checks/payload_conformance.py`

- [x] Runtime readiness:
  payload-local input data, RISC-V source/config assets, runtime control JSON,
  input/output DMA shape, and reference presence.
  - Owner: `compiler/gpdpu_compiler/validation/dfu_binary_checks/runtime_readiness.py`

- [x] Runtime memory layout:
  tensor SPM regions, dtype/shape byte sizes, reference sizes, input transfer
  coverage, DMA transfer size/offset, and input/output region overlap.
  - Owner: `compiler/gpdpu_compiler/validation/dfu_binary_checks/runtime_memory_layout.py`

- [x] Component consistency:
  `config/` copies and `simulator_bin/` section files match combined
  `result/` CBUF/MICC images.
  - Owner: `compiler/gpdpu_compiler/validation/dfu3500_package_checks/component_consistency_check.py`

- [x] Active task count must match `RuntimeControlPlan` launch task count.
  - Owner: `compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py`

- [x] Active task rows outside expected launch range are rejected.
  - Owner: `compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py`

- [x] Task successor graph checks:
  nonzero successor must point to active task, duplicates rejected, cycles
  rejected.
  - Owner: `compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py`

- [x] Task -> subtask references:
  duplicate subtask refs rejected, inactive referenced subtasks rejected,
  exactly one start and one end among active referenced subtasks.
  - Owner: `compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py`

- [x] Subtask successor graph checks:
  nonzero successor must point to active referenced subtask, duplicates
  rejected, cycles rejected, declared successor graph must reach active
  subtasks from start.
  - Owner: `compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py`

- [x] Active subtask task/subtask stamps must match row coordinates.
  - Owner: `compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py`

- [x] Subtask exeBlock counts:
  `block_amount`, `root_block_amount`, valid embedded exeBlock count sanity.
  - Owner: `compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py`

- [x] Active exeBlock task/subtask stamps must match parent subtask.
  - Owner: `compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py`

- [x] exeBlock stage PC and stage span must fit PE-local instruction capacity.
  - Owner: `compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py`

- [x] Active exeBlock stage instruction spans must point to meaningful CBUF rows:
  referenced rows are not all-zero padding and `opCode` is known by the ISA
  annotation table.
  - Owner: `compiler/gpdpu_compiler/validation/dfu3500_package_checks/instruction_span_check.py`

- [x] Active CBUF instruction rows must conform to source-backed opcode
  metadata:
  pseudo opcodes rejected, `unit_inst_type` matched, and `latency` matched.
  - Owner: `compiler/gpdpu_compiler/validation/dfu3500_package_checks/opcode_conformance_check.py`
  - Boundary: src_count / need_pe_idx are metadata only until operand verifier
    work lands.

- [x] Active CBUF instruction operand / route resource fields must fit hardware
  bounds:
  operand indices, destination block indices, destination PE positions, and
  bool-like fetch/forward/bypass flags are checked.
  - Owner: `compiler/gpdpu_compiler/validation/dfu3500_package_checks/operand_resource_check.py`
  - Boundary: route endpoint ownership and operand lifetime still need typed
    B-line route/resource plans.

- [x] Active memory/template rows must consume valid instance base slots:
  `iter_exe_cond`, `flow_ack`, and active instance `base_addr[slot]` sentinel
  checks are enforced.
  - Owner: `compiler/gpdpu_compiler/validation/dfu3500_package_checks/memory_template_check.py`
  - Boundary: operator-specific memory intent and byte/word address semantics
    remain future template verifier work.

- [x] exeBlock predecessor/successor reciprocity, reachability from roots, and
  successor cycles.
  - Owner: `compiler/gpdpu_compiler/validation/dfu3500_package_checks/control_graph_check.py`

- [x] Archived `validation/runtime_ready.json` freshness:
  recorded input sha256 values must still match current payload files.
  - Owner: `compiler/gpdpu_compiler/validation/dfu_binary_checks/report_freshness.py`

## Settled As Non-goals / Deferred

- [x] Runtime in-flight message structs are not current payload image decode
  priority.
  - Stable docs: `docs/runtime/data/messages.md`

- [x] RTL narrow instruction encodings are not mixed into wide SimICT `inst_t`
  decoder.
  - Future owner, if needed: separate RTL profile.

- [x] Decoder does not prove `runtime_runnable=true`.
  - Owner boundary: validation/package checks judge artifacts.

- [x] Decoder does not prove operand/template/operator semantics.
  - Future owner: template/package verifier.

- [x] Remote runtime output closure is deferred under current artifact-access
  constraints.
  - RFC: `docs/compiler/binary_packaging/research_notes/enhancements/rfc-runtime-output-closure.md`

## Re-audit Trigger

Re-open this checklist only if one of these happens:

```text
vendor source snapshot changes
DFU3500 runtime profile changes
new component/sidecar becomes a proven runtime input
RTL files become mainline validation artifacts
B-line template verifier starts consuming operand/route/resource semantics
```
