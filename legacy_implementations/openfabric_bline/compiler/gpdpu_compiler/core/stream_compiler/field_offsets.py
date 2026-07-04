"""Field-offset preflight reports for B-line candidate component structs.

This module is deliberately not a serializer.  It answers a narrower question:

    which candidate fields already have a known vendor byte offset,
    and which fields still need original C/C++ layout evidence?

Known offsets are copied from the curated runtime docs and archived serializer
notes.  Unknown offsets stay visible as ``unresolved`` records instead of being
guessed.
"""

from __future__ import annotations

from dataclasses import dataclass

from gpdpu_compiler.core.dfu3500 import DFU3500_STRUCT_SIZES

from .vendor_components import VendorComponentPlan


@dataclass(frozen=True)
class KnownFieldLayout:
    """One known vendor field layout fact."""

    offset: int
    size: int
    evidence: str
    vendor_field: str | None = None


@dataclass(frozen=True)
class StructFieldPreflightRecord:
    """Field-level offset preflight for one candidate field path."""

    struct_name: str
    candidate_field_path: str
    row_count: int
    struct_size: int
    offset_status: str
    byte_offset: int | None
    field_size: int | None
    vendor_field: str | None
    binary_encoded_count: int
    evidence: str

    def to_plan(self) -> dict[str, object]:
        return {
            "struct_name": self.struct_name,
            "candidate_field_path": self.candidate_field_path,
            "row_count": self.row_count,
            "struct_size": self.struct_size,
            "offset_status": self.offset_status,
            "byte_offset": self.byte_offset,
            "field_size": self.field_size,
            "vendor_field": self.vendor_field,
            "binary_encoded_count": self.binary_encoded_count,
            "evidence": self.evidence,
        }


@dataclass(frozen=True)
class StructOffsetPreflightReport:
    """Struct-level candidate field preflight."""

    struct_name: str
    component: str
    row_count: int
    struct_size: int
    records: tuple[StructFieldPreflightRecord, ...]

    def to_plan(self) -> dict[str, object]:
        return {
            "struct_name": self.struct_name,
            "component": self.component,
            "row_count": self.row_count,
            "struct_size": self.struct_size,
            "known_field_count": sum(
                1 for record in self.records if record.offset_status == "known"
            ),
            "unresolved_field_count": sum(
                1 for record in self.records if record.offset_status == "unresolved"
            ),
            "binary_encoded_field_count": sum(
                record.binary_encoded_count for record in self.records
            ),
            "records": [record.to_plan() for record in self.records],
        }


@dataclass(frozen=True)
class FieldOffsetPreflightPlan:
    """Report-only field offset preflight for component candidates."""

    profile_id: str
    runnability_state: str
    struct_reports: tuple[StructOffsetPreflightReport, ...]
    diagnostics: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_field_offset_preflight",
            "profile_id": self.profile_id,
            "runnability_state": self.runnability_state,
            "struct_reports": [report.to_plan() for report in self.struct_reports],
            "diagnostics": list(self.diagnostics),
            "layering_policy": (
                "field_offset_preflight_consumes_vendor_component_plan;"
                "reports_layout_facts_without_serializing_binary_bytes"
            ),
        }


RUNTIME_DOC_EVIDENCE = (
    "docs/runtime/data/cbuf.md;"
    "docs/runtime/data/micc.md;"
    "docs/compiler/binary_packaging/research_notes/archive/rfc-program-bin-serializer.md"
)


KNOWN_FIELD_LAYOUTS: dict[str, dict[str, KnownFieldLayout]] = {
    "inst_t": {},
    "instance_conf_info_t": {
        "base_addr.0.base_addr_word": KnownFieldLayout(
            0, 8, RUNTIME_DOC_EVIDENCE, "base_addr[0]"
        ),
        "base_addr.1.base_addr_word": KnownFieldLayout(
            8, 8, RUNTIME_DOC_EVIDENCE, "base_addr[1]"
        ),
        "base_addr.2.base_addr_word": KnownFieldLayout(
            16, 8, RUNTIME_DOC_EVIDENCE, "base_addr[2]"
        ),
        "base_addr.3.base_addr_word": KnownFieldLayout(
            24, 8, RUNTIME_DOC_EVIDENCE, "base_addr[3]"
        ),
    },
    "task_conf_info_t": {
        "is_exe_start": KnownFieldLayout(0, 1, RUNTIME_DOC_EVIDENCE),
        "is_exe_end": KnownFieldLayout(1, 1, RUNTIME_DOC_EVIDENCE),
        "subtasks_amount": KnownFieldLayout(8, 8, RUNTIME_DOC_EVIDENCE),
        "execute_times": KnownFieldLayout(16, 8, RUNTIME_DOC_EVIDENCE),
        "subtasks_idx": KnownFieldLayout(
            24, 64, RUNTIME_DOC_EVIDENCE, "subtasks_idx[0..7]"
        ),
        "suc_tasks": KnownFieldLayout(
            88, 32, RUNTIME_DOC_EVIDENCE, "suc_tasks[0..3]"
        ),
    },
    "sub_task_conf_info_t": {
        "is_exe_start": KnownFieldLayout(0, 1, RUNTIME_DOC_EVIDENCE),
        "is_exe_end": KnownFieldLayout(1, 1, RUNTIME_DOC_EVIDENCE),
        "instances_amount": KnownFieldLayout(8, 8, RUNTIME_DOC_EVIDENCE),
        "instances_conf_mem_based_addr": KnownFieldLayout(
            16, 8, RUNTIME_DOC_EVIDENCE
        ),
        "suc_subtasks": KnownFieldLayout(
            24, 32, RUNTIME_DOC_EVIDENCE, "suc_subtasks[0..3]"
        ),
        "root_block_amount": KnownFieldLayout(56, 8, RUNTIME_DOC_EVIDENCE),
        "block_amount": KnownFieldLayout(64, 8, RUNTIME_DOC_EVIDENCE),
        "embedded_exeblock_component_indices": KnownFieldLayout(
            72, 266240, RUNTIME_DOC_EVIDENCE, "exeBlocks_conf_info[512]"
        ),
        "subtask_idx": KnownFieldLayout(266312, 8, RUNTIME_DOC_EVIDENCE),
        "task_idx": KnownFieldLayout(266320, 8, RUNTIME_DOC_EVIDENCE),
    },
    "exeBlock_conf_info_t": {
        "valid": KnownFieldLayout(0, 1, RUNTIME_DOC_EVIDENCE),
        "block_idx": KnownFieldLayout(8, 8, RUNTIME_DOC_EVIDENCE),
        "pe_dst": KnownFieldLayout(16, 24, RUNTIME_DOC_EVIDENCE),
        "priority": KnownFieldLayout(40, 8, RUNTIME_DOC_EVIDENCE),
        "exeBlock_conf.req_activations": KnownFieldLayout(
            48, 8, RUNTIME_DOC_EVIDENCE
        ),
        "exeBlock_conf.has_stages": KnownFieldLayout(
            56, 4, RUNTIME_DOC_EVIDENCE, "exeBlock_conf.has_stages[0..3]"
        ),
        "exeBlock_conf.stages_start_pc": KnownFieldLayout(
            64, 40, RUNTIME_DOC_EVIDENCE, "exeBlock_conf.stages_start_pc[0..4]"
        ),
        "exeBlock_conf.predecessors": KnownFieldLayout(
            104, 160, RUNTIME_DOC_EVIDENCE, "exeBlock_conf.predecessors[0..3]"
        ),
        "exeBlock_conf.successors": KnownFieldLayout(
            264, 160, RUNTIME_DOC_EVIDENCE, "exeBlock_conf.successors[0..3]"
        ),
        "exeBlock_conf.block_idx": KnownFieldLayout(424, 8, RUNTIME_DOC_EVIDENCE),
        "exeBlock_conf.subtask_idx": KnownFieldLayout(432, 8, RUNTIME_DOC_EVIDENCE),
        "exeBlock_conf.task_idx": KnownFieldLayout(440, 8, RUNTIME_DOC_EVIDENCE),
        "exeBlock_conf.instances_amount": KnownFieldLayout(
            448, 8, RUNTIME_DOC_EVIDENCE
        ),
        "exeBlock_conf.child_amount": KnownFieldLayout(456, 8, RUNTIME_DOC_EVIDENCE),
        "exeBlock_conf.block_class": KnownFieldLayout(464, 8, RUNTIME_DOC_EVIDENCE),
        "exeBlock_conf.inst_mem_based_addr": KnownFieldLayout(
            472, 8, RUNTIME_DOC_EVIDENCE
        ),
        "exeBlock_conf.stage_inst_amounts.LD": KnownFieldLayout(
            480, 8, RUNTIME_DOC_EVIDENCE, "exeBlock_conf.ld_stage_inst_amount"
        ),
        "exeBlock_conf.stage_inst_amounts.CAL": KnownFieldLayout(
            488, 8, RUNTIME_DOC_EVIDENCE, "exeBlock_conf.cal_stage_inst_amount"
        ),
        "exeBlock_conf.stage_inst_amounts.FLOW": KnownFieldLayout(
            496, 8, RUNTIME_DOC_EVIDENCE, "exeBlock_conf.flow_stage_inst_amount"
        ),
        "exeBlock_conf.stage_inst_amounts.ST": KnownFieldLayout(
            504, 8, RUNTIME_DOC_EVIDENCE, "exeBlock_conf.st_stage_inst_amount"
        ),
        "exeBlock_conf.is_leaf": KnownFieldLayout(512, 1, RUNTIME_DOC_EVIDENCE),
    },
}


def build_field_offset_preflight_plan(
    component_plan: VendorComponentPlan,
) -> FieldOffsetPreflightPlan:
    """Build report-only field offset preflight from component candidates."""

    struct_reports = (
        _struct_report(
            "inst_t",
            "inst_rows",
            "inst_t",
            component_plan.inst_rows,
        ),
        _struct_report(
            "exeBlock_conf_info_t",
            "exeblock_rows",
            "exeBlock_conf_info_candidate",
            component_plan.exeblock_rows,
        ),
        _struct_report(
            "instance_conf_info_t",
            "instance_rows",
            "instance_conf_info_candidate",
            component_plan.instance_rows,
        ),
        _struct_report(
            "task_conf_info_t",
            "task_rows",
            "task_conf_info_candidate",
            component_plan.task_rows,
        ),
        _struct_report(
            "sub_task_conf_info_t",
            "subtask_rows",
            "sub_task_conf_info_candidate",
            component_plan.subtask_rows,
        ),
    )
    return FieldOffsetPreflightPlan(
        profile_id=component_plan.profile_id,
        runnability_state="layout_candidate",
        struct_reports=struct_reports,
    )


def summarize_field_offset_preflight_plan(
    plan: FieldOffsetPreflightPlan,
) -> dict[str, object]:
    """Return stable summary counts for Phase 6 checks."""

    return {
        "profile_id": plan.profile_id,
        "runnability_state": plan.runnability_state,
        "struct_report_count": len(plan.struct_reports),
        "struct_names": [report.struct_name for report in plan.struct_reports],
        "row_counts": {
            report.struct_name: report.row_count for report in plan.struct_reports
        },
        "known_struct_size_count": sum(
            1 for report in plan.struct_reports if report.struct_size > 0
        ),
        "field_record_count": sum(
            len(report.records) for report in plan.struct_reports
        ),
        "known_field_offset_count": sum(
            1
            for report in plan.struct_reports
            for record in report.records
            if record.offset_status == "known"
        ),
        "unresolved_field_offset_count": sum(
            1
            for report in plan.struct_reports
            for record in report.records
            if record.offset_status == "unresolved"
        ),
        "binary_encoded_field_count": sum(
            record.binary_encoded_count
            for report in plan.struct_reports
            for record in report.records
        ),
        "diagnostic_count": len(plan.diagnostics),
    }


def _struct_report(
    struct_name: str,
    component: str,
    candidate_key: str,
    rows: tuple[dict[str, object], ...],
) -> StructOffsetPreflightReport:
    struct_size = int(DFU3500_STRUCT_SIZES[struct_name])
    field_values: dict[str, list[object]] = {}
    for row in rows:
        candidate = row if candidate_key == "inst_t" else row.get(candidate_key)
        if not isinstance(candidate, dict):
            continue
        for path, value in _flatten_candidate_fields(candidate):
            field_values.setdefault(path, []).append(value)
    known_layouts = KNOWN_FIELD_LAYOUTS[struct_name]
    records = [
        _field_record(
            struct_name,
            path,
            values,
            row_count=len(rows),
            struct_size=struct_size,
            known_layouts=known_layouts,
        )
        for path, values in sorted(field_values.items())
    ]
    return StructOffsetPreflightReport(
        struct_name=struct_name,
        component=component,
        row_count=len(rows),
        struct_size=struct_size,
        records=tuple(records),
    )


def _field_record(
    struct_name: str,
    path: str,
    values: list[object],
    *,
    row_count: int,
    struct_size: int,
    known_layouts: dict[str, KnownFieldLayout],
) -> StructFieldPreflightRecord:
    layout = known_layouts.get(path)
    binary_encoded_count = sum(
        1 for value in values if _field_claims_binary_encoded(value)
    )
    if layout is None:
        return StructFieldPreflightRecord(
            struct_name=struct_name,
            candidate_field_path=path,
            row_count=row_count,
            struct_size=struct_size,
            offset_status="unresolved",
            byte_offset=None,
            field_size=None,
            vendor_field=None,
            binary_encoded_count=binary_encoded_count,
            evidence="unresolved_pending_original_struct_layout_or_serializer_audit",
        )
    return StructFieldPreflightRecord(
        struct_name=struct_name,
        candidate_field_path=path,
        row_count=row_count,
        struct_size=struct_size,
        offset_status="known",
        byte_offset=layout.offset,
        field_size=layout.size,
        vendor_field=layout.vendor_field or path,
        binary_encoded_count=binary_encoded_count,
        evidence=layout.evidence,
    )


def _flatten_candidate_fields(value: object, prefix: str = "") -> tuple[tuple[str, object], ...]:
    records: list[tuple[str, object]] = []
    if isinstance(value, dict):
        for key, item in sorted(value.items()):
            next_prefix = f"{prefix}.{key}" if prefix else str(key)
            records.extend(_flatten_candidate_fields(item, next_prefix))
    elif isinstance(value, list):
        if _is_scalar_list(value):
            records.append((prefix, value))
        else:
            for index, item in enumerate(value):
                next_prefix = f"{prefix}.{index}" if prefix else str(index)
                records.extend(_flatten_candidate_fields(item, next_prefix))
    else:
        records.append((prefix, value))
    return tuple(records)


def _is_scalar_list(values: list[object]) -> bool:
    return all(not isinstance(value, (dict, list)) for value in values)


def _field_claims_binary_encoded(value: object) -> bool:
    if isinstance(value, dict):
        if value.get("binary_encoded") is True:
            return True
        return any(_field_claims_binary_encoded(item) for item in value.values())
    if isinstance(value, list):
        return any(_field_claims_binary_encoded(item) for item in value)
    return False


__all__ = [
    "FieldOffsetPreflightPlan",
    "KnownFieldLayout",
    "StructFieldPreflightRecord",
    "StructOffsetPreflightReport",
    "build_field_offset_preflight_plan",
    "summarize_field_offset_preflight_plan",
]
