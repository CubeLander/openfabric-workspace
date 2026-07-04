#!/usr/bin/env python3
"""Focused validation for the S6 log10max local template pack."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from gpdpu_compiler.core.stream_compiler.log10max_template_pack import (
    S5_UNRESOLVED_GLOBAL_SCALAR_INPUT,
    ScalarVisibilitySource,
    build_log10max_status_report,
)


EXPECTED_OP_SEQUENCE = [
    "clamp_min",
    "FLOG2*log10(2)",
    "local_reduce_max",
    "maximum",
    "add_scalar",
    "mul_scalar",
    "store",
]

EXPECTED_STATUS_COUNTS = {
    "external_symbolic": 1,
    "ready_local": 6,
}

EXPECTED_OPCODE_METADATA_STATUS_COUNTS = {
    "constant_value_from_payload_contract": 5,
    "known_active_opcode": 9,
    "pseudo_assembler_only": 1,
}

EXPECTED_TEMPLATE_BINDING_STATUS_COUNTS = {
    "blocked_waiting_for_S5_scalar_visibility": 1,
    "candidate_reduce_skeleton": 2,
    "constant_operand_policy_unbound": 4,
    "local_template_shape_ready": 5,
    "memory_template_base_slot_unbound": 1,
    "must_expand_before_binary_accounting": 1,
    "scalar_visibility_external_until_S5": 1,
}

EXPECTED_BOUND_STATUS_COUNTS = {
    "ready_local": 7,
}

EXPECTED_BOUND_TEMPLATE_BINDING_STATUS_COUNTS = {
    "candidate_reduce_skeleton": 2,
    "constant_operand_policy_unbound": 4,
    "local_template_shape_ready": 5,
    "memory_template_base_slot_unbound": 1,
    "must_expand_before_binary_accounting": 1,
    "pe00_scalar_threshold_contract_complete": 1,
    "pe00_scalar_visibility_contract_complete": 1,
}


def main() -> None:
    args = _parse_args()
    status_report = build_log10max_status_report(
        global_scalar_input=args.global_scalar_input,
    )
    summary = status_report["summary"]
    artifact = status_report["artifact"]
    failures: list[str] = []

    if summary["local_template_step_count"] != 7:
        failures.append(
            "expected 7 local template steps, got "
            f"{summary['local_template_step_count']}"
        )
    if summary["op_sequence"] != EXPECTED_OP_SEQUENCE:
        failures.append(f"unexpected op sequence: {summary['op_sequence']}")
    if summary["status_counts"] != EXPECTED_STATUS_COUNTS:
        failures.append(f"unexpected status counts: {summary['status_counts']}")
    if (
        summary["opcode_metadata_status_counts"]
        != EXPECTED_OPCODE_METADATA_STATUS_COUNTS
    ):
        failures.append(
            "unexpected opcode metadata evidence counts: "
            f"{summary['opcode_metadata_status_counts']}"
        )
    if (
        summary["template_binding_status_counts"]
        != EXPECTED_TEMPLATE_BINDING_STATUS_COUNTS
    ):
        failures.append(
            "unexpected template binding evidence counts: "
            f"{summary['template_binding_status_counts']}"
        )
    if summary["s6a_local_template_pack_status"] != "complete_report_only":
        failures.append(
            "S6a local template pack must be complete_report_only, got "
            f"{summary['s6a_local_template_pack_status']}"
        )
    if summary["global_scalar_input"] == S5_UNRESOLVED_GLOBAL_SCALAR_INPUT:
        if summary["uploadable"] is not False:
            failures.append("unresolved S5 scalar binding must not be uploadable")
        if summary["symbolic_unresolved_count_for_uploadable"] != 1:
            failures.append(
                "expected exactly one uploadability blocker for unresolved "
                "symbolic scalar, got "
                f"{summary['symbolic_unresolved_count_for_uploadable']}"
            )
    elif summary["uploadable"] is not True:
        failures.append("concrete scalar input should make this status uploadable")

    local_pack = artifact["local_template_pack"]
    if local_pack["uploadable"] != summary["uploadable"]:
        failures.append(
            "artifact local_template_pack uploadable disagrees with summary: "
            f"{local_pack['uploadable']} vs {summary['uploadable']}"
        )
    if "waiting_for_S5" not in artifact["pipeline_position"]["S6b_scalar_visibility_binding"]:
        failures.append("S6b status must explicitly wait for S5 selected strategy")
    if artifact["numerical_contract"]["dtype"] != "fp32":
        failures.append("numerical contract dtype must be fp32")
    if artifact["numerical_contract"]["constants"]["clamp_min"] != 1.0e-10:
        failures.append("numerical contract clamp_min must stay 1e-10")
    if artifact["numerical_contract"]["constants"]["threshold_offset"] != -8.0:
        failures.append("numerical contract threshold offset must stay -8.0")
    if artifact["numerical_contract"]["constants"]["output_bias"] != 4.0:
        failures.append("numerical contract output bias must stay 4.0")
    if artifact["numerical_contract"]["constants"]["output_scale"] != 0.25:
        failures.append("numerical contract output scale must stay 0.25")
    constant_fields = artifact["numerical_contract"]["constant_fields"]
    for key in (
        "clamp_min_1e_10",
        "log10_of_2",
        "threshold_offset_minus_8",
        "output_bias_plus_4",
        "output_scale_0_25",
    ):
        if key not in constant_fields:
            failures.append(f"numerical contract missing constant field {key}")

    evidence_by_step = {
        step["id"]: step["opcode_evidence"]
        for step in local_pack["steps"]
    }
    _expect_step_mnemonics(
        evidence_by_step,
        failures,
        "s6a.step1.flog2_times_log10_2",
        {"FLOG2", "FMUL"},
    )
    _expect_step_mnemonics(
        evidence_by_step,
        failures,
        "s6a.step2.local_reduce_max",
        {"SHFL", "FMAX"},
    )
    _expect_step_mnemonics(
        evidence_by_step,
        failures,
        "s6a.step3.maximum_with_symbolic_global_scalar",
        {"FMAX"},
    )
    _expect_step_mnemonics(
        evidence_by_step,
        failures,
        "s6a.step4.add_scalar",
        {"FADD"},
    )
    _expect_step_mnemonics(
        evidence_by_step,
        failures,
        "s6a.step5.mul_scalar",
        {"FMUL"},
    )
    _expect_step_mnemonics(
        evidence_by_step,
        failures,
        "s6a.step6.store",
        {"STD", "HSTT"},
    )
    _check_synthetic_complete_scalar_source(failures)

    if args.write_status is not None:
        args.write_status.parent.mkdir(parents=True, exist_ok=True)
        args.write_status.write_text(
            json.dumps(status_report, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    if failures:
        print("stream compiler log10max template pack check FAILED")
        print(
            "symbolic_unresolved_count_for_uploadable="
            f"{summary['symbolic_unresolved_count_for_uploadable']}"
        )
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler log10max template pack check OK")
    print(f"local_template_steps={summary['local_template_step_count']}")
    print(f"op_sequence={summary['op_sequence']}")
    print(f"uploadable={summary['uploadable']}")
    print(
        "symbolic_unresolved_count_for_uploadable="
        f"{summary['symbolic_unresolved_count_for_uploadable']}"
    )
    if args.write_status is not None:
        print(f"wrote_status={args.write_status}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Check the S6 log10max local template pack artifact.",
    )
    parser.add_argument(
        "--global-scalar-input",
        default=S5_UNRESOLVED_GLOBAL_SCALAR_INPUT,
        help=(
            "Scalar source token. The default keeps the artifact fail-closed "
            "until S5 selected strategy is available."
        ),
    )
    parser.add_argument(
        "--write-status",
        type=Path,
        default=None,
        help="Optional path for local_template_pack.status.json output.",
    )
    return parser.parse_args()


def _check_synthetic_complete_scalar_source(failures: list[str]) -> None:
    synthetic_source = ScalarVisibilitySource(
        strategy="pe00_scalar_visibility",
        source_name="s5.pe00.global_max_scalar",
        scratch_slot="pe00.spm.scalar_slot.global_max.fp32",
        consumer_load_contract={
            "load_kind": "pe00_scalar_load_or_broadcast",
            "consumer": "s6a.step3.maximum_with_symbolic_global_scalar",
            "dtype": "fp32",
            "visibility_kind": "replicated_scalar",
            "threshold_transform": {
                "op": "add_scalar",
                "constant": -8.0,
            },
        },
        ordering_evidence_status="complete",
    )
    status_report = build_log10max_status_report(scalar_source=synthetic_source)
    summary = status_report["summary"]
    binding = status_report["artifact"]["scalar_visibility_binding"]
    local_pack = status_report["artifact"]["local_template_pack"]

    if summary["scalar_visibility_strategy"] != "pe00_scalar_visibility":
        failures.append(
            "synthetic scalar source did not preserve PE00 strategy: "
            f"{summary['scalar_visibility_strategy']}"
        )
    if summary["scalar_visibility_source_complete"] is not True:
        failures.append("synthetic scalar source should be complete")
    if summary["uploadable"] is not True:
        failures.append("synthetic complete scalar source should close uploadability")
    if summary["symbolic_unresolved_count_for_uploadable"] != 0:
        failures.append(
            "synthetic complete scalar source should clear uploadable unresolved "
            f"count, got {summary['symbolic_unresolved_count_for_uploadable']}"
        )
    if summary["status_counts"] != EXPECTED_BOUND_STATUS_COUNTS:
        failures.append(
            "unexpected bound status counts: "
            f"{summary['status_counts']}"
        )
    if (
        summary["template_binding_status_counts"]
        != EXPECTED_BOUND_TEMPLATE_BINDING_STATUS_COUNTS
    ):
        failures.append(
            "unexpected bound template binding evidence counts: "
            f"{summary['template_binding_status_counts']}"
        )
    if binding["runtime_runnable_claim"] is not False:
        failures.append("synthetic scalar source must not claim runtime runnable")
    if binding["row_bytes_claim"] is not False:
        failures.append("synthetic scalar source must not claim row bytes")
    if local_pack["uploadable_blockers"] != []:
        failures.append(
            "synthetic complete scalar source should clear upload blockers: "
            f"{local_pack['uploadable_blockers']}"
        )


def _expect_step_mnemonics(
    evidence_by_step: dict[str, object],
    failures: list[str],
    step_id: str,
    expected_mnemonics: set[str],
) -> None:
    records = evidence_by_step.get(step_id)
    if not isinstance(records, list):
        failures.append(f"missing opcode evidence for {step_id}")
        return
    actual = {
        record["mnemonic"]
        for record in records
        if isinstance(record, dict) and record.get("kind") == "opcode"
    }
    if actual != expected_mnemonics:
        failures.append(
            f"unexpected opcode evidence for {step_id}: {sorted(actual)}"
        )


if __name__ == "__main__":
    main()
