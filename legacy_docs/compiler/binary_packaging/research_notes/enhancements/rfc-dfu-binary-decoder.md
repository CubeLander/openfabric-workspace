# RFC: Generic DFU Binary Decoder And Tester Contract

## Status

Accepted direction; approve Phase 0 through Phase 2 after the tester/profile
contract in this revision is implemented.

Date: 2026-06-21

Review integration status:

```text
Accepted:
  - generalize decoder as DFU profile-driven core; DFU3500 is the first profile
  - split library from thin CLI
  - add tester contract before B-line guard integration
  - add profile self-proof metadata and source refs
  - define JSON schema, exit codes, lookup classifications, and diff kinds early
  - use synthetic fixtures as primary unit tests
  - keep Phase 3 diff scheduled, but do not attach B-line guard before strict policy exists

Deferred:
  - arch-13 alternate profile until remote layout evidence exists
  - exact PE coordinate order until source/serializer proof exists
  - true active row semantics until RuntimeControlPlan / package verifier owns it
  - RTL narrow instruction decode

Rejected:
  - decoder as second serializer
  - parser-generated layout as Phase 1 authority
  - regex-only field paths in JSON
```

Owner area:

```text
compiler/gpdpu_compiler/decoder/binary_layout.py
compiler/gpdpu_compiler/decoder/binary_decoder.py
compiler/gpdpu_compiler/decoder/binary_diff.py
compiler/gpdpu_compiler/decoder/profiles/dfu3500.py
compiler/tools/decode_dfu_binary.py
compiler/tests/tools/test_decode_dfu_binary_*.py
```

Related homework:

```text
BIN-002 reusable CBUF/MICC decoder
BIN-013 struct layout decoder for subtask-embedded exeBlocks
BIN-014 source-version audit discipline
```

## Summary

OpenFabric needs a local, profile-driven DFU binary decoder.  Its first profile
will decode DFU3500 `cbuf_file.bin`, `micc_file.bin`, and component files into
field-named reports.  The tool must make byte diffs explainable at the section/row/field level:

```text
raw offset 0x42aa8
  -> cbuf.insts[pe_index=?][inst_idx=?].<field>
  -> field value local=110 vendor=111
```

The decoder is a diagnostic and validation tool, not a second serializer.  It
consumes explicit, source-backed DFU target profile/layout metadata and decodes
existing binary files into deterministic text/JSON reports.  It must not silently
infer ABI facts from bytes when metadata is missing.

The important addition in this revision is that the decoder is also a tester
contract.  Before the tool becomes a B-line runnable-package guard, it must have
stable profile provenance, JSON schema, exit-code policy, lookup classifications,
diff classifications, and synthetic fixture tests.  A decoder with a crooked
ruler is worse than no decoder; it creates false confidence with field names.

## Current State

Binary knowledge is now centralized under docs:

```text
docs/runtime/data/cbuf.md
docs/runtime/data/micc.md
docs/compiler/binary_packaging/README.md
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_vendor_struct_layout_audit.md
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_remaining_binary_research_homework.md
```

Known local DFU3500 layout facts, which should become the first profile, include:

```text
inst_t                       = 304 bytes
exeBlock_conf_info_t          = 520 bytes
instance_conf_info_t          = 32 bytes
task_conf_info_t              = 120 bytes
sub_task_conf_info_t          = 266,328 bytes

insts_file.bin                = 21,168,128 bytes
exeblock_conf_info_file.bin    = 266,240 bytes
instance_conf_info_file.bin    = 2,097,152 bytes
cbuf_file.bin                 = 23,531,520 bytes

tasks_conf_info_file.bin      = 480 bytes
subtasks_conf_info_file.bin   = 8,522,496 bytes
micc_file.bin                 = 8,522,976 bytes
```

A-line pain was not “we had no bytes”.  We had too many bytes and too few field
names.  We repeatedly stared at raw offsets such as `0x130` strides and only
later proved that `0x130 == sizeof(inst_t)`.  That is exactly the failure this
decoder must prevent.

## Problem

Current binary debugging still relies on ad-hoc scripts and manual offset
reasoning:

```text
byte diff
  -> offset list
  -> human guesses row stride
  -> human maps offset to struct field
  -> maybe discovers wrong active task count / padded row assumption later
```

This fails in several ways:

1. Raw byte offsets hide whether a mismatch belongs to instruction rows, block
   rows, instance base rows, task rows, subtask control, or embedded exeBlock rows.
2. Padded-capacity rows and active rows are easy to confuse.
3. CBUF address-space macro ranges and emitted file layout are easy to merge by
   accident.
4. Local source headers, OCR headers, and remote arch-13 source may diverge; a
   decoder without source/profile fingerprints turns version ghosts into false
   certainty.
5. Offset lookup and diff boundaries are off-by-one prone.  If tests do not cover
   section edges, padding, arrays, nested structs, and unknown ranges, the tool
   becomes a crooked measuring stick.
6. B-line agents need a field-level oracle before touching binary emission.  If
   they must reverse raw offsets again, B-line inherits A-line’s mud.

## Goals / Non-goals

### Goals

- Decode DFU-family binary component files into named sections, rows, and fields.
  The first implemented profile is DFU3500 CBUF/MICC/component layout.
- Decode both final concatenated files and individual component files.
- Provide text output for humans and deterministic JSON output for tests/subagents.
- Provide offset lookup with field/padding/unknown classification.
- Provide field-aware diff mode with raw byte counts preserved.
- Provide a tester contract: synthetic fixtures, JSON schema, exit codes, and
  strict/flexible policies for padding and unknown ranges.
- Make active-vs-padded rows visible without pretending heuristics are runtime
  control semantics.
- Make section boundary and fixed-size guards fail closed.
- Carry profile id, profile hash, source fingerprints, and field provenance in
  reports.
- Be useful locally without arch-13 or closed runtime access.

### Non-goals

- Do not implement a new binary serializer.
- Do not mutate binary files in the first phase.
- Do not infer unknown fields by pattern matching and present them as facts.
- Do not decode RTL narrow instruction format in the first phase; `inst_t` is the
  simulator/component wide row.
- Do not require vendor C++ compilation for normal decode usage.
- Do not require arch-13 layout confirmation before local decoder Phase 0/2; if
  arch-13 differs, add a separate profile.
- Do not let decoder heuristics become runtime active-count authority.
- Do not generalize beyond the DFU binary package family.  This is not a CUDA/CANN
  or arbitrary executable parser; it is a profile-driven DFU binary decoder.

## Proposed Design

### 1. Generic DFU Core, Target Profiles At The Edge

The decoder architecture has two layers:

```text
DFU binary decoder core
  = profile-driven section / row / field decoding machinery
  = does not hardcode CBUF, MICC, inst_t, task_conf_info_t, or DFU3500 capacities

DFU target profile
  = declares file kinds, section layouts, struct layouts, field provenance,
    dimension formulas, size guards, source fingerprints, and target-specific names
```

DFU3500 is the first target profile, not the decoder itself.  The generic core
should be able to decode any future DFU-family binary package once that package
provides a complete enough `DfuBinaryProfile`.  Conversely, if a concept is only
true for DFU3500, it belongs in `decoder/profiles/dfu3500.py`, not in the
generic decoder machinery.

Authority boundary:

```text
DfuBinaryProfile
  = semantic source of truth for binary layout

DfuBinaryDecoder / DfuBinaryDiff
  = generic interpreters of the selected profile

DFU3500 profile
  = first concrete profile, carrying CBUF/MICC/component names and constants
```

This keeps the design DFU-first without freezing the tool to the exact DFU3500
component names.  In practice Phase 0/2 only ships the DFU3500 profile, but the
shape of the implementation should make `target="dfu3500"` a parameter rather
than a class name baked into every API.

### 2. Decoder Package Owns Diagnostic Decoding

Put the implementation under `compiler/gpdpu_compiler/decoder/`, not under
`core/`.  The reason is architectural: decoding is a diagnostic / validation
service over emitted artifacts.  It is not a lowering pass, semantic IR layer, or
target serializer.

Recommended package shape:

```text
compiler/gpdpu_compiler/decoder/
  __init__.py
  binary_layout.py      # generic profile/layout schema
  binary_decoder.py     # generic decode engine
  binary_diff.py        # generic diff engine
  profiles/
    __init__.py
    dfu3500.py          # first concrete profile
```

This gives us one obvious home for future decoder-only utilities without
polluting `core` lowering modules.  The package name is intentionally `decoder`,
not `dfu_decoder`: the package can hold all compiler-owned artifact decoders,
while this RFC only defines the DFU binary decoder inside it.

### 3. Split Library From Thin CLI

Use a library-first shape:

```text
compiler/gpdpu_compiler/decoder/binary_layout.py
  -> compiler/gpdpu_compiler/decoder/binary_decoder.py
  -> compiler/gpdpu_compiler/decoder/binary_diff.py
  -> compiler/gpdpu_compiler/decoder/profiles/dfu3500.py
  -> compiler/tools/decode_dfu_binary.py
  -> tests / B-line validation hooks / subagent tools
```

Responsibilities:

```text
binary_layout.py
  profile metadata, struct layouts, section layouts, dimension formulas,
  source fingerprints, profile hash

binary_decoder.py
  section split, size guard, offset lookup, row decode, summary generation,
  deterministic decode report objects

binary_diff.py
  field-aware diff, diff classification, byte diff count preservation,
  strict/relaxed policy decisions

compiler/tools/decode_dfu_binary.py
  argparse, file reads, profile selection, JSON/text rendering, exit codes
```

The CLI must stay thin.  B-line guards and tests should import the library API,
not subprocess the CLI as their primary integration.

### 4. Layout Metadata Is Source Of Truth

The metadata should be declarative and explicit:

```python
DfuBinaryProfile(
    schema_version="dfu_binary_profile_v1",
    target="dfu3500",
    profile_id="dfu3500_local_common_src_2026_06_20",
    profile_sha256="...",  # hash of canonical metadata content
    layout_status="complete_for_known_fields",
    source_fingerprints={
        "common/src/inst_def.h": "b263f25e...",
        "common/src/pe_com_def.h": "2d06ba8...",
        "common/src/dma_com_def.h": "42bd059...",
        "common/src/basic_def.h": "a336aca...",
    },
    endian="little",
    capacities=DfuTargetCapacities(...),
    structs={...},
    files={...},
)
```

Struct descriptors should spell out offsets, scalar widths, arrays, nested
structs, field status, and source refs.  They should not use Python `ctypes` as
the authority, because `ctypes` can hide alignment assumptions.  The profile
should encode known compiled offsets explicitly.

Example shape:

```python
StructLayout(
    name="inst_t",
    size=304,
    fields=(
        Field(
            name="opCode",
            offset=0,
            type="u32",
            count=1,
            status="source_backed",
            source_ref=SourceRef(
                file="common/src/inst_def.h",
                symbol="inst_t::opCode",
                evidence="local_common_src_2026_06_20",
            ),
        ),
        Field("unit_inst_type", offset=8, type="u64", status="source_backed", ...),
        Field("imms", offset=24, type="u64", count=3, status="source_backed", ...),
        Field("dst_pes_pos", offset=96, type="position_t", count=3, status="source_backed", ...),
    ),
)
```

Field status should be an explicit enum:

```text
source_backed
known_padding
reserved_unknown
unsupported
```

Reports may decode `source_backed` fields.  They may classify padding.  They
must not print `reserved_unknown` as if it were understood.

### 5. Section And Dimension Layouts Live In The Profile

Section split and row indexing formulas must not be scattered through decoder
logic.  Model sections declaratively:

```python
SectionLayout(
    file_kind="cbuf",
    name="insts",
    component="insts",
    offset=0,
    size=21168128,
    row_struct="inst_t",
    dimensions=(
        Dimension("pe_index", 16, coordinate_status="index_only"),
        Dimension("inst_idx", 4352),
    ),
)
```

Representative formulas:

```text
insts:
  row_index = pe_index * inst_per_pe + inst_idx

exeblocks:
  row_index = pe_index * block_per_pe + block_idx

instances:
  row_index = ((task * subtask_per_task) + subtask) * instance_per_subtask + instance

subtasks:
  row_index = task * subtask_per_task + subtask
```

PE coordinate order is not yet accepted as a known semantic field.  Phase 1 may
show `pe_index`; `--pe x,y` should either be unsupported or emit a diagnostic
until PE order is verified by source/serializer evidence.

### 6. Decoder CLI

Add one local tool:

```text
compiler/tools/decode_dfu_binary.py
```

Initial CLI:

```bash
python3 compiler/tools/decode_dfu_binary.py \
  --profile dfu3500_local_common_src_2026_06_20 \
  --kind cbuf \
  --input path/to/cbuf_file.bin \
  --summary

python3 compiler/tools/decode_dfu_binary.py \
  --kind micc \
  --input path/to/micc_file.bin \
  --offset 0x42aa8 \
  --format json

python3 compiler/tools/decode_dfu_binary.py \
  --kind component \
  --component insts \
  --input path/to/insts_file.bin \
  --row 18

python3 compiler/tools/decode_dfu_binary.py \
  --left ours/micc_file.bin \
  --right vendor/micc_file.bin \
  --kind micc \
  --diff \
  --format text
```

Profile commands:

```bash
--list-profiles
--dump-profile
--verify-source-fingerprints PATH_TO_SOURCE_ROOT
```

Output limiting:

```bash
--row 18
--row-range 0:32
--only-nonzero
--field opCode
--max-records 200
--all
```

Default behavior should avoid JSON avalanches:

```text
summary: aggregate only
offset: target offset only
row: selected row only
diff: summary + first N diff records unless --all
```

### 7. JSON Schema V1

Decode report minimum schema:

```json
{
  "schema_version": "dfu_binary_decode_report_v1",
  "tool": {
    "name": "decode_dfu_binary",
    "version": "0.1.0"
  },
  "profile": {
    "target": "dfu3500",
    "profile_id": "dfu3500_local_common_src_2026_06_20",
    "profile_sha256": "...",
    "source_fingerprints": {}
  },
  "input": {
    "path": "...",
    "sha256": "...",
    "size": 23531520,
    "kind": "cbuf"
  },
  "status": "ok",
  "sections": [],
  "records": [],
  "diagnostics": []
}
```

Diff report minimum schema:

```json
{
  "schema_version": "dfu_binary_diff_report_v1",
  "tool": {"name": "decode_dfu_binary", "version": "0.1.0"},
  "profile": {"target": "dfu3500", "profile_id": "...", "profile_sha256": "..."},
  "left": {"path": "...", "sha256": "...", "size": 8522976},
  "right": {"path": "...", "sha256": "...", "size": 8522976},
  "same_size": true,
  "byte_diff_count": 14944,
  "field_diff_count": 123,
  "padding_diff_count": 0,
  "unknown_range_diff_count": 0,
  "diffs": [],
  "diagnostics": []
}
```

JSON output must be deterministic: stable list order, sorted object keys where
appropriate, and no unordered set serialization.

### 8. Field Path Model: String Plus Tokens

Every decoded value should have both a human string path and structured tokens:

```json
{
  "path": "cbuf.insts[pe_index=0][inst_idx=18].opCode",
  "path_tokens": [
    {"kind": "file", "name": "cbuf"},
    {"kind": "section", "name": "insts"},
    {"kind": "index", "name": "pe_index", "value": 0},
    {"kind": "index", "name": "inst_idx", "value": 18},
    {"kind": "field", "name": "opCode"}
  ]
}
```

String paths are for humans.  Token paths are for tests, subagents, and future
aggregation.  Do not force consumers to regex field names out of a pretty string.

### 9. Offset Lookup Semantics

Offset lookup should report byte-in-field semantics, not just a field name:

```text
input_offset        = 0x42aa8
section             = cbuf.insts
section_offset      = 0x42aa8
row_index           = 2246
row_offset          = 0x18
struct              = inst_t
field               = imms[0]
field_type          = u64
field_abs_offset    = 0x42aa0
field_row_offset    = 0x18
byte_index_in_field = 0
field_size          = 8
field_value_dec     = 110
field_value_hex     = 0x000000000000006e
classification      = known_field
```

Classification enum:

```text
known_field
known_padding
unknown_range
out_of_bounds
size_mismatch
```

If the offset lands in alignment/padding, report padding explicitly.  If the
profile lacks field metadata, report `unknown_range`.  Do not guess.

### 10. Summary Mode

Summary mode should catch common A-line bug classes quickly:

```text
file: cbuf_file.bin
profile: dfu3500_local_common_src_2026_06_20
size: 23531520 OK
sections:
  insts: offset=0 size=21168128 rows=69632 row_size=304
  exeblocks: offset=21168128 size=266240 rows=512 row_size=520
  instances: offset=21434368 size=2097152 rows=65536 row_size=32

active-ish summary:
  heuristic: nonzero markers only; not RuntimeControlPlan verified
  inst rows with opCode != 0: ...
  exeblock rows valid != 0: ...
  instance rows with any base_addr != 0: ...
```

JSON must make the heuristic explicit:

```json
{
  "summary_kind": "heuristic_nonzero_markers",
  "control_semantics_verified": false
}
```

True activity belongs to `RuntimeControlPlan` / package validation, not decoder
core.  The decoder may expose evidence; it must not become the control-plane
authority.

### 11. Diff Mode

Diff mode should group by field path while preserving raw byte counts.  Define
diff kind before formatting:

```text
value_diff          known decoded field value differs
raw_only_diff       raw bytes differ but decoded semantic value is the same
padding_diff        known padding bytes differ
unknown_range_diff  profile has no source-backed field mapping
length_diff         file sizes differ
section_diff        section boundary or component-size policy differs
```

Diff records should include decoded values and raw bytes:

```json
{
  "diff_kind": "value_diff",
  "path": "micc.tasks[task=0].subtasks_amount",
  "left": {
    "value": 1,
    "raw_hex": "0100000000000000"
  },
  "right": {
    "value": 4,
    "raw_hex": "0400000000000000"
  },
  "byte_diff_count": 1
}
```

Policy flags:

```bash
--fail-on-diff
--strict-padding
--ignore-padding-diff
--fail-on-unknown-range
```

Default behavior:

```text
padding diffs are reported and counted as warnings, not silently ignored
unknown range diffs are reported and counted separately
CI/B-line guard may choose strict policy explicitly
```

### 12. CLI Exit Codes

Exit codes:

```text
0  command succeeded, no fatal diagnostic
1  diff found when --fail-on-diff is set, or validation failed under requested policy
2  usage error / invalid args
3  input file size/profile mismatch
4  internal decoder/profile invariant violation
```

Diff commands do not return `1` merely because files differ unless `--fail-on-diff`
or another `--fail-on-*` policy is set.  This keeps local exploration and CI gates
separate.

### 13. Decoder Does Not Become Serializer

The decoder may share layout metadata with future serializers, but it must not
import serializer implementation code or call binary emitters.  Dependency flows:

```text
DfuBinaryProfile
  -> generic decoder
  -> serializer guards / tests
```

not:

```text
serializer internals
  -> decoder guesses what serializer meant
```

## Invariants

1. File sizes must match the selected profile unless an explicit debug override
   is provided.
2. Every decoded field path must be derived from profile metadata, not guessed
   from raw strides.
3. Every report must include `profile_id`, `profile_sha256`, and source
   fingerprints.
4. Every decoded field must have a status; unknown/reserved ranges must stay
   unknown.
5. Final concatenated file offsets must be convertible to component offsets.
6. Component offsets must be convertible to row index + row offset.
7. Row offsets must be convertible to field path, padding, or unknown range.
8. Offset lookup must include classification and byte-in-field metadata.
9. Diff mode must preserve raw byte counts while adding field-level grouping.
10. Diff records must classify `value_diff`, `padding_diff`, `unknown_range_diff`,
    `raw_only_diff`, `length_diff`, or `section_diff`.
11. JSON output must be deterministic and schema-versioned.
12. Decoder implementation must be read-only with respect to input binaries.
13. Synthetic fixture tests must not depend on the serializer generating the same
    bytes.
14. B-line guard integration is forbidden until JSON schema, exit codes, and diff
    policy flags are implemented.

## Alternatives Considered

### Continue using byte-diff scripts only

Rejected.  This is exactly how A-line lost time: diffs were structured but not
named.  Raw offsets are useful evidence, not a sufficient interface.

### Generate decoder directly from C headers

Deferred.  Header parsing sounds elegant, but C alignment, local/remote source
version drift, and OCR-vs-clean header ambiguity make it risky as Phase 1.  Use
explicit checked layout metadata first.  A future helper can regenerate metadata
from audited C if needed.

### Use Python `ctypes.Structure` as the layout authority

Rejected for Phase 1.  `ctypes` can validate sizes, but it should not hide the
field table.  We want field offsets reviewable in normal code and docs.

### Decode only final `cbuf_file.bin` / `micc_file.bin`

Rejected.  Component files are the natural unit for comparing OpenFabric, vendor
`simulator_bin`, and final concatenated runtime files.  The decoder must support
both.

### Build this as a B-line pass

Rejected.  Decoder is tooling.  B-line can consume decoder reports and tests,
but binary decoding should not become part of semantic lowering.

## Migration / Implementation Plan

### Phase 0: Layout metadata skeleton

- Add decoder package skeleton under `compiler/gpdpu_compiler/decoder/`.
- Add generic layout/profile schema in `compiler/gpdpu_compiler/decoder/binary_layout.py`.
- Add the first concrete DFU3500 profile in
  `compiler/gpdpu_compiler/decoder/profiles/dfu3500.py`.
- Encode sizes/offsets for:
  - `position_t`
  - `inst_t`
  - `instance_conf_info_t`
  - `exeBlock_conf_t`
  - `exeBlock_conf_info_t`
  - `task_conf_info_t`
  - `sub_task_conf_info_t`
- Encode DFU3500 component file sizes, final file section boundaries, and row
  dimensions in the DFU3500 profile, not in generic decoder code.
- Add generic profile provenance fields:
  - `schema_version`
  - `profile_id`
  - `profile_sha256`
  - `layout_status`
  - source fingerprints
  - field `source_ref` and field status
- Add invariant tests for formulas:

```text
16 * 4352 * 304 = 21,168,128
16 * 32 * 520 = 266,240
4 * 8 * 2048 * 32 = 2,097,152
4 * 120 = 480
32 * 266,328 = 8,522,496
```

### Phase 0.5: Tester contract foundation

- Add library shell under `compiler/gpdpu_compiler/decoder/`:
  - `binary_decoder.py`
  - `binary_diff.py`
- Define JSON schema v1 dataclasses or dict builders.
- Define exit codes and CLI policy flags.
- Add synthetic fixture helper:

```text
compiler/tests/tools/fixtures/dfu_binary_fixtures.py
```

- Synthetic fixtures must use `bytearray(expected_size)` and patch known field
  offsets.  They must not call the serializer.

### Phase 1: Summary and offset lookup

- Add thin CLI `compiler/tools/decode_dfu_binary.py`.
- Support:
  - `--kind cbuf|micc|component`
  - `--component insts|exeblocks|instances|tasks|subtasks`
  - `--profile`, `--list-profiles`, `--dump-profile`
  - `--summary`
  - `--offset`
  - `--format text|json`
- Implement lookup classification:
  - `known_field`
  - `known_padding`
  - `unknown_range`
  - `out_of_bounds`
  - `size_mismatch`

### Phase 2: Row decode and deterministic JSON

- Support selecting rows by index and logical dimensions where verified.
- Decode nested fields and arrays.
- Emit deterministic JSON for tests.
- Add controls:
  - `--row`
  - `--row-range`
  - `--only-nonzero`
  - `--field`
  - `--max-records`
  - `--all`

### Phase 3: Field-aware diff

- Add `--left`, `--right`, `--diff`.
- Preserve raw byte diff count.
- Add diff kinds:
  - `value_diff`
  - `raw_only_diff`
  - `padding_diff`
  - `unknown_range_diff`
  - `length_diff`
  - `section_diff`
- Add strict/relaxed policy flags.
- Validate on synthetic mutations before using real vendor comparisons.

### Phase 4: B-line integration hooks

- Add checks that B-line emitted component files decode cleanly before they can
  claim `runtime_runnable=true`.
- Add optional snapshot artifacts:

```text
simulator_bin.decode.json
cbuf.decode.summary.txt
micc.decode.summary.txt
```

These are validation/debug artifacts, not runtime inputs.

## Validation Plan

### Test file layout

```text
compiler/tests/tools/test_decode_dfu_binary_layout.py
compiler/tests/tools/test_decode_dfu_binary_lookup.py
compiler/tests/tools/test_decode_dfu_binary_summary.py
compiler/tests/tools/test_decode_dfu_binary_diff.py
compiler/tests/tools/fixtures/dfu_binary_fixtures.py
```

### Layout tests

- Struct size formula.
- Field within bounds.
- Nested struct span within bounds.
- Array span within bounds.
- Padding range generated correctly.
- Section ranges exactly cover final file.
- Profile hash changes when canonical layout metadata changes.

### Offset lookup tests

- First byte of each section.
- Last byte of each section.
- Boundary byte before/after section.
- First/last byte of representative fields.
- Byte inside multi-byte scalar.
- Byte inside array element.
- Byte inside nested struct.
- Byte inside known padding.
- Byte inside unknown profile gap.
- Out-of-bounds offset.

### Summary tests

- All-zero valid-size file.
- One nonzero inst row.
- One nonzero task row.
- Padded row contains unexpected nonzero marker.
- Summary explicitly says `control_semantics_verified=false` for heuristic rows.

### Diff tests

- Same-size no diff.
- Size mismatch.
- One byte changed in scalar field.
- Multi-byte scalar changed.
- Padding byte changed.
- Unknown range changed.
- Nested field changed.
- Array element changed.
- `--fail-on-diff` exit behavior.
- `--strict-padding` exit behavior.
- `--fail-on-unknown-range` exit behavior.

### Golden binary validation

Use existing known-good files only as a secondary validation layer:

```text
simict3500final/.../application/gemm_template_fusion/result/cbuf_file.bin
simict3500final/.../application/gemm_template_fusion/result/micc_file.bin
compiler validation payloads, if present
```

Expected:

```text
size guard passes
section split passes
summary prints active-ish indicators
no decode exception
```

Golden binary validation is not enough on its own.  Synthetic fixtures are the
primary correctness tests because they can hit edges that real binaries may not.

## Risks and Mitigations

### Risk: profile layout differs on arch-13

Mitigation: every report includes `profile_id`, `profile_sha256`, and source
fingerprints.  If arch-13 differs, add a second profile.  Do not silently mutate
the local profile.

### Risk: PE ordering is guessed wrong

Mitigation: expose `pe_index` first.  Add `pe_coord` only after source or known
serializer evidence proves ordering.  `--pe x,y` should be unsupported until then.

### Risk: active row inference becomes a second control model

Mitigation: early summaries call this `active-ish` and set
`control_semantics_verified=false`.  True active predicates must be tied to
`RuntimeControlPlan` / task/subtask control semantics before being used as guards.

### Risk: decoder duplicates serializer constants and drifts

Mitigation: layout metadata should become shared read-only profile data.  Both
decoder and serializer guards can consume it; neither owns it privately.

### Risk: JSON output becomes unstable and useless for tests

Mitigation: schema version, stable ordering, canonical profile hash, and sorted
object keys where appropriate.

### Risk: full decode creates huge reports

Mitigation: default output is bounded.  Full dumps require `--all` or explicit row
ranges.

## Expected Effect

After Phase 3, future binary debugging should look like this:

```text
1. Run byte/field diff.
2. See exact component, row, and field names.
3. Decide whether mismatch belongs to:
   - instruction binding,
   - route endpoint patching,
   - task/subtask control,
   - instance base table,
   - padded capacity rows,
   - padding / unknown profile area,
   - or source profile mismatch.
4. Fix the owner plan instead of hand-editing bytes.
```

This directly supports B-line by turning binary mud into typed feedback.  B-line
agents should not need to rediscover CBUF/MICC layout from raw offsets.

## Open Questions

1. What is the exact PE row order for `insts_file.bin` and
   `exeblock_conf_info_file.bin` in every profile we care about?
2. Which source-line breadcrumbs are worth filling in Phase 0 versus later?
3. Should padding diffs be strict by default for OpenFabric-vs-OpenFabric checks
   but warning by default for OpenFabric-vs-vendor checks?
4. Should arch-13 remote layout confirmation become a separate profile before
   decoder Phase 3, or can Phase 3 proceed under the local profile first?
5. How much of `task_print.cpp` active-row semantics should be encoded in the
   decoder versus left to a future `RuntimeControlPlan` verifier?

## Recommended Decision

Accept Phase 0 through Phase 2 after this revision’s tester contract is included
in the implementation plan:

```text
Phase 0:   layout metadata + profile provenance
Phase 0.5: tester contract + JSON schema + exit code + synthetic fixtures
Phase 1:   summary + section split + offset lookup
Phase 2:   row decode + deterministic JSON
```

Then implement Phase 3 field-aware diff before using the decoder as a B-line
runnable-package guard.

The first implementation should be small, explicit, and annoyingly honest.  If a
mapping is unknown, print `unknown`.  If a file size is wrong, fail.  If a field
layout lacks source-backed metadata, refuse to decode that field.  We have paid
enough tuition to the byte-offset goblin; this tool is where that tuition turns
into machinery.
