# B-line 三算子交接报告

日期：2026-06-22

当前 HEAD：

```text
e63ff0b Materialize B-line legacy inst_t rows
```

前序关键提交：

```text
9321f3b Narrow PE00 scalar proof contracts
1b460e8 Advance B-line fiber template lowering
f207555 checkpoint b-line three operator upload bundle
```

本报告覆盖当前 B-line 主线进度。旧的 A-line operand allocation 交接内容已经过期。

## 总体结论

B-line 现在已经从“能不能表达三个算子”推进到“把 raw bytes 接到 runtime_ready/package”。

核心架构边界已经守住：

```text
Fiber 是 flat PE-local atomic tile job sequence
GEMM 在 Fiber 层是原子 gemm_tile
ReLU 是独立 relu_tile，不是 GEMM epilogue
log10max 的 global_max_tile 是独立通信 FiberOp
Template/physical lowering 可以展开 rows，但必须保留 primary FiberOp provenance
bundle 不进入 Fiber/Template 语义，只保留 package/customer 语境
runtime_ready / uploadable 不能虚报
```

## 三算子状态

| Operator | 当前状态 | 还差什么 |
|---|---|---|
| GEMM no-ReLU | raw `inst_t` rows/hash 已 materialized；runtime pre-gate 里是 `ready` | component assembly 从 shell/debug 走到真实 runtime_ready/uploadable |
| GEMM+ReLU | `gemm_tile -> relu_tile -> store_tile` 已闭合；ReLU 是独立 FiberOp；layout 可分配 HMAX row slot | HMAX/ReLU-specific selector、zero constant、operand/local_order、raw bytes/hash |
| log10max | local ops 已 production-mapped；PE00/global scalar contract 和 proof plans 已结构化 | PE00 FMAX combine / scalar store / consumer readback raw rows，runtime order proof，receiver roundtrip |

## GEMM no-ReLU

当前 GEMM Fiber 主线：

```text
gemm_tile -> store_tile
```

raw bytes materializer 已闭合：

```text
raw_inst_t_row_count = 36864
raw_inst_t_byte_count = 11206656

compute_core:gemm_tile = 32768 rows / 9961472 bytes
tile_store = 4096 rows / 1245184 bytes

byte_materializer_status = raw_inst_t_row_bytes_available
```

selector policy：

```text
GEMM_TILE_HMMAL_LOCAL_ORDER_SPAN_SELECTOR_V1
  每个 gemm_tile 选择 512 条 HMMAL local_orders
  64 个 gemm_tile 共 32768 条 selected legacy rows

STORE_TILE_STD_OUTPUT_LOCAL_ORDER_SELECTOR_V1
  每个 store_tile 选择 64 条 STD local_orders
  64 个 store_tile 共 4096 条 selected legacy rows
```

注意：`raw_template_row_sha256` 来自 `pack_legacy_inst()` 产出的 raw bytes，不是 span metadata hash。

下一步：

```text
GEMM component assembly
manifest/hash/runtime assets
local runtime_ready gate
uploadable candidate
```

## GEMM+ReLU

当前 ReLU 语义已经修正为显式 tile op-chain：

```text
gemm_tile -> relu_tile -> store_tile
```

当前状态：

```text
relu_tile is independent FiberOp
dfu3500_semantics_relu_tile = closed/proven local elementwise tile op
layout can allocate 64 HMAX row slots
runtime_ready = false
```

当前 focused check 看到：

```text
opcode_counts={'GEMM_TILE_TEMPLATE_SPAN': 64, 'HMAX': 64, 'STD': 64}
subtask4_relu_candidate: 64
```

ReLU 精确证据结论：

```text
legacy GEMM CSV:
  IMM rows = 128
  HMAX rows = 0
  FMAX rows = 0

functional maximum probe:
  IMM + FMAX exists, but it is fp32 maximum_scalar evidence

GEMM+ReLU:
  current dtype selects HMAX
  blocked_missing_hmax_or_relu_specific_selector = 64
```

不能用 fp32 `IMM+FMAX` probe 冒充当前 GEMM+ReLU 需要的 HMAX 证据。

下一步：

```text
ReLU HMAX selector / evidence path
IMM-zero or zero operand policy
HMAX operand indexes / local_order
raw inst_t row bytes
raw_template_row_sha256
```

## log10max

当前 Fiber chain：

```text
clamp_min_tile
-> log10_tile
-> local_reduce_max_tile
-> global_max_tile
-> max_with_floor_tile
-> affine_scale_tile
-> store_tile
```

local ops 已 production-mapped：

```text
clamp_min_tile        -> tile_op:clamp_min
log10_tile            -> tile_op:log10
local_reduce_max_tile -> tile_reduce:local_reduce_max
max_with_floor_tile   -> tile_op:max_with_floor
affine_scale_tile     -> tile_op:affine_scale
```

通信策略：

```text
selected_delivery_strategy = pe00_aggregate_materialize
customer_label = pe00_materialized_scalar
physical_route_allreduce = false
runtime_ready = false
row_bytes_claim = false
```

PE00 proof contract 已经结构化：

```text
producer_pe00_physical_store_row_bytes_missing
pe00_fmax_combine_order_row_bytes_missing
consumer_physical_readback_row_bytes_missing
runtime_subtask_order_proof_missing
receiver_global_scalar_binding_proof_missing
```

已有 proof plan：

```text
row_byte_proof_plan
runtime_order_proof_plan
receiver_binding_proof_plan
vendor_row_lowering_intent
micc_lowering_intent
```

下一步：

```text
PE00 FMAX combine selected rows / raw bytes
PE00 scalar store selected rows / raw bytes
consumer readback selected rows / raw bytes
decoded MICC order proof
runtime trace artifact
receiver operand roundtrip
```

## runtime_ready / package gate

新增最小预集成 gate：

```text
compiler/tools/check_bline_runtime_ready_preintegration.py
```

当前 gate 结论：

```text
final_state=blocked
runtime_ready=False
uploadable=False
operator_states={'gemm_no_relu': 'ready', 'gemm_relu': 'blocked', 'log10max': 'blocked'}
operator_missing_counts={'gemm_no_relu': 0, 'gemm_relu': 5, 'log10max': 46}
```

这说明：

```text
GEMM no-ReLU 已经达到 raw-byte ready 层
GEMM+ReLU 和 log10max 仍 fail-closed
整体 package/runtime_ready 仍 blocked
```

不要因为 package shell 或 debug writer 存在就标 uploadable。

## 已通过的 focused checks

建议接手后先跑：

```bash
cd /home/flecther/workspace/dpu_project

PYTHONPATH=compiler:compiler/tools python compiler/tools/check_bline_runtime_ready_preintegration.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_operator_payload_assembly.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_no_relu_safe_subset.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_relu_fiber_chain.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_relu_binding.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_collective.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_templates.py
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_stream_compiler_log10max_fiber_chain.py
```

最近一次回收里这些 focused checks 均通过。

## 关键文件

架构与交接：

```text
AGENTS.md
notes/aggressive/bline_fiber_template_gap_table_2026_06_22.md
notes/aggressive/bline_three_operator_lowering_map_2026_06_22.md
notes/aggressive/bline_native_lowering_replan_2026_06_22.md
notes/aggressive/bline_fiber_op_chain_audit_2026_06_22.md
```

Fiber / template 主线：

```text
compiler/gpdpu_compiler/core/stream_compiler/fiber.py
compiler/gpdpu_compiler/core/stream_compiler/executable.py
compiler/gpdpu_compiler/core/stream_compiler/template_ops.py
compiler/gpdpu_compiler/core/stream_compiler/template_records.py
compiler/gpdpu_compiler/core/stream_compiler/dfu3500_semantics.py
compiler/gpdpu_compiler/core/stream_compiler/binary_plan.py
compiler/gpdpu_compiler/core/stream_compiler/inst_writers.py
```

GEMM/ReLU/log10max：

```text
compiler/gpdpu_compiler/core/op_specs/matmul.py
compiler/gpdpu_compiler/core/op_specs/log10max.py
compiler/gpdpu_compiler/core/stream_compiler/gemm_demo.py
compiler/gpdpu_compiler/core/stream_compiler/relu_fiber_chain.py
compiler/gpdpu_compiler/core/stream_compiler/relu_binding.py
compiler/gpdpu_compiler/core/stream_compiler/log10max_fiber_chain.py
compiler/gpdpu_compiler/core/stream_compiler/log10max_collective_strategy.py
compiler/gpdpu_compiler/core/stream_compiler/log10max_template_pack.py
```

runtime/package:

```text
compiler/gpdpu_compiler/core/stream_compiler/operator_payload_assembly.py
compiler/gpdpu_compiler/core/program_runtime.py
compiler/gpdpu_compiler/core/stream_compiler/micc_component_writers.py
compiler/gpdpu_compiler/core/stream_compiler/binding.py
compiler/tools/check_bline_runtime_ready_preintegration.py
```

## 下一轮建议

建议继续并行三条：

```text
A. GEMM no-ReLU component assembly/runtime_ready
   输入：已 materialized raw inst_t rows/hash
   目标：payload files / manifest / local runtime_ready gate / uploadable candidate

B. ReLU exact HMAX row materializer
   输入：relu_tile production mapping + HMAX row slots
   目标：HMAX selector、zero constant、operand/local_order、raw bytes/hash

C. log10max PE00 row materializer/runtime proof
   输入：PE00 proof plans / vendor row intents / MICC intents
   目标：FMAX combine/store/readback raw rows、decoded MICC order、receiver roundtrip
```

主线程应继续做集成和架构守门。

## 禁止回退

后续继续遵守：

```text
不要恢复 sequential-K Fiber 主路径
不要把 ReLU 放进 GEMM fiber
不要使用 epilogue/fused post-op 表达 GEMM+ReLU
不要把 global_max/allreduce 藏进 package/bundle 语义
不要把 span hash 冒充 raw row hash
不要虚报 runtime_ready/uploadable
```

## 快速接手状态

```bash
cd /home/flecther/workspace/dpu_project
git log -5 --oneline
git status --short
PYTHONPATH=compiler:compiler/tools python compiler/tools/check_bline_runtime_ready_preintegration.py
```

预期：

```text
HEAD = e63ff0b Materialize B-line legacy inst_t rows
working tree clean
runtime_ready pre-integration final_state=blocked
gemm_no_relu=ready
gemm_relu=blocked
log10max=blocked
```
