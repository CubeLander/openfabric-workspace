"""Operator lowering strategy protocol.

This module defines the internal operator-spec protocol used by B-line schema
work.  It is intentionally free of stream/fiber/template builder imports.
"""

from __future__ import annotations

from typing import Protocol

from gpdpu_compiler.core.op_specs.base import (
    Dfu3500MatmulLoweringContract,
    MatmulSemanticContract,
    OpParallelProfile,
    OpView,
    TileLoweringProfile,
)
from gpdpu_compiler.core.op_specs.lowering_profiles import (
    ExecutableRoleSetProfile,
    OperatorAccessProfile,
    StreamVisibilityProfile,
    TemplateIntentSetProfile,
)


class OperatorLoweringSpec(Protocol):
    op_name: str

    def semantic_contract(self) -> MatmulSemanticContract:
        ...

    def dfu3500_lowering_contract(self) -> Dfu3500MatmulLoweringContract:
        ...

    def parallel_profile(self) -> OpParallelProfile:
        ...

    def tile_lowering_profile(self) -> TileLoweringProfile:
        ...

    def access_profile(self, op: OpView | None = None) -> OperatorAccessProfile:
        ...

    def stream_visibility_profile(self, op: OpView | None = None) -> StreamVisibilityProfile:
        ...

    def executable_role_profile(self, op: OpView | None = None) -> ExecutableRoleSetProfile:
        ...

    def template_intent_profile(self, op: OpView | None = None) -> TemplateIntentSetProfile:
        ...


__all__ = [
    "OperatorLoweringSpec",
]
