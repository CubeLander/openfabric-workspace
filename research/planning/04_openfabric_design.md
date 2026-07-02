# 4. OpenFabric Design

## Job of This Section

Explain the system architecture that realizes the programming model.

The section should answer:

```text
How does OpenFabric transform DTensor semantics into inspectable tile,
visibility, target, and vendor-case artifacts?
```

## Architecture Figure

Recommended figure:

```text
DTensor / ChipProgram
  shapes, dtypes, placements, storage boundaries
        |
        v
ProcessorTileProgram
  PE-local TileActions, globally named TileValues
        |
        v
Visibility / Collective Lowering
  LogicalCollective -> TileCollectiveAction / route intent
        |
        v
Implementation / Physical Plans
  template expansion, PE work partition, task/subtask/instance plan
        |
        v
VendorAssemblerInputBundle
  case config, template CSV, graph plugin, runtime control material
        |
        v
Vendor common_oper/build_app
  package generation and runtime execution
```

## Main Design Principles

### Principle 1: Separate semantics from vendor artifacts

Operator semantics should not be encoded first in CSV rows or binary blobs.
CSV, graph plugins, and runtime control files are projections from tile and
visibility facts.

### Principle 2: Tile Program is the semantic authority

Backend passes may derive graph, schedule, template, or package views, but they
should not rediscover or mutate tile semantics.

### Principle 3: Keep collectives logical before route lowering

COPY/COPYT and graph edges are target choices. Logical visibility must be
represented before selecting those mechanisms.

### Principle 4: Target vendor case authoring first

OpenFabric should automate what vendor engineers currently hand-maintain:

```text
case contract
PE work partition
template CSV program
subtask graph
runtime control intent
data staging material
```

Do not make final binary emission the primary contract until the assembler input
path is stable.

## Relationship To B-line Lessons

B-line provides two important lessons:

1. Binary-first delivery can become an ABI trap.
2. Fiber is useful but should not become the semantic center; tile program and
   physical program boundaries should be explicit.

The design section should show how OpenFabric keeps the useful B-line insights
while adopting the cleaner second-wind direction.

## What To Avoid In This Section

- Avoid naming every internal module unless necessary.
- Avoid framing `gemm_refactored` as the architecture itself.
- Avoid implying that current `stream_compiler` is the production spine.
