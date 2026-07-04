# OpenFabric lowering principles

Status: current guidance distilled from the former `drafts/` notes after
comparison with the active `simict3500final` implementation.

These principles are not a new compiler route. They summarize the constraints
that the current GEMM, softmax, GEMM+ReLU, and log10max refactors have made
visible in source. The active implementation still grows from vendor runnable
cases into hand-written operator contracts, manifests, checkers, and local
generators.

## Authority

The authoritative facts should live in plan/model objects, not in writers.
Compatibility headers, `app*.conf`, instance binaries, graph trace sources, CSV
rows, runtime images, dumps, and replay packages are projections. A projection
may be checked and compared, but it should not silently become the source of
truth for tensor shape, placement, address, task/subtask layout, runtime order,
or package ownership.

Current source evidence:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/common_app_builder/dtensor_plan.h
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/common_app_builder/spm_placement.h
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/common_app_builder/openfabric_runtime_action_plan.h
```

## Typed Address Projection

Address facts must keep their unit and consumer boundary visible. DFU3500 uses
different views of the same SPM storage: vendor base-address units, byte offsets
for DMA/runtime, base slots for CSV operand references, and per-stage instance
base rows. Treating all of these as plain integers recreates the old duplicated
truth problem.

Use explicit projections:

```text
TensorAccessSpmBinding
RuntimeSpmWindowProjection
StageBaseRowProjection
TileMemoryAccess
```

This is the reason the current code separates `TensorMemory`, tensor-access
base slots, runtime SPM windows, and stage base rows. GEMM may still keep some
GEMM-specific projection logic, but new work should make each address consumer
visible instead of hiding it behind generated compatibility text.

Related doc:

```text
docs/address-binding-projections.md
```

## Runtime Order

`RuntimeActionPlan` is the execution-order owner. A RISC-V program should be a
target executor for package preload, transfer, wait, launch, output, and finish
actions. It should not be another operator implementation or another place to
hand-maintain scheduling facts.

Current source evidence:

```text
common_app_builder/openfabric_runtime_action_plan.h
common_app_builder/openfabric_runtime_plan_image.h
common_app_builder/openfabric_runtime_plan_riscv_executor.c
gemm_refactored/operator_sources/gemm/device_program/gemm_config_program.h
softmax_refactored/operator_sources/softmax/device_program/main.cpp
log10max_refactored/operator_sources/log10max/device_program/main.cpp
```

The safety rule is trace equivalence: compare the plan API trace with the
RuntimePlanImage-interpreted trace. Replay does not require RISC-V binary
identity when behavior is owned by the runtime plan image and checked at the
DPU API boundary.

## Compatibility Writers

Compatibility outputs are allowed only as target-facing adapters. They should be
generated from explicit projections, then either compared against vendor
behavior or consumed by vendor tooling.

Useful compatibility outputs include:

```text
conf.h / conf_PEmap.h compatibility data
app*.conf
instance_conf_info_file*.bin
graph_trace/openfabric_graph_trace_data.cpp
runtime_plan.bin / runtime_plan.dump
```

Do not add a new maintained compatibility image just to avoid changing a writer.
If a compatibility artifact must exist during migration, keep it downstream of
the plan and make stale derived artifacts detectable.

## Sites And Fiber Values

A subtask site is a local context: task, subtask, PE, tile, active instruction
block, and operand materialization scope. It is not a universal scheduler.

`PlannedFiberValue`, `ContextTileView`, `FiberEndpoint`, and
`InstructionBlockRef` exist to keep a value tied to its planned tile owner,
local PE context, and vendor block endpoint. Cross-PE behavior must be explicit
at the endpoint/block level; it should not leak through a helper that only
looks like a PE-local arithmetic action.

Current source evidence:

```text
common_app_builder/subtask_site.h
common_app_builder/fiber_values.h
common_app_builder/fiber_actions.h
common_app_builder/vendor_emit_site.h
gemm_refactored/operator_sources/gemm/device_program/main.cpp
gemm_refactored/operator_sources/gemm/device_program/gemm_template_program.h
softmax_refactored/operator_sources/softmax/device_program/softmax_fiber_actions.cpp
log10max_refactored/operator_sources/log10max/device_program/log10max_fiber_actions.cpp
```

## Fiber Action Boundary

Keep fiber actions small enough to be checkable against vendor rows, but not so
small that they become aliases for single CSV instructions. A useful action
usually describes one contiguous local recipe with clear input, output, context,
and materialization behavior.

For now:

- PE-local load/compute/store actions are safe when context checks stay local.
- Partial-reduce templates are safe when the materialized scratch owner is
  explicit.
- GEMM communication is not just an atomic fiber op; COPY/COPYT endpoints and
  instruction blocks carry scheduling facts.
- Accumulators and planned intermediate values need visible lifetime warnings.
  Do not hide storage reuse or cross-stage visibility inside operand names.

Related doc:

```text
docs/partial-reduce-stage-binding.md
```

## Operand Materialization

Operand symbols are target artifacts. The reusable model is the logical operand
handle plus projection path, site context, operand class, and late
materialization step. This lets templates reason about values while still
emitting the vendor symbols needed by existing CSV tooling.

Current source evidence:

```text
common_app_builder/operand_allocator.h
common_app_builder/register_actions.h
```

Practical rules:

- Preserve legacy symbols when binary or CSV comparison depends on them.
- Use generated symbols only behind a stable logical projection path.
- Keep normal and reuse operands distinct.
- Do not introduce a row IR or allocator that changes emitted behavior before a
  comparison gate exists.

## Coverage Envelope

The current reliable envelope is intentionally narrow:

```text
contiguous tile/vector load and store
simple scalar constants
PE-local unary/binary map
PE-local horizontal reduction
partial-reduce materialize/consume
GEMM HMMAL tile compute
GEMM COPYT-style broadcast with explicit graph/block evidence
single-plan runtime package preload/transfer/wait/launch/finish
```

Unstable or deferred areas include arbitrary gather/scatter, per-lane
predication, scan, arg/value reductions, true atomic update semantics, and
performance-real cross-PE collective lowering beyond the current evidence.

Related doc:

```text
docs/openfabric-vector-hardware-coverage.md
```

## Extraction Order

Prefer small, comparison-backed extraction steps:

1. Keep source-of-truth facts in the active operator plan.
2. Project target addresses with typed consumer boundaries.
3. Emit runtime action plans and compare API traces.
4. Emit compatibility artifacts from the same plan.
5. Promote a common helper only after at least two active operators exercise the
   same boundary.
6. Defer automatic scheduling/lowering until the plan, address, runtime, graph,
   and package boundaries are all inspectable.

This keeps OpenFabric moving toward a target-aware NoC lowering platform without
sliding back into a B-line-style final-binary generator.
