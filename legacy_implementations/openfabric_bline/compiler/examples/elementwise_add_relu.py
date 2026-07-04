#!/usr/bin/env python3
"""ChipEnv example: explicit-SRAM elementwise Add followed by ReLU."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gpdpu_compiler.core import ChipEnv
from gpdpu_compiler.core.ops import add, relu
from gpdpu_compiler.placements import Shard, TaskShard


DEFAULT_OUTPUT_DIR = Path("tmp/gpdpu_compiler_chip_examples/elementwise_add_relu")


def build_env() -> ChipEnv:
    env = ChipEnv("elementwise_add_relu")
    env.configure_task_axis(task_axis_size=1, physical_mesh_shape=(4, 4))

    x_sram = env.sram_tensor("X", shape=(128, 128), dtype="fp16", offset_bytes=0x00000)
    bias_sram = env.sram_tensor("Bias", shape=(128, 128), dtype="fp16", offset_bytes=0x08000)
    y_sram = env.sram_tensor(
        "Y",
        shape=(128, 128),
        dtype="fp16",
        offset_bytes=0x10000,
        role="output",
    )

    x = env.load(
        x_sram,
        placements=[TaskShard("elementwise_output_tile"), Shard(0), Shard(1)],
    )
    bias = env.load(
        bias_sram,
        placements=[TaskShard("elementwise_output_tile"), Shard(0), Shard(1)],
    )
    y = relu(add(x, bias))
    env.set_task_placement(y, TaskShard("elementwise_output_tile"))

    env.store(y, y_sram)
    env.output("Y", y_sram)
    return env


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args()

    plan = build_env().generate(output_dir=args.output_dir)
    print(json.dumps(_summary(plan, args.output_dir), indent=2, sort_keys=True))


def _summary(plan: dict, output_dir: Path) -> dict:
    chip_program = plan["chip_program"]
    return {
        "program": chip_program["program"],
        "chip": plan["chip"]["name"],
        "status": plan["status"],
        "output": str(output_dir / "chip_program.json"),
        "ops": [op["op"] for op in chip_program["ops"]],
        "task_axis_mesh": chip_program["task_axis_mesh"],
    }


if __name__ == "__main__":
    main()
