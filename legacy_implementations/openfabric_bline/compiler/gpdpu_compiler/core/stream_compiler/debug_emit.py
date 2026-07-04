"""Debug row artifact emitter for B-line BinaryLayoutPlan.

This is not a vendor binary emitter.  It serializes the already-decided
`BinaryLayoutPlan` into stable JSON-shaped row artifacts so reviewers can diff
the quasi-binary contract before any byte writer exists.
"""

from __future__ import annotations

from dataclasses import dataclass

from .binary_plan import BinaryLayoutPlan
from .template_ops import Diagnostic


@dataclass(frozen=True)
class DebugRowArtifact:
    """Stable debug artifact derived from BinaryLayoutPlan."""

    profile_id: str
    runnability_state: str
    instruction_rows: tuple[dict[str, object], ...]
    zero_boundaries: tuple[dict[str, object], ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_debug_row_artifact",
            "profile_id": self.profile_id,
            "runnability_state": self.runnability_state,
            "instruction_rows": list(self.instruction_rows),
            "zero_boundaries": list(self.zero_boundaries),
            "diagnostics": [
                diagnostic.to_plan() for diagnostic in self.diagnostics
            ],
            "layering_policy": (
                "debug_row_artifact_consumes_binary_layout_plan;"
                "does_not_emit_vendor_binary_bytes"
            ),
        }


def emit_debug_row_artifact(layout: BinaryLayoutPlan) -> DebugRowArtifact:
    """Emit stable debug rows from an emittable-debug layout."""

    diagnostics = list(layout.diagnostics)
    if layout.runnability_state != "emittable_debug":
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="debug_emit_requires_emittable_debug",
                subject_id="BinaryLayoutPlan",
                message=(
                    "debug row artifact requires an emittable_debug layout; "
                    f"got {layout.runnability_state}"
                ),
            )
        )
    if layout.validation_status != "valid":
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="debug_emit_requires_valid_layout",
                subject_id="BinaryLayoutPlan",
                message=f"debug row artifact requires valid layout; got {layout.validation_status}",
            )
        )
    if any(diagnostic.severity == "error" for diagnostic in diagnostics):
        return DebugRowArtifact(
            profile_id=layout.profile_id,
            runnability_state=layout.runnability_state,
            instruction_rows=(),
            zero_boundaries=(),
            diagnostics=tuple(diagnostics),
        )
    return DebugRowArtifact(
        profile_id=layout.profile_id,
        runnability_state=layout.runnability_state,
        instruction_rows=tuple(
            _instruction_row_artifact(row)
            for row in layout.instruction_rows
        ),
        zero_boundaries=tuple(
            _zero_boundary_artifact(boundary)
            for boundary in layout.zero_instruction_boundaries
        ),
        diagnostics=tuple(diagnostics),
    )


def summarize_debug_row_artifact(artifact: DebugRowArtifact) -> dict[str, object]:
    """Return stable counts for checks and reports."""

    opcode_counts: dict[str, int] = {}
    role_counts: dict[str, int] = {}
    zero_role_counts: dict[str, int] = {}
    diagnostic_severity_counts: dict[str, int] = {}
    forbidden_tile_micro_block_fields = 0
    missing_template_provenance_count = 0
    missing_fiber_provenance_count = 0

    for diagnostic in artifact.diagnostics:
        diagnostic_severity_counts[diagnostic.severity] = (
            diagnostic_severity_counts.get(diagnostic.severity, 0) + 1
        )
    for row in artifact.instruction_rows:
        opcode = str(row.get("opcode"))
        role = str(row.get("role"))
        opcode_counts[opcode] = opcode_counts.get(opcode, 0) + 1
        role_counts[role] = role_counts.get(role, 0) + 1
        if not row.get("template_op_id"):
            missing_template_provenance_count += 1
        if not row.get("primary_fiber_op_id"):
            missing_fiber_provenance_count += 1
        forbidden_tile_micro_block_fields += _forbidden_field_count(row)
    for row in artifact.zero_boundaries:
        role = str(row.get("role"))
        zero_role_counts[role] = zero_role_counts.get(role, 0) + 1
        if not row.get("template_op_id"):
            missing_template_provenance_count += 1
        if not row.get("primary_fiber_op_id"):
            missing_fiber_provenance_count += 1
        forbidden_tile_micro_block_fields += _forbidden_field_count(row)

    return {
        "profile_id": artifact.profile_id,
        "runnability_state": artifact.runnability_state,
        "instruction_row_count": len(artifact.instruction_rows),
        "zero_boundary_count": len(artifact.zero_boundaries),
        "opcode_counts": dict(sorted(opcode_counts.items())),
        "role_counts": dict(sorted(role_counts.items())),
        "zero_boundary_role_counts": dict(sorted(zero_role_counts.items())),
        "diagnostic_severity_counts": dict(sorted(diagnostic_severity_counts.items())),
        "diagnostic_count": len(artifact.diagnostics),
        "missing_template_provenance_count": missing_template_provenance_count,
        "missing_fiber_provenance_count": missing_fiber_provenance_count,
        "forbidden_tile_micro_block_field_count": forbidden_tile_micro_block_fields,
    }


def _instruction_row_artifact(row: object) -> dict[str, object]:
    payload = row.to_plan()
    return {
        "row_kind": "instruction",
        "row_index": payload["row_index"],
        "pc": payload["pc"],
        "opcode": payload["opcode"],
        "role": payload["role"],
        "phase": payload["phase"],
        "loop_instance": payload["loop_instance"],
        "task_id": payload["task_id"],
        "stream_id": payload["stream_id"],
        "subtask_slot": payload["subtask_slot"],
        "template_op_id": payload["template_op_id"],
        "source_schedule_step_id": payload["source_schedule_step_id"],
        "primary_fiber_op_id": payload["primary_fiber_op_id"],
        "attrs": payload["attrs"],
    }


def _zero_boundary_artifact(boundary: object) -> dict[str, object]:
    payload = boundary.to_plan()
    return {
        "row_kind": "zero_instruction_boundary",
        "pc": None,
        "role": payload["role"],
        "phase": payload["phase"],
        "loop_instance": payload["loop_instance"],
        "task_id": payload["task_id"],
        "stream_id": payload["stream_id"],
        "subtask_slot": payload["subtask_slot"],
        "boundary_kind": payload["boundary_kind"],
        "template_op_id": payload["template_op_id"],
        "source_schedule_step_id": payload["source_schedule_step_id"],
        "primary_fiber_op_id": payload["primary_fiber_op_id"],
        "attrs": payload["attrs"],
    }


def _forbidden_field_count(row: dict[str, object]) -> int:
    return sum(
        1
        for key in row
        if key.startswith("source_tile_micro_block") or key == "tile_micro_block_kind"
    )


__all__ = [
    "DebugRowArtifact",
    "emit_debug_row_artifact",
    "summarize_debug_row_artifact",
]
