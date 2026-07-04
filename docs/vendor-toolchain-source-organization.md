# Vendor Toolchain Source Organization

Date: 2026-06-30

This note maps the active SimICT/GPDPU operator build toolchain and proposes a
cleaner source organization for the `second_wind` OpenFabric path.

The goal is not to rewrite the vendor assembler immediately.  The goal is to
make the source boundaries match the project direction:

```text
ChipProgramPlan / operator intent
  -> OpenFabric compiler support projections
  -> vendor assembler input bundle
  -> quarantined vendor assembler and package backend
  -> runtime package image
```

## Current Source Closure

The open vendor build path touches these source groups.

| Source range | Current role | Keep as |
| --- | --- | --- |
| `common/src/*` | Target ABI structs, instruction definitions, MICC/DMA/PE/memory definitions, `libcommon.so` support | Target ABI support |
| `dpuapi/DpuAPI.*` | RISC-V-side runtime API declarations and implementation used by `riscv/testarm.c` | Target runtime API support |
| `testcase/common_oper/*` | Vendor assembler library: CSV parse, pseudo instruction expansion, graph/task construction, PE operand mapping, exe block generation, simulator/RTL binary serialization | Quarantined vendor assembler backend |
| `testcase/common_oper/map/*` | Operand/block mapping strategy implementations copied into `inst_blk_map.cpp/h` by `common_oper/run.sh` | Backend strategy module |
| `testcase/application/build_app/*` | Tiny assembler driver executable. `main.cpp` is the launch entry that calls `Task_Group`, `INST_BLK_MAP`, `exe_block_gen`, and `Print_Task_Group` | Quarantined vendor assembler driver |
| `testcase/application/template/input_data_convert.c` | Shared SPM/input data converter used by package construction | Target data-staging utility |
| `testcase/application/<vendor_case>/csv_generate/*` | Case config generator, `app*.conf`, instance base rows, legacy `conf.h/conf_PEmap.h` truth copies | Case authoring source plus generated config artifacts |
| `testcase/application/<vendor_case>/gpdpu_*/*` | Case device program source that emits per-task/per-subtask CSV templates | Case authoring source |
| `testcase/application/<vendor_case>/task*/subtask*/build_so/*` | Graph hook source and generated `libsubtask.so` compatibility surface | Graph plan source plus generated compatibility artifact |
| `testcase/application/<vendor_case>/spm_data/*` | Input/golden/SPM data generation and checks | Case data source |
| `testcase/application/<vendor_case>/riscv/*` | RISC-V control program and makefile | Runtime control source |
| `tools/vendor_case/*` | Python staging, scanning, packaging, refactored replay, binary comparison | Repository orchestration |
| `testcase/application/common_app_builder/*` | Current OpenFabric support layer for distributed plans, CSV projection, graph trace, instance config, runtime plan image, and common RISC-V executor | Promote to OpenFabric compiler support |

## Actual Build Phases

The source closure above is exercised as:

```text
common/src
  -> libcommon.so

testcase/common_oper + selected map strategy
  -> libapp_build_common.so

case csv_generate/test_app_conf_generate.c
  -> app*.conf
  -> simulator_bin/instance_conf_info_file.bin
  -> rtl_bin/cbufData_instance.bin

case gpdpu_* task_main / templates
  -> task*/subtask*/template/*.csv

case graph hook source
  -> task*/subtask*/build_so/libsubtask.so

case spm_data
  -> input_data.bin and optional RTL/check artifacts

case riscv/testarm.c + dpuapi
  -> riscv/riscv and riscv/riscv.lst

application/build_app/main.cpp + common_oper
  -> simulator_bin/insts_file.bin
  -> simulator_bin/exeblock_conf_info_file.bin
  -> simulator_bin/tasks_conf_info_file.bin
  -> simulator_bin/subtasks_conf_info_file.bin
  -> simulator_bin/data_inst_replace.bin
  -> rtl_bin/cbufData_*.bin and miccData_*.bin

package collector
  -> result/cbuf_file.bin
  -> result/micc_file.bin
  -> runtime package config/*
```

`application/build_app/main.cpp` is therefore the assembler driver entry, not an
operator source file.  It belongs to the backend boundary.

## Problems In The Current Layout

The current tree preserves the vendor build shape, but that shape hides
ownership:

- Case authoring source, generated files, build scripts, and backend binaries
  live in the same directories.
- `csv_generate/run.sh` is both a config generator driver and a whole-case build
  orchestrator.
- `common_oper/run.sh` changes backend behavior by copying map source files over
  `inst_blk_map.cpp/h`.
- `common_app_builder` is under `testcase/application`, but it is no longer an
  application helper; it is OpenFabric compiler support.
- Runtime control facts still appear in several projections: device program
  plan, instance config, RISC-V control code, and runtime package metadata.
- Vendor backend source and OpenFabric-owned support code are adjacent enough
  that it is easy to accidentally treat `common_oper` as code we should refactor
  for aesthetics.  For now it is a compatibility backend.

## Proposed Logical Organization

The next source organization should make ownership explicit before moving large
files:

```text
simict3500final/gpdpu/users/risc_nn_riscv/
  target_support/
    abi/                         # current common/src logical role
    riscv_api/                   # current dpuapi logical role
    data_staging/                # current application/template utilities

  vendor_backend/
    assembler_core/              # current testcase/common_oper
    assembler_driver/            # current application/build_app
    map_strategies/              # current common_oper/map
    README.md

  openfabric_support/
    plan/                        # ChipProgramPlan, DTensor, mesh, memory plans
    device_projection/           # Fiber/Register actions, CSV instruction streams
    vendor_projection/           # app conf, instance config, graph compat, vendor CSV files
    runtime_projection/          # RuntimePlanImage, RISC-V executor, API trace gates
    validation/                  # graph/runtime readers and comparison helpers

  testcase/application/
    <vendor_case>/               # preserved vendor evidence case
    <op>_refactored/
      operator_sources/<op>/
        case_plan.json
        chip_program/
        data_program/
        README.md
```

This is a logical target shape.  Physical moves should happen only after replay
proves that include paths, generated artifacts, and package outputs remain
equivalent.

## Near-Term Physical Layout

Before a broad move, use this lower-risk intermediate organization:

```text
testcase/application/common_app_builder/
  plan/
  device_projection/
  vendor_projection/
  runtime_projection/
  validation/

testcase/application/build_app/
  README.md                      # mark as vendor assembler driver

testcase/common_oper/
  README.md                      # mark as vendor assembler core
  map/
```

The current flat `common_app_builder` headers can move into subdirectories in
small groups:

| New group | Existing files |
| --- | --- |
| `plan/` | `dtensor_plan.h`, future `chip_program_plan.*` |
| `device_projection/` | `fiber_actions.h`, `fiber_values.h`, `operand_allocator.h`, `register_actions.h`, `subtask_site.h`, `vendor_symbol_program.h`, `vendor_memory.h`, `vendor_numeric_helpers.h` |
| `vendor_projection/` | `vendor_app_config.h`, `vendor_csv_backend.h`, `vendor_emit_site.h`, `vendor_instance_config.h`, `vendor_instruction_block_file.h`, `vendor_instruction_stream.h`, `openfabric_graph_trace.h`, `openfabric_graph_trace_hook.cpp`, `openfabric_graph_trace_reader.h` |
| `runtime_projection/` | `openfabric_runtime_plan_image.h`, `openfabric_runtime_plan_riscv_executor.*`, `openfabric_runtime_plan_riscv_program.c`, `openfabric_runtime_api_trace.h`, `openfabric_riscv_trace_dpu_api.*`, `embed_runtime_plan_image.py` |
| `validation/` | dump/read helpers and future comparison gates that are not case-specific |

Use forwarding headers during the move so existing refactored operators can be
updated incrementally:

```cpp
// common_app_builder/dtensor_plan.h
#include "plan/dtensor_plan.h"
```

After all includes are migrated and replay passes, remove the forwarding layer.

## Operator Case Shape

Each refactored operator should own source, not generated vendor directories:

```text
operator_sources/<op>/
  case_plan.json
  chip_program/
    <op>_chip_program.h          # one source of truth for shape, memory, work split
  device_program/
    main.cpp                     # emits CSV/config/graph/runtime projections
    <op>_template_program.h
    <op>_fiber_actions.cpp       # only if behavior is not shared
  data_program/
    ...
  README.md
```

Avoid restoring these as maintained source:

```text
task*/subtask*/template/*.csv
task*/subtask*/build_so/libsubtask.so
simulator_bin/*
rtl_bin/*
result/*
app*.conf
case-local build_app binaries
```

They are replay/package outputs or compatibility surfaces.

## Ownership Rules

Use these rules when deciding where new code goes:

1. If it describes operator shape, tensor ownership, memory scope, task/subtask
   split, PE placement, or runtime-visible launch intent, it belongs in the
   OpenFabric plan layer.
2. If it turns a plan into vendor CSV rows, app config, instance config, graph
   trace, or runtime plan image, it belongs in OpenFabric projection support.
3. If it parses CSV, assigns final PE-local operand indices, patches COPY/COPYT
   destinations, builds exe blocks, or serializes MICC/CBUF binary structs, it
   remains in the quarantined vendor backend until explicitly replaced.
4. If it is only needed to stage, patch, compare, or package a vendor-shaped
   worktree, it belongs in `tools/vendor_case`.
5. If it is a runnable vendor case from the customer tree, preserve it as
   evidence.  Refactored source should point back to it through `case_plan.json`
   and replay comparison, not overwrite it.

## Migration Plan

### M0: Label boundaries

Add README files for:

```text
testcase/common_oper/
testcase/application/build_app/
testcase/application/common_app_builder/
```

The README files should say whether the directory is vendor backend, OpenFabric
support, or generated compatibility surface.

### M1: Split OpenFabric support internally

Move `common_app_builder` files into `plan/`, `device_projection/`,
`vendor_projection/`, `runtime_projection/`, and `validation/` with forwarding
headers.  Update only one refactored operator first, run syntax and replay, then
update the second.

### M2: Remove source-copy strategy switching

Replace `common_oper/run.sh` source-copy selection for
`inst_blk_map.cpp/h` with an explicit build variable or adapter source.  This
keeps backend strategy selection visible without mutating tracked source files.

### M3: Introduce a package compiler facade

Create a small OpenFabric-facing driver around `tools/vendor_case`:

```text
openfabric package <operator_source>
  -> materialize vendor input bundle
  -> run vendor backend
  -> collect runtime package
  -> write manifest and comparison report
```

Internally this may still call `application/build_app/main.cpp`, but users and
operator sources should not need to know that path.

### M4: Promote `ChipProgramPlan`

Make each refactored operator produce a single chip-level plan and derive:

```text
device CSV projection
app/task/subtask config
instance base rows
graph trace
runtime plan image
RISC-V executor inputs
package manifest
```

This prevents the old pattern where `conf.h`, `conf_PEmap.h`, RISC-V source,
and CSV emitters each carry overlapping truth.

## Non-Goals For Now

- Do not rewrite `common_oper` only to make it pretty.
- Do not bypass `application/build_app/main.cpp` before final binary comparison
  proves an alternative backend.
- Do not make generated vendor-shaped task directories canonical source.
- Do not mine the archived B-line generator as the new default package route.
- Do not change target ABI structs in `common/src` unless a runnable vendor case
  or binary comparison justifies the change.

## Immediate Recommendation

The next useful code change is small:

1. Add boundary README files to `common_oper`, `application/build_app`, and
   `common_app_builder`.
2. Start splitting `common_app_builder` by projection layer with forwarding
   headers.
3. Keep `common_oper` and `build_app` physically stable until both softmax and
   GEMM replay continue to match.

This improves the source shape without weakening the current comparison-backed
vendor workflow.
