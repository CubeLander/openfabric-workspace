"""Symbolic elementwise-family lowering profiles.

This is a descriptor-only sanity fixture for the operator strategy schema.  It
is intentionally not connected to runnable DFU3500 binary emission.
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


ELEMENTWISE_INPUT_ROLE = ExecutableRoleId(
    namespace="operand_materialize",
    name="operand_materialize",
    operand_role="X",
    text_value="operand_materialize:X",
)
ELEMENTWISE_APPLY_ROLE = ExecutableRoleId(
    namespace="elementwise",
    name="apply",
    text_value="elementwise:apply",
)
ELEMENTWISE_STORE_ROLE = ExecutableRoleId(
    namespace="store",
    name="tile_store",
    text_value="tile_store",
)


@dataclass(frozen=True)
class ElementwiseFamilySpec:
    """Descriptor-only non-GEMM proving target for B-line op specs."""

    op_name: str = "elementwise"

    def access_profile(self, op: object | None = None) -> OperatorAccessProfile:
        return OperatorAccessProfile(
            op_name=self.op_name,
            fragment_spaces=(
                FragmentSpaceProfile(name="X_tiles", axes=("tile",)),
                FragmentSpaceProfile(name="Y_tiles", axes=("tile",)),
            ),
            relations=(
                AccessRelationProfile(
                    name="elementwise_apply",
                    inputs=("X_tile(tile)",),
                    outputs=("Y_tile(tile)",),
                    relation="Y_tile = f(X_tile)",
                ),
            ),
            reductions=(),
        )

    def stream_visibility_profile(self, op: object | None = None) -> StreamVisibilityProfile:
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
            ),
        )

    def executable_role_profile(self, op: object | None = None) -> ExecutableRoleSetProfile:
        return ExecutableRoleSetProfile(
            op_name=self.op_name,
            roles=(
                ExecutableRoleProfile(
                    role=ELEMENTWISE_INPUT_ROLE,
                    source_step_ids=("materialize_input",),
                    phase="pre_loop",
                ),
                ExecutableRoleProfile(
                    role=ELEMENTWISE_APPLY_ROLE,
                    source_step_ids=("elementwise_apply",),
                    phase="loop_body",
                ),
                ExecutableRoleProfile(
                    role=ELEMENTWISE_STORE_ROLE,
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
                    executable_role=ELEMENTWISE_INPUT_ROLE,
                    template_family=None,
                    resource_intent=("local_operand_visibility",),
                    fallback_status="symbolic_unresolved",
                ),
                TemplateIntentProfile(
                    executable_role=ELEMENTWISE_APPLY_ROLE,
                    template_family="elementwise",
                    resource_intent=("elementwise_apply",),
                    fallback_status="symbolic_unresolved",
                ),
                TemplateIntentProfile(
                    executable_role=ELEMENTWISE_STORE_ROLE,
                    template_family=None,
                    resource_intent=("tile_store",),
                    fallback_status="symbolic_unresolved",
                ),
            ),
        )

ELEMENTWISE_FAMILY_SPEC = ElementwiseFamilySpec()


__all__ = [
    "ELEMENTWISE_FAMILY_SPEC",
    "ElementwiseFamilySpec",
]
