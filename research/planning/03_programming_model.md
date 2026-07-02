# 3. Programming Model

## Job of This Section

Define the paper's central model. This section should make OpenFabric feel like
a programming model rather than a collection of compiler passes.

Stop before implementation details. Section 4 explains the system architecture;
this section defines the objects users and compiler passes reason about.

## Model Overview

OpenFabric programs spatial accelerators as distributed tensor machines:

```text
M = (Mesh, Tensor, Placement, Storage, TileValue, Action, Collective)
```

Possible formalization:

- `Mesh`: processing elements organized into named axes.
- `Tensor`: shape, dtype, logical identity.
- `Placement`: shard, replicate, partial-like placement over mesh axes.
- `Storage`: explicit SRAM/SPM/DDR boundary and memory residency contract.
- `TileValue`: globally named tensor fragment or intermediate value.
- `TileAction`: PE-local action producing or consuming TileValues.
- `LogicalCollective`: shared visibility object connecting multiple PE-local
  TilePrograms.

## User-Facing Concepts

The user or front-end should express:

```text
declare storage tensors
load storage tensors into DTensor values
apply logical tensor operations
express or accept explicit placement/visibility transitions
store outputs to storage tensors
```

Example sketch:

```python
mesh = Mesh("pe", (4, 4), axes=("row", "col"))
A = input("A", shape=(M, K), dtype="fp16", placement=[Shard("row"), Replicate()])
B = input("B", shape=(K, N), dtype="fp16", placement=[Replicate(), Shard("col")])
C = matmul(A, B)
Y = relu(C)
output("Y", Y)
```

Important caveat:

```text
OpenFabric is not a PyTorch eager runtime. Placement movement is not free and
should not be silently hidden when it corresponds to real route/COPY/DMA work.
```

## Tile Program

Each PE/Tensor Core owns a local Tile Program:

```text
PE(i,j):
  a = materialize(tile:A:i,k)
  b = materialize(tile:B:k,j)
  c = gemm_tile_update(a, b)
  y = relu_tile(c)
  store(y)
```

TileValue names are globally unique. A PE-local program is therefore a projection
of a global program, not an isolated log.

## Logical Collective

When a value must become visible to multiple PEs, OpenFabric represents that as
a shared LogicalCollective:

```text
collective_id
  input_tile
  output_visible_tile
  visibility scope
  participants
```

Backend route lowering may implement it with COPY/COPYT, graph edges, DMA, or
other target mechanisms. The logical collective itself is the semantic object.

## Derived Dependency View

The full dependency graph is derived from:

```text
TileAction.inputs
TileAction.outputs
LogicalCollective uses
storage boundaries
```

This mirrors use-def chains: important for analysis and lowering, but not the
primary human-facing program representation.

## Epistemic Boundaries

Do not claim:

- all collectives are automatically optimized;
- all spatial accelerators share the same backend execution model;
- the current implementation proves full generality.

Claim:

```text
DTensor placement plus TileValue visibility is a useful semantic layer for
spatial accelerator operator programming, and it can be lowered to real vendor
operator surfaces.
```
