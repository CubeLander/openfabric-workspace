"""Refactored chip-level frontend environment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Sequence

from gpdpu_compiler.core.dfu3500 import (
    DFU3500_CHIP_CONFIG,
    DFU3500SRAMRegion,
    VendorRuntimeProfile,
    chip_config_to_plan,
    default_logical_fabric,
)
from gpdpu_compiler.core.placement_types import Placement
from gpdpu_compiler.core.program import (
    ChipOp,
    ChipProgram,
    LogicalDTensor,
    LogicalFabric,
    SRAMTensor,
    normalize_shape,
    tensor_nbytes,
)
from gpdpu_compiler.core.program_app import (
    AppPlan,
)
from gpdpu_compiler.core.dfu3500.legacy_templates import (
    lower_tile_micro_ops_to_dfu3500_template_bound,
)
from gpdpu_compiler.core.program_runtime import assign_app_plan_to_runtime_packages
from gpdpu_compiler.core.logical_plan import LogicalPlan
from gpdpu_compiler.core.program_task_partition import (
    TaskAxisPlacement,
    TaskPartial,
    TaskPartitionPlan,
)
from gpdpu_compiler.core.program_nodes import lower_processor_tile_to_program_nodes
from gpdpu_compiler.core.program_micro_ops import lower_processor_tile_to_micro_ops
from gpdpu_compiler.core.program_packing import lower_program_nodes_to_dfu_packing
from gpdpu_compiler.core.program_asm import lower_dfu_packing_to_program_asm
from gpdpu_compiler.core.program_bin import (
    VendorInstMode,
    lower_vendor_abi_to_program_bin_rows,
)
from gpdpu_compiler.core.program_serializer import lower_program_bin_rows_to_components
from gpdpu_compiler.core.program_vendor_abi import lower_program_asm_to_vendor_abi
from gpdpu_compiler.core.program_tile import lower_processor_logical_to_tile_program
from gpdpu_compiler.core.dfu3500.task_resource_replay import (
    replay_legacy_task_resource,
)


class ChipEnv:
    """Record a chip-level SPMD program before any DFU physical lowering."""

    def __init__(self, name: str, *, chip: dict[str, Any] | None = None) -> None:
        self.name = name
        self.chip = chip or DFU3500_CHIP_CONFIG
        self.program = ChipProgram(name=name)
        self._fabric_counter = 0
        self._sram_counter = 0
        self._dtensor_counter = 0
        self._op_counter = 0
        fabric_cfg = default_logical_fabric(self.chip)
        shape_tuple = normalize_shape(fabric_cfg["shape"])
        dim_names_tuple = tuple(str(dim) for dim in fabric_cfg["dim_names"])
        if len(dim_names_tuple) != len(shape_tuple):
            raise ValueError("fabric dim_names rank must match shape rank")
        self._chip_fabric = LogicalFabric(
            name=str(fabric_cfg["name"]),
            kind=str(fabric_cfg["kind"]),
            shape=shape_tuple,
            dim_names=dim_names_tuple,
        )
        self.program.fabrics[self._chip_fabric.name] = self._chip_fabric

    def sram_tensor(
        self,
        name: str,
        *,
        shape: Sequence[int],
        dtype: str,
        offset_bytes: int,
        layout: str = "contiguous",
        role: str = "input",
        nbytes: int | None = None,
    ) -> SRAMTensor:
        tensor_id = f"sram_{self._sram_counter:04d}"
        self._sram_counter += 1
        shape_tuple = normalize_shape(shape)
        region_nbytes = nbytes if nbytes is not None else tensor_nbytes(shape_tuple, dtype)
        tensor = SRAMTensor(
            id=tensor_id,
            name=name,
            shape=shape_tuple,
            dtype=dtype,
            offset_bytes=int(offset_bytes),
            layout=layout,
            role=role,
            nbytes=region_nbytes,
        )
        self.program.sram_tensors[tensor.id] = tensor
        self._append_op(
            "declare_sram_tensor",
            outputs=[tensor.id],
            attrs={
                "name": tensor.name,
                "shape": list(tensor.shape),
                "dtype": tensor.dtype,
                "layout": tensor.layout,
                "role": tensor.role,
                "region": self._sram_region(tensor),
            },
        )
        return tensor

    def sram_tensor_from_region(
        self,
        name: str,
        region: DFU3500SRAMRegion,
        *,
        shape: Sequence[int] | None = None,
        dtype: str | None = None,
        role: str | None = None,
        layout: str | None = None,
    ) -> SRAMTensor:
        if shape is None:
            if region.shape is None:
                raise ValueError(f"region does not define a tensor shape: {region.name}")
            shape = region.shape
        if dtype is None:
            if region.dtype is None:
                raise ValueError(f"region does not define a tensor dtype: {region.name}")
            dtype = region.dtype
        return self.sram_tensor(
            name,
            shape=shape,
            dtype=dtype,
            offset_bytes=region.offset_bytes,
            layout=layout or region.layout,
            role=role or region.role,
            nbytes=region.nbytes,
        )

    def load(
        self,
        tensor: SRAMTensor,
        *,
        placements: Sequence[Placement | TaskAxisPlacement],
        name: str | None = None,
    ) -> LogicalDTensor:
        self._require_sram_tensor(tensor)
        fabric = self._chip_fabric
        self._require_fabric(fabric)
        task_axis_placement, physical_placements = self._split_task_axis_placements(
            placements
        )
        dtensor = self._new_dtensor(
            name=name or tensor.name,
            shape=tensor.shape,
            dtype=tensor.dtype,
            placements=physical_placements,
            fabric=fabric,
            source_sram=tensor.id,
            task_axis_placement=(
                self._task_axis_placement_payload(task_axis_placement)
                if task_axis_placement is not None
                else None
            ),
        )
        if task_axis_placement is not None:
            self.program.task_axis_placements[dtensor.id] = (
                task_axis_placement.to_plan()
            )
        op = self._append_op(
            "load_sram_tensor",
            inputs=[tensor.id],
            outputs=[dtensor.id],
            attrs={"fabric": fabric.name, "src_region": self._sram_region(tensor)},
        )
        self._replace_dtensor(
            dtensor,
            LogicalDTensor(
                id=dtensor.id,
                name=dtensor.name,
                env=self,
                shape=dtensor.shape,
                dtype=dtensor.dtype,
                placements=dtensor.placements,
                fabric=dtensor.fabric,
                producer_op=op.id,
                source_sram=dtensor.source_sram,
                task_axis_placement=dtensor.task_axis_placement,
            ),
        )
        return self.program.dtensors[dtensor.id]

    def store(self, tensor: LogicalDTensor, dst: SRAMTensor) -> SRAMTensor:
        self._require_dtensor(tensor)
        self._require_sram_tensor(dst)
        if tensor.shape != dst.shape:
            raise ValueError(f"store shape mismatch: {tensor.shape} -> {dst.shape}")
        if tensor.dtype != dst.dtype:
            raise ValueError(f"store dtype mismatch: {tensor.dtype} -> {dst.dtype}")
        self._append_op(
            "store_sram_tensor",
            inputs=[tensor.id],
            outputs=[dst.id],
            attrs={"fabric": tensor.fabric.name, "dst_region": self._sram_region(dst)},
        )
        return dst

    def output(self, name: str, tensor: SRAMTensor) -> SRAMTensor:
        self._require_sram_tensor(tensor)
        self.program.outputs[name] = tensor.id
        return tensor

    def configure_task_axis(
        self,
        *,
        task_axis_size: int,
        physical_mesh_shape: Sequence[int] | None = None,
        axis_name: str = "task",
    ) -> None:
        """Declare the restricted soft task axis for later task partitioning."""

        task_axis_size = int(task_axis_size)
        if task_axis_size <= 0:
            raise ValueError("task_axis_size must be positive")
        physical_shape = (
            normalize_shape(physical_mesh_shape)
            if physical_mesh_shape is not None
            else self._chip_fabric.shape
        )
        if physical_shape != self._chip_fabric.shape:
            raise ValueError(
                "task-axis physical_mesh_shape must match chip logical fabric "
                f"shape: {physical_shape} != {self._chip_fabric.shape}"
            )
        self.program.task_axis_mesh = {
            "axis_name": axis_name,
            "task_axis_size": task_axis_size,
            "physical_mesh_shape": list(physical_shape),
            "physical_mesh_dim_names": list(self._chip_fabric.dim_names),
            "semantics": (
                "restricted_soft_task_axis_no_implicit_cross_task_visibility"
            ),
        }

    def set_task_placement(
        self,
        tensor: LogicalDTensor,
        placement: TaskAxisPlacement,
    ) -> LogicalDTensor:
        """Attach a manual task-axis placement requirement to a logical tensor."""

        self._require_dtensor(tensor)
        if self.program.task_axis_mesh is None:
            raise ValueError(
                "configure_task_axis(...) must be called before set_task_placement"
            )
        if isinstance(placement, TaskPartial):
            raise ValueError(
                "TaskPartial is not allowed on the task axis in the current "
                "runnable path; resolve or reject it before lowering"
            )
        self.program.task_axis_placements[tensor.id] = placement.to_plan()
        updated = LogicalDTensor(
            id=tensor.id,
            name=tensor.name,
            env=self,
            shape=tensor.shape,
            dtype=tensor.dtype,
            placements=tensor.placements,
            fabric=tensor.fabric,
            producer_op=tensor.producer_op,
            source_sram=tensor.source_sram,
            task_axis_placement=self._task_axis_placement_payload(placement),
        )
        self._replace_dtensor(tensor, updated)
        return self.program.dtensors[tensor.id]

    def set_task_partition(
        self,
        tensor: LogicalDTensor,
        placement: TaskAxisPlacement,
    ) -> LogicalDTensor:
        """Alias for set_task_placement while the API wording settles."""

        return self.set_task_placement(tensor, placement)

    def temp_dtensor(
        self,
        *,
        name: str,
        shape: Sequence[int],
        dtype: str,
        placements: Sequence[Placement],
        fabric: LogicalFabric,
        producer_op: str | None = None,
        task_axis_placement: dict[str, Any] | None = None,
    ) -> LogicalDTensor:
        self._require_fabric(fabric)
        return self._new_dtensor(
            name=name,
            shape=normalize_shape(shape),
            dtype=dtype,
            placements=tuple(placements),
            fabric=fabric,
            producer_op=producer_op,
            task_axis_placement=task_axis_placement,
        )

    def append_compute_op(
        self,
        op: str,
        *,
        inputs: Sequence[LogicalDTensor],
        outputs: Sequence[LogicalDTensor],
        attrs: dict[str, Any] | None = None,
    ) -> ChipOp:
        for tensor in inputs:
            self._require_dtensor(tensor)
        for tensor in outputs:
            self._require_dtensor(tensor)
        chip_op = self._append_op(
            op,
            inputs=[tensor.id for tensor in inputs],
            outputs=[tensor.id for tensor in outputs],
            attrs=attrs or {},
        )
        for tensor in outputs:
            self._replace_dtensor(
                tensor,
                LogicalDTensor(
                    id=tensor.id,
                    name=tensor.name,
                    env=self,
                    shape=tensor.shape,
                    dtype=tensor.dtype,
                    placements=tensor.placements,
                    fabric=tensor.fabric,
                    producer_op=chip_op.id,
                    source_sram=tensor.source_sram,
                    task_axis_placement=tensor.task_axis_placement,
                ),
            )
        return chip_op

    def to_chip_plan(self) -> dict[str, Any]:
        return self.program.to_plan()

    def generate(
        self,
        output_dir: str | Path | None = None,
        *,
        vendor_inst_mode: VendorInstMode = "native_symbolic",
    ) -> dict[str, Any]:
        runtime_profile = self.chip.get("runtime_profile")
        if not isinstance(runtime_profile, VendorRuntimeProfile):
            raise ValueError(
                "chip config must provide a dfu3500 VendorRuntimeProfile "
                "under key 'runtime_profile'"
            )
        app_plan = AppPlan(self.program)
        task_partition_plan = TaskPartitionPlan(app_plan, self.chip)
        runtime_package_assignment = assign_app_plan_to_runtime_packages(
            app_plan,
            runtime_profile,
        )
        processor_program = LogicalPlan(
            app_plan,
            self.chip,
            task_partition_plan=task_partition_plan,
        )
        tile_program = lower_processor_logical_to_tile_program(
            processor_program,
            self.chip,
            app_plan=app_plan,
        )
        tile_micro_op_program = lower_processor_tile_to_micro_ops(tile_program)
        dfu3500_template_bound_program = lower_tile_micro_ops_to_dfu3500_template_bound(
            tile_micro_op_program
        )
        node_program = lower_processor_tile_to_program_nodes(tile_program)
        packing_program = lower_program_nodes_to_dfu_packing(node_program)
        asm_program = lower_dfu_packing_to_program_asm(
            packing_program,
            node_program,
            template_bound_program=dfu3500_template_bound_program,
        )
        vendor_abi_program = lower_program_asm_to_vendor_abi(asm_program)
        if vendor_inst_mode == "legacy_gemm_compat":
            vendor_abi_program = replay_legacy_task_resource(vendor_abi_program)
        bin_rows_program = lower_vendor_abi_to_program_bin_rows(
            vendor_abi_program,
            vendor_inst_mode=vendor_inst_mode,
        )
        bin_components_program = lower_program_bin_rows_to_components(bin_rows_program)
        plan = {
            "schema_version": 1,
            "compiler": "openfabric_dfu_first_refactor",
            "status": _generate_status(vendor_inst_mode),
            "vendor_inst_mode": vendor_inst_mode,
            "chip": chip_config_to_plan(self.chip),
            "chip_program": self.to_chip_plan(),
            "app_plan": app_plan.to_plan(),
            "task_partition_plan": task_partition_plan.to_plan(),
            "runtime_package_assignment": runtime_package_assignment.to_plan(),
            "processor_logical_program": processor_program.to_plan(),
            "processor_tile_program": tile_program.to_plan(),
            "tile_micro_op_program": tile_micro_op_program.to_plan(),
            "dfu3500_template_bound_program": dfu3500_template_bound_program.to_plan(),
            "program_nodes": node_program.to_plan(),
            "dfu_packing_program": packing_program.to_plan(),
            "program_asm": asm_program.to_plan(),
            "program_vendor_abi": vendor_abi_program.to_plan(),
            "program_bin_rows": bin_rows_program.to_plan(),
            "program_bin_components": bin_components_program.to_plan(),
        }
        if output_dir is not None:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            bin_components_program.write_to(output_path)
            (output_path / "chip_program.json").write_text(
                json.dumps(plan, indent=2, sort_keys=True) + "\n",
                encoding="utf-8",
            )
        return plan

    def _new_dtensor(
        self,
        *,
        name: str,
        shape: Sequence[int],
        dtype: str,
        placements: tuple[Placement, ...],
        fabric: LogicalFabric,
        producer_op: str | None = None,
        source_sram: str | None = None,
        task_axis_placement: dict[str, Any] | None = None,
    ) -> LogicalDTensor:
        tensor_id = f"dtensor_{self._dtensor_counter:04d}"
        self._dtensor_counter += 1
        tensor = LogicalDTensor(
            id=tensor_id,
            name=name,
            env=self,
            shape=normalize_shape(shape),
            dtype=dtype,
            placements=placements,
            fabric=fabric,
            producer_op=producer_op,
            source_sram=source_sram,
            task_axis_placement=task_axis_placement,
        )
        self.program.dtensors[tensor.id] = tensor
        if task_axis_placement is not None:
            self.program.task_axis_placements[tensor.id] = {
                key: value
                for key, value in task_axis_placement.items()
                if key != "repr"
            }
        return tensor

    def _split_task_axis_placements(
        self,
        placements: Sequence[Placement | TaskAxisPlacement],
    ) -> tuple[TaskAxisPlacement | None, tuple[Placement, ...]]:
        # TODO(task-mesh-order): Current high-level API fixes the soft mesh order
        # as [task, pe_row, pe_col].  Future strategy search should make mesh-axis
        # order configurable, but only after task-axis legality and transform
        # rules are explicit.  Until then, only axis 0 may carry TaskAxisPlacement.
        if not placements:
            raise ValueError("placements must be non-empty")
        first = placements[0]
        if isinstance(first, TaskAxisPlacement):
            if self.program.task_axis_mesh is None:
                raise ValueError(
                    "3D task-axis placements require configure_task_axis(...) first"
                )
            if isinstance(first, TaskPartial):
                raise ValueError(
                    "TaskPartial is not allowed in placement axis 0 yet; "
                    "task-axis transforms/reductions must be resolved before lowering"
                )
            physical = tuple(placements[1:])
            if len(physical) != len(self._chip_fabric.shape):
                raise ValueError(
                    "3D placements must be [task_axis, *physical_mesh_axes]; "
                    f"got {len(placements)} entries for physical rank "
                    f"{len(self._chip_fabric.shape)}"
                )
        else:
            physical = tuple(placements)
            if any(isinstance(placement, TaskAxisPlacement) for placement in physical):
                raise TypeError("only placement axis 0 may use TaskAxisPlacement")
            if len(physical) != len(self._chip_fabric.shape):
                raise ValueError(
                    f"physical placements rank must match chip fabric rank: "
                    f"{len(physical)} != {len(self._chip_fabric.shape)}"
                )
        if not all(isinstance(placement, Placement) for placement in physical):
            raise TypeError("only placement axis 0 may use TaskAxisPlacement")
        return (
            first if isinstance(first, TaskAxisPlacement) else None,
            physical,
        )  # type: ignore[return-value]

    def _task_axis_placement_payload(
        self,
        placement: TaskAxisPlacement,
    ) -> dict[str, Any]:
        return {
            "repr": repr(placement),
            **placement.to_plan(),
        }

    def _replace_dtensor(self, old: LogicalDTensor, new: LogicalDTensor) -> None:
        if old.id not in self.program.dtensors:
            raise ValueError(f"unknown dtensor: {old.id}")
        self.program.dtensors[old.id] = new

    def _append_op(
        self,
        op: str,
        *,
        inputs: Sequence[str] = (),
        outputs: Sequence[str] = (),
        attrs: dict[str, Any] | None = None,
    ) -> ChipOp:
        chip_op = ChipOp(
            id=f"chip_op_{self._op_counter:04d}",
            op=op,
            inputs=tuple(inputs),
            outputs=tuple(outputs),
            attrs=attrs or {},
        )
        self._op_counter += 1
        self.program.ops.append(chip_op)
        return chip_op

    def _require_fabric(self, fabric: LogicalFabric) -> None:
        if self.program.fabrics.get(fabric.name) is not fabric:
            raise ValueError(f"fabric does not belong to this ChipEnv: {fabric.name}")

    def _require_sram_tensor(self, tensor: SRAMTensor) -> None:
        if self.program.sram_tensors.get(tensor.id) != tensor:
            raise ValueError(f"SRAM tensor does not belong to this ChipEnv: {tensor.id}")

    def _require_dtensor(self, tensor: LogicalDTensor) -> None:
        if tensor.env is not self or tensor.id not in self.program.dtensors:
            raise ValueError(f"DTensor does not belong to this ChipEnv: {tensor.id}")

    def _sram_region(self, tensor: SRAMTensor) -> dict[str, int | str]:
        nbytes = tensor.nbytes if tensor.nbytes is not None else tensor_nbytes(tensor.shape, tensor.dtype)
        return {
            "address_space": tensor.address_space,
            "offset_bytes": tensor.offset_bytes,
            "nbytes": nbytes,
            "end_offset_bytes": tensor.offset_bytes + nbytes,
        }


def _generate_status(vendor_inst_mode: VendorInstMode) -> str:
    if vendor_inst_mode == "legacy_gemm_compat":
        return "program_bin_package_legacy_gemm_compat_ready_runtime_validation_blocked"
    if vendor_inst_mode == "legacy_template_compat":
        return "program_bin_package_legacy_template_compat_ready_runtime_validation_blocked"
    return "program_bin_package_structural_smoke_ready_functional_blocked"
