# CMake Build And Replay Targets

OpenFabric's active DFU3500 work has a CMake shadow build rooted at the
repository root. This build is the source of truth for editor compile commands,
host-side syntax checks, lowering bundles, customer delivery packages, and
operator-owned approved snapshot checks.

Configure from the repository root:

```sh
cmake -S . -B build -DCMAKE_EXPORT_COMPILE_COMMANDS=ON
```

Build the syntax/analysis targets:

```sh
cmake --build build --target softmax_refactored_syntax
cmake --build build --target gemm_refactored_syntax
cmake --build build --target gemm_relu_refactored_syntax
cmake --build build --target log10max_refactored_syntax
```

Build the customer package and approved snapshot targets:

```sh
cmake --build build --target log10max_delivery_package
cmake --build build --target log10max_approved_snapshot_test
```

`build/compile_commands.json` is generated locally and must not be committed.
The root `.clangd` points clangd at `build`, so VS Code and other clangd clients
should use the CMake-generated database after configuration.

The first-stage targets are intentionally analysis/object targets:

- `softmax_refactored_device_program_analysis`
- `softmax_refactored_runtime_plan_riscv_program_analysis`
- `gemm_refactored_device_program_analysis`
- `gemm_refactored_runtime_plan_riscv_program_analysis`
- `openfabric_graph_trace_compat_hook_analysis`

The default RISC-V analysis target builds the common RuntimePlanImage executor
with a CMake-generated embedded image. The old generated-header RISC-V trace
targets have been retired for the refactored GEMM/softmax cases; RuntimePlanImage
API trace gates are the active compatibility check. Graph-trace analysis targets
use build-local compatibility headers where needed, instead of creating
generated vendor directories in the source tree. This keeps the syntax target
and `compile_commands.json` compiler-neutral across GCC, Clang, and clangd.

The old checked-in vendor-baseline replay targets have been retired together
with the repo-local SimICT vendor package. For refactored cases that use the
common RuntimePlanImage RISC-V executor, runtime-control equivalence is checked
by API trace gates in the syntax/analysis targets. Customer-locking should use
operator-owned approved snapshots and customer-side runs.
