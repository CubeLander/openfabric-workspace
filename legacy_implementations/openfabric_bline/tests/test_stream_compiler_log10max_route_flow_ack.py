from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "compiler"))

from gpdpu_compiler.core.stream_compiler.log10max_ring_update_operands import (  # noqa: E402
    EXPECTED_PHASE_COUNTS,
)
from gpdpu_compiler.core.stream_compiler.log10max_route_flow_ack import (  # noqa: E402
    BASE_ADDR_SLOT_COUNT,
    LOG10MAX_ROUTE_COMPONENT_BYTE_OFFSET_MISSING,
    LOG10MAX_ROUTE_FLOW_ACK_FINAL_POLICY_MISSING,
    FLOW_ACK_EVIDENCE_REFS,
    LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING,
    FlowAckPolicy,
    build_log10max_route_flow_ack_candidate_report,
    build_log10max_route_flow_ack_final_policy_report,
    build_log10max_route_flow_ack_policy_report,
)
from gpdpu_compiler.core.stream_compiler.log10max_route_endpoint_patch import (  # noqa: E402
    LOG10MAX_ROUTE_COMPONENT_INTEGRATION_BLOCKER,
)


def test_flow_ack_report_defaults_to_fail_closed() -> None:
    report = build_log10max_route_flow_ack_policy_report()
    summary = report.summary()

    assert summary["policy_count"] == 30
    assert summary["phase_counts"] == EXPECTED_PHASE_COUNTS
    assert summary["policy_counts"] == {"blocked": 30}
    assert summary["flow_ack_status_counts"] == {"blocked": 30}
    assert summary["route_family_intent_counts"] == {"copy_like_candidate": 30}
    assert summary["copy_like_serialization_blocked_count"] == 30
    assert summary["copy_like_row_candidate_serialization_claim_count"] == 0
    assert summary["candidate_evidence_count"] == 90
    assert summary["candidate_policy_counts"] == {
        "child_edge_slot": 30,
        "last_physical_copy_lane_sets_one": 30,
        "source_template_fixed": 30,
    }
    assert summary["candidate_status_counts"] == {
        "blocked_conflicting_evidence": 60,
        "blocked_missing_exact_source_span": 30,
    }
    assert summary["candidate_serialization_claim_count"] == 0
    assert summary["candidate_final_component_claim_count"] == 0
    assert LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING in summary["blocker_ids"]
    assert summary["evidence_refs"] == list(FLOW_ACK_EVIDENCE_REFS)
    assert report.runtime_ready is False
    assert report.uploadable is False
    assert report.final_component_claim is False


def test_each_flow_ack_policy_has_evidence_and_no_serialization_claim() -> None:
    report = build_log10max_route_flow_ack_policy_report()
    seen_edges: set[str] = set()

    for policy in report.policies:
        assert policy.logical_route_edge_id not in seen_edges
        seen_edges.add(policy.logical_route_edge_id)
        assert policy.policy == "blocked"
        assert policy.status == "blocked"
        assert policy.flow_ack_status == "blocked"
        assert policy.route_family_intent == "copy_like_candidate"
        assert policy.blocks_copy_like_serialization is True
        assert policy.copy_like_row_candidate_serialization_claim is False
        assert policy.final_component_claim is False
        assert policy.rtl_projection_status == "not_claimed"
        assert policy.bound_flow_ack_by_physical_lane == {}
        assert policy.candidate_policy_evidence_refs == FLOW_ACK_EVIDENCE_REFS
        assert LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING in policy.blocker_ids
        assert policy.runtime_ready is False
        assert policy.uploadable is False

    assert len(seen_edges) == 30


def test_flow_ack_candidate_evidence_matrix_is_explicit_and_blocked() -> None:
    report = build_log10max_route_flow_ack_policy_report()
    expected = {
        "child_edge_slot",
        "last_physical_copy_lane_sets_one",
        "source_template_fixed",
    }
    candidates_by_edge: dict[str, set[str]] = {}

    for candidate in report.candidate_evidence_matrix:
        candidates_by_edge.setdefault(candidate.logical_route_edge_id, set()).add(
            candidate.candidate_policy
        )
        assert candidate.serialization_allowed is False
        assert candidate.final_component_claim is False
        assert LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING in candidate.blocker_ids
        if candidate.candidate_policy == "child_edge_slot":
            assert candidate.candidate_status == "blocked_conflicting_evidence"
            assert candidate.candidate_flow_ack_by_physical_lane == {
                0: 0,
                1: 0,
                2: 0,
                3: 0,
            }
            assert candidate.conflict_refs
            assert candidate.missing_evidence
        elif candidate.candidate_policy == "last_physical_copy_lane_sets_one":
            assert candidate.candidate_status == "blocked_conflicting_evidence"
            assert candidate.candidate_flow_ack_by_physical_lane == {
                0: 0,
                1: 0,
                2: 0,
                3: 1,
            }
            assert candidate.conflict_refs
            assert candidate.missing_evidence
        elif candidate.candidate_policy == "source_template_fixed":
            assert candidate.candidate_status == "blocked_missing_exact_source_span"
            assert candidate.candidate_flow_ack_by_physical_lane == {}
            assert candidate.missing_evidence
        else:
            raise AssertionError(candidate)

    assert len(report.candidate_evidence_matrix) == 90
    assert len(candidates_by_edge) == 30
    assert all(policy_set == expected for policy_set in candidates_by_edge.values())


def test_unbound_copy_like_serialization_claim_is_invalid() -> None:
    bad_policy = FlowAckPolicy(
        schema_version="1",
        policy_id="policy:bad",
        operator="log10max",
        route_role="GlobalMax",
        selected_strategy="ring_spmd_row_then_col",
        logical_route_edge_id="ring_edge:bad",
        source_endpoint_patch_id="patch:bad",
        phase="row_reduce",
        route_family_intent="copy_like_candidate",
        policy="blocked",
        status="blocked",
        applies_to="simulator_inst_t",
        rtl_projection_status="not_claimed",
        base_addr_slot_count=4,
        bound_flow_ack_by_physical_lane={},
        source_template_evidence_id=None,
        source_template_sha256=None,
        candidate_policy_evidence_refs=FLOW_ACK_EVIDENCE_REFS,
        copy_like_row_candidate_serialization_claim=True,
        final_component_claim=False,
        blocker_ids=(LOG10MAX_ROUTE_FLOW_ACK_POLICY_MISSING,),
    )

    assert bad_policy.flow_ack_status != "bound"
    assert bad_policy.copy_like_row_candidate_serialization_claim is True
    assert bad_policy.blocks_copy_like_serialization is True


def test_flow_ack_candidate_report_binds_last_lane_only() -> None:
    report = build_log10max_route_flow_ack_candidate_report()
    summary = report.summary()

    assert summary["logical_route_edge_count"] == 30
    assert summary["candidate_count"] == 120
    assert summary["phase_counts"] == {
        phase: count * 4 for phase, count in sorted(EXPECTED_PHASE_COUNTS.items())
    }
    assert summary["flow_ack_value_counts"] == {"0": 90, "1": 30}
    assert summary["flow_ack_one_phase_counts"] == EXPECTED_PHASE_COUNTS
    assert summary["flow_ack_status_counts"] == {"candidate_bound": 120}
    assert summary["final_policy_status_counts"] == {"pending_final_policy": 120}
    assert summary["base_slot_status_counts"] == {"range_checked": 120}
    assert summary["candidate_policy_counts"] == {
        "last_physical_copy_lane_sets_one": 120
    }
    assert summary["flow_ack_reason_counts"] == {
        "lane_idx_0_not_last_physical_copy_lane": 30,
        "lane_idx_1_not_last_physical_copy_lane": 30,
        "lane_idx_2_not_last_physical_copy_lane": 30,
        "lane_idx_3_last_physical_copy_lane": 30,
    }
    assert summary["final_component_claim_count"] == 0
    assert summary["runtime_ready_claim_count"] == 0
    assert summary["uploadable_claim_count"] == 0
    assert LOG10MAX_ROUTE_FLOW_ACK_FINAL_POLICY_MISSING in summary["blocker_ids"]
    assert report.runtime_ready is False
    assert report.uploadable is False
    assert report.final_component_claim is False


def test_each_flow_ack_candidate_is_report_only_and_range_checked() -> None:
    report = build_log10max_route_flow_ack_candidate_report()
    candidates_by_edge: dict[str, list[int]] = {}

    for candidate in report.candidates:
        candidates_by_edge.setdefault(candidate.logical_route_edge_id, []).append(
            candidate.physical_lane_index
        )
        expected_flow_ack = (
            1
            if candidate.physical_lane_index == candidate.physical_lane_count - 1
            else 0
        )
        expected_reason = (
            "lane_idx_3_last_physical_copy_lane"
            if expected_flow_ack
            else (
                f"lane_idx_{candidate.physical_lane_index}_"
                "not_last_physical_copy_lane"
            )
        )

        assert candidate.physical_lane_count == 4
        assert candidate.flow_ack == expected_flow_ack
        assert candidate.flow_ack_reason == expected_reason
        assert 0 <= candidate.flow_ack < BASE_ADDR_SLOT_COUNT
        assert candidate.in_base_slot_range is True
        assert candidate.base_slot_status == "range_checked"
        assert candidate.base_slot_binding_id is None
        assert candidate.candidate_policy == "last_physical_copy_lane_sets_one"
        assert candidate.flow_ack_status == "candidate_bound"
        assert candidate.final_policy_status == "pending_final_policy"
        assert LOG10MAX_ROUTE_FLOW_ACK_FINAL_POLICY_MISSING in candidate.blocker_ids
        assert candidate.final_component_claim is False
        assert candidate.runtime_ready is False
        assert candidate.uploadable is False

    assert len(candidates_by_edge) == 30
    assert all(sorted(lanes) == [0, 1, 2, 3] for lanes in candidates_by_edge.values())


def test_flow_ack_final_policy_binds_simulator_inst_t_only() -> None:
    report = build_log10max_route_flow_ack_final_policy_report()
    summary = report.summary()

    assert summary["logical_route_edge_count"] == 30
    assert summary["binding_count"] == 120
    assert summary["phase_counts"] == {
        phase: count * 4 for phase, count in sorted(EXPECTED_PHASE_COUNTS.items())
    }
    assert summary["flow_ack_value_counts"] == {"0": 90, "1": 30}
    assert summary["flow_ack_one_phase_counts"] == EXPECTED_PHASE_COUNTS
    assert summary["final_policy_status_counts"] == {"final_bound": 120}
    assert summary["base_slot_status_counts"] == {"asset_bound": 120}
    assert summary["policy_scope_counts"] == {"simulator_inst_t_only": 120}
    assert summary["rtl_projection_status_counts"] == {"not_claimed": 120}
    assert summary["final_component_claim_count"] == 0
    assert summary["runtime_ready_claim_count"] == 0
    assert summary["uploadable_claim_count"] == 0
    assert LOG10MAX_ROUTE_FLOW_ACK_FINAL_POLICY_MISSING not in summary["blocker_ids"]
    assert LOG10MAX_ROUTE_COMPONENT_BYTE_OFFSET_MISSING in summary["blocker_ids"]
    assert LOG10MAX_ROUTE_COMPONENT_INTEGRATION_BLOCKER in summary["blocker_ids"]
    assert report.runtime_ready is False
    assert report.uploadable is False
    assert report.final_component_claim is False


def test_each_flow_ack_final_policy_has_base_slot_evidence() -> None:
    report = build_log10max_route_flow_ack_final_policy_report()
    lanes_by_edge: dict[str, list[int]] = {}

    for binding in report.bindings:
        lanes_by_edge.setdefault(binding.logical_route_edge_id, []).append(
            binding.physical_lane_index
        )
        expected_flow_ack = (
            1
            if binding.physical_lane_index == binding.physical_lane_count - 1
            else 0
        )
        assert binding.flow_ack == expected_flow_ack
        assert binding.final_policy_status == "final_bound"
        assert binding.policy_scope == "simulator_inst_t_only"
        assert binding.rtl_projection_status == "not_claimed"
        assert binding.base_slot_status == "asset_bound"
        assert binding.base_slot_binding_id
        assert binding.base_slot_evidence_id
        assert binding.memory_template_check_report_id
        assert binding.simulator_path_exempt_evidence_id is None
        assert binding.in_base_slot_range is True
        assert binding.blocker_ids == ()
        assert binding.final_component_claim is False
        assert binding.runtime_ready is False
        assert binding.uploadable is False

    assert len(lanes_by_edge) == 30
    assert all(sorted(lanes) == [0, 1, 2, 3] for lanes in lanes_by_edge.values())
