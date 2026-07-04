# AppPlan vs Runtime Image Boundary

## Status

Accepted working note for the DFU-first compiler pipeline.

## Summary

OpenFabric compile-time apps and DFU runtime images are different concepts.

```text
Compile-time AppPlan app
  = semantic PE-state lifetime boundary
  = independent app-local op list
  = no implicit PE-local value sharing with other apps

Runtime image / package
  = final CBUF/MICC emission unit
  = may pack one or more compile-time apps if hardware/runtime proof exists
  = owns task/subtask/instance/image-space allocation
```

The compiler must first lower independent app-local programs.  Later packaging
passes may merge apps into one runtime image, split them across multiple images,
or reject a mapping if the target runtime cannot prove launch and storage handoff
semantics.

## Vendor Evidence

The current DFU3500 SimICT flow uses several vendor names that look like
"apps", but they do not directly mean OpenFabric semantic apps.

Observed in the customer toolchain:

```text
run_mtr.sh
  -> passes app0.conf/app1.conf/... to build_app

build_app/main.cpp
  -> reads each app*.conf as a Task_Group
  -> maps all Task_Group objects through one INST_BLK_MAP
  -> prints one simulator_bin set

run_mtr.sh
  -> concatenates simulator_bin components into one result/cbuf_file.bin
  -> concatenates simulator_bin MICC rows into one result/micc_file.bin
```

The runtime headers also define:

```text
MAX_APP_AMOUNT = 1
MAX_CUR_TASK_CONF_PER_APP = 4
MAX_SUBTASK_PER_TASK = 8
```

So, in the current profile, vendor `appN.conf` is best treated as a task-group
configuration input.  It is not proof that the runtime supports multiple
OpenFabric semantic apps inside one image.

## Compiler Policy

The pipeline should keep this shape:

```text
ChipProgram
  -> AppPlan
  -> ProcessorLogicalProgram(app-local programs)
  -> ProcessorTileProgram(app-local/tile programs)
  -> RuntimeImagePlan / RuntimePackageAssignment
  -> ProgramVendorABI
  -> ProgramBinRows / Serializer
```

Rules:

1. `AppPlan` partitions chip-level ops and inserts explicit boundary ops.
2. `ProcessorLogicalProgram` consumes `AppPlan.apps`; it must not reconstruct a
   single global op stream from the original chip program.
3. Cross-app communication is represented by flat ops such as
   `app_materialize_store` and `app_materialize_load`.
4. PE-local tile/register/accumulator state cannot cross an app boundary.
5. Runtime image packing is a later pass.  It allocates task/subtask/instance
   rows and CBUF/MICC image regions after app-local lowering is already clear.
6. Vendor task rows are app-local work slots, not semantic app boundaries.

## Current Implementation Notes

`AppPlan` currently uses a conservative split policy:

```text
ordinary ops append to the current app
collective ops close the current app
tile-local lineage is recomputed in the next app by default
collective scalar outputs are materialized through synthetic flat ops
```

This is intentionally simple.  A future cost policy can choose to materialize
selected tile intermediates instead of recomputing them, but that should still
be expressed as explicit flat ops rather than side-table edges.

## Non-goals

This note does not prove multi-image runtime launch, inter-image storage handoff,
or single-image multi-semantic-app execution.  Those are RuntimeImagePlan /
RuntimePackageAssignment responsibilities, not AppPlan or ProcessorLogicalProgram
responsibilities.
