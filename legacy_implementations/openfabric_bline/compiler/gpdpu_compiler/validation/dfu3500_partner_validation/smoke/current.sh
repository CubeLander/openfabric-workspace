#!/usr/bin/env bash
set -u

# Current smoke hook for arch-13 experiments.
#
# Edit this file locally, rebuild/upload dfu3500-validation.tgz, then run:
#
#   RUN_SMOKE=1 RUN_PAYLOADS=0 ./validate_on_arch13.sh
#
# This file intentionally starts as a no-op scaffold.  Keep experiments small:
# test one instruction/control-flow unknown per upload when possible.

echo "smoke=current"
echo "SIMICT_ROOT=${SIMICT_ROOT:-}"
echo "RISC_ROOT=${RISC_ROOT:-}"
echo "CONFIG_ROOT=${CONFIG_ROOT:-}"
echo "SMOKE_OUT=${SMOKE_OUT:-}"

cat > "${SMOKE_OUT:-.}/README.txt" <<'EOF'
This smoke hook is a local-edit placeholder.

Suggested log10max experiments:

1. smoke_fmax_shfl_reduce
   - derive from softmax_1 subtask CSV
   - replace SHFL+FADD reduction combine with SHFL+FMAX
   - verify runtime accepts the instruction sequence

2. smoke_flog2
   - verify CSV/runtime accepts FLOG2 spelling or find required pseudo-op mode

3. smoke_copyt_gather
   - single vendor task
   - 16 PE local value -> PE00
   - PE00 combines with FMAX and stores scratch

This file is deliberately not a maintained payload registry.
EOF

echo "smoke_result=NOOP"
