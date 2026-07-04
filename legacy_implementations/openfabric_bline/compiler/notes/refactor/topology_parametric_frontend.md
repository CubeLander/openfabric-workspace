# DFU-First Frontend Refactor Principle

## Core conclusion

OpenFabric 当前阶段不以“一套代码同时兼容多个 backend”为项目目标。

当前目标是先把甲方 DFU 服务好：稳定生成、打包、上传、运行和验证
SimICT/GPDPU 所需的二进制与测试 bundle。CUDA/CANN 等其它后端只作为
以后做别的项目时可参考的架构思想，不进入当前交付路线，也不要求当前代码
提前为它们付复杂度成本。

因此当前 refactor 的目标不是抽象出一个宏大的多后端编译器，而是：

```text
DTensor-facing API
  ↓
DFU-oriented logical tile / fabric plan
  ↓
DFU physical lowering
  ↓
SimICT / GPDPU vendor artifacts
```

## Boundary we still want

虽然项目目标收束到 DFU-first，但仍然需要避免前端被低层 vendor ABI 污染。
这个边界不是为了马上支持 CUDA/CANN，而是为了让 DFU 交付本身更清楚、更可维护。

上层可以保留服务 DTensor 的逻辑拓扑和逻辑程序，例如：

```text
logical_fabric = grid(4, 4)
logical_axis = M / N / K
broadcast(A_tile, axis=row)
broadcast(B_tile, axis=col)
tile_gemm(A_tile, B_tile) -> C_tile
store(C_tile)
```

这些概念帮助我们描述 GEMM、tile 数据流、logical collective 和任务切分。
它们可以是 topology-aware，但应该是 DFU 交付所需的逻辑层描述，而不是直接等同
vendor 二进制 ABI。

上层不应该直接散落这些细节：

```text
instance_conf.base_addr
subtask_conf_info_t
exeBlock_conf_info_t
CBUF / MICC layout
inst_t field offsets
HMMAL instruction counts
```

这些仍然属于 DFU physical lowering / vendor serializer。

## Current implementation status

当前代码里，`OperatorEnv` 仍然会维护 PE program，并调用旧路径生成
`tile_backend`、DFU graph、packing、residency、vendor serializers。

这条链路已经能服务甲方 DFU bundle，不应该在当前阶段大拆大改。
我们已经把旧实现整体搬到：

```text
compiler/gpdpu_compiler/core_legacy/
```

并让：

```text
compiler/gpdpu_compiler/core/
```

先作为兼容 facade，继续支持旧 import，例如：

```text
gpdpu_compiler.core.env
gpdpu_compiler.core.dfu_vendor_inst_serializer
```

## Refactor direction

下一步的 refactor 应该围绕“让 DFU-first 代码更清楚”展开：

1. 保留当前可跑 DFU 流水线，不破坏 bundle 生成和 legacy GEMM compat。
2. 从 `core_legacy` 里逐步识别稳定 IR 边界，而不是一次性重写。
3. 新 `core` 优先承载面向 DTensor/DFU 的轻量逻辑结构：
   - logical tile value；
   - logical tile op；
   - logical collective；
   - logical fabric hint；
   - dependency/review surface。
4. PE、task、subtask、instance、CBUF、MICC、`inst_t` 等继续归入 DFU lowering。
5. 不新增 CUDA/CANN stub，不为了未来 backend 设计当前 API。

## How to treat multi-backend ideas

“抽象拓扑”“逻辑 fabric”“backend physical lowering”这些思想可以保留在脑子里，
也可以作为后续项目的参考。但它们不是当前 OpenFabric 的验收目标。

当前验收目标应写成：

```text
服务甲方 DFU / SimICT / GPDPU 工作流：
  - 生成 DFU 所需二进制；
  - 对齐 legacy GEMM 格式；
  - 打包可上传测试 bundle；
  - 保留可解释 debug/review surface；
  - 让后续 DFU 算子扩展更容易。
```

## Guiding sentence

Current code should continue serving the DFU customer delivery first.

> 先服务好甲方 DFU，不为了还不存在的 backend 牺牲当前实现清晰度。

