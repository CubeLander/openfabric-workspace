"""Chip-level program IR for the refactored DFU-first frontend."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Sequence

from gpdpu_compiler.core.placement_types import Placement


Shape = tuple[int, ...]

DTYPE_SIZE_BYTES = {
    "bool": 1,
    "int8": 1,
    "uint8": 1,
    "int16": 2,
    "uint16": 2,
    "fp16": 2,
    "float16": 2,
    "bf16": 2,
    "int32": 4,
    "uint32": 4,
    "fp32": 4,
    "float32": 4,
}


@dataclass(frozen=True)
class LogicalFabric:
    """A logical SPMD execution fabric, not a vendor PE topology."""

    name: str
    kind: str
    shape: Shape
    dim_names: tuple[str, ...]

    def to_plan(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "kind": self.kind,
            "shape": list(self.shape),
            "dim_names": list(self.dim_names),
            "semantics": "logical_spmd_fabric_not_physical_pe_mesh",
        }


@dataclass(frozen=True)
class SRAMTensor:
    """A chip-visible SRAM/SPM tensor declaration."""

    id: str
    name: str
    shape: Shape
    dtype: str
    offset_bytes: int
    layout: str = "contiguous"
    address_space: str = "sram"
    role: str = "input"
    nbytes: int | None = None

    def to_plan(self) -> dict[str, Any]:
        nbytes = self.nbytes if self.nbytes is not None else tensor_nbytes(self.shape, self.dtype)
        return {
            "id": self.id,
            "name": self.name,
            "shape": list(self.shape),
            "dtype": self.dtype,
            "offset_bytes": self.offset_bytes,
            "nbytes": nbytes,
            "region": {
                "address_space": self.address_space,
                "offset_bytes": self.offset_bytes,
                "nbytes": nbytes,
                "end_offset_bytes": self.offset_bytes + nbytes,
            },
            "layout": self.layout,
            "address_space": self.address_space,
            "role": self.role,
        }


@dataclass(frozen=True)
class LogicalDTensor:
    """A logical distributed tensor value loaded from or computed on chip."""

    id: str
    name: str
    env: Any
    shape: Shape
    dtype: str
    placements: tuple[Placement, ...]
    fabric: LogicalFabric
    producer_op: str | None = None
    source_sram: str | None = None
    task_axis_placement: dict[str, Any] | None = None

    def __matmul__(self, other: "LogicalDTensor") -> "LogicalDTensor":
        from gpdpu_compiler.core import ops

        return ops.matmul(self, other)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "shape": list(self.shape),
            "dtype": self.dtype,
            "placements": [
                *(
                    [self.task_axis_placement["repr"]]
                    if self.task_axis_placement is not None
                    else []
                ),
                *[repr(placement) for placement in self.placements],
            ],
            "physical_placements": [repr(placement) for placement in self.placements],
            "task_axis_placement": self.task_axis_placement,
            "fabric": self.fabric.name,
            "producer_op": self.producer_op,
            "source_sram": self.source_sram,
        }


@dataclass(frozen=True)
class ChipOp:
    """One chip-level logical operation."""

    id: str
    op: str
    inputs: tuple[str, ...] = ()
    outputs: tuple[str, ...] = ()
    attrs: dict[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "op": self.op,
            "inputs": list(self.inputs),
            "outputs": list(self.outputs),
            "attrs": self.attrs,
        }


@dataclass
class ChipProgram:
    """Frontend program before tile/fabric/DFU physical lowering."""

    name: str
    execution_model: str = "spmd"
    fabrics: dict[str, LogicalFabric] = field(default_factory=dict)
    sram_tensors: dict[str, SRAMTensor] = field(default_factory=dict)
    dtensors: dict[str, LogicalDTensor] = field(default_factory=dict)
    ops: list[ChipOp] = field(default_factory=list)
    outputs: dict[str, str] = field(default_factory=dict)
    task_axis_mesh: dict[str, Any] | None = None
    task_axis_placements: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": 1,
            "program": self.name,
            "ir": "chip_program",
            "execution_model": self.execution_model,
            "layering_policy": (
                "frontend_records_chip_level_program_only;"
                "processor_logical_lowering_starts_after_generate;"
                "processor_tile_lowering_follows_processor_logical_program;"
                "dfu_lowering_follows_processor_tile_program"
            ),
            "fabrics": {
                name: fabric.to_plan()
                for name, fabric in sorted(self.fabrics.items())
            },
            "sram_tensors": {
                tensor_id: tensor.to_plan()
                for tensor_id, tensor in sorted(self.sram_tensors.items())
            },
            "dtensors": {
                tensor_id: tensor.to_plan()
                for tensor_id, tensor in sorted(self.dtensors.items())
            },
            "ops": [op.to_plan() for op in self.ops],
            "outputs": dict(sorted(self.outputs.items())),
            "task_axis_mesh": self.task_axis_mesh,
            "task_axis_placements": dict(sorted(self.task_axis_placements.items())),
            "totals": {
                "fabric_count": len(self.fabrics),
                "sram_tensor_count": len(self.sram_tensors),
                "dtensor_count": len(self.dtensors),
                "op_count": len(self.ops),
                "output_count": len(self.outputs),
            },
        }


def normalize_shape(shape: Sequence[int]) -> Shape:
    return tuple(int(dim) for dim in shape)


def tensor_nbytes(shape: Shape, dtype: str) -> int:
    if dtype not in DTYPE_SIZE_BYTES:
        raise ValueError(f"unknown dtype size for SRAM tensor: {dtype}")
    element_count = 1
    for dim in shape:
        element_count *= dim
    return element_count * DTYPE_SIZE_BYTES[dtype]
