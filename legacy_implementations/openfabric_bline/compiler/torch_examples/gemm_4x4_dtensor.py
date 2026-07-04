#!/usr/bin/env python3
"""Describe GEMM on a 4x4 mesh using PyTorch DTensor concepts.

This is a frontend example for the DFU Tiny Distributed Tensor Compiler.

Dry run:
    python3 compiler/examples/gemm_4x4_dtensor.py --dry-run

Real DTensor run, when PyTorch is installed:
    python3 -m torch.distributed.run --nnodes=1 --nproc_per_node=16 \
      --master_addr=127.0.0.1 --master_port=29501 \
      -- compiler/examples/gemm_4x4_dtensor.py --backend gloo

The intended DFU lowering target is:
    DeviceMesh(4, 4)
      -> A: Shard(M) x Replicate
      -> B: Replicate x Shard(N)
      -> C: Shard(M) x Shard(N)
      -> PE-local K reduce through hardware instance loop
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Sequence
import torch
import torch.distributed as dist
from torch.distributed.device_mesh import init_device_mesh
from torch.distributed.tensor import Replicate, Shard, distribute_tensor


@dataclass(frozen=True)
class PlacementText:
    tensor: str
    shape: tuple[int, ...]
    placements: tuple[str, str]
    meaning: str


def build_plan_text(m: int, k: int, n: int) -> list[PlacementText]:
    """Return a human-readable version of the distributed GEMM layout.

    A DTensor placement list has one entry per DeviceMesh dimension. In this
    example the mesh dimensions are ("row", "col"), so placements are read as:

        placements=[what happens over mesh rows, what happens over mesh cols]

    Shard(dim) means:
        Split the global tensor along tensor dimension `dim`, and distribute
        those pieces across the current mesh dimension.

    Replicate() means:
        Do not split along the current mesh dimension. Ranks that differ only
        along this mesh dimension see the same logical tensor shard.

    For the future DFU compiler, these are not just PyTorch annotations. They
    describe PE ownership and communication:

        Shard     -> which PE/rank owns which tile
        Replicate -> broadcast, repeated local load, or already-shared data
    """
    return [
        PlacementText(
            tensor="A",
            shape=(m, k),
            placements=("Shard(dim=0)", "Replicate()"),
            meaning="M dimension is split across mesh rows; each mesh row broadcasts/replicates A along columns.",
        ),
        PlacementText(
            tensor="B",
            shape=(k, n),
            placements=("Replicate()", "Shard(dim=1)"),
            meaning="N dimension is split across mesh columns; each mesh column owns a B shard visible to rows.",
        ),
        PlacementText(
            tensor="C = A @ B",
            shape=(m, n),
            placements=("Shard(dim=0)", "Shard(dim=1)"),
            meaning="Each rank/PE owns a unique output C shard; no cross-rank all_reduce is required.",
        ),
    ]


def print_dry_run(args: argparse.Namespace) -> None:
    print("DFU GEMM on a 4x4 DeviceMesh")
    print("=" * 34)
    print(f"global shape: A[{args.m}, {args.k}] @ B[{args.k}, {args.n}] -> C[{args.m}, {args.n}]")
    print('mesh: DeviceMesh("pe", (4, 4), mesh_dim_names=("row", "col"))')
    print()

    for item in build_plan_text(args.m, args.k, args.n):
        print(f"{item.tensor}: shape={item.shape}")
        print(f"  placements over (row, col): {item.placements}")
        print(f"  meaning: {item.meaning}")
        print()

    print("DFU lowering sketch:")
    print("  subtask1: load/scale local C shard")
    print("  subtask2: hardware instance loop over K-slice stream")
    print("    A: row broadcast via COPYT")
    print("    B: local load by each PE")
    print("    C: PE-local accumulate")
    print("  subtask3: store local C shard")
    print()
    print("Run with PyTorch DTensor:")
    print("  python3 -m torch.distributed.run --nnodes=1 --nproc_per_node=16 \\")
    print("    --master_addr=127.0.0.1 --master_port=29501 \\")
    print("    -- compiler/examples/gemm_4x4_dtensor.py --backend gloo")


def assert_divisible(shape: Sequence[int], mesh_shape: Sequence[int]) -> None:
    m, _, n = shape
    mesh_rows, mesh_cols = mesh_shape
    if m % mesh_rows != 0:
        raise ValueError(f"M={m} must be divisible by mesh rows={mesh_rows}")
    if n % mesh_cols != 0:
        raise ValueError(f"N={n} must be divisible by mesh cols={mesh_cols}")


def run_dtensor(args: argparse.Namespace) -> None:
    assert_divisible((args.m, args.k, args.n), (4, 4))

    if not dist.is_initialized():
        dist.init_process_group(backend=args.backend)

    rank = dist.get_rank()
    world_size = dist.get_world_size()
    if world_size != 16:
        raise RuntimeError(f"expected world_size=16 for a 4x4 mesh, got {world_size}")

    # DeviceMesh is the distributed tensor view of the DFU PE array.
    #
    # PyTorch rank layout for a (4, 4) mesh is logically:
    #
    #     row0: rank00 rank01 rank02 rank03
    #     row1: rank04 rank05 rank06 rank07
    #     row2: rank08 rank09 rank10 rank11
    #     row3: rank12 rank13 rank14 rank15
    #
    # We intentionally name the mesh dimensions ("row", "col") because those
    # names line up with the physical 4x4 PE mesh we have been reconstructing:
    #
    #     row dimension -> PE row group
    #     col dimension -> PE column group
    #
    # Later, our compiler should replace PyTorch ranks with PE ids:
    #
    #     rank00 -> PE00
    #     rank01 -> PE01
    #     ...
    #     rank15 -> PE33 / linear PE15
    #
    mesh = init_device_mesh(
        "cpu",
        (4, 4),
        mesh_dim_names=("row", "col"),
    )

    # Keep data deterministic and simple. Every rank constructs the same global tensors;
    # distribute_tensor shards/replicates them according to placements.
    torch.manual_seed(args.seed)
    a_global = torch.arange(args.m * args.k, dtype=torch.float32).reshape(args.m, args.k)
    b_global = torch.arange(args.k * args.n, dtype=torch.float32).reshape(args.k, args.n)

    # A has shape [M, K].
    #
    # placements=[Shard(0), Replicate()] is read over mesh dims ("row", "col"):
    #
    #     over mesh row: Shard(0)
    #       Split A's tensor dimension 0, i.e. the M/row dimension, across
    #       the 4 mesh rows. Each mesh row gets a different band of A rows.
    #
    #     over mesh col: Replicate()
    #       Within one mesh row, copy/share that same A row band across the
    #       4 ranks/PEs in the row.
    #
    # For DFU lowering, this is the clean tensor-parallel way to describe the
    # hand-written GEMM behavior we observed:
    #
    #     PE00/04/08/12 load row-specific A tiles.
    #     COPYT broadcasts A along each PE row.
    #
    a = distribute_tensor(a_global, device_mesh=mesh, placements=[Shard(0), Replicate()])

    # B has shape [K, N].
    #
    # placements=[Replicate(), Shard(1)]:
    #
    #     over mesh row: Replicate()
    #       Ranks/PEs in different mesh rows need access to the same logical B
    #       column shard, because each output row block multiplies by B.
    #
    #     over mesh col: Shard(1)
    #       Split B's tensor dimension 1, i.e. the N/column dimension, across
    #       the 4 mesh columns. Each PE column owns different output columns.
    #
    # For DFU lowering, this means each PE can load the B tile corresponding
    # to its output-column shard. The first GEMM compiler milestone can model
    # this as PE-local B load from SPM.
    #
    b = distribute_tensor(b_global, device_mesh=mesh, placements=[Replicate(), Shard(1)])

    # Distributed matmul follows the placements above.
    #
    # A contributes an M shard from the mesh row.
    # B contributes an N shard from the mesh column.
    # The K dimension is not sharded across ranks in this first strategy; each
    # PE performs its own local K reduction. On DFU, that local K reduction is
    # where the subtask2 hardware instance loop naturally appears:
    #
    #     for each K slice / instance:
    #         load or receive A tile
    #         load B tile
    #         C_acc += A_tile @ B_tile
    #
    # Therefore C is a true output shard, not a Partial result. No all_reduce
    # is required after this matmul.
    #
    c = a @ b

    if rank == 0:
        print("Created DTensor GEMM on DeviceMesh(4, 4)")
        print(f"A placements: {a.placements}")
        print(f"B placements: {b.placements}")
        print(f"C placements: {c.placements}")
        print(f"C global shape: {tuple(c.shape)}")
        print()
        print("Expected DFU meaning:")
        print("  A row-sharded/col-replicated -> row broadcast/COPYT")
        print("  B row-replicated/col-sharded -> PE-local B shard")
        print("  C row+col sharded -> PE-local output shard, no all_reduce")

    dist.barrier()
    dist.destroy_process_group()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--m", type=int, default=512)
    parser.add_argument("--k", type=int, default=256)
    parser.add_argument("--n", type=int, default=512)
    parser.add_argument("--backend", default="gloo", help="torch.distributed backend for real DTensor run")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="print the distributed tensor plan without importing PyTorch",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.dry_run:
        print_dry_run(args)
        return
    run_dtensor(args)


if __name__ == "__main__":
    main()
