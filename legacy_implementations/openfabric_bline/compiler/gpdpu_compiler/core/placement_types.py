"""Placement metadata for chip-level logical tensors.

These are intentionally small DTensor-style placement descriptors used by the
DFU-first frontend and processor lowering. Runtime collective execution remains
a later compiler/backend concern.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, cast


class Placement:
    """Base class for logical tensor placements."""

    def is_shard(self, dim: Optional[int] = None) -> bool:
        is_shard_instance = isinstance(self, Shard)
        if dim is not None and is_shard_instance:
            return cast(Shard, self).dim == dim
        return is_shard_instance

    def is_replicate(self) -> bool:
        return isinstance(self, Replicate)

    def is_partial(self) -> bool:
        return isinstance(self, Partial)


@dataclass(frozen=True)
class Shard(Placement):
    """Shard a tensor dimension across the corresponding fabric dimension."""

    dim: int

    def __repr__(self) -> str:
        return f"Shard({self.dim})"


@dataclass(frozen=True)
class Replicate(Placement):
    """Replicate a tensor across the corresponding fabric dimension."""

    def __repr__(self) -> str:
        return "Replicate()"


@dataclass(frozen=True)
class Partial(Placement):
    """Mark a tensor as holding a pending reduction on a fabric dimension."""

    reduce_op: str = "sum"

    def __repr__(self) -> str:
        return f"Partial({self.reduce_op!r})"


__all__ = ["Partial", "Placement", "Replicate", "Shard"]
