# log10max FMAX Probe Notes

Status: hot customer-handoff diagnostic evidence, not a correctness package.

The customer-side crash reported for `log10max_refactored` stops around
`PE3,3, inst_idx:18, opcode:22`.  The generated PE(3,3) CSV maps that location
to the first local-reduction shuffle row:

```csv
SHFL,SHFL18,rof_t0_rShflF0,of_t0_local_log10_max,rof_t0_shuffle_tmp,,3,0
```

The source route is:

```text
main.cpp subtask1
  -> log10_tile
  -> materialize_log10_tile
  -> local_max_from_log10_tile
```

`local_max_from_log10_tile` first emits one `FMAX` across the two local log10
chunks, then emits five `SHFL + FMAX` reduction steps with shuffle constants
`16, 8, 4, 2, 1`.

To isolate whether the customer simulator can advance through the non-shuffle
part of the operator, the repository has a diagnostic CMake target:

```sh
cmake --build build --target log10max_fmax_probe_test_package
```

It writes:

```text
build/customer_delivery/log10max_fmax_probe.tar.gz
```

This package defines `LOG10MAX_FMAX_ONLY_LOCAL_MAX_PROBE` only for the probe
config generator.  The official `log10max_refactored` target is unchanged: it
still emits the full `SHFL + FMAX` local reduction.  The probe package is
expected to be numerically incomplete because it keeps only the first local
`FMAX` and skips the intra-PE shuffle reduction.  Its purpose is to answer a
narrow runtime question: whether the package can get past the place where the
full operator first hits the shuffle reduction.

## OCR/source risk

There is a separate risk that the checked-in `common_oper` SHFL handling is not
the exact partner implementation.  Historical notes say `testcase/common_oper`
was recovered far enough to compile, but behavior equivalence still needed care,
especially for complex register conflicts, chained reduce/copy behavior,
operand reuse, and serialization.  The old deferred-audit rule also says to
re-open OCR/source fingerprint work when local decoder behavior diverges from
runtime behavior or a blocking bug needs source-level re-audit.

For this incident, the useful re-check scope is narrow:

```text
testcase/common_oper/csv_oper.cpp      SHFL registration: arity, unit, latency
testcase/common_oper/task_print.cpp    SHFL serialization into simulator/RTL bins
common/src/inst_def.h                  OP_SHFL enum value and inst_t field layout
softmax_1 SHFL rows                    partner-known working SHFL operand pattern
```

The question is not "is SHFL real"; vendor softmax evidence says it is.  The
question is whether the current OCR-recovered `common_oper` encodes this exact
`SHFL, rShflF*, local_log10_max, shuffle_tmp, imm=3, iteration=0` pattern the
same way as the partner's real build/runtime path.

Local confirmation: the checked-in `task_print.cpp` currently routes `OP_SHFL`
through the generic `inst_t_cal2_for_rtl` serializer.  It writes only opcode,
base address selector, two source operand indices, one destination operand
index, a 10-bit immediate, end flag, and block index.  The legacy instruction
card describes SHFL as a lane-permutation instruction where `imm[1:0]` selects
mode, `imm[2:5]` controls four 1024-bit groups, and mode 3 is the softmax-style
shift reduction pattern.  That is enough evidence to treat current SHFL
serialization as stale or at least incomplete until the partner's real
`task_print.cpp`/common_oper source is recovered.

Follow-up with `testcase/common_oper/task_print.md` OCR: the recovered
special-cal fragment agrees with the checked-in SHFL handling at the useful
level.  `OP_SHFL` stays in the special-cal set and is written with its own
opcode instead of being remapped to `OP_FRCP`.  I did not copy the later
`LDCNST` continuation from OCR because it references fields such as
`mask_mode`/`sind_mode` that do not exist in the checked-in
`inst_t_ldst_for_rtl`.

The `task_print.md` OCR is not one continuous source file.  It is a concatenated
set of Qwen OCR replies, and it explicitly says the first capture was truncated
inside the `OP_LDCNST` branch before a later reply tries to continue it.  Several
nearby blocks are also clearly inactive source text after restoring dropped
preprocessor markers: old minimal LD/ST serialization under `#if 0`, debug
prints under `#if 0`, blank-fill code under `#ifndef BLANK_INST`, and the older
4-PE RTL merge loop inside `/* ... */`.  The `mask_mode`/`sind_mode` lines are
not visibly under one of those comment blocks; they are better classified as an
untrusted OCR continuation/reconstruction of the same truncated `OP_LDCNST`
branch rather than as authoritative active source.

Follow-up with `common/src/inst_def.md` OCR: the fresh customer-side header
points to a newer instruction definition than the checked-in code.  The applied
low-risk sync points are:

```text
OP_FLT_LATENCY: 72 -> 2
OP_SHA_SO:      OP_SHA_S0, with matching "SHA_S0" string registration
cal2 imm field: int64_t:10 -> uint64_t:10
```

The latency change is the important runtime-facing one for this incident:
`csv_oper.cpp` registers `FMAX`, `SHFL`, and most float-family instructions with
`OP_FLT_LATENCY`, so the old value can move schedule/packing decisions far away
from the partner build.  This also matches the older archive note that the
visible common header still carried stale `OP_FLT_LATENCY=72`.

Two OCR-visible names were not applied:

```text
OP_GTASK   -- current code, name table, and csv registration consistently use OP_GIBSN/GIBSN
OP_SLDM64  -- current code, name table, and csv registration consistently use OP_SLDMD64/SLDMD64
```

Those look like OCR loss rather than intentional ISA changes.  The new
`inst_def.md` also does not contain `mask_mode`/`sind_mode` in
`inst_t_ldst_for_rtl`.  A customer-side full-tree search also found no
`mask_mode`, `sind_mode`, or `sink_mode` symbols beyond the two copied OCR text
files, so the `task_print.md` LDCNST continuation is not a missing dependency to
implement.  Keep the checked-in/current `LDCNST` mapping onto
`int8_offset`/`simd_mode`/`mask_enable` unless a real source file, not an OCR
continuation, shows otherwise.
