#!/usr/bin/env bash
set -u

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VALIDATION_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

export SIMICT_ROOT="${SIMICT_ROOT:-/project/home-new/huake02/simict3500final}"
export VENDOR_HOME="${VENDOR_HOME:-/project/home-new/huake02}"
export OUT_DIR="${OUT_DIR:-$VALIDATION_ROOT/run_bline_progress}"
export RUNTIME_MODE="${RUNTIME_MODE:-normal}"
export SIMICT_VERBOSE_AFTER="${SIMICT_VERBOSE_AFTER:-0}"
export RUNTIME_TIMEOUT_SECONDS="${RUNTIME_TIMEOUT_SECONDS:-900}"
export STOP_ON_FAIL="${STOP_ON_FAIL:-0}"

SELECTED_PAYLOADS_DIR="$VALIDATION_ROOT/run_bline_progress_payload_selection"
rm -rf "$SELECTED_PAYLOADS_DIR"
mkdir -p "$SELECTED_PAYLOADS_DIR"

ln -s "$VALIDATION_ROOT/payloads/bline_gemm_no_relu" \
  "$SELECTED_PAYLOADS_DIR/bline_gemm_no_relu"
ln -s "$VALIDATION_ROOT/payloads/bline_gemm_relu" \
  "$SELECTED_PAYLOADS_DIR/bline_gemm_relu"
ln -s "$VALIDATION_ROOT/payloads/log10max_single_task" \
  "$SELECTED_PAYLOADS_DIR/bline_log10max"

export PAYLOADS_DIR="$SELECTED_PAYLOADS_DIR"
exec "$SCRIPT_DIR/run_payloads.sh"
