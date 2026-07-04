#!/usr/bin/env python3
"""Export a report-only vendor-shaped case package from B-line artifacts."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from gpdpu_compiler.core.stream_compiler.vendor_assembler_bundle import (
    build_vendor_assembler_input_bundle,
    summarize_vendor_assembler_input_bundle,
    write_vendor_assembler_input_bundle,
)
from stream_compiler_demo_pipeline import SnapshotProfile, build_demo_pipeline


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--profile",
        choices=("gemm_no_relu", "gemm_relu"),
        default="gemm_no_relu",
        help="Demo profile to export.",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="Directory where the case package will be written.",
    )
    parser.add_argument(
        "--summary-only",
        action="store_true",
        help="Print summary JSON without writing files.",
    )
    return parser.parse_args()


def build_case_package_summary(profile: SnapshotProfile) -> dict[str, object]:
    artifacts = build_demo_pipeline(profile)
    bundle = build_vendor_assembler_input_bundle(artifacts.binary_layout)
    return json.loads(
        json.dumps(summarize_vendor_assembler_input_bundle(bundle), sort_keys=True)
    )


def main() -> None:
    args = parse_args()
    artifacts = build_demo_pipeline(args.profile)
    bundle = build_vendor_assembler_input_bundle(artifacts.binary_layout)
    if args.summary_only:
        summary = summarize_vendor_assembler_input_bundle(bundle)
    else:
        summary = write_vendor_assembler_input_bundle(bundle, args.out_dir)
    sys.stdout.write(json.dumps(summary, indent=2, sort_keys=True) + "\n")


if __name__ == "__main__":
    main()
