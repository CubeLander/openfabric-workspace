#!/usr/bin/env python
# Python 2.7 / old Python 3 compatible top-level byte diff.
#
# This intentionally reports only the first useful comparison wave:
#   local/result/cbuf_file.bin  vs vendor result/cbuf_file.bin
#   local/result/micc_file.bin  vs vendor result/micc_file.bin
#
# Repeated runtime/config comparisons and section-level summaries are omitted
# because they duplicate the same evidence and make OCR/debug logs noisy.

import hashlib
import os
import sys
import time


DEFAULT_SIMICT_ROOT = os.path.join(
    "/project/home-new",
    os.environ.get("USER", os.environ.get("LOGNAME", "huake02")),
    "simict3500final",
)
APP_NAME = os.environ.get("APP_NAME", "gemm_template_fusion")
SIMICT_ROOT = os.environ.get("SIMICT_ROOT", DEFAULT_SIMICT_ROOT)
SCRIPT_DIR = os.path.abspath(os.path.dirname(__file__))
LOCAL_ROOT = os.environ.get("LOCAL_ROOT", os.path.join(SCRIPT_DIR, "local"))
RISC_NN_ROOT = os.path.join(SIMICT_ROOT, "gpdpu/users/risc_nn_riscv")
TESTCASE_ROOT = os.path.join(RISC_NN_ROOT, "testcase")
REMOTE_CASE = os.environ.get(
    "REMOTE_CASE",
    os.path.join(TESTCASE_ROOT, "application", APP_NAME),
)

# 0 means unlimited. Use a positive number on arch-13 if a broken package would
# otherwise print millions of byte rows.
MAX_DIFF_BYTES = int(os.environ.get("MAX_DIFF_BYTES", "0"))
OUT = os.environ.get("OUT", os.path.abspath("./diff.log"))


def bval(byte):
    if isinstance(byte, int):
        return byte
    return ord(byte)


def read_file(path):
    if not os.path.isfile(path):
        return None
    f = open(path, "rb")
    try:
        return f.read()
    finally:
        f.close()


def sha256_hex(data):
    if data is None:
        return "MISSING"
    h = hashlib.sha256()
    h.update(data)
    return h.hexdigest()


def size_text(data):
    if data is None:
        return "MISSING"
    return str(len(data))


def diff_count(a, b):
    min_len = min(len(a), len(b))
    count = abs(len(a) - len(b))
    index = 0
    while index < min_len:
        if bval(a[index]) != bval(b[index]):
            count += 1
        index += 1
    return count


def write_diff_bytes(w, a, b):
    min_len = min(len(a), len(b))
    printed = 0
    index = 0
    w("differing_bytes offset_dec offset_hex local remote:\n")
    while index < min_len:
        av = bval(a[index])
        bv = bval(b[index])
        if av != bv:
            if MAX_DIFF_BYTES == 0 or printed < MAX_DIFF_BYTES:
                w("  %d 0x%x %s %s\n" % (index, index, str(av), str(bv)))
            printed += 1
        index += 1
    while index < len(a):
        if MAX_DIFF_BYTES == 0 or printed < MAX_DIFF_BYTES:
            w("  %d 0x%x %s EOF\n" % (index, index, str(bval(a[index]))))
        printed += 1
        index += 1
    while index < len(b):
        if MAX_DIFF_BYTES == 0 or printed < MAX_DIFF_BYTES:
            w("  %d 0x%x EOF %s\n" % (index, index, str(bval(b[index]))))
        printed += 1
        index += 1
    if MAX_DIFF_BYTES != 0 and printed > MAX_DIFF_BYTES:
        w("diff_bytes_truncated=1 printed=%d total=%d\n" % (MAX_DIFF_BYTES, printed))
    else:
        w("diff_bytes_truncated=0 printed=%d total=%d\n" % (printed, printed))


def write_pair_report(w, title, local_path, remote_path):
    local_data = read_file(local_path)
    remote_data = read_file(remote_path)
    w("\n=== %s ===\n" % title)
    w("local:  %s\n" % local_path)
    w("remote: %s\n" % remote_path)
    w("local_size=%s local_sha=%s\n" % (size_text(local_data), sha256_hex(local_data)))
    w("remote_size=%s remote_sha=%s\n" % (size_text(remote_data), sha256_hex(remote_data)))
    if local_data is None or remote_data is None:
        w("status=MISSING\n")
        return False
    if local_data == remote_data:
        w("status=MATCH\n")
        return True
    w("status=DIFF\n")
    w("diff_byte_count=%d\n" % diff_count(local_data, remote_data))
    write_diff_bytes(w, local_data, remote_data)
    return False


def main():
    out_f = open(OUT, "w")

    def w(s):
        sys.stdout.write(s)
        out_f.write(s)

    try:
        w("# top-level OpenFabric vs arch13 vendor byte diff\n")
        w("date=%s\n" % time.strftime("%Y-%m-%dT%H:%M:%S%z"))
        if hasattr(os, "uname"):
            w("host=%s\n" % os.uname()[1])
        else:
            w("host=unknown\n")
        w("APP_NAME=%s\n" % APP_NAME)
        w("SIMICT_ROOT=%s\n" % SIMICT_ROOT)
        w("REMOTE_CASE=%s\n" % REMOTE_CASE)
        w("LOCAL_ROOT=%s\n" % LOCAL_ROOT)
        w("MAX_DIFF_BYTES=%d\n" % MAX_DIFF_BYTES)
        w("OUT=%s\n" % OUT)

        all_match = True
        pairs = [
            (
                "result/cbuf_file.bin",
                os.path.join(LOCAL_ROOT, "result/cbuf_file.bin"),
                os.path.join(REMOTE_CASE, "result/cbuf_file.bin"),
            ),
            (
                "result/micc_file.bin",
                os.path.join(LOCAL_ROOT, "result/micc_file.bin"),
                os.path.join(REMOTE_CASE, "result/micc_file.bin"),
            ),
        ]
        for title, local_path, remote_path in pairs:
            if not write_pair_report(w, title, local_path, remote_path):
                all_match = False

        w("\nALL_TOP_LEVEL_MATCH=%d\n" % (1 if all_match else 0))
        w("report=%s\n" % OUT)
    finally:
        out_f.close()


if __name__ == "__main__":
    main()
