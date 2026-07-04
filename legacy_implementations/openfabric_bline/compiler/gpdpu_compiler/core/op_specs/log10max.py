"""Log10max lowering policy descriptors.

The current DFU-first log10max path is a flat local tile op chain plus a
blocked PE00 scalar step.  This file only describes roles and template intent;
it does not construct stream/fiber/template/binary IR.
"""

from __future__ import annotations

from dataclasses import dataclass

from gpdpu_compiler.core.op_specs.lowering_profiles import (
    AccessRelationProfile,
    ExecutableRoleId,
    ExecutableRoleProfile,
    ExecutableRoleSetProfile,
    FragmentSpaceProfile,
    OperatorAccessProfile,
    StreamVisibilityProfile,
    TemplateIntentProfile,
    TemplateIntentSetProfile,
    VisibilityScopeProfile,
)


LOG10MAX_CLAMP_MIN_ROLE = ExecutableRoleId(
    namespace="tile_op",
    name="clamp_min",
    text_value="tile_op:clamp_min",
)
LOG10MAX_LOG10_ROLE = ExecutableRoleId(
    namespace="tile_op",
    name="log10",
    text_value="tile_op:log10",
)
LOG10MAX_LOCAL_REDUCE_MAX_ROLE = ExecutableRoleId(
    namespace="tile_reduce",
    name="local_reduce_max",
    text_value="tile_reduce:local_reduce_max",
)
LOG10MAX_GLOBAL_MAX_ROLE = ExecutableRoleId(
    namespace="collective",
    name="global_max",
    text_value="collective:global_max",
)
LOG10MAX_ROUTE_PUSH_GLOBAL_MAX_ROLE = ExecutableRoleId(
    namespace="operand_route_push",
    name="operand_route_push",
    operand_role="GlobalMax",
    text_value="operand_route_push:GlobalMax",
)
LOG10MAX_ROUTE_RECV_GLOBAL_MAX_ROLE = ExecutableRoleId(
    namespace="operand_route_recv",
    name="operand_route_recv",
    operand_role="GlobalMax",
    text_value="operand_route_recv:GlobalMax",
)
LOG10MAX_MAX_WITH_FLOOR_ROLE = ExecutableRoleId(
    namespace="tile_op",
    name="max_with_floor",
    text_value="tile_op:max_with_floor",
)
LOG10MAX_AFFINE_SCALE_ROLE = ExecutableRoleId(
    namespace="tile_op",
    name="affine_scale",
    text_value="tile_op:affine_scale",
)
LOG10MAX_STORE_ROLE = ExecutableRoleId(
    namespace="store",
    name="tile_store",
    text_value="tile_store",
)


@dataclass(frozen=True)
class Log10MaxOpSpec:
    """Descriptor-only profile for the current log10max tile chain."""

    op_name: str = "log10max"

    def access_profile(self, op: object | None = None) -> OperatorAccessProfile:
        return OperatorAccessProfile(
            op_name=self.op_name,
            fragment_spaces=(
                FragmentSpaceProfile(name="X_tiles", axes=("tile",)),
                FragmentSpaceProfile(name="local_scalar", axes=("tile",)),
                FragmentSpaceProfile(name="Y_tiles", axes=("tile",)),
            ),
            relations=(
                AccessRelationProfile(
                    name="clamp_min_tile",
                    inputs=("X_tile(tile)",),
                    outputs=("x_clamped_tile(tile)",),
                    relation="x_clamped_tile = max(X_tile, 1e-10)",
                ),
                AccessRelationProfile(
                    name="log10_tile",
                    inputs=("x_clamped_tile(tile)",),
                    outputs=("local_log10_tile(tile)",),
                    relation="local_log10_tile = log2(x_clamped_tile) * log10(2)",
                ),
                AccessRelationProfile(
                    name="local_reduce_max_tile",
                    inputs=("local_log10_tile(tile)",),
                    outputs=("local_max_scalar(tile)",),
                    relation="local_max_scalar = max(local_log10_tile lanes)",
                ),
                AccessRelationProfile(
                    name="affine_scale_tile",
                    inputs=("clipped_tile(tile)",),
                    outputs=("Y_tile(tile)",),
                    relation="Y_tile = (clipped_tile + 4.0) * 0.25",
                ),
            ),
            reductions=(),
        )

    def stream_visibility_profile(
        self,
        op: object | None = None,
    ) -> StreamVisibilityProfile:
        return StreamVisibilityProfile(
            op_name=self.op_name,
            scopes=(
                VisibilityScopeProfile(
                    kind="local",
                    consumer_space="Y_tiles",
                    consumer_axes=("tile",),
                    producer_fragment_space="X_tiles",
                    producer_fragment_axes=("tile",),
                    visibility_group_axes=("tile",),
                    materialization_policy="local_only",
                ),
                VisibilityScopeProfile(
                    kind="reduce_collective",
                    consumer_space="Y_tiles",
                    consumer_axes=("tile",),
                    producer_fragment_space="local_scalar",
                    producer_fragment_axes=("tile",),
                    visibility_group_axes=("tile",),
                    materialization_policy="collective_required",
                ),
            ),
        )

    def executable_role_profile(
        self,
        op: object | None = None,
    ) -> ExecutableRoleSetProfile:
        return ExecutableRoleSetProfile(
            op_name=self.op_name,
            roles=(
                ExecutableRoleProfile(
                    role=LOG10MAX_CLAMP_MIN_ROLE,
                    source_step_ids=("clamp_min_tile",),
                    phase="tile_body",
                ),
                ExecutableRoleProfile(
                    role=LOG10MAX_LOG10_ROLE,
                    source_step_ids=("log10_tile",),
                    phase="tile_body",
                ),
                ExecutableRoleProfile(
                    role=LOG10MAX_LOCAL_REDUCE_MAX_ROLE,
                    source_step_ids=("local_reduce_max_tile",),
                    phase="tile_body",
                ),
                ExecutableRoleProfile(
                    role=LOG10MAX_GLOBAL_MAX_ROLE,
                    source_step_ids=("global_max_tile",),
                    phase="tile_body",
                ),
                ExecutableRoleProfile(
                    role=LOG10MAX_ROUTE_PUSH_GLOBAL_MAX_ROLE,
                    source_step_ids=("materialize_GlobalMax",),
                    phase="tile_body",
                ),
                ExecutableRoleProfile(
                    role=LOG10MAX_ROUTE_RECV_GLOBAL_MAX_ROLE,
                    source_step_ids=("materialize_GlobalMax",),
                    phase="tile_body",
                ),
                ExecutableRoleProfile(
                    role=LOG10MAX_MAX_WITH_FLOOR_ROLE,
                    source_step_ids=("max_with_floor_tile",),
                    phase="tile_body",
                ),
                ExecutableRoleProfile(
                    role=LOG10MAX_AFFINE_SCALE_ROLE,
                    source_step_ids=("affine_scale_tile",),
                    phase="tile_body",
                ),
                ExecutableRoleProfile(
                    role=LOG10MAX_STORE_ROLE,
                    source_step_ids=("store_fragment",),
                    phase="post_loop",
                ),
            ),
        )

    def template_intent_profile(
        self,
        op: object | None = None,
    ) -> TemplateIntentSetProfile:
        return TemplateIntentSetProfile(
            op_name=self.op_name,
            intents=(
                TemplateIntentProfile(
                    executable_role=LOG10MAX_CLAMP_MIN_ROLE,
                    template_family="dfu3500_log10max_local",
                    resource_intent=("FMAX_immediate_clamp_min",),
                ),
                TemplateIntentProfile(
                    executable_role=LOG10MAX_LOG10_ROLE,
                    template_family="dfu3500_log10max_local",
                    resource_intent=("FLOG2", "FMUL_log10_2"),
                ),
                TemplateIntentProfile(
                    executable_role=LOG10MAX_LOCAL_REDUCE_MAX_ROLE,
                    template_family="dfu3500_log10max_local",
                    resource_intent=("SHFL_lane_reduce", "FMAX_local_reduce"),
                ),
                TemplateIntentProfile(
                    executable_role=LOG10MAX_GLOBAL_MAX_ROLE,
                    template_family="dfu3500_log10max_pe00_scalar",
                    resource_intent=("pe00_aggregate_materialize",),
                    fallback_status="symbolic_unresolved",
                ),
                TemplateIntentProfile(
                    executable_role=LOG10MAX_ROUTE_PUSH_GLOBAL_MAX_ROLE,
                    template_family="legacy_gemm_route_forward",
                    resource_intent=(
                        "reuse_existing_route_push_template_family",
                        "global_max_scalar_role_generalization",
                    ),
                ),
                TemplateIntentProfile(
                    executable_role=LOG10MAX_ROUTE_RECV_GLOBAL_MAX_ROLE,
                    template_family="legacy_gemm_route_forward",
                    resource_intent=(
                        "reuse_existing_route_recv_template_family",
                        "receiver_owned_global_max_scalar_operand",
                    ),
                ),
                TemplateIntentProfile(
                    executable_role=LOG10MAX_MAX_WITH_FLOOR_ROLE,
                    template_family="dfu3500_log10max_local",
                    resource_intent=("FMAX_vector_scalar_after_pe00_scalar",),
                    fallback_status="symbolic_unresolved",
                ),
                TemplateIntentProfile(
                    executable_role=LOG10MAX_AFFINE_SCALE_ROLE,
                    template_family="dfu3500_log10max_local",
                    resource_intent=("FADD_output_bias", "FMUL_output_scale"),
                ),
                TemplateIntentProfile(
                    executable_role=LOG10MAX_STORE_ROLE,
                    template_family="legacy_gemm",
                    resource_intent=("tile_store",),
                ),
            ),
        )


LOG10MAX_SPEC = Log10MaxOpSpec()


__all__ = [
    "LOG10MAX_SPEC",
    "LOG10MAX_ROUTE_PUSH_GLOBAL_MAX_ROLE",
    "LOG10MAX_ROUTE_RECV_GLOBAL_MAX_ROLE",
    "Log10MaxOpSpec",
]
