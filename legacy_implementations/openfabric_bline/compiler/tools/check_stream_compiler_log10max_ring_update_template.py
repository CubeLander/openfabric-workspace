#!/usr/bin/env python3
"""Check log10max ring receiver-side update template contract."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gpdpu_compiler.core.stream_compiler.log10max_ring_update_template import (
    build_log10max_ring_update_template_report,
    summarize_log10max_ring_update_template_report,
)


def main() -> None:
    report = build_log10max_ring_update_template_report()
    summary = summarize_log10max_ring_update_template_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["record_count"] != 30:
        failures.append(f"expected one update template candidate per edge: {summary}")
    if summary["opcode_counts"] != {"FMAX": 30}:
        failures.append(f"fp32 ring updates should use FMAX: {summary}")
    if summary["status_counts"] != {"candidate_available_row_bytes_missing": 30}:
        failures.append(f"unexpected update template statuses: {summary}")
    if summary["blocker_ids"] != ["log10max_ring_update_row_bytes_missing"]:
        failures.append(f"update template blocker must be row-byte precise: {summary}")
    if summary["template_ready_for_runtime_ready"] is not False:
        failures.append("update template report must not claim runtime_ready")
    if summary["row_bytes_claim"] is not False:
        failures.append("update template report must not claim row bytes")

    for record in plan["records"]:
        if record["destination"] != "receiver_owned_global_max_scalar_operand":
            failures.append(f"unexpected update destination: {record}")
        if record["template_proven_for_runtime_ready"] is not False:
            failures.append(f"template proof must stay fail-closed: {record}")
        if "dfu3500_isa.py:FMAX" not in " ".join(record["opcode_evidence_refs"]):
            failures.append(f"FMAX evidence refs missing: {record}")

    if failures:
        print("stream compiler log10max ring update template check FAILED")
        for failure in failures:
            print(f"- {failure}")
        raise SystemExit(1)

    print("stream compiler log10max ring update template check OK")
    print(f"record_count={summary['record_count']}")
    print(f"blocker_ids={summary['blocker_ids']}")


if __name__ == "__main__":
    main()
