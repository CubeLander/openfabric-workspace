"""Architecture-owned compiler backends.

This package intentionally contains target-specific knowledge that may later
move to private subrepositories or dynamically loaded backend packages.
"""

from gpdpu_compiler.arch.base import ArchitectureBackend
from gpdpu_compiler.arch.legacy_dfu import (
    LegacyDFUBackend,
    build_architecture_backend_plan,
    build_assembly_backend_plan,
)

__all__ = [
    "ArchitectureBackend",
    "LegacyDFUBackend",
    "build_architecture_backend_plan",
    "build_assembly_backend_plan",
]
