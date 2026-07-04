"""GPDPU compiler package."""

from gpdpu_compiler.arch import ArchitectureBackend, LegacyDFUBackend
from gpdpu_compiler.core import (
    ChipEnv,
    DFU3500_GEMM_REGIONS,
    DFU3500SRAMRegion,
    LogicalDTensor,
    Partial,
    Placement,
    Replicate,
    SRAMTensor,
    Shard,
    TaskPartial,
    TaskPartitionPlan,
    TaskReplicate,
    TaskShard,
)

__all__ = [
    "ArchitectureBackend",
    "ChipEnv",
    "DFU3500_GEMM_REGIONS",
    "DFU3500SRAMRegion",
    "LegacyDFUBackend",
    "LogicalDTensor",
    "Partial",
    "Placement",
    "Replicate",
    "SRAMTensor",
    "Shard",
    "TaskPartial",
    "TaskPartitionPlan",
    "TaskReplicate",
    "TaskShard",
]
