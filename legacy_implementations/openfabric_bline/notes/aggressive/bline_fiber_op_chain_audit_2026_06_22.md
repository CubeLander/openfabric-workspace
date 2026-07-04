# B-line Fiber Op-chain Audit

Date: 2026-06-22

Reference:

- `docs/compiler/planB.md`

Question:

Does current B-line mainline code implement the intended model where
`gemm_no_relu` and `gemm_relu` are different fiber/tile-job op-chain
compositions, rather than a GEMM writer that branches on whether ReLU exists?

## Verdict

Partially implemented, but not clean enough.

The core IR direction is correct:

- `Fiber` is a flat stream-local op list.
- `FiberOp` records have explicit inputs, outputs, dependencies, and attrs.
- `TemplateOpPlan` is derived from schedule rows and roles.
- `BinaryLayoutPlan` consumes TemplateOps and does not itself know frontend
  operator semantics.

However, the current demo/main B-line path still has ReLU-specific construction
switches and a dedicated ReLU binding report line.  These do not yet corrupt the
byte writer layer, but they are exactly the kind of coupling that will cause
rework if we build the next lowering phase on top of them.

## What Is Correct

### Plan B architecture

`docs/compiler/planB.md` states the intended lowering spine:

```text
StreamPlan / Fiber
  -> FiberBlockProjection
  -> FiberExecutableProgram
  -> SymbolicRoleBindingProgram
  -> SymbolicTemplateRecordProgram
  -> Dfu3500RoleSemanticReport
  -> ValidatedFiberExecutionSchedule
  -> TemplateOpPlan
  -> BinaryLayoutPlan
```

It also states that the fiber layer owns stream-local fragment actions and that
new operation support should enter through descriptors, not through hidden
frontend/op-time lower state.

### Fiber IR shape

`compiler/gpdpu_compiler/core/stream_compiler/fiber.py` defines:

- `FiberOp`
- `Fiber`
- explicit `inputs`
- explicit `outputs`
- explicit `depends_on`

This is the right unit for atomic template-op composition.

### Template/Binary layers

`compiler/gpdpu_compiler/core/stream_compiler/template_ops.py` lowers schedule
steps into `TemplateOp` rows by role.  It does not inspect a top-level
`gemm_relu` flag.

`compiler/gpdpu_compiler/core/stream_compiler/binary_plan.py` consumes
`TemplateOpPlan` and assigns symbolic binary rows.  This is also mostly aligned
with the op-chain model.

## What Is Not Clean Enough

### 1. Demo pipeline still derives ReLU from profile name

File:

- `compiler/tools/stream_compiler_demo_pipeline.py`

Current shape:

```python
SnapshotProfile = Literal["gemm_relu", "gemm_no_relu"]

def build_demo_pipeline(profile: SnapshotProfile) -> DemoPipelineArtifacts:
    include_relu = profile == "gemm_relu"
    ...
    stream_plan = build_demo_gemm_stream_plan(include_relu=include_relu)
    fibers = build_demo_fibers(stream_plan, include_relu=include_relu)
```

Risk:

- This encodes ReLU as a profile-level branch.
- It makes `gemm_no_relu` / `gemm_relu` look like two compiler modes rather than
  two fiber op-chain inputs.

Required direction:

- Replace `include_relu` with an explicit fiber/tile-job op-chain descriptor.
- `gemm_no_relu` and `gemm_relu` should differ only by the chain passed in.

### 2. Matmul fiber pattern currently hardcodes `epilogue_relu`

File:

- `compiler/gpdpu_compiler/core/stream_compiler/fiber_patterns.py`

Current shape:

```python
post_region=(
    finalize_accumulator,
    epilogue_relu,
    store_fragment,
)
```

File:

- `compiler/gpdpu_compiler/core/stream_compiler/fiber.py`

Current shape:

```python
include_epilogue_relu: bool = True
...
if include_epilogue_relu:
    next_op("epilogue_relu", ...)
...
next_op("store_fragment", inputs=(store_input,), ...)
```

Risk:

- The pattern says ReLU is always part of the matmul post-region, even when the
  builder skips it.
- The builder works, but conceptually it is still a special-case boolean rather
  than a generic ordered post-op chain.

Required direction:

- `post_region` should be built from:

```text
finalize_accumulator
  -> post_op_chain[]
  -> store_fragment
```

- Empty `post_op_chain` gives `gemm_no_relu`.
- `post_op_chain=[relu]` gives `gemm_relu`.
- Future post-ops should use the same shape.

### 3. ReLU has a dedicated report layer instead of generic op-chain binding

File:

- `compiler/gpdpu_compiler/core/stream_compiler/relu_binding.py`

Current role:

- Consumes `TemplateOpPlan`.
- Finds `epilogue:relu`.
- Verifies store consumes ReLU output.
- Remains fail-closed.

This report is useful as a diagnostic, but it should not become the primary
GEMM+ReLU lowering path.

Required direction:

- Keep the current report temporarily as an invariant checker.
- Move actual lowering authority into generic op-chain materialization:

```text
TemplateOp(role=epilogue:relu)
  -> template intent
  -> binary row/span materialization
```

The same mechanism should handle other local elementwise post-ops.

### 4. MatMul spec includes ReLU as a built-in role

File:

- `compiler/gpdpu_compiler/core/op_specs/matmul.py`

Current shape:

- `EPILOGUE_RELU_ROLE`
- `allowed_post_op_kinds=("relu",)`
- role profile includes `source_step_ids=("epilogue_relu",)`
- template intent profile includes ReLU fallback status.

Risk:

- This is acceptable as a transitional descriptor, but it should not mean that
  MatMul owns ReLU lowering.

Required direction:

- MatMul may declare post-op compatibility.
- ReLU should contribute its own local elementwise op descriptor.
- The fiber composer should merge the MatMul reduction chain and local post-op
  chain before target role/template lowering.

## Correct Target Shape

The B-line implementation should converge on:

```text
op specs / frontend program
  -> fiber/tile-job chain descriptor
  -> Fiber(flat ordered ops)
  -> ExecutableFiberOp roles
  -> TemplateOpPlan
  -> BinaryLayoutPlan
  -> component writers
```

For the two GEMM operators:

```text
gemm_no_relu chain:
  accumulator_prepare
  -> loop(materialize_A, materialize_B, gemm_update)
  -> finalize_accumulator
  -> store_fragment

gemm_relu chain:
  accumulator_prepare
  -> loop(materialize_A, materialize_B, gemm_update)
  -> finalize_accumulator
  -> epilogue_relu
  -> store_fragment
```

The materializer should consume these chains uniformly.  It should not branch
inside a GEMM writer based on `has_relu`.

## Refactor Before Next Binary Work

Before building the next B-line-native binary materializer, do this small
cleanup:

1. Introduce a small `FiberOpChainProfile` / `PostOpChainProfile` data shape.
2. Replace `include_epilogue_relu: bool` with `post_op_chain`.
3. Generate `post_region` from `finalize + post_op_chain + store`.
4. Make `gemm_no_relu` and `gemm_relu` demo profiles pass different chains.
5. Keep `relu_binding.py` as a diagnostic checker only.

This is not broad architecture work.  It is a small guardrail to prevent the
native binary materializer from baking in the wrong GEMM/ReLU split.

## Final Answer

The B-line code has the right IR foundations, but the current implementation has
not fully落实 the intended op-chain model.  If we start binary materialization
from the current `include_relu` switch, we will likely need to refactor later.
The next implementation cut should first make post-op composition explicit and
data-driven, then emit binary rows from the resulting chain.
