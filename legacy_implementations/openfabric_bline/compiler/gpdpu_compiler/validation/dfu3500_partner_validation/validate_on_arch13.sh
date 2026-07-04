#!/usr/bin/env bash
set -u
# Batch-validate OpenFabric payloads on huake02@arch-13.
#
# The default path validates every directory under payloads/* by staging its
# result/cbuf_file.bin and result/micc_file.bin into the vendor runtime config
# and then running SimICT.  Binary diff is optional and disabled by default.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export SIMICT_ROOT="${SIMICT_ROOT:-/project/home-new/huake02/simict3500final}"
export VENDOR_HOME="${VENDOR_HOME:-/project/home-new/huake02}"
export PAYLOADS_DIR="${PAYLOADS_DIR:-$SCRIPT_DIR/payloads}"
export PYTHON_BIN="${PYTHON_BIN:-python}"
export RUN_PAYLOADS="${RUN_PAYLOADS:-1}"
export RUN_SMOKE="${RUN_SMOKE:-0}"
export SMOKE_SCRIPT="${SMOKE_SCRIPT:-$SCRIPT_DIR/smoke/current.sh}"
export RUN_DIFF="${RUN_DIFF:-0}"
export MAX_DIFF_BYTES="${MAX_DIFF_BYTES:-200000}"
export RUNTIME_MODE="${RUNTIME_MODE:-normal}" # normal | verbose
export SIMICT_VERBOSE_AFTER="${SIMICT_VERBOSE_AFTER:-0}"
export RUNTIME_TIMEOUT_SECONDS="${RUNTIME_TIMEOUT_SECONDS:-900}"
export STOP_ON_FAIL="${STOP_ON_FAIL:-0}"
export REFRESH_VENDOR="${REFRESH_VENDOR:-0}"

OUT_DIR="${OUT_DIR:-$PWD/run}"
SUMMARY="$OUT_DIR/summary.tsv"

RISC_ROOT="$SIMICT_ROOT/gpdpu/users/risc_nn_riscv"
CONFIG_ROOT="$RISC_ROOT"
BUILD_APP_DIR="$RISC_ROOT/testcase/application/build_app"
RUNTIME_BIN="$RISC_ROOT/../../core/bin/runtime"
RUNTIME_VERBOSE_BIN="$RISC_ROOT/../../core/bin/runtime_verbose"

mkdir -p "$OUT_DIR"
: > "$SUMMARY"
printf "case_id\tapp_name\ttask_num\tdiff_status\truntime_rc\n" >> "$SUMMARY"

log_case() {
  local log_file="$1"
  shift
  echo "$@" | tee -a "$log_file"
}

manifest_value() {
  local manifest="$1"
  local key="$2"
  if [ -f "$manifest" ]; then
    grep -E "^${key}=" "$manifest" | tail -1 | sed "s/^${key}=//"
  fi
}

setup_vendor_env() {
  export HOME="$VENDOR_HOME"
  export PATH="$HOME/fake_root_5.1/gcc/bin:$PATH:$HOME/fake_root_5.1/m4/bin:$HOME/fake_root_5.1/automake/bin:$HOME/fake_root_5.1/autoconf/bin:$HOME/fake_root_5.1/automake/bin:$HOME/fake_root_5.1/libtool/bin:$HOME/fake_root_5.1/readline/bin"
  export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:$HOME/fake_root_5.1/gcc/lib:$HOME/fake_root_5.1/gmp/lib:$HOME/fake_root_5.1/mpc/lib:$HOME/fake_root_5.1/mpfr/lib:$HOME/fake_root_5.1/m4/lib:$HOME/fake_root_5.1/automake/lib:$HOME/fake_root_5.1/autoconf/lib:$HOME/fake_root_5.1/automake/lib:$HOME/fake_root_5.1/libtool/lib:$HOME/fake_root_5.1/readline/lib:$HOME/fake_root_5.1/gcc/lib64:"
  export C_INCLUDE_PATH="$HOME/fake_root_5.1/gcc/include:${C_INCLUDE_PATH:-}:$HOME/fake_root_5.1/mpfr/include:$HOME/fake_root_5.1/gmp/include:$HOME/fake_root_5.1/m4/include:$HOME/fake_root_5.1/automake/include:$HOME/fake_root_5.1/autoconf/include:$HOME/fake_root_5.1/automake/include:$HOME/fake_root_5.1/libtool/include:$HOME/fake_root_5.1/readline/include"
}

refresh_vendor_result() {
  local app_name="$1"
  local task_num="$2"
  local log_file="$3"
  local case_dir="$RISC_ROOT/testcase/application/$app_name"
  if [ ! -d "$case_dir" ]; then
    log_case "$log_file" "ERROR: missing vendor case: $case_dir"
    return 1
  fi
  if [ ! -d "$BUILD_APP_DIR" ]; then
    log_case "$log_file" "ERROR: missing build_app dir: $BUILD_APP_DIR"
    return 1
  fi
  (
    cd "$case_dir" && ./run.sh
  ) >> "$log_file" 2>&1 || return 1
  (
    cd "$BUILD_APP_DIR" && ./run_mtr.sh "$app_name" "$task_num" 1
  ) >> "$log_file" 2>&1 || return 1
}

find_case_input_data() {
  local case_dir="$1"
  local candidate
  for candidate in \
    "$case_dir/input_data.bin" \
    "$case_dir/spm_data/input_data.bin" \
    "$case_dir/config/input_data.bin"
  do
    if [ -f "$candidate" ]; then
      printf "%s\n" "$candidate"
      return 0
    fi
  done
  return 1
}

find_case_riscv_program() {
  local case_dir="$1"
  local candidate
  for candidate in \
    "$case_dir/riscv/riscv" \
    "$case_dir/config/riscv_program"
  do
    if [ -f "$candidate" ]; then
      printf "%s\n" "$candidate"
      return 0
    fi
  done
  return 1
}

find_payload_input_data() {
  local payload_dir="$1"
  local candidate
  for candidate in \
    "$payload_dir/runtime/input_data.bin" \
    "$payload_dir/input_data.bin" \
    "$payload_dir/data/input_data.bin"
  do
    if [ -f "$candidate" ]; then
      printf "%s\n" "$candidate"
      return 0
    fi
  done
  return 1
}

find_payload_riscv_program() {
  local payload_dir="$1"
  local candidate
  for candidate in \
    "$payload_dir/runtime/riscv_program" \
    "$payload_dir/riscv_program"
  do
    if [ -f "$candidate" ]; then
      printf "%s\n" "$candidate"
      return 0
    fi
  done
  return 1
}

build_payload_riscv_program() {
  local payload_dir="$1"
  local log_file="$2"
  local src_root="$payload_dir/runtime/riscv_src"
  local src="$src_root/riscv/testarm.c"
  local out="$payload_dir/runtime/riscv_program"
  local api_src="$src_root/dpuapi/DpuAPI.c"
  local api_include="$src_root/dpuapi"
  local common_include="$RISC_ROOT/common/src"

  if [ ! -f "$src" ]; then
    return 1
  fi
  if [ ! -f "$api_src" ]; then
    api_src="$RISC_ROOT/dpuapi/DpuAPI.c"
    api_include="$RISC_ROOT/dpuapi"
    log_case "$log_file" "payload-local DpuAPI missing; falling back to SIMICT_ROOT dpuapi"
  fi
  if [ ! -f "$api_src" ]; then
    log_case "$log_file" "ERROR: missing DpuAPI source: $api_src"
    return 1
  fi
  mkdir -p "$payload_dir/runtime"
  log_case "$log_file" "building payload riscv_program from: $src"
  (
    cd "$src_root/riscv" && \
    riscv64-unknown-elf-gcc \
      -mabi=lp64d -march=rv64gcv -static \
      -o "$out" \
      testarm.c "$api_src" \
      -I "$api_include" \
      -I "$common_include"
  ) >> "$log_file" 2>&1 || return 1
  if [ ! -f "$out" ]; then
    log_case "$log_file" "ERROR: RISC-V build completed without output: $out"
    return 1
  fi
}

prepare_case_assets_if_needed() {
  local case_dir="$1"
  local log_file="$2"
  local input_data_path=""
  local riscv_program_path=""

  input_data_path="$(find_case_input_data "$case_dir" || true)"
  riscv_program_path="$(find_case_riscv_program "$case_dir" || true)"
  if [ -n "$input_data_path" ] && [ -n "$riscv_program_path" ]; then
    return 0
  fi

  if [ ! -f "$case_dir/run.sh" ]; then
    return 0
  fi

  log_case "$log_file" "preparing vendor case assets with: $case_dir/run.sh"
  (
    cd "$case_dir" && sh ./run.sh
  ) >> "$log_file" 2>&1 || return 1
}

stage_payload_config() {
  local payload_dir="$1"
  local app_name="$2"
  local log_file="$3"
  local case_dir="$RISC_ROOT/testcase/application/$app_name"
  local input_data_path=""
  local riscv_program_path=""

  if [ ! -f "$payload_dir/result/cbuf_file.bin" ]; then
    log_case "$log_file" "ERROR: missing payload cbuf: $payload_dir/result/cbuf_file.bin"
    return 1
  fi
  if [ ! -f "$payload_dir/result/micc_file.bin" ]; then
    log_case "$log_file" "ERROR: missing payload micc: $payload_dir/result/micc_file.bin"
    return 1
  fi
  input_data_path="$(find_payload_input_data "$payload_dir" || true)"
  riscv_program_path="$(find_payload_riscv_program "$payload_dir" || true)"
  if [ -z "$riscv_program_path" ]; then
    build_payload_riscv_program "$payload_dir" "$log_file" || true
    riscv_program_path="$(find_payload_riscv_program "$payload_dir" || true)"
  fi

  if { [ -z "$input_data_path" ] || [ -z "$riscv_program_path" ]; } && [ -d "$case_dir" ]; then
    prepare_case_assets_if_needed "$case_dir" "$log_file" || return 1
    if [ -z "$input_data_path" ]; then
      input_data_path="$(find_case_input_data "$case_dir" || true)"
    fi
    if [ -z "$riscv_program_path" ]; then
      riscv_program_path="$(find_case_riscv_program "$case_dir" || true)"
    fi
  fi

  if [ -z "$input_data_path" ]; then
    log_case "$log_file" "ERROR: missing input_data.bin"
    log_case "$log_file" "checked:"
    log_case "$log_file" "  $payload_dir/runtime/input_data.bin"
    log_case "$log_file" "  $payload_dir/input_data.bin"
    log_case "$log_file" "  $payload_dir/data/input_data.bin"
    log_case "$log_file" "  $case_dir/input_data.bin"
    log_case "$log_file" "  $case_dir/spm_data/input_data.bin"
    log_case "$log_file" "  $case_dir/config/input_data.bin"
    find "$payload_dir" -maxdepth 4 -name input_data.bin -print >> "$log_file" 2>/dev/null || true
    if [ -d "$case_dir" ]; then
      find "$case_dir" -maxdepth 3 -name input_data.bin -print >> "$log_file" 2>/dev/null || true
    fi
    return 1
  fi
  if [ -z "$riscv_program_path" ]; then
    log_case "$log_file" "ERROR: missing riscv_program"
    log_case "$log_file" "checked:"
    log_case "$log_file" "  $payload_dir/runtime/riscv_program"
    log_case "$log_file" "  $payload_dir/riscv_program"
    log_case "$log_file" "  $payload_dir/runtime/riscv_src/riscv/testarm.c"
    log_case "$log_file" "  $case_dir/riscv/riscv"
    log_case "$log_file" "  $case_dir/config/riscv_program"
    find "$payload_dir" -maxdepth 5 -name riscv_program -o -name testarm.c >> "$log_file" 2>/dev/null || true
    if [ -d "$case_dir" ]; then
      find "$case_dir" -maxdepth 3 -name riscv -type f -print >> "$log_file" 2>/dev/null || true
    fi
    return 1
  fi
  log_case "$log_file" "input_data_path=$input_data_path"
  log_case "$log_file" "riscv_program_path=$riscv_program_path"

  cd "$CONFIG_ROOT" || return 1
  rm -rf stat log rtl_trace sim_trace config
  mkdir -p log stat rtl_trace sim_trace/cycle_trace sim_trace/checkpoint config
  cp -a "$payload_dir/result/cbuf_file.bin" ./config/cbuf_file.bin
  cp -a "$payload_dir/result/micc_file.bin" ./config/micc_file.bin
  if [ -f "$payload_dir/result/data_inst_replace.bin" ]; then
    cp -a "$payload_dir/result/data_inst_replace.bin" ./config/data_inst_replace.bin
  fi
  cp -a "$input_data_path" ./config/input_data.bin
  cp -a "$riscv_program_path" ./config/riscv_program
}

run_runtime() {
  local runtime_log="$1"
  local runtime_cmd=()
  local wrapped_cmd=()
  cd "$CONFIG_ROOT" || return 1
  export LD_LIBRARY_PATH="${LD_LIBRARY_PATH:-}:$CONFIG_ROOT/common/src/"
  if [ "$RUNTIME_MODE" = "verbose" ]; then
    if [ "$SIMICT_VERBOSE_AFTER" != "0" ]; then
      export SIMICT_VERBOSE_AFTER
    fi
    runtime_cmd=("$RUNTIME_VERBOSE_BIN" ./ top.so topPara.so common/src/libcommon.so)
  else
    runtime_cmd=("$RUNTIME_BIN" ./ top.so topPara.so common/src/libcommon.so)
  fi

  if command -v stdbuf >/dev/null 2>&1; then
    wrapped_cmd=(stdbuf -oL -eL "${runtime_cmd[@]}")
  else
    wrapped_cmd=("${runtime_cmd[@]}")
  fi

  if command -v timeout >/dev/null 2>&1 && [ "$RUNTIME_TIMEOUT_SECONDS" != "0" ]; then
    timeout "$RUNTIME_TIMEOUT_SECONDS" "${wrapped_cmd[@]}" 2>&1 | tee "$runtime_log"
    local rc=${PIPESTATUS[0]}
    [ "$RUNTIME_MODE" = "verbose" ] && unset SIMICT_VERBOSE_AFTER
    return "$rc"
  fi

  "${wrapped_cmd[@]}" 2>&1 | tee "$runtime_log"
  local rc=${PIPESTATUS[0]}
  [ "$RUNTIME_MODE" = "verbose" ] && unset SIMICT_VERBOSE_AFTER
  return "$rc"
}

setup_vendor_env

run_smoke_script() {
  local smoke_script="$1"
  local smoke_out="$OUT_DIR/smoke"
  local smoke_log="$smoke_out/run.log"
  mkdir -p "$smoke_out"
  : > "$smoke_log"
  if [ ! -f "$smoke_script" ]; then
    echo "ERROR: missing SMOKE_SCRIPT=$smoke_script" | tee -a "$smoke_log"
    printf "%s\t%s\t%s\t%s\t%s\n" "smoke" "-" "-" "SKIPPED" "1" >> "$SUMMARY"
    return 1
  fi
  echo "# run smoke script" | tee -a "$smoke_log"
  echo "SMOKE_SCRIPT=$smoke_script" | tee -a "$smoke_log"
  echo "SMOKE_OUT=$smoke_out" | tee -a "$smoke_log"
  SMOKE_OUT="$smoke_out"
  export SCRIPT_DIR OUT_DIR SMOKE_OUT
  export SIMICT_ROOT VENDOR_HOME RISC_ROOT CONFIG_ROOT BUILD_APP_DIR
  export RUNTIME_BIN RUNTIME_VERBOSE_BIN RUNTIME_MODE SIMICT_VERBOSE_AFTER
  (
    cd "$SCRIPT_DIR" && bash "$smoke_script"
  ) >> "$smoke_log" 2>&1
  local smoke_rc=$?
  echo "smoke_rc=$smoke_rc" | tee -a "$smoke_log"
  printf "%s\t%s\t%s\t%s\t%s\n" "smoke" "-" "-" "SKIPPED" "$smoke_rc" >> "$SUMMARY"
  return "$smoke_rc"
}

overall_rc=0

if [ "$RUN_SMOKE" = "1" ]; then
  run_smoke_script "$SMOKE_SCRIPT" || {
    overall_rc=1
    [ "$STOP_ON_FAIL" = "1" ] && exit 1
  }
fi

if [ "$RUN_PAYLOADS" != "1" ]; then
  echo "RUN_PAYLOADS=$RUN_PAYLOADS; skipping payload validation"
  echo "summary=$SUMMARY"
  cat "$SUMMARY"
  exit "$overall_rc"
fi

if [ ! -d "$PAYLOADS_DIR" ]; then
  echo "ERROR: missing PAYLOADS_DIR=$PAYLOADS_DIR"
  exit 1
fi

for payload_dir in "$PAYLOADS_DIR"/*; do
  [ -d "$payload_dir" ] || continue
  case_id="$(basename "$payload_dir")"
  manifest="$payload_dir/MANIFEST.txt"
  app_name="$(manifest_value "$manifest" app_name)"
  task_num="$(manifest_value "$manifest" task_num)"
  app_name="${app_name:-$case_id}"
  task_num="${task_num:-4}"

  case_out="$OUT_DIR/$case_id"
  mkdir -p "$case_out"
  run_log="$case_out/run.log"
  diff_log="$case_out/diff.log"
  runtime_log="$case_out/runtime.log"
  : > "$run_log"
  : > "$diff_log"
  : > "$runtime_log"

  log_case "$run_log" "# validate payload"
  log_case "$run_log" "case_id=$case_id"
  log_case "$run_log" "app_name=$app_name"
  log_case "$run_log" "task_num=$task_num"
  log_case "$run_log" "payload_dir=$payload_dir"
  log_case "$run_log" "SIMICT_ROOT=$SIMICT_ROOT"
  log_case "$run_log" "RUN_DIFF=$RUN_DIFF"
  log_case "$run_log" "REFRESH_VENDOR=$REFRESH_VENDOR"

  if [ "$REFRESH_VENDOR" = "1" ]; then
    refresh_vendor_result "$app_name" "$task_num" "$run_log" || {
      log_case "$run_log" "refresh_vendor_result=FAILED"
      printf "%s\t%s\t%s\tSKIPPED\t1\n" "$case_id" "$app_name" "$task_num" >> "$SUMMARY"
      overall_rc=1
      [ "$STOP_ON_FAIL" = "1" ] && exit 1
      continue
    }
  fi

  diff_status="SKIPPED"
  if [ "$RUN_DIFF" = "1" ]; then
    export APP_NAME="$app_name"
    export LOCAL_ROOT="$payload_dir"
    export OUT="$diff_log"
    export SIMICT_ROOT
    "$PYTHON_BIN" "$SCRIPT_DIR/tools/diff_vendor_bytes.py" >> "$run_log" 2>&1
    diff_rc=$?
    diff_status="rc=$diff_rc"
  fi

  stage_payload_config "$payload_dir" "$app_name" "$run_log" || {
    log_case "$run_log" "stage_payload_config=FAILED"
    printf "%s\t%s\t%s\t%s\t1\n" "$case_id" "$app_name" "$task_num" "$diff_status" >> "$SUMMARY"
    overall_rc=1
    [ "$STOP_ON_FAIL" = "1" ] && exit 1
    continue
  }

  log_case "$run_log" "starting runtime: mode=$RUNTIME_MODE log=$runtime_log"
  run_runtime "$runtime_log"
  runtime_rc=$?
  log_case "$run_log" "runtime_rc=$runtime_rc"
  grep -n -E "error|ERROR|Error|out of range|segfault|failed|FAILED|assert|invalid|exception" "$runtime_log" 2>/dev/null | tail -120 >> "$run_log" || true
  printf "%s\t%s\t%s\t%s\t%s\n" "$case_id" "$app_name" "$task_num" "$diff_status" "$runtime_rc" >> "$SUMMARY"
  if [ "$runtime_rc" != "0" ]; then
    overall_rc=1
    [ "$STOP_ON_FAIL" = "1" ] && exit "$runtime_rc"
  fi
done

echo "summary=$SUMMARY"
cat "$SUMMARY"
exit "$overall_rc"
