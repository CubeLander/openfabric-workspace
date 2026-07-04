"""Declarative operator lowering contracts.

Op specs centralize operator policy, but they must not build downstream IR.
Lowering passes consume these descriptors and construct their own layer's
program objects.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Mapping, Protocol

from gpdpu_compiler.core.placement_types import Placement


class OpView(Protocol):
    """Small read-only op shape accepted by spec methods."""

    id: str
    op: str
    inputs: tuple[str, ...]
    outputs: tuple[str, ...]
    attrs: Mapping[str, Any]


@dataclass(frozen=True)
class MatmulSemanticContract:
    shape_rule: Literal["rank2_mk_kn_to_mn"]
    dtype_policy: Literal["lhs_rhs_same_dtype"]


@dataclass(frozen=True)
class Dfu3500MatmulLoweringContract:
    lowering_kind: Literal["summa_gemm"]
    target: Literal["dfu3500"]
    target_profile_id: str
    supported_lhs_placements: tuple[Placement, ...]
    supported_rhs_placements: tuple[Placement, ...]
    supported_output_placements: tuple[Placement, ...]
    default_lowering_hint: str
    execution_model: Literal["spmd"]

    def attrs(self) -> dict[str, str]:
        return {
            "lowering_hint": self.default_lowering_hint,
            "execution_model": self.execution_model,
        }


@dataclass(frozen=True)
class TaskDecompositionProfile:
    partition_kind: Literal["gemm_output_tiles"]
    max_task_rows: int
    required_subtask_roles: tuple[str, ...]


@dataclass(frozen=True)
class FusionCompatibilityProfile:
    allowed_post_op_kinds: tuple[str, ...]
    dependency_requirement: Literal["tile_local_primary_output_only"]
    forbids_cross_pe_collective: bool
    forbids_app_storage_load: bool
    output_store_position: Literal["after_tile_op_chain"]


@dataclass(frozen=True)
class StateLifetimeProfile:
    value_role: Literal["primary_outputs"]
    state_kind: Literal["APP_LOCAL_EXPLICIT"]
    required_scope: Literal["same_app"]
    proof: str


@dataclass(frozen=True)
class OpParallelProfile:
    primary_schedule_kind: str
    task_decomposition: TaskDecompositionProfile
    fusion: FusionCompatibilityProfile
    state_lifetimes: tuple[StateLifetimeProfile, ...]
    requires_global_merge: bool = False
    result_visibility: Literal["independent_output_tiles"] = "independent_output_tiles"


@dataclass(frozen=True)
class ComputeMicroBlockProfile:
    compute_kind: Literal["accumulator_prepare", "gemm_k_update"]
    micro_block_kind: Literal["accumulator_prepare", "compute_update"]


@dataclass(frozen=True)
class TileLoweringProfile:
    phase_kind: Literal["local_gemm_summa"]
    template_kind: Literal["summa_gemm_64x64x64_fp16"]
    source_compute_kind: Literal["matmul"]
    accumulator_prepare_kind: Literal["accumulator_prepare"]
    k_update_kind: Literal["gemm_k_update"]
    local_prepare_op: Literal["init_c"]
    local_k_stream_op: Literal["stream_k_gemm"]
    local_store_op: Literal["store_c"]
    loop_axis: Literal["K"]
    loop_fold_policy: Literal["vendor_instance_repeat_candidate"]
    loop_closure_shape: Literal["closed_repeated_tile_body"]
    compute_micro_blocks: tuple[ComputeMicroBlockProfile, ...]


__all__ = [
    "Dfu3500MatmulLoweringContract",
    "ComputeMicroBlockProfile",
    "FusionCompatibilityProfile",
    "MatmulSemanticContract",
    "OpView",
    "OpParallelProfile",
    "StateLifetimeProfile",
    "TaskDecompositionProfile",
    "TileLoweringProfile",
]
