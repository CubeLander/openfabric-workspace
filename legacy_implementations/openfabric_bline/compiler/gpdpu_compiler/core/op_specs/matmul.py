"""MatMul lowering policy descriptors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from gpdpu_compiler.core.op_specs.base import (
    ComputeMicroBlockProfile,
    Dfu3500MatmulLoweringContract,
    FusionCompatibilityProfile,
    MatmulSemanticContract,
    OpParallelProfile,
    StateLifetimeProfile,
    TaskDecompositionProfile,
    TileLoweringProfile,
)
from gpdpu_compiler.core.op_specs.lowering_profiles import (
    AccessRelationProfile,
    ExecutableRoleId,
    ExecutableRoleProfile,
    ExecutableRoleSetProfile,
    FragmentSpaceProfile,
    NumericPolicy,
    OperatorAccessProfile,
    ReductionProfile,
    StreamVisibilityProfile,
    TemplateIntentProfile,
    TemplateIntentSetProfile,
    VisibilityScopeProfile,
)
from gpdpu_compiler.core.placement_types import Replicate, Shard


ACCUMULATOR_PREPARE_ROLE = ExecutableRoleId(
    namespace="accumulator",
    name="prepare",
    text_value="accumulator_prepare",
)
OPERAND_MATERIALIZE_A_ROLE = ExecutableRoleId(
    namespace="operand_materialize",
    name="operand_materialize",
    operand_role="A",
    text_value="operand_materialize:A",
)
OPERAND_MATERIALIZE_B_ROLE = ExecutableRoleId(
    namespace="operand_materialize",
    name="operand_materialize",
    operand_role="B",
    text_value="operand_materialize:B",
)
OPERAND_ROUTE_RECV_A_ROLE = ExecutableRoleId(
    namespace="operand_route_recv",
    name="operand_route_recv",
    operand_role="A",
    text_value="operand_route_recv:A",
)
OPERAND_ROUTE_RECV_B_ROLE = ExecutableRoleId(
    namespace="operand_route_recv",
    name="operand_route_recv",
    operand_role="B",
    text_value="operand_route_recv:B",
)
OPERAND_ROUTE_PUSH_A_ROLE = ExecutableRoleId(
    namespace="operand_route_push",
    name="operand_route_push",
    operand_role="A",
    text_value="operand_route_push:A",
)
OPERAND_ROUTE_PUSH_B_ROLE = ExecutableRoleId(
    namespace="operand_route_push",
    name="operand_route_push",
    operand_role="B",
    text_value="operand_route_push:B",
)
GEMM_UPDATE_ROLE = ExecutableRoleId(
    namespace="compute_core",
    name="gemm_update",
    text_value="compute_core:gemm_update",
)
GEMM_TILE_ROLE = ExecutableRoleId(
    namespace="compute_core",
    name="gemm_tile",
    text_value="compute_core:gemm_tile",
)
ACCUMULATOR_FINALIZE_ROLE = ExecutableRoleId(
    namespace="accumulator",
    name="finalize",
    text_value="accumulator_finalize",
)
TILE_STORE_ROLE = ExecutableRoleId(
    namespace="store",
    name="tile_store",
    text_value="tile_store",
)
RELU_TILE_ROLE = ExecutableRoleId(
    namespace="tile_op",
    name="relu",
    text_value="tile_op:relu",
)


@dataclass(frozen=True)
class MatmulOpSpec:
    """Declarative policy for the current rank-2 DFU-first matmul path."""

    op_name: Literal["matmul"] = "matmul"

    def semantic_contract(self) -> MatmulSemanticContract:
        return MatmulSemanticContract(
            shape_rule="rank2_mk_kn_to_mn",
            dtype_policy="lhs_rhs_same_dtype",
        )

    def dfu3500_lowering_contract(self) -> Dfu3500MatmulLoweringContract:
        return Dfu3500MatmulLoweringContract(
            lowering_kind="summa_gemm",
            target="dfu3500",
            target_profile_id="dfu3500_simict_legacy_gemm",
            supported_lhs_placements=(Shard(0), Replicate()),
            supported_rhs_placements=(Replicate(), Shard(1)),
            supported_output_placements=(Shard(0), Shard(1)),
            default_lowering_hint="dfu_summa_gemm",
            execution_model="spmd",
        )

    def access_profile(self, op: object | None = None) -> OperatorAccessProfile:
        update_relation = AccessRelationProfile(
            name="matmul_reduction_update",
            inputs=(
                "reduction_state(m,n,reduction_fragment-1)",
                "A_tile(m,reduction_fragment)",
                "B_tile(reduction_fragment,n)",
            ),
            outputs=("reduction_state(m,n,reduction_fragment)",),
            relation="acc_next = acc_prev + A_tile * B_tile",
        )
        output_relation = AccessRelationProfile(
            name="matmul_reduction_output",
            inputs=("final_reduction_state(m,n)",),
            outputs=("C_tile(m,n)",),
            relation="C_tile is derived from final reduction state",
        )
        return OperatorAccessProfile(
            op_name=self.op_name,
            fragment_spaces=(
                FragmentSpaceProfile(name="A_tiles", axes=("m_tile", "reduction_fragment")),
                FragmentSpaceProfile(name="B_tiles", axes=("reduction_fragment", "n_tile")),
                FragmentSpaceProfile(
                    name="C_acc_tiles",
                    axes=("m_tile", "n_tile", "reduction_fragment"),
                ),
                FragmentSpaceProfile(name="C_tiles", axes=("m_tile", "n_tile")),
            ),
            relations=(
                AccessRelationProfile(
                    name="matmul_accumulator_identity",
                    inputs=(),
                    outputs=("reduction_state(m,n,identity)",),
                    relation="identity element initializes reduction state",
                ),
                update_relation,
                output_relation,
            ),
            reductions=(
                ReductionProfile(
                    axis="k",
                    identity="zero",
                    update_relation=update_relation,
                    output_relation=output_relation,
                    numeric_policy=NumericPolicy(
                        input_dtype="fp16",
                        accumulator_dtype="dfu3500_legacy_gemm_accumulator",
                        rounding_mode="dfu3500_legacy_gemm",
                        overflow_behavior="dfu3500_legacy_gemm",
                        allowed_reassociation=False,
                        determinism_requirement="legacy_byte_stable",
                    ),
                    ordering="strict_sequential",
                    associativity="not_reassociable",
                ),
            ),
        )

    def parallel_profile(self) -> OpParallelProfile:
        return OpParallelProfile(
            primary_schedule_kind="gemm_output_tiles",
            task_decomposition=TaskDecompositionProfile(
                partition_kind="gemm_output_tiles",
                max_task_rows=4,
                required_subtask_roles=(
                    "accumulator_prepare",
                    "k_stream",
                    "finalize_store",
                ),
            ),
            fusion=FusionCompatibilityProfile(
                allowed_post_op_kinds=("relu",),
                dependency_requirement="tile_local_primary_output_only",
                forbids_cross_pe_collective=True,
                forbids_app_storage_load=True,
                output_store_position="after_tile_op_chain",
            ),
            state_lifetimes=(
                StateLifetimeProfile(
                    value_role="primary_outputs",
                    state_kind="APP_LOCAL_EXPLICIT",
                    required_scope="same_app",
                    proof="gemm_accumulator_lives_inside_task_subtask_instance_profile",
                ),
            ),
            requires_global_merge=False,
            result_visibility="independent_output_tiles",
        )

    def tile_lowering_profile(self) -> TileLoweringProfile:
        return TileLoweringProfile(
            phase_kind="local_gemm_summa",
            template_kind="summa_gemm_64x64x64_fp16",
            source_compute_kind="matmul",
            accumulator_prepare_kind="accumulator_prepare",
            k_update_kind="gemm_k_update",
            local_prepare_op="init_c",
            local_k_stream_op="stream_k_gemm",
            local_store_op="store_c",
            loop_axis="K",
            loop_fold_policy="vendor_instance_repeat_candidate",
            loop_closure_shape="closed_repeated_tile_body",
            compute_micro_blocks=(
                ComputeMicroBlockProfile(
                    compute_kind="accumulator_prepare",
                    micro_block_kind="accumulator_prepare",
                ),
                ComputeMicroBlockProfile(
                    compute_kind="gemm_k_update",
                    micro_block_kind="compute_update",
                ),
            ),
        )

    def stream_visibility_profile(self, op: object | None = None) -> StreamVisibilityProfile:
        return StreamVisibilityProfile(
            op_name=self.op_name,
            scopes=(
                VisibilityScopeProfile(
                    kind="row_visible",
                    consumer_space="C_tiles",
                    consumer_axes=("m_tile", "n_tile"),
                    producer_fragment_space="A_tiles",
                    producer_fragment_axes=("m_tile", "reduction_fragment"),
                    visibility_group_axes=("m_tile", "reduction_fragment"),
                    materialization_policy="task_local_route",
                ),
                VisibilityScopeProfile(
                    kind="column_visible",
                    consumer_space="C_tiles",
                    consumer_axes=("m_tile", "n_tile"),
                    producer_fragment_space="B_tiles",
                    producer_fragment_axes=("reduction_fragment", "n_tile"),
                    visibility_group_axes=("reduction_fragment", "n_tile"),
                    materialization_policy="task_local_route",
                ),
            ),
        )

    def executable_role_profile(self, op: object | None = None) -> ExecutableRoleSetProfile:
        return ExecutableRoleSetProfile(
            op_name=self.op_name,
            roles=(
                ExecutableRoleProfile(
                    role=GEMM_TILE_ROLE,
                    source_step_ids=("gemm_tile",),
                    phase="tile_body",
                ),
                ExecutableRoleProfile(
                    role=RELU_TILE_ROLE,
                    source_step_ids=("relu_tile",),
                    phase="tile_body",
                ),
                ExecutableRoleProfile(
                    role=ACCUMULATOR_PREPARE_ROLE,
                    source_step_ids=("accumulator_prepare",),
                    phase="pre_loop",
                ),
                ExecutableRoleProfile(
                    role=OPERAND_MATERIALIZE_A_ROLE,
                    source_step_ids=("materialize_A",),
                    phase="loop_body",
                ),
                ExecutableRoleProfile(
                    role=OPERAND_MATERIALIZE_B_ROLE,
                    source_step_ids=("materialize_B",),
                    phase="loop_body",
                ),
                ExecutableRoleProfile(
                    role=OPERAND_ROUTE_RECV_A_ROLE,
                    source_step_ids=("materialize_A",),
                    phase="loop_body",
                ),
                ExecutableRoleProfile(
                    role=OPERAND_ROUTE_RECV_B_ROLE,
                    source_step_ids=("materialize_B",),
                    phase="loop_body",
                ),
                ExecutableRoleProfile(
                    role=OPERAND_ROUTE_PUSH_A_ROLE,
                    source_step_ids=("materialize_A",),
                    phase="loop_body",
                ),
                ExecutableRoleProfile(
                    role=OPERAND_ROUTE_PUSH_B_ROLE,
                    source_step_ids=("materialize_B",),
                    phase="loop_body",
                ),
                ExecutableRoleProfile(
                    role=GEMM_UPDATE_ROLE,
                    source_step_ids=("gemm_update",),
                    phase="loop_body",
                ),
                ExecutableRoleProfile(
                    role=ACCUMULATOR_FINALIZE_ROLE,
                    source_step_ids=("finalize_accumulator",),
                    phase="post_loop",
                    zero_instruction_candidate=True,
                ),
                ExecutableRoleProfile(
                    role=TILE_STORE_ROLE,
                    source_step_ids=("store_fragment",),
                    phase="post_loop",
                ),
            ),
        )

    def template_intent_profile(self, op: object | None = None) -> TemplateIntentSetProfile:
        return TemplateIntentSetProfile(
            op_name=self.op_name,
            intents=(
                TemplateIntentProfile(
                    executable_role=GEMM_TILE_ROLE,
                    template_family="dfu3500_gemm_tile",
                    resource_intent=("atomic_gemm_tile_template_span",),
                    fallback_status="symbolic_unresolved",
                ),
                TemplateIntentProfile(
                    executable_role=RELU_TILE_ROLE,
                    template_family="dfu3500_relu_tile",
                    resource_intent=(
                        "independent_relu_tile_op",
                        "max_with_zero_constant",
                    ),
                    fallback_status="symbolic_unresolved",
                ),
                TemplateIntentProfile(
                    executable_role=ACCUMULATOR_PREPARE_ROLE,
                    template_family="legacy_gemm",
                    resource_intent=("accumulator_init",),
                ),
                TemplateIntentProfile(
                    executable_role=OPERAND_MATERIALIZE_A_ROLE,
                    template_family="legacy_gemm",
                    resource_intent=("operand_visibility", "route_source_materialize"),
                ),
                TemplateIntentProfile(
                    executable_role=OPERAND_MATERIALIZE_B_ROLE,
                    template_family="legacy_gemm",
                    resource_intent=("operand_visibility", "route_source_materialize"),
                ),
                TemplateIntentProfile(
                    executable_role=OPERAND_ROUTE_RECV_A_ROLE,
                    template_family="legacy_gemm",
                    resource_intent=("operand_visibility", "route_forward"),
                ),
                TemplateIntentProfile(
                    executable_role=OPERAND_ROUTE_RECV_B_ROLE,
                    template_family="legacy_gemm",
                    resource_intent=("operand_visibility", "route_forward"),
                ),
                TemplateIntentProfile(
                    executable_role=OPERAND_ROUTE_PUSH_A_ROLE,
                    template_family="legacy_gemm",
                    resource_intent=("operand_visibility", "route_forward"),
                ),
                TemplateIntentProfile(
                    executable_role=OPERAND_ROUTE_PUSH_B_ROLE,
                    template_family="legacy_gemm",
                    resource_intent=("operand_visibility", "route_forward"),
                ),
                TemplateIntentProfile(
                    executable_role=GEMM_UPDATE_ROLE,
                    template_family="legacy_gemm",
                    resource_intent=("gemm_compute_update",),
                ),
                TemplateIntentProfile(
                    executable_role=ACCUMULATOR_FINALIZE_ROLE,
                    template_family=None,
                    resource_intent=("accumulator_boundary",),
                    may_be_zero_instruction=True,
                ),
                TemplateIntentProfile(
                    executable_role=TILE_STORE_ROLE,
                    template_family="legacy_gemm",
                    resource_intent=("tile_store",),
                ),
            ),
        )


MATMUL_SPEC = MatmulOpSpec()


__all__ = [
    "MATMUL_SPEC",
    "MatmulOpSpec",
]
