#!/usr/bin/env python3
"""Inspect legacy GEMM CSV templates for B-line evidence gathering.

This is a read-only research helper.  It reports operation/stage structure in
vendor CSV templates so we can decide whether B-line roles such as
`accumulator_finalize` and `tile_op:relu` have explicit DFU3500 evidence or
should remain symbolic.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from pathlib import Path

from gpdpu_compiler.core.dfu3500.legacy_templates import _stage_for_legacy_inst
from gpdpu_compiler.core.program_legacy_inst import (
    LegacyInst,
    _legacy_gemm_template_root,
    parse_legacy_csv_template,
)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--root",
        type=Path,
        default=_legacy_gemm_template_root(),
        help="legacy gemm_template_fusion application root",
    )
    parser.add_argument(
        "--task",
        type=int,
        action="append",
        help="task index to include; may be repeated; default scans all",
    )
    parser.add_argument(
        "--subtask",
        type=int,
        action="append",
        help="subtask index to include; may be repeated; default scans all",
    )
    parser.add_argument(
        "--detail",
        action="store_true",
        help="print every template row instead of only aggregate summaries",
    )
    return parser.parse_args()


def main() -> None:
    args = _parse_args()
    root = args.root
    if not root.exists():
        raise SystemExit(f"legacy GEMM template root does not exist: {root}")
    task_filter = set(args.task or [])
    subtask_filter = set(args.subtask or [])
    template_paths = _find_template_paths(root, task_filter=task_filter, subtask_filter=subtask_filter)
    if not template_paths:
        raise SystemExit("no templates matched filters")

    reports = [_inspect_template(path) for path in template_paths]
    _print_summary(root=root, reports=reports)
    if args.detail:
        _print_detail(reports)


def _find_template_paths(
    root: Path,
    *,
    task_filter: set[int],
    subtask_filter: set[int],
) -> list[Path]:
    paths: list[Path] = []
    for path in root.glob("task*/subtask*/template/*.csv"):
        task_index, subtask_index, _ = _parse_template_path(path)
        if task_filter and task_index not in task_filter:
            continue
        if subtask_filter and subtask_index not in subtask_filter:
            continue
        paths.append(path)
    return sorted(paths, key=lambda path: _parse_template_path(path))


def _inspect_template(path: Path) -> dict[str, object]:
    task_index, subtask_index, template_index = _parse_template_path(path)
    try:
        insts = parse_legacy_csv_template(path)
        error = None
    except Exception as exc:  # pragma: no cover - diagnostic path
        insts = ()
        error = str(exc)
    op_counts = Counter(inst.op_name for inst in insts)
    stage_counts = Counter(_stage_for_legacy_inst(inst) for inst in insts)
    cal_counts = Counter(inst.op_name for inst in insts if _stage_for_legacy_inst(inst) == "CAL")
    st_counts = Counter(inst.op_name for inst in insts if _stage_for_legacy_inst(inst) == "ST")
    flow_counts = Counter(inst.op_name for inst in insts if _stage_for_legacy_inst(inst) == "FLOW")
    return {
        "path": path,
        "task": task_index,
        "subtask": subtask_index,
        "template": template_index,
        "inst_count": len(insts),
        "op_counts": op_counts,
        "stage_counts": stage_counts,
        "cal_counts": cal_counts,
        "st_counts": st_counts,
        "flow_counts": flow_counts,
        "evidence_flags": _evidence_flags(insts),
        "error": error,
    }


def _parse_template_path(path: Path) -> tuple[int, int, int]:
    task_part = next(part for part in path.parts if part.startswith("task"))
    subtask_part = next(part for part in path.parts if part.startswith("subtask"))
    return (
        int(task_part.removeprefix("task")),
        int(subtask_part.removeprefix("subtask")),
        int(path.stem),
    )


def _evidence_flags(insts: tuple[LegacyInst, ...]) -> tuple[str, ...]:
    op_names = {inst.op_name for inst in insts}
    flags: list[str] = []
    if op_names & {"HST", "HSTT", "ST", "STT", "STD"}:
        flags.append("has_store")
    if op_names & {"HMUL", "HADD", "HSUB", "HMAX", "HMIN", "FMAX", "FMIN"}:
        flags.append("has_float_cal")
    if op_names & {"HMMAL", "HMMA"}:
        flags.append("has_hmma")
    if any("RELU" in name or "MAX" in name or "MIN" in name for name in op_names):
        flags.append("activation_like_name")
    if op_names & {"TRCT", "TRCTT", "RXINT"}:
        flags.append("has_transform_or_extract")
    if op_names & {"COPY", "COPYT"}:
        flags.append("has_route_copy")
    return tuple(flags)


def _print_summary(*, root: Path, reports: list[dict[str, object]]) -> None:
    print("# legacy GEMM template inspection")
    print(f"root={root}")
    print(f"template_count={len(reports)}")
    errors = [report for report in reports if report["error"]]
    print(f"parse_errors={len(errors)}")

    grouped: dict[tuple[int, int], list[dict[str, object]]] = defaultdict(list)
    for report in reports:
        grouped[(int(report["task"]), int(report["subtask"]))].append(report)

    print("\n## aggregate by task/subtask")
    for (task_index, subtask_index), group in sorted(grouped.items()):
        op_counts = Counter()
        stage_counts = Counter()
        flag_counts = Counter()
        cal_counts = Counter()
        st_counts = Counter()
        for report in group:
            op_counts.update(report["op_counts"])
            stage_counts.update(report["stage_counts"])
            cal_counts.update(report["cal_counts"])
            st_counts.update(report["st_counts"])
            flag_counts.update(report["evidence_flags"])
        print(
            f"task{task_index}/subtask{subtask_index}: "
            f"templates={len(group)} insts={sum(int(report['inst_count']) for report in group)} "
            f"stages={_fmt_counter(stage_counts)} flags={_fmt_counter(flag_counts)}"
        )
        print(f"  ops={_fmt_counter(op_counts)}")
        if cal_counts:
            print(f"  cal_ops={_fmt_counter(cal_counts)}")
        if st_counts:
            print(f"  st_ops={_fmt_counter(st_counts)}")

    print("\n## subtask3 evidence focus")
    subtask3_reports = [report for report in reports if int(report["subtask"]) == 3]
    if not subtask3_reports:
        print("no subtask3 templates in selection")
        return
    for report in subtask3_reports[:16]:
        print(
            f"task{report['task']}/subtask3/template{report['template']}: "
            f"insts={report['inst_count']} stages={_fmt_counter(report['stage_counts'])} "
            f"ops={_fmt_counter(report['op_counts'])} flags={','.join(report['evidence_flags']) or '-'}"
        )
    if len(subtask3_reports) > 16:
        print(f"... {len(subtask3_reports) - 16} more subtask3 templates omitted; use --detail for all")


def _print_detail(reports: list[dict[str, object]]) -> None:
    print("\n## per-template detail")
    for report in reports:
        print(
            f"task{report['task']}/subtask{report['subtask']}/template{report['template']}: "
            f"insts={report['inst_count']} stages={_fmt_counter(report['stage_counts'])} "
            f"ops={_fmt_counter(report['op_counts'])} flags={','.join(report['evidence_flags']) or '-'}"
        )


def _fmt_counter(counter: Counter) -> str:
    if not counter:
        return "{}"
    return "{" + ", ".join(f"{key}:{counter[key]}" for key in sorted(counter)) + "}"


if __name__ == "__main__":
    main()
