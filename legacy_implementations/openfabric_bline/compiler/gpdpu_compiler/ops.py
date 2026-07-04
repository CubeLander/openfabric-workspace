"""Public logical op API for the DFU-first core."""

from gpdpu_compiler.core.ops import (
    add,
    add_scalar,
    clamp_min,
    log10,
    matmul,
    maximum,
    mul_scalar,
    reduce_max,
    reduce_sum,
    relu,
)

__all__ = [
    "add",
    "add_scalar",
    "clamp_min",
    "log10",
    "matmul",
    "maximum",
    "mul_scalar",
    "reduce_max",
    "reduce_sum",
    "relu",
]
