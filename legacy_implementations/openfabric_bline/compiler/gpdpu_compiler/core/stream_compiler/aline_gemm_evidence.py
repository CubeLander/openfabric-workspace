"""Report-only A-line GEMM evidence extracted from local vendor artifacts.

This module does not build or mutate vendor outputs.  It only scans local
DFU3500 GEMM reference cases and reports which A-line artifacts are available
for later S2 exact-seed work.
"""

from __future__ import annotations

import csv
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

from gpdpu_compiler.core.dfu3500.legacy_templates import _stage_for_legacy_inst
from gpdpu_compiler.core.program_legacy_inst import (
    pack_legacy_inst,
    parse_legacy_csv_template,
)


FULL_SIZE_CBUF_BYTES = 23_531_520
FULL_SIZE_MICC_BYTES = 8_522_976
SCHEMA_VERSION = 1
_ADAPTIVE_PSEUDO_OPS = frozenset(
    ("HLDT", "ILDT", "ILDMT", "HSTT", "ISTT", "COPYT")
)
_ADAPTIVE_PSEUDO_EXPANSION_COUNT = 4

_TEMPLATE_RE = re.compile(
    r"/gpdpu_tensor/task(?P<task>\d+)/subtask(?P<subtask>\d+)/template/"
    r"(?P<template>\d+)\.csv$"
)


@dataclass(frozen=True)
class AlineBinaryArtifactEvidence:
    """One binary artifact observed under an A-line GEMM case."""

    kind: str
    path: str
    size_bytes: int
    sha256: str | None = None
    expected_full_size_bytes: int | None = None
    full_size_match: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "path": self.path,
            "size_bytes": self.size_bytes,
            "sha256": self.sha256,
            "expected_full_size_bytes": self.expected_full_size_bytes,
            "full_size_match": self.full_size_match,
        }


@dataclass(frozen=True)
class AlineTemplateGroupEvidence:
    """CSV template index evidence for one task/subtask directory."""

    task_index: int
    subtask_index: int
    template_count: int
    template_index_min: int
    template_index_max: int
    template_indices: tuple[int, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_index": self.task_index,
            "subtask_index": self.subtask_index,
            "template_count": self.template_count,
            "template_index_min": self.template_index_min,
            "template_index_max": self.template_index_max,
            "template_indices": list(self.template_indices),
        }


@dataclass(frozen=True)
class AlineTemplateCsvEvidence:
    """Aggregate CSV template evidence for a local A-line GEMM case."""

    search_root: str
    csv_template_count: int
    task_index_min: int | None
    task_index_max: int | None
    subtask_index_min: int | None
    subtask_index_max: int | None
    task_indices: tuple[int, ...]
    subtask_indices: tuple[int, ...]
    groups: tuple[AlineTemplateGroupEvidence, ...] = ()

    @property
    def task_count(self) -> int:
        return len(self.task_indices)

    def to_dict(self) -> dict[str, Any]:
        return {
            "search_root": self.search_root,
            "csv_template_count": self.csv_template_count,
            "task_count": self.task_count,
            "task_index_min": self.task_index_min,
            "task_index_max": self.task_index_max,
            "subtask_index_min": self.subtask_index_min,
            "subtask_index_max": self.subtask_index_max,
            "task_indices": list(self.task_indices),
            "subtask_indices": list(self.subtask_indices),
            "groups": [group.to_dict() for group in self.groups],
        }


@dataclass(frozen=True)
class AlineTemplateRowEvidence:
    """One packed legacy inst_t row parsed from a selected A-line CSV."""

    task_index: int
    subtask_index: int
    template_index: int
    local_order: int
    inst_name: str
    op_name: str
    stage: str
    row_sha256: str
    csv_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_index": self.task_index,
            "subtask_index": self.subtask_index,
            "template_index": self.template_index,
            "local_order": self.local_order,
            "inst_name": self.inst_name,
            "op_name": self.op_name,
            "stage": self.stage,
            "row_sha256": self.row_sha256,
            "csv_path": self.csv_path,
        }


@dataclass(frozen=True)
class AlineTemplateRowCatalog:
    """Report-only row catalog for selected A-line GEMM templates.

    This is not an exact B-line binding.  It only proves that the selected
    A-line root can be parsed into row-addressable legacy template evidence.
    """

    search_root: str
    row_catalog_available: bool
    row_count: int
    rows: tuple[AlineTemplateRowEvidence, ...] = ()
    by_template_op_stage_counts: tuple[dict[str, Any], ...] = ()
    global_op_stage_counts: tuple[dict[str, Any], ...] = ()
    global_inst_stage_counts: tuple[dict[str, Any], ...] = ()
    parse_errors: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "search_root": self.search_root,
            "row_catalog_available": self.row_catalog_available,
            "row_count": self.row_count,
            "rows": [row.to_dict() for row in self.rows],
            "by_template_op_stage_counts": list(self.by_template_op_stage_counts),
            "global_op_stage_counts": list(self.global_op_stage_counts),
            "global_inst_stage_counts": list(self.global_inst_stage_counts),
            "parse_errors": list(self.parse_errors),
        }


@dataclass(frozen=True)
class AlineGemmEvidenceReport:
    """Report-only evidence summary for one selected A-line GEMM case."""

    case_path: str
    full_size_result_available: bool
    csv_evidence: AlineTemplateCsvEvidence
    row_catalog: AlineTemplateRowCatalog
    result_cbuf: AlineBinaryArtifactEvidence | None = None
    result_micc: AlineBinaryArtifactEvidence | None = None
    binary_artifacts: tuple[AlineBinaryArtifactEvidence, ...] = ()
    available_evidence: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    blockers: tuple[str, ...] = ()
    candidate_case_paths: tuple[str, ...] = ()
    scanned_case_reports: tuple[dict[str, Any], ...] = field(default_factory=tuple)

    @property
    def csv_template_count(self) -> int:
        return self.csv_evidence.csv_template_count

    @property
    def task_count(self) -> int:
        return self.csv_evidence.task_count

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": SCHEMA_VERSION,
            "report_kind": "aline_gemm_report_only_evidence",
            "case_path": self.case_path,
            "full_size_result_available": self.full_size_result_available,
            "expected_full_size_bytes": {
                "result/cbuf_file.bin": FULL_SIZE_CBUF_BYTES,
                "result/micc_file.bin": FULL_SIZE_MICC_BYTES,
            },
            "csv_evidence": self.csv_evidence.to_dict(),
            "row_catalog": self.row_catalog.to_dict(),
            "result_cbuf": (
                self.result_cbuf.to_dict() if self.result_cbuf is not None else None
            ),
            "result_micc": (
                self.result_micc.to_dict() if self.result_micc is not None else None
            ),
            "binary_artifacts": [
                artifact.to_dict() for artifact in self.binary_artifacts
            ],
            "available_evidence": list(self.available_evidence),
            "missing_evidence": list(self.missing_evidence),
            "blockers": list(self.blockers),
            "candidate_case_paths": list(self.candidate_case_paths),
            "scanned_case_reports": list(self.scanned_case_reports),
        }


def build_aline_gemm_evidence_report(
    *,
    repo_root: str | Path | None = None,
    case_paths: Iterable[str | Path] | None = None,
) -> AlineGemmEvidenceReport:
    """Scan local A-line GEMM candidates and return the best report.

    Candidate selection prefers a case with both full-size result binaries and
    CSV template evidence.  If no complete result is available, the returned
    report remains blocked and lists the closest candidate paths.
    """

    root = _repo_root(repo_root)
    candidates = tuple(_candidate_case_paths(root, case_paths))
    case_reports = tuple(_scan_case(path) for path in candidates)
    selected = max(case_reports, key=_candidate_score, default=None)
    if selected is None:
        csv_evidence = AlineTemplateCsvEvidence(
            search_root=str(root),
            csv_template_count=0,
            task_index_min=None,
            task_index_max=None,
            subtask_index_min=None,
            subtask_index_max=None,
            task_indices=(),
            subtask_indices=(),
            groups=(),
        )
        return AlineGemmEvidenceReport(
            case_path=str(root),
            full_size_result_available=False,
            csv_evidence=csv_evidence,
            row_catalog=AlineTemplateRowCatalog(
                search_root=str(root),
                row_catalog_available=False,
                row_count=0,
            ),
            missing_evidence=("candidate_case_path",),
            blockers=("no A-line GEMM candidate paths were provided or found",),
            candidate_case_paths=(),
        )

    return _report_from_scan(selected, case_reports)


def summarize_aline_gemm_evidence_report(
    report: AlineGemmEvidenceReport,
) -> dict[str, Any]:
    """Return the compact summary consumed by the check script."""

    return {
        "full_size_result_available": report.full_size_result_available,
        "csv_template_count": report.csv_template_count,
        "task_count": report.task_count,
        "row_catalog_available": report.row_catalog.row_catalog_available,
        "row_count": report.row_catalog.row_count,
        "global_op_stage_counts": list(report.row_catalog.global_op_stage_counts),
        "global_inst_stage_counts": list(report.row_catalog.global_inst_stage_counts),
        "blockers": list(report.blockers),
    }


def _repo_root(repo_root: str | Path | None) -> Path:
    if repo_root is not None:
        return Path(repo_root).resolve()
    return Path(__file__).resolve().parents[4]


def _candidate_case_paths(
    repo_root: Path,
    case_paths: Iterable[str | Path] | None,
) -> list[Path]:
    if case_paths is not None:
        return [Path(path).resolve() for path in case_paths]
    app_root = (
        repo_root
        / "simict3500final/gpdpu/users/risc_nn_riscv/testcase/application"
    )
    return [
        app_root / "gemm_template_fusion_bash_semantics_probe",
        app_root / "gemm_template_fusion_local_vendor_20260615_202035",
    ]


def _scan_case(case_path: Path) -> dict[str, Any]:
    result_cbuf = _binary_artifact(
        case_path / "result/cbuf_file.bin",
        kind="result/cbuf_file.bin",
        expected_full_size_bytes=FULL_SIZE_CBUF_BYTES,
        include_sha=True,
    )
    result_micc = _binary_artifact(
        case_path / "result/micc_file.bin",
        kind="result/micc_file.bin",
        expected_full_size_bytes=FULL_SIZE_MICC_BYTES,
        include_sha=True,
    )
    return {
        "case_path": case_path,
        "exists": case_path.exists(),
        "csv_evidence": _scan_csv_templates(case_path),
        "row_catalog": _scan_template_row_catalog(case_path),
        "result_cbuf": result_cbuf,
        "result_micc": result_micc,
        "binary_artifacts": tuple(_scan_binary_artifacts(case_path)),
    }


def _report_from_scan(
    selected: dict[str, Any],
    case_reports: tuple[dict[str, Any], ...],
) -> AlineGemmEvidenceReport:
    result_cbuf = selected["result_cbuf"]
    result_micc = selected["result_micc"]
    csv_evidence = selected["csv_evidence"]
    row_catalog = selected["row_catalog"]
    full_size_result_available = (
        result_cbuf is not None
        and result_cbuf.full_size_match is True
        and result_micc is not None
        and result_micc.full_size_match is True
    )

    available: list[str] = []
    missing: list[str] = []
    blockers: list[str] = []

    if full_size_result_available:
        available.append("full_size_result_cbuf_micc")
    else:
        missing.append("full_size_result_cbuf_micc")
        blockers.extend(_result_blockers(result_cbuf, result_micc))

    if csv_evidence.csv_template_count:
        available.append("gpdpu_tensor_csv_templates")
    else:
        missing.append("gpdpu_tensor_csv_templates")
        blockers.append("missing gpdpu_tensor/task*/subtask*/template/*.csv")

    if csv_evidence.task_count:
        available.append("task_subtask_template_index_ranges")
    else:
        missing.append("task_subtask_template_index_ranges")

    if row_catalog.row_catalog_available:
        available.append("selected_template_row_catalog")
    else:
        missing.append("selected_template_row_catalog")
        if row_catalog.parse_errors:
            blockers.extend(row_catalog.parse_errors)
        else:
            blockers.append("selected A-line row catalog is empty")

    return AlineGemmEvidenceReport(
        case_path=str(selected["case_path"]),
        full_size_result_available=full_size_result_available,
        csv_evidence=csv_evidence,
        row_catalog=row_catalog,
        result_cbuf=result_cbuf,
        result_micc=result_micc,
        binary_artifacts=selected["binary_artifacts"],
        available_evidence=tuple(available),
        missing_evidence=tuple(missing),
        blockers=tuple(blockers),
        candidate_case_paths=tuple(str(report["case_path"]) for report in case_reports),
        scanned_case_reports=tuple(_scan_summary(report) for report in case_reports),
    )


def _scan_summary(scan: dict[str, Any]) -> dict[str, Any]:
    result_cbuf = scan["result_cbuf"]
    result_micc = scan["result_micc"]
    csv_evidence = scan["csv_evidence"]
    row_catalog = scan["row_catalog"]
    return {
        "case_path": str(scan["case_path"]),
        "exists": scan["exists"],
        "full_size_result_available": (
            result_cbuf is not None
            and result_cbuf.full_size_match is True
            and result_micc is not None
            and result_micc.full_size_match is True
        ),
        "csv_template_count": csv_evidence.csv_template_count,
        "task_count": csv_evidence.task_count,
        "row_catalog_available": row_catalog.row_catalog_available,
        "row_count": row_catalog.row_count,
        "row_catalog_parse_error_count": len(row_catalog.parse_errors),
        "binary_artifact_count": len(scan["binary_artifacts"]),
    }


def _candidate_score(scan: dict[str, Any]) -> tuple[int, int, int, int]:
    result_cbuf = scan["result_cbuf"]
    result_micc = scan["result_micc"]
    full_size = int(
        result_cbuf is not None
        and result_cbuf.full_size_match is True
        and result_micc is not None
        and result_micc.full_size_match is True
    )
    csv_evidence = scan["csv_evidence"]
    return (
        full_size,
        int(csv_evidence.csv_template_count > 0),
        csv_evidence.csv_template_count,
        len(scan["binary_artifacts"]),
    )


def _scan_csv_templates(case_path: Path) -> AlineTemplateCsvEvidence:
    search_root = case_path / "gpdpu_tensor"
    grouped: dict[tuple[int, int], list[int]] = {}
    for path in sorted(search_root.glob("task*/subtask*/template/*.csv")):
        parsed = _parse_template_path(path)
        if parsed is None:
            continue
        task_index, subtask_index, template_index = parsed
        grouped.setdefault((task_index, subtask_index), []).append(template_index)

    groups: list[AlineTemplateGroupEvidence] = []
    for (task_index, subtask_index), indices in sorted(grouped.items()):
        template_indices = tuple(sorted(indices))
        groups.append(
            AlineTemplateGroupEvidence(
                task_index=task_index,
                subtask_index=subtask_index,
                template_count=len(template_indices),
                template_index_min=template_indices[0],
                template_index_max=template_indices[-1],
                template_indices=template_indices,
            )
        )

    task_indices = tuple(sorted({group.task_index for group in groups}))
    subtask_indices = tuple(sorted({group.subtask_index for group in groups}))
    return AlineTemplateCsvEvidence(
        search_root=str(search_root),
        csv_template_count=sum(group.template_count for group in groups),
        task_index_min=task_indices[0] if task_indices else None,
        task_index_max=task_indices[-1] if task_indices else None,
        subtask_index_min=subtask_indices[0] if subtask_indices else None,
        subtask_index_max=subtask_indices[-1] if subtask_indices else None,
        task_indices=task_indices,
        subtask_indices=subtask_indices,
        groups=tuple(groups),
    )


def _scan_template_row_catalog(case_path: Path) -> AlineTemplateRowCatalog:
    search_root = case_path / "gpdpu_tensor"
    rows: list[AlineTemplateRowEvidence] = []
    parse_errors: list[str] = []

    for path in sorted(search_root.glob("task*/subtask*/template/*.csv")):
        parsed = _parse_template_path(path)
        if parsed is None:
            continue
        task_index, subtask_index, template_index = parsed
        try:
            rows.extend(
                _parse_template_rows(
                    path,
                    task_index=task_index,
                    subtask_index=subtask_index,
                    template_index=template_index,
                )
            )
        except Exception as exc:  # noqa: BLE001 - report-only scanner must close.
            parse_errors.append(f"{path}: {exc}")

    by_template_counts = _template_op_stage_counts(rows)
    global_op_counts = _global_stage_counts(
        (row.op_name, row.stage) for row in rows
    )
    global_inst_counts = _global_stage_counts(
        (row.inst_name, row.stage) for row in rows
    )
    return AlineTemplateRowCatalog(
        search_root=str(search_root),
        row_catalog_available=bool(rows) and not parse_errors,
        row_count=len(rows),
        rows=tuple(rows),
        by_template_op_stage_counts=tuple(by_template_counts),
        global_op_stage_counts=tuple(global_op_counts),
        global_inst_stage_counts=tuple(global_inst_counts),
        parse_errors=tuple(parse_errors),
    )


def _parse_template_rows(
    path: Path,
    *,
    task_index: int,
    subtask_index: int,
    template_index: int,
) -> tuple[AlineTemplateRowEvidence, ...]:
    raw_ops = _expanded_csv_op_names(path)
    insts = parse_legacy_csv_template(path)
    if len(raw_ops) != len(insts):
        raise ValueError(
            "legacy CSV expansion count mismatch: "
            f"{len(raw_ops)} source op slots != {len(insts)} packed inst rows"
        )

    rows: list[AlineTemplateRowEvidence] = []
    for local_order, (op_name, inst) in enumerate(zip(raw_ops, insts, strict=True)):
        stage = _stage_for_legacy_inst(inst)
        row_sha256 = hashlib.sha256(pack_legacy_inst(inst)).hexdigest()
        rows.append(
            AlineTemplateRowEvidence(
                task_index=task_index,
                subtask_index=subtask_index,
                template_index=template_index,
                local_order=local_order,
                inst_name=inst.op_name,
                op_name=op_name,
                stage=stage,
                row_sha256=row_sha256,
                csv_path=str(path),
            )
        )
    return tuple(rows)


def _expanded_csv_op_names(path: Path) -> tuple[str, ...]:
    op_names: list[str] = []
    with path.open(newline="") as csv_file:
        reader = csv.reader(csv_file)
        next(reader, None)
        for row in reader:
            if not row or not row[0].strip():
                continue
            op_name = row[0].strip().upper()
            expansion_count = (
                _ADAPTIVE_PSEUDO_EXPANSION_COUNT
                if op_name in _ADAPTIVE_PSEUDO_OPS
                else 1
            )
            op_names.extend(op_name for _ in range(expansion_count))
    return tuple(op_names)


def _template_op_stage_counts(
    rows: Iterable[AlineTemplateRowEvidence],
) -> list[dict[str, Any]]:
    counts: dict[tuple[int, int, int, str, str], int] = {}
    for row in rows:
        key = (
            row.task_index,
            row.subtask_index,
            row.template_index,
            row.op_name,
            row.stage,
        )
        counts[key] = counts.get(key, 0) + 1
    return [
        {
            "task_index": task_index,
            "subtask_index": subtask_index,
            "template_index": template_index,
            "op_name": op_name,
            "stage": stage,
            "count": count,
        }
        for (
            task_index,
            subtask_index,
            template_index,
            op_name,
            stage,
        ), count in sorted(counts.items())
    ]


def _global_stage_counts(
    keys: Iterable[tuple[str, str]],
) -> list[dict[str, Any]]:
    counts: dict[tuple[str, str], int] = {}
    for name, stage in keys:
        key = (name, stage)
        counts[key] = counts.get(key, 0) + 1
    return [
        {"name": name, "stage": stage, "count": count}
        for (name, stage), count in sorted(counts.items())
    ]


def _parse_template_path(path: Path) -> tuple[int, int, int] | None:
    normalized = path.as_posix()
    match = _TEMPLATE_RE.search(normalized)
    if match is None:
        return None
    return (
        int(match.group("task")),
        int(match.group("subtask")),
        int(match.group("template")),
    )


def _scan_binary_artifacts(case_path: Path) -> list[AlineBinaryArtifactEvidence]:
    artifacts: list[AlineBinaryArtifactEvidence] = []
    for relative_path, expected_size in (
        ("result/cbuf_file.bin", FULL_SIZE_CBUF_BYTES),
        ("result/micc_file.bin", FULL_SIZE_MICC_BYTES),
        ("simulator_bin/cbuf_file.bin", None),
        ("simulator_bin/micc_file.bin", None),
        ("simulator_bin_multi_app/cbuf_file.bin", FULL_SIZE_CBUF_BYTES),
        ("simulator_bin_multi_app/micc_file.bin", FULL_SIZE_MICC_BYTES),
    ):
        artifact = _binary_artifact(
            case_path / relative_path,
            kind=relative_path,
            expected_full_size_bytes=expected_size,
            include_sha=relative_path.startswith("result/"),
        )
        if artifact is not None:
            artifacts.append(artifact)
    return artifacts


def _binary_artifact(
    path: Path,
    *,
    kind: str,
    expected_full_size_bytes: int | None,
    include_sha: bool,
) -> AlineBinaryArtifactEvidence | None:
    if not path.is_file():
        return None
    size_bytes = path.stat().st_size
    return AlineBinaryArtifactEvidence(
        kind=kind,
        path=str(path),
        size_bytes=size_bytes,
        sha256=_sha256(path) if include_sha else None,
        expected_full_size_bytes=expected_full_size_bytes,
        full_size_match=(
            None
            if expected_full_size_bytes is None
            else size_bytes == expected_full_size_bytes
        ),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file_obj:
        for chunk in iter(lambda: file_obj.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _result_blockers(
    result_cbuf: AlineBinaryArtifactEvidence | None,
    result_micc: AlineBinaryArtifactEvidence | None,
) -> list[str]:
    blockers: list[str] = []
    if result_cbuf is None:
        blockers.append("missing result/cbuf_file.bin")
    elif result_cbuf.full_size_match is not True:
        blockers.append(
            "result/cbuf_file.bin size "
            f"{result_cbuf.size_bytes} != {FULL_SIZE_CBUF_BYTES}"
        )
    if result_micc is None:
        blockers.append("missing result/micc_file.bin")
    elif result_micc.full_size_match is not True:
        blockers.append(
            "result/micc_file.bin size "
            f"{result_micc.size_bytes} != {FULL_SIZE_MICC_BYTES}"
        )
    return blockers
