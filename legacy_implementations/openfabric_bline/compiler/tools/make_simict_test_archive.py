#!/usr/bin/env python3
"""Create a portable SimICT test archive from compiler binary outputs.

The archive is meant to live next to ``simict3500final`` on the customer
server.  It contains one or more prebuilt operator bundles plus a root
``run_all_bundles.sh`` script that installs each bundle into the SimICT runtime
working directory, launches the closed runtime, and optionally runs the legacy
GEMM checker.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
DEFAULT_LEGACY_GEMM = (
    ROOT
    / "simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion"
)


def main() -> None:
    args = parse_args()
    output = args.output or (ROOT / "openfabric_simict_test_bundles.tar.gz")
    bundle_specs = parse_bundle_specs(args.bundle)
    if not bundle_specs:
        bundle_specs = default_bundle_specs()
    if not bundle_specs:
        raise SystemExit("no bundle outputs found; run compiler examples first")

    output = output.resolve()
    archive_name = output.name.removesuffix(".tar.gz").removesuffix(".tgz")
    with tempfile.TemporaryDirectory(prefix="openfabric_simict_archive_") as temp_dir:
        staging_root = Path(temp_dir) / archive_name
        staging_root.mkdir(parents=True)
        write_root_files(staging_root)

        generated_input = args.input_data
        if generated_input is None and args.generate_legacy_gemm_input:
            generated_input = generate_legacy_gemm_input_data(
                legacy_case=args.legacy_gemm_case,
                work_root=Path(temp_dir),
            )

        bundles = []
        for case_name, compiler_output in bundle_specs:
            bundles.append(
                create_bundle(
                    staging_root=staging_root,
                    case_name=case_name,
                    compiler_output=compiler_output,
                    legacy_gemm_case=args.legacy_gemm_case,
                    input_data=generated_input,
                    riscv_program=args.riscv_program,
                    include_riscv_source=args.include_legacy_gemm_riscv_source,
                    include_debug=args.include_debug,
                    check_mode="legacy_gemm" if case_name == "gemm" else "none",
                )
            )

        write_archive_manifest(staging_root, bundles)
        output.parent.mkdir(parents=True, exist_ok=True)
        with tarfile.open(output, "w:gz") as tar:
            tar.add(staging_root, arcname=staging_root.name)

    print(f"wrote {output}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--bundle",
        action="append",
        default=[],
        metavar="NAME=DIR",
        help="Bundle case name and compiler output dir. May be repeated.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Output .tar.gz path. Defaults to workspace sibling of simict3500final.",
    )
    parser.add_argument(
        "--legacy-gemm-case",
        type=Path,
        default=DEFAULT_LEGACY_GEMM,
        help="Legacy GEMM case used for input/check/RISC-V source seed files.",
    )
    parser.add_argument(
        "--input-data",
        type=Path,
        help="Existing input_data.bin to include in every bundle.",
    )
    parser.add_argument(
        "--riscv-program",
        type=Path,
        help="Existing RISC-V program to include in every bundle.",
    )
    parser.add_argument(
        "--no-include-legacy-gemm-riscv-source",
        action="store_false",
        dest="include_legacy_gemm_riscv_source",
        help="Do not include legacy GEMM RISC-V source for customer-side build.",
    )
    parser.add_argument(
        "--no-generate-legacy-gemm-input",
        action="store_false",
        dest="generate_legacy_gemm_input",
        help="Do not compile legacy GEMM data_generate.cpp for input_data.bin.",
    )
    parser.add_argument(
        "--include-debug",
        action="store_true",
        help="Include plan.json/debug_ir from compiler outputs.",
    )
    return parser.parse_args()


def parse_bundle_specs(values: list[str]) -> list[tuple[str, Path]]:
    specs = []
    for value in values:
        if "=" not in value:
            raise SystemExit(f"--bundle must be NAME=DIR: {value}")
        name, path = value.split("=", 1)
        name = safe_name(name)
        if not name:
            raise SystemExit(f"empty bundle name in: {value}")
        specs.append((name, Path(path).resolve()))
    return specs


def default_bundle_specs() -> list[tuple[str, Path]]:
    specs = []
    # Only include simulator-ready bundles by default.  ``gemm_relu`` currently
    # still uses the native-symbolic instruction path, which is useful for IR
    # smoke tests but not a functional SimICT runtime candidate.
    for name in ("gemm",):
        path = ROOT / "tmp/gpdpu_compiler_examples" / name
        if (path / "config/cbuf_file.bin").is_file() and (path / "config/micc_file.bin").is_file():
            specs.append((name, path))
    return specs


def create_bundle(
    *,
    staging_root: Path,
    case_name: str,
    compiler_output: Path,
    legacy_gemm_case: Path,
    input_data: Path | None,
    riscv_program: Path | None,
    include_riscv_source: bool,
    include_debug: bool,
    check_mode: str,
) -> dict[str, Any]:
    assert_file(compiler_output / "config/cbuf_file.bin")
    assert_file(compiler_output / "config/micc_file.bin")

    bundle_dir = staging_root / "bundles" / case_name
    config_dir = bundle_dir / "config"
    simulator_dir = bundle_dir / "simulator_bin"
    check_dir = bundle_dir / "check"
    config_dir.mkdir(parents=True)
    simulator_dir.mkdir(parents=True)
    check_dir.mkdir(parents=True)

    copy_file(compiler_output / "config/cbuf_file.bin", config_dir / "cbuf_file.bin")
    copy_file(compiler_output / "config/micc_file.bin", config_dir / "micc_file.bin")
    if input_data is not None:
        copy_file(input_data, config_dir / "input_data.bin")
    if riscv_program is not None:
        copy_file(riscv_program, config_dir / "riscv_program")
    if include_riscv_source:
        copy_legacy_gemm_riscv_source(legacy_gemm_case, bundle_dir / "riscv_case")

    source_simulator = compiler_output / "simulator_bin"
    if source_simulator.is_dir():
        for path in sorted(source_simulator.glob("*.bin")):
            copy_file(path, simulator_dir / path.name)

    if include_debug:
        debug_dir = bundle_dir / "debug"
        debug_dir.mkdir()
        if (compiler_output / "plan.json").is_file():
            copy_file(compiler_output / "plan.json", debug_dir / "plan.json")
        if (compiler_output / "debug_ir").is_dir():
            shutil.copytree(compiler_output / "debug_ir", debug_dir / "debug_ir")

    legacy_case_rel = "testcase/application/CASE/gemm_template_fusion"
    (bundle_dir / "legacy_case_rel.txt").write_text(legacy_case_rel + "\n", encoding="utf-8")

    if check_mode == "legacy_gemm":
        copy_legacy_gemm_check_files(legacy_gemm_case, check_dir)

    manifest = {
        "schema_version": 1,
        "case_name": case_name,
        "operator": case_name,
        "compiler_output": str(compiler_output),
        "runtime_files": manifest_files(config_dir),
        "simulator_bin_files": manifest_files(simulator_dir),
        "riscv_source_files": manifest_files(bundle_dir / "riscv_case"),
        "check": {
            "mode": check_mode,
            "ready": check_mode == "legacy_gemm" and (check_dir / "result_check.c").is_file(),
        },
        "notes": [
            "cbuf_file.bin and micc_file.bin are OpenFabric compiler outputs",
            "input_data.bin is generated from/provided for legacy runtime input",
            "riscv_program is prebuilt when supplied; otherwise run_all_bundles.sh builds bundled RISC-V source on the customer server",
        ],
    }
    write_json(bundle_dir / "manifest.json", manifest)
    write_bundle_readme(bundle_dir, case_name, check_mode)
    return manifest


def copy_legacy_gemm_check_files(legacy_case: Path, check_dir: Path) -> None:
    spm_dir = legacy_case / "spm_data"
    csv_dir = legacy_case / "csv_generate"
    copy_file(spm_dir / "result_check.c", check_dir / "result_check.c")
    copy_file(spm_dir / "data.h", check_dir / "spm_data" / "data.h")
    copy_file(csv_dir / "conf.h", check_dir / "csv_generate" / "conf.h")


def copy_legacy_gemm_riscv_source(legacy_case: Path, dst_dir: Path) -> None:
    riscv_source = legacy_case / "riscv"
    csv_source = legacy_case / "csv_generate"
    spm_source = legacy_case / "spm_data"
    assert_file(riscv_source / "testarm.c")
    assert_file(riscv_source / "makefile")
    assert_file(csv_source / "conf.h")
    assert_file(spm_source / "data.h")

    shutil.copytree(
        riscv_source,
        dst_dir / "riscv",
        ignore=shutil.ignore_patterns("riscv", "*.elf", "*.o", "*.lst"),
    )
    copy_file(csv_source / "conf.h", dst_dir / "csv_generate" / "conf.h")
    copy_file(spm_source / "data.h", dst_dir / "spm_data" / "data.h")


def generate_legacy_gemm_input_data(*, legacy_case: Path, work_root: Path) -> Path:
    spm_source = legacy_case / "spm_data"
    csv_source = legacy_case / "csv_generate"
    assert_file(spm_source / "data_generate.cpp")
    assert_file(spm_source / "data.h")
    assert_file(csv_source / "conf_PEmap.h")

    work_case = work_root / "legacy_gemm_input"
    work_spm = work_case / "spm_data"
    work_csv = work_case / "csv_generate"
    work_spm.mkdir(parents=True)
    work_csv.mkdir(parents=True)
    copy_file(spm_source / "data_generate.cpp", work_spm / "data_generate.cpp")
    copy_file(spm_source / "data.h", work_spm / "data.h")
    copy_file(csv_source / "conf_PEmap.h", work_csv / "conf_PEmap.h")

    subprocess.run(
        ["g++", "-std=c++11", "-include", "string", "data_generate.cpp", "-o", "data"],
        cwd=work_spm,
        check=True,
    )
    result = subprocess.run(["./data"], cwd=work_spm, check=False)
    input_data = work_case / "input_data.bin"
    if not input_data.is_file() or input_data.stat().st_size == 0:
        raise SystemExit(
            f"legacy data_generate exited {result.returncode} but did not produce {input_data}"
        )
    return input_data


def write_root_files(staging_root: Path) -> None:
    scripts_dir = staging_root / "scripts"
    scripts_dir.mkdir(parents=True)
    write_executable(staging_root / "run_all_bundles.sh", RUN_ALL_BUNDLES_SH)
    write_executable(staging_root / "upload_and_run_remote.sh", UPLOAD_AND_RUN_REMOTE_SH)
    write_executable(scripts_dir / "run_check.sh", RUN_CHECK_SH)
    write_executable(
        scripts_dir / "compare_remote_legacy_gemm.sh",
        COMPARE_REMOTE_LEGACY_GEMM_SH,
    )
    write_executable(
        scripts_dir / "run_remote_legacy_gemm_and_compare.sh",
        RUN_REMOTE_LEGACY_GEMM_AND_COMPARE_SH,
    )
    (staging_root / "README.md").write_text(ROOT_README, encoding="utf-8")


def write_archive_manifest(staging_root: Path, bundles: list[dict[str, Any]]) -> None:
    manifest = {
        "schema_version": 1,
        "archive": staging_root.name,
        "bundle_count": len(bundles),
        "bundles": [
            {
                "case_name": bundle["case_name"],
                "operator": bundle["operator"],
                "check": bundle["check"],
                "runtime_files": bundle["runtime_files"],
            }
            for bundle in bundles
        ],
    }
    write_json(staging_root / "manifest.json", manifest)


def write_bundle_readme(bundle_dir: Path, case_name: str, check_mode: str) -> None:
    (bundle_dir / "README.md").write_text(
        f"""# {case_name} SimICT Bundle

This bundle contains OpenFabric-generated accelerator runtime blobs.
It also contains `riscv_case/`, the minimal legacy RISC-V control source used
by the archive runner when `config/riscv_program` is not prebuilt.

Run from the archive root:

```sh
./run_all_bundles.sh /path/to/simict3500final
```

Check mode: `{check_mode}`.
""",
        encoding="utf-8",
    )


def manifest_files(root: Path) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    if not root.exists():
        return result
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rel = path.relative_to(root).as_posix()
        result[rel] = {
            "size": path.stat().st_size,
            "sha256": sha256_file(path),
        }
    return result


def write_json(path: Path, value: Any) -> None:
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_executable(path: Path, content: str) -> None:
    path.write_text(content.lstrip(), encoding="utf-8")
    mode = path.stat().st_mode
    path.chmod(mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)


def copy_file(src: Path, dst: Path) -> None:
    assert_file(src)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)


def assert_file(path: Path) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise SystemExit(f"missing or empty file: {path}")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def safe_name(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in value).strip("._-")


ROOT_README = """# OpenFabric SimICT Test Bundles

Place this extracted directory next to `simict3500final`, or pass the SimICT
root explicitly:

```sh
./run_all_bundles.sh ../simict3500final
```

Or upload to the customer machine from this extracted directory:

```sh
./upload_and_run_remote.sh
```

The remote helper is intended to run on the first Linux hop after copying this
archive from the Windows cloud desktop. By default it uploads to
`huake02@arch-13`, runs the bundle under
`/project/home-new/huake02/simict3500final`, and copies `run_out` back into
local `remote_out/<timestamp>/`. Use `./upload_and_run_remote.sh --upload-only`
for manual remote debugging.

It uses plain interactive `ssh`/`scp`, so enter the `huake02@arch-13` password
whenever prompted.

The runner installs each `bundles/<case>/config` into the SimICT runtime work
directory, builds the bundled RISC-V control program with the customer's
toolchain when `riscv_program` is not already present, runs the closed runtime,
collects `run.log`, traces, stats and `gpdpu_data`, then runs the bundle checker
when available.

This archive intentionally skips accelerator binary generation. It tests the
OpenFabric binary artifacts already present in the bundle.
"""


UPLOAD_AND_RUN_REMOTE_SH = r"""#!/usr/bin/env bash
set -euo pipefail

UPLOAD_HELPER_VERSION="2026-06-15-upload-legacy-compare"
REMOTE_ACTION="run"
if [[ "${1:-}" == "--upload-only" ]]; then
  REMOTE_ACTION="upload-only"
  shift
elif [[ "${1:-}" == "--legacy-compare" ]]; then
  REMOTE_ACTION="legacy-compare"
  shift
elif [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  cat <<'EOF_USAGE'
Usage:
  ./upload_and_run_remote.sh                  # upload, run remotely, and collect run_out
  ./upload_and_run_remote.sh --upload-only    # upload only, then print manual commands
  ./upload_and_run_remote.sh --legacy-compare # upload, run customer legacy GEMM workflow, compare artifacts, collect logs
EOF_USAGE
  exit 0
elif [[ "$#" -gt 0 ]]; then
  echo "ERROR: unknown argument: $1" >&2
  exit 1
fi

ARCHIVE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ARCHIVE_NAME="$(basename "${ARCHIVE_ROOT}")"

REMOTE_USER="${SIMICT_REMOTE_USER:-huake02}"
REMOTE_HOST="${SIMICT_REMOTE_HOST:-arch-13}"
REMOTE="${REMOTE_USER}@${REMOTE_HOST}"
REMOTE_SIMICT_ROOT="${SIMICT_REMOTE_SIMICT_ROOT:-/project/home-new/huake02/simict3500final}"
REMOTE_BASE="${SIMICT_REMOTE_BASE:-/project/home-new/huake02/openfabric_test_bundles}"
RUN_ID="${SIMICT_REMOTE_RUN_ID:-$(date +%Y%m%d_%H%M%S)}"
REMOTE_DIR="${REMOTE_BASE}/${ARCHIVE_NAME}_${RUN_ID}"
LOCAL_OUT="${SIMICT_REMOTE_LOCAL_OUT:-${ARCHIVE_ROOT}/remote_out/${RUN_ID}}"
KEEP_REMOTE="${SIMICT_REMOTE_KEEP:-1}"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

need_cmd() {
  command -v "$1" >/dev/null || die "missing command: $1"
}

ssh_base_args=(
  -o StrictHostKeyChecking=no
  -o UserKnownHostsFile="${SIMICT_REMOTE_KNOWN_HOSTS:-${HOME}/.ssh/known_hosts}"
)

if [[ -n "${SIMICT_REMOTE_SSH_OPTS:-}" ]]; then
  # shellcheck disable=SC2206
  extra_ssh_opts=(${SIMICT_REMOTE_SSH_OPTS})
  ssh_base_args+=("${extra_ssh_opts[@]}")
fi

ssh_cmd=(ssh "${ssh_base_args[@]}")
scp_cmd=(scp "${ssh_base_args[@]}")

need_cmd tar
need_cmd ssh
need_cmd scp

mkdir -p "${LOCAL_OUT}"
LOCAL_BUNDLE_TGZ="$(mktemp "${TMPDIR:-/tmp}/${ARCHIVE_NAME}.upload.XXXXXX.tar.gz")"
REMOTE_LOG="${LOCAL_OUT}/remote_run.log"
REMOTE_RESULT_TGZ="${LOCAL_OUT}/remote_run_out.tar.gz"
REMOTE_COMPARE_LOG="${LOCAL_OUT}/remote_legacy_compare.log"
REMOTE_COMPARE_TGZ="${LOCAL_OUT}/remote_legacy_compare.tar.gz"
cleanup() {
  rm -f "${LOCAL_BUNDLE_TGZ}"
}
trap cleanup EXIT

echo "remote=${REMOTE}"
echo "remote_dir=${REMOTE_DIR}"
echo "remote_simict_root=${REMOTE_SIMICT_ROOT}"
echo "local_out=${LOCAL_OUT}"
echo "remote_action=${REMOTE_ACTION}"
echo "OpenFabric upload helper version: ${UPLOAD_HELPER_VERSION}"

tar \
  --exclude="${ARCHIVE_NAME}/run_out" \
  --exclude="${ARCHIVE_NAME}/remote_out" \
  -czf "${LOCAL_BUNDLE_TGZ}" \
  -C "${ARCHIVE_ROOT}/.." \
  "${ARCHIVE_NAME}"

"${ssh_cmd[@]}" "${REMOTE}" "mkdir -p '${REMOTE_BASE}' && rm -rf '${REMOTE_DIR}'"
"${scp_cmd[@]}" "${LOCAL_BUNDLE_TGZ}" "${REMOTE}:${REMOTE_BASE}/${ARCHIVE_NAME}_${RUN_ID}.tar.gz"
"${ssh_cmd[@]}" "${REMOTE}" "cd '${REMOTE_BASE}' && tar -xzf '${ARCHIVE_NAME}_${RUN_ID}.tar.gz' && mv '${ARCHIVE_NAME}' '${REMOTE_DIR}'"
"${ssh_cmd[@]}" "${REMOTE}" "cd '${REMOTE_DIR}' && grep -n 'RUNNER_VERSION=' run_all_bundles.sh || true"

cat <<EOF_NEXT

Upload complete.

Remote bundle directory:
  ${REMOTE_DIR}

Manual debug commands:
  ssh ${REMOTE}
  cd '${REMOTE_DIR}'
  ./run_all_bundles.sh '${REMOTE_SIMICT_ROOT}' 2>&1 | tee run_manual.log

Manual legacy compare commands:
  ssh ${REMOTE}
  cd '${REMOTE_DIR}'
  ./scripts/run_remote_legacy_gemm_and_compare.sh '${REMOTE_SIMICT_ROOT}' bundles/gemm 2>&1 | tee run_legacy_compare_manual.log

After manual run, collect results from first Linux with:
  scp -r '${REMOTE}:${REMOTE_DIR}/run_out' '${LOCAL_OUT}/'

For upload-only debug mode:
  ./upload_and_run_remote.sh --upload-only

EOF_NEXT

if [[ "${REMOTE_ACTION}" == "upload-only" ]]; then
  exit 0
fi

set +e
if [[ "${REMOTE_ACTION}" == "legacy-compare" ]]; then
  "${ssh_cmd[@]}" "${REMOTE}" "cd '${REMOTE_DIR}' && ./scripts/run_remote_legacy_gemm_and_compare.sh '${REMOTE_SIMICT_ROOT}' bundles/gemm" 2>&1 | tee "${REMOTE_COMPARE_LOG}"
else
  "${ssh_cmd[@]}" "${REMOTE}" "cd '${REMOTE_DIR}' && ./run_all_bundles.sh '${REMOTE_SIMICT_ROOT}'" 2>&1 | tee "${REMOTE_LOG}"
fi
run_status=${PIPESTATUS[0]}
set -e

set +e
if [[ "${REMOTE_ACTION}" == "legacy-compare" ]]; then
  "${ssh_cmd[@]}" "${REMOTE}" "cd '${REMOTE_DIR}' && tar -czf - run_out/legacy_compare manifest.json bundles/*/manifest.json README.md scripts/compare_remote_legacy_gemm.sh scripts/run_remote_legacy_gemm_and_compare.sh 2>/dev/null" > "${REMOTE_COMPARE_TGZ}"
else
  "${ssh_cmd[@]}" "${REMOTE}" "cd '${REMOTE_DIR}' && tar -czf - run_out manifest.json bundles/*/manifest.json README.md 2>/dev/null" > "${REMOTE_RESULT_TGZ}"
fi
collect_status=$?
set -e
if [[ "${REMOTE_ACTION}" == "legacy-compare" && "${collect_status}" -eq 0 && -s "${REMOTE_COMPARE_TGZ}" ]]; then
  mkdir -p "${LOCAL_OUT}/remote_legacy_compare"
  tar -xzf "${REMOTE_COMPARE_TGZ}" -C "${LOCAL_OUT}/remote_legacy_compare"
  echo "collected remote legacy compare outputs into ${LOCAL_OUT}/remote_legacy_compare"
elif [[ "${REMOTE_ACTION}" != "legacy-compare" && "${collect_status}" -eq 0 && -s "${REMOTE_RESULT_TGZ}" ]]; then
  mkdir -p "${LOCAL_OUT}/remote_result"
  tar -xzf "${REMOTE_RESULT_TGZ}" -C "${LOCAL_OUT}/remote_result"
  echo "collected remote outputs into ${LOCAL_OUT}/remote_result"
else
  echo "WARN: failed to collect remote output archive; see ${REMOTE_LOG} or ${REMOTE_COMPARE_LOG}" >&2
fi

if [[ "${KEEP_REMOTE}" == "0" ]]; then
  "${ssh_cmd[@]}" "${REMOTE}" "rm -rf '${REMOTE_DIR}' '${REMOTE_BASE}/${ARCHIVE_NAME}_${RUN_ID}.tar.gz'" || true
fi

echo "remote exit status: ${run_status}"
exit "${run_status}"
"""


RUN_ALL_BUNDLES_SH = r"""#!/usr/bin/env bash
set -euo pipefail

RUNNER_VERSION="2026-06-15-legacy-root-runtime-layout"
ARCHIVE_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SIMICT_ROOT="${1:-${ARCHIVE_ROOT}/../simict3500final}"
NO_CHECK="${NO_CHECK:-0}"
SIMICT_RUNTIME_LAYOUT="${SIMICT_RUNTIME_LAYOUT:-legacy_root}"

RISC_ROOT="${SIMICT_ROOT}/gpdpu/users/risc_nn_riscv"
TC_ROOT="${RISC_ROOT}/testcase"
RUNTIME="${SIMICT_ROOT}/gpdpu/core/bin/runtime"

die() {
  echo "ERROR: $*" >&2
  exit 1
}

assert_file() {
  [[ -s "$1" ]] || die "missing or empty file: $1"
}

copy_tree_if_exists() {
  local src="$1"
  local dst="$2"
  if [[ -e "${src}" ]]; then
    rm -rf "${dst}"
    cp -a "${src}" "${dst}"
  fi
}

reset_dir() {
  local path="$1"
  local cleanup_root="${2:-}"
  if [[ -e "${path}" ]]; then
    if [[ -n "${cleanup_root}" ]]; then
      mkdir -p "${cleanup_root}"
      local name
      name="$(basename "${path}")"
      local old="${cleanup_root}/${name}.$(date +%Y%m%d_%H%M%S).$$"
      if mv "${path}" "${old}" 2>/dev/null; then
        (rm -rf "${old}" 2>/dev/null || true) &
      else
        rm -rf "${path}" 2>/dev/null || true
      fi
    else
      rm -rf "${path}" 2>/dev/null || true
    fi
  fi
  mkdir -p "${path}"
}

append_customer_toolchain_paths() {
  local tool_home="$1"
  local fake_root="${tool_home}/fake_root_5.1"
  [[ -d "${fake_root}" ]] || return 0
  export PATH="${fake_root}/gcc/bin:${PATH}:${fake_root}/m4/bin:${fake_root}/automake/bin:${fake_root}/autoconf/bin:${fake_root}/libtool/bin:${fake_root}/readline/bin"
  export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:${fake_root}/gcc/lib:${fake_root}/gmp/lib:${fake_root}/mpc/lib:${fake_root}/mpfr/lib:${fake_root}/m4/lib:${fake_root}/automake/lib:${fake_root}/autoconf/lib:${fake_root}/libtool/lib:${fake_root}/readline/lib:${fake_root}/gcc/lib64"
  export C_INCLUDE_PATH="${fake_root}/gcc/include:${C_INCLUDE_PATH:-}:${fake_root}/mpfr/include:${fake_root}/gmp/include:${fake_root}/m4/include:${fake_root}/automake/include:${fake_root}/autoconf/include:${fake_root}/libtool/include:${fake_root}/readline/include"
}

setup_customer_toolchain() {
  if [[ -n "${SIMICT_TOOL_HOME:-}" ]]; then
    append_customer_toolchain_paths "${SIMICT_TOOL_HOME}"
  elif [[ -d "${HOME:-}/fake_root_5.1" ]]; then
    append_customer_toolchain_paths "${HOME}"
  elif [[ -d "/project/home-new/huake02/fake_root_5.1" ]]; then
    append_customer_toolchain_paths "/project/home-new/huake02"
  elif [[ -d "/project/home-new/huake01/fake_root_5.1" ]]; then
    append_customer_toolchain_paths "/project/home-new/huake01"
  fi
  command -v riscv64-unknown-elf-gcc >/dev/null || die "riscv64-unknown-elf-gcc not found; set SIMICT_TOOL_HOME to the directory that contains fake_root_5.1"
  command -v riscv64-unknown-elf-objdump >/dev/null || die "riscv64-unknown-elf-objdump not found; set SIMICT_TOOL_HOME to the directory that contains fake_root_5.1"
}

build_bundle_riscv_program() {
  local bundle_dir="$1"
  local pkg_root="$2"
  local pkg_config="$3"

  if [[ -s "${pkg_config}/riscv_program" ]]; then
    return 0
  fi
  [[ -d "${bundle_dir}/riscv_case/riscv" ]] || die "bundle has no riscv_program or riscv_case source: ${bundle_dir}"

  cp -a "${bundle_dir}/riscv_case/." "${pkg_root}/"
  (
    cd "${pkg_root}/riscv"
    make -f makefile
  )
  assert_file "${pkg_root}/riscv/riscv"
  cp "${pkg_root}/riscv/riscv" "${pkg_config}/riscv_program"
}

link_runtime_dependencies() {
  local runtime_work="$1"
  local dep
  for dep in "${RISC_ROOT}"/*; do
    local name
    name="$(basename "${dep}")"
    case "${name}" in
      config|log|stat|rtl_trace|sim_trace|gpdpu_data|testcase)
        continue
        ;;
    esac
    ln -sfn "${dep}" "${runtime_work}/${name}"
  done
}

[[ -d "${SIMICT_ROOT}" ]] || die "simict root not found: ${SIMICT_ROOT}"
[[ -d "${RISC_ROOT}" ]] || die "risc root not found: ${RISC_ROOT}"
[[ -x "${RUNTIME}" ]] || die "runtime not executable: ${RUNTIME}"
assert_file "${RISC_ROOT}/top.so"
assert_file "${RISC_ROOT}/topPara.so"
assert_file "${RISC_ROOT}/common/src/libcommon.so"
setup_customer_toolchain
echo "OpenFabric runner version: ${RUNNER_VERSION}"
echo "OpenFabric runtime layout: ${SIMICT_RUNTIME_LAYOUT}"

mkdir -p "${ARCHIVE_ROOT}/run_out" "${TC_ROOT}/runtime_packages"

total=0
passed=0
failed=0

for bundle_dir in "${ARCHIVE_ROOT}"/bundles/*; do
  [[ -d "${bundle_dir}" ]] || continue
  case_name="$(basename "${bundle_dir}")"
  total=$((total + 1))
  echo "===== ${case_name} ====="

  pkg_root="${TC_ROOT}/runtime_packages/${case_name}"
  pkg_config="${pkg_root}/config"
  reset_dir "${pkg_root}" "${TC_ROOT}/runtime_packages/.openfabric_cleanup"
  mkdir -p "${pkg_config}"
  cp "${bundle_dir}/config/"* "${pkg_config}/"

  build_bundle_riscv_program "${bundle_dir}" "${pkg_root}" "${pkg_config}"

  assert_file "${pkg_config}/cbuf_file.bin"
  assert_file "${pkg_config}/micc_file.bin"
  assert_file "${pkg_config}/input_data.bin"
  assert_file "${pkg_config}/riscv_program"

  run_out="${ARCHIVE_ROOT}/run_out/${case_name}"
  reset_dir "${run_out}"
  case "${SIMICT_RUNTIME_LAYOUT}" in
    legacy_root)
      runtime_work="${RISC_ROOT}"
      reset_dir "${RISC_ROOT}/config" "${TC_ROOT}/runtime_packages/.openfabric_cleanup/risc_root"
      reset_dir "${RISC_ROOT}/log" "${TC_ROOT}/runtime_packages/.openfabric_cleanup/risc_root"
      reset_dir "${RISC_ROOT}/stat" "${TC_ROOT}/runtime_packages/.openfabric_cleanup/risc_root"
      reset_dir "${RISC_ROOT}/rtl_trace" "${TC_ROOT}/runtime_packages/.openfabric_cleanup/risc_root"
      reset_dir "${RISC_ROOT}/sim_trace" "${TC_ROOT}/runtime_packages/.openfabric_cleanup/risc_root"
      mkdir -p "${RISC_ROOT}/sim_trace/cycle_trace" "${RISC_ROOT}/sim_trace/checkpoint"
      cp "${pkg_config}/"* "${RISC_ROOT}/config/"
      (
        cd "${RISC_ROOT}"
        assert_file "mem/libmem.so"
        echo "runtime_work=$(pwd)"
        echo "libmem=$(readlink -f mem/libmem.so 2>/dev/null || echo mem/libmem.so)"
        ls -l mem mem/libmem.so
        export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:${RISC_ROOT}/common/src/:${RISC_ROOT}/mem"
        echo "OpenFabric phase: runtime start ${case_name}"
        "${RUNTIME}" "${RISC_ROOT}/" top.so topPara.so common/src/libcommon.so 2>&1 | tee "${run_out}/run.log"
        echo "OpenFabric phase: runtime end ${case_name}"
      )
      ;;
    isolated)
      runtime_work="${pkg_root}/runtime_work"
      reset_dir "${runtime_work}" "${pkg_root}/.openfabric_cleanup"
      (
        cd "${runtime_work}"
        mkdir -p config log stat rtl_trace sim_trace sim_trace/cycle_trace sim_trace/checkpoint
        cp "${pkg_config}/"* config/
        link_runtime_dependencies "${runtime_work}"
        assert_file "${runtime_work}/mem/libmem.so"
        echo "runtime_work=$(pwd)"
        echo "libmem=$(readlink -f mem/libmem.so 2>/dev/null || echo mem/libmem.so)"
        ls -l mem mem/libmem.so
        export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:${RISC_ROOT}/common/src/:${RISC_ROOT}/mem:${runtime_work}/common/src:${runtime_work}/mem"
        echo "OpenFabric phase: runtime start ${case_name}"
        "${RUNTIME}" "${runtime_work}/" top.so topPara.so common/src/libcommon.so 2>&1 | tee "${run_out}/run.log"
        echo "OpenFabric phase: runtime end ${case_name}"
      )
      ;;
    *)
      die "unknown SIMICT_RUNTIME_LAYOUT=${SIMICT_RUNTIME_LAYOUT}; expected legacy_root or isolated"
      ;;
  esac

  echo "OpenFabric phase: collect traces start ${case_name}"
  copy_tree_if_exists "${runtime_work}/stat" "${run_out}/stat"
  copy_tree_if_exists "${runtime_work}/rtl_trace" "${run_out}/rtl_trace"
  copy_tree_if_exists "${runtime_work}/sim_trace" "${run_out}/sim_trace"
  if [[ -s "${runtime_work}/gpdpu_data" ]]; then
    cp "${runtime_work}/gpdpu_data" "${run_out}/gpdpu_data"
  fi
  echo "OpenFabric phase: collect traces end ${case_name}"

  if [[ "${NO_CHECK}" != "1" && -x "${ARCHIVE_ROOT}/scripts/run_check.sh" && -f "${bundle_dir}/check/result_check.c" ]]; then
    echo "OpenFabric phase: check start ${case_name}"
    if "${ARCHIVE_ROOT}/scripts/run_check.sh" "${bundle_dir}" "${run_out}/gpdpu_data" "${run_out}/check"; then
      echo "check passed: ${case_name}"
    else
      echo "check failed: ${case_name}" >&2
      failed=$((failed + 1))
      continue
    fi
    echo "OpenFabric phase: check end ${case_name}"
  fi

  echo "OpenFabric phase: case done ${case_name}"
  passed=$((passed + 1))
done

cat > "${ARCHIVE_ROOT}/run_out/summary.txt" <<EOF_SUMMARY
total=${total}
passed=${passed}
failed=${failed}
EOF_SUMMARY

cat "${ARCHIVE_ROOT}/run_out/summary.txt"
[[ "${failed}" -eq 0 ]]
"""


RUN_CHECK_SH = r"""#!/usr/bin/env bash
set -euo pipefail

BUNDLE_DIR="${1:?bundle dir required}"
GPDPU_DATA="${2:?gpdpu_data required}"
OUT_DIR="${3:?out dir required}"

assert_file() {
  [[ -s "$1" ]] || {
    echo "ERROR: missing or empty file: $1" >&2
    exit 1
  }
}

assert_file "${BUNDLE_DIR}/config/input_data.bin"
assert_file "${GPDPU_DATA}"

rm -rf "${OUT_DIR}"
mkdir -p "${OUT_DIR}/case/spm_data" "${OUT_DIR}/case/csv_generate"
cp "${BUNDLE_DIR}/config/input_data.bin" "${OUT_DIR}/case/input_data.bin"
cp "${GPDPU_DATA}" "${OUT_DIR}/case/spm_data/gpdpu_data"
cp "${BUNDLE_DIR}/check/result_check.c" "${OUT_DIR}/case/spm_data/result_check.c"
cp "${BUNDLE_DIR}/check/spm_data/data.h" "${OUT_DIR}/case/spm_data/data.h"
cp "${BUNDLE_DIR}/check/csv_generate/conf.h" "${OUT_DIR}/case/csv_generate/conf.h"

include_flags=()
lib_flags=()
if [[ -d "${HOME}/fake_root_5.1/gmp" ]]; then
  include_flags+=("-I" "${HOME}/fake_root_5.1/gmp/include")
  lib_flags+=("-L" "${HOME}/fake_root_5.1/gmp/lib")
fi
if [[ -d "${HOME}/fake_root_5.1/mpfr" ]]; then
  include_flags+=("-I" "${HOME}/fake_root_5.1/mpfr/include")
  lib_flags+=("-L" "${HOME}/fake_root_5.1/mpfr/lib")
fi
lib_flags+=("-lgmp" "-lmpfr" "-lm")

(
  cd "${OUT_DIR}/case/spm_data"
  g++ "${include_flags[@]}" result_check.c -o result "${lib_flags[@]}"
  set +e
  ./result > "${OUT_DIR}/check.log" 2>&1
  status=$?
  set -e
  echo "result_check_exit=${status}" >> "${OUT_DIR}/check.log"
)

if grep -q "Result Error" "${OUT_DIR}/check.log"; then
  exit 1
fi
"""


COMPARE_REMOTE_LEGACY_GEMM_SH = r"""#!/usr/bin/env bash
set -euo pipefail

SIMICT_ROOT="${1:-/project/home-new/huake02/simict3500final}"
BUNDLE_DIR="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/bundles/gemm}"
RISC_ROOT="${SIMICT_ROOT}/gpdpu/users/risc_nn_riscv"

need_cmd() {
  command -v "$1" >/dev/null || {
    echo "ERROR: missing command: $1" >&2
    exit 1
  }
}

sha() {
  local path="$1"
  if [[ -s "${path}" ]]; then
    sha256sum "${path}" | awk '{print $1}'
  else
    echo "MISSING"
  fi
}

size() {
  local path="$1"
  if [[ -s "${path}" ]]; then
    wc -c < "${path}" | tr -d ' '
  else
    echo "MISSING"
  fi
}

compare_pair() {
  local label="$1"
  local ours="$2"
  local theirs="$3"
  local ours_sha theirs_sha ours_size theirs_size
  ours_sha="$(sha "${ours}")"
  theirs_sha="$(sha "${theirs}")"
  ours_size="$(size "${ours}")"
  theirs_size="$(size "${theirs}")"
  if [[ "${theirs_sha}" == "MISSING" ]]; then
    printf 'SKIP  %-40s remote artifact missing: %s\n' "${label}" "${theirs}"
    return 0
  fi
  if [[ "${ours_sha}" == "${theirs_sha}" && "${ours_sha}" != "MISSING" ]]; then
    printf 'MATCH %-40s size=%s sha=%s\n' "${label}" "${ours_size}" "${ours_sha}"
  else
    printf 'DIFF  %-40s ours_size=%s theirs_size=%s ours_sha=%s theirs_sha=%s\n' \
      "${label}" "${ours_size}" "${theirs_size}" "${ours_sha}" "${theirs_sha}"
    return 1
  fi
}

compare_case_dir() {
  local label="$1"
  local case_dir="$2"
  local status=0
  echo
  echo "=== ${label}: ${case_dir} ==="
  if [[ ! -d "${case_dir}" ]]; then
    echo "SKIP: directory not found"
    return 0
  fi

  compare_pair "config/cbuf_file.bin" \
    "${BUNDLE_DIR}/config/cbuf_file.bin" \
    "${case_dir}/result/cbuf_file.bin" || status=1
  compare_pair "config/micc_file.bin" \
    "${BUNDLE_DIR}/config/micc_file.bin" \
    "${case_dir}/result/micc_file.bin" || status=1

  for name in \
    insts_file.bin \
    exeblock_conf_info_file.bin \
    instance_conf_info_file.bin \
    tasks_conf_info_file.bin \
    subtasks_conf_info_file.bin
  do
    compare_pair "simulator_bin/${name}" \
      "${BUNDLE_DIR}/simulator_bin/${name}" \
      "${case_dir}/simulator_bin/${name}" || status=1
  done

  if [[ -s "${case_dir}/input_data.bin" ]]; then
    compare_pair "config/input_data.bin" \
      "${BUNDLE_DIR}/config/input_data.bin" \
      "${case_dir}/input_data.bin" || status=1
  else
    echo "SKIP input_data.bin: ${case_dir}/input_data.bin not found"
  fi

  return "${status}"
}

need_cmd sha256sum
need_cmd awk
need_cmd wc

echo "simict_root=${SIMICT_ROOT}"
echo "bundle_dir=${BUNDLE_DIR}"
[[ -d "${RISC_ROOT}" ]] || {
  echo "ERROR: RISC root not found: ${RISC_ROOT}" >&2
  exit 1
}
[[ -d "${BUNDLE_DIR}" ]] || {
  echo "ERROR: bundle dir not found: ${BUNDLE_DIR}" >&2
  exit 1
}

status=0
compare_case_dir \
  "application/gemm_template_fusion" \
  "${RISC_ROOT}/testcase/application/gemm_template_fusion" || status=1
compare_case_dir \
  "build_out/gemm_template_fusion worktree" \
  "${RISC_ROOT}/testcase/build_out/gemm_template_fusion/worktree/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion" || status=1

echo
if [[ "${status}" -eq 0 ]]; then
  echo "legacy_compare=all_found_artifacts_match"
else
  echo "legacy_compare=diff_found"
fi
exit "${status}"
"""


RUN_REMOTE_LEGACY_GEMM_AND_COMPARE_SH = r"""#!/usr/bin/env bash
set -euo pipefail

SIMICT_ROOT="${1:-/project/home-new/huake02/simict3500final}"
BUNDLE_DIR="${2:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/bundles/gemm}"
OUT_DIR="${3:-$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/run_out/legacy_compare}"
APP_NAME="${SIMICT_LEGACY_APP_NAME:-gemm_template_fusion}"
DUPLICATE_AMOUNT="${SIMICT_LEGACY_DUPLICATE_AMOUNT:-4}"

RISC_ROOT="${SIMICT_ROOT}/gpdpu/users/risc_nn_riscv"
RUN_SCRIPT="${RISC_ROOT}/test/run_app_riscv.sh"
COMPARE_SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/compare_remote_legacy_gemm.sh"
APP_DIR="${RISC_ROOT}/testcase/application/${APP_NAME}"

echo "simict_root=${SIMICT_ROOT}"
echo "bundle_dir=${BUNDLE_DIR}"
echo "out_dir=${OUT_DIR}"
echo "legacy_app=${APP_NAME}"
echo "duplicate_amount=${DUPLICATE_AMOUNT}"

[[ -x "${RUN_SCRIPT}" ]] || {
  echo "ERROR: legacy run script not executable: ${RUN_SCRIPT}" >&2
  exit 1
}
[[ -d "${APP_DIR}" ]] || {
  echo "ERROR: legacy application directory not found: ${APP_DIR}" >&2
  echo "Expected remote case at testcase/application/${APP_NAME}, not CASE/${APP_NAME}." >&2
  exit 1
}
[[ -d "${BUNDLE_DIR}" ]] || {
  echo "ERROR: bundle dir not found: ${BUNDLE_DIR}" >&2
  exit 1
}

mkdir -p "${OUT_DIR}"

echo
echo "=== run original customer workflow ==="
(
  cd "${RISC_ROOT}/test"
  ./run_app_riscv.sh "${APP_NAME}" "${DUPLICATE_AMOUNT}"
) 2>&1 | tee "${OUT_DIR}/legacy_run_app_riscv.log"

echo
echo "=== compare OpenFabric bundle against freshly generated remote legacy artifacts ==="
"${COMPARE_SCRIPT}" "${SIMICT_ROOT}" "${BUNDLE_DIR}" 2>&1 | tee "${OUT_DIR}/legacy_compare.log"

echo
echo "legacy diagnostics written to ${OUT_DIR}"
"""


if __name__ == "__main__":
    main()
