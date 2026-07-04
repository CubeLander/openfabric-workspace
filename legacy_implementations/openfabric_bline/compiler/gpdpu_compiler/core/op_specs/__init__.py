"""Internal operator lowering specs."""

from __future__ import annotations

from gpdpu_compiler.core.op_specs.base import (
    ComputeMicroBlockProfile,
    Dfu3500MatmulLoweringContract,
    FusionCompatibilityProfile,
    MatmulSemanticContract,
    OpView,
    OpParallelProfile,
    StateLifetimeProfile,
    TaskDecompositionProfile,
    TileLoweringProfile,
)
from gpdpu_compiler.core.op_specs.elementwise import (
    ELEMENTWISE_FAMILY_SPEC,
    ElementwiseFamilySpec,
)
from gpdpu_compiler.core.op_specs.lowering_profiles import (
    AccessRelationProfile,
    AssociativityPolicy,
    ExecutableRoleId,
    ExecutableRoleProfile,
    ExecutableRoleSetProfile,
    FragmentSpaceProfile,
    NumericPolicy,
    OperatorAccessProfile,
    OrderingPolicy,
    ReductionProfile,
    StreamVisibilityProfile,
    TemplateEvidenceProfile,
    TemplateIntentProfile,
    TemplateIntentSetProfile,
    VisibilityScopeProfile,
)
from gpdpu_compiler.core.op_specs.log10max import LOG10MAX_SPEC, Log10MaxOpSpec
from gpdpu_compiler.core.op_specs.matmul import MATMUL_SPEC, MatmulOpSpec
from gpdpu_compiler.core.op_specs.operator_strategy import OperatorLoweringSpec


_OP_SPECS = {
    "matmul": MATMUL_SPEC,
    "elementwise": ELEMENTWISE_FAMILY_SPEC,
    "log10max": LOG10MAX_SPEC,
}


def get_op_spec(op_name: str) -> object:
    try:
        return _OP_SPECS[op_name]
    except KeyError as exc:
        raise KeyError(f"unknown operator lowering spec: {op_name}") from exc

__all__ = [
    "AccessRelationProfile",
    "AssociativityPolicy",
    "Dfu3500MatmulLoweringContract",
    "ComputeMicroBlockProfile",
    "ELEMENTWISE_FAMILY_SPEC",
    "ElementwiseFamilySpec",
    "ExecutableRoleId",
    "ExecutableRoleProfile",
    "ExecutableRoleSetProfile",
    "FragmentSpaceProfile",
    "FusionCompatibilityProfile",
    "LOG10MAX_SPEC",
    "Log10MaxOpSpec",
    "MATMUL_SPEC",
    "MatmulOpSpec",
    "MatmulSemanticContract",
    "NumericPolicy",
    "OpView",
    "OperatorAccessProfile",
    "OperatorLoweringSpec",
    "OrderingPolicy",
    "OpParallelProfile",
    "ReductionProfile",
    "StateLifetimeProfile",
    "StreamVisibilityProfile",
    "TaskDecompositionProfile",
    "TemplateEvidenceProfile",
    "TemplateIntentProfile",
    "TemplateIntentSetProfile",
    "TileLoweringProfile",
    "VisibilityScopeProfile",
    "get_op_spec",
]
