#!/usr/bin/env python3
"""Check a DFU operator payload candidate before delivery/upload handoff."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPILER_ROOT = REPO_ROOT / "compiler"
if str(COMPILER_ROOT) not in sys.path:
    sys.path.insert(0, str(COMPILER_ROOT))

from gpdpu_compiler.validation.delivery_contracts import (  # noqa: E402
    validate_delivery_candidate,
)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate a DFU payload candidate with the S0 delivery gate."
    )
    parser.add_argument("payload_dir", type=Path)
    parser.add_argument("--operator", required=True)
    parser.add_argument(
        "--min-state",
        choices=("runtime_ready", "uploadable"),
        default="runtime_ready",
    )
    parser.add_argument("--report-path", type=Path, default=None)
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit the delivery report as JSON.",
    )
    args = parser.parse_args(argv)

    report = validate_delivery_candidate(
        args.payload_dir,
        args.operator,
        min_state=args.min_state,
        report_path=args.report_path,
    )

    if args.json:
        print(json.dumps(report.to_json(), indent=2, sort_keys=True))
    else:
        verdict = "PASS" if report.passed else "FAIL"
        print("dfu_delivery_candidate=%s" % verdict)
        print("operator=%s" % report.operator)
        print("requested_min_state=%s" % report.requested_min_state)
        print("final_state=%s" % report.final_state)
        print("validation_status=%s" % report.validation_status)
        print("report_path=%s" % report.report_path)
        print("runtime_ready_scope=%s" % report.runtime_ready_scope)
        for blocker in report.validation_blockers:
            print("blocker=%s" % blocker)
        for finding in report.placeholder_shell_findings:
            print("placeholder_shell_marker=%s:%s" % (finding.path, finding.marker))

    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
