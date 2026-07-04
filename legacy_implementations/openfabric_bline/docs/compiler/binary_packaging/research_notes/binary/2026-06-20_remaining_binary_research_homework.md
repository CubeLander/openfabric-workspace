# Remaining Binary Research Homework

Date: 2026-06-20

Status: active homework table for DFU3500 binary / runtime research

This note is the current homework board for binary-interface knowledge that is
not yet ready to graduate into `docs/vendor_reference`.  Detailed working notes
live mostly under:

```text
docs/compiler/binary_packaging/research_notes/binary
```

The goal is not to collect mysteries forever.  Each row should either become:

```text
1. source-backed documentation,
2. a B-line verifier/tooling task,
3. or a deliberately deferred unknown with a clear owner.
```

## Summary Table

| ID | Topic | Current status | Why it matters | Next evidence needed | Suggested owner/output | Priority |
| --- | --- | --- | --- | --- | --- | --- |
| BIN-001 | Arch-13 header/layout confirmation | Local clean `common/src` layouts captured; remote arch-13 layout not confirmed. | Local `inst_t=304`, `exeBlock_conf_info_t=520`, `sub_task_conf_info_t=266328` explain current blobs, but remote mismatch would poison byte emit. | Run/collect arch-13 `sha256sum` + `sizeof/offsetof` for `inst_t`, `task_conf_info_t`, `sub_task_conf_info_t`, `exeBlock_conf_info_t`, `instance_conf_info_t`. | `docs/compiler/binary_packaging/research_notes/binary` remote layout addendum; later `docs/vendor_reference/common_oper`. | P0 |
| BIN-002 | Reusable CBUF/MICC decoder | Not implemented; we only have manual layout notes. | Future diffs must decode to field names, not raw offsets. | Implement decoder using clean header layout; validate on known cbuf/micc sizes and old diff offsets. | `compiler/tools/decode_dfu3500_binary.py` or equivalent; no docs migration until tested. | P0 |
| BIN-003 | `CBUF_ISTC_CONST` section | Parallel audit found no local writer/reader; package scripts and observed size exclude it. | Wrong inclusion changes CBUF size by 1280 bytes and shifts MICC address-space reasoning. | Only remaining uncertainty is closed SimICT/runtime internals or arch-13-specific behavior. | Treat emitted `cbuf_file.bin` as inst+exeBlock+instance; keep address-space const area separate. | P0 |
| BIN-004 | Runtime active count vs padded capacity | A-line bug class understood; guard concept documented. | One active task must not become four runtime tasks; this caused wasted remote loops. | Add B-line/mainline verifier tying active task rows to runtime launch count. | `RuntimeControlPlan` / `VendorComponentPlan` guard. | P0 |
| BIN-005 | `iter_exe_cond` / base selector semantics | Writer RTL projection shows usage; simulator `inst_t` consumer not fully traced. | We need know whether it is base slot, loop condition, or both by instruction family. | Find PE execution consumer of `iter_exe_cond`; map per opcode family. | `BaseAddressBindingPlan` note + tests. | P0 |
| BIN-006 | COPY/COPYT endpoint binding | Source shows child-owned destination block/operand; B-line hook documented. | Route lowering cannot guess receiver operand indices locally. | Build verifier/replay over stream/fiber actions; validate with GEMM route diffs. | `RouteEndpointBinding` / task resource replay tests. | P0 |
| BIN-007 | `data_inst_replace.bin` semantics | Parallel audit found writer/staging only; no local runtime/SimICT source-level consumer. | It should remain optional compatibility artifact, not runtime readiness input. | Only remaining uncertainty is closed runtime/SimICT internals. | Manifest as optional `required_for_final_runtime=false`; do not include in cbuf/micc hashes. | P1 |
| BIN-008 | `taskEnable.bin` / `instEnable.bin` semantics | Writer/staging evidence only; no local runtime consumer found; `taskEnable` mask remains RTL-looking. | Must not be used as runtime task source of truth accidentally. | Closed-runtime evidence only if we want stronger proof. | Keep runtime task count sourced from `TaskControlPlan` / `RuntimeControlPlan`. | P1 |
| BIN-009 | `REDUCE` / `fill_reg_idx_rd()` mode | Parallel audit found local default not enabled: `//#define REDUCE 1`, no `-DREDUCE` in local Makefiles/workflow. | If arch-13 enables it, operand allocation can insert MOVE and change COPY dst operands/PCs. | Confirm arch-13 build flags if future diffs suggest REDUCE behavior. | Keep B-line capability flag; default non-REDUCE replay. | P1 |
| BIN-010 | FLOG2/FEXP2/FRCP-family encoding | Parallel audit: simulator `inst_t` preserves original opcode; RTL projection folds to `OP_FRCP` + imm bits. `FEXP2` and `FMAX` cases exist; no application CSV `FLOG2` found. | Non-GEMM local compute/log probes need correct executable encoding and unary operand handling. | Need runtime smoke for `FLOG2`; bind FRCP-family as unary despite raw empty operand becoming 0. | ISA docs addendum + template binding tests. | P1 |
| BIN-011 | `data_inst_replace` multi-app behavior | Packaging appends optional sidecar per app; semantics still unproven. | Multi-app may concatenate `1 1` markers, but runtime significance is unknown. | Inspect generated multi-app result only if compatibility wrapper needs exact sidecar text. | Packaging note + manifest rule. | P2 |
| BIN-012 | `CBUF_ISTC_CONST` vs `MICC_BASE_ADDR` address-space model | Local source supports split: address macros include const area, emitted cbuf excludes it. | B-line must distinguish address map from emitted file layout. | Remote/runtime proof only if we need closed-world certainty. | `VendorAddressSpacePlan` vs `VendorComponentFilePlan`. | P0 |
| BIN-013 | Struct layout decoder for subtask-embedded exeBlocks | Layout known; decoder missing. | MICC subtask rows embed 512 exeBlock rows, so field-level diagnosis otherwise painful. | Build decoder that prints active/padded subtask and embedded exeBlock summaries. | `compiler/tools` decoder + notes. | P0 |
| BIN-014 | Source-version audit discipline | Local `common/src`, `src_ocr`, and arch-13 versions may differ. | We have already been bitten by version ghosts. | Standardize fingerprint capture for every audited source/binary. | Note template/checklist; maybe helper script. | P1 |

## Current Evidence Notes

| Note | Covers |
| --- | --- |
| `docs/compiler/binary_packaging/research_notes/binary/2026-06-20_vendor_struct_layout_audit.md` | Clean header layout, sizes, component formulas, `inst_t=304`, CBUF observed size. |
| `docs/compiler/binary_packaging/research_notes/binary/2026-06-20_task_print_component_writer_audit.md` | Writer behavior, stage PC rebasing, active vs padded rows, task/subtask chains. |
| `docs/compiler/binary_packaging/research_notes/binary/2026-06-20_inst_blk_map_resource_owner_audit.md` | Task resource windows, operand allocation, COPY patching. |
| `docs/compiler/binary_packaging/research_notes/binary/2026-06-20_data_inst_replace_and_enable_files_audit.md` | Auxiliary file generation/staging and conservative interpretation. |
| `docs/compiler/binary_packaging/research_notes/binary/2026-06-20_binary_research_gap_tracker.md` | Binary notes index and P0/P1 gaps. |

## Suggested Parallel Investigation Batches

These tasks are independent and can be delegated safely:

```text
Batch A:
  BIN-003 / BIN-012: CBUF_ISTC_CONST reader/writer and address-space split.

Batch B:
  BIN-009: REDUCE / fill_reg_idx_rd mode and deployed cases.

Batch C:
  BIN-010: FLOG2/FEXP2/FRCP-family executable encoding and real cases.

Batch D:
  BIN-007 / BIN-008 / BIN-011: data_inst_replace and enable-file consumers.
```

## Rules For Closing A Row

A row can be marked closed only when it has one of:

```text
1. source file + line evidence,
2. original vendor document section,
3. byte-level diff / decoder evidence,
4. remote SimICT evidence,
5. or explicit “not found” audit across named source roots.
```

No more “probably”.  Binary interfaces are where guesses go to die, usually with
our weekend attached.  Tiny bit dramatic, but earned.


## Parallel Investigation Results Integrated

Date: 2026-06-20

| Batch | Result | Effect on table |
| --- | --- | --- |
| CBUF const area | No local writer/reader found; package scripts concatenate only inst/exeBlock/instance; observed size excludes 1280-byte const area. | BIN-003/BIN-012 downgraded from open source search to closed-runtime/arch-13 confirmation risk. |
| REDUCE mode | Local default does not enable `REDUCE`; no local `-DREDUCE`; REDUCE path can insert `MOVE` and alter operand allocation if enabled elsewhere. | BIN-009 downgraded to capability flag / remote build-flag confirmation. |
| FRCP/FLOG2 family | Simulator `inst_t` keeps original opcode; RTL projection folds special family to `OP_FRCP` + imm bits; `FEXP2` and `FMAX` real cases exist, no app CSV `FLOG2` found. | BIN-010 clarified: bind simulator rows by original opcode; do not confuse RTL projection with SimICT row. |
| data_inst_replace / enable files | Writer/staging only found; no local runtime/SimICT source-level consumer; OpenFabric already marks optional in debug IR. | BIN-007/BIN-008 remain optional compatibility artifacts unless closed runtime says otherwise. |
