"""Vendor assembler input bundle projection for B-line stream plans.

This module emits a vendor-shaped case package, not final CBUF/MICC bytes. The
first version is deliberately report-only: it preserves TemplateOp/BinaryLayout
provenance in an `app*.conf` + `template/*.csv` + `generateGraph` directory
shape so the next pass can replace symbolic template-span rows with real vendor
CSV microprograms.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .binary_plan import BinaryInstructionPlan, BinaryLayoutPlan
from .template_ops import Diagnostic

CSV_HEADER = (
    "inst_name",
    "inst_tag_name",
    "src_reg_idx0",
    "src_reg_idx1",
    "dst_reg_idx",
    "dst_pe_idx",
    "imm",
    "iteration",
    "extra_field0",
    "extra_field1",
    "extra_field2",
)

PE_ARRAY_X_LEN = 4
PE_ARRAY_Y_LEN = 4
PE_AMOUNT = PE_ARRAY_X_LEN * PE_ARRAY_Y_LEN


@dataclass(frozen=True)
class VendorAssemblerCsvRow:
    inst_name: str
    inst_tag_name: str
    src_reg_idx0: str
    src_reg_idx1: str
    dst_reg_idx: str
    dst_pe_idx: int
    imm: int
    iteration: int
    extra_fields: tuple[int, int, int]
    source_instruction_row_id: str
    template_op_id: str
    primary_fiber_op_id: str
    source_schedule_step_id: str
    role: str
    phase: str
    stream_id: str | None
    row_status: str

    def to_csv_fields(self) -> tuple[str, ...]:
        return (
            self.inst_name,
            self.inst_tag_name,
            self.src_reg_idx0,
            self.src_reg_idx1,
            self.dst_reg_idx,
            str(self.dst_pe_idx),
            str(self.imm),
            str(self.iteration),
            str(self.extra_fields[0]),
            str(self.extra_fields[1]),
            str(self.extra_fields[2]),
        )

    def to_plan(self) -> dict[str, object]:
        return {
            "inst_name": self.inst_name,
            "inst_tag_name": self.inst_tag_name,
            "src_reg_idx0": self.src_reg_idx0,
            "src_reg_idx1": self.src_reg_idx1,
            "dst_reg_idx": self.dst_reg_idx,
            "dst_pe_idx": self.dst_pe_idx,
            "imm": self.imm,
            "iteration": self.iteration,
            "extra_fields": list(self.extra_fields),
            "source_instruction_row_id": self.source_instruction_row_id,
            "template_op_id": self.template_op_id,
            "primary_fiber_op_id": self.primary_fiber_op_id,
            "source_schedule_step_id": self.source_schedule_step_id,
            "role": self.role,
            "phase": self.phase,
            "stream_id": self.stream_id,
            "row_status": self.row_status,
        }


@dataclass(frozen=True)
class VendorAssemblerTemplateCsv:
    task_name: str
    subtask_name: str
    subtask_slot: str
    pe_idx: int
    pe_x: int
    pe_y: int
    rows: tuple[VendorAssemblerCsvRow, ...]

    @property
    def relative_path(self) -> str:
        return f"{self.task_name}/{self.subtask_name}/template/{self.pe_idx}.csv"

    def to_plan(self) -> dict[str, object]:
        return {
            "task_name": self.task_name,
            "subtask_name": self.subtask_name,
            "subtask_slot": self.subtask_slot,
            "pe_idx": self.pe_idx,
            "pe_x": self.pe_x,
            "pe_y": self.pe_y,
            "relative_path": self.relative_path,
            "row_count": len(self.rows),
            "rows": [row.to_plan() for row in self.rows],
        }


@dataclass(frozen=True)
class VendorAssemblerSubtaskPlan:
    task_name: str
    subtask_name: str
    subtask_slot: str
    instance_times: int
    code_path: str
    csv_amount: int
    graph_height: int
    graph_width: int
    template_csvs: tuple[VendorAssemblerTemplateCsv, ...]
    graph_plugin_status: str

    def to_plan(self) -> dict[str, object]:
        return {
            "task_name": self.task_name,
            "subtask_name": self.subtask_name,
            "subtask_slot": self.subtask_slot,
            "instance_times": self.instance_times,
            "code_path": self.code_path,
            "csv_amount": self.csv_amount,
            "graph_height": self.graph_height,
            "graph_width": self.graph_width,
            "graph_plugin_status": self.graph_plugin_status,
            "template_csvs": [csv_file.to_plan() for csv_file in self.template_csvs],
        }


@dataclass(frozen=True)
class VendorAssemblerTaskPlan:
    task_id: int
    task_name: str
    execute_times: int
    subtasks: tuple[VendorAssemblerSubtaskPlan, ...]

    def to_plan(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "execute_times": self.execute_times,
            "subtasks": [subtask.to_plan() for subtask in self.subtasks],
        }


@dataclass(frozen=True)
class VendorAssemblerInputBundle:
    profile_id: str
    runnability_state: str
    bundle_status: str
    assembler_ready: bool
    tasks: tuple[VendorAssemblerTaskPlan, ...]
    diagnostics: tuple[Diagnostic, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_vendor_assembler_input_bundle",
            "profile_id": self.profile_id,
            "runnability_state": self.runnability_state,
            "bundle_status": self.bundle_status,
            "assembler_ready": self.assembler_ready,
            "tasks": [task.to_plan() for task in self.tasks],
            "diagnostics": [diagnostic.to_plan() for diagnostic in self.diagnostics],
            "layering_policy": (
                "vendor_assembler_input_bundle_consumes_binary_layout_plan;"
                "emits_case_package_sources_without_vendor_binary_bytes"
            ),
        }


def build_vendor_assembler_input_bundle(
    layout: BinaryLayoutPlan,
) -> VendorAssemblerInputBundle:
    diagnostics = list(layout.diagnostics)
    rows_by_key: dict[tuple[int, str, int], list[VendorAssemblerCsvRow]] = {}
    task_ids: set[int] = set()
    subtask_slots_by_task: dict[int, set[str]] = {}

    for row in layout.instruction_rows:
        task_id = 0 if row.task_id is None else row.task_id
        pe_idx = _pe_idx_from_row(row)
        task_ids.add(task_id)
        subtask_slots_by_task.setdefault(task_id, set()).add(row.subtask_slot)
        rows_by_key.setdefault((task_id, row.subtask_slot, pe_idx), []).append(
            _csv_row_from_instruction(row)
        )
        if row.opcode == "GEMM_TILE_TEMPLATE_SPAN":
            diagnostics.append(
                Diagnostic(
                    severity="warning",
                    code="symbolic_template_span_not_vendor_csv",
                    subject_id=row.id,
                    message=(
                        "GEMM_TILE_TEMPLATE_SPAN is a B-line template intent; "
                        "it must be expanded to real vendor CSV rows before "
                        "this package can be assembled."
                    ),
                    evidence_refs=(
                        "docs/vendor_reference/common_oper/vendor-assembler-composition-rules.md",
                    ),
                )
            )

    tasks: list[VendorAssemblerTaskPlan] = []
    for task_id in sorted(task_ids or {0}):
        task_name = f"task{task_id}"
        subtasks: list[VendorAssemblerSubtaskPlan] = []
        for subtask_slot in sorted(
            subtask_slots_by_task.get(task_id, ()),
            key=_subtask_sort_key,
        ):
            subtask_name = _subtask_name_from_slot(subtask_slot)
            template_csvs: list[VendorAssemblerTemplateCsv] = []
            for pe_idx in range(PE_AMOUNT):
                pe_x = pe_idx // PE_ARRAY_Y_LEN
                pe_y = pe_idx % PE_ARRAY_Y_LEN
                csv_rows = tuple(
                    sorted(
                        rows_by_key.get((task_id, subtask_slot, pe_idx), ()),
                        key=lambda item: item.inst_tag_name,
                    )
                )
                template_csvs.append(
                    VendorAssemblerTemplateCsv(
                        task_name=task_name,
                        subtask_name=subtask_name,
                        subtask_slot=subtask_slot,
                        pe_idx=pe_idx,
                        pe_x=pe_x,
                        pe_y=pe_y,
                        rows=csv_rows,
                    )
                )
            subtasks.append(
                VendorAssemblerSubtaskPlan(
                    task_name=task_name,
                    subtask_name=subtask_name,
                    subtask_slot=subtask_slot,
                    instance_times=1,
                    code_path="template/",
                    csv_amount=PE_AMOUNT,
                    graph_height=PE_ARRAY_X_LEN,
                    graph_width=PE_ARRAY_Y_LEN,
                    template_csvs=tuple(template_csvs),
                    graph_plugin_status="source_only_report_not_built",
                )
            )
        tasks.append(
            VendorAssemblerTaskPlan(
                task_id=task_id,
                task_name=task_name,
                execute_times=1,
                subtasks=tuple(subtasks),
            )
        )

    assembler_ready = not any(
        diagnostic.severity == "error"
        or diagnostic.code == "symbolic_template_span_not_vendor_csv"
        for diagnostic in diagnostics
    )
    return VendorAssemblerInputBundle(
        profile_id=layout.profile_id,
        runnability_state=layout.runnability_state,
        bundle_status=(
            "assembler_minimal_candidate"
            if assembler_ready
            else "report_only_symbolic_csv_not_assembler_ready"
        ),
        assembler_ready=assembler_ready,
        tasks=tuple(tasks),
        diagnostics=tuple(diagnostics),
    )


def summarize_vendor_assembler_input_bundle(
    bundle: VendorAssemblerInputBundle,
) -> dict[str, object]:
    diagnostic_counts: dict[str, int] = {}
    csv_row_status_counts: dict[str, int] = {}
    subtask_count = 0
    template_csv_count = 0
    csv_row_count = 0
    nonempty_csv_count = 0

    for diagnostic in bundle.diagnostics:
        diagnostic_counts[diagnostic.severity] = (
            diagnostic_counts.get(diagnostic.severity, 0) + 1
        )
    for task in bundle.tasks:
        subtask_count += len(task.subtasks)
        for subtask in task.subtasks:
            template_csv_count += len(subtask.template_csvs)
            for template_csv in subtask.template_csvs:
                if template_csv.rows:
                    nonempty_csv_count += 1
                csv_row_count += len(template_csv.rows)
                for row in template_csv.rows:
                    csv_row_status_counts[row.row_status] = (
                        csv_row_status_counts.get(row.row_status, 0) + 1
                    )

    return {
        "schema_version": 1,
        "artifact": "b_line_vendor_assembler_input_bundle_summary",
        "profile_id": bundle.profile_id,
        "runnability_state": bundle.runnability_state,
        "bundle_status": bundle.bundle_status,
        "assembler_ready": bundle.assembler_ready,
        "task_count": len(bundle.tasks),
        "subtask_count": subtask_count,
        "template_csv_count": template_csv_count,
        "nonempty_template_csv_count": nonempty_csv_count,
        "csv_row_count": csv_row_count,
        "csv_row_status_counts": dict(sorted(csv_row_status_counts.items())),
        "diagnostic_severity_counts": dict(sorted(diagnostic_counts.items())),
        "diagnostic_count": len(bundle.diagnostics),
    }


def write_vendor_assembler_input_bundle(
    bundle: VendorAssemblerInputBundle,
    output_dir: Path,
) -> dict[str, object]:
    output_dir.mkdir(parents=True, exist_ok=True)
    _write_text(output_dir / "app0.conf", _render_app_conf(bundle))
    _write_text(output_dir / "README.md", _render_bundle_readme(bundle))
    _write_json(output_dir / "manifest.json", bundle.to_plan())
    _write_json(output_dir / "summary.json", summarize_vendor_assembler_input_bundle(bundle))
    _write_json(output_dir / "provenance.json", _provenance_payload(bundle))

    for task in bundle.tasks:
        for subtask in task.subtasks:
            subtask_root = output_dir / task.task_name / subtask.subtask_name
            template_root = subtask_root / "template"
            build_root = subtask_root / "build_so"
            template_root.mkdir(parents=True, exist_ok=True)
            build_root.mkdir(parents=True, exist_ok=True)
            for template_csv in subtask.template_csvs:
                _write_text(output_dir / template_csv.relative_path, _render_csv(template_csv))
            _write_text(
                build_root / "test_graph_extend.cpp",
                _render_generate_graph_source(),
            )
            _write_text(build_root / "Makefile", _render_report_only_makefile())
            _write_text(build_root / "README.md", _render_graph_plugin_readme(subtask))

    return summarize_vendor_assembler_input_bundle(bundle)


def _csv_row_from_instruction(row: BinaryInstructionPlan) -> VendorAssemblerCsvRow:
    return VendorAssemblerCsvRow(
        inst_name=row.opcode,
        inst_tag_name=f"bline_row_{row.row_index:06d}",
        src_reg_idx0="",
        src_reg_idx1="",
        dst_reg_idx=_sanitize_symbol(f"dst_{row.primary_fiber_op_id}"),
        dst_pe_idx=0,
        imm=0,
        iteration=1,
        extra_fields=(0, 0, 0),
        source_instruction_row_id=row.id,
        template_op_id=row.template_op_id,
        primary_fiber_op_id=row.primary_fiber_op_id,
        source_schedule_step_id=row.source_schedule_step_id,
        role=row.role,
        phase=row.phase,
        stream_id=row.stream_id,
        row_status=(
            "symbolic_template_span_needs_vendor_expansion"
            if row.opcode == "GEMM_TILE_TEMPLATE_SPAN"
            else "symbolic_csv_candidate"
        ),
    )


def _pe_idx_from_row(row: BinaryInstructionPlan) -> int:
    if row.stream_id is None:
        return 0
    match = re.search(r"_pe(?P<x>\d)(?P<y>\d)$", row.stream_id)
    if match is None:
        return 0
    pe_idx = int(match.group("x")) * PE_ARRAY_Y_LEN + int(match.group("y"))
    return pe_idx if 0 <= pe_idx < PE_AMOUNT else 0


def _subtask_name_from_slot(slot: str) -> str:
    match = re.match(r"^(subtask\d+)", slot)
    if match is not None:
        return match.group(1)
    return _sanitize_symbol(slot)


def _subtask_sort_key(slot: str) -> tuple[int, str]:
    match = re.match(r"^subtask(?P<index>\d+)", slot)
    if match is None:
        return (9999, slot)
    return (int(match.group("index")), slot)


def _sanitize_symbol(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_]+", "_", value).strip("_") or "symbol"


def _render_app_conf(bundle: VendorAssemblerInputBundle) -> str:
    lines: list[str] = []
    for task in bundle.tasks:
        lines.append(
            "task("
            f"task_name:{task.task_name};"
            "reuse_input_reg:;"
            "reuse_output_reg:;"
            f"Execute Times : {task.execute_times};"
            f"subtask_num:{len(task.subtasks)}"
            ")"
        )
        lines.append("{")
        for subtask in task.subtasks:
            lines.append(
                "subtask("
                f"subtask_name:{subtask.subtask_name};"
                "reuse_input_reg:;"
                "reuse_output_reg:;"
                f"Instance Times : {subtask.instance_times};"
                f"code_path:{subtask.code_path};"
                f"csv_amount:{subtask.csv_amount};"
                f"graph height:{subtask.graph_height};"
                f"graph width:{subtask.graph_width}"
                ")"
            )
        lines.append("}")
    return "\n".join(lines) + "\n"


def _render_csv(template_csv: VendorAssemblerTemplateCsv) -> str:
    lines = [",".join(CSV_HEADER)]
    lines.extend(",".join(row.to_csv_fields()) for row in template_csv.rows)
    return "\n".join(lines) + "\n"


def _render_generate_graph_source() -> str:
    return """#include "graph_extend.h"

extern "C" void generateGraph(
    string task_name,
    string subTask_name,
    vector<GRAPH_NODE>& m_nodes,
    Inst_Block_Collect& inst_block_collect,
    uint64_t graph_height,
    uint64_t graph_width) {
    const uint64_t node_amount = graph_height * graph_width;
    m_nodes.resize(node_amount);
    for (uint64_t index = 0; index < node_amount; ++index) {
        m_nodes[index].m_pos_idx_df = index;
        Graph_Extend::initNode(m_nodes[index], index, true, inst_block_collect);
    }
}
"""


def _render_report_only_makefile() -> str:
    return """# Report-only B-line graph plugin placeholder.
# Replace include/library paths with the vendor common_oper build environment
# before using this as an assembler input.

.PHONY: all
all:
\t@echo "report-only graph plugin source; vendor build wiring is not emitted yet"
\t@false
"""


def _render_bundle_readme(bundle: VendorAssemblerInputBundle) -> str:
    summary = summarize_vendor_assembler_input_bundle(bundle)
    return f"""# B-line Vendor Assembler Input Bundle

Status: {bundle.bundle_status}
Assembler ready: {str(bundle.assembler_ready).lower()}

This directory is a vendor-shaped case package projection. It intentionally
does not contain final CBUF/MICC bytes. `GEMM_TILE_TEMPLATE_SPAN` rows are still
symbolic TemplateOp spans and must be expanded to real vendor CSV rows before
invoking `build_app/common_oper`.

```json
{json.dumps(summary, indent=2, sort_keys=True)}
```
"""


def _render_graph_plugin_readme(subtask: VendorAssemblerSubtaskPlan) -> str:
    return f"""# {subtask.task_name}/{subtask.subtask_name} graph plugin

`test_graph_extend.cpp` maps each template CSV file to one graph node with
explicit `m_pos_idx_df = pe_idx`. This is the simple fixed-placement bridge
described by the vendor assembler composition rules.

Status: {subtask.graph_plugin_status}
"""


def _provenance_payload(bundle: VendorAssemblerInputBundle) -> dict[str, object]:
    rows: list[dict[str, object]] = []
    for task in bundle.tasks:
        for subtask in task.subtasks:
            for template_csv in subtask.template_csvs:
                for row in template_csv.rows:
                    rows.append(
                        {
                            "task_name": task.task_name,
                            "subtask_name": subtask.subtask_name,
                            "template_csv": template_csv.relative_path,
                            **row.to_plan(),
                        }
                    )
    return {
        "schema_version": 1,
        "artifact": "b_line_vendor_assembler_input_bundle_provenance",
        "profile_id": bundle.profile_id,
        "rows": rows,
    }


def _write_json(path: Path, payload: dict[str, object]) -> None:
    _write_text(path, json.dumps(payload, indent=2, sort_keys=True) + "\n")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


__all__ = [
    "VendorAssemblerCsvRow",
    "VendorAssemblerInputBundle",
    "VendorAssemblerSubtaskPlan",
    "VendorAssemblerTaskPlan",
    "VendorAssemblerTemplateCsv",
    "build_vendor_assembler_input_bundle",
    "summarize_vendor_assembler_input_bundle",
    "write_vendor_assembler_input_bundle",
]
