# Plan B / Stream Compiler Source Survey

Date: 2026-06-22

Scope:

`compiler/gpdpu_compiler/core/stream_compiler`

## Executive Summary

`stream_compiler` is the current B-line experimental stream compiler branch. It
is intentionally report-first and fail-closed. The package docstring states that
it is not wired into the main DFU3500 lowering path yet; repository references
confirm that current use is mostly through `compiler/tools/check_stream_compiler_*.py`
and export helpers.

The current demo lowering entry is:

`compiler/tools/stream_compiler_demo_pipeline.py`

The key demo pipeline is:

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

After `BinaryLayoutPlan`, there is a second report-only line that projects rows
toward vendor-shaped artifacts, serializer readiness, debug byte writers, and
package-shell metadata. Those files are important for delivery evidence, but
they are not the core semantic lowering spine.

## Current Status

This branch is best understood as a Plan B / B-line investigation track:

- It is not the production DFU3500 lowering backend.
- It does not emit runnable DFU binaries as its main contract.
- Most layers produce reviewable reports, snapshots, debug rows, readiness
  reports, or fail-closed byte artifacts.
- It deliberately avoids treating old `TileMicroBlock` compatibility rows,
  ASM, ABI rows, or vendor serializers as semantic authority.

This matches the project layering rule: keep each intermediate layer observable,
reviewable, and independently validatable instead of mutating lower-level DFU
state during frontend/op construction.

## Bleeding Stop: Target The Vendor Assembler Input Contract

Update 2026-06-24:

B-line has spent too much effort trying to hand-write final CBUF/MICC binary
payloads. That is the wrong place to win first. The customer toolchain already
has an assembler/packer path, and B-line should study and target that path
instead of continuing to reproduce every final byte in Python.

The current source-backed understanding is:

```text
case contract / generated configs
  + per-task/per-subtask/per-PE template/*.csv
  + per-subtask build_so/libsubtask.so exposing generateGraph(...)
  -> testcase/application/build_app
  -> common_oper csv/graph/resource/task printer pipeline
  -> result/cbuf_file.bin + result/micc_file.bin
```

Important references:

- `docs/vendor_reference/original_materials_audit.md`
- `docs/vendor_reference/cases/softmax/softmax-current-real-workflow.md`
- `docs/vendor_reference/case_authoring/manual-vs-generated.md`
- `docs/architecture/instruction-encoding/isa-execution-model.md`
- `docs/compiler/binary_packaging/research_notes/binary/2026-06-20_common_oper_task_graph_exeblock_audit.md`
- `docs/vendor_reference/common_oper/openfabric-vs-vendor-compile-flow-report.md`
- `docs/vendor_reference/common_oper/vendor-assembler-composition-rules.md`

In this flow, the assembler/packer input is not final `inst_t` bytes. It is a
case package:

- `csv_generate/conf.h`, `conf_PEmap.h`, and generated `app*.conf` /
  task/subtask config material;
- `taskX/subtaskY/template/<pe>.csv` files, one PE microprogram template per
  active subtask;
- `taskX/subtaskY/build_so/libsubtask.so`, whose `generateGraph(...)` maps CSV
  blocks into graph nodes, PE positions, and dependencies;
- runtime-side case material such as `spm_data/*` and `riscv/testarm.c` when a
  full SimICT bundle is needed.

The customer `common_oper` pipeline then performs work that B-line should not
continue guessing at byte level:

```text
csv_oper.cpp:
  parse CSV, preserve symbolic operand tags, expand pseudo ops

inst_blk_gen.cpp:
  split each CSV block into LD -> CAL -> FLOW -> ST stages

task_create.cpp / graph_extend.cpp:
  load template CSV blocks and call per-subtask generateGraph(...)

inst_blk_map.cpp:
  allocate PE-local operand resources and patch COPY/COPYT destinations

task_print.cpp:
  write simulator/RTL component files and final CBUF/MICC package shape
```

Therefore the new Plan B delivery target should be:

```text
DTensor / ChipProgram
  -> StreamPlan
  -> Fiber / tile op-chain
  -> TemplateOpPlan
  -> VendorAssemblerInputBundle
  -> customer build_app/common_oper assembler
  -> vendor CBUF/MICC package
```

`VendorAssemblerInputBundle` should be a first-class artifact, not an ad hoc
temporary directory. It should contain at least:

- `CaseConfigPlan`: task/subtask counts, graph dimensions, instance counts,
  code paths, active PE set, and SRAM/SPM/base-address contract;
- `TemplateCsvProgram`: per task/subtask/PE CSV rows with source `FiberOp` /
  `TemplateOp` provenance and original symbolic operand tags preserved;
- `SubtaskGraphPlan`: graph nodes, node order, PE positions, parent/child edges,
  root block counts, and COPY edge ownership;
- `GraphPluginBuildPlan`: generated or templated `generateGraph(...)` C++ plus
  the compile command needed to produce `build_so/libsubtask.so`;
- `RuntimeControlPlan`: only when producing a runnable SimICT bundle, covering
  input data, DMA/control program expectations, and package invocation.

The direct Python binary writers should be downgraded to evidence tools:

- decode and diff vendor output;
- prove component offsets and field meanings;
- compare B-line assembler-input output with vendor-generated binaries;
- preserve exact-seed/debug-byte reports for review.

They should not be the primary path to runtime readiness. In particular,
`inst_writers.py`, `component_writers.py`, and `micc_component_writers.py` should
remain fail-closed debug/evidence surfaces unless a later decision explicitly
promotes one narrow writer with source-backed proof and runtime validation.

### Immediate Refactor Direction

1. Add a report-only `VendorAssemblerInputBundle` pass after `TemplateOpPlan`.
   It may initially mirror a known GEMM no-ReLU / softmax-style package shape
   without claiming runtime readiness.
2. Add a CSV emitter that consumes `TemplateOpPlan` / template intent records
   and writes per-PE CSV rows with stable provenance. Do not emit final `inst_t`
   bytes in this pass.
3. Add a generated `generateGraph(...)` bridge for the simple case first:
   one graph node per active PE CSV block, explicit PE position, no hidden
   graph dependencies. Then extend it for COPY/route edges once
   `SubtaskGraphPlan` is source-backed.
4. Add a local or remote assembler invocation wrapper that treats
   `build_app/common_oper` as the package compiler. The wrapper should archive
   the exact input bundle and produced `result/*.bin` for diffing.
5. Keep the current binary serializers as validators against vendor output, not
   as the default producer of customer-facing payloads.

Current implementation checkpoint:

- `compiler/tools/export_stream_compiler_case_package.py` emits the first
  report-only B-line case package skeleton.
- `gemm_no_relu` currently exports 4 tasks, 8 subtasks, 128 template CSV files,
  and 128 provenance rows.
- The package is not assembler-ready yet: 64 GEMM rows are still
  `GEMM_TILE_TEMPLATE_SPAN` placeholders that must be expanded into real vendor
  CSV microprogram rows.

### Guardrails

- Do not call `build_app` from `ChipEnv` or op construction. It belongs after
  explicit stream/fiber/template lowering.
- Do not let op specs write CSV, graph plugins, task rows, or binary rows
  directly. Op specs describe semantics and access profiles; backend passes
  emit assembler input.
- Do not reintroduce fused GEMM fiber flags such as `include_relu` or internal
  GEMM K-loop expansion to satisfy CSV shape. The tile op-chain remains the
  semantic authority; CSV is a backend projection.
- Do not treat vendor CSV operand numbers as final hardware operands. The
  assembler path uses symbolic tags and `inst_blk_map.cpp` performs resource
  assignment and COPY destination patching later.
- Do not set `runtime_ready` from local byte layout similarity. Runtime
  readiness requires successful vendor assembler packaging and SimICT/runtime
  validation, or an explicitly accepted probe exception.

## Macro Principle: DTensor-First Generalization

Plan B should be judged as a **DTensor-first compiler architecture**, not as a
GEMM-only shortcut and not as a premature multi-backend abstraction. The user
language remains chip-level DTensor programming:

```text
declare explicit SRAM tensors
  -> load SRAM tensors into LogicalDTensor values with placements
  -> apply logical compute ops over DTensors
  -> store logical outputs back to explicit SRAM tensors
```

The frontend owns only this semantic surface: tensor shape, dtype, placement,
load/store boundary, logical op identity, and output binding. It must not expose
physical PE mesh details, DFU subtasks, vendor rows, instruction blobs, or hidden
task/resource state to the user.

Plan B is generic because each lower layer answers one narrower question and
keeps the answer inspectable:

```text
ChipProgram / DTensor language:
  what values and logical relationships does the user ask for?

StreamPlan:
  on which streams must each logical value become visible?

StreamTilePlan / Fiber model:
  how is each stream-visible shard partitioned into tile fragments and
  deterministic local compute fibers?

Executable roles / template intents:
  which target-level execution roles are required by those fibers?

Target evidence / binary projection:
  which DFU3500 templates, rows, and vendor components can currently implement
  those roles?
```

This split gives the current design enough generalization capacity for upper
layers to continue speaking DTensor. Adding a new operation should not require a
new frontend language or op-time mutation of DFU state. A new operation should
contribute data-only lowering descriptors:

- semantic contract: shape, dtype, broadcast/reduce rules;
- access profile: fragment spaces and input/output relations;
- stream visibility profile: local, route, broadcast, or collective visibility;
- fiber schedule profile: tile fragments, carried state, reductions, and reuse;
- executable role profile: materialize, route, compute, finalize, store roles;
- template intent profile: target resource families and fallback status.

The stream/tile compiler then consumes those descriptors and constructs its own
IR objects. Operator specs may describe policy, but they must not build stream,
fiber, template, binary, or vendor IR directly.

### Why This Can Generalize

The key observation is that DTensor generality and DFU3500 specificity live at
different layers.

At the top, DTensor captures a broad class of programs:

- tensor values with shape/dtype;
- distributed placements such as shard/replicate/partial-like semantics;
- explicit storage boundaries through SRAM load/store;
- logical compute relationships such as matmul, elementwise, scalar broadcast,
  and reductions.

At the stream layer, those relationships become value-visibility problems. A
logical op is lowered left-to-right into per-stream action suffixes. Different
streams may receive different action suffixes, but the authority remains simple:

```text
streams[]
  actions[]
    depends_on[]
```

This is generic across operators because routes, broadcasts, collectives, local
materialization, and stores are all represented as ordinary stream actions with
ordinary dependencies. A route table, collective table, or dependency graph can
exist as a derived view, but it should not become a second source of truth.

At the tile/fiber layer, the compiler performs a second, processor-local
DTensor-style partition:

```text
stream-visible shard
  -> tile-visible fragments
  -> compute fibers
```

This is where GEMM stops being a simple zip of input/output tiles. The operation
describes a fiber access map:

```text
GEMM fiber(m, n, k)
  consumes A(m, k)
  consumes B(k, n)
  contributes C(m, n)
```

Elementwise ops can describe a simpler map:

```text
elementwise fiber(tile)
  consumes X(tile)
  produces Y(tile)
```

Reductions can describe carried state, identity, ordering, and reassociation
policy. In all cases, the compiler owns fragment materialization, fanout,
dependencies, and loop annotations. The op only provides the access/reduction
contract.

At the target layer, DFU3500 facts stay concentrated in target/profile modules:
template evidence, opcode families, SRAM/SPM regions, vendor capacities, row
layouts, and serializer readiness. This prevents DFU3500-specific constraints
from leaking upward into the DTensor language while still letting Plan B produce
honest fail-closed reports when a role cannot yet be emitted.

### What This Principle Does Not Claim

This principle does not claim that the current code already implements a full
generic compiler. Today, `stream_compiler` is still primarily a GEMM-centered
demo/report line, and `StreamTilePlan` is still a design direction rather than a
complete implemented pass.

The claim is architectural: the current separation is sufficient to grow toward
DTensor-level generality without changing the frontend contract. The missing
work should be added as explicit passes and descriptors, not as hidden frontend
state or per-op mutations of PE/DFU/vendor programs.

Practical rule:

> If a new Plan B feature cannot be explained as a transformation from DTensor
> semantics to stream visibility, then to tile fragments/fibers, then to target
> roles/evidence, it is probably crossing layers.

## Lowering Critical Path

These files form the current core lowering spine.

### `stream.py`

Defines the flat stream-action IR:

- `StreamValue`
- `StreamAction`
- `StreamPlan`

Primary role:

Track stream-local value visibility and action dependencies. Dependencies live
on downstream actions; separate dependency graphs are derived views.

### `fiber.py`

Defines the flat fiber-op model:

- `FragmentRef`
- `FiberDependency`
- `FiberOp`
- `Fiber`

Primary role:

Represent stream-local tile sequencing as a flat op list: prepared fragments,
loop-carried state, repeated region operations, finalization, and store-like
suffixes. This is the core source of truth for later executable-role lowering.

### `fiber_patterns.py`

Defines construction patterns:

- `FiberPatternPlan`
- `FiberPatternStep`
- `FiberRepeatedRegion`
- `TransitionalPatternId`

Primary role:

Describe how fibers are constructed. These records are construction plans, not
proof authority for folding or backend serialization.

### `blocks.py`

Defines fiber-to-block projection:

- `FiberBlock`
- `FiberBlockDependency`
- `FiberBlockProjection`
- `ProjectionValidationReport`
- `project_fiber_to_blocks()`
- `validate_fiber_block_projection()`

Primary role:

Project each `FiberOp` to one `FiberBlock` and prove/report structural
dependency preservation. The module also contains legacy-like / TileMicroBlock
compatibility probes, but its docstring explicitly calls this a validation
branch rather than the new production backend trunk.

Pipeline status:

Used by `stream_compiler_demo_pipeline.py`, so it is on the current demo
critical path. Architecturally, it is a validation checkpoint and adapter.

### `executable.py`

Defines executable-role lowering:

- `ExecutableFiberOp`
- `FiberExecutableProgram`
- `lower_fibers_to_executable_ops()`

Primary role:

Lower flat `FiberOp` records into symbolic executable roles. The source of truth
is `FiberOp`, not `FiberBlock` and not old `TileMicroBlock` rows. This phase
does not bind DFU3500 templates, ASM, ABI rows, packing, or serializers.

### `binding.py`

Defines symbolic role binding:

- `SymbolicRoleBinding`
- `SymbolicRoleBindingProgram`
- `bind_executable_roles_symbolically()`

Primary role:

Consume `ExecutableFiberOp.role` and resolve current symbolic template support
through DFU3500 legacy template evidence and op-spec template intent profiles.
It reports binding status instead of emitting concrete binary content.

### `template_records.py`

Defines symbolic template records:

- `SymbolicTemplateRecord`
- `SymbolicTemplateRecordProgram`
- `lower_symbolic_bindings_to_template_records()`

Primary role:

Turn symbolic role-binding results into inspectable target/profile template
records. Still no DFU3500 instruction emission, ASM, ABI rows, or binary blobs.

### `dfu3500_semantics.py`

Defines DFU3500 role semantic reporting:

- `Dfu3500RoleSemanticRecord`
- `Dfu3500RoleSemanticReport`
- `lower_template_records_to_dfu3500_semantics()`

Primary role:

Attach/report target semantic evidence for each executable role. This is a
target-semantic checkpoint after symbolic template records.

### `schedule.py`

Defines flat execution schedule rows:

- `FiberScheduleStep`
- `RawFiberExecutionSchedule`
- `ValidatedFiberExecutionSchedule`
- `build_fiber_execution_schedule()`
- `verify_fiber_execution_schedule()`

Primary role:

Build and verify a row view over `ExecutableFiberOp`. One executable op maps to
one schedule step. Dependencies remain references to source `FiberOp` ids.

### `template_ops.py`

Defines target-template content rows:

- `Diagnostic`
- `InstructionIntent`
- `TemplateOp`
- `TemplateOpPlan`
- `TemplateOpProvenance`
- `TemplateResourceRequirement`
- `lower_schedule_to_template_ops()`

Primary role:

Lower a validated schedule to report-only target-template content. This is the
first B-line layer that talks about concrete target-template content while still
refusing to become a binary layout or emitter.

### `binary_plan.py`

Defines symbolic binary layout:

- `BinaryInstructionPlan`
- `BinaryZeroInstructionBoundary`
- `BinaryTaskPlan`
- `BinarySubtaskPlan`
- `BinaryInstancePlan`
- `BinaryBlobRegionPlan`
- `BinaryLayoutPlan`
- `lower_template_ops_to_binary_layout()`

Primary role:

Place `TemplateOp` rows into symbolic binary layout rows: task, subtask,
instance, blob region, PC-like row slots, and zero-instruction boundaries.
Concrete instruction intents receive symbolic PC/row slots; unresolved candidate
intents remain visible and unallocated.

## Vendor-Shaped / Packaging Projection Path

These files are downstream of the core lowering spine. They are important for
debuggability, delivery evidence, and eventual vendor integration, but they are
not the main semantic lowering path.

### `debug_emit.py`

Primary API:

- `emit_debug_row_artifact()`

Role:

Serialize `BinaryLayoutPlan` into stable JSON-shaped debug row artifacts. This
is not a vendor binary emitter.

### `vendor_groups.py`

Primary APIs:

- `group_debug_rows_vendor_like()`
- `remap_vendor_like_groups_locally()`

Role:

Group debug rows by vendor-shaped coordinates such as task, subtask slot, and
loop instance, then produce local remap groups.

### `vendor_components.py`

Primary API:

- `build_vendor_component_plan()`

Role:

Project local-remap groups into component-shaped JSON sections:

- `inst_rows`
- `exeblock_rows`
- `task_rows`
- `subtask_rows`
- `instance_rows`
- `zero_boundaries`

This is one of the most important downstream files because it models the bridge
from B-line rows to vendor-like component structure. It still does not write
bytes or claim ABI compatibility.

### `field_offsets.py`

Primary API:

- `build_field_offset_preflight_plan()`

Role:

Report which candidate component fields already have known vendor byte offsets
and which still need C/C++ layout evidence. Unknown offsets remain visible
instead of being guessed.

### `serializer_readiness.py`

Primary API:

- `build_serializer_readiness_plan()`

Role:

Combine field-offset preflight and component candidate values. It distinguishes
known offset from packable value: padding, `None`, unresolved block classes, and
symbolic `inst_t` fields remain blockers.

### `component_writers.py`

Primary API:

- `emit_debug_instance_conf_info_component()`

Role:

Debug-only byte writer for selected component structs, currently focused on
`instance_conf_info_t`. It consumes readiness reports and writes only proven
packable struct families.

### `micc_component_writers.py`

Primary APIs include:

- `derive_instance_table_addresses()`
- `build_subtask_instance_semantics_report()`
- `emit_micc_task_conf_info_component()`
- `emit_micc_exeBlock_conf_info_component()`
- `emit_micc_sub_task_conf_info_component()`

Role:

Debug-only MICC/control component byte writers. Unknown or inconsistent fields
produce blocked artifacts with empty payloads.

### `inst_writers.py`

Primary APIs include:

- `build_raw_template_overlay_report()`
- `build_aline_template_span_candidate_report()`
- `build_compressed_template_span_authority_report()`
- `build_exact_template_span_hash_candidate_report()`
- `build_template_evidence_binding_report()`
- `build_exact_template_binding_seed_report()`

Role:

Fail-closed `inst_t` raw-template overlay and template-evidence reports. This
file is large and important for exact-seed / A-line evidence work, but it is not
a semantic lowering pass and does not encode runnable instruction bytes.

### `operator_payload_assembly.py`

Primary APIs:

- `build_operator_payload_assembly_report()`
- `gemm_no_relu_stream_statuses()`
- `gemm_relu_stream_statuses()`
- `log10max_stream_statuses()`

Role:

S3 report-only operator payload assembly shell. It aggregates statuses from
stream artifacts and produces honest package-shell metadata while remaining
fail-closed for upload/runtime readiness.

## Auxiliary, Prototype, and Feature-Specific Files

These files support experiments, proof reports, or specific operator/customer
cases. They should not be confused with the general lowering spine.

### `gemm_demo.py`

Role:

Small GEMM stream-action demo. It builds the current demo `StreamPlan` and
`Fiber` objects consumed by `stream_compiler_demo_pipeline.py`.

Status:

Critical for the current demo pipeline, but not a production compiler entry.

### `folding.py`

Role:

Stream-scoped loop folding analysis. It reports whether each stream's flat
fiber schedule contains a repeated subtask loop body that could later project to
vendor `instances_amount`.

Status:

Report-only. It does not fold component rows, mutate subtasks, delete expanded
K bodies, or emit bytes.

### `folded_components.py`

Role:

Report-only folded component experiment. It compares expanded component rows to
a projected folded representation. It does not mutate `vendor_components`
output.

### `relu_binding.py`

Role:

Explicit ReLU subtask binding report for GEMM+ReLU `TemplateOpPlan`. It makes
the current tile-op contract visible without pretending unresolved ReLU
templates are runnable.

### `log10max_collective_strategy.py`

Role:

Strategy report for log10max collective lowering. It reads chip/logical/tile
plans and names defensible customer-facing strategies without mutating lower IR.

### `log10max_ring_plan.py`

Role:

Delivery-scoped log10max ring-first plan. It expresses the representative
row/column reduce+broadcast path with existing stream route actions and emits
derived validation metadata; it is not a generic collective IR or scheduling
authority.

### `log10max_template_pack.py`

Role:

S6 report-only local template pack for log10max. It captures local
elementwise/reduce template binding shape and scalar visibility status.

### `aline_gemm_evidence.py`

Role:

Report-only scanner for local A-line GEMM/vendor artifacts. It reports which
reference artifacts exist for later exact-seed work.

### `__init__.py`

Role:

Package export surface. It also documents the key architectural fact: this
package is experimental and not wired into the main DFU3500 lowering path yet.

## Validation And Export Tools

The validation harness lives mostly under `compiler/tools`, not inside
`stream_compiler`.

Important shared tool:

- `compiler/tools/stream_compiler_demo_pipeline.py`

Focused check scripts:

- `check_stream_compiler_projection.py`
- `check_stream_compiler_executable.py`
- `check_stream_compiler_role_binding.py`
- `check_stream_compiler_template_records.py`
- `check_stream_compiler_dfu3500_semantics.py`
- `check_stream_compiler_schedule.py`
- `check_stream_compiler_template_ops.py`
- `check_stream_compiler_binary_plan.py`
- `check_stream_compiler_debug_emit.py`
- `check_stream_compiler_vendor_groups.py`
- `check_stream_compiler_local_remap.py`
- `check_stream_compiler_vendor_components.py`
- `check_stream_compiler_field_offsets.py`
- `check_stream_compiler_serializer_readiness.py`
- `check_stream_compiler_component_writers.py`
- `check_stream_compiler_micc_writers.py`
- `check_stream_compiler_inst_writer.py`
- `check_stream_compiler_folding.py`
- `check_stream_compiler_folded_components.py`
- `check_stream_compiler_relu_binding.py`
- `check_stream_compiler_log10max_collective.py`
- `check_stream_compiler_log10max_ring_plan.py`
- `check_stream_compiler_log10max_templates.py`
- `check_stream_compiler_operator_payload_assembly.py`
- `check_stream_compiler_aline_gemm_evidence.py`
- `check_stream_compiler_no_relu_safe_subset.py`
- `check_stream_compiler_snapshot_export.py`
- `check_stream_compiler_task_resource_replay.py`

Export helpers:

- `compiler/tools/export_stream_compiler_snapshot.py`
- `compiler/tools/export_stream_compiler_debug_rows.py`

## Recommended Reading Order

For lowering architecture:

1. `compiler/tools/stream_compiler_demo_pipeline.py`
2. `stream.py`
3. `fiber.py`
4. `blocks.py`
5. `executable.py`
6. `binding.py`
7. `template_records.py`
8. `dfu3500_semantics.py`
9. `schedule.py`
10. `template_ops.py`
11. `binary_plan.py`

For vendor-shaped/debug artifact path:

1. `debug_emit.py`
2. `vendor_groups.py`
3. `vendor_components.py`
4. `field_offsets.py`
5. `serializer_readiness.py`
6. `component_writers.py`
7. `micc_component_writers.py`
8. `inst_writers.py`
9. `operator_payload_assembly.py`

For feature-specific reports:

1. `relu_binding.py`
2. `log10max_collective_strategy.py`
3. `log10max_ring_plan.py`
4. `log10max_ring_fiber_projection.py`
5. `log10max_globalmax_consumer_binding.py`
6. `log10max_ring_update_template.py`
7. `log10max_template_pack.py`
8. `aline_gemm_evidence.py`
9. `folding.py`
10. `folded_components.py`

## Classification Table

| File | Category | Notes |
| --- | --- | --- |
| `stream.py` | Core lowering IR | Flat stream-action IR |
| `fiber.py` | Core lowering IR | Flat fiber-op model |
| `fiber_patterns.py` | Construction helper | Pattern records, not proof authority |
| `blocks.py` | Core demo path / validation | Fiber-to-block projection and validation |
| `executable.py` | Core lowering pass | FiberOp to symbolic executable roles |
| `binding.py` | Core lowering pass | Symbolic executable-role binding |
| `template_records.py` | Core lowering pass | Binding to inspectable template records |
| `dfu3500_semantics.py` | Core lowering pass | DFU3500 semantic evidence report |
| `schedule.py` | Core lowering pass | Execution schedule build/verify |
| `template_ops.py` | Core lowering pass | Target-template content plan |
| `binary_plan.py` | Core lowering pass | Symbolic binary layout plan |
| `debug_emit.py` | Downstream artifact | Stable debug row artifact |
| `vendor_groups.py` | Downstream artifact | Vendor-like grouping/remap |
| `vendor_components.py` | Downstream artifact | Component-shaped JSON plan |
| `field_offsets.py` | Serializer preflight | Known/unresolved field offset report |
| `serializer_readiness.py` | Serializer preflight | Packability/readiness report |
| `component_writers.py` | Debug byte writer | Narrow component writer |
| `micc_component_writers.py` | Debug byte writer | MICC/control component writers |
| `inst_writers.py` | Evidence / overlay reports | Raw-template and exact-seed reports |
| `operator_payload_assembly.py` | Packaging report | Report-only package shell |
| `gemm_demo.py` | Demo/prototype | Builds demo GEMM stream/fiber inputs |
| `folding.py` | Analysis report | Loop folding proof analysis |
| `folded_components.py` | Experiment | Folded component comparison |
| `relu_binding.py` | Feature report | GEMM+ReLU subtask binding report |
| `log10max_collective_strategy.py` | Feature report | log10max collective strategy |
| `log10max_ring_plan.py` | Feature report | log10max ring-first delivery plan |
| `log10max_ring_fiber_projection.py` | Feature report | Projects ring StreamActions to existing route FiberOps |
| `log10max_globalmax_consumer_binding.py` | Feature report | Binds ring `global_max_ready` tokens to `max_with_floor_tile` consumers |
| `log10max_ring_update_template.py` | Feature report | Receiver-side FMAX/HMAX update template contract, row bytes still fail-closed |
| `log10max_template_pack.py` | Feature report | log10max local template pack |
| `aline_gemm_evidence.py` | Evidence scanner | Local A-line GEMM artifact report |
| `__init__.py` | Package surface | Exports and experimental status note |

## Practical Guidance

When modifying this area:

- Treat `stream/fiber/executable/binding/template_records/dfu3500_semantics/schedule/template_ops/binary_plan`
  as the main semantic lowering spine.
- Keep report-only downstream projections honest: unresolved facts should stay
  visible as diagnostics or blockers.
- Do not make `stream_compiler` mutate production DFU package state implicitly.
- Do not turn legacy compatibility probes into semantic authority.
- If adding support for a real delivery path, prefer adding an explicit pipeline
  boundary and validation/export tool rather than smuggling state through
  frontend or op-time construction.
