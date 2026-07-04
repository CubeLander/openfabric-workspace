# Global Tile Dependency Network

The global tile dependency network is a hardware-independent program view that
connects all Tensor Cores through collective materialization, route, and store
semantics.

## Core Principle

```text
Tile Program is the program body.
Dependency Graph is a derived view.
```

Dependency relations can be derived from Tile Program's `inputs / outputs`:

```text
input tile -> TileOp -> output tile
```

The global network is not DFU-specific. It describes:

```text
tile state becomes available / visible
  -> dependent tile op becomes runnable
  -> new tile state is produced / made visible
```

DFU, CUDA, Ascend, or any dataflow runtime are different executors for this
dependency network.

## Tile Values As Virtual Registers

```text
tile produced
tile materialized/resident
tile consumed
tile assembled into a tile view
tile reused by a fused op
tile stored/released
```

Dependency kinds:

```text
LOCAL_TILE_DEP:
  dependency stays inside one Tensor Core / PE.

COLLECTIVE_TILE_DEP:
  dependency is created by generalized collective materialization, route, load,
  store, or visibility semantics.
```

## Cross-PE Dependencies

Single-PE tile dependencies already exist implicitly in TileScope/KTileStep.
The key addition is the global dependency network connecting all Tensor Cores:

```text
existing per-PE TileScope/KTileStep facts
  + route_lowering / generalized collective obligations
  -> global tile dependency network
```

## Backend Lowering

The DFU backend owns the translation from tile dependencies to:

```text
instruction block dependencies
runtime graph nodes
route/control edges
task/subtask serial boundaries
instance/base-table constraints
```

The logical layer does not build explicit graph nodes. The first explicit
graph node appears when the DFU backend groups the assembly records lowered
from one tile op, materialization action, or store action.
