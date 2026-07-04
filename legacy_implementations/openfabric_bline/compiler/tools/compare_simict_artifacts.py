#!/usr/bin/env python3
"""Compare legacy SimICT binary artifacts against compiler-generated artifacts."""

from __future__ import annotations

import argparse
import hashlib
import struct
from pathlib import Path


STRUCT_SIZES = {
    "inst_t": 304,
    "exeBlock_conf_info_t": 520,
    "instance_conf_info_t": 32,
    "task_conf_info_t": 120,
    "sub_task_conf_info_t": 266328,
}

COMPONENTS = (
    ("insts", "simulator_bin/insts_file.bin", "inst_t"),
    ("exeblock", "simulator_bin/exeblock_conf_info_file.bin", "exeBlock_conf_info_t"),
    ("instance", "simulator_bin/instance_conf_info_file.bin", "instance_conf_info_t"),
    ("tasks", "simulator_bin/tasks_conf_info_file.bin", "task_conf_info_t"),
    ("subtasks", "simulator_bin/subtasks_conf_info_file.bin", "sub_task_conf_info_t"),
)

CBUF_ORDER = ("insts", "exeblock", "instance")
MICC_ORDER = ("tasks", "subtasks")


def main() -> int:
    args = _parse_args()
    legacy = args.legacy.resolve()
    compiler = args.compiler.resolve()

    print(f"legacy={legacy}")
    print(f"compiler={compiler}")
    print()

    blobs: dict[str, tuple[bytes, bytes]] = {}
    for name, relative_path, struct_name in COMPONENTS:
        left = _read_component(legacy, relative_path)
        right = _read_component(compiler, relative_path)
        blobs[name] = (left, right)
        _print_component_summary(name, relative_path, struct_name, left, right)

    print("== final blob composition ==")
    _print_final_summary(
        "cbuf",
        _read_final(legacy, "cbuf_file.bin"),
        _read_final(compiler, "cbuf_file.bin"),
        b"".join(blobs[name][0] for name in CBUF_ORDER),
        b"".join(blobs[name][1] for name in CBUF_ORDER),
        CBUF_ORDER,
    )
    _print_final_summary(
        "micc",
        _read_final(legacy, "micc_file.bin"),
        _read_final(compiler, "micc_file.bin"),
        b"".join(blobs[name][0] for name in MICC_ORDER),
        b"".join(blobs[name][1] for name in MICC_ORDER),
        MICC_ORDER,
    )

    print("== sample decoded rows ==")
    _print_samples("legacy", blobs={name: left for name, (left, _) in blobs.items()}, limit=args.samples)
    _print_samples("compiler", blobs={name: right for name, (_, right) in blobs.items()}, limit=args.samples)
    return 0


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--legacy",
        type=Path,
        default=Path(
            "simict3500final/gpdpu/users/risc_nn_riscv/testcase/build_out/"
            "gemm_template_fusion/worktree/gpdpu/users/risc_nn_riscv/"
            "testcase/application/gemm_template_fusion"
        ),
        help="Legacy case directory containing simulator_bin/ and simulator_bin_multi_app/.",
    )
    parser.add_argument(
        "--compiler",
        type=Path,
        default=Path("tmp/gpdpu_compiler_examples/gemm"),
        help="Compiler output directory containing simulator_bin/ and config/.",
    )
    parser.add_argument(
        "--samples",
        type=int,
        default=4,
        help="Number of nonzero records to decode per component.",
    )
    return parser.parse_args()


def _read_component(root: Path, relative_path: str) -> bytes:
    path = root / relative_path
    if not path.exists() and relative_path.startswith("simulator_bin/"):
        path = root / "config" / Path(relative_path).name
    return path.read_bytes()


def _read_final(root: Path, name: str) -> bytes:
    for path in (
        root / "config" / name,
        root / "simulator_bin_multi_app" / name,
        root / "result" / name,
    ):
        if path.exists():
            return path.read_bytes()
    raise FileNotFoundError(f"cannot find final blob {name} under {root}")


def _print_component_summary(
    name: str,
    relative_path: str,
    struct_name: str,
    left: bytes,
    right: bytes,
) -> None:
    record_size = STRUCT_SIZES[struct_name]
    first_diff = _first_diff(left, right)
    print(f"== {name}: {relative_path} ==")
    print(f"  struct={struct_name} record_size={record_size}")
    print(
        "  size legacy={left_size} compiler={right_size} "
        "records={left_records}/{right_records}".format(
            left_size=len(left),
            right_size=len(right),
            left_records=len(left) // record_size,
            right_records=len(right) // record_size,
        )
    )
    print(
        "  sha256 legacy={left_hash} compiler={right_hash} same={same}".format(
            left_hash=_sha256(left),
            right_hash=_sha256(right),
            same=str(left == right).lower(),
        )
    )
    print(
        "  nonzero_records legacy={left_nz} compiler={right_nz} "
        "first_diff_byte={first_diff} byte_diffs={diffs}".format(
            left_nz=_nonzero_records(left, record_size),
            right_nz=_nonzero_records(right, record_size),
            first_diff="none" if first_diff is None else first_diff,
            diffs=_byte_diff_count(left, right),
        )
    )
    if first_diff is not None:
        print(
            f"  first_diff_record={first_diff // record_size} "
            f"record_byte={first_diff % record_size}"
        )
    print()


def _print_final_summary(
    name: str,
    legacy_blob: bytes,
    compiler_blob: bytes,
    legacy_expected: bytes,
    compiler_expected: bytes,
    order: tuple[str, ...],
) -> None:
    first_diff = _first_diff(legacy_blob, compiler_blob)
    print(f"{name}: append_order={','.join(order)}")
    print(
        f"  size legacy={len(legacy_blob)} compiler={len(compiler_blob)} "
        f"same={str(legacy_blob == compiler_blob).lower()}"
    )
    print(
        f"  sha256 legacy={_sha256(legacy_blob)} compiler={_sha256(compiler_blob)} "
        f"first_diff_byte={'none' if first_diff is None else first_diff}"
    )
    print(
        "  composition_matches legacy={legacy_ok} compiler={compiler_ok}".format(
            legacy_ok=str(legacy_blob == legacy_expected).lower(),
            compiler_ok=str(compiler_blob == compiler_expected).lower(),
        )
    )
    cursor = 0
    for component in order:
        component_size = len(legacy_expected[cursor:cursor])
        del component_size
        expected_len = _component_len(component)
        print(f"  boundary {component}: offset={cursor} size={expected_len}")
        cursor += expected_len
    print()


def _component_len(component: str) -> int:
    struct_by_name = {
        "insts": ("inst_t", 16 * 4352),
        "exeblock": ("exeBlock_conf_info_t", 512),
        "instance": ("instance_conf_info_t", 65536),
        "tasks": ("task_conf_info_t", 4),
        "subtasks": ("sub_task_conf_info_t", 32),
    }
    struct_name, count = struct_by_name[component]
    return STRUCT_SIZES[struct_name] * count


def _print_samples(label: str, *, blobs: dict[str, bytes], limit: int) -> None:
    print(f"-- {label} --")
    for name, data in blobs.items():
        decoder = {
            "insts": _decode_inst,
            "exeblock": _decode_exeblock,
            "instance": _decode_instance,
            "tasks": _decode_task,
            "subtasks": _decode_subtask,
        }[name]
        record_size = {
            "insts": STRUCT_SIZES["inst_t"],
            "exeblock": STRUCT_SIZES["exeBlock_conf_info_t"],
            "instance": STRUCT_SIZES["instance_conf_info_t"],
            "tasks": STRUCT_SIZES["task_conf_info_t"],
            "subtasks": STRUCT_SIZES["sub_task_conf_info_t"],
        }[name]
        print(f"  {name}:")
        count = 0
        for index in range(0, len(data), record_size):
            record = data[index:index + record_size]
            if not any(record):
                continue
            print(f"    record[{index // record_size}] {decoder(record)}")
            count += 1
            if count >= limit:
                break
        if count == 0:
            print("    no nonzero records")
    print()


def _decode_inst(record: bytes) -> str:
    opcode = struct.unpack_from("<I", record, 0)[0]
    unit_type = _u64(record, 8)
    latency = _u64(record, 16)
    imm0 = _u64(record, 24)
    src0 = _u64(record, 48)
    dst0 = _u64(record, 72)
    base_addr_idx = _u64(record, 240)
    block_idx = _u64(record, 256)
    end_inst = _u64(record, 272)
    return (
        f"opcode=0x{opcode:x} unit=0x{unit_type:x} latency={latency} "
        f"imm0={imm0} src0={src0} dst0={dst0} base_addr_idx={base_addr_idx} "
        f"block_idx={block_idx} end_inst={end_inst}"
    )


def _decode_exeblock(record: bytes) -> str:
    base = 48
    stages = tuple(record[base + 8 + index] for index in range(5))
    stage_pcs = tuple(_u64(record, base + 16 + index * 8) for index in range(5))
    return (
        f"valid={record[0]} block_idx={_u64(record, 8)} "
        f"pe=({_u64(record, 16)},{_u64(record, 24)},{_u64(record, 32)}) "
        f"req={_u64(record, base)} stages={stages} pcs={stage_pcs} "
        f"task={_u64(record, base + 392)} subtask={_u64(record, base + 384)} "
        f"instances={_u64(record, base + 400)} child={_u64(record, base + 408)} "
        f"inst_base={_u64(record, base + 424)} "
        f"counts=({_u64(record, base + 432)},{_u64(record, base + 440)},"
        f"{_u64(record, base + 448)},{_u64(record, base + 456)}) "
        f"is_leaf={record[base + 464]}"
    )


def _decode_instance(record: bytes) -> str:
    values = struct.unpack_from("<4Q", record, 0)
    return "base_addr=[" + ",".join(f"0x{value:x}" for value in values) + "]"


def _decode_task(record: bytes) -> str:
    values = struct.unpack_from("<BB6x14Q", record, 0)
    subtasks = values[4:12]
    successors = values[12:16]
    return (
        f"start={values[0]} end={values[1]} subtasks_amount={values[2]} "
        f"execute_times={values[3]} subtasks={subtasks} successors={successors}"
    )


def _decode_subtask(record: bytes) -> str:
    successors = tuple(_u64(record, 24 + index * 8) for index in range(4))
    return (
        f"start={record[0]} end={record[1]} instances={_u64(record, 8)} "
        f"instance_addr={_u64(record, 16)} successors={successors} "
        f"root_blocks={_u64(record, 56)} block_amount={_u64(record, 64)} "
        f"subtask_idx={_u64(record, 266312)} task_idx={_u64(record, 266320)}"
    )


def _u64(record: bytes, offset: int) -> int:
    return struct.unpack_from("<Q", record, offset)[0]


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _first_diff(left: bytes, right: bytes) -> int | None:
    for index, (left_byte, right_byte) in enumerate(zip(left, right)):
        if left_byte != right_byte:
            return index
    if len(left) != len(right):
        return min(len(left), len(right))
    return None


def _byte_diff_count(left: bytes, right: bytes) -> int:
    return sum(1 for left_byte, right_byte in zip(left, right) if left_byte != right_byte) + abs(
        len(left) - len(right)
    )


def _nonzero_records(data: bytes, record_size: int) -> int:
    return sum(1 for offset in range(0, len(data), record_size) if any(data[offset:offset + record_size]))


if __name__ == "__main__":
    raise SystemExit(main())
