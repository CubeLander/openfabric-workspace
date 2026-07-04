# common_oper Source Fingerprint Index

Date: 2026-06-20

Status: vendor evidence index, not OpenFabric design truth

This page indexes vendor-source fingerprints, file roles, and must-read entry
points distilled from the 2026-06-20 binary audit notes.

Important boundary:

```text
These fingerprints are vendor evidence.
They prove what the audited vendor snapshot appears to do.
They are not, by themselves, the OpenFabric compiler architecture.
```

OpenFabric should consume this evidence through typed owners such as
`TaskControlPlan`, `InstructionLayoutPlan`, `RouteEndpointPlan`,
`ResourceCapacityPlan`, `VendorComponentPlan`, and DFU3500 profile data.  Do not
copy vendor control flow into frontend IR or op-time lowering as a shortcut.

## Source Roots

Audited `common_oper` source root:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/common_oper
```

Audited clean common-header root:

```text
simict3500final/gpdpu/users/risc_nn_riscv/common/src
```

Notes warn that local source may differ from the remote arch-13/runtime build.
Use the hashes below as snapshot evidence and keep binary/runtime validation when
field layout, capacity, or exact emitted bytes are payload-critical.

## Fingerprint Matrix

### Clean Common Headers

| SHA-256 | File | Evidence role |
| --- | --- | --- |
| `b263f25e62403d4f1e365aafcec046e76c0c0030f1b6590ac4fb0d90aaa04a4a` | `common/src/inst_def.h` | `inst_t` simulator instruction row layout; local `sizeof(inst_t) = 304`. |
| `2d06ba8afb6f84cc50d120f3a9c6e3612d0b3fe2f48f42349ff27b211099bcae` | `common/src/pe_com_def.h` | PE array shape and fixed per-PE instruction/exeBlock capacity constants. |
| `42bd0593d6dfc4b7e361c49d8191049addb2f851162bccec66575b36fe31fa8b` | `common/src/dma_com_def.h` | Clean DMA-side struct evidence included in layout audit scope. |
| `a336aca7dec1f40a666f1ef45affb5048e3dcf3e79bb155663faef8c8f1218b7` | `common/src/basic_def.h` | Component filenames, task/subtask/instance capacities, auxiliary file names. |

Prefer `common/src` over OCR headers under `common/src_ocr` for binary interface
work unless a remote arch-13 mismatch is proven.

### `common_oper` Implementation Files

| SHA-256 | File | Evidence role |
| --- | --- | --- |
| `31a4ba6f4b9201a2a282b889b5cf4f7c95797342fc55806dc2931224d9968ca5` | `task_create.cpp` | Strict app/task/subtask grammar; task/subtask construction; map flow entry. |
| `cd5a2196700c9b0bb52e566de02864829af98171d8f109f89c25940763bfea22` | `graph_extend.cpp` | Graph relationships and COPY-like edge ownership between parent/child nodes. |
| `4457bd232c4da6237bd60ffd90fc038e706df1b0fd3ac1769c84cf0ad06cc6c7` | `inst_blk_gen.cpp` | CSV/template instruction rows split into fixed LD/CAL/FLOW/ST stage order. |
| `bdc8a311d801be6501f88c4de1af757f699aeae2a97dcd04334213dd42561eaa` | `exe_block_gen.cpp` | PE-local exeBlock index assignment, predecessor/successor metadata, stage PCs. |
| `d9c1af31a926e3f960706827f0bd15df7676656f2b491325f226637b48a1bef2` | `task_print.cpp` | MICC/CBUF/component writers; padding; task/subtask/exeBlock stamps; RTL/debug projections; enable/sidecar files. |
| `229af09d1eaf831bbd6deb44c35ec74a1c43019f877f32c42c568d08059069fa` | `common_app_build.cpp` | Utility glue for app build setup; not the core binary writer. |
| `bc91510345ee8473e065ee6449c8a776ef1c120469ae5a75ae10d9a20c4d401b` | `csv2bin.cpp` | Stub in audited snapshot; do not treat as the source of CSV-to-binary behavior. |
| `58fa864f09b8be1b163a4bf90e33a4d426ca32bb3755b4f1224fd0d1e8819b26` | `csv2bin.h` | Header counterpart for the stubbed CSV-to-binary helper snapshot. |
| `44a469f28bf92a7c79beedbd98611bd83828e82058d0a2a5b0e182b6e3254624` | `inst_blk_map.cpp` | Task resource windows; operand allocation; COPY/COPYT destination patching; app resource maxima. |

### Related Scripts And Runtime Docs

These entries are named evidence but were not fingerprinted in the audited notes:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/workflow/scripts/build_package.sh
simict3500final/gpdpu/users/risc_nn_riscv/test/README.md
compiler/gpdpu_compiler/validation/dfu3500_partner_validation/validate_on_arch13.sh
```

They support packaging/staging behavior for sidecar files such as
`data_inst_replace.bin`, but source-level runtime consumption was not proven in
the local tree.

## File Role Map

| Vendor area | Read first | What it can safely prove | What it must not be overused for |
| --- | --- | --- | --- |
| Struct layout and capacities | `common/src/*.h` via `2026-06-20_vendor_struct_layout_audit.md` | Row sizes, task/subtask/instance limits, fixed component capacity formulas. | Frontend IR shape or multi-chip abstraction. |
| Task and subtask declaration | `task_create.cpp` via common task/graph audit | Strict nested grammar and active task/subtask construction order. | Runtime task count from auxiliary enable files. |
| Template stage layout | `inst_blk_gen.cpp` and `exe_block_gen.cpp` via common task/graph audit | LD/CAL/FLOW/ST stage partitioning, PE-local block PCs, predecessor/successor rows. | Op-time direct PE program mutation. |
| Graph edge and route ownership | `graph_extend.cpp`, `inst_blk_map.cpp`, `inst_map_common.*` docs | COPY/COPYT edge ownership and receiver-owned destination operand patching. | Treating sender-local operands as final route destinations. |
| Resource allocation | `inst_blk_map.cpp` via resource-owner audit | Task resource windows, PE-local operand/block allocation, app resource maxima. | Replacing serializer capacity checks with ad-hoc action counts. |
| Component writing | `task_print.cpp` via writer audit | Per-PE instruction streams, late task/subtask stamps, padded component files. | Inferring simulator ABI from RTL/debug projection alone. |
| Auxiliary sidecars | `basic_def.h`, `task_print.cpp`, package scripts via sidecar audit | Names and current local writer behavior for `data_inst_replace.bin`, `instEnable.bin`, `taskEnable.bin`. | Deriving MICC active tasks, runtime task count, or data patch semantics without runtime consumer evidence. |

## Must-Read Audit Notes

Use these notes as the current entrance map before changing CBUF/MICC, task
control, route binding, resource planning, or vendor packaging:

| Question | Entry note | Why |
| --- | --- | --- |
| What are the row layouts and capacity constants? | [`2026-06-20_vendor_struct_layout_audit.md`](../../compiler/binary_packaging/research_notes/binary/2026-06-20_vendor_struct_layout_audit.md) | Starts from clean `common/src` headers and records component size formulas. |
| How does vendor graph/task/exeBlock metadata get created? | [`2026-06-20_common_oper_task_graph_exeblock_audit.md`](../../compiler/binary_packaging/research_notes/binary/2026-06-20_common_oper_task_graph_exeblock_audit.md) | Covers task config parsing, CSV template loading, case `generateGraph`, graph edges, exeBlock stage PCs, and padding. |
| Who owns operands, route destinations, and resource counts? | [`2026-06-20_inst_blk_map_resource_owner_audit.md`](../../compiler/binary_packaging/research_notes/binary/2026-06-20_inst_blk_map_resource_owner_audit.md) | Explains task resource windows, COPY destination patching from child/receiver state, and app maxima. |
| How are MICC/CBUF component files written? | [`2026-06-20_task_print_component_writer_audit.md`](../../compiler/binary_packaging/research_notes/binary/2026-06-20_task_print_component_writer_audit.md) | Explains per-PE streams, late stamps, fixed padding, and simulator-vs-RTL projection boundaries. |
| What are `data_inst_replace.bin` and enable files? | [`2026-06-20_data_inst_replace_and_enable_files_audit.md`](../../compiler/binary_packaging/research_notes/binary/2026-06-20_data_inst_replace_and_enable_files_audit.md) | Keeps auxiliary sidecars conservative and prevents over-interpreting runtime semantics. |

Related polished docs in this subtree:

- [`csv-to-binary-pipeline.md`](csv-to-binary-pipeline.md)
- [`task-creation-generategraph-chain.md`](task-creation-generategraph-chain.md)
- [`subtask-graph-compile-chain.md`](subtask-graph-compile-chain.md)
- [`binary-artifact-generation-pipeline.md`](binary-artifact-generation-pipeline.md)
- [`operand-resource-and-route-audit.md`](operand-resource-and-route-audit.md)
- [`dfu3500-hardware-constraints-from-vendor-algorithms.md`](dfu3500-hardware-constraints-from-vendor-algorithms.md)
- [`dfu3500-gemm-binary-replay.md`](dfu3500-gemm-binary-replay.md)

## Evidence Boundaries For OpenFabric

Carry these constraints forward when promoting vendor facts into compiler code:

```text
Vendor source fingerprint:
  identifies the audited vendor snapshot.

Vendor file role:
  explains which behavior that file can support as evidence.

OpenFabric owner:
  typed plan/pass/verifier/profile that consumes the evidence.

Runtime/binary validation:
  proves exact payload behavior for the target arch/server build.
```

If one slot is missing, document the gap.  Do not let a vendor filename, debug
projection, or local snapshot hash silently become an OpenFabric design invariant.
