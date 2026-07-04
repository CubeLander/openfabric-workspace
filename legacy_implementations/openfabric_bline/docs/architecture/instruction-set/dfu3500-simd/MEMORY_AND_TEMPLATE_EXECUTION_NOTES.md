# Memory And Template Execution Notes

Date: 2026-06-20

Status: runtime-learned ISA supplement

Related notes:

```text
docs/architecture/instruction-set/dfu3500-simd/OPERAND_LANE_MODEL.md
docs/architecture/instruction-set/dfu3500-simd/docx/instruction_sections/RXOUT.md
docs/compiler/binary_packaging/research_notes/binary/2026-06-20_functional_probe_manual_abi_assumptions.md
docs/compiler/binary_packaging/research_notes/enhancements/2026-06-20_a_line_binary_memory_mud_for_b_line.md
```

## Why This Exists

The instruction-set knowledge base previously focused on lane semantics:

```text
FMAX means lane-wise fp32 max.
HADD means lane-wise fp16 add.
COPYT means cross-PE operand copy.
```

That is necessary, but not enough for compiler/runtime correctness.

The A-line `functional_maximum_single_app` probe exposed a missing class of ISA
knowledge:

```text
instruction execution depends on template expansion, operand allocation,
instance base-address slots, and package control tables.
```

The most expensive example was:

```text
STD used iter_exe_cond = 2
therefore STD consumed instance base_addr2
```

A plain instruction card saying “STD stores operand to memory” would not catch
that.  This document records the execution-context semantics that the compiler
must keep next to the ISA, not buried only in binary notes.

## Evidence Classification

This section answers an important blame question: did we discover these facts,
or did we overlook them in vendor materials?

The answer is mixed.

### Written in original vendor documents

The original Office materials under `tmp/华科算子库编写` already contain several
key facts:

```text
1、DFU3500-架构.docx:
  - PE has no branch/jump style instruction flow; hardware instance tables store
    the memory addresses for loop iterations.
  - One task has up to 8 subtasks.
  - One subtask has at most one instance base-address table.
  - One instance table has up to 2048 entries.
  - Each entry contains base_addr0..base_addr3.

3、DFU3500-SIMD指令集文档.docx:
  - DFU memory address = imm + instance_baseaddr(iteration field).
  - HLDT alignment is 32*4 bytes.
  - ILDMT alignment is 4 bytes.
  - SIMD128 memory instructions are pseudo instructions that lower to multiple
    physical instructions.
```

So the high-level rule was not newly discovered by us.  We had overlooked its
importance when first building the binary path.  The ISA knowledge base also
failed to promote it from extracted doc text into a compiler-facing invariant.

### Explicit in `common_oper` implementation

The vendor compiler implementation makes the document rule concrete:

```text
common_oper/task_print.cpp:
  ldst_inst.base_addr_idx = tmp_inst.iter_exe_cond

common_oper/csv_oper.cpp:
  CSV column 7 is parsed as iter_exe_cond.
  ILDMT expands to LDM.
  HSTT/ISTT expand to STD.
  COPYT expands to COPY.

common_oper/inst_blk_map.cpp:
  Task_Resource maps CSV operand tags to PE-local operand indices.
  COPY/COPYT destination operand is looked up from the child/receiver PE's
  Task_Resource.
```

This means `iteration field -> base_addr slot` is not an inference.  It is the
vendor compiler's own RTL-print behavior.

### Learned by A-line runtime bring-up

A-line did not discover the general rule.  It discovered the consequence that
matters for OpenFabric's generated packages:

```text
Our HSTT-style store template expanded to STD rows with iter_exe_cond = 2.
Therefore the runnable package needed output SRAM in base_addr2.
Putting the output base in base_addr0 was wrong and could prevent completion.
```

This is the part the docs did not hand us directly, because it depends on the
specific generated template and runtime package shape.

### Updated responsibility

The failure was therefore not purely reverse-engineering difficulty.  It was a
knowledge-curation failure:

```text
vendor docs had the formula;
vendor source had the field mapping;
OpenFabric docs did not turn them into compiler guardrails early enough.
```

This file exists to close that gap.

## 1. Lane Semantics Are Not The Full Instruction Contract

For arithmetic ops, the lane view is usually straightforward:

```text
FMAX:
  dst[i] = max(src0[i], src1[i]) over fp32 lanes
```

But a runnable instruction row also needs:

```text
operand indices
unit / stage type
latency or wait field
immediate policy
end/stage flags
producer/consumer block relation
```

For memory ops, the lane view is even less sufficient.  A runnable memory row
needs:

```text
base address slot
immediate offset
address unit
iteration selector
instance row ownership
storage direction
```

Compiler rule:

```text
Do not treat an ISA mnemonic as a complete lowering contract.
A mnemonic must be paired with a TemplateFamily / MemoryAccessPlan before byte
emission.
```

## 2. Memory Address Formula Uses Instance Base Slot

The SIMD docx `RXOUT` section contains the key memory formula:

```text
DFU memory instruction address = imm + instance_baseaddr(iteration field)
```

A-line runtime work confirmed this matters for real SimICT completion.

Observed functional probe case:

```text
store template expands to STD rows
STD row has iter_exe_cond = 2
therefore the row consumes base_addr2 from the active instance row
```

The correct instance row for that store had to bind:

```text
base_addr0 = disabled sentinel
base_addr1 = disabled sentinel
base_addr2 = output SRAM base
base_addr3 = disabled sentinel
```

Using `base_addr0` for the output looked plausible but was wrong for that STD
row.  The symptom was not a friendly compile error; it was remote runtime
non-completion.

Compiler rule:

```text
Every LDM/STD-family physical row must declare which base_addr slot it consumes.
That slot is selected by the row/template iteration field, not by the storage
operand's human-readable role name.
```

## 3. Address Units Must Be Explicit

Current DFU3500 profile knowledge says legacy `base_addr` values are uint32-word
offsets.  Some docx examples describe final byte addresses using formulas such
as:

```text
4 * (regbase + imm)
```

So the compiler must keep these as separate concepts:

```text
base_addr word value
immediate field value
final byte address
alignment requirement
```

Compiler rule:

```text
Do not mix byte offsets and uint32-word offsets in the same field.
Reports should name the unit: bytes, uint32_words, 1024-bit chunks, etc.
```

## 4. Disabled Base Slots Are Semantic Sentinels

A-line used:

```text
0xffffffff
```

as the disabled base-address sentinel for unused `base_addr[4]` slots.

This is not cosmetic padding.  A compiler report should distinguish:

```text
disabled slot = 0xffffffff
valid zero base = 0x00000000
```

Compiler rule:

```text
The disabled base-address sentinel belongs in the DFU3500 profile.
Do not inline it as anonymous filler in serializers.
```

## 5. Pseudo-Ops Expand Before Binary Accounting

The docx/OCR and common-oper evidence both show that some 4096-bit template
mnemonics are pseudo operations over 1024-bit physical chunks.

Stable model:

```text
SIMD128 logical operand = 4096 bits = 4 x 1024-bit chunks
```

Important pseudo families:

```text
ILDMT / ILDT -> LDM-family rows
HSTT / ISTT  -> STD-family rows
COPYT        -> COPY-family rows
```

A-line functional probe used:

```text
local maximum:
  ILDMT input
  IMM scalar
  FMAX

store:
  HSTT-style pseudo template -> STD physical rows
```

Compiler rule:

```text
Pseudo-op expansion must happen before instruction row count, PC layout,
exeBlock stage layout, and memory base-slot validation.
```

Do not count a pseudo-op as one binary instruction row unless the target profile
explicitly says that mnemonic is physically encoded as one row.

## 6. Operand Tags Are Build-Time Names, Not Hardware Operands

CSV examples use human-readable operand tags such as:

```text
Kernel0
input0
output0
```

These are not final hardware operand indices.  Vendor mapping turns them into
PE-local operand RAM indices.

Important consequence:

```text
same tag text on different PEs does not imply same physical operand address
```

Compiler rule:

```text
Final operand indices are scoped by task / soft-processor / physical PE.
Route destination operands belong to the receiver endpoint's operand space, not
merely to the sender instruction row.
```

This rule is especially important for COPY/COPYT lowering.

## 7. Instruction Memory Is Not Data Memory

A-line and B-line both touch fields named like “base” or “PC”.  They must not be
collapsed.

Instruction-memory fields:

```text
candidate_pe_local_pc
stage_start_pc
inst_mem_based_addr
```

Data-memory fields:

```text
instance_conf_info.base_addr[4]
iter_exe_cond / iteration field
LDM/STD immediate offset
```

Compiler rule:

```text
inst_mem_based_addr describes where an exeBlock's instructions begin in PE-local
instruction memory.  It does not select SRAM/SPM data storage.
```

The A-line `STD base_addr2` bug was data-memory binding.  Fixing instruction
PCs would not have fixed it.

## 8. Template Families Need Evidence Status

The instruction table may show that an opcode exists:

```text
FMAX exists.
FLOG2 exists.
FMUL exists.
FADD exists.
```

That does not automatically mean the current compiler has a proven runnable
template for an operator using that opcode.

A-line proved a tiny `FMAX` local template in the context of:

```text
ILDMT input
IMM scalar
FMAX
HSTT/STD store
single task
full 4x4 PE mesh
fixed fp32 shape
```

It did not prove:

```text
FLOG2 template correctness
row-wise SHFL+FMAX reduction
allreduce
multi-app storage handoff
partial mesh runtime packaging
```

Compiler rule:

```text
Instruction availability and template availability are separate facts.
TemplateFamily should carry evidence status:
  documented_opcode
  source_template_seen
  local_generated_rows
  remote_runtime_smoke_passed
  numeric_result_checked
```

## 9. Minimum Compiler Objects Implied By This ISA Supplement

The ISA knowledge now implies these compiler objects before runnable emission:

```text
TemplateFamily:
  owns pseudo expansion, opcode family, operand policy, latency/wait policy,
  stage policy, and evidence status.

MemoryAccessPlan:
  owns storage region, direction, byte/word offset, base slot, iteration selector,
  and instance row ownership.

BaseSlotBinding:
  owns base_addr[0..3] values and disabled-slot sentinel use.

InstructionLayoutPlan:
  owns PE-local PC, stage_start_pc, and instruction-memory base fields.
```

If these facts are instead reconstructed inside a serializer, the ISA knowledge
base has failed to do its job.

## 10. Update To Agent Reading Order

When implementing or debugging a memory/template instruction, read in this order:

```text
1. instruction_cards.md / instruction_cards.jsonl for mnemonic lane semantics
2. OPERAND_LANE_MODEL.md for SIMD128/SIMD32 chunk model
3. this file for memory/template execution context
4. docx/instruction_sections/<MNEMONIC>.md for original extracted text
5. binary/runtime notes for observed package-level evidence
```

This prevents the common mistake:

```text
opcode exists in ISA table
  -> compiler assumes it can emit runnable bytes
```

That jump is not safe.  The missing middle is exactly where A-line hurt.
