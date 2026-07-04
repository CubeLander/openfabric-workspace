#!/usr/bin/env python3
"""Represent log10 + max + maximum as a distributed tensor program.

This example models the signal-processing fragment from Qwen3-ASR mel
preprocessing:

    log_spec = torch.clamp(mel_spec, min=1e-10).log10()
    log_spec = torch.maximum(log_spec, log_spec.max() - 8.0)
    log_spec = (log_spec + 4.0) / 4.0

The key distributed-tensor lesson:

    log10 / clamp / maximum / affine scale
        are elementwise and can run on each PE-local shard independently.

    log_spec.max()
        is a global reduction across all shards, so it becomes a collective
        all_reduce(MAX) that produces a replicated scalar.

Dry run:
    python3 compiler/examples/log10_maximum_dtensor.py --dry-run

Real DTensor run:
    python3 -m torch.distributed.run --nnodes=1 --nproc_per_node=16 \
      --master_addr=127.0.0.1 --master_port=29502 \
      -- compiler/examples/log10_maximum_dtensor.py --backend gloo
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Sequence


@dataclass(frozen=True)
class SignalPlanText:
    tensor: str
    shape: tuple[int, int]
    placements: tuple[str, str]
    meaning: str


def print_dry_run(args: argparse.Namespace) -> None:
    plan = SignalPlanText(
        tensor="mel_spec",
        shape=(args.mel_bins, args.frames),
        placements=("Shard(dim=0)", "Shard(dim=1)"),
        meaning="mel bins are split across mesh rows; time frames are split across mesh columns.",
    )

    print("DFU log10 + max + maximum on a 4x4 DeviceMesh")
    print("=" * 51)
    print(f"{plan.tensor}: shape={plan.shape}")
    print(f"placements over (row, col): {plan.placements}")
    print(f"meaning: {plan.meaning}")
    print()
    print("Distributed program:")
    print("  local_log = log10(clamp(local_mel_spec, min=1e-10))")
    print("  local_max = max(local_log)")
    print("  global_max = all_reduce(local_max, op=MAX)")
    print("  threshold = global_max - 8.0")
    print("  local_out = maximum(local_log, threshold)")
    print("  local_out = (local_out + 4.0) / 4.0")
    print()
    print("DFU lowering sketch:")
    print("  subtask1: PE-local clamp + log10 on each mel/frame tile")
    print("  subtask2: PE-local max, then mesh collective max reduction")
    print("  subtask3: ordinary PE-local maximum with replicated threshold, then affine scale")
    print()
    print("Why this is a good fusion example:")
    print("  log10 and maximum are local elementwise ops.")
    print("  max() is the only op that crosses PE shard boundaries.")
    print("  The compiler can fuse local ops around the collective boundary.")


def assert_divisible(shape: Sequence[int], mesh_shape: Sequence[int]) -> None:
    mel_bins, frames = shape
    mesh_rows, mesh_cols = mesh_shape
    if mel_bins % mesh_rows != 0:
        raise ValueError(f"mel_bins={mel_bins} must be divisible by mesh rows={mesh_rows}")
    if frames % mesh_cols != 0:
        raise ValueError(f"frames={frames} must be divisible by mesh cols={mesh_cols}")


def import_torch_distributed():
    try:
        import torch
        import torch.distributed as dist
        from torch.distributed.device_mesh import init_device_mesh
        from torch.distributed.tensor import Shard, distribute_tensor
    except Exception as exc:  # pragma: no cover - dry-run does not need torch.
        raise RuntimeError(
            "PyTorch with torch.distributed.tensor is required for non-dry-run mode. "
            "Use --dry-run to inspect the distributed signal-processing plan."
        ) from exc

    return torch, dist, init_device_mesh, Shard, distribute_tensor


def run_dtensor(args: argparse.Namespace) -> None:
    assert_divisible((args.mel_bins, args.frames), (4, 4))
    torch, dist, init_device_mesh, Shard, distribute_tensor = import_torch_distributed()

    if not dist.is_initialized():
        dist.init_process_group(backend=args.backend)

    rank = dist.get_rank()
    world_size = dist.get_world_size()
    if world_size != 16:
        raise RuntimeError(f"expected world_size=16 for a 4x4 mesh, got {world_size}")

    mesh = init_device_mesh(
        "cpu",
        (4, 4),
        mesh_dim_names=("row", "col"),
    )

    # This DTensor placement is intentionally different from GEMM:
    #
    #     placements=[Shard(0), Shard(1)]
    #
    # Read over mesh dims ("row", "col"):
    #
    #     over mesh row: Shard(0)
    #       split the mel-bin dimension across PE rows.
    #
    #     over mesh col: Shard(1)
    #       split the time-frame dimension across PE columns.
    #
    # Therefore every PE owns a 2D tile of the mel spectrogram. Elementwise
    # operations are purely PE-local. A global max over the whole tensor must
    # reduce all 16 PE-local maxima.
    placements = [Shard(0), Shard(1)]

    torch.manual_seed(args.seed)
    mel_global = torch.arange(
        args.mel_bins * args.frames,
        dtype=torch.float32,
    ).reshape(args.mel_bins, args.frames)
    mel_global = mel_global / mel_global.numel() + 1e-4

    mel_spec = distribute_tensor(mel_global, device_mesh=mesh, placements=placements)

    # Stage 1: local elementwise clamp + log10.
    #
    # Future DFU meaning:
    #     The compiler can keep this inside a PE-local CAL program because it
    #     only reads/writes the PE's own operand/tile shard.
    local_mel = mel_spec.to_local()
    local_log = torch.clamp(local_mel, min=1e-10).log10()

    # Stage 2: local max + global all_reduce(MAX).
    #
    # This is the exact point where a distributed tensor program stops being
    # PE-local. `local_max` is each rank's tile maximum; all_reduce turns it
    # into a replicated scalar equal to the full global tensor max.
    local_max = local_log.max()
    global_max = local_max.clone()
    dist.all_reduce(global_max, op=dist.ReduceOp.MAX)

    # Stage 3: local elementwise maximum and affine normalization.
    #
    # The threshold scalar is now replicated on every rank/PE, so the rest is
    # local again.
    threshold = global_max - 8.0
    local_out = torch.maximum(local_log, threshold)
    local_out = (local_out + 4.0) / 4.0

    # Validate against a single-process global reference, then shard the
    # reference with the same placements to compare only this rank's tile.
    ref = torch.clamp(mel_global, min=1e-10).log10()
    ref = torch.maximum(ref, ref.max() - 8.0)
    ref = (ref + 4.0) / 4.0
    ref_dt = distribute_tensor(ref, device_mesh=mesh, placements=placements)
    local_err = (local_out - ref_dt.to_local()).abs().max()
    dist.all_reduce(local_err, op=dist.ReduceOp.MAX)

    if rank == 0:
        print("Created DTensor signal-processing graph on DeviceMesh(4, 4)")
        print(f"mel_spec placements: {mel_spec.placements}")
        print(f"global shape: {tuple(mel_spec.shape)}")
        print(f"rank-local tile shape: {tuple(local_mel.shape)}")
        print(f"global max after log10: {float(global_max):.6f}")
        print(f"max validation error: {float(local_err):.6g}")
        print()
        print("Expected DFU meaning:")
        print("  Shard(0), Shard(1) -> each PE owns a mel/frame tile")
        print("  clamp/log10 -> PE-local elementwise CAL")
        print("  max -> PE-local max + mesh all_reduce(MAX)")
        print("  maximum/scale -> ordinary PE-local CAL after the collective barrier")

    dist.barrier()
    dist.destroy_process_group()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mel-bins", type=int, default=128)
    parser.add_argument("--frames", type=int, default=512)
    parser.add_argument("--backend", default="gloo")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--dry-run", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.dry_run:
        print_dry_run(args)
        return
    run_dtensor(args)


if __name__ == "__main__":
    main()
