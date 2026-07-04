#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VALIDATION_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
REPO_ROOT="$(cd "$VALIDATION_ROOT/../../../.." && pwd)"
OUT="${1:-dfuval.tgz}"

cd "$REPO_ROOT"

PYTHONPATH=compiler python3 compiler/tools/check_partner_validation_entrypoint.py

tar -C compiler/gpdpu_compiler/validation \
  --exclude='dfu3500_partner_validation/run' \
  --exclude='dfu3500_partner_validation/run_payload_selection' \
  --exclude='dfu3500_partner_validation/__pycache__' \
  --exclude='dfu3500_partner_validation/tools/__pycache__' \
  -czf "$OUT" dfu3500_partner_validation

sha256sum "$OUT"
ls -lh "$OUT"
