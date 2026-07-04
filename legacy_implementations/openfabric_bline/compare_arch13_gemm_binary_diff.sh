#!/usr/bin/env bash
set -euo pipefail

REMOTE_USER="${SIMICT_REMOTE_USER:-huake01}"
REMOTE_HOST="${SIMICT_REMOTE_HOST:-arch-13}"
REMOTE="${REMOTE_USER}@${REMOTE_HOST}"
SIMICT_ROOT="${SIMICT_REMOTE_SIMICT_ROOT:-/project/home-new/huake01/simict3500final}"
BUNDLE_DIR="${SIMICT_BUNDLE_DIR:-}"
OUT_DIR="${SIMICT_DIFF_OUT:-./arch13_gemm_binary_diff_$(date +%Y%m%d_%H%M%S)}"

usage() {
  cat <<'EOF'
Usage:
  ./compare_arch13_gemm_binary_diff.sh [REMOTE_BUNDLE_DIR]

Run this on the first-hop Linux machine. It ssh'es to arch-13 and compares
OpenFabric GEMM bundle binaries against arch-13's freshly generated legacy
gemm_template_fusion binaries.

Arguments:
  REMOTE_BUNDLE_DIR
    Path on arch-13 to the extracted openfabric_simict_test_bundles directory.
    If omitted, set SIMICT_BUNDLE_DIR.

Environment:
  SIMICT_REMOTE_USER        default: huake01
  SIMICT_REMOTE_HOST        default: arch-13
  SIMICT_REMOTE_SIMICT_ROOT default: /project/home-new/huake01/simict3500final
  SIMICT_DIFF_OUT           default: ./arch13_gemm_binary_diff_<timestamp>
  SIMICT_REMOTE_SSH_OPTS    optional extra ssh options

Examples:
  ./compare_arch13_gemm_binary_diff.sh /project/home-new/huake01/openfabric_test_bundles/openfabric_simict_test_bundles_20260615_123456

  SIMICT_BUNDLE_DIR=/project/home-new/huake01/openfabric_test_bundles/openfabric_simict_test_bundles_xxx \
    ./compare_arch13_gemm_binary_diff.sh
EOF
}

if [[ "${1:-}" == "--help" || "${1:-}" == "-h" ]]; then
  usage
  exit 0
fi
if [[ $# -gt 1 ]]; then
  usage >&2
  exit 1
fi
if [[ $# -eq 1 ]]; then
  BUNDLE_DIR="$1"
fi
if [[ -z "${BUNDLE_DIR}" ]]; then
  echo "ERROR: REMOTE_BUNDLE_DIR argument or SIMICT_BUNDLE_DIR is required." >&2
  usage >&2
  exit 1
fi

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

mkdir -p "${OUT_DIR}"
REMOTE_REPORT="/tmp/openfabric_gemm_binary_diff_${USER:-user}_$$.txt"
REMOTE_SCRIPT="/tmp/openfabric_gemm_binary_diff_${USER:-user}_$$.py"
LOCAL_REPORT="${OUT_DIR}/gemm_binary_diff_report.txt"

cleanup_remote() {
  "${ssh_cmd[@]}" "${REMOTE}" "rm -f '${REMOTE_SCRIPT}' '${REMOTE_REPORT}'" >/dev/null 2>&1 || true
}
trap cleanup_remote EXIT

echo "remote=${REMOTE}"
echo "simict_root=${SIMICT_ROOT}"
echo "bundle_dir=${BUNDLE_DIR}"
echo "out_dir=${OUT_DIR}"

"${ssh_cmd[@]}" "${REMOTE}" "cat > '${REMOTE_SCRIPT}'" <<'PY'
import hashlib
import os
import struct
import sys
from collections import Counter
from pathlib import Path


SIMICT_ROOT = Path(os.environ["SIMICT_ROOT"])
BUNDLE_ROOT = Path(os.environ["BUNDLE_DIR"])
OURS_ROOT = BUNDLE_ROOT / "bundles/gemm"
LEGACY_ROOT = (
    SIMICT_ROOT
    / "gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion"
)

COMPONENTS = [
    ("tasks", "simulator_bin/tasks_conf_info_file.bin", 120),
    ("subtasks", "simulator_bin/subtasks_conf_info_file.bin", 266328),
    ("exeblocks", "simulator_bin/exeblock_conf_info_file.bin", 520),
    ("insts", "simulator_bin/insts_file.bin", 304),
    ("instances", "simulator_bin/instance_conf_info_file.bin", 32),
    ("cbuf", "config/cbuf_file.bin", None),
    ("micc", "config/micc_file.bin", None),
    ("input", "config/input_data.bin", None),
]

OP_NAMES = {
    0x22: "IMM",
    0x40: "LDN",
    0x52: "HMUL",
    0x80: "STD",
    0xC0: "COPY",
    0xCE: "RXINT",
    0xCF: "TRCTT",
    0xE1: "HMMAL",
}


def sha16(data):
    return hashlib.sha256(data).hexdigest()[:16]


def read(path):
    if not path.is_file():
        return None
    return path.read_bytes()


def first_diff_offset(a, b):
    for index, (left, right) in enumerate(zip(a, b)):
        if left != right:
            return index
    return min(len(a), len(b))


def u64(row, offset):
    return struct.unpack_from("<Q", row, offset)[0]


def i32(row, offset):
    return struct.unpack_from("<i", row, offset)[0]


def summarize_tasks(row):
    fields = struct.unpack_from("<BB6xQ8Q4Q", row, 0)
    return {
        "start": fields[0],
        "end": fields[1],
        "subtask_amount": fields[2],
        "subtasks": fields[3:11],
        "successors": fields[11:15],
    }


def summarize_subtask(row):
    header = struct.unpack_from("<BB6xQQ4QQQ", row, 0)
    tail = struct.unpack_from("<QQ", row, 266328 - 16)
    return {
        "start": header[0],
        "end": header[1],
        "instances": header[2],
        "instance_conf_addr": header[3],
        "successors": header[4:8],
        "root_blocks": header[8],
        "valid_exeblocks": header[9],
        "subtask_idx_tail": tail[0],
        "task_idx_tail": tail[1],
    }


def summarize_exeblock(row):
    prefix = struct.unpack_from("<B7xQ3QQ", row, 0)
    base = struct.calcsize("<B7xQ3QQ")
    body = struct.unpack_from("<Q5B3x5Q", row, base)
    taskish = struct.unpack_from("<11QB7x", row, base + 376)
    return {
        "valid": prefix[0],
        "block_idx_prefix": prefix[1],
        "pe": prefix[2:5],
        "req_activations": body[0],
        "has_stages": body[1:6],
        "stage_start_pc": body[6:11],
        "block_idx": taskish[0],
        "subtask_idx": taskish[1],
        "task_idx": taskish[2],
        "instances": taskish[3],
        "child_amount": taskish[4],
        "inst_mem_addr": taskish[6],
        "stage_counts": taskish[7:12],
    }


def summarize_inst(row):
    opcode = i32(row, 0)
    return {
        "op": OP_NAMES.get(opcode, hex(opcode)),
        "opcode": opcode,
        "unit": u64(row, 8),
        "latency": u64(row, 16),
        "imm": (u64(row, 24), u64(row, 32), u64(row, 40)),
        "src": (u64(row, 48), u64(row, 56), u64(row, 64)),
        "dst": (u64(row, 72), u64(row, 80), u64(row, 88)),
        "dst_pe0": (u64(row, 96), u64(row, 104), u64(row, 112)),
        "dst_blocks": (u64(row, 168), u64(row, 176), u64(row, 184)),
        "fwd": (u64(row, 192), u64(row, 200), u64(row, 208)),
        "bypass": (u64(row, 216), u64(row, 224), u64(row, 232)),
        "base": u64(row, 240),
        "iter": u64(row, 248),
        "block": u64(row, 256),
        "flow_ack": u64(row, 264),
        "end": row[272],
        "extra": (u64(row, 280), u64(row, 288), u64(row, 296)),
    }


def field_summary(name, row):
    if name == "tasks":
        return summarize_tasks(row)
    if name == "subtasks":
        return summarize_subtask(row)
    if name == "exeblocks":
        return summarize_exeblock(row)
    if name == "insts":
        return summarize_inst(row)
    if name == "instances":
        return {
            "base_addr": struct.unpack_from("<4Q", row, 0),
        }
    return None


def row_diff_report(name, ours, theirs, record_size):
    rows = min(len(ours), len(theirs)) // record_size
    ours_extra = len(ours) - rows * record_size
    theirs_extra = len(theirs) - rows * record_size
    diff_rows = []
    diff_count = 0
    first_diff_by_offset = Counter()
    inst_op_diff = Counter()
    for row_index in range(rows):
        a = ours[row_index * record_size : (row_index + 1) * record_size]
        b = theirs[row_index * record_size : (row_index + 1) * record_size]
        if a == b:
            continue
        diff_count += 1
        first = first_diff_offset(a, b)
        first_diff_by_offset[first] += 1
        if name == "insts":
            inst_op_diff[
                (
                    OP_NAMES.get(i32(a, 0), hex(i32(a, 0))),
                    OP_NAMES.get(i32(b, 0), hex(i32(b, 0))),
                )
            ] += 1
        if len(diff_rows) < 24:
            diff_rows.append((row_index, first, sha16(a), sha16(b)))

    print(f"\n=== {name} row diff ===")
    print(
        f"record_size={record_size} rows={rows} "
        f"diff_rows={diff_count} ours_extra={ours_extra} theirs_extra={theirs_extra}"
    )
    print("first_diff_offset_top=", first_diff_by_offset.most_common(12))
    if inst_op_diff:
        print("inst_op_diff_top=", inst_op_diff.most_common(20))
    for row_index, first, ours_sha, theirs_sha in diff_rows:
        print(
            f"DIFF_ROW row={row_index} first_byte={first} "
            f"ours_sha16={ours_sha} theirs_sha16={theirs_sha}"
        )
        a = ours[row_index * record_size : (row_index + 1) * record_size]
        b = theirs[row_index * record_size : (row_index + 1) * record_size]
        ours_fields = field_summary(name, a)
        theirs_fields = field_summary(name, b)
        if ours_fields is not None:
            print(f"  ours_fields={ours_fields}")
            print(f"  theirs_fields={theirs_fields}")


def byte_component_report(name, ours, theirs):
    same = ours == theirs
    print(f"\n=== {name} file diff ===")
    print(
        f"same={same} ours_size={len(ours)} theirs_size={len(theirs)} "
        f"ours_sha={hashlib.sha256(ours).hexdigest()} "
        f"theirs_sha={hashlib.sha256(theirs).hexdigest()}"
    )
    if not same:
        first = first_diff_offset(ours, theirs)
        print(f"first_byte_diff={first}")
        start = max(0, first - 32)
        end = min(min(len(ours), len(theirs)), first + 96)
        print(f"ours_hex_window={ours[start:end].hex()}")
        print(f"theirs_hex_window={theirs[start:end].hex()}")


def main():
    print(f"simict_root={SIMICT_ROOT}")
    print(f"bundle_root={BUNDLE_ROOT}")
    print(f"ours_root={OURS_ROOT}")
    print(f"legacy_root={LEGACY_ROOT}")

    if not OURS_ROOT.is_dir():
        print(f"ERROR: OpenFabric bundle not found: {OURS_ROOT}", file=sys.stderr)
        return 2
    if not LEGACY_ROOT.is_dir():
        print(f"ERROR: legacy gemm case not found: {LEGACY_ROOT}", file=sys.stderr)
        return 2

    had_diff = False
    for name, rel, record_size in COMPONENTS:
        ours = read(OURS_ROOT / rel)
        theirs = read(LEGACY_ROOT / rel)
        if ours is None or theirs is None:
            print(f"\n=== {name} ===")
            print(f"missing ours={ours is None} path={OURS_ROOT / rel}")
            print(f"missing theirs={theirs is None} path={LEGACY_ROOT / rel}")
            continue
        byte_component_report(name, ours, theirs)
        if ours != theirs:
            had_diff = True
        if record_size is not None and len(ours) == len(theirs):
            row_diff_report(name, ours, theirs, record_size)

    print(f"\nsummary={'DIFF' if had_diff else 'MATCH'}")
    return 1 if had_diff else 0


if __name__ == "__main__":
    raise SystemExit(main())
PY

set +e
"${ssh_cmd[@]}" "${REMOTE}" \
  "SIMICT_ROOT='${SIMICT_ROOT}' BUNDLE_DIR='${BUNDLE_DIR}' python3 '${REMOTE_SCRIPT}' > '${REMOTE_REPORT}' 2>&1"
remote_status=$?
set -e

"${ssh_cmd[@]}" "${REMOTE}" "cat '${REMOTE_REPORT}'" | tee "${LOCAL_REPORT}"

echo
echo "local_report=${LOCAL_REPORT}"
echo "remote_status=${remote_status}"
exit "${remote_status}"
