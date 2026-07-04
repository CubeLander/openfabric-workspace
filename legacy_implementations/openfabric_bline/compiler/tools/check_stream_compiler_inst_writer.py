#!/usr/bin/env python3
"""Focused validation for the S2 ``inst_t`` raw-template overlay gate."""

from __future__ import annotations

from gpdpu_compiler.core.stream_compiler.debug_emit import emit_debug_row_artifact
from gpdpu_compiler.core.stream_compiler.field_offsets import (
    build_field_offset_preflight_plan,
)
from gpdpu_compiler.core.stream_compiler.folding import analyze_stream_loop_folding
from gpdpu_compiler.core.stream_compiler.inst_writers import (
    build_aline_template_span_candidate_report,
    build_compressed_template_span_authority_report,
    build_exact_template_binding_seed_report,
    build_exact_template_span_hash_candidate_report,
    build_raw_template_row_hash_readiness_report,
    build_raw_template_overlay_report,
    build_template_span_materialization_candidate_report,
    build_template_evidence_binding_report,
    summarize_aline_template_span_candidate_report,
    summarize_compressed_template_span_authority_report,
    summarize_exact_template_binding_seed_report,
    summarize_exact_template_span_hash_candidate_report,
    summarize_raw_template_row_hash_readiness_report,
    summarize_raw_template_overlay_report,
    summarize_template_span_materialization_candidate_report,
    summarize_template_evidence_binding_report,
)
from gpdpu_compiler.core.stream_compiler.aline_gemm_evidence import (
    build_aline_gemm_evidence_report,
)
from gpdpu_compiler.core.stream_compiler.micc_component_writers import (
    build_subtask_instance_semantics_report,
)
from gpdpu_compiler.core.stream_compiler.serializer_readiness import (
    build_serializer_readiness_plan,
)
from gpdpu_compiler.core.stream_compiler.vendor_components import (
    build_vendor_component_plan,
)
from gpdpu_compiler.core.stream_compiler.vendor_groups import (
    group_debug_rows_vendor_like,
    remap_vendor_like_groups_locally,
)
from gpdpu_compiler.core.dfu3500.task_resource_replay import (
    build_task_resource_replay_authority_report,
)
from stream_compiler_demo_pipeline import build_demo_pipeline


EXPECTED_OPCODE_COUNTS = {
    "ACC_PREPARE": 64,
    "HMMAL_OR_GEMM_UPDATE": 256,
    "LOAD_OR_COPY": 128,
    "ROUTE_RECV_VISIBILITY": 384,
    "STD": 64,
}

EXPECTED_EVIDENCE_ROLE_COUNTS = {
    "accumulator_prepare": 64,
    "compute_core:gemm_update": 256,
    "operand_materialize:A": 64,
    "operand_materialize:B": 64,
    "operand_route_recv:A": 192,
    "operand_route_recv:B": 192,
    "tile_store": 64,
}

EXPECTED_LEGACY_BLOCK_KIND_COUNTS = {
    "accumulator_prepare": 64,
    "compute_update": 256,
    "route_forward": 192,
    "route_source_materialize": 320,
    "tile_store": 64,
}

EXPECTED_MISSING_SEED_FIELDS = {
    "local_order_or_row_span": 896,
    "task_resource_replay_row_authority": 896,
    "template_row_sha256": 896,
}

EXPECTED_AUTHORITY_AWARE_MISSING_SEED_FIELDS = {
    "local_order_or_row_span": 896,
    "task_resource_replay_row_authority": 704,
    "template_row_sha256": 896,
}

EXPECTED_DEFAULT_MISSING_SEED_FIELDS = {
    **EXPECTED_MISSING_SEED_FIELDS,
    "s1_representation_selection": 896,
}

EXPECTED_CANDIDATE_RAW_ROW_HISTOGRAM = {
    "64": 384,
    "82": 64,
    "512": 256,
    "768": 192,
}

EXPECTED_ROLE_OPCODE_CANDIDATE_COUNTS = {
    "accumulator_prepare|ACC_PREPARE": {
        "role": "accumulator_prepare",
        "opcode": "ACC_PREPARE",
        "row_count": 64,
        "min_candidate_raw_row_count": 82,
        "max_candidate_raw_row_count": 82,
        "single_candidate_row_count": 0,
    },
    "compute_core:gemm_update|HMMAL_OR_GEMM_UPDATE": {
        "role": "compute_core:gemm_update",
        "opcode": "HMMAL_OR_GEMM_UPDATE",
        "row_count": 256,
        "min_candidate_raw_row_count": 512,
        "max_candidate_raw_row_count": 512,
        "single_candidate_row_count": 0,
    },
    "operand_materialize:A|LOAD_OR_COPY": {
        "role": "operand_materialize:A",
        "opcode": "LOAD_OR_COPY",
        "row_count": 64,
        "min_candidate_raw_row_count": 64,
        "max_candidate_raw_row_count": 64,
        "single_candidate_row_count": 0,
    },
    "operand_materialize:B|LOAD_OR_COPY": {
        "role": "operand_materialize:B",
        "opcode": "LOAD_OR_COPY",
        "row_count": 64,
        "min_candidate_raw_row_count": 64,
        "max_candidate_raw_row_count": 64,
        "single_candidate_row_count": 0,
    },
    "operand_route_recv:A|ROUTE_RECV_VISIBILITY": {
        "role": "operand_route_recv:A",
        "opcode": "ROUTE_RECV_VISIBILITY",
        "row_count": 192,
        "min_candidate_raw_row_count": 768,
        "max_candidate_raw_row_count": 768,
        "single_candidate_row_count": 0,
    },
    "operand_route_recv:B|ROUTE_RECV_VISIBILITY": {
        "role": "operand_route_recv:B",
        "opcode": "ROUTE_RECV_VISIBILITY",
        "row_count": 192,
        "min_candidate_raw_row_count": 64,
        "max_candidate_raw_row_count": 64,
        "single_candidate_row_count": 0,
    },
    "tile_store|STD": {
        "role": "tile_store",
        "opcode": "STD",
        "row_count": 64,
        "min_candidate_raw_row_count": 64,
        "max_candidate_raw_row_count": 64,
        "single_candidate_row_count": 0,
    },
}

EXPECTED_COMPRESSED_SPAN_ROLE_STATUS_COUNTS = {
    "accumulator_prepare": {"blocked_needs_span_policy": 64},
    "compute_core:gemm_update": {"blocked_needs_span_policy": 256},
    "operand_materialize:A": {"blocked_needs_span_policy": 64},
    "operand_materialize:B": {"blocked_needs_span_policy": 64},
    "operand_route_recv:A": {
        "partial_route_authority_span_policy_needed": 192,
    },
    "operand_route_recv:B": {"blocked_needs_span_policy": 192},
    "tile_store": {"blocked_needs_span_policy": 64},
}

EXPECTED_COMPRESSED_SPAN_ROLE_POLICIES = {
    "accumulator_prepare": "ACC_PREPARE_COMPRESSED_SPAN_POLICY",
    "compute_core:gemm_update": "HMMAL_COMPRESSED_SPAN_POLICY",
    "operand_materialize:A": "LDN_MATERIALIZE_COMPRESSED_SPAN_POLICY",
    "operand_materialize:B": "LDN_MATERIALIZE_COMPRESSED_SPAN_POLICY",
    "operand_route_recv:A": "SENDER_COPY_COMPRESSED_SPAN_POLICY",
    "operand_route_recv:B": "LDN_ROUTE_RECV_MATERIALIZE_COMPRESSED_SPAN_POLICY",
    "tile_store": "STD_COMPRESSED_SPAN_POLICY",
}

OPT_IN_SPAN_POLICY_ROLES = {
    "accumulator_prepare",
    "compute_core:gemm_update",
    "operand_materialize:A",
    "operand_materialize:B",
    "operand_route_recv:A",
    "operand_route_recv:B",
    "tile_store",
}

EXPECTED_OPT_IN_COMPRESSED_SPAN_ROLE_STATUS_COUNTS = {
    "accumulator_prepare": {"span_policy_candidate_closed": 64},
    "compute_core:gemm_update": {"span_policy_candidate_closed": 256},
    "operand_materialize:A": {"span_policy_candidate_closed": 64},
    "operand_materialize:B": {"span_policy_candidate_closed": 64},
    "operand_route_recv:A": {"route_span_policy_candidate_closed": 192},
    "operand_route_recv:B": {"route_span_policy_candidate_closed": 192},
    "tile_store": {"span_policy_candidate_closed": 64},
}

EXPECTED_OPT_IN_COMPRESSED_SPAN_POLICY_IDS = {
    "accumulator_prepare": "ALINE_CATALOG_SPAN_CANDIDATE_ACC_PREPARE_V1",
    "compute_core:gemm_update": "ALINE_CATALOG_SPAN_CANDIDATE_HMMAL_UPDATE_V1",
    "operand_materialize:A": "ALINE_CATALOG_SPAN_CANDIDATE_LDN_MATERIALIZE_A_V1",
    "operand_materialize:B": "ALINE_CATALOG_SPAN_CANDIDATE_LDN_MATERIALIZE_B_V1",
    "operand_route_recv:A": "ROUTE_VISIBILITY_SPAN_CANDIDATE_SENDER_COPY_A_V1",
    "operand_route_recv:B": "ROUTE_VISIBILITY_SPAN_CANDIDATE_CONSUMER_LDN_B_V1",
    "tile_store": "ALINE_CATALOG_SPAN_CANDIDATE_STD_STORE_V1",
}

EXPECTED_OPT_IN_COMPRESSED_SPAN_POLICY_SOURCES = {
    "accumulator_prepare": "aline_catalog_span_candidate",
    "compute_core:gemm_update": "aline_catalog_span_candidate",
    "operand_materialize:A": "aline_catalog_span_candidate",
    "operand_materialize:B": "aline_catalog_span_candidate",
    "operand_route_recv:A": (
        "task_resource_replay_route_authority+aline_catalog_span_candidate"
    ),
    "operand_route_recv:B": "aline_catalog_span_candidate",
    "tile_store": "aline_catalog_span_candidate",
}


def main() -> None:
    failures: list[str] = []

    pipeline = build_demo_pipeline("gemm_no_relu")
    evidence_report = build_template_evidence_binding_report(pipeline.binary_layout)
    evidence_summary = summarize_template_evidence_binding_report(evidence_report)
    aline_report = build_aline_gemm_evidence_report()
    aline_span_report = build_aline_template_span_candidate_report(
        pipeline.binary_layout,
        aline_report,
        evidence_report,
    )
    aline_span_summary = summarize_aline_template_span_candidate_report(
        aline_span_report
    )
    s1_semantics_report = _build_s1_semantics_report(pipeline)
    if not s1_semantics_report.selection_complete:
        failures.append(
            "expected S1 representation selection to be complete, got "
            f"{s1_semantics_report.to_plan()}"
        )
    default_seed_report = build_exact_template_binding_seed_report(
        pipeline.binary_layout,
        evidence_report,
    )
    default_seed_summary = summarize_exact_template_binding_seed_report(
        default_seed_report
    )
    if default_seed_summary["s1_representation_selection_status_counts"] != {
        "blocked_pending_s1_selection": 896,
    }:
        failures.append(
            "default S2 seed must remain fail-closed without S1 status, got "
            f"{default_seed_summary['s1_representation_selection_status_counts']}"
        )
    if (
        default_seed_summary["missing_seed_field_counts"]
        != EXPECTED_DEFAULT_MISSING_SEED_FIELDS
    ):
        failures.append(
            "default S2 seed should still require S1 selection, got "
            f"{default_seed_summary['missing_seed_field_counts']}"
        )
    seed_report = build_exact_template_binding_seed_report(
        pipeline.binary_layout,
        evidence_report,
        s1_representation_selection_complete=s1_semantics_report.selection_complete,
    )
    seed_summary = summarize_exact_template_binding_seed_report(seed_report)
    task_resource_authority_report = build_task_resource_replay_authority_report(
        s2_bindings=seed_report.bindings,
    )
    authority_seed_report = build_exact_template_binding_seed_report(
        pipeline.binary_layout,
        evidence_report,
        s1_representation_selection_complete=s1_semantics_report.selection_complete,
        task_resource_replay_authority_report=task_resource_authority_report,
    )
    authority_seed_summary = summarize_exact_template_binding_seed_report(
        authority_seed_report
    )
    compressed_span_authority_report = (
        build_compressed_template_span_authority_report(
            pipeline.binary_layout,
            aline_span_report,
            task_resource_replay_authority_report=(
                task_resource_authority_report
            ),
        )
    )
    compressed_span_authority_summary = (
        summarize_compressed_template_span_authority_report(
            compressed_span_authority_report
        )
    )
    opt_in_compressed_span_authority_report = (
        build_compressed_template_span_authority_report(
            pipeline.binary_layout,
            aline_span_report,
            task_resource_replay_authority_report=(
                task_resource_authority_report
            ),
            enabled_role_span_policies=OPT_IN_SPAN_POLICY_ROLES,
        )
    )
    opt_in_compressed_span_authority_summary = (
        summarize_compressed_template_span_authority_report(
            opt_in_compressed_span_authority_report
        )
    )
    exact_span_hash_report = build_exact_template_span_hash_candidate_report(
        pipeline.binary_layout,
        opt_in_compressed_span_authority_report,
    )
    exact_span_hash_summary = summarize_exact_template_span_hash_candidate_report(
        exact_span_hash_report
    )
    span_materialization_report = build_template_span_materialization_candidate_report(
        pipeline.binary_layout,
        exact_span_hash_report,
    )
    span_materialization_summary = (
        summarize_template_span_materialization_candidate_report(
            span_materialization_report
        )
    )
    raw_hash_readiness_report = build_raw_template_row_hash_readiness_report(
        pipeline.binary_layout,
        exact_span_hash_report,
    )
    raw_hash_readiness_summary = summarize_raw_template_row_hash_readiness_report(
        raw_hash_readiness_report
    )
    report = build_raw_template_overlay_report(pipeline.binary_layout)
    summary = summarize_raw_template_overlay_report(report)

    if evidence_summary["binding_status"] != "candidate_report_only":
        failures.append(
            f"expected candidate evidence report, got {evidence_summary['binding_status']}"
        )
    if evidence_summary["matched_template_evidence_count"] != 896:
        failures.append(
            "expected all concrete rows to match legacy template evidence, got "
            f"{evidence_summary['matched_template_evidence_count']}"
        )
    if evidence_summary["candidate_evidence_sha256_count"] != 896:
        failures.append(
            "expected candidate evidence hashes for all rows, got "
            f"{evidence_summary['candidate_evidence_sha256_count']}"
        )
    if evidence_summary["missing_raw_template_bytes_count"] != 896:
        failures.append(
            "candidate evidence must not pretend exact raw row bytes are bound, got "
            f"{evidence_summary['missing_raw_template_bytes_count']}"
        )
    if evidence_summary["unmatched_template_evidence_count"] != 0:
        failures.append(
            "expected no unmatched evidence rows, got "
            f"{evidence_summary['unmatched_template_evidence_count']}"
        )
    if evidence_summary["role_counts"] != EXPECTED_EVIDENCE_ROLE_COUNTS:
        failures.append(f"unexpected evidence role counts: {evidence_summary['role_counts']}")
    if evidence_summary["legacy_block_kind_counts"] != EXPECTED_LEGACY_BLOCK_KIND_COUNTS:
        failures.append(
            "unexpected legacy block-kind evidence counts: "
            f"{evidence_summary['legacy_block_kind_counts']}"
        )
    if evidence_summary["candidate_raw_row_count_histogram"] != EXPECTED_CANDIDATE_RAW_ROW_HISTOGRAM:
        failures.append(
            "unexpected candidate raw row histogram: "
            f"{evidence_summary['candidate_raw_row_count_histogram']}"
        )
    if evidence_summary["single_candidate_raw_row_count"] != 0:
        failures.append(
            "no current row should claim single-candidate closure, got "
            f"{evidence_summary['single_candidate_raw_row_count']}"
        )
    if (
        evidence_summary["role_opcode_candidate_raw_row_counts"]
        != EXPECTED_ROLE_OPCODE_CANDIDATE_COUNTS
    ):
        failures.append(
            "unexpected role/opcode candidate raw row counts: "
            f"{evidence_summary['role_opcode_candidate_raw_row_counts']}"
        )
    if evidence_summary["diagnostic_count"] != 0:
        failures.append(
            f"expected no evidence diagnostics, got {evidence_summary['diagnostic_count']}"
        )
    if not evidence_report.blockers or "missing exact raw template row bytes" not in evidence_report.blockers[0]:
        failures.append(f"expected exact raw row blocker, got {evidence_report.blockers}")

    if seed_summary["seed_status"] != "blocked":
        failures.append(f"expected blocked exact seed, got {seed_summary['seed_status']}")
    if seed_summary["exact_bound_row_count"] != 0:
        failures.append(
            "current B-line must not claim exact template rows, got "
            f"{seed_summary['exact_bound_row_count']}"
        )
    if seed_summary["partial_candidate_row_count"] != 896:
        failures.append(
            "expected all rows to advance to partial candidate seed, got "
            f"{seed_summary['partial_candidate_row_count']}"
        )
    if seed_summary["single_candidate_row_count"] != 0:
        failures.append(
            "expected no single-candidate exact seed rows, got "
            f"{seed_summary['single_candidate_row_count']}"
        )
    if seed_summary["blocked_row_count"] != 896:
        failures.append(
            f"expected 896 blocked exact seed rows, got {seed_summary['blocked_row_count']}"
        )
    if seed_summary["missing_seed_field_counts"] != EXPECTED_MISSING_SEED_FIELDS:
        failures.append(
            "unexpected exact seed missing fields: "
            f"{seed_summary['missing_seed_field_counts']}"
        )
    if seed_summary["required_raw_template_bytes_status_counts"] != {
        "partial_candidate_pending_task_resource_replay_row_authority": 192,
        "partial_multi_candidate_pending_local_order": 704,
    }:
        failures.append(
            "unexpected raw template byte seed statuses: "
            f"{seed_summary['required_raw_template_bytes_status_counts']}"
        )
    if seed_summary["exact_seed_candidate_status_counts"] != {
        "partial_candidate_pending_task_resource_replay_row_authority": 192,
        "partial_multi_candidate_pending_local_order": 704,
    }:
        failures.append(
            "unexpected exact seed candidate statuses: "
            f"{seed_summary['exact_seed_candidate_status_counts']}"
        )
    if seed_summary["s1_representation_selection_status_counts"] != {
        "closed": 896,
    }:
        failures.append(
            "S1 representation selection should be consumed as closed, got "
            f"{seed_summary['s1_representation_selection_status_counts']}"
        )
    if seed_summary["subtask_instance_semantics_status_counts"] != {
        "closed": 896,
    }:
        failures.append(
            "S1 subtask instance semantics should be consumed as closed, got "
            f"{seed_summary['subtask_instance_semantics_status_counts']}"
        )
    bad_closure_roles = {
        role: record
        for role, record in seed_summary["exact_seed_closure_by_role"].items()
        if record["closure_status"] != "requires_task_resource_replay_or_local_order"
        or record["single_candidate_raw_row_count"] != 0
        or record["closed_row_count"] != 0
    }
    if bad_closure_roles:
        failures.append(f"unexpected exact seed closure by role: {bad_closure_roles}")
    if seed_summary["role_counts"] != EXPECTED_EVIDENCE_ROLE_COUNTS:
        failures.append(f"unexpected exact seed role counts: {seed_summary['role_counts']}")
    if seed_summary["diagnostic_count"] != 0:
        failures.append(f"expected no exact seed diagnostics, got {seed_summary['diagnostic_count']}")
    if len(seed_report.blockers) != 1:
        failures.append(f"expected only exact seed blocker, got {seed_report.blockers}")

    if task_resource_authority_report.authority_status != "partial":
        failures.append(
            "TaskResourceReplay authority should be partial, got "
            f"{task_resource_authority_report.authority_status}"
        )
    if authority_seed_summary["seed_status"] != "blocked":
        failures.append(
            "authority-aware exact seed must remain blocked, got "
            f"{authority_seed_summary['seed_status']}"
        )
    if authority_seed_summary["exact_bound_row_count"] != 0:
        failures.append(
            "authority-aware seed must not claim exact template rows, got "
            f"{authority_seed_summary['exact_bound_row_count']}"
        )
    if (
        authority_seed_summary["missing_seed_field_counts"]
        != EXPECTED_AUTHORITY_AWARE_MISSING_SEED_FIELDS
    ):
        failures.append(
            "authority-aware seed should only close TaskResource authority for "
            "covered route-recv rows, got "
            f"{authority_seed_summary['missing_seed_field_counts']}"
        )
    if authority_seed_summary["task_resource_replay_authority_status_counts"] != {
        "closed": 192,
        "open": 704,
    }:
        failures.append(
            "unexpected TaskResourceReplay authority closure counts: "
            f"{authority_seed_summary['task_resource_replay_authority_status_counts']}"
        )
    if (
        authority_seed_summary["required_raw_template_bytes_status_counts"]
        != seed_summary["required_raw_template_bytes_status_counts"]
    ):
        failures.append(
            "authority report must not promote required raw byte statuses, got "
            f"{authority_seed_summary['required_raw_template_bytes_status_counts']}"
        )
    if (
        authority_seed_summary["exact_seed_candidate_status_counts"]
        != seed_summary["exact_seed_candidate_status_counts"]
    ):
        failures.append(
            "authority report must not promote exact seed candidate statuses, got "
            f"{authority_seed_summary['exact_seed_candidate_status_counts']}"
        )

    if compressed_span_authority_summary["authority_status"] != "blocked":
        failures.append(
            "compressed span authority report must stay blocked, got "
            f"{compressed_span_authority_summary['authority_status']}"
        )
    if compressed_span_authority_summary["bytes_emitted"] is not False:
        failures.append("compressed span authority report must not emit bytes")
    if compressed_span_authority_summary["instruction_row_count"] != 896:
        failures.append(
            "expected 896 compressed span authority rows, got "
            f"{compressed_span_authority_summary['instruction_row_count']}"
        )
    if compressed_span_authority_summary["exact_span_count"] != 0:
        failures.append(
            "compressed span authority must not claim exact spans, got "
            f"{compressed_span_authority_summary['exact_span_count']}"
        )
    if compressed_span_authority_summary["span_policy_needed_count"] != 896:
        failures.append(
            "expected all rows to require span policy, got "
            f"{compressed_span_authority_summary['span_policy_needed_count']}"
        )
    if compressed_span_authority_summary["closed_policy_row_count"] != 0:
        failures.append(
            "default compressed span path must not close policy candidates, got "
            f"{compressed_span_authority_summary['closed_policy_row_count']}"
        )
    if compressed_span_authority_summary["blocked_policy_row_count"] != 896:
        failures.append(
            "default compressed span path should keep all policies blocked, got "
            f"{compressed_span_authority_summary['blocked_policy_row_count']}"
        )
    if compressed_span_authority_summary["route_policy_closed_count"] != 0:
        failures.append(
            "default compressed span path must not close route policies, got "
            f"{compressed_span_authority_summary['route_policy_closed_count']}"
        )
    if compressed_span_authority_summary["route_policy_blocked_count"] != 384:
        failures.append(
            "default compressed span path should keep route policies blocked, got "
            f"{compressed_span_authority_summary['route_policy_blocked_count']}"
        )
    if compressed_span_authority_summary["task_resource_partial_count"] != 192:
        failures.append(
            "expected 192 partial route authority rows, got "
            f"{compressed_span_authority_summary['task_resource_partial_count']}"
        )
    if compressed_span_authority_summary["span_authority_status_counts"] != {
        "blocked_needs_span_policy": 704,
        "partial_route_authority_span_policy_needed": 192,
    }:
        failures.append(
            "unexpected compressed span authority statuses: "
            f"{compressed_span_authority_summary['span_authority_status_counts']}"
        )
    if (
        compressed_span_authority_summary["role_status_counts"]
        != EXPECTED_COMPRESSED_SPAN_ROLE_STATUS_COUNTS
    ):
        failures.append(
            "unexpected compressed span role statuses: "
            f"{compressed_span_authority_summary['role_status_counts']}"
        )
    compressed_span_role_policies = {
        role: decision["required_policy"]
        for role, decision in compressed_span_authority_summary[
            "role_next_decisions"
        ].items()
    }
    if compressed_span_role_policies != EXPECTED_COMPRESSED_SPAN_ROLE_POLICIES:
        failures.append(
            "unexpected compressed span role policies: "
            f"{compressed_span_role_policies}"
        )
    if any(
        record.span_authority_status in {"exact", "ready"}
        for record in compressed_span_authority_report.records
    ):
        failures.append("compressed span authority must not produce exact/ready rows")
    if compressed_span_authority_summary["diagnostic_count"] != 0:
        failures.append(
            "expected no compressed span diagnostics, got "
            f"{compressed_span_authority_summary['diagnostic_count']}"
        )

    if opt_in_compressed_span_authority_summary["authority_status"] != "blocked":
        failures.append(
            "opt-in compressed span authority must remain blocked, got "
            f"{opt_in_compressed_span_authority_summary['authority_status']}"
        )
    if opt_in_compressed_span_authority_summary["bytes_emitted"] is not False:
        failures.append("opt-in compressed span authority report must not emit bytes")
    if opt_in_compressed_span_authority_summary["instruction_row_count"] != 896:
        failures.append(
            "expected 896 opt-in compressed span rows, got "
            f"{opt_in_compressed_span_authority_summary['instruction_row_count']}"
        )
    if opt_in_compressed_span_authority_summary["exact_span_count"] != 0:
        failures.append(
            "opt-in policy closure must not claim exact spans, got "
            f"{opt_in_compressed_span_authority_summary['exact_span_count']}"
        )
    if opt_in_compressed_span_authority_summary["closed_policy_row_count"] != 896:
        failures.append(
            "expected 896 opt-in policy candidate closed rows, got "
            f"{opt_in_compressed_span_authority_summary['closed_policy_row_count']}"
        )
    if opt_in_compressed_span_authority_summary["blocked_policy_row_count"] != 0:
        failures.append(
            "expected 0 opt-in rows to stay policy-blocked, got "
            f"{opt_in_compressed_span_authority_summary['blocked_policy_row_count']}"
        )
    if opt_in_compressed_span_authority_summary["route_policy_closed_count"] != 384:
        failures.append(
            "expected 384 route opt-in policy candidate closed rows, got "
            f"{opt_in_compressed_span_authority_summary['route_policy_closed_count']}"
        )
    if opt_in_compressed_span_authority_summary["route_policy_blocked_count"] != 0:
        failures.append(
            "expected 0 route opt-in rows to stay policy-blocked, got "
            f"{opt_in_compressed_span_authority_summary['route_policy_blocked_count']}"
        )
    if opt_in_compressed_span_authority_summary["span_policy_needed_count"] != 0:
        failures.append(
            "opt-in span policy needed count should only include still-blocked rows, got "
            f"{opt_in_compressed_span_authority_summary['span_policy_needed_count']}"
        )
    if opt_in_compressed_span_authority_summary["task_resource_partial_count"] != 0:
        failures.append(
            "route opt-in should close partial route authority policy rows, got "
            f"{opt_in_compressed_span_authority_summary['task_resource_partial_count']}"
        )
    if (
        opt_in_compressed_span_authority_summary["span_authority_status_counts"]
        != {
            "route_span_policy_candidate_closed": 384,
            "span_policy_candidate_closed": 512,
        }
    ):
        failures.append(
            "unexpected opt-in compressed span statuses: "
            f"{opt_in_compressed_span_authority_summary['span_authority_status_counts']}"
        )
    if (
        opt_in_compressed_span_authority_summary["role_status_counts"]
        != EXPECTED_OPT_IN_COMPRESSED_SPAN_ROLE_STATUS_COUNTS
    ):
        failures.append(
            "unexpected opt-in compressed span role statuses: "
            f"{opt_in_compressed_span_authority_summary['role_status_counts']}"
        )
    opt_in_role_decisions = opt_in_compressed_span_authority_summary[
        "role_next_decisions"
    ]
    opt_in_policy_ids = {
        role: decision["policy_id"]
        for role, decision in opt_in_role_decisions.items()
        if decision["policy_candidate_status"] == "span_policy_candidate_closed"
    }
    if opt_in_policy_ids != EXPECTED_OPT_IN_COMPRESSED_SPAN_POLICY_IDS:
        failures.append(
            "unexpected opt-in compressed span policy ids: "
            f"{opt_in_policy_ids}"
        )
    for role in OPT_IN_SPAN_POLICY_ROLES:
        decision = opt_in_role_decisions[role]
        if (
            decision["policy_source"]
            != EXPECTED_OPT_IN_COMPRESSED_SPAN_POLICY_SOURCES[role]
        ):
            failures.append(
                f"opt-in role {role} should cite expected policy source, got "
                f"{decision}"
            )
        if decision["does_not_emit_bytes"] is not True:
            failures.append(
                f"opt-in role {role} must be marked does_not_emit_bytes, got "
                f"{decision}"
            )
        if decision["requires_template_row_hash"] is not True:
            failures.append(
                f"opt-in role {role} must still require template row hash, got "
                f"{decision}"
            )
    route_a_decision = opt_in_role_decisions["operand_route_recv:A"]
    if route_a_decision["requires_sender_copy_exact_span"] is not True:
        failures.append(
            "route A policy closure must still require sender COPY exact span, got "
            f"{route_a_decision}"
        )
    if route_a_decision["policy_candidate_blockers"]:
        failures.append(
            "route A opt-in should have TaskResourceReplay authority closed, got "
            f"{route_a_decision}"
        )
    route_b_decision = opt_in_role_decisions["operand_route_recv:B"]
    if route_b_decision["requires_sender_copy_exact_span"] is not False:
        failures.append(
            "route B is consumer-side LDN materialize visibility and must not "
            f"require sender COPY exact span, got {route_b_decision}"
        )
    if route_b_decision["policy_candidate_blockers"]:
        failures.append(
            "route B opt-in should close with consumer LDN materialize evidence, got "
            f"{route_b_decision}"
        )
    if any(
        record.span_authority_status == "span_policy_candidate_closed"
        and (
            record.policy_source != "aline_catalog_span_candidate"
            or record.does_not_emit_bytes is not True
            or record.requires_template_row_hash is not True
        )
        for record in opt_in_compressed_span_authority_report.records
    ):
        failures.append(
            "closed opt-in rows must carry source/does_not_emit_bytes/hash-required flags"
        )
    if any(
        record.span_authority_status == "route_span_policy_candidate_closed"
        and (
            record.policy_source
            != EXPECTED_OPT_IN_COMPRESSED_SPAN_POLICY_SOURCES[record.role]
            or record.does_not_emit_bytes is not True
            or record.requires_template_row_hash is not True
            or (
                record.role == "operand_route_recv:A"
                and record.requires_sender_copy_exact_span is not True
            )
            or (
                record.role == "operand_route_recv:B"
                and record.requires_sender_copy_exact_span is not False
            )
        )
        for record in opt_in_compressed_span_authority_report.records
    ):
        failures.append(
            "closed route opt-in rows must carry route source/bytes/hash/sender flags"
        )

    if exact_span_hash_summary["candidate_status"] != "candidate_report_only":
        failures.append(
            "exact span hash report should be report-only candidate, got "
            f"{exact_span_hash_summary['candidate_status']}"
        )
    if exact_span_hash_summary["bytes_emitted"] is not False:
        failures.append("exact span hash report must not emit bytes")
    if exact_span_hash_summary["instruction_row_count"] != 896:
        failures.append(
            "exact span hash report should cover all rows, got "
            f"{exact_span_hash_summary['instruction_row_count']}"
        )
    if exact_span_hash_summary["span_hash_candidate_count"] != 896:
        failures.append(
            "opt-in closed span policies should produce 896 span hash candidates, got "
            f"{exact_span_hash_summary['span_hash_candidate_count']}"
        )
    if exact_span_hash_summary["blocked_row_count"] != 0:
        failures.append(
            "opt-in exact span hash candidate report should have no blocked rows, got "
            f"{exact_span_hash_summary['blocked_row_count']}"
        )
    if exact_span_hash_summary["raw_overlay_consumable_count"] != 0:
        failures.append(
            "span hash candidates must not be raw overlay consumable, got "
            f"{exact_span_hash_summary['raw_overlay_consumable_count']}"
        )
    if exact_span_hash_summary["status_counts"] != {
        "span_hash_candidate_available": 896,
    }:
        failures.append(
            "unexpected exact span hash status counts: "
            f"{exact_span_hash_summary['status_counts']}"
        )
    if any(record.raw_overlay_consumable for record in exact_span_hash_report.records):
        failures.append("no span hash candidate may be raw overlay consumable")
    if any(record.span_hash_sha256 is None for record in exact_span_hash_report.records):
        failures.append("all opt-in span hash candidate rows should have a digest")
    if any(
        record.candidate_catalog_span_sha256 is None
        for record in aline_span_report.records
    ):
        failures.append("all A-line span candidate rows should carry span digest")
    if any(
        record.candidate_catalog_span_sha256 is None
        for record in exact_span_hash_report.records
    ):
        failures.append("all exact span hash records should carry source span digest")
    if span_materialization_summary["materialization_status"] != "candidate_report_only":
        failures.append(
            "span materialization should be report-only candidate, got "
            f"{span_materialization_summary['materialization_status']}"
        )
    if span_materialization_summary["bytes_emitted"] is not False:
        failures.append("span materialization candidate report must not emit bytes")
    if span_materialization_summary["instruction_row_count"] != 896:
        failures.append(
            "span materialization report should cover all rows, got "
            f"{span_materialization_summary['instruction_row_count']}"
        )
    if span_materialization_summary["materialized_span_candidate_count"] != 896:
        failures.append(
            "expected every row to have a materialized span candidate, got "
            f"{span_materialization_summary['materialized_span_candidate_count']}"
        )
    if span_materialization_summary["blocked_row_count"] != 0:
        failures.append(
            "materialized span candidates should have no missing-span rows, got "
            f"{span_materialization_summary['blocked_row_count']}"
        )
    if span_materialization_summary["raw_overlay_consumable_count"] != 0:
        failures.append(
            "materialized span candidates must not be raw overlay consumable, got "
            f"{span_materialization_summary['raw_overlay_consumable_count']}"
        )
    if span_materialization_summary["status_counts"] != {
        "span_materialization_candidate_available": 896,
    }:
        failures.append(
            "unexpected span materialization statuses: "
            f"{span_materialization_summary['status_counts']}"
        )
    if span_materialization_summary["materialized_span_total_byte_count"] <= 0:
        failures.append(
            "span materialization should expose positive candidate byte count, got "
            f"{span_materialization_summary['materialized_span_total_byte_count']}"
        )
    if (
        sum(record.materialized_span_byte_count for record in span_materialization_report.records)
        != span_materialization_summary["materialized_span_total_byte_count"]
    ):
        failures.append("span materialization total byte count should match records")
    if any(
        record.raw_template_row_sha256 is not None
        for record in span_materialization_report.records
    ):
        failures.append(
            "span materialization must not invent single raw template row hashes"
        )
    if any(
        record.span_row_hash_sequence_sha256 is None
        for record in span_materialization_report.records
    ):
        failures.append("all materialized span candidates should carry span digest")
    if raw_hash_readiness_summary["readiness_status"] != "blocked":
        failures.append(
            "raw template row hash readiness should stay blocked, got "
            f"{raw_hash_readiness_summary['readiness_status']}"
        )
    if raw_hash_readiness_summary["bytes_emitted"] is not False:
        failures.append("raw hash readiness report must not emit bytes")
    if raw_hash_readiness_summary["instruction_row_count"] != 896:
        failures.append(
            "raw hash readiness report should cover all rows, got "
            f"{raw_hash_readiness_summary['instruction_row_count']}"
        )
    if raw_hash_readiness_summary["span_hash_candidate_count"] != 896:
        failures.append(
            "raw hash readiness should consume 896 span hash candidates, got "
            f"{raw_hash_readiness_summary['span_hash_candidate_count']}"
        )
    if raw_hash_readiness_summary["raw_template_row_hash_ready_count"] != 0:
        failures.append(
            "span hash candidates must not become raw template row hashes, got "
            f"{raw_hash_readiness_summary['raw_template_row_hash_ready_count']}"
        )
    if raw_hash_readiness_summary["blocked_row_count"] != 896:
        failures.append(
            "raw hash readiness should block all rows until materialization, got "
            f"{raw_hash_readiness_summary['blocked_row_count']}"
        )
    if raw_hash_readiness_summary["readiness_status_counts"] != {
        "blocked_span_hash_is_not_raw_template_row": 896,
    }:
        failures.append(
            "unexpected raw hash readiness status counts: "
            f"{raw_hash_readiness_summary['readiness_status_counts']}"
        )
    if any(record.template_row_sha256 is not None for record in raw_hash_readiness_report.records):
        failures.append("raw hash readiness must not invent template_row_sha256")

    if summary["writer_status"] != "blocked":
        failures.append(f"expected blocked writer, got {summary['writer_status']}")
    if summary["bytes_emitted"] is not False:
        failures.append("writer must not emit bytes while blocked")
    if summary["struct_name"] != "inst_t":
        failures.append(f"unexpected struct name: {summary['struct_name']}")
    if summary["record_size_bytes"] != 304:
        failures.append(f"unexpected inst_t record size: {summary['record_size_bytes']}")
    if summary["instruction_row_count"] != 896:
        failures.append(
            f"expected 896 concrete instruction rows, got {summary['instruction_row_count']}"
        )
    if summary["zero_instruction_boundary_count"] != 64:
        failures.append(
            "expected 64 zero-instruction boundaries, got "
            f"{summary['zero_instruction_boundary_count']}"
        )
    if summary["symbolic_unresolved_count"] != 0:
        failures.append(
            "S2 gate requires symbolic_unresolved_count=0, got "
            f"{summary['symbolic_unresolved_count']}"
        )
    if summary["template_row_sha256_missing_count"] != 896:
        failures.append(
            "expected all concrete rows to be blocked on missing template hashes, got "
            f"{summary['template_row_sha256_missing_count']}"
        )
    if summary["forbidden_fields_touched_count"] != 0:
        failures.append(
            "S2 gate forbids touching TileMicroBlock/forbidden fields, got "
            f"{report.forbidden_fields_touched}"
        )
    if summary["unknown_fields_touched_count"] != 0:
        failures.append(
            "S2 gate forbids touching unknown inst_t fields, got "
            f"{report.unknown_fields_touched}"
        )
    if summary["patched_field_count"] != 0:
        failures.append(f"writer must not patch fields yet: {report.patched_fields}")
    if summary["zero_fill_field_count"] != 0:
        failures.append(f"writer must not zero-fill inst_t fields yet: {report.zero_fill_fields}")
    if summary["template_backed_field_count"] != 0:
        failures.append(
            "missing template hashes mean no row is template-backed yet: "
            f"{report.template_backed_fields}"
        )
    if summary["row_status_counts"] != {"blocked": 896}:
        failures.append(f"unexpected row statuses: {summary['row_status_counts']}")
    if summary["opcode_counts"] != EXPECTED_OPCODE_COUNTS:
        failures.append(f"unexpected opcode counts: {summary['opcode_counts']}")
    if summary["diagnostic_count"] != 0:
        failures.append(f"expected no upstream diagnostics, got {summary['diagnostic_count']}")
    if not report.blockers or "template_row_sha256 missing blocked" not in report.blockers[0]:
        failures.append(f"expected template hash blocker, got {report.blockers}")

    if not aline_report.row_catalog.row_catalog_available:
        failures.append(
            "expected selected A-line row catalog to be available, got "
            f"{aline_report.row_catalog.to_dict()}"
        )
    if aline_report.row_catalog.row_count != 53376:
        failures.append(
            "expected selected A-line row catalog to carry 53376 rows, got "
            f"{aline_report.row_catalog.row_count}"
        )
    if aline_span_summary["binding_status"] != "span_candidate_report_only":
        failures.append(
            "A-line span candidate report must stay report-only, got "
            f"{aline_span_summary['binding_status']}"
        )
    if aline_span_summary["bytes_emitted"] is not False:
        failures.append("A-line span candidate report must not emit bytes")
    if aline_span_summary["instruction_row_count"] != 896:
        failures.append(
            "expected 896 A-line span candidate rows, got "
            f"{aline_span_summary['instruction_row_count']}"
        )
    if aline_span_summary["catalog_available_row_count"] != 896:
        failures.append(
            "expected every B-line row to find A-line catalog candidates, got "
            f"{aline_span_summary['catalog_available_row_count']}"
        )
    if aline_span_summary["catalog_missing_row_count"] != 0:
        failures.append(
            "expected no missing A-line catalog candidates, got "
            f"{aline_span_summary['catalog_missing_row_count']}"
        )
    if aline_span_summary["catalog_unavailable_row_count"] != 0:
        failures.append(
            "expected available A-line catalog for every row, got "
            f"{aline_span_summary['catalog_unavailable_row_count']}"
        )
    if aline_span_summary["exact_single_row_count"] != 0:
        failures.append(
            "A-line catalog candidates must not be promoted to exact single rows, got "
            f"{aline_span_summary['exact_single_row_count']}"
        )
    if aline_span_summary["row_span_required_count"] != 896:
        failures.append(
            "expected every row to remain row-span required, got "
            f"{aline_span_summary['row_span_required_count']}"
        )
    if aline_span_summary["role_counts"] != EXPECTED_EVIDENCE_ROLE_COUNTS:
        failures.append(
            "unexpected A-line span role counts: "
            f"{aline_span_summary['role_counts']}"
        )
    if seed_summary["seed_status"] != "blocked":
        failures.append(
            "A-line span candidate report must not unblock exact seed, got "
            f"{seed_summary['seed_status']}"
        )

    first_row = report.rows[0]
    if first_row.template_row_sha256 is not None:
        failures.append(f"first row unexpectedly has template hash: {first_row}")
    if first_row.writer_status != "blocked":
        failures.append(f"first row should be blocked: {first_row}")
    if first_row.blockers != ("template_row_sha256 missing",):
        failures.append(f"unexpected first row blockers: {first_row.blockers}")
    first_evidence = evidence_report.records[0]
    if first_evidence.candidate_evidence_sha256 is None:
        failures.append(f"first row is missing candidate evidence hash: {first_evidence}")
    if first_evidence.candidate_raw_row_count != 82:
        failures.append(
            "expected accumulator_prepare candidate evidence to see 82 legacy rows, got "
            f"{first_evidence.candidate_raw_row_count}"
        )
    if first_evidence.missing_raw_template_bytes_reason is None:
        failures.append("candidate evidence must keep exact raw row blocker visible")
    first_seed = seed_report.bindings[0]
    if first_seed.source_plan_id != f"BinaryLayoutPlan:{pipeline.binary_layout.profile_id}":
        failures.append(f"unexpected seed source plan id: {first_seed}")
    if first_seed.logical_row_id != first_row.row_id:
        failures.append(f"seed logical row id should track instruction row id: {first_seed}")
    if first_seed.legacy_csv_path is not None:
        failures.append(f"final exact seed must not invent legacy csv path: {first_seed}")
    if first_seed.template_index is not None or first_seed.local_order is not None:
        failures.append(f"final exact seed must not invent template index/local order: {first_seed}")
    if first_seed.row_span is not None:
        failures.append(f"exact seed must not invent row span: {first_seed}")
    if first_seed.candidate_raw_row_count != 82:
        failures.append(f"expected first seed to carry 82 candidates: {first_seed}")
    if len(first_seed.candidate_legacy_csv_paths) != 1:
        failures.append(f"first seed should carry one candidate csv path: {first_seed}")
    if first_seed.candidate_template_indexes != (0,):
        failures.append(f"first seed should carry candidate template index 0: {first_seed}")
    if first_seed.candidate_template_row_sha256 is not None:
        failures.append(f"multi-candidate seed must not claim row sha: {first_seed}")
    if first_seed.candidate_evidence_sha256 != first_evidence.candidate_evidence_sha256:
        failures.append("exact seed should carry candidate evidence hash for traceability")
    if first_seed.required_raw_template_bytes_status != "partial_multi_candidate_pending_local_order":
        failures.append(f"unexpected exact seed status: {first_seed}")
    if first_seed.s1_representation_selection_status != "closed":
        failures.append(f"S1 representation selection should be closed: {first_seed}")
    if first_seed.subtask_instance_semantics_status != "closed":
        failures.append(f"S1 subtask semantics should be closed: {first_seed}")

    failed_report = build_raw_template_overlay_report(
        pipeline.binary_layout,
        patched_fields_by_template_op_id={
            first_row.template_op_id: ("opcode",),
        },
    )
    failed_summary = summarize_raw_template_overlay_report(failed_report)
    if failed_summary["writer_status"] != "failed":
        failures.append(
            "touching opcode without inst_t field-offset evidence must fail, got "
            f"{failed_summary['writer_status']}"
        )
    if failed_summary["unknown_fields_touched_count"] != 1:
        failures.append(
            "expected opcode to be reported as an unknown touched field, got "
            f"{failed_report.unknown_fields_touched}"
        )

    if failures:
        print("stream compiler inst writer check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler inst writer check OK")
    print(f"writer_status={summary['writer_status']}")
    print(
        "matched_template_evidence="
        f"{evidence_summary['matched_template_evidence_count']}"
    )
    print(f"exact_binding_seed_status={seed_summary['seed_status']}")
    print(f"exact_bound_rows={seed_summary['exact_bound_row_count']}")
    print(f"partial_candidate_rows={seed_summary['partial_candidate_row_count']}")
    print(f"single_candidate_rows={seed_summary['single_candidate_row_count']}")
    print(f"instruction_rows={summary['instruction_row_count']}")
    print(f"template_row_sha256_missing={summary['template_row_sha256_missing_count']}")
    print(
        "missing_raw_template_bytes="
        f"{evidence_summary['missing_raw_template_bytes_count']}"
    )
    print(f"missing_seed_fields={seed_summary['missing_seed_field_counts']}")
    print(
        "authority_aware_missing_seed_fields="
        f"{authority_seed_summary['missing_seed_field_counts']}"
    )
    print(
        "task_resource_replay_authority="
        f"{authority_seed_summary['task_resource_replay_authority_status_counts']}"
    )
    print(
        "compressed_span_authority="
        f"{compressed_span_authority_summary['span_authority_status_counts']}"
    )
    print(
        "compressed_span_role_status_counts="
        f"{compressed_span_authority_summary['role_status_counts']}"
    )
    print(
        "compressed_span_policy_needed="
        f"{compressed_span_authority_summary['span_policy_needed_count']}"
    )
    print(
        "compressed_span_closed_policy_rows="
        f"{compressed_span_authority_summary['closed_policy_row_count']}"
    )
    print(
        "compressed_span_blocked_policy_rows="
        f"{compressed_span_authority_summary['blocked_policy_row_count']}"
    )
    print(
        "compressed_span_route_policy_closed="
        f"{compressed_span_authority_summary['route_policy_closed_count']}"
    )
    print(
        "compressed_span_route_policy_blocked="
        f"{compressed_span_authority_summary['route_policy_blocked_count']}"
    )
    print(
        "compressed_span_task_resource_partial="
        f"{compressed_span_authority_summary['task_resource_partial_count']}"
    )
    print(
        "opt_in_compressed_span_authority="
        f"{opt_in_compressed_span_authority_summary['span_authority_status_counts']}"
    )
    print(
        "opt_in_compressed_span_role_status_counts="
        f"{opt_in_compressed_span_authority_summary['role_status_counts']}"
    )
    print(
        "opt_in_compressed_span_policy_needed="
        f"{opt_in_compressed_span_authority_summary['span_policy_needed_count']}"
    )
    print(
        "opt_in_compressed_span_closed_policy_rows="
        f"{opt_in_compressed_span_authority_summary['closed_policy_row_count']}"
    )
    print(
        "opt_in_compressed_span_blocked_policy_rows="
        f"{opt_in_compressed_span_authority_summary['blocked_policy_row_count']}"
    )
    print(
        "opt_in_compressed_span_route_policy_closed="
        f"{opt_in_compressed_span_authority_summary['route_policy_closed_count']}"
    )
    print(
        "opt_in_compressed_span_route_policy_blocked="
        f"{opt_in_compressed_span_authority_summary['route_policy_blocked_count']}"
    )
    print(
        "exact_span_hash_candidates="
        f"{exact_span_hash_summary['span_hash_candidate_count']}"
    )
    print(
        "exact_span_hash_raw_overlay_consumable="
        f"{exact_span_hash_summary['raw_overlay_consumable_count']}"
    )
    print(
        "span_materialization_candidates="
        f"{span_materialization_summary['materialized_span_candidate_count']}"
    )
    print(
        "span_materialization_total_bytes="
        f"{span_materialization_summary['materialized_span_total_byte_count']}"
    )
    print(
        "span_materialization_raw_overlay_consumable="
        f"{span_materialization_summary['raw_overlay_consumable_count']}"
    )
    print(
        "raw_template_row_hash_ready="
        f"{raw_hash_readiness_summary['raw_template_row_hash_ready_count']}"
    )
    print(
        "raw_template_row_hash_blocked="
        f"{raw_hash_readiness_summary['blocked_row_count']}"
    )
    print(
        "candidate_raw_row_histogram="
        f"{evidence_summary['candidate_raw_row_count_histogram']}"
    )
    print(
        "exact_seed_candidate_statuses="
        f"{seed_summary['exact_seed_candidate_status_counts']}"
    )
    print(
        "s1_representation_selection="
        f"{seed_summary['s1_representation_selection_status_counts']}"
    )
    print(f"aline_row_catalog_rows={aline_report.row_catalog.row_count}")
    print(
        "aline_span_catalog_available_rows="
        f"{aline_span_summary['catalog_available_row_count']}"
    )
    print(
        "aline_span_row_span_required="
        f"{aline_span_summary['row_span_required_count']}"
    )


def _build_s1_semantics_report(pipeline):
    artifact = emit_debug_row_artifact(pipeline.binary_layout)
    groups = group_debug_rows_vendor_like(artifact)
    remap = remap_vendor_like_groups_locally(groups)
    component_plan = build_vendor_component_plan(
        remap,
        loop_fold_report=analyze_stream_loop_folding(pipeline.schedule),
    )
    offset_plan = build_field_offset_preflight_plan(component_plan)
    build_serializer_readiness_plan(component_plan, offset_plan)
    return build_subtask_instance_semantics_report(component_plan)


if __name__ == "__main__":
    main()
