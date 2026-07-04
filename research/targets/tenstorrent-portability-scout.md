# Tenstorrent Portability Scout

Status: research scout for a possible second OpenFabric backend target. Mapping
language updated to follow `../../TWO_LEVEL_DTENSOR_NOTES_CN.md`.

Date: 2026-07-02

## Why Tenstorrent

Tenstorrent is a strong second-target candidate for OpenFabric because its
public software stack exposes a tile-oriented NoC accelerator programming
surface:

- TT-Metalium is the low-level programming model for custom kernels.
- TT-NN exposes tensor/operator APIs and tile-aware tensor layouts.
- 32x32 tiles are a central unit in the public documentation.
- `ttsim` provides a public full-system simulator route for Wormhole,
  Blackhole, and Quasar-class devices.

This makes Tenstorrent useful for the OpenFabric paper even before performance
optimization: it can test whether OpenFabric concepts are target-aware rather
than DFU3500-owned.

## Public Evidence Anchors

- TT-Metalium documentation:
  `https://docs.tenstorrent.com/tt-metal/latest/tt-metalium/index.html`
- TT-Metalium getting started:
  `https://docs.tenstorrent.com/tt-metal/latest/tt-metalium/get_started/get_started.html`
- TT-Metalium tiles:
  `https://docs.tenstorrent.com/tt-metal/latest/tt-metalium/tt_metal/advanced_topics/tiles.html`
- TT-NN tensor documentation:
  `https://docs.tenstorrent.com/tt-metal/latest/ttnn/ttnn/tensor.html`
- `ttsim` repository:
  `https://github.com/tenstorrent/ttsim`

Use these sources before making target claims. Do not infer private hardware or
runtime behavior from DFU3500.

## OpenFabric Mapping Hypothesis

| OpenFabric concept | Tenstorrent candidate |
| --- | --- |
| `DeviceMesh` | Tensix core grid |
| `Tensor` | TT-NN tensor with shape, layout, memory layout, and storage |
| `StreamTensorView` | Tensor projection over a core grid, program, kernel group, or sharded TT tensor view |
| `FiberTensorView` | Per-core/per-kernel local shard or tile-space in L1/circular buffers |
| `TypedTileValue` | tile-resident value, likely carried through circular buffers, Dst, SrcA/SrcB, SFPU view, or TT tensor tiles |
| `StorageBoundary` | host tensor, DRAM tensor, L1-resident tile data |
| logical `add/mul/matmul_accumulate/load/store` | TT-Metalium kernel-local compute or data movement step |
| `LogicalCollective` | explicit multicast/data-movement protocol or cooperating kernels |
| `RuntimeActionPlan` | host-side program/device launch and buffer transfers |
| `ArtifactManifest` | TT-Metalium source, compile target, run command, simulator output, checker |

This table is a starting hypothesis, not a completed backend design.

## Minimal Prototype Ladder

### Step 0: Target Model Notes

Create a small target note that records:

- core grid model;
- memory hierarchy and storage names;
- tile size and layout constraints;
- kernel/program launch shape;
- simulator invocation path;
- tensor transfer/checker path.

Deliverable:

```text
research/targets/tenstorrent-target-model.md
```

### Step 1: Single-Core Pointwise Tile

Candidate operators:

- add;
- relu;
- affine scale/add.

OpenFabric requirement:

```text
one FiberTensorView-local logical action over one TypedTileValue
```

Tenstorrent requirement:

```text
one TT-Metalium kernel shape or TT-NN custom-op route
```

Success:

- host input generated;
- target artifact runs on TT tooling or `ttsim`;
- output checker passes.

### Step 2: Multi-Core Pointwise Map

OpenFabric requirement:

```text
StreamTensorView tile placement over a core grid
```

Tenstorrent requirement:

```text
tile partition mapped to multiple cores
```

Success:

- same TileAction replicated over multiple placed tiles;
- generated artifact still has one source of truth for placement;
- output checker passes.

### Step 3: Matmul Tile Microcase

OpenFabric requirement:

```text
FiberTensorView tile contraction with A/B/C StreamTensorView placement
```

Tenstorrent requirement:

```text
small TT tile matmul program or TT-NN matmul-backed experiment
```

Success:

- expose A/B/C tile ownership;
- keep accumulator/output lifetime inspectable;
- validate through simulator or device if available.

### Step 4: Collective Microcase

Candidates:

- row broadcast;
- scalar broadcast;
- scalar reduce-to-one.

OpenFabric requirement:

```text
LogicalCollective with participants and visible TypedTileValues
```

Tenstorrent requirement:

```text
explicit data movement or cooperating kernel protocol
```

Success:

- the collective appears in the OpenFabric plan;
- target lowering explains how the value becomes visible;
- checker confirms the expected visible value.

## What This Can Prove

A successful scout can support this paper claim:

```text
OpenFabric's concepts are target-aware but not target-owned: the same
Tensor/Stream/Fiber projection, TypedTileValue, and LogicalCollective
abstractions can describe both a closed customer DFU3500 flow and a public
Tenstorrent-style tile accelerator.
```

It should not claim:

```text
OpenFabric fully supports Tenstorrent.
OpenFabric matches TT-NN performance.
OpenFabric replaces TT-Metalium or TT-NN.
```

## First Decision Point

Choose the first implementation route:

1. TT-NN-first:
   - faster tensor/checker path;
   - higher-level;
   - may hide too much low-level TileAction detail.

2. TT-Metalium-first:
   - better match for FiberTensorView materialization and kernel lowering;
   - more implementation work;
   - stronger systems paper evidence if runnable.

Suggested starting bias:

```text
Use TT-Metalium for the core scout, with TT-NN only as a reference/checker or
setup convenience.
```

That keeps the result closer to OpenFabric's thesis: lowering explicit tile and
visibility intent into target-visible execution material.
