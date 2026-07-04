"""Delivery control-plane contracts for DFU operator payload candidates.

``runtime_ready`` is a local structural/package readiness claim.  It means the
payload has the files, manifest claims, component layout, and runtime metadata
required by the local DFU validation suite.  It is not a SimICT execution proof
and does not validate operator numerical correctness.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal, Mapping, Sequence

from .dfu_binary_checks.runtime_ready_gate import (
    archive_runtime_ready_gate,
    runtime_ready_blockers,
)


DeliveryState = Literal[
    "draft",
    "inspectable",
    "package_complete",
    "runtime_ready",
    "uploadable",
]
ReadinessClaim = Literal[
    "inspectable",
    "package_complete",
    "runtime_ready",
    "uploadable",
]

MIN_DELIVERY_STATES: tuple[DeliveryState, ...] = ("runtime_ready", "uploadable")
RUNTIME_READY_SCOPE = (
    "local structural/package readiness only; not a SimICT execution or "
    "operator numerical-correctness claim"
)

_PLACEHOLDER_SHELL_MARKERS = (
    "local-edit placeholder",
    "smoke_result=NOOP",
    "This smoke hook is a local-edit placeholder",
)


@dataclass(frozen=True)
class FileRecord:
    path: str
    size: int | None = None
    sha256: str | None = None
    role: str | None = None

    def to_json(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "size": self.size,
            "sha256": self.sha256,
            "role": self.role,
        }


@dataclass(frozen=True)
class ComponentWriterArtifact:
    component_name: str
    writer_name: str
    schema_version: str = "dfu_component_writer_artifact_v1"
    operator: str | None = None
    path: str | None = None
    sha256: str | None = None
    size: int | None = None
    profile_id: str | None = None
    selected_representation: str | None = None
    row_count: int | None = None
    row_size: int | None = None
    writer_status: str | None = None
    unresolved_fields: tuple[str, ...] = ()
    forbidden_fields_touched: tuple[str, ...] = ()
    assumptions: Mapping[str, Any] = field(default_factory=dict)
    files: tuple[FileRecord, ...] = ()
    state: DeliveryState = "draft"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "operator": self.operator,
            "component_name": self.component_name,
            "writer_name": self.writer_name,
            "path": self.path,
            "sha256": self.sha256,
            "size": self.size,
            "profile_id": self.profile_id,
            "selected_representation": self.selected_representation,
            "row_count": self.row_count,
            "row_size": self.row_size,
            "writer_status": self.writer_status,
            "unresolved_fields": list(self.unresolved_fields),
            "forbidden_fields_touched": list(self.forbidden_fields_touched),
            "assumptions": dict(self.assumptions),
            "files": [record.to_json() for record in self.files],
            "state": self.state,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class OperatorBindingArtifact:
    operator: str
    binding_name: str
    source_plan_id: str | None = None
    template_plan_id: str | None = None
    selected_strategy: str | None = None
    concrete_template_count: int | None = None
    symbolic_unresolved_count: int | None = None
    unresolved_fields: tuple[str, ...] = ()
    numerical_contract_path: str | None = None
    assumptions: Mapping[str, Any] = field(default_factory=dict)
    files: tuple[FileRecord, ...] = ()
    state: DeliveryState = "draft"
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "binding_name": self.binding_name,
            "source_plan_id": self.source_plan_id,
            "template_plan_id": self.template_plan_id,
            "selected_strategy": self.selected_strategy,
            "concrete_template_count": self.concrete_template_count,
            "symbolic_unresolved_count": self.symbolic_unresolved_count,
            "unresolved_fields": list(self.unresolved_fields),
            "numerical_contract_path": self.numerical_contract_path,
            "assumptions": dict(self.assumptions),
            "files": [record.to_json() for record in self.files],
            "state": self.state,
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class OperatorPayloadManifest:
    operator: str
    payload_dir: str
    readiness_claim: ReadinessClaim
    profile_id: str | None = None
    selected_representation: str | None = None
    selected_strategy: str | None = None
    runtime_assets: tuple[FileRecord, ...] = ()
    known_limitations: tuple[str, ...] = ()
    files: tuple[FileRecord, ...] = ()
    component_artifacts: tuple[ComponentWriterArtifact, ...] = ()
    binding_artifacts: tuple[OperatorBindingArtifact, ...] = ()
    metadata: Mapping[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "payload_dir": self.payload_dir,
            "readiness_claim": self.readiness_claim,
            "profile_id": self.profile_id,
            "selected_representation": self.selected_representation,
            "selected_strategy": self.selected_strategy,
            "runtime_assets": [record.to_json() for record in self.runtime_assets],
            "known_limitations": list(self.known_limitations),
            "files": [record.to_json() for record in self.files],
            "component_artifacts": [
                artifact.to_json() for artifact in self.component_artifacts
            ],
            "binding_artifacts": [
                artifact.to_json() for artifact in self.binding_artifacts
            ],
            "metadata": dict(self.metadata),
        }


@dataclass(frozen=True)
class PlaceholderShellFinding:
    path: str
    marker: str

    def to_json(self) -> dict[str, str]:
        return {"path": self.path, "marker": self.marker}


@dataclass(frozen=True)
class DeliveryCandidateReport:
    operator: str
    payload_dir: str
    requested_min_state: DeliveryState
    final_state: DeliveryState
    passed: bool
    report_path: str
    runtime_ready_scope: str
    validation_status: str
    validation_blockers: tuple[str, ...] = ()
    placeholder_shell_findings: tuple[PlaceholderShellFinding, ...] = ()

    def to_json(self) -> dict[str, Any]:
        return {
            "operator": self.operator,
            "payload_dir": self.payload_dir,
            "requested_min_state": self.requested_min_state,
            "final_state": self.final_state,
            "passed": self.passed,
            "report_path": self.report_path,
            "runtime_ready_scope": self.runtime_ready_scope,
            "validation_status": self.validation_status,
            "validation_blockers": list(self.validation_blockers),
            "placeholder_shell_findings": [
                finding.to_json() for finding in self.placeholder_shell_findings
            ],
        }


def validate_delivery_candidate(
    payload_dir: Path | str,
    operator: str,
    *,
    min_state: Literal["runtime_ready", "uploadable"] = "runtime_ready",
    report_path: Path | str | None = None,
) -> DeliveryCandidateReport:
    """Validate a DFU payload candidate for delivery handoff.

    The function delegates local package/runtime validation to
    ``archive_runtime_ready_gate`` and only adds S0 delivery-control checks that
    sit above that gate.
    """

    if min_state not in MIN_DELIVERY_STATES:
        raise ValueError("min_state must be one of %s" % (MIN_DELIVERY_STATES,))

    root = Path(payload_dir)
    selected_report_path = (
        Path(report_path)
        if report_path is not None
        else root / "validation" / "runtime_ready.json"
    )
    validation_report = archive_runtime_ready_gate(
        root,
        report_path=selected_report_path,
        require_pass=False,
    )
    placeholder_findings = find_placeholder_shell_markers(root)

    validation_passed = validation_report.final_status == "pass"
    uploadable = validation_passed and not placeholder_findings
    final_state: DeliveryState
    if uploadable:
        final_state = "uploadable"
    elif validation_passed:
        final_state = "runtime_ready"
    else:
        final_state = "draft"

    passed = validation_passed and not placeholder_findings
    if min_state == "uploadable":
        passed = uploadable

    return DeliveryCandidateReport(
        operator=operator,
        payload_dir=str(root),
        requested_min_state=min_state,
        final_state=final_state,
        passed=passed,
        report_path=str(selected_report_path),
        runtime_ready_scope=RUNTIME_READY_SCOPE,
        validation_status=validation_report.final_status,
        validation_blockers=runtime_ready_blockers(validation_report),
        placeholder_shell_findings=placeholder_findings,
    )


def find_placeholder_shell_markers(
    payload_dir: Path | str,
    *,
    markers: Sequence[str] = _PLACEHOLDER_SHELL_MARKERS,
) -> tuple[PlaceholderShellFinding, ...]:
    root = Path(payload_dir)
    findings: list[PlaceholderShellFinding] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or not _should_scan_for_shell_placeholder(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        rel_path = path.relative_to(root).as_posix()
        for marker in markers:
            if marker in text:
                findings.append(PlaceholderShellFinding(path=rel_path, marker=marker))
                break
    return tuple(findings)


def _should_scan_for_shell_placeholder(path: Path) -> bool:
    if path.suffix in {".sh", ".bash"}:
        return True
    if path.name in {"run.sh", "current.sh"}:
        return True
    return path.stat().st_size <= 64 * 1024 and path.suffix in {".txt", ".md"}
