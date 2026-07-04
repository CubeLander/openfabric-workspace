from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "compiler"))
sys.path.insert(0, str(ROOT / "compiler" / "tools"))

from check_bline_runtime_ready_preintegration import (  # noqa: E402
    LOG10MAX_COMPONENT_PLACEMENT_INTEGRATION_MISSING,
    LOG10MAX_EXE_BLOCK_WRITER_PLAN_MISSING,
    LOG10MAX_INSTRUCTION_BOUNDARY_PLAN_MISSING,
    LOG10MAX_INSTRUCTION_LAYOUT_PLAN_MISSING,
    LOG10MAX_ROUTE_ENDPOINT_STATUS_MISSING,
    LOG10MAX_ROUTE_FAMILY_PHASE2_DECISION_MISSING,
    LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING,
    _augment_log10max_inst_field_provenance_gate,
)
from gpdpu_compiler.core.stream_compiler.operator_payload_assembly import (  # noqa: E402
    RuntimeReadyGateInputStatus,
    RuntimeReadyPreIntegrationReport,
)


def test_phase0_endpoint_bound_family_and_flow_ack_pending_stays_blocked() -> None:
    augmented = _augment_log10max_inst_field_provenance_gate(
        _ready_log10max_only_report(),
        {
            "ring_first_delivery_plan": {
                "inst_field_provenance_gate": _closed_inst_field_gate(),
                "route_layout_gate": {
                    "route_endpoint_status": "endpoint_bound_layout_pending",
                    "route_family_status": "pending_phase2_decision",
                    "flow_ack_status": "pending_policy",
                    "instruction_layout_status": "missing",
                    "exe_block_writer_status": "missing",
                    "boundary_status": "missing",
                    "component_placement_status": "unplaced_candidate",
                },
            }
        },
    )
    status = augmented.operator_statuses[0]
    route_gate = status.summary["route_layout_gate"]

    assert status.state == "blocked"
    assert status.runtime_ready is False
    assert status.uploadable is False
    assert augmented.runtime_ready is False
    assert augmented.uploadable is False
    assert LOG10MAX_ROUTE_ENDPOINT_STATUS_MISSING not in status.missing_blockers
    assert LOG10MAX_ROUTE_FAMILY_PHASE2_DECISION_MISSING in status.missing_blockers
    assert LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING in status.missing_blockers
    assert LOG10MAX_INSTRUCTION_LAYOUT_PLAN_MISSING in status.missing_blockers
    assert LOG10MAX_EXE_BLOCK_WRITER_PLAN_MISSING in status.missing_blockers
    assert LOG10MAX_INSTRUCTION_BOUNDARY_PLAN_MISSING in status.missing_blockers
    assert LOG10MAX_COMPONENT_PLACEMENT_INTEGRATION_MISSING in status.missing_blockers
    assert route_gate["route_family_status"] == "pending_phase2_decision"
    assert route_gate["route_family_pending_is_selected"] is False


def test_phase1_layout_planned_unplaced_stays_blocked() -> None:
    augmented = _augment_log10max_inst_field_provenance_gate(
        _ready_log10max_only_report(),
        {
            "ring_first_delivery_plan": {
                "inst_field_provenance_gate": _closed_inst_field_gate(),
                "route_layout_gate": {
                    "route_endpoint_status": "endpoint_bound",
                    "route_family_status": "selected",
                    "flow_ack_status": "bound",
                    "instruction_layout_status": "planned",
                    "exe_block_writer_status": "planned",
                    "boundary_status": "bound",
                    "component_placement_status": "unplaced_candidate",
                },
            }
        },
    )
    status = augmented.operator_statuses[0]
    route_gate = status.summary["route_layout_gate"]

    assert status.state == "blocked"
    assert status.runtime_ready is False
    assert status.uploadable is False
    assert LOG10MAX_ROUTE_ENDPOINT_STATUS_MISSING not in status.missing_blockers
    assert LOG10MAX_ROUTE_FAMILY_PHASE2_DECISION_MISSING not in status.missing_blockers
    assert LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING not in status.missing_blockers
    assert LOG10MAX_INSTRUCTION_LAYOUT_PLAN_MISSING not in status.missing_blockers
    assert LOG10MAX_EXE_BLOCK_WRITER_PLAN_MISSING not in status.missing_blockers
    assert LOG10MAX_INSTRUCTION_BOUNDARY_PLAN_MISSING not in status.missing_blockers
    assert LOG10MAX_COMPONENT_PLACEMENT_INTEGRATION_MISSING in status.missing_blockers
    assert route_gate["component_placement_status"] == "unplaced_candidate"
    assert route_gate["component_integrated_required_for_runtime_ready"] is True
    assert augmented.runtime_ready is False
    assert augmented.uploadable is False


def test_route_candidate_decode_roundtrip_is_not_uploadable() -> None:
    augmented = _augment_log10max_inst_field_provenance_gate(
        _ready_log10max_only_report(),
        {
            "ring_first_delivery_plan": {
                "inst_field_provenance_gate": _closed_inst_field_gate(),
                "route_layout_gate": {
                    "route_endpoint_status": "endpoint_bound",
                    "route_family_status": "selected",
                    "flow_ack_status": "bound",
                    "instruction_layout_status": "planned",
                    "exe_block_writer_status": "planned",
                    "boundary_status": "bound",
                    "component_placement_status": "unplaced_candidate",
                    "route_candidate_decode_status": (
                        "candidate_route_decode_roundtrip"
                    ),
                },
            }
        },
    )
    status = augmented.operator_statuses[0]
    route_gate = status.summary["route_layout_gate"]

    assert status.state == "blocked"
    assert status.runtime_ready is False
    assert status.uploadable is False
    assert route_gate["candidate_decode_roundtrip"] is True
    assert route_gate["candidate_decode_roundtrip_is_uploadable"] is False
    assert route_gate["runtime_ready_claim"] is False
    assert route_gate["uploadable_claim"] is False
    assert LOG10MAX_COMPONENT_PLACEMENT_INTEGRATION_MISSING in status.missing_blockers
    assert augmented.runtime_ready is False
    assert augmented.uploadable is False


def _closed_inst_field_gate() -> dict[str, str]:
    return {
        "field_ownership_status": "bound",
        "field_binding_status": "bound",
        "row_body_candidate_status": "candidate_decode_roundtrip",
        "component_integration_status": "component_integrated",
        "placement_status": "component_integrated",
    }


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
