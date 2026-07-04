#!/usr/bin/env python3
"""Export deterministic B-line stream compiler snapshots.

The snapshot is a feedback-loop artifact, not a runtime package.  It records
the current report-only lowering chain in stable JSON so reviews can diff
TemplateOp and BinaryLayout changes without opening binary serializers.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gpdpu_compiler.core.stream_compiler.binary_plan import (
    summarize_binary_layout_plan,
)
from gpdpu_compiler.core.stream_compiler.binding import summarize_role_binding_program
from gpdpu_compiler.core.stream_compiler.blocks import summarize_fiber_block_projections
from gpdpu_compiler.core.stream_compiler.dfu3500_semantics import (
    summarize_dfu3500_semantic_report,
)
from gpdpu_compiler.core.stream_compiler.executable import summarize_executable_program
from gpdpu_compiler.core.stream_compiler.schedule import (
    summarize_fiber_execution_schedule,
)
from gpdpu_compiler.core.stream_compiler.template_ops import summarize_template_op_plan
from gpdpu_compiler.core.stream_compiler.template_records import summarize_template_record_program
from stream_compiler_demo_pipeline import SnapshotProfile, build_demo_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=("gemm_relu", "gemm_no_relu"),
        default="gemm_relu",
        help="Demo profile to snapshot.",
    )
    parser.add_argument(
        "--out",
        type=Path,
        help="Write JSON snapshot to this file. Defaults to stdout.",
    )
    parser.add_argument(
        "--include-rows",
        action="store_true",
        help="Include full TemplateOp and BinaryLayout rows, not only summaries.",
    )
    return parser.parse_args()


def build_snapshot(
    profile: SnapshotProfile,
    *,
    include_rows: bool = False,
) -> dict[str, object]:
    artifacts = build_demo_pipeline(profile)
    snapshot: dict[str, object] = {
        "schema_version": 1,
        "artifact": "b_line_stream_compiler_snapshot",
        "profile": profile,
        "include_relu": artifacts.include_relu,
        "requested_runnability_state": artifacts.requested_runnability_state,
        "summaries": {
            "stream": {
                "stream_count": len(artifacts.stream_plan.streams),
                "action_count": sum(len(actions) for actions in artifacts.stream_plan.streams.values()),
                "dependency_edge_count": len(artifacts.stream_plan.dependency_edges()),
            },
            "fiber_projection": summarize_fiber_block_projections(artifacts.projections),
            "executable": summarize_executable_program(artifacts.executable),
            "role_binding": summarize_role_binding_program(artifacts.bindings),
            "template_records": summarize_template_record_program(artifacts.template_records),
            "dfu3500_semantics": summarize_dfu3500_semantic_report(artifacts.semantic_report),
            "schedule": summarize_fiber_execution_schedule(artifacts.schedule),
            "template_ops": summarize_template_op_plan(artifacts.template_plan),
            "binary_layout": summarize_binary_layout_plan(artifacts.binary_layout),
        },
    }
    if include_rows:
        snapshot["plans"] = {
            "schedule": artifacts.schedule.to_plan(),
            "template_ops": artifacts.template_plan.to_plan(),
            "binary_layout": artifacts.binary_layout.to_plan(),
        }
    return json.loads(json.dumps(snapshot, sort_keys=True))


def main() -> None:
    args = parse_args()
    snapshot = build_snapshot(args.profile, include_rows=args.include_rows)
    content = json.dumps(snapshot, indent=2, sort_keys=True) + "\n"
    if args.out is None:
        sys.stdout.write(content)
    else:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(content, encoding="utf-8")
        print(args.out)


if __name__ == "__main__":
    main()
