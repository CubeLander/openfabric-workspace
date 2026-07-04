"""DFU3500 chip configuration for the DFU-first frontend.

This module intentionally keeps the current chip facts close to the new
chip-level frontend.  It is not a generic multi-backend abstraction yet; it is
the named configuration for the customer DFU/SimICT target we are serving now.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from gpdpu_compiler.core.program import tensor_nbytes


@dataclass(frozen=True)
class DFU3500SRAMRegion:
    """One named SRAM/SPM region used by chip-level programs."""

    name: str
    offset_bytes: int
    nbytes: int
    role: str
    dtype: str | None = None
    shape: tuple[int, ...] | None = None
    layout: str = "contiguous"
    address_space: str = "sram"
    legacy_base_word32: int | None = None

    @property
    def end_offset_bytes(self) -> int:
        return self.offset_bytes + self.nbytes

    def to_plan(self) -> dict[str, Any]:
        plan = {
            "name": self.name,
            "address_space": self.address_space,
            "offset_bytes": self.offset_bytes,
            "nbytes": self.nbytes,
            "end_offset_bytes": self.end_offset_bytes,
            "role": self.role,
            "layout": self.layout,
        }
        if self.dtype is not None:
            plan["dtype"] = self.dtype
        if self.shape is not None:
            plan["shape"] = list(self.shape)
        if self.legacy_base_word32 is not None:
            plan["legacy_base_word32"] = self.legacy_base_word32
        return plan


@dataclass(frozen=True)
class VendorRuntimeProfile:
    """Runtime/package capacity facts for the current DFU3500 SimICT path."""

    profile_id: str
    max_runtime_apps_per_package: int
    max_task_rows_per_package: int
    max_subtask_rows_per_task: int
    max_subtask_rows_per_package: int
    max_instances_per_subtask: int
    supports_single_package_multi_semantic_app: bool
    supports_multi_package_launch: bool
    supports_inter_package_storage_handoff: bool
    package_policy: str = "single_runtime_app_image"

    def to_plan(self) -> dict[str, Any]:
        return {
            "profile_id": self.profile_id,
            "max_runtime_apps_per_package": self.max_runtime_apps_per_package,
            "max_task_rows_per_package": self.max_task_rows_per_package,
            "max_subtask_rows_per_task": self.max_subtask_rows_per_task,
            "max_subtask_rows_per_package": self.max_subtask_rows_per_package,
            "max_instances_per_subtask": self.max_instances_per_subtask,
            "supports_single_package_multi_semantic_app": (
                self.supports_single_package_multi_semantic_app
            ),
            "supports_multi_package_launch": self.supports_multi_package_launch,
            "supports_inter_package_storage_handoff": (
                self.supports_inter_package_storage_handoff
            ),
            "package_policy": self.package_policy,
        }


def _region(
    name: str,
    *,
    offset_bytes: int,
    shape: tuple[int, ...],
    dtype: str,
    role: str,
    legacy_base_word32: int,
) -> DFU3500SRAMRegion:
    return DFU3500SRAMRegion(
        name=name,
        offset_bytes=offset_bytes,
        nbytes=tensor_nbytes(shape, dtype),
        role=role,
        dtype=dtype,
        shape=shape,
        legacy_base_word32=legacy_base_word32,
    )


DFU3500_LOGICAL_FABRIC = {
    "name": "tile_grid",
    "kind": "grid",
    "shape": (4, 4),
    "dim_names": ("row", "col"),
    "semantics": "logical_spmd_fabric_used_before_dfu_physical_lowering",
}

DFU3500_PHYSICAL_TOPOLOGY = {
    "kind": "mesh",
    "shape": (4, 4),
    "processor_count": 16,
    "processor_ids": tuple(f"processor_{row}_{col}" for row in range(4) for col in range(4)),
    "vendor_pe_ids": tuple(f"PE{row}{col}" for row in range(4) for col in range(4)),
    "pe_count": 16,
    "pe_ids": tuple(f"PE{row}{col}" for row in range(4) for col in range(4)),
    "semantics": "physical_dfu_processor_mesh_for_backend_lowering",
}

DFU3500_VENDOR_LIMITS = {
    "pe_amount": 16,
    "max_tasks": 4,
    "max_subtasks_per_task": 8,
    "max_instances_per_subtask": 2048,
    "base_addr_slots_per_instance": 4,
    "max_inst_amount_per_pe": 4352,
    "max_exe_block": 512,
    "max_exe_block_per_pe": 32,
    "max_task_follow_per_task": 4,
}

DFU3500_SIMICT_LEGACY_RUNTIME_PROFILE = VendorRuntimeProfile(
    profile_id="dfu3500_simict_legacy_single_package",
    max_runtime_apps_per_package=1,
    max_task_rows_per_package=DFU3500_VENDOR_LIMITS["max_tasks"],
    max_subtask_rows_per_task=DFU3500_VENDOR_LIMITS["max_subtasks_per_task"],
    max_subtask_rows_per_package=(
        DFU3500_VENDOR_LIMITS["max_tasks"]
        * DFU3500_VENDOR_LIMITS["max_subtasks_per_task"]
    ),
    max_instances_per_subtask=DFU3500_VENDOR_LIMITS["max_instances_per_subtask"],
    supports_single_package_multi_semantic_app=False,
    supports_multi_package_launch=False,
    supports_inter_package_storage_handoff=False,
)

DFU3500_STRUCT_SIZES = {
    "inst_t": 304,
    "exeBlock_conf_info_t": 520,
    "instance_conf_info_t": 32,
    "task_conf_info_t": 120,
    "sub_task_conf_info_t": 266328,
}

DFU3500_MEMORY_LAYOUT = {
    "address_space": "sram",
    "offset_unit": "bytes",
    "legacy_base_addr_unit": "uint32_words",
    "word_bytes": 4,
    "dtype_default": "fp16",
    "notes": (
        "Current frontend records explicit SRAM/SPM regions. "
        "Legacy instance_conf base_addr values are uint32-word offsets."
    ),
}

DFU3500_GEMM_REGIONS = {
    "A": _region(
        "gemm_input1_a",
        offset_bytes=0x00000,
        shape=(512, 256),
        dtype="fp16",
        role="input",
        legacy_base_word32=0x00000,
    ),
    "B": _region(
        "gemm_input2_b",
        offset_bytes=0x40000,
        shape=(256, 512),
        dtype="fp16",
        role="input",
        legacy_base_word32=0x10000,
    ),
    "C": _region(
        "gemm_input3_c_or_output",
        offset_bytes=0x80000,
        shape=(512, 512),
        dtype="fp16",
        role="output",
        legacy_base_word32=0x20000,
    ),
}

DFU3500_DEFAULT_TILE = {
    "matmul_m": 64,
    "matmul_n": 64,
    "matmul_k": 64,
    "dtype": "fp16",
    "semantics": "current GEMM-oriented compiler default, not a frontend API limit",
}

DFU3500_CHIP_CONFIG = {
    "name": "dfu3500",
    "project_target": "customer_dfu_simict_gpdpu",
    "execution_model": "spmd",
    "logical_fabric": DFU3500_LOGICAL_FABRIC,
    "physical_topology": DFU3500_PHYSICAL_TOPOLOGY,
    "memory_layout": DFU3500_MEMORY_LAYOUT,
    "sram_regions": DFU3500_GEMM_REGIONS,
    "default_tile": DFU3500_DEFAULT_TILE,
    "vendor_limits": DFU3500_VENDOR_LIMITS,
    "struct_sizes": DFU3500_STRUCT_SIZES,
    "runtime_profile": DFU3500_SIMICT_LEGACY_RUNTIME_PROFILE,
}


def chip_config_to_plan(config: dict[str, Any] = DFU3500_CHIP_CONFIG) -> dict[str, Any]:
    """Return a JSON-serializable view of a DFU3500 config."""

    plan: dict[str, Any] = {}
    for key, value in config.items():
        if key == "sram_regions":
            plan[key] = {
                region_name: region.to_plan()
                for region_name, region in sorted(value.items())
            }
        elif isinstance(value, tuple):
            plan[key] = list(value)
        elif isinstance(value, VendorRuntimeProfile):
            plan[key] = value.to_plan()
        elif isinstance(value, dict):
            plan[key] = _to_jsonable(value)
        else:
            plan[key] = value
    return plan


def default_logical_fabric(config: dict[str, Any] = DFU3500_CHIP_CONFIG) -> dict[str, Any]:
    return dict(config["logical_fabric"])


def gemm_region(name: str) -> DFU3500SRAMRegion:
    return DFU3500_GEMM_REGIONS[name]


def _to_jsonable(value: Any) -> Any:
    if isinstance(value, DFU3500SRAMRegion):
        return value.to_plan()
    if isinstance(value, VendorRuntimeProfile):
        return value.to_plan()
    if isinstance(value, tuple):
        return list(value)
    if isinstance(value, dict):
        return {key: _to_jsonable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_to_jsonable(item) for item in value]
    return value


__all__ = [
    "DFU3500_CHIP_CONFIG",
    "DFU3500_DEFAULT_TILE",
    "DFU3500_GEMM_REGIONS",
    "DFU3500_LOGICAL_FABRIC",
    "DFU3500_MEMORY_LAYOUT",
    "DFU3500_PHYSICAL_TOPOLOGY",
    "DFU3500_SIMICT_LEGACY_RUNTIME_PROFILE",
    "DFU3500SRAMRegion",
    "VendorRuntimeProfile",
    "chip_config_to_plan",
    "default_logical_fabric",
    "gemm_region",
]
