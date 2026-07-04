# B-line Progress-first Technical Debt Checkpoint

Date: 2026-06-22

This checkpoint records the deliberate technical debt accepted to prioritize the
first three-operator upload bundle: `gemm_no_relu`, `gemm_relu`, and `log10max`.

## Accepted Debt

- The first upload bundle is progress-first. It is meant to unblock partner
  upload/runtime validation and is not a semantic proof of the three operators.
- `gemm_no_relu` and `gemm_relu` currently reuse the A-line GEMM fusion payload
  as the binary seed. This is a tactical delivery bridge and must not become the
  long-term semantic source for B-line.
- `log10max` currently uses the existing structural validation payload. It keeps
  the log/reduce/max intent visible, but the runtime path is not yet a completed
  B-line-native binary lowering.
- The package uses the repository partner-validation harness. The default
  `run.sh` remains the conservative smoke entrypoint; the three-operator upload
  run is exposed through a dedicated launcher script.
- Numerical correctness and full runtime proof are deferred. The immediate goal
  is to produce a packaged upload candidate that exercises the binary delivery
  path and exposes the next concrete runtime failures.

## Follow-up Closure Items

- Replace A-line GEMM seed reuse with B-line-native component writers.
- Split `gemm_no_relu` from fused GEMM evidence so the no-ReLU claim is not a
  packaging alias.
- Complete B-line-native `gemm_relu` ReLU binding without silently dropping the
  post-op.
- Finish `log10max` scalar visibility/allreduce lowering and choose the final
  V1 collective strategy.
- Promote the three-operator launcher to the default `run.sh` only after the
  partner runtime path is proven stable enough for daily upload use.
