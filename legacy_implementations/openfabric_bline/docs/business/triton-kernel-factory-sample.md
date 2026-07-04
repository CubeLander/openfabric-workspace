# Triton Kernel Factory Sample

Date: 2026-06-23

## The Key Reconciliation

OpenFabric's tile program should not be printed directly as Triton syntax.

The missing bridge is:

```text
ProcessorTileProgram
  -> TritonBlockProgram
  -> TritonTemplateExpansion
  -> .py kernel + wrapper + tests + benchmark
```

`ProcessorTileProgram` owns semantic tile actions:

```text
load / route visibility
compute gemm_tile
compute relu / bias
store
dependency order
```

Triton owns a different physical vocabulary:

```text
program_id
block offsets
pointer arithmetic
tl.load / tl.store masks
tl.dot
tl.constexpr meta-parameters
launch grid
num_warps / num_stages
```

So the correct move is not:

```text
TileRouteAction -> emit "route" in Triton
```

The correct move is:

```text
TileRouteAction(A/B visible)
  -> generate block pointer expressions and masks

TileComputeAction(gemm_tile)
  -> generate accumulator loop and tl.dot

TileComputeAction(relu / bias)
  -> generate fused accumulator epilogue

TileStoreAction(C)
  -> generate output pointer expressions and tl.store mask
```

## Example Source Tile Plan

This is the kind of OpenFabric-side plan we want to consume:

```python
tile_program = {
    "op_chain": [
        {
            "kind": "load",
            "sources": ["A[M,K]", "B[K,N]"],
            "visibility": "block_local",
        },
        {
            "kind": "compute",
            "op": "gemm_tile",
            "accumulator_dtype": "fp32",
        },
        {
            "kind": "compute",
            "op": "bias_add",
            "axis": "N",
        },
        {
            "kind": "compute",
            "op": "relu",
        },
        {
            "kind": "store",
            "target": "C[M,N]",
            "dtype": "fp16",
        },
    ],
    "tile_shape": {
        "BLOCK_M": 64,
        "BLOCK_N": 64,
        "BLOCK_K": 32,
    },
    "launch_order": {
        "kind": "grouped_m",
        "GROUP_M": 4,
    },
}
```

That plan is still too abstract for Triton. It needs to become a GPU block program.

## Lowered TritonBlockProgram

This is the bridge object:

```python
triton_block_program = {
    "program_axes": ["m_block", "n_block"],
    "grid": "ceil_div(M, BLOCK_M) * ceil_div(N, BLOCK_N)",
    "pid_mapping": {
        "kind": "grouped_m",
        "group_size_m": "GROUP_M",
    },
    "block_indices": {
        "m": "pid_m * BLOCK_M + arange(BLOCK_M)",
        "n": "pid_n * BLOCK_N + arange(BLOCK_N)",
        "k": "arange(BLOCK_K)",
    },
    "loads": [
        {
            "name": "a",
            "ptr_expr": "A + m[:,None] * stride_am + k[None,:] * stride_ak",
            "mask": "k[None,:] < K - k0",
            "other": 0.0,
        },
        {
            "name": "b",
            "ptr_expr": "B + k[:,None] * stride_bk + n[None,:] * stride_bn",
            "mask": "k[:,None] < K - k0",
            "other": 0.0,
        },
    ],
    "loop": {
        "axis": "K",
        "step": "BLOCK_K",
        "body": "acc = dot(load(a), load(b), acc)",
    },
    "epilogue": [
        "acc += bias[n][None, :]",
        "acc = maximum(acc, 0.0)",
        "c = acc.to(float16)",
    ],
    "store": {
        "ptr_expr": "C + m[:,None] * stride_cm + n[None,:] * stride_cn",
        "mask": "(m[:,None] < M) & (n[None,:] < N)",
    },
    "meta": {
        "BLOCK_M": 64,
        "BLOCK_N": 64,
        "BLOCK_K": 32,
        "GROUP_M": 4,
        "num_warps": 4,
        "num_stages": 4,
    },
}
```

This object is close enough to Triton that code generation becomes boring template
work instead of architecture magic.

## Generated Triton Kernel

The following is the kind of output the factory should generate for a fixed
`gemm + bias + relu` family.

```python
import torch
import triton
import triton.language as tl


@triton.jit
def _of_gemm_bias_relu_kernel(
    a_ptr,
    b_ptr,
    bias_ptr,
    c_ptr,
    M: tl.constexpr,
    N: tl.constexpr,
    K: tl.constexpr,
    stride_am: tl.constexpr,
    stride_ak: tl.constexpr,
    stride_bk: tl.constexpr,
    stride_bn: tl.constexpr,
    stride_cm: tl.constexpr,
    stride_cn: tl.constexpr,
    BLOCK_M: tl.constexpr,
    BLOCK_N: tl.constexpr,
    BLOCK_K: tl.constexpr,
    GROUP_M: tl.constexpr,
):
    pid = tl.program_id(axis=0)

    num_pid_m = tl.cdiv(M, BLOCK_M)
    num_pid_n = tl.cdiv(N, BLOCK_N)
    num_pid_in_group = GROUP_M * num_pid_n

    group_id = pid // num_pid_in_group
    first_pid_m = group_id * GROUP_M
    group_size_m = tl.minimum(num_pid_m - first_pid_m, GROUP_M)

    pid_m = first_pid_m + ((pid % num_pid_in_group) % group_size_m)
    pid_n = (pid % num_pid_in_group) // group_size_m

    offs_m = pid_m * BLOCK_M + tl.arange(0, BLOCK_M)
    offs_n = pid_n * BLOCK_N + tl.arange(0, BLOCK_N)
    offs_k = tl.arange(0, BLOCK_K)

    a_ptrs = a_ptr + offs_m[:, None] * stride_am + offs_k[None, :] * stride_ak
    b_ptrs = b_ptr + offs_k[:, None] * stride_bk + offs_n[None, :] * stride_bn

    acc = tl.zeros((BLOCK_M, BLOCK_N), dtype=tl.float32)

    for k0 in range(0, K, BLOCK_K):
        a = tl.load(a_ptrs, mask=(offs_k[None, :] + k0) < K, other=0.0)
        b = tl.load(b_ptrs, mask=(offs_k[:, None] + k0) < K, other=0.0)
        acc = tl.dot(a, b, acc)
        a_ptrs += BLOCK_K * stride_ak
        b_ptrs += BLOCK_K * stride_bk

    bias = tl.load(bias_ptr + offs_n, mask=offs_n < N, other=0.0)
    acc = acc + bias[None, :]
    acc = tl.maximum(acc, 0.0)
    out = acc.to(tl.float16)

    c_ptrs = c_ptr + offs_m[:, None] * stride_cm + offs_n[None, :] * stride_cn
    c_mask = (offs_m[:, None] < M) & (offs_n[None, :] < N)
    tl.store(c_ptrs, out, mask=c_mask)


def of_gemm_bias_relu(a: torch.Tensor, b: torch.Tensor, bias: torch.Tensor) -> torch.Tensor:
    assert a.is_cuda and b.is_cuda and bias.is_cuda
    assert a.dtype == torch.float16
    assert b.dtype == torch.float16
    assert bias.dtype == torch.float16
    assert a.ndim == 2 and b.ndim == 2 and bias.ndim == 1
    assert a.shape[1] == b.shape[0]
    assert bias.shape[0] == b.shape[1]
    assert a.is_contiguous()
    assert b.is_contiguous()

    M, K = a.shape
    _, N = b.shape
    c = torch.empty((M, N), device=a.device, dtype=torch.float16)

    block_m = 64
    block_n = 64
    block_k = 32
    group_m = 4

    grid = (triton.cdiv(M, block_m) * triton.cdiv(N, block_n),)

    _of_gemm_bias_relu_kernel[grid](
        a,
        b,
        bias,
        c,
        M,
        N,
        K,
        a.stride(0),
        a.stride(1),
        b.stride(0),
        b.stride(1),
        c.stride(0),
        c.stride(1),
        BLOCK_M=block_m,
        BLOCK_N=block_n,
        BLOCK_K=block_k,
        GROUP_M=group_m,
        num_warps=4,
        num_stages=4,
    )
    return c
```

## Why This Is Not Hand-Waving

Triton already uses one program instance per output block for blocked matmul. Its
official matmul tutorial describes the same shape:

```text
one Triton program instance computes one [BLOCK_M, BLOCK_N] output block
```

OpenFabric's tile is therefore not alien to Triton. The mismatch is mostly naming:

| OpenFabric concept | Triton concept |
| --- | --- |
| tile id | `tl.program_id` mapped to block coordinates |
| tile shape | `BLOCK_M`, `BLOCK_N`, `BLOCK_K` meta-parameters |
| route / visibility | pointer expressions, masks, cache behavior |
| tile local accumulator | `tl.zeros((BLOCK_M, BLOCK_N), dtype=tl.float32)` |
| gemm tile action | `tl.dot(a, b, acc)` |
| op-chain epilogue | fused accumulator transforms before store |
| store action | `tl.store` with boundary mask |
| physical descriptor | launch grid, block sizes, warps, stages, layout assumptions |
| resource checker | static constraints plus generated correctness/benchmark tests |

## Factory Output Shape

For a real customer, the factory should not only emit the kernel. It should emit:

```text
kernel.py
wrapper.py
test_correctness.py
benchmark.py
autotune_configs.py
report.md
```

The report should include:

```text
source op-chain
generated TritonBlockProgram
candidate tile shapes
correctness tolerance
latency results
baseline comparison
known shape/layout assumptions
fallback path
```

## Minimum Confidence PoC

A good two-week PoC is:

```text
1. Take gemm + bias + relu for fixed shapes.
2. Generate 8-16 Triton tile configs.
3. Run correctness against torch reference.
4. Benchmark against torch.compile / eager baseline.
5. Emit a report with the winning config.
```

This proves the bridge without pretending we solved arbitrary Triton generation.

## Sources

- Triton repository: https://github.com/triton-lang/triton
- Triton matmul tutorial: https://triton-lang.org/main/getting-started/tutorials/03-matrix-multiplication.html
- Triton language API: https://triton-lang.org/main/python-api/triton.language.html
- PyTorch user-defined Triton kernel tutorial: https://docs.pytorch.org/tutorials/recipes/torch_compile_user_defined_triton_kernel_tutorial.html
