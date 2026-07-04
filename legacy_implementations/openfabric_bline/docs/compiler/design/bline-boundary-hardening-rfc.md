# RFC: B-line Boundary Hardening

Status: draft for review, recommended `accept with minor execution-safety amendments`
Date: 2026-06-23
Scope: safe next architecture phase for `compiler/gpdpu_compiler/core`

## Summary

This RFC proposes the next B-line architecture phase: harden authority
boundaries in the current DFU-first compiler spine without disrupting the
working operator delivery path.

The decision under review is:

```text
Accept ProcessorTileProgram as the semantic authority below ChipProgram.
Treat Fiber / TileMicroOp as execution-organization views.
Introduce TemplateExpansion and Dfu3500PhysicalProgramDescriptor before vendor rows.
Keep early phases report-only / byte-equivalent until delivery gates are stable.
```

This RFC should be accepted only as a safe migration plan. It is not approval for
a new architecture relocation or broad lowering rewrite.

Recommended adoption:

```text
Phase 0 / Phase 1: do now.
Phase 2: do as mechanical extraction with byte/hash equivalence.
Phase 3 / Phase 4: report-only and strict-gated; do not take P0 operator
delivery owners.
Phase 6: first phase allowed to intentionally change emitted rows.
```

Required execution-safety amendments before implementation:

```text
Make report-only versus blocking behavior explicit.
Prevent backfilled descriptors from driving vendor projection.
Wrap pipeline artifacts in metadata envelopes.
Define deterministic profile hashing.
Draw migration-order versus target-order causality.
Keep logical resource checks separate from physical placement checks.
Use feature flags/options so delivery-week report-only behavior is enforceable.
```

## Current State

The current production-facing path is:

```text
ChipEnv / ChipProgram
  -> AppPlan / TaskPartitionPlan / runtime package assignment
  -> ProcessorLogicalProgram
  -> ProcessorTileProgram
  -> TileMicroOpProgram
  -> Dfu3500TemplateBoundProgram
  -> ProgramNodeProgram
  -> DFUPackingProgram
  -> ProgramAsm
  -> ProgramVendorABI
  -> ProgramBinRows
  -> ProgramBinComponents
```

The good parts:

- `ChipEnv` records chip-level tensor semantics only.
- SRAM `load` / `store` boundaries are explicit.
- `core/op_specs` is descriptor-only and does not build downstream IR.
- `ProcessorTileProgram` already models route, compute, store, dependencies,
  micro-blocks, loop regions, and visibility refs.
- downstream products are flat, serializable, and carry provenance.
- `runtime_ready` is correctly scoped as local structural/package readiness,
  not SimICT execution or numerical correctness.

The unstable parts:

- `ChipEnv.generate()` owns too much orchestration.
- `stream_compiler` still looks like a parallel architecture even though the
  `program_*` spine is the current trunk.
- template binding exists but is not yet authoritative for binary planning and
  serialization.
- `program_bin.py` owns DFU3500 record sizes, capacities, legacy address
  profiles, and binary policies that should come from DFU3500 profiles.
- local resource / physical checks are not pipeline stages.
- many intermediate products use `Program` in their names, which obscures layer
  category and authority.

## Problem

B-line is at risk of semantic drift:

```text
TemplateBoundProgram chooses template A
  -> ProgramAsm interprets it as A'
  -> ProgramBin interprets it as A''
  -> Serializer / simulator interprets it as A'''
```

This can happen because downstream layers still carry enough legacy template,
instruction, or hardware knowledge to infer decisions that should already be
final.

The failure mode is expensive debugging: byte rows fail in SimICT, but no
single layer is clearly authoritative for why those rows were generated.

The same issue exists for hardware facts. If SRAM/SPM layout, PE count, record
capacity, task/subtask slots, and legacy base-address equations live in multiple
modules, validation and serialization can disagree without an obvious source of
truth.

## Goals

- Preserve the current DFU3500 delivery path while hardening boundaries.
- Make `ProcessorTileProgram` the explicit semantic authority below chip-level
  program IR.
- Make `TemplateExpansion` the authority for template family, segment, local
  template order, and stage attribution.
- Make `Dfu3500PhysicalProgramDescriptor` the authority for PE binding, physical
  PC spans, memory windows, route resources, patch points, dependency ordering,
  and physical provenance.
- Move compile orchestration out of `ChipEnv`.
- Centralize DFU3500 chip, memory, binary, and legacy profile facts.
- Add local resource / physical validation stages before byte serialization.
- Define shared provenance, layer categories, and typed validation reports.
- Freeze `stream_compiler` as lab/evidence/migration source unless pieces
  graduate into the trunk.

## Non-goals

- Do not make TT-Metal a dependency or backend substrate.
- Do not introduce CUDA/CANN/multi-backend abstractions.
- Do not rewrite all existing lowering in one change.
- Do not remove legacy compatibility modes before replacement gates exist.
- Do not make Fiber the semantic center of B-line.
- Do not make the first simulator cycle-accurate.
- Do not change serializer behavior before the current operator delivery gate is
  stable.
- Do not claim local `runtime_ready` proves SimICT execution or numerical
  correctness.

## Proposed Design

### Authority Decision Matrix

Accept this matrix as the B-line ownership contract:

| Decision | Owner | Downstream may infer? |
| --- | --- | --- |
| Tensor-level op semantics | `ChipProgram` | No |
| Processor-local logical actions | `ProcessorLogicalProgram` | No |
| Tile compute / route / store / dependency / visibility semantics | `ProcessorTileProgram` | No |
| Work grouping / executable ordering view | Fiber / `TileMicroOpProgram` | Derived only |
| Template family / segment / local instruction order | `TemplateExpansion` | No |
| PE binding / physical PC span / memory windows / patch points | `Dfu3500PhysicalProgramDescriptor` | No |
| Vendor row fields | `ProgramVendorABI` | Projection only |
| Binary row placement | `ProgramBinRows` | Placement only |
| Bytes | `ProgramBinComponents` | Serialization only |

Important consequence:

```text
ProcessorTileProgram is the semantic source of truth.
Fiber / TileMicroOp is a derived execution view.
TemplateExpansion is the implementation choice.
Dfu3500PhysicalProgramDescriptor is the physical resource contract.
Vendor ABI and binary rows are projections.
```

Downstream projections must not infer K-loop structure, route semantics,
template family, local order, stage attribution, or hardware capacity from
legacy evidence if that information belongs to an upstream authority.

Code review checklist for this matrix:

```text
Does the new field belong to the current layer?
Does this layer infer an upstream decision from legacy rows?
Does this layer bypass source_ir / provenance?
Does this change introduce a new DFU3500 numeric capacity outside profiles?
Does this change treat delivery projection as semantic truth?
```

### ProcessorTileProgram Authority Boundary

`ProcessorTileProgram` owns:

- tile-local compute intent;
- tile-local load/store semantics;
- route intent;
- data visibility requirements;
- dependency semantics;
- loop-region semantic structure;
- logical tile action ownership.

`ProcessorTileProgram` does not own:

- template family selection;
- vendor instruction row shape;
- physical PE binding or physical PC placement;
- SRAM/SPM concrete window allocation;
- runtime patch-point formulas;
- binary row capacity policy;
- component byte layout.

This boundary prevents two failures:

```text
Downstream cannot reinvent semantics from legacy rows.
Upstream cannot push physical/template decisions back into tile semantic IR.
```

### TemplateExpansion Versus Physical Descriptor

Split instruction-span language clearly:

`TemplateExpansion` owns:

- template family;
- template segment;
- template-local instruction ids;
- template-local instruction order;
- logical segment/stage attribution;
- provenance to `TileMicroOp` / tile micro-block.

The first implementation may keep the existing `Dfu3500TemplateBoundProgram`
class name, but it must expose a template-expansion view:

```python
@dataclass(frozen=True)
class TemplateExpansionRecord:
    id: str
    source_tile_micro_op_id: str
    source_tile_micro_block_id: str
    template_family: str
    template_segment: str
    stage: str
    local_instruction_ids: tuple[str, ...]
    local_order_index: int
    implementation_assumptions: tuple[str, ...]
    evidence_refs: tuple[str, ...]
```

Required compatibility hook:

```python
Dfu3500TemplateBoundProgram.to_template_expansion_records()
```

This lets the authority boundary exist before a broad rename.

`Dfu3500PhysicalProgramDescriptor` owns:

- PE binding;
- physical PC start/end;
- physical memory windows;
- route resources;
- runtime patch points;
- physical dependency ordering;
- physical provenance and proof status.

Recommended naming:

```python
DfuPhysicalTemplateExpansion.local_instruction_ids
DfuPhysicalInstructionSpan.physical_start_pc
DfuPhysicalInstructionSpan.physical_end_pc
```

Do not use one generic `instruction_span` concept to mean both local template
order and physical PC placement.

### Existing Artifact Transition Map

The current trunk has intermediate artifacts that cannot disappear immediately.
Give them transition categories:

| Existing artifact | Temporary category | Long-term fate | Sunset trigger |
| --- | --- | --- | --- |
| `ProgramNodeProgram` | implementation compatibility view | migrate fields into `TemplateExpansion` or retire | `TemplateExpansionRecord` covers all delivery ops |
| `DFUPackingProgram` | delivery/placement planning | rename or fold into `ProgramBinRows` / binary layout plan | binary layout plan owns equivalent placement with hash tests |
| `ProgramAsm` | implementation-to-delivery projection | consume physical descriptor or become diagnostic dump | `ProgramVendorABI` consumes authoritative physical descriptor |
| `ProgramVendorABI` | delivery projection | eventually consume physical descriptor directly | stays, but inference logic is deleted |
| `ProgramBinRows` | binary placement | no semantics, no template inference | stays, but remains placement-only |
| `ProgramBinComponents` | byte serialization | no semantics, no placement inference | stays, byte-only |

This map is part of the RFC decision. These artifacts may remain during
migration, but they must not grow new semantic authority.

### Pipeline Orchestration

Add:

```text
compiler/gpdpu_compiler/core/pipeline.py
```

Use typed pipeline stages rather than string stop points:

```python
class PipelineStage(StrEnum):
    CHIP_PROGRAM = "chip_program"
    APP_PLAN = "app_plan"
    PROCESSOR_LOGICAL_PROGRAM = "processor_logical_program"
    PROCESSOR_TILE_PROGRAM = "processor_tile_program"
    TILE_MICRO_OP_PROGRAM = "tile_micro_op_program"
    TEMPLATE_EXPANSION_PROGRAM = "template_expansion_program"
    PHYSICAL_DESCRIPTOR = "physical_descriptor"
    VENDOR_ABI = "vendor_abi"
    BIN_ROWS = "bin_rows"
    BIN_COMPONENTS = "bin_components"
```

Initial API:

```python
class CheckEnforcement(StrEnum):
    DISABLED = "disabled"
    REPORT_ONLY = "report_only"
    STRICT_GATED = "strict_gated"
    RUNTIME_READY_GATED = "runtime_ready_gated"

@dataclass(frozen=True)
class CompileOptions:
    vendor_inst_mode: VendorInstMode = "native_symbolic"
    stop_after: PipelineStage | None = None
    output_dir: Path | None = None
    validation_mode: Literal["dev", "strict", "runtime_ready"] = "dev"
    simulator_mode: Literal["none", "resource", "physical"] = "none"
    emit_physical_descriptor: bool = False
    physical_descriptor_enforcement: CheckEnforcement = CheckEnforcement.REPORT_ONLY
    serializer_consumes_descriptor: bool = False

@dataclass(frozen=True)
class PipelineArtifact:
    stage: PipelineStage
    artifact_kind: str
    artifact_id: str
    schema_version: str
    layer_category: str
    source_artifact_ids: tuple[str, ...]
    authority_policy: str
    payload: object
    payload_sha256: str | None = None

@dataclass(frozen=True)
class CompileResult:
    run_id: str
    options: CompileOptions
    completed_stage: PipelineStage
    artifacts: Mapping[PipelineStage, PipelineArtifact]
    validation_reports: tuple[PipelineValidationReport, ...]

    def get(self, stage: PipelineStage) -> PipelineArtifact | None: ...
    def require(self, stage: PipelineStage) -> PipelineArtifact: ...
    def to_plan(self) -> dict: ...
```

`ChipEnv.generate()` remains, but becomes a wrapper:

```python
def generate(self, output_dir=None, *, vendor_inst_mode="native_symbolic"):
    return compile_chip_program(
        self.program,
        self.chip,
        CompileOptions(output_dir=output_dir, vendor_inst_mode=vendor_inst_mode),
    ).to_plan()
```

This keeps user code stable while removing pass ownership from the frontend.

Phase 1 must support at least:

```text
stop_after = PROCESSOR_TILE_PROGRAM
stop_after = TEMPLATE_EXPANSION_PROGRAM
```

### Typed Validation Reports

Do not use `tuple[dict, ...]` as the validation contract. Add a typed report
shape, aligned with existing validation package status semantics:

```python
ValidationStatus = Literal["pass", "fail", "blocked", "diagnostic_only"]
CoverageStatus = Literal["covered", "partial", "unsupported", "missing_evidence"]
BlockingEffect = Literal["none", "blocks_serialization", "blocks_runtime_ready"]

@dataclass(frozen=True)
class ValidationIssue:
    code: str
    message: str
    severity: Literal["info", "warning", "error", "blocker"]
    source_ref: str | None = None

@dataclass(frozen=True)
class PipelineValidationReport:
    schema_version: str
    check_name: str
    layer_category: str
    source_artifact_id: str | None
    status: ValidationStatus
    authority_policy: str
    requested_gate: str | None
    enforcement: CheckEnforcement
    coverage_status: CoverageStatus
    blocking_effect: BlockingEffect
    issues: tuple[ValidationIssue, ...]
```

Reports must distinguish:

```text
checker found invalid resource use
checker lacks evidence
checker does not cover this op/profile yet
checker passed
```

Enforcement, not status alone, determines whether a report blocks work:

```text
DISABLED:
  check is not run and must not be interpreted as pass.

REPORT_ONLY:
  fail/blocked enters the report but has blocking_effect = none.

STRICT_GATED:
  fail/blocked blocks serialization.

RUNTIME_READY_GATED:
  fail/blocked blocks runtime_ready / partner bundle creation.
```

Example report-only blocked evidence:

```json
{
  "check_name": "physical_descriptor_checker",
  "status": "blocked",
  "enforcement": "report_only",
  "coverage_status": "missing_evidence",
  "blocking_effect": "none"
}
```

### DFU3500 Hardware And Binary Profiles

Add:

```text
compiler/gpdpu_compiler/core/dfu3500/chip_model.py
compiler/gpdpu_compiler/core/dfu3500/binary_profile.py
compiler/gpdpu_compiler/core/dfu3500/memory_model.py
compiler/gpdpu_compiler/core/dfu3500/legacy_profiles.py
```

Profile objects must include identity, not just constants:

```python
@dataclass(frozen=True)
class Dfu3500BinaryProfile:
    schema_version: str
    profile_id: str
    profile_sha256: str
    source_fingerprints: Mapping[str, str]
    chip_model_id: str
    memory_model_id: str
    capacities: Dfu3500Capacities
    record_layouts: Mapping[str, StructLayout]
    component_layouts: Mapping[str, ComponentLayout]
    legacy_profiles: Mapping[str, LegacyAddressProfile]
```

`profile_sha256` must be deterministic. It is computed from canonical JSON:

```text
sorted object keys
UTF-8 bytes
no whitespace significance
exclude the profile_sha256 field itself
include schema_version, capacities, record_layouts, component_layouts,
legacy_profiles, chip_model_id, memory_model_id, and source_fingerprints
```

Move or mirror these facts out of generic binary modules:

- PE count and PE grid facts;
- task/subtask/instance/exeBlock capacities;
- record sizes and component capacities;
- legacy GEMM base-address profiles;
- SRAM/SPM region capacities and alignment;
- legacy sentinel values and slot counts.

`program_bin.py` may import profile values, but it must not define DFU3500
numeric capacities directly.

### Physical Descriptor

Use a target-specific name for the first concrete descriptor:

```text
Dfu3500PhysicalProgramDescriptor
```

A generic base/protocol can come later if another chip exists.

Authority level must be explicit:

```python
PhysicalAuthorityLevel = Literal[
    "backfilled_report_only",
    "validated_report_only",
    "authoritative_for_vendor_projection",
]
```

Phase 3 descriptor output must use:

```text
authority_level = "backfilled_report_only"
```

because it is built from existing downstream rows. It is an observed projection,
not yet the upstream cause of those rows.

After checker coverage improves:

```text
authority_level = "validated_report_only"
```

Only when `ProgramVendorABI` consumes the descriptor directly:

```text
authority_level = "authoritative_for_vendor_projection"
```

Hard invariant:

```text
ProgramVendorABI must not consume a descriptor whose authority_level is
backfilled_report_only or validated_report_only.
```

Recommended guard:

```python
if descriptor.authority_level != "authoritative_for_vendor_projection":
    raise UsageError("physical descriptor cannot drive vendor projection")
```

Initial typed records:

```python
ProofStatus = Literal["proven", "assumed", "unresolved", "legacy_derived"]

@dataclass(frozen=True)
class DfuPhysicalTemplateExpansion:
    id: str
    source_micro_op_id: str
    source_tile_micro_block_id: str
    template_family: str
    stage: str
    local_instruction_ids: tuple[str, ...]
    provenance: dict[str, str]

@dataclass(frozen=True)
class DfuPhysicalInstructionSpan:
    id: str
    template_expansion_id: str
    processor: str
    pe: str
    stage: str
    physical_start_pc: int
    physical_end_pc: int
    source_instruction_ids: tuple[str, ...]

@dataclass(frozen=True)
class DfuPhysicalMemoryWindow:
    id: str
    memory_kind: Literal["SRAM", "SPM", "scratch", "global_scalar"]
    owner_id: str
    base_expr: str
    size_bytes: int
    alignment_bytes: int
    lifetime: tuple[str, str]
    proof_status: ProofStatus

@dataclass(frozen=True)
class DfuPhysicalRouteResource:
    id: str
    source_pe: str
    target_pe: str
    route_kind: str
    visibility_kind: str
    proof_status: ProofStatus

@dataclass(frozen=True)
class DfuPhysicalPatchPoint:
    id: str
    patch_kind: str
    target_id: str
    value_expr: str
    proof_status: ProofStatus

@dataclass(frozen=True)
class DfuPhysicalDependencyEdge:
    id: str
    source_id: str
    target_id: str
    dependency_kind: Literal["data", "control", "memory", "patch", "route"]
    proof_status: ProofStatus

@dataclass
class Dfu3500PhysicalProgramDescriptor:
    schema_version: str
    authority_level: PhysicalAuthorityLevel
    chip: str
    source_program: str
    source_ir: str
    template_expansions: dict[str, DfuPhysicalTemplateExpansion]
    instruction_spans: dict[str, DfuPhysicalInstructionSpan]
    memory_windows: dict[str, DfuPhysicalMemoryWindow]
    route_resources: dict[str, DfuPhysicalRouteResource]
    patch_points: dict[str, DfuPhysicalPatchPoint]
    dependency_edges: dict[str, DfuPhysicalDependencyEdge]
    provenance_map: dict[str, dict]
```

Phase 3 can populate this from existing `Dfu3500TemplateBoundProgram`,
`ProgramAsm`, and `ProgramVendorABI`. It must not alter serialized bytes.

Migration-order causality is different from the final target order.

Phase 3 / Phase 4 migration order:

```text
TemplateExpansion
  -> legacy ProgramNodeProgram / DFUPackingProgram / ProgramAsm / ProgramVendorABI
  -> backfilled physical descriptor
  -> report-only or strict-gated checks
  -> ProgramBinRows / ProgramBinComponents remain byte-equivalent
```

Phase 6 target order:

```text
TemplateExpansion
  -> authoritative physical descriptor
  -> physical checks
  -> ProgramVendorABI
  -> ProgramBinRows
  -> ProgramBinComponents
```

Phase 3 descriptors are mirrors. Phase 6 descriptors are steering inputs.

### Simulator And Local Checks

Add:

```text
compiler/gpdpu_compiler/core/sim/
  README.md
  __init__.py
  target.py
  resource_checker.py
  physical_descriptor_checker.py
  replay_bundle.py
  tile_interpreter.py
```

The README must state:

```text
core/sim initial scope is local structural/resource checking and replay
packaging. It is not a cycle-accurate simulator. It does not own semantic
lowering or byte serialization.
```

Initial scope:

1. `resource_checker.py`
   - consumes `ProcessorTileProgram`;
   - checks logical resource requirements, logical route intent completeness,
     logical visibility requirements, logical dependency closure, tile-local
     load/store intent consistency, and capacity demand summaries;
   - does not check concrete PE assignment, physical SRAM/SPM window overlap,
     physical PC span, or concrete route-resource binding;
   - emits `ResourceCheckReport`.

2. `physical_descriptor_checker.py`
   - consumes `Dfu3500PhysicalProgramDescriptor`;
   - checks concrete DFU3500 placement/resource facts, template expansion
     completeness, instruction span ownership, memory-window legality,
     patch-point proof status, dependency ordering, and provenance continuity;
   - emits `PhysicalCheckReport`.

3. `replay_bundle.py`
   - archives plan dumps, profile id/hash, component hashes, validation reports,
     and partner/SimICT verdict placeholders;
   - emits `ReplayBundleManifest`.

4. `tile_interpreter.py`
   - deferred until resource and physical checks are stable;
   - first supports selected simple op chains only.

Blocking policy:

```text
dev default:
  run checkers with REPORT_ONLY unless requested otherwise;
  fail/blocked reports have blocking_effect = none;
  proven fatal violations may still block.

strict mode:
  run relevant checks with STRICT_GATED;
  fail/blocked reports block serialization.

runtime_ready / partner bundle:
  run relevant checks with RUNTIME_READY_GATED;
  resource_checker fail -> block;
  physical_descriptor_checker fail -> block;
  missing checker evidence -> blocked, not pass.
```

Proof status policy:

```text
unresolved      -> fail in strict/runtime_ready
assumed         -> warning or blocked depending on gate
legacy_derived  -> allowed only with provenance
proven          -> pass
```

`resource_checker` over `ProcessorTileProgram` checks logical resource demand.
Concrete DFU3500 allocation is owned by `physical_descriptor_checker`.

### Replay Bundles And Customer Bundles

Keep replay/debug artifacts distinct from customer delivery artifacts:

```text
ReplayBundle:
  for debugging, reproduction, partner failure analysis.

CustomerDeliveryBundle:
  for handoff, with explicit status labels and known limitations.
```

Minimum replay manifest:

```json
{
  "bundle_kind": "replay_bundle",
  "schema_version": "replay_bundle_v1",
  "run_id": "...",
  "profile_id": "...",
  "profile_sha256": "...",
  "component_hashes": {},
  "local_structural_status": "pass",
  "local_checker_status": "diagnostic_only",
  "simict_status": "not_run",
  "numerical_status": "not_checked"
}
```

### Layer Categories And Naming

Add a layer map to compiler docs:

```text
Semantic layer:
  ChipProgram
  ProcessorLogicalProgram
  ProcessorTileProgram

Execution layer:
  Fiber view
  TileMicroOpProgram

Implementation layer:
  TemplateExpansionProgram

Physical layer:
  Dfu3500PhysicalProgramDescriptor

Delivery layer:
  ProgramVendorABI
  ProgramBinRows
  ProgramBinComponents

Validation layer:
  ResourceCheckReport
  PhysicalCheckReport
  ReplayBundleManifest
```

New artifacts must declare:

```text
schema_version
ir or artifact kind
layer_category
source_ir
authority_policy
validation status
```

This does not require immediate mass renaming. It prevents future `Program*`
suffix sprawl from hiding ownership.

### Stream Compiler Status

Add `core/stream_compiler/README.md` in Phase 0:

```text
stream_compiler is lab/evidence/migration source.
It is not imported by the production `ChipEnv.generate()` B-line trunk.
Mature records or passes must migrate into `program_*`, `dfu3500`, `sim`, or
pipeline modules before becoming trunk authority.
```

Add a minimal import guard in Phase 0 or Phase 1, not Phase 6:

```text
production pipeline and program_* modules must not import core.stream_compiler
```

Start narrow, then expand the check as production modules stabilize.

### Delivery-week Adoption Rule

This RFC must not take resources from the current operator delivery P0 work.

During delivery week:

```text
Phase 0 allowed.
Phase 1 allowed if owned by pipeline/frontend engineer and equivalence tests pass.
Phase 2 allowed only as mechanical extraction with byte/hash equivalence.
Phase 3+ report-only work allowed only if it does not take GEMM / GEMM+ReLU /
log10max delivery owners.
No serializer behavior change until the three-operator delivery gate stabilizes.
```

Delivery-week defaults must be encoded in options or feature flags, not only in
team memory:

```text
BLINE_BOUNDARY_HARDENING_REPORT_ONLY=1
```

Equivalent compile options:

```python
CompileOptions(
    emit_physical_descriptor=False,  # or True only for report-only dumps
    physical_descriptor_enforcement=CheckEnforcement.REPORT_ONLY,
    serializer_consumes_descriptor=False,
)
```

After the delivery gate stabilizes, `serializer_consumes_descriptor=True` may be
enabled only through the Phase 6 acceptance gates.

## Invariants

1. `ChipEnv` and op calls only build chip-level semantics.
2. `ProcessorTileProgram` is the tile semantic source of truth.
3. Fiber / TileMicroOp records are derived execution organization views.
4. TemplateExpansion owns implementation template choice and template-local
   instruction ordering.
5. `Dfu3500PhysicalProgramDescriptor` owns PE binding, physical PC spans,
   memory windows, route resources, patch points, dependency ordering, and
   physical provenance.
6. Vendor ABI and binary rows are delivery projections, not semantic authority.
7. Binary planning must not rediscover K-loop, route, template, or stage
   semantics from legacy CSV evidence.
8. DFU3500 hardware facts are read from `core/dfu3500` profiles, not scattered
   through frontend, op specs, serializers, or validation scripts.
9. Every artifact crossing a layer carries provenance to its source record.
10. Local validation claims distinguish structural readiness, local simulator /
    checker correctness, SimICT execution, and numerical correctness.
11. Backfilled physical descriptors are not upstream authority until a later
    phase makes vendor projection consume them.
12. `ProgramVendorABI` must reject non-authoritative physical descriptors.
13. Report-only checks may report `fail` or `blocked`, but their
    `blocking_effect` must remain `none`.

## Alternatives Considered

### Alternative A: Keep Current Shape And Add Comments

Rejected. Comments help, but they do not stop downstream layers from importing
legacy template helpers or redefining chip facts.

### Alternative B: Rewrite B-line Around A New Fiber Spine

Rejected. Fiber is useful for execution organization, but `ProcessorTileProgram`
is the semantic center.

### Alternative C: Jump Directly To A Full Simulator

Deferred. A full functional simulator is valuable, but resource and physical
descriptor checks are cheaper and unblock earlier debugging.

### Alternative D: Rename Every Program Class Immediately

Rejected for this phase. It would create churn without first establishing the
layer-category contract. Add the naming map first, then rename selectively.

### Alternative E: Keep `stream_compiler` As A Parallel Production Line

Rejected. Parallel trunks will create duplicate concepts and unclear authority.
`stream_compiler` can remain as evidence/lab code until pieces migrate.

## Migration / Implementation Plan

### Phase 0: Boundary Map And Import Guard

Deliverables:

- Accept this RFC.
- Add layer-category map to compiler docs.
- Add authority decision matrix to docs.
- Add `core/stream_compiler/README.md` with lab/evidence status.
- Add minimal production import guard against `core.stream_compiler`.
- No behavior change.

Acceptance criteria:

- reviewers agree `ProcessorTileProgram` is semantic authority;
- reviewers agree Fiber / TileMicroOp is a derived execution view;
- reviewers agree physical descriptor is the next authority boundary;
- production pipeline path does not import `core.stream_compiler`.

### Phase 1: Pipeline Wrapper

Deliverables:

- Add `core/pipeline.py`.
- Add `PipelineStage`.
- Add `CompileOptions.stop_after: PipelineStage | None`.
- Add `PipelineArtifact` envelope.
- Add `CompileResult` artifact map with `get()` / `require()`.
- Move orchestration body out of `ChipEnv.generate()`.
- Preserve `ChipEnv.generate()` public behavior.

Acceptance criteria:

- existing `env.generate()` tests pass unchanged;
- direct `compile_chip_program(...)` emits the same plan schema keys as
  `ChipEnv.generate()`;
- stable IDs remain stable where expected;
- output filenames remain unchanged when `output_dir` is used;
- full-pipeline component hashes are unchanged for GEMM no-ReLU if bytes are
  emitted;
- if bytes are not emitted in the test, normalized `to_plan()` canonical JSON
  hash is unchanged;
- validation report count/status is unchanged for existing tests;
- `stop_after=PROCESSOR_TILE_PROGRAM` works;
- `stop_after=TEMPLATE_EXPANSION_PROGRAM` works.

### Phase 2: DFU3500 Profile Extraction

Deliverables:

- Add `chip_model.py`, `memory_model.py`, `binary_profile.py`,
  `legacy_profiles.py`.
- Add `profile_id`, `profile_sha256`, and `source_fingerprints`.
- Move record sizes, capacities, PE count, slot counts, sentinels, and legacy
  GEMM base-address profile into profile records.
- Make `program_bin.py` import profile values.

Acceptance criteria:

- representative payload component hashes unchanged;
- `profile_sha256` is deterministic;
- profile hash excludes the `profile_sha256` field itself;
- profile hash is stable under dictionary insertion order;
- profile hash changes when a capacity changes;
- profile hash changes when a struct field offset changes;
- `program_bin.py` contains no DFU3500 numeric capacities except through
  profile import;
- validation reports continue to expose the same capacities;
- decoder profile and serializer guard profile share the same source object
  when applicable.

### Phase 3: Backfilled Physical Descriptor

Deliverables:

- Add `core/program_physical.py`.
- Add typed physical records listed in this RFC.
- Build `Dfu3500PhysicalProgramDescriptor` from existing
  `Dfu3500TemplateBoundProgram`, `ProgramAsm`, and `ProgramVendorABI`.
- Set `authority_level = "backfilled_report_only"`.
- Include descriptor in `CompileResult.to_plan()`.
- Keep `serializer_consumes_descriptor=False`.
- No serialized byte change.

Acceptance criteria:

- every physical instruction span points back to a template expansion;
- every template expansion points back to TileMicroOp / tile micro-block;
- descriptor authority level is `backfilled_report_only`;
- `ProgramVendorABI` does not consume the descriptor;
- provenance coverage report is included;
- component hashes are unchanged for representative payloads.

### Phase 4: Resource And Physical Checks

Deliverables:

- Add `core/sim/README.md`.
- Add `core/sim/resource_checker.py`.
- Add `core/sim/physical_descriptor_checker.py`.
- Wire typed reports into `CompileResult.validation_reports`.
- Implement `CheckEnforcement`, `coverage_status`, and `blocking_effect`.
- Implement dev / strict / runtime_ready blocking policy through enforcement.

Acceptance criteria:

- resource checker runs on existing GEMM / GEMM+ReLU / log10max examples;
- physical checker reports missing provenance or unsupported patch points
  fail-closed in strict/runtime_ready mode;
- dev mode can report immature coverage without blocking ordinary compile;
- report-only mode records fail/blocked reports with `blocking_effect = none`;
- serializers do not run in strict mode if physical descriptor check fails.

### Phase 5: Replay Bundle Skeleton

Deliverables:

- Add `core/sim/replay_bundle.py`.
- Bundle selected plan dumps, profile id/hash, component hashes, validation
  reports, and runtime mode metadata.
- Leave memory snapshots and SimICT verdicts optional placeholders.

Acceptance criteria:

- one command can create a deterministic bundle directory;
- replay manifest uses `bundle_kind = "replay_bundle"`;
- customer delivery bundle is a separate artifact with explicit known
  limitations;
- bundle manifest differentiates local structural pass, local checker/simulator
  pass, external SimICT pass, and numerical pass;
- first golden bundle is GEMM no-ReLU.

### Phase 6: Consume Physical Descriptor

Deliverables:

- Make `ProgramVendorABI` consume `Dfu3500PhysicalProgramDescriptor`.
- Promote descriptor authority to `authoritative_for_vendor_projection` only
  when this consumption path is active.
- Allow intentional row changes only behind validation gates.

Acceptance criteria:

- `ProgramVendorABI` rejects `backfilled_report_only` and
  `validated_report_only` descriptors;
- ProgramVendorABI no longer infers template-local or physical facts that are
  present in descriptor;
- row changes are intentional and reviewed;
- strict physical checks pass before serialization.

## Validation Plan

Run existing tests after each behavior-preserving phase:

```text
pytest tests/test_chip_program_frontend.py
```

Run targeted validation after serialization-adjacent phases:

```text
python -m gpdpu_compiler.validation.dfu_binary_checks.runner ...
```

Add new focused tests:

- `test_pipeline_generate_full_equivalence_for_gemm_no_relu`
- `test_pipeline_generate_plan_hash_equivalence`
- `test_pipeline_stop_after_processor_tile_program`
- `test_pipeline_stop_after_template_expansion_program`
- `test_pipeline_artifacts_use_envelope`
- `test_binary_profile_is_source_of_capacity_facts`
- `test_binary_profile_hash_is_deterministic`
- `test_profile_hash_excludes_itself`
- `test_profile_hash_stable_under_dict_order`
- `test_profile_hash_changes_when_capacity_changes`
- `test_profile_hash_changes_when_struct_field_offset_changes`
- `test_component_hashes_unchanged_after_profile_extraction`
- `test_physical_descriptor_has_template_and_tile_provenance`
- `test_physical_descriptor_authority_level_backfilled`
- `test_vendor_abi_rejects_non_authoritative_descriptor`
- `test_resource_checker_reports_logical_demand_only`
- `test_physical_checker_rejects_overlapping_sram_region`
- `test_physical_checker_rejects_missing_patch_proof`
- `test_report_only_checker_has_no_blocking_effect`
- `test_validation_reports_are_typed`
- `test_replay_bundle_is_not_customer_delivery_bundle`
- `test_stream_compiler_not_imported_by_production_pipeline`

For partner-facing payloads, continue using:

```text
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/build_payloads.py
```

The RFC does not redefine partner validation. It adds local checks before the
partner path.

## Risks And Mitigations

### Risk: More IR Objects Increase Cognitive Load

Mitigation: introduce layer categories and authority policies. Do not add a new
artifact unless it owns a decision or validation result that currently floats
between layers.

### Risk: Physical Descriptor Becomes A Passive Dump

Mitigation: Phase 3 explicitly sets `authority_level = backfilled_report_only`.
Phase 4 validates completeness. Phase 6 is the first phase where vendor
projection consumes the descriptor as authority.

### Risk: Backfilled Descriptor Reverses Causality

Mitigation: distinguish `backfilled_report_only`, `validated_report_only`, and
`authoritative_for_vendor_projection`. Do not let a backfilled descriptor block
or rewrite delivery rows except through explicit checker policy.

### Risk: Report-only Checks Accidentally Block Delivery

Mitigation: reports carry `enforcement` and `blocking_effect`. Report-only
failures may be visible and archived, but they must not block serialization,
`runtime_ready`, or customer bundle creation.

### Risk: Logical Resource Checks Become Physical Allocation Checks

Mitigation: `resource_checker` over `ProcessorTileProgram` checks only logical
resource demand. Concrete PE binding, PC span, and SRAM/SPM window legality are
owned by `physical_descriptor_checker`.

### Risk: Pipeline Refactor Breaks Existing User API

Mitigation: keep `ChipEnv.generate()` as wrapper and require equivalence tests.

### Risk: Binary Profile Extraction Changes Bytes

Mitigation: move constants mechanically first, then compare generated component
hashes for representative payloads.

### Risk: Profile Hash Is Not Stable Across Machines

Mitigation: define canonical JSON hashing, exclude `profile_sha256` itself, and
test dictionary-order stability plus sensitivity to capacity/layout changes.

### Risk: `stream_compiler` Freezing Blocks Useful Work

Mitigation: freezing does not delete it. It defines migration criteria: code can
graduate into trunk only as a layer-owned artifact/pass with clear authority.

### Risk: Simulator Scope Expands Too Fast

Mitigation: start with resource and physical descriptor checks. Defer numerical
tile interpreter until basic resource legality is stable.

### Risk: Boundary Hardening Steals Delivery-week Ownership

Mitigation: Phase 0/1 are allowed only if they do not take P0 delivery owners.
Phase 2 must be mechanical and byte/hash equivalent. Phase 3/4 stay report-only
until delivery gates stabilize.

## Expected Effect

After this RFC is implemented:

- reviewers can identify exactly which layer owns a compile decision;
- binary rows become delivery projections, not hidden knowledge carriers;
- template choice and physical resources become inspectable before vendor ABI;
- local checks catch structural/resource errors before SimICT;
- generated bundles become easier to reproduce and discuss with partners;
- future contributors have a naming map rather than a pile of `Program*`
  classes.

## Open Questions And Recommended Answers

| Question | Recommendation |
| --- | --- |
| `DfuPhysicalProgramDescriptor` or `Dfu3500PhysicalProgramDescriptor`? | Use `Dfu3500PhysicalProgramDescriptor` now. Add a generic protocol only when a second chip exists. |
| Rename `Dfu3500TemplateBoundProgram` now? | No broad rename now. Add conceptual alias / layer category. Use `TemplateExpansion` for new APIs and reports. |
| Which Phase 1 stop points? | Support `PROCESSOR_TILE_PROGRAM` and `TEMPLATE_EXPANSION_PROGRAM`. Use enum, not string. |
| Should checker failures block serialization? | Only according to `CheckEnforcement` and `blocking_effect`. Dev/report-only reports. Strict blocks serialization. Runtime-ready gated blocks runtime_ready / partner bundle. Proven fatal violations may block in any mode. |
| First replay-bundle golden? | GEMM no-ReLU first. GEMM+ReLU second. log10max after collective strategy stabilizes. |
| Can Phase 3 descriptors be consumed by vendor projection? | No. `ProgramVendorABI` may consume only `authoritative_for_vendor_projection` descriptors in Phase 6. |
| Are replay bundles customer delivery bundles? | No. Replay bundles are debug/reproduction artifacts. Customer delivery bundles remain separate handoff artifacts with explicit limitations. |

## Review Checklist

Before acceptance, reviewers should confirm:

- authority decision matrix is accepted;
- `ProcessorTileProgram` owns / does-not-own boundary is accepted;
- transition categories for `ProgramNodeProgram`, `DFUPackingProgram`, and
  `ProgramAsm` are accepted;
- `CompileOptions.stop_after` uses `PipelineStage`;
- `CompileOptions` carries report-only / descriptor-consumption switches;
- `CompileResult` uses a stage artifact map with `PipelineArtifact` envelopes;
- validation reports are typed and include requested gate, enforcement,
  coverage status, and blocking effect;
- DFU3500 profiles include `profile_id`, `profile_sha256`, and
  `source_fingerprints`;
- `profile_sha256` canonicalization is defined;
- Phase 2 requires component hash equivalence;
- physical descriptor includes `authority_level`;
- Phase 3 descriptor is `backfilled_report_only`;
- `ProgramVendorABI` cannot consume backfilled or validated-report-only
  descriptors;
- physical descriptor uses typed memory / route / patch / dependency records;
- `proof_status` is enum-based;
- checker blocking policy is explicit;
- `resource_checker` checks logical demand only; concrete allocation belongs to
  `physical_descriptor_checker`;
- Phase 3/4 migration order and Phase 6 target order are both documented;
- `TemplateExpansionRecord` export view is defined;
- replay bundle and customer delivery bundle are distinct artifacts;
- `stream_compiler` import guard is Phase 0/1;
- delivery-week adoption rule is accepted.

## Recommended Decision

Accept the RFC with the small required execution-safety amendments in this
version.

Immediate work:

```text
Phase 0:
  layer-category map
  authority decision matrix
  stream_compiler lab/evidence README
  minimal import guard

Phase 1:
  core/pipeline.py
  PipelineStage enum
  PipelineArtifact envelope
  CompileResult artifact map
  ChipEnv.generate wrapper
  deterministic equivalence tests
```

Allowed parallel work:

```text
Phase 2:
  DFU3500 profile extraction
  byte/hash equivalence required
```

Careful report-only work:

```text
Phase 3 / Phase 4:
  backfilled physical descriptor
  resource / physical checks
  report-only behind explicit enforcement
  strict-gated only where requested
  no delivery-owner starvation
```

Deferred until gates stabilize:

```text
ProgramVendorABI consumes physical descriptor
large-scale renames
serializer behavior changes
```

The intended outcome is a compiler where each layer has a visible owner:
semantics, execution organization, template choice, physical binding, delivery
projection, and byte serialization are no longer allowed to blur together.
