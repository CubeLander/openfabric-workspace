# OpenFabric Publication Roadmap

Status: active roadmap for turning the current DFU3500 milestone into a
publishable OpenFabric research story.

Date: 2026-07-03

## Publication Thesis

OpenFabric should be presented as a DTensor and Tile Program abstraction for
NoC-style spatial accelerators:

```text
DTensor placement and storage boundaries
  -> per-PE Tile Programs with named TileValues
  -> LogicalCollective visibility objects
  -> target-specific package / runtime artifacts
```

DFU3500 is the first real target and customer validation path. It is not the
conceptual boundary. The next research step is to show that the same
OpenFabric concepts reduce operator surface area for another tiled NoC target,
with Tenstorrent as the most attractive public candidate.

## Current Milestone

The active OpenFabric submodule is pinned at:

```text
1d7e936 updated log10max snapshot
```

This line carries the first customer-runnable OpenFabric-generated operator
package forward into the renamed fp32 delivery contract and refreshed approved
snapshot:

```text
OpenFabric/build/customer_delivery/log10max-fp32.tar.gz
OpenFabric/openfabric/dfu3500/operators/log10max-fp32/snapshots/approved/default/log10max-fp32.tar.gz
```

The package is generated from `openfabric/dfu3500/operators/log10max-fp32`,
assembled and run through the customer-side DFU3500 flow, and passed the output
checker with:

```text
mismatch_count = 0
```

The original customer-pass milestone was recorded at:

```text
1846dca Document log10max customer milestone
```

This milestone matters for the paper because log10max is a non-GEMM exposure
case. It shows chained local tile work plus global scalar visibility and helps
defend against the critique that OpenFabric is only a GEMM generator.

## Workstream A: DFU3500 Customer Delivery

Goal: keep serving the DFU3500 customer while accumulating strong evidence for
vendor-compatible lowering.

### Near-Term Tasks

- Convert more refactored operators into direct customer delivery packages:
  - `gemm`
  - `gemm_relu`
  - `softmax`
  - standalone pointwise operators such as add, multiply, relu, clamp, affine
- Add one checker per delivered operator:
  - CPU reference output
  - runtime return code
  - numerical status
  - `summary.tsv`
- Standardize package provenance:
  - source commit
  - generated package path
  - package hash
  - tensor layout dump
  - instance/base-slot dump
- Keep customer packages under:

```text
OpenFabric/build/customer_delivery/<operator>.tar.gz
```

### Paper Evidence

This workstream supports:

- vendor compatibility;
- numerical correctness on a real customer runtime;
- reduction of handwritten vendor case surface;
- evidence that OpenFabric can handle more than one operator family.

### Guardrails

- Do not compare CSV text as the primary correctness contract.
- Separate package build success, runtime execution, and numerical correctness.
- Keep target facts tied to vendor source, customer runtime evidence, or
  generated artifact inspection.

## Workstream B: OpenFabric Core Lowering

Goal: move from operator-authored lowering toward plan-dominant lowering
without inventing an oversized IR ahead of evidence.

### Target Shape

The next core object should be a thin `ChipProgramPlan`:

```text
ChipProgramPlan {
  DistributedPlan device;
  RuntimeActionPlan runtime;
  ArtifactManifest artifacts;
  TargetBinding target;
}
```

This object should organize existing evidence rather than replace the current
working path.

### Near-Term Tasks

1. Define an `ArtifactManifest`.
   - Generated inputs.
   - Runtime plan images.
   - Support binaries.
   - Checkers and summaries.

2. Generalize `StageAccess`.
   - Subtask/stage id.
   - Instance scope.
   - `TensorAccessRef`.
   - Tile/window scope.
   - Slot policy.
   - Base-row projection.
   - CSV memory projection.

3. Split physical placement from target base slots.
   - `TensorMemory` still carries compatibility base-slot state.
   - Covered operator lowering now uses access-slot policy, but the storage
     object still needs cleanup.

4. Make layout reports first-class.
   - Tensor byte ranges.
   - Overlap warnings.
   - Planned reuse annotations later.

### Paper Evidence

This workstream supports the core architecture claim:

```text
OpenFabric lowers distributed tensor placement into inspectable target
programs instead of directly writing opaque target binaries.
```

### Guardrails

- Keep this track comparison-backed.
- Do not rewrite working operator packages just to make abstractions prettier.
- Avoid a universal scheduler until stage access and collective facts are
  stable.

## Workstream C: LogicalCollective and NoC Semantics

Goal: make cross-PE visibility a first-class OpenFabric object.

### Target Shape

```text
LogicalCollective {
  kind: broadcast | reduce | allreduce | reduce_scatter
  participants
  source TileValues
  visible result TileValues
  ordering requirements
  target lowering evidence
}
```

The first goal is representation and auditability, not automatic route
optimization.

### Near-Term Microcases

- Row broadcast.
- Column broadcast.
- Scalar reduce-to-one.
- Scalar broadcast-from-one.
- Tree allreduce sketch.
- Ring allreduce sketch.

### log10max Role

log10max should be used as the motivating non-GEMM case:

```text
PE-local clamp/log10/local max
  -> global max visibility
  -> PE-local maximum/affine/store
```

The current customer-passing implementation is acceptable as delivery evidence.
The research track should make the global scalar visibility explicit through a
LogicalCollective plan.

### Paper Evidence

This workstream supports the claim that OpenFabric is about NoC visibility, not
only tiled compute.

### Guardrails

- Do not claim a physical allreduce implementation until the route/lowering
  evidence exists.
- Keep physical route selection target-specific.
- Prefer tile-local execution unless cross-tile or cross-PE visibility truly
  requires a phase split.

## Workstream D: Tenstorrent Portability Scout

Goal: show that OpenFabric abstractions can reduce operator surface area for a
second NoC/tile target.

Tenstorrent is attractive because public documentation and repositories expose:

- TT-Metalium as a low-level programming model.
- TT-NN as a tensor/operator library.
- 32x32 tile layout as a central execution/storage concept.
- `ttsim` as a full-system simulator path without requiring local silicon.

### Candidate Mapping

```text
OpenFabric DeviceMesh
  -> Tensix core grid

OpenFabric TileValue
  -> TT tile-resident tensor value / circular-buffer resident value

OpenFabric StorageBoundary
  -> DRAM/L1 tensor layout and host-device transfers

OpenFabric TileAction
  -> TT-Metalium kernel operation

OpenFabric LogicalCollective
  -> explicit TT data movement / multicast / kernel protocol
```

### Minimal Prototype Ladder

1. Documentation-only target model.
   - Identify TT-Metalium objects corresponding to mesh, tile, storage, kernel,
     circular buffer, and program launch.

2. Single-core tile-local operator.
   - Add or ReLU.
   - Show OpenFabric TileAction can lower to one TT-Metalium kernel shape.

3. Multi-core pointwise map.
   - Partition tiles over a core grid.
   - Validate through TT tooling or simulator.

4. Matmul tile microcase.
   - Map sharded A/B/C tile ownership.
   - Keep the first prototype simple and auditable.

5. Collective microcase.
   - Row broadcast or scalar broadcast.
   - Use it to test the LogicalCollective abstraction on a non-DFU target.

### Paper Evidence

This workstream is not required for the first DFU3500 customer story, but it is
high-value for ASPLOS/CGO positioning:

```text
The OpenFabric abstraction is target-aware but not DFU-owned.
```

### Guardrails

- Do not claim Tenstorrent support until a runnable artifact exists.
- Use public TT-Metalium/TT-NN/ttsim documentation as the source of target
  facts.
- Treat the first Tenstorrent target as a portability scout, not a performance
  claim.

## Publication Plan

### Primary Target: ASPLOS 2027 September Cycle

Best fit:

- hardware/software/PL/OS intersection;
- accelerators and heterogeneous systems;
- practical artifacts and experience-style evidence;
- room for a programming-model plus implementation story.

Expected story:

```text
OpenFabric: DTensor Visibility Lowering for Spatial Accelerators
```

### Backup Target: CGO 2027

Best fit if the paper is framed as:

```text
case-authoring code generation and lowering for NoC/tile accelerators
```

### Riskier Target: HPCA 2027

HPCA is attractive for architecture, but the 2026-07-31 deadline is too soon
for the current state unless the paper becomes a narrower architecture
experience paper.

## Evidence Matrix To Build

| Case | Evidence target | Why it matters |
| --- | --- | --- |
| GEMM | E2E replay/package parity | canonical tile contraction |
| GEMM+ReLU | E2E replay or runtime trace | fusion as tile op-chain |
| Softmax | runtime trace or package evidence | staged row reduction |
| log10max | customer-side numerical pass | non-GEMM global scalar visibility |
| Collective microcases | structural plan then package/sim evidence | explicit NoC semantics |
| Tenstorrent microcase | simulator-backed portability scout | target abstraction is not DFU-only |

## Immediate Next Steps

1. Update the coverage audit to upgrade log10max evidence.
2. Add a Tenstorrent scout note with public target facts and a minimal prototype
   ladder.
3. Draft an `ArtifactManifest` shape for OpenFabric-generated packages.
4. Choose the next DFU3500 customer operator package.
5. Start one LogicalCollective microcase before expanding the operator list too
   far.
