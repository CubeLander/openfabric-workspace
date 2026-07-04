# DFU3500 address composition notes

Date: 2026-07-02

This note records the current address-model investigation for the active
`simict3500final` path. The main question is how vendor instance rows and CSV
memory immediates are meant to compose.

## Confirmed model

For LD/ST-style memory instructions, the target-visible address is split:

```text
effective_vendor_word_addr =
  current_instance_conf_info.base_addr[base_addr_idx] + imm
```

Facts from current sources:

- `instance_conf_info_t` contains `base_addr[MAX_BASE_ADDR_PER_SUBTASK]`.
- `MAX_BASE_ADDR_PER_SUBTASK == 4`, so valid logical slots are `0..3`.
- CSV column `iteration` is parsed into `inst_t.iter_exe_cond`.
- `task_print.cpp` serializes `iter_exe_cond` into RTL `base_addr_idx` for
  `STM`, `LD/ST`, `CAL`, `MOVE`, and `IMM` families. For normal memory ops it
  is the base slot selector, not a hardware loop index.
- `inst_t_ldst_for_rtl` and `inst_t_stm_for_rtl` carry:
  - `base_addr_idx:4`
  - `imm:21`
- The OpenFabric common builder treats vendor base-address units as 4-byte
  words. Therefore:
  - fp32 element offset `N` -> vendor offset `N`
  - fp16 element offset `N` -> vendor offset `floor(N / 2)` on the legacy path
- Customer documentation confirms that a single subtask's instance base-address
  table has at most 2048 entries and is compact within that subtask table. It is
  laid out by active instance rows, with each row carrying its base slots:

```text
(instance0, addr0), (instance0, addr1), ...
...
(instance2047, addr0), (instance2047, addr1), ...
```

## Intended responsibility split

The durable model should be:

```text
subtask instance row:
  stage/shard/window-level base addresses

CSV imm:
  PE-local or tile-inner offset within that stage/shard/window

CSV iteration:
  base slot selector, i.e. which base_addr[0..3] to use
```

This means large tensor/shard movement should normally be represented by
different instance rows when the same template body repeats. PE-local row, lane,
column, window, or summary-slot variation should normally be represented by
instruction immediates.

The rule is not "always use instance for large addresses". The useful rule is:
if multiple executions reuse the same CSV template but should see different
coarse tensor windows, put that variation in the instance row. If different PEs
or instructions in the same execution see different positions inside the same
window, put that variation in `imm`.

## Field/range constraints

Hard structural limits:

```text
tasks per app:                 4
subtasks per task:             8
instances per subtask:         2048
base slots per instance row:   4
valid base slot values:        0..3
LD/ST/STM/HSTT imm bits:       21
LD/ST/STM/HSTT imm range:      0..2,097,151 vendor words
RTL base row field bits:       21 per base slot
vendor word size:              4 bytes
```

Practical generator checks should therefore fail fast when:

- a memory CSV row selects a base slot outside `0..3`;
- a selected base slot is `0xffffffff`;
- an instruction offset is negative or larger than `2^21 - 1`;
- a base row value is neither invalid nor representable in the 21-bit RTL base
  field;
- `base + imm` points outside the tensor/window region the access claims to
  reference;
- a byte address or byte size is not 4-byte aligned for vendor base/imm fields;
- a dtype-specific element offset is converted with the wrong unit rule.

## Evidence from vendor runnable cases

`log10_test` uses a single subtask with `Instance Times : 2048`. Its instance
generator writes a row, then advances both input/output bases by:

```text
ROW_OFFSET = 32 * 8
```

This is the clean vendor pattern for a repeated template over coarse windows:
the template imm can stay small while the instance row advances the big window.

`gemm_template_fusion` uses per-subtask instance counts such as:

```text
subtask1: 1
subtask2: 4
subtask3: 1
```

Its instance generator advances A/B bases across K instances for the repeated
compute subtask. This shows that instance count is naturally a per-subtask fact,
not just a per-task fact.

## Fixed OpenFabric risk

The current `vendor_app_config.h` collapses instance count to:

```text
program.instance_count_for_task(task_id)
```

and applies that same value to every subtask. That is too weak for GEMM-like
cases and suspicious for any future multi-stage repeated body.

There was also a concrete log10max hazard in the generated package before the
per-subtask compact writer fix:

```text
app0.conf:
  subtask1 Instance Times : 1
  subtask2 Instance Times : 1
  subtask3 Instance Times : 1

instance_conf_info_file0.bin rows:
  row0 = (0, 131072, 32768, 49152)
  row1 = (32768, 163840, 65536, 65536)
  row2 = (32768, 163840, 65536, 65536)
```

The corrected interpretation is that the global instance file still preserves
fixed task/subtask slots. For each task file:

```text
subtask0 block: 2048 rows
subtask1 block: 2048 rows
...
subtask7 block: 2048 rows
```

Within each subtask's 2048-row block, only the first `Instance Times` rows are
active and compact. Padding rows after the active rows must not keep generating
shifted valid addresses. OpenFabric now emits invalid padding rows there, so an
accidental overrun fails loudly instead of reading a plausible but wrong tile.

For GEMM/GEMM+ReLU, the writer must receive the derived per-subtask instance
times, such as `{1, 4, 1}`, instead of falling back to the old per-task default.

The writer now also checks these fail-fast conditions:

- active instance count must be `0..2048`;
- non-invalid base row fields must fit the 21-bit RTL base field;
- odd RTL row counts are flushed by pairing the final row with an invalid
  padding row in the RTL text file, although normal fixed subtask blocks are
  even-sized.
