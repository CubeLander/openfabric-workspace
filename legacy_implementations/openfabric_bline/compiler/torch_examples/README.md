# Compiler Examples

这里放 DFU Tiny Distributed Tensor Compiler 的前端示例。当前示例先用
PyTorch `torch.distributed` / DTensor 的语言描述 4x4 PE mesh 上的 GEMM，不直接生成 DFU
runtime package。

## GEMM On 4x4 Mesh

```bash
python3 compiler/examples/gemm_4x4_dtensor.py --dry-run
```

如果本机安装了 PyTorch，并且支持 `torch.distributed.tensor`，可以用 16 个进程运行：

```bash
torchrun --nnodes=1 --nproc_per_node=16 \
  --master_addr=127.0.0.1 --master_port=29501 \
  -- compiler/examples/gemm_4x4_dtensor.py --backend gloo
```

如果 `torchrun` 不在 `PATH` 中，也可以用：

```bash
python3 -m torch.distributed.run --nnodes=1 --nproc_per_node=16 \
  --master_addr=127.0.0.1 --master_port=29501 \
  -- compiler/examples/gemm_4x4_dtensor.py --backend gloo
```

在 macOS 上，显式指定 `127.0.0.1` 比 `--standalone` 更稳定。

这个例子表达的策略是：

```text
DeviceMesh:
  4x4 ranks, named ("row", "col")

A[M, K]:
  placements = [Shard(0), Replicate()]
  M 维沿 mesh row 切分，沿 mesh col 复制/广播。

B[K, N]:
  placements = [Replicate(), Shard(1)]
  N 维沿 mesh col 切分，沿 mesh row 复制/本地可见。

C[M, N] = A @ B:
  placements = [Shard(0), Shard(1)]
  每个 rank/PE 拥有唯一 C shard，不产生 Partial，不需要 all_reduce。
```

这正是我们希望后续 lowering 到 DFU 的第一版策略：

```text
Shard / Replicate / Partial / collective
  -> PE-local tile stream
  -> task/subtask/instance
  -> COPYT + PE-local HMMAL template
```

## Signal Fusion: log10 + max + maximum

```bash
python3 compiler/examples/log10_maximum_dtensor.py --dry-run
```

真实 16 rank 运行：

```bash
python3 -m torch.distributed.run --nnodes=1 --nproc_per_node=16 \
  --master_addr=127.0.0.1 --master_port=29502 \
  -- compiler/examples/log10_maximum_dtensor.py --backend gloo
```

这个例子来自 Qwen3-ASR mel spectrogram preprocessing:

```python
log_spec = torch.clamp(mel_spec, min=1e-10).log10()
log_spec = torch.maximum(log_spec, log_spec.max() - 8.0)
log_spec = (log_spec + 4.0) / 4.0
```

分布式语义：

```text
mel_spec[mel_bins, frames]:
  placements = [Shard(0), Shard(1)]

clamp/log10:
  PE-local elementwise

max:
  PE-local max + all_reduce(MAX)

maximum/scale:
  PE-local elementwise using replicated global threshold
```

这说明 fusion lowering 需要识别 collective boundary：

```text
local elementwise ops before max
  -> fuse into pre-reduce PE-local program

global max
  -> collective / reduce subtask

local elementwise ops after max
  -> fuse into the next ordinary PE-local program after the reduce barrier
```
