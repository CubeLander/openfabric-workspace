# Vendor assembler input protocol

Date: 2026-06-26

This is the second `second_wind` live document.  It records the input protocol
accepted by the vendor `build_app/common_oper` assembler and the cleanup policy
for consolidating hand-written operator sources.

## Decision

We should not preserve the vendor task/subtask source layout as the canonical
source form.

The canonical source should be centralized and parameterized:

```text
central operator source
  -> centralized vendor handwritten-operator emitters
  -> materialize vendor assembler input bundle
  -> run vendor build_app/common_oper
  -> produce runtime package
```

The first refactoring target is the vendor authoring source: the semi-automatic
CSV emitters and graph-hook source that operator authors maintain today.  The
generated/copied bundle is only a validation boundary.  It should contain the
artifacts consumed by the assembler, but it is not the main source we organize.

## Protocol Summary

The vendor assembler input is a case package:

```text
app*.conf
  + task*/subtask*/template/*.csv
  + task*/subtask*/build_so/libsubtask.so::generateGraph(...)
  + optional runtime case material
  -> application/build_app + testcase/common_oper
  -> simulator_bin + rtl_bin
  -> result/cbuf_file.bin + result/micc_file.bin
```

The important boundary:

```text
OpenFabric / second_wind owns:
  centralized operator source and operator plan
  centralized CSV-emitter source
  centralized graph-hook source or graph plan
  task/subtask/PE/source plan
  symbolic CSV template rows
  graph plan or graph plugin artifact
  provenance and manifest

vendor common_oper owns:
  CSV parsing and pseudo-op expansion
  LD/CAL/FLOW/ST stage splitting
  PE-local operand assignment
  COPY/COPYT destination patching
  exeBlock/task/subtask/instance serialization
  final CBUF/MICC binary package
```

## Required Input Files

For assembler-minimal packaging, `build_app/common_oper` needs:

```text
app0.conf
app1.conf
...

task0/subtask1/template/0.csv
task0/subtask1/template/1.csv
...
task0/subtask1/build_so/libsubtask.so

task0/subtask2/template/*.csv
task0/subtask2/build_so/libsubtask.so

task1/...
```

For a full runnable SimICT case, the surrounding workflow also needs:

```text
csv_generate/conf.h
csv_generate/conf_PEmap.h
spm_data/data_generate.c or generated input_data.bin
riscv/testarm.c or generated riscv_program
application/template/input_data_convert.c
common/src/*
dpuapi/DpuAPI.*
```

The second group is runtime/control material, not the assembler-minimal core.

## `app*.conf`

`app*.conf` is the top-level manifest parsed by `Task_Group::readFromTaskFile`.
It declares task and subtask containers.

Task fields:

```text
task_name
reuse_input_reg
reuse_output_reg
Execute Times
subtask_num
```

Subtask fields:

```text
subtask_name
reuse_input_reg
reuse_output_reg
Instance Times
code_path
csv_amount
graph height
graph width
```

Rules:

```text
csv_amount must match template/<i>.csv files.
code_path is normally template/.
graph height / graph width are passed to generateGraph(...).
Instance Times and Execute Times become runtime task/subtask config, not CSV rows.
```

## Template CSV Program

Each `task*/subtask*/template/<i>.csv` is one instruction-block template.

CSV rows carry symbolic operand names, not final PE operand RAM numbers.
The vendor parser and mapper assign final IDs later.

Typical columns:

```text
inst_name
inst_tag_name
src_reg_idx0
src_reg_idx1
dst_reg_idx
dst_pe_idx
imm
iteration
extra_field0
extra_field1
extra_field2
```

Rules:

```text
Keep symbolic operand tags stable.
Do not pre-bake final operand RAM indices.
Preserve provenance from each row back to the centralized source plan.
Emit rows in LD -> CAL -> FLOW -> ST order inside each block.
Pseudo rows such as HLDT, ILDMT, HSTT, COPYT may be emitted if common_oper owns their expansion.
Do not assume one CSV row becomes one final instruction row.
```

## Graph Plugin Protocol

Each subtask must provide a shared object containing:

```cpp
extern "C" void generateGraph(
    string task_name,
    string subTask_name,
    vector<GRAPH_NODE>& m_nodes,
    Inst_Block_Collect& inst_block_collect,
    uint64_t graph_height,
    uint64_t graph_width);
```

This function turns the subtask's CSV blocks into graph nodes.

Rules:

```text
Each graph node points at an Inst_Block loaded from template/<i>.csv.
generateGraph may set m_pos_idx_df to request a PE position.
generateGraph may add parent/child edges.
COPY/COPYT edges must identify the receiver endpoint; common_oper patches final destination PE/block/operand.
```

For simple softmax-like cases, the first generated graph can be:

```text
one active PE CSV block -> one GRAPH_NODE
explicit m_pos_idx_df
no inter-node edges
```

For GEMM-like cases, the graph plan must preserve:

```text
local load -> compute edges
load -> copy edges
copy -> copy edges
copy -> compute edges
COPYT receiver ownership
```

## Centralized Source Layout

The new source shape should be closer to this:

```text
operator_sources/
  softmax/
    case_plan.*
    template_program.*
    graph_plan.*
    runtime_control.*
  gemm_template_fusion/
    case_plan.*
    template_program.*
    graph_plan.*
    runtime_control.*
```

The centralized source should expose functions parameterized by task/subtask
identity, for example:

```text
emit_softmax_template(task_id, subtask_id, pe_id, plan)
emit_softmax_graph(task_id, subtask_id, graph_plan)

emit_gemm_template(task_id, subtask_id, pe_id, plan)
emit_gemm_graph(task_id, subtask_id, graph_plan)
```

The materialized assembler input bundle should then create the vendor
filesystem shape:

```text
assembler_input_root/
  app*.conf
  task*/subtask*/template/*.csv
  task*/subtask*/build_so/libsubtask.so
```

The old `task*/subtask*/template/*.cpp` files should not remain the authority.
They should not be emitted as the target artifact. If a graph plugin build step
temporarily needs C/C++, that code is an internal build detail, not the vendor
assembler input contract.

## Generated vs Source

Canonical source:

```text
central operator source
case plan
template program emitter
graph plan emitter
runtime control plan
manifest/provenance
```

Materialized assembler input bundle:

```text
app*.conf
task*/subtask*/template/*.csv
task*/subtask*/build_so/libsubtask.so
```

Transition-only source to retire:

```text
task*/subtask*/template/taskX_subtaskY.cpp
task*/subtask*/template/new_temp.c
task*/subtask*/template/new_temp.cpp
task*/subtask*/build_so/test_graph_extend.cpp
```

These are vendor authoring files today, but in second_wind they should be
replaced by centralized plans and emitters. They are not the desired output
format.

## Implementation Order

1. Define a manifest for the current handwritten source layout of `softmax_1`
   and `gemm_template_fusion`.
2. For `softmax_1`, centralize the repeated CSV-emitter source and graph-hook
   source without changing behavior.
3. For `softmax_1`, materialize an assembler input bundle containing
   `app*.conf`, `task*/subtask*/template/*.csv`, and
   `task*/subtask*/build_so/libsubtask.so`.
4. For `softmax_1`, replace copied CSV files with a centralized CSV-row emitter
   one subtask at a time.
5. Replace copied graph plugin artifacts only after the graph plan is explicit
   enough to reproduce the same assembler-visible behavior.
6. Run `cmake --build --preset vendor-cases-package`.
7. Compare generated runtime package with the current baseline package.
8. Only then repeat for GEMM, preserving `loadA`, `copyA`, and
   `taskAddr_per_pe_A/B/C` as explicit dataflow plan fields.

## Non-Negotiables

```text
Do not keep hand-maintained task/subtask source files as the long-term source of truth.
Do not write final CBUF/MICC bytes as the primary path.
Do not collapse conf.h, testarm.c, and package scripts into one abstraction.
Do not lose symbolic operand tags before common_oper mapping.
Do not hide graph edges inside CSV strings.
Do not call the package runtime-ready until the generated projection has been replayed through vendor build_app/common_oper.
```
