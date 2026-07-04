# Logical Plan Naming and Layering Direction

Status: working principle / long-lived refactor guide

## Context

The current compiler core still carries historical names such as
`ProcessorLogicalProgram`, `ProcessorLogicalAppProgram`, and `ProcessorProgram`.
Those names are increasingly misleading now that task partitioning is modeled as
part of a restricted soft mesh axis.

The upper logical layers should not look like vendor task/subtask/binary program
objects. They describe chip-level dynamics over a logical execution space. Vendor
DFU task rows and binary packaging should re-enter only in downstream projection
and serialization layers.

## Naming Principle

Use `Plan` for IR-like descriptions of a layer's result. Use `Planner` only if a
separate strategy/search object becomes necessary.

Preferred naming direction:

```text
ProcessorLogicalProgram     -> LogicalPlan
ProcessorLogicalAppProgram  -> LogicalApp
ProcessorProgram            -> LogicalStream
```

Rationale:

- `Program` sounds like an executable/vendor image and encourages cross-layer
  state leakage.
- `Plan` better describes a reviewable, dumpable intermediate result.
- `LogicalStream` describes one soft processor's action stream without implying a
  vendor task row or hardware program image.
- Avoid names like `LogicalTask` at this layer because `task` is overloaded by
  DFU vendor task rows.

## Soft Mesh Ownership

The top-level logical plan should own the soft mesh table.

A soft coordinate should be explicit and uniform:

```text
coord = (task_id, x, y)
axis_names = ("task", "x", "y")
```

Derived fields such as `task_id`, `physical_processor`, and
`soft_processor_id` may be exposed for compatibility or dumps, but they should
be derived from the coordinate rather than maintained as independent sources of
truth.

Conceptually:

```text
LogicalPlan
  owns the soft mesh and all LogicalApps

LogicalApp
  consumes the soft mesh
  owns app-local logical streams, values, routes, reduces, dependencies

LogicalStream
  represents one soft processor coordinate's ordered action stream
```

`LogicalApp` should not independently construct the soft mesh. This keeps the
execution space global and app projections local.

## Layering Invariant

Upper logical and tile layers should treat `(task_id, physical_pe)` as a virtual
processor/soft processor. They should not use vendor task rows as semantic
inputs.

Vendor task boundaries should matter again only when projecting to DFU-specific
vendor package/ABI/binary layers.

In other words:

```text
soft processor mesh -> logical/tile lowering
vendor task rows    -> downstream DFU projection
```

Do not let vendor row arithmetic become the semantic source of task partitioning.

## Refactor Strategy

This is a direction, not a single atomic rewrite requirement. During migration,
compatibility views may remain if downstream code still expects old keys.
However, new code should follow these rules:

1. One layer's top-level plan owns that layer's execution-space table.
2. Child app/stream objects consume execution-space entries; they do not rebuild
   topology.
3. Prefer a single coordinate field over parallel independently maintained
   fields.
4. Do not introduce a new wrapper class just to protect old names.
5. If construction has only one valid path, put construction in the plan object;
   introduce a `Planner` only for real strategy search or cost-model selection.
6. Keep compatibility aggregate views clearly labeled as compatibility views and
   remove them once downstream consumers are migrated.

## Immediate Implication for `logical_plan.py`

The current split is inverted:

```text
ProcessorLogicalProgram
  mostly aggregates app-local `programs`

ProcessorLogicalAppProgram
  constructs physical processors × task axis and owns `self.programs`
```

The desired direction is:

```text
LogicalPlan
  constructs and owns the soft mesh table
  owns LogicalApps

LogicalApp
  receives the soft mesh table
  lowers app ops into app-local LogicalStreams
```

This should guide the next refactor pass before adding heavier operator-specific
lowering policy objects.
