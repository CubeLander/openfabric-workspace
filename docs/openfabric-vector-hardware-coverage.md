# OpenFabric Vector / Hardware Coverage Boundary

Date: 2026-06-30

Status: long-term design note. This document records the coverage boundary that
operator refactors should keep using after the initial GEMM/softmax work. It is
the stable constraint extracted from the now-resolved exploratory coverage
matrix draft.

## Why This Exists

OpenFabric can describe more tensor behavior than the current DFU3500/GPDPU
active cases have proven. That is useful for architecture, but dangerous for
lowering: an operation being representable in a plan does not mean it can be
safely emitted as hardware-visible package material.

For current second_wind work, coverage must be comparison-backed. A hardware
behavior is considered stable only when it is supported by active
`simict3500final` cases, vendor workflow evidence, instruction material, or a
checked artifact such as package/API trace/binary comparison.

## V1 Coverage Envelope

OpenFabric v1 should not promise an arbitrary vector ISA. It should promise a
small set of hardware-visible behavior families:

```text
contiguous tile load/store
PE-local vector map
PE-local vector reduce/update
explicit route/copy/collective
matrix/tensor contraction template
explicit materialization boundary
```

Most dense model operators are still coverable because they can be decomposed
into these behavior families:

```text
pointwise / epilogue
row reduce / softmax / norm
GEMM / batched GEMM
attention as GEMM + softmax + GEMM
conv2d as materialized virtual-im2col GEMM
explicit layout movement
```

The lowering rule is:

```text
semantic operator
  -> VectorBehaviorPlan
  -> target capability check
  -> package/kernel action rows
  -> RuntimePlanImage
```

`RuntimePlanImage` remains a runtime executor image. It should not become a
vector program image. Vector opcodes, register/tmp allocation, dtype conversion,
tail behavior, and package instruction rows belong to the package/kernel action
plan before runtime image generation.

## Active Coverage Cases

| Case | Covered behavior | Evidence |
| --- | --- | --- |
| `gemm_refactored` | Matrix/tensor contraction, contiguous tile load/store, explicit COPYT broadcast topology | Vendor replay compares package/support binaries against `gemm_template_fusion` reference outputs; runtime API trace gates compare RuntimePlanImage and common executor behavior. |
| `gemm_relu_refactored` | GEMM-family contraction plus `DistributedPlan` tensor-unary ReLU epilogue map | Vendor-reference replay compares package/support binaries against `gemm_relu_template_fusion` reference outputs; CMake syntax target lowers the plan-declared ReLU through a GEMM-family subtask4 fiber op and checks `HMAX` backend rows. |
| `softmax_refactored` | Row-wise reduce/update plus normalization, contiguous load/store, simple runtime control | RuntimePlanImage and common executor API trace gates cover runtime control; generated config/header compatibility remains plan-derived. |
| `log10max_refactored` | PE-local transcendental map, local reduce, staged naive global max, materialized scratch boundary | RuntimePlanImage/common executor trace gates plus generated input/reference/package artifacts cover the no-vendor-baseline path. |

## Coverage Table

| Vector behavior | Hardware behavior / lowering | Status | Design constraint |
| --- | --- | --- | --- |
| Contiguous vector/tile load | SPM/operand load, `HLDT`/`ILDMT` style rows | stable | MemoryLayoutPlan must provide a contiguous tile view. |
| Contiguous vector/tile store | SPM/operand store, `HSTT` style rows | stable | Store ownership and output/workspace boundary must be explicit. |
| Scalar immediate / constant | `IMM` plus register/tmp reuse | stable for simple constants | Constants are package/action-plan facts, not runtime image facts. |
| PE-local unary/binary map | CAL rows such as `FADD`, `FMUL`, `FDIV`, `FMIN`, `FEXP2`, `FRSQRT`, `H2FP`, `FP2H`, `SHFL` | mostly stable | Needs a target capability registry instead of scattered opcode strings. |
| Transcendental / approximate map | Target opcode or composed implementation for exp/log/rsqrt/div | partial | Record dtype path, precision expectations, and fp32 intermediate needs. |
| PE-local horizontal reduce | Local max/sum/update into tmp/register/workspace | stable for row-wise families | Reduction dimension and neutral value must be explicit in plan. |
| Cross-PE route/broadcast/reduce | `COPYT`/COPY plus graph dependency and app/task boundary | partial but central | Route topology must come from CollectivePlan, not graph hook side facts. |
| Matrix/tensor contraction | `HMMAL`/`HMMA`/`IMMA` template plus tile loop | stable for GEMM family | Accumulator lifetime, tmp pressure, and K-loop visibility must be explicit. |
| Layout transform / transpose | Explicit redistribute, COPY/COPYT, or materialized workspace | materialize-first | No implicit layout repair. Source/plan must request movement. |
| Strided/window/gather read | Materialize contiguous tile, then normal load/compute | materialize-first | Direct gather is unproven in active evidence. |
| Scatter write / indexed update | Multi-stage materialize or unsupported | defer | Do not advertise as generic vector store support. |
| Mask / tail / padding | Valid region plus padded tile and selective output/store policy | partial | Plan must own valid region, padding value, store policy, and reduce neutral value. |
| Dtype convert / mixed precision | `RXINT`/`TRCTT`/`H2FP`/`FP2H` style conversion | partial | Needs dtype capability table and rounding/saturation policy. |
| Arg/value pair reduce | Tuple reduce state, value+index output | not v1 | Requires separate payload/state layout design. |
| Scan/prefix/stateful vector op | Sequential or tree prefix over ordered data | not v1 | Do not infer from ordinary reduce support. |
| Atomic/update semantics | Shared update or concurrent accumulation | not v1 | Prefer owner-compute or explicit reduce. |

## Unstable Areas

### Gather / Scatter / Window Access

Conv2d, stencil, and some fused attention paths want non-contiguous logical
access. The stable v1 route is:

```text
non-contiguous logical access
  -> materialize contiguous tile
  -> ordinary load/store and PE-local compute
```

Do not lower a virtual view as direct hardware gather unless a real active case
or instruction-level evidence proves the behavior.

### Mask / Tail / Padding

Tail handling is not just a shape calculation. It affects:

```text
load out-of-bounds behavior
whether padded values participate in compute
whether stores write only valid output
whether reduce uses the correct neutral value
```

For softmax/norm/reduce, padding that participates in sum/max can change
results. New plans must carry valid-region and padding policy explicitly before
claiming shape generality.

### Transcendental And Approximate Math

Evidence for operations such as exp/log/rsqrt/div is not the same as a full
math-library contract. Each op needs:

```text
target opcode or composition
dtype path
precision/error expectation
overflow/underflow behavior when relevant
```

For example, a softmax lowering may use exp2-style hardware plus scale, but
the max-shift, precision path, and reference comparison policy are part of the
operator contract.

### Cross-PE Collective Behavior

GEMM proves an important COPYT/broadcast pattern, but not every collective.
Generic collective lowering must specify:

```text
source owner
receiver set
dependency graph
task-local versus cross-app boundary
materialized scalar/tile lifetime
```

The graph hook must not be a hidden source of route truth. It should consume a
CollectivePlan or graph projection generated from the operator plan.

### Dtype Conversion / Mixed Precision

Having conversion instructions is not enough. Mixed precision plans must state:

```text
input dtype
compute dtype
accumulator dtype
store dtype
rounding/saturation policy
NaN/Inf/subnormal policy if relied upon
```

GEMM has relatively clear fp16 input plus fp32 accumulator behavior. Softmax,
norm, quantized paths, and fusion need stronger target capability records.

### Argmax / TopK / Scan / Atomic

These are outside v1 unless a new active case forces them:

```text
argmax/topk: value+index tuple state
scan/prefix: ordered dependency, not ordinary reduce
atomic: conflict resolution semantics
scatter: write ownership and conflict handling
```

They should be separate design items, not accidental consequences of reduce or
store support.

## Implication For RISC-V Program Merge

The RISC-V control program should become a homogeneous executor for a
chip-level runtime plan/image, but that image should stay at the runtime-control
layer:

```text
package preload
DMA transfer
kernel start/wait
app finish
```

It should not absorb vector opcode sequencing. The device/package side should
continue to receive package/kernel action rows generated from the same
ChipProgramPlan:

```text
ChipProgramPlan
  -> VectorBehaviorPlan / DeviceExecutionPlan
  -> package/kernel action rows
  -> RuntimeLaunchPlan
  -> RuntimePlanImage
  -> homogeneous RISC-V executor
```

This keeps the RISC-V merge tractable:

- one runtime executor can serve GEMM and softmax;
- operator-specific vector behavior remains in generated package material;
- the same plan still owns memory scope, app boundaries, transfers, and launch
  order;
- future vector coverage expansion happens by adding checked target
  capabilities, not by growing hand-coded RISC-V control branches.

## Practical Rule

When adding or refactoring an operator, ask this before lowering:

```text
Can every vector behavior be decomposed into the v1 coverage envelope?
```

If yes, generate package/runtime artifacts and compare them. If no, either
materialize into a covered behavior or write a new target capability note before
implementation.
