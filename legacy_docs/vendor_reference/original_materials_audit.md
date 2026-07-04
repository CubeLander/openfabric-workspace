# Vendor Original Materials Audit

Date: 2026-06-20

Status: living audit index / must-read map

Original material root:

```text
tmp/华科算子库编写
```

Source implementation root:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper
```

## Why This Audit Exists

We lost time because important binary-interface facts were present in vendor
materials but were not promoted into OpenFabric compiler invariants early enough.
The clearest example:

```text
Original SIMD doc:
  DFU memory address = imm + instance_baseaddr(iteration field)

common_oper/task_print.cpp:
  ldst_inst.base_addr_idx = tmp_inst.iter_exe_cond

A-line runtime consequence:
  HSTT/STD with iter_exe_cond=2 needs output base in base_addr2
```

This was not a case where the materials had no clue.  The materials had the
rule; we failed to make the rule operational in the compiler knowledge base.

The new discipline is:

```text
For every binary/runtime-critical vendor fact, keep:
  1. original material reference,
  2. common_oper/source reference if available,
  3. OpenFabric documentation reference,
  4. compiler owner / future owner,
  5. status.
```

No more half-reading and guessing for binary interfaces.  Guessing at this layer
turns into remote hangs.

## Reading Discipline For Future Agents

When touching CBUF/MICC, instruction rows, memory layout, task/subtask rows,
RISC-V runtime control, or template binding:

```text
1. Read the relevant original material section.
2. Read the corresponding common_oper implementation if it exists.
3. Check whether docs/vendor_reference or docs/architecture already distilled it.
4. If not, update docs before or with code.
5. Add a local guard/check for every fact that can cause runtime hang.
```

A runnable binary patch without a documented source/evidence path is not
acceptable unless it is explicitly marked as a temporary probe.

## No-reference, No-change Gate

Binary/runtime-critical changes must not rely on “looks similar to vendor” as
the only justification.  Before code is promoted beyond a probe, it needs a
reference slot in this tree or in `docs/architecture`:

```text
source document:
  original Office / spreadsheet material, if vendor documented it

source implementation:
  `common_oper` / runtime / case source, if vendor implemented it

OpenFabric reference:
  distilled note that future agents can read before coding

compiler owner:
  typed plan, verifier, serializer, or explicit TODO owner
```

If any slot is missing, the change can still exist as an experiment, but its
manifest / note must say which slot is missing.  This makes uncertainty visible
instead of letting it leak into CBUF/MICC bytes as folklore.

## Original Materials Matrix

| Material | Critical facts | Current OpenFabric reference | Status |
| --- | --- | --- | --- |
| `1、DFU3500-架构.docx` | PE/SPM/DRAM overview; no branch/jump PE model; hardware instance table; max 4 tasks, 8 subtasks/task, 2048 instance entries/subtask, base_addr0..3 | `docs/architecture/instruction-set/dfu3500-simd/MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md`; `compiler/notes/refactor/rfc-soft-device-mesh-task-axis.md`; `docs/vendor_reference/common_oper/dfu3500-hardware-constraints-from-vendor-algorithms.md` | Partially absorbed; task/instance facts now known, but should be tied to typed B-line task/subtask/memory plans |
| `2、DFU3500-SIMD指令集.xlsx` | mnemonic list, pipeline, latency, opcode families, memory op families, FMAX/FLOG2 presence | `docs/architecture/instruction-set/dfu3500-simd/instruction_cards.md`; `instruction_cards.jsonl`; `xlsx/Sheet*.csv` | Extracted; must not be confused with proven runnable template support |
| `3、DFU3500-SIMD指令集文档.docx` | lane semantics; COPYT; memory address formula; memory alignment; ILDMT/HSTT sections; OCR image evidence | `docs/architecture/instruction-set/dfu3500-simd/docx/instruction_sections/*`; `MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md`; `OPERAND_LANE_MODEL.md` | Extracted; memory/template execution now promoted after A-line pain |
| `4、DFU3500-汇编编程介绍.docx` | simulator API/control overview; app/csv_generate flow; `instance_base_noneed`; `conf.h` fields; APP/TASK/PE/INSTANCE concepts | `docs/vendor_reference/runtime_evidence/runtime-control-source-audit.md`; `docs/vendor_reference/runtime_evidence/riscv-control-and-dpuapi.md`; `docs/vendor_reference/case_authoring/*`; `docs/vendor_reference/runtime_evidence/simict-runtime.md` | Absorbed for launch/control basics; `instance_base_noneed` still needs typed `RuntimeControlPlan` / `MemoryAccessPlan` owner |
| `5、DFU3500-模拟器使用方法.docx` | simulator invocation, runtime directory expectations, package flow | `docs/vendor_reference/runtime_evidence/simict-runtime.md`; `docs/vendor_reference/remote_ops/arch13-server-environment.md` | Partially absorbed; should be re-audited before B-line runtime packaging |
| `6、DFU3500-DMA数据传输介绍.docx` | DMA transfers, DDR/SPM movement, host/RISC-V control responsibilities | `docs/vendor_reference/runtime_evidence/runtime-control-source-audit.md`; `docs/vendor_reference/runtime_evidence/dpu-dma-instruction-load-share.md`; `docs/vendor_reference/runtime_evidence/riscv-control-and-dpuapi.md`; `docs/compiler/binary_packaging/research_notes/enhancements/rfc-riscv-control-program-generation.md` | Absorbed for validation bundle needs; needs RuntimeControlPlan implementation |
| `7、softmax详解.pptx` | softmax task/subtask shape, row-wise work split, SHFL/FADD reduction skeleton, instance usage | `docs/vendor_reference/cases/softmax/softmax-original-materials-audit.md`; `docs/vendor_reference/cases/softmax/*`; `compiler/notes/log10max/README.md` | Absorbed as staged-op evidence; should not be copied as generic probe template |
| `8、类型转换指令.docx` | RXINT/TRCTT/type conversion temp mapping, conversion modes | `docs/architecture/instruction-set/dfu3500-tensor/TYPE_CONVERSION_SOURCE_AUDIT.md`; `docs/architecture/instruction-set/dfu3500-tensor/README.md`; `docs/architecture/instruction-set/dfu3500-tensor/docx/*`; `UNCLEAR_SEMANTICS_BACKLOG.md` | Absorbed for RXINT/TRCTT fields; B-line still needs `TensorTmpResourcePlan` before runnable conversion probes |
| `（这个文档先不看）DFU3500-tensor指令集.*` | RXINT/HMMAL/TRCTT tensor tmp semantics, HMMAL imm fields | `docs/architecture/instruction-set/dfu3500-tensor/*`; `docs/architecture/instruction-set/dfu3500-tensor/TYPE_CONVERSION_SOURCE_AUDIT.md`; `docs/vendor_reference/cases/gemm/gemm-original-materials-audit.md`; `docs/vendor_reference/common_oper/dfu3500-hardware-constraints-from-vendor-algorithms.md` | Absorbed for tensor tmp / HMMAL immediate facts; final B-line tensor tmp resource plan still needed |
| `HMMAL详解.pptx` | HMMAL examples/visual semantics | `docs/vendor_reference/cases/gemm/gemm-original-materials-audit.md`; tensor docs and GEMM notes | Absorbed at case-audit level; needs byte-emitter verifier before B-line HMMAL path |
| `gemm手写代码详解.pptx` | GEMM task/subtask/instance/base table shape; 4-task mapping; hardware loop explanation | `docs/vendor_reference/cases/gemm/gemm-original-materials-audit.md`; `docs/vendor_reference/cases/gemm/*`; `docs/compiler/binary_packaging/research_notes/binary/*`; `compiler/notes/refactor/rfc-soft-device-mesh-task-axis.md` | Absorbed for GEMM evidence; should be cross-checked against B-line GEMM no-ReLU counts |

## `common_oper` Source Matrix

| Source file | Critical behavior | Current OpenFabric reference | Status |
| --- | --- | --- | --- |
| `csv_oper.cpp/.h` | CSV parser; column 7 -> `iter_exe_cond`; opcode registry; pseudo expansion `ILDMT->LDM`, `HSTT->STD`, `COPYT->COPY`; extra fields | `MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md`; `OPERAND_LANE_MODEL.md`; `docs/compiler/binary_packaging/research_notes/enhancements/2026-06-20_a_line_binary_memory_mud_for_b_line.md` | Now explicitly referenced; B-line needs `TemplateFamily` owner |
| `task_print.cpp/.h` | Converts `inst_t` to RTL/simulator structs; `ldst_inst.base_addr_idx = tmp_inst.iter_exe_cond`; component file writing/padding; task/subtask printing | `MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md`; `binary-artifact-generation-pipeline.md`; A-line mud map | Critical; B-line needs typed `MemoryAccessPlan`, `InstructionLayoutPlan`, `TaskControlPlan` |
| `inst_blk_map.cpp/.h` | `Task_Resource`; PE-local operand allocation; bank layout; LD/CAL/FLOW/ST operand fill order; COPYT destination operand from child PE resource | `dfu3500-hardware-constraints-from-vendor-algorithms.md`; `dfu3500_gemm_diff3_notes.md`; A-line mud map | Important; B-line route/template operand ownership must cite it |
| `inst_blk_gen.cpp/.h` | Splits processed instructions into LD/CAL/FLOW/ST stages | `binary-artifact-generation-pipeline.md`; B-line `TemplateOpPlan`/`BinaryLayoutPlan` notes | Partially absorbed; should inform B-line stage layout verifier |
| `exe_block_gen.cpp/.h` | ExeBlock generation, PE-local block indices | `binary-artifact-generation-pipeline.md`; B-line `VendorComponentPlan` | Partially absorbed; B-line candidate exeblocks need final ABI verification |
| `task_create.cpp/.h` | Reads app/task/subtask conf and builds Task_Group | `subtask-graph-compile-chain.md`; `task-creation-generategraph-chain.md` | Partially absorbed; more evidence needed for multi-app/multi-task packaging |
| `graph_extend.cpp/.h` | Graph node relationships and COPY instruction attachment | `subtask-graph-compile-chain.md`; B-line StreamPlan/Fiber route notes | Partially absorbed; route path lowering should cite this |
| `graph_gen.cpp/.h` | Case graph generation base classes | case docs | Mostly background; read when adding new vendor-like reference case |
| `common_app_build.cpp/.h` | build_app shared setup | `binary-artifact-generation-pipeline.md` | Background; read before changing package generation assumptions |
| `csv2bin.cpp/.h` | CSV to binary conversion helpers | ISA/template notes | Needs targeted audit if B-line writes direct CSV-compatible templates |
| `inst_map_common.cpp/.h` | Shared PE coordinate mapping; register offset pass; COPY/LCOPY endpoint patching; Manhattan route distance | `docs/vendor_reference/common_oper/operand-resource-and-route-audit.md`; hardware constraints notes | Absorbed; B-line still needs typed `OperandResourcePlan` / `RouteEndpointPlan` |
| `checkpoint_print/inst_print.cpp` | Debug print of instruction structures | binary diff/debug tooling | Useful for diagnostics, not source of semantic truth |

## Critical Facts Promoted After A-line Pain

### Memory formula is documented

```text
DFU memory instruction address = imm + instance_baseaddr(iteration field)
```

This appears in the original SIMD doc.  We should have promoted it earlier.

OpenFabric owner now:

```text
docs/architecture/instruction-set/dfu3500-simd/MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md
```

Future compiler owner:

```text
MemoryAccessPlan / BaseSlotBinding / InstanceBaseRowPlan
```

### `iter_exe_cond` concretely chooses `base_addr_idx`

`common_oper/task_print.cpp` makes it operational:

```text
ldst_inst.base_addr_idx = tmp_inst.iter_exe_cond
```

A-line consequence:

```text
STD iter_exe_cond=2 -> output base must live in base_addr2
```

Future compiler owner:

```text
TemplateFamily exports base-slot requirement to MemoryAccessPlan.
```

### Pseudo-op expansion is source-backed

`common_oper/csv_oper.cpp` maps:

```text
ILDMT -> LDM
HSTT  -> STD
COPYT -> COPY
```

Future compiler owner:

```text
TemplateFamily pseudo expansion contract.
```

### Operand tags are not hardware operands

`common_oper/inst_blk_map.cpp` maps tags to PE-local operand RAM and uses child
PE resources for COPY/COPYT destination operands.

Future compiler owner:

```text
TemplateOperandPolicy / route endpoint ownership plan.
```

## Audit Status Legend

```text
Extracted:
  raw text/table has been converted into Markdown/CSV/JSONL.

Absorbed:
  extracted fact has a human-readable OpenFabric reference note.

Operationalized:
  compiler has a typed plan/check that enforces the fact.

Runtime-proven:
  generated package has passed SimICT/runtime or numeric validation.
```

Many facts are now extracted and absorbed.  Far fewer are operationalized.
B-line should focus on operationalizing the binary-critical ones.

## Open Audit Debts

These need explicit follow-up before their corresponding compiler feature:

```text
1. `instance_base_noneed` from 汇编编程介绍:
   Source-audited in `runtime_evidence/runtime-control-source-audit.md`;
   still needs typed RuntimeControlPlan/MemoryAccessPlan support before use.

2. DMA transfer document:
   Source-audited for launch/control shape; still needs generated
   RuntimeControlPlan implementation and validation.

3. softmax PPT:
   Source-audited in `cases/softmax/softmax-original-materials-audit.md`;
   still needed before staged non-GEMM/reduce/log10max byte path.

4. type conversion document:
   Source-audited in
   `docs/architecture/instruction-set/dfu3500-tensor/TYPE_CONVERSION_SOURCE_AUDIT.md`;
   still needs TensorTmpResourcePlan before FLOG2/log10/type conversion payloads.

5. tensor/HMMAL PPT:
   Source-audited in `cases/gemm/gemm-original-materials-audit.md`;
   still needs TensorTmpResourcePlan/HMMAL byte-emitter verifier.

6. common_oper/inst_map_common.cpp:
   Source-audited in `common_oper/operand-resource-and-route-audit.md`;
   still needed when final route/tensor operand allocator is implemented.
```

## Required Reference Policy

For any future change touching binary/runtime-critical code, the PR or note must
answer:

```text
What original material says this?
What common_oper source implements this?
Where is the OpenFabric reference note?
Which compiler plan/check owns it?
```

If the answer is “we only observed it in a remote run,” then the field must be
marked as a probe assumption until source/doc evidence is found or the runtime
probe is intentionally accepted as the evidence.
