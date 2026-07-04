"""Serializer-readiness reports for B-line component candidates.

This layer is still not a byte writer.  It combines two facts:

* field-offset preflight: where a field would be written;
* component candidate values: whether the value is concrete enough to pack.

The important distinction is that a known offset is not enough.  Padding slots,
``None`` sentinels, unresolved block classes, and symbolic ``inst_t`` fields
must remain visible blockers until a serializer policy proves them.
"""

from __future__ import annotations

from dataclasses import dataclass

from .field_offsets import FieldOffsetPreflightPlan, KNOWN_FIELD_LAYOUTS
from .vendor_components import VendorComponentPlan


@dataclass(frozen=True)
class SerializerFieldReadiness:
    """Readiness of one required serializer field."""

    struct_name: str
    field_path: str
    offset_status: str
    value_status: str
    byte_offset: int | None
    field_size: int | None
    blocker_reason: str | None

    def to_plan(self) -> dict[str, object]:
        return {
            "struct_name": self.struct_name,
            "field_path": self.field_path,
            "offset_status": self.offset_status,
            "value_status": self.value_status,
            "byte_offset": self.byte_offset,
            "field_size": self.field_size,
            "blocker_reason": self.blocker_reason,
        }


@dataclass(frozen=True)
class StructSerializerReadiness:
    """Readiness of one candidate struct family."""

    struct_name: str
    component: str
    row_count: int
    serializer_status: str
    required_fields: tuple[SerializerFieldReadiness, ...]

    def to_plan(self) -> dict[str, object]:
        return {
            "struct_name": self.struct_name,
            "component": self.component,
            "row_count": self.row_count,
            "serializer_status": self.serializer_status,
            "required_field_count": len(self.required_fields),
            "known_offset_count": sum(
                1 for field in self.required_fields if field.offset_status == "known"
            ),
            "value_ready_count": sum(
                1 for field in self.required_fields if field.value_status == "ready"
            ),
            "blocked_field_count": sum(
                1
                for field in self.required_fields
                if field.offset_status != "known" or field.value_status != "ready"
            ),
            "required_fields": [field.to_plan() for field in self.required_fields],
        }


@dataclass(frozen=True)
class SerializerReadinessPlan:
    """Report-only serializer readiness view."""

    profile_id: str
    runnability_state: str
    struct_readiness: tuple[StructSerializerReadiness, ...]
    recommended_first_writer: str | None
    diagnostics: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_serializer_readiness",
            "profile_id": self.profile_id,
            "runnability_state": self.runnability_state,
            "recommended_first_writer": self.recommended_first_writer,
            "struct_readiness": [
                readiness.to_plan() for readiness in self.struct_readiness
            ],
            "diagnostics": list(self.diagnostics),
            "layering_policy": (
                "serializer_readiness_consumes_component_and_offset_preflight;"
                "reports_packability_without_serializing_binary_bytes"
            ),
        }


REQUIRED_SERIALIZER_FIELDS: dict[str, tuple[str, ...]] = {
    "inst_t": ("inst_t_fields",),
    "instance_conf_info_t": (
        "base_addr.0.base_addr_word",
        "base_addr.1.base_addr_word",
        "base_addr.2.base_addr_word",
        "base_addr.3.base_addr_word",
    ),
    "task_conf_info_t": (
        "is_exe_start",
        "is_exe_end",
        "subtasks_amount",
        "execute_times",
        "subtasks_idx",
        "suc_tasks",
    ),
    "sub_task_conf_info_t": (
        "is_exe_start",
        "is_exe_end",
        "instances_amount",
        "instances_conf_mem_based_addr",
        "suc_subtasks",
        "root_block_amount",
        "block_amount",
        "embedded_exeblock_component_indices",
        "subtask_idx",
        "task_idx",
    ),
    "exeBlock_conf_info_t": (
        "valid",
        "block_idx",
        "pe_dst",
        "priority",
        "exeBlock_conf.req_activations",
        "exeBlock_conf.has_stages",
        "exeBlock_conf.stages_start_pc",
        "exeBlock_conf.predecessors",
        "exeBlock_conf.successors",
        "exeBlock_conf.block_idx",
        "exeBlock_conf.subtask_idx",
        "exeBlock_conf.task_idx",
        "exeBlock_conf.instances_amount",
        "exeBlock_conf.child_amount",
        "exeBlock_conf.block_class",
        "exeBlock_conf.inst_mem_based_addr",
        "exeBlock_conf.stage_inst_amounts.LD",
        "exeBlock_conf.stage_inst_amounts.CAL",
        "exeBlock_conf.stage_inst_amounts.FLOW",
        "exeBlock_conf.stage_inst_amounts.ST",
        "exeBlock_conf.is_leaf",
    ),
}


STRUCT_CANDIDATE_SOURCES = {
    "inst_t": ("inst_rows", "inst_t"),
    "exeBlock_conf_info_t": ("exeblock_rows", "exeBlock_conf_info_candidate"),
    "instance_conf_info_t": ("instance_rows", "instance_conf_info_candidate"),
    "task_conf_info_t": ("task_rows", "task_conf_info_candidate"),
    "sub_task_conf_info_t": ("subtask_rows", "sub_task_conf_info_candidate"),
}


def build_serializer_readiness_plan(
    component_plan: VendorComponentPlan,
    offset_plan: FieldOffsetPreflightPlan,
) -> SerializerReadinessPlan:
    """Build a fail-closed serializer readiness report."""

    offset_records = {
        (report.struct_name, record.candidate_field_path): record
        for report in offset_plan.struct_reports
        for record in report.records
    }
    struct_readiness = tuple(
        _struct_readiness(component_plan, offset_plan, offset_records, struct_name)
        for struct_name in (
            "inst_t",
            "exeBlock_conf_info_t",
            "instance_conf_info_t",
            "task_conf_info_t",
            "sub_task_conf_info_t",
        )
    )
    ready_structs = [
        readiness.struct_name
        for readiness in struct_readiness
        if readiness.serializer_status == "packable_candidate"
    ]
    return SerializerReadinessPlan(
        profile_id=component_plan.profile_id,
        runnability_state="report_only",
        struct_readiness=struct_readiness,
        recommended_first_writer=_recommended_first_writer(ready_structs),
    )


def summarize_serializer_readiness_plan(
    plan: SerializerReadinessPlan,
) -> dict[str, object]:
    """Return stable readiness counts for focused checks."""

    return {
        "profile_id": plan.profile_id,
        "runnability_state": plan.runnability_state,
        "struct_readiness_count": len(plan.struct_readiness),
        "packable_struct_count": sum(
            1
            for readiness in plan.struct_readiness
            if readiness.serializer_status == "packable_candidate"
        ),
        "blocked_struct_count": sum(
            1
            for readiness in plan.struct_readiness
            if readiness.serializer_status != "packable_candidate"
        ),
        "recommended_first_writer": plan.recommended_first_writer,
        "required_field_count": sum(
            len(readiness.required_fields) for readiness in plan.struct_readiness
        ),
        "known_required_offset_count": sum(
            1
            for readiness in plan.struct_readiness
            for field in readiness.required_fields
            if field.offset_status == "known"
        ),
        "ready_required_value_count": sum(
            1
            for readiness in plan.struct_readiness
            for field in readiness.required_fields
            if field.value_status == "ready"
        ),
        "blocked_required_field_count": sum(
            1
            for readiness in plan.struct_readiness
            for field in readiness.required_fields
            if field.offset_status != "known" or field.value_status != "ready"
        ),
        "diagnostic_count": len(plan.diagnostics),
        "serializer_status_counts": _status_counts(plan),
    }


def _struct_readiness(
    component_plan: VendorComponentPlan,
    offset_plan: FieldOffsetPreflightPlan,
    offset_records: dict[tuple[str, str], object],
    struct_name: str,
) -> StructSerializerReadiness:
    component_name, candidate_key = STRUCT_CANDIDATE_SOURCES[struct_name]
    rows = tuple(getattr(component_plan, component_name))
    reports = {report.struct_name: report for report in offset_plan.struct_reports}
    row_count = reports[struct_name].row_count
    fields = tuple(
        _field_readiness(
            struct_name,
            field_path,
            rows,
            candidate_key,
            offset_records,
        )
        for field_path in REQUIRED_SERIALIZER_FIELDS[struct_name]
    )
    serializer_status = (
        "packable_candidate"
        if all(
            field.offset_status == "known" and field.value_status == "ready"
            for field in fields
        )
        else "blocked_pending_evidence"
    )
    return StructSerializerReadiness(
        struct_name=struct_name,
        component=component_name,
        row_count=row_count,
        serializer_status=serializer_status,
        required_fields=fields,
    )


def _field_readiness(
    struct_name: str,
    field_path: str,
    rows: tuple[dict[str, object], ...],
    candidate_key: str,
    offset_records: dict[tuple[str, str], object],
) -> SerializerFieldReadiness:
    offset_record = offset_records.get((struct_name, field_path))
    known_layout = KNOWN_FIELD_LAYOUTS.get(struct_name, {}).get(field_path)
    offset_status = getattr(
        offset_record,
        "offset_status",
        "known" if known_layout is not None else "unresolved",
    )
    byte_offset = getattr(
        offset_record,
        "byte_offset",
        known_layout.offset if known_layout is not None else None,
    )
    field_size = getattr(
        offset_record,
        "field_size",
        known_layout.size if known_layout is not None else None,
    )

    if offset_status != "known":
        return SerializerFieldReadiness(
            struct_name=struct_name,
            field_path=field_path,
            offset_status="unresolved",
            value_status="blocked",
            byte_offset=None,
            field_size=None,
            blocker_reason="missing_known_field_offset",
        )

    values = [
        _candidate_field_value(row, candidate_key, field_path)
        for row in rows
    ]
    if any(value is _MISSING for value in values):
        return SerializerFieldReadiness(
            struct_name=struct_name,
            field_path=field_path,
            offset_status="known",
            value_status="blocked",
            byte_offset=byte_offset,
            field_size=field_size,
            blocker_reason="missing_candidate_value",
        )
    if any(_contains_unresolved_placeholder(value) for value in values):
        return SerializerFieldReadiness(
            struct_name=struct_name,
            field_path=field_path,
            offset_status="known",
            value_status="blocked",
            byte_offset=byte_offset,
            field_size=field_size,
            blocker_reason="candidate_value_contains_unresolved_placeholder",
        )
    return SerializerFieldReadiness(
        struct_name=struct_name,
        field_path=field_path,
        offset_status="known",
        value_status="ready",
        byte_offset=byte_offset,
        field_size=field_size,
        blocker_reason=None,
    )


def _candidate_field_value(
    row: dict[str, object],
    candidate_key: str,
    field_path: str,
) -> object:
    if candidate_key == "inst_t":
        return _MISSING
    candidate = row.get(candidate_key)
    if not isinstance(candidate, dict):
        return _MISSING
    current: object = candidate
    for part in field_path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return _MISSING
            current = current[part]
        elif isinstance(current, list):
            if not part.isdigit():
                return _MISSING
            index = int(part)
            if index >= len(current):
                return _MISSING
            current = current[index]
        else:
            return _MISSING
    return current


def _contains_unresolved_placeholder(value: object) -> bool:
    if value is None:
        return True
    if isinstance(value, dict):
        return any(_contains_unresolved_placeholder(item) for item in value.values())
    if isinstance(value, list):
        return any(_contains_unresolved_placeholder(item) for item in value)
    return False


def _status_counts(plan: SerializerReadinessPlan) -> dict[str, int]:
    counts: dict[str, int] = {}
    for readiness in plan.struct_readiness:
        status = readiness.serializer_status
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _recommended_first_writer(ready_structs: list[str]) -> str | None:
    """Pick the narrowest debug writer target among packable candidates."""

    preferred_order = (
        "instance_conf_info_t",
        "task_conf_info_t",
        "exeBlock_conf_info_t",
        "sub_task_conf_info_t",
        "inst_t",
    )
    for struct_name in preferred_order:
        if struct_name in ready_structs:
            return struct_name
    return ready_structs[0] if ready_structs else None


class _Missing:
    pass


_MISSING = _Missing()


__all__ = [
    "SerializerFieldReadiness",
    "SerializerReadinessPlan",
    "StructSerializerReadiness",
    "build_serializer_readiness_plan",
    "summarize_serializer_readiness_plan",
]
