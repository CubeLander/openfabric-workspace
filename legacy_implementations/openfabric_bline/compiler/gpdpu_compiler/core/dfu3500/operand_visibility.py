"""DFU3500 processor-level operand visibility route policies.

These policies are backend schedule decisions derived from operand placements,
logical lowering hints, and the current DFU3500 mesh.  They intentionally live
outside op specs: ops describe data relationships; this module decides how the
current DFU3500 processor lowering makes operands visible.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class Dfu3500OperandVisibilityRoute:
    operand_index: int
    operand_role: Literal["A", "B"]
    route_kind: Literal["row_broadcast", "column_broadcast"]
    visibility_kind: Literal["row_visibility", "column_visibility"]
    fabric_scope: Literal["row", "column"]
    group_dim: int
    axis_name: Literal["row", "col"]


@dataclass(frozen=True)
class Dfu3500OperandVisibilityPolicy:
    operand_routes: tuple[Dfu3500OperandVisibilityRoute, ...]


def dfu3500_summa_operand_visibility_policy() -> Dfu3500OperandVisibilityPolicy:
    """Return the current DFU3500 SUMMA operand visibility plan."""

    return Dfu3500OperandVisibilityPolicy(
        operand_routes=(
            Dfu3500OperandVisibilityRoute(
                operand_index=0,
                operand_role="A",
                route_kind="row_broadcast",
                visibility_kind="row_visibility",
                fabric_scope="row",
                group_dim=0,
                axis_name="row",
            ),
            Dfu3500OperandVisibilityRoute(
                operand_index=1,
                operand_role="B",
                route_kind="column_broadcast",
                visibility_kind="column_visibility",
                fabric_scope="column",
                group_dim=1,
                axis_name="col",
            ),
        )
    )


def dfu3500_operand_visibility_policy_for(
    *,
    lowering_hint: str | None,
    operand_count: int,
) -> Dfu3500OperandVisibilityPolicy | None:
    """Return operand visibility routing required by a lowered compute action.

    The resolver is keyed by the already-selected lowering strategy, not by the
    frontend op name.  For the current DFU path, ``dfu_summa_gemm`` requires two
    operands to be made visible through the SUMMA row/column policy.
    """

    if lowering_hint == "dfu_summa_gemm" and operand_count == 2:
        return dfu3500_summa_operand_visibility_policy()
    return None


__all__ = [
    "Dfu3500OperandVisibilityPolicy",
    "Dfu3500OperandVisibilityRoute",
    "dfu3500_operand_visibility_policy_for",
    "dfu3500_summa_operand_visibility_policy",
]
