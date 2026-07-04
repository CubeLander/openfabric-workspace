from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "compiler"))
sys.path.insert(0, str(ROOT / "compiler" / "tools"))

from check_bline_runtime_ready_preintegration import (  # noqa: E402
    LOG10MAX_INST_FIELD_BINDING_MISSING,
    LOG10MAX_INST_FIELD_OWNERSHIP_MISSING,
    LOG10MAX_RING_UPDATE_COMPONENT_INTEGRATED_BYTES_MISSING,
    LOG10MAX_RING_UPDATE_ROW_BODY_CANDIDATE_BYTES_MISSING,
    _augment_log10max_inst_field_provenance_gate,
)
from gpdpu_compiler.core.stream_compiler.operator_payload_assembly import (  # noqa: E402
    RuntimeReadyGateInputStatus,
    RuntimeReadyPreIntegrationReport,
)


def test_inst_field_gate_reports_phase0_missing_blockers() -> None:
    report = _ready_log10max_only_report()

    augmented = _augment_log10max_inst_field_provenance_gate(
        report,
        {"ring_first_delivery_plan": {}},
    )
    status = augmented.operator_statuses[0]

    assert status.state == "blocked"
    assert status.runtime_ready is False
    assert status.uploadable is False
    assert LOG10MAX_INST_FIELD_OWNERSHIP_MISSING in status.missing_blockers
    assert LOG10MAX_INST_FIELD_BINDING_MISSING in status.missing_blockers
    assert (
        LOG10MAX_RING_UPDATE_ROW_BODY_CANDIDATE_BYTES_MISSING
        in status.missing_blockers
    )
    assert (
        LOG10MAX_RING_UPDATE_COMPONENT_INTEGRATED_BYTES_MISSING
        in status.missing_blockers
    )
    assert augmented.runtime_ready is False
    assert augmented.uploadable is False


def test_candidate_row_body_decode_roundtrip_is_not_uploadable() -> None:
    report = _ready_log10max_only_report()

    augmented = _augment_log10max_inst_field_provenance_gate(
        report,
        {
            "ring_first_delivery_plan": {
                "inst_field_provenance_gate": {
                    "field_ownership_status": "bound",
                    "field_binding_status": "bound",
                    "row_body_candidate_status": "candidate_decode_roundtrip",
                    "component_integration_status": "not_integrated",
                    "placement_status": "unplaced_candidate",
                }
            }
        },
    )
    status = augmented.operator_statuses[0]
    inst_gate = status.summary["inst_field_provenance_gate"]

    assert status.state == "blocked"
    assert status.runtime_ready is False
    assert status.uploadable is False
    assert LOG10MAX_INST_FIELD_OWNERSHIP_MISSING not in status.missing_blockers
    assert LOG10MAX_INST_FIELD_BINDING_MISSING not in status.missing_blockers
    assert (
        LOG10MAX_RING_UPDATE_ROW_BODY_CANDIDATE_BYTES_MISSING
        not in status.missing_blockers
    )
    assert (
        LOG10MAX_RING_UPDATE_COMPONENT_INTEGRATED_BYTES_MISSING
        in status.missing_blockers
    )
    assert inst_gate["candidate_decode_roundtrip"] is True
    assert inst_gate["candidate_decode_roundtrip_is_uploadable"] is False
    assert inst_gate["runtime_ready_claim"] is False
    assert inst_gate["uploadable_claim"] is False
    assert augmented.runtime_ready is False
    assert augmented.uploadable is False


def _ready_log10max_only_report() -> RuntimeReadyPreIntegrationReport:
    return RuntimeReadyPreIntegrationReport(
        operator_statuses=(
            RuntimeReadyGateInputStatus(
                operator="log10max",
                gate_id="ring_first_row_col_reduce_broadcast",
                state="ready",
                runtime_ready=False,
                uploadable=False,
                missing_blockers=(),
                summary={},
            ),
        ),
        payload_files_claimed=True,
        placeholder_files_present=False,
    )
