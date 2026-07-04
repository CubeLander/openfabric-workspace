"""Base interfaces for architecture-owned compiler backends."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class ArchitectureBackend(ABC):
    """Target-owned lowering from tile semantics to symbolic instructions."""

    name: str

    @abstractmethod
    def expand(self, tile_backend: dict[str, Any]) -> dict[str, Any]:
        """Expand a backend-independent tile plan for this architecture."""

    @abstractmethod
    def expand_gemm_tile_update(self, phase: dict[str, Any]) -> dict[str, Any]:
        """Realize one semantic GEMM tile update template."""

    def expand_elementwise_tile(self, _phase: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(f"{self.name} does not implement elementwise tile expansion yet")

    def expand_reduce_tile(self, _phase: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(f"{self.name} does not implement reduce tile expansion yet")

    def expand_materialize_tile(self, _phase: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(f"{self.name} does not implement materialize tile expansion yet")

    def expand_store_tile(self, _phase: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError(f"{self.name} does not implement store tile expansion yet")
