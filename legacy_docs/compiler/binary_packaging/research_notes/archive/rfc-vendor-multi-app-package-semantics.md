# RFC: Vendor Multi-App Package Semantics And OpenFabric AppPlan Lowering

Status: Proposed for review

Date: 2026-06-16

Scope: OpenFabric `AppPlan`, `ProcessorTaskPlan`, DFU3500 package planning,
`ProgramVendorABI`, `ProgramBinRows`, and SimICT package generation.

## Summary

OpenFabric now has a first-class semantic `AppPlan` layer, but the runnable DFU3500
binary path still effectively emits one SimICT runtime package:

```text
ProgramBinRows
  -> config/cbuf_file.bin
  -> config/micc_file.bin
```

The vendor examples use the word "app" in a different, overloaded way. In the
observed `build_app` flow, `app0.conf` ... `app3.conf` are read as multiple
`Task_Group` inputs to one `build_app` invocation, and the output is still one
combined runtime package.

Therefore:

```text
OpenFabric AppRegion
  != vendor appN.conf exactly
  != MAX_APP_AMOUNT runtime app table entry
```

The current compiler can describe multiple semantic apps at the IR level, but it
does not yet have a proven runnable mapping from multiple OpenFabric `AppRegion`
objects into one or more DFU3500 runtime packages.

This RFC proposes a conservative path:

1. Keep `AppPlan` as the semantic app boundary and PE-local lifetime boundary.
2. Add an explicit `VendorPackagePlan` / `VendorPackageGroupPlan` layer before
   `ProgramVendorABI`.
3. Treat the current vendor `app*.conf` shape as "multiple task groups in one
   runtime package", not as cross-package semantic app sequencing.
4. For non-GEMM staged operators such as `log10max`, keep runnable binary emission
   gated until app-to-package mapping and storage handoff are explicitly modeled.

## Investigation Notes

### Vendor Entry Flow

The top-level SimICT script is:

```text
simict3500final/gpdpu/users/risc_nn_riscv/test/run_app_riscv.sh
```

Relevant behavior:

```text
Duplicate_Application_Amount=1 by default
arg2 overrides Duplicate_Application_Amount
app_num=1 by default

cd testcase/application/${app_name}
./run.sh

cd testcase/application/build_app
./run_mtr.sh ${app_name} ${Duplicate_Application_Amount} ${app_num}

cp testcase/application/${app_name}/result ./config -r
cp testcase/application/${app_name}/input_data.bin ./config
cp testcase/application/${app_name}/riscv/riscv ./config/riscv_program

runtime consumes config/result/cbuf_file.bin and config/result/micc_file.bin
```

For `gemm_template_fusion 4`, the second argument is not a second host runtime
package count. It causes `run_mtr.sh` to pass four app config files to
`build_app`:

```text
./build_app app0.conf app1.conf app2.conf app3.conf
```

### Vendor `run_mtr.sh` Packaging

The relevant script is:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/build_app/run_mtr.sh
```

It constructs `Build_Conf_ARG` from `app0.conf ... appN.conf`, runs one
`build_app`, then concatenates component files:

```text
simulator_bin/insts_file.bin
simulator_bin/exeblock_conf_info_file.bin
simulator_bin/instance_conf_info_file.bin
  -> simulator_bin_multi_app/cbuf_file.bin

simulator_bin/tasks_conf_info_file.bin
simulator_bin/subtasks_conf_info_file.bin
  -> simulator_bin_multi_app/micc_file.bin

simulator_bin/data_inst_replace.bin
  -> simulator_bin_multi_app/data_inst_replace.bin
```

Then:

```text
simulator_bin_multi_app/cbuf_file.bin
simulator_bin_multi_app/micc_file.bin
simulator_bin_multi_app/data_inst_replace.bin
  -> result/
```

So in the observed workflow, `simulator_bin_multi_app` means "combined package
from one or more `app*.conf` inputs"; it does not prove that the hardware MICC
table supports multiple independent runtime apps in one launch.

### Vendor `build_app/main.cpp`

The restored `build_app/main.cpp` constructs one `Task_Group` per input config:

```text
for each argv[1..]:
  Task_Group::readFromTaskFile(appN.conf)
  Task_Group::tasksConstruct()
  Task_Group::map(INST_BLK_MAP)
  task_groups.push_back(task_group)

exe_block_gen(...)

for each task_group:
  task_group->task_idx = i
  Print_Task_Group::print_task_group(...)

Print_Task_Group::print_inst(...)
Print_Task_Group::fill_task_simulator(task_groups)
Print_Task_Group::task_inst_enable_print(task_groups)
Print_Task_Group::print_for_micc_rtl(task_groups)
```

The comment in `main.cpp` says "multiple application", but the emitted SimICT
tables still use the DFU3500 task/subtask capacity described below.

### Vendor Capacity Constants

The DFU3500 headers define:

```text
MAX_APP_AMOUNT = 1
MAX_CUR_TASK_CONF_PER_APP = 4
MAX_SUBTASK_PER_TASK = 8
MAX_INSTANCES_PER_SUBTASK = 2048
MAX_TASK_AMOUNT = MAX_APP_AMOUNT * MAX_CUR_TASK_CONF_PER_APP = 4
MAX_SUBTASK_AMOUNT = MAX_TASK_AMOUNT * MAX_SUBTASK_PER_TASK = 32
```

This is strong evidence that the currently runnable SimICT package is one
hardware/runtime app image with up to four task rows and thirty-two subtask rows.

### RISC-V Control And Hardware Launch Behavior

The RISC-V control path gives the clearest evidence for how original vendor
"apps" execute.

`gemm_template_fusion/riscv/dpuctrl*.c` performs package transfers once before
the `app_num` loop:

```text
DPU_CbufTransfer(CBUF_DDR_ADDR)
DPU_MiccTransfer(MICC_DDR_ADDR)

for app_num in ...:
  DMA input tiles into SPM for this app_num
  wait previous MICC buffer if needed
  inst_reload = app_num > 0 ? 0 : 1
  DPU_Kernel_Start(
    inst_reload,
    TASK_NUM,
    instance_base = ((app_num % 2) * 0x400000) / 4,
    instance_base_noneed = 0,
    buf_num = app_num % 2,
  )
  optionally DMA previous output from SPM to DDR

final:
  wait last buffer
  DMA final output
  DPU_App_Finish()
```

`DPU_Kernel_Start` writes:

```text
MICC_INSTANCE_BASE
MICC_INSTANCE_BASE_NONEED
MICC_BUF{0,1}_INST   # 1 reload insts, 0 keep insts
MICC_BUF{0,1}_TASK   # task enable mask, e.g. 4 tasks -> 0b1111
MICC_BUF{0,1}_START
```

This means the observed multi-`app_num` flow does **not** automatically preserve
or exchange PE-local state between semantic app stages. The RISC-V program:

1. loads one combined CBUF/MICC program package,
2. explicitly DMA-loads each `app_num`'s input data into SPM,
3. starts MICC on one of two buffers,
4. uses `inst_reload=1` only for the first launch and keeps instructions for
   later launches,
5. changes the instance-base selector per launch,
6. explicitly DMA-stores outputs.

So the hardware behavior is closer to:

```text
one resident program package
  + repeated host/RISC-V controlled launches
  + explicit SPM/DDR data movement
  + explicit instance-base switching
```

not:

```text
multiple semantic apps sharing PE registers/tensor_tmp state implicitly
```

This is the key reason OpenFabric must treat cross-`AppRegion` values as storage
handoffs, not as PE-local dependencies.

### Vendor `appN.conf`

For `gemm_template_fusion`, each `appN.conf` contains exactly one task:

```text
app0.conf -> task(task_name:task0; subtask_num:3)
app1.conf -> task(task_name:task1; subtask_num:3)
app2.conf -> task(task_name:task2; subtask_num:3)
app3.conf -> task(task_name:task3; subtask_num:3)
```

Each task has:

```text
subtask1: Instance Times = 1
subtask2: Instance Times = 4
subtask3: Instance Times = 1
```

The better interpretation is:

```text
vendor appN.conf
  = one task-group config file
  = usually one vendor task row for the observed GEMM/softmax cases
```

not:

```text
vendor appN.conf
  = one OpenFabric semantic app boundary
```

### `Print_Task_Group` Emission

`Print_Task_Group::print_task_group` writes the tasks of each `Task_Group`, then
pads subtask rows to `task_amount * MAX_SUBTASK_PER_TASK`.

`Print_Task_Group::fill_task_simulator` pads the total task table to
`MAX_CUR_TASK_CONF_PER_APP`.

This matches the package layout we have reproduced:

```text
cbuf_file.bin:
  insts_file.bin
  exeblock_conf_info_file.bin
  instance_conf_info_file.bin

micc_file.bin:
  tasks_conf_info_file.bin
  subtasks_conf_info_file.bin
```

## Current OpenFabric Support

### Already Present

OpenFabric now has semantic app metadata:

```text
ChipProgram
  -> AppPlan
      AppRegion
      FusionRegion
      AppStorageRegion
      AppStorageEdge
```

For `log10max`, the current plan can represent:

```text
app0:
  clamp/log/reduce
  materialize global_max

app1:
  reload input
  load global_max
  recompute clamp/log
  post-process/store
```

The tile layer can also express symbolic app-storage actions:

```text
scalar_materialize_store
scalar_broadcast_load
materialized_storage dependency
```

### Missing

The runnable binary path does not yet describe:

```text
multiple OpenFabric AppRegion objects
  -> one or more VendorPackagePlan groups
  -> one or more ProgramVendorABI packages
  -> one or more cbuf/micc/runtime config launches
```

Current `ProgramBinRows` and `program_serializer.py` assume a single package:

```text
components -> config/cbuf_file.bin
components -> config/micc_file.bin
```

There is no explicit representation of:

```text
package_id
vendor_package_group_id
semantic_app_ids contained by package
inter-package storage handoff
riscv/control sequencing for multiple package launches
```

## Problem

The term "app" currently has three meanings:

### 1. OpenFabric Semantic App

```text
AppRegion = PE-local state lifetime boundary
```

This is a compiler semantic object. PE-local operands, registers, tensor temps,
and accumulators cannot cross this boundary unless materialized through explicit
storage.

### 2. Vendor Build Input `appN.conf`

```text
appN.conf = one Task_Group input to build_app
```

In observed GEMM and softmax packages, each `appN.conf` usually contains one
task named `taskN`. Multiple `appN.conf` files are packed into one task table.

### 3. DFU3500 Runtime App Capacity

```text
MAX_APP_AMOUNT = 1
```

The current runtime package format appears to support one app image at a time,
with up to four task rows inside that image.

These cannot be collapsed into one type without corrupting compiler layering.

## Desired Invariants

1. `AppRegion` is semantic and frontend/mid-end owned.
2. `Task` is app-local vendor work partitioning, not a global semantic phase.
3. `VendorPackagePlan` decides how semantic apps become vendor package groups.
4. `ProgramVendorABI` consumes a package/application-group plan; it must not infer
   semantic app boundaries from `appN.conf` naming or task id.
5. `ProgramBinRows` serializes one package at a time.
6. Multi-package sequencing must be explicit before runnable multi-app binary is
   allowed.
7. Cross-OpenFabric-app dependencies must be storage edges, never PE-local value
   edges.

## Proposed Model

## Automatic App Boundary Inference

OpenFabric should not require users to manually place every `AppRegion`.
The compiler should infer semantic app boundaries from synchronization, storage,
and state-lifetime requirements.

### Strong App-Cut Candidates

The following patterns should normally introduce an `AppRegion` boundary:

```text
1. Global collective -> later parallel region

   Example:
     reduce_max(X) produces global_max
     later elementwise stage consumes global_max on all processors

   Reason:
     PE-local partial values cannot be assumed visible everywhere.
     The collective result must become a materialized or explicitly broadcast
     value before the next region.

2. Incompatible primary schedules

   Example:
     reduce_tree schedule followed by elementwise_tile_wave schedule

   Reason:
     Task partitioning is app-local. A reduce tree and a tile-parallel phase
     should not be silently packed into one vendor task policy.

3. Cross-region value requires storage handoff

   Example:
     app0 produces global_max_storage
     app1 loads global_max_storage

   Reason:
     This is exactly the OpenFabric app boundary contract.

4. PE-local value would otherwise cross a sequencing boundary

   Example:
     tensor_tmp/log_tile computed before a global reduction and consumed after
     the reduction without materialization.

   Reason:
     PE-local state is not an inter-app ABI.
```

### Not Every Collective Is Automatically An App Boundary

Some collectives are implementation details inside a single app:

```text
GEMM route/broadcast:
  A/B tile visibility movement inside one GEMM schedule.

Tile route:
  sender-push visibility for compute, not an app boundary.

Loop-carried accumulator:
  instance-repeat carried state inside one subtask, not an app boundary.
```

So the rule is not:

```text
any collective == app boundary
```

The better rule is:

```text
collective result consumed by a different primary schedule
or after a global synchronization/materialization point
=> app boundary unless a same-app hardware proof exists.
```

### Log10Max App Count

For the audio preprocessing `log10max` operator, semantic app count should be
greater than one.

The conservative split is:

```text
AppRegion 0:
  clamp_min
  log10
  reduce_max
  materialize global_max

AppRegion 1:
  reload input
  load global_max
  recompute clamp_min/log10
  maximum(log_spec, global_max - 8)
  affine transform
  store output
```

Therefore:

```text
OpenFabric semantic app amount = 2
DFU3500 current runtime MAX_APP_AMOUNT = 1
```

These are not contradictory. They live at different layers:

```text
semantic app amount:
  how many PE-state lifetime regions the compiler sees

runtime MAX_APP_AMOUNT:
  how many runtime app images the current SimICT package profile exposes
```

Current consequence:

```text
log10max:
  AppPlan / TileProgram may contain 2 semantic apps
  runnable DFU3500 ProgramBinRows remains gated
  until VendorPackagePlan proves same-package or multi-package sequencing
```

### App Boundary Inference Pass

Add a compiler pass conceptually before processor/tile lowering:

```text
ChipProgram / FusionRegion candidates
  -> AppBoundaryInference
  -> AppPlan
```

The pass should:

```text
1. identify primary schedules,
2. identify collective outputs,
3. classify values as PE-local vs materialized,
4. cut at required storage handoff boundaries,
5. clone/recompute cheap tile-local ops when crossing an app boundary is cheaper
   than materializing their full tile outputs,
6. emit AppStorageRegion/AppStorageEdge for required cross-app values.
```

For `log10max`, this is why `log_spec` is recomputed in app1 while `global_max`
is materialized:

```text
log_spec:
  tile-local, large, cheap enough to recompute, not stored across app boundary

global_max:
  collective scalar, required by app1, cheap and necessary to materialize
```

### New Layer: `VendorPackagePlan`

Add an internal layer after `ProcessorTaskPlan` / before `ProgramVendorABI`:

```text
AppPlan
  -> ProcessorLogicalProgram
  -> ProcessorTaskPlan
  -> ProcessorTileProgram
  -> VendorPackagePlan
  -> ProgramVendorABI
  -> ProgramBinRows
```

Proposed shape:

```python
@dataclass(frozen=True)
class VendorRuntimeProfile:
    profile_id: str
    max_runtime_apps_per_package: int
    max_task_rows_per_package: int
    max_subtask_rows_per_task: int
    max_subtask_rows_per_package: int
    supports_single_package_multi_semantic_app: bool
    supports_multi_package_launch: bool
    supports_inter_package_storage_handoff: bool

@dataclass(frozen=True)
class VendorPackageGroup:
    group_id: int
    package_id: str
    semantic_app_ids: tuple[int, ...]
    vendor_task_row_ids: tuple[int, ...]
    vendor_task_group_config_count: int
    task_group_policy: str
    storage_inputs: tuple[str, ...]
    storage_outputs: tuple[str, ...]
    mapping_kind: Literal[
        "single_semantic_app_to_single_package",
        "analysis_only_multi_semantic_app_group",
        "multi_package_launch_step",
    ]
    semantic_mapping_status: Literal[
        "legal",
        "illegal",
        "requires_proof",
    ]
    binary_emission_status: Literal[
        "runnable_single_package",
        "symbolic_only",
        "requires_multi_package_runtime",
        "unsupported_vendor_profile",
    ]

@dataclass(frozen=True)
class VendorPackagePlan:
    runtime_profile: VendorRuntimeProfile
    groups: tuple[VendorPackageGroup, ...]
    package_count: int
    runtime_launch_policy: Literal[
        "single_package",
        "multi_package_sequential",
        "unsupported",
    ]
```

### GEMM Mapping

Current `gemm_template_fusion` should map to:

```text
OpenFabric AppPlan:
  app0: one semantic app containing GEMM(+optional epilogue)

VendorPackagePlan:
  group0:
    semantic_app_ids = (0,)
    vendor_task_row_ids = (0, 1, 2, 3)
    package_id = "package0"
    mapping_kind = "single_semantic_app_to_single_package"
    binary_emission_status = "runnable_single_package"
    runtime_launch_policy = single_package

ProgramBinRows:
  emits one cbuf/micc package
```

This preserves current runnable behavior.

### Log10Max Mapping

For `log10max`, the semantic AppPlan has:

```text
app0: reduce/max and materialize global_max
app1: reload input/global_max and post-process
```

Initial package policy should be:

```text
Option A: symbolic only
  symbolic group0 references app0/app1 only as analysis metadata
  mapping_kind = analysis_only_multi_semantic_app_group
  binary_emission_status = symbolic_only
  ProgramBinRows refuses runnable binary

Option B: future multi-package sequential
  package0: app0 reduce/materialize
  package1: app1 reload/post-process
  RISC-V/runtime control launches package0 then package1
```

Do not map:

```text
app0 -> task0
app1 -> task1
```

inside a single package unless we have a proof that task/subtask sequencing is a
legal app boundary and that required storage handoff is explicit.

For the current DFU3500 SimICT legacy profile:

```text
max_runtime_apps_per_package = 1
supports_single_package_multi_semantic_app = false
supports_multi_package_launch = false
supports_inter_package_storage_handoff = false
```

So `log10max` remains IR/symbolic only for runnable binary purposes.

## Why Not Use Vendor `appN.conf` Directly?

The vendor `appN.conf` files are not reliable semantic app boundaries:

```text
app0.conf/app1.conf/app2.conf/app3.conf in GEMM
  are four parallel task groups / task slots
  not four staged PE-state lifetime boundaries
```

They are closer to a vendor packer input convention:

```text
one or more appN.conf files
  -> one build_app invocation
  -> one combined cbuf/micc package
```

OpenFabric should not make `AppRegion` equal to `appN.conf`.

## Implementation Plan

### Phase 0: Documentation And Dumps

1. Add this RFC.
2. Update dumps to print:

```text
OpenFabric AppRegion count
Vendor task row count
Vendor package count
```

3. Make `ProgramBinRows.to_plan()` state:

```text
package_count = 1
max_app_amount_per_package = 1
```

for current DFU3500 legacy profile.

### Phase 1: Add `VendorPackagePlan` Metadata

Add a metadata-only pass:

```text
ProcessorTileProgram
  -> VendorPackagePlan
```

For current GEMM:

```text
one semantic app
one package
four vendor tasks
```

For `log10max`:

```text
two semantic apps
binary_status = symbolic_only
```

No binary output should change in this phase.

### Phase 2: Gate Runnable Binary

Add validation:

```text
if semantic_app_count > 1 and no proven vendor package/runtime policy:
  ProgramBinRows refuses runnable binary
```

Error message should mention:

```text
OpenFabric AppRegion is a semantic PE-state boundary.
Current DFU3500 package path only supports a proven single-package mapping.
```

### Phase 3: Single-Package Multi-Task Clarification

Rename internal fields where useful:

```text
vendor app config file count
  -> task_group_config_count

Duplicate_Application_Amount
  -> vendor_conf_file_count in notes/dumps
```

Keep exact vendor names in reverse maps and compatibility reports, but avoid
using them as OpenFabric semantic names.

### Phase 3.5: RISC-V Runtime Control Boundary

Add an explicit out-of-scope marker for current `ProgramBinRows`:

```text
ProgramBinRows emits CBUF/MICC package bytes only.
It does not emit RISC-V control flow for:
  - per-app DMA input staging,
  - MICC double-buffer launch sequencing,
  - inst_reload policy,
  - app_num-dependent instance_base switching,
  - inter-package storage handoff.
```

Future runnable multi-semantic-app support requires either:

```text
single-package proof:
  task/subtask order plus explicit storage handoff is enough

or

multi-package proof:
  ProgramRuntimeBundle emits launch sequence and storage handoff
```

### Phase 4: Future Multi-Package Runtime

Only after runtime evidence:

```text
package0 result storage -> package1 input storage
RISC-V control launches package0 then package1
DPU_App_Finish / DPU_Kernel_Start sequencing is deterministic
```

introduce:

```text
ProgramRuntimeBundle:
  packages: tuple[ProgramBinPackageSet, ...]
  launch_sequence: tuple[LaunchStep, ...]
  storage_handoffs: tuple[RuntimeStorageHandoff, ...]
```

This is out of scope for the immediate GEMM binary path.

## Validation Plan

### Positive Tests

```text
test_gemm_app_plan_single_semantic_app
test_gemm_vendor_group_one_package_four_tasks
test_gemm_binary_unchanged_after_vendor_group_metadata
test_program_bin_rows_reports_single_package_capacity
test_gemm_runtime_control_model_is_single_package_repeated_launch
```

### Negative Tests

```text
test_log10max_multi_app_refuses_runnable_bin_without_package_policy
test_reject_cross_app_pe_local_dependency
test_reject_mapping_openfabric_app_region_directly_to_task_id
test_reject_multi_package_without_runtime_launch_policy
test_reject_runnable_multi_semantic_app_current_profile
test_reject_appN_conf_index_as_app_region_id
```

### Vendor Evidence Tests

Use fixture-level checks from the restored vendor flow:

```text
run_mtr.sh app_conf list:
  app0.conf..app3.conf -> one build_app invocation

component package:
  insts + exeblock + instance -> cbuf
  tasks + subtasks -> micc

capacity:
  task rows = 4
  subtask rows = 32
  MAX_APP_AMOUNT = 1

riscv control:
  DPU_CbufTransfer and DPU_MiccTransfer happen before app_num loop
  inst_reload is 1 only for first kernel launch
  later launches keep resident instructions
  instance_base and buf_num vary with app_num
  data movement is explicit DMA to/from SPM/DDR
```

## Expected Effect

This RFC should make the compiler more honest:

```text
GEMM:
  remains one runnable vendor package with four task rows.

log10max:
  remains two semantic apps and symbolic/tile-lowerable,
  but cannot accidentally enter a fake runnable binary path.

future softmax/layernorm:
  can use AppPlan for staged semantics,
  but must choose explicit materialize/recompute/package policy.
```

The concrete design effect we want is:

```text
1. Compiler semantics stay above vendor naming accidents.
2. Binary generation remains a package serializer, not a hidden runtime scheduler.
3. Any cross-AppRegion value transfer becomes visible as storage handoff.
4. RISC-V control requirements become explicit before we claim runnable binary.
5. Current GEMM remains byte-stable and keeps using one resident package with
   four vendor task rows.
```

The key benefit is preventing a tempting but wrong shortcut:

```text
OpenFabric app0/app1
  -> vendor task0/task1
```

without proving that task boundaries provide app lifetime semantics.

## Open Questions

1. Does the real DFU3500 runtime support more than one `MAX_APP_AMOUNT` in a
   different profile, or is `MAX_APP_AMOUNT=1` fixed for SimICT?
2. Can RISC-V control code safely launch multiple packages sequentially from one
   `config/` directory, or would it require a new file layout?
3. Is there a vendor example where `app0.conf` and `app1.conf` represent staged
   semantics rather than parallel task-group slots?
4. For reduce+elementwise operators, can a single vendor package legally express
   the storage handoff using subtask sequencing, or must it be separate packages?
5. Should OpenFabric eventually generate vendor-style `appN.conf` as an
   intermediate debug artifact, or continue generating `ProgramVendorABI` rows
   directly?

## Recommended Near-Term Decision

Accept the following policy:

```text
Current runnable DFU3500 path:
  supports one OpenFabric semantic app per package.

Vendor appN.conf:
  is treated as task-group config input, not semantic AppRegion.

Multi-App OpenFabric programs:
  are allowed in AppPlan / TileProgram as IR,
  but ProgramBinRows must refuse runnable binary until a
  VendorPackagePlan or ProgramRuntimeBundle proves a legal package/launch mapping.
```

This keeps GEMM moving while protecting the newer App/Fusion/Task semantics from
being crushed into vendor naming accidents.
