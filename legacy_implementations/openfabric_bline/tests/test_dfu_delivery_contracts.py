from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "compiler"))
sys.path.insert(0, str(ROOT / "tests"))

from gpdpu_compiler.validation.delivery_contracts import (  # noqa: E402
    RUNTIME_READY_SCOPE,
    ComponentWriterArtifact,
    FileRecord,
    OperatorBindingArtifact,
    OperatorPayloadManifest,
    validate_delivery_candidate,
)
from test_dfu_binary_validation import _write_runtime_ready_payload  # noqa: E402


def test_delivery_contract_dataclasses_are_json_serializable() -> None:
    file_record = FileRecord(
        path="simulator_bin/tasks_conf_info_file.bin",
        size=480,
        sha256="0" * 64,
        role="component",
    )
    manifest = OperatorPayloadManifest(
        operator="maximum",
        payload_dir="payloads/maximum",
        readiness_claim="runtime_ready",
        profile_id="dfu3500_simict_legacy",
        selected_representation="component_files_plus_combined_images",
        selected_strategy="legacy_template_compat",
        runtime_assets=(
            FileRecord(
                path="runtime/riscv_src/riscv_control.json",
                size=128,
                sha256="1" * 64,
                role="runtime_asset",
            ),
        ),
        known_limitations=("runtime_ready_is_not_simict_or_numerical_proof",),
        files=(file_record,),
        component_artifacts=(
            ComponentWriterArtifact(
                component_name="tasks_conf_info_file.bin",
                writer_name="dfu3500_component_writer",
                operator="maximum",
                path="simulator_bin/tasks_conf_info_file.bin",
                sha256="0" * 64,
                size=480,
                profile_id="dfu3500_simict_legacy",
                selected_representation="component_file",
                row_count=1,
                row_size=480,
                writer_status="runtime_ready",
                unresolved_fields=("sub_task_loop_cond",),
                forbidden_fields_touched=("padded_capacity_rows",),
                assumptions={"active_rows_not_from_padding": True},
                files=(file_record,),
                state="runtime_ready",
            ),
        ),
        binding_artifacts=(
            OperatorBindingArtifact(
                operator="maximum",
                binding_name="dfu3500_legacy_template",
                source_plan_id="source-plan-0",
                template_plan_id="template-plan-0",
                selected_strategy="legacy_template_compat",
                concrete_template_count=1,
                symbolic_unresolved_count=0,
                unresolved_fields=(),
                numerical_contract_path="reference/Y.fp32.bin",
                assumptions={"decoder_is_diagnostic_only": True},
                files=(file_record,),
                state="runtime_ready",
            ),
        ),
    )

    payload = manifest.to_json()

    assert payload["readiness_claim"] == "runtime_ready"
    assert payload["profile_id"] == "dfu3500_simict_legacy"
    assert payload["selected_representation"] == "component_files_plus_combined_images"
    assert payload["selected_strategy"] == "legacy_template_compat"
    assert payload["runtime_assets"][0]["role"] == "runtime_asset"
    assert payload["known_limitations"] == [
        "runtime_ready_is_not_simict_or_numerical_proof"
    ]
    component = payload["component_artifacts"][0]
    assert component["schema_version"] == "dfu_component_writer_artifact_v1"
    assert component["operator"] == "maximum"
    assert component["path"] == "simulator_bin/tasks_conf_info_file.bin"
    assert component["profile_id"] == "dfu3500_simict_legacy"
    assert component["selected_representation"] == "component_file"
    assert component["row_count"] == 1
    assert component["row_size"] == 480
    assert component["writer_status"] == "runtime_ready"
    assert component["unresolved_fields"] == ["sub_task_loop_cond"]
    assert component["forbidden_fields_touched"] == ["padded_capacity_rows"]
    assert component["assumptions"] == {"active_rows_not_from_padding": True}
    assert payload["component_artifacts"][0]["state"] == "runtime_ready"
    binding = payload["binding_artifacts"][0]
    assert binding["operator"] == "maximum"
    assert binding["source_plan_id"] == "source-plan-0"
    assert binding["template_plan_id"] == "template-plan-0"
    assert binding["selected_strategy"] == "legacy_template_compat"
    assert binding["concrete_template_count"] == 1
    assert binding["symbolic_unresolved_count"] == 0
    assert binding["unresolved_fields"] == []
    assert binding["numerical_contract_path"] == "reference/Y.fp32.bin"
    assert binding["assumptions"] == {"decoder_is_diagnostic_only": True}


def test_validate_delivery_candidate_passes_runtime_ready_payload(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)

    report = validate_delivery_candidate(
        tmp_path,
        "unit_payload",
        min_state="uploadable",
    )

    assert report.passed is True
    assert report.final_state == "uploadable"
    assert report.validation_status == "pass"
    assert report.placeholder_shell_findings == ()
    assert Path(report.report_path).is_file()
    assert RUNTIME_READY_SCOPE in report.runtime_ready_scope
    assert "not a SimICT execution" in report.runtime_ready_scope


def test_validate_delivery_candidate_blocks_placeholder_marker(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)
    (tmp_path / "PLACEHOLDER.txt").write_text(
        "This smoke hook is a local-edit placeholder.\n"
    )

    report = validate_delivery_candidate(
        tmp_path,
        "unit_payload",
        min_state="uploadable",
    )

    assert report.passed is False
    assert report.final_state == "runtime_ready"
    assert report.validation_status == "pass"
    assert [finding.path for finding in report.placeholder_shell_findings] == [
        "PLACEHOLDER.txt"
    ]


def test_delivery_candidate_cli_reports_pass(tmp_path: Path) -> None:
    _write_runtime_ready_payload(tmp_path)

    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "compiler/tools/check_dfu_delivery_candidate.py"),
            str(tmp_path),
            "--operator",
            "unit_payload",
            "--min-state",
            "runtime_ready",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    assert "dfu_delivery_candidate=PASS" in completed.stdout
    assert "operator=unit_payload" in completed.stdout
    assert "report_path=" in completed.stdout
