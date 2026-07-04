"""Internal operator lowering strategy descriptors.

These records are intentionally data-only.  Operator specs may return them, and
lowering passes may consume them, but specs must not construct or mutate
downstream stream/fiber/template/binary IR.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal, TypeAlias


JsonScalar: TypeAlias = str | int | float | bool | None
JsonValue: TypeAlias = JsonScalar | tuple["JsonValue", ...] | tuple[tuple[str, "JsonValue"], ...]


FiberPhase = Literal["tile_body", "tile_store", "pre_loop", "loop_body", "post_loop"]
VisibilityKind = Literal[
    "local",
    "row_visible",
    "column_visible",
    "broadcast",
    "reduce_collective",
    "materialized_storage",
]
VisibilityCostModel = Literal[
    "local_only",
    "per_task_input_visibility",
    "task_local_route",
    "collective_required",
    "materialized_reload",
]
TemplateFallbackStatus = Literal["symbolic_unresolved", "unsupported"]
TargetTemplateStatus = Literal[
    "concrete",
    "legacy_candidate",
    "candidate_unproven",
    "zero_instruction",
    "symbolic_unresolved",
    "unsupported",
]
AssociativityPolicy = Literal[
    "not_reassociable",
    "associative_for_declared_numeric_policy",
]
OrderingPolicy = Literal[
    "strict_sequential",
    "fixed_tree",
    "unordered_associative",
]
ValueExpr: TypeAlias = str


@dataclass(frozen=True)
class ExecutableRoleId:
    """Structured executable role identifier.

    The text form is intentionally stable because current B-line reports still
    use role strings.  The structured form prevents new specs from inventing
    near-duplicate strings by accident.
    """

    namespace: str
    name: str
    operand_role: str | None = None
    text_value: str | None = None

    def text(self) -> str:
        if self.text_value is not None:
            return self.text_value
        if self.operand_role is not None:
            return f"{self.namespace}:{self.name}:{self.operand_role}"
        if self.namespace == "store":
            return self.name
        return f"{self.namespace}:{self.name}"


@dataclass(frozen=True)
class FragmentSpaceProfile:
    name: str
    axes: tuple[str, ...]


@dataclass(frozen=True)
class NumericPolicy:
    input_dtype: str
    accumulator_dtype: str
    rounding_mode: str
    overflow_behavior: str
    allowed_reassociation: bool
    determinism_requirement: str


@dataclass(frozen=True)
class AccessRelationProfile:
    name: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    relation: str
    attrs: tuple[tuple[str, JsonValue], ...] = ()


@dataclass(frozen=True)
class ReductionProfile:
    axis: str
    identity: ValueExpr
    update_relation: AccessRelationProfile
    output_relation: AccessRelationProfile
    numeric_policy: NumericPolicy
    ordering: OrderingPolicy
    associativity: AssociativityPolicy


@dataclass(frozen=True)
class OperatorAccessProfile:
    op_name: str
    fragment_spaces: tuple[FragmentSpaceProfile, ...]
    relations: tuple[AccessRelationProfile, ...]
    reductions: tuple[ReductionProfile, ...] = ()


@dataclass(frozen=True)
class VisibilityScopeProfile:
    kind: VisibilityKind
    consumer_space: str
    consumer_axes: tuple[str, ...]
    producer_fragment_space: str
    producer_fragment_axes: tuple[str, ...]
    visibility_group_axes: tuple[str, ...]
    materialization_policy: VisibilityCostModel


@dataclass(frozen=True)
class StreamVisibilityProfile:
    op_name: str
    scopes: tuple[VisibilityScopeProfile, ...]


@dataclass(frozen=True)
class ExecutableRoleProfile:
    role: ExecutableRoleId
    source_step_ids: tuple[str, ...]
    phase: FiberPhase
    zero_instruction_candidate: bool = False


@dataclass(frozen=True)
class ExecutableRoleSetProfile:
    op_name: str
    roles: tuple[ExecutableRoleProfile, ...]

    def role_texts(self) -> tuple[str, ...]:
        return tuple(role.role.text() for role in self.roles)


@dataclass(frozen=True)
class TemplateIntentProfile:
    executable_role: ExecutableRoleId
    template_family: str | None
    resource_intent: tuple[str, ...]
    may_be_zero_instruction: bool = False
    fallback_status: TemplateFallbackStatus = "symbolic_unresolved"


@dataclass(frozen=True)
class TemplateIntentSetProfile:
    op_name: str
    intents: tuple[TemplateIntentProfile, ...]


@dataclass(frozen=True)
class TemplateEvidenceProfile:
    """Shared shape for target-owned evidence records.

    Concrete instances must be produced by target/profile modules, not by
    concrete operator specs.
    """

    executable_role: ExecutableRoleId
    target_profile_id: str
    resolved_status: TargetTemplateStatus
    template_role: str | None
    evidence_refs: tuple[str, ...]


__all__ = [
    "AccessRelationProfile",
    "AssociativityPolicy",
    "ExecutableRoleId",
    "ExecutableRoleProfile",
    "ExecutableRoleSetProfile",
    "FiberPhase",
    "FragmentSpaceProfile",
    "JsonValue",
    "NumericPolicy",
    "OperatorAccessProfile",
    "OrderingPolicy",
    "ReductionProfile",
    "StreamVisibilityProfile",
    "TargetTemplateStatus",
    "TemplateEvidenceProfile",
    "TemplateFallbackStatus",
    "TemplateIntentProfile",
    "TemplateIntentSetProfile",
    "VisibilityCostModel",
    "VisibilityKind",
    "VisibilityScopeProfile",
    "ValueExpr",
]
