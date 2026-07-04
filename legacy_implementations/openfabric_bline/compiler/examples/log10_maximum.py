#!/usr/bin/env python3
"""ChipEnv example: audio log10 + global max + maximum preprocessing.

This models the signal-preprocessing fragment:

    log_spec = log10(clamp(mel_spec, min=1e-10))
    global_max = reduce_max(log_spec)
    out = maximum(log_spec, global_max - 8.0)
    out = (out + 4.0) / 4.0

The current compiler intentionally stops at `AppPlan` for this case.  The
important test is semantic partitioning:

    app0: compute/materialize global max
    app1: reload input + global max, recompute local log tile, post-process

That avoids assuming PE-local log tiles survive across app boundaries.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gpdpu_compiler.core import AppPlan, ChipEnv, TaskPartitionPlan
from gpdpu_compiler.core.ops import (
    add_scalar,
    clamp_min,
    log10,
    maximum,
    mul_scalar,
    reduce_max,
)
from gpdpu_compiler.placements import Shard, TaskShard


DEFAULT_OUTPUT_DIR = Path("tmp/gpdpu_compiler_chip_examples/log10_maximum")


def build_env() -> ChipEnv:
    env = ChipEnv("log10max_audio_preprocess")
    env.configure_task_axis(task_axis_size=1, physical_mesh_shape=(4, 4))

    mel_sram = env.sram_tensor(
        "mel_spec",
        shape=(128, 512),
        dtype="fp32",
        offset_bytes=0x00000,
        role="input",
    )
    out_sram = env.sram_tensor(
        "Y",
        shape=(128, 512),
        dtype="fp32",
        offset_bytes=0x80000,
        role="output",
    )

    mel = env.load(
        mel_sram,
        placements=[TaskShard("log10max_single_task_tile"), Shard(0), Shard(1)],
    )
    log_spec = log10(clamp_min(mel, min_value=1.0e-10))
    global_max = reduce_max(log_spec)
    threshold = add_scalar(global_max, -8.0)
    clipped = maximum(log_spec, threshold)
    normalized = mul_scalar(add_scalar(clipped, 4.0), 0.25)

    env.store(normalized, out_sram)
    env.output("Y", out_sram)
    return env


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    env = build_env()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    chip_plan = env.to_chip_plan()
    app_plan_ir = AppPlan(env.program)
    app_plan = app_plan_ir.to_plan()
    task_partition_plan = TaskPartitionPlan(app_plan_ir, env.chip).to_plan()
    (args.output_dir / "chip_program.json").write_text(
        json.dumps(chip_plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "app_plan.json").write_text(
        json.dumps(app_plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (args.output_dir / "task_partition_plan.json").write_text(
        json.dumps(task_partition_plan, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            _summary(chip_plan, app_plan, task_partition_plan, args.output_dir),
            indent=2,
            sort_keys=True,
        )
    )


def _summary(
    chip_plan: dict,
    app_plan: dict,
    task_partition_plan: dict,
    output_dir: Path,
) -> dict:
    return {
        "program": chip_plan["program"],
        "status": "app_plan_ir_only_binary_not_started",
        "chip_program": str(output_dir / "chip_program.json"),
        "app_plan": str(output_dir / "app_plan.json"),
        "task_partition_plan": str(output_dir / "task_partition_plan.json"),
        "ops": [op["op"] for op in chip_plan["ops"]],
        "apps": list(app_plan["apps"]),
        "task_axis_mesh": chip_plan["task_axis_mesh"],
        "task_partition_validation": task_partition_plan["validation"],
        "validation": app_plan["validation"],
    }


if __name__ == "__main__":
    main()
