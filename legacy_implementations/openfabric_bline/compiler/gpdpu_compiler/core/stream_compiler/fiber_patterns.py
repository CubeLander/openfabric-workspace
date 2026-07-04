"""Stream-owned fiber construction patterns.

These records are construction plans only.  They are not folding proofs, and
backend serializers must not consume them as proof authority.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

PatternRegionKind = Literal["pre_region", "repeated_region", "post_region"]


@dataclass(frozen=True)
class TransitionalPatternId:
    name: str
    owner: str
    retirement_condition: str
    allowed_consumers: tuple[str, ...]


@dataclass(frozen=True)
class FiberPatternStep:
    step_id: str
    role: str
    region: PatternRegionKind
    attrs: tuple[tuple[str, object], ...] = ()
    zero_instruction_candidate: bool = False


@dataclass(frozen=True)
class FiberRepeatedRegion:
    region_id: str
    steps: tuple[FiberPatternStep, ...]


@dataclass(frozen=True)
class FiberPatternPlan:
    pattern_id: TransitionalPatternId
    pre_region: tuple[FiberPatternStep, ...]
    repeated_regions: tuple[FiberRepeatedRegion, ...]
    post_region: tuple[FiberPatternStep, ...]

    @property
    def step_order(self) -> tuple[str, ...]:
        repeated_steps = tuple(
            step
            for region in self.repeated_regions
            for step in region.steps
        )
        return tuple(
            step.step_id
            for step in (*self.pre_region, *repeated_steps, *self.post_region)
        )

    def step(self, step_id: str) -> FiberPatternStep | None:
        for step in (
            *self.pre_region,
            *(step for region in self.repeated_regions for step in region.steps),
            *self.post_region,
        ):
            if step.step_id == step_id:
                return step
        return None


def build_matmul_sequential_reduction_pattern() -> FiberPatternPlan:
    """Return the current GEMM construction pattern owned by stream compiler."""

    repeated_steps = (
        FiberPatternStep(
            step_id="materialize_A",
            role="operand_materialize:A",
            region="repeated_region",
            attrs=(("operand", "A"), ("subtask_role", "k_stream")),
        ),
        FiberPatternStep(
            step_id="materialize_B",
            role="operand_materialize:B",
            region="repeated_region",
            attrs=(("operand", "B"), ("subtask_role", "k_stream")),
        ),
        FiberPatternStep(
            step_id="gemm_update",
            role="compute_core:gemm_update",
            region="repeated_region",
            attrs=(("subtask_role", "k_stream"),),
        ),
    )
    return FiberPatternPlan(
        pattern_id=TransitionalPatternId(
            name="matmul_sequential_reduction_transitional",
            owner="stream_compiler/fiber_patterns.py",
            retirement_condition=(
                "replace with generic region-DAG construction after a second "
                "non-MatMul repeated fiber proves the abstraction"
            ),
            allowed_consumers=("stream_compiler/fiber.py",),
        ),
        pre_region=(
            FiberPatternStep(
                step_id="accumulator_prepare",
                role="accumulator_prepare",
                region="pre_region",
                attrs=(("subtask_role", "accumulator_prepare"),),
            ),
        ),
        repeated_regions=(
            FiberRepeatedRegion(
                region_id="reduction_region",
                steps=repeated_steps,
            ),
        ),
        post_region=(
            FiberPatternStep(
                step_id="finalize_accumulator",
                role="accumulator_finalize",
                region="post_region",
                attrs=(("subtask_role", "finalize_store"),),
                zero_instruction_candidate=True,
            ),
            FiberPatternStep(
                step_id="store_fragment",
                role="tile_store",
                region="post_region",
                attrs=(("subtask_role", "finalize_store"),),
            ),
        ),
    )


__all__ = [
    "FiberPatternPlan",
    "FiberPatternStep",
    "FiberRepeatedRegion",
    "TransitionalPatternId",
    "build_matmul_sequential_reduction_pattern",
]
