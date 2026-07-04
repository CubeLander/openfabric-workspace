#!/usr/bin/env python3
"""Emit progress-first B-line binary payloads from local tactical baselines.

This is intentionally not a reliability gate.  It exists for delivery-week
progress: take a known local A-line binary baseline and package it as a B-line
progress payload so binary upload / SimICT bring-up can start while the true
B-line byte writers continue to catch up.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
COMPILER_ROOT = REPO_ROOT / "compiler"
if str(COMPILER_ROOT) not in sys.path:
    sys.path.insert(0, str(COMPILER_ROOT))

from gpdpu_compiler.core.stream_compiler.aline_gemm_evidence import (  # noqa: E402
    build_aline_gemm_evidence_report,
)
from gpdpu_compiler.decoder.profiles import DFU3500_SIMICT_LEGACY_PROFILE  # noqa: E402
from gpdpu_compiler.validation.dfu_binary_checks.runtime_ready_gate import (  # noqa: E402
    archive_runtime_ready_gate,
)


DEFAULT_OUTPUT_ROOT = REPO_ROOT / "report" / "b_line_progress_payloads"
LOCAL_RISC_ROOT = REPO_ROOT / "simict3500final" / "gpdpu" / "users" / "risc_nn_riscv"
SUPPORTED_OPERATORS = ("gemm_no_relu", "gemm_relu", "log10max")
LOG10MAX_VALIDATION_PAYLOAD = (
    REPO_ROOT
    / "compiler"
    / "gpdpu_compiler"
    / "validation"
    / "dfu3500_partner_validation"
    / "payloads"
    / "log10max_single_task"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--operator",
        choices=SUPPORTED_OPERATORS,
        default="gemm_no_relu",
        help="operator payload to emit",
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=DEFAULT_OUTPUT_ROOT,
        help="directory that will receive <operator>/ payload directories",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="replace an existing operator payload directory",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    if args.operator == "log10max":
        _emit_log10max_progress_payload(args.output_root, force=args.force)
        return
    if args.operator not in SUPPORTED_OPERATORS:
        raise SystemExit(f"unsupported progress payload operator: {args.operator}")

    report = build_aline_gemm_evidence_report(repo_root=REPO_ROOT)
    case_path = Path(report.case_path)
    if not report.full_size_result_available:
        raise SystemExit(
            "selected A-line GEMM case lacks full-size result binaries: "
            f"{case_path}"
        )

    payload_dir = args.output_root / args.operator
    if payload_dir.exists():
        if not args.force:
            raise SystemExit(
                f"{payload_dir} already exists; pass --force to replace it"
            )
        shutil.rmtree(payload_dir)
    payload_dir.mkdir(parents=True)

    copied = []
    copied.extend(
        _copy_required_files(
            case_path,
            payload_dir,
            (
                ("result/cbuf_file.bin", "result/cbuf_file.bin"),
                ("result/micc_file.bin", "result/micc_file.bin"),
                ("result/data_inst_replace.bin", "result/data_inst_replace.bin"),
                ("result/cbuf_file.bin", "config/cbuf_file.bin"),
                ("result/micc_file.bin", "config/micc_file.bin"),
                ("input_data.bin", "runtime/input_data.bin"),
                ("input_data_m.bin", "runtime/input_data_m.bin"),
                ("output_data_m.bin", "reference/output_data_m.bin"),
                ("operator_conf.h", "source/operator_conf.h"),
                ("riscv/testarm.c", "runtime/riscv_src/riscv/testarm.c"),
                ("riscv/dpuctrl.c", "runtime/riscv_src/riscv/dpuctrl.c"),
                ("riscv/makefile", "runtime/riscv_src/riscv/makefile"),
                ("csv_generate/conf.h", "runtime/riscv_src/csv_generate/conf.h"),
                ("spm_data/data.h", "runtime/riscv_src/spm_data/data.h"),
            ),
        )
    )
    copied.extend(_copy_payload_dpuapi(payload_dir))
    _ensure_payload_riscv_makefile(payload_dir)
    copied.extend(
        _copy_tree_files(
            case_path / "simulator_bin",
            payload_dir / "simulator_bin",
        )
    )

    metadata = _metadata(
        operator=args.operator,
        case_path=case_path,
        payload_dir=payload_dir,
        copied_files=copied,
        evidence_report=report,
    )
    (payload_dir / "PROGRESS_METADATA.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _try_build_payload_riscv_program(payload_dir)
    manifest_lines = _manifest_lines(metadata, payload_dir)
    (payload_dir / "MANIFEST.txt").write_text(
        "\n".join(manifest_lines) + "\n",
        encoding="utf-8",
    )
    _archive_runtime_ready_report(payload_dir, operator_metadata=metadata)

    print("b-line progress payload emitted")
    print(f"operator={args.operator}")
    print(f"payload_dir={payload_dir}")
    print(f"source_case={case_path}")
    print(f"file_count={len(_payload_files(payload_dir))}")
    print(f"result_cbuf_sha256={metadata['result_cbuf_sha256']}")
    print(f"result_micc_sha256={metadata['result_micc_sha256']}")
    print("status=progress_first_tactical_binary_seed")


def _emit_log10max_progress_payload(output_root: Path, *, force: bool) -> None:
    source_dir = LOG10MAX_VALIDATION_PAYLOAD
    if not source_dir.exists():
        raise SystemExit(f"missing log10max validation payload: {source_dir}")
    payload_dir = output_root / "log10max"
    if payload_dir.exists():
        if not force:
            raise SystemExit(
                f"{payload_dir} already exists; pass --force to replace it"
            )
        shutil.rmtree(payload_dir)
    shutil.copytree(source_dir, payload_dir)
    _copy_payload_dpuapi(payload_dir)
    _ensure_payload_riscv_makefile(payload_dir)
    _try_build_payload_riscv_program(payload_dir)

    metadata = _log10max_metadata(source_dir=source_dir, payload_dir=payload_dir)
    (payload_dir / "PROGRESS_METADATA.json").write_text(
        json.dumps(metadata, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    original_manifest = payload_dir / "MANIFEST.txt"
    original_manifest_text = (
        original_manifest.read_text(encoding="utf-8")
        if original_manifest.exists()
        else ""
    )
    (payload_dir / "SOURCE_MANIFEST.txt").write_text(
        original_manifest_text,
        encoding="utf-8",
    )
    (payload_dir / "MANIFEST.txt").write_text(
        "\n".join(_manifest_lines(metadata, payload_dir)) + "\n",
        encoding="utf-8",
    )
    _archive_runtime_ready_report(payload_dir, operator_metadata=metadata)

    print("b-line progress payload emitted")
    print("operator=log10max")
    print(f"payload_dir={payload_dir}")
    print(f"source_payload={source_dir}")
    print(f"file_count={len(_payload_files(payload_dir))}")
    print(f"result_cbuf_sha256={metadata['result_cbuf_sha256']}")
    print(f"result_micc_sha256={metadata['result_micc_sha256']}")
    print("status=progress_first_structural_binary_seed")


def _copy_payload_dpuapi(payload_dir: Path) -> list[str]:
    copied: list[str] = []
    dpuapi_src = LOCAL_RISC_ROOT / "dpuapi"
    dpuapi_dst = payload_dir / "runtime" / "riscv_src" / "dpuapi"
    dpuapi_dst.mkdir(parents=True, exist_ok=True)
    for name in ("DpuAPI.c", "DpuAPI.h"):
        src = dpuapi_src / name
        if not src.exists():
            raise SystemExit(f"missing local DpuAPI source: {src}")
        dst = dpuapi_dst / name
        shutil.copy2(src, dst)
        copied.append(str(dst.relative_to(payload_dir)))
    return copied


def _ensure_payload_riscv_makefile(payload_dir: Path) -> None:
    makefile = payload_dir / "runtime" / "riscv_src" / "riscv" / "makefile"
    makefile.parent.mkdir(parents=True, exist_ok=True)
    makefile.write_text(
        "\n".join(
            [
                "CC ?= riscv64-unknown-elf-gcc",
                "OBJDUMP ?= riscv64-unknown-elf-objdump",
                "COMMON_SRC ?= $(SIMICT_ROOT)/gpdpu/users/risc_nn_riscv/common/src",
                "CFLAGS ?= -mabi=lp64d -march=rv64imafdc -static -std=gnu99 -Wno-error=int-conversion",
                "API_SOURCE := ../dpuapi/DpuAPI.c",
                "all: riscv",
                "riscv: testarm.c $(API_SOURCE)",
                "\t$(CC) $(CFLAGS) -o $@ testarm.c $(API_SOURCE) -I../dpuapi -I$(COMMON_SRC)",
                "\t$(OBJDUMP) -D $@ > riscv.lst || true",
                "clean:",
                "\trm -f riscv riscv.lst",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _try_build_payload_riscv_program(payload_dir: Path) -> None:
    gcc_path = shutil.which("riscv64-unknown-elf-gcc")
    if gcc_path is None:
        print("warning=missing_riscv64_unknown_elf_gcc; runtime/riscv_program not built locally")
        return
    gcc = str(Path(gcc_path).resolve())

    src_root = payload_dir / "runtime" / "riscv_src"
    riscv_dir = src_root / "riscv"
    testarm = riscv_dir / "testarm.c"
    dpuapi = src_root / "dpuapi" / "DpuAPI.c"
    common_include = LOCAL_RISC_ROOT / "common" / "src"
    out = payload_dir / "runtime" / "riscv_program"
    if not testarm.exists() or not dpuapi.exists():
        print("warning=missing_riscv_source; runtime/riscv_program not built locally")
        return

    out.parent.mkdir(parents=True, exist_ok=True)
    flag_attempts = (
        ("rv64imafdc_lp64d", ["-mabi=lp64d", "-march=rv64imafdc", "-static"]),
        ("toolchain_default_static", ["-static"]),
        ("toolchain_default", []),
    )
    build_log = payload_dir / "runtime" / "riscv_program.build.log"
    attempts: list[str] = []
    result: subprocess.CompletedProcess[str] | None = None
    for attempt_name, arch_flags in flag_attempts:
        cmd = [
            gcc,
            *arch_flags,
            "-std=gnu99",
            "-Wno-error=int-conversion",
            "-o",
            str(out),
            str(testarm),
            str(dpuapi),
            "-I",
            str(src_root / "dpuapi"),
            "-I",
            str(common_include),
        ]
        result = subprocess.run(
            cmd,
            cwd=riscv_dir,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            check=False,
        )
        attempts.append(
            "### attempt=%s\n$ %s\n%s\n"
            % (attempt_name, " ".join(cmd), result.stdout)
        )
        if result.returncode == 0 and out.exists():
            break
    build_log.write_text("\n".join(attempts), encoding="utf-8")
    if result is None or result.returncode != 0 or not out.exists():
        print(f"warning=riscv_program_local_build_failed; log={build_log}")
        return
    objdump_path = shutil.which("riscv64-unknown-elf-objdump")
    if objdump_path is not None:
        objdump = str(Path(objdump_path).resolve())
        lst = payload_dir / "runtime" / "riscv_program.lst"
        with lst.open("w", encoding="utf-8") as file:
            subprocess.run([objdump, "-D", str(out)], stdout=file, check=False)
    print(f"runtime_riscv_program={out}")


def _archive_runtime_ready_report(
    payload_dir: Path,
    *,
    operator_metadata: dict[str, object] | None = None,
) -> None:
    report = archive_runtime_ready_gate(
        payload_dir,
        profile=DFU3500_SIMICT_LEGACY_PROFILE,
        require_pass=False,
    )
    if operator_metadata is not None:
        report_path = payload_dir / "validation" / "runtime_ready.json"
        report_data = json.loads(report_path.read_text(encoding="utf-8"))
        report_data["operator_metadata"] = {
            key: operator_metadata[key]
            for key in (
                "operator",
                "collective_strategy",
                "customer_collective_label",
                "direct_route_reduce_broadcast",
                "task_axis",
                "runtime_ordering_domain",
                "cross_task_one_app_ring",
                "cross_task_visibility_claim",
            )
            if key in operator_metadata
        }
        report_path.write_text(
            json.dumps(report_data, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(f"runtime_ready_final_status={report.final_status}")


def _copy_required_files(
    source_root: Path,
    payload_dir: Path,
    mapping: tuple[tuple[str, str], ...],
) -> list[str]:
    copied: list[str] = []
    for src_rel, dst_rel in mapping:
        src = source_root / src_rel
        if not src.exists():
            continue
        dst = payload_dir / dst_rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(dst_rel)
    return copied


def _copy_tree_files(source_dir: Path, dest_dir: Path) -> list[str]:
    if not source_dir.exists():
        return []
    copied: list[str] = []
    for src in sorted(path for path in source_dir.rglob("*") if path.is_file()):
        rel = src.relative_to(source_dir)
        dst = dest_dir / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
        copied.append(str(dst.relative_to(dest_dir.parents[0])))
    return copied


def _metadata(
    *,
    operator: str,
    case_path: Path,
    payload_dir: Path,
    copied_files: list[str],
    evidence_report: object,
) -> dict[str, object]:
    result_cbuf = payload_dir / "result" / "cbuf_file.bin"
    result_micc = payload_dir / "result" / "micc_file.bin"
    return {
        "schema_version": 1,
        "artifact": "b_line_progress_first_payload",
        "operator": operator,
        "payload_status": "progress_first_tactical_binary_seed",
        "source_line": "A-line",
        "source_case_path": str(case_path),
        "source_case_kind": "gemm_template_fusion_bash_semantics_probe",
        "b_line_claim": (
            "binary bring-up seed only; true B-line byte writers still need to "
            "replace tactical A-line bytes"
        ),
        "customer_delivery_use": (
            "use for upload/SimICT path bring-up before final B-line-native binary"
        ),
        "full_size_result_available": bool(
            getattr(evidence_report, "full_size_result_available", False)
        ),
        "csv_template_count": int(getattr(evidence_report, "csv_template_count", 0)),
        "task_count": int(getattr(evidence_report, "task_count", 0)),
        "copied_files": sorted(copied_files),
        "result_cbuf_size": result_cbuf.stat().st_size,
        "result_cbuf_sha256": _sha256_file(result_cbuf),
        "result_micc_size": result_micc.stat().st_size,
        "result_micc_sha256": _sha256_file(result_micc),
        "known_limitations": _known_limitations(operator),
    }


def _log10max_metadata(*, source_dir: Path, payload_dir: Path) -> dict[str, object]:
    manifest = _parse_key_value_manifest(source_dir / "MANIFEST.txt")
    result_cbuf = payload_dir / "result" / "cbuf_file.bin"
    result_micc = payload_dir / "result" / "micc_file.bin"
    chip_program = payload_dir / "chip_program.json"
    return {
        "schema_version": 1,
        "artifact": "b_line_progress_first_payload",
        "operator": "log10max",
        "payload_status": "progress_first_structural_binary_seed",
        "source_line": "B-line/current-validation",
        "source_case_path": str(source_dir),
        "source_case_kind": "log10max_single_task",
        "case_id": "log10max_single_task",
        "b_line_claim": (
            "binary structure seed for log10max; current instruction rows are "
            "not yet functional for full log10max semantics"
        ),
        "customer_delivery_use": (
            "use for upload/package/SimICT control-path bring-up while PE00 "
            "physical store/readback and functional instruction rows are finished"
        ),
        "program_status": manifest.get("program_status"),
        "task_count": int(manifest.get("task_num", "1")),
        "csv_template_count": 0,
        "runtime_runnable": manifest.get("runtime_runnable") == "1",
        "runtime_package_complete": _has_complete_binary_package(payload_dir),
        "runtime_expectation": manifest.get("runtime_expectation"),
        "collective_strategy": "ring_spmd_row_then_col",
        "customer_collective_label": "spmd_ring_materialized_reduce",
        "direct_route_reduce_broadcast": "deferred",
        "task_axis": 1,
        "runtime_ordering_domain": "single_task_group",
        "cross_task_one_app_ring": "forbidden",
        "cross_task_visibility_claim": False,
        "runtime_blocking_reasons": [
            value
            for key, value in manifest.items()
            if key.startswith("runtime_blocking_reason:")
        ],
        "chip_program_present": chip_program.exists(),
        "result_cbuf_size": result_cbuf.stat().st_size,
        "result_cbuf_sha256": _sha256_file(result_cbuf),
        "result_micc_size": result_micc.stat().st_size,
        "result_micc_sha256": _sha256_file(result_micc),
        "known_limitations": [
            "runtime_runnable is false in the source manifest",
            "instruction rows are structural smoke, not full functional log10max",
            "unsupported broadcast_load/local_compute/reduce_store rows remain",
            "ring_spmd_row_then_col route/update/global-max binding still needs progress work",
            "PE00 materialized scalar is debug/delivery escape hatch only",
            "direct_route_reduce_broadcast is deferred",
            "not a numerical correctness proof",
        ],
    }


def _parse_key_value_manifest(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        if "=" not in raw_line:
            continue
        key, value = raw_line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if key == "runtime_blocking_reason":
            # Preserve repeated values with stable synthetic keys for metadata
            # callers that want every source blocker.
            index = sum(1 for existing in values if existing.startswith(key))
            values[f"{key}:{index}"] = value
        else:
            values[key] = value
    return values


def _has_complete_binary_package(payload_dir: Path) -> bool:
    return all(
        (payload_dir / rel).exists()
        for rel in (
            "result/cbuf_file.bin",
            "result/micc_file.bin",
            "config/cbuf_file.bin",
            "config/micc_file.bin",
            "simulator_bin/insts_file.bin",
            "simulator_bin/exeblock_conf_info_file.bin",
            "simulator_bin/instance_conf_info_file.bin",
            "simulator_bin/tasks_conf_info_file.bin",
            "simulator_bin/subtasks_conf_info_file.bin",
        )
    )


def _known_limitations(operator: str) -> list[str]:
    limitations = [
        "not emitted by final B-line inst_t byte writer",
        "not a numerical correctness proof",
        "not a replacement for final GEMM/GEMM+ReLU/log10max customer bundle",
    ]
    if operator == "gemm_no_relu":
        limitations.append(
            "source is a gemm_template_fusion case and may include fused ReLU semantics"
        )
    if operator == "gemm_relu":
        limitations.append(
            "source is tactical A-line fused GEMM/ReLU baseline, not B-line-native"
        )
    return limitations


def _manifest_lines(metadata: dict[str, object], payload_dir: Path) -> list[str]:
    lines = [
        f"operator={metadata['operator']}",
        f"payload_status={metadata['payload_status']}",
        f"source_line={metadata['source_line']}",
        f"source_case_path={metadata['source_case_path']}",
        f"source_case_kind={metadata['source_case_kind']}",
        f"task_count={metadata['task_count']}",
        f"csv_template_count={metadata['csv_template_count']}",
        f"result_cbuf_file.bin_size={metadata['result_cbuf_size']}",
        f"result_cbuf_file.bin_sha256={metadata['result_cbuf_sha256']}",
        f"result_micc_file.bin_size={metadata['result_micc_size']}",
        f"result_micc_file.bin_sha256={metadata['result_micc_sha256']}",
    ]
    if "case_id" in metadata:
        lines.append(f"case_id={metadata['case_id']}")
    if "runtime_package_complete" in metadata:
        lines.append(
            "runtime_package_complete=%d"
            % int(bool(metadata["runtime_package_complete"]))
        )
    for key in (
        "collective_strategy",
        "customer_collective_label",
        "direct_route_reduce_broadcast",
        "task_axis",
        "runtime_ordering_domain",
        "cross_task_one_app_ring",
        "cross_task_visibility_claim",
    ):
        if key in metadata:
            value = metadata[key]
            if isinstance(value, bool):
                value = int(value)
            lines.append(f"{key}={value}")
    for path in _payload_files(payload_dir):
        rel = path.relative_to(payload_dir)
        key = str(rel).replace("/", "_")
        lines.append(f"{key}_size={path.stat().st_size}")
        lines.append(f"{key}_sha256={_sha256_file(path)}")
    return lines


def _payload_files(payload_dir: Path) -> list[Path]:
    return sorted(
        path
        for path in payload_dir.rglob("*")
        if path.is_file()
        and path.name != "MANIFEST.txt"
        and path.relative_to(payload_dir) != Path("validation/runtime_ready.json")
    )


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


if __name__ == "__main__":
    main()
