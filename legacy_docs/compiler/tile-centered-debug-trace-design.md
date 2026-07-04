# Tile-centered PE Debug Trace Design

This note records the human-facing design for Layer 3 in per-PE debug traces.

The structured `plan.json` and global `*.lines.txt` files can stay close to the
compiler's internal schema. A per-PE trace is different: it should help a kernel
developer quickly answer:

```text
For this output tile, what inputs are consumed?
What named intermediate results are produced?
What compute chain runs?
Which final tile is written?
```

Therefore Layer 3 in `pe/PE*.trace.txt` is intentionally tile-centered.

## Format

Use a small SSA-like tile program:

```text
TILE tile0 wave=wave0 task=0 output=y0->%t2:Y[m=0:64,n=0:64]
  inputs:
    a0 = A[m=0:64,k=0:256] via row_broadcast split=Kx4
    b0 = B[k=0:256,n=0:64] via column_broadcast split=Kx4
  compute:
    c0 = matmul_reduce_k(a0, b0) -> %t1:Cacc[m=0:64,n=0:64]
    y0 = relu(c0) -> %t2:Y[m=0:64,n=0:64]
  output:
    y0 -> %t2:Y[m=0:64,n=0:64]
```

The names `a0`, `b0`, `c0`, and `y0` are local references inside the debug
trace. They are not hardware operand names and are not parsed by later compiler
passes.

## Semantics

The block has three parts:

```text
inputs:
  Named tile inputs. Inputs can be local tiles, row/column broadcasts, workspace
  tiles, scalar summaries, or future collective results.

compute:
  A named compute chain. The first operation may be many-to-one, such as
  matmul_reduce_k, convolution, local_reduce, or attention block update. Later
  operations in the same tile phase should be local one-to-one transforms, such
  as relu, log10, maximum-with-scalar, cast, clamp, or scale.

output:
  The named result committed by this tile phase.
```

This structure makes fusion explicit:

```text
c0 = matmul_reduce_k(a0, b0) -> %t1:Cacc[...]
y0 = relu(c0)                -> %t2:Y[...]
```

Future local fusion can extend the compute chain:

```text
r0 = relu(c0)                -> %t2:R[...]
z0 = mul(r0, s0)             -> %t3:Z[...]
y0 = clamp(z0, min=0, max=6) -> Y[...]
```

Future collective-heavy programs can split naturally across phases:

```text
TILE tile0 local_reduce
  inputs:
    x0 = X[m=0:64,n=0:64] local
  compute:
    lmax0 = reduce_max(x0) -> %t1:LocalMax[scalar]
  output:
    lmax0 -> %t1:LocalMax[scalar]

COLLECTIVE reduce0
  inputs:
    lmax0 from PE00..PE33
  compute:
    gmax0 = all_reduce_max(lmax0) -> %t2:GlobalMax[replicated scalar]

TILE tile1 kind=local_elementwise
  inputs:
    x0 = X[m=0:64,n=0:64] local
    gmax0 = %t2:GlobalMax[scalar]
  compute:
    log0 = log10(x0)          -> %t3:Log[m=0:64,n=0:64]
    y0 = maximum(log0, gmax0) -> Y[m=0:64,n=0:64]
  output:
    y0 -> Y[m=0:64,n=0:64]
```

## Layering Rule

Layer 3 should summarize tile-level dataflow. It should not duplicate every
K-instance or every collective bundle:

```text
Layer 3:
  which tile is computed from which input spans and which named compute chain.

Layer 4:
  exact K-instance A/B/C tile ranges, grouped by tile/wave so long bundle ids
  do not dominate the PE trace. Materialize actions carry visibility,
  obligation_key, and route_ref fields.

Layer 5:
  backend-independent K tile step program and named member values.

Layer 6:
  architecture expansion for semantic tile ops, such as gemm_tile_update to
  legacy_dfu instruction templates.

Layer 7:
  route summary only. Full derived visibility obligations live in the global
  derived-obligation file. The default route lowering file is a compact
  pattern view, while `11_route_lowering.verbose.lines.txt` keeps the
  exhaustive per-route debug view.

Layer 8:
  DFU assembly summary. This is the first target-level symbolic surface:
  structured assembly records with source step/source route provenance, still
  before binary encoding. The compact global file is `14_dfu_assembly.lines.txt`;
  the exhaustive record dump is `14_dfu_assembly.verbose.lines.txt`.
```

This keeps Layer 3 readable while preserving detailed validation surfaces in
the lower layers.
