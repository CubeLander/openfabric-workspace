# Subtask Loop Folding Algorithm

一句话总结：subtask formation has two jobs: fold repeated consecutive
subgraphs into hardware instance loops, and partition the remaining graph by
hardware capacity.

## Why This Exists

The DFU runtime does not only use subtask as a named phase. A subtask can also
represent a repeated graph template:

```text
one subtask graph
+ N instance base-table rows
```

Therefore OpenFabric should not hard-code vendor phase names such as:

```text
init / compute / store
```

as the primary subtask construction rule. Instead, after the dependency DAG is
available, the packer should discover when adjacent graph regions are actually
the same graph shape with different instance-local addresses.

This turns hardware instance loops into an algorithmic result of the DAG.

## Core Principle

```text
Subtask packing =
  repeated-subgraph folding
  + capacity-constrained graph partitioning
```

The packer should try these mechanisms in order:

```text
1. loop folding:
     repeated graph template -> one subtask + N instances

2. capacity partition:
     oversized graph region -> multiple legal subtasks
```

## Repeated Consecutive Subgraph

A repeated consecutive subgraph is a set of adjacent graph windows with the same:

```text
logical dependency shape
physical dataflow graph shape
PE role structure
assembly record kind sequence
operand allocation shape
resource footprint
```

and different only in:

```text
instance-local tile ids
base_addr table rows
immediate offsets
K/block/wave indices
instance-local value ids
```

If these conditions hold, the windows can be folded into:

```text
one subtask graph + multiple subtask instances
```

## Algorithm Sketch

```text
1. Build the global tile dependency network.

2. Lower it into the DFU physical dataflow graph.

3. Split the graph into candidate consecutive windows:
     microstep windows
     topo-order windows
     repeated K-stream windows

4. For each candidate window, compute a canonical signature:
     op kinds
     tile dependency kinds
     physical graph node kinds
     physical graph edge kinds
     PE role / mesh coordinate role
     record role sequence
     resource footprint
     operand allocation shape

5. Normalize away instance-local symbols:
     concrete k index
     concrete base table row
     absolute tile id
     instance-local value id
     immediate offset values when they are base-row-derived

6. Scan adjacent windows for identical canonical signatures.

7. If N adjacent windows match and differ only by allowed instance-local
   bindings:
     emit one folded subtask template
     emit N instance table rows
     attach the per-instance tile/base/offset bindings.

8. If no legal fold exists:
     fall back to capacity-constrained graph partitioning.
```

## Capacity Partition Fallback

If a graph region cannot be folded, or if the folded template still does not fit,
the packer should introduce a new subtask when the current graph container would
exceed:

```text
instruction RAM
inst block count
exeBlock count
operand pressure
base address slot pressure
backend graph node/edge limits
required serial boundary constraints
```

Every capacity-driven split should report:

```text
first exceeded limit
graph region before split
graph region after split
estimated instruction / exeBlock / operand / base-slot pressure
```

## GEMM Explanation

Vendor GEMM has:

```text
subtask_instance_times = {1, 4, 1}
```

This should be explainable as repeated-subgraph folding:

```text
init:
  singleton graph region -> 1 instance

K streaming:
  four isomorphic K update graph slices -> 4 instances

store:
  singleton graph region -> 1 instance
```

For example:

```text
gemm_update(wave0,k0)
gemm_update(wave0,k1)
gemm_update(wave0,k2)
gemm_update(wave0,k3)
```

normalizes to:

```text
gemm_update(wave=?, k=instance)
```

and folds into:

```text
subtask2:
  graph = K-stream template
  instances = 4
```

This means `{1,4,1}` is not a magic vendor constant. It is the result of:

```text
singleton init graph
+ repeated K-stream graph
+ singleton store graph
```

## V1 Implementation Priority

Do not implement this before the dependency DAG is stable.

V1 dependency analysis should first produce:

```text
global_tile_dependency_network
dfu_dataflow_graph
```

with enough metadata to support future folding:

```text
canonical_signature
relative_dependency_shape
resource_shape
instance_local_symbols
```

Only after the graph dump is readable should OpenFabric implement the actual
subtask folding pass.

## Debug Output

When implemented, the packer should emit:

```text
FOLD_CANDIDATE id=... windows=... signature=...
FOLD_ACCEPTED id=... subtask=... instances=...
FOLD_REJECTED id=... reason=...
CAPACITY_SPLIT id=... reason=... limit=...
```

Human reviewers should be able to answer:

```text
Why is this repeated region an instance loop?
Why was this graph region split into another subtask?
Which symbols are instance-local rather than part of the graph template?
```
