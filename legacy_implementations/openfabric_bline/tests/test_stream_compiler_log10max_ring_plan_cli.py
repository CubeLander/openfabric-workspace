from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_log10max_ring_plan_cli_is_wired_and_fail_closed() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(ROOT / "compiler/tools/check_stream_compiler_log10max_ring_plan.py"),
            "--json",
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    stdout = completed.stdout
    marker = "\nstream compiler log10max ring plan check OK\n"
    assert stdout.endswith(marker)

    plan = json.loads(stdout[: -len(marker)])
    summary = plan["summary"]

    assert plan["artifact_kind"] == "log10max_task_local_ring_plan"
    assert plan["implementation_scope"] == (
        "ring_first_delivery_path_not_generic_collective_framework"
    )
    assert summary["strategy"] == "ring_spmd_row_then_col"
    assert summary["edge_count"] == 30
    assert summary["task_axis"] == 1
    assert summary["one_app_cross_task_ring"] == "forbidden"
    assert summary["runtime_ready"] is False
    assert "route_role_globalmax_unproven" in summary["runtime_ready_blockers"]


def test_log10max_ring_update_template_rows_cli_is_report_only_candidate() -> None:
    completed = subprocess.run(
        [
            sys.executable,
            str(
                ROOT
                / "compiler/tools/check_stream_compiler_log10max_ring_update_template_rows.py"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    stdout = completed.stdout

    assert "stream compiler log10max ring update template rows check OK" in stdout
    assert "row_candidate_count=30" in stdout
    assert "blocker_ids=['log10max_ring_update_row_bytes_missing']" in stdout
