# Unimplemented Binary Knowledge Backlog

Date: 2026-06-21

Status: active execution backlog

Purpose:

```text
Track important binary / memory-layout / template knowledge that is documented
or source-backed, but not yet embodied in local decoder or validation tooling.
```

This backlog intentionally excludes knowledge already checked off in:

```text
compiler/notes/decoder/settled_binary_knowledge_checklist.md
```

## Priority Summary

Recommended implementation order:

```text
P2  Operand / route verifier
P2  Memory / template verifier
P2  Tensor immediate decoder
P3  RTL narrow encoding profile, only if RTL artifacts become mainline inputs
```

The current highest-value work is local and does not depend on remote artifact
access.

## Closed: Runtime Memory-Layout Checker

Implemented as:

```text
compiler/gpdpu_compiler/validation/dfu_binary_checks/runtime_memory_layout.py
```

Current coverage:

```text
tensor byte_offset >= 0
tensor byte_size > 0
tensor byte_offset + byte_size <= spm_image_size_bytes
tensor dtype alignment
tensor shape/dtype byte-size consistency
reference file size for output tensors
input_data.bin covers ddr_to_spm DMA ranges
transfer byte_size matches referenced tensor byte_size
transfer spm_offset matches referenced tensor byte_offset
transfer region fits SPM image
input/output tensor regions do not overlap
input/output transfer direction and phase are compatible
```

Boundary:

```text
input_data.bin is treated as a runtime staging image.  It does not need to be
exactly equal to one input tensor size; it must cover declared DMA ranges.
```

### Original knowledge source

`RuntimeControlPlan` describes:

```text
spm_image_size_bytes
tensors[].byte_offset
tensors[].byte_size
tensors[].direction
transfers[].ddr_offset
transfers[].spm_offset
transfers[].byte_size
transfers[].phase
```

### Why it matters

This catches mistakes before remote runtime:

```text
wrong SPM output offset
wrong input image size
wrong reference size
overlapping input/output regions
transfer size smaller than tensor
```

These are exactly the kinds of bugs that remote logs would not explain cleanly.

## Closed: Required Manifest Claim Checker

Implemented in:

```text
compiler/gpdpu_compiler/validation/dfu_binary_checks/payload_conformance.py
```

Current coverage:

```text
PACKAGE_COMPLETE:
  result/cbuf_file.bin and result/micc_file.bin must exist, match profile size,
  and carry manifest size/hash claims.

RUNTIME_READY:
  config copies, simulator_bin component files, runtime assets, and reference
  files present in the payload must also carry manifest size/hash claims.
```

Boundary:

```text
diagnostic sidecars remain optional unless manifest marks them required
```

### Original target

```text
result/cbuf_file.bin
result/micc_file.bin
config/cbuf_file.bin
config/micc_file.bin
runtime/input_data.bin
runtime/riscv_src/riscv_control.json
runtime/riscv_src/riscv/testarm.c
runtime/riscv_src/csv_generate/conf.h
reference files declared by output tensors
simulator_bin component files
```

### Why it matters

This blocks a common stale-artifact shape:

```text
file exists and current check reads it
but manifest does not bind it
later packaging copies a different stale file
```

## Closed: CBUF Stage Instruction Span Checker

Implemented as:

```text
compiler/gpdpu_compiler/validation/dfu3500_package_checks/instruction_span_check.py
```

Current coverage:

```text
for every active exeBlock stage with amount > 0:
  referenced CBUF instruction rows exist inside PE-local inst section
  referenced rows are not all-zero padding
  opCode is known by compiler/gpdpu_compiler/decoder/dfu3500_isa.py
  exeBlock pe_dst maps to valid 4x4 PE index
  stage amount does not point into padded garbage because stage span is already
  guarded by control_graph_check
```

Boundary:

```text
This does not prove operand ownership, unit_inst_type/opCode compatibility, or
pseudo/template legality.  Those belong to opcode conformance and template
verifier work.
```

### Source / docs

```text
docs/compiler/binary_packaging/README.md
docs/runtime/data/cbuf.md
docs/architecture/instruction-set/dfu3500-simd/README.md
compiler/gpdpu_compiler/decoder/dfu3500_isa.py
```

### Why it matters

A-line pain showed that a correct-looking MICC graph can still hang or run
wrong if stage PCs point at padding, stale rows, or badly rebound instruction
blocks.

## Closed: Opcode Conformance Table

Implemented as:

```text
compiler/gpdpu_compiler/decoder/dfu3500_isa.py
compiler/gpdpu_compiler/validation/dfu3500_package_checks/opcode_conformance_check.py
```

Current coverage:

```text
decoder annotates inst_t.opCode with:
  mnemonic/category
  source-backed latency
  source operand count
  need_pe_idx
  unit_inst_type
  pseudo-vs-real opcode status

validation checks active stage CBUF rows:
  assembler-only pseudo opcodes are rejected
  unit_inst_type must match Csv_Operate::registerOp metadata
  latency must match Csv_Operate::registerOp metadata
```

Boundary:

```text
src_count and need_pe_idx are captured as metadata but not yet used as blocking
operand checks.  Operand ownership, routing legality, and template semantics
remain future verifier work.
```

### Source / docs

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/csv_oper.cpp
simict3500final/gpdpu/users/risc_nn_riscv/common/src/inst_def.h
docs/architecture/instruction-set/dfu3500-simd/README.md
docs/architecture/instruction-set/dfu3500-simd/instruction_cards.jsonl
```

### Why it matters

This turns A-line lessons into a local gate:

```text
opCode alone is not enough
SIMD unit type must match opcode family
latency must match vendor registerOp table
pseudo instructions must not leak into final CBUF rows
```

## Deferred: Source Fingerprint Expansion For OCR Vendor Sources

### Decision

Do not prioritize expanding source fingerprints for OCR-derived vendor sources.
The local vendor tree is not guaranteed to be the latest source of truth, and
we currently cannot fetch authoritative updated sources from the partner
machine.  Treating OCR snapshots as strict runtime-ready evidence would create
false confidence and noisy gates.

### Deferred sources

```text
testcase/common_oper/csv_oper.cpp
testcase/common_oper/inst_blk_gen.cpp
testcase/common_oper/inst_blk_map.cpp
testcase/common_oper/task_print.cpp
```

### Re-open trigger

Re-open this only if one of these happens:

```text
partner provides authoritative simulator/compiler sources
local decoder behavior seriously diverges from runtime behavior
binary/control semantics need source-level re-audit for a blocking bug
```

### Boundary

Existing profile/source fingerprints may remain useful as diagnostic provenance,
but expanding OCR `common_oper` fingerprints is not mainline validation work.

## Closed: Operand / Route Field Boundary Checker

Implemented as:

```text
compiler/gpdpu_compiler/validation/dfu3500_package_checks/operand_resource_check.py
```

Current coverage:

```text
for every active CBUF instruction row:
  src_operands_idx[] and dst_operands_idx[] must fit PE operand RAM capacity
  dst_blocks_idx[] must fit PE block capacity
  dst_pes_pos[] must fit DFU3500 4x4x1 PE coordinate space
  forwarding_bits[] and bypass_bits[] must be boolean
  src_operands_fetched[] and dst_operands_fetched[] must be boolean
```

Boundary:

```text
This is a field/resource boundary check, not a semantic route proof.  It does
not yet prove COPY/COPYT endpoint ownership, route path isomorphism, or operand
lifetime.  Those still need typed route/resource plans from B-line executable
binding.
```

### Source / docs

```text
simict3500final/gpdpu/users/risc_nn_riscv/common/src/pe_com_def.h
simict3500final/gpdpu/users/risc_nn_riscv/common/src/inst_def.h
docs/vendor_reference/common_oper/operand-resource-and-route-audit.md
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_inst_blk_map_resource_owner_audit.md
```

## Deferred: Typed Operand / Route Verifier

### Missing knowledge

Docs/source evidence say:

```text
operand tag is build-time name
final value is PE-local operand index
COPY/COPYT destination belongs to receiver owner
route source row and destination receiver binding are different ownership domains
```

Current tools do not prove this.

### Tooling target

Future package/template verifier, not generic decoder.

Suggested checks:

```text
receiver-owned COPY dst PE/block/operand is valid
COPYT expansion rows are structurally complete
local COPY rewrite does not violate endpoint ownership
route producer/consumer binding matches typed route plan
PE-local block id and operand windows are within resource capacity
```

### Source / docs

```text
docs/vendor_reference/common_oper/operand-resource-and-route-audit.md
docs/architecture/instruction-set/dfu3500-simd/MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_inst_blk_map_resource_owner_audit.md
```

### Why it matters

This is where a lot of B-line executable binding risk lives.  Decoder can expose
fields, but only a verifier with route/resource owner plans can judge legality.

## Closed: Memory / Template Base-Slot Checker

Implemented as:

```text
compiler/gpdpu_compiler/validation/dfu3500_package_checks/memory_template_check.py
```

Current coverage:

```text
for every active CBUF instruction row:
  iter_exe_cond must fit base_addr[0..3]
  flow_ack must fit base_addr[0..3]
  LDM/STD-family rows consume base_addr[iter_exe_cond]
  COPY rows consume base_addr[flow_ack]
  consumed active instance base_addr slot must not be disabled sentinel
  active memory rows require active instance rows
```

Boundary:

```text
This catches the A-line base-slot/sentinel class of bugs.  It does not yet
prove operator-specific storage intent, byte-vs-word address units, or full
template family row-count semantics.
```

### Source / docs

```text
docs/architecture/instruction-set/dfu3500-simd/MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_task_print_component_writer_audit.md
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_functional_probe_manual_abi_assumptions.md
```

## Deferred: Typed Memory / Template Verifier

### Missing knowledge

Docs capture rules such as:

```text
pseudo-op expands before row count / PC assignment
iter_exe_cond chooses base_addr[] slot
flow_ack has base-selector implications
COPY uses flow/base semantics differently from compute
byte vs word unit matters for memory addressing
disabled sentinel rows must not become executable work
```

Current validation does not enforce these semantics.

### Tooling target

Future template verifier or executable role binder validation.

Suggested checks:

```text
pseudo-expanded row count matches stage PC/span
stage roles do not reference pre-expansion pseudo row counts
iter_exe_cond field matches expected base_addr slot
flow_ack/base selector fields match operation kind
memory address unit is consistent with operation family
disabled sentinel rows are outside active stage spans
```

### Source / docs

```text
docs/architecture/instruction-set/dfu3500-simd/MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_task_print_component_writer_audit.md
```

## P2: Tensor Immediate Decoder

### Missing knowledge

Tensor/tile instructions such as:

```text
RXINT
TRCTT
HMMA / HMMAL
```

carry immediate bitfields and tmp/group occupancy semantics that are documented
but not decoded structurally.

### Tooling target

Add optional diagnostic decode for tensor immediate fields.

Suggested owner:

```text
compiler/gpdpu_compiler/decoder/dfu3500_tensor_isa.py
```

Boundary:

```text
diagnostic decode first
legality proof later in template verifier
```

### Source / docs

```text
docs/architecture/instruction-set/dfu3500-tensor/README.md
```

## P3: RTL Narrow Encoding Profile

### Missing knowledge

Runtime docs contain RTL narrow instruction structures, but current decoder is
for wide SimICT `inst_t` rows.

### Tooling target

Only implement if RTL outputs become mainline validation artifacts:

```text
separate RTL file/profile kinds
bitfield decode for inst_t_*_for_rtl families
relation report back to wide inst_t row
```

Boundary:

```text
never mix RTL narrow bitfields into SimICT CBUF inst_t profile
```

### Source / docs

```text
docs/runtime/data/rtl.md
```

## Not Current Work

### Remote runtime output closure

Current access constraints mean we cannot assume binary output artifacts can be
downloaded from the customer machine.  Remote output self-check can be revisited
later, but it is not the next local tooling priority.

Tracking RFC:

```text
docs/compiler/binary_packaging/research_notes/enhancements/rfc-runtime-output-closure.md
```

### Runtime in-flight messages

`docs/runtime/data/messages.md` remains background/simulator behavior evidence.
It is not a payload image and should not block local binary validation work.

## Suggested Next Step

Start P1:

```text
1. opcode conformance table
2. expanded source fingerprints
```
