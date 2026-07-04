"""Debug-only component byte writers for B-line candidates.

This module is the first narrow byte-writing step after serializer readiness.
It is not a runnable package emitter.  Each writer consumes already-decided
component candidates and readiness reports, then writes only the struct family
whose fields are proven packable.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct

from .serializer_readiness import SerializerReadinessPlan
from .template_ops import Diagnostic
from .vendor_components import VendorComponentPlan

INSTANCE_CONF_INFO_STRUCT = "instance_conf_info_t"
INSTANCE_CONF_INFO_FORMAT = "<4Q"
INSTANCE_CONF_INFO_RECORD_SIZE = struct.calcsize(INSTANCE_CONF_INFO_FORMAT)
INSTANCE_BASE_ADDR_SLOTS = 4


@dataclass(frozen=True)
class DebugComponentWriterArtifact:
    """Debug-only byte artifact for one component family."""

    profile_id: str
    component: str
    struct_name: str
    writer_status: str
    byte_order: str
    record_format: str
    row_count: int
    record_size_bytes: int
    payload: bytes
    row_records: tuple[dict[str, object], ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_debug_component_writer_artifact",
            "profile_id": self.profile_id,
            "component": self.component,
            "struct_name": self.struct_name,
            "writer_status": self.writer_status,
            "byte_order": self.byte_order,
            "record_format": self.record_format,
            "row_count": self.row_count,
            "record_size_bytes": self.record_size_bytes,
            "payload_size_bytes": len(self.payload),
            "payload_hex": self.payload.hex(),
            "row_records": list(self.row_records),
            "diagnostics": [
                diagnostic.to_plan() for diagnostic in self.diagnostics
            ],
            "layering_policy": (
                "debug_component_writer_consumes_serializer_readiness_and_"
                "vendor_component_candidates;debug_only_not_runnable_package"
            ),
        }


def emit_debug_instance_conf_info_component(
    component_plan: VendorComponentPlan,
    readiness_plan: SerializerReadinessPlan,
) -> DebugComponentWriterArtifact:
    """Pack debug-only ``instance_conf_info_t`` rows as ``<4Q`` records."""

    diagnostics = list(component_plan.diagnostics)
    diagnostics.extend(_readiness_diagnostics(readiness_plan))

    if component_plan.profile_id != readiness_plan.profile_id:
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="component_writer_profile_mismatch",
                subject_id=INSTANCE_CONF_INFO_STRUCT,
                message=(
                    "component plan and readiness plan profile ids differ: "
                    f"{component_plan.profile_id} != {readiness_plan.profile_id}"
                ),
            )
        )
    if component_plan.runnability_state != "emittable_debug":
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="debug_component_writer_requires_emittable_debug",
                subject_id=INSTANCE_CONF_INFO_STRUCT,
                message=(
                    "debug component writer requires an emittable_debug "
                    f"component plan; got {component_plan.runnability_state}"
                ),
            )
        )
    if not _struct_is_packable(readiness_plan, INSTANCE_CONF_INFO_STRUCT):
        diagnostics.append(
            Diagnostic(
                severity="error",
                code="instance_conf_info_not_packable",
                subject_id=INSTANCE_CONF_INFO_STRUCT,
                message="instance_conf_info_t is not marked packable by readiness",
            )
        )

    row_records: list[dict[str, object]] = []
    chunks: list[bytes] = []
    if not any(diagnostic.severity == "error" for diagnostic in diagnostics):
        for row in component_plan.instance_rows:
            record = _instance_conf_info_record(row)
            if record.get("status") != "packed":
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="invalid_instance_conf_info_candidate",
                        subject_id=str(row.get("component_index")),
                        message=str(record.get("error")),
                    )
                )
                continue
            base_addr_words = record["base_addr_words"]
            if not isinstance(base_addr_words, tuple):
                diagnostics.append(
                    Diagnostic(
                        severity="error",
                        code="invalid_instance_base_addr_words",
                        subject_id=str(row.get("component_index")),
                        message="packed instance record did not return tuple base addresses",
                    )
                )
                continue
            chunks.append(struct.pack(INSTANCE_CONF_INFO_FORMAT, *base_addr_words))
            row_records.append(record)

    if any(diagnostic.severity == "error" for diagnostic in diagnostics):
        return DebugComponentWriterArtifact(
            profile_id=component_plan.profile_id,
            component="instance_rows",
            struct_name=INSTANCE_CONF_INFO_STRUCT,
            writer_status="blocked",
            byte_order="little",
            record_format=INSTANCE_CONF_INFO_FORMAT,
            row_count=0,
            record_size_bytes=INSTANCE_CONF_INFO_RECORD_SIZE,
            payload=b"",
            row_records=(),
            diagnostics=tuple(diagnostics),
        )

    return DebugComponentWriterArtifact(
        profile_id=component_plan.profile_id,
        component="instance_rows",
        struct_name=INSTANCE_CONF_INFO_STRUCT,
        writer_status="debug_only",
        byte_order="little",
        record_format=INSTANCE_CONF_INFO_FORMAT,
        row_count=len(row_records),
        record_size_bytes=INSTANCE_CONF_INFO_RECORD_SIZE,
        payload=b"".join(chunks),
        row_records=tuple(row_records),
        diagnostics=tuple(diagnostics),
    )


def summarize_debug_component_writer_artifact(
    artifact: DebugComponentWriterArtifact,
) -> dict[str, object]:
    """Return stable counts for focused checks."""

    diagnostic_counts: dict[str, int] = {}
    for diagnostic in artifact.diagnostics:
        diagnostic_counts[diagnostic.severity] = (
            diagnostic_counts.get(diagnostic.severity, 0) + 1
        )
    return {
        "profile_id": artifact.profile_id,
        "component": artifact.component,
        "struct_name": artifact.struct_name,
        "writer_status": artifact.writer_status,
        "record_format": artifact.record_format,
        "row_count": artifact.row_count,
        "record_size_bytes": artifact.record_size_bytes,
        "payload_size_bytes": len(artifact.payload),
        "diagnostic_count": len(artifact.diagnostics),
        "diagnostic_severity_counts": dict(sorted(diagnostic_counts.items())),
        "row_status_counts": _row_status_counts(artifact.row_records),
        "base_addr_slot_count": INSTANCE_BASE_ADDR_SLOTS,
        "debug_only": artifact.writer_status == "debug_only",
    }


def _readiness_diagnostics(plan: SerializerReadinessPlan) -> tuple[Diagnostic, ...]:
    return tuple(
        Diagnostic(
            severity="error",
            code="serializer_readiness_diagnostic",
            subject_id="SerializerReadinessPlan",
            message=message,
        )
        for message in plan.diagnostics
    )


def _struct_is_packable(plan: SerializerReadinessPlan, struct_name: str) -> bool:
    return any(
        readiness.struct_name == struct_name
        and readiness.serializer_status == "packable_candidate"
        for readiness in plan.struct_readiness
    )


def _instance_conf_info_record(row: dict[str, object]) -> dict[str, object]:
    candidate = row.get("instance_conf_info_candidate")
    if not isinstance(candidate, dict):
        return {
            "status": "blocked",
            "error": "missing instance_conf_info_candidate",
        }
    base_addr = candidate.get("base_addr")
    if not isinstance(base_addr, list) or len(base_addr) != INSTANCE_BASE_ADDR_SLOTS:
        return {
            "component_index": row.get("component_index"),
            "status": "blocked",
            "error": "base_addr must contain four slots",
        }
    words: list[int] = []
    slot_records: list[dict[str, object]] = []
    for expected_slot, slot in enumerate(base_addr):
        if not isinstance(slot, dict):
            return {
                "component_index": row.get("component_index"),
                "status": "blocked",
                "error": f"base_addr[{expected_slot}] is not a candidate slot",
            }
        if slot.get("slot") != expected_slot:
            return {
                "component_index": row.get("component_index"),
                "status": "blocked",
                "error": f"base_addr[{expected_slot}] has non-matching slot id",
            }
        word = slot.get("base_addr_word")
        if not isinstance(word, int) or word < 0:
            return {
                "component_index": row.get("component_index"),
                "status": "blocked",
                "error": f"base_addr[{expected_slot}] lacks concrete word value",
            }
        words.append(word)
        slot_records.append(
            {
                "slot": expected_slot,
                "role": slot.get("role"),
                "status": slot.get("status"),
                "base_addr_word": word,
                "base_addr_word_hex": f"0x{word:08x}",
            }
        )
    return {
        "component_index": row.get("component_index"),
        "task_idx": candidate.get("task_idx"),
        "subtask_idx": candidate.get("subtask_idx"),
        "instance_idx": candidate.get("instance_idx"),
        "loop_instance": candidate.get("loop_instance"),
        "status": "packed",
        "base_addr_words": tuple(words),
        "base_addr_slots": slot_records,
        "source_policy": candidate.get("base_addr_policy"),
        "binary_encoding_policy": "debug_only_instance_conf_info_t_4x_u64",
    }


def _row_status_counts(rows: tuple[dict[str, object], ...]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        status = str(row.get("status"))
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


__all__ = [
    "DebugComponentWriterArtifact",
    "emit_debug_instance_conf_info_component",
    "summarize_debug_component_writer_artifact",
]
