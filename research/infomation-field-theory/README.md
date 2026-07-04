# Information-System Theory Notes

This directory contains the working theory notes for the information-field /
information-system model behind OpenFabric.

Current compressed thesis:

```text
A computing system is a constrained information-state transition system.
```

Recursive thesis:

```text
Computing systems scale because internal state trajectories, rule firings, and
constraints can sometimes be soundly projected into higher-level states, macro
rules, and macro constraints.
```

## Canonical Core

The canonical theory lives in `core/`. If an older note conflicts with these
files, prefer the core version.

Recommended reading order:

1. `core/00_theory_section_draft.md`
2. `core/01_minimal_core_and_falsifiability.md`
3. `core/02_projection_equivalence_refinement.md`
4. `core/03_composition.md`

The core object model is intentionally small:

```text
Information System = (State, Rule, Constraint)
```

Everything else should be derived from those objects or treated as an operator
or relation between information systems:

```text
projection
equivalence
composition
refinement
```

Derived concepts include:

```text
data
program
control
resource availability
scheduler
fabric
capability envelope
compilation
fusion
```

## Case Studies And Attacks

The `cases/` directory is where the theory is forced to touch real systems.

Quick validation path:

1. `cases/dfu_gemm_tile_case.md`
2. `cases/falsification_cases.md`

The DFU GEMM tile case is the current concrete anchor. It tests whether a
single tile update can be expressed using only states, rules, and constraints:

```text
visibility state != tensor existence
program state enables compute
resource availability is a state
sender-side route action != receiver-side visibility endpoint
```

The falsification table is the review checklist. New theory extensions should
say which falsification cases they address and which ones they still fail.

## Development Notes

The `notes/` directory keeps useful development history. These files explain
how the current core emerged, but they are not canonical definitions.

Suggested background reading:

1. `notes/information_transformation_fabric.md`
2. `notes/information_meta_transformation.md`
3. `notes/information_reaction_rules.md`
4. `notes/information_resource_constraints.md`
5. `notes/information_system_core.md`

Use these for motivation, examples, and alternative phrasings. Prefer `core/`
when writing definitions, paper text, or implementation requirements.

## Archive

`archive/discussions.md` is the raw conversation log that seeded the theory.
It is valuable context, but it is not a stable spec.

## Compression Rules

Before adding a new concept, check whether it is:

1. One of `State`, `Rule`, or `Constraint`.
2. A derived concept definable from `State / Rule / Constraint`.
3. An operator or relation between information systems.
4. An empirical parameter or cost model used by a rule or constraint.

If it is none of these, treat it as vocabulary growth until proven otherwise.

## Near-Term Engineering Anchor

The next implementation-oriented step is a read-only extractor from existing
OpenFabric IR into an information-system view:

```text
ProcessorTileProgram or FiberExecutableProgram
  -> states
  -> rules
  -> constraints
  -> projection checks
```

For the first pass, target the DFU GEMM tile case and map:

```text
LogicalRouteEdge      -> visibility/route rule family
TileRouteAction       -> sender-side route rule
TileVisibilityRef     -> receiver-side visibility state
TileComputeAction     -> GEMMUpdate rule instance
TileDependency        -> dependency/proof state
VendorTaskProjection  -> staged program state
```
