"""Chip-level logical ops for the refactored frontend."""

from __future__ import annotations

from typing import Sequence

from gpdpu_compiler.core.op_specs import MATMUL_SPEC
from gpdpu_compiler.core.placement_types import Partial, Replicate, Shard
from gpdpu_compiler.core.program import LogicalDTensor


def matmul(lhs: LogicalDTensor, rhs: LogicalDTensor) -> LogicalDTensor:
    _same_env(lhs, rhs)
    _same_fabric(lhs, rhs)
    semantic_contract = MATMUL_SPEC.semantic_contract()
    lowering_contract = MATMUL_SPEC.dfu3500_lowering_contract()
    if len(lhs.shape) != 2 or len(rhs.shape) != 2:
        raise NotImplementedError(
            f"chip matmul currently supports {semantic_contract.shape_rule}"
        )
    if lhs.shape[1] != rhs.shape[0]:
        raise ValueError(f"matmul shape mismatch: {lhs.shape} @ {rhs.shape}")
    if lhs.dtype != rhs.dtype:
        raise ValueError(f"matmul dtype mismatch: {lhs.dtype} vs {rhs.dtype}")

    if (
        lhs.placements != lowering_contract.supported_lhs_placements
        or rhs.placements != lowering_contract.supported_rhs_placements
    ):
        raise NotImplementedError(
            "DFU-first matmul currently expects "
            "lhs placements=[Shard(0), Replicate()] and "
            "rhs placements=[Replicate(), Shard(1)]"
        )

    out = lhs.env.temp_dtensor(
        name=f"{lhs.name}_matmul_{rhs.name}",
        shape=(lhs.shape[0], rhs.shape[1]),
        dtype=lhs.dtype,
        placements=lowering_contract.supported_output_placements,
        fabric=lhs.fabric,
    )
    lhs.env.append_compute_op(
        "matmul",
        inputs=[lhs, rhs],
        outputs=[out],
        attrs=lowering_contract.attrs(),
    )
    return lhs.env.program.dtensors[out.id]


def relu(tensor: LogicalDTensor) -> LogicalDTensor:
    if any(isinstance(placement, Partial) for placement in tensor.placements):
        raise NotImplementedError("relu over Partial tensors needs a reduce first")
    out = tensor.env.temp_dtensor(
        name=f"{tensor.name}_relu",
        shape=tensor.shape,
        dtype=tensor.dtype,
        placements=tensor.placements,
        fabric=tensor.fabric,
        task_axis_placement=tensor.task_axis_placement,
    )
    tensor.env.append_compute_op(
        "relu",
        inputs=[tensor],
        outputs=[out],
        attrs={"execution_model": "spmd"},
    )
    return tensor.env.program.dtensors[out.id]


def add(lhs: LogicalDTensor, rhs: LogicalDTensor) -> LogicalDTensor:
    _same_env(lhs, rhs)
    _same_fabric(lhs, rhs)
    _same_shape_dtype(lhs, rhs, "add")
    out = lhs.env.temp_dtensor(
        name=f"{lhs.name}_add_{rhs.name}",
        shape=lhs.shape,
        dtype=lhs.dtype,
        placements=lhs.placements,
        fabric=lhs.fabric,
        task_axis_placement=lhs.task_axis_placement,
    )
    lhs.env.append_compute_op(
        "add",
        inputs=[lhs, rhs],
        outputs=[out],
        attrs={"execution_model": "spmd"},
    )
    return lhs.env.program.dtensors[out.id]


def clamp_min(tensor: LogicalDTensor, *, min_value: float) -> LogicalDTensor:
    return _unary_elementwise(
        tensor,
        "clamp_min",
        name_suffix="clamp_min",
        attrs={"min_value": float(min_value), "execution_model": "spmd"},
    )


def log10(tensor: LogicalDTensor) -> LogicalDTensor:
    return _unary_elementwise(
        tensor,
        "log10",
        name_suffix="log10",
        attrs={
            "execution_model": "spmd",
            "lowering_hint": "dfu_flog2_times_log10_2",
        },
    )


def maximum(lhs: LogicalDTensor, rhs: LogicalDTensor) -> LogicalDTensor:
    _same_env(lhs, rhs)
    _same_fabric(lhs, rhs)
    if lhs.dtype != rhs.dtype:
        raise ValueError(f"maximum dtype mismatch: {lhs.dtype} vs {rhs.dtype}")
    if lhs.shape == rhs.shape:
        output_shape = lhs.shape
        output_placements = lhs.placements
    elif rhs.shape == () and _is_replicated(rhs):
        output_shape = lhs.shape
        output_placements = lhs.placements
    elif lhs.shape == () and _is_replicated(lhs):
        output_shape = rhs.shape
        output_placements = rhs.placements
    else:
        raise NotImplementedError(
            "maximum currently supports same-shape tensors or replicated scalar broadcast"
        )
    out = lhs.env.temp_dtensor(
        name=f"{lhs.name}_maximum_{rhs.name}",
        shape=output_shape,
        dtype=lhs.dtype,
        placements=output_placements,
        fabric=lhs.fabric,
        task_axis_placement=_merged_task_axis_placement(lhs, rhs),
    )
    lhs.env.append_compute_op(
        "maximum",
        inputs=[lhs, rhs],
        outputs=[out],
        attrs={
            "execution_model": "spmd",
            "broadcast_semantics": "replicated_scalar_or_same_shape",
        },
    )
    return lhs.env.program.dtensors[out.id]


def maximum_scalar(tensor: LogicalDTensor, scalar: float) -> LogicalDTensor:
    return _scalar_elementwise(
        tensor,
        "maximum_scalar",
        name_suffix="maximum_scalar",
        scalar=scalar,
        attrs={"execution_model": "spmd"},
    )


def add_scalar(tensor: LogicalDTensor, scalar: float) -> LogicalDTensor:
    return _scalar_elementwise(
        tensor,
        "add_scalar",
        name_suffix="add_scalar",
        scalar=scalar,
        attrs={"execution_model": "spmd"},
    )


def mul_scalar(tensor: LogicalDTensor, scalar: float) -> LogicalDTensor:
    return _scalar_elementwise(
        tensor,
        "mul_scalar",
        name_suffix="mul_scalar",
        scalar=scalar,
        attrs={"execution_model": "spmd"},
    )


def reduce_sum(tensor: LogicalDTensor, *, axes: Sequence[int]) -> LogicalDTensor:
    axes_tuple = tuple(int(axis) for axis in axes)
    out_shape = tuple(
        dim for index, dim in enumerate(tensor.shape)
        if index not in axes_tuple
    )
    out = tensor.env.temp_dtensor(
        name=f"{tensor.name}_reduce_sum",
        shape=out_shape,
        dtype=tensor.dtype,
        placements=tuple(Replicate() for _ in tensor.placements),
        fabric=tensor.fabric,
        task_axis_placement=tensor.task_axis_placement,
    )
    tensor.env.append_compute_op(
        "reduce_sum",
        inputs=[tensor],
        outputs=[out],
        attrs={"axes": list(axes_tuple), "execution_model": "spmd"},
    )
    return tensor.env.program.dtensors[out.id]


def reduce_max(tensor: LogicalDTensor, *, axes: Sequence[int] | None = None) -> LogicalDTensor:
    axes_tuple = tuple(range(len(tensor.shape))) if axes is None else tuple(int(axis) for axis in axes)
    out_shape = tuple(
        dim for index, dim in enumerate(tensor.shape)
        if index not in axes_tuple
    )
    out = tensor.env.temp_dtensor(
        name=f"{tensor.name}_reduce_max",
        shape=out_shape,
        dtype=tensor.dtype,
        placements=tuple(Replicate() for _ in tensor.placements),
        fabric=tensor.fabric,
        task_axis_placement=tensor.task_axis_placement,
    )
    tensor.env.append_compute_op(
        "reduce_max",
        inputs=[tensor],
        outputs=[out],
        attrs={
            "axes": list(axes_tuple),
            "execution_model": "spmd",
            "collective": "all_reduce_max_when_reducing_sharded_dims",
            "app_boundary_candidate": True,
        },
    )
    return tensor.env.program.dtensors[out.id]


def _unary_elementwise(
    tensor: LogicalDTensor,
    op: str,
    *,
    name_suffix: str,
    attrs: dict[str, object],
) -> LogicalDTensor:
    if any(isinstance(placement, Partial) for placement in tensor.placements):
        raise NotImplementedError(f"{op} over Partial tensors needs a reduce first")
    out = tensor.env.temp_dtensor(
        name=f"{tensor.name}_{name_suffix}",
        shape=tensor.shape,
        dtype=tensor.dtype,
        placements=tensor.placements,
        fabric=tensor.fabric,
        task_axis_placement=tensor.task_axis_placement,
    )
    tensor.env.append_compute_op(
        op,
        inputs=[tensor],
        outputs=[out],
        attrs=dict(attrs),
    )
    return tensor.env.program.dtensors[out.id]


def _scalar_elementwise(
    tensor: LogicalDTensor,
    op: str,
    *,
    name_suffix: str,
    scalar: float,
    attrs: dict[str, object],
) -> LogicalDTensor:
    if any(isinstance(placement, Partial) for placement in tensor.placements):
        raise NotImplementedError(f"{op} over Partial tensors needs a reduce first")
    out = tensor.env.temp_dtensor(
        name=f"{tensor.name}_{name_suffix}",
        shape=tensor.shape,
        dtype=tensor.dtype,
        placements=tensor.placements,
        fabric=tensor.fabric,
        task_axis_placement=tensor.task_axis_placement,
    )
    op_attrs = dict(attrs)
    op_attrs["scalar"] = float(scalar)
    tensor.env.append_compute_op(
        op,
        inputs=[tensor],
        outputs=[out],
        attrs=op_attrs,
    )
    return tensor.env.program.dtensors[out.id]


def _is_replicated(tensor: LogicalDTensor) -> bool:
    return all(isinstance(placement, Replicate) for placement in tensor.placements)


def _same_env(lhs: LogicalDTensor, rhs: LogicalDTensor) -> None:
    if lhs.env is not rhs.env:
        raise ValueError("operands belong to different ChipEnv instances")


def _same_fabric(lhs: LogicalDTensor, rhs: LogicalDTensor) -> None:
    if lhs.fabric != rhs.fabric:
        raise ValueError("operands belong to different logical fabrics")


def _same_shape_dtype(lhs: LogicalDTensor, rhs: LogicalDTensor, op: str) -> None:
    if lhs.shape != rhs.shape:
        raise ValueError(f"{op} shape mismatch: {lhs.shape} vs {rhs.shape}")
    if lhs.dtype != rhs.dtype:
        raise ValueError(f"{op} dtype mismatch: {lhs.dtype} vs {rhs.dtype}")


def _merged_task_axis_placement(
    lhs: LogicalDTensor,
    rhs: LogicalDTensor,
) -> dict[str, object] | None:
    if lhs.task_axis_placement == rhs.task_axis_placement:
        return lhs.task_axis_placement
    if rhs.shape == ():
        return lhs.task_axis_placement
    if lhs.shape == ():
        return rhs.task_axis_placement
    return lhs.task_axis_placement
