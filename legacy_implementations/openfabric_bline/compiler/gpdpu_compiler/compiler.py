"""Current public compiler entry points."""

from __future__ import annotations

from gpdpu_compiler.core import ChipEnv

__all__ = ["ChipEnv"]


def __getattr__(name: str) -> object:
    if name == "OperatorEnv":
        raise ImportError(
            "OperatorEnv was removed with core_legacy. Use "
            "gpdpu_compiler.core.ChipEnv and explicit SRAM load/store instead."
        )
    raise AttributeError(name)
