# GEMM DTensor-first 地址自动规划路线

Status: active implementation plan.

## 核心判断

GEMM 地址自动规划不应该从 vendor base row、`conf.h` 公式或现有
`GemmPlanSpec` 地址常量开始。那些地址是结果，不是 source of truth。

OpenFabric 侧更可靠的入口是：

```text
DTensor / tile ownership / PE work partition
  -> 每个 PE 在每个 stage 读写哪些 tensor shard
  -> stage-visible tensor window
  -> runtime/static materialization request
  -> SPM/DDR/base-row/CSV/runtime descriptor projection
```

也就是说，地址映射应该是 tensor lowering 层的事情。GEMM 只是一个 op adapter：
它提供 A/B/C 的逻辑角色、M/N/K tile ownership 和计算阶段依赖，不应该拥有通用
materialization、external memory layout 或 runtime transfer descriptor 的规则。

## 当前已落地边界

公共层已经具备这些可复用积木：

```text
DTensor / DTensorTileRef
TensorAccessRef(read/write)
TensorAccessSpmBinding
RuntimeSpmWindowProjection
StageBaseRowProjection
TileMemoryAccess
TensorRuntimeMaterializationRequest
TensorRuntimeMaterializationAction
TensorRuntimeMaterializationWindowPlan
TensorExternalMemoryLayout
TensorExternalMemoryPlan
TensorWindowTransferProjection
TensorTaskAddressProjection
openfabric_runtime_plan_tensor_materialization_transfer(...)
openfabric_runtime_action_plan_add_tensor_materialization(...)
```

GEMM/GEMM+ReLU 已经完成的关键收敛：

```text
GEMM-local tile ownership shim 已删除
  -> 调用点直接使用 common matmul ownership / DTensor tile ref helper

runtime SPM window projection 已下沉
  -> TensorAccessRef + runtime_app_id + stride

runtime transfer projection 已下沉
  -> TensorRuntimeMaterializationRequest

runtime materialization action 已下沉
  -> GEMM loop 从 plan read/write access 动态生成 TensorRuntimeMaterializationAction

external DDR layout 已下沉
  -> TensorExternalMemoryPlan + plan read/write access 生成 TensorExternalMemoryLayout

runtime transfer direction 已下沉
  -> TensorAccessRef(Read/Write) 决定 MEM_TO_SPM/SPM_TO_MEM

task address projection 已开始下沉
  -> TensorTaskAddressProjection 按 TensorAccessRef 管理 PE/task 地址图
  -> matmul A/B/C 地址公式已移动到 common matmul lower helper
```

softmax/log10max 没有强行套入 GEMM 的 ping-pong materialization 模型；它们仍是
static window transfer，但已经复用 `TensorAccessRef -> transfer direction` 这条
公共事实。这一点很重要：公共抽象服务 tensor access 语义，不服务 GEMM 名字。

## 当前仍保留的 GEMM adapter

`GemmRuntimeTransferView` 过渡层和四个 `input0/input1/input2/output0` action factory
已删除。现在 GEMM 本地还保留的是 app/window schedule：

```text
app_batch_count / app_m / app_n / app_k loop
kernel wait/start slot policy
output writeback timing
```

这些仍是 GEMM op schedule，用来守住现有 vendor 调度和二进制对比安全绳。runtime
materialization 的 tensor 个数、read/write access 顺序、external DDR input/output
布局已经由 plan 推出。

当前仍未完全通用的是：

```text
input/output app_id 校验
output writeback 使用 producer app_id = app_id - 1
window index 来自 full_shape.cols / app_shape.cols
contiguous-channel vs strided-column 目前由 shape window 数推断
```

后续难点是把 app/window schedule 本身也从 GEMM spec 里提升成更通用的 runtime
iteration/window plan，而不是回到按 tensor 名字写 transfer。

## 主攻方向

### 1. Runtime materialization action 公共化

Status: landed for GEMM/GEMM+ReLU.

当前形态：

```text
TensorRuntimeMaterializationAction
  request: TensorRuntimeMaterializationRequest

TensorRuntimeMaterializationWindowPlan
  batch_count
  channel_count
  window_stride_bytes
```

runtime action sequencing 已经从 plan 动态生成并消费 action：

```text
tensor_runtime_materialization_read_actions_from_plan(...)
tensor_runtime_materialization_output_write_actions_from_plan(...)
openfabric_runtime_action_plan_add_tensor_materialization(...)
```

GEMM loop 只负责声明阶段顺序，不再声明有多少个 input：

```text
preload all read accesses
kernel wait/start
writeback all output accesses
```

不再手写 GEMM view 到 transfer 的最后一段 wiring。

已通过 GEMM/GEMM+ReLU syntax、runtime API trace、common executor trace 和 replay
package/support binary compare。

### 2. External memory layout 从 API trace 事实升级为 tensor binding plan

Status: first shared helper landed for GEMM/GEMM+ReLU.

现在 `TensorExternalMemoryPlan` 声明 input/output DDR base 和 batch count，
`TensorExternalMemoryLayout` 由 plan read/write access 推出：

```text
read accesses in tensor_access_base_slot_bindings order
  -> input DDR region

outputs by binding_index
  -> output DDR region
```

下一步还应把它升级成 operator contract / build input 的一部分：

```text
TensorAccessRef
  -> external memory scope
  -> base address policy
  -> byte extent
```

这样 softmax/log10max 也能从同一类 binding plan 生成 runtime transfer；当前它们
仍保留各自静态 flat/aligned transfer 逻辑。

风险：中。外部地址是 vendor-visible 行为，必须用 package/support binary compare
兜住。

### 3. StageBaseRowProjection 继续从 GEMM 分支中抽出

base row 本质上描述某个 stage instance 可见的 tensor window/scope，不应由 GEMM
subtask 分支手写。

目标形态：

```text
StageTensorWindowScope
  TensorAccessRef
  DTensorTileRef 或 tensor window ref
  element/vendor offset
  -> StageBaseRowProjection
```

GEMM 当前的 `derive_instance_base_row(...)` 可逐步变成：

```text
subtask/stage intent
  -> tensor window scopes
  -> common base-row projection
```

风险：中。会触达 instance config support binary，是重点安全绳区域。

### 4. CSV task address projection 抽成 tensor tile address binding

Status: first shared helper landed for GEMM/GEMM+ReLU.

`taskAddr_per_pe_A/B/C` 不再是 `GemmConfigProjection` 的固定字段；GEMM adapter
现在把 matmul 输入/输出角色绑定成 `TensorAccessRef -> TensorPeTaskAddressMap`。
PE/task 地址图由 common matmul lower helper 根据 plan mesh、tensor storage shape 和
matmul tile ownership 推出。

下一步目标是让 CSV memory refs 也消费同一组 tensor tile access：

```text
TensorAccessRef + DTensorTileRef + lane/instance
  -> TileMemoryAccess
  -> CSV slot/imm
```

这一步完成后，device lowering、address dump、base row、CSV task address 和 fiber
op memory refs 才会真正共享同一个 tile ownership source of truth。

风险：中高。已落地的第一层只改变 projection 的组织方式，并通过 GEMM/GEMM+ReLU
replay package/support binary compare。后续若继续改 CSV memory refs 或 fiber ops，
仍然需要小步改、每步 replay。

## 暂缓方向

以下方向有价值，但现在不主攻：

```text
plan -> fiber ops 自动映射
subtask partitioning 算法
COPYT / collective topology planning
log10max replay compare 升级
```

原因是这些会牵出更高层 scheduler 和客户验证状态。当前阶段先把底层 lowering
边界抽干净，让 runtime/static materialization、base row、CSV address binding
先能共享 tensor 事实。

## 安全绳

轻量门：

```sh
cmake --build build --target \
  gemm_refactored_syntax \
  gemm_relu_refactored_syntax \
  softmax_refactored_syntax \
  log10max_refactored_syntax
```

影响 vendor-visible package/support binary 时跑：

```sh
cmake --build build --target \
  refactored_replay_compare_gemm \
  refactored_replay_compare_gemm_relu \
  refactored_replay_compare_softmax
```

replay compare 已支持 vendor baseline cache。vendor 输入未变时应复用 baseline；
manifest 缺失、输入 hash 变化或必要产物缺失时才重建。

成功标准：

```text
同一个 DTensor/tensor access 事实
  能解释 runtime materialization window
  能解释 external memory base/offset
  能解释 stage base row
  能解释 CSV memory refs
  并且 vendor-visible binaries 保持对齐
```

## 近期下一刀建议

优先回到 base row 和 CSV task address projection。runtime materialization 和 external
layout 已经能从 plan access 推出，下一步应让 instance base row 与 CSV memory refs
也吃同一组 tensor access/tile/window 事实。
