# Operand Resource And Route Source Audit

Date: 2026-06-20

Status: source audit card for `common_oper` operand/resource behavior

This note records the vendor-source evidence for PE-local operand allocation,
COPY/COPYT endpoint ownership, and graph-node-to-PE mapping.  These facts are
binary-critical: they influence instruction rows and route payloads, not just
pretty debug names.

## Source Files

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/inst_map_common.h
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/inst_map_common.cpp
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper/inst_blk_map.cpp
```

Related docs:

```text
docs/architecture/instruction-set/dfu3500-simd/OPERAND_LANE_MODEL.md
docs/architecture/instruction-set/dfu3500-simd/MEMORY_AND_TEMPLATE_EXECUTION_NOTES.md
docs/vendor_reference/common_oper/dfu3500-hardware-constraints-from-vendor-algorithms.md
```

## PE And Graph Position Model

`OP_POS` stores the vendor graph position:

```text
x, y, z, pe_idx, block_idx, graph_idx
```

`setPEPos` maps linear PE index to 2-D PE coordinates:

```text
x = pe_idx / PE_ARRAY_Y_LEN
y = pe_idx % PE_ARRAY_Y_LEN
z = 0
```

`setNodes` attaches a `GRAPH_NODE` to one PE and assigns:

```text
node start register index = PE register counter
node block index          = PE-local graph-node index
node name                 = n{x}_{y}_{block_idx}_{graph_idx}
```

Reference source:

```text
inst_map_common.h:16
inst_map_common.cpp:129
inst_map_common.cpp:139
```

### Compiler implication

A B-line `Stream/Fiber` location should not be just a string name.  It needs a
stable coordinate equivalent to:

```text
(task_id, pe_x, pe_y, block/fiber identity)
```

The final vendor binding can then project it to PE-local `block_idx` and row
indices.

## Operand Offset Pass

`fillRegIdx` adds each node's `m_start_reg_idx` to all instruction source and
destination operand indices across LD/CAL/FLOW/ST stages.

Reference source:

```text
inst_map_common.cpp:173
inst_map_common.cpp:185
```

### Compiler implication

Template-local operand tags are not final hardware operand indices.  A B-line
`TemplateOpPlan` may use symbolic operands, but a later `OperandResourcePlan`
must own final PE-local operand allocation.

Do not bake final operand numbers into high-level op specs.

## COPY / COPYT Destination Ownership

For inter-node COPY instructions, the vendor source patches destination metadata
from the child/receiver node:

```text
dst block index = child node PE-local block index
dst PE position = child node x/y
dst operand     = child node start_reg_idx + child template operand tag
```

Reference source:

```text
inst_map_common.cpp:226
inst_map_common.cpp:245
```

`inst_blk_map.cpp` contains the heavier route/template replay path and follows
the same core idea: route destination operands are receiver-owned, not
sender-owned.

### Compiler implication

A B-line route action should carry two identities:

```text
logical owner:
  receiver stream/fiber where the value becomes visible

physical executor:
  sender/route-side instruction placement if vendor COPY/COPYT emits there
```

The final destination operand must come from the receiver endpoint's operand
resource plan.  This is exactly the pain that made route binding feel haunted in
A-line.

## Local COPY Rewrite

`fillLocalCpInst` rewrites `LCOPY`/`LCOPYT` into `COPY` with destination block and
PE set to the same node.

Reference source:

```text
inst_map_common.cpp:263
```

### Compiler implication

Local movement and inter-PE movement may share the final opcode family, but they
should remain separate semantic actions until binding.  Collapsing them too
early hides endpoint ownership and can make dependency debugging much harder.

## Router Distance

`routerDist` computes Manhattan distance in PE coordinates:

```text
abs(src.x - dst.x) + abs(src.y - dst.y)
```

Reference source:

```text
inst_map_common.cpp:285
```

### Compiler implication

Route cost/debug reports can use Manhattan distance as a source-backed first
metric, but final route path selection still belongs to the stream/topology
planner, not to an op spec.

## What B-line Should Operationalize

```text
1. CoordinatePlan:
   stable `(task, pe_x, pe_y, fiber/block)` location metadata.

2. OperandResourcePlan:
   converts symbolic template operands into PE-local operand RAM indices.

3. RouteEndpointPlan:
   records sender executor, receiver logical owner, destination block and
   receiver-owned operand binding.

4. LocalMovePlan vs RouteMovePlan:
   keeps local copy and inter-PE copy distinct until final binding.
```

## Current Status

```text
Extracted:
  `inst_map_common` PE/operand/COPY rules are identified.

Absorbed:
  This note and the SIMD operand-lane notes record the source-backed behavior.

Operationalized:
  Partial.  B-line stream/fiber IR has the right conceptual split, but final
  operand and endpoint binding still needs typed checks.

Runtime-proven:
  A-line functional maximum probe ran, but it did not stress COPY/COPYT endpoint
  ownership.  GEMM/ReLU path remains the stronger route evidence.
```
