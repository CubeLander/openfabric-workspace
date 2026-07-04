"""Consumer binding report for log10max ring GlobalMax visibility.

This is a narrow B-line bridge between the delivery-scoped ring movement and
the existing flat log10max FiberOp chain.  It does not create communication IR
or binary rows; it only records that each postprocess consumer has a concrete
``global_max_ready`` source token before ``max_with_floor_tile`` consumes the
GlobalMax operand.
"""

from __future__ import annotations

from dataclasses import dataclass

from .fiber import Fiber
from .log10max_fiber_chain import build_log10max_production_fiber
from .log10max_ring_fiber_projection import (
    Log10MaxRingFiberProjectionReport,
    build_log10max_ring_fiber_projection_report,
)
from .log10max_ring_plan import (
    Log10MaxRingPlanReport,
    build_log10max_task_local_ring_plan,
)


@dataclass(frozen=True)
class GlobalMaxConsumerBindingRecord:
    """One consumer PE binding from ring-ready token to postprocess operand."""

    consumer_id: str
    ready_token: str
    consumer_fiber_op_id: str
    consumer_fiber_op_kind: str
    destination_operand: str
    depends_on_global_max_ready: bool
    symbolic_global_max_reaches_postprocess: bool

    @property
    def runtime_ready(self) -> bool:
        return (
            self.consumer_fiber_op_kind == "max_with_floor_tile"
            and self.destination_operand == "GlobalMax"
            and self.depends_on_global_max_ready
            and not self.symbolic_global_max_reaches_postprocess
        )

    def to_plan(self) -> dict[str, object]:
        return {
            "consumer_id": self.consumer_id,
            "ready_token": self.ready_token,
            "consumer_fiber_op_id": self.consumer_fiber_op_id,
            "consumer_fiber_op_kind": self.consumer_fiber_op_kind,
            "destination_operand": self.destination_operand,
            "depends_on_global_max_ready": self.depends_on_global_max_ready,
            "symbolic_global_max_reaches_postprocess": (
                self.symbolic_global_max_reaches_postprocess
            ),
            "runtime_ready": self.runtime_ready,
        }


@dataclass(frozen=True)
class GlobalMaxConsumerBindingReport:
    """Fail-closed report for postprocess GlobalMax consumption."""

    profile_id: str
    records: tuple[GlobalMaxConsumerBindingRecord, ...]
    projection_runtime_ready: bool
    diagnostics: tuple[str, ...]

    @property
    def runtime_ready(self) -> bool:
        return (
            self.projection_runtime_ready
            and not self.diagnostics
            and bool(self.records)
            and all(record.runtime_ready for record in self.records)
        )

    @property
    def blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        if not self.projection_runtime_ready:
            blockers.append("global_max_ready_projection_not_runtime_ready")
        if not self.records:
            blockers.append("consumer_global_max_binding_missing")
        for diagnostic in self.diagnostics:
            blockers.append(diagnostic)
        if any(not record.depends_on_global_max_ready for record in self.records):
            blockers.append("consumer_depends_on_global_ready_missing")
        if any(record.symbolic_global_max_reaches_postprocess for record in self.records):
            blockers.append("symbolic_global_max_reaches_postprocess")
        return tuple(dict.fromkeys(blockers))

    def summary(self) -> dict[str, object]:
        return {
            "profile_id": self.profile_id,
            "record_count": len(self.records),
            "projection_runtime_ready": self.projection_runtime_ready,
            "runtime_ready": self.runtime_ready,
            "blockers": list(self.blockers),
            "diagnostic_count": len(self.diagnostics),
            "consumer_fiber_op_kinds": sorted(
                {record.consumer_fiber_op_kind for record in self.records}
            ),
        }

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact_kind": "log10max_globalmax_consumer_binding_report",
            "summary": self.summary(),
            "runtime_ready": self.runtime_ready,
            "blockers": list(self.blockers),
            "records": [record.to_plan() for record in self.records],
            "diagnostics": list(self.diagnostics),
            "layering_policy": (
                "consumer binding consumes ring global_max_ready tokens and the "
                "existing max_with_floor_tile FiberOp; it does not create "
                "communication IR, template rows, or binary bytes"
            ),
        }


def build_log10max_globalmax_consumer_binding_report(
    ring_report: Log10MaxRingPlanReport | None = None,
    projection_report: Log10MaxRingFiberProjectionReport | None = None,
    consumer_fiber: Fiber | None = None,
    *,
    profile_id: str = "dfu3500_log10max_globalmax_consumer_binding_v1",
) -> GlobalMaxConsumerBindingReport:
    """Build the postprocess consumer binding report."""

    ring = ring_report or build_log10max_task_local_ring_plan()
    projection = projection_report or build_log10max_ring_fiber_projection_report(ring)
    fiber = consumer_fiber or build_log10max_production_fiber()
    diagnostics: list[str] = []

    max_ops = tuple(op for op in fiber.ops if op.op == "max_with_floor_tile")
    if len(max_ops) != 1:
        diagnostics.append("max_with_floor_tile_consumer_not_unique")
        consumer_op = None
    else:
        consumer_op = max_ops[0]
        if not any(fragment.role == "GlobalMax" for fragment in consumer_op.inputs):
            diagnostics.append("max_with_floor_tile_globalmax_operand_missing")
        if not any(
            dependency.via_fragment is not None
            and dependency.via_fragment.role == "GlobalMax"
            for dependency in consumer_op.depends_on
        ):
            diagnostics.append("max_with_floor_tile_globalmax_dependency_missing")

    records: list[GlobalMaxConsumerBindingRecord] = []
    if consumer_op is not None:
        for ready_token in ring.global_max_ready:
            consumer_id = ready_token.split("<-", 1)[0]
            records.append(
                GlobalMaxConsumerBindingRecord(
                    consumer_id=consumer_id,
                    ready_token=ready_token,
                    consumer_fiber_op_id=consumer_op.id,
                    consumer_fiber_op_kind=consumer_op.op,
                    destination_operand="GlobalMax",
                    depends_on_global_max_ready=projection.runtime_ready,
                    symbolic_global_max_reaches_postprocess=(
                        not projection.runtime_ready
                    ),
                )
            )

    return GlobalMaxConsumerBindingReport(
        profile_id=profile_id,
        records=tuple(records),
        projection_runtime_ready=projection.runtime_ready,
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )


def summarize_log10max_globalmax_consumer_binding_report(
    report: GlobalMaxConsumerBindingReport,
) -> dict[str, object]:
    return report.summary()


__all__ = [
    "GlobalMaxConsumerBindingRecord",
    "GlobalMaxConsumerBindingReport",
    "build_log10max_globalmax_consumer_binding_report",
    "summarize_log10max_globalmax_consumer_binding_report",
]
