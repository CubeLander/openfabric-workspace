# Vendor Workflow Evidence

This directory keeps useful evidence extracted from the old `testcase/workflow`
cleanup path. Treat these notes as investigation material, not as an active
build route.

Current active work should start from:

```text
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/softmax_1
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_template_fusion
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/softmax_refactored
simict3500final/gpdpu/users/risc_nn_riscv/testcase/application/gemm_refactored
tools/vendor_case/
```

The old direct workflow scripts and generated output directories were removed
from the active `testcase/` tree. The notes here preserve hardware, operand,
CSV, COPYT, and runtime-package observations that are still useful when
checking or extending the current CMake/refactored-replay path.
