#!/usr/bin/env bash
set -u
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=env_arch13.sh
source "$SCRIPT_DIR/env_arch13.sh"

export RUN_SMOKE=0
export RUN_PAYLOADS=1
export RUN_DIFF=0
export RUNTIME_MODE=verbose
export SIMICT_VERBOSE_AFTER="${SIMICT_VERBOSE_AFTER:-1000}"
exec "$VALIDATION_ROOT/validate_on_arch13.sh"
