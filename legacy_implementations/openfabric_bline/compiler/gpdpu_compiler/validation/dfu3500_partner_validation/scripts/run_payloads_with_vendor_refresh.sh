#!/usr/bin/env bash
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env_arch13.sh
source "$SCRIPT_DIR/env_arch13.sh"

export RUN_SMOKE=0
export RUN_PAYLOADS=1
export RUN_DIFF=0
export REFRESH_VENDOR=1
exec "$VALIDATION_ROOT/validate_on_arch13.sh"
