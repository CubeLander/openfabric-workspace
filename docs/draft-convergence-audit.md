# Draft convergence audit

Status: current triage record for the `drafts/` cleanup pass.

Each draft was compared against active source under
`simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/`, the shared
`common_app_builder/` support code, current `docs/`, and the latest GEMM/GEMM+ReLU
runtime/address refactors.

## Summary

Most historical drafts have completed their job. Their durable design content
now has two owners:

- `drafts/` only for unfinished work;
- `docs/` for current guidance and reusable design constraints.

The active code evidence includes:

```text
common_app_builder/dtensor_plan.h
common_app_builder/spm_placement.h
common_app_builder/subtask_site.h
common_app_builder/fiber_values.h
common_app_builder/fiber_actions.h
common_app_builder/operand_allocator.h
common_app_builder/register_actions.h
common_app_builder/openfabric_runtime_action_plan.h
common_app_builder/openfabric_runtime_plan_image.h
common_app_builder/openfabric_runtime_plan_riscv_executor.c
gemm_refactored/operator_sources/gemm/
softmax_refactored/operator_sources/softmax/
gemm_relu_refactored/operator_sources/gemm_relu/
log10max_refactored/operator_sources/log10max/
```

## Remaining Drafts

| Draft | Why it remains |
| --- | --- |
| `gemm-dtensor-address-auto-planning-cn.md` | Active address/materialization route; still tracks materialization actions, external layout, base-row, and CSV address projection. |
| `gemm-fiberop-design-notes.md` | Deferred plan-to-fiber direction; useful when automatic lowering resumes. |
| `openfabric-strong-generalization-gap-notes-cn.md` | Short active gap list for ChipProgramPlan, CollectivePlan, ArtifactManifest, and deferred automatic lowering. |
| `spm-data-operator-generation-todo-cn.md` | SPM/test-data helper ownership remains intentionally deferred. |

## Removed Drafts

| Former draft | Source comparison | Disposition |
| --- | --- | --- |
| `log10max-refactored-plan-cn.md` | `log10max_refactored` now generates a customer-runnable package, uses flat SPM layout and subtask-local access slots, and passed the customer-side output checker. | Removed; remaining collective/generalization questions stay in the active gap list and source-owned notes. |
| `atomic-fiber-ops-and-planned-values-investigation.md` | `fiber_values.h`, `fiber_actions.h`, `operand_allocator.h`, and lowering principles cover the stable value/action boundary. | Removed. |
| `atomic-fiber-ops-planned-values-cn-draft.md` | Same design content as above, with Chinese discussion detail. | Removed. |
| `conf-header-consumer-contract-risk-notes-cn.md` | Header consumer risk is superseded by source-owned generators and RuntimePlanImage. | Removed. |
| `config-compat-image-route-cn.md` | Generated-header route is superseded by RuntimePlanImage/common executor. | Removed. |
| `gemm-address-difficulty-notes-cn.md` | Split-address, base row, and visibility principles are in `address-binding-projections.md`; dump-only harness is removed. | Removed. |
| `gemm-config-address-source-risk-register-cn.md` | GEMM plan/projection code and replay compare have superseded the pre-removal risk register. | Removed. |
| `gemm-config-device-single-entry-investigation-cn.md` | Source-owned config entry and replay wrappers have superseded the single-entry investigation. | Removed. |
| `gemm-softmax-site-abstraction-risk-register-cn.md` | Site/value risks are in `openfabric-lowering-principles.md`. | Removed. |
| `lazy-operand-symbol-allocation-cn.md` | Operand handle/materialization guidance is in code and lowering principles. | Removed. |
| `openfabric-config-program-principles-cn.md` | Distilled into `openfabric-lowering-principles.md`. | Removed. |
| `openfabric-operator-coverage-matrix-cn.md` | Distilled into `operator-coverage-checklist.md` and vector coverage docs. | Removed. |
| `riscv-runtime-actions-plan-mapping-cn.md` | Runtime order is now owned by RuntimeActionPlan and documented in `runtime-plan-image.md`. | Removed. |
| `runtime-config-image-riscv-plan-cn.md` | Separate runtime config image route is superseded by RuntimePlanImage. | Removed. |
| `runtime-plan-image-protocol-cn.md` | Protocol guidance moved to `runtime-plan-image.md`; ABI owner is source header. | Removed. |
| `softmax-runtime-header-generation-notes.md` | Already marked superseded. Softmax now emits RuntimePlanImage and uses common executor/replay materialization. | Removed. |
| `subtask-site-common-abstraction-draft.md` | Common site abstractions have landed; remaining rules are in lowering principles. | Removed. |
| `tensor-materialization-decoupling-cn.md` | Merged into active GEMM DTensor route and address-binding docs. | Removed. |
| `three-operator-lifecycle-abstraction-table-cn.md` | Lifecycle guidance moved into lowering principles and coverage checklist. | Removed. |

## Current Reading Path

For design principles:

```text
docs/openfabric-lowering-principles.md
docs/runtime-plan-image.md
docs/operator-coverage-checklist.md
docs/chip-program-plan.md
docs/dtensor-stage-shard-address-plan.md
docs/address-binding-projections.md
docs/partial-reduce-stage-binding.md
docs/typed-vector-operand-design.md
docs/openfabric-vector-hardware-coverage.md
```

For active evidence:

```text
docs/gemm-subtask-blocks-and-graph-dependency.md
docs/gemm-vendor-graph-csv-layout.md
docs/graph-plan-projection.md
docs/softmax-subtask-site-refactor.md
docs/isa/hmmal.md
docs/vendor-workflow-evidence/
```

For runnable source-of-truth comparison:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/softmax_1
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_refactored
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/softmax_refactored
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/log10max_refactored
```
