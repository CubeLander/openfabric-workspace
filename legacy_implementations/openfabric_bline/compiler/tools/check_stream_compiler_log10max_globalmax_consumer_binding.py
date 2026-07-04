#!/usr/bin/env python3
"""Focused check for log10max GlobalMax postprocess consumer binding."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gpdpu_compiler.core.stream_compiler.log10max_globalmax_consumer_binding import (  # noqa: E402
    build_log10max_globalmax_consumer_binding_report,
    summarize_log10max_globalmax_consumer_binding_report,
)


def main() -> None:
    report = build_log10max_globalmax_consumer_binding_report()
    summary = summarize_log10max_globalmax_consumer_binding_report(report)
    plan = report.to_plan()
    failures: list[str] = []

    if summary["runtime_ready"] is not True:
        failures.append(f"consumer binding should be runtime-ready: {summary}")
    if summary["record_count"] != 16:
        failures.append(f"expected one consumer binding per 4x4 PE: {summary}")
    if summary["consumer_fiber_op_kinds"] != ["max_with_floor_tile"]:
        failures.append(f"unexpected consumer kinds: {summary}")
    if summary["blockers"] != []:
        failures.append(f"consumer binding blockers should be closed: {summary}")
    if plan["layering_policy"].find("does not create communication IR") < 0:
        failures.append("layering policy must forbid new communication IR")

    for record in plan["records"]:
        if record["destination_operand"] != "GlobalMax":
            failures.append(f"consumer must bind GlobalMax operand: {record}")
        if record["depends_on_global_max_ready"] is not True:
            failures.append(f"consumer must depend on ready token: {record}")
        if record["symbolic_global_max_reaches_postprocess"] is not False:
            failures.append(f"postprocess must not see symbolic GlobalMax: {record}")
        if not str(record["ready_token"]).startswith("global_max_ready[task=0,pe="):
            failures.append(f"unexpected ready token: {record}")

    if "--json" in sys.argv:
        print(json.dumps(plan, indent=2, sort_keys=True))

    if failures:
        print("stream compiler log10max GlobalMax consumer binding check FAILED")
        for failure in failures:
            print(f"  - {failure}")
        raise SystemExit(1)

    print("stream compiler log10max GlobalMax consumer binding check OK")
    print(f"record_count={summary['record_count']}")


if __name__ == "__main__":
    main()
