# Operator Coverage Checklist

Status: current planning checklist for future OpenFabric operators.

The active implementation still grows from runnable cases under
`simict3500final/`. This checklist only records the semantic coverage envelope
we should test before claiming OpenFabric can support a new operator family.

## Required Evidence

For every new operator family, aim for at least one of:

- runnable vendor baseline and replay comparison;
- trusted teammate/customer operator output;
- RuntimePlanImage API trace and common executor trace;
- deterministic input/reference sidecar;
- package/support binary comparison.

The evidence strength can differ by operator, but it must be explicit.

## Currently Covered Envelope

OpenFabric v1 is reliable for operators that can be decomposed into:

```text
contiguous tile/vector movement
PE-local vector map or reduce
explicit route/copy/reduce/materialization boundary
explicit task/subtask/app lifetime
target runtime action stream
```

Active evidence:

- GEMM: tile contraction, A broadcast/copy topology, HMMAL materializer,
  RuntimePlanImage, package/support replay.
- GEMM+ReLU: GEMM plus plan-declared unary epilogue and storage alias.
- Softmax: row summary scratch, normalize/store, RuntimePlanImage, replay.
- Log10max: staged fp32 local program, deterministic input/reference, runtime
  image and package scaffolding; true collective/replay remains open.

## Operator Families

| Family | Status | Notes |
| --- | --- | --- |
| Pointwise / epilogue | Partial | GEMM+ReLU proves fused unary epilogue shape; standalone pointwise still needs evidence. |
| Row-wise reduce / softmax / norm | Partial | Softmax is active. Norm needs scale/bias views and runnable evidence. |
| GEMM / batched GEMM | Active | Current GEMM covers `app_N=2`; `app_M/app_K/batch` expansion remains open. |
| Attention | Design only | Materialized path can be GEMM + softmax + GEMM; fused attention needs stronger lifetime model. |
| Conv2d virtual im2col | Design only | Prefer materialized contiguous tiles first; direct gather is not proven. |
| Global reduction / collective | Partial | log10max has a naive staged fallback; explicit collective plan is deferred. |

## Not Yet Covered

Do not claim generic support for:

- arbitrary gather/scatter;
- per-lane predication;
- scan/prefix operators;
- arg/value pair reductions;
- true atomic update semantics;
- unproven cross-task collective lowering inside one app.

These need target evidence and explicit capability checks before entering the
main coverage envelope.

## RuntimePlanImage Boundary

RuntimePlanImage only records effective executor actions:

```text
package preload
DMA/materialization transfer
kernel wait/start
finish
```

It should not become a vector program image. Vector opcodes, tile fragments,
tail policy, dtype conversion, scratch lifetime, and collective topology belong
to the device/package lowering plan before the runtime action stream.
