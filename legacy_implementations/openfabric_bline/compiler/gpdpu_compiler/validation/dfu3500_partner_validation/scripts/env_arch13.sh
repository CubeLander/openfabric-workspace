#!/usr/bin/env bash
# Shared arch-13 defaults for DFU3500 partner validation scripts.
#
# Principle: prefer editing these scripts locally and re-uploading the fixed
# dfu3500-validation.tgz bundle over typing long environment-variable commands
# inside nested remote shells.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VALIDATION_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export SIMICT_ROOT="${SIMICT_ROOT:-/project/home-new/huake02/simict3500final}"
export VENDOR_HOME="${VENDOR_HOME:-/project/home-new/huake02}"
export PAYLOADS_DIR="${PAYLOADS_DIR:-$VALIDATION_ROOT/payloads}"
export PYTHON_BIN="${PYTHON_BIN:-python}"
export OUT_DIR="${OUT_DIR:-$VALIDATION_ROOT/run}"

export RUN_DIFF="${RUN_DIFF:-0}"
export MAX_DIFF_BYTES="${MAX_DIFF_BYTES:-200000}"
export RUNTIME_MODE="${RUNTIME_MODE:-normal}"
export SIMICT_VERBOSE_AFTER="${SIMICT_VERBOSE_AFTER:-0}"
export RUNTIME_TIMEOUT_SECONDS="${RUNTIME_TIMEOUT_SECONDS:-900}"
export STOP_ON_FAIL="${STOP_ON_FAIL:-0}"
export REFRESH_VENDOR="${REFRESH_VENDOR:-0}"

export SMOKE_SCRIPT="${SMOKE_SCRIPT:-$VALIDATION_ROOT/smoke/current.sh}"
