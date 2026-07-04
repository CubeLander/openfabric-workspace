# GPDPU Hardware Working Model

This document records the hardware model currently used by the testcase
workflow investigation. It is a working model, not a vendor specification. When
the code gives direct evidence, the evidence is listed explicitly; when a point
comes from project discussion, it is marked as such.

## Topology

The target hardware has 16 processing elements, arranged as a 4 by 4 planar
mesh network.

Project discussion names the PEs as:

```text
PE00 PE01 PE02 PE03
PE10 PE11 PE12 PE13
PE20 PE21 PE22 PE23
PE30 PE31 PE32 PE33
```

The legacy GEMM code normally uses integer PE ids `0..15`. The most likely
human-readable mapping is row-major:

```text
0  1  2  3
4  5  6  7
8  9  10 11
12 13 14 15
```

This mapping is consistent with the row-wise `copyA` plan in the GEMM example,
but it still needs to be checked against the vendor ISA/runtime convention.

## Memory And Data Paths

Project discussion model:

```text
DRAM -> DMA -> CBUF
             -> SPM
             -> MICC
```

PEs communicate with adjacent PEs through mesh data channels. The instruction
stream can use `COPY` / `COPYT` style instructions to share data between PEs,
which reduces repeated SPM/CBUF bandwidth use.

Project discussion also says:

```text
PE00..PE03 and PE03..PE33 have direct SPM data paths.
PE30..PE33 have direct CBUF data paths.
```

The exact relationship between these named PE paths and the integer PE ids used
by generator code is still under investigation.

## GEMM Execution Model

For matrix multiplication, the workload is tiled and split across PEs:

```text
1. DMA/runtime prepares input data in SPM/CBUF/MICC.
2. Each PE loads the input tile or partial tile it owns.
3. Reusable data is propagated to neighboring PEs with COPY/COPYT.
4. PEs run local matrix instructions such as HMMAL.
5. Each PE stores its output tile back to its assigned output address.
```

This model is important for the workflow rewrite because the generator should
produce a PE-local instruction/data plan rather than treating GEMM as a single
flat program.

## Task/Subtask Execution Model

Project discussion and vendor documentation describe the execution model as
dependency-driven: the hardware/runtime analyzes instruction dependencies and
schedules legal execution order. We do not currently know the exact closed
runtime or microarchitecture scheduling algorithm.

The practical model for reading the GEMM testcase is:

```text
task0/subtask1: all active PEs prepare/load/scale their C tile
task0/subtask2: all active PEs load A/B, exchange reusable A data, compute
task0/subtask3: all active PEs store their C tile

task1/subtask1
task1/subtask2
task1/subtask3

task2/subtask1
task2/subtask2
task2/subtask3

task3/subtask1
task3/subtask2
task3/subtask3
```

Each subtask contains multiple per-PE CSV instruction streams. Conceptually the
PEs in the same subtask run in parallel, while the dependency graph and
instruction dependencies decide the precise legal ordering. `subtask4`, when
enabled by `SUBTASK_COUNT == 4`, is the optional fused post-op path.

## Code Evidence

The GEMM example has direct topology constants in:

```text
application/CASE/gemm_template_fusion/csv_generate/conf_PEmap.h
```

Relevant constants:

```c
#define PE_ROW 4
#define PE_COL 4
#define PE_NUM 16
```

The same file defines per-PE SPM offsets:

```text
taskAddr_per_pe_A
taskAddr_per_pe_B
taskAddr_per_pe_C
```

These maps are then consumed by the `new_temp.*` generators to emit per-PE CSV
instruction streams. In the current examples, these maps should be treated as
developer-authored source configuration rather than as proven output of a local
automatic planner.

The same file defines A-tensor transfer planning:

```c
copyA = {
  {0, {{0,1},{1,2},{2,3},{4,5},{5,6},{6,7},{8,9},{9,10},{10,11},{12,13},{13,14},{14,15}}},
  ...
};

loadA = {
  {0, {0,1,2,3}},
  {4, {0,1,2,3}},
  {8, {0,1,2,3}},
  {12, {0,1,2,3}}
};
```

This is direct evidence that GEMM loads A from a subset of PEs, then fans it out
to neighboring PEs through pairwise copies. Under row-major PE id mapping,
`copyA` is row-wise propagation. `loadA` injects A from PE ids `0,4,8,12`; this
needs to be reconciled with the named SPM direct-path description above.

Current project assumption: `copyA` is manually written by the operator
developer to express intended PE-to-PE data reuse. The workflow compiles this
plan; it does not decide where COPY should happen.

The `COPYT` instructions are generated from `copyA` in the restored
`task*_1.c` files, which correspond to `subtask2`. The important point is that
the C source iterates over each source PE in `copyA[unroll_i]`; if the current
`pe_id` is a copy source, it emits `COPYT` instructions into that PE's subtask2
CSV. For example, the `copyA` pairs:

```text
0->1, 1->2, 2->3
4->5, 5->6, 6->7
8->9, 9->10, 10->11
12->13, 13->14, 14->15
```

mean that A tile data is expected to move across neighboring PEs in each row
under the likely row-major PE id mapping. The exact encoding of the destination
PE or direction inside `COPYT` still needs to be decoded from the ISA/runtime
code.

The full observed COPYT compile pipeline is documented in:

```text
gemm-copyt-pipeline-notes.md
```

The PE-local operand RAM layout and the conversion from CSV operand strings to
final RTL operand indices are documented in:

```text
pe-operand-index-model.md
```

The restored generator sources in:

```text
former testcase/build_out/gemm_template_fusion_new_temp_analysis/sources/
```

show the concrete instruction roles:

```text
task*_1.c / subtask2:
  HLDT  loads A and B tiles from taskAddr_per_pe_A/B
  COPYT copies A between PEs according to copyA
  HMMAL performs matrix multiply accumulation

task*_2.c / subtask3:
  HSTT stores each PE's C tile to taskAddr_per_pe_C

task*_3.cpp / subtask4:
  emits optional fused post-op instruction sequences over per-PE C mappings
```

The `new_temp.c` files also contain direction comments:

```text
0 - up
1 - down
2 - left
3 - right
```

This supports the interpretation that the instruction stream is aware of mesh
neighbor directions, although the exact encoded field for `COPYT` still needs an
ISA-level decode.

## Open Questions

The following points should be resolved before we generate GEMM plans
automatically:

```text
1. Confirm the official mapping between integer PE ids 0..15 and PErc names.
2. Decode COPY/COPYT fields that are still template-specific, especially
   dst_pe_idx/type and direction/immediate use. The final RTL operand index and
   target PE coordinate fields are now described in
   `pe-operand-index-model.md`.
3. Locate the strongest code evidence for direct CBUF paths to PE30..PE33.
4. Clarify whether loadA={0,4,8,12} represents physical SPM access PEs,
   compiler scheduling choices, or a PE-id mapping difference.
5. Map HLDT/HSTT extra_fields to SPM/CBUF/MICC memory spaces.
```
