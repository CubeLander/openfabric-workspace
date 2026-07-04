#!/usr/bin/env bash
set -u

# One-button arch-13 entrypoint.
#
# Agents should edit this file locally before packaging when the validation
# workflow changes.  The commander should only need the fixed remote command:
#
#   tar -xzf dfu3500-validation.tgz
#   cd dfu3500_partner_validation
#   ./run.sh
#
# Do not ask the commander to choose payloads or type long environment-variable
# commands in nested remote shells.  Encode the intended run below, rebuild the
# fixed-name dfu3500-validation.tgz bundle, and keep the remote command boring.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Default arch-13 environment.  Override here when a run needs different paths
# or runtime behavior.
export SIMICT_ROOT="${SIMICT_ROOT:-/project/home-new/huake02/simict3500final}"
export VENDOR_HOME="${VENDOR_HOME:-/project/home-new/huake02}"
export OUT_DIR="${OUT_DIR:-$SCRIPT_DIR/run}"
export RUNTIME_MODE="${RUNTIME_MODE:-normal}"
export SIMICT_VERBOSE_AFTER="${SIMICT_VERBOSE_AFTER:-0}"
export RUNTIME_TIMEOUT_SECONDS="${RUNTIME_TIMEOUT_SECONDS:-900}"
export STOP_ON_FAIL="${STOP_ON_FAIL:-0}"

# Today's default: run the B-line three-operator upload payloads.  This is an
# upload/remote-validation entrypoint: the selected payloads carry their own
# local runtime_ready reports and may fail remotely.  Keep this file as the only
# command the commander has to run inside the extracted package.
SELECTED_PAYLOADS_DIR="$SCRIPT_DIR/run_payload_selection"
rm -rf "$SELECTED_PAYLOADS_DIR"
mkdir -p "$SELECTED_PAYLOADS_DIR"
ln -s "$SCRIPT_DIR/payloads/bline_gemm_no_relu" \
  "$SELECTED_PAYLOADS_DIR/bline_gemm_no_relu"
ln -s "$SCRIPT_DIR/payloads/bline_gemm_relu" \
  "$SELECTED_PAYLOADS_DIR/bline_gemm_relu"
ln -s "$SCRIPT_DIR/payloads/log10max_single_task" \
  "$SELECTED_PAYLOADS_DIR/log10max_single_task"
export PAYLOADS_DIR="$SELECTED_PAYLOADS_DIR"

# For smoke-only validation, replace the exec line below with:
#
#   exec "$SCRIPT_DIR/scripts/run_smoke.sh"
#
# Other useful fixed launchers:
#   exec "$SCRIPT_DIR/scripts/run_smoke_then_payloads.sh"
#   exec "$SCRIPT_DIR/scripts/run_verbose_payloads.sh"
#   exec "$SCRIPT_DIR/scripts/run_payloads_with_vendor_refresh.sh"
exec "$SCRIPT_DIR/scripts/run_payloads.sh"
