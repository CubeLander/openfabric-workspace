# RFC: B-line Vendor Assembler Input Bundle

Status: proposed
Date: 2026-06-24
Scope: `compiler/gpdpu_compiler/core/stream_compiler`,
`simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/build_app`,
and B-line delivery packaging

## Summary

B-line should stop treating final CBUF/MICC byte emission as the primary path to
runtime readiness. The customer toolchain already has a source-backed assembler
and packer: `build_app` plus `common_oper`. The smallest useful change is to add
a first-class `VendorAssemblerInputBundle` projection after B-line template
planning. This bundle should generate the inputs consumed by the vendor
assembler: task/subtask config, per-PE CSV templates, per-subtask
`generateGraph(...)` plugins, and optional runnable SimICT case material.

Recommended decision:

```text
Keep StreamPlan/Fiber/Schedule/TemplateOpPlan as B-line semantic authority.
Add VendorAssemblerInputBundle as a backend projection.
Use build_app/common_oper to produce customer-facing CBUF/MICC binaries.
Demote local Python byte writers to evidence, diff, and fallback tooling.
```

Implementation note 2026-06-24:

`compiler/tools/export_stream_compiler_case_package.py` now emits a first
report-only package skeleton for the B-line demo profiles. For
`gemm_no_relu`, it writes `app0.conf`, per-task/per-subtask `template/*.csv`,
`build_so/test_graph_extend.cpp`, `manifest.json`, `summary.json`, and
`provenance.json`. The bundle is intentionally marked
`assembler_ready=false` while `GEMM_TILE_TEMPLATE_SPAN` remains a symbolic
TemplateOp span instead of real vendor CSV microprogram rows.

## Current State

The current B-line demo/report spine is:

```text
StreamPlan / Fiber
  -> FiberBlockProjection
  -> FiberExecutableProgram
  -> SymbolicRoleBindingProgram
  -> SymbolicTemplateRecordProgram
  -> Dfu3500RoleSemanticReport
  -> ValidatedFiberExecutionSchedule
  -> TemplateOpPlan
  -> BinaryLayoutPlan
```

For `gemm_no_relu`, the current snapshot/export path already exposes useful
planning facts:

```text
stream_count = 64
schedule steps = 128
template ops = 128
BinaryLayoutPlan instruction rows = 128
task rows = 4
vendor-like groups = 8
subtask group kinds:
  subtask1_gemm_tile_template_span
  subtask3_store_tile
```

These facts are enough to describe task/subtask grouping, PE-local work buckets,
roles, phases, and provenance. They are not enough to produce vendor assembler
input directly, because `BinaryLayoutPlan` rows are symbolic template rows, not
CSV microprogram rows.

The customer assembler path is source-backed:

```text
testcase/application/build_app/main.cpp
  argv app*.conf
  -> Task_Group::readFromTaskFile(...)
  -> Task_Group::tasksConstruct()
  -> Task_Group::map(INST_BLK_MAP)
  -> exe_block_gen(...)
  -> Print_Task_Group writes simulator/RTL/CBUF/MICC outputs
```

`Task_Group::tasksConstruct()` does:

```text
for each task/subtask:
  SubTask::read_inst_block_collect()
    -> read code_dir/template/<i>.csv
    -> Inst_Block::process()
  SubTask::subtask_graph_extend()
    -> dlopen code_dir/build_so/libsubtask.so
    -> dlsym generateGraph(...)
  count_root_block_amount()
```

The assembler input is therefore not final `inst_t` bytes. It is a case package
with config, CSV templates, and graph-extension code.

The detailed extraction of the source rules is maintained in:

```text
docs/vendor_reference/common_oper/vendor-assembler-composition-rules.md
```

## Problem

B-line has been losing time at the wrong boundary. Reconstructing final
CBUF/MICC bytes in Python forces us to duplicate the hard parts of
`common_oper`:

- CSV pseudo-op expansion;
- LD/CAL/FLOW/ST stage partitioning;
- PE-local operand resource assignment;
- COPY/COPYT destination patching from graph edges;
- exeBlock construction;
- task/subtask/instance component packing;
- simulator vs RTL component variants.

This is high-risk because the vendor assembler is not merely a byte packer. It
mutates and completes instruction/resource fields after CSV parsing and graph
construction. Local byte similarity is not a reliable runtime-ready claim.

The design failure is ownership confusion:

```text
TemplateOpPlan knows semantic target intent.
BinaryLayoutPlan knows symbolic grouping/numbering.
common_oper knows assembler/resource/package completion.
```

B-line should connect these layers through an explicit assembler-input bundle,
not by teaching Python serializers to be a second vendor assembler.

## Goals / Non-goals

Goals:

- Define the exact vendor assembler input package B-line should emit.
- Show how task/subtask planning and scheduling facts can be derived from
  existing B-line progress.
- Preserve B-line layering: DTensor, stream, fiber, schedule, template, and
  assembler-input projection remain separate.
- Keep every generated CSV row and graph node traceable to `TemplateOp`,
  `FiberOp`, and stream/tile provenance.
- Make the first phase report-only and deterministic.

Non-goals:

- Do not make `ChipEnv` call `build_app`.
- Do not make op specs write CSV, graph plugins, task rows, or binary rows.
- Do not claim runtime readiness before the generated bundle passes vendor
  assembler and SimICT/runtime validation.
- Do not reintroduce fused GEMM flags or fiber-internal K-loop expansion.
- Do not retire binary decoders/diff tools; they remain essential evidence
  tools.

## Proposed Design

Add a B-line projection:

```text
TemplateOpPlan
  + ValidatedFiberExecutionSchedule
  + StreamPlan / Fiber provenance
  + DFU3500 target profile
  -> VendorAssemblerInputBundle
```

The bundle has two modes:

```text
assembler_minimal:
  files required for build_app/common_oper to produce CBUF/MICC

simict_case:
  assembler_minimal plus input data, runtime control, and result-check material
```

### Bundle Shape

```text
VendorAssemblerInputBundle
  schema_version
  bundle_id
  profile_id
  mode
  source_artifacts
  case_config_plan
  template_csv_program
  subtask_graph_plan
  graph_plugin_build_plan
  runtime_control_plan?
  diagnostics
```

Filesystem projection:

```text
<bundle_root>/
  app0.conf
  app1.conf
  ...
  task0/
    subtask1/
      template/0.csv
      template/1.csv
      ...
      build_so/test_graph_extend.cpp
      build_so/Makefile
      build_so/run.sh
    subtask3/
      template/0.csv
      ...
      build_so/test_graph_extend.cpp
  task1/
  ...
  manifest.json
  provenance.json
```

For `simict_case`:

```text
<bundle_root>/
  csv_generate/conf.h
  csv_generate/conf_PEmap.h
  spm_data/*
  riscv/testarm.c
  run_assembler.sh
  run_simict.sh
```

The assembler-minimal bundle should not require B-line to regenerate all legacy
case authoring files. `build_app` consumes `app*.conf`, `task*/subtask*/template`
CSV files, and `task*/subtask*/build_so/libsubtask.so`. The richer SimICT case
mode can later generate or copy the surrounding runtime files.

### CaseConfigPlan

`CaseConfigPlan` owns app/task/subtask declarations.

Example emitted `app0.conf` shape:

```text
task(task_name:task0;reuse_input_reg:;reuse_output_reg:;Execute Times : 1;subtask_num:2)
{
subtask(subtask_name:subtask1;reuse_input_reg:;reuse_output_reg:;Instance Times : 1;code_path:template/;csv_amount:16;graph height:4;graph width:4)
subtask(subtask_name:subtask3;reuse_input_reg:;reuse_output_reg:;Instance Times : 1;code_path:template/;csv_amount:16;graph height:4;graph width:4)
}
```

Sources:

- task ids: current `stream_id` convention such as `t0_pe00`, or a future
  explicit task partition plan;
- subtask slots: current `_subtask_slot_for_op()` policy in `BinaryLayoutPlan`,
  promoted into a named `AssemblerSubtaskPolicy`;
- active PE count / graph dimensions: DFU3500 physical topology and stream ids;
- `csv_amount`: number of CSV blocks a subtask exposes to `generateGraph`;
- `Instance Times`: loop-folding/subtask repetition policy when proven, else
  `1` in phase 1.

The config must be front-loaded. It must not infer subtask counts after CSV
emission, because vendor `Task_Group::readFromTaskFile` treats missing/extra
structure as fatal.

Directory-facing subtask names should stay vendor-shaped:

```text
subtask1
subtask2
subtask3
...
```

Semantic labels such as `gemm_tile_template_span` or `store_tile` belong in
`manifest.json`, `provenance.json`, and the in-memory `AssemblerSubtaskPolicy`,
not in the required directory names. This keeps generated bundles compatible
with the vendor `taskX/subtaskY` convention while preserving semantic
readability in sidecars.

### TemplateCsvProgram

`TemplateCsvProgram` owns per-task/per-subtask/per-PE CSV rows.

CSV header:

```text
inst_name,inst_tag_name,src_reg_idx0,src_reg_idx1,dst_reg_idx,dst_pe_idx,imm,iteration,extra_fields[0],extra_fields[1],extra_fields[2]
```

Sources:

- `TemplateOpPlan` supplies role, phase, template kind, instruction intent, and
  proof/evidence status;
- template evidence supplies concrete CSV fragments or CSV-fragment generators
  for roles such as `compute_core:gemm_tile` and `tile_store`;
- `StreamPlan` / `FiberOp` provenance supplies task/PE/tile coordinates and
  dependency references;
- memory plans supply `imm`, `iteration` / base-address slot, and extra fields
  for load/store pseudo ops;
- symbolic operand names are generated from DTensor/tile/fiber provenance and
  must remain symbolic. B-line must not pre-allocate final hardware operand
  indices.

Important boundary:

```text
TemplateOpPlan row:
  compute_core:gemm_tile, template_kind=dfu3500_gemm_tile_template_span

TemplateCsvProgram rows:
  one or more CSV rows/fragments that common_oper can parse and later map
```

`TemplateOpPlan` remains atomic for GEMM. If a GEMM tile expands to many CSV
rows, that expansion belongs to template/assembler projection and every row
must carry provenance back to the single source `FiberOp`.

### SubtaskGraphPlan

`SubtaskGraphPlan` owns graph nodes and relationships consumed by
`generateGraph(...)`.

Phase 1 node model:

```text
GraphNode
  node_name = node<i>
  node_idx = i
  task_name
  subtask_name
  blk_map_tag
  subtask_map_tag
  pos_idx_df
  csv_block_index
  parent_node_ids = []
  child_node_ids = []
```

Phase 1 `generateGraph(...)` can mirror the known simple vendor pattern:

```cpp
m_nodes.resize(graph_height * graph_width);
for (i = 0; i < graph_height; i++) {
  for (j = 0; j < graph_width; j++) {
    int index = i * graph_width + j;
    m_nodes[index].m_node_name = "node" + to_string(index);
    m_nodes[index].m_node_idx = index;
    m_nodes[index].m_task_name = task_name;
    m_nodes[index].m_subTask_name = subTask_name;
    m_nodes[index].m_blkMapTag = task_name + subTask_name + to_string(index);
    m_nodes[index].m_subTaskMapTag = task_name + to_string(index);
    m_nodes[index].m_pos_idx_df = i * graph_width + j;
    m_graph_extend.initNode(m_nodes[index], index, true, inst_block_collect);
  }
}
```

Sources:

- node order and PE position: stream id `t{task}_pe{x}{y}` and DFU3500 mesh
  topology;
- block grouping: `VendorLikeRowGroupPlan` / `VendorComponentPlan` can provide
  task/subtask buckets, but must remain a derived planning view;
- dependencies: `ValidatedFiberExecutionSchedule.dependency_source_ids` and
  `StreamPlan.dependency_edges()`;
- route/COPY ownership: deferred until route edge lowering is source-backed
  enough to generate graph edges and COPY/COPYT rows together.

Phase 1 intentionally does not express complex graph edges. It is enough for
one-node-per-PE subtasks such as the simple GEMM/softmax patterns. Route-heavy
operators must stay report-only until edge ownership is encoded.

### GraphPluginBuildPlan

`GraphPluginBuildPlan` owns generated C++ and build commands for each subtask.

Inputs:

- `SubtaskGraphPlan` records;
- standard include path to `graph_extend.h`, `inst_def.h`,
  `inst_block_gen.h`, and `csv_oper.h`;
- optional generated `conf_PEmap.h` include for compatibility with current
  vendor templates.

Output:

```text
taskX/subtaskY/build_so/test_graph_extend.cpp
taskX/subtaskY/build_so/Makefile
taskX/subtaskY/build_so/run.sh
taskX/subtaskY/build_so/libsubtask.so
```

The plan should record the command but phase 1 does not need to execute it in
the compiler. A separate assembler wrapper can build the shared libraries.

### RuntimeControlPlan

`RuntimeControlPlan` is optional and only required for `simict_case`.

Sources:

- explicit SRAM tensor declarations and load/store regions from `ChipEnv`;
- DFU3500 region/base-address rules;
- operator-specific input/output data generator;
- existing partner-validation bundle conventions.

This plan must not be invented from binary layout. If runtime control facts are
missing, the assembler-minimal bundle can still be emitted, but the SimICT case
bundle must be blocked.

## Deriving From Existing Progress

The current B-line artifacts map into the new bundle as follows:

| Bundle field | Existing source | Current gap |
| --- | --- | --- |
| task id | `stream_id` prefix `tN`, `BinaryLayoutPlan.task_rows` | Needs explicit task partition owner for production |
| PE position | `stream_id` suffix `peXY`, DFU3500 topology | Need shared parser/helper, not ad hoc string parsing |
| subtask slot | `_subtask_slot_for_op()` and vendor-like grouping | Promote to named `AssemblerSubtaskPolicy` |
| subtask active rows | `VendorLikeRowGroupPlan`, `VendorComponentPlan` summaries | Must decide CSV block count vs symbolic row count |
| op order | `ValidatedFiberExecutionSchedule.source_order_index` / ordinal | Need per-subtask CSV row ordering policy |
| role/template kind | `TemplateOpPlan.role`, `template_kind` | Need CSV fragment templates for each proven role |
| instruction intent | `InstructionIntent` opcode/operand/immediate policy | Need CSV-level mnemonic and fields, not final opcodes only |
| dependency edges | `schedule.dependency_source_ids`, `StreamPlan.dependency_edges()` | Need graph edge lowering and COPY ownership rules |
| loop instances | `loop_instance_key`, folding reports | Need proven mapping to `Instance Times` |
| memory addresses | DFU3500 regions and future MemoryAccessPlan | Current B-line lacks complete CSV `imm/iteration` derivation |
| provenance | `TemplateOpProvenance`, `FiberOp` ids | Already strong; preserve in sidecar and CSV comments/manifest |

This means phase 1 can generate a complete report-only bundle plan and a
limited file bundle for proven GEMM/store template evidence. It should not
claim a general runnable compiler until memory/base-slot, graph edge, and CSV
fragment evidence are complete.

## Invariants

1. `StreamPlan`, `Fiber`, schedule, and `TemplateOpPlan` remain semantic
   authority. CSV files are backend projection artifacts.
2. `VendorAssemblerInputBundle` must not contain final `inst_t` bytes as
   authority.
3. CSV operands remain symbolic tags. Final operand indices belong to
   `inst_blk_map.cpp`.
4. CSV pseudo ops such as `HLDT`, `HSTT`, `ILDMT`, `COPYT`, and `LCOPYT` are
   assembler input mnemonics. B-line must not confuse them with final hardware
   row bytes.
5. Every emitted CSV row carries sidecar provenance to `TemplateOp`, `FiberOp`,
   stream id, task, subtask, PE, and source tensor/tile when available.
6. `generateGraph(...)` is generated from `SubtaskGraphPlan`; it must not
   re-derive compiler semantics in C++.
7. Route/COPY graph edges and CSV rows must be generated by the same lowering
   decision, because vendor COPY destination patching is edge-owned.
8. `build_app` invocation is an external packaging step after explicit B-line
   lowering. It is never called during frontend op construction.
9. Runtime readiness is a validation result, not a property of bundle emission.

## Alternatives Considered

### Continue Python CBUF/MICC Byte Writers

Rejected as the primary path. The writers are useful for decoding, diffing,
field audits, and narrow proof reports, but they duplicate too much vendor
assembler behavior.

### Treat BinaryLayoutPlan As The Assembler Input

Rejected. `BinaryLayoutPlan` groups symbolic template intents into row-like
debug records. Vendor `build_app` consumes CSV blocks and graph plugins. The
shape is related but not the same.

### Emit Only CSV And Skip `generateGraph(...)`

Rejected. `build_app` explicitly loads per-subtask `libsubtask.so` and calls
`generateGraph(...)`. The graph plugin is part of the assembler input contract.

### Shell Out To Existing Vendor Case Templates Without A Bundle IR

Deferred as a tactical probe only. Copying and patching a vendor case may help
validate a hypothesis, but without `VendorAssemblerInputBundle` it becomes
another hidden backend.

### Rebuild A Clean Native Assembler In Python

Rejected for now. That is the path that caused the bleeding. It may become a
long-term option only after the vendor input/output contract is fully modeled
and runtime-proven.

## Migration / Implementation Plan

### Phase 0: Documentation And Fixture Audit

- Accept this RFC.
- Add a tiny fixture inventory for `app0.conf`, one `template/0.csv`, and one
  `test_graph_extend.cpp` from GEMM and softmax.
- Record the minimal assembler input file list in the current
  `docs/vendor-assembler-input-protocol.md` and the bundle README.

No behavior change.

### Phase 1: Report-only Bundle Plan

Add dataclasses and summarizer:

```text
vendor_assembler_bundle.py
  VendorAssemblerInputBundle
  CaseConfigPlan
  TemplateCsvProgram
  TemplateCsvBlock
  TemplateCsvRow
  SubtaskGraphPlan
  GraphPluginBuildPlan
  RuntimeControlPlan
  lower_template_ops_to_vendor_assembler_input_bundle(...)
```

The first pass consumes the existing demo pipeline and emits JSON only. It
should prove:

- 4 task declarations for `gemm_no_relu`;
- subtask declarations derived from current grouping;
- one graph node per active PE/subtask block;
- CSV row placeholders for proven roles, blocked where CSV fragment evidence is
  missing;
- provenance coverage for every placeholder or row.

### Phase 2: File Materialization Without Build

Add an export tool:

```text
compiler/tools/export_vendor_assembler_input_bundle.py
```

It writes `app*.conf`, `template/*.csv`, generated graph C++, build scripts,
`manifest.json`, and `provenance.json` under an output directory.

The tool should fail closed unless:

- all declared subtasks have at least one CSV block;
- `csv_amount` equals emitted CSV file count;
- graph nodes reference existing CSV block indices;
- every CSV row has provenance;
- no unresolved template role is emitted as concrete CSV.

### Phase 3: Assembler Wrapper

Add a wrapper that copies or points to the vendor `build_app/common_oper`
environment and runs:

```text
build task*/subtask*/build_so/libsubtask.so
build_app app0.conf app1.conf ...
archive result/cbuf_file.bin result/micc_file.bin
```

The wrapper is not called by `ChipEnv`. It is a delivery/validation tool.

### Phase 4: Runtime Bundle

Extend from assembler-minimal to `simict_case` by adding:

- input data generation;
- SRAM/SPM runtime layout;
- RISC-V control program generation or templating;
- SimICT invocation;
- result checking and archive manifest.

### Phase 5: Broaden Operators

Add CSV fragment evidence and graph-edge lowering for:

- GEMM + explicit ReLU tile op-chain;
- elementwise add/relu;
- log10max local stages;
- route/COPY and ring/collective paths.

Each operator must enter through explicit tile/fiber/template roles, not
through op-time vendor state mutation.

## Validation Plan

Static validation:

- JSON round-trip for `VendorAssemblerInputBundle`.
- Config grammar check: task/subtask counts, braces, `csv_amount`, graph dims.
- CSV schema check: fixed header, field count, mnemonic support, symbolic
  operands only.
- Graph plan check: node indices dense, PE positions valid, CSV block index
  exists, edge endpoints valid.
- Provenance check: every config/subtask/CSV/graph record links to source IR.
- Layering check: bundle pass does not import byte writers or mutate upstream
  IR.

Assembler validation:

- Build `libsubtask.so` for every subtask.
- Run vendor `build_app` on generated `app*.conf`.
- Archive generated `simulator_bin`, `rtl_bin`, `result/cbuf_file.bin`, and
  `result/micc_file.bin`.
- Decode and diff output using existing binary tools.

Runtime validation:

- Run SimICT only for `simict_case` bundles with complete `RuntimeControlPlan`.
- Compare output data and runtime logs.
- Promote `runtime_ready` only from successful assembler + runtime verdicts.

## Risks and Mitigations

Risk: generated CSV fragments are still too close to legacy template copying.

Mitigation: make template fragment provenance explicit and keep GEMM atomic at
fiber level. CSV expansion is a backend projection, not fiber semantics.

Risk: `stream_id` parsing becomes another hidden task planner.

Mitigation: use it only as a phase-1 compatibility source. Production should
consume an explicit task/placement plan.

Risk: graph plugin C++ becomes a second semantic compiler.

Mitigation: generate boring C++ from `SubtaskGraphPlan`; forbid hand-authored
logic except in checked fixtures.

Risk: route/COPY behavior is under-modeled.

Mitigation: block route-heavy bundles until graph edge ownership and CSV COPY
rows are generated together.

Risk: local vendor source differs from remote arch-13 source.

Mitigation: treat local `common_oper` as algorithm evidence and keep remote
assembler/runtime validation in the promotion gate.

## Expected Effect

This design changes B-line's customer-facing path from:

```text
B-line tries to write final binary bytes
  -> local byte diffs
  -> remote runtime surprises
```

to:

```text
B-line emits source-backed assembler input
  -> customer build_app/common_oper completes package
  -> B-line decoders/diffs validate produced bytes
  -> SimICT/runtime gates decide readiness
```

The compiler remains layered. The immediate output becomes easier to review:
`app.conf`, CSV rows, graph nodes, and provenance are all text/JSON artifacts.

## Open Questions

1. What exact vendor-style subtask numbering should `AssemblerSubtaskPolicy`
   choose for GEMM/store/ReLU/log10max phases, and which numbers must preserve
   legacy case parity?
2. How much of `csv_generate/conf.h` and `conf_PEmap.h` is required for
   assembler-minimal mode if generated `generateGraph(...)` no longer includes
   the legacy headers?
3. Where should concrete GEMM CSV fragment evidence live:
   `core/dfu3500/template_evidence.py`, a new `assembler_templates/`, or a
   fixture directory under `docs/vendor_reference`?
4. What is the first runtime target: GEMM no-ReLU parity, GEMM+ReLU explicit
   tile op-chain, or a softmax/log10max-derived staged operator?
5. Should `VendorAssemblerInputBundle` consume `BinaryLayoutPlan`, or should it
   consume `TemplateOpPlan` plus a separate subtask policy directly? This RFC
   recommends the latter, with `BinaryLayoutPlan` used only as a comparison
   view.

## Recommended Decision

Accept `VendorAssemblerInputBundle` as the next B-line delivery boundary.

Implement phase 1 as report-only JSON from the existing `gemm_no_relu` demo
pipeline. Then add file materialization for assembler-minimal bundles. Keep
Python binary writers in the evidence lane, and require vendor assembler output
plus SimICT/runtime validation before any generated package is labeled
`runtime_ready`.
