# Binary Notes To Docs Reduction Plan

Date: 2026-06-20

Status: migration design; do not treat as final docs

This note inventories where binary/image knowledge currently lives and proposes
how to reduce working notes into the `docs/` knowledge tree without creating a
new confusing top-level silo.

## Executive Decision

Do **not** create a new top-level `docs/binary` directory for now.

The repository already has the right three-way split:

```text
docs/runtime/data/
  Runtime-consumed binary image truth: CBUF, MICC, RTL/debug artifacts, messages.

docs/compiler/binary_packaging/
  OpenFabric compiler-side plan: how IR/binding/resource plans emit vendor images.

docs/vendor_reference/common_oper/
  Vendor source evidence: common_oper, task_print, inst_blk_map, scripts.
```

A new `docs/binary` would blur these ownership boundaries.  Binary/image facts
are shared, but their questions differ:

```text
What is the binary layout?             -> docs/runtime/data
How does OpenFabric generate it?       -> docs/compiler/binary_packaging
Where did the vendor behavior come from? -> docs/vendor_reference/common_oper
```

## Current Working Notes Inventory

### `docs/compiler/binary_packaging/research_notes/binary`

| File | Current role | Should reduce into |
| --- | --- | --- |
| `2026-06-20_vendor_struct_layout_audit.md` | clean header struct sizes/offsets, component size formulas | `docs/runtime/data/cbuf.md`, `docs/runtime/data/micc.md`, `docs/runtime/data/README.md`; source citations mirrored in `docs/vendor_reference/common_oper` |
| `2026-06-20_task_print_component_writer_audit.md` | writer behavior: inst streams, stage PC, active rows, padding, task/subtask chains | `docs/vendor_reference/common_oper/task-print-component-writer.md` plus compiler packaging guards |
| `2026-06-20_inst_blk_map_resource_owner_audit.md` | task resource windows, operand allocation, COPY endpoint patching | `docs/vendor_reference/common_oper/operand-resource-and-route-audit.md`; B-line owner map in `docs/compiler/binary_packaging` |
| `2026-06-20_common_oper_task_graph_exeblock_audit.md` | task_create/graph/exeBlock common chain | `docs/vendor_reference/common_oper/binary-artifact-generation-pipeline.md` and possible new `task-graph-exeblock-audit.md` |
| `2026-06-20_data_inst_replace_and_enable_files_audit.md` | auxiliary sidecar files and conservative semantics | `docs/runtime/data/auxiliary-artifacts.md` or `docs/runtime/data/rtl.md`; vendor source evidence in common_oper |
| `2026-06-20_binary_research_gap_tracker.md` | active gap tracker | Stay in `docs/compiler/binary_packaging/research_notes/binary` until gaps close; link from docs only if needed |
| `2026-06-20_functional_probe_manual_abi_assumptions.md` | A-line manual ABI assumptions | Keep as historical note; summarize lessons in `docs/compiler/binary_packaging/README.md` |
| `2026-06-20_a_line_pain_retrospective.md` | A-line pain / why B-line exists | Keep in notes; extract principles into `docs/compiler/design` or `binary_packaging` |
| `common_oper_source_gap_audit.md` | older landing/index for source gap audits | Replace with links to new notes; later archive or fold into `docs/vendor_reference/original_materials_audit.md` |
| `dfu3500_gemm_diff3_notes.md` | old byte diff analysis | Keep as historical evidence; distill stable facts into common_oper/runtime data docs |
| `inst_blk_map_arch13_analysis.md` | old arch13 inst_blk_map analysis | Merge stable facts into resource owner docs; leave raw analysis in notes |
| `rfc-dfu3500-taskresource-replay-handoff.md` | design/RFC for TaskResource replay | Move stable design decisions to `docs/compiler/binary_packaging/task-resource-replay.md` |
| `taskresource_order_replay_update.md` | TaskResource replay update | Fold into compiler packaging / route endpoint binding docs |
| `taskresource_replay_diff_analysis.md` | TaskResource diff analysis | Historical evidence; summarize stable algorithm in vendor_reference/common_oper |
| `vendor_node_traversal_order.md` | vendor node traversal ordering | Fold into common_oper task/graph docs |

### Other binary-ish notes outside `docs/compiler/binary_packaging/research_notes/binary`

| File/area | Current role | Should reduce into |
| --- | --- | --- |
| `docs/compiler/binary_packaging/research_notes/binary/2026-06-20_remaining_binary_research_homework.md` | current homework board | Keep active in notes; create docs TODO only after priorities stabilize |
| `docs/compiler/binary_packaging/research_notes/enhancements/2026-06-20_a_line_binary_memory_mud_for_b_line.md` | B-line lessons from A-line binary/memory pain | `docs/compiler/binary_packaging/README.md` + B-line design docs |
| `docs/compiler/binary_packaging/research_notes/enhancements/rfc-b-line-template-op-binary-plan.md` | B-line template/binary plan | `docs/compiler/binary_packaging/template-op-binding.md` when accepted/stable |
| `docs/compiler/binary_packaging/research_notes/enhancements/rfc-fiber-executable-role-binding.md` | executable role binding | `docs/compiler/lowering` or `binary_packaging`, depending on final implementation boundary |
| `docs/compiler/binary_packaging/research_notes/archive/rfc-vendor-multi-app-package-semantics.md` | vendor app/package semantics | `docs/compiler/binary_packaging/vendor-package-plan.md` + `docs/runtime/workflow` |
| `docs/compiler/binary_packaging/research_notes/archive/app-plan-vs-runtime-image.md` | app plan vs image boundary | `docs/compiler/binary_packaging` + `docs/runtime/workflow` |

## Existing Docs That Already Own Parts Of This

### Runtime data truth

```text
docs/runtime/data/README.md
docs/runtime/data/cbuf.md
docs/runtime/data/micc.md
docs/runtime/data/rtl.md
docs/runtime/data/messages.md
```

These already contain much of the clean struct layout.  They should receive:

```text
- clean-header fingerprints,
- CBUF_ISTC_CONST exclusion note,
- optional auxiliary artifact note,
- field offset verification provenance.
```

### Compiler packaging truth

```text
docs/compiler/binary_packaging/README.md
```

This directory is currently too thin.  It should become the compiler-facing
home for:

```text
- active rows vs padded capacity guards,
- InstructionLayoutPlan,
- VendorComponentPlan,
- RouteEndpointBinding,
- TaskResourceWindow / TaskResource replay,
- BaseAddressBindingPlan,
- RuntimeControlPlan handoff requirements.
```

### Vendor evidence truth

```text
docs/vendor_reference/common_oper/README.md
```

This should receive the source-backed evidence pages:

```text
- task_print component writer,
- inst_blk_map resource owner,
- common_oper task/graph/exeBlock audit,
- auxiliary artifacts evidence,
- clean header/source fingerprint index.
```

## Proposed Final Docs Shape

### 1. `docs/runtime/data` should be the binary image reference

Proposed tree:

```text
docs/runtime/data/
  README.md
  cbuf.md
  micc.md
  rtl.md
  messages.md
  auxiliary-artifacts.md      # new: data_inst_replace / instEnable / taskEnable
  component-size-formulas.md  # optional if cbuf/micc pages get too long
```

Ownership:

```text
CBUF/MICC row layout
file sizes
emitted image vs address-space distinction
runtime-staged sidecar artifacts
```

Recommended migrations:

```text
vendor_struct_layout_audit -> cbuf.md / micc.md / component-size-formulas.md
data_inst_replace_and_enable_files_audit -> auxiliary-artifacts.md
```

### 2. `docs/compiler/binary_packaging` should be the compiler plan reference

Proposed tree:

```text
docs/compiler/binary_packaging/
  README.md
  vendor-component-plan.md
  instruction-layout-plan.md
  task-resource-replay.md
  route-endpoint-binding.md
  base-address-binding.md
  runnable-package-guards.md
```

Ownership:

```text
how OpenFabric should generate these binary images
which verifier guards must fire before runtime_runnable=true
which B-line owner object consumes vendor facts
```

Recommended migrations:

```text
task_print_component_writer_audit -> vendor-component-plan.md + runnable-package-guards.md
inst_blk_map_resource_owner_audit -> task-resource-replay.md + route-endpoint-binding.md
functional_probe_manual_abi_assumptions -> runnable-package-guards.md
a_line_pain_retrospective -> README principles / design warning
```

### 3. `docs/vendor_reference/common_oper` should keep vendor-source evidence

Proposed additions:

```text
docs/vendor_reference/common_oper/
  task-print-component-writer.md
  inst-blk-map-resource-owner.md
  common-oper-task-graph-exeblock-audit.md
  auxiliary-artifacts-source-evidence.md
  source-fingerprint-index.md
```

Ownership:

```text
vendor source behavior, not OpenFabric design
line-level evidence and source fingerprints
```

Recommended migrations:

```text
common_oper_task_graph_exeblock_audit -> common-oper-task-graph-exeblock-audit.md
task_print_component_writer_audit -> task-print-component-writer.md
inst_blk_map_resource_owner_audit -> inst-blk-map-resource-owner.md
data_inst_replace_and_enable_files_audit -> auxiliary-artifacts-source-evidence.md
```

## Why Not `docs/binary`?

A standalone `docs/binary` sounds attractive, but it would immediately compete
with three already valid questions:

```text
Runtime asks: what bytes are loaded and consumed?
Compiler asks: what plans produce those bytes?
Vendor reference asks: which original code proves those bytes?
```

Putting all of that under `docs/binary` would recreate the exact mud we are
trying to escape: implementation strategy, runtime ABI, and vendor archaeology
all in one bucket.

If we want a friendly top-level binary index later, prefer:

```text
docs/binary.md
```

as a pure navigation page that links to the three owner subtrees, not a new
content-owning directory.

## Reduction Order

### Phase 1: stabilize docs entry points

```text
1. Expand docs/compiler/binary_packaging/README.md.
2. Add docs/runtime/data/auxiliary-artifacts.md.
3. Add docs/vendor_reference/common_oper/source-fingerprint-index.md.
```

### Phase 2: migrate stable facts

```text
1. Move struct layout facts into runtime/data pages.
2. Move source evidence into vendor_reference/common_oper pages.
3. Move compiler guard/owner maps into compiler/binary_packaging pages.
```

### Phase 3: keep active gaps in docs research notes

```text
1. Keep remaining homework tracker in `docs/compiler/binary_packaging/research_notes/binary`.
2. Keep raw diff analyses in docs/compiler/binary_packaging/research_notes/binary.
3. Only graduate a row after evidence is source-backed or runtime-proven.
```

## Recommended Immediate Action

Do this next:

```text
1. Create docs/runtime/data/auxiliary-artifacts.md from the sidecar note.
2. Expand docs/compiler/binary_packaging/README.md with the B-line owner map.
3. Add docs/vendor_reference/common_oper/source-fingerprint-index.md.
```

Do **not** move all notes at once.  The current notes still contain active gaps,
raw observations, and historical pain.  Docs should receive distilled facts; the
notes should remain the lab notebook.
