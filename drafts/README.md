# Drafts

This directory is only for unfinished design notes and risk registers. A draft
should leave this directory once it has either become current project guidance
under `../docs/` or has been superseded by implementation/source-local docs.

Current naming guidance comes from `../TWO_LEVEL_DTENSOR_NOTES_CN.md`. Drafts
that still say `DTensor`, `DTensorTileRef`, `TileValue`, or `Tile Program`
should be read as pre-scoped-projection language until rewritten.

Current unfinished notes:

| Draft | Status |
| --- | --- |
| `gemm-dtensor-address-auto-planning-cn.md` | Active GEMM/tensor address auto-planning route, but needs terminology migration from DTensor refs to Stream/Fiber projections. |
| `gemm-fiberop-design-notes.md` | Deferred GEMM FiberOp API direction; useful when we return to StreamTensorView/FiberTensorView lowering. |
| `openfabric-strong-generalization-gap-notes-cn.md` | Short active gap list around ChipProgramPlan, CollectivePlan, artifact manifest, and deferred automatic lowering. |
| `spm-data-operator-generation-todo-cn.md` | TODO for eventually generating SPM/input-data helpers from the operator entry. |

Recently resolved:

| Former draft | Resolution |
| --- | --- |
| `log10max-refactored-plan-cn.md` | Superseded by the customer-runnable `log10max_refactored` package milestone. Remaining collective/generalization questions live in the active gap list and source-owned notes. |
| `atomic-fiber-ops-and-planned-values-investigation.md` | Durable value/site/action boundaries distilled into `../docs/openfabric-lowering-principles.md`. |
| `atomic-fiber-ops-planned-values-cn-draft.md` | Same design content consolidated into the current lowering principles. |
| `conf-header-consumer-contract-risk-notes-cn.md` | Header consumer investigation is superseded by generated/runtime-plan source ownership; durable rules moved to docs. |
| `config-compat-image-route-cn.md` | Generated-header route is superseded by RuntimePlanImage/common executor; relevant protocol is in `../docs/runtime-plan-image.md`. |
| `gemm-address-difficulty-notes-cn.md` | Split-address and visibility principles moved to `../docs/address-binding-projections.md`; dump-only harness removed. |
| `gemm-config-address-source-risk-register-cn.md` | Superseded by current GEMM plan/projection implementation and replay guardrails. |
| `gemm-config-device-single-entry-investigation-cn.md` | Superseded by the source-owned GEMM config entry and current replay path. |
| `gemm-softmax-site-abstraction-risk-register-cn.md` | Common site/value cautions are now in `../docs/openfabric-lowering-principles.md`. |
| `lazy-operand-symbol-allocation-cn.md` | Operand materialization rules are now covered by `operand_allocator.h` and lowering principles. |
| `openfabric-config-program-principles-cn.md` | Distilled into `../docs/openfabric-lowering-principles.md`. |
| `openfabric-operator-coverage-matrix-cn.md` | Distilled into `../docs/operator-coverage-checklist.md` and `../docs/openfabric-vector-hardware-coverage.md`. |
| `riscv-runtime-actions-plan-mapping-cn.md` | Runtime order is now owned by RuntimeActionPlan and documented in `../docs/runtime-plan-image.md`. |
| `runtime-config-image-riscv-plan-cn.md` | Superseded by RuntimePlanImage; no separate runtime config image route remains active. |
| `runtime-plan-image-protocol-cn.md` | Protocol moved to `../docs/runtime-plan-image.md`; source ABI remains in `common_app_builder/openfabric_runtime_plan_image.h`. |
| `subtask-site-common-abstraction-draft.md` | Implementation has landed; durable rules are in lowering principles. |
| `tensor-materialization-decoupling-cn.md` | Merged into the active GEMM address plan and address-binding docs; old DTensor wording is superseded by scoped projection. |
| `three-operator-lifecycle-abstraction-table-cn.md` | Cross-operator lifecycle guidance moved to lowering principles and coverage docs. |
| `gemm-subtask-blocks-and-graph-dependency-dump-cn.md` | Promoted to `../docs/gemm-subtask-blocks-and-graph-dependency.md`. |
| `softmax-graph-plan-notes.md` | Design intent promoted to `../docs/graph-plan-projection.md`; draft removed. |
| `softmax-toward-gemm-subtask-site-plan.md` | Promoted to `../docs/softmax-subtask-site-refactor.md`. |
| `common_abstractions.md` | Removed; superseded by the common site draft/risk notes and current code. |
| `gemm_device_program_refactor_plan.md` | Removed; superseded by source-owned GEMM implementation docs and current code. |
| `gemm-refactored-investigation-notes.md` | Removed; superseded by the current `operator_sources/gemm/` structure. |
| `gemm-softmax-refactor-content-matrix.md` | Removed; superseded by the current GEMM refactored source layout. |
| `gemm-refactor-migration-and-binary-verification-plan.md` | Removed; superseded by current replay/compare targets and graph-trace docs. |
| `softmax-runtime-header-generation-notes.md` | Superseded by RuntimePlanImage/common executor flow and removed. |
