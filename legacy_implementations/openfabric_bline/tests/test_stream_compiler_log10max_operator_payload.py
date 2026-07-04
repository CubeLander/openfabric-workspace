from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "compiler"))

from gpdpu_compiler.core.stream_compiler.log10max_operator_payload import (  # noqa: E402
    EXPECTED_LOG10MAX_ROW_FAMILIES,
    EXPECTED_LOG10MAX_SEMANTIC_OPS,
    LOG10MAX_OPERATOR_CONTROL_COHERENCE_BLOCKED,
    LOG10MAX_OPERATOR_INSTS_COMPONENT_PARTIAL,
    LOG10MAX_OPERATOR_PAYLOAD_MANIFEST_BLOCKED,
    LOG10MAX_OPERATOR_SLICE_SET_PARTIAL,
    REQUIRED_LOG10MAX_PAYLOAD_FILE_ROLES,
    SEMANTIC_OPS_BY_SLICE,
    build_log10max_operator_control_coherence_report,
    build_log10max_operator_insts_component_candidate,
    build_log10max_operator_instruction_slice_set,
    build_log10max_operator_payload_manifest_candidate,
)


EXPECTED_BLOCKED = tuple(
    family
    for family in EXPECTED_LOG10MAX_ROW_FAMILIES
    if family not in {"route_copy", "ring_fmax_update"}
)
EXPECTED_MISSING_SEMANTIC_OPS = tuple(
    op
    for op in EXPECTED_LOG10MAX_SEMANTIC_OPS
    if op
    not in (
        *SEMANTIC_OPS_BY_SLICE["route_copy"],
        *SEMANTIC_OPS_BY_SLICE["ring_fmax_update"],
    )
)


def test_log10max_operator_slice_set_promotes_route_only() -> None:
    report = build_log10max_operator_instruction_slice_set()
    summary = report.summary()

    assert tuple(summary["expected_row_families"]) == EXPECTED_LOG10MAX_ROW_FAMILIES
    assert summary["present_row_families"] == ["route_copy", "ring_fmax_update"]
    assert summary["folded_row_families"] == []
    assert tuple(summary["missing_row_families"]) == EXPECTED_BLOCKED
    assert tuple(summary["blocked_row_families"]) == EXPECTED_BLOCKED
    assert tuple(summary["covered_semantic_ops"]) == (
        *SEMANTIC_OPS_BY_SLICE["route_copy"],
        *SEMANTIC_OPS_BY_SLICE["ring_fmax_update"],
    )
    assert tuple(summary["missing_semantic_ops"]) == EXPECTED_MISSING_SEMANTIC_OPS
    assert summary["duplicate_semantic_ops"] == []
    assert summary["slice_set_status"] == "partial"
    assert summary["slice_status_counts"] == {"blocked": 5, "present": 2}
    assert summary["byte_status_counts"] == {"blocked": 5, "copied_from_candidate": 2}
    assert summary["placement_status_counts"] == {"blocked": 5, "placed": 2}
    assert summary["row_counts_by_family"]["route_copy"] == 120
    assert summary["row_counts_by_family"]["ring_fmax_update"] == 30
    assert LOG10MAX_OPERATOR_SLICE_SET_PARTIAL in summary["blocker_ids"]
    assert report.runtime_ready is False
    assert report.uploadable is False


def test_log10max_operator_slice_records_are_explicit() -> None:
    report = build_log10max_operator_instruction_slice_set()
    slices = {item.slice_kind: item for item in report.slices}

    assert set(slices) == set(EXPECTED_LOG10MAX_ROW_FAMILIES)
    route = slices["route_copy"]
    assert route.slice_status == "present"
    assert route.covered_semantic_ops == ("route_globalmax_copy",)
    assert route.row_count == 120
    assert len(route.row_ids) == 120
    assert len(route.component_byte_offsets) == 120
    assert len(route.row_sha256s) == 120
    assert route.slice_sha256
    assert route.layout_epoch
    assert route.layout_plan_sha256
    assert route.placement_status == "placed"
    assert route.byte_status == "copied_from_candidate"
    assert route.no_overwrite_status == "pass"
    assert route.decode_roundtrip_status == "pass"
    assert route.provenance_status == "pass"
    assert route.blocker_ids == ()

    fmax = slices["ring_fmax_update"]
    assert fmax.slice_status == "present"
    assert fmax.covered_semantic_ops == ("max_update_global_max",)
    assert fmax.row_count == 30
    assert len(fmax.row_ids) == 30
    assert len(fmax.component_byte_offsets) == 30
    assert len(fmax.row_sha256s) == 30
    assert fmax.slice_sha256
    assert fmax.layout_epoch == route.layout_epoch
    assert fmax.layout_plan_sha256 == route.layout_plan_sha256
    assert fmax.placement_status == "placed"
    assert fmax.byte_status == "copied_from_candidate"
    assert fmax.no_overwrite_status == "pass"
    assert fmax.decode_roundtrip_status == "pass"
    assert fmax.provenance_status == "pass"
    assert fmax.blocker_ids == ()

    for family in EXPECTED_BLOCKED:
        item = slices[family]
        assert item.slice_status == "blocked"
        assert item.covered_semantic_ops == ()
        assert item.folded_into_slice_id is None
        assert item.folded_evidence_id is None
        assert item.row_count == 0
        assert item.row_ids == ()
        assert item.component_byte_offsets == ()
        assert item.row_sha256s == ()
        assert item.slice_sha256 is None
        assert item.placement_status == "blocked"
        assert item.byte_status == "blocked"
        assert item.no_overwrite_status == "blocked"
        assert item.decode_roundtrip_status == "blocked"
        assert item.provenance_status == "blocked"
        assert item.blocker_ids == (f"log10max_operator_slice_{family}_missing",)


def test_log10max_operator_slice_set_checker_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "compiler/tools/check_stream_compiler_log10max_operator_instruction_slice_set.py"
            ),
        ],
        check=False,
        cwd=ROOT,
        env={"PYTHONPATH": f"{ROOT / 'compiler'}:{ROOT / 'compiler' / 'tools'}"},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_log10max_operator_insts_component_candidate_is_partial() -> None:
    report = build_log10max_operator_insts_component_candidate()
    summary = report.summary()

    assert summary["component_status"] == "partial_operator_candidate"
    assert summary["integrated_row_count"] == 150
    assert summary["active_row_count"] == 150
    assert summary["reserved_row_count"] == 0
    assert summary["zero_padding_row_count"] == 0
    assert summary["unowned_nonzero_row_count"] == 0
    assert tuple(summary["expected_row_families"]) == EXPECTED_LOG10MAX_ROW_FAMILIES
    assert summary["present_row_families"] == ["route_copy", "ring_fmax_update"]
    assert summary["folded_row_families"] == []
    assert tuple(summary["missing_row_families"]) == EXPECTED_BLOCKED
    assert summary["component_sha256"] is None
    assert summary["diagnostic_partial_component_sha256"]
    assert summary["no_overwrite_status"] == "pass"
    assert summary["decode_roundtrip_status"] == "pass"
    assert summary["provenance_status"] == "pass"
    assert summary["micc_coherence_status"] == "not_checked"
    assert LOG10MAX_OPERATOR_INSTS_COMPONENT_PARTIAL in summary["blocker_ids"]
    assert report.runtime_ready is False
    assert report.uploadable is False
    assert report.to_plan()["operator_payload_manifest_entries"] == []


def test_log10max_operator_insts_component_candidate_checker_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "compiler/tools/check_stream_compiler_log10max_operator_insts_component_candidate.py"
            ),
        ],
        check=False,
        cwd=ROOT,
        env={"PYTHONPATH": f"{ROOT / 'compiler'}:{ROOT / 'compiler' / 'tools'}"},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_log10max_operator_control_coherence_is_full_operator_blocked() -> None:
    report = build_log10max_operator_control_coherence_report()
    summary = report.summary()

    assert summary["coherence_scope"] == "full_operator"
    assert summary["coherence_status"] == "blocked"
    assert summary["source_micc_candidate_id"] is None
    assert summary["source_exeblock_component_id"] is None
    assert summary["source_instance_component_id"] is None
    statuses = summary["status_by_check"]
    assert statuses["insts_component_status"] == "blocked"
    assert statuses["micc_candidate_status"] == "blocked"
    assert statuses["stage_pc_within_pe_local_inst_rows_status"] == "blocked"
    assert statuses["active_exeblock_points_to_owned_rows_status"] == "blocked"
    assert LOG10MAX_OPERATOR_CONTROL_COHERENCE_BLOCKED in summary["blocker_ids"]
    assert "log10max_control_coherence_component_partial" in summary["blocker_ids"]
    assert report.runtime_ready is False
    assert report.uploadable is False


def test_log10max_operator_control_coherence_checker_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "compiler/tools/check_stream_compiler_log10max_operator_control_coherence.py"
            ),
        ],
        check=False,
        cwd=ROOT,
        env={"PYTHONPATH": f"{ROOT / 'compiler'}:{ROOT / 'compiler' / 'tools'}"},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_log10max_operator_payload_manifest_candidate_is_blocked() -> None:
    report = build_log10max_operator_payload_manifest_candidate()
    summary = report.summary()

    assert tuple(summary["required_file_roles"]) == REQUIRED_LOG10MAX_PAYLOAD_FILE_ROLES
    assert summary["present_file_roles"] == []
    assert tuple(summary["missing_file_roles"]) == REQUIRED_LOG10MAX_PAYLOAD_FILE_ROLES
    assert summary["component_manifest_status"] == "blocked"
    assert summary["operator_payload_manifest_status"] == "blocked"
    assert summary["readiness_claim"] == "blocked"
    assert summary["component_hashes"] == {}
    assert "diagnostic_partial_insts_component" in summary["diagnostic_hashes"]
    assert summary["runtime_asset_status"] == "blocked"
    assert summary["simict_status"] == "not_run"
    assert summary["numerical_status"] == "not_checked"
    assert LOG10MAX_OPERATOR_PAYLOAD_MANIFEST_BLOCKED in summary["blocker_ids"]
    assert set(summary["blockers_by_layer"]) == {
        "slice_set",
        "insts_component",
        "control_coherence",
        "payload_manifest",
        "runtime_assets",
        "numerical",
    }
    assert report.runtime_ready is False
    assert report.uploadable is False


def test_log10max_operator_payload_manifest_candidate_checker_passes() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "compiler/tools/check_stream_compiler_log10max_operator_payload_manifest_candidate.py"
            ),
        ],
        check=False,
        cwd=ROOT,
        env={"PYTHONPATH": f"{ROOT / 'compiler'}:{ROOT / 'compiler' / 'tools'}"},
        text=True,
        capture_output=True,
    )
    assert result.returncode == 0, result.stdout + result.stderr
