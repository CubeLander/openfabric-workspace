#!/usr/bin/env python3
"""Check local A-line GEMM report-only evidence availability."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPILER_ROOT = REPO_ROOT / "compiler"
if str(COMPILER_ROOT) not in sys.path:
    sys.path.insert(0, str(COMPILER_ROOT))

from gpdpu_compiler.core.stream_compiler.aline_gemm_evidence import (  # noqa: E402
    build_aline_gemm_evidence_report,
    summarize_aline_gemm_evidence_report,
)

_EXPECTED_OBSERVED_OPS = frozenset(("HSTT", "STD", "HMMAL", "COPY", "LDN"))


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--case-path",
        action="append",
        type=Path,
        help="candidate GEMM case path; may be repeated",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="print the full report JSON after the compact summary",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    report = build_aline_gemm_evidence_report(
        repo_root=REPO_ROOT,
        case_paths=args.case_path,
    )
    summary = summarize_aline_gemm_evidence_report(report)

    print(f"full_size_result_available={summary['full_size_result_available']}")
    print(f"csv_template_count={summary['csv_template_count']}")
    print(f"task_count={summary['task_count']}")
    print(f"row_catalog_available={summary['row_catalog_available']}")
    print(f"row_count={summary['row_count']}")
    print(f"global_op_stage_counts={summary['global_op_stage_counts']}")
    print(f"global_inst_stage_counts={summary['global_inst_stage_counts']}")
    print(f"blockers={summary['blockers']}")

    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))

    blockers = list(summary["blockers"])
    observed_ops = {
        str(item["name"]) for item in summary["global_op_stage_counts"]
    } | {
        str(item["name"]) for item in summary["global_inst_stage_counts"]
    }
    missing_ops = sorted(_EXPECTED_OBSERVED_OPS - observed_ops)
    if not summary["full_size_result_available"]:
        blockers.append("full_size_result_available is not True")
    if not summary["row_catalog_available"]:
        blockers.append("selected root row catalog is not available")
    if summary["row_count"] <= 0:
        blockers.append("selected root row catalog row_count is not > 0")
    if missing_ops:
        blockers.append(f"missing expected observed ops: {missing_ops}")

    if blockers:
        print(f"assertion_blockers={blockers}")
        raise SystemExit(1)


if __name__ == "__main__":
    main()
