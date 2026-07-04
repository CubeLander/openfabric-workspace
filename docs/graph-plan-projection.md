# Graph Plan Projection

OpenFabric should treat graph material as a device-side dataflow and copy
dependency projection, not as a side artifact owned by the vendor plugin.

The current DFU3500/SimICT carrier still consumes a generated `generateGraph`
plugin under each vendor subtask directory. That plugin is a compatibility
backend. The source of truth should be an OpenFabric graph projection derived
from the same program facts that own tensor placement, PE ownership,
instruction block identity, and runtime launch material.

## Vendor Boundary

The active vendor package builder loads graph plugins from generated case
directories:

```text
gpdpu_TestOp/task{task_id}/subtask{subtask_id}/build_so/test_graph_extend.cpp
  -> build_so/libsubtask.so
```

`common_oper` calls the plugin through this ABI:

```cpp
extern "C" void generateGraph(
    string task_name,
    string subTask_name,
    vector<GRAPH_NODE> &m_nodes,
    Inst_Block_Collect &inst_block_collect,
    uint64_t graph_height,
    uint64_t graph_width);
```

`app*.conf` supplies `csv_amount`, `graph height`, and `graph width`. The
vendor loader reads template CSV files into `Inst_Block_Collect` before calling
`generateGraph`.

This means the graph backend sees both the template blocks and the graph shape.
OpenFabric should generate that backend from its own graph projection rather
than maintaining local graph tables beside CSV generation.

## Concepts

A minimal OpenFabric graph projection needs these concepts:

```text
GraphNode
  task/subtask
  instruction block reference
  placement PE
  root/leaf metadata

GraphEdge
  producer node
  consumer node
  dependency kind
  copy binding / route selector when the edge patches COPY/COPYT rows

GraphPlan
  nodes
  edges
  target backend projection
```

For simple operators such as the current softmax/log10max shape, the graph may
degenerate to one node per active PE and no explicit edges.

For GEMM-family operators, graph edges are behaviorally important. The vendor
graph relationships patch COPY/COPYT destinations after mapping, so a GEMM
graph projection must preserve load-to-copy, copy-to-copy, and copy-to-compute
relationships rather than flattening them into block order.

## Working Rules

- Graph source generation is a target compatibility writer, not the authority.
- Graph edges are not merely ordering edges; on this target they may also bind
  parent copy instructions to consumer nodes.
- Copy topology must eventually come from the same plan facts that emit COPY or
  COPYT rows.
- Softmax/log10max can use the same graph model through a degenerate strategy,
  but GEMM-level block nodes and explicit edges define the required expressive
  ceiling.
- Do not make graph generation block current runtime-action work. Preserve the
  facts needed for future graph projection while continuing to compare generated
  packages against vendor baselines.

See also:

```text
gemm-vendor-graph-csv-layout.md
gemm-subtask-blocks-and-graph-dependency.md
```
