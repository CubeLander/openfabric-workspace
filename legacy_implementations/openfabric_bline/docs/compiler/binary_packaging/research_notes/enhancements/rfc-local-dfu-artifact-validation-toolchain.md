# RFC: Local DFU Artifact Validation Toolchain

## Status

Proposed for review.

## Summary

OpenFabric needs a local validation toolchain that can answer whether emitted DFU
artifacts are structurally sane before we upload them to partner runtime /
SimICT.  The existing generic DFU decoder is a good microscope: it can explain
CBUF/MICC bytes, map offsets to fields, diff payloads, and annotate opcodes.
But the project goal is broader than decoding.  We need a validation layer that
uses decoder reports to judge payload conformance, profile/source consistency,
package-control legality, and mainline payload readiness.

The decision under review is:

```text
Keep `compiler/gpdpu_compiler/decoder` as a read-only byte microscope.
Add validation/tester APIs under `compiler/gpdpu_compiler/validation` to judge
whether generated artifacts are correct enough for the requested workflow.
```

In short:

```text
decoder explains bytes
validation judges artifacts
```

## Current State

### Decoder

Current implementation lives under:

```text
compiler/gpdpu_compiler/decoder/
compiler/tools/decode_dfu_binary.py
compiler/tools/compare_dfu_payloads.py
```

It currently provides:

```text
implemented:
  CBUF/MICC/component layout decode
  known field offsets and padding/unknown classification
  row decode
  byte offset lookup
  field-aware diff
  deterministic JSON schemas
  DFU3500 MICC active-ish diagnostics
  DFU3500 opCode -> mnemonic annotation

explicitly diagnostic-only:
  source fingerprints are embedded but not verified against local files
  active-ish rows are visible but not runtime truth
  manifest/file-size conformance is reported by compare tooling

explicitly out of decoder scope:
  RISC-V DMA/start/wait/finish correctness
  operand/template runnable proof
  route/resource semantic ownership proof
```

The decoder also has a coverage command:

```bash
python compiler/tools/decode_dfu_binary.py --coverage
```

This is useful, but it is still a decoder-facing view.  It does not provide a
full local artifact validation contract.

### Validation

Current validation code lives under:

```text
compiler/gpdpu_compiler/validation/
  dfu3500_partner_validation/
```

This package builds payloads, stages runtime assets, and runs partner SimICT on arch-13.  It is already the right place for checks
whose purpose is:

```text
Is this payload locally complete and runtime-ready?
```

However, several checks are currently either ad hoc, CLI-only, or still only
written as notes:

```text
source fingerprint verification
payload file conformance
manifest / runtime asset consistency
active task/subtask chain legality
component rows vs control metadata consistency
```

## Problem

The decoder was created because previous manual payload development repeatedly failed in ways
that raw bytes could not explain quickly:

```text
wrong MICC task count
short or mis-staged MICC payload
padded rows accidentally treated as active work
manual task/subtask metadata drift
instruction rows with numeric opcodes but no readable owner/mnemonic
component file size assumptions copied by hand
```

The decoder solves the observability part.  But if we keep adding “is this
payload correct?” logic into decoder CLIs, the decoder will slowly become a
second serializer / runtime verifier.  That would repeat the same architecture
mistake that made previous payload painful: one tool would both interpret bytes and decide
semantic/runtime truth.

We need an explicit local toolchain boundary:

```text
1. decoder produces field-aware facts
2. validation consumes those facts and applies workflow-specific gates
3. partner runtime is only used after local checks have filtered obvious defects
```

Without this split, mainline compiler agents will either:

- keep uploading malformed payloads and debugging failures remotely; or
- overgrow decoder into a monolithic “binary oracle” that silently owns too many
  layers.

Both outcomes are bad.

## Goals / Non-goals

### Goals

1. Provide a local tester / validation toolchain for DFU artifacts.
2. Keep decoder as a read-only diagnostic library with stable JSON reports.
3. Move artifact correctness checks into `compiler/gpdpu_compiler/validation`.
4. Make validation reports explicit about `pass`, `fail`, `blocked`, and
   `diagnostic_only`.
5. Make payload construction consume validation APIs rather than ad-hoc CLI text.
6. Prevent known manual payload mistakes from reaching arch-13 runtime when they can be
   caught locally.

### Non-goals

1. Do not make decoder a serializer.
2. Do not prove operator/template correctness from byte decode alone.
3. Do not prioritize runtime in-flight message decoding; those messages are noisy
   and not current payload artifacts.
4. Do not move all existing partner validation scripts in one step.
5. Do not require full runnable proof before keeping decoder diagnostics useful.

## Reviewer Feedback Integrated

This revision incorporates review feedback that Phase 1 needs a gate/readiness
contract, not only a pile of check functions.  The central addition is a
`ReadinessLevel` model plus suite-level aggregation.  payload builders should ask
for a gate such as `package_complete` or `runtime_ready`; they should not manually
compose scattered checks and reinterpret their statuses.

## Proposed Design

### 1. Keep Decoder As Diagnostic Library

Keep these modules under `compiler/gpdpu_compiler/decoder`:

```text
binary_layout.py       profile/field/section schema
binary_decoder.py      summary, row decode, offset lookup
binary_diff.py         field-aware diff
coverage.py            decoder knowledge coverage report
profiles/dfu3500.py    DFU3500 SimICT legacy profile
dfu3500_isa.py         opcode mnemonic annotation
```

Decoder answers questions like:

```text
What file kind is this?
What section contains byte 0x1234?
Which row and field own this byte?
Is this byte in a known field, known padding, unknown range, or out of bounds?
Which field-level values differ between two payloads?
What mnemonic does opCode 0x27 name?
```

Decoder must not answer:

```text
Is this payload runnable?
Is this subtask graph legal?
Is this template a correct implementation of maximum/log10/GEMM?
Is this RISC-V control program correct?
```

### 2. Add Generic DFU Binary Validation Checks

Add a validation package:

```text
compiler/gpdpu_compiler/validation/dfu_binary_checks/
  __init__.py
  report.py
  source_fingerprint_check.py
  payload_conformance.py
  profile_conformance.py
```

Responsibilities:

```text
source_fingerprint_check.py:
  compare profile source_fingerprints against local vendor files
  distinguish missing source from hash mismatch
  never update profile hashes automatically

payload_conformance.py:
  check expected cbuf/micc/component files exist
  check file sizes match selected profile
  check MANIFEST claims agree with files when available
  check payload has expected local runtime assets before runtime staging

profile_conformance.py:
  validate profile struct sizes, field bounds, section coverage, and dimensions
  expose profile validation as a validation report, not only pytest assertions
```

These checks consume decoder profiles and reports; they do not duplicate decoder
logic.

### 3. Add DFU3500 Package / Control Checks

Add a DFU3500-specific validation package:

```text
compiler/gpdpu_compiler/validation/dfu3500_package_checks/
  __init__.py
  control_graph_check.py
  component_consistency_check.py
  runtime_readiness_check.py
```

Initial checks should cover the previous payload pain points:

```text
active task count matches declared package/control plan
active subtask chain has unique start/end
no bogus successor beyond active chain
active exeBlock rows have matching task_idx/subtask_idx stamps
stage PCs fit PE-local instruction rows
valid exeBlock rows do not point into padded instruction garbage
component files and runtime control metadata are same-source
```

This package may call decoder functions, but it owns validation semantics.  If a
check needs to interpret task graph legality, it belongs here, not in
`binary_decoder.py`.

### 4. Define Payload-Local Readiness Contract

Validation must be organized around payload-local readiness gates, not upload
actions or scattered checks.  The current practical gate model is:

```python
class ReadinessLevel(str, Enum):
    INSPECTABLE = "inspectable"
    PACKAGE_COMPLETE = "package_complete"
    RUNTIME_READY = "runtime_ready"
```

Intended meaning:

```text
inspectable:
  payload bytes can be decoded or diagnosed; missing runtime evidence may be tolerated

package_complete:
  final CBUF/MICC files exist, sizes match profile, and MANIFEST claims match actual files

runtime_ready:
  package_complete passes, runtime_control/input/output/reference metadata exists and is self-consistent
```

`runtime_ready` is not a proof that SimICT will pass or that the operator math is
correct.  It only proves the local payload has enough coherent runtime metadata
to be handed to the existing partner runtime workflow.

Each check should declare which gates it serves:

```python
@dataclass(frozen=True)
class CheckSpec:
    name: str
    applies_to: tuple[ReadinessLevel, ...]
    authoritative: bool
    default_policy: Mapping[str, object]
    required_inputs: tuple[str, ...]
```

Payload construction should call:

```python
validate_payload(..., requested_gate=ReadinessLevel.RUNTIME_READY)
```

It should not parse decoder CLI text or manually reinterpret individual check
statuses.

### 5. Define Validation Report Contract

Validation reports should use stable status values:

```text
pass:
  check proves the requested invariant

fail:
  check proves a violation

blocked:
  check cannot run because required evidence is missing

diagnostic_only:
  check reports useful facts but is not authoritative for the requested gate
```

Suggested common shape:

```python
@dataclass(frozen=True)
class ValidationIssue:
    severity: Literal["info", "warning", "error"]
    code: str
    message: str
    path: str | None = None
    details: Mapping[str, object] = field(default_factory=dict)

@dataclass(frozen=True)
class ValidationReport:
    schema_version: str
    check_name: str
    status: Literal["pass", "fail", "blocked", "diagnostic_only"]
    authoritative: bool
    requested_gate: ReadinessLevel | None
    profile_id: str | None
    profile_sha256: str | None
    input_paths: tuple[str, ...]
    input_sha256: Mapping[str, str]
    policy: Mapping[str, object]
    issues: tuple[ValidationIssue, ...]

@dataclass(frozen=True)
class ValidationSuiteReport:
    schema_version: str
    requested_gate: ReadinessLevel
    final_status: Literal["pass", "fail", "blocked"]
    artifact_root: str
    manifest_path: str | None
    created_at_utc: str
    reports: tuple[ValidationReport, ...]
```

Suite aggregation rules:

```text
authoritative fail    -> final_status = fail
authoritative blocked -> final_status = blocked
diagnostic_only       -> never makes suite pass by itself
no authoritative checks for requested gate -> final_status = blocked
```

CLI exit codes should be consistent:

```text
0: all requested authoritative checks pass
1: authoritative check failed
2: usage error
3: missing input / size or profile mismatch
4: internal invariant error
```

### 6. Keep CLIs Thin

Current CLIs may remain for humans:

```text
compiler/tools/decode_dfu_binary.py
compiler/tools/compare_dfu_payloads.py
```

But reusable guard logic should move under `validation`.  For example,
`compare_dfu_payloads.py` can remain a diagnostic CLI while its conformance logic
is progressively factored into:

```text
validation/dfu_binary_checks/payload_conformance.py
```

### 7. Payload Build Integration

Integrate local validation directly after payload construction:

```text
build payloads
  -> write MANIFEST and runtime metadata
  -> run payload-local validation checks
  -> archive validation report beside payload
  -> partner runtime workflow consumes the validated payload
```

There is no separate upload gate in the current design.  Compression, copying,
uploading, and arch-13 execution should consume the payload-local validation
report instead of reinterpreting files.

Suggested gate order inside `validate_payload(..., RUNTIME_READY)`:

```text
1. profile_conformance
2. source_fingerprint_check as diagnostic provenance unless explicitly strict
3. payload_conformance
4. runtime_readiness
5. future dfu3500_package_checks when task graph semantics become blocking
```

## Payload Manifest / Readiness Claim Contract

A payload must not become `runtime_ready` by filename, sidecar presence, or
active-ish nonzero rows.  The intended readiness must be explicit metadata.  The
minimum manifest contract should look like:

```json
{
  "schema_version": "dfu_payload_manifest_v1",
  "artifact_kind": "dfu3500_payload",
  "profile_id": "dfu3500_simict_legacy_2026_06_20",
  "readiness_claim": "runtime_ready",
  "build_id": "...",
  "control_plan": {
    "path": "runtime_control_plan.json",
    "sha256": "..."
  },
  "files": {
    "cbuf_file.bin": {"role": "cbuf", "sha256": "...", "size": 23531520},
    "micc_file.bin": {"role": "micc", "sha256": "...", "size": 8522976}
  }
}
```

Rules:

```text
missing readiness_claim -> not runtime_ready
missing control_plan under runtime_ready -> blocked
manifest hash/size mismatch -> fail
sidecar-only readiness claim -> fail
```

## Invariants

1. Decoder is read-only and never writes binary payloads.
2. Decoder reports unknown/padding explicitly; it never guesses fields.
3. Validation checks consume decoder facts but own pass/fail semantics.
4. Active-ish rows are not runtime truth.
5. Sidecars do not imply runtime readiness.
6. Runtime messages are out of the payload decoder priority path.
7. Opcode mnemonic annotation does not prove template legality.
8. Payload-local validation must fail locally for known malformed payload shapes.

## Source Fingerprint Policy By Gate

Default source fingerprint policy should depend on requested gate:

| Gate | Default policy | Rationale |
| --- | --- | --- |
| `inspectable` | `warn` or `missing-ok` | Byte inspection should work even without vendor source checkout. |
| `package_complete` | `warn` | Packaging can be checked while source evidence is still being staged. |
| `runtime_ready` | `warn` by default | Runtime metadata checks are payload-local; source audit can be made strict explicitly. |

Every report must state the policy and its source:

```json
{
  "check_name": "source_fingerprint_check",
  "policy": {
    "mode": "strict",
    "source": "gate_default",
    "requested_gate": "runtime_ready"
  }
}
```

## Alternatives Considered

### Alternative A: Put All Checks In Decoder

Rejected.

This would make decoder a second serializer/runtime oracle.  It would also blur
the boundary between facts about bytes and judgments about runnable artifacts.
That is exactly the style of technical debt previous manual payload path exposed.

### Alternative B: Keep Validation As Shell Scripts Only

Rejected.

Shell wrappers are useful for arch-13 orchestration, but they are not good owners
for structured checks, JSON reports, profile provenance, or pytest coverage.

### Alternative C: Move Decoder Under Validation

Deferred / not recommended now.

The decoder is useful as a generic library independent of any one validation
workflow.  Keeping it under `compiler/gpdpu_compiler/decoder` preserves reuse,
while validation packages consume it.

### Alternative D: Prioritize Runtime Message Decoding

Rejected for current phase.

Runtime messages are in-flight simulator/control structs, not emitted payload
images.  They are noisy and do not address the current mainline artifact validation
bottleneck.

## Migration / Implementation Plan

### Phase 0: Document Boundary

- Keep decoder coverage map current.
- Add this RFC.
- Keep `compiler/notes/decoder/validation_reorg_plan.md` as working notes until
  implementation catches up.

### Phase 1: Generic Checks + Readiness Contract

Add:

```text
validation/dfu_binary_checks/report.py
validation/dfu_binary_checks/profile_conformance.py
validation/dfu_binary_checks/payload_conformance.py
validation/dfu_binary_checks/source_fingerprint_check.py
```

Also add:

```text
ReadinessLevel
ValidationSuiteReport
validate_payload(..., requested_gate=...)
suite aggregation tests
JSON schema / exit code contract tests
```

Wire tests with synthetic fixtures, not serializer-generated files only.

### Phase 2: Payload Build Integration

- Make payload construction call validation APIs after manifest/runtime metadata generation.
- Archive `validation/runtime_ready.json` beside each payload.
- Keep decoder CLI for byte-level interactive debugging.

### Phase 3: DFU3500 Control Checks

Add:

```text
validation/dfu3500_package_checks/control_graph_check.py
validation/dfu3500_package_checks/component_consistency_check.py
```

Start with report-only mode, then make checks blocking for payloads that request the `runtime_ready` gate.

### Phase 4: Mainline Consumption

- Use validation reports as the payload-local source of truth in mainline workflows.
- Archive failure reports alongside payload build artifacts.
- Keep remote arch-13 failures focused on runtime/simulator behavior, not local
  payload construction mistakes.

## Validation Plan

Test categories:

```text
profile conformance:
  struct size formula
  fields within bounds
  nested struct spans
  section coverage
  profile sha stability

payload conformance:
  missing cbuf/micc
  short micc/cbuf
  component size mismatch
  manifest/file disagreement
  missing runtime assets before runtime staging

source fingerprint:
  missing source root
  matching hash
  hash mismatch

decoder integration:
  validation report includes field paths from decoder
  size mismatch uses profile metadata
  active-ish diagnostics do not become pass/fail truth unless a validation check owns it

DFU3500 package checks:
  active task count mismatch
  bogus successor
  missing end subtask
  exeBlock task/subtask stamp mismatch
  stage PC outside PE-local instruction rows
```

Use synthetic fixtures first.  Golden payloads are useful regression evidence but
must not be the only correctness source, because serializer and decoder could
otherwise drift together.

## Risks and Mitigations

### Risk: Validation Layer Duplicates Decoder Logic

Mitigation:

```text
validation imports decoder reports/profiles
validation does not reimplement field offset lookup
```

### Risk: Validation Becomes Too Strict Too Early

Mitigation:

Use `diagnostic_only` and `blocked` statuses.  Only make checks blocking when a
payload claims the corresponding readiness level.

### Risk: Mainline Slows Down

Mitigation:

Keep checks local and fast.  Use profile metadata and synthetic fixtures.  Do not
invoke SimICT for local conformance gates.

### Risk: Source Fingerprints Block Work On Different Vendor Snapshots

Mitigation:

Make fingerprint policy configurable:

```text
warn: report mismatch but continue
strict: fail if mismatch
missing-ok: for environments without vendor tree
```

The report must always state which policy was used.

## Expected Effect

After this change, local development should be able to answer:

```text
Can I inspect this byte?                  -> decoder
Did this payload match the profile?       -> validation/dfu_binary_checks
Is this payload runtime-ready locally?     -> validation guard
Does this task graph look runnable?       -> dfu3500_package_checks
Did SimICT actually execute it correctly? -> partner runtime validation
```

This turns the current decoder from a useful standalone tool into the foundation
of a local validation toolchain, while keeping ownership clean.

## Open Questions

1. Should source fingerprint strict mode support explicit signed profile provenance when vendor source is absent?
2. Should `compare_dfu_payloads.py` be kept permanently as a human diff tool, or
   folded behind a new `validate_dfu_payload.py` CLI?
3. Should a future manifest schema add an explicit `readiness_claim`, or is the requested validation gate enough for mainline experiments?
4. How much of DFU3500 package graph legality should be blocking before the first
   first mainline runtime payload?

## Recommended Decision

Accept the split:

```text
decoder remains a generic diagnostic library
validation becomes the home for artifact correctness checks
partner validation consumes validation reports before runtime execution
```

Implement Phase 1 next as `generic checks + payload-local readiness contract`: add
`validation/dfu_binary_checks` with report schema, `ReadinessLevel`, suite
aggregation rules, profile conformance, payload conformance, runtime readiness, and source
fingerprint checks.  Do not move decoder core, and do not make runtime message
decoding part of the critical path.
