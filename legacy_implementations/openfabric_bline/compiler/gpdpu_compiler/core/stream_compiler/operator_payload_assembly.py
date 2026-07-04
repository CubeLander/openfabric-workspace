"""S3 fail-closed operator payload assembly reports.

This layer consumes status records from earlier/later stream artifacts and
produces honest local payload metadata.  It may expose section-level candidate
bytes, but it must remain fail-closed unless complete CBUF/MICC/runtime assets
and the local delivery gate are all proven.
"""

from __future__ import annotations

import hashlib
import json
import re
import struct
from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence

from gpdpu_compiler.core.dfu3500 import DFU3500_STRUCT_SIZES
from gpdpu_compiler.core.dfu3500.legacy_templates import (
    legacy_gemm_template_for_micro_block_kind,
)
from gpdpu_compiler.core.stream_compiler.micc_component_writers import (
    EXEBLOCK_CONF_FORMAT,
    EXEBLOCK_CONF_INFO_HEADER_FORMAT,
    EXEBLOCK_CONF_INFO_RECORD_SIZE,
)
from gpdpu_compiler.core.program_legacy_inst import pack_legacy_inst


AssemblyState = Literal["inspectable_shell", "blocked"]
GemmNoReluPayloadState = Literal["raw_inst_t_payload_candidate", "blocked"]
RuntimeReadyPreIntegrationState = Literal["ready", "blocked"]
StreamStage = Literal["S0", "S1", "S2", "S3", "S4", "S5", "S6"]
ShellSectionStatus = Literal["expected_not_emitted", "referenced", "blocked"]
ComponentAssemblyStatus = Literal[
    "candidate_available",
    "section_candidate_available",
    "blocked",
]

RUNTIME_READY_SCOPE = (
    "local structural/package readiness only; not a SimICT execution or "
    "operator numerical-correctness claim"
)
PLACEHOLDER_SHELL_RULE = (
    "placeholder_files_present => uploadable=false and runtime_ready=false"
)
EXPECTED_CBUF_SECTIONS = ("insts", "exeblock_conf_info", "instance_conf_info")
EXPECTED_MICC_SECTIONS = ("tasks_conf_info", "subtasks_conf_info")
SUPPORTED_OPERATORS = ("gemm_no_relu", "gemm_relu", "log10max")
INST_T_RECORD_SIZE_BYTES = int(DFU3500_STRUCT_SIZES["inst_t"])
LOG10MAX_RING_FIRST_BLOCKERS = (
    "task_axis_scope_unproven",
    "cross_task_one_app_ring_forbidden",
    "representative_selection_missing",
    "ring_edge_template_missing",
    "ring_edge_route_template_missing",
    "log10max_ring_update_template_missing",
    "log10max_ring_update_operand_placeholders_missing",
    "log10max_ring_update_operand_allocation_missing",
    "log10max_ring_update_inst_operand_patch_missing",
    "log10max_ring_update_row_bytes_missing",
    "route_role_globalmax_unproven",
    "route_path_proof_missing",
    "ring_phase_order_missing",
    "global_max_distribution_missing",
    "consumer_global_max_binding_missing",
    "consumer_depends_on_global_ready_missing",
    "ring_capacity_overflow",
    "dtype_update_op_mismatch",
    "symbolic_global_max_reaches_postprocess",
)


@dataclass(frozen=True)
class StreamArtifactStatus:
    """One upstream/downstream stream artifact status consumed by S3."""

    stage: StreamStage
    artifact: str
    status: str
    uploadable: bool = False
    runtime_ready: bool = False
    blockers: tuple[str, ...] = ()
    customer_labels: tuple[str, ...] = ()
    summary: Mapping[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "artifact": self.artifact,
            "status": self.status,
            "uploadable": self.uploadable,
            "runtime_ready": self.runtime_ready,
            "blockers": list(self.blockers),
            "customer_labels": list(self.customer_labels),
            "summary": dict(self.summary),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class PackageShellSection:
    """One expected package section in the shell assembly view."""

    name: str
    status: ShellSectionStatus
    required_for_runtime_ready: bool
    expected_files: tuple[str, ...] = ()
    expected_sections: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "status": self.status,
            "required_for_runtime_ready": self.required_for_runtime_ready,
            "expected_files": list(self.expected_files),
            "expected_sections": list(self.expected_sections),
            "blockers": list(self.blockers),
        }


@dataclass(frozen=True)
class PayloadCandidateFileRecord:
    """One file claim in a local payload candidate report."""

    path: str
    role: str
    size: int
    sha256: str
    source: str

    def to_plan(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "role": self.role,
            "size": self.size,
            "sha256": self.sha256,
            "source": self.source,
        }


@dataclass(frozen=True)
class ComponentAssemblySectionRecord:
    """One section state inside a local CBUF/MICC assembly candidate."""

    component: Literal["cbuf", "micc"]
    section: str
    status: ComponentAssemblyStatus
    role: str
    size: int = 0
    sha256: str | None = None
    source: str | None = None
    finalization_status: str = "blocked"
    finalization_requirements: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    proof_summary: Mapping[str, Any] = field(default_factory=dict)

    def to_plan(self) -> dict[str, Any]:
        return {
            "component": self.component,
            "section": self.section,
            "status": self.status,
            "role": self.role,
            "size": self.size,
            "sha256": self.sha256,
            "source": self.source,
            "finalization_status": self.finalization_status,
            "finalization_requirements": list(self.finalization_requirements),
            "blockers": list(self.blockers),
            "proof_summary": dict(self.proof_summary),
        }


@dataclass(frozen=True)
class GemmNoReluComponentPayloadCandidateReport:
    """GEMM no-ReLU local payload candidate below final CBUF/MICC assembly.

    This report consumes already-proven exact selectors and raw ``inst_t`` row
    bytes, then exposes file records that later S0/runtime gates can hash.  It
    intentionally does not claim final CBUF/MICC images or runtime readiness.
    """

    state: GemmNoReluPayloadState
    payload_root: str
    files: tuple[PayloadCandidateFileRecord, ...]
    cbuf_sections: tuple[ComponentAssemblySectionRecord, ...]
    micc_sections: tuple[ComponentAssemblySectionRecord, ...]
    raw_inst_t_row_count: int
    raw_inst_t_byte_count: int
    role_raw_row_counts: Mapping[str, int]
    role_raw_byte_counts: Mapping[str, int]
    blockers: tuple[str, ...]
    micc_final_candidate_summary: Mapping[str, Any] = field(default_factory=dict)
    runtime_ready_scope: str = RUNTIME_READY_SCOPE
    schema_version: int = 1

    @property
    def raw_inst_t_payload_present(self) -> bool:
        return any(file.role == "raw_inst_t_rows" for file in self.files)

    @property
    def payload_files_claimed(self) -> bool:
        return self.raw_inst_t_payload_present

    @property
    def cbuf_inst_section_candidate_present(self) -> bool:
        return any(
            section.component == "cbuf"
            and section.section == "insts"
            and section.status in {"candidate_available", "section_candidate_available"}
            for section in self.cbuf_sections
        )

    @property
    def final_cbuf_candidate_present(self) -> bool:
        return (
            self.cbuf_inst_section_candidate_present
            and all(section.status == "candidate_available" for section in self.cbuf_sections)
        )

    @property
    def final_micc_candidate_present(self) -> bool:
        return all(section.status == "candidate_available" for section in self.micc_sections)

    @property
    def runtime_ready(self) -> bool:
        return False

    @property
    def uploadable(self) -> bool:
        return False

    @property
    def final_state(self) -> str:
        if self.state == "raw_inst_t_payload_candidate":
            return "component_payload_candidate"
        return "blocked"

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact": "gemm_no_relu_component_payload_candidate",
            "operator": "gemm_no_relu",
            "state": self.state,
            "final_state": self.final_state,
            "payload_root": self.payload_root,
            "payload_files_claimed": self.payload_files_claimed,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "runtime_ready_scope": self.runtime_ready_scope,
            "raw_inst_t_payload_present": self.raw_inst_t_payload_present,
            "cbuf_inst_section_candidate_present": (
                self.cbuf_inst_section_candidate_present
            ),
            "final_cbuf_candidate_present": self.final_cbuf_candidate_present,
            "final_micc_candidate_present": self.final_micc_candidate_present,
            "raw_inst_t_row_count": self.raw_inst_t_row_count,
            "raw_inst_t_byte_count": self.raw_inst_t_byte_count,
            "role_raw_row_counts": dict(self.role_raw_row_counts),
            "role_raw_byte_counts": dict(self.role_raw_byte_counts),
            "files": [file.to_plan() for file in self.files],
            "cbuf_sections": [section.to_plan() for section in self.cbuf_sections],
            "micc_sections": [section.to_plan() for section in self.micc_sections],
            "micc_final_candidate_summary": dict(
                self.micc_final_candidate_summary
            ),
            "blockers": list(self.blockers),
            "layering_policy": (
                "gemm_no_relu_payload_candidate_consumes_exact_selector_raw_"
                "inst_t_bytes;does_not_mutate_fiber_semantics;does_not_claim_"
                "complete_cbuf_micc_runtime_assets;does_not_claim_runtime_ready"
            ),
        }


@dataclass(frozen=True)
class OperatorPayloadAssemblyReport:
    """S3 operator package shell report.

    ``uploadable`` and ``runtime_ready`` are derived fail-closed properties.
    Placeholder shell files always force both false.
    """

    operator: str
    state: AssemblyState
    stream_artifacts: tuple[StreamArtifactStatus, ...]
    package_shell_sections: tuple[PackageShellSection, ...]
    blockers: tuple[str, ...]
    placeholder_files_present: bool = False
    customer_bundle_metadata: Mapping[str, Any] = field(default_factory=dict)
    runtime_ready_scope: str = RUNTIME_READY_SCOPE
    schema_version: int = 1

    @property
    def uploadable(self) -> bool:
        if self.placeholder_files_present or self.state != "inspectable_shell":
            return False
        return all(artifact.uploadable for artifact in self.stream_artifacts)

    @property
    def runtime_ready(self) -> bool:
        if self.placeholder_files_present or self.state != "inspectable_shell":
            return False
        return all(artifact.runtime_ready for artifact in self.stream_artifacts)

    @property
    def final_state(self) -> str:
        if self.uploadable:
            return "uploadable"
        if self.runtime_ready:
            return "runtime_ready"
        return "blocked"

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact": "s3_operator_payload_assembly_report",
            "operator": self.operator,
            "state": self.state,
            "final_state": self.final_state,
            "uploadable": self.uploadable,
            "runtime_ready": self.runtime_ready,
            "runtime_ready_scope": self.runtime_ready_scope,
            "placeholder_files_present": self.placeholder_files_present,
            "placeholder_shell_rule": PLACEHOLDER_SHELL_RULE,
            "blockers": list(self.blockers),
            "stream_artifacts": [
                artifact.to_plan() for artifact in self.stream_artifacts
            ],
            "package_shell_sections": [
                section.to_plan() for section in self.package_shell_sections
            ],
            "customer_bundle_metadata": dict(self.customer_bundle_metadata),
            "layering_policy": (
                "s3_operator_payload_assembly_consumes_stream_artifact_statuses;"
                "does_not_emit_cbuf_micc_or_runtime_payload_bytes;"
                "does_not_mutate_frontend_or_op_time_low_level_state;"
                "placeholder_shells_are_never_uploadable"
            ),
        }


@dataclass(frozen=True)
class RuntimeReadyGateInputStatus:
    """One raw-bytes pre-integration input consumed by the runtime gate."""

    operator: str
    gate_id: str
    state: RuntimeReadyPreIntegrationState
    runtime_ready: bool
    uploadable: bool
    missing_blockers: tuple[str, ...]
    summary: Mapping[str, Any] = field(default_factory=dict)
    evidence_refs: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "gate_id": self.gate_id,
            "state": self.state,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "missing_blockers": list(self.missing_blockers),
            "summary": dict(self.summary),
            "evidence_refs": list(self.evidence_refs),
        }


@dataclass(frozen=True)
class RuntimeReadyPreIntegrationReport:
    """Fail-closed gate for raw-bytes/runtime proof pre-integration.

    This report is intentionally narrower than the full delivery validation
    framework.  It only decides whether the three B-line operator byte-path
    inputs are ready to be consumed by a future payload assembly step.
    """

    operator_statuses: tuple[RuntimeReadyGateInputStatus, ...]
    payload_files_claimed: bool = False
    placeholder_files_present: bool = False
    runtime_ready_scope: str = RUNTIME_READY_SCOPE
    schema_version: int = 1

    @property
    def missing_blockers(self) -> tuple[str, ...]:
        blockers: list[str] = []
        for status in self.operator_statuses:
            blockers.extend(
                "%s:%s:%s" % (status.operator, status.gate_id, blocker)
                for blocker in status.missing_blockers
            )
            if status.uploadable or status.runtime_ready:
                blockers.append(
                    "%s:%s_must_not_claim_runtime_ready_before_gate"
                    % (status.operator, status.gate_id)
                )
        if self.placeholder_files_present:
            blockers.append("placeholder_files_present")
        if not self.payload_files_claimed:
            blockers.append("payload_files_not_claimed_by_preintegration_gate")
        return tuple(blockers)

    @property
    def preintegration_ready(self) -> bool:
        return (
            not self.placeholder_files_present
            and all(status.state == "ready" for status in self.operator_statuses)
        )

    @property
    def runtime_ready(self) -> bool:
        return (
            self.preintegration_ready
            and self.payload_files_claimed
            and not self.missing_blockers
        )

    @property
    def uploadable(self) -> bool:
        return self.runtime_ready

    @property
    def final_state(self) -> str:
        if self.runtime_ready:
            return "runtime_ready"
        if self.preintegration_ready:
            return "preintegration_ready"
        return "blocked"

    def to_plan(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "artifact": "bline_runtime_ready_preintegration_report",
            "final_state": self.final_state,
            "preintegration_ready": self.preintegration_ready,
            "runtime_ready": self.runtime_ready,
            "uploadable": self.uploadable,
            "payload_files_claimed": self.payload_files_claimed,
            "placeholder_files_present": self.placeholder_files_present,
            "runtime_ready_scope": self.runtime_ready_scope,
            "missing_blockers": list(self.missing_blockers),
            "operator_statuses": [
                status.to_plan() for status in self.operator_statuses
            ],
            "layering_policy": (
                "preintegration_gate_consumes_raw_byte_and_runtime_proof_status;"
                "does_not_emit_inst_t_cbuf_micc_or_runtime_payload_bytes;"
                "does_not_mutate_fiber_template_semantics;"
                "package_shells_are_never_runtime_ready"
            ),
        }


def build_operator_payload_assembly_report(
    operator: str,
    *,
    stream_artifacts: Sequence[StreamArtifactStatus],
    placeholder_files_present: bool = False,
) -> OperatorPayloadAssemblyReport:
    """Build an S3 fail-closed package shell report for ``operator``."""

    if operator not in SUPPORTED_OPERATORS:
        raise ValueError("unsupported operator for S3 assembly shell: %s" % operator)

    blockers = _collect_blockers(stream_artifacts)
    if placeholder_files_present:
        blockers = blockers + ("placeholder_files_present",)
    state: AssemblyState = "inspectable_shell" if not blockers else "blocked"

    return OperatorPayloadAssemblyReport(
        operator=operator,
        state=state,
        stream_artifacts=tuple(stream_artifacts),
        package_shell_sections=_package_shell_sections(operator, blockers),
        blockers=blockers,
        placeholder_files_present=placeholder_files_present,
        customer_bundle_metadata=_customer_bundle_metadata(operator, stream_artifacts),
    )


def build_runtime_ready_preintegration_report(
    *,
    gemm_materialization_summary: Mapping[str, Any],
    gemm_selector_summary: Mapping[str, Any],
    relu_binding_summary: Mapping[str, Any],
    relu_writer_summary: Mapping[str, Any],
    log10max_collective_summary: Mapping[str, Any],
    log10max_collective_plan: Mapping[str, Any],
    gemm_payload_component_summary: Mapping[str, Any] | None = None,
    payload_files_claimed: bool = False,
    placeholder_files_present: bool = False,
) -> RuntimeReadyPreIntegrationReport:
    """Build the minimal fail-closed runtime_ready gate for B-line bytes."""

    return RuntimeReadyPreIntegrationReport(
        operator_statuses=(
            _gemm_raw_bytes_gate_status(
                gemm_materialization_summary,
                gemm_selector_summary,
                gemm_payload_component_summary,
            ),
            _relu_writer_gate_status(
                relu_binding_summary,
                relu_writer_summary,
            ),
            _log10max_pe00_gate_status(
                log10max_collective_summary,
                log10max_collective_plan,
            ),
        ),
        payload_files_claimed=payload_files_claimed,
        placeholder_files_present=placeholder_files_present,
    )


def build_gemm_no_relu_component_payload_candidate_report(
    materialization_report: Any,
    *,
    payload_root: str = "out/bline/gemm_no_relu",
    cbuf_exeblock_payload: bytes = b"",
    cbuf_instance_payload: bytes = b"",
    cbuf_exeblock_artifact_plan: Mapping[str, Any] | None = None,
    cbuf_instance_artifact_plan: Mapping[str, Any] | None = None,
    micc_subtask_artifact_plan: Mapping[str, Any] | None = None,
    micc_task_payload: bytes = b"",
    micc_subtask_payload: bytes = b"",
    micc_final_candidate_summary: Mapping[str, Any] | None = None,
) -> GemmNoReluComponentPayloadCandidateReport:
    """Build the GEMM no-ReLU raw-row payload candidate report.

    The report repacks exact selected legacy rows into the same raw bytes used
    by the materializer.  It does not write files here; it records the stable
    paths, sizes, and hashes that a package emitter can later materialize.
    """

    payload_bytes, role_row_counts, role_byte_counts, materializer_blockers = (
        _pack_raw_inst_t_rows_from_materialization_records(
            getattr(materialization_report, "records", ())
        )
    )
    files: list[PayloadCandidateFileRecord] = []
    cbuf_sections = _gemm_no_relu_cbuf_section_candidates(
        payload_bytes,
        cbuf_exeblock_payload=cbuf_exeblock_payload,
        cbuf_instance_payload=cbuf_instance_payload,
        cbuf_exeblock_artifact_plan=cbuf_exeblock_artifact_plan,
        cbuf_instance_artifact_plan=cbuf_instance_artifact_plan,
        micc_subtask_artifact_plan=micc_subtask_artifact_plan,
    )
    micc_sections = _gemm_no_relu_micc_section_candidates(
        task_payload=micc_task_payload,
        subtask_payload=micc_subtask_payload,
    )
    if payload_bytes:
        raw_record = PayloadCandidateFileRecord(
            path="config/raw_inst_t_rows.bin",
            role="raw_inst_t_rows",
            size=len(payload_bytes),
            sha256=hashlib.sha256(payload_bytes).hexdigest(),
            source="exact_selector_pack_legacy_inst",
        )
        manifest_seed = {
            "operator": "gemm_no_relu",
            "payload_root": payload_root,
            "raw_inst_t_file": raw_record.to_plan(),
            "raw_inst_t_row_count": sum(role_row_counts.values()),
            "role_raw_row_counts": dict(sorted(role_row_counts.items())),
            "runtime_ready": False,
            "uploadable": False,
        }
        manifest_bytes = json.dumps(
            manifest_seed,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        files.extend(
            (
                raw_record,
                PayloadCandidateFileRecord(
                    path="manifest/operator_payload_manifest.json",
                    role="payload_manifest",
                    size=len(manifest_bytes),
                    sha256=hashlib.sha256(manifest_bytes).hexdigest(),
                    source="gemm_no_relu_component_payload_candidate_report",
                ),
                PayloadCandidateFileRecord(
                    path="config/cbuf_file.insts_section.candidate.bin",
                    role="cbuf_insts_section_candidate",
                    size=len(payload_bytes),
                    sha256=hashlib.sha256(payload_bytes).hexdigest(),
                    source="raw_inst_t_rows_as_cbuf_insts_section_only",
                ),
            )
        )
    files.extend(
        _candidate_file_records_from_component_sections(cbuf_sections + micc_sections)
    )

    blockers = list(materializer_blockers)
    if not payload_bytes:
        blockers.append("raw_inst_t_rows_payload_not_materialized")
    blockers.extend(
        (
            _final_cbuf_blocker(cbuf_sections),
            _final_micc_blocker(micc_sections),
            "runtime_assets_not_emitted",
            "delivery_candidate_gate_not_run",
        )
    )
    if micc_final_candidate_summary:
        micc_status = str(micc_final_candidate_summary.get("status"))
        if micc_status != "final_micc_candidate_available":
            blockers.append("final_micc_candidate_blocked:%s" % micc_status)
        for blocker in micc_final_candidate_summary.get("blockers", ()):
            blockers.append("micc_final:%s" % blocker)
    state: GemmNoReluPayloadState = (
        "raw_inst_t_payload_candidate" if payload_bytes else "blocked"
    )
    return GemmNoReluComponentPayloadCandidateReport(
        state=state,
        payload_root=payload_root,
        files=tuple(files),
        cbuf_sections=cbuf_sections,
        micc_sections=micc_sections,
        raw_inst_t_row_count=sum(role_row_counts.values()),
        raw_inst_t_byte_count=sum(role_byte_counts.values()),
        role_raw_row_counts=dict(sorted(role_row_counts.items())),
        role_raw_byte_counts=dict(sorted(role_byte_counts.items())),
        blockers=tuple(_dedupe_preserve_order(blockers)),
        micc_final_candidate_summary=dict(micc_final_candidate_summary or {}),
    )


def summarize_gemm_no_relu_component_payload_candidate_report(
    report: GemmNoReluComponentPayloadCandidateReport,
) -> dict[str, Any]:
    """Return stable summary fields for the GEMM payload candidate gate."""

    raw_files = [file for file in report.files if file.role == "raw_inst_t_rows"]
    manifest_files = [file for file in report.files if file.role == "payload_manifest"]
    cbuf_inst_files = [
        file for file in report.files if file.role == "cbuf_insts_section_candidate"
    ]
    raw_file = raw_files[0] if raw_files else None
    manifest_file = manifest_files[0] if manifest_files else None
    cbuf_inst_file = cbuf_inst_files[0] if cbuf_inst_files else None
    return {
        "state": report.state,
        "final_state": report.final_state,
        "payload_files_claimed": report.payload_files_claimed,
        "raw_inst_t_payload_present": report.raw_inst_t_payload_present,
        "cbuf_inst_section_candidate_present": (
            report.cbuf_inst_section_candidate_present
        ),
        "final_cbuf_candidate_present": report.final_cbuf_candidate_present,
        "final_micc_candidate_present": report.final_micc_candidate_present,
        "runtime_ready": report.runtime_ready,
        "uploadable": report.uploadable,
        "payload_file_count": len(report.files),
        "raw_inst_t_row_count": report.raw_inst_t_row_count,
        "raw_inst_t_byte_count": report.raw_inst_t_byte_count,
        "raw_inst_t_file_size": None if raw_file is None else raw_file.size,
        "raw_inst_t_file_sha256": None if raw_file is None else raw_file.sha256,
        "manifest_file_size": None if manifest_file is None else manifest_file.size,
        "manifest_file_sha256": None if manifest_file is None else manifest_file.sha256,
        "cbuf_inst_section_file_size": (
            None if cbuf_inst_file is None else cbuf_inst_file.size
        ),
        "cbuf_inst_section_file_sha256": (
            None if cbuf_inst_file is None else cbuf_inst_file.sha256
        ),
        "cbuf_section_statuses": {
            section.section: section.status for section in report.cbuf_sections
        },
        "micc_section_statuses": {
            section.section: section.status for section in report.micc_sections
        },
        "cbuf_section_blockers": {
            section.section: list(section.blockers) for section in report.cbuf_sections
        },
        "micc_section_blockers": {
            section.section: list(section.blockers) for section in report.micc_sections
        },
        "cbuf_section_finalization_statuses": {
            section.section: section.finalization_status
            for section in report.cbuf_sections
        },
        "micc_section_finalization_statuses": {
            section.section: section.finalization_status
            for section in report.micc_sections
        },
        "cbuf_section_finalization_requirements": {
            section.section: list(section.finalization_requirements)
            for section in report.cbuf_sections
        },
        "cbuf_section_proof_summaries": {
            section.section: dict(section.proof_summary)
            for section in report.cbuf_sections
        },
        "micc_section_finalization_requirements": {
            section.section: list(section.finalization_requirements)
            for section in report.micc_sections
        },
        "micc_final_candidate_status": report.micc_final_candidate_summary.get(
            "status"
        ),
        "micc_final_section_statuses": dict(
            report.micc_final_candidate_summary.get("section_statuses", {})
        ),
        "micc_final_runtime_order_status": (
            report.micc_final_candidate_summary.get(
                "runtime_order_proof_plan", {}
            ).get("status")
            if isinstance(
                report.micc_final_candidate_summary.get("runtime_order_proof_plan"),
                Mapping,
            )
            else None
        ),
        "micc_final_blockers": list(
            report.micc_final_candidate_summary.get("blockers", ())
        ),
        "role_raw_row_counts": dict(report.role_raw_row_counts),
        "role_raw_byte_counts": dict(report.role_raw_byte_counts),
        "blocker_count": len(report.blockers),
        "blockers": list(report.blockers),
    }


def summarize_operator_payload_assembly_report(
    report: OperatorPayloadAssemblyReport,
) -> dict[str, Any]:
    """Return stable summary fields for focused checks and CLI output."""

    status_by_stage = {
        artifact.stage: artifact.status for artifact in report.stream_artifacts
    }
    return {
        "operator": report.operator,
        "state": report.state,
        "final_state": report.final_state,
        "uploadable": report.uploadable,
        "runtime_ready": report.runtime_ready,
        "placeholder_files_present": report.placeholder_files_present,
        "blocker_count": len(report.blockers),
        "blockers": list(report.blockers),
        "status_by_stage": status_by_stage,
        "customer_labels": list(
            report.customer_bundle_metadata.get("customer_labels", ())
        ),
        "package_shell_section_count": len(report.package_shell_sections),
    }


def summarize_runtime_ready_preintegration_report(
    report: RuntimeReadyPreIntegrationReport,
) -> dict[str, Any]:
    """Return stable summary fields for the B-line pre-integration gate."""

    return {
        "final_state": report.final_state,
        "preintegration_ready": report.preintegration_ready,
        "runtime_ready": report.runtime_ready,
        "uploadable": report.uploadable,
        "payload_files_claimed": report.payload_files_claimed,
        "placeholder_files_present": report.placeholder_files_present,
        "missing_blocker_count": len(report.missing_blockers),
        "missing_blockers": list(report.missing_blockers),
        "operator_states": {
            status.operator: status.state for status in report.operator_statuses
        },
        "operator_missing_counts": {
            status.operator: len(status.missing_blockers)
            for status in report.operator_statuses
        },
    }


def gemm_no_relu_stream_statuses(
    *,
    vendor_component_summary: Mapping[str, Any],
    serializer_summary: Mapping[str, Any],
    component_writer_summary: Mapping[str, Any],
    micc_component_writer_summary: Mapping[str, Any] | None = None,
) -> tuple[StreamArtifactStatus, ...]:
    """Build S0/S1/S2 status records for the current GEMM no-ReLU shell."""

    serializer_blockers = _serializer_blockers(serializer_summary)
    writer_status = str(component_writer_summary.get("writer_status"))
    writer_blockers = ()
    if writer_status != "debug_only":
        writer_blockers = ("S2_component_writer_not_debug_only",)
    else:
        writer_blockers = ("S2_component_writer_debug_only_not_runtime_payload",)
    micc_labels = _micc_writer_labels(micc_component_writer_summary)
    micc_blockers = _micc_writer_blockers(micc_component_writer_summary)
    micc_summary = (
        {"micc_component_writer": dict(micc_component_writer_summary)}
        if micc_component_writer_summary is not None
        else {}
    )

    return (
        StreamArtifactStatus(
            stage="S0",
            artifact="delivery_candidate_gate",
            status="referenced_not_run",
            blockers=("no payload directory generated by S3 shell",),
            customer_labels=("shell_only",),
            evidence_refs=(
                "compiler/gpdpu_compiler/validation/delivery_contracts.py",
                "compiler/tools/check_dfu_delivery_candidate.py",
            ),
        ),
        StreamArtifactStatus(
            stage="S1",
            artifact="vendor_component_plan",
            status=str(vendor_component_summary.get("runnability_state")),
            blockers=("S1_vendor_components_are_component_shaped_json_only",),
            customer_labels=("component_shell",),
            summary=dict(vendor_component_summary),
            evidence_refs=(
                "compiler/gpdpu_compiler/core/stream_compiler/vendor_components.py",
            ),
        ),
        StreamArtifactStatus(
            stage="S2",
            artifact="serializer_readiness_and_debug_writer",
            status=str(serializer_summary.get("runnability_state")),
            blockers=serializer_blockers + writer_blockers + micc_blockers,
            customer_labels=(
                "serializer_report_only",
                "debug_writer_only",
            )
            + micc_labels,
            summary={
                "serializer": dict(serializer_summary),
                "component_writer": dict(component_writer_summary),
                **micc_summary,
            },
            evidence_refs=(
                "compiler/gpdpu_compiler/core/stream_compiler/serializer_readiness.py",
                "compiler/gpdpu_compiler/core/stream_compiler/component_writers.py",
                "compiler/gpdpu_compiler/core/stream_compiler/micc_component_writers.py",
            ),
        ),
    )


def gemm_relu_stream_statuses(
    *,
    relu_binding_summary: Mapping[str, Any],
) -> tuple[StreamArtifactStatus, ...]:
    """Build S4 status records for GEMM+ReLU package metadata."""

    blockers = tuple(str(item) for item in relu_binding_summary.get("blockers", ()))
    if not blockers:
        blockers = (
            "explicit ReLU subtask binding is not concrete for runtime package",
        )
    return (
        StreamArtifactStatus(
            stage="S4",
            artifact="explicit_relu_subtask_binding",
            status=str(relu_binding_summary.get("binding_status")),
            blockers=blockers,
            customer_labels=(
                "blocked_symbolic_relu",
                "explicit_relu_subtask_candidate",
            ),
            summary=dict(relu_binding_summary),
            evidence_refs=(
                "compiler/gpdpu_compiler/core/stream_compiler/relu_binding.py",
            ),
        ),
    )


def log10max_stream_statuses(
    *,
    collective_summary: Mapping[str, Any],
    template_summary: Mapping[str, Any],
    route_role_summary: Mapping[str, Any] | None = None,
) -> tuple[StreamArtifactStatus, ...]:
    """Build S5/S6 status records for log10max package metadata."""

    s5_blockers = list(
        "S5_ring_first_%s" % blocker
        for blocker in LOG10MAX_RING_FIRST_BLOCKERS
    )
    if route_role_summary is None:
        s5_blockers.append(
            "S5_globalmax_route_role:route_role_binding_report_missing"
        )
    elif route_role_summary.get("proof_status") != "proven":
        route_role_blockers = tuple(
            str(blocker)
            for blocker in route_role_summary.get("blockers", ())
        ) or (
            "route_role_globalmax_proof_status=%s"
            % route_role_summary.get("proof_status"),
        )
        s5_blockers.extend(
            "S5_globalmax_route_role:%s" % blocker
            for blocker in route_role_blockers
        )
    s6_blockers = ()
    if not bool(template_summary.get("uploadable")):
        s6_blockers = (
            "S6_global_scalar_visibility_external_until_S5",
            "S6_symbolic_unresolved_count_for_uploadable=%s"
            % template_summary.get("symbolic_unresolved_count_for_uploadable"),
        )

    return (
        StreamArtifactStatus(
            stage="S5",
            artifact="log10max_ring_first_collective_strategy",
            status=str(
                collective_summary.get(
                    "ring_first_delivery_status",
                    collective_summary.get("delivery_status"),
                )
            ),
            blockers=s5_blockers,
            customer_labels=(
                "ring_spmd_row_then_col_first_delivery",
                "spmd_ring_materialized_reduce",
                "physical_allreduce_not_claimed",
                "internal_redundant_recompute_not_customer_delivery",
                "pe00_materialized_scalar_debug_escape_hatch",
                "globalmax_route_role_binding_required",
            ),
            summary=dict(
                collective_summary,
                globalmax_route_role_summary=(
                    {}
                    if route_role_summary is None
                    else dict(route_role_summary)
                ),
            ),
            evidence_refs=(
                "compiler/gpdpu_compiler/core/stream_compiler/"
                "log10max_collective_strategy.py",
                "compiler/gpdpu_compiler/core/stream_compiler/"
                "route_role_binding.py",
            ),
        ),
        StreamArtifactStatus(
            stage="S6",
            artifact="log10max_local_template_pack",
            status=str(template_summary.get("s6a_local_template_pack_status")),
            blockers=s6_blockers,
            customer_labels=("local_template_pack_report_only",),
            summary=dict(template_summary),
            evidence_refs=(
                "compiler/gpdpu_compiler/core/stream_compiler/"
                "log10max_template_pack.py",
            ),
        ),
    )


def _collect_blockers(
    stream_artifacts: Sequence[StreamArtifactStatus],
) -> tuple[str, ...]:
    blockers: list[str] = []
    for artifact in stream_artifacts:
        blockers.extend("%s:%s" % (artifact.stage, blocker) for blocker in artifact.blockers)
        if artifact.uploadable or artifact.runtime_ready:
            blockers.append(
                "%s:%s_must_not_claim_runtime_ready_in_shell"
                % (artifact.stage, artifact.artifact)
            )
    return tuple(blockers)


def _serializer_blockers(summary: Mapping[str, Any]) -> tuple[str, ...]:
    blockers = []
    blocked_struct_count = int(summary.get("blocked_struct_count", 0))
    blocked_field_count = int(summary.get("blocked_required_field_count", 0))
    if blocked_struct_count:
        blockers.append("S2_blocked_struct_count=%d" % blocked_struct_count)
    if blocked_field_count:
        blockers.append("S2_blocked_required_field_count=%d" % blocked_field_count)
    if str(summary.get("runnability_state")) == "report_only":
        blockers.append("S2_serializer_readiness_report_only")
    return tuple(blockers)


def _micc_writer_labels(
    summary: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    if summary is None:
        return ()

    labels: list[str] = []
    if _micc_selected_subtask_bytes_present(summary):
        labels.append("micc_selected_subtask_bytes_present")
    if summary.get("struct_name") == "sub_task_conf_info_t" and bool(
        summary.get("debug_only")
    ):
        labels.append("subtask_bytes_debug_only")
    return tuple(labels)


def _micc_writer_blockers(
    summary: Mapping[str, Any] | None,
) -> tuple[str, ...]:
    if summary is None:
        return ()
    if summary.get("struct_name") != "sub_task_conf_info_t":
        return ("S2_micc_subtask_writer_summary_missing",)
    if bool(summary.get("debug_only")):
        return ("S2_subtask_bytes_debug_only_not_runtime_payload",)
    return ("S2_micc_subtask_writer_not_debug_only",)


def _micc_selected_subtask_bytes_present(summary: Mapping[str, Any]) -> bool:
    selected_rows = summary.get("selected_rows")
    if not isinstance(selected_rows, int):
        selected_rows = 0
    row_status_counts = summary.get("row_status_counts")
    if isinstance(row_status_counts, Mapping):
        raw_selected = row_status_counts.get("selected", 0)
        if isinstance(raw_selected, int):
            selected_rows = max(selected_rows, raw_selected)

    return (
        summary.get("struct_name") == "sub_task_conf_info_t"
        and int(summary.get("payload_size_bytes", 0)) > 0
        and selected_rows > 0
    )


def _package_shell_sections(
    operator: str,
    blockers: Sequence[str],
) -> tuple[PackageShellSection, ...]:
    section_blockers = tuple(blockers) or ("runtime assets not emitted by S3 shell",)
    if operator == "gemm_no_relu":
        return (
            PackageShellSection(
                name="manifest",
                status="expected_not_emitted",
                required_for_runtime_ready=True,
                expected_files=("manifest.json",),
                blockers=section_blockers,
            ),
            PackageShellSection(
                name="runtime_assets",
                status="expected_not_emitted",
                required_for_runtime_ready=True,
                expected_files=(
                    "runtime/input_data.bin",
                    "runtime/runtime_control.json",
                    "reference/reference.json",
                ),
                blockers=section_blockers,
            ),
            PackageShellSection(
                name="cbuf",
                status="expected_not_emitted",
                required_for_runtime_ready=True,
                expected_files=("config/cbuf_file.bin",),
                expected_sections=EXPECTED_CBUF_SECTIONS,
                blockers=section_blockers,
            ),
            PackageShellSection(
                name="micc",
                status="expected_not_emitted",
                required_for_runtime_ready=True,
                expected_files=("config/micc_file.bin",),
                expected_sections=EXPECTED_MICC_SECTIONS,
                blockers=section_blockers,
            ),
        )
    return (
        PackageShellSection(
            name="customer_bundle_metadata",
            status="referenced",
            required_for_runtime_ready=False,
            expected_files=("metadata/operator_status.json",),
            blockers=section_blockers,
        ),
        PackageShellSection(
            name="runtime_binary_payload",
            status="blocked",
            required_for_runtime_ready=True,
            expected_files=("config/cbuf_file.bin", "config/micc_file.bin"),
            expected_sections=EXPECTED_CBUF_SECTIONS + EXPECTED_MICC_SECTIONS,
            blockers=section_blockers,
        ),
    )


def _customer_bundle_metadata(
    operator: str,
    artifacts: Sequence[StreamArtifactStatus],
) -> dict[str, Any]:
    labels: list[str] = ["not_uploadable", "runtime_ready_false"]
    stages: dict[str, str] = {}
    blockers: list[str] = []
    for artifact in artifacts:
        stages[artifact.stage] = artifact.status
        labels.extend(artifact.customer_labels)
        blockers.extend("%s:%s" % (artifact.stage, item) for item in artifact.blockers)

    return {
        "operator": operator,
        "customer_labels": sorted(set(labels)),
        "readiness": "blocked",
        "runtime_ready": False,
        "uploadable": False,
        "stage_status": stages,
        "blocked_reasons": blockers,
        "honesty_note": (
            "S3 shell metadata may enter a customer bundle, but it is not a "
            "runnable binary payload and must not be uploaded as runtime-ready."
        ),
    }


def _pack_raw_inst_t_rows_from_materialization_records(
    records: Sequence[Any],
) -> tuple[bytes, dict[str, int], dict[str, int], tuple[str, ...]]:
    payload_chunks: list[bytes] = []
    role_row_counts: dict[str, int] = {}
    role_byte_counts: dict[str, int] = {}
    blockers: list[str] = []
    for record in records:
        logical_row_id = str(getattr(record, "logical_row_id", "unknown"))
        role = str(getattr(record, "role", ""))
        opcode = str(getattr(record, "opcode", ""))
        if getattr(record, "byte_materializer_status", None) != (
            "raw_inst_t_row_bytes_available"
        ):
            blockers.append(
                "record_%s_raw_inst_t_bytes_not_available" % logical_row_id
            )
            continue
        block_kind = _legacy_block_kind_for_payload_record(role, opcode)
        if block_kind is None:
            blockers.append("record_%s_unsupported_role=%s" % (logical_row_id, role))
            continue
        template_index = getattr(record, "selected_template_index", None)
        selected_local_orders = tuple(getattr(record, "selected_local_orders", ()))
        if not isinstance(template_index, int):
            blockers.append("record_%s_template_index_missing" % logical_row_id)
            continue
        if not selected_local_orders:
            blockers.append("record_%s_selected_local_orders_missing" % logical_row_id)
            continue

        template = legacy_gemm_template_for_micro_block_kind(
            block_kind,
            task_index=_task_index_for_payload_record(record),
            template_index=template_index,
        )
        record_chunks: list[bytes] = []
        for local_order in selected_local_orders:
            if not isinstance(local_order, int):
                blockers.append(
                    "record_%s_non_integer_local_order=%s"
                    % (logical_row_id, local_order)
                )
                record_chunks = []
                break
            if local_order < 0 or local_order >= len(template):
                blockers.append(
                    "record_%s_local_order_out_of_range=%s"
                    % (logical_row_id, local_order)
                )
                record_chunks = []
                break
            record_chunks.append(pack_legacy_inst(template[local_order]))
        if not record_chunks:
            continue

        record_payload = b"".join(record_chunks)
        expected_size = len(record_chunks) * INST_T_RECORD_SIZE_BYTES
        if len(record_payload) != expected_size:
            blockers.append("record_%s_packed_size_mismatch" % logical_row_id)
            continue
        expected_hash = getattr(record, "raw_inst_t_row_bytes_sha256", None)
        actual_hash = hashlib.sha256(record_payload).hexdigest()
        if expected_hash and expected_hash != actual_hash:
            blockers.append("record_%s_raw_inst_t_sha256_mismatch" % logical_row_id)
            continue

        payload_chunks.append(record_payload)
        role_row_counts[role] = role_row_counts.get(role, 0) + len(record_chunks)
        role_byte_counts[role] = role_byte_counts.get(role, 0) + len(record_payload)

    return (
        b"".join(payload_chunks),
        role_row_counts,
        role_byte_counts,
        tuple(_dedupe_preserve_order(blockers)),
    )


def _legacy_block_kind_for_payload_record(role: str, opcode: str) -> str | None:
    if role == "compute_core:gemm_tile":
        return "compute_update"
    if role == "tile_store" and opcode == "STD":
        return "tile_store"
    return None


def _gemm_no_relu_cbuf_section_candidates(
    raw_inst_t_payload: bytes,
    *,
    cbuf_exeblock_payload: bytes = b"",
    cbuf_instance_payload: bytes = b"",
    cbuf_exeblock_artifact_plan: Mapping[str, Any] | None = None,
    cbuf_instance_artifact_plan: Mapping[str, Any] | None = None,
    micc_subtask_artifact_plan: Mapping[str, Any] | None = None,
) -> tuple[ComponentAssemblySectionRecord, ...]:
    insts_sha = hashlib.sha256(raw_inst_t_payload).hexdigest() if raw_inst_t_payload else None
    insts_status: ComponentAssemblyStatus = (
        "candidate_available" if raw_inst_t_payload else "blocked"
    )
    exeblock_proof = _exeblock_section_proof(
        cbuf_exeblock_payload,
        cbuf_exeblock_artifact_plan,
    )
    instance_proof = _instance_section_proof(
        cbuf_instance_payload,
        cbuf_instance_artifact_plan,
        micc_subtask_artifact_plan,
    )
    cbuf_layout_proof = _cbuf_section_offset_layout_proof(
        raw_inst_t_payload=raw_inst_t_payload,
        cbuf_exeblock_payload=cbuf_exeblock_payload,
        cbuf_instance_payload=cbuf_instance_payload,
        instance_section_final_candidate=bool(
            instance_proof.get("final_section_candidate")
        ),
    )
    exeblock_requirements = _exeblock_finalization_requirements(
        exeblock_proof,
        cbuf_layout_proof,
    )
    instance_status: ComponentAssemblyStatus = (
        "candidate_available"
        if bool(instance_proof.get("final_section_candidate"))
        else (
            "section_candidate_available"
            if cbuf_instance_payload
            else "blocked"
        )
    )
    return (
        ComponentAssemblySectionRecord(
            component="cbuf",
            section="insts",
            status=insts_status,
            role="raw_inst_t_rows",
            size=len(raw_inst_t_payload),
            sha256=insts_sha,
            source="exact_selector_pack_legacy_inst",
            finalization_status=(
                "final_section_candidate_available"
                if raw_inst_t_payload
                else "blocked_missing_raw_inst_t_rows"
            ),
            finalization_requirements=()
            if raw_inst_t_payload
            else ("raw_inst_t_rows_payload_not_materialized",),
            blockers=()
            if raw_inst_t_payload
            else ("raw_inst_t_rows_payload_not_materialized",),
            proof_summary={
                "section_offset_layout": cbuf_layout_proof.get("sections", {}).get(
                    "insts",
                    {},
                ),
                "section_offset_decode_roundtrip_status": cbuf_layout_proof.get(
                    "decode_roundtrip_status"
                ),
            },
        ),
        ComponentAssemblySectionRecord(
            component="cbuf",
            section="exeblock_conf_info",
            status="section_candidate_available"
            if cbuf_exeblock_payload
            else "blocked",
            role="exeBlock_conf_info_t",
            size=len(cbuf_exeblock_payload),
            sha256=hashlib.sha256(cbuf_exeblock_payload).hexdigest()
            if cbuf_exeblock_payload
            else None,
            source="debug_exeBlock_conf_info_t_writer"
            if cbuf_exeblock_payload
            else None,
            finalization_status="blocked_debug_only_candidate"
            if cbuf_exeblock_payload
            else "blocked_missing_section_bytes",
            finalization_requirements=exeblock_requirements
            if cbuf_exeblock_payload
            else ("exeBlock_conf_info_t_section_bytes",),
            blockers=_exeblock_section_blockers(exeblock_requirements)
            if cbuf_exeblock_payload
            else (
                "exeblock_conf_info_section_bytes_not_connected_to_cbuf_candidate",
            ),
            proof_summary={
                **exeblock_proof,
                "section_offset_layout": cbuf_layout_proof.get("sections", {}).get(
                    "exeblock_conf_info",
                    {},
                ),
                "section_offset_decode_roundtrip_status": cbuf_layout_proof.get(
                    "decode_roundtrip_status"
                ),
                "cbuf_candidate_total_size": cbuf_layout_proof.get(
                    "candidate_total_size"
                ),
            },
        ),
        ComponentAssemblySectionRecord(
            component="cbuf",
            section="instance_conf_info",
            status=instance_status,
            role="instance_conf_info_t",
            size=len(cbuf_instance_payload),
            sha256=hashlib.sha256(cbuf_instance_payload).hexdigest()
            if cbuf_instance_payload
            else (
                hashlib.sha256(b"").hexdigest()
                if bool(instance_proof.get("final_section_candidate"))
                else None
            ),
            source="debug_instance_conf_info_t_writer"
            if cbuf_instance_payload
            else (
                "zero_instance_control_empty_instance_section"
                if bool(instance_proof.get("final_section_candidate"))
                else None
            ),
            finalization_status=(
                "final_empty_section_candidate_available"
                if bool(instance_proof.get("final_section_candidate"))
                else (
                    "blocked_debug_only_candidate"
                    if cbuf_instance_payload
                    else "blocked_missing_instance_table_semantics"
                )
            ),
            finalization_requirements=()
            if bool(instance_proof.get("final_section_candidate"))
            else (
                (
                    "instance_conf_info_t_final_field_encoder",
                    "instance_base_addr_slots_proven",
                    "instances_conf_mem_based_addr_points_to_instance_section",
                    "final_cbuf_section_offset_layout",
                )
                if cbuf_instance_payload
                else tuple(str(item) for item in instance_proof.get("requirements", ()))
            ),
            blockers=()
            if bool(instance_proof.get("final_section_candidate"))
            else (
                (
                    "instance_conf_info_section_debug_only_not_final_cbuf_payload",
                )
                if cbuf_instance_payload
                else tuple(str(item) for item in instance_proof.get("blockers", ()))
            ),
            proof_summary={
                **instance_proof,
                "section_offset_layout": cbuf_layout_proof.get("sections", {}).get(
                    "instance_conf_info",
                    {},
                ),
                "section_offset_decode_roundtrip_status": cbuf_layout_proof.get(
                    "decode_roundtrip_status"
                ),
            },
        ),
    )


def _exeblock_section_proof(
    payload: bytes,
    artifact_plan: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not payload:
        return {"status": "missing_section_bytes"}
    record_size = int(DFU3500_STRUCT_SIZES["exeBlock_conf_info_t"])
    row_records = _mapping_rows(artifact_plan, "row_records")
    inst_addrs = [
        row.get("inst_mem_based_addr")
        for row in row_records
        if isinstance(row.get("inst_mem_based_addr"), int)
    ]
    aligned_addrs = [
        addr
        for addr in inst_addrs
        if isinstance(addr, int)
        and addr >= 0
        and addr % INST_T_RECORD_SIZE_BYTES == 0
    ]
    expected_rows = len(payload) // record_size if record_size else 0
    size_aligned = record_size > 0 and len(payload) % record_size == 0
    all_rows_packed = bool(row_records) and all(
        row.get("status") == "packed" for row in row_records
    )
    all_addrs_aligned = bool(row_records) and len(aligned_addrs) == len(row_records)
    decoded_roundtrip = _decode_exeblock_section_roundtrip(
        payload,
        row_records=row_records,
        record_size=record_size,
    )
    return {
        "status": "debug_candidate_bytes_available",
        "record_size_bytes": record_size,
        "payload_size_bytes": len(payload),
        "payload_size_aligned": size_aligned,
        "payload_row_count": expected_rows if size_aligned else None,
        "artifact_row_count": _optional_int_from_mapping(
            artifact_plan,
            "row_count",
        ),
        "row_record_count": len(row_records),
        "all_rows_packed": all_rows_packed,
        "inst_mem_based_addr_status": (
            "candidate_byte_offsets_aligned_to_inst_t"
            if all_addrs_aligned
            else "missing_or_unaligned_candidate_byte_offsets"
        ),
        "inst_mem_based_addr_unit": "bytes",
        "inst_mem_based_addr_alignment_bytes": INST_T_RECORD_SIZE_BYTES,
        "inst_mem_based_addr_min": min(inst_addrs) if inst_addrs else None,
        "inst_mem_based_addr_max": max(inst_addrs) if inst_addrs else None,
        "inst_mem_based_addr_distinct_values": sorted(set(inst_addrs)),
        "decode_roundtrip_status": decoded_roundtrip["status"],
        "decoded_row_count": decoded_roundtrip["decoded_row_count"],
        "decode_roundtrip_blockers": decoded_roundtrip["blockers"],
        "inst_mem_based_addr_decode_roundtrip_status": decoded_roundtrip[
            "inst_mem_based_addr_status"
        ],
        "inst_mem_based_addr_decoded_distinct_values": decoded_roundtrip[
            "inst_mem_based_addr_distinct_values"
        ],
        "final_field_encoder_status": decoded_roundtrip[
            "final_field_encoder_status"
        ],
        "final_field_encoder_source_backed_fields": decoded_roundtrip[
            "final_field_encoder_source_backed_fields"
        ],
        "final_field_encoder_missing_source_fields": decoded_roundtrip[
            "final_field_encoder_missing_source_fields"
        ],
        "final_field_encoder_policy": decoded_roundtrip[
            "final_field_encoder_policy"
        ],
        "endpoint_slots_status": (
            decoded_roundtrip["endpoint_slots_status"]
        ),
        "endpoint_slots_valid_counts": decoded_roundtrip[
            "endpoint_slots_valid_counts"
        ],
        "endpoint_slots_source_roundtrip_claim": decoded_roundtrip[
            "endpoint_slots_source_roundtrip_claim"
        ],
        "endpoint_slots_missing_source_fields": decoded_roundtrip[
            "endpoint_slots_missing_source_fields"
        ],
        "endpoint_slots_policy": decoded_roundtrip[
            "endpoint_slots_policy"
        ],
        "source": "exeBlock_conf_info_t_writer_artifact.row_records",
    }


def _instance_section_proof(
    payload: bytes,
    artifact_plan: Mapping[str, Any] | None,
    subtask_artifact_plan: Mapping[str, Any] | None,
) -> dict[str, Any]:
    instance_row_count = _optional_int_from_mapping(artifact_plan, "row_count")
    subtask_rows = _mapping_rows(subtask_artifact_plan, "row_records")
    selected_rows = [row for row in subtask_rows if row.get("status") == "selected"]
    zero_instance_rows = [
        row
        for row in selected_rows
        if row.get("instances_amount") == 0
        and row.get("instances_conf_mem_based_addr") == 0
        and row.get("selected_representation") == "zero_instance_control"
    ]
    all_selected_zero_instance = bool(selected_rows) and len(zero_instance_rows) == len(
        selected_rows
    )
    if payload:
        return {
            "status": "debug_instance_rows_available",
            "final_section_candidate": False,
            "instance_row_count": instance_row_count,
            "payload_size_bytes": len(payload),
            "requirements": (
                "instance_conf_info_t_final_field_encoder",
                "instances_conf_mem_based_addr_points_to_instance_section",
                "final_cbuf_section_offset_layout",
            ),
            "blockers": (
                "instance_conf_info_section_debug_only_not_final_cbuf_payload",
            ),
        }
    if instance_row_count == 0 and all_selected_zero_instance:
        return {
            "status": "empty_instance_section_consistent_with_zero_instance_control",
            "final_section_candidate": True,
            "instance_row_count": 0,
            "payload_size_bytes": 0,
            "selected_subtask_row_count": len(selected_rows),
            "zero_instance_subtask_row_count": len(zero_instance_rows),
            "instances_amount_policy": "instances_amount==0_address_zero_ignored",
            "requirements": (),
            "blockers": (),
        }
    requirements = (
        "resolve_subtask_instances_amount_zero_or_emit_instance_rows",
        "resolve_instances_conf_mem_based_addr",
        "connect_instance_conf_info_t_rows_to_cbuf_section",
    )
    return {
        "status": "empty_instance_section_without_complete_subtask_zero_proof",
        "final_section_candidate": False,
        "instance_row_count": instance_row_count,
        "payload_size_bytes": 0,
        "selected_subtask_row_count": len(selected_rows),
        "zero_instance_subtask_row_count": len(zero_instance_rows),
        "requirements": requirements,
        "blockers": (
            "instance_conf_info_section_empty_without_zero_instance_control_proof",
            "subtask_instances_conf_mem_based_addr_unresolved",
        ),
    }


def _cbuf_section_offset_layout_proof(
    *,
    raw_inst_t_payload: bytes,
    cbuf_exeblock_payload: bytes,
    cbuf_instance_payload: bytes,
    instance_section_final_candidate: bool,
) -> dict[str, Any]:
    insts_size = len(raw_inst_t_payload)
    exeblock_size = len(cbuf_exeblock_payload)
    instance_size = len(cbuf_instance_payload)
    instance_layout_known = instance_size > 0 or instance_section_final_candidate
    sections = {
        "insts": {
            "offset": 0,
            "size": insts_size,
            "present": bool(raw_inst_t_payload),
        },
        "exeblock_conf_info": {
            "offset": insts_size,
            "size": exeblock_size,
            "present": bool(cbuf_exeblock_payload),
        },
        "instance_conf_info": {
            "offset": insts_size + exeblock_size,
            "size": instance_size,
            "present": instance_layout_known,
            "empty_section": instance_size == 0 and instance_section_final_candidate,
        },
    }
    return {
        "status": (
            "candidate_section_offsets_known"
            if raw_inst_t_payload and cbuf_exeblock_payload and instance_layout_known
            else "blocked_missing_section_for_offset_layout"
        ),
        "sections": sections,
        "candidate_total_size": insts_size + exeblock_size + instance_size,
        "decode_roundtrip_status": (
            "candidate_section_offsets_decode_roundtrip_available"
            if raw_inst_t_payload and cbuf_exeblock_payload and instance_layout_known
            else "blocked_missing_section_for_offset_decode_roundtrip"
        ),
        "decode_roundtrip_claim": bool(
            raw_inst_t_payload and cbuf_exeblock_payload and instance_layout_known
        ),
        "final_layout_claim": False,
        "final_layout_blocker": "exeblock_section_still_debug_only",
    }


def _exeblock_finalization_requirements(
    exeblock_proof: Mapping[str, Any],
    layout_proof: Mapping[str, Any],
) -> tuple[str, ...]:
    requirements = []
    if exeblock_proof.get("final_field_encoder_status") != (
        "candidate_final_field_encoder_source_roundtrip_available"
    ):
        requirements.append("exeBlock_conf_info_t_source_field_provenance")
    if exeblock_proof.get("endpoint_slots_status") != (
        "decoded_endpoint_slots_match_source_records"
    ):
        requirements.append("endpoint_slots_source_records")
    if (
        exeblock_proof.get("inst_mem_based_addr_decode_roundtrip_status")
        != "decoded_field_matches_writer_records"
    ):
        requirements.append("inst_mem_based_addr_decode_roundtrip_proof")
    if (
        layout_proof.get("decode_roundtrip_status")
        != "candidate_section_offsets_decode_roundtrip_available"
    ):
        requirements.append("final_cbuf_section_offset_layout")
    return tuple(requirements)


def _decode_exeblock_section_roundtrip(
    payload: bytes,
    *,
    row_records: Sequence[Mapping[str, Any]],
    record_size: int,
) -> dict[str, Any]:
    """Decode debug exeBlock rows and compare fields preserved in row records."""

    blockers: list[str] = []
    if record_size != EXEBLOCK_CONF_INFO_RECORD_SIZE:
        blockers.append("record_size_drift")
    if record_size <= 0 or len(payload) % record_size != 0:
        blockers.append("payload_size_not_aligned_to_exeBlock_conf_info_t")
        return _exeblock_decode_roundtrip_summary((), blockers, row_records=())

    header_size = struct.calcsize(EXEBLOCK_CONF_INFO_HEADER_FORMAT)
    decoded_rows: list[dict[str, Any]] = []
    for row_index, start in enumerate(range(0, len(payload), record_size)):
        chunk = payload[start : start + record_size]
        try:
            header = struct.unpack(
                EXEBLOCK_CONF_INFO_HEADER_FORMAT,
                chunk[:header_size],
            )
            inner = struct.unpack(EXEBLOCK_CONF_FORMAT, chunk[header_size:])
        except struct.error:
            blockers.append("row_%d_decode_failed" % row_index)
            continue
        decoded = {
            "row_index": row_index,
            "valid": header[0],
            "header_block_idx": header[1],
            "pe_dst": {"x": header[2], "y": header[3], "z": header[4]},
            "priority": header[5],
            "req_activations": inner[0],
            "predecessors": tuple(inner[11:31]),
            "successors": tuple(inner[31:51]),
            "block_idx": inner[51],
            "subtask_idx": inner[52],
            "task_idx": inner[53],
            "instances_amount": inner[54],
            "child_amount": inner[55],
            "block_class": inner[56],
            "inst_mem_based_addr": inner[57],
            "is_leaf": inner[62],
        }
        decoded_rows.append(decoded)
        if row_index >= len(row_records):
            blockers.append("row_%d_missing_writer_record" % row_index)
            continue
        record = row_records[row_index]
        for field in (
            "block_idx",
            "task_idx",
            "subtask_idx",
            "pe_dst",
            "req_activations",
            "child_amount",
            "inst_mem_based_addr",
        ):
            if decoded[field] != record.get(field):
                blockers.append("row_%d_%s_roundtrip_mismatch" % (row_index, field))
        if decoded["header_block_idx"] != record.get("block_idx"):
            blockers.append("row_%d_header_block_idx_roundtrip_mismatch" % row_index)
        if decoded["is_leaf"] != record.get("is_leaf_serialized"):
            blockers.append("row_%d_is_leaf_serialization_mismatch" % row_index)

    if len(decoded_rows) != len(row_records):
        blockers.append("decoded_row_count_does_not_match_writer_records")
    return _exeblock_decode_roundtrip_summary(
        decoded_rows,
        blockers,
        row_records=row_records,
    )


def _exeblock_decode_roundtrip_summary(
    decoded_rows: Sequence[Mapping[str, Any]],
    blockers: Sequence[str],
    *,
    row_records: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    inst_values = [
        row.get("inst_mem_based_addr")
        for row in decoded_rows
        if isinstance(row.get("inst_mem_based_addr"), int)
    ]
    endpoint_counts = {
        "predecessor_valid_total": sum(
            _endpoint_valid_count(row.get("predecessors")) for row in decoded_rows
        ),
        "successor_valid_total": sum(
            _endpoint_valid_count(row.get("successors")) for row in decoded_rows
        ),
    }
    status = (
        "decoded_roundtrip_available"
        if decoded_rows and not blockers
        else "blocked_decode_roundtrip_missing"
    )
    final_field_proof = _exeblock_final_field_encoder_proof(
        decoded_rows,
        row_records=row_records,
        blockers=blockers,
    )
    endpoint_proof = _exeblock_endpoint_source_roundtrip_proof(
        decoded_rows,
        row_records=row_records,
        blockers=blockers,
    )
    return {
        "status": status,
        "decoded_row_count": len(decoded_rows),
        "blockers": list(blockers),
        "inst_mem_based_addr_status": (
            "decoded_field_matches_writer_records"
            if decoded_rows and not blockers
            else "blocked_missing_inst_mem_based_addr_roundtrip"
        ),
        "inst_mem_based_addr_distinct_values": sorted(set(inst_values)),
        "final_field_encoder_status": final_field_proof["status"],
        "final_field_encoder_source_backed_fields": final_field_proof[
            "source_backed_fields"
        ],
        "final_field_encoder_missing_source_fields": final_field_proof[
            "missing_source_fields"
        ],
        "final_field_encoder_policy": final_field_proof["policy"],
        "endpoint_slots_status": endpoint_proof["status"],
        "endpoint_slots_valid_counts": endpoint_counts,
        "endpoint_slots_source_roundtrip_claim": endpoint_proof[
            "source_roundtrip_claim"
        ],
        "endpoint_slots_missing_source_fields": endpoint_proof[
            "missing_source_fields"
        ],
        "endpoint_slots_policy": endpoint_proof["policy"],
    }


def _exeblock_final_field_encoder_proof(
    decoded_rows: Sequence[Mapping[str, Any]],
    *,
    row_records: Sequence[Mapping[str, Any]],
    blockers: Sequence[str],
) -> dict[str, Any]:
    source_backed_fields = (
        "block_idx",
        "task_idx",
        "subtask_idx",
        "pe_dst",
        "req_activations",
        "child_amount",
        "inst_mem_based_addr",
        "is_leaf_serialized",
    )
    required_source_fields = source_backed_fields + (
        "valid",
        "priority",
        "has_stages",
        "stages_start_pc",
        "predecessors",
        "successors",
        "instances_amount",
        "block_class",
        "stage_inst_amounts",
    )
    missing = _missing_record_fields(row_records, required_source_fields)
    if not decoded_rows or blockers:
        status = "blocked_final_field_encoder_decode_roundtrip_missing"
    elif not missing:
        status = "candidate_final_field_encoder_source_roundtrip_available"
    else:
        status = "blocked_source_field_provenance_missing"
    return {
        "status": status,
        "source_backed_fields": list(source_backed_fields),
        "missing_source_fields": list(missing),
        "policy": (
            "final exeBlock_conf_info_t encoder requires every serialized field "
            "to be source-backed in the writer artifact; debug-only zero/default "
            "fields are not promoted to runtime CBUF claims"
        ),
    }


def _exeblock_endpoint_source_roundtrip_proof(
    decoded_rows: Sequence[Mapping[str, Any]],
    *,
    row_records: Sequence[Mapping[str, Any]],
    blockers: Sequence[str],
) -> dict[str, Any]:
    required_fields = ("predecessors", "successors")
    missing = _missing_record_fields(row_records, required_fields)
    source_roundtrip_claim = False
    if not decoded_rows or blockers:
        status = "blocked_endpoint_slots_decode_roundtrip_missing"
    elif missing:
        status = "blocked_source_endpoint_records_missing"
    else:
        mismatches: list[str] = []
        for index, decoded in enumerate(decoded_rows):
            record = row_records[index]
            for field in required_fields:
                if tuple(decoded.get(field, ())) != tuple(record.get(field, ())):
                    mismatches.append(f"row_{index}_{field}_source_roundtrip_mismatch")
        if mismatches:
            status = "blocked_endpoint_slots_source_roundtrip_mismatch"
        else:
            status = "decoded_endpoint_slots_match_source_records"
            source_roundtrip_claim = True
    return {
        "status": status,
        "source_roundtrip_claim": source_roundtrip_claim,
        "missing_source_fields": list(missing),
        "policy": (
            "endpoint slots are final only when decoded predecessor/successor "
            "slots roundtrip against source endpoint records, not merely when "
            "debug bytes can be unpacked"
        ),
    }


def _missing_record_fields(
    row_records: Sequence[Mapping[str, Any]],
    fields: Sequence[str],
) -> tuple[str, ...]:
    if not row_records:
        return tuple(fields)
    missing: list[str] = []
    for field in fields:
        if any(field not in record for record in row_records):
            missing.append(field)
    return tuple(missing)


def _endpoint_valid_count(value: object) -> int:
    if not isinstance(value, Sequence) or isinstance(value, (str, bytes)):
        return 0
    return sum(
        1
        for index, slot_value in enumerate(value)
        if index % 5 == 4 and slot_value == 1
    )


def _exeblock_section_blockers(
    requirements: Sequence[str],
) -> tuple[str, ...]:
    blockers = ["exeblock_conf_info_section_debug_only_not_final_cbuf_payload"]
    if "exeBlock_conf_info_t_final_field_encoder" in requirements:
        blockers.append("exeBlock_conf_info_t_final_field_encoder_missing")
    if "exeBlock_conf_info_t_source_field_provenance" in requirements:
        blockers.append("exeBlock_conf_info_t_source_field_provenance_missing")
    if "endpoint_slots_debug_encoding_decode_roundtrip" in requirements:
        blockers.append("endpoint_slots_source_roundtrip_missing")
    if "endpoint_slots_source_records" in requirements:
        blockers.append("endpoint_slots_source_records_missing")
    if "inst_mem_based_addr_decode_roundtrip_proof" in requirements:
        blockers.append("inst_mem_based_addr_decode_roundtrip_missing")
    if "final_cbuf_section_offset_decode_roundtrip" in requirements:
        blockers.append("final_cbuf_section_offset_decode_roundtrip_missing")
    return tuple(blockers)


def _mapping_rows(
    mapping: Mapping[str, Any] | None,
    key: str,
) -> tuple[Mapping[str, Any], ...]:
    if mapping is None:
        return ()
    rows = mapping.get(key)
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        return ()
    return tuple(row for row in rows if isinstance(row, Mapping))


def _optional_int_from_mapping(
    mapping: Mapping[str, Any] | None,
    key: str,
) -> int | None:
    if mapping is None:
        return None
    value = mapping.get(key)
    return value if isinstance(value, int) else None


def _gemm_no_relu_micc_section_candidates(
    *,
    task_payload: bytes = b"",
    subtask_payload: bytes = b"",
) -> tuple[ComponentAssemblySectionRecord, ...]:
    return (
        ComponentAssemblySectionRecord(
            component="micc",
            section="tasks_conf_info",
            status="section_candidate_available" if task_payload else "blocked",
            role="task_conf_info_t",
            size=len(task_payload),
            sha256=hashlib.sha256(task_payload).hexdigest() if task_payload else None,
            source="debug_task_conf_info_t_writer" if task_payload else None,
            finalization_status="blocked_debug_only_candidate"
            if task_payload
            else "blocked_missing_section_bytes",
            finalization_requirements=(
                "task_conf_info_t_final_field_encoder",
                "active_subtask_indices_binary_encoding",
                "final_micc_section_offset_layout",
            )
            if task_payload
            else ("task_conf_info_t_section_bytes",),
            blockers=(
                "task_conf_info_section_debug_only_not_final_micc_payload",
            )
            if task_payload
            else ("task_conf_info_section_bytes_not_connected_to_micc_candidate",),
        ),
        ComponentAssemblySectionRecord(
            component="micc",
            section="subtasks_conf_info",
            status="section_candidate_available" if subtask_payload else "blocked",
            role="sub_task_conf_info_t",
            size=len(subtask_payload),
            sha256=hashlib.sha256(subtask_payload).hexdigest()
            if subtask_payload
            else None,
            source="debug_sub_task_conf_info_t_writer" if subtask_payload else None,
            finalization_status="blocked_debug_only_candidate"
            if subtask_payload
            else "blocked_missing_section_bytes",
            finalization_requirements=(
                "sub_task_conf_info_t_final_field_encoder",
                "instances_amount_and_instances_conf_mem_based_addr_policy",
                "successor_subtask_indices_binary_encoding",
                "embedded_exeblock_indices_binary_encoding",
                "final_micc_section_offset_layout",
            )
            if subtask_payload
            else ("sub_task_conf_info_t_section_bytes",),
            blockers=(
                "sub_task_conf_info_section_bytes_debug_only_not_final_micc_candidate",
            )
            if subtask_payload
            else (
                "sub_task_conf_info_section_bytes_not_connected_to_micc_candidate",
            ),
        ),
    )


def _final_cbuf_blocker(
    sections: Sequence[ComponentAssemblySectionRecord],
) -> str:
    missing = [
        section.section
        for section in sections
        if section.status == "blocked"
    ]
    debug_only = [
        section.section
        for section in sections
        if section.status == "section_candidate_available"
    ]
    blockers = []
    if missing:
        blockers.append("missing_sections=%s" % ",".join(missing))
    if debug_only:
        blockers.append("debug_only_sections=%s" % ",".join(debug_only))
    if not blockers:
        blockers.append("section_layout_not_concatenated")
    return "final_cbuf_file_not_assembled:%s" % ";".join(blockers)


def _final_micc_blocker(
    sections: Sequence[ComponentAssemblySectionRecord],
) -> str:
    missing = [
        section.section
        for section in sections
        if section.status == "blocked"
    ]
    debug_only = [
        section.section
        for section in sections
        if section.status == "section_candidate_available"
    ]
    blockers = []
    if missing:
        blockers.append("missing_sections=%s" % ",".join(missing))
    if debug_only:
        blockers.append("debug_only_sections=%s" % ",".join(debug_only))
    if not blockers:
        blockers.append("section_layout_not_concatenated")
    return "final_micc_file_not_assembled:%s" % ";".join(blockers)


def _candidate_file_records_from_component_sections(
    sections: Sequence[ComponentAssemblySectionRecord],
) -> tuple[PayloadCandidateFileRecord, ...]:
    records: list[PayloadCandidateFileRecord] = []
    for section in sections:
        if section.status != "section_candidate_available":
            continue
        if not section.sha256 or section.size <= 0:
            continue
        records.append(
            PayloadCandidateFileRecord(
                path=(
                    "config/%s_file.%s_section.candidate.bin"
                    % (section.component, section.section)
                ),
                role="%s_%s_section_candidate" % (section.component, section.section),
                size=section.size,
                sha256=section.sha256,
                source=section.source or "component_section_candidate",
            )
        )
    return tuple(records)


def _task_index_for_payload_record(record: Any) -> int:
    task_id = getattr(record, "task_id", None)
    if isinstance(task_id, int) and task_id >= 0:
        return task_id
    logical_row_id = str(getattr(record, "logical_row_id", ""))
    match = re.search(r":fiber:t(\d+)_", logical_row_id)
    if match:
        return int(match.group(1))
    return 0


def _gemm_raw_bytes_gate_status(
    materialization_summary: Mapping[str, Any],
    selector_summary: Mapping[str, Any],
    payload_component_summary: Mapping[str, Any] | None = None,
) -> RuntimeReadyGateInputStatus:
    missing = _counter_blockers(
        "byte_materializer",
        materialization_summary.get("missing_byte_materializer_input_counts"),
    )
    if materialization_summary.get("bytes_emitted") is not True:
        missing.append("raw_inst_t_bytes_not_emitted")
    if materialization_summary.get("raw_overlay_consumable_count", 0) != 0:
        missing.append("raw_overlay_consumable_must_remain_zero")
    if selector_summary.get("bytes_emitted") is not False:
        missing.append("selector_report_must_not_emit_bytes")
    payload_summary = (
        {}
        if payload_component_summary is None
        else dict(payload_component_summary)
    )
    if payload_component_summary is not None:
        if payload_summary.get("raw_inst_t_payload_present") is not True:
            missing.append("gemm_raw_inst_t_payload_file_missing")
        if payload_summary.get("payload_files_claimed") is not True:
            missing.append("gemm_payload_files_not_claimed")
        expected_bytes = materialization_summary.get("raw_inst_t_byte_count")
        if payload_summary.get("raw_inst_t_file_size") != expected_bytes:
            missing.append(
                "gemm_raw_inst_t_payload_size_mismatch=%s!=%s"
                % (payload_summary.get("raw_inst_t_file_size"), expected_bytes)
            )

    state: RuntimeReadyPreIntegrationState = "ready" if not missing else "blocked"
    return RuntimeReadyGateInputStatus(
        operator="gemm_no_relu",
        gate_id="gemm_raw_bytes_and_hash",
        state=state,
        runtime_ready=False,
        uploadable=False,
        missing_blockers=tuple(missing),
        summary={
            "materialization_status": materialization_summary.get(
                "materialization_status"
            ),
            "instruction_row_count": materialization_summary.get(
                "instruction_row_count"
            ),
            "byte_materializer_status_counts": dict(
                materialization_summary.get("byte_materializer_status_counts", {})
            ),
            "missing_byte_materializer_input_counts": dict(
                materialization_summary.get(
                    "missing_byte_materializer_input_counts", {}
                )
            ),
            "selector_status_counts": dict(
                selector_summary.get("selector_status_counts", {})
            ),
            "role_selected_row_counts": dict(
                selector_summary.get("role_selected_row_counts", {})
            ),
            "bytes_emitted": materialization_summary.get("bytes_emitted"),
            "payload_component": payload_summary,
        },
        evidence_refs=(
            "compiler/gpdpu_compiler/core/stream_compiler/inst_writers.py",
            "compiler/tools/check_stream_compiler_no_relu_safe_subset.py",
        ),
    )


def _relu_writer_gate_status(
    relu_binding_summary: Mapping[str, Any],
    relu_writer_summary: Mapping[str, Any],
) -> RuntimeReadyGateInputStatus:
    missing: list[str] = []
    if relu_binding_summary.get("binding_status") != "ready":
        missing.append(
            "relu_binding_status=%s" % relu_binding_summary.get("binding_status")
        )
    missing.extend(
        "relu_p0_blocker=%s" % blocker
        for blocker in relu_binding_summary.get("p0_blocker_ids", ())
    )
    if relu_writer_summary.get("binding_status") != "ready":
        missing.append(
            "relu_writer_status=%s" % relu_writer_summary.get("binding_status")
        )
    relu_rows = (
        relu_writer_summary.get("role_opcode_candidate_raw_row_counts", {})
        .get("tile_op:relu|HMAX", {})
    )
    if relu_rows.get("single_candidate_row_count") != 64:
        missing.append("relu_exact_hmax_rows_missing")
    if relu_writer_summary.get("missing_raw_template_bytes_count", 0):
        missing.append(
            "relu_missing_raw_template_bytes=%s"
            % relu_writer_summary.get("missing_raw_template_bytes_count")
        )

    state: RuntimeReadyPreIntegrationState = "ready" if not missing else "blocked"
    return RuntimeReadyGateInputStatus(
        operator="gemm_relu",
        gate_id="relu_row_writer",
        state=state,
        runtime_ready=False,
        uploadable=False,
        missing_blockers=tuple(missing),
        summary={
            "binding_status": relu_binding_summary.get("binding_status"),
            "binding_count": relu_binding_summary.get("binding_count"),
            "concrete_relu_template_count": relu_binding_summary.get(
                "concrete_relu_template_count"
            ),
            "p0_blocker_ids": list(relu_binding_summary.get("p0_blocker_ids", ())),
            "writer_binding_status": relu_writer_summary.get("binding_status"),
            "writer_binding_status_counts": dict(
                relu_writer_summary.get("binding_status_counts", {})
            ),
            "relu_hmax_candidate_rows": dict(relu_rows),
        },
        evidence_refs=(
            "compiler/gpdpu_compiler/core/stream_compiler/relu_binding.py",
            "compiler/tools/check_stream_compiler_relu_fiber_chain.py",
        ),
    )


def _log10max_pe00_gate_status(
    collective_summary: Mapping[str, Any],
    collective_plan: Mapping[str, Any],
) -> RuntimeReadyGateInputStatus:
    return _log10max_ring_first_gate_status(
        collective_summary,
        collective_plan,
    )


def _log10max_ring_first_gate_status(
    collective_summary: Mapping[str, Any],
    collective_plan: Mapping[str, Any],
) -> RuntimeReadyGateInputStatus:
    ring_plan = _ring_first_plan(collective_plan)
    missing: list[str] = []

    if _ring_first_strategy(ring_plan, collective_summary) != (
        "ring_spmd_row_then_col"
    ):
        missing.append("ring_spmd_row_then_col_strategy_not_selected")
    if _ring_value(ring_plan, "task_axis", "profile.task_axis") != 1:
        missing.append("task_axis_scope_unproven")
    if _ring_cross_task_one_app_forbidden(ring_plan):
        missing.append("cross_task_one_app_ring_forbidden")
    if _ring_status(ring_plan, "representative_selection") != "proven":
        missing.append("representative_selection_missing")
    route_template_proven = _ring_edges_route_template_proven(ring_plan)
    update_template_status = _ring_edges_update_template_status(ring_plan)
    update_template_proven = update_template_status == "row_bytes_emitted"
    if not route_template_proven:
        missing.append("ring_edge_route_template_missing")
    if update_template_status == "missing":
        missing.append("log10max_ring_update_template_missing")
    elif update_template_status == "operand_placeholders_missing":
        missing.append("log10max_ring_update_operand_placeholders_missing")
    elif update_template_status == "operand_allocation_missing":
        missing.append("log10max_ring_update_operand_allocation_missing")
    elif update_template_status == "inst_operand_patch_missing":
        missing.append("log10max_ring_update_inst_operand_patch_missing")
    elif not update_template_proven:
        missing.append("log10max_ring_update_row_bytes_missing")
    if (
        route_template_proven is False
        and update_template_proven is False
        and not _ring_edges_template_proven(ring_plan)
    ):
        missing.append("ring_edge_template_missing")
    if _ring_route_role_globalmax_status(ring_plan) != "proven":
        missing.append("route_role_globalmax_unproven")
    if not _ring_edges_route_path_proven(ring_plan):
        missing.append("route_path_proof_missing")
    if _ring_status(ring_plan, "phase_order") != "proven":
        missing.append("ring_phase_order_missing")
    if _ring_status(ring_plan, "global_max_distribution") != "proven":
        missing.append("global_max_distribution_missing")
    if _ring_status(ring_plan, "consumer_global_max_binding") != "proven":
        missing.append("consumer_global_max_binding_missing")
    if _ring_status(ring_plan, "consumer_global_max_ready_dependencies") != "proven":
        missing.append("consumer_depends_on_global_ready_missing")
    if _ring_status(ring_plan, "capacity") != "fits":
        missing.append("ring_capacity_overflow")
    if _ring_status(ring_plan, "dtype_update_op") != "consistent":
        missing.append("dtype_update_op_mismatch")
    if _ring_symbolic_global_max_reaches_postprocess(ring_plan):
        missing.append("symbolic_global_max_reaches_postprocess")

    state: RuntimeReadyPreIntegrationState = "ready" if not missing else "blocked"
    return RuntimeReadyGateInputStatus(
        operator="log10max",
        gate_id="ring_first_row_col_reduce_broadcast",
        state=state,
        runtime_ready=False,
        uploadable=False,
        missing_blockers=tuple(_dedupe_preserve_order(missing)),
        summary={
            "selected_delivery_strategy": _ring_first_strategy(
                ring_plan,
                collective_summary,
            ),
            "selected_delivery_customer_label": _ring_value(
                ring_plan,
                "customer_collective_label",
                default=collective_summary.get("selected_delivery_customer_label"),
            ),
            "task_axis": _ring_value(ring_plan, "task_axis", "profile.task_axis"),
            "runtime_ordering_domain": _ring_value(
                ring_plan,
                "runtime_ordering_domain",
                "profile.runtime_ordering_domain",
            ),
            "cross_task_visibility_claim": _ring_value(
                ring_plan,
                "cross_task_visibility_claim",
                "profile.cross_task_visibility_claim",
            ),
            "ring_edge_count": len(_ring_edges(ring_plan)),
            "ring_first_blocker_count": len(missing),
            "pe00_escape_hatch_status": collective_summary.get("pe00_plan_status"),
            "pe00_open_requirement_count": collective_summary.get(
                "pe00_open_requirement_count"
            ),
            "runtime_ready_scope": RUNTIME_READY_SCOPE,
        },
        evidence_refs=(
            "docs/compiler/design/bline-log10max-task-local-ring-execution-rfc.md",
            "compiler/gpdpu_compiler/core/stream_compiler/"
            "log10max_collective_strategy.py",
            "compiler/gpdpu_compiler/core/stream_compiler/log10max_template_pack.py",
            "compiler/gpdpu_compiler/core/program_runtime.py",
            "compiler/gpdpu_compiler/core/stream_compiler/binding.py",
        ),
    )


def _legacy_log10max_pe00_gate_status(
    collective_summary: Mapping[str, Any],
    collective_plan: Mapping[str, Any],
) -> RuntimeReadyGateInputStatus:
    pe00_plan = collective_plan.get("pe00_materialized_scalar_plan", {})
    missing: list[str] = []
    if collective_summary.get("runtime_ready") is not True:
        missing.append("log10max_collective_runtime_ready_false")
    if pe00_plan.get("runtime_ready") is not True:
        missing.append("pe00_plan_runtime_ready_false")
    if collective_summary.get("selected_delivery_strategy") != (
        "pe00_aggregate_materialize"
    ):
        missing.append("pe00_delivery_strategy_not_selected")
    if pe00_plan.get("not_a_direct_physical_allreduce") is not True:
        missing.append("pe00_must_not_claim_direct_physical_allreduce")

    template_contract = pe00_plan.get("global_scalar_template_contract", {})
    for section_name in (
        "pe00_fmax_combine_order",
        "producer_pe00_physical_store",
        "consumer_physical_readback",
    ):
        section = template_contract.get(section_name, {})
        proof_plan = section.get("row_byte_proof_plan", {})
        missing.extend(_proof_plan_blockers(section_name, proof_plan))

    runtime_order = pe00_plan.get("runtime_order_contract", {})
    missing.extend(
        _proof_plan_blockers(
            "runtime_subtask_order",
            runtime_order.get("runtime_order_proof_plan", {}),
        )
    )
    receiver = pe00_plan.get("receiver_binding_contract", {})
    missing.extend(
        _proof_plan_blockers(
            "receiver_global_scalar_binding",
            receiver.get("receiver_binding_proof_plan", {}),
        )
    )

    state: RuntimeReadyPreIntegrationState = "ready" if not missing else "blocked"
    return RuntimeReadyGateInputStatus(
        operator="log10max",
        gate_id="pe00_global_scalar_rows_and_runtime",
        state=state,
        runtime_ready=False,
        uploadable=False,
        missing_blockers=tuple(_dedupe_preserve_order(missing)),
        summary={
            "selected_delivery_strategy": collective_summary.get(
                "selected_delivery_strategy"
            ),
            "selected_delivery_customer_label": collective_summary.get(
                "selected_delivery_customer_label"
            ),
            "runtime_ready": collective_summary.get("runtime_ready"),
            "pe00_plan_status": collective_summary.get("pe00_plan_status"),
            "pe00_open_requirement_count": collective_summary.get(
                "pe00_open_requirement_count"
            ),
            "runtime_launch_supported": collective_summary.get(
                "runtime_launch_supported"
            ),
        },
        evidence_refs=(
            "compiler/gpdpu_compiler/core/stream_compiler/"
            "log10max_collective_strategy.py",
            "compiler/gpdpu_compiler/core/stream_compiler/log10max_template_pack.py",
            "compiler/gpdpu_compiler/core/program_runtime.py",
            "compiler/gpdpu_compiler/core/stream_compiler/binding.py",
        ),
    )


def _ring_first_plan(collective_plan: Mapping[str, Any]) -> Mapping[str, Any]:
    for key in (
        "ring_first_delivery_plan",
        "ring_spmd_row_then_col_plan",
        "representative_ring_plan",
    ):
        candidate = collective_plan.get(key, {})
        if isinstance(candidate, Mapping):
            return candidate
    return {}


def _ring_first_strategy(
    ring_plan: Mapping[str, Any],
    collective_summary: Mapping[str, Any],
) -> object:
    return _ring_value(
        ring_plan,
        "collective_strategy",
        "strategy",
        default=collective_summary.get("selected_delivery_strategy"),
    )


def _ring_status(ring_plan: Mapping[str, Any], key: str) -> object:
    value = ring_plan.get(key)
    if isinstance(value, Mapping):
        return value.get("status") or value.get("proof_status")
    return value


def _ring_value(
    ring_plan: Mapping[str, Any],
    *paths: str,
    default: object = None,
) -> object:
    for path in paths:
        current: object = ring_plan
        for part in path.split("."):
            if not isinstance(current, Mapping) or part not in current:
                current = None
                break
            current = current[part]
        if current is not None:
            return current
    return default


def _ring_edges(ring_plan: Mapping[str, Any]) -> tuple[Mapping[str, Any], ...]:
    for key in ("ring_edges", "edge_records", "representative_edges"):
        value = ring_plan.get(key, ())
        if isinstance(value, Sequence) and not isinstance(value, (str, bytes)):
            return tuple(item for item in value if isinstance(item, Mapping))
    return ()


def _ring_edges_template_proven(ring_plan: Mapping[str, Any]) -> bool:
    edges = _ring_edges(ring_plan)
    return bool(edges) and all(
        edge.get("template_evidence_id")
        and edge.get("template_status", edge.get("proof_status")) == "proven"
        for edge in edges
    )


def _ring_edges_route_template_proven(ring_plan: Mapping[str, Any]) -> bool:
    edges = _ring_edges(ring_plan)
    return bool(edges) and all(
        (
            edge.get("route_template_evidence_id")
            or edge.get("template_evidence_id")
        )
        and edge.get(
            "route_template_status",
            edge.get("template_status", edge.get("proof_status")),
        )
        == "proven"
        for edge in edges
    )


def _ring_edges_update_template_proven(ring_plan: Mapping[str, Any]) -> bool:
    return _ring_edges_update_template_status(ring_plan) == "row_bytes_emitted"


def _ring_edges_update_template_status(ring_plan: Mapping[str, Any]) -> str:
    edges = _ring_edges(ring_plan)
    if not edges:
        return "missing"
    blockers = tuple(edge.get("update_template_blocker") for edge in edges)
    if all(blocker == "log10max_ring_update_operand_placeholders_missing" for blocker in blockers):
        return "operand_placeholders_missing"
    if all(blocker == "log10max_ring_update_operand_allocation_missing" for blocker in blockers):
        return "operand_allocation_missing"
    if all(blocker == "log10max_ring_update_inst_operand_patch_missing" for blocker in blockers):
        return "inst_operand_patch_missing"
    if all(blocker == "log10max_ring_update_row_bytes_missing" for blocker in blockers):
        return "row_bytes_missing"
    statuses = tuple(
        edge.get(
            "update_template_status",
            edge.get("template_status", edge.get("proof_status")),
        )
        for edge in edges
    )
    if all(status in {"row_bytes_emitted", "proven"} for status in statuses):
        return "row_bytes_emitted"
    if all(
        status in {
            "candidate_available",
            "row_shape_bound",
            "layout_candidate",
            "row_bytes_missing",
        }
        for status in statuses
    ):
        return "operand_placeholders_missing"
    return "missing"


def _ring_edges_route_path_proven(ring_plan: Mapping[str, Any]) -> bool:
    edges = _ring_edges(ring_plan)
    return bool(edges) and all(
        edge.get("route_path_proof_status", edge.get("proof_status")) == "proven"
        for edge in edges
    )


def _ring_route_role_globalmax_status(ring_plan: Mapping[str, Any]) -> object:
    bindings = ring_plan.get("route_role_bindings", ())
    if not isinstance(bindings, Sequence) or isinstance(bindings, (str, bytes)):
        return None
    for binding in bindings:
        if not isinstance(binding, Mapping):
            continue
        if binding.get("role") == "GlobalMax":
            return binding.get("proof_status") or binding.get("status")
    return None


def _ring_cross_task_one_app_forbidden(ring_plan: Mapping[str, Any]) -> bool:
    task_axis = _ring_value(ring_plan, "task_axis", "profile.task_axis")
    app_count = _ring_value(
        ring_plan,
        "runtime_app_count",
        "runtime.required_launch_count",
        default=1,
    )
    cross_task_claim = _ring_value(
        ring_plan,
        "cross_task_visibility_claim",
        "profile.cross_task_visibility_claim",
    )
    if cross_task_claim is not False:
        return True
    return isinstance(task_axis, int) and task_axis > 1 and app_count == 1


def _ring_symbolic_global_max_reaches_postprocess(
    ring_plan: Mapping[str, Any],
) -> bool:
    value = _ring_value(
        ring_plan,
        "symbolic_global_max_reaches_postprocess",
        "postprocess.symbolic_global_max_reaches_postprocess",
    )
    if value is None:
        return True
    return bool(value)


def _counter_blockers(prefix: str, counters: Any) -> list[str]:
    if not isinstance(counters, Mapping):
        return []
    return [
        "%s:%s=%s" % (prefix, key, value)
        for key, value in sorted(counters.items())
        if value
    ]


def _proof_plan_blockers(prefix: str, proof_plan: Mapping[str, Any]) -> list[str]:
    if not proof_plan:
        return ["%s:proof_plan_missing" % prefix]
    blockers: list[str] = []
    if proof_plan.get("row_bytes_claim") is not True:
        blockers.append("%s:row_bytes_claim_false" % prefix)
    if proof_plan.get("runtime_runnable_claim") is not True:
        blockers.append("%s:runtime_runnable_claim_false" % prefix)
    blockers.extend(
        "%s:missing_field=%s" % (prefix, field)
        for field in proof_plan.get("missing_fields", ())
    )
    for blocker in proof_plan.get("proof_blockers", ()):
        if isinstance(blocker, Mapping) and blocker.get("blocker_id"):
            blockers.append("%s:%s" % (prefix, blocker["blocker_id"]))
    return blockers


def _dedupe_preserve_order(values: Sequence[str]) -> tuple[str, ...]:
    seen: set[str] = set()
    deduped: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        deduped.append(value)
    return tuple(deduped)


__all__ = [
    "EXPECTED_CBUF_SECTIONS",
    "EXPECTED_MICC_SECTIONS",
    "OperatorPayloadAssemblyReport",
    "PackageShellSection",
    "PLACEHOLDER_SHELL_RULE",
    "GemmNoReluComponentPayloadCandidateReport",
    "PayloadCandidateFileRecord",
    "RuntimeReadyGateInputStatus",
    "RuntimeReadyPreIntegrationReport",
    "StreamArtifactStatus",
    "build_gemm_no_relu_component_payload_candidate_report",
    "build_operator_payload_assembly_report",
    "build_runtime_ready_preintegration_report",
    "gemm_no_relu_stream_statuses",
    "gemm_relu_stream_statuses",
    "log10max_stream_statuses",
    "summarize_gemm_no_relu_component_payload_candidate_report",
    "summarize_operator_payload_assembly_report",
    "summarize_runtime_ready_preintegration_report",
]
