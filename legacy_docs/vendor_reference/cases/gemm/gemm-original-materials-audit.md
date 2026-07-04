# GEMM Original Materials Audit

Date: 2026-06-20

Status: case-specific original-materials audit card

This note connects the original GEMM/HMMAL materials to the compiler facts that
B-line must eventually operationalize.  It is not a new design; it is an evidence
map so future GEMM byte emitters do not rediscover vendor rules by remote hangs.

## Source Materials

Original materials:

```text
tmp/华科算子库编写/（这个文档先不看）gemm手写代码详解.pptx
tmp/华科算子库编写/（这个文档先不看）HMMAL详解.pptx
tmp/华科算子库编写/（这个文档先不看）DFU3500-tensor指令集.xlsx
tmp/华科算子库编写/（这个文档先不看）DFU3500-tensor指令集.docx
```

Vendor implementation and workflow:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper
```

Existing OpenFabric references:

```text
docs/vendor_reference/common_oper/dfu3500-gemm-binary-replay.md
docs/vendor_reference/common_oper/dfu3500-hardware-constraints-from-vendor-algorithms.md
docs/architecture/instruction-set/dfu3500-tensor/README.md
docs/compiler/binary_packaging/research_notes/enhancements/2026-06-20_a_line_binary_memory_mud_for_b_line.md
```

## Original GEMM Shape Evidence

The GEMM hand-written-code PPT describes a representative case:

```text
dtype: fp16
A: 512 x 256
B: 256 x 1024
app_M = 1
app_K = 1
app_N = 2
TASK_NUM = 4
SUBTASK_NUM = 3
PE_NUM = 16
```

It also describes the app-level data movement as DDR -> SPM and then mapping one
app's data to the PE array.

## Subtask / Hardware Loop Evidence

The GEMM PPT describes three subtasks:

```text
subtask1: load C
  base0: C
  loop count: 1

subtask2: load A, load B, compute
  base0: A
  base1: B
  loop count: 4

subtask3: store C
  base0: C
  loop count: 1
```

It explicitly says the repeated `subtask2` hardware-loop instances are not
expanded in CSV; CSV shows the instance-0 instruction shape, while instance
base rows provide the changing A/B regions.

### Compiler implication

B-line should model GEMM K-loop folding as:

```text
one loop-body template
  + K instance/base rows
  + loop-carried accumulator state
```

not as four separately emitted instruction bodies unless an experiment is
explicitly unfurled.

## Tensor Instruction Envelope

The tensor docs say the GEMM instruction family uses tensor tmp state:

```text
RXINT: operand -> tensor tmp, optional conversion
HMMAL: fp16 64x64 matrix multiply, dst tmp selected by imm[9:7]
TRCTT: tensor tmp -> operand, optional conversion
```

The HMMAL immediate shape is:

```text
imm[1:0] = base mode, e.g. hmma.64
imm[2]   = A half selector
imm[3]   = B half selector
imm[6:4] = data_select_type0..7
imm[9:7] = destination tmp0..tmp7
```

The extracted docx examples show legacy-style generated HMMAL rows such as
`HMMAL,HMMAL25,MATRIXA1,MATRIXB0,...,128,0`, which matches:

```text
imm = (tmp_id << 7)
    | (data_select_type << 4)
    | (b_half << 3)
    | (a_half << 2)
    | base_mode
```

Detailed tensor facts are owned by:

```text
docs/architecture/instruction-set/dfu3500-tensor/README.md
docs/architecture/instruction-set/dfu3500-tensor/TYPE_CONVERSION_SOURCE_AUDIT.md
```

## Route / Reuse Evidence

The GEMM PPT explains that A data is reused across a PE row and copied between
PEs to reduce transfer cost.  This supports the B-line separation:

```text
StreamPlan:
  whole-value visibility / inter-stream topology

FiberPlan:
  per-output-tile K fibers and fragment reuse

RouteEndpointPlan:
  final COPY/COPYT sender/receiver operand binding
```

The source-backed endpoint details live in:

```text
docs/vendor_reference/common_oper/operand-resource-and-route-audit.md
```

## What Must Be Operationalized

Before B-line GEMM byte emission is called complete, it needs:

```text
1. TaskPartitionPlan:
   maps GEMM output work to task axis + PE axis without treating vendor rows as
   semantic source of truth.

2. InstanceBaseRowPlan:
   owns subtask instance count and base_addr0..3 rows.

3. TensorTmpResourcePlan:
   owns RXINT/HMMAL/TRCTT tmp lifetimes and HMMAL dst tmp ids.

4. OperandResourcePlan:
   owns PE-local operand RAM indices after template-local tags.

5. RouteEndpointPlan:
   owns A/B fragment route materialization and receiver-owned destination
   operands.

6. VendorComponentPlan:
   serializes fixed-size CBUF/MICC components with active rows and padded rows
   clearly distinguished.
```

## Current Status

```text
Extracted:
  GEMM PPT shape/subtask/instance facts and tensor instruction docs are present.

Absorbed:
  This card, hardware-constraints notes, GEMM binary replay notes, and tensor ISA
  notes summarize the major facts.

Operationalized:
  Partial in A-line compatibility code; not yet cleanly operationalized in B-line
  typed plans.

Runtime-proven:
  A-line legacy GEMM and functional maximum paths are runnable, but B-line GEMM
  byte emission remains a future integration target.
```
