"""Report-only folded component experiment for B-line.

This module intentionally does not mutate :mod:`vendor_components` output.

The current authoritative component view remains expanded:

    one k-stream exeBlock row per stream per loop instance

This experiment projects the already-proven stream/subtask loop overlay into a
separate comparison artifact:

    one canonical k-stream exeBlock row per stream
    repeated by subtask instances_amount

No bytes are emitted, no expanded rows are deleted, and no row is marked
binary-encoded.
"""

from __future__ import annotations

from dataclasses import dataclass

from .vendor_components import VendorComponentPlan, summarize_vendor_component_plan

TARGET_FOLD_PROJECTION_PROOF_SCHEMA_VERSION = "target_fold_projection_proof.v1"


@dataclass(frozen=True)
class FoldedTaskComponentCandidate:
    """One task-level folded k-stream comparison record."""

    task_id: int
    subtask_slot: str
    instances_amount: int
    stream_candidate_count: int
    expanded_k_stream_exeblock_count: int
    folded_k_stream_exeblock_count: int
    expanded_k_stream_instruction_count: int
    folded_k_stream_instruction_count: int
    expanded_total_exeblock_count: int
    folded_total_exeblock_count: int
    expanded_total_instruction_count: int
    folded_total_instruction_count: int
    instance_base_mapping_status: str
    stream_body_shape_counts: dict[str, int]
    stream_fold_body_signature_counts: dict[str, int]
    target_projection_status: str
    target_projection_policy: str
    binary_encoded: bool
    policy: str

    def to_plan(self) -> dict[str, object]:
        return {
            "task_id": self.task_id,
            "subtask_slot": self.subtask_slot,
            "instances_amount": self.instances_amount,
            "stream_candidate_count": self.stream_candidate_count,
            "expanded_k_stream_exeblock_count": self.expanded_k_stream_exeblock_count,
            "folded_k_stream_exeblock_count": self.folded_k_stream_exeblock_count,
            "expanded_k_stream_instruction_count": self.expanded_k_stream_instruction_count,
            "folded_k_stream_instruction_count": self.folded_k_stream_instruction_count,
            "expanded_total_exeblock_count": self.expanded_total_exeblock_count,
            "folded_total_exeblock_count": self.folded_total_exeblock_count,
            "expanded_total_instruction_count": self.expanded_total_instruction_count,
            "folded_total_instruction_count": self.folded_total_instruction_count,
            "instance_base_mapping_status": self.instance_base_mapping_status,
            "stream_body_shape_counts": dict(sorted(self.stream_body_shape_counts.items())),
            "stream_fold_body_signature_counts": dict(
                sorted(self.stream_fold_body_signature_counts.items())
            ),
            "target_projection_status": self.target_projection_status,
            "target_projection_policy": self.target_projection_policy,
            "binary_encoded": self.binary_encoded,
            "policy": self.policy,
        }


@dataclass(frozen=True)
class FoldedVendorComponentExperiment:
    """Separate folded component comparison artifact."""

    profile_id: str
    runnability_state: str
    expanded_inst_row_count: int
    folded_inst_row_count: int
    expanded_exeblock_row_count: int
    folded_exeblock_row_count: int
    task_candidates: tuple[FoldedTaskComponentCandidate, ...]
    diagnostics: tuple[str, ...] = ()

    def to_plan(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "artifact": "b_line_folded_vendor_component_experiment",
            "profile_id": self.profile_id,
            "runnability_state": self.runnability_state,
            "expanded_inst_row_count": self.expanded_inst_row_count,
            "folded_inst_row_count": self.folded_inst_row_count,
            "expanded_exeblock_row_count": self.expanded_exeblock_row_count,
            "folded_exeblock_row_count": self.folded_exeblock_row_count,
            "task_candidates": [
                candidate.to_plan() for candidate in self.task_candidates
            ],
            "diagnostics": list(self.diagnostics),
            "layering_policy": (
                "folded_vendor_component_experiment_consumes_vendor_component_plan;"
                "does_not_mutate_expanded_rows_or_emit_binary_bytes"
            ),
        }


def build_folded_vendor_component_experiment(
    component_plan: VendorComponentPlan,
) -> FoldedVendorComponentExperiment:
    """Build a folded comparison artifact from a component plan."""

    summary = summarize_vendor_component_plan(component_plan)
    diagnostics: list[str] = []
    task_candidates: list[FoldedTaskComponentCandidate] = []

    for row in component_plan.subtask_rows:
        subtask_slot = str(row.get("subtask_slot"))
        if subtask_slot != "subtask1_k_stream":
            continue
        overlay = row.get("folded_subtask_conf_candidate")
        if not isinstance(overlay, dict):
            diagnostics.append(
                f"missing folded overlay for task {row.get('task_id')} {subtask_slot}"
            )
            continue
        candidate = _candidate_for_k_stream_subtask(component_plan, row, overlay)
        task_candidates.append(candidate)

    expanded_inst_row_count = int(summary["inst_row_count"])
    expanded_exeblock_row_count = int(summary["exeblock_row_count"])
    folded_inst_row_count = expanded_inst_row_count - sum(
        candidate.expanded_k_stream_instruction_count
        - candidate.folded_k_stream_instruction_count
        for candidate in task_candidates
    )
    folded_exeblock_row_count = expanded_exeblock_row_count - sum(
        candidate.expanded_k_stream_exeblock_count
        - candidate.folded_k_stream_exeblock_count
        for candidate in task_candidates
    )

    if not task_candidates:
        diagnostics.append("no folded k-stream candidates found")
    if any(candidate.binary_encoded for candidate in task_candidates):
        diagnostics.append("folded candidates must not claim binary encoding")

    return FoldedVendorComponentExperiment(
        profile_id=component_plan.profile_id,
        runnability_state="layout_candidate",
        expanded_inst_row_count=expanded_inst_row_count,
        folded_inst_row_count=folded_inst_row_count,
        expanded_exeblock_row_count=expanded_exeblock_row_count,
        folded_exeblock_row_count=folded_exeblock_row_count,
        task_candidates=tuple(sorted(task_candidates, key=lambda candidate: candidate.task_id)),
        diagnostics=tuple(diagnostics),
    )


def summarize_folded_vendor_component_experiment(
    experiment: FoldedVendorComponentExperiment,
) -> dict[str, object]:
    """Return stable comparison counts for focused checks."""

    return {
        "profile_id": experiment.profile_id,
        "runnability_state": experiment.runnability_state,
        "expanded_inst_row_count": experiment.expanded_inst_row_count,
        "folded_inst_row_count": experiment.folded_inst_row_count,
        "inst_row_reduction_count": (
            experiment.expanded_inst_row_count - experiment.folded_inst_row_count
        ),
        "expanded_exeblock_row_count": experiment.expanded_exeblock_row_count,
        "folded_exeblock_row_count": experiment.folded_exeblock_row_count,
        "exeblock_row_reduction_count": (
            experiment.expanded_exeblock_row_count
            - experiment.folded_exeblock_row_count
        ),
        "task_candidate_count": len(experiment.task_candidates),
        "task_candidate_binary_encoded_count": sum(
            1 for candidate in experiment.task_candidates if candidate.binary_encoded
        ),
        "task_candidate_instances_amount_total": sum(
            candidate.instances_amount for candidate in experiment.task_candidates
        ),
        "task_candidate_stream_total": sum(
            candidate.stream_candidate_count for candidate in experiment.task_candidates
        ),
        "task_candidate_shape_total": sum(
            len(candidate.stream_body_shape_counts)
            for candidate in experiment.task_candidates
        ),
        "task_candidate_signature_total": sum(
            len(candidate.stream_fold_body_signature_counts)
            for candidate in experiment.task_candidates
        ),
        "task_candidate_target_projection_report_only_count": sum(
            1
            for candidate in experiment.task_candidates
            if candidate.target_projection_status == "report_only_eligible"
            and "does_not_define_foldability_or_emit_binary_bytes"
            in candidate.target_projection_policy
        ),
        "diagnostic_count": len(experiment.diagnostics),
    }


def _candidate_for_k_stream_subtask(
    component_plan: VendorComponentPlan,
    subtask_row: dict[str, object],
    overlay: dict[str, object],
) -> FoldedTaskComponentCandidate:
    task_id = _int_field(subtask_row, "task_id")
    subtask_slot = str(subtask_row.get("subtask_slot"))
    instances_amount = int(overlay.get("instances_amount", 0))
    stream_candidate_count = int(overlay.get("stream_candidate_count", 0))
    expanded_k_exeblocks = [
        row
        for row in component_plan.exeblock_rows
        if row.get("task_id") == task_id
        and row.get("subtask_slot") == subtask_slot
    ]
    canonical_loop_key = _first_loop_key(overlay)
    folded_k_exeblocks = [
        row
        for row in expanded_k_exeblocks
        if row.get("loop_instance") == canonical_loop_key
    ]
    expanded_k_instruction_count = sum(
        int(row.get("instruction_count", 0)) for row in expanded_k_exeblocks
    )
    folded_k_instruction_count = sum(
        int(row.get("instruction_count", 0)) for row in folded_k_exeblocks
    )
    expanded_task_exeblock_count = sum(
        1 for row in component_plan.exeblock_rows if row.get("task_id") == task_id
    )
    expanded_task_instruction_count = sum(
        1 for row in component_plan.inst_rows if row.get("task_id") == task_id
    )
    target_projection_proof = _target_projection_proof(overlay)
    return FoldedTaskComponentCandidate(
        task_id=task_id,
        subtask_slot=subtask_slot,
        instances_amount=instances_amount,
        stream_candidate_count=stream_candidate_count,
        expanded_k_stream_exeblock_count=len(expanded_k_exeblocks),
        folded_k_stream_exeblock_count=len(folded_k_exeblocks),
        expanded_k_stream_instruction_count=expanded_k_instruction_count,
        folded_k_stream_instruction_count=folded_k_instruction_count,
        expanded_total_exeblock_count=expanded_task_exeblock_count,
        folded_total_exeblock_count=(
            expanded_task_exeblock_count
            - len(expanded_k_exeblocks)
            + len(folded_k_exeblocks)
        ),
        expanded_total_instruction_count=expanded_task_instruction_count,
        folded_total_instruction_count=(
            expanded_task_instruction_count
            - expanded_k_instruction_count
            + folded_k_instruction_count
        ),
        instance_base_mapping_status=str(overlay.get("instance_base_mapping_status")),
        stream_body_shape_counts=_dict_str_int(overlay.get("stream_body_shape_counts")),
        stream_fold_body_signature_counts=_dict_str_int(
            overlay.get("stream_fold_body_signature_counts")
        ),
        target_projection_status=str(
            target_projection_proof.get("projection_status", "missing")
        ),
        target_projection_policy=str(target_projection_proof.get("policy", "missing")),
        binary_encoded=False,
        policy=(
            "report_only_folded_component_experiment;"
            "canonical_loop_body_selected_from_first_loop_instance;"
            "expanded_vendor_component_plan_remains_authoritative"
        ),
    )


def _first_loop_key(overlay: dict[str, object]) -> object:
    values = overlay.get("loop_instance_keys")
    if isinstance(values, list) and values:
        return values[0]
    return None


def _target_projection_proof(overlay: dict[str, object]) -> dict[str, object]:
    proof = overlay.get("target_fold_projection_proof")
    if not isinstance(proof, dict):
        return {
            "projection_status": "invalid_projection_proof_schema",
            "policy": "missing_target_fold_projection_proof",
        }
    if proof.get("schema_version") != TARGET_FOLD_PROJECTION_PROOF_SCHEMA_VERSION:
        return {
            "projection_status": "invalid_projection_proof_schema",
            "policy": "unsupported_target_fold_projection_proof_schema",
        }
    return proof


def _int_field(row: dict[str, object], key: str) -> int:
    value = row.get(key)
    if not isinstance(value, int):
        raise ValueError(f"expected integer field {key}: {row}")
    return value


def _dict_str_int(value: object) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {
        str(key): int(item)
        for key, item in value.items()
        if isinstance(item, int)
    }


__all__ = [
    "FoldedTaskComponentCandidate",
    "FoldedVendorComponentExperiment",
    "build_folded_vendor_component_experiment",
    "summarize_folded_vendor_component_experiment",
]
