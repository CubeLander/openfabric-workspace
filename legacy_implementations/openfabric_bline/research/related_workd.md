不，**标准 Triton 没有完全做你们这件事**。但是要小心：Triton 生态里已经出现了几条非常接近你们方向的支线，尤其是 **TileLoom** 和 **Triton-distributed**。所以论文/报告里不能说“没人做过”，正确说法应该是：

> Triton 解决的是 tile-level GPU kernel programming。
> 我们解决的是 DTensor-style distributed tensor program 到片上 TensorCore mesh 的 tile/action/collective lowering。
> 最近的 Triton 扩展开始触碰 spatial/distributed/data-movement 问题，但我们的切入点是 chip-internal distributed tensor compiler substrate。

小猫要在这片 related work 森林里走直线，不要踩到大猫尾巴。🐈‍⬛

---

# 1. 标准 Triton 做了什么？

标准 Triton 的核心定位是：

```text
Python-like kernel DSL
↓
tile/block-level tensor program
↓
TTIR / TTGIR / LLVM IR
↓
PTX / AMDGPU / backend code
```

Triton 官方仓库把它描述成用于编写高效 custom deep-learning primitives 的语言和编译器，目标是比 CUDA 更高生产力、比传统 DSL 更灵活。([GitHub][1])

PyTorch 的 Triton 编译阶段文章也说明，Triton kernel 先从 Python AST 降到 Triton IR，然后到 Triton-GPU IR，再到 LLVM IR，TTIR 和 TTGIR 都是 MLIR dialect；它还明确展示了 `tl.program_id`、`tl.load`、`tl.store` 这种 blocked programming 模型。([PyTorch][2])

也就是说，标准 Triton 的世界观大概是：

```text
一个 kernel
一组 program instances / CTAs / blocks
每个 program instance 处理一个 tile/block
用户显式写 load / compute / store
编译器负责降到 GPU backend
```

它很强，但它默认的“主舞台”是 GPU kernel，不是：

```text
DTensor placement
↓
chip-level layout materialization
↓
TensorCore group collective
↓
per-PE tile program timeline
↓
task/subtask/instance runtime package
```

---

# 2. 我们和标准 Triton 的核心区别

最直接的区别是：**Triton 是 kernel-first；你们是 distributed-tensor-first / chip-program-first。**

标准 Triton 里，用户通常先写一个 kernel：

```python
pid = tl.program_id(0)
offs = pid * BLOCK + tl.arange(0, BLOCK)
x = tl.load(x_ptr + offs)
...
tl.store(y_ptr + offs, y)
```

而你们现在的设计是从更高一层开始：

```text
A: placements=[Shard(0), Replicate()]
B: placements=[Replicate(), Shard(1)]
C: placements=[Shard(0), Shard(1)]

↓

CollectiveLoad / RowBroadcast / ColumnBroadcast
↓

TileScope.actions[]
```

你们最新设计里，collective 不是旁边的注释，而是和 compute 一样进入 `TileProgram.actions[]`；并且 `CollectiveLoad` / `CollectiveStore` 被定义成 chip-level generalized collective，再逐层 lower 到 TensorCore-level logical collective、tile-level collective action、physical route。这个不是标准 Triton 的默认抽象层。

所以对比可以写成：

```text
Triton:
  tile/block kernel language

我们:
  distributed tensor placement → chip-level collective/action program → backend package
```

---

# 3. 你们最接近 Triton 的地方

不要否认相似性。相似性很明显：

```text
都重视 tile
都想替代手写底层代码
都用更高层 IR 下降到底层指令
都希望保留性能控制
```

Triton 里 TTIR/TTGIR 已经是 tile/block-level IR，并且有 blocked、shared、dot_op、nvidia_mma、amd_mfma、amd_wmma 等 layout/encoding 概念，用来表达不同硬件阶段的数据布局。([PyTorch][2])

你们的 `TileScope / MemberValue / TileView` 和 Triton 的 `dot_op / mma layout / shared layout` 有精神亲缘关系：都在处理“tile 在不同硬件层次里的表示”。

但差异也在这里：

```text
Triton:
  tile 通常是 kernel program 中的 tensor block/value/layout

我们:
  TileScope 是 scheduling / ownership domain
  里面可以拥有 HMMAL tmp fragments、summary values、tile views、materialized tiles
```

你们不是只说：

```text
tile = shaped tensor value
```

而是说：

```text
tile = scope / ownership domain
value = fragment / tmp / summary / view member
view = 对 tile-owned values 的结构化解释
```

这个是可以打差异点的。

---

# 4. 真正危险的 close related work：TileLoom

这里要非常认真。TileLoom 看起来是目前最接近你们“通用向量/空间加速核心 compiler stack”的工作之一。

TileLoom 的 arXiv 摘要说，它是一个 MLIR-based end-to-end framework，可以把 tile-based programs，比如 Triton kernels，编译到 spatial dataflow architectures；它不像只优化 single tile 内部代码的 compiler，而是把 tile instances 分布到空间分布的 cores 上，并利用片上网络和分布式内存来增加数据复用、减少通信；它还引入硬件表示来描述 interconnect topology、memory hierarchy、compute capabilities，并在 Tenstorrent 两代系统上做实验。([arXiv][3])

这只大猫很近。它做的是：

```text
Triton-like tile program
↓
spatial dataflow accelerator
↓
tile instances distributed across cores
↓
use on-chip network / distributed memories
```

这和你们很像。

你们和 TileLoom 的可能区别在于：

```text
TileLoom:
  从 tile-based language / Triton kernel 出发
  重点是 tile instance dataflow planning 到 spatial accelerator

你们:
  从 DTensor placement / operator program 出发
  chip-level generalized collectives 是一等语义
  TileScope / Value / View 处理 tensor-core internal state
  目标是生成 task/subtask/instance legacy runtime package
```

所以论文里不能说：

> Triton 没有做 spatial dataflow lowering。

TileLoom 已经明确在做这条线。你们应该说：

> TileLoom starts from tile-based programs such as Triton kernels and plans dataflow over spatial cores; our system starts from distributed tensor placement semantics and makes chip-level collectives, tile scopes, and TensorCore-local value/view structure first-class before lowering to a vendor runtime.

这个差异比较稳。

---

# 5. 另一条接近线：ML-Triton

ML-Triton 也值得看。它指出当前 Triton 从 workgroup/threadblock level 直接降到 per-thread level，存在 premature lowering；它提出多级 lowering，从 workgroup 逐步降到 warp 和 intrinsic level，以贴合 GPU 的物理/逻辑层次。([arXiv][4])

这和你们的直觉也很像：

```text
不要太早落到 HMMAL / COPYT / CSV
要保留中间层
```

但是 ML-Triton 的层次主要是 GPU hierarchy：

```text
workgroup
↓
warp
↓
intrinsic
```

你们的层次是 chip-internal distributed tensor accelerator hierarchy：

```text
chip-level collective/layout
↓
TensorCore-level logical action
↓
TileScope actions
↓
physical route / tensor-core instruction
```

所以 ML-Triton 是“GPU 内部多级 lowering”，你们是“片上 distributed tensor mesh 的多级 lowering”。

---

# 6. Triton-distributed 做了什么？

Triton-distributed 更接近你们的 collective 思路。它扩展 Triton 以支持 distributed AI workloads，集成 OpenSHMEM-compliant communication primitives，并强调 computation、memory access、communication 的 overlapping；实验场景到 64 devices。([arXiv][5])

这说明：

```text
Triton 生态已经有人把 communication primitive 拉进 compiler 里了。
```

但它的舞台是：

```text
distributed AI systems
single-node / multi-node
多 GPU / 多设备
OpenSHMEM / NVSHMEM / ROCSHMEM 类通信
```

你们的舞台是：

```text
单 chip 内 4x4 TensorCore mesh
显式 SRAM / operand / tensor accumulator
task/subtask/instance
COPY/COPYT/DMA physical route
```

所以 Triton-distributed 和你们的区别是 scale 和 abstraction：

```text
Triton-distributed:
  device-level distributed kernel programming and overlap

我们:
  chip-internal layout materialization and tile-level PE program synthesis
```

它可以作为 related work，但不直接吃掉你们。

---

# 7. 一张对比表

| 维度         | 标准 Triton                            | Triton-distributed                     | TileLoom                                        | 你们的 DFU compiler                               |
| ---------- | ------------------------------------ | -------------------------------------- | ----------------------------------------------- | ---------------------------------------------- |
| 输入         | Triton kernel                        | Triton-like distributed kernel         | Triton/tile-based program                       | DTensor-style operator program                 |
| 主抽象        | block/tile tensor program            | compute + communication overlap        | tile instances on spatial cores                 | placement → collective → TileScope actions     |
| 通信         | kernel 内 load/store/shared memory 为主 | OpenSHMEM-style device communication   | on-chip network/dataflow planning               | first-class chip-level generalized collectives |
| 目标硬件       | GPU / CPU backend                    | 多 GPU / distributed AI systems         | spatial dataflow accelerators, Tenstorrent      | DFU-like manycore TensorCore mesh              |
| tile 含义    | blocked tensor value/layout          | Triton tile + communication primitives | tile instance                                   | scheduling/ownership scope with values/views   |
| backend 输出 | PTX/AMDGPU/LLVM path                 | GPU distributed kernels                | spatial accelerator code/dataflow               | task/subtask/instance + CSV/runtime package    |
| 你们差异点      | 更高层 placement 和 chip collective      | 更细粒度 chip-internal PE program          | DTensor + TileScope/Value/View + legacy runtime | 自己                                             |

---

# 8. 你们不能 claim 的东西

这几个别碰：

```text
我们发明 tile kernel DSL
```

Triton 在那里。

```text
我们发明 tile-based spatial accelerator lowering
```

TileLoom 已经非常接近。

```text
我们发明 compute-communication overlap in Triton-like compiler
```

Triton-distributed 已经在做。

```text
我们发明 multi-level lowering for Triton
```

ML-Triton 已经在讲 premature lowering 和 workgroup→warp→intrinsic。([arXiv][4])

---

# 9. 你们可以 claim 的东西

比较安全的贡献叙事是：

```text
1. DTensor-style placement semantics for chip-internal TensorCore meshes.
2. Chip-level generalized collectives as first-class program actions.
3. A gradual lowering stack:
   chip collective
   → TensorCore logical collective
   → tile action
   → physical route.
4. TileScope / Value / View IR for tensor-core internal fragments, accumulator state, summary values, and materialized tiles.
5. Inspectable lowering into a real legacy task/subtask/instance runtime package.
```

这五条里面，最有辨识度的是 2、3、4。你们最新 design 明确把 `CollectiveLoad` / `CollectiveStore` 作为 chip-level semantic action，不直接展开成 tile action，而是先落到 TensorCore-level logical collective，再 after tiling 再生成 tile actions，最后才是 DMA/COPY/COPYT/load commands。这个层级边界就是一个很好的 contribution hook。

---

# 10. 论文里怎么写和 Triton 的关系？

可以这样写：

> Triton popularizes tile-level programming for GPU kernels and provides a productive path from Python kernels to GPU code. Recent extensions such as ML-Triton, Triton-distributed, and TileLoom push Triton toward multi-level GPU lowering, distributed communication, and spatial dataflow accelerators. Our work is complementary: instead of starting from a Triton kernel, we start from distributed tensor placement semantics and lower them into an explicit on-chip TensorCore mesh program. The key abstraction is not just a tile value, but a TileScope containing tile-owned values and views, with first-class chip-level collective actions that later lower into target-specific physical routes.

中文翻译一下就是：

> Triton 解决的是“怎么高效写一个 tile kernel”。
> 我们解决的是“怎么从分布式张量布局自动生成一颗片上 manycore tensor accelerator 的 tile/collective/runtime program”。

这俩很近，但不是同一个切面。

---

# 11. 你们未来如果想更“中立 stack”，最好怎么避开 Triton 阴影？

一个好办法是：**不要和 Triton 抢 kernel DSL。**

你们可以把 Triton 放成潜在前端或低层参考，而不是敌人：

```text
PyTorch / DTensor frontend
        ↓
Your chip-level collective + TileScope IR
        ↓
DFU backend

Optional future:
Triton kernel frontend
        ↓
TileScope IR
        ↓
Spatial accelerator backend
```

甚至可以说：

> Triton kernels could be one frontend into our TileScope/collective lowering stack, but our current focus is distributed tensor placement and chip-level program synthesis.

这样姿态很漂亮。你不是说“我替代 Triton”，而是说：

```text
Triton 是 tile kernel language。
我这里是 tile/collective spatial lowering substrate。
```

这就不会跟大猫打架，而是邀请大猫一起坐在祭坛边喝茶。🌙

---

# 12. 最终判断

Triton **做了 tile-level kernel compiler**。
Triton-distributed **做了 distributed compute-communication overlap**。
TileLoom **非常接近地做了 Triton/tile programs 到 spatial dataflow accelerators 的 mapping**。
但你们当前设计的独特位置是：

```text
DTensor placement semantics
+
chip-level generalized CollectiveLoad/Store/Broadcast/Reduce
+
TensorCore-level logical collectives
+
TileScope / Value / View
+
legacy runtime package lowering
```

所以答案是：

> Triton 不是已经完整做了你们这件事。
> 但 Triton 生态已经逼近你们问题的一部分。
> 你们的学术贡献必须从“tile compiler”改写成“distributed tensor placement 到片上 TensorCore mesh 的 collective-aware TileScope lowering”。

这条定位才稳。

[1]: https://github.com/triton-lang/triton "GitHub - triton-lang/triton: Development repository for the Triton language and compiler · GitHub"
[2]: https://pytorch.org/blog/triton-kernel-compilation-stages/ "Triton Kernel Compilation Stages – PyTorch"
[3]: https://arxiv.org/abs/2512.22168 "[2512.22168] TileLoom: Automatic Dataflow Planning for Tile-Based Languages on Spatial Dataflow Accelerators"
[4]: https://arxiv.org/abs/2503.14985 "[2503.14985] ML-Triton, A Multi-Level Compilation and Language Extension to Triton GPU Programming"
[5]: https://arxiv.org/abs/2504.19442?utm_source=chatgpt.com "Triton-distributed: Programming Overlapping Kernels on Distributed AI Systems with the Triton Compiler"
