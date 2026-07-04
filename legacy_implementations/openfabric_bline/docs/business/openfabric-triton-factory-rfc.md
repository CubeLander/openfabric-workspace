# RFC: OpenFabric Triton Factory

Date: 2026-06-23

## Status

Draft for business and architecture review.

Recommended decision:

```text
Accept as a lab/business route.
Do not merge into the DFU3500 production compiler spine yet.
```

## Summary

This RFC proposes an OpenFabric-to-Triton route:

```text
OpenFabric Tensor / Tile Intent
  -> TileReuseGraph
  -> MemoryScopePlan
  -> TritonBlockProgram
  -> Triton kernel family
  -> correctness / benchmark / autotune report
```

The thesis is precise:

```text
OpenFabric should become a locality-aware planning layer above Triton.
```

It should not become a thin Triton syntax generator. The value is not printing
`tl.load` and `tl.dot`; the value is deriving tile shape, launch order, reuse grouping,
memory policy, reduction strategy, and autotune candidates from tensor-level dataflow
intent.

Product phrasing:

```text
OpenFabric automatically derives cache-aware Triton kernel families from
tensor-level tile and dataflow intent.
```

## Known Facts

Triton already exposes the right execution substrate:

- Its matmul tutorial describes block-level matrix multiplication, pointer arithmetic,
  program reordering for L2 cache hit rate, and autotuning in one flow.
- The tutorial states that each iteration of the outer output-block loop is performed
  by a dedicated Triton program instance.
- `tl.program_id(axis)` exposes the program instance id inside the launch grid.
- `triton.Config` carries meta-parameters and compiler options such as `num_warps`
  and `num_stages`.
- `tl.load` / `tl.store` expose pointer masks and cache-related modifiers/policies.
- `make_tensor_descriptor` gives a lower-level descriptor path that can map to TMA
  behavior on supporting hardware.
- `tl.atomic_add` and multi-kernel staging can implement split-K or other cross-program
  reduction strategies.
- `triton.autotune` can benchmark candidate configs keyed by problem dimensions.

These facts mean OpenFabric can sit above Triton as a planner:

```text
decide tile space / order / locality / reuse / sync
then lower those decisions into Triton physical knobs
```

## Current State

The current business note has a working sample:

```text
ProcessorTileProgram
  -> TritonBlockProgram
  -> TritonTemplateExpansion
  -> kernel.py / wrapper.py / tests / benchmark
```

That sample proves the syntax bridge for:

```text
gemm_tile -> bias_add -> relu -> store
```

But it is still too close to code generation. It shows how to emit a Triton kernel
after tile choices are known. It does not yet define the higher-value planner that
chooses those tile/locality/synchronization decisions.

## Problem

If OpenFabric only generates Triton code from fixed templates, it competes with
handwritten Triton snippets and normal autotune scripts. That is a weak business
position.

The stronger position is:

```text
OpenFabric derives a family of semantically equivalent Triton kernels
with different locality and communication plans,
then validates and autotunes them.
```

To do that, the current route needs two new planning abstractions:

```text
TileReuseGraph
MemoryScopePlan
```

Without them, `TritonBlockProgram` becomes a bag of codegen fields, and the key
decision logic is hidden in templates.

## Goals

- Make OpenFabric a cache/locality/schedule planner above Triton.
- Keep OpenFabric's own IR independent from Triton syntax.
- Derive Triton kernel families from tile/dataflow intent.
- Generate explainable plans, not just benchmark winners.
- Support correctness tests, benchmark reports, fallback paths, and autotune caches.
- Keep this route isolated from the DFU3500 production compiler until it earns its
  own product decision.

## Non-goals

- Do not replace Triton.
- Do not build a generic GPU compiler.
- Do not compete with cuBLAS for fully generic GEMM.
- Do not claim exact GPU cache control. Cache modifiers and launch order are planning
  mechanisms and hints, not absolute cache-line commands.
- Do not mix locality planning with correctness synchronization.
- Do not add Triton-specific state to `gpdpu_compiler/core` DFU3500 B-line.

## Proposed Design

### Pipeline

```text
OpenFabric Tensor Program
  -> OpChainNormalization
  -> TileSpace
  -> TileReuseGraph
  -> Candidate MemoryScopePlans
  -> ResourceModel / PlanPruning
  -> TritonBlockProgram
  -> TritonTemplateExpansion
  -> Autotune / Benchmark / Correctness
  -> KernelPack
```

### TileReuseGraph

`TileReuseGraph` is the main source of planner intelligence.

For:

```text
C[m,n] = sum_k A[m,k] * B[k,n]
```

The reuse graph records:

```text
A[m,k]    -> C[m,n0], C[m,n1], C[m,n2], ...
B[k,n]    -> C[m0,n], C[m1,n], C[m2,n], ...
bias[n]   -> C[m0,n], C[m1,n], C[m2,n], ...
C_acc[m,n] lives across K-loop chunks inside one output tile
```

The planner asks:

```text
Should tiles sharing A be close in launch time?
Should tiles sharing B be close in launch time?
Is bias reuse worth shaping launch order?
Should K be split?
Should partial reductions use atomics or a second kernel?
```

Example shape:

```python
class TileReuseGraph:
    op_id: str
    tile_axes: tuple[str, ...]
    tensors: tuple[str, ...]
    producer_to_consumers: Mapping[str, tuple[str, ...]]
    reuse_axes: Mapping[str, tuple[str, ...]]
    estimated_reuse_distance: Mapping[str, str]
```

### MemoryScopePlan

`MemoryScopePlan` is not Triton IR. It is OpenFabric's target-independent locality
and communication intent.

Example:

```python
memory_scope_plan = {
    "op": "gemm_bias_relu",
    "tile_domain": {
        "m_tiles": "ceil_div(M, BLOCK_M)",
        "n_tiles": "ceil_div(N, BLOCK_N)",
        "k_tiles": "ceil_div(K, BLOCK_K)",
    },
    "reuse_groups": [
        {
            "tensor": "B",
            "shared_by": ["m_block"],
            "group_axis": "M",
            "group_size": 4,
            "preferred_scope": "L2",
            "reuse_distance": "short",
        },
        {
            "tensor": "A",
            "shared_by": ["n_block"],
            "preferred_scope": "L2",
            "reuse_distance": "medium",
        },
        {
            "tensor": "C_acc",
            "owned_by": ["m_block", "n_block"],
            "preferred_scope": "register",
            "lifetime": "whole_k_loop",
        },
    ],
    "launch_topology": {
        "kind": "grouped_m",
        "group_size": 4,
    },
    "reduction": {
        "kind": "none",
    },
    "epilogue_fusion": ["bias_add", "relu"],
}
```

### TritonBlockProgram

`TritonBlockProgram` is the first Triton-shaped object. It is close enough to emit
code, but still structured enough to validate.

Example:

```python
triton_block_program = {
    "program_axes": ["m_block", "n_block"],
    "pid_mapping": {
        "kind": "grouped_m",
        "GROUP_M": 4,
        "reuse_target": "B",
        "expected_scope": "L2",
    },
    "block_shape": {
        "BLOCK_M": 64,
        "BLOCK_N": 64,
        "BLOCK_K": 32,
    },
    "loads": [
        {
            "tensor": "A",
            "lowering": "pointer_matrix",
            "cache_modifier": None,
            "eviction_policy": "evict_first",
        },
        {
            "tensor": "B",
            "lowering": "pointer_matrix",
            "cache_modifier": ".cg",
            "eviction_policy": "evict_last",
        },
    ],
    "loop": {
        "axis": "K",
        "step": "BLOCK_K",
        "body": "acc = dot(load(A), load(B), acc)",
    },
    "epilogue": ["bias_add", "relu", "cast_fp16"],
    "store": {
        "tensor": "C",
        "mask": "boundary_mn",
        "cache_modifier": None,
    },
    "pipeline": {
        "num_warps": 4,
        "num_stages": 4,
    },
}
```

### Physical Knobs Lowered To Triton

| OpenFabric decision | Triton realization |
| --- | --- |
| output tile ownership | `tl.program_id` mapping to `pid_m`, `pid_n` |
| tile shape | `BLOCK_M`, `BLOCK_N`, `BLOCK_K` |
| B reuse across M tiles | grouped-M launch ordering |
| A reuse across N tiles | grouped-N launch ordering |
| accumulator lifetime | `tl.zeros(..., dtype=tl.float32)` and K-loop `tl.dot` |
| epilogue fusion | accumulator transforms before store |
| boundary policy | `tl.load` / `tl.store` masks |
| memory policy | cache modifier / eviction policy where useful |
| software pipeline | `num_stages` |
| warp allocation | `num_warps` |
| split-K reduction | atomics or two-kernel reduction |
| descriptor/TMA path | tensor descriptor lowering when architecture profile supports it |

## Candidate Plan Families

For `C = relu(A @ B + bias)`, the planner should generate several families:

### Row-major output-stationary

```text
one program computes one C tile
K-loop accumulates in registers
no cross-program reduction
```

This is the correctness baseline.

### Grouped-M output-stationary

```text
time-neighbor programs share B[:, n:n+BLOCK_N]
expected benefit: better L2 reuse for B tiles
```

This is the first serious commercial target because it can beat a naive template
without introducing synchronization complexity.

### Grouped-N output-stationary

```text
time-neighbor programs share A[m:m+BLOCK_M, :]
expected benefit: better L2 reuse for A tiles
```

This is useful when shape/layout makes A reuse more valuable than B reuse.

### Split-K

```text
multiple programs compute partial sums for the same C tile
```

Reduction choices:

```text
atomic_add
two_pass_reduce
```

This is not just cache planning. It is communication and synchronization planning.

### Persistent

```text
launch a bounded number of workers
device-side assignment of multiple C tiles per worker
```

This should be deferred until the normal block path is stable.

### Descriptor / TMA path

```text
use tensor descriptors for block load/store where hardware and Triton support it
```

This should be gated by architecture profile.

## Locality vs Synchronization

This RFC treats GPU memory hierarchy as an implicit communication substrate:

```text
registers       -> program-local accumulator communication
shared memory   -> CTA/program-internal explicit cooperation
L1              -> per-SM short-distance locality
L2              -> cross-SM implicit reuse medium
HBM             -> global data source/sink
atomics         -> cross-program correctness synchronization
kernel launch   -> global synchronization boundary
```

OpenFabric must distinguish:

```text
locality route:
  affects performance
  examples: grouped launch order, cache modifiers, eviction policy

synchronization route:
  affects correctness
  examples: atomics, two-pass reductions, kernel boundaries
```

Invariant:

```text
Cache locality must never be used as a correctness synchronization mechanism.
```

## Planner Passes

### Pass 1: Op-chain normalization

Normalize:

```text
gemm + bias + relu
```

into:

```text
matmul core
epilogue fusion
accumulator dtype
output dtype
layout assumptions
```

### Pass 2: Tile domain construction

Define:

```text
C tile axes: M, N
reduction tile axis: K
```

### Pass 3: Reuse graph analysis

Compute tile-level consumers for A, B, bias, and accumulator.

### Pass 4: Candidate locality plans

Generate:

```text
row_major
grouped_m
grouped_n
split_k_atomic
split_k_two_pass
persistent
descriptor_path
```

### Pass 5: Resource model and pruning

Estimate:

```text
register pressure
L2 working-set size
HBM bytes
FLOPs per byte
occupancy proxy
mask overhead
atomic overhead
number of programs
```

First version can be approximate. It only needs to reject obviously bad candidates
and produce a better autotune set.

### Pass 6: TritonBlockProgram emission

Emit a structured block program with launch mapping, block shape, loads, loop,
epilogue, store, and pipeline fields.

### Pass 7: Triton template expansion

Generate:

```text
kernel.py
wrapper.py
autotune_configs.py
test_correctness.py
benchmark.py
report.md
```

### Pass 8: Autotune, benchmark, cache

Run correctness and benchmark. Cache the winning config by:

```text
op family
shape
dtype
layout
target GPU
Triton version
driver/runtime versions
```

## Invariants

- `TileReuseGraph` owns reuse reasoning.
- `MemoryScopePlan` owns locality and communication intent.
- `TritonBlockProgram` owns Triton-shaped executable block decisions.
- Triton templates must not infer new tensor semantics.
- Benchmark winners must be tied to shape/dtype/layout/target profile.
- Generated kernels must include fallback and correctness tests.
- Cache hints are advisory and must be described as such.
- Synchronization must be explicit: atomics, multi-kernel boundary, or unsupported.
- This route must stay outside the DFU3500 B-line production path until explicitly
  accepted as a product track.

## Minimum PoC

Scope:

```text
op: gemm + bias + relu
input dtype: fp16
accumulator dtype: fp32
output dtype: fp16
layout: contiguous A/B, bias[N]
target: CUDA first
```

Generate a small kernel family:

```text
tile shapes:
  64x64x32
  64x128x32
  128x64x32
  128x128x32

launch mappings:
  row_major
  grouped_m_4
  grouped_m_8

pipeline:
  num_warps in {4, 8}
  num_stages in {3, 4}
```

Do not let the Cartesian product explode. The first planner should produce roughly
8-16 candidates.

Output:

```text
generated/
  kernel_row_major.py
  kernel_grouped_m_4.py
  kernel_grouped_m_8.py
  wrapper.py
  test_correctness.py
  benchmark.py
  report.md
```

Success criteria:

```text
correctness passes against torch reference
benchmark runs reproducibly
report explains why each candidate was generated
at least one grouped plan beats row-major for a shape where reuse matters
```

Stretch criterion:

```text
one generated variant beats torch eager or torch.compile baseline by 20%+ for a
fixed commercially relevant shape
```

## Product Shape

Commercial deliverable:

```text
OpenFabric Triton Kernel Pack
```

Input:

```text
PyTorch reference function
shape/dtype/layout profile
target GPU profile
accuracy tolerance
latency target
```

Output:

```text
kernel.py
wrapper.py
test_correctness.py
benchmark.py
autotune cache
performance report
fallback path
known assumptions
```

First sellable families:

```text
gemm + bias + activation for fixed odd shapes
RMSNorm / LayerNorm variants
reduction chains such as reduce-max + logsumexp
quant/dequant + elementwise fusion
MoE routing helpers
sampling / top-k helpers
vision post-processing kernels
```

Avoid first:

```text
generic GEMM
FlashAttention head-on replacement
arbitrary dynamic shape
full graph compiler
```

## Alternatives Considered

### Direct OpenFabric-to-Triton syntax printing

Rejected. It hides locality decisions in templates and produces a weak product.

### Triton-only hand-written kernel service

Rejected as OpenFabric strategy. It may make money, but it does not build a durable
compiler asset.

### Full GPU backend compiler

Deferred. Too broad and likely to collide with Triton, Inductor, MLIR GPU, and vendor
libraries.

### Put Triton as a backend inside current DFU compiler

Rejected for now. It would violate the current DFU-first project target and pollute
the B-line architecture with a premature multi-backend branch.

## Risks and Mitigations

| Risk | Mitigation |
| --- | --- |
| Planner becomes vague marketing language | Require generated `TileReuseGraph`, `MemoryScopePlan`, and candidate rejection reasons in every report. |
| Autotune alone provides the actual value | Planner must reduce search space and explain candidate generation. |
| Triton API/hardware behavior changes | Version generated reports by Triton, CUDA/ROCm, driver, and GPU profile. |
| Cache hints do not behave as expected | Treat hints as advisory and require benchmark validation. |
| Generated kernels are correct only for narrow layouts | Make shape/dtype/layout assumptions explicit in wrappers and reports. |
| This distracts from DFU3500 | Keep work under `docs/business` / `experiments` until separately accepted. |

## Validation Plan

For each generated kernel pack:

```text
unit correctness vs torch reference
randomized shape boundary tests within supported profile
max_abs_error / max_rel_error report
benchmark against torch eager and torch.compile where available
benchmark against row-major generated baseline
artifact hash and environment capture
fallback path check
```

Report must include:

```text
source op-chain
TileReuseGraph summary
MemoryScopePlan
candidate plans
rejected plans and reasons
generated configs
benchmark table
winning config
known limitations
```

## Expected Effect

If successful, this route gives OpenFabric a nearer-term monetization path:

```text
paid custom Triton kernel packs
performance consulting backed by generated reports
repeatable kernel-family generation for fixed production workloads
```

It also preserves the larger compiler story:

```text
OpenFabric plans information movement over a memory/fabric hierarchy,
then projects that plan onto a concrete execution substrate.
```

For DFU3500 that substrate is a DFU physical program and vendor binary rows.
For GPGPU that substrate is Triton block programs and generated kernels.

## Open Questions

- Should the first PoC live under `experiments/triton_factory/` or a separate repo?
- Which GPU is the first benchmark target?
- Which customer-shaped kernel family is most commercially useful: GEMM epilogue,
  RMSNorm, reduction/logsumexp, or MoE routing?
- Should `MemoryScopePlan` be target-independent from day one, or initially Triton-biased?
- How much source code generation should be template-based versus AST-based?

## Recommended Decision

Accept the route as:

```text
OpenFabric Triton Factory:
From tile intent to locality-aware GPU kernels.
```

Approve the next phase:

```text
Phase 0: keep documentation and architecture route under docs/business.
Phase 1: create an isolated experimental generator for gemm + bias + relu.
Phase 2: add TileReuseGraph and MemoryScopePlan dumps.
Phase 3: generate 8-16 Triton candidates and benchmark them.
Phase 4: decide whether to package as a sellable kernel-pack service.
```

Do not approve:

```text
Triton integration into current DFU3500 production compiler.
Generic GPU backend scope.
Claims that cache locality is correctness synchronization.
```

## Sources

- Triton matrix multiplication tutorial: https://triton-lang.org/main/getting-started/tutorials/03-matrix-multiplication.html
- `tl.program_id`: https://triton-lang.org/main/python-api/generated/triton.language.program_id.html
- `triton.Config`: https://triton-lang.org/main/python-api/generated/triton.Config.html
- `tl.load`: https://triton-lang.org/main/python-api/generated/triton.language.load.html
- `make_tensor_descriptor`: https://triton-lang.org/main/python-api/generated/triton.language.make_tensor_descriptor.html
- `tl.atomic_add`: https://triton-lang.org/main/python-api/generated/triton.language.atomic_add.html
- Triton persistent matmul tutorial: https://triton-lang.org/main/getting-started/tutorials/09-persistent-matmul.html
- `triton.autotune`: https://triton-lang.org/main/python-api/generated/triton.autotune.html
