# RFC: B-line Compiler Organization

Status: proposed
Date: 2026-06-23
Scope: `compiler/gpdpu_compiler/core/stream_compiler` and the future B-line
lowering spine

## Summary

The current B-line code has the right architectural instinct: flat IR records,
explicit provenance, report-first lowering, and fail-closed target evidence.
The problem is that most of those layers live in one flat package, so semantic
IR, target evidence, binary layout, debug writers, delivery reports, and
operator-specific probes all share the same namespace.

Recommended decision:

```text
Keep the B-line programming model.
Reorganize it around layer-owned packages and one-way lowering passes.
Keep `stream_compiler` as a compatibility facade during migration.
Do not rewrite the lowering semantics as part of the package split.
```

## Current State

The current demo spine is:

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

Downstream report and delivery work then projects `BinaryLayoutPlan` into debug
rows, vendor-like groups, component candidates, serializer readiness, byte
writer artifacts, exact-template evidence, and operator payload status.

The main structural problems are:

1. `stream_compiler` is a flat namespace for every layer.
2. `__init__.py` exports almost everything, which makes cross-layer imports easy.
3. Large files such as `inst_writers.py`, `log10max_collective_strategy.py`,
   `micc_component_writers.py`, `vendor_components.py`, and `program_tile.py`
   are high-conflict collaboration zones.
4. Compatibility and evidence paths sit next to semantic lowering paths, so it
   is easy to accidentally promote a validation projection into authority.
5. The current demo entry builds `StreamPlan/Fiber` directly; the production
   integration point should eventually be explicit lowering from chip/logical
   and tile op-chain IR, not an ad hoc demo builder.

## DDIA-Inspired Principles

Treat every IR layer as a durable data product, not as a mutable object graph.
The compiler should resemble a small data pipeline:

```text
authoritative facts at layer N
  -> deterministic pass
  -> authoritative facts at layer N+1
  -> derived indexes / reports / materialized views
```

Practical rules:

- Each IR is a flat fact table: stable ids, scalar fields, explicit references,
  and no hidden backpointers.
- Derived views are allowed, but they are named as views and are never semantic
  authority.
- Every lowering pass is a pure-ish batch job: consume one layer, produce the
  next layer plus diagnostics, no mutation of upstream records.
- Every row that crosses a layer carries provenance back to the source row.
- Each IR has `schema_version`, `ir`, validation status, diagnostics, and a
  deterministic `to_plan()` representation.
- Compatibility with A-line/vendor artifacts is an evidence branch, not a
  replacement source of truth.
- Runnability is a gate claim, not a hopeful status string. Unknown evidence
  remains visible as blockers.

## Target Package Shape

Introduce a B-line package structure that mirrors the dataflow. This can be
done inside the existing `stream_compiler` directory first, then optionally
renamed to `core/bline` once imports are stable.

```text
compiler/gpdpu_compiler/core/bline/
  README.md
  pipeline.py

  ir/
    stream.py
    fiber.py
    executable.py
    schedule.py
    template.py
    binary_layout.py
    diagnostics.py
    provenance.py

  passes/
    stream_to_fiber.py
    fiber_to_executable.py
    executable_to_schedule.py
    schedule_to_template.py
    template_to_binary_layout.py

  ops/
    matmul.py
    relu.py
    log10max.py
    profiles.py

  target/
    dfu3500/
      config.py
      role_binding.py
      template_records.py
      semantics.py
      template_evidence.py
      binary_layout_policy.py
      resources.py

  artifacts/
    debug_rows.py
    vendor_groups.py
    vendor_components.py
    field_offsets.py
    serializer_readiness.py
    writers/
      instance_conf.py
      micc_components.py
      inst_rows.py

  compat/
    aline/
      block_projection.py
      gemm_evidence.py
      template_span_reports.py

  delivery/
    operator_payload_assembly.py
    runtime_ready_summary.py

  demo/
    gemm_pipeline.py
```

Ownership:

- `ir/` owns data classes only. It must not import `target/`, `artifacts/`,
  `delivery/`, or compatibility modules.
- `passes/` owns layer-to-layer transforms. A pass imports source IR, target IR,
  and policy/profile descriptors only.
- `ops/` owns declarative operator profiles: shape/access/fiber/template intent
  descriptors. It must not construct target rows or vendor artifacts.
- `target/dfu3500/` owns DFU3500 facts, template evidence, role semantics, and
  target resource policy.
- `artifacts/` owns debug/vendor-shaped projections and byte writers. It cannot
  feed authority back into semantic IR.
- `compat/aline/` owns comparison and evidence reports against legacy/A-line
  artifacts.
- `delivery/` owns packaging and gate aggregation only.

## Recommended Spine

The B-line spine should be explicitly aligned with the existing production
compiler spine:

```text
ChipProgram / DTensor program
  -> AppPlan / task partition / runtime package assignment
  -> ProcessorLogicalProgram
  -> ProcessorTileProgram with first-class tile op chains
  -> BLineStreamProgram
  -> BLineFiberProgram
  -> BLineExecutableProgram
  -> BLineScheduleProgram
  -> Dfu3500TemplatePlan
  -> Dfu3500BinaryLayoutPlan
  -> vendor-shaped artifacts / serializers / delivery gates
```

The current `StreamPlan / Fiber` demo can remain, but it should be treated as a
fixture builder until there is a real lowering pass from `ProcessorTileProgram`
or a tile op-chain view.

## Invariants

1. Frontend and op calls only build chip-level tensor semantics.
2. B-line semantic IR never contains vendor row bytes, serializer structs, ABI
   offsets, or A-line row identities as authority.
3. GEMM remains an atomic fiber/tile compute action. K-loop row expansion is
   target/template lowering content, not fiber semantics.
4. ReLU, bias, gelu, log10max steps, and stores are first-class tile/fiber ops,
   not hidden GEMM flags.
5. A compatibility projection may prove equivalence, but new lowering must not
   consume compatibility-only fields as semantic authority.
6. Every downstream row carries provenance to the source `FiberOp` or tile
   action.
7. Every package boundary has a validator or summary check before downstream
   code consumes it.

## Migration Plan

### Phase 0: Freeze the Contract

- Add this RFC and a `stream_compiler/README.md` boundary map.
- Stop expanding `stream_compiler.__init__` as a convenience export surface.
- Add a small import-boundary check that prevents `ir/` and semantic passes from
  importing artifact, writer, delivery, or compatibility modules.

No behavior change.

### Phase 1: Create Layer Packages In Place

Create subpackages under `stream_compiler` first:

```text
stream_compiler/ir/
stream_compiler/passes/
stream_compiler/target/dfu3500/
stream_compiler/artifacts/
stream_compiler/compat/aline/
stream_compiler/delivery/
stream_compiler/demo/
```

Move the smallest, least risky files first:

```text
stream.py              -> ir/stream.py
executable.py          -> ir/executable.py + passes/fiber_to_executable.py
schedule.py            -> ir/schedule.py + passes/executable_to_schedule.py
template_records.py    -> target/dfu3500/template_records.py
dfu3500_semantics.py   -> target/dfu3500/semantics.py
debug_emit.py          -> artifacts/debug_rows.py
vendor_groups.py       -> artifacts/vendor_groups.py
operator_payload_assembly.py -> delivery/operator_payload_assembly.py
```

Leave compatibility re-export modules at old paths until all tools are updated.

### Phase 2: Split Large Files By Authority

Split large files only after Phase 1 proves imports are stable:

- `inst_writers.py`
  - `artifacts/writers/inst_rows.py`
  - `compat/aline/template_span_reports.py`
  - `target/dfu3500/template_evidence.py`
- `vendor_components.py`
  - component schema rows
  - component grouping/projection
  - readiness summaries
- `micc_component_writers.py`
  - runtime address derivation
  - task/exeBlock/subtask writers
  - log10max PE00 proof helpers
- `log10max_collective_strategy.py`
  - semantic collective strategy
  - DFU3500 runtime proof
  - delivery blocker summary

Each split should preserve existing public APIs through wrapper imports.

### Phase 3: Add The Real B-line Entry

Add a named pipeline entry, separate from demo tools:

```text
lower_processor_tile_to_bline_stream(tile_program, chip_config)
lower_bline_stream_to_fibers(stream_program, op_profiles)
lower_bline_to_dfu3500_binary_layout(...)
```

The demo pipeline remains for snapshots, but production integration should call
the named passes. `ChipEnv.generate()` should not grow B-line state mutation;
it should call a pipeline object and dump each product.

### Phase 4: Retire The Flat Facade

Once focused checks and delivery tools import the new packages, shrink
`stream_compiler.__init__` to stable high-level entry points only:

```text
build_demo_pipeline
lower_bline_pipeline
summarize_bline_pipeline
```

## Validation Plan

Required checks after each phase:

```text
python -m py_compile compiler/gpdpu_compiler/core/stream_compiler/**/*.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_no_relu_safe_subset.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_relu_fiber_chain.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_relu_binding.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_collective.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_templates.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_fiber_chain.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_bline_runtime_ready_preintegration.py
```

Add two structural checks:

1. Import boundary check.
2. Snapshot schema check for every core IR `to_plan()` result.

## Risks

The main risk is spending delivery time on a rename. Mitigation: phase the work
as compatibility wrappers first; do not change behavior during package moves.

The second risk is creating an over-generic backend. Mitigation: keep the only
target under `target/dfu3500/` for now and explicitly defer CUDA/CANN/multi-chip
architecture.

The third risk is hiding tactical delivery bridges behind clean package names.
Mitigation: every bridge lives under `compat/`, `artifacts/`, or `delivery/`,
not under semantic `ir/` or generic `passes/`.

## Recommended Decision

Adopt the package split and import-boundary rules now, but migrate in small
compatibility-preserving patches. The architecture should keep the current
B-line thesis intact: flat fact records, deterministic pass outputs, explicit
provenance, fail-closed target evidence, and no cross-layer mutation.
