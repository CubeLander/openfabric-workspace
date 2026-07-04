#!/usr/bin/env python3
"""ChipEnv example: explicit-SRAM GEMM followed by ReLU."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from gpdpu_compiler.core import ChipEnv, DFU3500_GEMM_REGIONS
from gpdpu_compiler.core.ops import relu
from gpdpu_compiler.placements import Replicate, Shard, TaskReplicate, TaskShard


DEFAULT_OUTPUT_DIR = Path("tmp/gpdpu_compiler_chip_examples/gemm_relu")


def build_env() -> ChipEnv:
    env = ChipEnv("gemm_relu")
    env.configure_task_axis(task_axis_size=4, physical_mesh_shape=(4, 4))

    a_sram = env.sram_tensor_from_region("A", DFU3500_GEMM_REGIONS["A"])
    b_sram = env.sram_tensor_from_region("B", DFU3500_GEMM_REGIONS["B"])
    y_sram = env.sram_tensor_from_region("Y", DFU3500_GEMM_REGIONS["C"])

    a = env.load(
        a_sram,
        placements=[TaskReplicate(), Shard(0), Replicate()],
    )
    b = env.load(
        b_sram,
        placements=[TaskReplicate(), Replicate(), Shard(1)],
    )
    gemm = env.set_task_placement(
        a @ b,
        TaskShard("gemm_output_tiles", work_axis_order=("m_tile", "n_tile")),
    )
    y = relu(gemm)

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
        "task_axis_placements": chip_program["task_axis_placements"],
    }


if __name__ == "__main__":
    main()
