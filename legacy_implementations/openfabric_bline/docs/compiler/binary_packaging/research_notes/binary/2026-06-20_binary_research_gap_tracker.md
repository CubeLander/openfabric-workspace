# Binary Research Gap Tracker

Date: 2026-06-20

Status: active notes index for binary / MICC / CBUF research gaps

This tracker keeps the current binary research gaps in `docs/compiler/binary_packaging/research_notes/binary`.
Only move an item into polished docs after we have source evidence, payload
validation evidence, or both.

## Current Notes

| Note | Main purpose |
| --- | --- |
| `2026-06-20_common_oper_task_graph_exeblock_audit.md` | Source-backed overview of task config, graph generation, stage split, exeBlock metadata, task/subtask rows, padding. |
| `2026-06-20_task_print_component_writer_audit.md` | Writer-side conversion to component files: instruction projection, stage PCs, active vs padded rows, runtime agreement guards. |
| `2026-06-20_inst_blk_map_resource_owner_audit.md` | Resource owner sequence: task windows, operand allocation, COPY patching, local COPY rewrite, app capacity accounting. |
| `2026-06-20_vendor_struct_layout_audit.md` | Clean-header struct sizes/offsets and CBUF/MICC component size formulas. |
| `2026-06-20_data_inst_replace_and_enable_files_audit.md` | Auxiliary artifact evidence for data_inst_replace, instEnable, taskEnable. |
| `2026-06-20_functional_probe_manual_abi_assumptions.md` | A-line manual ABI assumptions and runnable maximum-probe lessons. |
| `2026-06-20_a_line_pain_retrospective.md` | Pain retrospective explaining why A-line binary patching is not sustainable. |
| `common_oper_source_gap_audit.md` | Older source-gap landing page; now links to the detailed follow-up notes. |

## P0 Gaps Blocking Reliable B-line Binary Emission

### 1. Exact simulator struct definitions

Local clean-header layouts are now captured in `2026-06-20_vendor_struct_layout_audit.md`. Still need arch-13 confirmation and reusable decoders for:

```text
inst_t
task_conf_info_t
sub_task_conf_info_t
exe_block_conf_info_t
instance_conf_info_t
data_inst_replace row
```

Known evidence:

```text
task_print.cpp writer behavior
existing OpenFabric generated component sizes
remote SimICT runtime behavior
```

Still needed:

```text
arch-13 header fingerprint / sizeof / offsetof confirmation
byte-level layout decoder/test for every component row type
```

### 2. Runtime active count vs padded capacity

Known from A-line:

```text
one active task + 4-task runtime expectation caused wrong behavior
component blobs are padded to fixed capacity
runtime launch count must use active rows, not padded rows
```

Still needed:

```text
single source of truth in B-line VendorComponentPlan / RuntimeControlPlan
verifier that rejects active-count / runtime-count mismatch
```

### 3. Base address selector ownership

Known from `task_print.cpp`:

```text
iter_exe_cond feeds base_addr_idx for many instruction families
COPY uses flow_ack as base_addr_idx in RTL projection
IMM/FIMM split immediates into imm_1/imm_2
```

Still needed:

```text
source-backed mapping for simulator inst_t fields, not only RTL projection
B-line BaseAddressBindingPlan design and tests
```

### 4. Operand tag allocation and COPY patching

Known from `inst_blk_map.cpp`:

```text
operand allocation runs before COPY destination patching
COPY destination operand is retrieved from receiver task resource
COPYT lane rows advance by OPERANDS_PER_OPERAND_RAM
```

Still needed:

```text
current arch-13 source/version confirmation
B-line deterministic replay/verifier over stream/fiber actions
route endpoint lineage from stream/fiber IR to final COPY row
```

### 5. Stage PC and instruction stream layout

Known from `task_print.cpp` / `exe_block_gen.cpp`:

```text
LD/CAL/FLOW/ST stage order is fixed
only valid instructions are counted
stage PCs are PE-local instruction offsets
per-PE streams are padded then merged
```

Still needed:

```text
B-line InstructionLayoutPlan with stable dump
golden compare on tiny functional probe and GEMM template path
```

## P1 Gaps Needed For Better ISA Knowledge Base

### 1. `taskEnable.bin` semantics

Current evidence is captured in `2026-06-20_data_inst_replace_and_enable_files_audit.md`.

Known:

```text
task_print.cpp emits taskEnable with a reversed-looking enable pattern
```

Unknown:

```text
whether SimICT runtime consumes this file
whether it is RTL-only debug collateral
whether arch-13 differs
```

### 2. `data_inst_replace.bin` semantics

Current evidence is captured in `2026-06-20_data_inst_replace_and_enable_files_audit.md`.

Known:

```text
`task_inst_enable_print()` writes it
```

Unknown:

```text
runtime/RTL consumer
row format
relationship to data instruction replacement and base address patching
```

### 3. `REDUCE` compile-time mode

Known:

```text
inst_blk_map.cpp switches fill_reg_idx vs fill_reg_idx_rd under REDUCE
```

Unknown:

```text
which deployed cases compile with REDUCE
how REDUCE changes operand allocation and copy patching
```

### 4. Special CAL / FRCP-family encoding

Known:

```text
FLOG2/FEXP2 and related ops collapse into OP_FRCP in RTL projection with imm bits
```

Unknown:

```text
exact simulator inst_t encoding path for these ops
which vendor cases execute FLOG2/FMAX/FEXP2 in SimICT
numerical dtype/conversion envelope
```

## B-line Design Hooks That Should Consume These Notes

```text
TaskControlPlan:
  active task/subtask rows, start/end/successor flags, runtime count

TaskResourceWindow:
  task-scoped PE resource allocation window

RouteEndpointBinding:
  child-owned COPY destination block/PE/operand patching

InstructionLayoutPlan:
  valid instruction rows, stage groups, PE-local PCs, final merge order

BaseAddressBindingPlan:
  iter_exe_cond / flow_ack / base slot assignment

VendorComponentPlan:
  active rows vs padded component capacity, component sizes

RuntimeControlPlan:
  active launch count, payload-local runtime assets, output collection
```

## Research Discipline Going Forward

No binary interface field should be introduced by guesswork.  For every field,
record at least one of:

```text
1. original source file + line range,
2. original document section,
3. byte-level diff evidence,
4. remote SimICT runtime evidence.
```

If none exists, the field belongs in `docs/compiler/binary_packaging/research_notes/binary` as an open gap, not
in polished docs and not in a runnable-code path.

## 2026-06-20 Parallel Audit Update

```text
CBUF_ISTC_CONST:
  no local writer/reader found; emitted cbuf remains inst+exeBlock+instance.

REDUCE:
  local build does not enable it; keep as capability flag / remote-diff risk.

FRCP/FLOG2 family:
  simulator inst_t preserves original opcode; RTL projection folds to OP_FRCP.
  FEXP2/FMAX real cases exist; FLOG2 still lacks real app CSV evidence.

data_inst_replace / enable files:
  writer/staging only; no local runtime consumer found; treat as optional sidecar.
```
